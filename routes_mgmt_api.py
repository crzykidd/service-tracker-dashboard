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

import json
import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import Blueprint, Response, current_app, g, jsonify, request
from pydantic import ValidationError
from sqlalchemy.orm import joinedload, selectinload
from werkzeug.exceptions import HTTPException

import api_keys
import backups
import check_form
import entry_rules
import export_format
import health_history
import importer
import jobs
import mgmt_openapi
import notify
import routes_api
import settings_loader
import settings_store
import streams
import synthesizer
import version_check
import widget_rules
from api_version import API_REVISION, FEATURES
from extensions import csrf, db
from health_state import entry_health
from image_utils import fetch_icon_if_missing
from mgmt_schemas import (
    NOTIFIER_OWNED_FIELDS,
    BackupRunRequest,
    BackupSettingsPut,
    CheckPatch,
    EntryCreate,
    EntryPatch,
    EntryUnlinkRequest,
    ExposureSettingsPut,
    GroupCreate,
    GroupPatch,
    ImportApplyRequest,
    ImportPlanRequest,
    NotificationChannelCreate,
    NotificationChannelPatch,
    NotificationOrphanClearRequest,
    NotificationOrphanScanRequest,
    NotificationPurgeRequest,
    ServiceCheckCreate,
    StreamDisableRequest,
    StreamLinkRequest,
    StreamPatch,
    StreamSnapshotPut,
    UpdateCheckSettingsPut,
    WidgetPut,
)
from mgmt_serializers import (
    block_out,
    check_out,
    entry_detail_out,
    entry_out,
    group_out,
    notification_channel_out,
    offer_out,
    stream_out,
    widget_instance_out,
    widget_out,
)
from models import (
    CHECK_KIND_CONTAINER,
    CHECK_KIND_SERVICE,
    NAME_SOURCE_UI_EDIT,
    SOURCE_MANUAL,
    URL_CHECK_KINDS,
    VALID_SOURCES,
    ApiAudit,
    Group,
    HealthCheck,
    HealthResult,
    InventoryBlock,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    StreamLinkOffer,
    Widget,
    WidgetValue,
    check_counts,
    ensure_url_checks,
    hard_delete_entry,
)
from notify_purge import MAX_PREVIOUS_BASES, PurgeError
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
    405: "Method not allowed", 409: "Conflict", 413: "Request body too large",
    422: "Unprocessable entity",
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


@mgmt_bp.errorhandler(streams.StreamError)
def _stream_error(exc):
    return json_error(exc.status, exc.message, exc.details)


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
    if request.endpoint == "mgmt_api.put_stream_snapshot":
        return response     # a snapshot arrives every few minutes; the stream row keeps the counts (PRD 18.5)
    if request.endpoint == "mgmt_api.import_plan":
        return response     # a dry run: it reads and writes nothing
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


def _build_facts():
    """commit / channel / build_time / update, shared by whoami and config (additive fields)."""
    info = current_app.config.get("VERSION_INFO") or {}
    running = str(info.get("version") or "unknown")
    return {"commit": info.get("commit") or "unknown",
            "channel": info.get("channel") or "local",
            "build_time": info.get("build_time") or "unknown",
            "update": version_check.api_update(running)}


@mgmt_bp.route("/meta", methods=["GET"])
def meta():
    """Contract revision and features. Public, no DB access: no more than the headers say."""
    version = (current_app.config.get("VERSION_INFO") or {}).get("version") or "unknown"
    return jsonify({"std_version": str(version), "api_revision": API_REVISION,
                    "features": list(FEATURES)})


@mgmt_bp.route("/whoami", methods=["GET"])
@require_api_key("read")
def whoami():
    key = g.api_key
    version = (current_app.config.get("VERSION_INFO") or {}).get("version") or "unknown"
    return jsonify({"name": key.name, "prefix": key.prefix, "scope": key.scope,
                    "version": str(version), "api_revision": API_REVISION, **_build_facts()})


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
                        "cert_min_days", "ha_exclude"}
_CONTAINER_CHECK_PATCHABLE = {"enabled", "interval_seconds", "ha_exclude"}
# `ha_exclude` is not a probe setting: it has no validator, the routes write it directly.
_NOT_NULL = {"enabled", "verify_tls", "mode", "check_type", "target", "ha_exclude"}


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
        joinedload(ServiceEntry.stream),
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
        "ha_publish": bool(entry.ha_publish),
    }


def _check_snapshot(check):
    cfg = check.to_config()
    cfg.pop("kind", None)
    cfg["ha_exclude"] = bool(check.ha_exclude)
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
    if source != "all" and source not in VALID_SOURCES:
        abort(400, f"'source' must be one of: all, {', '.join(VALID_SOURCES)}.")
    include_deleted, deleted_only = _bool_arg("include_deleted"), _bool_arg("deleted_only")

    query = _entry_query()
    if deleted_only:
        query = query.filter(ServiceEntry.deleted_at.isnot(None))
    elif not include_deleted:
        query = query.filter(ServiceEntry.deleted_at.is_(None))
    if source != "all":
        query = query.filter(ServiceEntry.source == source)
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
        if settings.ha_exclude is not None:
            values["ha_exclude"] = settings.ha_exclude
        url_values[which] = values
        errors += _prefixed(problems, f"url_checks.{which}.")
    service_values = []
    if len(data.checks) > check_form.MAX_SERVICE_CHECKS:
        errors.append({"field": "checks", "message":
                       f"a service can have at most {check_form.MAX_SERVICE_CHECKS} service checks"})
    for i, c in enumerate(data.checks[:check_form.MAX_SERVICE_CHECKS]):
        values, problems = check_form.validate_service_check(_service_check_input(c))
        values["ha_exclude"] = c.ha_exclude
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
            ha_publish=data.ha_publish,
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
    if entry.is_docker and {"name", "host"} & sent:
        fields = sorted({"name", "host"} & sent)
        return json_error(
            400, "Name and host can only be changed on manual entries; this one is reported by the notifier.",
            [{"loc": [k], "msg": "only editable on manual entries", "type": "read_only"} for k in fields])
    if entry.is_stream and "host" in sent:
        return json_error(
            400, "Stream entries have no host; only the name can be changed.",
            [{"loc": ["host"], "msg": "not editable on stream entries", "type": "read_only"}])

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
    if "ha_publish" in sent and data.ha_publish is None:
        errors.append({"field": "ha_publish", "message": "ha_publish must be true or false"})
    if errors:
        return _fail(errors)

    if icon:
        entry_rules.download_icon(current_app.config["IMAGE_DIR"], icon, new_name)

    with routes_api._UPSERT_LOCK:
        # Stream entries are unique by stream key, not by (host, name) (PRD 18.6).
        if (({"name", "host"} & sent) and (new_name, new_host) != (entry.container_name, entry.host)
                and entry.stream_id is None):
            existing = entry_rules.find_duplicate(new_host, new_name, exclude_id=entry.id)
            if existing:
                return json_error(409, entry_rules.duplicate_message(existing, new_name, new_host),
                                  {"id": existing.id, "deleted": existing.deleted_at is not None})
        before = _entry_snapshot(entry)
        if "name" in sent:
            if entry.is_stream and new_name != entry.container_name:
                entry.name_source = NAME_SOURCE_UI_EDIT      # snapshots no longer write the name
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
        if "ha_publish" in sent and data.ha_publish is not None:
            entry.ha_publish = data.ha_publish
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
    block = _bool_arg("block")
    if block and permanent:
        abort(400, "'block' applies to the first delete; it cannot be combined with 'permanent'.")
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
        blocked = streams.soft_delete_entry(entry, block, actor=g.api_key_name)
        db.session.commit()
    changes = {"deleted_at": [None, entry.deleted_at.replace(microsecond=0).isoformat()]}
    if blocked:
        changes["stream_block"] = [None, entry.stream_key]
    audit("entry", id, changes)
    return jsonify(entry_out(_load_entry(id)))


@mgmt_bp.route("/entries/<int:id>/unlink", methods=["POST"])
@require_api_key("write")
def unlink_entry(id):
    """A stream entry goes back to being a manual entry (a linked one gets its host back)."""
    entry = _load_entry(id)
    audit("entry", id)
    data = _optional_body(EntryUnlinkRequest)
    with routes_api._UPSERT_LOCK:
        if entry.deleted_at is not None:
            return json_error(409, "This entry is deleted; restore it first.", {"id": id})
        stream_slug, key = (entry.stream.stream_id if entry.stream else None), entry.stream_key
        result = streams.unlink_entry(entry, data.block, actor=g.api_key_name)
    changes = {"source": ["stream", "manual"], "stream": [stream_slug, None]}
    if result["blocked"]:
        changes["stream_block"] = [None, key]
    if result["host"]:
        changes["host"] = [None, result["host"]]
    audit("entry", id, changes)
    return jsonify({"entry": entry_out(_load_entry(id)), **result})


@mgmt_bp.route("/entries/<int:id>/restore", methods=["POST"])
@require_api_key("write")
def restore_entry(id):
    entry = _load_entry(id)
    audit("entry", id)
    with routes_api._UPSERT_LOCK:
        if entry.deleted_at is None:
            return json_error(409, "This entry is not deleted.", {"id": id})
        clash = None if entry.stream_id is not None else ServiceEntry.active().filter_by(
            host=entry.host, container_name=entry.container_name).first()
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
        allowed, label = set(_CHECK_FIELD_TO_VALIDATOR) | {"ha_exclude"}, "a service check"
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
        if "ha_exclude" in sent:
            check.ha_exclude = data.ha_exclude
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
    stream_rows, stale_rows = _summary_streams(entries)
    counts["streams_stale"] = len(stale_rows)
    return jsonify({"counts": counts, "failing": failing, "streams": stream_rows,
                    "stale_streams": stale_rows})


def _summary_streams(entries):
    """The compact per-stream block of the health summary, and one `down` line per
    stale stream. Entries of a stale stream are not marked: their own checks decide
    their health (PRD 18.9)."""
    active, missing = {}, {}
    for e in entries:
        if e.stream_id is not None:
            active[e.stream_id] = active.get(e.stream_id, 0) + 1
            if e.inventory_missing:
                missing[e.stream_id] = missing.get(e.stream_id, 0) + 1
    rows, stale = [], []
    now = datetime.utcnow()
    for s in InventoryStream.query.order_by(InventoryStream.id).all():
        h = streams.stream_health(s, now)
        rows.append({"stream_id": s.stream_id, "display_name": s.display_name, "status": s.status,
                     "stale": h["stale"], "last_snapshot_at": health_history.iso_z(s.last_snapshot_at),
                     "last_item_count": s.last_item_count,
                     "effective_interval_seconds": h["effective_interval_seconds"],
                     "last_error": s.last_error,
                     "last_rejected_at": health_history.iso_z(s.last_rejected_at),
                     "last_rejection": s.last_rejection,
                     "entries_active": active.get(s.id, 0), "entries_missing": missing.get(s.id, 0)})
        if h["stale"]:
            stale.append({"stream_id": s.stream_id, "display_name": s.display_name, "state": "down",
                          "message": h["message"], "since": h["stale_since"]})
    return rows, stale


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


def _update_check_payload():
    enabled, hours = settings_store.get_update_check_settings()
    return {"enabled": enabled, "interval_hours": hours}


@mgmt_bp.route("/settings/update-check", methods=["GET"])
@require_api_key("read")
def get_update_check_settings():
    return jsonify(_update_check_payload())


@mgmt_bp.route("/settings/update-check", methods=["PUT"])
@require_api_key("write")
def put_update_check_settings():
    audit("update_check_settings")
    data = UpdateCheckSettingsPut.model_validate(_json_body())
    errors = []
    if data.enabled is None and data.interval_hours is None:
        errors.append({"field": "body", "message": "name at least one of enabled, interval_hours"})
    if data.interval_hours is not None and data.interval_hours < 1:
        errors.append({"field": "interval_hours", "message": "must be a whole number of hours, 1 or more"})
    if errors:
        return _fail(errors)
    before = _update_check_payload()
    settings_store.save_update_check_settings(data.enabled, data.interval_hours)
    db.session.commit()
    version_check.reset()
    after = _update_check_payload()
    audit("update_check_settings", None, _diff(before, after))
    return jsonify(after)


# --- backups and export (PRD 20) -----------------------------------------------------


def _backup_flat_values():
    """The effective backup values keyed like the audit trail (`snapshot.time`)."""
    return {key.replace("_", ".", 1): entry["value"] for key, entry in backups.effective_flat(current_app).items()}


def _backup_payload():
    eff = backups.effective_settings(current_app)

    def one(entry):
        return {"value": entry["value"], "origin": entry["origin"]}

    out = {"path": one(eff["path"])}
    for kind in backups.KINDS:
        out[kind] = {name: one(entry) for name, entry in eff[kind].items()}
    out["last_runs"] = {
        kind: {k: run.get(k) for k in ("at", "ok", "file", "size", "error", "trigger")}
        for kind, run in backups.last_runs().items() if kind in backups.KINDS and isinstance(run, dict)}
    out["next_runs"] = {
        kind: (when.isoformat(timespec="seconds") if when else None)
        for kind, when in jobs.next_run_times().items()}
    return out


@mgmt_bp.route("/settings/backup", methods=["GET"])
@require_api_key("read")
def get_backup_settings():
    return jsonify(_backup_payload())


@mgmt_bp.route("/settings/backup", methods=["PUT"])
@require_api_key("write")
def put_backup_settings():
    audit("backup_settings")
    data = BackupSettingsPut.model_validate(_json_body())
    values = {}
    if data.path is not None:
        values["path"] = data.path
    for kind, job in (("snapshot", data.snapshot), ("export", data.export)):
        if job is None:
            continue
        for name in ("enabled", "time", "keep_days", "format"):
            if getattr(job, name, None) is not None:
                values[f"{kind}_{name}"] = getattr(job, name)
    if not values:
        return _fail([{"field": "body",
                       "message": "name at least one of path, snapshot, export (each with at least one field)"}])
    current = backups.effective_flat(current_app)
    for key, raw in values.items():
        entry = current[key]
        if entry["env_name"] and str(raw).strip() != str(entry["value"]):
            return json_error(409, f"{key.replace('_', '.', 1)} is set by the environment "
                                   f"({entry['env_name']}) and cannot be changed here.")
    before = _backup_flat_values()
    errors, warnings = backups.save_settings(current_app, values)
    if errors:
        db.session.rollback()
        return _fail([{"field": key.replace("_", ".", 1), "message": msg}
                      for key, msg in errors.items()])
    db.session.commit()
    jobs.reschedule_backups(current_app)
    audit("backup_settings", None, _diff(before, _backup_flat_values()))
    return jsonify({**_backup_payload(), "warnings": warnings})


@mgmt_bp.route("/backups", methods=["GET"])
@require_api_key("read")
def list_backups():
    try:
        files = backups.list_files()
    except OSError as e:
        return json_error(409, f"Could not read the backup folder: {e.strerror or e}.")
    rows = files["snapshots"] + files["exports"]
    rows.sort(key=lambda r: (r["modified"], r["name"]), reverse=True)
    return jsonify({"items": [
        {"name": r["name"], "kind": r["kind"], "size": r["size"],
         "modified": r["modified"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "manual": r["manual"], "legacy": r["legacy"]}
        for r in rows]})


@mgmt_bp.route("/backups/run", methods=["POST"])
@require_api_key("write")
def run_backup():
    audit("backup_run")
    data = BackupRunRequest.model_validate(_json_body())
    audit("backup_run", data.kind)
    app = current_app._get_current_object()
    result = backups.run_snapshot(app, "manual") if data.kind == "snapshot" else backups.run_export(app, "manual")
    if result.get("busy"):
        return json_error(409, result["error"])
    audit("backup_run", data.kind, {"result": [None, "ok" if result["ok"] else "failed"],
                                    "file": [None, result.get("file")]})
    return jsonify({"kind": data.kind, **{k: result.get(k) for k in ("ok", "file", "size", "error", "at", "trigger")}})


@mgmt_bp.route("/export", methods=["GET"])
@require_api_key("read")
def get_export():
    fmt = (request.args.get("format") or "json").strip().lower()
    if fmt not in ("json", "yaml"):
        return _fail([{"field": "format", "message": "must be json or yaml"}])
    data = export_format.dump(export_format.build_export(), fmt)
    response = Response(data, mimetype="application/yaml" if fmt == "yaml" else "application/json")
    response.headers["Cache-Control"] = "no-store"
    return response


# --- import (PRD 20; design 7, 11) ---------------------------------------------------------


def _import_request(model):
    """The validated request body of the import routes. The size is checked first (413); the
    document may arrive as an object or as text (YAML, JSON or an old YAML backup)."""
    limit = importer.MAX_UPLOAD_BYTES + 64 * 1024
    if request.content_length is not None and request.content_length > limit:
        raise ApiError(413, f"The request body is larger than {limit} bytes.", {"limit": limit})
    return model.model_validate(_json_body())


def _import_parsed(data):
    """The `ParsedDoc` of a request, or a 400 response for a file that cannot be read."""
    if data.document is not None:
        raw, name = json.dumps(data.document).encode("utf-8"), "document.json"
    else:
        raw, name = data.document_text.encode("utf-8"), None
    try:
        return importer.parse(raw, name), None
    except importer.ImportParseError as exc:
        return None, json_error(400, str(exc))


def _import_selection(data):
    if data.selection is None:
        return None
    return {rid: row.model_dump() for rid, row in data.selection.items()}


def _import_plan_out(the_plan, selection=None):
    """The plan as JSON. `fingerprint` is the one for `selection`, or for the default selection
    (`default_selection`, the rows the UI pre-ticks) when none is given."""
    out = the_plan.to_dict()
    out.pop("digests", None)
    default = the_plan.default_selection()
    out["default_selection"] = default
    out["fingerprint"] = importer.fingerprint(the_plan, default if selection is None else selection)
    return out


@mgmt_bp.route("/import/plan", methods=["POST"])
@require_api_key("write")
def import_plan():
    data = _import_request(ImportPlanRequest)
    parsed, error = _import_parsed(data)
    if error is not None:
        return error
    the_plan = importer.plan(parsed, data.stream_map)
    return jsonify(_import_plan_out(the_plan, _import_selection(data)))


@mgmt_bp.route("/import/apply", methods=["POST"])
@require_api_key("write")
def import_apply():
    audit("import")
    data = _import_request(ImportApplyRequest)
    parsed, error = _import_parsed(data)
    if error is not None:
        return error
    selection = _import_selection(data)
    try:
        result = importer.apply(parsed, data.stream_map, selection, data.mode, data.fingerprint,
                                g.get("api_key_name") or "api")
    except importer.ImportStale as exc:
        response = jsonify({"error": str(exc), "details": None, "plan": _import_plan_out(exc.plan, selection)})
        response.status_code = 409
        return response
    except importer.ImportApplyError as exc:
        return json_error(400, str(exc))
    out = result.to_dict()
    audit("import", None, {key: [None, value] for key, value in sorted(out["counts"].items())})
    return jsonify(out)


# --- notification channels (PRD 17.2) --------------------------------------------


def _channel_snapshot(channel):
    """Audit view: the secret is only ever recorded as a changed flag."""
    return {"name": channel.name, "enabled": bool(channel.enabled), "config": dict(channel.config or {})}


def _load_channel(id):
    channel = db.session.get(NotificationChannel, id)
    if channel is None:
        abort(404, f"No notification channel with id {id}.")
    return channel


@mgmt_bp.route("/notifications/channels", methods=["GET"])
@require_api_key("read")
def list_notification_channels():
    limit, offset = _page_args()
    query = NotificationChannel.query.order_by(NotificationChannel.id.asc())
    total = query.count()
    items = [notification_channel_out(c) for c in query.limit(limit).offset(offset).all()]
    return _page(items, total, limit, offset)


@mgmt_bp.route("/notifications/channels", methods=["POST"])
@require_api_key("write")
def create_notification_channel():
    audit("notification_channel")
    data = NotificationChannelCreate.model_validate(_json_body())
    channel, errors = notify.create_channel(data.name, data.type, data.enabled, data.config, data.secret)
    if errors:
        status_conflict = any("already exists" in e["message"] for e in errors)
        if status_conflict:
            return json_error(409, errors[0]["message"], errors)
        return _fail(errors)
    audit("notification_channel", channel.id,
          {**_channel_snapshot(channel), "credential_set": [None, bool(channel.secret)]})
    response = jsonify(notification_channel_out(channel))
    response.status_code = 201
    return response


@mgmt_bp.route("/notifications/channels/<int:id>", methods=["GET"])
@require_api_key("read")
def get_notification_channel(id):
    return jsonify(notification_channel_out(_load_channel(id)))


@mgmt_bp.route("/notifications/channels/<int:id>", methods=["PATCH"])
@require_api_key("write")
def patch_notification_channel(id):
    audit("notification_channel", id)
    channel = _load_channel(id)
    data = NotificationChannelPatch.model_validate(_json_body())
    sent = data.model_fields_set
    if not sent:
        return _fail([{"field": "body", "message": "name at least one field to change"}])
    errors = [{"field": f, "message": "cannot be null"} for f in ("name", "enabled", "config")
              if f in sent and getattr(data, f) is None]
    if errors:
        return _fail(errors)
    if sent == {"cleanup"}:
        return _fail([{"field": "body", "message": "name at least one field to change"}])
    before = _channel_snapshot(channel)
    had_secret = bool(channel.secret)
    kwargs = {f: getattr(data, f) for f in ("name", "enabled", "config", "secret") if f in sent}
    # `cleanup` null/omitted: clear the old base on a base change, not on a plain disable.
    cleanup = data.cleanup
    kwargs["cleanup_disable"] = bool(cleanup)
    kwargs["cleanup_old_base"] = True if cleanup is None else cleanup
    try:
        _, errors = notify.update_channel(channel, **kwargs)
    except PurgeError as exc:
        return _purge_error(exc)
    if errors:
        if any("already exists" in e["message"] for e in errors):
            return json_error(409, errors[0]["message"], errors)
        return _fail(errors)
    changes = _diff(before, _channel_snapshot(channel))
    if "secret" in sent:
        changes["credential_set"] = [had_secret, bool(channel.secret)]
    audit("notification_channel", id, changes)
    return jsonify(notification_channel_out(channel))


@mgmt_bp.route("/notifications/channels/<int:id>", methods=["DELETE"])
@require_api_key("write")
def delete_notification_channel(id):
    audit("notification_channel", id)
    channel = _load_channel(id)
    raw = request.args.get("cleanup")
    if raw is None or raw.strip() == "":
        cleanup = True
    elif raw.strip().lower() in ("1", "true", "yes", "on"):
        cleanup = True
    elif raw.strip().lower() in ("0", "false", "no", "off"):
        cleanup = False
    else:
        abort(400, "'cleanup' must be true or false.")
    name = channel.name
    try:
        cleared = notify.delete_channel(channel, cleanup=cleanup)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("notification_channel", id, {"name": [name, None]})
    return jsonify({"id": id, "deleted": True, "cleanup": cleared})


@mgmt_bp.route("/notifications/channels/<int:id>/test", methods=["POST"])
@require_api_key("write")
def test_notification_channel(id):
    """Connect with the stored config and publish a non-retained message to
    `<base_topic>/test`. A failed test is a 200 with `ok: false` and the reason."""
    audit("notification_channel", id)
    channel = _load_channel(id)
    ok, message = notify.test_channel(channel.type, dict(channel.config or {}), channel.secret)
    audit("notification_channel", id, {"test": [None, "ok" if ok else "failed"]})
    return jsonify({"ok": ok, "message": message})


def _purge_error(exc):
    return json_error(exc.status, exc.message)


@mgmt_bp.route("/notifications/channels/<int:id>/purge", methods=["POST"])
@require_api_key("write")
def purge_notification_channel(id):
    """Clean slate for one channel's broker (PRD 17.5). The body is optional."""
    audit("notification_channel", id)
    channel = _load_channel(id)
    raw = request.get_json(silent=True) if request.data else {}
    if not isinstance(raw, dict):
        abort(400, "Send a JSON object as the request body.")
    data = NotificationPurgeRequest.model_validate(raw)
    try:
        result = notify.purge_channel(channel.id, data.republish)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("notification_channel", id, {"purge": [None, {"topics_cleared": result["topics_cleared"],
                                                         "republish": data.republish}]})
    return jsonify(result)


@mgmt_bp.route("/notifications/channels/<int:id>/previous-bases", methods=["GET"])
@require_api_key("read")
def list_notification_previous_bases(id):
    """The base topics this channel used before (the orphan scan looks under them)."""
    channel = _load_channel(id)
    return jsonify({"channel_id": channel.id, "limit": MAX_PREVIOUS_BASES,
                    "items": notify.previous_bases(channel.id)})


@mgmt_bp.route("/notifications/channels/<int:id>/orphans/scan", methods=["POST"])
@require_api_key("write")
def scan_notification_orphans(id):
    """Preview the retained STD topics nothing desires any more (PRD 17.5)."""
    audit("notification_channel", id)
    channel = _load_channel(id)
    data = _optional_body(NotificationOrphanScanRequest)
    try:
        result = notify.scan_orphans(channel.id, data.extra_base)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("notification_channel", id, {"orphan_scan": [None, {"count": result["count"]}]})
    return jsonify(result)


@mgmt_bp.route("/notifications/channels/<int:id>/orphans/clear", methods=["POST"])
@require_api_key("write")
def clear_notification_orphans(id):
    """Clear the orphans a scan listed (or, with no list, every orphan a fresh scan finds)."""
    audit("notification_channel", id)
    channel = _load_channel(id)
    data = _optional_body(NotificationOrphanClearRequest)
    try:
        result = notify.clear_orphans(channel.id, data.topics, data.extra_base)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("notification_channel", id, {"orphans_cleared": [None, result["topics_cleared"]]})
    return jsonify(result)


@mgmt_bp.route("/entries/<int:id>/notifications/purge", methods=["POST"])
@require_api_key("write")
def purge_entry_notifications(id):
    """Purge one entry's topics and Home Assistant device, then republish it."""
    entry = _load_entry(id)
    audit("entry", id)
    try:
        result = notify.purge_entry(entry.id)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("entry", id, {"notification_purge": [None, {"topics_cleared": result["topics_cleared"]}]})
    return jsonify(result)


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
    return jsonify({"version": version, **_build_facts(), "settings": values, "sources": sources})


# --- inventory streams (PRD 18.5 ingest, 18.7 lifecycle) -------------------------


def _bad_stream_id():
    return _fail([{"field": "stream_id", "message": "stream_id must match ^[a-z0-9][a-z0-9_-]{0,62}$"}])


def _snapshot_body():
    """The parsed JSON object. The size is checked before anything is parsed (413)."""
    limit = streams.MAX_BODY_BYTES
    declared = request.content_length
    if declared is not None and declared > limit:
        raise ApiError(413, f"The request body is larger than {limit} bytes.", {"limit": limit})
    data = request.get_data() if declared is not None else request.stream.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, f"The request body is larger than {limit} bytes.", {"limit": limit})
    try:
        body = json.loads(data)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        abort(400, "Send a JSON object as the request body.")
    return body


@mgmt_bp.route("/streams/<stream_id>/snapshot", methods=["PUT"])
@require_api_key("ingest")
def put_stream_snapshot(stream_id):
    """A sidecar's full snapshot. Not audited: it arrives every few minutes."""
    if not streams.STREAM_ID_RE.fullmatch(stream_id):
        return _bad_stream_id()
    existing = streams.find_stream(stream_id)
    if existing is not None:
        streams.check_binding(existing, g.api_key)
        if existing.status == "ignored":
            return jsonify({"stream_id": stream_id, "stream_status": "ignored", "applied": False}), 202
    pk = existing.id if existing is not None else None
    try:
        payload = StreamSnapshotPut.model_validate(_snapshot_body())
        items, errors = streams.normalize_items(payload.key_type, payload.items)
        if errors:
            if pk is not None:
                first = errors[0]
                streams.record_rejection(pk, 400, f"{first['field']}: {first['message']}")
            return _fail(errors)
        status, body = streams.receive_snapshot(stream_id, payload, items, g.api_key)
    except ValidationError as exc:
        if pk is not None:
            first = (exc.errors() or [{}])[0]
            loc = ".".join(str(p) for p in first.get("loc", ())) or "body"
            streams.record_rejection(pk, 400, f"{loc}: {first.get('msg')}")
        raise
    except (ApiError, streams.StreamError) as exc:
        # A rejection of a stream this key may use (the binding passed above); the
        # stream row keeps it for the operator. A 403 from a re-check is not recorded.
        if pk is not None and exc.status in (400, 409, 413):
            streams.record_rejection(pk, exc.status, exc.message)
        raise
    return jsonify(body), status


@mgmt_bp.route("/streams/<stream_id>/status", methods=["GET"])
@require_api_key("ingest")
def get_stream_status(stream_id):
    """What STD knows about the stream, for a sidecar to log at startup."""
    stream = streams.find_stream(stream_id) if streams.STREAM_ID_RE.fullmatch(stream_id) else None
    if stream is None:
        abort(404, f"No stream '{stream_id}' yet.")
    streams.check_binding(stream, g.api_key)
    return jsonify(streams.status_body(stream))


def _load_stream(stream_id):
    stream = streams.find_stream(stream_id) if streams.STREAM_ID_RE.fullmatch(stream_id) else None
    if stream is None:
        abort(404, f"No stream '{stream_id}'.")
    return stream


def _optional_body(model):
    raw = request.get_json(silent=True) if request.data else {}
    if not isinstance(raw, dict):
        abort(400, "Send a JSON object as the request body.")
    return model.model_validate(raw)


@mgmt_bp.route("/streams", methods=["GET"])
@require_api_key("read")
def list_streams():
    limit, offset = _page_args()
    query = InventoryStream.query.order_by(InventoryStream.id)
    rows = query.limit(limit).offset(offset).all()
    body = {"items": [stream_out(s) for s in rows], "total": query.order_by(None).count(),
            "limit": limit, "offset": offset,
            "pending": InventoryStream.query.filter_by(status=streams.STREAM_PENDING).count(),
            "stale": len(streams.stale_streams())}
    return jsonify(body)


@mgmt_bp.route("/streams/<stream_id>", methods=["GET"])
@require_api_key("read")
def get_stream(stream_id):
    return jsonify(stream_out(_load_stream(stream_id)))


@mgmt_bp.route("/streams/<stream_id>", methods=["PATCH"])
@require_api_key("write")
def patch_stream(stream_id):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    data = StreamPatch.model_validate(_json_body())
    sent = data.model_fields_set
    if not sent:
        return _fail([{"field": "body", "message": "name at least one field to change"}])
    default_checks = data.default_checks.model_dump() if data.default_checks is not None else None
    changes = streams.update(stream, data.display_name, data.network_include,
                             data.network_exclude, sent, default_checks=default_checks,
                             expected_interval_seconds=data.expected_interval_seconds,
                             missing_expiry_days=data.missing_expiry_days)
    audit("stream", stream_id, changes)
    return jsonify(stream_out(stream))


@mgmt_bp.route("/streams/<stream_id>/default-checks/apply", methods=["POST"])
@require_api_key("write")
def apply_stream_default_checks(stream_id):
    """Add the stream's missing default checks to every active entry of the stream."""
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    result = streams.apply_default_checks(stream)
    audit("stream", stream_id, {"default_checks_applied": [None, result["checks_added"]],
                                "entries_changed": [None, result["entries_changed"]]})
    return jsonify({"stream": stream_out(stream), **result})


@mgmt_bp.route("/streams/<stream_id>/notifications/purge", methods=["POST"])
@require_api_key("write")
def purge_stream_notifications(stream_id):
    """Purge every entry of a stream (and its status topic and hub device) from MQTT and
    Home Assistant, then republish what is still eligible."""
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    try:
        result = notify.purge_stream(stream.id)
    except PurgeError as exc:
        return _purge_error(exc)
    audit("stream", stream_id, {"notification_purge": [None, {"topics_cleared": result["topics_cleared"]}]})
    return jsonify(result)


@mgmt_bp.route("/streams/<stream_id>/preview", methods=["GET"])
@require_api_key("read")
def preview_stream(stream_id):
    return jsonify(streams.preview(_load_stream(stream_id)))


@mgmt_bp.route("/streams/<stream_id>/enable", methods=["POST"])
@require_api_key("write")
def enable_stream(stream_id):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    before = stream.status
    result = streams.enable(stream)
    audit("stream", stream_id, {"status": [before, stream.status], "counts": [None, result["counts"]]})
    return jsonify({"stream": stream_out(stream), **result})


@mgmt_bp.route("/streams/<stream_id>/disable", methods=["POST"])
@require_api_key("write")
def disable_stream(stream_id):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    data = _optional_body(StreamDisableRequest)
    before = stream.status
    result = streams.disable(stream, data.cleanup, data.clear_blocks)
    audit("stream", stream_id, {"status": [before, stream.status], "cleanup": [None, data.cleanup],
                                "clear_blocks": [False, data.clear_blocks and data.cleanup == "purge"],
                                "result": [None, result]})
    return jsonify({"stream": stream_out(stream), "cleanup": data.cleanup, "result": result})


@mgmt_bp.route("/streams/<stream_id>/ignore", methods=["POST"])
@require_api_key("write")
def ignore_stream(stream_id):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    before = stream.status
    streams.ignore(stream)
    audit("stream", stream_id, {"status": [before, stream.status]})
    return jsonify(stream_out(stream))


@mgmt_bp.route("/streams/<stream_id>", methods=["DELETE"])
@require_api_key("write")
def remove_stream(stream_id):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    cleanup = (request.args.get("cleanup") or "keep").strip().lower()
    name, before = stream.display_name, stream.status
    result = streams.delete(stream, cleanup)
    audit("stream", stream_id, {"name": [name, None], "status": [before, None],
                                "cleanup": [None, cleanup], "result": [None, result]})
    return jsonify({"stream_id": stream_id, "deleted": True, "cleanup": cleanup, "result": result})


@mgmt_bp.route("/streams/<stream_id>/blocks", methods=["GET"])
@require_api_key("read")
def list_stream_blocks(stream_id):
    stream = _load_stream(stream_id)
    limit, offset = _page_args()
    query = InventoryBlock.query.filter_by(stream_id=stream.id).order_by(InventoryBlock.id)
    return _page([block_out(b) for b in query.limit(limit).offset(offset).all()],
                 query.order_by(None).count(), limit, offset)


@mgmt_bp.route("/streams/<stream_id>/blocks/<int:block_id>", methods=["DELETE"])
@require_api_key("write")
def unblock_stream_key(stream_id, block_id):
    """Remove a block: the next snapshot restores the entry or creates a new one."""
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    key = streams.unblock(stream, block_id)
    audit("stream", stream_id, {"unblocked": [None, key]})
    return jsonify({"stream_id": stream_id, "key": key, "unblocked": True})


@mgmt_bp.route("/streams/<stream_id>/offers", methods=["GET"])
@require_api_key("read")
def list_stream_offers(stream_id):
    stream = _load_stream(stream_id)
    limit, offset = _page_args()
    query = StreamLinkOffer.query.filter_by(stream_id=stream.id).order_by(StreamLinkOffer.id)
    return _page([offer_out(o) for o in query.limit(limit).offset(offset).all()],
                 query.order_by(None).count(), limit, offset)


def _answer_offer(stream_id, offer_id, answer):
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    offer = streams.get_offer(stream, offer_id)
    key = offer.key
    if answer == "accepted":
        entry = streams.accept_offer(stream, offer)
    else:
        entry = streams.decline_offer(stream, offer)
    audit("stream", stream_id, {"link_offer": [key, answer], "entry_id": [None, entry.id]})
    return jsonify({"stream_id": stream_id, "key": key, "answer": answer,
                    "entry": entry_out(_load_entry(entry.id))})


@mgmt_bp.route("/streams/<stream_id>/offers/<int:offer_id>/accept", methods=["POST"])
@require_api_key("write")
def accept_stream_offer(stream_id, offer_id):
    """The manual entry joins the stream, keeping its id, history, checks and settings."""
    return _answer_offer(stream_id, offer_id, "accepted")


@mgmt_bp.route("/streams/<stream_id>/offers/<int:offer_id>/decline", methods=["POST"])
@require_api_key("write")
def decline_stream_offer(stream_id, offer_id):
    """A new stream entry is created from the item; the manual entry is left alone."""
    return _answer_offer(stream_id, offer_id, "declined")


@mgmt_bp.route("/streams/<stream_id>/unmatched", methods=["GET"])
@require_api_key("read")
def list_stream_unmatched(stream_id):
    """Items of the latest snapshot with no entry, not blocked: link targets."""
    stream = _load_stream(stream_id)
    limit, offset = _page_args()
    items = streams.unmatched_items(stream)
    return _page(items[offset:offset + limit], len(items), limit, offset)


@mgmt_bp.route("/streams/<stream_id>/link", methods=["POST"])
@require_api_key("write")
def link_stream_item(stream_id):
    """Link an active manual entry to an unmatched item of the latest snapshot (its host is cleared)."""
    audit("stream", stream_id)
    stream = _load_stream(stream_id)
    data = StreamLinkRequest.model_validate(_json_body())
    entry = _load_entry(data.entry_id)
    streams.link_entry(stream, entry, data.key)
    audit("stream", stream_id, {"link": [None, data.key], "entry_id": [None, entry.id]})
    return jsonify({"stream_id": stream_id, "key": data.key, "answer": "linked",
                    "entry": entry_out(_load_entry(entry.id))})
