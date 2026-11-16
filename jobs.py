"""Background jobs.

All APScheduler-driven background work plus the startup
verify-and-fetch-missing-icons sweep. Each function takes the Flask
`app` explicitly and pushes its own app context, so the factory in
app.py can wire them up without keeping a module-level `app`
reference here.

Public entry points:
- `start_background_workers(app)` — registers the APScheduler jobs
  (widget refresh, daily backup, widget_value retention prune, soft-delete
  purge, daily API audit purge, hourly health-history purge and compaction) and starts the
  concurrent health-check scheduler thread (probes live in checker.py). Called once, via app.run_startup_tasks(),
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
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from functools import partial

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import func

import checker
from extensions import db
from image_utils import fetch_icon_if_missing
from models import (
    CHECK_KIND_CONTAINER,
    CHECK_KIND_EXTERNAL,
    CHECK_KIND_INTERNAL,
    ApiAudit,
    HealthCheck,
    HealthResult,
    ServiceEntry,
    Widget,
    WidgetValue,
    check_counts,
    ensure_container_check,
    ensure_url_checks,
    evaluate_container,
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
DEFAULT_HEALTH_WORKERS = 8
DEFAULT_HEALTH_RAW_HOURS = 24
DEFAULT_HEALTH_HISTORY_DAYS = 7
DEFAULT_API_AUDIT_RETENTION_DAYS = 90
DEFAULT_URL_INTERVAL = 300
MIN_CHECK_INTERVAL = 30
TICK_SECONDS = 5
PURGE_BATCH = 2000


def _int_setting(app, key, default, minimum=1):
    """A positive-int setting from app.config, falling back to `default`."""
    try:
        value = int(app.config.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if value >= minimum else default


def _global_health_timeout(app):
    return _int_setting(app, "health_check_timeout", DEFAULT_HEALTH_CHECK_TIMEOUT)


def record_check_result(check, result, now_utc=None):
    """Store `result` (a checker.ProbeResult) as a HealthResult and update
    the check's cached `last_*` state. Scheduler thread only. Caller commits."""
    now_utc = now_utc or datetime.utcnow()
    db.session.add(HealthResult(
        check_id=check.id,
        ts=now_utc,
        ok=result.ok,
        latency_ms=result.latency_ms,
        latency_max_ms=result.latency_ms,
        status_code=result.status_code,
        message=result.message,
    ))
    check.last_ok = result.ok
    check.last_checked_at = now_utc
    check.last_status_code = result.status_code
    check.last_latency_ms = result.latency_ms
    check.last_message = result.message
    check.consecutive_failures = 0 if result.ok else (check.consecutive_failures or 0) + 1


def _check_interval(check, global_interval):
    if check.interval_seconds:
        return max(MIN_CHECK_INTERVAL, int(check.interval_seconds))
    return global_interval


# Check now: ids asked to run at the next tick regardless of their interval.
# In-process only, which is fine: gunicorn runs exactly one worker and the
# scheduler lives in it. Using a set (not clearing last_checked_at) keeps the
# last result visible while the requested run is pending.
_run_requests = set()
_run_requests_lock = threading.Lock()


def request_run(check_ids):
    """Mark checks to run at the next scheduler tick (Check now)."""
    with _run_requests_lock:
        _run_requests.update(check_ids)


def _pending_run_requests():
    with _run_requests_lock:
        return set(_run_requests)


def _clear_run_requests(check_ids):
    with _run_requests_lock:
        _run_requests.difference_update(check_ids)


def select_due_jobs(app, now_utc=None, skip_ids=()):
    """Plain-dict descriptions of the checks that are due, for the pool.

    Due = enabled, entry active, a target to probe (URL-kind: the entry's
    current URL; service: its own target) and `last_checked_at IS NULL or
    last_checked_at + interval <= now`. Rows missing for an entry get
    created first (ensure_url_checks / ensure_container_check). Container
    checks are never returned: they are a DB read, evaluated on the
    scheduler thread by `run_container_checks`. Reads only; returns no ORM
    objects so the workers never touch a session.
    """
    now_utc = now_utc or datetime.utcnow()
    global_interval = _int_setting(app, "url_healthcheck_interval", DEFAULT_URL_INTERVAL)
    default_timeout = _global_health_timeout(app)
    jobs_due = []
    requested = _pending_run_requests()
    added = False
    for entry in ServiceEntry.active().all():
        before = len(entry.checks)
        ensure_url_checks(entry)
        ensure_container_check(entry)
        if len(entry.checks) != before:
            added = True
    if added:
        db.session.commit()
    checks = (
        HealthCheck.query.join(ServiceEntry, HealthCheck.service_entry_id == ServiceEntry.id)
        .filter(HealthCheck.enabled.is_(True), ServiceEntry.deleted_at.is_(None))
        .all()
    )
    for check in checks:
        if check.id in skip_ids:
            continue
        entry = check.service_entry
        if check.kind == CHECK_KIND_CONTAINER or not check_counts(entry, check):
            continue
        if check.kind == CHECK_KIND_INTERNAL:
            target = entry.internalurl
        elif check.kind == CHECK_KIND_EXTERNAL:
            target = entry.externalurl
        else:
            target = check.target
        target = target.strip()
        interval = _check_interval(check, global_interval)
        if (
            check.id not in requested
            and check.last_checked_at is not None
            and check.last_checked_at + timedelta(seconds=interval) > now_utc
        ):
            continue
        jobs_due.append({
            "check_id": check.id,
            "check_type": check.check_type,
            "target": target,
            "mode": check.mode,
            "timeout": check.timeout_seconds or default_timeout,
            "verify": check.verify_tls is not False,
        })
    return jobs_due


def run_container_checks(app, now_utc=None, now_local=None):
    """Evaluate every due Container check and record the results.

    Runs on the scheduler thread, inline: the evaluation is a read of the
    entry's docker_status / last_api_update, so there is no network and no
    pool submission. Due like any check (interval, or a pending run request
    from a register that changed the status). Locked, manual and soft-deleted
    entries are skipped. Returns the number of results written.
    """
    now_utc = now_utc or datetime.utcnow()
    global_interval = _int_setting(app, "url_healthcheck_interval", DEFAULT_URL_INTERVAL)
    requested = _pending_run_requests()
    checks = (
        HealthCheck.query.join(ServiceEntry, HealthCheck.service_entry_id == ServiceEntry.id)
        .filter(
            HealthCheck.kind == CHECK_KIND_CONTAINER,
            HealthCheck.enabled.is_(True),
            ServiceEntry.deleted_at.is_(None),
        )
        .all()
    )
    written = 0
    ran = []
    for check in checks:
        entry = check.service_entry
        if not check_counts(entry, check):
            continue
        interval = _check_interval(check, global_interval)
        if (
            check.id not in requested
            and check.last_checked_at is not None
            and check.last_checked_at + timedelta(seconds=interval) > now_utc
        ):
            continue
        ok, message = evaluate_container(entry, now_local)
        record_check_result(check, checker.ProbeResult(ok=ok, latency_ms=None, message=message), now_utc)
        ran.append(check.id)
        written += 1
    if written:
        db.session.commit()
    _clear_run_requests(ran)
    return written


def _run_job(job):
    """Pool worker: network I/O only. Takes a plain dict, returns
    (check_id, ProbeResult); never touches the database."""
    return job["check_id"], checker.run_probe(job)


class HealthScheduler:
    """Finds due checks, runs them on a thread pool, writes the results.

    `tick()` is meant to be called from ONE thread (the health-check
    thread): it collects finished futures and performs every DB write, then
    submits newly due checks. `in_flight` stops a slow check from being
    submitted twice.
    """

    def __init__(self, app, executor=None):
        self.app = app
        workers = _int_setting(app, "health_check_workers", DEFAULT_HEALTH_WORKERS)
        self.executor = executor or ThreadPoolExecutor(max_workers=workers, thread_name_prefix="health-check")
        self.in_flight = {}  # check_id -> Future

    def collect(self):
        """Write the results of every finished future. Returns the count."""
        written = 0
        for check_id, future in list(self.in_flight.items()):
            if not future.done():
                continue
            del self.in_flight[check_id]
            try:
                _, result = future.result()
            except Exception:
                logger.exception("Health check %s worker failed", check_id)
                continue
            check = db.session.get(HealthCheck, check_id)
            if check is None:  # deleted while in flight
                continue
            record_check_result(check, result)
            entry = check.service_entry
            logger.info("%s - %s: %s", entry.container_name if entry else "?", check.kind,
                        "ok" if result.ok else f"failing ({result.message})")
            written += 1
        if written:
            db.session.commit()
        return written

    def submit_due(self, now_utc=None):
        due = select_due_jobs(self.app, now_utc, skip_ids=set(self.in_flight))
        for job in due:
            self.in_flight[job["check_id"]] = self.executor.submit(_run_job, job)
        _clear_run_requests(job["check_id"] for job in due)
        return len(due)

    def tick(self, now_utc=None):
        """One scheduler pass inside its own app context. Returns
        (results_written, checks_submitted)."""
        with self.app.app_context():
            try:
                written = self.collect()
                submitted = self.submit_due(now_utc)
                written += run_container_checks(self.app, now_utc)
            except Exception:
                db.session.rollback()
                raise
            return written, submitted

    def shutdown(self):
        self.executor.shutdown(wait=False, cancel_futures=True)


def health_check_loop(app, stop_event=None, scheduler=None):
    """Background thread body: tick every TICK_SECONDS until `stop_event`."""
    scheduler = scheduler or HealthScheduler(app)
    stop_event = stop_event or threading.Event()
    iteration = 0
    while not stop_event.is_set():
        iteration += 1
        try:
            scheduler.tick()
        except Exception:
            # Safety net: keep the worker thread alive across unexpected
            # failures (DB errors, surprise probe exceptions, etc.).
            logger.exception("Health-check iteration %d failed; continuing.", iteration)
        stop_event.wait(TICK_SECONDS)
    scheduler.shutdown()


def compact_health_results(app, now_utc=None):
    """Merge old raw successes into hourly range rows (PRD 13.4).

    Per check and clock hour that lies wholly before `health_raw_hours` ago,
    each unbroken run of raw ok rows becomes one row: `ts` = first sample,
    `ts_end` = last, `samples` = count, average and maximum latency.
    Failures are untouched and split runs. One (check, hour) per commit so
    the write lock is never held for long. Returns the rows removed.
    """
    now_utc = now_utc or datetime.utcnow()
    raw_hours = _int_setting(app, "health_raw_hours", DEFAULT_HEALTH_RAW_HOURS)
    cutoff = (now_utc - timedelta(hours=raw_hours)).replace(minute=0, second=0, microsecond=0)
    removed = 0
    with app.app_context():
        check_ids = [
            row[0] for row in db.session.query(HealthResult.check_id)
            .filter(HealthResult.ok.is_(True), HealthResult.ts_end.is_(None), HealthResult.ts < cutoff)
            .distinct().all()
        ]
        for check_id in check_ids:
            while True:
                first = (
                    HealthResult.query
                    .filter(HealthResult.check_id == check_id, HealthResult.ok.is_(True),
                            HealthResult.ts_end.is_(None), HealthResult.ts < cutoff)
                    .order_by(HealthResult.ts).first()
                )
                if first is None:
                    break
                hour_start = first.ts.replace(minute=0, second=0, microsecond=0)
                rows = (
                    HealthResult.query
                    .filter(HealthResult.check_id == check_id, HealthResult.ts >= hour_start,
                            HealthResult.ts < hour_start + timedelta(hours=1))
                    .order_by(HealthResult.ts, HealthResult.id).all()
                )
                removed += _compact_rows(rows)
                db.session.commit()
    if removed:
        logger.info("Health history compaction merged away %d rows", removed)
    return removed


def _compact_rows(rows):
    """Compact the unbroken runs of raw ok rows inside one (check, hour).
    Returns the number of rows deleted."""
    removed = 0
    run = []

    def flush():
        nonlocal removed
        if run:
            removed += _merge_run(run)
        run.clear()

    for row in rows:
        if row.ok and row.ts_end is None:
            run.append(row)
        else:
            flush()
    flush()
    return removed


def _merge_run(run):
    head = run[0]
    total = sum(r.samples or 1 for r in run)
    weighted = sum((r.latency_ms or 0) * (r.samples or 1) for r in run if r.latency_ms is not None)
    counted = sum((r.samples or 1) for r in run if r.latency_ms is not None)
    maxima = [r.latency_max_ms if r.latency_max_ms is not None else r.latency_ms
              for r in run if (r.latency_max_ms is not None or r.latency_ms is not None)]
    head.ts_end = run[-1].ts
    head.samples = total
    head.latency_ms = (weighted / counted) if counted else None
    head.latency_max_ms = int(max(maxima)) if maxima else None
    head.status_code = None
    head.message = None
    for r in run[1:]:
        db.session.delete(r)
    return len(run) - 1


def purge_health_results(app, now_utc=None):
    """Delete health results older than `health_history_days`, in batches.
    A compacted range counts as old once its `ts_end` is. Returns rows deleted."""
    now_utc = now_utc or datetime.utcnow()
    days = _int_setting(app, "health_history_days", DEFAULT_HEALTH_HISTORY_DAYS)
    cutoff = now_utc - timedelta(days=days)
    deleted = 0
    with app.app_context():
        while True:
            ids = [
                row[0] for row in db.session.query(HealthResult.id)
                .filter(func.coalesce(HealthResult.ts_end, HealthResult.ts) < cutoff)
                .limit(PURGE_BATCH).all()
            ]
            if not ids:
                break
            HealthResult.query.filter(HealthResult.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            deleted += len(ids)
    if deleted:
        logger.info("Purged %d health results older than %d days", deleted, days)
    return deleted


def purge_api_audit(app, now_utc=None):
    """Delete management-API audit rows older than `api_audit_retention_days`
    (default 90), in batches. Returns rows deleted."""
    now_utc = now_utc or datetime.utcnow()
    days = _int_setting(app, "api_audit_retention_days", DEFAULT_API_AUDIT_RETENTION_DAYS)
    cutoff = now_utc - timedelta(days=days)
    deleted = 0
    with app.app_context():
        try:
            while True:
                ids = [
                    row[0] for row in db.session.query(ApiAudit.id)
                    .filter(ApiAudit.ts < cutoff).limit(PURGE_BATCH).all()
                ]
                if not ids:
                    break
                ApiAudit.query.filter(ApiAudit.id.in_(ids)).delete(synchronize_session=False)
                db.session.commit()
                deleted += len(ids)
        except Exception:
            logger.exception("API audit purge failed; rolling back.")
            db.session.rollback()
    if deleted:
        logger.info("Purged %d API audit rows older than %d days", deleted, days)
    return deleted


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
    scheduler.add_job(
        partial(purge_api_audit, app),
        CronTrigger(hour=0, minute=35),
        id='api_audit_purge_job',
        name='Purge API audit rows past the retention window',
        replace_existing=True
    )
    scheduler.add_job(
        partial(purge_health_results, app),
        CronTrigger(minute=3),
        id='health_result_purge_job',
        name='Purge health results past the history window',
        replace_existing=True
    )
    scheduler.add_job(
        partial(compact_health_results, app),
        CronTrigger(minute=5),
        id='health_result_compaction_job',
        name='Compact old raw health successes into hourly ranges',
        replace_existing=True
    )
    scheduler.start()

    threading.Thread(target=partial(health_check_loop, app), daemon=True, name="health-check-loop").start()
