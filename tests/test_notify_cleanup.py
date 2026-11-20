"""Broker cleanup (PRD 17.5), per-stream status topic (18.6) and stream hub devices
(17.4): channel delete / disable cleanup, base topic change cleanup and remembered
bases, per-stream purge, the orphan scan, the stream topic and the stream device.
The fake paho client (tests/test_notifications.py) stands in for the broker; the
API tests start the publisher thread because the request waits for it."""

import json
import time
from datetime import datetime

import pytest

import mgmt_openapi
import notify
import notify_ha
import notify_purge
import notify_state
import streams
from extensions import db
from models import (
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    StreamLinkOffer,
    ensure_url_checks,
)
from tests.test_ha_discovery import HA_CFG, _cfg, _configs, _entry, _node, _setup
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_notifications import Factory, _add
from tests.test_purge import _cleared, _first_channel, _sent
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


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "cleaner", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "viewer", "read")[1])


def _wait(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert predicate()


@pytest.fixture
def running(app, factory):
    """The publisher thread with one connected HA channel (`std` base)."""
    cid = _add(app, config=HA_CFG)
    pub = notify.get_publisher()
    pub.start(app)
    _wait(lambda: pub.session_status(cid) is not None and pub.session_status(cid)["state"] == "connected")
    yield cid, factory.clients[0]
    pub.stop()


def _stream(app, slug="dhcp", n=2, publish=True, status="enabled", name="DHCP"):
    """An inventory stream with `n` stream entries, each with an enabled internal-URL
    check. Returns `(stream pk, [entry ids])`."""
    with app.app_context():
        stream = InventoryStream(stream_id=slug, display_name=name, producer="std-source-test",
                                 producer_version="1.2.3", key_type="mac", status=status, last_item_count=n)
        db.session.add(stream)
        db.session.flush()
        ids = []
        for i in range(n):
            entry = ServiceEntry(host=None, container_name=f"{slug}-dev{i}", source="stream",
                                 stream_id=stream.id, stream_key=f"aa:00:00:00:00:0{i}",
                                 internalurl=f"http://{slug}-dev{i}", ha_publish=publish,
                                 last_updated=datetime.now())
            db.session.add(entry)
            db.session.flush()
            ensure_url_checks(entry)
            entry.url_check("internal").enabled = True
            ids.append(entry.id)
        db.session.commit()
        return stream.id, ids


def _entry_topics(app, entry_ids, base="std"):
    """`(state topics, discovery topics)` an opted-in entry has on a channel."""
    node = _node(app)
    state, discovery = set(), set()
    with app.app_context():
        for eid in entry_ids:
            state.add(f"{base}/entry/{eid}/state")
            discovery |= {f"homeassistant/sensor/{node}/entry_{eid}_state/config",
                          f"homeassistant/sensor/{node}/entry_{eid}_since/config"}
            for check in db.session.get(ServiceEntry, eid).checks:     # a purge clears every check
                state.add(f"{base}/{notify_state.check_topic(eid, check.id)}")
                discovery.add(f"homeassistant/binary_sensor/{node}/check_{check.id}/config")
    return state, discovery


# --- stream status topic (PRD 18.6) -----------------------------------------------------------


def test_stream_topic_payload(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=3)
    with app.app_context():
        nas, _check = _entry("nas", publish=False)
        stream = db.session.get(InventoryStream, sid)
        stream.last_snapshot_at = datetime(2026, 11, 19, 10, 0, 5)
        stream.last_applied_at = datetime(2026, 11, 19, 10, 0, 6)
        db.session.get(ServiceEntry, ids[2]).inventory_missing = True
        db.session.add(StreamLinkOffer(stream_id=sid, key="aa:00:00:00:00:99", entry_id=nas, item={}))
        db.session.commit()
        _sync(pub, app)
    assert json.loads(_sent(client)["std/stream/dhcp"]) == {
        "stream_id": "dhcp", "display_name": "DHCP", "status": "enabled",
        "producer": "std-source-test", "producer_version": "1.2.3",
        "last_snapshot_at": "2026-11-19T10:00:05Z", "last_applied_at": "2026-11-19T10:00:06Z",
        "counts": {"active": 3, "missing": 1, "pending_offers": 1}, "item_count": 3}
    assert all(r for *_x, r in client.published)                       # retained
    assert "stream/dhcp" in pub.state.topics                           # tracked, so it can be cleared


def test_a_pending_stream_publishes_its_status_without_entries(app, factory):
    pub, client = _setup(app, factory)
    _stream(app, n=0, status="pending")
    with app.app_context():
        _sync(pub, app)
    payload = json.loads(_sent(client)["std/stream/dhcp"])
    assert payload["status"] == "pending" and payload["counts"]["active"] == 0


def test_entry_topics_stay_keyed_by_entry_id(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=1)
    with app.app_context():
        _sync(pub, app)
    assert f"std/entry/{ids[0]}/state" in _sent(client)
    assert not any("/stream/" in t and "/entry/" in t for t in _sent(client))


def test_stream_status_change_requests_a_sync_and_republishes(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app)
    with app.app_context():
        _sync(pub, app)
        assert not pub.sync_pending()
        client.published.clear()
        db.session.get(InventoryStream, sid).status = "disabled"
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
    assert json.loads(_sent(client)["std/stream/dhcp"])["status"] == "disabled"
    assert set(_sent(client)) == {"std/stream/dhcp"}                    # nothing else changed


def test_a_new_link_offer_and_a_snapshot_time_request_a_sync(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app)
    with app.app_context():
        nas, _check = _entry("nas", publish=False)
        _sync(pub, app)
        db.session.add(StreamLinkOffer(stream_id=sid, key="aa:00:00:00:00:99", entry_id=nas, item={}))
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
        assert json.loads(_sent(client)["std/stream/dhcp"])["counts"]["pending_offers"] == 1
        db.session.get(InventoryStream, sid).last_snapshot_at = datetime(2026, 11, 20, 8, 0, 0)
        db.session.commit()
        assert pub.sync_pending()


def test_deleting_a_stream_clears_its_topic_and_hub_device(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app)
    node = _node(app)
    with app.app_context():
        _sync(pub, app)
    hub = {f"homeassistant/sensor/{node}/stream_dhcp_{part}/config" for part in ("status", "active", "missing")}
    assert hub <= set(_sent(client)) and "std/stream/dhcp" in _sent(client)
    client.published.clear()
    with app.app_context():
        streams.delete(db.session.get(InventoryStream, sid), cleanup="keep")
        assert pub.sync_pending()
        pub.run_sync_now(app)
    assert "std/stream/dhcp" in _cleared(client) and hub <= _cleared(client)
    assert "stream/dhcp" not in pub.state.topics
    assert not any(t.startswith("std/stream/") for t in _sent(client))


# --- stream hub device (PRD 17.4) ------------------------------------------------------------


def test_stream_hub_device_and_entry_via_device(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=2)
    with app.app_context():
        manual_id, _c = _entry("plain")
        _sync(pub, app)
    node = _node(app)
    status = _cfg(client, node, "sensor", "stream_dhcp_status")
    assert status["device"] == {
        "identifiers": [f"{node}_stream_dhcp"], "name": "STD DHCP stream", "manufacturer": "Service Tracker Dashboard",
        "model": "Stream", "sw_version": status["device"]["sw_version"], "via_device": node}
    assert status["state_topic"] == status["json_attributes_topic"] == "std/stream/dhcp"
    assert status["value_template"] == "{{ value_json.status }}"
    assert status["unique_id"] == f"{node}_stream_dhcp_status"
    assert status["availability_topic"] == "std/status"
    active = _cfg(client, node, "sensor", "stream_dhcp_active")
    missing = _cfg(client, node, "sensor", "stream_dhcp_missing")
    assert active["value_template"] == "{{ value_json.counts.active }}"
    assert missing["value_template"] == "{{ value_json.counts.missing }}"
    assert active["device"] == missing["device"] == status["device"]
    # Entry devices of the stream hang off the stream device; every other entry off the hub.
    for eid in ids:
        assert _cfg(client, node, "sensor", f"entry_{eid}_state")["device"]["via_device"] == f"{node}_stream_dhcp"
    assert _cfg(client, node, "sensor", f"entry_{manual_id}_state")["device"]["via_device"] == node


def test_a_stream_without_a_published_entry_has_no_hub_device(app, factory):
    pub, client = _setup(app, factory)
    _stream(app, publish=False)
    with app.app_context():
        _sync(pub, app)
    assert not any("stream_dhcp" in t for t in _configs(client))
    assert "std/stream/dhcp" in _sent(client)                           # the status topic does not depend on it


def test_stream_hub_device_follows_the_last_published_entry(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=1)
    node = _node(app)
    with app.app_context():
        _sync(pub, app)
        client.published.clear()
        db.session.get(ServiceEntry, ids[0]).ha_publish = False
        db.session.commit()
        pub.run_sync_now(app)
    gone = {f"homeassistant/sensor/{node}/stream_dhcp_{p}/config" for p in ("status", "active", "missing")}
    assert gone <= _cleared(client)
    assert not (gone & set(_sent(client)))


def test_stream_hub_device_name_uses_the_device_prefix(app, factory):
    pub, client = _setup(app, factory, ha_device_prefix="Lab")
    _stream(app, name="Static DHCP")
    with app.app_context():
        _sync(pub, app)
    node = _node(app)
    assert _cfg(client, node, "sensor", "stream_dhcp_status")["device"]["name"] == "Lab Static DHCP stream"


# --- per-stream purge ----------------------------------------------------------------------


def test_stream_purge_clears_every_entry_of_the_stream_in_one_batch(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=3)
    with app.app_context():
        other, other_check = _entry("other")
        _sync(pub, app)
    node = _node(app)
    state, discovery = _entry_topics(app, ids)
    mine = state | discovery | {"std/stream/dhcp"} | {
        f"homeassistant/sensor/{node}/stream_dhcp_{p}/config" for p in ("status", "active", "missing")}
    client.published.clear()

    with app.app_context():
        result = notify_purge.purge_stream(pub, sid)

    assert _cleared(client) == mine
    published = set(_sent(client))
    assert published <= mine and {"std/stream/dhcp", *(f"std/entry/{e}/state" for e in ids)} <= published
    log = client.published
    cleared_at = [i for i, (t, p, _q, r) in enumerate(log) if p == ""]
    resent_at = [i for i, (t, p, _q, r) in enumerate(log) if p != ""]
    assert max(cleared_at) < min(resent_at)                              # clear first, republish after
    assert not any(f"/{other}/" in t or f"entry_{other}_" in t for t, *_ in log)
    assert result == {"stream_id": "dhcp", "entries": 3, "topics_cleared": len(mine), "republished": True,
                      "channels": [{"id": _first_channel(app), "name": "ha",
                                    "state_topics": len(state) + 1, "discovery_topics": len(discovery) + 3}]}


def test_stream_purge_of_a_disabled_stream_brings_nothing_back(app, factory):
    pub, client = _setup(app, factory)
    sid, ids = _stream(app, n=2)
    with app.app_context():
        _sync(pub, app)
        for eid in ids:                                    # what disable + soft_delete does
            db.session.get(ServiceEntry, eid).deleted_at = datetime.now()
        db.session.get(InventoryStream, sid).status = "disabled"
        db.session.commit()
        client.published.clear()
        notify_purge.purge_stream(pub, sid)
    state, discovery = _entry_topics(app, ids)
    assert state | discovery <= _cleared(client)                          # soft-deleted entries are cleared too
    assert set(_sent(client)) == {"std/stream/dhcp", "std/summary"}      # the (disabled) status and the new summary
    assert json.loads(_sent(client)["std/stream/dhcp"])["status"] == "disabled"


def test_stream_purge_clears_every_channel_and_needs_one(app, factory):
    pub = notify.get_publisher()
    sid, ids = _stream(app)
    with app.app_context(), pytest.raises(notify_purge.PurgeError) as exc:
        notify_purge.purge_stream(pub, sid)
    assert exc.value.status == 409
    _add(app, name="a", config=HA_CFG)
    _add(app, name="b", config={**HA_CFG, "base_topic": "other"})
    pub.reload_now(app)
    with app.app_context():
        result = notify_purge.purge_stream(pub, sid)
    assert sorted(c["name"] for c in result["channels"]) == ["a", "b"]
    assert "std/stream/dhcp" in _cleared(factory.clients[0]) and "other/stream/dhcp" in _cleared(factory.clients[1])


def test_api_stream_purge(app, client, wkey, running):
    cid, broker = running
    sid, ids = _stream(app)
    resp = client.post("/api/v1/streams/dhcp/notifications/purge", headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["stream_id"] == "dhcp" and body["entries"] == 2 and body["republished"] is True
    assert body["channels"][0]["id"] == cid and body["topics_cleared"] >= 8
    assert f"std/entry/{ids[0]}/state" in _cleared(broker) and "std/stream/dhcp" in _cleared(broker)
    assert client.post("/api/v1/streams/nope/notifications/purge", headers=wkey).status_code == 404


def test_api_stream_purge_scope_and_no_channel(app, client, wkey, rkey):
    assert client.post("/api/v1/streams/dhcp/notifications/purge", headers=rkey).status_code == 403
    assert client.post("/api/v1/streams/dhcp/notifications/purge").status_code == 401
    _stream(app)
    pub = notify.get_publisher()
    pub.start(app)
    try:
        assert client.post("/api/v1/streams/dhcp/notifications/purge", headers=wkey).status_code == 409
    finally:
        pub.stop()


def test_ui_stream_purge_and_button(app, admin_client, monkeypatch):
    _stream(app)
    assert b"stream-notify-purge" not in admin_client.get("/settings?section=streams").data
    _add(app)
    assert b"stream-notify-purge" in admin_client.get("/settings?section=streams").data
    calls = []
    monkeypatch.setattr(notify, "purge_stream", lambda pk: calls.append(pk) or {
        "stream_id": "dhcp", "entries": 2, "topics_cleared": 5, "channels": [], "republished": True})
    resp = admin_client.post("/settings/streams/dhcp/purge-notifications")
    assert resp.get_json()["ok"] is True and resp.get_json()["entries"] == 2 and len(calls) == 1
    assert admin_client.post("/settings/streams/nope/purge-notifications").status_code == 404


def test_ui_stream_purge_is_admin_only(app, client):
    _stream(app)
    assert client.post("/settings/streams/dhcp/purge-notifications").status_code in (302, 401)


# --- channel delete / disable cleanup --------------------------------------------------------


def test_purge_for_removal_clears_status_last_and_stop_does_not_republish_offline(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    client.retained = [("std/status", "online"), ("std/summary", "{}")]
    client.published.clear()
    with app.app_context():
        result = notify_purge.purge_channel(pub, _first_channel(app), republish=False, clear_status=True)
    assert [t for t, *_ in client.published][-1] == "std/status"        # cleared last
    assert "std/status" in _cleared(client) and "std/summary" in _cleared(client)
    assert result["republished"] is False
    client.published.clear()
    pub.apply_specs([], "x")                                           # the channel is gone: the session stops
    assert client.disconnected and not any(p == "offline" for _t, p, *_r in client.published)


def test_a_plain_stop_still_publishes_offline(app, factory):
    pub, client = _setup(app, factory)
    client.published.clear()
    pub.apply_specs([], "x")
    assert ("std/status", "offline", 1, True) in client.published


def test_api_delete_cleans_the_broker_first(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/summary", "{}"), ("std/entry/1/state", "{}"), ("std/status", "online")]
    broker.published.clear()
    resp = client.delete(f"/api/v1/notifications/channels/{cid}", headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["id"] == cid and body["deleted"] is True
    assert body["cleanup"]["state_topics"] == 2 and body["cleanup"]["topics_cleared"] == 2
    assert {"std/summary", "std/entry/1/state", "std/status"} <= _cleared(broker)
    with app.app_context():
        assert db.session.get(NotificationChannel, cid) is None
    pub = notify.get_publisher()
    _wait(lambda: pub.session_status(cid) is None)
    assert not any(p == "offline" for _t, p, *_r in broker.published)  # nothing re-created the status topic


def test_api_delete_with_cleanup_false_leaves_the_broker_alone(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/summary", "{}")]
    broker.published.clear()
    resp = client.delete(f"/api/v1/notifications/channels/{cid}?cleanup=false", headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["cleanup"] is None
    assert _cleared(broker) == set()
    assert client.delete(f"/api/v1/notifications/channels/{cid}?cleanup=maybe", headers=wkey).status_code in (400, 404)


def test_api_delete_refuses_when_the_broker_is_unreachable_and_deletes_anyway_on_request(
        app, client, wkey, running, factory):
    _cid, _broker = running
    factory.client_kwargs["outcome"] = "unreachable"
    down = _add(app, name="down", config={"host": "gone.lan"})
    pub = notify.get_publisher()
    pub.request_reload()
    _wait(lambda: (pub.session_status(down) or {}).get("state") == "error")
    resp = client.delete(f"/api/v1/notifications/channels/{down}", headers=wkey)
    assert resp.status_code == 409 and "not connected" in resp.get_json()["error"]
    with app.app_context():
        assert db.session.get(NotificationChannel, down) is not None   # nothing was deleted
    assert client.delete(f"/api/v1/notifications/channels/{down}?cleanup=false", headers=wkey).status_code == 200
    with app.app_context():
        assert db.session.get(NotificationChannel, down) is None


def test_api_delete_of_a_disabled_channel_needs_cleanup_false(app, client, wkey, running):
    off = _add(app, name="off", enabled=False)
    resp = client.delete(f"/api/v1/notifications/channels/{off}", headers=wkey)
    assert resp.status_code == 409
    assert client.delete(f"/api/v1/notifications/channels/{off}?cleanup=false", headers=wkey).status_code == 200


def test_api_disable_cleanup_is_opt_in(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/summary", "{}")]
    broker.published.clear()
    resp = client.patch(f"/api/v1/notifications/channels/{cid}", json={"enabled": False}, headers=wkey)
    assert resp.status_code == 200 and _cleared(broker) == set()       # default: leave the broker alone
    client.patch(f"/api/v1/notifications/channels/{cid}", json={"enabled": True}, headers=wkey)
    pub = notify.get_publisher()
    _wait(lambda: pub.session_status(cid) is not None and pub.session_status(cid)["state"] == "connected")
    broker2 = [c for c in notify_factory_clients(pub, cid)][-1]
    broker2.retained = [("std/summary", "{}"), ("std/status", "online")]
    broker2.published.clear()
    resp = client.patch(f"/api/v1/notifications/channels/{cid}", json={"enabled": False, "cleanup": True},
                        headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["enabled"] is False
    assert "std/summary" in _cleared(broker2)
    assert "std/status" not in _cleared(broker2)                         # reads offline, not removed


def notify_factory_clients(pub, cid):
    return [s._client for c, s in pub.sessions() if c == cid]


def test_api_disable_cleanup_refuses_an_unreachable_broker(app, client, wkey, running, factory):
    _cid, _broker = running
    factory.client_kwargs["outcome"] = "unreachable"
    down = _add(app, name="down", config={"host": "gone.lan"})
    pub = notify.get_publisher()
    pub.request_reload()
    _wait(lambda: (pub.session_status(down) or {}).get("state") == "error")
    resp = client.patch(f"/api/v1/notifications/channels/{down}", json={"enabled": False, "cleanup": True},
                        headers=wkey)
    assert resp.status_code == 409
    with app.app_context():
        assert db.session.get(NotificationChannel, down).enabled is True
    assert client.patch(f"/api/v1/notifications/channels/{down}", json={"enabled": False},
                        headers=wkey).status_code == 200


def test_patch_with_only_cleanup_is_rejected(app, client, wkey, running):
    cid, _broker = running
    assert client.patch(f"/api/v1/notifications/channels/{cid}", json={"cleanup": True},
                        headers=wkey).status_code == 400


def test_ui_delete_and_disable_forms(app, admin_client, monkeypatch):
    cid = _add(app, enabled=False)
    calls = []
    real = notify.delete_channel
    monkeypatch.setattr(notify, "delete_channel", lambda ch, cleanup=False: calls.append(cleanup) or real(ch))
    resp = admin_client.post(f"/settings/notifications/{cid}/delete", data={"cleanup": "1"},
                             headers={"Accept": "application/json"})
    assert resp.get_json()["ok"] is True and calls == [True]
    with app.app_context():
        assert NotificationChannel.query.count() == 0


def test_ui_delete_reports_an_unreachable_broker_and_keeps_the_channel(app, admin_client):
    cid = _add(app, enabled=False)
    resp = admin_client.post(f"/settings/notifications/{cid}/delete", data={"cleanup": "1"},
                             headers={"Accept": "application/json"})
    body = resp.get_json()
    assert resp.status_code == 409 and body["ok"] is False and body["message"]
    with app.app_context():
        assert NotificationChannel.query.count() == 1
    resp = admin_client.post(f"/settings/notifications/{cid}/delete", data={"cleanup": "0"},
                             headers={"Accept": "application/json"})
    assert resp.get_json()["ok"] is True
    with app.app_context():
        assert NotificationChannel.query.count() == 0


def test_ui_disable_with_cleanup_passes_the_choice(app, admin_client, monkeypatch):
    cid = _add(app)
    seen = []
    real = notify.update_channel
    monkeypatch.setattr(notify, "update_channel",
                        lambda ch, **kw: seen.append(kw.get("cleanup_disable")) or real(ch, **kw))
    # Unticked (the default): plain disable, no broker work.
    resp = admin_client.post(f"/settings/notifications/{cid}/toggle")
    assert resp.status_code == 302 and seen == [False]
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).enabled is False


def test_ui_disable_with_cleanup_on_an_unreachable_channel_is_a_409_json(app, admin_client):
    cid = _add(app)                                     # enabled, but no publisher is running
    resp = admin_client.post(f"/settings/notifications/{cid}/toggle", data={"cleanup": "1"},
                             headers={"Accept": "application/json"})
    assert resp.status_code == 409 and resp.get_json()["ok"] is False
    with app.app_context():
        assert db.session.get(NotificationChannel, cid).enabled is True


def test_ui_buttons_render(app, admin_client):
    _add(app)
    page = admin_client.get("/settings").get_data(as_text=True)
    assert 'data-channel-remove="delete"' in page and 'data-channel-remove="disable"' in page
    assert "data-notification-orphans" in page and 'id="nf-cleanup-row"' in page


# --- base topic / prefix change ----------------------------------------------------------------


def test_clear_old_namespace_for_a_base_change(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    node = _node(app)
    client.retained = [("std/summary", "{}"), ("std/entry/77/state", "{}"), ("std/status", "online"),
                       (f"homeassistant/sensor/{node}/entry_77_state/config", "{}")]
    client.published.clear()
    new = {**pub.sessions()[0][1].config, "base_topic": "std2"}
    with app.app_context():
        result = notify_purge.clear_old_namespace(pub, _first_channel(app), new)
    cleared = _cleared(client)
    assert {"std/summary", "std/entry/77/state", "std/status"} <= cleared      # old status too
    assert not any(t.startswith("homeassistant/") for t in cleared)           # prefix unchanged: configs stay
    assert ("std/#", 1) in client.subscriptions and not any(t.startswith("homeassistant/+") for t, _ in client.subscriptions)
    assert result["discovery_topics"] == 0 and result["state_topics"] == len(cleared)
    client.published.clear()
    pub.apply_specs([], "x")
    assert not any(p == "offline" for _t, p, *_r in client.published)           # not on the old status topic


def test_clear_old_namespace_for_a_discovery_prefix_change(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    mine = {t for t in _sent(client) if t.startswith("homeassistant/")}
    node = _node(app)
    client.retained = [(f"homeassistant/sensor/{node}/entry_77_state/config", "{}"),
                       ("homeassistant/sensor/std_deadbeef/entry_1_state/config", "{}")]
    client.published.clear()
    new = {**pub.sessions()[0][1].config, "ha_prefix": "ha"}
    with app.app_context():
        notify_purge.clear_old_namespace(pub, _first_channel(app), new)
    cleared = _cleared(client)
    assert f"homeassistant/sensor/{node}/entry_77_state/config" in cleared
    assert "homeassistant/sensor/std_deadbeef/entry_1_state/config" not in cleared   # another install
    assert mine <= cleared and not any(t.startswith("std/") for t in cleared)
    assert pub.state.ha_topics == {}


def test_clear_old_namespace_for_a_device_prefix_change_clears_the_configs_to_republish(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    mine = {t for t in _sent(client) if t.startswith("homeassistant/")}
    client.published.clear()
    new = {**pub.sessions()[0][1].config, "ha_device_prefix": "Lab"}
    with app.app_context():
        notify_purge.clear_old_namespace(pub, _first_channel(app), new)
    assert mine <= _cleared(client)


def test_nothing_to_clean_when_nothing_changed(app, factory):
    pub, client = _setup(app, factory)
    client.published.clear()
    client.subscriptions.clear()
    with app.app_context():
        result = notify_purge.clear_old_namespace(pub, _first_channel(app), dict(pub.sessions()[0][1].config))
    assert result["topics_cleared"] == 0 and client.published == [] and client.subscriptions == []


def test_namespace_change_rules():
    base = {"base_topic": "std", "ha_prefix": "homeassistant", "ha_device_prefix": "STD", "ha_discovery": True}
    assert notify_purge.namespace_change(base, {**base}) == (False, False)
    assert notify_purge.namespace_change(base, {**base, "base_topic": "x"}) == (True, False)
    assert notify_purge.namespace_change(base, {**base, "ha_prefix": "x"}) == (False, True)
    assert notify_purge.namespace_change(base, {**base, "ha_device_prefix": "x"}) == (False, True)
    off = {**base, "ha_discovery": False}
    assert notify_purge.namespace_change(off, {**off, "ha_prefix": "x", "ha_device_prefix": "y"}) == (False, False)


def test_api_patch_base_topic_cleans_the_old_base_and_remembers_it(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/entry/9/state", "{}"), ("std/status", "online")]
    broker.published.clear()
    resp = client.patch(f"/api/v1/notifications/channels/{cid}", json={"config": {"base_topic": "std2"}},
                        headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["config"]["base_topic"] == "std2"
    assert {"std/entry/9/state", "std/status"} <= _cleared(broker)
    prev = client.get(f"/api/v1/notifications/channels/{cid}/previous-bases", headers=wkey).get_json()
    assert prev == {"channel_id": cid, "limit": 5, "items": [{"base_topic": "std", "ha_prefix": "homeassistant"}]}


def test_api_patch_base_topic_without_cleanup_only_remembers(app, client, wkey, running):
    cid, broker = running
    broker.retained = [("std/entry/9/state", "{}")]
    broker.published.clear()
    resp = client.patch(f"/api/v1/notifications/channels/{cid}",
                        json={"config": {"base_topic": "std2"}, "cleanup": False}, headers=wkey)
    assert resp.status_code == 200 and _cleared(broker) == set()
    prev = client.get(f"/api/v1/notifications/channels/{cid}/previous-bases", headers=wkey).get_json()
    assert prev["items"] == [{"base_topic": "std", "ha_prefix": "homeassistant"}]


def test_api_patch_cleanup_error_changes_nothing(app, client, wkey, running, factory):
    _cid, _broker = running
    factory.client_kwargs["outcome"] = "unreachable"
    down = _add(app, name="down", config={"host": "gone.lan"})
    pub = notify.get_publisher()
    pub.request_reload()
    _wait(lambda: (pub.session_status(down) or {}).get("state") == "error")
    resp = client.patch(f"/api/v1/notifications/channels/{down}", json={"config": {"base_topic": "x"}},
                        headers=wkey)
    assert resp.status_code == 409
    with app.app_context():
        assert db.session.get(NotificationChannel, down).config["base_topic"] == "std"
        assert notify.previous_bases(down) == []
    assert client.patch(f"/api/v1/notifications/channels/{down}",
                        json={"config": {"base_topic": "x"}, "cleanup": False}, headers=wkey).status_code == 200


def test_a_disabled_channel_skips_the_base_change_cleanup_but_remembers(app):
    cid = _add(app, enabled=False)
    with app.app_context():
        channel, errors = notify.update_channel(db.session.get(NotificationChannel, cid),
                                                config={"base_topic": "new"}, cleanup_old_base=True)
        assert not errors and notify.previous_bases(cid) == [{"base_topic": "std", "ha_prefix": "homeassistant"}]


def test_remembered_bases_keep_the_last_five_newest_first(app):
    cid = _add(app, enabled=False)
    with app.app_context():
        channel = db.session.get(NotificationChannel, cid)
        for name in ["a", "b", "c", "d", "e", "f", "g"]:
            notify.update_channel(channel, config={"base_topic": name})
        assert [p["base_topic"] for p in notify.previous_bases(cid)] == ["f", "e", "d", "c", "b"]
        notify.update_channel(channel, config={"base_topic": "c"})         # back to an old one: not "previous" now
        assert [p["base_topic"] for p in notify.previous_bases(cid)] == ["g", "f", "e", "d", "b"]
        notify.update_channel(channel, name="renamed")                        # nothing remembered
        assert len(notify.previous_bases(cid)) == 5
        notify.delete_channel(channel)
        assert notify.previous_bases(cid) == []


def test_a_prefix_change_is_remembered_with_its_prefix(app):
    cid = _add(app, enabled=False, config={**HA_CFG, "ha_prefix": "ha1"})
    with app.app_context():
        notify.update_channel(db.session.get(NotificationChannel, cid), config={"ha_prefix": "ha2"})
        assert notify.previous_bases(cid) == [{"base_topic": "std", "ha_prefix": "ha1"}]


def test_ui_save_base_change_reports_a_cleanup_failure_then_saves_without_it(app, admin_client, factory):
    from tests.test_notifications import FORM
    admin_client.post("/settings/notifications/save", data=FORM)
    with app.app_context():
        cid = NotificationChannel.query.one().id
    notify.get_publisher().reload_now(app)                  # a live session, but no publisher thread
    data = {**FORM, "channel_id": str(cid), "base_topic": "std2", "password": "", "cleanup_old_base": "1"}
    resp = admin_client.post("/settings/notifications/save", data=data)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 409 and "Nothing was saved" in html and "Remove the old topics" in html
    with app.app_context():
        assert NotificationChannel.query.one().config["base_topic"] == "std"
    data.pop("cleanup_old_base")
    resp = admin_client.post("/settings/notifications/save", data=data)
    assert resp.status_code == 302
    with app.app_context():
        assert NotificationChannel.query.one().config["base_topic"] == "std2"
        assert notify.previous_bases(cid)[0]["base_topic"] == "std"


# --- orphan scan ------------------------------------------------------------------------------


def _orphan_setup(app, factory):
    """A synced entry, a remembered previous base `old`, and a broker that holds STD's
    own topics plus assorted leftovers. Returns `(pub, client, node, orphans)`."""
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
        notify_purge.remember_base(_first_channel(app), {"base_topic": "old", "ha_prefix": "homeassistant"},
                                   {"base_topic": "std", "ha_prefix": "homeassistant"})
        db.session.commit()
    node = _node(app)
    mine = [(t, "{}") for t in _sent(client)] + [("std/status", "online")]
    orphans = {
        "std/entry/999/state": "state",                                         # a deleted entry, never tracked
        "std/entry/999/check/5": "state",
        f"homeassistant/sensor/{node}/entry_999_state/config": "discovery",
        "old/entry/5/state": "state",                                          # previous base
        "old/status": "state",
        "legacy/summary": "state",                                             # the operator-typed base
    }
    ignored = [("std/other/thing", "x"),                                       # not STD-shaped
               ("old/notes", "x"),
               ("homeassistant/sensor/std_deadbeef/entry_1_state/config", "{}"),  # another install
               ("homeassistant/sensor/kitchen/temp/config", "{}"),
               ("elsewhere/summary", "{}")]                                    # a base nobody asked about
    client.retained = mine + [(t, "{}") for t in orphans] + ignored
    client.published.clear()
    client.subscriptions.clear()
    return pub, client, node, orphans


def test_scan_lists_only_what_nothing_desires(app, factory):
    pub, client, node, orphans = _orphan_setup(app, factory)
    with app.app_context():
        result = notify_purge.scan_orphans(pub, _first_channel(app), extra_base="legacy")
    assert {o["topic"]: o["kind"] for o in result["orphans"]} == orphans
    assert result["count"] == len(orphans)
    assert result["scanned"] == ["std/#", "old/#", "legacy/#", f"homeassistant/+/{node}/#"]
    assert client.published == []                                                # a preview publishes nothing
    assert sorted(t for t, _q in client.subscriptions) == sorted(result["scanned"])
    assert sorted(client.unsubscribed) == sorted(result["scanned"])


def test_scan_without_extra_base_or_orphans(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    client.retained = [(t, "{}") for t in _sent(client)] + [("std/status", "online")]
    with app.app_context():
        result = notify_purge.scan_orphans(pub, _first_channel(app))
    assert result["count"] == 0 and result["orphans"] == []


def test_scan_treats_other_live_topics_as_desired_including_streams(app, factory):
    pub, client = _setup(app, factory)
    _stream(app)
    with app.app_context():
        _sync(pub, app)
    client.retained = [(t, "{}") for t in _sent(client)] + [("std/status", "online"),
                                                           ("std/stream/gone", "{}")]
    with app.app_context():
        result = notify_purge.scan_orphans(pub, _first_channel(app))
    assert [o["topic"] for o in result["orphans"]] == ["std/stream/gone"]


def test_scan_does_not_call_a_sibling_channels_topics_orphans(app, factory):
    pub, first = _setup(app, factory)
    _add(app, name="second", config={**HA_CFG, "base_topic": "other"})
    pub.reload_now(app)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
        notify_purge.remember_base(_first_channel(app), {"base_topic": "other", "ha_prefix": "homeassistant"},
                                   {"base_topic": "std", "ha_prefix": "homeassistant"})
        db.session.commit()
    first.retained = [(t, "{}") for t in _sent(factory.clients[1])] + [("other/status", "online")]
    with app.app_context():
        result = notify_purge.scan_orphans(pub, _first_channel(app))
    assert result["count"] == 0                      # `other/` belongs to a channel on the same broker


def test_scan_validates_the_extra_base(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        for bad in ("a/+", "#", "/x", "a//b", "$SYS", "x" * 200, 5):
            with pytest.raises(notify_purge.PurgeError) as exc:
                notify_purge.scan_orphans(pub, _first_channel(app), extra_base=bad)
            assert exc.value.status == 400
        with pytest.raises(notify_purge.PurgeError) as exc:
            notify_purge.scan_orphans(pub, _first_channel(app), extra_base="homeassistant")   # the discovery prefix
        assert exc.value.status == 400
        assert notify_purge.clean_extra_base("  ") is None and notify_purge.clean_extra_base("old/") == "old"


def test_scan_needs_a_connected_channel(app, factory):
    _add(app, enabled=False)
    pub = notify.get_publisher()
    pub.reload_now(app)
    with app.app_context(), pytest.raises(notify_purge.PurgeError) as exc:
        notify_purge.scan_orphans(pub, _first_channel(app))
    assert exc.value.status == 409


def test_clear_given_orphans_only_clears_those_that_still_qualify(app, factory):
    pub, client, node, orphans = _orphan_setup(app, factory)
    desired = next(t for t, _p in client.retained if t == "std/summary")
    asked = ["std/entry/999/state", "old/entry/5/state", desired, "elsewhere/summary", "std/other/thing"]
    with app.app_context():
        result = notify_purge.clear_orphans(pub, _first_channel(app), topics=asked)
    assert _cleared(client) == {"std/entry/999/state", "old/entry/5/state"}
    assert result["topics_cleared"] == 2 and sorted(result["topics"]) == ["old/entry/5/state", "std/entry/999/state"]
    assert sorted(result["skipped"]) == sorted([desired, "elsewhere/summary", "std/other/thing"])
    assert client.subscriptions == []                                              # no scan for an explicit list


def test_clear_without_a_list_rescans_and_clears_everything(app, factory):
    pub, client, node, orphans = _orphan_setup(app, factory)
    with app.app_context():
        result = notify_purge.clear_orphans(pub, _first_channel(app), extra_base="legacy")
    assert _cleared(client) == set(orphans)
    assert result["topics_cleared"] == len(orphans) and result["skipped"] == []


def test_clear_orphans_drops_cleared_discovery_topics_from_the_tracking(app, factory):
    pub, client, node, orphans = _orphan_setup(app, factory)
    stale = f"homeassistant/sensor/{node}/entry_999_state/config"
    pub.state.ha_topics.setdefault(str(_first_channel(app)), set()).add(stale)
    with app.app_context():
        notify_purge.clear_orphans(pub, _first_channel(app), topics=[stale])
    assert stale not in pub.state.ha_topics.get(str(_first_channel(app)), set())


def test_api_orphan_scan_and_clear(app, client, wkey, running):
    cid, broker = running
    node = _node(app)
    leftover = f"homeassistant/sensor/{node}/entry_999_state/config"
    broker.retained = [("std/entry/999/state", "{}"), (leftover, "{}"), ("std/status", "online")]
    resp = client.post(f"/api/v1/notifications/channels/{cid}/orphans/scan", headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["count"] == 2 and {o["topic"] for o in body["orphans"]} == {"std/entry/999/state", leftover}
    assert _cleared(broker) == set()                                              # a preview
    resp = client.post(f"/api/v1/notifications/channels/{cid}/orphans/clear",
                       json={"topics": [o["topic"] for o in body["orphans"]]}, headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["topics_cleared"] == 2
    assert _cleared(broker) == {"std/entry/999/state", leftover}
    resp = client.post(f"/api/v1/notifications/channels/{cid}/orphans/clear", headers=wkey)    # re-scan mode
    assert resp.status_code == 200 and resp.get_json()["topics_cleared"] == 2


def test_api_orphan_errors_and_scopes(app, client, wkey, rkey, running):
    cid, _broker = running
    url = f"/api/v1/notifications/channels/{cid}/orphans"
    assert client.post("/api/v1/notifications/channels/999/orphans/scan", headers=wkey).status_code == 404
    assert client.post(url + "/scan", json={"extra_base": "a/+"}, headers=wkey).status_code == 400
    assert client.post(url + "/scan", json={"surprise": 1}, headers=wkey).status_code == 400
    assert client.post(url + "/clear", json={"topics": "std/x"}, headers=wkey).status_code == 400
    off = _add(app, name="off", enabled=False)
    assert client.post(f"/api/v1/notifications/channels/{off}/orphans/scan", headers=wkey).status_code == 409
    assert client.post(url + "/scan", headers=rkey).status_code == 403
    assert client.post(url + "/clear", headers=rkey).status_code == 403
    assert client.get(f"/api/v1/notifications/channels/{cid}/previous-bases", headers=rkey).status_code == 200
    assert client.get("/api/v1/notifications/channels/999/previous-bases", headers=rkey).status_code == 404
    assert client.get(f"/api/v1/notifications/channels/{cid}/previous-bases").status_code == 401


def test_ui_orphan_routes(app, admin_client, monkeypatch):
    cid = _add(app)
    calls = []
    monkeypatch.setattr(notify, "scan_orphans", lambda c, extra: calls.append(("scan", c, extra)) or {
        "channel_id": c, "scanned": [], "count": 1, "orphans": [{"topic": "std/entry/9/state", "kind": "state"}]})
    monkeypatch.setattr(notify, "clear_orphans", lambda c, topics, extra: calls.append(("clear", c, topics, extra)) or {
        "channel_id": c, "topics_cleared": len(topics), "topics": topics, "skipped": []})
    resp = admin_client.post(f"/settings/notifications/{cid}/orphans/scan", data={"extra_base": " old "})
    assert resp.get_json()["ok"] is True and resp.get_json()["count"] == 1
    resp = admin_client.post(f"/settings/notifications/{cid}/orphans/clear",
                             data={"topic": ["std/entry/9/state", "std/entry/8/state"], "extra_base": ""})
    assert resp.get_json()["topics_cleared"] == 2
    assert calls == [("scan", cid, "old"), ("clear", cid, ["std/entry/9/state", "std/entry/8/state"], None)]
    assert admin_client.post("/settings/notifications/999/orphans/scan").status_code == 404


def test_ui_orphan_routes_are_admin_only(app, client):
    cid = _add(app)
    assert client.post(f"/settings/notifications/{cid}/orphans/scan").status_code in (302, 401)
    assert client.post(f"/settings/notifications/{cid}/orphans/clear").status_code in (302, 401)


# --- registry ------------------------------------------------------------------------------------


def test_every_new_route_is_in_the_openapi_registry():
    declared = {(op.method, op.path): op.scope for op in mgmt_openapi.OPERATIONS}
    assert declared[("GET", "/notifications/channels/{id}/previous-bases")] == "read"
    for method, path in (("POST", "/notifications/channels/{id}/orphans/scan"),
                         ("POST", "/notifications/channels/{id}/orphans/clear"),
                         ("POST", "/streams/{stream_id}/notifications/purge")):
        assert declared[(method, path)] == "write"


def test_openapi_documents_the_cleanup_options(app, client):
    doc = client.get("/api/v1/openapi.json").get_json()
    delete = doc["paths"]["/notifications/channels/{id}"]["delete"]
    assert [p["name"] for p in delete["parameters"] if p["in"] == "query"] == ["cleanup"]
    patch = doc["paths"]["/notifications/channels/{id}"]["patch"]
    schema = patch["requestBody"]["content"]["application/json"]["schema"]
    assert "cleanup" in doc["components"]["schemas"][schema["$ref"].rsplit("/", 1)[1]]["properties"]


def test_hub_helpers():
    assert notify_ha.stream_device_id("std_ab", "dhcp") == "std_ab_stream_dhcp"
    assert notify_state.stream_topic("dhcp") == "stream/dhcp"
