#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp==1.30.0", "httpx==0.28.1"]
# ///
"""MCP server for the Service Tracker Dashboard management API (PRD 14.7, 15.7).

A small stdio server that lets Claude Code (or any MCP client) look after an STD
instance. It is a plain HTTP client of `/api/v1`: no database access, no imports
from the STD application, no business logic of its own. It runs on the
operator's machine and is NOT part of the Docker image.

Environment:
    STD_URL          base URL of the dashboard, e.g. http://std.lan:8815   (required)
    STD_API_KEY      an admin API key from Settings -> API keys             (required)
    STD_VERIFY_TLS   "false" to skip TLS verification (default true)
    STD_TIMEOUT      request timeout in seconds (default 15)

At startup it calls `GET /api/v1/whoami`. A `read` key registers only the read
tools; a `write` key registers all of them. whoami also returns the STD version,
which is compared with MCP_VERSION so Claude can say when this script needs updating.

Run it with `uv run std_mcp.py`: the dependencies are declared in the PEP 723 block
above (kept equal to mcp/requirements.in by a test), so no virtualenv is needed.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# httpx logs every request URL at INFO; keep the stdio server quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

# The release this script belongs to. `/release-prep` sets it with VERSION; a test
# keeps the two from drifting.
MCP_VERSION = "0.13.2"

API = "/api/v1"
DEFAULT_TIMEOUT = 15.0
# server_info re-checks the STD version with GET /api/v1/meta (public, no DB) on each call.
META_TIMEOUT = 3.0
SCRIPT_URL = "https://raw.githubusercontent.com/crzykidd/service-tracker-dashboard/v{version}/mcp/std_mcp.py"

# Fields the PATCH endpoints accept. Checked client-side so that a typo gives a
# readable error, not a round trip. The server stays the authority.
ENTRY_PATCH_FIELDS = {
    "name", "host", "description", "group", "internalurl", "externalurl",
    "icon", "image_repo_url", "sort_priority", "locked", "ha_publish",
    "image_update_policy", "image_update_scope", "image_tag_pattern",
}
CHECK_PATCH_FIELDS = {
    "enabled", "name", "check_type", "target", "mode", "interval_seconds",
    "timeout_seconds", "verify_tls",
    "dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer",
    "cert_min_days", "ha_exclude",
}


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


class StdClient:
    """Thin synchronous wrapper over httpx for the management API."""

    def __init__(self, base_url: str, api_key: str, verify_tls: bool = True,
                 timeout: float = DEFAULT_TIMEOUT, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url + API,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            verify=verify_tls,
            timeout=timeout,
            transport=transport,
        )

    def request(self, method: str, path: str, params: dict | None = None, json: Any = None) -> Any:
        clean = {k: (str(v).lower() if isinstance(v, bool) else v)
                 for k, v in (params or {}).items() if v is not None}
        try:
            resp = self._http.request(method, path, params=clean or None, json=json)
        except httpx.HTTPError as exc:
            raise ToolError(f"Cannot reach STD at {self.base_url}: {exc.__class__.__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise ToolError(_format_error(resp))
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            raise ToolError(f"STD returned a non-JSON answer (HTTP {resp.status_code}).") from None

    def meta(self, timeout: float = META_TIMEOUT) -> dict:
        """`GET /api/v1/meta` with a short timeout: `{std_version, api_revision, features}`.
        Raises ToolError on any failure (the caller falls back to the startup values)."""
        try:
            resp = self._http.get("/meta", timeout=timeout)
        except httpx.HTTPError as exc:
            raise ToolError(f"{exc.__class__.__name__}: {exc}") from exc
        if resp.status_code >= 400:
            raise ToolError(_format_error(resp))
        try:
            body = resp.json()
        except ValueError:
            raise ToolError(f"non-JSON answer (HTTP {resp.status_code})") from None
        if not isinstance(body, dict):
            raise ToolError("unexpected /meta answer")
        return body

    def close(self) -> None:
        self._http.close()


_STATUS_TEXT = {
    400: "invalid request",
    401: "bad or revoked API key",
    403: "this API key's scope is too low (needs write)",
    404: "not found",
    409: "conflicts with the current state",
}


def _format_error(resp: httpx.Response) -> str:
    """`HTTP 409 (conflicts ...): <error>` plus the API's `details`, kept verbatim."""
    msg, details, stale_plan = resp.text[:500], None, False
    try:
        body = resp.json()
        if isinstance(body, dict) and "error" in body:
            msg, details = str(body["error"]), body.get("details")
            stale_plan = isinstance(body.get("plan"), dict)
    except ValueError:
        pass
    text = f"HTTP {resp.status_code} ({_STATUS_TEXT.get(resp.status_code, 'error')}): {msg}"
    if details:
        text += f"\ndetails: {details!r}"
    if stale_plan:
        text += "\nNothing was written. Call import_plan again, show the operator the new plan, then apply."
    return text


def _drop_none(**kwargs: Any) -> dict:
    return {k: v for k, v in kwargs.items() if v is not None}


def _check_fields(fields: dict, allowed: set[str], what: str) -> dict:
    if not isinstance(fields, dict) or not fields:
        raise ToolError(f"`fields` must be a non-empty object naming the {what} fields to change.")
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise ToolError(f"Unknown {what} field(s): {', '.join(unknown)}. Allowed: {', '.join(sorted(allowed))}.")
    return fields


_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _parse_semver(value: Any) -> tuple[int, int, int] | None:
    m = _SEMVER.match(value.strip()) if isinstance(value, str) else None
    return tuple(int(g) for g in m.groups()) if m else None


def compare_versions(mcp_version: str, std_version: Any) -> dict:
    """Compare this script with the STD it talks to.

    `std_version` is what whoami returned; None (the field is missing) means an STD
    older than 0.9.0. Returns {mcp_version, std_version, status, advice} where status
    is match | std_newer | std_older | unknown. A patch-only difference is still
    `match`; its advice says so. Anything that is not plain MAJOR.MINOR.PATCH is unknown.
    """
    info = {"mcp_version": mcp_version, "std_version": std_version if isinstance(std_version, str) else None}
    mine = _parse_semver(mcp_version)
    if std_version is None:
        info["status"] = "std_older"
        info["advice"] = ("This STD does not report its version, so it is older than 0.9.0. "
                          "Some tools may call endpoints it lacks and return 404; upgrade STD.")
        return info
    theirs = _parse_semver(std_version)
    if mine is None or theirs is None:
        info["status"] = "unknown"
        info["advice"] = (f"The STD version ({std_version!r}) could not be compared with this script "
                          f"({mcp_version}). Everything may work; if a tool is missing or returns 404, "
                          "update std_mcp.py (see mcp/README.md).")
    elif mine[:2] == theirs[:2]:
        info["status"] = "match"
        info["advice"] = ("Versions match." if mine == theirs else
                          "Versions match (the patch level differs, which is fine).")
    elif theirs[:2] > mine[:2]:
        info["status"] = "std_newer"
        info["advice"] = (f"STD {std_version} is newer than this script ({mcp_version}) and may have API "
                          "features or tools this script lacks. Update std_mcp.py (see mcp/README.md).")
    else:
        info["status"] = "std_older"
        info["advice"] = (f"STD {std_version} is older than this script ({mcp_version}). Some tools may "
                          "call endpoints STD does not have yet and return 404. Upgrade STD, or use an "
                          "older std_mcp.py.")
    return info


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def update_advice(mcp_version: str, std_version: Any) -> str:
    """What to do when this script is older (major.minor) than STD."""
    return (f"This MCP script ({mcp_version}) is older than STD ({std_version}): stream tools and other "
            "tools or fields added since may be missing or incomplete. Update the script: "
            f"`uv run {SCRIPT_URL.format(version=std_version)}` in the MCP config, or `git pull` in your "
            "checkout. Then restart the MCP client (or reconnect the MCP server) so it loads the new tools.")


def recheck(startup: dict, current_version: Any, current_revision: Any, error: str | None) -> dict:
    """`server_info`'s answer: the startup comparison plus a fresh one.

    `startup` is the dict built at startup (compare_versions plus the std_* facts and
    `checked_at`). With `error` set the current values are unknown and the answer uses
    the startup values, labelled "as of startup <time>". Adds `startup`, `current`,
    `restart_advised` (STD changed since this server started) and `update_advised`
    (this script is older than STD); `advice` says both when they apply."""
    started = {"std_version": startup.get("std_version"), "std_api_revision": startup.get("std_api_revision"),
               "checked_at": startup.get("checked_at")}
    info = {k: v for k, v in startup.items() if k != "checked_at"}
    info["startup"] = started
    if error is not None:
        info["current"] = {"std_version": None, "std_api_revision": None, "checked": False, "error": error}
        info["std_version_source"] = f"as of startup {started['checked_at'] or 'unknown'}"
        info["restart_advised"] = False
        info["update_advised"] = info.get("status") == "std_newer"
        if info["update_advised"]:
            info["advice"] = update_advice(info["mcp_version"], info["std_version"])
        info["advice"] = (f"Could not re-check STD now ({error}); versions are as of startup "
                          f"{started['checked_at'] or 'unknown'}. " + info["advice"])
        return info
    fresh = compare_versions(info["mcp_version"], current_version if isinstance(current_version, str) else None)
    info.update(status=fresh["status"], std_version=fresh["std_version"], advice=fresh["advice"])
    if current_revision is not None:
        info["std_api_revision"] = current_revision
    info["std_version_source"] = "current"
    info["current"] = {"std_version": fresh["std_version"], "std_api_revision": current_revision,
                       "checked": True, "error": None}
    old, new = _parse_semver(started["std_version"]), _parse_semver(fresh["std_version"])
    changed = (started["std_version"] != fresh["std_version"]
               or (current_revision is not None and started["std_api_revision"] is not None
                   and current_revision != started["std_api_revision"]))
    info["restart_advised"] = bool(changed)
    info["update_advised"] = fresh["status"] == "std_newer"
    parts = []
    if changed:
        what = "upgraded" if (old and new and new > old) else "changed"
        parts.append(f"STD was {what} from {started['std_version'] or 'unknown'} to {fresh['std_version']} "
                     "since this MCP server started: restart the MCP server (restart or reconnect the MCP "
                     "client) so the tool set and the version notice are current.")
    if info["update_advised"]:
        parts.append(update_advice(info["mcp_version"], fresh["std_version"]))
    if parts:
        info["advice"] = " ".join(parts)
    return info


def version_notice(info: dict) -> str | None:
    """The one stderr line for a version difference, or None when the versions are identical."""
    mine, theirs = info["mcp_version"], info["std_version"]
    if info["status"] == "match":
        return None if mine == theirs else f"std_mcp {mine} talking to STD {theirs} (patch difference, fine)"
    shown = theirs or "older than 0.9.0"
    if info["status"] == "std_older":
        return f"std_mcp {mine} talking to STD {shown}: some tools may return 404; upgrade STD (see mcp/README.md)"
    if info["status"] == "unknown":
        return f"std_mcp {mine} talking to STD {shown}: version could not be compared (see mcp/README.md)"
    return f"std_mcp {mine} talking to STD {shown}: update std_mcp.py (see mcp/README.md)"


def build_server(client: StdClient, scope: str, version_info: dict | None = None) -> FastMCP:
    """Create the FastMCP server. Write tools are registered only for a `write` key.

    `version_info` is the result of compare_versions from startup; `server_info` reports it
    and the instructions mention a mismatch. Omitted, no version check is reported.
    """
    if scope not in ("read", "write"):
        raise ValueError(f"unexpected key scope {scope!r}")
    if version_info is None:
        version_info = {"mcp_version": MCP_VERSION, "std_version": None, "status": "unknown",
                        "advice": "The STD version was not checked."}
        mismatch = ""
    else:
        status = version_info["status"]
        advice = (update_advice(version_info["mcp_version"], version_info["std_version"])
                  if status == "std_newer" else version_info["advice"])
        mismatch = "" if status == "match" else (
            " Version notice: " + advice + " If a tool seems missing or returns 404, "
            "tell the operator to update the MCP server (std_mcp.py); server_info shows the versions."
            if status != "unknown" else
            " Version notice: the STD version could not be compared with this MCP server "
            f"({version_info['mcp_version']}). If a tool seems missing or returns 404, tell the "
            "operator to update the MCP server (std_mcp.py).")
    server = FastMCP(
        "std",
        instructions=(
            "Tools for a Service Tracker Dashboard (STD). Entries are the dashboard's services: "
            "'notifier' entries come from Docker containers (their Docker-owned fields cannot be "
            "edited), 'manual' entries are added by hand, 'stream' entries are pushed by inventory sidecars "
            "(see list_streams); a stream entry's `inventory` object carries its ip, mac, network, key and whether it is missing from the latest snapshot. Each entry has checks (internal URL, "
            "external URL, container, and any number of service checks) that roll up to a health "
            "state. Start with health_summary to see what is broken."
            + ("" if scope == "write" else " This key is read-only: no change tools are available.")
            + mismatch
        ),
    )

    def read_tool(fn):
        return server.tool()(fn)

    def write_tool(fn):
        return server.tool()(fn) if scope == "write" else fn

    # ---- read tools ---------------------------------------------------------

    startup_info = dict(version_info)
    startup_info.setdefault("checked_at", None)

    @read_tool
    def server_info() -> dict:
        """Versions of this MCP server and of the STD it talks to, and whether they match. Call it when a tool seems missing or returns 404, or when the operator asks about versions.

        Re-checks STD's version on every call with GET /api/v1/meta (3 s timeout). Returns {mcp_version, std_version, std_api_revision, status: match | std_newer | std_older | unknown, advice, std_version_source ("current", or "as of startup <time>" when the re-check failed), startup: {std_version, std_api_revision, checked_at}, current: {std_version, std_api_revision, checked, error}, restart_advised (STD changed since this MCP server started: restart it), update_advised (this script is older than STD: update std_mcp.py, then restart the MCP client)}, plus std_commit, std_channel (release | main | dev | pr | local) and std_update ({enabled, latest_version, update_available, release_url, checked_at}) from startup when STD reported them.
        """
        try:
            meta = client.meta()
        except ToolError as exc:
            return recheck(startup_info, None, None, str(exc))
        return recheck(startup_info, meta.get("std_version"), meta.get("api_revision"), None)

    @read_tool
    def list_entries(status: str = "all", source: str = "all", host: str | None = None,
                     group: str | None = None, q: str | None = None,
                     include_deleted: bool = False, deleted_only: bool = False,
                     limit: int = 200, offset: int = 0) -> dict:
        """List dashboard entries with their health summary and checks (paged, ordered by id).

        status: all | failing | healthy | unknown | stale (derived health state; use `failing` to see what is broken).
        source: all | notifier (Docker containers) | manual (added by hand) | stream (pushed by an inventory sidecar).
        q: case-insensitive search of name, host, stack and description.
        Returns {items, total, limit, offset}.
        """
        return client.request("GET", "/entries", params=dict(
            status=status, source=source, host=host, group=group, q=q,
            include_deleted=include_deleted or None, deleted_only=deleted_only or None,
            limit=limit, offset=offset))

    @read_tool
    def get_entry(entry_id: int) -> dict:
        """Get one entry in full: checks, notifier-reported data (networks, ports, exposures) and its widget (the widget key is never returned)."""
        return client.request("GET", f"/entries/{entry_id}")

    @read_tool
    def health_summary() -> dict:
        """Counts (total, passing, failing, unknown, stale = Docker entries whose notifier stopped reporting, streams_stale) and the failing entries with each failing check, its message and how long it has been failing; `streams` (per inventory stream: status, stale, last_snapshot_at, last_item_count, effective_interval_seconds, last_error, last_rejected_at, last_rejection, entries_active, entries_missing) and `stale_streams` (one {stream_id, display_name, state: "down", message, since} per stale stream; its entries keep their own health). The quickest way to ask what is broken."""
        return client.request("GET", "/health/summary")

    @read_tool
    def get_health_history(entry_id: int, range: str = "24h") -> dict:
        """Per-check health history of one entry: current state, recent failures (newest first) and the pass/fail bars. range is `24h` (half-hour buckets) or `7d`."""
        return client.request("GET", f"/entries/{entry_id}/health", params={"range": range})

    @read_tool
    def list_groups(limit: int = 200, offset: int = 0) -> dict:
        """List dashboard groups with their sort priority, icon and number of active entries."""
        return client.request("GET", "/groups", params={"limit": limit, "offset": offset})

    @read_tool
    def list_widgets(limit: int = 200, offset: int = 0) -> dict:
        """List widget instances (type, URL, fields, whether a key is set, which entries use them, whether detached)."""
        return client.request("GET", "/widgets", params={"limit": limit, "offset": offset})

    @read_tool
    def list_widget_types() -> dict:
        """List the widget types and the fields each one offers. Use it to choose `type` and `fields` for set_widget."""
        return client.request("GET", "/widgets/types")

    @read_tool
    def get_exposure_settings() -> dict:
        """The exposure direction settings (layer -> internal/external, plus per-host overrides), the layers and hosts seen so far and the valid directions."""
        return client.request("GET", "/settings/exposure")

    @read_tool
    def list_notification_channels(limit: int = 200, offset: int = 0) -> dict:
        """List notification channels (where STD publishes state, MQTT first) with their settings and live connection `status` ({state: disabled | stopped | connecting | connected | error, last_error, since}). The password is never returned, only `secret_set`. Returns {items, total, limit, offset}."""
        return client.request("GET", "/notifications/channels", params={"limit": limit, "offset": offset})

    @read_tool
    def list_notification_previous_bases(channel_id: int) -> dict:
        """The base topics (and Home Assistant discovery prefixes) a notification channel used before its last changes, newest first, at most 5. The orphan scan looks under each of them. Returns {channel_id, limit, items: [{base_topic, ha_prefix}]}."""
        return client.request("GET", f"/notifications/channels/{channel_id}/previous-bases")

    @read_tool
    def get_notification_channel(channel_id: int) -> dict:
        """Get one notification channel: type, name, enabled, config (host, port, tls, base_topic, qos, ha_discovery, ha_prefix, ha_device_prefix, ...), `secret_set` and its live connection `status`. Use it to check whether the MQTT broker is connected and why not (status.last_error)."""
        return client.request("GET", f"/notifications/channels/{channel_id}")

    @read_tool
    def list_streams(limit: int = 200, offset: int = 0) -> dict:
        """List inventory streams: sidecars (e.g. a DHCP reservation reader) that push device lists into STD. Use it to see whether a producer is alive. Each item has: status (pending = waiting for approval, enabled, disabled, ignored), producer and producer_version, first_seen_at, last_snapshot_at (last accepted snapshot), last_applied_at, last_item_count, last_counts (created/updated/unchanged/restored/missing/blocked/link_offers/filtered), last_error (last STD-side apply failure), last_rejected_at and last_rejection (the last snapshot STD refused, "<status>: <first error>") and rejecting (the latest attempt was refused), staleness: stale (enabled and no snapshot for 2 x the interval), stale_message, snapshot_age_seconds, stale_after_seconds, effective_interval_seconds with interval_source (operator | producer | default) plus expected_interval_seconds (operator) and producer_interval_seconds (advertised), missing_expiry_days, network filters, default_checks (Ping / TCP check a new entry starts with), entries {total, active, deleted, missing, linked}, blocks and link_offers counts. Returns {items, total, limit, offset, pending, stale}; `pending` is how many streams wait for review and `stale` how many are stale (the operator sees both on the Settings link in the header)."""
        return client.request("GET", "/streams", params=dict(limit=limit, offset=offset))

    @read_tool
    def get_stream(stream_id: str) -> dict:
        """Get one inventory stream by its stream_id (the slug, e.g. "dhcp"), with the same fields as a list_streams item: status, producer and version, last_snapshot_at, last_applied_at, last_item_count, last_counts, last_error, last_rejected_at / last_rejection / rejecting, stale / stale_message / snapshot_age_seconds / stale_after_seconds, effective_interval_seconds / interval_source / expected_interval_seconds / producer_interval_seconds, missing_expiry_days, filters, default_checks, entries {total, active, deleted, missing, linked}, blocks and link_offers."""
        return client.request("GET", f"/streams/{stream_id}")

    @read_tool
    def preview_stream(stream_id: str) -> dict:
        """What applying a stream's stored snapshot would do, with no changes (works for pending and disabled streams too; the Settings page shows the same counts as "would: ..."): counts plus the per-item action (created, updated, unchanged, restored, blocked, link_offer, filtered) and the entries that would be flagged missing. Use it before enable_stream on a pending stream."""
        return client.request("GET", f"/streams/{stream_id}/preview")

    @read_tool
    def list_stream_blocks(stream_id: str, limit: int = 200, offset: int = 0) -> dict:
        """List the keys blocked on a stream (deleted entries the stream must not bring back). Returns {items, total, limit, offset}."""
        return client.request("GET", f"/streams/{stream_id}/blocks", params=dict(limit=limit, offset=offset))

    @read_tool
    def list_stream_offers(stream_id: str, limit: int = 200, offset: int = 0) -> dict:
        """List open link offers: new stream items whose name (or first DNS label) equals exactly one manual entry's name, host or host's first label and wait for accept or decline (answer_link_offer). Returns {items, total, limit, offset}."""
        return client.request("GET", f"/streams/{stream_id}/offers", params=dict(limit=limit, offset=offset))

    @read_tool
    def list_stream_unmatched_items(stream_id: str, limit: int = 200, offset: int = 0) -> dict:
        """List items of a stream's latest snapshot that have no entry and are not blocked: what link_entry_to_stream_item can link a manual entry to. Returns {items, total, limit, offset}."""
        return client.request("GET", f"/streams/{stream_id}/unmatched", params=dict(limit=limit, offset=offset))

    @read_tool
    def list_image_updates(state: str | None = None, limit: int = 200, offset: int = 0) -> dict:
        """List the image references the Docker entries run and whether a newer image exists (the image update check), with the entries using each. Entries also carry an `image_update` block (list_entries, get_entry).

        state: update | current | unknown | error | pinned | off (only references with an entry in that state). `update` is what needs attention; `unknown` says why in `reason` (for example an older notifier that does not report the running digest); `off` is also what every entry shows while the check is switched off (it is off by default; STD_IMAGE_UPDATE_ENABLED or Settings turns it on).
        Returns {items, total, limit, offset}; each item has ref, remote_digest, checked_at, error, next_check_at and entries [{id, name, host, state, latest, kind, since, policy}].
        """
        return client.request("GET", "/image-updates", params=dict(state=state, limit=limit, offset=offset))

    @read_tool
    def list_ports(kind: str = "all", host: str | None = None, query: str | None = None,
                   conflicts_only: bool = False) -> dict:
        """List the container ports in use across all hosts: answer "what is on port 8080 on host X" or "is this port free". Ports come from the Docker notifier and only for running containers.

        kind: published (bound on the host: reachable at host:host_port) | host_network (a network_mode host container: its port is bound directly on the host, host_port = container port) | direct (a macvlan/ipvlan container with its own LAN address: reachable at host_ips[0]:container_port, not through the host; network names the network) | exposed (declared by the image but NOT bound on the host, so it takes no host port) | all (default). host: exact host name. query: text in the name, container name, stack or a port number. conflicts_only: only rows in conflict.
        A conflict means two different entries on the same host publish the same protocol and host port on overlapping addresses (a wildcard address such as 0.0.0.0 or :: overlaps any other), so one of them cannot bind. host_network rows take part in that rule; direct rows conflict only with another direct row on the same address, protocol and port.
        Returns {summary: {hosts, published, host_network, direct, exposed, conflicts}, ports: [{entry_id, name, host, container_name, stack_name, docker_status, kind, host_ips, host_port (null when exposed or ports_unknown), container_port and protocol (null when ports_unknown), port_source (declared | url, a port read from the entry's URL), ports_unknown (a macvlan/ipvlan or host-network container that declares no ports: every port is reachable, never a conflict), network and driver (direct rows, else null), conflict, conflict_with: [entry ids]}]}; summary counts all ports, not only the filtered ones.
        """
        return client.request("GET", "/ports", params=dict(
            kind=kind, host=host, q=query, conflicts="true" if conflicts_only else None))

    @read_tool
    def backup_settings() -> dict:
        """The backup settings: the folder and the two daily jobs (snapshot, export), each value with its origin (env | ui | file | default; env means pinned by an environment variable and read-only), plus last_runs and next_runs by kind."""
        return client.request("GET", "/settings/backup")

    @read_tool
    def list_backups() -> dict:
        """List the backup files in STD's backup folder, newest first: {items: [{name, kind (snapshot | export), size, modified, manual, legacy}]}. Snapshots hold every secret and cannot be downloaded through the API; use export_config for the exportable settings."""
        return client.request("GET", "/backups")

    @read_tool
    def export_config() -> dict:
        """The export of the operator-set settings (format std-export, version 1) as JSON: groups, URLs the operator set, checks, widgets, notification channels, inventory streams and blocks, users, exposure and update-check settings and the backup schedule. It never contains a secret: secret_set and api_key_set only say that a password or key exists. Soft-deleted entries and anything STD rebuilds on its own (status, IPs, health results) are left out. Can be large."""
        return client.request("GET", "/export", params={"format": "json"})

    @read_tool
    def get_config() -> dict:
        """The effective STD configuration, read-only. Secrets appear as `***`; `sources` says whether each value came from env, file or default."""
        return client.request("GET", "/config")

    # ---- write tools --------------------------------------------------------

    @write_tool
    def run_backup(kind: str) -> dict:
        """Run a backup now and wait for it. kind: snapshot (a full copy of the database, secrets included; stays in STD's backup folder) or export (the operator-set settings, no secrets, as YAML or JSON per the backup settings). Returns {kind, ok, file, size, error, at, trigger}; ok false carries the error. It is a 409 when that kind is already running."""
        if kind not in ("snapshot", "export"):
            raise ToolError("kind must be 'snapshot' or 'export'.")
        return client.request("POST", "/backups/run", json={"kind": kind})

    @write_tool
    def import_plan(document_text: str, stream_map: dict | None = None, selection: dict | None = None) -> dict:
        """Dry-run an import and return the plan. Nothing is written. ALWAYS call this first and show the operator the plan before import_apply.

        document_text: the export as text (YAML or JSON), or an old YAML backup.
        stream_map: {file stream id: local stream id, or null to skip}. A stream left out is matched by id.
        selection: {row id: {"apply": true, "fields": [..] or null, "target_id": id or null, "create": bool, "options": ["restore"]}}, the rows you intend to apply. Leave it out to get the default (pre-ticked) selection.
        Returns {header, stream_mapping, rows, counts, warnings, stream_map, default_selection, fingerprint}. Every row has a status: missing (settings to fill; ticked by default), differs (only applied in overwrite mode), identical, deleted (restore needs the `restore` option), ambiguous (choose target_id), not_found (create: true imports it as new), waiting, conflict, invalid. The fingerprint is for `selection` (or default_selection): pass the same selection, stream_map and fingerprint to import_apply.
        """
        body = _drop_none(document_text=document_text, stream_map=stream_map, selection=selection)
        return client.request("POST", "/import/plan", json=body)

    @write_tool
    def import_apply(document_text: str, stream_map: dict | None, selection: dict, mode: str, fingerprint: str) -> dict:
        """Apply the selected rows of an import in one transaction, or nothing. Call import_plan first and show the operator the plan: this writes to STD.

        mode: `fill` (only fields that are missing) or `overwrite` (also the differing fields named in `fields`).
        fingerprint: the one import_plan returned for exactly this selection and stream_map. If a selected row changed since, nothing is written and the call fails: plan again.
        Never deletes anything and never writes a secret. Users are created without a password and channels disabled; the result's `still_to_do` lists what the operator must set up again (user passwords, the MQTT password, widget API keys, ingest keys, the notifier api_token).
        Returns {mode, counts, skipped, still_to_do, notes, applied}.
        """
        if mode not in ("fill", "overwrite"):
            raise ToolError("mode must be 'fill' or 'overwrite'.")
        body = _drop_none(document_text=document_text, stream_map=stream_map)
        body.update(selection=selection, mode=mode, fingerprint=fingerprint)
        return client.request("POST", "/import/apply", json=body)

    @write_tool
    def create_manual_entry(name: str, host: str | None = None, description: str | None = None,
                            group: str | None = None, internalurl: str | None = None,
                            externalurl: str | None = None, icon: str | None = None,
                            sort_priority: int | None = None, locked: bool = False,
                            ha_publish: bool = False,
                            url_checks: dict | None = None,
                            checks: list[dict] | None = None) -> dict:
        """Add a manual (non-Docker) entry, optionally with checks.

        group: group name; created if missing; omit to leave the entry ungrouped.
        ha_publish: true publishes the entry to Home Assistant (default false; needs a channel with Add to Home Assistant on).
        url_checks: settings for the URL checks, e.g.
            {"internal": {"enabled": true, "mode": "body", "interval_seconds": 60}, "external": {"enabled": false}}
            mode is `status` (HTTP status below 400 is up) or `body` (the body must be `OK`; anything else is down and `Error: <msg>` shows <msg> as the failure message).
            cert_min_days (1..365, https URLs only) also fails the check when the certificate has fewer days left, e.g. {"internal": {"enabled": true, "verify_tls": false, "cert_min_days": 7}}.
        checks: extra service checks, each {target, check_type (http|tcp|ping|dns), name, mode, interval_seconds, timeout_seconds, verify_tls, enabled}, e.g.
            [{"target": "nas.lan", "check_type": "ping"}, {"target": "http://nas.lan:5000/health", "mode": "body", "interval_seconds": 60}]
            tcp targets are `host:port`. A dns check takes the DNS server as target plus dns_name (see add_check).
        """
        body = _drop_none(name=name, host=host, description=description, group=group,
                          internalurl=internalurl, externalurl=externalurl, icon=icon,
                          sort_priority=sort_priority, url_checks=url_checks, checks=checks)
        body["locked"] = locked
        body["ha_publish"] = ha_publish
        return client.request("POST", "/entries", json=body)

    @write_tool
    def update_entry(entry_id: int, fields: dict) -> dict:
        """Edit an entry. `fields` names only what changes; a field left out is untouched and a field set to null clears it.

        Allowed: name, host (manual entries only), description, group (group name; null ungroups), internalurl, externalurl, icon, image_repo_url (http(s) override for the image repository link; null clears it), sort_priority, locked, ha_publish (true publishes the entry's device to Home Assistant, default false; only matters when a notification channel has Add to Home Assistant on).
        Docker entries also take the image update settings: image_update_policy (auto | tags | digest | off), image_update_scope (any | minor | patch; null = the global default) and image_tag_pattern (a full-match regex for the tag model; null clears it).
        Docker-owned fields of notifier entries are rejected. A URL you edit here is protected from being overwritten by the notifier.
        Example fields: {"description": "Media server", "group": "Media", "externalurl": null}
        """
        return client.request("PATCH", f"/entries/{entry_id}",
                              json=_check_fields(fields, ENTRY_PATCH_FIELDS, "entry"))

    @write_tool
    def delete_entry(entry_id: int, permanent: bool = False, block: bool = False) -> dict:
        """Delete an entry. By default it is soft-deleted and can be brought back with restore_entry. permanent=true removes an already deleted entry for good (irreversible). block=true (entries that belong to an inventory stream) also blocks the entry's key so a later snapshot cannot bring it back; unblock it with unblock_stream_key."""
        return client.request("DELETE", f"/entries/{entry_id}",
                              params={"permanent": permanent or None, "block": block or None})

    @write_tool
    def unlink_entry(entry_id: int, block: bool = False) -> dict:
        """Unlink a stream entry: it becomes a manual entry again, keeping its id, history, checks and settings. An entry that was a manual entry linked to the stream gets its old host back (unless that host and name are now taken: it stays hostless; host_clash says which). block=true also blocks the item's key so no snapshot re-creates or re-offers it (unblock_stream_key undoes it); without it the next snapshot may offer the link again. Returns {entry, blocked, host_restored, host_clash, host}."""
        return client.request("POST", f"/entries/{entry_id}/unlink", json={"block": block})

    @write_tool
    def restore_entry(entry_id: int) -> dict:
        """Restore a soft-deleted entry."""
        return client.request("POST", f"/entries/{entry_id}/restore")

    @write_tool
    def add_check(entry_id: int, target: str, check_type: str = "http", name: str | None = None,
                  mode: str | None = None, interval_seconds: int | None = None,
                  timeout_seconds: int | None = None, verify_tls: bool = True,
                  enabled: bool = True, dns_name: str | None = None,
                  dns_record_type: str | None = None, dns_expected_rcode: str | None = None,
                  dns_expected_answer: str | None = None, cert_min_days: int | None = None) -> dict:
        """Add a service check to an entry.

        check_type: http (target is a URL), tcp (target is `host:port`), ping (target is a host) or dns (target is the DNS server).
        dns checks query the given server directly (never the system resolver). target is an IP address, optionally with a port (`10.100.16.16`, `10.100.16.16:5353`, `[2001:db8::1]:53`); a hostname is rejected.
            dns_name: the name to look up (required; an IP address is accepted for PTR).
            dns_record_type: A (default), AAAA, CNAME, TXT, PTR, MX, NS or SRV.
            dns_expected_rcode: NOERROR (default), NXDOMAIN, SERVFAIL, REFUSED, ...
            dns_expected_answer: optional; up only when any answer record matches exactly (case-insensitive, trailing dot ignored). Omit it to judge by rcode only. A NOERROR reply with no answers is up only when no answer is expected.
            Example: check_type="dns", target="10.100.16.16", dns_name="em-pve01.crzynet.me", dns_record_type="A", dns_expected_answer="10.100.17.10"
        mode (http only): `status` (default; up when the HTTP status is below 400) or `body` (up only when the response body is exactly `OK`; a body like `Error: disk full` is down and shows `disk full` as the message).
        cert_min_days (http checks only, 1..365): also fail the check when the https certificate has fewer than this many days left (message `cert expires in N days (min M)`). The certificate is read separately from the HTTP request, so it works with verify_tls false: a self-signed cert still reports its expiry. Ignored for an http:// target; tcp, ping and dns checks reject it.
            Example (Emmett's Proxmox, self-signed): check_type="http", target="https://em-pve01.crzynet.me:8006/", verify_tls=false, cert_min_days=7
        interval_seconds 30..86400 and timeout_seconds 1..60; omit for the global defaults.
        """
        body = _drop_none(target=target, check_type=check_type, name=name, mode=mode,
                          interval_seconds=interval_seconds, timeout_seconds=timeout_seconds, dns_name=dns_name,
                          dns_record_type=dns_record_type, dns_expected_rcode=dns_expected_rcode,
                          dns_expected_answer=dns_expected_answer, cert_min_days=cert_min_days)
        body.update(verify_tls=verify_tls, enabled=enabled)
        return client.request("POST", f"/entries/{entry_id}/checks", json=body)

    @write_tool
    def update_check(check_id: int, fields: dict) -> dict:
        """Edit or enable/disable a check. `fields` names only what changes (null clears where that makes sense).

        Allowed: enabled, name, check_type, target, mode, interval_seconds, timeout_seconds, verify_tls, dns_name, dns_record_type, dns_expected_rcode, dns_expected_answer, cert_min_days, ha_exclude (true removes this check's entity from Home Assistant; allowed on every kind of check).
        cert_min_days (URL checks and http service checks, 1..365; null clears it) fails the check when the https certificate has fewer days left, e.g. a URL check on https://em-pve01.crzynet.me:8006/ with {"cert_min_days": 7}; Proxmox's self-signed certificate with verify_tls false still reports its expiry. It is a 400 on tcp, ping and dns checks.
        The dns_* fields apply to service checks of type dns (target is then the DNS server), e.g. {"check_type": "dns", "target": "10.100.16.16", "dns_name": "em-pve01.crzynet.me", "dns_record_type": "A", "dns_expected_answer": "10.100.17.10"}; dns_expected_answer null clears it (rcode only).
        URL checks (internal/external) accept enabled, mode, interval_seconds, timeout_seconds, verify_tls, cert_min_days and ha_exclude; container checks accept enabled, interval_seconds and ha_exclude; service checks accept everything.
        Example fields: {"enabled": false}  or  {"mode": "body", "interval_seconds": 60}
        """
        return client.request("PATCH", f"/checks/{check_id}",
                              json=_check_fields(fields, CHECK_PATCH_FIELDS, "check"))

    @write_tool
    def delete_check(check_id: int) -> dict:
        """Delete a service check. Only service checks can be deleted; disable the URL and container checks instead (update_check)."""
        return client.request("DELETE", f"/checks/{check_id}")

    @write_tool
    def run_image_update_check(entry_id: int | None = None) -> dict:
        """Ask STD to check the image registries for newer images now. Without entry_id every image is checked (at most once per hour); with it only that entry's image (at most once per 15 minutes per image). Returns {ok, queued, requested_at} at once: the check runs in the background, so read the result a little later with list_image_updates or get_entry. A 429 means it was throttled (see Retry-After); a 409 means the check is switched off or the entry has no image to check."""
        return client.request("POST", "/image-updates/run",
                              json=None if entry_id is None else {"entry_id": entry_id})

    @write_tool
    def run_checks(entry_id: int) -> dict:
        """Queue every check of an entry that counts for an immediate run ("check now"). Returns how many were queued; read the result a few seconds later with get_entry."""
        return client.request("POST", f"/entries/{entry_id}/checks/run")

    @write_tool
    def upsert_group(name: str, new_name: str | None = None, icon: str | None = None,
                     sort_priority: int | None = None) -> dict:
        """Create the group `name`, or update it if it already exists (matched by exact name).

        new_name renames an existing group. icon and sort_priority are set only when given (they cannot be cleared here).
        Returns {"action": "created" | "updated" | "unchanged", "group": {...}}.
        """
        existing = None
        offset = 0
        while existing is None:
            page = client.request("GET", "/groups", params={"limit": 1000, "offset": offset})
            existing = next((g for g in page["items"] if g["name"] == name), None)
            offset += len(page["items"])
            if existing is not None or not page["items"] or offset >= page["total"]:
                break
        if existing is None:
            if new_name:
                raise ToolError(f"Group {name!r} does not exist, so it cannot be renamed.")
            group = client.request("POST", "/groups",
                                   json=_drop_none(name=name, icon=icon, sort_priority=sort_priority))
            return {"action": "created", "group": group}
        changes = _drop_none(name=new_name if new_name and new_name != name else None,
                             icon=icon, sort_priority=sort_priority)
        if not changes:
            return {"action": "unchanged", "group": existing}
        group = client.request("PATCH", f"/groups/{existing['id']}", json=changes)
        return {"action": "updated", "group": group}

    @write_tool
    def set_widget(entry_id: int, type: str, url: str, fields: list[str],
                   widget_api_key: str | None = None, clear_api_key: bool = False) -> dict:
        """Attach a widget to an entry, or reconfigure the one it has (replaces type, URL and fields).

        type and the available field keys come from list_widget_types. widget_api_key left out keeps the stored key; clear_api_key=true removes it. The key is never returned.
        Example: set_widget(12, "sonarr", "http://sonarr.lan:8989", ["queue", "wanted"], widget_api_key="...")
        """
        body: dict = {"type": type, "url": url, "fields": fields}
        if clear_api_key:
            if widget_api_key is not None:
                raise ToolError("Give widget_api_key or clear_api_key, not both.")
            body["widget_api_key"] = None
        elif widget_api_key is not None:
            body["widget_api_key"] = widget_api_key
        return client.request("PUT", f"/entries/{entry_id}/widget", json=body)

    @write_tool
    def remove_widget(entry_id: int, delete: bool = False) -> dict:
        """Detach an entry's widget. delete=true also removes the widget and its stored values (when no other entry uses it); otherwise it stays in Settings -> Widgets."""
        return client.request("DELETE", f"/entries/{entry_id}/widget",
                              params={"delete": delete or None})

    @write_tool
    def test_notification_channel(channel_id: int) -> dict:
        """Send a test message through a notification channel: connects with the stored settings and publishes a non-retained JSON message to `<base_topic>/test`. Returns {ok, message}; a failure is ok=false with the reason (it is not an error). Takes up to about 13 seconds."""
        return client.request("POST", f"/notifications/channels/{channel_id}/test")

    @write_tool
    def purge_notification_channel(channel_id: int, republish: bool = True) -> dict:
        """Clean slate for one notification channel's MQTT broker: removes every retained STD message under its base_topic and every STD Home Assistant discovery config (devices and entities) of this STD instance. `<base_topic>/status` is left alone.

        republish=true (default) publishes the current state and configs again after about 2 seconds, so Home Assistant recreates the devices with fresh entity ids. republish=false leaves the broker empty until something changes or the channel reconnects. Returns the counts {topics_cleared, state_topics, discovery_topics, republished}. Takes several seconds; 409 if the channel is disabled or not connected.
        """
        return client.request("POST", f"/notifications/channels/{channel_id}/purge",
                              json={"republish": republish})

    @write_tool
    def purge_entry_notifications(entry_id: int) -> dict:
        """Purge one entry's MQTT topics and Home Assistant device on every enabled channel, wait about 2 seconds, then republish it, so Home Assistant recreates the device with fresh entity ids (use it after renaming an entry). An entry not published to Home Assistant only has its state topics cleared and republished. Returns {entry_id, topics_cleared, channels, republished}; 409 if no channel is enabled."""
        return client.request("POST", f"/entries/{entry_id}/notifications/purge")

    @write_tool
    def delete_notification_channel(channel_id: int, cleanup: bool = True) -> dict:
        """Delete a notification channel. cleanup=true (default) first removes the channel's retained STD topics, Home Assistant discovery configs and its `<base_topic>/status` from the MQTT broker (no republish). If the channel is disabled or its broker cannot be reached the answer is 409 and nothing is deleted: enable the channel and wait until it is connected, or call again with cleanup=false to delete without touching the broker (topics may stay behind; scan_notification_orphans finds them later). Returns {id, deleted, cleanup: {topics_cleared, state_topics, discovery_topics} or null}. Takes several seconds with cleanup."""
        return client.request("DELETE", f"/notifications/channels/{channel_id}", params={"cleanup": cleanup})

    @write_tool
    def update_notification_channel(channel_id: int, fields: dict, cleanup: bool | None = None) -> dict:
        """Change a notification channel (the password cannot be set here). `fields` names only what changes: name, enabled, config (keys are merged over the stored config: host, port, tls, tls_insecure, username, client_id, base_topic, qos, keepalive, ha_discovery, ha_prefix, ha_device_prefix).
        cleanup clears the broker first. Omitted: a change of base_topic (or ha_prefix / ha_device_prefix while discovery is on) removes the old base's retained topics and discovery configs and remembers the old base; a plain disable leaves the broker alone. cleanup=true also removes the channel's data when this call disables it; cleanup=false never touches the broker. 409 (nothing changed) when the cleanup is wanted but the broker cannot be reached.
        Example: fields {"config": {"base_topic": "std2"}}, or fields {"enabled": false} with cleanup true."""
        allowed = {"name", "enabled", "config"}
        body = dict(_check_fields(fields, allowed, "notification channel"))
        if cleanup is not None:
            body["cleanup"] = cleanup
        return client.request("PATCH", f"/notifications/channels/{channel_id}", json=body)

    @write_tool
    def scan_notification_orphans(channel_id: int, extra_base: str | None = None) -> dict:
        """Preview orphaned retained STD topics on a channel's MQTT broker; nothing is cleared. It subscribes briefly to the current base_topic, every remembered previous base (list_notification_previous_bases), the optional extra_base (a base topic you remember using) and this STD install's Home Assistant discovery configs, and lists retained STD-shaped topics (status, summary, entry/<id>/state, entry/<id>/check/<id>, stream/<id>, discovery configs) that STD no longer publishes. Returns {channel_id, scanned, count, orphans: [{topic, kind}]}. Takes several seconds; 409 if the channel is disabled or not connected."""
        return client.request("POST", f"/notifications/channels/{channel_id}/orphans/scan",
                              json={"extra_base": extra_base} if extra_base else None)

    @write_tool
    def clear_notification_orphans(channel_id: int, topics: list[str] | None = None,
                                   extra_base: str | None = None) -> dict:
        """Clear orphaned retained topics on a channel's broker. Pass `topics` (the list scan_notification_orphans returned) to clear exactly those; topics outside the scanned bases or that STD publishes again are returned in `skipped`. Without `topics` the channel is scanned again and every orphan found is cleared. Use the same extra_base as for the scan. Returns {channel_id, topics_cleared, topics, skipped}."""
        body = {k: v for k, v in (("topics", topics), ("extra_base", extra_base)) if v is not None}
        return client.request("POST", f"/notifications/channels/{channel_id}/orphans/clear", json=body or None)

    @write_tool
    def purge_stream_notifications(stream_id: str) -> dict:
        """Purge every entry of an inventory stream from MQTT and Home Assistant on every enabled channel in one batch: state and check topics and discovery configs of all its entries (soft-deleted ones too) plus the stream's own `<base_topic>/stream/<stream_id>` status topic and its Home Assistant hub device. After about 2 seconds what is still eligible is published again (entries that are gone or not opted in to Home Assistant stay cleared). Returns {stream_id, entries, topics_cleared, channels, republished}; 409 if no channel is enabled."""
        return client.request("POST", f"/streams/{stream_id}/notifications/purge")

    @write_tool
    def update_stream(stream_id: str, fields: dict) -> dict:
        """Rename an inventory stream or change its network filters, default checks, expected interval and missing-entry expiry. `fields` names only what changes: display_name (1-32 characters), network_include and network_exclude (lists of network names; null or [] clears), default_checks ({"ping": bool, "tcp_port": 1-65535 or null}; null clears), expected_interval_seconds (60-86400; null = the producer's advertised interval or 15 min; the stream is stale after 2 x this without a snapshot), missing_expiry_days (1-3650; null = off: soft-delete entries missing that long, daily, never ones a human edited). Items outside the include list or inside the exclude list are dropped from the next snapshot on. default_checks make new stream entries start with an enabled Ping check on their IP and, when tcp_port is set, a TCP check on ip:port; existing entries are not touched until apply_stream_default_checks.
        Example fields: {"network_exclude": ["Guest"]}, {"default_checks": {"ping": true, "tcp_port": null}} or {"expected_interval_seconds": 300, "missing_expiry_days": 30}
        """
        allowed = {"display_name", "network_include", "network_exclude", "default_checks",
                   "expected_interval_seconds", "missing_expiry_days"}
        return client.request("PATCH", f"/streams/{stream_id}", json=_check_fields(fields, allowed, "stream"))

    @write_tool
    def apply_stream_default_checks(stream_id: str) -> dict:
        """Add the stream's default checks (see update_stream) to every active entry of the stream that has an IP. Entries that already have a check of that kind (any Ping, any TCP) are skipped, so nothing is duplicated and customised checks are left alone. Returns {stream, entries, entries_changed, checks_added}."""
        return client.request("POST", f"/streams/{stream_id}/default-checks/apply")

    @write_tool
    def enable_stream(stream_id: str) -> dict:
        """Enable a pending, disabled or ignored inventory stream and apply its stored snapshot now (creates entries). Run preview_stream first. Returns {stream, applied, counts}."""
        return client.request("POST", f"/streams/{stream_id}/enable")

    @write_tool
    def disable_stream(stream_id: str, cleanup: str = "keep", clear_blocks: bool = False) -> dict:
        """Disable an enabled stream: it stops applying snapshots (they are still stored). cleanup decides what happens to its entries: keep (they stay, no longer updated), soft_delete (all soft-deleted; re-enabling restores them) or purge (hard delete, plus the link offers; irreversible). Entries that were manual entries linked to the stream (inventory.linked) are never deleted by soft_delete or purge: they are unlinked (back to manual with their old host) and counted in result.unlinked. clear_blocks=true (purge only) also empties the block list. The stored snapshot is kept in every mode. Returns {stream, cleanup, result}."""
        return client.request("POST", f"/streams/{stream_id}/disable",
                              json={"cleanup": cleanup, "clear_blocks": clear_blocks})

    @write_tool
    def ignore_stream(stream_id: str) -> dict:
        """Ignore a pending or disabled stream: its stored snapshot is discarded and later snapshots are dropped."""
        return client.request("POST", f"/streams/{stream_id}/ignore")

    @write_tool
    def delete_stream(stream_id: str, cleanup: str = "keep") -> dict:
        """Delete an inventory stream and its blocks and link offers. cleanup: keep (entries become manual entries), soft_delete (entries are soft-deleted and become manual, restorable) or purge (hard delete; irreversible). Linked entries (inventory.linked: manual entries that joined the stream) are never deleted: soft_delete and purge unlink them (back to manual, keeping their old host, counted in result.unlinked) and keep makes them manual with their host restored. A sidecar that keeps posting recreates the stream as pending."""
        return client.request("DELETE", f"/streams/{stream_id}", params={"cleanup": cleanup})

    @write_tool
    def unblock_stream_key(stream_id: str, block_id: int) -> dict:
        """Remove a block (ids from list_stream_blocks). The next snapshot restores the entry or creates a new one."""
        return client.request("DELETE", f"/streams/{stream_id}/blocks/{block_id}")

    @write_tool
    def answer_link_offer(stream_id: str, offer_id: int, accept: bool) -> dict:
        """Answer a link offer (ids from list_stream_offers). accept=true: the manual entry becomes a stream entry and keeps its id, history, checks and Home Assistant setting. accept=false: a new stream entry is created and the manual entry is left alone."""
        return client.request("POST", f"/streams/{stream_id}/offers/{offer_id}/{'accept' if accept else 'decline'}")

    @write_tool
    def link_entry_to_stream_item(stream_id: str, entry_id: int, key: str) -> dict:
        """Link any active manual entry (with or without a host) to an unmatched item of a stream's latest snapshot (keys from list_stream_unmatched_items). The entry keeps its id, history and checks; its host is cleared because the stream reports the address."""
        return client.request("POST", f"/streams/{stream_id}/link", json={"entry_id": entry_id, "key": key})

    @write_tool
    def set_exposure_settings(layer_directions: dict[str, str],
                              host_overrides: dict[str, dict[str, str]] | None = None) -> dict:
        """Replace the exposure direction settings, then recompute every service's synthesized URLs (UI edits and explicit labels are never overwritten).

        layer_directions maps a layer to `internal`, `external` or `neither` (see valid_directions in get_exposure_settings); host_overrides maps host -> layer -> direction.
        This REPLACES both mappings: start from get_exposure_settings and send the full result.
        """
        return client.request("PUT", "/settings/exposure", json={
            "layer_directions": layer_directions, "host_overrides": host_overrides or {}})

    return server


def main() -> None:
    url = os.environ.get("STD_URL", "").strip()
    key = os.environ.get("STD_API_KEY", "").strip()
    if not url or not key:
        sys.exit("std-mcp: set STD_URL and STD_API_KEY (see mcp/README.md).")
    try:
        timeout = float(os.environ.get("STD_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        sys.exit("std-mcp: STD_TIMEOUT must be a number of seconds.")
    client = StdClient(url, key, verify_tls=_truthy(os.environ.get("STD_VERIFY_TLS")), timeout=timeout)
    try:
        who = client.request("GET", "/whoami")
    except ToolError as exc:
        sys.exit(f"std-mcp: cannot use the API key at {url}: {exc}")
    std_version = who.get("version")
    info = compare_versions(MCP_VERSION, std_version)
    info["checked_at"] = _now_iso()
    # Build facts and the update check are reported as-is; they never affect the comparison.
    for field, name in (("commit", "std_commit"), ("channel", "std_channel"), ("update", "std_update"),
                         ("api_revision", "std_api_revision")):
        if who.get(field) is not None:
            info[name] = who[field]
    channel = who.get("channel")
    print(f"std-mcp: connected to STD {std_version or 'unknown version'}"
          f"{f' ({channel} build)' if channel and channel != 'release' else ''} as key {who['name']!r} "
          f"({who['scope']}); std_mcp {MCP_VERSION}", file=sys.stderr)
    update = who.get("update") or {}
    if update.get("update_available"):
        print(f"std-mcp: STD {update.get('latest_version')} is available (running {std_version})",
              file=sys.stderr)
    notice = version_notice(info)
    if notice:
        print(f"std-mcp: {notice}", file=sys.stderr)
    build_server(client, who["scope"], info).run(transport="stdio")


if __name__ == "__main__":
    main()
