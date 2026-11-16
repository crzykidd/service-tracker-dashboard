"""Per-service health-check options (PRD 12.8)."""

import warnings
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import jobs
from extensions import db
from models import ServiceEntry, ensure_url_checks


def _entry(timeout=None, verify=True):
    """A check-shaped object: probe_url reads timeout_seconds / verify_tls."""
    return SimpleNamespace(timeout_seconds=timeout, verify_tls=verify)


def _check_entry(**kw):
    e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now(), **kw)
    ensure_url_checks(e)
    db.session.add(e)
    db.session.commit()
    return e


def test_global_timeout_used_when_entry_blank():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 200
        assert jobs.probe_url("http://x", _entry(), default_timeout=9)["status"] == "200"
    assert get.call_args.kwargs["timeout"] == 9


def test_entry_timeout_wins():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 204
        jobs.probe_url("http://x", _entry(timeout=30), default_timeout=9)
    assert get.call_args.kwargs["timeout"] == 30


def test_verify_flag_passed_through():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 200
        jobs.probe_url("https://x", _entry(verify=True), 5)
        assert get.call_args.kwargs["verify"] is True
        jobs.probe_url("https://x", _entry(verify=False), 5)
        assert get.call_args.kwargs["verify"] is False


def test_warning_suppressed_only_when_verify_false():
    from urllib3.exceptions import InsecureRequestWarning

    def warn(*a, **k):
        warnings.warn("insecure", InsecureRequestWarning, stacklevel=2)
        return SimpleNamespace(status_code=200)

    with patch("jobs.requests.get", side_effect=warn):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            jobs.probe_url("https://x", _entry(verify=False), 5)
            assert not caught
            jobs.probe_url("https://x", _entry(verify=True), 5)
            assert len(caught) == 1


def test_error_status():
    with patch("jobs.requests.get", side_effect=OSError("boom")):
        out = jobs.probe_url("http://x", _entry(), 5)
        assert out["status"] == "Error: OSError" and out["ok"] is False
        assert out["status_code"] is None and out["message"] == "Error: OSError"


def test_status_code_ok_threshold():
    for code, ok in ((200, True), (399, True), (400, False), (503, False)):
        with patch("jobs.requests.get") as get:
            get.return_value.status_code = code
            out = jobs.probe_url("http://x", _entry(), 5)
        assert out["ok"] is ok and out["status_code"] == code


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
