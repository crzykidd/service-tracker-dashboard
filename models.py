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
# Entries pushed by an inventory stream sidecar (v0.10.0, PRD 18).
SOURCE_STREAM = 'stream'
VALID_SOURCES = (SOURCE_NOTIFIER, SOURCE_MANUAL, SOURCE_STREAM)

# Inventory streams (PRD 18.4).
STREAM_PENDING = 'pending'
STREAM_ENABLED = 'enabled'
STREAM_DISABLED = 'disabled'
STREAM_IGNORED = 'ignored'
STREAM_STATUSES = (STREAM_PENDING, STREAM_ENABLED, STREAM_DISABLED, STREAM_IGNORED)
# Who owns a stream entry's name: the producer ('stream') or the operator ('ui_edit').
NAME_SOURCE_STREAM = 'stream'
NAME_SOURCE_UI_EDIT = 'ui_edit'

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
CHECK_TYPE_DNS = 'dns'
CHECK_TYPES = (CHECK_TYPE_HTTP, CHECK_TYPE_TCP, CHECK_TYPE_PING, CHECK_TYPE_DNS)
# DNS check (v0.9.0): record types a query can ask for, and the default rcode.
DNS_RECORD_TYPES = ('A', 'AAAA', 'CNAME', 'TXT', 'PTR', 'MX', 'NS', 'SRV')
DNS_DEFAULT_RECORD_TYPE = 'A'
DNS_DEFAULT_RCODE = 'NOERROR'
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
    container_name = db.Column(db.String(128), nullable=False)
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
    # Canonical image reference (registry/repository:tag or @digest), parsed by image_ref.py
    # from the raw image the notifier sends. Observed by register only: not editable, not exported.
    image_ref = db.Column(db.String(512), nullable=True, index=True)
    # Operator-owned override for the image repository link (v0.11.1); never written by register.
    image_repo_url = db.Column(db.String(512), nullable=True)
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
    # Home Assistant opt-in (PRD 17.4). Operator-owned: register never writes
    # it. True publishes this entry's device to Home Assistant discovery.
    ha_publish = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # Inventory streams (v0.10.0, PRD 18.4). NULL for notifier and manual entries.
    # `stream_id` + `stream_key` identify the item in its stream (unique, soft-deleted
    # rows included); mac/ip/network/attributes are pure observation overwritten by
    # every snapshot; `inventory_missing` means the key was absent from the latest
    # snapshot; `name_source` is 'stream' until the operator renames the entry
    # ('ui_edit'), after which snapshots no longer write the name.
    stream_id = db.Column(db.Integer, db.ForeignKey('inventory_stream.id'), nullable=True, index=True)
    stream_key = db.Column(db.String(128), nullable=True)
    mac = db.Column(db.String(17), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    network = db.Column(db.String(64), nullable=True)
    attributes = db.Column(db.JSON, nullable=True)
    inventory_missing = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # When the entry was flagged missing (naive UTC; NULL while present). PRD 18.9.
    inventory_missing_since = db.Column(db.DateTime, nullable=True)
    name_source = db.Column(db.String(16), nullable=True)
    # A manual entry that joined a stream (Convert / accept / Link) belongs to the
    # operator: stream cleanup unlinks it instead of deleting it, and `pre_link_host`
    # is the host it had before the join (restored on unlink; NULL when unknown).
    stream_linked = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    pre_link_host = db.Column(db.String(100), nullable=True)
    stream = db.relationship('InventoryStream', backref=db.backref('entries', lazy=True))
    link_offers = db.relationship(
        'StreamLinkOffer',
        backref='entry',
        lazy=True,
        cascade='all, delete-orphan',
    )

    __table_args__ = (
        db.Index('ix_service_entry_host_container_name', 'host', 'container_name'),
        db.Index('ux_service_entry_stream_key', 'stream_id', 'stream_key', unique=True,
                 sqlite_where=db.text('stream_id IS NOT NULL')),
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
            'ha_publish': bool(self.ha_publish),
            'networks': self.networks,
            'exposed_ports': self.exposed_ports,
            'published_ports': self.published_ports,
            'mac': self.mac,
            'ip': self.ip,
            'network': self.network,
            'attributes': self.attributes,
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
    def is_stream(self):
        """True for entries kept current by an inventory stream."""
        return self.source == SOURCE_STREAM

    @property
    def is_docker(self):
        """True for entries owned by the Docker notifier (`source == notifier`)."""
        # A not-yet-flushed instance has source None; the column default is notifier.
        return (self.source or SOURCE_NOTIFIER) == SOURCE_NOTIFIER

    @property
    def image_repo_link(self):
        """The image's repository page: the operator override, else derived from
        the image fields, else None (see image_repo.py)."""
        from image_repo import effective_repo_url

        return effective_repo_url(self)

    @property
    def is_docker_status_stale(self):
        """True when the notifier hasn't reported in within `stale_after_minutes`.

        Manual and locked entries are never stale. A dynamic entry with no
        `last_api_update` (never registered) counts as stale; the Tiled view
        shows that case separately as "no update received".
        """
        if not self.is_docker or self.is_static:
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
    if entry.is_docker and entry.container_check is None:
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
        return entry.is_docker and not entry.is_static
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
    # DNS checks only (v0.9.0; NULL on every other type). `target` is the DNS
    # server (an IP literal, optional port); these describe the query and the
    # expected reply. A blank expected_rcode means NOERROR, a blank
    # expected_answer means "judge by rcode only".
    dns_name = db.Column(db.String(255), nullable=True)
    dns_record_type = db.Column(db.String(8), nullable=True)
    dns_expected_rcode = db.Column(db.String(16), nullable=True)
    dns_expected_answer = db.Column(db.String(255), nullable=True)
    # Certificate-expiry condition (v0.9.0; HTTPS checks only). `cert_min_days`
    # is the operator's minimum days left (NULL = off); `last_cert_expires_at`
    # is the leaf certificate's notAfter as the checker last saw it (naive UTC),
    # cleared when the check has no condition or the target is plain http.
    cert_min_days = db.Column(db.Integer, nullable=True)
    last_cert_expires_at = db.Column(db.DateTime, nullable=True)
    # Home Assistant opt-out (PRD 17.4): True removes this check's entity from
    # discovery. Operator-owned; not part of the check's probe configuration.
    ha_exclude = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
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
            'dns_name': self.dns_name,
            'dns_record_type': self.dns_record_type,
            'dns_expected_rcode': self.dns_expected_rcode,
            'dns_expected_answer': self.dns_expected_answer,
            'cert_min_days': self.cert_min_days,
            'ha_exclude': bool(self.ha_exclude),
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


class ApiKey(db.Model):
    """Admin API key for the management API (v0.8.0, PRD 14.2).

    Only the SHA-256 of the full key is stored; the secret is shown once at
    creation. `scope` is `read` or `write` (write includes read).
    """
    __tablename__ = 'api_key'
    # Names are unique among active keys only, so a revoked key's name can be
    # reused (v0.9.0). Mirrors the partial index in the v090-03 migration.
    __table_args__ = (
        db.Index('ux_api_key_name_active', 'name', unique=True,
                 sqlite_where=db.text('revoked_at IS NULL')),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(64), nullable=False)
    prefix = db.Column(db.String(8), nullable=False, index=True)
    key_hash = db.Column(db.String(64), nullable=False)
    scope = db.Column(db.String(8), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True, index=True)
    last_used_at = db.Column(db.DateTime, nullable=True)
    last_used_ip = db.Column(db.String(64), nullable=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    rotated_at = db.Column(db.DateTime, nullable=True)  # v0.9.0: last secret rotation

    @property
    def is_revoked(self):
        return self.revoked_at is not None


class ApiAudit(db.Model):
    """One row per management-API write request (v0.8.0, PRD 14.6).

    `key_name` is a snapshot so the row survives key deletion; `changes` is
    `{field: [old, new]}` with secrets already masked.
    """
    __tablename__ = 'api_audit'

    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_key.id', ondelete='SET NULL'),
                           nullable=True, index=True)
    key_name = db.Column(db.String(64), nullable=True)
    method = db.Column(db.String(8), nullable=False)
    path = db.Column(db.String(255), nullable=False)
    object_type = db.Column(db.String(32), nullable=True)
    object_id = db.Column(db.String(64), nullable=True)
    status_code = db.Column(db.Integer, nullable=False)
    changes = db.Column(db.JSON, nullable=True)


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

# The `password_hash` of a user the import created without a password (design 7.6). It has
# no `$` separators, so werkzeug's `check_password_hash` is always False for it.
UNSET_PASSWORD_HASH = '!unset'


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

    @property
    def has_password(self):
        """False for a user an import created without a password (the sentinel hash is
        not a werkzeug hash, so no password ever matches it)."""
        return self.password_hash != UNSET_PASSWORD_HASH


def hard_delete_entry(entry):
    """Permanently delete a service entry.

    The single place a ServiceEntry row is really removed: used by the
    purge job and Settings -> Deleted -> Delete permanently. Caller commits.

    The entry's widget (and its widget_value history) is kept: once no entry
    references it, it is "detached" (Widget.detached()) and can be re-attached
    or deleted from Settings -> Deleted.
    """
    db.session.delete(entry)


class NotificationChannel(db.Model):
    """A place STD publishes state to (v0.10.0, PRD 17.2). `type` selects the
    channel implementation in `notify.py` (`mqtt` first); `config` holds its
    non-secret settings as JSON; `secret` (an MQTT password) is write-only:
    never returned by the UI or API, never logged."""
    __tablename__ = 'notification_channel'
    __table_args__ = (
        db.Index('ux_notification_channel_name', 'name', unique=True),
        db.Index('ix_notification_channel_type', 'type'),
    )

    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(32), nullable=False)
    name = db.Column(db.String(64), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    config = db.Column(db.JSON, nullable=False, default=dict)
    secret = db.Column(db.String(512), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<NotificationChannel {self.id} {self.type} {self.name!r}>'


class InventoryStream(db.Model):
    """One producer stream of inventory items (v0.10.0, PRD 18.4).

    Created `pending` by the first snapshot PUT. `snapshot` holds the latest
    accepted items (normalised) so Enable and Preview work without the sidecar.
    `api_key_id` is the key that created the stream: an `ingest` key may only
    post to its own streams. Counts and times are bookkeeping for the UI/API.
    """
    __tablename__ = 'inventory_stream'

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.String(63), nullable=False, unique=True)
    display_name = db.Column(db.String(32), nullable=False)
    producer = db.Column(db.String(64), nullable=False)
    producer_version = db.Column(db.String(32), nullable=False)
    key_type = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False, default=STREAM_PENDING,
                       server_default=STREAM_PENDING)
    api_key_id = db.Column(db.Integer, db.ForeignKey('api_key.id', ondelete='SET NULL'),
                           nullable=True, index=True)
    network_include = db.Column(db.JSON, nullable=True)
    network_exclude = db.Column(db.JSON, nullable=True)
    # {"ping": bool, "tcp_port": int | None}: checks a new stream entry starts with.
    default_checks = db.Column(db.JSON, nullable=True)
    snapshot = db.Column(db.JSON, nullable=True)
    first_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_snapshot_at = db.Column(db.DateTime, nullable=True)
    last_applied_at = db.Column(db.DateTime, nullable=True)
    last_item_count = db.Column(db.Integer, nullable=True)
    last_counts = db.Column(db.JSON, nullable=True)
    last_error = db.Column(db.String(255), nullable=True)
    # Observability (PRD 18.9). The operator's expected snapshot interval wins over the
    # one the producer advertises (`snapshot_interval_seconds`); both NULL = 15 min.
    expected_interval_seconds = db.Column(db.Integer, nullable=True)
    producer_interval_seconds = db.Column(db.Integer, nullable=True)
    # Soft-delete entries missing for this many days (NULL = off, the default).
    missing_expiry_days = db.Column(db.Integer, nullable=True)
    # The last snapshot PUT refused with 400/409/413 ("<status>: <first error>").
    # Separate from `last_error`, which is an STD-side apply failure.
    last_rejected_at = db.Column(db.DateTime, nullable=True)
    last_rejection = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<InventoryStream {self.stream_id} {self.status}>'


class InventoryBlock(db.Model):
    """A stream key the operator chose not to re-add (PRD 18.7). Kept when the
    entry is hard-deleted; removed with its stream."""
    __tablename__ = 'inventory_block'
    __table_args__ = (
        db.Index('ux_inventory_block_stream_key', 'stream_id', 'key', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('inventory_stream.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    key = db.Column(db.String(128), nullable=False)
    name = db.Column(db.String(128), nullable=True)
    ip = db.Column(db.String(64), nullable=True)
    blocked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    blocked_by = db.Column(db.String(80), nullable=True)

    stream = db.relationship(
        'InventoryStream', backref=db.backref('blocks', lazy=True, cascade='all, delete-orphan'))


class StreamLinkOffer(db.Model):
    """A new stream item whose name matches one manual entry (PRD 18.6): nothing
    is created until the operator accepts (the manual entry joins the stream) or
    declines (a new stream entry is created). `item` is the stored snapshot item."""
    __tablename__ = 'stream_link_offer'
    __table_args__ = (
        db.Index('ux_stream_link_offer_stream_key', 'stream_id', 'key', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey('inventory_stream.id', ondelete='CASCADE'),
                          nullable=False, index=True)
    key = db.Column(db.String(128), nullable=False)
    entry_id = db.Column(db.Integer, db.ForeignKey('service_entry.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    item = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    stream = db.relationship(
        'InventoryStream', backref=db.backref('offers', lazy=True, cascade='all, delete-orphan'))
