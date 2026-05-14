"""SQLAlchemy models for Service Tracker Dashboard.

Single source of truth for the database schema. Migrations track
changes here. Imported by `alembic/env.py` so model classes register
themselves with `db.metadata` before autogenerate runs.
"""

from datetime import datetime, timedelta

from flask_login import UserMixin
from sqlalchemy import func, select
from sqlalchemy.orm import column_property
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


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
    # Exposure observations (v0.6.0 — interpreter mechanism). Many rows
    # per service possible (one per interpreter layer that sees the
    # container). Replaced wholesale on register when the payload
    # carries `exposure_observations`. See ServiceExposure below.
    exposures = db.relationship(
        'ServiceExposure',
        backref='service_entry',
        lazy=True,
        cascade='all, delete-orphan',
    )
    sort_priority = db.Column(db.Integer, nullable=True, default=None)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=True)
    # Captured from the most recent notifier register payload for this
    # service. Lets the planned "export overridden labels" feature
    # diff the user-edited value against what the notifier reported,
    # without losing one to the other on every register call.
    # Populated by the v0.5.0 register handler; read by no one yet.
    notifier_reported_group_name = db.Column(db.String(100), nullable=True)
    notifier_reported_sort_priority = db.Column(db.Integer, nullable=True, default=None)
    # Observed container facts, captured from the notifier (v0.6.0+).
    # Pure observation — overwritten on every register call. Notifier
    # v0.3.2+ populates these; rows from older notifiers remain NULL.
    # networks: [{"name": "...", "aliases": ["..."]}]
    # exposed_ports: ["5173/tcp", "9000/tcp"]
    # published_ports: [{"container_port": 5173, "protocol": "tcp",
    #                    "host_ip": "0.0.0.0", "host_port": 8080}]
    networks = db.Column(db.JSON, nullable=True)
    exposed_ports = db.Column(db.JSON, nullable=True)
    published_ports = db.Column(db.JSON, nullable=True)

    # URL provenance (v0.6.0 — exposure interpreter). Tracks which actor
    # last wrote each URL so the synthesizer doesn't clobber UI edits or
    # explicit labels. Values: "ui_edit", "explicit_label",
    # "synthesized", or NULL. Ordering: ui_edit > explicit_label >
    # synthesized > NULL. See synthesizer.py for the merge rules.
    internalurl_source = db.Column(db.String(20), nullable=True)
    externalurl_source = db.Column(db.String(20), nullable=True)

    __table_args__ = (
        db.Index('ix_service_entry_host_container_name', 'host', 'container_name'),
    )

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
            'networks': self.networks,
            'exposed_ports': self.exposed_ports,
            'published_ports': self.published_ports,
            'internalurl_source': self.internalurl_source,
            'externalurl_source': self.externalurl_source,
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

class ServiceExposure(db.Model):
    """One observation from one interpreter layer about how a service
    is exposed (Traefik sees hostname X with TLS, Dockflare sees
    hostname Y, etc.). Many rows per ServiceEntry possible — one per
    layer that recognizes the container.

    Pure observation, owned by the notifier. The register handler
    replaces all rows for a service wholesale when the payload carries
    `exposure_observations`. The synthesizer reads these rows to
    populate ServiceEntry.internalurl / externalurl per operator-
    configured direction mapping (see settings_store.py).
    """
    __tablename__ = 'service_exposure'

    id = db.Column(db.Integer, primary_key=True)
    service_entry_id = db.Column(
        db.Integer,
        db.ForeignKey('service_entry.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    layer = db.Column(db.String(64), nullable=False)
    hostname = db.Column(db.String(255), nullable=True)
    tls = db.Column(db.Boolean, nullable=True)
    path_prefix = db.Column(db.String(255), nullable=True)
    auth = db.Column(db.String(128), nullable=True)
    details = db.Column(db.JSON, nullable=True)
    last_updated = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f'<ServiceExposure {self.layer} svc={self.service_entry_id} host={self.hostname}>'


class Setting(db.Model):
    """KV-style store for operator-editable runtime settings.

    Distinct from `settings.yml` / `app.config`: those are loaded once
    at startup and treated as immutable for the lifetime of the
    process. `Setting` rows can be edited via the web UI and are
    re-read on every access.

    Introduced in v0.6.0 to back the per-interpreter direction
    mappings used by the exposure synthesizer. Values are JSON so we
    can store dicts/lists without inventing a richer schema for one
    feature.
    """
    __tablename__ = 'setting'

    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.JSON, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Setting {self.key}={self.value!r}>'


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

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        self.password_changed_at = datetime.utcnow()

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
