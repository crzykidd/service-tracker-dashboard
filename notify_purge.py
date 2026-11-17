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
  entity ids.
"""

import logging
import re
import threading
import time

import notify_ha
import notify_state
import settings_store
from extensions import db
from models import ServiceEntry

logger = logging.getLogger(__name__)

# Collecting the retained burst: wait at least SETTLE seconds, then until QUIET
# seconds pass without a retained message, never longer than MAX_WAIT.
SETTLE_SECONDS = 1.0
QUIET_SECONDS = 0.6
MAX_WAIT_SECONDS = 6.0
# Home Assistant needs a moment to process the removals before the republish,
# otherwise it keeps the old entity registry entries.
HA_PROCESS_SECONDS = 2.0


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


def _ha_pattern(prefix, node):
    return re.compile(rf"^{re.escape(prefix)}/[^/]+/{re.escape(node)}/.+")


# --- channel ---------------------------------------------------------------------


def purge_channel(publisher, channel_id, republish=True):
    """Clear every retained STD topic and discovery config on one channel.
    Returns `{channel_id, topics_cleared, state_topics, discovery_topics,
    republished}`. Publisher thread, inside an app context."""
    session = _live_session(publisher, channel_id)
    if session is None:
        raise PurgeError(409, "This channel is disabled or not running; enable it first.")
    if session.status()["state"] != "connected":
        raise PurgeError(409, "This channel is not connected to its broker; "
                              "see its status for the reason.")
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


# --- entry -----------------------------------------------------------------------


def purge_entry(publisher, entry_id):
    """Clear one entry's state, check and discovery topics on every channel, wait
    for Home Assistant, then republish what is still desired. Returns
    `{entry_id, topics_cleared, channels: [{id, name, state_topics,
    discovery_topics}], republished}`. Publisher thread, inside an app context."""
    sessions = publisher.sessions()
    if not sessions:
        raise PurgeError(409, "No notification channel is enabled.")
    state = publisher.state
    state.load()
    entry = db.session.get(ServiceEntry, entry_id)
    check_ids = {c.id for c in entry.checks} if entry is not None else set()
    with state.lock:
        for topic in state.topics:
            m = re.fullmatch(rf"entry/{entry_id}/check/(\d+)", topic)
            if m:
                check_ids.add(int(m.group(1)))
    state_suffixes = {notify_state.entry_topic(entry_id)} | {
        notify_state.check_topic(entry_id, c) for c in check_ids}
    node = notify_ha.node_id(settings_store.get_instance_id())

    per_channel, total = [], 0
    for channel_id, session in sessions:
        base, prefix = session.config["base_topic"], session.config["ha_prefix"]
        key = str(channel_id)
        discovery = {notify_ha.config_topic(prefix, "sensor", node, f"entry_{entry_id}_state")}
        discovery |= {notify_ha.config_topic(prefix, "binary_sensor", node, f"check_{c}")
                      for c in check_ids}
        with state.lock:
            discovery |= {t for t in state.ha_topics.get(key, ())
                          if f"/{node}/entry_{entry_id}_" in t}
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
    return {"entry_id": entry_id, "topics_cleared": total, "channels": per_channel,
            "republished": True}
