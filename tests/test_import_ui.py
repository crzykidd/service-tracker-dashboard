"""Import UI (backup phase 4): upload -> stream mapping -> grouped preview -> apply -> summary.

The page is parsed back the way a browser would read it (`Page.form()` returns what the form would
submit), so the tests exercise the template's checkbox names and default ticks, not a hand-built
POST. The engine itself is covered by tests/test_import_engine.py.
"""

import json
import os
import re

import pytest

import importer
from extensions import db
from models import Group, NotificationChannel, ServiceEntry, User
from tests.import_helpers import Page, post_form, section, token_of, upload
from tests.test_import_engine import _put, docker_rec, minimal, stream_rec


def preview(client, doc, name="export.json"):
    token = token_of(upload(client, doc, name))
    resp = client.get(f"/settings/import/{token}")
    assert resp.status_code == 200
    return token, Page(resp.get_data(as_text=True))


def _local_entries(app, register):
    """grafana (nothing set) and sonarr (a description of its own), registered by the notifier."""
    assert register(host="h1", container_name="grafana").status_code == 200
    assert register(host="h1", container_name="sonarr").status_code == 200
    with app.app_context():
        ServiceEntry.query.filter_by(container_name="sonarr").one().description = "mine"
        db.session.commit()


def _doc():
    return minimal(
        entries=[docker_rec("grafana", description="from file"), docker_rec("sonarr", description="theirs"),
                 docker_rec("ghost", description="not here")],
        groups=[{"name": "Monitoring"}],
        users=[{"username": "carol", "email": "carol@example.com", "is_admin": False, "is_active": True}])


# --- upload and the preview -----------------------------------------------------------------------


def test_upload_redirects_to_the_token_page_and_groups_render_in_order(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    html = page.html
    assert 'id="section-import"' in html and 'aria-current="page"' in html
    keys = re.findall(r'data-group-key="([^"]+)"', html)
    assert keys == ["docker", "groups", "users"]
    assert page.ticked("sel-entry:docker:h1/grafana")                      # missing: ticked
    assert not page.ticked("sel-entry:docker:h1/sonarr")                   # differs: unticked
    assert not page.ticked("create-entry:docker:h1/ghost")                 # not found: off
    assert not page.ticked("create-user:carol")                            # user: off
    assert page.ticked("sel-group:Monitoring")                             # a missing group is created: ticked
    # per-field boxes: missing ticked, differs disabled in fill mode
    assert page.ticked("field-entry:docker:h1/grafana", "description")
    assert page.box("field-entry:docker:h1/sonarr", "description")["disabled"]
    assert page.ticked("mode", "fill") and not page.ticked("mode", "overwrite")
    assert "Create user (no password)" in html and "Created users cannot sign in" in html
    assert 'name="fingerprint"' in html
    # nothing was written by looking
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description is None
        assert User.query.count() == 1 or User.query.filter_by(username="carol").count() == 0


def test_preview_is_a_full_settings_page_with_backup_current(admin_client):
    _, page = preview(admin_client, minimal(groups=[{"name": "Solo"}]))
    assert 'class="settings-nav"' in page.html and 'href="/settings?section=backup"' in page.html
    assert 'data-imp-form' in page.html and "js/settings/import.js" in page.html


def test_expired_or_foreign_token_redirects_with_a_banner(app, admin_client):
    token, _ = preview(admin_client, minimal(groups=[{"name": "Solo"}]))
    resp = admin_client.get("/settings/import/not-a-real-token-1234", follow_redirects=True)
    assert "This import expired. Upload the file again." in section(resp.get_data(as_text=True))
    # someone else's token
    other = app.test_client()
    with app.app_context():
        u = User(username="other", email="o@example.com", is_admin=True, is_active=True)
        u.set_password("other-password-1")
        db.session.add(u)
        db.session.commit()
    other.post("/login", data={"username": "other", "password": "other-password-1"})
    resp = other.get(f"/settings/import/{token}", follow_redirects=True)
    assert "This import expired" in resp.get_data(as_text=True)
    for path in ("map", "apply", "cancel"):
        assert admin_client.post(f"/settings/import/zzzzzzzzzzzzzzzzzz/{path}").status_code == 302
    assert other.post(f"/settings/import/{token}/apply").status_code == 302
    # the owner's staged file is untouched by the other user's attempts
    assert admin_client.get(f"/settings/import/{token}").status_code == 200


def test_parse_error_shows_a_banner_in_the_backup_section(admin_client):
    resp = upload(admin_client, b"this: is: not: valid: [", "bad.yml", follow=True)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Could not import bad.yml" in section(html)
    resp = upload(admin_client, {"format": "nope"}, "x.json", follow=True)
    assert "not an STD export" in section(resp.get_data(as_text=True))
    resp = admin_client.post("/settings/import", data={}, follow_redirects=True)
    assert "Choose a file" in section(resp.get_data(as_text=True))


def test_a_too_big_upload_is_refused_before_reading(admin_client, monkeypatch):
    monkeypatch.setattr(importer, "MAX_UPLOAD_BYTES", 100)
    resp = upload(admin_client, b"x" * 300_000, "big.yml", follow=True)
    assert "larger than" in section(resp.get_data(as_text=True))


def test_cancel_deletes_the_staged_file(app, admin_client):
    token = token_of(upload(admin_client, minimal(groups=[{"name": "Solo"}])))
    path = os.path.join(importer.staging_dir(), f"{token}.json")
    assert os.path.isfile(path)
    resp = admin_client.post(f"/settings/import/{token}/cancel")
    assert resp.status_code == 302 and "section=backup" in resp.headers["Location"]
    assert not os.path.exists(path)
    assert admin_client.get(f"/settings/import/{token}").status_code == 302


# --- stream mapping -------------------------------------------------------------------------------


def test_remap_a_stream_and_rerender(app, admin_client, client):
    _put(client, app)                                       # a local `dhcp` stream, pending
    doc = minimal(streams=[{"stream_id": "other", "display_name": "Other", "key_type": "mac",
                            "producer": "p", "status": "enabled", "network_include": ["Home"]}])
    token, page = preview(admin_client, doc)
    assert 'name="map-other"' in page.html and "Not present yet" in page.html
    resp = admin_client.post(f"/settings/import/{token}/map", data={"map-other": "dhcp"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'value="dhcp" selected' in html
    assert "stream:other" in html                           # the settings row now matches the local stream
    # skipping it
    resp = admin_client.post(f"/settings/import/{token}/map", data={"map-other": ""}, follow_redirects=True)
    assert "Skipped in the stream mapping" in resp.get_data(as_text=True)


# --- apply ----------------------------------------------------------------------------------------


def test_fill_mode_writes_only_missing_fields_and_lists_what_is_still_to_do(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    items = page.form()
    items += [["create-user:carol", "1"]]
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200 and 'id="import-summary"' in html
    assert "Import applied" in html and "Still to do" in html
    assert "carol" in html and "Set a password" in html and "ingest key" in html
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description == "from file"
        assert ServiceEntry.query.filter_by(container_name="sonarr").one().description == "mine"
        assert ServiceEntry.query.filter_by(container_name="ghost").count() == 0       # off by default
        carol = User.query.filter_by(username="carol").one()
        assert carol.has_password is False
    assert admin_client.get(f"/settings/import/{token}").status_code == 302           # staged file is gone


def test_overwrite_mode_with_a_ticked_differs_field(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    items = [i for i in page.form() if i[0] != "mode"] + [["mode", "overwrite"]]
    items += [["sel-entry:docker:h1/sonarr", "1"], ["field-entry:docker:h1/sonarr", "description"],
              ["fieldset", "entry:docker:h1/sonarr"]]
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:600]
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="sonarr").one().description == "theirs"
    assert "Fields overwritten" in resp.get_data(as_text=True)


def test_an_unticked_field_is_not_written_even_when_the_row_is_ticked(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    items = [i for i in page.form() if i[0] != "field-entry:docker:h1/grafana"]
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    assert resp.status_code == 200
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description is None


def test_ambiguous_target_and_import_as_new_post_through_the_form(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    items = page.form() + [["create-entry:docker:h1/ghost", "1"]]
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    assert resp.status_code == 200
    with app.app_context():
        ghost = ServiceEntry.query.filter_by(container_name="ghost").one()
        assert ghost.source == "manual" and ghost.description == "not here"


def test_a_stale_apply_is_409_with_the_banner_and_the_ticks_kept(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    items = page.form() + [["create-user:carol", "1"]]
    with app.app_context():                                # the world changes under the preview
        ServiceEntry.query.filter_by(container_name="grafana").one().description = "someone set it"
        db.session.commit()
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    html = resp.get_data(as_text=True)
    assert resp.status_code == 409
    assert "Something changed since the preview" in section(html, "import")
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description == "someone set it"
        assert User.query.filter_by(username="carol").count() == 0
    again = Page(html)
    assert again.ticked("create-user:carol")               # the operator's tick survived
    # grafana is no longer missing, so its row is a differs row now (unticked) and the page is usable
    assert not again.ticked("sel-entry:docker:h1/sonarr")
    resp = post_form(admin_client, f"/settings/import/{token}/apply", again.form())
    assert resp.status_code == 200 and "Import applied" in resp.get_data(as_text=True)
    with app.app_context():
        assert User.query.filter_by(username="carol").count() == 1


def test_an_outdated_form_from_another_tab_is_refused(app, admin_client, register):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())
    old_items = page.form()
    admin_client.get(f"/settings/import/{token}")           # a second tab replans (same plan, same fp)
    items = [i if i[0] != "fingerprint" else ["fingerprint", "0" * 64] for i in old_items]
    resp = post_form(admin_client, f"/settings/import/{token}/apply", items)
    assert resp.status_code == 409 and "out of date" in resp.get_data(as_text=True)


def test_an_apply_error_rerenders_with_nothing_changed(app, admin_client, register, monkeypatch):
    _local_entries(app, register)
    token, page = preview(admin_client, _doc())

    def boom(*a, **k):
        raise importer.ImportApplyError("Nothing was changed: boom")

    monkeypatch.setattr(importer, "apply", boom)
    resp = post_form(admin_client, f"/settings/import/{token}/apply", page.form())
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400 and "Nothing was changed: boom" in section(html, "import")
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().description is None


def test_summary_offers_the_run_again_form_for_a_server_file(app, admin_client, register):
    _local_entries(app, register)
    path = os.path.join(app.config["backup_path"], "2026-11-20-std_export.json")
    with open(path, "w") as f:
        json.dump(_doc(), f)
    try:
        token = token_of(admin_client.post("/settings/import", data={"server_file": "2026-11-20-std_export.json"}))
        page = Page(admin_client.get(f"/settings/import/{token}").get_data(as_text=True))
        resp = post_form(admin_client, f"/settings/import/{token}/apply", page.form())
        assert 'name="server_file" value="2026-11-20-std_export.json"' in resp.get_data(as_text=True)
    finally:
        os.remove(path)


# --- server files (the confinement the old restore had) ---------------------------------------------


@pytest.mark.parametrize("name", ["../x.yml", "sub/x.yml", "/etc/passwd", "notes.txt", "x.sqlite3",
                                  "2026-11-20-std_backup.sqlite3", "missing.yml"])
def test_server_file_rejects_bad_names(admin_client, name):
    resp = admin_client.post("/settings/import", data={"server_file": name}, follow_redirects=True)
    assert resp.status_code == 200
    assert "is not an export in the backup folder" in section(resp.get_data(as_text=True))


def test_server_file_accepts_a_plain_export_and_a_legacy_name(app, admin_client):
    folder = app.config["backup_path"]
    names = {"sectest.yml": "[]\n", "2026-11-20-std_export.json": json.dumps(minimal(groups=[{"name": "G"}]))}
    for n, body in names.items():
        with open(os.path.join(folder, n), "w") as f:
            f.write(body)
    try:
        for n in names:
            resp = admin_client.post("/settings/import", data={"server_file": n})
            assert resp.status_code == 302 and "/settings/import/" in resp.headers["Location"], n
    finally:
        for n in names:
            os.remove(os.path.join(folder, n))


def test_server_file_cannot_escape_through_a_symlink(app, admin_client, tmp_path):
    outside = tmp_path / "outside.yml"
    outside.write_text("[]\n")
    link = os.path.join(app.config["backup_path"], "link.yml")
    os.symlink(outside, link)
    try:
        resp = admin_client.post("/settings/import", data={"server_file": "link.yml"}, follow_redirects=True)
        assert "is not an export in the backup folder" in section(resp.get_data(as_text=True))
    finally:
        os.remove(link)


def test_backup_section_has_the_import_card_and_the_menu_entry(app, admin_client):
    folder = app.config["backup_path"]
    path = os.path.join(folder, "2026-11-20-std_export.yml")
    with open(path, "w") as f:
        f.write("[]\n")
    try:
        html = section(admin_client.get("/settings?section=backup").get_data(as_text=True))
    finally:
        os.remove(path)
    assert 'id="backup-import"' in html and "Preview import" in html and 'name="import_file"' in html
    assert 'name="server_file"' in html and "Import&hellip;" in html
    assert "Restore Service Data" not in html and "Save Full Backup" not in html and 'name="action"' not in html


# --- legacy and users ---------------------------------------------------------------------------------


def test_a_legacy_v0_upload_goes_through_the_same_flow(app, admin_client, register):
    import yaml
    _local_entries(app, register)
    legacy = yaml.safe_dump([{"host": "h1", "container_name": "grafana", "internalurl": "http://grafana:3000",
                              "last_updated": "2026-01-01 00:00:00", "last_api_update": "2026-01-01 00:00:00"}]).encode()
    token, page = preview(admin_client, legacy, "2026-11-19-std_backup.yml")
    assert "old YAML backup" in page.html and page.ticked("sel-entry:docker:h1/grafana")
    resp = post_form(admin_client, f"/settings/import/{token}/apply", page.form())
    assert resp.status_code == 200
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="grafana").one().internalurl == "http://grafana:3000"


def test_users_created_without_a_password_show_the_tag_and_cannot_log_in(app, admin_client):
    token, page = preview(admin_client, _doc())
    resp = post_form(admin_client, f"/settings/import/{token}/apply", page.form() + [["create-user:carol", "1"]])
    assert resp.status_code == 200
    users = section(admin_client.get("/settings?section=users").get_data(as_text=True), "users")
    assert users.count("No password set, cannot sign in") == 1 and "carol" in users
    fresh = app.test_client()
    for attempt in ("", "carol", "!unset"):
        r = fresh.post("/login", data={"username": "carol", "password": attempt})
        assert r.status_code == 200


# --- the old restore is gone --------------------------------------------------------------------------


@pytest.mark.parametrize("data", [
    {"action": "restore", "restore_source": "server", "server_backup_filename": "x.yml"},
    {"action": "restore", "restore_source": "upload"},
    {"action": "backup", "backup_operation": "download_all"},
    {"action": "backup", "backup_operation": "save_on_server"},
])
def test_the_old_restore_and_backup_posts_do_nothing(app, admin_client, data):
    with app.app_context():
        before = ServiceEntry.query.count()
    resp = admin_client.post("/settings", data=data)
    assert resp.status_code == 405
    assert not os.path.exists(os.path.join(app.config["backup_path"], "backup.yml"))
    with app.app_context():
        assert ServiceEntry.query.count() == before


def test_the_old_restore_cannot_overwrite_an_entry(app, admin_client, register):
    import io

    import yaml
    _local_entries(app, register)
    payload = yaml.dump([{"host": "h1", "container_name": "sonarr", "description": "overwritten"}])
    admin_client.post("/settings", data={"action": "restore", "restore_source": "upload", "restore_scope": "all",
                                         "restore_file": (io.BytesIO(payload.encode()), "b.yaml")},
                      content_type="multipart/form-data")
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="sonarr").one().description == "mine"


def test_channels_and_groups_rows_render_without_secrets(app, admin_client):
    doc = minimal(notification_channels=[{"name": "home", "type": "mqtt", "enabled": True, "secret_set": True,
                                          "config": {"host": "mqtt.lan", "port": 1883}}],
                  groups=[{"name": "Media"}])
    token, page = preview(admin_client, doc)
    assert "channel:home" in page.html and not page.ticked("create-channel:home")
    resp = post_form(admin_client, f"/settings/import/{token}/apply", [["create-channel:home", "1"]] +
                     [i for i in page.form() if i[0] in ("csrf_token", "fingerprint", "mode")])
    assert resp.status_code == 200
    with app.app_context():
        ch = NotificationChannel.query.one()
        assert ch.enabled is False and ch.secret is None
        assert Group.query.count() == 0                    # the unticked group row was not applied
    assert "home" in resp.get_data(as_text=True)


def test_a_stream_record_for_a_not_enabled_stream_is_waiting_and_not_selectable(app, admin_client, client):
    _put(client, app)
    doc = minimal(streams=[{"stream_id": "dhcp", "display_name": "DHCP", "key_type": "mac", "producer": "p", "status": "enabled",
                            "network_include": ["Home"]}], entries=[stream_rec()])
    _, page = preview(admin_client, doc)
    assert "imp-pill--waiting" in page.html
    assert not [i for i in page.inputs if i["name"] and i["name"].endswith("aa:bb:cc:00:00:01")]


def test_a_locked_record_is_never_created_locked_and_the_summary_says_so(app, admin_client):
    # The old Restore had a "static only" scope; import's lock rules replace it (design 7.5):
    # "Import as new" never sets the lock, and the summary says to re-run after the container registers.
    from tests.import_helpers import import_flow
    doc = minimal(entries=[docker_rec("lockedbox", is_static=True, description="d")])
    resp = import_flow(admin_client, doc)
    assert "static lock" in resp.get_data(as_text=True)
    with app.app_context():
        e = ServiceEntry.query.filter_by(container_name="lockedbox").one()
        assert e.is_static is False and e.source == "manual"


def test_an_unlocked_local_entry_is_locked_by_a_ticked_row(app, admin_client, register):
    from tests.import_helpers import import_flow
    assert register(host="h1", container_name="plex").status_code == 200
    import_flow(admin_client, minimal(entries=[docker_rec("plex", is_static=True)]))
    with app.app_context():
        assert ServiceEntry.query.filter_by(container_name="plex").one().is_static is True
