# Config
import os
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory, make_response
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import humanize
from dateutil import parser
import sqlite3
import threading
import time
import requests
from collections import defaultdict


API_TOKEN = os.getenv("API_TOKEN", "supersecrettoken")
STD_DOZZLE_URL = os.getenv("STD_DOZZLE_URL", "http://localhost:8888")
DATABASE_PATH = '/config/services.db'
LOGFILE = '/config/std.log'
IMAGE_DIR = '/config/images'

# Ensure the directory exists
os.makedirs(IMAGE_DIR, exist_ok=True)

# for image lookup
failed_icon_cache = {}  # image_icon -> last_failed_time
RETRY_INTERVAL = timedelta(minutes=60)  # Adjust this as needed
# === Logging Setup ===
log_formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] %(message)s')
log_handler = RotatingFileHandler(
    LOGFILE, maxBytes=100 * 1024, backupCount=4
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
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

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
        }

def fetch_icon_if_missing(image_name):
    if not image_name:
        return None
    filename = f"{image_name}.svg"
    local_path = os.path.join(IMAGE_DIR, filename)
    if os.path.exists(local_path):
        return filename

    icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{filename}"
    try:
        response = requests.get(icon_url, timeout=5)
        if response.status_code == 200:
            with open(local_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"⬇️ Downloaded icon for {image_name} to {local_path}")
            return filename
        else:
            logger.warning(f"⚠️ Icon not found for {image_name} (HTTP {response.status_code})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to download icon for {image_name}: {e}")
    return None

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
        key = getattr(entry, group_by) or 'zz_none'
        grouped_entries[key].append(entry)

    # Sort group keys alphabetically
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
    
@app.route("/dbdump")
def db_dump():
    entries = ServiceEntry.query.order_by(ServiceEntry.id).all()
    return render_template("dbdump.html", entries=entries)    

@app.route('/images/<path:filename>')
def serve_image(filename):
    response = make_response(send_from_directory(IMAGE_DIR, filename))
    response.headers['Cache-Control'] = 'public, max-age=86400'  # cache for 1 day
    return response

@app.route('/add', methods=['GET', 'POST'])
def add_entry():
    if request.method == 'POST':
        host = request.form.get('host')
        container_name = request.form.get('container_name')
        container_id = request.form.get('container_id')
        internalurl = request.form.get('internalurl')
        externalurl = request.form.get('externalurl')

        if not host or not container_name:
            return render_template("add_entry.html", msg='error')

        existing = ServiceEntry.query.filter(
            (ServiceEntry.container_name == container_name) |
            (ServiceEntry.container_id == container_id if container_id else False)
        ).first()
        if existing:
            return render_template("add_entry.html", msg='duplicate')

        raw_enabled = request.form.get('internal_health_check_enabled')
        internal_health_check_enabled = True if raw_enabled == 'true' else False if raw_enabled == 'false' else None

        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            container_id=container_id,
            internalurl=internalurl,
            externalurl=externalurl,
            stack_name=request.form.get('stack_name'),
            docker_status=request.form.get('docker_status'),
            last_updated=datetime.now(),
            internal_health_check_enabled=internal_health_check_enabled
        )
        db.session.add(entry)

        raw_external_enabled = request.form.get('external_health_check_enabled')
        entry.external_health_check_enabled = True if raw_external_enabled == 'true' else False if raw_external_enabled == 'false' else None
        entry.external_health_check_status = request.form.get('external_health_check_status')
        entry.external_health_check_update = request.form.get('external_health_check_update')

        if entry.external_health_check_enabled and entry.externalurl:
            try:
                response = requests.get(entry.externalurl, timeout=5)
                entry.external_health_check_status = str(response.status_code)
            except Exception as e:
                entry.external_health_check_status = f"Error: {type(e).__name__}"
            entry.external_health_check_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        db.session.commit()
        return redirect(url_for('dashboard', msg='added'))

    return render_template("add_entry.html", msg='')

@app.route('/api/register', methods=['POST'])
def api_register():
    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {API_TOKEN}"
    if auth_header != expected:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    if app.debug:
        logger.info("🔍 Received API payload:")
        for k, v in data.items():
            logger.info(f"    {k}: {v}")

    if not data.get('host') or not data.get('container_name'):
        return jsonify({"error": "Missing host or container_name"}), 400

    # Parse image_name into components
    image_raw = data.get("image_name", "")
    registry, owner, img_name, tag = None, None, None, None

    if image_raw:
        tag_split = image_raw.split(":")
        base = tag_split[0]
        tag = tag_split[1] if len(tag_split) > 1 else None
        parts = base.split("/")
        if len(parts) == 3:
            registry, owner, img_name = parts
        elif len(parts) == 2:
            owner, img_name = parts
        elif len(parts) == 1:
            img_name = parts[0]

    # Use provided image_icon or try to fetch from known icon repo
    image_icon = data.get("image_icon")
    if not image_icon and img_name:
        image_icon = fetch_icon_if_missing(img_name)

    elif image_icon:
        icon_path = os.path.join(IMAGE_DIR, image_icon)
        now = datetime.now()
        last_fail = failed_icon_cache.get(image_icon)

        if not os.path.exists(icon_path) and (not last_fail or now - last_fail > RETRY_INTERVAL):
            try:
                icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{image_icon}"
                response = requests.get(icon_url, timeout=5)
                if response.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"⬇️ Downloaded explicitly provided icon: {image_icon}")
                    failed_icon_cache.pop(image_icon, None)
                else:
                    failed_icon_cache[image_icon] = now
                    logger.warning(f"⚠️ Could not download image_icon '{image_icon}' — status {response.status_code}")
            except Exception as e:
                failed_icon_cache[image_icon] = now
                logger.warning(f"⚠️ Failed to fetch image_icon '{image_icon}': {e}")



    # If image_icon was explicitly provided, check and download if needed
    if image_icon and not os.path.exists(os.path.join(IMAGE_DIR, image_icon)):
        try:
            icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{image_icon}"
            response = requests.get(icon_url, timeout=5)
            if response.status_code == 200:
                with open(os.path.join(IMAGE_DIR, image_icon), 'wb') as f:
                    f.write(response.content)
                logger.info(f"⬇️ Downloaded explicitly provided icon: {image_icon}")
            else:
                logger.warning(f"⚠️ Could not download image_icon '{image_icon}' — status {response.status_code}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to fetch image_icon '{image_icon}': {e}")
    # Convert booleans
    def parse_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == 'true'
        return None

    # Update or create entry
    entry = ServiceEntry.query.filter_by(container_name=data['container_name']).first()
    if entry:
        entry.host = data['host']
        entry.container_id = data.get('container_id')
        entry.internalurl = data.get('internalurl')
        entry.externalurl = data.get('externalurl')
        entry.stack_name = data.get('stack_name')
        entry.docker_status = data.get('docker_status')
        entry.internal_health_check_enabled = parse_bool(data.get('internal_health_check_enabled'))
        entry.external_health_check_enabled = parse_bool(data.get('external_health_check_enabled'))
        entry.group_name = data.get('group_name') or "zz_none"
        entry.started_at = data.get('started_at')
        entry.last_updated = datetime.now()
        entry.last_api_update = datetime.now()
        entry.image_registry = registry
        entry.image_owner = owner
        entry.image_name = img_name
        entry.image_icon = image_icon
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
    if request.method == 'POST':
        if 'delete' in request.form:
            db.session.delete(entry)
            db.session.commit()
            return redirect(url_for('dashboard'))


        entry.host = request.form.get('host')
        entry.container_name = request.form.get('container_name')
        entry.container_id = request.form.get('container_id')
        entry.internalurl = request.form.get('internalurl')
        entry.externalurl = request.form.get('externalurl')
        entry.stack_name = request.form.get('stack_name')
        entry.docker_status = request.form.get('docker_status')

        raw_enabled = request.form.get('internal_health_check_enabled')
        entry.internal_health_check_enabled = True if raw_enabled == 'true' else False if raw_enabled == 'false' else None
        entry.internal_health_check_status = request.form.get('internal_health_check_status')
        entry.internal_health_check_update = request.form.get('internal_health_check_update')

        raw_external_enabled = request.form.get('external_health_check_enabled')
        entry.external_health_check_enabled = True if raw_external_enabled == 'true' else False if raw_external_enabled == 'false' else None
        entry.external_health_check_status = request.form.get('external_health_check_status')
        entry.external_health_check_update = request.form.get('external_health_check_update')

        for field in ['internal_health_check_update', 'external_health_check_update']:
            dt_val = getattr(entry, field)
            if dt_val and isinstance(dt_val, str) and " " in dt_val:
                setattr(entry, field, dt_val.replace(" ", "T")[:16])

        entry.last_updated = datetime.now()
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template("edit_entry.html", entry=entry)

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

app.debug = os.environ.get("FLASK_DEBUG", "0") == "1"

if __name__ == '__main__':
    logger.info(f"🚀 Starting app (debug={app.debug}) on port 8815")
    app.run(host='0.0.0.0', port=8815, debug=app.debug)
 