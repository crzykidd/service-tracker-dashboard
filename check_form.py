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
    CHECK_KIND_CONTAINER,
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


def _coerce_interval(raw, low, high, label, errors, field):
    """Whole seconds from `raw` (int, numeric string, blank or None).

    Blank/None means "use the global setting" (returns None). Anything else
    outside `low`..`high` appends a `{field, message}` error and returns None.
    Booleans and floats are rejected so JSON `true` or `1.5` is not coerced.
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    value = None
    if isinstance(raw, str):
        try:
            value = int(raw.strip())
        except ValueError:
            value = None
    elif isinstance(raw, int) and not isinstance(raw, bool):
        value = raw
    if value is None or not low <= value <= high:
        errors.append({
            "field": field,
            "message": f"{label} must be a whole number of seconds from {low} to {high}",
        })
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


# --- validation over plain dicts (shared by the form parser and the API) ------
#
# Each validator takes a dict and returns `(values, errors)`. `errors` is a list
# of `{"field": str, "message": str}` (message has no trailing period and no
# check label; callers add context). `values` is normalized and always
# complete, with safe fallbacks for invalid fields, so callers that collect
# every error can still render. The form passes raw strings, the API typed JSON.


def validate_url_check_settings(d):
    """Settings shared by URL checks and service checks.

    Reads `enabled`, `mode`, `verify`, `interval`, `timeout`. Returns values
    `{enabled, mode, verify, interval_value, timeout_value}`.
    """
    errors = []
    mode = d.get("mode")
    mode = CHECK_MODE_STATUS if mode is None or mode == "" else mode
    if isinstance(mode, str):
        mode = mode.strip()
    if mode not in CHECK_MODES:
        errors.append({"field": "mode", "message": "mode must be Status or Body"})
        mode = CHECK_MODE_STATUS
    values = {
        "enabled": bool(d.get("enabled")),
        "mode": mode,
        "verify": bool(d.get("verify", True)),
        "interval_value": _coerce_interval(
            d.get("interval"), MIN_INTERVAL, MAX_INTERVAL, "interval", errors, "interval"),
        "timeout_value": _coerce_interval(
            d.get("timeout"), MIN_TIMEOUT, MAX_TIMEOUT, "timeout", errors, "timeout"),
    }
    return values, errors


def validate_service_check(d):
    """A service check: `name`, `check_type`, `target` plus the shared settings.

    Returns values `{name, check_type, target, enabled, mode, verify,
    interval_value, timeout_value}`.
    """
    errors = []
    check_type = d.get("check_type")
    check_type = CHECK_TYPE_HTTP if check_type is None or check_type == "" else check_type
    if isinstance(check_type, str):
        check_type = check_type.strip()
    if check_type not in CHECK_TYPES:
        errors.append({"field": "check_type", "message": "type must be HTTP/HTTPS, TCP or Ping"})
        check_type = CHECK_TYPE_HTTP
    name = d.get("name")
    name = name.strip() if isinstance(name, str) else ""
    if len(name) > NAME_MAX:
        errors.append({"field": "name", "message": f"name is limited to {NAME_MAX} characters"})
    target = d.get("target")
    target = target.strip() if isinstance(target, str) else ""
    problem = validate_target(check_type, target)
    if problem:
        errors.append({"field": "target", "message": problem})
    common, common_errors = validate_url_check_settings(d)
    values = {"name": name, "check_type": check_type, "target": target, **common}
    return values, errors + common_errors


def validate_container_check(d):
    """The Container check: `enabled` and `interval`.

    Returns values `{enabled, interval_value}`.
    """
    errors = []
    values = {
        "enabled": bool(d.get("enabled")),
        "interval_value": _coerce_interval(
            d.get("interval"), MIN_INTERVAL, MAX_INTERVAL, "interval", errors, "interval"),
    }
    return values, errors


def _with_who(errors, who):
    """Form-style messages: `Label: message.`"""
    return [f"{who}: {e['message']}." for e in errors]


def _parse_common(form, prefix, row, errors, who):
    """Fill the fields shared by URL rows and service rows."""
    raw = {
        "enabled": form.get(f"{prefix}enabled") is not None,
        "mode": (form.get(f"{prefix}mode") or CHECK_MODE_STATUS).strip(),
        "verify": form.get(f"{prefix}verify") is not None,
        "interval": (form.get(f"{prefix}interval") or "").strip(),
        "timeout": (form.get(f"{prefix}timeout") or "").strip(),
    }
    values, problems = validate_url_check_settings(raw)
    errors.extend(_with_who(problems, who))
    row["enabled"] = raw["enabled"]
    row["mode"] = values["mode"]
    row["verify"] = raw["verify"]
    row["interval"], row["timeout"] = raw["interval"], raw["timeout"]
    row["interval_value"] = values["interval_value"]
    row["timeout_value"] = values["timeout_value"]


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
        who = f"Service check {index}" + (f" ({name})" if name else "")
        raw = {
            "name": name,
            "check_type": (form.get(f"{prefix}type") or CHECK_TYPE_HTTP).strip(),
            "target": (form.get(f"{prefix}target") or "").strip(),
        }
        values, problems = validate_service_check(raw)
        errors.extend(_with_who(problems, who))
        row["name"] = name
        row["check_type"] = values["check_type"]
        row["target"] = raw["target"]
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
    raw = {"enabled": form.get("cc_enabled") is not None,
           "interval": (form.get("cc_interval") or "").strip()}
    values, problems = validate_container_check(raw)
    row = {"id": None, "enabled": raw["enabled"], "interval": raw["interval"],
           "interval_value": values["interval_value"]}
    return row, _with_who(problems, "Container check")


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
    check_type = row.get("check_type", check.check_type)
    is_http = check_type == CHECK_TYPE_HTTP
    check.check_type = check_type
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


def apply_check_values(check, values):
    """Write validated `values` (from the `validate_*` functions) onto one
    existing check and make it due at the next tick if its settings changed.
    Used by the management API; the form path goes through `apply_rows`.

    URL checks and service checks take `values` from `validate_url_check_settings`
    / `validate_service_check`; the container check from `validate_container_check`
    (only `enabled` and `interval_value`).
    """
    before = _signature(check)
    if check.kind == CHECK_KIND_CONTAINER:
        check.interval_seconds = values["interval_value"]
        check.enabled = values["enabled"]
    else:
        if check.kind == CHECK_KIND_SERVICE:
            check.name = values["name"] or values["target"][:NAME_MAX]
            check.target = values["target"]
        _assign(check, values)
    if _signature(check) != before:
        check.last_checked_at = None


def new_service_check(values):
    """A not-yet-attached service `HealthCheck` from validated values."""
    check = HealthCheck(kind=CHECK_KIND_SERVICE, consecutive_failures=0)
    check.name = values["name"] or values["target"][:NAME_MAX]
    check.target = values["target"]
    _assign(check, values)
    return check
