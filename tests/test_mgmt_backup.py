"""Management API: backup settings, backup list and run, export (API revision 4, bak-02)."""

import json
import os
import time

import pytest
import yaml

import backups
import mgmt_openapi
from api_version import API_REVISION, API_REVISION_HISTORY, FEATURES
from export_format import ExportDoc
from tests.test_mgmt_api_keys import _bearer, _key
from tests.test_mgmt_entries import _audit


@pytest.fixture
def folder(app, tmp_path):
    old = {k: app.config.get(k) for k in ("backup_path", "backup_days_to_keep")}
    old_env, old_file = app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"]
    app.config["backup_path"] = str(tmp_path)
    app.config["backup_days_to_keep"] = 7
    app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = {}, {}
    yield tmp_path
    app.config.update(old)
    app.config["CONFIG_FROM_ENV"], app.config["CONFIG_FROM_FILE"] = old_env, old_file


@pytest.fixture
def wkey(app):
    return _bearer(_key(app, "writer", "write")[1])


@pytest.fixture
def rkey(app):
    return _bearer(_key(app, "reader", "read")[1])


# --- revision ----------------------------------------------------------------------------


def test_revision_4_row_and_feature():
    assert API_REVISION >= 5         # 5 is the image_repo_url addition, 6 the ports route
    row = [r for r in API_REVISION_HISTORY if r[0] == 4][0]
    assert row[:2] == (4, "0.11.0") and "export" in row[2]
    assert "backup" in FEATURES


def test_new_routes_are_declared_with_the_right_scopes():
    ops = {(o.method, o.path): o.scope for o in mgmt_openapi.OPERATIONS}
    assert ops[("GET", "/settings/backup")] == "read" and ops[("PUT", "/settings/backup")] == "write"
    assert ops[("GET", "/backups")] == "read" and ops[("POST", "/backups/run")] == "write"
    assert ops[("GET", "/export")] == "read"


def test_spec_describes_the_export_and_the_requests(client):
    spec = client.get("/api/v1/openapi.json").get_json()
    schemas = spec["components"]["schemas"]
    assert schemas["BackupSettingsPut"]["additionalProperties"] is False
    assert schemas["BackupRunRequest"]["additionalProperties"] is False
    assert "ExportDoc" in schemas
    assert not any(k in json.dumps(schemas["ExportDoc"]) for k in ("password_hash", "key_hash"))


# --- scopes ---------------------------------------------------------------------------------

WRITES = [("put", "/api/v1/settings/backup", {"path": "/x"}), ("post", "/api/v1/backups/run", {"kind": "export"})]
READS = ["/api/v1/settings/backup", "/api/v1/backups", "/api/v1/export"]


@pytest.mark.parametrize("method,path,body", WRITES)
def test_a_read_key_cannot_write(client, rkey, method, path, body):
    assert getattr(client, method)(path, json=body, headers=rkey).status_code == 403


@pytest.mark.parametrize("path", READS)
def test_reads_need_a_key_and_a_read_key_is_enough(client, rkey, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=rkey).status_code == 200


# --- settings ----------------------------------------------------------------------------------


def test_get_settings_has_origins_runs_and_next_runs(app, client, rkey, folder):
    body = client.get("/api/v1/settings/backup", headers=rkey).get_json()
    assert body["path"] == {"value": str(folder), "origin": "default"}
    assert body["snapshot"]["time"] == {"value": "00:05", "origin": "default"}
    assert body["export"]["format"] == {"value": "yaml", "origin": "default"}
    assert body["export"]["keep_days"]["value"] == 7
    assert body["last_runs"] == {} and set(body["next_runs"]) == {"snapshot", "export"}


def test_put_changes_values_reschedules_and_audits(app, client, wkey, folder, monkeypatch):
    calls = []
    monkeypatch.setattr("jobs.reschedule_backups", lambda a: calls.append(a))
    r = client.put("/api/v1/settings/backup", headers=wkey, json={
        "snapshot": {"time": "03:30", "keep_days": 14}, "export": {"enabled": False, "format": "json"}})
    assert r.status_code == 200, r.get_json()
    out = r.get_json()
    assert out["snapshot"]["time"] == {"value": "03:30", "origin": "ui"}
    assert out["snapshot"]["keep_days"]["value"] == 14 and out["export"]["enabled"]["value"] is False
    assert out["export"]["format"] == {"value": "json", "origin": "ui"} and out["warnings"] == []
    assert out["snapshot"]["enabled"]["origin"] == "default" and calls
    rows = _audit(app, object_type="backup_settings")
    assert rows[-1][:2] == ("PUT", "/api/v1/settings/backup") and rows[-1][4] == 200
    assert rows[-1][5]["snapshot.time"] == ["00:05", "03:30"] and rows[-1][5]["export.format"] == ["yaml", "json"]


def test_put_validation_errors_write_nothing(app, client, wkey, folder):
    for body, field in (({"snapshot": {"time": "25:00"}}, "snapshot.time"),
                        ({"export": {"keep_days": 0}}, "export.keep_days"),
                        ({"path": "relative/dir"}, "path")):
        r = client.put("/api/v1/settings/backup", headers=wkey, json=body)
        assert r.status_code == 400, body
        assert r.get_json()["details"][0]["loc"] == field.split(".")
    for body in ({}, {"snapshot": {}}, {"export": {"format": "toml"}}, {"bogus": 1},
                 {"snapshot": {"format": "json"}}, {"snapshot": {"keep_days": "7"}}):
        assert client.put("/api/v1/settings/backup", headers=wkey, json=body).status_code == 400, body
    assert client.get("/api/v1/settings/backup", headers=wkey).get_json()["snapshot"]["time"]["origin"] == "default"


def test_put_an_env_pinned_field_is_a_409_unless_unchanged(app, client, wkey, folder):
    app.config["CONFIG_FROM_ENV"] = {"backup_days_to_keep": 7}
    got = client.get("/api/v1/settings/backup", headers=wkey).get_json()
    assert got["snapshot"]["keep_days"]["origin"] == "env"
    r = client.put("/api/v1/settings/backup", headers=wkey, json={"snapshot": {"keep_days": 30}})
    assert r.status_code == 409 and "BACKUP_DAYS_TO_KEEP" in r.get_json()["error"]
    assert client.put("/api/v1/settings/backup", headers=wkey,
                      json={"snapshot": {"keep_days": 7, "time": "04:00"}}).status_code == 200
    assert _audit(app, object_type="backup_settings")[0][4] == 409


def test_put_path_outside_config_warns(app, client, wkey, folder, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere")
    r = client.put("/api/v1/settings/backup", headers=wkey, json={"path": str(other)})
    assert r.status_code == 200 and r.get_json()["path"]["value"] == str(other)
    assert r.get_json()["warnings"] and "outside /config" in r.get_json()["warnings"][0]


# --- list and run -----------------------------------------------------------------------------


def test_run_lists_and_audits(app, client, wkey, folder):
    r = client.post("/api/v1/backups/run", headers=wkey, json={"kind": "snapshot"})
    assert r.status_code == 200
    snap = r.get_json()
    assert snap["ok"] is True and snap["kind"] == "snapshot" and snap["trigger"] == "manual"
    assert snap["file"].endswith("-std_backup.sqlite3") and snap["size"] > 0 and snap["error"] is None
    exp = client.post("/api/v1/backups/run", headers=wkey, json={"kind": "export"}).get_json()
    assert exp["ok"] and exp["file"].endswith("-std_export.yml")
    (folder / "2019-01-01-std_backup.yml").write_text("- x: 1\n")
    items = client.get("/api/v1/backups", headers=wkey).get_json()["items"]
    by_name = {i["name"]: i for i in items}
    assert set(by_name) == {snap["file"], exp["file"], "2019-01-01-std_backup.yml"}
    assert by_name[snap["file"]]["kind"] == "snapshot" and by_name[snap["file"]]["manual"] is True
    assert by_name["2019-01-01-std_backup.yml"]["legacy"] is True
    assert items[0]["modified"].endswith("Z") and set(items[0]) == {"name", "kind", "size", "modified", "manual", "legacy"}
    got = client.get("/api/v1/settings/backup", headers=wkey).get_json()["last_runs"]
    assert got["snapshot"]["ok"] is True and got["export"]["file"] == exp["file"]
    rows = _audit(app, object_type="backup_run")
    assert [(r[3], r[4]) for r in rows] == [("snapshot", 200), ("export", 200)]
    assert rows[0][5]["result"] == [None, "ok"] and rows[0][5]["file"] == [None, snap["file"]]
    assert not [n for n in os.listdir(folder) if n.endswith(".tmp")]


def test_run_rejects_an_unknown_kind_and_audits_it(app, client, wkey, folder):
    assert client.post("/api/v1/backups/run", headers=wkey, json={"kind": "all"}).status_code == 400
    assert client.post("/api/v1/backups/run", headers=wkey, json={}).status_code == 400
    assert [r[4] for r in _audit(app, object_type="backup_run")] == [400, 400]


def test_run_while_running_is_a_409(app, client, wkey, folder):
    assert backups._RUN_LOCKS["export"].acquire(blocking=False)
    try:
        r = client.post("/api/v1/backups/run", headers=wkey, json={"kind": "export"})
    finally:
        backups._RUN_LOCKS["export"].release()
    assert r.status_code == 409 and "already running" in r.get_json()["error"]
    assert _audit(app, object_type="backup_run")[-1][4] == 409


def test_a_failed_run_is_reported_in_the_result(app, client, wkey, folder, monkeypatch):
    def boom(path, fmt):
        raise OSError("disk full")
    monkeypatch.setattr(backups, "_write_export", boom)
    r = client.post("/api/v1/backups/run", headers=wkey, json={"kind": "export"})
    assert r.status_code == 200 and r.get_json()["ok"] is False and "disk full" in r.get_json()["error"]
    assert _audit(app, object_type="backup_run")[-1][5]["result"] == [None, "failed"]


def test_list_with_an_unreadable_folder_is_a_409(app, client, rkey, folder, monkeypatch):
    def boom(directory=None):
        raise PermissionError(13, "Permission denied")
    monkeypatch.setattr(backups, "list_files", boom)
    r = client.get("/api/v1/backups", headers=rkey)
    assert r.status_code == 409 and "Permission denied" in r.get_json()["error"]


def test_old_files_still_sort_by_age(app, client, rkey, folder):
    old = time.time() - 86400
    for name, ts in (("2020-01-01-std_backup.sqlite3", old), ("2020-01-02-std_export.json", time.time())):
        (folder / name).write_text("x")
        os.utime(folder / name, (ts, ts))
    assert [i["name"] for i in client.get("/api/v1/backups", headers=rkey).get_json()["items"]] == [
        "2020-01-02-std_export.json", "2020-01-01-std_backup.sqlite3"]


# --- export -----------------------------------------------------------------------------------


def test_export_json_default_and_yaml(app, client, rkey, register):
    register(host="h1", container_name="grafana", group_name="Monitoring")
    r = client.get("/api/v1/export", headers=rkey)
    assert r.status_code == 200 and r.mimetype == "application/json" and r.headers["Cache-Control"] == "no-store"
    doc = r.get_json()
    assert doc["format"] == "std-export" and doc["format_version"] == 1 and doc["api_revision"] == API_REVISION
    assert doc["entries"][0]["identity"] == {"container_name": "grafana", "host": "h1", "linked": False}
    assert doc["groups"] == [{"name": "Monitoring"}]
    ExportDoc.model_validate(doc)
    y = client.get("/api/v1/export?format=yaml", headers=rkey)
    assert y.status_code == 200 and y.mimetype == "application/yaml"
    ydoc = yaml.safe_load(y.data)
    assert ydoc["entries"] == doc["entries"] and ydoc["groups"] == doc["groups"]
    assert client.get("/api/v1/export?format=json", headers=rkey).get_json()["entries"] == doc["entries"]


def test_export_bad_format_is_a_400_and_reads_are_not_audited(app, client, rkey):
    r = client.get("/api/v1/export?format=xml", headers=rkey)
    assert r.status_code == 400 and r.get_json()["details"][0]["loc"] == ["format"]
    client.get("/api/v1/export", headers=rkey)
    client.get("/api/v1/backups", headers=rkey)
    assert _audit(app) == []


def test_export_has_no_secret(app, client, rkey, wkey, register):
    from extensions import db
    from models import NotificationChannel, User
    with app.app_context():
        db.session.add(NotificationChannel(type="mqtt", name="b", enabled=False, secret="s3cret-mqtt",
                                           config={"host": "mqtt.lan"}))
        u = User(username="u1", email="u1@example.com", is_admin=False, is_active=True)
        u.set_password("pw-u1-secret")
        db.session.add(u)
        db.session.commit()
    for fmt in ("json", "yaml"):
        text = client.get(f"/api/v1/export?format={fmt}", headers=rkey).get_data(as_text=True)
        for needle in ("s3cret-mqtt", "pw-u1-secret", wkey["Authorization"].split(" ")[1], "password_hash"):
            assert needle not in text
