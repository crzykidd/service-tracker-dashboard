"""Purge MQTT topics and Home Assistant devices (PRD 17.5). The fake paho client
(tests/test_notifications.py) answers subscriptions with preset retained
messages; purge logic is called directly, the API tests start the publisher
thread because the request waits for it."""

import time

import pytest

import notify
import notify_purge
import notify_state
from extensions import db
from models import NotificationChannel, ServiceEntry
from tests.test_ha_discovery import HA_CFG, _entry, _node, _setup
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_notifications import Factory, _add
from tests.test_state_publishing import _sync


@pytest.fixture
def factory():
    fake = Factory()
    notify.set_client_factory(fake)
    return fake


@pytest.fixture(autouse=True)
def fast_purge(monkeypatch):
    monkeypatch.setattr(notify_purge, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(notify_purge, "QUIET_SECONDS", 0)
    monkeypatch.setattr(notify_purge, "HA_PROCESS_SECONDS", 0)


def _cleared(client):
    return {t for t, p, _q, r in client.published if r and p == ""}


def _sent(client):
    """topic -> payload for every non-empty retained publish."""
    return {t: p for t, p, _q, r in client.published if r and p != ""}


def _first_channel(app):
    with app.app_context():
        return NotificationChannel.query.order_by(NotificationChannel.id).first().id


def _published_everything(app, pub, client):
    """Entry + check synced, then the client's log reset. Returns the topics STD
    put on the broker (state and discovery)."""
    with app.app_context():
        eid, cid = _entry("web")
        _sync(pub, app)
    topics = set(_sent(client))
    client.published.clear()
    return eid, cid, topics


# --- channel purge ----------------------------------------------------------------


def test_purge_clears_discovered_and_tracked_topics(app, factory):
    pub, client = _setup(app, factory)
    eid, cid, mine = _published_everything(app, pub, client)
    node = _node(app)
    leftover_state = "std/entry/999/state"                      # not tracked, only on the broker
    leftover_cfg = f"homeassistant/sensor/{node}/entry_999_state/config"
    client.retained = [(leftover_state, "{}"), (leftover_cfg, "{}")]
    assert any(t.startswith("homeassistant/") for t in mine) and any(t.startswith("std/") for t in mine)

    with app.app_context():
        result = notify_purge.purge_channel(pub, _first_channel(app), republish=False)

    assert _cleared(client) == mine | {leftover_state, leftover_cfg}
    discovery = {t for t in _cleared(client) if t.startswith("homeassistant/")}
    assert result == {"channel_id": _first_channel(app), "topics_cleared": len(_cleared(client)),
                      "state_topics": len(_cleared(client)) - len(discovery),
                      "discovery_topics": len(discovery), "republished": False}
    assert all(r for *_x, r in client.published)               # every clear is retained
    assert ("std/#", 1) in client.subscriptions and (f"homeassistant/+/{node}/#", 1) in client.subscriptions
    assert sorted(client.unsubscribed) == sorted(["std/#", f"homeassistant/+/{node}/#"])


def test_purge_skips_the_availability_topic(app, factory):
    pub, client = _setup(app, factory)
    client.retained = [("std/status", "online"), ("std/summary", "{}")]
    with app.app_context():
        notify_purge.purge_channel(pub, _first_channel(app), republish=False)
    assert "std/status" not in {t for t, *_ in client.published}
    assert _cleared(client) == {"std/summary"}


def test_purge_ignores_another_instances_node_id(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    mine = f"homeassistant/sensor/{node}/entry_1_state/config"
    theirs = "homeassistant/sensor/std_deadbeef/entry_1_state/config"
    other_ha = "homeassistant/sensor/living_room/temp/config"
    client.retained = [(mine, "{}"), (theirs, "{}"), (other_ha, "{}")]
    with app.app_context():
        notify_purge.purge_channel(pub, _first_channel(app), republish=False)
    assert _cleared(client) == {mine}


def test_purge_ignores_non_retained_messages(app, factory):
    pub, client = _setup(app, factory)

    original = client.subscribe

    def subscribe(topic, qos=0):
        original(topic, qos)
        if topic == "std/#":
            client.deliver("std/live", "x", retain=False)     # a live message, not stored
    client.subscribe = subscribe
    with app.app_context():
        result = notify_purge.purge_channel(pub, _first_channel(app), republish=False)
    assert result["topics_cleared"] == 0 and _cleared(client) == set()


def test_published_sets_are_empty_afterwards(app, factory):
    pub, client = _setup(app, factory)
    _published_everything(app, pub, client)
    assert pub.state.topics and pub.state.ha_topics and pub.state.ha_payloads
    with app.app_context():
        notify_purge.purge_channel(pub, _first_channel(app), republish=False)
        assert pub.state.topics == set() and pub.state.payloads == {}
        assert pub.state.ha_topics == {} and pub.state.ha_payloads == {}
        fresh = notify_state.PublishState()                      # what a restart would load
        fresh.load()
        assert fresh.topics == set() and fresh.ha_topics == {}


def test_republish_true_publishes_everything_again(app, factory):
    pub, client = _setup(app, factory)
    eid, cid, mine = _published_everything(app, pub, client)
    with app.app_context():
        result = notify_purge.purge_channel(pub, _first_channel(app), republish=True)
    assert result["republished"] is True
    assert set(_sent(client)) == mine                            # configs and states are back
    log = [t for t, p, _q, r in client.published]
    assert log.index(next(t for t in log if t.startswith("homeassistant/"))) < \
        log.index(next(t for t in log if t.startswith("std/entry")))
    assert pub.state.topics and pub.state.ha_topics              # tracked again


def test_republish_false_does_not_republish_until_something_changes(app, factory):
    pub, client = _setup(app, factory)
    eid, cid, mine = _published_everything(app, pub, client)
    channel_id = _first_channel(app)
    with app.app_context():
        notify_purge.purge_channel(pub, channel_id, republish=False)
        client.published.clear()
        assert channel_id in pub.state.held

        # Neither a queued event, the forced safety-net sync nor a plain full_sync reaches it.
        pub.enqueue({"topic": "summary", "payload": {"x": 1}, "retain": True})
        pub.drain()
        pub.request_sync(force=True, keep_held=True)
        pub.run_sync_now(app)
        assert _sent(client) == {}

        # A change (a commit-driven sync request) ends the hold and republishes everything.
        pub.request_sync()
        assert channel_id not in pub.state.held
        pub.run_sync_now(app)
    assert set(_sent(client)) == mine


def test_reconnect_ends_the_hold(app, factory):
    pub, client = _setup(app, factory)
    _published_everything(app, pub, client)
    channel_id = _first_channel(app)
    with app.app_context():
        notify_purge.purge_channel(pub, channel_id, republish=False)
    assert channel_id in pub.state.held
    client.drop_connection()
    client.on_connect(client, None, {}, type("R", (), {"is_failure": False})(), None)
    assert channel_id not in pub.state.held and pub.sync_pending()


def test_purge_refuses_a_channel_that_is_not_connected(app, factory):
    _add(app, name="off", enabled=False)
    pub = notify.get_publisher()
    pub.reload_now(app)
    with app.app_context(), pytest.raises(notify_purge.PurgeError) as exc:
        notify_purge.purge_channel(pub, _first_channel(app), republish=True)
    assert exc.value.status == 409


def test_purge_only_touches_the_named_channel(app, factory):
    pub, first = _setup(app, factory)
    _add(app, name="second", config={**HA_CFG, "base_topic": "other"})
    pub.reload_now(app)
    second = factory.clients[1]
    with app.app_context():
        eid, cid = _entry("web")
        _sync(pub, app)
    keep = set(_sent(second))
    assert keep
    second.published.clear()
    first.published.clear()
    first.retained = [("std/summary", "{}")]
    second.retained = [("other/summary", "{}")]
    with app.app_context():
        notify_purge.purge_channel(pub, _first_channel(app), republish=False)
    assert second.published == []
    assert "std/summary" in _cleared(first)


# --- entry purge ------------------------------------------------------------------


def _two_channels(app, factory):
    pub, first = _setup(app, factory)
    _add(app, name="second", config={**HA_CFG, "base_topic": "other"})
    pub.reload_now(app)
    return pub, first, factory.clients[1]


def test_entry_purge_clears_and_republishes_only_that_entry_on_every_channel(app, factory):
    pub, first, second = _two_channels(app, factory)
    with app.app_context():
        a, a_check = _entry("alpha")
        b, b_check = _entry("beta")
        _sync(pub, app)
    node = _node(app)
    with app.app_context():
        a_checks = sorted(c.id for c in db.session.get(ServiceEntry, a).checks)
    assert a_check in a_checks and len(a_checks) >= 2           # a purge clears disabled checks too

    def topics(base):
        out = {f"{base}/entry/{a}/state", f"homeassistant/sensor/{node}/entry_{a}_state/config"}
        for c in a_checks:
            out |= {f"{base}/entry/{a}/check/{c}", f"homeassistant/binary_sensor/{node}/check_{c}/config"}
        return out
    mine = {"std": topics("std"), "other": topics("other")}
    for c in (first, second):
        c.published.clear()

    with app.app_context():
        result = notify_purge.purge_entry(pub, a)

    assert _cleared(first) == mine["std"] and _cleared(second) == mine["other"]
    assert set(_sent(first)) <= mine["std"] and set(_sent(second)) <= mine["other"]
    assert f"std/entry/{a}/state" in _sent(first) and f"other/entry/{a}/state" in _sent(second)
    for c in (first, second):
        cleared_at = [i for i, (t, p, _q, r) in enumerate(c.published) if p == ""]
        resent_at = [i for i, (t, p, _q, r) in enumerate(c.published) if p != ""]
        assert max(cleared_at) < min(resent_at)                  # clear first, republish after
        assert not any(f"/{b}/" in t or f"entry_{b}_" in t or f"check_{b_check}" in t
                       for t, *_ in c.published)
    assert result["topics_cleared"] == len(mine["std"]) + len(mine["other"]) and result["republished"] is True
    assert sorted(c["name"] for c in result["channels"]) == ["ha", "second"]
    assert all(c["state_topics"] == 1 + len(a_checks) and c["discovery_topics"] == 1 + len(a_checks)
               for c in result["channels"])


def test_entry_not_opted_in_only_has_state_purged(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("plain", publish=False)
        _sync(pub, app)
    node = _node(app)
    client.published.clear()
    with app.app_context():
        notify_purge.purge_entry(pub, eid)
    state_topics = {f"std/entry/{eid}/state", f"std/entry/{eid}/check/{cid}"}
    assert state_topics <= _cleared(client)
    assert f"std/entry/{eid}/state" in _sent(client)             # state is republished as normal
    assert all(t.startswith("std/") for t in _sent(client))
    # The device configs are cleared defensively but never republished.
    assert not any(t.startswith("homeassistant/") for t in _sent(client))
    assert f"homeassistant/sensor/{node}/entry_{eid}_state/config" in _cleared(client)


def test_entry_purge_drops_it_from_the_published_sets_then_restores_them(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("web")
        _sync(pub, app)
        monkey_sets = {}
        original = notify_state.full_sync

        def spy(publisher, force=False):
            monkey_sets["topics"] = set(publisher.state.topics)
            monkey_sets["ha"] = set(publisher.state.ha_topics.get("1", ()))
            return original(publisher, force=force)
        notify_state.full_sync = spy
        try:
            notify_purge.purge_entry(pub, eid)
        finally:
            notify_state.full_sync = original
    assert f"entry/{eid}/state" not in monkey_sets["topics"]
    assert not any(f"entry_{eid}_" in t or f"check_{cid}" in t for t in monkey_sets["ha"])
    assert f"entry/{eid}/state" in pub.state.topics


def test_entry_purge_needs_a_channel(app, factory):
    pub = notify.get_publisher()
    with app.app_context():
        eid, cid = _entry("web")
        with pytest.raises(notify_purge.PurgeError) as exc:
            notify_purge.purge_entry(pub, eid)
    assert exc.value.status == 409


def test_deleted_entry_is_purged_and_not_republished(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("web")
        _sync(pub, app)
        db.session.get(ServiceEntry, eid).deleted_at = __import__("datetime").datetime.now()
        db.session.commit()
        client.published.clear()
        notify_purge.purge_entry(pub, eid)
    assert f"std/entry/{eid}/state" in _cleared(client)
    assert not any(f"entry/{eid}" in t or f"entry_{eid}_" in t for t in _sent(client))


# --- management API (the request waits for the publisher thread) -------------------


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "purger", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "viewer", "read")[1])


@pytest.fixture
def running(app, factory):
    """The publisher thread, started with one connected HA channel."""
    cid = _add(app, config=HA_CFG)
    pub = notify.get_publisher()
    pub.start(app)
    deadline = time.monotonic() + 5
    while pub.session_status(cid) is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert pub.session_status(cid)["state"] == "connected"
    yield cid, factory.clients[0]
    pub.stop()


def test_api_channel_purge(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/summary", "{}"), ("std/entry/1/state", "{}")]
    resp = client.post(f"/api/v1/notifications/channels/{cid}/purge", json={"republish": False},
                       headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["channel_id"] == cid and body["republished"] is False
    assert body["state_topics"] == 2 and body["discovery_topics"] == 0
    assert {"std/summary", "std/entry/1/state"} <= _cleared(broker)


def test_api_channel_purge_body_is_optional_and_defaults_to_republish(app, client, wkey, running):
    cid, broker = running
    resp = client.post(f"/api/v1/notifications/channels/{cid}/purge", headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["republished"] is True


def test_api_channel_purge_errors(app, client, wkey, running):
    cid, _broker = running
    url = f"/api/v1/notifications/channels/{cid}/purge"
    assert client.post("/api/v1/notifications/channels/999/purge", headers=wkey).status_code == 404
    assert client.post(url, json={"republish": "yes"}, headers=wkey).status_code == 400
    assert client.post(url, json={"surprise": 1}, headers=wkey).status_code == 400
    with app.app_context():
        off = _add(app, name="off", enabled=False)
    resp = client.post(f"/api/v1/notifications/channels/{off}/purge", headers=wkey)
    assert resp.status_code == 409 and "error" in resp.get_json()


def test_api_channel_purge_when_the_publisher_is_not_running(app, client, wkey, factory):
    cid = _add(app)
    resp = client.post(f"/api/v1/notifications/channels/{cid}/purge", headers=wkey)
    assert resp.status_code == 409 and "not running" in resp.get_json()["error"]


def test_api_request_times_out_with_504(app, client, wkey, running, monkeypatch):
    cid, _broker = running
    monkeypatch.setattr(notify, "JOB_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(notify_purge, "HA_PROCESS_SECONDS", 1.0)
    resp = client.post(f"/api/v1/notifications/channels/{cid}/purge", headers=wkey)
    assert resp.status_code == 504
    time.sleep(1.2)                                              # let the worker finish before teardown


def test_api_entry_purge(app, client, wkey, running):
    cid, broker = running
    with app.app_context():
        eid, check_id = _entry("web")
    resp = client.post(f"/api/v1/entries/{eid}/notifications/purge", headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["entry_id"] == eid and body["republished"] is True
    assert body["channels"][0]["id"] == cid and body["topics_cleared"] >= 4
    assert f"std/entry/{eid}/state" in _cleared(broker)
    assert client.post("/api/v1/entries/9999/notifications/purge", headers=wkey).status_code == 404


def test_api_entry_purge_without_a_channel_is_409(app, client, wkey):
    pub = notify.get_publisher()
    pub.start(app)
    try:
        with app.app_context():
            eid, _check = _entry("web")
        resp = client.post(f"/api/v1/entries/{eid}/notifications/purge", headers=wkey)
        assert resp.status_code == 409
    finally:
        pub.stop()


def test_api_purge_needs_a_write_key(app, client, rkey):
    assert client.post("/api/v1/notifications/channels/1/purge", headers=rkey).status_code == 403
    assert client.post("/api/v1/entries/1/notifications/purge", headers=rkey).status_code == 403
    assert client.post("/api/v1/notifications/channels/1/purge").status_code == 401
    assert client.post("/api/v1/entries/1/notifications/purge").status_code == 401


def test_api_audit_records_the_purge(app, client, wkey, running):
    cid, _broker = running
    client.post(f"/api/v1/notifications/channels/{cid}/purge", headers=wkey)
    from models import ApiAudit
    with app.app_context():
        assert ApiAudit.query.filter(ApiAudit.path.like("%/purge")).count() >= 1


# --- UI routes (admin only, POST) ------------------------------------------------------


def test_ui_channel_purge_passes_the_choice_and_returns_counts(app, admin_client, monkeypatch):
    cid = _add(app)
    calls = []
    monkeypatch.setattr(notify, "purge_channel", lambda c, r: calls.append((c, r)) or {
        "channel_id": c, "topics_cleared": 3, "state_topics": 2, "discovery_topics": 1, "republished": r})
    url = f"/settings/notifications/{cid}/purge"
    resp = admin_client.post(url, data={"republish": "1"})
    assert resp.get_json()["ok"] is True and resp.get_json()["topics_cleared"] == 3
    admin_client.post(url, data={"republish": "0"})
    admin_client.post(url, data={})
    assert calls == [(cid, True), (cid, False), (cid, False)]
    assert admin_client.post("/settings/notifications/999/purge").status_code == 404


def test_ui_entry_purge_and_error_shape(app, admin_client, monkeypatch):
    with app.app_context():
        eid, _cid = _entry("web")

    def boom(entry_id):
        raise notify_purge.PurgeError(409, "No notification channel is enabled.")
    monkeypatch.setattr(notify, "purge_entry", boom)
    resp = admin_client.post(f"/edit/{eid}/purge-notifications")
    assert resp.status_code == 409 and resp.get_json() == {
        "ok": False, "message": "No notification channel is enabled."}


def test_ui_purge_is_admin_only(app, client):
    cid = _add(app)
    assert client.post(f"/settings/notifications/{cid}/purge").status_code in (302, 401)
    assert client.post("/edit/1/purge-notifications").status_code in (302, 401)


def test_ui_buttons_render_only_when_relevant(app, admin_client):
    with app.app_context():
        eid, _cid = _entry("web")
    assert b"notify-purge-btn" not in admin_client.get(f"/edit/{eid}").data
    cid = _add(app)
    page = admin_client.get(f"/edit/{eid}").data
    assert b"Purge and republish to MQTT/HA" in page
    assert b"Purge MQTT and Home Assistant" in admin_client.get("/settings").data
    with app.app_context():
        notify.update_channel(db.session.get(NotificationChannel, cid), enabled=False)
    assert b"notify-purge-btn" not in admin_client.get(f"/edit/{eid}").data
