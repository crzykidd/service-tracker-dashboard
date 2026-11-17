"""Notification channels and the background publisher (PRD 17.2).

Producers (the health scheduler, later the register path) call
`enqueue(event_dict)`: it never blocks and never raises. One publisher thread
owns a bounded queue and one live session (paho client) per enabled channel;
it is the only code that talks to a broker, so the checker and scheduler
threads never wait on network I/O. gunicorn runs exactly one worker, so one
in-process publisher is correct.

Events are plain dicts. For MQTT an event is
`{"topic": "<suffix under base_topic>", "payload": str | dict | list, "retain": bool}`;
notif-02/03 add the producers. `on_connect_hooks` lets them republish
everything after a (re)connect.

Channel rows live in `notification_channel`; creating, editing, toggling or
deleting one calls `request_reload()`, which makes the publisher thread diff
the enabled channels against its live sessions (a changed channel is stopped
cleanly and reconnected with the new config) without restarting STD.

The publisher is not started under pytest; tests inject a fake paho client
through `set_client_factory` and call `reload_now` / `apply_specs` directly.
"""

import atexit
import logging
import queue
import threading
import time
from dataclasses import dataclass

from pydantic import ValidationError

import notify_state
import settings_store
from extensions import db
from models import NotificationChannel
from notify_mqtt import MqttChannelType, default_client_factory

logger = logging.getLogger(__name__)

QUEUE_MAX = 1000
DROP_WARN_EVERY_SECONDS = 60
SYNC_DEBOUNCE_SECONDS = 2
SYNC_SAFETY_NET_MINUTES = 10
NAME_MAX = 64
SECRET_MAX = 256

CHANNEL_TYPES = {MqttChannelType.type: MqttChannelType}

# Called as hook(session) from the broker's network thread after a (re)connect
# (the `online` message is already out). `session.publish(event)` is safe to use.
on_connect_hooks: list = []

UNSET = object()   # "leave this field alone" for update_channel


@dataclass(frozen=True)
class ChannelSpec:
    id: int
    type: str
    name: str
    config: dict
    secret: str | None

    def fingerprint(self, instance_id):
        import json
        return (self.type, json.dumps(self.config, sort_keys=True), self.secret, instance_id)


# --- client factory (injectable) ---------------------------------------------

_client_factory = default_client_factory


def set_client_factory(factory):
    """Replace the paho client factory (tests); None restores the real one."""
    global _client_factory
    _client_factory = factory or default_client_factory


def client_factory():
    return _client_factory


def _on_connected(session):
    # Runs on the paho network thread: only ask the publisher thread for a full
    # republish (state publishing, PRD 17.3); it does the database work.
    request_sync(force=True)
    for hook in list(on_connect_hooks):
        try:
            hook(session)
        except Exception:
            logger.exception("Notification on-connect hook failed")


# --- the publisher ------------------------------------------------------------


class Publisher:
    def __init__(self):
        self.queue = queue.Queue(maxsize=QUEUE_MAX)
        self.dropped = 0
        self._last_drop_warn = 0.0
        self._sessions: dict = {}        # channel id -> (fingerprint, session)
        self._lock = threading.RLock()
        self._reload = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._app = None
        self.state = notify_state.PublishState()
        self._sync_lock = threading.Lock()
        self._sync_due = None            # monotonic time the pending sync may run
        self._sync_force = False

    # producers ----------------------------------------------------------------

    def enqueue(self, event) -> bool:
        """Never blocks, never raises. When full the OLDEST event is dropped
        (a state change is superseded by the next one) with a rate-limited warning."""
        try:
            if not isinstance(event, dict):
                return False
            for _ in range(3):
                try:
                    self.queue.put_nowait(event)
                    return True
                except queue.Full:
                    try:
                        self.queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.dropped += 1
                    now = time.monotonic()
                    if now - self._last_drop_warn >= DROP_WARN_EVERY_SECONDS:
                        self._last_drop_warn = now
                        logger.warning("Notification queue is full (%d): dropping the oldest events "
                                       "(%d dropped so far)", QUEUE_MAX, self.dropped)
        except Exception:
            logger.debug("enqueue failed", exc_info=True)
        return False

    # lifecycle ----------------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, app):
        with self._lock:
            if self.running:
                return
            self._app = app
            self._stop.clear()
            self._reload.set()
            self._thread = threading.Thread(target=self._run, daemon=True, name="notify-publisher")
            self._thread.start()
        atexit.register(self.stop)

    def stop(self, timeout=5):
        thread = self._thread
        self._stop.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout)
        self._close_all()
        self._thread = None

    def request_reload(self):
        """Ask the publisher thread to re-read the channels. A no-op when the
        publisher is not running (it loads the channels when it starts)."""
        if self.running:
            self._reload.set()

    def request_sync(self, force=False):
        """Ask for a reconcile of the retained state topics (PRD 17.3). Cheap and
        non-blocking; requests inside the debounce window collapse into one run.
        `force` republishes every topic instead of only what changed."""
        with self._sync_lock:
            self._sync_force = self._sync_force or force
            if self._sync_due is None:
                self._sync_due = time.monotonic() + SYNC_DEBOUNCE_SECONDS

    def sync_pending(self) -> bool:
        return self._sync_due is not None

    def run_sync_now(self, app=None):
        """Run the pending sync (if any) now, ignoring the debounce. Publisher
        thread; tests call it directly. Returns `(published, cleared)` or None."""
        with self._sync_lock:
            if self._sync_due is None:
                return None
            force = self._sync_force
            self._sync_due, self._sync_force = None, False
        app = app or self._app
        with app.app_context():
            try:
                return notify_state.full_sync(self, force=force)
            except Exception:
                db.session.rollback()
                logger.exception("Notification state sync failed")
                return None

    def has_sessions(self) -> bool:
        with self._lock:
            return bool(self._sessions)

    def drain(self):
        """Dispatch every queued event now (tests; the thread does this itself)."""
        while True:
            try:
                event = self.queue.get_nowait()
            except queue.Empty:
                return
            self.dispatch(event)

    # internals ----------------------------------------------------------------

    def _run(self):
        while not self._stop.is_set():
            if self._reload.is_set():
                self._reload.clear()
                try:
                    self.reload_now(self._app)
                except Exception:
                    logger.exception("Notification channel reload failed")
            due = self._sync_due
            if due is not None and time.monotonic() >= due:
                self.run_sync_now(self._app)
            try:
                event = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            self.dispatch(event)
        self._close_all()

    def dispatch(self, event):
        """Hand one event to every live session (publisher thread)."""
        with self._lock:
            sessions = [s for _, s in self._sessions.values()]
        for session in sessions:
            try:
                CHANNEL_TYPES[session.type].publish(session, event)
            except Exception:
                logger.exception("Publishing to channel '%s' failed", session.name)

    _dispatch = dispatch

    def reload_now(self, app=None):
        """Read the enabled channels from the database and apply them."""
        app = app or self._app
        with app.app_context():
            instance_id = settings_store.get_instance_id()
            specs = [
                ChannelSpec(c.id, c.type, c.name, dict(c.config or {}), c.secret)
                for c in NotificationChannel.query.filter_by(enabled=True).order_by(NotificationChannel.id)
                if c.type in CHANNEL_TYPES
            ]
        self.apply_specs(specs, instance_id)

    def apply_specs(self, specs, instance_id):
        """Make the live sessions match `specs`: stop removed and changed
        channels (cleanly, `offline` published), start new and changed ones."""
        wanted = {s.id: s for s in specs}
        to_stop, to_start = [], []
        with self._lock:
            for cid, (fingerprint, session) in list(self._sessions.items()):
                spec = wanted.get(cid)
                if spec is None or spec.fingerprint(instance_id) != fingerprint:
                    to_stop.append(session)
                    del self._sessions[cid]
            for cid, spec in wanted.items():
                if cid not in self._sessions:
                    to_start.append(spec)
        for session in to_stop:
            session.stop()      # may wait a couple of seconds; outside the lock
        for spec in to_start:
            session = CHANNEL_TYPES[spec.type].open_session(
                spec.id, spec.name, spec.config, spec.secret, instance_id,
                _client_factory, _on_connected)
            with self._lock:
                self._sessions[spec.id] = (spec.fingerprint(instance_id), session)
            session.start()

    def _close_all(self):
        with self._lock:
            sessions = [s for _, s in self._sessions.values()]
            self._sessions.clear()
        for session in sessions:
            try:
                session.stop()
            except Exception:
                logger.debug("closing session failed", exc_info=True)

    def session_status(self, channel_id):
        with self._lock:
            entry = self._sessions.get(channel_id)
        return entry[1].status() if entry else None


_publisher = Publisher()


def get_publisher() -> Publisher:
    return _publisher


def enqueue(event) -> bool:
    """Queue an event for every enabled channel. Never blocks, never raises."""
    return _publisher.enqueue(event)


def start(app):
    _publisher.start(app)


def stop():
    _publisher.stop()


def request_reload():
    _publisher.request_reload()


def request_sync(force=False):
    """Mutation paths and the periodic safety net call this; see Publisher.request_sync."""
    _publisher.request_sync(force)


def publish_changes(check_ids):
    """Scheduler thread, after a tick commits: enqueue the state changes for the
    checks whose result changed. Never raises."""
    try:
        return notify_state.publish_changes(_publisher, check_ids)
    except Exception:
        db.session.rollback()
        logger.exception("Publishing state changes failed")
        return 0


def reset():
    """Test helper: stop everything and forget all state, hooks and the factory."""
    global _publisher
    _publisher.stop(timeout=1)
    _publisher = Publisher()
    on_connect_hooks.clear()
    set_client_factory(None)


# --- status -------------------------------------------------------------------


def channel_status(channel) -> dict:
    """`{state, last_error, since}` for the UI and API. State is one of
    disabled | stopped (publisher not running) | connecting | connected | error."""
    if not channel.enabled:
        return {"state": "disabled", "last_error": None, "since": None}
    live = _publisher.session_status(channel.id)
    if live is not None:
        return live
    if not _publisher.running:
        return {"state": "stopped", "last_error": None, "since": None}
    return {"state": "connecting", "last_error": None, "since": None}


# --- channel CRUD (shared by the Settings page and the management API) ----------


def channel_type(type_name):
    return CHANNEL_TYPES.get(type_name)


def _check_name(name, exclude_id=None):
    if not isinstance(name, str) or not name.strip():
        return None, [{"field": "name", "message": "is required"}]
    name = name.strip()
    if len(name) > NAME_MAX:
        return None, [{"field": "name", "message": f"is limited to {NAME_MAX} characters"}]
    clash = NotificationChannel.query.filter(NotificationChannel.name == name)
    if exclude_id is not None:
        clash = clash.filter(NotificationChannel.id != exclude_id)
    if clash.first() is not None:
        return None, [{"field": "name", "message": f"a channel named '{name}' already exists"}]
    return name, []


def _check_secret(secret):
    if secret is not None and (not isinstance(secret, str) or len(secret) > SECRET_MAX):
        return [{"field": "secret", "message": f"must be text of at most {SECRET_MAX} characters"}]
    return []


def validate_config(type_name, config):
    """`(clean_config, errors)` for a channel type."""
    ctype = CHANNEL_TYPES.get(type_name)
    if ctype is None:
        return None, [{"field": "type", "message": f"unknown channel type; use one of {', '.join(CHANNEL_TYPES)}"}]
    try:
        return ctype.validate(config), []
    except ValidationError as exc:
        return None, ctype.errors(exc)


def create_channel(name, type_name, enabled, config, secret):
    """`(channel, errors)`. Commits and asks the publisher to reload."""
    name, errors = _check_name(name)
    clean, cfg_errors = validate_config(type_name, config or {})
    errors = errors + cfg_errors + _check_secret(secret)
    if errors:
        return None, errors
    channel = NotificationChannel(type=type_name, name=name, enabled=bool(enabled), config=clean,
                                  secret=secret or None)
    db.session.add(channel)
    db.session.commit()
    request_reload()
    return channel, []


def update_channel(channel, name=UNSET, enabled=UNSET, config=UNSET, secret=UNSET):
    """`(channel, errors)`. `config` is merged over the stored config; `secret`
    UNSET keeps it, None clears it. Commits and asks the publisher to reload."""
    errors = []
    if name is not UNSET:
        name, name_errors = _check_name(name, exclude_id=channel.id)
        errors += name_errors
    clean = None
    if config is not UNSET:
        clean, cfg_errors = validate_config(channel.type, {**(channel.config or {}), **config})
        errors += cfg_errors
    if secret is not UNSET:
        errors += _check_secret(secret)
    if errors:
        return None, errors
    if name is not UNSET:
        channel.name = name
    if enabled is not UNSET:
        channel.enabled = bool(enabled)
    if clean is not None:
        channel.config = clean
    if secret is not UNSET:
        channel.secret = secret or None
    db.session.commit()
    request_reload()
    return channel, []


def delete_channel(channel):
    db.session.delete(channel)
    db.session.commit()
    request_reload()


def test_channel(type_name, config, secret):
    """`(ok, message)`: validate, then try a real connection and a test message."""
    clean, errors = validate_config(type_name, config)
    if errors:
        return False, "; ".join(f"{e['field']}: {e['message']}" for e in errors)
    instance_id = settings_store.get_instance_id()
    return CHANNEL_TYPES[type_name].test(clean, secret, instance_id, _client_factory)


notify_state.install_listeners()
