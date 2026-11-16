"""SQLAlchemy models for Service Tracker Dashboard.

Single source of truth for the database schema. Migrations track
changes here. Imported by `alembic/env.py` so model classes register
themselves with `db.metadata` before autogenerate runs.
"""

from datetime import datetime, timedelta, timezone

from flask import current_app, has_app_context
from flask_login import UserMixin
from sqlalchemy import func, select
from sqlalchemy.orm import column_property
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

DEFAULT_STALE_AFTER_MINUTES = 5

SOURCE_NOTIFIER = 'notifier'
SOURCE_MANUAL = 'manual'
VALID_SOURCES = (SOURCE_NOTIFIER, SOURCE_MANUAL)

# Health checks (v0.7.0). URL kinds follow the entry's internal/external URL
# (target is NULL); 'service' checks are separate rows (added in a later chunk).
CHECK_KIND_INTERNAL = 'internal_url'
CHECK_KIND_EXTERNAL = 'external_url'
CHECK_KIND_SERVICE = 'service'
# Container state reported by the notifier (one per notifier entry, no target).
CHECK_KIND_CONTAINER = 'container'
URL_CHECK_KINDS = (CHECK_KIND_INTERNAL, CHECK_KIND_EXTERNAL)
CHECK_KINDS = URL_CHECK_KINDS + (CHECK_KIND_SERVICE, CHECK_KIND_CONTAINER)
CHECK_TYPE_HTTP = 'http'
CHECK_TYPE_TCP = 'tcp'
CHECK_TYPE_PING = 'ping'
CHECK_TYPES = (CHECK_TYPE_HTTP, CHECK_TYPE_TCP, CHECK_TYPE_PING)
# The container check's own type; not selectable on a service check.
CHECK_TYPE_DOCKER = 'docker'
CONTAINER_CHECK_NAME = 'Container'
CHECK_MODE_STATUS = 'status'
CHECK_MODE_BODY = 'body'
CHECK_MODES = (CHECK_MODE_STATUS, CHECK_MODE_BODY)

_URL_CHECK_NAMES = {CHECK_KIND_INTERNAL: 'Internal URL', CHECK_KIND_EXTERNAL: 'External URL'}
# Short names the templates and routes use: 'internal' / 'external'.
_URL_CHECK_ALIASES = {'internal': CHECK_KIND_INTERNAL, 'external': CHECK_KIND_EXTERNAL}


class ServiceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # NULL host is allowed for manual entries (v0.7.0).
    host = db.Column(db.String(100), nullable=True)
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
    # Health checks (v0.7.0): two URL-kind rows per entry plus any service
    # checks. Config and cached state live here, not on service_entry.
    checks = db.relationship(
        'HealthCheck',
        backref='service_entry',
        lazy=True,
        cascade='all, delete-orphan',
        order_by='HealthCheck.id',
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
    # v0.4.0+ populates these; rows from older notifiers remain NULL.
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

    # Soft delete (v0.6.9). NULL = active; a timestamp = deleted at that
    # moment and recoverable from Settings -> Deleted until the purge job
    # (deleted_retention_days) hard-deletes it. Naive local time, like
    # last_updated. Use ServiceEntry.active() for anything user-facing.
    deleted_at = db.Column(db.DateTime, nullable=True, index=True)

    # Per-service health-check options (v0.6.9). Operator-curated, never
    # register fields. NULL timeout = use the global health_check_timeout.
    health_check_timeout = db.Column(db.Integer, nullable=True)
    health_check_verify_tls = db.Column(
        db.Boolean, nullable=False, default=True, server_default=db.true()
    )

    # Entry source (v0.7.0): 'notifier' (created/kept current by
    # /api/v1/register) or 'manual' (created on the Add page). A register
    # that matches an unlocked manual entry adopts it (-> 'notifier').
    # `is_static` is only the lock; it no longer means "manual".
    source = db.Column(
        db.String(16), nullable=False, default=SOURCE_NOTIFIER, server_default=SOURCE_NOTIFIER
    )
    description = db.Column(db.String(255), nullable=True)

    __table_args__ = (
        db.Index('ix_service_entry_host_container_name', 'host', 'container_name'),
    )

    @classmethod
    def active(cls):
        """Query of entries that are not soft-deleted."""
        return cls.query.filter(cls.deleted_at.is_(None))

    @classmethod
    def deleted(cls):
        """Query of soft-deleted entries (newest deletion first)."""
        return cls.query.filter(cls.deleted_at.isnot(None)).order_by(cls.deleted_at.desc())

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
            # Legacy keys are kept (values read from the check rows) so an
            # older STD can still restore a backup made by this version.
            'internal_health_check_enabled': self.internal_check_enabled,
            'internal_health_check_status': _legacy_status(self.url_check('internal')),
            'internal_health_check_update': _legacy_update(self.url_check('internal')),
            'external_health_check_enabled': self.external_check_enabled,
            'external_health_check_status': _legacy_status(self.url_check('external')),
            'external_health_check_update': _legacy_update(self.url_check('external')),
            'image_registry': self.image_registry,
            'image_owner': self.image_owner,
            'image_name': self.image_name,
            'image_tag': self.image_tag,
            'started_at': self.started_at,
            'image_icon': self.image_icon,
            'is_static': self.is_static,
            'source': self.source,
            'description': self.description,
            'sort_priority': self.sort_priority,
            'networks': self.networks,
            'exposed_ports': self.exposed_ports,
            'published_ports': self.published_ports,
            'internalurl_source': self.internalurl_source,
            'externalurl_source': self.externalurl_source,
            'health_check_timeout': self.url_check_timeout,
            'health_check_verify_tls': self.url_check_verify_tls,
            'checks': [c.to_config() for c in self.checks],
            'deleted_at': self.deleted_at.strftime('%Y-%m-%d %H:%M:%S') if self.deleted_at else None,
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

    def url_check(self, which):
        """The entry's URL-kind check row: 'internal' / 'external' (or the
        full kind name). None when the row does not exist yet."""
        kind = _URL_CHECK_ALIASES.get(which, which)
        for check in self.checks:
            if check.kind == kind:
                return check
        return None

    @property
    def container_check(self):
        """The notifier entry's Container check row, or None."""
        for check in self.checks:
            if check.kind == CHECK_KIND_CONTAINER:
                return check
        return None

    @property
    def service_checks(self):
        """Service-kind checks, in creation order."""
        return [c for c in self.checks if c.kind == CHECK_KIND_SERVICE]

    @property
    def internal_check_enabled(self):
        check = self.url_check('internal')
        return bool(check and check.enabled)

    @property
    def external_check_enabled(self):
        check = self.url_check('external')
        return bool(check and check.enabled)

    @property
    def url_check_timeout(self):
        """Timeout shared by the two URL checks (NULL = global default)."""
        check = self.url_check('internal') or self.url_check('external')
        return check.timeout_seconds if check else None

    @property
    def url_check_verify_tls(self):
        check = self.url_check('internal') or self.url_check('external')
        return True if check is None else check.verify_tls is not False

    @property
    def is_manual(self):
        """True for entries created on the Add page (no notifier behind them)."""
        return self.source == SOURCE_MANUAL

    @property
    def is_docker_status_stale(self):
        """True when the notifier hasn't reported in within `stale_after_minutes`.

        Manual and locked entries are never stale. A dynamic entry with no
        `last_api_update` (never registered) counts as stale; the Tiled view
        shows that case separately as "no update received".
        """
        if self.is_manual or self.is_static:
            return False
        if self.last_api_update:
            return (datetime.now() - self.last_api_update) > timedelta(minutes=_stale_after_minutes())
        return True


def _legacy_status(check):
    """Pre-0.7 status string for a URL check row, for backups that older STD
    versions can restore: the status code, else `Error: <ExceptionName>`.
    NULL when the check has not run. Derived from the row (the legacy
    columns are no longer written)."""
    if check is None or check.last_ok is None:
        return None
    code = check.last_status_code
    if code is not None and (check.last_ok or code >= 400):
        return str(code)
    name = (check.last_message or '').split(':', 1)[0].strip()
    return f"Error: {name or 'CheckFailed'}"


def _legacy_update(check):
    """Last-checked time as the server-local string older STD stored."""
    if check is None or check.last_checked_at is None:
        return None
    local = check.last_checked_at.replace(tzinfo=timezone.utc).astimezone()
    return local.strftime('%Y-%m-%d %H:%M:%S')


def ensure_url_checks(entry):
    """Make sure `entry` has exactly its two URL-kind check rows.

    Idempotent: adds only the missing ones (disabled, global timeout, verify
    TLS on). Used by every path that creates or edits an entry. Caller commits.
    """
    for kind in URL_CHECK_KINDS:
        if entry.url_check(kind) is None:
            entry.checks.append(HealthCheck(
                kind=kind,
                name=_URL_CHECK_NAMES[kind],
                check_type=CHECK_TYPE_HTTP,
                mode=CHECK_MODE_STATUS,
                verify_tls=True,
                enabled=False,
                consecutive_failures=0,
            ))
    return entry


def ensure_container_check(entry):
    """Give a notifier entry its one Container check (enabled by default).

    Manual entries get none. Idempotent. Caller commits.
    """
    if entry.source == SOURCE_NOTIFIER and entry.container_check is None:
        entry.checks.append(HealthCheck(
            kind=CHECK_KIND_CONTAINER,
            name=CONTAINER_CHECK_NAME,
            check_type=CHECK_TYPE_DOCKER,
            mode=CHECK_MODE_STATUS,
            verify_tls=True,
            enabled=True,
            consecutive_failures=0,
        ))
    return entry


def evaluate_container(entry, now=None):
    """(ok, message) for the entry's Container check, from what the notifier
    last reported. A pure read; message is None when ok."""
    now = now or datetime.now()
    if entry.last_api_update is None:
        return False, 'No update from notifier yet'
    age = now - entry.last_api_update
    if age > timedelta(minutes=_stale_after_minutes()):
        return False, f'No update from notifier for {int(age.total_seconds() // 60)} min'
    status = (entry.docker_status or '').strip()
    if status.lower() == 'running':
        return True, None
    return False, f'Container {status}' if status else 'Container status unknown'


def check_counts(entry, check):
    """True when `check` can run and takes part in the rollup: enabled, and
    - URL kinds: the entry has that URL; service: it has a target;
    - container: the entry is an unlocked notifier entry (a locked entry gets
      no registers, so its container state is frozen and not evidence)."""
    if not check.enabled:
        return False
    if check.kind == CHECK_KIND_CONTAINER:
        return entry.source == SOURCE_NOTIFIER and not entry.is_static
    if check.kind == CHECK_KIND_INTERNAL:
        target = entry.internalurl
    elif check.kind == CHECK_KIND_EXTERNAL:
        target = entry.externalurl
    else:
        target = check.target
    return bool((target or '').strip())


def _stale_after_minutes():
    """Configured staleness threshold; default 5 when unset/invalid or outside an app context."""
    if not has_app_context():
        return DEFAULT_STALE_AFTER_MINUTES
    try:
        value = int(current_app.config.get("stale_after_minutes", DEFAULT_STALE_AFTER_MINUTES))
    except (TypeError, ValueError):
        return DEFAULT_STALE_AFTER_MINUTES
    return value if value >= 0 else DEFAULT_STALE_AFTER_MINUTES


class HealthCheck(db.Model):
    """One configured health check plus its cached latest state.

    URL kinds (`internal_url` / `external_url`) follow the entry's URL, so
    `target` is NULL; `service` rows carry their own target. Exactly one of
    each URL kind per entry (see ensure_url_checks), and one `container` row
    per notifier entry (ensure_container_check; evaluated from the entry's
    docker_status, no target). NULL interval/timeout
    mean "use the global setting".
    """
    __tablename__ = 'health_check'

    id = db.Column(db.Integer, primary_key=True)
    service_entry_id = db.Column(
        db.Integer,
        db.ForeignKey('service_entry.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    kind = db.Column(db.String(16), nullable=False)
    name = db.Column(db.String(100), nullable=True)
    check_type = db.Column(db.String(8), nullable=False, default=CHECK_TYPE_HTTP, server_default=CHECK_TYPE_HTTP)
    target = db.Column(db.String(255), nullable=True)
    mode = db.Column(db.String(8), nullable=False, default=CHECK_MODE_STATUS, server_default=CHECK_MODE_STATUS)
    interval_seconds = db.Column(db.Integer, nullable=True)
    timeout_seconds = db.Column(db.Integer, nullable=True)
    verify_tls = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # Cached latest state (naive UTC timestamp).
    last_ok = db.Column(db.Boolean, nullable=True)
    last_checked_at = db.Column(db.DateTime, nullable=True)
    last_status_code = db.Column(db.Integer, nullable=True)
    last_latency_ms = db.Column(db.Integer, nullable=True)
    last_message = db.Column(db.String(255), nullable=True)
    consecutive_failures = db.Column(db.Integer, nullable=False, default=0, server_default='0')

    results = db.relationship(
        'HealthResult',
        backref='check',
        lazy=True,
        cascade='all, delete-orphan',
    )

    @property
    def is_url_kind(self):
        return self.kind in URL_CHECK_KINDS

    def to_config(self):
        """Configuration only (no cached state, no results), for backups."""
        return {
            'kind': self.kind,
            'name': self.name,
            'check_type': self.check_type,
            'target': self.target,
            'mode': self.mode,
            'interval_seconds': self.interval_seconds,
            'timeout_seconds': self.timeout_seconds,
            'verify_tls': self.verify_tls,
            'enabled': self.enabled,
        }

    def __repr__(self):
        return f'<HealthCheck {self.kind} svc={self.service_entry_id} enabled={self.enabled}>'


class HealthResult(db.Model):
    """One check sample, or (later) a compacted range of successes.

    `ts_end` is NULL for a single sample. Timestamps are naive UTC.
    """
    __tablename__ = 'health_result'

    id = db.Column(db.Integer, primary_key=True)
    check_id = db.Column(
        db.Integer,
        db.ForeignKey('health_check.id', ondelete='CASCADE'),
        nullable=False,
    )
    ts = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ts_end = db.Column(db.DateTime, nullable=True)
    samples = db.Column(db.Integer, nullable=False, default=1, server_default='1')
    ok = db.Column(db.Boolean, nullable=False)
    latency_ms = db.Column(db.Float, nullable=True)
    latency_max_ms = db.Column(db.Integer, nullable=True)
    status_code = db.Column(db.Integer, nullable=True)
    message = db.Column(db.String(255), nullable=True)

    # The composite index also serves the check_id FK.
    __table_args__ = (
        db.Index('ix_health_result_check_id_ts', 'check_id', 'ts'),
    )

    def __repr__(self):
        return f'<HealthResult check={self.check_id} ts={self.ts} ok={self.ok}>'


class Widget(db.Model):
    __tablename__ = 'widget'

    id = db.Column(db.Integer, primary_key=True)
    widget_name = db.Column(db.String(255), nullable=False)
    widget_url = db.Column(db.String(255), nullable=False)
    widget_fields = db.Column(db.JSON, nullable=False)  # Store the fields as a JSON list
    widget_api_key = db.Column(db.String(255), nullable=True)  # New column for widget API key

    @classmethod
    def detached(cls):
        """Widgets no ServiceEntry (active or soft-deleted) references."""
        return cls.query.filter(~cls.services.any())

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
        .where(ServiceEntry.deleted_at.is_(None))
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


def hard_delete_entry(entry):
    """Permanently delete a service entry.

    The single place a ServiceEntry row is really removed: used by the
    purge job and Settings -> Deleted -> Delete permanently. Caller commits.

    The entry's widget (and its widget_value history) is kept: once no entry
    references it, it is "detached" (Widget.detached()) and can be re-attached
    or deleted from Settings -> Deleted.
    """
    db.session.delete(entry)
