"""Compact view: expand button per tile and the details dialog route (PRD 13.7)."""

# The shared fixtures come from test_streams by import, which ruff reads as unused/redefined.
# ruff: noqa: F401, F811

from datetime import datetime

from extensions import db
from models import ServiceEntry
from tests.test_streams import enabled_stream, keys, op, put, stream_entries
from tests.test_streams_ui import PUMP_KEY


def _docker(app, name="web", host="em-host1"):
    with app.app_context():
        e = ServiceEntry(
            host=host, container_name=name, source="notifier", internalurl="http://i",
            last_updated=datetime.now(),
            networks=[{"name": "frontend", "aliases": ["web-alias"]}],
            published_ports=[{"container_port": 8080, "protocol": "tcp", "host_port": 18080}],
        )
        db.session.add(e)
        db.session.commit()
        return e.id


def test_compact_page_has_one_expand_button_per_entry(app, admin_client):
    ids = [_docker(app, "a", "h1"), _docker(app, "b", "h2")]
    html = admin_client.get("/compact_dash").get_data(as_text=True)
    for i in ids:
        assert f'data-compact-expand="{i}"' in html
    assert html.count("data-compact-expand=") == 2
    # The click must bubble to compact_details.js's document listener; the tile's own
    # onclick already ignores .compact-expand-btn, so the button must not stop it.
    import re
    for btn in re.findall(r'<button[^>]*data-compact-expand=[^>]*>', html):
        assert "stopPropagation" not in btn
    assert 'id="compact-details"' in html and "compact_details.js" in html
    assert 'aria-label="Show details for a"' in html


def test_details_route_renders_facts_and_health_panel(app, admin_client):
    eid = _docker(app)
    r = admin_client.get(f"/service/{eid}/details")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "em-host1" in html and "frontend" in html and "web-alias" in html
    assert "8080/tcp" in html and "18080" in html
    assert "data-health-detail" in html and f"/service/{eid}/health" in html
    assert "data-compact-delete" in html and "Edit" in html


def test_details_route_shows_a_stream_entrys_mac(app, admin_client, put, op):
    enabled_stream(app, put, op)
    with app.app_context():
        eid = stream_entries()[PUMP_KEY].id
    html = admin_client.get(f"/service/{eid}/details").get_data(as_text=True)
    assert PUMP_KEY in html and "Stream" in html


def test_static_entry_has_no_delete_button(app, admin_client):
    eid = _docker(app)
    with app.app_context():
        db.session.get(ServiceEntry, eid).is_static = True
        db.session.commit()
    html = admin_client.get(f"/service/{eid}/details").get_data(as_text=True)
    assert "data-compact-delete" not in html


def test_details_route_needs_login(app, client):
    eid = _docker(app)
    r = client.get(f"/service/{eid}/details")
    assert r.status_code in (302, 401)


def test_details_route_404_for_deleted_or_unknown(app, admin_client):
    eid = _docker(app)
    with app.app_context():
        db.session.get(ServiceEntry, eid).deleted_at = datetime.now()
        db.session.commit()
    assert admin_client.get(f"/service/{eid}/details").status_code == 404
    assert admin_client.get("/service/99999/details").status_code == 404
