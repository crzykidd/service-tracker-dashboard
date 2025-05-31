# Config
import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, send_file, flash, jsonify, render_template, redirect, url_for, send_from_directory, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import humanize
from dateutil import parser
import sqlite3
import threading
import time
import requests
from collections import defaultdict
import yaml
from settings_loader import load_settings
from image_utils import resolve_image_metadata, parse_bool
from urllib.parse import urlparse, urljoin

DATABASE_PATH = '/config/services.db'
LOGFILE = '/config/std.log'
IMAGE_DIR = '/config/images'

# === Logging Setup ===
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
log_handler = RotatingFileHandler(
    LOGFILE, maxBytes=10 * 1024 * 1024, backupCount=4
)
log_handler.setFormatter(log_formatter)
log_handler.setLevel(logging.INFO)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)

# Optional: also log to console (helpful for Docker)
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
logger.addHandler(console_handler)


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "changeme-in-prod")
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

config, config_from_env, config_from_file = load_settings()

logger.info("🔧 Loaded settings:")
for k, v in config.items():
    logger.info(f"    {k} = {v}")

# Optionally populate into app.config if you use `Flask config`
app.config.update(config)

logger.info("⚙️ Flask config (from settings):")
for k in config:
    logger.info(f"    {k} = {app.config.get(k)}")


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
    group_name = db.Column(db.String(20), nullable=True, default="zz_none")
    is_static = db.Column(db.Boolean, nullable=False, default=False)
    started_at = db.Column(db.String(100), nullable=True)  # stored in ISO string format

    def to_dict(self):
        return {
            'stack_name': self.stack_name,
            'id': self.id,
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
            'group_name': self.group_name or "zz_none",
            'started_at': self.started_at,
            'image_icon': self.image_icon,
            'is_static': self.is_static,
        }


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

# Ensure DB schema exists
logger.info("✅ Checking for 'service_entry' table...")
conn = sqlite3.connect(DATABASE_PATH)
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS service_entry (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        host TEXT NOT NULL,
        container_name TEXT NOT NULL,
        container_id TEXT,
        internalurl TEXT,
        externalurl TEXT,
        last_updated TEXT NOT NULL,
        last_api_update TEXT,
        stack_name TEXT,
        docker_status TEXT,
        internal_health_check_enabled BOOLEAN,
        internal_health_check_status TEXT,
        internal_health_check_update TEXT,
        external_health_check_enabled BOOLEAN,
        external_health_check_status TEXT,
        external_health_check_update TEXT,
        image_registry TEXT,
        image_owner TEXT,
        image_name TEXT,
        image_tag TEXT,
        image_icon TEXT,
        group_name TEXT,
        is_static BOOLEAN NOT NULL DEFAULT 0,
        started_at TEXT
    )
""")
conn.commit()
conn.close()
logger.info("✅ DB schema ensured.")


from collections import defaultdict

@app.route('/')
def dashboard():
    sort = request.args.get('sort', 'group_name')
    direction = request.args.get('dir', 'asc')
    group_by = request.args.get('group_by', 'group_name')
    msg = request.args.get('msg')

    # Build query and sort direction
    sort_attr = getattr(ServiceEntry, sort)
    sort_attr = sort_attr.asc() if direction == 'asc' else sort_attr.desc()
    entries = ServiceEntry.query.order_by(sort_attr).all()

    # Group entries
    grouped_entries = defaultdict(list)
    for entry in entries:
        raw_key = getattr(entry, group_by)
        if isinstance(raw_key, bool):
            key = "Static" if raw_key else "Dynamic"
        else:
            key = str(raw_key) if raw_key else "zz_none"
        grouped_entries[key].append(entry)

    # Custom sort: prioritize "Static" over "Dynamic", then alphabetical
    if group_by == "is_static":
        sort_order = {"Static": 0, "Dynamic": 1}
        grouped_entries = dict(sorted(grouped_entries.items(), key=lambda item: sort_order.get(item[0], 99)))
    else:
        grouped_entries = dict(sorted(grouped_entries.items()))

    return render_template(
        "dashboard.html",
        entries=entries,
        grouped_entries=grouped_entries,
        sort=sort,
        direction=direction,
        group_by=group_by,
        msg=msg,
        STD_DOZZLE_URL=os.getenv('STD_DOZZLE_URL')
    )



from collections import defaultdict # Ensure this is imported at the top of your app.py


@app.route('/tiled_dash')
def tiled_dashboard():
    group_by_param = request.args.get('group_by', 'group_name')  # Default grouping by group_name

    # Determine the attribute to sort and group by
    if hasattr(ServiceEntry, group_by_param):
        group_by_attr_name = group_by_param
        group_by_attr_for_query = getattr(ServiceEntry, group_by_param)
    else:
        # Fallback to group_name if the param is invalid
        group_by_attr_name = 'group_name'
        group_by_attr_for_query = ServiceEntry.group_name

    # Fetch entries, sorted primarily by the grouping attribute, then by container name
    entries = ServiceEntry.query.order_by(group_by_attr_for_query.asc(), ServiceEntry.container_name.asc()).all()

    grouped_entries_dict = defaultdict(list)
    for entry in entries:
        key_value = getattr(entry, group_by_attr_name)

        if group_by_attr_name == "is_static": # If you add 'is_static' to dropdown later
            key = "Static Entries" if key_value else "Dynamic Entries"
        # Handle common 'empty' or 'placeholder' group names
        elif key_value is None or str(key_value).strip() == "" or str(key_value).lower() == "zz_none":
            key = "Ungrouped"
        else:
            key = str(key_value)
        grouped_entries_dict[key].append(entry)

    # Sort groups for consistent display
    if group_by_attr_name == "is_static":
        sort_order = {"Static Entries": 0, "Dynamic Entries": 1, "Ungrouped": 2}
        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items(), key=lambda item: (sort_order.get(item[0], 99), item[0])))
    elif group_by_attr_name in ["group_name", "host", "stack_name"]: # Added "stack_name"
        # Sort alphabetically, but ensure "Ungrouped" (if it appears for None/empty values) is last
        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items(), key=lambda item: (item[0] == "Ungrouped", item[0])))
    else:
        # Default to alphabetical sorting for other group types
        sorted_grouped_entries = dict(sorted(grouped_entries_dict.items()))

    return render_template(
        "tiled_dash.html",
        grouped_entries=sorted_grouped_entries,
        active_group_by=group_by_attr_name, # Pass the currently active group_by key
        STD_DOZZLE_URL=app.config['std_dozzle_url']
    )

@app.route("/dbdump")
def db_dump():
    entries = ServiceEntry.query.order_by(ServiceEntry.id).all()
    return render_template("dbdump.html", entries=entries)    


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings, config_from_env, config_from_file = load_settings()
    BACKUP_DIR = settings.get("backup_path", "/config/backups")
    BACKUP_PATH = os.path.join(BACKUP_DIR, "backup.yml")
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'backup':
            backup_operation = request.form.get('backup_operation')
            
            # Backup is always for all entries now
            entries = ServiceEntry.query.all()
            data = [e.to_dict() for e in entries]

            # The default backup file is always written/updated first
            # You might want to name this default file more explicitly, e.g., latest_backup.yaml
            # or use BACKUP_PATH directly if it's intended as the primary/latest server backup.
            # For this example, we continue to use BACKUP_PATH as the target for server saves.
            try:
                with open(BACKUP_PATH, 'w') as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
                logger.info(f"📦 Default YAML backup updated at {BACKUP_PATH} (all entries)")

                if backup_operation == 'save_on_server':
                    # If the goal was just to save on the server, we're done.
                    flash(f"✅ Backup saved to server: {BACKUP_PATH}", "success")
                    return redirect(url_for('settings'))
                
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
                    return redirect(url_for('settings'))

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

                    entry = ServiceEntry.query.filter_by(
                        container_name=item['container_name'],
                        host=item['host']
                    ).first()

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

                    # Apply fields from backup item to DB entry
                    for field, value in item.items():
                        # Ensure 'is_static' is handled correctly based on the item from backup
                        if field == 'is_static':
                            if hasattr(entry, 'is_static'):
                                setattr(entry, 'is_static', item_is_static_from_backup)
                        elif hasattr(entry, field) and field not in ['id', 'last_updated', 'last_api_update']:
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
            
            return redirect(url_for('settings'))

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
            
    return render_template(
        'settings.html',
         current_config=config,
         config_from_env=config_from_env,
         config_from_file=config_from_file,
         server_backup_files=server_backup_files
    )

# Helper to check if flash messages are already present (to avoid duplicates)
# This is a basic check; Flask's get_flashed_messages usually clears them.
def flash_is_present(req):
    return '_flashes' in req.environ.get('flask._flashes', [])




@app.route('/images/<path:filename>')
def serve_image(filename):
    response = make_response(send_from_directory(IMAGE_DIR, filename))
    response.headers['Cache-Control'] = 'public, max-age=86400'  # cache for 1 day
    return response

@app.route('/add', methods=['GET', 'POST'])
def add_entry():
    if request.method == 'POST':
        host = request.form.get('host')
        # Use 'application' from form, map to container_name
        container_name = request.form.get('application')
        # internalurl from form
        internalurl = request.form.get('internal_url')
        # externalurl from form
        externalurl = request.form.get('external_url')
        group_name = request.form.get('group_name')
        # image_icon from form
        image_icon = request.form.get('icon_image')

        if not host or not container_name:
            flash('Host and Application (Container Name) are required.', 'danger')
            return render_template("add_entry.html", msg='error', entry=request.form)

        # Check for duplicates based on host and container_name
        existing = ServiceEntry.query.filter_by(host=host, container_name=container_name).first()
        if existing:
            flash(f"An entry for '{container_name}' on host '{host}' already exists.", 'danger')
            return render_template("add_entry.html", msg='duplicate', entry=request.form)

        # Handle boolean for internal_health_check (from HTML name 'internal_health_check')
        internal_health_check_enabled = request.form.get('internal_health_check') == 'on'
        # Handle boolean for external_health_check (from HTML name 'external_health_check')
        external_health_check_enabled = request.form.get('external_health_check') == 'on'
        # Handle boolean for is_static (from HTML name 'locked')
        is_static = request.form.get('locked') == 'on'

        # Attempt to fetch icon if not provided and container_name is available
        if not image_icon and container_name:
            # Sanitize container_name to be a valid part of a filename if needed,
            # or use a derived name. For simplicity, using container_name directly.
            # Your fetch_icon_if_missing might need adjustment if container_name contains chars invalid for filenames.
            derived_icon_name = container_name.lower().replace(" ", "-") # Example derivation
            image_icon = fetch_icon_if_missing(derived_icon_name)
            if image_icon:
                 logger.info(f"💡 Automatically fetched icon '{image_icon}' for new entry '{container_name}'.")
            else:
                 logger.info(f"⚠️ Could not automatically fetch icon for '{container_name}'. Manual entry recommended.")


        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            internalurl=internalurl,
            externalurl=externalurl,
            last_updated=datetime.now(),
            # last_api_update will be set by API calls, not manual add
            group_name=group_name if group_name else "zz_none", # Ensure default if empty
            internal_health_check_enabled=internal_health_check_enabled,
            external_health_check_enabled=external_health_check_enabled,
            image_icon=image_icon,
            is_static=is_static
            # Other fields like container_id, stack_name, docker_status, etc.,
            # are typically populated by API updates or could be added as optional form fields.
            # For now, they will be None or their default.
        )
        db.session.add(entry)
        db.session.commit()
        flash(f"Service entry '{container_name}' added successfully!", 'success')
        return redirect(url_for('tiled_dashboard')) # Or 'dashboard'

    return render_template("add_entry.html", msg='', entry={}) # Pass an empty dict for `entry` on GET

@app.route('/api/register', methods=['POST'])
def api_register():
    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {app.config['api_token']}"
    if auth_header != expected:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
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
        logger=logger
    )

    registry = image_meta["registry"]
    owner = image_meta["owner"]
    img_name = image_meta["image_name"]
    tag = image_meta["image_tag"]
    image_icon = image_meta["image_icon"]

    # Update or create entry
    entry = ServiceEntry.query.filter_by(container_name=data['container_name'], host=data['host']).first()
    if entry:
        if entry.is_static:
            logger.info(f"Skipping update for '{entry.container_name}' on '{entry.host}' — static lock enabled.")
            return jsonify({"status": "skipped", "reason": "static lock"}), 200
        entry.last_updated = datetime.now()
        entry.last_api_update = datetime.now()

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
        if data.get("group_name"):
            entry.group_name = data["group_name"]
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
            group_name=data.get('group_name') or "zz_none",
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





@app.route('/edit/<int:id>', methods=['GET', 'POST'])
def edit_entry(id):
    entry = ServiceEntry.query.get_or_404(id)

    # Track the referrer for redirecting after save
    raw_referrer = request.args.get('ref', '/')
    parsed = urlparse(raw_referrer)
    referrer = parsed.path
    if parsed.query:
        referrer += '?' + parsed.query

    # Safety check: prevent open redirect attacks
    if not referrer.startswith('/'):
        referrer = '/'

    if request.method == 'POST':
        # Handle delete action
        if 'delete' in request.form and request.form.get('delete_confirmation') == entry.container_name:
            logger.info(f"\U0001f5d1️ Deleting entry ID {id}: {entry.container_name} on {entry.host}")
            db.session.delete(entry)
            db.session.commit()
            flash(f"Service entry '{entry.container_name}' deleted successfully.", 'success')
            return redirect(referrer)
        elif 'delete' in request.form:
            flash(f"Deletion not confirmed for '{entry.container_name}'. Please type the name to confirm.", 'warning')
            return render_template("edit_entry.html", entry=entry, ref=referrer)

        # Update all editable fields
        entry.host = request.form.get('host', '').strip()
        entry.container_name = request.form.get('container_name', '').strip()
        entry.internalurl = request.form.get('internalurl', '').strip() or None
        entry.externalurl = request.form.get('externalurl', '').strip() or None
        entry.group_name = request.form.get('group_name', '').strip() or None

        new_image_icon = request.form.get('image_icon', '').strip()
        entry.image_icon = new_image_icon  # Always set explicitly, even blank

        if new_image_icon:
            icon_path = os.path.join(IMAGE_DIR, new_image_icon)
            if not os.path.exists(icon_path):
                try:
                    icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{new_image_icon}"
                    response = requests.get(icon_url, timeout=5)
                    if response.status_code == 200:
                        with open(icon_path, 'wb') as f:
                            f.write(response.content)
                        logger.info(f"\U0001f4e5 Downloaded manually supplied icon: {new_image_icon}")
                    else:
                        msg = f"Icon not found (HTTP {response.status_code}) at {icon_url}"
                        if app.debug:
                            logger.debug(msg)
                        else:
                            logger.warning(f"⚠️ {msg}")
                except Exception as e:
                    msg = f"Exception while downloading icon '{new_image_icon}': {e}"
                    if app.debug:
                        logger.debug(msg)
                    else:
                        logger.warning(f"⚠️ {msg}")

        elif not new_image_icon and request.form.get('force_update_icon') == 'true':
            derived_icon_name = entry.container_name.lower().replace(" ", "-")
            fetched_icon = fetch_icon_if_missing(derived_icon_name)
            if fetched_icon:
                entry.image_icon = fetched_icon
                logger.info(f"\U0001f4a1 Auto-fetched icon '{fetched_icon}' during edit for '{entry.container_name}'.")

        # Boolean fields
        entry.internal_health_check_enabled = request.form.get('internal_health_check_enabled') == 'on'
        entry.external_health_check_enabled = request.form.get('external_health_check_enabled') == 'on'
        entry.is_static = request.form.get('is_static') == 'on'

        entry.last_updated = datetime.now()

        try:
            db.session.commit()
            flash(f"Service entry '{entry.container_name}' updated successfully!", 'success')
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error updating entry {entry.id}: {e}")
            flash(f"Error updating entry: {str(e)}", 'danger')

        return redirect(referrer)

    return render_template("edit_entry.html", entry=entry, ref=referrer)



# Background health check loop
def health_check_loop():
    with app.app_context():
        while True:
            time.sleep(60)
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

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=health_check_loop, daemon=True).start()

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
# for 5 min testing
from apscheduler.triggers.interval import IntervalTrigger

def run_scheduled_backup():
    with app.app_context():
        config, _, _ = load_settings()
        backup_dir = config.get("backup_path", "/config/backups")
        days_to_keep = int(config.get("backup_days_to_keep", 7))

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


# Start background scheduler
scheduler = BackgroundScheduler()
#scheduler.add_job(run_scheduled_backup, CronTrigger(hour=0, minute=5))  # 12:05 AM
scheduler.add_job(run_scheduled_backup, IntervalTrigger(minutes=1))
scheduler.start()

app.debug = os.environ.get("FLASK_DEBUG", "0") == "1"

if __name__ == '__main__':
    logger.info(f"🚀 Starting app (debug={app.debug}) on port 8815")
    app.run(host='0.0.0.0', port=8815, debug=app.debug)
 