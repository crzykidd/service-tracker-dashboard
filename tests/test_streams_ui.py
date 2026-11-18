"""Streams UI: Settings -> Streams, stream entries in the views, edit page (PRD 18.8)."""

# The shared fixtures come from test_streams by import, which ruff reads as unused/redefined.
# ruff: noqa: F401, F811

import re

import pytest

from extensions import db
from models import (
    ApiKey,
    InventoryBlock,
    InventoryStream,
    ServiceEntry,
    StreamLinkOffer,
)
from tests.test_streams import (
    enabled_stream,
    keys,
    manual,
    op,
    put,
    snapshot,
    stream_entries,
)

NAS_KEY = "aa:bb:cc:00:00:07"
PUMP_KEY = "aa:bb:cc:00:00:01"


def _entry_id(app, key=PUMP_KEY):
    with app.app_context():
        return stream_entries()[key].id


def _stream_status(app):
    with app.app_context():
        return InventoryStream.query.filter_by(stream_id="dhcp").one().status


def _flashes(client):
    with client.session_transaction() as sess:
        return [m for _, m in sess.get("_flashes", [])]


# --- API key scope ------------------------------------------------------------------


def test_scope_select_offers_ingest_and_creating_one_works(admin_client, app):
    html = admin_client.get("/settings?section=api").get_data(as_text=True)
    assert '<option value="ingest">Ingest (sidecars)</option>' in html
    r = admin_client.post("/settings/api-keys", data={"name": "sidecar", "scope": "ingest"})
    assert r.status_code == 200
    with app.app_context():
        assert ApiKey.query.filter_by(name="sidecar").one().scope == "ingest"


# --- Settings -> Streams ------------------------------------------------------------


def test_streams_tab_empty_and_docker_row(admin_client, register):
    register(container_name="svc-a")
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert 'id="section-streams"' in html and "Docker (register)" in html
    assert 'id="stream-empty"' in html
    row = re.search(r'id="stream-row-docker">(.*?)</tr>', html, re.S).group(1)
    assert "<td class=\"px-3 py-2\">1</td>" in row and "never" not in row      # one entry, registered just now


def test_pending_stream_is_highlighted_with_item_count(admin_client, put):
    put()
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "New stream waiting:" in html and "to import\n    10 items" in html
    assert 'data-stream-status="pending"' in html
    assert ">Enable</button>" in html and ">Ignore</button>" in html and ">Preview</a>" in html
    assert "Disable…</button>" not in html          # only an enabled stream can be disabled


def test_preview_lists_items_with_actions_and_writes_nothing(admin_client, app, put, manual):
    manual("nas")
    put()
    html = admin_client.get("/settings?section=streams&preview=dhcp").get_data(as_text=True)
    assert 'id="stream-preview"' in html
    assert html.count('class="preview-action"') == 10
    assert 'data-action="created"' in html and 'data-action="link_offer"' in html
    with app.app_context():
        assert ServiceEntry.query.filter_by(source="stream").count() == 0


def test_preview_of_unknown_stream_flashes(admin_client):
    html = admin_client.get("/settings?section=streams&preview=nope").get_data(as_text=True)
    assert 'id="stream-preview"' not in html and "exist" in html and "That stream" in html


def test_enable_ignore_and_the_409s(admin_client, app, put, op):
    put()
    r = admin_client.post("/settings/streams/dhcp/enable")
    assert r.status_code == 302 and "section=streams" in r.headers["Location"]
    assert _stream_status(app) == "enabled"
    assert "Enabled stream 'DHCP'" in " ".join(_flashes(admin_client))
    with app.app_context():
        assert len(stream_entries()) == 10
    admin_client.post("/settings/streams/dhcp/enable")                  # already enabled: 409 as a flash
    assert any("Cannot enable" in m for m in _flashes(admin_client))
    assert _stream_status(app) == "enabled"


def test_ignore_discards_the_snapshot(admin_client, app, put):
    put()
    assert admin_client.post("/settings/streams/dhcp/ignore").status_code == 302
    assert _stream_status(app) == "ignored"
    with app.app_context():
        assert InventoryStream.query.one().snapshot is None


def test_unknown_stream_is_404(admin_client):
    assert admin_client.post("/settings/streams/nope/enable").status_code == 404


@pytest.mark.parametrize("cleanup,expect_active,expect_all,expect_source", [
    ("keep", 10, 10, "stream"),
    ("soft_delete", 0, 10, "stream"),
    ("purge", 0, 0, None),
])
def test_disable_cleanups(admin_client, app, put, op, cleanup, expect_active, expect_all, expect_source):
    enabled_stream(app, put, op)
    r = admin_client.post("/settings/streams/dhcp/disable", data={"cleanup": cleanup})
    assert r.status_code == 302 and _stream_status(app) == "disabled"
    with app.app_context():
        assert ServiceEntry.active().count() == expect_active
        assert ServiceEntry.query.count() == expect_all
        if expect_source:
            assert ServiceEntry.query.first().source == expect_source


def test_disable_purge_can_clear_the_block_list(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    assert admin_client.post(f"/api/v1/entries/{eid}/delete", json={"block": True}).status_code == 200
    admin_client.post("/settings/streams/dhcp/disable", data={"cleanup": "purge"})
    with app.app_context():
        assert InventoryBlock.query.count() == 1                        # purge alone keeps blocks
    enabled_after = admin_client.post("/settings/streams/dhcp/enable")
    assert enabled_after.status_code == 302
    admin_client.post("/settings/streams/dhcp/disable", data={"cleanup": "purge", "clear_blocks": "1"})
    with app.app_context():
        assert InventoryBlock.query.count() == 0


def test_bad_cleanup_flashes_and_changes_nothing(admin_client, app, put, op):
    enabled_stream(app, put, op)
    admin_client.post("/settings/streams/dhcp/disable", data={"cleanup": "bogus"})
    assert any("cleanup must be one of" in m for m in _flashes(admin_client))
    assert _stream_status(app) == "enabled"


@pytest.mark.parametrize("cleanup,entries_left,manual_left", [("keep", 10, 10), ("soft_delete", 10, 10), ("purge", 0, 0)])
def test_delete_stream_cleanups(admin_client, app, put, op, cleanup, entries_left, manual_left):
    enabled_stream(app, put, op)
    assert admin_client.post("/settings/streams/dhcp/delete", data={"cleanup": cleanup}).status_code == 302
    with app.app_context():
        assert InventoryStream.query.count() == 0
        assert ServiceEntry.query.count() == entries_left
        assert ServiceEntry.query.filter_by(source="manual").count() == manual_left
        assert ServiceEntry.active().count() == (10 if cleanup == "keep" else 0)


def test_delete_drops_blocks_and_offers_with_the_stream(admin_client, app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    admin_client.post(f"/api/v1/entries/{eid}/delete", json={"block": True})
    admin_client.post("/settings/streams/dhcp/delete", data={"cleanup": "keep"})
    with app.app_context():
        assert InventoryBlock.query.count() == 0 and StreamLinkOffer.query.count() == 0


def test_dialog_shows_counts_customised_names_and_cleanup_choices(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    admin_client.post(f"/edit/{eid}", data={"container_name": "Pump renamed", "widget_name": "none"})
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    dialog = re.search(r'<dialog id="stream-dialog-dhcp".*?</dialog>', html, re.S).group(0)
    assert "<strong>10</strong> entries" in dialog and "10 active" in dialog
    for value in ("keep", "soft_delete", "purge"):
        assert f'name="cleanup" value="{value}"' in dialog
    assert 'name="clear_blocks"' in dialog and "Also clear the block list" in dialog
    assert "Pump renamed" in dialog and "renamed" in dialog and "1 customised entry" in dialog
    assert "Disable…</button>" in html and "Delete…</button>" in html


def test_update_display_name_and_filters(admin_client, app, put, op):
    put()
    r = admin_client.post("/settings/streams/dhcp/update", data={
        "display_name": "Leases", "network_include": "CrzyIoT\nCrzyMedia", "network_exclude": "Guest, Other"})
    assert r.status_code == 302
    with app.app_context():
        s = InventoryStream.query.one()
        assert (s.display_name, s.network_include, s.network_exclude) == \
            ("Leases", ["CrzyIoT", "CrzyMedia"], ["Guest", "Other"])
    admin_client.post("/settings/streams/dhcp/update", data={"display_name": "Leases"})   # empty textareas clear
    with app.app_context():
        s = InventoryStream.query.one()
        assert s.network_include is None and s.network_exclude is None
    admin_client.post("/settings/streams/dhcp/update", data={"display_name": "  "})
    assert any("display_name" in m for m in _flashes(admin_client))
    with app.app_context():
        assert InventoryStream.query.one().display_name == "Leases"


def test_blocked_list_and_unblock(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    admin_client.post(f"/api/v1/entries/{eid}/delete", json={"block": True})
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert 'id="stream-blocks"' in html and PUMP_KEY in html and ">Unblock</button>" in html
    with app.app_context():
        block_id = InventoryBlock.query.one().id
    assert admin_client.post(f"/settings/streams/dhcp/blocks/{block_id}/unblock").status_code == 302
    with app.app_context():
        assert InventoryBlock.query.count() == 0
    admin_client.post(f"/settings/streams/dhcp/blocks/{block_id}/unblock")
    assert any("No block" in m for m in _flashes(admin_client))


def test_offers_listed_and_accept_decline(admin_client, app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert 'id="stream-offers"' in html and ">Accept</button>" in html and ">Decline</button>" in html
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    r = admin_client.post(f"/settings/streams/dhcp/offers/{offer_id}/accept")
    assert r.status_code == 302
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "stream"
    assert admin_client.post("/settings/streams/dhcp/offers/999/decline").status_code == 302
    assert any("No link offer" in m for m in _flashes(admin_client))
    assert admin_client.post(f"/settings/streams/dhcp/offers/{offer_id}/frobnicate").status_code == 404


def test_decline_creates_a_separate_entry(admin_client, app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    admin_client.post(f"/settings/streams/dhcp/offers/{offer_id}/decline")
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "manual"
        assert NAS_KEY in stream_entries()


# --- Permissions and CSRF -----------------------------------------------------------

ROUTES = [
    ("/settings/streams/dhcp/enable", {}),
    ("/settings/streams/dhcp/ignore", {}),
    ("/settings/streams/dhcp/disable", {"cleanup": "keep"}),
    ("/settings/streams/dhcp/delete", {"cleanup": "keep"}),
    ("/settings/streams/dhcp/update", {"display_name": "x"}),
    ("/settings/streams/dhcp/blocks/1/unblock", {}),
    ("/settings/streams/dhcp/offers/1/accept", {}),
    ("/settings/streams/dhcp/offers/1/decline", {}),
    ("/edit/1/stream-link", {"target": "dhcp:k"}),
]


@pytest.mark.parametrize("path,data", ROUTES)
def test_anonymous_cannot_post(client, app, put, path, data):
    put()
    r = client.post(path, data=data)
    assert r.status_code in (302, 401) and "/login" in r.headers.get("Location", "/login")
    assert _stream_status(app) == "pending"


@pytest.mark.parametrize("path,data", ROUTES)
def test_non_admin_cannot_post(app, put, path, data):
    from models import User
    put()
    with app.app_context():
        u = User(username="viewer", email="v@example.com", is_admin=False, is_active=True)
        u.set_password("viewer-pw-1")
        db.session.add(u)
        db.session.commit()
    c = app.test_client()
    assert c.post("/login", data={"username": "viewer", "password": "viewer-pw-1"}).status_code == 302
    assert c.post(path, data=data).status_code == 403
    assert _stream_status(app) == "pending"


@pytest.mark.parametrize("path,data", ROUTES)
def test_csrf_is_enforced(app, admin_client, put, path, data):
    put()
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = admin_client.post(path, data=data)
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert r.status_code == 302                      # bounced back with a "stale form" flash
    assert any("stale" in m for m in _flashes(admin_client))
    assert _stream_status(app) == "pending"          # nothing ran
    with app.app_context():
        assert InventoryStream.query.count() == 1 and ServiceEntry.query.count() == 0


def test_csrf_token_is_accepted(app, admin_client, put):
    put()
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        r = admin_client.post("/settings/streams/dhcp/enable", data={"csrf_token": token})
    finally:
        app.config["WTF_CSRF_ENABLED"] = False
    assert r.status_code == 302 and _stream_status(app) == "enabled"


# --- Views --------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/", "/tiled_dash", "/compact_dash"])
def test_stream_entry_shows_the_stream_pill_on_every_view(admin_client, app, put, op, path):
    enabled_stream(app, put, op)
    html = admin_client.get(path).get_data(as_text=True)
    assert html.count('class="status-pill stream-pill') == 10
    assert '<span class="stream-pill-name">DHCP</span>' in html
    assert "Manual" not in re.sub(r"<option.*?</option>", "", html)       # no grey Manual pill for streams
    assert "shelly-pump" in html


def test_dashboard_shows_manual_pill_for_manual_and_not_stream_pill(admin_client, manual):
    manual("hand-made")
    html = admin_client.get("/").get_data(as_text=True)
    assert "Manual" in html and "stream-pill" not in html.replace(".stream-pill", "")


@pytest.mark.parametrize("path", ["/", "/tiled_dash", "/compact_dash"])
def test_missing_marker(admin_client, app, put, op, path):
    enabled_stream(app, put, op)
    body = snapshot()
    body["items"] = body["items"][1:]                     # shelly-pump leaves the snapshot
    assert put(body).status_code == 200
    html = admin_client.get(path).get_data(as_text=True)
    assert html.count('class="stream-missing"') == 1
    assert "stream-pill stream-pill-missing" in html


@pytest.mark.parametrize("path", ["/", "/tiled_dash", "/compact_dash"])
def test_source_filter_lists_each_stream_and_filters(admin_client, app, put, op, manual, path):
    manual("hand-made")
    enabled_stream(app, put, op)
    html = admin_client.get(path).get_data(as_text=True)
    assert '<option value="stream:dhcp" >DHCP</option>' in html
    both = admin_client.get(path + "?source=stream:dhcp").get_data(as_text=True)
    assert "hand-made" not in both and "shelly-pump" in both
    assert 'value="stream:dhcp" selected' in both
    only_manual = admin_client.get(path + "?source=manual").get_data(as_text=True)
    assert "hand-made" in only_manual and "shelly-pump" not in only_manual
    other = admin_client.get(path + "?source=stream:other").get_data(as_text=True)      # unknown stream: no rows
    assert "shelly-pump" not in other
    junk = admin_client.get(path + "?source=stream:../x").get_data(as_text=True)         # not a stream id: all
    assert "shelly-pump" in junk and "hand-made" in junk


def test_delete_buttons_carry_the_stream_flag(admin_client, app, put, op, manual):
    manual("hand-made")
    enabled_stream(app, put, op)
    for path in ("/", "/tiled_dash"):
        html = admin_client.get(path).get_data(as_text=True)
        assert 'data-stream="1"' in html and 'data-stream="0"' in html


# --- Delete with block (the dialog's path) --------------------------------------------


def test_delete_allow_readding_lets_the_next_snapshot_restore_it(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    assert admin_client.post(f"/api/v1/entries/{eid}/delete", json={}).status_code == 200
    with app.app_context():
        assert InventoryBlock.query.count() == 0
    put()
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).deleted_at is None            # restored by key


def test_delete_dont_readd_blocks_the_key(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    assert admin_client.post(f"/api/v1/entries/{eid}/delete", json={"block": True}).status_code == 200
    with app.app_context():
        b = InventoryBlock.query.one()
        assert b.key == PUMP_KEY and b.blocked_by == "admin"
    put()
    with app.app_context():
        assert db.session.get(ServiceEntry, eid).deleted_at is not None
        assert PUMP_KEY not in {e.stream_key for e in ServiceEntry.active()}


def test_edit_page_delete_form_blocks_too(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    r = admin_client.post(f"/edit/{eid}", data={"delete": "1", "delete_confirmation": "shelly-pump", "block": "1"})
    assert r.status_code == 302
    with app.app_context():
        assert InventoryBlock.query.count() == 1


def test_block_on_a_non_stream_entry_is_ignored(admin_client, manual, app):
    mid = manual("hand-made")
    assert admin_client.post(f"/api/v1/entries/{mid}/delete", json={"block": True}).status_code == 200
    with app.app_context():
        assert InventoryBlock.query.count() == 0


# --- Edit page ----------------------------------------------------------------------


def test_stream_entry_edit_page_is_read_only_for_observations(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    html = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'id="stream-info"' in html
    for text in ("aa:bb:cc:00:00:01", "10.0.40.21", "CrzyIoT", "reservation_comment", "boiler room", "DHCP"):
        assert text in html
    assert 'name="host"' not in html                       # no host field for a stream entry
    assert 'name="container_name"' in html                 # the name stays editable
    assert 'data-stream="1"' in html


def test_stream_entry_rename_sets_ui_edit_and_keeps_observations(admin_client, app, put, op):
    enabled_stream(app, put, op)
    eid = _entry_id(app)
    admin_client.post(f"/edit/{eid}", data={"container_name": "Pump", "widget_name": "none",
                                            "mac": "ff:ff:ff:ff:ff:ff", "ip": "1.2.3.4"})
    with app.app_context():
        e = db.session.get(ServiceEntry, eid)
        assert (e.container_name, e.name_source, e.mac, e.ip) == ("Pump", "ui_edit", PUMP_KEY, "10.0.40.21")


def test_manual_entry_with_an_offer_shows_the_banner(admin_client, app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    html = admin_client.get(f"/edit/{mid}").get_data(as_text=True)
    assert "data-link-offer=" in html and "Convert</button>" in html and "Keep separate</button>" in html
    assert NAS_KEY in html and 'id="stream-link"' not in html
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    # Convert posts to the offer route and comes back to the edit page.
    form = re.search(r'action="([^"]*offers/%d/accept)".*?name="next" value="([^"]+)"' % offer_id, html, re.S)
    assert form
    r = admin_client.post(form.group(1), data={"next": form.group(2)})
    assert r.status_code == 302 and f"/edit/{mid}" in r.headers["Location"]
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "stream"
    assert "data-link-offer=" not in admin_client.get(f"/edit/{mid}").get_data(as_text=True)


def test_manual_entry_keep_separate(admin_client, app, put, op, manual):
    mid = manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    r = admin_client.post(f"/settings/streams/dhcp/offers/{offer_id}/decline", data={"next": f"/edit/{mid}"})
    assert f"/edit/{mid}" in r.headers["Location"]
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "manual" and NAS_KEY in stream_entries()


def test_offer_next_redirect_is_same_site_only(admin_client, app, put, op, manual):
    manual("nas")
    enabled_stream(app, put, op)
    with app.app_context():
        offer_id = StreamLinkOffer.query.one().id
    r = admin_client.post(f"/settings/streams/dhcp/offers/{offer_id}/decline", data={"next": "https://evil.example/x"})
    assert "evil.example" not in r.headers["Location"]


def test_manual_entry_without_offer_can_link_by_hand(admin_client, app, put, manual):
    mid = manual("my-printer")
    put()                                                  # pending: every item is unmatched
    html = admin_client.get(f"/edit/{mid}").get_data(as_text=True)
    assert 'id="stream-link"' in html and "Link to stream item…" in html
    assert 'value="dhcp:aa:bb:cc:00:00:04"' in html and "data-link-offer=" not in html
    r = admin_client.post(f"/edit/{mid}/stream-link", data={"target": "dhcp:aa:bb:cc:00:00:04"})
    assert r.status_code == 302
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert (e.source, e.stream_key, e.ip, e.container_name) == ("stream", "aa:bb:cc:00:00:04", "10.0.10.31", "my-printer")
    assert 'id="stream-link"' not in admin_client.get(f"/edit/{mid}").get_data(as_text=True)


def test_link_by_hand_errors_flash(admin_client, app, put, manual):
    mid = manual("my-printer")
    put()
    admin_client.post(f"/edit/{mid}/stream-link", data={"target": ""})
    assert any("Choose a stream item" in m for m in _flashes(admin_client))
    admin_client.post(f"/edit/{mid}/stream-link", data={"target": "dhcp:nope"})
    assert any("not in the stream" in m for m in _flashes(admin_client))
    with app.app_context():
        assert db.session.get(ServiceEntry, mid).source == "manual"


def test_docker_entry_edit_page_has_no_stream_ui(admin_client, register, app):
    register(container_name="svc-a")
    with app.app_context():
        eid = ServiceEntry.query.one().id
    html = admin_client.get(f"/edit/{eid}").get_data(as_text=True)
    assert 'id="stream-info"' not in html and 'id="stream-link"' not in html and 'name="host"' in html
