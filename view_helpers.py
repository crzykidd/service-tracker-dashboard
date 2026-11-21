"""Grouping/sorting helper for the dashboard views.

Resolves D2: the three dashboard handlers (`/`, `/tiled_dash`,
`/compact_dash`) each carried their own ~50 lines of
grouping/sorting logic with subtle key/sort drift between them.
This module is the single source of truth.

The helper is also where the v0.5.x view controls
(`group_by` axis selector, `show_urlless` filter) are interpreted,
so each route handler only has to read the query params and hand them
off.
"""

import re
from collections import defaultdict
from urllib.parse import urlparse

from flask import url_for

from health_state import (
    STATE_DEGRADED,
    STATE_DOWN,
    STATE_NONE,
    STATE_UNKNOWN,
    STATE_UP,
    entry_health,
)
from models import VALID_SOURCES, Group

VALID_AXES = ("group", "stack", "host")
DEFAULT_AXIS = "group"
DEFAULT_SORT_IN_GROUP = "priority"

# Bucket labels used when the keying attribute is null/empty.
UNGROUPED_LABEL = "Ungrouped"
UNSTACKED_LABEL = "Unstacked"
UNKNOWN_HOST_LABEL = "Unknown host"


def normalize_axis(value, logger=None):
    if value in VALID_AXES:
        return value
    if value is not None and logger is not None:
        logger.debug("Unknown group_by axis %r — falling back to %r", value, DEFAULT_AXIS)
    return DEFAULT_AXIS


def normalize_show_urlless(value):
    """Coerce a query-string value into a bool. Default True."""
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    return str(value).strip().lower() not in {"false", "0", "no", "off"}


VALID_STATUS_FILTERS = ("all", "failing", "healthy", "unknown", "stale")
VALID_SOURCE_FILTERS = ("all", *VALID_SOURCES)

_STATUS_STATES = {
    "failing": (STATE_DEGRADED, STATE_DOWN),
    "healthy": (STATE_UP,),
    "unknown": (STATE_UNKNOWN, STATE_NONE),
}


def normalize_status_filter(value):
    """Query-string value -> one of VALID_STATUS_FILTERS (default 'all')."""
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if value in VALID_STATUS_FILTERS else "all"


STREAM_FILTER_PREFIX = "stream:"
_STREAM_FILTER_RE = re.compile(r"^stream:[a-z0-9][a-z0-9_-]{0,62}$")


def normalize_source_filter(value):
    """`all`, a source, or `stream:<stream_id>` for one inventory stream."""
    value = value.strip().lower() if isinstance(value, str) else ""
    if value in VALID_SOURCE_FILTERS or _STREAM_FILTER_RE.match(value):
        return value
    return "all"


_TRUE_VALUES = {"1", "true", "yes", "on"}


def normalize_updates_filter(value):
    """Query-string value -> bool: only an explicit true value turns the Updates filter on."""
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in _TRUE_VALUES


def matches_updates(entry):
    """A plain predicate on the stored state column. The caller drops the filter while the
    check is switched off (the stored state outlives the switch), so no overlay is needed here."""
    return entry.image_update_state == "update"


def matches_status(entry, status):
    if status == "all":
        return True
    if status == "stale":
        return entry.is_docker and entry.is_docker_status_stale
    return entry_health(entry).state in _STATUS_STATES[status]


def matches_source(entry, source):
    if source == "all":
        return True
    if source.startswith(STREAM_FILTER_PREFIX):
        return (entry.source == "stream" and entry.stream is not None
                and entry.stream.stream_id == source[len(STREAM_FILTER_PREFIX):])
    return entry.source == source


def health_counts(services, show_urlless=True, source="all"):
    """Total / Passing / Failing for the filter-bar chips.

    Covers the entries left after the Source and Show URL-less filters,
    ignoring the Status filter, so each number equals what its chip shows
    when clicked. One rollup per entry. Unknown and Not monitored entries
    count toward Total only.
    """
    source = normalize_source_filter(source)
    total = passing = failing = 0
    for e in services:
        if not show_urlless and not entry_has_url(e):
            continue
        if not matches_source(e, source):
            continue
        total += 1
        state = entry_health(e).state
        if state in _STATUS_STATES["healthy"]:
            passing += 1
        elif state in _STATUS_STATES["failing"]:
            failing += 1
    return {"total": total, "passing": passing, "failing": failing}


def updates_count(services, show_urlless=True, source="all", status="all"):
    """The N of "Updates available (N)": entries with a newer image among those the other
    filters (Source, Status, Show URL-less) leave, so it equals what the toggle shows."""
    source = normalize_source_filter(source)
    status = normalize_status_filter(status)
    return sum(
        1 for e in services
        if matches_updates(e)
        and (show_urlless or entry_has_url(e))
        and matches_source(e, source) and matches_status(e, status))


def entry_has_url(entry):
    return bool((entry.internalurl or "").strip()) or bool((entry.externalurl or "").strip())


def _within_bucket_sort_key(entry, sort_in_group):
    name = (entry.container_name or "").lower()
    if sort_in_group == "alphabetical":
        return (0, name)
    priority = entry.sort_priority if entry.sort_priority is not None else 9999
    return (priority, name)


def group_and_sort_services(
    services,
    axis=DEFAULT_AXIS,
    show_urlless=True,
    sort_in_group=DEFAULT_SORT_IN_GROUP,
    status="all",
    source="all",
    updates=False,
):
    """Group and sort services for rendering.

    Returns a list of `(bucket_label, entries)` tuples in render order.
    `bucket_label` is the string the template displays; `entries` are
    the services in that bucket, sorted per `sort_in_group`.

    For `axis='group'` the keying is `group_id` (canonical), so two
    distinct Group rows that happen to share a display name yield two
    distinct buckets. For `axis='stack'` and `axis='host'` the bucket
    key is the string value itself; null/empty values are collected
    into a single sentinel-labeled bucket rendered last.
    """
    axis = normalize_axis(axis)

    if not show_urlless:
        services = [e for e in services if entry_has_url(e)]

    status = normalize_status_filter(status)
    source = normalize_source_filter(source)
    if status != "all" or source != "all":
        services = [e for e in services if matches_source(e, source) and matches_status(e, status)]
    if updates:
        services = [e for e in services if matches_updates(e)]

    buckets = defaultdict(list)
    for entry in services:
        if axis == "group":
            key = entry.group_id  # may be None
        elif axis == "stack":
            key = (entry.stack_name or "").strip() or None
        else:  # host
            key = (entry.host or "").strip() or None
        buckets[key].append(entry)

    for key in buckets:
        buckets[key].sort(key=lambda e: _within_bucket_sort_key(e, sort_in_group))

    if axis == "group":
        return _order_group_buckets(buckets)
    null_label = UNSTACKED_LABEL if axis == "stack" else UNKNOWN_HOST_LABEL
    return _order_string_buckets(buckets, null_label=null_label)


def _order_group_buckets(buckets):
    group_ids = [k for k in buckets if k is not None]
    groups_by_id = {}
    if group_ids:
        groups_by_id = {g.id: g for g in Group.query.filter(Group.id.in_(group_ids)).all()}

    def sort_key(group_id):
        g = groups_by_id.get(group_id)
        priority = g.group_sort_priority if g and g.group_sort_priority is not None else 9999
        name = g.group_name.lower() if g else "zzz"
        return (priority, name)

    ordered = sorted((k for k in buckets if k is not None), key=sort_key)
    result = []
    for gid in ordered:
        g = groups_by_id.get(gid)
        label = g.group_name if g else "Unknown Group"
        result.append((label, buckets[gid]))
    if None in buckets:
        result.append((UNGROUPED_LABEL, buckets[None]))
    return result


def _order_string_buckets(buckets, null_label):
    known = sorted((k for k in buckets if k is not None), key=lambda s: s.lower())
    result = [(k, buckets[k]) for k in known]
    if None in buckets:
        result.append((null_label, buckets[None]))
    return result


def safe_redirect_target(target, fallback=None):
    """Return `target` only if it is a same-site relative path, else `fallback`.

    Allowed: no scheme, no netloc, starts with a single '/', and not '//' or
    '/\\' (browsers treat both as protocol-relative). `fallback` defaults to
    the dashboard.
    """
    if fallback is None:
        fallback = url_for("dashboard.dashboard")
    if not isinstance(target, str) or not target:
        return fallback
    if "\\" in target or any(ord(c) < 32 for c in target):
        return fallback
    # Shape follows CodeQL's documented py/url-redirection sanitizer
    # (backslash strip + no netloc + no scheme, with the safe value returned
    # inside the guarded branch) so the analyzer recognises it as a barrier.
    # The backslash case already returned above; the replace is for CodeQL.
    target = target.replace("\\", "")
    if (
        not urlparse(target).netloc
        and not urlparse(target).scheme
        and target.startswith("/")
        and not target.startswith("//")
    ):
        return target
    return fallback


def duplicate_name_ids(entries):
    """Ids of active entries whose name is shared by another active entry on a
    different host. Names compare case-insensitively, trimmed. Soft-deleted
    entries are ignored and entries with no host are never marked (and never
    count as "a different host"). Pass ALL active entries, not a filtered
    subset, so a filter can't make a duplicate look unique."""
    hosts_by_name = defaultdict(set)
    keyed = []
    for e in entries:
        host = (e.host or "").strip()
        if getattr(e, "deleted_at", None) is not None or not host:
            continue
        name = (e.container_name or "").strip().lower()
        hosts_by_name[name].add(host)
        keyed.append((e.id, name))
    return {i for i, name in keyed if len(hosts_by_name[name]) > 1}


def host_label_ids(entries, mode):
    """Ids that should show their host, per the `tile_show_host` mode:
    `never` -> none, `always` -> every active entry with a host,
    `duplicates` (default for any other value) -> `duplicate_name_ids`."""
    if mode == "never":
        return set()
    if mode == "always":
        return {
            e.id for e in entries
            if (e.host or "").strip() and getattr(e, "deleted_at", None) is None
        }
    return duplicate_name_ids(entries)


def exposure_layers(exposures):
    """Collapse ServiceExposure rows into one summary per layer, first-seen order.

    Each item: layer, count (raw rows), tls / labeled / auth (true if ANY row),
    routes (de-duplicated by hostname+path; dicts: route, tls, auth) and title
    (hover text: "<layer> \u2014 N routes" with the raw row count, then one
    distinct route per line).
    """
    layers = {}
    for ex in exposures or []:
        item = layers.setdefault(ex.layer, {
            "layer": ex.layer, "count": 0, "tls": False, "labeled": False,
            "auth": False, "routes": [], "_seen": {}})
        item["count"] += 1
        auth = ex.auth if ex.auth and ex.auth not in ("none", "") else None
        tls = bool(ex.tls)
        item["tls"] = item["tls"] or tls
        item["labeled"] = item["labeled"] or bool(ex.hostname)
        item["auth"] = item["auth"] or bool(auth)
        route = f"{ex.hostname or ''}{ex.path_prefix or ''}"
        # De-duplicate on the route alone (web + websecure routers share a
        # hostname); TLS / auth aggregate as "any" across the duplicates.
        if route in item["_seen"]:
            existing = item["_seen"][route]
            existing["tls"] = existing["tls"] or tls
            existing["auth"] = existing["auth"] or auth
        else:
            entry = {"route": route, "tls": tls, "auth": auth}
            item["_seen"][route] = entry
            item["routes"].append(entry)
    out = []
    for item in layers.values():
        item.pop("_seen")
        n = item["count"]
        lines = [f"{item['layer']} \u2014 {n} route{'s' if n != 1 else ''}"]
        for r in item["routes"]:
            if not r["route"]:
                continue
            line = r["route"]
            if r["tls"]:
                line += " (TLS)"
            if r["auth"]:
                line += f" (auth: {r['auth']})"
            lines.append(line)
        item["title"] = "\n".join(lines)
        out.append(item)
    return out
