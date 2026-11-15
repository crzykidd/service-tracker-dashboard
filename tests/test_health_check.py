"""Per-service health-check options (PRD 12.8)."""

import warnings
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import jobs
from extensions import db
from models import ServiceEntry


def _entry(timeout=None, verify=True):
    return SimpleNamespace(health_check_timeout=timeout, health_check_verify_tls=verify)


def test_global_timeout_used_when_entry_blank():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 200
        assert jobs.check_url("http://x", _entry(), default_timeout=9) == "200"
    assert get.call_args.kwargs["timeout"] == 9


def test_entry_timeout_wins():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 204
        jobs.check_url("http://x", _entry(timeout=30), default_timeout=9)
    assert get.call_args.kwargs["timeout"] == 30


def test_verify_flag_passed_through():
    with patch("jobs.requests.get") as get:
        get.return_value.status_code = 200
        jobs.check_url("https://x", _entry(verify=True), 5)
        assert get.call_args.kwargs["verify"] is True
        jobs.check_url("https://x", _entry(verify=False), 5)
        assert get.call_args.kwargs["verify"] is False


def test_warning_suppressed_only_when_verify_false():
    from urllib3.exceptions import InsecureRequestWarning

    def warn(*a, **k):
        warnings.warn("insecure", InsecureRequestWarning, stacklevel=2)
        return SimpleNamespace(status_code=200)

    with patch("jobs.requests.get", side_effect=warn):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            jobs.check_url("https://x", _entry(verify=False), 5)
            assert not caught
            jobs.check_url("https://x", _entry(verify=True), 5)
            assert len(caught) == 1


def test_error_status():
    with patch("jobs.requests.get", side_effect=OSError("boom")):
        assert jobs.check_url("http://x", _entry(), 5) == "Error: OSError"


def test_model_defaults(app):
    with app.app_context():
        e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now())
        db.session.add(e)
        db.session.commit()
        assert e.health_check_timeout is None
        assert e.health_check_verify_tls is True


def test_register_does_not_touch_options(app, register):
    register(container_name="keep")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="keep").one()
        e.health_check_timeout = 20
        e.health_check_verify_tls = False
        db.session.commit()
    register(container_name="keep", image="nginx:1")
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="keep").one()
        assert e.health_check_timeout == 20
        assert e.health_check_verify_tls is False


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
        assert e.health_check_timeout == 15
        assert e.health_check_verify_tls is False  # checkbox absent

    admin_client.post(f"/edit/{eid}", data={**base, "health_check_timeout": "999",
                                            "health_check_verify_tls": "on"})
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert e.health_check_timeout == 15  # invalid value rejected
        assert e.health_check_verify_tls is True

    admin_client.post(f"/edit/{eid}", data={**base, "health_check_timeout": ""})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).health_check_timeout is None


def test_to_dict_round_trips_fields(app):
    with app.app_context():
        e = ServiceEntry(host="h", container_name="c", last_updated=datetime.now(), health_check_timeout=12,
                         health_check_verify_tls=False)
        db.session.add(e)
        db.session.commit()
        d = e.to_dict()
    assert d["health_check_timeout"] == 12
    assert d["health_check_verify_tls"] is False
