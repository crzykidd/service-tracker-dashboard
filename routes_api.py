"""Register API.

Owns the `api` blueprint. Today this is just the legacy
`/api/register` endpoint that notifier (and any other producer)
pushes container metadata to.

Module-level state local to this surface:
- `unauthorized_log_tracker` — rate-limits the unauthorized-access
  WARNING log line to once per IP every 2 minutes. Only this
  handler reads/writes it, so it doesn't need to live in app.py.
- `failed_icon_cache` / `RETRY_INTERVAL` — passed through to
  `image_utils.resolve_image_metadata` to throttle repeated icon
  download attempts. Same scope rationale.

Phase 5 will add `/api/v1/register` (canonical keys, pydantic-
validated) alongside this; this file is its home.
"""

import logging
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from extensions import db
from image_utils import parse_bool, resolve_image_metadata
from models import Group, ServiceEntry

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__)

unauthorized_log_tracker = {}

# Throttle for repeated icon-download failures. Used by resolve_image_metadata.
failed_icon_cache = {}  # image_icon -> last_failed_time
RETRY_INTERVAL = timedelta(minutes=60)


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
