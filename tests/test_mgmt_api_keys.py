"""Admin API keys, the management blueprint and the write audit log
(v0.8.0, PRD 14.2 and 14.6)."""

import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta

import pytest
from flask import Blueprint, jsonify
from flask import g as flask_g

import api_keys
import jobs
import routes_mgmt_api as mgmt
from extensions import csrf, db
from models import ApiAudit, ApiKey
from tests.conftest import TEST_TOKEN

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PREVIOUS_HEAD = "c1d7a3e5f2b8"
API_REV = "d4a9e2c6b715"


def _key(app, name="k1", scope="read"):
    with app.app_context():
        key, full = api_keys.create_key(name, scope)
        return key.id, full


def _bearer(full):
    return {"Authorization": f"Bearer {full}"}


# --- dummy write routes (the real write endpoints arrive in v080-02) ----------


@pytest.fixture(scope="session", autouse=True)
def _test_write_routes(app):
    bp = Blueprint("mgmt_test", __name__, url_prefix="/api/v1/_test")
    csrf.exempt(bp)
    bp.after_request(mgmt.audit_response)

    @bp.route("/write", methods=["POST", "DELETE"])
    @mgmt.require_api_key("write")
    def write():
        from flask import request

        body = request.get_json(silent=True) or {}
        if body.get("bad"):
            return mgmt.json_error(400, "Invalid request body", ["bad"])
        mgmt.audit("thing", 7, {"name": ["a", "b"], "widget_api_key": ["old", "new"],
                                "api_token": [None, "s3cretvalue"]})
        return jsonify({"ok": True})

    @bp.route("/read", methods=["GET"])
    @mgmt.require_api_key("read")
    def read():
        mgmt.audit("thing", 1, {"x": [1, 2]})  # reads are never audited
        return jsonify({"ok": True})

    # Flask refuses new routes after the first request; the session app has
    # already served some by the time this fixture runs.
    app._got_first_request = False
    app.register_blueprint(bp)
    app._got_first_request = True


# --- generation and verification ----------------------------------------------


def test_generate_key_format_and_hash():
    full, prefix, key_hash = api_keys.generate_key()
    assert re.fullmatch(r"std_[0-9a-f]{8}_[A-Za-z0-9_-]{43,}", full)
    assert full.split("_", 2)[1] == prefix
    assert len(key_hash) == 64 and full not in key_hash
    assert api_keys.generate_key()[0] != full


def test_verify_good_wrong_unknown_revoked(app):
    key_id, full = _key(app)
    with app.app_context():
        assert api_keys.verify(full).id == key_id
        assert api_keys.verify(full + "x") is None  # wrong secret
        prefix = full.split("_", 2)[1]
        assert api_keys.verify(f"std_{prefix}_{'A' * 43}") is None
        assert api_keys.verify("std_deadbeef_" + "A" * 43) is None  # unknown prefix
        for junk in (None, "", "std_", "std__x", "nope", "Bearer " + full):
            assert api_keys.verify(junk) is None
        api_keys.revoke_key(db.session.get(ApiKey, key_id))
        assert api_keys.verify(full) is None


def test_secret_may_contain_underscores(app):
    with app.app_context():
        key, _ = api_keys.create_key("u", "read")
        full = f"std_{key.prefix}_ab_cd-ef"
        key.key_hash = api_keys._hash(full)
        db.session.commit()
        assert api_keys.verify(full).id == key.id


def test_scope_allows():
    assert api_keys.scope_allows("write", "read")
    assert api_keys.scope_allows("write", "write")
    assert api_keys.scope_allows("read", "read")
    assert not api_keys.scope_allows("read", "write")


def test_key_hash_only_is_stored(app):
    _, full = _key(app)
    with app.app_context():
        row = ApiKey.query.one()
        assert full.split("_", 2)[2] not in (row.key_hash, row.prefix, row.name)


# --- auth matrix ---------------------------------------------------------------


def test_whoami_scope_matrix(app, client):
    _, rk = _key(app, "reader", "read")
    _, wk = _key(app, "writer", "write")
    r = client.get("/api/v1/whoami", headers=_bearer(rk))
    assert r.status_code == 200
    body = r.get_json()
    assert {k: body[k] for k in ("name", "prefix", "scope", "version")} == {
        "name": "reader", "prefix": rk.split("_")[1], "scope": "read",
        "version": app.config["VERSION_INFO"]["version"]}
    # additive build/update fields (version-in-ui)
    assert {"commit", "channel", "build_time", "update"} <= set(body)
    assert client.get("/api/v1/whoami", headers=_bearer(wk)).get_json()["scope"] == "write"

    # read key on a write endpoint -> 403; write key -> 200
    assert client.post("/api/v1/_test/write", headers=_bearer(rk)).status_code == 403
    assert client.post("/api/v1/_test/write", headers=_bearer(wk)).status_code == 200
    # write key on a read endpoint
    assert client.get("/api/v1/_test/read", headers=_bearer(wk)).status_code == 200


def test_missing_invalid_revoked_are_401_json(app, client):
    kid, full = _key(app)
    for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": full},
                    {"Authorization": f"Basic {full}"}):
        r = client.get("/api/v1/whoami", headers=headers)
        assert r.status_code == 401
        assert set(r.get_json()) == {"error", "details"}
        assert r.headers["WWW-Authenticate"] == "Bearer"
    with app.app_context():
        api_keys.revoke_key(db.session.get(ApiKey, kid))
    assert client.get("/api/v1/whoami", headers=_bearer(full)).status_code == 401


def test_session_cookie_alone_is_401(admin_client):
    assert admin_client.get("/api/v1/whoami").status_code == 401


def test_notifier_token_rejected_on_mgmt_and_mgmt_key_rejected_on_register(app, client, register):
    assert client.get("/api/v1/whoami", headers=_bearer(TEST_TOKEN)).status_code == 401
    _, wk = _key(app, "w", "write")
    r = register(headers=_bearer(wk))
    assert r.status_code == 401
    # and the notifier token still registers
    assert register().status_code in (200, 201)


def test_json_error_shape_on_forbidden(app, client):
    _, rk = _key(app)
    body = client.post("/api/v1/_test/write", headers=_bearer(rk)).get_json()
    assert body["error"] == "Forbidden" and "write" in body["details"]


# --- last_used throttling ------------------------------------------------------


def test_last_used_is_throttled_to_once_a_minute(app, client):
    kid, full = _key(app)
    client.get("/api/v1/whoami", headers=_bearer(full), environ_overrides={"REMOTE_ADDR": "10.1.2.3"})
    with app.app_context():
        k = db.session.get(ApiKey, kid)
        first = k.last_used_at
        assert first is not None and k.last_used_ip == "10.1.2.3"
    client.get("/api/v1/whoami", headers=_bearer(full), environ_overrides={"REMOTE_ADDR": "10.9.9.9"})
    with app.app_context():
        k = db.session.get(ApiKey, kid)
        assert k.last_used_at == first and k.last_used_ip == "10.1.2.3"
        k.last_used_at = datetime.utcnow() - timedelta(minutes=2)
        db.session.commit()
    client.get("/api/v1/whoami", headers=_bearer(full), environ_overrides={"REMOTE_ADDR": "10.9.9.9"})
    with app.app_context():
        k = db.session.get(ApiKey, kid)
        assert k.last_used_at > datetime.utcnow() - timedelta(seconds=30)
        assert k.last_used_ip == "10.9.9.9"


# --- audit ---------------------------------------------------------------------


def test_audit_row_on_write_with_masked_secrets(app, client):
    kid, full = _key(app, "agent", "write")
    assert client.post("/api/v1/_test/write", headers=_bearer(full)).status_code == 200
    with app.app_context():
        row = ApiAudit.query.one()
        assert (row.api_key_id, row.key_name, row.method, row.path, row.status_code) == (
            kid, "agent", "POST", "/api/v1/_test/write", 200)
        assert (row.object_type, row.object_id) == ("thing", "7")
        assert row.changes["name"] == ["a", "b"]
        assert row.changes["widget_api_key"] == ["***", "***"]
        assert row.changes["api_token"] == ["***", "***"]
        assert "s3cretvalue" not in str(row.changes) and "old" not in str(row.changes) and "new" not in str(row.changes)


def test_failed_write_is_audited_reads_and_unauthenticated_are_not(app, client):
    _, full = _key(app, "agent", "write")
    r = client.post("/api/v1/_test/write", json={"bad": 1}, headers=_bearer(full))
    assert r.status_code == 400
    client.delete("/api/v1/_test/write", headers=_bearer(full))
    client.get("/api/v1/_test/read", headers=_bearer(full))
    client.get("/api/v1/whoami", headers=_bearer(full))
    client.post("/api/v1/_test/write")  # no key
    client.post("/api/v1/_test/write", headers=_bearer("std_00000000_x"))
    with app.app_context():
        rows = ApiAudit.query.order_by(ApiAudit.id).all()
        assert [(r.method, r.status_code) for r in rows] == [("POST", 400), ("DELETE", 200)]
        assert rows[0].object_type is None and rows[0].changes is None


def test_forbidden_write_by_read_key_is_audited(app, client):
    _, rk = _key(app, "ro", "read")
    client.post("/api/v1/_test/write", headers=_bearer(rk))
    with app.app_context():
        assert [r.status_code for r in ApiAudit.query.all()] == [403]


def test_audit_masking_helper(app):
    with app.test_request_context("/"):
        mgmt.audit("widget", 3, {"widget_api_key": ["a", "b"], "Secret_Key": ["a", "b"],
                                 "password": ["a", "b"], "url": ["x", "y"],
                                 "when": [datetime(2026, 1, 1), None]})
        ch = flask_g.audit["changes"]
        assert ch["widget_api_key"] == ch["Secret_Key"] == ch["password"] == ["***", "***"]
        assert ch["url"] == ["x", "y"]
        assert ch["when"] == ["2026-01-01 00:00:00", None]
        assert flask_g.audit["object_id"] == "3"


def test_audit_survives_key_deletion(app, client):
    kid, full = _key(app, "gone", "write")
    client.post("/api/v1/_test/write", headers=_bearer(full))
    with app.app_context():
        db.session.execute(db.text("PRAGMA foreign_keys=ON"))
        db.session.delete(db.session.get(ApiKey, kid))
        db.session.commit()
        row = ApiAudit.query.one()
        assert row.key_name == "gone"


# --- retention -----------------------------------------------------------------


def test_purge_api_audit_respects_retention(app):
    now = datetime(2026, 11, 15, 12, 0)
    with app.app_context():
        for days, path in ((100, "/old"), (91, "/old2"), (89, "/new"), (0, "/now")):
            db.session.add(ApiAudit(ts=now - timedelta(days=days), method="POST", path=path,
                                    status_code=200))
        db.session.commit()
        assert jobs.purge_api_audit(app, now_utc=now) == 2
        assert sorted(r.path for r in ApiAudit.query.all()) == ["/new", "/now"]
        app.config["api_audit_retention_days"] = 10
        try:
            assert jobs.purge_api_audit(app, now_utc=now) == 1
        finally:
            app.config["api_audit_retention_days"] = 90


def test_retention_setting_default(app):
    assert app.config["api_audit_retention_days"] == 90


# --- Settings -> API tab -------------------------------------------------------


def test_settings_requires_admin_for_key_routes(client):
    assert client.post("/settings/api-keys", data={"name": "x", "scope": "read"}).status_code == 302
    with client.application.app_context():
        assert ApiKey.query.count() == 0


def test_settings_create_show_once_and_revoke(app, admin_client):
    r = admin_client.post("/settings/api-keys", data={"name": "agent", "scope": "write"})
    assert r.status_code == 200
    assert r.headers["Cache-Control"] == "no-store"
    html = r.get_data(as_text=True)
    full = re.search(r'id="new-api-key"[^>]*value="(std_[^"]+)"', html).group(1)
    assert "won't see it again" in html and "copy-api-key" in html
    with app.app_context():
        row = ApiKey.query.one()
        assert (row.name, row.scope) == ("agent", "write")
        assert row.created_by is not None and api_keys.verify(full).id == row.id
        kid = row.id

    # Never in the session/flash, and never on the settings page afterwards.
    with admin_client.session_transaction() as sess:
        assert full not in str(dict(sess))
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert full not in page and full.split("_", 2)[2] not in page
    assert "agent" in page and "active" in page

    r = admin_client.post(f"/settings/api-keys/{kid}/revoke")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(ApiKey, kid).revoked_at is not None
        assert api_keys.verify(full) is None
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert "agent" in page and "revoked" in page and "opacity-50" in page


@pytest.mark.parametrize("name,scope", [("", "read"), ("x" * 65, "read"), ("ok", "admin"), ("ok", "")])
def test_settings_create_rejects_bad_input(app, admin_client, name, scope):
    r = admin_client.post("/settings/api-keys", data={"name": name, "scope": scope})
    assert r.status_code == 302
    with app.app_context():
        assert ApiKey.query.count() == 0


def test_settings_create_rejects_duplicate_active_name(app, admin_client):
    _, _ = _key(app, "dup", "read")
    admin_client.post("/settings/api-keys", data={"name": "dup", "scope": "read"})
    with app.app_context():
        assert ApiKey.query.count() == 1


def test_settings_key_routes_enforce_csrf(app, admin_client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = admin_client.post("/settings/api-keys", data={"name": "n", "scope": "read"},
                              headers={"Referer": "http://localhost/settings"})
        assert r.status_code == 302 and "/settings" in r.headers["Location"]
        with app.app_context():
            assert ApiKey.query.count() == 0
        html = admin_client.get("/settings?section=api").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = admin_client.post("/settings/api-keys",
                              data={"name": "n", "scope": "read", "csrf_token": token})
        assert r.status_code == 200
        with app.app_context():
            kid = ApiKey.query.one().id
        r = admin_client.post(f"/settings/api-keys/{kid}/revoke")
        assert r.status_code == 302
        with app.app_context():
            assert db.session.get(ApiKey, kid).revoked_at is None  # no token, not revoked
        admin_client.post(f"/settings/api-keys/{kid}/revoke", data={"csrf_token": token})
        with app.app_context():
            assert db.session.get(ApiKey, kid).revoked_at is not None
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_mgmt_blueprint_is_csrf_exempt(app, client):
    _, full = _key(app, "w", "write")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        assert client.post("/api/v1/_test/write", headers=_bearer(full)).status_code == 200
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


# --- migration -----------------------------------------------------------------


def _alembic(tmp_path, db_path, command, target):
    ini = tmp_path / "alembic.ini"
    text = open(os.path.join(REPO_ROOT, "alembic.ini")).read()
    text = re.sub(r"(?m)^script_location\s*=.*$", f"script_location = {REPO_ROOT}/alembic", text)
    text = re.sub(r"(?m)^sqlalchemy.url\s*=.*$", f"sqlalchemy.url = sqlite:///{db_path}", text)
    ini.write_text(text)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ini), command, target],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr


def _tables(db_path):
    con = sqlite3.connect(db_path)
    try:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_migration_up_down_up(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", PREVIOUS_HEAD)
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO service_entry (host, container_name, last_updated, is_static) "
                "VALUES ('h', 'keepme', '2026-01-01 00:00:00', 0)")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "upgrade", API_REV)
    assert {"api_key", "api_audit"} <= _tables(db_path)
    con = sqlite3.connect(db_path)
    idx_key = [r[1] for r in con.execute("PRAGMA index_list(api_key)")]
    idx_audit = [r[1] for r in con.execute("PRAGMA index_list(api_audit)")]
    assert "ix_api_key_prefix" in idx_key and "ix_api_key_created_by" in idx_key
    assert "ix_api_audit_ts" in idx_audit and "ix_api_audit_api_key_id" in idx_audit
    con.execute("INSERT INTO api_key (name, prefix, key_hash, scope, created_at) "
                "VALUES ('n', 'abcd1234', 'h', 'read', '2026-01-01 00:00:00')")
    con.commit()
    con.close()

    _alembic(tmp_path, db_path, "downgrade", "-1")
    assert not ({"api_key", "api_audit"} & _tables(db_path))
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM service_entry").fetchone()[0] == 1
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    assert {"api_key", "api_audit"} <= _tables(db_path)
    con = sqlite3.connect(db_path)
    assert con.execute("SELECT count(*) FROM service_entry").fetchone()[0] == 1
    con.close()


# --- v0.9.0: rotation and name reuse --------------------------------------------


REVOKE_REV = "b7d3f1a94e26"
ROTATE_REV = "c2e8a5b3d917"


def _index_sql(db_path, name):
    con = sqlite3.connect(db_path)
    try:
        row = con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone()
        return row[0] if row else None
    finally:
        con.close()


def _insert_key(db_path, name, revoked=None):
    con = sqlite3.connect(db_path)
    con.execute("INSERT INTO api_key (name, prefix, key_hash, scope, created_at, revoked_at) "
                "VALUES (?, 'abcd1234', 'h', 'read', '2026-01-01 00:00:00', ?)", (name, revoked))
    con.commit()
    con.close()


def test_migration_rotate_and_name_reuse_up_down_up(tmp_path):
    db_path = str(tmp_path / "m.db")
    _alembic(tmp_path, db_path, "upgrade", REVOKE_REV)
    _insert_key(db_path, "old")
    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO api_key (name, prefix, key_hash, scope, created_at) "
                    "VALUES ('old', 'x', 'h', 'read', '2026-01-01 00:00:00')")
    con.close()

    _alembic(tmp_path, db_path, "upgrade", ROTATE_REV)
    con = sqlite3.connect(db_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(api_key)")}
    assert "rotated_at" in cols
    assert con.execute("SELECT rotated_at FROM api_key").fetchone() == (None,)
    assert "WHERE revoked_at IS NULL" in _index_sql(db_path, "ux_api_key_name_active")
    idx = {r[1] for r in con.execute("PRAGMA index_list(api_key)")}
    assert {"ix_api_key_prefix", "ix_api_key_created_by"} <= idx
    con.execute("UPDATE api_key SET revoked_at='2026-02-01 00:00:00'")
    con.commit()
    con.close()
    _insert_key(db_path, "old")  # reuse after revoke works
    con = sqlite3.connect(db_path)
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO api_key (name, prefix, key_hash, scope, created_at) "
                    "VALUES ('old', 'y', 'h', 'read', '2026-01-01 00:00:00')")
    con.close()

    # Duplicate names exist, so the downgrade must refuse with a clear message.
    ini = tmp_path / "alembic.ini"
    result = subprocess.run([sys.executable, "-m", "alembic", "-c", str(ini), "downgrade", "-1"],
                            cwd=REPO_ROOT, capture_output=True, text=True)
    assert result.returncode != 0 and "Cannot downgrade" in result.stderr and "old" in result.stderr

    con = sqlite3.connect(db_path)
    con.execute("DELETE FROM api_key WHERE revoked_at IS NOT NULL")
    con.commit()
    con.close()
    _alembic(tmp_path, db_path, "downgrade", "-1")
    con = sqlite3.connect(db_path)
    assert "rotated_at" not in {r[1] for r in con.execute("PRAGMA table_info(api_key)")}
    assert _index_sql(db_path, "ux_api_key_name_active") is None
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO api_key (name, prefix, key_hash, scope, created_at) "
                    "VALUES ('old', 'z', 'h', 'read', '2026-01-01 00:00:00')")
    con.close()

    _alembic(tmp_path, db_path, "upgrade", "head")
    assert "rotated_at" in {r[1] for r in sqlite3.connect(db_path).execute("PRAGMA table_info(api_key)")}


def test_name_reuse_after_revoke_and_active_clash_rejected(app, admin_client):
    _key(app, "dup", "read")
    r = admin_client.post("/settings/api-keys", data={"name": "dup", "scope": "read"})
    assert r.status_code == 302
    with app.app_context():
        assert ApiKey.query.count() == 1
        api_keys.revoke_key(ApiKey.query.one())
    r = admin_client.post("/settings/api-keys", data={"name": "dup", "scope": "write"})
    assert r.status_code == 200
    with app.app_context():
        assert ApiKey.query.filter_by(name="dup").count() == 2
        assert ApiKey.query.filter_by(name="dup", revoked_at=None).count() == 1
    r = admin_client.post("/settings/api-keys", data={"name": "dup", "scope": "write"})
    assert r.status_code == 302
    with app.app_context():
        assert ApiKey.query.filter_by(name="dup").count() == 2


def test_db_rejects_two_active_keys_with_one_name(app):
    from sqlalchemy.exc import IntegrityError

    with app.app_context():
        for i in range(2):
            db.session.add(ApiKey(name="same", prefix=f"p{i}", key_hash="h", scope="read",
                                  created_at=datetime.utcnow()))
            if i == 0:
                db.session.commit()
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_audit_filter_tells_a_reused_name_apart(app, admin_client):
    with app.app_context():
        old, _ = api_keys.create_key("agent", "write")
        old_id = old.id
        api_keys.revoke_key(old)
        new, _ = api_keys.create_key("agent", "write")
        new_id = new.id
        for kid, path in ((old_id, "/api/v1/groups/1"), (new_id, "/api/v1/widgets/9")):
            db.session.add(ApiAudit(ts=datetime.utcnow(), api_key_id=kid, key_name="agent", method="POST",
                                    path=path, status_code=200))
        db.session.commit()
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert f'value="id:{old_id}"' in page and "agent (revoked)" in page and f'value="id:{new_id}"' in page
    only_old = admin_client.get(f"/settings?section=api&audit_key=id:{old_id}").get_data(as_text=True)
    assert "/api/v1/groups/1" in only_old and "/api/v1/widgets/9" not in only_old
    only_new = admin_client.get(f"/settings?section=api&audit_key=id:{new_id}").get_data(as_text=True)
    assert "/api/v1/widgets/9" in only_new and "/api/v1/groups/1" not in only_new


def test_rotate_key_replaces_secret_and_keeps_identity(app):
    with app.app_context():
        key, old_full = api_keys.create_key("rot", "write")
        kid, old_prefix, old_hash, created = key.id, key.prefix, key.key_hash, key.created_at
        key.last_used_at = datetime.utcnow()
        key.last_used_ip = "10.0.0.1"
        db.session.commit()
        new_full = api_keys.rotate_key(key)
        assert new_full != old_full and new_full.startswith("std_")
        row = db.session.get(ApiKey, kid)
        assert row.prefix != old_prefix and row.key_hash != old_hash
        assert (row.name, row.scope, row.created_at) == ("rot", "write", created)
        assert row.rotated_at is not None
        assert row.last_used_at is None and row.last_used_ip is None
        assert api_keys.verify(old_full) is None
        assert api_keys.verify(new_full).id == kid


def test_rotate_key_refuses_revoked(app):
    with app.app_context():
        key, _ = api_keys.create_key("gone", "read")
        api_keys.revoke_key(key)
        with pytest.raises(ValueError):
            api_keys.rotate_key(key)
        assert key.rotated_at is None


def test_rotate_route_shows_new_key_once_with_no_store(app, admin_client, client):
    kid, old_full = _key(app, "agent", "read")
    r = admin_client.post(f"/settings/api-keys/{kid}/rotate")
    assert r.status_code == 200
    assert "no-store" in r.headers["Cache-Control"] and "no-cache" in r.headers["Cache-Control"]
    html = r.get_data(as_text=True)
    assert "Key rotated" in html and "Key created" not in html
    new_full = re.search(r'id="new-api-key"[^>]*value="(std_[^"]+)"', html).group(1)
    assert new_full != old_full
    with admin_client.session_transaction() as sess:
        assert new_full not in str(dict(sess))
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert new_full not in page and new_full.split("_", 2)[2] not in page
    assert "Rotated" in page
    assert re.search(r"<td[^>]*>\d{4}-\d\d-\d\d \d\d:\d\d UTC</td>", page)  # the Rotated cell holds a date
    # The management API: old key 401, new key 200.
    assert client.get("/api/v1/whoami", headers=_bearer(old_full)).status_code == 401
    assert client.get("/api/v1/whoami", headers=_bearer(new_full)).status_code == 200


def test_settings_list_has_rotated_column_and_buttons(app, admin_client):
    kid, _ = _key(app, "listed", "read")
    rid, _ = _key(app, "dead", "read")
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert "<th class=\"px-4 py-2\">Rotated</th>" in page
    assert f"/settings/api-keys/{kid}/rotate" in page
    assert "The current key stops working immediately" in page and "listed" in page
    assert "<td class=\"px-4 py-2\">—</td>" in page  # never rotated
    admin_client.post(f"/settings/api-keys/{kid}/rotate")
    with app.app_context():
        stamp = db.session.get(ApiKey, kid).rotated_at.strftime("%Y-%m-%d %H:%M")
        api_keys.revoke_key(db.session.get(ApiKey, rid))
    page = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert stamp in page
    assert f"/settings/api-keys/{rid}/rotate" not in page and f"/settings/api-keys/{rid}/revoke" not in page


def test_rotate_revoked_or_unknown_redirects_with_flash(app, admin_client):
    kid, full = _key(app, "dead", "read")
    with app.app_context():
        api_keys.revoke_key(db.session.get(ApiKey, kid))
    for target in (kid, 9999):
        r = admin_client.post(f"/settings/api-keys/{target}/rotate")
        assert r.status_code == 302 and "section=api" in r.headers["Location"]
    with admin_client.session_transaction() as sess:
        assert any("can't be rotated" in m for _, m in sess.get("_flashes", []))
    with app.app_context():
        assert db.session.get(ApiKey, kid).rotated_at is None


def test_rotate_route_requires_admin(app, client):
    kid, full = _key(app, "x", "read")
    assert client.post(f"/settings/api-keys/{kid}/rotate").status_code == 302
    with app.app_context():
        assert api_keys.verify(full) is not None


def test_rotate_route_enforces_csrf(app, admin_client):
    kid, full = _key(app, "c", "read")
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = admin_client.post(f"/settings/api-keys/{kid}/rotate")
        assert r.status_code == 302
        with app.app_context():
            assert api_keys.verify(full) is not None  # no token, not rotated
        html = admin_client.get("/settings?section=api").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        r = admin_client.post(f"/settings/api-keys/{kid}/rotate", data={"csrf_token": token})
        assert r.status_code == 200
        with app.app_context():
            assert api_keys.verify(full) is None
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_rotate_route_does_not_log_key_material(app, admin_client, caplog):
    import logging

    kid, _ = _key(app, "secretname", "read")
    with caplog.at_level(logging.DEBUG):
        r = admin_client.post(f"/settings/api-keys/{kid}/rotate")
    full = re.search(r'id="new-api-key"[^>]*value="(std_[^"]+)"', r.get_data(as_text=True)).group(1)
    assert f"id={kid}" in caplog.text
    assert "secretname" not in caplog.text and full not in caplog.text and full.split("_")[1] not in caplog.text
