"""Entry sources (v0.7.0, PRD 13.2): notifier vs manual entries."""

import io
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import yaml

from extensions import db
from models import ServiceEntry

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIOUS_HEAD = "f6b2d8e41c03"


def _make(name="svc1", host="host1", **kw):
    e = ServiceEntry(host=host, container_name=name, last_updated=datetime.now(), **kw)
    db.session.add(e)
    db.session.commit()
    return e


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _, m in sess.get("_flashes", [])]


def _get(name):
    return ServiceEntry.query.filter_by(container_name=name).one()


# --- migration ---------------------------------------------------------------


def _alembic(tmp_path, db_path, target):
    """Run `alembic upgrade <target>` in a subprocess against `db_path`.

    A subprocess keeps alembic's fileConfig() from reconfiguring logging in
    the test process. The repo's alembic.ini hardcodes the production DB, so
    write a copy with an absolute script_location and the temp URL.
    """
    ini = tmp_path / "alembic.ini"
    text = open(os.path.join(REPO_ROOT, "alembic.ini")).read()
    text = re.sub(r"(?m)^script_location\s*=.*$", f"script_location = {REPO_ROOT}/alembic", text)
    text = re.sub(r"(?m)^sqlalchemy.url\s*=.*$", f"sqlalchemy.url = sqlite:///{db_path}", text)
    ini.write_text(text)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), "upgrade", target],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def test_migration_backfills_source_and_allows_null_host(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, PREVIOUS_HEAD)

    con = sqlite3.connect(db_path)
    now = "2026-01-01 00:00:00"
    cols = "host, container_name, last_updated, last_api_update, is_static, health_check_verify_tls"
    con.executemany(
        f"INSERT INTO service_entry ({cols}) VALUES (?, ?, ?, ?, ?, 1)",
        [
            ("h1", "registered", now, now, 0),
            ("h1", "never-registered", now, None, 0),
            ("h1", "locked-never-registered", now, None, 1),
        ],
    )
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "head")

    con = sqlite3.connect(db_path)
    rows = dict(con.execute("SELECT container_name, source FROM service_entry"))
    assert rows == {
        "registered": "notifier",
        "never-registered": "manual",
        "locked-never-registered": "manual",
    }
    # host is nullable now, description exists, and the logical-key index survived.
    con.execute("INSERT INTO service_entry (host, container_name, last_updated, description, is_static, "
                "health_check_verify_tls) VALUES (NULL, 'nohost', '2026-01-01 00:00:00', 'about', 0, 1)")
    assert con.execute("SELECT source FROM service_entry WHERE container_name='nohost'").fetchone() == ("notifier",)
    names = [r[1] for r in con.execute("PRAGMA index_list(service_entry)")]
    assert "ix_service_entry_host_container_name" in names
    con.close()


def test_migration_on_empty_db_reaches_head(tmp_path):
    db_path = str(tmp_path / "empty.db")
    _alembic(tmp_path, db_path, "head")
    con = sqlite3.connect(db_path)
    cols = {r[1]: r for r in con.execute("PRAGMA table_info(service_entry)")}
    assert cols["source"][3] == 1 and cols["source"][4] == "'notifier'"
    assert cols["host"][3] == 0  # nullable
    assert "description" in cols


# --- model -------------------------------------------------------------------


def test_default_source_is_notifier_and_is_manual(app):
    with app.app_context():
        e = _make("a")
        assert e.source == "notifier" and e.is_manual is False
        m = _make("b", source="manual")
        assert m.is_manual is True


def test_manual_and_locked_entries_never_stale(app):
    old = datetime.now() - timedelta(minutes=600)
    with app.app_context():
        assert _make("notifier-old", last_api_update=old).is_docker_status_stale is True
        assert _make("manual-old", source="manual", last_api_update=old).is_docker_status_stale is False
        assert _make("manual-never", source="manual").is_docker_status_stale is False
        assert _make("locked-old", last_api_update=old, is_static=True).is_docker_status_stale is False


# --- register: adoption --------------------------------------------------------


def test_register_creates_notifier_entries(app, register):
    assert register(container_name="fresh").status_code == 200
    with app.app_context():
        assert _get("fresh").source == "notifier"


def test_register_adopts_unlocked_manual_entry(app, register, caplog):
    with app.app_context():
        _make("prestaged", host="host1", source="manual", description="mine", sort_priority=3)
    with caplog.at_level(logging.INFO):
        resp = register(container_name="prestaged", docker_status="running", container_id="abc123")
    assert resp.status_code == 200
    assert resp.get_json().get("status") != "skipped"
    assert any("Adopting manual entry" in r.getMessage() for r in caplog.records)
    with app.app_context():
        e = _get("prestaged")
        assert e.source == "notifier"
        assert e.docker_status == "running" and e.container_id == "abc123"
        assert e.last_api_update is not None
        assert e.description == "mine"  # operator text survives adoption
        assert ServiceEntry.query.filter_by(container_name="prestaged").count() == 1


def test_register_skips_locked_manual_entry(app, register):
    with app.app_context():
        _make("locked", source="manual", is_static=True)
    resp = register(container_name="locked", docker_status="running")
    assert resp.status_code == 200 and resp.get_json()["status"] == "skipped"
    with app.app_context():
        e = _get("locked")
        assert e.source == "manual" and e.docker_status is None


def test_register_never_matches_manual_entry_without_host(app, register):
    with app.app_context():
        _make("nohost", host=None, source="manual")
    assert register(container_name="nohost").status_code == 200
    with app.app_context():
        rows = ServiceEntry.query.filter_by(container_name="nohost").all()
        assert sorted((r.host, r.source) for r in rows if r.host) == [("host1", "notifier")]
        assert any(r.host is None and r.source == "manual" for r in rows)


# --- Add / Edit pages ----------------------------------------------------------


def test_add_creates_manual_entry_with_host(app, admin_client):
    resp = admin_client.post("/add", data={
        "container_name": "Router", "host": "lab", "description": "edge router",
        "internal_url": "http://10.0.0.1", "icon_image": "router.svg",
        "group_mode": "new", "group_name_new": "Network",
    })
    assert resp.status_code == 302
    with app.app_context():
        e = _get("Router")
        assert (e.source, e.host, e.description) == ("manual", "lab", "edge router")
        assert e.last_api_update is None
        assert e.internalurl_source == "ui_edit"


def test_add_creates_manual_entry_without_host(app, admin_client):
    resp = admin_client.post("/add", data={"container_name": "Docs site", "host": "  ",
                                           "icon_image": "docs.svg"})
    assert resp.status_code == 302
    with app.app_context():
        e = _get("Docs site")
        assert e.source == "manual" and e.host is None


def test_add_without_group_leaves_entry_ungrouped(app, admin_client):
    """No group picked (or a blank one) -> group_id NULL, no 'None' group made."""
    from models import Group

    for name, data in (
        ("NoGroup A", {"group_mode": "existing", "group_name_existing": ""}),
        ("NoGroup B", {"group_mode": "new", "group_name_new": "   "}),
        ("NoGroup C", {}),
    ):
        resp = admin_client.post("/add", data={"container_name": name, "icon_image": "x.svg", **data})
        assert resp.status_code == 302
    with app.app_context():
        for name in ("NoGroup A", "NoGroup B", "NoGroup C"):
            assert _get(name).group_id is None
        assert Group.query.filter_by(group_name="None").first() is None


def test_add_requires_a_name_not_a_host(admin_client):
    resp = admin_client.post("/add", data={"container_name": "", "host": "lab", "icon_image": "x.svg"})
    assert resp.status_code == 200
    assert "Name is required" in resp.get_data(as_text=True)  # rendered on the page


def test_add_duplicate_check_handles_null_host(app, admin_client):
    data = {"container_name": "Wiki", "icon_image": "wiki.svg"}
    assert admin_client.post("/add", data=data).status_code == 302
    resp = admin_client.post("/add", data=data)
    assert resp.status_code == 200
    assert "already exists" in resp.get_data(as_text=True)  # rendered on the page
    # A different host is a different entry; so is the same name with no host vs. a host.
    assert admin_client.post("/add", data={**data, "host": "lab"}).status_code == 302
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="Wiki").count() == 2


def test_add_duplicate_of_soft_deleted_keeps_restore_message(app, admin_client):
    with app.app_context():
        _make("Gone", host=None, source="manual", deleted_at=datetime.now())
    resp = admin_client.post("/add", data={"container_name": "Gone", "icon_image": "g.svg"})
    assert resp.status_code == 200
    assert "was deleted" in resp.get_data(as_text=True)  # rendered on the page


def test_edit_manual_hides_docker_block_and_saves_description(app, admin_client):
    with app.app_context():
        mid = _make("man", host=None, source="manual").id
        nid = _make("note").id
    page = admin_client.get(f"/edit/{mid}").get_data(as_text=True)
    assert "Reported by notifier" not in page
    assert 'name="description"' in page
    assert "Lock (ignore notifier updates)" in page
    page = admin_client.get(f"/edit/{nid}").get_data(as_text=True)
    assert "Reported by notifier" in page
    assert 'name="description"' not in page

    admin_client.post(f"/edit/{mid}", data={"host": "", "container_name": "man",
                                            "description": "hello", "widget_name": "none"})
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert e.host is None and e.description == "hello" and e.source == "manual"


# --- views ---------------------------------------------------------------------


def test_views_render_manual_and_hostless_entries(app, admin_client):
    with app.app_context():
        _make("man-nohost", host=None, source="manual", description="about me",
              internalurl="http://x.test")
        _make("man-host", host="lab", source="manual")
        _make("dock", host="lab", last_api_update=datetime.now() - timedelta(hours=3),
              docker_status="running")
    for path in ("/", "/tiled_dash", "/compact_dash"):
        for axis in ("group", "stack", "host"):
            resp = admin_client.get(f"{path}?group_by={axis}")
            assert resp.status_code == 200, (path, axis)
            html = resp.get_data(as_text=True)
            assert "man-nohost" in html and "None</span>" not in html
    host_view = admin_client.get("/tiled_dash?group_by=host").get_data(as_text=True)
    assert "Unknown host" in host_view
    tiled = admin_client.get("/tiled_dash").get_data(as_text=True)
    assert "ti-link" in tiled and "ti-brand-docker" in tiled
    table = admin_client.get("/").get_data(as_text=True)
    assert "ti-link" in table and "Manual" in table
    # Manual entries never get the stale clock; the 3 h old notifier entry does.
    assert table.count("ti-clock-exclamation") == 1


# --- backups -------------------------------------------------------------------


def _download(admin_client):
    resp = admin_client.post("/settings", data={"action": "backup", "backup_operation": "download_all"})
    assert resp.status_code == 200
    return yaml.safe_load(resp.get_data(as_text=True))


def _restore(admin_client, records):
    payload = yaml.dump(records)
    return admin_client.post("/settings", data={
        "action": "restore", "restore_source": "upload", "restore_scope": "all",
        "restore_file": (io.BytesIO(payload.encode()), "b.yaml"),
    }, content_type="multipart/form-data")


def test_backup_round_trips_source_description_and_null_host(app, admin_client):
    with app.app_context():
        _make("man", host=None, source="manual", description="d")
        _make("note", last_api_update=datetime.now())
    records = _download(admin_client)
    by_name = {r["container_name"]: r for r in records}
    assert (by_name["man"]["source"], by_name["man"]["description"], by_name["man"]["host"]) == ("manual", "d", None)
    assert by_name["note"]["source"] == "notifier"

    with app.app_context():
        ServiceEntry.query.delete()
        db.session.commit()
    assert _restore(admin_client, records).status_code == 302
    with app.app_context():
        man, note = _get("man"), _get("note")
        assert (man.source, man.host, man.description) == ("manual", None, "d")
        assert note.source == "notifier"


def test_restore_of_old_backup_without_source_uses_backfill_rule(app, admin_client):
    base = {"last_updated": "2026-01-01 00:00:00"}
    records = [
        {**base, "host": "h", "container_name": "registered", "last_api_update": "2026-01-01 00:00:00"},
        {**base, "host": "h", "container_name": "never-registered", "last_api_update": None},
        {**base, "container_name": "nohost-never", "last_api_update": None},
        {**base, "container_name": "nohost-registered", "last_api_update": "2026-01-01 00:00:00"},
    ]
    assert _restore(admin_client, records).status_code == 302
    with app.app_context():
        assert _get("registered").source == "notifier"
        assert _get("never-registered").source == "manual"
        nohost = _get("nohost-never")
        assert nohost.source == "manual" and nohost.host is None
        # A notifier entry needs a host, so that record is skipped.
        assert ServiceEntry.query.filter_by(container_name="nohost-registered").count() == 0


# --- is_docker and source filters (PRD 18.3) --------------------------------------


def test_is_docker_means_notifier_source(app):
    with app.app_context():
        assert _make("d").is_docker is True
        m = _make("m", source="manual")
        assert m.is_docker is False and m.is_manual is True
        # Not Docker -> never stale, even with no last_api_update.
        assert m.is_docker_status_stale is False


def test_source_filters_accept_every_valid_source(app):
    from models import VALID_SOURCES
    from view_helpers import matches_source, normalize_source_filter

    with app.app_context():
        entries = {s: _make(f"e-{s}", source=s) for s in VALID_SOURCES}
        for source in VALID_SOURCES:
            assert normalize_source_filter(source.upper()) == source
            for other, entry in entries.items():
                assert matches_source(entry, source) is (other == source)
        for entry in entries.values():
            assert matches_source(entry, "all") is True
        assert normalize_source_filter("bogus") == "all"
        assert normalize_source_filter(None) == "all"


def test_restore_unknown_source_becomes_manual(app, admin_client):
    base = {"last_updated": "2026-01-01 00:00:00", "last_api_update": "2026-01-01 00:00:00"}
    records = [
        {**base, "container_name": "future-nohost", "source": "stream"},
        {**base, "host": "h", "container_name": "future-host", "source": "stream"},
    ]
    assert _restore(admin_client, records).status_code == 302
    with app.app_context():
        # Unknown source restores as manual, so no host is required.
        nohost = _get("future-nohost")
        assert nohost.source == "manual" and nohost.host is None
        assert _get("future-host").source == "manual"
