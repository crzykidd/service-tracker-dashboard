"""Backup settings, jobs, files and the Settings -> Backup & restore routes (bak-01)."""

import os
import re
import sqlite3
import threading
import time
from datetime import datetime

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import backups
import jobs
import settings_store
from extensions import db
from models import ServiceEntry
from settings_loader import CONFIG_DIR


@pytest.fixture
def folder(app, tmp_path):
    old = {k: app.config.get(k) for k in ("backup_path", "backup_days_to_keep")}
    old_env, old_file = app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"]
    app.config["backup_path"] = str(tmp_path)
    app.config["backup_days_to_keep"] = 7
    app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = {}, {}
    yield tmp_path
    app.config.update(old)
    app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = old_env, old_file


def _save(app, **values):
    with app.app_context():
        errors, warnings = backups.save_settings(app, values)
        if not errors:
            db.session.commit()
        return errors, warnings


def _eff(app):
    with app.app_context():
        return backups.effective_settings(app)


# --- precedence ----------------------------------------------------------------------------


def test_defaults(app, folder):
    eff = _eff(app)
    assert eff["path"]["value"] == str(folder) and eff["path"]["origin"] == "default"
    assert eff["snapshot"]["time"]["value"] == "00:05"
    assert eff["export"]["time"]["value"] == "00:10"
    assert eff["snapshot"]["enabled"]["value"] is True
    assert eff["export"]["format"]["value"] == "yaml"
    assert eff["snapshot"]["keep_days"]["value"] == 7


def test_file_value_then_ui_beats_file_then_reset(app, folder):
    app.config["backup_days_to_keep"] = 14
    app.config["CONFIG_FROM_FILE"] = {"backup_days_to_keep": 14}
    eff = _eff(app)
    assert eff["snapshot"]["keep_days"]["value"] == 14
    assert eff["snapshot"]["keep_days"]["origin"] == "file"
    assert _save(app, snapshot_keep_days="30")[0] == {}
    eff = _eff(app)
    assert eff["snapshot"]["keep_days"]["value"] == 30
    assert eff["snapshot"]["keep_days"]["origin"] == "ui"
    assert eff["export"]["keep_days"]["value"] == 14      # the other kind is untouched
    with app.app_context():
        assert backups.reset("snapshot_keep_days")
        db.session.commit()
    eff = _eff(app)
    assert eff["snapshot"]["keep_days"]["value"] == 14
    assert eff["snapshot"]["keep_days"]["origin"] == "file"


def test_saving_an_unchanged_value_does_not_make_it_a_ui_value(app, folder):
    app.config["CONFIG_FROM_FILE"] = {"backup_days_to_keep": 7}
    assert _save(app, snapshot_keep_days="7", export_keep_days="7")[0] == {}
    assert _eff(app)["snapshot"]["keep_days"]["origin"] == "file"


def test_env_beats_ui_and_a_save_is_refused(app, folder):
    assert _save(app, export_keep_days="20")[0] == {}
    app.config["CONFIG_FROM_ENV"] = {"backup_days_to_keep": 9}
    app.config["backup_days_to_keep"] = 9
    eff = _eff(app)
    assert eff["export"]["keep_days"]["value"] == 9
    assert eff["export"]["keep_days"]["origin"] == "env"
    assert eff["export"]["keep_days"]["env_name"] == "BACKUP_DAYS_TO_KEEP"
    errors, _ = _save(app, export_keep_days="30")
    assert "BACKUP_DAYS_TO_KEEP" in errors["export_keep_days"]
    assert _save(app, export_keep_days="9")[0] == {}      # the read-only field echoes the env value


def test_env_path_refuses_a_different_path(app, folder, tmp_path_factory):
    app.config["CONFIG_FROM_ENV"] = {"backup_path": str(folder)}
    other = tmp_path_factory.mktemp("other")
    errors, _ = _save(app, path=str(other))
    assert "BACKUP_PATH" in errors["path"]
    assert _eff(app)["path"]["origin"] == "env"


def test_backup_days_seeds_both_keep_days(app, folder):
    app.config["backup_days_to_keep"] = 21
    eff = _eff(app)
    assert eff["snapshot"]["keep_days"]["value"] == eff["export"]["keep_days"]["value"] == 21


@pytest.mark.parametrize("values,key", [
    ({"snapshot_time": "24:00"}, "snapshot_time"),
    ({"export_time": "7:5"}, "export_time"),
    ({"snapshot_keep_days": "0"}, "snapshot_keep_days"),
    ({"export_keep_days": "366"}, "export_keep_days"),
    ({"export_keep_days": "abc"}, "export_keep_days"),
    ({"export_format": "xml"}, "export_format"),
])
def test_validation_errors_write_nothing(app, folder, values, key):
    errors, _ = _save(app, snapshot_enabled=False, **values)
    assert key in errors
    assert _eff(app)["snapshot"]["enabled"]["value"] is True


# --- validate_path -------------------------------------------------------------------------


def test_validate_path_rules(tmp_path):
    assert backups.validate_path("relative/dir")[1]
    f = tmp_path / "afile"
    f.write_text("x")
    assert backups.validate_path(str(f))[1]
    assert backups.validate_path("")[1]
    new = tmp_path / "made" / "deeper"
    real, errors, _ = backups.validate_path(str(new))
    assert not errors and os.path.isdir(real)
    assert not os.path.exists(os.path.join(real, ".std-write-test"))


@pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere")
def test_validate_path_unwritable(tmp_path):
    d = tmp_path / "ro"
    d.mkdir()
    d.chmod(0o500)
    try:
        assert backups.validate_path(str(d))[1]
    finally:
        d.chmod(0o700)


def test_validate_path_warns_outside_config_only(tmp_path):
    assert backups.validate_path(str(tmp_path / "x"))[2]
    inside = os.path.join(CONFIG_DIR, "bk-inside")
    _, errors, warnings = backups.validate_path(inside)
    assert not errors and not warnings


# --- scheduler -----------------------------------------------------------------------------


@pytest.fixture
def sched_factory(app):
    """A real BackgroundScheduler started paused (so no job ever fires)."""
    made = []

    def make():
        sched = BackgroundScheduler()
        sched.start(paused=True)
        jobs._add_backup_jobs(app, sched)
        made.append(sched)
        return sched
    yield make
    for sched in made:
        sched.shutdown(wait=False)


def test_reschedule_sets_times_pauses_and_resumes(app, folder, sched_factory):
    sched = sched_factory()
    assert _save(app, snapshot_time="03:30", export_time="04:45", export_enabled=False)[0] == {}
    jobs.reschedule_backups(app, sched)

    def fields(job):
        return {f.name: str(f) for f in job.trigger.fields}

    snap, exp = sched.get_job(jobs.BACKUP_SNAPSHOT_JOB), sched.get_job(jobs.BACKUP_EXPORT_JOB)
    assert fields(snap)["hour"] == "3" and fields(snap)["minute"] == "30"
    assert fields(exp)["hour"] == "4" and fields(exp)["minute"] == "45"
    assert snap.next_run_time is not None
    assert exp.next_run_time is None
    assert jobs.next_run_times(sched)["export"] is None
    assert _save(app, export_enabled=True)[0] == {}
    jobs.reschedule_backups(app, sched)
    assert sched.get_job(jobs.BACKUP_EXPORT_JOB).next_run_time is not None


def test_disabled_job_is_added_paused(app, folder, sched_factory):
    assert _save(app, snapshot_enabled=False)[0] == {}
    sched = sched_factory()
    assert sched.get_job(jobs.BACKUP_SNAPSHOT_JOB).next_run_time is None
    assert sched.get_job(jobs.BACKUP_EXPORT_JOB).next_run_time is not None


# --- runs ----------------------------------------------------------------------------------


def test_manual_snapshot_is_valid_timestamped_and_recorded(app, folder):
    with app.app_context():
        db.session.add(ServiceEntry(host="h", container_name="a", last_updated=datetime.now()))
        db.session.commit()
    result = backups.run_snapshot(app, "manual")
    assert result["ok"] and re.match(r"^\d{4}-\d{2}-\d{2}_\d{6}-std_backup\.sqlite3$", result["file"])
    path = folder / result["file"]
    assert sqlite3.connect(path).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    with app.app_context():
        rec = settings_store.get_backup_last_runs()["snapshot"]
    assert rec["ok"] is True and rec["file"] == result["file"] and rec["trigger"] == "manual"


def test_scheduled_names_have_no_time(app, folder):
    assert backups.run_snapshot(app, "schedule")["file"] == datetime.now().strftime("%Y-%m-%d-std_backup.sqlite3")
    assert backups.run_export(app, "schedule")["file"] == datetime.now().strftime("%Y-%m-%d-std_backup.yml")


def test_failed_snapshot_is_recorded_and_leaves_no_tmp(app, folder, monkeypatch):
    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(backups.sqlite3, "connect", boom)
    result = backups.run_snapshot(app, "manual")
    assert not result["ok"] and "disk full" in result["error"]
    assert not list(folder.glob("*.tmp")) and not list(folder.glob("*.sqlite3"))
    with app.app_context():
        rec = settings_store.get_backup_last_runs()["snapshot"]
        assert rec["ok"] is False and "disk full" in rec["error"]
        assert backups.attention_needed()


def test_success_after_failure_clears_attention(app, folder, monkeypatch):
    with monkeypatch.context() as m:
        m.setattr(backups.sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
        backups.run_snapshot(app, "manual")
    with app.app_context():
        assert backups.attention_needed()
    assert backups.run_snapshot(app, "manual")["ok"]
    with app.app_context():
        assert not backups.attention_needed()


def test_concurrent_run_says_already_running(app, folder):
    lock = backups._RUN_LOCKS["snapshot"]
    assert lock.acquire(blocking=False)
    try:
        result = backups.run_snapshot(app, "manual")
    finally:
        lock.release()
    assert not result["ok"] and result["busy"] and "already running" in result["error"]
    with app.app_context():
        assert "snapshot" not in settings_store.get_backup_last_runs()


def test_runs_of_different_kinds_do_not_block_each_other(app, folder):
    lock = backups._RUN_LOCKS["snapshot"]
    done = {}
    assert lock.acquire(blocking=False)
    try:
        t = threading.Thread(target=lambda: done.update(r=backups.run_export(app, "manual")))
        t.start()
        t.join(10)
    finally:
        lock.release()
    assert done["r"]["ok"]


# --- retention and listing -----------------------------------------------------------------


def test_retention_is_per_kind_by_mtime_and_suffix(app, folder):
    old = time.time() - 30 * 86400
    names = {
        "2020-01-01-std_backup.sqlite3": "snapshot",
        "2020-01-01-std_backup.yml": "export",
        "2020-01-01-std_export.yml": "export",
        "2020-01-01-std_export.json": "export",
        "backup.yml": None,
        "notes.txt": None,
        "2020-01-01-other.sqlite3": None,
    }
    for n in names:
        p = folder / n
        p.write_text("x")
        os.utime(p, (old, old))
    assert backups.prune(str(folder), "snapshot", 7) == 1
    assert not (folder / "2020-01-01-std_backup.sqlite3").exists()
    assert (folder / "2020-01-01-std_backup.yml").exists()           # the other kind is kept
    assert backups.prune(str(folder), "export", 7) == 3
    for n in ("backup.yml", "notes.txt", "2020-01-01-other.sqlite3"):
        assert (folder / n).exists(), n


def test_list_files_classifies_and_sorts(app, folder):
    now = time.time()
    for n, age in (("2026-01-01-std_backup.sqlite3", 3), ("2026-01-02_101500-std_backup.sqlite3", 1),
                   ("2026-01-02-std_backup.yml", 2), ("backup.yml", 5), ("ignored.txt", 1), ("x.tmp", 1)):
        p = folder / n
        p.write_text("data")
        os.utime(p, (now - age * 3600, now - age * 3600))
    with app.app_context():
        listing = backups.list_files()
    assert [f["name"] for f in listing["snapshots"]] == [
        "2026-01-02_101500-std_backup.sqlite3", "2026-01-01-std_backup.sqlite3"]
    assert listing["snapshots"][0]["manual"] and not listing["snapshots"][1]["manual"]
    assert [f["name"] for f in listing["exports"]] == ["2026-01-02-std_backup.yml", "backup.yml"]
    assert all(f["legacy"] for f in listing["exports"])


# --- routes --------------------------------------------------------------------------------


def _section(html, slug):
    start = html.index(f'id="section-{slug}"')
    nxt = html.find('<section id="section-', start + 10)
    return html[start:nxt if nxt != -1 else len(html)]


def test_save_bad_time_rerenders_400_with_banner_and_typed_values(app, folder, admin_client):
    resp = admin_client.post("/settings/backups/settings", data={
        "path": str(folder), "snapshot_enabled": "1", "snapshot_time": "99:99", "snapshot_keep_days": "12",
        "export_time": "00:10", "export_keep_days": "7", "export_format": "yaml"})
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    section = _section(html, "backup")
    assert "flash-alert" in section and "HH:MM" in section
    assert 'value="99:99"' in section and 'value="12"' in section
    assert _eff(app)["snapshot"]["keep_days"]["value"] == 7


def test_save_success_redirects_to_backup_and_reschedules(app, folder, admin_client, monkeypatch):
    calls = []
    monkeypatch.setattr(jobs, "reschedule_backups", lambda a: calls.append(a))
    resp = admin_client.post("/settings/backups/settings", data={
        "path": str(folder), "snapshot_enabled": "1", "snapshot_time": "02:15", "snapshot_keep_days": "10",
        "export_time": "00:10", "export_keep_days": "7", "export_format": "json"})
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    assert calls
    eff = _eff(app)
    assert eff["snapshot"]["time"]["value"] == "02:15" and eff["export"]["format"]["value"] == "json"
    assert eff["export"]["enabled"]["value"] is False       # the switch was not submitted


def test_new_path_is_created_and_warned_about(app, folder, admin_client, tmp_path_factory):
    target = tmp_path_factory.mktemp("elsewhere") / "bk"
    resp = admin_client.post("/settings/backups/settings", data={
        "path": str(target), "snapshot_enabled": "1", "snapshot_time": "00:05", "snapshot_keep_days": "7",
        "export_enabled": "1", "export_time": "00:10", "export_keep_days": "7", "export_format": "yaml"},
        follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert target.is_dir()
    assert "outside /config" in _section(html, "backup")                       # warning banner
    assert "Existing backups stay in the old folder" in html[html.index('id="toast-region"'):]
    assert _eff(app)["path"]["origin"] == "ui"


def test_reset_route(app, folder, admin_client):
    assert _save(app, snapshot_keep_days="40")[0] == {}
    resp = admin_client.post("/settings/backups/settings/reset", data={"key": "snapshot_keep_days"})
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    assert _eff(app)["snapshot"]["keep_days"]["origin"] == "default"
    resp = admin_client.post("/settings/backups/settings/reset", data={"key": "bogus"}, follow_redirects=True)
    assert "Unknown backup setting" in resp.get_data(as_text=True)


def test_run_now_redirects_with_a_toast(app, folder, admin_client):
    resp = admin_client.post("/settings/backups/run", data={"kind": "snapshot"})
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    html = admin_client.get(resp.headers["Location"]).get_data(as_text=True)
    toasts = html[html.index('id="toast-region"'):]
    assert "Snapshot saved:" in toasts and "-std_backup.sqlite3" in toasts
    assert len(list(folder.glob("*-std_backup.sqlite3"))) == 1
    resp = admin_client.post("/settings/backups/run", data={"kind": "export"})
    assert resp.status_code == 302 and len(list(folder.glob("*-std_backup.yml"))) == 1
    resp = admin_client.post("/settings/backups/run", data={"kind": "nope"}, follow_redirects=True)
    assert "Unknown backup kind" in resp.get_data(as_text=True)


def test_failed_run_shows_banner_inline_warning_and_nav_badge(app, folder, admin_client, monkeypatch):
    monkeypatch.setattr(backups.sqlite3, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("no space")))
    resp = admin_client.post("/settings/backups/run", data={"kind": "snapshot"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    section = _section(html, "backup")
    assert "Snapshot failed: no space" in section                 # the banner
    assert 'data-backup-failed="snapshot"' in section and "Last snapshot failed" in section
    nav = html[html.index('class="settings-nav"'):html.index('class="settings-main"')]
    assert re.search(r'data-section="backup".*?settings-nav-badge--bad.*?>!<', nav, re.S)
    # a later success removes both
    monkeypatch.undo()
    admin_client.post("/settings/backups/run", data={"kind": "snapshot"})
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    assert 'data-backup-failed' not in html
    nav = html[html.index('class="settings-nav"'):html.index('class="settings-main"')]
    assert "settings-nav-badge--bad" not in nav


def test_download_and_delete_are_confined(app, folder, admin_client):
    good = folder / "2026-01-01-std_backup.sqlite3"
    good.write_text("snap")
    (folder / "notes.txt").write_text("n")
    resp = admin_client.get("/settings/backups/2026-01-01-std_backup.sqlite3/download")
    assert resp.status_code == 200 and resp.data == b"snap"
    for bad in ("..%2Fx.yml", "%2Fetc%2Fpasswd", "notes.txt", "nothere-std_backup.sqlite3", "..", "sub%2Fa-std_backup.yml"):
        assert admin_client.get(f"/settings/backups/{bad}/download").status_code == 404, bad
        assert admin_client.post(f"/settings/backups/{bad}/delete").status_code == 404, bad
    assert (folder / "notes.txt").exists()
    resp = admin_client.post("/settings/backups/2026-01-01-std_backup.sqlite3/delete")
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    assert not good.exists()


def test_symlink_out_of_the_folder_is_refused(app, folder, admin_client, tmp_path_factory):
    outside = tmp_path_factory.mktemp("out") / "secret-std_backup.yml"
    outside.write_text("secret")
    os.symlink(outside, folder / "link-std_backup.yml")
    assert admin_client.get("/settings/backups/link-std_backup.yml/download").status_code == 404
    assert outside.exists()


def test_page_lists_files_with_confirm_delete_and_no_nested_forms(app, folder, admin_client):
    (folder / "2026-01-01-std_backup.sqlite3").write_text("s")
    (folder / "backup.yml").write_text("[]")
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    section = _section(html, "backup")
    assert "2026-01-01-std_backup.sqlite3" in section and "legacy" in section
    assert re.search(r'<form[^>]*data-confirm="Delete 2026-01-01-std_backup\.sqlite3\?', section)
    assert "Snapshots contain every secret" in section
    assert "Import (legacy)" in section
    settings_form = section[section.index('id="backup-settings-form"'):section.index("</form>", section.index('id="backup-settings-form"'))]
    assert "<form" not in settings_form[5:]


def test_env_pinned_fields_render_read_only(app, folder, admin_client):
    app.config["CONFIG_FROM_ENV"] = {"backup_path": str(folder), "backup_days_to_keep": 7}
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    section = _section(html, "backup")
    assert "BACKUP_PATH" in section and "BACKUP_DAYS_TO_KEEP" in section
    assert re.search(r'<input id="bk-path"[^>]*readonly', section)


def test_backup_routes_need_admin(app, folder):
    c = app.test_client()
    for method, url in (("post", "/settings/backups/run"), ("post", "/settings/backups/settings"),
                        ("get", "/settings/backups/x-std_backup.yml/download")):
        assert getattr(c, method)(url).status_code in (302, 401, 403)
