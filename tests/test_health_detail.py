"""Health detail panel: history service, endpoint, partial (v0.7.0, PRD 13.7)."""

from datetime import datetime, timedelta

from extensions import db
from health_history import bars, recent_failures, uptime
from models import HealthResult, ServiceEntry, ensure_url_checks

NOW = datetime(2026, 11, 15, 12, 10, 0)  # inside the 12:00-12:30 bucket


def _entry(name="svc", source="notifier"):
    e = ServiceEntry(
        host="h" if source == "notifier" else None, container_name=name, source=source,
        internalurl="http://svc.lan", last_updated=datetime.now(), last_api_update=datetime.now())
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    c = e.url_check("internal")
    c.enabled = True
    db.session.flush()
    return e, c


def _res(c, ts, ok=True, ts_end=None, samples=1, msg=None):
    db.session.add(HealthResult(check_id=c.id, ts=ts, ts_end=ts_end, samples=samples, ok=ok, message=msg))
    db.session.flush()


def test_bars_shape_and_raw(app):
    with app.app_context():
        _, c = _entry()
        _res(c, NOW - timedelta(minutes=5))
        _res(c, NOW - timedelta(minutes=2), ok=False, msg="boom")
        _res(c, NOW - timedelta(hours=3, minutes=1))
        b = bars(c, "24h", NOW)
        assert len(b) == 48
        assert b[-1]["end"] == datetime(2026, 11, 15, 12, 30)
        assert b[-1]["ok_samples"] == 1 and b[-1]["fail_samples"] == 1
        assert b[-1]["messages"] == ["boom"]
        assert sum(x["ok_samples"] + x["fail_samples"] for x in b) == 3
        empty = [x for x in b if not (x["ok_samples"] or x["fail_samples"])]
        assert len(empty) == 46


def test_bars_messages_capped_and_distinct(app):
    with app.app_context():
        _, c = _entry()
        for i, m in enumerate(["a", "a", "b", "c", "d"]):
            _res(c, NOW - timedelta(minutes=9 - i), ok=False, msg=m)
        assert bars(c, "24h", NOW)[-1]["messages"] == ["a", "b", "c"]


def test_bars_7d_hourly(app):
    with app.app_context():
        _, c = _entry()
        _res(c, NOW - timedelta(days=6, hours=2))
        _res(c, NOW - timedelta(days=8))  # outside the window
        b = bars(c, "7d", NOW)
        assert len(b) == 168
        assert b[-1]["end"] == datetime(2026, 11, 15, 13, 0)
        assert sum(x["ok_samples"] for x in b) == 1


def test_range_split_across_buckets_preserves_total(app):
    with app.app_context():
        _, c = _entry()
        # 11:00-12:00 with 12 samples over two half-hour buckets, unevenly:
        # 11:10-11:50 -> 20 min in the 11:00 bucket, 20 in the 11:30 bucket.
        _res(c, datetime(2026, 11, 15, 11, 10), ts_end=datetime(2026, 11, 15, 11, 50), samples=7)
        b = bars(c, "24h", NOW)
        got = [x["ok_samples"] for x in b if x["ok_samples"]]
        assert sum(got) == 7 and sorted(got) == [3, 4]


def test_range_proportional_and_clipped_to_window(app):
    with app.app_context():
        _, c = _entry()
        # 3 h range, 18 samples, starting before the window (starts 12:30 the day before): only the part inside counts.
        _res(c, datetime(2026, 11, 14, 11, 0), ts_end=datetime(2026, 11, 14, 14, 0), samples=18)
        b = bars(c, "24h", NOW)
        total = sum(x["ok_samples"] for x in b)
        assert total == 9  # 12:30-14:00 is half of the range


def test_range_of_one_and_failed_range(app):
    with app.app_context():
        _, c = _entry()
        t = NOW - timedelta(minutes=40)
        _res(c, t, ts_end=t, samples=1)
        _res(c, t, ts_end=t + timedelta(minutes=1), samples=2, ok=False, msg="x")
        b = bars(c, "24h", NOW)
        assert sum(x["ok_samples"] for x in b) == 1
        assert sum(x["fail_samples"] for x in b) == 2


def test_uptime(app):
    with app.app_context():
        _, c = _entry()
        assert uptime(c, 24, NOW) is None
        for i in range(3):
            _res(c, NOW - timedelta(minutes=10 + i))
        _res(c, NOW - timedelta(minutes=1), ok=False, msg="e")
        assert uptime(c, 24, NOW) == 75.0
        # an old success only counts for the 7 day figure
        _res(c, NOW - timedelta(days=3), ts_end=NOW - timedelta(days=3, hours=-1), samples=12)
        assert uptime(c, 24, NOW) == 75.0
        assert uptime(c, 168, NOW) == round(100 * 15 / 16, 1)


def test_recent_failures_order_and_limit(app):
    with app.app_context():
        _, c = _entry()
        for i in range(25):
            _res(c, NOW - timedelta(minutes=i), ok=False, msg=f"m{i}")
        _res(c, NOW, ok=True)
        f = recent_failures(c)
        assert len(f) == 20 and f[0]["message"] == "m0" and f[-1]["message"] == "m19"
        assert len(recent_failures(c, limit=5)) == 5


def test_endpoint_auth_shape_and_404(app, client, admin_client):
    with app.app_context():
        e, c = _entry()
        eid = e.id
        c.last_ok = False
        c.last_message = "boom"
        _res(c, datetime.utcnow() - timedelta(minutes=3), ok=False, msg="boom")
        _res(c, datetime.utcnow() - timedelta(minutes=8))
        # a second, disabled check must not appear
        e.url_check("external").enabled = False
        db.session.commit()
    assert client.get(f"/service/{eid}/health").status_code in (302, 401)
    r = admin_client.get(f"/service/{eid}/health")
    assert r.status_code == 200
    d = r.get_json()
    assert d["range"] == "24h" and len(d["checks"]) == 1
    ch = d["checks"][0]
    assert ch["state"] == "down" and ch["message"] == "boom"
    assert ch["target"] == "http://svc.lan" and ch["check_type"] == "http"
    assert len(ch["bars"]) == 48
    assert ch["uptime_24h"] == 50.0
    assert ch["failures"][0]["message"] == "boom"
    assert set(ch["bars"][0]) == {"start", "end", "ok", "fail", "messages"}
    d7 = admin_client.get(f"/service/{eid}/health?range=7d").get_json()
    assert len(d7["checks"][0]["bars"]) == 168
    assert admin_client.get(f"/service/{eid}/health?range=bogus").get_json()["range"] == "24h"
    assert admin_client.get("/service/99999/health").status_code == 404


def test_endpoint_404_for_soft_deleted(app, admin_client):
    with app.app_context():
        e, _ = _entry()
        e.deleted_at = datetime.now()
        db.session.commit()
        eid = e.id
    assert admin_client.get(f"/service/{eid}/health").status_code == 404


def test_panel_renders_on_each_surface(app, admin_client):
    with app.app_context():
        e, _ = _entry()
        db.session.commit()
        eid = e.id
    marker = f'data-url="/service/{eid}/health"'
    assert marker in admin_client.get("/tiled_dash").get_data(as_text=True)
    dash = admin_client.get("/").get_data(as_text=True)
    assert marker in dash and f'id="health-row-{eid}"' in dash and f'data-health-expand="{eid}"' in dash
    edit = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert marker in edit and 'id="health-history"' in edit and "data-autoload" in edit
    assert "data-health-detail" not in admin_client.get("/compact_dash").get_data(as_text=True)


# --- failure text: probe -> stored rows -> panel JSON and management API ----------------

_EMMETT = (b'{"status":"Error","last_error":"Mgmt1: Scope \'Mgmt1\' not found on destination ...",'
           b'"failing_scopes":["Mgmt","Mgmt1"]}')
_EMMETT_MSG = "503: Mgmt1: Scope 'Mgmt1' not found on destination ..."


def _mock_503(body=_EMMETT):
    from unittest.mock import MagicMock, patch

    r = MagicMock()
    r.status_code = 503
    r.iter_content.side_effect = lambda chunk_size=1024: iter(
        [body[i:i + chunk_size] for i in range(0, len(body), chunk_size)])
    return patch("checker.requests.get", return_value=r)


def test_panel_bars_and_failures_carry_the_stored_message(app, admin_client):
    with app.app_context():
        e, c = _entry()
        eid = e.id
        c.last_ok, c.last_status_code, c.last_message = False, 503, "503: something"
        _res(c, datetime.utcnow() - timedelta(minutes=2), ok=False, msg="503: something")
        db.session.commit()
    ch = admin_client.get(f"/service/{eid}/health").get_json()["checks"][0]
    assert ch["status_code"] == 503 and ch["message"] == "503: something"
    assert ch["failures"][0]["message"] == "503: something"
    assert any("503: something" in b["messages"] for b in ch["bars"])


def test_probe_503_text_reaches_check_rows_panel_and_api(app, admin_client):
    import jobs
    from tests.test_health_schema import _SyncExecutor

    with app.app_context():
        e, c = _entry()
        e.source = "manual"
        e.host = "h"
        c.interval_seconds = 30
        eid, cid = e.id, c.id
        db.session.commit()
        sched = jobs.HealthScheduler(app, executor=_SyncExecutor())
        with _mock_503():
            sched.tick(datetime.utcnow() + timedelta(hours=1))
            sched.tick(datetime.utcnow() + timedelta(hours=1))
            # "Check now": due regardless of interval, same write path
            jobs.request_run([cid])
            sched.tick()
            sched.tick()
        db.session.expire_all()
        from models import HealthCheck

        chk = db.session.get(HealthCheck, cid)
        assert chk.last_message == _EMMETT_MSG and chk.last_status_code == 503
        rows = db.session.query(HealthResult).filter_by(check_id=cid).all()
        assert rows and all(r.message == _EMMETT_MSG for r in rows)
    ch = admin_client.get(f"/service/{eid}/health").get_json()["checks"][0]
    assert ch["message"] == _EMMETT_MSG
    assert ch["failures"][0]["message"] == _EMMETT_MSG
    assert _EMMETT_MSG in [m for b in ch["bars"] for m in b["messages"]]


def test_panel_js_falls_back_to_status_for_a_down_check_without_message():
    src = open("static/js/health_detail.js").read()
    assert "c.message ||" in src and "' (empty reply)'" in src and "'no reply'" in src


def test_static_assets_carry_a_version_query(admin_client):
    html = admin_client.get("/tiled_dash").get_data(as_text=True)
    for f in ("css/dashboard.css", "js/dashboard.js", "js/health_detail.js", "js/uptime_strip.js"):
        assert f"/static/{f}?v=" in html
