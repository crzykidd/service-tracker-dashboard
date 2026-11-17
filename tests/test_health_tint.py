"""Degraded/down entries get an entry-health-<state> class on all three views (PRD 15.10)."""

import re
from datetime import datetime

import pytest

from extensions import db
from models import ServiceEntry, ensure_url_checks

VIEWS = ["/", "/tiled_dash", "/compact_dash"]


def _entry(name, internal_ok=None, external_ok=None):
    e = ServiceEntry(host="h", container_name=name, source="manual",
                     internalurl=f"http://{name}.lan", externalurl=f"https://{name}.example.com",
                     last_updated=datetime.now(), last_api_update=datetime.now())
    db.session.add(e)
    db.session.flush()
    ensure_url_checks(e)
    for kind, ok in (("internal", internal_ok), ("external", external_ok)):
        c = e.url_check(kind)
        c.enabled = ok is not None
        c.last_ok = ok
    db.session.flush()
    return e


@pytest.fixture
def seeded(app):
    with app.app_context():
        _entry("upsvc", True, True)
        _entry("degsvc", True, False)
        _entry("downsvc", False, False)
        db.session.commit()


def _opening_tags(html, cls):
    return [t for t in re.findall(r"<(?:tr|div)\b[^>]*>", html) if re.search(rf'class="[^"]*\b{cls}\b', t)]


@pytest.mark.parametrize("path", VIEWS)
def test_tint_classes(admin_client, seeded, path):
    html = admin_client.get(path).get_data(as_text=True)
    assert "entry-health-degraded" in html and "entry-health-down" in html
    base = {"/": "group-entry", "/tiled_dash": "tile", "/compact_dash": "compact-tile"}[path]
    tagged = {s: _opening_tags(html, base) for s in ("degraded", "down")}
    for state in tagged:
        hits = [t for t in tagged[state] if f"entry-health-{state}" in t]
        assert len(hits) == 1, (path, state)
    # No tint class anywhere on the up entry's element: exactly two tinted elements.
    assert len([t for t in _opening_tags(html, base) if "entry-health-" in t]) == 2
