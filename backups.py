"""Backups: effective settings, the two daily jobs' work, file listing (PRD 19.x, design
docs/design/2026-11-20-backup-export-import.md section 4).

Two kinds of file live in one folder:

- **snapshot**: a WAL-safe copy of the whole database (`sqlite3.Connection.backup()`),
  `YYYY-MM-DD-std_backup.sqlite3`.
- **export**: the versioned export of operator-set state (`export_format.py`, format v1),
  `YYYY-MM-DD-std_export.yml|json`. Older `-std_backup.yml` files (the pre-0.11 entry list)
  are still listed and pruned with the exports.

Manual runs carry a time in the name (`YYYY-MM-DD_HHMMSS-...`) so they never overwrite the
scheduled file of the day. Retention is per kind, by mtime, by suffix only: a file that
matches no known suffix is never deleted.

The settings precedence is env > UI (DB row) > `settings.yml` > default. `load_settings()`
runs once at startup and is never called from here; the startup values are read from
`app.config` (`backup_path`, `backup_days_to_keep`, `CONFIG_FROM_ENV`).

Functions here are plain: they raise nothing for routes to catch except where noted, and
the run functions record their outcome in the `backup_last_runs` setting.
"""

import logging
import os
import re
import sqlite3
import threading
import time
from datetime import datetime

from flask import current_app

import export_format
import settings_store
from extensions import db
from settings_loader import CONFIG_DIR

logger = logging.getLogger(__name__)

KINDS = ("snapshot", "export")
KIND_LABELS = {"snapshot": "snapshot", "export": "export"}

SNAPSHOT_SUFFIX = "-std_backup.sqlite3"
# Export files. `-std_backup.yml` is the legacy daily YAML entry list (before 0.11).
EXPORT_SUFFIXES = ("-std_export.yml", "-std_export.json", "-std_backup.yml")
LEGACY_SUFFIXES = ("-std_backup.yml",)
LEGACY_NAMES = ("backup.yml",)          # the old "Save to server" file; never auto-deleted
KNOWN_SUFFIXES = (SNAPSHOT_SUFFIX,) + EXPORT_SUFFIXES
SUFFIXES_BY_KIND = {"snapshot": (SNAPSHOT_SUFFIX,), "export": EXPORT_SUFFIXES}

DEFAULT_KEEP_DAYS = 7
DEFAULT_TIMES = {"snapshot": "00:05", "export": "00:10"}
DEFAULT_FORMAT = "yaml"
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_MANUAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}-")

# Keys the UI can reset (delete the DB row so the value falls back to settings.yml/default).
SETTING_KEYS = (
    "path",
    "snapshot_enabled", "snapshot_time", "snapshot_keep_days",
    "export_enabled", "export_time", "export_keep_days", "export_format",
)
RESETTABLE_KEYS = SETTING_KEYS

_STORE_KEYS = {
    "path": settings_store.KEY_BACKUP_PATH,
    "snapshot_enabled": settings_store.KEY_BACKUP_SNAPSHOT_ENABLED,
    "snapshot_time": settings_store.KEY_BACKUP_SNAPSHOT_TIME,
    "snapshot_keep_days": settings_store.KEY_BACKUP_SNAPSHOT_KEEP_DAYS,
    "export_enabled": settings_store.KEY_BACKUP_EXPORT_ENABLED,
    "export_time": settings_store.KEY_BACKUP_EXPORT_TIME,
    "export_keep_days": settings_store.KEY_BACKUP_EXPORT_KEEP_DAYS,
    "export_format": settings_store.KEY_BACKUP_EXPORT_FORMAT,
}
# Which startup (settings.yml / env) key seeds a setting, for the env check and origin.
_ENV_KEYS = {
    "path": "backup_path",
    "snapshot_keep_days": "backup_days_to_keep",
    "export_keep_days": "backup_days_to_keep",
}
_ENV_NAMES = {"backup_path": "BACKUP_PATH", "backup_days_to_keep": "BACKUP_DAYS_TO_KEEP"}

_RUN_LOCKS = {kind: threading.Lock() for kind in KINDS}


# --- settings ------------------------------------------------------------------------------


def _startup_value(app, key):
    """(value, origin) from the startup dict: `env`, `file` or `default`."""
    value = app.config.get(key)
    if key in app.config.get("CONFIG_FROM_ENV", {}):
        return value, "env"
    if key in app.config.get("CONFIG_FROM_FILE", {}):
        return value, "file"
    return value, "default"


def _valid_keep_days(value):
    return isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 365


def effective_settings(app):
    """Every backup setting with its value and origin (design 4.2).

    `{"path": {value, origin, fallback, env_name}, "snapshot": {"enabled": {...}, "time":
    {...}, "keep_days": {...}}, "export": {..., "format": {...}}}`. `origin` is `env`, `ui`,
    `file` or `default`; `fallback` is what Reset gives back; `env_name` is set when an
    environment variable pins the value."""
    flat = {}

    def resolve(key, default, valid=lambda v: True):
        stored = settings_store.get_backup_value(_STORE_KEYS[key])
        seed_key = _ENV_KEYS.get(key)
        if seed_key:
            seed, seed_origin = _startup_value(app, seed_key)
            if seed_key == "backup_days_to_keep" and not _valid_keep_days(seed):
                seed, seed_origin = DEFAULT_KEEP_DAYS, "default"
            if seed_key == "backup_path" and not (isinstance(seed, str) and seed):
                seed, seed_origin = os.path.join(CONFIG_DIR, "backups"), "default"
        else:
            seed, seed_origin = default, "default"
        entry = {"value": seed, "origin": seed_origin, "fallback": seed, "fallback_origin": seed_origin,
                 "env_name": None}
        if seed_origin == "env":
            entry["env_name"] = _ENV_NAMES[seed_key]
        elif stored is not None and valid(stored):
            entry["value"], entry["origin"] = stored, "ui"
        flat[key] = entry

    resolve("path", os.path.join(CONFIG_DIR, "backups"), lambda v: isinstance(v, str) and bool(v))
    for kind in KINDS:
        resolve(f"{kind}_enabled", True, lambda v: isinstance(v, bool))
        resolve(f"{kind}_time", DEFAULT_TIMES[kind], lambda v: isinstance(v, str) and bool(TIME_RE.match(v)))
        resolve(f"{kind}_keep_days", DEFAULT_KEEP_DAYS, _valid_keep_days)
    resolve("export_format", DEFAULT_FORMAT, lambda v: v in ("yaml", "json"))

    out = {"path": flat["path"]}
    for kind in KINDS:
        out[kind] = {name: flat[f"{kind}_{name}"] for name in ("enabled", "time", "keep_days")}
    out["export"]["format"] = flat["export_format"]
    return out


def effective_flat(app):
    """`effective_settings` keyed by the flat setting keys (`snapshot_time`, ...)."""
    eff = effective_settings(app)
    flat = {"path": eff["path"]}
    for kind in KINDS:
        for name, entry in eff[kind].items():
            flat[f"{kind}_{name}"] = entry
    return flat


def backup_dir(app=None):
    """The effective backup folder."""
    app = app or current_app
    return effective_settings(app)["path"]["value"]


def outside_config(path):
    """True when `path` is not inside CONFIG_DIR (the mounted /config volume)."""
    real = os.path.realpath(path)
    config_real = os.path.realpath(CONFIG_DIR)
    return real != config_real and not real.startswith(config_real + os.sep)


def validate_path(path):
    """`(realpath, errors, warnings)` for a backup folder (design 4.5). Creates the folder
    when missing and proves it is writable. A folder outside CONFIG_DIR is a warning."""
    errors, warnings = [], []
    raw = (path or "").strip()
    if not raw:
        return None, ["The backup folder is required."], warnings
    if not os.path.isabs(raw):
        return None, ["The backup folder must be an absolute path (it starts with /)."], warnings
    real = os.path.realpath(raw)
    if os.path.exists(real) and not os.path.isdir(real):
        return None, [f"{real} exists and is not a folder."], warnings
    try:
        os.makedirs(real, exist_ok=True)
    except OSError as e:
        return None, [f"Could not create {real}: {e.strerror or e}."], warnings
    probe = os.path.join(real, ".std-write-test")
    try:
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
    except OSError as e:
        return None, [f"{real} is not writable: {e.strerror or e}."], warnings
    if outside_config(real):
        warnings.append(
            "This folder is outside /config. Make sure it is a mounted volume, or backups are "
            "lost when the container is recreated.")
    return real, errors, warnings


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "on", "yes")


def save_settings(app, values):
    """Validate and stage the backup settings; the caller commits. `values` maps setting
    keys (`path`, `snapshot_time`, ...) to submitted values; a key left out is untouched.

    A value equal to the current effective one is not written (a save must not turn a
    `settings.yml` value into a UI value). An environment-pinned key refuses a different
    value. Returns `(errors, warnings)`; any error means nothing was staged. `errors` maps
    the setting key to a message."""
    current = effective_flat(app)
    errors, warnings, staged = {}, [], {}

    for key in SETTING_KEYS:
        if key not in values:
            continue
        raw = values[key]
        entry = current[key]
        if key == "path":
            parsed = None
            text = (raw or "").strip()
            if entry["env_name"]:
                if text and text != entry["value"]:
                    errors[key] = f"Set by environment ({entry['env_name']}); it cannot be changed here."
                continue
            if text == entry["value"]:
                continue
            real, path_errors, path_warnings = validate_path(text)
            if path_errors:
                errors[key] = path_errors[0]
                continue
            parsed = real
            warnings.extend(path_warnings)
            if parsed == entry["value"]:
                continue
        elif key.endswith("_enabled"):
            parsed = _parse_bool(raw)
        elif key.endswith("_time"):
            parsed = (raw or "").strip()
            if not TIME_RE.match(parsed):
                errors[key] = "Use a time of day as HH:MM, 00:00 to 23:59."
                continue
        elif key.endswith("_keep_days"):
            text = str(raw).strip()
            try:
                parsed = int(text)
            except ValueError:
                parsed = None
            if parsed is None or not _valid_keep_days(parsed):
                errors[key] = "Keep days must be a whole number from 1 to 365."
                continue
            if entry["env_name"]:
                if parsed != entry["value"]:
                    errors[key] = f"Set by environment ({entry['env_name']}); it cannot be changed here."
                continue
        elif key == "export_format":
            parsed = (raw or "").strip().lower()
            if parsed not in ("yaml", "json"):
                errors[key] = "The format must be yaml or json."
                continue
        else:  # pragma: no cover - SETTING_KEYS is closed
            continue
        if parsed != entry["value"]:
            staged[key] = parsed

    if errors:
        return errors, []
    for key, value in staged.items():
        settings_store.set_backup_value(_STORE_KEYS[key], value)
    return {}, warnings


def reset(key):
    """Delete the DB row for `key` (the value falls back to settings.yml or the default).
    Caller commits. Returns False for an unknown key."""
    if key not in RESETTABLE_KEYS:
        return False
    settings_store.delete_backup_value(_STORE_KEYS[key])
    return True


# --- files ---------------------------------------------------------------------------------


def human_size(num):
    num = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{int(num)} B" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"  # pragma: no cover


def _kind_of(name):
    if name.endswith(SNAPSHOT_SUFFIX):
        return "snapshot"
    if name.endswith(EXPORT_SUFFIXES) or name in LEGACY_NAMES:
        return "export"
    return None


def _is_legacy(name):
    return name.endswith(LEGACY_SUFFIXES) or name in LEGACY_NAMES


def list_files(directory=None):
    """`{"snapshots": [...], "exports": [...]}`, newest first. Each item is `{name, kind,
    size, size_text, modified, manual, legacy}`. Raises OSError if the folder cannot be
    read (the caller shows an inline warning)."""
    directory = directory or backup_dir()
    out = {"snapshots": [], "exports": []}
    if not os.path.isdir(directory):
        return out
    for name in os.listdir(directory):
        kind = _kind_of(name)
        path = os.path.join(directory, name)
        if kind is None or not os.path.isfile(path):
            continue
        st = os.stat(path)
        out["snapshots" if kind == "snapshot" else "exports"].append({
            "name": name, "kind": kind, "size": st.st_size, "size_text": human_size(st.st_size),
            "modified": datetime.fromtimestamp(st.st_mtime), "manual": bool(_MANUAL_RE.match(name)),
            "legacy": _is_legacy(name),
        })
    for rows in out.values():
        rows.sort(key=lambda r: (r["modified"], r["name"]), reverse=True)
    return out


def resolve_file(name, directory=None, suffixes=None):
    """The real path of a backup file by bare name, or None. `name` must be a bare filename
    with a known suffix (or one of `suffixes`, which replaces the known list; the restore
    form passes `.yml` / `.yaml`), and its real path must be a file inside the folder."""
    if not name or not isinstance(name, str):
        return None
    if name != os.path.basename(name) or name in (".", "..") or "\x00" in name or "\\" in name:
        return None
    allowed = tuple(suffixes) if suffixes else KNOWN_SUFFIXES
    if not (name.endswith(allowed) or (not suffixes and name in LEGACY_NAMES)):
        return None
    root = os.path.realpath(directory or backup_dir())
    path = os.path.realpath(os.path.join(root, name))
    if not path.startswith(root + os.sep) or not os.path.isfile(path):
        return None
    return path


def prune(directory, kind, keep_days):
    """Delete files of `kind` whose mtime is older than `keep_days`. Never touches a file
    that matches no suffix of the kind. Returns the number removed."""
    cutoff = time.time() - keep_days * 86400
    suffixes = SUFFIXES_BY_KIND[kind]
    removed = 0
    for fname in os.listdir(directory):
        if not fname.endswith(suffixes):
            continue
        fpath = os.path.join(directory, fname)
        try:
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                os.remove(fpath)
                logger.info(f"🧹 Removed old backup: {fname}")
                removed += 1
        except OSError as e:
            logger.warning(f"⚠️ Could not remove old backup {fname}: {e}")
    if removed:
        logger.info(f"🧹 Removed {removed} expired {kind} file(s) from {directory}")
    return removed


# --- runs ----------------------------------------------------------------------------------


def _file_name(kind, trigger, now=None, fmt="yaml"):
    now = now or datetime.now()
    stamp = now.strftime("%Y-%m-%d") if trigger == "schedule" else now.strftime("%Y-%m-%d_%H%M%S")
    if kind == "snapshot":
        return stamp + SNAPSHOT_SUFFIX
    return stamp + ("-std_export.json" if fmt == "json" else "-std_export.yml")


def _write_sqlite_snapshot(path):
    """Consistent copy of the live database via sqlite3's online backup API (WAL-safe;
    never a file copy), through `<path>.tmp` and `os.replace`. Raises on failure and leaves
    no temp file."""
    tmp = path + ".tmp"
    src = dst = None
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
        raw = db.engine.raw_connection()
        try:
            src = raw.driver_connection
            dst = sqlite3.connect(tmp)
            src.backup(dst)
        finally:
            if dst is not None:
                dst.close()
            raw.close()
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _write_export(path, fmt):
    """The v1 export (`export_format`) through `<path>.tmp` and `os.replace`. Raises on
    failure and leaves no temp file."""
    tmp = path + ".tmp"
    try:
        data = export_format.dump(export_format.build_export(), fmt)
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        raise


def _record(kind, result):
    """Write `backup_last_runs[kind]` and commit (success and failure alike)."""
    try:
        runs = dict(settings_store.get_backup_last_runs())
        runs[kind] = result
        settings_store.set_backup_last_runs(runs)
        db.session.commit()
    except Exception:
        logger.exception("Could not record the %s backup result", kind)
        db.session.rollback()


def _run(app, kind, trigger):
    """One run of `kind`. Returns `{ok, file, size, error, at, trigger, busy}`; a run
    already in progress returns `busy: True` and records nothing."""
    lock = _RUN_LOCKS[kind]
    if not lock.acquire(blocking=False):
        return {"ok": False, "busy": True, "error": f"A {KIND_LABELS[kind]} is already running.",
                "file": None, "size": None, "trigger": trigger,
                "at": datetime.now().isoformat(timespec="seconds")}
    try:
        with app.app_context():
            now = datetime.now()
            result = {"at": now.isoformat(timespec="seconds"), "ok": False, "file": None,
                      "size": None, "size_text": None, "error": None, "trigger": trigger}
            try:
                eff = effective_settings(app)
                directory = eff["path"]["value"]
                os.makedirs(directory, exist_ok=True)
                fmt = eff["export"]["format"]["value"]
                name = _file_name(kind, trigger, now, fmt)
                path = os.path.join(directory, name)
                if kind == "snapshot":
                    _write_sqlite_snapshot(path)
                else:
                    _write_export(path, fmt)
                size = os.path.getsize(path)
                result.update(ok=True, file=name, size=size, size_text=human_size(size))
                logger.info(f"🌙 {trigger.capitalize()} {kind} saved to {path}")
                try:
                    prune(directory, kind, eff[kind]["keep_days"]["value"])
                except Exception:
                    logger.exception("Retention for %s backups failed", kind)
            except Exception as e:
                result["error"] = str(e) or e.__class__.__name__
                logger.error(f"❌ {trigger.capitalize()} {kind} failed: {e}")
            _record(kind, result)
            result["busy"] = False
            return result
    finally:
        lock.release()


def run_snapshot(app, trigger="manual"):
    return _run(app, "snapshot", trigger)


def run_export(app, trigger="manual"):
    return _run(app, "export", trigger)


def last_runs():
    """The recorded last run per kind (`{}` before any)."""
    return settings_store.get_backup_last_runs()


def attention_needed(runs=None):
    """True while either kind's last recorded run failed."""
    runs = runs if runs is not None else last_runs()
    return any(isinstance(r, dict) and r.get("ok") is False for r in runs.values())
