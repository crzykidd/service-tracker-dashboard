"""Ports in use (PRD 25): container ports across all hosts, and where they clash.

Pure: no Flask, no DB queries. It takes a list of entries (anything with the
`ServiceEntry` attributes used below) and returns plain data, so the Ports page and
`GET /api/v1/ports` share exactly one implementation.

The data is pure observation from the notifier (`exposed_ports`, `published_ports`);
nothing here edits it.
"""

KINDS = ("all", "published", "exposed")
SORTS = ("name", "port", "host", "protocol")
DEFAULT_SORT = "name"
# Sorts that make sense inside one host's section (the host is the same for every row).
GROUPED_SORTS = ("name", "port", "protocol")
# Old name of `port`; kept so saved browser states and old links keep working.
SORT_ALIASES = {"host_port": "port"}

# A container reported with one of these is running (the dashboards treat `start` as
# running too). Any other set status is stopped: Docker clears its published ports.
RUNNING_STATUSES = ("running", "start")

# A published binding to one of these covers every address of the host.
WILDCARD_IPS = ("", "0.0.0.0", "::")


def _is_running(entry):
    status = entry.docker_status
    return not status or status.strip().lower() in RUNNING_STATUSES


def _port(value):
    """A port number from a JSON value, or None (bool and out of range are not ports)."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number < 65536 else None


def _protocol(value):
    return value.strip().lower() if isinstance(value, str) and value.strip() else "tcp"


def _published(entry):
    """`(host_port, container_port, protocol, host_ip)` for each well-formed binding."""
    out = []
    items = entry.published_ports
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        host_port = _port(item.get("host_port"))
        container_port = _port(item.get("container_port"))
        if host_port is None or container_port is None:
            continue
        ip = item.get("host_ip")
        out.append((host_port, container_port, _protocol(item.get("protocol")),
                    ip.strip() if isinstance(ip, str) else ""))
    return out


def _exposed(entry):
    """`(container_port, protocol)` for each well-formed exposed port ("5173/tcp")."""
    out = []
    items = entry.exposed_ports
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, str):
            continue
        number, _, proto = item.partition("/")
        port = _port(number.strip())
        if port is not None:
            out.append((port, _protocol(proto)))
    return out


def _row(entry, kind, host_ips, host_port, container_port, protocol):
    return {
        "entry_id": entry.id,
        "name": entry.container_name,
        "host": entry.host,
        "container_name": entry.container_name,
        "stack_name": entry.stack_name,
        "docker_status": entry.docker_status,
        "kind": kind,
        "host_ips": host_ips,
        "host_port": host_port,
        "container_port": container_port,
        "protocol": protocol,
        "conflict": False,
        "conflict_with": [],
    }


def _ips_overlap(a, b):
    """Any wildcard overlaps everything (a simplification: no per-family check); two
    specific addresses overlap only when they are the same."""
    if any(ip in WILDCARD_IPS for ip in a) or any(ip in WILDCARD_IPS for ip in b):
        return True
    return bool(set(a) & set(b))


def _mark_conflicts(rows):
    groups = {}
    for row in rows:
        if row["kind"] == "published" and row["host"]:
            groups.setdefault((row["host"], row["protocol"], row["host_port"]), []).append(row)
    for group in groups.values():
        for row in group:
            others = [o for o in group
                      if o["entry_id"] != row["entry_id"] and _ips_overlap(row["host_ips"], o["host_ips"])]
            if others:
                row["conflict"] = True
                row["conflict_with"] = sorted({o["entry_id"] for o in others})


def _order(row):
    return (row["host"] or "", row["kind"] != "published",
            row["host_port"] if row["host_port"] is not None else 0,
            row["container_port"], row["protocol"], row["name"] or "", row["entry_id"] or 0)


def build_rows(entries):
    """One row per published binding (the `0.0.0.0` and `::` pair of one port is one row
    with both addresses) and one per exposed-only port. Conflicts are marked."""
    rows = []
    for entry in entries:
        if getattr(entry, "deleted_at", None) is not None or not _is_running(entry):
            continue
        bound = {}
        for host_port, container_port, protocol, ip in _published(entry):
            ips = bound.setdefault((host_port, container_port, protocol), [])
            if ip not in ips:
                ips.append(ip)
        for (host_port, container_port, protocol), ips in bound.items():
            rows.append(_row(entry, "published", ips, host_port, container_port, protocol))
        published_keys = {(c, p) for (_, c, p) in bound}
        seen = set()
        for container_port, protocol in _exposed(entry):
            key = (container_port, protocol)
            if key in published_keys or key in seen:
                continue
            seen.add(key)
            rows.append(_row(entry, "exposed", [], None, container_port, protocol))
    _mark_conflicts(rows)
    rows.sort(key=_order)
    return rows


def summarize(rows):
    """Counts over `rows`. `conflicts` is the number of conflicting rows (each side of a
    clash counts), the same definition in the page and the API."""
    return {
        "hosts": len({r["host"] for r in rows if r["host"]}),
        "published": sum(1 for r in rows if r["kind"] == "published"),
        "exposed": sum(1 for r in rows if r["kind"] == "exposed"),
        "conflicts": sum(1 for r in rows if r["conflict"]),
    }


def filter_rows(rows, kind="all", host=None, q=None, conflicts_only=False):
    """Filter rows. `q` is a case-insensitive substring of the name, container name,
    stack or the port numbers."""
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        if kind in ("published", "exposed") and r["kind"] != kind:
            continue
        if host and r["host"] != host:
            continue
        if conflicts_only and not r["conflict"]:
            continue
        if needle:
            hay = [r["name"], r["container_name"], r["stack_name"], str(r["container_port"]),
                   str(r["host_port"]) if r["host_port"] is not None else "", r["protocol"],
                   f"{r['container_port']}/{r['protocol']}"]
            if not any(needle in (h or "").lower() for h in hay):
                continue
        out.append(r)
    return out


def normalize_kind(value):
    return value if value in KINDS else "all"


def normalize_sort(value, allowed=SORTS):
    """A known sort (the `host_port` alias maps to `port`), else the default. `allowed`
    narrows the choice (the grouped view has no `host` sort)."""
    value = SORT_ALIASES.get(value, value)
    return value if value in allowed else DEFAULT_SORT


def _sort_key(sort):
    """Every sort orders by state first (published, then exposed), then by the chosen key,
    then by a stable tie-break (host, port, protocol, entry id)."""
    primary = {
        "name": lambda r: (r["name"] or "").lower(),
        "port": lambda r: r["host_port"] if r["kind"] == "published" and r["host_port"] is not None
        else r["container_port"],
        "host": lambda r: (r["host"] or "").lower(),
        "protocol": lambda r: r["protocol"],
    }[sort]

    def key(r):
        return (r["kind"] != "published", primary(r), (r["host"] or "").lower(),
                r["host_port"] if r["host_port"] is not None else 0, r["container_port"],
                r["protocol"], r["entry_id"] or 0)
    return key


def sort_rows(rows, sort=DEFAULT_SORT):
    """Flat-table order: published rows first, then not-published, each sorted by `sort`."""
    return sorted(rows, key=_sort_key(normalize_sort(sort)))


def group_by_host(rows, sort=DEFAULT_SORT):
    """`[(host, rows)]`, hosts alphabetical, each section ordered like the flat table
    (`host` is meaningless inside one host, so it falls back to the default)."""
    key = _sort_key(normalize_sort(sort, GROUPED_SORTS))
    groups = {}
    for r in rows:
        groups.setdefault(r["host"] or "", []).append(r)
    return [(h, sorted(rs, key=key)) for h, rs in sorted(groups.items(), key=lambda kv: kv[0].lower())]
