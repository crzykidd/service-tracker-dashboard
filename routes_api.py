"""Register API.

Owns the `api` blueprint. Surfaces:
- `/api/v1/register` (v0.5.0+) — canonical-keys-only, pydantic-
  validated. The contract notifier v0.3.0 targets.
- `/api/register` (legacy) — compat shim that remaps legacy keys
  and calls the same shared upsert. Emits `Deprecation: true`.
  Will be removed in v0.6.0.

Both routes call into `upsert_service(canonical, app)` — there is
exactly one place where the upsert logic lives.

Module-level state local to this surface:
- `unauthorized_log_tracker` — rate-limits the unauthorized-access
  WARNING log line to once per IP every 2 minutes.
- `failed_icon_cache` / `RETRY_INTERVAL` — passed through to
  `image_utils.resolve_image_metadata` to throttle repeated icon
  download attempts.
- `_UPSERT_LOCK` — single `threading.Lock` serializing the
  find-or-create + merge + commit critical section in
  `upsert_service`. Coarse (one lock for all keys) and that's
  intentional — see the function docstring.
"""

import logging
import threading
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from pydantic import ValidationError

from extensions import db
from image_utils import parse_bool, resolve_image_metadata
from models import Group, ServiceEntry
from schemas import RegisterPayload

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

unauthorized_log_tracker = {}

# Throttle for repeated icon-download failures. Used by resolve_image_metadata.
failed_icon_cache = {}  # image_icon -> last_failed_time
RETRY_INTERVAL = timedelta(minutes=60)

# Serializes the upsert critical section across all register calls.
# See upsert_service docstring for the rationale.
_UPSERT_LOCK = threading.Lock()


def _check_bearer_auth(endpoint_label):
    """Validate the Authorization header against `api_token`.

    Returns None on success, or a 401 Flask Response on failure.
    Shared between /api/v1/register and /api/register so the auth
    contract stays in one place. The compat shim wraps the failure
    response with the deprecation headers; the v1 endpoint returns
    it as-is.
    """
    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {current_app.config['api_token']}"
    if auth_header == expected:
        return None

    client_ip = request.remote_addr
    now = datetime.utcnow()
    logger.info(f"401 - Unauthorized API access from {client_ip} to {endpoint_label}")

    last_log_time = unauthorized_log_tracker.get(client_ip)
    if not last_log_time or (now - last_log_time) > timedelta(minutes=2):
        logger.warning(f"⚠️ Repeated unauthorized access from {client_ip}")
        unauthorized_log_tracker[client_ip] = now

    response = jsonify({"error": "Unauthorized"})
    response.status_code = 401
    return response


# Legacy → canonical key remap. The compat shim is the ONLY place
# this happens. /api/v1/register does not look at these names — a
# producer that sends a legacy key against v1 gets a 400.
_LEGACY_KEY_MAP = {
    "group": "group_name",
    "internal_health": "internal_health_check_enabled",
    "internal.health": "internal_health_check_enabled",
    "external_health": "external_health_check_enabled",
    "external.health": "external_health_check_enabled",
    "docker_host": "host",
    "icon": "image_icon",
    "sort.priority": "sort_priority",
}


def _remap_legacy_to_canonical(data):
    """Translate a legacy /api/register payload to a canonical dict.

    - Canonical keys present in `data` are passed through.
    - Legacy keys are remapped to their canonical name, but only
      when the canonical key is not already explicitly set (so a
      producer that sends both `group_name` and `group` gets the
      `group_name` value).
    - Keys not in the canonical schema and not in the legacy map
      are silently dropped — matches v0.4.x behavior (the existing
      handler ignored them; in debug it logged a warning).

    Bool coercion is NOT done here — upsert_service runs values
    through `parse_bool` itself, which handles both real bools and
    the "true"/"false" string variants that legacy producers send.
    """
    canonical = {}
    schema_fields = RegisterPayload.model_fields
    for key, value in data.items():
        if key in schema_fields:
            canonical[key] = value
    for legacy_key, canonical_key in _LEGACY_KEY_MAP.items():
        if legacy_key in data and canonical_key not in canonical:
            canonical[canonical_key] = data[legacy_key]
    return canonical


# Per-IP rate limit on the deprecation warning log. Logging every
# /api/register call would drown out everything else; once per
# producer per hour is enough to drive the migration conversation.
_DEPRECATION_LOG_TRACKER = {}


def _maybe_log_deprecation(client_ip):
    now = datetime.utcnow()
    last_log = _DEPRECATION_LOG_TRACKER.get(client_ip)
    if not last_log or (now - last_log) > timedelta(hours=1):
        logger.warning(
            f"⚠️ Deprecated /api/register called by {client_ip}; "
            f"migrate this producer to /api/v1/register before v0.6.0."
        )
        _DEPRECATION_LOG_TRACKER[client_ip] = now


def _add_deprecation_headers(response):
    """Attach Deprecation + successor-version Link to a Response.

    No Sunset header in v0.5.0 — a wrong Sunset date is worse than
    none. v0.6.0 with a firm cutover timeline can add it.
    """
    response.headers['Deprecation'] = 'true'
    response.headers['Link'] = '</api/v1/register>; rel="successor-version"'
    return response


def upsert_service(canonical, app):
    """Apply a canonical register payload to the service_entry row
    for `(host, container_name)`. Returns `(body_dict, http_status)`.

    Caller is responsible for auth and for translating wire-format
    keys to canonical (the pydantic schema does this for
    /api/v1/register; the legacy-key remap function does it for
    /api/register).

    Concurrency
    -----------
    Holds `_UPSERT_LOCK` across the find-or-create + merge + commit.
    Two concurrent register calls — same or different services —
    serialize. Coarse: one lock for all keys, not per-key. Chosen
    because:

    - The homelab-scale workload is one Flask process with a low
      write rate (~50 services, register calls measured in dozens
      per minute peak). Contention on a single lock is negligible.
    - Per-key locking adds a dict-of-locks plus its own outer mutex
      for safe insertion, and the bookkeeping isn't free.

    Image-metadata resolution may issue an HTTP icon download, so
    it runs BEFORE the lock — holding the lock across HTTP would
    serialize every register behind one slow CDN response.

    Caveat: under Gunicorn with multiple workers, this in-process
    lock does not serialize across workers. SQLite's WAL single-
    writer behavior is the actual cross-process safety net. The
    deployment documented in docker-compose.yml is a single-process
    Flask server, so the in-process lock is sufficient there.

    Field ownership
    ---------------
    Notifier-owned fields (container_id, URLs, stack_name,
    docker_status, started_at, health-check toggles, image_*) are
    overwritten on update whenever the payload carries them.

    User-overridable fields (group_name -> group_id, sort_priority)
    are governed by a per-deployment mode. v0.5.0 hard-codes
    "user_wins" here; commit 6 wires it to the
    `register_field_ownership` setting:
    - "user_wins" — existing non-NULL values are preserved on
      update. New rows are written with whatever the payload says.
    - "notifier_wins" — payload always wins.

    Regardless of mode, the `notifier_reported_*` capture columns
    record what the notifier actually sent, so a future
    overridden-labels export can compare against the user's value.

    is_static rows short-circuit with a 200 + skipped body — that
    behavior is unchanged from v0.4.x.
    """
    image_meta = resolve_image_metadata(
        image_raw=canonical.get("image_name"),
        image_icon_override=canonical.get("image_icon"),
        fallback_name=canonical.get("container_name"),
        image_dir=app.config['IMAGE_DIR'],
        failed_icon_cache=failed_icon_cache,
        retry_interval=RETRY_INTERVAL,
        logger=logger,
        debug=app.debug,
    )

    # Commit 6 replaces this hard-coded mode with a read from
    # app.config.get("register_field_ownership", "user_wins").
    mode = "user_wins"

    with _UPSERT_LOCK:
        group_obj = None
        group_name = canonical.get("group_name")
        if group_name:
            group_obj = Group.query.filter_by(group_name=group_name).first()
            if not group_obj:
                group_obj = Group(group_name=group_name)
                db.session.add(group_obj)
                db.session.flush()

        entry = ServiceEntry.query.filter_by(
            host=canonical['host'],
            container_name=canonical['container_name'],
        ).first()

        if entry is not None:
            if entry.is_static:
                logger.info(
                    f"Skipping update for '{entry.container_name}' on "
                    f"'{entry.host}' — static lock enabled."
                )
                return {"status": "skipped", "reason": "static lock"}, 200

            now = datetime.now()
            entry.last_updated = now
            entry.last_api_update = now

            # Notifier-owned fields — always overwrite when payload carries them.
            if canonical.get("container_id"):
                entry.container_id = canonical["container_id"]
            if canonical.get("internalurl"):
                entry.internalurl = canonical["internalurl"]
            if canonical.get("externalurl"):
                entry.externalurl = canonical["externalurl"]
            if canonical.get("stack_name"):
                entry.stack_name = canonical["stack_name"]
            if canonical.get("docker_status"):
                entry.docker_status = canonical["docker_status"]
            if canonical.get("started_at"):
                entry.started_at = canonical["started_at"]

            if "internal_health_check_enabled" in canonical:
                parsed = parse_bool(canonical["internal_health_check_enabled"])
                if parsed is not None:
                    entry.internal_health_check_enabled = parsed
            if "external_health_check_enabled" in canonical:
                parsed = parse_bool(canonical["external_health_check_enabled"])
                if parsed is not None:
                    entry.external_health_check_enabled = parsed

            if image_meta["registry"]:
                entry.image_registry = image_meta["registry"]
            if image_meta["owner"]:
                entry.image_owner = image_meta["owner"]
            if image_meta["image_name"]:
                entry.image_name = image_meta["image_name"]
            if image_meta["image_icon"]:
                entry.image_icon = image_meta["image_icon"]
            if image_meta["image_tag"]:
                entry.image_tag = image_meta["image_tag"]

            # User-overridable fields. Always record what the notifier
            # reported into the capture columns; whether the live
            # column gets the new value depends on `mode`.
            if "group_name" in canonical and canonical["group_name"] is not None:
                entry.notifier_reported_group_name = canonical["group_name"]
                if mode == "notifier_wins" or entry.group_id is None:
                    entry.group_id = group_obj.id if group_obj else None

            if "sort_priority" in canonical and canonical["sort_priority"] is not None:
                entry.notifier_reported_sort_priority = canonical["sort_priority"]
                if mode == "notifier_wins" or entry.sort_priority is None:
                    entry.sort_priority = canonical["sort_priority"]
        else:
            # New row — every field from the payload, plus the capture columns.
            now = datetime.now()
            entry = ServiceEntry(
                host=canonical['host'],
                container_name=canonical['container_name'],
                container_id=canonical.get('container_id'),
                internalurl=canonical.get('internalurl'),
                externalurl=canonical.get('externalurl'),
                stack_name=canonical.get('stack_name'),
                docker_status=canonical.get('docker_status'),
                internal_health_check_enabled=parse_bool(canonical.get('internal_health_check_enabled')),
                external_health_check_enabled=parse_bool(canonical.get('external_health_check_enabled')),
                group_id=group_obj.id if group_obj else None,
                started_at=canonical.get('started_at'),
                last_updated=now,
                last_api_update=now,
                image_registry=image_meta["registry"],
                image_owner=image_meta["owner"],
                image_name=image_meta["image_name"],
                image_icon=image_meta["image_icon"],
                image_tag=image_meta["image_tag"],
                sort_priority=canonical.get('sort_priority'),
                notifier_reported_group_name=canonical.get('group_name'),
                notifier_reported_sort_priority=canonical.get('sort_priority'),
            )
            db.session.add(entry)

        db.session.commit()
        return entry.to_dict(), 200


@api_bp.route('/api/v1/register', methods=['POST'])
def api_v1_register():
    """Canonical register endpoint (v0.5.0+).

    Strict: pydantic validates with `extra="forbid"`, so any key not
    in `RegisterPayload` triggers a 400 with the list of offending
    keys. `host` and `container_name` are required; everything else
    is optional.

    Notifier v0.3.0 targets this endpoint. The legacy /api/register
    compat shim remains available through v0.6.0.
    """
    auth_failure = _check_bearer_auth("/api/v1/register")
    if auth_failure is not None:
        return auth_failure

    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return jsonify({"error": "Request body must be a JSON object"}), 400

    try:
        payload = RegisterPayload.model_validate(raw)
    except ValidationError as e:
        errors = e.errors()
        unknown_keys = [
            err["loc"][0] for err in errors
            if err.get("type") == "extra_forbidden" and err.get("loc")
        ]
        body = {"error": "Invalid register payload", "details": errors}
        if unknown_keys:
            body["unknown_keys"] = unknown_keys
        return jsonify(body), 400

    if current_app.debug:
        logger.info("🔍 Received /api/v1/register payload:")
        for k, v in payload.model_dump(exclude_none=True).items():
            logger.info(f"    {k}: {v}")

    canonical = payload.model_dump()
    body, status = upsert_service(canonical, current_app._get_current_object())
    return jsonify(body), status


@api_bp.route('/api/register', methods=['POST'])
def api_register():
    """Legacy compat shim. Deprecated; will be removed in v0.6.0.

    Remaps the historical key spellings to canonical and calls the
    same shared upsert as /api/v1/register. The remap is the ONE
    place legacy keys are interpreted; no other code in this file
    looks at `group`, `docker_host`, `internal.health`, etc.

    Unlike the v1 endpoint, this shim does NOT route through the
    pydantic schema: real-world v0.4.x payloads may carry keys
    pydantic-strict would reject (e.g., experimental `timestamp`
    variants), and the goal of the shim is translation, not
    enforcement. Unknown keys are silently dropped by the remap.

    Every response includes `Deprecation: true` and a Link header
    pointing to /api/v1/register. A per-IP rate-limited warning is
    logged once per hour to drive producer migration without
    flooding the log.
    """
    auth_failure = _check_bearer_auth("/api/register")
    if auth_failure is not None:
        return _add_deprecation_headers(auth_failure)

    _maybe_log_deprecation(request.remote_addr)

    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        response = jsonify({"error": "Request body must be a JSON object"})
        response.status_code = 400
        return _add_deprecation_headers(response)

    if current_app.debug:
        logger.info("🔍 Received /api/register payload:")
        for k, v in raw.items():
            logger.info(f"    {k}: {v}")
        unknown = [
            k for k in raw
            if k not in RegisterPayload.model_fields and k not in _LEGACY_KEY_MAP
        ]
        if unknown:
            logger.warning(f"⚠️ Unknown keys in legacy payload (dropped): {unknown}")

    canonical = _remap_legacy_to_canonical(raw)

    if not canonical.get('host') or not canonical.get('container_name'):
        response = jsonify({"error": "Missing host or container_name"})
        response.status_code = 400
        return _add_deprecation_headers(response)

    body, status = upsert_service(canonical, current_app._get_current_object())
    response = jsonify(body)
    response.status_code = status
    return _add_deprecation_headers(response)
