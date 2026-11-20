"""Checker probes, scheduler, retention and check-now (v0.7.0, PRD 13.4).

No real network: HTTP is mocked, TCP uses a loopback listener, ping mocks
icmplib. Nothing here starts the background threads (those start only from
run_startup_tasks).
"""

import inspect
import re
import socket
import threading
from concurrent.futures import Future
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import icmplib
import pytest

import checker
import jobs
from extensions import db
from models import HealthCheck, HealthResult, ServiceEntry, ensure_url_checks
from tests.test_health_schema import _pass, _SyncExecutor

# --- helpers -------------------------------------------------------------------


def _resp(code=200, body=b""):
    r = MagicMock()
    r.status_code = code
    r.iter_content.side_effect = lambda chunk_size=1024: iter(
        [body[i:i + chunk_size] for i in range(0, len(body), chunk_size)]
    )
    return r


def _body(code, body, **kw):
    with patch("checker.requests.get", return_value=_resp(code, body)) as get:
        out = checker.probe_http("http://x", "body", 5, True)
    assert get.call_args.kwargs["stream"] is True
    return out


def _entry(name="svc", **kw):
    # Manual by default: these tests are about the URL/service checks; the
    # notifier-only Container check has its own tests (test_container_check.py).
    kw.setdefault("source", "manual")
    e = ServiceEntry(host="h", container_name=name, last_updated=datetime.now(), **kw)
    ensure_url_checks(e)
    db.session.add(e)
    db.session.commit()
    return e


# --- HTTP body mode --------------------------------------------------------------


@pytest.mark.parametrize("body", [b"OK", b"ok", b"  Ok\n"])
def test_body_ok_case_insensitive(body):
    out = _body(200, body)
    assert out.ok is True and out.message is None and out.status_code == 200


def test_body_error_prefix_gives_message_capped():
    out = _body(200, b"Error:   database down  ")
    assert out.ok is False and out.message == "database down"
    out = _body(200, b"Error: " + b"x" * 500)
    assert len(out.message) == 200


def test_body_unexpected_response_truncated():
    out = _body(200, b"<html>" + b"a" * 200)
    assert out.ok is False
    assert out.message == "Unexpected response: " + ("<html>" + "a" * 200)[:60]


def test_body_status_400_handling():
    assert _body(503, b"Error: maintenance").message == "maintenance"
    out = _body(500, b"some html")
    assert out.ok is False and out.message == "500: some html" and out.status_code == 500
    assert _body(500, b"").message == "500"
    # An OK body does not rescue a failing status.
    assert _body(500, b"OK").ok is False


def test_body_read_capped_at_4kb():
    resp = _resp(200, b"OK" + b" " * 10000 + b"junk")
    with patch("checker.requests.get", return_value=resp):
        out = checker.probe_http("http://x", "body", 5, True)
    assert out.ok is True  # junk past 4 KB was never read


def test_status_mode_streams_closes_and_skips_body_on_success():
    resp = _resp(200, b"some body")
    with patch("checker.requests.get", return_value=resp) as get:
        out = checker.probe_http("http://x", "status", 5, True)
    assert out.ok and out.message is None and get.call_args.kwargs["stream"] is True
    resp.iter_content.assert_not_called()  # codes below 400: body not read
    resp.close.assert_called()


# --- HTTP status mode failure message (v0.9.0 step 8) -----------------------------


def _status(code, body):
    resp = _resp(code, body)
    with patch("checker.requests.get", return_value=resp):
        out = checker.probe_http("http://x", "status", 5, True)
    resp.close.assert_called()
    assert out.ok is False and out.status_code == code
    return out.message


def test_status_failure_emmett_json():
    body = (b'{"status":"Error","last_error":"Mgmt1: Scope \'Mgmt1\' not found on destination ...",'
            b'"failing_scopes":["Mgmt","Mgmt1"]}')
    assert _status(503, body) == "503: Mgmt1: Scope 'Mgmt1' not found on destination ..."


@pytest.mark.parametrize("body,expected", [
    (b'{"error": "boom"}', "503: boom"),
    (b'{"error": {"message": "nested"}}', "503: nested"),
    (b'{"detail": "x"}', "503: x"),
    (b'{"message": "m", "detail": "d"}', "503: m"),
    (b'{"last_error": "", "error": "e"}', "503: e"),            # empty skipped
    (b'{"error": 5, "message": "m"}', "503: m"),                # non-string skipped
    (b'{"status": "Error", "n": 1}', '503: {"status": "Error", "n": 1}'),  # raw fallback
    (b"\n\n  first line  \nsecond\n", "503: first line"),
    (b"a   b \t c", "503: a b c"),
    (b"", "503"),
    (b"   \n ", "503"),
    (b"\x89PNG\xff\xfe\x00\x01", "503"),                      # not UTF-8
    (b"\x01\x02\x03\x04abc", "503"),                           # control characters
])
def test_status_failure_messages(body, expected):
    assert _status(503, body) == expected


def test_status_failure_long_body_capped_and_never_over_read():
    resp = _resp(500, b"x" * 20000)
    with patch("checker.requests.get", return_value=resp):
        out = checker.probe_http("http://x", "status", 5, True)
    assert len(out.message) <= 200 and out.message.endswith("…") and out.message.startswith("500: xxx")
    assert resp.iter_content.side_effect  # chunks are lazy; stop at the limit
    consumed = []
    def gen(chunk_size=1024):
        for _ in range(100):
            consumed.append(1)
            yield b"y" * chunk_size
    resp2 = _resp(500)
    resp2.iter_content.side_effect = gen
    with patch("checker.requests.get", return_value=resp2):
        checker.probe_http("http://x", "status", 5, True)
    assert len(consumed) * 1024 <= checker.BODY_READ_LIMIT + 1024


def test_status_failure_with_cert_condition_keeps_http_message():
    resp = _resp(503, b'{"error": "boom"}')
    with patch("checker.requests.get", return_value=resp), \
            patch("checker._apply_cert_condition", side_effect=lambda r, *a: r):
        out = checker.probe_http("https://x", "status", 5, True, cert_min_days=14)
    assert out.message == "503: boom"


def test_http_exception_never_raises():
    import requests

    with patch("checker.requests.get", side_effect=requests.ConnectionError("refused")):
        out = checker.probe_http("http://x", "body", 5, True)
    assert out.ok is False and out.message.startswith("ConnectionError: refused")


# --- TCP -----------------------------------------------------------------------


def test_tcp_up_and_down():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        up = checker.probe_tcp(f"127.0.0.1:{port}", 2)
        assert up.ok is True and up.latency_ms >= 0
    finally:
        srv.close()
    down = checker.probe_tcp(f"127.0.0.1:{port}", 2)
    assert down.ok is False and down.message


@pytest.mark.parametrize("target", ["nohost", "h:0", "h:99999", "h:abc", ":80", ""])
def test_tcp_bad_target_fails_cleanly(target):
    out = checker.probe_tcp(target, 1)
    assert out.ok is False and out.message


# --- ping ----------------------------------------------------------------------


def _host(received=3, rtt=4.4):
    return MagicMock(packets_received=received, packets_sent=3, avg_rtt=rtt)


def test_ping_ok_and_no_reply():
    with patch("checker.icmplib.ping", return_value=_host()) as ping:
        out = checker.probe_ping("10.0.0.1", 2)
    assert out.ok and out.latency_ms == 4
    assert ping.call_args.kwargs["count"] == 3 and ping.call_args.kwargs["privileged"] is True
    with patch("checker.icmplib.ping", return_value=_host(0)):
        out = checker.probe_ping("10.0.0.1", 2)
    assert out.ok is False and "No reply" in out.message


def test_ping_falls_back_to_unprivileged():
    calls = []

    def fake(host, **kw):
        calls.append(kw["privileged"])
        if kw["privileged"]:
            raise icmplib.SocketPermissionError(True)
        return _host()

    with patch("checker.icmplib.ping", side_effect=fake):
        out = checker.probe_ping("h", 2)
    assert out.ok and calls == [True, False]


def test_ping_permission_failure_message():
    with patch("checker.icmplib.ping", side_effect=icmplib.SocketPermissionError(True)):
        out = checker.probe_ping("h", 2)
    assert out.ok is False and out.message == "ICMP not permitted"


def test_ping_other_error_and_empty_target():
    with patch("checker.icmplib.ping", side_effect=icmplib.NameLookupError("nope")):
        out = checker.probe_ping("nope", 2)
    assert out.ok is False and "NameLookupError" in out.message
    assert checker.probe_ping("", 2).ok is False


def test_run_probe_dispatch_never_raises():
    with patch("checker.probe_tcp") as tcp, patch("checker.probe_ping") as ping, \
            patch("checker.probe_http") as http:
        checker.run_probe({"check_type": "tcp", "target": "h:1", "timeout": 3})
        checker.run_probe({"check_type": "ping", "target": "h", "timeout": 3})
        checker.run_probe({"check_type": "http", "target": "http://h", "mode": "body",
                           "timeout": 3, "verify": False})
    tcp.assert_called_once_with("h:1", 3)
    ping.assert_called_once_with("h", 3)
    http.assert_called_once_with("http://h", "body", 3, False, None)  # cert_min_days off
    assert checker.run_probe({"check_type": "tcp"}).ok is False  # missing keys


# --- due selection ---------------------------------------------------------------


def test_due_selection_rules(app):
    now = datetime(2026, 1, 1, 12, 0, 0)
    with app.app_context():
        e = _entry("a", internalurl="http://i", externalurl="http://e")
        internal, external = e.url_check("internal"), e.url_check("external")
        internal.enabled = True
        external.enabled = False
        svc = HealthCheck(service_entry_id=e.id, kind="service", name="db", check_type="tcp",
                          target="db:5432", enabled=True, interval_seconds=60)
        notarget = HealthCheck(service_entry_id=e.id, kind="service", name="x", check_type="tcp",
                               target=None, enabled=True)
        db.session.add_all([svc, notarget])
        gone = _entry("gone", internalurl="http://g", deleted_at=datetime.now())
        gone.url_check("internal").enabled = True
        db.session.commit()

        due = jobs.select_due_jobs(app, now)
        targets = sorted(j["target"] for j in due)
        assert targets == ["db:5432", "http://i"]  # disabled/targetless/deleted skipped
        by_target = {j["target"]: j for j in due}
        assert by_target["db:5432"]["check_type"] == "tcp"
        assert by_target["http://i"]["timeout"] == 5 and by_target["http://i"]["verify"] is True

        # Not yet due: interval (global 300 here) has not elapsed.
        internal.last_checked_at = now - timedelta(seconds=299)
        svc.last_checked_at = now - timedelta(seconds=59)
        db.session.commit()
        assert jobs.select_due_jobs(app, now) == []
        # Due exactly at the boundary; per-check interval below 30 is clamped to 30.
        internal.last_checked_at = now - timedelta(seconds=300)
        svc.last_checked_at = now - timedelta(seconds=60)
        db.session.commit()
        assert len(jobs.select_due_jobs(app, now)) == 2
        svc.interval_seconds = 5
        svc.last_checked_at = now - timedelta(seconds=29)
        internal.last_checked_at = now
        db.session.commit()
        assert jobs.select_due_jobs(app, now) == []
        # Skipped when already in flight.
        internal.last_checked_at = None
        db.session.commit()
        assert jobs.select_due_jobs(app, now, skip_ids={internal.id}) == []


def test_missing_url_rows_created_by_selection(app):
    with app.app_context():
        e = ServiceEntry(host="h", container_name="legacy", last_updated=datetime.now(),
                         internalurl="http://i")
        db.session.add(e)
        db.session.commit()
        assert HealthCheck.query.count() == 0
        jobs.select_due_jobs(app)
        # Two URL rows plus the notifier entry's Container check.
        assert HealthCheck.query.count() == 3


# --- scheduler / single writer ----------------------------------------------------


def test_worker_takes_no_session_and_touches_no_db():
    params = list(inspect.signature(jobs._run_job).parameters)
    assert params == ["job"]
    src = inspect.getsource(jobs._run_job)
    assert "db." not in src and "session" not in src


def test_workers_do_no_db_writes(app):
    """Run through a real pool: results are written only by tick()."""
    with app.app_context():
        e = _entry("pool", internalurl="http://i")
        e.url_check("internal").enabled = True
        db.session.commit()
    sched = jobs.HealthScheduler(app)  # real ThreadPoolExecutor
    try:
        with patch("checker.requests.get") as get:
            get.return_value.status_code = 200
            sched.tick()
            for f in list(sched.in_flight.values()):
                f.result(timeout=5)
            with app.app_context():
                assert HealthResult.query.count() == 0  # nothing written by workers
            sched.tick()
        with app.app_context():
            assert HealthResult.query.count() == 1
    finally:
        sched.shutdown()


def test_in_flight_prevents_double_submission(app):
    with app.app_context():
        e = _entry("slow", internalurl="http://i")
        e.url_check("internal").enabled = True
        db.session.commit()
    pending = Future()
    executor = MagicMock()
    executor.submit.return_value = pending
    sched = jobs.HealthScheduler(app, executor=executor)
    assert sched.tick() == (0, 1)
    assert sched.tick() == (0, 0)  # still running: not resubmitted
    assert executor.submit.call_count == 1
    pending.set_result((next(iter(sched.in_flight)), checker.ProbeResult(True, 5, 200)))
    written, submitted = sched.tick()
    assert written == 1 and submitted == 0
    assert sched.in_flight == {}


def test_result_for_deleted_check_is_dropped(app):
    with app.app_context():
        e = _entry("vanish", internalurl="http://i")
        e.url_check("internal").enabled = True
        db.session.commit()
        cid = e.url_check("internal").id
    sched = jobs.HealthScheduler(app, executor=_SyncExecutor())
    with patch("checker.requests.get") as get:
        get.return_value.status_code = 200
        sched.tick()
        with app.app_context():
            HealthCheck.query.filter_by(id=cid).delete()
            db.session.commit()
        assert sched.tick()[0] == 0


def test_service_check_runs_and_records(app):
    with app.app_context():
        e = _entry("svc-tcp")
        db.session.add(HealthCheck(service_entry_id=e.id, kind="service", name="db",
                                   check_type="tcp", target="db:5432", enabled=True))
        db.session.commit()
    with patch("checker.probe_tcp", return_value=checker.ProbeResult(False, 12, None, "timed out")):
        _pass(app)
    with app.app_context():
        c = HealthCheck.query.filter_by(kind="service").one()
        assert c.last_ok is False and c.last_message == "timed out" and c.consecutive_failures == 1
        assert ServiceEntry.query.one().internal_health_check_status is None


def test_loop_survives_tick_errors_and_stops(app):
    stop = threading.Event()
    sched = MagicMock()
    calls = []

    def tick():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("db gone")
        stop.set()

    sched.tick.side_effect = tick
    with patch.object(jobs, "TICK_SECONDS", 0):
        jobs.health_check_loop(app, stop_event=stop, scheduler=sched)
    assert sched.tick.call_count == 2
    sched.shutdown.assert_called_once()


def test_no_background_threads_started_by_tests():
    names = [t.name for t in threading.enumerate()]
    assert "health-check-loop" not in names


def test_settings_defaults(app):
    for key, val in (("health_check_workers", 8), ("health_raw_hours", 24), ("health_history_days", 7)):
        assert app.config[key] == val


# --- retention -------------------------------------------------------------------


def _add(check_id, ts, ok=True, latency=10, **kw):
    r = HealthResult(check_id=check_id, ts=ts, ok=ok, latency_ms=latency,
                     latency_max_ms=latency, status_code=200 if ok else 500, **kw)
    db.session.add(r)
    return r


def _check_id():
    e = _entry("ret")
    return e.url_check("internal").id


def _uptime(check_id):
    rows = HealthResult.query.filter_by(check_id=check_id).all()
    total = sum(r.samples for r in rows)
    return sum(r.samples for r in rows if r.ok), total


NOW = datetime(2026, 6, 10, 12, 30, 0)


def test_compaction_ranges_and_failures(app):
    with app.app_context():
        cid = _check_id()
        base = datetime(2026, 6, 8, 10, 0, 0)  # > 24h before NOW
        # hour 10: 4 ok, a failure, 2 ok -> two ranges around the failure
        for i, lat in enumerate((10, 20, 30, 40)):
            _add(cid, base + timedelta(minutes=i), latency=lat)
        _add(cid, base + timedelta(minutes=4), ok=False)
        _add(cid, base + timedelta(minutes=5), latency=100)
        _add(cid, base + timedelta(minutes=6), latency=200)
        # hour 11: 3 ok
        for i in range(3):
            _add(cid, base + timedelta(hours=1, minutes=i), latency=50)
        # hour 12 yesterday's tail: a single sample
        _add(cid, base + timedelta(hours=2), latency=7)
        # recent rows stay raw
        for i in range(3):
            _add(cid, NOW - timedelta(hours=2, minutes=i))
        db.session.commit()
        before = _uptime(cid)

        removed = jobs.compact_health_results(app, NOW)
        assert removed == 3 + 1 + 2 + 0

        rows = HealthResult.query.filter_by(check_id=cid).order_by(HealthResult.ts).all()
        old = [r for r in rows if r.ts < NOW - timedelta(hours=24)]
        assert len(old) == 5  # range(4), failure, range(2), range(3), single
        r1, fail, r2, r3, single = old
        assert (r1.samples, r1.ts_end, r1.latency_ms, r1.latency_max_ms) == (
            4, base + timedelta(minutes=3), 25.0, 40)
        assert fail.ok is False and fail.samples == 1 and fail.ts_end is None
        assert (r2.samples, r2.latency_ms, r2.latency_max_ms) == (2, 150.0, 200)
        assert (r3.samples, r3.ts, r3.ts_end) == (3, base + timedelta(hours=1),
                                                   base + timedelta(hours=1, minutes=2))
        assert single.samples == 1 and single.ts_end == single.ts
        assert len([r for r in rows if r.ts >= NOW - timedelta(hours=24)]) == 3
        assert _uptime(cid) == before  # uptime totals preserved

        # Idempotent.
        assert jobs.compact_health_results(app, NOW) == 0


def test_compaction_only_whole_hours_before_cutoff(app):
    with app.app_context():
        cid = _check_id()
        # cutoff = 12:30 - 24h = yesterday 12:30 -> floored to 12:00 yesterday
        edge = NOW - timedelta(hours=24)
        _add(cid, edge.replace(minute=10))  # hour 12:00 yesterday is NOT whole-before-cutoff
        _add(cid, edge.replace(minute=20))
        _add(cid, edge.replace(minute=0) - timedelta(minutes=5))  # 11:55 -> compactable
        _add(cid, edge.replace(minute=0) - timedelta(minutes=6))
        db.session.commit()
        jobs.compact_health_results(app, NOW)
        rows = HealthResult.query.filter_by(check_id=cid).order_by(HealthResult.ts).all()
        assert [r.samples for r in rows] == [2, 1, 1]


def test_compaction_respects_raw_hours_setting(app):
    with app.app_context():
        cid = _check_id()
        for i in range(3):
            _add(cid, NOW - timedelta(hours=3, minutes=i))
        db.session.commit()
        assert jobs.compact_health_results(app, NOW) == 0
        app.config["health_raw_hours"] = 1
        try:
            assert jobs.compact_health_results(app, NOW) == 2
        finally:
            app.config["health_raw_hours"] = 24


def test_purge_boundary(app):
    with app.app_context():
        cid = _check_id()
        cutoff = NOW - timedelta(days=7)
        _add(cid, cutoff - timedelta(seconds=1))                   # purged
        _add(cid, cutoff)                                          # kept (not older)
        _add(cid, cutoff - timedelta(hours=1), ok=False)           # purged failure
        rng = _add(cid, cutoff - timedelta(hours=2))
        rng.ts_end = cutoff + timedelta(minutes=1)                 # range still reaching in: kept
        db.session.commit()
        assert jobs.purge_health_results(app, NOW) == 2
        assert HealthResult.query.count() == 2


def test_purge_batches(app):
    with app.app_context():
        cid = _check_id()
        for i in range(25):
            _add(cid, NOW - timedelta(days=30, minutes=i))
        db.session.commit()
        with patch.object(jobs, "PURGE_BATCH", 10):
            assert jobs.purge_health_results(app, NOW) == 25
        assert HealthResult.query.count() == 0


def test_retention_jobs_registered(app):
    with patch("jobs.BackgroundScheduler") as sched_cls, patch("jobs.threading.Thread") as thread, \
            patch("jobs.notify.start") as notify_start:
        jobs.start_background_workers(app)
    ids = {c.kwargs["id"] for c in sched_cls.return_value.add_job.call_args_list}
    assert {"health_result_purge_job", "health_result_compaction_job"} <= ids
    notify_start.assert_called_once_with(app)  # the publisher has its own thread
    assert thread.call_args.kwargs["daemon"] is True
    thread.return_value.start.assert_called_once()  # mocked: no real thread


# --- check now -------------------------------------------------------------------


def test_check_now_clears_enabled_checks(app, admin_client):
    with app.app_context():
        e = _entry("now", internalurl="http://i", externalurl="http://e")
        stamp = datetime.utcnow()
        e.url_check("internal").enabled = True
        e.url_check("internal").last_checked_at = stamp
        e.url_check("external").last_checked_at = stamp  # disabled: untouched
        db.session.commit()
        eid = e.id
    resp = admin_client.post(f"/service/{eid}/checks/run")
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] is True and body["queued"] == 1
    assert body["requested_at"].endswith("Z")
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        internal_id = e.url_check("internal").id
        # The last result stays visible while the run is pending.
        assert e.url_check("internal").last_checked_at == stamp
        assert internal_id in jobs._pending_run_requests()
        assert e.url_check("external").id not in jobs._pending_run_requests()
        # The requested check is due now despite a fresh last_checked_at,
        # and submitting it clears the request.
        due = {j["check_id"] for j in jobs.select_due_jobs(app)}
        assert internal_id in due
    jobs._clear_run_requests([internal_id])


def test_check_now_404_for_unknown_or_deleted(app, admin_client):
    assert admin_client.post("/service/9999/checks/run").status_code == 404
    with app.app_context():
        e = _entry("del", deleted_at=datetime.now())
        eid = e.id
    assert admin_client.post(f"/service/{eid}/checks/run").status_code == 404


def test_check_now_requires_login(app, client):
    resp = client.post("/service/1/checks/run")
    assert resp.status_code in (302, 401)


def test_check_now_requires_csrf(app, admin_client):
    with app.app_context():
        eid = _entry("csrf").id
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = admin_client.post(f"/service/{eid}/checks/run", headers={"Accept": "application/json"})
        assert resp.status_code == 400
        html = admin_client.get("/settings").get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
        ok = admin_client.post(f"/service/{eid}/checks/run", headers={"X-CSRFToken": token})
        assert ok.status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_check_now_request_cleared_once_submitted(app):
    from tests.test_health_schema import _SyncExecutor

    with app.app_context():
        e = _entry("req", internalurl="http://i")
        check = e.url_check("internal")
        check.enabled = True
        check.last_checked_at = datetime.utcnow()
        db.session.commit()
        cid = check.id
    jobs.request_run([cid])
    sched = jobs.HealthScheduler(app, executor=_SyncExecutor())
    with patch("checker.run_probe", return_value=checker.ProbeResult(True, 1, 200, "200")):
        sched.tick()
    assert cid not in jobs._pending_run_requests()


def test_body_mode_status_failure_uses_json_reason():
    body = (b'{"status":"Error","last_error":"Mgmt1: Scope \'Mgmt1\' not found on destination ...",'
            b'"failing_scopes":["Mgmt","Mgmt1"]}')
    out = _body(503, body)
    assert out.ok is False and out.status_code == 503
    assert out.message == "503: Mgmt1: Scope 'Mgmt1' not found on destination ..."


_HEALTHZ_503 = (
    b'{"status": "Error", "last_sync": "2026-11-17T03:32:17+00:00", "last_error": "Mgmt1: Scope '
    b"'Mgmt1' not found on destination 10.100.16.17.; Mgmt: Scope 'Mgmt' exists on destination "
    b"10.100.16.17 but not on source 10.100.16.16.\", \"failing_scopes\": [\"Mgmt\", \"Mgmt1\"]}"
)
_HEALTHZ_MSG = (
    "503: Mgmt1: Scope 'Mgmt1' not found on destination 10.100.16.17.; Mgmt: Scope 'Mgmt' "
    "exists on destination 10.100.16.17 but not on source 10.100.16.16."
)


@pytest.mark.parametrize("mode", ["status", "body"])
def test_operator_healthz_503_gives_last_error_in_both_modes(mode):
    with patch("checker.requests.get", return_value=_resp(503, _HEALTHZ_503)):
        out = checker.probe_http("http://x/healthz", mode, 5, True)
    assert out.ok is False and out.status_code == 503
    assert out.message == _HEALTHZ_MSG
