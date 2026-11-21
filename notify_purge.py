"""Purge MQTT topics and Home Assistant devices (PRD 17.5).

Two clean-slate tools, both run on the publisher thread (the request thread only
queues the job and waits for the counts, see `Publisher.call`):

- `purge_channel()` removes every retained STD message and every STD discovery
  config from one channel's broker. It subscribes briefly to `<base>/#` and to
  `<ha_prefix>/+/std_<instance>/#` (this instance's node id only, so another
  STD install's devices are never touched), collects what arrives retained, adds
  the topics the publish state remembers, and publishes an empty retained
  payload to each. `<base>/status` (the last will) is left alone.
- `purge_entry()` clears one entry's state topic, check topics and discovery
  configs on every channel, waits for Home Assistant to process the removals and
  republishes whatever is still desired, so HA recreates the device with fresh
  entity ids. `purge_stream()` does the same for every entry of an inventory
  stream plus the stream's own status topic and hub device, batched in one job.
- `clear_old_namespace()` runs when a channel's base topic or discovery prefix is
  about to change: it clears what the old values left on the broker. Previous
  bases are remembered per channel (last 5) for `scan_orphans()`, which lists the
  retained STD topics that nothing desires any more (state and discovery, current
  and remembered bases, an optional operator-typed base) and `clear_orphans()`
  removes them.
"""

import logging
import re
import threading
import time

import image_update
import notify_ha
import notify_state
import settings_store
from extensions import db
from models import HealthCheck, InventoryStream, NotificationChannel, ServiceEntry

logger = logging.getLogger(__name__)

# Collecting the retained burst: wait at least SETTLE seconds, then until QUIET
# seconds pass without a retained message, never longer than MAX_WAIT.
SETTLE_SECONDS = 1.0
QUIET_SECONDS = 0.6
MAX_WAIT_SECONDS = 6.0
# Home Assistant needs a moment to process the removals before the republish,
# otherwise it keeps the old entity registry entries.
HA_PROCESS_SECONDS = 2.0
KEY_PREVIOUS_BASES = "notify_previous_bases"
MAX_PREVIOUS_BASES = 5
BASE_MAX = 128
# The topic shapes STD publishes under a base topic; the orphan scan never reports
# anything else, so an operator-typed base cannot sweep up another application's topics.
_STATE_SHAPE = re.compile(
    r"^(status|summary|entry/\d+/state|entry/\d+/image|entry/\d+/check/\d+|stream/[a-z0-9][a-z0-9_-]*)$")


class PurgeError(Exception):
    """A refusal the caller reports as HTTP `status` with `message`."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Job:
    """A unit of work for the publisher thread; the requester waits on `done`."""

    def __init__(self, fn):
        self.fn = fn
        self.done = threading.Event()
        self.result = None
        self.error = None

    def run(self, publisher, app):
        try:
            with app.app_context():
                self.result = self.fn(publisher)
        except PurgeError as exc:
            self.error = exc
        except Exception:
            db.session.rollback()
            logger.exception("Notification purge failed")
            self.error = PurgeError(500, "The purge failed; see the STD log.")
        finally:
            self.done.set()


def _clear(topic):
    return {"topic": topic, "payload": "", "retain": True, "absolute": True}


def _live_session(publisher, channel_id):
    for cid, session in publisher.sessions():
        if cid == channel_id:
            return session
    return None


def _connected_session(publisher, channel_id):
    """The channel's live, connected session, or a 409 `PurgeError` saying why not."""
    session = _live_session(publisher, channel_id)
    if session is None:
        raise PurgeError(409, "This channel is disabled or not running; enable it first.")
    if session.status()["state"] != "connected":
        raise PurgeError(409, "This channel is not connected to its broker; "
                              "see its status for the reason.")
    return session


def _ha_pattern(prefix, node):
    return re.compile(rf"^{re.escape(prefix)}/[^/]+/{re.escape(node)}/.+")


# --- channel ---------------------------------------------------------------------


def purge_channel(publisher, channel_id, republish=True, clear_status=False):
    """Clear every retained STD topic and discovery config on one channel.
    Returns `{channel_id, topics_cleared, state_topics, discovery_topics,
    republished}`. Publisher thread, inside an app context.

    `clear_status` is for a channel that is about to be deleted: `<base>/status` is
    cleared too, last, and the session is told not to publish `offline` over it
    when it stops. Without it the availability topic is left alone."""
    session = _connected_session(publisher, channel_id)
    state = publisher.state
    state.load()
    config = session.config
    base, prefix = config["base_topic"], config["ha_prefix"]
    node = notify_ha.node_id(settings_store.get_instance_id())
    ha_re = _ha_pattern(prefix, node)
    status_topic = f"{base}/status"

    found = session.collect_retained(
        [f"{base}/#", f"{prefix}/+/{node}/#"], SETTLE_SECONDS, QUIET_SECONDS, MAX_WAIT_SECONDS)
    key = str(channel_id)
    with state.lock:
        tracked = {f"{base}/{t}" for t in state.topics} | set(state.ha_topics.get(key, ()))
    # Only this channel's own namespace and this instance's node id, never
    # anything else that happened to match, and never the availability topic.
    topics = {t for t in found | tracked
              if t != status_topic and (ha_re.match(t) or t.startswith(base + "/"))}
    discovery = {t for t in topics if ha_re.match(t)}
    for topic in sorted(topics):
        publisher.dispatch_to(session, _clear(topic))
    if clear_status:
        publisher.dispatch_to(session, _clear(status_topic))
        session.suppress_offline = True

    with state.lock:
        state.ha_topics.pop(key, None)
        for pk in [p for p in state.ha_payloads if p[0] == key]:
            state.ha_payloads.pop(pk)
        # The state-topic bookkeeping is one set shared by every channel; it is
        # emptied only when no other channel still has these topics.
        if len(publisher.sessions()) <= 1:
            state.topics = set()
            state.payloads.clear()
            state.summary = None
        state.save()

    if republish:
        state.held.discard(channel_id)
        time.sleep(HA_PROCESS_SECONDS)
        notify_state.full_sync(publisher, force=True)
    else:
        state.held.add(channel_id)
    return {"channel_id": channel_id, "topics_cleared": len(topics),
            "state_topics": len(topics) - len(discovery), "discovery_topics": len(discovery),
            "republished": bool(republish)}


# --- entries and streams ------------------------------------------------------------


def _purge_entries(publisher, entry_ids, stream=None):
    """Clear the state, check and discovery topics of `entry_ids` (and a stream's own
    status topic and hub device when `stream` is given) on every live channel, wait for
    Home Assistant, then republish what is still desired. One batch, whatever the
    number of entries. Returns `(per_channel, topics_cleared)`."""
    sessions = publisher.sessions()
    if not sessions:
        raise PurgeError(409, "No notification channel is enabled.")
    state = publisher.state
    state.load()
    ids = set(entry_ids)
    check_ids = {eid: set() for eid in ids}
    if ids:
        for check_id, entry_id in db.session.query(HealthCheck.id, HealthCheck.service_entry_id).filter(
                HealthCheck.service_entry_id.in_(ids)):
            check_ids[entry_id].add(check_id)
    check_re = re.compile(r"entry/(\d+)/check/(\d+)")
    with state.lock:
        remembered = set(state.topics)
        for topic in state.topics:               # remembered checks that may no longer exist
            m = check_re.fullmatch(topic)
            if m and int(m.group(1)) in ids:
                check_ids[int(m.group(1))].add(int(m.group(2)))
    state_suffixes = set()
    for eid in ids:
        state_suffixes.add(notify_state.entry_topic(eid))
        if notify_state.image_topic(eid) in remembered:      # only when one was published
            state_suffixes.add(notify_state.image_topic(eid))
        state_suffixes |= {notify_state.check_topic(eid, c) for c in check_ids[eid]}
    if stream is not None:
        state_suffixes.add(notify_state.stream_topic(stream.stream_id))
    node = notify_ha.node_id(settings_store.get_instance_id())
    entry_cfg_re = re.compile(rf"/{re.escape(node)}/entry_(\d+)_")

    per_channel, total = [], 0
    for channel_id, session in sessions:
        base, prefix = session.config["base_topic"], session.config["ha_prefix"]
        key = str(channel_id)
        discovery = set()
        for eid in ids:
            discovery.add(notify_ha.config_topic(prefix, "sensor", node, f"entry_{eid}_state"))
            discovery.add(notify_ha.config_topic(prefix, "sensor", node, f"entry_{eid}_since"))
            discovery |= {notify_ha.config_topic(prefix, "binary_sensor", node, f"check_{c}")
                          for c in check_ids[eid]}
        if stream is not None:
            discovery |= {notify_ha.config_topic(prefix, "sensor", node, f"stream_{stream.stream_id}_{part}")
                          for part in ("status", "active", "missing")}
            discovery.add(notify_ha.config_topic(prefix, "binary_sensor", node,
                                                 f"stream_{stream.stream_id}_problem"))
        with state.lock:
            for t in state.ha_topics.get(key, ()):
                m = entry_cfg_re.search(t)
                if m and int(m.group(1)) in ids:
                    discovery.add(t)
        for suffix in sorted(state_suffixes):
            publisher.dispatch_to(session, _clear(f"{base}/{suffix}"))
        for topic in sorted(discovery):
            publisher.dispatch_to(session, _clear(topic))
        with state.lock:
            state.ha_topics[key] = set(state.ha_topics.get(key, ())) - discovery
            if not state.ha_topics[key]:
                state.ha_topics.pop(key)
            for topic in discovery:
                state.ha_payloads.pop((key, topic), None)
        per_channel.append({"id": channel_id, "name": session.name,
                            "state_topics": len(state_suffixes),
                            "discovery_topics": len(discovery)})
        total += len(state_suffixes) + len(discovery)
    with state.lock:
        state.topics -= state_suffixes
        for suffix in state_suffixes:
            state.payloads.pop(suffix, None)
        state.save()

    # Let Home Assistant drop the device, then publish whatever is still desired
    # (a reconcile: only the missing topics go out). An entry that is not opted
    # in to Home Assistant gets its state topics back and no discovery configs.
    time.sleep(HA_PROCESS_SECONDS)
    notify_state.full_sync(publisher, force=False)
    return per_channel, total


def purge_entry(publisher, entry_id):
    """Clear one entry's state, check and discovery topics on every channel, wait
    for Home Assistant, then republish what is still desired. Returns
    `{entry_id, topics_cleared, channels: [{id, name, state_topics,
    discovery_topics}], republished}`. Publisher thread, inside an app context."""
    per_channel, total = _purge_entries(publisher, [entry_id])
    return {"entry_id": entry_id, "topics_cleared": total, "channels": per_channel,
            "republished": True}


def purge_stream(publisher, stream_pk):
    """Clear the topics and Home Assistant devices of every entry of one inventory
    stream (soft-deleted ones too), plus the stream's status topic and hub device, on
    every channel; then republish what is still eligible. Returns `{stream_id,
    entries, topics_cleared, channels: [{id, name, state_topics, discovery_topics}],
    republished}`. Publisher thread, inside an app context."""
    stream = db.session.get(InventoryStream, stream_pk)
    if stream is None:
        raise PurgeError(404, "That stream no longer exists.")
    entry_ids = [eid for (eid,) in db.session.query(ServiceEntry.id).filter_by(stream_id=stream.id)]
    per_channel, total = _purge_entries(publisher, entry_ids, stream=stream)
    return {"stream_id": stream.stream_id, "entries": len(entry_ids), "topics_cleared": total,
            "channels": per_channel, "republished": True}


# --- previous bases ----------------------------------------------------------------------


def previous_bases(channel_id):
    """`[{base_topic, ha_prefix}]`, newest first, at most MAX_PREVIOUS_BASES: the base
    topic and discovery prefix pairs this channel used before (needs an app context)."""
    raw = settings_store._get_value(KEY_PREVIOUS_BASES, {}) or {}
    return [dict(item) for item in raw.get(str(channel_id), [])]


def remember_base(channel_id, old, new):
    """Record the `(base_topic, ha_prefix)` pair `old` as previous when it differs from
    `new` (both `{base_topic, ha_prefix, ...}` configs). The caller commits."""
    old_pair = {"base_topic": old["base_topic"], "ha_prefix": old["ha_prefix"]}
    new_pair = {"base_topic": new["base_topic"], "ha_prefix": new["ha_prefix"]}
    if old_pair == new_pair:
        return
    raw = dict(settings_store._get_value(KEY_PREVIOUS_BASES, {}) or {})
    items = [i for i in raw.get(str(channel_id), []) if i not in (old_pair, new_pair)]
    raw[str(channel_id)] = ([old_pair] + items)[:MAX_PREVIOUS_BASES]
    settings_store._set_value(KEY_PREVIOUS_BASES, raw)


def forget_bases(channel_id):
    """Drop a deleted channel's remembered bases. The caller commits."""
    raw = dict(settings_store._get_value(KEY_PREVIOUS_BASES, {}) or {})
    if raw.pop(str(channel_id), None) is not None:
        settings_store._set_value(KEY_PREVIOUS_BASES, raw)


# --- base topic / prefix change -----------------------------------------------------------


def namespace_change(old, new):
    """`(base_changed, ha_changed)` between two channel configs. A discovery change only
    counts when discovery was on: a new prefix or device name prefix leaves configs (or
    stale device names) behind."""
    base_changed = old["base_topic"] != new["base_topic"]
    ha_changed = bool(old.get("ha_discovery")) and (
        old["ha_prefix"] != new["ha_prefix"] or old["ha_device_prefix"] != new["ha_device_prefix"])
    return base_changed, ha_changed


def clear_old_namespace(publisher, channel_id, new_config):
    """Clear what the channel's current (old) base topic and discovery prefix left on its
    broker, before the channel switches to `new_config`. A changed base: every retained
    topic under `<old>/#`, the old `status` included. A changed discovery prefix or
    device prefix: this instance's discovery configs under the old prefix (Home Assistant
    drops the devices; the next sync publishes them under the new values). Returns
    `{topics_cleared, state_topics, discovery_topics}`. Publisher thread."""
    session = _connected_session(publisher, channel_id)
    state = publisher.state
    state.load()
    old = session.config
    base_changed, ha_changed = namespace_change(old, new_config)
    if not (base_changed or ha_changed):
        return {"topics_cleared": 0, "state_topics": 0, "discovery_topics": 0}
    node = notify_ha.node_id(settings_store.get_instance_id())
    old_base, old_prefix = old["base_topic"], old["ha_prefix"]
    ha_re = _ha_pattern(old_prefix, node)
    filters = []
    if base_changed:
        filters.append(f"{old_base}/#")
    if ha_changed:
        filters.append(f"{old_prefix}/+/{node}/#")
    found = session.collect_retained(filters, SETTLE_SECONDS, QUIET_SECONDS, MAX_WAIT_SECONDS)
    key = str(channel_id)
    topics = set()
    with state.lock:
        if base_changed:
            topics |= {t for t in found if t.startswith(old_base + "/")}
            topics |= {f"{old_base}/{t}" for t in state.topics}
            topics.add(f"{old_base}/status")
        if ha_changed:
            topics |= {t for t in found if ha_re.match(t)}
            topics |= {t for t in state.ha_topics.get(key, ()) if ha_re.match(t)}
    discovery = {t for t in topics if ha_re.match(t)}
    for topic in sorted(topics):
        publisher.dispatch_to(session, _clear(topic))
    if base_changed:
        session.suppress_offline = True      # stop() would publish `offline` to the old status topic
    with state.lock:
        state.ha_topics[key] = {t for t in state.ha_topics.get(key, ()) if t not in discovery}
        if not state.ha_topics[key]:
            state.ha_topics.pop(key)
        for topic in discovery:
            state.ha_payloads.pop((key, topic), None)
        state.save()
    return {"topics_cleared": len(topics), "state_topics": len(topics) - len(discovery),
            "discovery_topics": len(discovery)}


# --- orphans ---------------------------------------------------------------------------


def clean_extra_base(value):
    """The operator-typed base topic to scan as well, normalised; None when blank.
    Raises a 400 `PurgeError` for a value that is not a plain topic prefix."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise PurgeError(400, "extra_base must be text.")
    value = value.strip().rstrip("/")
    if not value:
        return None
    if (len(value) > BASE_MAX or value.startswith(("/", "$")) or "+" in value or "#" in value
            or "//" in value or "\x00" in value):
        raise PurgeError(400, "extra_base must be a topic prefix without '+', '#', '//' or a leading '/' or '$'.")
    return value


def _desired_topics(channel):
    """Every absolute topic that something still wants on this channel's broker: the
    desired state topics, the availability topic and the discovery configs of every
    channel that shares the broker (same host and port), so one channel's scan never
    calls another's live topics orphans."""
    from flask import current_app
    state_keys = set(notify_state.desired_state(notify_state.PublishState()))
    entries = notify_state._active_entries()
    image_enabled = image_update.is_enabled()
    instance_id = settings_store.get_instance_id()
    version = current_app.config.get("VERSION_INFO", {}).get("version", "unknown")
    host, port = (channel.config or {}).get("host"), (channel.config or {}).get("port")
    out = set()
    for other in NotificationChannel.query.all():
        cfg = other.config or {}
        if (cfg.get("host"), cfg.get("port")) != (host, port) or "base_topic" not in cfg:
            continue
        out |= {f"{cfg['base_topic']}/{k}" for k in state_keys}
        out.add(f"{cfg['base_topic']}/status")
        if cfg.get("ha_discovery"):
            out |= set(notify_ha.desired_configs(entries, cfg, instance_id, version, image_enabled))
    return out


class _Namespaces:
    """What a channel's orphan scan looks at: bases and prefixes, and a classifier."""

    def __init__(self, channel, extra_base):
        cfg = channel.config or {}
        previous = previous_bases(channel.id)
        self.bases = list(dict.fromkeys(
            [cfg["base_topic"]] + [p["base_topic"] for p in previous] + ([extra_base] if extra_base else [])))
        self.prefixes = list(dict.fromkeys([cfg["ha_prefix"]] + [p["ha_prefix"] for p in previous]))
        if extra_base and extra_base in self.prefixes:
            raise PurgeError(400, "extra_base is a Home Assistant discovery prefix; "
                                  "other devices' configs live there.")
        self.node = notify_ha.node_id(settings_store.get_instance_id())
        self._ha = [_ha_pattern(p, self.node) for p in self.prefixes]

    def filters(self):
        return [f"{b}/#" for b in self.bases] + [f"{p}/+/{self.node}/#" for p in self.prefixes]

    def kind(self, topic):
        """`"state"`, `"discovery"` or None for a topic outside everything scanned."""
        if any(r.match(topic) for r in self._ha):
            return "discovery"
        for base in self.bases:
            if topic.startswith(base + "/") and _STATE_SHAPE.match(topic[len(base) + 1:]):
                return "state"
        return None


def _load_channel(channel_id):
    channel = db.session.get(NotificationChannel, channel_id)
    if channel is None:
        raise PurgeError(404, f"No notification channel with id {channel_id}.")
    return channel


def scan_orphans(publisher, channel_id, extra_base=None):
    """List the retained STD topics on a channel's broker that nothing desires any more
    (preview; nothing is cleared). Subscribes briefly (the purge timing) to `<base>/#`
    for the current base, every remembered previous base and `extra_base`, plus this
    instance's discovery wildcard under the current and remembered prefixes, and diffs the
    retained topics against the desired set. Only topics shaped like STD's own count.
    Returns `{channel_id, scanned, count, orphans: [{topic, kind}]}`. Publisher thread."""
    extra_base = clean_extra_base(extra_base)
    session = _connected_session(publisher, channel_id)
    channel = _load_channel(channel_id)
    spaces = _Namespaces(channel, extra_base)
    found = session.collect_retained(spaces.filters(), SETTLE_SECONDS, QUIET_SECONDS, MAX_WAIT_SECONDS)
    desired = _desired_topics(channel)
    orphans = [{"topic": t, "kind": spaces.kind(t)} for t in sorted(found - desired) if spaces.kind(t)]
    return {"channel_id": channel_id, "scanned": spaces.filters(), "count": len(orphans), "orphans": orphans}


def clear_orphans(publisher, channel_id, topics=None, extra_base=None):
    """Clear orphans. With `topics` (what a scan returned) only those are cleared, and
    only when they are still inside the scanned namespaces and still not desired; the
    rest come back as `skipped`. Without `topics` the channel is scanned again and
    every orphan found is cleared. Returns `{channel_id, topics_cleared, topics,
    skipped}`. Publisher thread."""
    extra_base = clean_extra_base(extra_base)
    if topics is None:
        found = scan_orphans(publisher, channel_id, extra_base)
        topics = [o["topic"] for o in found["orphans"]]
        skipped = []
    else:
        session = _connected_session(publisher, channel_id)
        channel = _load_channel(channel_id)
        spaces = _Namespaces(channel, extra_base)
        desired = _desired_topics(channel)
        skipped = [t for t in topics if not isinstance(t, str) or t in desired or not spaces.kind(t)]
        topics = [t for t in dict.fromkeys(topics) if t not in skipped]
    session = _connected_session(publisher, channel_id)
    for topic in topics:
        publisher.dispatch_to(session, _clear(topic))
    state = publisher.state
    state.load()
    key = str(channel_id)
    with state.lock:
        if state.ha_topics.get(key):
            state.ha_topics[key] -= set(topics)
            if not state.ha_topics[key]:
                state.ha_topics.pop(key)
        for topic in topics:
            state.ha_payloads.pop((key, topic), None)
        state.save()
    return {"channel_id": channel_id, "topics_cleared": len(topics), "topics": list(topics),
            "skipped": skipped}
