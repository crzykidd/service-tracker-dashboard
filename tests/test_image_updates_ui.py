"""Image update UI (img-03): badges, the ?updates filter, entry details, the edit block, the
Settings section and Check now. Everything reads stored state; no registry is contacted."""

import re
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

import image_update
from extensions import db
from models import ImageReference, ServiceEntry, User

D1 = "sha256:" + "a" * 64
D2 = "sha256:" + "b" * 64
VIEWS = ("/", "/tiled_dash", "/compact_dash")


def enable(on=True):
    image_update.save_settings(enabled=on)
    db.session.commit()


def add(name, ref, digest=None, info=None, host="h1", **kw):
    e = ServiceEntry(host=host, container_name=name, source="notifier", last_updated=datetime.now(),
                     image_ref=ref, image_running_digest=digest, image_info=info,
                     internalurl=f"http://{name}.lan", **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


def reference(ref, **kw):
    reg, rest = ref.split("/", 1)
    repo, tag = rest.rsplit(":", 1)
    kw.setdefault("checked_at", datetime.utcnow())
    db.session.add(ImageReference(ref=ref, registry_name=reg, repository=repo, tag=tag,
                                  last_wanted_at=datetime.utcnow(), **kw))
    db.session.commit()


def recompute_all():
    for e in ServiceEntry.query.filter(ServiceEntry.image_ref.isnot(None)):
        image_update.recompute_entry(e)
    db.session.commit()


@pytest.fixture
def seeded(app):
    """web (tag update 1.2.0, minor), db (current), moving (digest update), manual (no image)."""
    with app.app_context():
        enable()
        ids = {
            "web": add("web", "ghcr.io/o/app:1.0.0",
                       info={"version": "1.0.0", "source": "https://github.com/o/app"}),
            "db": add("db", "docker.io/library/postgres:16.1"),
            "moving": add("moving", "docker.io/library/nginx:latest", digest=D1,
                          info={"version": "1.27.2"}),
        }
        m = ServiceEntry(host=None, container_name="manual", source="manual", last_updated=datetime.now(),
                         internalurl="http://manual.lan")
        db.session.add(m)
        reference("ghcr.io/o/app:1.0.0", candidates={"tags": ["1.1.0", "1.2.0"], "patterns": {}})
        reference("docker.io/library/postgres:16.1", candidates={"tags": [], "patterns": {}})
        reference("docker.io/library/nginx:latest", remote_digest=D2,
                  remote_digest_changed_at=datetime.utcnow() - timedelta(days=2))
        db.session.commit()
        recompute_all()
        ids["manual"] = m.id
        return ids


# --- badge -----------------------------------------------------------------------------------


@pytest.mark.parametrize("view", VIEWS)
def test_badge_only_on_update_entries(admin_client, seeded, view):
    html = admin_client.get(view).get_data(as_text=True)
    assert html.count("data-image-update-badge") == 2
    assert "Newer image: 1.2.0 (minor)" in html
    assert "Image updated upstream (latest, pushed 2 days ago)" in html


@pytest.mark.parametrize("view", VIEWS)
def test_badge_and_filter_hidden_when_the_check_is_off(app, admin_client, seeded, view):
    with app.app_context():
        enable(False)
    html = admin_client.get(view + "?updates=true").get_data(as_text=True)
    assert "data-image-update-badge" not in html
    assert 'id="updatesToggle"' not in html
    # the param is ignored while off: every entry still shows
    assert "manual" in html and "db" in html


def test_badge_is_not_health(admin_client, seeded):
    html = admin_client.get("/").get_data(as_text=True)
    row = html[html.index("data-image-update-badge"):][:400]
    assert "health-" not in row
    assert 'role="img"' in html and 'aria-label="Newer image: 1.2.0 (minor)"' in html


def test_compact_details_dialog_has_badge_and_line(admin_client, seeded):
    html = admin_client.get(f"/service/{seeded['web']}/details").get_data(as_text=True)
    assert "data-image-update-badge" in html
    assert "<strong>1.2.0</strong> available (minor)" in html


# --- filter ----------------------------------------------------------------------------------


@pytest.mark.parametrize("view", VIEWS)
def test_updates_filter_lists_only_updates_and_counts(admin_client, seeded, view):
    html = admin_client.get(view + "?updates=true").get_data(as_text=True)
    assert 'id="updatesToggle"' in html and "checked" in html[html.index('id="updatesToggle"'):][:300]
    assert '<span id="updatesCount">2</span>' in html
    names = re.findall(r'(?:title|data-container)="(web|db|moving|manual)"', html)
    assert set(names) >= {"web", "moving"} and not {"db", "manual"} & set(names)


def test_updates_filter_off_by_default_and_toggle_shown(admin_client, seeded):
    html = admin_client.get("/").get_data(as_text=True)
    assert 'id="updatesToggle"' in html
    assert "checked" not in html[html.index('id="updatesToggle"'):][:300]
    assert "Updates available (" in html


def test_updates_filter_combines_with_other_filters(admin_client, seeded):
    html = admin_client.get("/compact_dash?updates=true&source=manual").get_data(as_text=True)
    assert 'title="web"' not in html and 'title="moving"' not in html
    html = admin_client.get("/compact_dash?updates=true&source=notifier").get_data(as_text=True)
    assert 'title="web"' in html and 'title="moving"' in html
    # the count follows the other filters
    html = admin_client.get("/?source=manual").get_data(as_text=True)
    assert '<span id="updatesCount">0</span>' in html


def test_view_switcher_keeps_the_updates_filter(admin_client, seeded):
    html = admin_client.get("/?updates=true").get_data(as_text=True)
    assert 'href="/tiled_dash?updates=true"' in html and 'href="/compact_dash?updates=true"' in html
    html = admin_client.get("/").get_data(as_text=True)
    assert 'href="/tiled_dash"' in html


@pytest.mark.parametrize("view", VIEWS)
def test_view_query_count_stays_flat(app, admin_client, view):
    def more(n, start):
        with app.app_context():
            enable()
            for i in range(start, start + n):
                add(f"bulk-{i}", f"ghcr.io/o/app{i}:1.0.0")
                reference(f"ghcr.io/o/app{i}:1.0.0", candidates={"tags": ["1.1.0"], "patterns": {}})
            recompute_all()

    def count():
        statements = []

        def hook(conn, cursor, statement, params, context, many):
            statements.append(statement)

        with app.app_context():
            event.listen(db.engine, "before_cursor_execute", hook)
            try:
                assert admin_client.get(view).status_code == 200
            finally:
                event.remove(db.engine, "before_cursor_execute", hook)
        return len(statements)

    more(3, 0)
    admin_client.get(view)
    few = count()
    more(25, 100)
    assert count() == few


# --- details ---------------------------------------------------------------------------------


def details(client, id_):
    return client.get(f"/service/{id_}/details").get_data(as_text=True)


def test_details_update_tag_model_with_release_notes(admin_client, seeded):
    html = details(admin_client, seeded["web"])
    assert "Update: <strong>1.2.0</strong> available (minor)" in html
    assert "checked" in html
    assert 'href="https://github.com/o/app/releases"' in html
    assert 'target="_blank" rel="noopener noreferrer"' in html[html.index("o/app/releases"):][:200]


def test_details_update_digest_model(admin_client, seeded):
    html = details(admin_client, seeded["moving"])
    assert "newer <code>latest</code> pushed 2 days ago (running 1.27.2)" in html


def test_details_current_unknown_error_pinned_and_off(app, admin_client, seeded):
    assert "Image up to date" in details(admin_client, seeded["db"])
    with app.app_context():
        u = add("unk", "docker.io/library/redis:latest")       # no running digest: old notifier
        p = add("pin", "docker.io/library/redis@sha256:" + "c" * 64)
        err = add("bad", "ghcr.io/o/bad:1.0.0")
        reference("ghcr.io/o/bad:1.0.0", checked_at=None, last_error="registry asked for a login")
        off = add("nope", "ghcr.io/o/nope:1.0.0", image_update_policy="off")
        recompute_all()
    assert "needs notifier 0.5.0 or later" in details(admin_client, u)
    assert "Pinned by digest" in details(admin_client, p)
    html = details(admin_client, err)
    assert "Could not check: registry asked for a login" in html
    assert "Image update" not in details(admin_client, off)


def test_details_rebuilt_note_is_muted(app, admin_client):
    with app.app_context():
        enable()
        e = add("pinned-tag", "docker.io/library/nginx:1.27.2", digest=D1)
        reference("docker.io/library/nginx:1.27.2", remote_digest=D2, candidates={"tags": [], "patterns": {}})
        recompute_all()
    html = details(admin_client, e)
    assert "Image up to date" in html and "rebuilt upstream" in html


def test_details_nothing_when_off_or_manual(app, admin_client, seeded):
    with app.app_context():
        enable(False)
    assert "Image update" not in details(admin_client, seeded["web"])


def test_check_now_link_is_admin_only(app, admin_client, seeded):
    assert "data-image-check" in details(admin_client, seeded["web"])
    with app.app_context():
        u = User(username="viewer", email="v@example.com", is_admin=False, is_active=True)
        u.set_password("viewer-pw-123")
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    assert c.post("/login", data={"username": "viewer", "password": "viewer-pw-123"}).status_code == 302
    html = details(c, seeded["web"])
    assert "Update: <strong>1.2.0</strong>" in html and "data-image-check" not in html
    assert c.post(f"/service/{seeded['web']}/image-update/check").status_code == 403
    assert c.post("/settings/image-updates/check").status_code == 403


# --- edit block ------------------------------------------------------------------------------


def edit_form(app, id_, **over):
    with app.app_context():
        e = db.session.get(ServiceEntry, id_)
        form = {"container_name": e.container_name, "host": e.host or "", "group_mode": "existing",
                "widget_name": "none", "image_update_form": "1", "image_update_policy": "auto",
                "image_update_scope": "",
                "image_tag_pattern": ""}
    form.update(over)
    return form


def test_edit_block_renders_for_docker_entries_only(admin_client, seeded):
    html = admin_client.get(f"/edit/{seeded['web']}").get_data(as_text=True)
    assert 'id="image-updates-block"' in html
    assert "Newer tags" in html and "Same major" in html and "Same minor" in html
    assert "Matches at the last check: 1.2.0, 1.1.0." in html
    assert 'id="image-updates-block"' not in admin_client.get(f"/edit/{seeded['manual']}").get_data(as_text=True)


def test_edit_saves_policy_scope_and_recomputes_locally(app, admin_client, seeded):
    resp = admin_client.post(f"/edit/{seeded['web']}", data=edit_form(
        app, seeded["web"], image_update_policy="tags", image_update_scope="patch"))
    assert resp.status_code == 302
    with app.app_context():
        e = db.session.get(ServiceEntry, seeded["web"])
        assert (e.image_update_policy, e.image_update_scope) == ("tags", "patch")
        assert e.image_update_state == "current"          # 1.2.0 is a minor step: out of "patch" scope
    admin_client.post(f"/edit/{seeded['web']}", data=edit_form(app, seeded["web"], image_update_policy="off"))
    with app.app_context():
        assert db.session.get(ServiceEntry, seeded["web"]).image_update_state == "off"


def test_edit_rejects_a_bad_pattern_and_changes_nothing(app, admin_client, seeded):
    resp = admin_client.post(f"/edit/{seeded['web']}", data=edit_form(
        app, seeded["web"], image_update_policy="digest", image_tag_pattern="(a+)+$", container_name="renamed"))
    assert resp.status_code == 200
    assert "Image tag pattern" in resp.get_data(as_text=True)
    resp = admin_client.post(f"/edit/{seeded['web']}", data=edit_form(
        app, seeded["web"], image_tag_pattern="[unclosed"))
    assert resp.status_code == 200
    with app.app_context():
        e = db.session.get(ServiceEntry, seeded["web"])
        assert (e.image_update_policy, e.image_tag_pattern, e.container_name) == ("auto", None, "web")


def test_edit_rejects_unknown_policy_and_scope(app, admin_client, seeded):
    for over in ({"image_update_policy": "bogus"}, {"image_update_scope": "huge"}):
        assert admin_client.post(f"/edit/{seeded['web']}",
                                 data=edit_form(app, seeded["web"], **over)).status_code == 200
    with app.app_context():
        assert db.session.get(ServiceEntry, seeded["web"]).image_update_policy == "auto"


def test_edit_saved_pattern_without_stored_candidates_applies_at_next_check(app, admin_client, seeded):
    admin_client.post(f"/edit/{seeded['web']}", data=edit_form(
        app, seeded["web"], image_tag_pattern=r"\d+\.\d+\.\d+"))
    with app.app_context():
        e = db.session.get(ServiceEntry, seeded["web"])
        assert e.image_tag_pattern == r"\d+\.\d+\.\d+" and e.image_update_state == "unknown"
    html = admin_client.get(f"/edit/{seeded['web']}").get_data(as_text=True)
    assert "saved pattern applies at the next check" in html


def test_edit_without_the_block_leaves_image_settings_alone(app, admin_client, seeded):
    with app.app_context():
        db.session.get(ServiceEntry, seeded["web"]).image_update_policy = "tags"
        db.session.commit()
    form = edit_form(app, seeded["web"])
    del form["image_update_form"]
    admin_client.post(f"/edit/{seeded['web']}", data=form)
    with app.app_context():
        assert db.session.get(ServiceEntry, seeded["web"]).image_update_policy == "tags"


# --- Settings --------------------------------------------------------------------------------


def section(html):
    start = html.index('id="section-image-updates"')
    return html[start:html.index("</section>", start)]


def test_settings_section_is_registered_under_sources(admin_client):
    html = admin_client.get("/settings").get_data(as_text=True)
    assert 'href="#image-updates" data-section="image-updates"' in html
    assert "Checks once a day" in section(html)
    assert "interval" not in section(html).lower().replace("interval_hours", "")


def test_settings_save_switch_and_scope(app, admin_client):
    resp = admin_client.post("/settings/image-updates", data={"image_update_enabled": "1",
                                                              "image_update_scope": "minor"})
    assert resp.status_code == 302 and "section=image-updates" in resp.headers["Location"]
    with app.app_context():
        assert image_update.effective_enabled() == (True, "ui")
        assert image_update.default_scope() == "minor"
    html = admin_client.get("/settings").get_data(as_text=True)
    sec = section(html)
    assert re.search(r'id="image-update-enabled"[^>]*checked', sec)
    assert '<option value="minor" selected>' in sec
    admin_client.post("/settings/image-updates", data={"image_update_scope": "minor"})
    with app.app_context():
        assert image_update.effective_enabled() == (False, "ui")


def test_settings_save_rejects_a_bad_scope(app, admin_client):
    admin_client.post("/settings/image-updates", data={"image_update_enabled": "1", "image_update_scope": "wide"})
    with app.app_context():
        assert image_update.effective_enabled() == (False, "default")


def test_settings_scope_change_recomputes_entries(app, admin_client, seeded):
    admin_client.post("/settings/image-updates", data={"image_update_enabled": "1", "image_update_scope": "patch"})
    with app.app_context():
        assert db.session.get(ServiceEntry, seeded["web"]).image_update_state == "current"


def test_settings_env_lock(app, admin_client, monkeypatch):
    monkeypatch.setenv("STD_IMAGE_UPDATE_ENABLED", "true")
    sec = section(admin_client.get("/settings").get_data(as_text=True))
    assert "data-image-update-env-lock" in sec and "STD_IMAGE_UPDATE_ENABLED" in sec
    assert re.search(r'id="image-update-enabled"[^>]*disabled', sec)
    admin_client.post("/settings/image-updates", data={"image_update_scope": "minor"})
    with app.app_context():
        assert image_update.default_scope() == "minor"
        assert image_update.effective_enabled() == (True, "env")
        assert image_update.settings_store.get_image_update_value("image_update_enabled") is None


def test_settings_status_card_and_problems(app, admin_client, seeded):
    with app.app_context():
        image_update.settings_store.set_image_update_value("image_update_last_run", {
            "at": image_update._iso(datetime.utcnow() - timedelta(hours=3)), "trigger": "schedule",
            "refs": 4, "checked": 3, "updates": 2, "errors": 1})
        add("bad", "ghcr.io/o/bad:1.0.0")
        reference("ghcr.io/o/bad:1.0.0", checked_at=None, last_error="registry asked for a login",
                  last_error_at=datetime.utcnow())
        recompute_all()
    sec = section(admin_client.get("/settings").get_data(as_text=True))
    assert "3 of 4 references checked" in sec and "2 updates found" in sec and "1 error" in sec
    assert 'data-image-update-problem="ghcr.io/o/bad:1.0.0"' in sec
    assert "registry asked for a login" in sec and "bad" in sec
    assert "data-image-check" in sec and "disabled" not in sec[sec.index("data-image-check"):][:200]


def test_settings_status_card_when_off(app, admin_client):
    sec = section(admin_client.get("/settings").get_data(as_text=True))
    assert "The check is off" in sec and 'id="image-update-problems"' not in sec
    assert re.search(r"data-image-check[^>]*disabled", sec)


def test_docker_section_hint_while_off(app, admin_client):
    assert 'id="docker-image-update-hint"' in admin_client.get("/settings").get_data(as_text=True)
    with app.app_context():
        enable()
    assert 'id="docker-image-update-hint"' not in admin_client.get("/settings").get_data(as_text=True)


# --- Check now -------------------------------------------------------------------------------


def _never_checked(app):
    with app.app_context():
        ImageReference.query.update({"checked_at": None})
        db.session.commit()


def test_check_now_entry_asks_for_confirmation_inside_the_cooldown(app, admin_client, seeded):
    image_update.reset_state()
    _never_checked(app)
    url = f"/service/{seeded['web']}/image-update/check"
    first = admin_client.post(url)
    assert first.status_code == 202 and first.get_json()["ok"] is True
    image_update._drain_pending()                                  # the run took the request
    second = admin_client.post(url)
    body = second.get_json()
    assert second.status_code == 409 and body["ok"] is False and body["confirm_required"] is True
    assert body["ago_text"] == "less than a minute ago" and "Check again anyway?" in body["message"]
    assert admin_client.post(url + "?force=1").status_code == 202
    image_update._drain_pending()
    assert admin_client.post(url, json={"force": True}).status_code == 202
    image_update._drain_pending()
    assert admin_client.post(url, data={"force": "1"}).status_code == 202
    image_update.reset_state()


def test_check_now_global_asks_for_confirmation_inside_the_cooldown(app, admin_client, seeded):
    image_update.reset_state()
    assert admin_client.post("/settings/image-updates/check").status_code == 202
    image_update._drain_pending()
    again = admin_client.post("/settings/image-updates/check")
    assert again.status_code == 409 and again.get_json()["confirm_required"] is True
    assert admin_client.post("/settings/image-updates/check?force=1").status_code == 202
    image_update.reset_state()


def test_check_now_while_a_run_is_pending_says_already_running(app, admin_client, seeded):
    image_update.reset_state()
    assert admin_client.post("/settings/image-updates/check").status_code == 202
    again = admin_client.post("/settings/image-updates/check?force=1")
    body = again.get_json()
    assert again.status_code == 202 and body["already_running"] is True and "already running" in body["message"]
    image_update.reset_state()


def test_check_now_while_off_is_refused(app, admin_client, seeded):
    with app.app_context():
        enable(False)
    resp = admin_client.post("/settings/image-updates/check")
    assert resp.status_code == 409 and resp.get_json()["ok"] is False


def test_check_now_unknown_entry_is_404(admin_client, seeded):
    assert admin_client.post("/service/99999/image-update/check").status_code == 404


def test_check_now_requires_login(client, seeded):
    resp = client.post(f"/service/{seeded['web']}/image-update/check")
    assert resp.status_code in (302, 401)


@pytest.fixture
def csrf_on(app):
    app.config["WTF_CSRF_ENABLED"] = True
    yield
    app.config["WTF_CSRF_ENABLED"] = False


def test_check_now_and_settings_save_need_csrf(app, csrf_on, seeded):
    image_update.reset_state()
    _never_checked(app)
    from tests.conftest import ADMIN_PASSWORD, ADMIN_USER

    with app.app_context():
        u = User(username=ADMIN_USER, email="a@example.com", is_admin=True, is_active=True)
        u.set_password(ADMIN_PASSWORD)
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    page = c.get("/login").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    c.post("/login", data={"username": ADMIN_USER, "password": ADMIN_PASSWORD, "csrf_token": token})
    url = f"/service/{seeded['web']}/image-update/check"
    assert c.post(url, headers={"X-CSRFToken": ""}).status_code == 400
    assert c.post("/settings/image-updates/check", headers={"X-CSRFToken": "bad"}).status_code == 400
    assert c.post(url, headers={"X-CSRFToken": token}).status_code == 202
    resp = c.post("/settings/image-updates", data={"image_update_scope": "minor"})
    assert resp.status_code == 302 and "section=image-updates" not in resp.headers["Location"]
    with app.app_context():
        assert image_update.default_scope() == "any"
    image_update.reset_state()
