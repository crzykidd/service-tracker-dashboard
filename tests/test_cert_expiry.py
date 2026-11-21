"""Certificate-expiry condition on HTTPS checks (v0.9.0, PRD 15.2): probe,
validation, form, job write-back, API, MCP, detail payload and migration. No
real network: the TLS handshake is `checker._read_cert_expiry`, patched here
(one test builds a real throwaway certificate to cover the DER parsing)."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import check_form
import checker
import jobs
from extensions import db
from health_history import check_payload
from models import HealthCheck, ServiceEntry, ensure_url_checks
from tests.test_check_config_ui import _form, _make, _services, _svc
from tests.test_mcp_server import Fake, call, std_mcp
from tests.test_mgmt_api_keys import _alembic, _bearer, _key

EMMETT = "https://em-pve01.crzynet.me:8006/"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _in(days=0.0, hours=0.0):
    """An aware-UTC expiry that many days (and hours) from now."""
    return datetime.now(timezone.utc) + timedelta(days=days, hours=hours)


def _response(code=200):
    r = MagicMock()
    r.status_code = code
    return r


def _probe(target=EMMETT, expiry=None, code=200, cert_min_days=7, verify=True, handshake=None, **kw):
    """Run probe_http with requests.get and the handshake patched; returns
    (result, requests.get mock, handshake mock)."""
    with patch("checker.requests.get", return_value=_response(code)) as get, \
         patch("checker._read_cert_expiry", **(handshake or {"return_value": expiry})) as hs:
        out = checker.probe_http(target, timeout=3, verify=verify, cert_min_days=cert_min_days, **kw)
    return out, get, hs


# --- probe ---------------------------------------------------------------------


def test_passes_above_the_minimum_and_reports_the_expiry():
    expiry = _in(days=30, hours=1)
    out, get, hs = _probe(expiry=expiry)
    assert out.ok and out.message is None and out.status_code == 200
    assert out.cert_expires_at == expiry.replace(tzinfo=None)  # naive UTC
    hs.assert_called_once_with("em-pve01.crzynet.me", 8006, 3)


def test_fails_below_the_minimum_with_the_exact_message():
    out, _, _ = _probe(expiry=_in(days=5, hours=1))
    assert (out.ok, out.message, out.status_code) == (False, "cert expires in 5 days (min 7)", 200)
    assert out.cert_expires_at is not None


def test_days_left_is_floored():
    out, _, _ = _probe(expiry=_in(days=2, hours=23))
    assert out.message == "cert expires in 2 days (min 7)"
    out, _, _ = _probe(expiry=_in(hours=5))
    assert out.message == "cert expires in 0 days (min 7)"


def test_exactly_the_minimum_passes():
    out, _, _ = _probe(expiry=_in(days=7, hours=1))
    assert out.ok


def test_already_expired_message():
    out, _, _ = _probe(expiry=_in(days=-3, hours=-2))
    assert (out.ok, out.message) == (False, "cert expired 3 days ago")


def test_http_failure_keeps_its_message_and_still_reports_the_expiry():
    expiry = _in(days=30)
    out, _, hs = _probe(expiry=expiry, code=503)
    assert (out.ok, out.message, out.status_code) == (False, "503", 503)
    assert out.cert_expires_at == expiry.replace(tzinfo=None)
    hs.assert_called_once()
    # A short cert does not replace the HTTP failure message either.
    out, _, _ = _probe(expiry=_in(days=1), code=503)
    assert out.message == "503"


def test_http_exception_keeps_its_message_when_the_handshake_also_fails():
    with patch("checker.requests.get", side_effect=OSError("refused")), \
         patch("checker._read_cert_expiry", side_effect=OSError("refused")):
        out = checker.probe_http(EMMETT, timeout=3, cert_min_days=7)
    assert out.ok is False and out.message == "OSError: refused" and out.cert_expires_at is None


def test_handshake_failure_gives_cert_check_failed():
    out, _, _ = _probe(handshake={"side_effect": TimeoutError("timed out")})
    assert out.ok is False and out.status_code == 200 and out.cert_expires_at is None
    assert out.message == "cert check failed: TimeoutError: timed out"


def test_http_scheme_skips_the_handshake():
    out, _, hs = _probe(target="http://em-pve01.crzynet.me:8006/", expiry=_in(days=1))
    assert out.ok and out.cert_expires_at is None
    hs.assert_not_called()


def test_no_condition_skips_the_handshake():
    for off in (None, 0):
        out, _, hs = _probe(expiry=_in(days=1), cert_min_days=off)
        assert out.ok and out.cert_expires_at is None
        hs.assert_not_called()


def test_works_with_verify_off_and_the_default_port():
    expiry = _in(days=30)
    out, get, hs = _probe(target="https://nas.lan/health", expiry=expiry, verify=False)
    assert out.ok and out.cert_expires_at is not None
    assert get.call_args.kwargs["verify"] is False
    hs.assert_called_once_with("nas.lan", 443, 3)


def test_body_mode_failure_message_is_kept():
    r = _response(200)
    r.iter_content.return_value = [b"Error: disk full"]
    with patch("checker.requests.get", return_value=r), \
         patch("checker._read_cert_expiry", return_value=_in(days=30)):
        out = checker.probe_http(EMMETT, mode="body", timeout=3, cert_min_days=7)
    assert (out.ok, out.message) == (False, "disk full")


def test_run_probe_passes_cert_min_days():
    job = {"check_type": "http", "target": EMMETT, "mode": "status", "timeout": 5, "verify": False,
           "cert_min_days": 7}
    with patch("checker.requests.get", return_value=_response()), \
         patch("checker._read_cert_expiry", return_value=_in(days=5, hours=1)):
        assert checker.run_probe(job).message == "cert expires in 5 days (min 7)"
    job.pop("cert_min_days")
    with patch("checker.requests.get", return_value=_response()), \
         patch("checker._read_cert_expiry") as hs:
        assert checker.run_probe(job).ok
    hs.assert_not_called()


def test_emmett_parity_case():
    """https://em-pve01.crzynet.me:8006/ answering 200 with a self-signed cert
    (verify off) and cert_min_days=7."""
    job = {"check_type": "http", "target": EMMETT, "timeout": 5, "verify": False, "cert_min_days": 7}
    with patch("checker.requests.get", return_value=_response(200)), \
         patch("checker._read_cert_expiry", return_value=_in(days=30, hours=1)):
        out = checker.run_probe(job)
    assert out.ok is True and out.cert_expires_at is not None
    with patch("checker.requests.get", return_value=_response(200)), \
         patch("checker._read_cert_expiry", return_value=_in(days=5, hours=1)):
        out = checker.run_probe(job)
    assert (out.ok, out.message) == (False, "cert expires in 5 days (min 7)")


def test_read_cert_expiry_parses_a_real_der_certificate():
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "em-pve01.crzynet.me")])
    not_after = datetime(2027, 2, 1, 12, 0, 0)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(datetime(2026, 1, 1))
            .not_valid_after(not_after).sign(key, hashes.SHA256()))
    der = cert.public_bytes(serialization.Encoding.DER)

    tls = MagicMock()
    tls.getpeercert.return_value = der
    tls.__enter__.return_value = tls
    context = MagicMock()
    context.wrap_socket.return_value = tls
    sock = MagicMock()
    sock.__enter__.return_value = sock
    with patch("checker.ssl.create_default_context", return_value=context), \
         patch("checker.socket.create_connection", return_value=sock) as conn:
        got = checker._read_cert_expiry("em-pve01.crzynet.me", 8006, 4)
    assert got == not_after.replace(tzinfo=timezone.utc)
    conn.assert_called_once_with(("em-pve01.crzynet.me", 8006), timeout=4)
    context.wrap_socket.assert_called_once_with(sock, server_hostname="em-pve01.crzynet.me")
    tls.getpeercert.assert_called_once_with(binary_form=True)
    # Verification is off so a self-signed or expired certificate can be read.
    assert context.check_hostname is False
    import ssl
    assert context.verify_mode == ssl.CERT_NONE


def test_read_cert_expiry_failure_modes_raise_into_the_probe():
    tls = MagicMock()
    tls.getpeercert.return_value = None
    tls.__enter__.return_value = tls
    context = MagicMock()
    context.wrap_socket.return_value = tls
    sock = MagicMock()
    sock.__enter__.return_value = sock
    with patch("checker.ssl.create_default_context", return_value=context), \
         patch("checker.socket.create_connection", return_value=sock), \
         pytest.raises(Exception, match="no certificate"):
        checker._read_cert_expiry("h", 443, 1)


# --- job write-back ---------------------------------------------------------------


def _entry_with_check(**kw):
    e = ServiceEntry(host=None, container_name="pve", source="manual", last_updated=datetime.now())
    db.session.add(e)
    db.session.flush()
    fields = {"service_entry_id": e.id, "kind": "service", "name": "PVE", "check_type": "http",
              "target": EMMETT, "enabled": True, "verify_tls": False, "cert_min_days": 7, **kw}
    c = HealthCheck(**fields)
    db.session.add(c)
    db.session.commit()
    db.session.refresh(e)
    return e, c


def test_due_jobs_carry_cert_min_days(app):
    with app.app_context():
        _, c = _entry_with_check()
        (job,) = [j for j in jobs.select_due_jobs(app) if j["check_id"] == c.id]
    assert job["cert_min_days"] == 7 and job["verify"] is False


def test_write_back_sets_and_clears_last_cert_expires_at(app):
    with app.app_context():
        _, c = _entry_with_check()
        out, _, _ = _probe(expiry=_in(days=30, hours=1))
        jobs.record_check_result(c, out)
        db.session.commit()
        assert c.last_cert_expires_at is not None and c.last_ok is True
        assert abs((c.last_cert_expires_at - _utcnow()).days - 30) <= 1

        # No condition any more: the next result carries no expiry, so it clears.
        c.cert_min_days = None
        no_cond = checker.ProbeResult(True, 5, 200)
        jobs.record_check_result(c, no_cond)
        assert c.last_cert_expires_at is None

        # A plain http target never reports one.
        c.cert_min_days = 7
        c.target = "http://em-pve01.crzynet.me:8006/"
        out, _, hs = _probe(target=c.target, expiry=_in(days=30))
        jobs.record_check_result(c, out)
        assert c.last_cert_expires_at is None
        hs.assert_not_called()


def test_failing_cert_check_marks_the_check_down_with_the_message(app):
    with app.app_context():
        _, c = _entry_with_check()
        out, _, _ = _probe(expiry=_in(days=5, hours=1))
        jobs.record_check_result(c, out)
        db.session.commit()
        assert (c.last_ok, c.last_message, c.consecutive_failures) == (False, "cert expires in 5 days (min 7)", 1)


def test_url_check_job_uses_the_current_url_scheme(app):
    with app.app_context():
        e = ServiceEntry(host=None, container_name="u", source="manual", last_updated=datetime.now(),
                         internalurl=EMMETT)
        db.session.add(e)
        db.session.flush()
        ensure_url_checks(e)
        chk = e.url_check("internal")
        chk.enabled, chk.cert_min_days = True, 7
        db.session.commit()
        (job,) = [j for j in jobs.select_due_jobs(app) if j["check_id"] == chk.id]
        assert job["target"] == EMMETT and job["cert_min_days"] == 7
        # The URL changes to http: the stored condition stays, the probe ignores it.
        e.internalurl = "http://em-pve01.crzynet.me:8006/"
        db.session.commit()
        (job,) = [j for j in jobs.select_due_jobs(app) if j["check_id"] == chk.id]
    with patch("checker.requests.get", return_value=_response()), patch("checker._read_cert_expiry") as hs:
        out = checker.run_probe(job)
    assert out.ok and out.cert_expires_at is None
    hs.assert_not_called()


# --- validation ----------------------------------------------------------------------


@pytest.mark.parametrize("raw,ok,value", [
    (None, True, None), ("", True, None), ("  ", True, None), ("1", True, 1), (" 7 ", True, 7),
    ("365", True, 365), (30, True, 30), ("0", False, None), (0, False, None), ("366", False, None),
    (366, False, None), ("-1", False, None), ("1.5", False, None), ("abc", False, None),
    (True, False, None), (2.5, False, None),
])
def test_cert_min_days_bounds(raw, ok, value):
    values, errors = check_form.validate_url_check_settings({"cert_min_days": raw})
    assert (errors == []) is ok
    assert values["cert_days_value"] == value
    if not ok:
        assert errors[0]["field"] == "cert_min_days" and "1 to 365" in errors[0]["message"]


def test_service_validation_allows_http_only():
    base = {"target": EMMETT, "cert_min_days": 7}
    values, errors = check_form.validate_service_check({"check_type": "http", **base})
    assert errors == [] and values["cert_days_value"] == 7
    for kind, target in (("tcp", "h:22"), ("ping", "h"), ("dns", "10.0.0.1")):
        extra = {"dns_name": "a.example"} if kind == "dns" else {}
        values, errors = check_form.validate_service_check(
            {"check_type": kind, "target": target, "cert_min_days": 7, **extra})
        assert [e["field"] for e in errors] == ["cert_min_days"], kind
        assert values["cert_days_value"] is None
    values, errors = check_form.validate_service_check({"check_type": "tcp", "target": "h:22"})
    assert errors == [] and values["cert_days_value"] is None


def test_signature_includes_cert_min_days():
    a = HealthCheck(check_type="http", target="t", cert_min_days=None)
    b = HealthCheck(check_type="http", target="t", cert_min_days=7)
    assert check_form._signature(a) != check_form._signature(b)


# --- Add / Edit form --------------------------------------------------------------------


def test_edit_round_trip_for_a_service_check(app, admin_client):
    with app.app_context():
        eid = _make()
    row = _svc(target=EMMETT, cert_min_days="7", verify=None)
    assert admin_client.post(f"/edit/{eid}", data=_form(row)).status_code == 302
    with app.app_context():
        (c,) = _services(eid)
        assert c.cert_min_days == 7 and c.verify_tls is False
        cid = c.id
        c.last_checked_at, c.last_cert_expires_at = datetime(2026, 1, 1), datetime(2027, 1, 1)
        db.session.commit()
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'name="svc_id%d_cert_min_days"' % cid in page and 'value="7"' in page
    assert "Min cert days" in page and 'placeholder="off"' in page

    # Unchanged resubmit keeps cached state; changing the minimum makes it due.
    same = {**_svc("id%d" % cid, target=EMMETT, cert_min_days="7", verify=None), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(same))
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert c.last_checked_at == datetime(2026, 1, 1) and c.last_cert_expires_at == datetime(2027, 1, 1)
    changed = {**_svc("id%d" % cid, target=EMMETT, cert_min_days="14", verify=None), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(changed))
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert c.cert_min_days == 14 and c.last_checked_at is None

    # Blank turns it off and drops the cached date.
    off = {**_svc("id%d" % cid, target=EMMETT, cert_min_days="", verify=None), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(off))
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert c.cert_min_days is None and c.last_cert_expires_at is None


def test_edit_round_trip_for_a_url_check(app, admin_client):
    with app.app_context():
        eid = _make(internalurl=EMMETT)
    resp = admin_client.post(f"/edit/{eid}", data=_form(uc_internal_enabled="on", uc_internal_cert_min_days="7"))
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).url_check("internal").cert_min_days == 7
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'name="uc_internal_cert_min_days"' in page and 'name="uc_external_cert_min_days"' in page
    assert 'data-cert-source="internal_url"' in page and 'data-cert-source="external_url"' in page


def test_http_url_with_a_value_is_stored(app, admin_client):
    with app.app_context():
        eid = _make(internalurl="http://a.example/")
    admin_client.post(f"/edit/{eid}", data=_form(uc_internal_enabled="on", uc_internal_cert_min_days="7"))
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).url_check("internal").cert_min_days == 7


@pytest.mark.parametrize("bad", ["0", "366", "abc", "1.5", "-3"])
def test_form_rejects_out_of_range_and_rerenders_the_input(app, admin_client, bad):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data=_form(_svc(target=EMMETT, cert_min_days=bad)))
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200 and "min cert days must be a whole number of days from 1 to 365" in page
    assert f'value="{bad}"' in page
    with app.app_context():
        assert _services(eid) == []


def test_form_ignores_the_minimum_on_non_http_rows(app, admin_client):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data=_form(_svc(type="tcp", target="h:22", cert_min_days="7")))
    assert resp.status_code == 302
    with app.app_context():
        (c,) = _services(eid)
        assert c.check_type == "tcp" and c.cert_min_days is None
    # Switching an http check with a minimum to tcp clears it.
    with app.app_context():
        c = _services(eid)[0]
        c.check_type, c.target, c.cert_min_days = "http", EMMETT, 7
        db.session.commit()
        cid = c.id
    tcp = {**_svc("id%d" % cid, type="tcp", target="h:22", cert_min_days="7"), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(tcp))
    with app.app_context():
        assert db.session.get(HealthCheck, cid).cert_min_days is None


def test_form_hooks_show_the_field_only_for_https():
    js = open("static/js/health_checks_form.js").read()
    assert "data-cert-field" in js and "https:" in js and "addEventListener('input'" in js


def test_add_page_has_the_field_for_url_and_service_rows(admin_client):
    page = admin_client.get("/add").get_data(as_text=True)
    assert page.count("data-cert-field") >= 3  # two URL rows + the service-row template
    assert 'name="uc_internal_cert_min_days"' in page and 'svc___KEY___cert_min_days' in page
    assert 'id="internal_url"' in page and 'id="external_url"' in page


def test_to_config_round_trips_through_import(app, admin_client):
    import yaml

    from tests.import_helpers import import_flow
    with app.app_context():
        e, c = _entry_with_check(last_cert_expires_at=datetime(2027, 1, 1))
        cfg = c.to_config()
        assert cfg["cert_min_days"] == 7 and "last_cert_expires_at" not in cfg
    base = {"host": None, "source": "manual", "last_updated": "2026-01-01 00:00:00"}
    old = {k: v for k, v in cfg.items() if k != "cert_min_days"}
    records = [{**base, "container_name": "restored", "checks": [json.loads(json.dumps(cfg))]},
               {**base, "container_name": "restored-old", "checks": [old]},
               {**base, "container_name": "restored-bad", "checks": [{**cfg, "cert_min_days": 999}]}]
    import_flow(admin_client, yaml.dump(records).encode(), name="b.yaml")
    with app.app_context():
        (r,) = ServiceEntry.query.filter_by(container_name="restored").one().service_checks
        assert r.to_config() == cfg and r.last_cert_expires_at is None
        # An older backup without the key imports it as NULL.
        (r,) = ServiceEntry.query.filter_by(container_name="restored-old").one().service_checks
        assert r.cert_min_days is None
        # An out-of-range value makes that record invalid; it is never created.
        assert ServiceEntry.query.filter_by(container_name="restored-bad").count() == 0


# --- detail payload ----------------------------------------------------------------------


def test_detail_payload_includes_cert_fields(app, admin_client):
    with app.app_context():
        e, c = _entry_with_check(last_cert_expires_at=datetime(2027, 2, 1, 12, 0, 0))
        p = check_payload(e, c)
        assert (p["cert_min_days"], p["cert_expires_at"]) == (7, "2027-02-01T12:00:00Z")
        eid = e.id
        c.cert_min_days = c.last_cert_expires_at = None
        db.session.commit()
        p = check_payload(e, c)
        assert (p["cert_min_days"], p["cert_expires_at"]) == (None, None)
    got = admin_client.get(f"/service/{eid}/health").get_json()["checks"][0]
    assert "cert_expires_at" in got and "cert_min_days" in got
    js = open("static/js/health_detail.js").read()
    assert "'Cert expires '" in js and "health-cert-low" in js
    assert ".health-cert-low" in open("static/css/dashboard.css").read()


# --- management API -------------------------------------------------------------------------


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "cert-writer", "write")[1])


def _manual(app, **kw):
    with app.app_context():
        e = ServiceEntry(host=None, container_name="m", source="manual", last_updated=datetime.now(), **kw)
        db.session.add(e)
        db.session.commit()
        return e.id


def test_api_create_http_service_check_with_the_minimum(app, client, wkey):
    eid = _manual(app)
    resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                       json={"target": EMMETT, "verify_tls": False, "cert_min_days": 7})
    assert resp.status_code == 201
    out = resp.get_json()
    assert out["cert_min_days"] == 7 and out["cert_expires_at"] is None
    with app.app_context():
        db.session.get(HealthCheck, out["id"]).last_cert_expires_at = datetime(2027, 2, 1)
        db.session.commit()
    listed = client.get(f"/api/v1/entries/{eid}/checks", headers=wkey).get_json()["items"]
    assert listed[0]["cert_expires_at"] == "2027-02-01T00:00:00Z"


@pytest.mark.parametrize("kind,target,extra", [
    ("tcp", "h:22", {}), ("ping", "h", {}), ("dns", "10.0.0.1", {"dns_name": "a.example"})])
def test_api_rejects_the_minimum_on_other_check_types(app, client, wkey, kind, target, extra):
    eid = _manual(app)
    resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                       json={"target": target, "check_type": kind, "cert_min_days": 7, **extra})
    assert resp.status_code == 400
    assert resp.get_json()["details"][0]["loc"] == ["cert_min_days"]


def test_api_bounds_and_inline_entry_checks(app, client, wkey):
    eid = _manual(app)
    for bad in (0, 366, "7", 1.5, True):
        resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                           json={"target": EMMETT, "cert_min_days": bad})
        assert resp.status_code == 400, bad
    resp = client.post("/api/v1/entries", headers=wkey, json={
        "name": "Proxmox",
        "url_checks": {"internal": {"enabled": True, "cert_min_days": 7}},
        "checks": [{"target": EMMETT, "cert_min_days": 14}]})
    assert resp.status_code == 201
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="Proxmox").one()
        assert e.url_check("internal").cert_min_days == 7 and e.service_checks[0].cert_min_days == 14


def test_api_patch_on_service_and_url_checks_and_null_clears(app, client, wkey):
    eid = _manual(app, internalurl=EMMETT)
    cid = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                      json={"target": EMMETT}).get_json()["id"]
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        c.last_checked_at, c.last_cert_expires_at = datetime(2026, 1, 1), datetime(2027, 1, 1)
        ensure_url_checks(db.session.get(ServiceEntry, eid))
        db.session.commit()
        url_id = db.session.get(ServiceEntry, eid).url_check("internal").id

    resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"cert_min_days": 7})
    assert resp.status_code == 200 and resp.get_json()["cert_min_days"] == 7
    with app.app_context():
        assert db.session.get(HealthCheck, cid).last_checked_at is None  # due again
    resp = client.patch(f"/api/v1/checks/{url_id}", headers=wkey, json={"cert_min_days": 30})
    assert resp.status_code == 200 and resp.get_json()["cert_min_days"] == 30
    bad = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"cert_min_days": 400})
    assert bad.status_code == 400 and bad.get_json()["details"][0]["loc"] == ["cert_min_days"]

    resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"cert_min_days": None})
    assert resp.status_code == 200
    assert (resp.get_json()["cert_min_days"], resp.get_json()["cert_expires_at"]) == (None, None)

    # Switching a check with a minimum away from HTTP drops it without being told to.
    client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"cert_min_days": 5})
    resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"check_type": "tcp", "target": "h:22"})
    assert resp.status_code == 200 and resp.get_json()["cert_min_days"] is None
    # ...but asking for a minimum on tcp is a 400.
    bad = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"cert_min_days": 5})
    assert bad.status_code == 400 and bad.get_json()["details"][0]["loc"] == ["cert_min_days"]


def test_api_patch_rejected_on_the_container_check(app, client, wkey, register):
    register(container_name="n", host="h1")
    with app.app_context():
        e = ServiceEntry.query.one()
        ensure_url_checks(e)
        db.session.commit()
        cont_id = e.container_check.id
    resp = client.patch(f"/api/v1/checks/{cont_id}", headers=wkey, json={"cert_min_days": 7})
    assert resp.status_code == 400 and "cert_min_days" in resp.get_json()["error"]


def test_openapi_describes_the_cert_fields(client):
    schemas = client.get("/api/v1/openapi.json").get_json()["components"]["schemas"]
    for name in ("ServiceCheckCreate", "CheckPatch", "CheckOut", "UrlCheckSettings"):
        assert "cert_min_days" in schemas[name]["properties"], name
    assert "cert_expires_at" in schemas["CheckOut"]["properties"]


# --- MCP ---------------------------------------------------------------------------------------


def test_mcp_add_check_passes_cert_min_days():
    fake = Fake()
    call(std_mcp.build_server(fake.client(), "write"), "add_check", {
        "entry_id": 7, "target": EMMETT, "verify_tls": False, "cert_min_days": 7})
    req = fake.requests[0]
    assert (req.method, req.url.path) == ("POST", "/api/v1/entries/7/checks")
    assert json.loads(req.content) == {
        "target": EMMETT, "check_type": "http", "cert_min_days": 7, "verify_tls": False, "enabled": True}


def test_mcp_update_check_accepts_cert_min_days_including_null():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    call(server, "update_check", {"check_id": 3, "fields": {"cert_min_days": 7}})
    call(server, "update_check", {"check_id": 3, "fields": {"cert_min_days": None}})
    assert [json.loads(r.content) for r in fake.requests] == [{"cert_min_days": 7}, {"cert_min_days": None}]
    assert "cert_min_days" in std_mcp.CHECK_PATCH_FIELDS


def test_mcp_docstrings_explain_the_condition_with_the_emmett_example():
    server = std_mcp.build_server(Fake().client(), "write")
    tools = {t.name: t.description for t in asyncio.run(server.list_tools())}
    for name in ("add_check", "update_check"):
        assert "cert_min_days" in tools[name] and "em-pve01.crzynet.me:8006" in tools[name]
        assert "self-signed" in tools[name] and "verify_tls" in tools[name]


# --- migration ---------------------------------------------------------------------------------


DNS_REV = "a1c5e8d2f093"
CERT_REV = "b7d3f1a94e26"


def _health_cols(path):
    con = sqlite3.connect(path)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(health_check)")}
    finally:
        con.close()


def test_migration_adds_and_drops_the_cert_columns(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", DNS_REV)
    cols = {"cert_min_days", "last_cert_expires_at"}
    assert not cols & _health_cols(db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO service_entry (host, container_name, last_updated, is_static) "
                "VALUES ('h', 'keepme', '2026-01-01 00:00:00', 0)")
    con.execute("INSERT INTO health_check (service_entry_id, kind, name, check_type, target, mode, verify_tls, "
                "enabled, consecutive_failures) VALUES (1, 'service', 'web', 'http', 'https://h/', 'status', 1, 1, 0)")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "upgrade", CERT_REV)
    assert cols <= _health_cols(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT cert_min_days, last_cert_expires_at FROM health_check").fetchone() == (None, None)
    con.execute("UPDATE health_check SET cert_min_days=7, last_cert_expires_at='2027-02-01 00:00:00'")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "downgrade", "-1")
    assert not cols & _health_cols(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM health_check").fetchone()[0] == 1
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    assert cols <= _health_cols(db_path)


def test_cert_handshake_requires_tls_1_2():
    """The cert-reading handshake refuses TLS 1.0/1.1 (CodeQL py/insecure-protocol)."""
    import ssl
    ctx = MagicMock()
    with patch("checker.ssl.create_default_context", return_value=ctx), \
         patch("checker.socket.create_connection", side_effect=OSError("stop")):
        with pytest.raises(OSError):
            checker._read_cert_expiry("example.test", 443, 1)
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
