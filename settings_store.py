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

DEFAULT_UPDATE_CHECK_ENABLED = True
DEFAULT_UPDATE_CHECK_INTERVAL_HOURS = 6


def _get_value(key: str, default):
    row = Setting.query.get(key)
    if row is None or row.value is None:
        return default
    return row.value


def _set_value(key: str, value) -> None:
    row = Setting.query.get(key)
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
