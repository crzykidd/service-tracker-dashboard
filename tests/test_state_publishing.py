"""Retained check / roll-up / summary publishing (PRD 17.3). A fake paho client
from tests/test_notifications.py stands in for the broker; no thread, no socket."""

import json
from datetime import datetime, timedelta

import pytest

import checker
import jobs
import notify
from extensions import db
from health_state import entry_health
from models import HealthCheck, ServiceEntry, ensure_url_checks
from tests.test_notifications import Factory, _add


@pytest.fixture
def factory():
    fake = Factory()
    notify.set_client_factory(fake)
    return fake


def _entry(name="web", internalurl="http://i", group=None, **kw):
    e = ServiceEntry(host=None, container_name=name, source="manual", internalurl=internalurl,
                     last_updated=datetime.now(), **kw)
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    e.url_check("internal").enabled = True
    db.session.commit()
    return e.id, e.url_check("internal").id


def _result(check_id, ok, message=None):
    with_check = db.session.get(HealthCheck, check_id)
    changed = jobs.record_check_result(
        with_check, checker.ProbeResult(ok=ok, latency_ms=12, status_code=200 if ok else 500,
                                        message=message))
    db.session.commit()
    return changed


def _setup(app, factory, **config):
    _add(app, config={"host": "mqtt.lan", **config})
    pub = notify.get_publisher()
    pub.reload_now(app)
    client = factory.clients[0]
    client.published.clear()
    return pub, client


def _retained(client):
    """topic -> latest payload text for everything published with retain."""
    out = {}
    for topic, payload, _qos, retain in client.published:
        assert retain or topic.endswith("/test") is False
        out[topic] = payload
    return out


def _sync(pub, app, force=True):
    pub.request_sync(force=force)
    return pub.run_sync_now(app)


# --- change detection --------------------------------------------------------------


def test_first_result_publishes_check_entry_and_summary(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry()
        assert _result(cid, True) is True
        notify.publish_changes([cid])
        pub.drain()
    sent = _retained(client)
    assert set(sent) == {f"std/entry/{eid}/check/{cid}", f"std/entry/{eid}/state", "std/summary"}
    assert all(r for *_x, r in client.published)
    check = json.loads(sent[f"std/entry/{eid}/check/{cid}"])
    assert check["ok"] is True and check["state"] == "up" and check["latency_ms"] == 12
    assert check["target"] == "http://i" and check["check_type"] == "http"
    assert check["last_change"] and check["last_checked_at"]
    entry = json.loads(sent[f"std/entry/{eid}/state"])
    assert entry["state"] == "up" and entry["name"] == "web" and entry["group"] is None
    assert entry["source"] == "manual" and entry["dashboard_url"] == f"/edit/{eid}"
    assert entry["checks"] == {"up": 1, "down": 0, "unknown": 0}
    assert json.loads(sent["std/summary"]) == {"up": 1, "degraded": 0, "down": 0, "unknown": 0,
                                               "none": 0, "total": 1, "updates": 0}


def test_unchanged_result_does_not_publish(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _, cid = _entry()
        assert _result(cid, True) is True
        notify.publish_changes([cid])
        pub.drain()
        client.published.clear()
        assert _result(cid, True, "still fine") is False     # no ok change: nothing to hand over
        assert not pub.queue.qsize()
        assert client.published == []


def test_ok_to_fail_publishes_check_entry_and_summary(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry()
        _result(cid, True)
        notify.publish_changes([cid])
        pub.drain()
        client.published.clear()
        assert _result(cid, False, "HTTP 500") is True
        notify.publish_changes([cid])
        pub.drain()
    sent = _retained(client)
    assert set(sent) == {f"std/entry/{eid}/check/{cid}", f"std/entry/{eid}/state", "std/summary"}
    check = json.loads(sent[f"std/entry/{eid}/check/{cid}"])
    assert (check["ok"], check["state"], check["message"], check["consecutive_failures"]) == \
        (False, "down", "HTTP 500", 1)
    assert json.loads(sent[f"std/entry/{eid}/state"])["state"] == "down"
    assert json.loads(sent["std/summary"])["down"] == 1


def test_rollup_comes_from_entry_health(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry(externalurl="http://e")
        e = db.session.get(ServiceEntry, eid)
        e.url_check("external").enabled = True
        db.session.commit()
        ext = e.url_check("external").id
        _result(cid, True)
        _result(ext, False, "boom")
        notify.publish_changes([cid, ext])
        pub.drain()
        expected = entry_health(db.session.get(ServiceEntry, eid)).state
    assert expected == "degraded"
    assert json.loads(_retained(client)[f"std/entry/{eid}/state"])["state"] == expected


def test_scheduler_tick_publishes_container_check_changes(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        e = ServiceEntry(host="h", container_name="c", source="notifier", docker_status="running",
                         internalurl=None, last_updated=datetime.now(), last_api_update=datetime.now())
        db.session.add(e)
        db.session.flush()
        from models import ensure_container_check
        ensure_container_check(e)
        db.session.commit()
        eid = e.id
        sched = jobs.HealthScheduler(app, executor=None)
        sched.tick(datetime.utcnow())
        pub.drain()
        sched.executor.shutdown(wait=False)
    topics = set(_retained(client))
    assert f"std/entry/{eid}/state" in topics and "std/summary" in topics
    assert any("/check/" in t for t in topics)


# --- full sync -----------------------------------------------------------------------


def test_full_sync_on_connect_publishes_every_entry_and_check(app, factory):
    with app.app_context():
        e1, c1 = _entry("a")
        e2, c2 = _entry("b")
        _result(c1, True)
    _add(app)
    pub = notify.get_publisher()
    pub.reload_now(app)                    # the fake client connects at once -> sync requested
    assert pub.sync_pending()
    assert pub.run_sync_now(app) == (5, 0)
    sent = _retained(factory.clients[0])
    for eid, cid in ((e1, c1), (e2, c2)):
        assert f"std/entry/{eid}/state" in sent and f"std/entry/{eid}/check/{cid}" in sent
    summary = json.loads(sent["std/summary"])
    assert summary["total"] == 2 and summary["up"] == 1 and summary["unknown"] == 1


def test_unforced_sync_skips_unchanged_topics(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        _entry()
        assert _sync(pub, app)[0] == 3
        client.published.clear()
        assert _sync(pub, app, force=False) == (0, 0)
        assert client.published == []


def test_deleted_and_soft_deleted_entries_are_cleared(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        e1, c1 = _entry("a")
        e2, c2 = _entry("b")
        _sync(pub, app)
        client.published.clear()
        db.session.get(ServiceEntry, e1).deleted_at = datetime.now()
        db.session.delete(db.session.get(ServiceEntry, e2))
        db.session.commit()
        assert pub.sync_pending()                       # the commit listener asked for it
        _published, cleared = pub.run_sync_now(app)
    assert cleared == 4
    cleared_topics = {t for t, payload, _q, retain in client.published if payload == "" and retain}
    assert cleared_topics == {f"std/entry/{e1}/state", f"std/entry/{e1}/check/{c1}",
                              f"std/entry/{e2}/state", f"std/entry/{e2}/check/{c2}"}


def test_disabled_check_is_cleared(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry()
        _sync(pub, app)
        client.published.clear()
        db.session.get(HealthCheck, cid).enabled = False
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
    assert (f"std/entry/{eid}/check/{cid}", "", 1, True) in client.published


def test_published_set_survives_a_restart(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry()
        _sync(pub, app)
        pub.stop()
        notify.reset()                                   # a "restart": new publisher, same database
        db.session.delete(db.session.get(ServiceEntry, eid))
        db.session.commit()
    notify.set_client_factory(factory)
    pub2 = notify.get_publisher()
    assert pub2 is not pub
    pub2.reload_now(app)
    client2 = factory.clients[-1]
    client2.published.clear()
    assert pub2.state.topics == set()
    pub2.request_sync(force=True)
    _published, cleared = pub2.run_sync_now(app)
    assert cleared == 2
    assert (f"std/entry/{eid}/state", "", 1, True) in client2.published
    assert (f"std/entry/{eid}/check/{cid}", "", 1, True) in client2.published


def test_rename_keeps_the_topic(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("before")
        _sync(pub, app)
        client.published.clear()
        db.session.get(ServiceEntry, eid).container_name = "after"
        db.session.commit()
        assert pub.sync_pending()                        # the name is in the payload
        assert pub.run_sync_now(app) == (2, 0)      # the entry topic and its check (entry_name)
    assert sorted(t for t, *_x in client.published) == sorted(
        [f"std/entry/{eid}/state", f"std/entry/{eid}/check/{cid}"])
    assert json.loads(dict((t, p) for t, p, *_x in client.published)[f"std/entry/{eid}/state"])["name"] == "after"


def test_last_result_columns_do_not_request_a_sync(app, factory):
    pub, _client = _setup(app, factory)
    with app.app_context():
        _, cid = _entry()
        pub.run_sync_now(app)                            # drop anything pending from the setup commits
        _result(cid, False, "x")
        assert not pub.sync_pending()


def test_disabled_channel_publishes_nothing(app, factory):
    _add(app, enabled=False)
    pub = notify.get_publisher()
    pub.reload_now(app)
    with app.app_context():
        _, cid = _entry()
        _result(cid, True)
        notify.publish_changes([cid])
        pub.request_sync(force=True)
        assert pub.run_sync_now(app) == (0, 0)
        pub.drain()
    assert factory.clients == []


def test_publishing_never_blocks_when_the_queue_is_full(app, factory):
    pub, _client = _setup(app, factory)
    with app.app_context():
        _, cid = _entry()
        for _ in range(notify.QUEUE_MAX):
            pub.queue.put_nowait({"topic": "x", "payload": "1"})
        _result(cid, True)
        started = datetime.now()
        notify.publish_changes([cid])                    # drops the oldest, returns at once
        assert datetime.now() - started < timedelta(seconds=2)
    assert pub.queue.qsize() == notify.QUEUE_MAX and pub.dropped >= 3
