"""Health rollup, badge and status/source filters (v0.7.0, PRD 13.6)."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from extensions import db
from health_state import entry_health
from models import HealthCheck, ServiceEntry, ensure_url_checks

VIEWS = ("/", "/tiled_dash", "/compact_dash")


def _entry(name, source="notifier", fresh=True, internalurl="http://i", externalurl=None, **kw):
    e = ServiceEntry(
        host="h" if source == "notifier" else None, container_name=name, source=source,
        internalurl=internalurl, externalurl=externalurl, last_updated=datetime.now(),
        last_api_update=datetime.now() if (fresh and source == "notifier") else None, **kw)
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    return e


def _set(e, which, enabled=True, ok=None, msg=None):
    c = e.url_check(which)
    c.enabled = enabled
    c.last_ok = ok
    c.last_message = msg
    if ok is not None:
        c.last_checked_at = datetime.utcnow()
    return c


def _svc(e, name, ok=None, msg=None, enabled=True, target="db:1"):
    c = HealthCheck(service_entry_id=e.id, kind="service", name=name, check_type="tcp",
                    target=target, enabled=enabled, last_ok=ok, last_message=msg)
    db.session.add(c)
    db.session.flush()
    db.session.refresh(e)
    return c


@pytest.mark.parametrize("states,expected", [
    ([], "none"),
    ([("internal", False, None)], "none"),                     # disabled
    ([("internal", True, None)], "unknown"),                   # never run
    ([("internal", True, True)], "up"),
    ([("internal", True, False)], "down"),
    ([("internal", True, True), ("external", True, False)], "degraded"),
    ([("internal", True, False), ("external", True, False)], "down"),
    ([("internal", True, True), ("external", True, True)], "up"),
    ([("internal", True, False), ("external", True, None)], "down"),   # only run checks count
    ([("internal", True, True), ("external", True, None)], "up"),
    ([("internal", True, False), ("external", False, True)], "down"),  # disabled ignored
])
def test_rollup_truth_table(app, states, expected):
    with app.app_context():
        e = _entry("t", externalurl="http://e")
        for which, enabled, ok in states:
            _set(e, which, enabled, ok, "boom" if ok is False else None)
        h = entry_health(e)
        assert h.state == expected
        assert h.failing == sum(1 for _, en, ok in states if en and ok is False)


def test_rollup_service_checks_and_failures(app):
    with app.app_context():
        e = _entry("t")
        _set(e, "internal", True, True)
        _svc(e, "db", ok=False, msg="refused")
        _svc(e, "off", ok=False, enabled=False)
        h = entry_health(e)
        assert (h.state, h.total, h.failing) == ("degraded", 2, 1)
        assert h.failures == (("db", "refused"),)
        assert "db: refused" in h.tooltip


def test_rollup_ignores_check_without_target(app):
    with app.app_context():
        e = _entry("t", internalurl=None)
        _set(e, "internal", True, False, "stale result")  # URL cleared since
        assert entry_health(e).state == "none"


def _seed():
    up = _entry("up-svc")
    _set(up, "internal", True, True)
    deg = _entry("deg-svc", externalurl="http://e")
    _set(deg, "internal", True, True)
    _set(deg, "external", True, False, "SSLError: bad")
    down = _entry("down-svc")
    _set(down, "internal", True, False, "OSError: refused")
    unk = _entry("unk-svc")
    _set(unk, "internal", True, None)
    _entry("none-svc")
    man = _entry("man-up", source="manual")
    _set(man, "internal", True, True)
    _entry("man-none", source="manual")
    stale = _entry("stale-svc", fresh=False)
    stale.last_api_update = datetime.now() - timedelta(hours=2)
    _set(stale, "internal", True, True)
    db.session.commit()


EXPECTED = {
    ("all", "all"): {"up-svc", "deg-svc", "down-svc", "unk-svc", "none-svc", "man-up", "man-none", "stale-svc"},
    ("failing", "all"): {"deg-svc", "down-svc"},
    ("healthy", "all"): {"up-svc", "man-up", "stale-svc"},
    ("unknown", "all"): {"unk-svc", "none-svc", "man-none"},
    ("stale", "all"): {"stale-svc"},
    ("all", "manual"): {"man-up", "man-none"},
    ("all", "notifier"): {"up-svc", "deg-svc", "down-svc", "unk-svc", "none-svc", "stale-svc"},
    ("healthy", "manual"): {"man-up"},
    ("healthy", "notifier"): {"up-svc", "stale-svc"},
    ("stale", "manual"): set(),
    ("failing", "manual"): set(),
}
NAMES = {n for s in EXPECTED.values() for n in s}


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("status,source", list(EXPECTED))
def test_filters_on_each_view(app, admin_client, view, status, source):
    with app.app_context():
        _seed()
    body = admin_client.get(f"{view}?status={status}&source={source}").get_data(as_text=True)
    present = {n for n in NAMES if f">{n}<" in body or f'title="{n}"' in body}
    assert present == EXPECTED[(status, source)]


@pytest.mark.parametrize("view", VIEWS)
def test_filters_combine_with_show_urlless(app, admin_client, view):
    with app.app_context():
        _seed()
        _entry("man-nourl", source="manual", internalurl=None)
        db.session.commit()
    both = admin_client.get(f"{view}?source=manual&show_urlless=false").get_data(as_text=True)
    assert "man-up" in both and "man-nourl" not in both and "up-svc" not in both.replace("man-up", "")
    shown = admin_client.get(f"{view}?source=manual").get_data(as_text=True)
    assert "man-nourl" in shown


def test_invalid_filter_values_fall_back_to_all(app, admin_client):
    with app.app_context():
        _seed()
    body = admin_client.get("/?status=bogus&source=%27%3Cx%3E").get_data(as_text=True)
    assert "up-svc" in body and "man-up" in body and "<x>" not in body


def test_selects_reflect_params_and_total(app, admin_client):
    with app.app_context():
        _seed()
    body = admin_client.get("/tiled_dash?status=failing&source=notifier").get_data(as_text=True)
    assert '<option value="failing" selected>' in body
    assert '<option value="notifier" selected>' in body
    assert 'id="statusSelect"' in body and 'class="view-control' in body
    assert '<span id="totalServices">2 / 8</span>' in body
    plain = admin_client.get("/").get_data(as_text=True)
    assert '<span id="totalServices">8</span>' in plain


@pytest.mark.parametrize("view,marker", [
    ("/", 'class="health-pill health-{s}"'),
    ("/tiled_dash", 'health-icon health-{s}"'),
    ("/compact_dash", 'class="health-dot health-{s}"'),
])
def test_badge_renders_every_state(app, admin_client, view, marker):
    with app.app_context():
        _seed()
    body = admin_client.get(view).get_data(as_text=True)
    for s in ("up", "degraded", "down", "unknown", "none"):
        assert marker.format(s=s) in body, s
    assert "SSLError: bad" in body  # failing check message in the tooltip


def test_compact_badge_links_to_edit_health(app, admin_client):
    with app.app_context():
        _seed()
        eid = ServiceEntry.query.filter_by(container_name="down-svc").one().id
    body = admin_client.get("/compact_dash").get_data(as_text=True)
    assert f'href="/edit/{eid}#health"' in body


def test_no_legacy_status_parsing_left():
    import pathlib
    for name in ("dashboard.html", "tiled_dash.html", "compact_dash.html"):
        text = (pathlib.Path(__file__).resolve().parent.parent / "templates" / name).read_text()
        assert "_health_check_status" not in text and "_health_check_update" not in text


def _count_queries(app, client, path):
    from extensions import db as _db
    n = []
    def hook(conn, cursor, statement, params, context, many):
        n.append(statement)
    with app.app_context():
        event.listen(_db.engine, "before_cursor_execute", hook)
        try:
            assert client.get(path).status_code == 200
        finally:
            event.remove(_db.engine, "before_cursor_execute", hook)
    return len(n)


@pytest.mark.parametrize("view", VIEWS)
def test_query_count_flat(app, admin_client, view):
    def add(n, start):
        with app.app_context():
            for i in range(start, start + n):
                e = _entry(f"bulk-{i}", externalurl="http://e", stack_name=f"s{i}")
                _set(e, "internal", True, i % 2 == 0, "x")
                _set(e, "external", True, True)
                _svc(e, "svc", ok=i % 3 == 0)
            db.session.commit()
    add(3, 0)
    admin_client.get(view)  # warm-up (lazy settings etc.)
    few = _count_queries(app, admin_client, view)
    add(30, 100)
    many = _count_queries(app, admin_client, view)
    assert many == few, (few, many)
