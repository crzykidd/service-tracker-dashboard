"""Management API: groups, widgets, exposure settings and config (v0.8.0, PRD 14.4)."""

import pytest

import widget_rules
from extensions import db
from models import ApiAudit, Group, ServiceEntry, Widget, WidgetValue
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_mgmt_entries import _audit, no_icon_network  # noqa: F401
from tests.test_mgmt_entries import _make as _make_in_ctx


def _make(*args, **kw):
    """`_make` needs an app context; most of these tests call it from outside one."""
    from app import app
    with app.app_context():
        return _make_in_ctx(*args, **kw)


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "reader", "read")[1])


WIDGET = {"type": "sonarr", "url": "http://sonarr:8989", "fields": ["wanted", "queued"]}


# --- scopes ---------------------------------------------------------------------

WRITE_CALLS = [
    ("post", "/api/v1/groups", {"name": "x"}),
    ("patch", "/api/v1/groups/1", {"name": "x"}),
    ("delete", "/api/v1/groups/1", None),
    ("put", "/api/v1/entries/1/widget", WIDGET),
    ("delete", "/api/v1/entries/1/widget", None),
    ("delete", "/api/v1/widgets/1", None),
    ("put", "/api/v1/settings/exposure", {"layer_directions": {}}),
]
READ_CALLS = ["/api/v1/groups", "/api/v1/widgets/types", "/api/v1/widgets",
              "/api/v1/settings/exposure", "/api/v1/config"]


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_read_key_cannot_write(client, rkey, method, path, body):
    assert getattr(client, method)(path, json=body, headers=rkey).status_code == 403
    assert getattr(client, method)(path, json=body).status_code == 401


@pytest.mark.parametrize("path", READ_CALLS)
def test_reads_need_a_key_and_read_scope_works(client, rkey, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=rkey).status_code == 200


# --- groups ---------------------------------------------------------------------


def test_group_crud_and_audit(app, client, wkey, rkey):
    resp = client.post("/api/v1/groups", json={"name": " Media ", "icon": "tv.svg", "sort_priority": 2},
                       headers=wkey)
    assert resp.status_code == 201
    group = resp.get_json()
    assert group["name"] == "Media" and group["icon"] == "tv.svg" and group["sort_priority"] == 2
    assert group["entry_count"] == 0
    gid = group["id"]

    resp = client.patch(f"/api/v1/groups/{gid}", json={"name": "Movies", "sort_priority": None, "icon": None},
                        headers=wkey)
    assert resp.status_code == 200
    assert resp.get_json()["name"] == "Movies" and resp.get_json()["sort_priority"] is None
    assert resp.get_json()["icon"] is None

    items = client.get("/api/v1/groups", headers=rkey).get_json()
    assert items["total"] == 1 and items["items"][0]["name"] == "Movies"

    assert client.delete(f"/api/v1/groups/{gid}", headers=wkey).get_json() == {
        "id": gid, "deleted": True, "ungrouped_entries": 0}
    assert client.patch(f"/api/v1/groups/{gid}", json={"name": "x"}, headers=wkey).status_code == 404
    assert client.delete(f"/api/v1/groups/{gid}", headers=wkey).status_code == 404

    rows = _audit(app, object_type="group")
    assert [r[0] for r in rows] == ["POST", "PATCH", "DELETE", "PATCH", "DELETE"]
    assert rows[1][5]["name"] == ["Media", "Movies"]


def test_group_duplicate_is_409_and_validation_400(app, client, wkey):
    first = client.post("/api/v1/groups", json={"name": "A"}, headers=wkey).get_json()
    other = client.post("/api/v1/groups", json={"name": "B"}, headers=wkey).get_json()
    assert client.post("/api/v1/groups", json={"name": "A"}, headers=wkey).status_code == 409
    assert client.patch(f"/api/v1/groups/{other['id']}", json={"name": "A"}, headers=wkey).status_code == 409
    # renaming to its own name is fine
    assert client.patch(f"/api/v1/groups/{first['id']}", json={"name": "A"}, headers=wkey).status_code == 200
    for body in ({"name": ""}, {"name": "x" * 101}, {"name": "ok", "bogus": 1}, {"name": "ok", "sort_priority": "3"}):
        assert client.post("/api/v1/groups", json=body, headers=wkey).status_code == 400
    assert client.patch(f"/api/v1/groups/{first['id']}", json={"name": None}, headers=wkey).status_code == 400
    assert client.patch(f"/api/v1/groups/{first['id']}", json={"icon": "i" * 256}, headers=wkey).status_code == 400


def test_group_delete_blocked_by_active_entries_unless_forced(app, client, wkey, rkey):
    gid = client.post("/api/v1/groups", json={"name": "G"}, headers=wkey).get_json()["id"]
    with app.app_context():
        live = _make("live", source="manual", group_id=gid)
        gone = _make("gone", source="manual", group_id=gid)
        from datetime import datetime
        db.session.get(ServiceEntry, gone).deleted_at = datetime.now()
        db.session.commit()
    assert client.get("/api/v1/groups", headers=rkey).get_json()["items"][0]["entry_count"] == 1
    resp = client.delete(f"/api/v1/groups/{gid}", headers=wkey)
    assert resp.status_code == 409 and resp.get_json()["details"]["entry_count"] == 1
    resp = client.delete(f"/api/v1/groups/{gid}?force=true", headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["ungrouped_entries"] == 1
    with app.app_context():
        assert db.session.get(ServiceEntry, live).group_id is None
        assert db.session.get(ServiceEntry, gone).group_id is None
        assert db.session.get(Group, gid) is None
    assert client.delete(f"/api/v1/groups/{gid}?force=maybe", headers=wkey).status_code in (400, 404)


def test_group_delete_with_only_deleted_entries_succeeds(app, client, wkey):
    from datetime import datetime
    gid = client.post("/api/v1/groups", json={"name": "G"}, headers=wkey).get_json()["id"]
    with app.app_context():
        eid = _make("old", source="manual", group_id=gid, deleted_at=datetime.now())
    assert client.delete(f"/api/v1/groups/{gid}", headers=wkey).status_code == 200
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).group_id is None


# --- widget types ---------------------------------------------------------------


def test_widget_types_listing(client, rkey):
    body = client.get("/api/v1/widgets/types", headers=rkey).get_json()
    types = {t["type"]: t for t in body["items"]}
    assert {"sonarr", "radarr", "bazarr", "overseerr", "prowlarr", "syncthing"} <= set(types)
    assert "__pycache__" not in types
    keys = {f["key"] for f in types["sonarr"]["available_fields"]}
    assert {"wanted", "queued", "series"} <= keys
    assert set(types["sonarr"]["available_fields"][0]) == {"key", "label", "description"}
    assert body["total"] == len(body["items"])


@pytest.mark.parametrize("name", ["../app", "..", "sonarr/../radarr", "/etc", "widgets", "__pycache__", "", "SONARR"])
def test_get_type_rejects_traversalish_names(name):
    assert widget_rules.get_type(name) is None


@pytest.mark.parametrize("name", ["../app", "sonarr/../radarr", "/etc/passwd", "nope", "__pycache__"])
def test_put_traversalish_type_is_400(app, client, wkey, name):
    eid = _make("s", source="manual")
    resp = client.put(f"/api/v1/entries/{eid}/widget", json={**WIDGET, "type": name}, headers=wkey)
    assert resp.status_code == 400
    assert any(d["loc"] == ["type"] for d in resp.get_json()["details"])


# --- widget put / delete ---------------------------------------------------------


def test_put_widget_creates_then_updates_and_never_returns_key(app, client, wkey, rkey):
    eid = _make("s", source="manual")
    resp = client.put(f"/api/v1/entries/{eid}/widget", json={**WIDGET, "widget_api_key": "TOPSECRET"},
                      headers=wkey)
    assert resp.status_code == 201
    out = resp.get_json()
    assert out["type"] == "sonarr" and out["fields"] == ["wanted", "queued"]
    assert out["widget_api_key_set"] is True and "TOPSECRET" not in resp.get_data(as_text=True)
    wid = out["id"]

    # omitted key is kept; fields are replaced
    resp = client.put(f"/api/v1/entries/{eid}/widget", json={**WIDGET, "fields": ["series"]}, headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["id"] == wid
    assert resp.get_json()["fields"] == ["series"] and resp.get_json()["widget_api_key_set"] is True
    with app.app_context():
        assert db.session.get(Widget, wid).widget_api_key == "TOPSECRET"

    for path in (f"/api/v1/entries/{eid}", "/api/v1/widgets"):
        assert "TOPSECRET" not in client.get(path, headers=rkey).get_data(as_text=True)
    listed = client.get("/api/v1/widgets", headers=rkey).get_json()["items"][0]
    assert listed["entry_ids"] == [eid] and listed["detached"] is False
    assert "widget_api_key" not in listed

    # null clears it
    resp = client.put(f"/api/v1/entries/{eid}/widget", json={**WIDGET, "widget_api_key": None}, headers=wkey)
    assert resp.get_json()["widget_api_key_set"] is False

    # audit rows never hold the key, and the key change is masked
    rows = _audit(app, object_type="widget")
    assert [r[0] for r in rows] == ["PUT", "PUT", "PUT"]
    with app.app_context():
        raw = " ".join(str(r.changes) for r in ApiAudit.query.all())
    assert "TOPSECRET" not in raw
    assert rows[0][5]["widget_api_key"] == ["***", "***"]


def test_put_widget_field_validation(app, client, wkey):
    eid = _make("s", source="manual")
    url = f"/api/v1/entries/{eid}/widget"
    bad = [
        ({**WIDGET, "fields": ["wanted", "nonsense"]}, "fields"),
        ({**WIDGET, "fields": []}, "fields"),
        ({**WIDGET, "url": ""}, "url"),
        ({**WIDGET, "url": "h" * 256}, "url"),
        ({**WIDGET, "widget_api_key": "k" * 256}, "widget_api_key"),
    ]
    for body, field in bad:
        resp = client.put(url, json=body, headers=wkey)
        assert resp.status_code == 400, body
        assert any(d["loc"][0] == field for d in resp.get_json()["details"])
    # a field of another plugin is not valid for this one
    assert client.put(url, json={**WIDGET, "fields": ["queue_size_not_here"]}, headers=wkey).status_code == 400
    for body in ({**WIDGET, "extra": 1}, {"type": "sonarr"}, {**WIDGET, "fields": "wanted"}):
        assert client.put(url, json=body, headers=wkey).status_code == 400
    with app.app_context():
        assert Widget.query.count() == 0


def test_put_widget_missing_or_deleted_entry(app, client, wkey):
    from datetime import datetime
    assert client.put("/api/v1/entries/999/widget", json=WIDGET, headers=wkey).status_code == 404
    eid = _make("s", source="manual", deleted_at=datetime.now())
    assert client.put(f"/api/v1/entries/{eid}/widget", json=WIDGET, headers=wkey).status_code == 409


def _widgeted(app, client, wkey):
    eid = _make("s", source="manual")
    wid = client.put(f"/api/v1/entries/{eid}/widget", json=WIDGET, headers=wkey).get_json()["id"]
    with app.app_context():
        db.session.add(WidgetValue(widget_id=wid, widget_value_key="wanted", widget_value="3"))
        db.session.commit()
    return eid, wid


def test_delete_widget_detaches_by_default_then_delete_detached(app, client, wkey, rkey):
    eid, wid = _widgeted(app, client, wkey)
    # an attached widget cannot be deleted directly
    resp = client.delete(f"/api/v1/widgets/{wid}", headers=wkey)
    assert resp.status_code == 409 and resp.get_json()["details"]["entry_ids"] == [eid]

    resp = client.delete(f"/api/v1/entries/{eid}/widget", headers=wkey)
    assert resp.get_json() == {"entry_id": eid, "widget_id": wid, "deleted": False}
    listed = client.get("/api/v1/widgets", headers=rkey).get_json()["items"][0]
    assert listed["detached"] is True and listed["entry_ids"] == []
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).widget_id is None
        assert WidgetValue.query.filter_by(widget_id=wid).count() == 1
    assert client.delete(f"/api/v1/entries/{eid}/widget", headers=wkey).status_code == 404

    assert client.delete(f"/api/v1/widgets/{wid}", headers=wkey).status_code == 200
    with app.app_context():
        assert db.session.get(Widget, wid) is None
        assert WidgetValue.query.count() == 0
    assert client.delete(f"/api/v1/widgets/{wid}", headers=wkey).status_code == 404


def test_delete_widget_with_delete_flag_removes_values(app, client, wkey):
    eid, wid = _widgeted(app, client, wkey)
    resp = client.delete(f"/api/v1/entries/{eid}/widget?delete=true", headers=wkey)
    assert resp.get_json()["deleted"] is True
    with app.app_context():
        assert db.session.get(Widget, wid) is None and WidgetValue.query.count() == 0
        assert db.session.get(ServiceEntry, eid).widget_id is None
    assert client.delete(f"/api/v1/entries/{eid}/widget?delete=maybe", headers=wkey).status_code == 400


# --- exposure settings -----------------------------------------------------------


def test_exposure_round_trip_and_matches_the_settings_ui(app, client, wkey, rkey, admin_client):
    import settings_store
    from models import ServiceExposure
    with app.app_context():
        eid = _make("web", host="edge")
        db.session.add(ServiceExposure(service_entry_id=eid, layer="traefik", hostname="a.example.com"))
        db.session.commit()
    got = client.get("/api/v1/settings/exposure", headers=rkey).get_json()
    assert got["layer_directions"] == {} and got["host_overrides"] == {}
    assert got["discovered_layers"] == ["traefik"] and got["discovered_hosts"] == ["edge"]
    assert got["valid_directions"] == ["internal", "external", "neither"]

    body = {"layer_directions": {"traefik": "internal"}, "host_overrides": {"edge": {"traefik": "external"}}}
    resp = client.put("/api/v1/settings/exposure", json=body, headers=wkey)
    assert resp.status_code == 200
    assert resp.get_json()["recomputed"] == 1
    assert client.get("/api/v1/settings/exposure", headers=rkey).get_json()["layer_directions"] == {
        "traefik": "internal"}
    with app.app_context():
        assert settings_store.get_layer_directions() == {"traefik": "internal"}
        assert settings_store.get_host_layer_overrides() == {"edge": {"traefik": "external"}}
        assert db.session.get(ServiceEntry, eid).internalurl is None  # host override says external

    # what the UI form writes reads back the same through the API
    admin_client.post("/settings/exposure", data={"layer:traefik": "external", "override:edge:traefik": "internal"})
    ui = client.get("/api/v1/settings/exposure", headers=rkey).get_json()
    assert ui["layer_directions"] == {"traefik": "external"}
    assert ui["host_overrides"] == {"edge": {"traefik": "internal"}}

    # PUT replaces wholesale; an empty body of mappings clears
    client.put("/api/v1/settings/exposure", json={"layer_directions": {}}, headers=wkey)
    cleared = client.get("/api/v1/settings/exposure", headers=rkey).get_json()
    assert cleared["layer_directions"] == {} and cleared["host_overrides"] == {}
    rows = _audit(app, object_type="exposure_settings")
    assert [r[0] for r in rows] == ["PUT", "PUT"]
    assert rows[0][5]["layer_directions"] == [{}, {"traefik": "internal"}]


def test_exposure_put_recomputes_synthesized_urls(app, client, wkey):
    from models import ServiceExposure
    with app.app_context():
        eid = _make("web", host="edge")
        db.session.add(ServiceExposure(service_entry_id=eid, layer="traefik", hostname="a.example.com", tls=True))
        db.session.commit()
    client.put("/api/v1/settings/exposure", json={"layer_directions": {"traefik": "internal"}}, headers=wkey)
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).internalurl == "https://a.example.com/"


@pytest.mark.parametrize("body", [
    {"layer_directions": {"traefik": "sideways"}},
    {"layer_directions": {"": "internal"}},
    {"layer_directions": {}, "host_overrides": {"edge": {"traefik": "nope"}}},
    {"layer_directions": {}, "host_overrides": {"": {"traefik": "internal"}}},
    {"layer_directions": {"a": "internal"}, "bogus": 1},
    {"host_overrides": {}},
    {"layer_directions": {"a": 1}},
])
def test_exposure_put_invalid_is_400_and_changes_nothing(app, client, wkey, rkey, body):
    client.put("/api/v1/settings/exposure", json={"layer_directions": {"keep": "internal"}}, headers=wkey)
    assert client.put("/api/v1/settings/exposure", json=body, headers=wkey).status_code == 400
    assert client.get("/api/v1/settings/exposure", headers=rkey).get_json()["layer_directions"] == {
        "keep": "internal"}


# --- config ----------------------------------------------------------------------


def test_config_masks_secrets_and_is_read_only(app, client, rkey, wkey):
    from tests.conftest import TEST_TOKEN
    resp = client.get("/api/v1/config", headers=rkey)
    text = resp.get_data(as_text=True)
    body = resp.get_json()
    assert TEST_TOKEN not in text
    assert body["settings"]["api_token"] == "***"
    assert body["settings"]["backup_days_to_keep"] == 7
    assert body["version"] and body["sources"]["api_token"] == "env"
    assert body["sources"]["backup_days_to_keep"] == "default"
    assert set(body["settings"]) >= {"stale_after_minutes", "api_audit_retention_days", "display_tools", "tile_show_host"}
    assert body["settings"]["tile_show_host"] == "duplicates"
    assert body["sources"]["tile_show_host"] == "default"
    assert client.put("/api/v1/config", json={}, headers=wkey).status_code == 405
    assert client.post("/api/v1/config", json={}, headers=wkey).status_code == 405


def test_config_secret_name_rule():
    import routes_mgmt_api as m
    for name in ("api_token", "secret_key", "widget_api_key", "x_token", "db_password", "app_secret", "api_key"):
        assert m._config_is_secret(name), name
    for name in ("backup_path", "user_session_length", "keyboard"):
        assert not m._config_is_secret(name), name
