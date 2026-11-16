"""The stdio MCP server in mcp/std_mcp.py (v0.8.0, PRD 14.7).

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

from tests.test_mgmt_api_keys import _key

# httpx and mcp come from mcp/requirements.txt (pulled in by requirements-dev.txt),
# so a missing install fails the suite loudly instead of silently skipping.

_PATH = Path(__file__).resolve().parent.parent / "mcp" / "std_mcp.py"
_spec = importlib.util.spec_from_file_location("std_mcp", _PATH)
std_mcp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(std_mcp)

READ_TOOLS = {
    "list_entries", "get_entry", "health_summary", "get_health_history", "list_groups",
    "list_widgets", "list_widget_types", "get_exposure_settings", "get_config",
}
WRITE_TOOLS = {
    "create_manual_entry", "update_entry", "delete_entry", "restore_entry", "add_check",
    "update_check", "delete_check", "run_checks", "upsert_group", "set_widget",
    "remove_widget", "set_exposure_settings",
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
    "create_manual_entry": (
        {"name": "NAS", "group": "Storage", "internalurl": "http://nas.lan:5000",
         "checks": [{"target": "nas.lan", "check_type": "ping"}]},
        "POST", "/api/v1/entries", {},
        {"name": "NAS", "group": "Storage", "internalurl": "http://nas.lan:5000", "locked": False,
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
    out = asyncio.run(server.call_tool(name, args or {}))
    return json.loads(out[0].text)


def tool_names(server):
    return {t.name for t in asyncio.run(server.list_tools())}


# --- registration and scope gating ----------------------------------------------


def test_write_key_registers_every_tool():
    server = std_mcp.build_server(Fake().client(), "write")
    assert tool_names(server) == READ_TOOLS | WRITE_TOOLS


def test_read_key_registers_only_read_tools():
    server = std_mcp.build_server(Fake().client(), "read")
    assert tool_names(server) == READ_TOOLS


def test_calls_table_covers_every_tool():
    assert set(CALLS) == (READ_TOOLS | WRITE_TOOLS) - {"upsert_group"}


def test_every_tool_has_a_description():
    server = std_mcp.build_server(Fake().client(), "write")
    for tool in asyncio.run(server.list_tools()):
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
