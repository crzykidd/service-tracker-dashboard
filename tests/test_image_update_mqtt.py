"""Image update state over MQTT and as Home Assistant `update` entities (img-04). Uses the fake
paho client from tests/test_notifications.py; no thread, no socket, no registry."""

import json
from datetime import datetime

import pytest

import image_update
import notify
import notify_purge
import notify_state
from extensions import db
from models import ImageReference, ServiceEntry
from tests.test_ha_discovery import _cfg, _configs, _entry, _node, _setup
from tests.test_state_publishing import _sync

D1 = "sha256:" + "a1b2c3d" + "0" * 57
D2 = "sha256:" + "e4f5a6b" + "0" * 5      # the stored `latest` form: 12 hex


@pytest.fixture
def factory():
    from tests.test_notifications import Factory
    fake = Factory()
    notify.set_client_factory(fake)
    return fake


def _image(app_eid, ref, state, latest=None, kind=None, model=None, digest=None, info=None,
           policy="auto", enable=True):
    """Make a (manual) test entry a Docker entry with stored image update state."""
    e = db.session.get(ServiceEntry, app_eid)
    e.source = "notifier"
    e.image_ref = ref
    e.image_update_policy = policy
    e.image_update_state, e.image_update_latest, e.image_update_kind = state, latest, kind
    e.image_update_detail = {"model": model} if model else None
    e.image_running_digest = digest
    e.image_info = info
    reg, rest = ref.split("/", 1)
    repo, _, tag = rest.partition(":")
    if "@" not in rest and not ImageReference.query.filter_by(ref=ref).first():
        db.session.add(ImageReference(ref=ref, registry_name=reg, repository=repo, tag=tag,
                                      last_wanted_at=datetime.utcnow(),
                                      checked_at=datetime(2026, 11, 20, 3, 0, 0)))
    image_update.save_settings(enabled=enable)
    db.session.commit()


def _topic(client, eid):
    sent = {t: p for t, p, *_x in client.published}
    return json.loads(sent[f"std/entry/{eid}/image"])


def _sent_topics(client):
    return {t for t, p, *_x in client.published if p != ""}


def _cleared(client):
    return {t for t, p, _q, r in client.published if p == "" and r}


def _states(client):
    return {t: json.loads(p) for t, p, *_x in client.published if t.startswith("std/") and p}


# --- the state topic -------------------------------------------------------------------


def test_tag_model_update_payload(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags",
               info={"version": "1.0.0", "source": "https://github.com/o/app"})
        _sync(pub, app)
    assert _topic(client, eid) == {
        "installed_version": "1.0.0", "latest_version": "1.2.0", "title": "o/app",
        "release_url": "https://github.com/o/app/releases", "release_summary": None,
        "state": "update", "kind": "minor", "checked_at": "2026-11-20T03:00:00Z", "std_entry_id": eid}
    assert all(r for t, _p, _q, r in client.published if t.endswith("/image"))        # retained


def test_tag_model_current_shows_the_running_tag_twice(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("db")
        _image(eid, "docker.io/library/postgres:16.1", "current", model="tags")
        _sync(pub, app)
    p = _topic(client, eid)
    assert p["installed_version"] == p["latest_version"] == "16.1" and p["state"] == "current"
    assert p["title"] == "library/postgres" and p["kind"] is None


def test_digest_model_formats_tag_at_seven_hex(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("moving")
        _image(eid, "docker.io/library/nginx:latest", "update", latest=D2, kind="digest",
               model="digest", digest=D1, info={"version": "1.27.2"})
        cur, _ = _entry("same")
        _image(cur, "docker.io/library/redis:latest", "current", model="digest", digest=D1)
        _sync(pub, app)
    p = _topic(client, eid)
    assert p["installed_version"] == "latest@a1b2c3d" and p["latest_version"] == "latest@e4f5a6b"
    assert p["release_summary"] == "Running version 1.27.2" and p["kind"] == "digest"
    q = _topic(client, cur)
    assert q["installed_version"] == q["latest_version"] == "latest@a1b2c3d"
    assert q["release_summary"] is None


@pytest.mark.parametrize("state", ["unknown", "error"])
def test_unknown_and_error_have_no_installed_version(app, factory, state):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("x")
        _image(eid, "ghcr.io/o/app:1.0.0", state, model="tags")
        _sync(pub, app)
    p = _topic(client, eid)
    assert p["installed_version"] is None and p["latest_version"] is None and p["state"] == state


def test_pinned_reads_as_up_to_date_not_unknown(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("pin")
        _image(eid, "docker.io/library/nginx@" + D1, "pinned")
        _sync(pub, app)
    p = _topic(client, eid)
    assert p["installed_version"] == p["latest_version"] == "@a1b2c3d" and p["state"] == "pinned"


def test_off_and_no_image_publish_no_image_topic(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        off, _ = _entry("off")
        _image(off, "ghcr.io/o/a:1.0.0", "off", policy="off")
        plain, _ = _entry("plain")                  # no image at all
        _sync(pub, app)
    assert not [t for t in _sent_topics(client) if t.endswith("/image")]
    assert _states(client)[f"std/entry/{off}/state"]["image_update_state"] is None


# --- additive fields -------------------------------------------------------------------


def test_summary_updates_and_state_field_are_additive(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        a, _ = _entry("a")
        _image(a, "ghcr.io/o/a:1.0.0", "update", latest="1.1.0", kind="minor", model="tags")
        b, _ = _entry("b")
        _image(b, "ghcr.io/o/b:1.0.0", "update", latest="2.0.0", kind="major", model="tags")
        c, _ = _entry("c")
        _image(c, "ghcr.io/o/c:1.0.0", "current", model="tags")
        _sync(pub, app)
    sent = _states(client)
    assert sent["std/summary"] == {"up": 0, "degraded": 0, "down": 0, "unknown": 3, "none": 0,
                                   "total": 3, "updates": 2}
    assert sent[f"std/entry/{a}/state"]["image_update_state"] == "update"
    assert sent[f"std/entry/{c}/state"]["image_update_state"] == "current"
    # every pre-existing key is still there with the same meaning
    for key in ("state", "entry_id", "std_entry_id", "name", "host", "group", "source", "dashboard_url",
                "since", "checks"):
        assert key in sent[f"std/entry/{a}/state"]


def test_updates_never_touch_health_or_the_state_sensors(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("a")
        before = None
        _sync(pub, app)
        before = _states(client)[f"std/entry/{eid}/state"]["state"]
        _image(eid, "ghcr.io/o/a:1.0.0", "update", latest="1.1.0", kind="minor", model="tags")
        _sync(pub, app)
    after = _states(client)
    assert after[f"std/entry/{eid}/state"]["state"] == before
    assert after["std/summary"]["total"] == 1 and after["std/summary"]["unknown"] == 1
    node = _node(app)
    state_cfg = _cfg(client, node, "sensor", f"entry_{eid}_state")
    assert state_cfg["options"] == ["up", "degraded", "down", "unknown", "none"]
    assert "update" not in state_cfg["value_template"]


# --- Home Assistant discovery ----------------------------------------------------------------


def test_update_entity_and_hub_sensor_config(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags")
        _sync(pub, app)
    node = _node(app)
    cfg = _cfg(client, node, "update", f"entry_{eid}_image")
    assert cfg["unique_id"] == f"{node}_entry_{eid}_image"
    assert cfg["state_topic"] == f"std/entry/{eid}/image"
    assert cfg["entity_category"] == "diagnostic"
    assert cfg["availability_topic"] == "std/status"
    assert "command_topic" not in cfg and "entity_picture" not in cfg
    assert cfg["device"]["identifiers"] == [f"{node}_entry_{eid}"]
    assert cfg["default_entity_id"] == "update.std_web_image"
    hub = _cfg(client, node, "sensor", "hub_updates")
    assert hub["name"] == "Updates available" and hub["unique_id"] == f"{node}_hub_updates"
    assert hub["state_topic"] == "std/summary" and hub["value_template"] == "{{ value_json.updates }}"
    assert hub["availability_topic"] == "std/status"
    assert hub["device"]["identifiers"] == [node]


def test_no_entity_for_unpublished_policy_off_or_non_image_entries(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        optout, _ = _entry("optout", publish=False)
        _image(optout, "ghcr.io/o/a:1.0.0", "current", model="tags")
        off, _ = _entry("off")
        _image(off, "ghcr.io/o/b:1.0.0", "off", policy="off")
        plain, _ = _entry("plain")
        _sync(pub, app)
    node = _node(app)
    updates = [t for t in _configs(client) if "/update/" in t]
    assert updates == []
    assert f"std/entry/{optout}/image" in _sent_topics(client)      # the topic still goes out
    assert f"homeassistant/sensor/{node}/hub_updates/config" in _configs(client)


def test_withdrawn_when_the_check_is_switched_off(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags")
        _sync(pub, app)
        assert f"std/entry/{eid}/image" in _sent_topics(client)
        client.published.clear()
        image_update.save_settings(enabled=False)
        db.session.commit()
        image_update.on_settings_changed(app, True)           # what the UI and API call
        assert pub.sync_pending()
        pub.run_sync_now(app)
        cleared = _cleared(client)
        summary = _states(client)["std/summary"]
        state = _states(client)[f"std/entry/{eid}/state"]
    assert f"std/entry/{eid}/image" in cleared
    assert f"homeassistant/update/{node}/entry_{eid}_image/config" in cleared
    assert f"homeassistant/sensor/{node}/hub_updates/config" in cleared
    assert summary["updates"] == 0 and state["image_update_state"] is None


def test_switching_on_fires_a_full_sync(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags",
               enable=False)
        _sync(pub, app)
        assert f"std/entry/{eid}/image" not in _sent_topics(client)
        client.published.clear()
        image_update.save_settings(enabled=True)
        db.session.commit()
        image_update.on_settings_changed(app, False)
        assert pub.sync_pending() and pub._sync_force
        pub.run_sync_now(app)
    assert f"std/entry/{eid}/image" in _sent_topics(client)
    assert f"homeassistant/update/{node}/entry_{eid}_image/config" in _configs(client)
    assert _states(client)["std/summary"]["updates"] == 1


def test_unchanged_toggle_does_not_force_a_sync(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        image_update.save_settings(enabled=True)
        db.session.commit()
        pub.run_sync_now(app)                               # the connect's own sync
        image_update.on_settings_changed(app, True)
        assert not pub.sync_pending()


def test_policy_off_opt_out_soft_delete_and_purge_clear_the_image_topic_and_entity(app, factory):
    pub, client = _setup(app, factory)
    node = _node(app)
    cfg = f"homeassistant/update/{node}/entry_%s_image/config"
    with app.app_context():
        ids = {}
        for name in ("pol", "opt", "soft", "gone"):
            eid, _ = _entry(name)
            _image(eid, f"ghcr.io/o/{name}:1.0.0", "current", model="tags")
            ids[name] = eid
        _sync(pub, app)
        for name, change in (("pol", "policy"), ("opt", "optout"), ("soft", "soft"), ("gone", "delete")):
            client.published.clear()
            e = db.session.get(ServiceEntry, ids[name])
            if change == "policy":
                e.image_update_policy, e.image_update_state = "off", "off"
            elif change == "optout":
                e.ha_publish = False
            elif change == "soft":
                e.deleted_at = datetime.now()
            else:
                db.session.delete(e)
            db.session.commit()
            assert pub.sync_pending()
            pub.run_sync_now(app)
            cleared = _cleared(client)
            assert cfg % ids[name] in cleared, name
            if change == "optout":
                assert f"std/entry/{ids[name]}/image" not in cleared     # topic stays, entity goes
            else:
                assert f"std/entry/{ids[name]}/image" in cleared, name


def test_entry_purge_clears_and_republishes_the_image_topic(app, factory, monkeypatch):
    monkeypatch.setattr(notify_purge, "SETTLE_SECONDS", 0)
    monkeypatch.setattr(notify_purge, "QUIET_SECONDS", 0)
    monkeypatch.setattr(notify_purge, "HA_PROCESS_SECONDS", 0)
    pub, client = _setup(app, factory)
    node = _node(app)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags")
        _sync(pub, app)
        client.published.clear()
        notify_purge.purge_entry(pub, eid)
    cleared = _cleared(client)
    assert f"std/entry/{eid}/image" in cleared
    assert f"homeassistant/update/{node}/entry_{eid}_image/config" in cleared
    assert f"std/entry/{eid}/image" in _sent_topics(client)           # republished after


# --- change detection -------------------------------------------------------------------


def test_state_change_requests_one_sync_and_no_change_requests_none(app, factory):
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "current", model="tags")
        _sync(pub, app)
        client.published.clear()
        e = db.session.get(ServiceEntry, eid)
        # the job's own write path: nothing changed -> no commit-driven sync
        ev = image_update.image_tags.Evaluation("current", model="tags")
        assert image_update.apply_evaluation(e, ev) is False
        db.session.commit()
        assert not pub.sync_pending()
        # a newer tag appears
        ev = image_update.image_tags.Evaluation("update", latest="1.1.0", kind="minor", model="tags")
        assert image_update.apply_evaluation(e, ev) is True
        db.session.commit()
        assert pub.sync_pending()
        pub.run_sync_now(app)
        sent = _sent_topics(client)
        assert f"std/entry/{eid}/image" in sent and f"std/entry/{eid}/state" in sent
        client.published.clear()
        assert _sync(pub, app, force=False) == (0, 0)             # a repeat sync publishes nothing
    assert client.published == []


def test_the_job_never_waits_on_the_broker(app, factory):
    """Change detection only sets a flag; publishing happens on the publisher thread."""
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, _ = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "current", model="tags")
        _sync(pub, app)
        client.published.clear()
        e = db.session.get(ServiceEntry, eid)
        e.image_update_state = "unknown"
        db.session.commit()
        assert client.published == [] and pub.sync_pending()


def test_summary_from_publish_changes_keeps_updates(app, factory):
    """A health change publishes the summary too; it must carry the same `updates` count."""
    from tests.test_state_publishing import _result
    pub, client = _setup(app, factory)
    with app.app_context():
        eid, cid = _entry("web")
        _image(eid, "ghcr.io/o/app:1.0.0", "update", latest="1.2.0", kind="minor", model="tags")
        _result(cid, True)
        notify.publish_changes([cid])
        pub.drain()
    assert _states(client)["std/summary"]["updates"] == 1
    assert notify_state.SUMMARY_TOPIC == "summary"
