"""Notification channels: MQTT config, publisher, Settings tab and management API
(PRD 17.2). No test opens a socket: a fake paho client is injected through
`notify.set_client_factory`, and the publisher thread is never started."""

import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import time

import pytest

import notify
import notify_mqtt
from extensions import db
from models import ApiAudit, NotificationChannel
from tests.test_mgmt_api_keys import _bearer, _key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIOUS_HEAD = "c2e8a5b3d917"
NOTIFY_REV = "a2f4c6e8b031"
SECRET = "hunter2-very-secret"


# --- a fake paho client ----------------------------------------------------------


class FakeReason:
    def __init__(self, failure=False, text="Success"):
        self.is_failure = failure
        self._text = text

    def __str__(self):
        return self._text


class FakeInfo:
    def __init__(self, rc=0):
        self.rc = rc

    def wait_for_publish(self, timeout=None):
        return None

    def is_published(self):
        return self.rc == 0


def topic_matches(topic_filter, topic):
    """MQTT wildcard matching (`+` one level, `#` the rest) for the fake broker."""
    f, t = topic_filter.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or (part != "+" and part != t[i]):
            return False
    return len(f) == len(t)


class FakeClient:
    """Stands in for paho.mqtt.client.Client. `connect_async` answers at once
    (success, or the failure given by the factory) and records every call."""

    def __init__(self, client_id, outcome="ok", publish_rc=0, retained=None):
        self.client_id = client_id
        self.outcome = outcome
        self.publish_rc = publish_rc
        self.will = None
        self.auth = None
        self.tls = False
        self.tls_insecure = False
        self.reconnect_delay = None
        self.published = []
        self.connected_to = None
        self.loop_started = False
        self.loop_stopped = False
        self.disconnected = False
        self.on_connect = self.on_disconnect = self.on_connect_fail = None
        self.on_message = None
        self.subscriptions = []
        self.unsubscribed = []
        # Messages the "broker" holds retained: [(topic, payload)]. Subscribing
        # delivers the ones matching the filter, flagged retained (PRD 17.5).
        self.retained = list(retained or [])

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))
        for stored_topic, stored_payload in list(self.retained):
            if topic_matches(topic, stored_topic):
                self.deliver(stored_topic, stored_payload, retain=True)
        return (0, 1)

    def unsubscribe(self, topic):
        self.unsubscribed.append(topic)
        return (0, 1)

    def deliver(self, topic, payload, retain=False):
        """Simulate an incoming message (the Home Assistant birth message, or a
        retained message after a subscription)."""
        class Message:
            pass
        message = Message()
        message.topic, message.payload = topic, payload.encode() if isinstance(payload, str) else payload
        message.retain = retain
        self.on_message(self, None, message)

    def username_pw_set(self, username, password=None):
        self.auth = (username, password)

    def tls_set(self):
        self.tls = True

    def tls_insecure_set(self, value):
        self.tls_insecure = value

    def will_set(self, topic, payload=None, qos=0, retain=False):
        self.will = (topic, payload, qos, retain)

    def reconnect_delay_set(self, min_delay=1, max_delay=120):
        self.reconnect_delay = (min_delay, max_delay)

    def connect_async(self, host, port=1883, keepalive=60):
        self.connected_to = (host, port, keepalive)

    def loop_start(self):
        self.loop_started = True
        if self.outcome == "ok":
            self.on_connect(self, None, {}, FakeReason(), None)
        elif self.outcome == "refused":
            self.on_connect(self, None, {}, FakeReason(True, "Not authorized"), None)
        elif self.outcome == "unreachable":
            self.on_connect_fail(self, None)

    def loop_stop(self):
        self.loop_stopped = True

    def disconnect(self):
        self.disconnected = True

    def publish(self, topic, payload=None, qos=0, retain=False):
        self.published.append((topic, payload, qos, retain))
        return FakeInfo(self.publish_rc)

    def drop_connection(self):
        self.on_disconnect(self, None, {}, FakeReason(True, "Unspecified error"), None)


class Factory:
    def __init__(self, **client_kwargs):
        self.clients = []
        self.client_kwargs = client_kwargs

    def __call__(self, client_id):
        client = FakeClient(client_id, **self.client_kwargs)
        self.clients.append(client)
        return client


@pytest.fixture
def factory():
    fake = Factory()
    notify.set_client_factory(fake)
    return fake


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "reader", "read")[1])


GOOD = {"host": "mqtt.lan"}


def _add(app, name="ha", enabled=True, config=None, secret=None):
    with app.app_context():
        channel, errors = notify.create_channel(name, "mqtt", enabled, config or GOOD, secret)
        assert not errors, errors
        return channel.id


def _specs(app):
    with app.app_context():
        return [notify.ChannelSpec(c.id, c.type, c.name, dict(c.config), c.secret)
                for c in NotificationChannel.query.filter_by(enabled=True).all()]


# --- config validation --------------------------------------------------------------


def test_config_defaults_and_port_by_tls():
    cfg = notify_mqtt.clean_config({"host": "b.lan"})
    assert cfg["port"] == 1883 and cfg["qos"] == 1 and cfg["keepalive"] == 60
    assert cfg["base_topic"] == "std" and cfg["tls"] is False and cfg["tls_insecure"] is False
    assert (cfg["ha_discovery"], cfg["ha_prefix"], cfg["ha_device_prefix"]) == (False, "homeassistant", "STD")
    assert notify_mqtt.clean_config({"host": "b.lan", "tls": True})["port"] == 8883
    assert notify_mqtt.clean_config({"host": "b.lan", "tls": True, "port": 1884})["port"] == 1884


def test_base_topic_trailing_slash_is_stripped():
    assert notify_mqtt.clean_config({"host": "b", "base_topic": "home/std//"})["base_topic"] == "home/std"
    assert notify_mqtt.clean_config({"host": "b", "base_topic": "std/"})["base_topic"] == "std"


@pytest.mark.parametrize("bad", [
    {"host": "b", "port": 0}, {"host": "b", "port": 70000}, {"host": "b", "port": "abc"},
    {"host": ""}, {"host": "mqtt://b"}, {"host": "has space"}, {},
    {"host": "b", "qos": 2}, {"host": "b", "keepalive": 1},
    {"host": "b", "base_topic": "a/+/b"}, {"host": "b", "base_topic": "/"},
    {"host": "b", "client_id": "bad id!"}, {"host": "b", "tls_insecure": True},
    {"host": "b", "surprise": 1},
])
def test_bad_config_is_rejected(bad):
    with pytest.raises(Exception) as exc:
        notify_mqtt.clean_config(bad)
    assert exc.type.__name__ == "ValidationError"


def test_unknown_key_error_names_the_field(app):
    with app.app_context():
        _, errors = notify.validate_config("mqtt", {"host": "b", "surprise": 1})
    assert errors == [{"field": "config.surprise", "message": "Extra inputs are not permitted"}]


def test_unknown_channel_type(app):
    with app.app_context():
        channel, errors = notify.create_channel("x", "carrier-pigeon", True, {}, None)
    assert channel is None and errors[0]["field"] == "type"


# --- instance id ----------------------------------------------------------------------


def test_instance_id_is_generated_once_and_stable(app):
    import settings_store
    with app.app_context():
        first = settings_store.get_instance_id()
        assert re.fullmatch(r"[0-9a-f-]{36}", first)
        assert settings_store.get_instance_id() == first
        assert len(settings_store.short_instance_id(first)) == 8
    assert notify_mqtt.client_id_for({}, first) == f"std-{first.replace('-', '')[:8]}"
    assert notify_mqtt.client_id_for({"client_id": "mine"}, first) == "mine"


# --- enqueue never blocks, drops the oldest ------------------------------------------------


def test_enqueue_drops_oldest_when_full_and_never_blocks(caplog):
    pub = notify.get_publisher()
    caplog.set_level(logging.WARNING, logger="notify")
    started = time.monotonic()
    for n in range(notify.QUEUE_MAX + 25):
        assert notify.enqueue({"n": n}) is True
    assert time.monotonic() - started < 2
    assert pub.queue.qsize() == notify.QUEUE_MAX
    assert pub.queue.get_nowait() == {"n": 25}            # the 25 oldest are gone
    assert pub.dropped == 25
    warnings = [r for r in caplog.records if "queue is full" in r.getMessage()]
    assert len(warnings) == 1                              # rate limited, not once per drop


def test_enqueue_never_raises():
    assert notify.enqueue("not a dict") is False
    assert notify.enqueue(None) is False


# --- LWT, online, reconnect ----------------------------------------------------------------------


def test_session_sets_will_and_publishes_online(app, factory):
    _add(app, config={"host": "mqtt.lan", "username": "u", "base_topic": "home/std/", "qos": 1}, secret=SECRET)
    pub = notify.get_publisher()
    with app.app_context():
        from settings_store import get_instance_id
        iid = get_instance_id()
    pub.reload_now(app)
    (client,) = factory.clients
    assert client.client_id == f"std-{iid.replace('-', '')[:8]}"
    assert client.will == ("home/std/status", "offline", 1, True)
    assert client.auth == ("u", SECRET)
    assert client.connected_to == ("mqtt.lan", 1883, 60)
    assert client.reconnect_delay == (1, 60) and client.loop_started
    assert ("home/std/status", "online", 1, True) in client.published
    cid = _channel_id(app, "ha")
    assert pub.session_status(cid)["state"] == "connected"
    pub.stop()


def _channel_id(app, name):
    with app.app_context():
        return NotificationChannel.query.filter_by(name=name).one().id


def test_tls_options_reach_the_client(app, factory):
    _add(app, config={"host": "b", "tls": True, "tls_insecure": True})
    notify.get_publisher().reload_now(app)
    client = factory.clients[0]
    assert client.tls and client.tls_insecure and client.connected_to[1] == 8883
    notify.get_publisher().stop()


def test_clean_stop_publishes_offline(app, factory):
    _add(app)
    pub = notify.get_publisher()
    pub.reload_now(app)
    client = factory.clients[0]
    pub.stop()
    assert client.published[-1] == ("std/status", "offline", 1, True)
    assert client.disconnected and client.loop_stopped


def test_dispatch_publishes_events_to_enabled_channels(app, factory):
    _add(app)
    pub = notify.get_publisher()
    pub.reload_now(app)
    notify.enqueue({"topic": "entry/1/state", "payload": {"state": "up"}, "retain": True})
    notify.enqueue({"nothing": "to publish"})
    pub._dispatch(pub.queue.get_nowait())
    pub._dispatch(pub.queue.get_nowait())
    published = factory.clients[0].published
    assert ("std/entry/1/state", '{"state":"up"}', 1, True) in published
    assert not [p for p in published if "nothing" in str(p)]
    pub.stop()


def test_on_connect_hooks_run_after_each_connect(app, factory):
    seen = []
    notify.on_connect_hooks.append(lambda session: seen.append(session.name))
    notify.on_connect_hooks.append(lambda session: 1 / 0)       # a bad hook must not break the rest
    _add(app, name="ha")
    pub = notify.get_publisher()
    pub.reload_now(app)
    assert seen == ["ha"]
    client = factory.clients[0]
    client.drop_connection()
    client.on_connect(client, None, {}, FakeReason(), None)      # paho reconnects
    assert seen == ["ha", "ha"]
    pub.stop()


def test_state_changes_log_once_not_per_retry(app, factory, caplog):
    factory.client_kwargs["outcome"] = "unreachable"
    caplog.set_level(logging.INFO, logger="notify_mqtt")
    _add(app)
    pub = notify.get_publisher()
    pub.reload_now(app)
    client = factory.clients[0]
    for _ in range(5):
        client.on_connect_fail(client, None)                      # paho retrying
    lines = [r for r in caplog.records if "cannot reach the broker" in r.getMessage()]
    assert len(lines) == 1
    cid = _channel_id(app, "ha")
    assert pub.session_status(cid)["state"] == "error"
    assert "cannot reach the broker at mqtt.lan:1883" in pub.session_status(cid)["last_error"]
    pub.stop()


def test_refused_connection_is_an_error_without_secret(app, factory, caplog):
    factory.client_kwargs["outcome"] = "refused"
    caplog.set_level(logging.DEBUG)
    _add(app, config={"host": "b", "username": "u"}, secret=SECRET)
    pub = notify.get_publisher()
    pub.reload_now(app)
    status = pub.session_status(_channel_id(app, "ha"))
    assert status["state"] == "error" and "Not authorized" in status["last_error"]
    assert SECRET not in caplog.text and SECRET not in json.dumps(status)
    pub.stop()


# --- reload on config change -----------------------------------------------------------------------


def test_config_change_reconnects_with_the_new_config(app, factory):
    cid = _add(app, config={"host": "old.lan"})
    pub = notify.get_publisher()
    pub.reload_now(app)
    first = factory.clients[0]
    pub.reload_now(app)                                  # nothing changed: same session
    assert len(factory.clients) == 1

    with app.app_context():
        channel = db.session.get(NotificationChannel, cid)
        _, errors = notify.update_channel(channel, config={"host": "new.lan"})
        assert not errors
    pub.reload_now(app)
    assert first.published[-1] == ("std/status", "offline", 1, True) and first.disconnected
    assert len(factory.clients) == 2 and factory.clients[1].connected_to[0] == "new.lan"
    assert pub.session_status(cid)["state"] == "connected"

    with app.app_context():                               # password change reconnects too
        notify.update_channel(db.session.get(NotificationChannel, cid), secret="other")
    pub.reload_now(app)
    assert len(factory.clients) == 3

    with app.app_context():                               # disabling disconnects
        notify.update_channel(db.session.get(NotificationChannel, cid), enabled=False)
    pub.reload_now(app)
    assert pub.session_status(cid) is None and factory.clients[2].disconnected
    pub.stop()


def test_deleting_a_channel_disconnects_it(app, factory):
    cid = _add(app)
    pub = notify.get_publisher()
    pub.reload_now(app)
    with app.app_context():
        notify.delete_channel(db.session.get(NotificationChannel, cid))
    pub.reload_now(app)
    assert factory.clients[0].disconnected and pub.session_status(cid) is None


def test_request_reload_is_a_noop_without_the_thread(app, factory):
    _add(app)
    notify.request_reload()
    assert factory.clients == []                         # nothing connects in tests


def test_running_thread_applies_a_reload(app, factory):
    """The one test that starts the publisher thread (with the fake client)."""
    cid = _add(app)
    pub = notify.get_publisher()
    pub.start(app)
    try:
        deadline = time.monotonic() + 5
        while pub.session_status(cid) is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pub.session_status(cid)["state"] == "connected"
        with app.app_context():
            notify.update_channel(db.session.get(NotificationChannel, cid), config={"host": "x.lan"})
        deadline = time.monotonic() + 5
        while len(factory.clients) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert factory.clients[1].connected_to[0] == "x.lan"
    finally:
        pub.stop()
    assert not pub.running


# --- test message ---------------------------------------------------------------------------------------


def test_test_message_success(app, factory):
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b.lan", "base_topic": "x"}, SECRET)
    assert ok and "x/test" in message and SECRET not in message
    client = factory.clients[0]
    assert client.client_id.endswith("-test") and client.will is None
    topic, payload, qos, retain = client.published[0]
    assert topic == "x/test" and retain is False and json.loads(payload)["message"]
    assert client.disconnected and client.loop_stopped


@pytest.mark.parametrize("outcome,expect", [("refused", "Not authorized"), ("unreachable", "cannot reach")])
def test_test_message_failure(app, factory, outcome, expect):
    factory.client_kwargs["outcome"] = outcome
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b.lan"}, SECRET)
    assert not ok and expect.lower() in message.lower() and SECRET not in message


def test_test_message_publish_failure(app, factory):
    factory.client_kwargs["publish_rc"] = 4
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b.lan"}, None)
    assert not ok and "not delivered" in message


def test_test_message_timeout(app, factory, monkeypatch):
    factory.client_kwargs["outcome"] = "silent"
    monkeypatch.setattr(notify_mqtt, "TEST_CONNECT_SECONDS", 0.05)
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b.lan"}, None)
    assert not ok and "No answer" in message


def test_test_message_budget_is_short_and_bounded():
    # the whole test (connect + publish) is about 5 s, never the old ~13 s
    assert notify_mqtt.TEST_TOTAL_SECONDS <= 5
    assert notify_mqtt.TEST_CONNECT_SECONDS < notify_mqtt.TEST_TOTAL_SECONDS


def test_test_message_silent_broker_returns_within_budget(app, factory, monkeypatch):
    import time
    factory.client_kwargs["outcome"] = "silent"
    monkeypatch.setattr(notify_mqtt, "TEST_CONNECT_SECONDS", 0.2)
    started = time.monotonic()
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b.lan", "port": 1884}, None)
    assert not ok and "b.lan:1884" in message and "within 0.2 seconds" in message
    assert time.monotonic() - started < 2


def test_test_with_invalid_config_reports_it(app, factory):
    with app.app_context():
        ok, message = notify.test_channel("mqtt", {"host": "b", "port": 0}, None)
    assert not ok and "config.port" in message and factory.clients == []


# --- management API ------------------------------------------------------------------------------------------


def _post(client, headers, **body):
    return client.post("/api/v1/notifications/channels", json=body, headers=headers)


def test_api_create_get_list_and_secret_is_write_only(app, client, wkey, rkey):
    resp = _post(client, wkey, name="ha", enabled=True, config={"host": "mqtt.lan", "username": "u"},
                 secret=SECRET)
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["secret_set"] is True and "secret" not in body and SECRET not in resp.get_data(as_text=True)
    assert body["config"]["port"] == 1883 and body["status"]["state"] == "stopped"
    cid = body["id"]
    for url in (f"/api/v1/notifications/channels/{cid}", "/api/v1/notifications/channels"):
        got = client.get(url, headers=rkey)
        assert got.status_code == 200 and SECRET not in got.get_data(as_text=True)
    assert client.get("/api/v1/notifications/channels", headers=rkey).get_json()["total"] == 1
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).secret == SECRET


def test_api_patch_secret_semantics(app, client, wkey):
    cid = _post(client, wkey, name="ha", config=GOOD, secret=SECRET).get_json()["id"]
    url = f"/api/v1/notifications/channels/{cid}"

    got = client.patch(url, json={"enabled": True}, headers=wkey).get_json()       # omitted keeps
    assert got["secret_set"] is True and got["enabled"] is True
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).secret == SECRET

    got = client.patch(url, json={"secret": "new"}, headers=wkey).get_json()
    assert got["secret_set"] is True
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).secret == "new"

    got = client.patch(url, json={"secret": None}, headers=wkey).get_json()       # null clears
    assert got["secret_set"] is False
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).secret is None


def test_api_patch_merges_config_and_validates(app, client, wkey):
    cid = _post(client, wkey, name="ha", config={"host": "a", "qos": 0}).get_json()["id"]
    url = f"/api/v1/notifications/channels/{cid}"
    got = client.patch(url, json={"config": {"host": "b"}}, headers=wkey).get_json()
    assert got["config"]["host"] == "b" and got["config"]["qos"] == 0
    assert client.patch(url, json={"config": {"port": 0}}, headers=wkey).status_code == 400
    assert client.patch(url, json={"config": {"nope": 1}}, headers=wkey).status_code == 400
    assert client.patch(url, json={}, headers=wkey).status_code == 400
    assert client.patch(url, json={"name": None}, headers=wkey).status_code == 400
    assert client.patch(url, json={"surprise": 1}, headers=wkey).status_code == 400


def test_api_validation_and_conflicts(client, wkey):
    assert _post(client, wkey, name="x", config={"host": "b", "port": 99999}).status_code == 400
    assert _post(client, wkey, name="x", config={"host": "b", "zzz": 1}).status_code == 400
    assert _post(client, wkey, name="x", type="smoke", config={}).status_code == 400
    assert _post(client, wkey, name="", config=GOOD).status_code == 400
    assert _post(client, wkey, name="dup", config=GOOD).status_code == 201
    assert _post(client, wkey, name="dup", config=GOOD).status_code == 409
    assert client.get("/api/v1/notifications/channels/999", headers=wkey).status_code == 404


def test_api_delete(app, client, wkey):
    cid = _post(client, wkey, name="ha", config=GOOD).get_json()["id"]
    resp = client.delete(f"/api/v1/notifications/channels/{cid}?cleanup=false", headers=wkey)
    assert resp.get_json() == {"id": cid, "deleted": True, "cleanup": None}
    assert client.delete(f"/api/v1/notifications/channels/{cid}", headers=wkey).status_code == 404


def test_api_scopes(client, rkey):
    assert _post(client, rkey, name="x", config=GOOD).status_code == 403
    assert client.patch("/api/v1/notifications/channels/1", json={"enabled": True}, headers=rkey).status_code == 403
    assert client.delete("/api/v1/notifications/channels/1", headers=rkey).status_code == 403
    assert client.post("/api/v1/notifications/channels/1/test", headers=rkey).status_code == 403
    assert client.get("/api/v1/notifications/channels").status_code == 401


def test_api_test_endpoint_success_and_failure(app, client, wkey, factory):
    cid = _post(client, wkey, name="ha", config={"host": "b.lan"}, secret=SECRET).get_json()["id"]
    resp = client.post(f"/api/v1/notifications/channels/{cid}/test", headers=wkey)
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] is True and "std/test" in body["message"]
    assert factory.clients[0].auth is None or factory.clients[0].auth[1] == SECRET

    factory.client_kwargs["outcome"] = "refused"
    body = client.post(f"/api/v1/notifications/channels/{cid}/test", headers=wkey).get_json()
    assert body["ok"] is False and "Not authorized" in body["message"] and SECRET not in json.dumps(body)
    assert client.post("/api/v1/notifications/channels/999/test", headers=wkey).status_code == 404


def test_api_audit_never_records_the_secret(app, client, wkey):
    cid = _post(client, wkey, name="ha", config=GOOD, secret=SECRET).get_json()["id"]
    client.patch(f"/api/v1/notifications/channels/{cid}", json={"secret": "another-secret"}, headers=wkey)
    with app.app_context():
        rows = ApiAudit.query.filter_by(object_type="notification_channel").all()
        dump = json.dumps([r.changes for r in rows])
    assert rows and SECRET not in dump and "another-secret" not in dump


# --- Settings -> Notifications -------------------------------------------------------------------------------------


FORM = {"name": "broker", "enabled": "1", "host": "mqtt.lan", "port": "", "username": "u",
        "password": SECRET, "client_id": "", "base_topic": "std", "qos": "1", "keepalive": "60"}


def test_ui_tab_requires_admin(client):
    assert client.post("/settings/notifications/save", data=FORM).status_code in (302, 401)


def test_ui_create_edit_and_password_is_write_only(app, admin_client):
    resp = admin_client.post("/settings/notifications/save", data=FORM)
    assert resp.status_code == 302
    with app.app_context():
        channel = NotificationChannel.query.one()
        cid = channel.id
        assert channel.secret == SECRET and channel.enabled and channel.config["port"] == 1883

    page = admin_client.get("/settings?section=notifications").get_data(as_text=True)
    assert "broker" in page and SECRET not in page
    assert re.search(r'"secret_set":\s*true', page)          # only the flag reaches the page

    edit = {**FORM, "channel_id": str(cid), "password": "", "host": "other.lan", "tls": "1"}
    assert admin_client.post("/settings/notifications/save", data=edit).status_code == 302
    with app.app_context():
        channel = db.session.get(NotificationChannel, cid)
        assert channel.secret == SECRET                                   # blank keeps it
        assert channel.config["host"] == "other.lan" and channel.config["port"] == 8883

    cleared = {**edit, "clear_password": "1"}
    admin_client.post("/settings/notifications/save", data=cleared)
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).secret is None    # clear box removes it


def test_ui_invalid_form_rerenders_with_errors(app, admin_client):
    resp = admin_client.post("/settings/notifications/save", data={**FORM, "port": "70000"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400 and "config.port" in html and SECRET not in html
    with app.app_context():
        assert NotificationChannel.query.count() == 0


def test_ui_toggle_and_delete(app, admin_client):
    admin_client.post("/settings/notifications/save", data=FORM)
    with app.app_context():
        cid = NotificationChannel.query.one().id
    admin_client.post(f"/settings/notifications/{cid}/toggle")
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).enabled is False
    admin_client.post(f"/settings/notifications/{cid}/delete")
    with app.app_context():
        assert NotificationChannel.query.count() == 0


def test_ui_test_button_uses_submitted_values(admin_client, factory):
    resp = admin_client.post("/settings/notifications/test", data=FORM)
    body = resp.get_json()
    assert body["ok"] is True and SECRET not in json.dumps(body)
    assert factory.clients[0].auth == ("u", SECRET) and factory.clients[0].connected_to[0] == "mqtt.lan"


def test_ui_test_button_with_blank_password_uses_stored_one(app, admin_client, factory):
    admin_client.post("/settings/notifications/save", data=FORM)
    with app.app_context():
        cid = NotificationChannel.query.one().id
    admin_client.post("/settings/notifications/test", data={**FORM, "channel_id": str(cid), "password": ""})
    assert factory.clients[0].auth == ("u", SECRET)


def test_ui_test_button_failure_and_bad_input(admin_client, factory):
    factory.client_kwargs["outcome"] = "unreachable"
    body = admin_client.post("/settings/notifications/test", data=FORM).get_json()
    assert body["ok"] is False and "cannot reach" in body["message"].lower()
    body = admin_client.post("/settings/notifications/test", data={**FORM, "host": ""}).get_json()
    assert body["ok"] is False and "config.host" in body["message"]


def test_ui_status_endpoint(app, admin_client):
    admin_client.post("/settings/notifications/save", data=FORM)
    data = admin_client.get("/settings/notifications/status").get_json()
    (state,) = data.values()
    assert state["state"] == "stopped"                    # the publisher is not running in tests


# --- migration -------------------------------------------------------------------------------------------------------


def _alembic(tmp_path, db_path, command, target):
    ini = tmp_path / "alembic.ini"
    text = open(os.path.join(REPO_ROOT, "alembic.ini")).read()
    text = re.sub(r"(?m)^script_location\s*=.*$", f"script_location = {REPO_ROOT}/alembic", text)
    text = re.sub(r"(?m)^sqlalchemy.url\s*=.*$", f"sqlalchemy.url = sqlite:///{db_path}", text)
    ini.write_text(text)
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ini), command, target],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _tables(db_path):
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_migration_up_down_up(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS_HEAD)
    assert "notification_channel" not in _tables(db_path)
    _alembic(tmp_path, db_path, "upgrade", NOTIFY_REV)
    con = sqlite3.connect(db_path)
    indexes = {r[1]: r[2] for r in con.execute("PRAGMA index_list(notification_channel)")}
    assert indexes["ux_notification_channel_name"] == 1 and "ix_notification_channel_type" in indexes
    con.execute("INSERT INTO notification_channel (type, name, enabled, config, created_at, updated_at) "
                "VALUES ('mqtt', 'a', 0, '{}', '2026-01-01', '2026-01-01')")
    con.commit()
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO notification_channel (type, name, enabled, config, created_at, updated_at) "
                    "VALUES ('mqtt', 'a', 0, '{}', '2026-01-01', '2026-01-01')")
    con.close()

    _alembic(tmp_path, db_path, "downgrade", "-1")
    assert "notification_channel" not in _tables(db_path)
    _alembic(tmp_path, db_path, "upgrade", "head")
    assert "notification_channel" in _tables(db_path)


def test_publisher_is_not_running_under_tests():
    assert not notify.get_publisher().running
