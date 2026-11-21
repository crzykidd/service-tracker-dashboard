"""Settings -> Notifications cards + channel dialog, and the grouped Home Assistant
section (design: docs/design/2026-11-20-settings-modernization.md, phase 2)."""

# Shared fixtures come from test_streams by import (ruff reads them as unused/redefined).
# ruff: noqa: F401, F811

import re
from datetime import datetime

from extensions import db
from models import ServiceEntry
from tests.test_notifications import FORM, SECRET, _add
from tests.test_streams import (  # noqa: F401
    enabled_stream,
    keys,
    manual,
    op,
    put,
    snapshot,
)


def _page(client, url="/settings"):
    return client.get(url).get_data(as_text=True)


def _dialog(html, dialog_id):
    start = html.index(f'<dialog id="{dialog_id}"')
    return html[start:html.index("</dialog>", start)]


# --- channel dialog ---------------------------------------------------------------------


def test_channel_save_error_reopens_the_dialog_with_the_banner_inside(app, admin_client):
    resp = admin_client.post("/settings/notifications/save", data={**FORM, "port": "70000"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 400 and SECRET not in html
    assert 'data-open-modal="channel-modal"' in html
    modal = _dialog(html, "channel-modal")
    assert 'class="flash-alert' in modal and "config.port" in modal
    assert re.search(r'id="nf-port"[^>]*aria-invalid="true"', modal)
    assert "data-unsaved-start-dirty" in modal
    assert 'value="70000"' in modal                      # what was typed is kept
    assert 'aria-invalid="true"' not in modal.split('id="nf-host"')[1].split(">")[0]
    # the section itself carries no second copy of the banner
    section = html[html.index('id="section-notifications"'):html.index('<dialog id="purge-dialog"')]
    assert 'class="flash-alert' not in section


def test_advanced_block_opens_for_an_error_inside_it(app, admin_client):
    html = _page_post(admin_client, {**FORM, "keepalive": "1"})
    assert re.search(r'<details class="std-modal-advanced" open>', html)


def _page_post(client, data):
    return client.post("/settings/notifications/save", data=data).get_data(as_text=True)


def test_cards_dialog_and_menu_markup(app, admin_client):
    cid = _add(app, name="mqtt-main", secret=SECRET)
    html = _page(admin_client)
    assert 'id="notification-list"' in html and f'data-channel-id="{cid}"' in html
    assert f'data-notification-edit="{cid}"' in html and f'data-notification-test="{cid}"' in html
    assert "Purge MQTT and Home Assistant" in html and 'role="switch"' in html
    assert 'id="notification-channels-data"' in html and SECRET not in html
    assert 'id="channel-modal"' in html and 'id="nf-test"' in html and "Save channel" in html
    assert "<table" not in html[html.index('id="section-notifications"'):html.index('id="section-home-assistant"')]


def test_empty_state_has_an_add_button(admin_client):
    html = _page(admin_client)
    assert 'id="notification-empty"' in html and "data-notification-add" in html


# --- Home Assistant ----------------------------------------------------------------------


def _docker(name, publish=False):
    e = ServiceEntry(host="h1", container_name=name, source="notifier", last_updated=datetime.now(),
                     ha_publish=publish)
    db.session.add(e)
    db.session.commit()


def test_ha_groups_order_counts_and_stream_rows(app, admin_client, put, op, manual):
    with app.app_context():
        _docker("web", publish=True)
        _docker("db")
    manual("hand")
    enabled_stream(app, put, op)
    html = _page(admin_client, "/settings?section=home-assistant")
    keys_in_order = re.findall(r'data-group-key="([^"]+)"', html)
    assert keys_in_order[:3] == ["docker", "manual", "stream-dhcp"]
    toggles = re.findall(r'settings-group-count">([^<]+)<', html)
    assert toggles[:3] == ["1 of 2", "0 of 1", "0 of 10"]
    assert html.count('data-ha-source="DHCP"') == 10
    assert 'aria-label="Publish all Docker entries"' in html
    assert 'data-collapsed="true"' in html and "settings-savebar" in html
    assert "1 of 13" in html          # saved published count


def test_ha_warning_ignores_a_disabled_channel(app, admin_client):
    _add(app, name="off", enabled=False, config={"host": "m", "ha_discovery": True})
    html = _page(admin_client, "/settings?section=home-assistant")
    assert "No channel publishes discovery" in html
    assert "off</strong> (disabled)" not in html          # no discovery line while none is live


def test_ha_status_line_when_an_enabled_channel_has_discovery(app, admin_client):
    _add(app, name="live", config={"host": "m", "ha_discovery": True})
    _add(app, name="off", enabled=False, config={"host": "m2", "ha_discovery": True})
    html = _page(admin_client, "/settings?section=home-assistant")
    assert "No channel publishes discovery" not in html
    assert "<strong>live</strong>" in html and "<strong>off</strong> (disabled)" in html


def test_ha_nav_dot_only_when_ticked_and_no_live_channel(app, admin_client):
    with app.app_context():
        _docker("web", publish=True)
    assert "settings-nav-dot" in _page(admin_client)
    _add(app, name="live", config={"host": "m", "ha_discovery": True})
    assert "settings-nav-dot" not in _page(admin_client)


def test_save_ha_entries_redirects_to_its_section(app, admin_client):
    with app.app_context():
        _docker("web")
        eid = ServiceEntry.query.one().id
    resp = admin_client.post("/settings/notifications/ha-entries",
                             data={"ha_entry_ids": [str(eid)], "ha_publish": [str(eid)]})
    assert resp.status_code == 302 and "section=home-assistant" in resp.headers["Location"]
