"""Plain functions turning models into the response dicts typed in
`mgmt_schemas.py` (v0.8.0, PRD 14). No queries beyond what is eager-loaded,
except `entry_detail_out` (exposures, widget)."""

import notify
from health_history import effective_target, iso_z
from health_state import entry_health
from mgmt_schemas import (
    CheckLastOut,
    CheckOut,
    EntryDetailOut,
    EntryHealthOut,
    EntryOut,
    ExposureOut,
    GroupOut,
    NotificationChannelOut,
    NotifierOut,
    WidgetInstanceOut,
    WidgetOut,
)
from models import SOURCE_NOTIFIER, HealthCheck, ServiceEntry, check_counts


def _local_iso(dt):
    """Columns written with `datetime.now()` are server-local and naive."""
    return dt.replace(microsecond=0).isoformat() if dt else None


def check_out(entry: ServiceEntry, check: HealthCheck) -> CheckOut:
    if check.last_ok is None:
        state = "unknown"
    else:
        state = "up" if check.last_ok else "down"
    last: CheckLastOut = {
        "state": state,
        "checked_at": iso_z(check.last_checked_at),
        "latency_ms": check.last_latency_ms,
        "status_code": check.last_status_code,
        "message": check.last_message,
    }
    return {
        "id": check.id,
        "entry_id": check.service_entry_id,
        "kind": check.kind,
        "name": check.name or check.kind,
        "check_type": check.check_type,
        "target": effective_target(entry, check),
        "mode": check.mode,
        "enabled": bool(check.enabled),
        "active": check_counts(entry, check),
        "interval_seconds": check.interval_seconds,
        "timeout_seconds": check.timeout_seconds,
        "verify_tls": check.verify_tls is not False,
        "dns_name": check.dns_name,
        "dns_record_type": check.dns_record_type,
        "dns_expected_rcode": check.dns_expected_rcode,
        "dns_expected_answer": check.dns_expected_answer,
        "cert_min_days": check.cert_min_days,
        "cert_expires_at": iso_z(check.last_cert_expires_at),
        "ha_exclude": bool(check.ha_exclude),
        "consecutive_failures": check.consecutive_failures or 0,
        "last": last,
    }


def health_out(entry: ServiceEntry) -> EntryHealthOut:
    h = entry_health(entry)
    return {
        "state": h.state,
        "label": h.label,
        "checks_total": h.total,
        "checks_failing": h.failing,
        "failures": [{"check": name, "message": msg} for name, msg in h.failures],
    }


def entry_out(entry: ServiceEntry) -> EntryOut:
    group = entry.group
    return {
        "id": entry.id,
        "name": entry.container_name,
        "host": entry.host,
        "description": entry.description,
        "source": entry.source,
        "group": {"id": group.id, "name": group.group_name} if group else None,
        "internalurl": entry.internalurl,
        "externalurl": entry.externalurl,
        "internalurl_source": entry.internalurl_source,
        "externalurl_source": entry.externalurl_source,
        "icon": entry.image_icon or None,
        "sort_priority": entry.sort_priority,
        "locked": bool(entry.is_static),
        "ha_publish": bool(entry.ha_publish),
        "stale": entry.source == SOURCE_NOTIFIER and entry.is_docker_status_stale,
        "last_updated": _local_iso(entry.last_updated),
        "deleted_at": _local_iso(entry.deleted_at),
        "health": health_out(entry),
        "checks": [check_out(entry, c) for c in entry.checks],
    }


def entry_detail_out(entry: ServiceEntry) -> EntryDetailOut:
    exposures: list[ExposureOut] = [
        {"layer": x.layer, "hostname": x.hostname, "tls": x.tls,
         "path_prefix": x.path_prefix, "auth": x.auth}
        for x in entry.exposures
    ]
    notifier: NotifierOut = {
        "container_id": entry.container_id,
        "stack_name": entry.stack_name,
        "docker_status": entry.docker_status,
        "started_at": entry.started_at,
        "last_api_update": _local_iso(entry.last_api_update),
        "image_registry": entry.image_registry,
        "image_owner": entry.image_owner,
        "image_name": entry.image_name,
        "image_tag": entry.image_tag,
        "reported_group_name": entry.notifier_reported_group_name,
        "reported_sort_priority": entry.notifier_reported_sort_priority,
        "networks": entry.networks,
        "exposed_ports": entry.exposed_ports,
        "published_ports": entry.published_ports,
        "exposures": exposures,
    }
    widget = entry.widget
    widget_out: WidgetOut | None = None
    if widget is not None:
        widget_out = {
            "id": widget.id,
            "type": widget.widget_name,
            "url": widget.widget_url,
            "fields": widget.widget_fields,
            "widget_api_key_set": bool(widget.widget_api_key),
        }
    return {**entry_out(entry), "notifier": notifier, "widget": widget_out}


def group_out(group) -> GroupOut:
    return {
        "id": group.id,
        "name": group.group_name,
        "sort_priority": group.group_sort_priority,
        "icon": group.group_icon,
        "entry_count": group.services_count or 0,
    }


def widget_out(widget) -> WidgetOut:
    """The key itself is never serialised, only whether one is stored."""
    return {
        "id": widget.id,
        "type": widget.widget_name,
        "url": widget.widget_url,
        "fields": widget.widget_fields,
        "widget_api_key_set": bool(widget.widget_api_key),
    }


def widget_instance_out(widget) -> WidgetInstanceOut:
    entry_ids = sorted(e.id for e in widget.services)
    return {**widget_out(widget), "entry_ids": entry_ids, "detached": not entry_ids}


def notification_channel_out(channel) -> NotificationChannelOut:
    """The secret is reported only as `secret_set`."""
    return {
        "id": channel.id,
        "type": channel.type,
        "name": channel.name,
        "enabled": bool(channel.enabled),
        "config": dict(channel.config or {}),
        "secret_set": bool(channel.secret),
        "status": notify.channel_status(channel),
        "created_at": iso_z(channel.created_at),
        "updated_at": iso_z(channel.updated_at),
    }
