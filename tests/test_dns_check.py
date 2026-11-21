"""DNS service check (v0.9.0, PRD 15.1): probe, validation, form, API, MCP,
detail payload and migration. No real network: replies are real `dns.message`
objects fed through a patched `dns.query.udp_with_fallback`."""

import asyncio
import json
import re
import sqlite3
from datetime import datetime
from unittest.mock import patch

import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rrset
import pytest
from werkzeug.datastructures import MultiDict

import check_form
import checker
import jobs
from extensions import db
from health_history import check_payload, entry_payload
from health_state import entry_health
from models import CHECK_KIND_SERVICE, HealthCheck, ServiceEntry
from tests.test_check_config_ui import _form, _make, _services, _svc
from tests.test_mcp_server import Fake, call, std_mcp
from tests.test_mgmt_api_keys import _alembic, _bearer, _key

SERVER = "10.100.16.16"


def _reply(qname="em-pve01.crzynet.me", rdtype="A", answers=(), rcode="NOERROR", extra=()):
    """A response to a query for `qname`/`rdtype` with `answers` (text rdatas of
    that type) plus any `extra` (name, type, text) rrsets before them."""
    query = dns.message.make_query(qname, rdtype)
    resp = dns.message.make_response(query)
    resp.set_rcode(dns.rcode.from_text(rcode))
    for name, rtype, text in extra:
        resp.answer.append(dns.rrset.from_text(name, 300, "IN", rtype, text))
    if answers:
        resp.answer.append(dns.rrset.from_text(qname, 300, "IN", rdtype, *answers))
    return resp


def _probe(resp, **kw):
    args = {"server": SERVER, "name": "em-pve01.crzynet.me", "record_type": "A",
            "expected_rcode": None, "expected_answer": None, "timeout": 3, **kw}
    with patch("checker.dns.query.udp_with_fallback", return_value=(resp, False)) as q:
        out = checker.probe_dns(**args)
    return out, q


# --- probe ---------------------------------------------------------------------


def test_a_record_match_passes_and_queries_the_given_server():
    out, q = _probe(_reply(answers=["10.100.17.10"]), expected_answer="10.100.17.10")
    assert out.ok and out.message is None and out.status_code is None
    assert q.call_args.args[1] == SERVER and q.call_args.kwargs == {"timeout": 3, "port": 53}


def test_emmett_parity_case_through_run_probe():
    job = {"check_type": "dns", "target": "10.100.16.16", "timeout": 5, "dns_name": "em-pve01.crzynet.me",
           "dns_record_type": "A", "dns_expected_rcode": "NOERROR", "dns_expected_answer": "10.100.17.10"}
    with patch("checker.dns.query.udp_with_fallback",
               return_value=(_reply(answers=["10.100.17.10"]), False)) as q:
        out = checker.run_probe(job)
    assert out.ok is True
    assert q.call_args.args[1] == "10.100.16.16"
    assert str(q.call_args.args[0].question[0].name) == "em-pve01.crzynet.me."


def test_port_is_passed_through():
    _, q = _probe(_reply(), server="10.0.0.1:5353")
    assert q.call_args.kwargs["port"] == 5353


def test_wrong_answer_message_and_multiple_answers_joined():
    out, _ = _probe(_reply(answers=["10.0.0.5"]), expected_answer="10.100.17.10")
    assert (out.ok, out.message) == (False, "answer 10.0.0.5, expected 10.100.17.10")
    out, _ = _probe(_reply(answers=["10.0.0.5", "10.0.0.6"]), expected_answer="10.100.17.10")
    assert out.message == "answer 10.0.0.5 | 10.0.0.6, expected 10.100.17.10"
    out, _ = _probe(_reply(answers=["10.0.0.5", "10.100.17.10"]), expected_answer="10.100.17.10")
    assert out.ok  # any answer may match


def test_wrong_answer_message_is_clipped():
    out, _ = _probe(_reply(rdtype="TXT", answers=['"%s" "%s"' % ("x" * 200, "y" * 200)]), record_type="TXT",
                    name="em-pve01.crzynet.me", expected_answer="nope")
    assert not out.ok and len(out.message) == checker.MESSAGE_COLUMN_LIMIT and out.message.endswith("…")


def test_nxdomain_message_and_expected_nxdomain():
    out, _ = _probe(_reply(rcode="NXDOMAIN"))
    assert (out.ok, out.message) == (False, "rcode NXDOMAIN")
    out, _ = _probe(_reply(rcode="NXDOMAIN"), expected_rcode="nxdomain")
    assert out.ok
    out, _ = _probe(_reply(rcode="NOERROR"), expected_rcode="NXDOMAIN")
    assert (out.ok, out.message) == (False, "rcode NOERROR")


def test_nodata_passes_without_expected_answer_and_fails_with_one():
    assert _probe(_reply())[0].ok
    out, _ = _probe(_reply(), expected_answer="10.100.17.10")
    assert (out.ok, out.message) == (False, "no answer, expected 10.100.17.10")


def test_cname_chain_then_a_matches_the_a_record():
    resp = _reply(qname="www.example.com", answers=["10.1.1.1"],
                  extra=[("www.example.com", "CNAME", "web.example.com.")])
    # The A record sits at a different owner name than the question.
    resp.answer[-1] = dns.rrset.from_text("web.example.com.", 300, "IN", "A", "10.1.1.1")
    out, _ = _probe(resp, name="www.example.com", expected_answer="10.1.1.1")
    assert out.ok


def test_cname_query_matches_target_case_and_trailing_dot_insensitive():
    resp = _reply(qname="www.example.com", rdtype="CNAME", answers=["Web.Example.COM."])
    out, _ = _probe(resp, name="www.example.com", record_type="CNAME", expected_answer="web.example.com")
    assert out.ok


def test_txt_normalization_strips_quotes_and_joins_strings():
    resp = _reply(qname="example.com", rdtype="TXT", answers=['"v=spf1 " "include:x.example"'])
    for expected in ("v=spf1 include:x.example", '"v=spf1 include:x.example"', "V=SPF1 INCLUDE:X.EXAMPLE"):
        out, _ = _probe(resp, name="example.com", record_type="TXT", expected_answer=expected)
        assert out.ok, expected


def test_mx_and_srv_compare_full_text_form():
    mx = _reply(qname="example.com", rdtype="MX", answers=["10 Mail.Example.com."])
    assert _probe(mx, name="example.com", record_type="MX", expected_answer="10 mail.example.com")[0].ok
    assert not _probe(mx, name="example.com", record_type="MX", expected_answer="mail.example.com")[0].ok
    srv = _reply(qname="_sip._tcp.example.com", rdtype="SRV", answers=["0 5 5060 sip.example.com."])
    assert _probe(srv, name="_sip._tcp.example.com", record_type="SRV",
                  expected_answer="0 5 5060 sip.example.com.")[0].ok


def test_aaaa_compares_canonical_addresses():
    resp = _reply(qname="v6.example.com", rdtype="AAAA", answers=["2001:db8::1"])
    out, _ = _probe(resp, name="v6.example.com", record_type="AAAA", expected_answer="2001:0DB8:0:0::1")
    assert out.ok


def test_ptr_from_an_ip_queries_the_reverse_name():
    resp = _reply(qname="10.17.100.10.in-addr.arpa", rdtype="PTR", answers=["em-pve01.crzynet.me."])
    out, q = _probe(resp, name="10.100.17.10", record_type="PTR", expected_answer="em-pve01.crzynet.me")
    assert out.ok
    assert str(q.call_args.args[0].question[0].name) == "10.17.100.10.in-addr.arpa."
    # A name already in in-addr.arpa is used as is.
    _, q = _probe(resp, name="10.17.100.10.in-addr.arpa", record_type="PTR")
    assert str(q.call_args.args[0].question[0].name) == "10.17.100.10.in-addr.arpa."
    # IPv6
    _, q = _probe(resp, name="2001:db8::1", record_type="PTR")
    assert str(q.call_args.args[0].question[0].name).endswith(".ip6.arpa.")


def test_timeout_gives_exactly_timeout():
    with patch("checker.dns.query.udp_with_fallback", side_effect=dns.exception.Timeout()):
        out = checker.probe_dns(SERVER, "a.example", "A", None, None, 1)
    assert (out.ok, out.message, out.status_code) == (False, "timeout", None)


def test_unexpected_exception_never_raises():
    with patch("checker.dns.query.udp_with_fallback", side_effect=OSError("network unreachable")):
        out = checker.probe_dns(SERVER, "a.example", "A", None, None, 1)
    assert out.ok is False and "network unreachable" in out.message and out.error_type == "OSError"
    with patch("checker.dns.query.udp_with_fallback", side_effect=RuntimeError("boom")):
        job = {"check_type": "dns", "target": SERVER, "timeout": 1, "dns_name": "a.example"}
        assert checker.run_probe(job).ok is False
    # Garbage input is a failing result, not an exception.
    assert checker.probe_dns("not-an-ip", "a.example", "A", None, None, 1).ok is False
    assert checker.probe_dns(SERVER, "a.example", "BOGUS", None, None, 1).ok is False


def test_the_system_resolver_is_never_used():
    import dns.resolver

    def explode(*a, **kw):
        raise AssertionError("system resolver used")

    with patch.object(dns.resolver, "Resolver", explode), \
         patch.object(dns.resolver, "resolve", explode), \
         patch.object(dns.resolver, "get_default_resolver", explode), \
         patch("socket.getaddrinfo", explode):
        out, _ = _probe(_reply(answers=["10.100.17.10"]), expected_answer="10.100.17.10")
    assert out.ok
    assert "dns.resolver" not in open(checker.__file__).read().replace("`dns.resolver`", "")


# --- validation ------------------------------------------------------------------


@pytest.mark.parametrize("target,expected", [
    ("10.100.16.16", ("10.100.16.16", 53)),
    ("10.100.16.16:5353", ("10.100.16.16", 5353)),
    ("2001:db8::1", ("2001:db8::1", 53)),
    ("[2001:db8::1]", ("2001:db8::1", 53)),
    ("[2001:db8::1]:5353", ("2001:db8::1", 5353)),
])
def test_split_dns_server_accepts(target, expected):
    assert checker.split_dns_server(target) == expected
    assert check_form.validate_target("dns", target) is None


@pytest.mark.parametrize("target", [
    "dns.example.com", "dns.example.com:53", "10.0.0.1:0", "10.0.0.1:70000", "10.0.0.1:abc",
    "10.0.0.1:", "[2001:db8::1]:", "2001:db8::zz:53", "[2001:db8::1", "[2001:db8::1]x", "http://10.0.0.1",
])
def test_dns_server_rejected(target):
    assert check_form.validate_target("dns", target)


def test_hostname_server_message_is_clear():
    assert "not a hostname" in check_form.validate_target("dns", "dns.example.com")
    assert "1 to 65535" in check_form.validate_target("dns", "10.0.0.1:99999")


def _validate(**kw):
    return check_form.validate_service_check(
        {"check_type": "dns", "target": SERVER, "dns_name": "a.example", **kw})


def test_validate_defaults_and_normalization():
    values, errors = _validate(dns_expected_rcode="nxdomain", dns_record_type="aaaa",
                               dns_expected_answer="  1.2.3.4 ")
    assert errors == []
    assert (values["dns_record_type"], values["dns_expected_rcode"], values["dns_expected_answer"]) == (
        "AAAA", "NXDOMAIN", "1.2.3.4")
    assert (values["mode"], values["verify"]) == ("status", True)
    values, errors = _validate()
    assert errors == [] and values["dns_record_type"] == "A" and values["dns_expected_rcode"] == "NOERROR"
    assert values["dns_expected_answer"] is None


def test_validate_errors_are_per_field():
    values, errors = check_form.validate_service_check(
        {"check_type": "dns", "target": "host.example", "dns_name": "", "dns_record_type": "SOA",
         "dns_expected_rcode": "BOGUS"})
    assert {e["field"] for e in errors} == {"target", "dns_name", "dns_record_type", "dns_expected_rcode"}
    assert values["dns_record_type"] == "A" and values["dns_expected_rcode"] == "NOERROR"
    assert any(e["field"] == "dns_expected_rcode" for e in _validate(dns_expected_rcode="3")[1])


@pytest.mark.parametrize("name,rtype,ok", [
    ("em-pve01.crzynet.me", "A", True), ("em-pve01.crzynet.me.", "A", True), ("_sip._tcp.x.example", "SRV", True),
    ("a b.example", "A", False), ("bad..example", "A", False), ("-x.example", "A", False),
    ("http://x.example", "A", False), ("10.100.17.10", "PTR", True), ("10.100.17.10", "A", True),
    ("2001:db8::1", "PTR", True), ("2001:db8::1", "A", False), ("a" * 64 + ".example", "A", False),
])
def test_dns_name_validation(name, rtype, ok):
    # (an IPv4 literal is also a syntactically valid name, so it passes for A)
    _, errors = _validate(dns_name=name, dns_record_type=rtype)
    assert (not [e for e in errors if e["field"] == "dns_name"]) is ok


def test_dns_fields_are_none_for_other_types():
    values, errors = check_form.validate_service_check(
        {"check_type": "tcp", "target": "h:22", "dns_name": "ignored.example"})
    assert errors == [] and values["dns_name"] is None and values["dns_expected_rcode"] is None


def test_type_error_message_lists_dns():
    _, errors = check_form.validate_service_check({"check_type": "smtp", "target": "x"})
    assert errors[0]["message"] == "type must be HTTP/HTTPS, TCP, Ping or DNS"


def test_signature_includes_dns_fields():
    base = HealthCheck(check_type="dns", target=SERVER, dns_name="a.example", dns_record_type="A",
                       dns_expected_rcode="NOERROR", dns_expected_answer="1.1.1.1", enabled=True)
    sig = check_form._signature(base)
    for field, value in (("dns_name", "b.example"), ("dns_record_type", "TXT"),
                         ("dns_expected_rcode", "NXDOMAIN"), ("dns_expected_answer", None)):
        other = HealthCheck(check_type="dns", target=SERVER, dns_name="a.example", dns_record_type="A",
                            dns_expected_rcode="NOERROR", dns_expected_answer="1.1.1.1", enabled=True)
        setattr(other, field, value)
        assert check_form._signature(other) != sig, field


# --- Add / Edit form -----------------------------------------------------------------


def _dns_row(key="n1", **fields):
    row = {"type": "dns", "name": "Emmett DNS", "target": SERVER, "dns_name": "em-pve01.crzynet.me",
           "dns_type": "A", "dns_rcode": "NOERROR", "dns_answer": "10.100.17.10", **fields}
    return _svc(key, **row)


def test_edit_round_trip_saves_and_renders_dns_fields(app, admin_client):
    with app.app_context():
        eid = _make()
    assert admin_client.post(f"/edit/{eid}", data=_form(_dns_row(mode="body", verify=None))).status_code == 302
    with app.app_context():
        (c,) = _services(eid)
        assert (c.check_type, c.target, c.dns_name, c.dns_record_type, c.dns_expected_rcode,
                c.dns_expected_answer) == ("dns", SERVER, "em-pve01.crzynet.me", "A", "NOERROR", "10.100.17.10")
        assert (c.mode, c.verify_tls) == ("status", True)
        cid = c.id
        c.last_checked_at = datetime(2026, 1, 1)
        db.session.commit()
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert '<option value="dns" selected>' in page
    assert 'value="em-pve01.crzynet.me"' in page and 'value="10.100.17.10"' in page
    assert re.search(r'<option value="NOERROR" selected>', page)

    # Unchanged resubmit keeps cached state; changing the expected answer makes it due.
    same = {**_dns_row("id%d" % cid), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(same))
    with app.app_context():
        assert db.session.get(HealthCheck, cid).last_checked_at == datetime(2026, 1, 1)
    changed = {**_dns_row("id%d" % cid, dns_answer="10.100.17.11", dns_type="AAAA", dns_rcode="NXDOMAIN"),
               f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(changed))
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert c.last_checked_at is None
        assert (c.dns_record_type, c.dns_expected_rcode, c.dns_expected_answer) == ("AAAA", "NXDOMAIN", "10.100.17.11")

    # Switching away from dns clears the dns columns.
    tcp = {**_svc("id%d" % cid, type="tcp", target="h:22"), f"svc_id{cid}_id": str(cid)}
    admin_client.post(f"/edit/{eid}", data=_form(tcp))
    with app.app_context():
        c = db.session.get(HealthCheck, cid)
        assert (c.check_type, c.dns_name, c.dns_record_type, c.dns_expected_rcode, c.dns_expected_answer) == (
            "tcp", None, None, None, None)


def test_add_creates_dns_check_and_rerenders_errors_with_input(app, admin_client):
    bad = _form(_dns_row(target="dns.example.com", dns_name="", dns_type="SOA", dns_rcode="BOGUS",
                         dns_answer="keep me"), name="NAS", icon_image="nas.svg")
    resp = admin_client.post("/add", data=bad)
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'class="flash-alert' in page
    assert "not a hostname" in page and "query name is required" in page
    assert 'value="dns.example.com"' in page and 'value="keep me"' in page
    assert '<option value="dns" selected>' in page
    with app.app_context():
        assert ServiceEntry.query.count() == 0
    good = _form(_dns_row(), name="NAS", icon_image="nas.svg")
    assert admin_client.post("/add", data=good).status_code == 302
    with app.app_context():
        (c,) = HealthCheck.query.filter_by(kind=CHECK_KIND_SERVICE).all()
        assert c.check_type == "dns" and c.dns_name == "em-pve01.crzynet.me"


def test_form_parse_keeps_dns_input_and_defaults():
    form = MultiDict([("svc_row", "n1"), ("svc_n1_type", "dns"), ("svc_n1_target", SERVER),
                      ("svc_n1_dns_name", " a.example ")])
    _, rows, errors = check_form.parse_form(form)
    assert errors == []
    r = rows[0]
    assert (r["dns_name"], r["dns_type"], r["dns_rcode"], r["dns_answer"]) == ("a.example", "A", "NOERROR", "")


def test_add_page_has_dns_option_fields_and_show_hide_hooks(admin_client):
    page = admin_client.get("/add").get_data(as_text=True)
    assert '<option value="dns" ' in page or '<option value="dns">' in page
    for name in ("dns_name", "dns_type", "dns_rcode", "dns_answer"):
        assert f"svc___KEY___{name}" in page  # in the row template
    assert "data-target-label" in page and "data-dns-only" in page
    js = open("static/js/health_checks_form.js").read()
    assert "data-dns-only" in js and "DNS server" in js


# --- detail payload, rollup, jobs -----------------------------------------------------------


def _dns_entry(**check_kw):
    e = ServiceEntry(host=None, container_name="dns-svc", source="manual", last_updated=datetime.now())
    db.session.add(e)
    db.session.flush()
    kw = {"service_entry_id": e.id, "kind": "service", "name": "Emmett DNS", "check_type": "dns",
          "target": SERVER, "enabled": True, "dns_name": "em-pve01.crzynet.me", "dns_record_type": "A",
          "dns_expected_rcode": "NOERROR", "dns_expected_answer": "10.100.17.10", **check_kw}
    c = HealthCheck(**kw)
    db.session.add(c)
    db.session.commit()
    db.session.refresh(e)
    return e, c


def test_detail_payload_includes_dns_fields(app, admin_client):
    with app.app_context():
        e, c = _dns_entry()
        p = check_payload(e, c)
        assert (p["check_type"], p["target"], p["dns_name"], p["dns_record_type"], p["dns_expected_rcode"],
                p["dns_expected_answer"]) == ("dns", SERVER, "em-pve01.crzynet.me", "A", "NOERROR", "10.100.17.10")
        assert entry_payload(e)["checks"][0]["dns_name"] == "em-pve01.crzynet.me"
        eid = e.id
    got = admin_client.get(f"/service/{eid}/health").get_json()["checks"][0]
    assert got["dns_expected_answer"] == "10.100.17.10"
    js = open("static/js/health_detail.js").read()
    assert "dns: 'DNS'" in js and "' @ '" in js and "'expect '" in js


def test_failing_dns_check_makes_the_entry_down_and_degraded_with_other_checks(app):
    with app.app_context():
        e, c = _dns_entry()
        bad, _ = _probe(_reply(answers=["10.0.0.5"]), expected_answer="10.100.17.10")
        jobs.record_check_result(c, bad)
        db.session.commit()
        db.session.refresh(e)
        assert entry_health(e).state == "down"
        assert entry_health(e).failures[0][1] == "answer 10.0.0.5, expected 10.100.17.10"
        # With a healthy second check the entry is degraded, not down.
        db.session.add(HealthCheck(service_entry_id=e.id, kind="service", name="ssh", check_type="tcp",
                                   target="h:22", enabled=True, last_ok=True))
        db.session.commit()
        db.session.refresh(e)
        assert entry_health(e).state == "degraded"


def test_due_jobs_carry_the_dns_fields(app):
    with app.app_context():
        _, c = _dns_entry()
        due = [j for j in jobs.select_due_jobs(app) if j["check_id"] == c.id]
    assert len(due) == 1
    job = due[0]
    assert (job["check_type"], job["target"], job["dns_name"], job["dns_record_type"],
            job["dns_expected_rcode"], job["dns_expected_answer"]) == (
        "dns", SERVER, "em-pve01.crzynet.me", "A", "NOERROR", "10.100.17.10")
    with patch("checker.dns.query.udp_with_fallback", return_value=(_reply(answers=["10.100.17.10"]), False)):
        assert checker.run_probe(job).ok


# --- backup / restore -------------------------------------------------------------------------


def test_to_config_round_trips_through_import(app, admin_client):
    import yaml

    from tests.import_helpers import import_flow
    with app.app_context():
        e, c = _dns_entry()
        cfg = c.to_config()
        assert cfg["dns_name"] == "em-pve01.crzynet.me" and cfg["dns_expected_answer"] == "10.100.17.10"
    base = {"host": None, "source": "manual", "last_updated": "2026-01-01 00:00:00"}
    # An older backup without the dns keys imports them as NULL.
    old = {k: v for k, v in cfg.items() if not k.startswith("dns_")}
    old["check_type"], old["target"] = "tcp", "10.0.0.5:53"
    records = [{**base, "container_name": "restored", "checks": [json.loads(json.dumps(cfg))]},
               {**base, "container_name": "restored-old", "checks": [old]}]
    import_flow(admin_client, yaml.dump(records).encode(), name="b.yaml")
    with app.app_context():
        (r,) = ServiceEntry.query.filter_by(container_name="restored").one().service_checks
        assert r.to_config() == cfg
        (r,) = ServiceEntry.query.filter_by(container_name="restored-old").one().service_checks
        assert r.dns_name is None and r.dns_expected_rcode is None


# --- management API -------------------------------------------------------------------------------


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "dns-writer", "write")[1])


def _manual(app):
    with app.app_context():
        e = ServiceEntry(host=None, container_name="m", source="manual", last_updated=datetime.now())
        db.session.add(e)
        db.session.commit()
        return e.id


DNS_BODY = {"check_type": "dns", "target": SERVER, "dns_name": "em-pve01.crzynet.me",
            "dns_record_type": "A", "dns_expected_answer": "10.100.17.10", "name": "Emmett DNS"}


def test_api_create_dns_check_and_out_fields(app, client, wkey):
    eid = _manual(app)
    resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json=DNS_BODY)
    assert resp.status_code == 201
    out = resp.get_json()
    assert (out["check_type"], out["target"], out["dns_name"], out["dns_record_type"],
            out["dns_expected_rcode"], out["dns_expected_answer"]) == (
        "dns", SERVER, "em-pve01.crzynet.me", "A", "NOERROR", "10.100.17.10")
    other = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey,
                        json={"target": "h:22", "check_type": "tcp"}).get_json()
    assert other["dns_name"] is None and other["dns_expected_rcode"] is None
    listed = client.get(f"/api/v1/entries/{eid}/checks", headers=wkey).get_json()["items"]
    assert {c["check_type"] for c in listed} >= {"dns", "tcp"}


def test_api_create_validation_lists_every_bad_field(app, client, wkey):
    eid = _manual(app)
    resp = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json={
        "check_type": "dns", "target": "dns.example.com", "dns_record_type": "SOA",
        "dns_expected_rcode": "BOGUS", "interval_seconds": 5})
    assert resp.status_code == 400
    assert {d["loc"][-1] for d in resp.get_json()["details"]} == {
        "target", "dns_name", "dns_record_type", "dns_expected_rcode", "interval_seconds"}
    unknown = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json={**DNS_BODY, "dns_bogus": 1})
    assert unknown.status_code == 400  # extra=forbid


def test_api_create_entry_with_inline_dns_check(app, client, wkey):
    resp = client.post("/api/v1/entries", headers=wkey, json={"name": "Resolver", "checks": [DNS_BODY]})
    assert resp.status_code == 201
    with app.app_context():
        (c,) = HealthCheck.query.filter_by(kind="service").all()
        assert c.check_type == "dns" and c.dns_expected_answer == "10.100.17.10"
    bad = client.post("/api/v1/entries", headers=wkey,
                      json={"name": "Resolver2", "checks": [{**DNS_BODY, "dns_name": ""}]})
    assert bad.status_code == 400 and bad.get_json()["details"][0]["loc"] == ["checks", "0", "dns_name"]


def test_api_patch_dns_fields(app, client, wkey):
    eid = _manual(app)
    cid = client.post(f"/api/v1/entries/{eid}/checks", headers=wkey, json=DNS_BODY).get_json()["id"]
    with app.app_context():
        db.session.get(HealthCheck, cid).last_checked_at = datetime(2026, 1, 1)
        db.session.commit()
    resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey,
                        json={"dns_expected_answer": None, "dns_expected_rcode": "nxdomain", "dns_record_type": "TXT"})
    out = resp.get_json()
    assert resp.status_code == 200
    assert (out["dns_expected_answer"], out["dns_expected_rcode"], out["dns_record_type"]) == (None, "NXDOMAIN", "TXT")
    with app.app_context():
        assert db.session.get(HealthCheck, cid).last_checked_at is None  # due again
    bad = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"dns_expected_rcode": "BOGUS", "target": "host"})
    assert bad.status_code == 400
    assert {d["loc"][-1] for d in bad.get_json()["details"]} == {"dns_expected_rcode", "target"}
    # Switching a dns check to tcp drops the dns columns.
    resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"check_type": "tcp", "target": "h:53"})
    assert resp.status_code == 200 and resp.get_json()["dns_name"] is None
    # Switching a tcp check to dns requires the name.
    need = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={"check_type": "dns", "target": SERVER})
    assert need.status_code == 400 and need.get_json()["details"][0]["loc"] == ["dns_name"]


def test_api_patch_dns_fields_rejected_on_url_and_container_checks(app, client, wkey, register):
    register(container_name="n", host="h1")
    with app.app_context():
        from models import ensure_url_checks
        e = ServiceEntry.query.one()
        ensure_url_checks(e)
        db.session.commit()
        url_id, cont_id = e.url_check("internal").id, e.container_check.id
    for cid in (url_id, cont_id):
        for field in ("dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer"):
            resp = client.patch(f"/api/v1/checks/{cid}", headers=wkey, json={field: "x"})
            assert resp.status_code == 400 and field in resp.get_json()["error"], (cid, field)


def test_openapi_describes_the_dns_fields(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    schemas = spec["components"]["schemas"]
    for name in ("ServiceCheckCreate", "CheckPatch", "CheckOut"):
        assert {"dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer"} <= set(
            schemas[name]["properties"]), name


# --- MCP --------------------------------------------------------------------------------------------


def test_mcp_add_check_passes_dns_arguments():
    fake = Fake()
    call(std_mcp.build_server(fake.client(), "write"), "add_check", {
        "entry_id": 7, "target": SERVER, "check_type": "dns", "dns_name": "em-pve01.crzynet.me",
        "dns_record_type": "A", "dns_expected_answer": "10.100.17.10"})
    req = fake.requests[0]
    assert (req.method, req.url.path) == ("POST", "/api/v1/entries/7/checks")
    assert json.loads(req.content) == {
        "target": SERVER, "check_type": "dns", "dns_name": "em-pve01.crzynet.me", "dns_record_type": "A",
        "dns_expected_answer": "10.100.17.10", "verify_tls": True, "enabled": True}


def test_mcp_update_check_accepts_dns_fields_and_rejects_typos():
    fake = Fake()
    server = std_mcp.build_server(fake.client(), "write")
    call(server, "update_check", {"check_id": 3, "fields": {"dns_expected_answer": None, "dns_expected_rcode": "NXDOMAIN"}})
    assert json.loads(fake.requests[0].content) == {"dns_expected_answer": None, "dns_expected_rcode": "NXDOMAIN"}
    assert {"dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer"} <= std_mcp.CHECK_PATCH_FIELDS
    with pytest.raises(Exception, match="Unknown check field"):
        call(server, "update_check", {"check_id": 3, "fields": {"dns_nam": "x"}})


def test_mcp_docstrings_explain_dns_with_the_emmett_example():
    server = std_mcp.build_server(Fake().client(), "write")
    tools = {t.name: t.description for t in asyncio.run(server.list_tools())}
    for name in ("add_check", "update_check"):
        assert "dns" in tools[name] and "em-pve01.crzynet.me" in tools[name] and "10.100.16.16" in tools[name]


# --- migration ---------------------------------------------------------------------------------------------


DNS_REV = "a1c5e8d2f093"
PREV_REV = "d4a9e2c6b715"


def _health_cols(path):
    con = sqlite3.connect(path)
    try:
        return {r[1] for r in con.execute("PRAGMA table_info(health_check)")}
    finally:
        con.close()


def test_migration_adds_and_drops_dns_columns(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREV_REV)
    dns_cols = {"dns_name", "dns_record_type", "dns_expected_rcode", "dns_expected_answer"}
    assert not dns_cols & _health_cols(db_path)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO service_entry (host, container_name, last_updated, is_static) "
                "VALUES ('h', 'keepme', '2026-01-01 00:00:00', 0)")
    con.execute("INSERT INTO health_check (service_entry_id, kind, name, check_type, target, mode, verify_tls, "
                "enabled, consecutive_failures) VALUES (1, 'service', 'ssh', 'tcp', 'h:22', 'status', 1, 1, 0)")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "upgrade", DNS_REV)
    assert dns_cols <= _health_cols(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT dns_name, dns_expected_answer FROM health_check").fetchone() == (None, None)
    con.execute("UPDATE health_check SET check_type='dns', dns_name='a.example'")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "downgrade", "-1")
    assert not dns_cols & _health_cols(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM health_check").fetchone()[0] == 1
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    assert dns_cols <= _health_cols(db_path)
