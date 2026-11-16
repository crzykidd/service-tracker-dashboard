"""Health-check configuration UI on Add and Edit (PRD 13.5)."""

import re
from datetime import datetime

import pytest

from extensions import db
from models import CHECK_KIND_SERVICE, HealthCheck, HealthResult, ServiceEntry


def _make(name="site", source="manual", **kw):
    e = ServiceEntry(host=kw.pop("host", None), container_name=name, source=source,
                     last_updated=datetime.now(), **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


def _base(name="site"):
    return {"host": "", "container_name": name, "widget_name": "none", "checks_form": "1"}


def _svc(key="n1", **fields):
    """Form fields for one service-check row."""
    data = {"svc_row": key}
    row = {"type": "http", "target": "https://example.com/health", "name": "Web", "enabled": "on", **fields}
    for field, value in row.items():
        if value is not None:
            data[f"svc_{key}_{field}"] = value
    return data


def _form(*rows, **extra):
    """Build a multi-value form dict (svc_row repeats)."""
    from werkzeug.datastructures import MultiDict

    m = MultiDict(_base(extra.pop("name", "site")))
    m.update(extra)
    for row in rows:
        for k, v in row.items():
            m.add(k, v)
    return m


def _services(eid):
    return HealthCheck.query.filter_by(service_entry_id=eid, kind=CHECK_KIND_SERVICE).order_by(HealthCheck.id).all()


# --- rendering ---------------------------------------------------------------


def test_add_and_edit_pages_render_the_section(app, admin_client):
    page = admin_client.get("/add").get_data(as_text=True)
    assert "Health checks" in page and 'id="service-check-template"' in page
    assert "health_checks_form.js" in page and 'name="uc_internal_enabled"' in page
    with app.app_context():
        eid = _make(internalurl="http://a.example/")
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert "Health checks" in page and "http://a.example/" in page
    assert 'name="internal_health_check_enabled"' not in page  # old toggles are gone
    assert "Advanced health check" not in page


def test_edit_renders_saved_service_checks(app, admin_client):
    with app.app_context():
        eid = _make()
        e = db.session.get(ServiceEntry, eid)
        e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="SSH", check_type="tcp",
                                    target="host:22", interval_seconds=60, enabled=True))
        db.session.commit()
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'value="SSH"' in page and 'value="host:22"' in page and 'value="60"' in page
    assert re.search(r'<option value="tcp" selected>', page)


# --- create / update / delete via Edit ------------------------------------------


def test_edit_creates_updates_and_deletes_service_checks(app, admin_client):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        _svc("n1", name="Web", target="https://example.com/health", interval="60", timeout="3"),
        _svc("n2", name="SSH", type="tcp", target="host:22"),
        _svc("n3", name="Gateway", type="ping", target="192.168.1.1", mode="body", verify=None),
    ))
    assert resp.status_code == 302
    with app.app_context():
        web, ssh, gw = _services(eid)
        assert (web.name, web.check_type, web.target, web.interval_seconds, web.timeout_seconds) == (
            "Web", "http", "https://example.com/health", 60, 3)
        assert web.enabled and web.last_checked_at is None
        assert (ssh.check_type, ssh.target, ssh.mode, ssh.verify_tls) == ("tcp", "host:22", "status", True)
        assert gw.check_type == "ping" and gw.mode == "status"  # mode is HTTP-only
        ids = (web.id, ssh.id, gw.id)

    # Update Web (keep id), drop SSH, keep Gateway untouched, add a new row.
    # Give the unchanged check a timestamp: only changed checks are made due.
    with app.app_context():
        HealthCheck.query.filter_by(id=ids[2]).one().last_checked_at = datetime(2026, 1, 1)
        db.session.commit()
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        {**_svc("id%d" % ids[0], name="Web 2", target="http://example.com/", mode="body", verify=None),
         f"svc_id{ids[0]}_id": str(ids[0])},
        {**_svc("id%d" % ids[2], name="Gateway", type="ping", target="192.168.1.1"),
         f"svc_id{ids[2]}_id": str(ids[2])},
        _svc("n9", name="DB", type="tcp", target="db:5432"),
    ))
    assert resp.status_code == 302
    with app.app_context():
        rows = _services(eid)
        assert [r.name for r in rows if r.id in ids] == ["Web 2", "Gateway"]
        assert db.session.get(HealthCheck, ids[1]) is None
        web = db.session.get(HealthCheck, ids[0])
        assert (web.mode, web.verify_tls, web.target) == ("body", False, "http://example.com/")
        assert db.session.get(HealthCheck, ids[2]).last_checked_at == datetime(2026, 1, 1)
        assert rows[-1].name == "DB" and rows[-1].last_checked_at is None

    # Remove everything: no svc_row fields at all.
    admin_client.post(f"/edit/{eid}", data=_form())
    with app.app_context():
        assert _services(eid) == []


def test_removed_check_results_cascade(app, admin_client):
    with app.app_context():
        eid = _make()
        e = db.session.get(ServiceEntry, eid)
        check = HealthCheck(kind=CHECK_KIND_SERVICE, name="x", check_type="tcp", target="h:1", enabled=True)
        e.checks.append(check)
        db.session.commit()
        db.session.add(HealthResult(check_id=check.id, ts=datetime.now(), ok=True, latency_ms=1))
        db.session.commit()
    admin_client.post(f"/edit/{eid}", data=_form())
    with app.app_context():
        assert HealthResult.query.count() == 0


def test_url_check_fields_saved_per_row(app, admin_client):
    with app.app_context():
        eid = _make(internalurl="http://a/")
    admin_client.post(f"/edit/{eid}", data={
        **_base(),
        "internalurl": "http://a/", "uc_internal_enabled": "on", "uc_internal_mode": "body",
        "uc_internal_interval": "120", "uc_internal_timeout": "7", "uc_internal_verify": "on",
        "uc_external_timeout": "11",
    })
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        i, x = e.url_check("internal"), e.url_check("external")
        assert (i.enabled, i.mode, i.interval_seconds, i.timeout_seconds, i.verify_tls) == (True, "body", 120, 7, True)
        assert (x.enabled, x.timeout_seconds, x.verify_tls) == (False, 11, False)


def test_changing_the_url_makes_its_check_due(app, admin_client):
    with app.app_context():
        eid = _make(internalurl="http://a/")
        e = db.session.get(ServiceEntry, eid)
        from models import ensure_url_checks
        ensure_url_checks(e)
        e.url_check("internal").last_checked_at = datetime(2026, 1, 1)
        db.session.commit()
    admin_client.post(f"/edit/{eid}", data={**_base(), "internalurl": "http://b/"})
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).url_check("internal").last_checked_at is None


def test_edit_without_checks_marker_leaves_checks_alone(app, admin_client):
    with app.app_context():
        eid = _make()
        e = db.session.get(ServiceEntry, eid)
        e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="keep", check_type="tcp", target="h:1", enabled=True))
        db.session.commit()
    data = _base()
    del data["checks_form"]
    admin_client.post(f"/edit/{eid}", data=data)
    with app.app_context():
        assert [c.name for c in _services(eid)] == ["keep"]


# --- validation ----------------------------------------------------------------


BAD = [
    ("bad http url", dict(type="http", target="ftp://example.com"), "full http:// or https:// URL"),
    ("http no host", dict(type="http", target="http://"), "full http:// or https:// URL"),
    ("bare host as http", dict(type="http", target="example.com"), "full http:// or https:// URL"),
    ("tcp no port", dict(type="tcp", target="example.com"), "host:port"),
    ("tcp port 0", dict(type="tcp", target="example.com:0"), "port from 1 to 65535"),
    ("tcp port high", dict(type="tcp", target="example.com:70000"), "port from 1 to 65535"),
    ("tcp port text", dict(type="tcp", target="example.com:ssh"), "host:port"),
    ("empty ping", dict(type="ping", target=""), "target is required"),
    ("ping with port", dict(type="ping", target="host:22"), "hostname or IP"),
    ("ping with url", dict(type="ping", target="http://host/"), "hostname or IP"),
    ("interval low", dict(interval="29"), "interval must be a whole number of seconds from 30 to 86400"),
    ("interval high", dict(interval="86401"), "from 30 to 86400"),
    ("interval text", dict(interval="soon"), "from 30 to 86400"),
    ("timeout zero", dict(timeout="0"), "timeout must be a whole number of seconds from 1 to 60"),
    ("timeout high", dict(timeout="61"), "from 1 to 60"),
    ("bad type", dict(type="udp"), "type must be"),
    ("bad mode", dict(mode="xml"), "mode must be"),
]


@pytest.mark.parametrize("label,fields,message", BAD, ids=[b[0] for b in BAD])
def test_service_check_validation_rerenders_with_input_and_flash(app, admin_client, label, fields, message):
    with app.app_context():
        eid = _make(name="orig")
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        _svc("n1", name="Typed name", **fields), name="Edited name",
        uc_internal_timeout="12",
    ))
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'class="flash-alert' in page and message in page
    # Operator's input is kept, including the unrelated field and a URL-check field.
    assert 'value="Edited name"' in page and 'value="Typed name"' in page
    assert 'value="12"' in page
    # Nothing was saved.
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).container_name == "orig"
        assert _services(eid) == []


def test_validation_keeps_other_checks_edits_and_lists_every_error(app, admin_client):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        _svc("n1", name="Good", type="tcp", target="h:22", interval="90"),
        _svc("n2", name="Bad one", type="tcp", target="h"),
        _svc("n3", name="Bad two", interval="5"),
    ))
    page = resp.get_data(as_text=True)
    assert page.count('class="flash-alert') == 2
    assert 'value="Good"' in page and 'value="h:22"' in page and 'value="90"' in page
    assert "Service check 2 (Bad one)" in page and "Service check 3 (Bad two)" in page
    assert 'value="n1"' in page and 'value="n3"' in page  # rows keep their keys


def test_unknown_check_id_is_rejected(app, admin_client):
    with app.app_context():
        eid = _make()
        other = _make(name="other")
        e = db.session.get(ServiceEntry, other)
        c = HealthCheck(kind=CHECK_KIND_SERVICE, name="theirs", check_type="tcp", target="h:1", enabled=True)
        e.checks.append(c)
        db.session.commit()
        foreign = c.id
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        {**_svc("id%d" % foreign, type="tcp", target="h:2"), f"svc_id{foreign}_id": str(foreign)}))
    assert resp.status_code == 200 and "no longer exists" in resp.get_data(as_text=True)
    with app.app_context():
        assert db.session.get(HealthCheck, foreign).target == "h:1"


def test_url_check_bounds_are_validated(app, admin_client):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data={**_base(), "uc_external_interval": "5",
                                                   "uc_internal_timeout": "99"})
    page = resp.get_data(as_text=True)
    assert "External URL: interval must be" in page and "Internal URL: timeout must be" in page


def test_ipv6_tcp_and_ping_targets_accepted(app, admin_client):
    with app.app_context():
        eid = _make()
    resp = admin_client.post(f"/edit/{eid}", data=_form(
        _svc("n1", name="v6 tcp", type="tcp", target="[2001:db8::1]:443"),
        _svc("n2", name="v6 ping", type="ping", target="2001:db8::1"),
        _svc("n3", name="", type="ping", target="router.lan"),
    ))
    assert resp.status_code == 302
    with app.app_context():
        assert [c.name for c in _services(eid)] == ["v6 tcp", "v6 ping", "router.lan"]


# --- Add page --------------------------------------------------------------------


def test_add_with_a_service_check(app, admin_client):
    resp = admin_client.post("/add", data=_form(
        _svc("n1", name="Ping", type="ping", target="nas.lan"), name="NAS",
        icon_image="nas.svg", uc_internal_enabled="on",
    ))
    assert resp.status_code == 302
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="NAS").one()
        assert [(c.name, c.check_type, c.target) for c in e.service_checks] == [("Ping", "ping", "nas.lan")]
        assert e.url_check("internal").enabled and not e.url_check("external").enabled


def test_add_validation_rerenders_with_input_and_flash(app, admin_client):
    resp = admin_client.post("/add", data=_form(
        _svc("n1", name="Bad", type="tcp", target="nas.lan"), name="NAS", icon_image="nas.svg",
        internal_url="http://nas.lan/", uc_internal_enabled="on",
    ))
    page = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'class="flash-alert' in page and "host:port" in page
    assert 'value="NAS"' in page and 'value="nas.lan"' in page and 'value="http://nas.lan/"' in page
    assert re.search(r'name="uc_internal_enabled"[^>]*checked', page)
    with app.app_context():
        assert ServiceEntry.query.count() == 0


def test_new_rows_after_rerender_keep_unique_keys_in_js():
    js = open("static/js/health_checks_form.js").read()
    assert "Math.max(counter" in js  # new keys continue after re-rendered n<N> rows


# --- register never touches service rows ---------------------------------------


def test_register_leaves_service_checks_alone(app, register):
    register(container_name="svc1", internalurl="http://a/", internal_health_check_enabled=True)
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="svc1").one()
        e.checks.append(HealthCheck(kind=CHECK_KIND_SERVICE, name="Port", check_type="tcp",
                                    target="h:22", interval_seconds=45, enabled=True,
                                    last_ok=True, last_checked_at=datetime(2026, 1, 1)))
        db.session.commit()
        eid, before = e.id, _services(e.id)[0].to_config()
    for payload in (
        {"internalurl": "http://b/", "internal_health_check_enabled": False,
         "external_health_check_enabled": True, "exposure_observations": []},
        {},
    ):
        assert register(container_name="svc1", **payload).status_code in (200, 201)
    with app.app_context():
        rows = _services(eid)
        assert len(rows) == 1 and rows[0].to_config() == before
        assert rows[0].last_checked_at == datetime(2026, 1, 1) and rows[0].last_ok is True


# --- CSRF ----------------------------------------------------------------------


def test_edit_and_add_require_csrf(app, admin_client):
    with app.app_context():
        eid = _make()
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = admin_client.post(f"/edit/{eid}", data=_form(_svc("n1")))
        assert resp.status_code in (302, 400)
        resp2 = admin_client.post("/add", data=_form(_svc("n1"), name="NoToken", icon_image="a.svg"))
        assert resp2.status_code in (302, 400)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        assert _services(eid) == []
        assert ServiceEntry.query.filter_by(container_name="NoToken").count() == 0
    page = admin_client.get("/add").get_data(as_text=True)
    assert 'name="csrf_token"' in page
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'name="csrf_token"' in page


# --- flashes ---------------------------------------------------------------------


def test_stale_success_flashes_dropped_but_warnings_kept(app, admin_client):
    with app.app_context():
        eid = _make()
    with admin_client.session_transaction() as sess:
        sess["_flashes"] = [("success", "Old success"), ("warning", "Keep this warning")]
    page = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert "Old success" not in page and "Keep this warning" in page
