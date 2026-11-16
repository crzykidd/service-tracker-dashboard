"""Health checks as their own tables (v0.7.0, PRD 13.3)."""

import io
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from unittest.mock import patch

import yaml

import jobs
from extensions import db
from models import HealthCheck, HealthResult, ServiceEntry, ensure_url_checks

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIOUS_HEAD = "a7c3e9f15d28"


def _make(name="svc1", host="host1", **kw):
    e = ServiceEntry(host=host, container_name=name, last_updated=datetime.now(), **kw)
    ensure_url_checks(e)
    db.session.add(e)
    db.session.commit()
    return e


def _get(name):
    return ServiceEntry.query.filter_by(container_name=name).one()


def _kinds(entry):
    return sorted(c.kind for c in entry.checks)


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


def _seed_legacy(db_path):
    con = sqlite3.connect(db_path)
    cols = ("host, container_name, last_updated, is_static, health_check_verify_tls, source, "
            "internal_health_check_enabled, internal_health_check_status, internal_health_check_update, "
            "external_health_check_enabled, external_health_check_status, external_health_check_update, "
            "health_check_timeout")
    con.executemany(
        f"INSERT INTO service_entry ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # healthy internal, failing external with a code, custom timeout, TLS off
            ("h", "ok-bad", "2026-01-01 00:00:00", 0, 0, "notifier",
             1, "200", "2026-01-01 12:00:00", 1, "503", "2026-01-01 12:00:01", 12),
            # exception string, unparsable update time
            ("h", "errored", "2026-01-01 00:00:00", 0, 1, "notifier",
             1, "Error: SSLError", "garbage", 0, None, None, None),
            # NULL toggles (never set) and no status
            ("h", "untouched", "2026-01-01 00:00:00", 0, 1, "notifier",
             None, None, None, None, None, None, None),
        ],
    )
    con.commit()
    con.close()


def test_migration_copies_legacy_health_values(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS_HEAD)
    _seed_legacy(db_path)
    _alembic(tmp_path, db_path, "upgrade", "head")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = {}
    for r in con.execute(
        "SELECT c.*, e.container_name AS ename FROM health_check c "
        "JOIN service_entry e ON e.id = c.service_entry_id"
    ):
        rows[(r["ename"], r["kind"])] = r
    assert len(rows) == 6  # two URL rows per entry, nothing else

    r = rows[("ok-bad", "internal_url")]
    assert (r["enabled"], r["timeout_seconds"], r["verify_tls"]) == (1, 12, 0)
    assert (r["last_ok"], r["last_status_code"], r["last_message"], r["consecutive_failures"]) == (1, 200, None, 0)
    assert r["last_checked_at"] is not None and r["target"] is None
    assert (r["check_type"], r["mode"], r["name"]) == ("http", "status", "Internal URL")

    r = rows[("ok-bad", "external_url")]
    assert (r["last_ok"], r["last_status_code"], r["last_message"], r["consecutive_failures"]) == (0, 503, "503", 1)

    r = rows[("errored", "internal_url")]
    assert (r["enabled"], r["last_ok"], r["last_status_code"], r["last_message"]) == (1, 0, None, "Error: SSLError")
    assert r["last_checked_at"] is None  # unparsable update time
    assert rows[("errored", "external_url")]["enabled"] == 0

    r = rows[("untouched", "internal_url")]
    assert (r["enabled"], r["last_ok"], r["last_message"], r["last_checked_at"]) == (0, None, None, None)
    assert r["verify_tls"] == 1 and r["timeout_seconds"] is None

    # Composite index exists and the FK column is indexed.
    idx = {r[1]: [c[2] for c in con.execute(f"PRAGMA index_info({r[1]})")]
           for r in con.execute("PRAGMA index_list(health_result)")}
    assert idx["ix_health_result_check_id_ts"] == ["check_id", "ts"]
    assert "ix_health_check_service_entry_id" in [r[1] for r in con.execute("PRAGMA index_list(health_check)")]
    con.close()


def test_migration_downgrade_restores_legacy_enabled_and_round_trips(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS_HEAD)
    _seed_legacy(db_path)
    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    con.execute("UPDATE health_check SET enabled = 1 WHERE kind = 'external_url'")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "downgrade", "-1")
    con = sqlite3.connect(db_path)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "health_check" not in tables and "health_result" not in tables
    got = con.execute(
        "SELECT internal_health_check_enabled, external_health_check_enabled "
        "FROM service_entry WHERE container_name='errored'").fetchone()
    assert got == (1, 1)
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM health_check").fetchone() == (6,)
    con.close()


def test_migration_on_empty_db_creates_tables(tmp_path):
    db_path = str(tmp_path / "empty.db")
    _alembic(tmp_path, db_path, "upgrade", "head")
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT COUNT(*) FROM health_check").fetchone() == (0,)
    assert con.execute("SELECT COUNT(*) FROM health_result").fetchone() == (0,)
    con.close()


# --- models / helpers ----------------------------------------------------------


def test_ensure_url_checks_is_idempotent_and_helpers(app):
    with app.app_context():
        e = _make("a")
        ensure_url_checks(e)
        db.session.commit()
        assert _kinds(e) == ["external_url", "internal_url"]
        assert e.url_check("internal").kind == "internal_url"
        assert e.url_check("external_url").kind == "external_url"
        assert e.service_checks == []
        c = e.url_check("internal")
        assert (c.enabled, c.verify_tls, c.check_type, c.mode, c.target) == (False, True, "http", "status", None)


def test_entry_delete_cascades_to_checks_and_results(app):
    with app.app_context():
        e = _make("gone")
        db.session.add(HealthResult(check_id=e.checks[0].id, ts=datetime.utcnow(), ok=True))
        db.session.commit()
        db.session.delete(e)
        db.session.commit()
        assert HealthCheck.query.count() == 0 and HealthResult.query.count() == 0


# --- create paths --------------------------------------------------------------


def test_register_create_makes_both_rows_and_maps_toggles(app, register):
    register(container_name="reg", internal_health_check_enabled=True)
    with app.app_context():
        e = _get("reg")
        assert _kinds(e) == ["external_url", "internal_url"]
        assert e.url_check("internal").enabled is True
        assert e.url_check("external").enabled is False
        # Legacy column no longer written.
        assert e.internal_health_check_enabled is None


def test_register_toggle_updates_row_and_absent_means_no_change(app, register):
    register(container_name="t", internal_health_check_enabled=True, external_health_check_enabled=True)
    register(container_name="t", external_health_check_enabled=False)  # internal absent
    with app.app_context():
        e = _get("t")
        assert e.url_check("internal").enabled is True
        assert e.url_check("external").enabled is False
        assert len(e.checks) == 2
    register(container_name="t")
    with app.app_context():
        e = _get("t")
        assert e.url_check("internal").enabled is True and e.url_check("external").enabled is False


def test_register_on_entry_without_rows_creates_them(app, register):
    with app.app_context():
        db.session.add(ServiceEntry(host="host1", container_name="bare", last_updated=datetime.now()))
        db.session.commit()
    register(container_name="bare", internal_health_check_enabled=True)
    with app.app_context():
        e = _get("bare")
        assert _kinds(e) == ["external_url", "internal_url"] and e.url_check("internal").enabled


def test_add_page_creates_rows_with_form_values(app, admin_client):
    admin_client.post("/add", data={
        "container_name": "added", "icon_image": "a.svg", "internal_health_check": "on",
        "health_check_timeout": "9",
    })
    with app.app_context():
        e = _get("added")
        assert _kinds(e) == ["external_url", "internal_url"]
        assert e.url_check("internal").enabled is True and e.url_check("external").enabled is False
        assert e.url_check("internal").timeout_seconds == 9 == e.url_check("external").timeout_seconds
        assert e.url_check("internal").verify_tls is False  # checkbox absent


def test_edit_toggles_write_rows_and_form_reads_them(app, admin_client):
    with app.app_context():
        eid = _make("ed", source="manual").id
    admin_client.post(f"/edit/{eid}", data={
        "host": "", "container_name": "ed", "widget_name": "none",
        "external_health_check_enabled": "on", "health_check_verify_tls": "on",
    })
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.url_check("internal").enabled is False and e.url_check("external").enabled is True
        assert e.internal_health_check_enabled is None and e.external_health_check_enabled is None
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert re.search(r'name="external_health_check_enabled"[^>]*checked', page)
    assert not re.search(r'name="internal_health_check_enabled"[^>]*checked', page)


# --- checker loop writes (engine details live in test_checker.py) ----------------


class _SyncExecutor:
    """Runs submitted work inline so tests need no threads."""

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        f = Future()
        try:
            f.set_result(fn(*args, **kwargs))
        except Exception as e:  # pragma: no cover
            f.set_exception(e)
        return f

    def shutdown(self, **kw):
        pass


def _pass(app, sched=None, hours=0):
    """One full submit-and-collect pass; `hours` shifts the clock so checks
    that just ran are due again."""
    from datetime import timedelta

    sched = sched or jobs.HealthScheduler(app, executor=_SyncExecutor())
    now = datetime.utcnow() + timedelta(hours=hours)
    sched.tick(now)       # submits (and runs inline)
    sched.tick(now)       # collects and writes
    return sched


def test_loop_writes_result_updates_check_and_mirrors_legacy(app):
    with app.app_context():
        e = _make("probe", internalurl="http://i", externalurl="http://e")
        e.url_check("internal").enabled = True
        e.url_check("internal").timeout_seconds = 7
        # external disabled; a third entry has the toggle on but no URL
        other = _make("nourl")
        other.url_check("internal").enabled = True
        db.session.commit()

        with patch("checker.requests.get") as get:
            get.return_value.status_code = 200
            _pass(app)
        assert get.call_count == 1
        assert get.call_args.args[0] == "http://i" and get.call_args.kwargs["timeout"] == 7

        e = _get("probe")
        c = e.url_check("internal")
        assert c.last_ok is True and c.last_status_code == 200 and c.last_checked_at is not None
        assert c.last_message is None and c.consecutive_failures == 0
        assert e.url_check("external").last_checked_at is None
        results = HealthResult.query.filter_by(check_id=c.id).all()
        assert len(results) == 1 and results[0].ok is True and results[0].status_code == 200
        # TEMP mirror into the legacy status columns.
        assert e.internal_health_check_status == "200" and e.internal_health_check_update
        assert e.external_health_check_status is None
        assert HealthResult.query.count() == 1


def test_loop_failure_counts_and_mirrors_error_string(app):
    with app.app_context():
        e = _make("down", internalurl="http://i")
        e.url_check("internal").enabled = True
        db.session.commit()
        sched = jobs.HealthScheduler(app, executor=_SyncExecutor())
        with patch("checker.requests.get", side_effect=OSError("boom")):
            _pass(app, sched)
            _pass(app, sched, hours=1)
        e = _get("down")
        c = e.url_check("internal")
        assert c.last_ok is False and c.last_message == "OSError: boom" and c.consecutive_failures == 2
        assert e.internal_health_check_status == "Error: OSError"
        with patch("checker.requests.get") as get:
            get.return_value.status_code = 200
            _pass(app, sched, hours=2)
        db.session.expire_all()
        assert _get("down").url_check("internal").consecutive_failures == 0


def test_loop_skips_soft_deleted_entries(app):
    with app.app_context():
        e = _make("trash", internalurl="http://i", deleted_at=datetime.now())
        e.url_check("internal").enabled = True
        db.session.commit()
        with patch("checker.requests.get") as get:
            _pass(app)
        assert not get.called


# --- backups ---------------------------------------------------------------------


def _restore(admin_client, records):
    payload = yaml.dump(records)
    return admin_client.post("/settings", data={
        "action": "restore", "restore_source": "upload", "restore_scope": "all",
        "restore_file": (io.BytesIO(payload.encode()), "b.yaml"),
    }, content_type="multipart/form-data")


def test_backup_exports_check_config_only(app):
    with app.app_context():
        e = _make("exp")
        c = e.url_check("internal")
        c.enabled = True
        c.timeout_seconds = 4
        c.last_ok = True
        db.session.add(HealthResult(check_id=c.id, ts=datetime.utcnow(), ok=True))
        db.session.commit()
        d = e.to_dict()
    assert [x["kind"] for x in d["checks"]] == ["internal_url", "external_url"]
    cfg = d["checks"][0]
    assert cfg["enabled"] is True and cfg["timeout_seconds"] == 4
    assert not any(k.startswith("last_") for k in cfg) and "results" not in cfg
    # Legacy keys stay readable by an older STD.
    assert d["internal_health_check_enabled"] is True and d["health_check_timeout"] == 4


def test_new_format_backup_round_trip(app, admin_client):
    with app.app_context():
        e = _make("rt")
        e.url_check("external").enabled = True
        e.url_check("external").verify_tls = False
        e.url_check("external").timeout_seconds = 11
        e.url_check("internal").interval_seconds = 120
        svc = HealthCheck(kind="service", name="db port", check_type="tcp", target="db:5432",
                          mode="status", enabled=True, consecutive_failures=0)
        e.checks.append(svc)
        db.session.commit()
        records = [e.to_dict()]
        db.session.delete(e)
        db.session.commit()
    records[0]["last_updated"] = "2026-01-01 00:00:00"
    assert _restore(admin_client, records).status_code == 302
    with app.app_context():
        e = _get("rt")
        assert _kinds(e) == ["external_url", "internal_url", "service"]
        ext = e.url_check("external")
        assert (ext.enabled, ext.verify_tls, ext.timeout_seconds) == (True, False, 11)
        assert e.url_check("internal").interval_seconds == 120
        s, = e.service_checks
        assert (s.name, s.check_type, s.target, s.enabled) == ("db port", "tcp", "db:5432", True)
        assert e.internal_health_check_enabled is None  # legacy column not written


def test_restore_replaces_service_checks_wholesale(app, admin_client):
    with app.app_context():
        e = _make("rs")
        e.checks.append(HealthCheck(kind="service", name="old", check_type="tcp", target="x:1",
                                    consecutive_failures=0))
        db.session.commit()
    rec = {"host": "host1", "container_name": "rs", "last_updated": "2026-01-01 00:00:00", "checks": []}
    assert _restore(admin_client, [rec]).status_code == 302
    with app.app_context():
        assert _get("rs").service_checks == []


def test_old_format_backup_maps_legacy_fields(app, admin_client):
    rec = {
        "host": "h", "container_name": "old", "last_updated": "2026-01-01 00:00:00",
        "internal_health_check_enabled": True, "external_health_check_enabled": None,
        "health_check_timeout": 25, "health_check_verify_tls": False,
        "internal_health_check_status": "200", "internal_health_check_update": "2026-01-01 00:00:00",
    }
    bare = {"host": "h", "container_name": "oldest", "last_updated": "2026-01-01 00:00:00"}
    assert _restore(admin_client, [rec, bare]).status_code == 302
    with app.app_context():
        e = _get("old")
        assert _kinds(e) == ["external_url", "internal_url"]
        assert e.url_check("internal").enabled is True and e.url_check("external").enabled is False
        assert e.url_check("internal").timeout_seconds == 25 == e.url_check("external").timeout_seconds
        assert e.url_check("internal").verify_tls is False
        assert e.internal_health_check_status == "200"  # status strings still restore
        b = _get("oldest")
        assert b.url_check("internal").enabled is False and b.url_check_timeout is None
        assert b.url_check_verify_tls is True
