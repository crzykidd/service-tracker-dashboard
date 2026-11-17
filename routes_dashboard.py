"""Dashboard, settings, and CRUD routes.

Owns the `dashboard` blueprint:
- Read-only dashboard views: /, /tiled_dash, /compact_dash
- Settings page: /settings (backup/restore, users list, groups, version)
- Groups: /settings/groups/save (one Save for the whole table)
- Service CRUD: /add, /edit/<id>, /dbdump
- Static assets: /images/<filename>

Grouping/sorting for the three dashboard views lives in
`view_helpers.group_and_sort_services`. The view controls
(`group_by` axis selector, `show_urlless` filter) are URL-driven
(`?group_by=stack&show_urlless=false`); each route here just parses
the query params and hands them to the helper.
"""

import json
import logging
import math
import os
import re
from datetime import datetime, timedelta

import markdown as _md
import requests
import yaml
from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    session,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from sqlalchemy.orm import joinedload, selectinload

import api_keys
import check_form
import entry_rules
import health_history
import jobs
import settings_store
import synthesizer
import version_check
from extensions import db
from image_utils import fetch_icon_if_missing, icon_path_in_dir, safe_icon_filename
from models import (
    CHECK_KIND_CONTAINER,
    CHECK_KIND_SERVICE,
    CHECK_MODES,
    CHECK_TYPE_DNS,
    CHECK_TYPE_HTTP,
    CHECK_TYPES,
    SOURCE_MANUAL,
    SOURCE_NOTIFIER,
    URL_CHECK_KINDS,
    VALID_SOURCES,
    ApiAudit,
    ApiKey,
    Group,
    HealthCheck,
    ServiceEntry,
    User,
    Widget,
    WidgetValue,
    check_counts,
    ensure_container_check,
    ensure_url_checks,
    hard_delete_entry,
)
from routes_auth import is_admin_required
from settings_loader import CONFIG_DIR
from view_helpers import (
    DEFAULT_SORT_IN_GROUP,
    group_and_sort_services,
    health_counts,
    host_label_ids,
    normalize_axis,
    normalize_show_urlless,
    normalize_source_filter,
    normalize_status_filter,
    safe_redirect_target,
)

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

# Module-level cache for parsed changelog sections. CHANGELOG.md is baked into
# the image at build time and never changes at runtime, so parse once on first
# request and reuse.
_changelog_cache = None
_CHANGELOG_SECTION_RE = re.compile(
    r'^## \[(\d+\.\d+\.\d+)\] — (\d{4}-\d{2}-\d{2})',
    re.MULTILINE,
)


def _parse_version(s):
    try:
        return tuple(int(x) for x in s.split('.'))
    except (ValueError, AttributeError):
        return None


def _get_changelog_sections():
    global _changelog_cache
    if _changelog_cache is not None:
        return _changelog_cache

    try:
        # CHANGELOG.md is at the same directory as this file in both the
        # container (COPY . . puts everything under /app) and local dev.
        changelog_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'CHANGELOG.md')
        if not os.path.exists(changelog_path):
            _changelog_cache = []
            return _changelog_cache
        with open(changelog_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        _changelog_cache = []
        return _changelog_cache

    matches = list(_CHANGELOG_SECTION_RE.finditer(content))
    sections = []
    for i, match in enumerate(matches):
        version = match.group(1)
        date = match.group(2)
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        body = content[body_start:body_end].strip()
        sections.append({
            'version': version,
            'date': date,
            'html': _md.markdown(body),
        })

    _changelog_cache = sections
    return _changelog_cache


# Helper to check if flash messages are already present (to avoid duplicates)
# This is a basic check; Flask's get_flashed_messages usually clears them.
def flash_is_present(req):
    return '_flashes' in req.environ.get('flask._flashes', [])


def _retention_days():
    try:
        return max(0, int(current_app.config.get("deleted_retention_days", 30)))
    except (TypeError, ValueError):
        return 30


def _restore_hint():
    days = _retention_days()
    return (
        f"It can be restored from Settings → Deleted for {days} "
        f"day{'' if days == 1 else 's'}."
    )


def _parse_backup_datetime(value):
    """Parse a backup timestamp ('%Y-%m-%d %H:%M:%S' or a YAML datetime)."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value), '%Y-%m-%d %H:%M:%S')
    except ValueError:
        logger.warning(f"Ignoring unparseable deleted_at in backup: {value!r}")
        return None


def _detached_widget_rows():
    """Detached widgets with their newest value timestamp."""
    rows = []
    for w in Widget.detached().order_by(Widget.widget_name.asc(), Widget.id.asc()).all():
        last = db.session.query(func.max(WidgetValue.last_updated)).filter(
            WidgetValue.widget_id == w.id
        ).scalar()
        rows.append({'widget': w, 'last_value': last})
    return rows


def _deleted_entry_rows():
    """Soft-deleted entries with the days left before the purge job runs."""
    retention = timedelta(days=_retention_days())
    now = datetime.now()
    rows = []
    for e in ServiceEntry.deleted().all():
        remaining = (e.deleted_at + retention - now).total_seconds() / 86400
        rows.append({'entry': e, 'days_left': max(0, math.ceil(remaining))})
    return rows


def _load_widget_values():
    widget_values = {}
    for wv in WidgetValue.query.all():
        widget_values.setdefault(wv.widget_id, {})[wv.widget_value_key] = wv.widget_value
    widget_fields = {w.id: w.widget_fields for w in Widget.query.all()}
    return widget_values, widget_fields


def _read_view_controls(default_sort_in_group=DEFAULT_SORT_IN_GROUP):
    axis = normalize_axis(request.args.get("group_by"), logger=logger)
    show_urlless = normalize_show_urlless(request.args.get("show_urlless"))
    sort_in_group = request.args.get("sort_in_group", default_sort_in_group)
    return axis, show_urlless, sort_in_group


def _read_filters():
    """The status/source filters (PRD 13.6), normalized to known values."""
    return (
        normalize_status_filter(request.args.get("status")),
        normalize_source_filter(request.args.get("source")),
    )


def _health_count_context(entries, show_urlless, source, status):
    """Counts and server-built chip links for the filter bar. Each link
    keeps every other current query param and swaps only `status`."""
    counts = health_counts(entries, show_urlless=show_urlless, source=source)
    base = request.args.to_dict()
    links = {}
    for key, value in (("total", "all"), ("passing", "healthy"), ("failing", "failing")):
        links[key] = url_for(request.endpoint, **{**base, "status": value})
    active = {"all": "total", "healthy": "passing", "failing": "failing"}.get(status)
    return {"health_counts": counts, "health_links": links, "health_active": active}


def _load_view_entries():
    """Active entries for a dashboard view, with everything the templates
    touch eager-loaded so the page costs a fixed number of queries."""
    return (
        ServiceEntry.active()
        .options(joinedload(ServiceEntry.group))
        .options(selectinload(ServiceEntry.exposures))
        .options(selectinload(ServiceEntry.checks))
        .all()
    )


def _host_label_ids(entries):
    """Entry ids that show a host, per `tile_show_host`. `entries` is every
    active entry (unfiltered) so a filter can't hide a duplicate."""
    return host_label_ids(entries, current_app.config.get('tile_show_host', 'duplicates'))


@dashboard_bp.route('/')
@login_required
def dashboard():
    axis, show_urlless, sort_in_group = _read_view_controls()
    msg = request.args.get('msg')

    entries = _load_view_entries()
    status, source = _read_filters()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
    )

    visible_total = sum(len(es) for _, es in grouped_entries)
    widget_values, widget_fields = _load_widget_values()

    return render_template(
        "dashboard.html",
        grouped_entries=grouped_entries,
        total_entries=visible_total,
        all_entries_count=len(entries),
        **_health_count_context(entries, show_urlless, source, status),
        status_filter=status,
        source_filter=source,
        group_by=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        msg=msg,
        STD_DOZZLE_URL=current_app.config.get("std_dozzle_url"),
        display_tools=current_app.config.get("display_tools", False),
        widget_values=widget_values,
        widget_fields=widget_fields,
        active_tab='dashboard',
    )


@dashboard_bp.route('/tiled_dash')
@login_required
def tiled_dashboard():
    axis, show_urlless, sort_in_group = _read_view_controls()

    entries = _load_view_entries()
    status, source = _read_filters()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
    )

    visible_total = sum(len(es) for _, es in grouped_entries)
    widget_values, widget_fields = _load_widget_values()

    return render_template(
        "tiled_dash.html",
        grouped_entries=grouped_entries,
        group_by=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        STD_DOZZLE_URL=current_app.config['std_dozzle_url'],
        total_entries=visible_total,
        all_entries_count=len(entries),
        **_health_count_context(entries, show_urlless, source, status),
        status_filter=status,
        source_filter=source,
        host_label_ids=_host_label_ids(entries),
        widget_values=widget_values,
        widget_fields=widget_fields,
    )


@dashboard_bp.route('/compact_dash')
@login_required
def compact_dash():
    axis, show_urlless, sort_in_group = _read_view_controls(
        default_sort_in_group="alphabetical"
    )

    entries = _load_view_entries()
    status, source = _read_filters()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
    )

    flattened_entries = []
    visible_total = 0
    for label, bucket_entries in grouped_entries:
        flattened_entries.append({'is_group_header': True, 'group': label})
        for entry in bucket_entries:
            flattened_entries.append({'is_group_header': False, 'entry': entry})
            visible_total += 1

    return render_template(
        "compact_dash.html",
        flattened_entries=flattened_entries,
        total_entries=visible_total,
        all_entries_count=len(entries),
        **_health_count_context(entries, show_urlless, source, status),
        status_filter=status,
        source_filter=source,
        host_label_ids=_host_label_ids(entries),
        group_by=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        active_tab="compact"
    )


@dashboard_bp.route("/dbdump")
@login_required
@is_admin_required
def db_dump():
    # All rows, soft-deleted included (marked in the template): this is
    # the raw-table view, so hiding rows would defeat its purpose.
    entries = ServiceEntry.query.order_by(ServiceEntry.id).all()
    return render_template("dbdump.html", entries=entries)


AUDIT_VIEW_LIMIT = 200


def _audit_change_lines(changes):
    """Plain-text lines for an audit row's `{field: [old, new]}`. Jinja escapes
    them on output; values are shortened, and secrets arrive already masked."""
    if not isinstance(changes, dict):
        return []

    def show(value):
        text = value if isinstance(value, str) else json.dumps(value, default=str)
        return text if len(text) <= 120 else text[:117] + '...'

    lines = []
    for field, pair in changes.items():
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            lines.append(f'{field}: {show(pair[0])} -> {show(pair[1])}')
        else:
            lines.append(f'{field}: {show(pair)}')
    return lines


@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@is_admin_required
def settings():
    BACKUP_DIR = current_app.config.get("backup_path", os.path.join(CONFIG_DIR, "backups"))
    BACKUP_PATH = os.path.join(BACKUP_DIR, "backup.yml")
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'backup':
            backup_operation = request.form.get('backup_operation')

            # Backup is always for all entries now, soft-deleted included
            # (to_dict carries deleted_at so a restore round-trips it).
            entries = ServiceEntry.query.all()
            data = []
            for e in entries:
                entry_data = e.to_dict()

                # Add authoritative group_name from the relationship if group is linked
                if e.group:
                    entry_data['group_name'] = e.group.group_name
                else:
                    entry_data['group_name'] = None  # fallback for safety

                data.append(entry_data)


            try:
                with open(BACKUP_PATH, 'w') as f:
                    yaml.dump(data, f, allow_unicode=True, sort_keys=False)
                logger.info(f"📦 Default YAML backup updated at {BACKUP_PATH} (all entries)")

                if backup_operation == 'save_on_server':
                    # If the goal was just to save on the server, we're done.
                    flash(f"✅ Backup saved to server: {BACKUP_PATH}", "success")
                    return redirect(url_for('dashboard.settings', section='backup'))

                elif backup_operation == 'download_all':
                    # If the goal is to download, send the file that was just written.
                    logger.info(f"📦 Preparing YAML backup for download from {BACKUP_PATH} (all entries)")
                    return send_file(
                        BACKUP_PATH,
                        mimetype='text/yaml',
                        as_attachment=True,
                        download_name=f'service_backup_all_{datetime.now().strftime("%Y%m%d_%H%M%S")}.yaml' # Added timestamp to download
                    )
                else:
                    flash("Unknown backup operation.", "danger")
                    return redirect(url_for('dashboard.settings', section='backup'))

            except Exception as e:
                logger.exception("❌ Backup operation failed")
                flash(f"Backup operation failed: {str(e)}", "danger")
                return redirect(url_for('dashboard.settings'))

        elif action == 'restore':
            restore_source = request.form.get('restore_source')
            restore_scope = request.form.get('restore_scope', 'all') # Defaults to 'all'

            records = None
            source_description = "unknown source"

            try:
                if restore_source == 'upload':
                    file = request.files.get('restore_file')
                    if file and file.filename:
                        content = file.read().decode('utf-8')
                        records = yaml.safe_load(content)
                        source_description = f"uploaded file '{file.filename}'"
                    else:
                        flash("No file uploaded for restore.", "warning")
                        return redirect(url_for('dashboard.settings'))

                elif restore_source == 'server':
                    selected_filename = request.form.get('server_backup_filename')
                    if selected_filename:
                        # Confine to BACKUP_DIR: a bare filename with a backup
                        # extension whose resolved path stays inside the folder.
                        safe_name = os.path.basename(selected_filename)
                        backup_root = os.path.realpath(BACKUP_DIR)
                        file_path = os.path.realpath(os.path.join(backup_root, safe_name))
                        if (
                            safe_name != selected_filename
                            or not safe_name.endswith(('.yaml', '.yml'))
                            or not file_path.startswith(backup_root + os.sep)
                        ):
                            flash("Invalid server filename selected.", "danger")
                            return redirect(url_for('dashboard.settings'))

                        if os.path.exists(file_path) and os.path.isfile(file_path):
                            with open(file_path, 'r') as f:
                                records = yaml.safe_load(f)
                            source_description = f"server file '{selected_filename}'"
                        else:
                            flash(f"Selected server backup file '{selected_filename}' not found or is invalid.", "danger")
                            return redirect(url_for('dashboard.settings'))
                    else:
                        flash("No server backup file selected.", "warning")
                        return redirect(url_for('dashboard.settings'))
                else:
                    flash("Invalid restore source selected.", "danger")
                    return redirect(url_for('dashboard.settings'))

                if records is None:
                    if not flash_is_present(request): # Avoid double flashing if already flashed above
                         flash("Could not load records for restore.", "danger")
                    return redirect(url_for('dashboard.settings'))

                restored_count = 0
                skipped_count = 0

                for item in records:
                    # Source: backups from before v0.7.0 have none; use the
                    # migration's backfill rule (never registered -> manual).
                    item_source = item.get('source')
                    if item_source not in VALID_SOURCES:
                        item_source = SOURCE_NOTIFIER if item.get('last_api_update') else SOURCE_MANUAL
                    item_host = (item.get('host') or '').strip() or None

                    # Host is optional for manual entries only.
                    if not item.get('container_name') or (item_host is None and item_source != SOURCE_MANUAL):
                        logger.warning(f"⛔ Skipping entry with missing host/container_name: {item}")
                        skipped_count +=1
                        continue

                    item_is_static_from_backup = item.get('is_static', False)

                    # Apply restore_scope: if scope is 'static', skip non-static items from backup
                    if restore_scope == 'static' and not item_is_static_from_backup:
                        skipped_count +=1
                        continue

                    # Handle embedded widget data if present
                    # --- 1. Restore or create the widget ---
                    widget_data = item.get('widget')
                    widget_obj = None

                    if widget_data:
                        widget_obj = Widget.query.filter_by(
                            widget_name=widget_data.get('widget_name'),
                            widget_url=widget_data.get('widget_url')
                        ).first()

                        if not widget_obj:
                            widget_obj = Widget(
                                widget_name=widget_data.get('widget_name'),
                                widget_url=widget_data.get('widget_url'),
                                widget_fields=widget_data.get('widget_fields') or [],
                                widget_api_key=widget_data.get('widget_api_key'),
                            )
                            db.session.add(widget_obj)
                        else:
                            widget_obj.widget_fields = widget_data.get('widget_fields') or []
                            widget_obj.widget_api_key = widget_data.get('widget_api_key')

                        db.session.flush()  # ensure widget_obj.id is available



                    entry = ServiceEntry.query.filter_by(
                        container_name=item['container_name'],
                        host=item_host
                    ).first()

                    group_name = item.get('group_name')
                    group_obj = None

                    if group_name:
                        group_obj = Group.query.filter_by(group_name=group_name).first()
                        if not group_obj:
                            group_obj = Group(group_name=group_name)
                            db.session.add(group_obj)
                            db.session.flush()

                    # Fetch or create entry
                    entry = ServiceEntry.query.filter_by(
                        container_name=item['container_name'],
                        host=item_host
                    ).first()

                    if not entry:
                        entry = ServiceEntry(host=item_host, container_name=item['container_name'])
                        db.session.add(entry)

                    # Assign group_id only now (after entry exists)
                    entry.group_id = group_obj.id if group_obj else None


                    if entry: # Entry exists in DB
                        # Rule: Protect existing static entries in DB from being overwritten by non-static items
                        # during a 'restore all' operation.
                        if entry.is_static and restore_scope == 'all' and not item_is_static_from_backup:
                            logger.info(f"ℹ️ Skipping update for DB static entry '{entry.container_name}' "
                                        f"by non-static item from backup during 'all' scope restore.")
                            skipped_count +=1
                            continue
                        # Otherwise (entry is not static, or item from backup is static, or scope is 'static'), proceed to update.
                    else: # New entry, create it
                        entry = ServiceEntry(host=item_host, container_name=item['container_name'])
                        db.session.add(entry)
                    if widget_obj:
                        entry.widget_id = widget_obj.id

                    # Apply fields from backup item to DB entry
                    for field, value in item.items():
                        # Ensure 'is_static' is handled correctly based on the item from backup
                        if field == 'is_static':
                            if hasattr(entry, 'is_static'):
                                entry.is_static = item_is_static_from_backup
                        elif hasattr(entry, field) and field not in ['id', 'last_updated', 'last_api_update', 'widget', 'deleted_at', 'health_check_timeout', 'health_check_verify_tls', 'host', 'source', 'checks', 'internal_health_check_enabled', 'external_health_check_enabled']:
                            setattr(entry, field, value)

                    entry.source = item_source
                    entry.host = item_host

                    # deleted_at round-trips; absent (v0.6.8 backups) means active.
                    entry.deleted_at = _parse_backup_datetime(item.get('deleted_at'))

                    # Health checks (v0.7.0): a new-format backup carries `checks`;
                    # an older one is mapped from the legacy fields.
                    _restore_checks(entry, item)

                    # If 'is_static' wasn't in item.items() but we are creating, ensure it's set
                    # (especially if item_is_static_from_backup was derived from .get with a default)
                    if not entry.id and hasattr(entry, 'is_static'): # if it's a new entry being added
                         if 'is_static' not in item: # if 'is_static' was not explicitly in the backup item dict
                            entry.is_static = item_is_static_from_backup # ensure it's set from .get default

                    entry.last_updated = datetime.now()
                    restored_count += 1

                db.session.commit()
                flash_message = f"✅ Restored {restored_count} entries"
                if restore_scope == 'static':
                    flash_message += " (static entries only)"
                flash_message += f" from {source_description}."
                if skipped_count > 0:
                    flash_message += f" Skipped {skipped_count} items."
                flash(flash_message, "success")
                logger.info(f"♻️ {flash_message}")

            except Exception as e:
                db.session.rollback() # Rollback in case of error during DB operations
                logger.exception("❌ Restore failed")
                flash(f"Restore failed: {str(e)}", "danger")

            return redirect(url_for('dashboard.settings', section='backup'))

    return _render_settings()


def _render_settings(group_form=None, status=200):
    """Render the Settings page. `group_form` (a failed Groups save) is shown in
    place of the stored groups, with its per-row errors, on the Groups tab."""
    BACKUP_DIR = current_app.config.get("backup_path", os.path.join(CONFIG_DIR, "backups"))
    image_dir = current_app.config['IMAGE_DIR']
    os.makedirs(BACKUP_DIR, exist_ok=True)
    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()

    if group_form:
        group_rows = group_form['rows']
    else:
        group_rows = [{'id': g.id, 'name': g.group_name, 'icon': g.group_icon or '',
                       'priority': '' if g.group_sort_priority is None else g.group_sort_priority,
                       'services_count': g.services_count, 'delete': False} for g in groups]

    # List backup files for the restore dropdown
    server_backup_files = []
    if os.path.exists(BACKUP_DIR):
        try:
            # List files and filter for .yaml or .yml, sort them (e.g., reverse for newest first if names allow)
            all_files = [f for f in os.listdir(BACKUP_DIR) if os.path.isfile(os.path.join(BACKUP_DIR, f)) and (f.endswith('.yaml') or f.endswith('.yml'))]
            # You might want to sort these files, e.g., by modification time or name
            all_files.sort(reverse=True) # Example: newest first if names are sortable by time
            server_backup_files = all_files
        except Exception as e:
            logger.exception(f"Error listing backup files from {BACKUP_DIR}")
            flash(f"Could not list server backup files: {str(e)}", "warning")

# Check which icon files are missing
        missing_icons = []
        all_entries = ServiceEntry.active().all()
        for entry in all_entries:
            icon = entry.image_icon
            if icon and not os.path.exists(os.path.join(image_dir, icon)):
                missing_icons.append(f"{entry.container_name} → {icon}")
    widgets = Widget.query.all()
    users = User.query.order_by(User.username.asc()).all()

    # Exposure interpreter settings (v0.6.0). Only layers that have
    # been observed get exposed for configuration — the form should
    # never offer an empty table or invented layer names.
    exposure_layers = settings_store.discovered_layers()
    exposure_layer_directions = settings_store.get_layer_directions()
    exposure_hosts = settings_store.discovered_hosts()
    exposure_host_overrides = settings_store.get_host_layer_overrides()

    audit_filter = (request.args.get('audit_key') or '').strip()
    audit_query = ApiAudit.query
    if audit_filter.startswith('id:') and audit_filter[3:].isdigit():
        audit_query = audit_query.filter(ApiAudit.api_key_id == int(audit_filter[3:]))
    elif audit_filter:
        audit_query = audit_query.filter(ApiAudit.key_name == audit_filter, ApiAudit.api_key_id.is_(None))
    audit_rows = [
        {'row': r, 'changes': _audit_change_lines(r.changes)}
        for r in audit_query.order_by(ApiAudit.ts.desc(), ApiAudit.id.desc()).limit(AUDIT_VIEW_LIMIT).all()
    ]
    # Filter options: one per key id (a reused name is two different keys, the
    # revoked one labelled), plus name-only options for rows whose key is gone.
    audit_key_options = []
    for kid, kname, revoked_at in (
            db.session.query(ApiAudit.api_key_id, ApiAudit.key_name, ApiKey.revoked_at)
            .outerjoin(ApiKey, ApiKey.id == ApiAudit.api_key_id)
            .filter(ApiAudit.key_name.isnot(None)).distinct()
            .order_by(ApiAudit.key_name, ApiAudit.api_key_id).all()):
        if kid is None:
            audit_key_options.append({'value': kname, 'label': kname})
        else:
            audit_key_options.append({'value': f'id:{kid}',
                                      'label': f'{kname} (revoked)' if revoked_at else kname})

    return render_template(
        'settings.html',
         current_config=current_app.config['LOADED_SETTINGS'],
         config_from_env=current_app.config['CONFIG_FROM_ENV'],
         config_from_file=current_app.config['CONFIG_FROM_FILE'],
         server_backup_files=server_backup_files,
         version_info=current_app.config['VERSION_INFO'],
         version_display=version_check.display_info(current_app.config['VERSION_INFO']),
         update_status=version_check.status(current_app.config['VERSION_INFO'].get('version', 'unknown')),
         widgets=widgets,
         missing_icons=missing_icons,
         groups=groups,
         group_form=group_form,
         group_rows=group_rows,
         force_section='groups' if group_form else '',
         users=users,
         deleted_rows=_deleted_entry_rows(),
         detached_widgets=_detached_widget_rows(),
         attachable_entries=ServiceEntry.active().filter(ServiceEntry.widget_id.is_(None))
             .order_by(ServiceEntry.container_name.asc(), ServiceEntry.host.asc()).all(),
         deleted_retention_days=_retention_days(),
         api_token_missing=not current_app.config.get('api_token'),
         default_secret_key=current_app.config.get('DEFAULT_SECRET_KEY_IN_USE', False),
         default_admin_password=current_app.config.get('DEFAULT_ADMIN_PASSWORD_IN_USE', False),
         audit_rows=audit_rows,
         audit_key_options=audit_key_options,
         audit_filter=audit_filter,
         audit_limit=AUDIT_VIEW_LIMIT,
         api_key_rows=ApiKey.query.order_by(ApiKey.created_at.desc(), ApiKey.id.desc()).all(),
         exposure_layers=exposure_layers,
         exposure_layer_directions=exposure_layer_directions,
         exposure_hosts=exposure_hosts,
         exposure_host_overrides=exposure_host_overrides,
    ), status


@dashboard_bp.route('/settings/exposure', methods=['POST'])
@login_required
@is_admin_required
def save_exposure_settings():
    """Save per-interpreter direction mappings and trigger
    synthesizer recompute for all services.

    Form shape: for each discovered layer L, a field named
    `layer:<L>` with value "internal"/"external"/"neither".
    For each per-host override, fields named `override:<host>:<L>`
    with the same values. Empty / missing fields default to
    "neither" (no override).
    """
    layer_directions = {}
    host_overrides = {}
    for field, value in request.form.items():
        if not value:
            continue
        if field.startswith("layer:"):
            layer = field[len("layer:"):]
            if layer:
                layer_directions[layer] = value
        elif field.startswith("override:"):
            rest = field[len("override:"):]
            if ":" in rest:
                host, layer = rest.split(":", 1)
                if host and layer:
                    host_overrides.setdefault(host, {})[layer] = value

    settings_store.save_exposure_settings(layer_directions, host_overrides)
    touched = synthesizer.recompute_all()
    db.session.commit()
    flash(
        f"✅ Exposure settings saved. Recomputed URLs for {touched} service(s).",
        "success",
    )
    return redirect(url_for('dashboard.settings', section='exposure'))


@dashboard_bp.route('/settings/update-check', methods=['POST'])
@login_required
@is_admin_required
def save_update_check():
    """Save the update-check toggle and interval (Settings -> Info)."""
    enabled = request.form.get('update_check_enabled') == '1'
    raw = (request.form.get('update_check_interval_hours') or '').strip()
    try:
        hours = int(raw)
        if hours < 1:
            raise ValueError
    except ValueError:
        flash("Update check interval must be a whole number of hours, 1 or more.", "danger")
        return redirect(url_for('dashboard.settings', section='info'))
    settings_store.save_update_check_settings(enabled, hours)
    db.session.commit()
    version_check.reset()  # re-read the cache/interval; the next page load may refetch
    flash("✅ Update check settings saved.", "success")
    return redirect(url_for('dashboard.settings', section='info'))


def _parse_group_form(form, groups):
    """Read the Groups table form into `(rows, new_row, errors)`.

    `rows` holds one dict per stored group, in `groups` order, with the
    submitted values (`name`, `icon`, `priority` as typed, `delete`);
    `new_row` is the optional added group or None; `errors` maps a row key
    (the group id, or "new") to its messages. Nothing is written here."""
    rows, errors = [], {}

    def problem(key, message):
        errors.setdefault(key, []).append(message)

    for g in groups:
        pre = f'group-{g.id}-'
        if pre + 'name' not in form:
            continue  # not in the submitted table (added after it loaded)
        row = {'id': g.id, 'services_count': g.services_count,
               'name': (form.get(pre + 'name') or '').strip(),
               'icon': (form.get(pre + 'icon') or '').strip(),
               'priority': (form.get(pre + 'priority') or '').strip(),
               'delete': form.get(pre + 'delete') == '1',
               'group': g}
        row['priority_value'], priority_error = entry_rules.parse_sort_priority(row['priority'])
        if row['delete']:
            if g.services_count:
                problem(g.id, 'Cannot delete a group that has entries. Move them first.')
        else:
            for e in entry_rules.validate_group(row['name'], row['icon']):
                problem(g.id, e['message'])
            if priority_error:
                problem(g.id, priority_error)
        rows.append(row)

    new_row = None
    new_name = (form.get('new-name') or '').strip()
    if new_name:
        new_row = {'name': new_name, 'icon': (form.get('new-icon') or '').strip(),
                   'priority': (form.get('new-priority') or '').strip()}
        new_row['priority_value'], priority_error = entry_rules.parse_sort_priority(new_row['priority'])
        for e in entry_rules.validate_group(new_row['name'], new_row['icon']):
            problem('new', e['message'])
        if priority_error:
            problem('new', priority_error)

    # Names must be unique across the resulting set (deleted rows free theirs).
    seen = {}
    final = [(r['id'], r['name']) for r in rows if not r['delete']]
    if new_row:
        final.append(('new', new_row['name']))
    for key, name in final:
        if name:
            seen.setdefault(name, []).append(key)
    for name, keys in seen.items():
        if len(keys) > 1:
            for key in keys:
                problem(key, f"Another group is already named '{name}'.")
    return rows, new_row, errors


@dashboard_bp.route('/settings/groups/save', methods=['POST'])
@login_required
@is_admin_required
def save_groups():
    """Apply the whole Settings -> Groups table at once, or nothing.

    Row fields are `group-<id>-name|icon|priority|delete` plus the optional
    `new-name|icon|priority`. Any validation error re-renders the page (400)
    with what was typed and per-row messages; success redirects."""
    groups = Group.query.all()
    submitted_ids = {int(m.group(1)) for k in request.form
                     if (m := re.match(r'group-(\d+)-name$', k))}
    stale = submitted_ids - {g.id for g in groups}
    rows, new_row, errors = _parse_group_form(request.form, groups)

    if stale or len(submitted_ids) < len(groups):
        # The table the operator saw is out of date (a group was removed, or one
        # added elsewhere), so applying it could silently undo someone's change.
        flash("The groups changed since this page loaded. Nothing was saved; "
              "your edits are still in the table.", "danger")
        errors.setdefault('page', []).append('stale')

    if errors:
        group_form = {'rows': rows, 'new': new_row, 'errors': errors}
        flash("Nothing was saved. Fix the marked rows and save again.", "danger")
        return _render_settings(group_form=group_form, status=400)

    updated = added = deleted = 0
    try:
        # Group names are UNIQUE and SQLite checks per statement, so a swap
        # (A<->B) or reusing a freed name needs the old names out of the way
        # first: delete, park renamed rows on a placeholder, then set finals.
        for r in rows:
            if r['delete']:
                # Only active entries block deletion; soft-deleted ones are
                # detached so no dangling group_id is left behind.
                for e in r['group'].services:
                    e.group_id = None
                db.session.delete(r['group'])
                deleted += 1
        changed = [r for r in rows if not r['delete'] and (
            r['group'].group_name, r['group'].group_icon or '', r['group'].group_sort_priority) !=
            (r['name'], r['icon'], r['priority_value'])]
        renamed = [r for r in changed if r['group'].group_name != r['name']]
        for r in renamed:
            r['group'].group_name = f"\x00renaming-{r['id']}"
        db.session.flush()
        for r in changed:
            g = r['group']
            g.group_name = r['name']
            g.group_icon = r['icon'] or None
            g.group_sort_priority = r['priority_value']
            updated += 1
        if new_row:
            db.session.flush()
            db.session.add(Group(group_name=new_row['name'], group_icon=new_row['icon'] or None,
                                 group_sort_priority=new_row['priority_value']))
            added += 1
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Saving groups failed")
        flash("Saving groups failed; nothing was changed.", "danger")
        return redirect(url_for('dashboard.settings', section='groups'))

    parts = [f'{n} {label}' for n, label in ((updated, 'updated'), (added, 'added'), (deleted, 'deleted')) if n]
    flash(f"✅ Saved: {', '.join(parts)}." if parts else "No changes.", "success")
    return redirect(url_for('dashboard.settings', section='groups'))


@dashboard_bp.route('/images/<path:filename>')
@login_required
def serve_image(filename):
    response = make_response(send_from_directory(current_app.config['IMAGE_DIR'], filename))
    response.headers['Cache-Control'] = 'public, max-age=86400'  # cache for 1 day
    return response


def _drop_stale_success_flashes():
    """Forget non-error flashes queued by earlier redirects.

    The Dashboard views don't render flashes, so "Logged in" or "Entry
    updated" messages wait in the session until a page that does. Showing
    them on a fresh Add/Edit page would be noise; warnings and errors (for
    example the failed delete confirmation redirected to Edit) are kept.
    """
    kept = [(cat, msg) for cat, msg in session.get('_flashes', []) if cat in ('warning', 'danger')]
    if kept:
        session['_flashes'] = kept
    else:
        session.pop('_flashes', None)


@dashboard_bp.route('/add', methods=['GET', 'POST'])
@login_required
@is_admin_required
def add_entry():
    _drop_stale_success_flashes()
    image_dir = current_app.config['IMAGE_DIR']

    if request.method == 'POST':
        # Needed by every error re-render of the add form below.
        groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
        url_rows, svc_rows, check_errors = check_form.parse_form(request.form)

        def render_error(msg='error'):
            return render_template("add_entry.html", msg=msg, entry=request.form, groups=groups,
                                   url_rows=url_rows, svc_rows=svc_rows)

        host = (request.form.get('host') or '').strip() or None
        container_name = (request.form.get('container_name') or '').strip()
        description = (request.form.get('description') or '').strip() or None
        internalurl = request.form.get('internal_url')
        externalurl = request.form.get('external_url')
        group_mode = request.form.get('group_mode')  # 'existing' or 'new'
        group_name = None

        if group_mode == 'existing':
            group_name = request.form.get('group_name_existing')
        elif group_mode == 'new':
            group_name = request.form.get('group_name_new')

        # No group picked -> the entry is ungrouped (group_id NULL). This used
        # to create/reuse a real group literally named "None".
        group_name = (group_name or '').strip() or None


        image_icon, icon_error = entry_rules.resolve_icon(request.form.get('icon_image', ''))
        if icon_error:
            flash('Invalid icon name: use letters, numbers, dots, dashes and underscores only.', 'danger')
            return render_error()

        basic_errors = entry_rules.validate_basic(container_name, host, description)
        if any(e['field'] == 'name' and 'required' in e['message'] for e in basic_errors):
            flash('Name is required.', 'danger')
            return render_error()
        if basic_errors:
            flash('Name and Host are limited to 100 characters, Description to 255.', 'danger')
            return render_error()

        # Check for duplicates. An empty host is its own value: the key is
        # (host or NULL, name).
        existing = entry_rules.find_duplicate(host, container_name)
        if existing:
            flash(entry_rules.duplicate_message(existing, container_name, host), 'danger')
            return render_error('duplicate')

        # Booleans
        is_static = request.form.get('locked') == 'on'

        # === ICON RESOLUTION LOGIC ===
        if image_icon:
            entry_rules.download_icon(image_dir, image_icon, container_name)
        else:
            derived_icon_name = container_name.lower().replace(" ", "-")
            image_icon = fetch_icon_if_missing(derived_icon_name, image_dir, logger, debug=current_app.debug)
            if image_icon:
                logger.info(f"💡 Automatically fetched icon '{image_icon}' for new entry '{container_name}'.")
            else:
                logger.info(f"⚠️ Could not automatically fetch icon for '{container_name}'.")

        # Optional sort priority (must be an int if provided)
        sort_priority, sort_error = entry_rules.parse_sort_priority(request.form.get('sort_priority', ''))
        if sort_error:
            flash("Sort priority must be a number.", 'danger')
            return render_error()

        if check_errors:
            for message in check_errors:
                flash(message, 'danger')
            return render_error()

        # === CREATE ENTRY ===
        # Look up or create group
        group_obj = entry_rules.get_or_create_group(group_name) if group_name else None

        # Now create entry with group_id. URLs typed in the UI get
        # source=ui_edit so future register calls and the synthesizer
        # don't clobber them.
        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            description=description,
            source=SOURCE_MANUAL,
            internalurl=internalurl or None,
            externalurl=externalurl or None,
            internalurl_source=synthesizer.SOURCE_UI_EDIT if internalurl else None,
            externalurl_source=synthesizer.SOURCE_UI_EDIT if externalurl else None,
            last_updated=datetime.now(),
            group_id=group_obj.id if group_obj else None,
            image_icon=image_icon,
            sort_priority=sort_priority,
            is_static=is_static,
        )
        check_form.apply_rows(entry, url_rows, svc_rows)

        db.session.add(entry)
        db.session.commit()

        flash(f"✅ Service entry '{container_name}' added successfully!", 'success')
        return redirect(url_for('dashboard.tiled_dashboard'))

    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
    url_rows, svc_rows = check_form.default_rows()
    return render_template("add_entry.html", msg='', entry={}, active_tab="add", groups=groups,
                           url_rows=url_rows, svc_rows=svc_rows)


def _positive_int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _text_or_none(value):
    value = value.strip() if isinstance(value, str) else ''
    return value or None


def _restore_checks(entry, item):
    """Apply a backup record's health-check configuration to `entry`.

    New format: `item['checks']` is a list of check configs. URL-kind rows
    are matched by kind; service rows are replaced wholesale. Old format (no
    `checks`): the legacy `*_health_check_enabled`, `health_check_timeout`
    and `health_check_verify_tls` fields are mapped onto the two URL rows,
    absent meaning disabled / global timeout / verify TLS on.
    """
    ensure_url_checks(entry)
    ensure_container_check(entry)
    checks = item.get('checks')
    if isinstance(checks, list):
        # Service rows are replaced wholesale by what the backup carries.
        for old in entry.service_checks:
            entry.checks.remove(old)
        for cfg in checks:
            if not isinstance(cfg, dict):
                continue
            kind = cfg.get('kind')
            if kind == CHECK_KIND_CONTAINER:
                # Notifier entries only; just enabled + interval round-trip.
                check = entry.container_check
                if check is not None:
                    check.interval_seconds = _positive_int(cfg.get('interval_seconds'))
                    check.enabled = bool(cfg.get('enabled'))
                continue
            if kind in URL_CHECK_KINDS:
                check = entry.url_check(kind)
            elif kind == CHECK_KIND_SERVICE:
                check = HealthCheck(kind=CHECK_KIND_SERVICE, consecutive_failures=0)
                entry.checks.append(check)
            else:
                continue
            check.name = cfg.get('name')
            if cfg.get('check_type') in CHECK_TYPES:
                check.check_type = cfg['check_type']
            check.target = cfg.get('target') if kind == CHECK_KIND_SERVICE else None
            if cfg.get('mode') in CHECK_MODES:
                check.mode = cfg['mode']
            check.interval_seconds = _positive_int(cfg.get('interval_seconds'))
            check.timeout_seconds = _positive_int(cfg.get('timeout_seconds'))
            check.verify_tls = cfg.get('verify_tls') is not False
            check.enabled = bool(cfg.get('enabled'))
            # DNS settings (v0.9.0); absent in older backups, so they stay NULL.
            is_dns = check.check_type == CHECK_TYPE_DNS and kind == CHECK_KIND_SERVICE
            check.dns_name = _text_or_none(cfg.get('dns_name')) if is_dns else None
            rtype = _text_or_none(cfg.get('dns_record_type'))
            check.dns_record_type = rtype.upper() if is_dns and rtype else None
            rcode = _text_or_none(cfg.get('dns_expected_rcode'))
            check.dns_expected_rcode = rcode.upper() if is_dns and rcode else None
            check.dns_expected_answer = _text_or_none(cfg.get('dns_expected_answer')) if is_dns else None
            # Certificate-expiry minimum (v0.9.0); absent in older backups. Only
            # http checks use it, and the cached expiry is never restored.
            days = cfg.get('cert_min_days')
            is_http = check.check_type == CHECK_TYPE_HTTP
            valid = isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 365
            check.cert_min_days = days if is_http and valid else None
            check.last_cert_expires_at = None
        return

    timeout = _positive_int(item.get('health_check_timeout'))
    verify = item.get('health_check_verify_tls') is not False
    for which in ('internal', 'external'):
        check = entry.url_check(which)
        check.enabled = bool(item.get(f'{which}_health_check_enabled'))
        check.timeout_seconds = timeout
        check.verify_tls = verify


@dashboard_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@is_admin_required
def edit_entry(id):
    _drop_stale_success_flashes()
    image_dir = current_app.config['IMAGE_DIR']
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()

    # Track the referrer for redirecting after save
    referrer = safe_redirect_target(request.args.get('ref'), url_for('dashboard.dashboard'))

    # Discover available widgets
    widgets_dir = '/app/widgets'
    available_widgets = []
    if os.path.exists(widgets_dir):
        available_widgets = [
            d for d in os.listdir(widgets_dir)
            if os.path.isdir(os.path.join(widgets_dir, d)) and d != '__pycache__'
        ]
        logger.debug(f"Widgets found: {', '.join(available_widgets)}") if available_widgets else logger.debug("No widgets found.")
    else:
        logger.warning(f"Widgets directory not found: {widgets_dir}")

    # Fetch current widget association
    selected_widget = None
    if entry.widget_id:
        selected_widget = Widget.query.get(entry.widget_id)
        if selected_widget:
            logger.debug(f"Selected widget: {selected_widget.widget_name}")
        else:
            logger.warning(f"Widget ID {entry.widget_id} not found")

    def render_edit(form=None, url_rows=None, svc_rows=None, container_row=None):
        groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
        if url_rows is None:
            url_rows, svc_rows = check_form.rows_from_entry(entry)
        if container_row is None:
            container_row = check_form.container_row_from_entry(entry)
        return render_template("edit_entry.html",
                               entry=entry,
                               ref=referrer,
                               groups=groups,
                               available_widgets=available_widgets,
                               selected_widget=selected_widget,
                               form=form,
                               url_rows=url_rows,
                               svc_rows=svc_rows,
                               container_row=container_row)

    # Handle form submission
    if request.method == 'POST':
        # === DELETE ACTION ===
        if 'delete' in request.form:
            if request.form.get('delete_confirmation') == entry.container_name:


                # Soft delete: recoverable from Settings -> Deleted. The widget
                # stays attached; nothing else is removed.
                entry.deleted_at = datetime.now()
                db.session.commit()
                flash(
                    f"Deleted entry: {entry.container_name}. "
                    f"{_restore_hint()}",
                    'success',
                )
                return redirect(safe_redirect_target(referrer))
            else:
                flash("Confirmation name does not match. Entry not deleted.", "warning")
                return redirect(url_for('dashboard.edit_entry', id=id, ref=referrer))

        # === HEALTH CHECKS: validate first, change nothing on error ===
        checks_submitted = 'checks_form' in request.form
        if checks_submitted:
            url_rows, svc_rows, check_errors = check_form.parse_form(
                request.form, {c.id for c in entry.service_checks})
            container_row = None
            if entry.container_check is not None:
                container_row, container_errors = check_form.parse_container(request.form)
                check_errors += container_errors
            if check_errors:
                for message in check_errors:
                    flash(message, 'danger')
                return render_edit(form=request.form, url_rows=url_rows, svc_rows=svc_rows,
                                   container_row=container_row)

        # === BASIC FIELDS ===
        new_host = request.form.get('host', '').strip()
        if entry.is_manual:
            # Host is optional for manual entries.
            entry.host = new_host or None
            entry.description = request.form.get('description', '').strip()[:255] or None
        else:
            entry.host = new_host
        entry.container_name = request.form.get('container_name', '').strip()

        # URL provenance: setting a URL via UI marks it ui_edit (highest
        # precedence, the synthesizer won't touch it). Clearing the URL
        # resets source to null so synthesis can re-fill on the next
        # register. See synthesizer.py for the ordering rules.
        url_changed = {
            'internal': entry_rules.set_url(entry, 'internal', request.form.get('internalurl', '')),
            'external': entry_rules.set_url(entry, 'external', request.form.get('externalurl', '')),
        }

        ensure_url_checks(entry)
        if checks_submitted:
            check_form.apply_rows(entry, url_rows, svc_rows)
            check_form.apply_container(entry, container_row)
        # A changed URL is a new target: re-check it at the next tick.
        for which, changed in (('internal', url_changed['internal']), ('external', url_changed['external'])):
            if changed:
                entry.url_check(which).last_checked_at = None
        was_locked = entry.is_static
        entry.is_static = 'is_static' in request.form
        if was_locked and not entry.is_static and entry.container_check is not None:
            # Unlocked: the container state was frozen, so re-evaluate it now.
            entry.container_check.last_checked_at = None

        entry.sort_priority, sort_error = entry_rules.parse_sort_priority(request.form.get('sort_priority', ''))
        if sort_error:
            flash("Sort priority must be a number.", "warning")

        # === GROUP HANDLING ===
        group_mode = request.form.get('group_mode')


        group = None

        if group_mode == 'existing':
            group_id = request.form.get('group_id_existing')
            if group_id:
                group = Group.query.get(int(group_id))  # safely cast to int

        elif group_mode == 'new':
            group_name = request.form.get('group_name_new', '').strip()
            if group_name:
                group = Group.query.filter_by(group_name=group_name).first()
                if not group:
                    group = Group(group_name=group_name)
                    db.session.add(group)
                    db.session.commit()

        # fallback if none found
        if not group:
            group = Group.query.filter_by(group_name="zz_none").first()
            if not group:
                group = Group(group_name="zz_none")
                db.session.add(group)
                db.session.commit()

        entry.group_id = group.id
        entry.group_name = group.group_name

        # === ICON ===
        raw_icon = request.form.get('image_icon', '').strip()
        icon_ok = True
        if raw_icon:
            safe_icon = safe_icon_filename(raw_icon)
            if safe_icon:
                entry.image_icon = safe_icon
            else:
                icon_ok = False
                flash('Invalid icon name: icon not changed. Use letters, numbers, dots, dashes and underscores only.', 'warning')
        else:
            entry.image_icon = ''
        icon_path = icon_path_in_dir(image_dir, entry.image_icon) if (icon_ok and entry.image_icon) else None
        if not icon_ok:
            pass
        elif icon_path and not os.path.exists(icon_path):
            try:
                icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{entry.image_icon}"
                response = requests.get(icon_url, timeout=5)
                if response.status_code == 200:
                    with open(icon_path, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"Downloaded icon: {entry.image_icon}")
                else:
                    logger.warning(f"Icon not found at {icon_url}")
            except Exception as e:
                logger.warning(f"Error fetching icon: {e}")
        elif not entry.image_icon and request.form.get('force_update_icon') == 'true':
            derived_icon_name = entry.container_name.lower().replace(" ", "-")
            fetched_icon = fetch_icon_if_missing(derived_icon_name, image_dir, logger, debug=current_app.debug)
            if fetched_icon:
                entry.image_icon = fetched_icon

        # === WIDGET LOGIC ===
        widget_name = request.form.get('widget_name')
        widget_url = request.form.get('widget_url') or None
        widget_api_key = request.form.get('widget_api_key') or None
        widget_fields = request.form.getlist('widget_fields')

        if widget_name == 'none':
            if entry.widget_id:
                WidgetValue.query.filter_by(widget_id=entry.widget_id).delete()
                Widget.query.filter_by(id=entry.widget_id).delete()
                entry.widget_id = None
        else:
            if entry.widget_id:
                widget = Widget.query.get(entry.widget_id)
                if widget:
                    widget.widget_name = widget_name
                    widget.widget_url = widget_url
                    widget.widget_api_key = widget_api_key
                    widget.widget_fields = widget_fields
                else:
                    widget = Widget(widget_name=widget_name, widget_url=widget_url,
                                    widget_api_key=widget_api_key, widget_fields=widget_fields)
                    db.session.add(widget)
                    db.session.flush()
                    entry.widget_id = widget.id
            else:
                widget = Widget(widget_name=widget_name, widget_url=widget_url,
                                widget_api_key=widget_api_key, widget_fields=widget_fields)
                db.session.add(widget)
                db.session.flush()
                entry.widget_id = widget.id

        entry.last_updated = datetime.now()

        # If the operator cleared a URL its source is now NULL and the
        # synthesizer should refill from any remaining exposure rows
        # without waiting for the next register. Safe to call even when
        # nothing about URLs changed — it's a no-op when sources are
        # ui_edit / explicit_label.
        synthesizer.synthesize_for_entry(entry)

        try:
            db.session.commit()
            flash(f"✅ Entry '{entry.container_name}' updated!", "success")
        except Exception as e:
            db.session.rollback()
            logger.error(f"Update error: {e}")
            flash("Error saving changes", "danger")

        return redirect(safe_redirect_target(referrer))

    return render_edit()


@dashboard_bp.route('/service/<int:id>/checks/run', methods=['POST'])
@login_required
def run_checks_now(id):
    """Check now: run every enabled check of this entry at the next scheduler
    tick (within about 5 seconds). The last result stays in place until the
    new one is written; `requested_at` lets the panel poll for it."""
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()
    ids = [check.id for check in entry.checks if check_counts(entry, check)]
    jobs.request_run(ids)
    return jsonify({
        'ok': True,
        'queued': len(ids),
        'requested_at': health_history.iso_z(datetime.utcnow()),
    })


@dashboard_bp.route('/service/<int:id>/health')
@login_required
def entry_health_detail(id):
    """Detail panel data: per-check state, uptime, recent failures and the
    24h / 7d bar series (PRD 13.7). `range` is `24h` (default) or `7d`."""
    entry = (
        ServiceEntry.active()
        .options(selectinload(ServiceEntry.checks))
        .filter(ServiceEntry.id == id)
        .first_or_404()
    )
    range_name = request.args.get('range', '24h')
    if range_name not in health_history.RANGES:
        range_name = '24h'
    return jsonify(health_history.entry_payload(entry, range_name))


@dashboard_bp.route('/health/strips')
@login_required
def health_strips():
    """Inline 24h uptime strips for many entries in one request (PRD 13.7).
    `ids` is a comma-separated list, capped at MAX_STRIP_IDS; unknown,
    soft-deleted and non-numeric ids are silently left out."""
    ids = []
    for part in request.args.get('ids', '').split(','):
        part = part.strip()
        if part.isdigit() and int(part) not in ids:
            ids.append(int(part))
        if len(ids) >= health_history.MAX_STRIP_IDS:
            break
    if not ids:
        return jsonify({})
    entries = (
        ServiceEntry.active()
        .options(selectinload(ServiceEntry.checks))
        .filter(ServiceEntry.id.in_(ids))
        .all()
    )
    return jsonify({str(k): v for k, v in health_history.strips(entries).items()})


@dashboard_bp.route('/api/v1/entries/<int:id>/delete', methods=['POST'])
@login_required
@is_admin_required
def delete_entry_json(id):
    """JSON delete endpoint for JS-triggered deletes (tile trash icon, drawer delete button).

    Soft-deletes the entry (sets deleted_at). Returns {ok: true} on success. The caller is responsible for DOM cleanup or redirect.
    """
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()

    # Soft delete: recoverable from Settings -> Deleted. Widget stays attached.
    entry.deleted_at = datetime.now()
    db.session.commit()
    return jsonify({'ok': True})


@dashboard_bp.route('/settings/api-keys', methods=['POST'])
@login_required
@is_admin_required
def create_api_key():
    """Create an admin API key and show the full key once, on this response.

    The key is deliberately not flashed or put in the session; it exists only
    in the rendered page and is never retrievable again.
    """
    name = (request.form.get('name') or '').strip()
    scope = request.form.get('scope') or ''
    error = api_keys.validate_name(name)
    if not error and scope not in api_keys.SCOPES:
        error = "Choose a scope: read or write."
    if error:
        flash(error, "danger")
        return redirect(url_for('dashboard.settings', section='api'))
    key, full_key = api_keys.create_key(name, scope, created_by=current_user.id)
    logger.info(f"Created API key '{key.name}' ({key.prefix}, {key.scope}) by {current_user.username}.")
    response = make_response(render_template('api_key_created.html', key=key, full_key=full_key))
    response.headers['Cache-Control'] = 'no-store'
    return response


@dashboard_bp.route('/settings/api-keys/<int:id>/rotate', methods=['POST'])
@login_required
@is_admin_required
def rotate_api_key(id):
    """Issue a new secret for an active key; shown once, like creation.

    Logs the key id only (never the name, prefix or secret).
    """
    key = db.session.get(ApiKey, id)
    if key is None or key.revoked_at is not None:
        flash("That API key doesn't exist or is revoked, so it can't be rotated.", "danger")
        return redirect(url_for('dashboard.settings', section='api'))
    full_key = api_keys.rotate_key(key)
    logger.info(f"Rotated API key id={key.id} by {current_user.username}.")
    response = make_response(render_template('api_key_created.html', key=key, full_key=full_key,
                                             rotated=True))
    response.headers['Cache-Control'] = 'no-store, no-cache'
    response.headers['Pragma'] = 'no-cache'
    return response


@dashboard_bp.route('/settings/api-keys/<int:id>/revoke', methods=['POST'])
@login_required
@is_admin_required
def revoke_api_key(id):
    key = db.get_or_404(ApiKey, id)
    api_keys.revoke_key(key)
    logger.info(f"Revoked API key '{key.name}' ({key.prefix}) by {current_user.username}.")
    flash(f"Revoked API key '{key.name}'.", "success")
    return redirect(url_for('dashboard.settings', section='api'))


@dashboard_bp.route('/settings/deleted/<int:id>/restore', methods=['POST'])
@login_required
@is_admin_required
def restore_deleted_entry(id):
    entry = ServiceEntry.deleted().filter(ServiceEntry.id == id).first_or_404()
    clash = ServiceEntry.active().filter_by(
        host=entry.host, container_name=entry.container_name
    ).first()
    if clash:
        flash(
            f"Cannot restore '{entry.container_name}' on '{entry.host or 'no host'}': an active "
            f"entry with that name already exists.",
            "danger",
        )
    else:
        entry.deleted_at = None
        db.session.commit()
        logger.info(f"Restored soft-deleted entry '{entry.container_name}' on '{entry.host or 'no host'}'.")
        flash(f"✅ Restored '{entry.container_name}'.", "success")
    return redirect(url_for('dashboard.settings', section='deleted'))


@dashboard_bp.route('/settings/deleted/<int:id>/delete', methods=['POST'])
@login_required
@is_admin_required
def purge_deleted_entry(id):
    entry = ServiceEntry.deleted().filter(ServiceEntry.id == id).first_or_404()
    name = entry.container_name
    hard_delete_entry(entry)
    db.session.commit()
    logger.info(f"Permanently deleted entry '{name}'.")
    flash(f"🗑️ Permanently deleted '{name}'.", "success")
    return redirect(url_for('dashboard.settings', section='deleted'))


@dashboard_bp.route('/api/update-status')
@login_required
def update_status_api():
    """Cached update-check status for the header's hourly poll. Starts a
    background refresh when the cache is stale; never waits on GitHub and is
    read-only for the caller (GET)."""
    version_check.maybe_refresh(current_app._get_current_object())
    running = current_app.config['VERSION_INFO'].get('version', 'unknown')
    return jsonify(version_check.status(running))


@dashboard_bp.route('/api/v1/changelog')
@login_required
def changelog_api():
    """Return parsed CHANGELOG.md sections as JSON.

    ?since=<version>  — return only sections newer than this version (exclusive).
    Omitted / invalid since → return only the current version's section.
    since >= current → empty sections array (downgrade case).
    """
    current = current_app.config['VERSION_INFO'].get('version', 'unknown')
    since_raw = request.args.get('since', '').strip()
    since_tuple = _parse_version(since_raw)
    current_tuple = _parse_version(current)

    sections = _get_changelog_sections()

    if since_tuple is None:
        result = [s for s in sections if s['version'] == current]
    elif current_tuple is not None and since_tuple >= current_tuple:
        result = []
    else:
        result = [
            s for s in sections
            if _parse_version(s['version']) is not None
            and _parse_version(s['version']) > since_tuple
        ]

    return jsonify({'current': current, 'sections': result})


@dashboard_bp.route('/settings/widgets/<int:id>/attach', methods=['POST'])
@login_required
@is_admin_required
def attach_detached_widget(id):
    widget = Widget.detached().filter(Widget.id == id).first_or_404()
    entry = ServiceEntry.active().filter(
        ServiceEntry.id == request.form.get('entry_id', type=int),
        ServiceEntry.widget_id.is_(None),
    ).first()
    if not entry:
        flash("Pick an active service that has no widget.", "danger")
    else:
        entry.widget_id = widget.id
        db.session.commit()
        logger.info(f"Attached widget {widget.id} ('{widget.widget_name}') to '{entry.container_name}'.")
        flash(f"✅ Attached widget '{widget.widget_name}' to '{entry.container_name}'.", "success")
    return redirect(url_for('dashboard.settings', section='deleted'))


@dashboard_bp.route('/settings/widgets/<int:id>/delete', methods=['POST'])
@login_required
@is_admin_required
def delete_detached_widget(id):
    widget = Widget.detached().filter(Widget.id == id).first_or_404()
    name = widget.widget_name
    WidgetValue.query.filter_by(widget_id=widget.id).delete()
    db.session.delete(widget)
    db.session.commit()
    logger.info(f"Deleted detached widget {id} ('{name}').")
    flash(f"🗑️ Deleted detached widget '{name}'.", "success")
    return redirect(url_for('dashboard.settings', section='deleted'))
