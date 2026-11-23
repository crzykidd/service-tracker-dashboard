"""The stdio MCP server in mcp/std_mcp.py (PRD 14.7, 15.7).

The server is an HTTP client of the management API and imports nothing from the
app, so most tests run it against an httpx MockTransport (no network). Two tests
bridge it to the real Flask app with httpx.WSGITransport, and one checks every
(method, path) a tool uses against `/api/v1/openapi.json`.

mcp/ has no __init__.py on purpose (a package named `mcp` would shadow the SDK),
so the module is loaded from its path.
"""

import asyncio
import importlib.util
import json
import re
from pathlib import Path

import httpx
import pytest
from mcp.client import Client
from mcp.server.mcpserver.exceptions import ToolError

from api_version import API_REVISION
from tests.test_mgmt_api_keys import _key

# httpx and mcp come from mcp/requirements.txt (pulled in by requirements-dev.txt),
# so a missing install fails the suite loudly instead of silently skipping.

_PATH = Path(__file__).resolve().parent.parent / "mcp" / "std_mcp.py"
_spec = importlib.util.spec_from_file_location("std_mcp", _PATH)
std_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(std_mcp)

READ_TOOLS = {
    "list_entries", "get_entry", "health_summary", "get_health_history", "list_groups",
    "list_widgets", "list_widget_types", "get_exposure_settings", "get_config", "server_info",
    "list_notification_channels", "get_notification_channel", "list_notification_previous_bases",
    "list_streams", "get_stream", "preview_stream", "list_stream_blocks", "list_stream_offers",
    "list_stream_unmatched_items", "backup_settings", "list_backups", "export_config",
    "list_image_updates", "list_ports",
}
WRITE_TOOLS = {
    "create_manual_entry", "update_entry", "delete_entry", "restore_entry", "add_check",
    "update_check", "delete_check", "run_checks", "upsert_group", "set_widget",
    "remove_widget", "set_exposure_settings", "test_notification_channel",
    "purge_notification_channel", "purge_entry_notifications", "purge_stream_notifications",
    "delete_notification_channel", "update_notification_channel", "scan_notification_orphans",
    "clear_notification_orphans", "update_stream", "enable_stream", "disable_stream", "ignore_stream", "delete_stream",
    "unblock_stream_key", "answer_link_offer", "link_entry_to_stream_item",
    "apply_stream_default_checks", "unlink_entry", "run_backup", "import_plan", "import_apply",
    "run_image_update_check",
}

# tool name -> (arguments, expected method, expected path, expected query, expected body)
CALLS = {
    "list_entries": ({"status": "failing", "q": "nas", "limit": 10}, "GET", "/api/v1/entries",
                     {"status": "failing", "source": "all", "q": "nas", "limit": "10", "offset": "0"}, None),
    "get_entry": ({"entry_id": 7}, "GET", "/api/v1/entries/7", {}, None),
    "health_summary": ({}, "GET", "/api/v1/health/summary", {}, None),
    "get_health_history": ({"entry_id": 7, "range": "7d"}, "GET", "/api/v1/entries/7/health", {"range": "7d"}, None),
    "list_groups": ({}, "GET", "/api/v1/groups", {"limit": "200", "offset": "0"}, None),
    "list_widgets": ({}, "GET", "/api/v1/widgets", {"limit": "200", "offset": "0"}, None),
    "list_widget_types": ({}, "GET", "/api/v1/widgets/types", {}, None),
    "get_exposure_settings": ({}, "GET", "/api/v1/settings/exposure", {}, None),
    "get_config": ({}, "GET", "/api/v1/config", {}, None),
    "backup_settings": ({}, "GET", "/api/v1/settings/backup", {}, None),
    "list_backups": ({}, "GET", "/api/v1/backups", {}, None),
    "list_image_updates": ({"state": "update"}, "GET", "/api/v1/image-updates",
                           {"state": "update", "limit": "200", "offset": "0"}, None),
    "list_ports": ({"kind": "published", "query": "web", "conflicts_only": True}, "GET", "/api/v1/ports",
                   {"kind": "published", "q": "web", "conflicts": "true"}, None),
    "run_image_update_check": ({"entry_id": 7}, "POST", "/api/v1/image-updates/run", {}, {"entry_id": 7}),
    "export_config": ({}, "GET", "/api/v1/export", {"format": "json"}, None),
    "run_backup": ({"kind": "export"}, "POST", "/api/v1/backups/run", {}, {"kind": "export"}),
    "import_plan": ({"document_text": "a: 1"}, "POST", "/api/v1/import/plan", {}, {"document_text": "a: 1"}),
    "import_apply": ({"document_text": "a: 1", "stream_map": None, "selection": {"r": {"apply": True}},
                      "mode": "fill", "fingerprint": "f"}, "POST", "/api/v1/import/apply", {},
                     {"document_text": "a: 1", "selection": {"r": {"apply": True}}, "mode": "fill",
                      "fingerprint": "f"}),
    "list_notification_channels": ({}, "GET", "/api/v1/notifications/channels",
                                   {"limit": "200", "offset": "0"}, None),
    "get_notification_channel": ({"channel_id": 4}, "GET", "/api/v1/notifications/channels/4", {}, None),
    "test_notification_channel": ({"channel_id": 4}, "POST", "/api/v1/notifications/channels/4/test", {}, None),
    "purge_notification_channel": ({"channel_id": 4, "republish": False}, "POST",
                                   "/api/v1/notifications/channels/4/purge", {}, {"republish": False}),
    "purge_entry_notifications": ({"entry_id": 7}, "POST", "/api/v1/entries/7/notifications/purge",
                                  {}, None),
    "purge_stream_notifications": ({"stream_id": "dhcp"}, "POST",
                                   "/api/v1/streams/dhcp/notifications/purge", {}, None),
    "delete_notification_channel": ({"channel_id": 4, "cleanup": False}, "DELETE",
                                    "/api/v1/notifications/channels/4", {"cleanup": "false"}, None),
    "update_notification_channel": ({"channel_id": 4, "fields": {"config": {"base_topic": "std2"}},
                                     "cleanup": True}, "PATCH", "/api/v1/notifications/channels/4", {},
                                    {"config": {"base_topic": "std2"}, "cleanup": True}),
    "scan_notification_orphans": ({"channel_id": 4, "extra_base": "old/std"}, "POST",
                                  "/api/v1/notifications/channels/4/orphans/scan", {},
                                  {"extra_base": "old/std"}),
    "clear_notification_orphans": ({"channel_id": 4, "topics": ["std/entry/9/state"]}, "POST",
                                   "/api/v1/notifications/channels/4/orphans/clear", {},
                                   {"topics": ["std/entry/9/state"]}),
    "list_notification_previous_bases": ({"channel_id": 4}, "GET",
                                         "/api/v1/notifications/channels/4/previous-bases", {}, None),
    "list_streams": ({}, "GET", "/api/v1/streams", {"limit": "200", "offset": "0"}, None),
    "get_stream": ({"stream_id": "dhcp"}, "GET", "/api/v1/streams/dhcp", {}, None),
    "preview_stream": ({"stream_id": "dhcp"}, "GET", "/api/v1/streams/dhcp/preview", {}, None),
    "list_stream_blocks": ({"stream_id": "dhcp"}, "GET", "/api/v1/streams/dhcp/blocks",
                           {"limit": "200", "offset": "0"}, None),
    "list_stream_offers": ({"stream_id": "dhcp"}, "GET", "/api/v1/streams/dhcp/offers",
                           {"limit": "200", "offset": "0"}, None),
    "list_stream_unmatched_items": ({"stream_id": "dhcp"}, "GET", "/api/v1/streams/dhcp/unmatched",
                                    {"limit": "200", "offset": "0"}, None),
    "update_stream": ({"stream_id": "dhcp", "fields": {"network_exclude": ["Guest"]}},
                      "PATCH", "/api/v1/streams/dhcp", {}, {"network_exclude": ["Guest"]}),
    "apply_stream_default_checks": ({"stream_id": "dhcp"}, "POST",
                                    "/api/v1/streams/dhcp/default-checks/apply", {}, None),
    "enable_stream": ({"stream_id": "dhcp"}, "POST", "/api/v1/streams/dhcp/enable", {}, None),
    "disable_stream": ({"stream_id": "dhcp", "cleanup": "purge", "clear_blocks": True},
                       "POST", "/api/v1/streams/dhcp/disable", {},
                       {"cleanup": "purge", "clear_blocks": True}),
    "ignore_stream": ({"stream_id": "dhcp"}, "POST", "/api/v1/streams/dhcp/ignore", {}, None),
    "delete_stream": ({"stream_id": "dhcp", "cleanup": "soft_delete"}, "DELETE", "/api/v1/streams/dhcp",
                      {"cleanup": "soft_delete"}, None),
    "unblock_stream_key": ({"stream_id": "dhcp", "block_id": 5}, "DELETE", "/api/v1/streams/dhcp/blocks/5",
                           {}, None),
    "answer_link_offer": ({"stream_id": "dhcp", "offer_id": 2, "accept": False}, "POST",
                          "/api/v1/streams/dhcp/offers/2/decline", {}, None),
    "link_entry_to_stream_item": ({"stream_id": "dhcp", "entry_id": 7, "key": "aa:bb:cc:dd:ee:ff"},
                                  "POST", "/api/v1/streams/dhcp/link", {},
                                  {"entry_id": 7, "key": "aa:bb:cc:dd:ee:ff"}),
    "unlink_entry": ({"entry_id": 7, "block": True}, "POST", "/api/v1/entries/7/unlink", {},
                     {"block": True}),
    "create_manual_entry": (
        {"name": "NAS", "group": "Storage", "internalurl": "http://nas.lan:5000",
         "checks": [{"target": "nas.lan", "check_type": "ping"}]},
        "POST", "/api/v1/entries", {},
        {"name": "NAS", "group": "Storage", "internalurl": "http://nas.lan:5000", "locked": False, "ha_publish": False,
         "checks": [{"target": "nas.lan", "check_type": "ping"}]}),
    "update_entry": ({"entry_id": 7, "fields": {"externalurl": None, "description": "x"}},
                     "PATCH", "/api/v1/entries/7", {}, {"externalurl": None, "description": "x"}),
    "delete_entry": ({"entry_id": 7}, "DELETE", "/api/v1/entries/7", {}, None),
    "restore_entry": ({"entry_id": 7}, "POST", "/api/v1/entries/7/restore", {}, None),
    "add_check": ({"entry_id": 7, "target": "http://a/health", "mode": "body", "interval_seconds": 60},
                  "POST", "/api/v1/entries/7/checks", {},
                  {"target": "http://a/health", "check_type": "http", "mode": "body",
                   "interval_seconds": 60, "verify_tls": True, "enabled": True}),
    "update_check": ({"check_id": 3, "fields": {"enabled": False}},
                     "PATCH", "/api/v1/checks/3", {}, {"enabled": False}),
    "delete_check": ({"check_id": 3}, "DELETE", "/api/v1/checks/3", {}, None),
    "run_checks": ({"entry_id": 7}, "POST", "/api/v1/entries/7/checks/run", {}, None),
    "set_widget": ({"entry_id": 7, "type": "sonarr", "url": "http://s", "fields": ["queue"],
                    "widget_api_key": "k"},
                   "PUT", "/api/v1/entries/7/widget", {},
                   {"type": "sonarr", "url": "http://s", "fields": ["queue"], "widget_api_key": "k"}),
    "remove_widget": ({"entry_id": 7, "delete": True}, "DELETE", "/api/v1/entries/7/widget",
                      {"delete": "true"}, None),
    "set_exposure_settings": ({"layer_directions": {"lan": "internal"}},
                              "PUT", "/api/v1/settings/exposure", {},
                              {"layer_directions": {"lan": "internal"}, "host_overrides": {}}),
}


class Fake:
    """Records requests; answers from `replies` (callable) or `{}` with 200."""

    def __init__(self, replies=None):
        self.requests = []
        self.replies = replies

    def __call__(self, request):
        self.requests.append(request)
        if self.replies:
            reply = self.replies(request)
            if reply is not None:
                return reply
        return httpx.Response(200, json={})

    def client(self):
        return std_mcp.StdClient("http://std.test", "secret-key", transport=httpx.MockTransport(self))


def call(server, name, args=None):
    """Run a tool; the result is the JSON the server put in its text content."""

    async def run():
        async with Client(server) as client:
            return await client.call_tool(name, args or {})

    result = asyncio.run(run())
    text = result.content[0].text
    if result.is_error:
        # The 1.x server raised the tool's error; keep that contract for the assertions.
        raise ToolError(text)
    return json.loads(text)


def list_tools(server):
    async def run():
        async with Client(server) as client:
            return (await client.list_tools()).tools

    return asyncio.run(run())


def tool_names(server):
    return {t.name for t in list_tools(server)}


# --- registration and scope gating ----------------------------------------------


def test_write_key_registers_every_tool():
    server = std_mcp.build_server(Fake().client(), "write")
    assert tool_names(server) == READ_TOOLS | WRITE_TOOLS


def test_read_key_registers_only_read_tools():
    server = std_mcp.build_server(Fake().client(), "read")
    assert tool_names(server) == READ_TOOLS


def test_calls_table_covers_every_tool():
    assert set(CALLS) == (READ_TOOLS | WRITE_TOOLS) - {"upsert_group", "server_info"}


def test_every_tool_has_a_description():
    server = std_mcp.build_server(Fake().client(), "write")
    for tool in list_tools(server):
        assert tool.description and len(tool.description) > 20, tool.name


# --- method, path, query and body -------------------------------------------------


@pytest.mark.parametrize("name", sorted(CALLS))
def test_tool_maps_to_method_path_and_body(name):
    args, method, path, query, body = CALLS[name]
    fake = Fake()
    call(std_mcp.build_server(fake.client(), "write"), name, args)
    assert len(fake.requests) == 1
    req = fake.requests[0]
    assert (req.method, req.url.path) == (method, path)
    assert dict(req.url.params) == query
    assert req.headers["authorization"] == "Bearer secret-key"
    assert (json.loads(req.content) if req.content else None) == body


def test_delete_entry_permanent_flag_and_default():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    call(server, "delete_entry", {"entry_id": 4, "permanent": True})
    assert dict(fake.requests[0].url.params) == {"permanent": "true"}


def test_set_widget_key_semantics():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    base = {"entry_id": 1, "type": "t", "url": "http://u", "fields": ["a"]}
    call(server, "set_widget", base)
    call(server, "set_widget", {**base, "clear_api_key": True})
    assert "widget_api_key" not in json.loads(fake.requests[0].content)      # omitted: keep
    assert json.loads(fake.requests[1].content)["widget_api_key"] is None    # null: clear
    with pytest.raises(Exception, match="not both"):
        call(server, "set_widget", {**base, "widget_api_key": "k", "clear_api_key": True})


def test_update_tools_reject_unknown_and_empty_fields_without_a_request():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    with pytest.raises(Exception, match="Unknown entry field"):
        call(server, "update_entry", {"entry_id": 1, "fields": {"bogus": 1}})
    with pytest.raises(Exception, match="non-empty"):
        call(server, "update_check", {"check_id": 1, "fields": {}})
    assert fake.requests == []


# --- upsert_group (client-side over list/create/patch) ----------------------------


def _groups_reply(items):
    def reply(request):
        if request.method == "GET":
            return httpx.Response(200, json={"items": items, "total": len(items), "limit": 1000, "offset": 0})
        return httpx.Response(200, json={"id": 9, "name": "echo"})
    return reply


def test_upsert_group_creates_when_missing():
    fake = Fake(_groups_reply([{"id": 1, "name": "Other"}]))
    out = call(std_mcp.build_server(fake.client(), "write"), "upsert_group", {"name": "Media", "icon": "film.png"})
    assert [(r.method, r.url.path) for r in fake.requests] == [("GET", "/api/v1/groups"), ("POST", "/api/v1/groups")]
    assert json.loads(fake.requests[1].content) == {"name": "Media", "icon": "film.png"}
    assert "created" in str(out)


def test_upsert_group_patches_only_given_fields_when_present():
    fake = Fake(_groups_reply([{"id": 4, "name": "Media"}]))
    call(std_mcp.build_server(fake.client(), "write"), "upsert_group", {"name": "Media", "sort_priority": 2})
    assert (fake.requests[1].method, fake.requests[1].url.path) == ("PATCH", "/api/v1/groups/4")
    assert json.loads(fake.requests[1].content) == {"sort_priority": 2}


def test_upsert_group_rename_and_noop():
    fake = Fake(_groups_reply([{"id": 4, "name": "Media"}]))
    server = std_mcp.build_server(fake.client(), "write")
    call(server, "upsert_group", {"name": "Media", "new_name": "Movies"})
    assert json.loads(fake.requests[1].content) == {"name": "Movies"}
    fake.requests.clear()
    assert "unchanged" in str(call(server, "upsert_group", {"name": "Media"}))
    assert [r.method for r in fake.requests] == ["GET"]
    with pytest.raises(Exception, match="does not exist"):
        call(server, "upsert_group", {"name": "Nope", "new_name": "X"})


# --- error mapping ----------------------------------------------------------------


def _err(status, body):
    return Fake(lambda r: httpx.Response(status, json=body))


def test_api_error_keeps_message_and_details():
    details = [{"loc": ["target"], "msg": "Field required", "type": "missing"}]
    fake = _err(400, {"error": "Validation failed", "details": details})
    with pytest.raises(Exception) as exc:
        call(std_mcp.build_server(fake.client(), "write"), "add_check", {"entry_id": 1, "target": "x"})
    text = str(exc.value)
    assert "HTTP 400" in text and "Validation failed" in text and "Field required" in text


@pytest.mark.parametrize("status,word", [(401, "API key"), (403, "scope"), (404, "not found"), (409, "conflicts")])
def test_status_codes_are_readable(status, word):
    fake = _err(status, {"error": "boom", "details": None})
    with pytest.raises(Exception) as exc:
        call(std_mcp.build_server(fake.client(), "write"), "get_entry", {"entry_id": 1})
    assert f"HTTP {status}" in str(exc.value) and word in str(exc.value) and "boom" in str(exc.value)


def test_network_failure_is_a_readable_error():
    def boom(request):
        raise httpx.ConnectError("refused")
    client = std_mcp.StdClient("http://std.test", "k", transport=httpx.MockTransport(boom))
    with pytest.raises(Exception, match="Cannot reach STD"):
        call(std_mcp.build_server(client, "read"), "get_config")


def test_non_json_error_body_is_still_reported():
    fake = Fake(lambda r: httpx.Response(502, text="<html>bad gateway</html>"))
    with pytest.raises(Exception, match="HTTP 502"):
        call(std_mcp.build_server(fake.client(), "read"), "get_config")


def test_unexpected_scope_is_refused():
    with pytest.raises(ValueError):
        std_mcp.build_server(Fake().client(), "admin")


# --- against the real API ---------------------------------------------------------


def _spec_matcher(spec):
    ops = []
    for path, item in spec["paths"].items():
        rx = re.compile("^/api/v1" + re.sub(r"\{[^}]+\}", "[^/]+", path) + "$")
        ops.extend((method.upper(), rx) for method in item)
    return lambda method, url_path: any(m == method and rx.match(url_path) for m, rx in ops)


def test_every_tool_endpoint_exists_in_the_openapi_spec(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    exists = _spec_matcher(spec)
    fake = Fake(lambda r: httpx.Response(200, json={"items": [], "total": 0, "limit": 1, "offset": 0}))
    server = std_mcp.build_server(fake.client(), "write")
    for name, (args, *_rest) in CALLS.items():
        call(server, name, args)
    call(server, "upsert_group", {"name": "G"})
    assert len(fake.requests) == len(CALLS) + 2
    for req in fake.requests:
        assert exists(req.method, req.url.path), (req.method, req.url.path)


def _live_client(app, scope):
    _, secret = _key(app, f"mcp-{scope}", scope)
    return std_mcp.StdClient("http://std.test", secret, transport=httpx.WSGITransport(app=app))


def test_whoami_scope_drives_the_tool_set_against_the_real_app(app):
    for scope, expected in (("read", READ_TOOLS), ("write", READ_TOOLS | WRITE_TOOLS)):
        client = _live_client(app, scope)
        who = client.request("GET", "/whoami")
        assert who["scope"] == scope
        assert tool_names(std_mcp.build_server(client, who["scope"])) == expected


def test_write_flow_against_the_real_app(app):
    server = std_mcp.build_server(_live_client(app, "write"), "write")
    made = call(server, "create_manual_entry", {
        "name": "NAS", "group": "Storage", "internalurl": "http://nas.lan:5000",
        "url_checks": {"internal": {"enabled": True, "mode": "body", "interval_seconds": 60}},
        "checks": [{"target": "nas.lan", "check_type": "ping"}]})
    eid = made["id"]
    got = call(server, "get_entry", {"entry_id": eid})
    assert got["name"] == "NAS" and got["source"] == "manual"
    modes = {c["kind"]: c["mode"] for c in got["checks"]}
    assert modes.get("internal_url") == "body"
    call(server, "update_entry", {"entry_id": eid, "fields": {"description": "storage box"}})
    call(server, "upsert_group", {"name": "Storage", "sort_priority": 3})
    call(server, "health_summary")
    with pytest.raises(Exception, match="HTTP 409"):
        call(server, "delete_entry", {"entry_id": eid, "permanent": True})   # not soft-deleted yet
    call(server, "delete_entry", {"entry_id": eid})
    call(server, "restore_entry", {"entry_id": eid})


def test_read_key_is_refused_by_the_api_even_without_tool_gating(app):
    # Defence in depth: gating hides the write tools, and the API still refuses the key.
    with pytest.raises(Exception, match="HTTP 403"):
        call(std_mcp.build_server(_live_client(app, "read"), "write"), "delete_check", {"check_id": 1})


# --- install header and version -----------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent


def _inline_metadata():
    """Parse the PEP 723 `# /// script` block at the top of std_mcp.py."""
    m = re.search(r"^# /// script\n((?:#.*\n)+?)# ///$", _PATH.read_text(), re.MULTILINE)
    assert m, "std_mcp.py has no PEP 723 script block"
    body = "\n".join(line[2:] if line.startswith("# ") else line[1:] for line in m.group(1).splitlines())
    import tomllib
    return tomllib.loads(body)


def test_inline_dependencies_equal_requirements_in():
    pins = [ln.strip() for ln in (_ROOT / "mcp" / "requirements.in").read_text().splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")]
    assert pins
    assert sorted(_inline_metadata()["dependencies"]) == sorted(pins)
    assert _inline_metadata()["requires-python"]


def test_mcp_version_is_not_behind_the_repo_version():
    # release-prep sets both to the new version. On dev, between releases, MCP_VERSION may
    # already be the next release (VERSION is still the last shipped one), never behind it.
    repo = std_mcp._parse_semver((_ROOT / "VERSION").read_text().strip())
    mine = std_mcp._parse_semver(std_mcp.MCP_VERSION)
    assert repo and mine and mine >= repo


@pytest.mark.parametrize("std, status, patch_note", [
    ("0.9.0", "match", False),
    ("0.9.7", "match", True),
    ("0.10.1", "std_newer", None),
    ("1.0.0", "std_newer", None),
    ("0.8.0", "std_older", None),
    (None, "std_older", None),
    ("dev", "unknown", None),
    ("0.9", "unknown", None),
    ("0.9.0-rc1", "unknown", None),
])
def test_compare_versions(std, status, patch_note):
    info = std_mcp.compare_versions("0.9.0", std)
    assert info["status"] == status
    assert info["mcp_version"] == "0.9.0" and info["std_version"] == std
    assert info["advice"]
    if patch_note is not None:
        assert ("patch" in info["advice"]) is patch_note


def test_version_notice_lines():
    assert std_mcp.version_notice(std_mcp.compare_versions("0.9.0", "0.9.0")) is None
    assert "patch difference" in std_mcp.version_notice(std_mcp.compare_versions("0.9.0", "0.9.2"))
    assert "update std_mcp.py" in std_mcp.version_notice(std_mcp.compare_versions("0.9.0", "0.10.1"))
    assert "older than 0.9.0" in std_mcp.version_notice(std_mcp.compare_versions("0.9.0", None))


def _instructions(info):
    return std_mcp.build_server(Fake().client(), "write", info).instructions


def test_instructions_mention_a_mismatch_only_when_there_is_one():
    for std in ("0.9.0", "0.9.4"):
        assert "Version notice" not in _instructions(std_mcp.compare_versions("0.9.0", std))
    assert "Version notice" not in _instructions(None)
    for std in ("0.10.0", "0.8.0", None, "dev"):
        text = _instructions(std_mcp.compare_versions("0.9.0", std))
        assert "Version notice" in text and "update the MCP server" in text


def _meta_reply(version, revision=3):
    def reply(request):
        if request.url.path == "/api/v1/meta":
            return httpx.Response(200, json={"std_version": version, "api_revision": revision,
                                             "features": ["streams"]})
        return None
    return reply


def _startup(std="0.10.0", revision=2):
    info = std_mcp.compare_versions("0.10.0", std)
    info.update(std_api_revision=revision, checked_at="2026-11-20T08:00:00Z", std_commit="abc")
    return info


def test_server_info_rechecks_with_meta_on_every_call():
    fake = Fake(_meta_reply("0.10.0", 2))
    server = std_mcp.build_server(fake.client(), "read", _startup())
    for _ in range(2):
        out = call(server, "server_info")
        assert out["status"] == "match" and out["std_version"] == "0.10.0"
        assert out["std_version_source"] == "current" and out["current"]["checked"] is True
        assert out["startup"] == {"std_version": "0.10.0", "std_api_revision": 2,
                                  "checked_at": "2026-11-20T08:00:00Z"}
        assert out["restart_advised"] is False and out["update_advised"] is False
        assert out["std_commit"] == "abc"                  # startup facts kept
    assert [r.url.path for r in fake.requests] == ["/api/v1/meta", "/api/v1/meta"]


def test_server_info_advises_restart_and_update_when_std_moved_on():
    server = std_mcp.build_server(Fake(_meta_reply("0.11.0", 3)).client(), "read", _startup())
    out = call(server, "server_info")
    assert out["status"] == "std_newer" and out["std_version"] == "0.11.0"
    assert out["startup"]["std_version"] == "0.10.0" and out["current"]["std_api_revision"] == 3
    assert out["restart_advised"] is True and out["update_advised"] is True
    assert "upgraded from 0.10.0 to 0.11.0" in out["advice"] and "restart the MCP server" in out["advice"]
    assert "stream tools" in out["advice"] and "v0.11.0/mcp/std_mcp.py" in out["advice"]
    assert "git pull" in out["advice"] and "restart the MCP client" in out["advice"]


def test_server_info_restart_only_on_a_patch_upgrade():
    out = call(std_mcp.build_server(Fake(_meta_reply("0.10.1", 2)).client(), "read", _startup()),
               "server_info")
    assert out["status"] == "match" and out["restart_advised"] is True and out["update_advised"] is False
    assert "update the script" not in out["advice"].lower()


def test_server_info_falls_back_to_the_startup_values_when_meta_fails():
    def boom(request):
        raise httpx.ConnectError("refused", request=request)
    out = call(std_mcp.build_server(Fake(boom).client(), "read", _startup("0.11.0")), "server_info")
    assert out["std_version"] == "0.11.0" and out["status"] == "std_newer"
    assert out["std_version_source"] == "as of startup 2026-11-20T08:00:00Z"
    assert out["current"]["checked"] is False and "ConnectError" in out["current"]["error"]
    assert out["update_advised"] is True and "as of startup" in out["advice"]
    out = call(std_mcp.build_server(Fake(lambda r: httpx.Response(500, json={"error": "x"})).client(),
                                    "read", _startup()), "server_info")
    assert out["current"]["checked"] is False and out["std_version"] == "0.10.0"


def test_server_info_without_a_startup_check():
    out = call(std_mcp.build_server(Fake(_meta_reply(std_mcp.MCP_VERSION)).client(), "read"), "server_info")
    assert out["status"] == "match" and out["startup"]["std_version"] is None


def test_meta_uses_a_short_timeout(monkeypatch):
    seen = {}
    client = Fake(_meta_reply("0.10.0")).client()
    real = client._http.get
    monkeypatch.setattr(client._http, "get", lambda path, timeout: seen.update(t=timeout) or real(path))
    client.meta()
    assert seen["t"] == std_mcp.META_TIMEOUT <= 5


def test_instructions_name_the_update_command_when_std_is_newer():
    text = _instructions(std_mcp.compare_versions("0.10.0", "0.11.0"))
    assert "stream tools" in text and "git pull" in text and "v0.11.0/mcp/std_mcp.py" in text


def test_stream_tool_descriptions_name_the_observability_fields():
    tools = {t.name: t.description for t in list_tools(std_mcp.build_server(Fake().client(), "read"))}
    for name in ("list_streams", "get_stream"):
        for field in ("last_snapshot_at", "last_applied_at", "last_item_count", "last_error",
                      "last_rejected_at", "last_rejection", "stale", "effective_interval_seconds",
                      "missing", "missing_expiry_days"):
            assert field in tools[name], (name, field)
    for field in ("stale_streams", "streams_stale", "last_rejection"):
        assert field in tools["health_summary"]


def test_stream_observability_against_the_real_app(app):
    from datetime import datetime, timedelta

    from extensions import db
    from models import InventoryStream
    ingest = _key(app, "sidecar", "ingest")[1]
    body = json.loads((_ROOT / "tests" / "fixtures" / "stream_snapshot.json").read_text())
    body["snapshot_interval_seconds"] = 300
    c = app.test_client()
    assert c.put("/api/v1/streams/dhcp/snapshot", json=body,
                 headers={"Authorization": f"Bearer {ingest}"}).status_code == 202
    with app.app_context():
        s = InventoryStream.query.one()
        s.status = "enabled"
        s.last_snapshot_at = datetime.utcnow() - timedelta(hours=1)
        db.session.commit()
    server = std_mcp.build_server(_live_client(app, "write"), "write")
    streams_out = call(server, "list_streams")
    assert streams_out["stale"] == 1 and streams_out["items"][0]["producer_interval_seconds"] == 300
    assert call(server, "get_stream", {"stream_id": "dhcp"})["stale"] is True
    summary = call(server, "health_summary")
    assert summary["counts"]["streams_stale"] == 1 and summary["stale_streams"][0]["state"] == "down"
    out = call(server, "update_stream", {"stream_id": "dhcp", "fields": {"expected_interval_seconds": 7200,
                                                                        "missing_expiry_days": 30}})
    assert out["stale"] is False and out["missing_expiry_days"] == 30
    info = call(server, "server_info")
    assert info["current"]["checked"] is True and info["std_api_revision"] == API_REVISION


def test_whoami_includes_the_std_version(app):
    who = _live_client(app, "read").request("GET", "/whoami")
    assert who["version"] == app.config["VERSION_INFO"]["version"]


@pytest.mark.parametrize("version", ["99.0.0", "0.8.0", "dev", None])
def test_startup_never_fails_on_a_mismatch(monkeypatch, capsys, version):
    who = {"name": "k", "prefix": "abcd1234", "scope": "write"}
    if version is not None:
        who["version"] = version
    monkeypatch.setenv("STD_URL", "http://std.test")
    monkeypatch.setenv("STD_API_KEY", "secret")
    monkeypatch.setattr(std_mcp.StdClient, "request", lambda self, *a, **k: who)
    ran = []
    monkeypatch.setattr(std_mcp.MCPServer, "run", lambda self, transport: ran.append(self))
    std_mcp.main()
    err = capsys.readouterr().err
    assert ran and "Version notice" in ran[0].instructions
    assert f"std_mcp {std_mcp.MCP_VERSION}" in err and "connected to STD" in err
    assert f"std_mcp {std_mcp.MCP_VERSION} talking to STD" in err


def test_startup_line_when_versions_are_equal(monkeypatch, capsys):
    monkeypatch.setenv("STD_URL", "http://std.test")
    monkeypatch.setenv("STD_API_KEY", "secret")
    monkeypatch.setattr(std_mcp.StdClient, "request", lambda self, *a, **k: {
        "name": "k", "prefix": "p", "scope": "read", "version": std_mcp.MCP_VERSION})
    monkeypatch.setattr(std_mcp.MCPServer, "run", lambda self, transport: None)
    std_mcp.main()
    err = capsys.readouterr().err
    assert f"connected to STD {std_mcp.MCP_VERSION} as key 'k' (read); std_mcp {std_mcp.MCP_VERSION}" in err
    assert "talking to" not in err


# --- backup and export tools (STD API revision 4) -----------------------------------------


def test_run_backup_rejects_an_unknown_kind_without_a_request():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    with pytest.raises(Exception, match="snapshot"):
        call(server, "run_backup", {"kind": "everything"})
    assert fake.requests == []


def test_backup_tools_against_the_real_app(app, tmp_path):
    old = (app.config.get("backup_path"), app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"])
    app.config["backup_path"] = str(tmp_path)
    app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = {}, {}
    try:
        server = std_mcp.build_server(_live_client(app, "write"), "write")
        run = call(server, "run_backup", {"kind": "export"})
        assert run["ok"] is True and run["file"].endswith("-std_export.yml")
        listing = call(server, "list_backups")
        assert [i["name"] for i in listing["items"]] == [run["file"]]
        assert call(server, "backup_settings")["export"]["format"]["value"] == "yaml"
        doc = call(server, "export_config")
        assert doc["format"] == "std-export" and doc["format_version"] == 1
    finally:
        app.config["backup_path"], app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = old


# --- import tools (STD API revision 4, bak-04) ---------------------------------------------------


def test_import_apply_rejects_an_unknown_mode_without_a_request():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    with pytest.raises(Exception, match="fill"):
        call(server, "import_apply", {"document_text": "x", "stream_map": None, "selection": {},
                                      "mode": "everything", "fingerprint": "f"})
    assert fake.requests == []


def test_import_tools_document_the_plan_first_rule():
    server = std_mcp.build_server(Fake().client(), "write")
    tools = {t.name: t for t in list_tools(server)}
    assert "ALWAYS call this first" in tools["import_plan"].description
    assert "import_plan first" in tools["import_apply"].description


def test_import_tools_against_the_real_app(app, register):
    import yaml
    assert register(host="h1", container_name="grafana").status_code == 200
    doc = yaml.safe_dump({"format": "std-export", "format_version": 1, "exported_at": "2026-11-20T00:10:02Z",
                          "std_version": "0.11.0", "api_revision": 4,
                          "entries": [{"kind": "docker", "identity": {"host": "h1", "container_name": "grafana"},
                                       "description": "from the file"}]})
    server = std_mcp.build_server(_live_client(app, "write"), "write")
    plan = call(server, "import_plan", {"document_text": doc})
    assert plan["rows"][0]["status"] == "missing" and plan["default_selection"]
    result = call(server, "import_apply", {"document_text": doc, "stream_map": None,
                                           "selection": plan["default_selection"], "mode": "fill",
                                           "fingerprint": plan["fingerprint"]})
    assert result["counts"]["rows_applied"] == 1
    with pytest.raises(Exception, match="import_plan again"):
        call(server, "import_apply", {"document_text": doc, "stream_map": None,
                                      "selection": plan["default_selection"], "mode": "fill",
                                      "fingerprint": plan["fingerprint"]})
