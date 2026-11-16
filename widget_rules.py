"""Widget plugin discovery and validation, shared by the management API.

A widget type is a directory under `widgets/` that holds a `settings.json`
with `available_fields`. Filesystem paths are built only from names that
`os.listdir` returned, never from request values, so no user input reaches a
path (the same CodeQL-safe shape as `routes_widgets.widget_config`).

Validators return `{"field", "message"}` error dicts like `entry_rules`.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

WIDGETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "widgets")

URL_MAX = 255
API_KEY_MAX = 255


def _type_dirs():
    try:
        entries = sorted(os.listdir(WIDGETS_DIR))
    except OSError:
        return []
    return [d for d in entries if d != "__pycache__" and os.path.isdir(os.path.join(WIDGETS_DIR, d))]


def _load(dirname):
    """The plugin's settings as `{type, description, available_fields}`, or None."""
    try:
        with open(os.path.join(WIDGETS_DIR, dirname, "settings.json")) as f:
            config = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("Could not load widget settings for %s: %s", dirname, exc)
        return None
    if not isinstance(config, dict):
        return None
    fields = []
    for field in config.get("available_fields") or []:
        if isinstance(field, dict) and field.get("key"):
            fields.append({
                "key": str(field["key"]),
                "label": field.get("label") or str(field["key"]),
                "description": field.get("description"),
            })
    return {"type": dirname, "description": config.get("description"), "available_fields": fields}


def list_types():
    """Every widget plugin that has a readable settings.json."""
    return [t for t in (_load(d) for d in _type_dirs()) if t is not None]


def get_type(name):
    """The plugin called `name`, or None. `name` is matched against the
    directory listing; it is never used to build a path."""
    if not isinstance(name, str):
        return None
    dirname = next((d for d in _type_dirs() if d == name), None)
    return _load(dirname) if dirname is not None else None


def validate_widget(type_name, url, fields):
    """`(plugin, errors)`: the type must exist, the URL be present and the
    fields be a non-empty list of that plugin's field keys."""
    errors = []
    plugin = get_type(type_name)
    if plugin is None:
        errors.append({"field": "type", "message": "unknown widget type"})
    url = url.strip() if isinstance(url, str) else ""
    if not url:
        errors.append({"field": "url", "message": "url is required"})
    elif len(url) > URL_MAX:
        errors.append({"field": "url", "message": f"url is limited to {URL_MAX} characters"})
    if plugin is not None:
        valid = {f["key"] for f in plugin["available_fields"]}
        unknown = sorted({f for f in fields if f not in valid})
        if unknown:
            errors.append({"field": "fields", "message": "unknown fields for this widget type: "
                           + ", ".join(unknown)})
        if not fields:
            errors.append({"field": "fields", "message": "choose at least one field"})
    return plugin, errors


def validate_api_key(value):
    if value is not None and len(value) > API_KEY_MAX:
        return [{"field": "widget_api_key", "message": f"widget_api_key is limited to {API_KEY_MAX} characters"}]
    return []
