"""Inventory streams: apply engine and lifecycle (v0.10.0, PRD 18.4-18.7).

A sidecar PUTs a full snapshot of some inventory (DHCP reservations, a Zigbee
bridge, ...) to `/api/v1/streams/<stream_id>/snapshot`. STD keeps the latest
snapshot on the `inventory_stream` row and, for an `enabled` stream, applies it
to `service_entry` rows with `source = 'stream'`.

Layout of this module:

- ingest helpers: `normalize_mac`, `normalize_items` (value rules the pydantic
  models cannot express), `check_binding`, `receive_snapshot`.
- the apply engine: `plan()` decides what a snapshot does (also behind Preview, no
  writes); `apply()` executes a plan in one transaction under `_LOCK`.
- lifecycle: enable, disable, ignore, delete, update, blocks, link offers, entry
  delete with `block`. Plain functions raising `StreamError`, used by the
  management API and (later) the Settings UI. Each mutating function commits once.

STD makes no outbound calls here, so holding `_LOCK` is cheap. Everything that
writes stream state takes the lock; it is re-entrant because enable and the link
functions call `apply` while holding it.
"""

import ipaddress
import logging
import math
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import func

import entry_rules
from check_form import new_service_check, validate_service_check
from extensions import db
from models import (
    CHECK_KIND_SERVICE,
    CHECK_TYPE_DNS,
    CHECK_TYPE_HTTP,
    CHECK_TYPE_PING,
    CHECK_TYPE_TCP,
    NAME_SOURCE_STREAM,
    NAME_SOURCE_UI_EDIT,
    SOURCE_MANUAL,
    SOURCE_STREAM,
    STREAM_DISABLED,
    STREAM_ENABLED,
    STREAM_IGNORED,
    STREAM_PENDING,
    HealthCheck,
    InventoryBlock,
    InventoryStream,
    ServiceEntry,
    StreamLinkOffer,
    ensure_url_checks,
    hard_delete_entry,
)

logger = logging.getLogger(__name__)

STREAM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
KEY_TYPE_RE = re.compile(r"^[a-z0-9_]{1,16}$")
ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
MAX_ITEMS = 5000
MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_ATTRIBUTES = 32
MAX_ATTRIBUTE_VALUE = 256
MAX_FILTER_ENTRIES = 64
KEY_TYPE_MAC = "mac"

# Observability (PRD 18.9).
DEFAULT_INTERVAL_SECONDS = 15 * 60       # when neither the operator nor the producer says
MIN_INTERVAL_SECONDS = 60
MAX_INTERVAL_SECONDS = 86400
STALE_GRACE_FACTOR = 2                   # stale after 2 x the expected interval without a snapshot
MAX_EXPIRY_DAYS = 3650
INTERVAL_OPERATOR, INTERVAL_PRODUCER, INTERVAL_DEFAULT = "operator", "producer", "default"

CLEANUP_KEEP = "keep"
CLEANUP_SOFT_DELETE = "soft_delete"
CLEANUP_PURGE = "purge"
CLEANUP_CHOICES = (CLEANUP_KEEP, CLEANUP_SOFT_DELETE, CLEANUP_PURGE)

# The keys of the `counts` object in the snapshot response and `last_counts`.
COUNT_KEYS = ("created", "updated", "unchanged", "restored", "missing", "blocked",
              "link_offers", "filtered")

ACTION_CREATED = "created"
ACTION_UPDATED = "updated"
ACTION_UNCHANGED = "unchanged"
ACTION_RESTORED = "restored"
ACTION_BLOCKED = "blocked"
ACTION_LINK_OFFER = "link_offer"
ACTION_FILTERED = "filtered"
_ACTION_COUNT = {ACTION_LINK_OFFER: "link_offers"}

_LOCK = threading.RLock()


class StreamError(Exception):
    """A lifecycle rule was broken; routes answer with `json_error(status, message)`."""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


# --- value rules (shared by the ingest route and the tests) ------------------------

_MAC_COLON_DASH = re.compile(r"[0-9a-f]{2}([:-])[0-9a-f]{2}(\1[0-9a-f]{2}){4}")
_MAC_DOTTED = re.compile(r"[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}")
_MAC_BARE = re.compile(r"[0-9a-f]{12}")


def normalize_mac(value):
    """Lower-case colon form of a MAC, or None when `value` is not one.

    Accepts `aa:bb:cc:dd:ee:ff`, `AA-BB-CC-DD-EE-FF`, `aabb.ccdd.eeff` and
    `aabbccddeeff` (any case, surrounding whitespace ignored).
    """
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if _MAC_COLON_DASH.fullmatch(text):
        digits = text.replace(":", "").replace("-", "")
    elif _MAC_DOTTED.fullmatch(text):
        digits = text.replace(".", "")
    elif _MAC_BARE.fullmatch(text):
        digits = text
    else:
        return None
    return ":".join(digits[i:i + 2] for i in range(0, 12, 2))


def normalize_ip(value):
    """Canonical text of an IPv4/IPv6 address, or None when it isn't one."""
    try:
        return str(ipaddress.ip_address(str(value).strip()))
    except ValueError:
        return None


def check_attributes(attributes):
    """Error text for an `attributes` object that breaks the contract, else None.
    Values are string (<= 256 chars), number, boolean or null; never interpreted."""
    if len(attributes) > MAX_ATTRIBUTES:
        return f"at most {MAX_ATTRIBUTES} attributes are allowed"
    for name, value in attributes.items():
        if not ATTRIBUTE_KEY_RE.fullmatch(name):
            return f"attribute name {name!r} must match ^[A-Za-z0-9_.-]{{1,64}}$"
        if isinstance(value, str) and len(value) > MAX_ATTRIBUTE_VALUE:
            return f"attribute {name!r} is longer than {MAX_ATTRIBUTE_VALUE} characters"
        if isinstance(value, float) and not math.isfinite(value):
            return f"attribute {name!r} must be a finite number"
    return None


def normalize_items(key_type, items):
    """`(items, errors)`: each pydantic-validated item as a stored dict, with MACs
    normalised, plus `{"field", "message"}` problems the models cannot express:
    a `mac`-typed key that isn't a MAC, and duplicate keys.

    Stored item keys: key, name, ip, mac, network, attributes. With
    `key_type: mac` and no `mac`, the (normalised) key is copied into `mac`.
    """
    out, errors, seen = [], [], {}
    for i, item in enumerate(items):
        key = item.key
        if key_type == KEY_TYPE_MAC:
            key = normalize_mac(key)
            if key is None:
                errors.append({"field": f"items.{i}.key",
                               "message": "key must be a MAC address when key_type is 'mac'"})
                continue
        if key in seen:
            errors.append({"field": f"items.{i}.key",
                           "message": f"duplicate key (same as items.{seen[key]}.key)"})
            continue
        seen[key] = i
        mac = item.mac
        if mac is None and key_type == KEY_TYPE_MAC:
            mac = key
        out.append({"key": key, "name": item.name, "ip": item.ip, "mac": mac,
                    "network": item.network, "attributes": item.attributes})
    return out, errors


# --- authorisation -----------------------------------------------------------------


def check_binding(stream, api_key):
    """Raise 403 when `api_key` may not use `stream`: an `ingest` key is bound to
    the key that created the stream; a `write` key may use any stream."""
    if api_key.scope == "write":
        return
    if stream.api_key_id is None or stream.api_key_id != api_key.id:
        raise StreamError(403, "This stream belongs to a different API key.",
                          {"stream_id": stream.stream_id})


# --- the apply engine --------------------------------------------------------------


def _network_ok(stream, network):
    """Include list (when set) must contain the item's network; the exclude list must not."""
    net = (network or "").casefold()
    include = [n.casefold() for n in (stream.network_include or [])]
    exclude = [n.casefold() for n in (stream.network_exclude or [])]
    if include and net not in include:
        return False
    return net not in exclude


@dataclass
class ItemPlan:
    key: str
    name: str
    action: str
    item: dict
    entry: object = None            # the stream's existing entry (known key)
    offer: object = None            # an existing open offer (waiting)
    offer_entry_id: int | None = None   # the manual entry a new offer points at
    changes: dict = field(default_factory=dict)


@dataclass
class Plan:
    items: list
    counts: dict
    newly_missing: list             # entries to flag now
    stale_offers: list              # offers whose manual entry is gone: dropped
    missing: list                   # every non-deleted entry absent from the snapshot

    def actions(self):
        """Per-item rows for Preview."""
        return [{"key": p.key, "name": p.name, "action": p.action, "ip": p.item.get("ip"),
                 "network": p.item.get("network"),
                 "entry_id": (p.entry.id if p.entry is not None
                              else p.offer_entry_id if p.offer_entry_id is not None
                              else p.offer.entry_id if p.offer is not None else None)}
                for p in self.items]


def _empty_counts():
    return {k: 0 for k in COUNT_KEYS}


def _item_values(item):
    return {"ip": item.get("ip"), "mac": item.get("mac"), "network": item.get("network"),
            "attributes": item.get("attributes")}


def _first_label(text):
    return text.split(".", 1)[0]


def _name_tokens(name):
    """Casefolded forms an item name is matched by: the whole name and its first
    DNS label (`z-wave-house.crzynet.me` -> `z-wave-house`)."""
    text = (name or "").strip().casefold()
    return {t for t in (text, _first_label(text)) if t}


def _entry_tokens(entry):
    """Casefolded forms a manual entry is matched by: its name, its host and the
    first label of its host (operators put a device's hostname in Host)."""
    tokens = set()
    for text in (entry.container_name, entry.host):
        text = (text or "").strip().casefold()
        if text:
            tokens.add(text)
    host = (entry.host or "").strip().casefold()
    if host:
        tokens.add(_first_label(host))
    return tokens


def plan(stream, items):
    """Decide what applying `items` to `stream` would do. Reads only.

    Loads the stream's entries, blocks and offers and the active manual entries
    once each, then diffs in Python (a handful of queries at 5,000 items).
    """
    entries = {e.stream_key: e for e in ServiceEntry.query.filter_by(stream_id=stream.id).all()}
    blocked = {k for (k,) in db.session.query(InventoryBlock.key).filter_by(stream_id=stream.id)}
    offers = {o.key: o for o in StreamLinkOffer.query.filter_by(stream_id=stream.id).all()}
    manual_by_id, manual_by_token = {}, {}
    for e in ServiceEntry.active().filter(ServiceEntry.source == SOURCE_MANUAL).all():
        manual_by_id[e.id] = e
        for token in _entry_tokens(e):
            manual_by_token.setdefault(token, []).append(e)
    # A manual entry already offered to one key is not offered to a second one.
    claimed = {o.entry_id for o in offers.values()}

    counts = _empty_counts()
    plans, stale = [], []
    for item in items:
        key, name = item["key"], item["name"]
        if not _network_ok(stream, item.get("network")):
            plans.append(ItemPlan(key, name, ACTION_FILTERED, item))
        elif key in blocked:
            plans.append(ItemPlan(key, name, ACTION_BLOCKED, item))
        elif key in entries:
            entry = entries[key]
            changes = {k: v for k, v in _item_values(item).items() if getattr(entry, k) != v}
            if entry.name_source != NAME_SOURCE_UI_EDIT and entry.container_name != name:
                changes["container_name"] = name
            if entry.inventory_missing:
                changes["inventory_missing"] = False
                changes["inventory_missing_since"] = None
            if entry.deleted_at is not None:
                action = ACTION_RESTORED
                changes["deleted_at"] = None
            else:
                action = ACTION_UPDATED if changes else ACTION_UNCHANGED
            plans.append(ItemPlan(key, name, action, item, entry=entry, changes=changes))
        else:
            offer = offers.get(key)
            if offer is not None and offer.entry_id not in manual_by_id:
                stale.append(offer)       # its manual entry was deleted, locked in or converted
                offer = None
            if offer is not None:
                plans.append(ItemPlan(key, name, ACTION_LINK_OFFER, item, offer=offer))
                continue
            candidates = {}
            for token in _name_tokens(name):
                for e in manual_by_token.get(token, ()):
                    if e.id not in claimed:
                        candidates[e.id] = e
            if len(candidates) == 1:
                (entry_id,) = candidates
                claimed.add(entry_id)
                plans.append(ItemPlan(key, name, ACTION_LINK_OFFER, item, offer_entry_id=entry_id))
            else:
                plans.append(ItemPlan(key, name, ACTION_CREATED, item))
    for p in plans:
        counts[_ACTION_COUNT.get(p.action, p.action)] += 1

    present = {item["key"] for item in items}
    missing = [e for k, e in entries.items() if k not in present and e.deleted_at is None]
    counts["missing"] = len(missing)
    newly = [e for e in missing if not e.inventory_missing]
    return Plan(plans, counts, newly, stale, missing)


def _execute(stream, the_plan, now):
    """Write a plan. Caller holds the lock and commits."""
    stamp = datetime.now()
    moved = []
    for p in the_plan.items:
        if p.action in (ACTION_UPDATED, ACTION_RESTORED):
            old_ip = p.entry.ip
            for attr, value in p.changes.items():
                setattr(p.entry, attr, value)
            p.entry.last_updated = stamp
            if "ip" in p.changes and old_ip:
                moved.append((p.entry, old_ip, p.entry.ip))
        elif p.action == ACTION_CREATED:
            db.session.add(new_stream_entry(stream, p.item))
        elif p.action == ACTION_LINK_OFFER:
            if p.offer is not None:
                if p.offer.item != p.item:
                    p.offer.item = p.item
            else:
                db.session.add(StreamLinkOffer(stream_id=stream.id, key=p.key,
                                               entry_id=p.offer_entry_id, item=p.item,
                                               created_at=now))
    for entry in the_plan.newly_missing:
        entry.inventory_missing = True
        entry.inventory_missing_since = now
        entry.last_updated = stamp
    for offer in the_plan.stale_offers:
        db.session.delete(offer)
    follow_ips(moved)
    stream.last_applied_at = now
    stream.last_counts = dict(the_plan.counts)
    stream.last_error = None


def new_stream_entry(stream, item):
    """A fresh stream entry: no host; the dormant URL rows plus the stream's default
    checks (ping / TCP on its IP) when it has any."""
    entry = ServiceEntry(
        host=None, container_name=item["name"], source=SOURCE_STREAM,
        stream_id=stream.id, stream_key=item["key"], name_source=NAME_SOURCE_STREAM,
        last_updated=datetime.now(), inventory_missing=False, **_item_values(item),
    )
    ensure_url_checks(entry)
    add_default_checks(stream, entry)
    return entry


def _apply_locked(stream, items):
    """Plan and execute without committing. Returns the counts."""
    the_plan = plan(stream, items)
    _execute(stream, the_plan, datetime.utcnow())
    return dict(the_plan.counts)


def apply(stream, items):
    """Apply `items` to an enabled `stream` in one transaction and return the
    counts. On failure the transaction is rolled back and `last_error` recorded."""
    with _LOCK:
        try:
            counts = _apply_locked(stream, items)
            db.session.commit()
            return counts
        except Exception as exc:
            _record_failure(stream.id, exc)
            raise


def _record_failure(stream_pk, exc):
    db.session.rollback()
    logger.exception("Applying a snapshot failed for stream %s", stream_pk)
    stream = db.session.get(InventoryStream, stream_pk)
    if stream is not None:
        stream.last_error = f"{type(exc).__name__}: {exc}"[:255]
        db.session.commit()


# --- default checks ---------------------------------------------------------------

DEFAULT_CHECK_KEYS = ("ping", "tcp_port")


def clean_default_checks(value):
    """Validate and normalise a `default_checks` value: `{"ping": bool, "tcp_port":
    int | None}` (missing keys default off). Returns the stored dict, or None when
    nothing is enabled (so "off" is stored as NULL). Raises `StreamError(400)`."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise StreamError(400, "default_checks must be an object like {\"ping\": true, \"tcp_port\": 22}.")
    unknown = sorted(set(value) - set(DEFAULT_CHECK_KEYS))
    if unknown:
        raise StreamError(400, f"default_checks has unknown keys: {', '.join(unknown)}.")
    ping = value.get("ping", False)
    if ping is None:
        ping = False
    if not isinstance(ping, bool):
        raise StreamError(400, "default_checks.ping must be true or false.")
    port = value.get("tcp_port")
    if port is not None:
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise StreamError(400, "default_checks.tcp_port must be a port from 1 to 65535, or null.")
    if not ping and port is None:
        return None
    return {"ping": ping, "tcp_port": port}


def default_checks_of(stream):
    """The stream's default checks as `{"ping": bool, "tcp_port": int | None}`."""
    cfg = stream.default_checks or {}
    return {"ping": bool(cfg.get("ping")), "tcp_port": cfg.get("tcp_port")}


def _has_service_check(entry, check_type):
    return any(c.check_type == check_type for c in entry.service_checks)


def add_default_checks(stream, entry):
    """Add the stream's missing default checks to `entry` (enabled service checks on
    its IP). A kind the entry already has a check of is skipped, so customised checks
    are never touched or duplicated. No IP: nothing. Caller commits. Returns how
    many checks were added."""
    cfg = default_checks_of(stream)
    ip = (entry.ip or "").strip()
    if not ip or not (cfg["ping"] or cfg["tcp_port"]):
        return 0
    specs = []
    if cfg["ping"] and not _has_service_check(entry, CHECK_TYPE_PING):
        specs.append({"name": "Ping", "check_type": CHECK_TYPE_PING, "target": ip})
    if cfg["tcp_port"] and not _has_service_check(entry, CHECK_TYPE_TCP):
        host = f"[{ip}]" if ":" in ip else ip
        specs.append({"name": f"TCP {cfg['tcp_port']}", "check_type": CHECK_TYPE_TCP,
                      "target": f"{host}:{cfg['tcp_port']}"})
    added = 0
    for spec in specs:
        values, errors = validate_service_check({**spec, "enabled": True})
        if errors:
            logger.warning("Default check %s skipped for %s: %s", spec["name"], entry.container_name, errors)
            continue
        entry.checks.append(new_service_check(values))
        added += 1
    return added


def apply_default_checks(stream):
    """Add the missing default checks to every active entry of `stream`. Returns
    `{"entries": n, "checks_added": n, "entries_changed": n}`."""
    with _LOCK:
        result = {"entries": 0, "checks_added": 0, "entries_changed": 0}
        for entry in ServiceEntry.active().filter_by(stream_id=stream.id).all():
            result["entries"] += 1
            added = add_default_checks(stream, entry)
            if added:
                result["checks_added"] += added
                result["entries_changed"] += 1
        db.session.commit()
        return result


# --- ingest ------------------------------------------------------------------------

STORED_MESSAGE = ("Snapshot stored, not applied. Enable the stream in Settings → Streams "
                  "to import its {n} items.")


def find_stream(slug):
    return InventoryStream.query.filter_by(stream_id=slug).first()


def receive_snapshot(slug, payload, items, api_key):
    """Store (and for an enabled stream apply) a validated snapshot.

    `payload` is the pydantic model, `items` the result of `normalize_items`,
    `api_key` the calling ApiKey. Returns `(http_status, body)`: 200 applied, 202
    stored or ignored. Raises `StreamError` 403 (another key's stream) or 409
    (`key_type` differs from the stream's).
    """
    with _LOCK:
        stream = find_stream(slug)
        now = datetime.utcnow()
        if stream is not None:
            check_binding(stream, api_key)      # re-checked: the stream may have appeared meanwhile
        if stream is not None and stream.status == STREAM_IGNORED:
            return 202, {"stream_id": slug, "stream_status": STREAM_IGNORED, "applied": False}
        if stream is None:
            stream = InventoryStream(
                stream_id=slug, display_name=payload.display_name, producer=payload.producer,
                producer_version=payload.producer_version, key_type=payload.key_type,
                producer_interval_seconds=payload.snapshot_interval_seconds,
                status=STREAM_PENDING, api_key_id=api_key.id, first_seen_at=now, created_at=now)
            db.session.add(stream)
        elif stream.key_type != payload.key_type:
            raise StreamError(409, f"This stream's key_type is '{stream.key_type}'; "
                                   f"a snapshot cannot change it to '{payload.key_type}'.",
                              {"stream_id": slug, "key_type": stream.key_type})
        else:
            stream.producer = payload.producer
            stream.producer_version = payload.producer_version
            # Observation: a producer that stops advertising its interval clears it.
            stream.producer_interval_seconds = payload.snapshot_interval_seconds
        stream.snapshot = items
        stream.last_snapshot_at = now
        stream.last_item_count = len(items)
        if stream.status != STREAM_ENABLED:
            db.session.commit()
            return 202, {"stream_id": slug, "stream_status": stream.status, "applied": False,
                         "item_count": len(items), "message": STORED_MESSAGE.format(n=len(items))}
        try:
            counts = _apply_locked(stream, items)
            db.session.commit()
        except Exception as exc:
            _record_failure(stream.id, exc)
            raise
        return 200, {"stream_id": slug, "stream_status": STREAM_ENABLED, "applied": True,
                     "item_count": len(items), "counts": counts}


def status_body(stream):
    return {"stream_id": stream.stream_id, "stream_status": stream.status,
            "display_name": stream.display_name,
            "last_snapshot_at": _iso(stream.last_snapshot_at),
            "last_applied_at": _iso(stream.last_applied_at),
            "last_item_count": stream.last_item_count, "last_counts": stream.last_counts}


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


# --- rejected snapshots -------------------------------------------------------------


def rejection_text(status, message):
    """`"<status>: <first error>"`, at most 255 characters."""
    return f"{status}: {message}"[:255]


def record_rejection(stream_pk, status, message, now=None):
    """Remember that a snapshot PUT to an existing stream (by a key bound to it) was
    refused. Not audited, like every snapshot PUT. Rolls back whatever the request
    left in the session first, then commits only these two columns."""
    with _LOCK:
        db.session.rollback()
        stream = db.session.get(InventoryStream, stream_pk)
        if stream is None:
            return
        stream.last_rejected_at = now or datetime.utcnow()
        stream.last_rejection = rejection_text(status, message)
        db.session.commit()
        logger.warning("Snapshot for stream %s rejected: %s", stream.stream_id, stream.last_rejection)


# --- staleness (computed on read) ---------------------------------------------------


def effective_interval(stream):
    """`(seconds, source)`: the operator's expected interval, else the producer's
    advertised one, else 15 minutes. `source` is operator | producer | default."""
    if stream.expected_interval_seconds:
        return int(stream.expected_interval_seconds), INTERVAL_OPERATOR
    if stream.producer_interval_seconds:
        return int(stream.producer_interval_seconds), INTERVAL_PRODUCER
    return DEFAULT_INTERVAL_SECONDS, INTERVAL_DEFAULT


def stale_after_seconds(stream):
    return effective_interval(stream)[0] * STALE_GRACE_FACTOR


def is_stale(stream, now=None):
    """An enabled stream with no snapshot for more than `STALE_GRACE_FACTOR` x its
    expected interval (measured from the last snapshot, or from when it was first
    seen if it never sent one since). Pending, disabled and ignored streams are never
    stale: nobody asked STD to rely on them."""
    if stream.status != STREAM_ENABLED:
        return False
    ref = stream.last_snapshot_at or stream.first_seen_at
    if ref is None:
        return False
    now = now or datetime.utcnow()
    return (now - ref).total_seconds() > stale_after_seconds(stream)


def is_rejecting(stream):
    """The latest snapshot attempt was refused (newer than the last accepted one)."""
    if stream.last_rejected_at is None:
        return False
    return stream.last_snapshot_at is None or stream.last_rejected_at > stream.last_snapshot_at


def _minutes(seconds):
    minutes = max(1, round(seconds / 60))
    return f"{minutes} min" if minutes < 120 else f"{round(minutes / 60)} h"


def stream_health(stream, now=None):
    """The observability facts of one stream, for the API, the UI and MQTT."""
    now = now or datetime.utcnow()
    interval, source = effective_interval(stream)
    stale = is_stale(stream, now)
    ref = stream.last_snapshot_at or stream.first_seen_at
    age = int((now - ref).total_seconds()) if ref is not None else None
    message = None
    if stale:
        what = (f"No snapshot for {_minutes(age)}" if stream.last_snapshot_at is not None
                else f"No snapshot since it was first seen {_minutes(age)} ago")
        message = f"{what} (expected every {_minutes(interval)})"
        if is_rejecting(stream):
            message += f"; last snapshot rejected: {stream.last_rejection}"
    return {"stale": stale, "effective_interval_seconds": interval, "interval_source": source,
            "stale_after_seconds": interval * STALE_GRACE_FACTOR,
            "snapshot_age_seconds": age, "rejecting": is_rejecting(stream), "message": message,
            "stale_since": (_iso(ref + timedelta(seconds=interval * STALE_GRACE_FACTOR))
                            if stale else None)}


def stale_streams(now=None):
    """Enabled streams that are stale now (one query)."""
    now = now or datetime.utcnow()
    return [s for s in InventoryStream.query.filter_by(status=STREAM_ENABLED)
            .order_by(InventoryStream.id).all() if is_stale(s, now)]


_STALE_WATCH = {"known": None, "next": 0.0}
STALE_WATCH_SECONDS = 30


def watch_staleness(now=None, force=False):
    """Called by the health scheduler tick (no thread of its own), at most every 30 s.
    Logs each stale/fresh transition once and asks the notifier for a sync so the
    `stale` field on `<base>/stream/<id>` (and the HA problem sensor) follow time,
    not only commits. Returns the set of stale stream ids."""
    mono = time.monotonic()
    if not force and mono < _STALE_WATCH["next"]:
        return _STALE_WATCH["known"]
    _STALE_WATCH["next"] = mono + STALE_WATCH_SECONDS
    current = {s.stream_id for s in stale_streams(now)}
    known = _STALE_WATCH["known"]
    if known is None:
        for slug in sorted(current):
            logger.warning("Inventory stream %s is stale (no snapshot within the expected interval).", slug)
        changed = bool(current)
    else:
        for slug in sorted(current - known):
            logger.warning("Inventory stream %s is stale (no snapshot within the expected interval).", slug)
        for slug in sorted(known - current):
            logger.info("Inventory stream %s is receiving snapshots again (or no longer enabled).", slug)
        changed = current != known
    _STALE_WATCH["known"] = current
    if changed:
        import notify
        notify.request_sync()
    return current


def reset_stale_watch():
    _STALE_WATCH.update(known=None, next=0.0)


# --- IP follow (PRD 18.9: no templated targets) --------------------------------------


def _same_ip(a, b):
    na, nb = normalize_ip(a) if a else None, normalize_ip(b) if b else None
    return na is not None and na == nb


def _host_port(text):
    """`(host, port | None)` of `host`, `host:port` or `[v6]:port` (a bare v6 too)."""
    text = (text or "").strip()
    if text.startswith("["):
        host, _, rest = text[1:].partition("]")
        return host, (rest[1:] if rest.startswith(":") else None)
    if text.count(":") == 1:
        host, _, port = text.partition(":")
        return host, port
    return text, None


def _join_host_port(host, port):
    shown = f"[{host}]" if ":" in host else host
    return f"{shown}:{port}" if port else host


def retarget(check_type, target, old_ip, new_ip):
    """The check target with `old_ip` replaced by `new_ip`, or None when the target
    does not point at `old_ip`. Ping: the target; TCP and DNS: the host of
    `host[:port]`; HTTP: the URL's host (port, path and userinfo kept)."""
    if not target or not old_ip or not new_ip:
        return None
    if check_type == CHECK_TYPE_PING:
        return new_ip if _same_ip(target, old_ip) else None
    if check_type in (CHECK_TYPE_TCP, CHECK_TYPE_DNS):
        host, port = _host_port(target)
        if not _same_ip(host, old_ip):
            return None
        if port is None and ":" in new_ip and check_type == CHECK_TYPE_DNS:
            return new_ip
        return _join_host_port(new_ip, port)
    if check_type == CHECK_TYPE_HTTP:
        try:
            parts = urlsplit(target)
            host, port = parts.hostname, parts.port
        except ValueError:
            return None
        if not host or not _same_ip(host, old_ip):
            return None
        netloc = parts.netloc.rpartition("@")
        userinfo = netloc[0] + "@" if netloc[1] else ""
        shown = f"[{new_ip}]" if ":" in new_ip else new_ip
        return urlunsplit(parts._replace(netloc=f"{userinfo}{shown}{f':{port}' if port else ''}"))
    return None


def follow_ips(changes):
    """The producer changed some entries' IPs (`[(entry, old_ip, new_ip)]`): every
    service check whose target points at the old IP is moved to the new one (and
    asked to run at the next tick), so no check keeps probing the old host. One query
    for all their service checks. With no new IP nothing can be followed; that is
    logged per check. Returns the ids of the checks retargeted. Caller commits."""
    changes = [(e, old, new) for e, old, new in changes if old and old != new and e.id is not None]
    if not changes:
        return []
    by_entry = {}
    for check in HealthCheck.query.filter(
            HealthCheck.service_entry_id.in_([e.id for e, _o, _n in changes]),
            HealthCheck.kind == CHECK_KIND_SERVICE):
        by_entry.setdefault(check.service_entry_id, []).append(check)
    moved = []
    for entry, old_ip, new_ip in changes:
        for check in by_entry.get(entry.id, ()):
            if not new_ip:
                if retarget(check.check_type, check.target, old_ip, "0.0.0.0") is not None:
                    logger.warning("Entry %s lost its IP (%s); check %r still targets %s.",
                                   entry.container_name, old_ip, check.name, check.target)
                continue
            target = retarget(check.check_type, check.target, old_ip, new_ip)
            if target is None or target == check.target:
                continue
            logger.info("Entry %s moved from %s to %s: check %r now targets %s (was %s).",
                        entry.container_name, old_ip, new_ip, check.name, target, check.target)
            check.target = target[:255]
            moved.append(check.id)
    if moved:
        import jobs
        jobs.request_run(moved)
    return moved


# --- missing entries: auto soft-delete ---------------------------------------------

_TCP_DEFAULT_NAME = re.compile(r"^TCP (\d{1,5})$")


def _is_default_check(entry, check):
    """True for a service check exactly as `add_default_checks` makes it (Ping on the
    entry's IP, `TCP <port>` on ip:port), never edited since."""
    ip = (entry.ip or "").strip()
    if (not ip or check.kind != CHECK_KIND_SERVICE or not check.enabled or check.interval_seconds
            or check.timeout_seconds or check.cert_min_days or check.ha_exclude):
        return False
    if check.check_type == CHECK_TYPE_PING:
        return check.name == "Ping" and check.target == ip
    if check.check_type == CHECK_TYPE_TCP:
        m = _TCP_DEFAULT_NAME.match(check.name or "")
        return bool(m) and check.target == _join_host_port(ip, m.group(1))
    return False


def human_edits(entry):
    """Why an entry counts as edited by a human and is never auto soft-deleted: linked
    (a manual entry that joined the stream), renamed, locked, group, description,
    icon, URLs, sort priority, widget, Home Assistant, or any service check that is
    not an untouched default check (added, edited or disabled). Empty = not edited."""
    reasons = []
    for flag, reason in ((entry.stream_linked, "linked"),
                         (entry.name_source == NAME_SOURCE_UI_EDIT, "renamed"),
                         (entry.is_static, "locked"), (entry.group_id is not None, "group"),
                         (entry.description, "description"), (entry.image_icon, "icon"),
                         (entry.internalurl or entry.externalurl, "urls"),
                         (entry.sort_priority is not None, "sort_priority"),
                         (entry.widget_id is not None, "widget"), (entry.ha_publish, "home_assistant")):
        if flag:
            reasons.append(reason)
    if any(c.kind == CHECK_KIND_SERVICE and not _is_default_check(entry, c) for c in entry.checks):
        reasons.append("checks")
    return reasons


def expire_missing(now=None):
    """Soft-delete entries of enabled streams with `missing_expiry_days` set that have
    been missing longer than that, unless a human edited them (`human_edits`). Run by
    the daily soft-delete purge job. The item coming back restores the entry by key
    (the normal apply path). Returns `{"soft_deleted": n, "kept": n}`."""
    now = now or datetime.utcnow()
    result = {"soft_deleted": 0, "kept": 0}
    with _LOCK:
        rows = InventoryStream.query.filter(InventoryStream.status == STREAM_ENABLED,
                                            InventoryStream.missing_expiry_days.isnot(None)).all()
        stamp = datetime.now()
        for stream in rows:
            cutoff = now - timedelta(days=stream.missing_expiry_days)
            for entry in (ServiceEntry.active().filter(
                    ServiceEntry.stream_id == stream.id, ServiceEntry.inventory_missing.is_(True),
                    ServiceEntry.inventory_missing_since.isnot(None),
                    ServiceEntry.inventory_missing_since <= cutoff).order_by(ServiceEntry.id).all()):
                reasons = human_edits(entry)
                if reasons:
                    result["kept"] += 1
                    logger.info("Stream %s: %s missing since %s, kept (edited: %s).", stream.stream_id,
                                entry.container_name, _iso(entry.inventory_missing_since), ", ".join(reasons))
                    continue
                entry.deleted_at = stamp
                result["soft_deleted"] += 1
                logger.info("Stream %s: soft-deleted %s (missing since %s, expiry %d days).",
                            stream.stream_id, entry.container_name,
                            _iso(entry.inventory_missing_since), stream.missing_expiry_days)
        db.session.commit()
    return result


# --- reading -----------------------------------------------------------------------


def preview(stream):
    """What applying the stored snapshot would do, with no writes."""
    if stream.snapshot is None:
        raise StreamError(409, "This stream has no stored snapshot.", {"stream_id": stream.stream_id})
    the_plan = plan(stream, stream.snapshot)
    return {"stream_id": stream.stream_id, "stream_status": stream.status,
            "item_count": len(stream.snapshot), "counts": the_plan.counts,
            "items": the_plan.actions(),
            "missing": [{"entry_id": e.id, "key": e.stream_key, "name": e.container_name}
                        for e in the_plan.missing]}


def would_counts(stream):
    """The counts applying the stored snapshot would give (read-only `plan()`), or
    None when the stream has no stored snapshot."""
    if stream.snapshot is None:
        return None
    return plan(stream, stream.snapshot).counts


def entry_stats(stream):
    """Entry counts of one stream: total, active, deleted, missing."""
    row = (db.session.query(
        func.count(ServiceEntry.id),
        func.sum(db.case((ServiceEntry.deleted_at.is_(None), 1), else_=0)),
        func.sum(db.case((db.and_(ServiceEntry.deleted_at.is_(None),
                                  ServiceEntry.inventory_missing.is_(True)), 1), else_=0)))
        .filter(ServiceEntry.stream_id == stream.id).one())
    total, active, missing = (int(v or 0) for v in row)
    linked = (db.session.query(func.count(ServiceEntry.id))
              .filter(ServiceEntry.stream_id == stream.id, ServiceEntry.stream_linked.is_(True),
                      ServiceEntry.deleted_at.is_(None)).scalar())
    return {"total": total, "active": active, "deleted": total - active, "missing": missing,
            "linked": int(linked or 0)}


def customised_entries(stream):
    """Active entries the operator changed (renamed, grouped, described, extra
    checks, published to Home Assistant): `[{"id", "name", "reasons"}]`. The
    cleanup dialog lists them by name before anything is removed. Linked entries
    (`stream_linked`) are left out: cleanup unlinks them, see `linked_entries`."""
    out = []
    for entry in ServiceEntry.active().filter_by(stream_id=stream.id).order_by(ServiceEntry.id):
        if entry.stream_linked:
            continue          # the operator's entry: cleanup unlinks it, nothing is lost
        reasons = []
        if entry.name_source == NAME_SOURCE_UI_EDIT:
            reasons.append("renamed")
        if entry.group_id is not None:
            reasons.append("group")
        if entry.description:
            reasons.append("description")
        if entry.image_icon:
            reasons.append("icon")
        if entry.ha_publish:
            reasons.append("home_assistant")
        if entry.service_checks:
            reasons.append("checks")
        if reasons:
            out.append({"id": entry.id, "name": entry.container_name, "reasons": reasons})
    return out


def linked_entries(stream):
    """Active entries that were manual entries linked to this stream:
    `[{"id", "name", "host"}]` (`host` is what unlinking restores). Cleanup never
    deletes these; it unlinks them."""
    return [{"id": e.id, "name": e.container_name, "host": e.pre_link_host}
            for e in ServiceEntry.active().filter_by(stream_id=stream.id, stream_linked=True)
            .order_by(ServiceEntry.id)]


def unmatched_items(stream):
    """Items of the latest snapshot with no entry yet and not blocked: what a
    manual entry can be linked to by hand."""
    have = {k for (k,) in db.session.query(ServiceEntry.stream_key).filter_by(stream_id=stream.id)}
    blocked = {k for (k,) in db.session.query(InventoryBlock.key).filter_by(stream_id=stream.id)}
    return [i for i in (stream.snapshot or []) if i["key"] not in have and i["key"] not in blocked]


# --- lifecycle ---------------------------------------------------------------------


def _need_status(stream, allowed, verb):
    if stream.status not in allowed:
        raise StreamError(409, f"Cannot {verb} a stream that is {stream.status}.",
                          {"stream_id": stream.stream_id, "stream_status": stream.status})


def enable(stream):
    """pending / disabled / ignored -> enabled, applying the stored snapshot now.
    Returns `{"applied": bool, "counts": dict | None}`."""
    with _LOCK:
        _need_status(stream, (STREAM_PENDING, STREAM_DISABLED, STREAM_IGNORED), "enable")
        stream.status = STREAM_ENABLED
        counts = None
        try:
            if stream.snapshot is not None:
                counts = _apply_locked(stream, stream.snapshot)
            db.session.commit()
        except Exception as exc:
            _record_failure(stream.id, exc)
            raise
        return {"applied": counts is not None, "counts": counts}


def ignore(stream):
    """pending / disabled -> ignored: the stored snapshot is discarded and later
    snapshots are answered 202 and dropped. Entries are left alone."""
    with _LOCK:
        _need_status(stream, (STREAM_PENDING, STREAM_DISABLED), "ignore")
        stream.status = STREAM_IGNORED
        stream.snapshot = None
        db.session.commit()


def _check_cleanup(cleanup):
    if cleanup not in CLEANUP_CHOICES:
        raise StreamError(400, f"cleanup must be one of: {', '.join(CLEANUP_CHOICES)}.")


def _stream_entries(stream):
    return ServiceEntry.query.filter_by(stream_id=stream.id).all()


def _become_manual(entry):
    """Detach an entry from its stream: it stays, as a manual entry, keeping mac and ip."""
    entry.source = SOURCE_MANUAL
    entry.stream_id = None
    entry.stream_key = None
    entry.inventory_missing = False
    entry.inventory_missing_since = None
    entry.name_source = None
    entry.stream_linked = False
    entry.pre_link_host = None


def _unlink_locked(entry, block=False, actor=None):
    """`unlink_entry` without the lock or the commit (the caller holds `_LOCK`).
    Returns `{"host": restored host | None, "host_restored": bool, "host_clash": bool,
    "blocked": bool}`; `host_clash` means the pre-link host was not restored because
    `(host, name)` is taken."""
    stream_pk, key = entry.stream_id, entry.stream_key
    host = entry.pre_link_host
    if host and entry_rules.find_duplicate(host, entry.container_name, exclude_id=entry.id):
        host = None          # (host, name) is taken: stay hostless rather than clash
    wanted = entry.pre_link_host
    blocked = False
    if block and stream_pk is not None and key is not None and not InventoryBlock.query.filter_by(
            stream_id=stream_pk, key=key).first():
        db.session.add(InventoryBlock(
            stream_id=stream_pk, key=key, name=(entry.container_name or "")[:128],
            ip=entry.ip, blocked_at=datetime.utcnow(), blocked_by=(actor or "")[:80] or None))
        blocked = True
    _become_manual(entry)
    entry.host = host
    return {"host": host, "host_restored": bool(wanted) and host == wanted,
            "host_clash": bool(wanted) and host != wanted, "blocked": blocked}


def unlink_entry(entry, block=False, actor=None):
    """A stream entry goes back to being a manual entry, keeping its id, history,
    checks and settings. A linked entry gets its pre-link host back (unless
    `(host, name)` is now taken, then it stays hostless: `host_clash` is true
    and `host` null); a stream-created entry simply becomes manual. With `block`
    the item key joins the stream's block list so no snapshot re-creates or
    re-offers it; without, the next snapshot may offer the link again. Commits."""
    with _LOCK:
        if entry.stream_id is None or entry.source != SOURCE_STREAM:
            raise StreamError(409, "Only a stream entry can be unlinked.", {"entry_id": entry.id})
        result = _unlink_locked(entry, block, actor)
        db.session.commit()
        return result


def _cleanup_entries(stream, cleanup):
    """Soft delete or hard delete the stream's entries; returns the counts. Linked
    entries (manual entries that joined the stream) are never deleted: with
    `soft_delete` and `purge` they are unlinked and counted in `unlinked`."""
    counts = {"entries": 0, "kept": 0, "soft_deleted": 0, "purged": 0, "unlinked": 0}
    entries = _stream_entries(stream)
    counts["entries"] = len(entries)
    stamp = datetime.now()
    for entry in entries:
        if entry.stream_linked and cleanup != CLEANUP_KEEP:
            _unlink_locked(entry)
            counts["unlinked"] += 1
        elif cleanup == CLEANUP_PURGE:
            hard_delete_entry(entry)
            counts["purged"] += 1
        elif cleanup == CLEANUP_SOFT_DELETE:
            if entry.deleted_at is None:
                entry.deleted_at = stamp
                counts["soft_deleted"] += 1
        else:
            counts["kept"] += 1
    return counts


def disable(stream, cleanup=CLEANUP_KEEP, clear_blocks=False):
    """enabled -> disabled, then the cleanup of the stream's entries.

    `keep`: entries stay and are no longer updated. `soft_delete`: every entry is
    soft-deleted (re-enabling restores them by key). `purge`: hard delete through
    `hard_delete_entry`, plus the stored snapshot and link offers; `clear_blocks`
    (purge only) also empties the block list.
    """
    _check_cleanup(cleanup)
    with _LOCK:
        _need_status(stream, (STREAM_ENABLED,), "disable")
        stream.status = STREAM_DISABLED
        offers = StreamLinkOffer.query.filter_by(stream_id=stream.id).count()
        counts = _cleanup_entries(stream, cleanup)
        counts.update({"offers_removed": 0, "blocks_cleared": 0})
        if cleanup == CLEANUP_PURGE:
            StreamLinkOffer.query.filter_by(stream_id=stream.id).delete()
            counts["offers_removed"] = offers
            stream.last_counts = None
            if clear_blocks:
                counts["blocks_cleared"] = InventoryBlock.query.filter_by(stream_id=stream.id).delete()
        db.session.commit()
        return counts


def delete(stream, cleanup=CLEANUP_KEEP):
    """Remove the stream row. With `keep` its entries become manual entries (mac
    and ip kept); `soft_delete` soft-deletes them first, and they too become manual
    (restorable from Settings -> Deleted); `purge` hard-deletes them. The stream's
    blocks and link offers go with it."""
    _check_cleanup(cleanup)
    with _LOCK:
        offers = StreamLinkOffer.query.filter_by(stream_id=stream.id).count()
        blocks = InventoryBlock.query.filter_by(stream_id=stream.id).count()
        counts = _cleanup_entries(stream, cleanup)
        if cleanup != CLEANUP_PURGE:
            for entry in _stream_entries(stream):
                if entry.stream_linked:      # `keep`: the host comes back too
                    _unlink_locked(entry)
                    counts["unlinked"] += 1
                    counts["kept"] -= 1
                else:
                    _become_manual(entry)
        counts["offers_removed"], counts["blocks_cleared"] = offers, blocks
        db.session.flush()
        db.session.delete(stream)      # its blocks and offers go with it (ORM cascade)
        db.session.commit()
        return counts


def update(stream, display_name=None, network_include=None, network_exclude=None, sent=(),
           default_checks=None, expected_interval_seconds=None, missing_expiry_days=None):
    """Change the display name, the network filters, the default checks
    (`default_checks`: `{"ping": bool, "tcp_port": int | None}`, null clears), the
    expected snapshot interval (seconds, 60-86400, null = the producer's or 15 min)
    and the missing-entry expiry (days, 1-3650, null = off). `sent` names the fields
    the caller provided; an empty list or null clears a filter. Returns the changes
    as `{field: [old, new]}`. Raises `StreamError(400)` on a bad value."""
    changes = {}
    with _LOCK:
        for field_name, value, low, high, unit in (
                ("expected_interval_seconds", expected_interval_seconds,
                 MIN_INTERVAL_SECONDS, MAX_INTERVAL_SECONDS, "seconds"),
                ("missing_expiry_days", missing_expiry_days, 1, MAX_EXPIRY_DAYS, "days")):
            if field_name not in sent:
                continue
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                      or not low <= value <= high):
                raise StreamError(400, f"{field_name} must be {low}-{high} {unit}, or null.")
            if value != getattr(stream, field_name):
                changes[field_name] = [getattr(stream, field_name), value]
                setattr(stream, field_name, value)
        if "display_name" in sent:
            name = (display_name or "").strip()
            if not 1 <= len(name) <= 32:
                raise StreamError(400, "display_name must be 1-32 characters.")
            if name != stream.display_name:
                changes["display_name"] = [stream.display_name, name]
                stream.display_name = name
        for field_name, value in (("network_include", network_include),
                                  ("network_exclude", network_exclude)):
            if field_name not in sent:
                continue
            cleaned = _clean_filter(field_name, value)
            if cleaned != getattr(stream, field_name):
                changes[field_name] = [getattr(stream, field_name), cleaned]
                setattr(stream, field_name, cleaned)
        if "default_checks" in sent:
            cleaned = clean_default_checks(default_checks)
            if cleaned != stream.default_checks:
                changes["default_checks"] = [stream.default_checks, cleaned]
                stream.default_checks = cleaned
        db.session.commit()
    return changes


def _clean_filter(name, value):
    if value is None:
        return None
    if len(value) > MAX_FILTER_ENTRIES:
        raise StreamError(400, f"{name} has at most {MAX_FILTER_ENTRIES} entries.")
    cleaned = []
    for raw in value:
        text = raw.strip() if isinstance(raw, str) else ""
        if not 1 <= len(text) <= 64:
            raise StreamError(400, f"{name} entries must be 1-64 characters.")
        if text not in cleaned:
            cleaned.append(text)
    return cleaned or None


# --- blocks ------------------------------------------------------------------------


def soft_delete_entry(entry, block=False, actor=None):
    """Soft-delete an entry; with `block`, also put its stream key on the block
    list so a later snapshot cannot bring it back. The caller commits.
    Returns True when a block row was written."""
    if block and entry.stream_id is None:
        raise StreamError(400, "block only applies to entries that belong to an inventory stream.")
    entry.deleted_at = datetime.now()
    if not block:
        return False
    if InventoryBlock.query.filter_by(stream_id=entry.stream_id, key=entry.stream_key).first():
        return False
    db.session.add(InventoryBlock(
        stream_id=entry.stream_id, key=entry.stream_key, name=(entry.container_name or "")[:128],
        ip=entry.ip, blocked_at=datetime.utcnow(), blocked_by=(actor or "")[:80] or None))
    return True


def unblock(stream, block_id):
    """Remove a block; the next snapshot restores the row or creates a new one.
    Returns the removed block's key."""
    with _LOCK:
        block = db.session.get(InventoryBlock, block_id)
        if block is None or block.stream_id != stream.id:
            raise StreamError(404, f"No block with id {block_id} on this stream.")
        key = block.key
        db.session.delete(block)
        db.session.commit()
        return key


# --- link offers -------------------------------------------------------------------


def _convert(entry, stream, item):
    """A manual entry joins the stream (and is marked `stream_linked`, with its old
    host in `pre_link_host`, so cleanup unlinks rather than deletes it). It keeps its id, history, checks and
    `ha_publish`. Its name is the operator's, so snapshots no longer write it. Its
    host is cleared: stream entries have none (the stream reports the address)."""
    entry.pre_link_host = entry.host
    entry.stream_linked = True
    entry.host = None
    entry.source = SOURCE_STREAM
    entry.stream_id = stream.id
    entry.stream_key = item["key"]
    entry.name_source = NAME_SOURCE_UI_EDIT
    entry.inventory_missing = False
    entry.inventory_missing_since = None
    old_ip = entry.ip
    for attr, value in _item_values(item).items():
        setattr(entry, attr, value)
    if old_ip and old_ip != entry.ip:
        follow_ips([(entry, old_ip, entry.ip)])
    entry.last_updated = datetime.now()
    # Offers on this entry from other items are moot now.
    StreamLinkOffer.query.filter_by(entry_id=entry.id).delete()


def _need_enabled(stream):
    _need_status(stream, (STREAM_ENABLED,), "answer a link offer for")


def _key_in_use(stream, key):
    return ServiceEntry.query.filter_by(stream_id=stream.id, stream_key=key).first()


def get_offer(stream, offer_id):
    offer = db.session.get(StreamLinkOffer, offer_id)
    if offer is None or offer.stream_id != stream.id:
        raise StreamError(404, f"No link offer with id {offer_id} on this stream.")
    return offer


def accept_offer(stream, offer):
    """The manual entry becomes a stream entry. Returns the entry."""
    with _LOCK:
        _need_enabled(stream)
        entry = db.session.get(ServiceEntry, offer.entry_id)
        if entry is None or entry.deleted_at is not None or entry.source != SOURCE_MANUAL:
            raise StreamError(409, "The entry this offer points at is no longer an active manual entry.",
                              {"entry_id": offer.entry_id})
        if _key_in_use(stream, offer.key):
            raise StreamError(409, "An entry for this key already exists.", {"key": offer.key})
        item = offer.item
        db.session.delete(offer)
        db.session.flush()
        _convert(entry, stream, item)
        db.session.commit()
        return entry


def decline_offer(stream, offer):
    """A new stream entry is created from the stored item; the manual entry is
    left alone. Returns the new entry."""
    with _LOCK:
        _need_enabled(stream)
        if _key_in_use(stream, offer.key):
            raise StreamError(409, "An entry for this key already exists.", {"key": offer.key})
        if InventoryBlock.query.filter_by(stream_id=stream.id, key=offer.key).first():
            raise StreamError(409, "This key is blocked; unblock it first.", {"key": offer.key})
        item = offer.item
        db.session.delete(offer)
        entry = new_stream_entry(stream, item)
        db.session.add(entry)
        db.session.commit()
        return entry


def link_entry(stream, entry, key):
    """Link a manual entry to an unmatched item of the stream's latest snapshot."""
    with _LOCK:
        if entry.deleted_at is not None or entry.source != SOURCE_MANUAL:
            raise StreamError(409, "Only an active manual entry can be linked.",
                              {"entry_id": entry.id})
        item = next((i for i in (stream.snapshot or []) if i["key"] == key), None)
        if item is None:
            raise StreamError(404, "That key is not in the stream's latest snapshot.", {"key": key})
        if _key_in_use(stream, key):
            raise StreamError(409, "An entry for this key already exists.", {"key": key})
        if InventoryBlock.query.filter_by(stream_id=stream.id, key=key).first():
            raise StreamError(409, "This key is blocked; unblock it first.", {"key": key})
        StreamLinkOffer.query.filter_by(stream_id=stream.id, key=key).delete()
        db.session.flush()
        _convert(entry, stream, item)
        db.session.commit()
        return entry
