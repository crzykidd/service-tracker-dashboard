"""Inline uptime strips: /health/strips, aggregation, toggle markup (PRD 13.7)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from extensions import db
from health_history import MAX_STRIP_IDS, strips
from models import HealthCheck, HealthResult, ServiceEntry, ensure_url_checks

NOW = datetime(2026, 11, 15, 12, 10, 0)  # inside the 12:00-12:30 bucket
VIEWS = ("/", "/tiled_dash", "/compact_dash")


def _entry(name="svc", internalurl="http://svc.lan", externalurl=None):
    e = ServiceEntry(
        host="h", container_name=name, source="notifier", internalurl=internalurl,
        externalurl=externalurl, last_updated=datetime.now(), last_api_update=datetime.now())
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    e.url_check("internal").enabled = bool(internalurl)
    e.url_check("external").enabled = bool(externalurl)
    db.session.flush()
    return e


def _res(c, ts, ok=True, ts_end=None, samples=1, msg=None):
    db.session.add(HealthResult(check_id=c.id, ts=ts, ts_end=ts_end, samples=samples, ok=ok, message=msg))
    db.session.flush()


def test_merges_checks_failed_if_any_and_uptime(app):
    with app.app_context():
        e = _entry(externalurl="http://ext.example")
        i, x = e.url_check("internal"), e.url_check("external")
        _res(i, NOW - timedelta(minutes=5))
        _res(x, NOW - timedelta(minutes=4), ok=False, msg="ext down")
        _res(i, NOW - timedelta(hours=2, minutes=3))
        _res(x, NOW - timedelta(hours=2, minutes=3))
        db.session.refresh(e)
        s = strips([e], NOW)[e.id]
        assert len(s["bars"]) == 48
        last = s["bars"][-1]
        assert last["ok"] == 1 and last["fail"] == 1 and last["messages"] == ["ext down"]
        assert last["end"] == "2026-11-15T12:30:00Z"
        # 3 ok of 4 samples
        assert s["uptime"] == 75.0


def test_compacted_range_spans_buckets(app):
    with app.app_context():
        e = _entry()
        c = e.url_check("internal")
        _res(c, datetime(2026, 11, 15, 11, 10), ts_end=datetime(2026, 11, 15, 11, 50), samples=8)
        _res(c, NOW - timedelta(minutes=1), ok=False, msg="x", ts_end=None)
        db.session.refresh(e)
        s = strips([e], NOW)[e.id]
        spans = [b["ok"] for b in s["bars"] if b["ok"]]
        assert sum(spans) == 8 and len(spans) == 2
        assert s["uptime"] == round(100 * 8 / 9, 1)


def test_no_counting_checks_and_no_samples(app):
    with app.app_context():
        none = _entry("a", internalurl=None)
        quiet = _entry("b")
        db.session.refresh(none)
        s = strips([none, quiet], NOW)
        assert s[none.id] == {"bars": [], "uptime": None}
        assert len(s[quiet.id]["bars"]) == 48 and s[quiet.id]["uptime"] is None
        assert not any(b["ok"] or b["fail"] for b in s[quiet.id]["bars"])


def test_endpoint_auth_shape_omits_deleted_and_unknown(app, client, admin_client):
    with app.app_context():
        e = _entry("live")
        gone = _entry("gone")
        gone.deleted_at = datetime.utcnow()
        _res(e.url_check("internal"), datetime.utcnow() - timedelta(minutes=2))
        db.session.commit()
        eid, gid = e.id, gone.id
    assert client.get(f"/health/strips?ids={eid}").status_code in (302, 401)
    r = admin_client.get(f"/health/strips?ids={eid},{gid},99999,abc,")
    assert r.status_code == 200
    d = r.get_json()
    assert list(d) == [str(eid)]
    assert len(d[str(eid)]["bars"]) == 48 and d[str(eid)]["uptime"] == 100.0
    assert set(d[str(eid)]["bars"][0]) == {"start", "end", "ok", "fail", "messages"}
    assert admin_client.get("/health/strips").get_json() == {}


def test_id_cap(app, admin_client):
    with app.app_context():
        e = _entry()
        db.session.commit()
        eid = e.id
    # The real entry is id N; put it after the cap and it is not read.
    ids = [str(100000 + i) for i in range(MAX_STRIP_IDS)] + [str(eid)]
    assert admin_client.get("/health/strips?ids=" + ",".join(ids)).get_json() == {}
    ids = [str(eid)] + [str(100000 + i) for i in range(MAX_STRIP_IDS - 1)]
    assert list(admin_client.get("/health/strips?ids=" + ",".join(ids)).get_json()) == [str(eid)]


def _count_selects(app, client, ids):
    stmts = []

    def hook(conn, cursor, statement, *a):
        if statement.lstrip().upper().startswith("SELECT"):
            stmts.append(statement)

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", hook)
    try:
        r = client.get("/health/strips?ids=" + ",".join(map(str, ids)))
    finally:
        event.remove(engine, "before_cursor_execute", hook)
    assert r.status_code == 200 and len(r.get_json()) == len(ids)
    return len(stmts)


def test_query_count_flat(app, admin_client):
    def make(n):
        with app.app_context():
            out = []
            for i in range(n):
                e = _entry(f"s{n}-{i}", externalurl="http://x.example")
                for c in e.checks:
                    _res(c, datetime.utcnow() - timedelta(minutes=3))
                db.session.add(HealthCheck(
                    service_entry_id=e.id, kind="service", name="db", check_type="tcp",
                    target="db:1", enabled=True))
                out.append(e.id)
            db.session.commit()
            return out

    few = _count_selects(app, admin_client, make(3))
    many = _count_selects(app, admin_client, make(30))
    assert few == many
    assert many <= 6


@pytest.mark.parametrize("path", VIEWS)
def test_toggle_and_containers_render(app, admin_client, path):
    with app.app_context():
        e = _entry()
        eid = e.id
        db.session.commit()
    off = admin_client.get(path).get_data(as_text=True)
    assert 'id="showUptimeToggle"' in off
    assert "checked" not in off.split('id="showUptimeToggle"', 1)[1].split(">", 1)[0]
    assert "show-uptime" not in off.split("<body", 1)[1].split(">", 1)[0]
    assert f'data-uptime-id="{eid}"' in off
    admin_client.set_cookie("std_show_uptime", "1")
    on = admin_client.get(path).get_data(as_text=True)
    assert "checked" in on.split('id="showUptimeToggle"', 1)[1].split(">", 1)[0]
    assert "show-uptime" in on.split("<body", 1)[1].split(">", 1)[0]
    admin_client.set_cookie("std_show_uptime", "<script>")
    junk = admin_client.get(path).get_data(as_text=True)
    assert "<script>" not in junk.split("<body", 1)[1].split(">", 1)[0]
    assert "show-uptime" not in junk.split("<body", 1)[1].split(">", 1)[0]
