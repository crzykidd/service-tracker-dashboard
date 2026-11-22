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


def fake(id_, name, host="h1", published=None, exposed=None, status="running", deleted_at=None, stack=None):
    return SimpleNamespace(id=id_, container_name=name, host=host, published_ports=published,
                           exposed_ports=exposed, docker_status=status, deleted_at=deleted_at,
                           stack_name=stack)


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
    assert ports.summarize(rows) == {"hosts": 2, "published": 3, "exposed": 1, "conflicts": 2}


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
    groups = ports.group_by_host(rows)
    assert [h for h, _ in groups] == ["alpha", "zeta"]
    assert [r["host_port"] for r in groups[0][1]] == [80, 9000, None]
    flat = ports.sort_rows(rows, "name")
    assert [r["name"] for r in flat] == ["a", "b", "b", "c"]
    assert ports.normalize_sort("bogus") == "host" and ports.normalize_kind("bogus") == "all"


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


def test_grouped_view_with_conflict_and_summary(admin_client, seeded):
    html = admin_client.get("/ports").get_data(as_text=True)
    assert 'class="mb-6 ports-host" data-host="h1"' in html and 'data-host="h2"' in html
    assert html.index('data-host="h1"') < html.index('data-host="h2"')
    assert html.count("ports-conflict-marker") == 2
    assert "Same host port as other" in html and "Same host port as web" in html
    assert "2 hosts" in html and "3 published" in html and "1 exposed" in html
    assert 'id="ports-count-conflicts" href="/ports?view=grouped&amp;kind=all&amp;sort=host&amp;conflicts=true"' in html
    assert "7777" not in html
    assert "port-exposed opacity-50" in html and "0.0.0.0, ::" in html


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
                add(f"bulk-{i}", f"h{i % 4}", [pub(1000 + i)], ["80/tcp"])

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
    assert body["summary"] == {"hosts": 2, "published": 3, "exposed": 1, "conflicts": 2}
    assert len(body["ports"]) == 4
    row = next(r for r in body["ports"] if r["name"] == "web" and r["kind"] == "published")
    assert set(row) == {"entry_id", "name", "host", "container_name", "stack_name", "docker_status", "kind",
                        "host_ips", "host_port", "container_port", "protocol", "conflict", "conflict_with"}
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
