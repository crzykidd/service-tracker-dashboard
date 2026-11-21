"""Entry-level rules shared by the Add/Edit pages and the management API.

Plain functions over plain values, so the browser forms and the API enforce
one rule set: name/host/description limits, the duplicate check, sort
priority, icon names (and the download of a missing icon), group lookup and
URL provenance. Validators return `{"field", "message"}` error dicts (message
without a trailing period); callers add their own context.
"""

import logging
import os

import requests

import image_repo
import synthesizer
from extensions import db
from image_utils import icon_path_in_dir, safe_icon_filename
from models import Group, ServiceEntry

logger = logging.getLogger(__name__)

NAME_MAX = 128   # = service_entry.container_name and the stream item name max
HOST_MAX = 100
DESCRIPTION_MAX = 255
URL_MAX = 255
IMAGE_REPO_URL_MAX = 512

GROUP_NAME_MAX = 100
GROUP_ICON_MAX = 255

ICON_ERROR = "icon name may only use letters, numbers, dots, dashes and underscores"


def validate_basic(name, host, description):
    """Name is required; name, host and description have length limits."""
    errors = []
    if not name:
        errors.append({"field": "name", "message": "name is required"})
    if name and len(name) > NAME_MAX:
        errors.append({"field": "name", "message": f"name is limited to {NAME_MAX} characters"})
    if host and len(host) > HOST_MAX:
        errors.append({"field": "host", "message": f"host is limited to {HOST_MAX} characters"})
    if description and len(description) > DESCRIPTION_MAX:
        errors.append({"field": "description",
                       "message": f"description is limited to {DESCRIPTION_MAX} characters"})
    return errors


def validate_group(name, icon, name_sent=True, icon_sent=True):
    """Group name is required (and limited); the group icon is only limited."""
    errors = []
    if name_sent:
        if not (name or "").strip():
            errors.append({"field": "name", "message": "name is required"})
        elif len(name.strip()) > GROUP_NAME_MAX:
            errors.append({"field": "name", "message": f"name is limited to {GROUP_NAME_MAX} characters"})
    if icon_sent and icon and len(icon) > GROUP_ICON_MAX:
        errors.append({"field": "icon", "message": f"icon is limited to {GROUP_ICON_MAX} characters"})
    return errors


def validate_url(field, value):
    """URLs are free text (as on the Edit page) apart from the column limit."""
    if value and len(value) > URL_MAX:
        return [{"field": field, "message": f"{field} is limited to {URL_MAX} characters"}]
    return []


def validate_image_repo_url(field, value):
    """The optional image repo override: an http(s) URL, at most 512 characters."""
    if not value:
        return []
    if len(value) > IMAGE_REPO_URL_MAX:
        return [{"field": field, "message": f"{field} is limited to {IMAGE_REPO_URL_MAX} characters"}]
    if not image_repo.valid_repo_override(value):
        return [{"field": field, "message": f"{field} must be an http:// or https:// URL"}]
    return []


def find_duplicate(host, name, exclude_id=None):
    """The entry occupying `(host, name)`, or None. An empty host is its own
    value (matched with IS NULL). An active entry wins over a soft-deleted one."""
    host_filter = ServiceEntry.host.is_(None) if host is None else ServiceEntry.host == host
    query = ServiceEntry.query.filter(host_filter, ServiceEntry.container_name == name)
    if exclude_id is not None:
        query = query.filter(ServiceEntry.id != exclude_id)
    return query.order_by(ServiceEntry.deleted_at.isnot(None), ServiceEntry.id).first()


def duplicate_message(existing, name, host):
    """Operator-facing text for a duplicate; mentions Restore for a deleted one."""
    where = f"on host '{host}'" if host else "with no host"
    if existing.deleted_at is not None:
        return (f"An entry for '{name}' {where} was deleted. "
                f"Restore it from Settings → Deleted instead of adding a new one.")
    return f"An entry for '{name}' {where} already exists."


def parse_sort_priority(raw):
    """`(value, error)`: blank is None; anything else must be a whole number."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    if isinstance(raw, bool):
        return None, "sort priority must be a number"
    if isinstance(raw, int):
        return raw, None
    try:
        return int(str(raw).strip()), None
    except ValueError:
        return None, "sort priority must be a number"


def resolve_icon(raw):
    """`(safe_filename_or_empty, error)` for an operator-supplied icon name."""
    raw = raw.strip() if isinstance(raw, str) else ""
    if not raw:
        return "", None
    safe = safe_icon_filename(raw)
    if not safe:
        return "", ICON_ERROR
    return safe, None


def download_icon(image_dir, icon, label):
    """Fetch `icon` (already a safe name) into `image_dir` if it isn't there."""
    icon_path = icon_path_in_dir(image_dir, icon)
    if not icon_path or os.path.exists(icon_path):
        return
    try:
        icon_url = f"https://raw.githubusercontent.com/homarr-labs/dashboard-icons/main/svg/{icon}"
        response = requests.get(icon_url, timeout=5)
        if response.status_code == 200:
            with open(icon_path, 'wb') as f:
                f.write(response.content)
            logger.info(f"⬇️ Downloaded user-supplied icon '{icon}' for '{label}'")
        else:
            logger.warning(f"⚠️ Icon '{icon}' not found (HTTP {response.status_code})")
    except Exception as e:
        logger.warning(f"⚠️ Failed to fetch icon '{icon}': {e}")


def get_or_create_group(name):
    """The group called `name`, created (and flushed for its id) if missing."""
    group = Group.query.filter_by(group_name=name).first()
    if not group:
        group = Group(group_name=name)
        db.session.add(group)
        db.session.flush()
    return group


def set_url(entry, which, new):
    """Set the internal/external URL as an operator edit and keep provenance.

    A value is `ui_edit` (highest precedence, never overwritten by the notifier
    or synthesizer); clearing it resets provenance to NULL so synthesis can
    refill it. Returns True when the URL changed.
    """
    attr = f"{which}url"
    new = (new or "").strip() or None
    if new == getattr(entry, attr):
        return False
    setattr(entry, attr, new)
    setattr(entry, f"{attr}_source", synthesizer.SOURCE_UI_EDIT if new else None)
    return True
