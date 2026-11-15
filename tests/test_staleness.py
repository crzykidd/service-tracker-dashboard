"""Unified staleness indicator (v0.6.9, PRD 12.7)."""

from datetime import datetime, timedelta

from extensions import db
from models import ServiceEntry


def _entry(name, age_min=None, **kw):
    last = datetime.now() - timedelta(minutes=age_min) if age_min is not None else None
    e = ServiceEntry(host="h", container_name=name, last_updated=datetime.now(),
                     last_api_update=last, **kw)
    db.session.add(e)
    db.session.commit()
    return e


def test_threshold_boundary(app):
    with app.app_context():
        assert _entry("fresh", 4.9).is_docker_status_stale is False
        assert _entry("old", 5.5).is_docker_status_stale is True


def test_static_never_stale(app):
    with app.app_context():
        assert _entry("s", 600, is_static=True).is_docker_status_stale is False
        assert _entry("s2", None, is_static=True).is_docker_status_stale is False


def test_null_last_api_update_is_stale(app):
    with app.app_context():
        assert _entry("never").is_docker_status_stale is True


def test_setting_is_honored(app):
    with app.app_context():
        e = _entry("x", 10)
        old = app.config.get("stale_after_minutes")
        try:
            app.config["stale_after_minutes"] = 30
            assert e.is_docker_status_stale is False
            app.config["stale_after_minutes"] = 1
            assert e.is_docker_status_stale is True
            app.config["stale_after_minutes"] = "junk"
            assert e.is_docker_status_stale is True  # falls back to 5
        finally:
            app.config["stale_after_minutes"] = old


def test_default_outside_app_context():
    e = ServiceEntry(host="h", container_name="n",
                     last_api_update=datetime.now() - timedelta(minutes=6))
    assert e.is_docker_status_stale is True


def test_indicator_on_all_views(app, admin_client):
    with app.app_context():
        _entry("stale-one", 30)
        _entry("fresh-one", 0)
    for path in ("/", "/tiled_dash", "/compact_dash"):
        body = admin_client.get(path).get_data(as_text=True)
        assert "stale-one" in body, path
        assert "Stale" in body or "stale" in body, path
    for path in ("/", "/compact_dash"):
        body = admin_client.get(path).get_data(as_text=True)
        assert body.count("ti-clock-exclamation") == 1, path
