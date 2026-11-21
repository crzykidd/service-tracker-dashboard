"""Settings -> Backup & restore -> Restore database (backup phase 5, design section 10).

Stage only: pick a snapshot of the backup folder or upload one, see what was found, confirm.
The file is validated and copied to `<CONFIG_DIR>/restore/pending.sqlite3`; `restore_swap.py`
swaps it in at the next container start. There is no live swap and no management API route.
Routes hang on `dashboard_bp`, so the endpoints stay `dashboard.*`.
"""

import logging
import os
import re
import secrets

from flask import flash, request
from flask_login import current_user, login_required

import backups
import restore_staging
from extensions import db
from routes_auth import is_admin_required
from routes_dashboard import _render_settings, _settings_redirect, dashboard_bp

logger = logging.getLogger(__name__)

UPLOAD_OVERHEAD = 64 * 1024            # multipart framing on top of the 200 MB file limit
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
CHUNK = 1024 * 1024


def _too_large():
    flash(f"The file is larger than {restore_staging.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", "danger")
    return _settings_redirect("backup")


def _confirm_page(info, source_name, *, server_file=None, token=None):
    return _render_settings(section="backup", restore_confirm={
        "info": info, "source_name": source_name, "server_file": server_file, "token": token})


def _stream_upload(upload, dest):
    """Write the upload to `dest` in chunks; False (file removed) when it exceeds the limit."""
    limit = restore_staging.MAX_UPLOAD_BYTES
    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = upload.stream.read(CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > limit:
                break
            out.write(chunk)
    if written > limit:
        os.remove(dest)
        return False
    return True


@dashboard_bp.route("/settings/restore/stage", methods=["POST"])
@login_required
@is_admin_required
def restore_stage():
    """Validate a snapshot (from the backup folder, or uploaded) and show what was found. Nothing
    is staged until the operator confirms."""
    limit = restore_staging.MAX_UPLOAD_BYTES
    if (request.content_length or 0) > limit + UPLOAD_OVERHEAD:
        return _too_large()
    server_file = (request.form.get("server_file") or "").strip()
    upload = request.files.get("snapshot_file")
    if upload is not None and upload.filename:
        name = os.path.basename(upload.filename)
        token = secrets.token_urlsafe(16)
        os.makedirs(restore_staging.restore_dir(), exist_ok=True)
        dest = restore_staging.upload_path(token)
        try:
            if not _stream_upload(upload, dest):
                return _too_large()
            info = restore_staging.validate(dest)
        except restore_staging.RestoreError as e:
            _remove(dest)
            flash(f"Could not use {name}: {e}", "danger")
            return _settings_redirect("backup")
        except OSError as e:
            _remove(dest)
            flash(f"Could not read the upload: {e.strerror or e}.", "danger")
            return _settings_redirect("backup")
        return _confirm_page(info, name, token=token)
    if server_file:
        path = backups.resolve_file(server_file, suffixes=(".sqlite3",))
        if path is None:
            flash(f"'{server_file}' is not a snapshot in the backup folder.", "danger")
            return _settings_redirect("backup")
        try:
            info = restore_staging.validate(path)
        except restore_staging.RestoreError as e:
            flash(f"Could not use {server_file}: {e}", "danger")
            return _settings_redirect("backup")
        return _confirm_page(info, os.path.basename(path), server_file=os.path.basename(path))
    flash("Choose a snapshot, or upload a .sqlite3 file.", "warning")
    return _settings_redirect("backup")


def _remove(path):
    try:
        os.remove(path)
    except OSError:
        pass


@dashboard_bp.route("/settings/restore/confirm", methods=["POST"])
@login_required
@is_admin_required
def restore_confirm():
    """Stage the validated snapshot as the pending restore (applied on the next start)."""
    token = (request.form.get("token") or "").strip()
    server_file = (request.form.get("server_file") or "").strip()
    keep_dir = backups.backup_dir()
    path, name, temp = None, None, None
    if token:
        if not TOKEN_RE.match(token) or not os.path.isfile(restore_staging.upload_path(token)):
            flash("This restore expired. Upload the file again.", "warning")
            return _settings_redirect("backup")
        temp = path = restore_staging.upload_path(token)
        name = (request.form.get("source_name") or "uploaded.sqlite3")
        name = os.path.basename(name) or "uploaded.sqlite3"
    elif server_file:
        path = backups.resolve_file(server_file, suffixes=(".sqlite3",))
        if path is None:
            flash(f"'{server_file}' is not a snapshot in the backup folder.", "danger")
            return _settings_redirect("backup")
        name = os.path.basename(path)
    else:
        flash("Choose a snapshot, or upload a .sqlite3 file.", "warning")
        return _settings_redirect("backup")
    try:
        meta = restore_staging.stage(path, name, current_user.username, keep_dir)
    except restore_staging.RestoreError as e:
        flash(f"Could not stage {name}: {e}", "danger")
        return _settings_redirect("backup")
    except OSError as e:
        flash(f"Could not stage {name}: {e.strerror or e}.", "danger")
        return _settings_redirect("backup")
    finally:
        if temp:
            _remove(temp)
    logger.info("Database restore staged from %s by %s (revision %s)", name, current_user.username,
                meta["revision"])
    flash(f"Restore of {name} is staged. It is applied on the next container restart.", "success")
    return _settings_redirect("backup")


@dashboard_bp.route("/settings/restore/cancel", methods=["POST"])
@login_required
@is_admin_required
def restore_cancel():
    if restore_staging.cancel():
        logger.info("Staged database restore cancelled by %s", current_user.username)
        flash("The staged restore was cancelled.", "success")
    else:
        flash("No restore was staged.", "info")
    return _settings_redirect("backup")


@dashboard_bp.route("/settings/restore/dismiss", methods=["POST"])
@login_required
@is_admin_required
def restore_dismiss():
    restore_staging.mark_seen()
    db.session.commit()
    return _settings_redirect("backup")
