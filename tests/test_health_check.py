"""Per-service health-check options (PRD 12.8)."""

import warnings
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import checker
from extensions import db
from models import ServiceEntry, ensure_url_checks


def _check_entry(**kw):
    e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now(), **kw)
    ensure_url_checks(e)
    db.session.add(e)
    db.session.commit()
    return e


def test_probe_passes_timeout_and_verify():
    with patch("checker.requests.get") as get:
        get.return_value.status_code = 200
        checker.probe_http("http://x", "status", 9, True)
        assert get.call_args.kwargs["timeout"] == 9
        assert get.call_args.kwargs["verify"] is True
        checker.probe_http("https://x", "status", 30, False)
        assert get.call_args.kwargs["timeout"] == 30
        assert get.call_args.kwargs["verify"] is False


def test_warning_suppressed_only_when_verify_false():
    from urllib3.exceptions import InsecureRequestWarning

    def warn(*a, **k):
        warnings.warn("insecure", InsecureRequestWarning, stacklevel=2)
        return SimpleNamespace(status_code=200)

    with patch("checker.requests.get", side_effect=warn):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            checker.probe_http("https://x", "status", 5, False)
            assert not caught
            checker.probe_http("https://x", "status", 5, True)
            assert len(caught) == 1


def test_error_status():
    with patch("checker.requests.get", side_effect=OSError("boom")):
        out = checker.probe_http("http://x", "status", 5, True)
        assert out.ok is False and out.status_code is None
        assert out.message == "OSError: boom" and checker.legacy_status(out) == "Error: OSError"


def test_status_code_ok_threshold():
    for code, ok in ((200, True), (399, True), (400, False), (503, False)):
        with patch("checker.requests.get") as get:
            get.return_value.status_code = code
            out = checker.probe_http("http://x", "status", 5, True)
        assert out.ok is ok and out.status_code == code


def test_model_defaults(app):
    with app.app_context():
        e = _check_entry()
        assert e.url_check_timeout is None
        assert e.url_check_verify_tls is True
        assert e.internal_check_enabled is False and e.external_check_enabled is False


def test_register_does_not_touch_options(app, register):
    register(container_name="keep")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="keep").one()
        for c in e.checks:
            c.timeout_seconds = 20
            c.verify_tls = False
        db.session.commit()
    register(container_name="keep", image="nginx:1")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="keep").one()
        assert e.url_check_timeout == 20
        assert e.url_check_verify_tls is False


def test_edit_form_saves_and_validates(app, admin_client):
    with app.app_context():
        e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now(), is_static=True)
        db.session.add(e)
        db.session.commit()
        eid = e.id
    base = {"host": "h", "container_name": "c", "is_static": "on", "widget_name": "none"}

    admin_client.post(f"/edit/{eid}", data={**base, "health_check_timeout": "15"})
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.url_check("internal").timeout_seconds == 15
        assert e.url_check("external").timeout_seconds == 15
        assert e.url_check("internal").verify_tls is False  # checkbox absent

    admin_client.post(f"/edit/{eid}", data={**base, "health_check_timeout": "999",
                                            "health_check_verify_tls": "on"})
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.url_check_timeout == 15  # invalid value rejected
        assert e.url_check("external").verify_tls is True

    admin_client.post(f"/edit/{eid}", data={**base, "health_check_timeout": ""})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).url_check_timeout is None


def test_to_dict_round_trips_fields(app):
    with app.app_context():
        e = _check_entry()
        for c in e.checks:
            c.timeout_seconds = 12
            c.verify_tls = False
        db.session.commit()
        d = e.to_dict()
    assert d["health_check_timeout"] == 12
    assert d["health_check_verify_tls"] is False
