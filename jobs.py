"""Background jobs.

All APScheduler-driven background work plus the startup
verify-and-fetch-missing-icons sweep. Each function takes the Flask
`app` explicitly and pushes its own app context, so the factory in
app.py can wire them up without keeping a module-level `app`
reference here.

Public entry points:
- `start_background_workers(app)` — registers the APScheduler jobs
  (widget refresh, daily backup, widget_value retention prune, soft-delete
  purge) and
  starts the URL health-check thread. Called once, via app.run_startup_tasks(),
  after migrations.
- `verify_and_fetch_missing_icons(app)` — one-shot icon sweep run
  at startup.
"""

import importlib
import json
import logging
import os
import threading
import time
import warnings
from datetime import datetime, timedelta
from functools import partial

import requests
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from urllib3.exceptions import InsecureRequestWarning

from extensions import db
from image_utils import fetch_icon_if_missing
from models import (
    HealthResult,
    ServiceEntry,
    Widget,
    WidgetValue,
    ensure_url_checks,
    hard_delete_entry,
)
from settings_loader import CONFIG_DIR

logger = logging.getLogger(__name__)


def update_widget_data_periodically(app):
    with app.app_context():
        # Refresh only widgets with at least one active service. Skipped:
        # widgets whose services are all soft-deleted (Restore brings them
        # back intact) and detached widgets (no service references them).
        widgets = Widget.query.filter(
            Widget.services.any(ServiceEntry.deleted_at.is_(None))
        ).all()

        for widget in widgets:  # ✅ Now inside context
            print(f"🔄 Running widget fetch for: {widget.widget_name} ({widget.id})")
            try:
                widget_key = widget.widget_name  # 💡 Use widget_name, not widget_key
                widget_dir = os.path.join('widgets', widget_key)
                settings_path = os.path.join(widget_dir, 'settings.json')

                if not os.path.exists(settings_path):
                    print(f"⚠️ Missing settings.json for widget '{widget_key}'")
                    continue

                with open(settings_path, 'r') as f:
                    settings = json.load(f)

                available_fields = settings.get("available_fields", [])
                requested_fields = widget.widget_fields
                api_url = widget.widget_url
                api_key = widget.widget_api_key

                try:
                    module = importlib.import_module(f"widgets.{widget_key}.fetch_data")
                    fetch_func = module.fetch_widget_data
                    data = fetch_func(api_url, api_key, requested_fields, available_fields)
                except Exception as e:
                    print(f"❌ Failed to load widget fetcher for '{widget_key}': {e}")
                    continue

                if isinstance(data, dict) and "error" in data:
                    print(f"❌ Error fetching data for widget {widget.id}: {data['error']}")
                    continue

                for key, value in data.items():
                    widget_value = WidgetValue.query.filter_by(widget_id=widget.id, widget_value_key=key).first()

                    if not widget_value:
                        widget_value = WidgetValue(
                            widget_id=widget.id,
                            widget_value_key=key,
                            widget_value=str(value),
                            last_updated=datetime.utcnow()
                        )
                        db.session.add(widget_value)
                    else:
                        widget_value.widget_value = str(value)
                        widget_value.last_updated = datetime.utcnow()

                db.session.commit()
                print(f"✅ Updated values for widget {widget_key} (ID: {widget.id})")

            except Exception as e:
                print(f"🔥 Exception while processing widget {widget.id}: {str(e)}")


DEFAULT_HEALTH_CHECK_TIMEOUT = 5


def _global_health_timeout(app):
    try:
        value = int(app.config.get("health_check_timeout", DEFAULT_HEALTH_CHECK_TIMEOUT))
    except (TypeError, ValueError):
        return DEFAULT_HEALTH_CHECK_TIMEOUT
    return value if value > 0 else DEFAULT_HEALTH_CHECK_TIMEOUT


def probe_url(url, check, default_timeout=DEFAULT_HEALTH_CHECK_TIMEOUT):
    """Run one URL health check and return its outcome as a dict.

    Timeout is the check's own `timeout_seconds` when set, else
    `default_timeout` (the global setting). `verify` follows the check's
    `verify_tls`; when it is off, urllib3's InsecureRequestWarning is
    silenced for this call only.

    Keys: ok (status < 400), status_code (int or None), latency_ms (int),
    message (None when ok, else the status string), status (the legacy
    string: "200" or "Error: <ExceptionName>").
    """
    timeout = check.timeout_seconds or default_timeout
    verify = check.verify_tls is not False
    started = time.monotonic()
    try:
        with warnings.catch_warnings():
            if not verify:
                warnings.simplefilter("ignore", InsecureRequestWarning)
            response = requests.get(url, timeout=timeout, verify=verify)
        latency_ms = int((time.monotonic() - started) * 1000)
        code = int(response.status_code)
        ok = code < 400
        return {
            "ok": ok,
            "status_code": code,
            "latency_ms": latency_ms,
            "message": None if ok else str(code),
            "status": str(code),
        }
    except Exception as e:
        latency_ms = int((time.monotonic() - started) * 1000)
        status = f"Error: {type(e).__name__}"
        return {
            "ok": False,
            "status_code": None,
            "latency_ms": latency_ms,
            "message": status,
            "status": status,
        }


def record_check_result(check, outcome, now_utc=None):
    """Store `outcome` (from probe_url) as a HealthResult and update the
    check's cached `last_*` state. Caller commits."""
    now_utc = now_utc or datetime.utcnow()
    db.session.add(HealthResult(
        check_id=check.id,
        ts=now_utc,
        ok=outcome["ok"],
        latency_ms=outcome["latency_ms"],
        latency_max_ms=outcome["latency_ms"],
        status_code=outcome["status_code"],
        message=outcome["message"],
    ))
    check.last_ok = outcome["ok"]
    check.last_checked_at = now_utc
    check.last_status_code = outcome["status_code"]
    check.last_latency_ms = outcome["latency_ms"]
    check.last_message = outcome["message"]
    check.consecutive_failures = 0 if outcome["ok"] else (check.consecutive_failures or 0) + 1


def run_url_checks_once(app):
    """One sequential pass over every enabled URL-kind check of active
    entries. Interim implementation: v070-03 replaces it with the concurrent
    scheduler. Returns the number of checks run."""
    default_timeout = _global_health_timeout(app)
    ran = 0
    entries = ServiceEntry.active().all()
    for entry in entries:
        ensure_url_checks(entry)
        for which, url_attr in (("internal", "internalurl"), ("external", "externalurl")):
            check = entry.url_check(which)
            url = getattr(entry, url_attr)
            if not (check and check.enabled and url):
                continue
            if check.id is None:
                db.session.flush()
            outcome = probe_url(url, check, default_timeout)
            record_check_result(check, outcome)
            # TEMP: removed in v070-05 (templates still read the legacy status columns)
            setattr(entry, f"{which}_health_check_status", outcome["status"])
            setattr(entry, f"{which}_health_check_update", datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            ran += 1
            logger.info(f"{entry.container_name} - {which}: {outcome['status']}")
    db.session.commit()
    return ran


# Background health check loop
def health_check_loop(app):
    URL_HEALTHCHECK_INTERVAL = app.config.get("url_healthcheck_interval", 60)

    with app.app_context():
        iteration = 0
        while True:
            time.sleep(URL_HEALTHCHECK_INTERVAL)
            iteration += 1
            try:
                logger.info("\U0001f504 Running URL health checks...")
                run_url_checks_once(app)
            except Exception:
                # Safety net: keep the worker thread alive across unexpected
                # failures (DB errors, surprise requests exceptions, etc.).
                logger.exception("Health-check iteration %d failed; continuing.", iteration)
                try:
                    db.session.rollback()
                except Exception:
                    logger.exception("Failed to roll back session after health-check error")


def run_scheduled_backup(app):
    with app.app_context():
        backup_dir = app.config.get("backup_path", os.path.join(CONFIG_DIR, "backups"))
        days_to_keep = int(app.config.get("backup_days_to_keep", 7))

        os.makedirs(backup_dir, exist_ok=True)

        filename = datetime.now().strftime("%Y-%m-%d-std_backup.yml")
        full_path = os.path.join(backup_dir, filename)

        try:
            # All rows, soft-deleted included: the backup carries deleted_at.
            entries = ServiceEntry.query.all()
            data = [e.to_dict() for e in entries]
            with open(full_path, 'w') as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            logger.info(f"🌙 Scheduled backup saved to {full_path}")
        except Exception as e:
            logger.error(f"❌ Scheduled backup failed: {e}")

        # Cleanup
        now = time.time()
        cutoff = now - (days_to_keep * 86400)
        removed = 0
        for fname in os.listdir(backup_dir):
            if fname.endswith("-std_backup.yml"):
                fpath = os.path.join(backup_dir, fname)
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    try:
                        os.remove(fpath)
                        logger.info(f"🧹 Removed old backup: {fname}")
                        removed += 1
                    except Exception as e:
                        logger.warning(f"⚠️ Could not remove old backup {fname}: {e}")
        if removed:
            logger.info(f"🧹 Removed {removed} expired backup(s) from {backup_dir}")


def prune_widget_values(app):
    """Delete widget_value rows whose last_updated is older than the
    configured retention window.

    The widget refresh loop upserts in place — one row per
    (widget_id, widget_value_key) — so old `last_updated` timestamps
    mean the key has been abandoned (widget configuration removed the
    field). Pruning keeps the table from growing unbounded.

    Wrapped in try/except so a transient DB error never kills the
    scheduler. Follows the same pattern Phase 7a applied to the URL
    health-check loop.
    """
    with app.app_context():
        try:
            retention_days = int(app.config.get("widget_value_retention_days", 30))
            cutoff = datetime.utcnow() - timedelta(days=retention_days)
            deleted = (
                WidgetValue.query
                .filter(WidgetValue.last_updated < cutoff)
                .delete(synchronize_session=False)
            )
            db.session.commit()
            logger.info(
                f"🧹 Pruned {deleted} widget_value row(s) older than "
                f"{retention_days} days (cutoff: {cutoff.isoformat()})."
            )
        except Exception:
            logger.exception("Widget value retention prune failed; rolling back.")
            try:
                db.session.rollback()
            except Exception:
                logger.exception("Failed to roll back session after prune error")


def purge_deleted_entries(app):
    """Hard-delete soft-deleted entries older than deleted_retention_days.

    0 purges every soft-deleted entry at the next run. Each purge goes
    through `hard_delete_entry`. Wrapped in try/except so a transient DB
    error never kills the scheduler.
    """
    with app.app_context():
        try:
            retention_days = int(app.config.get("deleted_retention_days", 30))
            cutoff = datetime.now() - timedelta(days=retention_days)
            expired = (
                ServiceEntry.query
                .filter(ServiceEntry.deleted_at.isnot(None))
                .filter(ServiceEntry.deleted_at <= cutoff)
                .all()
            )
            for entry in expired:
                hard_delete_entry(entry)
            db.session.commit()
            logger.info(
                f"🧹 Purged {len(expired)} soft-deleted service(s) older than "
                f"{retention_days} days (cutoff: {cutoff.isoformat()})."
            )
        except Exception:
            logger.exception("Soft-delete purge failed; rolling back.")
            try:
                db.session.rollback()
            except Exception:
                logger.exception("Failed to roll back session after purge error")


# Check images at startup
def verify_and_fetch_missing_icons(app):
    image_dir = app.config['IMAGE_DIR']
    logger.info("🔍 Verifying icon files for all ServiceEntry records...")
    with app.app_context():
        entries = ServiceEntry.active().all()
        missing_count = 0
        for entry in entries:
            icon = entry.image_icon
            if icon:
                icon_path = os.path.join(image_dir, icon)
                if not os.path.exists(icon_path):
                    logger.warning(f"🚫 Missing icon: {icon} — attempting download...")
                    fetched = fetch_icon_if_missing(icon, image_dir, logger, debug=app.debug)
                    if fetched:
                        logger.info(f"✅ Successfully fetched missing icon: {fetched}")
                    else:
                        logger.error(f"❌ Failed to download icon: {icon}")
                        missing_count += 1
        logger.info(f"🔁 Icon verification complete. Missing count: {missing_count}")


def start_background_workers(app):
    scheduler = BackgroundScheduler()
    reload_seconds = app.config.get("widget_background_reload")
    if not isinstance(reload_seconds, int) or reload_seconds <= 0:
        reload_seconds = 300  # default fallback
    scheduler.add_job(
        partial(update_widget_data_periodically, app),
        IntervalTrigger(seconds=reload_seconds),
        id='widget_data_update_job',
        name='Update widget values periodically',
        replace_existing=True
    )
    scheduler.add_job(
        partial(run_scheduled_backup, app),
        CronTrigger(hour=0, minute=5),
        id='scheduled_backup_job',
        name='Run daily backup',
        replace_existing=True
    )
    scheduler.add_job(
        partial(prune_widget_values, app),
        CronTrigger(hour=0, minute=15),
        id='widget_value_prune_job',
        name='Prune widget_value rows past retention window',
        replace_existing=True
    )
    scheduler.add_job(
        partial(purge_deleted_entries, app),
        CronTrigger(hour=0, minute=25),
        id='deleted_entry_purge_job',
        name='Purge soft-deleted entries past retention window',
        replace_existing=True
    )
    scheduler.start()

    threading.Thread(target=partial(health_check_loop, app), daemon=True).start()
