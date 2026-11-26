"""Optional Docker Hub login for the image update check: Basic only to the auth.docker.io
realm, anonymous otherwise, write-only token everywhere."""

import base64
import logging
from datetime import datetime, timezone

import pytest

import export_format
import image_update
import registry_client
from extensions import db
from registry_client import ERR_HUB_LOGIN, ERR_LOGIN, RegistryClient, RegistryError
from tests.test_image_updates import FakeRegistry, Resp
from tests.test_mgmt_api_keys import _bearer, _key

USER = "hubuser"
TOKEN = "dckr_pat_SUPERSECRET123"
BASIC = "Basic " + base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()
D1 = "sha256:" + "a" * 64


class HubRegistry:
    """A registry host that demands a Bearer token from the given realm."""

    def __init__(self, realm, registry_host="registry-1.docker.io", token_status=200):
        self.realm = realm
        self.host = registry_host
        self.token_status = token_status
        self.calls = []
        self.redirect_to = None

    def __call__(self, method, url, headers=None, params=None, timeout=None, allow_redirects=False):
        from urllib.parse import urlparse
        u = urlparse(url)
        headers = dict(headers or {})
        self.calls.append({"method": method, "url": url, "host": u.hostname, "headers": headers,
                           "allow_redirects": allow_redirects})
        if u.hostname == self.host:
            if headers.get("Authorization", "").startswith("Bearer "):
                return Resp(200, {"Docker-Content-Digest": D1})
            return Resp(401, {"WWW-Authenticate": f'Bearer realm="{self.realm}",service="s"'})
        if self.redirect_to:
            return Resp(302, {"Location": self.redirect_to})
        return Resp(self.token_status, body={"token": "tok", "expires_in": 300})

    def token_calls(self):
        return [c for c in self.calls if c["host"] != self.host]


def head(fake, registry="docker.io", login=(USER, TOKEN)):
    client = RegistryClient(http=fake, dockerhub_login=login)
    return client.head_manifest(registry, "library/nginx", "1.0")


# --- the client --------------------------------------------------------------------------------


def test_basic_goes_only_to_the_docker_hub_token_realm():
    fake = HubRegistry("https://auth.docker.io/token")
    assert head(fake) == D1
    (call,) = fake.token_calls()
    assert call["headers"]["Authorization"] == BASIC
    # never to the registry itself
    assert all(c["headers"].get("Authorization") != BASIC for c in fake.calls if c["host"] == fake.host)


@pytest.mark.parametrize("registry,host", [
    ("ghcr.io", "ghcr.io"), ("quay.io", "quay.io"), ("lscr.io", "lscr.io")])
def test_never_sent_to_another_registry_even_with_the_hub_realm(registry, host):
    fake = HubRegistry("https://auth.docker.io/token", registry_host=host)
    head(fake, registry=registry)
    (call,) = fake.token_calls()
    assert "Authorization" not in call["headers"]


@pytest.mark.parametrize("realm", [
    "https://auth.example/token",
    "https://auth.docker.io.evil.example/token",
    "https://evil.example/auth.docker.io",
    "https://auth.docker.io@evil.example/token",
    "https://user:pw@auth.docker.io/token",
    "https://auth.docker.io:8443/token",
    "https://AUTH2.docker.io/token",
])
def test_never_sent_to_a_different_realm_host(realm):
    fake = HubRegistry(realm)
    head(fake)
    for call in fake.token_calls():
        assert "Authorization" not in call["headers"]


def test_a_non_https_realm_is_refused_and_nothing_is_sent():
    fake = HubRegistry("http://auth.docker.io/token")
    with pytest.raises(RegistryError):
        head(fake)
    assert fake.token_calls() == []


def test_never_followed_to_a_redirect_target():
    fake = HubRegistry("https://auth.docker.io/token")
    fake.token_status = 302
    fake.redirect_to = "https://evil.example/steal"
    with pytest.raises(RegistryError):
        head(fake)
    assert all(c["host"] != "evil.example" for c in fake.calls)
    assert all(c["allow_redirects"] is False for c in fake.calls)


@pytest.mark.parametrize("login", [None, (USER, ""), ("", TOKEN), (USER, None), (None, None)])
def test_anonymous_when_unconfigured_or_half_configured(login):
    fake = HubRegistry("https://auth.docker.io/token")
    head(fake, login=login)
    (call,) = fake.token_calls()
    assert "Authorization" not in call["headers"]


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_login_is_a_fixed_error_and_never_retried_anonymously(status):
    fake = HubRegistry("https://auth.docker.io/token", token_status=status)
    with pytest.raises(RegistryError) as exc:
        head(fake)
    assert exc.value.message == ERR_HUB_LOGIN
    assert TOKEN not in exc.value.message and USER not in exc.value.message
    assert len(fake.token_calls()) == 1           # no anonymous retry


def test_an_anonymous_token_rejection_keeps_the_old_message():
    fake = HubRegistry("https://auth.docker.io/token", token_status=401)
    with pytest.raises(RegistryError) as exc:
        head(fake, login=None)
    assert exc.value.message == ERR_LOGIN


def test_manifests_stay_head_only_on_docker_hub():
    fake = HubRegistry("https://auth.docker.io/token")
    head(fake)
    assert {c["method"] for c in fake.calls if c["host"] == fake.host} == {"HEAD"}


# --- the login test ----------------------------------------------------------------------------


def test_login_test_asks_only_auth_docker_io():
    fake = HubRegistry("https://auth.docker.io/token")
    status, message = RegistryClient(http=fake).test_dockerhub_login(USER, TOKEN)
    assert status == registry_client.LOGIN_OK and message == registry_client.LOGIN_MESSAGES["ok"]
    (call,) = fake.calls
    assert call["host"] == "auth.docker.io" and call["headers"]["Authorization"] == BASIC
    assert "/v2/" not in call["url"]


@pytest.mark.parametrize("code,expected", [(401, "rejected"), (403, "rejected"), (429, "unexpected"),
                                           (500, "unexpected")])
def test_login_test_statuses(code, expected):
    fake = HubRegistry("x", token_status=code)
    status, message = RegistryClient(http=fake).test_dockerhub_login(USER, TOKEN)
    assert status == expected and TOKEN not in message


def test_login_test_unreachable():
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError(f"secret {TOKEN}")

    status, message = RegistryClient(http=boom).test_dockerhub_login(USER, TOKEN)
    assert status == "unreachable" and TOKEN not in message


# --- resolution: env > UI > settings.yml -------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch):
    for name in (image_update.ENV_DOCKERHUB_USERNAME, image_update.ENV_DOCKERHUB_TOKEN,
                 image_update.ENV_DOCKERHUB_TOKEN_FILE):
        monkeypatch.delenv(name, raising=False)


def set_file(app, monkeypatch, **values):
    monkeypatch.setitem(app.config, "CONFIG_FROM_FILE", {**app.config.get("CONFIG_FROM_FILE", {}), **{
        k: v for k, v in values.items()}})
    for k, v in values.items():
        monkeypatch.setitem(app.config, k, v)


def test_unset_is_not_configured(app, clean_env):
    with app.app_context():
        st = image_update.dockerhub_status()
        assert st["configured"] is False and st["source"] is None and image_update.dockerhub_credentials() is None


def test_yml_then_ui_then_env(app, clean_env, monkeypatch):
    with app.app_context():
        set_file(app, monkeypatch, dockerhub_username="fileuser", dockerhub_token="filetok")
        assert image_update.dockerhub_credentials() == ("fileuser", "filetok")
        assert image_update.dockerhub_status()["source"] == "file"

        image_update.save_dockerhub("uiuser", "uitok")
        db.session.commit()
        assert image_update.dockerhub_credentials() == ("uiuser", "uitok")
        assert image_update.dockerhub_status()["source"] == "ui"

        monkeypatch.setenv(image_update.ENV_DOCKERHUB_USERNAME, "envuser")
        assert image_update.dockerhub_credentials() == ("envuser", "uitok")
        assert image_update.dockerhub_status()["source"] == "mixed"
        monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN, "envtok")
        assert image_update.dockerhub_credentials() == ("envuser", "envtok")
        assert image_update.dockerhub_status()["source"] == "env"


def test_token_file_and_token_wins_over_file(app, clean_env, monkeypatch, tmp_path):
    secret = tmp_path / "tok"
    secret.write_text(" filetoken \n")
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_USERNAME, "u")
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN_FILE, str(secret))
    with app.app_context():
        assert image_update.dockerhub_credentials() == ("u", "filetoken")
        monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN, "direct")
        assert image_update.dockerhub_credentials() == ("u", "direct")


def test_an_unreadable_token_file_is_not_configured_and_logs_only_the_name(app, clean_env, monkeypatch, caplog):
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_USERNAME, "u")
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN_FILE, "/nonexistent/secret")
    with app.app_context(), caplog.at_level(logging.DEBUG):
        assert image_update.dockerhub_credentials() is None
    assert "/nonexistent/secret" not in caplog.text


def test_half_configured_is_not_configured(app, clean_env, monkeypatch):
    with app.app_context():
        image_update.save_dockerhub("onlyuser", None)
        db.session.commit()
        st = image_update.dockerhub_status()
        assert st["configured"] is False and st["username_set"] and not st["token_set"]
        assert st["username"] is None
        assert image_update.dockerhub_credentials() is None


def test_the_run_builds_its_client_with_the_resolved_login(app, clean_env, monkeypatch):
    seen = {}

    class Spy(RegistryClient):
        def __init__(self, *a, **k):
            seen.update(k)
            super().__init__(*a, **k)

    monkeypatch.setattr(image_update, "RegistryClient", Spy)
    from models import ServiceEntry
    reg = FakeRegistry()
    reg.digests[("registry-1.docker.io", "library/nginx", "1.4.2")] = D1
    reg.tags[("registry-1.docker.io", "library/nginx")] = ["1.4.2"]
    monkeypatch.setattr(image_update, "_HTTP_OVERRIDE", reg)
    with app.app_context():
        image_update.save_settings(enabled=True)
        image_update.save_dockerhub(USER, TOKEN)
        db.session.add(ServiceEntry(host="h", container_name="n", source="notifier",
                                    last_updated=datetime.now(), image_ref="docker.io/library/nginx:1.4.2"))
        db.session.commit()
        image_update.execute(app, image_update.RunPlan("test", everything=True))
    assert seen["dockerhub_login"] == (USER, TOKEN)


# --- the token never leaves -------------------------------------------------------------------


@pytest.fixture
def saved(app, clean_env):
    with app.app_context():
        image_update.save_dockerhub(USER, TOKEN)
        db.session.commit()


def test_settings_html_never_carries_the_token(admin_client, saved):
    html = admin_client.get("/settings").get_data(as_text=True)
    assert TOKEN not in html and "SUPERSECRET" not in html
    assert USER in html and "Login set" in html and "Settings" in html
    assert "type=\"password\"" in html


def test_config_table_masks_the_token_from_yml(app, admin_client, clean_env, monkeypatch):
    monkeypatch.setitem(app.config["LOADED_SETTINGS"], "dockerhub_token", "FILETOKEN")
    html = admin_client.get("/settings").get_data(as_text=True)
    assert "FILETOKEN" not in html


def test_env_values_render_read_only(app, admin_client, clean_env, monkeypatch):
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_USERNAME, "envuser")
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN, "ENVTOKEN")
    html = admin_client.get("/settings").get_data(as_text=True)
    assert "ENVTOKEN" not in html and html.count("Set by environment") >= 2
    assert "readonly" in html


def test_api_returns_status_but_never_the_token(app, client, saved):
    key = _bearer(_key(app, "reader", "read")[1])
    resp = client.get("/api/v1/settings/image-updates", headers=key)
    body = resp.get_json()
    assert body["dockerhub"] == {"configured": True, "username": USER, "source": "ui"}
    assert TOKEN not in resp.get_data(as_text=True)
    cfg = client.get("/api/v1/config", headers=key)
    assert TOKEN not in cfg.get_data(as_text=True)


def test_the_token_cannot_be_set_through_the_api(app, client, clean_env):
    key = _bearer(_key(app, "writer", "write")[1])
    resp = client.put("/api/v1/settings/image-updates", json={"dockerhub_token": "x"}, headers=key)
    assert resp.status_code == 400
    with app.app_context():
        assert image_update.dockerhub_status()["token_set"] is False


def test_openapi_documents_the_dockerhub_block(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    assert "dockerhub" in str(spec["components"]["schemas"]["ImageUpdateSettingsOut"])


def test_export_never_carries_the_login(app, saved):
    with app.app_context():
        doc = export_format.build_export(now=datetime(2026, 11, 26, tzinfo=timezone.utc))
        text = export_format.dump(doc, "json")
        text = text.decode() if isinstance(text, bytes) else text
    assert TOKEN not in text and "dockerhub" not in text.lower()


def test_the_loader_does_not_log_the_token(tmp_path, monkeypatch, caplog):
    import settings_loader
    monkeypatch.setenv("STD_DOCKERHUB_TOKEN", TOKEN)
    monkeypatch.setenv("STD_DOCKERHUB_USERNAME", USER)
    with caplog.at_level(logging.DEBUG):
        final, from_env, _ = settings_loader.load_settings()
    assert final["dockerhub_token"] == TOKEN and "dockerhub_token" in from_env
    assert TOKEN not in caplog.text


def test_the_token_is_not_logged_or_stored_in_errors(app, saved, caplog):
    fake = HubRegistry("https://auth.docker.io/token", token_status=401)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(RegistryError):
            head(fake)
        RegistryClient(http=fake).test_dockerhub_login(USER, TOKEN)
    assert TOKEN not in caplog.text


# --- the Settings routes -----------------------------------------------------------------------


def test_save_keeps_the_token_when_the_field_is_empty(app, admin_client, clean_env):
    admin_client.post("/settings/image-updates/dockerhub", data={"dockerhub_username": USER, "dockerhub_token": TOKEN})
    admin_client.post("/settings/image-updates/dockerhub", data={"dockerhub_username": "renamed", "dockerhub_token": ""})
    with app.app_context():
        assert image_update.dockerhub_credentials() == ("renamed", TOKEN)


def test_save_flash_does_not_echo_the_token(admin_client, clean_env):
    resp = admin_client.post("/settings/image-updates/dockerhub",
                             data={"dockerhub_username": USER, "dockerhub_token": TOKEN}, follow_redirects=True)
    assert TOKEN not in resp.get_data(as_text=True)


def test_save_rejects_whitespace_in_values(app, admin_client, clean_env):
    admin_client.post("/settings/image-updates/dockerhub",
                      data={"dockerhub_username": USER, "dockerhub_token": "has space"})
    with app.app_context():
        assert image_update.dockerhub_status()["token_set"] is False


def test_clear_removes_the_ui_login(app, admin_client, saved):
    admin_client.post("/settings/image-updates/dockerhub", data={"action": "clear"})
    with app.app_context():
        assert image_update.dockerhub_status()["configured"] is False
        assert image_update.dockerhub_status()["username_set"] is False


def test_env_values_are_not_overwritten_by_a_save(app, admin_client, clean_env, monkeypatch):
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_USERNAME, "envuser")
    monkeypatch.setenv(image_update.ENV_DOCKERHUB_TOKEN, "envtok")
    admin_client.post("/settings/image-updates/dockerhub", data={"dockerhub_username": "x", "dockerhub_token": "y"})
    with app.app_context():
        assert image_update.dockerhub_credentials() == ("envuser", "envtok")
        from settings_store import (
            KEY_DOCKERHUB_TOKEN,
            KEY_DOCKERHUB_USERNAME,
            get_image_update_value,
        )
        assert get_image_update_value(KEY_DOCKERHUB_USERNAME) is None
        assert get_image_update_value(KEY_DOCKERHUB_TOKEN) is None


def test_routes_are_admin_only_and_csrf_guarded(client, app):
    assert client.post("/settings/image-updates/dockerhub", data={"action": "clear"}).status_code in (302, 401, 403)
    assert client.post("/settings/image-updates/dockerhub/test").status_code in (302, 401, 403)


@pytest.mark.parametrize("answer,ok", [(registry_client.LOGIN_OK, True), (registry_client.LOGIN_REJECTED, False),
                                       (registry_client.LOGIN_UNREACHABLE, False)])
def test_test_login_route(app, admin_client, clean_env, monkeypatch, answer, ok):
    seen = {}

    def fake(self, username, token):
        seen["args"] = (username, token)
        return answer, registry_client.LOGIN_MESSAGES[answer]

    monkeypatch.setattr(RegistryClient, "test_dockerhub_login", fake)
    resp = admin_client.post("/settings/image-updates/dockerhub/test",
                             data={"dockerhub_username": USER, "dockerhub_token": TOKEN})
    body = resp.get_json()
    assert body["ok"] is ok and body["status"] == answer and TOKEN not in resp.get_data(as_text=True)
    assert seen["args"] == (USER, TOKEN)


def test_test_login_uses_the_stored_token_for_a_blank_field(app, admin_client, saved, monkeypatch):
    seen = {}
    monkeypatch.setattr(RegistryClient, "test_dockerhub_login",
                        lambda self, u, t: (seen.update(args=(u, t)) or ("ok", "ok")))
    admin_client.post("/settings/image-updates/dockerhub/test", data={"dockerhub_username": "", "dockerhub_token": ""})
    assert seen["args"] == (USER, TOKEN)


def test_test_login_without_a_login_is_a_400(admin_client, clean_env):
    resp = admin_client.post("/settings/image-updates/dockerhub/test", data={})
    assert resp.status_code == 400 and resp.get_json()["ok"] is False


def test_the_revision_row():
    from api_version import API_REVISION, API_REVISION_HISTORY
    row = [r for r in API_REVISION_HISTORY if r[0] == 8]
    assert API_REVISION == 8 and row and "dockerhub" in row[0][2]
