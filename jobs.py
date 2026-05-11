"""Background jobs.

All APScheduler-driven background work plus the startup
verify-and-fetch-missing-icons sweep. Each function takes the Flask
`app` explicitly and pushes its own app context, so the factory in
app.py can wire them up without keeping a module-level `app`
reference here.

Public entry points:
- `start_background_workers(app)` — registers the APScheduler jobs
  (widget refresh, daily backup) and starts the URL health-check
  thread. Called once from the __main__ block after migrations.
- `verify_and_fetch_missing_icons(app)` — one-shot icon sweep run
  at startup.

Phase 3 (a later phase) will add the widget_value retention job to
this file.
"""

import importlib
import json
import logging
import os
import threading
import time
from datetime import datetime
from functools import partial

import requests
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from extensions import db
from image_utils import fetch_icon_if_missing
from models import ServiceEntry, Widget, WidgetValue

logger = logging.getLogger(__name__)


def update_widget_data_periodically(app):
    with app.app_context():
        widgets = Widget.query.all()

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
                    fetch_func = getattr(module, "fetch_widget_data")
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


# Background health check loop
def health_check_loop(app):
    URL_HEALTHCHECK_INTERVAL = app.config.get("url_healthcheck_interval", 60)

    with app.app_context():
        iteration = 0
        while True:
            time.sleep(URL_HEALTHCHECK_INTERVAL)
            iteration += 1
            try:
                log_output = ["\U0001f504 Running internal health checks..."]
                entries = ServiceEntry.query.all()

                for entry in entries:
                    show_log = False
                    internal_status = ""
                    external_status = ""

                    if entry.internal_health_check_enabled and entry.internalurl:
                        show_log = True
                        try:
                            response = requests.get(entry.internalurl, timeout=5)
                            internal_status = str(response.status_code)
                            entry.internal_health_check_status = internal_status
                        except Exception as e:
                            internal_status = f"Error: {type(e).__name__}"
                            entry.internal_health_check_status = internal_status
                        entry.internal_health_check_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    if entry.external_health_check_enabled and entry.externalurl:
                        show_log = True
                        try:
                            response = requests.get(entry.externalurl, timeout=5)
                            external_status = str(response.status_code)
                            entry.external_health_check_status = external_status
                        except Exception as e:
                            external_status = f"Error: {type(e).__name__}"
                            entry.external_health_check_status = external_status
                        entry.external_health_check_update = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                    if show_log:
                        log_output.append(f"{entry.container_name} - Internal: {internal_status or 'N/A'} External: {external_status or 'N/A'}")

                db.session.commit()
                for line in log_output:
                    logger.info(line)
            except Exception:
                # Safety net: keep the worker thread alive across unexpected
                # failures (DB errors, surprise requests exceptions, etc.).
                service_count = len(entries) if "entries" in locals() else -1
                logger.exception(
                    "Health-check iteration %d failed (services=%d); continuing.",
                    iteration,
                    service_count,
                )
                try:
                    db.session.rollback()
                except Exception:
                    logger.exception("Failed to roll back session after health-check error")


def run_scheduled_backup(app):
    with app.app_context():
        backup_dir = app.config.get("backup_path", "/config/backups")
        days_to_keep = int(app.config.get("backup_days_to_keep", 7))

        os.makedirs(backup_dir, exist_ok=True)

        filename = datetime.now().strftime("%Y-%m-%d-std_backup.yml")
        full_path = os.path.join(backup_dir, filename)

        try:
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


# Check images at startup
def verify_and_fetch_missing_icons(app):
    image_dir = app.config['IMAGE_DIR']
    logger.info("🔍 Verifying icon files for all ServiceEntry records...")
    with app.app_context():
        entries = ServiceEntry.query.all()
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
    scheduler.start()

    threading.Thread(target=partial(health_check_loop, app), daemon=True).start()
