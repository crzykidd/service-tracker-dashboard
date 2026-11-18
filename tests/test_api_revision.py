"""API revision headers, GET /api/v1/meta, and once-per-User-Agent register logging (PRD 18.1)."""

import logging

import pytest

import api_keys
import routes_api
from api_version import API_REVISION, FEATURES
from extensions import db


def _key(app, scope="read"):
    with app.app_context():
        _, token = api_keys.create_key("rev", scope)
        db.session.commit()
    return {"Authorization": f"Bearer {token}"}


def _has_headers(resp, app):
    assert resp.headers["X-STD-API-Revision"] == str(API_REVISION)
    assert resp.headers["X-STD-Version"] == app.config["VERSION_INFO"]["version"]


def test_meta_is_public_and_complete(client, app):
    r = client.get("/api/v1/meta")
    assert r.status_code == 200
    assert r.get_json() == {"std_version": app.config["VERSION_INFO"]["version"],
                            "api_revision": API_REVISION, "features": list(FEATURES)}
    _has_headers(r, app)


def test_meta_is_in_the_spec_without_security(client):
    op = client.get("/api/v1/openapi.json").get_json()["paths"]["/meta"]["get"]
    assert "security" not in op


@pytest.mark.parametrize("method,path,headers", [
    ("post", "/api/v1/register", {}),                               # 401
    ("post", "/api/v1/register", {"Authorization": "Bearer test-token"}),  # 400 (no body)
    ("get", "/api/v1/whoami", {}),                                   # 401
    ("get", "/api/v1/nope", {"Accept": "application/json"}),         # 404 JSON
    ("get", "/api/v1/register", {"Accept": "application/json"}),     # 405
])
def test_headers_on_error_responses(client, app, method, path, headers):
    r = getattr(client, method)(path, headers=headers)
    assert r.status_code >= 400
    _has_headers(r, app)


def test_headers_on_success_and_403(client, app, register):
    _has_headers(register(), app)
    read = _key(app, "read")
    _has_headers(client.get("/api/v1/whoami", headers=read), app)
    r = client.post("/api/v1/groups", json={"name": "x"}, headers=read)
    assert r.status_code == 403
    _has_headers(r, app)


def test_no_headers_outside_api(client):
    assert "X-STD-API-Revision" not in client.get("/login").headers


def test_whoami_and_openapi_carry_the_revision(client, app):
    assert client.get("/api/v1/whoami", headers=_key(app)).get_json()["api_revision"] == API_REVISION
    spec = client.get("/api/v1/openapi.json").get_json()
    assert spec["info"]["x-api-revision"] == API_REVISION


def test_register_logs_each_user_agent_once(client, auth_headers, caplog):
    routes_api._SEEN_UAS.clear()
    body = {"host": "h", "container_name": "c"}
    with caplog.at_level(logging.INFO, logger="routes_api"):
        for _ in range(3):
            client.post("/api/v1/register", json=body, headers={**auth_headers, "User-Agent": "nt/1.2"})
        client.post("/api/v1/register", json=body, headers={**auth_headers, "User-Agent": "other/2"})
    lines = [r.getMessage() for r in caplog.records if "Register client seen" in r.getMessage()]
    assert len(lines) == 2 and "nt/1.2" in lines[0] and "other/2" in lines[1]
    assert not any("test-token" in r.getMessage() for r in caplog.records)


def test_user_agent_set_is_capped(client, auth_headers):
    routes_api._SEEN_UAS.clear()
    routes_api._SEEN_UAS.update(str(i) for i in range(routes_api._SEEN_UAS_MAX))
    client.post("/api/v1/register", json={"host": "h", "container_name": "c"},
                headers={**auth_headers, "User-Agent": "late/1"})
    assert len(routes_api._SEEN_UAS) == routes_api._SEEN_UAS_MAX
    assert "late/1" not in routes_api._SEEN_UAS
    routes_api._SEEN_UAS.clear()
