"""Home Assistant MQTT discovery (PRD 17.4). Uses the fake paho client from
tests/test_notifications.py; no thread, no socket."""

import json
import sqlite3
from datetime import datetime

import pytest

import notify
import notify_ha
import settings_store
from extensions import db
from models import HealthCheck, ServiceEntry
from tests.test_notifications import Factory, _add, _alembic
from tests.test_state_publishing import _entry, _result, _sync

HA_CFG = {"host": "mqtt.lan", "ha_discovery": True}
REV = "d8e2a6f4b915"
PREVIOUS = "a2f4c6e8b031"


@pytest.fixture
def factory():
    fake = Factory()
    notify.set_client_factory(fake)
    return fake


def _setup(app, factory, **config):
    _add(app, config={**HA_CFG, **config})
    pub = notify.get_publisher()
    pub.reload_now(app)
    client = factory.clients[0]
    client.published.clear()
    return pub, client


def _configs(client, prefix="homeassistant"):
    """discovery topic -> payload text (latest) for everything under the prefix."""
    out = {}
    for topic, payload, _q, retain in client.published:
        if topic.startswith(prefix + "/") and topic.endswith("/config"):
            assert retain
            out[topic] = payload
    return out


def _node(app):
    with app.app_context():
        return notify_ha.node_id(settings_store.get_instance_id())


def _cfg(client, node, component, object_id, prefix="homeassistant"):
    return json.loads(_configs(client, prefix)[f"{prefix}/{component}/{node}/{object_id}/config"])


# --- payload shape -------------------------------------------------------------------


def test_config_payload_shape(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("web")
        db.session.get(ServiceEntry, eid).image_tag = "1.2.3"
        db.session.commit()
        _sync(pub, app)
    node = _node(app)

    hub = _cfg(client, node, "binary_sensor", "hub_connectivity")
    assert hub["device"] == {"identifiers": [node], "name": "STD", "manufacturer": "Service Tracker Dashboard",
                             "model": "STD", "sw_version": hub["device"]["sw_version"]}
    assert hub["state_topic"] == "std/status" and hub["device_class"] == "connectivity"
    assert "availability_topic" not in hub
    count = _cfg(client, node, "sensor", "hub_down")
    assert count["state_topic"] == "std/summary" and count["value_template"] == "{{ value_json.down }}"
    assert count["availability_topic"] == "std/status"

    state = _cfg(client, node, "sensor", f"entry_{eid}_state")
    assert state["unique_id"] == f"{node}_entry_{eid}_state"
    assert state["device_class"] == "enum" and state["options"] == ["up", "degraded", "down", "unknown", "none"]
    assert state["state_topic"] == f"std/entry/{eid}/state" == state["json_attributes_topic"]
    assert state["availability_topic"] == "std/status"
    assert state["default_entity_id"] == "sensor.std_web_state"
    assert "object_id" not in state
    device = state["device"]
    assert device["identifiers"] == [f"{node}_entry_{eid}"] and device["via_device"] == node
    assert device["name"] == "STD web" and device["manufacturer"] == "Service Tracker Dashboard"
    assert device["model"] == "Manual" and device["sw_version"] == "1.2.3"
    assert "suggested_area" not in device

    check = _cfg(client, node, "binary_sensor", f"check_{cid}")
    assert check["unique_id"] == f"{node}_check_{cid}"
    assert check["device_class"] == "problem" and check["payload_on"] == "ON"
    assert check["state_topic"] == f"std/entry/{eid}/check/{cid}" == check["json_attributes_topic"]
    assert check["availability_topic"] == "std/status" and check["device"] == device
    assert check["default_entity_id"].startswith("binary_sensor.std_web_")


def test_configs_are_published_before_states(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    topics = [t for t, *_x in client.published]
    last_config = max(i for i, t in enumerate(topics) if t.endswith("/config"))
    first_state = min(i for i, t in enumerate(topics) if t.startswith("std/"))
    assert last_config < first_state


def test_custom_prefixes(app, factory):
    pub, client = _setup(app, factory, ha_prefix="ha", ha_device_prefix="Lab")
    with app.app_context():
        eid, _ = _entry("web")
        _sync(pub, app)
    node = _node(app)
    state = _cfg(client, node, "sensor", f"entry_{eid}_state", prefix="ha")
    assert state["device"]["name"] == "Lab web" and state["default_entity_id"] == "sensor.lab_web_state"
    assert _cfg(client, node, "binary_sensor", "hub_connectivity", prefix="ha")["device"]["name"] == "Lab"
    assert not _configs(client, "homeassistant")


def test_state_payloads_carry_the_filter_attributes(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("web")
        _result(cid, True)
        notify.publish_changes([cid])
        pub.drain()
    sent = {t: json.loads(p) for t, p, *_x in client.published}
    check = sent[f"std/entry/{eid}/check/{cid}"]
    for key in ("std_entry_id", "host", "group", "source", "check_type", "target", "latency_ms",
                "message", "last_change", "dashboard_url"):
        assert key in check, key
    assert check["std_entry_id"] == eid
    entry = sent[f"std/entry/{eid}/state"]
    for key in ("std_entry_id", "host", "group", "source", "dashboard_url"):
        assert key in entry, key


# --- lifecycle -----------------------------------------------------------------------


def test_discovery_off_publishes_no_configs(app, factory):
    pub, client = _setup(app, factory, ha_discovery=False)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
    assert not _configs(client)
    assert client.subscriptions == []


def test_new_check_auto_publishes(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("web")
        _sync(pub, app)
        client.published.clear()
        entry = db.session.get(ServiceEntry, eid)
        entry.checks.append(HealthCheck(kind="service", name="TCP 443", check_type="tcp",
                                        target="h:443", enabled=True))
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
        new_id = max(c.id for c in db.session.get(ServiceEntry, eid).checks)
    node = _node(app)
    cfg = _cfg(client, node, "binary_sensor", f"check_{new_id}")
    assert cfg["name"] == "TCP 443"


def test_new_entry_auto_publishes(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _sync(pub, app)
        client.published.clear()
        eid, _ = _entry("fresh")
        assert pub.sync_pending()
        pub.run_sync_now(app)
    assert f"homeassistant/sensor/{_node(app)}/entry_{eid}_state/config" in _configs(client)


def _cleared(client):
    return {t for t, payload, _q, retain in client.published if payload == "" and retain}


def test_entry_opt_out_clears_its_configs(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, cid = _entry("web")
        other, ocid = _entry("keep")
        _sync(pub, app)
        client.published.clear()
        db.session.get(ServiceEntry, eid).ha_exclude = True
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
    pfx = f"homeassistant/%s/{node}/%s/config"
    assert _cleared(client) == {pfx % ("sensor", f"entry_{eid}_state"), pfx % ("binary_sensor", f"check_{cid}")}
    # the state topics are still published: ha_exclude only affects discovery
    assert not any(t.startswith("std/") and p == "" for t, p, *_x in client.published)


def test_check_opt_out_clears_only_that_check(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, cid = _entry("web")
        _sync(pub, app)
        client.published.clear()
        db.session.get(HealthCheck, cid).ha_exclude = True
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
    assert _cleared(client) == {f"homeassistant/binary_sensor/{node}/check_{cid}/config"}


def test_delete_soft_delete_and_purge_clear_configs(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        e1, c1 = _entry("a")
        e2, c2 = _entry("b")
        _sync(pub, app)
        client.published.clear()
        db.session.get(ServiceEntry, e1).deleted_at = datetime.now()
        db.session.commit()
        pub.run_sync_now(app)
        soft = _cleared(client)
        client.published.clear()
        db.session.delete(db.session.get(ServiceEntry, e2))
        db.session.commit()
        pub.run_sync_now(app)
        purged = _cleared(client)
    assert {f"homeassistant/sensor/{node}/entry_{e1}_state/config",
            f"homeassistant/binary_sensor/{node}/check_{c1}/config"} <= soft
    assert {f"homeassistant/sensor/{node}/entry_{e2}_state/config",
            f"homeassistant/binary_sensor/{node}/check_{c2}/config"} <= purged


def test_turning_discovery_off_clears_everything(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry("web")
        _sync(pub, app)
        published = set(_configs(client))
        assert len(published) == 7          # hub (1 + 4), entry state, one check
        client.published.clear()
        from models import NotificationChannel
        channel = NotificationChannel.query.one()
        _, errors = notify.update_channel(channel, config={"ha_discovery": False})
        assert not errors
    pub.reload_now(app)                       # the config changed: reconnect (new fake client)
    client2 = factory.clients[-1]
    assert pub.run_sync_now(app) is not None
    assert {t for t, payload, *_x in client2.published if payload == ""} >= published
    assert pub.state.ha_topics == {}


def test_rename_keeps_unique_id(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, cid = _entry("before")
        _sync(pub, app)
        before = _cfg(client, node, "sensor", f"entry_{eid}_state")
        client.published.clear()
        db.session.get(ServiceEntry, eid).container_name = "after"
        db.session.commit()
        pub.run_sync_now(app)
    after = _cfg(client, node, "sensor", f"entry_{eid}_state")
    assert after["unique_id"] == before["unique_id"] and after["device"]["identifiers"] == before["device"]["identifiers"]
    assert after["device"]["name"] == "STD after"


def test_two_instances_do_not_collide(app, factory):
    with app.app_context():
        assert notify_ha.node_id("11111111-2222-3333-4444-555555555555") != \
            notify_ha.node_id("aaaaaaaa-2222-3333-4444-555555555555")
        entry = ServiceEntry(host=None, container_name="x", source="manual", last_updated=datetime.now())
        db.session.add(entry)
        db.session.commit()
        cfg = notify_mqtt_config()
        a = notify_ha.desired_configs([entry], cfg, "11111111-2222-3333-4444-555555555555", "1")
        b = notify_ha.desired_configs([entry], cfg, "aaaaaaaa-2222-3333-4444-555555555555", "1")
        assert not set(a) & set(b)
        uids = lambda d: {c["unique_id"] for c in d.values()}  # noqa: E731
        assert not uids(a) & uids(b)


def notify_mqtt_config():
    import notify_mqtt
    return notify_mqtt.clean_config(HA_CFG)


# --- Home Assistant birth message --------------------------------------------------------


def test_birth_message_republishes_configs_then_states(app, factory):
    pub, client = _setup(app, factory)
    assert client.subscriptions == [("homeassistant/status", 1)]
    with app.app_context():
        _entry("web")
        _sync(pub, app)
        pub.run_sync_now(app)                 # nothing pending
        client.published.clear()
        client.deliver("homeassistant/status", "offline")
        assert not pub.sync_pending()
        client.deliver("homeassistant/other", "online")
        assert not pub.sync_pending()
        client.deliver("homeassistant/status", "online")
        assert pub.sync_pending()
        pub.run_sync_now(app)
    topics = [t for t, *_x in client.published]
    assert any(t.endswith("/config") for t in topics) and "std/summary" in topics
    assert max(i for i, t in enumerate(topics) if t.endswith("/config")) < \
        min(i for i, t in enumerate(topics) if t.startswith("std/"))


def test_birth_subscription_follows_the_prefix(app, factory):
    _pub, client = _setup(app, factory, ha_prefix="ha")
    assert client.subscriptions == [("ha/status", 1)]


# --- register must not touch the opt-outs --------------------------------------------------


def test_register_never_overwrites_ha_exclude(app, register):
    assert register().status_code == 200
    with app.app_context():
        entry = ServiceEntry.query.filter_by(host="host1", container_name="svc1").one()
        entry.ha_exclude = True
        for check in entry.checks:
            check.ha_exclude = True
        db.session.commit()
        n = len(entry.checks)
    assert register(docker_status="running").status_code == 200
    with app.app_context():
        entry = ServiceEntry.query.filter_by(host="host1", container_name="svc1").one()
        assert entry.ha_exclude is True
        assert len(entry.checks) == n and all(c.ha_exclude for c in entry.checks)


# --- management API and forms ---------------------------------------------------------------


def test_mgmt_api_reads_and_writes_ha_exclude(app, client):
    from tests.test_mgmt_api_keys import _bearer, _key
    headers = _bearer(_key(app, "w", "write")[1])
    created = client.post("/api/v1/entries", json={"name": "api", "ha_exclude": True,
                                                   "url_checks": {"internal": {"enabled": True, "ha_exclude": True}},
                                                   "checks": [{"target": "h:80", "check_type": "tcp"}]},
                          headers=headers)
    assert created.status_code == 201, created.get_json()
    body = created.get_json()
    assert body["ha_exclude"] is True
    by_kind = {c["kind"]: c for c in body["checks"]}
    assert by_kind["internal_url"]["ha_exclude"] is True
    assert by_kind["service"]["ha_exclude"] is False
    patched = client.patch(f"/api/v1/entries/{body['id']}", json={"ha_exclude": False}, headers=headers)
    assert patched.status_code == 200 and patched.get_json()["ha_exclude"] is False
    cid = by_kind["service"]["id"]
    patched = client.patch(f"/api/v1/checks/{cid}", json={"ha_exclude": True}, headers=headers)
    assert patched.status_code == 200 and patched.get_json()["ha_exclude"] is True
    null = client.patch(f"/api/v1/checks/{cid}", json={"ha_exclude": None}, headers=headers)
    assert null.status_code == 400


def test_channel_config_accepts_ha_fields(app, client):
    from tests.test_mgmt_api_keys import _bearer, _key
    headers = _bearer(_key(app, "w", "write")[1])
    resp = client.post("/api/v1/notifications/channels", headers=headers, json={
        "name": "ha", "config": {"host": "b", "ha_discovery": True, "ha_prefix": "hass", "ha_device_prefix": "Lab"}})
    assert resp.status_code == 201, resp.get_json()
    assert resp.get_json()["config"]["ha_prefix"] == "hass"


def test_edit_form_toggles_entry_and_check_opt_out(app, admin_client):
    with app.app_context():
        eid, cid = _entry("web")
    page = admin_client.get(f"/edit/{eid}")
    html = page.get_data(as_text=True)
    assert "Exclude from Home Assistant" in html and "Publish to Home Assistant" in html
    form = {"container_name": "web", "host": "", "widget_name": "none", "checks_form": "1", "ha_form": "1",
            "uc_internal_ha_seen": "1", "uc_external_ha_seen": "1", "uc_internal_enabled": "1"}
    resp = admin_client.post(f"/edit/{eid}", data={**form, "ha_exclude": "1"})
    assert resp.status_code in (200, 302)
    with app.app_context():
        entry = db.session.get(ServiceEntry, eid)
        assert entry.ha_exclude is True
        assert entry.url_check("internal").ha_exclude is True      # seen marker, box unticked
    resp = admin_client.post(f"/edit/{eid}", data={**form, "uc_internal_ha_publish": "1"})
    with app.app_context():
        entry = db.session.get(ServiceEntry, eid)
        assert entry.ha_exclude is False and entry.url_check("internal").ha_exclude is False
    # a form without the markers leaves both flags alone
    with app.app_context():
        db.session.get(ServiceEntry, eid).ha_exclude = True
        db.session.commit()
    admin_client.post(f"/edit/{eid}", data={"container_name": "web", "host": "", "widget_name": "none", "checks_form": "1"})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).ha_exclude is True


# --- migration --------------------------------------------------------------------------------


def test_migration_up_down(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS)

    def columns(table):
        con = sqlite3.connect(db_path)
        try:
            return {r[1]: r for r in con.execute(f"PRAGMA table_info({table})")}
        finally:
            con.close()

    assert "ha_exclude" not in columns("service_entry")
    _alembic(tmp_path, db_path, "upgrade", REV)
    for table in ("service_entry", "health_check"):
        col = columns(table)["ha_exclude"]
        assert col[3] == 1 and col[4] in ("0", "false", "FALSE")     # NOT NULL, default false
    _alembic(tmp_path, db_path, "downgrade", "-1")
    assert "ha_exclude" not in columns("service_entry") and "ha_exclude" not in columns("health_check")
    _alembic(tmp_path, db_path, "upgrade", "head")
    assert "ha_exclude" in columns("health_check")
