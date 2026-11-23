"""Ports in use (PRD 25): container ports across all hosts, and where they clash.

Pure: no Flask, no DB queries. It takes a list of entries (anything with the
`ServiceEntry` attributes used below) and returns plain data, so the Ports page and
`GET /api/v1/ports` share exactly one implementation.

The data is pure observation from the notifier (`exposed_ports`, `published_ports`);
nothing here edits it.
"""

import ipaddress
from urllib.parse import urlsplit

KINDS = ("all", "published", "host_network", "direct", "exposed")
# Row kinds in display order: published, host network, direct, not published.
KIND_ORDER = {"published": 0, "host_network": 1, "direct": 2, "exposed": 3}
SORTS = ("name", "port", "host", "protocol")
DEFAULT_SORT = "name"
# Sorts that make sense inside one host's section (the host is the same for every row).
GROUPED_SORTS = ("name", "port", "protocol")
# Old name of `port`; kept so saved browser states and old links keep working.
SORT_ALIASES = {"host_port": "port"}

# A container reported with one of these is running (the dashboards treat `start` as
# running too). Any other set status is stopped: Docker clears its published ports.
RUNNING_STATUSES = ("running", "start")

# Network drivers where the container has its own LAN address (Docker ignores published ports).
DIRECT_DRIVERS = ("macvlan", "ipvlan")
# The network Docker reserves for `network_mode: host`.
HOST_NETWORK = "host"

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


def _networks(entry):
    """`(host_network, [(name, driver, [ips])])`: whether the entry is on the host network
    (the name `host` counts even without a driver) and its macvlan/ipvlan networks that
    have an address. Malformed items are skipped; no `networks` is the old behavior."""
    host_network = False
    direct = []
    items = getattr(entry, "networks", None)
    for net in items if isinstance(items, list) else []:
        if not isinstance(net, dict):
            continue
        name = net.get("name") if isinstance(net.get("name"), str) else ""
        driver = net.get("driver").strip().lower() if isinstance(net.get("driver"), str) else ""
        if name == HOST_NETWORK or driver == HOST_NETWORK:
            host_network = True
        elif driver in DIRECT_DRIVERS:
            ips = [v.strip() for v in (net.get("ip_address"), net.get("ipv6_address"))
                   if isinstance(v, str) and v.strip()]
            if ips:
                direct.append((name, driver, ips))
    return host_network, direct


def _same_ip(a, b):
    try:
        return ipaddress.ip_address(a) == ipaddress.ip_address(b)
    except ValueError:
        return False


def _url_ports(entry, ips):
    """`(port, "tcp")` for each internal/external URL whose host is one of `ips` (the
    container's own address). A hostname never matches: only the address proves the URL
    points at this container. No port in the URL means the scheme's default."""
    out = []
    for url in (getattr(entry, "internalurl", None), getattr(entry, "externalurl", None)):
        if not isinstance(url, str) or not url.strip():
            continue
        try:
            parts = urlsplit(url.strip())
            host = parts.hostname
            port = parts.port
        except ValueError:
            continue
        if not host or not any(_same_ip(host, ip) for ip in ips):
            continue
        if port is None:
            port = {"http": 80, "https": 443}.get(parts.scheme.lower())
        port = _port(port)
        if port is not None and (port, "tcp") not in out:
            out.append((port, "tcp"))
    return out


def _row(entry, kind, host_ips, host_port, container_port, protocol, network=None, driver=None,
         port_source="declared", ports_unknown=False):
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
        "network": network,
        "driver": driver,
        "port_source": port_source,
        "ports_unknown": ports_unknown,
        "conflict": False,
        "conflict_with": [],
    }


def _ips_overlap(a, b):
    """Any wildcard overlaps everything (a simplification: no per-family check); two
    specific addresses overlap only when they are the same."""
    if any(ip in WILDCARD_IPS for ip in a) or any(ip in WILDCARD_IPS for ip in b):
        return True
    return bool(set(a) & set(b))


def _mark_group(group, overlap):
    for row in group:
        others = [o for o in group
                  if o["entry_id"] != row["entry_id"] and overlap(row["host_ips"], o["host_ips"])]
        if others:
            row["conflict"] = True
            row["conflict_with"] = sorted(set(row["conflict_with"]) | {o["entry_id"] for o in others})


def _mark_conflicts(rows):
    """Published and host-network rows share the host's ports. Direct rows live on their
    own LAN address: they clash only with another direct row on the same address."""
    host_groups = {}
    direct_groups = {}
    for row in rows:
        if row["ports_unknown"]:
            continue
        if row["kind"] in ("published", "host_network") and row["host"]:
            host_groups.setdefault((row["host"], row["protocol"], row["host_port"]), []).append(row)
        elif row["kind"] == "direct":
            direct_groups.setdefault((row["protocol"], row["host_port"]), []).append(row)
    for group in host_groups.values():
        _mark_group(group, _ips_overlap)
    for group in direct_groups.values():
        _mark_group(group, lambda a, b: bool(set(a) & set(b)))


def _order(row):
    return (row["host"] or "", KIND_ORDER[row["kind"]], row["ports_unknown"],
            row["host_port"] if row["host_port"] is not None else 0,
            row["container_port"] or 0, row["protocol"] or "", row["name"] or "", row["entry_id"] or 0)


def build_rows(entries):
    """One row per published binding (the `0.0.0.0` and `::` pair of one port is one row
    with both addresses), one per exposed port of a host-network entry (bound on the host)
    or of a macvlan/ipvlan network (reachable at the container's own address), and one per
    remaining exposed-only port. Docker ignores published ports on the host network and on
    macvlan/ipvlan, so an entry attached only to those has no published rows. Conflicts
    are marked."""
    rows = []
    for entry in entries:
        if getattr(entry, "deleted_at", None) is not None or not _is_running(entry):
            continue
        host_network, direct = _networks(entry)
        published = _published(entry)
        exposed = _exposed(entry)
        # Docker ignores published ports on the host network and on macvlan/ipvlan; they
        # still apply when the entry is also on an ordinary (bridge, unknown) network.
        items = getattr(entry, "networks", None)
        ordinary = [n for n in (items if isinstance(items, list) else []) if isinstance(n, dict)
                    and n.get("name") != HOST_NETWORK
                    and str(n.get("driver") or "").strip().lower() not in (*DIRECT_DRIVERS, HOST_NETWORK)]
        only_unpublishing = bool(host_network or direct) and not ordinary
        if only_unpublishing:
            published = []
        bound = {}
        for host_port, container_port, protocol, ip in published:
            ips = bound.setdefault((host_port, container_port, protocol), [])
            if ip not in ips:
                ips.append(ip)
        for (host_port, container_port, protocol), ips in bound.items():
            rows.append(_row(entry, "published", ips, host_port, container_port, protocol))
        published_keys = {(c, p) for (_, c, p) in bound}
        # Ports the entry listens on: declared by the image, plus the container side of
        # any binding Docker ignored.
        listening = []
        for container_port, protocol in exposed + [(c, p) for (_, c, p, _) in _published(entry)]:
            if (container_port, protocol) not in listening:
                listening.append((container_port, protocol))
        if host_network:
            for container_port, protocol in listening:
                rows.append(_row(entry, "host_network", ["0.0.0.0"], container_port, container_port, protocol))
            if not listening:
                rows.append(_row(entry, "host_network", ["0.0.0.0"], None, None, None, ports_unknown=True))
        for name, driver, ips in direct:
            from_url = [p for p in _url_ports(entry, ips) if p not in listening]
            for container_port, protocol in listening + from_url:
                rows.append(_row(entry, "direct", list(ips), container_port, container_port, protocol,
                                 network=name, driver=driver,
                                 port_source="declared" if (container_port, protocol) in listening else "url"))
            if not listening and not from_url:
                rows.append(_row(entry, "direct", list(ips), None, None, None, network=name, driver=driver,
                                 ports_unknown=True))
        seen = set()
        for container_port, protocol in exposed:
            key = (container_port, protocol)
            if key in published_keys or key in seen:
                continue
            seen.add(key)
            if host_network or direct:
                continue
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
        "host_network": sum(1 for r in rows if r["kind"] == "host_network"),
        "direct": sum(1 for r in rows if r["kind"] == "direct"),
        "exposed": sum(1 for r in rows if r["kind"] == "exposed"),
        "conflicts": sum(1 for r in rows if r["conflict"]),
    }


def filter_rows(rows, kind="all", host=None, q=None, conflicts_only=False):
    """Filter rows. `q` is a case-insensitive substring of the name, container name,
    stack or the port numbers."""
    needle = (q or "").strip().lower()
    out = []
    for r in rows:
        if kind != "all" and kind in KIND_ORDER and r["kind"] != kind:
            continue
        if host and r["host"] != host:
            continue
        if conflicts_only and not r["conflict"]:
            continue
        if needle:
            hay = [r["name"], r["container_name"], r["stack_name"]]
            if r["ports_unknown"]:
                hay += [r["network"], *r["host_ips"]]
            else:
                hay += [str(r["container_port"]),
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
    """Every sort orders by state first (published, host network, direct, not published), then by the chosen key,
    then by a stable tie-break (host, port, protocol, entry id)."""
    primary = {
        "name": lambda r: (r["name"] or "").lower(),
        "port": lambda r: (r["host_port"] if r["kind"] != "exposed" and r["host_port"] is not None
                           else r["container_port"]) or 0,
        "host": lambda r: (r["host"] or "").lower(),
        "protocol": lambda r: r["protocol"] or "",
    }[sort]

    def key(r):
        return (KIND_ORDER[r["kind"]], r["ports_unknown"], primary(r), (r["host"] or "").lower(),
                r["host_port"] if r["host_port"] is not None else 0, r["container_port"] or 0,
                r["protocol"] or "", r["entry_id"] or 0)
    return key


def sort_rows(rows, sort=DEFAULT_SORT):
    """Flat-table order: published, host network, direct, then not-published rows, each sorted by `sort`."""
    return sorted(rows, key=_sort_key(normalize_sort(sort)))


def group_by_host(rows, sort=DEFAULT_SORT):
    """`[(host, rows)]`, hosts alphabetical, each section ordered like the flat table
    (`host` is meaningless inside one host, so it falls back to the default)."""
    key = _sort_key(normalize_sort(sort, GROUPED_SORTS))
    groups = {}
    for r in rows:
        groups.setdefault(r["host"] or "", []).append(r)
    return [(h, sorted(rs, key=key)) for h, rs in sorted(groups.items(), key=lambda kv: kv[0].lower())]
