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
    STD_API_KEY      an admin API key from Settings -> API                  (required)
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
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# httpx logs every request URL at INFO; keep the stdio server quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

# The release this script belongs to. `/release-prep` sets it with VERSION; a test
# keeps the two from drifting.
MCP_VERSION = "0.9.0"

API = "/api/v1"
DEFAULT_TIMEOUT = 15.0

# Fields the PATCH endpoints accept. Checked client-side so that a typo gives a
# readable error, not a round trip. The server stays the authority.
ENTRY_PATCH_FIELDS = {
    "name", "host", "description", "group", "internalurl", "externalurl",
    "icon", "sort_priority", "locked", "ha_publish",
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
    msg, details = resp.text[:500], None
    try:
        body = resp.json()
        if isinstance(body, dict) and "error" in body:
            msg, details = str(body["error"]), body.get("details")
    except ValueError:
        pass
    text = f"HTTP {resp.status_code} ({_STATUS_TEXT.get(resp.status_code, 'error')}): {msg}"
    if details:
        text += f"\ndetails: {details!r}"
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
        mismatch = "" if status == "match" else (
            " Version notice: " + version_info["advice"] + " If a tool seems missing or returns 404, "
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
            "edited), 'manual' entries are added by hand. Each entry has checks (internal URL, "
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

    @read_tool
    def server_info() -> dict:
        """Versions of this MCP server and of the STD it talks to, and whether they match. Call it when a tool seems missing or returns 404, or when the operator asks about versions.

        Returns {mcp_version, std_version, status: match | std_newer | std_older | unknown, advice}, plus std_commit, std_channel (release | main | dev | pr | local) and std_update ({enabled, latest_version, update_available, release_url, checked_at}) when STD reports them. Answered from what was checked at startup; no request is made.
        """
        return dict(version_info)

    @read_tool
    def list_entries(status: str = "all", source: str = "all", host: str | None = None,
                     group: str | None = None, q: str | None = None,
                     include_deleted: bool = False, deleted_only: bool = False,
                     limit: int = 200, offset: int = 0) -> dict:
        """List dashboard entries with their health summary and checks (paged, ordered by id).

        status: all | failing | healthy | unknown | stale (derived health state; use `failing` to see what is broken).
        source: all | notifier (Docker containers) | manual (added by hand).
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
        """Counts (total, passing, failing, unknown, stale) and the failing entries with each failing check, its message and how long it has been failing. The quickest way to ask what is broken."""
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
    def get_notification_channel(channel_id: int) -> dict:
        """Get one notification channel: type, name, enabled, config (host, port, tls, base_topic, qos, ha_discovery, ha_prefix, ha_device_prefix, ...), `secret_set` and its live connection `status`. Use it to check whether the MQTT broker is connected and why not (status.last_error)."""
        return client.request("GET", f"/notifications/channels/{channel_id}")

    @read_tool
    def get_config() -> dict:
        """The effective STD configuration, read-only. Secrets appear as `***`; `sources` says whether each value came from env, file or default."""
        return client.request("GET", "/config")

    # ---- write tools --------------------------------------------------------

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

        Allowed: name, host (manual entries only), description, group (group name; null ungroups), internalurl, externalurl, icon, sort_priority, locked, ha_publish (true publishes the entry's device to Home Assistant, default false; only matters when a notification channel has Add to Home Assistant on).
        Docker-owned fields of notifier entries are rejected. A URL you edit here is protected from being overwritten by the notifier.
        Example fields: {"description": "Media server", "group": "Media", "externalurl": null}
        """
        return client.request("PATCH", f"/entries/{entry_id}",
                              json=_check_fields(fields, ENTRY_PATCH_FIELDS, "entry"))

    @write_tool
    def delete_entry(entry_id: int, permanent: bool = False) -> dict:
        """Delete an entry. By default it is soft-deleted and can be brought back with restore_entry. permanent=true removes an already deleted entry for good (irreversible)."""
        return client.request("DELETE", f"/entries/{entry_id}",
                              params={"permanent": permanent or None})

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
    # Build facts and the update check are reported as-is; they never affect the comparison.
    for field, name in (("commit", "std_commit"), ("channel", "std_channel"), ("update", "std_update")):
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
