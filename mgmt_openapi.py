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
from api_version import API_REVISION
from models import VALID_SOURCES
from view_helpers import VALID_STATUS_FILTERS

API_PREFIX = "/api/v1"
SCOPE_NOTE = {
    None: "No authentication needed.",
    "read": "Needs an API key with the `read` or `write` scope.",
    "write": "Needs an API key with the `write` scope. The request is recorded in the audit log.",
    "ingest": "Needs an API key with the `ingest` or `write` scope. An `ingest` key opens only the "
              "stream ingest routes; a stream is bound to the key that created it. Not recorded in "
              "the audit log.",
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
    scope: str | None              # None (public), "read", "write" or "ingest"
    summary: str
    response: Any                  # a TypedDict, a Page[...] or a union of them
    request: Any = None            # pydantic model for the JSON body
    params: tuple = ()             # query parameters
    status: int = 200
    errors: tuple = ()             # extra error statuses beyond 401/403 (+400 when input is read)
    description: str = ""
    also: tuple = ()               # more success statuses: (status, response model, description)


_BOOL = {"type": "boolean", "default": False}
_LIMIT = Param("limit", {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
               "Page size (values above 1000 are clamped to 1000).")
_OFFSET = Param("offset", {"type": "integer", "minimum": 0, "default": 0}, "Rows to skip.")
_PAGE = (_LIMIT, _OFFSET)
_CLEANUP = ("`keep` (entries stay and are no longer updated), `soft_delete` (every entry is soft-deleted "
            "and can be restored) or `purge` (hard delete, plus the link offers; the stored snapshot is kept)")

_PATCH_NOTE = (
    "Every field is optional. A field that is **absent** is left alone; a field sent as "
    "**null** clears the value where that makes sense (so each field is optional and nullable). "
    "A request that names no field is rejected with 400."
)

OPERATIONS: tuple = (
    Op("GET", "/openapi.json", None, "This OpenAPI document", dict,
       description="The machine-readable description of the management API (OpenAPI 3.1). "
                   "It describes shapes only, never data. `/api/v1/register` is not part of it."),
    Op("GET", "/meta", None, "STD version, API revision and supported features", S.MetaOut,
       description="Producers call it at startup to log what this STD speaks. No key needed and no "
                   "database access. Every `/api/...` response, errors included, also carries "
                   "`X-STD-API-Revision` and `X-STD-Version` headers."),
    Op("GET", "/whoami", "read", "Name, prefix and scope of the calling key, and the STD version", S.WhoamiOut,
       description="Handy to check that a key works and what it may do. `version` is the STD "
                   "version; the MCP server compares it with its own. `commit`, `channel` and `build_time` "
                   "identify the build, and `update` is the cached GitHub update check."),

    Op("GET", "/entries", "read", "List entries", S.Page[S.EntryOut], params=_PAGE + (
        Param("status", {"type": "string", "enum": list(VALID_STATUS_FILTERS), "default": "all"},
              "Filter by derived health state."),
        Param("source", {"type": "string", "enum": ["all", *VALID_SOURCES], "default": "all"},
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
                   "service checks (HTTP, TCP, ping or DNS). A missing group is created. "
                   "An entry with no `group` is left ungrouped."),
    Op("GET", "/entries/{id}", "read", "Get one entry in full", S.EntryDetailOut, errors=(404,),
       description="Adds notifier-reported data (networks, ports, exposures) and the widget."),
    Op("PATCH", "/entries/{id}", "write", "Edit an entry", S.EntryDetailOut, request=S.EntryPatch,
       errors=(404, 409), description=_PATCH_NOTE + " Notifier-owned fields are rejected by name; "
       "`name` and `host` can be changed on manual entries only. `ha_publish` true publishes the "
       "entry's device to Home Assistant discovery (default false)."),
    Op("DELETE", "/entries/{id}", "write", "Delete an entry (soft) or remove it for good",
       S.EntryOut | S.PermanentDeleteOut,
       params=(Param("permanent", _BOOL, "Permanently remove an entry that is already deleted."),
               Param("block", _BOOL, "Stream entries only: also put the entry's stream key on the "
                                     "stream's block list so a later snapshot cannot bring it back.")),
       errors=(404, 409),
       description="By default the entry is soft-deleted and can be restored. "
                   "`?permanent=true` removes an already deleted entry for good. "
                   "`?block=true` (a stream entry, first delete only) also blocks its key."),
    Op("POST", "/entries/{id}/restore", "write", "Restore a deleted entry", S.EntryOut,
       errors=(404, 409)),

    Op("GET", "/entries/{id}/checks", "read", "List an entry's checks", S.Page[S.CheckOut],
       params=_PAGE, errors=(404,)),
    Op("POST", "/entries/{id}/checks", "write", "Add a service check", S.CheckOut,
       request=S.ServiceCheckCreate, status=201, errors=(404, 409),
       description="HTTP checks can use `mode: body` to look at the response body, and "
                   "`cert_min_days` (1-365) to fail when an https target's certificate has fewer "
                   "days left (a 400 on tcp, ping and dns checks). DNS checks "
                   "(`check_type: dns`) take the DNS server as `target` and `dns_name`, "
                   "`dns_record_type`, `dns_expected_rcode` and `dns_expected_answer`."),
    Op("PATCH", "/checks/{id}", "write", "Edit or enable/disable a check", S.CheckOut,
       request=S.CheckPatch, errors=(404, 409),
       description=_PATCH_NOTE + " Which fields are allowed depends on the check: URL checks take "
       "enabled, mode, interval, timeout, verify and cert_min_days (null clears it); container checks take enabled and interval; "
       "service checks take everything (the dns_* fields only make sense on a dns check; "
       "cert_min_days only on an http check). `ha_exclude` (true removes the check's Home "
       "Assistant entity) is allowed on every kind of check."),
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
    Op("GET", "/settings/update-check", "read", "Update check settings", S.UpdateCheckSettingsOut,
       description="Whether STD asks GitHub for the latest release, and how often (hours)."),
    Op("PUT", "/settings/update-check", "write", "Change the update check settings",
       S.UpdateCheckSettingsOut, request=S.UpdateCheckSettingsPut,
       description="`enabled` (default on) and `interval_hours` (default 6, minimum 1). Omitted "
                   "fields keep their value. When disabled STD makes no request to GitHub."),
    Op("GET", "/notifications/channels", "read", "List notification channels",
       S.Page[S.NotificationChannelOut], params=_PAGE,
       description="Each channel carries its live connection `status`. The secret (the MQTT "
                   "password) is never returned, only `secret_set`."),
    Op("POST", "/notifications/channels", "write", "Add a notification channel",
       S.NotificationChannelOut, request=S.NotificationChannelCreate, status=201, errors=(409,),
       description="`type` is `mqtt`. `config` takes host (required), port (default 1883, or 8883 "
                   "with tls), tls, tls_insecure, username, client_id, base_topic (default `std`), "
                   "qos (0 or 1, default 1), keepalive (default 60) and the Home Assistant settings "
                   "ha_discovery (default false), ha_prefix (default `homeassistant`) and "
                   "ha_device_prefix (default `STD`); unknown keys are a 400. "
                   "`secret` is the MQTT password. A channel is created disabled unless "
                   "`enabled` is true."),
    Op("GET", "/notifications/channels/{id}", "read", "Get a notification channel",
       S.NotificationChannelOut, errors=(404,)),
    Op("PATCH", "/notifications/channels/{id}", "write", "Edit a notification channel",
       S.NotificationChannelOut, request=S.NotificationChannelPatch, errors=(404, 409, 504),
       description="`config` keys are merged over the stored config. `secret` omitted keeps the "
                   "stored password, null clears it. The publisher reconnects with the new settings "
                   "at once. A request that names no field is rejected with 400. `cleanup` clears "
                   "the broker first: when the request disables the channel (default false: its "
                   "retained topics and discovery configs are removed, `<base_topic>/status` ends "
                   "as `offline`), and when it changes `base_topic` (or `ha_prefix` / "
                   "`ha_device_prefix` while discovery is on; default true: the old base's retained "
                   "topics and discovery configs are removed, and the old base and prefix are "
                   "remembered, see `previous-bases`). 409 when the cleanup is wanted but the "
                   "broker cannot be reached (nothing is changed; send `cleanup: false`)."),
    Op("DELETE", "/notifications/channels/{id}", "write", "Delete a notification channel",
       S.NotificationChannelDeleteOut, errors=(404, 409, 504),
       params=(Param("cleanup", {"type": "boolean", "default": True},
                     "Remove the channel's retained topics, Home Assistant discovery configs and "
                     "`<base_topic>/status` from the broker first (default true). Send `false` to "
                     "delete without touching the broker."),),
       description="With `cleanup` (the default) the broker is cleaned on the publisher thread before "
                   "the channel is deleted; when the channel is disabled or its broker cannot be "
                   "reached the answer is 409 and nothing is deleted (use `cleanup=false` to delete "
                   "anyway). Takes several seconds with cleanup."),
    Op("POST", "/notifications/channels/{id}/test", "write", "Send a test message through a channel",
       S.NotificationTestOut, errors=(404,),
       description="Connects with the stored settings and publishes a non-retained JSON message to "
                   "`<base_topic>/test`. Takes up to about 13 seconds. A failed test is a 200 with "
                   "`ok: false` and the reason in `message`."),
    Op("POST", "/notifications/channels/{id}/purge", "write",
       "Purge a channel's retained MQTT topics and Home Assistant devices", S.NotificationPurgeOut,
       request=S.NotificationPurgeRequest, errors=(404, 409, 504),
       description="Clean slate: publishes an empty retained payload to every retained topic under the "
                   "channel's `base_topic` and to every discovery config of this STD instance under "
                   "`ha_prefix`, plus everything STD remembers publishing. `<base_topic>/status` is "
                   "left alone. The body is optional; `republish` (default true) publishes everything "
                   "again after about 2 seconds, false leaves the broker empty until something changes "
                   "or the channel reconnects. 409 when the channel is disabled or not connected; "
                   "takes several seconds."),
    Op("GET", "/notifications/channels/{id}/previous-bases", "read",
       "List the base topics a channel used before", S.NotificationPreviousBasesOut, errors=(404,),
       description="The last 5 `{base_topic, ha_prefix}` pairs the channel used before a change, newest "
                   "first. The orphan scan looks under each of them."),
    Op("POST", "/notifications/channels/{id}/orphans/scan", "write",
       "Scan a channel's broker for orphaned retained STD topics", S.NotificationOrphanScanOut,
       request=S.NotificationOrphanScanRequest, errors=(404, 409, 504),
       description="A preview: nothing is cleared. Subscribes briefly to the current `base_topic`, every "
                   "remembered previous base, the optional `extra_base` and this instance's discovery "
                   "configs under the current and remembered `ha_prefix`, and lists the retained "
                   "STD-shaped topics (`status`, `summary`, `entry/<id>/state`, `entry/<id>/check/<id>`, "
                   "`stream/<id>`, discovery configs) that STD no longer desires. 409 when the channel "
                   "is disabled or not connected; takes several seconds. The body is optional."),
    Op("POST", "/notifications/channels/{id}/orphans/clear", "write", "Clear orphaned retained topics",
       S.NotificationOrphanClearOut, request=S.NotificationOrphanClearRequest, errors=(404, 409, 504),
       description="`topics` (what a scan returned) clears exactly those that are still inside the "
                   "scanned bases and still not desired; the rest come back in `skipped`. Without "
                   "`topics` the channel is scanned again and every orphan found is cleared. The body "
                   "is optional."),
    Op("POST", "/streams/{stream_id}/notifications/purge", "write",
       "Purge a stream's entries' MQTT topics and Home Assistant devices, then republish", S.StreamPurgeOut,
       errors=(404, 409, 504),
       description="One batch on every enabled channel: clears the state and check topics and the "
                   "discovery configs of every entry of the stream (soft-deleted ones too) plus the "
                   "stream's own status topic and hub device, waits about 2 seconds for Home "
                   "Assistant, then publishes what is still eligible (entries that are gone or "
                   "not opted in to Home Assistant stay cleared). 409 when no channel is enabled."),
    Op("POST", "/entries/{id}/notifications/purge", "write",
       "Purge an entry's MQTT topics and Home Assistant device, then republish it", S.EntryPurgeOut,
       errors=(404, 409, 504),
       description="Clears the entry's state topic, its check topics and its Home Assistant discovery "
                   "configs on every enabled channel, waits about 2 seconds for Home Assistant, then "
                   "republishes what is still desired so the device is recreated with fresh entity "
                   "ids (use it after a rename). An entry that is not opted in to Home Assistant only "
                   "has its state topics cleared and republished. 409 when no channel is enabled."),
    Op("PUT", "/streams/{stream_id}/snapshot", "ingest", "Push a full inventory snapshot", S.SnapshotAppliedOut,
       request=S.StreamSnapshotPut, errors=(409, 413),
       also=((202, S.SnapshotStoredOut | S.SnapshotIgnoredOut,
              "Accepted but not applied: a new or `pending`/`disabled` stream stores the snapshot "
              "(`message` tells the operator to enable it); an `ignored` stream discards it."),),
       description="The contract inventory sidecars code against (PRD 18.5). The body is the stream's "
                   "complete current item list; items that are missing from it are flagged missing, "
                   "never deleted. `stream_id` matches `^[a-z0-9][a-z0-9_-]{0,62}$`. A stream is created "
                   "`pending` by its first snapshot and applies nothing until the operator enables it "
                   "(200 once enabled, 202 before). `key_type: mac` means every `key` is a MAC (any "
                   "common form, normalised to lower-case colon form). Up to 5000 items and 2 MiB; a "
                   "snapshot is applied whole or not at all. 403 when the stream belongs to another "
                   "`ingest` key, 409 when `key_type` differs from the stream's, 413 over the size limit."),
    Op("GET", "/streams/{stream_id}/status", "ingest", "A stream's status, for a sidecar to log", S.StreamStatusOut,
       errors=(404,), description="404 until the first snapshot has created the stream."),

    Op("GET", "/streams", "read", "List inventory streams", S.StreamListOut, params=_PAGE,
       description="Status, producer, last counts, filters, default checks, entry counts and the last error of "
                   "every stream. `pending` counts the streams waiting for review (all pages)."),
    Op("GET", "/streams/{stream_id}", "read", "Get one stream", S.StreamOut, errors=(404,)),
    Op("PATCH", "/streams/{stream_id}", "write", "Rename a stream or change its filters and default checks", S.StreamOut,
       request=S.StreamPatch, errors=(404,),
       description=_PATCH_NOTE + " `network_include` / `network_exclude` are lists of network names "
                   "(null or an empty list clears the filter); items whose `network` is not in the include "
                   "list, or is in the exclude list, are dropped (`filtered`). Takes effect at the next "
                   "snapshot. `default_checks` is `{\"ping\": bool, \"tcp_port\": 1-65535 | null}` (null "
                   "clears): new stream entries start with an enabled Ping check on their IP and, when "
                   "set, a TCP check on `ip:port`. It affects entries created from then on; use "
                   "`POST /streams/{stream_id}/default-checks/apply` for the existing ones."),
    Op("POST", "/streams/{stream_id}/default-checks/apply", "write",
       "Add the stream's default checks to its existing entries", S.StreamApplyChecksOut, errors=(404,),
       description="Adds the missing default checks to every active entry of the stream that has an IP. An "
                   "entry that already has a check of that kind (any Ping, any TCP) is skipped, so nothing "
                   "is duplicated and customised checks are not touched. Returns the counts."),
    Op("GET", "/streams/{stream_id}/preview", "read", "What applying the stored snapshot would do",
       S.StreamPreviewOut, errors=(404, 409),
       description="The per-item action and the counts, with no writes. 409 when no snapshot is stored."),
    Op("POST", "/streams/{stream_id}/enable", "write", "Enable a stream and apply its stored snapshot",
       S.StreamEnableOut, errors=(404, 409),
       description="From `pending`, `disabled` or `ignored`. Applies the stored snapshot at once and every "
                   "later one as it arrives."),
    Op("POST", "/streams/{stream_id}/disable", "write", "Disable a stream", S.StreamDisableOut,
       request=S.StreamDisableRequest, errors=(404, 409),
       description="From `enabled`. The body is optional. `cleanup` is " + _CLEANUP + ". "
                   "`clear_blocks` (purge only, default false) also empties the block list. The stored "
                   "snapshot is kept in every mode, and later snapshots are still accepted and stored."),
    Op("POST", "/streams/{stream_id}/ignore", "write", "Ignore a stream", S.StreamOut, errors=(404, 409),
       description="From `pending` or `disabled`. The stored snapshot is discarded and later snapshots "
                   "are answered 202 and dropped."),
    Op("DELETE", "/streams/{stream_id}", "write", "Delete a stream", S.StreamDeleteOut,
       params=(Param("cleanup", {"type": "string", "enum": ["keep", "soft_delete", "purge"], "default": "keep"},
                     "What happens to the stream's entries."),),
       errors=(404,),
       description="`cleanup`: " + _CLEANUP.replace("(entries stay and are no longer updated)",
                                                    "(entries become manual entries, keeping mac and ip)")
                   + ". Soft-deleted entries also become manual entries so they can be restored. The "
                   "stream's blocks and link offers are removed with it. A sidecar that keeps posting "
                   "recreates the stream as `pending`."),
    Op("GET", "/streams/{stream_id}/blocks", "read", "List a stream's blocked keys", S.Page[S.BlockOut],
       params=_PAGE, errors=(404,)),
    Op("DELETE", "/streams/{stream_id}/blocks/{block_id}", "write", "Unblock a key", S.UnblockOut,
       errors=(404,), description="The next snapshot restores the entry or creates a new one."),
    Op("GET", "/streams/{stream_id}/offers", "read", "List open link offers", S.Page[S.OfferOut],
       params=_PAGE, errors=(404,),
       description="A new item whose name (or first DNS label) equals exactly one active manual "
                   "entry's name, host or host's first label waits here instead of being created."),
    Op("POST", "/streams/{stream_id}/offers/{offer_id}/accept", "write", "Accept a link offer", S.OfferAnswerOut,
       errors=(404, 409), description="The manual entry becomes a stream entry, keeping its id, history, "
                                      "checks and Home Assistant setting; its host is cleared."),
    Op("POST", "/streams/{stream_id}/offers/{offer_id}/decline", "write", "Decline a link offer",
       S.OfferAnswerOut, errors=(404, 409),
       description="A new stream entry is created from the item; the manual entry is left alone."),
    Op("GET", "/streams/{stream_id}/unmatched", "read", "Items of the latest snapshot with no entry",
       S.Page[S.StreamItemOut], params=_PAGE, errors=(404,),
       description="Not blocked and not yet an entry: what a manual entry can be linked to by hand."),
    Op("POST", "/streams/{stream_id}/link", "write", "Link a manual entry to a snapshot item", S.OfferAnswerOut,
       request=S.StreamLinkRequest, errors=(404, 409),
       description="`entry_id` is an active manual entry (its host, if any, is cleared: the stream "
                   "reports the address); `key` an unmatched item."),

    Op("GET", "/config", "read", "Effective configuration (read-only)", S.ConfigOut,
       description="Secrets are masked as `***`. `sources` says where each value came from."),
)

_ERROR_TEXT = {
    400: "Invalid request: bad body, query value or validation failure (`details` lists problems).",
    401: "Missing, invalid or revoked API key.",
    403: "The key's scope is too low for this endpoint.",
    404: "No such object.",
    409: "The request conflicts with the current state.",
    413: "The request body is larger than the limit (2 MiB for a snapshot).",
    504: "The background worker did not finish in time; the operation may still complete.",
}


# --- generation ----------------------------------------------------------------

# Path parameters are integer ids unless named here.
_PATH_PARAM_SCHEMAS = {
    "stream_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,62}$"},
}


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
            {"name": n, "in": "path", "required": True, "schema": _PATH_PARAM_SCHEMAS.get(n, {"type": "integer"})}
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
        for status, model, text in op.also:
            responses[str(status)] = {
                "description": text,
                "content": {"application/json": {"schema": comp.schema_for(model)}},
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
            "x-api-revision": API_REVISION,
            "description": (
                "Everything an operator can do in the UI, over JSON. Authenticate with an admin API key "
                "(Settings -> API) sent as `Authorization: Bearer <key>`. A `read` key can read; a "
                "`write` key can read and change; an `ingest` key (for inventory sidecars) can use only the two stream "
                "ingest routes. Errors are `{\"error\": str, \"details\": ...}`; "
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
