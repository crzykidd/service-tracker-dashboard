"""Import engine: parse a v1 export or a legacy entry list, match every record against the
database as it is now, return a pure dry-run plan, and apply a selection in one transaction
(PRD 20.3-20.4, design docs/design/2026-11-20-backup-export-import.md sections 5.5, 6, 7, 9).

No routes, templates or API live here (bak-04 adds them). The layers are:

- `parse(raw, filename)`: size limit, JSON or YAML (no anchors or aliases), v0 list or v1
  mapping, per-record validation (a bad record becomes an *Invalid* row, only a bad header or
  an unsupported `format_version` rejects the file), record caps, unknown-key warnings.
- `plan(doc, stream_map)`: **pure**. Reads only, opens no lock, loads each table once and
  diffs in Python (like `streams.plan`). Every row has a stable `rid`, a status (design 6.1),
  per-field `missing` / `differs` diffs (6.2) and a digest.
- `fingerprint(...)` / `fingerprint_from_digests(...)`: sha256 over the selected rows only.
- `apply(...)`: takes `routes_api._UPSERT_LOCK`, then `streams._LOCK` (the order the management
  API's unlink route already uses), re-plans, compares the fingerprint (`ImportStale` writes
  nothing) and writes in one transaction in the 7.3 order. It never commits through a helper
  that commits, never writes a secret, never answers a link offer, never changes a stream's
  status and never creates a stream.
- the staging store the UI uses between the preview and the apply
  (`stage` / `load` / `discard` / `prune_expired`).

A selection is `{rid: {"apply": bool, "fields": [name, ...] | None, "target_id": int | None,
"create": bool, "options": [str]}}`; a row left out is not applied.
"""

import hashlib
import json
import logging
import os
import re
import secrets
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

import yaml
from flask import current_app
from pydantic import ValidationError
from sqlalchemy.orm import joinedload, selectinload

import backups
import check_form
import entry_rules
import export_format
import image_tags
import image_update
import notify
import settings_store
import streams
import synthesizer
from export_format import (
    ChannelRecord,
    EntryRecord,
    ExportDoc,
    GroupRecord,
    RuntimeSettings,
    StreamRecord,
    UserRecord,
    WidgetRecord,
)
from extensions import db
from models import (
    CHECK_KIND_CONTAINER,
    NAME_SOURCE_UI_EDIT,
    SOURCE_MANUAL,
    SOURCE_NOTIFIER,
    SOURCE_STREAM,
    STREAM_ENABLED,
    UNSET_PASSWORD_HASH,
    URL_CHECK_KINDS,
    Group,
    InventoryBlock,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    StreamLinkOffer,
    User,
    Widget,
    ensure_url_checks,
)
from notify_mqtt import MqttChannelType
from settings_loader import CONFIG_DIR

logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ENTRY_RECORDS = 20000
MAX_BLOCKS_PER_STREAM = streams.MAX_ITEMS          # 5,000, the ingest limit
STAGING_TTL_SECONDS = 60 * 60
MODES = ("fill", "overwrite")

# Row statuses (design 6.1).
MISSING = "missing"          # Matched - missing settings
DIFFERS = "differs"          # Matched - differs
IDENTICAL = "identical"      # Matched - identical
DELETED = "deleted"          # Matched - deleted locally
AMBIGUOUS = "ambiguous"
NOT_FOUND = "not_found"
WAITING = "waiting"
CONFLICT = "conflict"
INVALID = "invalid"
STATUSES = (MISSING, DIFFERS, IDENTICAL, DELETED, AMBIGUOUS, NOT_FOUND, WAITING, CONFLICT, INVALID)
STATUS_LABELS = {
    MISSING: "Matched - missing settings", DIFFERS: "Matched - differs", IDENTICAL: "Matched - identical",
    DELETED: "Matched - deleted locally", AMBIGUOUS: "Ambiguous", NOT_FOUND: "Not found",
    WAITING: "Waiting", CONFLICT: "Conflict", INVALID: "Invalid",
}

# Config keys of a channel that a re-import never changes on an existing channel (design 6.4):
# changing them needs the broker cleanup `notify.update_channel` runs.
NAMESPACE_KEYS = ("base_topic", "ha_prefix", "ha_device_prefix")

# What a freshly created health check looks like (models.ensure_url_checks / container).
_CHECK_VALUE_KEYS = ("check_type", "target", "mode", "interval_seconds", "timeout_seconds", "verify_tls",
                     "enabled", "dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer",
                     "cert_min_days", "ha_exclude")
_FRESH_URL_CHECK = {"check_type": "http", "target": None, "mode": "status", "interval_seconds": None,
                    "timeout_seconds": None, "verify_tls": True, "enabled": False, "dns_name": None,
                    "dns_record_type": None, "dns_expected_rcode": None, "dns_expected_answer": None,
                    "cert_min_days": None, "ha_exclude": False}
_FRESH_CONTAINER_CHECK = {**_FRESH_URL_CHECK, "check_type": "docker", "enabled": True}

GENERIC_TO_DO = (
    "Create a new ingest key for each stream sidecar (Settings -> API keys, scope Ingest) and set it "
    "in the sidecar's config.",
    "Set the notifier's api_token (it lives in settings.yml or the environment, not in the database).",
    "Create new management API keys for scripts and the MCP server.",
)


# --- errors --------------------------------------------------------------------------------


class ImportParseError(Exception):
    """The file cannot be read at all (too big, not an export, a newer format, bad syntax)."""


class ImportApplyError(Exception):
    """The import was rolled back; `str(exc)` says why and nothing was changed."""




class ImportStale(Exception):
    """The selected rows changed since the preview. Nothing was written. `plan` is the fresh plan."""

    def __init__(self, plan):
        super().__init__("Something changed since the preview (a register or a snapshot arrived). "
                         "Review and apply again.")
        self.plan = plan


# --- parsing -------------------------------------------------------------------------------

SECTION_MODELS = {
    "groups": GroupRecord, "widgets": WidgetRecord, "notification_channels": ChannelRecord,
    "streams": StreamRecord, "entries": EntryRecord, "users": UserRecord,
}


@dataclass
class ParsedDoc:
    """A parsed upload: the document, its warnings and the records that failed validation."""

    doc: ExportDoc
    warnings: list = field(default_factory=list)
    invalid: list = field(default_factory=list)     # [{rid, section, label, message}]
    filename: str | None = None
    legacy: bool = False

    def to_dict(self):
        return {"doc": self.doc.model_dump(mode="json"), "warnings": list(self.warnings),
                "invalid": list(self.invalid), "filename": self.filename, "legacy": self.legacy}

    @classmethod
    def from_dict(cls, data):
        return cls(doc=ExportDoc.model_validate(data["doc"]), warnings=list(data.get("warnings") or []),
                   invalid=list(data.get("invalid") or []), filename=data.get("filename"),
                   legacy=bool(data.get("legacy")))


class _NoAliasLoader(yaml.SafeLoader):
    """A SafeLoader that refuses anchors and aliases: the exporter never writes them, and
    refusing them rules out alias-expansion bombs."""

    def compose_node(self, parent, index):
        if self.check_event(yaml.events.AliasEvent):
            raise ImportParseError("YAML anchors and aliases are not allowed in an import file.")
        if self.peek_event().anchor is not None:
            raise ImportParseError("YAML anchors and aliases are not allowed in an import file.")
        return super().compose_node(parent, index)


def _load_text(raw, filename):
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportParseError("The file is not UTF-8 text.") from None
    ext = os.path.splitext(filename or "")[1].lower()
    stripped = text.lstrip()
    if ext == ".json" or stripped[:1] in ("{", "["):
        try:
            return json.loads(text)
        except ValueError as exc:
            if ext == ".json":
                raise ImportParseError(f"The file is not valid JSON: {exc}") from None
    try:
        return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 - SafeLoader subclass
    except ImportParseError:
        raise
    except yaml.YAMLError as exc:
        raise ImportParseError(f"The file is not valid YAML: {exc}") from None


def _first_error(exc):
    first = exc.errors()[0]
    where = ".".join(str(p) for p in first.get("loc", ()))
    return f"{where}: {first.get('msg')}" if where else str(first.get("msg"))


def _nh(host):
    """Host as the database stores it: a blank host is NULL."""
    if host is None:
        return None
    host = host.strip() if isinstance(host, str) else host
    return host or None


def _entry_rid(rec):
    ident = rec.identity
    if rec.kind == "stream":
        return f"entry:stream:{ident.stream or '-'}/{ident.stream_key}"
    return f"entry:{rec.kind}:{_nh(ident.host) or ''}/{ident.container_name}"


def _section_rid(section, rec):
    if section == "entries":
        return _entry_rid(rec)
    if section == "groups":
        return f"group:{rec.name}"
    if section == "widgets":
        return f"widget:{rec.widget_name}|{rec.widget_url}"
    if section == "notification_channels":
        return f"channel:{rec.name}"
    if section == "streams":
        return f"stream:{rec.stream_id}"
    return f"user:{rec.username}"


def _guess_label(section, item):
    if not isinstance(item, dict):
        return "(not a mapping)"
    if section == "entries":
        ident = item.get("identity") if isinstance(item.get("identity"), dict) else {}
        return str(ident.get("container_name") or "(entry)")
    for key in ("name", "stream_id", "username", "widget_name"):
        if item.get(key):
            return str(item[key])
    return f"({section} record)"


def _check_entry(rec, legacy):
    errs = []
    ident = rec.identity
    host = _nh(ident.host)
    name = ident.container_name
    if rec.kind == "docker" and not host:
        errs.append("a Docker entry needs a host")
    if rec.kind == "stream":
        if not legacy and not (ident.stream and ident.stream_key):
            errs.append("a stream entry needs identity.stream and identity.stream_key")
        if host:
            errs.append("a stream entry has no host")
        if not ident.stream_key:
            errs.append("a stream entry needs identity.stream_key")
        if len(ident.stream_key or "") > 128:
            errs.append("stream_key is limited to 128 characters")
        if ident.pre_link_host and len(ident.pre_link_host) > entry_rules.HOST_MAX:
            errs.append(f"pre_link_host is limited to {entry_rules.HOST_MAX} characters")
    errs += [e["message"] for e in entry_rules.validate_basic(name, host, rec.description)]
    for which in ("internalurl", "externalurl"):
        value = getattr(rec, which)
        if value is not None:
            errs += [e["message"] for e in entry_rules.validate_url(which, value.value)]
    if rec.image_icon:
        _, problem = entry_rules.resolve_icon(rec.image_icon)
        if problem:
            errs.append(problem)
    if rec.image_repo_url:
        errs += [e["message"] for e in entry_rules.validate_image_repo_url("image_repo_url", rec.image_repo_url)]
    if rec.kind == "docker":
        if rec.image_update_policy and rec.image_update_policy not in image_tags.POLICIES:
            errs.append("image_update_policy must be one of: " + ", ".join(image_tags.POLICIES))
        if rec.image_update_scope and rec.image_update_scope not in image_tags.SCOPES:
            errs.append("image_update_scope must be one of: " + ", ".join(image_tags.SCOPES))
        problem = image_tags.validate_tag_pattern(rec.image_tag_pattern)
        if problem:
            errs.append(problem)
    seen = set()
    services = 0
    for check in rec.checks:
        if check.kind in URL_CHECK_KINDS or check.kind == CHECK_KIND_CONTAINER:
            key = check.kind
        else:
            key = (check.check_type, check.name or (check.target or "")[:100])
            services += 1
        if key in seen:
            errs.append(f"two checks share the identity {key}")
        seen.add(key)
        errs += [f"check {check.kind}: {e['message']}" for e in _check_config_errors(check)]
    if services > check_form.MAX_SERVICE_CHECKS:
        errs.append(f"at most {check_form.MAX_SERVICE_CHECKS} service checks per entry")
    return errs


def _check_form_dict(cfg):
    """The `check_form` validator input for a check config (a CheckRecord or a normalised dict)."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k))
    return {"enabled": get("enabled"), "mode": get("mode"), "verify": get("verify_tls"),
            "interval": get("interval_seconds"), "timeout": get("timeout_seconds"),
            "cert_min_days": get("cert_min_days"), "check_type": get("check_type"), "name": get("name"),
            "target": get("target"), "dns_name": get("dns_name"), "dns_record_type": get("dns_record_type"),
            "dns_expected_rcode": get("dns_expected_rcode"),
            "dns_expected_answer": get("dns_expected_answer")}


def _check_config_errors(check):
    d = _check_form_dict(check)
    if check.kind == CHECK_KIND_CONTAINER:
        return check_form.validate_container_check(d)[1]
    if check.kind in URL_CHECK_KINDS:
        errors = check_form.validate_url_check_settings(d)[1]
        if check.check_type != "http":
            errors = errors + [{"field": "check_type", "message": "a URL check is always http"}]
        return errors
    return check_form.validate_service_check(d)[1]


def _check_group(rec):
    return [e["message"] for e in entry_rules.validate_group(rec.name, rec.icon)]


def _check_widget(rec):
    errs = []
    for label, value in (("widget_name", rec.widget_name), ("widget_url", rec.widget_url)):
        if not value or len(value) > 255:
            errs.append(f"{label} is required and limited to 255 characters")
    return errs


def _check_channel(rec):
    if not rec.name or not rec.name.strip():
        return ["name is required"]
    errs = []
    if len(rec.name.strip()) > notify.NAME_MAX:
        errs.append(f"name is limited to {notify.NAME_MAX} characters")
    clean, config_errors = notify.validate_config(rec.type, rec.config or {})
    errs += [f"{e['field']}: {e['message']}" for e in config_errors]
    return errs


def _check_stream(rec):
    errs = []
    if not streams.STREAM_ID_RE.match(rec.stream_id or ""):
        errs.append("stream_id is not a valid stream id")
    if not streams.KEY_TYPE_RE.match(rec.key_type or ""):
        errs.append("key_type is not valid")
    if not 1 <= len((rec.display_name or "").strip()) <= 32:
        errs.append("display_name must be 1-32 characters")
    try:
        if rec.network_include is not None:
            streams._clean_filter("network_include", rec.network_include)
        if rec.network_exclude is not None:
            streams._clean_filter("network_exclude", rec.network_exclude)
        if rec.default_checks is not None:
            streams.clean_default_checks(rec.default_checks)
    except (streams.StreamError, TypeError) as exc:
        errs.append(getattr(exc, "message", None) or str(exc))
    for name, value, low, high in (
            ("expected_interval_seconds", rec.expected_interval_seconds,
             streams.MIN_INTERVAL_SECONDS, streams.MAX_INTERVAL_SECONDS),
            ("missing_expiry_days", rec.missing_expiry_days, 1, streams.MAX_EXPIRY_DAYS)):
        if value is not None and not low <= value <= high:
            errs.append(f"{name} must be {low}-{high}")
    for block in rec.blocks:
        if not block.key or len(block.key) > 128:
            errs.append("a block needs a key of at most 128 characters")
            break
    return errs


def _check_user(rec):
    errs = []
    if not rec.username or len(rec.username) > 80:
        errs.append("username is required and limited to 80 characters")
    if not rec.email or len(rec.email) > 120:
        errs.append("email is required and limited to 120 characters")
    return errs


def _validate_record(section, rec, legacy):
    if section == "entries":
        return _check_entry(rec, legacy)
    return {"groups": _check_group, "widgets": _check_widget, "notification_channels": _check_channel,
            "streams": _check_stream, "users": _check_user}[section](rec)


def _unknown_warning(doc):
    unknown = export_format.unknown_keys(doc)
    if not unknown:
        return None
    parts = ", ".join(f"`{path}` ({count}x)" for path, count in sorted(unknown.items()))
    return f"Ignored fields this STD does not know: {parts}"


def parse(raw, filename=None):
    """Parse an upload into a `ParsedDoc`. Raises `ImportParseError` for a file that cannot
    be read at all; a bad record is an entry of `ParsedDoc.invalid` instead."""
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ImportParseError(f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    data = _load_text(raw, filename)
    if isinstance(data, list):
        return _parse_legacy(data, filename)
    if not isinstance(data, dict) or data.get("format") != export_format.FORMAT:
        raise ImportParseError(
            "This file is not an STD export (a v1 export is a mapping with `format: std-export`; "
            "an older backup is a list of entries).")
    version = data.get("format_version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ImportParseError("The export has no valid format_version.")
    if version > export_format.FORMAT_VERSION:
        raise ImportParseError(
            f"This export was made by STD {data.get('std_version') or 'unknown'} (format {version}). "
            f"This STD reads up to format {export_format.FORMAT_VERSION}. Upgrade STD first.")
    if version != export_format.FORMAT_VERSION:
        raise ImportParseError(f"Unsupported export format_version {version}.")

    warnings, invalid = [], []
    header = {k: v for k, v in data.items() if k not in SECTION_MODELS and k != "settings"}
    try:
        doc = ExportDoc.model_validate(header)
    except ValidationError as exc:
        raise ImportParseError(f"The export header is not valid ({_first_error(exc)}).") from None
    if data.get("settings") is not None:
        try:
            doc.settings = RuntimeSettings.model_validate(data["settings"])
        except ValidationError as exc:
            warnings.append(f"The settings section was ignored ({_first_error(exc)}).")

    for section, model in SECTION_MODELS.items():
        items = data.get(section)
        if items is None:
            continue
        if not isinstance(items, list):
            raise ImportParseError(f"`{section}` must be a list.")
        if section == "entries" and len(items) > MAX_ENTRY_RECORDS:
            raise ImportParseError(f"The file has more than {MAX_ENTRY_RECORDS} entry records.")
        seen, good = set(), []
        for index, item in enumerate(items):
            try:
                rec = model.model_validate(item)
            except ValidationError as exc:
                invalid.append({"rid": f"invalid:{section}/{index}", "section": section,
                                "label": _guess_label(section, item), "message": _first_error(exc)})
                continue
            problems = _validate_record(section, rec, legacy=False)
            rid = _section_rid(section, rec)
            if not problems and rid in seen:
                problems = ["duplicate record in the file"]
            if problems:
                invalid.append({"rid": f"invalid:{section}/{index}", "section": section,
                                "label": _guess_label(section, item), "message": "; ".join(problems)})
                continue
            seen.add(rid)
            if section == "streams":
                if len(rec.blocks) > MAX_BLOCKS_PER_STREAM:
                    raise ImportParseError(
                        f"Stream '{rec.stream_id}' has more than {MAX_BLOCKS_PER_STREAM} blocks.")
                keys, kept = set(), []
                for block in rec.blocks:
                    if block.key not in keys:
                        keys.add(block.key)
                        kept.append(block)
                rec.blocks = kept
            good.append(rec)
        setattr(doc, section, good)

    warning = _unknown_warning(doc)
    if warning:
        warnings.append(warning)
    return ParsedDoc(doc=doc, warnings=warnings, invalid=invalid, filename=filename, legacy=False)


def _parse_legacy(records, filename):
    if len(records) > MAX_ENTRY_RECORDS:
        raise ImportParseError(f"The file has more than {MAX_ENTRY_RECORDS} entry records.")
    bad = []
    doc, warnings = export_format.from_legacy(records, invalid=bad)
    invalid = [{"rid": f"invalid:entries/{b['index']}", "section": "entries", "label": b["label"],
                "message": b["message"]} for b in bad]
    good, seen = [], set()
    for index, rec in enumerate(doc.entries):
        problems = _check_entry(rec, legacy=True)
        rid = _entry_rid(rec)
        if not problems and rid in seen:
            problems = ["duplicate record in the file"]
        if problems:
            invalid.append({"rid": f"invalid:entries/L{index}", "section": "entries",
                            "label": rec.identity.container_name, "message": "; ".join(problems)})
            continue
        seen.add(rid)
        good.append(rec)
    doc.entries = good
    return ParsedDoc(doc=doc, warnings=warnings, invalid=invalid, filename=filename, legacy=True)


def _unwrap(doc):
    """`(ExportDoc, ParsedDoc | None)` from either."""
    if isinstance(doc, ParsedDoc):
        return doc.doc, doc
    return doc, None


# --- plan data -----------------------------------------------------------------------------


@dataclass
class FieldDiff:
    field: str
    file: object
    local: object
    kind: str                           # "missing" | "differs"
    note: str | None = None
    applicable: bool = True             # False: shown, never applied (design 6.4)

    def to_dict(self):
        return {"field": self.field, "file": self.file, "local": self.local, "kind": self.kind,
                "note": self.note, "applicable": self.applicable}


@dataclass
class RowPlan:
    rid: str
    section: str                        # entries | groups | channels | streams | blocks | users | settings
    source_group: str                   # docker | manual | stream:<slug> | groups | channels | ...
    label: str
    status: str = NOT_FOUND
    target_id: int | None = None
    candidates: list = field(default_factory=list)
    fields: list = field(default_factory=list)
    can_create: bool = False
    options: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    default_selected: bool = False
    record: object = None               # the file record (not serialised)
    ctx: dict = field(default_factory=dict)   # engine data (not serialised)

    def to_dict(self):
        return {"rid": self.rid, "section": self.section, "source_group": self.source_group,
                "label": self.label, "status": self.status, "status_label": STATUS_LABELS[self.status],
                "target_id": self.target_id, "candidates": list(self.candidates),
                "fields": [f.to_dict() for f in self.fields], "can_create": self.can_create,
                "options": list(self.options), "notes": list(self.notes),
                "default_selected": self.default_selected}


@dataclass
class ImportPlan:
    header: dict
    stream_mapping: list
    rows: list
    counts: dict
    warnings: list
    stream_map: dict = field(default_factory=dict)      # effective {file_id: local slug | None}
    digests: dict = field(default_factory=dict)         # {rid: digest}
    fingerprint: str = ""                               # over the default selection
    ctx: object = None                                  # engine data (not serialised)

    def row(self, rid):
        return next((r for r in self.rows if r.rid == rid), None)

    def default_selection(self):
        return {r.rid: {"apply": True} for r in self.rows if r.default_selected}

    def to_dict(self):
        return {"header": self.header, "stream_mapping": self.stream_mapping,
                "rows": [r.to_dict() for r in self.rows], "counts": self.counts,
                "warnings": list(self.warnings), "stream_map": self.stream_map,
                "fingerprint": self.fingerprint, "digests": dict(self.digests)}


@dataclass
class ImportResult:
    mode: str
    counts: dict = field(default_factory=dict)
    skipped: dict = field(default_factory=dict)
    still_to_do: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)
    applied_rids: list = field(default_factory=list)

    def to_dict(self):
        return {"mode": self.mode, "counts": dict(self.counts), "skipped": dict(self.skipped),
                "still_to_do": self.still_to_do, "notes": list(self.notes),
                "applied": list(self.applied_rids)}


# --- local state ---------------------------------------------------------------------------


class _Local:
    """Every table the matcher needs, loaded once."""

    def __init__(self):
        self.entries = (ServiceEntry.query
                        .options(selectinload(ServiceEntry.checks), joinedload(ServiceEntry.group),
                                 joinedload(ServiceEntry.widget))
                        .order_by(ServiceEntry.id).all())
        self.entry_by_id = {e.id: e for e in self.entries}
        self.pair = defaultdict(list)           # (host, name) -> non-stream entries
        self.by_key = {}                        # (stream pk, key) -> stream entry
        self.manual_active = defaultdict(list)  # (host, name) -> active manual entries
        self.dup_active = defaultdict(list)     # (host, name) -> every active entry (find_duplicate)
        for e in self.entries:
            if (e.source or SOURCE_NOTIFIER) == SOURCE_STREAM:
                if e.stream_id is not None:
                    self.by_key[(e.stream_id, e.stream_key)] = e
            else:
                self.pair[(e.host, e.container_name)].append(e)
            if e.deleted_at is None:
                self.dup_active[(e.host, e.container_name)].append(e)
                if e.source == SOURCE_MANUAL:
                    self.manual_active[(e.host, e.container_name)].append(e)
        self.groups = {g.group_name: g for g in Group.query.order_by(Group.id).all()}
        self.groups_ci = defaultdict(list)
        for g in self.groups.values():
            self.groups_ci[g.group_name.casefold()].append(g)
        self.widgets = {}
        for w in Widget.query.order_by(Widget.id).all():
            self.widgets.setdefault((w.widget_name, w.widget_url), w)
        self.channels = {c.name: c for c in NotificationChannel.query.all()}
        self.users = {u.username: u for u in User.query.all()}
        self.user_emails = {(u.email or "").casefold(): u for u in self.users.values()}
        self.streams = InventoryStream.query.order_by(InventoryStream.id).all()
        self.streams_by_slug = {s.stream_id: s for s in self.streams}
        self.blocks = {(b.stream_id, b.key): b for b in InventoryBlock.query.all()}
        self.offers = {(o.stream_id, o.key): o for o in StreamLinkOffer.query.all()}
        self.instance_id = settings_store.peek_instance_id()
        self.notifier_wins = current_app.config.get("register_field_ownership", "user_wins") == "notifier_wins"


class _DocCtx:
    """What the entry diff needs from the file."""

    def __init__(self, doc):
        self.groups = {g.name: g for g in doc.groups}
        self.widgets = {(w.widget_name, w.widget_url): w for w in doc.widgets}


# --- diff helpers --------------------------------------------------------------------------


def _norm(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def _diff(diffs, name, file_value, local_value, fresh, note=None):
    """Append a FieldDiff when `file_value` (non-null) differs from `local_value`."""
    if _norm(file_value) is None:
        return
    if _norm(file_value) == _norm(local_value):
        return
    diffs.append(FieldDiff(name, file_value, local_value, MISSING if fresh else DIFFERS, note))


def _check_cfg(cfg):
    """The compared form of a check config (a CheckRecord or `HealthCheck.to_config()`)."""
    get = cfg.get if isinstance(cfg, dict) else (lambda k: getattr(cfg, k, None))
    out = {}
    for key in _CHECK_VALUE_KEYS:
        value = _norm(get(key))
        if key == "verify_tls" and value is None:
            value = True
        if key in ("enabled", "ha_exclude"):
            value = bool(value)
        out[key] = value
    return out


def _service_key(cfg):
    name = _norm(cfg.get("name") if isinstance(cfg, dict) else cfg.name)
    target = _norm(cfg.get("target") if isinstance(cfg, dict) else cfg.target)
    check_type = cfg.get("check_type") if isinstance(cfg, dict) else cfg.check_type
    return (check_type, name or (target or "")[:100])


def _check_diffs(rec, entry, diffs, notes):
    local_url = {c.kind: c for c in entry.checks if c.kind in URL_CHECK_KINDS}
    local_container = entry.container_check
    local_services = defaultdict(list)
    for c in entry.service_checks:
        local_services[_service_key(c.to_config())].append(c)
    for check in rec.checks:
        file_cfg = _check_cfg(check)
        label = f"check:{check.kind}"
        if check.kind in URL_CHECK_KINDS:
            local = local_url.get(check.kind)
            local_cfg = _check_cfg(local.to_config()) if local is not None else dict(_FRESH_URL_CHECK)
            fresh_cfg = _FRESH_URL_CHECK
        elif check.kind == CHECK_KIND_CONTAINER:
            if local_container is None:
                notes.append("The Container check is added once the container registers; re-run the "
                             "import then.")
                continue
            local_cfg = _check_cfg(local_container.to_config())
            fresh_cfg = _FRESH_CONTAINER_CHECK
        else:
            key = _service_key(check)
            label = f"check:service:{key[0]}:{key[1]}"
            file_cfg = {**file_cfg, "name": key[1]}
            matches = local_services.get(key, [])
            if not matches:
                diffs.append(FieldDiff(label, file_cfg, None, MISSING))
                continue
            local_cfgs = [{**_check_cfg(m.to_config()), "name": key[1]} for m in matches]
            if len(matches) > 1:
                if any(c != file_cfg for c in local_cfgs):
                    diffs.append(FieldDiff(label, file_cfg, local_cfgs[0], DIFFERS,
                                           "several local checks share this type and name", False))
                continue
            if local_cfgs[0] != file_cfg:
                diffs.append(FieldDiff(label, file_cfg, local_cfgs[0], DIFFERS))
            continue
        if local_cfg == file_cfg:
            continue
        diffs.append(FieldDiff(label, file_cfg, local_cfg, MISSING if local_cfg == fresh_cfg else DIFFERS))


def _entry_diffs(rec, entry, L, D):
    """`(diffs, notes)` of one file entry against one local entry (design 6.2)."""
    diffs, notes = [], []
    docker = (entry.source or SOURCE_NOTIFIER) == SOURCE_NOTIFIER
    # group
    if rec.group:
        if rec.group not in D.groups and rec.group not in L.groups:
            notes.append(f"The group '{rec.group}' is not in the file or here; the field was skipped.")
        else:
            local_name = entry.group.group_name if entry.group else None
            if local_name != rec.group:
                if docker and L.notifier_wins:
                    notes.append("group: the notifier owns this field (notifier_wins), not imported.")
                else:
                    fresh = local_name is None or (docker and local_name == entry.notifier_reported_group_name)
                    diffs.append(FieldDiff("group", rec.group, local_name, MISSING if fresh else DIFFERS))
    # sort priority
    if rec.sort_priority is not None and rec.sort_priority != entry.sort_priority:
        if docker and L.notifier_wins:
            notes.append("sort_priority: the notifier owns this field (notifier_wins), not imported.")
        else:
            fresh = entry.sort_priority is None or (docker and entry.sort_priority
                                                    == entry.notifier_reported_sort_priority)
            diffs.append(FieldDiff("sort_priority", rec.sort_priority, entry.sort_priority,
                                   MISSING if fresh else DIFFERS))
    _diff(diffs, "description", rec.description, entry.description, not _norm(entry.description))
    # The icon is stored as `entry_rules.resolve_icon` writes it (`name` -> `name.svg`).
    _diff(diffs, "image_icon", entry_rules.resolve_icon(rec.image_icon)[0],
          entry_rules.resolve_icon(entry.image_icon)[0] or entry.image_icon, not _norm(entry.image_icon))
    _diff(diffs, "image_repo_url", (rec.image_repo_url or "").strip() or None, entry.image_repo_url,
          not _norm(entry.image_repo_url))
    if docker:
        # Image update settings are operator-owned; an absent value leaves the local one alone.
        _diff(diffs, "image_update_policy", rec.image_update_policy, entry.image_update_policy,
              (entry.image_update_policy or "auto") == "auto")
        _diff(diffs, "image_update_scope", rec.image_update_scope, entry.image_update_scope,
              not _norm(entry.image_update_scope))
        _diff(diffs, "image_tag_pattern", rec.image_tag_pattern, entry.image_tag_pattern,
              not _norm(entry.image_tag_pattern))
    if bool(rec.is_static) != bool(entry.is_static):
        diffs.append(FieldDiff("is_static", bool(rec.is_static), bool(entry.is_static),
                               MISSING if not entry.is_static else DIFFERS))
    if bool(rec.ha_publish) != bool(entry.ha_publish):
        diffs.append(FieldDiff("ha_publish", bool(rec.ha_publish), bool(entry.ha_publish),
                               MISSING if not entry.ha_publish else DIFFERS))
    # URLs: fresh when empty or not an explicit label / UI edit.
    for which in ("internalurl", "externalurl"):
        url = getattr(rec, which)
        if url is None or not _norm(url.value):
            continue
        local = getattr(entry, which)
        source = getattr(entry, f"{which}_source")
        if _norm(local) == _norm(url.value):
            continue
        fresh = not _norm(local) or source in (None, synthesizer.SOURCE_SYNTHESIZED)
        diffs.append(FieldDiff(which, url.value, local, MISSING if fresh else DIFFERS))
    # widget
    if rec.widget is not None:
        key = (rec.widget.widget_name, rec.widget.widget_url)
        wrec = D.widgets.get(key)
        if wrec is None and key not in L.widgets:
            notes.append(f"The widget '{key[0]}' is not in the file or here; the field was skipped.")
        else:
            local_widget = entry.widget
            local_key = (local_widget.widget_name, local_widget.widget_url) if local_widget else None
            file_value = {"widget_name": key[0], "widget_url": key[1]}
            local_value = ({"widget_name": local_key[0], "widget_url": local_key[1]} if local_key else None)
            note = None
            if wrec is not None and wrec.api_key_set and not (
                    local_key == key and local_widget.widget_api_key):
                existing = L.widgets.get(key)
                if existing is None or not existing.widget_api_key:
                    note = "needs its API key (Edit entry -> widget)"
            if local_key == key:
                if wrec is not None and wrec.widget_fields and not local_widget.widget_fields:
                    diffs.append(FieldDiff("widget", file_value, local_value, MISSING,
                                           "fills the widget's fields" + (f"; {note}" if note else "")))
            else:
                diffs.append(FieldDiff("widget", file_value, local_value,
                                       MISSING if local_key is None else DIFFERS, note))
    # a stream entry's name (the operator renamed it)
    if (entry.source == SOURCE_STREAM and rec.kind == "stream"
            and rec.identity.name_source == NAME_SOURCE_UI_EDIT
            and rec.identity.container_name != entry.container_name):
        fresh = entry.name_source != NAME_SOURCE_UI_EDIT
        diffs.append(FieldDiff("name", rec.identity.container_name, entry.container_name,
                               MISSING if fresh else DIFFERS))
    _check_diffs(rec, entry, diffs, notes)
    return diffs, notes


def _status_of(diffs):
    if any(d.kind == MISSING and d.applicable for d in diffs):
        return MISSING
    return DIFFERS if diffs else IDENTICAL


def _candidate(e):
    where = e.host or "no host"
    return {"id": e.id, "label": f"#{e.id} {e.container_name} on {where} ({e.source or SOURCE_NOTIFIER})"}


def _src_group(rec, slug=None):
    if rec.kind == "stream":
        return f"stream:{slug or rec.identity.stream or 'legacy'}"
    return rec.kind


# --- planning: entries ---------------------------------------------------------------------


def _finish_match(row, rec, entry, L, D):
    """Set status, diffs and notes of a row matched to `entry`."""
    diffs, notes = _entry_diffs(rec, entry, L, D)
    row.target_id = entry.id
    row.fields = diffs
    row.notes += notes
    if entry.deleted_at is not None:
        twin = [a for a in L.dup_active.get((entry.host, entry.container_name), []) if a.id != entry.id]
        if entry.stream_id is None and twin:
            row.status = CONFLICT
            row.notes.append("An active entry with that name already exists, so the deleted one cannot "
                             "be restored.")
            return
        row.status = DELETED
        row.options = ["restore"]
        row.notes.append("Matched an entry that was deleted here. Tick it with Restore to bring it back "
                         "and fill it.")
    else:
        row.status = _status_of(diffs)
    row.default_selected = row.status == MISSING


def _plan_pair_entry(row, rec, host, name, L, D):
    candidates = L.pair.get((host, name), [])
    active = [e for e in candidates if e.deleted_at is None]
    deleted = [e for e in candidates if e.deleted_at is not None]
    if len(active) == 1:
        _finish_match(row, rec, active[0], L, D)
    elif len(active) > 1:
        row.status = AMBIGUOUS
        row.candidates = [_candidate(e) for e in active]
        row.ctx["cand_fields"] = {}
        for e in active:
            diffs, _ = _entry_diffs(rec, e, L, D)
            row.ctx["cand_fields"][e.id] = diffs
        row.notes.append("More than one local entry has this host and name. Pick the one to use.")
    elif deleted:
        _finish_match(row, rec, deleted[0], L, D)
    else:
        _not_found(row, rec, host, name, L)


def _not_found(row, rec, host, name, L):
    clash = L.dup_active.get((host, name))
    if clash:
        row.status = CONFLICT
        row.notes.append(f"Import as new would duplicate '{name}'"
                         f"{' on ' + host if host else ' with no host'} (#{clash[0].id}).")
        return
    row.status = NOT_FOUND
    row.can_create = True
    row.ctx["new_key"] = (host, name)
    if rec.kind == "stream":
        row.notes.append("Import as new creates a manual entry. When the sidecar posts this device, a "
                         "link offer is made if its name matches. The recommended path is to wait for "
                         "the sidecar and re-run the import.")
    elif rec.kind == "docker":
        row.notes.append("Import as new creates a manual entry that the notifier adopts when the "
                         "container registers.")
    else:
        row.notes.append("Import as new creates a manual entry.")
    if rec.is_static:
        row.notes.append("The lock is not set on a new entry; it is applied on a re-run, after the "
                         "container registers.")


def _plan_entry(rec, L, D, smap, legacy):
    ident = rec.identity
    row = RowPlan(rid=_entry_rid(rec), section="entries", source_group=_src_group(rec), record=rec,
                  label=(f"{ident.container_name} ({ident.stream_key})" if rec.kind == "stream"
                         else f"{_nh(ident.host) or '-'}/{ident.container_name}"))
    if rec.deleted_in_file:
        row.notes.append("Deleted in the file. It is applied only if you tick it, and then it imports "
                         "as an active entry.")
    host, name = _nh(ident.host), ident.container_name
    if rec.kind != "stream":
        _plan_pair_entry(row, rec, host, name, L, D)
    elif ident.stream is None:
        # Legacy stream record: no stream id, so try every local mac stream by MAC.
        hits = [L.by_key[(s.id, ident.stream_key)] for s in L.streams
                if s.key_type == streams.KEY_TYPE_MAC and (s.id, ident.stream_key) in L.by_key]
        if len(hits) == 1:
            _finish_match(row, rec, hits[0], L, D)
        elif len(hits) > 1:
            row.status = AMBIGUOUS
            row.candidates = [_candidate(e) for e in hits]
            row.ctx["cand_fields"] = {e.id: _entry_diffs(rec, e, L, D)[0] for e in hits}
        else:
            row.source_group = "manual"
            _plan_pair_entry(row, rec, None, name, L, D)
            if row.status == NOT_FOUND:
                row.notes.insert(0, "A stream entry from an older backup (no stream id) and no stream "
                                    "device has this MAC.")
    else:
        _plan_stream_entry(row, rec, L, D, smap)
    if rec.deleted_in_file:
        row.default_selected = False
    return row


def _plan_stream_entry(row, rec, L, D, smap):
    ident = rec.identity
    mapping = smap.get(ident.stream)
    row.source_group = f"stream:{ident.stream}"
    if mapping is None or mapping["local"] is None:
        row.status = WAITING
        row.notes.append(mapping["note"] if mapping else "Its stream is not in the file.")
        return
    local = mapping["local"]
    key, name = ident.stream_key, ident.container_name
    target = L.by_key.get((local.id, key))
    pre_host = _nh(ident.pre_link_host)
    manual = L.manual_active.get((pre_host, name), [])
    if target is not None:
        _finish_match(row, rec, target, L, D)
        if manual:
            row.notes.append(f"A manual entry '{name}' also exists, probably from an earlier import as "
                             f"new. Link or delete it.")
        return
    offer = L.offers.get((local.id, key))
    offered = L.entry_by_id.get(offer.entry_id) if offer is not None else None
    if offered is not None and offered.deleted_at is None and offered.source == SOURCE_MANUAL:
        _finish_match(row, rec, offered, L, D)
        row.notes.append("Matched the manual entry offered for this device. Accept the link offer in "
                         "Streams to join it to the stream.")
        return
    if len(manual) == 1:
        _finish_match(row, rec, manual[0], L, D)
        row.notes.append("A manual entry, not linked to the stream yet.")
        return
    if len(manual) > 1:
        row.status = AMBIGUOUS
        row.candidates = [_candidate(e) for e in manual]
        row.ctx["cand_fields"] = {e.id: _entry_diffs(rec, e, L, D)[0] for e in manual}
        return
    if local.status != STREAM_ENABLED:
        row.status = WAITING
        row.notes.append(f"The stream is {local.status} here. Its entries appear when you enable it; "
                         f"re-run the import after enabling.")
        return
    _not_found(row, rec, pre_host, name, L)
    if (local.id, key) in L.blocks and row.status == NOT_FOUND:
        row.notes.append("This device is on the stream's block list.")


# --- planning: the other sections ----------------------------------------------------------


def _build_mapping(doc, stream_map, L):
    """`(mapping_rows, smap)`; `smap[file_id]` is `{"local": InventoryStream | None, "note": str}`."""
    stream_map = dict(stream_map or {})
    smap, used = {}, {}
    pending = []
    for srec in doc.streams:
        fid = srec.stream_id
        if fid in stream_map and stream_map[fid] is not None:
            slug = stream_map[fid]
            local = L.streams_by_slug.get(slug)
            problem = None
            if local is None:
                problem = f"There is no local stream '{slug}'."
            elif local.key_type != srec.key_type:
                problem = (f"'{slug}' reads {local.key_type} keys; the file's stream uses {srec.key_type}. "
                           f"Streams can only map to a stream with the same key type.")
            elif local.id in used:
                problem = "Each local stream can be the target once."
            if problem:
                smap[fid] = {"local": None, "note": problem, "error": problem}
            else:
                smap[fid] = {"local": local, "note": "", "error": None}
                used[local.id] = fid
        elif fid in stream_map:
            smap[fid] = {"local": None, "note": "Skipped in the stream mapping.", "error": None}
        else:
            pending.append(srec)
    for srec in pending:                           # automatic: the same stream id and key type
        local = L.streams_by_slug.get(srec.stream_id)
        if local is None:
            smap[srec.stream_id] = {"local": None, "error": None, "note":
                                    "Not present yet. Re-run the import after the sidecar posts."}
        elif local.key_type != srec.key_type:
            smap[srec.stream_id] = {"local": None, "error": None, "note":
                                    f"The local stream '{local.stream_id}' reads {local.key_type} keys, not "
                                    f"{srec.key_type}. Map it by hand to a stream of the same key type."}
        elif local.id in used:
            smap[srec.stream_id] = {"local": None, "error": "Each local stream can be the target once.",
                                    "note": "Each local stream can be the target once."}
        else:
            smap[srec.stream_id] = {"local": local, "note": "", "error": None}
            used[local.id] = srec.stream_id
    rows = []
    for srec in doc.streams:
        m = smap[srec.stream_id]
        local = m["local"]
        note = m["note"]
        if local is not None:
            if srec.status == STREAM_ENABLED and local.status != STREAM_ENABLED:
                note = (f"Enabled in the file, {local.status} here: enable it in Streams. Its settings "
                        f"and blocks can be applied now; its entries appear when you enable it. "
                        f"Re-run the import after enabling.")
            elif local.status != STREAM_ENABLED:
                note = f"The stream is {local.status} here."
        rows.append({
            "file_id": srec.stream_id, "display_name": srec.display_name, "key_type": srec.key_type,
            "producer": srec.producer, "file_status": srec.status,
            "local_id": local.stream_id if local is not None else None,
            "local_status": local.status if local is not None else None,
            "options": [{"id": s.stream_id, "label": f"{s.display_name} ({s.stream_id})"}
                        for s in L.streams if s.key_type == srec.key_type],
            "note": note, "error": m["error"],
        })
    return rows, smap


def _plan_group(rec, L):
    row = RowPlan(rid=f"group:{rec.name}", section="groups", source_group="groups", label=rec.name,
                  record=rec)
    local = L.groups.get(rec.name)
    if local is None:
        near = L.groups_ci.get(rec.name.casefold(), [])
        if near:
            row.status = AMBIGUOUS
            row.candidates = [{"id": g.id, "label": f"Use '{g.group_name}'"} for g in near]
            row.can_create = True
            row.notes.append(f"No group is called '{rec.name}', but '{near[0].group_name}' is close. "
                             f"Use it, or create '{rec.name}'.")
            return row
        row.status = MISSING
        row.default_selected = True
        row.fields = [FieldDiff("group", rec.name, None, MISSING, "created")]
        if rec.sort_priority is not None:
            row.fields.append(FieldDiff("sort_priority", rec.sort_priority, None, MISSING))
        if rec.icon:
            row.fields.append(FieldDiff("icon", rec.icon, None, MISSING))
        return row
    row.target_id = local.id
    diffs = []
    if rec.sort_priority is not None and rec.sort_priority != local.group_sort_priority:
        diffs.append(FieldDiff("sort_priority", rec.sort_priority, local.group_sort_priority,
                               MISSING if local.group_sort_priority is None else DIFFERS))
    _diff(diffs, "icon", rec.icon, local.group_icon, not _norm(local.group_icon))
    row.fields = diffs
    row.status = _status_of(diffs)
    row.default_selected = row.status == MISSING
    return row


def _channel_cfg(type_name, config):
    clean, errors = notify.validate_config(type_name, config or {})
    return clean if not errors else {**MqttChannelType.defaults(), **(config or {})}


def _plan_channel(rec, L):
    row = RowPlan(rid=f"channel:{rec.name}", section="channels", source_group="channels",
                  label=rec.name, record=rec)
    local = L.channels.get(rec.name)
    if local is None:
        row.status = NOT_FOUND
        row.can_create = True
        if rec.secret_set:
            row.notes.append("It is created disabled: it needs its password (Settings -> Notifications), "
                             "then enable it.")
        return row
    if local.type != rec.type:
        row.status = CONFLICT
        row.notes.append(f"A channel called '{rec.name}' exists with type '{local.type}', not '{rec.type}'.")
        return row
    row.target_id = local.id
    file_cfg = _channel_cfg(rec.type, rec.config)
    local_cfg = _channel_cfg(local.type, local.config)
    defaults = MqttChannelType.defaults()
    diffs = []
    for key in sorted(file_cfg):
        if file_cfg[key] == local_cfg.get(key):
            continue
        if key in NAMESPACE_KEYS:
            diffs.append(FieldDiff(f"config.{key}", file_cfg[key], local_cfg.get(key), DIFFERS,
                                   "change this in Notifications, which offers to clear the old topics",
                                   False))
            continue
        fresh = local_cfg.get(key) == defaults.get(key)
        diffs.append(FieldDiff(f"config.{key}", file_cfg[key], local_cfg.get(key), MISSING if fresh else DIFFERS))
    needs_password = rec.secret_set and not local.secret
    if bool(rec.enabled) != bool(local.enabled) and not (needs_password and rec.enabled):
        diffs.append(FieldDiff("enabled", bool(rec.enabled), bool(local.enabled),
                               MISSING if not local.enabled else DIFFERS))
    if needs_password:
        row.notes.append("The file says a password was set. Set it in Settings -> Notifications.")
    row.fields = diffs
    row.status = _status_of(diffs)
    row.default_selected = row.status == MISSING
    return row


def _plan_user(rec, L):
    row = RowPlan(rid=f"user:{rec.username}", section="users", source_group="users", label=rec.username,
                  record=rec)
    local = L.users.get(rec.username)
    if local is None:
        clash = L.user_emails.get(rec.email.casefold())
        if clash is not None:
            row.status = CONFLICT
            row.notes.append(f"The email {rec.email} belongs to the user '{clash.username}'.")
            return row
        row.status = NOT_FOUND
        row.can_create = True
        row.notes.append("Created without a password: the user cannot sign in until an admin sets one in "
                         "Users.")
        return row
    row.target_id = local.id
    diffs = []
    for name, file_value, local_value in (("email", rec.email, local.email),
                                          ("is_admin", bool(rec.is_admin), bool(local.is_admin)),
                                          ("is_active", bool(rec.is_active), bool(local.is_active))):
        if file_value != local_value:
            diffs.append(FieldDiff(name, file_value, local_value, DIFFERS, "not changed by import", False))
    row.fields = diffs
    row.status = DIFFERS if diffs else IDENTICAL
    if diffs:
        row.notes.append("An existing user is never modified by an import.")
    return row


def _plan_stream_settings(srec, m, L):
    row = RowPlan(rid=f"stream:{srec.stream_id}", section="streams", source_group="streams",
                  label=srec.display_name, record=srec)
    local = m["local"]
    if local is None:
        row.status = WAITING
        row.notes.append(m["note"])
        return row
    row.target_id = local.id
    diffs = []
    _diff(diffs, "display_name", srec.display_name, local.display_name, False)
    for name in ("network_include", "network_exclude"):
        value = getattr(srec, name)
        if value is None:
            continue
        cleaned = streams._clean_filter(name, value)
        current = getattr(local, name)
        if cleaned != current:
            diffs.append(FieldDiff(name, cleaned, current, MISSING if current is None else DIFFERS))
    if srec.default_checks is not None:
        cleaned = streams.clean_default_checks(srec.default_checks)
        if cleaned != local.default_checks:
            diffs.append(FieldDiff("default_checks", cleaned, local.default_checks,
                                   MISSING if local.default_checks is None else DIFFERS))
    for name in ("expected_interval_seconds", "missing_expiry_days"):
        value = getattr(srec, name)
        if value is not None and value != getattr(local, name):
            diffs.append(FieldDiff(name, value, getattr(local, name),
                                   MISSING if getattr(local, name) is None else DIFFERS))
    row.fields = diffs
    row.status = _status_of(diffs)
    row.default_selected = row.status == MISSING
    if local.status != STREAM_ENABLED:
        row.notes.append(f"The stream is {local.status}. Applying its filters and blocks now means "
                         f"enabling it creates only the entries you want.")
    return row


def _plan_block(srec, block, m, L):
    row = RowPlan(rid=f"block:{srec.stream_id}/{block.key}", section="blocks", source_group="streams",
                  label=f"{block.name or block.key} ({block.key})", record=block)
    local = m["local"]
    if local is None:
        row.status = WAITING
        row.notes.append(m["note"])
        return row
    row.ctx["stream_pk"] = local.id
    existing = L.blocks.get((local.id, block.key))
    if existing is not None:
        row.status = IDENTICAL
        row.target_id = existing.id
        return row
    row.status = MISSING
    row.default_selected = True
    row.fields = [FieldDiff("block", {"key": block.key, "name": block.name, "ip": block.ip}, None, MISSING)]
    entry = L.by_key.get((local.id, block.key))
    if entry is not None and entry.deleted_at is None:
        row.options = ["soft_delete_entry"]
        row.ctx["entry_id"] = entry.id
        row.notes.append(f"An entry '{entry.container_name}' already exists for this key. Tick "
                         f"'Also soft-delete the entry' to remove it; otherwise it stays.")
    return row


def _plan_settings(doc, L, app):
    rows = []
    cfg = doc.settings
    layers = settings_store.get_layer_directions()
    hosts = settings_store.get_host_layer_overrides()
    for layer, direction in sorted((cfg.exposure_layers or {}).items()):
        row = RowPlan(rid=f"setting:exposure_layers/{layer}", section="settings", source_group="settings",
                      label=f"Exposure layer {layer}", record=("exposure_layers", layer, direction))
        local = layers.get(layer)
        eff = local or settings_store.DEFAULT_DIRECTION
        if direction != eff:
            row.fields = [FieldDiff("direction", direction, local,
                                    MISSING if eff == settings_store.DEFAULT_DIRECTION else DIFFERS)]
        row.status = _status_of(row.fields)
        row.default_selected = row.status == MISSING
        rows.append(row)
    for host, layer_map in sorted((cfg.exposure_layers_per_host or {}).items()):
        for layer, direction in sorted(layer_map.items()):
            row = RowPlan(rid=f"setting:exposure_layers_per_host/{host}/{layer}", section="settings",
                          source_group="settings", label=f"Exposure override {host} / {layer}",
                          record=("exposure_layers_per_host", (host, layer), direction))
            local = hosts.get(host, {}).get(layer)
            if direction != local:
                row.fields = [FieldDiff("direction", direction, local, MISSING if local is None else DIFFERS)]
            row.status = _status_of(row.fields)
            row.default_selected = row.status == MISSING
            rows.append(row)
    if cfg.update_check is not None:
        enabled, hours = settings_store.get_update_check_settings()
        row = RowPlan(rid="setting:update_check", section="settings", source_group="settings",
                      label="Update check", record=("update_check", None, cfg.update_check))
        if cfg.update_check.enabled is not None and cfg.update_check.enabled != enabled:
            row.fields.append(FieldDiff("enabled", cfg.update_check.enabled, enabled,
                                        MISSING if enabled == settings_store.DEFAULT_UPDATE_CHECK_ENABLED
                                        else DIFFERS))
        if (cfg.update_check.interval_hours is not None and cfg.update_check.interval_hours >= 1
                and cfg.update_check.interval_hours != hours):
            row.fields.append(FieldDiff("interval_hours", cfg.update_check.interval_hours, hours,
                                        MISSING if hours == settings_store.DEFAULT_UPDATE_CHECK_INTERVAL_HOURS
                                        else DIFFERS))
        row.status = _status_of(row.fields)
        row.default_selected = row.status == MISSING
        rows.append(row)
    if cfg.backup is not None:
        eff = backups.effective_flat(app)
        for kind in backups.KINDS:
            sched = getattr(cfg.backup, kind)
            if sched is None:
                continue
            row = RowPlan(rid=f"setting:backup/{kind}", section="settings", source_group="settings",
                          label=f"Backup {kind} schedule", record=("backup", kind, sched))
            for name in ("enabled", "time", "keep_days", "format"):
                value = getattr(sched, name)
                key = f"{kind}_{name}"
                if value is None or key not in eff:
                    continue
                entry = eff[key]
                if name == "time" and not backups.TIME_RE.match(str(value)):
                    row.notes.append(f"{name}: '{value}' is not a time of day, skipped.")
                    continue
                if name == "keep_days" and not backups._valid_keep_days(value):
                    row.notes.append("keep_days: not a number of days from 1 to 365, skipped.")
                    continue
                if name == "format" and value not in ("yaml", "json"):
                    continue
                if entry["env_name"]:
                    if value != entry["value"]:
                        row.notes.append(f"{name}: set by environment ({entry['env_name']}), not imported.")
                    continue
                if value != entry["value"]:
                    row.fields.append(FieldDiff(name, value, entry["value"],
                                                DIFFERS if entry["origin"] == "ui" else MISSING))
            row.status = _status_of(row.fields)
            row.default_selected = row.status == MISSING
            rows.append(row)
    return rows


# --- plan ----------------------------------------------------------------------------------


def _jsonable(value):
    return json.dumps(value, sort_keys=True, default=str)


def _digest(row):
    material = [row.rid, row.status, row.target_id, sorted(c["id"] for c in row.candidates),
                [(f.field, f.kind, f.applicable, _jsonable(f.file), _jsonable(f.local))
                 for f in sorted(row.fields, key=lambda f: f.field)]]
    cand = row.ctx.get("cand_fields") or {}
    material.append([(cid, [(f.field, f.kind, _jsonable(f.file), _jsonable(f.local))
                            for f in sorted(fields, key=lambda f: f.field)])
                     for cid, fields in sorted(cand.items())])
    return hashlib.sha256(_jsonable(material).encode()).hexdigest()


def fingerprint_from_digests(digests, selection, stream_map):
    """sha256 over the selected rows' digests and the stream map. A row the plan no longer has
    hashes as absent, so a vanished row changes the fingerprint."""
    chosen = sorted(rid for rid, sel in (selection or {}).items() if _selected(sel))
    material = [[rid, digests.get(rid)] for rid in chosen]
    return hashlib.sha256(_jsonable([material, sorted((stream_map or {}).items())]).encode()).hexdigest()


def fingerprint(plan, selection, stream_map=None):
    """The fingerprint of the selected rows of `plan` (design 7.2). `stream_map` is accepted for
    symmetry with `apply`; the plan already carries the effective map it was built with."""
    return fingerprint_from_digests(plan.digests, selection, plan.stream_map)


def _selected(sel):
    if isinstance(sel, dict):
        return bool(sel.get("apply", True))
    return bool(sel)


def plan(doc, stream_map=None):
    """The dry-run plan of `doc` against the database as it is now. Pure: reads only, opens no
    lock, writes nothing. `doc` is an `ExportDoc` or a `ParsedDoc` (its invalid rows and warnings
    are then part of the plan)."""
    doc, parsed = _unwrap(doc)
    app = current_app._get_current_object()
    L, D = _Local(), _DocCtx(doc)
    legacy = doc.format_version == 0
    mapping_rows, smap = _build_mapping(doc, stream_map, L)
    rows = []

    for rec in sorted(doc.groups, key=lambda g: g.name):
        rows.append(_plan_group(rec, L))
    for rec in sorted(doc.notification_channels, key=lambda c: c.name):
        rows.append(_plan_channel(rec, L))
    for srec in sorted(doc.streams, key=lambda s: s.stream_id):
        m = smap[srec.stream_id]
        rows.append(_plan_stream_settings(srec, m, L))
        for block in sorted(srec.blocks, key=lambda b: b.key):
            rows.append(_plan_block(srec, block, m, L))
    for rec in sorted(doc.users, key=lambda u: u.username):
        rows.append(_plan_user(rec, L))
    rows += _plan_settings(doc, L, app)
    creating = {}
    for rec in doc.entries:
        row = _plan_entry(rec, L, D, smap, legacy)
        key = row.ctx.get("new_key")
        if row.status == NOT_FOUND and key in creating:      # two records would become the same entry
            row.status, row.can_create = CONFLICT, False
            row.notes.append(f"Another record in the file ({creating[key]}) already imports as new with "
                             f"this name, so this one would be a duplicate.")
        elif row.status == NOT_FOUND:
            creating[key] = row.label
        rows.append(row)
    if parsed is not None:
        for bad in parsed.invalid:
            section = {"notification_channels": "channels"}.get(bad["section"], bad["section"])
            rows.append(RowPlan(rid=bad["rid"], section=section, source_group=section, label=bad["label"],
                                status=INVALID, notes=[bad["message"]]))
    _order_rows(rows)

    warnings = list(parsed.warnings) if parsed is not None else []
    if L.notifier_wins and any("notifier_wins" in n for r in rows for n in r.notes):
        warnings.append("register_field_ownership is notifier_wins: the group and sort priority of Docker "
                        "entries are not imported, because the next register would overwrite them.")
    for m in mapping_rows:
        if m["error"]:
            warnings.append(f"Stream '{m['file_id']}': {m['error']}")

    counts = {"total": len(rows), "by_status": {s: 0 for s in STATUSES}, "by_group": {}}
    for r in rows:
        counts["by_status"][r.status] += 1
        counts["by_group"].setdefault(r.source_group, {s: 0 for s in STATUSES})[r.status] += 1
    header = {
        "format_version": doc.format_version, "exported_at": doc.exported_at.isoformat(),
        "std_version": doc.std_version, "api_revision": doc.api_revision, "instance_id": doc.instance_id,
        "filename": parsed.filename if parsed is not None else None, "legacy": legacy,
        "other_install": bool(doc.instance_id and doc.instance_id != L.instance_id),
    }
    effective = {m["file_id"]: m["local_id"] for m in mapping_rows}
    result = ImportPlan(header=header, stream_mapping=mapping_rows, rows=rows, counts=counts,
                        warnings=warnings, stream_map=effective, ctx=(L, D))
    result.digests = {r.rid: _digest(r) for r in rows}
    result.fingerprint = fingerprint_from_digests(result.digests, result.default_selection(), effective)
    return result


def _order_rows(rows):
    """Stable ordering: Docker, manual, one per stream, groups, channels, streams and blocks,
    users, settings (design 12.2); within a group the plan order."""
    order = {"docker": 0, "manual": 1}

    def key(r):
        if r.section == "entries":
            sg = r.source_group
            return (order.get(sg, 2), sg if sg.startswith("stream:") else "")
        return (3 + ["groups", "channels", "streams", "blocks", "users", "settings"].index(r.section)
                if r.section in ("groups", "channels", "streams", "blocks", "users", "settings") else 20, "")
    rows.sort(key=key)


# --- applying ------------------------------------------------------------------------------


def _chosen_fields(row, sel, mode):
    names = sel.get("fields") if isinstance(sel, dict) else None
    out = []
    for f in row.fields:
        if not f.applicable:
            continue
        if names is not None and f.field not in names:
            continue
        if f.kind == DIFFERS and mode != "overwrite":
            continue
        out.append(f)
    return out


class _Applier:
    def __init__(self, the_plan, selection, mode, actor, app):
        self.plan = the_plan
        self.L, self.D = the_plan.ctx
        self.selection = selection
        self.mode = mode
        self.actor = actor
        self.app = app
        self.now = datetime.now()
        self.alias = {}                       # file group name -> local group name
        self.result = ImportResult(mode=mode)
        self.c = defaultdict(int)
        self.skipped = defaultdict(int)
        self.todo = {"users_without_password": [], "channels_disabled": [], "widgets_need_key": [],
                     "streams_not_present": [], "streams_to_enable": [], "open_link_offers": 0,
                     "entries_created_waiting": 0, "locks_deferred": []}
        self.channels_changed = False
        self.backup_changed = False
        self.exposure_changed = False
        self.new_widgets = {}

    # -- selection -----------------------------------------------------------------------

    def selected_rows(self):
        out = []
        for row in self.plan.rows:
            sel = self.selection.get(row.rid)
            if sel is None or not _selected(sel):
                if row.status in (MISSING, DIFFERS, DELETED, AMBIGUOUS, NOT_FOUND):
                    self.skipped["not selected"] += 1
                continue
            sel = sel if isinstance(sel, dict) else {"apply": True}
            if row.status in (WAITING, CONFLICT, INVALID, IDENTICAL):
                self.skipped[row.status] += 1
                continue
            out.append((row, sel))
        return out

    def run(self):
        rows = self.selected_rows()
        order = ["groups", "channels", "streams", "blocks", "users", "settings", "entries"]
        for section in order:
            for row, sel in rows:
                if row.section == section:
                    if getattr(self, f"_apply_{section}")(row, sel):
                        self.result.applied_rids.append(row.rid)
                        logger.debug("Import applied %s", row.rid)
        self._finish()
        return self.result

    # -- shared writers ------------------------------------------------------------------

    def _count_field(self, diff):
        self.c["fields_overwritten" if diff.kind == DIFFERS else "fields_filled"] += 1

    def _group_named(self, name):
        local_name = self.alias.get(name, name)
        existing = Group.query.filter_by(group_name=local_name).first()
        if existing is not None:
            return existing
        group = Group(group_name=local_name)
        db.session.add(group)
        db.session.flush()
        self.c["groups_created"] += 1
        return group

    def _widget_for(self, ref):
        key = (ref["widget_name"], ref["widget_url"])
        widget = Widget.query.filter_by(widget_name=key[0], widget_url=key[1]).order_by(Widget.id).first()
        wrec = self.D.widgets.get(key)
        if widget is None:
            widget = Widget(widget_name=key[0], widget_url=key[1],
                            widget_fields=list(wrec.widget_fields) if wrec else [], widget_api_key=None)
            db.session.add(widget)
            db.session.flush()
            self.c["widgets_created"] += 1
        elif wrec is not None and wrec.widget_fields and not widget.widget_fields:
            widget.widget_fields = list(wrec.widget_fields)
        if wrec is not None and wrec.api_key_set and not widget.widget_api_key:
            label = f"{key[0]} ({key[1]})"
            if label not in self.todo["widgets_need_key"]:
                self.todo["widgets_need_key"].append(label)
        return widget

    def _write_check(self, entry, diff):
        cfg = diff.file
        kind = diff.field.split(":")[1]
        d = _check_form_dict(cfg)
        if kind in URL_CHECK_KINDS:
            ensure_url_checks(entry)
            check = entry.url_check(kind)
            values, errors = check_form.validate_url_check_settings(d)
        elif kind == CHECK_KIND_CONTAINER:
            check = entry.container_check
            if check is None:
                return
            values, errors = check_form.validate_container_check(d)
        else:
            key = _service_key(cfg)
            existing = [c for c in entry.service_checks if _service_key(c.to_config()) == key]
            values, errors = check_form.validate_service_check(d)
            if errors:
                raise ImportApplyError(f"{entry.container_name}: invalid check {key}: {errors[0]['message']}")
            values["ha_exclude"] = bool(cfg.get("ha_exclude"))
            if existing:
                check_form.apply_check_values(existing[0], values)
            else:
                entry.checks.append(check_form.new_service_check(values))
            return
        if errors:
            raise ImportApplyError(f"{entry.container_name}: invalid {kind} check: {errors[0]['message']}")
        values["ha_exclude"] = bool(cfg.get("ha_exclude"))
        check_form.apply_check_values(check, values)

    def _write_entry_field(self, entry, diff):
        name, value = diff.field, diff.file
        if name == "group":
            entry.group_id = self._group_named(value).id
        elif name == "sort_priority":
            entry.sort_priority = value
        elif name == "description":
            entry.description = value.strip()[:entry_rules.DESCRIPTION_MAX]
        elif name == "image_icon":
            entry.image_icon = entry_rules.resolve_icon(value)[0] or None
        elif name == "image_repo_url":
            entry.image_repo_url = value.strip() or None
        elif name in ("image_update_policy", "image_update_scope", "image_tag_pattern"):
            setattr(entry, name, value.strip() or None)
            if name == "image_update_policy" and not entry.image_update_policy:
                entry.image_update_policy = "auto"
            image_update.recompute_entry(entry)
        elif name == "is_static":
            entry.is_static = bool(value)
        elif name == "ha_publish":
            entry.ha_publish = bool(value)
        elif name in ("internalurl", "externalurl"):
            setattr(entry, name, value.strip())
            setattr(entry, f"{name}_source", synthesizer.SOURCE_UI_EDIT)
        elif name == "widget":
            entry.widget = self._widget_for(value)
        elif name == "name":
            entry.container_name = value
            entry.name_source = NAME_SOURCE_UI_EDIT
        elif name.startswith("check:"):
            self._write_check(entry, diff)
        else:  # pragma: no cover - closed set
            raise ImportApplyError(f"Unknown field {name!r}")
        self._count_field(diff)

    # -- groups --------------------------------------------------------------------------

    def _apply_groups(self, row, sel):
        rec = row.record
        if row.status == AMBIGUOUS:
            target = sel.get("target_id")
            if target is not None:
                if target not in {c["id"] for c in row.candidates}:
                    raise ImportApplyError(f"{row.label}: that is not one of the candidates.")
                group = db.session.get(Group, target)
                self.alias[rec.name] = group.group_name
                self._fill_group(group, rec, sel)
                self.c["rows_applied"] += 1
                return True
            if not sel.get("create"):
                self.skipped["needs a choice"] += 1
                return False
            self._new_group(rec)
            return True
        if row.target_id is None:
            self._new_group(rec)
            return True
        self._fill_group(db.session.get(Group, row.target_id), rec, sel, row)
        self.c["rows_applied"] += 1
        return True

    def _new_group(self, rec):
        db.session.add(Group(group_name=rec.name, group_sort_priority=rec.sort_priority,
                             group_icon=rec.icon or None))
        db.session.flush()
        self.c["groups_created"] += 1
        self.c["rows_applied"] += 1

    def _fill_group(self, group, rec, sel, row=None):
        """Fill `group` from `rec`. For a planned row its diffs are used; for an ambiguous pick
        the diffs against the chosen group are computed here."""
        if row is None:
            diffs = []
            if rec.sort_priority is not None and rec.sort_priority != group.group_sort_priority:
                diffs.append(FieldDiff("sort_priority", rec.sort_priority, group.group_sort_priority,
                                       MISSING if group.group_sort_priority is None else DIFFERS))
            _diff(diffs, "icon", rec.icon, group.group_icon, not _norm(group.group_icon))
            row = RowPlan(rid="", section="groups", source_group="groups", label="", fields=diffs)
        for f in _chosen_fields(row, sel, self.mode):
            if f.field == "sort_priority":
                group.group_sort_priority = f.file
            elif f.field == "icon":
                group.group_icon = f.file
            self._count_field(f)

    # -- channels ------------------------------------------------------------------------

    def _apply_channels(self, row, sel):
        rec = row.record
        if row.status == NOT_FOUND:
            if not sel.get("create"):
                self.skipped["not selected"] += 1
                return False
            clean, errors = notify.validate_config(rec.type, rec.config or {})
            if errors:
                raise ImportApplyError(f"Channel '{rec.name}': {errors[0]['message']}")
            enabled = bool(rec.enabled) and not rec.secret_set
            channel = NotificationChannel(type=rec.type, name=rec.name.strip(), enabled=enabled,
                                          config=clean, secret=None)
            db.session.add(channel)
            self.c["channels_created"] += 1
            self.channels_changed = True
            if rec.secret_set:
                self.todo["channels_disabled"].append(rec.name)
            return True
        channel = db.session.get(NotificationChannel, row.target_id)
        fields = _chosen_fields(row, sel, self.mode)
        if not fields:
            self.skipped["nothing to apply"] += 1
            return False
        config = dict(channel.config or {})
        for f in fields:
            if f.field == "enabled":
                channel.enabled = bool(f.file)
            else:
                config[f.field.split(".", 1)[1]] = f.file
            self._count_field(f)
        clean, errors = notify.validate_config(channel.type, config)
        if errors:
            raise ImportApplyError(f"Channel '{channel.name}': {errors[0]['message']}")
        channel.config = clean
        self.channels_changed = True
        self.c["rows_applied"] += 1
        return True

    # -- streams and blocks --------------------------------------------------------------

    def _apply_streams(self, row, sel):
        stream = db.session.get(InventoryStream, row.target_id)
        fields = _chosen_fields(row, sel, self.mode)
        if not fields:
            self.skipped["nothing to apply"] += 1
            return False
        for f in fields:
            setattr(stream, f.field, f.file)
            self._count_field(f)
        self.c["rows_applied"] += 1
        return True

    def _apply_blocks(self, row, sel):
        block = row.record
        stream = db.session.get(InventoryStream, row.ctx["stream_pk"])
        blocked_at = block.blocked_at
        if blocked_at is not None:
            blocked_at = blocked_at.astimezone(timezone.utc).replace(tzinfo=None)
        db.session.add(InventoryBlock(
            stream_id=stream.id, key=block.key, name=(block.name or None), ip=block.ip,
            blocked_at=blocked_at or datetime.utcnow(),
            blocked_by=(block.blocked_by or self.actor or "")[:80] or None))
        db.session.flush()
        self.c["blocks_created"] += 1
        if "soft_delete_entry" in (sel.get("options") or []) and row.ctx.get("entry_id"):
            entry = db.session.get(ServiceEntry, row.ctx["entry_id"])
            streams.soft_delete_entry(entry, block=True, actor=self.actor)
            self.c["entries_soft_deleted"] += 1
        return True

    # -- users ---------------------------------------------------------------------------

    def _apply_users(self, row, sel):
        if row.status != NOT_FOUND:
            self.skipped["nothing to apply"] += 1
            return False
        if not sel.get("create"):
            self.skipped["not selected"] += 1
            return False
        rec = row.record
        db.session.add(User(username=rec.username, email=rec.email, password_hash=UNSET_PASSWORD_HASH,
                            is_admin=bool(rec.is_admin), is_active=bool(rec.is_active)))
        self.c["users_created"] += 1
        self.todo["users_without_password"].append(rec.username)
        return True

    # -- settings ------------------------------------------------------------------------

    def _apply_settings(self, row, sel):
        fields = _chosen_fields(row, sel, self.mode)
        if not fields:
            self.skipped["nothing to apply"] += 1
            return False
        what, key, value = row.record
        if what in ("exposure_layers", "exposure_layers_per_host"):
            layers = settings_store.get_layer_directions()
            hosts = settings_store.get_host_layer_overrides()
            if what == "exposure_layers":
                layers[key] = value
            else:
                hosts.setdefault(key[0], {})[key[1]] = value
            settings_store.save_exposure_settings(layers, hosts)
            self.exposure_changed = True
        elif what == "update_check":
            kwargs = {f.field: f.file for f in fields}
            settings_store.save_update_check_settings(kwargs.get("enabled"), kwargs.get("interval_hours"))
        else:
            values = {f"{key}_{f.field}": f.file for f in fields}
            errors, _ = backups.save_settings(self.app, values)
            if errors:
                raise ImportApplyError(f"Backup settings: {next(iter(errors.values()))}")
            self.backup_changed = True
        for f in fields:
            self._count_field(f)
        self.c["settings_changed"] += 1
        return True

    # -- entries -------------------------------------------------------------------------

    def _apply_entries(self, row, sel):
        rec = row.record
        status = row.status
        if status == NOT_FOUND:
            if not sel.get("create"):
                self.skipped["not selected"] += 1
                return False
            return self._create_entry(rec, row)
        if status == AMBIGUOUS:
            target = sel.get("target_id")
            if target is None:
                self.skipped["needs a choice"] += 1
                return False
            if target not in {c["id"] for c in row.candidates}:
                raise ImportApplyError(f"{row.label}: that is not one of the candidates.")
            fields_all = row.ctx["cand_fields"][target]
            entry = db.session.get(ServiceEntry, target)
            fake = RowPlan(rid=row.rid, section="entries", source_group=row.source_group, label=row.label,
                           fields=fields_all)
            return self._fill_entry(entry, _chosen_fields(fake, sel, self.mode))
        entry = db.session.get(ServiceEntry, row.target_id)
        if status == DELETED:
            if "restore" not in (sel.get("options") or []):
                self.skipped["restore not ticked"] += 1
                return False
            entry.deleted_at = None
            self.c["entries_restored"] += 1
            self._fill_entry(entry, _chosen_fields(row, sel, self.mode), force=True)
            return True
        return self._fill_entry(entry, _chosen_fields(row, sel, self.mode))

    def _fill_entry(self, entry, fields, force=False):
        if not fields:
            if not force:
                self.skipped["nothing to apply"] += 1
            return False
        for f in fields:
            self._write_entry_field(entry, f)
        entry.last_updated = self.now
        self.c["rows_applied"] += 1
        return True

    def _create_entry(self, rec, row):
        ident = rec.identity
        host = _nh(ident.pre_link_host) if rec.kind == "stream" else _nh(ident.host)
        name = ident.container_name
        clash = entry_rules.find_duplicate(host, name)
        if clash is not None and clash.deleted_at is None:
            raise ImportApplyError(f"Cannot import '{name}' as new: an entry with that name already exists.")
        entry = ServiceEntry(host=host, container_name=name, source=SOURCE_MANUAL, is_static=False,
                             last_updated=self.now)
        ensure_url_checks(entry)
        db.session.add(entry)
        db.session.flush()
        diffs, _ = _entry_diffs(rec, entry, self.L, self.D)
        for f in diffs:
            if f.field == "is_static":
                if f.file:
                    self.todo["locks_deferred"].append(f"{host or '-'}/{name}")
                continue
            if f.field == "name" or not f.applicable:
                continue
            self._write_entry_field(entry, f)
        self.c["entries_created"] += 1
        self.c["entries_created_waiting"] += 1
        return True

    # -- finish --------------------------------------------------------------------------

    def _finish(self):
        if self.exposure_changed:
            synthesizer.recompute_all()
        mapped = []
        for m in self.plan.stream_mapping:
            if m["local_id"] is None:
                if not m["error"]:
                    self.todo["streams_not_present"].append(m["file_id"])
            else:
                mapped.append(self.L.streams_by_slug[m["local_id"]].id)
                if m["local_status"] != STREAM_ENABLED:
                    self.todo["streams_to_enable"].append(m["local_id"])
        if mapped:
            self.todo["open_link_offers"] = StreamLinkOffer.query.filter(
                StreamLinkOffer.stream_id.in_(mapped)).count()
        self.todo["generic"] = list(GENERIC_TO_DO)
        self.result.counts = dict(self.c)
        self.result.skipped = dict(self.skipped)
        self.result.still_to_do = self.todo
        if self.todo["locks_deferred"]:
            self.result.notes.append("Entries created as new are not locked; re-run the import after the "
                                     "container registers to apply the lock.")


def apply(doc, stream_map, selection, mode, fingerprint, actor):
    """Apply the selected rows. Takes `routes_api._UPSERT_LOCK` then `streams._LOCK`, re-plans,
    and writes nothing (`ImportStale`) unless the selected rows still match the fingerprint
    the preview showed. One transaction; any error rolls it back (`ImportApplyError`)."""
    import jobs
    import routes_api

    if mode not in MODES:
        raise ImportApplyError(f"mode must be one of: {', '.join(MODES)}.")
    if not fingerprint:
        raise ImportApplyError("A fingerprint from the preview is required.")
    doc, parsed = _unwrap(doc)
    app = current_app._get_current_object()
    selection = selection or {}
    with routes_api._UPSERT_LOCK:
        with streams._LOCK:
            the_plan = plan(parsed if parsed is not None else doc, stream_map)
            if fingerprint_from_digests(the_plan.digests, selection, the_plan.stream_map) != fingerprint:
                db.session.rollback()
                raise ImportStale(the_plan)
            bad = [m for m in the_plan.stream_mapping if m["error"]]
            if bad:
                raise ImportApplyError(f"Fix the stream mapping first: {bad[0]['error']}")
            try:
                applier = _Applier(the_plan, selection, mode, actor, app)
                result = applier.run()
                db.session.commit()
            except ImportApplyError:
                db.session.rollback()
                raise
            except Exception as exc:
                db.session.rollback()
                logger.exception("Import failed")
                raise ImportApplyError("Nothing was changed: the import failed. The server log has the details.") from exc
    if applier.channels_changed:
        notify.request_reload()
    if applier.backup_changed:
        jobs.reschedule_backups(app)
    logger.info("Import applied by %s (%s, mode %s): %s", actor or "?",
                (parsed.filename if parsed is not None else None) or "document", mode,
                json.dumps(result.counts, sort_keys=True))
    return result


# --- staging store -------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def staging_dir():
    return os.path.join(CONFIG_DIR, "import-staging")


def _staging_path(token):
    if not isinstance(token, str) or not _TOKEN_RE.match(token):
        return None
    base = os.path.realpath(staging_dir())
    path = os.path.realpath(os.path.join(base, f"{token}.json"))
    if not path.startswith(base + os.sep):   # belt and braces: the token regex already rules this out
        return None
    return path


def stage(parsed, user_id):
    """Store a parsed upload for the preview and apply pages. Returns the token. The file is
    bound to `user_id` and expires after 60 minutes."""
    os.makedirs(staging_dir(), exist_ok=True)
    prune_expired()
    token = secrets.token_urlsafe(16)
    path = _staging_path(token)
    tmp = path + ".tmp"
    payload = {"token": token, "user_id": user_id, "created": time.time(), "parsed": parsed.to_dict()}
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, path)
    return token


def load(token, user_id, now=None):
    """The `ParsedDoc` staged under `token` for this user, or None (unknown, expired or someone
    else's token). An expired file is deleted."""
    path = _staging_path(token)
    if path is None or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        if (now or time.time()) - float(payload["created"]) > STAGING_TTL_SECONDS:
            discard(token)
            return None
        if payload.get("user_id") != user_id:
            return None
        return ParsedDoc.from_dict(payload["parsed"])
    except (OSError, ValueError, KeyError, ValidationError):
        return None


def load_state(token, user_id):
    """The preview state kept beside a staged upload: `{"stream_map": {...}, "digests": {...},
    "plan_fp": str}`. The digests are those of the plan the operator last saw, so the apply route
    can hash the submitted selection against them (`fingerprint_from_digests`). `{}` for an
    unknown token or one that is not this user's."""
    if load(token, user_id) is None:
        return {}
    try:
        with open(_staging_path(token), encoding="utf-8") as f:
            return dict(json.load(f).get("state") or {})
    except (OSError, ValueError):
        return {}


def save_state(token, user_id, state):
    """Replace the preview state of a staged upload (see `load_state`). A no-op for an unknown
    or foreign token."""
    path = _staging_path(token)
    if load(token, user_id) is None:
        return False
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        payload["state"] = state
        tmp = path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, path)
    except (OSError, ValueError):
        return False
    return True


def discard(token):
    path = _staging_path(token)
    if path is not None:
        try:
            os.remove(path)
        except OSError:
            pass


def prune_expired(now=None):
    """Delete staged files older than the TTL (and stray temp files). Returns how many."""
    directory = staging_dir()
    if not os.path.isdir(directory):
        return 0
    cutoff = (now or time.time()) - STAGING_TTL_SECONDS
    removed = 0
    for name in os.listdir(directory):
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
        except OSError:
            pass
    return removed
