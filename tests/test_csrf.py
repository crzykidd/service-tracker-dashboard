"""CSRF protection on UI POSTs (v0.6.9, PRD 12.4)."""

import re

import pytest

ADMIN_USER = "admin"
ADMIN_PASSWORD = "test-admin-pw"


@pytest.fixture
def csrf_on(app):
    app.config["WTF_CSRF_ENABLED"] = True
    yield
    app.config["WTF_CSRF_ENABLED"] = False


def _token(client, path="/login"):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf-token" content="([^"]+)"', html)
    assert m, "csrf meta tag missing"
    return m.group(1)


def test_form_post_without_token_redirects_with_flash(csrf_on, client):
    resp = client.post(
        "/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD},
        headers={"Referer": "http://localhost/login"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/login")
    with client.session_transaction() as sess:
        flashes = [m for _, m in sess.get("_flashes", [])]
    assert any("stale" in m for m in flashes)


def test_json_post_without_token_returns_400(csrf_on, client):
    resp = client.post("/entries/1/delete", json={})
    assert resp.status_code == 400
    assert resp.get_json() == {"error": "CSRF token missing or invalid"}


def test_fetch_post_without_token_returns_400(csrf_on, client):
    resp = client.post("/entries/1/delete", headers={"Accept": "application/json"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "CSRF token missing or invalid"


def test_login_form_with_token_succeeds(csrf_on, app):
    from extensions import db
    from models import User

    with app.app_context():
        u = User(username=ADMIN_USER, email="a@example.com", is_admin=True, is_active=True)
        u.set_password(ADMIN_PASSWORD)
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    token = _token(c)
    resp = c.post(
        "/login",
        data={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "csrf_token": token},
    )
    assert resp.status_code == 302
    assert not resp.headers["Location"].endswith("/login")


def test_header_token_accepted_on_delete(csrf_on, app):
    from extensions import db
    from models import User

    with app.app_context():
        u = User(username=ADMIN_USER, email="a@example.com", is_admin=True, is_active=True)
        u.set_password(ADMIN_PASSWORD)
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    token = _token(c)
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "csrf_token": token})
    token = _token(c, "/settings")
    # Passes CSRF; the entry doesn't exist so the view answers 404 (not 400).
    resp = c.post("/entries/999/delete", headers={"X-CSRFToken": token})
    assert resp.status_code != 400


def test_register_stays_exempt(csrf_on, register):
    resp = register()
    assert resp.status_code in (200, 201)
