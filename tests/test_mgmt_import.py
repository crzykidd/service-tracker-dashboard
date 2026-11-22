"""Management API: POST /import/plan and /import/apply (API revision 4, bak-04)."""

import json

import pytest
import yaml

import mgmt_openapi
from api_version import API_REVISION, API_REVISION_HISTORY, FEATURES
from extensions import db
from models import ServiceEntry, User
from tests.test_import_engine import docker_rec, minimal
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_mgmt_entries import _audit


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "reader", "read")[1])


def _doc():
    return minimal(
        entries=[docker_rec("grafana", description="from file"), docker_rec("sonarr", description="theirs"),
                 docker_rec("ghost", description="not here")],
        users=[{"username": "carol", "email": "carol@example.com", "is_admin": False, "is_active": True}])


@pytest.fixture
def local(app, register):
    assert register(host="h1", container_name="grafana").status_code == 200
    assert register(host="h1", container_name="sonarr").status_code == 200
    with app.app_context():
        ServiceEntry.query.filter_by(container_name="sonarr").one().description = "mine"
        db.session.commit()


def _plan(client, key, **body):
    return client.post("/api/v1/import/plan", headers=key, json={"document": _doc(), **body})


# --- revision, spec and scopes -------------------------------------------------------------------


def test_revision_row_text_and_feature():
    assert API_REVISION >= 5         # 5 is the image_repo_url addition, 6 the ports route
    row = [r for r in API_REVISION_HISTORY if r[0] == 4][0]
    assert row[:2] == (4, "0.11.0") and "import" in row[2]
    assert "import" in FEATURES and len([r for r in API_REVISION_HISTORY if r[0] == 4]) == 1


def test_routes_are_declared_with_write_scope():
    ops = {(o.method, o.path): o.scope for o in mgmt_openapi.OPERATIONS}
    assert ops[("POST", "/import/plan")] == "write" and ops[("POST", "/import/apply")] == "write"


def test_a_read_key_is_refused(client, rkey, local):
    assert _plan(client, rkey).status_code == 403
    body = {"document": _doc(), "selection": {}, "fingerprint": "x"}
    assert client.post("/api/v1/import/apply", headers=rkey, json=body).status_code == 403
    assert client.post("/api/v1/import/plan", json={"document": _doc()}).status_code == 401


# --- plan -------------------------------------------------------------------------------------------


def test_plan_describes_every_row_and_writes_nothing(app, client, wkey, local):
    r = _plan(client, wkey)
    assert r.status_code == 200, r.get_json()
    plan = r.get_json()
    by = {row["rid"]: row for row in plan["rows"]}
    assert by["entry:docker:h1/grafana"]["status"] == "missing"
    assert by["entry:docker:h1/sonarr"]["status"] == "differs"
    assert by["entry:docker:h1/ghost"]["status"] == "not_found" and by["entry:docker:h1/ghost"]["can_create"]
    assert by["user:carol"]["status"] == "not_found"
    assert plan["default_selection"] == {"entry:docker:h1/grafana": {"apply": True}}
    assert len(plan["fingerprint"]) == 64 and "digests" not in plan
    assert [r for r in _audit(app, object_type="import")] == []           # a dry run is not audited
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description is None
        assert ServiceEntry.query.filter_by(container_name="ghost").count() == 0


def test_plan_takes_text_in_yaml_json_and_legacy_shapes(client, wkey, local):
    for text in (yaml.safe_dump(_doc()), json.dumps(_doc())):
        r = client.post("/api/v1/import/plan", headers=wkey, json={"document_text": text})
        assert r.status_code == 200 and r.get_json()["header"]["format_version"] == 1
    legacy = yaml.safe_dump([{"host": "h1", "container_name": "grafana", "description": "d",
                              "last_api_update": "2026-01-01 00:00:00"}])
    r = client.post("/api/v1/import/plan", headers=wkey, json={"document_text": legacy})
    assert r.status_code == 200 and r.get_json()["header"]["legacy"] is True


def test_plan_fingerprint_follows_the_selection(client, wkey, local):
    default = _plan(client, wkey).get_json()
    sel = {"entry:docker:h1/grafana": {"apply": True}, "user:carol": {"apply": True, "create": True}}
    other = _plan(client, wkey, selection=sel).get_json()
    assert other["fingerprint"] != default["fingerprint"]
    again = _plan(client, wkey, selection=sel).get_json()
    assert again["fingerprint"] == other["fingerprint"]


@pytest.mark.parametrize("body", [
    {}, {"document": {}, "document_text": "x"}, {"document": _doc(), "bogus": 1},
    {"document": _doc(), "selection": {"x": {"nope": 1}}}, {"document_text": 5},
])
def test_plan_rejects_a_bad_body(client, wkey, body):
    assert client.post("/api/v1/import/plan", headers=wkey, json=body).status_code == 400


def test_plan_parse_errors_are_400(client, wkey):
    for text in ("a: [", "format: nope", "{}"):
        r = client.post("/api/v1/import/plan", headers=wkey, json={"document_text": text})
        assert r.status_code == 400 and r.get_json()["error"], text


def test_a_body_over_the_limit_is_413(client, wkey, monkeypatch):
    import importer
    monkeypatch.setattr(importer, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/v1/import/plan", headers=wkey, data=b"x" * 70_000, content_type="application/json")
    assert r.status_code == 413


# --- apply --------------------------------------------------------------------------------------------


def _apply(client, key, selection, plan, **extra):
    body = {"document": _doc(), "selection": selection, "fingerprint": plan["fingerprint"], **extra}
    return client.post("/api/v1/import/apply", headers=key, json=body)


def test_apply_happy_path_fill_mode_and_the_audit_row(app, client, wkey, local):
    sel = {"entry:docker:h1/grafana": {"apply": True}, "user:carol": {"apply": True, "create": True},
           "entry:docker:h1/ghost": {"apply": True, "create": True}}
    plan = _plan(client, wkey, selection=sel).get_json()
    r = _apply(client, wkey, sel, plan)
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert out["mode"] == "fill" and out["counts"]["users_created"] == 1 and out["counts"]["entries_created"] == 1
    assert out["still_to_do"]["users_without_password"] == ["carol"]
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description == "from file"
        assert ServiceEntry.query.filter_by(container_name="sonarr").one().description == "mine"
        assert User.query.filter_by(username="carol").one().has_password is False
    row = _audit(app, object_type="import")[-1]
    assert row[:2] == ("POST", "/api/v1/import/apply") and row[4] == 200
    assert row[5]["users_created"] == [None, 1] and "from file" not in json.dumps(row[5])
    assert set(row[5]) == set(out["counts"])                                    # counts only


def test_apply_overwrite_needs_the_field_named(client, app, wkey, local):
    sel = {"entry:docker:h1/sonarr": {"apply": True, "fields": ["description"]}}
    plan = _plan(client, wkey, selection=sel).get_json()
    assert _apply(client, wkey, sel, plan).get_json()["counts"].get("fields_overwritten", 0) == 0
    r = _apply(client, wkey, sel, plan, mode="overwrite")
    assert r.status_code == 200 and r.get_json()["counts"]["fields_overwritten"] == 1
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="sonarr").one().description == "theirs"


def test_a_stale_apply_is_409_with_a_fresh_plan_and_is_audited(app, client, wkey, local):
    sel = {"entry:docker:h1/grafana": {"apply": True}}
    plan = _plan(client, wkey, selection=sel).get_json()
    with app.app_context():
        ServiceEntry.query.filter_by(container_name="grafana").one().description = "someone set it"
        db.session.commit()
    r = _apply(client, wkey, sel, plan)
    assert r.status_code == 409
    body = r.get_json()
    assert "Something changed" in body["error"] and body["plan"]["fingerprint"] != plan["fingerprint"]
    assert {row["rid"]: row["status"] for row in body["plan"]["rows"]}["entry:docker:h1/grafana"] == "differs"
    assert _audit(app, object_type="import")[-1][4] == 409
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description == "someone set it"


def test_apply_errors(app, client, wkey, local):
    sel = {"entry:docker:h1/grafana": {"apply": True}}
    plan = _plan(client, wkey, selection=sel).get_json()
    assert _apply(client, wkey, sel, plan, mode="nope").status_code == 400            # schema
    bad = client.post("/api/v1/import/apply", headers=wkey,
                      json={"document_text": "a: [", "selection": {}, "fingerprint": "x"})
    assert bad.status_code == 400
    missing = client.post("/api/v1/import/apply", headers=wkey, json={"document": _doc(), "selection": {}})
    assert missing.status_code == 400
    assert [r[4] for r in _audit(app, object_type="import")] == [400, 400, 400]


def test_apply_stream_map_error_changes_nothing(app, client, wkey, local):
    doc = minimal(streams=[{"stream_id": "dhcp", "display_name": "D", "key_type": "mac", "producer": "p",
                            "status": "enabled", "network_include": ["Home"]}])
    plan = client.post("/api/v1/import/plan", headers=wkey,
                       json={"document": doc, "stream_map": {"dhcp": "nowhere"}}).get_json()
    assert any("no local stream" in w.lower() for w in plan["warnings"])
    r = client.post("/api/v1/import/apply", headers=wkey,
                    json={"document": doc, "stream_map": {"dhcp": "nowhere"}, "selection": {},
                          "fingerprint": plan["fingerprint"]})
    assert r.status_code == 400 and "stream mapping" in r.get_json()["error"]
