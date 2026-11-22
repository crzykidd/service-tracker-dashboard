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
from flask import (
    Blueprint,
    Response,
    abort,
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
import backups
import check_form
import entry_rules
import export_format
import health_history
import image_tags
import image_update
import jobs
import mgmt_serializers
import notify
import ports
import restore_staging
import settings_sections
import settings_store
import streams
import synthesizer
import version_check
from extensions import db
from image_update_ui import image_updates_enabled
from image_utils import fetch_icon_if_missing, icon_path_in_dir, safe_icon_filename
from models import (
    NAME_SOURCE_UI_EDIT,
    SOURCE_MANUAL,
    SOURCE_NOTIFIER,
    ApiAudit,
    ApiKey,
    Group,
    InventoryBlock,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    StreamLinkOffer,
    User,
    Widget,
    WidgetValue,
    check_counts,
    ensure_url_checks,
    hard_delete_entry,
)
from notify_purge import PurgeError
from routes_auth import is_admin_required
from view_helpers import (
    DEFAULT_SORT_IN_GROUP,
    group_and_sort_services,
    health_counts,
    host_label_ids,
    normalize_axis,
    normalize_show_urlless,
    normalize_source_filter,
    normalize_status_filter,
    normalize_updates_filter,
    safe_redirect_target,
    updates_count,
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


def _read_updates_filter():
    """The `?updates=1` filter. Ignored while the image update check is switched off: the
    toggle is hidden then, and stored results must not filter the views."""
    return image_updates_enabled() and normalize_updates_filter(request.args.get("updates"))


def _image_update_filter_context(entries, show_urlless, source, status, updates):
    """Filter bar context for the Updates toggle (hidden while the check is off)."""
    enabled = image_updates_enabled()
    return {
        "image_updates_on": enabled,
        "updates_filter": updates,
        "updates_available": updates_count(entries, show_urlless, source, status) if enabled else 0,
    }


def _health_count_context(entries, show_urlless, source, status):
    """Counts and server-built chip links for the filter bar. Each link
    keeps every other current query param and swaps only `status`."""
    counts = health_counts(entries, show_urlless=show_urlless, source=source)
    base = request.args.to_dict()
    links = {}
    for key, value in (("total", "all"), ("passing", "healthy"), ("failing", "failing")):
        links[key] = url_for(request.endpoint, **{**base, "status": value})
    active = {"all": "total", "healthy": "passing", "failing": "failing"}.get(status)
    return {"health_counts": counts, "health_links": links, "health_active": active,
            "source_streams": InventoryStream.query.order_by(InventoryStream.display_name).all()}


def _load_view_entries():
    """Active entries for a dashboard view, with everything the templates
    touch eager-loaded so the page costs a fixed number of queries."""
    return (
        ServiceEntry.active()
        .options(joinedload(ServiceEntry.group))
        .options(joinedload(ServiceEntry.stream))
        .options(selectinload(ServiceEntry.exposures))
        .options(selectinload(ServiceEntry.checks))
        .options(selectinload(ServiceEntry.image_reference))
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
    updates = _read_updates_filter()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
        updates=updates,
    )

    visible_total = sum(len(es) for _, es in grouped_entries)
    widget_values, widget_fields = _load_widget_values()

    return render_template(
        "dashboard.html",
        grouped_entries=grouped_entries,
        total_entries=visible_total,
        all_entries_count=len(entries),
        **_health_count_context(entries, show_urlless, source, status),
        **_image_update_filter_context(entries, show_urlless, source, status, updates),
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
    updates = _read_updates_filter()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
        updates=updates,
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
        **_image_update_filter_context(entries, show_urlless, source, status, updates),
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
    updates = _read_updates_filter()

    grouped_entries = group_and_sort_services(
        entries,
        axis=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        status=status,
        source=source,
        updates=updates,
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
        **_image_update_filter_context(entries, show_urlless, source, status, updates),
        status_filter=status,
        source_filter=source,
        host_label_ids=_host_label_ids(entries),
        group_by=axis,
        show_urlless=show_urlless,
        sort_in_group=sort_in_group,
        active_tab="compact"
    )


@dashboard_bp.route('/ports')
@login_required
def ports_page():
    """Ports in use across all hosts (PRD 25). One query; unknown params fall back."""
    args = request.args
    view = args.get('view') if args.get('view') in ('grouped', 'flat') else 'grouped'
    kind = ports.normalize_kind(args.get('kind'))
    sort = ports.normalize_sort(args.get('sort'))
    host = (args.get('host') or '').strip() or None
    q = (args.get('q') or '').strip()
    conflicts_only = (args.get('conflicts') or '').strip().lower() in ('1', 'true', 'yes', 'on')

    all_rows = ports.build_rows(ServiceEntry.active().all())
    summary = ports.summarize(all_rows)
    hosts = sorted({r['host'] for r in all_rows if r['host']}, key=str.lower)
    if host not in hosts:
        host = None
    rows = ports.filter_rows(all_rows, kind=kind, host=host, q=q, conflicts_only=conflicts_only)
    by_id = {r['entry_id']: r['name'] for r in all_rows}

    return render_template(
        'ports.html',
        view=view, kind=kind, sort=sort, host=host, q=q, conflicts_only=conflicts_only,
        hosts=hosts, summary=summary, total_rows=len(all_rows), visible=len(rows),
        grouped=ports.group_by_host(rows) if view == 'grouped' else [],
        flat=ports.sort_rows(rows, sort) if view == 'flat' else [],
        names=by_id,
        active_tab='ports',
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


@dashboard_bp.route('/settings', methods=['GET'])
@login_required
@is_admin_required
def settings():
    # The old backup / restore branches (a POST with `action=backup|restore`) were removed
    # in 0.11.0: export and import (routes_import.py) replace them.
    return _render_settings()


def _settings_redirect(section, **params):
    """Redirect to a Settings section (`?section=<slug>`). Every redirect to Settings
    goes through here so the page lands on, and places its flashes in, that section."""
    return redirect(url_for('dashboard.settings', section=section, **params))


def _initial_section(section=None):
    """Which Settings section the server says to open (design 5.2): an explicit
    `section` (a validation re-render) > `?section=` (slug or legacy alias) >
    `streams` when `?preview=` is present > `audit-log` when `?audit_key=` is present > ''."""
    explicit = settings_sections.resolve(section)
    if explicit:
        return explicit
    from_query = settings_sections.resolve(request.args.get('section'))
    if from_query:
        return from_query
    if request.args.get('preview'):
        return 'streams'
    if request.args.get('audit_key'):
        return 'audit-log'
    return ''


def _ha_context(channels):
    """Template variables for Settings -> Home Assistant (design 9.7): the entries grouped
    by source (Docker, Manual, then one group per stream by display name; empty groups
    omitted; rows sorted by name then host), the channels that publish discovery and the
    saved published count. A disabled channel publishes nothing, so `ha_discovery_live`
    counts enabled ones only."""
    entries = ServiceEntry.active().options(
        joinedload(ServiceEntry.stream), joinedload(ServiceEntry.group)).all()
    entries.sort(key=lambda e: ((e.container_name or '').lower(), (e.host or '').lower()))
    docker, manual, streams = [], [], {}
    for e in entries:
        if e.is_stream:
            sid = e.stream.stream_id if e.stream else (e.stream_id or '')
            label = e.stream.display_name if e.stream else 'Stream'
            streams.setdefault(sid, {'key': f'stream:{sid}', 'label': label, 'entries': []})['entries'].append(e)
        elif e.is_docker:
            docker.append(e)
        else:
            manual.append(e)
    groups = [{'key': 'docker', 'label': 'Docker', 'entries': docker},
              {'key': 'manual', 'label': 'Manual', 'entries': manual}]
    groups += sorted(streams.values(), key=lambda g: g['label'].lower())
    groups = [g for g in groups if g['entries']]
    ha_channels = [{'name': c['name'], 'enabled': c['enabled'],
                    'prefix': c['config'].get('ha_prefix') or 'homeassistant',
                    'device_prefix': c['config'].get('ha_device_prefix') or 'STD'}
                   for c in channels if c['config'].get('ha_discovery')]
    published = sum(1 for e in entries if e.ha_publish)
    live = any(c['enabled'] for c in ha_channels)
    return {'ha_groups': groups, 'ha_channels': ha_channels, 'ha_published': published,
            'ha_total': len(entries), 'ha_discovery_live': live,
            'ha_needs_channel': bool(published) and not live}


def _render_settings(*, section=None, open_modal=None, forms=None, status=200, **extra):
    """Render the Settings page. `forms['group']` (a failed Groups save) is shown in
    place of the stored groups, with its per-row errors, on the Groups section;
    `forms['notification']` keeps a failed channel save's typed values;
    `forms['stream:<slug>:<block>']` those of a failed Edit stream block. `section` and
    `open_modal` say where a validation re-render lands (design 5.2)."""
    forms = forms or {}
    group_form = forms.get('group')
    notification_form = forms.get('notification')
    backup_form = forms.get('backup')
    BACKUP_DIR = backups.backup_dir(current_app)
    image_dir = current_app.config['IMAGE_DIR']
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
    except OSError:
        logger.warning("Could not create the backup folder %s", BACKUP_DIR)
    groups = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc()).all()

    if group_form:
        group_rows = group_form['rows']
    else:
        group_rows = [{'id': g.id, 'name': g.group_name, 'icon': g.group_icon or '',
                       'priority': '' if g.group_sort_priority is None else g.group_sort_priority,
                       'services_count': g.services_count, 'delete': False} for g in groups]

    backup_list_error = None
    try:
        backup_files = backups.list_files(BACKUP_DIR)
    except OSError as e:
        backup_files = {'snapshots': [], 'exports': []}
        backup_list_error = f"Could not read the backup folder {BACKUP_DIR}: {e.strerror or e}."
    backup_runs = backups.last_runs()
    backup_next = {k: (v.strftime('%Y-%m-%d %H:%M') if v else None)
                   for k, v in jobs.next_run_times().items()}

    # Check which icon files are missing
    missing_icons = []
    for entry in ServiceEntry.active().all():
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

    stream_ctx = _streams_context(request.args.get('preview'))
    if stream_ctx['preview'] and not open_modal:
        open_modal = 'stream-preview-modal'
    initial_section = _initial_section(section)
    notification_channels_out = [mgmt_serializers.notification_channel_out(c) for c in
                                 NotificationChannel.query.order_by(NotificationChannel.id).all()]
    ha = _ha_context(notification_channels_out)
    image_update_ctx = _image_update_settings_context()
    return render_template(
        'settings.html',
         current_config=current_app.config['LOADED_SETTINGS'],
         config_from_env=current_app.config['CONFIG_FROM_ENV'],
         config_from_file=current_app.config['CONFIG_FROM_FILE'],
         backup_settings=backups.effective_settings(current_app),
         backup_form=backup_form,
         backup_files=backup_files,
         backup_last_runs=backup_runs,
         backup_next_runs=backup_next,
         backup_list_error=backup_list_error,
         backup_outside_config=backups.outside_config(BACKUP_DIR),
         backup_attention=backups.attention_needed(backup_runs),
         restore_pending=restore_staging.pending(),
         restore_result=restore_staging.last_result(),
         version_info=current_app.config['VERSION_INFO'],
         version_display=version_check.display_info(current_app.config['VERSION_INFO']),
         update_status=version_check.status(current_app.config['VERSION_INFO'].get('version', 'unknown')),
         widgets=widgets,
         missing_icons=missing_icons,
         groups=groups,
         group_form=group_form,
         group_rows=group_rows,
         initial_section=initial_section,
         open_modal=open_modal or '',
         flash_target=open_modal or initial_section or 'page',
         settings_groups=settings_sections.GROUPS,
         settings_sections=settings_sections.SECTIONS,
         settings_default_section=settings_sections.DEFAULT,
         settings_aliases=settings_sections.ALIASES,
         **stream_ctx,
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
         notification_channels=notification_channels_out,
         notification_form=notification_form,
         stream_forms={k: v for k, v in forms.items() if k.startswith('stream:')},
         **ha,
         **image_update_ctx,
         notifications_enabled=any(c['enabled'] for c in notification_channels_out),
         exposure_layers=exposure_layers,
         exposure_layer_directions=exposure_layer_directions,
         exposure_hosts=exposure_hosts,
         exposure_host_overrides=exposure_host_overrides,
         **extra,
    ), status


def render_settings_for(**kwargs):
    """Public wrapper over `_render_settings` for other route modules (routes_auth re-renders
    Settings with a dialog open). Returns `(html, status)`; imported lazily there because
    this module imports routes_auth."""
    return _render_settings(**kwargs)


# --- Settings -> Notifications (PRD 17.2) -----------------------------------------


def _notification_form_data(form):
    """Read the channel form: `(name, enabled, config, secret_op)` where
    `secret_op` is `notify.UNSET` (keep), None (clear) or the new password."""
    def text(key):
        return (form.get(key) or '').strip()

    def number(key):
        raw = text(key)
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return raw          # left as text so validation reports it

    config = {
        'host': text('host'),
        'port': number('port'),
        'tls': form.get('tls') == '1',
        'tls_insecure': form.get('tls_insecure') == '1',
        'username': text('username') or None,
        'client_id': text('client_id') or None,
        'base_topic': text('base_topic') or 'std',
        'qos': number('qos') if text('qos') else 1,
        'keepalive': number('keepalive') if text('keepalive') else 60,
        'ha_discovery': form.get('ha_discovery') == '1',
        'ha_prefix': text('ha_prefix') or 'homeassistant',
        'ha_device_prefix': text('ha_device_prefix') or 'STD',
    }
    password = form.get('password') or ''
    if form.get('clear_password') == '1':
        secret = None
    elif password:
        secret = password
    else:
        secret = notify.UNSET
    return text('name'), form.get('enabled') == '1', config, secret


@dashboard_bp.route('/settings/notifications/save', methods=['POST'])
@login_required
@is_admin_required
def save_notification_channel():
    """Create (no `channel_id`) or update an MQTT channel. A blank password keeps
    the stored one; the clear box removes it. The password never leaves the server.

    On an update that changes the base topic (or the discovery prefix / device prefix
    with discovery on), `cleanup_old_base` clears what the old values left on the
    broker first (PRD 17.5); when the broker can't be reached nothing is saved and the
    form comes back so the operator can untick it."""
    name, enabled, config, secret = _notification_form_data(request.form)
    raw_id = (request.form.get('channel_id') or '').strip()
    cleanup_failed = False
    if raw_id:
        channel = db.get_or_404(NotificationChannel, int(raw_id) if raw_id.isdigit() else 0)
        try:
            _, errors = notify.update_channel(
                channel, name=name, enabled=enabled, config=config, secret=secret,
                cleanup_old_base=request.form.get('cleanup_old_base') == '1')
        except PurgeError as exc:
            cleanup_failed = True
            errors = [{'field': 'cleanup', 'message': f"{exc.message} Nothing was saved: untick "
                       "\"Remove the old topics from the broker\" to save anyway."}]
    else:
        channel, errors = notify.create_channel(name, 'mqtt', enabled, config,
                                                None if secret is notify.UNSET else secret)
    if errors:
        for e in errors:
            flash(f"Notification channel: {e['field']} {e['message']}", "danger")
        form = {'id': raw_id, 'name': name, 'enabled': enabled, **config}
        error_fields = sorted({e['field'].removeprefix('config.') for e in errors})
        return _render_settings(section='notifications', open_modal='channel-modal',
                                forms={'notification': form}, notification_error_fields=error_fields,
                                status=409 if cleanup_failed else 400)
    logger.info(f"Notification channel '{channel.name}' saved by {current_user.username}.")
    flash(f"✅ Notification channel '{channel.name}' saved.", "success")
    return _settings_redirect('notifications')


@dashboard_bp.route('/settings/notifications/ha-entries', methods=['POST'])
@login_required
@is_admin_required
def save_ha_entries():
    """Apply the Home Assistant entries picker in one commit (so one sync).

    `ha_entry_ids` lists every row the operator saw; `ha_publish` the ticked
    ones. Rows not listed (an entry added since the page loaded) are left alone."""
    def ids(name):
        return {int(v) for v in request.form.getlist(name) if v.isdigit()}
    seen, ticked = ids('ha_entry_ids'), ids('ha_publish')
    changed = 0
    for entry in ServiceEntry.active().filter(ServiceEntry.id.in_(seen)).all():
        want = entry.id in ticked
        if bool(entry.ha_publish) != want:
            entry.ha_publish = want
            changed += 1
    db.session.commit()
    logger.info(f"Home Assistant entries saved by {current_user.username} ({changed} changed).")
    flash(f"✅ Home Assistant entries saved ({changed} changed).", "success")
    return _settings_redirect('home-assistant')


def _wants_json():
    return request.accept_mimetypes.best_match(['application/json', 'text/html']) == 'application/json'


def _channel_action_result(call, success):
    """Run a channel change that may clean the broker first. JSON for the Settings
    dialog (which then reloads to show the flash); a flash and a redirect otherwise."""
    try:
        message = success(call())
    except PurgeError as exc:
        if _wants_json():
            return jsonify({'ok': False, 'message': exc.message}), exc.status
        flash(exc.message, 'danger')
        return _settings_redirect('notifications')
    flash(message, 'success')
    if _wants_json():
        return jsonify({'ok': True, 'message': message})
    return _settings_redirect('notifications')


@dashboard_bp.route('/settings/notifications/<int:id>/toggle', methods=['POST'])
@login_required
@is_admin_required
def toggle_notification_channel(id):
    """Enable or disable a channel. Disabling can first remove the channel's data from
    its broker (`cleanup=1`, off by default)."""
    channel = db.get_or_404(NotificationChannel, id)
    cleanup = request.form.get('cleanup') == '1'
    return _channel_action_result(
        lambda: notify.update_channel(channel, enabled=not channel.enabled, cleanup_disable=cleanup),
        lambda _r: f"Notification channel '{channel.name}' {'enabled' if channel.enabled else 'disabled'}"
                   f"{' and removed from the broker' if cleanup and not channel.enabled else ''}.")


@dashboard_bp.route('/settings/notifications/<int:id>/delete', methods=['POST'])
@login_required
@is_admin_required
def delete_notification_channel(id):
    """Delete a channel. `cleanup=1` (the dialog's default) removes its retained topics,
    discovery configs and status first; when the broker can't be reached nothing is
    deleted and the dialog offers "Delete anyway" (`cleanup=0`)."""
    channel = db.get_or_404(NotificationChannel, id)
    name = channel.name
    cleanup = request.form.get('cleanup') == '1'

    def done(cleared):
        extra = (f" and removed {cleared['topics_cleared']} topics from the broker" if cleared else '')
        return f"Deleted notification channel '{name}'{extra}."
    return _channel_action_result(lambda: notify.delete_channel(channel, cleanup=cleanup), done)


@dashboard_bp.route('/settings/notifications/test', methods=['POST'])
@login_required
@is_admin_required
def test_notification_channel_form():
    """Send a test message with the submitted (possibly unsaved) values.
    A blank password on a saved channel tests with the stored one."""
    _, _, config, secret = _notification_form_data(request.form)
    if secret is notify.UNSET:
        raw_id = (request.form.get('channel_id') or '').strip()
        stored = db.session.get(NotificationChannel, int(raw_id)) if raw_id.isdigit() else None
        secret = stored.secret if stored else None
    ok, message = notify.test_channel('mqtt', config, secret)
    return jsonify({'ok': ok, 'message': message})


def _purge_response(call, *args):
    try:
        result = call(*args)
    except PurgeError as exc:
        return jsonify({'ok': False, 'message': exc.message}), exc.status
    return jsonify({'ok': True, **result})


@dashboard_bp.route('/settings/notifications/<int:id>/purge', methods=['POST'])
@login_required
@is_admin_required
def purge_notification_channel(id):
    """Clear every retained STD topic and discovery config on a channel's broker.
    The Notifications tab posts this with fetch and shows the counts inline."""
    channel = db.get_or_404(NotificationChannel, id)
    republish = request.form.get('republish', '') not in ('', '0', 'false')
    return _purge_response(notify.purge_channel, channel.id, republish)


@dashboard_bp.route('/settings/notifications/<int:id>/orphans/scan', methods=['POST'])
@login_required
@is_admin_required
def scan_notification_orphans(id):
    """List the retained STD topics nothing desires any more (nothing is cleared)."""
    channel = db.get_or_404(NotificationChannel, id)
    return _purge_response(notify.scan_orphans, channel.id,
                           (request.form.get('extra_base') or '').strip() or None)


@dashboard_bp.route('/settings/notifications/<int:id>/orphans/clear', methods=['POST'])
@login_required
@is_admin_required
def clear_notification_orphans(id):
    """Clear the listed orphans (`topic` fields from the scan)."""
    channel = db.get_or_404(NotificationChannel, id)
    return _purge_response(notify.clear_orphans, channel.id, request.form.getlist('topic'),
                           (request.form.get('extra_base') or '').strip() or None)


@dashboard_bp.route('/edit/<int:id>/purge-notifications', methods=['POST'])
@login_required
@is_admin_required
def purge_entry_notifications(id):
    """Purge this entry's MQTT topics and Home Assistant device, then republish it."""
    entry = db.get_or_404(ServiceEntry, id)
    return _purge_response(notify.purge_entry, entry.id)


@dashboard_bp.route('/settings/notifications/status', methods=['GET'])
@login_required
@is_admin_required
def notification_status():
    """Live connection status per channel id, polled by the Notifications tab."""
    return jsonify({str(c.id): notify.channel_status(c) for c in NotificationChannel.query.all()})


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
    return _settings_redirect('docker')


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
        return _settings_redirect('about')
    settings_store.save_update_check_settings(enabled, hours)
    db.session.commit()
    version_check.reset()  # re-read the cache/interval; the next page load may refetch
    flash("✅ Update check settings saved.", "success")
    return _settings_redirect('about')


# --- Settings -> Backup & restore (design 4) -----------------------------------------------


def _backup_form_values(form):
    """The backup settings form as `{setting key: submitted value}`; an unchecked switch
    is False."""
    values = {'path': form.get('path', '')}
    for kind in backups.KINDS:
        values[f'{kind}_enabled'] = form.get(f'{kind}_enabled') == '1'
        values[f'{kind}_time'] = form.get(f'{kind}_time', '')
        values[f'{kind}_keep_days'] = form.get(f'{kind}_keep_days', '')
    values['export_format'] = form.get('export_format', '')
    return values


@dashboard_bp.route('/settings/backups/settings', methods=['POST'])
@login_required
@is_admin_required
def save_backup_settings():
    """Save the backup folder and the two daily jobs' settings, then reschedule. A
    validation error re-renders the section (400) with what was typed."""
    values = _backup_form_values(request.form)
    old_path = backups.backup_dir(current_app)
    errors, warnings = backups.save_settings(current_app, values)
    if errors:
        db.session.rollback()
        flash("Nothing was saved. " + " ".join(errors.values()), "danger")
        return _render_settings(section='backup', status=400,
                                forms={'backup': {'values': values, 'errors': errors}})
    db.session.commit()
    jobs.reschedule_backups(current_app)
    for message in warnings:
        flash(message, "warning")
    message = "Backup settings saved. Schedules updated."
    if backups.backup_dir(current_app) != old_path:
        message += " Existing backups stay in the old folder."
    flash(message, "success")
    return _settings_redirect('backup')


@dashboard_bp.route('/settings/backups/settings/reset', methods=['POST'])
@login_required
@is_admin_required
def reset_backup_setting():
    """Delete one saved backup setting so it falls back to settings.yml or the default."""
    key = request.form.get('key', '')
    if not backups.reset(key):
        db.session.rollback()
        flash("Unknown backup setting.", "danger")
        return _settings_redirect('backup')
    db.session.commit()
    jobs.reschedule_backups(current_app)
    flash("Setting reset to its default.", "success")
    return _settings_redirect('backup')


@dashboard_bp.route('/settings/backups/run', methods=['POST'])
@login_required
@is_admin_required
def run_backup_now():
    """Run a snapshot or an export now (synchronously)."""
    kind = request.form.get('kind', '')
    if kind not in backups.KINDS:
        flash("Unknown backup kind.", "danger")
        return _settings_redirect('backup')
    result = backups.run_snapshot(current_app, 'manual') if kind == 'snapshot' \
        else backups.run_export(current_app, 'manual')
    label = kind.capitalize()
    if result['ok']:
        flash(f"{label} saved: {result['file']}, {backups.human_size(result['size'])}", "success")
    else:
        flash(f"{label} failed: {result['error']}", "danger")
    return _settings_redirect('backup')


@dashboard_bp.route('/settings/backups/export', methods=['GET'])
@login_required
@is_admin_required
def download_export():
    """Download the export of operator-set state now (format v1, never any secret).
    `?format=yaml` (default) or `json`; nothing is written to the backup folder."""
    fmt = (request.args.get('format') or 'yaml').strip().lower()
    if fmt not in ('yaml', 'json'):
        abort(400)
    data = export_format.dump(export_format.build_export(), fmt)
    ext, mimetype = ('yml', 'application/yaml') if fmt == 'yaml' else ('json', 'application/json')
    name = f"std_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{ext}"
    resp = Response(data, mimetype=mimetype)
    resp.headers['Content-Disposition'] = f'attachment; filename="{name}"'
    resp.headers['Cache-Control'] = 'no-store'
    return resp


@dashboard_bp.route('/settings/backups/<name>/download', methods=['GET'])
@login_required
@is_admin_required
def download_backup_file(name):
    path = backups.resolve_file(name)
    if path is None:
        abort(404)
    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


@dashboard_bp.route('/settings/backups/<name>/delete', methods=['POST'])
@login_required
@is_admin_required
def delete_backup_file(name):
    path = backups.resolve_file(name)
    if path is None:
        abort(404)
    try:
        os.remove(path)
    except OSError as e:
        flash(f"Could not delete {name}: {e.strerror or e}", "danger")
        return _settings_redirect('backup')
    logger.info("Backup file deleted from Settings: %s", name)
    flash(f"Deleted {name}.", "success")
    return _settings_redirect('backup')


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
        # Open the staging dialog on the first row with a message (design 9.3); a stale
        # table has no row to edit, so its banner stays in the Groups section.
        first = next((r['id'] for r in rows if r['id'] in errors), 'new' if 'new' in errors else None)
        if first is not None:
            return _render_settings(section='groups', forms={'group': group_form}, status=400,
                                    open_modal='group-modal', group_modal_id=first)
        return _render_settings(section='groups', forms={'group': group_form}, status=400)

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
        return _settings_redirect('groups')

    parts = [f'{n} {label}' for n, label in ((updated, 'updated'), (added, 'added'), (deleted, 'deleted')) if n]
    flash(f"✅ Saved: {', '.join(parts)}." if parts else "No changes.", "success")
    return _settings_redirect('groups')


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
        image_repo_url = (request.form.get('image_repo_url') or '').strip() or None
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

        repo_errors = entry_rules.validate_image_repo_url('image_repo_url', image_repo_url)
        if repo_errors:
            flash(f"Image repo URL: {repo_errors[0]['message'].split(' ', 1)[1]}.", 'danger')
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
            image_repo_url=image_repo_url,
            sort_priority=sort_priority,
            is_static=is_static,
            ha_publish='ha_publish' in request.form,
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
        selected_widget = db.session.get(Widget, entry.widget_id)
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
                               container_row=container_row,
                               **_edit_stream_context(entry),
                               **_image_update_edit_context(entry),
                               notifications_enabled=NotificationChannel.query.filter_by(
                                   enabled=True).first() is not None)

    # Handle form submission
    if request.method == 'POST':
        # === DELETE ACTION ===
        if 'delete' in request.form:
            if request.form.get('delete_confirmation') == entry.container_name:


                # Soft delete: recoverable from Settings -> Deleted. The widget
                # stays attached; nothing else is removed. "Don't re-add" (stream
                # entries) also blocks the key.
                streams.soft_delete_entry(
                    entry, _truthy(request.form.get('block')) and entry.stream_id is not None,
                    actor=current_user.username)
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

        # === IMAGE REPO URL: validate first, change nothing on error ===
        new_repo_url = request.form.get('image_repo_url', '').strip() or None
        repo_errors = entry_rules.validate_image_repo_url('image_repo_url', new_repo_url)
        if repo_errors:
            flash(f"Image repo URL: {repo_errors[0]['message'].split(' ', 1)[1]}.", 'danger')
            return render_edit(form=request.form)

        # === IMAGE UPDATES: validate first, change nothing on error ===
        image_update_values = None
        if entry.is_docker and 'image_update_form' in request.form:
            image_update_values, iu_errors = _parse_image_update_form(request.form)
            if iu_errors:
                for message in iu_errors:
                    flash(message, 'danger')
                return render_edit(form=request.form)

        # === BASIC FIELDS ===
        new_host = request.form.get('host', '').strip()
        if not entry.is_docker:
            # Host is optional for manual entries (stream entries never have one).
            entry.host = None if entry.is_stream else (new_host or None)
            if 'description' in request.form:
                entry.description = request.form.get('description', '').strip()[:255] or None
        else:
            entry.host = new_host
        new_name = request.form.get('container_name', '').strip()
        if entry.is_stream and new_name and new_name != entry.container_name:
            entry.name_source = NAME_SOURCE_UI_EDIT     # snapshots no longer write the name
        entry.container_name = new_name
        if 'image_repo_url' in request.form:
            entry.image_repo_url = new_repo_url

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
        if 'ha_form' in request.form:
            entry.ha_publish = 'ha_publish' in request.form
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
                group = db.session.get(Group, int(group_id))  # safely cast to int

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
                widget = db.session.get(Widget, entry.widget_id)
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

        if image_update_values is not None:
            entry.image_update_policy, entry.image_update_scope, entry.image_tag_pattern = image_update_values
            image_update.recompute_entry(entry)      # from the stored reference row: no network

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


# --- Image updates (PRD 24): entry edit block, Check now, Settings section -----------------

_POLICY_LABELS = (('auto', 'Auto'), ('tags', 'Newer tags'), ('digest', 'Digest'), ('off', 'Off'))
_SCOPE_LABELS = (('', 'Default'), ('any', 'Any'), ('minor', 'Same major'), ('patch', 'Same minor'))


def _parse_image_update_form(form):
    """`((policy, scope, pattern), errors)` from the entry edit block. The tag pattern is
    checked with the same validator as the management API."""
    errors = []
    policy = (form.get('image_update_policy') or 'auto').strip().lower()
    if policy not in image_tags.POLICIES:
        errors.append("Image update policy must be one of: " + ", ".join(image_tags.POLICIES) + ".")
    scope = (form.get('image_update_scope') or '').strip().lower() or None
    if scope is not None and scope not in image_tags.SCOPES:
        errors.append("Image update scope must be Default, Any, Same major or Same minor.")
    pattern = (form.get('image_tag_pattern') or '').strip() or None
    problem = image_tags.validate_tag_pattern(pattern)
    if problem:
        errors.append(f"Image tag pattern: {problem}")
    return (policy, scope, pattern), errors


def _image_update_edit_context(entry):
    """Edit page context for the Image updates block (Docker entries only): the choices and
    the "matches" preview from the candidates stored at the last check (no registry call)."""
    if not entry.is_docker:
        return {'image_update_edit': None}
    row = entry.image_reference if entry.image_ref else None
    candidates = (row.candidates or {}) if row else {}
    pattern = entry.image_tag_pattern or None
    if pattern:
        pool = (candidates.get('patterns') or {}).get(pattern)
    else:
        pool = candidates.get('tags') if row and row.checked_at else None
    return {'image_update_edit': {
        'policies': _POLICY_LABELS, 'scopes': _SCOPE_LABELS,
        'default_scope': image_update.default_scope(),
        'enabled': image_updates_enabled(),
        'matches': list(reversed(pool))[:10] if pool else [],
        'matches_known': pool is not None,
        'can_check': bool(entry.image_ref),
    }}


def _check_now_json(entry=None):
    """Run Check now (throttled, never blocks) and answer JSON for the page script."""
    try:
        queued = image_update.request_check(current_app._get_current_object(), entry)
    except image_update.CheckRequestError as exc:
        message = exc.message
        if exc.status == 429 and exc.retry_after:
            message = f"Checked recently; try again in about {max(1, -(-exc.retry_after // 60))} min."
        response = jsonify({'ok': False, 'message': message, 'retry_after': exc.retry_after})
        response.status_code = exc.status
        if exc.retry_after:
            response.headers['Retry-After'] = str(exc.retry_after)
        return response
    what = 'this image' if entry is not None else f"{queued} image{'s' if queued != 1 else ''}"
    response = jsonify({'ok': True, 'queued': queued,
                        'message': f"Checking {what} now; the result shows here when the check ends."})
    response.status_code = 202
    return response


@dashboard_bp.route('/service/<int:id>/image-update/check', methods=['POST'])
@login_required
@is_admin_required
def check_image_update_now(id):
    """Per-entry Check now (throttled per reference). A request, not a registry call here."""
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()
    return _check_now_json(entry)


@dashboard_bp.route('/settings/image-updates/check', methods=['POST'])
@login_required
@is_admin_required
def check_image_updates_now():
    """Settings -> Image updates -> Check now (every reference, once an hour)."""
    return _check_now_json(None)


@dashboard_bp.route('/settings/image-updates', methods=['POST'])
@login_required
@is_admin_required
def save_image_update_settings():
    """Save the switch and the default scope. With the switch set by the environment, the
    submitted switch is ignored."""
    was_enabled, origin = image_update.effective_enabled()
    scope = (request.form.get('image_update_scope') or '').strip().lower()
    if scope not in image_tags.SCOPES:
        flash("Default scope must be Any, Same major or Same minor.", 'danger')
        return _settings_redirect('image-updates')
    enabled = None if origin == 'env' else request.form.get('image_update_enabled') == '1'
    scope_changed = scope != image_update.default_scope()
    image_update.save_settings(enabled, scope)
    db.session.commit()
    image_update.on_settings_changed(current_app._get_current_object(), was_enabled)
    if scope_changed:
        # A new default scope changes what is "newer": recompute locally, no registry call.
        for e in ServiceEntry.active().filter(ServiceEntry.image_ref.isnot(None)).all():
            image_update.recompute_entry(e, scope=scope)
        db.session.commit()
    flash("✅ Image update settings saved.", 'success')
    return _settings_redirect('image-updates')


def _image_update_settings_context():
    """Settings -> Image updates: the switch (and what locks it), the last and next run and
    the references in error. All read from stored state."""
    enabled, origin = image_update.effective_enabled()
    last = image_update.last_run()
    last_at = image_update._parse_iso((last or {}).get('at'))
    next_run = jobs.image_update_next_run() if enabled else None
    problems = []
    if enabled:
        for item in image_update.reference_report('error'):
            members = [m for m in item['entries'] if m['state'] == 'error']
            problems.append({'ref': item['ref'], 'error': item['error'],
                             'error_at': item['error_at'], 'next_check_at': item['next_check_at'],
                             'entries': members})
    return {
        'image_update_enabled': enabled,
        'image_update_origin': origin,
        'image_update_env_name': image_update.ENV_ENABLED,
        'image_update_scope': image_update.default_scope(),
        'image_update_scopes': _SCOPE_LABELS[1:],
        'image_update_last': last,
        'image_update_last_at': last_at,
        'image_update_next': next_run.astimezone().strftime('%Y-%m-%d %H:%M') if next_run else None,
        'image_update_problems': problems,
    }


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


@dashboard_bp.route('/service/<int:id>/details')
@login_required
def entry_details(id):
    """HTML fragment for the Compact view's details dialog (PRD 13.7): header,
    the shared entry facts beside the health panel, and the action row.
    Fetched when the dialog opens; 404 for an unknown or deleted entry."""
    entry = (
        ServiceEntry.active()
        .options(selectinload(ServiceEntry.checks))
        .filter(ServiceEntry.id == id)
        .first_or_404()
    )
    widget_values, widget_fields = _load_widget_values()
    return render_template(
        'partials/compact_details.html',
        entry=entry,
        widget_values=widget_values,
        widget_fields=widget_fields,
        STD_DOZZLE_URL=current_app.config.get('std_dozzle_url'),
    )


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


def _truthy(value):
    """A form/JSON flag: True, 1, "true", "yes" or "on"."""
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


@dashboard_bp.route('/entries/<int:id>/delete', methods=['POST'])
@login_required
@is_admin_required
def delete_entry_json(id):
    """JSON delete endpoint for JS-triggered deletes (tile trash icon, drawer delete button).

    Soft-deletes the entry (sets deleted_at). Returns {ok: true} on success. The caller is responsible for DOM cleanup or redirect.
    """
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()

    # Soft delete: recoverable from Settings -> Deleted. Widget stays attached.
    # `block` (stream entries): also keep the stream from bringing the entry back.
    body = request.get_json(silent=True)
    block = _truthy((body.get('block') if isinstance(body, dict) else None) or request.values.get('block'))
    streams.soft_delete_entry(entry, block and entry.stream_id is not None, actor=current_user.username)
    db.session.commit()
    return jsonify({'ok': True})


def _api_key_secret_response(key, full_key, rotated):
    """Render Settings with the new key in the show-once dialog (design 9.10).

    The key is not flashed or put in the session; it exists only in this response's
    HTML (nav.js then replaces the POST URL, so a reload is a plain Settings GET)."""
    html, _status = _render_settings(
        section='api-keys', open_modal='api-key-secret-modal',
        api_key_secret={'name': key.name, 'scope': key.scope, 'full_key': full_key, 'rotated': rotated})
    response = make_response(html)
    if rotated:
        response.headers['Cache-Control'] = 'no-store, no-cache'
        response.headers['Pragma'] = 'no-cache'
    else:
        response.headers['Cache-Control'] = 'no-store'
    return response


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
        error = "Choose a scope: read, write or ingest."
    if error:
        flash(error, "danger")
        return _render_settings(section='api-keys', open_modal='api-key-modal', status=400,
                                api_key_form={'name': name, 'scope': scope})
    key, full_key = api_keys.create_key(name, scope, created_by=current_user.id)
    logger.info(f"Created API key '{key.name}' ({key.prefix}, {key.scope}) by {current_user.username}.")
    return _api_key_secret_response(key, full_key, rotated=False)


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
        return _settings_redirect('api-keys')
    full_key = api_keys.rotate_key(key)
    logger.info(f"Rotated API key id={key.id} by {current_user.username}.")
    return _api_key_secret_response(key, full_key, rotated=True)


@dashboard_bp.route('/settings/api-keys/<int:id>/revoke', methods=['POST'])
@login_required
@is_admin_required
def revoke_api_key(id):
    key = db.get_or_404(ApiKey, id)
    api_keys.revoke_key(key)
    logger.info(f"Revoked API key '{key.name}' ({key.prefix}) by {current_user.username}.")
    flash(f"Revoked API key '{key.name}'.", "success")
    return _settings_redirect('api-keys')


@dashboard_bp.route('/settings/deleted/<int:id>/restore', methods=['POST'])
@login_required
@is_admin_required
def restore_deleted_entry(id):
    entry = ServiceEntry.deleted().filter(ServiceEntry.id == id).first_or_404()
    # Stream entries are unique by stream key, not by (host, name) (PRD 18.6).
    clash = None if entry.stream_id is not None else ServiceEntry.active().filter_by(
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
    return _settings_redirect('deleted')


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
    return _settings_redirect('deleted')


# --- Settings -> Streams (PRD 18.8) ------------------------------------------------
# Thin wrappers over streams.py: the lifecycle rules live there, these routes only
# read the form, call one function and flash the outcome.

PREVIEW_ROW_LIMIT = 1000


def _streams_context(preview_slug=None):
    """Everything the Streams tab renders: one dict per stream (counts, cleanup
    dialog data, blocks, offers), the read-only Docker row and the optional Preview."""
    rows = []
    for stream in InventoryStream.query.order_by(InventoryStream.display_name, InventoryStream.id).all():
        offers = StreamLinkOffer.query.filter_by(stream_id=stream.id).order_by(StreamLinkOffer.id).all()
        entry_ids = {o.entry_id for o in offers}
        names = {e.id: e.container_name for e in
                 ServiceEntry.query.filter(ServiceEntry.id.in_(entry_ids)).all()} if entry_ids else {}
        rows.append({
            'stream': stream,
            'stats': streams.entry_stats(stream),
            'customised': streams.customised_entries(stream),
            'linked': streams.linked_entries(stream),
            'blocks': InventoryBlock.query.filter_by(stream_id=stream.id).order_by(InventoryBlock.id).all(),
            'offers': [{'offer': o, 'entry_name': names.get(o.entry_id, '?')} for o in offers],
            'item_count': len(stream.snapshot) if stream.snapshot is not None else None,
            'health': streams.stream_health(stream),
            # Dry run for streams that are not applying: one read-only plan() each.
            'would_counts': (streams.would_counts(stream) if stream.status != 'enabled' else None),
        })
    docker_q = ServiceEntry.active().filter(ServiceEntry.source == SOURCE_NOTIFIER)
    docker_row = {'count': docker_q.count(),
                  'last_register': docker_q.with_entities(func.max(ServiceEntry.last_api_update)).scalar()}
    preview = None
    if preview_slug:
        stream = streams.find_stream(preview_slug)
        if stream is None:
            flash("That stream doesn't exist.", "danger")
        else:
            try:
                data = streams.preview(stream)
                preview = {'stream': stream, 'data': data, 'items': data['items'][:PREVIEW_ROW_LIMIT],
                           'truncated': max(0, len(data['items']) - PREVIEW_ROW_LIMIT)}
            except streams.StreamError as exc:
                flash(exc.message, "danger")
    return {'stream_rows': rows, 'docker_row': docker_row, 'preview': preview,
            'pending_streams': sum(1 for r in rows if r['stream'].status == 'pending'),
            'open_offers': sum(len(r['offers']) for r in rows)}


def _stream_edit_error(slug, block, values, message):
    """A failed Edit stream block: re-render Settings with that dialog open and the
    typed values kept (design 9.8), instead of a flash and a redirect."""
    flash(message, "danger")
    return _render_settings(section='streams', open_modal=f'stream-edit-{slug}',
                            forms={f'stream:{slug}:{block}': values}, status=400)


def _streams_redirect():
    return _settings_redirect('streams')


def _stream_or_404(slug):
    stream = streams.find_stream(slug)
    if stream is None:
        abort(404)
    return stream


def _stream_action(slug, fn, success, **kwargs):
    """Run one lifecycle call; flash its message, or the StreamError's. `success`
    is a callable of the result returning the message."""
    stream = _stream_or_404(slug)
    name = stream.display_name
    try:
        result = fn(stream, **kwargs)
    except streams.StreamError as exc:
        db.session.rollback()
        flash(exc.message, "danger")
        return False
    flash(success(name, result), "success")
    return True


def _counts_text(counts):
    parts = [f"{v} {k.replace('_', ' ')}" for k, v in (counts or {}).items() if v]
    return ", ".join(parts) or "nothing to change"


@dashboard_bp.route('/settings/streams/<slug>/enable', methods=['POST'])
@login_required
@is_admin_required
def stream_enable(slug):
    if _stream_action(slug, streams.enable, lambda n, r: (
            f"Enabled stream '{n}': {_counts_text(r['counts'])}." if r['applied']
            else f"Enabled stream '{n}'. The next snapshot will import its items.")):
        logger.info(f"Stream '{slug}' enabled by {current_user.username}.")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/ignore', methods=['POST'])
@login_required
@is_admin_required
def stream_ignore(slug):
    if _stream_action(slug, streams.ignore, lambda n, r: f"Ignoring stream '{n}'. Its snapshots are dropped."):
        logger.info(f"Stream '{slug}' ignored by {current_user.username}.")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/disable', methods=['POST'])
@login_required
@is_admin_required
def stream_disable(slug):
    cleanup = request.form.get('cleanup') or streams.CLEANUP_KEEP
    clear_blocks = _truthy(request.form.get('clear_blocks'))
    if _stream_action(
            slug, streams.disable, lambda n, r: f"Disabled stream '{n}' ({cleanup}): {_counts_text(r)}.",
            cleanup=cleanup, clear_blocks=clear_blocks):
        logger.info(f"Stream '{slug}' disabled ({cleanup}) by {current_user.username}.")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/delete', methods=['POST'])
@login_required
@is_admin_required
def stream_delete(slug):
    cleanup = request.form.get('cleanup') or streams.CLEANUP_KEEP
    if _stream_action(
            slug, streams.delete, lambda n, r: f"Deleted stream '{n}' ({cleanup}): {_counts_text(r)}.",
            cleanup=cleanup):
        logger.info(f"Stream '{slug}' deleted ({cleanup}) by {current_user.username}.")
    return _streams_redirect()


def _filter_lines(text):
    """A textarea of filters (one per line, commas also split) -> list."""
    return [p.strip() for p in re.split(r'[\n,]', text or '') if p.strip()]


@dashboard_bp.route('/settings/streams/<slug>/update', methods=['POST'])
@login_required
@is_admin_required
def stream_update(slug):
    stream = _stream_or_404(slug)
    try:
        changes = streams.update(
            stream, request.form.get('display_name'),
            _filter_lines(request.form.get('network_include')),
            _filter_lines(request.form.get('network_exclude')),
            sent=('display_name', 'network_include', 'network_exclude'))
    except streams.StreamError as exc:
        db.session.rollback()
        return _stream_edit_error(slug, 'name', {
            'display_name': request.form.get('display_name') or '',
            'network_include': request.form.get('network_include') or '',
            'network_exclude': request.form.get('network_exclude') or ''}, exc.message)
    logger.info(f"Stream '{slug}' updated by {current_user.username}: {', '.join(changes) or 'no changes'}.")
    flash(f"Saved stream '{stream.display_name}'." if changes else "Nothing changed.", "success")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/monitoring', methods=['POST'])
@login_required
@is_admin_required
def stream_monitoring(slug):
    """Expected snapshot interval (minutes in the form, seconds stored) and the
    missing-entry expiry (days). Blank clears either (PRD 18.9)."""
    stream = _stream_or_404(slug)
    typed = {k: (request.form.get(k) or '').strip()
             for k in ('expected_interval_minutes', 'missing_expiry_days')}
    values = {}
    for field_name, label in (('expected_interval_minutes', 'Expected interval'),
                              ('missing_expiry_days', 'Missing expiry')):
        raw = typed[field_name]
        try:
            values[field_name] = int(raw) if raw else None
        except ValueError:
            return _stream_edit_error(slug, 'monitoring', typed, f"{label} must be a whole number.")
    minutes = values['expected_interval_minutes']
    try:
        changes = streams.update(
            stream, sent=('expected_interval_seconds', 'missing_expiry_days'),
            expected_interval_seconds=minutes * 60 if minutes is not None else None,
            missing_expiry_days=values['missing_expiry_days'])
    except streams.StreamError as exc:
        db.session.rollback()
        return _stream_edit_error(slug, 'monitoring', typed, exc.message.replace(
            'expected_interval_seconds must be 60-86400 seconds', 'Expected interval must be 1-1440 minutes'))
    logger.info(f"Stream '{slug}' monitoring saved by {current_user.username}: {', '.join(changes) or 'no changes'}.")
    flash(f"Saved staleness and missing-entry settings for '{stream.display_name}'." if changes
          else "Nothing changed.", "success")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/default-checks', methods=['POST'])
@login_required
@is_admin_required
def stream_default_checks(slug):
    stream = _stream_or_404(slug)
    raw_port = (request.form.get('tcp_port') or '').strip()
    typed = {'ping': _truthy(request.form.get('ping')), 'tcp_port': raw_port}
    try:
        port = int(raw_port) if raw_port else None
    except ValueError:
        return _stream_edit_error(slug, 'checks', typed, "TCP port must be a number from 1 to 65535.")
    try:
        changes = streams.update(stream, sent=('default_checks',), default_checks={
            'ping': typed['ping'], 'tcp_port': port})
    except streams.StreamError as exc:
        db.session.rollback()
        return _stream_edit_error(slug, 'checks', typed, exc.message)
    logger.info(f"Stream '{slug}' default checks saved by {current_user.username}: "
                f"{'changed' if changes else 'no changes'}.")
    flash(f"Saved default checks for '{stream.display_name}'. New entries get them; use "
          "Apply to existing entries for the current ones." if changes else "Nothing changed.", "success")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/default-checks/apply', methods=['POST'])
@login_required
@is_admin_required
def stream_default_checks_apply(slug):
    stream = _stream_or_404(slug)
    result = streams.apply_default_checks(stream)
    logger.info(f"Stream '{slug}' default checks applied by {current_user.username}: "
                f"{result['checks_added']} added to {result['entries_changed']} of {result['entries']} entries.")
    flash(f"Added {result['checks_added']} check{'' if result['checks_added'] == 1 else 's'} to "
          f"{result['entries_changed']} of {result['entries']} active "
          f"entr{'y' if result['entries'] == 1 else 'ies'} of '{stream.display_name}'.", "success")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/purge-notifications', methods=['POST'])
@login_required
@is_admin_required
def stream_purge_notifications(slug):
    """Purge this stream's entries from MQTT and Home Assistant, then republish what is
    still eligible. Posted with fetch; the counts show inline."""
    stream = _stream_or_404(slug)
    return _purge_response(notify.purge_stream, stream.id)


@dashboard_bp.route('/settings/streams/<slug>/blocks/<int:block_id>/unblock', methods=['POST'])
@login_required
@is_admin_required
def stream_unblock(slug, block_id):
    stream = _stream_or_404(slug)
    try:
        key = streams.unblock(stream, block_id)
    except streams.StreamError as exc:
        flash(exc.message, "danger")
        return _streams_redirect()
    logger.info(f"Stream '{slug}' key {key} unblocked by {current_user.username}.")
    flash(f"Unblocked {key}. The next snapshot will bring it back.", "success")
    return _streams_redirect()


@dashboard_bp.route('/settings/streams/<slug>/offers/<int:offer_id>/<answer>', methods=['POST'])
@login_required
@is_admin_required
def stream_answer_offer(slug, offer_id, answer):
    """Accept (the manual entry joins the stream) or decline (a new stream entry is
    created). Posted from the Streams tab and from the manual entry's edit page."""
    if answer not in ('accept', 'decline'):
        abort(404)
    stream = _stream_or_404(slug)
    target = safe_redirect_target(request.form.get('next'), url_for('dashboard.settings', section='streams'))
    try:
        offer = streams.get_offer(stream, offer_id)
        entry = (streams.accept_offer if answer == 'accept' else streams.decline_offer)(stream, offer)
    except streams.StreamError as exc:
        db.session.rollback()
        flash(exc.message, "danger")
        return redirect(target)
    logger.info(f"Stream '{slug}' link offer {offer_id} {answer}ed by {current_user.username}.")
    flash(f"Converted '{entry.container_name}' to a stream entry." if answer == 'accept'
          else f"Kept '{entry.container_name}' separate from the manual entry.", "success")
    return redirect(target)


@dashboard_bp.route('/edit/<int:id>/stream-link', methods=['POST'])
@login_required
@is_admin_required
def link_entry_to_stream(id):
    """Link a manual entry to an unmatched item of a stream (`target` is `slug:key`)."""
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()
    back = url_for('dashboard.edit_entry', id=id, ref=request.form.get('ref') or None)
    slug, _, key = (request.form.get('target') or '').partition(':')
    stream = streams.find_stream(slug) if slug and key else None
    if stream is None:
        flash("Choose a stream item to link to.", "danger")
        return redirect(back)
    try:
        streams.link_entry(stream, entry, key)
    except streams.StreamError as exc:
        db.session.rollback()
        flash(exc.message, "danger")
        return redirect(back)
    logger.info(f"Entry {id} linked to stream '{slug}' by {current_user.username}.")
    flash(f"Linked '{entry.container_name}' to stream '{stream.display_name}'.", "success")
    return redirect(back)


@dashboard_bp.route('/edit/<int:id>/stream-unlink', methods=['POST'])
@login_required
@is_admin_required
def unlink_entry_from_stream(id):
    """Unlink a stream entry: it becomes a manual entry again. `block` also keeps the
    stream from re-adding or re-offering the item."""
    entry = ServiceEntry.active().filter(ServiceEntry.id == id).first_or_404()
    ref = request.form.get('ref') or None
    back = url_for('dashboard.edit_entry', id=id, ref=ref)
    try:
        result = streams.unlink_entry(entry, _truthy(request.form.get('block')),
                                      actor=current_user.username)
    except streams.StreamError as exc:
        db.session.rollback()
        flash(exc.message, "danger")
        return redirect(back)
    logger.info(f"Entry {id} unlinked from its stream by {current_user.username}.")
    msg = f"Unlinked '{entry.container_name}': it is a manual entry again."
    if result['host_restored']:
        msg += f" Its host '{result['host']}' is back."
    elif result['host_clash']:
        msg += " Its old host was left empty because another entry now uses that host and name."
    if result['blocked']:
        msg += " The stream will not add or offer it again (Settings → Streams → Blocked)."
    flash(msg, "success")
    return redirect(back)


def _edit_stream_context(entry):
    """Edit page extras for a manual entry: its open link offers, and the stream
    items it could be linked to by hand."""
    offers, choices = [], []
    if entry.source == SOURCE_MANUAL:
        offers = StreamLinkOffer.query.filter_by(entry_id=entry.id).order_by(StreamLinkOffer.id).all()
        if not offers:
            for stream in InventoryStream.query.order_by(InventoryStream.display_name).all():
                items = streams.unmatched_items(stream)
                if items:
                    choices.append({'stream': stream, 'items': items})
    return {'link_offers': offers, 'link_choices': choices}


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
    return _settings_redirect('deleted')


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
    return _settings_redirect('deleted')
