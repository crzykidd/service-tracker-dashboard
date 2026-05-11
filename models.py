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
