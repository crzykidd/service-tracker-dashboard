"""Management API blueprint (v0.8.0, PRD 14).

Authenticated JSON endpoints under `/api/v1`. They accept ONLY
`Authorization: Bearer <admin API key>` (never the session cookie and never
the notifier's `api_token`), which is why the whole blueprint is CSRF-exempt.
`/api/v1/register` lives in `routes_api.py` and is unchanged.

Endpoint recipe:

    @mgmt_bp.route("/thing/<int:id>", methods=["PATCH"])
    @require_api_key("write")
    def patch_thing(id):
        ...
        audit("entry", id, {"container_name": [old, new]})
        return jsonify(...)

Every POST/PATCH/PUT/DELETE that reached a valid key is audited by the
blueprint's `after_request` hook, including 4xx responses.
"""

import logging
from datetime import datetime, timedelta
from functools import wraps

from flask import Blueprint, g, jsonify, request
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

import api_keys
from extensions import csrf, db
from models import ApiAudit

logger = logging.getLogger(__name__)

mgmt_bp = Blueprint("mgmt_api", __name__, url_prefix="/api/v1")
csrf.exempt(mgmt_bp)

LAST_USED_THROTTLE = timedelta(minutes=1)
WRITE_METHODS = {"POST", "PATCH", "PUT", "DELETE"}

# Field names (case-insensitive) or substrings whose values never reach the audit log.
_SECRET_NAMES = {"widget_api_key", "api_token", "secret_key", "key_hash", "password", "api_key"}
_SECRET_FRAGMENTS = ("secret", "password", "token")
MASK = "***"

_unauth_log = {}


# --- JSON errors ---------------------------------------------------------------


def json_error(status, message, details=None):
    """The blueprint's error shape: `{"error": str, "details": ...}`."""
    response = jsonify({"error": message, "details": details})
    response.status_code = status
    return response


_STATUS_MESSAGES = {
    400: "Bad request", 401: "Unauthorized", 403: "Forbidden", 404: "Not found",
    405: "Method not allowed", 409: "Conflict", 422: "Unprocessable entity",
}


def _http_error(exc):
    return json_error(exc.code, _STATUS_MESSAGES.get(exc.code, exc.name),
                      exc.description if exc.description else None)


for _code in _STATUS_MESSAGES:
    mgmt_bp.register_error_handler(_code, _http_error)


@mgmt_bp.errorhandler(ValidationError)
def _validation_error(exc):
    """pydantic failures (including `extra="forbid"` unknown keys) are a 400."""
    details = [
        {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg"), "type": e.get("type")}
        for e in exc.errors()
    ]
    return json_error(400, "Invalid request body", details)


@mgmt_bp.errorhandler(Exception)
def _unhandled(exc):
    if isinstance(exc, HTTPException):
        return _http_error(exc)
    logger.exception("Unhandled error in management API: %s %s", request.method, request.path)
    try:
        db.session.rollback()
    except Exception:
        pass
    return json_error(500, "Internal server error")


# --- auth ----------------------------------------------------------------------


def _bearer_token():
    header = request.headers.get("Authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip() or None


def _touch(key):
    """Record last use, at most once a minute per key."""
    now = datetime.utcnow()
    if key.last_used_at is not None and now - key.last_used_at < LAST_USED_THROTTLE:
        return
    key.last_used_at = now
    key.last_used_ip = (request.remote_addr or "")[:64] or None
    db.session.commit()


def _unauthorized():
    ip = request.remote_addr
    now = datetime.utcnow()
    logger.info("401 - Unauthorized management API access from %s to %s", ip, request.path)
    last = _unauth_log.get(ip)
    if not last or now - last > timedelta(minutes=2):
        logger.warning("Repeated unauthorized management API access from %s", ip)
        _unauth_log[ip] = now
    response = json_error(401, "Unauthorized", "Send 'Authorization: Bearer <API key>'.")
    response.headers["WWW-Authenticate"] = "Bearer"
    return response


def require_api_key(scope):
    """Gate a view on an admin API key of at least `scope` ("read" or "write").

    Reads only the Authorization header: sessions and the notifier token do
    not authenticate here. Sets `g.api_key`.
    """
    if scope not in api_keys.SCOPES:
        raise ValueError(f"unknown scope {scope!r}")

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            key = api_keys.verify(_bearer_token())
            if key is None:
                return _unauthorized()
            g.api_key = key
            # Snapshot now: the audit hook must not depend on ORM state later.
            g.api_key_id, g.api_key_name = key.id, key.name
            _touch(key)
            if not api_keys.scope_allows(key.scope, scope):
                logger.info("403 - API key '%s' (%s) lacks '%s' scope for %s %s",
                            g.api_key_name, key.prefix, scope, request.method, request.path)
                return json_error(403, "Forbidden",
                                  f"This endpoint needs a '{scope}' key; this key is '{key.scope}'.")
            return view(*args, **kwargs)

        return wrapped

    return decorator


# --- audit ---------------------------------------------------------------------


def _is_secret_field(name):
    n = str(name).lower()
    return n in _SECRET_NAMES or any(f in n for f in _SECRET_FRAGMENTS)


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def audit(object_type, object_id=None, changes=None):
    """Describe what this request changed; written by the after_request hook.

    `changes` is `{field: [old, new]}`. Values of secret fields are replaced
    with "***" here, so a secret never sits in `g` or the database.
    """
    masked = {}
    for field, pair in (changes or {}).items():
        if _is_secret_field(field):
            masked[str(field)] = [MASK, MASK]
        else:
            masked[str(field)] = _jsonable(pair)
    g.audit = {
        "object_type": object_type,
        "object_id": None if object_id is None else str(object_id),
        "changes": masked or None,
    }


def audit_response(response):
    """after_request hook: one `ApiAudit` row per authenticated write request."""
    key_id = g.get("api_key_id")
    if key_id is None or request.method not in WRITE_METHODS:
        return response
    info = g.get("audit") or {}
    try:
        db.session.add(ApiAudit(
            ts=datetime.utcnow(),
            api_key_id=key_id,
            key_name=g.get("api_key_name"),
            method=request.method,
            path=request.path[:255],
            object_type=(info.get("object_type") or None) and info["object_type"][:32],
            object_id=(info.get("object_id") or None) and info["object_id"][:64],
            status_code=response.status_code,
            changes=info.get("changes"),
        ))
        db.session.commit()
    except Exception:
        logger.exception("Failed to write API audit row for %s %s", request.method, request.path)
        try:
            db.session.rollback()
        except Exception:
            pass
    return response


mgmt_bp.after_request(audit_response)


# --- endpoints -----------------------------------------------------------------


@mgmt_bp.route("/whoami", methods=["GET"])
@require_api_key("read")
def whoami():
    key = g.api_key
    return jsonify({"name": key.name, "prefix": key.prefix, "scope": key.scope})
