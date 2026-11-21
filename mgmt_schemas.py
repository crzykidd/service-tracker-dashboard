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

from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

# pydantic refuses `typing.TypedDict` before Python 3.12, and CI runs 3.11.
from typing_extensions import TypedDict

from streams import check_attributes, normalize_ip, normalize_mac

# --- requests ------------------------------------------------------------------


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _text(max_length):
    """A trimmed string of 1..max_length characters."""
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


class StreamSnapshotItem(_Request):
    """One inventory item (PRD 18.5). `key` is the item's identity in the stream;
    for `key_type: mac` it and `mac` accept any common MAC form."""

    key: _text(128)
    name: _text(128)                      # the entry name, e.g. the reservation hostname
    ip: str | None = None                 # an IPv4 or IPv6 address
    mac: str | None = None
    network: _text(64) | None = None      # e.g. the DHCP scope; the stream's network filter matches it
    # <= 32 keys matching ^[A-Za-z0-9_.-]{1,64}$; string (<= 256 chars), number, boolean or null.
    attributes: dict[str, StrictStr | StrictInt | StrictFloat | StrictBool | None] | None = None

    @field_validator("ip")
    @classmethod
    def _ip(cls, value):
        if value is None:
            return None
        normalised = normalize_ip(value)
        if normalised is None:
            raise ValueError("ip must be an IPv4 or IPv6 address")
        return normalised

    @field_validator("mac")
    @classmethod
    def _mac(cls, value):
        if value is None:
            return None
        normalised = normalize_mac(value)
        if normalised is None:
            raise ValueError("mac must be a MAC address (aa:bb:cc:dd:ee:ff, AA-BB-..., aabb.ccdd.eeff or aabbccddeeff)")
        return normalised

    @field_validator("attributes")
    @classmethod
    def _attributes(cls, value):
        if value is None:
            return None
        problem = check_attributes(value)
        if problem:
            raise ValueError(problem)
        return value


class StreamSnapshotPut(_Request):
    """The body of `PUT /api/v1/streams/<stream_id>/snapshot`: a full snapshot."""

    display_name: _text(32)               # used when the stream is created; the operator may rename it
    producer: _text(64)                   # e.g. std-source-technitium
    producer_version: _text(32)
    key_type: Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,16}$")]   # `mac`: every key is a MAC
    items: Annotated[list[StreamSnapshotItem], Field(max_length=5000)]
    # Optional (API revision 3): how often the producer posts, 60-86400 s. STD uses it
    # for staleness unless the operator set an expected interval. Older STDs refuse it.
    snapshot_interval_seconds: Annotated[int, Field(ge=60, le=86400)] | None = None


class StreamDefaultChecksIn(_Request):
    """Checks a new stream entry starts with, on the entry's IP. Both off = none."""

    ping: bool = False                    # an enabled Ping check on the entry's IP
    tcp_port: int | None = None           # 1..65535: also an enabled TCP check on ip:port; null = none


class StreamPatch(_Request):
    """Every field is optional; null (or an empty list) clears a network filter,
    null clears `default_checks`."""

    display_name: str | None = None
    network_include: list[str] | None = None
    network_exclude: list[str] | None = None
    default_checks: StreamDefaultChecksIn | None = None
    expected_interval_seconds: int | None = None   # 60-86400; null = the producer's interval or 15 min
    missing_expiry_days: int | None = None         # 1-3650; null = never auto soft-delete missing entries


class StreamDisableRequest(_Request):
    cleanup: str = "keep"                 # keep | soft_delete | purge
    clear_blocks: bool = False            # purge only: also empty the block list


class EntryUnlinkRequest(_Request):
    block: bool = False                   # also block the item key so no snapshot re-adds or re-offers it


class StreamLinkRequest(_Request):
    entry_id: int                         # an active manual entry (its host, if any, is cleared)
    key: str                              # an unmatched key of the stream's latest snapshot


class UrlCheckSettings(_Request):
    """Settings of an Internal/External URL check. Omitted fields keep their value."""

    enabled: bool | None = None
    mode: str | None = None              # "status" | "body"
    interval_seconds: int | None = None  # 30..86400; null = global default
    timeout_seconds: int | None = None   # 1..60; null = global default
    verify_tls: bool | None = None
    cert_min_days: int | None = None     # 1..365; https only (ignored at runtime on http); null = off
    ha_exclude: bool | None = None       # true removes the check's Home Assistant entity


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
    ha_exclude: bool = False                 # true: no Home Assistant entity for this check


class EntryCreate(_Request):
    name: str
    host: str | None = None
    description: str | None = None
    group: str | None = None             # group name; created if missing
    internalurl: str | None = None
    externalurl: str | None = None
    icon: str | None = None              # icon file name; fetched if missing
    image_repo_url: str | None = None    # http(s) override for the image repository link
    sort_priority: int | None = None
    locked: bool = False
    ha_publish: bool = False             # true: publish this entry's device to Home Assistant
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
    image_repo_url: str | None = None    # null/"" clears the override
    sort_priority: int | None = None
    locked: bool | None = None
    ha_publish: bool | None = None       # true publishes the entry's Home Assistant device
    # Image update check (Docker entries only, revision 5): auto | tags | digest | off
    image_update_policy: str | None = None
    image_update_scope: str | None = None    # any | minor | patch; null = the global default
    image_tag_pattern: str | None = None     # regex (full match) for the tag model; null/"" clears it


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
    ha_exclude: bool | None = None           # any check; true removes its Home Assistant entity


# Notifier-owned entry fields. A PATCH naming any of them is a 400.
NOTIFIER_OWNED_FIELDS = frozenset({
    "id", "source", "container_name", "container_id", "stack_name", "docker_status",
    "started_at", "last_api_update", "last_updated", "image_registry", "image_owner",
    "image_name", "image_tag", "image_icon", "networks", "exposed_ports",
    "published_ports", "exposures", "internalurl_source", "externalurl_source",
    "notifier", "notifier_reported_group_name", "notifier_reported_sort_priority",
    "health", "checks", "widget", "group_id", "stale", "deleted_at", "image_update",
    "image_info", "image_running_digest",
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


class ImageUpdateSettingsPut(_Request):
    """Omitted fields keep their value; at least one is required."""

    enabled: bool | None = None
    scope: str | None = None            # any | minor | patch: the default scope of the tag model


class ImageUpdateRunRequest(_Request):
    """The body is optional: without `entry_id` every image is checked."""

    entry_id: int | None = None


class UpdateCheckSettingsPut(_Request):
    """Omitted fields keep their value; at least one is required."""

    enabled: bool | None = None
    interval_hours: int | None = None   # whole hours, 1 or more


class BackupJobPut(_Request):
    """One daily backup job. Omitted fields keep their value."""

    enabled: bool | None = None
    time: str | None = None             # HH:MM, 00:00 to 23:59, container time
    keep_days: int | None = None        # 1 to 365


class BackupExportJobPut(BackupJobPut):
    format: Literal["yaml", "json"] | None = None


class BackupSettingsPut(_Request):
    """Change the backup settings (same rules as Settings -> Backup & restore). Omitted
    fields keep their value; at least one is required. A field pinned by an environment
    variable is a 409 unless the value is unchanged."""

    path: str | None = None             # absolute folder; created when missing
    snapshot: BackupJobPut | None = None
    export: BackupExportJobPut | None = None


class BackupRunRequest(_Request):
    kind: Literal["snapshot", "export"]


class ImportSelectionRow(_Request):
    """One row of an import selection (design 7.1). A row left out of `selection` is not applied;
    `fields: null` means every field that is actionable in the chosen mode."""

    apply: bool = True
    fields: list[str] | None = None
    target_id: int | None = None
    create: bool = False
    options: list[str] = []


class ImportPlanRequest(_Request):
    """Dry-run an import. Send the export as `document` (a v1 object) or `document_text` (YAML or
    JSON text, also an old YAML backup); exactly one. `stream_map` maps a file stream id to a local
    stream id (`null` skips it); a stream left out is matched by id. `selection` (optional) is the
    set of rows you intend to apply, and `fingerprint` in the answer is the one for exactly those
    rows; without it the answer carries the default (pre-ticked) selection."""

    document: dict[str, Any] | None = None
    document_text: str | None = None
    stream_map: dict[str, str | None] | None = None
    selection: dict[str, ImportSelectionRow] | None = None

    @model_validator(mode="after")
    def _one_document(self):
        if (self.document is None) == (self.document_text is None):
            raise ValueError("send exactly one of document and document_text")
        return self


class ImportApplyRequest(ImportPlanRequest):
    """Apply the selected rows. `fingerprint` must be the one `POST /import/plan` returned for this
    same `selection` and `stream_map`; if the rows changed since, nothing is written (409)."""

    selection: dict[str, ImportSelectionRow]
    mode: Literal["fill", "overwrite"] = "fill"
    fingerprint: str


class NotificationChannelCreate(_Request):
    """Add a notification channel. `config` holds the non-secret settings of the
    channel type (for `mqtt`: host, port, tls, tls_insecure, username, client_id,
    base_topic, qos, keepalive, ha_discovery, ha_prefix, ha_device_prefix; unknown keys are rejected). `secret` is the MQTT
    password, write-only."""

    name: str
    type: str = "mqtt"
    enabled: bool = False
    config: dict[str, Any] = {}
    secret: str | None = None


class NotificationChannelPatch(_Request):
    """Every field optional. `config` keys are merged over the stored config;
    `secret` omitted keeps the stored value, null clears it."""

    name: str | None = None
    enabled: bool | None = None
    config: dict[str, Any] | None = None
    secret: str | None = None
    # Clear the broker first. Applies when this request disables the channel (default
    # false) or changes the base topic / discovery prefix (default true).
    cleanup: bool | None = None


class NotificationOrphanScanRequest(_Request):
    """Scan a channel's broker for orphaned retained STD topics. `extra_base` also
    scans one more base topic the operator remembers using."""

    extra_base: str | None = None


class NotificationOrphanClearRequest(_Request):
    """Clear orphans. `topics` is the list a scan returned (only those are cleared, and
    only while they are still orphans); omitted, the channel is scanned again and every
    orphan found is cleared. `extra_base` as for the scan."""

    topics: list[str] | None = None
    extra_base: str | None = None


class NotificationPurgeRequest(_Request):
    """Purge a channel's broker. `republish` (default true) publishes the current
    state and discovery configs again after about 2 seconds; false leaves the
    broker empty until something changes or the channel reconnects."""

    republish: bool = True


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
    api_revision: int                # /api/v1 contract revision (additive; older STDs omit it)


class StreamCountsOut(TypedDict):
    created: int
    updated: int
    unchanged: int
    restored: int
    missing: int                     # entries of the stream absent from this snapshot
    blocked: int
    link_offers: int                 # items held back for a manual-entry link offer
    filtered: int                    # dropped by the stream's network filter


class SnapshotAppliedOut(TypedDict):
    stream_id: str
    stream_status: str               # "enabled"
    applied: bool                    # true
    item_count: int
    counts: StreamCountsOut


class SnapshotStoredOut(TypedDict):
    stream_id: str
    stream_status: str               # "pending" | "disabled"
    applied: bool                    # false
    item_count: int
    message: str


class SnapshotIgnoredOut(TypedDict):
    stream_id: str
    stream_status: str               # "ignored": discarded, not stored
    applied: bool                    # false


class StreamStatusOut(TypedDict):
    stream_id: str
    stream_status: str               # pending | enabled | disabled | ignored
    display_name: str
    last_snapshot_at: str | None
    last_applied_at: str | None
    last_item_count: int | None
    last_counts: StreamCountsOut | None


class MetaOut(TypedDict):
    std_version: str                 # bare semver, e.g. "0.10.0"
    api_revision: int                # /api/v1 contract revision
    features: list[str]              # register | management | notifications | streams | backup


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
    ha_exclude: bool                 # true: not published to Home Assistant
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
    image_ref: str | None            # canonical reference, observed (revision 5; null until the next register)
    image_info: Any                  # {id, created, version, revision, source} from the notifier (revision 5; null until it sends one)
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


class InventoryOut(TypedDict):
    stream_id: str                   # the stream's slug
    stream: str                      # the stream's display name
    key: str
    mac: str | None
    ip: str | None
    network: str | None
    attributes: Any
    missing: bool                    # absent from the stream's latest snapshot
    missing_since: str | None        # when it was flagged missing (UTC, Z); null while present (revision 3)
    name_source: str | None          # "stream" | "ui_edit" (renamed in STD)
    linked: bool                     # was a manual entry linked to the stream; cleanup unlinks it, never deletes it


class ImageUpdateOut(TypedDict):
    state: str | None                # update | current | unknown | error | pinned | off (off also while the check is switched off)
    latest: str | None               # the newer tag, or `sha256:<12 hex>` of the newer digest
    kind: str | None                 # major | minor | patch | build | digest
    since: str | None                # when the state became `update` (UTC, Z)
    checked_at: str | None           # last successful check of the reference (UTC, Z)
    error: str | None                # why the last check of the reference failed
    reason: str | None               # why the state is unknown / error / pinned
    model: str | None                # tags | digest
    rebuilt: bool                    # the running tag was re-pushed upstream (a muted note, not an update)
    policy: str                      # auto | tags | digest | off
    scope: str | None                # any | minor | patch; null = the global default
    tag_pattern: str | None
    running_digest: str | None
    ref: str | None                  # the canonical image reference
    provider: str | None             # which update provider produced the state


class EntryOut(TypedDict):
    id: int
    name: str
    host: str | None
    description: str | None
    source: str                      # "manual" | "notifier" | "stream"
    group: GroupRefOut | None
    internalurl: str | None
    externalurl: str | None
    internalurl_source: str | None   # ui_edit | explicit_label | synthesized | null
    externalurl_source: str | None
    icon: str | None
    image_repo_url: str | None       # operator override (null: derived from the image fields)
    image_repo_link: str | None      # the link shown: the override, else derived, else null
    sort_priority: int | None
    locked: bool
    ha_publish: bool                 # true: published to Home Assistant (opt-in)
    stale: bool
    last_updated: str | None
    deleted_at: str | None
    inventory: InventoryOut | None   # set for source "stream" (additive; older STDs omit it)
    image_update: ImageUpdateOut | None  # Docker entries only (revision 5); null for manual and stream entries
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
    stale: int                       # Docker entries whose notifier stopped reporting
    streams_stale: int               # stale inventory streams (revision 3)


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


class SummaryStreamOut(TypedDict):
    stream_id: str
    display_name: str
    status: str                      # pending | enabled | disabled | ignored
    stale: bool
    last_snapshot_at: str | None
    last_item_count: int | None
    effective_interval_seconds: int
    last_error: str | None
    last_rejected_at: str | None
    last_rejection: str | None
    entries_active: int
    entries_missing: int


class SummaryStaleStreamOut(TypedDict):
    stream_id: str
    display_name: str
    state: str                       # "down"
    message: str                     # e.g. "No snapshot for 42 min (expected every 5 min)"
    since: str | None                # when it became stale (UTC, Z)


class HealthSummaryOut(TypedDict):
    counts: SummaryCountsOut
    failing: list[SummaryEntryOut]
    streams: list[SummaryStreamOut]              # every inventory stream, compact (revision 3)
    stale_streams: list[SummaryStaleStreamOut]   # one "down" line per stale stream (revision 3)



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


class BackupSettingOut(TypedDict):
    value: Any
    origin: str                      # "env" | "ui" | "file" | "default"


class BackupJobOut(TypedDict):
    enabled: BackupSettingOut
    time: BackupSettingOut           # HH:MM
    keep_days: BackupSettingOut


class BackupExportJobOut(BackupJobOut):
    format: BackupSettingOut         # "yaml" | "json"


class BackupRunInfoOut(TypedDict):
    at: str                          # container local time, ISO 8601
    ok: bool
    file: str | None
    size: int | None
    error: str | None
    trigger: str                     # "schedule" | "manual"


class BackupSettingsOut(TypedDict):
    path: BackupSettingOut
    snapshot: BackupJobOut
    export: BackupExportJobOut
    last_runs: dict[str, BackupRunInfoOut]   # by kind; absent before the first run
    next_runs: dict[str, str | None]         # by kind; null when disabled (container local time)


class BackupSettingsSavedOut(BackupSettingsOut):
    warnings: list[str]              # for example: the folder is outside /config


class BackupFileOut(TypedDict):
    name: str
    kind: str                        # "snapshot" | "export"
    size: int                        # bytes
    modified: str                    # ISO 8601, UTC, with Z
    manual: bool                     # made by Run now (the name carries a time)
    legacy: bool                     # a pre-0.11 entry-list file


class BackupListOut(TypedDict):
    items: list[BackupFileOut]       # snapshots and exports, newest first


class BackupRunOut(TypedDict):
    kind: str
    ok: bool
    file: str | None
    size: int | None
    error: str | None
    at: str
    trigger: str


class ImportPlanOut(TypedDict):
    header: dict[str, Any]
    stream_mapping: list[dict[str, Any]]
    rows: list[dict[str, Any]]
    counts: dict[str, Any]
    warnings: list[str]
    stream_map: dict[str, str | None]
    default_selection: dict[str, dict[str, Any]]
    fingerprint: str


class ImportResultOut(TypedDict):
    mode: str
    counts: dict[str, int]
    skipped: dict[str, int]
    still_to_do: dict[str, Any]
    notes: list[str]
    applied: list[str]


class ImportStaleOut(TypedDict):
    error: str
    details: None
    plan: ImportPlanOut


class ImageUpdateSettingsOut(TypedDict):
    enabled: bool                    # default false
    enabled_origin: str              # env (STD_IMAGE_UPDATE_ENABLED, read-only here) | ui | default
    scope: str                       # any | minor | patch
    interval_hours: int              # always 24: fixed, there is no setting
    last_run: dict[str, Any] | None  # {at, trigger, refs, checked, updates, errors, skipped, duration_seconds}
    next_run: str | None             # the daily job's next run (UTC, Z); null while the check is off


class ImageReferenceEntryOut(TypedDict):
    id: int
    name: str
    host: str | None
    state: str | None
    latest: str | None
    kind: str | None
    since: str | None
    policy: str


class ImageReferenceOut(TypedDict):
    ref: str
    registry: str | None
    repository: str | None
    tag: str | None
    remote_digest: str | None
    remote_digest_changed_at: str | None
    checked_at: str | None
    error: str | None
    error_at: str | None
    failures: int
    next_check_at: str | None        # the reference is in backoff until then
    tags_total: int | None           # tags the registry listed (tag model)
    entries: list[ImageReferenceEntryOut]


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


class NotificationStatusOut(TypedDict):
    state: str                       # disabled | stopped | connecting | connected | error
    last_error: str | None
    since: str | None                # when the state last changed (UTC), null when not live


class NotificationChannelOut(TypedDict):
    id: int
    type: str
    name: str
    enabled: bool
    config: dict[str, Any]
    secret_set: bool                 # the secret itself is never returned
    status: NotificationStatusOut
    created_at: str | None
    updated_at: str | None


class NotificationTestOut(TypedDict):
    ok: bool
    message: str                     # what happened; never contains the secret


class NotificationPurgeOut(TypedDict):
    channel_id: int
    topics_cleared: int
    state_topics: int                # under the channel's base topic
    discovery_topics: int            # Home Assistant discovery configs
    republished: bool


class PurgeChannelCountOut(TypedDict):
    id: int
    name: str
    state_topics: int
    discovery_topics: int


class EntryPurgeOut(TypedDict):
    entry_id: int
    topics_cleared: int
    channels: list[PurgeChannelCountOut]
    republished: bool


class NotificationCleanupOut(TypedDict):
    topics_cleared: int
    state_topics: int
    discovery_topics: int


class NotificationChannelDeleteOut(TypedDict):
    id: int
    deleted: bool
    cleanup: NotificationCleanupOut | None   # what was cleared from the broker; null when not requested


class StreamPurgeOut(TypedDict):
    stream_id: str
    entries: int                     # entries of the stream, soft-deleted ones included
    topics_cleared: int
    channels: list[PurgeChannelCountOut]
    republished: bool


class OrphanTopicOut(TypedDict):
    topic: str
    kind: str                        # state | discovery


class NotificationOrphanScanOut(TypedDict):
    channel_id: int
    scanned: list[str]               # the topic filters subscribed to
    count: int
    orphans: list[OrphanTopicOut]


class NotificationOrphanClearOut(TypedDict):
    channel_id: int
    topics_cleared: int
    topics: list[str]
    skipped: list[str]               # given topics that are outside the scanned bases or no longer orphans


class PreviousBaseOut(TypedDict):
    base_topic: str
    ha_prefix: str


class NotificationPreviousBasesOut(TypedDict):
    channel_id: int
    limit: int                       # how many are remembered (the newest)
    items: list[PreviousBaseOut]


class StreamEntryStatsOut(TypedDict):
    total: int
    active: int
    deleted: int
    missing: int                     # active entries absent from the latest snapshot
    linked: int                      # active entries that were manual entries linked to the stream


class StreamDefaultChecksOut(TypedDict):
    ping: bool
    tcp_port: int | None


class StreamOut(TypedDict):
    stream_id: str
    display_name: str
    producer: str
    producer_version: str
    key_type: str
    status: str                      # pending | enabled | disabled | ignored
    api_key: str | None              # name of the key that created the stream
    network_include: list[str] | None
    network_exclude: list[str] | None
    default_checks: StreamDefaultChecksOut   # checks new entries start with (additive in revision 2)
    first_seen_at: str | None
    last_snapshot_at: str | None
    last_applied_at: str | None
    last_item_count: int | None
    last_counts: StreamCountsOut | None
    last_error: str | None           # the last STD-side apply failure (cleared by a good apply)
    # Observability (revision 3, PRD 18.9).
    expected_interval_seconds: int | None    # the operator's value (null = not set)
    producer_interval_seconds: int | None    # what the producer advertises (snapshot_interval_seconds)
    effective_interval_seconds: int          # operator > producer > 900
    interval_source: str                     # operator | producer | default
    stale: bool                              # enabled and no snapshot for > 2 x the effective interval
    stale_after_seconds: int
    snapshot_age_seconds: int | None         # since the last snapshot (or first seen)
    stale_message: str | None                # e.g. "No snapshot for 42 min (expected every 5 min)"
    last_rejected_at: str | None             # the last refused snapshot PUT (400/409/413)
    last_rejection: str | None               # "<status>: <first error>"
    rejecting: bool                          # the latest attempt was refused (newer than the last accepted one)
    missing_expiry_days: int | None          # auto soft-delete after N days missing; null = off
    entries: StreamEntryStatsOut
    blocks: int
    link_offers: int


class StreamListOut(TypedDict):
    items: list[StreamOut]
    total: int
    limit: int
    offset: int
    pending: int                     # streams waiting for review (status "pending"), all pages
    stale: int                       # enabled streams that are stale, all pages (revision 3)


class StreamApplyChecksOut(TypedDict):
    stream: StreamOut
    entries: int                     # active entries of the stream
    entries_changed: int             # entries that gained at least one check
    checks_added: int


class StreamEnableOut(TypedDict):
    stream: StreamOut
    applied: bool                    # false when no snapshot was stored yet
    counts: StreamCountsOut | None


class StreamCleanupOut(TypedDict):
    entries: int                     # entries the stream had
    kept: int
    soft_deleted: int
    purged: int
    unlinked: int                    # linked manual entries that went back to manual (never deleted)
    offers_removed: int
    blocks_cleared: int


class EntryUnlinkOut(TypedDict):
    entry: EntryOut                  # now a manual entry
    blocked: bool                    # the item key was put on the stream's block list
    host_restored: bool              # a linked entry got its pre-link host back
    host_clash: bool                 # the pre-link host was left empty because (host, name) is now taken
    host: str | None


class StreamDisableOut(TypedDict):
    stream: StreamOut
    cleanup: str
    result: StreamCleanupOut


class StreamDeleteOut(TypedDict):
    stream_id: str
    deleted: bool
    cleanup: str
    result: StreamCleanupOut


class StreamPreviewItemOut(TypedDict):
    key: str
    name: str
    action: str                      # created | updated | unchanged | restored | blocked | link_offer | filtered
    ip: str | None
    network: str | None
    entry_id: int | None             # the existing entry (or the manual entry an offer points at)


class StreamPreviewMissingOut(TypedDict):
    entry_id: int
    key: str
    name: str


class StreamPreviewOut(TypedDict):
    stream_id: str
    stream_status: str
    item_count: int
    counts: StreamCountsOut
    items: list[StreamPreviewItemOut]
    missing: list[StreamPreviewMissingOut]


class StreamItemOut(TypedDict):
    key: str
    name: str
    ip: str | None
    mac: str | None
    network: str | None
    attributes: Any


class BlockOut(TypedDict):
    id: int
    stream_id: str
    key: str
    name: str | None
    ip: str | None
    blocked_at: str | None
    blocked_by: str | None


class UnblockOut(TypedDict):
    stream_id: str
    key: str
    unblocked: bool


class OfferOut(TypedDict):
    id: int
    stream_id: str
    key: str
    entry_id: int                    # the manual entry that would join the stream
    entry_name: str | None
    item: StreamItemOut
    created_at: str | None


class OfferAnswerOut(TypedDict):
    stream_id: str
    key: str
    answer: str                      # accepted | declined
    entry: EntryOut                  # the entry that now carries the key
