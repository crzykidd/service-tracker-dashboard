#!/usr/bin/env python3
"""MCP server for the Service Tracker Dashboard management API (v0.8.0, PRD 14.7).

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
tools; a `write` key registers all of them.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# httpx logs every request URL at INFO; keep the stdio server quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)

API = "/api/v1"
DEFAULT_TIMEOUT = 15.0

# Fields the PATCH endpoints accept. Checked client-side so that a typo gives a
# readable error, not a round trip. The server stays the authority.
ENTRY_PATCH_FIELDS = {
    "name", "host", "description", "group", "internalurl", "externalurl",
    "icon", "sort_priority", "locked",
}
CHECK_PATCH_FIELDS = {
    "enabled", "name", "check_type", "target", "mode", "interval_seconds",
    "timeout_seconds", "verify_tls",
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


def build_server(client: StdClient, scope: str) -> FastMCP:
    """Create the FastMCP server. Write tools are registered only for a `write` key."""
    if scope not in ("read", "write"):
        raise ValueError(f"unexpected key scope {scope!r}")
    server = FastMCP(
        "std",
        instructions=(
            "Tools for a Service Tracker Dashboard (STD). Entries are the dashboard's services: "
            "'notifier' entries come from Docker containers (their Docker-owned fields cannot be "
            "edited), 'manual' entries are added by hand. Each entry has checks (internal URL, "
            "external URL, container, and any number of service checks) that roll up to a health "
            "state. Start with health_summary to see what is broken."
            + ("" if scope == "write" else " This key is read-only: no change tools are available.")
        ),
    )

    def read_tool(fn):
        return server.tool()(fn)

    def write_tool(fn):
        return server.tool()(fn) if scope == "write" else fn

    # ---- read tools ---------------------------------------------------------

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
    def get_config() -> dict:
        """The effective STD configuration, read-only. Secrets appear as `***`; `sources` says whether each value came from env, file or default."""
        return client.request("GET", "/config")

    # ---- write tools --------------------------------------------------------

    @write_tool
    def create_manual_entry(name: str, host: str | None = None, description: str | None = None,
                            group: str | None = None, internalurl: str | None = None,
                            externalurl: str | None = None, icon: str | None = None,
                            sort_priority: int | None = None, locked: bool = False,
                            url_checks: dict | None = None,
                            checks: list[dict] | None = None) -> dict:
        """Add a manual (non-Docker) entry, optionally with checks.

        group: group name; created if missing; omit to leave the entry ungrouped.
        url_checks: settings for the URL checks, e.g.
            {"internal": {"enabled": true, "mode": "body", "interval_seconds": 60}, "external": {"enabled": false}}
            mode is `status` (HTTP status below 400 is up) or `body` (the body must be `OK`; anything else is down and `Error: <msg>` shows <msg> as the failure message).
        checks: extra service checks, each {target, check_type (http|tcp|ping), name, mode, interval_seconds, timeout_seconds, verify_tls, enabled}, e.g.
            [{"target": "nas.lan", "check_type": "ping"}, {"target": "http://nas.lan:5000/health", "mode": "body", "interval_seconds": 60}]
            tcp targets are `host:port`.
        """
        body = _drop_none(name=name, host=host, description=description, group=group,
                          internalurl=internalurl, externalurl=externalurl, icon=icon,
                          sort_priority=sort_priority, url_checks=url_checks, checks=checks)
        body["locked"] = locked
        return client.request("POST", "/entries", json=body)

    @write_tool
    def update_entry(entry_id: int, fields: dict) -> dict:
        """Edit an entry. `fields` names only what changes; a field left out is untouched and a field set to null clears it.

        Allowed: name, host (manual entries only), description, group (group name; null ungroups), internalurl, externalurl, icon, sort_priority, locked.
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
                  enabled: bool = True) -> dict:
        """Add a service check to an entry.

        check_type: http (target is a URL), tcp (target is `host:port`) or ping (target is a host).
        mode (http only): `status` (default; up when the HTTP status is below 400) or `body` (up only when the response body is exactly `OK`; a body like `Error: disk full` is down and shows `disk full` as the message).
        interval_seconds 30..86400 and timeout_seconds 1..60; omit for the global defaults.
        """
        body = _drop_none(target=target, check_type=check_type, name=name, mode=mode,
                          interval_seconds=interval_seconds, timeout_seconds=timeout_seconds)
        body.update(verify_tls=verify_tls, enabled=enabled)
        return client.request("POST", f"/entries/{entry_id}/checks", json=body)

    @write_tool
    def update_check(check_id: int, fields: dict) -> dict:
        """Edit or enable/disable a check. `fields` names only what changes (null clears where that makes sense).

        Allowed: enabled, name, check_type, target, mode, interval_seconds, timeout_seconds, verify_tls.
        URL checks (internal/external) accept enabled, mode, interval_seconds, timeout_seconds and verify_tls; container checks accept enabled and interval_seconds; service checks accept everything.
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
    print(f"std-mcp: connected to {url} as key {who['name']!r} ({who['scope']})", file=sys.stderr)
    build_server(client, who["scope"]).run(transport="stdio")


if __name__ == "__main__":
    main()
