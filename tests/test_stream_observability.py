"""Inventory stream observability (PRD 18.9, inv-08): rejected snapshots, staleness,
the health summary block, MQTT `stale` + the HA problem sensor, the `missing`
lifecycle (badge, since, auto soft-delete and its exemptions), IP-following checks,
and no automatic checks without `default_checks`."""

# Shared fixtures come from test_streams by import (ruff reads them as unused/redefined).
# ruff: noqa: F401, F811

import logging
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

import jobs
import notify
import notify_ha
import notify_state
import streams
from api_version import API_REVISION, API_REVISION_HISTORY
from extensions import db
from models import (
    CHECK_KIND_SERVICE,
    ApiAudit,
    Group,
    HealthCheck,
    InventoryStream,
    ServiceEntry,
)
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_streams import (
    _alembic,
    enabled_stream,
    keys,
    manual,
    op,
    put,
    snapshot,
)

SLUG = "dhcp"


def _stream():
    return InventoryStream.query.filter_by(stream_id=SLUG).one()


def _age(app, seconds, **fields):
    """Pretend the last snapshot arrived `seconds` ago (and set other stream fields)."""
    with app.app_context():
        s = _stream()
        s.last_snapshot_at = datetime.utcnow() - timedelta(seconds=seconds)
        for k, v in fields.items():
            setattr(s, k, v)
        db.session.commit()


@pytest.fixture(autouse=True)
def fresh_watch():
    streams.reset_stale_watch()
    yield
    streams.reset_stale_watch()


# --- revision ------------------------------------------------------------------------


def test_api_revision_3_has_its_history_row():
    # Revision 3 is the stream observability set; later revisions append rows (4 in 0.11.0).
    assert API_REVISION >= 3
    assert 3 in [row[0] for row in API_REVISION_HISTORY]
    assert API_REVISION_HISTORY[-1][0] == API_REVISION


# --- rejected snapshots -----------------------------------------------------------------


def test_rejections_are_recorded_on_an_existing_stream(app, put, op, client, keys):
    enabled_stream(app, put, op)
    bad = snapshot()
    bad["items"][0]["ip"] = "not-an-ip"
    assert put(bad).status_code == 400
    with app.app_context():
        s = _stream()
        assert s.last_rejected_at is not None
        assert s.last_rejection.startswith("400: items.0.ip")
        assert s.last_error is None                       # kept apart from apply failures
        assert streams.is_rejecting(s)
    dup = snapshot()
    dup["items"][1]["key"] = dup["items"][0]["key"]
    assert put(dup).status_code == 400
    with app.app_context():
        assert _stream().last_rejection.startswith("400: items.1.key")
    assert put(snapshot(key_type="name")).status_code == 409
    with app.app_context():
        assert _stream().last_rejection.startswith("409: This stream's key_type")
    big = b'{"x": "' + b"a" * (streams.MAX_BODY_BYTES + 10) + b'"}'
    r = client.put(f"/api/v1/streams/{SLUG}/snapshot", data=big, content_type="application/json",
                   headers=_bearer(keys["ingest"]))
    assert r.status_code == 413
    with app.app_context():
        assert _stream().last_rejection.startswith("413:")
    body = op("GET", f"/streams/{SLUG}").get_json()
    assert body["last_rejected_at"].endswith("Z") and body["rejecting"] is True
    # a good snapshot makes it current again; the rejection stays for the record
    assert put().status_code == 200
    body = op("GET", f"/streams/{SLUG}").get_json()
    assert body["rejecting"] is False and body["last_rejection"].startswith("413:")
    with app.app_context():                               # snapshot PUTs are never audited
        assert ApiAudit.query.filter(ApiAudit.path.like("%/snapshot")).count() == 0


def test_rejection_without_a_stream_row_or_from_another_key_is_not_recorded(app, put, client):
    bad = snapshot()
    bad["items"][0]["ip"] = "nope"
    assert put(bad).status_code == 400
    with app.app_context():
        assert InventoryStream.query.count() == 0
    assert put().status_code == 202
    other = _key(app, "other-sidecar", "ingest")[1]
    r = client.put(f"/api/v1/streams/{SLUG}/snapshot", json=bad, headers=_bearer(other))
    assert r.status_code == 403
    with app.app_context():
        assert _stream().last_rejected_at is None


# --- producer interval (ingest contract, revision 3) -------------------------------------------


def test_producer_interval_is_optional_and_validated(app, put, op):
    assert put(snapshot(snapshot_interval_seconds=300)).status_code == 202
    with app.app_context():
        assert _stream().producer_interval_seconds == 300
    assert put(snapshot(snapshot_interval_seconds=59)).status_code == 400
    assert put(snapshot(snapshot_interval_seconds=True)).status_code == 400
    assert put(snapshot()).status_code == 202            # absent: an older producer, cleared
    with app.app_context():
        assert _stream().producer_interval_seconds is None


def test_operator_interval_wins_over_the_producer(app, put, op):
    enabled_stream(app, put, op, body=snapshot(snapshot_interval_seconds=300))
    body = op("GET", f"/streams/{SLUG}").get_json()
    assert (body["effective_interval_seconds"], body["interval_source"]) == (300, "producer")
    r = op("PATCH", f"/streams/{SLUG}", json={"expected_interval_seconds": 600})
    assert r.status_code == 200 and r.get_json()["effective_interval_seconds"] == 600
    assert r.get_json()["interval_source"] == "operator" and r.get_json()["stale_after_seconds"] == 1200
    assert op("PATCH", f"/streams/{SLUG}", json={"expected_interval_seconds": 30}).status_code == 400
    assert op("PATCH", f"/streams/{SLUG}", json={"expected_interval_seconds": "600"}).status_code == 400
    r = op("PATCH", f"/streams/{SLUG}", json={"expected_interval_seconds": None})
    assert r.get_json()["interval_source"] == "producer"


# --- staleness ------------------------------------------------------------------------


def test_default_interval_and_grace_factor_boundary(app, put, op):
    enabled_stream(app, put, op)
    limit = streams.DEFAULT_INTERVAL_SECONDS * streams.STALE_GRACE_FACTOR
    assert streams.STALE_GRACE_FACTOR == 2 and streams.DEFAULT_INTERVAL_SECONDS == 900
    with app.app_context():
        s = _stream()
        now = datetime.utcnow()
        s.last_snapshot_at = now - timedelta(seconds=limit)
        assert not streams.is_stale(s, now)                # exactly 2 x: not yet
        s.last_snapshot_at = now - timedelta(seconds=limit + 1)
        assert streams.is_stale(s, now)
        s.last_snapshot_at = now - timedelta(seconds=streams.DEFAULT_INTERVAL_SECONDS + 1)
        assert not streams.is_stale(s, now)                # one missed post is not stale
        db.session.rollback()


@pytest.mark.parametrize("status", ["pending", "disabled", "ignored"])
def test_only_enabled_streams_go_stale(app, put, status):
    put()
    _age(app, 10 * 86400, status=status)
    with app.app_context():
        assert not streams.is_stale(_stream())
        assert streams.stale_streams() == []


def test_stale_on_the_api_list_summary_and_header(app, put, op, admin_client):
    enabled_stream(app, put, op)
    _age(app, 3600)
    body = op("GET", "/streams").get_json()
    assert body["stale"] == 1 and body["items"][0]["stale"] is True
    assert "No snapshot for 60 min (expected every 15 min)" == body["items"][0]["stale_message"]
    summary = op("GET", "/health/summary", key="read").get_json()
    assert summary["counts"]["streams_stale"] == 1
    (line,) = summary["stale_streams"]
    assert line["stream_id"] == SLUG and line["state"] == "down" and line["since"].endswith("Z")
    (row,) = summary["streams"]
    assert row["stale"] is True and row["last_item_count"] == 10
    assert row["entries_active"] == 10 and row["entries_missing"] == 0
    # entries of a stale stream are not marked: their own checks decide their health
    assert summary["counts"]["failing"] == 0 and summary["failing"] == []
    html = admin_client.get("/").get_data(as_text=True)
    assert 'id="settings-stale-streams"' in html and "1 inventory stream stale" in html
    assert "stream stale (no recent snapshot)" in html     # muted hint in the entry tooltips
    page = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "stream-stale-badge" in page
    _age(app, 0)
    assert 'id="settings-stale-streams"' not in admin_client.get("/").get_data(as_text=True)


def test_stale_rejecting_stream_says_why(app, put, op):
    enabled_stream(app, put, op)
    bad = snapshot()
    bad["items"][0]["ip"] = "nope"
    put(bad)
    _age(app, 7200, last_rejected_at=datetime.utcnow())
    line = op("GET", "/health/summary", key="read").get_json()["stale_streams"][0]
    assert "last snapshot rejected: 400: items.0.ip" in line["message"]


def test_watch_staleness_logs_transitions_once_and_requests_a_sync(app, put, op, monkeypatch, caplog):
    enabled_stream(app, put, op)
    syncs = []
    monkeypatch.setattr(notify, "request_sync", lambda *a, **k: syncs.append(1))
    caplog.set_level(logging.INFO, logger="streams")
    with app.app_context():
        assert streams.watch_staleness(force=True) == set() and syncs == []
    _age(app, 3600)            # (the commit listener asks for a sync of its own; not counted)
    syncs.clear()
    with app.app_context():
        assert streams.watch_staleness(force=True) == {SLUG}
        assert streams.watch_staleness(force=True) == {SLUG}
        assert streams.watch_staleness() == {SLUG}         # throttled: no query, same answer
    assert len(syncs) == 1
    assert sum("dhcp is stale" in r.message for r in caplog.records) == 1
    _age(app, 0)
    syncs.clear()
    with app.app_context():
        assert streams.watch_staleness(force=True) == set()
    assert len(syncs) == 1 and any("receiving snapshots again" in r.message for r in caplog.records)


def test_health_tick_runs_the_staleness_watch(app, monkeypatch):
    called = []
    monkeypatch.setattr(streams, "watch_staleness", lambda *a, **k: called.append(1))
    sched = jobs.HealthScheduler(app, executor=None)
    try:
        sched.tick()
    finally:
        sched.shutdown()
    assert called == [1]


# --- MQTT and Home Assistant ----------------------------------------------------------------


def test_stream_payload_carries_stale_and_ha_has_a_problem_sensor(app, put, op):
    enabled_stream(app, put, op)
    _age(app, 3600)
    with app.app_context():
        s = _stream()
        payload = notify_state.stream_payload(s, 10, 0, 0)
        assert payload["stale"] is True and payload["expected_interval_seconds"] == 900
        assert payload["last_rejected_at"] is None
        configs = notify_ha.stream_configs("std", "homeassistant", "node", "STD", s, "0.10.0")
        problem = configs["homeassistant/binary_sensor/node/stream_dhcp_problem/config"]
        assert problem["device_class"] == "problem"
        assert problem["state_topic"] == "std/stream/dhcp"
        assert problem["value_template"] == "{{ 'ON' if value_json.stale else 'OFF' }}"
        assert problem["device"]["identifiers"] == ["node_stream_dhcp"]
    _age(app, 0)
    with app.app_context():
        assert notify_state.stream_payload(_stream(), 10, 0, 0)["stale"] is False


def test_entry_payload_carries_missing_and_since(app, put, op):
    enabled_stream(app, put, op)
    body = snapshot()
    body["items"] = body["items"][1:]
    put(body)
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="shelly-pump").one()
        p = notify_state.entry_payload(e, notify_state.health_state.entry_health(e), None)
        assert p["missing"] is True and p["missing_since"].endswith("Z")
        assert p["state"] == "none"                         # missing never changes the roll-up
        m = ServiceEntry(host="h", container_name="m", source="manual", last_updated=datetime.now())
        p = notify_state.entry_payload(m, notify_state.health_state.entry_health(m), None)
        assert p["missing"] is None and p["missing_since"] is None


# --- missing lifecycle -------------------------------------------------------------------


def test_missing_since_is_set_kept_and_cleared(app, put, op, admin_client):
    enabled_stream(app, put, op)
    body = snapshot()
    body["items"] = body["items"][1:]
    put(body)
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="shelly-pump").one()
        first = e.inventory_missing_since
        assert e.inventory_missing and first is not None
        eid = e.id
    put(body)                                               # still missing: the time is kept
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).inventory_missing_since == first
    api = op("GET", f"/entries/{eid}").get_json()["inventory"]
    assert api["missing"] is True and api["missing_since"].endswith("Z")
    html = admin_client.get("/").get_data(as_text=True)
    assert 'class="stream-missing"' in html and "ti-alert-triangle" in html
    edit = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'id="stream-missing-note"' in edit and "since" in edit and "data-missing-since" in edit
    tiled = admin_client.get("/tiled_dash").get_data(as_text=True)
    assert "stream-missing-fact" in tiled and "status-icon-warn stream-icon" in tiled
    put()                                                   # it comes back
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert not e.inventory_missing and e.inventory_missing_since is None


def _expiry_setup(app, put, op, days=30, default_checks=None):
    """An enabled stream whose first item has been missing for 40 days."""
    if default_checks is not None:
        put()
        assert op("PATCH", f"/streams/{SLUG}", json={"default_checks": default_checks}).status_code == 200
        assert op("POST", f"/streams/{SLUG}/enable").status_code == 200
    else:
        enabled_stream(app, put, op)
    body = snapshot()
    body["items"] = body["items"][4:]                       # the first four go missing
    put(body)
    if days is not None:
        assert op("PATCH", f"/streams/{SLUG}", json={"missing_expiry_days": days}).status_code == 200
    with app.app_context():
        old = datetime.utcnow() - timedelta(days=40)
        for e in ServiceEntry.query.filter_by(inventory_missing=True):
            e.inventory_missing_since = old
        db.session.commit()
    return body


def _by_name(name):
    return ServiceEntry.query.filter_by(container_name=name).one()


def test_expiry_is_off_by_default(app, put, op):
    _expiry_setup(app, put, op, days=None)
    with app.app_context():
        assert streams.expire_missing() == {"soft_deleted": 0, "kept": 0}
        assert ServiceEntry.active().filter_by(inventory_missing=True).count() == 4


def test_expiry_soft_deletes_untouched_entries_and_restores_on_return(app, put, op):
    _expiry_setup(app, put, op, default_checks={"ping": True, "tcp_port": 22})
    with app.app_context():
        assert len([c for c in _by_name("shelly-pump").checks if c.kind == CHECK_KIND_SERVICE]) == 2
        recent = _by_name("printer")
        recent.inventory_missing_since = datetime.utcnow() - timedelta(days=29)
        db.session.commit()
        result = streams.expire_missing()
        assert result == {"soft_deleted": 3, "kept": 0}      # untouched default checks don't protect
        assert _by_name("shelly-pump").deleted_at is not None
        assert _by_name("printer").deleted_at is None         # not long enough yet
    r = put()
    assert r.get_json()["counts"]["restored"] == 3
    with app.app_context():
        e = _by_name("shelly-pump")
        assert e.deleted_at is None and not e.inventory_missing


@pytest.mark.parametrize("edit, reason", [
    (lambda e: setattr(e, "stream_linked", True), "linked"),
    (lambda e: setattr(e, "name_source", "ui_edit"), "renamed"),
    (lambda e: setattr(e, "is_static", True), "locked"),
    (lambda e: setattr(e, "description", "boiler"), "description"),
    (lambda e: setattr(e, "image_icon", "x.png"), "icon"),
    (lambda e: setattr(e, "internalurl", "http://pump"), "urls"),
    (lambda e: setattr(e, "sort_priority", 5), "sort_priority"),
    (lambda e: setattr(e, "ha_publish", True), "home_assistant"),
    (lambda e: setattr(e, "group_id", _group()), "group"),
    (lambda e: e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="Web", check_type="http",
                                           target="http://10.0.40.21", enabled=True)), "checks"),
    (lambda e: setattr(next(c for c in e.checks if c.check_type == "ping"), "interval_seconds", 30), "checks"),
    (lambda e: setattr(next(c for c in e.checks if c.check_type == "ping"), "enabled", False), "checks"),
])
def test_expiry_never_removes_an_edited_entry(app, put, op, edit, reason):
    _expiry_setup(app, put, op, default_checks={"ping": True})
    with app.app_context():
        edit(_by_name("shelly-pump"))
        db.session.commit()
        assert reason in streams.human_edits(_by_name("shelly-pump"))
        result = streams.expire_missing()
        assert result == {"soft_deleted": 3, "kept": 1}
        assert _by_name("shelly-pump").deleted_at is None


def _group():
    g = Group(group_name="Pumps")
    db.session.add(g)
    db.session.flush()
    return g.id


def test_expiry_skips_disabled_streams_and_runs_in_the_purge_job(app, put, op):
    _expiry_setup(app, put, op)
    with app.app_context():
        _stream().status = "disabled"
        db.session.commit()
        assert streams.expire_missing() == {"soft_deleted": 0, "kept": 0}
        _stream().status = "enabled"
        db.session.commit()
    jobs.purge_deleted_entries(app)
    with app.app_context():
        assert ServiceEntry.query.filter(ServiceEntry.deleted_at.isnot(None)).count() == 4


def test_expiry_days_validation_and_ui_route(app, put, op, admin_client):
    enabled_stream(app, put, op)
    assert op("PATCH", f"/streams/{SLUG}", json={"missing_expiry_days": 0}).status_code == 400
    assert op("PATCH", f"/streams/{SLUG}", json={"missing_expiry_days": 4000}).status_code == 400
    r = admin_client.post(f"/settings/streams/{SLUG}/monitoring",
                          data={"expected_interval_minutes": "5", "missing_expiry_days": "14"})
    assert r.status_code == 302
    with app.app_context():
        s = _stream()
        assert (s.expected_interval_seconds, s.missing_expiry_days) == (300, 14)
    admin_client.post(f"/settings/streams/{SLUG}/monitoring",
                      data={"expected_interval_minutes": "", "missing_expiry_days": ""})
    with app.app_context():
        s = _stream()
        assert (s.expected_interval_seconds, s.missing_expiry_days) == (None, None)
    admin_client.post(f"/settings/streams/{SLUG}/monitoring", data={"expected_interval_minutes": "abc"})
    page = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert f'id="stream-monitoring-{SLUG}"' in page and "every 15 min (default)" in page


# --- IP follow ---------------------------------------------------------------------------------


@pytest.mark.parametrize("check_type, target, old, new, expected", [
    ("ping", "10.0.0.5", "10.0.0.5", "10.0.0.9", "10.0.0.9"),
    ("ping", "nas.lan", "10.0.0.5", "10.0.0.9", None),
    ("tcp", "10.0.0.5:22", "10.0.0.5", "10.0.0.9", "10.0.0.9:22"),
    ("tcp", "10.0.0.5:22", "10.0.0.5", "fd00::9", "[fd00::9]:22"),
    ("tcp", "[fd00::5]:22", "fd00::5", "10.0.0.9", "10.0.0.9:22"),
    ("tcp", "10.0.0.50:22", "10.0.0.5", "10.0.0.9", None),
    ("http", "https://10.0.0.5:8443/health?x=1", "10.0.0.5", "10.0.0.9", "https://10.0.0.9:8443/health?x=1"),
    ("http", "http://user:pw@10.0.0.5/", "10.0.0.5", "10.0.0.9", "http://user:pw@10.0.0.9/"),
    ("http", "http://nas.lan/", "10.0.0.5", "10.0.0.9", None),
    ("dns", "10.0.0.5", "10.0.0.5", "10.0.0.9", "10.0.0.9"),
    ("dns", "10.0.0.5:5353", "10.0.0.5", "10.0.0.9", "10.0.0.9:5353"),
])
def test_retarget(check_type, target, old, new, expected):
    assert streams.retarget(check_type, target, old, new) == expected


def test_ip_change_moves_checks_that_point_at_the_old_ip(app, put, op, monkeypatch):
    put()
    op("PATCH", f"/streams/{SLUG}", json={"default_checks": {"ping": True, "tcp_port": 22}})
    op("POST", f"/streams/{SLUG}/enable")
    with app.app_context():
        e = _by_name("shelly-pump")
        e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="Web", check_type="http",
                                    target="http://10.0.40.21:8080/", enabled=True))
        e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="Name", check_type="ping",
                                    target="shelly-pump.lan", enabled=True))
        db.session.commit()
    runs = []
    monkeypatch.setattr(jobs, "request_run", lambda ids: runs.extend(ids))
    body = snapshot()
    body["items"][0]["ip"] = "10.0.40.99"
    assert put(body).status_code == 200
    with app.app_context():
        targets = {c.name: c.target for c in _by_name("shelly-pump").checks if c.kind == CHECK_KIND_SERVICE}
        assert targets == {"Ping": "10.0.40.99", "TCP 22": "10.0.40.99:22",
                           "Web": "http://10.0.40.99:8080/", "Name": "shelly-pump.lan"}
        assert len(runs) == 3
        # untouched default checks still count as defaults after the move (not "edited")
        assert streams.human_edits(_by_name("shelly-pump")) == ["checks"]


def test_ip_removed_leaves_the_checks_and_logs(app, put, op, caplog):
    put()
    op("PATCH", f"/streams/{SLUG}", json={"default_checks": {"ping": True}})
    op("POST", f"/streams/{SLUG}/enable")
    body = snapshot()
    body["items"][0].pop("ip")
    caplog.set_level(logging.WARNING, logger="streams")
    put(body)
    with app.app_context():
        ping = next(c for c in _by_name("shelly-pump").checks if c.check_type == "ping")
        assert ping.target == "10.0.40.21"
    assert any("lost its IP" in r.message for r in caplog.records)


# --- not monitored by default -------------------------------------------------------------------


def test_new_stream_entries_get_no_checks_without_default_checks(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        for e in ServiceEntry.query.filter_by(source="stream"):
            assert [c for c in e.checks if c.kind == CHECK_KIND_SERVICE] == []
            assert not any(c.enabled for c in e.checks)


# --- migration ------------------------------------------------------------------------------------


def test_migration_adds_and_drops_the_columns_and_backfills_since(tmp_path):
    db_path = str(tmp_path / "o.db")
    _alembic(tmp_path, db_path, "upgrade", "b4e7a1c9d325")
    con = sqlite3.connect(db_path)
    base = ("INSERT INTO service_entry (container_name, last_updated, is_static, health_check_verify_tls, "
            "source, inventory_missing) VALUES (?, '2026-01-01', 0, 1, 'manual', ?)")
    con.execute(base, ("gone", 1))
    con.execute(base, ("here", 0))
    con.commit()
    con.close()
    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(inventory_stream)")}
    assert {"expected_interval_seconds", "producer_interval_seconds", "missing_expiry_days",
            "last_rejected_at", "last_rejection"} <= cols
    since = dict(con.execute("SELECT container_name, inventory_missing_since FROM service_entry"))
    assert since["gone"] is not None and since["here"] is None
    con.close()
    _alembic(tmp_path, db_path, "downgrade", "b4e7a1c9d325")
    con = sqlite3.connect(db_path)
    assert "inventory_missing_since" not in {r[1] for r in con.execute("PRAGMA table_info(service_entry)")}
    assert "last_rejection" not in {r[1] for r in con.execute("PRAGMA table_info(inventory_stream)")}
    con.close()
    assert os.path.exists(db_path)


def test_openapi_carries_the_new_fields(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    text = str(spec)
    for name in ("snapshot_interval_seconds", "expected_interval_seconds", "missing_expiry_days",
                 "last_rejection", "stale_streams", "missing_since", "streams_stale"):
        assert name in text, name
    assert spec["info"]["x-api-revision"] == API_REVISION
