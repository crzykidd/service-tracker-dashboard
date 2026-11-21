"""Settings -> Backup & restore -> Import (backup phase 4, design 12.2).

Upload (or pick a server file) -> stage -> a preview page with the stream mapping, the mode
switch and the ticks -> apply -> summary. The routes only parse the form and render; matching,
the fingerprint and every write are `importer`'s (design 7). Routes hang on `dashboard_bp`, so
the endpoints stay `dashboard.*`.
"""

import json
import logging
import os

from flask import flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import backups
import importer
import settings_sections
from routes_auth import is_admin_required
from routes_dashboard import _settings_redirect, dashboard_bp

logger = logging.getLogger(__name__)

IMPORT_SUFFIXES = (".yml", ".yaml", ".json")
UPLOAD_OVERHEAD = 64 * 1024            # multipart framing on top of the 10 MB file limit
EXPIRED_MESSAGE = "This import expired. Upload the file again."

# Pill text per status (importer.STATUS_LABELS carries the long form).
PILL_LABELS = {
    importer.MISSING: "Missing settings", importer.DIFFERS: "Differs", importer.IDENTICAL: "Identical",
    importer.DELETED: "Deleted locally", importer.AMBIGUOUS: "Ambiguous", importer.NOT_FOUND: "Not found",
    importer.WAITING: "Waiting", importer.CONFLICT: "Conflict", importer.INVALID: "Invalid",
}
FILTER_CHIPS = (importer.MISSING, importer.DIFFERS, importer.AMBIGUOUS, importer.NOT_FOUND,
                importer.WAITING, importer.CONFLICT)
SECTION_LABELS = {
    "docker": "Docker", "manual": "Manual", "groups": "Groups", "channels": "Notification channels",
    "streams": "Streams & blocks", "users": "Users", "settings": "Settings",
}
GROUP_SUBTITLES = {
    "users": "Created users cannot sign in until an admin sets a password in Users.",
    "channels": "A channel is created without its password and disabled until you set one.",
}


# --- helpers ---------------------------------------------------------------------------------


def _uid():
    return current_user.id


def _expired():
    flash(EXPIRED_MESSAGE, "warning")
    return _settings_redirect("backup")


def _show(value, limit=240):
    """A value from the file or the database as one short line of text."""
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, sort_keys=True, default=str)
    else:
        text = str(value)
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _summary_text(row):
    missing = sum(1 for f in row.fields if f.kind == importer.MISSING and f.applicable)
    differs = sum(1 for f in row.fields if f.kind == importer.DIFFERS)
    parts = []
    if missing:
        parts.append(f"{missing} missing")
    if differs:
        parts.append(f"{differs} differs")
    return " · ".join(parts)


def _row_sub(row):
    if row.section != "entries" or row.record is None:
        return ""
    ident = row.record.identity
    return ident.host or ident.stream_key or ident.pre_link_host or ""


def _parse_form(form):
    """The operator's choices from the preview form (design 12.2 step 4): the `Selection` for
    `importer.apply`, plus the raw ticks used to re-render. Field ticks are `field-<rid>` and
    options `opt-<rid>`, both multi-valued (the value is the field / option name), so a rid
    never has to be split from a field name."""
    mode = form.get("mode") or "fill"
    rids = set()
    ticks = {"sel": set(), "create": set(), "target": {}, "opts": {}, "fields": {},
             "fieldsets": set(form.getlist("fieldset"))}
    for key in form.keys():
        for prefix, bucket in (("sel-", "sel"), ("create-", "create")):
            if key.startswith(prefix):
                rid = key[len(prefix):]
                ticks[bucket].add(rid)
                rids.add(rid)
        if key.startswith("target-"):
            rid = key[len("target-"):]
            ticks["target"][rid] = (form.get(key) or "").strip()
            rids.add(rid)
        elif key.startswith("opt-"):
            rid = key[len("opt-"):]
            ticks["opts"][rid] = set(form.getlist(key))
            rids.add(rid)
        elif key.startswith("field-"):
            rid = key[len("field-"):]
            ticks["fields"][rid] = set(form.getlist(key))
            rids.add(rid)
    selection = {}
    for rid in rids:
        target = ticks["target"].get(rid)
        create = rid in ticks["create"] or target == "create"
        apply_row = rid in ticks["sel"] or rid in ticks["create"]
        if not apply_row:
            continue
        entry = {"apply": True, "create": create,
                 "options": sorted(ticks["opts"].get(rid, ())),
                 "target_id": int(target) if target and target.isdigit() else None}
        if rid in ticks["fieldsets"]:           # the row showed field boxes: exactly the ticked ones
            entry["fields"] = sorted(ticks["fields"].get(rid, ()))
        selection[rid] = entry
    return mode, selection, ticks


def _stream_map_from_form(form):
    """`{file_id: local slug | None}` from the `map-<file_id>` selects ('' = Skip)."""
    out = {}
    for key in form.keys():
        if key.startswith("map-"):
            out[key[len("map-"):]] = (form.get(key) or "").strip() or None
    return out


def _view_rows(the_plan, mode, ticks, known_rids):
    """One dict per plan row for the template: the row, its checkbox / switch state and the
    per-field boxes. `ticks` (a previous submission) keeps the operator's choices for rows that
    were on screen before (`known_rids`); everything else starts at the plan's defaults."""
    views = []
    for idx, row in enumerate(the_plan.rows):
        kept = ticks is not None and row.rid in known_rids
        sel = (row.rid in ticks["sel"]) if kept else bool(row.default_selected)
        create = (row.rid in ticks["create"] or ticks["target"].get(row.rid) == "create") if kept else False
        target = None
        if kept and (ticks["target"].get(row.rid) or "").isdigit():
            target = int(ticks["target"][row.rid])
        opts = set(ticks["opts"].get(row.rid, ())) if kept else set()
        field_ticks = (ticks["fields"].get(row.rid, set()) if row.rid in ticks["fieldsets"] else None) \
            if kept else None
        fields = []
        for f in row.fields:
            checked = (f.field in field_ticks) if field_ticks is not None else f.kind == importer.MISSING
            fields.append({
                "name": f.field, "kind": f.kind, "note": f.note, "applicable": f.applicable,
                "file": _show(f.file), "local": _show(f.local),
                "checked": bool(checked and f.applicable),
                "disabled": (not f.applicable) or (f.kind == importer.DIFFERS and mode != "overwrite"),
            })
        views.append({
            "row": row, "idx": idx, "sel": sel, "create": create, "target": target, "opts": opts,
            "fields": fields, "summary": _summary_text(row), "sub": _row_sub(row),
            "pill": PILL_LABELS[row.status],
            "search": f"{row.label} {_row_sub(row)}".lower(),
            "selectable": row.status in (importer.MISSING, importer.DIFFERS, importer.DELETED,
                                         importer.AMBIGUOUS, importer.NOT_FOUND),
        })
    return views


def _group_views(the_plan, views):
    """The rows grouped for display in plan order: `[{key, label, subtitle, rows, identical,
    total, checked}]`. Identical rows are collapsed per group."""
    labels = {m["file_id"]: m["display_name"] or m["file_id"] for m in the_plan.stream_mapping}
    groups, order = {}, []
    for v in views:
        key = v["row"].source_group
        if key not in groups:
            if key.startswith("stream:"):
                label = labels.get(key[len("stream:"):], key[len("stream:"):])
            else:
                label = SECTION_LABELS.get(key, key.title())
            groups[key] = {"key": key, "label": label, "subtitle": GROUP_SUBTITLES.get(key, ""),
                           "rows": [], "identical": [], "total": 0, "checked": 0}
            order.append(key)
        g = groups[key]
        if v["row"].status == importer.IDENTICAL:
            g["identical"].append(v)
            continue
        g["rows"].append(v)
        if v["selectable"]:
            g["total"] += 1
            if v["sel"] or v["create"]:
                g["checked"] += 1
    return [groups[k] for k in order]


def _bar_counts(views):
    """The apply bar's initial counts (import.js keeps them live): ticked records, the fields
    that would be written, and the rows imported as new."""
    records = fields = new = 0
    for v in views:
        if not v["selectable"] or not (v["sel"] or v["create"]):
            continue
        records += 1
        new += 1 if v["create"] else 0
        fields += sum(1 for f in v["fields"] if f["checked"] and not f["disabled"])
    return {"records": records, "fields": fields, "new": new}


def _status_counts(the_plan):
    by = the_plan.counts["by_status"]
    return {s: by.get(s, 0) for s in importer.STATUSES}


def _nav_context():
    return {"settings_groups": settings_sections.GROUPS, "settings_sections": settings_sections.SECTIONS,
            "settings_default_section": settings_sections.DEFAULT}


def _render_preview(token, parsed, state, *, ticks=None, mode="fill", status=200):
    """Plan the staged document, keep what the apply route needs beside it, render the page."""
    the_plan = importer.plan(parsed, state.get("stream_map") or None)
    known = set((state.get("digests") or {}).keys())
    new_state = dict(state)
    new_state.update({"digests": the_plan.digests, "plan_fp": the_plan.fingerprint,
                      "eff_map": the_plan.stream_map})
    importer.save_state(token, _uid(), new_state)
    views = _view_rows(the_plan, mode, ticks, known)
    html = render_template(
        "settings_import.html", step="preview", token=token, plan=the_plan, mode=mode,
        groups=_group_views(the_plan, views), chips=FILTER_CHIPS, pill_labels=PILL_LABELS,
        status_counts=_status_counts(the_plan), bar=_bar_counts(views), filename=parsed.filename, flash_target="import",
        **_nav_context())
    return html, status


# --- routes ----------------------------------------------------------------------------------


@dashboard_bp.route("/settings/import", methods=["POST"])
@login_required
@is_admin_required
def import_upload():
    """Read an upload or a file of the backup folder, parse it, stage it, show the preview."""
    limit = importer.MAX_UPLOAD_BYTES
    server_file = (request.form.get("server_file") or "").strip()
    upload = request.files.get("import_file") if (request.content_length or 0) <= limit + UPLOAD_OVERHEAD else None
    if (request.content_length or 0) > limit + UPLOAD_OVERHEAD:
        flash(f"The file is larger than {limit // (1024 * 1024)} MB.", "danger")
        return _settings_redirect("backup")
    name = None
    if upload is not None and upload.filename:
        name = os.path.basename(upload.filename)
        raw = upload.stream.read(limit + 1)
    elif server_file:
        path = backups.resolve_file(server_file, suffixes=IMPORT_SUFFIXES)
        if path is None:
            flash(f"'{server_file}' is not an export in the backup folder.", "danger")
            return _settings_redirect("backup")
        name = os.path.basename(path)
        try:
            with open(path, "rb") as f:
                raw = f.read(limit + 1)
        except OSError as e:
            flash(f"Could not read {name}: {e.strerror or e}.", "danger")
            return _settings_redirect("backup")
    else:
        flash("Choose a file to import, or pick an export from the backup folder.", "warning")
        return _settings_redirect("backup")
    try:
        parsed = importer.parse(raw, name)
    except importer.ImportParseError as e:
        flash(f"Could not import {name}: {e}", "danger")
        return _settings_redirect("backup")
    token = importer.stage(parsed, _uid())
    if server_file and not (upload is not None and upload.filename):
        importer.save_state(token, _uid(), {"server_file": name})
    return redirect(url_for("dashboard.import_preview", token=token))


@dashboard_bp.route("/settings/import/<token>", methods=["GET"])
@login_required
@is_admin_required
def import_preview(token):
    parsed = importer.load(token, _uid())
    if parsed is None:
        return _expired()
    return _render_preview(token, parsed, importer.load_state(token, _uid()))


@dashboard_bp.route("/settings/import/<token>/map", methods=["POST"])
@login_required
@is_admin_required
def import_map(token):
    parsed = importer.load(token, _uid())
    if parsed is None:
        return _expired()
    state = importer.load_state(token, _uid())
    state["stream_map"] = _stream_map_from_form(request.form)
    importer.save_state(token, _uid(), state)
    return redirect(url_for("dashboard.import_preview", token=token))


@dashboard_bp.route("/settings/import/<token>/cancel", methods=["POST"])
@login_required
@is_admin_required
def import_cancel(token):
    if importer.load(token, _uid()) is not None:
        importer.discard(token)
    return _settings_redirect("backup")


@dashboard_bp.route("/settings/import/<token>/apply", methods=["POST"])
@login_required
@is_admin_required
def import_apply_route(token):
    parsed = importer.load(token, _uid())
    if parsed is None:
        return _expired()
    state = importer.load_state(token, _uid())
    mode, selection, ticks = _parse_form(request.form)
    if mode not in importer.MODES:
        mode = "fill"
    digests = state.get("digests") or {}
    shown_fp = request.form.get("fingerprint") or ""
    if not digests or shown_fp != state.get("plan_fp"):
        # The page is not the one last planned (another tab, or the preview was never loaded).
        flash("This preview is out of date. Review it and apply again.", "warning")
        html, _ = _render_preview(token, parsed, state, ticks=ticks, mode=mode)
        return html, 409
    fingerprint = importer.fingerprint_from_digests(digests, selection, state.get("eff_map") or {})
    try:
        result = importer.apply(parsed, state.get("stream_map") or None, selection, mode, fingerprint,
                                current_user.username)
    except importer.ImportStale as e:
        flash(str(e), "warning")
        return _render_preview(token, parsed, state, ticks=ticks, mode=mode, status=409)
    except importer.ImportApplyError as e:
        flash(str(e), "danger")
        return _render_preview(token, parsed, state, ticks=ticks, mode=mode, status=400)
    importer.discard(token)
    flash("Import applied.", "success")
    html = render_template(
        "settings_import.html", step="summary", result=result.to_dict(), filename=parsed.filename,
        server_file=state.get("server_file"), flash_target="import", **_nav_context())
    return html, 200
