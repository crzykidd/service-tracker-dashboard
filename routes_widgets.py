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
    path = os.path.join('/app/widgets', widget_name, 'settings.json')
    if not os.path.exists(path):
        return jsonify([])  # Or 404 if you prefer

    with open(path) as f:
        try:
            config = json.load(f)
            return jsonify(config.get("available_fields", []))  # ✅ FIXED
        except Exception as e:
            current_app.logger.warning(f"Failed to load widget settings for {widget_name}: {e}")
            return jsonify([])
