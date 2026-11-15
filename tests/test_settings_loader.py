"""Settings loader precedence and known bugs (PRD §12.3)."""

import pytest

import settings_loader


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the loader at a temp settings.yml; returns a writer."""
    path = tmp_path / "settings.yml"
    monkeypatch.setattr(settings_loader, "CONFIG_PATH", str(path))
    monkeypatch.setattr(settings_loader, "EXAMPLE_DEST", str(tmp_path / "settings.example.yml"))
    for key in settings_loader.VALID_KEYS:
        monkeypatch.delenv(key.upper(), raising=False)

    def write(text):
        path.write_text(text)

    return write


def test_default_when_unset(settings_file):
    final, from_env, from_file = settings_loader.load_settings()
    assert final["url_healthcheck_interval"] == 300
    assert from_env == {} and from_file == {}


def test_file_beats_default(settings_file):
    settings_file("url_healthcheck_interval: 42\n")
    final, _, from_file = settings_loader.load_settings()
    assert final["url_healthcheck_interval"] == 42
    assert from_file["url_healthcheck_interval"] == 42


def test_env_beats_file(settings_file, monkeypatch):
    settings_file("url_healthcheck_interval: 42\n")
    monkeypatch.setenv("URL_HEALTHCHECK_INTERVAL", "7")
    final, from_env, _ = settings_loader.load_settings()
    assert final["url_healthcheck_interval"] == 7
    assert from_env["url_healthcheck_interval"] == 7


def test_default_backup_path_follows_config_dir(settings_file):
    final, _, _ = settings_loader.load_settings()
    assert final["backup_path"] == f"{settings_loader.CONFIG_DIR}/backups"


# --- Known v0.6.8 bugs: PRD §12.3 (prompt v069-03) removes these xfail marks ---


@pytest.mark.xfail(strict=True, reason="PRD §12.3: settings.yml keys missing from VALID_KEYS are dropped")
def test_file_only_keys_reach_config(settings_file):
    settings_file("widget_value_retention_days: 30\nregister_field_ownership: notifier_wins\n")
    final, _, _ = settings_loader.load_settings()
    assert final.get("widget_value_retention_days") == 30
    assert final.get("register_field_ownership") == "notifier_wins"


@pytest.mark.xfail(strict=True, reason="PRD §12.3: unset api_token makes 'Bearer None' a valid credential")
def test_unset_api_token_rejects_bearer_none(app, register):
    original = app.config["api_token"]
    app.config["api_token"] = None
    try:
        resp = register(headers={"Authorization": "Bearer None"})
        assert resp.status_code in (401, 503)
    finally:
        app.config["api_token"] = original
