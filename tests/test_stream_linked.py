"""Linked stream entries are unlinked, never deleted, by stream cleanup (PRD 5.10, 18.7).

A manual entry that joined a stream (accept / link / Convert) is `stream_linked`; its
pre-link host is kept so unlinking restores it."""

# The shared fixtures come from test_streams by import, which ruff reads as unused/redefined.
# ruff: noqa: F401, F811

import sqlite3
from datetime import datetime

import pytest

import mgmt_openapi
import notify
import streams
from extensions import db
from models import (
    ApiAudit,
    InventoryBlock,
    InventoryStream,
    ServiceEntry,
    StreamLinkOffer,
)
from tests.test_ha_discovery import _cfg, _node, _setup
from tests.test_mgmt_api_keys import _bearer
from tests.test_notifications import Factory
from tests.test_state_publishing import _sync
from tests.test_streams import (
    _alembic,
    _schema,
    enabled_stream,
    keys,
    manual,
    op,
    put,
    snapshot,
    stream_entries,
)

LINK_A = "aa:bb:cc:00:00:04"     # printer
LINK_B = "aa:bb:cc:00:00:05"     # dup-name


def _seed(app, put, op, manual):
    """A pending stream with two linked entries (one with a host), then enabled:
    eight stream-created entries, two linked. Returns (linked with host, linked without)."""
    assert put().status_code == 202
    a = manual("my-printer", host="docker1")
    b = manual("my-hostless")
    assert op("POST", "/streams/dhcp/link", json={"entry_id": a, "key": LINK_A}).status_code == 200
    assert op("POST", "/streams/dhcp/link", json={"entry_id": b, "key": LINK_B}).status_code == 200
    assert op("POST", "/streams/dhcp/enable").status_code == 200
    return a, b


def _get(app, eid):
    with app.app_context():
        return db.session.get(ServiceEntry, eid)


# --- link sets the flags ------------------------------------------------------------------


def test_link_marks_the_entry_and_keeps_its_old_host(app, put, op, manual):
    a, b = _seed(app, put, op, manual)
    with app.app_context():
        ea, eb = db.session.get(ServiceEntry, a), db.session.get(ServiceEntry, b)
        assert (ea.stream_linked, ea.pre_link_host, ea.host) == (True, "docker1", None)
        assert (eb.stream_linked, eb.pre_link_host) == (True, None)
        assert {e.stream_linked for e in stream_entries().values()} == {True, False}
        assert sum(e.stream_linked for e in stream_entries().values()) == 2
    body = op("GET", f"/entries/{a}").get_json()
    assert body["inventory"]["linked"] is True
    own = op("GET", f"/entries/{_get_own(app)}").get_json()
    assert own["inventory"]["linked"] is False
    assert op("GET", "/streams/dhcp").get_json()["entries"]["linked"] == 2


def _get_own(app):
    with app.app_context():
        return stream_entries()["aa:bb:cc:00:00:01"].id


def test_accepting_a_link_offer_marks_the_entry(app, put, op, manual):
    pump = manual("shelly-pump", host="h9")
    enabled_stream(app, put, op)
    with app.app_context():
        offer = StreamLinkOffer.query.filter_by(entry_id=pump).first()
        assert offer is not None
        oid = offer.id
    assert op("POST", f"/streams/dhcp/offers/{oid}/accept").status_code == 200
    e = _get(app, pump)
    assert (e.stream_linked, e.pre_link_host, e.host) == (True, "h9", None)


# --- unlink -----------------------------------------------------------------------------


def test_unlink_restores_the_host_and_clears_the_flags(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    r = op("POST", f"/entries/{a}/unlink")
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert (body["host_restored"], body["host_clash"], body["blocked"], body["host"]) == (True, False, False, "docker1")
    assert body["entry"]["source"] == "manual" and body["entry"]["host"] == "docker1"
    assert body["entry"]["inventory"] is None
    e = _get(app, a)
    assert (e.source, e.stream_id, e.stream_key, e.stream_linked, e.pre_link_host, e.name_source) == \
        ("manual", None, None, False, None, None)
    assert (e.mac, e.ip) == ("aa:bb:cc:00:00:04", "10.0.10.31")           # observation kept
    with app.app_context():
        assert InventoryBlock.query.count() == 0
        row = ApiAudit.query.filter_by(object_type="entry", object_id=str(a)).all()
        assert row


def test_unlink_a_host_that_is_now_taken_stays_hostless(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    manual("my-printer", host="docker1")                                   # takes (docker1, my-printer)
    body = op("POST", f"/entries/{a}/unlink").get_json()
    assert (body["host"], body["host_restored"], body["host_clash"]) == (None, False, True)
    assert _get(app, a).host is None and _get(app, a).source == "manual"


def test_unlink_a_stream_created_entry_just_makes_it_manual(app, put, op, manual):
    enabled_stream(app, put, op)
    own = _get_own(app)
    body = op("POST", f"/entries/{own}/unlink").get_json()
    assert (body["host_restored"], body["host_clash"], body["host"]) == (False, False, None)
    e = _get(app, own)
    assert (e.source, e.stream_id, e.host) == ("manual", None, None)


def test_unlink_errors_and_scope(app, put, op, manual):
    enabled_stream(app, put, op)
    plain = manual("plain")
    assert op("POST", f"/entries/{plain}/unlink").status_code == 409        # not a stream entry
    assert op("POST", "/entries/9999/unlink").status_code == 404
    own = _get_own(app)
    assert op("POST", f"/entries/{own}/unlink", json={"block": True, "x": 1}).status_code == 400
    assert op("POST", f"/entries/{own}/unlink", key="read").status_code == 403
    assert op("POST", f"/entries/{own}/unlink", key="ingest").status_code == 403
    op("DELETE", f"/entries/{own}")
    assert op("POST", f"/entries/{own}/unlink").status_code == 409          # deleted


def test_unlink_with_block_is_not_re_added_or_re_offered(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    body = op("POST", f"/entries/{a}/unlink", json={"block": True}).get_json()
    assert body["blocked"] is True
    with app.app_context():
        assert InventoryBlock.query.filter_by(key=LINK_A).count() == 1
    assert put().status_code == 200
    with app.app_context():
        assert LINK_A not in stream_entries()
        assert StreamLinkOffer.query.filter_by(key=LINK_A).count() == 0


def test_unlink_without_block_lets_the_next_snapshot_bring_the_item_back(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    assert op("POST", f"/entries/{a}/unlink", json={"block": False}).get_json()["blocked"] is False
    assert put().status_code == 200
    with app.app_context():
        assert InventoryBlock.query.count() == 0
        # either a fresh stream entry or an offer to link the manual entry again
        assert LINK_A in stream_entries() or StreamLinkOffer.query.filter_by(key=LINK_A).count() == 1


# --- cleanup respects linked entries --------------------------------------------------------


def test_disable_keep_leaves_linked_entries_attached(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    res = op("POST", "/streams/dhcp/disable", json={"cleanup": "keep"}).get_json()["result"]
    assert (res["entries"], res["kept"], res["unlinked"]) == (10, 10, 0)
    e = _get(app, a)
    assert e.source == "stream" and e.stream_linked is True and e.host is None


@pytest.mark.parametrize("cleanup,own_deleted,own_left", [("soft_delete", 8, 8), ("purge", 0, 0)])
def test_disable_soft_delete_and_purge_unlink_linked_entries(app, put, op, manual, cleanup, own_deleted, own_left):
    a, b = _seed(app, put, op, manual)
    res = op("POST", "/streams/dhcp/disable", json={"cleanup": cleanup}).get_json()["result"]
    assert res["entries"] == 10 and res["unlinked"] == 2
    assert res["soft_deleted"] == own_deleted and res["purged"] == (8 if cleanup == "purge" else 0)
    with app.app_context():
        ea, eb = db.session.get(ServiceEntry, a), db.session.get(ServiceEntry, b)
        assert ea is not None and eb is not None                          # never deleted
        assert (ea.source, ea.deleted_at, ea.host, ea.stream_linked) == ("manual", None, "docker1", False)
        assert (eb.source, eb.deleted_at, eb.host) == ("manual", None, None)
        assert ServiceEntry.query.filter_by(source="stream").count() == own_left
        assert ServiceEntry.query.filter(ServiceEntry.deleted_at.isnot(None)).count() == own_deleted


def test_delete_stream_keep_unlinks_linked_with_their_host_and_others_become_manual(app, put, op, manual):
    a, b = _seed(app, put, op, manual)
    res = op("DELETE", "/streams/dhcp", query_string={"cleanup": "keep"}).get_json()["result"]
    assert res["entries"] == 10 and res["unlinked"] == 2 and res["kept"] == 8
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream").count() == 0
        assert db.session.get(ServiceEntry, a).host == "docker1"
        assert ServiceEntry.query.filter_by(source="manual", deleted_at=None).count() == 10


@pytest.mark.parametrize("cleanup,soft,purged,remaining_active", [("soft_delete", 8, 0, 2), ("purge", 0, 8, 2)])
def test_delete_stream_soft_delete_and_purge_never_delete_linked(app, put, op, manual, cleanup, soft, purged,
                                                                 remaining_active):
    a, b = _seed(app, put, op, manual)
    res = op("DELETE", "/streams/dhcp", query_string={"cleanup": cleanup}).get_json()["result"]
    assert (res["unlinked"], res["soft_deleted"], res["purged"]) == (2, soft, purged)
    with app.app_context():
        assert InventoryStream.query.count() == 0
        active = ServiceEntry.query.filter(ServiceEntry.deleted_at.is_(None)).all()
        assert {e.id for e in active} == {a, b} and all(e.source == "manual" for e in active)
        assert db.session.get(ServiceEntry, a).host == "docker1"


def test_an_already_deleted_linked_entry_is_unlinked_not_purged(app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    op("DELETE", f"/entries/{a}")
    op("POST", "/streams/dhcp/disable", json={"cleanup": "purge"})
    e = _get(app, a)
    assert e is not None and e.source == "manual" and e.deleted_at is not None


def test_cleanup_without_linked_entries_reports_zero(app, put, op):
    enabled_stream(app, put, op)
    res = op("POST", "/streams/dhcp/disable", json={"cleanup": "soft_delete"}).get_json()["result"]
    assert res["unlinked"] == 0 and res["soft_deleted"] == 10


def test_linked_entries_are_not_listed_as_customised(app, put, op, manual):
    _seed(app, put, op, manual)
    with app.app_context():
        stream = streams.find_stream("dhcp")
        assert [c["name"] for c in streams.customised_entries(stream)] == []
        assert [(x["name"], x["host"]) for x in streams.linked_entries(stream)] == \
            [("my-printer", "docker1"), ("my-hostless", None)]


# --- registry ------------------------------------------------------------------------------


def test_unlink_route_is_in_the_openapi_registry():
    ops = {(o.method, o.path): o for o in mgmt_openapi.OPERATIONS}
    op_ = ops[("POST", "/entries/{id}/unlink")]
    assert op_.scope == "write" and op_.request.__name__ == "EntryUnlinkRequest"
    spec = mgmt_openapi.build_spec() if hasattr(mgmt_openapi, "build_spec") else None
    if spec:
        assert "/entries/{id}/unlink" in spec["paths"]


# --- UI ------------------------------------------------------------------------------------


def test_edit_page_shows_linked_note_and_unlink_form(admin_client, app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    html = admin_client.get(f"/edit/{a}").get_data(as_text=True)
    assert "Linked from a manual entry" in html and "docker1" in html
    assert "Allow re-offering" in html and "Don&#39;t re-add" in html or "Don't re-add" in html
    own = _get_own(app)
    html = admin_client.get(f"/edit/{own}").get_data(as_text=True)
    assert "Linked from a manual entry" not in html and "Unlink from stream" in html


def test_unlink_form_posts_and_flashes(admin_client, app, put, op, manual):
    a, _b = _seed(app, put, op, manual)
    r = admin_client.post(f"/edit/{a}/stream-unlink", data={"block": "1"})
    assert r.status_code == 302
    e = _get(app, a)
    assert e.source == "manual" and e.host == "docker1"
    with app.app_context():
        assert InventoryBlock.query.filter_by(key=LINK_A).count() == 1


def test_dialog_lists_linked_entries_and_says_they_are_never_deleted(admin_client, app, put, op, manual):
    _seed(app, put, op, manual)
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "2 linked entries go back to manual entries (with their host); they are never deleted" in html


# --- migration backfill ---------------------------------------------------------------------


def test_migration_backfills_linked_entries_by_id_order(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", "a9d3c5e7f102")
    con = sqlite3.connect(db_path)
    for pk, slug in ((1, "s1"), (2, "s2")):
        con.execute("INSERT INTO inventory_stream (id, stream_id, display_name, producer, producer_version, "
                    "key_type, status, first_seen_at, created_at, updated_at) VALUES (?,?,?,'p','1','mac',"
                    "'enabled','2026-01-01','2026-01-01','2026-01-01')", (pk, slug, slug))
    ins = ("INSERT INTO service_entry (id, container_name, last_updated, is_static, health_check_verify_tls, "
           "source, stream_id, stream_key, name_source) VALUES (?, ?, '2026-01-01', 0, 1, ?, ?, ?, ?)")
    rows = [
        (1, "linked-before", "stream", 1, "k1", "ui_edit"),      # lower than the first stream-named one
        (2, "stream-made", "stream", 1, "k2", "stream"),
        (3, "renamed-later", "stream", 1, "k3", "ui_edit"),      # higher: a renamed stream entry
        (4, "other-stream-ui", "stream", 2, "k4", "ui_edit"),    # stream s2 has no stream-named entry
        (5, "manual", "manual", None, None, None),
    ]
    for r in rows:
        con.execute(ins, r)
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    _tables, cols, _idx = _schema(db_path)
    assert {"stream_linked", "pre_link_host"} <= cols
    con = sqlite3.connect(db_path)
    got = {n: (linked, host) for n, linked, host in con.execute(
        "SELECT container_name, stream_linked, pre_link_host FROM service_entry")}
    assert got == {"linked-before": (1, None), "stream-made": (0, None), "renamed-later": (0, None),
                   "other-stream-ui": (0, None), "manual": (0, None)}
    con.close()
    _alembic(tmp_path, db_path, "downgrade", "a9d3c5e7f102")
    _alembic(tmp_path, db_path, "upgrade", "head")


# --- Home Assistant: the device moves back to the hub --------------------------------------


def test_unlinked_entry_moves_from_the_stream_hub_to_the_std_hub(app):
    factory = Factory()
    notify.set_client_factory(factory)
    pub, client = _setup(app, factory)
    with app.app_context():
        stream = InventoryStream(stream_id="dhcp", display_name="DHCP", producer="p", producer_version="1",
                                 key_type="mac", status="enabled", last_item_count=1)
        db.session.add(stream)
        db.session.flush()
        from models import ensure_url_checks
        entry = ServiceEntry(host=None, container_name="linked-thing", source="stream", stream_id=stream.id,
                             stream_key="aa:00:00:00:00:01", internalurl="http://x", ha_publish=True,
                             stream_linked=True, pre_link_host="docker1", name_source="ui_edit",
                             last_updated=datetime.now())
        db.session.add(entry)
        db.session.flush()
        ensure_url_checks(entry)
        entry.url_check("internal").enabled = True
        db.session.commit()
        eid = entry.id
        _sync(pub, app)
    node = _node(app)
    assert _cfg(client, node, "sensor", f"entry_{eid}_state")["device"]["via_device"] == f"{node}_stream_dhcp"
    with app.app_context():
        streams.unlink_entry(db.session.get(ServiceEntry, eid))
        _sync(pub, app)
    assert _cfg(client, node, "sensor", f"entry_{eid}_state")["device"]["via_device"] == node
