"""Apply a staged database restore before migrations (backup phase 5, design section 10.1).

Run by `entrypoint.sh` ahead of `alembic upgrade head`. **Standard library only, no app
import**: it must work when the app (or its database) cannot even be imported.

- Nothing pending (`<CONFIG_DIR>/restore/pending.json` absent): exit 0 at once.
- Otherwise: re-check the staged file (sha256 + integrity_check), keep the current database
  with `sqlite3.Connection.backup()` as `<keep_dir>/pre-restore-YYYYMMDD-HHMMSS.sqlite3`
  (WAL-safe; never a file copy of a live database), move the current files aside, put the
  staged file in place, write `restore/last.json`.
- **A failure never stops the container**: the current database is put back, the staged
  files become `failed-<ts>.*`, `last.json` records the error, and the exit code is 0.

`STD_CONFIG_DIR` (default `/config`) is the same knob `settings_loader` reads.
"""

import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime

CONFIG_DIR = os.environ.get("STD_CONFIG_DIR", "/config")
RESTORE_DIR = os.path.join(CONFIG_DIR, "restore")
DB_PATH = os.path.join(CONFIG_DIR, "services.db")
SIDECARS = ("-wal", "-shm")
ASIDE = ".restore-old"


def say(msg):
    print(f"[restore] {msg}", flush=True)


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _integrity_ok(path):
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        rows = con.execute("PRAGMA integrity_check").fetchall()
    finally:
        con.close()
    return rows == [("ok",)]


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _record_failure(meta, error, stamp):
    """Park the staged files as `failed-<ts>.*` and write `last.json` with the error."""
    for ext in (".sqlite3", ".json"):
        src = os.path.join(RESTORE_DIR, "pending" + ext)
        if os.path.exists(src):
            try:
                os.replace(src, os.path.join(RESTORE_DIR, f"failed-{stamp}{ext}"))
            except OSError as e:
                say(f"could not rename {src}: {e}")
    try:
        _write_json(os.path.join(RESTORE_DIR, "last.json"), {
            "ok": False, "at": datetime.now().isoformat(timespec="seconds"),
            "source_name": (meta or {}).get("source_name"), "kept_as": None, "error": str(error)})
    except OSError as e:
        say(f"could not write last.json: {e}")


def _put_back():
    """Undo the move-aside of the current database files."""
    for suffix in ("",) + SIDECARS:
        aside = DB_PATH + suffix + ASIDE
        if os.path.exists(aside):
            os.replace(aside, DB_PATH + suffix)


def run():
    meta_path = os.path.join(RESTORE_DIR, "pending.json")
    pending = os.path.join(RESTORE_DIR, "pending.sqlite3")
    if not os.path.exists(meta_path):
        say("no restore pending")
        return
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M%S")
    meta = None
    moved = False
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        say(f"restore pending: {meta.get('source_name')}")
        if not os.path.exists(pending):
            raise RuntimeError("the staged database file is missing")
        if _sha256(pending) != meta.get("sha256"):
            raise RuntimeError("the staged file does not match its checksum")
        say("checksum ok")
        if not _integrity_ok(pending):
            raise RuntimeError("the staged file failed the integrity check")
        say("integrity ok")

        keep_dir = meta.get("keep_dir") or os.path.join(CONFIG_DIR, "backups")
        os.makedirs(keep_dir, exist_ok=True)
        kept = None
        had_db = os.path.exists(DB_PATH)
        if had_db:
            kept_name = f"pre-restore-{stamp}.sqlite3"
            kept_path = os.path.join(keep_dir, kept_name)
            src = dst = None
            try:
                src = sqlite3.connect(DB_PATH)
                dst = sqlite3.connect(kept_path)
                src.backup(dst)     # WAL-safe; captures committed WAL frames
                kept = kept_name
                say(f"current database kept as {kept_path}")
            except sqlite3.Error as e:
                # Unreadable current database (the very case a restore may be for): keep its
                # raw file instead of refusing to restore.
                say(f"could not read the current database ({e}); keeping its file as-is")
                kept = None
            finally:
                for con in (dst, src):
                    if con is not None:
                        con.close()
                if kept is None and os.path.exists(kept_path):
                    _remove(kept_path)

        for suffix in ("",) + SIDECARS:
            path = DB_PATH + suffix
            if os.path.exists(path):
                os.replace(path, path + ASIDE)
        moved = True
        if had_db and kept is None:
            kept_name = f"pre-restore-{stamp}-unreadable.sqlite3"
            os.replace(DB_PATH + ASIDE, os.path.join(keep_dir, kept_name))
            kept = kept_name
            say(f"current database file kept as {os.path.join(keep_dir, kept_name)}")
        os.replace(pending, DB_PATH)
        for suffix in ("",) + SIDECARS:
            _remove(DB_PATH + suffix + ASIDE)
        _remove(meta_path)
        _write_json(os.path.join(RESTORE_DIR, "last.json"), {
            "ok": True, "at": now.isoformat(timespec="seconds"),
            "source_name": meta.get("source_name"), "revision": meta.get("revision"),
            "kept_as": kept, "kept_dir": keep_dir, "error": None})
        say(f"restored {meta.get('source_name')}; migrations run next")
    except Exception as e:  # noqa: BLE001 - a restore failure must never stop startup
        say(f"restore failed: {e}")
        try:
            if moved and not os.path.exists(DB_PATH):
                _put_back()
                say("the current database was put back")
        except Exception as e2:  # noqa: BLE001
            say(f"could not put the current database back: {e2}")
        _record_failure(meta, e, stamp)


def main():
    try:
        run()
    except Exception as e:  # noqa: BLE001
        say(f"restore step crashed: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
