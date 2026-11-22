"""Ports in use (PRD 25): the pure module, the /ports page, GET /api/v1/ports."""

from datetime import datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import event

import api_keys
import ports
from api_version import API_REVISION
from extensions import db
from models import ApiKey, ServiceEntry


def pub(host_port, container_port=None, protocol="tcp", ip="0.0.0.0"):
    return {"container_port": container_port or host_port, "protocol": protocol,
            "host_ip": ip, "host_port": host_port}


def fake(id_, name, host="h1", published=None, exposed=None, status="running", deleted_at=None, stack=None,
         networks=None):
    return SimpleNamespace(id=id_, container_name=name, host=host, published_ports=published,
                           exposed_ports=exposed, docker_status=status, deleted_at=deleted_at,
                           stack_name=stack, networks=networks)


def net(name, driver=None, ip=None, ipv6=None):
    out = {"name": name, "aliases": []}
    if driver:
        out["driver"] = driver
    if ip:
        out["ip_address"] = ip
    if ipv6:
        out["ipv6_address"] = ipv6
    return out


# --- pure module -------------------------------------------------------------------------


def test_null_and_malformed_data_never_raise():
    entries = [
        fake(1, "a"),
        fake(2, "b", published="nope", exposed={"x": 1}),
        fake(3, "c", published=[None, 5, {"host_port": "x", "container_port": 1}, {"host_port": 0, "container_port": 1},
                                {"host_port": True, "container_port": 1}, {"container_port": 80}],
             exposed=[None, 7, "abc/tcp", "99999/tcp", "/tcp"]),
    ]
    assert ports.build_rows(entries) == []


def test_ipv4_and_ipv6_binding_collapse_into_one_row():
    rows = ports.build_rows([fake(1, "web", published=[pub(8080, 80), pub(8080, 80, ip="::")])])
    assert len(rows) == 1
    assert rows[0]["host_ips"] == ["0.0.0.0", "::"] and rows[0]["kind"] == "published"
    assert rows[0]["host_port"] == 8080 and rows[0]["container_port"] == 80


def test_exposed_only_detection():
    e = fake(1, "web", published=[pub(8080, 80)], exposed=["80/tcp", "9000/tcp", "9000/tcp", "53/udp"])
    rows = ports.build_rows([e])
    exposed = [(r["container_port"], r["protocol"]) for r in rows if r["kind"] == "exposed"]
    assert sorted(exposed) == [(53, "udp"), (9000, "tcp")]
    assert all(r["host_port"] is None and r["host_ips"] == [] and not r["conflict"]
               for r in rows if r["kind"] == "exposed")


def test_exposed_without_protocol_defaults_to_tcp():
    rows = ports.build_rows([fake(1, "a", exposed=["80"])])
    assert rows[0]["protocol"] == "tcp"


def _conflicts(*entries):
    return {r["entry_id"]: r["conflict_with"] for r in ports.build_rows(entries) if r["conflict"]}


def test_conflict_same_host_and_port():
    got = _conflicts(fake(1, "a", published=[pub(80)]), fake(2, "b", published=[pub(80)]))
    assert got == {1: [2], 2: [1]}


def test_no_conflict_on_different_hosts():
    assert _conflicts(fake(1, "a", "h1", [pub(80)]), fake(2, "b", "h2", [pub(80)])) == {}


def test_no_conflict_for_hostless_entries():
    assert _conflicts(fake(1, "a", None, [pub(80)]), fake(2, "b", None, [pub(80)])) == {}


def test_no_conflict_tcp_vs_udp():
    assert _conflicts(fake(1, "a", published=[pub(53)]), fake(2, "b", published=[pub(53, protocol="udp")])) == {}


def test_no_conflict_for_two_different_specific_ips():
    a = fake(1, "a", published=[pub(80, ip="10.0.0.1")])
    b = fake(2, "b", published=[pub(80, ip="10.0.0.2")])
    assert _conflicts(a, b) == {}


def test_conflict_for_the_same_specific_ip():
    a = fake(1, "a", published=[pub(80, ip="10.0.0.1")])
    b = fake(2, "b", published=[pub(80, ip="10.0.0.1")])
    assert set(_conflicts(a, b)) == {1, 2}


def test_wildcard_overlaps_a_specific_ip():
    a = fake(1, "a", published=[pub(80, ip="0.0.0.0")])
    b = fake(2, "b", published=[pub(80, ip="10.0.0.2")])
    assert set(_conflicts(a, b)) == {1, 2}


def test_the_same_entry_twice_is_not_a_conflict():
    e = fake(1, "a", published=[pub(80, 80), pub(80, 8080)])
    assert _conflicts(e) == {}


def test_exposed_rows_never_conflict():
    a = fake(1, "a", exposed=["80/tcp"])
    b = fake(2, "b", published=[pub(80)])
    assert _conflicts(a, b) == {}


def test_deleted_and_stopped_entries_are_excluded():
    entries = [
        fake(1, "gone", published=[pub(80)], deleted_at=datetime.now()),
        fake(2, "dead", published=[pub(81)], status="exited"),
        fake(3, "up", published=[pub(82)], status="running"),
        fake(4, "starting", published=[pub(83)], status="start"),
        fake(5, "unknown", published=[pub(84)], status=None),
    ]
    assert [r["entry_id"] for r in ports.build_rows(entries)] == [3, 4, 5]


def test_summary_counts():
    rows = ports.build_rows([
        fake(1, "a", "h1", [pub(80)], ["80/tcp", "9/tcp"]),
        fake(2, "b", "h1", [pub(80)]),
        fake(3, "c", "h2", [pub(81)]),
    ])
    assert ports.summarize(rows) == {"hosts": 2, "published": 3, "host_network": 0, "direct": 0, "exposed": 1,
                                      "conflicts": 2}


def test_filter_rows():
    rows = ports.build_rows([
        fake(1, "web", "h1", [pub(80)], ["9000/tcp"], stack="blog"),
        fake(2, "db", "h2", [pub(5432)]),
        fake(3, "web2", "h1", [pub(80)]),
    ])
    assert {r["entry_id"] for r in ports.filter_rows(rows, kind="exposed")} == {1}
    assert {r["entry_id"] for r in ports.filter_rows(rows, host="h2")} == {2}
    assert {r["entry_id"] for r in ports.filter_rows(rows, q="BLOG")} == {1}
    assert {r["entry_id"] for r in ports.filter_rows(rows, q="5432")} == {2}
    assert {r["entry_id"] for r in ports.filter_rows(rows, conflicts_only=True)} == {1, 3}
    assert len(ports.filter_rows(rows)) == len(rows)


def test_group_and_sort_order():
    rows = ports.build_rows([
        fake(1, "a", "zeta", [pub(90)]), fake(2, "b", "alpha", [pub(9000)], ["1/tcp"]), fake(3, "c", "alpha", [pub(80)]),
    ])
    # Default sort is the container name, but published rows always come first.
    groups = ports.group_by_host(rows)
    assert [h for h, _ in groups] == ["alpha", "zeta"]
    assert [(r["name"], r["kind"]) for r in groups[0][1]] == [("b", "published"), ("c", "published"), ("b", "exposed")]
    assert [r["host_port"] for r in ports.group_by_host(rows, "port")[0][1]] == [80, 9000, None]
    # `host` is not offered inside a section: it falls back to the default.
    assert ports.group_by_host(rows, "host") == ports.group_by_host(rows, "name")
    flat = ports.sort_rows(rows)
    assert [(r["name"], r["kind"]) for r in flat] == [
        ("a", "published"), ("b", "published"), ("c", "published"), ("b", "exposed")]
    assert [r["host"] for r in ports.sort_rows(rows, "host")][:3] == ["alpha", "alpha", "zeta"]
    assert ports.normalize_sort("bogus") == "name" and ports.normalize_kind("bogus") == "all"


def test_sort_by_port_uses_container_port_for_not_published_and_keeps_alias():
    rows = ports.build_rows([
        fake(1, "a", "h1", [pub(9000, 1)], ["70/tcp"]), fake(2, "b", "h1", [pub(80, 2)], ["5/tcp"]),
    ])
    out = ports.sort_rows(rows, "port")
    assert [(r["kind"], r["host_port"] or r["container_port"]) for r in out] == [
        ("published", 80), ("published", 9000), ("exposed", 5), ("exposed", 70)]
    assert ports.normalize_sort("host_port") == "port"
    assert ports.sort_rows(rows, "host_port") == out


# --- the page and the API ----------------------------------------------------------------


def add(name, host="h1", published=None, exposed=None, status="running", **kw):
    e = ServiceEntry(host=host, container_name=name, source="notifier", last_updated=datetime.now(),
                     published_ports=published, exposed_ports=exposed, docker_status=status, **kw)
    db.session.add(e)
    db.session.commit()
    return e.id


@pytest.fixture
def seeded(app):
    with app.app_context():
        return {
            "web": add("web", "h1", [pub(8080, 80), pub(8080, 80, ip="::")], ["80/tcp", "9000/tcp"]),
            "other": add("other", "h1", [pub(8080, 3000)]),
            "db": add("db", "h2", [pub(5432)]),
            "dead": add("dead", "h2", [pub(7777)], status="exited"),
        }


def _key(app, scope="read"):
    with app.app_context():
        _, token = api_keys.create_key(f"ports-{scope}-{ApiKey.query.count()}", scope)
        db.session.commit()
    return {"Authorization": f"Bearer {token}"}


def test_page_requires_login(client):
    r = client.get("/ports")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_tab_is_in_the_nav_on_every_view(admin_client):
    for view in ("/", "/tiled_dash", "/compact_dash", "/ports"):
        assert 'href="/ports"' in admin_client.get(view).get_data(as_text=True)


def test_page_loads_the_autosubmit_and_view_memory_script(admin_client):
    html = admin_client.get("/ports").get_data(as_text=True)
    # Not deferred: it restores the remembered view before the tables render.
    start = html.index('js/ports.js')
    tag = html[html.rindex('<script', 0, start):html.index('</script>', start)]
    assert 'defer' not in tag
    assert 'id="ports-reset"' in html
    # The Apply button stays in the markup for no-JS use.
    assert 'type="submit"' in html


def test_grouped_view_with_conflict_and_summary(admin_client, seeded):
    html = admin_client.get("/ports").get_data(as_text=True)
    assert 'class="mb-6 ports-host" data-host="h1"' in html and 'data-host="h2"' in html
    assert html.index('data-host="h1"') < html.index('data-host="h2"')
    assert html.count("ports-conflict-marker") == 2
    assert "Same host port as other" in html and "Same host port as web" in html
    assert "2 hosts" in html and "3 published" in html and "1 not published" in html
    assert 'id="ports-count-conflicts" href="/ports?view=grouped&amp;kind=all&amp;sort=name&amp;conflicts=true"' in html
    assert "7777" not in html
    assert "port-exposed opacity-50" in html and "0.0.0.0, ::" in html


def test_not_published_label(admin_client, seeded):
    html = admin_client.get("/ports").get_data(as_text=True)
    assert ">not published</span>" in html and ">not published</option>" in html
    assert ">exposed<" not in html and 'data-kind="exposed"' in html
    # The kind=exposed query value still works on the page.
    assert "9000/tcp" in admin_client.get("/ports?kind=exposed").get_data(as_text=True)


def test_sort_select_in_both_views(admin_client, seeded):
    flat = admin_client.get("/ports?view=flat").get_data(as_text=True)
    grouped = admin_client.get("/ports?view=grouped").get_data(as_text=True)
    assert 'name="sort"' in flat and 'name="sort"' in grouped
    assert '<option value="host"' in flat and '<option value="host"' not in grouped
    assert '<option value="name" selected>' in grouped
    # host falls back to the default in the grouped view; the old alias still selects port.
    assert '<option value="name" selected>' in admin_client.get("/ports?sort=host").get_data(as_text=True)
    assert '<option value="port" selected>' in admin_client.get("/ports?sort=host_port").get_data(as_text=True)


def test_flat_view_and_sort(admin_client, seeded):
    html = admin_client.get("/ports?view=flat&sort=name").get_data(as_text=True)
    assert 'id="ports-flat"' in html and "ports-host" not in html
    names = [n for n in ("db", "other", "web") if n]
    positions = [html.index(f'>{n}</a>') for n in names]
    assert positions == sorted(positions)


def test_filters(admin_client, seeded):
    kind = admin_client.get("/ports?kind=exposed").get_data(as_text=True)
    assert "9000/tcp" in kind and "5432" not in kind
    host = admin_client.get("/ports?host=h2").get_data(as_text=True)
    assert "5432" in host and "8080" not in host
    only = admin_client.get("/ports?conflicts=true").get_data(as_text=True)
    assert "5432" not in only and "8080" in only
    q = admin_client.get("/ports?q=postgres-none").get_data(as_text=True)
    assert "No ports match" in q


def test_unknown_params_fall_back(admin_client, seeded):
    r = admin_client.get("/ports?view=x&kind=y&sort=z&host=nope&conflicts=maybe")
    html = r.get_data(as_text=True)
    assert r.status_code == 200 and 'class="mb-6 ports-host"' in html and "5432" in html


def test_empty_state(admin_client):
    html = admin_client.get("/ports").get_data(as_text=True)
    assert 'id="ports-empty"' in html and "docker-api-notifier 0.4.0" in html


def test_ports_page_query_count_stays_flat(app, admin_client):
    def more(n, start):
        with app.app_context():
            for i in range(start, start + n):
                add(f"bulk-{i}", f"h{i % 4}", [pub(1000 + i)], ["80/tcp"],
                    networks=[net("lan", "macvlan", f"10.0.0.{i % 250}")] if i % 2 else None)

    def count():
        statements = []

        def hook(conn, cursor, statement, params, context, many):
            statements.append(statement)

        with app.app_context():
            event.listen(db.engine, "before_cursor_execute", hook)
            try:
                assert admin_client.get("/ports").status_code == 200
            finally:
                event.remove(db.engine, "before_cursor_execute", hook)
        return len(statements)

    more(3, 0)
    admin_client.get("/ports")
    few = count()
    more(25, 100)
    assert count() == few


def test_api_shape_and_filters(client, app, seeded):
    body = client.get("/api/v1/ports", headers=_key(app)).get_json()
    assert body["summary"] == {"hosts": 2, "published": 3, "host_network": 0, "direct": 0, "exposed": 1,
                                      "conflicts": 2}
    assert len(body["ports"]) == 4
    row = next(r for r in body["ports"] if r["name"] == "web" and r["kind"] == "published")
    assert set(row) == {"entry_id", "name", "host", "container_name", "stack_name", "docker_status", "kind",
                        "host_ips", "host_port", "container_port", "protocol", "network", "driver",
                       "conflict", "conflict_with"}
    assert row["conflict"] and row["conflict_with"] == [seeded["other"]]
    h = _key(app)
    got = client.get("/api/v1/ports?kind=exposed", headers=h).get_json()
    assert [r["kind"] for r in got["ports"]] == ["exposed"] and got["summary"]["published"] == 3
    assert {r["host"] for r in client.get("/api/v1/ports?host=h2", headers=h).get_json()["ports"]} == {"h2"}
    assert len(client.get("/api/v1/ports?conflicts=true", headers=h).get_json()["ports"]) == 2
    assert len(client.get("/api/v1/ports?q=5432", headers=h).get_json()["ports"]) == 1


def test_api_bad_params_and_auth(client, app):
    r = client.get("/api/v1/ports?kind=nope", headers=_key(app))
    assert r.status_code == 400 and r.get_json()["error"]
    assert client.get("/api/v1/ports?conflicts=maybe", headers=_key(app)).status_code == 400
    assert client.get("/api/v1/ports").status_code == 401
    assert client.get("/api/v1/ports", headers=_key(app, "write")).status_code == 200


def test_meta_reports_revision_6(client):
    meta = client.get("/api/v1/meta").get_json()
    assert API_REVISION == 6 and meta["api_revision"] == 6 and "ports" in meta["features"]


# --- network details: macvlan, ipvlan, host network (PRD 25) ---------------------------------


@pytest.mark.parametrize("driver", ["macvlan", "ipvlan"])
def test_direct_rows_for_macvlan_and_ipvlan(driver):
    e = fake(1, "nas", published=[pub(8080, 80)], exposed=["80/tcp", "443/tcp"],
             networks=[net("lan", driver, "192.168.1.50")])
    rows = ports.build_rows([e])
    assert [(r["kind"], r["container_port"], r["host_port"], r["host_ips"], r["network"], r["driver"])
            for r in rows] == [("direct", 80, 80, ["192.168.1.50"], "lan", driver),
                               ("direct", 443, 443, ["192.168.1.50"], "lan", driver)]
    # the published binding is ignored by Docker on these drivers: no published row
    assert not any(r["kind"] in ("published", "exposed") for r in rows)


def test_direct_needs_an_address_and_a_driver():
    no_ip = fake(1, "a", exposed=["80/tcp"], networks=[net("lan", "macvlan")])
    no_driver = fake(2, "b", exposed=["80/tcp"], networks=[net("lan", None, "192.168.1.9")])
    assert [r["kind"] for r in ports.build_rows([no_ip, no_driver])] == ["exposed", "exposed"]


def test_direct_with_ipv6_only_and_both():
    rows = ports.build_rows([fake(1, "a", exposed=["80/tcp"], networks=[net("lan", "macvlan", "10.0.0.2", "fd00::2")])])
    assert rows[0]["host_ips"] == ["10.0.0.2", "fd00::2"]


def test_published_still_apply_next_to_an_ordinary_network():
    e = fake(1, "a", published=[pub(8080, 80)], exposed=["80/tcp"],
             networks=[net("bridge", "bridge"), net("lan", "macvlan", "10.0.0.2")])
    rows = ports.build_rows([e])
    assert [r["kind"] for r in rows] == ["published", "direct"]


@pytest.mark.parametrize("networks", [[net("host", "host")], [net("host")]])
def test_host_network_rows_with_and_without_driver(networks):
    rows = ports.build_rows([fake(1, "h", exposed=["9000/tcp"], published=[pub(9001, 9001)], networks=networks)])
    assert [(r["kind"], r["host_port"], r["container_port"], r["host_ips"], r["network"]) for r in rows] == [
        ("host_network", 9000, 9000, ["0.0.0.0"], None), ("host_network", 9001, 9001, ["0.0.0.0"], None)]


def test_older_data_behaves_as_before():
    e = fake(1, "a", published=[pub(8080, 80)], exposed=["80/tcp", "81/tcp"],
             networks=[{"name": "bridge", "aliases": []}, "junk", {"aliases": 3}])
    assert [r["kind"] for r in ports.build_rows([e])] == ["published", "exposed"]
    assert [r["kind"] for r in ports.build_rows([fake(2, "b", exposed=["80/tcp"])])] == ["exposed"]


def test_host_network_conflicts_with_published_on_the_same_host():
    a = fake(1, "hostnet", exposed=["8080/tcp"], networks=[net("host", "host")])
    b = fake(2, "web", published=[pub(8080, 80)])
    c = fake(3, "elsewhere", host="h2", published=[pub(8080, 80)])
    rows = {r["name"]: r for r in ports.build_rows([a, b, c])}
    assert rows["hostnet"]["conflict"] and rows["hostnet"]["conflict_with"] == [2]
    assert rows["web"]["conflict"] and rows["web"]["conflict_with"] == [1]
    assert not rows["elsewhere"]["conflict"]
    # a different protocol does not clash
    d = fake(4, "udp", exposed=["8080/udp"], networks=[net("host", "host")])
    assert not any(r["conflict"] for r in ports.build_rows([d, b]))


def test_direct_never_conflicts_with_host_ports_only_with_direct_on_same_address():
    host_pub = fake(1, "web", published=[pub(80, 80)])
    d1 = fake(2, "d1", exposed=["80/tcp"], networks=[net("lan", "macvlan", "10.0.0.2")])
    d2 = fake(3, "d2", host="h2", exposed=["80/tcp"], networks=[net("lan", "macvlan", "10.0.0.2")])
    d3 = fake(4, "d3", exposed=["80/tcp"], networks=[net("lan", "macvlan", "10.0.0.3")])
    hostnet = fake(5, "hn", exposed=["80/tcp"], networks=[net("host")], host="h9")
    rows = {r["name"]: r for r in ports.build_rows([host_pub, d1, d2, d3, hostnet])}
    assert not rows["web"]["conflict"] and not rows["d3"]["conflict"] and not rows["hn"]["conflict"]
    assert rows["d1"]["conflict_with"] == [3] and rows["d2"]["conflict_with"] == [2]


def test_order_and_summary_and_filter_for_the_new_kinds():
    entries = [
        fake(1, "ex", exposed=["1/tcp"]),
        fake(2, "d", exposed=["2/tcp"], networks=[net("lan", "macvlan", "10.0.0.2")]),
        fake(3, "hn", exposed=["3/tcp"], networks=[net("host")]),
        fake(4, "p", published=[pub(4)]),
    ]
    rows = ports.build_rows(entries)
    assert [r["kind"] for r in rows] == ["published", "host_network", "direct", "exposed"]
    assert [r["kind"] for r in ports.sort_rows(rows, "name")] == ["published", "host_network", "direct", "exposed"]
    summary = ports.summarize(rows)
    assert (summary["published"], summary["host_network"], summary["direct"], summary["exposed"]) == (1, 1, 1, 1)
    for kind in ("published", "host_network", "direct", "exposed"):
        assert [r["kind"] for r in ports.filter_rows(rows, kind=kind)] == [kind]
    assert ports.normalize_kind("direct") == "direct" and ports.normalize_kind("bogus") == "all"


def _add_network_entries(app):
    with app.app_context():
        add("nas", "h1", None, ["80/tcp"], networks=[net("lan", "macvlan", "192.168.1.50")])
        add("hn", "h1", None, ["8123/tcp"], networks=[net("host", "host")])
        add("web", "h1", [pub(8123, 80)])


def test_api_kind_filter_and_new_fields(client, app):
    _add_network_entries(app)
    h = _key(app)
    body = client.get("/api/v1/ports", headers=h).get_json()
    assert body["summary"]["host_network"] == 1 and body["summary"]["direct"] == 1
    assert body["summary"]["conflicts"] == 2
    direct = client.get("/api/v1/ports?kind=direct", headers=h).get_json()["ports"]
    assert [(r["kind"], r["host_ips"], r["network"], r["driver"]) for r in direct] == [
        ("direct", ["192.168.1.50"], "lan", "macvlan")]
    hn = client.get("/api/v1/ports?kind=host_network", headers=h).get_json()["ports"]
    assert len(hn) == 1 and hn[0]["host_port"] == 8123 and hn[0]["network"] is None and hn[0]["conflict"]
    assert client.get("/api/v1/ports?kind=nope", headers=h).status_code == 400


def test_page_labels_and_filter_options(app, admin_client):
    _add_network_entries(app)
    html = admin_client.get("/ports").get_data(as_text=True)
    assert "direct (macvlan)" in html and "host network" in html
    assert 'value="host_network"' in html and 'value="direct"' in html
    assert 'id="ports-count-direct"' in html and 'id="ports-count-host-network"' in html
    direct_only = admin_client.get("/ports?kind=direct").get_data(as_text=True)
    assert 'data-kind="direct"' in direct_only and 'data-kind="published"' not in direct_only


def test_meta_advertises_network_details(client):
    assert "network_details" in client.get("/api/v1/meta").get_json()["features"]
