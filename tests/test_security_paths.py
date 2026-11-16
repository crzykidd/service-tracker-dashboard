"""Path-injection and open-redirect guards (v0.6.9, PRD 12.11)."""

import os
from datetime import datetime

import pytest

import image_utils
import routes_api
from extensions import db
from image_utils import icon_path_in_dir, safe_icon_filename
from models import ServiceEntry
from view_helpers import safe_redirect_target


class _Resp:
    status_code = 200
    content = b"<svg/>"


@pytest.fixture
def fetched(monkeypatch):
    """Mock icon downloads everywhere; record the URLs requested."""
    urls = []

    def fake_get(url, *a, **kw):
        urls.append(url)
        return _Resp()

    monkeypatch.setattr(image_utils.requests, "get", fake_get)
    import routes_dashboard

    monkeypatch.setattr(routes_dashboard.requests, "get", fake_get)
    return urls


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _, m in sess.get("_flashes", [])]


def _outside_files(image_dir):
    parent = os.path.dirname(image_dir)
    return sorted(
        os.path.join(r, f)
        for r, _, fs in os.walk(parent)
        for f in fs
        if not os.path.realpath(os.path.join(r, f)).startswith(os.path.realpath(image_dir) + os.sep)
        and f.endswith(".svg")
    )


# --- icon sanitiser ----------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    ("plex", "plex.svg"),
    ("Plex.SVG", "plex.svg"),
    ("my-app_2.v1", "my-app_2.v1.svg"),
    ("a" * 96, "a" * 96 + ".svg"),
])
def test_icon_sanitiser_accepts(name, expected):
    assert safe_icon_filename(name) == expected


@pytest.mark.parametrize("name", [
    "../x", "a/b", "..", "/etc/passwd", "..\\x", ".hidden", "a..b", "",
    ".svg", "a" * 97, "a b", None, 5,
])
def test_icon_sanitiser_rejects(name):
    assert safe_icon_filename(name) is None


def test_icon_path_confined(tmp_path):
    assert icon_path_in_dir(str(tmp_path), "ok.svg").startswith(str(tmp_path.resolve()) + os.sep)
    assert icon_path_in_dir(str(tmp_path), "../x.svg") is None


# --- register / add / edit ---------------------------------------------------


def test_register_traversal_icon_still_succeeds(app, monkeypatch, register, fetched):
    monkeypatch.setattr(routes_api, "resolve_image_metadata", image_utils.resolve_image_metadata)
    image_dir = app.config["IMAGE_DIR"]
    resp = register(image_icon="../../evil.svg", image_name="nginx")
    assert 200 <= resp.status_code < 300
    assert fetched == []
    assert _outside_files(image_dir) == []
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="svc1").one().image_icon is None


def test_register_good_icon_downloaded(app, monkeypatch, register, fetched):
    monkeypatch.setattr(routes_api, "resolve_image_metadata", image_utils.resolve_image_metadata)
    resp = register(image_icon="sectest-icon", image_name="nginx")
    assert 200 <= resp.status_code < 300
    path = os.path.join(app.config["IMAGE_DIR"], "sectest-icon.svg")
    assert os.path.exists(path)
    os.remove(path)


def test_add_bad_icon_flashes_and_writes_nothing(app, admin_client, fetched):
    resp = admin_client.post("/add", data={
        "host": "h", "container_name": "newapp", "icon_image": "../../evil",
    })
    assert resp.status_code == 200
    assert "Invalid icon name" in resp.get_data(as_text=True)
    assert fetched == []
    assert _outside_files(app.config["IMAGE_DIR"]) == []
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="newapp").first() is None


def _make_entry():
    e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now(),
                     is_static=True, image_icon="keep.svg")
    db.session.add(e)
    db.session.commit()
    return e.id


def test_edit_bad_icon_flashes_and_writes_nothing(app, admin_client, fetched):
    with app.app_context():
        eid = _make_entry()
    resp = admin_client.post(f"/edit/{eid}", data={
        "host": "h", "container_name": "c", "is_static": "on", "widget_name": "none",
        "image_icon": "../../evil",
    })
    assert resp.status_code == 302
    assert any("Invalid icon name" in m for m in _flashes(admin_client))
    assert fetched == []
    assert _outside_files(app.config["IMAGE_DIR"]) == []
    with app.app_context():
        assert ServiceEntry.query.get(eid).image_icon == "keep.svg"


# --- restore / widget_config -------------------------------------------------


@pytest.mark.parametrize("name", ["../x.yml", "sub/x.yml", "/etc/passwd", "notes.txt"])
def test_restore_rejects_bad_filenames(admin_client, name):
    resp = admin_client.post("/settings", data={
        "action": "restore", "restore_source": "server", "server_backup_filename": name,
    }, follow_redirects=True)
    assert "Invalid server filename selected." in resp.get_data(as_text=True)


def test_restore_accepts_plain_backup_name(app, admin_client):
    path = os.path.join(app.config["backup_path"], "sectest.yml")
    with open(path, "w") as f:
        f.write("[]\n")
    try:
        resp = admin_client.post("/settings", data={
            "action": "restore", "restore_source": "server", "server_backup_filename": "sectest.yml",
        }, follow_redirects=True)
        assert "Invalid server filename" not in resp.get_data(as_text=True)
    finally:
        os.remove(path)


def test_widget_config_traversal_returns_empty(admin_client):
    for name in ("..%2f..", "..%2f..%2fetc", "nope"):
        resp = admin_client.get(f"/widget_config/{name}")
        # Encoded slashes may 404 at routing; either way no file is read.
        assert resp.status_code == 404 or resp.get_json() == []
    assert admin_client.get("/widget_config/nope").get_json() == []
    assert admin_client.get("/widget_config/..").get_json() == []


def test_widget_config_known_widget(admin_client):
    resp = admin_client.get("/widget_config/sonarr")
    assert resp.status_code == 200
    assert isinstance(resp.get_json(), list)


# --- redirects ---------------------------------------------------------------


@pytest.mark.parametrize("target,expected", [
    ("https://evil", "/"),
    ("//evil", "/"),
    ("/\\evil", "/"),
    ("javascript:alert(1)", "/"),
    ("evil.com", "/"),
    ("", "/"),
    (None, "/"),
    ("/tiled_dash?x=1", "/tiled_dash?x=1"),
    ("/", "/"),
])
def test_safe_redirect_target(app, target, expected):
    with app.test_request_context():
        assert safe_redirect_target(target, "/") == expected


def test_edit_save_with_external_ref_goes_to_dashboard(app, admin_client):
    with app.app_context():
        eid = _make_entry()
    resp = admin_client.post(f"/edit/{eid}?ref=https://evil", data={
        "host": "h", "container_name": "c", "is_static": "on", "widget_name": "none",
    })
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_edit_save_with_local_ref_kept(app, admin_client):
    with app.app_context():
        eid = _make_entry()
    resp = admin_client.post(f"/edit/{eid}?ref=/compact_dash?x=1", data={
        "host": "h", "container_name": "c", "is_static": "on", "widget_name": "none",
    })
    assert resp.headers["Location"] == "/compact_dash?x=1"


def test_edit_delete_with_external_ref_goes_to_dashboard(app, admin_client):
    with app.app_context():
        eid = _make_entry()
    resp = admin_client.post(f"/edit/{eid}?ref=//evil.example", data={
        "delete": "1", "delete_confirmation": "c",
    })
    assert resp.headers["Location"] == "/"
