"""Export format v1: the versioned document of operator-set state (PRD 20.5, design
docs/design/2026-11-20-backup-export-import.md sections 5 and 8).

An export holds only what the operator chose (groups, URLs they typed, checks, Home
Assistant picks, stream filters, blocks, channels without passwords, ...). It is never a
table dump. **No secret is ever written**: no MQTT password, no widget API key, no password
hash, no API key. Booleans (`secret_set`, `api_key_set`) say that something has to be set
again after an import.

`build_export()` applies the field ownership table of design 5.3, `dump()` serialises the
document as YAML or JSON (the same document). Both are plain functions that need an app
context. The models read leniently (`extra="allow"`, `unknown_keys()` lists what a reader
does not know); the writer only emits the known fields. Import (bak-03) builds on this
module and does not live here.
"""

import json
from datetime import datetime, timezone
from typing import Literal

import yaml
from flask import current_app, has_app_context
from pydantic import BaseModel, ConfigDict

import settings_store
from models import (
    SOURCE_MANUAL,
    SOURCE_NOTIFIER,
    SOURCE_STREAM,
    Group,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    User,
)

FORMAT = "std-export"
FORMAT_VERSION = 1
SUPPORTED_VERSIONS = (0, 1)     # 0 (the legacy entry list) is read by bak-03

Direction = Literal["internal", "external", "neither"]

# The YAML file opens with this comment: what an export deliberately leaves out.
YAML_HEADER = """\
# Service Tracker Dashboard export (format std-export, version 1).
# It holds the settings you chose. It does NOT include:
#   - passwords or keys: user passwords, API keys, widget API keys, the MQTT password
#     (the file only says that one was set)
#   - anything STD rebuilds on its own: container status, IPs and MACs, health results,
#     exposure observations, stream snapshots
#   - settings.yml and environment variables (api_token, retention days, ...)
#   - soft-deleted entries (they are in Settings -> Deleted; a database snapshot has them)
"""

# Config keys that must never leave the database even if a channel type grew one.
_SECRET_FRAGMENTS = ("secret", "password", "token", "api_key")


# --- models --------------------------------------------------------------------------------


class _Rec(BaseModel):
    """Lenient on read (unknown keys are kept in `model_extra` and reported, design 5.5)."""

    model_config = ConfigDict(extra="allow")


class UpdateCheck(_Rec):
    enabled: bool | None = None
    interval_hours: int | None = None


class JobSchedule(_Rec):
    enabled: bool | None = None
    time: str | None = None             # "HH:MM", container time
    keep_days: int | None = None
    format: Literal["yaml", "json"] | None = None   # export only


class BackupSchedule(_Rec):
    snapshot: JobSchedule | None = None
    export: JobSchedule | None = None


class RuntimeSettings(_Rec):
    exposure_layers: dict[str, Direction] | None = None
    exposure_layers_per_host: dict[str, dict[str, Direction]] | None = None
    update_check: UpdateCheck | None = None
    backup: BackupSchedule | None = None            # never the folder path


class GroupRecord(_Rec):
    name: str
    sort_priority: int | None = None
    icon: str | None = None


class WidgetRecord(_Rec):
    widget_name: str
    widget_url: str
    widget_fields: list = []
    api_key_set: bool = False           # the key itself is never exported


class ChannelRecord(_Rec):
    name: str
    type: str
    enabled: bool = False
    config: dict = {}
    secret_set: bool = False            # a password was stored; not the password


class BlockRecord(_Rec):
    key: str
    name: str | None = None
    ip: str | None = None
    blocked_at: datetime | None = None
    blocked_by: str | None = None


class StreamRecord(_Rec):
    stream_id: str
    key_type: str
    producer: str
    display_name: str
    status: str                         # informational, never applied by import
    network_include: list[str] | None = None
    network_exclude: list[str] | None = None
    default_checks: dict | None = None
    expected_interval_seconds: int | None = None
    missing_expiry_days: int | None = None
    blocks: list[BlockRecord] = []


class UrlValue(_Rec):
    value: str
    source: Literal["ui_edit", "explicit_label", "synthesized"] | None = None


class WidgetRef(_Rec):
    widget_name: str
    widget_url: str


class EntryIdentity(_Rec):
    container_name: str
    host: str | None = None
    stream: str | None = None
    stream_key: str | None = None
    name_source: Literal["stream", "ui_edit"] | None = None
    linked: bool = False
    pre_link_host: str | None = None


class CheckRecord(_Rec):                # HealthCheck.to_config(), same keys
    kind: Literal["internal_url", "external_url", "service", "container"]
    name: str | None = None
    check_type: str
    target: str | None = None
    mode: str
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    verify_tls: bool = True
    enabled: bool = False
    dns_name: str | None = None
    dns_record_type: str | None = None
    dns_expected_rcode: str | None = None
    dns_expected_answer: str | None = None
    cert_min_days: int | None = None
    ha_exclude: bool = False


class EntryRecord(_Rec):
    kind: Literal["docker", "manual", "stream"]
    identity: EntryIdentity
    is_static: bool = False
    description: str | None = None
    image_icon: str | None = None
    group: str | None = None
    sort_priority: int | None = None
    internalurl: UrlValue | None = None
    externalurl: UrlValue | None = None
    ha_publish: bool = False
    widget: WidgetRef | None = None
    checks: list[CheckRecord] = []


class UserRecord(_Rec):
    username: str
    email: str
    is_admin: bool = False
    is_active: bool = True


class ExportDoc(_Rec):
    format: Literal["std-export"]
    format_version: int
    exported_at: datetime
    std_version: str
    api_revision: int
    instance_id: str | None = None
    settings: RuntimeSettings = RuntimeSettings()
    groups: list[GroupRecord] = []
    widgets: list[WidgetRecord] = []
    notification_channels: list[ChannelRecord] = []
    streams: list[StreamRecord] = []
    entries: list[EntryRecord] = []
    users: list[UserRecord] = []


def unknown_keys(model, _path="", _out=None):
    """`{path: count}` of keys a parsed document carries that this version does not know,
    for the import warning "Ignored fields this STD does not know: `entries[].foo` (12x)".
    Paths use `[]` for list items (`entries[].identity.foo`)."""
    out = {} if _out is None else _out
    if isinstance(model, BaseModel):
        for key in (model.model_extra or {}):
            where = f"{_path}.{key}" if _path else key
            out[where] = out.get(where, 0) + 1
        for name in type(model).model_fields:
            value = getattr(model, name)
            unknown_keys(value, f"{_path}.{name}" if _path else name, out)
    elif isinstance(model, list):
        for item in model:
            unknown_keys(item, f"{_path}[]", out)
    return out


# --- building ------------------------------------------------------------------------------


def _utc(value):
    """A naive-UTC database datetime as an aware UTC one, without microseconds."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _std_version():
    if has_app_context():
        info = current_app.config.get("VERSION_INFO") or {}
        if info.get("version"):
            return str(info["version"])
    return "unknown"


def _safe_config(config):
    """The channel's stored non-secret config. A key that looks like a secret is dropped:
    nothing may leave the database through this door."""
    out = {}
    for key, value in (config or {}).items():
        lowered = str(key).lower()
        if any(f in lowered for f in _SECRET_FRAGMENTS):
            continue
        out[str(key)] = value
    return out


def _url_value(entry, which):
    """The entry's operator-owned URL (design 5.3), or None. A Docker entry's URL is
    operator state only when a UI edit wrote it; a manual or stream entry's URL always is."""
    value = getattr(entry, which)
    if not value:
        return None
    source = getattr(entry, f"{which}_source")
    if (entry.source or SOURCE_NOTIFIER) == SOURCE_NOTIFIER and source != "ui_edit":
        return None
    return UrlValue(value=value, source=source)


def _entry_record(entry):
    source = entry.source or SOURCE_NOTIFIER
    if source == SOURCE_STREAM:
        if entry.stream is None:
            return None
        kind = "stream"
        identity = EntryIdentity(
            container_name=entry.container_name, stream=entry.stream.stream_id,
            stream_key=entry.stream_key, name_source=entry.name_source or "stream",
            linked=bool(entry.stream_linked),
            pre_link_host=entry.pre_link_host if entry.stream_linked else None)
    elif source == SOURCE_MANUAL:
        kind = "manual"
        identity = EntryIdentity(container_name=entry.container_name, host=entry.host)
    else:
        kind = "docker"
        identity = EntryIdentity(container_name=entry.container_name, host=entry.host)
    # image_icon: a Docker entry's icon is rewritten on every register unless it is locked.
    icon_owned = kind != "docker" or bool(entry.is_static)
    widget = None
    if entry.widget is not None:
        widget = WidgetRef(widget_name=entry.widget.widget_name, widget_url=entry.widget.widget_url)
    return EntryRecord(
        kind=kind, identity=identity, is_static=bool(entry.is_static),
        description=entry.description or None,
        image_icon=(entry.image_icon or None) if icon_owned else None,
        group=entry.group.group_name if entry.group else None,
        sort_priority=entry.sort_priority,
        internalurl=_url_value(entry, "internalurl"),
        externalurl=_url_value(entry, "externalurl"),
        ha_publish=bool(entry.ha_publish), widget=widget,
        checks=[CheckRecord(**c.to_config()) for c in entry.checks])


def _entry_sort_key(rec):
    ident = rec.identity
    return (rec.kind, ident.host or "", ident.stream or "", ident.container_name or "",
            ident.stream_key or "")


def _runtime_settings(app):
    import backups  # backups imports this module for its export job

    layers = settings_store.get_layer_directions()
    per_host = {h: dict(sorted(m.items())) for h, m in settings_store.get_host_layer_overrides().items() if m}
    enabled, hours = settings_store.get_update_check_settings()
    eff = backups.effective_settings(app)

    def job(kind):
        e = eff[kind]
        return JobSchedule(enabled=e["enabled"]["value"], time=e["time"]["value"],
                           keep_days=e["keep_days"]["value"],
                           format=e["format"]["value"] if kind == "export" else None)

    return RuntimeSettings(
        exposure_layers=dict(sorted(layers.items())) or None,
        exposure_layers_per_host=dict(sorted(per_host.items())) or None,
        update_check=UpdateCheck(enabled=enabled, interval_hours=hours),
        backup=BackupSchedule(snapshot=job("snapshot"), export=job("export")))


def build_export(now=None) -> ExportDoc:
    """The export document of the current database (design 5.3, 8). Reads only; no
    secret is read into the result. Needs an app context."""
    from api_version import API_REVISION

    app = current_app._get_current_object()
    now = _utc(now or datetime.now(timezone.utc))

    groups = [GroupRecord(name=g.group_name, sort_priority=g.group_sort_priority, icon=g.group_icon or None)
              for g in Group.query.order_by(Group.group_name).all()]

    entries = [r for r in (_entry_record(e) for e in ServiceEntry.active().order_by(ServiceEntry.id))
               if r is not None]
    entries.sort(key=_entry_sort_key)

    # Attached widgets only: the ones an exported entry points at. Detached widgets and
    # those of soft-deleted entries stay in the trash (the database snapshot has them).
    widgets, seen = [], set()
    for e in ServiceEntry.active().filter(ServiceEntry.widget_id.isnot(None)).order_by(ServiceEntry.id):
        w = e.widget
        key = (w.widget_name, w.widget_url)
        if key in seen:
            continue
        seen.add(key)
        widgets.append(WidgetRecord(widget_name=w.widget_name, widget_url=w.widget_url,
                                    widget_fields=list(w.widget_fields or []),
                                    api_key_set=bool(w.widget_api_key)))
    widgets.sort(key=lambda w: (w.widget_name, w.widget_url))

    channels = [ChannelRecord(name=c.name, type=c.type, enabled=bool(c.enabled),
                              config=_safe_config(c.config), secret_set=bool(c.secret))
                for c in NotificationChannel.query.order_by(NotificationChannel.name).all()]

    streams = []
    for s in InventoryStream.query.order_by(InventoryStream.stream_id).all():
        blocks = [BlockRecord(key=b.key, name=b.name or None, ip=b.ip or None,
                              blocked_at=_utc(b.blocked_at), blocked_by=b.blocked_by or None)
                  for b in sorted(s.blocks, key=lambda b: b.key)]
        streams.append(StreamRecord(
            stream_id=s.stream_id, key_type=s.key_type, producer=s.producer,
            display_name=s.display_name, status=s.status,
            network_include=list(s.network_include) if s.network_include is not None else None,
            network_exclude=list(s.network_exclude) if s.network_exclude is not None else None,
            default_checks=dict(s.default_checks) if s.default_checks is not None else None,
            expected_interval_seconds=s.expected_interval_seconds,
            missing_expiry_days=s.missing_expiry_days, blocks=blocks))

    users = [UserRecord(username=u.username, email=u.email, is_admin=bool(u.is_admin),
                        is_active=bool(u.is_active))
             for u in User.query.order_by(User.username).all()]

    return ExportDoc(
        format=FORMAT, format_version=FORMAT_VERSION, exported_at=now,
        std_version=_std_version(), api_revision=API_REVISION,
        instance_id=settings_store.peek_instance_id(),
        settings=_runtime_settings(app), groups=groups, widgets=widgets,
        notification_channels=channels, streams=streams, entries=entries, users=users)


# --- serialising ---------------------------------------------------------------------------


def _plain(value):
    """Plain data for YAML/JSON: known fields only, a null model field left out (reading it
    back gives the same default), datetimes as UTC ISO 8601 with `Z`. Free-form dicts
    (`config`, `default_checks`) are kept as they are."""
    if isinstance(value, BaseModel):
        out = {}
        for name in type(value).model_fields:
            item = getattr(value, name)
            if item is not None:
                out[name] = _plain(item)
        return out
    if isinstance(value, datetime):
        return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    return value


def to_dict(doc) -> dict:
    """The document as plain, JSON-ready data (what both formats serialise)."""
    return _plain(doc)


def dump(doc, fmt) -> bytes:
    """The document as `yaml` (default order kept, header comment first) or `json`
    (indent 2, trailing newline). Both carry the same data."""
    data = to_dict(doc)
    if fmt == "yaml":
        body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        return (YAML_HEADER + body).encode("utf-8")
    if fmt == "json":
        return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    raise ValueError(f"unknown export format {fmt!r} (use 'yaml' or 'json')")
