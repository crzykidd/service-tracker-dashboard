# Config
import os
API_TOKEN = os.getenv("API_TOKEN", "supersecrettoken")
STD_DOZZLE_URL = os.getenv("STD_DOZZLE_URL", "http://localhost:8888")
DATABASE_PATH = '/config/services.db'

from flask import Flask, request, jsonify, render_template, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import humanize
from dateutil import parser
import sqlite3
import threading
import time
import requests

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
    stack_name = db.Column(db.String(100), nullable=True)
    docker_status = db.Column(db.String(100), nullable=True)
    internal_health_check_enabled = db.Column(db.Boolean, nullable=True)
    internal_health_check_status = db.Column(db.String(100), nullable=True)
    internal_health_check_update = db.Column(db.String(100), nullable=True)
    external_health_check_enabled = db.Column(db.Boolean, nullable=True)
    external_health_check_status = db.Column(db.String(100), nullable=True)
    external_health_check_update = db.Column(db.String(100), nullable=True)

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
            'docker_status': self.docker_status,
            'internal_health_check_enabled': self.internal_health_check_enabled,
            'internal_health_check_status': self.internal_health_check_status,
            'internal_health_check_update': self.internal_health_check_update,
            'external_health_check_enabled': self.external_health_check_enabled,
            'external_health_check_status': self.external_health_check_status,
            'external_health_check_update': self.external_health_check_update,
        }

@app.template_filter('time_since')
def time_since(dt):
    if not dt:
        return "never"
    if isinstance(dt, str):
        dt = parser.parse(dt)
    return humanize.naturaltime(datetime.now() - dt)

# Ensure DB schema exists
print("\u2705 Checking for 'service_entry' table...")
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
        stack_name TEXT,
        docker_status TEXT,
        internal_health_check_enabled BOOLEAN,
        internal_health_check_status TEXT,
        internal_health_check_update TEXT,
        external_health_check_enabled BOOLEAN,
        external_health_check_status TEXT,
        external_health_check_update TEXT
    )
""")
conn.commit()
conn.close()
print("\u2705 DB schema ensured.")

@app.route('/')
def dashboard():
    msg = request.args.get('msg')
    query = request.args.get('q', '').lower()
    sort = request.args.get('sort', 'container_name')
    direction = request.args.get('dir', 'asc')
    reverse = direction == 'desc'

    entries = ServiceEntry.query.all()
    from collections import defaultdict
    grouped_entries = defaultdict(list)
    for e in entries:
        if e.internal_health_check_update:
            try:
                e.internal_health_check_parsed = parser.parse(e.internal_health_check_update)
            except Exception:
                e.internal_health_check_parsed = None
        else:
            e.internal_health_check_parsed = None
        grouped_entries[e.stack_name or 'Unassigned'].append(e)

    grouped_entries = dict(sorted(grouped_entries.items()))
    entries = [e for group in grouped_entries.values() for e in group]

    if query:
        entries = [e for e in entries if query in e.host.lower() or query in e.container_name.lower()]

    if sort == 'host':
        entries.sort(key=lambda x: x.host, reverse=reverse)
    else:
        entries.sort(key=lambda x: x.container_name, reverse=reverse)

    return render_template("dashboard.html", entries=entries, query=query, sort=sort, direction=direction, STD_DOZZLE_URL=STD_DOZZLE_URL, msg=msg, datetime=datetime)

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

    if not data.get('host') or not data.get('container_name'):
        return jsonify({"error": "Missing host or container_name"}), 400

    entry = ServiceEntry.query.filter_by(container_name=data['container_name']).first()

    def parse_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == 'true'
        return None

    if entry:
        # Update existing entry
        entry.host = data['host']
        entry.container_id = data.get('container_id')
        entry.internalurl = data.get('internalurl')
        entry.externalurl = data.get('externalurl')
        entry.stack_name = data.get('stack_name')
        entry.docker_status = data.get('docker_status')
        entry.internal_health_check_enabled = parse_bool(data.get('internal_health_check_enabled'))
        entry.external_health_check_enabled = parse_bool(data.get('external_health_check_enabled'))
        entry.last_updated = datetime.now()
    else:
        # Create new entry
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
            last_updated=datetime.now()
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
            print("\n".join(log_output), flush=True)

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    threading.Thread(target=health_check_loop, daemon=True).start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8815, debug=True)
