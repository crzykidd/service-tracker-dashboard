"""Presentation helpers for the image update check (img-03).

Read-only: everything here reads the state `image_update.py` already stored. No registry
call, no recompute, nothing written. The templates use `image_update_info(entry)` for the
badge, the details line and the Check now link; `image_updates_enabled()` is the global
switch, read once per request (a missing settings row is not cached by the session, so
reading it per entry would be one query each, the same guard as `mgmt_serializers`).
"""

import re
from datetime import datetime

import humanize
from flask import g, has_request_context

import image_update
from image_ref import parse as parse_image_ref

# A GitHub repository URL (from the OCI `source` label): owner/repo, optional .git.
_GITHUB_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")

# States with something to say in the details; `off` (and no state) say nothing.
_DETAIL_STATES = ("update", "current", "unknown", "error", "pinned")
# States where a manual check can do something (an entry with a checkable reference).
_CHECKABLE_STATES = ("update", "current", "unknown", "error")


def image_updates_enabled():
    """The check's on/off switch, once per request."""
    if not has_request_context():
        return image_update.is_enabled()
    if "image_update_ui_enabled" not in g:
        g.image_update_ui_enabled = image_update.is_enabled()
    return g.image_update_ui_enabled


def release_notes_url(source):
    """`<source>/releases` when `source` is a GitHub repository URL, else None."""
    match = _GITHUB_RE.match(source or "")
    if not match:
        return None
    return f"https://github.com/{match.group(1)}/{match.group(2)}/releases"


def image_update_info(entry):
    """What the views show for one entry, or None when there is nothing to show (not a Docker
    entry, no state, or the check is switched off). Keys: state, model, latest, kind, reason,
    rebuilt, checked_at, pushed_at, error, tag, running_version, release_url, checkable,
    badge_title."""
    if not entry.is_docker or entry.image_update_state is None:
        return None
    state = image_update.effective_state(entry, image_updates_enabled())
    if state not in _DETAIL_STATES:
        return None
    detail = entry.image_update_detail if isinstance(entry.image_update_detail, dict) else {}
    row = entry.image_reference if entry.image_ref else None
    parsed = parse_image_ref(entry.image_ref) if entry.image_ref else None
    info = entry.image_info if isinstance(entry.image_info, dict) else {}
    out = {
        "state": state,
        "model": detail.get("model"),
        "latest": entry.image_update_latest,
        "kind": entry.image_update_kind,
        "reason": detail.get("reason"),
        "rebuilt": bool(detail.get("rebuilt")),
        "checked_at": row.checked_at if row else None,
        "pushed_at": row.remote_digest_changed_at if row else None,
        "error": row.last_error if row else None,
        "tag": parsed.tag if parsed else None,
        "running_version": info.get("version") or None,
        "release_url": release_notes_url(info.get("source")),
        "checkable": state in _CHECKABLE_STATES,
        "badge_title": None,
    }
    if state == "update":
        out["badge_title"] = _badge_title(out)
    return out


def _badge_title(info):
    if info["model"] == "digest" or info["kind"] == "digest":
        parts = [info["tag"] or "tag"]
        if info["pushed_at"]:
            parts.append("pushed " + humanize.naturaltime(datetime.utcnow() - info["pushed_at"]))
        return "Image updated upstream ({})".format(", ".join(parts))
    kind = f" ({info['kind']})" if info["kind"] else ""
    return f"Newer image: {info['latest']}{kind}"
