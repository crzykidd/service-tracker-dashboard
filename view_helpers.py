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
from models import SOURCE_MANUAL, SOURCE_NOTIFIER, Group

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
VALID_SOURCE_FILTERS = ("all", "notifier", "manual")

_STATUS_STATES = {
    "failing": (STATE_DEGRADED, STATE_DOWN),
    "healthy": (STATE_UP,),
    "unknown": (STATE_UNKNOWN, STATE_NONE),
}


def normalize_status_filter(value):
    """Query-string value -> one of VALID_STATUS_FILTERS (default 'all')."""
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if value in VALID_STATUS_FILTERS else "all"


def normalize_source_filter(value):
    value = value.strip().lower() if isinstance(value, str) else ""
    return value if value in VALID_SOURCE_FILTERS else "all"


def matches_status(entry, status):
    if status == "all":
        return True
    if status == "stale":
        return entry.source == SOURCE_NOTIFIER and entry.is_docker_status_stale
    return entry_health(entry).state in _STATUS_STATES[status]


def matches_source(entry, source):
    if source == "all":
        return True
    return entry.source == (SOURCE_MANUAL if source == "manual" else SOURCE_NOTIFIER)


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
