"""One exposure badge per layer (v0.9.0 step 7)."""

import re
from datetime import datetime
from types import SimpleNamespace as NS

from extensions import db
from models import ServiceEntry, ServiceExposure
from view_helpers import exposure_layers


def _x(layer, hostname=None, tls=None, path=None, auth=None):
    return NS(layer=layer, hostname=hostname, tls=tls, path_prefix=path, auth=auth)


def test_two_traefik_rows_one_layer():
    out = exposure_layers([_x("traefik", "a.me", True), _x("traefik", "a.lan", False)])
    assert len(out) == 1 and out[0]["layer"] == "traefik" and out[0]["count"] == 2
    assert [r["route"] for r in out[0]["routes"]] == ["a.me", "a.lan"]
    assert out[0]["title"] == "traefik — 2 routes\na.me (TLS)\na.lan"


def test_mixed_layers_keep_first_seen_order():
    out = exposure_layers([_x("traefik"), _x("cloudflare"), _x("traefik")])
    assert [(o["layer"], o["count"]) for o in out] == [("traefik", 2), ("cloudflare", 1)]


def test_flags_aggregate_as_any():
    out = exposure_layers([_x("traefik"), _x("traefik", "h", True, auth="authelia")])[0]
    assert out["tls"] and out["labeled"] and out["auth"]
    plain = exposure_layers([_x("traefik", auth="none"), _x("traefik", auth="")])[0]
    assert not (plain["tls"] or plain["labeled"] or plain["auth"])


def test_duplicate_routes_deduplicated_but_counted():
    out = exposure_layers([_x("traefik", "a", True, "/x"), _x("traefik", "a", True, "/x")])[0]
    assert out["count"] == 2 and [r["route"] for r in out["routes"]] == ["a/x"]
    assert out["title"] == "traefik \u2014 2 routes\na/x (TLS)"


def test_web_and_websecure_same_host_one_line():
    out = exposure_layers([_x("traefik", "a.me", False), _x("traefik", "a.me", True)])[0]
    assert out["title"] == "traefik \u2014 2 routes\na.me (TLS)"


def test_empty():
    assert exposure_layers([]) == [] and exposure_layers(None) == []


def _seed():
    def add(name, rows):
        e = ServiceEntry(host="h", container_name=name, source="notifier",
                         internalurl="http://i", last_updated=datetime.now())
        db.session.add(e)
        db.session.flush()
        for layer, host, tls in rows:
            db.session.add(ServiceExposure(service_entry_id=e.id, layer=layer, hostname=host, tls=tls))
    add("twotraefik", [("traefik", "s.crzynet.me", True), ("traefik", None, False)])
    add("four", [("traefik", None, None), ("cloudflare", None, None),
                 ("nginx", None, None), ("caddy", None, None)])
    db.session.commit()


def _tile(html, name):
    start = html.index(f'title="{name}"')
    return html[start:html.index("tile-drawer", start)]


def test_one_logo_on_tiled_and_dashboard(app, admin_client):
    with app.app_context():
        _seed()
    for url in ("/tiled_dash", "/"):
        html = admin_client.get(url).get_data(as_text=True)
        seg = html[html.index("twotraefik"):]
        seg = seg[:seg.index("exposure-icons") + 1500]
        assert seg.count("exposure/traefik.svg") == 1 and "&times;" not in seg
    html = admin_client.get("/tiled_dash").get_data(as_text=True)
    assert "+1" in _tile(html, "four")
    assert _tile(html, "four").count("exposure-icon-layer") == 3


def test_tiled_badges_in_bottom_row_not_details(app, admin_client):
    with app.app_context():
        _seed()
    html = admin_client.get("/tiled_dash").get_data(as_text=True)
    tile = _tile(html, "twotraefik")
    details = tile[:tile.index('class="tile-status-row"')]
    assert "exposure-icons" not in details
    row = tile[tile.index('class="tile-status-row"'):]
    assert "exposure-icons-inline" in row
    assert row.index("tile-icon-row-status") < row.index("exposure-icons-inline") < row.index("tile-icon-row-actions")
    assert len(re.findall(r"exposure/traefik\.svg", row)) == 1
    # The Dashboard view keeps its own (non-inline) badges.
    dash = admin_client.get("/").get_data(as_text=True)
    assert "exposure-icons" in dash
