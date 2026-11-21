---
name: 2026-11-21-compact-expand
status: completed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: Compact expand button + details dialog, GET /service/<id>/details, tests, docs; ruff clean, 1634 tests pass
---

# Task: Add an expand button and a details view to the compact dashboard

On the Compact view (`templates/compact_dash.html`), each tile shows only:

- an icon and a name;
- a host label;
- a source icon and a health badge;
- a stale icon;
- an uptime strip.

Clicking a tile opens its URL. The operator wants to expand an entry there and see the same details as on the Dashboard and Tiled views.

## Before you start

- Read `CLAUDE.md` and `templates/compact_dash.html`.
- Read `templates/partials/entry_facts.html`. It holds the shared info rows and was just added; it is used by the tile drawer and the Dashboard expand row.
- Also read `templates/partials/health_detail.html`, `templates/dashboard.html` (the `.expand-two-col` expand row, around line 252) and `templates/tiled_dash.html` (the drawer and its action row).
- Read the scripts and styles: `static/js/health_detail.js`, `static/js/dashboard.js` and `static/css/dashboard.css` (look for `.compact-tile`, `.expand-two-col` and `.drawer-*`).
- Look at the Settings `std-modal` dialog pattern (`templates/settings.html`, `static/js/settings/ui.js`) and any dialogs outside Settings (`grep -rn "<dialog" templates`).
- Find the tests that render the compact view: `grep -ln compact tests/*.py`.
- Another agent is fixing small code issues in parallel. It is editing `app.py`, `jobs.py`, `settings_loader.py`, `routes_dashboard.py` (only the `/api/v1/entries/<id>/delete` route), `static/js/dashboard.js` (only the delete URL) and `templates/edit_entry.html`. Avoid editing those areas. If you must add a route to `routes_dashboard.py`, add it near the existing `/service/<id>/health` route; don't touch the delete route. If you need `dashboard.js`, keep your change away from its `stdPost(...delete...)` line, or prefer a new small script file.

## Working tree check

Run `git status --porcelain`. Files the other agent is editing will show as dirty: ignore them. If a file *you* need is dirty and not in that list, stop and report.

## What to do

1. **The expand control.** Add a small expand button to each compact tile, e.g. a chevron or `ti-dots` in `.compact-end`.
   - It must not fire the tile's open-URL click. Use `stopPropagation`, or extend the existing `closest()` guard.
   - Give it an `aria-label` and a `title`.
   - Keyboard-focusable, with a visible focus style.
   - It must keep working when the tile has no URL.
2. **The details view.** The compact grid flows by column (`grid-flow-col`, 10 rows), so an inline drawer would shuffle the layout. Show the details in a dialog (`<dialog>`, matching the `std-modal` look) instead.
   - It has a header with the icon, name, health badge and source.
   - Its body has the same two columns as the Dashboard expand row: the shared `entry_facts.html` on the left, and the health detail (`hide_facts=true`) on the right, stacking on narrow screens.
   - Its footer has Edit, Delete (not for locked or static entries, with the same delete flow and popover as the other views) and the Dozzle log link when applicable, matching the tile drawer's action row.
   - Escape and the close button close it.
3. **Loading.** Don't render facts for every tile up front. Add a lightweight GET route that renders the dialog body for one entry, e.g. `/service/<id>/details`.
   - Login required.
   - Same context as the views: `widget_values`, `widget_fields`, `stream_health`, `entry_health`.
   - 404 for a deleted or unknown entry.

   Fetch it when the dialog opens, then initialise the health detail through `health_detail.js`, so lazy-loading and Check now work. If auto-refresh is active on Compact, pause it while the dialog is open, the same way an open drawer or row does.
4. **Don't change** the compact tile size, the grid layout, the click-to-open behavior or the uptime strips.
5. **Tests:**
   - The compact page renders an expand button per entry.
   - The details route returns the facts (host, networks, ports, a stream entry's MAC) and the health panel.
   - The route needs a login, and returns 404 for a deleted entry.

   Run `uvx ruff@0.15.17 check .` and the full `uvx --with-requirements requirements-dev.txt pytest -q`. Both must be green.
6. **Docs:**
   - Add a `CHANGELOG.md` entry under `[Unreleased]` → Added: "Compact view: an expand button opens an entry's details…". You own the CHANGELOG in this pair; the other agent won't touch it.
   - `README.md`: add one bullet to the "### v0.11.0" What's New block. Also update the Dashboards section's Compact description if it says details aren't available.
   - `docs/PRD.md`: §13.7 (where the Dashboard expand row is described) and the views section. Add a line on the Compact details dialog and the new route, and add revision row 0.93.

## Conventions to honor

- Jinja/Tailwind style matching the existing templates; Tabler icons; no new JS dependencies.
- Build DOM with DOM calls where you insert server text. Inserting the route's server-rendered HTML fragment is fine; it is our own escaped template.

## When done

1. Set this file's frontmatter: `status`, `completed` and `result`.
2. Move it to `prompts/done/` (or `prompts/failed/`). It is untracked, so use plain `mv`.
3. Don't edit `docs/decisions.md`; list decision notes in your report.
4. You are a spawned agent, so do **not** commit. Report back with:
   - the exact files changed;
   - a proposed `feat:` commit message;
   - the design choices;
   - the test results;
   - what to check in a browser.
