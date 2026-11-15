"""Service Tracker Dashboard — Flask app factory.

`create_app()` builds and returns the Flask app: loads settings,
binds extensions, registers blueprints, error handlers, context
processors, and template filters. It does NOT start background
workers — run_startup_tasks() (called from __main__ or the gunicorn
post_worker_init hook) is responsible for that,
so importing this module is side-effect-light enough to allow
alembic and ad-hoc scripts to grab `app` without spawning threads.
"""

import logging
import os
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse

import humanize
from dateutil import parser
from flask import Flask, flash, jsonify, redirect, render_template, request
from flask_wtf.csrf import CSRFError

from extensions import csrf, db, login_manager
from health import health_bp
from jobs import start_background_workers, verify_and_fetch_missing_icons
from models import User
from routes_api import api_bp
from routes_auth import auth_bp, refresh_default_password_flag
from routes_dashboard import dashboard_bp
from routes_widgets import widgets_bp
from settings_loader import CONFIG_DIR, load_settings, mask_value
from view_helpers import safe_redirect_target

DATABASE_PATH = os.path.join(CONFIG_DIR, 'services.db')
LOGFILE = os.path.join(CONFIG_DIR, 'std.log')
IMAGE_DIR = os.path.join(CONFIG_DIR, 'images')
IS_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

logger = logging.getLogger(__name__)


def _configure_logging():
    log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')

    log_handler = RotatingFileHandler(LOGFILE, maxBytes=10 * 1024 * 1024, backupCount=4)
    log_handler.setFormatter(log_formatter)
    log_handler.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    console_handler.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)
    root_logger.addHandler(log_handler)
    root_logger.addHandler(console_handler)


def read_version_info():
    try:
        with open("/app/version.txt", "r") as f:
            return dict(line.strip().split("=", 1) for line in f)
    except Exception as e:
        logger.warning(f"⚠️ Could not read version info: {e}")
        # Local run (no image build): fall back to the repo's VERSION file.
        version = "unknown"
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")) as vf:
                version = vf.read().strip() or "unknown"
        except OSError:
            pass
        return {
            "version": version,
            "commit": "unknown",
            "build_time": "unknown"
        }


def create_app():
    _configure_logging()

    settings, config_from_env, config_from_file = load_settings()

    app = Flask(__name__)
    app.debug = IS_DEBUG
    app.secret_key = os.getenv("FLASK_SECRET_KEY") or "changeme-in-prod"
    app.config['DEFAULT_SECRET_KEY_IN_USE'] = not os.getenv("FLASK_SECRET_KEY")
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=int(settings.get("user_session_length", 120)))

    # Tokens live as long as the session so a dashboard left open for hours
    # doesn't 400 on the next delete.
    app.config['WTF_CSRF_TIME_LIMIT'] = None
    csrf.init_app(app)
    login_manager.init_app(app)
    db.init_app(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(widgets_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(api_bp)

    app.config['std_dozzle_url'] = os.getenv("STD_DOZZLE_URL", settings.get("STD_DOZZLE_URL", ""))

    logger.info("🔧 Loaded settings:")
    for k, v in settings.items():
        logger.info(f"    {k} = {mask_value(k, v)}")

    app.config.update(settings)
    # Snapshot the full loaded dict for the /settings page to render. The page
    # iterates current_config to display every loaded key, so we can't just
    # point it at app.config (that also holds Flask-internal keys).
    app.config['LOADED_SETTINGS'] = settings
    app.config['IMAGE_DIR'] = IMAGE_DIR
    app.config['CONFIG_FROM_ENV'] = config_from_env
    app.config['CONFIG_FROM_FILE'] = config_from_file
    app.config['VERSION_INFO'] = read_version_info()

    # Validate register_field_ownership once at startup. An operator
    # typo would otherwise silently behave as user_wins per the
    # upsert_service default; logging it makes the misconfig visible.
    _valid_ownership_modes = {"user_wins", "notifier_wins"}
    ownership_mode = app.config.get("register_field_ownership", "user_wins")
    if ownership_mode not in _valid_ownership_modes:
        logger.warning(
            f"⚠️ Invalid register_field_ownership={ownership_mode!r}; "
            f"falling back to 'user_wins'. Valid values: "
            f"{sorted(_valid_ownership_modes)}."
        )
        app.config['register_field_ownership'] = "user_wins"

    logger.info("⚙️ Flask config (from settings):")
    for k in settings:
        logger.info(f"    {k} = {mask_value(k, app.config.get(k))}")

    if not app.config.get("api_token"):
        logger.warning(
            "⚠️ API_TOKEN is not set: /api/v1/register will return 503 "
            "until api_token is configured."
        )
    if app.config['DEFAULT_SECRET_KEY_IN_USE']:
        logger.warning(
            "⚠️ FLASK_SECRET_KEY is not set: using the built-in default to sign "
            "sessions. Set FLASK_SECRET_KEY to a long random value."
        )
    refresh_default_password_flag(app)

    os.makedirs(IMAGE_DIR, exist_ok=True)

    @app.context_processor
    def inject_globals():
        return {
            'now': datetime.now,
            'version_info': app.config['VERSION_INFO'],
        }

    @app.template_filter('time_since')
    def time_since(dt):
        if not dt:
            return "never"
        if isinstance(dt, str):
            dt = parser.parse(dt)
        now = datetime.now().astimezone()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=now.tzinfo)
        return humanize.naturaltime(now - dt)

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        wants_json = (
            request.is_json
            or request.path.startswith("/api/")
            or request.headers.get("X-CSRFToken") is not None
            or "application/json" in request.headers.get("Accept", "")
        )
        if wants_json:
            return jsonify({"error": "CSRF token missing or invalid"}), 400
        flash("Your session expired or the form was stale; please retry.", "danger")
        # request.referrer is an absolute URL; keep only its same-site path.
        ref = urlparse(request.referrer or "")
        target = ref.path + (f"?{ref.query}" if ref.query else "")
        return redirect(safe_redirect_target(target))

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template("403.html"), 403

    version_info = app.config['VERSION_INFO']
    logger.info("🚀 Service Tracker Dashboard Starting...")
    logger.info(f"📦 Version: {version_info.get('version', 'unknown')}")
    logger.info(f"🔀 Commit: {version_info.get('commit', 'unknown')}")
    logger.info(f"⏱️ Build Time: {version_info.get('build_time', 'unknown')}")

    return app


def create_default_admin(app):
    with app.app_context():
        existing_admin = User.query.filter_by(username="admin").first()
        if not existing_admin:
            admin = User(
                username="admin",
                email="admin@example.com",
                is_admin=True,
                is_active=True
            )
            admin.set_password("changeme123")
            db.session.add(admin)
            db.session.commit()
            logger.info("🛠️ Default admin user created (username: admin, password: changeme123)")
        else:
            logger.info("👤 Admin user already exists.")
    refresh_default_password_flag(app)


app = create_app()


_startup_done = False


def run_startup_tasks(app):
    """Default admin, icon sweep, and background workers (scheduler + health
    thread). Idempotent within a process: a second call is a no-op, so the
    scheduler and health thread can never be started twice."""
    global _startup_done
    if _startup_done:
        return
    _startup_done = True
    create_default_admin(app)
    verify_and_fetch_missing_icons(app)
    start_background_workers(app)


if __name__ == '__main__':
    # In Werkzeug's debug reloader the script runs twice (supervisor + child).
    # Only the child (WERKZEUG_RUN_MAIN=true) should own the workers.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        run_startup_tasks(app)

    logger.info(f"🚀 Starting app (debug={app.debug}) on port 8815")
    app.run(host='0.0.0.0', port=8815, debug=app.debug)
