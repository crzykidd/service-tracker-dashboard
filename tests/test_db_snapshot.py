"""Nightly SQLite snapshot (PRD 18.2): WAL-safe copy, failure isolation, pruning."""

import os
import sqlite3
import time
from datetime import datetime

import backups
from extensions import db
from models import ServiceEntry


def _make(name):
    db.session.add(ServiceEntry(host="h", container_name=name, last_updated=datetime.now()))
    db.session.commit()


def _counts(path):
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {t: con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def _live_counts(app):
    with app.app_context():
        raw = db.engine.raw_connection()
        try:
            tables = [r[0] for r in raw.driver_connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            return {t: raw.driver_connection.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    for t in tables}
        finally:
            raw.close()


def test_snapshot_has_same_tables_and_rows(app, tmp_path):
    with app.app_context():
        _make("a")
        _make("b")
    app.config["backup_path"] = str(tmp_path)
    # The export runs first: a run records `backup_last_runs` (one `setting` row), and the
    # snapshot must be taken after that row exists to match the live counts.
    assert backups.run_export(app, "schedule")["ok"]
    assert backups.run_snapshot(app, "schedule")["ok"]
    name = datetime.now().strftime("%Y-%m-%d-std_backup.sqlite3")
    snap = tmp_path / name
    assert snap.is_file()
    assert (tmp_path / datetime.now().strftime("%Y-%m-%d-std_export.yml")).is_file()
    assert sqlite3.connect(snap).execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    counts = _counts(snap)
    assert counts == _live_counts(app)
    assert not list(tmp_path.glob("*.tmp"))


def test_snapshot_failure_does_not_stop_yaml_backup(app, tmp_path, monkeypatch):
    app.config["backup_path"] = str(tmp_path)

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(backups.sqlite3, "connect", boom)
    assert not backups.run_snapshot(app, "schedule")["ok"]
    assert backups.run_export(app, "schedule")["ok"]
    assert (tmp_path / datetime.now().strftime("%Y-%m-%d-std_export.yml")).is_file()
    assert not list(tmp_path.glob("*.sqlite3"))


def test_prune_removes_only_old_backup_files(app, tmp_path):
    app.config["backup_path"] = str(tmp_path)
    app.config["backup_days_to_keep"] = 7
    old = time.time() - 30 * 86400
    names = {
        "2020-01-01-std_backup.yml": True,
        "2020-01-01-std_backup.sqlite3": True,
        "notes.txt": False,
        "services.sqlite3": False,
        "2020-01-01-other.sqlite3": False,
    }
    for n in names:
        p = tmp_path / n
        p.write_text("x")
        os.utime(p, (old, old))
    assert backups.run_snapshot(app, "schedule")["ok"]
    assert backups.run_export(app, "schedule")["ok"]
    for n, removed in names.items():
        assert (not (tmp_path / n).exists()) == removed, n
    assert (tmp_path / datetime.now().strftime("%Y-%m-%d-std_backup.sqlite3")).exists()
