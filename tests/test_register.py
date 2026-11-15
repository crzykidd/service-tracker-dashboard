"""Register contract tests, written against v0.6.8 behavior."""

import pytest

import settings_store
import synthesizer
from extensions import db
from models import Group, ServiceEntry, ServiceExposure

TRAEFIK = {"layer": "traefik", "hostname": "svc.example.com", "tls": True}


def _entry():
    return ServiceEntry.query.filter_by(host="host1", container_name="svc1").one()


def _set_layers(layers):
    settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS, layers)
    db.session.commit()


# --- auth -----------------------------------------------------------------


def test_register_correct_token(app, register):
    resp = register()
    assert 200 <= resp.status_code < 300
    with app.app_context():
        assert _entry().container_name == "svc1"


@pytest.mark.parametrize("headers", [
    {"Authorization": "Bearer wrong"},
    {"Authorization": "test-token"},
    {},
])
def test_register_bad_or_missing_token(register, headers):
    resp = register(headers=headers)
    assert resp.status_code == 401


# --- extra="forbid" -------------------------------------------------------


def test_unknown_top_level_key_rejected(register):
    resp = register(bogus="x")
    assert resp.status_code == 400
    assert "bogus" in resp.get_json()["unknown_keys"]


def test_unknown_nested_key_rejected(register):
    resp = register(exposure_observations=[{"layer": "traefik", "bogus": 1}])
    assert resp.status_code == 400
    resp = register(networks=[{"name": "n", "bogus": 1}])
    assert resp.status_code == 400


# --- exposure_observations absent vs [] -----------------------------------


def test_absent_observations_preserve_rows(app, register):
    register(exposure_observations=[TRAEFIK])
    register()  # key absent
    with app.app_context():
        assert ServiceExposure.query.count() == 1


def test_empty_observations_clear_rows(app, register):
    register(exposure_observations=[TRAEFIK])
    with app.app_context():
        assert ServiceExposure.query.count() == 1
    register(exposure_observations=[])
    with app.app_context():
        assert ServiceExposure.query.count() == 0


# --- URL provenance --------------------------------------------------------


def test_synthesis_sets_synthesized_source(app, register):
    with app.app_context():
        _set_layers({"traefik": "internal"})
    register(exposure_observations=[TRAEFIK])
    with app.app_context():
        e = _entry()
        assert e.internalurl == "https://svc.example.com/"
        assert e.internalurl_source == synthesizer.SOURCE_SYNTHESIZED


def test_explicit_label_beats_synthesized(app, register):
    with app.app_context():
        _set_layers({"traefik": "internal"})
    register(exposure_observations=[TRAEFIK])
    register(internalurl="http://label.example/")
    with app.app_context():
        e = _entry()
        assert e.internalurl == "http://label.example/"
        assert e.internalurl_source == synthesizer.SOURCE_EXPLICIT_LABEL
    # A later synthesis pass must not displace the explicit label.
    register(exposure_observations=[TRAEFIK])
    with app.app_context():
        assert _entry().internalurl == "http://label.example/"


def test_ui_edit_never_overwritten_by_register_or_synthesis(app, register):
    with app.app_context():
        _set_layers({"traefik": "internal"})
    register()
    with app.app_context():
        e = _entry()
        e.internalurl = "http://mine.example/"
        e.internalurl_source = synthesizer.SOURCE_UI_EDIT
        db.session.commit()
    register(internalurl="http://label.example/", exposure_observations=[TRAEFIK])
    with app.app_context():
        e = _entry()
        assert e.internalurl == "http://mine.example/"
        assert e.internalurl_source == synthesizer.SOURCE_UI_EDIT


def test_clearing_url_in_ui_resets_source(app, register, admin_client):
    register(internalurl="http://label.example/")
    with app.app_context():
        e = _entry()
        assert e.internalurl_source == synthesizer.SOURCE_EXPLICIT_LABEL
        entry_id = e.id
    resp = admin_client.post(
        f"/edit/{entry_id}",
        data={
            "host": "host1",
            "container_name": "svc1",
            "internalurl": "",
            "externalurl": "",
            "widget_name": "none",
            "group_mode": "none",
        },
    )
    assert resp.status_code == 302
    with app.app_context():
        e = _entry()
        assert e.internalurl is None
        assert e.internalurl_source is None


# --- register_field_ownership ---------------------------------------------


def _group_name(app):
    with app.app_context():
        e = _entry()
        return Group.query.get(e.group_id).group_name if e.group_id else None


def test_user_wins_preserves_existing_group_and_priority(app, register):
    app.config["register_field_ownership"] = "user_wins"
    register(group_name="first", sort_priority=1)
    register(group_name="second", sort_priority=2)
    assert _group_name(app) == "first"
    with app.app_context():
        e = _entry()
        assert e.sort_priority == 1
        # The notifier's latest report is still captured.
        assert e.notifier_reported_group_name == "second"
        assert e.notifier_reported_sort_priority == 2


def test_notifier_wins_overwrites_group_and_priority(app, register):
    app.config["register_field_ownership"] = "notifier_wins"
    try:
        register(group_name="first", sort_priority=1)
        register(group_name="second", sort_priority=2)
        assert _group_name(app) == "second"
        with app.app_context():
            assert _entry().sort_priority == 2
    finally:
        app.config["register_field_ownership"] = "user_wins"
