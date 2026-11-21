"""Import engine (backup phase 3): parse, match, plan, apply, fingerprint, staging.

No routes and no UI exist yet, so every test drives `importer` directly. The big scenario
exports a realistic source database, wipes it, re-creates the base the way a new install
would (register again, the sidecar posts a snapshot to a new stream), and imports.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

import backups
import export_format
import importer
import notify
import settings_store
import streams
from check_form import new_service_check, validate_service_check
from extensions import db
from importer import (
    DELETED,
    DIFFERS,
    IDENTICAL,
    MISSING,
    NOT_FOUND,
    WAITING,
    ImportApplyError,
    ImportParseError,
    ImportStale,
)
from models import (
    ApiKey,
    Group,
    InventoryBlock,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    StreamLinkOffer,
    User,
    Widget,
    ensure_url_checks,
)
from tests.test_mgmt_api_keys import _bearer, _key

SNAPSHOT = json.loads((Path(__file__).parent / "fixtures" / "stream_snapshot.json").read_text())
MQTT_PASSWORD = "mqtt-pw-SECRET-123"
TRAEFIK = {"layer": "traefik", "hostname": "grafana.example.com", "tls": True}
NOW = datetime(2026, 11, 20, 0, 10, 2, tzinfo=timezone.utc)

# The Docker entries a new install registers again (the same payloads as the source install).
REGISTERS = [
    dict(host="h1", container_name="grafana", group_name="Monitoring", sort_priority=5, image_icon="grafana",
         internalurl="http://grafana:3000", docker_status="running", exposure_observations=[TRAEFIK]),
    dict(host="h1", container_name="sonarr", image_icon="sonarr"),
    dict(host="h1", container_name="radarr", group_name="Media"),
    dict(host="h1", container_name="plex"),
]


# --- helpers ---------------------------------------------------------------------------------------


def _put(client, app, items=None, slug="dhcp", key=None, name="sidecar"):
    key = key or _key(app, name, "ingest")[1]
    body = dict(SNAPSHOT)
    if items is not None:
        body["items"] = items
    resp = client.put(f"/api/v1/streams/{slug}/snapshot", json=body, headers=_bearer(key))
    assert resp.status_code in (200, 202), resp.get_json()
    return key


def _enable(app, slug="dhcp"):
    with app.app_context():
        streams.enable(InventoryStream.query.filter_by(stream_id=slug).one())


def _entry(app, name, host=None, stream=None):
    with app.app_context():
        q = ServiceEntry.query.filter_by(container_name=name)
        if stream:
            q = q.filter(ServiceEntry.stream_id.isnot(None))
        e = q.one()
        db.session.expunge(e)
        return e


def seed_source(app, client, register):
    """A realistic source install (see the module docstring). Returns the secrets."""
    with app.app_context():
        settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS, {"traefik": "external"})
        settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS_PER_HOST, {"h2": {"traefik": "internal"}})
        settings_store.save_update_check_settings(False, 12)
        settings_store.set_backup_value(settings_store.KEY_BACKUP_SNAPSHOT_TIME, "03:30")
        db.session.commit()
    for payload in REGISTERS:
        assert register(**payload).status_code == 200
    assert register(host="h1", container_name="trashed").status_code == 200
    with app.app_context():
        media = Group.query.filter_by(group_name="Media").one()          # radarr's label created it
        media.group_sort_priority, media.group_icon = 10, "mdi-play"
        home = Group(group_name="Home", group_sort_priority=3)
        iot = Group(group_name="IoT")
        db.session.add_all([home, iot])
        grafana = ServiceEntry.query.filter_by(container_name="grafana").one()
        grafana.ha_publish = True
        ext = grafana.url_check("external")
        ext.enabled, ext.interval_seconds, ext.timeout_seconds = True, 120, 5
        sonarr = ServiceEntry.query.filter_by(container_name="sonarr").one()
        sonarr.is_static = True
        sonarr.externalurl, sonarr.externalurl_source = "https://sonarr.example", "ui_edit"
        sonarr.ha_publish = True
        sonarr.description = "TV"
        widget = Widget(widget_name="sonarr", widget_url="http://sonarr:8989", widget_fields=["queue"],
                        widget_api_key="widget-SECRET-key")
        db.session.add(widget)
        sonarr.widget = widget
        ServiceEntry.query.filter_by(container_name="radarr").one().group = home
        ServiceEntry.query.filter_by(container_name="trashed").one().deleted_at = datetime.now()
        shelf = ServiceEntry(host=None, container_name="shelf", source="manual", last_updated=datetime.now(),
                             internalurl="http://shelf.lan", internalurl_source="ui_edit", image_icon="shelf.svg",
                             group=media, sort_priority=2, description="top shelf")
        db.session.add(shelf)
        ensure_url_checks(shelf)
        nas = ServiceEntry(host=None, container_name="nas", source="manual", last_updated=datetime.now(),
                           ha_publish=True, group=media)
        db.session.add(nas)
        ensure_url_checks(nas)
        values, errors = validate_service_check({"name": "Ping", "check_type": "ping", "target": "10.0.10.5",
                                                 "enabled": True})
        assert not errors
        nas.checks.append(new_service_check(values))
        db.session.add(NotificationChannel(
            type="mqtt", name="home-broker", enabled=True, secret=MQTT_PASSWORD,
            config={"host": "mqtt.lan", "port": 1883, "username": "std", "base_topic": "std"}))
        for name in ("alice", "bob"):
            user = User(username=name, email=f"{name}@example.com", is_admin=name == "alice", is_active=True)
            user.set_password("user-pw-SECRET")
            db.session.add(user)
        db.session.commit()
    _put(client, app)
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        stream.network_exclude = ["Guest"]
        stream.missing_expiry_days = 14
        stream.default_checks = {"ping": True, "tcp_port": None}
        db.session.add(InventoryBlock(stream_id=stream.id, key="aa:bb:cc:00:00:0a", name="no-network",
                                      ip="10.0.0.9", blocked_by="admin"))
        db.session.commit()
    _enable(app)
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        offer = StreamLinkOffer.query.filter_by(stream_id=stream.id, key="aa:bb:cc:00:00:07").one()
        streams.accept_offer(stream, offer)             # nas joins the stream: a linked entry
        kitchen = ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:02").one()
        kitchen.container_name, kitchen.name_source = "kitchen-plug", "ui_edit"
        kitchen.group, kitchen.ha_publish = Group.query.filter_by(group_name="IoT").one(), True
        pump = ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:01").one()
        values, errors = validate_service_check({"name": "Web", "check_type": "tcp", "target": "10.0.40.21:8080",
                                                 "enabled": True})
        assert not errors
        pump.checks.append(new_service_check(values))
        db.session.commit()


def export_source(app, fmt="yaml"):
    with app.app_context():
        return export_format.dump(export_format.build_export(now=NOW), fmt)


def wipe(app):
    with app.app_context():
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()


def recreate_base(app, client, register):
    """What a new install has before the first import: the notifier registered again and the
    sidecar posted a snapshot to a new stream (pending)."""
    for payload in REGISTERS:
        assert register(**payload).status_code == 200
    _put(client, app, key=_key(app, "new-sidecar", "ingest")[1])


def parse(data, name="export.yml"):
    return importer.parse(data if isinstance(data, bytes) else json.dumps(data).encode(), name)


def minimal(**sections):
    """A v1 document with the given sections (plain dicts)."""
    return {"format": "std-export", "format_version": 1, "exported_at": "2026-11-20T00:10:02Z",
            "std_version": "0.11.0", "api_revision": 4, **sections}


def docker_rec(name="grafana", host="h1", **fields):
    return {"kind": "docker", "identity": {"host": host, "container_name": name}, **fields}


def manual_rec(name="shelf", host=None, **fields):
    return {"kind": "manual", "identity": {"host": host, "container_name": name}, **fields}


def stream_rec(key="aa:bb:cc:00:00:01", name="shelly-pump", stream="dhcp", **fields):
    ident = {"stream": stream, "stream_key": key, "container_name": name}
    ident.update(fields.pop("identity", {}))
    return {"kind": "stream", "identity": ident, **fields}


def do_plan(app, parsed, stream_map=None):
    with app.app_context():
        return importer.plan(parsed, stream_map)


def select_all(p, create=True, restore=True, options=None, only=None):
    """A selection of every actionable row of `p` (optionally only the rids in `only`)."""
    sel = {}
    for r in p.rows:
        if only is not None and r.rid not in only:
            continue
        if r.status in (MISSING, DIFFERS):
            sel[r.rid] = {"apply": True}
        elif r.status == NOT_FOUND and create:
            sel[r.rid] = {"apply": True, "create": True}
        elif r.status == DELETED and restore:
            sel[r.rid] = {"apply": True, "options": ["restore"]}
        if r.rid in sel and options and r.rid in options:
            sel[r.rid]["options"] = options[r.rid]
    return sel


def do_apply(app, parsed, selection=None, mode="fill", stream_map=None, fingerprint=None, actor="tester"):
    """Plan, then apply `selection` (default: every actionable row) with the matching fingerprint."""
    with app.app_context():
        p = importer.plan(parsed, stream_map)
        selection = select_all(p) if selection is None else selection
        fp = fingerprint or importer.fingerprint(p, selection)
        result = importer.apply(parsed, stream_map, selection, mode, fp, actor)
        return result, p


def statuses(p):
    return {r.rid: r.status for r in p.rows}


def row(p, rid):
    r = p.row(rid)
    assert r is not None, (rid, [x.rid for x in p.rows])
    return r


def fields(r):
    return {f.field: f for f in r.fields}


def state(app):
    """The operator-owned state of the whole database, comparable between two installs."""
    out = {}
    with app.app_context():
        entries = {}
        for e in ServiceEntry.query.filter(ServiceEntry.deleted_at.is_(None)).all():
            ident = (e.source, e.host, e.container_name) if e.source != "stream" else (
                "stream", e.stream.stream_id, e.stream_key)
            owned = e.source != "notifier" or e.is_static
            entries[ident] = {
                "name": e.container_name, "group": e.group.group_name if e.group else None,
                "sort": e.sort_priority, "description": e.description or None,
                "icon": (e.image_icon or None) if owned else None, "static": bool(e.is_static),
                "ha": bool(e.ha_publish), "name_source": e.name_source,
                "int": (e.internalurl, e.internalurl_source) if e.internalurl_source == "ui_edit" or e.source != "notifier" else None,
                "ext": (e.externalurl, e.externalurl_source) if e.externalurl_source == "ui_edit" or e.source != "notifier" else None,
                "widget": (e.widget.widget_name, e.widget.widget_url, tuple(e.widget.widget_fields)) if e.widget else None,
                "checks": sorted(json.dumps(c.to_config(), sort_keys=True) for c in e.checks),
            }
        out["entries"] = entries
        out["groups"] = {g.group_name: (g.group_sort_priority, g.group_icon) for g in Group.query.all()}
        out["channels"] = {c.name: (c.type, json.dumps(notify.validate_config(c.type, c.config)[0], sort_keys=True))
                           for c in NotificationChannel.query.all()}
        out["users"] = {u.username: (u.email, bool(u.is_admin), bool(u.is_active)) for u in User.query.all()}
        out["streams"] = {s.stream_id: (s.display_name, s.network_include, s.network_exclude, s.default_checks,
                                        s.expected_interval_seconds, s.missing_expiry_days)
                          for s in InventoryStream.query.all()}
        out["blocks"] = sorted((b.stream.stream_id, b.key) for b in InventoryBlock.query.all())
        out["settings"] = {
            "layers": settings_store.get_layer_directions(), "hosts": settings_store.get_host_layer_overrides(),
            "update": settings_store.get_update_check_settings(),
            "snapshot_time": settings_store.get_backup_value(settings_store.KEY_BACKUP_SNAPSHOT_TIME)}
    return out


def assert_same_state(a, b):
    """`a == b` with a readable list of the differing leaves."""
    diffs = []

    def walk(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                walk(x.get(k, "<absent>"), y.get(k, "<absent>"), f"{path}/{k}")
        elif x != y:
            diffs.append(f"{path}: {x!r} != {y!r}")

    walk(a, b, "")
    assert not diffs, "\n".join(diffs)


# --- the scenario ----------------------------------------------------------------------------------


def test_full_scenario_is_idempotent(app, client, register):
    seed_source(app, client, register)
    source = state(app)
    data = export_source(app)
    wipe(app)
    recreate_base(app, client, register)
    parsed = importer.parse(data, "2026-11-20-std_export.yml")
    assert not parsed.invalid and not parsed.warnings

    # 1. first import: the stream is pending, so its entries wait.
    p = do_plan(app, parsed)
    assert p.header["format_version"] == 1 and not p.header["legacy"]
    st = statuses(p)
    assert st["entry:docker:h1/grafana"] == MISSING
    assert st["entry:docker:h1/sonarr"] == MISSING
    assert st["entry:docker:h1/radarr"] == MISSING                  # the operator moved it to Home
    assert st["entry:docker:h1/plex"] == IDENTICAL
    assert st["entry:manual:/shelf"] == NOT_FOUND
    stream_rows = [r for r in p.rows if r.source_group == "stream:dhcp" and r.section == "entries"]
    assert len(stream_rows) == 8 and {r.status for r in stream_rows} == {WAITING}
    assert st["stream:dhcp"] == MISSING                              # filters, default checks, expiry
    assert st["block:dhcp/aa:bb:cc:00:00:0a"] == MISSING
    assert st["channel:home-broker"] == NOT_FOUND
    assert st["user:alice"] == st["user:bob"] == NOT_FOUND
    assert any("pending" in m["note"] for m in p.stream_mapping)
    assert p.stream_map == {"dhcp": "dhcp"}

    result, _ = do_apply(app, parsed)
    assert result.counts["channels_created"] == 1 and result.counts["users_created"] == 2
    assert result.still_to_do["users_without_password"] == ["alice", "bob"]
    assert result.still_to_do["channels_disabled"] == ["home-broker"]
    assert result.still_to_do["widgets_need_key"] == ["sonarr (http://sonarr:8989)"]
    assert result.still_to_do["streams_to_enable"] == ["dhcp"]
    with app.app_context():
        assert Widget.query.one().widget_api_key is None
        channel = NotificationChannel.query.one()
        assert channel.enabled is False and channel.secret is None

    # 2. enable the stream: the imported filters and blocks mean only wanted entries appear.
    _enable(app)
    with app.app_context():
        assert ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:0a").count() == 0   # blocked
        assert ServiceEntry.query.filter(ServiceEntry.stream_id.isnot(None)).count() == 8
    p2 = do_plan(app, parsed)
    st2 = statuses(p2)
    for key in ("01", "02", "07"):                                   # pump (check), kitchen (name, group), nas (name)
        assert st2[f"entry:stream:dhcp/aa:bb:cc:00:00:{key}"] == MISSING, key
    assert st2["entry:stream:dhcp/aa:bb:cc:00:00:03"] == IDENTICAL
    assert fields(row(p2, "entry:stream:dhcp/aa:bb:cc:00:00:07"))["name"].file == "nas"
    do_apply(app, parsed)

    # 3. everything operator-owned equals the source, and a re-plan has nothing left.
    assert_same_state(state(app), source)
    p3 = do_plan(app, parsed)
    assert {r.status for r in p3.rows} == {IDENTICAL}, {r.rid: (r.status, [f.field for f in r.fields]) for r in p3.rows if r.status != IDENTICAL}
    result3, _ = do_apply(app, parsed)
    assert result3.counts.get("rows_applied", 0) == 0
    assert_same_state(state(app), source)


def test_fill_missing_leaves_a_differing_value_and_overwrite_needs_the_box(app, register):
    register(host="h1", container_name="app", sort_priority=9)
    with app.app_context():
        e = ServiceEntry.query.one()
        e.description = "local text"
        e.sort_priority = 12            # the operator's own value, not what the notifier reported (9)
        db.session.commit()
    data = minimal(entries=[docker_rec("app", description="file text", sort_priority=3, ha_publish=True)])
    parsed = parse(data)
    p = do_plan(app, parsed)
    r = row(p, "entry:docker:h1/app")
    f = fields(r)
    assert f["ha_publish"].kind == MISSING
    assert f["description"].kind == DIFFERS and f["sort_priority"].kind == DIFFERS
    assert r.status == MISSING
    do_apply(app, parsed)                                           # fill
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.ha_publish is True and e.description == "local text" and e.sort_priority == 12
    # overwrite, with only the description box ticked
    sel = {"entry:docker:h1/app": {"apply": True, "fields": ["description"]}}
    result, _ = do_apply(app, parsed, sel, mode="overwrite")
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.description == "file text" and e.sort_priority == 12
    assert result.counts["fields_overwritten"] == 1
    # overwrite with no field list writes every actionable field
    do_apply(app, parsed, {"entry:docker:h1/app": {"apply": True}}, mode="overwrite")
    with app.app_context():
        assert ServiceEntry.query.one().sort_priority == 3
    # a fill-mode selection naming a differing field still does not write it
    do_apply(app, parsed, {"entry:docker:h1/app": {"apply": True, "fields": ["sort_priority"]}}, mode="fill")


def test_never_applied_fields_in_either_mode(app, register):
    with app.app_context():
        db.session.add(NotificationChannel(type="mqtt", name="b", enabled=True, secret="x",
                                           config={"host": "old.lan", "base_topic": "mine"}))
        db.session.add(User(username="alice", email="old@example.com", password_hash="h", is_admin=False,
                            is_active=True))
        db.session.commit()
    data = minimal(
        notification_channels=[{"name": "b", "type": "mqtt", "enabled": True, "secret_set": True,
                                "config": {"host": "new.lan", "base_topic": "theirs", "ha_prefix": "other",
                                           "ha_device_prefix": "dd"}}],
        users=[{"username": "alice", "email": "new@example.com", "is_admin": True, "is_active": False}])
    parsed = parse(data)
    for mode in ("fill", "overwrite"):
        do_apply(app, parsed, {"channel:b": {"apply": True}, "user:alice": {"apply": True}}, mode=mode,
                 stream_map=None)
        with app.app_context():
            channel = NotificationChannel.query.one()
            assert channel.config["base_topic"] == "mine"
            assert channel.config.get("ha_prefix") != "other" and channel.config.get("ha_device_prefix") != "dd"
            user = User.query.one()
            assert (user.email, user.is_admin, user.is_active) == ("old@example.com", False, True)
    p = do_plan(app, parsed)
    ch = fields(row(p, "channel:b"))
    assert not ch["config.base_topic"].applicable and "Notifications" in ch["config.base_topic"].note
    assert all(not f.applicable for f in row(p, "user:alice").fields)
    with app.app_context():
        assert NotificationChannel.query.one().config["host"] == "new.lan"      # a normal key, overwritten


def test_fresh_value_rules(app, register, client):
    register(host="h1", container_name="g", group_name="Media", sort_priority=5, internalurl="http://label",
             exposure_observations=[{"layer": "traefik", "hostname": "g.example.com", "tls": True}])
    with app.app_context():
        settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS, {"traefik": "external"})
        db.session.commit()
    register(host="h1", container_name="g")                         # recompute synthesized external URL
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.externalurl_source == "synthesized" and e.internalurl_source == "explicit_label"
    data = minimal(groups=[{"name": "Media"}, {"name": "Home"}], entries=[docker_rec(
        "g", group="Home", sort_priority=1,
        internalurl={"value": "http://typed", "source": "ui_edit"},
        externalurl={"value": "https://typed.example", "source": "ui_edit"})])
    parsed = parse(data)
    r = row(do_plan(app, parsed), "entry:docker:h1/g")
    f = fields(r)
    assert f["group"].kind == MISSING and f["group"].local == "Media"      # the notifier's own group
    assert f["sort_priority"].kind == MISSING
    assert f["internalurl"].kind == DIFFERS                                 # explicit label
    assert f["externalurl"].kind == MISSING                                 # synthesized
    do_apply(app, parsed)
    with app.app_context():
        e = ServiceEntry.query.one()
        assert (e.externalurl, e.externalurl_source) == ("https://typed.example", "ui_edit")
        assert e.internalurl == "http://label"
    # a later register with an explicit label does not overwrite the imported URL
    register(host="h1", container_name="g", externalurl="https://label.example")
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.externalurl == "https://typed.example"
        assert e.group.group_name == "Home" and e.sort_priority == 1


def test_notifier_wins_excludes_group_and_sort_priority(app, register, monkeypatch):
    register(host="h1", container_name="g")
    monkeypatch.setitem(app.config, "register_field_ownership", "notifier_wins")
    parsed = parse(minimal(groups=[{"name": "Home"}], entries=[docker_rec("g", group="Home", sort_priority=2,
                                                                           description="d")]))
    p = do_plan(app, parsed)
    r = row(p, "entry:docker:h1/g")
    assert set(fields(r)) == {"description"}
    assert any("notifier_wins" in n for n in r.notes) and any("notifier_wins" in w for w in p.warnings)
    do_apply(app, parsed)
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.group_id is None and e.sort_priority is None and e.description == "d"


def test_ambiguous_entry_and_group(app, register):
    register(host="h1", container_name="dup")
    with app.app_context():
        second = ServiceEntry(host="h1", container_name="dup", source="manual", last_updated=datetime.now())
        db.session.add(second)
        ensure_url_checks(second)
        db.session.add(Group(group_name="media"))
        db.session.commit()
        ids = sorted(e.id for e in ServiceEntry.query.all())
    parsed = parse(minimal(groups=[{"name": "Media", "sort_priority": 4}],
                           entries=[docker_rec("dup", description="picked")]))
    p = do_plan(app, parsed)
    r = row(p, "entry:docker:h1/dup")
    assert r.status == "ambiguous" and [c["id"] for c in r.candidates] == ids
    g = row(p, "group:Media")
    assert g.status == "ambiguous" and "close" in g.notes[0]
    # unpicked: nothing is written
    result, _ = do_apply(app, parsed, {r.rid: {"apply": True}, g.rid: {"apply": True}})
    assert result.skipped["needs a choice"] == 2
    with app.app_context():
        assert {e.description for e in ServiceEntry.query.all()} == {None}
    # a pick that is not a candidate is refused
    with pytest.raises(ImportApplyError):
        do_apply(app, parsed, {r.rid: {"apply": True, "target_id": 9999}})
    do_apply(app, parsed, {r.rid: {"apply": True, "target_id": ids[1]},
                           g.rid: {"apply": True, "target_id": row(p, "group:Media").candidates[0]["id"]}})
    with app.app_context():
        assert db.session.get(ServiceEntry, ids[1]).description == "picked"
        assert db.session.get(ServiceEntry, ids[0]).description is None
        assert Group.query.filter_by(group_name="media").one().group_sort_priority == 4
        assert Group.query.filter_by(group_name="Media").count() == 0
    # "create" makes the exact-case group instead
    do_apply(app, parsed, {g.rid: {"apply": True, "create": True}})
    with app.app_context():
        assert Group.query.filter_by(group_name="Media").one().group_sort_priority == 4


def test_soft_deleted_local_entry_is_restored_and_filled(app, register):
    register(host="h1", container_name="old")
    with app.app_context():
        e = ServiceEntry.query.one()
        e.deleted_at = datetime.now()
        db.session.commit()
    parsed = parse(minimal(entries=[docker_rec("old", description="back")]))
    p = do_plan(app, parsed)
    r = row(p, "entry:docker:h1/old")
    assert r.status == DELETED and r.options == ["restore"] and not r.default_selected
    result, _ = do_apply(app, parsed, {r.rid: {"apply": True}})                 # restore not ticked
    assert result.skipped["restore not ticked"] == 1
    with app.app_context():
        assert ServiceEntry.query.one().deleted_at is not None
    result, _ = do_apply(app, parsed, {r.rid: {"apply": True, "options": ["restore"]}})
    assert result.counts["entries_restored"] == 1
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.deleted_at is None and e.description == "back"


def test_restore_clash_with_an_active_twin_is_a_conflict(app):
    with app.app_context():
        deleted = ServiceEntry(host=None, container_name="x", source="manual", last_updated=datetime.now(),
                               deleted_at=datetime.now())
        db.session.add(deleted)
        db.session.commit()
    _put_stream_entry_named_x(app)
    parsed = parse(minimal(entries=[manual_rec("x", description="d")]))
    r = row(do_plan(app, parsed), "entry:manual:/x")
    assert r.status == "conflict" and "cannot be restored" in r.notes[0]
    result, _ = do_apply(app, parsed, {"entry:manual:/x": {"apply": True, "options": ["restore"]}})
    assert result.skipped["conflict"] == 1


def _put_stream_entry_named_x(app):
    """An active host-less stream entry called x (the twin a restore would clash with)."""
    with app.app_context():
        stream = InventoryStream(stream_id="s", display_name="S", producer="p", producer_version="1",
                                 key_type="mac", status="enabled")
        db.session.add(stream)
        db.session.flush()
        db.session.add(ServiceEntry(host=None, container_name="x", source="stream", stream_id=stream.id,
                                    stream_key="aa:aa:aa:aa:aa:aa", last_updated=datetime.now()))
        db.session.commit()


def test_import_as_new_docker_record_is_adopted_by_register(app, register):
    parsed = parse(minimal(
        groups=[{"name": "Media"}],
        entries=[docker_rec("late", group="Media", is_static=True, ha_publish=True,
                            checks=[{"kind": "container", "check_type": "docker", "mode": "status",
                                     "enabled": True}])]))
    p = do_plan(app, parsed)
    r = row(p, "entry:docker:h1/late")
    assert r.status == NOT_FOUND and r.can_create and any("lock" in n for n in r.notes)
    result, _ = do_apply(app, parsed)
    assert result.counts["entries_created"] == 1
    assert result.still_to_do["locks_deferred"] == ["h1/late"]
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="late").one()
        assert e.source == "manual" and e.is_static is False and e.ha_publish is True
        assert e.group.group_name == "Media" and e.container_check is None
    assert register(host="h1", container_name="late").status_code == 200
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="late").one()
        assert e.source == "notifier" and e.group.group_name == "Media" and e.container_check is not None
    p2 = do_plan(app, parsed)
    f = fields(row(p2, "entry:docker:h1/late"))
    assert f["is_static"].kind == MISSING and set(f) == {"is_static"}
    do_apply(app, parsed)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="late").one().is_static is True


def test_import_as_new_manual_refuses_a_duplicate(app):
    with app.app_context():
        db.session.add(ServiceEntry(host=None, container_name="dup", source="manual", last_updated=datetime.now()))
        db.session.commit()
    _put_stream_entry_named_x(app)
    parsed = parse(minimal(entries=[manual_rec("x"), manual_rec("fresh")]))
    st = statuses(do_plan(app, parsed))
    assert st["entry:manual:/x"] == "conflict" and st["entry:manual:/fresh"] == NOT_FOUND
    assert "duplicate" in row(do_plan(app, parsed), "entry:manual:/x").notes[0]


def test_import_as_new_stream_record_gets_a_link_offer(app, client):
    _put(client, app)
    _enable(app)
    # the record's key is in the snapshot but was never applied: use a fresh key
    rec = stream_rec("aa:bb:cc:00:00:55", "boiler", identity={"pre_link_host": "boiler-host"}, description="hot")
    parsed = parse(minimal(streams=[_stream_rec_for_dhcp()], entries=[rec]))
    p = do_plan(app, parsed)
    r = row(p, "entry:stream:dhcp/aa:bb:cc:00:00:55")
    assert r.status == NOT_FOUND and r.can_create
    do_apply(app, parsed, {r.rid: {"apply": True, "create": True}})
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="boiler").one()
        assert e.source == "manual" and e.host == "boiler-host" and e.description == "hot"
        assert e.stream_id is None
    # the sidecar now reports the device: its name matches, so an offer is made
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        item = {"key": "aa:bb:cc:00:00:55", "name": "boiler", "ip": "10.0.40.55", "mac": "aa:bb:cc:00:00:55",
                "network": "CrzyIoT", "attributes": None}
        streams.apply(stream, [item])
        offer = StreamLinkOffer.query.filter_by(key="aa:bb:cc:00:00:55").one()
        entry_id = offer.entry_id
        # while the offer is open, a re-plan matches the offered manual entry and does not accept it
        p2 = importer.plan(parsed)
        r2 = p2.row("entry:stream:dhcp/aa:bb:cc:00:00:55")
        assert r2.status == IDENTICAL and r2.target_id == entry_id
        assert any("link offer" in n for n in r2.notes)
        importer.apply(parsed, None, {}, "fill", importer.fingerprint(p2, {}), "t")
        assert StreamLinkOffer.query.filter_by(key="aa:bb:cc:00:00:55").count() == 1
        assert db.session.get(ServiceEntry, entry_id).source == "manual"
        streams.accept_offer(stream, StreamLinkOffer.query.filter_by(key="aa:bb:cc:00:00:55").one())
    p3 = do_plan(app, parsed)
    r3 = row(p3, "entry:stream:dhcp/aa:bb:cc:00:00:55")
    assert r3.status == IDENTICAL and r3.target_id == entry_id        # matched by (stream, key) now
    assert not any("not linked" in n for n in r3.notes)


def _stream_rec_for_dhcp(**fields):
    return {"stream_id": "dhcp", "key_type": "mac", "producer": "std-source-technitium", "display_name": "DHCP",
            "status": "enabled", **fields}


def test_a_renamed_stream_record_gets_no_offer(app, client):
    _put(client, app)
    _enable(app)
    rec = stream_rec("aa:bb:cc:00:00:56", "my-name", identity={"name_source": "ui_edit"})
    parsed = parse(minimal(streams=[_stream_rec_for_dhcp()], entries=[rec]))
    do_apply(app, parsed)
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        streams.apply(stream, [{"key": "aa:bb:cc:00:00:56", "name": "other-name", "ip": "10.0.0.56",
                                "mac": "aa:bb:cc:00:00:56", "network": "CrzyIoT", "attributes": None}])
        assert StreamLinkOffer.query.filter_by(key="aa:bb:cc:00:00:56").count() == 0     # documented limit


def test_stream_mapping_auto_remap_and_refusals(app, client):
    _put(client, app)
    _put(client, app, slug="other", key=_key(app, "k2", "ingest")[1])
    with app.app_context():
        hosts = InventoryStream(stream_id="hostnames", display_name="H", producer="p", producer_version="1",
                                key_type="hostname", status="enabled")
        db.session.add(hosts)
        db.session.commit()
    doc = minimal(streams=[_stream_rec_for_dhcp(missing_expiry_days=30),
                           {**_stream_rec_for_dhcp(stream_id="ghost", display_name="Ghost")}],
                  entries=[stream_rec(), stream_rec(stream="ghost", key="aa:aa:aa:aa:aa:aa", name="g")])
    parsed = parse(doc)
    p = do_plan(app, parsed)
    assert p.stream_map == {"dhcp": "dhcp", "ghost": None}
    ghost = next(m for m in p.stream_mapping if m["file_id"] == "ghost")
    assert "Not present yet" in ghost["note"]
    assert {o["id"] for o in ghost["options"]} == {"dhcp", "other"}      # same key type only
    assert row(p, "entry:stream:ghost/aa:aa:aa:aa:aa:aa").status == WAITING
    # a remap to another stream with the same key type
    p2 = do_plan(app, parsed, {"dhcp": "other"})
    assert p2.stream_map["dhcp"] == "other" and row(p2, "stream:dhcp").target_id is not None
    # a different key type is refused
    p3 = do_plan(app, parsed, {"dhcp": "hostnames"})
    assert p3.stream_map["dhcp"] is None and "same key type" in next(
        m for m in p3.stream_mapping if m["file_id"] == "dhcp")["error"]
    assert row(p3, "stream:dhcp").status == WAITING
    with pytest.raises(ImportApplyError, match="stream mapping"):
        do_apply(app, parsed, {}, stream_map={"dhcp": "hostnames"})
    # "skip" and two file streams on one local stream
    assert do_plan(app, parsed, {"dhcp": None}).stream_map["dhcp"] is None
    p4 = do_plan(app, parsed, {"dhcp": "other", "ghost": "other"})
    assert "once" in next(m for m in p4.stream_mapping if m["file_id"] == "ghost")["error"]


def test_stream_settings_and_blocks_apply_to_a_pending_stream(app, client):
    _put(client, app)
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        assert stream.status == "pending"
    rec = _stream_rec_for_dhcp(display_name="DHCP", network_exclude=["Guest"], default_checks={"ping": True},
                               expected_interval_seconds=300, missing_expiry_days=14,
                               blocks=[{"key": "aa:bb:cc:00:00:0a", "name": "no-network", "ip": "10.0.0.9",
                                        "blocked_by": "admin", "blocked_at": "2026-11-01T10:00:00Z"}])
    parsed = parse(minimal(streams=[rec]))
    p = do_plan(app, parsed)
    assert row(p, "stream:dhcp").status == MISSING and row(p, "block:dhcp/aa:bb:cc:00:00:0a").status == MISSING
    do_apply(app, parsed)
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        assert stream.status == "pending"                                        # never changed
        assert stream.network_exclude == ["Guest"] and stream.missing_expiry_days == 14
        assert stream.default_checks == {"ping": True, "tcp_port": None} and stream.expected_interval_seconds == 300
        block = InventoryBlock.query.one()
        assert (block.key, block.name, block.blocked_by) == ("aa:bb:cc:00:00:0a", "no-network", "admin")
        assert block.blocked_at == datetime(2026, 11, 1, 10, 0)
        assert InventoryStream.query.count() == 1                                # never creates a stream
    p2 = do_plan(app, parsed)
    assert {r.status for r in p2.rows} == {IDENTICAL}


def test_block_for_an_existing_entry_with_soft_delete_option(app, client):
    _put(client, app)
    _enable(app)
    key = "aa:bb:cc:00:00:03"
    parsed = parse(minimal(streams=[_stream_rec_for_dhcp(blocks=[{"key": key, "name": "tv-lounge"}])]))
    r = row(do_plan(app, parsed), f"block:dhcp/{key}")
    assert r.options == ["soft_delete_entry"] and "already exists" in r.notes[0]
    do_apply(app, parsed, {r.rid: {"apply": True}})                              # block only: the entry stays
    with app.app_context():
        assert InventoryBlock.query.count() == 1
        assert ServiceEntry.query.filter_by(stream_key=key).one().deleted_at is None
        InventoryBlock.query.delete()
        db.session.commit()
    result, _ = do_apply(app, parsed, {r.rid: {"apply": True, "options": ["soft_delete_entry"]}})
    assert result.counts["entries_soft_deleted"] == 1
    with app.app_context():
        assert ServiceEntry.query.filter_by(stream_key=key).one().deleted_at is not None
        assert InventoryBlock.query.filter_by(key=key).count() == 1


def test_users_are_created_without_a_usable_password(app, client):
    parsed = parse(minimal(users=[{"username": "carol", "email": "carol@example.com", "is_admin": True,
                                   "is_active": True}]))
    do_apply(app, parsed)
    with app.app_context():
        user = User.query.one()
        assert user.password_hash == "!unset" and user.has_password is False
        assert user.is_admin and user.is_active and user.password_changed_at is None
        for attempt in ("", "!unset", "password", "carol", "x" * 80, "pbkdf2:sha256:1$a$b"):
            assert user.check_password(attempt) is False
    for attempt in ("", "!unset", "carol"):
        resp = client.post("/login", data={"username": "carol", "password": attempt})
        assert resp.status_code == 200                                           # re-rendered, no redirect
    with app.app_context():
        user = User.query.one()
        user.set_password("a-real-password")
        assert user.has_password


def test_an_email_in_use_is_a_conflict_and_existing_users_are_untouched(app):
    with app.app_context():
        u = User(username="dave", email="dave@example.com", password_hash="h", is_admin=False, is_active=True)
        db.session.add(u)
        db.session.commit()
    parsed = parse(minimal(users=[{"username": "eve", "email": "DAVE@example.com"},
                                  {"username": "dave", "email": "other@example.com", "is_admin": True}]))
    p = do_plan(app, parsed)
    assert row(p, "user:eve").status == "conflict" and "dave" in row(p, "user:eve").notes[0]
    assert row(p, "user:dave").status == DIFFERS
    do_apply(app, parsed, {"user:eve": {"apply": True, "create": True}, "user:dave": {"apply": True}},
             mode="overwrite")
    with app.app_context():
        assert User.query.count() == 1
        assert User.query.one().email == "dave@example.com" and User.query.one().is_admin is False


def test_channels_are_created_disabled_without_their_secret(app):
    parsed = parse(minimal(notification_channels=[
        {"name": "withpw", "type": "mqtt", "enabled": True, "secret_set": True,
         "config": {"host": "m.lan", "username": "u", "base_topic": "x"}},
        {"name": "nopw", "type": "mqtt", "enabled": True, "secret_set": False, "config": {"host": "n.lan"}},
        {"name": "bad", "type": "mqtt", "enabled": True, "config": {"host": "x", "port": "nope"}},
        {"name": "weird", "type": "carrier-pigeon", "enabled": True}]))
    assert {i["label"] for i in parsed.invalid} == {"bad", "weird"}
    p = do_plan(app, parsed)
    assert {r.rid for r in p.rows if r.status == "invalid"} == {
        "invalid:notification_channels/2", "invalid:notification_channels/3"}
    do_apply(app, parsed)
    with app.app_context():
        by = {c.name: c for c in NotificationChannel.query.all()}
        assert by["withpw"].enabled is False and by["withpw"].secret is None
        assert by["withpw"].config["base_topic"] == "x"
        assert by["nopw"].enabled is True and by["nopw"].secret is None
    # an unknown type is invalid at parse time, so a type clash can only come from a known type
    p2 = do_plan(app, parse(minimal(notification_channels=[{"name": "nopw", "type": "webhook"}])))
    assert [r.status for r in p2.rows] == ["invalid"]


def test_a_stale_plan_writes_nothing(app, register):
    register(host="h1", container_name="a")
    parsed = parse(minimal(entries=[docker_rec("a", description="x"), docker_rec("b", description="y")]))
    with app.app_context():
        p = importer.plan(parsed)
        sel = {"entry:docker:h1/a": {"apply": True}}
        fp = importer.fingerprint(p, sel)
    with app.app_context():
        e = ServiceEntry.query.one()
        e.description = "changed meanwhile"
        db.session.commit()
    with app.app_context():
        with pytest.raises(ImportStale) as exc:
            importer.apply(parsed, None, sel, "fill", fp, "t")
        assert "description" in fields(exc.value.plan.row("entry:docker:h1/a"))      # the fresh plan
        assert ServiceEntry.query.one().description == "changed meanwhile"
    # a register that turns a not-found row into a match makes a selected create stale
    with app.app_context():
        sel_b = {"entry:docker:h1/b": {"apply": True, "create": True}}
        fp_b = importer.fingerprint(importer.plan(parsed), sel_b)
    register(host="h1", container_name="b")
    with app.app_context():
        with pytest.raises(ImportStale):
            importer.apply(parsed, None, sel_b, "fill", fp_b, "t")
        assert ServiceEntry.query.filter_by(container_name="b").one().description is None
        assert ServiceEntry.query.filter_by(container_name="b").count() == 1


def test_observed_changes_do_not_make_a_plan_stale(app, register):
    register(host="h1", container_name="a", docker_status="running")
    parsed = parse(minimal(entries=[docker_rec("a", description="x")]))
    with app.app_context():
        sel = {"entry:docker:h1/a": {"apply": True}}
        fp = importer.fingerprint(importer.plan(parsed), sel)
    register(host="h1", container_name="a", docker_status="exited", networks=[{"name": "n", "aliases": []}])
    with app.app_context():
        result = importer.apply(parsed, None, sel, "fill", fp, "t")
        assert result.counts["rows_applied"] == 1
    # an unselected row changing is not stale either
    with app.app_context():
        e = ServiceEntry.query.one()
        e.description = None
        db.session.commit()
    parsed2 = parse(minimal(entries=[docker_rec("a", description="x"), docker_rec("zzz", description="q")]))
    with app.app_context():
        sel2 = {"entry:docker:h1/a": {"apply": True}}
        fp2 = importer.fingerprint(importer.plan(parsed2), sel2)
    register(host="h1", container_name="zzz")
    with app.app_context():
        importer.apply(parsed2, None, sel2, "fill", fp2, "t")


def test_fingerprint_helpers(app, register):
    register(host="h1", container_name="a")
    parsed = parse(minimal(entries=[docker_rec("a", description="x")]))
    p = do_plan(app, parsed)
    assert p.fingerprint == importer.fingerprint(p, p.default_selection())
    sel = {"entry:docker:h1/a": {"apply": True}}
    assert importer.fingerprint_from_digests(p.digests, sel, p.stream_map) == importer.fingerprint(p, sel)
    assert importer.fingerprint(p, {}) != importer.fingerprint(p, sel)
    assert do_plan(app, parsed).digests == p.digests                         # deterministic
    with app.app_context():
        with pytest.raises(ImportApplyError, match="fingerprint"):
            importer.apply(parsed, None, sel, "fill", "", "t")
        with pytest.raises(ImportApplyError, match="mode"):
            importer.apply(parsed, None, sel, "mirror", "x", "t")


def test_a_failure_mid_apply_writes_nothing(app, register, monkeypatch):
    register(host="h1", container_name="a")
    parsed = parse(minimal(groups=[{"name": "NewGroup"}], notification_channels=[
        {"name": "c", "type": "mqtt", "config": {"host": "h"}}], entries=[docker_rec("a", description="x")]))

    def boom(self, row, sel):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(importer._Applier, "_apply_entries", boom)
    with pytest.raises(ImportApplyError, match="Nothing was changed") as info:
        do_apply(app, parsed)
    # The raw exception text stays in the server log, never in the message a client sees.
    assert "disk on fire" not in str(info.value)
    with app.app_context():
        assert Group.query.count() == 0 and NotificationChannel.query.count() == 0
        assert ServiceEntry.query.one().description is None


def test_plan_is_pure_and_opens_no_lock(app, register, monkeypatch):
    import routes_api

    register(host="h1", container_name="a")
    parsed = parse(minimal(groups=[{"name": "G"}], entries=[docker_rec("a", description="x", group="G")]))

    class Boom:
        def __enter__(self):
            raise AssertionError("plan took a lock")

        __exit__ = acquire = release = lambda *a, **k: (_ for _ in ()).throw(AssertionError("plan took a lock"))

    monkeypatch.setattr(routes_api, "_UPSERT_LOCK", Boom())
    monkeypatch.setattr(streams, "_LOCK", Boom())
    with app.app_context():
        before = [(e.id, e.description) for e in ServiceEntry.query.all()]
        importer.plan(parsed)
        assert not db.session.new and not db.session.dirty and not db.session.deleted
        assert Group.query.count() == 0
        assert before == [(e.id, e.description) for e in ServiceEntry.query.all()]


def test_apply_takes_the_locks_in_order(app, register, monkeypatch):
    import routes_api

    log = []

    class Spy:
        def __init__(self, name, real):
            self.name, self.real = name, real

        def __enter__(self):
            log.append(("in", self.name))
            self.real.acquire()

        def __exit__(self, *a):
            self.real.release()
            log.append(("out", self.name))

    register(host="h1", container_name="a")
    monkeypatch.setattr(routes_api, "_UPSERT_LOCK", Spy("upsert", routes_api._UPSERT_LOCK))
    monkeypatch.setattr(streams, "_LOCK", Spy("streams", streams._LOCK))
    do_apply(app, parse(minimal(entries=[docker_rec("a", description="x")])))
    assert log == [("in", "upsert"), ("in", "streams"), ("out", "streams"), ("out", "upsert")]


def test_settings_rows_apply_and_reschedule(app, monkeypatch):
    import jobs

    calls = []
    monkeypatch.setattr(jobs, "reschedule_backups", lambda a, scheduler=None: calls.append(a))
    parsed = parse(minimal(settings={
        "exposure_layers": {"traefik": "internal", "dockflare": "neither"},
        "exposure_layers_per_host": {"h2": {"traefik": "external"}},
        "update_check": {"enabled": False, "interval_hours": 12},
        "backup": {"snapshot": {"enabled": False, "time": "03:30", "keep_days": 30},
                   "export": {"format": "json", "time": "99:99"}}}))
    p = do_plan(app, parsed)
    assert row(p, "setting:exposure_layers/dockflare").status == IDENTICAL      # absent == neither
    assert row(p, "setting:exposure_layers/traefik").status == MISSING
    assert any("not a time" in n for n in row(p, "setting:backup/export").notes)
    do_apply(app, parsed)
    with app.app_context():
        assert settings_store.get_layer_directions() == {"traefik": "internal"}
        assert settings_store.get_host_layer_overrides() == {"h2": {"traefik": "external"}}
        assert settings_store.get_update_check_settings() == (False, 12)
        eff = backups.effective_settings(app)
        assert eff["snapshot"]["time"]["value"] == "03:30" and eff["snapshot"]["enabled"]["value"] is False
        assert eff["snapshot"]["keep_days"]["value"] == 30 and eff["export"]["format"]["value"] == "json"
        assert eff["export"]["time"]["value"] == "00:10"
        assert settings_store.get_backup_value(settings_store.KEY_BACKUP_PATH) is None      # never the path
    assert len(calls) == 1
    assert {r.status for r in do_plan(app, parsed).rows} == {IDENTICAL}


def test_settings_set_by_environment_are_not_imported(app, monkeypatch):
    monkeypatch.setitem(app.config, "CONFIG_FROM_ENV", {"backup_days_to_keep": "5"})
    monkeypatch.setitem(app.config, "backup_days_to_keep", 5)
    parsed = parse(minimal(settings={"backup": {"snapshot": {"keep_days": 30}}}))
    r = row(do_plan(app, parsed), "setting:backup/snapshot")
    assert r.status == IDENTICAL and "environment" in r.notes[0]


def test_checks_by_kind_and_service_identity(app, register):
    register(host="h1", container_name="c")
    with app.app_context():
        e = ServiceEntry.query.one()
        for name, target in (("Web", "10.0.0.1:80"), ("Web", "10.0.0.2:80")):
            values, _ = validate_service_check({"name": name, "check_type": "tcp", "target": target})
            e.checks.append(new_service_check(values))
        values, _ = validate_service_check({"name": "Solo", "check_type": "tcp", "target": "10.0.0.3:80"})
        e.checks.append(new_service_check(values))
        db.session.commit()
    svc = {"kind": "service", "check_type": "tcp", "mode": "status", "enabled": False}
    parsed = parse(minimal(entries=[docker_rec("c", checks=[
        {"kind": "external_url", "check_type": "http", "mode": "status", "enabled": True, "interval_seconds": 90},
        {**svc, "name": "Web", "target": "10.0.0.9:80"},                 # shared identity: differs, never filled
        {**svc, "name": "Solo", "target": "10.0.0.4:80"},                # one local: differs
        {**svc, "name": "New", "target": "10.0.0.5:80"},                 # none local: missing
        {"kind": "container", "check_type": "docker", "mode": "status", "enabled": False, "interval_seconds": 60},
    ])]))
    r = row(do_plan(app, parsed), "entry:docker:h1/c")
    f = fields(r)
    assert f["check:external_url"].kind == MISSING
    assert f["check:service:tcp:Web"].kind == DIFFERS and not f["check:service:tcp:Web"].applicable
    assert f["check:service:tcp:Solo"].kind == DIFFERS
    assert f["check:service:tcp:New"].kind == MISSING
    assert f["check:container"].kind == MISSING                         # still at its fresh value
    do_apply(app, parsed, mode="overwrite")
    with app.app_context():
        e = ServiceEntry.query.one()
        assert e.url_check("external").enabled and e.url_check("external").interval_seconds == 90
        by = {(c.name, c.target) for c in e.service_checks}
        assert ("Solo", "10.0.0.4:80") in by and ("New", "10.0.0.5:80") in by
        assert ("Web", "10.0.0.1:80") in by and ("Web", "10.0.0.2:80") in by      # never written
        assert e.container_check.enabled is False and e.container_check.interval_seconds == 60


def test_widget_matching_and_creation(app, register):
    register(host="h1", container_name="w")
    register(host="h1", container_name="w3")
    with app.app_context():
        db.session.add(Widget(widget_name="sonarr", widget_url="http://s", widget_fields=[], widget_api_key="keep"))
        db.session.commit()
    doc = minimal(widgets=[{"widget_name": "sonarr", "widget_url": "http://s", "widget_fields": ["queue"],
                            "api_key_set": True},
                           {"widget_name": "radarr", "widget_url": "http://r", "widget_fields": ["q"],
                            "api_key_set": True}],
                  entries=[docker_rec("w", widget={"widget_name": "sonarr", "widget_url": "http://s"}),
                           docker_rec("w2", widget={"widget_name": "radarr", "widget_url": "http://r"}),
                           docker_rec("w3", widget={"widget_name": "ghost", "widget_url": "http://g"})])
    parsed = parse(doc)
    p = do_plan(app, parsed)
    assert fields(row(p, "entry:docker:h1/w"))["widget"].kind == MISSING
    assert any("not in the file" in n for n in row(p, "entry:docker:h1/w3").notes)
    result, _ = do_apply(app, parsed, {"entry:docker:h1/w": {"apply": True},
                                       "entry:docker:h1/w2": {"apply": True, "create": True}})
    with app.app_context():
        sonarr = Widget.query.filter_by(widget_name="sonarr").one()
        assert sonarr.widget_api_key == "keep" and sonarr.widget_fields == ["queue"]
        radarr = Widget.query.filter_by(widget_name="radarr").one()
        assert radarr.widget_api_key is None and radarr.widget_fields == ["q"]
        assert ServiceEntry.query.filter_by(container_name="w2").one().widget_id == radarr.id
    assert result.still_to_do["widgets_need_key"] == ["radarr (http://r)"]


# --- parsing ---------------------------------------------------------------------------------------


def test_parse_json_yaml_and_unknown_keys(app):
    data = minimal(entries=[docker_rec("a", future_field=1), docker_rec("b", future_field=2)], future_top=1)
    as_json = json.dumps(data)
    as_yaml = export_format.yaml.safe_dump(data)
    for raw, name in ((as_json, "x.json"), (as_yaml, "x.yml"), (as_json, "noext"), (as_yaml, "x.json.bak")):
        parsed = importer.parse(raw.encode(), name)
        assert len(parsed.doc.entries) == 2 and not parsed.legacy
        assert any("`entries[].future_field` (2x)" in w and "future_top" in w for w in parsed.warnings)
    # unknown fields are not applied
    assert do_plan(app, importer.parse(as_json.encode(), "x.json")).warnings       # shown in the plan too


def test_parse_limits_and_header_errors():
    with pytest.raises(ImportParseError, match="10 MB"):
        importer.parse(b"x" * (importer.MAX_UPLOAD_BYTES + 1), "big.yml")
    with pytest.raises(ImportParseError, match="anchors"):
        importer.parse(b"format: std-export\nformat_version: 1\nentries: &a []\nusers: *a\n", "x.yml")
    with pytest.raises(ImportParseError, match="anchors"):
        importer.parse(b"- &a {container_name: x}\n- *a\n", "x.yml")
    with pytest.raises(ImportParseError, match="format 2.*reads up to format 1.*Upgrade STD first"):
        parse(minimal(format_version=2, std_version="0.13.0"))
    with pytest.raises(ImportParseError, match="not an STD export"):
        parse({"hello": "world"})
    with pytest.raises(ImportParseError, match="not an STD export"):
        importer.parse(b"just a string", "x.yml")
    with pytest.raises(ImportParseError, match="header"):
        parse({"format": "std-export", "format_version": 1})
    with pytest.raises(ImportParseError, match="valid JSON"):
        importer.parse(b"{not json", "x.json")
    with pytest.raises(ImportParseError, match="UTF-8"):
        importer.parse(b"\xff\xfe\x00", "x.yml")
    with pytest.raises(ImportParseError, match="format_version"):
        parse(minimal(format_version="one"))


def test_record_caps():
    many = minimal(entries=[manual_rec(f"n{i}") for i in range(importer.MAX_ENTRY_RECORDS + 1)])
    with pytest.raises(ImportParseError, match="more than 20000"):
        parse(many)
    blocks = [{"key": f"k{i}"} for i in range(importer.MAX_BLOCKS_PER_STREAM + 1)]
    with pytest.raises(ImportParseError, match="blocks"):
        parse(minimal(streams=[_stream_rec_for_dhcp(blocks=blocks)]))
    ok = parse(minimal(entries=[manual_rec(f"n{i}") for i in range(importer.MAX_ENTRY_RECORDS)]))
    assert len(ok.doc.entries) == importer.MAX_ENTRY_RECORDS


def test_a_bad_record_is_an_invalid_row_not_a_failed_file(app):
    long_name = "x" * 200
    doc = minimal(
        entries=[docker_rec("good", description="d"),
                 {"kind": "docker", "identity": {"container_name": "nohost"}},
                 {"kind": "stream", "identity": {"container_name": "s"}},
                 {"kind": "stream", "identity": {"container_name": "s", "host": "h", "stream": "d",
                                                 "stream_key": "k"}},
                 manual_rec(long_name),
                 manual_rec("dupe"), manual_rec("dupe"),
                 {"kind": "weird", "identity": {"container_name": "w"}},
                 manual_rec("badcheck", checks=[{"kind": "service", "check_type": "tcp", "mode": "status",
                                                 "target": "no port", "name": "T"}]),
                 manual_rec("badicon", image_icon="../../etc/passwd")],
        groups=[{"name": ""}], users=[{"username": "u"}])
    parsed = parse(doc)
    assert [e.identity.container_name for e in parsed.doc.entries] == ["good", "dupe"]
    assert len(parsed.invalid) == 10          # 8 bad entries (one is the second dupe), an empty group name, a bad user
    labels = {i["label"] for i in parsed.invalid}
    assert {"nohost", "s", "badcheck", "badicon", "w"} <= labels
    p = do_plan(app, parsed)
    invalid = [r for r in p.rows if r.status == "invalid"]
    assert len(invalid) == len(parsed.invalid) and all(r.notes for r in invalid)
    assert p.counts["by_status"]["invalid"] == len(invalid)
    result, _ = do_apply(app, parsed)
    with app.app_context():
        assert {e.container_name for e in ServiceEntry.query.all()} == {"good", "dupe"}   # the valid ones only
    assert result.skipped.get("invalid", 0) == 0                          # an invalid row is never selected
    result2, _ = do_apply(app, parsed, {invalid[0].rid: {"apply": True}})
    assert result2.skipped["invalid"] == 1


# --- legacy (format 0) --------------------------------------------------------------------------


def test_legacy_lists_in_both_shapes(app, client, register):
    seed_source(app, client, register)
    with app.app_context():
        records = [e.to_dict() for e in ServiceEntry.query.all()]        # the scheduled daily format
        ui_records = [{**e.to_dict(), "group_name": e.group.group_name if e.group else None}
                      for e in ServiceEntry.query.all()]                 # the UI backup (adds group_name)
    legacy_json = json.dumps(records).encode()
    wipe(app)
    recreate_base(app, client, register)
    parsed = importer.parse(legacy_json, "2026-11-19-std_backup.yml")
    assert parsed.legacy and parsed.doc.format_version == 0
    assert export_format.LEGACY_NO_GROUPS_WARNING in parsed.warnings
    assert export_format.LEGACY_KEY_WARNING in parsed.warnings        # sonarr's key was in the file
    assert "widget-SECRET-key" not in json.dumps(parsed.to_dict())              # ignored, never in the document
    p = do_plan(app, parsed)
    assert p.header["legacy"] is True
    st = statuses(p)
    assert st["entry:docker:h1/sonarr"] == MISSING
    assert st["entry:docker:h1/plex"] == IDENTICAL
    trashed = row(p, "entry:docker:h1/trashed")
    assert trashed.status == NOT_FOUND and trashed.default_selected is False
    assert any("Deleted in the file" in n for n in trashed.notes)
    assert st["entry:manual:/shelf"] == NOT_FOUND
    legacy_streams = [r for r in p.rows if r.rid.startswith("entry:stream:-/")]
    assert len(legacy_streams) == 8                           # the dhcp devices, nas among them (no stream id)
    # the stream is pending: they fall back to manual; the two "dup-name" devices cannot both be created
    assert sorted(r.status for r in legacy_streams) == ["conflict"] + [NOT_FOUND] * 7
    assert {r.source_group for r in legacy_streams} == {"manual"}
    # the UI shape: it carries the groups, so the daily-job warning is gone and a moved group is missing
    ui = importer.parse(json.dumps(ui_records).encode(), "service_backup_all.yaml")
    assert export_format.LEGACY_NO_GROUPS_WARNING not in ui.warnings
    assert {g.name for g in ui.doc.groups} == {"Monitoring", "Media", "Home", "IoT"}
    p_ui = do_plan(app, ui)
    assert statuses(p_ui)["entry:docker:h1/radarr"] == MISSING
    assert fields(row(p_ui, "entry:docker:h1/radarr"))["group"].file == "Home"
    assert statuses(p)["entry:docker:h1/radarr"] == IDENTICAL                    # the daily shape has no groups
    do_apply(app, ui)
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="radarr").one().group.group_name == "Home"


def test_legacy_stream_record_matches_by_mac(app, client):
    _put(client, app)
    _enable(app)
    with app.app_context():
        e = ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:01").one()
        e.description = None
        db.session.commit()
    records = [{"container_name": "shelly-pump", "host": None, "source": "stream", "mac": "AA-BB-CC-00-00-01",
                "description": "boiler room", "ha_publish": True, "group_name": "IoT"}]
    parsed = importer.parse(json.dumps(records).encode(), "backup.yml")
    p = do_plan(app, parsed)
    r = row(p, "entry:stream:-/aa:bb:cc:00:00:01")
    assert r.status == MISSING and {f.field for f in r.fields} >= {"description", "ha_publish", "group"}
    do_apply(app, parsed)
    with app.app_context():
        e = ServiceEntry.query.filter_by(stream_key="aa:bb:cc:00:00:01").one()
        assert e.description == "boiler room" and e.ha_publish and e.group.group_name == "IoT"
    # no mac stream has the key: it falls back to the manual identity
    records = [{"container_name": "ghost", "host": None, "source": "stream", "mac": "aa:aa:aa:aa:aa:aa"}]
    p2 = do_plan(app, importer.parse(json.dumps(records).encode(), "b.yml"))
    r2 = row(p2, "entry:stream:-/aa:aa:aa:aa:aa:aa")
    assert r2.status == NOT_FOUND and r2.source_group == "manual" and r2.can_create
    # two mac streams with the same key: ambiguous
    _put(client, app, slug="dhcp2", key=_key(app, "k9", "ingest")[1])
    _enable(app, "dhcp2")
    p3 = do_plan(app, parsed)
    r3 = row(p3, "entry:stream:-/aa:bb:cc:00:00:01")
    assert r3.status == "ambiguous" and len(r3.candidates) == 2


def test_legacy_fields_and_pre_07_checks(app, register):
    register(host="h1", container_name="old", docker_status="running")
    records = [
        {"container_name": "old", "host": "h1", "last_api_update": "2026-01-01 00:00:00",
         "internalurl": "http://typed", "internalurl_source": "ui_edit",
         "externalurl": "https://label", "externalurl_source": "explicit_label",
         "internal_health_check_enabled": True, "external_health_check_enabled": False,
         "health_check_timeout": 7, "health_check_verify_tls": False, "is_static": False,
         "description": "legacy", "image_icon": "ignored-for-unlocked", "docker_status": "exited",
         "networks": [{"name": "x"}], "ip": "1.2.3.4"},
        {"container_name": "hand-made", "host": None, "internalurl": "http://m", "image_icon": "m"},
        {"container_name": "no-source-key", "host": "h1", "last_api_update": "2026-01-01 00:00:00",
         "internalurl": "http://pre06"},
        "not a record", {"host": "h1"},
    ]
    parsed = importer.parse(json.dumps(records).encode(), "b.yml")
    assert len(parsed.invalid) == 2
    rec = {e.identity.container_name: e for e in parsed.doc.entries}
    old = rec["old"]
    assert old.kind == "docker" and old.internalurl.value == "http://typed" and old.externalurl is None
    assert old.image_icon is None
    by_kind = {c.kind: c for c in old.checks}
    assert by_kind["internal_url"].enabled and by_kind["internal_url"].timeout_seconds == 7
    assert by_kind["internal_url"].verify_tls is False and not by_kind["external_url"].enabled
    assert rec["hand-made"].kind == "manual" and rec["hand-made"].internalurl.value == "http://m"
    assert rec["hand-made"].image_icon == "m"
    assert rec["no-source-key"].internalurl.value == "http://pre06" and rec["no-source-key"].internalurl.source is None
    do_apply(app, parsed)
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="old").one()
        assert e.description == "legacy" and (e.internalurl, e.internalurl_source) == ("http://typed", "ui_edit")
        assert e.url_check("internal").enabled and e.url_check("internal").timeout_seconds == 7
        assert e.url_check("internal").verify_tls is False
        assert e.docker_status == "running"                              # observation is ignored


# --- staging -----------------------------------------------------------------------------------


def test_staging_store(app):
    parsed = parse(minimal(entries=[docker_rec("a")]), "up.json")
    token = importer.stage(parsed, user_id=7)
    path = Path(importer.staging_dir()) / f"{token}.json"
    assert path.is_file() and oct(path.stat().st_mode)[-3:] == "600"
    loaded = importer.load(token, 7)
    assert loaded.doc == parsed.doc and loaded.filename == "up.json"
    assert importer.load(token, 8) is None                                # bound to the user
    assert importer.load("../../etc/passwd", 7) is None and importer.load("short", 7) is None
    assert importer.load(token, 7, now=time.time() + importer.STAGING_TTL_SECONDS + 5) is None
    assert not path.exists()                                              # an expired file is deleted
    t2 = importer.stage(parsed, 7)
    importer.discard(t2)
    assert importer.load(t2, 7) is None
    importer.discard(t2)                                                  # a second discard is harmless


def test_prune_expired_and_the_backup_job_calls_it(app):
    parsed = parse(minimal(entries=[docker_rec("a")]))
    old, fresh = importer.stage(parsed, 1), importer.stage(parsed, 1)
    old_path = Path(importer.staging_dir()) / f"{old}.json"
    stale = time.time() - importer.STAGING_TTL_SECONDS - 60
    os.utime(old_path, (stale, stale))
    assert importer.prune_expired() == 1
    assert not old_path.exists() and importer.load(fresh, 1) is not None
    os.utime(Path(importer.staging_dir()) / f"{fresh}.json", (stale, stale))
    with app.app_context():
        result = backups.run_snapshot(app, "manual")
        assert result["ok"], result
    assert not (Path(importer.staging_dir()) / f"{fresh}.json").exists()


# --- misc --------------------------------------------------------------------------------------


def test_the_plan_serialises(app, register):
    register(host="h1", container_name="a")
    parsed = parse(minimal(entries=[docker_rec("a", description="x")]))
    p = do_plan(app, parsed)
    data = json.loads(json.dumps(p.to_dict()))
    assert data["rows"][0]["status"] == MISSING and data["fingerprint"] == p.fingerprint
    result, _ = do_apply(app, parsed)
    assert json.loads(json.dumps(result.to_dict()))["counts"]["rows_applied"] == 1


def test_apply_logs_one_info_line(app, register, caplog):
    import logging

    register(host="h1", container_name="a")
    parsed = parse(minimal(entries=[docker_rec("a", description="x")]), "mine.yml")
    with caplog.at_level(logging.INFO, logger="importer"):
        do_apply(app, parsed)
    lines = [r for r in caplog.records if r.name == "importer" and r.levelno == logging.INFO]
    assert len(lines) == 1 and "tester" in lines[0].getMessage() and "rows_applied" in lines[0].getMessage()


def test_import_never_writes_a_secret(app, client, register):
    seed_source(app, client, register)
    data = export_source(app)
    wipe(app)
    recreate_base(app, client, register)
    do_apply(app, importer.parse(data, "x.yml"))
    with app.app_context():
        assert ApiKey.query.filter(ApiKey.name == "agent").count() == 0
        assert User.query.filter(User.password_hash != "!unset").count() == 0
        assert all(c.secret is None for c in NotificationChannel.query.all())
        assert all(w.widget_api_key is None for w in Widget.query.all())


def test_staging_path_stays_inside_the_staging_folder():
    assert importer._staging_path("../../etc/passwd") is None
    assert importer._staging_path("a" * 15) is None
    path = importer._staging_path("A" * 20)
    assert path.startswith(os.path.realpath(importer.staging_dir()) + os.sep)
