"""Check and roll-up state publishing (PRD 17.3).

Builds the retained MQTT topics from the database and decides what to send:

- `publish_changes()` runs on the health scheduler thread right after a tick's
  writes commit. It builds plain dicts and enqueues them (non-blocking): a
  check event when a check's `ok` changed (the first ever result counts), an
  entry event when the roll-up (`health_state.entry_health`) or the per-state
  check counts changed, and a summary event when any roll-up changed.
- `full_sync()` runs on the publisher thread. It builds the desired topic set
  from the active entries, publishes it retained, and publishes an empty
  retained payload to every previously published topic that is no longer
  desired. That one reconcile covers soft delete, restore, purge, check
  edits and renames, so no delete path needs its own hook.
- `install_listeners()` asks for a sync after any commit that changed what a
  topic carries (entry name, host, group, URLs, source, soft delete, a
  check's config, a group's name).

`PublishState` lives on the `Publisher` (in memory) and is persisted in the
`setting` store, so the cleanup still works after a restart.

Topic suffixes under the channel's `base_topic`:
    entry/<entry_id>/state, entry/<entry_id>/check/<check_id>, summary
"""

import json
import logging
import threading
from datetime import datetime

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, joinedload, selectinload

import health_state
import settings_store
from extensions import db
from models import (
    CHECK_KIND_CONTAINER,
    CHECK_KIND_EXTERNAL,
    CHECK_KIND_INTERNAL,
    Group,
    HealthCheck,
    ServiceEntry,
    check_counts,
)

logger = logging.getLogger(__name__)

KEY_PUBLISH_STATE = "notify_publish_state"
SUMMARY_TOPIC = "summary"

# What changes a topic's payload. Cached `last_*` result columns are left out
# on purpose: every health tick writes those, and a sync per tick is wasteful.
_ENTRY_ATTRS = ("container_name", "host", "group_id", "source", "deleted_at",
                "internalurl", "externalurl", "is_static", "image_tag", "ha_publish")
_CHECK_ATTRS = ("enabled", "kind", "name", "check_type", "target", "ha_exclude")
_GROUP_ATTRS = ("group_name",)


def entry_topic(entry_id):
    return f"entry/{entry_id}/state"


def check_topic(entry_id, check_id):
    return f"entry/{entry_id}/check/{check_id}"


def _iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def _now():
    return datetime.utcnow()


def check_state(check):
    if check.last_ok is None:
        return "unknown"
    return "up" if check.last_ok else "down"


def _target(entry, check):
    if check.kind == CHECK_KIND_INTERNAL:
        return entry.internalurl
    if check.kind == CHECK_KIND_EXTERNAL:
        return entry.externalurl
    return check.target


def counted_checks(entry):
    return [c for c in entry.checks if check_counts(entry, c)]


def check_counts_by_state(entry):
    counts = {"up": 0, "down": 0, "unknown": 0}
    for c in counted_checks(entry):
        counts[check_state(c)] += 1
    return counts


def dashboard_url(entry_id):
    """The entry's page. STD has no configured public base URL, so this is the
    path; a base URL, when one exists, would be prefixed here."""
    return f"/edit/{entry_id}"


def check_payload(entry, check, last_change):
    return {
        "ok": check.last_ok,
        "state": check_state(check),
        "entry_id": entry.id,
        "std_entry_id": entry.id,
        "entry_name": entry.container_name,
        "host": entry.host,
        "group": entry.group.group_name if entry.group is not None else None,
        "source": entry.source,
        "dashboard_url": dashboard_url(entry.id),
        "check_id": check.id,
        "name": check.name or check.kind,
        "kind": check.kind,
        "check_type": "container" if check.kind == CHECK_KIND_CONTAINER else check.check_type,
        "target": _target(entry, check),
        "latency_ms": check.last_latency_ms,
        "status_code": check.last_status_code,
        "message": check.last_message,
        "consecutive_failures": check.consecutive_failures or 0,
        "last_checked_at": _iso(check.last_checked_at),
        "last_change": _iso(last_change),
    }


def entry_payload(entry, health, since):
    return {
        "state": health.state,
        "entry_id": entry.id,
        "std_entry_id": entry.id,
        "name": entry.container_name,
        "host": entry.host,
        "group": entry.group.group_name if entry.group is not None else None,
        "source": entry.source,
        "dashboard_url": dashboard_url(entry.id),
        "since": _iso(since),
        "checks": check_counts_by_state(entry),
    }


def summary_payload(healths):
    counts = {s: 0 for s in health_state.STATES}
    for h in healths:
        counts[h.state] += 1
    counts["total"] = len(healths)
    return counts


def _event(suffix, payload):
    return {"topic": suffix, "payload": payload, "retain": True}


def _clear(suffix):
    return {"topic": suffix, "payload": "", "retain": True}


def _text(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _active_entries():
    return (ServiceEntry.active()
            .options(selectinload(ServiceEntry.checks), joinedload(ServiceEntry.group))
            .order_by(ServiceEntry.id).all())


class PublishState:
    """What has been published, kept by the `Publisher`.

    Persisted (JSON in `setting[notify_publish_state]`): `topics` (every
    topic believed to be on the broker), `entries` (id -> {state, since,
    checks}) and `checks` (id -> {ok, changed}). In memory only: `payloads`
    (topic -> last text sent, to skip unchanged ones on a non-forced sync)
    and `summary`.
    """

    def __init__(self):
        self.lock = threading.RLock()
        self.loaded = False
        self.topics: set = set()
        self.entries: dict = {}
        self.checks: dict = {}
        self.payloads: dict = {}
        self.summary = None
        # Home Assistant discovery (PRD 17.4), per channel id (as text): the
        # absolute config topics believed to be on that broker (persisted) and
        # the last text sent for each (in memory).
        self.ha_topics: dict = {}
        self.ha_payloads: dict = {}

    def load(self):
        """Read the persisted part once (needs an app context)."""
        with self.lock:
            if self.loaded:
                return
            raw = settings_store._get_value(KEY_PUBLISH_STATE, {}) or {}
            self.topics = set(raw.get("topics") or [])
            self.entries = {int(k): v for k, v in (raw.get("entries") or {}).items()}
            self.checks = {int(k): v for k, v in (raw.get("checks") or {}).items()}
            self.ha_topics = {str(k): set(v) for k, v in (raw.get("ha") or {}).items()}
            self.loaded = True

    def save(self):
        with self.lock:
            settings_store._set_value(KEY_PUBLISH_STATE, {
                "topics": sorted(self.topics),
                "entries": {str(k): v for k, v in self.entries.items()},
                "checks": {str(k): v for k, v in self.checks.items()},
                "ha": {k: sorted(v) for k, v in self.ha_topics.items() if v},
            })
            db.session.commit()

    def check_changed(self, check, now):
        """When this check last changed `ok`, remembering it. A check that is
        new to the tracker, or whose ok differs from the remembered one, counts
        as changed `now` (its last check time when it has one)."""
        known = self.checks.get(check.id)
        if known is None or known.get("ok") != check.last_ok:
            when = _iso(check.last_checked_at or now)
            known = {"ok": check.last_ok, "changed": when}
            self.checks[check.id] = known
        return _parse(known["changed"])

    def entry_since(self, entry, health, now):
        known = self.entries.get(entry.id)
        if known is None or known.get("state") != health.state:
            return now, True
        return _parse(known.get("since")) or now, False


def _parse(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError):
        return None


# --- change events (scheduler thread) -------------------------------------------


def publish_changes(publisher, check_ids):
    """Called after a tick's writes commit, inside an app context, on the
    scheduler thread. Builds the events and enqueues them; no network I/O."""
    ids = list(dict.fromkeys(check_ids))
    if not ids:
        return 0
    state = publisher.state
    state.load()
    now = _now()
    checks = HealthCheck.query.filter(HealthCheck.id.in_(ids)).all()
    sent = 0
    with state.lock:
        entries = {}
        for check in checks:
            entry = check.service_entry
            if entry is None or entry.deleted_at is not None:
                continue
            entries[entry.id] = entry
            if not check_counts(entry, check):
                continue
            changed = now
            state.checks[check.id] = {"ok": check.last_ok, "changed": _iso(changed)}
            topic = check_topic(entry.id, check.id)
            payload = check_payload(entry, check, changed)
            state.payloads[topic] = _text(payload)
            state.topics.add(topic)
            publisher.enqueue(_event(topic, payload))
            sent += 1
        rollup_changed = False
        for entry in entries.values():
            health = health_state.entry_health(entry)
            counts = check_counts_by_state(entry)
            known = state.entries.get(entry.id)
            since, state_changed = state.entry_since(entry, health, now)
            if state_changed or known.get("checks") != counts:
                payload = entry_payload(entry, health, since)
                state.entries[entry.id] = {"state": health.state, "since": _iso(since), "checks": counts}
                topic = entry_topic(entry.id)
                state.payloads[topic] = _text(payload)
                state.topics.add(topic)
                publisher.enqueue(_event(topic, payload))
                sent += 1
            rollup_changed = rollup_changed or state_changed
        if rollup_changed:
            summary = summary_payload([health_state.entry_health(e) for e in _active_entries()])
            text = _text(summary)
            if text != state.summary:
                state.summary = text
                state.payloads[SUMMARY_TOPIC] = text
                state.topics.add(SUMMARY_TOPIC)
                publisher.enqueue(_event(SUMMARY_TOPIC, summary))
                sent += 1
        state.save()
    return sent


# --- reconcile (publisher thread) -------------------------------------------------


def desired_state(state, now=None):
    """`{topic: payload dict}` for every active entry and counted check plus the
    summary, updating the tracker's since/changed bookkeeping."""
    now = now or _now()
    desired = {}
    healths = []
    entry_meta, check_meta = {}, {}
    for entry in _active_entries():
        health = health_state.entry_health(entry)
        healths.append(health)
        since, _ = state.entry_since(entry, health, now)
        entry_meta[entry.id] = {"state": health.state, "since": _iso(since),
                                "checks": check_counts_by_state(entry)}
        desired[entry_topic(entry.id)] = entry_payload(entry, health, since)
        for check in counted_checks(entry):
            changed = state.check_changed(check, now)
            check_meta[check.id] = state.checks[check.id]
            desired[check_topic(entry.id, check.id)] = check_payload(entry, check, changed)
    desired[SUMMARY_TOPIC] = summary_payload(healths)
    state.entries, state.checks = entry_meta, check_meta
    return desired


def _clear_absolute(topic):
    return {"topic": topic, "payload": "", "retain": True, "absolute": True}


def sync_discovery(publisher, state, force):
    """Home Assistant discovery (PRD 17.4), per live session: publish the
    desired retained configs and clear every previously published config that
    is no longer desired (opt-outs, deletes, removed checks, discovery turned
    off). A session whose channel has `ha_discovery` off has an empty desired
    set, so its old configs are cleared. Channels with no live session keep
    their remembered topics until they reconnect. Returns `(published, cleared)`."""
    from flask import current_app

    import notify_ha
    from models import NotificationChannel

    sessions = publisher.sessions()
    published = cleared = 0
    if sessions or state.ha_topics:
        known = {str(c.id) for c in NotificationChannel.query.all()}
        for key in [k for k in state.ha_topics if k not in known]:
            state.ha_topics.pop(key)        # channel deleted: nothing left to reach
            for pk in [p for p in state.ha_payloads if p[0] == key]:
                state.ha_payloads.pop(pk)
    if not sessions:
        return 0, 0
    entries = _active_entries()
    instance_id = settings_store.get_instance_id()
    version = current_app.config.get("VERSION_INFO", {}).get("version", "unknown")
    for channel_id, session in sessions:
        key = str(channel_id)
        config = session.config
        desired = (notify_ha.desired_configs(entries, config, instance_id, version)
                   if config.get("ha_discovery") else {})
        for topic in sorted(desired):
            text = _text(desired[topic])
            if not force and state.ha_payloads.get((key, topic)) == text:
                continue
            publisher.dispatch_to(session, {"topic": topic, "payload": desired[topic],
                                            "retain": True, "absolute": True})
            state.ha_payloads[(key, topic)] = text
            published += 1
        for topic in sorted(state.ha_topics.get(key, set()) - set(desired)):
            publisher.dispatch_to(session, _clear_absolute(topic))
            state.ha_payloads.pop((key, topic), None)
            cleared += 1
        if desired:
            state.ha_topics[key] = set(desired)
        else:
            state.ha_topics.pop(key, None)
    return published, cleared


def full_sync(publisher, force=False):
    """Publish the desired retained set and clear what is no longer desired.
    Runs on the publisher thread, inside an app context. `force` republishes
    every topic; otherwise only topics whose payload changed. Does nothing (and
    remembers nothing) while no channel has a session: the connect that
    follows forces a sync. Returns `(published, cleared)`."""
    if not publisher.has_sessions():
        return 0, 0
    state = publisher.state
    state.load()
    with state.lock:
        # Discovery configs go out before the states they describe.
        ha_published, ha_cleared = sync_discovery(publisher, state, force)
        desired = desired_state(state)
        published = cleared = 0
        for topic in sorted(desired):
            text = _text(desired[topic])
            if not force and state.payloads.get(topic) == text:
                continue
            publisher.dispatch(_event(topic, desired[topic]))
            state.payloads[topic] = text
            published += 1
        for topic in sorted(state.topics - set(desired)):
            publisher.dispatch(_clear(topic))
            state.payloads.pop(topic, None)
            cleared += 1
        state.topics = set(desired)
        state.summary = _text(desired[SUMMARY_TOPIC])
        state.save()
    return published + ha_published, cleared + ha_cleared


# --- commit listener -----------------------------------------------------------------


def _touches(obj):
    state = inspect(obj)
    if isinstance(obj, ServiceEntry):
        attrs = _ENTRY_ATTRS
    elif isinstance(obj, HealthCheck):
        attrs = _CHECK_ATTRS
    elif isinstance(obj, Group):
        attrs = _GROUP_ATTRS
    else:
        return False
    return any(state.attrs[a].history.has_changes() for a in attrs)


def _before_flush(session, flush_context, instances):
    if session.info.get("notify_sync"):
        return
    watched = (ServiceEntry, HealthCheck, Group)
    if any(isinstance(o, watched) for o in session.new) or \
            any(isinstance(o, watched) for o in session.deleted) or \
            any(_touches(o) for o in session.dirty):
        session.info["notify_sync"] = True


def _after_commit(session):
    if session.info.pop("notify_sync", False):
        import notify
        notify.request_sync()


def _after_rollback(session):
    session.info.pop("notify_sync", None)


_installed = False


def install_listeners():
    """Idempotent: ask for a sync after commits that change a topic's content."""
    global _installed
    if _installed:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_commit", _after_commit)
    event.listen(Session, "after_soft_rollback", lambda s, prev: _after_rollback(s))
    _installed = True
