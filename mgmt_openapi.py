"""Route registry and OpenAPI 3.1 generator for the management API (v0.8.0, PRD 14.5).

Every management endpoint is declared ONCE in `OPERATIONS`: method, path,
scope, summary, request model, response model and query parameters. The
document served at `GET /api/v1/openapi.json` is generated from that table
plus pydantic's JSON schema for the models in `mgmt_schemas.py`; nothing is
hand-written. `tests/test_mgmt_openapi.py` compares the table with
`app.url_map` (every rule of the management blueprint) and with each view's
`require_api_key` scope, so a route added without a declaration, or declared
with the wrong scope, fails the suite.

Paths are relative to the server URL `/api/v1`.
"""

import re
from dataclasses import dataclass
from typing import Any, get_args, get_origin

from pydantic import TypeAdapter

import mgmt_schemas as S
from view_helpers import VALID_STATUS_FILTERS

API_PREFIX = "/api/v1"
SCOPE_NOTE = {
    None: "No authentication needed.",
    "read": "Needs an API key with the `read` or `write` scope.",
    "write": "Needs an API key with the `write` scope. The request is recorded in the audit log.",
}


@dataclass(frozen=True)
class Param:
    name: str
    schema: dict
    description: str


@dataclass(frozen=True)
class Op:
    method: str
    path: str                      # OpenAPI style, relative to /api/v1
    scope: str | None              # None (public), "read" or "write"
    summary: str
    response: Any                  # a TypedDict, a Page[...] or a union of them
    request: Any = None            # pydantic model for the JSON body
    params: tuple = ()             # query parameters
    status: int = 200
    errors: tuple = ()             # extra error statuses beyond 401/403 (+400 when input is read)
    description: str = ""


_BOOL = {"type": "boolean", "default": False}
_LIMIT = Param("limit", {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
               "Page size (values above 1000 are clamped to 1000).")
_OFFSET = Param("offset", {"type": "integer", "minimum": 0, "default": 0}, "Rows to skip.")
_PAGE = (_LIMIT, _OFFSET)

_PATCH_NOTE = (
    "Every field is optional. A field that is **absent** is left alone; a field sent as "
    "**null** clears the value where that makes sense (so each field is optional and nullable). "
    "A request that names no field is rejected with 400."
)

OPERATIONS: tuple = (
    Op("GET", "/openapi.json", None, "This OpenAPI document", dict,
       description="The machine-readable description of the management API (OpenAPI 3.1). "
                   "It describes shapes only, never data. `/api/v1/register` is not part of it."),
    Op("GET", "/whoami", "read", "Name, prefix and scope of the calling key", S.WhoamiOut,
       description="Handy to check that a key works and what it may do."),

    Op("GET", "/entries", "read", "List entries", S.Page[S.EntryOut], params=_PAGE + (
        Param("status", {"type": "string", "enum": list(VALID_STATUS_FILTERS), "default": "all"},
              "Filter by derived health state."),
        Param("source", {"type": "string", "enum": ["all", "notifier", "manual"], "default": "all"},
              "Where the entry came from."),
        Param("host", {"type": "string"}, "Exact host name."),
        Param("group", {"type": "string"}, "Exact group name."),
        Param("q", {"type": "string"}, "Case-insensitive search of name, host, stack and description."),
        Param("include_deleted", _BOOL, "Also return soft-deleted entries."),
        Param("deleted_only", _BOOL, "Return only soft-deleted entries."),
    ), errors=(), description="Ordered by id. Entries carry their health summary and checks."),
    Op("POST", "/entries", "write", "Add a manual entry", S.EntryDetailOut, request=S.EntryCreate,
       status=201, errors=(409,),
       description="Creates a manual (non-Docker) entry, optionally with URL-check settings and "
                   "service checks (HTTP, TCP or ping). A missing group is created. "
                   "An entry with no `group` is left ungrouped."),
    Op("GET", "/entries/{id}", "read", "Get one entry in full", S.EntryDetailOut, errors=(404,),
       description="Adds notifier-reported data (networks, ports, exposures) and the widget."),
    Op("PATCH", "/entries/{id}", "write", "Edit an entry", S.EntryDetailOut, request=S.EntryPatch,
       errors=(404, 409), description=_PATCH_NOTE + " Notifier-owned fields are rejected by name; "
       "`name` and `host` can be changed on manual entries only."),
    Op("DELETE", "/entries/{id}", "write", "Delete an entry (soft) or remove it for good",
       S.EntryOut | S.PermanentDeleteOut,
       params=(Param("permanent", _BOOL, "Permanently remove an entry that is already deleted."),),
       errors=(404, 409),
       description="By default the entry is soft-deleted and can be restored. "
                   "`?permanent=true` removes an already deleted entry for good."),
    Op("POST", "/entries/{id}/restore", "write", "Restore a deleted entry", S.EntryOut,
       errors=(404, 409)),

    Op("GET", "/entries/{id}/checks", "read", "List an entry's checks", S.Page[S.CheckOut],
       params=_PAGE, errors=(404,)),
    Op("POST", "/entries/{id}/checks", "write", "Add a service check", S.CheckOut,
       request=S.ServiceCheckCreate, status=201, errors=(404, 409),
       description="HTTP checks can use `mode: body` to look at the response body."),
    Op("PATCH", "/checks/{id}", "write", "Edit or enable/disable a check", S.CheckOut,
       request=S.CheckPatch, errors=(404, 409),
       description=_PATCH_NOTE + " Which fields are allowed depends on the check: URL checks take "
       "enabled, mode, interval, timeout and verify; container checks take enabled and interval; "
       "service checks take everything."),
    Op("DELETE", "/checks/{id}", "write", "Delete a service check", S.CheckDeleteOut,
       errors=(404, 409), description="Only service checks can be deleted; disable the others."),
    Op("POST", "/entries/{id}/checks/run", "write", "Check now", S.RunRequestedOut,
       errors=(404, 409), description="Queues every check that counts for an immediate run."),
    Op("GET", "/entries/{id}/health", "read", "Health history of an entry", S.EntryHealthDetailOut,
       params=(Param("range", {"type": "string", "enum": ["24h", "7d"], "default": "24h"},
                     "Bucket range."),), errors=(404,)),
    Op("GET", "/health/summary", "read", "Counts and the failing entries", S.HealthSummaryOut,
       description="The quickest way to ask what is broken."),

    Op("GET", "/groups", "read", "List groups", S.Page[S.GroupOut], params=_PAGE),
    Op("POST", "/groups", "write", "Create a group", S.GroupOut, request=S.GroupCreate,
       status=201, errors=(409,)),
    Op("PATCH", "/groups/{id}", "write", "Rename or edit a group", S.GroupOut, request=S.GroupPatch,
       errors=(404, 409), description=_PATCH_NOTE),
    Op("DELETE", "/groups/{id}", "write", "Delete a group", S.GroupDeleteOut,
       params=(Param("force", _BOOL, "Ungroup the group's entries instead of refusing."),),
       errors=(404, 409), description="Refused with 409 while active entries use the group."),

    Op("GET", "/widgets/types", "read", "Widget types and their fields", S.Page[S.WidgetTypeOut]),
    Op("GET", "/widgets", "read", "List widget instances", S.Page[S.WidgetInstanceOut], params=_PAGE),
    Op("PUT", "/entries/{id}/widget", "write", "Attach or reconfigure an entry's widget",
       S.WidgetOut, request=S.WidgetPut, errors=(404, 409),
       description="Replaces type, URL and fields. 201 when the widget is new, 200 when updated. "
                   "`widget_api_key` omitted keeps the stored key, null clears it. "
                   "The key itself is never returned."),
    Op("DELETE", "/entries/{id}/widget", "write", "Detach an entry's widget", S.WidgetDetachOut,
       params=(Param("delete", _BOOL, "Also remove the widget and its stored values."),),
       errors=(404, 409), description="The detached widget stays available in Settings → Widgets."),
    Op("DELETE", "/widgets/{id}", "write", "Delete a detached widget", S.WidgetDeleteOut,
       errors=(404, 409)),

    Op("GET", "/settings/exposure", "read", "Exposure direction settings", S.ExposureSettingsOut),
    Op("PUT", "/settings/exposure", "write", "Replace exposure direction settings",
       S.ExposureSettingsSavedOut, request=S.ExposureSettingsPut,
       description="Replaces both mappings, then recomputes every service's synthesized URLs. "
                   "UI edits and explicit labels are never overwritten."),
    Op("GET", "/config", "read", "Effective configuration (read-only)", S.ConfigOut,
       description="Secrets are masked as `***`. `sources` says where each value came from."),
)

_ERROR_TEXT = {
    400: "Invalid request: bad body, query value or validation failure (`details` lists problems).",
    401: "Missing, invalid or revoked API key.",
    403: "The key's scope is too low for this endpoint.",
    404: "No such object.",
    409: "The request conflicts with the current state.",
}


# --- generation ----------------------------------------------------------------


def flask_rule_to_path(rule: str) -> str:
    """`/api/v1/entries/<int:id>` -> `/entries/{id}`."""
    path = rule[len(API_PREFIX):] if rule.startswith(API_PREFIX) else rule
    return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", path)


def operation_id(op: Op) -> str:
    words = re.sub(r"[{}]", "", op.path).strip("/").replace("/", "_").replace("-", "_")
    return f"{op.method.lower()}_{words}"


class _Components:
    """Collects JSON schemas into `components.schemas` with `#/components/schemas/...` refs."""

    def __init__(self):
        self.schemas: dict = {}

    def schema_for(self, tp) -> dict:
        if tp is dict:
            return {"type": "object", "description": "An OpenAPI 3.1 document."}
        raw = TypeAdapter(tp).json_schema(ref_template="#/components/schemas/{model}")
        self.schemas.update(raw.pop("$defs", {}))
        if "$ref" in raw and len(raw) == 1:
            return raw
        if "anyOf" in raw and "title" not in raw:
            return raw                       # a union: inline, its members are already components
        args = get_args(tp)
        if args and hasattr(args[0], "__name__"):     # Page[EntryOut] -> PageOfEntryOut
            title = f"{get_origin(tp).__name__}Of{args[0].__name__}"
        else:
            title = re.sub(r"[^A-Za-z0-9._-]", "", raw.get("title") or getattr(tp, "__name__", "Schema"))
        self.schemas[title] = raw
        return {"$ref": f"#/components/schemas/{title}"}


def build_spec(version: str = "") -> dict:
    comp = _Components()
    error_ref = comp.schema_for(S.ErrorOut)
    paths: dict = {}
    for op in OPERATIONS:
        item = paths.setdefault(op.path, {})
        parameters = [
            {"name": n, "in": "path", "required": True, "schema": {"type": "integer"}}
            for n in re.findall(r"{(\w+)}", op.path)
        ]
        parameters += [
            {"name": p.name, "in": "query", "required": False, "description": p.description,
             "schema": p.schema}
            for p in op.params
        ]
        scope_note = f"**Scope:** {SCOPE_NOTE[op.scope]}"
        out: dict = {
            "operationId": operation_id(op),
            "summary": op.summary,
            "description": "\n\n".join(t for t in (op.description, scope_note) if t),
            "tags": [op.path.strip("/").split("/")[0].replace("openapi.json", "meta")],
            "x-required-scope": op.scope,
        }
        if parameters:
            out["parameters"] = parameters
        if op.request is not None:
            out["requestBody"] = {
                "required": True,
                "content": {"application/json": {"schema": comp.schema_for(op.request)}},
            }
        responses: dict = {
            str(op.status): {
                "description": "Success",
                "content": {"application/json": {"schema": comp.schema_for(op.response)}},
            }
        }
        statuses = set(op.errors)
        if op.request is not None or op.params:
            statuses.add(400)
        if op.scope:
            statuses |= {401, 403}
        for status in sorted(statuses):
            responses[str(status)] = {
                "description": _ERROR_TEXT[status],
                "content": {"application/json": {"schema": error_ref}},
            }
        out["responses"] = responses
        if op.scope:
            out["security"] = [{"bearerAuth": []}]
        item[op.method.lower()] = out

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Service Tracker Dashboard management API",
            "version": version or "unknown",
            "description": (
                "Everything an operator can do in the UI, over JSON. Authenticate with an admin API key "
                "(Settings -> API) sent as `Authorization: Bearer <key>`. A `read` key can read; a "
                "`write` key can read and change. Errors are `{\"error\": str, \"details\": ...}`; "
                "validation `details` is a list of `{loc, msg, type}`. Lists are "
                "`{items, total, limit, offset}`. The notifier's `api_token` only works on "
                "`/api/v1/register`, which is not described here."
            ),
        },
        "servers": [{"url": API_PREFIX}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": "Admin API key (`std_<prefix>_<secret>`), `read` or `write` scope.",
                }
            },
            "schemas": dict(sorted(comp.schemas.items())),
        },
    }
