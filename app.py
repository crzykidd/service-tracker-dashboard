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
from collections import defaultdict
from urllib.parse import urlparse, urljoin
import requests
import humanize
import yaml
from dateutil import parser
from flask import Flask, request, send_file, flash, jsonify, render_template, redirect, url_for, send_from_directory, make_response, session, abort
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import joinedload, column_property
from sqlalchemy import select, func, asc, desc, nullslast


# Local application modules
from extensions import db
from settings_loader import load_settings
from image_utils import resolve_image_metadata, parse_bool, fetch_icon_if_missing


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
unauthorized_log_tracker = {}

# Load settings before app config
settings, config_from_env, config_from_file = load_settings()

app = Flask(__name__)
app.debug = IS_DEBUG
app.secret_key = os.getenv("FLASK_SECRET_KEY", "changeme-in-prod")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=int(settings.get("user_session_length", 120)))

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'



@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

from flask_login import current_user

db.init_app(app)


def is_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return login_manager.unauthorized()
        if not current_user.is_admin:
            abort(403)  # Forbidden
        return f(*args, **kwargs)
    return decorated_function

@app.context_processor
def inject_now():
    return {'now': datetime.now}

settings, config_from_env, config_from_file = load_settings()
# Set STD_DOZZLE_URL from environment first, fallback to settings file
app.config['std_dozzle_url'] = os.getenv("STD_DOZZLE_URL", settings.get("STD_DOZZLE_URL", ""))


logger.info("🔧 Loaded settings:")
for k, v in settings.items():
    logger.info(f"    {k} = {v}")

# Optionally populate into app.config if you use `Flask config`
app.config.update(settings)

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
# Ensure the directory exists
os.makedirs(IMAGE_DIR, exist_ok=True)

# for image lookup
failed_icon_cache = {}  # image_icon -> last_failed_time
RETRY_INTERVAL = timedelta(minutes=60)  # Adjust this as needed


class ServiceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(100), nullable=False)
    container_name = db.Column(db.String(100), nullable=False)
    container_id = db.Column(db.String(100), nullable=True)
    internalurl = db.Column(db.String(255), nullable=True)
    externalurl = db.Column(db.String(255), nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False)
    last_api_update = db.Column(db.DateTime, nullable=True)  # <-- Add this line
    stack_name = db.Column(db.String(100), nullable=True)
    docker_status = db.Column(db.String(100), nullable=True)
    internal_health_check_enabled = db.Column(db.Boolean, nullable=True)
    internal_health_check_status = db.Column(db.String(100), nullable=True)
    internal_health_check_update = db.Column(db.String(100), nullable=True)
    external_health_check_enabled = db.Column(db.Boolean, nullable=True)
    external_health_check_status = db.Column(db.String(100), nullable=True)
    external_health_check_update = db.Column(db.String(100), nullable=True)
    image_registry = db.Column(db.String(100), nullable=True)
    image_owner = db.Column(db.String(100), nullable=True)
    image_name = db.Column(db.String(100), nullable=True)
    image_tag = db.Column(db.String(100), nullable=True)
    image_icon = db.Column(db.String(100), nullable=True)
    is_static = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.String(100), nullable=True)  # stored in ISO string format
    widget_id = db.Column(db.Integer, db.ForeignKey('widget.id'), nullable=True)
    widget = db.relationship('Widget', backref='services', lazy=True)
    sort_priority = db.Column(db.Integer, nullable=True, default=None)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)

# fields for backup
    def to_dict(self):
        data = {
            'stack_name': self.stack_name,
            'host': self.host,
            'container_name': self.container_name,
            'container_id': self.container_id,
            'internalurl': self.internalurl,
            'externalurl': self.externalurl,
            'last_updated': self.last_updated.strftime('%Y-%m-%d %H:%M:%S'),
            'last_api_update': self.last_api_update.strftime('%Y-%m-%d %H:%M:%S') if self.last_api_update else None,
            'docker_status': self.docker_status,
            'internal_health_check_enabled': self.internal_health_check_enabled,
            'internal_health_check_status': self.internal_health_check_status,
            'internal_health_check_update': self.internal_health_check_update,
            'external_health_check_enabled': self.external_health_check_enabled,
            'external_health_check_status': self.external_health_check_status,
            'external_health_check_update': self.external_health_check_update,
            'image_registry': self.image_registry,
            'image_owner': self.image_owner,
            'image_name': self.image_name,
            'image_tag': self.image_tag,
            'started_at': self.started_at,
            'image_icon': self.image_icon,
            'is_static': self.is_static,
            'sort_priority': self.sort_priority,
            
        }

        # Add inline widget info if attached
        if self.widget:
            data['widget'] = {
                'widget_name': self.widget.widget_name,
                'widget_url': self.widget.widget_url,
                'widget_fields': self.widget.widget_fields,
                'widget_api_key': self.widget.widget_api_key,
            }

        return data


class Widget(db.Model):
    __tablename__ = 'widget'

    id = db.Column(db.Integer, primary_key=True)
    widget_name = db.Column(db.String(255), nullable=False)
    widget_url = db.Column(db.String(255), nullable=False)
    widget_fields = db.Column(db.JSON, nullable=False)  # Store the fields as a JSON list
    widget_api_key = db.Column(db.String(255), nullable=True)  # New column for widget API key

    def __repr__(self):
        return f'<Widget {self.widget_name}>'
    
class WidgetValue(db.Model):
    __tablename__ = 'widget_value'

    id = db.Column(db.Integer, primary_key=True)
    widget_id = db.Column(db.Integer, db.ForeignKey('widget.id'), nullable=False)  # Foreign key to widget.id
    widget_value_key = db.Column(db.String(255), nullable=False)
    widget_value = db.Column(db.String(255), nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    widget = db.relationship('Widget', backref=db.backref('widget_values', lazy=True))

    def __repr__(self):
        return f'<WidgetValue {self.widget_id}, {self.widget_value_key}>'    

class Group(db.Model):
    __tablename__ = 'group'

    id = db.Column(db.Integer, primary_key=True)
    group_name = db.Column(db.String(100), unique=True, nullable=False)
    group_sort_priority = db.Column(db.Integer, nullable=True, default=None)
    group_icon = db.Column(db.String(255), nullable=True)

    services = db.relationship('ServiceEntry', backref='group', lazy=True)

    services_count = column_property(
        select(func.count(ServiceEntry.id))
        .where(ServiceEntry.group_id == id)
        .correlate_except(ServiceEntry)
        .scalar_subquery()
    )

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    
    # Basic info
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    # Security & status
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)

    # Audit fields
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login_at = db.Column(db.DateTime)
    password_changed_at = db.Column(db.DateTime)

    # OAuth fields
    oauth_provider = db.Column(db.String(64), nullable=True)
    oauth_id = db.Column(db.String(128), nullable=True)

    # API session/token field (e.g., for internal API calls or bearer auth)
    session_token = db.Column(db.String(128), unique=True, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def generate_session_token(self):
        import secrets
        self.session_token = secrets.token_urlsafe(64)


# Add this inside the ServiceEntry class in your app.py

    @property
    def is_docker_status_stale(self):
        if self.is_static:  # Static entries might not receive frequent API updates
            return False
        if self.last_api_update:
            # Consider stale if last_api_update is older than 5 minutes
            return (datetime.now() - self.last_api_update) > timedelta(minutes=5)
        # If no API update has ever been recorded, and it's not static, consider it stale or unknown.
        # For a newly added dynamic entry, this would be True until the first API update.
        return True

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


@app.route('/')
@login_required
def dashboard():

    sort = request.args.get('sort', 'group_name')
    direction = request.args.get('dir', 'asc')
    group_by = request.args.get('group_by', 'group_name')
    sort_in_group = request.args.get('sort_in_group', 'priority')  # default to priority
    msg = request.args.get('msg')

    sort = request.args.get('sort', 'group_name')
    direction = request.args.get('dir', 'asc')

    if sort == 'group_name':
        # Join to Group and sort by group.group_name
        query = ServiceEntry.query.options(joinedload(ServiceEntry.group)) \
            .join(Group, isouter=True) \
            .order_by(asc(Group.group_name) if direction == 'asc' else desc(Group.group_name))
    else:
        sort_attr = getattr(ServiceEntry, sort, None)
        if not sort_attr:
            sort_attr = ServiceEntry.container_name
        query = ServiceEntry.query.order_by(sort_attr.asc() if direction == 'asc' else sort_attr.desc())

    entries = query.all()

    # Group lookup for ID → name
    groups = Group.query.all()
    group_lookup = {g.id: g.group_name for g in groups}

    # Widget values
    widget_value_rows = WidgetValue.query.all()
    widget_values = {}
    for wv in widget_value_rows:
        if wv.widget_id not in widget_values:
            widget_values[wv.widget_id] = {}
        widget_values[wv.widget_id][wv.widget_value_key] = wv.widget_value

    # Group entries by group_id (not group_name) so the template lookup works
    grouped_entries = defaultdict(list)
    for entry in entries:
        if group_by == 'group_name':
            raw_key = entry.group_id  # group by ID for name lookup
        elif group_by == 'is_static':
            raw_key = "Static" if entry.is_static else "Dynamic"
        else:
            raw_key = getattr(entry, group_by)
            raw_key = str(raw_key) if raw_key is not None else "None"

        grouped_entries[raw_key].append(entry)

    # Sort entries within each group
    for key in grouped_entries:
        if sort_in_group == 'alphabetical':
            grouped_entries[key].sort(key=lambda e: e.container_name.lower())
        else:  # default to priority
            grouped_entries[key].sort(key=lambda e: (
                e.sort_priority if e.sort_priority is not None else 9999,
                e.container_name.lower()
            ))

    # Sort group headers
    if group_by == "is_static":
        sort_order = {"Static": 0, "Dynamic": 1}
        grouped_entries = dict(sorted(grouped_entries.items(), key=lambda item: sort_order.get(item[0], 99)))
    elif group_by == "group_name":
        group_meta = {
            g.id: (
                g.group_sort_priority if g.group_sort_priority is not None else 9999,
                g.group_name.lower()
            )
            for g in groups
        }

        def group_sort_key(item):
            group_id = item[0]
            if group_id is None:
                return (float('inf'), 'zzz')  # Ungrouped last
            return group_meta.get(group_id, (9999, 'zzz'))

        grouped_entries = dict(sorted(grouped_entries.items(), key=group_sort_key))

    else:
        grouped_entries = dict(sorted(grouped_entries.items()))

    widget_fields = {
        widget.id: widget.widget_fields for widget in Widget.query.all()
    }

    return render_template(
        "dashboard.html",
        entries=entries,
        grouped_entries=grouped_entries,
        sort=sort,
        direction=direction,
        group_by=group_by,
        msg=msg,
        STD_DOZZLE_URL=settings.get("std_dozzle_url"),
        display_tools=settings.get("display_tools", False),
        widget_values=widget_values,
        widget_fields=widget_fields,
        sort_in_group=sort_in_group,
        active_tab='dashboard',
        group_lookup=group_lookup,
    )


@app.route('/tiled_dash')
@login_required
def tiled_dashboard():
    group_by_param = request.args.get('group_by', 'group_name')
    sort_in_group = request.args.get('sort_in_group', 'priority')  # default to priority

    # Use actual attribute for sorting if valid
    if hasattr(ServiceEntry, group_by_param):
        group_by_attr_name = group_by_param
        group_by_attr_for_query = getattr(ServiceEntry, group_by_param)
    else:
        group_by_attr_name = 'group_name'
        group_by_attr_for_query = ServiceEntry.group_id  # default fallback

    entries = ServiceEntry.query.order_by(group_by_attr_for_query.asc(), ServiceEntry.container_name.asc()).all()

    # === Preload widget values ===
    widget_value_rows = WidgetValue.query.all()
    widget_values = {}
    for wv in widget_value_rows:
        if wv.widget_id not in widget_values:
            widget_values[wv.widget_id] = {}
        widget_values[wv.widget_id][wv.widget_value_key] = wv.widget_value

    # === Group entries ===
    grouped_entries_dict = defaultdict(list)
    for entry in entries:
        if group_by_attr_name == "is_static":
            key = "Static Entries" if entry.is_static else "Dynamic Entries"
        elif group_by_attr_name == "group_name":
            key = entry.group.group_name if entry.group else "Ungrouped"
        else:
            raw_value = getattr(entry, group_by_attr_name, None)
            key = "Ungrouped" if raw_value in [None, '', 'None'] else str(raw_value)
        grouped_entries_dict[key].append(entry)

    # === Sort entries within each group ===
    for key, group_entries in grouped_entries_dict.items():
        if sort_in_group == "alphabetical":
            grouped_entries_dict[key] = sorted(
                group_entries, key=lambda e: e.container_name.lower()
            )
        else:  # default to priority
            grouped_entries_dict[key] = sorted(
                group_entries,
                key=lambda e: (
                    e.sort_priority if e.sort_priority is not None else 9999,
                    e.container_name.lower()
                )
            )

    # === Sort groups themselves ===
    if group_by_attr_name == "is_static":
        sort_order = {"Static Entries": 0, "Dynamic Entries": 1, "Ungrouped": 2}
        sorted_grouped_entries = dict(sorted(
            grouped_entries_dict.items(),
            key=lambda item: (sort_order.get(item[0], 99), item[0])
        ))

    elif group_by_attr_name == "group_name":
        group_meta = {
            g.group_name: (
                g.group_sort_priority if g.group_sort_priority is not None else 9999,
                g.group_name.lower()
            )
            for g in Group.query.all()
        }

        def group_sort_key(item):
            name = item[0]
            if name == "Ungrouped":
                return (float('inf'), 'zzz')  # Always last
            return group_meta.get(name, (9999, name.lower()))

        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items(), key=group_sort_key))

    else:
        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items()))

    widget_fields = {
        widget.id: widget.widget_fields for widget in Widget.query.all()
    }

    return render_template(
        "tiled_dash.html",
        grouped_entries=sorted_grouped_entries,
        active_group_by=group_by_attr_name,
        sort_in_group=sort_in_group,
        STD_DOZZLE_URL=app.config['std_dozzle_url'],
        total_entries=len(entries),
        widget_values=widget_values,
        widget_fields=widget_fields
    )

@app.route('/compact_dash')
@login_required
def compact_dash():
    group_by_param = request.args.get('group_by', 'group_name')
    sort_in_group = request.args.get('sort_in_group', 'alphabetical')

    group_by_attr_name = group_by_param

    # Explicitly join Group to allow sorting by Group.group_name
    entries = (
        ServiceEntry.query
        .options(joinedload(ServiceEntry.group))
        .join(Group, isouter=True)
        .order_by(
            nullslast(Group.group_sort_priority.asc()),
            ServiceEntry.container_name.asc()
        )
        .all()
    )

    # Group entries
    grouped_entries_dict = defaultdict(list)
    for entry in entries:
        if group_by_attr_name == "is_static":
            key = "Static Entries" if entry.is_static else "Dynamic Entries"
        elif group_by_attr_name == "group_name":
            key = entry.group.group_name if entry.group else "Ungrouped"
        else:
            raw_value = getattr(entry, group_by_attr_name, None)
            key = "Ungrouped" if raw_value in [None, '', 'None'] else str(raw_value)
        grouped_entries_dict[key].append(entry)

    # Sort entries within each group
    for key in grouped_entries_dict:
        if sort_in_group == 'priority':
            grouped_entries_dict[key] = sorted(
                grouped_entries_dict[key],
                key=lambda e: (
                    e.sort_priority if e.sort_priority is not None else 9999,
                    e.container_name.lower()
                )
            )
        else:
            grouped_entries_dict[key] = sorted(
                grouped_entries_dict[key],
                key=lambda e: e.container_name.lower()
            )

    # Sort group names
    if group_by_attr_name == "group_name":
        group_meta = {
            g.group_name: g.group_sort_priority if g.group_sort_priority is not None else 9999
            for g in Group.query.all()
        }

        def sort_key(item):
            name = item[0]
            if name == "Ungrouped":
                return (float('inf'), "")  # put ungrouped last
            return (group_meta.get(name, 9999), name.lower())

        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items(), key=sort_key))

    elif group_by_attr_name in ["host", "stack_name"]:
        sorted_grouped_entries = dict(
            sorted(grouped_entries_dict.items(), key=lambda item: (item[0] == "Ungrouped", item[0].lower()))
        )

    elif group_by_attr_name == "is_static":
        sort_order = {"Static Entries": 0, "Dynamic Entries": 1, "Ungrouped": 2}
        sorted_grouped_entries = dict(
            sorted(grouped_entries_dict.items(), key=lambda item: (sort_order.get(item[0], 99), item[0]))
        )

    else:
        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items()))


    # Flatten for rendering
    flattened_entries = []
    for group_name, group_entries in sorted_grouped_entries.items():
        flattened_entries.append({'is_group_header': True, 'group': group_name})
        for entry in group_entries:
            flattened_entries.append({'is_group_header': False, 'entry': entry})

    unique_hosts = set(e.host for e in entries if e.host)
    show_host = len(unique_hosts) > 1

    return render_template(
        "compact_dash.html",
        flattened_entries=flattened_entries,
        total_entries=len(entries),
        show_host=show_host,
        group_by=group_by_param,
        sort_in_group=sort_in_group,
        active_tab="compact"
    )


@app.route("/dbdump")
@login_required
@is_admin_required
def db_dump():
    entries = ServiceEntry.query.order_by(ServiceEntry.id).all()
    return render_template("dbdump.html", entries=entries)    

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()

        if user and user.is_active and check_password_hash(user.password_hash, password):
            login_user(user)  # <-- This is the key line you’re missing
            session.permanent = True
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")

@app.route("/logout", methods=["POST"])
@login_required
def logout():
    session.clear()
    flash("You’ve been logged out.", "info")
    return redirect(url_for("login"))


@app.route('/settings', methods=['GET', 'POST'])
@login_required
@is_admin_required
def settings():
    settings, config_from_env, config_from_file = load_settings()
    BACKUP_DIR = settings.get("backup_path", "/config/backups")
    BACKUP_PATH = os.path.join(BACKUP_DIR, "backup.yml")
    os.makedirs(BACKUP_DIR, exist_ok=True)
    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()


    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'backup':
            backup_operation = request.form.get('backup_operation')
            
            # Backup is always for all entries now
            entries = ServiceEntry.query.all()
            data = []
            for e in entries:
                entry_data = e.to_dict()

                # Add authoritative group_name from the relationship if group is linked
                if e.group:
                    entry_data['group_name'] = e.group.group_name
                else:
                    entry_data['group_name'] = None  # fallback for safety

                data.append(entry_data)


            try:
                with open(BACKUP_PATH, 'w') as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
                logger.info(f"📦 Default YAML backup updated at {BACKUP_PATH} (all entries)")

                if backup_operation == 'save_on_server':
                    # If the goal was just to save on the server, we're done.
                    flash(f"✅ Backup saved to server: {BACKUP_PATH}", "success")
                    return redirect(url_for('settings', section='backup'))
                
                elif backup_operation == 'download_all':
                    # If the goal is to download, send the file that was just written.
                    logger.info(f"📦 Preparing YAML backup for download from {BACKUP_PATH} (all entries)")
                    return send_file(
                        BACKUP_PATH,
                        mimetype='text/yaml',
                        as_attachment=True,
                        download_name=f'service_backup_all_{datetime.now().strftime("%Y%m%d_%H%M%S")}.yaml' # Added timestamp to download
                    )
                else:
                    flash("Unknown backup operation.", "danger")
                    return redirect(url_for('settings', section='backup'))

            except Exception as e:
                logger.exception("❌ Backup operation failed")
                flash(f"Backup operation failed: {str(e)}", "danger")
                return redirect(url_for('settings'))

        elif action == 'restore':
            restore_source = request.form.get('restore_source')
            restore_scope = request.form.get('restore_scope', 'all') # Defaults to 'all'
            
            records = None
            source_description = "unknown source"

            try:
                if restore_source == 'upload':
                    file = request.files.get('restore_file')
                    if file and file.filename:
                        content = file.read().decode('utf-8')
                        records = yaml.safe_load(content)
                        source_description = f"uploaded file '{file.filename}'"
                    else:
                        flash("No file uploaded for restore.", "warning")
                        return redirect(url_for('settings'))
                
                elif restore_source == 'server':
                    selected_filename = request.form.get('server_backup_filename')
                    if selected_filename:
                        # Basic security check: ensure filename doesn't try to escape BACKUP_DIR
                        if ".." in selected_filename or selected_filename.startswith("/"):
                            flash("Invalid server filename selected.", "danger")
                            return redirect(url_for('settings'))
                        
                        file_path = os.path.join(BACKUP_DIR, selected_filename)
                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            with open(file_path, 'r') as f:
                                records = yaml.safe_load(f)
                            source_description = f"server file '{selected_filename}'"
                        else:
                            flash(f"Selected server backup file '{selected_filename}' not found or is invalid.", "danger")
                            return redirect(url_for('settings'))
                    else:
                        flash("No server backup file selected.", "warning")
                        return redirect(url_for('settings'))
                else:
                    flash("Invalid restore source selected.", "danger")
                    return redirect(url_for('settings'))

                if records is None:
                    if not flash_is_present(request): # Avoid double flashing if already flashed above
                         flash("Could not load records for restore.", "danger")
                    return redirect(url_for('settings'))

                restored_count = 0
                skipped_count = 0
                
                for item in records:
                    if not item.get('host') or not item.get('container_name'):
                        logger.warning(f"⛔ Skipping entry with missing host/container_name: {item}")
                        skipped_count +=1
                        continue

                    item_is_static_from_backup = item.get('is_static', False)

                    # Apply restore_scope: if scope is 'static', skip non-static items from backup
                    if restore_scope == 'static' and not item_is_static_from_backup:
                        skipped_count +=1
                        continue

                    # Handle embedded widget data if present
                    # --- 1. Restore or create the widget ---
                    widget_data = item.get('widget')
                    widget_obj = None

                    if widget_data:
                        widget_obj = Widget.query.filter_by(
                            widget_name=widget_data.get('widget_name'),
                            widget_url=widget_data.get('widget_url')
                        ).first()

                        if not widget_obj:
                            widget_obj = Widget(
                                widget_name=widget_data.get('widget_name'),
                                widget_url=widget_data.get('widget_url'),
                                widget_fields=widget_data.get('widget_fields') or [],
                                widget_api_key=widget_data.get('widget_api_key'),
                            )
                            db.session.add(widget_obj)
                        else:
                            widget_obj.widget_fields = widget_data.get('widget_fields') or []
                            widget_obj.widget_api_key = widget_data.get('widget_api_key')

                        db.session.flush()  # ensure widget_obj.id is available



                    entry = ServiceEntry.query.filter_by(
                        container_name=item['container_name'],
                        host=item['host']
                    ).first()

                    group_name = item.get('group_name')
                    group_obj = None
                    
                    if group_name:
                        group_obj = Group.query.filter_by(group_name=group_name).first()
                        if not group_obj:
                            group_obj = Group(group_name=group_name)
                            db.session.add(group_obj)
                            db.session.flush()

                    # Fetch or create entry
                    entry = ServiceEntry.query.filter_by(
                        container_name=item['container_name'],
                        host=item['host']
                    ).first()

                    if not entry:
                        entry = ServiceEntry(host=item['host'], container_name=item['container_name'])
                        db.session.add(entry)

                    # Assign group_id only now (after entry exists)
                    entry.group_id = group_obj.id if group_obj else None


                    if entry: # Entry exists in DB
                        # Rule: Protect existing static entries in DB from being overwritten by non-static items
                        # during a 'restore all' operation.
                        if entry.is_static and restore_scope == 'all' and not item_is_static_from_backup:
                            logger.info(f"ℹ️ Skipping update for DB static entry '{entry.container_name}' "
                                        f"by non-static item from backup during 'all' scope restore.")
                            skipped_count +=1
                            continue
                        # Otherwise (entry is not static, or item from backup is static, or scope is 'static'), proceed to update.
                    else: # New entry, create it
                        entry = ServiceEntry(host=item['host'], container_name=item['container_name'])
                        db.session.add(entry)
                    if widget_obj:
                        entry.widget_id = widget_obj.id

                    # Apply fields from backup item to DB entry
                    for field, value in item.items():
                        # Ensure 'is_static' is handled correctly based on the item from backup
                        if field == 'is_static':
                            if hasattr(entry, 'is_static'):
                                setattr(entry, 'is_static', item_is_static_from_backup)
                        elif hasattr(entry, field) and field not in ['id', 'last_updated', 'last_api_update', 'widget']:
                            setattr(entry, field, value)

                    
                    # If 'is_static' wasn't in item.items() but we are creating, ensure it's set
                    # (especially if item_is_static_from_backup was derived from .get with a default)
                    if not entry.id and hasattr(entry, 'is_static'): # if it's a new entry being added
                         if 'is_static' not in item: # if 'is_static' was not explicitly in the backup item dict
                            setattr(entry, 'is_static', item_is_static_from_backup) # ensure it's set from .get default

                    entry.last_updated = datetime.now()
                    restored_count += 1
                
                db.session.commit()
                flash_message = f"✅ Restored {restored_count} entries"
                if restore_scope == 'static':
                    flash_message += " (static entries only)"
                flash_message += f" from {source_description}."
                if skipped_count > 0:
                    flash_message += f" Skipped {skipped_count} items."
                flash(flash_message, "success")
                logger.info(f"♻️ {flash_message}")

            except Exception as e:
                db.session.rollback() # Rollback in case of error during DB operations
                logger.exception("❌ Restore failed")
                flash(f"Restore failed: {str(e)}", "danger")
            
            return redirect(url_for('settings', section='backup'))

    # GET request: List backup files for the restore dropdown
    server_backup_files = []
    if os.path.exists(BACKUP_DIR):
        try:
            # List files and filter for .yaml or .yml, sort them (e.g., reverse for newest first if names allow)
            all_files = [f for f in os.listdir(BACKUP_DIR) if os.path.isfile(os.path.join(BACKUP_DIR, f)) and (f.endswith('.yaml') or f.endswith('.yml'))]
            # You might want to sort these files, e.g., by modification time or name
            all_files.sort(reverse=True) # Example: newest first if names are sortable by time
            server_backup_files = all_files
        except Exception as e:
            logger.exception(f"Error listing backup files from {BACKUP_DIR}")
            flash(f"Could not list server backup files: {str(e)}", "warning")

# Check which icon files are missing
        missing_icons = []
        all_entries = ServiceEntry.query.all()
        for entry in all_entries:
            icon = entry.image_icon
            if icon and not os.path.exists(os.path.join(IMAGE_DIR, icon)):
                missing_icons.append(f"{entry.container_name} → {icon}")            
    widgets = Widget.query.all()
    users = User.query.order_by(User.username.asc()).all()
    return render_template(
        'settings.html',
         current_config=settings,
         config_from_env=config_from_env,
         config_from_file=config_from_file,
         server_backup_files=server_backup_files,
         version_info=read_version_info(),
         widgets=widgets,
         missing_icons=missing_icons,
         groups=groups,
         users=users
    )

# Helper to check if flash messages are already present (to avoid duplicates)
# This is a basic check; Flask's get_flashed_messages usually clears them.
def flash_is_present(req):
    return '_flashes' in req.environ.get('flask._flashes', [])


@app.route('/update_group', methods=['POST'])
@login_required
@is_admin_required
def update_group():
    group_id = request.form.get("group_id")
    group = Group.query.get(group_id)

    if group:
        group.group_name = request.form.get("group_name", group.group_name)
        group.group_icon = request.form.get("group_icon", group.group_icon)
        priority_val = request.form.get("group_sort_priority")
        group.group_sort_priority = int(priority_val) if priority_val and priority_val.isdigit() else None

        db.session.commit()
        flash(f"✅ Group {group.group_name} updated successfully.", "success")
    else:
        flash("❌ Group not found.", "danger")

    return redirect(url_for("settings", section="groups"))

@app.route('/add_group', methods=['POST'])
@login_required
@is_admin_required
def add_group():
    name = request.form.get("group_name")
    icon = request.form.get("group_icon")
    priority = request.form.get("group_sort_priority")

    if not name:
        flash("❌ Group name is required.", "danger")
        return redirect(url_for("settings", section="groups"))

    existing = Group.query.filter_by(group_name=name).first()
    if existing:
        flash("❌ Group with that name already exists.", "danger")
        return redirect(url_for("settings", section="groups"))

    new_group = Group(
        group_name=name,
        group_icon=icon or None,
        group_sort_priority=int(priority) if priority and priority.isdigit() else None
    )

    db.session.add(new_group)
    db.session.commit()
    flash(f"✅ Group '{name}' created.", "success")
    return redirect(url_for("settings", section="groups"))

@app.route('/delete_group', methods=['POST'])
@login_required
@is_admin_required
def delete_group():
    group_id = request.form.get('group_id')
    group = Group.query.get(group_id)

    if group:
        if len(group.services) == 0:
            db.session.delete(group)
            db.session.commit()
            flash(f"🗑️ Group '{group.group_name}' deleted successfully.", "success")
        else:
            flash("❌ Cannot delete group that has services.", "danger")
    else:
        flash("❌ Group not found.", "danger")

    return redirect(url_for('settings', section='groups'))

@app.route("/add_user", methods=["POST"])
@login_required
@is_admin_required
def add_user():
    username = request.form.get("username")
    email = request.form.get("email")
    password = request.form.get("password")
    is_admin = request.form.get("is_admin") == "on"

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("User already exists with this username or email", "danger")
        return redirect(url_for("settings", section="users"))

    user = User(username=username, email=email, is_admin=is_admin)
    user.set_password(password)
    user.generate_session_token()
    db.session.add(user)
    db.session.commit()

    flash(f"✅ User '{username}' created", "success")
    return redirect(url_for("settings", section="users"))

@app.route("/reset_user_password", methods=["POST"])
@login_required
@is_admin_required
def reset_user_password():
    user_id = request.form.get("user_id")
    user = User.query.get(user_id)
    if user:
        user.set_password("changeme123")
        db.session.commit()
        flash(f"🔁 Password reset for {user.username} to 'changeme123'", "info")
    else:
        flash("❌ User not found", "danger")
    return redirect(url_for("settings", section="users"))

@app.route("/delete_user", methods=["POST"])
@login_required
@is_admin_required
def delete_user():
    user_id = request.form.get("user_id")
    user = User.query.get(user_id)
    if user and not user.is_admin:
        db.session.delete(user)
        db.session.commit()
        flash(f"🗑️ User {user.username} deleted", "success")
    else:
        flash("❌ Cannot delete admin or invalid user", "danger")
    return redirect(url_for("settings", section="users"))

@app.route('/images/<path:filename>')
@login_required

def serve_image(filename):
    response = make_response(send_from_directory(IMAGE_DIR, filename))
    response.headers['Cache-Control'] = 'public, max-age=86400'  # cache for 1 day
    return response

@app.route('/add', methods=['GET', 'POST'])
@login_required
@is_admin_required
def add_entry():
    raw_referrer = request.args.get('ref', '/')
    parsed = urlparse(raw_referrer)
    referrer = parsed.path
    if parsed.query:
        referrer += '?' + parsed.query
    if not referrer.startswith('/'):
        referrer = '/tiled_dash'

    if request.method == 'POST':
        host = request.form.get('host')
        container_name = request.form.get('application')
        internalurl = request.form.get('internal_url')
        externalurl = request.form.get('external_url')
        group_mode = request.form.get('group_mode')  # 'existing' or 'new'
        group_name = None

        if group_mode == 'existing':
            group_name = request.form.get('group_name_existing')
        elif group_mode == 'new':
            group_name = request.form.get('group_name_new')

        if not group_name:
            group_name = "None"
        

        image_icon_raw = request.form.get('icon_image', '').strip().lower()
        if image_icon_raw and not image_icon_raw.endswith('.svg'):
            image_icon = f"{image_icon_raw}.svg"
        else:
            image_icon = image_icon_raw

        if not host or not container_name:
            flash('Host and Application (Container Name) are required.', 'danger')
            return render_template("add_entry.html", msg='error', entry=request.form)

        # Check for duplicates
        existing = ServiceEntry.query.filter_by(host=host, container_name=container_name).first()
        if existing:
            flash(f"An entry for '{container_name}' on host '{host}' already exists.", 'danger')
            return render_template("add_entry.html", msg='duplicate', entry=request.form)

        # Booleans
        internal_health_check_enabled = request.form.get('internal_health_check') == 'on'
        external_health_check_enabled = request.form.get('external_health_check') == 'on'
        is_static = request.form.get('locked') == 'on'

        # === ICON RESOLUTION LOGIC ===
        if image_icon:
            icon_path = os.path.join(IMAGE_DIR, image_icon)
            if not os.path.exists(icon_path):
                try:
                    icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{image_icon}"
                    response = requests.get(icon_url, timeout=5)
                    if response.status_code == 200:
                        with open(icon_path, 'wb') as f:
                            f.write(response.content)
                        logger.info(f"⬇️ Downloaded user-supplied icon '{image_icon}' for '{container_name}'")
                    else:
                        logger.warning(f"⚠️ Icon '{image_icon}' not found (HTTP {response.status_code})")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to fetch icon '{image_icon}': {e}")
        else:
            derived_icon_name = container_name.lower().replace(" ", "-")
            image_icon = fetch_icon_if_missing(derived_icon_name, IMAGE_DIR, logger, debug=app.debug)
            if image_icon:
                logger.info(f"💡 Automatically fetched icon '{image_icon}' for new entry '{container_name}'.")
            else:
                logger.info(f"⚠️ Could not automatically fetch icon for '{container_name}'.")

        # Optional sort priority (must be an int if provided)
        sort_priority_raw = request.form.get('sort_priority', '').strip()
        sort_priority = None
        if sort_priority_raw:
            try:
                sort_priority = int(sort_priority_raw)
            except ValueError:
                flash("Sort priority must be a number.", 'danger')
                return render_template("add_entry.html", msg='error', entry=request.form, groups=groups)

        # === CREATE ENTRY ===
        # Look up or create group
        group_obj = Group.query.filter_by(group_name=group_name).first()
        if not group_obj:
            group_obj = Group(group_name=group_name)
            db.session.add(group_obj)
            db.session.flush()  # ensures group_obj.id is populated before use

        # Now create entry with group_id
        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            internalurl=internalurl,
            externalurl=externalurl,
            last_updated=datetime.now(),
            group_id=group_obj.id if group_obj else None,
            internal_health_check_enabled=internal_health_check_enabled,
            external_health_check_enabled=external_health_check_enabled,
            image_icon=image_icon,
            sort_priority=sort_priority,
            is_static=is_static
)

        db.session.add(entry)
        db.session.commit()

        flash(f"✅ Service entry '{container_name}' added successfully!", 'success')
        return redirect(url_for('tiled_dashboard'))

    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
    return render_template("add_entry.html", msg='', entry={}, active_tab="add", groups=groups)

@app.route('/api/register', methods=['POST'])
def api_register():

    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {app.config['api_token']}"
    client_ip = request.remote_addr
    now = datetime.utcnow()

    # Rate-limit unauthorized logs to once every 2 minutes per IP
    if auth_header != expected:
        logger.info(f"401 - Unauthorized API access from {client_ip} to /api/register")

        # Rate-limited WARNING (optional)
        last_log_time = unauthorized_log_tracker.get(client_ip)
        if not last_log_time or (now - last_log_time) > timedelta(minutes=2):
            logger.warning(f"⚠️ Repeated unauthorized access from {client_ip}")
            unauthorized_log_tracker[client_ip] = now

        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    # 🔁 Remap STD-style keys to internal DB fields
    label_key_map = {
        "group": "group_name",
        "internal_health": "internal_health_check_enabled",
        "internal.health": "internal_health_check_enabled",  # Add this
        "external_health": "external_health_check_enabled",
        "external.health": "external_health_check_enabled",  # Add this
        "docker_host": "host",
        "icon": "image_icon",
    }
    for src_key, target_key in label_key_map.items():
        if src_key in data and target_key not in data:
            data[target_key] = data[src_key]
    # For debug: log any unexpected fields (not known or remapped)
    if app.debug:
        known_fields = {
            "host", "docker_host", "container_name", "container_id", "internalurl", "externalurl",
            "stack_name", "docker_status", "group_name", "group", "started_at",
            "internal_health_check_enabled", "external_health_check_enabled",
            "internal.health", "external.health",
            "image_name", "image_icon", "timestamp", "sort.priority"
        }
        # Include remapped fields (e.g., group → group_name)
        known_fields.update(label_key_map.values())

        for key in data:
            if key not in known_fields:
                logger.warning(f"⚠️ Unexpected STD label received (ignored): {key} = {data[key]}")


    if app.debug:
        logger.info("🔍 Received API payload:")
        for k, v in data.items():
            logger.info(f"    {k}: {v}")

    if not data.get('host') or not data.get('container_name'):
        return jsonify({"error": "Missing host or container_name"}), 400

    # ✅ Use shared metadata resolver
    image_meta = resolve_image_metadata(
        image_raw=data.get("image_name"),
        image_icon_override=data.get("image_icon"),
        fallback_name=data.get("container_name"),
        image_dir=IMAGE_DIR,
        failed_icon_cache=failed_icon_cache,
        retry_interval=RETRY_INTERVAL,
        logger=logger,
        debug=app.debug
    )

    registry = image_meta["registry"]
    owner = image_meta["owner"]
    img_name = image_meta["image_name"]
    tag = image_meta["image_tag"]
    image_icon = image_meta["image_icon"]

    # Update or create entry
    # Handle group assignment
    group_name = data.get("group_name")
    group_obj = None

    if group_name:
        group_obj = Group.query.filter_by(group_name=group_name).first()
        if not group_obj:
            group_obj = Group(group_name=group_name)
            db.session.add(group_obj)
            db.session.flush()  # ensure group_obj.id is available
    entry = ServiceEntry.query.filter_by(container_name=data['container_name'], host=data['host']).first()
    
    if entry:
        if entry.is_static:
            logger.info(f"Skipping update for '{entry.container_name}' on '{entry.host}' — static lock enabled.")
            return jsonify({"status": "skipped", "reason": "static lock"}), 200
        entry.last_updated = datetime.now()
        entry.last_api_update = datetime.now()
        if "sort.priority" in data:
            try:
                entry.sort_priority = int(data["sort.priority"])
            except (TypeError, ValueError):
                logger.warning(f"⚠️ Invalid sort priority: {data['sort.priority']}")


        if data.get("container_id"):
            entry.container_id = data["container_id"]
        if data.get("internalurl"):
            entry.internalurl = data["internalurl"]
        if data.get("externalurl"):
            entry.externalurl = data["externalurl"]
        if data.get("stack_name"):
            entry.stack_name = data["stack_name"]
        if data.get("docker_status"):
            entry.docker_status = data["docker_status"]

        if "group_name" in data:
            entry.group_id = group_obj.id if group_obj else None

        if data.get("started_at"):
            entry.started_at = data["started_at"]

        if "internal_health_check_enabled" in data:
            parsed = parse_bool(data["internal_health_check_enabled"])
            if parsed is not None:
                entry.internal_health_check_enabled = parsed

        if "external_health_check_enabled" in data:
            parsed = parse_bool(data["external_health_check_enabled"])
            if parsed is not None:
                entry.external_health_check_enabled = parsed

        if registry:
            entry.image_registry = registry
        if owner:
            entry.image_owner = owner
        if img_name:
            entry.image_name = img_name
        if image_icon:
            entry.image_icon = image_icon
        if tag:
            entry.image_tag = tag

   
    
    else:
        entry = ServiceEntry(
            host=data['host'],
            container_name=data['container_name'],
            container_id=data.get('container_id'),
            internalurl=data.get('internalurl'),
            externalurl=data.get('externalurl'),
            stack_name=data.get('stack_name'),
            docker_status=data.get('docker_status'),
            internal_health_check_enabled=parse_bool(data.get('internal_health_check_enabled')),
            external_health_check_enabled=parse_bool(data.get('external_health_check_enabled')),
            group_id=group_obj.id if group_obj else None,
            started_at=data.get('started_at'),
            last_updated=datetime.now(),
            last_api_update=datetime.now(),
            image_registry=registry,
            image_owner=owner,
            image_name=img_name,
            image_icon=image_icon,
            image_tag=tag
        )
        db.session.add(entry)


    db.session.commit()
    return jsonify(entry.to_dict()), 200 if entry else 201


@app.route('/widget_config/<widget_name>')
@login_required
@is_admin_required
def widget_config(widget_name):
    path = os.path.join('/app/widgets', widget_name, 'settings.json')
    if not os.path.exists(path):
        return jsonify([])  # Or 404 if you prefer

    with open(path) as f:
        try:
            config = json.load(f)
            return jsonify(config.get("available_fields", []))  # ✅ FIXED
        except Exception as e:
            app.logger.warning(f"Failed to load widget settings for {widget_name}: {e}")
            return jsonify([])
        
@app.errorhandler(403)
def forbidden_error(error):
    return render_template("403.html"), 403

@app.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@is_admin_required
def edit_entry(id):
    entry = ServiceEntry.query.get_or_404(id)

    # Track the referrer for redirecting after save
    raw_referrer = request.args.get('ref', '/')
    parsed = urlparse(raw_referrer)
    referrer = parsed.path
    if parsed.query:
        referrer += '?' + parsed.query
    if not referrer.startswith('/'):
        referrer = '/'

    # Discover available widgets
    widgets_dir = '/app/widgets'
    available_widgets = []
    if os.path.exists(widgets_dir):
        available_widgets = [
            d for d in os.listdir(widgets_dir)
            if os.path.isdir(os.path.join(widgets_dir, d)) and d != '__pycache__'
        ]
        logger.debug(f"Widgets found: {', '.join(available_widgets)}") if available_widgets else logger.debug("No widgets found.")
    else:
        logger.warning(f"Widgets directory not found: {widgets_dir}")

    # Fetch current widget association
    selected_widget = None
    if entry.widget_id:
        selected_widget = Widget.query.get(entry.widget_id)
        if selected_widget:
            logger.debug(f"Selected widget: {selected_widget.widget_name}")
        else:
            logger.warning(f"Widget ID {entry.widget_id} not found")

    # Handle form submission
    if request.method == 'POST':
        # === DELETE ACTION ===
        if 'delete' in request.form:
            if request.form.get('delete_confirmation') == entry.container_name:
                Widget.query.filter_by(service_entry_id=entry.id).delete()
                db.session.delete(entry)
                db.session.commit()
                flash(f"Deleted entry: {entry.container_name}", 'success')
                return redirect(referrer)
            else:
                flash("Confirmation name does not match. Entry not deleted.", "warning")
                return redirect(url_for('edit_entry', id=id, ref=referrer))

        # === BASIC FIELDS ===
        entry.host = request.form.get('host', '').strip()
        entry.container_name = request.form.get('container_name', '').strip()
        entry.internalurl = request.form.get('internalurl', '').strip() or None
        entry.externalurl = request.form.get('externalurl', '').strip() or None
        entry.internal_health_check_enabled = 'internal_health_check_enabled' in request.form
        entry.external_health_check_enabled = 'external_health_check_enabled' in request.form
        entry.is_static = 'is_static' in request.form

        sort_priority_raw = request.form.get('sort_priority', '').strip()
        try:
            entry.sort_priority = int(sort_priority_raw) if sort_priority_raw else None
        except ValueError:
            entry.sort_priority = None
            flash("Sort priority must be a number.", "warning")

        # === GROUP HANDLING ===
        group_mode = request.form.get('group_mode')
        group_name = None
        if group_mode == 'existing':
            group_name = request.form.get('group_name_existing')
        elif group_mode == 'new':
            group_name = request.form.get('group_name_new')

        if not group_name:
            group_name = "zz_none"

        group = Group.query.filter_by(group_name=group_name).first()
        if not group:
            group = Group(group_name=group_name)
            db.session.add(group)
            db.session.commit()
        entry.group_name = group.group_name
        entry.group_id = group.id

        # === ICON ===
        raw_icon = request.form.get('image_icon', '').strip().lower()
        entry.image_icon = f"{raw_icon}.svg" if raw_icon and not raw_icon.endswith('.svg') else raw_icon
        icon_path = os.path.join(IMAGE_DIR, entry.image_icon) if entry.image_icon else ''
        if entry.image_icon and not os.path.exists(icon_path):
            try:
                icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{entry.image_icon}"
                response = requests.get(icon_url, timeout=5)
                if response.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Downloaded icon: {entry.image_icon}")
                else:
                    logger.warning(f"Icon not found at {icon_url}")
            except Exception as e:
                logger.warning(f"Error fetching icon: {e}")
        elif not entry.image_icon and request.form.get('force_update_icon') == 'true':
            derived_icon_name = entry.container_name.lower().replace(" ", "-")
            fetched_icon = fetch_icon_if_missing(derived_icon_name, IMAGE_DIR, logger, debug=app.debug)
            if fetched_icon:
                entry.image_icon = fetched_icon

        # === WIDGET LOGIC ===
        widget_name = request.form.get('widget_name')
        widget_url = request.form.get('widget_url') or None
        widget_api_key = request.form.get('widget_api_key') or None
        widget_fields = request.form.getlist('widget_fields')

        if widget_name == 'none':
            if entry.widget_id:
                WidgetValue.query.filter_by(widget_id=entry.widget_id).delete()
                Widget.query.filter_by(id=entry.widget_id).delete()
                entry.widget_id = None
        else:
            if entry.widget_id:
                widget = Widget.query.get(entry.widget_id)
                if widget:
                    widget.widget_name = widget_name
                    widget.widget_url = widget_url
                    widget.widget_api_key = widget_api_key
                    widget.widget_fields = widget_fields
                else:
                    widget = Widget(widget_name=widget_name, widget_url=widget_url,
                                    widget_api_key=widget_api_key, widget_fields=widget_fields)
                    db.session.add(widget)
                    db.session.flush()
                    entry.widget_id = widget.id
            else:
                widget = Widget(widget_name=widget_name, widget_url=widget_url,
                                widget_api_key=widget_api_key, widget_fields=widget_fields)
                db.session.add(widget)
                db.session.flush()
                entry.widget_id = widget.id

        entry.last_updated = datetime.now()

        try:
            db.session.commit()
            flash(f"✅ Entry '{entry.container_name}' updated!", "success")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Update error: {e}")
            flash("Error saving changes", "danger")

        return redirect(referrer)

    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
    return render_template("edit_entry.html",
                           entry=entry,
                           ref=referrer,
                           groups=groups,
                           available_widgets=available_widgets,
                           selected_widget=selected_widget)


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
    from settings_loader import load_settings
    settings, _, _ = load_settings()
    URL_HEALTHCHECK_INTERVAL = settings.get("url_healthcheck_interval", 60)

    with app.app_context():
        while True:
            time.sleep(URL_HEALTHCHECK_INTERVAL)
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


def run_scheduled_backup():
    with app.app_context():
        settings, _, _ = load_settings()
        backup_dir = settings.get("backup_path", "/config/backups")
        days_to_keep = int(settings.get("backup_days_to_keep", 7))

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

version_info = read_version_info()
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

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=health_check_loop, daemon=True).start()

# === APScheduler Setup with Debug-Safe Guard ===
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    scheduler = BackgroundScheduler()
    settings, _, _ = load_settings()
    reload_seconds = settings.get("widget_background_reload")
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

    # Start any background threads too
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
            admin.generate_session_token()
            db.session.add(admin)
            db.session.commit()
            logger.info("🛠️ Default admin user created (username: admin, password: changeme123)")
        else:
            logger.info("👤 Admin user already exists.")

if __name__ == '__main__':
    create_default_admin()
    logger.info("🔍 Verifying icon files for all ServiceEntry records...")
    verify_and_fetch_missing_icons()

    logger.info(f"🚀 Starting app (debug={app.debug}) on port 8815")
    app.run(host='0.0.0.0', port=8815, debug=app.debug)
 