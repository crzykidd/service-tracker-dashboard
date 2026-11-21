"""Settings -> Groups: one Save for the whole table (v0.9.0)."""

import re
from datetime import datetime

import pytest

from extensions import db
from models import Group, ServiceEntry, User

URL = "/settings/groups/save"


def _groups(app, *specs):
    """Create groups from (name, icon, priority) and return their ids."""
    ids = []
    with app.app_context():
        for name, icon, priority in specs:
            g = Group(group_name=name, group_icon=icon, group_sort_priority=priority)
            db.session.add(g)
            db.session.flush()
            ids.append(g.id)
        db.session.commit()
    return ids


def _form(app, **overrides):
    """The form the browser would post for the current table, with overrides
    keyed like `name-<id>` -> value or `new-name` -> value."""
    data = {}
    with app.app_context():
        for g in Group.query.all():
            data[f"group-{g.id}-name"] = g.group_name
            data[f"group-{g.id}-icon"] = g.group_icon or ""
            data[f"group-{g.id}-priority"] = "" if g.group_sort_priority is None else str(g.group_sort_priority)
            data[f"group-{g.id}-delete"] = "0"
    data.update(overrides)
    return data


def _state(app):
    with app.app_context():
        return {g.group_name: (g.group_icon, g.group_sort_priority) for g in Group.query.all()}


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _, m in sess.get("_flashes", [])]


def test_updates_several_rows_at_once(app, admin_client):
    a, b, c = _groups(app, ("A", None, 1), ("B", None, 2), ("C", "c.png", 3))
    resp = admin_client.post(URL, data=_form(app, **{
        f"group-{a}-name": "A2", f"group-{b}-priority": "9", f"group-{c}-icon": ""}))
    assert resp.status_code == 302 and resp.headers["Location"].endswith("section=groups")
    assert _state(app) == {"A2": (None, 1), "B": (None, 9), "C": (None, 3)}
    assert "Saved: 3 updated." in _flashes(admin_client)[-1]


def test_add_update_and_delete_in_one_save(app, admin_client):
    a, b = _groups(app, ("A", None, 1), ("B", None, 2))
    admin_client.post(URL, data=_form(app, **{
        f"group-{a}-priority": "5", f"group-{b}-delete": "1",
        "new-name": "N", "new-icon": "n.png", "new-priority": "-2"}))
    assert _state(app) == {"A": (None, 5), "N": ("n.png", -2)}
    assert "Saved: 1 updated, 1 added, 1 deleted." in _flashes(admin_client)[-1]


def test_no_changes(app, admin_client):
    _groups(app, ("A", "a.png", 1))
    admin_client.post(URL, data=_form(app))
    assert _flashes(admin_client)[-1] == "No changes."


def test_name_swap_in_one_save(app, admin_client):
    a, b = _groups(app, ("A", None, 1), ("B", None, 2))
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-name": "B", f"group-{b}-name": "A"}))
    assert resp.status_code == 302
    with app.app_context():
        assert db.session.get(Group, a).group_name == "B"
        assert db.session.get(Group, b).group_name == "A"


def test_new_group_takes_name_of_deleted_row(app, admin_client):
    a, = _groups(app, ("A", None, None))
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-delete": "1", "new-name": "A"}))
    assert resp.status_code == 302
    with app.app_context():
        assert [g.group_name for g in Group.query.all()] == ["A"]


def test_blank_new_row_is_ignored(app, admin_client):
    _groups(app, ("A", None, 1))
    admin_client.post(URL, data=_form(app, **{"new-icon": "x.png", "new-priority": "4"}))
    assert _state(app) == {"A": (None, 1)}


def test_duplicate_name_is_400_writes_nothing_and_keeps_input(app, admin_client):
    a, b = _groups(app, ("A", None, 1), ("B", None, 2))
    resp = admin_client.post(URL, data=_form(app, **{
        f"group-{a}-priority": "77", f"group-{b}-name": "A", "new-name": "typed-new"}))
    assert resp.status_code == 400
    assert _state(app) == {"A": (None, 1), "B": (None, 2)}
    html = resp.get_data(as_text=True)
    assert "Another group is already named" in html
    assert 'value="77"' in html and 'value="typed-new"' in html
    assert "data-unsaved-start-dirty" in html


def test_duplicate_of_new_row_name(app, admin_client):
    _groups(app, ("A", None, 1))
    resp = admin_client.post(URL, data=_form(app, **{"new-name": "A"}))
    assert resp.status_code == 400


def test_blank_existing_name_is_400(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-name": "  "}))
    assert resp.status_code == 400
    assert "name is required" in resp.get_data(as_text=True)
    assert _state(app) == {"A": (None, 1)}


def test_overlong_name_is_400(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-name": "x" * 101}))
    assert resp.status_code == 400


def test_non_numeric_priority_is_400(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-priority": "abc", "new-name": "N"}))
    assert resp.status_code == 400
    assert _state(app) == {"A": (None, 1)}
    assert "must be a number" in resp.get_data(as_text=True)


def test_negative_and_zero_priority_allowed(app, admin_client):
    a, b = _groups(app, ("A", None, 1), ("B", None, 1))
    admin_client.post(URL, data=_form(app, **{f"group-{a}-priority": "-3", f"group-{b}-priority": "0"}))
    assert _state(app) == {"A": (None, -3), "B": (None, 0)}


def test_priority_zero_renders_in_input(app, admin_client):
    _groups(app, ("A", None, 0))
    html = admin_client.get("/settings?section=groups").get_data(as_text=True)
    assert re.search(r'name="group-\d+-priority" value="0"', html)


def test_delete_of_group_with_active_entry_is_refused(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    with app.app_context():
        db.session.add(ServiceEntry(container_name="svc", host="h", last_updated=datetime.now(), group_id=a))
        db.session.commit()
    resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-delete": "1", "new-name": "N"}))
    assert resp.status_code == 400
    assert _state(app) == {"A": (None, 1)}
    assert "Cannot delete a group that has entries" in resp.get_data(as_text=True)


def test_delete_detaches_soft_deleted_entries(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    with app.app_context():
        db.session.add(ServiceEntry(container_name="svc", host="h", last_updated=datetime.now(), group_id=a, deleted_at=datetime.now()))
        db.session.commit()
    admin_client.post(URL, data=_form(app, **{f"group-{a}-delete": "1"}))
    with app.app_context():
        assert Group.query.count() == 0
        assert ServiceEntry.query.one().group_id is None


def test_unknown_group_id_is_400_and_applies_nothing(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    data = _form(app, **{f"group-{a}-priority": "8", "group-9999-name": "ghost",
                         "group-9999-priority": "", "group-9999-icon": ""})
    resp = admin_client.post(URL, data=data)
    assert resp.status_code == 400
    assert _state(app) == {"A": (None, 1)}


def test_group_added_after_page_load_is_400(app, admin_client):
    _groups(app, ("A", None, 1))
    data = _form(app)
    _groups(app, ("Late", None, 2))
    resp = admin_client.post(URL, data=data)
    assert resp.status_code == 400
    assert _state(app) == {"A": (None, 1), "Late": (None, 2)}


def test_per_row_priority_wipe_is_gone(app, admin_client):
    """The old per-row Save posted only group_id, which set priority to NULL."""
    a, = _groups(app, ("A", None, 5))
    admin_client.post(URL, data=_form(app, **{f"group-{a}-name": "A2"}))
    assert _state(app) == {"A2": (None, 5)}
    html = admin_client.get("/settings?section=groups").get_data(as_text=True)
    assert "/update_group" not in html and "/add_group" not in html and "/delete_group" not in html
    assert html.count('id="groups-form"') == 1


def test_form_wraps_every_input_in_one_form(app, admin_client):
    _groups(app, ("A", None, 5))
    html = admin_client.get("/settings?section=groups").get_data(as_text=True)
    start = html.index('id="section-groups"')
    section = html[start:html.index("<section", start + 1)]
    assert section.count("<form") == 1
    form = section[section.index("<form"):section.index("</form>")]
    for needle in ("group-", "new-name", "csrf_token"):
        assert needle in form


def test_non_admin_refused(app):
    with app.app_context():
        u = User(username="bob", email="b@example.com", is_admin=False, is_active=True)
        u.set_password("pw-bob")
        db.session.add(u)
        db.session.commit()
    a, = _groups(app, ("A", None, 1))
    c = app.test_client()
    c.post("/login", data={"username": "bob", "password": "pw-bob"})
    resp = c.post(URL, data={f"group-{a}-name": "hacked"})
    assert resp.status_code in (302, 401, 403)
    assert _state(app) == {"A": (None, 1)}


def test_anonymous_refused(app):
    _groups(app, ("A", None, 1))
    resp = app.test_client().post(URL, data={"new-name": "x"})
    assert resp.status_code in (302, 401)
    assert _state(app) == {"A": (None, 1)}


def test_csrf_enforced(app, admin_client):
    a, = _groups(app, ("A", None, 1))
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        resp = admin_client.post(URL, data=_form(app, **{f"group-{a}-name": "A2"}),
                                 headers={"Referer": "http://localhost/settings?section=groups"})
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert resp.status_code == 302
    assert _state(app) == {"A": (None, 1)}


@pytest.mark.parametrize("old", ["/update_group", "/add_group", "/delete_group"])
def test_old_per_row_routes_are_gone(admin_client, old):
    assert admin_client.post(old, data={"group_id": "1"}).status_code == 404
