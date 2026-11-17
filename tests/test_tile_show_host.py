"""tile_show_host: duplicate-name host labels on Tiled/Compact (v0.9.0, PRD 15.5)."""

import logging
from datetime import datetime
from types import SimpleNamespace as NS

import pytest

import settings_loader
from extensions import db
from models import ServiceEntry
from view_helpers import duplicate_name_ids, host_label_ids


def _e(i, name, host, deleted=False):
    return NS(id=i, container_name=name, host=host, deleted_at=datetime.now() if deleted else None)


def test_same_name_different_hosts_marks_both():
    assert duplicate_name_ids([_e(1, "dns", "a"), _e(2, "dns", "b"), _e(3, "uniq", "a")]) == {1, 2}


def test_case_and_whitespace_still_duplicate():
    assert duplicate_name_ids([_e(1, "DNS", "a"), _e(2, " dns ", "b")]) == {1, 2}


def test_deleted_twin_ignored():
    assert duplicate_name_ids([_e(1, "dns", "a"), _e(2, "dns", "b", deleted=True)]) == set()


def test_same_host_twins_not_duplicates():
    assert duplicate_name_ids([_e(1, "dns", "a"), _e(2, "dns", "a")]) == set()


def test_no_host_never_marked_and_not_a_different_host():
    ents = [_e(1, "dns", None), _e(2, "dns", "a"), _e(3, "dns", "")]
    assert duplicate_name_ids(ents) == set()


def test_host_label_modes():
    ents = [_e(1, "dns", "a"), _e(2, "dns", "b"), _e(3, "uniq", "a"), _e(4, "man", None)]
    assert host_label_ids(ents, "never") == set()
    assert host_label_ids(ents, "always") == {1, 2, 3}
    assert host_label_ids(ents, "duplicates") == {1, 2}


# --- settings -------------------------------------------------------------------


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    path = tmp_path / "settings.yml"
    monkeypatch.setattr(settings_loader, "CONFIG_PATH", str(path))
    monkeypatch.setattr(settings_loader, "EXAMPLE_DEST", str(tmp_path / "ex.yml"))
    for key in settings_loader.VALID_KEYS:
        monkeypatch.delenv(key.upper(), raising=False)
    return path


def test_setting_default(settings_file):
    assert settings_loader.load_settings()[0]["tile_show_host"] == "duplicates"


def test_setting_env_override_normalised(settings_file, monkeypatch):
    settings_file.write_text("tile_show_host: never\n")
    monkeypatch.setenv("TILE_SHOW_HOST", "  ALWAYS ")
    final, from_env, _ = settings_loader.load_settings()
    assert final["tile_show_host"] == "always" and "tile_show_host" in from_env


def test_setting_invalid_falls_back_with_warning(settings_file, caplog):
    settings_file.write_text("tile_show_host: sometimes\n")
    with caplog.at_level(logging.WARNING, logger="settings_loader"):
        final, _, _ = settings_loader.load_settings()
    assert final["tile_show_host"] == "duplicates"
    assert "tile_show_host" in caplog.text


# --- views ----------------------------------------------------------------------


def _seed():
    for name, host in (("technitium", "em-dns01"), ("technitium", "em-dns02"),
                       ("soloapp", "em-solo"), ("manualthing", None)):
        db.session.add(ServiceEntry(
            host=host, container_name=name, source="notifier" if host else "manual",
            internalurl="http://i", last_updated=datetime.now()))
    db.session.commit()


def _page(client, url, app, mode):
    old = app.config.get("tile_show_host")
    app.config["tile_show_host"] = mode
    try:
        return client.get(url).get_data(as_text=True)
    finally:
        app.config["tile_show_host"] = old


def _host_shown(html, host, view):
    marker = 'class="tile-host"' if view == "tiled" else 'class="host-name"'
    return f'{marker} title="{host}"' in html


@pytest.mark.parametrize("view,url", [("tiled", "/tiled_dash"), ("compact", "/compact_dash")])
def test_views_per_mode(app, admin_client, view, url):
    with app.app_context():
        _seed()
    dup = _page(admin_client, url, app, "duplicates")
    assert _host_shown(dup, "em-dns01", view) and _host_shown(dup, "em-dns02", view)
    assert not _host_shown(dup, "em-solo", view)
    alw = _page(admin_client, url, app, "always")
    assert all(_host_shown(alw, h, view) for h in ("em-dns01", "em-dns02", "em-solo"))
    nev = _page(admin_client, url, app, "never")
    assert not any(_host_shown(nev, h, view) for h in ("em-dns01", "em-dns02", "em-solo"))


@pytest.mark.parametrize("view,url", [("tiled", "/tiled_dash"), ("compact", "/compact_dash")])
def test_filter_does_not_hide_duplicate(app, admin_client, view, url):
    """Filtering to one host's entry must still label it (computed over all active)."""
    with app.app_context():
        _seed()
    html = _page(admin_client, url + "?status=unknown&source=notifier", app, "duplicates")
    assert _host_shown(html, "em-dns01", view)
    # Soft-delete the twin: the survivor is now unique and loses its label.
    with app.app_context():
        e = ServiceEntry.query.filter_by(host="em-dns02").one()
        e.deleted_at = datetime.now()
        db.session.commit()
    html = _page(admin_client, url, app, "duplicates")
    assert not _host_shown(html, "em-dns01", view)
