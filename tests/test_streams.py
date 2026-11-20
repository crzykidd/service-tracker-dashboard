"""Inventory streams: ingest contract, apply engine and lifecycle (PRD 18.4-18.7)."""

import copy
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event

import api_keys
import notify_ha
import notify_state
import streams
from api_version import API_REVISION
from extensions import db
from health_state import entry_health
from models import (
    ApiAudit,
    InventoryBlock,
    InventoryStream,
    ServiceEntry,
    StreamLinkOffer,
    ensure_url_checks,
)
from tests.test_mgmt_api_keys import _bearer, _key

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = Path(__file__).parent / "fixtures" / "stream_snapshot.json"
PREVIOUS_HEAD = "e3b7c1d9a204"
URL = "/api/v1/streams/dhcp/snapshot"


def snapshot(**overrides):
    body = json.loads(FIXTURE.read_text())
    body.update(overrides)
    return body


@pytest.fixture
def keys(app):
    return {"ingest": _key(app, "sidecar", "ingest")[1], "write": _key(app, "ops", "write")[1],
            "read": _key(app, "viewer", "read")[1]}


@pytest.fixture
def put(client, keys):
    def _put(body=None, slug="dhcp", key="ingest", **kw):
        return client.put(f"/api/v1/streams/{slug}/snapshot", json=snapshot() if body is None else body,
                          headers=_bearer(keys[key]), **kw)
    return _put


@pytest.fixture
def op(client, keys):
    """An operator call with the write key: op("POST", "/streams/dhcp/enable")."""
    def _op(method, path, key="write", **kw):
        return client.open("/api/v1" + path, method=method, headers=_bearer(keys[key]), **kw)
    return _op


@pytest.fixture
def manual(app):
    """manual("nas") adds a manual entry (no host unless given) and returns its id."""
    def _manual(name="nas", host=None, **kw):
        with app.app_context():
            e = ServiceEntry(host=host, container_name=name, source="manual", last_updated=datetime.now(), **kw)
            db.session.add(e)
            ensure_url_checks(e)
            db.session.commit()
            return e.id
    return _manual


def stream_entries(**filters):
    return {e.stream_key: e for e in ServiceEntry.query.filter_by(source="stream", **filters)}


def enabled_stream(app, put, op, body=None):
    assert put(body).status_code == 202
    r = op("POST", "/streams/dhcp/enable")
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# --- MAC normalisation -----------------------------------------------------------


@pytest.mark.parametrize("raw", [
    "aa:bb:cc:dd:ee:ff", "AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "AA-BB-CC-DD-EE-FF",
    "aabb.ccdd.eeff", "AABB.CCDD.EEFF", "aabbccddeeff", "AABBCCDDEEFF", "  aa:bb:cc:dd:ee:ff ",
])
def test_normalize_mac_accepts_each_form(raw):
    assert streams.normalize_mac(raw) == "aa:bb:cc:dd:ee:ff"


@pytest.mark.parametrize("raw", [
    "", "aa:bb:cc:dd:ee", "aa:bb:cc:dd:ee:ff:00", "aa:bb-cc:dd-ee:ff", "aabb.ccdd.eef", "gg:bb:cc:dd:ee:ff",
    "aabbccddeef", "aabbccddeeff0", None, 123,
])
def test_normalize_mac_rejects_everything_else(raw):
    assert streams.normalize_mac(raw) is None


# --- keys and scopes -------------------------------------------------------------


def test_ingest_scope_matrix():
    assert api_keys.scope_allows("ingest", "ingest")
    assert api_keys.scope_allows("write", "ingest")
    assert not api_keys.scope_allows("read", "ingest")
    assert not api_keys.scope_allows("ingest", "read")
    assert not api_keys.scope_allows("ingest", "write")
    assert "ingest" in api_keys.SCOPES


def test_ingest_key_is_refused_everywhere_else(client, keys):
    h = _bearer(keys["ingest"])
    for method, path in (("get", "/api/v1/whoami"), ("get", "/api/v1/entries"), ("get", "/api/v1/streams"),
                         ("post", "/api/v1/entries"), ("post", "/api/v1/streams/dhcp/enable"),
                         ("get", "/api/v1/config")):
        r = getattr(client, method)(path, headers=h)
        assert r.status_code == 403, path


def test_read_key_cannot_ingest_and_no_key_is_401(client, keys):
    assert client.put(URL, json=snapshot(), headers=_bearer(keys["read"])).status_code == 403
    assert client.put(URL, json=snapshot()).status_code == 401
    assert client.get("/api/v1/streams/dhcp/status").status_code == 401


def test_write_key_may_ingest(put):
    assert put(key="write").status_code == 202


# --- the ingest contract: status codes ------------------------------------------


def test_new_stream_is_pending_and_202(app, put):
    r = put()
    assert r.status_code == 202
    body = r.get_json()
    assert set(body) == {"stream_id", "stream_status", "applied", "item_count", "message"}
    assert (body["stream_id"], body["stream_status"], body["applied"], body["item_count"]) == \
        ("dhcp", "pending", False, 10)
    assert "Settings" in body["message"] and "Streams" in body["message"]
    with app.app_context():
        stream = InventoryStream.query.one()
        assert stream.status == "pending" and stream.display_name == "DHCP" and stream.key_type == "mac"
        assert len(stream.snapshot) == 10 and stream.last_item_count == 10
        assert ServiceEntry.query.count() == 0           # nothing applied
        assert stream.api_key_id is not None


def test_enabled_stream_returns_200_with_counts(app, put, op):
    put()
    op("POST", "/streams/dhcp/enable")
    r = put()
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"stream_id", "stream_status", "applied", "item_count", "counts"}
    assert body["stream_status"] == "enabled" and body["applied"] is True and body["item_count"] == 10
    assert set(body["counts"]) == set(streams.COUNT_KEYS)
    assert body["counts"]["unchanged"] == 10 and body["counts"]["link_offers"] == 0


def test_disabled_stream_stores_but_does_not_apply(app, put, op):
    enabled_stream(app, put, op)
    assert op("POST", "/streams/dhcp/disable", json={"cleanup": "keep"}).status_code == 200
    body = snapshot()
    body["items"] = body["items"][:2]
    r = put(body)
    assert r.status_code == 202 and r.get_json()["stream_status"] == "disabled"
    with app.app_context():
        assert len(InventoryStream.query.one().snapshot) == 2
        assert ServiceEntry.query.filter_by(source="stream", inventory_missing=True).count() == 0


def test_ignored_stream_is_discarded_and_not_stored(app, put, op):
    put()
    assert op("POST", "/streams/dhcp/ignore").status_code == 200
    r = put()
    assert r.status_code == 202
    assert r.get_json() == {"stream_id": "dhcp", "stream_status": "ignored", "applied": False}
    with app.app_context():
        assert InventoryStream.query.one().snapshot is None


def test_status_route(app, put, op, client, keys):
    assert client.get("/api/v1/streams/dhcp/status", headers=_bearer(keys["ingest"])).status_code == 404
    put()
    r = client.get("/api/v1/streams/dhcp/status", headers=_bearer(keys["ingest"]))
    assert r.status_code == 200
    body = r.get_json()
    assert set(body) == {"stream_id", "stream_status", "display_name", "last_snapshot_at",
                         "last_applied_at", "last_item_count", "last_counts"}
    assert body["stream_status"] == "pending" and body["last_item_count"] == 10
    assert body["last_applied_at"] is None and body["last_counts"] is None
    assert body["last_snapshot_at"].endswith("Z")


@pytest.mark.parametrize("mutate", [
    lambda b: b.update(extra="x"),                                   # unknown top-level key
    lambda b: b["items"][0].update(extra="x"),                       # unknown item key
    lambda b: b.pop("producer"),
    lambda b: b.pop("items"),
    lambda b: b.update(display_name=""),
    lambda b: b.update(display_name="x" * 33),
    lambda b: b.update(producer="x" * 65),
    lambda b: b.update(producer_version="x" * 33),
    lambda b: b.update(key_type="MAC"),
    lambda b: b["items"][0].update(key="not-a-mac"),                  # key_type mac
    lambda b: b["items"][1].update(key="aa:bb:cc:00:00:01"),          # duplicate after normalising
    lambda b: b["items"][0].update(name=""),
    lambda b: b["items"][0].update(name="x" * 129),
    lambda b: b["items"][0].update(ip="10.0.0.999"),
    lambda b: b["items"][0].update(mac="zz"),
    lambda b: b["items"][0].update(network="x" * 65),
    lambda b: b["items"][0].update(attributes={f"k{i}": i for i in range(33)}),
    lambda b: b["items"][0].update(attributes={"bad key": 1}),
    lambda b: b["items"][0].update(attributes={"k": "x" * 257}),
    lambda b: b["items"][0].update(attributes={"k": [1]}),
    lambda b: b["items"][0].update(attributes={"k": {"a": 1}}),
    lambda b: b.update(items=[{"key": f"{i:012x}", "name": "n"} for i in range(5001)]),
])
def test_validation_failures_are_400(put, mutate):
    body = snapshot()
    mutate(body)
    r = put(body)
    assert r.status_code == 400, r.get_json()
    out = r.get_json()
    assert out["error"] and isinstance(out["details"], list) and out["details"]


def test_bad_json_bodies_are_400(client, keys):
    h = _bearer(keys["ingest"])
    assert client.put(URL, data=b"not json", content_type="application/json", headers=h).status_code == 400
    assert client.put(URL, json=[1, 2], headers=h).status_code == 400


def test_bad_stream_id_is_400(put):
    assert put(slug="Bad_ID").status_code == 400
    assert put(slug="-x").status_code == 400
    assert put(slug="a" * 64).status_code == 400
    assert put(slug="a" * 63).status_code == 202


def test_attribute_values_of_every_allowed_type_are_stored(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        attrs = stream_entries()["aa:bb:cc:00:00:01"].attributes
        assert attrs == {"scope": "CrzyIoT", "reservation_comment": "boiler room", "lease_hours": 24,
                         "static": True, "note": None}


def test_empty_items_is_valid(app, put):
    body = snapshot(items=[])
    assert put(body).status_code == 202


def test_five_thousand_items_is_the_limit(put):
    body = snapshot(items=[{"key": f"{i:012x}", "name": f"n{i}"} for i in range(5000)])
    assert put(body).status_code == 202


def test_key_type_cannot_change(put):
    assert put().status_code == 202
    body = snapshot(key_type="ieee")
    body["items"] = [{"key": "0x1234", "name": "bulb"}]
    r = put(body)
    assert r.status_code == 409 and r.get_json()["error"]


def test_non_mac_key_type_keeps_keys_as_given(app, put):
    body = snapshot(key_type="ieee", items=[{"key": "0x00158D0001", "name": "bulb", "mac": "AABBCCDDEEFF"}])
    assert put(body).status_code == 202
    with app.app_context():
        item = InventoryStream.query.one().snapshot[0]
        assert item["key"] == "0x00158D0001" and item["mac"] == "aa:bb:cc:dd:ee:ff"


def test_mac_key_type_copies_the_key_into_mac(app, put):
    assert put().status_code == 202
    with app.app_context():
        items = {i["key"]: i for i in InventoryStream.query.one().snapshot}
        assert items["aa:bb:cc:00:00:02"]["mac"] == "aa:bb:cc:00:00:02"   # from AA-BB-CC-00-00-02
        assert items["aa:bb:cc:00:00:03"]["mac"] == "aa:bb:cc:00:00:03"   # from aabb.cc00.0003
        assert items["aa:bb:cc:00:00:04"]["mac"] == "aa:bb:cc:00:00:04"   # from aabbcc000004


def test_body_over_2_mib_is_413_before_parsing(client, keys):
    big = b'{"x": "' + b"a" * (2 * 1024 * 1024 + 10) + b'"}'
    r = client.put(URL, data=big, content_type="application/json", headers=_bearer(keys["ingest"]))
    assert r.status_code == 413
    assert r.get_json()["error"]


def test_body_at_the_limit_is_not_413(client, keys):
    body = b'{"x": "' + b"a" * 1000 + b'"}'
    r = client.put(URL, data=body, content_type="application/json", headers=_bearer(keys["ingest"]))
    assert r.status_code == 400          # parsed (and rejected for the unknown key), not too large


# --- key binding -------------------------------------------------------------------


def test_stream_is_bound_to_its_creating_key(app, put, client, keys):
    assert put().status_code == 202
    other = _key(app, "other-sidecar", "ingest")[1]
    r = client.put(URL, json=snapshot(), headers=_bearer(other))
    assert r.status_code == 403 and r.get_json()["error"]
    assert client.get("/api/v1/streams/dhcp/status", headers=_bearer(other)).status_code == 403
    assert put(key="ingest").status_code == 202           # the creator still can
    assert put(key="write").status_code == 202            # a write key may post to any stream


def test_binding_survives_key_rotation(app, put, client, keys):
    assert put().status_code == 202
    with app.app_context():
        key = api_keys.verify(keys["ingest"])
        new_secret = api_keys.rotate_key(key)
    assert client.put(URL, json=snapshot(), headers=_bearer(keys["ingest"])).status_code == 401
    assert client.put(URL, json=snapshot(), headers=_bearer(new_secret)).status_code == 202


def test_snapshot_puts_are_not_audited_but_status_changes_are(app, put, op):
    put()
    put()
    op("POST", "/streams/dhcp/enable")
    with app.app_context():
        rows = ApiAudit.query.all()
        assert [r.path for r in rows] == ["/api/v1/streams/dhcp/enable"]
        assert rows[0].object_type == "stream" and rows[0].object_id == "dhcp"
        assert rows[0].changes["status"] == ["pending", "enabled"]


def test_revision_headers_on_the_new_routes(app, put, op, client, keys):
    for resp in (put(), client.get("/api/v1/streams/dhcp/status", headers=_bearer(keys["ingest"])),
                 put(slug="Bad"), op("GET", "/streams"), op("POST", "/streams/dhcp/enable"),
                 client.put(URL, data=b"x" * (2 * 1024 * 1024 + 1), content_type="application/json",
                            headers=_bearer(keys["ingest"])),
                 client.put(URL, json=snapshot())):
        assert resp.headers["X-STD-API-Revision"] == str(API_REVISION)
        assert resp.headers["X-STD-Version"] == app.config["VERSION_INFO"]["version"]


# --- enable applies the stored snapshot; each apply rule ---------------------------


def test_pending_then_enable_applies_the_stored_snapshot(app, put, op, manual):
    manual("nas")
    put()
    r = op("POST", "/streams/dhcp/enable")
    body = r.get_json()
    assert body["applied"] is True and body["stream"]["status"] == "enabled"
    assert body["counts"] == {"created": 9, "updated": 0, "unchanged": 0, "restored": 0, "missing": 0,
                              "blocked": 0, "link_offers": 1, "filtered": 0}
    with app.app_context():
        entries = stream_entries()
        assert len(entries) == 9 and "aa:bb:cc:00:00:07" not in entries    # NAS is held for a link offer
        e = entries["aa:bb:cc:00:00:01"]
        assert (e.container_name, e.host, e.source, e.ip, e.mac, e.network, e.name_source,
                e.inventory_missing) == ("shelly-pump", None, "stream", "10.0.40.21",
                                         "aa:bb:cc:00:00:01", "CrzyIoT", "stream", False)
        assert e.url_check("internal") is not None and not e.internal_check_enabled
        assert not e.is_docker and e.container_check is None and not e.is_docker_status_stale
        assert StreamLinkOffer.query.count() == 1
        stream = InventoryStream.query.one()
        assert stream.last_counts == body["counts"] and stream.last_applied_at is not None
        assert stream.last_error is None


def test_enable_with_no_stored_snapshot_applies_nothing(app, op, put):
    put(snapshot(items=[]))
    with app.app_context():
        s = InventoryStream.query.one()
        s.snapshot = None
        db.session.commit()
    r = op("POST", "/streams/dhcp/enable")
    assert r.status_code == 200 and r.get_json()["applied"] is False and r.get_json()["counts"] is None


def test_enable_twice_is_409(app, put, op):
    enabled_stream(app, put, op)
    assert op("POST", "/streams/dhcp/enable").status_code == 409


def test_duplicate_names_create_two_entries(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="dup-name").count() == 2


def test_filter_include_and_exclude(app, put, op):
    put()
    assert op("PATCH", "/streams/dhcp", json={"network_include": ["crzyiot", "CrzyMedia"],
                                              "network_exclude": ["CrzyMedia"]}).status_code == 200
    body = op("POST", "/streams/dhcp/enable").get_json()
    # include (case-insensitive) keeps CrzyIoT + CrzyMedia; exclude then drops CrzyMedia; Guest and
    # the item with no network are not in the include list.
    with app.app_context():
        nets = {e.network for e in stream_entries().values()}
        assert nets == {"CrzyIoT"}
    assert body["counts"]["filtered"] == 10 - 5      # 5 CrzyIoT items created (incl. the 2 dup names)
    assert sum(v for k, v in body["counts"].items() if k != "missing") == 10


def test_exclude_only_filter(app, put, op):
    put()
    op("PATCH", "/streams/dhcp", json={"network_exclude": ["Guest"]})
    body = op("POST", "/streams/dhcp/enable").get_json()
    assert body["counts"]["filtered"] == 1 and body["counts"]["created"] == 9
    with app.app_context():
        assert "aa:bb:cc:00:00:08" not in stream_entries()


def test_counts_partition_the_items(app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    body = put().get_json()
    c = body["counts"]
    assert sum(c[k] for k in c if k != "missing") == body["item_count"] == 10


def test_blocked_keys_are_skipped(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        entry = stream_entries()["aa:bb:cc:00:00:08"]
        eid = entry.id
    assert op("DELETE", f"/entries/{eid}", query_string={"block": "true"}).status_code == 200
    body = put().get_json()
    assert body["counts"]["blocked"] == 1 and body["counts"]["restored"] == 0
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.deleted_at is not None              # stays deleted
        assert stream_entries(deleted_at=None).get("aa:bb:cc:00:00:08") is None
        assert InventoryStream.query.one().entries      # relationship works


def test_update_unchanged_and_overwritten_fields(app, put, op):
    enabled_stream(app, put, op)
    assert put().get_json()["counts"]["unchanged"] == 10
    body = snapshot()
    body["items"][0].update(ip="10.0.40.99", network="Moved", attributes={"a": 1})
    counts = put(body).get_json()["counts"]
    assert counts["updated"] == 1 and counts["unchanged"] == 9
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        assert (e.ip, e.network, e.attributes) == ("10.0.40.99", "Moved", {"a": 1})


def test_operator_owned_fields_are_never_written(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        e.description, e.image_icon, e.ha_publish, e.sort_priority = "boiler", "pump.svg", True, 7
        from models import Group
        g = Group(group_name="IoT")
        db.session.add(g)
        db.session.flush()
        e.group_id = g.id
        db.session.commit()
    body = snapshot()
    body["items"][0]["ip"] = "10.0.40.77"
    assert put(body).get_json()["counts"]["updated"] == 1
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        assert (e.description, e.image_icon, e.ha_publish, e.sort_priority) == ("boiler", "pump.svg", True, 7)
        assert e.group.group_name == "IoT" and e.ip == "10.0.40.77"


def test_name_follows_the_producer_until_the_operator_renames(app, put, op):
    enabled_stream(app, put, op)
    body = snapshot()
    body["items"][0]["name"] = "shelly-pump-2"
    put(body)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        assert e.container_name == "shelly-pump-2" and e.name_source == "stream"
        eid = e.id
    r = op("PATCH", f"/entries/{eid}", json={"name": "Boiler pump"})
    assert r.status_code == 200 and r.get_json()["name"] == "Boiler pump"
    assert r.get_json()["inventory"]["name_source"] == "ui_edit"
    body["items"][0]["name"] = "shelly-pump-3"
    body["items"][0]["ip"] = "10.0.40.55"
    put(body)
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.container_name == "Boiler pump" and e.ip == "10.0.40.55"     # name kept, ip follows


def test_renaming_to_the_same_name_keeps_name_source(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        eid, name = e.id, e.container_name
    op("PATCH", f"/entries/{eid}", json={"name": name})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).name_source == "stream"


def test_stream_entry_rename_skips_the_duplicate_check_and_host_is_refused(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        a = stream_entries()["aa:bb:cc:00:00:05"].id
    # "dup-name" already exists for the other item: stream entries are unique by key, not by name.
    assert op("PATCH", f"/entries/{a}", json={"name": "printer"}).status_code == 200
    assert op("PATCH", f"/entries/{a}", json={"host": "h1"}).status_code == 400


def test_ui_rename_sets_ui_edit(app, put, op, admin_client):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:01"].id
    r = admin_client.post(f"/edit/{eid}", data={"container_name": "Renamed", "host": "ignored",
                                                "description": "d", "widget_name": "none"})
    assert r.status_code in (200, 302)
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert (e.container_name, e.name_source, e.host, e.description) == ("Renamed", "ui_edit", None, "d")


def test_missing_flag_sets_and_clears_and_nothing_is_deleted(app, put, op):
    enabled_stream(app, put, op)
    body = snapshot()
    body["items"] = body["items"][:6]
    counts = put(body).get_json()["counts"]
    assert counts["missing"] == 4
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream", deleted_at=None).count() == 10
        assert ServiceEntry.query.filter_by(inventory_missing=True).count() == 4
    assert put(body).get_json()["counts"]["missing"] == 4            # stays flagged, no churn
    counts = put().get_json()["counts"]
    assert counts["missing"] == 0 and counts["updated"] == 4          # the flag clears when they come back
    with app.app_context():
        assert ServiceEntry.query.filter_by(inventory_missing=True).count() == 0


def test_empty_snapshot_flags_everything_missing(app, put, op):
    enabled_stream(app, put, op)
    counts = put(snapshot(items=[])).get_json()["counts"]
    assert counts["missing"] == 10
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream", inventory_missing=True).count() == 10
        assert ServiceEntry.query.filter(ServiceEntry.deleted_at.isnot(None)).count() == 0


def test_soft_deleted_entry_is_restored_by_its_key(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:03"].id
    assert op("DELETE", f"/entries/{eid}").status_code == 200       # allow re-adding
    counts = put().get_json()["counts"]
    assert counts["restored"] == 1 and counts["created"] == 0
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.deleted_at is None
        assert ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:03").count() == 1


def test_a_deleted_entry_is_not_missing(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:03"].id
    op("DELETE", f"/entries/{eid}")
    body = snapshot()
    body["items"] = [i for i in body["items"] if "0003" not in i["key"]]
    assert put(body).get_json()["counts"]["missing"] == 0


def test_register_never_touches_stream_entries(app, put, op, register):
    with app.app_context():
        e = ServiceEntry(host="host1", container_name="svc1", source="stream", stream_key="k",
                         last_updated=datetime.now())
        s = InventoryStream(stream_id="x", display_name="X", producer="p", producer_version="1",
                            key_type="mac", status="enabled")
        db.session.add_all([s, e])
        db.session.flush()
        e.stream_id = s.id
        ensure_url_checks(e)
        db.session.commit()
        eid = e.id
    r = register(host="host1", container_name="svc1", docker_status="running")
    assert r.status_code == 200
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.source == "stream" and e.docker_status is None and e.last_api_update is None
        rows = ServiceEntry.query.filter_by(host="host1", container_name="svc1").all()
        assert len(rows) == 2 and {r.source for r in rows} == {"stream", "notifier"}


# --- link offers -------------------------------------------------------------------


def test_new_item_matching_one_manual_entry_becomes_an_offer(app, put, op, manual):
    mid = manual("nas", description="the box")
    enabled_stream(app, put, op)
    with app.app_context():
        assert "aa:bb:cc:00:00:07" not in stream_entries()
        offer = StreamLinkOffer.query.one()
        assert offer.entry_id == mid and offer.key == "aa:bb:cc:00:00:07"
        assert offer.item["name"] == "NAS"
    r = op("GET", "/streams/dhcp/offers")
    assert r.get_json()["total"] == 1 and r.get_json()["items"][0]["entry_name"] == "nas"
    assert put().get_json()["counts"]["link_offers"] == 1            # keeps waiting, one offer
    with app.app_context():
        assert StreamLinkOffer.query.count() == 1


def test_two_manual_matches_create_normally(app, put, op, manual):
    manual("nas")
    manual("NAS")                         # two candidates: ambiguous, no offer
    enabled_stream(app, put, op)
    with app.app_context():
        assert StreamLinkOffer.query.count() == 0
        assert "aa:bb:cc:00:00:07" in stream_entries()


def test_host_and_first_label_matching(app, put, op, manual):
    by_host = manual("Some Device", host="NAS")                 # the host equals the item name
    by_label = manual("plug", host="plug-kitchen.lan")          # the host's first label
    enabled_stream(app, put, op)
    with app.app_context():
        offers = {o.key: o.entry_id for o in StreamLinkOffer.query.all()}
        assert offers["aa:bb:cc:00:00:07"] == by_host
        assert offers["AA:BB:CC:00:00:02".lower()] == by_label


def test_item_first_label_matches_entry_name(app, put, op, manual):
    mid = manual("z-wave-house")
    body = snapshot()
    body["items"].append({"key": "aa:bb:cc:00:00:f2", "name": "Z-Wave-House.crzynet.me"})
    enabled_stream(app, put, op, body)
    with app.app_context():
        assert StreamLinkOffer.query.filter_by(key="aa:bb:cc:00:00:f2").one().entry_id == mid


def test_an_entry_is_offered_to_one_key_only(app, put, op, manual):
    manual("dup")
    body = snapshot()
    body["items"] += [{"key": "aa:bb:cc:00:00:f3", "name": "dup"}, {"key": "aa:bb:cc:00:00:f4", "name": "dup.lan"}]
    enabled_stream(app, put, op, body)
    with app.app_context():
        assert StreamLinkOffer.query.filter(StreamLinkOffer.key.in_(["aa:bb:cc:00:00:f3", "aa:bb:cc:00:00:f4"])).count() == 1
        assert "aa:bb:cc:00:00:f4" in stream_entries()


def test_accepting_an_offer_clears_the_host(app, put, op, manual):
    mid = manual("box", host="nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    assert op("POST", f"/streams/dhcp/offers/{offer_id}/accept").status_code == 200
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert e.host is None and e.source == "stream"


def test_accept_converts_the_manual_entry(app, put, op, manual):
    mid = manual("nas", ha_publish=True, description="the box")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    r = op("POST", f"/streams/dhcp/offers/{offer_id}/accept")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body["answer"] == "accepted" and body["entry"]["id"] == mid and body["entry"]["source"] == "stream"
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert (e.source, e.stream_key, e.mac, e.ip, e.network) == \
            ("stream", "aa:bb:cc:00:00:07", "aa:bb:cc:00:00:07", "10.0.10.5", "CrzyMedia")
        assert e.container_name == "nas" and e.name_source == "ui_edit"     # the operator's name stays
        assert e.ha_publish is True and e.description == "the box"
        assert StreamLinkOffer.query.count() == 0
    counts = put().get_json()["counts"]
    assert counts["unchanged"] + counts["updated"] == 10 and counts["link_offers"] == 0
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).container_name == "nas"


def test_decline_creates_a_stream_entry_and_leaves_the_manual_one(app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    r = op("POST", f"/streams/dhcp/offers/{offer_id}/decline")
    assert r.status_code == 200 and r.get_json()["answer"] == "declined"
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "manual"
        e = stream_entries()["aa:bb:cc:00:00:07"]
        assert e.container_name == "NAS" and e.name_source == "stream"
        assert StreamLinkOffer.query.count() == 0
    assert put().get_json()["counts"]["link_offers"] == 0      # the key is known now


def test_offer_errors(app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    assert op("POST", "/streams/dhcp/offers/999/accept").status_code == 404
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    op("POST", "/streams/dhcp/disable", json={"cleanup": "keep"})
    assert op("POST", f"/streams/dhcp/offers/{offer_id}/accept").status_code == 409   # not enabled


def test_a_stale_offer_is_dropped_and_the_item_is_created(app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    assert op("DELETE", f"/entries/{mid}").status_code == 200     # the manual entry goes away
    counts = put().get_json()["counts"]
    assert counts["link_offers"] == 0 and counts["created"] == 1
    with app.app_context():
        assert StreamLinkOffer.query.count() == 0
        assert "aa:bb:cc:00:00:07" in stream_entries()


def test_hard_deleting_the_manual_entry_removes_its_offers(app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    op("DELETE", f"/entries/{mid}")
    assert op("DELETE", f"/entries/{mid}", query_string={"permanent": "true"}).status_code == 200
    with app.app_context():
        assert StreamLinkOffer.query.count() == 0


def test_link_by_hand(app, put, op, manual):
    put()                                         # pending: nothing applied, everything is unmatched
    mid = manual("my-printer")
    r = op("GET", "/streams/dhcp/unmatched")
    assert r.get_json()["total"] == 10
    r = op("POST", "/streams/dhcp/link", json={"entry_id": mid, "key": "aa:bb:cc:00:00:04"})
    assert r.status_code == 200 and r.get_json()["answer"] == "linked"
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert (e.source, e.stream_key, e.ip, e.container_name) == \
            ("stream", "aa:bb:cc:00:00:04", "10.0.10.31", "my-printer")
    assert op("GET", "/streams/dhcp/unmatched").get_json()["total"] == 9
    op("POST", "/streams/dhcp/enable")
    with app.app_context():
        assert ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:04").count() == 1   # not created twice
        assert db.session.get(ServiceEntry, mid).container_name == "my-printer"


def test_link_by_hand_errors(app, put, op, manual):
    put()
    mid = manual("m")
    hosted = manual("h", host="host")
    assert op("POST", "/streams/dhcp/link", json={"entry_id": mid, "key": "nope"}).status_code == 404
    assert op("POST", "/streams/dhcp/link", json={"entry_id": mid, "key": "aa:bb:cc:00:00:04"}).status_code == 200
    r = op("POST", "/streams/dhcp/link", json={"entry_id": hosted, "key": "aa:bb:cc:00:00:05"})     # a host is fine
    assert r.status_code == 200 and r.get_json()["entry"]["host"] is None
    other = manual("o")
    assert op("POST", "/streams/dhcp/link", json={"entry_id": other, "key": "aa:bb:cc:00:00:04"}).status_code == 409


# --- block list ----------------------------------------------------------------------


def test_block_and_unblock(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:01"].id
    assert op("DELETE", f"/entries/{eid}", query_string={"block": "true"}).status_code == 200
    blocks = op("GET", "/streams/dhcp/blocks").get_json()
    assert blocks["total"] == 1
    b = blocks["items"][0]
    assert (b["key"], b["name"], b["ip"], b["blocked_by"], b["stream_id"]) == \
        ("aa:bb:cc:00:00:01", "shelly-pump", "10.0.40.21", "ops", "dhcp")
    assert b["blocked_at"].endswith("Z")
    # even after the soft-delete retention purge hard-deletes the entry, the block stays
    assert op("DELETE", f"/entries/{eid}", query_string={"permanent": "true"}).status_code == 200
    assert put().get_json()["counts"]["blocked"] == 1
    r = op("DELETE", f"/streams/dhcp/blocks/{b['id']}")
    assert r.status_code == 200 and r.get_json()["unblocked"] is True
    assert op("DELETE", f"/streams/dhcp/blocks/{b['id']}").status_code == 404
    counts = put().get_json()["counts"]
    assert counts["created"] == 1 and counts["blocked"] == 0         # a new row (the old one is gone)


def test_unblock_restores_a_kept_row(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:01"].id
    op("DELETE", f"/entries/{eid}", query_string={"block": "true"})
    with app.app_context():
        bid = InventoryBlock.query.one().id
    op("DELETE", f"/streams/dhcp/blocks/{bid}")
    assert put().get_json()["counts"]["restored"] == 1
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).deleted_at is None


def test_block_on_a_non_stream_entry_is_400_and_permanent_conflicts(app, put, op, manual):
    mid = manual("plain")
    assert op("DELETE", f"/entries/{mid}", query_string={"block": "true"}).status_code == 400
    assert op("DELETE", f"/entries/{mid}", query_string={"block": "true", "permanent": "true"}).status_code == 400
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).deleted_at is None


def test_ui_delete_with_block(app, put, op, admin_client):
    enabled_stream(app, put, op)
    with app.app_context():
        a = stream_entries()["aa:bb:cc:00:00:01"].id
        b = stream_entries()["aa:bb:cc:00:00:02"].id
    assert admin_client.post(f"/api/v1/entries/{a}/delete", json={"block": True}).get_json() == {"ok": True}
    assert admin_client.post(f"/api/v1/entries/{b}/delete").get_json() == {"ok": True}
    with app.app_context():
        keys = {x.key: x.blocked_by for x in InventoryBlock.query.all()}
        assert keys == {"aa:bb:cc:00:00:01": "admin"}
        assert db.session.get(ServiceEntry, b).deleted_at is not None


def test_ui_edit_page_delete_with_block(app, put, op, admin_client):
    enabled_stream(app, put, op)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        eid, name = e.id, e.container_name
    admin_client.post(f"/edit/{eid}", data={"delete": "1", "delete_confirmation": name, "block": "true"})
    with app.app_context():
        assert InventoryBlock.query.count() == 1 and db.session.get(ServiceEntry, eid).deleted_at is not None


def test_restore_of_a_stream_entry_skips_the_clash_check(app, put, op, admin_client, manual):
    enabled_stream(app, put, op)
    with app.app_context():
        a = stream_entries()["aa:bb:cc:00:00:05"].id      # "dup-name", host NULL
    op("DELETE", f"/entries/{a}")
    manual("dup-name")                                    # an active host-less entry with the same name
    assert op("POST", f"/entries/{a}/restore").status_code == 200
    with app.app_context():
        assert db.session.get(ServiceEntry, a).deleted_at is None


# --- lifecycle: disable, delete, ignore, update ------------------------------------------


def _seed_cleanup(app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()["aa:bb:cc:00:00:01"].id
        gone = stream_entries()["aa:bb:cc:00:00:02"].id
    op("DELETE", f"/entries/{gone}", query_string={"block": "true"})
    return eid, gone


def test_disable_keep(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("POST", "/streams/dhcp/disable", json={"cleanup": "keep"})
    assert r.status_code == 200
    assert r.get_json()["stream"]["status"] == "disabled"
    res = r.get_json()["result"]
    assert (res["entries"], res["kept"], res["soft_deleted"], res["purged"]) == (9, 9, 0, 0)
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream", deleted_at=None).count() == 8
        assert InventoryStream.query.one().snapshot is not None
        assert StreamLinkOffer.query.count() == 1 and InventoryBlock.query.count() == 1


def test_disable_default_body_is_keep(app, put, op):
    enabled_stream(app, put, op)
    r = op("POST", "/streams/dhcp/disable")
    assert r.status_code == 200 and r.get_json()["cleanup"] == "keep"


def test_disable_soft_delete_then_reenable_restores(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("POST", "/streams/dhcp/disable", json={"cleanup": "soft_delete"})
    assert r.get_json()["result"]["soft_deleted"] == 8          # the blocked one was already deleted
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream", deleted_at=None).count() == 0
        assert ServiceEntry.query.filter_by(source="manual", deleted_at=None).count() == 1   # manual untouched
    r = op("POST", "/streams/dhcp/enable")
    assert r.get_json()["counts"]["restored"] == 8 and r.get_json()["counts"]["blocked"] == 1


def test_disable_purge_and_clear_blocks(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("POST", "/streams/dhcp/disable", json={"cleanup": "purge"})
    res = r.get_json()["result"]
    assert res["purged"] == 9 and res["offers_removed"] == 1 and res["blocks_cleared"] == 0
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream").count() == 0
        assert ServiceEntry.query.filter_by(source="manual").count() == 1
        s = InventoryStream.query.one()
        assert s.snapshot is not None and s.status == "disabled"      # the snapshot is kept
        assert StreamLinkOffer.query.count() == 0 and InventoryBlock.query.count() == 1     # blocks kept
    op("POST", "/streams/dhcp/enable")
    # re-enable and purge again, this time clearing the blocks
    put()
    op("POST", "/streams/dhcp/disable", json={"cleanup": "purge", "clear_blocks": True})
    with app.app_context():
        assert InventoryBlock.query.count() == 0


def test_clear_blocks_is_ignored_without_purge(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    op("POST", "/streams/dhcp/disable", json={"cleanup": "keep", "clear_blocks": True})
    with app.app_context():
        assert InventoryBlock.query.count() == 1


def test_disable_errors(app, put, op):
    put()
    assert op("POST", "/streams/dhcp/disable").status_code == 409              # pending
    op("POST", "/streams/dhcp/enable")
    assert op("POST", "/streams/dhcp/disable", json={"cleanup": "nuke"}).status_code == 400
    assert op("POST", "/streams/dhcp/disable", json={"cleanup": "keep", "x": 1}).status_code == 400


def test_delete_stream_keep_makes_entries_manual(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("DELETE", "/streams/dhcp", query_string={"cleanup": "keep"})
    assert r.status_code == 200 and r.get_json()["deleted"] is True
    with app.app_context():
        assert InventoryStream.query.count() == 0 and InventoryBlock.query.count() == 0
        assert StreamLinkOffer.query.count() == 0
        entries = ServiceEntry.query.filter_by(container_name="shelly-pump").all()
        e = entries[0]
        assert (e.source, e.stream_id, e.stream_key, e.mac, e.ip) == \
            ("manual", None, None, "aa:bb:cc:00:00:01", "10.0.40.21")
        assert ServiceEntry.query.filter_by(source="stream").count() == 0


def test_delete_stream_soft_delete(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("DELETE", "/streams/dhcp", query_string={"cleanup": "soft_delete"})
    assert r.get_json()["result"]["soft_deleted"] == 8
    with app.app_context():
        active = ServiceEntry.query.filter(ServiceEntry.deleted_at.is_(None), ServiceEntry.container_name != "nas")
        assert active.count() == 0
        assert ServiceEntry.query.filter(ServiceEntry.deleted_at.isnot(None)).count() == 9
        assert ServiceEntry.query.filter_by(source="stream").count() == 0     # restorable as manual


def test_delete_stream_purge(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    assert op("DELETE", "/streams/dhcp", query_string={"cleanup": "purge"}).status_code == 200
    with app.app_context():
        assert ServiceEntry.query.count() == 1 and InventoryStream.query.count() == 0
    assert op("DELETE", "/streams/dhcp").status_code == 404
    assert op("DELETE", "/streams/dhcp", query_string={"cleanup": "nope"}).status_code in (400, 404)


def test_delete_stream_rejects_unknown_cleanup(app, put, op):
    put()
    assert op("DELETE", "/streams/dhcp", query_string={"cleanup": "nope"}).status_code == 400
    with app.app_context():
        assert InventoryStream.query.count() == 1


def test_ignore_rules(app, put, op):
    put()
    r = op("POST", "/streams/dhcp/ignore")
    assert r.status_code == 200 and r.get_json()["status"] == "ignored"
    assert op("POST", "/streams/dhcp/ignore").status_code == 409
    assert op("POST", "/streams/dhcp/enable").status_code == 200       # ignored streams can be enabled again
    assert op("POST", "/streams/dhcp/ignore").status_code == 409       # but not ignored while enabled


def test_update_stream(app, put, op):
    put()
    r = op("PATCH", "/streams/dhcp", json={"display_name": "  Static DHCP ", "network_exclude": ["Guest", "Guest"]})
    assert r.status_code == 200
    body = r.get_json()
    assert body["display_name"] == "Static DHCP" and body["network_exclude"] == ["Guest"]
    assert op("PATCH", "/streams/dhcp", json={"network_exclude": []}).get_json()["network_exclude"] is None
    assert op("PATCH", "/streams/dhcp", json={}).status_code == 400
    assert op("PATCH", "/streams/dhcp", json={"display_name": ""}).status_code == 400
    assert op("PATCH", "/streams/dhcp", json={"display_name": "x" * 33}).status_code == 400
    assert op("PATCH", "/streams/dhcp", json={"network_include": [""]}).status_code == 400
    assert op("PATCH", "/streams/dhcp", json={"bogus": 1}).status_code == 400
    assert op("PATCH", "/streams/nope", json={"display_name": "x"}).status_code == 404
    # the producer's display_name no longer renames it
    body = snapshot(display_name="Producer Name")
    put(body)
    assert op("GET", "/streams/dhcp").get_json()["display_name"] == "Static DHCP"


def test_stream_audit_rows(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    op("POST", "/streams/dhcp/disable", json={"cleanup": "soft_delete"})
    with app.app_context():
        rows = {r.path: r for r in ApiAudit.query.filter(ApiAudit.object_type == "stream")}
        dis = rows["/api/v1/streams/dhcp/disable"]
        assert dis.changes["cleanup"] == [None, "soft_delete"]
        assert dis.changes["result"][1]["soft_deleted"] == 8
        ent = ApiAudit.query.filter(ApiAudit.object_type == "entry").first()
        assert ent.changes["stream_block"] == [None, "aa:bb:cc:00:00:02"]


def test_unblock_and_offer_answers_are_audited(app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
        eid = stream_entries()["aa:bb:cc:00:00:01"].id
    op("POST", f"/streams/dhcp/offers/{offer_id}/decline")
    op("DELETE", f"/entries/{eid}", query_string={"block": "true"})
    with app.app_context():
        bid = InventoryBlock.query.one().id
    op("DELETE", f"/streams/dhcp/blocks/{bid}")
    with app.app_context():
        changes = [r.changes for r in ApiAudit.query.filter_by(object_type="stream").order_by(ApiAudit.id)]
        assert any("link_offer" in c for c in changes if c)
        assert any("unblocked" in c for c in changes if c)


def test_list_and_get_stream(app, put, op, manual):
    _seed_cleanup(app, put, op, manual)
    r = op("GET", "/streams", key="read")
    assert r.status_code == 200 and r.get_json()["total"] == 1
    s = op("GET", "/streams/dhcp", key="read").get_json()
    assert s["stream_id"] == "dhcp" and s["status"] == "enabled" and s["producer"] == "std-source-technitium"
    assert s["entries"] == {"total": 9, "active": 8, "deleted": 1, "missing": 0}
    assert s["blocks"] == 1 and s["link_offers"] == 1 and s["api_key"] == "sidecar"
    assert s["last_counts"]["created"] == 9 and s["last_error"] is None
    assert op("GET", "/streams/nope").status_code == 404
    assert op("POST", "/streams/dhcp/enable", key="read").status_code == 403    # read key can't change


def test_preview_has_no_side_effects(app, put, op, manual):
    manual("nas")
    put()
    r = op("GET", "/streams/dhcp/preview", key="read")
    assert r.status_code == 200
    body = r.get_json()
    actions = {i["key"]: i["action"] for i in body["items"]}
    assert body["counts"]["created"] == 9 and body["counts"]["link_offers"] == 1
    assert actions["aa:bb:cc:00:00:07"] == "link_offer" and actions["aa:bb:cc:00:00:01"] == "created"
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream").count() == 0
        assert StreamLinkOffer.query.count() == 0
        assert InventoryStream.query.one().status == "pending" and InventoryStream.query.one().last_counts is None
    op("PATCH", "/streams/dhcp", json={"network_exclude": ["Guest"]})
    assert op("GET", "/streams/dhcp/preview").get_json()["counts"]["filtered"] == 1


def test_preview_reports_each_action_and_missing(app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        eids = {k: e.id for k, e in stream_entries().items()}
    op("DELETE", f"/entries/{eids['aa:bb:cc:00:00:03']}")
    op("DELETE", f"/entries/{eids['aa:bb:cc:00:00:08']}", query_string={"block": "true"})
    body = snapshot()
    body["items"] = [i for i in body["items"] if "0004" not in i["key"]]
    body["items"][0]["ip"] = "10.9.9.9"
    body["items"].append({"key": "aa:bb:cc:00:00:ff", "name": "fresh", "ip": "10.0.0.1"})
    with app.app_context():
        s = InventoryStream.query.one()
        s.status = "disabled"       # the new snapshot is stored, not applied
        db.session.commit()
    put(body)
    pv = op("GET", "/streams/dhcp/preview").get_json()
    actions = {i["key"]: i["action"] for i in pv["items"]}
    assert actions["aa:bb:cc:00:00:01"] == "updated" and actions["aa:bb:cc:00:00:03"] == "restored"
    assert actions["aa:bb:cc:00:00:08"] == "blocked" and actions["aa:bb:cc:00:00:ff"] == "created"
    assert actions["aa:bb:cc:00:00:02"] == "unchanged" and actions["aa:bb:cc:00:00:07"] == "link_offer"
    assert [m["key"] for m in pv["missing"]] == ["aa:bb:cc:00:00:04"]


def test_preview_without_a_snapshot_is_409(app, put, op):
    put()
    op("POST", "/streams/dhcp/ignore")
    assert op("GET", "/streams/dhcp/preview").status_code == 409


def test_customised_entries_lists_what_the_operator_changed(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        e.name_source, e.description = "ui_edit", "x"
        db.session.commit()
        stream = InventoryStream.query.one()
        assert streams.customised_entries(stream) == [{"id": e.id, "name": e.container_name,
                                                       "reasons": ["renamed", "description"]}]


# --- failure handling ---------------------------------------------------------------------


def test_a_failed_apply_rolls_back_and_records_the_error(app, put, op, monkeypatch, client, keys):
    enabled_stream(app, put, op)

    def boom(stream, the_plan, now):
        db.session.add(ServiceEntry(host=None, container_name="half", source="stream",
                                    last_updated=datetime.now()))
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(streams, "_execute", boom)
    r = put()
    assert r.status_code == 500
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="half").count() == 0     # nothing half-applied
        assert "disk on fire" in InventoryStream.query.one().last_error
    monkeypatch.undo()
    assert put().status_code == 200
    with app.app_context():
        assert InventoryStream.query.one().last_error is None


# --- notifications -------------------------------------------------------------------------


def test_mqtt_payload_fields_and_ha_model(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        payload = notify_state.entry_payload(e, entry_health(e), None)
        assert (payload["ip"], payload["mac"], payload["network"], payload["stream"], payload["source"]) == \
            ("10.0.40.21", "aa:bb:cc:00:00:01", "CrzyIoT", "DHCP", "stream")
        assert "attributes" not in payload
        assert notify_ha.entry_device("std_x", "STD", e)["model"] == "DHCP"
        for attr in ("ip", "mac", "network", "stream_id", "inventory_missing"):
            assert attr in notify_state._ENTRY_ATTRS
        plain = ServiceEntry(host="h", container_name="svc", source="notifier", last_updated=datetime.now())
        p2 = notify_state.entry_payload(plain, entry_health(plain), None)
        assert (p2["ip"], p2["mac"], p2["network"], p2["stream"]) == (None, None, None, None)
        assert notify_ha.entry_device("std_x", "STD", plain)["model"] == "Docker container"


def test_renaming_a_stream_republishes_the_entries(app, put, op):
    enabled_stream(app, put, op)
    requests = []
    import notify
    original = notify.request_sync
    notify.request_sync = lambda *a, **k: requests.append(1)
    try:
        op("PATCH", "/streams/dhcp", json={"display_name": "Reservations"})
    finally:
        notify.request_sync = original
    assert requests


def test_apply_is_one_commit_and_one_sync(app, put, op):
    import notify
    put()
    calls = []
    original = notify.request_sync
    notify.request_sync = lambda *a, **k: calls.append(1)
    try:
        op("POST", "/streams/dhcp/enable")
    finally:
        notify.request_sync = original
    assert len(calls) == 1


# --- entries API shows stream facts -----------------------------------------------------------


def test_entry_api_carries_the_inventory_block(app, put, op, manual):
    enabled_stream(app, put, op)
    items = op("GET", "/entries", query_string={"source": "stream"}).get_json()["items"]
    assert len(items) == 10
    e = next(i for i in items if i["name"] == "shelly-pump")
    assert e["source"] == "stream" and e["host"] is None
    assert e["inventory"] == {"stream_id": "dhcp", "stream": "DHCP", "key": "aa:bb:cc:00:00:01",
                              "mac": "aa:bb:cc:00:00:01", "ip": "10.0.40.21", "network": "CrzyIoT",
                              "attributes": e["inventory"]["attributes"], "missing": False,
                              "name_source": "stream"}
    assert e["inventory"]["attributes"]["scope"] == "CrzyIoT"
    mid = manual("plain")
    assert op("GET", f"/entries/{mid}").get_json()["inventory"] is None


# --- backups ---------------------------------------------------------------------------------------


def test_a_stream_entry_restores_from_backup_as_manual(app, put, op, admin_client):
    from tests.test_entry_sources import _restore
    enabled_stream(app, put, op)
    with app.app_context():
        record = stream_entries()["aa:bb:cc:00:00:01"].to_dict()
        assert record["source"] == "stream" and record["mac"] == "aa:bb:cc:00:00:01"
        assert "stream_id" not in record and "stream_key" not in record
    op("DELETE", "/streams/dhcp", query_string={"cleanup": "purge"})
    assert _restore(admin_client, [record]).status_code == 302
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="shelly-pump").one()
        assert (e.source, e.stream_id, e.stream_key, e.ip, e.mac, e.host) == \
            ("manual", None, None, "10.0.40.21", "aa:bb:cc:00:00:01", None)


def test_restore_does_not_overwrite_a_live_stream_entry(app, put, op, admin_client):
    from tests.test_entry_sources import _restore
    enabled_stream(app, put, op)
    with app.app_context():
        record = stream_entries()["aa:bb:cc:00:00:01"].to_dict()
    record["ip"] = "1.2.3.4"
    assert _restore(admin_client, [record]).status_code == 302
    with app.app_context():
        e = stream_entries()["aa:bb:cc:00:00:01"]
        assert e.ip == "10.0.40.21" and e.source == "stream"
        assert ServiceEntry.query.filter_by(container_name="shelly-pump").count() == 1


# --- scale -------------------------------------------------------------------------------------------


def test_apply_at_5000_items_is_a_handful_of_queries(app, put, op):
    items = [{"key": f"{i:012x}", "name": f"dev{i}", "ip": f"10.1.{i // 250}.{i % 250 + 1}",
              "network": "Big", "attributes": {"n": i}} for i in range(5000)]
    body = snapshot(items=items)
    put(body)
    r = op("POST", "/streams/dhcp/enable")
    assert r.get_json()["counts"]["created"] == 5000
    changed = copy.deepcopy(body)
    for item in changed["items"][:100]:
        item["ip"] = "10.2.0.1"
    selects = []

    def count(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            selects.append(statement)

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", count)
    try:
        r = put(changed)
    finally:
        with app.app_context():
            event.remove(db.engine, "before_cursor_execute", count)
    assert r.status_code == 200 and r.get_json()["counts"]["updated"] == 100
    assert r.get_json()["counts"]["unchanged"] == 4900
    # key lookup + stream load + entries + blocks + offers + manual candidates + a few bookkeeping reads
    assert len(selects) <= 15, len(selects)


# --- OpenAPI -------------------------------------------------------------------------------------------


def test_spec_describes_the_ingest_routes(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    put_op = spec["paths"]["/streams/{stream_id}/snapshot"]["put"]
    assert put_op["x-required-scope"] == "ingest" and put_op["security"] == [{"bearerAuth": []}]
    assert {"200", "202", "400", "401", "403", "409", "413"} <= set(put_op["responses"])
    assert put_op["requestBody"]["content"]["application/json"]["schema"] == \
        {"$ref": "#/components/schemas/StreamSnapshotPut"}
    schemas = spec["components"]["schemas"]
    assert schemas["StreamSnapshotPut"]["additionalProperties"] is False
    assert schemas["StreamSnapshotItem"]["additionalProperties"] is False
    param = next(p for p in put_op["parameters"] if p["name"] == "stream_id")
    assert param["schema"]["type"] == "string" and "pattern" in param["schema"]
    assert spec["paths"]["/streams/{stream_id}/status"]["get"]["x-required-scope"] == "ingest"
    assert "StreamOut" in schemas and "SnapshotAppliedOut" in schemas


# --- migration ------------------------------------------------------------------------------------------


def _alembic(tmp_path, db_path, *args):
    ini = tmp_path / "alembic.ini"
    text = open(os.path.join(REPO_ROOT, "alembic.ini")).read()
    text = re.sub(r"(?m)^script_location\s*=.*$", f"script_location = {REPO_ROOT}/alembic", text)
    text = re.sub(r"(?m)^sqlalchemy.url\s*=.*$", f"sqlalchemy.url = sqlite:///{db_path}", text)
    ini.write_text(text)
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ini), *args],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result


def _schema(db_path):
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {r[1] for r in con.execute("PRAGMA table_info(service_entry)")}
    idx = {r[1]: r for r in con.execute("PRAGMA index_list(service_entry)")}
    con.close()
    return tables, cols, idx


def test_migration_upgrade_and_downgrade_on_a_migrated_db(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS_HEAD)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO service_entry (host, container_name, last_updated, is_static, "
                "health_check_verify_tls, source) VALUES ('h', 'keep-me', '2026-01-01 00:00:00', 0, 1, 'notifier')")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    tables, cols, idx = _schema(db_path)
    assert {"inventory_stream", "inventory_block", "stream_link_offer"} <= tables
    assert {"stream_id", "stream_key", "mac", "ip", "network", "attributes", "inventory_missing",
            "name_source"} <= cols
    assert {"ix_service_entry_stream_id", "ux_service_entry_stream_key",
            "ix_service_entry_host_container_name", "ix_service_entry_deleted_at"} <= set(idx)
    con = sqlite3.connect(db_path)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='ux_service_entry_stream_key'").fetchone()[0]
    assert "WHERE stream_id IS NOT NULL" in sql and "UNIQUE" in sql
    for name in ("ix_inventory_stream_api_key_id", "ix_inventory_block_stream_id",
                 "ix_stream_link_offer_stream_id", "ix_stream_link_offer_entry_id"):
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone(), name
    # existing rows are untouched and the new flag defaults to false
    assert con.execute("SELECT container_name, inventory_missing, stream_id FROM service_entry").fetchall() == \
        [("keep-me", 0, None)]
    # the partial unique index: two non-stream rows may share NULL; the same stream+key may not
    con.execute("INSERT INTO inventory_stream (stream_id, display_name, producer, producer_version, key_type, "
                "status, first_seen_at, created_at, updated_at) VALUES ('s','S','p','1','mac','enabled',"
                "'2026-01-01','2026-01-01','2026-01-01')")
    base = ("INSERT INTO service_entry (container_name, last_updated, is_static, health_check_verify_tls, "
            "source, stream_id, stream_key) VALUES (?, '2026-01-01', 0, 1, 'stream', ?, ?)")
    con.execute(base, ("a", 1, "k1"))
    con.execute(base, ("b", 1, "k2"))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute(base, ("c", 1, "k1"))
    con.rollback()
    con.close()

    # downgrade: stream rows become manual, everything the migration added is gone, other rows survive
    con = sqlite3.connect(db_path)
    con.execute(base, ("a", 1, "k1"))
    con.commit()
    con.close()
    _alembic(tmp_path, db_path, "downgrade", PREVIOUS_HEAD)
    tables, cols, idx = _schema(db_path)
    assert not ({"inventory_stream", "inventory_block", "stream_link_offer"} & tables)
    assert not ({"stream_id", "stream_key", "mac", "ip", "network", "attributes", "inventory_missing",
                 "name_source"} & cols)
    assert not {"ix_service_entry_stream_id", "ux_service_entry_stream_key"} & set(idx)
    assert {"ix_service_entry_host_container_name", "ix_service_entry_deleted_at"} <= set(idx)
    con = sqlite3.connect(db_path)
    assert dict(con.execute("SELECT container_name, source FROM service_entry")) == \
        {"keep-me": "notifier", "a": "manual"}
    con.close()
    _alembic(tmp_path, db_path, "upgrade", "head")        # and back up again


def test_migration_on_an_empty_db_reaches_a_single_head(tmp_path):
    db_path = str(tmp_path / "empty.db")
    _alembic(tmp_path, db_path, "upgrade", "head")
    heads = _alembic(tmp_path, db_path, "heads").stdout
    assert heads.count("(head)") == 1 and "a9d3c5e7f102" in heads
    tables, cols, _ = _schema(db_path)
    assert "inventory_stream" in tables and "name_source" in cols
    _alembic(tmp_path, db_path, "downgrade", "base")
