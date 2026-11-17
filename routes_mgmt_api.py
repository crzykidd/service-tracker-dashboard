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

from flask import Blueprint, current_app, g, jsonify, request
from pydantic import ValidationError
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.exceptions import HTTPException

import api_keys
import check_form
import entry_rules
import health_history
import jobs
import mgmt_openapi
import routes_api
import settings_loader
import settings_store
import synthesizer
import widget_rules
from extensions import csrf, db
from health_state import entry_health
from image_utils import fetch_icon_if_missing
from mgmt_schemas import (
    NOTIFIER_OWNED_FIELDS,
    CheckPatch,
    EntryCreate,
    EntryPatch,
    ExposureSettingsPut,
    GroupCreate,
    GroupPatch,
    ServiceCheckCreate,
    WidgetPut,
)
from mgmt_serializers import (
    check_out,
    entry_detail_out,
    entry_out,
    group_out,
    widget_instance_out,
    widget_out,
)
from models import (
    CHECK_KIND_CONTAINER,
    CHECK_KIND_SERVICE,
    SOURCE_MANUAL,
    SOURCE_NOTIFIER,
    URL_CHECK_KINDS,
    ApiAudit,
    Group,
    HealthCheck,
    HealthResult,
    ServiceEntry,
    Widget,
    WidgetValue,
    check_counts,
    ensure_url_checks,
    hard_delete_entry,
)
from view_helpers import VALID_STATUS_FILTERS, matches_status

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


class ApiError(Exception):
    """Raise anywhere in a management view to answer with `json_error`."""

    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status, self.message, self.details = status, message, details


@mgmt_bp.errorhandler(ApiError)
def _api_error(exc):
    return json_error(exc.status, exc.message, exc.details)


def abort(status, message):
    raise ApiError(status, message)


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
                # Which key it was is recorded in the audit log (writes) and as
                # the key's last-used time; nothing key-derived is logged here
                # (CodeQL py/clear-text-logging-sensitive-data).
                logger.info("403 - API key lacks '%s' scope for %s %s",
                            scope, request.method, request.path)
                return json_error(403, "Forbidden",
                                  f"This endpoint needs a '{scope}' key; this key is '{key.scope}'.")
            return view(*args, **kwargs)

        wrapped.required_scope = scope   # read by the OpenAPI completeness test
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


@mgmt_bp.route("/openapi.json", methods=["GET"])
def openapi_spec():
    """The OpenAPI 3.1 description of this blueprint. Public: shapes, not data."""
    version = (current_app.config.get("VERSION_INFO") or {}).get("version") or ""
    return jsonify(mgmt_openapi.build_spec(str(version)))


@mgmt_bp.route("/whoami", methods=["GET"])
@require_api_key("read")
def whoami():
    key = g.api_key
    version = (current_app.config.get("VERSION_INFO") or {}).get("version") or "unknown"
    return jsonify({"name": key.name, "prefix": key.prefix, "scope": key.scope,
                    "version": str(version)})


# --- shared helpers --------------------------------------------------------------

DEFAULT_LIMIT = 200
MAX_LIMIT = 1000

# Validator field names -> the API's field names.
_API_FIELD = {"interval": "interval_seconds", "timeout": "timeout_seconds", "verify": "verify_tls"}
_CHECK_FIELD_TO_VALIDATOR = {
    "enabled": "enabled", "mode": "mode", "interval_seconds": "interval",
    "timeout_seconds": "timeout", "verify_tls": "verify",
    "name": "name", "check_type": "check_type", "target": "target",
    "dns_name": "dns_name", "dns_record_type": "dns_record_type",
    "dns_expected_rcode": "dns_expected_rcode", "dns_expected_answer": "dns_expected_answer",
    "cert_min_days": "cert_min_days",
}
_URL_CHECK_PATCHABLE = {"enabled", "mode", "interval_seconds", "timeout_seconds", "verify_tls",
                        "cert_min_days"}
_CONTAINER_CHECK_PATCHABLE = {"enabled", "interval_seconds"}
_NOT_NULL = {"enabled", "verify_tls", "mode", "check_type", "target"}


def _prefixed(problems, prefix):
    """Validator errors with API field names, under `prefix` (e.g. `checks.0.`)."""
    return [{"field": prefix + _API_FIELD.get(e["field"], e["field"]), "message": e["message"]}
            for e in problems]


def _fail(errors, message="Invalid request body"):
    """400 listing every `{field, message}` problem, in the same shape as a
    pydantic failure (`loc`, `msg`, `type`)."""
    details = [{"loc": [p for p in _API_FIELD.get(e["field"], e["field"]).split(".") if p],
                "msg": e["message"], "type": "value_error"} for e in errors]
    return json_error(400, message, details)


def _json_body():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        abort(400, "Send a JSON object as the request body.")
    return body


def _page_args():
    out = {}
    for name, default in (("limit", DEFAULT_LIMIT), ("offset", 0)):
        raw = request.args.get(name)
        if raw is None or raw == "":
            out[name] = default
            continue
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if value < (1 if name == "limit" else 0):
            abort(400, f"'{name}' must be a whole number{' of at least 1' if name == 'limit' else ' of at least 0'}.")
        out[name] = value
    out["limit"] = min(out["limit"], MAX_LIMIT)
    return out["limit"], out["offset"]


def _bool_arg(name):
    raw = (request.args.get(name) or "").strip().lower()
    if raw in ("", "0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    abort(400, f"'{name}' must be true or false.")


def _page(items, total, limit, offset):
    return jsonify({"items": items, "total": total, "limit": limit, "offset": offset})


def _entry_query():
    return ServiceEntry.query.options(
        joinedload(ServiceEntry.group),
        selectinload(ServiceEntry.checks),
    )


def _load_entry(id, detail=False):
    query = _entry_query()
    if detail:
        query = query.options(selectinload(ServiceEntry.exposures), joinedload(ServiceEntry.widget))
    entry = query.filter(ServiceEntry.id == id).first()
    if entry is None:
        abort(404, f"No entry with id {id}.")
    return entry


def _require_active(entry):
    if entry.deleted_at is not None:
        return json_error(409, "This entry is deleted; restore it first.", {"id": entry.id})
    return None


def _diff(before, after):
    return {k: [before.get(k), after.get(k)] for k in after if before.get(k) != after.get(k)}


def _entry_snapshot(entry):
    return {
        "name": entry.container_name,
        "host": entry.host,
        "description": entry.description,
        "group": entry.group.group_name if entry.group else None,
        "internalurl": entry.internalurl,
        "externalurl": entry.externalurl,
        "icon": entry.image_icon or None,
        "sort_priority": entry.sort_priority,
        "locked": bool(entry.is_static),
    }


def _check_snapshot(check):
    cfg = check.to_config()
    cfg.pop("kind", None)
    return cfg


def _settings_dict(model, fields, defaults=None):
    """Validator input from the fields a request actually sent (None means
    "not sent" except for the nullable interval/timeout)."""
    d = dict(defaults or {})
    sent = model.model_fields_set
    for api_name, validator_name in fields.items():
        if api_name in sent:
            d[validator_name] = getattr(model, api_name)
    return d


def _service_check_input(c: ServiceCheckCreate):
    return {
        "name": c.name, "check_type": c.check_type, "target": c.target, "mode": c.mode,
        "enabled": c.enabled, "verify": c.verify_tls,
        "interval": c.interval_seconds, "timeout": c.timeout_seconds,
        "dns_name": c.dns_name, "dns_record_type": c.dns_record_type,
        "dns_expected_rcode": c.dns_expected_rcode, "dns_expected_answer": c.dns_expected_answer,
        "cert_min_days": c.cert_min_days,
    }


def _ensure_icon(image_dir, icon, name):
    """Download a named icon, or derive one from the entry name (as Add does)."""
    if icon:
        entry_rules.download_icon(image_dir, icon, name)
        return icon
    derived = name.lower().replace(" ", "-")
    return fetch_icon_if_missing(derived, image_dir, logger, debug=current_app.debug) or ""


# --- entries -------------------------------------------------------------------


@mgmt_bp.route("/entries", methods=["GET"])
@require_api_key("read")
def list_entries():
    limit, offset = _page_args()
    status = (request.args.get("status") or "all").strip().lower()
    if status not in VALID_STATUS_FILTERS:
        abort(400, f"'status' must be one of: {', '.join(VALID_STATUS_FILTERS)}.")
    source = (request.args.get("source") or "all").strip().lower()
    if source not in ("all", "notifier", "manual"):
        abort(400, "'source' must be one of: all, notifier, manual.")
    include_deleted, deleted_only = _bool_arg("include_deleted"), _bool_arg("deleted_only")

    query = _entry_query()
    if deleted_only:
        query = query.filter(ServiceEntry.deleted_at.isnot(None))
    elif not include_deleted:
        query = query.filter(ServiceEntry.deleted_at.is_(None))
    if source != "all":
        query = query.filter(ServiceEntry.source == (SOURCE_MANUAL if source == "manual" else SOURCE_NOTIFIER))
    if request.args.get("host"):
        query = query.filter(ServiceEntry.host == request.args["host"])
    if request.args.get("group"):
        query = query.join(Group, ServiceEntry.group_id == Group.id).filter(Group.group_name == request.args["group"])
    q = (request.args.get("q") or "").strip()
    if q:
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        query = query.filter(db.or_(
            ServiceEntry.container_name.ilike(like, escape="\\"),
            ServiceEntry.host.ilike(like, escape="\\"),
            ServiceEntry.stack_name.ilike(like, escape="\\"),
            ServiceEntry.description.ilike(like, escape="\\"),
        ))
    query = query.order_by(ServiceEntry.id)

    if status == "all":
        total = query.order_by(None).count()
        rows = query.limit(limit).offset(offset).all()
    else:
        # The health state is derived, so filter after loading (checks are eager-loaded).
        matching = [e for e in query.all() if matches_status(e, status)]
        total = len(matching)
        rows = matching[offset:offset + limit]
    return _page([entry_out(e) for e in rows], total, limit, offset)


@mgmt_bp.route("/entries/<int:id>", methods=["GET"])
@require_api_key("read")
def get_entry(id):
    return jsonify(entry_detail_out(_load_entry(id, detail=True)))


@mgmt_bp.route("/entries", methods=["POST"])
@require_api_key("write")
def create_entry():
    data = EntryCreate.model_validate(_json_body())
    name = data.name.strip()
    host = (data.host or "").strip() or None
    description = (data.description or "").strip() or None
    internalurl = (data.internalurl or "").strip() or None
    externalurl = (data.externalurl or "").strip() or None
    group_name = (data.group or "").strip() or None

    errors = entry_rules.validate_basic(name, host, description)
    errors += entry_rules.validate_url("internalurl", internalurl)
    errors += entry_rules.validate_url("externalurl", externalurl)
    icon, icon_error = entry_rules.resolve_icon(data.icon)
    if icon_error:
        errors.append({"field": "icon", "message": icon_error})
    if group_name and len(group_name) > 100:
        errors.append({"field": "group", "message": "group is limited to 100 characters"})

    url_values = {}
    for which in ("internal", "external"):
        settings = getattr(data.url_checks, which) if data.url_checks else None
        if settings is None:
            continue
        d = _settings_dict(settings, {k: v for k, v in _CHECK_FIELD_TO_VALIDATOR.items()
                                      if k in _URL_CHECK_PATCHABLE})
        values, problems = check_form.validate_url_check_settings(d)
        url_values[which] = values
        errors += _prefixed(problems, f"url_checks.{which}.")
    service_values = []
    if len(data.checks) > check_form.MAX_SERVICE_CHECKS:
        errors.append({"field": "checks", "message":
                       f"a service can have at most {check_form.MAX_SERVICE_CHECKS} service checks"})
    for i, c in enumerate(data.checks[:check_form.MAX_SERVICE_CHECKS]):
        values, problems = check_form.validate_service_check(_service_check_input(c))
        service_values.append(values)
        errors += _prefixed(problems, f"checks.{i}.")
    if errors:
        return _fail(errors)

    existing = entry_rules.find_duplicate(host, name)
    if existing:
        return json_error(409, entry_rules.duplicate_message(existing, name, host),
                          {"id": existing.id, "deleted": existing.deleted_at is not None})

    icon = _ensure_icon(current_app.config["IMAGE_DIR"], icon, name)

    with routes_api._UPSERT_LOCK:
        existing = entry_rules.find_duplicate(host, name)
        if existing:
            return json_error(409, entry_rules.duplicate_message(existing, name, host),
                              {"id": existing.id, "deleted": existing.deleted_at is not None})
        group = entry_rules.get_or_create_group(group_name) if group_name else None
        entry = ServiceEntry(
            host=host, container_name=name, description=description, source=SOURCE_MANUAL,
            internalurl=internalurl, externalurl=externalurl,
            internalurl_source=synthesizer.SOURCE_UI_EDIT if internalurl else None,
            externalurl_source=synthesizer.SOURCE_UI_EDIT if externalurl else None,
            last_updated=datetime.now(), group_id=group.id if group else None,
            image_icon=icon, sort_priority=data.sort_priority, is_static=data.locked,
        )
        ensure_url_checks(entry)
        for which, values in url_values.items():
            check_form.apply_check_values(entry.url_check(which), values)
        for values in service_values:
            entry.checks.append(check_form.new_service_check(values))
        db.session.add(entry)
        db.session.commit()
        entry_id = entry.id

    created = _entry_snapshot(entry)
    created["checks"] = [c["target"] for c in service_values]
    audit("entry", entry_id, {k: [None, v] for k, v in created.items() if v not in (None, [], False)})
    response = jsonify(entry_detail_out(_load_entry(entry_id, detail=True)))
    response.status_code = 201
    return response


@mgmt_bp.route("/entries/<int:id>", methods=["PATCH"])
@require_api_key("write")
def patch_entry(id):
    entry = _load_entry(id)
    audit("entry", id)
    body = _json_body()

    owned = sorted(k for k in body if k in NOTIFIER_OWNED_FIELDS)
    if owned:
        return json_error(
            400, "These fields belong to the notifier or are derived and cannot be changed: "
                 + ", ".join(owned) + ".",
            [{"loc": [k], "msg": "not editable", "type": "read_only"} for k in owned])
    data = EntryPatch.model_validate(body)
    sent = data.model_fields_set

    if (resp := _require_active(entry)) is not None:
        return resp
    if entry.source != SOURCE_MANUAL and {"name", "host"} & sent:
        fields = sorted({"name", "host"} & sent)
        return json_error(
            400, "Name and host can only be changed on manual entries; this one is reported by the notifier.",
            [{"loc": [k], "msg": "only editable on manual entries", "type": "read_only"} for k in fields])

    errors = []
    if "name" in sent and data.name is None:
        errors.append({"field": "name", "message": "name is required"})
    new_name = data.name.strip() if "name" in sent and data.name is not None else entry.container_name
    new_host = ((data.host or "").strip() or None) if "host" in sent else entry.host
    new_description = ((data.description or "").strip() or None) if "description" in sent else entry.description
    errors += entry_rules.validate_basic(new_name, new_host, new_description)
    new_urls = {}
    for which in ("internal", "external"):
        if f"{which}url" in sent:
            value = (getattr(data, f"{which}url") or "").strip() or None
            errors += entry_rules.validate_url(f"{which}url", value)
            new_urls[which] = value
    icon = None
    if "icon" in sent:
        icon, icon_error = entry_rules.resolve_icon(data.icon)
        if icon_error:
            errors.append({"field": "icon", "message": icon_error})
    group_name = (data.group or "").strip() or None if "group" in sent else None
    if group_name and len(group_name) > 100:
        errors.append({"field": "group", "message": "group is limited to 100 characters"})
    if "locked" in sent and data.locked is None:
        errors.append({"field": "locked", "message": "locked must be true or false"})
    if errors:
        return _fail(errors)

    if icon:
        entry_rules.download_icon(current_app.config["IMAGE_DIR"], icon, new_name)

    with routes_api._UPSERT_LOCK:
        if ({"name", "host"} & sent) and (new_name, new_host) != (entry.container_name, entry.host):
            existing = entry_rules.find_duplicate(new_host, new_name, exclude_id=entry.id)
            if existing:
                return json_error(409, entry_rules.duplicate_message(existing, new_name, new_host),
                                  {"id": existing.id, "deleted": existing.deleted_at is not None})
        before = _entry_snapshot(entry)
        if "name" in sent:
            entry.container_name = new_name
        if "host" in sent:
            entry.host = new_host
        if "description" in sent:
            entry.description = new_description
        if "group" in sent:
            entry.group = entry_rules.get_or_create_group(group_name) if group_name else None
        if new_urls:
            ensure_url_checks(entry)
        for which, value in new_urls.items():
            if entry_rules.set_url(entry, which, value):
                # A changed URL is a new target: re-check it at the next tick.
                entry.url_check(which).last_checked_at = None
        if "icon" in sent:
            entry.image_icon = icon or ""
        if "sort_priority" in sent:
            entry.sort_priority = data.sort_priority
        if "locked" in sent and data.locked is not None:
            was_locked = entry.is_static
            entry.is_static = data.locked
            if was_locked and not entry.is_static and entry.container_check is not None:
                entry.container_check.last_checked_at = None
        entry.last_updated = datetime.now()
        if new_urls:
            # A cleared URL has source NULL; refill from any exposure rows.
            synthesizer.synthesize_for_entry(entry)
        changes = _diff(before, _entry_snapshot(entry))
        db.session.commit()

    audit("entry", id, changes)
    return jsonify(entry_detail_out(_load_entry(id, detail=True)))


@mgmt_bp.route("/entries/<int:id>", methods=["DELETE"])
@require_api_key("write")
def delete_entry(id):
    entry = _load_entry(id)
    audit("entry", id)
    permanent = _bool_arg("permanent")
    with routes_api._UPSERT_LOCK:
        if permanent:
            if entry.deleted_at is None:
                return json_error(409, "Only an already deleted entry can be permanently deleted. "
                                       "Delete it first, then repeat with ?permanent=true.", {"id": id})
            name = entry.container_name
            hard_delete_entry(entry)
            db.session.commit()
            audit("entry", id, {"name": [name, None], "permanent": [False, True]})
            return jsonify({"id": id, "permanent": True})
        if entry.deleted_at is not None:
            return json_error(409, "This entry is already deleted. Use ?permanent=true to remove it for good.",
                              {"id": id})
        entry.deleted_at = datetime.now()
        db.session.commit()
    audit("entry", id, {"deleted_at": [None, entry.deleted_at.replace(microsecond=0).isoformat()]})
    return jsonify(entry_out(_load_entry(id)))


@mgmt_bp.route("/entries/<int:id>/restore", methods=["POST"])
@require_api_key("write")
def restore_entry(id):
    entry = _load_entry(id)
    audit("entry", id)
    with routes_api._UPSERT_LOCK:
        if entry.deleted_at is None:
            return json_error(409, "This entry is not deleted.", {"id": id})
        clash = ServiceEntry.active().filter_by(host=entry.host, container_name=entry.container_name).first()
        if clash is not None:
            return json_error(
                409, f"Cannot restore '{entry.container_name}': an active entry with that name and host exists.",
                {"id": clash.id})
        deleted_at = entry.deleted_at
        entry.deleted_at = None
        db.session.commit()
    audit("entry", id, {"deleted_at": [deleted_at.replace(microsecond=0).isoformat(), None]})
    return jsonify(entry_out(_load_entry(id)))


# --- checks --------------------------------------------------------------------


@mgmt_bp.route("/entries/<int:id>/checks", methods=["GET"])
@require_api_key("read")
def list_checks(id):
    entry = _load_entry(id)
    limit, offset = _page_args()
    checks = entry.checks
    return _page([check_out(entry, c) for c in checks[offset:offset + limit]], len(checks), limit, offset)


@mgmt_bp.route("/entries/<int:id>/checks", methods=["POST"])
@require_api_key("write")
def add_check(id):
    entry = _load_entry(id)
    audit("entry", id)
    data = ServiceCheckCreate.model_validate(_json_body())
    if (resp := _require_active(entry)) is not None:
        return resp
    values, problems = check_form.validate_service_check(_service_check_input(data))
    if problems:
        return _fail(problems)
    with routes_api._UPSERT_LOCK:
        if len(entry.service_checks) >= check_form.MAX_SERVICE_CHECKS:
            return json_error(409, f"A service can have at most {check_form.MAX_SERVICE_CHECKS} service checks.",
                              {"id": id})
        check = check_form.new_service_check(values)
        entry.checks.append(check)
        db.session.commit()
    audit("check", check.id, {"entry_id": [None, id], **{k: [None, v] for k, v in _check_snapshot(check).items()
                                                        if v is not None}})
    response = jsonify(check_out(entry, check))
    response.status_code = 201
    return response


def _load_check(id):
    check = db.session.get(HealthCheck, id)
    if check is None:
        abort(404, f"No check with id {id}.")
    return check


@mgmt_bp.route("/checks/<int:id>", methods=["PATCH"])
@require_api_key("write")
def patch_check(id):
    check = _load_check(id)
    entry = check.service_entry
    audit("check", id)
    body = _json_body()
    data = CheckPatch.model_validate(body)
    sent = data.model_fields_set
    if (resp := _require_active(entry)) is not None:
        return resp

    if check.kind in URL_CHECK_KINDS:
        allowed, label = _URL_CHECK_PATCHABLE, "a URL check"
    elif check.kind == CHECK_KIND_CONTAINER:
        allowed, label = _CONTAINER_CHECK_PATCHABLE, "the container check"
    else:
        allowed, label = set(_CHECK_FIELD_TO_VALIDATOR), "a service check"
    blocked = sorted(sent - allowed)
    if blocked:
        return json_error(
            400, f"These fields cannot be changed on {label}: {', '.join(blocked)}.",
            [{"loc": [k], "msg": "not editable on this kind of check", "type": "read_only"} for k in blocked])
    nulls = sorted(k for k in sent if k in _NOT_NULL and getattr(data, k) is None)
    if nulls:
        return _fail([{"field": k, "message": f"{k} cannot be null"} for k in nulls])

    current = {
        "enabled": check.enabled, "mode": check.mode, "verify": check.verify_tls is not False,
        "interval": check.interval_seconds, "timeout": check.timeout_seconds,
        "name": check.name, "check_type": check.check_type, "target": check.target,
        "dns_name": check.dns_name, "dns_record_type": check.dns_record_type,
        "dns_expected_rcode": check.dns_expected_rcode,
        "dns_expected_answer": check.dns_expected_answer,
        "cert_min_days": check.cert_min_days,
    }
    merged = _settings_dict(data, _CHECK_FIELD_TO_VALIDATOR, current)
    if (check.kind == CHECK_KIND_SERVICE and "cert_min_days" not in sent
            and merged.get("check_type") != "http"):
        # Switching a check away from HTTP drops its certificate condition.
        merged["cert_min_days"] = None
    if check.kind == CHECK_KIND_CONTAINER:
        values, problems = check_form.validate_container_check(merged)
    elif check.kind == CHECK_KIND_SERVICE:
        values, problems = check_form.validate_service_check(merged)
    else:
        values, problems = check_form.validate_url_check_settings(merged)
    if problems:
        return _fail(problems)

    with routes_api._UPSERT_LOCK:
        before = _check_snapshot(check)
        check_form.apply_check_values(check, values)
        changes = _diff(before, _check_snapshot(check))
        db.session.commit()
    audit("check", id, changes)
    return jsonify(check_out(entry, check))


@mgmt_bp.route("/checks/<int:id>", methods=["DELETE"])
@require_api_key("write")
def delete_check(id):
    check = _load_check(id)
    entry = check.service_entry
    audit("check", id)
    if (resp := _require_active(entry)) is not None:
        return resp
    if check.kind != CHECK_KIND_SERVICE:
        return json_error(
            409, "Only service checks can be deleted. Disable a URL or container check instead "
                 "(PATCH enabled=false).", {"id": id, "kind": check.kind})
    with routes_api._UPSERT_LOCK:
        snapshot = _check_snapshot(check)
        entry.checks.remove(check)
        db.session.commit()
    audit("check", id, {k: [v, None] for k, v in snapshot.items() if v is not None})
    return jsonify({"id": id, "deleted": True})


@mgmt_bp.route("/entries/<int:id>/checks/run", methods=["POST"])
@require_api_key("write")
def run_checks(id):
    entry = _load_entry(id)
    audit("entry", id)
    if (resp := _require_active(entry)) is not None:
        return resp
    ids = [c.id for c in entry.checks if check_counts(entry, c)]
    jobs.request_run(ids)
    audit("entry", id, {"check_run_requested": [None, ids]})
    return jsonify({"ok": True, "queued": len(ids),
                    "requested_at": health_history.iso_z(datetime.utcnow())})


# --- health --------------------------------------------------------------------


@mgmt_bp.route("/entries/<int:id>/health", methods=["GET"])
@require_api_key("read")
def entry_health_payload(id):
    entry = _load_entry(id)
    range_name = request.args.get("range", "24h")
    if range_name not in health_history.RANGES:
        abort(400, f"'range' must be one of: {', '.join(health_history.RANGES)}.")
    return jsonify(health_history.entry_payload(entry, range_name))


def _failing_since(check):
    """Start of the current run of failures: the earliest failed sample after
    the latest passing one (falls back to the last check time)."""
    last_ok = (
        db.session.query(db.func.max(db.func.coalesce(HealthResult.ts_end, HealthResult.ts)))
        .filter(HealthResult.check_id == check.id, HealthResult.ok.is_(True))
        .scalar()
    )
    query = db.session.query(db.func.min(HealthResult.ts)).filter(
        HealthResult.check_id == check.id, HealthResult.ok.is_(False))
    if last_ok is not None:
        query = query.filter(HealthResult.ts > last_ok)
    return health_history.iso_z(query.scalar() or check.last_checked_at)


@mgmt_bp.route("/health/summary", methods=["GET"])
@require_api_key("read")
def health_summary():
    entries = ServiceEntry.active().options(selectinload(ServiceEntry.checks)).order_by(ServiceEntry.id).all()
    counts = {"total": len(entries)}
    for key, status in (("passing", "healthy"), ("failing", "failing"),
                        ("unknown", "unknown"), ("stale", "stale")):
        counts[key] = sum(1 for e in entries if matches_status(e, status))
    failing = []
    for e in entries:
        if not matches_status(e, "failing"):
            continue
        failures = [
            {"check": c.name or c.kind, "kind": c.kind, "message": c.last_message, "since": _failing_since(c)}
            for c in e.checks if check_counts(e, c) and c.last_ok is False
        ]
        failing.append({"id": e.id, "name": e.container_name, "host": e.host, "state": entry_health(e).state,
                        "failures": failures})
    return jsonify({"counts": counts, "failing": failing})


# --- groups --------------------------------------------------------------------

def _group_problems(name, icon, name_sent=True, icon_sent=True):
    return entry_rules.validate_group(name, icon, name_sent, icon_sent)


def _group_snapshot(group):
    return {"name": group.group_name, "sort_priority": group.group_sort_priority, "icon": group.group_icon}


def _load_group(id):
    group = db.session.get(Group, id)
    if group is None:
        abort(404, f"No group with id {id}.")
    return group


def _name_taken(name, exclude_id=None):
    query = Group.query.filter(Group.group_name == name)
    if exclude_id is not None:
        query = query.filter(Group.id != exclude_id)
    return query.first()


@mgmt_bp.route("/groups", methods=["GET"])
@require_api_key("read")
def list_groups():
    limit, offset = _page_args()
    query = Group.query.order_by(Group.group_sort_priority.asc().nulls_last(), Group.group_name.asc())
    total = query.count()
    return _page([group_out(g_) for g_ in query.limit(limit).offset(offset).all()], total, limit, offset)


@mgmt_bp.route("/groups", methods=["POST"])
@require_api_key("write")
def create_group():
    audit("group")
    data = GroupCreate.model_validate(_json_body())
    errors = _group_problems(data.name, data.icon)
    if errors:
        return _fail(errors)
    name = data.name.strip()
    with routes_api._UPSERT_LOCK:
        existing = _name_taken(name)
        if existing:
            return json_error(409, f"A group named '{name}' already exists.", {"id": existing.id})
        group = Group(group_name=name, group_icon=data.icon or None, group_sort_priority=data.sort_priority)
        db.session.add(group)
        db.session.commit()
    audit("group", group.id, _diff({}, _group_snapshot(group)))
    response = jsonify(group_out(group))
    response.status_code = 201
    return response


@mgmt_bp.route("/groups/<int:id>", methods=["PATCH"])
@require_api_key("write")
def patch_group(id):
    audit("group", id)
    group = _load_group(id)
    data = GroupPatch.model_validate(_json_body())
    sent = data.model_fields_set
    errors = _group_problems(data.name, data.icon, "name" in sent, "icon" in sent)
    if errors:
        return _fail(errors)
    before = _group_snapshot(group)
    with routes_api._UPSERT_LOCK:
        if "name" in sent:
            name = data.name.strip()
            existing = _name_taken(name, exclude_id=id)
            if existing:
                return json_error(409, f"A group named '{name}' already exists.", {"id": existing.id})
            group.group_name = name
        if "icon" in sent:
            group.group_icon = data.icon or None
        if "sort_priority" in sent:
            group.group_sort_priority = data.sort_priority
        db.session.commit()
    audit("group", id, _diff(before, _group_snapshot(group)))
    return jsonify(group_out(group))


@mgmt_bp.route("/groups/<int:id>", methods=["DELETE"])
@require_api_key("write")
def delete_group(id):
    """Refuses while active entries use the group, as the Settings page does;
    `?force=true` ungroups them first. Deleted entries are always ungrouped."""
    audit("group", id)
    group = _load_group(id)
    force = _bool_arg("force")
    with routes_api._UPSERT_LOCK:
        active = [e for e in group.services if e.deleted_at is None]
        if active and not force:
            return json_error(409, "Cannot delete a group that has entries. Move them first, "
                                   "or repeat with ?force=true to ungroup them.",
                              {"id": id, "entry_count": len(active)})
        for e in group.services:
            e.group_id = None
        name = group.group_name
        db.session.delete(group)
        db.session.commit()
    audit("group", id, {"name": [name, None], "ungrouped_entries": [0, len(active)]})
    return jsonify({"id": id, "deleted": True, "ungrouped_entries": len(active)})


# --- widgets -------------------------------------------------------------------


@mgmt_bp.route("/widgets/types", methods=["GET"])
@require_api_key("read")
def list_widget_types():
    types = widget_rules.list_types()
    return _page(types, len(types), len(types), 0)


@mgmt_bp.route("/widgets", methods=["GET"])
@require_api_key("read")
def list_widgets():
    limit, offset = _page_args()
    query = Widget.query.options(selectinload(Widget.services)).order_by(Widget.id.asc())
    total = query.count()
    items = [widget_instance_out(w) for w in query.limit(limit).offset(offset).all()]
    return _page(items, total, limit, offset)


def _widget_snapshot(widget):
    return {"type": widget.widget_name, "url": widget.widget_url,
            "fields": widget.widget_fields, "widget_api_key": widget.widget_api_key}


@mgmt_bp.route("/entries/<int:id>/widget", methods=["PUT"])
@require_api_key("write")
def put_entry_widget(id):
    audit("widget")
    entry = _load_entry(id, detail=True)
    data = WidgetPut.model_validate(_json_body())
    conflict = _require_active(entry)
    if conflict:
        return conflict
    plugin, errors = widget_rules.validate_widget(data.type, data.url, data.fields)
    if "widget_api_key" in data.model_fields_set:
        errors += widget_rules.validate_api_key(data.widget_api_key)
    if errors:
        return _fail(errors)
    url = data.url.strip()
    fields = list(dict.fromkeys(data.fields))
    with routes_api._UPSERT_LOCK:
        widget = entry.widget
        created = widget is None
        before = {} if created else _widget_snapshot(widget)
        if created:
            widget = Widget(widget_name=plugin["type"], widget_url=url, widget_fields=fields,
                            widget_api_key=data.widget_api_key)
            db.session.add(widget)
            db.session.flush()
            entry.widget_id = widget.id
        else:
            widget.widget_name = plugin["type"]
            widget.widget_url = url
            widget.widget_fields = fields
            if "widget_api_key" in data.model_fields_set:
                widget.widget_api_key = data.widget_api_key
        db.session.commit()
    audit("widget", widget.id, {"entry_id": [None, id], **_diff(before, _widget_snapshot(widget))}
          if created else _diff(before, _widget_snapshot(widget)))
    response = jsonify(widget_out(widget))
    response.status_code = 201 if created else 200
    return response


@mgmt_bp.route("/entries/<int:id>/widget", methods=["DELETE"])
@require_api_key("write")
def delete_entry_widget(id):
    """Detach the entry's widget (kept, with its values, for re-attaching in
    Settings → Widgets); `?delete=true` removes it and its values."""
    audit("widget")
    entry = _load_entry(id, detail=True)
    delete = _bool_arg("delete")
    conflict = _require_active(entry)
    if conflict:
        return conflict
    widget = entry.widget
    if widget is None:
        abort(404, f"Entry {id} has no widget.")
    widget_id = widget.id
    with routes_api._UPSERT_LOCK:
        entry.widget_id = None
        removed = False
        if delete and not any(e.id != id for e in widget.services):
            WidgetValue.query.filter_by(widget_id=widget_id).delete()
            db.session.delete(widget)
            removed = True
        db.session.commit()
    audit("widget", widget_id, {"entry_id": [id, None], "deleted": [False, removed]})
    return jsonify({"entry_id": id, "widget_id": widget_id, "deleted": removed})


@mgmt_bp.route("/widgets/<int:id>", methods=["DELETE"])
@require_api_key("write")
def delete_widget(id):
    audit("widget", id)
    widget = db.session.get(Widget, id)
    if widget is None:
        abort(404, f"No widget with id {id}.")
    with routes_api._UPSERT_LOCK:
        if Widget.detached().filter(Widget.id == id).first() is None:
            return json_error(409, "Only a detached widget can be deleted. Detach it from its entry first.",
                              {"id": id, "entry_ids": sorted(e.id for e in widget.services)})
        name = widget.widget_name
        WidgetValue.query.filter_by(widget_id=id).delete()
        db.session.delete(widget)
        db.session.commit()
    audit("widget", id, {"type": [name, None]})
    return jsonify({"id": id, "deleted": True})


# --- runtime settings ----------------------------------------------------------


def _exposure_payload():
    return {
        "layer_directions": settings_store.get_layer_directions(),
        "host_overrides": settings_store.get_host_layer_overrides(),
        "discovered_layers": settings_store.discovered_layers(),
        "discovered_hosts": settings_store.discovered_hosts(),
        "valid_directions": list(settings_store.VALID_DIRECTIONS),
    }


@mgmt_bp.route("/settings/exposure", methods=["GET"])
@require_api_key("read")
def get_exposure_settings():
    return jsonify(_exposure_payload())


@mgmt_bp.route("/settings/exposure", methods=["PUT"])
@require_api_key("write")
def put_exposure_settings():
    """Replaces both mappings, as the Settings form does, then recomputes
    every service's synthesized URLs."""
    audit("exposure_settings")
    data = ExposureSettingsPut.model_validate(_json_body())
    errors = []
    valid = settings_store.VALID_DIRECTIONS
    for layer, direction in data.layer_directions.items():
        if not layer.strip():
            errors.append({"field": "layer_directions", "message": "layer names cannot be empty"})
        elif direction not in valid:
            errors.append({"field": f"layer_directions.{layer}",
                           "message": f"direction must be one of {', '.join(valid)}"})
    for host, layer_map in data.host_overrides.items():
        if not host.strip():
            errors.append({"field": "host_overrides", "message": "host names cannot be empty"})
        for layer, direction in layer_map.items():
            if not layer.strip():
                errors.append({"field": f"host_overrides.{host}", "message": "layer names cannot be empty"})
            elif direction not in valid:
                errors.append({"field": f"host_overrides.{host}.{layer}",
                               "message": f"direction must be one of {', '.join(valid)}"})
    if errors:
        return _fail(errors)
    before = {"layer_directions": settings_store.get_layer_directions(),
              "host_overrides": settings_store.get_host_layer_overrides()}
    with routes_api._UPSERT_LOCK:
        settings_store.save_exposure_settings(data.layer_directions, data.host_overrides)
        touched = synthesizer.recompute_all()
        db.session.commit()
    after = {"layer_directions": settings_store.get_layer_directions(),
             "host_overrides": settings_store.get_host_layer_overrides()}
    audit("exposure_settings", None, {**_diff(before, after), "recomputed": [None, touched]})
    return jsonify({**_exposure_payload(), "recomputed": touched})


_SECRET_SUFFIXES = ("_key", "_token", "_password", "_secret")


def _config_is_secret(name):
    n = name.lower()
    return n in settings_loader.SECRET_KEYS or n.endswith(_SECRET_SUFFIXES) or n in _SECRET_NAMES


@mgmt_bp.route("/config", methods=["GET"])
@require_api_key("read")
def get_config():
    """Effective startup settings (read-only). Secrets show as "***", or null
    when unset."""
    cfg = current_app.config
    from_env, from_file = cfg.get("CONFIG_FROM_ENV") or {}, cfg.get("CONFIG_FROM_FILE") or {}
    names = list(settings_loader.VALID_KEYS) + ["display_tools"]
    values, sources = {}, {}
    for name in names:
        value = cfg.get(name)
        values[name] = (MASK if value else None) if _config_is_secret(name) else value
        sources[name] = "env" if name in from_env else "file" if name in from_file else "default"
    sources["display_tools"] = "derived"
    version = (cfg.get("VERSION_INFO") or {}).get("version", "unknown")
    return jsonify({"version": version, "settings": values, "sources": sources})
