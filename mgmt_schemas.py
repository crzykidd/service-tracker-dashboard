"""Request models and response shapes for the management API (v0.8.0, PRD 14).

Kept apart from `schemas.py`, which is the notifier register contract only.

Request bodies are pydantic models with `extra="forbid"` and strict types
(JSON `true` is a bool, `"60"` is not an int). They check shape only; value
rules (ranges, target formats, name limits) live in `check_form` and
`entry_rules` so the browser forms and the API share one rule set.

Response shapes are `TypedDict`s. The serializers in `mgmt_serializers.py`
are plain functions returning these dicts, and the OpenAPI generator
(v080-04) builds response schemas from them with
`pydantic.TypeAdapter(SomeTypedDict).json_schema()`.
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict

# pydantic refuses `typing.TypedDict` before Python 3.12, and CI runs 3.11.
from typing_extensions import TypedDict

# --- requests ------------------------------------------------------------------


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class UrlCheckSettings(_Request):
    """Settings of an Internal/External URL check. Omitted fields keep their value."""

    enabled: bool | None = None
    mode: str | None = None              # "status" | "body"
    interval_seconds: int | None = None  # 30..86400; null = global default
    timeout_seconds: int | None = None   # 1..60; null = global default
    verify_tls: bool | None = None
    cert_min_days: int | None = None     # 1..365; https only (ignored at runtime on http); null = off


class UrlChecksIn(_Request):
    internal: UrlCheckSettings | None = None
    external: UrlCheckSettings | None = None


class ServiceCheckCreate(_Request):
    target: str
    check_type: str = "http"             # "http" | "tcp" | "ping" | "dns"
    name: str | None = None              # defaults to the target
    mode: str | None = None              # "status" (default) | "body"; HTTP only
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    verify_tls: bool = True
    enabled: bool = True
    # DNS checks only (target is then the DNS server, an IP with optional port).
    dns_name: str | None = None              # the query name (an IP for PTR); required for dns
    dns_record_type: str | None = None       # A (default) | AAAA | CNAME | TXT | PTR | MX | NS | SRV
    dns_expected_rcode: str | None = None    # NOERROR (default), NXDOMAIN, ...
    dns_expected_answer: str | None = None   # empty/null = judge by rcode only
    cert_min_days: int | None = None         # http checks only; 1..365, fails when the cert has fewer days left


class EntryCreate(_Request):
    name: str
    host: str | None = None
    description: str | None = None
    group: str | None = None             # group name; created if missing
    internalurl: str | None = None
    externalurl: str | None = None
    icon: str | None = None              # icon file name; fetched if missing
    sort_priority: int | None = None
    locked: bool = False
    url_checks: UrlChecksIn | None = None
    checks: list[ServiceCheckCreate] = []


class EntryPatch(_Request):
    """Every field optional; a field that is present is applied (null clears
    it where that makes sense). Which fields were sent is read from
    `model_fields_set`."""

    name: str | None = None              # manual entries only
    host: str | None = None              # manual entries only
    description: str | None = None
    group: str | None = None
    internalurl: str | None = None
    externalurl: str | None = None
    icon: str | None = None
    sort_priority: int | None = None
    locked: bool | None = None


class CheckPatch(_Request):
    """Every field optional. Which are allowed depends on the check's kind
    (URL: enabled/mode/interval/timeout/verify; container: enabled/interval;
    service: everything, including the dns_* fields)."""

    enabled: bool | None = None
    name: str | None = None
    check_type: str | None = None
    target: str | None = None
    mode: str | None = None
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    verify_tls: bool | None = None
    dns_name: str | None = None              # service checks of type dns only
    dns_record_type: str | None = None
    dns_expected_rcode: str | None = None
    dns_expected_answer: str | None = None   # null clears it (rcode only)
    cert_min_days: int | None = None         # URL and http service checks; null clears it


# Notifier-owned entry fields. A PATCH naming any of them is a 400.
NOTIFIER_OWNED_FIELDS = frozenset({
    "id", "source", "container_name", "container_id", "stack_name", "docker_status",
    "started_at", "last_api_update", "last_updated", "image_registry", "image_owner",
    "image_name", "image_tag", "image_icon", "networks", "exposed_ports",
    "published_ports", "exposures", "internalurl_source", "externalurl_source",
    "notifier", "notifier_reported_group_name", "notifier_reported_sort_priority",
    "health", "checks", "widget", "group_id", "stale", "deleted_at",
})


class GroupCreate(_Request):
    name: str
    icon: str | None = None
    sort_priority: int | None = None


class GroupPatch(_Request):
    name: str | None = None
    icon: str | None = None              # null clears it
    sort_priority: int | None = None     # null clears it


class WidgetPut(_Request):
    """Attach or reconfigure an entry's widget (a full replacement of type,
    url and fields). `widget_api_key` omitted keeps the stored key; null
    clears it."""

    type: str
    url: str
    fields: list[str]
    widget_api_key: str | None = None


class UpdateCheckSettingsPut(_Request):
    """Omitted fields keep their value; at least one is required."""

    enabled: bool | None = None
    interval_hours: int | None = None   # whole hours, 1 or more


class ExposureSettingsPut(_Request):
    layer_directions: dict[str, str]
    host_overrides: dict[str, dict[str, str]] = {}


# --- responses -----------------------------------------------------------------

T = TypeVar("T")


class Page(TypedDict, Generic[T]):
    """Every list endpoint returns this envelope."""

    items: list[T]
    total: int
    limit: int
    offset: int


class ErrorOut(TypedDict):
    error: str
    details: Any


class UpdateInfoOut(TypedDict):
    enabled: bool                    # false: update check turned off (no fetch is made)
    latest_version: str | None       # latest GitHub release seen, bare (e.g. "0.9.1")
    update_available: bool           # true only when latest_version > the running version
    release_url: str | None          # the release page, set when update_available
    checked_at: str | None           # UTC ISO time of the last successful check


class WhoamiOut(TypedDict):
    name: str
    prefix: str
    scope: str                       # "read" | "write"
    version: str                     # the STD version, e.g. "0.9.0" (older STDs omit it)
    commit: str                      # full git SHA of the build, or "unknown"
    channel: str                     # release | main | dev | pr | local
    build_time: str                  # UTC ISO build time, or "unknown"
    update: UpdateInfoOut            # GitHub update check (additive; older STDs omit it)


class CheckDeleteOut(TypedDict):
    id: int
    deleted: bool


class CheckLastOut(TypedDict):
    state: str                       # "up" | "down" | "unknown"
    checked_at: str | None           # ISO 8601 UTC, Z suffix
    latency_ms: int | None
    status_code: int | None
    message: str | None


class CheckOut(TypedDict):
    id: int
    entry_id: int
    kind: str                        # internal_url | external_url | service | container
    name: str
    check_type: str
    target: str | None               # URL kinds: the entry's current URL
    mode: str
    enabled: bool
    active: bool                     # enabled and able to run (counts toward health)
    interval_seconds: int | None
    timeout_seconds: int | None
    verify_tls: bool
    dns_name: str | None             # dns checks only; null on every other type
    dns_record_type: str | None
    dns_expected_rcode: str | None
    dns_expected_answer: str | None
    cert_min_days: int | None        # certificate-expiry minimum (https checks); null = off
    cert_expires_at: str | None      # leaf cert notAfter last seen, ISO 8601 UTC Z; null if unknown
    consecutive_failures: int
    last: CheckLastOut


class HealthFailureOut(TypedDict):
    check: str
    message: str | None


class EntryHealthOut(TypedDict):
    state: str                       # up | degraded | down | unknown | none
    label: str
    checks_total: int
    checks_failing: int
    failures: list[HealthFailureOut]


class GroupRefOut(TypedDict):
    id: int
    name: str


class ExposureOut(TypedDict):
    layer: str
    hostname: str | None
    tls: bool | None
    path_prefix: str | None
    auth: str | None


class NotifierOut(TypedDict):
    container_id: str | None
    stack_name: str | None
    docker_status: str | None
    started_at: str | None
    last_api_update: str | None
    image_registry: str | None
    image_owner: str | None
    image_name: str | None
    image_tag: str | None
    reported_group_name: str | None
    reported_sort_priority: int | None
    networks: Any
    exposed_ports: Any
    published_ports: Any
    exposures: list[ExposureOut]


class WidgetOut(TypedDict):
    id: int
    type: str
    url: str | None
    fields: Any
    widget_api_key_set: bool         # the key itself is never returned


class EntryOut(TypedDict):
    id: int
    name: str
    host: str | None
    description: str | None
    source: str                      # "manual" | "notifier"
    group: GroupRefOut | None
    internalurl: str | None
    externalurl: str | None
    internalurl_source: str | None   # ui_edit | explicit_label | synthesized | null
    externalurl_source: str | None
    icon: str | None
    sort_priority: int | None
    locked: bool
    stale: bool
    last_updated: str | None
    deleted_at: str | None
    health: EntryHealthOut
    checks: list[CheckOut]


class EntryDetailOut(EntryOut):
    notifier: NotifierOut
    widget: WidgetOut | None


class RunRequestedOut(TypedDict):
    ok: bool
    queued: int
    requested_at: str


class PermanentDeleteOut(TypedDict):
    id: int
    permanent: bool


class SummaryCountsOut(TypedDict):
    total: int
    passing: int
    failing: int
    unknown: int
    stale: int


class SummaryFailureOut(TypedDict):
    check: str
    kind: str
    message: str | None
    since: str | None                # start of the current run of failures


class SummaryEntryOut(TypedDict):
    id: int
    name: str
    host: str | None
    state: str
    failures: list[SummaryFailureOut]


class HealthSummaryOut(TypedDict):
    counts: SummaryCountsOut
    failing: list[SummaryEntryOut]



class HealthFailureSampleOut(TypedDict):
    ts: str | None
    message: str | None
    status_code: int | None


class HealthBarOut(TypedDict):
    start: str | None
    end: str | None
    ok: int                          # passing samples in the bucket
    fail: int
    messages: list[str]              # up to 3 distinct failure messages


class CheckHealthOut(TypedDict):
    id: int
    kind: str
    name: str
    check_type: str
    target: str | None
    mode: str
    state: str                       # "up" | "down" | "unknown"
    last_checked_at: str | None
    latency_ms: int | None
    status_code: int | None
    message: str | None
    uptime_24h: float | None         # percent; null with no samples
    uptime_7d: float | None
    failures: list[HealthFailureSampleOut]   # newest first, up to 20
    bars: list[HealthBarOut]


class EntryHealthDetailOut(TypedDict):
    entry_id: int
    range: str                       # "24h" | "7d"
    generated_at: str
    checks: list[CheckHealthOut]


class GroupOut(TypedDict):
    id: int
    name: str
    sort_priority: int | None
    icon: str | None
    entry_count: int                 # active (not deleted) entries


class GroupDeleteOut(TypedDict):
    id: int
    deleted: bool
    ungrouped_entries: int


class WidgetFieldOut(TypedDict):
    key: str
    label: str
    description: str | None


class WidgetTypeOut(TypedDict):
    type: str
    description: str | None
    available_fields: list[WidgetFieldOut]


class WidgetInstanceOut(WidgetOut):
    entry_ids: list[int]             # every entry referencing it, deleted ones included
    detached: bool


class WidgetDetachOut(TypedDict):
    entry_id: int
    widget_id: int
    deleted: bool                    # true when the widget and its values were removed


class WidgetDeleteOut(TypedDict):
    id: int
    deleted: bool


class ExposureSettingsOut(TypedDict):
    layer_directions: dict[str, str]
    host_overrides: dict[str, dict[str, str]]
    discovered_layers: list[str]
    discovered_hosts: list[str]
    valid_directions: list[str]


class ExposureSettingsSavedOut(ExposureSettingsOut):
    recomputed: int                  # services whose URLs were recomputed


class UpdateCheckSettingsOut(TypedDict):
    enabled: bool
    interval_hours: int


class ConfigOut(TypedDict):
    version: str
    commit: str
    channel: str
    build_time: str
    update: UpdateInfoOut
    settings: dict[str, Any]         # secrets appear as "***" (null when unset)
    sources: dict[str, str]          # "env" | "file" | "default" per setting
