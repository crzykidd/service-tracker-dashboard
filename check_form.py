"""Health-check form handling for the Add and Edit pages (PRD 13.5).

Parses the "Health checks" form section into plain row dicts, validates it
(collecting every error so the operator sees them all), and applies it to a
`ServiceEntry`. Rows keep the operator's raw strings so a failed submit can
re-render with the input intact.

Form field names:
  checks_form                       marker; absent means "section not submitted"
  uc_<internal|external>_<field>    URL-check fields (enabled, mode, interval,
                                    timeout, verify)
  cc_row, cc_enabled, cc_interval   Container check (notifier entries on Edit)
  svc_row                           one per service-check row (the row key)
  svc_<key>_<field>                 id, name, type, target, mode, interval,
                                    timeout, verify, enabled
"""

import ipaddress
import re
from urllib.parse import urlsplit

from checker import split_host_port
from models import (
    CHECK_KIND_SERVICE,
    CHECK_MODE_STATUS,
    CHECK_MODES,
    CHECK_TYPE_HTTP,
    CHECK_TYPE_PING,
    CHECK_TYPE_TCP,
    CHECK_TYPES,
    HealthCheck,
    ensure_url_checks,
)

MIN_INTERVAL = 30
MAX_INTERVAL = 86400
MIN_TIMEOUT = 1
MAX_TIMEOUT = 60
MAX_SERVICE_CHECKS = 20
NAME_MAX = 100
TARGET_MAX = 255

URL_ROWS = (("internal", "Internal URL"), ("external", "External URL"))

_KEY_RE = re.compile(r"^[A-Za-z0-9_]{1,32}$")
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$")


def _row_from_check(check, key=None, label=None):
    return {
        "key": key,
        "label": label,
        "id": check.id,
        "name": check.name or "",
        "check_type": check.check_type,
        "target": check.target or "",
        "mode": check.mode,
        "interval": "" if check.interval_seconds is None else str(check.interval_seconds),
        "timeout": "" if check.timeout_seconds is None else str(check.timeout_seconds),
        "verify": check.verify_tls is not False,
        "enabled": bool(check.enabled),
    }


def _blank_url_row(which, label):
    return {
        "key": which, "label": label, "id": None, "name": label, "check_type": CHECK_TYPE_HTTP,
        "target": "", "mode": CHECK_MODE_STATUS, "interval": "", "timeout": "",
        "verify": True, "enabled": False,
    }


def default_rows():
    """Rows for a page with nothing saved yet (Add)."""
    return [_blank_url_row(which, label) for which, label in URL_ROWS], []


def rows_from_entry(entry):
    """Rows reflecting what is saved on `entry`."""
    url_rows = []
    for which, label in URL_ROWS:
        check = entry.url_check(which)
        url_rows.append(_row_from_check(check, which, label) if check else _blank_url_row(which, label))
    svc_rows = [_row_from_check(c, key=f"id{c.id}") for c in entry.service_checks]
    return url_rows, svc_rows


def container_row_from_entry(entry):
    """The Container check's form row, or None when the entry has none
    (manual entries)."""
    check = entry.container_check
    if check is None:
        return None
    return {
        "id": check.id,
        "enabled": bool(check.enabled),
        "interval": "" if check.interval_seconds is None else str(check.interval_seconds),
    }


def _parse_int(raw, low, high, label, unit_hint, errors, who):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        value = None
    if value is None or not low <= value <= high:
        errors.append(f"{who}: {label} must be a whole number of seconds from {low} to {high}{unit_hint}.")
        return None
    return value


def validate_target(check_type, target):
    """Error string for an invalid service-check target, else None."""
    if not target:
        return "target is required"
    if len(target) > TARGET_MAX:
        return f"target is limited to {TARGET_MAX} characters"
    if check_type == CHECK_TYPE_HTTP:
        parts = urlsplit(target)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return "an HTTP target must be a full http:// or https:// URL"
        try:
            if not parts.hostname:
                return "an HTTP target must be a full http:// or https:// URL"
            parts.port  # noqa: B018 - raises ValueError on a bad port
        except ValueError:
            return "the port in the URL is not valid"
    elif check_type == CHECK_TYPE_TCP:
        try:
            split_host_port(target)
        except ValueError:
            return "a TCP target must be host:port with a port from 1 to 65535"
    elif check_type == CHECK_TYPE_PING:
        try:
            ipaddress.ip_address(target.strip("[]"))
        except ValueError:
            if not _HOSTNAME_RE.match(target):
                return "a Ping target must be a hostname or IP address, with no port or path"
    return None


def _parse_common(form, prefix, row, errors, who):
    """Fill the fields shared by URL rows and service rows."""
    row["enabled"] = form.get(f"{prefix}enabled") is not None
    mode = (form.get(f"{prefix}mode") or CHECK_MODE_STATUS).strip()
    if mode not in CHECK_MODES:
        errors.append(f"{who}: mode must be Status or Body.")
        mode = CHECK_MODE_STATUS
    row["mode"] = mode
    row["verify"] = form.get(f"{prefix}verify") is not None
    row["interval"] = (form.get(f"{prefix}interval") or "").strip()
    row["timeout"] = (form.get(f"{prefix}timeout") or "").strip()
    row["interval_value"] = _parse_int(row["interval"], MIN_INTERVAL, MAX_INTERVAL, "interval", "", errors, who)
    row["timeout_value"] = _parse_int(row["timeout"], MIN_TIMEOUT, MAX_TIMEOUT, "timeout", "", errors, who)


def parse_form(form, existing_service_ids=()):
    """Parse the section from `form`.

    Returns (url_rows, svc_rows, errors). Each row is a dict of the raw
    strings plus parsed `interval_value` / `timeout_value`. `errors` is a
    list of messages (empty when valid).
    """
    errors = []
    url_rows = []
    for which, label in URL_ROWS:
        row = _blank_url_row(which, label)
        _parse_common(form, f"uc_{which}_", row, errors, label)
        url_rows.append(row)

    svc_rows = []
    seen = set()
    keys = form.getlist("svc_row")
    if len(keys) > MAX_SERVICE_CHECKS:
        errors.append(f"A service can have at most {MAX_SERVICE_CHECKS} service checks.")
        keys = keys[:MAX_SERVICE_CHECKS]
    for index, key in enumerate(keys, start=1):
        if not _KEY_RE.match(key) or key in seen:
            continue
        seen.add(key)
        prefix = f"svc_{key}_"
        row = {"key": key, "label": None}
        raw_id = (form.get(f"{prefix}id") or "").strip()
        row["id"] = int(raw_id) if raw_id.isdigit() else None
        name = (form.get(f"{prefix}name") or "").strip()
        row["name"] = name
        who = f"Service check {index}" + (f" ({name})" if name else "")
        check_type = (form.get(f"{prefix}type") or CHECK_TYPE_HTTP).strip()
        if check_type not in CHECK_TYPES:
            errors.append(f"{who}: type must be HTTP/HTTPS, TCP or Ping.")
            check_type = CHECK_TYPE_HTTP
        row["check_type"] = check_type
        target = (form.get(f"{prefix}target") or "").strip()
        row["target"] = target
        if len(name) > NAME_MAX:
            errors.append(f"{who}: name is limited to {NAME_MAX} characters.")
        problem = validate_target(check_type, target)
        if problem:
            errors.append(f"{who}: {problem}.")
        _parse_common(form, prefix, row, errors, who)
        if raw_id and row["id"] not in existing_service_ids:
            errors.append(f"{who}: this check no longer exists (it may have been removed in another window). Reload the page.")
        svc_rows.append(row)
    return url_rows, svc_rows, errors


def parse_container(form):
    """Parse the Container row. Returns (row, errors); row is None when the
    form did not carry it (a page loaded before the row existed)."""
    if form.get("cc_row") is None:
        return None, []
    errors = []
    row = {"id": None, "enabled": form.get("cc_enabled") is not None}
    row["interval"] = (form.get("cc_interval") or "").strip()
    row["interval_value"] = _parse_int(
        row["interval"], MIN_INTERVAL, MAX_INTERVAL, "interval", "", errors, "Container check")
    return row, errors


def apply_container(entry, row):
    """Write a validated Container row onto `entry` (caller commits)."""
    check = entry.container_check
    if check is None or row is None:
        return
    before = (check.interval_seconds, check.enabled)
    check.interval_seconds = row["interval_value"]
    check.enabled = row["enabled"]
    if (check.interval_seconds, check.enabled) != before:
        check.last_checked_at = None


def _signature(check):
    return (check.check_type, check.target, check.mode, check.interval_seconds,
            check.timeout_seconds, check.verify_tls, check.enabled)


def _assign(check, row):
    is_http = row["check_type"] == CHECK_TYPE_HTTP
    check.check_type = row["check_type"]
    check.mode = row["mode"] if is_http else CHECK_MODE_STATUS
    check.interval_seconds = row["interval_value"]
    check.timeout_seconds = row["timeout_value"]
    check.verify_tls = row["verify"] if is_http else True
    check.enabled = row["enabled"]


def apply_rows(entry, url_rows, svc_rows):
    """Write validated rows onto `entry` (caller commits).

    URL rows update the two URL-kind checks (created if missing). Service
    rows with an id update that check; rows without one are created; saved
    service checks missing from the submission are removed (results
    cascade). A check whose settings changed is made due at the next
    scheduler tick (`last_checked_at` cleared).
    """
    ensure_url_checks(entry)
    for row in url_rows:
        check = entry.url_check(row["key"])
        before = _signature(check)
        _assign(check, row)
        if _signature(check) != before:
            check.last_checked_at = None

    existing = {c.id: c for c in entry.service_checks}
    kept = set()
    for row in svc_rows:
        check = existing.get(row["id"]) if row["id"] is not None else None
        if check is None:
            check = HealthCheck(kind=CHECK_KIND_SERVICE, consecutive_failures=0)
            entry.checks.append(check)
            before = None
        else:
            kept.add(check.id)
            before = _signature(check)
        check.name = row["name"] or row["target"][:NAME_MAX]
        check.target = row["target"]
        _assign(check, row)
        if before is None or _signature(check) != before:
            check.last_checked_at = None
    for check_id, check in existing.items():
        if check_id not in kept:
            entry.checks.remove(check)
