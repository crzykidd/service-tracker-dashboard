"""Management API: entries, checks and health (v0.8.0, PRD 14.3)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

import jobs
import synthesizer
from extensions import db
from models import (
    ApiAudit,
    Group,
    HealthCheck,
    HealthResult,
    ServiceEntry,
)
from tests.test_mgmt_api_keys import _bearer, _key


@pytest.fixture(autouse=True)
def no_icon_network(monkeypatch):
    """Add/PATCH would try to download icons."""
    import entry_rules
    import image_utils

    class _NotFound:
        status_code = 404
        content = b""

    monkeypatch.setattr(image_utils.requests, "get", lambda *a, **kw: _NotFound())
    monkeypatch.setattr(entry_rules.requests, "get", lambda *a, **kw: _NotFound())


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "reader", "read")[1])


def _make(name="svc", host="h1", source="notifier", **kw):
    kw.setdefault("last_updated", datetime.now())
    if source == "notifier":
        kw.setdefault("last_api_update", datetime.now())
        kw.setdefault("docker_status", "running")
    e = ServiceEntry(host=host, container_name=name, source=source, **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


def _svc_check(eid, name="Web", ok=None, failures=0, **kw):
    c = HealthCheck(service_entry_id=eid, kind="service", name=name, check_type=kw.pop("check_type", "http"),
                    target=kw.pop("target", "https://example.com/"), enabled=True, last_ok=ok,
                    consecutive_failures=failures, last_message=kw.pop("message", None), **kw)
    db.session.add(c)
    db.session.commit()
    return c.id


def _post_entry(client, wkey, **body):
    body = {"name": "Wiki", **body}
    return client.post("/api/v1/entries", json=body, headers=wkey)


def _audit(app, **filters):
    with app.app_context():
        return [(r.method, r.path, r.object_type, r.object_id, r.status_code, r.changes)
                for r in ApiAudit.query.filter_by(**filters).order_by(ApiAudit.id).all()]


# --- scopes ---------------------------------------------------------------------

WRITE_CALLS = [
    ("post", "/api/v1/entries", {"name": "x"}),
    ("patch", "/api/v1/entries/1", {"description": "x"}),
    ("delete", "/api/v1/entries/1", None),
    ("post", "/api/v1/entries/1/restore", None),
    ("post", "/api/v1/entries/1/checks", {"target": "https://a.example/"}),
    ("patch", "/api/v1/checks/1", {"enabled": False}),
    ("delete", "/api/v1/checks/1", None),
    ("post", "/api/v1/entries/1/checks/run", None),
]
READ_CALLS = [
    "/api/v1/entries", "/api/v1/entries/1", "/api/v1/entries/1/checks",
    "/api/v1/entries/1/health", "/api/v1/health/summary",
]


@pytest.mark.parametrize("method,path,body", WRITE_CALLS)
def test_read_key_cannot_write(client, rkey, method, path, body):
    resp = getattr(client, method)(path, json=body, headers=rkey)
    assert resp.status_code == 403
    assert getattr(client, method)(path, json=body).status_code == 401


@pytest.mark.parametrize("path", READ_CALLS)
def test_reads_need_a_key_and_accept_read_scope(app, client, rkey, path):
    assert client.get(path).status_code == 401
    with app.app_context():
        _make()
    assert client.get(path, headers=rkey).status_code == 200


def test_session_cookie_does_not_authenticate(admin_client):
    assert admin_client.get("/api/v1/entries").status_code == 401


# --- list / get ------------------------------------------------------------------


def test_list_shape_and_filters(app, client, rkey):
    with app.app_context():
        g = Group(group_name="Media")
        db.session.add(g)
        db.session.commit()
        _make("plex", "h1", stack_name="media", description="Movies", group_id=g.id)
        _make("wiki", "h2", source="manual")
        gone = _make("old", "h1", deleted_at=datetime.now())
        assert gone
    body = client.get("/api/v1/entries", headers=rkey).get_json()
    assert set(body) == {"items", "total", "limit", "offset"}
    assert (body["total"], body["limit"], body["offset"]) == (2, 200, 0)
    item = next(i for i in body["items"] if i["name"] == "plex")
    assert item["group"]["name"] == "Media" and item["source"] == "notifier"
    assert set(item["health"]) >= {"state", "label", "failures"} and isinstance(item["checks"], list)

    def names(qs):
        return sorted(i["name"] for i in client.get("/api/v1/entries?" + qs, headers=rkey).get_json()["items"])

    assert names("source=manual") == ["wiki"]
    assert names("host=h1") == ["plex"]
    assert names("group=Media") == ["plex"]
    assert names("q=movie") == ["plex"] and names("q=media") == ["plex"] and names("q=h2") == ["wiki"]
    assert names("q=%25") == []  # a literal percent, not a wildcard
    assert names("include_deleted=true") == ["old", "plex", "wiki"]
    assert names("deleted_only=true") == ["old"]
    assert client.get("/api/v1/entries?status=bogus", headers=rkey).status_code == 400
    assert client.get("/api/v1/entries?include_deleted=maybe", headers=rkey).status_code == 400


def test_pagination(app, client, rkey):
    with app.app_context():
        for i in range(5):
            _make(f"s{i}")
    page = client.get("/api/v1/entries?limit=2&offset=1", headers=rkey).get_json()
    assert [i["name"] for i in page["items"]] == ["s1", "s2"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 1)
    assert client.get("/api/v1/entries?limit=99999", headers=rkey).get_json()["limit"] == 1000
    for bad in ("limit=0", "limit=x", "offset=-1"):
        assert client.get("/api/v1/entries?" + bad, headers=rkey).status_code == 400


def test_status_filter_matches_the_ui(app, client, rkey, admin_client):
    with app.app_context():
        up, down = _make("up"), _make("down")
        _make("none")
        for eid, ok in ((up, True), (down, False)):
            _svc_check(eid, ok=ok)
    def api(status):
        return sorted(i["name"] for i in client.get(f"/api/v1/entries?status={status}", headers=rkey).get_json()["items"])
    assert api("healthy") == ["up"] and api("failing") == ["down"] and api("unknown") == ["none"]
    for status, expect in (("healthy", "up"), ("failing", "down")):
        page = admin_client.get(f"/tiled_dash?status={status}").get_data(as_text=True)
        assert expect in page


def test_get_entry_detail_hides_secrets(app, client, rkey):
    from models import Widget
    with app.app_context():
        w = Widget(widget_name="sonarr", widget_url="http://s", widget_fields=["queue"], widget_api_key="TOPSECRET")
        db.session.add(w)
        db.session.commit()
        eid = _make(widget_id=w.id, container_id="abc", stack_name="arr", networks=["n"])
    resp = client.get(f"/api/v1/entries/{eid}", headers=rkey)
    body = resp.get_json()
    assert "TOPSECRET" not in resp.get_data(as_text=True)
    assert body["widget"]["type"] == "sonarr" and body["widget"]["widget_api_key_set"] is True
    assert "widget_api_key" not in body["widget"]
    assert body["notifier"]["container_id"] == "abc" and body["notifier"]["networks"] == ["n"]
    assert client.get("/api/v1/entries/9999", headers=rkey).status_code == 404
    assert client.get("/api/v1/entries/9999", headers=rkey).get_json()["error"]


def test_list_query_count_is_flat(app, client, rkey):
    counts = {}

    def count_for(n):
        with app.app_context():
            for i in range(n):
                eid = _make(f"e{n}-{i}")
                _svc_check(eid, ok=True)
                _svc_check(eid, name="B", ok=False)
        n_queries = []

        def before(*a, **kw):
            n_queries.append(1)

        with app.app_context():
            engine = db.engine
        event.listen(engine, "before_cursor_execute", before)
        try:
            assert client.get("/api/v1/entries", headers=rkey).status_code == 200
        finally:
            event.remove(engine, "before_cursor_execute", before)
        return len(n_queries)

    client.get("/api/v1/entries", headers=rkey)  # the first call touches the key's last_used_at
    counts[3] = count_for(3)
    counts[30] = count_for(27)  # 3 + 27 = 30 entries now
    assert counts[3] == counts[30], counts


# --- create ---------------------------------------------------------------------


def test_create_manual_entry_with_body_check(app, client, wkey):
    resp = _post_entry(client, wkey, host="lab", description="Wiki", group="Docs",
                       internalurl="http://wiki.lan/", icon="Wiki.svg", sort_priority=5, locked=True,
                       url_checks={"internal": {"enabled": True, "mode": "body", "interval_seconds": 60}},
                       checks=[{"target": "https://wiki.example/health", "mode": "body", "name": "Public"},
                               {"target": "wiki.lan:22", "check_type": "tcp"}])
    assert resp.status_code == 201, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["source"] == "manual" and body["group"]["name"] == "Docs" and body["locked"] is True
    assert body["internalurl_source"] == "ui_edit" and body["icon"] == "wiki.svg" and body["sort_priority"] == 5
    kinds = {c["kind"]: c for c in body["checks"] if c["kind"] != "service"}
    assert kinds["internal_url"]["enabled"] and kinds["internal_url"]["mode"] == "body"
    assert kinds["internal_url"]["interval_seconds"] == 60 and kinds["internal_url"]["target"] == "http://wiki.lan/"
    assert not kinds["external_url"]["enabled"]
    svc = {c["name"]: c for c in body["checks"] if c["kind"] == "service"}
    assert svc["Public"]["mode"] == "body" and svc["Public"]["enabled"] is True
    assert svc["wiki.lan:22"]["check_type"] == "tcp"
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.is_static and e.checks[0].last_checked_at is None
    log = _audit(app, method="POST")
    assert log[0][2:5] == ("entry", str(body["id"]), 201) and log[0][5]["name"] == [None, "Wiki"]


def test_create_minimal_is_ungrouped_and_has_no_checks_enabled(client, wkey):
    body = _post_entry(client, wkey).get_json()
    assert body["group"] is None and body["health"]["state"] == "none"
    assert [c["kind"] for c in body["checks"]] == ["internal_url", "external_url"]
    assert not any(c["enabled"] for c in body["checks"])


def test_create_validation_lists_every_problem(client, wkey):
    resp = _post_entry(client, wkey, name="  ", host="h" * 101, icon="../evil",
                       url_checks={"internal": {"mode": "weird", "interval_seconds": 5}},
                       checks=[{"target": "ftp://x", "interval_seconds": 99999},
                               {"target": "nope", "check_type": "tcp"}])
    assert resp.status_code == 400
    locs = {".".join(d["loc"]) for d in resp.get_json()["details"]}
    assert locs >= {"name", "host", "icon", "url_checks.internal.mode", "url_checks.internal.interval_seconds",
                    "checks.0.target", "checks.0.interval_seconds", "checks.1.target"}


def test_create_rejects_unknown_wrong_typed_and_non_object(client, wkey):
    assert _post_entry(client, wkey, bogus=1).status_code == 400
    assert _post_entry(client, wkey, locked="yes").status_code == 400
    assert _post_entry(client, wkey, sort_priority="5").status_code == 400
    assert _post_entry(client, wkey, source="notifier").status_code == 400
    assert client.post("/api/v1/entries", json=[1], headers=wkey).status_code == 400
    assert client.post("/api/v1/entries", data="nope", headers=wkey).status_code == 400


def test_create_too_many_service_checks(client, wkey):
    checks = [{"target": f"https://a{i}.example/"} for i in range(21)]
    assert _post_entry(client, wkey, checks=checks).status_code == 400


def test_create_duplicate_is_409_including_deleted_and_null_host(app, client, wkey):
    assert _post_entry(client, wkey, host="lab").status_code == 201
    dup = _post_entry(client, wkey, host="lab")
    assert dup.status_code == 409 and "already exists" in dup.get_json()["error"]
    assert _post_entry(client, wkey).status_code == 201          # no host: a different key
    assert _post_entry(client, wkey).status_code == 409
    with app.app_context():
        _make("Gone", host=None, source="manual", deleted_at=datetime.now())
    gone = _post_entry(client, wkey, name="Gone")
    assert gone.status_code == 409 and gone.get_json()["details"]["deleted"] is True
    assert "Restore" in gone.get_json()["error"]
    with app.app_context():
        assert ServiceEntry.query.count() == 3


def test_create_group_reused_when_it_exists(app, client, wkey):
    _post_entry(client, wkey, name="A", group="Same")
    _post_entry(client, wkey, name="B", group="Same")
    with app.app_context():
        assert Group.query.filter_by(group_name="Same").count() == 1


def test_create_fetches_named_icon(app, client, wkey, monkeypatch):
    import entry_rules

    class _Ok:
        status_code = 200
        content = b"<svg/>"

    urls = []
    monkeypatch.setattr(entry_rules.requests, "get", lambda url, *a, **kw: urls.append(url) or _Ok())
    assert _post_entry(client, wkey, icon="Zed Thing").status_code == 400  # unsafe name, nothing fetched
    assert urls == []
    resp = _post_entry(client, wkey, icon="zzz-mgmt-test.svg")
    assert resp.status_code == 201 and urls and urls[0].endswith("/zzz-mgmt-test.svg")
    import os
    os.remove(os.path.join(app.config["IMAGE_DIR"], "zzz-mgmt-test.svg"))


# --- patch ----------------------------------------------------------------------


def test_patch_operator_fields_with_audit_diff(app, client, wkey):
    with app.app_context():
        eid = _make("svc", source="notifier")
    resp = client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={
        "group": "Infra", "internalurl": "http://x.lan/", "sort_priority": 3, "locked": True,
        "description": "d", "icon": "x.svg"})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["group"]["name"] == "Infra" and body["internalurl_source"] == "ui_edit"
    assert body["sort_priority"] == 3 and body["locked"] and body["description"] == "d"
    changes = _audit(app, method="PATCH")[0][5]
    assert changes["group"] == [None, "Infra"] and changes["internalurl"] == [None, "http://x.lan/"]
    assert "externalurl" not in changes
    # null clears
    body = client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={"group": None, "sort_priority": None,
                                                                      "internalurl": None}).get_json()
    assert body["group"] is None and body["sort_priority"] is None
    assert body["internalurl"] is None and body["internalurl_source"] is None


def test_patch_url_edit_survives_a_later_register(app, client, wkey, register):
    assert register(container_name="svc", host="h1").status_code in (200, 201)
    with app.app_context():
        eid = ServiceEntry.query.one().id
    client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={"externalurl": "https://mine.example/"})
    register(container_name="svc", host="h1", externalurl="https://label.example/")
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.externalurl == "https://mine.example/" and e.externalurl_source == synthesizer.SOURCE_UI_EDIT


def test_patch_changed_url_makes_check_due(app, client, wkey):
    with app.app_context():
        eid = _make("m", source="manual", internalurl="http://a/")
        e = db.session.get(ServiceEntry, eid)
        from models import ensure_url_checks
        ensure_url_checks(e)
        e.url_check("internal").last_checked_at = datetime.utcnow()
        db.session.commit()
    client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={"internalurl": "http://b/"})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).url_check("internal").last_checked_at is None


def test_patch_notifier_owned_fields_are_400_and_named(app, client, wkey):
    with app.app_context():
        eid = _make("svc")
    resp = client.patch(f"/api/v1/entries/{eid}", headers=wkey,
                        json={"docker_status": "x", "stack_name": "y", "description": "ok"})
    assert resp.status_code == 400
    err = resp.get_json()
    assert "docker_status" in err["error"] and "stack_name" in err["error"]
    assert {d["loc"][0] for d in err["details"]} == {"docker_status", "stack_name"}
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).description is None  # nothing applied
    assert client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={"nonsense": 1}).status_code == 400


def test_patch_name_and_host_manual_only(app, client, wkey):
    with app.app_context():
        nid = _make("svc", source="notifier")
        mid = _make("man", host=None, source="manual")
    resp = client.patch(f"/api/v1/entries/{nid}", headers=wkey, json={"name": "new"})
    assert resp.status_code == 400 and "manual" in resp.get_json()["error"]
    assert client.patch(f"/api/v1/entries/{nid}", headers=wkey, json={"host": "z"}).status_code == 400
    resp = client.patch(f"/api/v1/entries/{mid}", headers=wkey, json={"name": "renamed", "host": "lab"})
    assert resp.status_code == 200 and resp.get_json()["name"] == "renamed" and resp.get_json()["host"] == "lab"
    assert client.patch(f"/api/v1/entries/{mid}", headers=wkey, json={"name": ""}).status_code == 400
    assert client.patch(f"/api/v1/entries/{mid}", headers=wkey, json={"name": None}).status_code == 400


def test_patch_rename_into_a_duplicate_is_409(app, client, wkey):
    with app.app_context():
        _make("a", host=None, source="manual")
        b = _make("b", host=None, source="manual")
    resp = client.patch(f"/api/v1/entries/{b}", headers=wkey, json={"name": "a"})
    assert resp.status_code == 409
    assert client.patch(f"/api/v1/entries/{b}", headers=wkey, json={"name": "b"}).status_code == 200  # itself


def test_patch_validation_and_deleted_entry(app, client, wkey):
    with app.app_context():
        eid = _make("m", source="manual")
        gone = _make("g", source="manual", deleted_at=datetime.now())
    resp = client.patch(f"/api/v1/entries/{eid}", headers=wkey,
                        json={"icon": "../x", "description": "d" * 300, "locked": None})
    assert resp.status_code == 400
    assert {d["loc"][0] for d in resp.get_json()["details"]} >= {"icon", "description", "locked"}
    assert client.patch(f"/api/v1/entries/{gone}", headers=wkey, json={"description": "x"}).status_code == 409
    assert client.patch("/api/v1/entries/9999", headers=wkey, json={}).status_code == 404


def test_unlocking_makes_container_check_due(app, client, wkey, register):
    register(container_name="svc", host="h1")
    with app.app_context():
        e = ServiceEntry.query.one()
        eid = e.id
        e.is_static = True
        e.container_check.last_checked_at = datetime.utcnow()
        db.session.commit()
    client.patch(f"/api/v1/entries/{eid}", headers=wkey, json={"locked": False})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).container_check.last_checked_at is None


# --- delete / restore -----------------------------------------------------------


def test_delete_restore_and_permanent_rules(app, client, wkey):
    with app.app_context():
        eid = _make("svc")
        clash = _make("other")
    # permanent on an active entry
    assert client.delete(f"/api/v1/entries/{eid}?permanent=true", headers=wkey).status_code == 409
    resp = client.delete(f"/api/v1/entries/{eid}", headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["deleted_at"]
    assert client.delete(f"/api/v1/entries/{eid}", headers=wkey).status_code == 409  # already deleted
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).deleted_at is not None
    assert client.post(f"/api/v1/entries/{clash}/restore", headers=wkey).status_code == 409  # not deleted
    resp = client.post(f"/api/v1/entries/{eid}/restore", headers=wkey)
    assert resp.status_code == 200 and resp.get_json()["deleted_at"] is None
    client.delete(f"/api/v1/entries/{eid}", headers=wkey)
    resp = client.delete(f"/api/v1/entries/{eid}?permanent=true", headers=wkey)
    assert resp.status_code == 200 and resp.get_json() == {"id": eid, "permanent": True}
    with app.app_context():
        assert db.session.get(ServiceEntry, eid) is None
    assert client.post(f"/api/v1/entries/{eid}/restore", headers=wkey).status_code == 404
    assert client.delete("/api/v1/entries/9999", headers=wkey).status_code == 404


def test_restore_blocked_by_an_active_twin(app, client, wkey):
    with app.app_context():
        gone = _make("twin", host=None, source="manual", deleted_at=datetime.now())
        _make("twin", host=None, source="manual")
    resp = client.post(f"/api/v1/entries/{gone}/restore", headers=wkey)
    assert resp.status_code == 409


def test_delete_audited(app, client, wkey):
    with app.app_context():
        eid = _make("svc")
    client.delete(f"/api/v1/entries/{eid}", headers=wkey)
    row = _audit(app, method="DELETE")[0]
    assert row[2:5] == ("entry", str(eid), 200) and row[5]["deleted_at"][0] is None


# --- checks ---------------------------------------------------------------------


def test_add_check_rules(app, client, wkey):
    with app.app_context():
        eid = _make("m", source="manual")
    resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                       json={"target": "https://m.example/", "name": "Home", "mode": "body", "interval_seconds": 45})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["kind"] == "service" and body["mode"] == "body" and body["interval_seconds"] == 45
    assert body["enabled"] and body["entry_id"] == eid
    listed = client.get(f"/api/v1/entries/{eid}/checks", headers=wkey).get_json()
    assert listed["total"] == 1 and {"items", "limit", "offset"} <= set(listed)
    bad = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json={"target": "x", "check_type": "ping",
                                                                            "timeout_seconds": 0})
    assert bad.status_code == 400
    assert {d["loc"][0] for d in bad.get_json()["details"]} == {"timeout_seconds"}
    assert client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json={}).status_code == 400
    ping = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                       json={"target": "10.0.0.1", "check_type": "ping"})
    assert ping.status_code == 201 and ping.get_json()["mode"] == "status"
    assert client.post("/api/v1/entries/9999/checks", headers=wkey, json={"target": "https://a/"}).status_code == 404
    log = _audit(app, method="POST", object_type="check")
    assert log[0][5]["target"] == [None, "https://m.example/"]


def test_add_check_limit_and_deleted_entry(app, client, wkey):
    with app.app_context():
        eid = _make("m", source="manual")
        gone = _make("g", source="manual", deleted_at=datetime.now())
        for i in range(20):
            _svc_check(eid, name=f"c{i}")
    assert client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json={"target": "https://a.example/"}
                       ).status_code == 409
    assert client.post(f"/api/v1/entries/{gone}/checks", headers=wkey, json={"target": "https://a.example/"}
                       ).status_code == 409


def test_patch_checks_per_kind(app, client, wkey, register):
    register(container_name="n", host="h1")
    with app.app_context():
        e = ServiceEntry.query.one()
        from models import ensure_url_checks
        ensure_url_checks(e)
        svc = HealthCheck(kind="service", name="S", check_type="http", target="https://a.example/",
                          enabled=True, last_checked_at=datetime.utcnow(), service_entry_id=e.id)
        db.session.add(svc)
        db.session.commit()
        url_id, cont_id, svc_id = e.url_check("internal").id, e.container_check.id, svc.id
    # URL kind: only settings
    ok = client.patch(f"/api/v1/checks/{url_id}", headers=wkey,
                      json={"enabled": True, "mode": "body", "interval_seconds": 120, "timeout_seconds": 5,
                            "verify_tls": False})
    assert ok.status_code == 200
    assert ok.get_json()["mode"] == "body" and ok.get_json()["verify_tls"] is False
    assert ok.get_json()["interval_seconds"] == 120
    for field in ({"target": "https://x/"}, {"name": "n"}, {"check_type": "tcp"}):
        resp = client.patch(f"/api/v1/checks/{url_id}", headers=wkey, json=field)
        assert resp.status_code == 400 and list(field)[0] in resp.get_json()["error"]
    # container kind: enabled + interval only
    assert client.patch(f"/api/v1/checks/{cont_id}", headers=wkey,
                        json={"enabled": False, "interval_seconds": 60}).status_code == 200
    assert client.patch(f"/api/v1/checks/{cont_id}", headers=wkey, json={"mode": "body"}).status_code == 400
    # service kind: everything, and the check becomes due
    resp = client.patch(f"/api/v1/checks/{svc_id}", headers=wkey,
                        json={"target": "db.lan:5432", "check_type": "tcp", "name": "DB"})
    assert resp.status_code == 200 and resp.get_json()["check_type"] == "tcp"
    with app.app_context():
        assert db.session.get(HealthCheck, svc_id).last_checked_at is None
    # validation
    bad = client.patch(f"/api/v1/checks/{svc_id}", headers=wkey, json={"target": "nope"})
    assert bad.status_code == 400 and bad.get_json()["details"][0]["loc"] == ["target"]
    assert client.patch(f"/api/v1/checks/{url_id}", headers=wkey, json={"interval_seconds": 5}).status_code == 400
    assert client.patch(f"/api/v1/checks/{url_id}", headers=wkey, json={"enabled": None}).status_code == 400
    assert client.patch(f"/api/v1/checks/{url_id}", headers=wkey, json={"interval_seconds": None}
                        ).get_json()["interval_seconds"] is None
    assert client.patch("/api/v1/checks/9999", headers=wkey, json={}).status_code == 404
    diff = _audit(app, method="PATCH", object_id=str(url_id))[0][5]
    assert diff["mode"] == ["status", "body"] and diff["enabled"] == [False, True]


def test_delete_check_rules(app, client, wkey, register):
    register(container_name="n", host="h1")
    with app.app_context():
        e = ServiceEntry.query.one()
        from models import ensure_url_checks
        ensure_url_checks(e)
        svc = HealthCheck(kind="service", name="S", target="https://a.example/", service_entry_id=e.id)
        db.session.add(svc)
        db.session.commit()
        ids = {"url": e.url_check("external").id, "cont": e.container_check.id, "svc": svc.id}
        db.session.add(HealthResult(check_id=svc.id, ok=True))
        db.session.commit()
    for k in ("url", "cont"):
        resp = client.delete(f"/api/v1/checks/{ids[k]}", headers=wkey)
        assert resp.status_code == 409 and "Disable" in resp.get_json()["error"]
    assert client.delete(f"/api/v1/checks/{ids['svc']}", headers=wkey).status_code == 200
    assert client.delete(f"/api/v1/checks/{ids['svc']}", headers=wkey).status_code == 404
    with app.app_context():
        assert HealthResult.query.count() == 0  # results cascade


def test_run_checks_queues_counting_checks(app, client, wkey):
    with app.app_context():
        eid = _make("m", source="manual", internalurl="http://a/")
        e = db.session.get(ServiceEntry, eid)
        from models import ensure_url_checks
        ensure_url_checks(e)
        e.url_check("internal").enabled = True
        db.session.commit()
        cid = _svc_check(eid)
        off = _svc_check(eid, name="off")
        db.session.get(HealthCheck, off).enabled = False
        db.session.commit()
        want = {e.url_check("internal").id, cid}
    jobs._run_requests.clear()
    resp = client.post(f"/api/v1/entries/{eid}/checks/run", headers=wkey)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["queued"] == 2 and body["requested_at"].endswith("Z")
    assert jobs._pending_run_requests() == want
    jobs._run_requests.clear()
    assert _audit(app, method="POST", object_type="entry")[0][5]["check_run_requested"][0] is None
    assert client.post("/api/v1/entries/9999/checks/run", headers=wkey).status_code == 404


# --- health ---------------------------------------------------------------------


def test_entry_health_matches_the_ui_endpoint(app, client, rkey, admin_client):
    with app.app_context():
        eid = _make("m", source="manual")
        cid = _svc_check(eid, ok=False, failures=2, message="boom")
        db.session.add(HealthResult(check_id=cid, ok=False, ts=datetime.utcnow(), message="boom"))
        db.session.commit()
    for rng in ("24h", "7d"):
        api = client.get(f"/api/v1/entries/{eid}/health?range={rng}", headers=rkey).get_json()
        ui = admin_client.get(f"/service/{eid}/health?range={rng}").get_json()
        api.pop("generated_at"), ui.pop("generated_at")
        assert api == ui
    assert client.get(f"/api/v1/entries/{eid}/health?range=1y", headers=rkey).status_code == 400
    assert client.get("/api/v1/entries/9999/health", headers=rkey).status_code == 404


def test_health_summary_counts_and_failures(app, client, rkey):
    now = datetime.utcnow()
    with app.app_context():
        up = _make("up", source="manual")
        _svc_check(up, ok=True)
        down = _make("down", source="manual")
        d1 = _svc_check(down, name="Web", ok=False, failures=3, message="HTTP 500", last_checked_at=now)
        degraded = _make("degraded", source="manual")
        _svc_check(degraded, name="Good", ok=True)
        _svc_check(degraded, name="Bad", ok=False, failures=1, message="refused", last_checked_at=now)
        _make("empty", source="manual")
        waiting = _make("waiting", source="manual")
        _svc_check(waiting)  # enabled, never ran: unknown
        _make("stale", source="notifier", last_api_update=datetime.now() - timedelta(hours=2))
        _make("deleted", source="manual", deleted_at=now)
        # history for Web: ok, then three failures
        for minutes, ok in ((50, True), (40, False), (30, False), (20, False)):
            db.session.add(HealthResult(check_id=d1, ok=ok, ts=now - timedelta(minutes=minutes), message="x"))
        db.session.commit()
    body = client.get("/api/v1/health/summary", headers=rkey).get_json()
    assert body["counts"] == {"total": 6, "passing": 1, "failing": 2, "unknown": 3, "stale": 1,
                              "streams_stale": 0}
    assert body["streams"] == [] and body["stale_streams"] == []
    by_name = {f["name"]: f for f in body["failing"]}
    assert set(by_name) == {"down", "degraded"}
    assert by_name["down"]["state"] == "down" and by_name["degraded"]["state"] == "degraded"
    web = by_name["down"]["failures"][0]
    assert web["check"] == "Web" and web["kind"] == "service" and web["message"] == "HTTP 500"
    expected = (now - timedelta(minutes=40)).replace(microsecond=0).isoformat() + "Z"
    assert web["since"] == expected
    assert [f["check"] for f in by_name["degraded"]["failures"]] == ["Bad"]


def test_summary_counts_match_the_filter_bar(app, client, rkey):
    from view_helpers import health_counts
    with app.app_context():
        for i, ok in enumerate((True, True, False, None)):
            eid = _make(f"e{i}", source="manual")
            _svc_check(eid, ok=ok, failures=int(ok is False))
        _make("none", source="manual")
        expected = health_counts(ServiceEntry.active().all())
    counts = client.get("/api/v1/health/summary", headers=rkey).get_json()["counts"]
    assert {k: counts[k] for k in expected} == expected
    assert counts["unknown"] == 2  # never ran + not monitored


def test_error_shape_is_json(client, wkey):
    resp = client.get("/api/v1/entries/9999", headers=wkey)
    assert resp.status_code == 404 and set(resp.get_json()) == {"error", "details"}


def test_health_summary_container_up_url_failing_is_down(app, client, rkey):
    from models import ensure_container_check
    with app.app_context():
        eid = _make("emmett")  # notifier entry, running
        e = db.session.get(ServiceEntry, eid)
        ensure_container_check(e)
        e.container_check.last_ok = True
        _svc_check(eid, name="Web", ok=False, failures=3, message="503: Scope not found")
        db.session.commit()
    body = client.get("/api/v1/health/summary", headers=rkey).get_json()
    assert [(f["name"], f["state"]) for f in body["failing"]] == [("emmett", "down")]
    assert body["failing"][0]["failures"][0]["message"] == "503: Scope not found"
    entry = client.get(f"/api/v1/entries/{eid}", headers=rkey).get_json()
    assert entry["health"]["state"] == "down"


def test_mgmt_entries_source_query_covers_valid_sources(app, client, rkey):
    from models import VALID_SOURCES

    with app.app_context():
        for s in VALID_SOURCES:
            _make(f"q-{s}", source=s)
    for s in VALID_SOURCES:
        body = client.get(f"/api/v1/entries?source={s}", headers=rkey).get_json()
        assert [i["name"] for i in body["items"]] == [f"q-{s}"]
    assert client.get("/api/v1/entries?source=bogus", headers=rkey).status_code == 400
