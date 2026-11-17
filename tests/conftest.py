"""Shared pytest fixtures.

`app.py` builds the Flask app at import (`app = create_app()`), and that
import reads `STD_CONFIG_DIR` and the settings env vars. So the test
environment is configured here, at conftest import time, *before* anything
imports `app`. All tests share one temp config dir and one app; the
`clean_db` autouse fixture resets the DB between tests.
"""

import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

TEST_TOKEN = "test-token"
CONFIG_DIR = tempfile.mkdtemp(prefix="std-test-config-")

os.environ["STD_CONFIG_DIR"] = CONFIG_DIR
os.environ["API_TOKEN"] = TEST_TOKEN
# Make sure the developer's shell can't leak settings into the suite.
for _key in (
    "BACKUP_PATH", "BACKUP_DAYS_TO_KEEP", "STD_DOZZLE_URL",
    "URL_HEALTHCHECK_INTERVAL", "WIDGET_BACKGROUND_RELOAD", "USER_SESSION_LENGTH",
    "FLASK_DEBUG",
):
    os.environ.pop(_key, None)

# settings.example.yml is copied by relative path at startup.
os.chdir(REPO_ROOT)

ADMIN_USER = "admin"
ADMIN_PASSWORD = "test-admin-pw"


@pytest.fixture(scope="session")
def app():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    # CSRF is off for the general suite; tests/test_csrf.py turns it on.
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.app_context():
        from extensions import db

        db.create_all()
    return flask_app


@pytest.fixture(autouse=True)
def clean_db(app):
    """Empty every table before each test (and keep tests off the network)."""
    from extensions import db

    with app.app_context():
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
    yield


@pytest.fixture(autouse=True)
def no_icon_fetch(monkeypatch):
    """register would otherwise try to download an icon over the network."""
    import routes_api

    def fake_resolve(image_raw=None, image_icon_override=None, fallback_name=None, **kwargs):
        return {
            "registry": None,
            "owner": None,
            "image_name": fallback_name,
            "image_tag": None,
            "image_icon": image_icon_override,
        }

    monkeypatch.setattr(routes_api, "resolve_image_metadata", fake_resolve)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def register(client, auth_headers):
    """Return a helper that POSTs an authed register payload."""

    def _register(payload=None, headers=None, **fields):
        body = {"host": "host1", "container_name": "svc1"}
        body.update(payload or {})
        body.update(fields)
        return client.post(
            "/api/v1/register",
            json=body,
            headers=auth_headers if headers is None else headers,
        )

    return _register


@pytest.fixture
def admin_client(app):
    """A test client logged in as an admin user (for UI-route tests)."""
    from extensions import db
    from models import User

    with app.app_context():
        user = User(username=ADMIN_USER, email="admin@example.com", is_admin=True, is_active=True)
        user.set_password(ADMIN_PASSWORD)
        db.session.add(user)
        db.session.commit()

    c = app.test_client()
    resp = c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD})
    assert resp.status_code == 302
    return c


@pytest.fixture(autouse=True)
def no_update_check_network(monkeypatch):
    """Page renders start the GitHub update check; keep tests off the network
    and off background threads. Tests that exercise it patch these themselves."""
    import version_check

    version_check.reset()
    monkeypatch.setattr(version_check, "_spawn", lambda target: None)
    monkeypatch.setattr(
        version_check, "_http_get",
        lambda url, headers: (_ for _ in ()).throw(AssertionError("test reached GitHub")),
    )
    yield
    version_check.reset()


@pytest.fixture(autouse=True)
def no_mqtt_sockets():
    """Notification tests inject a fake paho client; anything else must never
    open a real connection. The publisher thread is not started in tests."""
    import notify

    notify.reset()

    def refuse(client_id):
        raise AssertionError("test tried to open a real MQTT client")

    notify.set_client_factory(refuse)
    yield
    notify.reset()
