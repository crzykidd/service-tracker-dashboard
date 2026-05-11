# Config
# Standard library
import os
import json
import threading
import time
import sqlite3
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
import requests
import humanize
import yaml
from dateutil import parser
from flask import Flask, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger


# Local application modules
from extensions import db, login_manager
from settings_loader import load_settings
from image_utils import fetch_icon_if_missing
from models import Group, ServiceEntry, User, Widget, WidgetValue
from health import health_bp
from routes_auth import auth_bp
from routes_widgets import widgets_bp
from routes_dashboard import dashboard_bp
from routes_api import api_bp


DATABASE_PATH = '/config/services.db'
LOGFILE = '/config/std.log'
IMAGE_DIR = '/config/images'
IS_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# === Logging Setup ===
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')

log_handler = RotatingFileHandler(LOGFILE, maxBytes=10 * 1024 * 1024, backupCount=4)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG if IS_DEBUG else logging.INFO)
logger.addHandler(log_handler)
logger.addHandler(console_handler)

# Load settings before app config
settings, config_from_env, config_from_file = load_settings()

app = Flask(__name__)
app.debug = IS_DEBUG
app.secret_key = os.getenv("FLASK_SECRET_KEY", "changeme-in-prod")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=int(settings.get("user_session_length", 120)))

login_manager.init_app(app)

db.init_app(app)

app.register_blueprint(health_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(widgets_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(api_bp)


@app.context_processor
def inject_now():
    return {'now': datetime.now}

# Set STD_DOZZLE_URL from environment first, fallback to settings file
app.config['std_dozzle_url'] = os.getenv("STD_DOZZLE_URL", settings.get("STD_DOZZLE_URL", ""))


logger.info("🔧 Loaded settings:")
for k, v in settings.items():
    logger.info(f"    {k} = {v}")

app.config.update(settings)
# Snapshot the full loaded dict for the /settings page to render. The page
# iterates current_config to display every loaded key, so we can't just
# point it at app.config (that also holds Flask-internal keys).
app.config['LOADED_SETTINGS'] = settings
app.config['IMAGE_DIR'] = IMAGE_DIR
app.config['CONFIG_FROM_ENV'] = config_from_env
app.config['CONFIG_FROM_FILE'] = config_from_file

logger.info("⚙️ Flask config (from settings):")
for k in settings:
    logger.info(f"    {k} = {app.config.get(k)}")

def read_version_info():
    try:
        with open("/app/version.txt", "r") as f:
            return dict(line.strip().split("=", 1) for line in f)
    except Exception as e:
        logger.warning(f"⚠️ Could not read version info: {e}")
        return {
            "version": "unknown",
            "commit": "unknown",
            "build_time": "unknown"
        }

# Cache once at startup. The /settings page reads this from app.config.
app.config['VERSION_INFO'] = read_version_info()

# Ensure the directory exists
os.makedirs(IMAGE_DIR, exist_ok=True)


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


scheduler = BackgroundScheduler()


@app.errorhandler(403)
def forbidden_error(error):
    return render_template("403.html"), 403

def update_widget_data_periodically():
    with app.app_context():
        widgets = Widget.query.all()

        for widget in widgets:  # ✅ Now inside context
            print(f"🔄 Running widget fetch for: {widget.widget_name} ({widget.id})")
            try:
                widget_key = widget.widget_name  # 💡 Use widget_name, not widget_key
                widget_dir = os.path.join('widgets', widget_key)
                settings_path = os.path.join(widget_dir, 'settings.json')

                if not os.path.exists(settings_path):
                    print(f"⚠️ Missing settings.json for widget '{widget_key}'")
                    continue

                with open(settings_path, 'r') as f:
                    settings = json.load(f)

                available_fields = settings.get("available_fields", [])
                requested_fields = widget.widget_fields
                api_url = widget.widget_url
                api_key = widget.widget_api_key

                try:
                    import importlib
                    module = importlib.import_module(f"widgets.{widget_key}.fetch_data")
                    fetch_func = getattr(module, "fetch_widget_data")
                    data = fetch_func(api_url, api_key, requested_fields, available_fields)
                except Exception as e:
                    print(f"❌ Failed to load widget fetcher for '{widget_key}': {e}")
                    continue

                if isinstance(data, dict) and "error" in data:
                    print(f"❌ Error fetching data for widget {widget.id}: {data['error']}")
                    continue

                for key, value in data.items():
                    widget_value = WidgetValue.query.filter_by(widget_id=widget.id, widget_value_key=key).first()

                    if not widget_value:
                        widget_value = WidgetValue(
                            widget_id=widget.id,
                            widget_value_key=key,
                            widget_value=str(value),
                            last_updated=datetime.utcnow()
                        )
                        db.session.add(widget_value)
                    else:
                        widget_value.widget_value = str(value)
                        widget_value.last_updated = datetime.utcnow()

                db.session.commit()
                print(f"✅ Updated values for widget {widget_key} (ID: {widget.id})")

            except Exception as e:
                print(f"🔥 Exception while processing widget {widget.id}: {str(e)}")

        




# Background health check loop
def health_check_loop():
    URL_HEALTHCHECK_INTERVAL = app.config.get("url_healthcheck_interval", 60)

    with app.app_context():
        iteration = 0
        while True:
            time.sleep(URL_HEALTHCHECK_INTERVAL)
            iteration += 1
            try:
                log_output = ["\U0001f504 Running internal health checks..."]
                entries = ServiceEntry.query.all()

                for entry in entries:
                    show_log = False
                    internal_status = ""
                    external_status = ""

                    if entry.internal_health_check_enabled and entry.internalurl:
                        show_log = True
                        try:
                            response = requests.get(entry.internalurl, timeout=5)
                            internal_status = str(response.status_code)
                            entry.internal_health_check_status = internal_status
                        except Exception as e:
                            internal_status = f"Error: {type(e).__name__}"
                            entry.internal_health_check_status = internal_status
                        entry.internal_health_check_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    if entry.external_health_check_enabled and entry.externalurl:
                        show_log = True
                        try:
                            response = requests.get(entry.externalurl, timeout=5)
                            external_status = str(response.status_code)
                            entry.external_health_check_status = external_status
                        except Exception as e:
                            external_status = f"Error: {type(e).__name__}"
                            entry.external_health_check_status = external_status
                        entry.external_health_check_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    if show_log:
                        log_output.append(f"{entry.container_name} - Internal: {internal_status or 'N/A'} External: {external_status or 'N/A'}")

                db.session.commit()
                for line in log_output:
                    logger.info(line)
            except Exception:
                # Safety net: keep the worker thread alive across unexpected
                # failures (DB errors, surprise requests exceptions, etc.).
                service_count = len(entries) if "entries" in locals() else -1
                logger.exception(
                    "Health-check iteration %d failed (services=%d); continuing.",
                    iteration,
                    service_count,
                )
                try:
                    db.session.rollback()
                except Exception:
                    logger.exception("Failed to roll back session after health-check error")


def run_scheduled_backup():
    with app.app_context():
        backup_dir = app.config.get("backup_path", "/config/backups")
        days_to_keep = int(app.config.get("backup_days_to_keep", 7))

        os.makedirs(backup_dir, exist_ok=True)

        filename = datetime.now().strftime("%Y-%m-%d-std_backup.yml")
        full_path = os.path.join(backup_dir, filename)

        try:
            entries = ServiceEntry.query.all()
            data = [e.to_dict() for e in entries]
            with open(full_path, 'w') as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            logger.info(f"🌙 Scheduled backup saved to {full_path}")
        except Exception as e:
            logger.error(f"❌ Scheduled backup failed: {e}")

        # Cleanup
        now = time.time()
        cutoff = now - (days_to_keep * 86400)
        removed = 0
        for fname in os.listdir(backup_dir):
            if fname.endswith("-std_backup.yml"):
                fpath = os.path.join(backup_dir, fname)
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    try:
                        os.remove(fpath)
                        logger.info(f"🧹 Removed old backup: {fname}")
                        removed += 1
                    except Exception as e:
                        logger.warning(f"⚠️ Could not remove old backup {fname}: {e}")
        if removed:
            logger.info(f"🧹 Removed {removed} expired backup(s) from {backup_dir}")



app.debug = os.environ.get("FLASK_DEBUG", "0") == "1"

version_info = app.config['VERSION_INFO']
logger.info(f"🚀 Service Tracker Dashboard Starting...")
logger.info(f"📦 Version: {version_info.get('version', 'unknown')}")
logger.info(f"🔀 Commit: {version_info.get('commit', 'unknown')}")
logger.info(f"⏱️ Build Time: {version_info.get('build_time', 'unknown')}")

# Check images at startup
def verify_and_fetch_missing_icons():
    logger.info("🔍 Verifying icon files for all ServiceEntry records...")
    with app.app_context():
        entries = ServiceEntry.query.all()
        missing_count = 0
        for entry in entries:
            icon = entry.image_icon
            if icon:
                icon_path = os.path.join(IMAGE_DIR, icon)
                if not os.path.exists(icon_path):
                    logger.warning(f"🚫 Missing icon: {icon} — attempting download...")
                    fetched = fetch_icon_if_missing(icon, IMAGE_DIR, logger, debug=app.debug)
                    if fetched:
                        logger.info(f"✅ Successfully fetched missing icon: {fetched}")
                    else:
                        logger.error(f"❌ Failed to download icon: {icon}")
                        missing_count += 1
        logger.info(f"🔁 Icon verification complete. Missing count: {missing_count}")

def start_background_workers():
    scheduler = BackgroundScheduler()
    reload_seconds = app.config.get("widget_background_reload")
    if not isinstance(reload_seconds, int) or reload_seconds <= 0:
        reload_seconds = 300  # default fallback
    scheduler.add_job(
        update_widget_data_periodically,
        IntervalTrigger(seconds=reload_seconds),
        id='widget_data_update_job',
        name='Update widget values periodically',
        replace_existing=True
    )
    scheduler.add_job(
        run_scheduled_backup,
        CronTrigger(hour=0, minute=5),
        id='scheduled_backup_job',
        name='Run daily backup',
        replace_existing=True
    )
    scheduler.start()

    threading.Thread(target=health_check_loop, daemon=True).start()

def create_default_admin():
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

if __name__ == '__main__':
    create_default_admin()
    logger.info("🔍 Verifying icon files for all ServiceEntry records...")
    verify_and_fetch_missing_icons()

    # In Werkzeug's debug reloader the script runs twice (supervisor + child).
    # Only the child (WERKZEUG_RUN_MAIN=true) should own the workers.
    if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_background_workers()

    logger.info(f"🚀 Starting app (debug={app.debug}) on port 8815")
    app.run(host='0.0.0.0', port=8815, debug=app.debug)
 