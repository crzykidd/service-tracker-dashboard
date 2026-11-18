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
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func

from extensions import db
from models import (
    NAME_SOURCE_STREAM,
    NAME_SOURCE_UI_EDIT,
    SOURCE_MANUAL,
    SOURCE_STREAM,
    STREAM_DISABLED,
    STREAM_ENABLED,
    STREAM_IGNORED,
    STREAM_PENDING,
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


def plan(stream, items):
    """Decide what applying `items` to `stream` would do. Reads only.

    Loads the stream's entries, blocks and offers and the host-less manual entries
    once each, then diffs in Python (a handful of queries at 5,000 items).
    """
    entries = {e.stream_key: e for e in ServiceEntry.query.filter_by(stream_id=stream.id).all()}
    blocked = {k for (k,) in db.session.query(InventoryBlock.key).filter_by(stream_id=stream.id)}
    offers = {o.key: o for o in StreamLinkOffer.query.filter_by(stream_id=stream.id).all()}
    manual_by_id, manual_by_name = {}, {}
    for e in (ServiceEntry.active()
              .filter(ServiceEntry.host.is_(None), ServiceEntry.source == SOURCE_MANUAL).all()):
        manual_by_id[e.id] = e
        manual_by_name.setdefault((e.container_name or "").casefold(), []).append(e)

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
            candidates = manual_by_name.get(name.casefold(), [])
            if len(candidates) == 1:
                plans.append(ItemPlan(key, name, ACTION_LINK_OFFER, item,
                                      offer_entry_id=candidates[0].id))
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
    for p in the_plan.items:
        if p.action in (ACTION_UPDATED, ACTION_RESTORED):
            for attr, value in p.changes.items():
                setattr(p.entry, attr, value)
            p.entry.last_updated = stamp
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
        entry.last_updated = stamp
    for offer in the_plan.stale_offers:
        db.session.delete(offer)
    stream.last_applied_at = now
    stream.last_counts = dict(the_plan.counts)
    stream.last_error = None


def new_stream_entry(stream, item):
    """A fresh stream entry: no host, no health checks beyond the dormant URL rows."""
    entry = ServiceEntry(
        host=None, container_name=item["name"], source=SOURCE_STREAM,
        stream_id=stream.id, stream_key=item["key"], name_source=NAME_SOURCE_STREAM,
        last_updated=datetime.now(), inventory_missing=False, **_item_values(item),
    )
    ensure_url_checks(entry)
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
                status=STREAM_PENDING, api_key_id=api_key.id, first_seen_at=now, created_at=now)
            db.session.add(stream)
        elif stream.key_type != payload.key_type:
            raise StreamError(409, f"This stream's key_type is '{stream.key_type}'; "
                                   f"a snapshot cannot change it to '{payload.key_type}'.",
                              {"stream_id": slug, "key_type": stream.key_type})
        else:
            stream.producer = payload.producer
            stream.producer_version = payload.producer_version
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


def entry_stats(stream):
    """Entry counts of one stream: total, active, deleted, missing."""
    row = (db.session.query(
        func.count(ServiceEntry.id),
        func.sum(db.case((ServiceEntry.deleted_at.is_(None), 1), else_=0)),
        func.sum(db.case((db.and_(ServiceEntry.deleted_at.is_(None),
                                  ServiceEntry.inventory_missing.is_(True)), 1), else_=0)))
        .filter(ServiceEntry.stream_id == stream.id).one())
    total, active, missing = (int(v or 0) for v in row)
    return {"total": total, "active": active, "deleted": total - active, "missing": missing}


def customised_entries(stream):
    """Active entries the operator changed (renamed, grouped, described, extra
    checks, published to Home Assistant): `[{"id", "name", "reasons"}]`. The
    cleanup dialog lists them by name before anything is removed."""
    out = []
    for entry in ServiceEntry.active().filter_by(stream_id=stream.id).order_by(ServiceEntry.id):
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
    entry.name_source = None


def _cleanup_entries(stream, cleanup):
    """Soft delete or hard delete the stream's entries; returns the counts."""
    counts = {"entries": 0, "kept": 0, "soft_deleted": 0, "purged": 0}
    entries = _stream_entries(stream)
    counts["entries"] = len(entries)
    stamp = datetime.now()
    for entry in entries:
        if cleanup == CLEANUP_PURGE:
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
            stream.snapshot = None
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
                _become_manual(entry)
        counts["offers_removed"], counts["blocks_cleared"] = offers, blocks
        db.session.flush()
        db.session.delete(stream)      # its blocks and offers go with it (ORM cascade)
        db.session.commit()
        return counts


def update(stream, display_name=None, network_include=None, network_exclude=None, sent=()):
    """Change the display name and the network filters. `sent` names the fields
    the caller provided; an empty list or null clears a filter. Returns the changes
    as `{field: [old, new]}`. Raises `StreamError(400)` on a bad value."""
    changes = {}
    with _LOCK:
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
    """A manual entry joins the stream. It keeps its id, history, checks and
    `ha_publish`. Its name is the operator's, so snapshots no longer write it."""
    entry.source = SOURCE_STREAM
    entry.stream_id = stream.id
    entry.stream_key = item["key"]
    entry.name_source = NAME_SOURCE_UI_EDIT
    entry.inventory_missing = False
    for attr, value in _item_values(item).items():
        setattr(entry, attr, value)
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
        if entry.deleted_at is not None or entry.source != SOURCE_MANUAL or entry.host is not None:
            raise StreamError(409, "Only an active manual entry with no host can be linked.",
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
