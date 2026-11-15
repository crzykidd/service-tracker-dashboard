"""Soft-delete behavior (v0.6.9): hide, restore, purge, resurrect, backup."""

from datetime import datetime, timedelta

import yaml

import jobs
from extensions import db
from models import Group, ServiceEntry, Widget, WidgetValue, hard_delete_entry


def _make(name="svc1", host="host1", **kw):
    e = ServiceEntry(host=host, container_name=name, last_updated=datetime.now(), **kw)
    db.session.add(e)
    db.session.commit()
    return e


def _names(q):
    return sorted(e.container_name for e in q.all())


def test_delete_hides_from_dashboard_and_health_query(app, admin_client):
    with app.app_context():
        keep, gone = _make("keep"), _make("gone")
        gone_id = gone.id
        assert keep.id
    resp = admin_client.post(f"/api/v1/entries/{gone_id}/delete")
    assert resp.status_code == 200
    with app.app_context():
        assert ServiceEntry.query.get(gone_id).deleted_at is not None
        # The query the dashboards and the health loop use.
        assert _names(ServiceEntry.active()) == ["keep"]
    body = admin_client.get("/tiled_dash").get_data(as_text=True)
    assert "keep" in body and "gone" not in body
    assert admin_client.get(f"/edit/{gone_id}").status_code == 404


def test_edit_page_delete_is_soft(app, admin_client):
    with app.app_context():
        e = _make("svc1")
        eid = e.id
    resp = admin_client.post(
        f"/edit/{eid}", data={"delete": "1", "delete_confirmation": "svc1"}
    )
    assert resp.status_code == 302
    with app.app_context():
        assert ServiceEntry.query.get(eid).deleted_at is not None


def test_delete_keeps_widget_attached(app, admin_client):
    with app.app_context():
        w = Widget(widget_name="w", widget_url="http://x", widget_fields=[])
        db.session.add(w)
        db.session.flush()
        e = _make("svc1", widget_id=w.id)
        eid, wid = e.id, w.id
    admin_client.post(f"/api/v1/entries/{eid}/delete")
    with app.app_context():
        assert Widget.query.get(wid) is not None
        assert ServiceEntry.query.get(eid).widget_id == wid


def test_restore_brings_it_back(app, admin_client):
    with app.app_context():
        e = _make("svc1", deleted_at=datetime.now())
        eid = e.id
    page = admin_client.get("/settings?section=deleted").get_data(as_text=True)
    assert "svc1" in page and "Restore" in page
    resp = admin_client.post(f"/settings/deleted/{eid}/restore")
    assert resp.status_code == 302
    with app.app_context():
        assert _names(ServiceEntry.active()) == ["svc1"]


def test_delete_permanently_removes_row(app, admin_client):
    with app.app_context():
        e = _make("svc1", deleted_at=datetime.now())
        eid = e.id
    admin_client.post(f"/settings/deleted/{eid}/delete")
    with app.app_context():
        assert ServiceEntry.query.get(eid) is None


def test_permanent_delete_refuses_active_entry(app, admin_client):
    with app.app_context():
        eid = _make("svc1").id
    assert admin_client.post(f"/settings/deleted/{eid}/delete").status_code == 404
    with app.app_context():
        assert ServiceEntry.query.get(eid) is not None


def test_purge_removes_expired_keeps_recent(app):
    app.config["deleted_retention_days"] = 30
    with app.app_context():
        _make("old", deleted_at=datetime.now() - timedelta(days=31))
        _make("recent", deleted_at=datetime.now() - timedelta(days=5))
        _make("active")
        jobs.purge_deleted_entries(app)
        assert _names(ServiceEntry.query) == ["active", "recent"]


def test_purge_retention_zero_purges_all_deleted(app):
    app.config["deleted_retention_days"] = 0
    try:
        with app.app_context():
            _make("just_now", deleted_at=datetime.now() - timedelta(seconds=1))
            _make("active")
            jobs.purge_deleted_entries(app)
            assert _names(ServiceEntry.query) == ["active"]
    finally:
        app.config["deleted_retention_days"] = 30


def test_hard_delete_removes_unused_widget(app):
    with app.app_context():
        w = Widget(widget_name="w", widget_url="http://x", widget_fields=[])
        db.session.add(w)
        db.session.flush()
        db.session.add(WidgetValue(widget_id=w.id, widget_value_key="k",
                                   widget_value="1", last_updated=datetime.utcnow()))
        e = _make("svc1", widget_id=w.id)
        wid = w.id
        hard_delete_entry(e)
        db.session.commit()
        assert Widget.query.get(wid) is None
        assert WidgetValue.query.filter_by(widget_id=wid).count() == 0


def test_register_resurrects_with_curated_state(app, register):
    with app.app_context():
        g = Group(group_name="Media")
        db.session.add(g)
        db.session.flush()
        _make("svc1", group_id=g.id, sort_priority=7, deleted_at=datetime.now())
        gid = g.id
    assert register().status_code == 200
    with app.app_context():
        rows = ServiceEntry.query.filter_by(host="host1", container_name="svc1").all()
        assert len(rows) == 1
        assert rows[0].deleted_at is None
        assert rows[0].group_id == gid
        assert rows[0].sort_priority == 7


def test_register_prefers_active_row_over_deleted(app, register):
    with app.app_context():
        deleted = _make("svc1", deleted_at=datetime.now())
        active = _make("svc1")
        did, aid = deleted.id, active.id
    assert register(docker_status="running").status_code == 200
    with app.app_context():
        assert ServiceEntry.query.get(aid).docker_status == "running"
        assert ServiceEntry.query.get(did).deleted_at is not None


def test_group_count_and_delete_ignore_deleted_entries(app, admin_client):
    with app.app_context():
        g = Group(group_name="G")
        db.session.add(g)
        db.session.flush()
        _make("svc1", group_id=g.id, deleted_at=datetime.now())
        gid = g.id
        assert Group.query.get(gid).services_count == 0
    admin_client.post("/delete_group", data={"group_id": gid})
    with app.app_context():
        assert Group.query.get(gid) is None


def test_backup_round_trips_deleted_at(app, admin_client):
    stamp = datetime(2026, 1, 2, 3, 4, 5)
    with app.app_context():
        _make("svc1", deleted_at=stamp)
        _make("svc2")
    resp = admin_client.post("/settings", data={"action": "backup",
                                                "backup_operation": "download_all"})
    assert resp.status_code == 200
    records = yaml.safe_load(resp.get_data(as_text=True))
    by_name = {r["container_name"]: r for r in records}
    assert by_name["svc1"]["deleted_at"] == "2026-01-02 03:04:05"
    assert by_name["svc2"]["deleted_at"] is None

    with app.app_context():
        ServiceEntry.query.delete()
        db.session.commit()
    # v0.6.8-style record for svc2: no deleted_at key at all.
    del by_name["svc2"]["deleted_at"]
    payload = yaml.dump([by_name["svc1"], by_name["svc2"]])
    import io
    resp = admin_client.post("/settings", data={
        "action": "restore", "restore_source": "upload", "restore_scope": "all",
        "restore_file": (io.BytesIO(payload.encode()), "b.yaml"),
    }, content_type="multipart/form-data")
    assert resp.status_code == 302
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="svc1").one().deleted_at == stamp
        assert ServiceEntry.query.filter_by(container_name="svc2").one().deleted_at is None
