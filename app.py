# Config
import os
API_TOKEN = os.getenv("API_TOKEN", "supersecrettoken")
STD_DOZZLE_URL = os.getenv("STD_DOZZLE_URL", "http://localhost:8888")
DATABASE_PATH = '/config/services.db'

from flask import Flask, request, jsonify, render_template_string, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import humanize
import sqlite3

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DATABASE_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

@app.template_filter('time_since')
def time_since(dt):
    return humanize.naturaltime(datetime.now() - dt)

# Ensure DB file exists and patch schema early — BEFORE SQLAlchemy loads
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
        last_updated TEXT NOT NULL
    )
""")
conn.commit()
conn.close()
print("\u2705 DB schema ensured.")

db = SQLAlchemy(app)

class ServiceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    host = db.Column(db.String(100), nullable=False)
    container_name = db.Column(db.String(100), nullable=False)
    container_id = db.Column(db.String(100), nullable=True)
    internalurl = db.Column(db.String(255), nullable=True)
    externalurl = db.Column(db.String(255), nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False)

    def to_dict(self):
        return {
            'id': self.id,
            'host': self.host,
            'container_name': self.container_name,
            'container_id': self.container_id,
            'internalurl': self.internalurl,
            'externalurl': self.externalurl,
            'last_updated': self.last_updated.strftime('%Y-%m-%d %H:%M:%S')
        }

DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html data-bs-theme=\"dark\">
<head>
  <title>Service Dashboard</title>
  <link href=\"https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css\" rel=\"stylesheet\">
<meta http-equiv=\"refresh\" content=\"30\">
</head>
<body class=\"bg-dark text-light\">
<nav class=\"navbar navbar-expand-lg navbar-dark bg-primary fixed-top\">
  <div class=\"container-fluid\">
    <a class=\"navbar-brand\" href=\"/\">Service Dashboard</a>
    <div class=\"d-flex\">
      <a href=\"/add\" class=\"btn btn-light btn-sm\">Add New Entry</a>
    </div>
  </div>
</nav>
<div style=\"height: 70px;\"></div>
<div class=\"container mt-5\">
  {% if msg == 'deleted' %}
    <div class=\"alert alert-danger\" role=\"alert\">Entry deleted successfully.</div>
  {% endif %}
  <h1 class=\"mb-4\">Service Dashboard</h1>
  <div class=\"d-flex justify-content-between align-items-center mb-3\">
    <a href=\"/add\" class=\"btn btn-success\">Add New Entry</a>
  </div>
  <div class=\"row g-3 mb-4\">
    <div class=\"col-auto\">
      <input type=\"text\" id=\"filterInput\" class=\"form-control\" placeholder=\"Filter...\">
    </div>
  </div>

  <table class=\"table table-hover table-bordered table-dark\">
  <thead class=\"table-secondary\">
    <tr>
      <th data-sort-key=\"host\">Host</th>
      <th data-sort-key=\"container_name\">Container Name</th>
      <th data-sort-key=\"container_id\">Container ID</th>
      <th>Internal URL</th>
      <th>External URL</th>
      <th>Last Updated</th>
      <th>Actions</th>
    </tr>
  </thead>
  <tbody>
    {% for entry in entries %}
    <tr>
      <td>{{ entry.host }}</td>
      <td>{{ entry.container_name }}</td>
      <td>{{ entry.container_id or '' }}</td>
      <td>{% if entry.internalurl %}<a href=\"{{ entry.internalurl }}\" target=\"_blank\" class=\"btn btn-sm btn-outline-info\">Internal</a>{% endif %}</td>
      <td>{% if entry.externalurl %}<a href=\"{{ entry.externalurl }}\" target=\"_blank\" class=\"btn btn-sm btn-outline-success\">External</a>{% endif %}</td>
      <td>{{ (entry.last_updated|time_since) }}</td>
      <td><a href=\"/edit/{{ entry.id }}\" class=\"btn btn-sm btn-outline-warning\">Edit</a></td>
    </tr>
    {% endfor %}
  </tbody>
  </table>
</div>
<script>
  document.addEventListener('DOMContentLoaded', function () {
    const input = document.getElementById('filterInput');
    input.addEventListener('input', function () {
      const filter = input.value.toLowerCase();
      const rows = document.querySelectorAll('table tbody tr');
      rows.forEach(row => {
        const host = row.children[0].innerText.toLowerCase();
        const name = row.children[1].innerText.toLowerCase();
        const id = row.children[2].innerText.toLowerCase();
        row.style.display = (host.includes(filter) || name.includes(filter) || id.includes(filter)) ? '' : 'none';
      });
    });
  });
    const table = document.querySelector('table');
    const headers = table.querySelectorAll('th[data-sort-key]');
    headers.forEach((header, index) => {
      header.style.cursor = 'pointer';
      header.addEventListener('click', () => {
        const rows = Array.from(table.querySelectorAll('tbody tr'));
        const direction = header.dataset.direction === 'asc' ? 'desc' : 'asc';
        header.dataset.direction = direction;

        rows.sort((a, b) => {
          const textA = a.cells[index].innerText.toLowerCase();
          const textB = b.cells[index].innerText.toLowerCase();
          if (textA < textB) return direction === 'asc' ? -1 : 1;
          if (textA > textB) return direction === 'asc' ? 1 : -1;
          return 0;
        });

        const tbody = table.querySelector('tbody');
        rows.forEach(row => tbody.appendChild(row));
      });
    });
  });
</script>
</body>
</html>
"""

ADD_TEMPLATE = """
<!DOCTYPE html>
<html data-bs-theme='dark'>
<head>
  <title>Add Service Entry</title>
  <link href='https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css' rel='stylesheet'>
</head>
<body class='bg-dark text-light'>
  <div class='container mt-5'>
    {% if msg == 'error' %}<div class='alert alert-danger'>Host and Container Name are required.</div>{% elif msg == 'duplicate' %}<div class='alert alert-warning'>An entry with this Container Name or Container ID already exists.</div>{% endif %}
    <h1>Add Service Entry</h1>
    <form method='post'>
      <div class='mb-3'>
        <label class='form-label'>Host</label>
        <input class='form-control' name='host' required />
      </div>
      <div class='mb-3'>
        <label class='form-label'>Container Name</label>
        <input class='form-control' name='container_name' required />
      </div>
      <div class='mb-3'>
        <label class='form-label'>Container ID</label>
        <input class='form-control' name='container_id' />
      </div>
      <div class='mb-3'>
        <label class='form-label'>Internal URL</label>
        <input class='form-control' name='internalurl' />
      </div>
      <div class='mb-3'>
        <label class='form-label'>External URL</label>
        <input class='form-control' name='externalurl' />
      </div>
      <button type='submit' class='btn btn-primary'>Submit</button>
      <a href='/' class='btn btn-secondary'>Cancel</a>
    </form>
  </div>
</body>
</html>
"""

EDIT_TEMPLATE = """
<!-- full edit-entry HTML omitted for brevity -->
"""

@app.route('/')
def dashboard():
    msg = request.args.get('msg')
    query = request.args.get('q', '').lower()
    sort = request.args.get('sort', 'container_name')
    direction = request.args.get('dir', 'asc')
    reverse = direction == 'desc'

    entries = ServiceEntry.query.all()
    if query:
        entries = [e for e in entries if query in e.host.lower() or query in e.container_name.lower()]

    if sort == 'host':
        entries.sort(key=lambda x: x.host, reverse=reverse)
    else:
        entries.sort(key=lambda x: x.container_name, reverse=reverse)

    return render_template_string(DASHBOARD_TEMPLATE, entries=entries, query=query, sort=sort, direction=direction, STD_DOZZLE_URL=STD_DOZZLE_URL, msg=msg)

@app.route('/add', methods=['GET', 'POST'])
def add_entry():
    if request.method == 'POST':
        host = request.form.get('host')
        container_name = request.form.get('container_name')
        container_id = request.form.get('container_id')
        internalurl = request.form.get('internalurl')
        externalurl = request.form.get('externalurl')

        if not host or not container_name:
            return render_template_string(ADD_TEMPLATE, msg='error')

        existing = ServiceEntry.query.filter(
            (ServiceEntry.container_name == container_name) |
            (ServiceEntry.container_id == container_id if container_id else False)
        ).first()
        if existing:
            return render_template_string(ADD_TEMPLATE, msg='duplicate')  # Duplicate name or container ID

        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            container_id=container_id,
            internalurl=internalurl,
            externalurl=externalurl,
            last_updated=datetime.now()
        )
        db.session.add(entry)
        db.session.commit()
        return redirect(url_for('dashboard', msg='added'))
    return render_template_string(ADD_TEMPLATE, msg='')

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
        entry.last_updated = datetime.now()
        db.session.commit()
        return redirect(url_for('dashboard'))
    return render_template_string(EDIT_TEMPLATE, entry=entry)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8815, debug=True)
