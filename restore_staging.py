"""Staged database restore, app side (backup phase 5, design section 10).

The app only ever *stages*: it validates a snapshot, copies it to
`<CONFIG_DIR>/restore/pending.sqlite3` and records `pending.json`. The swap happens at the
next container start, before migrations, in `restore_swap.py` (stdlib only). There is no live
swap. Every copy here goes through `sqlite3.Connection.backup()` (CLAUDE.md Database Rules).
"""

import hashlib
import json
import os
import sqlite3
from datetime import datetime

from alembic.config import Config
from alembic.script import ScriptDirectory

import settings_store
from settings_loader import CONFIG_DIR

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
REQUIRED_TABLES = ("alembic_version", "service_entry", "setting")
MAX_UPLOAD_BYTES = 200 * 1024 * 1024


class RestoreError(Exception):
    """The file cannot be restored; the message is shown to the operator."""


def restore_dir():
    return os.path.join(CONFIG_DIR, "restore")


def _path(name):
    """`name` inside the restore folder. Raises RestoreError for a name that would leave it
    (callers pass fixed names or a token already checked against a strict regex)."""
    base = os.path.realpath(restore_dir())
    path = os.path.realpath(os.path.join(base, name))
    if not path.startswith(base + os.sep):
        raise RestoreError("Invalid restore file name.")
    return path


def _known_revisions():
    cfg = Config(os.path.join(REPO_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_DIR, "alembic"))
    script = ScriptDirectory.from_config(cfg)
    return {rev.revision for rev in script.walk_revisions()}


def validate(path):
    """Check `path` is a restorable STD database; return `{revision, entries, latest_update,
    instance_id, same_install}` or raise `RestoreError`."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    except sqlite3.Error as e:
        raise RestoreError(f"Could not open the file as a database: {e}.") from e
    try:
        try:
            rows = con.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.DatabaseError:
            raise RestoreError("This file is not a SQLite database, or it is damaged.") from None
        if rows != [("ok",)]:
            raise RestoreError("The database failed its integrity check; it is damaged.")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not all(t in tables for t in REQUIRED_TABLES):
            raise RestoreError("This is not an STD database (expected tables are missing).")
        versions = [r[0] for r in con.execute("SELECT version_num FROM alembic_version")]
        if len(versions) != 1:
            raise RestoreError("The database has no single schema revision.")
        revision = versions[0]
        if revision not in _known_revisions():
            raise RestoreError(
                f"Schema revision {revision} is unknown to this version: the file was made by a "
                "newer STD. Upgrade STD first.")
        entries = con.execute("SELECT COUNT(*) FROM service_entry").fetchone()[0]
        try:
            latest = con.execute("SELECT MAX(last_updated) FROM service_entry").fetchone()[0]
        except sqlite3.Error:
            latest = None
        instance_id = None
        row = con.execute("SELECT value FROM setting WHERE key = ?",
                          (settings_store.KEY_INSTANCE_ID,)).fetchone()
        if row and row[0]:
            try:
                value = json.loads(row[0])
                instance_id = value if isinstance(value, str) else None
            except (TypeError, ValueError):
                instance_id = None
    except sqlite3.Error as e:
        raise RestoreError(f"Could not read the database: {e}.") from e
    finally:
        con.close()
    return {"revision": revision, "entries": entries, "latest_update": latest,
            "instance_id": instance_id,
            "same_install": bool(instance_id) and instance_id == settings_store.peek_instance_id()}


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stage(path, source_name, user, keep_dir):
    """Validate `path`, copy it (online backup, not a file copy) to `pending.sqlite3` and write
    `pending.json`. Replaces an earlier pending restore. Returns the pending metadata."""
    info = validate(path)
    os.makedirs(restore_dir(), exist_ok=True)
    dest = _path("pending.sqlite3")
    tmp = dest + ".tmp"
    cancel()
    src = dst = None
    try:
        src = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
        dst = sqlite3.connect(tmp)
        src.backup(dst)
    except sqlite3.Error as e:
        raise RestoreError(f"Could not stage the file: {e}.") from e
    finally:
        for con in (dst, src):
            if con is not None:
                con.close()
    os.replace(tmp, dest)
    meta = {"source_name": source_name, "sha256": _sha256(dest), "revision": info["revision"],
            "entries": info["entries"], "staged_at": datetime.now().isoformat(timespec="seconds"),
            "staged_by": user, "keep_dir": keep_dir}
    tmp_json = _path("pending.json.tmp")
    with open(tmp_json, "w") as f:
        json.dump(meta, f, indent=2)
    os.replace(tmp_json, _path("pending.json"))
    return meta


def pending():
    """The staged restore's metadata, or None."""
    try:
        with open(_path("pending.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and os.path.exists(_path("pending.sqlite3")) else None


def cancel():
    """Delete the staged files. True when something was removed."""
    removed = False
    for name in ("pending.json", "pending.json.tmp", "pending.sqlite3", "pending.sqlite3.tmp"):
        try:
            os.remove(_path(name))
            removed = True
        except FileNotFoundError:
            pass
    return removed


def last_result():
    """`restore/last.json` plus `seen` (the operator dismissed it), or None."""
    try:
        with open(_path("last.json")) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    data["seen"] = settings_store.get_restore_last_seen() == data.get("at")
    return data


def mark_seen():
    """Record the current `last.json` as seen. Caller commits."""
    try:
        with open(_path("last.json")) as f:
            at = json.load(f).get("at")
    except (OSError, ValueError, AttributeError):
        return
    settings_store.set_restore_last_seen(at)


def upload_path(token):
    return _path(f"upload-{token}.sqlite3")


def clean_uploads():
    """Remove leftover `upload-*.sqlite3` files (an abandoned confirmation)."""
    try:
        for name in os.listdir(restore_dir()):
            if name.startswith("upload-"):
                try:
                    os.remove(_path(name))
                except OSError:
                    pass
    except OSError:
        pass
