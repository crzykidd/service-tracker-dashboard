"""Export format v1: ownership rules, no secrets, round trip, determinism, and the UI
download (backup phase 2, design 5 and 8)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import api_keys
import export_format
import settings_store
from export_format import ExportDoc
from extensions import db
from models import (
    ApiKey,
    Group,
    InventoryBlock,
    InventoryStream,
    NotificationChannel,
    ServiceEntry,
    User,
    Widget,
    ensure_url_checks,
)
from tests.test_mgmt_api_keys import _bearer, _key

MQTT_PASSWORD = "mqtt-pw-SECRET-123"
USER_PASSWORD = "user-pw-SECRET-456"
WIDGET_KEY = "widget-key-SECRET-789"
FIXTURE = Path(__file__).parent / "fixtures" / "stream_snapshot.json"
TRAEFIK = {"layer": "traefik", "hostname": "grafana.example.com", "tls": True}


@pytest.fixture
def seeded(app, client, register):
    """A database that exercises every ownership row. Returns the secrets that were seeded."""
    with app.app_context():
        settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS, {"traefik": "external"})
        settings_store._set_value(settings_store.KEY_EXPOSURE_LAYERS_PER_HOST, {"h2": {"traefik": "internal"}})
        db.session.commit()
    # An unlocked Docker entry: its icon, label URL and synthesized URL are all rebuilt by register.
    assert register(host="h1", container_name="grafana", group_name="Monitoring", sort_priority=5,
                    image_icon="grafana", internalurl="http://grafana:3000",
                    docker_status="running", networks=[{"name": "bridge", "aliases": []}],
                    exposed_ports=["3000/tcp"], exposure_observations=[TRAEFIK]).status_code == 200
    assert register(host="h1", container_name="sonarr", image_icon="sonarr").status_code == 200
    assert register(host="h1", container_name="trashed").status_code == 200
    with app.app_context():
        sonarr = ServiceEntry.query.filter_by(container_name="sonarr").one()
        sonarr.is_static = True                      # locked: its icon is operator state
        sonarr.externalurl, sonarr.externalurl_source = "https://sonarr.example", "ui_edit"
        sonarr.ha_publish = True
        sonarr.description = "TV"
        widget = Widget(widget_name="sonarr", widget_url="http://sonarr:8989", widget_fields=["queue"],
                        widget_api_key=WIDGET_KEY)
        db.session.add(widget)
        sonarr.widget = widget
        grafana = ServiceEntry.query.filter_by(container_name="grafana").one()
        assert grafana.externalurl_source == "synthesized" and grafana.internalurl_source == "explicit_label"
        ServiceEntry.query.filter_by(container_name="trashed").one().deleted_at = datetime.now()
        media = Group(group_name="Media", group_sort_priority=10, group_icon="mdi-play")
        db.session.add(media)
        manual = ServiceEntry(host=None, container_name="nas", source="manual", last_updated=datetime.now(),
                              internalurl="http://nas.lan", internalurl_source="ui_edit",
                              image_icon="nas", group=media, ip="10.0.0.5")
        db.session.add(manual)
        ensure_url_checks(manual)
        db.session.add(NotificationChannel(
            type="mqtt", name="home-broker", enabled=True, secret=MQTT_PASSWORD,
            config={"host": "mqtt.lan", "port": 1883, "username": "std", "base_topic": "std"}))
        for name in ("alice", "bob"):
            user = User(username=name, email=f"{name}@example.com", is_admin=name == "alice", is_active=True)
            user.set_password(USER_PASSWORD)
            db.session.add(user)
        _, api_key = api_keys.create_key("agent", "write")
        db.session.commit()
    ingest = _key(app, "sidecar", "ingest")[1]
    body = json.loads(FIXTURE.read_text())
    assert client.put("/api/v1/streams/dhcp/snapshot", json=body, headers=_bearer(ingest)).status_code == 202
    write = _key(app, "ops", "write")[1]
    assert client.post("/api/v1/streams/dhcp/enable", headers=_bearer(write)).status_code == 200
    with app.app_context():
        stream = InventoryStream.query.filter_by(stream_id="dhcp").one()
        stream.network_exclude = ["Guest"]
        stream.missing_expiry_days = 14
        db.session.add(InventoryBlock(stream_id=stream.id, key="aa:bb:cc:00:99:99", name="old-printer",
                                      ip="10.0.40.9", blocked_by="admin"))
        db.session.commit()
    return {"mqtt": MQTT_PASSWORD, "user": USER_PASSWORD, "widget": WIDGET_KEY, "api_key": api_key}


def _export(app, fmt=None):
    with app.app_context():
        doc = export_format.build_export(now=datetime(2026, 11, 20, 0, 10, 2, tzinfo=timezone.utc))
        return doc if fmt is None else export_format.dump(doc, fmt)


def _entry(doc, name, kind=None):
    rows = [e for e in doc.entries if e.identity.container_name == name and (kind is None or e.kind == kind)]
    assert len(rows) == 1, (name, [e.identity for e in doc.entries])
    return rows[0]


# --- structure and the ownership table (design 5.3) ------------------------------------------------


def test_header_and_validation(app, seeded):
    doc = _export(app)
    assert (doc.format, doc.format_version) == ("std-export", 1)
    assert export_format.SUPPORTED_VERSIONS == (0, 1)
    assert doc.exported_at == datetime(2026, 11, 20, 0, 10, 2, tzinfo=timezone.utc)
    assert doc.std_version and doc.api_revision >= 4
    assert doc.instance_id is None                   # none created yet: an export never writes one
    ExportDoc.model_validate(yaml.safe_load(export_format.dump(doc, "yaml")))


def test_docker_entry_keeps_only_operator_state(app, seeded):
    grafana = _entry(_export(app), "grafana")
    assert grafana.kind == "docker" and grafana.identity.host == "h1"
    assert grafana.image_icon is None                # unlocked: rewritten on every register
    assert grafana.internalurl is None and grafana.externalurl is None   # label + synthesized URLs
    assert grafana.group == "Monitoring" and grafana.sort_priority == 5
    assert [c.kind for c in grafana.checks] == ["internal_url", "external_url", "container"]


def test_locked_docker_entry_and_ui_edit_url(app, seeded):
    doc = _export(app)
    sonarr = _entry(doc, "sonarr")
    assert sonarr.is_static is True and sonarr.image_icon == "sonarr"
    assert sonarr.externalurl.value == "https://sonarr.example" and sonarr.externalurl.source == "ui_edit"
    assert sonarr.ha_publish is True and sonarr.description == "TV"
    assert sonarr.widget.model_dump() == {"widget_name": "sonarr", "widget_url": "http://sonarr:8989"}
    assert [(w.widget_name, w.widget_url, w.widget_fields, w.api_key_set) for w in doc.widgets] == [
        ("sonarr", "http://sonarr:8989", ["queue"], True)]


def test_manual_entry_keeps_its_urls_and_icon(app, seeded):
    nas = _entry(_export(app), "nas")
    assert nas.kind == "manual" and nas.identity.host is None
    assert nas.image_icon == "nas" and nas.group == "Media"
    assert nas.internalurl.value == "http://nas.lan" and nas.internalurl.source == "ui_edit"


def test_stream_entries_blocks_and_settings(app, seeded):
    doc = _export(app)
    stream_entries = [e for e in doc.entries if e.kind == "stream"]
    assert len(stream_entries) >= 5
    pump = _entry(doc, "shelly-pump", "stream")
    assert pump.identity.stream == "dhcp" and pump.identity.stream_key == "aa:bb:cc:00:00:01"
    assert pump.identity.host is None and pump.identity.name_source == "stream" and not pump.identity.linked
    dhcp, = doc.streams
    assert (dhcp.stream_id, dhcp.key_type, dhcp.status, dhcp.network_exclude, dhcp.missing_expiry_days) == (
        "dhcp", "mac", "enabled", ["Guest"], 14)
    assert [(b.key, b.name, b.ip, b.blocked_by) for b in dhcp.blocks] == [
        ("aa:bb:cc:00:99:99", "old-printer", "10.0.40.9", "admin")]
    assert dhcp.blocks[0].blocked_at.tzinfo is not None


def test_observed_and_bookkeeping_fields_are_absent(app, seeded):
    data = export_format.to_dict(_export(app))
    entry_keys = set()
    for entry in data["entries"]:
        entry_keys |= set(_all_keys(entry))
    for field in ("docker_status", "container_id", "networks", "exposed_ports", "published_ports",
                  "mac", "ip", "network", "attributes", "last_updated", "started_at", "image_registry",
                  "image_tag", "last_checked_at", "consecutive_failures", "inventory_missing",
                  "notifier_reported_group_name", "deleted_at", "last_ok"):
        assert field not in entry_keys, field
    text = json.dumps(data)
    assert "10.0.0.5" not in text and "bridge" not in text      # observed ip and networks
    for field in ("oauth_", "last_login_at", "created_at", "password_changed_at"):
        assert field not in text, field


def test_soft_deleted_entries_are_not_exported(app, seeded):
    names = {e.identity.container_name for e in _export(app).entries}
    assert "trashed" not in names and {"grafana", "sonarr", "nas"} <= names


def test_groups_widgets_channels_users_and_settings(app, seeded):
    doc = _export(app)
    assert [(g.name, g.sort_priority, g.icon) for g in doc.groups] == [
        ("Media", 10, "mdi-play"), ("Monitoring", None, None)]
    channel, = doc.notification_channels
    assert (channel.name, channel.type, channel.enabled, channel.secret_set) == ("home-broker", "mqtt", True, True)
    assert channel.config["host"] == "mqtt.lan" and channel.config["username"] == "std"
    assert [(u.username, u.email, u.is_admin, u.is_active) for u in doc.users] == [
        ("alice", "alice@example.com", True, True), ("bob", "bob@example.com", False, True)]
    s = doc.settings
    assert s.exposure_layers == {"traefik": "external"}
    assert s.exposure_layers_per_host == {"h2": {"traefik": "internal"}}
    assert s.update_check.enabled is True and s.update_check.interval_hours == 6
    assert s.backup.snapshot.time == "00:05" and s.backup.export.format == "yaml"
    assert "path" not in s.backup.model_dump() and "path" not in export_format.to_dict(doc)["settings"]["backup"]


def test_entries_are_sorted_by_kind_host_and_name(app, seeded):
    doc = _export(app)
    keys = [(e.kind, e.identity.host or "", e.identity.stream or "", e.identity.container_name)
            for e in doc.entries]
    assert keys == sorted(keys)
    assert [e.kind for e in doc.entries][:2] == ["docker", "docker"]


# --- secrets ----------------------------------------------------------------------------------------


def _all_keys(data):
    if isinstance(data, dict):
        for k, v in data.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(data, list):
        for item in data:
            yield from _all_keys(item)


def test_no_secret_is_ever_serialised(app, seeded):
    with app.app_context():
        user_hash = User.query.filter_by(username="alice").one().password_hash
        key_hash = ApiKey.query.filter_by(name="agent").one().key_hash
    doc = _export(app)
    for fmt in ("yaml", "json"):
        text = export_format.dump(doc, fmt).decode()
        text = "\n".join(line for line in text.splitlines() if not line.startswith("#"))   # the header comment
        for secret in (seeded["mqtt"], seeded["widget"], seeded["user"], user_hash, key_hash,
                       seeded["api_key"], seeded["api_key"].split("_")[1]):
            assert secret not in text, (fmt, secret)
        for name in ("password_hash", "key_hash", "widget_api_key", "api_token"):
            assert name not in text, (fmt, name)
    data = export_format.to_dict(doc)
    names = set(_all_keys(data))
    assert not names & {"secret", "password", "password_hash", "widget_api_key", "key_hash", "api_key"}
    assert "secret_set" in names and "api_key_set" in names
    assert "agent" not in json.dumps(data)            # API keys are not exported at all


def test_a_secret_looking_channel_config_key_is_dropped(app, seeded):
    with app.app_context():
        channel = NotificationChannel.query.one()
        channel.config = {**channel.config, "password": "leak", "api_key": "leak2"}
        db.session.commit()
    text = export_format.dump(_export(app), "json").decode()
    assert "leak" not in text


# --- serialising ---------------------------------------------------------------------------------


def test_yaml_and_json_round_trip_to_equal_documents(app, seeded):
    doc = _export(app)
    from_yaml = ExportDoc.model_validate(yaml.safe_load(export_format.dump(doc, "yaml")))
    from_json = ExportDoc.model_validate(json.loads(export_format.dump(doc, "json")))
    assert from_yaml == from_json == doc
    assert not export_format.unknown_keys(from_yaml)


def test_formats_are_well_formed(app, seeded):
    doc = _export(app)
    raw_yaml = export_format.dump(doc, "yaml").decode()
    assert raw_yaml.startswith("# Service Tracker Dashboard export") and "does NOT include" in raw_yaml
    assert 'exported_at: "2026-11-20T00:10:02Z"' in raw_yaml or "exported_at: '2026-11-20T00:10:02Z'" in raw_yaml
    raw_json = export_format.dump(doc, "json").decode()
    assert raw_json.endswith("}\n") and raw_json.startswith('{\n  "format": "std-export"')
    with pytest.raises(ValueError):
        export_format.dump(doc, "toml")


def test_output_is_deterministic(app, seeded):
    first, second = _export(app, "yaml"), _export(app, "yaml")
    assert first == second
    assert _export(app, "json") == _export(app, "json")
    other = export_format.dump(
        ExportDoc.model_validate({**export_format.to_dict(_export(app)), "exported_at": "2030-01-01T00:00:00Z"}),
        "yaml")
    assert other != first and other.replace(b"2030-01-01T00:00:00Z", b"2026-11-20T00:10:02Z") == first


def test_an_empty_database_exports_cleanly(app):
    doc = _export(app)
    assert doc.entries == [] and doc.groups == [] and doc.users == []
    assert ExportDoc.model_validate(json.loads(export_format.dump(doc, "json"))) == doc


def test_unknown_keys_are_reported_by_path_and_not_written_back(app, seeded):
    data = export_format.to_dict(_export(app))
    data["future"] = 1
    for entry in data["entries"][:2]:
        entry["foo"] = "x"
    data["entries"][0]["identity"]["bar"] = True
    doc = ExportDoc.model_validate(data)
    assert export_format.unknown_keys(doc) == {"future": 1, "entries[].foo": 2, "entries[].identity.bar": 1}
    assert "foo" not in export_format.to_dict(doc)["entries"][0]


def test_a_bad_header_is_rejected():
    with pytest.raises(ValidationError):
        ExportDoc.model_validate({"format": "other", "format_version": 1, "exported_at": "2026-01-01T00:00:00Z",
                                  "std_version": "1", "api_revision": 4})


# --- the UI download ---------------------------------------------------------------------------


def test_ui_download_yaml_and_json(app, seeded, admin_client):
    resp = admin_client.get("/settings/backups/export?format=yaml")
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["Content-Disposition"].startswith('attachment; filename="std_export_')
    assert resp.headers["Content-Disposition"].endswith('.yml"')
    assert resp.mimetype == "application/yaml"
    assert ExportDoc.model_validate(yaml.safe_load(resp.data)).format == "std-export"
    default = admin_client.get("/settings/backups/export")
    assert default.headers["Content-Disposition"].endswith('.yml"')
    resp = admin_client.get("/settings/backups/export?format=json")
    assert resp.headers["Content-Disposition"].endswith('.json"') and resp.mimetype == "application/json"
    assert json.loads(resp.data)["format_version"] == 1
    for secret in (MQTT_PASSWORD, WIDGET_KEY, USER_PASSWORD):
        assert secret.encode() not in resp.data


def test_ui_download_rejects_an_unknown_format_and_needs_admin(app, client, admin_client):
    assert admin_client.get("/settings/backups/export?format=xml").status_code == 400
    assert client.get("/settings/backups/export").status_code in (302, 401, 403)


def test_the_exports_card_offers_both_downloads(app, admin_client):
    html = admin_client.get("/settings?section=backup").get_data(as_text=True)
    assert 'id="export-download-yaml"' in html and "format=yaml" in html
    assert 'id="export-download-json"' in html and "format=json" in html
