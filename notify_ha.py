"""Home Assistant MQTT discovery configs (PRD 17.4).

Pure builders: given the active entries and one channel's settings they return
`{discovery topic: config dict}`. `notify_state.full_sync()` publishes them
(retained, before the states) and clears whatever was published before and is no
longer in the set, so opt-outs, deletes and turning discovery off need no hooks
of their own.

Layout, for node `std_<instance>` (the first 8 hex digits of the instance id, so
two STD installs never collide) and discovery prefix `<ha_prefix>`:

    <ha_prefix>/<component>/<node>/<object_id>/config

One hub device (`identifiers: [<node>]`), one device per entry
(`identifiers: [<node>_entry_<id>]`, `via_device` the hub) and one hub device per
inventory stream that has a published entry (`identifiers: [<node>_stream_<stream_id>]`,
`via_device` the STD hub; that stream's entry devices use it as `via_device`). Entities read the
retained topics of PRD 17.3 and use `<base>/status` for availability.
"""

import re

import notify_state
from models import CHECK_KIND_CONTAINER, SOURCE_MANUAL, SOURCE_NOTIFIER, SOURCE_STREAM

MANUFACTURER = "Service Tracker Dashboard"
# HA device model per entry source. A stream entry's model is its stream's display name
# (see `source_model`); "Stream" is only the fallback.
SOURCE_MODELS = {SOURCE_MANUAL: "Manual", SOURCE_NOTIFIER: "Docker container", SOURCE_STREAM: "Stream"}
ENTRY_STATES = ["up", "degraded", "down", "unknown", "none"]
HUB_COUNTS = ("up", "degraded", "down", "unknown")
SINCE_TEMPLATE = "{{ value_json.since if value_json.since else None }}"
AVAILABLE, NOT_AVAILABLE = "online", "offline"


def slug(text):
    """Lower-case `a-z0-9_` form of `text` for entity ids."""
    out = re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")
    return out or "unnamed"


def node_id(instance_id):
    return f"std_{instance_id.replace('-', '')[:8]}"


def config_topic(prefix, component, node, object_id):
    return f"{prefix}/{component}/{node}/{object_id}/config"


def _availability(base):
    return {"availability_topic": f"{base}/status",
            "payload_available": AVAILABLE, "payload_not_available": NOT_AVAILABLE}


def hub_device(node, device_prefix, version):
    return {"identifiers": [node], "name": device_prefix, "manufacturer": MANUFACTURER,
            "model": "STD", "sw_version": version}


def device_name(device_prefix, entry):
    """`<prefix> <name> (<host>)`; no host (a manual entry) is `<prefix> <name>`.
    The host is always shown so same-named entries on different hosts differ."""
    name = f"{device_prefix} {entry.container_name}"
    host = (entry.host or "").strip()
    return f"{name} ({host})" if host else name


def source_model(entry):
    """The device model: the stream's display name for a stream entry, else per source."""
    if entry.source == SOURCE_STREAM and entry.stream is not None:
        return entry.stream.display_name
    return SOURCE_MODELS.get(entry.source, "Manual")


def stream_device_id(node, stream_slug):
    return f"{node}_stream_{stream_slug}"


def stream_device(node, device_prefix, stream, version):
    """One hub device per inventory stream (PRD 17.4), below the STD hub."""
    return {"identifiers": [stream_device_id(node, stream.stream_id)],
            "name": f"{device_prefix} {stream.display_name} stream",
            "manufacturer": MANUFACTURER, "model": "Stream", "sw_version": version,
            "via_device": node}


def entry_device(node, device_prefix, entry):
    via = node
    if entry.stream_id is not None and entry.stream is not None:
        via = stream_device_id(node, entry.stream.stream_id)   # a stream entry hangs off its stream hub
    device = {
        "identifiers": [f"{node}_entry_{entry.id}"],
        "name": device_name(device_prefix, entry),
        "manufacturer": MANUFACTURER,
        "model": source_model(entry),
        "via_device": via,
    }
    if entry.image_tag:
        device["sw_version"] = entry.image_tag
    return device


def check_label(check):
    if check.kind == CHECK_KIND_CONTAINER:
        return "Container"
    return check.name or check.kind


def hub_configs(base, prefix, node, device_prefix, version):
    """The hub device's entities: connectivity and the per-state counts."""
    device = hub_device(node, device_prefix, version)
    hub_slug = slug(device_prefix)
    out = {}
    out[config_topic(prefix, "binary_sensor", node, "hub_connectivity")] = {
        "name": "Connectivity",
        "unique_id": f"{node}_hub_connectivity",
        "default_entity_id": f"binary_sensor.{hub_slug}_connectivity",
        "device_class": "connectivity",
        "state_topic": f"{base}/status",
        "payload_on": AVAILABLE, "payload_off": NOT_AVAILABLE,
        "device": device,
    }
    for state in HUB_COUNTS:
        out[config_topic(prefix, "sensor", node, f"hub_{state}")] = {
            "name": f"{state.capitalize()} entries",
            "unique_id": f"{node}_hub_{state}",
            "default_entity_id": f"sensor.{hub_slug}_{state}_entries",
            "state_topic": f"{base}/summary",
            "value_template": f"{{{{ value_json.{state} }}}}",
            "state_class": "measurement",
            **_availability(base),
            "device": device,
        }
    return out


STREAM_STATUSES = ["pending", "enabled", "disabled", "ignored"]


def stream_configs(base, prefix, node, device_prefix, stream, version):
    """A stream hub device's entities, all read from `<base>/stream/<stream_id>`:
    the status, the active and missing entry counts and the stale `problem` sensor."""
    device = stream_device(node, device_prefix, stream, version)
    device_slug = slug(device["name"])
    topic = f"{base}/{notify_state.stream_topic(stream.stream_id)}"
    key = stream.stream_id
    out = {}
    out[config_topic(prefix, "sensor", node, f"stream_{key}_status")] = {
        "name": "Status",
        "unique_id": f"{node}_stream_{key}_status",
        "default_entity_id": f"sensor.{device_slug}_status",
        "device_class": "enum",
        "options": list(STREAM_STATUSES),
        "state_topic": topic,
        "value_template": "{{ value_json.status }}",
        "json_attributes_topic": topic,
        **_availability(base),
        "device": device,
    }
    for name, field in (("Active entries", "active"), ("Missing entries", "missing")):
        out[config_topic(prefix, "sensor", node, f"stream_{key}_{field}")] = {
            "name": name,
            "unique_id": f"{node}_stream_{key}_{field}",
            "default_entity_id": f"sensor.{device_slug}_{field}_entries",
            "state_topic": topic,
            "value_template": f"{{{{ value_json.counts.{field} }}}}",
            "state_class": "measurement",
            **_availability(base),
            "device": device,
        }
    # PRD 18.9: on while the stream is stale (enabled, no snapshot for 2 x its interval).
    out[config_topic(prefix, "binary_sensor", node, f"stream_{key}_problem")] = {
        "name": "Problem",
        "unique_id": f"{node}_stream_{key}_problem",
        "default_entity_id": f"binary_sensor.{device_slug}_problem",
        "device_class": "problem",
        "state_topic": topic,
        "value_template": "{{ 'ON' if value_json.stale else 'OFF' }}",
        "payload_on": "ON", "payload_off": "OFF",
        "json_attributes_topic": topic,
        **_availability(base),
        "device": device,
    }
    return out


def entry_configs(base, prefix, node, device_prefix, entry, image_enabled=False):
    """The entry device's entities: roll-up state, since, one problem sensor per counted
    check that is not opted out, and (image update check on, something published for the
    entry) a read-only `update` entity."""
    device = entry_device(node, device_prefix, entry)
    device_slug = slug(device["name"])
    state_topic = notify_state.entry_topic(entry.id)
    out = {}
    out[config_topic(prefix, "sensor", node, f"entry_{entry.id}_state")] = {
        "name": "State",
        "unique_id": f"{node}_entry_{entry.id}_state",
        "default_entity_id": f"sensor.{device_slug}_state",
        "device_class": "enum",
        "options": list(ENTRY_STATES),
        "state_topic": f"{base}/{state_topic}",
        "value_template": "{{ value_json.state }}",
        "json_attributes_topic": f"{base}/{state_topic}",
        **_availability(base),
        "device": device,
    }
    out[config_topic(prefix, "sensor", node, f"entry_{entry.id}_since")] = {
        "name": "Since",
        "unique_id": f"{node}_entry_{entry.id}_since",
        "default_entity_id": f"sensor.{device_slug}_since",
        "device_class": "timestamp",
        "state_topic": f"{base}/{state_topic}",
        # `since` is ISO 8601 UTC (`...Z`); null renders "None", which MQTT
        # sensors treat as unknown instead of an invalid timestamp.
        "value_template": SINCE_TEMPLATE,
        **_availability(base),
        "device": device,
    }
    for check in notify_state.counted_checks(entry):
        if check.ha_exclude:
            continue
        label = check_label(check)
        topic = f"{base}/{notify_state.check_topic(entry.id, check.id)}"
        out[config_topic(prefix, "binary_sensor", node, f"check_{check.id}")] = {
            "name": label,
            "unique_id": f"{node}_check_{check.id}",
            "default_entity_id": f"binary_sensor.{device_slug}_{slug(label)}",
            "device_class": "problem",
            "state_topic": topic,
            "value_template": "{{ 'ON' if value_json.state == 'down' else 'OFF' }}",
            "payload_on": "ON", "payload_off": "OFF",
            "json_attributes_topic": topic,
            **_availability(base),
            "device": device,
        }
    if notify_state.image_info(entry, image_enabled) is not None:
        # HA `update` entity, read-only: no command_topic, so HA offers no install. No
        # entity_picture (STD has no public base URL). The state topic's JSON carries
        # installed_version, latest_version, title, release_url and release_summary.
        out[config_topic(prefix, "update", node, f"entry_{entry.id}_image")] = {
            "name": "Image",
            "unique_id": f"{node}_entry_{entry.id}_image",
            "default_entity_id": f"update.{device_slug}_image",
            "entity_category": "diagnostic",
            "state_topic": f"{base}/{notify_state.image_topic(entry.id)}",
            **_availability(base),
            "device": device,
        }
    return out


def desired_configs(entries, config, instance_id, version, image_enabled=False):
    """`{discovery topic: config}` for one channel with `ha_discovery` on. `image_enabled` is
    the image update check's switch: off, no `update` entity and no "Updates available" sensor."""
    base, prefix = config["base_topic"], config["ha_prefix"]
    device_prefix = config["ha_device_prefix"]
    node = node_id(instance_id)
    out = hub_configs(base, prefix, node, device_prefix, version)
    if image_enabled:
        out[config_topic(prefix, "sensor", node, "hub_updates")] = {
            "name": "Updates available",
            "unique_id": f"{node}_hub_updates",
            "default_entity_id": f"sensor.{slug(device_prefix)}_updates_available",
            "state_topic": f"{base}/summary",
            "value_template": "{{ value_json.updates }}",
            "state_class": "measurement",
            **_availability(base),
            "device": hub_device(node, device_prefix, version),
        }
    streams = {}
    for entry in entries:
        if not entry.ha_publish:
            continue
        out.update(entry_configs(base, prefix, node, device_prefix, entry, image_enabled))
        if entry.stream_id is not None and entry.stream is not None:
            streams[entry.stream.id] = entry.stream
    # A stream gets a hub device only while at least one of its entries is published.
    for stream in streams.values():
        out.update(stream_configs(base, prefix, node, device_prefix, stream, version))
    return out
