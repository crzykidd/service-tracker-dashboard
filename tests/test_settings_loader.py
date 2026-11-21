"""Settings loader precedence, token hardening and credential warnings (PRD §12.3)."""

import pathlib
import re

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


def test_file_only_keys_reach_config(settings_file):
    settings_file("widget_value_retention_days: 30\nregister_field_ownership: notifier_wins\n")
    final, _, _ = settings_loader.load_settings()
    assert final.get("widget_value_retention_days") == 30
    assert final.get("register_field_ownership") == "notifier_wins"


def test_new_key_defaults(settings_file):
    final, _, _ = settings_loader.load_settings()
    assert final["widget_value_retention_days"] == 30
    assert final["register_field_ownership"] == "user_wins"


def test_example_yml_keys_are_all_valid():
    """Every key documented in settings.example.yml (even commented out) must load."""
    text = (pathlib.Path(__file__).resolve().parent.parent / "settings.example.yml").read_text()
    keys = set(re.findall(r"^#?([a-z][a-z0-9_]*):", text, flags=re.M))
    assert keys, "no keys parsed from settings.example.yml"
    assert keys <= set(settings_loader.VALID_KEYS), keys - set(settings_loader.VALID_KEYS)


def test_mask_value():
    assert settings_loader.mask_value("api_token", "secret") == "***"
    assert settings_loader.mask_value("api_token", None) is None
    assert settings_loader.mask_value("backup_path", "/x") == "/x"


def test_api_token_not_logged(settings_file, monkeypatch, caplog):
    monkeypatch.setenv("API_TOKEN", "s3cr3t-value")
    with caplog.at_level("DEBUG", logger="settings_loader"):
        settings_loader.load_settings()
    assert "s3cr3t-value" not in caplog.text


def test_unset_api_token_returns_503(app, register):
    original = app.config["api_token"]
    app.config["api_token"] = None
    try:
        resp = register(headers={"Authorization": "Bearer None"})
        assert resp.status_code == 503
        assert resp.get_json() == {"error": "API token not configured"}
    finally:
        app.config["api_token"] = original


def test_missing_auth_header_is_401(register):
    assert register(headers={}).status_code == 401


def test_default_credential_flags(app, admin_client):
    import routes_auth
    from extensions import db
    from models import User

    # conftest admin uses a non-default password.
    assert routes_auth.refresh_default_password_flag(app) is False
    with app.app_context():
        User.query.filter_by(username="admin").first().set_password("changeme123")
        db.session.commit()
    assert routes_auth.refresh_default_password_flag(app) is True
    assert app.config["DEFAULT_ADMIN_PASSWORD_IN_USE"] is True
    resp = admin_client.get("/settings")
    assert b"Default credentials in use" in resp.data
    app.config["DEFAULT_ADMIN_PASSWORD_IN_USE"] = False


def test_token_missing_notice_on_settings(app, admin_client):
    original = app.config["api_token"]
    app.config["api_token"] = None
    try:
        assert b"API token not set" in admin_client.get("/settings").data
    finally:
        app.config["api_token"] = original


def test_quoted_int_in_file_is_cast(settings_file):
    settings_file('health_check_timeout: "5"\n')
    final, _, from_file = settings_loader.load_settings()
    assert final["health_check_timeout"] == 5 and isinstance(final["health_check_timeout"], int)
    assert from_file["health_check_timeout"] == 5


def test_uncastable_file_value_warns_and_keeps_raw(settings_file, caplog):
    settings_file("health_check_timeout: soon\n")
    with caplog.at_level("WARNING"):
        final, _, _ = settings_loader.load_settings()
    assert final["health_check_timeout"] == "soon"
    assert "health_check_timeout" in caplog.text


def test_bool_strings_are_cast():
    cast = settings_loader.cast_value
    assert cast(bool, "false") is False and cast(bool, "Yes") is True
    assert cast(bool, True) is True
    with pytest.raises(ValueError):
        cast(bool, "maybe")


def test_env_still_beats_quoted_file_value(settings_file, monkeypatch):
    settings_file('health_check_timeout: "5"\n')
    monkeypatch.setenv("HEALTH_CHECK_TIMEOUT", "9")
    final, from_env, from_file = settings_loader.load_settings()
    assert final["health_check_timeout"] == 9 and from_env and not from_file


def test_widget_reload_fallback_is_the_documented_default():
    import jobs
    assert jobs.WIDGET_BACKGROUND_RELOAD_DEFAULT == 900
