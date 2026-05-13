"""Process-level health endpoints.

Liveness/readiness checks for the running Flask process. These are
distinct from the URL health checks the scheduler runs against
registered services (those live in `jobs.py`).
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.route("/healthz", methods=["GET"])
def healthz():
    """Liveness probe. Returns 200 as long as the WSGI worker is up."""
    return jsonify({"status": "ok"}), 200
