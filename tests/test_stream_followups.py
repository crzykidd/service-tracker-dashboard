"""Inventory-stream follow-ups (0.10.0): widened link matching, default checks,
dry-run counts, the pending flag, detail facts, HA source column, add/edit wording."""

# Shared fixtures come from test_streams by import (ruff reads them as unused/redefined).
# ruff: noqa: F401, F811

import pytest

from extensions import db
from models import InventoryStream, ServiceEntry, StreamLinkOffer
from tests.test_streams import (
    enabled_stream,
    keys,
    manual,
    op,
    put,
    snapshot,
    stream_entries,
)

PUMP = "aa:bb:cc:00:00:01"
PRINTER = "aa:bb:cc:00:00:04"


def _checks(app, key):
    with app.app_context():
        e = stream_entries()[key]
        return sorted((c.check_type, c.target, c.enabled) for c in e.service_checks)


# --- matching --------------------------------------------------------------------


def test_offer_endpoint_lists_a_host_entry_match(app, put, op, manual):
    mid = manual("Some Device", host="printer")
    enabled_stream(app, put, op)
    items = op("GET", "/streams/dhcp/offers").get_json()["items"]
    assert [o["entry_id"] for o in items] == [mid]


def test_edit_page_banner_and_link_picker_mention_the_cleared_host(admin_client, app, put, op, manual):
    mid = manual("box", host="printer")
    enabled_stream(app, put, op)
    html = admin_client.get(f"/edit/{mid}").get_data(as_text=True)
    assert "Its host <code>printer</code> will be cleared; the stream reports its address." in html
    assert "The machine that runs this container, if the notifier should take this entry over later." in html


def test_link_picker_offered_for_a_hosted_manual_entry_and_clears_host(admin_client, app, put, manual):
    mid = manual("box", host="somewhere")
    put()
    html = admin_client.get(f"/edit/{mid}").get_data(as_text=True)
    assert 'id="stream-link"' in html and "will be cleared" in html
    assert admin_client.post(f"/edit/{mid}/stream-link", data={"target": f"dhcp:{PRINTER}"}).status_code == 302
    with app.app_context():
        e = db.session.get(ServiceEntry, mid)
        assert e.source == "stream" and e.host is None


def test_add_page_host_wording(admin_client):
    html = admin_client.get("/add").get_data(as_text=True)
    assert "Docker host (optional)" in html and "server01.example.com" not in html
    assert "Leave blank for a device, VM or anything not running in Docker." in html


# --- purge keeps the snapshot -----------------------------------------------------


def test_purge_keeps_the_snapshot_but_delete_removes_the_row(app, put, op):
    enabled_stream(app, put, op)
    op("POST", "/streams/dhcp/disable", json={"cleanup": "purge"})
    with app.app_context():
        s = InventoryStream.query.one()
        assert s.snapshot is not None and s.last_counts is None
    assert op("GET", "/streams/dhcp/preview").status_code == 200
    assert op("DELETE", "/streams/dhcp").status_code == 200
    with app.app_context():
        assert InventoryStream.query.count() == 0


# --- Settings -> Streams ----------------------------------------------------------


def test_pending_stream_shows_would_counts_and_enabled_does_not(admin_client, app, put, op, manual):
    manual("nas")
    put()
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "would: created 9, link offers 1" in html
    assert "stream-waiting" not in html
    op("POST", "/streams/dhcp/enable")
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "stream-would-counts" not in html


def test_stream_without_a_snapshot_says_waiting(admin_client, app, put, op):
    put()
    op("POST", "/streams/dhcp/ignore")                       # discards the snapshot
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "Waiting for the next snapshot" in html


def test_dialog_states_what_each_mode_removes(admin_client, app, put, op):
    enabled_stream(app, put, op)
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "The stored snapshot is kept in every mode" in html
    assert "stored snapshot, its" in html


# --- pending flag in the header -----------------------------------------------------


def test_pending_flag_shown_hidden_and_anonymous(admin_client, client, app, put, op):
    assert "settings-pending-streams" not in admin_client.get("/").get_data(as_text=True)
    put()
    for path in ("/", "/tiled_dash", "/compact_dash", "/add"):
        html = admin_client.get(path).get_data(as_text=True)
        assert 'id="settings-pending-streams"' in html, path
        assert "1 inventory stream pending review" in html
        assert "section=streams" in html and "ring-amber-400" in html
    op("POST", "/streams/dhcp/enable")
    assert "settings-pending-streams" not in admin_client.get("/").get_data(as_text=True)
    assert "settings-pending-streams" not in client.get("/login").get_data(as_text=True)


def test_pending_flag_anonymous_with_a_pending_stream(client, put):
    put()
    assert "settings-pending-streams" not in client.get("/login").get_data(as_text=True)


# --- default checks ---------------------------------------------------------------


def test_default_checks_on_new_entries(app, put, op):
    r = op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True}})
    assert r.status_code == 404                              # no stream yet
    put()
    r = op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True, "tcp_port": 22}})
    assert r.status_code == 200 and r.get_json()["default_checks"] == {"ping": True, "tcp_port": 22}
    op("POST", "/streams/dhcp/enable")
    assert _checks(app, PUMP) == [("ping", "10.0.40.21", True), ("tcp", "10.0.40.21:22", True)]
    assert _checks(app, "aa:bb:cc:00:00:09") == [("ping", "fd00::9", True), ("tcp", "[fd00::9]:22", True)]


def test_default_checks_skip_entries_without_an_ip(app, put, op):
    body = snapshot()
    body["items"].append({"key": "aa:bb:cc:00:00:f9", "name": "no-ip"})
    put(body)
    op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True}})
    op("POST", "/streams/dhcp/enable")
    assert _checks(app, "aa:bb:cc:00:00:f9") == []


def test_apply_to_existing_adds_missing_without_duplicates(app, put, op):
    enabled_stream(app, put, op)
    assert _checks(app, PUMP) == []
    op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True, "tcp_port": 80}})
    r = op("POST", "/streams/dhcp/default-checks/apply")
    assert r.status_code == 200
    body = r.get_json()
    assert body["entries"] == 10 and body["entries_changed"] == 10 and body["checks_added"] == 20
    again = op("POST", "/streams/dhcp/default-checks/apply").get_json()
    assert again["checks_added"] == 0 and again["entries_changed"] == 0
    assert len(_checks(app, PUMP)) == 2


def test_apply_skips_an_entry_that_already_has_a_check_of_the_kind(app, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        from check_form import new_service_check, validate_service_check
        e = stream_entries()[PUMP]
        values, _ = validate_service_check({"name": "mine", "check_type": "ping", "target": "my.host",
                                            "interval": 60})
        e.checks.append(new_service_check(values))
        db.session.commit()
    op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True, "tcp_port": 22}})
    op("POST", "/streams/dhcp/default-checks/apply")
    assert sorted(t for t, _, _ in _checks(app, PUMP)) == ["ping", "tcp"]
    with app.app_context():
        ping = [c for c in stream_entries()[PUMP].service_checks if c.check_type == "ping"]
        assert len(ping) == 1 and ping[0].target == "my.host"


@pytest.mark.parametrize("value", [{"tcp_port": 0}, {"tcp_port": 70000}, {"tcp_port": "x"},
                                   {"ping": "yes"}, {"bogus": 1}, "ping"])
def test_default_checks_validation(app, put, op, value):
    put()
    assert op("PATCH", "/streams/dhcp", json={"default_checks": value}).status_code == 400


def test_default_checks_null_clears_and_list_reports_pending(app, put, op):
    put()
    op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True}})
    listing = op("GET", "/streams").get_json()
    assert listing["pending"] == 1 and listing["items"][0]["default_checks"]["ping"] is True
    op("PATCH", "/streams/dhcp", json={"default_checks": None})
    assert op("GET", "/streams/dhcp").get_json()["default_checks"] == {"ping": False, "tcp_port": None}
    op("POST", "/streams/dhcp/enable")
    assert op("GET", "/streams").get_json()["pending"] == 0


def test_default_checks_ui_routes(admin_client, app, put, op):
    enabled_stream(app, put, op)
    r = admin_client.post("/settings/streams/dhcp/default-checks", data={"ping": "1", "tcp_port": "443"})
    assert r.status_code == 302
    assert op("GET", "/streams/dhcp").get_json()["default_checks"] == {"ping": True, "tcp_port": 443}
    admin_client.post("/settings/streams/dhcp/default-checks/apply")
    assert len(_checks(app, PUMP)) == 2
    html = admin_client.get("/settings?section=streams").get_data(as_text=True)
    assert "Default checks" in html and "Apply to existing entries" in html
    admin_client.post("/settings/streams/dhcp/default-checks", data={"tcp_port": "abc"})
    assert op("GET", "/streams/dhcp").get_json()["default_checks"]["tcp_port"] == 443


def test_default_checks_api_audit_and_openapi(app, put, op):
    from mgmt_openapi import OPERATIONS
    assert any(o.path == "/streams/{stream_id}/default-checks/apply" for o in OPERATIONS)
    put()
    assert op("PATCH", "/streams/dhcp", json={"default_checks": {"ping": True, "x": 1}}).status_code == 400
    assert op("POST", "/streams/dhcp/default-checks/apply", key="read").status_code == 403


# --- detail facts, HA source column -------------------------------------------------


def test_detail_panel_shows_ip_mac_network(admin_client, app, put, op):
    enabled_stream(app, put, op)
    html = admin_client.get("/").get_data(as_text=True)
    # The Dashboard expand row shows them in the shared facts column (the health
    # column hides its own copy), the tile drawer in the same partial.
    row = html[html.index('class="health-expand-row'):]
    assert 'expand-facts' in row and "10.0.40.21" in row and "aa:bb:cc:00:00:01" in row
    assert 'data-entry-facts' not in row
    tiled = admin_client.get("/tiled_dash").get_data(as_text=True)
    assert "10.0.40.21" in tiled and "aa:bb:cc:00:00:01" in tiled


def test_ha_picker_groups_entries_by_source_and_the_search_matches_it(admin_client, app, put, op, manual):
    manual("hand")
    enabled_stream(app, put, op)
    html = admin_client.get("/settings?section=home-assistant").get_data(as_text=True)
    assert '<th class="py-2 px-3">Source</th>' not in html          # the Source column became groups
    assert html.count('data-ha-source="DHCP"') == 10 and 'data-ha-source="Manual"' in html
    assert "Search by name, host or group" in html
