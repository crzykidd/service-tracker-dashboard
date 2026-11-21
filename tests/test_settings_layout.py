"""Settings page structure: section registry, sidebar, deep links, flash placement
(design: docs/design/2026-11-20-settings-modernization.md, phase 1)."""

import re
from datetime import datetime

import pytest

import settings_sections
from extensions import db
from models import Group, InventoryStream, ServiceEntry, User


def _stream(status="pending"):
    db.session.add(InventoryStream(stream_id="dhcp", display_name="DHCP", producer="x",
                                   producer_version="1", key_type="mac", status=status))
    db.session.commit()


def _drain(client):
    """Show (and so consume) the "Logged in successfully." toast the fixture's login left."""
    client.get("/settings")
    return client


def _page(client, url="/settings"):
    return client.get(url).get_data(as_text=True)


def _section_html(html, slug):
    start = html.index(f'id="section-{slug}"')
    nxt = html.find("<section", start + 1)
    return html[start:nxt if nxt != -1 else len(html)]


def _location(resp):
    return resp.headers["Location"]


# --- registry -----------------------------------------------------------------------


def test_registry_order_and_groups():
    assert [g for g, _ in settings_sections.GROUPS] == [
        "general", "dashboard", "sources", "integrations", "access", "data"]
    assert [s for s, _, _ in settings_sections.SECTIONS] == [
        "about", "configuration", "groups", "widgets", "docker", "streams", "notifications",
        "home-assistant", "users", "api-keys", "audit-log", "backup", "deleted"]
    group_keys = {g for g, _ in settings_sections.GROUPS}
    assert {g for _, _, g in settings_sections.SECTIONS} <= group_keys
    assert settings_sections.DEFAULT == "about"


def test_resolve_slugs_aliases_and_unknown():
    for slug, _, _ in settings_sections.SECTIONS:
        assert settings_sections.resolve(slug) == slug
    assert settings_sections.resolve("info") == "about"
    assert settings_sections.resolve("exposure") == "docker"
    assert settings_sections.resolve("api") == "api-keys"
    assert settings_sections.resolve("INFO") == "about"
    for bad in (None, "", "nope", "section-about", 5):
        assert settings_sections.resolve(bad) is None


# --- sidebar + structure ------------------------------------------------------------


def test_sidebar_has_six_groups_and_thirteen_links_in_order(admin_client):
    html = _page(admin_client)
    nav = html[html.index('<nav class="settings-nav"'):html.index("</nav>", html.index('<nav class="settings-nav"'))]
    labels = re.findall(r'<h3 class="settings-nav-label">([^<]+)</h3>', nav)
    assert labels == [label for _, label in settings_sections.GROUPS]
    assert re.findall(r'href="#([a-z-]+)" data-section', nav) == [s for s, _, _ in settings_sections.SECTIONS]
    # the mobile select carries the same sections, one optgroup per group
    select = html[html.index('id="settings-nav-select"'):]
    select = select[:select.index("</select>")]
    assert select.count("<optgroup") == 6
    assert re.findall(r'<option value="([a-z-]+)"', select) == [s for s, _, _ in settings_sections.SECTIONS]


def test_each_section_once_and_no_bare_slug_ids(admin_client):
    html = _page(admin_client)
    for slug, _, _ in settings_sections.SECTIONS:
        assert html.count(f'id="section-{slug}"') == 1, slug
        assert f'id="{slug}"' not in html, slug
    assert html.count('<section id="section-') == 13


def test_non_current_sections_are_hidden_by_the_server(admin_client):
    html = _page(admin_client, "/settings?section=users")
    for slug, _, _ in settings_sections.SECTIONS:
        tag = re.search(rf'<section id="section-{slug}" class="([^"]*)"', html).group(1)
        assert ("hidden" in tag.split()) == (slug != "users"), slug


# --- deep links ---------------------------------------------------------------------


@pytest.mark.parametrize("query,expected", [
    ("", ""),
    ("?section=groups", "groups"),
    ("?section=home-assistant", "home-assistant"),
    ("?section=info", "about"),
    ("?section=exposure", "docker"),
    ("?section=api", "api-keys"),
    ("?section=bogus", ""),
    ("?audit_key=agent", "audit-log"),
    ("?preview=dhcp", "streams"),
    ("?section=users&audit_key=agent", "users"),
])
def test_initial_section(admin_client, query, expected):
    html = _page(admin_client, "/settings" + query)
    assert f'data-initial-section="{expected}"' in html


def test_root_carries_deep_link_data(admin_client):
    html = _page(admin_client)
    assert 'data-settings-url="/settings"' in html
    assert 'data-open-modal=""' in html
    assert "&#34;info&#34;: &#34;about&#34;" in html  # aliases JSON, attribute-escaped


# --- redirects carry a resolvable section ---------------------------------------------


def _redirect_section(resp):
    assert resp.status_code == 302, resp.status_code
    m = re.search(r"[?&]section=([a-z-]+)", _location(resp))
    assert m, _location(resp)
    return m.group(1)


def test_backup_and_restore_paths_redirect_to_backup(admin_client):
    posts = [
        {"action": "backup", "backup_operation": "save_on_server"},
        {"action": "backup", "backup_operation": "bogus"},
        {"action": "restore", "restore_source": "upload"},
        {"action": "restore", "restore_source": "server"},
        {"action": "restore", "restore_source": "server", "server_backup_filename": "../x.yml"},
        {"action": "restore", "restore_source": "server", "server_backup_filename": "missing.yml"},
        {"action": "restore", "restore_source": "nope"},
    ]
    for data in posts:
        assert _redirect_section(admin_client.post("/settings", data=data)) == "backup", data


def test_set_user_password_always_returns_to_users(app, admin_client):
    with app.app_context():
        uid = User.query.filter_by(username="admin").one().id
    for pw in ("abc", "longenough1"):
        resp = admin_client.post(f"/settings/users/{uid}/set_password", data={"new_password": pw})
        assert _redirect_section(resp) == "users"
    resp = admin_client.post("/settings/users/99999/set_password", data={"new_password": "longenough1"})
    assert _redirect_section(resp) == "users"


@pytest.mark.parametrize("url,data,expected", [
    ("/settings/update-check", {"update_check_enabled": "1", "update_check_interval_hours": "0"}, "about"),
    ("/settings/update-check", {"update_check_enabled": "1", "update_check_interval_hours": "12"}, "about"),
    ("/settings/exposure", {}, "docker"),
    ("/settings/api-keys", {"name": "", "scope": "read"}, "api-keys"),
    ("/settings/notifications/ha-entries", {}, "home-assistant"),
])
def test_post_routes_redirect_to_their_section(admin_client, url, data, expected):
    assert _redirect_section(admin_client.post(url, data=data)) == expected
    assert settings_sections.resolve(expected) == expected


def test_revoke_deleted_and_stream_redirects(app, admin_client):
    import api_keys

    with app.app_context():
        key, _ = api_keys.create_key("k", "read")
        kid = key.id
        _stream()
        entry = ServiceEntry(host="h", container_name="gone", last_updated=datetime.now(),
                             deleted_at=datetime.now())
        db.session.add(entry)
        db.session.commit()
        eid = entry.id
    assert _redirect_section(admin_client.post(f"/settings/api-keys/{kid}/revoke")) == "api-keys"
    assert _redirect_section(admin_client.post(f"/settings/deleted/{eid}/restore")) == "deleted"
    assert _redirect_section(admin_client.post("/settings/streams/dhcp/ignore")) == "streams"


def test_groups_save_success_redirects_to_groups(app, admin_client):
    with app.app_context():
        g = Group(group_name="A", group_sort_priority=1)
        db.session.add(g)
        db.session.commit()
        gid = g.id
    resp = admin_client.post("/settings/groups/save", data={
        f"group-{gid}-name": "A", f"group-{gid}-icon": "", f"group-{gid}-priority": "1",
        f"group-{gid}-delete": "0"})
    assert _redirect_section(resp) == "groups"


def test_groups_failed_save_rerenders_groups_section(app, admin_client):
    with app.app_context():
        db.session.add(Group(group_name="A", group_sort_priority=1))
        db.session.commit()
    resp = admin_client.post("/settings/groups/save", data={"new-name": ""})  # stale: no group ids
    assert resp.status_code == 400
    html = resp.get_data(as_text=True)
    assert 'data-initial-section="groups"' in html
    assert 'data-flash-slot="groups"' in html


def test_channel_save_error_rerenders_notifications_section(admin_client):
    resp = admin_client.post("/settings/notifications/save", data={"name": "x", "host": ""})
    assert resp.status_code == 400
    assert 'data-initial-section="notifications"' in resp.get_data(as_text=True)


# --- flash policy -------------------------------------------------------------------


def test_success_flash_is_a_toast_not_a_banner(admin_client):
    _drain(admin_client)
    resp = admin_client.post("/settings/exposure", data={}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'class="toast ' in html
    assert 'class="flash-alert' not in html
    assert "Exposure settings saved" in html[html.index('id="toast-region"'):]


def test_toast_text_drops_the_leading_pictograph(app, admin_client):
    with admin_client.session_transaction() as sess:
        sess["_flashes"] = [("success", "✅ Backup saved to server: /x")]
    html = _page(admin_client, "/settings?section=backup")
    assert "Backup saved to server: /x" in html
    assert "✅" not in html


def test_error_flash_is_a_banner_inside_its_section(admin_client):
    _drain(admin_client)
    resp = admin_client.post("/settings/api-keys", data={"name": "", "scope": "read"}, follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert 'class="flash-alert' in html and 'class="toast ' not in html
    section = _section_html(html, "api-keys")
    assert 'class="flash-alert' in section
    for other in ("about", "users", "audit-log"):
        assert 'class="flash-alert' not in _section_html(html, other)


def test_error_category_maps_to_a_banner(admin_client):
    _drain(admin_client)
    resp = admin_client.post("/settings/users/99999/set_password", data={"new_password": "longenough1"},
                             follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "User not found" in _section_html(html, "users")
    assert 'class="flash-alert flash-alert--danger"' in _section_html(html, "users")
    assert 'class="toast ' not in html


def test_warning_flash_is_an_amber_banner(admin_client):
    _drain(admin_client)
    resp = admin_client.post("/settings", data={"action": "restore", "restore_source": "upload"},
                             follow_redirects=True)
    html = resp.get_data(as_text=True)
    assert "flash-alert--warning" in _section_html(html, "backup")


def test_unknown_preview_flashes_into_streams(admin_client):
    html = _page(admin_client, "/settings?preview=nope")
    assert "That stream" in _section_html(html, "streams")
    assert 'data-flash-slot="streams"' in html


def test_flash_without_a_section_lands_in_the_page_slot(admin_client):
    with admin_client.session_transaction() as sess:
        sess["_flashes"] = [("danger", "Something broke")]
    html = _page(admin_client)  # no ?section= and no preview: the default About is shown
    assert 'data-flash-slot="page"' in html
    assert html.index('data-flash-slot="page"') < html.index('id="section-about"')


# --- moved content ------------------------------------------------------------------


def test_ha_entries_and_audit_log_live_in_their_own_sections(admin_client):
    html = _page(admin_client)
    assert "Home Assistant entries" in _section_html(html, "home-assistant")
    assert "Home Assistant entries" not in _section_html(html, "notifications")
    assert 'id="api-audit-empty"' in _section_html(html, "audit-log")
    assert "Audit log" not in _section_html(html, "api-keys")
    assert 'id="audit-filter-form"' in _section_html(html, "audit-log")
    assert 'name="section" value="audit-log"' in html
    assert 'id="stream-table"' in _section_html(html, "streams")


def test_stream_badges_in_the_sidebar(app, admin_client):
    with app.app_context():
        _stream()
    html = _page(admin_client)
    assert 'settings-nav-badge--warn" title="1 pending"' in html
