"""OpenAPI document, route registry and the audit-log view (v0.8.0, PRD 14.5/14.6)."""

import re
from datetime import datetime, timedelta

import pytest

import api_keys
import mgmt_openapi
from extensions import db
from models import ApiAudit

METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


def _mgmt_rules(app):
    for rule in app.url_map.iter_rules():
        if rule.endpoint.startswith("mgmt_api."):
            for method in rule.methods & METHODS:
                yield method, mgmt_openapi.flask_rule_to_path(rule.rule), rule


@pytest.fixture
def spec(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200
    return r.get_json()


# --- spec -----------------------------------------------------------------------


def test_spec_is_public_json(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200 and r.is_json


def test_every_management_rule_is_in_the_spec_and_vice_versa(app, spec):
    from_flask = {(m, p) for m, p, _ in _mgmt_rules(app)}
    from_spec = {(m.upper(), p) for p, item in spec["paths"].items() for m in item}
    assert from_flask == from_spec
    declared = {(op.method, op.path) for op in mgmt_openapi.OPERATIONS}
    assert declared == from_flask
    assert len(declared) == len(mgmt_openapi.OPERATIONS), "an operation is declared twice"
    assert ("GET", "/whoami") in from_spec and ("GET", "/openapi.json") in from_spec


def test_registry_scope_matches_the_decorator(app):
    declared = {(op.method, op.path): op.scope for op in mgmt_openapi.OPERATIONS}
    for method, path, rule in _mgmt_rules(app):
        view = app.view_functions[rule.endpoint]
        assert getattr(view, "required_scope", None) == declared[(method, path)], (method, path)


def test_browser_json_routes_and_register_are_not_in_the_spec(app, spec):
    paths = set(spec["paths"])
    assert "/register" not in paths
    assert not any("delete" in p.split("/")[-1] for p in paths)
    assert "/changelog" not in paths
    # They do exist as routes, just not on the management blueprint.
    rules = {r.rule for r in app.url_map.iter_rules()}
    assert "/api/v1/register" in rules and "/api/v1/changelog" in rules
    assert "register" not in str(spec["info"]["description"]).replace("`/api/v1/register`", "")


def _walk(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "$ref":
                yield v
            else:
                yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def test_spec_structure_and_refs_resolve(spec):
    assert spec["openapi"].startswith("3.1")
    assert spec["info"]["title"] and spec["info"]["version"]
    assert spec["servers"] == [{"url": "/api/v1"}]
    assert spec["components"]["securitySchemes"]["bearerAuth"] == {
        "type": "http", "scheme": "bearer",
        "description": spec["components"]["securitySchemes"]["bearerAuth"]["description"]}
    refs = list(_walk(spec))
    assert refs
    for ref in refs:
        assert ref.startswith("#/components/schemas/"), ref
        assert ref.rsplit("/", 1)[1] in spec["components"]["schemas"], ref
    for path, item in spec["paths"].items():
        assert path.startswith("/")
        for method, op in item.items():
            assert method in {"get", "post", "put", "patch", "delete"}
            assert op["operationId"] and op["summary"] and op["responses"]
            for name in re.findall(r"{(\w+)}", path):
                assert any(p["name"] == name and p["in"] == "path" for p in op["parameters"])
    ids = [op["operationId"] for item in spec["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids))


def test_security_and_scopes_documented(spec):
    ops = {(m, p): op for p, item in spec["paths"].items() for m, op in item.items()}
    assert "security" not in ops[("get", "/openapi.json")]
    assert ops[("get", "/whoami")]["security"] == [{"bearerAuth": []}]
    assert ops[("get", "/entries")]["x-required-scope"] == "read"
    assert ops[("post", "/entries")]["x-required-scope"] == "write"
    assert "401" in ops[("get", "/entries")]["responses"] and "403" in ops[("post", "/entries")]["responses"]
    assert "401" not in ops[("get", "/openapi.json")]["responses"]
    assert "write" in ops[("delete", "/groups/{id}")]["description"]


def test_request_models_query_params_and_responses(spec):
    schemas = spec["components"]["schemas"]
    ops = {(m, p): op for p, item in spec["paths"].items() for m, op in item.items()}
    body = ops[("post", "/entries")]["requestBody"]["content"]["application/json"]["schema"]
    assert body == {"$ref": "#/components/schemas/EntryCreate"}
    assert schemas["EntryCreate"]["additionalProperties"] is False
    for model in ("EntryPatch", "CheckPatch", "GroupPatch", "GroupCreate", "WidgetPut",
                  "ExposureSettingsPut", "ServiceCheckCreate"):
        assert schemas[model]["additionalProperties"] is False
    assert "name" in schemas["EntryPatch"]["properties"]
    assert "required" not in schemas["EntryPatch"]
    # nullable + optional is documented for PATCH.
    assert "absent" in ops[("patch", "/entries/{id}")]["description"]
    q = {p["name"] for p in ops[("get", "/entries")]["parameters"]}
    assert {"limit", "offset", "status", "source", "host", "group", "q",
            "include_deleted", "deleted_only"} <= q
    assert {p["name"] for p in ops[("delete", "/groups/{id}")]["parameters"]} == {"id", "force"}
    assert {p["name"] for p in ops[("delete", "/entries/{id}/widget")]["parameters"]} == {"id", "delete"}
    assert {p["name"] for p in ops[("delete", "/entries/{id}")]["parameters"]} == {"id", "permanent"}
    assert {p["name"] for p in ops[("get", "/entries/{id}/health")]["parameters"]} == {"id", "range"}
    page = ops[("get", "/entries")]["responses"]["200"]["content"]["application/json"]["schema"]
    assert page == {"$ref": "#/components/schemas/PageOfEntryOut"}
    assert schemas["PageOfEntryOut"]["properties"]["items"]["items"] == {"$ref": "#/components/schemas/EntryOut"}
    assert ops[("post", "/entries")]["responses"]["201"]
    assert schemas["ErrorOut"]["required"] == ["error", "details"]


def test_spec_never_contains_a_secret_value(app, spec):
    text = str(spec)
    assert "test-token" not in text


def test_spec_version_follows_the_app(app, spec):
    assert spec["info"]["version"] == str(app.config["VERSION_INFO"].get("version") or "unknown")


# --- JSON 404/405 for unmatched /api/v1 URLs --------------------------------------


def test_unmatched_api_v1_json_for_api_clients(app, client):
    _, full = _make_key(app)
    h = {"Authorization": f"Bearer {full}"}
    r = client.get("/api/v1/nope", headers=h)
    assert r.status_code == 404 and r.get_json()["error"] == "Not found"
    r = client.get("/api/v1/nope", headers={"Accept": "application/json"})
    assert r.status_code == 404 and r.is_json
    r = client.put("/api/v1/health/summary", headers=h)
    assert r.status_code == 405 and r.get_json()["error"] == "Method not allowed"
    assert "GET" in r.headers["Allow"]


def test_unmatched_urls_stay_html_for_browsers_and_other_paths(client):
    r = client.get("/api/v1/nope")
    assert r.status_code == 404 and not r.is_json
    r = client.get("/nope", headers={"Authorization": "Bearer x", "Accept": "application/json"})
    assert r.status_code == 404 and not r.is_json
    # register keeps its own behaviour (a wrong method is Flask's 405 page).
    r = client.get("/api/v1/register")
    assert r.status_code == 405 and not r.is_json


def _make_key(app, name="spec-key", scope="read"):
    with app.app_context():
        key, full = api_keys.create_key(name, scope)
        return key.id, full


# --- audit view ---------------------------------------------------------------------


def _audit(app, n=1, key="agent", **kw):
    with app.app_context():
        for i in range(n):
            db.session.add(ApiAudit(
                ts=kw.get("ts", datetime.utcnow()) - timedelta(seconds=i), key_name=key,
                method=kw.get("method", "PATCH"), path=kw.get("path", f"/api/v1/entries/{i}"),
                object_type=kw.get("object_type", "entry"), object_id=str(i),
                status_code=kw.get("status_code", 200), changes=kw.get("changes", {"description": ["a", "b"]})))
        db.session.commit()


def _api_page(client, **query):
    return client.get("/settings", query_string={"section": "api", **query}).get_data(as_text=True)


def test_audit_view_requires_admin(client, admin_client):
    r = client.get("/settings?section=api")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_audit_view_renders_rows(app, admin_client):
    _audit(app, 2, key="agent", changes={"description": ["old text", "new text"], "locked": [False, True]})
    html = _api_page(admin_client)
    assert 'id="api-audit-table"' in html
    assert "agent" in html and "PATCH" in html and "/api/v1/entries/0" in html
    assert "description: old text -&gt; new text" in html
    assert "locked: false -&gt; true" in html
    assert "entry #1" in html


def test_audit_view_empty_state(admin_client):
    assert "No API writes recorded" in _api_page(admin_client)


def test_audit_view_filter_by_key(app, admin_client):
    _audit(app, 1, key="alpha", path="/api/v1/groups/1")
    _audit(app, 1, key="beta", path="/api/v1/widgets/9")
    both = _api_page(admin_client)
    assert "/api/v1/groups/1" in both and "/api/v1/widgets/9" in both
    only = _api_page(admin_client, audit_key="alpha")
    assert "/api/v1/groups/1" in only and "/api/v1/widgets/9" not in only
    assert '<option value="alpha" selected>' in only
    none = _api_page(admin_client, audit_key="ghost")
    assert "No API writes recorded for this key" in none


def test_audit_view_shows_latest_200_newest_first(app, admin_client):
    _audit(app, 205)
    html = _api_page(admin_client)
    table = html[html.index('id="api-audit-table"'):]
    assert table.count("<code>/api/v1/entries/") == 200
    assert "/api/v1/entries/0<" in table and "/api/v1/entries/204<" not in table


def test_audit_view_escapes_changes_and_masks_secrets(app, admin_client):
    evil = '<script>alert(1)</script>'
    _audit(app, 1, key="<b>k</b>", path='/api/v1/x"><img src=x>',
           changes={"description": [evil, '"><img src=x onerror=1>'], "widget_api_key": ["***", "***"]})
    html = _api_page(admin_client)
    assert evil not in html and "<img src=x" not in html and "<b>k</b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "widget_api_key: *** -&gt; ***" in html


def test_audit_view_end_to_end_masks_a_real_write(app, admin_client, client):
    _, full = _make_key(app, "writer", "write")
    r = client.post("/api/v1/groups", json={"name": "G<x>"}, headers={"Authorization": f"Bearer {full}"})
    assert r.status_code == 201
    html = _api_page(admin_client, audit_key="writer")
    assert "POST" in html and "group" in html and "G&lt;x&gt;" in html and "G<x>" not in html


# --- README ---------------------------------------------------------------------------


def test_readme_endpoint_table_matches_the_registry():
    import os

    readme = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"),
                  encoding="utf-8").read()
    for op in mgmt_openapi.OPERATIONS:
        row = f"| {op.method} | `/api/v1{op.path}` | {op.scope or 'none'} |"
        assert row in readme, f"README endpoint table is missing: {row}"
