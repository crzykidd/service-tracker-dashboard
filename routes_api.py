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

    Returns None on success, or a Flask (response, status) tuple on
    failure. Shared between /api/v1/register and /api/register so
    the auth contract stays in one place.
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

    return jsonify({"error": "Unauthorized"}), 401


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

    auth_header = request.headers.get("Authorization", "")
    expected = f"Bearer {current_app.config['api_token']}"
    client_ip = request.remote_addr
    now = datetime.utcnow()

    # Rate-limit unauthorized logs to once every 2 minutes per IP
    if auth_header != expected:
        logger.info(f"401 - Unauthorized API access from {client_ip} to /api/register")

        # Rate-limited WARNING (optional)
        last_log_time = unauthorized_log_tracker.get(client_ip)
        if not last_log_time or (now - last_log_time) > timedelta(minutes=2):
            logger.warning(f"⚠️ Repeated unauthorized access from {client_ip}")
            unauthorized_log_tracker[client_ip] = now

        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    # 🔁 Remap STD-style keys to internal DB fields
    label_key_map = {
        "group": "group_name",
        "internal_health": "internal_health_check_enabled",
        "internal.health": "internal_health_check_enabled",  # Add this
        "external_health": "external_health_check_enabled",
        "external.health": "external_health_check_enabled",  # Add this
        "docker_host": "host",
        "icon": "image_icon",
    }
    for src_key, target_key in label_key_map.items():
        if src_key in data and target_key not in data:
            data[target_key] = data[src_key]
    # For debug: log any unexpected fields (not known or remapped)
    if current_app.debug:
        known_fields = {
            "host", "docker_host", "container_name", "container_id", "internalurl", "externalurl",
            "stack_name", "docker_status", "group_name", "group", "started_at",
            "internal_health_check_enabled", "external_health_check_enabled",
            "internal.health", "external.health",
            "image_name", "image_icon", "timestamp", "sort.priority"
        }
        # Include remapped fields (e.g., group → group_name)
        known_fields.update(label_key_map.values())

        for key in data:
            if key not in known_fields:
                logger.warning(f"⚠️ Unexpected STD label received (ignored): {key} = {data[key]}")


    if current_app.debug:
        logger.info("🔍 Received API payload:")
        for k, v in data.items():
            logger.info(f"    {k}: {v}")

    if not data.get('host') or not data.get('container_name'):
        return jsonify({"error": "Missing host or container_name"}), 400

    # ✅ Use shared metadata resolver
    image_meta = resolve_image_metadata(
        image_raw=data.get("image_name"),
        image_icon_override=data.get("image_icon"),
        fallback_name=data.get("container_name"),
        image_dir=current_app.config['IMAGE_DIR'],
        failed_icon_cache=failed_icon_cache,
        retry_interval=RETRY_INTERVAL,
        logger=logger,
        debug=current_app.debug
    )

    registry = image_meta["registry"]
    owner = image_meta["owner"]
    img_name = image_meta["image_name"]
    tag = image_meta["image_tag"]
    image_icon = image_meta["image_icon"]

    # Update or create entry
    # Handle group assignment
    group_name = data.get("group_name")
    group_obj = None

    if group_name:
        group_obj = Group.query.filter_by(group_name=group_name).first()
        if not group_obj:
            group_obj = Group(group_name=group_name)
            db.session.add(group_obj)
            db.session.flush()  # ensure group_obj.id is available
    entry = ServiceEntry.query.filter_by(container_name=data['container_name'], host=data['host']).first()

    if entry:
        if entry.is_static:
            logger.info(f"Skipping update for '{entry.container_name}' on '{entry.host}' — static lock enabled.")
            return jsonify({"status": "skipped", "reason": "static lock"}), 200
        entry.last_updated = datetime.now()
        entry.last_api_update = datetime.now()
        if "sort.priority" in data:
            try:
                entry.sort_priority = int(data["sort.priority"])
            except (TypeError, ValueError):
                logger.warning(f"⚠️ Invalid sort priority: {data['sort.priority']}")


        if data.get("container_id"):
            entry.container_id = data["container_id"]
        if data.get("internalurl"):
            entry.internalurl = data["internalurl"]
        if data.get("externalurl"):
            entry.externalurl = data["externalurl"]
        if data.get("stack_name"):
            entry.stack_name = data["stack_name"]
        if data.get("docker_status"):
            entry.docker_status = data["docker_status"]

        if "group_name" in data:
            entry.group_id = group_obj.id if group_obj else None

        if data.get("started_at"):
            entry.started_at = data["started_at"]

        if "internal_health_check_enabled" in data:
            parsed = parse_bool(data["internal_health_check_enabled"])
            if parsed is not None:
                entry.internal_health_check_enabled = parsed

        if "external_health_check_enabled" in data:
            parsed = parse_bool(data["external_health_check_enabled"])
            if parsed is not None:
                entry.external_health_check_enabled = parsed

        if registry:
            entry.image_registry = registry
        if owner:
            entry.image_owner = owner
        if img_name:
            entry.image_name = img_name
        if image_icon:
            entry.image_icon = image_icon
        if tag:
            entry.image_tag = tag



    else:
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
            group_id=group_obj.id if group_obj else None,
            started_at=data.get('started_at'),
            last_updated=datetime.now(),
            last_api_update=datetime.now(),
            image_registry=registry,
            image_owner=owner,
            image_name=img_name,
            image_icon=image_icon,
            image_tag=tag
        )
        db.session.add(entry)


    db.session.commit()
    return jsonify(entry.to_dict()), 200 if entry else 201
