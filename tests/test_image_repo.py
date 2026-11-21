"""Image repository link: derivation, override, forms, management API, export/import (GitHub #6)."""

from datetime import datetime, timezone

import pytest

import entry_rules
import export_format
from extensions import db
from image_repo import effective_repo_url, image_repo_url, valid_repo_override
from models import ServiceEntry
from tests.test_import_engine import (
    do_apply,
    do_plan,
    fields,
    manual_rec,
    minimal,
    parse,
    row,
)
from tests.test_mgmt_api_keys import _bearer, _key

# --- derivation (pure) ---------------------------------------------------------------------


@pytest.mark.parametrize("registry,owner,name,expected", [
    (None, None, "nginx", "https://hub.docker.com/_/nginx"),
    ("", "library", "nginx", "https://hub.docker.com/_/nginx"),
    ("docker.io", None, "redis", "https://hub.docker.com/_/redis"),
    ("index.docker.io", "library", "redis", "https://hub.docker.com/_/redis"),
    (None, "grafana", "grafana", "https://hub.docker.com/r/grafana/grafana"),
    ("registry-1.docker.io", "grafana", "grafana", "https://hub.docker.com/r/grafana/grafana"),
    ("ghcr.io", "crzykidd", "service-tracker-dashboard",
     "https://github.com/users/crzykidd/packages/container/package/service-tracker-dashboard"),
    ("GHCR.IO", "home-assistant", "home-assistant",
     "https://github.com/users/home-assistant/packages/container/package/home-assistant"),
    ("quay.io", "prometheus", "prometheus", "https://quay.io/repository/prometheus/prometheus"),
    ("lscr.io", "linuxserver", "sonarr", "https://github.com/linuxserver/docker-sonarr"),
])
def test_derived_urls(registry, owner, name, expected):
    assert image_repo_url(registry, owner, name) == expected


@pytest.mark.parametrize("registry,owner,name", [
    (None, None, None),                       # no name
    ("ghcr.io", "owner", ""),                 # empty name
    ("registry.example.com", "team", "app"),  # unknown / private registry: never guess
    ("gcr.io", "project", "app"),
    ("ghcr.io", None, "app"),                 # registry with no owner
    ("lscr.io", "someone-else", "app"),       # lscr is only known for linuxserver
    (None, "ghcr.io", "app"),                 # "ghcr.io/app" parsed as owner/name
    (None, "localhost:5000", "app"),
])
def test_no_link_when_not_derivable(registry, owner, name):
    assert image_repo_url(registry, owner, name) is None


def test_values_are_quoted_and_nested_paths_survive():
    assert image_repo_url(None, "o wner", "na me?x#y") == "https://hub.docker.com/r/o%20wner/na%20me%3Fx%23y"
    assert image_repo_url("quay.io", "org", "team/app") == "https://quay.io/repository/org/team/app"
    assert "<" not in image_repo_url("ghcr.io", "o", "<script>")


def test_override_validation():
    assert valid_repo_override("https://github.com/o/r")
    assert valid_repo_override("http://git.lan/o/r")
    for bad in ("ftp://x/y", "javascript:alert(1)", "github.com/o/r", "https://", "https://a b/c"):
        assert not valid_repo_override(bad), bad
    assert entry_rules.validate_image_repo_url("image_repo_url", "") == []
    assert entry_rules.validate_image_repo_url("image_repo_url", "nope")[0]["field"] == "image_repo_url"
    assert entry_rules.validate_image_repo_url("image_repo_url", "https://x/" + "a" * 600)


def test_override_wins_over_derived(app):
    with app.app_context():
        e = ServiceEntry(container_name="x", image_registry="quay.io", image_owner="o", image_name="n")
        assert effective_repo_url(e) == "https://quay.io/repository/o/n"
        e.image_repo_url = "https://example.org/mine"
        assert effective_repo_url(e) == "https://example.org/mine" == e.image_repo_link
        e.image_repo_url = "  "
        assert e.image_repo_link == "https://quay.io/repository/o/n"


# --- display ---------------------------------------------------------------------------------


def _docker(name="app", **kw):
    now = datetime.now()
    e = ServiceEntry(host="h", container_name=name, source="notifier", last_updated=now,
                     last_api_update=now, docker_status="running", **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


def test_facts_render_a_safe_link(app, admin_client):
    with app.app_context():
        _docker(image_registry="ghcr.io", image_owner="crzykidd", image_name="std", image_tag="v1")
    for path in ("/", "/tiled_dash"):
        html = admin_client.get(path).get_data(as_text=True)
        assert ('href="https://github.com/users/crzykidd/packages/container/package/std" '
                'target="_blank" rel="noopener noreferrer"') in html, path
        assert "ghcr.io/crzykidd/std:v1" in html


def test_facts_show_override_and_plain_text_when_unknown(app, admin_client):
    with app.app_context():
        _docker(image_registry="reg.lan", image_owner="t", image_name="a", image_tag="1", name="plain")
        _docker(image_registry="reg.lan", image_owner="t", image_name="b", image_tag="2", name="linked",
                image_repo_url="https://git.lan/t/b")
    html = admin_client.get("/").get_data(as_text=True)
    assert "reg.lan/t/a:1" in html and 'href="https://git.lan/t/b"' in html
    assert html.count('class="image-repo-link') == 1


def test_compact_details_dialog_has_the_link(app, admin_client):
    with app.app_context():
        eid = _docker(image_owner="grafana", image_name="grafana")
    html = admin_client.get(f"/service/{eid}/details").get_data(as_text=True)
    assert 'href="https://hub.docker.com/r/grafana/grafana"' in html


# --- add / edit forms ----------------------------------------------------------------------


def test_add_form_saves_and_rejects(app, admin_client):
    r = admin_client.post("/add", data={"container_name": "wiki", "image_repo_url": "https://git.lan/wiki"})
    assert r.status_code in (200, 302)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="wiki").one().image_repo_url == "https://git.lan/wiki"
    r = admin_client.post("/add", data={"container_name": "bad", "image_repo_url": "javascript:alert(1)"})
    assert "Image repo URL" in r.get_data(as_text=True)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="bad").count() == 0


def test_edit_form_sets_clears_and_validates(app, admin_client):
    with app.app_context():
        eid = _docker(image_owner="grafana", image_name="grafana")
    base = {"host": "h", "container_name": "app", "widget_name": "none"}
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'name="image_repo_url"' in page
    admin_client.post(f"/edit/{eid}", data={**base, "image_repo_url": "https://git.lan/g"})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).image_repo_url == "https://git.lan/g"
    r = admin_client.post(f"/edit/{eid}", data={**base, "image_repo_url": "ftp://nope"})
    assert "Image repo URL" in r.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).image_repo_url == "https://git.lan/g"
    admin_client.post(f"/edit/{eid}", data={**base, "image_repo_url": ""})
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.image_repo_url is None
        assert e.image_repo_link == "https://hub.docker.com/r/grafana/grafana"


def test_register_never_touches_the_override(app, register):
    register(host="h1", container_name="svc")
    with app.app_context():
        e = ServiceEntry.query.one()
        e.image_repo_url = "https://git.lan/keep"
        db.session.commit()
    register(host="h1", container_name="svc", description="x")
    with app.app_context():
        assert ServiceEntry.query.one().image_repo_url == "https://git.lan/keep"


# --- management API --------------------------------------------------------------------------


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


def test_api_round_trip(app, client, wkey):
    r = client.post("/api/v1/entries", json={"name": "Wiki", "image_repo_url": "https://git.lan/wiki"},
                    headers=wkey)
    assert r.status_code == 201
    body = r.get_json()
    assert body["image_repo_url"] == "https://git.lan/wiki" and body["image_repo_link"] == "https://git.lan/wiki"
    eid = body["id"]
    r = client.patch(f"/api/v1/entries/{eid}", json={"image_repo_url": "https://git.lan/other"}, headers=wkey)
    assert r.status_code == 200 and r.get_json()["image_repo_url"] == "https://git.lan/other"
    r = client.patch(f"/api/v1/entries/{eid}", json={"image_repo_url": None}, headers=wkey)
    assert r.get_json()["image_repo_url"] is None and r.get_json()["image_repo_link"] is None
    assert client.get(f"/api/v1/entries/{eid}", headers=wkey).get_json()["image_repo_url"] is None


def test_api_validation(client, wkey):
    r = client.post("/api/v1/entries", json={"name": "Bad", "image_repo_url": "not a url"}, headers=wkey)
    assert r.status_code == 400
    r = client.post("/api/v1/entries", json={"name": "Ok"}, headers=wkey)
    eid = r.get_json()["id"]
    r = client.patch(f"/api/v1/entries/{eid}", json={"image_repo_url": "javascript:x"}, headers=wkey)
    assert r.status_code == 400


def test_api_derived_link_on_a_docker_entry(app, client, wkey):
    with app.app_context():
        eid = _docker(image_registry="quay.io", image_owner="o", image_name="n")
    body = client.get(f"/api/v1/entries/{eid}", headers=wkey).get_json()
    assert body["image_repo_url"] is None and body["image_repo_link"] == "https://quay.io/repository/o/n"


def test_openapi_lists_the_field(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    schemas = spec["components"]["schemas"]
    assert "image_repo_url" in schemas["EntryPatch"]["properties"]
    assert "image_repo_url" in schemas["EntryCreate"]["properties"]


# --- export / import --------------------------------------------------------------------------


def test_export_carries_the_override_for_every_kind(app):
    with app.app_context():
        _docker(image_repo_url="https://git.lan/d")
        m = ServiceEntry(container_name="shelf", source="manual", last_updated=datetime.now(),
                         image_repo_url="https://git.lan/m")
        none = ServiceEntry(container_name="plain", host="h", source="manual", last_updated=datetime.now())
        db.session.add_all([m, none])
        db.session.commit()
        doc = export_format.build_export(now=datetime(2026, 11, 20, tzinfo=timezone.utc))
    by = {e.identity.container_name: e for e in doc.entries}
    assert by["app"].image_repo_url == "https://git.lan/d"
    assert by["shelf"].image_repo_url == "https://git.lan/m"
    assert by["plain"].image_repo_url is None


def test_import_round_trip_and_ownership(app):
    with app.app_context():
        db.session.add(ServiceEntry(container_name="shelf", source="manual", last_updated=datetime.now()))
        db.session.commit()
    data = minimal(entries=[manual_rec(image_repo_url="https://git.lan/m")])
    parsed = parse(data)
    p = do_plan(app, parsed)
    assert "image_repo_url" in fields(row(p, "entry:manual:/shelf"))
    do_apply(app, parsed)
    with app.app_context():
        assert ServiceEntry.query.one().image_repo_url == "https://git.lan/m"
    assert not do_plan(app, parsed).row("entry:manual:/shelf").fields


def test_import_rejects_a_bad_url(app):
    import importer

    parsed = parse(minimal(entries=[manual_rec(image_repo_url="javascript:alert(1)")]))
    with app.app_context():
        p = importer.plan(parsed, None)
    assert [r.status for r in p.rows] == ["invalid"] or not p.rows
    with app.app_context():
        assert ServiceEntry.query.count() == 0
