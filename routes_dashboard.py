"""Dashboard, settings, and CRUD routes.

Owns the `dashboard` blueprint:
- Read-only dashboard views: /, /tiled_dash, /compact_dash
- Settings page: /settings (backup/restore, users list, groups, version)
- Group CRUD: /update_group, /add_group, /delete_group
- Service CRUD: /add, /edit/<id>, /dbdump
- Static assets: /images/<filename>

Grouping/sorting for the three dashboard views lives in
`view_helpers.group_and_sort_services`. The view controls
(`group_by` axis selector, `show_urlless` filter) are URL-driven
(`?group_by=stack&show_urlless=false`); each route here just parses
the query params and hands them to the helper.
"""

import logging
import os
from datetime import datetime
from urllib.parse import urlparse

import requests
import yaml
from flask import (
    Blueprint,
    current_app,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import login_required
from sqlalchemy.orm import joinedload, selectinload

import settings_store
import synthesizer
from extensions import db
from image_utils import fetch_icon_if_missing
from models import Group, ServiceEntry, ServiceExposure, User, Widget, WidgetValue
from routes_auth import is_admin_required
from view_helpers import (
    DEFAULT_SORT_IN_GROUP,
    group_and_sort_services,
    normalize_axis,
    normalize_show_urlless,
)

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


# Helper to check if flash messages are already present (to avoid duplicates)
# This is a basic check; Flask's get_flashed_messages usually clears them.
def flash_is_present(req):
    return '_flashes' in req.environ.get('flask._flashes', [])


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


@dashboard_bp.route('/')
@login_required
def dashboard():
    axis, show_urlless, sort_in_group = _read_view_controls()
    msg = request.args.get('msg')

    entries = (
        ServiceEntry.query
        .options(joinedload(ServiceEntry.group))
        .options(selectinload(ServiceEntry.exposures))
        .all()
    )

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
    )

    visible_total = sum(len(es) for _, es in grouped_entries)
    widget_values, widget_fields = _load_widget_values()

    return render_template(
        "dashboard.html",
        grouped_entries=grouped_entries,
        total_entries=visible_total,
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

    entries = (
        ServiceEntry.query
        .options(joinedload(ServiceEntry.group))
        .options(selectinload(ServiceEntry.exposures))
        .all()
    )

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
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
        widget_values=widget_values,
        widget_fields=widget_fields,
    )


@dashboard_bp.route('/compact_dash')
@login_required
def compact_dash():
    axis, show_urlless, sort_in_group = _read_view_controls(
        default_sort_in_group="alphabetical"
    )

    entries = (
        ServiceEntry.query
        .options(joinedload(ServiceEntry.group))
        .options(selectinload(ServiceEntry.exposures))
        .all()
    )

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
    )

    flattened_entries = []
    visible_total = 0
    for label, bucket_entries in grouped_entries:
        flattened_entries.append({'is_group_header': True, 'group': label})
        for entry in bucket_entries:
            flattened_entries.append({'is_group_header': False, 'entry': entry})
            visible_total += 1

    unique_hosts = {e.host for _, bucket in grouped_entries for e in bucket if e.host}
    show_host = len(unique_hosts) > 1

    return render_template(
        "compact_dash.html",
        flattened_entries=flattened_entries,
        total_entries=visible_total,
        show_host=show_host,
        group_by=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        active_tab="compact"
    )


@dashboard_bp.route("/dbdump")
@login_required
@is_admin_required
def db_dump():
    entries = ServiceEntry.query.order_by(ServiceEntry.id).all()
    return render_template("dbdump.html", entries=entries)


@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
@is_admin_required
def settings():
    BACKUP_DIR = current_app.config.get("backup_path", "/config/backups")
    BACKUP_PATH = os.path.join(BACKUP_DIR, "backup.yml")
    image_dir = current_app.config['IMAGE_DIR']
    os.makedirs(BACKUP_DIR, exist_ok=True)
    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()


    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'backup':
            backup_operation = request.form.get('backup_operation')

            # Backup is always for all entries now
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
                        # Basic security check: ensure filename doesn't try to escape BACKUP_DIR
                        if ".." in selected_filename or selected_filename.startswith("/"):
                            flash("Invalid server filename selected.", "danger")
                            return redirect(url_for('dashboard.settings'))

                        file_path = os.path.join(BACKUP_DIR, selected_filename)
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
                    if not item.get('host') or not item.get('container_name'):
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
                        host=item['host']
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
                        host=item['host']
                    ).first()

                    if not entry:
                        entry = ServiceEntry(host=item['host'], container_name=item['container_name'])
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
                        entry = ServiceEntry(host=item['host'], container_name=item['container_name'])
                        db.session.add(entry)
                    if widget_obj:
                        entry.widget_id = widget_obj.id

                    # Apply fields from backup item to DB entry
                    for field, value in item.items():
                        # Ensure 'is_static' is handled correctly based on the item from backup
                        if field == 'is_static':
                            if hasattr(entry, 'is_static'):
                                setattr(entry, 'is_static', item_is_static_from_backup)
                        elif hasattr(entry, field) and field not in ['id', 'last_updated', 'last_api_update', 'widget']:
                            setattr(entry, field, value)


                    # If 'is_static' wasn't in item.items() but we are creating, ensure it's set
                    # (especially if item_is_static_from_backup was derived from .get with a default)
                    if not entry.id and hasattr(entry, 'is_static'): # if it's a new entry being added
                         if 'is_static' not in item: # if 'is_static' was not explicitly in the backup item dict
                            setattr(entry, 'is_static', item_is_static_from_backup) # ensure it's set from .get default

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

    # GET request: List backup files for the restore dropdown
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
        all_entries = ServiceEntry.query.all()
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

    return render_template(
        'settings.html',
         current_config=current_app.config['LOADED_SETTINGS'],
         config_from_env=current_app.config['CONFIG_FROM_ENV'],
         config_from_file=current_app.config['CONFIG_FROM_FILE'],
         server_backup_files=server_backup_files,
         version_info=current_app.config['VERSION_INFO'],
         widgets=widgets,
         missing_icons=missing_icons,
         groups=groups,
         users=users,
         exposure_layers=exposure_layers,
         exposure_layer_directions=exposure_layer_directions,
         exposure_hosts=exposure_hosts,
         exposure_host_overrides=exposure_host_overrides,
    )


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


@dashboard_bp.route('/update_group', methods=['POST'])
@login_required
@is_admin_required
def update_group():
    group_id = request.form.get("group_id")
    group = Group.query.get(group_id)

    if group:
        group.group_name = request.form.get("group_name", group.group_name)
        group.group_icon = request.form.get("group_icon", group.group_icon)
        priority_val = request.form.get("group_sort_priority")
        group.group_sort_priority = int(priority_val) if priority_val and priority_val.isdigit() else None

        db.session.commit()
        flash(f"✅ Group {group.group_name} updated successfully.", "success")
    else:
        flash("❌ Group not found.", "danger")

    return redirect(url_for("dashboard.settings", section="groups"))


@dashboard_bp.route('/add_group', methods=['POST'])
@login_required
@is_admin_required
def add_group():
    name = request.form.get("group_name")
    icon = request.form.get("group_icon")
    priority = request.form.get("group_sort_priority")

    if not name:
        flash("❌ Group name is required.", "danger")
        return redirect(url_for("dashboard.settings", section="groups"))

    existing = Group.query.filter_by(group_name=name).first()
    if existing:
        flash("❌ Group with that name already exists.", "danger")
        return redirect(url_for("dashboard.settings", section="groups"))

    new_group = Group(
        group_name=name,
        group_icon=icon or None,
        group_sort_priority=int(priority) if priority and priority.isdigit() else None
    )

    db.session.add(new_group)
    db.session.commit()
    flash(f"✅ Group '{name}' created.", "success")
    return redirect(url_for("dashboard.settings", section="groups"))


@dashboard_bp.route('/delete_group', methods=['POST'])
@login_required
@is_admin_required
def delete_group():
    group_id = request.form.get('group_id')
    group = Group.query.get(group_id)

    if group:
        if len(group.services) == 0:
            db.session.delete(group)
            db.session.commit()
            flash(f"🗑️ Group '{group.group_name}' deleted successfully.", "success")
        else:
            flash("❌ Cannot delete group that has services.", "danger")
    else:
        flash("❌ Group not found.", "danger")

    return redirect(url_for('dashboard.settings', section='groups'))


@dashboard_bp.route('/images/<path:filename>')
@login_required
def serve_image(filename):
    response = make_response(send_from_directory(current_app.config['IMAGE_DIR'], filename))
    response.headers['Cache-Control'] = 'public, max-age=86400'  # cache for 1 day
    return response


@dashboard_bp.route('/add', methods=['GET', 'POST'])
@login_required
@is_admin_required
def add_entry():
    image_dir = current_app.config['IMAGE_DIR']
    raw_referrer = request.args.get('ref', '/')
    parsed = urlparse(raw_referrer)
    referrer = parsed.path
    if parsed.query:
        referrer += '?' + parsed.query
    if not referrer.startswith('/'):
        referrer = '/tiled_dash'

    if request.method == 'POST':
        host = request.form.get('host')
        container_name = request.form.get('application')
        internalurl = request.form.get('internal_url')
        externalurl = request.form.get('external_url')
        group_mode = request.form.get('group_mode')  # 'existing' or 'new'
        group_name = None

        if group_mode == 'existing':
            group_name = request.form.get('group_name_existing')
        elif group_mode == 'new':
            group_name = request.form.get('group_name_new')

        if not group_name:
            group_name = "None"


        image_icon_raw = request.form.get('icon_image', '').strip().lower()
        if image_icon_raw and not image_icon_raw.endswith('.svg'):
            image_icon = f"{image_icon_raw}.svg"
        else:
            image_icon = image_icon_raw

        if not host or not container_name:
            flash('Host and Application (Container Name) are required.', 'danger')
            return render_template("add_entry.html", msg='error', entry=request.form)

        # Check for duplicates
        existing = ServiceEntry.query.filter_by(host=host, container_name=container_name).first()
        if existing:
            flash(f"An entry for '{container_name}' on host '{host}' already exists.", 'danger')
            return render_template("add_entry.html", msg='duplicate', entry=request.form)

        # Booleans
        internal_health_check_enabled = request.form.get('internal_health_check') == 'on'
        external_health_check_enabled = request.form.get('external_health_check') == 'on'
        is_static = request.form.get('locked') == 'on'

        # === ICON RESOLUTION LOGIC ===
        if image_icon:
            icon_path = os.path.join(image_dir, image_icon)
            if not os.path.exists(icon_path):
                try:
                    icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{image_icon}"
                    response = requests.get(icon_url, timeout=5)
                    if response.status_code == 200:
                        with open(icon_path, 'wb') as f:
                            f.write(response.content)
                        logger.info(f"⬇️ Downloaded user-supplied icon '{image_icon}' for '{container_name}'")
                    else:
                        logger.warning(f"⚠️ Icon '{image_icon}' not found (HTTP {response.status_code})")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to fetch icon '{image_icon}': {e}")
        else:
            derived_icon_name = container_name.lower().replace(" ", "-")
            image_icon = fetch_icon_if_missing(derived_icon_name, image_dir, logger, debug=current_app.debug)
            if image_icon:
                logger.info(f"💡 Automatically fetched icon '{image_icon}' for new entry '{container_name}'.")
            else:
                logger.info(f"⚠️ Could not automatically fetch icon for '{container_name}'.")

        # Optional sort priority (must be an int if provided)
        sort_priority_raw = request.form.get('sort_priority', '').strip()
        sort_priority = None
        if sort_priority_raw:
            try:
                sort_priority = int(sort_priority_raw)
            except ValueError:
                flash("Sort priority must be a number.", 'danger')
                return render_template("add_entry.html", msg='error', entry=request.form, groups=groups)

        # === CREATE ENTRY ===
        # Look up or create group
        group_obj = Group.query.filter_by(group_name=group_name).first()
        if not group_obj:
            group_obj = Group(group_name=group_name)
            db.session.add(group_obj)
            db.session.flush()  # ensures group_obj.id is populated before use

        # Now create entry with group_id. URLs typed in the UI get
        # source=ui_edit so future register calls and the synthesizer
        # don't clobber them.
        entry = ServiceEntry(
            host=host,
            container_name=container_name,
            internalurl=internalurl or None,
            externalurl=externalurl or None,
            internalurl_source=synthesizer.SOURCE_UI_EDIT if internalurl else None,
            externalurl_source=synthesizer.SOURCE_UI_EDIT if externalurl else None,
            last_updated=datetime.now(),
            group_id=group_obj.id if group_obj else None,
            internal_health_check_enabled=internal_health_check_enabled,
            external_health_check_enabled=external_health_check_enabled,
            image_icon=image_icon,
            sort_priority=sort_priority,
            is_static=is_static
)

        db.session.add(entry)
        db.session.commit()

        flash(f"✅ Service entry '{container_name}' added successfully!", 'success')
        return redirect(url_for('dashboard.tiled_dashboard'))

    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
    return render_template("add_entry.html", msg='', entry={}, active_tab="add", groups=groups)


@dashboard_bp.route('/edit/<int:id>', methods=['GET', 'POST'])
@login_required
@is_admin_required
def edit_entry(id):
    image_dir = current_app.config['IMAGE_DIR']
    entry = ServiceEntry.query.get_or_404(id)

    # Track the referrer for redirecting after save
    raw_referrer = request.args.get('ref', '/')
    parsed = urlparse(raw_referrer)
    referrer = parsed.path
    if parsed.query:
        referrer += '?' + parsed.query
    if not referrer.startswith('/'):
        referrer = '/'

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

    # Handle form submission
    if request.method == 'POST':
        # === DELETE ACTION ===
        if 'delete' in request.form:
            if request.form.get('delete_confirmation') == entry.container_name:


                # Delete the associated widget if no other services use it
                if entry.widget_id:
                    other_services = ServiceEntry.query.filter(
                        ServiceEntry.widget_id == entry.widget_id,
                        ServiceEntry.id != entry.id
                    ).count()

                    if other_services == 0:
                        WidgetValue.query.filter_by(widget_id=entry.widget_id).delete()
                        Widget.query.filter_by(id=entry.widget_id).delete()

                db.session.delete(entry)
                db.session.commit()
                flash(f"Deleted entry: {entry.container_name}", 'success')
                return redirect(referrer)
            else:
                flash("Confirmation name does not match. Entry not deleted.", "warning")
                return redirect(url_for('dashboard.edit_entry', id=id, ref=referrer))

        # === BASIC FIELDS ===
        entry.host = request.form.get('host', '').strip()
        entry.container_name = request.form.get('container_name', '').strip()

        # URL provenance: setting a URL via UI marks it ui_edit (highest
        # precedence, the synthesizer won't touch it). Clearing the URL
        # resets source to null so synthesis can re-fill on the next
        # register. See synthesizer.py for the ordering rules.
        new_internalurl = request.form.get('internalurl', '').strip() or None
        new_externalurl = request.form.get('externalurl', '').strip() or None
        if new_internalurl != entry.internalurl:
            entry.internalurl = new_internalurl
            entry.internalurl_source = synthesizer.SOURCE_UI_EDIT if new_internalurl else None
        if new_externalurl != entry.externalurl:
            entry.externalurl = new_externalurl
            entry.externalurl_source = synthesizer.SOURCE_UI_EDIT if new_externalurl else None

        entry.internal_health_check_enabled = 'internal_health_check_enabled' in request.form
        entry.external_health_check_enabled = 'external_health_check_enabled' in request.form
        entry.is_static = 'is_static' in request.form

        sort_priority_raw = request.form.get('sort_priority', '').strip()
        try:
            entry.sort_priority = int(sort_priority_raw) if sort_priority_raw else None
        except ValueError:
            entry.sort_priority = None
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
        raw_icon = request.form.get('image_icon', '').strip().lower()
        entry.image_icon = f"{raw_icon}.svg" if raw_icon and not raw_icon.endswith('.svg') else raw_icon
        icon_path = os.path.join(image_dir, entry.image_icon) if entry.image_icon else ''
        if entry.image_icon and not os.path.exists(icon_path):
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

        return redirect(referrer)

    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()
    return render_template("edit_entry.html",
                           entry=entry,
                           ref=referrer,
                           groups=groups,
                           available_widgets=available_widgets,
                           selected_widget=selected_widget)
