"""Staged database restore (backup phase 5): validate, stage, the pre-migration swap, the UI.

`restore_swap.py` runs as a subprocess against a temp config dir, the way `entrypoint.sh` runs
it. Real schema files come from running the alembic migrations in a subprocess (alembic.ini
hardcodes the production path, so the URL is overridden there).
"""

import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys

import pytest

import backups
import restore_staging
from tests.conftest import REPO_ROOT

OLDER_REVISION = "e3b7c1d9a204"      # an ancestor of head (the settings/streams era)

_MIGRATE = """
import sys
from alembic import command
from alembic.config import Config
cfg = Config("alembic.ini")
cfg.set_main_option("sqlalchemy.url", "sqlite:///" + sys.argv[1])
command.upgrade(cfg, sys.argv[2])
"""


def migrated_db(path, revision="head", entries=0):
    """A real STD database at `revision` (alembic in a subprocess) with `entries` rows."""
    subprocess.run([sys.executable, "-c", _MIGRATE, str(path), revision], cwd=REPO_ROOT, check=True,
                   capture_output=True)
    if entries:
        con = sqlite3.connect(path)
        # Fill every NOT NULL column that has no default (the model's defaults are Python-side).
        extra = {r[1]: (0 if "INT" in r[2].upper() or "BOOL" in r[2].upper() else "x")
                 for r in con.execute("PRAGMA table_info(service_entry)")
                 if r[3] and r[4] is None and not r[5]}
        for i in range(entries):
            row = {**extra, "host": f"h{i}", "container_name": f"svc{i}", "last_updated": "2026-01-01 00:00:00"}
            con.execute(f"INSERT INTO service_entry ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                        list(row.values()))
        con.commit()
        con.close()
    return str(path)


def fake_db(path, tables=("alembic_version", "service_entry", "setting"), revision=None):
    con = sqlite3.connect(path)
    for t in tables:
        con.execute(f'CREATE TABLE "{t}" (version_num TEXT, key TEXT, value TEXT)')
    if revision and "alembic_version" in tables:
        con.execute("INSERT INTO alembic_version VALUES (?, NULL, NULL)", (revision,))
    con.commit()
    con.close()
    return str(path)


def _count(path, table="service_entry"):
    con = sqlite3.connect(path)
    try:
        return con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
    finally:
        con.close()


@pytest.fixture(scope="module")
def head_db(tmp_path_factory):
    return migrated_db(tmp_path_factory.mktemp("head") / "head.sqlite3", entries=3)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    """A temp CONFIG_DIR for restore_staging."""
    monkeypatch.setattr(restore_staging, "CONFIG_DIR", str(tmp_path))
    return tmp_path


def swap(config_dir):
    return subprocess.run([sys.executable, os.path.join(REPO_ROOT, "restore_swap.py")],
                          env={**os.environ, "STD_CONFIG_DIR": str(config_dir)}, capture_output=True,
                          text=True, cwd=str(config_dir))


# --- validate --------------------------------------------------------------------------------


def test_validate_good_snapshot_reports_metadata(app, head_db):
    info = restore_staging.validate(head_db)
    assert info["entries"] == 3 and info["revision"] in restore_staging._known_revisions()
    assert info["latest_update"] == "2026-01-01 00:00:00"
    assert info["instance_id"] is None and info["same_install"] is False


def test_validate_accepts_a_snapshot_made_by_run_snapshot(app, tmp_path, monkeypatch):
    """The live test database has no alembic_version table, so add it as production has."""
    monkeypatch.setitem(app.config, "backup_path", str(tmp_path))
    with app.app_context():
        result = backups.run_snapshot(app, "manual")
    assert result["ok"]
    path = os.path.join(tmp_path, result["file"])
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL)")
    con.execute("DELETE FROM alembic_version")
    con.execute("INSERT INTO alembic_version VALUES (?)", (OLDER_REVISION,))
    con.commit()
    con.close()
    assert restore_staging.validate(path)["revision"] == OLDER_REVISION


def test_validate_older_known_revision_is_accepted(tmp_path):
    assert restore_staging.validate(fake_db(tmp_path / "o.sqlite3", revision=OLDER_REVISION))["revision"] \
        == OLDER_REVISION


def test_validate_rejects_corrupt_file(tmp_path, head_db):
    bad = tmp_path / "bad.sqlite3"
    bad.write_bytes(open(head_db, "rb").read()[:5000])
    with pytest.raises(restore_staging.RestoreError):
        restore_staging.validate(str(bad))
    garbage = tmp_path / "garbage.sqlite3"
    garbage.write_bytes(b"this is not a database" * 200)
    with pytest.raises(restore_staging.RestoreError):
        restore_staging.validate(str(garbage))


def test_validate_rejects_non_std_sqlite(tmp_path):
    other = tmp_path / "other.sqlite3"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE notes (id INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(restore_staging.RestoreError, match="not an STD database"):
        restore_staging.validate(str(other))


def test_validate_rejects_unknown_revision_as_newer(tmp_path):
    path = fake_db(tmp_path / "n.sqlite3", revision="ffffffffffff")
    with pytest.raises(restore_staging.RestoreError, match="newer STD"):
        restore_staging.validate(path)


# --- stage / pending / cancel ------------------------------------------------------------------


def test_stage_pending_cancel(app, cfg, head_db):
    meta = restore_staging.stage(head_db, "2026-snap.sqlite3", "admin", "/keep")
    pend = restore_staging.pending()
    assert pend == meta
    assert set(meta) >= {"source_name", "sha256", "revision", "staged_at", "staged_by", "keep_dir"}
    assert meta["keep_dir"] == "/keep" and meta["staged_by"] == "admin"
    staged = cfg / "restore" / "pending.sqlite3"
    assert hashlib.sha256(staged.read_bytes()).hexdigest() == meta["sha256"]
    assert _count(str(staged)) == 3
    assert restore_staging.cancel() is True
    assert restore_staging.pending() is None and not staged.exists()
    assert restore_staging.cancel() is False


def test_stage_refuses_an_invalid_file_and_leaves_nothing(cfg, tmp_path):
    with pytest.raises(restore_staging.RestoreError):
        restore_staging.stage(fake_db(tmp_path / "x.sqlite3"), "x", "admin", "/keep")
    assert restore_staging.pending() is None


# --- restore_swap.py ---------------------------------------------------------------------------


def _stage_for_swap(cfg, snapshot, keep):
    return restore_staging.stage(snapshot, "snap.sqlite3", "admin", str(keep))


def test_swap_nothing_pending_changes_nothing(tmp_path):
    db_file = migrated_db(tmp_path / "services.db", entries=1)
    before = open(db_file, "rb").read()
    proc = swap(tmp_path)
    assert proc.returncode == 0 and "no restore pending" in proc.stdout
    assert open(db_file, "rb").read() == before
    assert not (tmp_path / "restore").exists()


def test_swap_replaces_db_keeps_old_with_wal_rows(app, cfg, head_db, tmp_path):
    live = tmp_path / "services.db"
    migrated_db(live, entries=1)
    keep = tmp_path / "keep"
    # a row committed only in the live database's WAL (no checkpoint)
    con = sqlite3.connect(live)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    cols = {r[1]: (0 if "INT" in r[2].upper() or "BOOL" in r[2].upper() else "x")
            for r in con.execute("PRAGMA table_info(service_entry)") if r[3] and r[4] is None and not r[5]}
    cols.update(host="walhost", container_name="wal-only", last_updated="2026-01-02 00:00:00")
    con.execute(f"INSERT INTO service_entry ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                list(cols.values()))
    con.commit()
    assert os.path.getsize(str(live) + "-wal") > 0
    _stage_for_swap(cfg, head_db, keep)
    proc = swap(tmp_path)
    con.close()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _count(str(live)) == 3                                   # the snapshot's rows
    assert not os.path.exists(str(live) + "-wal") and not os.path.exists(str(live) + "-shm")
    kept = [f for f in os.listdir(keep) if f.startswith("pre-restore-")]
    assert len(kept) == 1
    old = sqlite3.connect(os.path.join(keep, kept[0]))
    assert old.execute("SELECT COUNT(*) FROM service_entry").fetchone()[0] == 2
    assert old.execute("SELECT COUNT(*) FROM service_entry WHERE container_name='wal-only'").fetchone()[0] == 1
    assert old.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    old.close()
    last = json.loads((tmp_path / "restore" / "last.json").read_text())
    assert last["ok"] is True and last["kept_as"] == kept[0] and last["source_name"] == "snap.sqlite3"
    assert not (tmp_path / "restore" / "pending.json").exists()
    assert not (tmp_path / "restore" / "pending.sqlite3").exists()
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".restore-old")]


def test_swap_checksum_mismatch_keeps_current_db(cfg, head_db, tmp_path):
    live = migrated_db(tmp_path / "services.db", entries=1)
    before = open(live, "rb").read()
    _stage_for_swap(cfg, head_db, tmp_path / "keep")
    meta_path = tmp_path / "restore" / "pending.json"
    meta = json.loads(meta_path.read_text())
    meta["sha256"] = "0" * 64
    meta_path.write_text(json.dumps(meta))
    proc = swap(tmp_path)
    assert proc.returncode == 0
    assert open(live, "rb").read() == before
    names = os.listdir(tmp_path / "restore")
    assert any(n.startswith("failed-") and n.endswith(".sqlite3") for n in names)
    assert any(n.startswith("failed-") and n.endswith(".json") for n in names)
    assert "pending.json" not in names and "pending.sqlite3" not in names
    last = json.loads((tmp_path / "restore" / "last.json").read_text())
    assert last["ok"] is False and "checksum" in last["error"]
    assert restore_staging.pending() is None


def test_swap_without_a_current_db_still_restores(cfg, head_db, tmp_path):
    _stage_for_swap(cfg, head_db, tmp_path / "keep")
    assert swap(tmp_path).returncode == 0
    assert _count(str(tmp_path / "services.db")) == 3


def test_swap_with_unusable_metadata_exits_zero(tmp_path):
    (tmp_path / "restore").mkdir()
    (tmp_path / "restore" / "pending.json").write_text("{not json")
    proc = swap(tmp_path)
    assert proc.returncode == 0
    assert json.loads((tmp_path / "restore" / "last.json").read_text())["ok"] is False


def test_restored_older_revision_migrates_forward(cfg, tmp_path):
    old = migrated_db(tmp_path / "old.sqlite3", OLDER_REVISION)
    _stage_for_swap(cfg, old, tmp_path / "keep")
    assert swap(tmp_path).returncode == 0
    live = str(tmp_path / "services.db")
    con = sqlite3.connect(live)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone()[0] == OLDER_REVISION
    con.close()
    subprocess.run([sys.executable, "-c", _MIGRATE, live, "head"], cwd=REPO_ROOT, check=True,
                   capture_output=True)
    con = sqlite3.connect(live)
    head = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    con.close()
    assert head != OLDER_REVISION


def test_entrypoint_runs_the_swap_before_migrations():
    text = open(os.path.join(REPO_ROOT, "entrypoint.sh")).read()
    assert text.index("restore_swap.py") < text.index("alembic upgrade head")


# --- pre-restore files in the snapshot list ----------------------------------------------------


def test_pre_restore_files_are_listed_tagged_and_never_pruned(tmp_path):
    f = tmp_path / "pre-restore-20260101-000000.sqlite3"
    f.write_bytes(b"x")
    old = 1000000
    os.utime(f, (old, old))
    listed = backups.list_files(str(tmp_path))["snapshots"]
    assert [r["name"] for r in listed] == [f.name] and listed[0]["pre_restore"]
    assert backups.prune(str(tmp_path), "snapshot", 1) == 0 and f.exists()
    assert backups.resolve_file(f.name, str(tmp_path)) is not None


# --- routes ------------------------------------------------------------------------------------


@pytest.fixture
def snapdir(app, tmp_path, monkeypatch):
    d = tmp_path / "bk"
    d.mkdir()
    monkeypatch.setitem(app.config, "backup_path", str(d))
    monkeypatch.setitem(app.config, "CONFIG_FROM_ENV", {})
    monkeypatch.setitem(app.config, "CONFIG_FROM_FILE", {})
    return d


def _put_snapshot(snapdir, head_db, name="2026-01-01-std_backup.sqlite3"):
    path = snapdir / name
    with open(head_db, "rb") as src, open(path, "wb") as dst:
        dst.write(src.read())
    return name


def test_stage_from_server_file_shows_found_then_confirm_stages(admin_client, cfg, snapdir, head_db):
    name = _put_snapshot(snapdir, head_db)
    resp = admin_client.post("/settings/restore/stage", data={"server_file": name})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'id="restore-confirm"' in html
    assert "3 entries" in html and "Everything since the snapshot is lost" in html
    assert restore_staging.pending() is None                         # nothing staged by looking
    resp = admin_client.post("/settings/restore/confirm", data={"server_file": name})
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    pend = restore_staging.pending()
    assert pend["source_name"] == name and pend["keep_dir"] == str(snapdir)


def test_stage_upload_confirm_and_cleanup(admin_client, cfg, snapdir, head_db):
    data = {"snapshot_file": (io.BytesIO(open(head_db, "rb").read()), "mine.sqlite3")}
    resp = admin_client.post("/settings/restore/stage", data=data, content_type="multipart/form-data")
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "Found in mine.sqlite3" in html
    uploads = [n for n in os.listdir(cfg / "restore") if n.startswith("upload-")]
    assert len(uploads) == 1
    import re
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    resp = admin_client.post("/settings/restore/confirm", data={"token": token, "source_name": "mine.sqlite3"})
    assert resp.status_code == 302
    assert restore_staging.pending()["source_name"] == "mine.sqlite3"
    assert not [n for n in os.listdir(cfg / "restore") if n.startswith("upload-")]


def test_upload_size_limit(admin_client, cfg, snapdir, head_db, monkeypatch):
    monkeypatch.setattr(restore_staging, "MAX_UPLOAD_BYTES", 1000)
    data = {"snapshot_file": (io.BytesIO(b"x" * 200_000), "big.sqlite3")}
    resp = admin_client.post("/settings/restore/stage", data=data, content_type="multipart/form-data",
                             follow_redirects=True)
    assert "larger than" in resp.get_data(as_text=True)
    assert restore_staging.pending() is None
    assert not [n for n in os.listdir(cfg / "restore") if n.startswith("upload-")] \
        if (cfg / "restore").exists() else True


def test_invalid_upload_is_rejected_and_removed(admin_client, cfg, snapdir):
    data = {"snapshot_file": (io.BytesIO(b"nope" * 100), "bad.sqlite3")}
    resp = admin_client.post("/settings/restore/stage", data=data, content_type="multipart/form-data",
                             follow_redirects=True)
    assert "Could not use bad.sqlite3" in resp.get_data(as_text=True)
    assert not [n for n in os.listdir(cfg / "restore") if n.startswith("upload-")]


@pytest.mark.parametrize("name", ["../../etc/passwd", "a/b.sqlite3", "missing-std_backup.sqlite3",
                                  "2026-01-01-std_backup.yml"])
def test_server_file_is_confined(admin_client, cfg, snapdir, name):
    for path in ("/settings/restore/stage", "/settings/restore/confirm"):
        resp = admin_client.post(path, data={"server_file": name}, follow_redirects=True)
        assert resp.status_code == 200 and "not a snapshot in the backup folder" in resp.get_data(as_text=True)
    assert restore_staging.pending() is None


def test_confirm_with_a_bad_token_is_refused(admin_client, cfg, snapdir):
    resp = admin_client.post("/settings/restore/confirm", data={"token": "../../x"}, follow_redirects=True)
    assert "expired" in resp.get_data(as_text=True) and restore_staging.pending() is None


def test_pending_banner_on_every_section_then_cancel(admin_client, cfg, snapdir, head_db):
    name = _put_snapshot(snapdir, head_db)
    admin_client.post("/settings/restore/confirm", data={"server_file": name})
    for section in ("about", "groups", "backup"):
        html = admin_client.get(f"/settings?section={section}").get_data(as_text=True)
        assert "data-restore-pending" in html and "Cancel restore" in html
    admin_client.post("/settings/restore/cancel")
    assert "data-restore-pending" not in admin_client.get("/settings?section=about").get_data(as_text=True)
    assert restore_staging.pending() is None


def test_snapshot_rows_offer_restore_and_card_renders(admin_client, cfg, snapdir, head_db):
    _put_snapshot(snapdir, head_db)
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    assert "Restore&hellip;" in html and 'id="backup-restore"' in html and 'name="snapshot_file"' in html


def test_last_result_banner_until_dismissed(app, admin_client, cfg, snapdir):
    (cfg / "restore").mkdir()
    (cfg / "restore" / "last.json").write_text(json.dumps(
        {"ok": True, "at": "2026-11-20T01:00:00", "source_name": "snap.sqlite3",
         "kept_as": "pre-restore-20261120-010000.sqlite3", "error": None}))
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    assert 'data-restore-result="ok"' in html and "pre-restore-20261120-010000.sqlite3" in html
    admin_client.post("/settings/restore/dismiss")
    assert 'data-restore-result' not in admin_client.get("/settings?section=backup").get_data(as_text=True)
    (cfg / "restore" / "last.json").write_text(json.dumps(
        {"ok": False, "at": "2026-11-21T01:00:00", "source_name": "snap.sqlite3", "kept_as": None,
         "error": "checksum"}))
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    assert 'data-restore-result="error"' in html and "checksum" in html


def test_restore_routes_need_an_admin(client, cfg):
    for path in ("stage", "confirm", "cancel", "dismiss"):
        resp = client.post(f"/settings/restore/{path}")
        assert resp.status_code in (302, 401, 403)
