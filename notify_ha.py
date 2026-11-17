"""Home Assistant MQTT discovery configs (PRD 17.4).

Pure builders: given the active entries and one channel's settings they return
`{discovery topic: config dict}`. `notify_state.full_sync()` publishes them
(retained, before the states) and clears whatever was published before and is no
longer in the set, so opt-outs, deletes and turning discovery off need no hooks
of their own.

Layout, for node `std_<instance>` (the first 8 hex digits of the instance id, so
two STD installs never collide) and discovery prefix `<ha_prefix>`:

    <ha_prefix>/<component>/<node>/<object_id>/config

One hub device (`identifiers: [<node>]`) and one device per entry
(`identifiers: [<node>_entry_<id>]`, `via_device` the hub). Entities read the
retained topics of PRD 17.3 and use `<base>/status` for availability.
"""

import re

import notify_state
from models import CHECK_KIND_CONTAINER, SOURCE_MANUAL

MANUFACTURER = "Service Tracker Dashboard"
ENTRY_STATES = ["up", "degraded", "down", "unknown", "none"]
HUB_COUNTS = ("up", "degraded", "down", "unknown")
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


def entry_device(node, device_prefix, entry):
    device = {
        "identifiers": [f"{node}_entry_{entry.id}"],
        "name": f"{device_prefix} {entry.container_name}",
        "manufacturer": MANUFACTURER,
        "model": "Manual" if entry.source == SOURCE_MANUAL else "Docker container",
        "via_device": node,
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


def entry_configs(base, prefix, node, device_prefix, entry):
    """The entry device's entities: roll-up state and one problem sensor per
    counted check that is not opted out."""
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
    return out


def desired_configs(entries, config, instance_id, version):
    """`{discovery topic: config}` for one channel with `ha_discovery` on."""
    base, prefix = config["base_topic"], config["ha_prefix"]
    device_prefix = config["ha_device_prefix"]
    node = node_id(instance_id)
    out = hub_configs(base, prefix, node, device_prefix, version)
    for entry in entries:
        if entry.ha_exclude:
            continue
        out.update(entry_configs(base, prefix, node, device_prefix, entry))
    return out
