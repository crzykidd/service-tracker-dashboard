"""Container check: Docker state as an automatic health check (v0.7.0, PRD 13.8)."""

import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import yaml

import jobs
from extensions import db
from health_state import entry_health
from models import (
    HealthCheck,
    HealthResult,
    ServiceEntry,
    ensure_container_check,
    ensure_url_checks,
    evaluate_container,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HEALTH_REV = "b8e4d6a2c1f9"


def _entry(name="c", source="notifier", status="running", age_min=0, static=False, **kw):
    now = datetime.now()
    e = ServiceEntry(
        host="h" if source == "notifier" else None, container_name=name, source=source,
        docker_status=status, is_static=static, last_updated=now,
        last_api_update=None if age_min is None else now - timedelta(minutes=age_min), **kw)
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    ensure_container_check(e)
    db.session.commit()
    return e


def _tick(app, hours=0):
    sched = jobs.HealthScheduler(app, executor=_PoolForbidden())
    return sched.tick(datetime.utcnow() + timedelta(hours=hours))


class _PoolForbidden:
    def submit(self, fn, *a, **k):
        raise AssertionError("container checks must never go to the pool")


# --- evaluation --------------------------------------------------------------


def test_evaluate_running_and_fresh(app):
    with app.app_context():
        e = _entry()
        assert evaluate_container(e) == (True, None)


def test_evaluate_case_insensitive(app):
    with app.app_context():
        assert evaluate_container(_entry("a", status="Running"))[0] is True
        assert evaluate_container(_entry("b", status=" RUNNING "))[0] is True


def test_evaluate_not_running(app):
    with app.app_context():
        assert evaluate_container(_entry("a", status="exited")) == (False, "Container exited")
        assert evaluate_container(_entry("b", status=None)) == (False, "Container status unknown")


def test_evaluate_stale_and_never_reported(app):
    with app.app_context():
        ok, msg = evaluate_container(_entry("a", age_min=12))
        assert ok is False and msg == "No update from notifier for 12 min"
        assert evaluate_container(_entry("b", age_min=None)) == (False, "No update from notifier yet")


# --- creation ----------------------------------------------------------------


def test_ensure_container_check_notifier_only_and_idempotent(app):
    with app.app_context():
        n = _entry("n")
        m = _entry("m", source="manual")
        ensure_container_check(n)
        db.session.commit()
        cc = [c for c in n.checks if c.kind == "container"]
        assert len(cc) == 1
        assert (cc[0].name, cc[0].check_type, cc[0].target, cc[0].enabled) == ("Container", "docker", None, True)
        assert m.container_check is None


def test_register_create_makes_container_check(app, register):
    register(container_name="new", docker_status="running")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="new").one()
        assert e.container_check is not None and e.container_check.enabled


def test_adoption_creates_container_check(app, register):
    with app.app_context():
        m = _entry("adopt", source="manual")
        m.host = "host1"
        db.session.commit()
        assert m.container_check is None
    register(container_name="adopt")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="adopt").one()
        assert e.source == "notifier" and e.container_check is not None


# --- scheduler ---------------------------------------------------------------


def test_scheduler_records_on_scheduler_thread_not_pool(app):
    with app.app_context():
        e = _entry("run")
        cid = e.container_check.id
    written, submitted = _tick(app)
    assert (written, submitted) == (1, 0)
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert c.last_ok is True and c.last_message is None and c.last_checked_at
        assert c.last_status_code is None and c.last_latency_ms is None
        r, = HealthResult.query.filter_by(check_id=cid).all()
        assert r.ok is True and r.latency_ms is None and r.status_code is None
    # Not due again until the interval passes.
    assert _tick(app) == (0, 0)
    assert _tick(app, hours=1) == (1, 0)


def test_scheduler_records_failure_messages(app):
    with app.app_context():
        _entry("down", status="exited")
        _entry("old", age_min=30)
        _entry("never", age_min=None)
    _tick(app)
    with app.app_context():
        msgs = {c.service_entry.container_name: (c.last_ok, c.last_message)
                for c in HealthCheck.query.filter_by(kind="container")}
    assert msgs["down"] == (False, "Container exited")
    assert msgs["old"] == (False, "No update from notifier for 30 min")
    assert msgs["never"] == (False, "No update from notifier yet")


def test_scheduler_uses_check_interval(app):
    with app.app_context():
        e = _entry("iv")
        e.container_check.interval_seconds = 3600
        db.session.commit()
    _tick(app)
    assert _tick(app, hours=0.5) == (0, 0)
    assert _tick(app, hours=2) == (1, 0)


def test_locked_manual_deleted_and_disabled_are_skipped(app):
    with app.app_context():
        _entry("locked", static=True)
        _entry("man", source="manual")
        gone = _entry("gone")
        gone.deleted_at = datetime.now()
        off = _entry("off")
        off.container_check.enabled = False
        db.session.commit()
    assert _tick(app) == (0, 0)
    with app.app_context():
        assert HealthResult.query.count() == 0


def test_locked_entry_container_check_not_counted_in_rollup(app):
    with app.app_context():
        e = _entry("lk", static=True)
        e.container_check.last_ok = True
        db.session.commit()
        assert entry_health(e).state == "none"
        e.is_static = False
        assert entry_health(e).state == "up"


# --- register queues a run ---------------------------------------------------


def test_register_status_change_queues_run(app, register):
    register(container_name="q", docker_status="running")
    with app.app_context():
        cid = ServiceEntry.query.filter_by(container_name="q").one().container_check.id
    jobs._clear_run_requests(jobs._pending_run_requests())
    register(container_name="q", docker_status="running")
    assert jobs._pending_run_requests() == set()
    register(container_name="q", docker_status="exited")
    assert jobs._pending_run_requests() == {cid}


def test_register_after_failing_check_queues_run(app, register):
    register(container_name="r", docker_status="running")
    with app.app_context():
        c = ServiceEntry.query.filter_by(container_name="r").one().container_check
        c.last_ok = False
        cid = c.id
        db.session.commit()
    jobs._clear_run_requests(jobs._pending_run_requests())
    register(container_name="r", docker_status="running")
    assert jobs._pending_run_requests() == {cid}


def test_run_request_makes_check_due_immediately_and_recovers(app, register):
    register(container_name="z", docker_status="exited")
    _tick(app)
    with app.app_context():
        cid = ServiceEntry.query.filter_by(container_name="z").one().container_check.id
        assert db.session.get(HealthCheck, cid).last_message == "Container exited"
    register(container_name="z", docker_status="running")
    assert _tick(app) == (1, 0)  # same instant: due only because of the request
    with app.app_context():
        assert db.session.get(HealthCheck, cid).last_ok is True


# --- rollup truth table ------------------------------------------------------


def test_rollup_with_container_check(app):
    with app.app_context():
        up = _entry("up")
        up.container_check.last_ok = True
        down = _entry("down", status="exited")
        down.container_check.last_ok = False
        deg = _entry("deg", internalurl="http://i")
        deg.container_check.last_ok = True
        deg.url_check("internal").enabled = True
        deg.url_check("internal").last_ok = False
        off = _entry("off")
        off.container_check.enabled = False
        db.session.commit()
        assert entry_health(up).state == "up"
        assert entry_health(down).state == "down"
        assert "Container" in entry_health(down).tooltip
        assert entry_health(deg).state == "degraded"
        assert entry_health(off).state == "none"


# --- edit page ---------------------------------------------------------------


def test_edit_shows_container_row_for_notifier_only(app, admin_client):
    with app.app_context():
        n = _entry("n").id
        m = _entry("m", source="manual").id
    assert "Container (Docker state)" in admin_client.get(f"/edit/{n}").get_data(as_text=True)
    assert "Container (Docker state)" not in admin_client.get(f"/edit/{m}").get_data(as_text=True)
    assert "Container (Docker state)" not in admin_client.get("/add").get_data(as_text=True)


def _post(admin_client, eid, **extra):
    data = {"host": "h", "container_name": "n", "widget_name": "none", "checks_form": "1", "cc_row": "1"}
    data.update(extra)
    return admin_client.post(f"/edit/{eid}", data=data)


def test_edit_saves_enabled_and_interval(app, admin_client):
    with app.app_context():
        eid = _entry("n").id
    assert _post(admin_client, eid, cc_interval="120", cc_enabled="on").status_code == 302
    with app.app_context():
        c = db.session.get(ServiceEntry, eid).container_check
        assert (c.enabled, c.interval_seconds) == (True, 120)
    _post(admin_client, eid, cc_interval="")
    with app.app_context():
        c = db.session.get(ServiceEntry, eid).container_check
        assert (c.enabled, c.interval_seconds) == (False, None)


def test_edit_validates_interval(app, admin_client):
    with app.app_context():
        eid = _entry("n").id
    resp = _post(admin_client, eid, cc_interval="5", cc_enabled="on")
    assert resp.status_code == 200 and "Container check" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).container_check.interval_seconds is None


def test_edit_without_container_row_leaves_it_alone(app, admin_client):
    with app.app_context():
        eid = _entry("n").id
    data = {"host": "h", "container_name": "n", "widget_name": "none", "checks_form": "1"}
    admin_client.post(f"/edit/{eid}", data=data)
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).container_check.enabled is True


# --- health endpoint, check now ---------------------------------------------


def test_health_endpoint_includes_container_check(app, admin_client):
    with app.app_context():
        eid = _entry("n", status="exited").id
    _tick(app)
    data = admin_client.get(f"/service/{eid}/health").get_json()
    c, = data["checks"]
    assert (c["kind"], c["name"], c["check_type"], c["target"]) == ("container", "Container", "docker", None)
    assert c["state"] == "down" and c["message"] == "Container exited"
    assert c["uptime_24h"] == 0.0 and sum(b["fail"] for b in c["bars"]) == 1


def test_health_endpoint_omits_locked_container_check(app, admin_client):
    with app.app_context():
        eid = _entry("n", static=True).id
    assert admin_client.get(f"/service/{eid}/health").get_json()["checks"] == []


def test_check_now_queues_container_check(app, admin_client):
    with app.app_context():
        e = _entry("n")
        eid, cid = e.id, e.container_check.id
    jobs._clear_run_requests(jobs._pending_run_requests())
    assert admin_client.post(f"/service/{eid}/checks/run").get_json()["queued"] == 1
    assert cid in jobs._pending_run_requests()


# --- backup ------------------------------------------------------------------


def _restore(admin_client, records):
    payload = yaml.dump(records)
    return admin_client.post("/settings", data={
        "action": "restore", "restore_source": "upload", "restore_scope": "all",
        "restore_file": (io.BytesIO(payload.encode()), "b.yaml"),
    }, content_type="multipart/form-data")


def test_backup_round_trip_keeps_container_config(app, admin_client):
    with app.app_context():
        e = _entry("rt")
        e.container_check.enabled = False
        e.container_check.interval_seconds = 90
        db.session.commit()
        records = [e.to_dict()]
        assert any(c["kind"] == "container" for c in records[0]["checks"])
        db.session.delete(e)
        db.session.commit()
    records[0]["last_updated"] = "2026-01-01 00:00:00"
    assert _restore(admin_client, records).status_code == 302
    with app.app_context():
        c = ServiceEntry.query.filter_by(container_name="rt").one().container_check
        assert (c.enabled, c.interval_seconds, c.check_type, c.target) == (False, 90, "docker", None)


def test_old_backup_without_container_row_creates_it(app, admin_client):
    with app.app_context():
        e = _entry("old")
        rec = e.to_dict()
        rec["checks"] = [c for c in rec["checks"] if c["kind"] != "container"]
        legacy = e.to_dict()
        for k in ("checks", "source"):
            legacy.pop(k)
        legacy["container_name"] = "legacy"
        db.session.delete(e)
        db.session.commit()
    rec["last_updated"] = legacy["last_updated"] = "2026-01-01 00:00:00"
    assert _restore(admin_client, [rec, legacy]).status_code == 302
    with app.app_context():
        for name in ("old", "legacy"):
            e = ServiceEntry.query.filter_by(container_name=name).one()
            assert e.source == "notifier" and e.container_check.enabled


def test_manual_backup_entry_gets_no_container_check(app, admin_client):
    with app.app_context():
        e = _entry("man", source="manual")
        records = [e.to_dict()]
        db.session.delete(e)
        db.session.commit()
    records[0]["last_updated"] = "2026-01-01 00:00:00"
    _restore(admin_client, records)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="man").one().container_check is None


# --- migration ---------------------------------------------------------------


def _alembic(tmp_path, db_path, command, target):
    ini = tmp_path / "alembic.ini"
    text = open(os.path.join(REPO_ROOT, "alembic.ini")).read()
    text = re.sub(r"(?m)^script_location\s*=.*$", f"script_location = {REPO_ROOT}/alembic", text)
    text = re.sub(r"(?m)^sqlalchemy.url\s*=.*$", f"sqlalchemy.url = sqlite:///{db_path}", text)
    ini.write_text(text)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), command, target],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_migration_creates_container_rows_for_notifier_entries_only(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", HEALTH_REV)
    con = sqlite3.connect(db_path)
    con.executemany(
        "INSERT INTO service_entry (host, container_name, last_updated, is_static, source, deleted_at) "
        "VALUES (?,?,?,?,?,?)",
        [("h", "n1", "2026-01-01 00:00:00", 0, "notifier", None),
         ("h", "n2", "2026-01-01 00:00:00", 1, "notifier", "2026-02-01 00:00:00"),
         (None, "m1", "2026-01-01 00:00:00", 1, "manual", None)])
    con.commit()
    con.close()
    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    rows = con.execute(
        "SELECT e.container_name, c.name, c.check_type, c.target, c.mode, c.enabled, c.verify_tls, "
        "c.consecutive_failures, c.last_ok FROM health_check c "
        "JOIN service_entry e ON e.id = c.service_entry_id WHERE c.kind = 'container' "
        "ORDER BY e.container_name").fetchall()
    assert rows == [("n1", "Container", "docker", None, "status", 1, 1, 0, None),
                    ("n2", "Container", "docker", None, "status", 1, 1, 0, None)]
    # Downgrade removes them and their results; upgrade restores them.
    cid = con.execute("SELECT id FROM health_check WHERE kind='container' LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO health_result (check_id, ts, samples, ok) VALUES (?, '2026-01-01', 1, 1)", (cid,))
    con.commit()
    con.close()
    _alembic(tmp_path, db_path, "downgrade", "-1")
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM health_check WHERE kind='container'").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM health_result").fetchone() == (0,)
    con.close()
    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM health_check WHERE kind='container'").fetchone() == (2,)
    con.close()


