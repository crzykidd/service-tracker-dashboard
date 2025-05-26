
from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

API_TOKEN = os.getenv("API_TOKEN", "supersecrettoken")
DATABASE_PATH = '/config/services.db'

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

import sqlite3

# Ensure DB table exists before any routes
with app.app_context():
    print("✅ Checking for 'service_entry' table...")
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS service_entry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host TEXT NOT NULL,
            service TEXT NOT NULL,
            fqdn TEXT NOT NULL,
            last_updated TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()
    print("✅ DB schema ensured.")


class ServiceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(100), nullable=False)
    service = db.Column(db.String(100), nullable=False)
    fqdn = db.Column(db.String(255), nullable=False)
    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'host': self.host,
            'service': self.service,
            'fqdn': self.fqdn,
            'last_updated': self.last_updated.strftime('%Y-%m-%d %H:%M:%S')
        }



@app.route('/api/register', methods=['POST'])
def register():
    token = request.headers.get('Authorization')
    if token != f"Bearer {API_TOKEN}":
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    host = data.get('host')
    service = data.get('service')
    fqdn = data.get('fqdn')
    if not all([host, service, fqdn]):
        return jsonify({'error': 'Missing fields'}), 400

    existing = ServiceEntry.query.filter_by(service=service).first()
    if existing:
        existing.host = host
        existing.fqdn = fqdn
        existing.last_updated = datetime.utcnow()
    else:
        new_entry = ServiceEntry(host=host, service=service, fqdn=fqdn)
        db.session.add(new_entry)

    db.session.commit()
    return jsonify({'status': 'success'})

@app.route('/')
def dashboard():
    query = request.args.get('q', '').lower()
    sort = request.args.get('sort', 'service')
    entries = ServiceEntry.query.all()
    if query:
        entries = [e for e in entries if query in e.host.lower() or query in e.service.lower()]
    if sort == 'host':
        entries.sort(key=lambda x: x.host)
    else:
        entries.sort(key=lambda x: x.service)

    return render_template_string(DASHBOARD_TEMPLATE, entries=entries, query=query, sort=sort)

@app.route('/add', methods=['GET', 'POST'])
def add_entry():
    if request.method == 'POST':
        host = request.form.get('host')
        service = request.form.get('service')
        fqdn = request.form.get('fqdn')
        if host and service and fqdn:
            entry = ServiceEntry(host=host, service=service, fqdn=fqdn)
            db.session.add(entry)
            db.session.commit()
            return redirect(url_for('dashboard'))
    return render_template_string(ADD_TEMPLATE)

DASHBOARD_TEMPLATE = """<html>
<head>
  <title>Service Tracker</title>
  <style>
    table { width: 100%; border-collapse: collapse; }
    th, td { border: 1px solid #ccc; padding: 8px; }
    th { background: #f0f0f0; cursor: pointer; }
  </style>
</head>
<body>
  <h1>Service Dashboard</h1>
  <form method="get">
    <input type="text" name="q" placeholder="Search..." value="{{ query }}" />
    <button type="submit">Search</button>
    <a href="/add">Add Service</a>
  </form>
  <table>
    <tr>
      <th><a href="?sort=host&q={{ query }}">Host</a></th>
      <th><a href="?sort=service&q={{ query }}">Service</a></th>
      <th>Last Updated</th>
    </tr>
    {% for entry in entries %}
    <tr>
      <td>
        {{ entry.host }}<br>
        <a href="http://{{ entry.host }}:8888" target="_blank">Dozzle</a> |
        <a href="http://{{ entry.host }}:9000" target="_blank">Komodo</a>
      </td>
      <td><a href="https://{{ entry.fqdn }}" target="_blank">{{ entry.service }}</a></td>
      <td>{{ entry.last_updated }}</td>
    </tr>
    {% endfor %}
  </table>
</body>
</html>"""

ADD_TEMPLATE = """<html>
<head><title>Add Service</title></head>
<body>
  <h1>Add Service Entry</h1>
  <form method="post">
    <label>Host: <input type="text" name="host" /></label><br>
    <label>Service: <input type="text" name="service" /></label><br>
    <label>FQDN: <input type="text" name="fqdn" /></label><br>
    <button type="submit">Submit</button>
  </form>
  <a href="/">Back to Dashboard</a>
</body>
</html>"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8815, debug=True)
