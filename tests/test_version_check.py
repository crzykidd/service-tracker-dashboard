"""Version in the UI: build channel, display strings, the GitHub update check
(mocked HTTP only), the header, the status endpoint and the API fields."""

import threading
import time

import pytest
import requests

import app as app_module
import settings_store
import version_check
from extensions import db
from tests.test_mgmt_api_keys import _bearer, _key

SHA = "0123456789abcdef0123456789abcdef01234567"


# --- read_version_info ----------------------------------------------------------

def _patch_open(monkeypatch, text):
    import builtins
    real = builtins.open

    def fake(path, *a, **k):
        if path == "/app/version.txt":
            if text is None:
                raise FileNotFoundError(path)
            import io
            return io.StringIO(text)
        return real(path, *a, **k)

    monkeypatch.setattr(builtins, "open", fake)


def test_read_version_info_without_file_defaults(monkeypatch):
    _patch_open(monkeypatch, None)
    info = app_module.read_version_info()
    assert info["channel"] == "local" and info["commit"] == "unknown"
    assert info["build_time"] == "unknown" and info["version"] not in ("", None)


def test_read_version_info_file_without_channel(monkeypatch):
    _patch_open(monkeypatch, f"version=0.9.0\ncommit={SHA}\nbuild_time=2026-01-01T00:00:00Z\n")
    info = app_module.read_version_info()
    assert info == {"version": "0.9.0", "commit": SHA, "build_time": "2026-01-01T00:00:00Z",
                    "channel": "local"}


def test_read_version_info_reads_channel(monkeypatch):
    _patch_open(monkeypatch, "version=0.9.0\ncommit=abc\nchannel=release\nbuild_time=x\n")
    assert app_module.read_version_info()["channel"] == "release"


# --- display strings ------------------------------------------------------------

@pytest.mark.parametrize("channel,commit,label,text", [
    ("release", SHA, "v0.9.0", "v0.9.0"),
    ("main", SHA, "v0.9.0 · main", "v0.9.0 · main+sha-0123456"),
    ("dev", SHA, "dev · 0.9.0", "dev · 0.9.0+sha-0123456"),
    ("pr", SHA, "dev · 0.9.0", "dev · 0.9.0+sha-0123456"),
    ("local", "unknown", "dev · 0.9.0", "dev · 0.9.0"),
    ("weird", "unknown", "dev · 0.9.0", "dev · 0.9.0"),
])
def test_display_info(channel, commit, label, text):
    d = version_check.display_info({"version": "0.9.0", "commit": commit, "channel": channel})
    assert d["label"] == label and d["text"] == text
    if channel in ("dev", "pr", "main"):
        assert d["sha_url"] == f"https://github.com/crzykidd/service-tracker-dashboard/commit/{SHA}"
    else:
        assert d["sha_url"] is None


# --- semver comparison ----------------------------------------------------------

@pytest.mark.parametrize("latest,running,expected", [
    ("0.9.1", "0.9.0", True),
    ("0.10.0", "0.9.9", True),
    ("0.9.0", "0.9.0", False),
    ("0.9.0", "0.9.0+sha-abc1234", False),   # dev build of the same version
    ("0.8.0", "0.9.0", False),
    ("v1.0.0", "0.9.0", True),
    ("garbage", "0.9.0", False),
    ("0.9.1", "unknown", False),
    (None, "0.9.0", False),
])
def test_is_newer(latest, running, expected):
    assert version_check.is_newer(latest, running) is expected


# --- cache / refresh ------------------------------------------------------------

class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body, headers or {}

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


RELEASE = {"tag_name": "v0.9.5", "html_url": "https://github.com/x/y/releases/tag/v0.9.5",
           "draft": False, "prerelease": False}


@pytest.fixture
def http(monkeypatch):
    calls = []
    box = {"resp": FakeResp(200, RELEASE, {"ETag": 'W/"1"'})}

    def fake_get(url, headers):
        calls.append((url, headers))
        if isinstance(box["resp"], Exception):
            raise box["resp"]
        return box["resp"]

    monkeypatch.setattr(version_check, "_http_get", fake_get)
    return calls, box


@pytest.fixture
def spawned(monkeypatch):
    started = []
    monkeypatch.setattr(version_check, "_spawn", lambda target: started.append(target))
    return started


def test_stale_cache_starts_one_refresh_only(app, spawned):
    with app.app_context():
        version_check.maybe_refresh(app)
        version_check.maybe_refresh(app)   # second page load while one is in flight
        assert len(spawned) == 1
        version_check._inflight.release()  # the stub never runs _run
        version_check.maybe_refresh(app)
        assert len(spawned) == 2


def test_fresh_cache_starts_no_refresh(app, spawned, http):
    with app.app_context():
        version_check.refresh_now("0.9.0")
        version_check.maybe_refresh(app)
        assert spawned == []


def test_refresh_runs_in_a_background_thread_and_page_does_not_wait(app, monkeypatch, http):
    calls, _ = http
    done = threading.Event()
    gate = threading.Event()
    real_http = version_check._http_get

    def slow(url, headers):
        gate.wait(5)
        return real_http(url, headers)

    monkeypatch.setattr(version_check, "_http_get", slow)
    real_spawn = threading.Thread

    def spawn(target):
        def run():
            target()
            done.set()
        real_spawn(target=run, daemon=True).start()

    monkeypatch.setattr(version_check, "_spawn", spawn)
    with app.app_context():
        t0 = time.time()
        version_check.maybe_refresh(app)
        assert time.time() - t0 < 1          # returned without waiting on "GitHub"
        assert version_check.status("0.9.0")["latest_version"] is None
    gate.set()
    assert done.wait(5)
    with app.app_context():
        assert version_check.status("0.9.0")["latest_version"] == "0.9.5"
    assert len(calls) == 1


def test_refresh_success_sets_status_and_persists(app, http):
    calls, _ = http
    with app.app_context():
        version_check.refresh_now("0.9.0")
        s = version_check.status("0.9.0")
        assert s["latest_version"] == "0.9.5" and s["update_available"] is True
        assert s["release_url"] == RELEASE["html_url"] and s["checked_at"]
        assert settings_store.get_update_check_cache()["latest_version"] == "0.9.5"
        # same version running: no update
        assert version_check.status("0.9.5")["update_available"] is False
        assert version_check.status("0.9.5")["release_url"] is None
    url, headers = calls[0]
    assert url.endswith("/repos/crzykidd/service-tracker-dashboard/releases/latest")
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["User-Agent"] == "service-tracker-dashboard/0.9.0"
    assert "Authorization" not in headers


def test_persisted_result_survives_restart_without_refetch(app, spawned, http):
    with app.app_context():
        version_check.refresh_now("0.9.0")
        version_check.reset()                # simulates a process restart
        version_check.maybe_refresh(app)     # loads the persisted cache: still fresh
        assert spawned == []
        assert version_check.status("0.9.0")["latest_version"] == "0.9.5"


def test_error_keeps_last_good_value_and_backs_off(app, http):
    calls, box = http
    with app.app_context():
        version_check.refresh_now("0.9.0")
        good = version_check.status("0.9.0")
        box["resp"] = FakeResp(500)
        before = time.time()
        version_check.refresh_now("0.9.0")
        s = version_check.status("0.9.0")
        assert s["latest_version"] == good["latest_version"]
        assert s["checked_at"] == good["checked_at"]
        assert "500" in s["last_error"]
        first_wait = version_check._state["next_check_at"] - before
        assert first_wait >= 2 * 6 * 3600 - 5
        version_check.refresh_now("0.9.0")
        second_wait = version_check._state["next_check_at"] - before
        assert second_wait > first_wait
        for _ in range(10):
            version_check.refresh_now("0.9.0")
        assert version_check._state["next_check_at"] - time.time() <= 24 * 3600 + 5
        box["resp"] = requests.ConnectionError("boom")
        version_check.refresh_now("0.9.0")
        assert "request failed" in version_check.status("0.9.0")["last_error"]
        box["resp"] = FakeResp(200, RELEASE)
        version_check.refresh_now("0.9.0")
        assert version_check.status("0.9.0")["last_error"] is None


def test_rate_limit_headers_extend_the_backoff(app, http):
    _, box = http
    reset_at = time.time() + 5 * 24 * 3600
    box["resp"] = FakeResp(403, None, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_at)})
    with app.app_context():
        version_check.refresh_now("0.9.0")
        assert version_check._state["next_check_at"] >= reset_at
        box["resp"] = FakeResp(429, None, {"Retry-After": "172800"})
        version_check.refresh_now("0.9.0")
        assert version_check._state["next_check_at"] >= time.time() + 172000


def test_not_modified_keeps_value_and_sends_etag(app, http):
    calls, box = http
    with app.app_context():
        version_check.refresh_now("0.9.0")
        box["resp"] = FakeResp(304)
        version_check.refresh_now("0.9.0")
        assert calls[1][1]["If-None-Match"] == 'W/"1"'
        assert version_check.status("0.9.0")["latest_version"] == "0.9.5"


def test_prerelease_and_draft_are_ignored(app, http):
    _, box = http
    box["resp"] = FakeResp(200, {**RELEASE, "prerelease": True})
    with app.app_context():
        version_check.refresh_now("0.9.0")
        assert version_check.status("0.9.0")["update_available"] is False


def test_disabled_means_no_fetch(app, spawned, http):
    calls, _ = http
    with app.app_context():
        settings_store.save_update_check_settings(False, 6)
        db.session.commit()
        version_check.maybe_refresh(app)
        version_check.refresh_now("0.9.0")
        s = version_check.status("0.9.0")
    assert spawned == [] and calls == []
    assert s["enabled"] is False and s["update_available"] is False and s["latest_version"] is None


# --- header ---------------------------------------------------------------------

def test_header_renders_version_and_update_link(app, admin_client, http):
    with app.app_context():
        version_check.refresh_now("0.9.0")
    saved = dict(app.config["VERSION_INFO"])
    app.config["VERSION_INFO"] = {**saved, "channel": "dev", "commit": SHA, "version": "0.9.0"}
    try:
        html = admin_client.get("/").get_data(as_text=True)
    finally:
        app.config["VERSION_INFO"] = saved
    assert 'id="std-version-btn"' in html and "dev · 0.9.0" in html
    assert f"/commit/{SHA}" in html and "sha-0123456" in html
    assert "update available" in html and RELEASE["html_url"] in html
    assert 'id="std-update-link"' in html
    link = html.split('id="std-update-link"')[1].split(">")[0]
    assert "hidden" not in link


def test_header_hides_update_link_when_current_or_disabled(app, admin_client):
    html = admin_client.get("/").get_data(as_text=True)
    link = html.split('id="std-update-link"')[1].split(">")[0]
    assert "hidden" in link
    assert 'data-update-enabled="true"' in html
    with app.app_context():
        settings_store.save_update_check_settings(False, 6)
        db.session.commit()
    html = admin_client.get("/").get_data(as_text=True)
    assert 'data-update-enabled="false"' in html


def test_release_header_has_no_sha_link(app, admin_client):
    saved = dict(app.config["VERSION_INFO"])
    app.config["VERSION_INFO"] = {**saved, "channel": "release", "commit": SHA}
    try:
        html = admin_client.get("/").get_data(as_text=True)
    finally:
        app.config["VERSION_INFO"] = saved
    assert f">v{saved['version']}</button>" in html and "/commit/" not in html


# --- endpoints ------------------------------------------------------------------

def test_status_endpoint_requires_login(client):
    r = client.get("/api/update-status")
    assert r.status_code in (302, 401)


def test_status_endpoint_returns_cached_status(app, admin_client, http, spawned, monkeypatch):
    # The fake release (0.9.5) must be newer than the running version.
    monkeypatch.setitem(app.config, "VERSION_INFO", {**app.config["VERSION_INFO"], "version": "0.9.0"})
    with app.app_context():
        version_check.refresh_now("0.9.0")
    r = admin_client.get("/api/update-status")
    assert r.status_code == 200
    body = r.get_json()
    assert body["latest_version"] == "0.9.5" and body["update_available"] is True
    assert spawned == []  # cache fresh


def test_status_endpoint_starts_refresh_when_stale(admin_client, spawned):
    assert admin_client.get("/api/update-status").status_code == 200
    assert len(spawned) >= 1


def test_settings_page_about_and_form(app, admin_client, http):
    with app.app_context():
        version_check.refresh_now("0.9.0")
    html = admin_client.get("/settings").get_data(as_text=True)
    assert "Latest release seen" in html and "v0.9.5" in html and "Last checked" in html
    r = admin_client.post("/settings/update-check",
                          data={"update_check_interval_hours": "12"})  # box unchecked = off
    assert r.status_code == 302
    with app.app_context():
        assert settings_store.get_update_check_settings() == (False, 12)
    assert "Update check disabled" in admin_client.get("/settings").get_data(as_text=True)
    r = admin_client.post("/settings/update-check",
                          data={"update_check_enabled": "1", "update_check_interval_hours": "0"})
    with app.app_context():
        assert settings_store.get_update_check_settings() == (False, 12)


def test_settings_defaults(app):
    with app.app_context():
        assert settings_store.get_update_check_settings() == (True, 6)


# --- management API -------------------------------------------------------------

def test_whoami_and_config_carry_build_and_update_fields(app, client, http, monkeypatch):
    # The fake release (0.9.5) must be newer than the running version.
    monkeypatch.setitem(app.config, "VERSION_INFO", {**app.config["VERSION_INFO"], "version": "0.9.0"})
    with app.app_context():
        version_check.refresh_now("0.9.0")
    _, full = _key(app, "reader", "read")
    for path in ("/api/v1/whoami", "/api/v1/config"):
        body = client.get(path, headers=_bearer(full)).get_json()
        assert set(body["update"]) == {"enabled", "latest_version", "update_available",
                                       "release_url", "checked_at"}
        assert body["update"]["latest_version"] == "0.9.5"
        assert body["update"]["update_available"] is True
        assert {"commit", "channel", "build_time", "version"} <= set(body)


def test_update_check_settings_api(app, client):
    _, rk = _key(app, "r", "read")
    _, wk = _key(app, "w", "write")
    url = "/api/v1/settings/update-check"
    assert client.get(url, headers=_bearer(rk)).get_json() == {"enabled": True, "interval_hours": 6}
    assert client.put(url, json={"enabled": False}, headers=_bearer(rk)).status_code == 403
    r = client.put(url, json={"enabled": False, "interval_hours": 3}, headers=_bearer(wk))
    assert r.status_code == 200 and r.get_json() == {"enabled": False, "interval_hours": 3}
    r = client.put(url, json={"interval_hours": 8}, headers=_bearer(wk))
    assert r.get_json() == {"enabled": False, "interval_hours": 8}   # omitted keeps its value
    for bad in ({}, {"interval_hours": 0}, {"interval_hours": "x"}, {"bogus": 1}):
        assert client.put(url, json=bad, headers=_bearer(wk)).status_code == 400
    me = client.get("/api/v1/whoami", headers=_bearer(rk)).get_json()
    assert me["update"]["enabled"] is False
