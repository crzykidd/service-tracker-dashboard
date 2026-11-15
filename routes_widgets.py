"""Widget configuration endpoints.

Owns the `widgets` blueprint. Currently a single read-only endpoint
that returns the available fields a widget plugin exposes; expected
to grow as the widget surface develops.
"""

import json
import os

from flask import Blueprint, current_app, jsonify
from flask_login import login_required

from routes_auth import is_admin_required

widgets_bp = Blueprint("widgets", __name__)


@widgets_bp.route('/widget_config/<widget_name>')
@login_required
@is_admin_required
def widget_config(widget_name):
    # Only names of directories actually present under the widgets dir are
    # accepted; anything else (traversal included) gets the empty list.
    widgets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'widgets')
    try:
        known = {d for d in os.listdir(widgets_dir) if d != '__pycache__' and os.path.isdir(os.path.join(widgets_dir, d))}
    except OSError:
        known = set()
    if widget_name not in known:
        return jsonify([])
    path = os.path.join(widgets_dir, widget_name, 'settings.json')
    if not os.path.exists(path):
        return jsonify([])  # Or 404 if you prefer

    with open(path) as f:
        try:
            config = json.load(f)
            return jsonify(config.get("available_fields", []))  # ✅ FIXED
        except Exception as e:
            current_app.logger.warning(f"Failed to load widget settings for {widget_name}: {e}")
            return jsonify([])
