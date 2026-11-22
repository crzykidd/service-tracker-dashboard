"""The shared entry facts partial: tile drawer and main dashboard expand row show the same details."""

from datetime import datetime

from extensions import db
from models import ServiceEntry, ServiceExposure


def _seed():
    now = datetime.now()
    e = ServiceEntry(
        host="facts-host", container_name="facts-svc", source="notifier",
        description="Facts about me", stack_name="facts-stack",
        internalurl="http://facts.lan", last_updated=now, last_api_update=now,
        networks=[{"name": "facts-net", "aliases": ["facts-alias"]}],
        published_ports=[{"container_port": 8080, "protocol": "tcp", "host_port": 9090}],
        exposed_ports=["8080/tcp"])
    s = ServiceEntry(
        container_name="facts-stream", source="stream", stream_key="k1",
        mac="aa:bb:cc:dd:ee:ff", ip="10.9.8.7", last_updated=now)
    db.session.add_all([e, s])
    db.session.flush()
    db.session.add(ServiceExposure(
        service_entry_id=e.id, layer="traefik-facts", hostname="facts.example.com", tls=True))
    db.session.commit()


EXPECTED = ["facts-host", "Facts about me", "facts-stack", "facts-net", "facts-alias",
            "8080/tcp", "traefik-facts", "facts.example.com", "aa:bb:cc:dd:ee:ff", "10.9.8.7"]


def test_dashboard_expand_row_has_facts_and_health(app, admin_client):
    with app.app_context():
        _seed()
    html = admin_client.get("/").get_data(as_text=True)
    row = html[html.index('class="health-expand-row'):]
    assert "expand-facts" in row and "expand-health" in row
    for text in EXPECTED:
        assert text in row, text
    assert "data-health-detail" in row
    # IP/MAC are in the facts column only, not repeated by the health detail.
    assert "data-entry-facts" not in row


def test_tile_drawer_still_has_facts(app, admin_client):
    with app.app_context():
        _seed()
    html = admin_client.get("/tiled_dash").get_data(as_text=True)
    drawer = html[html.index('class="tile-drawer"'):]
    for text in EXPECTED:
        assert text in drawer, text


def test_exposed_only_ports_are_listed(app, admin_client):
    """Exposed ports with no published mapping show as "(exposed)", not a blank Ports row
    (a Jinja loop-scope bug dropped them before)."""
    now = datetime.now()
    with app.app_context():
        e = ServiceEntry(
            host="exp-host", container_name="exp-svc", source="notifier",
            last_updated=now, last_api_update=now,
            published_ports=[], exposed_ports=["8080/tcp", "9000/udp"])
        db.session.add(e)
        db.session.commit()
    for path in ("/", "/tiled_dash"):
        html = admin_client.get(path).get_data(as_text=True)
        assert "8080/tcp, 9000/udp (exposed)" in html, path


def test_docker_line_shows_the_full_image(app, admin_client):
    """The details show the image (registry/owner/name:tag), not only the tag (issue #5)."""
    now = datetime.now()
    with app.app_context():
        db.session.add_all([
            ServiceEntry(host="img-host", container_name="img-full", source="notifier",
                         last_updated=now, last_api_update=now, docker_status="running",
                         image_registry="ghcr.io", image_owner="crzykidd",
                         image_name="service-tracker-dashboard", image_tag="dev"),
            ServiceEntry(host="img-host", container_name="img-short", source="notifier",
                         last_updated=now, last_api_update=now, docker_status="running",
                         image_name="nginx", image_tag=None),
        ])
        db.session.commit()
    for path in ("/", "/tiled_dash"):
        html = admin_client.get(path).get_data(as_text=True)
        assert "<code>ghcr.io/crzykidd/service-tracker-dashboard:dev</code>" in html, path
        assert "<code>nginx</code>" in html, path


def test_network_details_render_in_the_facts(app, admin_client):
    with app.app_context():
        db.session.add(ServiceEntry(
            host="nd-host", container_name="nd-svc", source="notifier", last_updated=datetime.now(),
            networks=[{"name": "lan_macvlan", "aliases": [], "driver": "macvlan", "ip_address": "192.168.1.50",
                       "mac_address": "02:42:ac:11:00:02"}, {"name": "old", "aliases": []}]))
        db.session.commit()
    html = admin_client.get("/").get_data(as_text=True)
    for text in ("lan_macvlan", "(macvlan)", "192.168.1.50", "02:42:ac:11:00:02"):
        assert text in html, text
    assert "old" in html
