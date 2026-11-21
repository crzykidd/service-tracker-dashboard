"""DB-stored operator settings.

Distinct from `settings_loader.py` / `settings.yml`: those values are
loaded once at startup and treated as immutable for the process
lifetime. The settings here can be edited at runtime via the web UI
and are re-read on every access. Introduced in v0.6.0 to back the
per-interpreter direction mapping the exposure synthesizer needs.

Keys currently in use:

- `exposure_layers`        dict[str, str]
                           e.g. {"traefik": "internal", "dockflare": "external"}
                           Layer name → direction. Direction is one
                           of "internal", "external", "neither". A
                           layer not present here defaults to
                           "neither" (the synthesizer ignores it).

- `update_check_enabled` / `update_check_interval_hours`
                           bool (default on) / int >= 1 (default 6): the
                           GitHub "update available" check (version_check.py).

- `update_check_cache`     dict: last good result (latest_version,
                           release_url, checked_at, etag) so a restart does
                           not refetch at once.

- `instance_id`            str: a UUID generated once. Stable identity of this
                           STD install for MQTT client ids and Home Assistant
                           unique ids (PRD 17.2). Never changes after creation.

- `backup_path`, `backup_snapshot_enabled|time|keep_days`,
  `backup_export_enabled|time|keep_days|format`
                           The backup settings the operator saved in the UI (design
                           docs/design/2026-11-20-backup-export-import.md 4.1). A missing
                           row means "not set in the UI": `backups.effective_settings`
                           falls back to settings.yml / the default (env always wins).
                           Read and written through `get_backup_value` /
                           `set_backup_value` / `delete_backup_value`.

- `backup_last_runs`       dict: {"snapshot": {...}, "export": {...}}, each {at, ok, file,
                           size, error, trigger}. Observed; written by the backup runs.

- `exposure_layers_per_host`  dict[str, dict[str, str]]
                              e.g. {"docker-edge": {"traefik": "external"}}
                              Per-host override for `exposure_layers`.
                              Same layer, different deployment.
                              Per-host overrides any global setting
                              for that layer on that host.

Reads hit the DB directly. Settings are tiny (a couple of rows max),
the homelab workload is low, and a stale-cache bug here would be
silently wrong rather than silently slow.
"""

import uuid
from typing import Dict, List

from extensions import db
from models import Setting

VALID_DIRECTIONS = ("internal", "external", "neither")
DEFAULT_DIRECTION = "neither"

KEY_EXPOSURE_LAYERS = "exposure_layers"
KEY_EXPOSURE_LAYERS_PER_HOST = "exposure_layers_per_host"
KEY_UPDATE_CHECK_ENABLED = "update_check_enabled"
KEY_UPDATE_CHECK_INTERVAL = "update_check_interval_hours"
KEY_UPDATE_CHECK_CACHE = "update_check_cache"
KEY_INSTANCE_ID = "instance_id"
KEY_BACKUP_PATH = "backup_path"
KEY_BACKUP_SNAPSHOT_ENABLED = "backup_snapshot_enabled"
KEY_BACKUP_SNAPSHOT_TIME = "backup_snapshot_time"
KEY_BACKUP_SNAPSHOT_KEEP_DAYS = "backup_snapshot_keep_days"
KEY_BACKUP_EXPORT_ENABLED = "backup_export_enabled"
KEY_BACKUP_EXPORT_TIME = "backup_export_time"
KEY_BACKUP_EXPORT_KEEP_DAYS = "backup_export_keep_days"
KEY_BACKUP_EXPORT_FORMAT = "backup_export_format"
KEY_BACKUP_LAST_RUNS = "backup_last_runs"
KEY_RESTORE_LAST_SEEN = "restore_last_seen"

DEFAULT_UPDATE_CHECK_ENABLED = True
DEFAULT_UPDATE_CHECK_INTERVAL_HOURS = 6


def _get_value(key: str, default):
    row = db.session.get(Setting, key)
    if row is None or row.value is None:
        return default
    return row.value


def _set_value(key: str, value) -> None:
    row = db.session.get(Setting, key)
    if row is None:
        row = Setting(key=key, value=value)
        db.session.add(row)
    else:
        row.value = value


def get_layer_directions() -> Dict[str, str]:
    raw = _get_value(KEY_EXPOSURE_LAYERS, {}) or {}
    return {
        str(layer): direction
        for layer, direction in raw.items()
        if direction in VALID_DIRECTIONS
    }


def get_host_layer_overrides() -> Dict[str, Dict[str, str]]:
    raw = _get_value(KEY_EXPOSURE_LAYERS_PER_HOST, {}) or {}
    cleaned: Dict[str, Dict[str, str]] = {}
    for host, layer_map in raw.items():
        if not isinstance(layer_map, dict):
            continue
        cleaned[str(host)] = {
            str(layer): direction
            for layer, direction in layer_map.items()
            if direction in VALID_DIRECTIONS
        }
    return cleaned


def direction_for(layer: str, host: str) -> str:
    """Resolve direction for `(layer, host)` with per-host override
    precedence over the global setting. Unknown / unset = "neither"."""
    overrides = get_host_layer_overrides()
    host_map = overrides.get(host) if host else None
    if host_map and layer in host_map:
        return host_map[layer]
    globals_ = get_layer_directions()
    return globals_.get(layer, DEFAULT_DIRECTION)


def save_exposure_settings(
    layer_directions: Dict[str, str],
    host_overrides: Dict[str, Dict[str, str]],
) -> None:
    """Replace both settings rows atomically. Caller commits.

    Invalid direction values are silently dropped; the form UI is
    expected to constrain the dropdown to valid values, and a typo
    via curl shouldn't be allowed to render the synthesizer
    inconsistent.
    """
    cleaned_globals = {
        str(layer): direction
        for layer, direction in layer_directions.items()
        if direction in VALID_DIRECTIONS
    }
    cleaned_overrides: Dict[str, Dict[str, str]] = {}
    for host, layer_map in host_overrides.items():
        if not isinstance(layer_map, dict):
            continue
        host_cleaned = {
            str(layer): direction
            for layer, direction in layer_map.items()
            if direction in VALID_DIRECTIONS
        }
        if host_cleaned:
            cleaned_overrides[str(host)] = host_cleaned

    _set_value(KEY_EXPOSURE_LAYERS, cleaned_globals)
    _set_value(KEY_EXPOSURE_LAYERS_PER_HOST, cleaned_overrides)


def discovered_layers() -> List[str]:
    """Layers that have ever been seen in service_exposure. Sorted.

    Used by the settings page to populate the layer table — operators
    only get to configure layers that have actually been observed,
    avoiding empty config screens before any interpreter has run.
    """
    from models import ServiceExposure
    rows = (
        db.session.query(ServiceExposure.layer)
        .distinct()
        .order_by(ServiceExposure.layer.asc())
        .all()
    )
    return [r[0] for r in rows]


def discovered_hosts() -> List[str]:
    """Hosts that have any exposure rows attached. Sorted.

    Used by the settings page's per-host overrides section. A host
    with no exposure observations doesn't need an override because
    the synthesizer has no candidates to direct.
    """
    from models import ServiceEntry, ServiceExposure
    rows = (
        db.session.query(ServiceEntry.host)
        .join(ServiceExposure, ServiceExposure.service_entry_id == ServiceEntry.id)
        .filter(ServiceEntry.deleted_at.is_(None))
        .distinct()
        .order_by(ServiceEntry.host.asc())
        .all()
    )
    return [r[0] for r in rows]


def get_update_check_settings():
    """(enabled, interval_hours) with defaults; a bad stored value falls back."""
    enabled = _get_value(KEY_UPDATE_CHECK_ENABLED, DEFAULT_UPDATE_CHECK_ENABLED)
    hours = _get_value(KEY_UPDATE_CHECK_INTERVAL, DEFAULT_UPDATE_CHECK_INTERVAL_HOURS)
    if not isinstance(enabled, bool):
        enabled = DEFAULT_UPDATE_CHECK_ENABLED
    if isinstance(hours, bool) or not isinstance(hours, int) or hours < 1:
        hours = DEFAULT_UPDATE_CHECK_INTERVAL_HOURS
    return enabled, hours


def save_update_check_settings(enabled=None, interval_hours=None) -> None:
    """Set either value (None = leave alone). Caller validates and commits."""
    if enabled is not None:
        _set_value(KEY_UPDATE_CHECK_ENABLED, bool(enabled))
    if interval_hours is not None:
        _set_value(KEY_UPDATE_CHECK_INTERVAL, int(interval_hours))


def get_update_check_cache() -> dict:
    raw = _get_value(KEY_UPDATE_CHECK_CACHE, {})
    return raw if isinstance(raw, dict) else {}


def save_update_check_cache(cache: dict) -> None:
    """Persist the last good update-check result and commit (called from the
    background thread, which owns its own app context)."""
    _set_value(KEY_UPDATE_CHECK_CACHE, cache)
    db.session.commit()


def get_instance_id() -> str:
    """The install's stable UUID, created and committed on first use."""
    value = _get_value(KEY_INSTANCE_ID, None)
    if isinstance(value, str) and value:
        return value
    value = str(uuid.uuid4())
    _set_value(KEY_INSTANCE_ID, value)
    db.session.commit()
    return value


def peek_instance_id():
    """The install's UUID if it has been created, else None. Never writes (the export
    header is informational and a read must not create a row)."""
    value = _get_value(KEY_INSTANCE_ID, None)
    return value if isinstance(value, str) and value else None


def short_instance_id(instance_id: str) -> str:
    """The first 8 hex digits, for client ids (`std-1a2b3c4d`)."""
    return instance_id.replace("-", "")[:8]


def get_backup_value(key: str):
    """A backup setting saved in the UI, or None when there is no row."""
    return _get_value(key, None)


def set_backup_value(key: str, value) -> None:
    """Store one backup setting. Caller validates and commits."""
    _set_value(key, value)


def delete_backup_value(key: str) -> None:
    """Remove a backup setting row (Reset). Caller commits."""
    row = db.session.get(Setting, key)
    if row is not None:
        db.session.delete(row)


def get_backup_last_runs() -> dict:
    raw = _get_value(KEY_BACKUP_LAST_RUNS, {})
    return raw if isinstance(raw, dict) else {}


def set_backup_last_runs(runs: dict) -> None:
    """Store the whole last-runs dict. Caller commits."""
    _set_value(KEY_BACKUP_LAST_RUNS, runs)


def get_restore_last_seen():
    """The `at` of the last restore result the operator dismissed (restore/last.json), or None."""
    value = _get_value(KEY_RESTORE_LAST_SEEN, None)
    return value if isinstance(value, str) else None


def set_restore_last_seen(at) -> None:
    """Mark a restore result seen. Caller commits."""
    _set_value(KEY_RESTORE_LAST_SEEN, at)
