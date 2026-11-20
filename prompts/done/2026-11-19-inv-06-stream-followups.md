---
name: 2026-11-19-inv-06-stream-followups
status: completed        # pending | completed | failed
created: 2026-11-19
model: sonnet
completed: 2026-11-19
result: All 13 steps built plus the Compact source-icon scope addition; lint clean, full suite green. Not committed.
---

# Task: inventory-stream follow-ups from the first live test (0.10.0)

The operator ran the first live `std-source-technitium` test against `:dev` at
`8ce1ad8`. These fixes go into 0.10.0 before release (still API revision 2: no
`/api/v1` wire change unless noted; if a management-API response gains a field,
that is additive inside the unreleased revision 2 — note it in PRD §18 rather than
bumping `API_REVISION`).

## Before you start

- Read `CLAUDE.md` (Definition of Done, Inventory Stream Ingest Rules, Database
  Rules), `standards.md`, `docs/PRD.md` §18 (incl. the "As built" notes) and the
  newest entries of `docs/decisions.md`.
- Key code: `streams.py` (`plan`, `_execute`, `disable`, `preview`,
  `link_entry`, `_convert`, `unmatched_items`), `routes_dashboard.py` (stream
  routes, `/add`, settings context), `app.py` (`inject_globals` context
  processor), `templates/partials/settings_streams.html`,
  `templates/partials/stream_pill.html`, `templates/tiled_dash.html`,
  `templates/dashboard.html`, `templates/compact_dash.html`,
  `templates/partials/health_detail.html` + `static/js/health_detail.js` and the
  `/service/<id>/health` route, `templates/edit_entry.html`,
  `templates/add_entry.html`, `templates/settings.html` (Home Assistant entries
  table, ~line 812), `templates/base.html` (header nav).
- Lint: `uvx ruff@0.15.17 check .` Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any have uncommitted changes, list them and stop and
report back. This file is exempt.

## What to do

1. **Broader link-offer matching (`streams.plan`).** Today only active manual
   entries with `host IS NULL` and an exact case-insensitive name match are
   candidates. Operators fill the add page's Host field with the device's
   hostname, so real matches were missed. New rule:
   - candidates are all active **manual** entries (`source == manual`), host or not;
   - an item matches an entry when the item's name — or its first DNS label
     (`z-wave-house.crzynet.me` → `z-wave-house`) — equals, case-insensitively,
     the entry's `container_name`, its `host`, or the first label of its `host`;
   - still **exactly one** candidate entry, else no offer (item is created);
   - an entry already linked/offered to another key of the same stream is not a
     candidate twice (keep current stale/duplicate protections);
   - keep the query budget (test pins 5,000 items ≤ 15 SELECTs) — build lookup
     dicts in Python.
   - The same widening applies to the edit page "Link to stream item…" picker and
     `link_entry` / `POST .../link` (any active manual entry, not only host-less).
   - **Convert / accept / link clears `host`** (stream entries have no host). The
     Convert banner on the manual edit page says so when the entry has a host:
     "Its host `<host>` will be cleared; the stream reports its address."
   - Check register adoption, `find_duplicate` and restore clash rules are
     unaffected (stream entries remain excluded from them).
2. **Disable + purge keeps the stored snapshot.** In `streams.disable(...,
   cleanup=purge)` stop clearing `stream.snapshot` (still remove entries, offers,
   `last_counts`, and blocks when `clear_blocks`). `delete` still removes the row.
   Update the Disable…/Delete… dialog text so it states exactly what each mode
   removes (and that the stored snapshot is kept on disable).
3. **Stream row without a snapshot:** where Preview is hidden, show muted
   "Waiting for the next snapshot" text.
4. **Dry-run counts for non-enabled streams.** For a pending or disabled stream
   with a stored snapshot, the Last counts cell shows the would-be counts from
   `plan()` (read-only), labelled "would: created 5, link offer 2…", instead of
   "—". Keep it cheap (one `plan()` per such stream on the Streams tab render).
5. **Pending-stream flag in the header.** Add `pending_streams` (count of
   `InventoryStream.status == 'pending'`) to `inject_globals` for authenticated
   users only; wrap in try/except like the version header (must never break a
   page). In `base.html`, when > 0, the Settings nav link gets an amber ring and a
   small amber count badge, `title`/`aria-label` "N inventory stream(s) pending
   review", and links to Settings → Streams (`section=streams`). Works on every
   page using the shared header.
6. **Default checks per stream.** Operators can't easily monitor stream items.
   Add per-stream default checks:
   - Alembic migration: nullable JSON column on `inventory_stream` (e.g.
     `default_checks`), shape like `{"ping": true, "tcp_port": null | int}`;
     validated (port 1–65535).
   - New stream entries (`new_stream_entry`) get an enabled ping check on the
     entry's IP (and a TCP check on `ip:port` when set) using the existing
     check model/helpers (`check_form.py`, `ensure_url_checks` patterns). No IP →
     skip.
   - Settings → Streams row (inside the existing "Edit name and network filters"
     details, or a sibling details) gets the editor, plus an **Apply to existing
     entries** button that adds the missing default checks to every active entry
     of the stream, skipping entries that already have a check of that kind
     (don't duplicate, don't touch customised checks). Flash a summary count.
   - Management API: expose `default_checks` on the stream resource and accept it
     on the stream PATCH (schemas `extra="forbid"`, register in `mgmt_openapi.py`),
     plus an apply route; MCP tool if the stream tools pattern makes it trivial.
     This is a management API change, not the ingest contract.
   - Audit API actions as the other stream routes do; UI actions log.
7. **Detail panel shows IP and MAC.** The expandable per-entry detail (dashboard
   expand row / `health_detail` panel, and wherever Tiled/Compact show more info)
   includes the stream's `ip`, `mac` and `network` for stream entries (and for any
   entry that has them). Read-only.
8. **Tiled view: compact stream icon.** On Tiled, replace the full stream pill
   (`stream_pill.html` include in `tiled_dash.html`) with a single `status-icon`
   in the same slot and style as the Docker icon: a Tabler icon that reads as
   DHCP/network (e.g. `ti-router` or `ti-network`; pick one and keep it), class
   `status-icon-ok` normally and `status-icon-warn` when `inventory_missing`,
   tooltip "Stream: <display name> — <ip>" plus "— missing from the latest
   snapshot" when missing. Don't render the separate ghost marker on Tiled
   (the icon state carries it).
   **Scope addition (operator, mid-task):** Compact gets the same treatment. Replace
   the full pill with the same stream `status-icon`, and show one source icon on every
   Compact row: `ti-brand-docker` (same status classes/tooltip as Tiled) for Docker
   entries, the stream icon for stream entries, `ti-link` (muted) for manual entries.
   Nothing else from the Tiled status row goes on Compact. The full pill stays on the
   main Dashboard view only.
9. **Home Assistant entries table (Settings → Notifications):** add a **Source**
   column — "Docker", "Manual", or the stream's display name — and make the
   `#ha-filter` box match it, so "technitium" + Select all works.
10. **Add page Host wording.** Label "Docker host (optional)"; drop the
    `server01.example.com` placeholder; help text: "The machine that runs this
    container, if the notifier should take this entry over later. Leave blank for
    a device, VM or anything not running in Docker." Mirror on the edit page's
    Host field help for manual entries.
11. **MCP parity (required).** Everything this task adds or changes that an
    operator can see or do must be reachable from the MCP server (`mcp/std_mcp.py`,
    an HTTP client of the management API only): default checks get/set and
    apply-to-existing; widened link matching via the existing unmatched/link/offer
    tools (update descriptions); dry-run counts via the preview tool; stream
    entries' `ip`/`mac`/`network` in entry tools' output; the pending-stream count
    (e.g. in a streams list/summary tool). Where the management API lacks a route,
    add it (schemas, `mgmt_openapi.py`, tests) first. Update `mcp/README.md` and
    MCP tests.
12. **Tests** for: the new matching (host match, first-label match, ambiguity → no
    offer, query budget), convert clears host, purge keeps snapshot, dry-run
    counts, pending flag in header (shown/hidden/unauthenticated), default checks
    on create and apply-to-existing (no duplicates), HA table source column,
    management API schema + OpenAPI registry.
13. **Docs:** CHANGELOG `[Unreleased]` entries (operator language); PRD §18
    (matching rule, disable+purge, default checks, UI) + §5.10 schema + revision
    row; README if operator-facing behavior described there changed;
    `docs/decisions.md` for the matching widening (why host is compared) and
    purge keeping the snapshot.

## Conventions to honor

- Contract rules in CLAUDE.md: no ingest wire change; stream entries never touched
  by register adoption / `find_duplicate` / restore clash checks.
- Migration: FK/index rule; must pass the CI Migration check.
- Match existing Tailwind/Tabler patterns; no new JS frameworks.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move this file into `prompts/done/` (or `prompts/failed/`) with plain `mv`
   (it is untracked).
3. Record non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Run lint + tests, then report back
   the file list, test/lint results, any doc contradictions found, and a proposed
   one-line message (`feat: ...`, no Co-authored-by trailer).
