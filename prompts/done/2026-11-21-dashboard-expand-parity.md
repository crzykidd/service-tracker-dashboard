---
name: 2026-11-21-dashboard-expand-parity
status: completed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: Dashboard expand row now shows shared entry facts (partials/entry_facts.html) beside health detail in two columns; tests and lint green
---

# Task: Give the main dashboard's expanded row the same detail as the tile drawer, in two columns

On the tiled view (`templates/tiled_dash.html`), the chevron opens a drawer (`.tile-drawer`, around lines 214–420) that shows:

- Host and About (description);
- Stack;
- the Internal and External URLs, each with its last check result;
- Docker status, with time since the last update and the image tag;
- stream facts (stream, missing since, stale) and network facts (IP, MAC, network);
- Networks, with aliases;
- published and exposed ports;
- exposure observations (layer, hostname, path, TLS, auth);
- widget data cards;
- health detail.

On the main dashboard (`templates/dashboard.html`), the expand row (`.health-expand-row`, around line 252) shows only `partials/health_detail.html`: health history, plus IP, MAC and network facts for stream entries. The operator wants the main dashboard expansion to carry all the same information, laid out in two columns.

## Before you start

- Read `CLAUDE.md`, then `templates/tiled_dash.html`, `templates/dashboard.html` and `templates/partials/health_detail.html`.
- Read the drawer and expand CSS in `static/css/dashboard.css`, and the expand/drawer JS: `static/js/dashboard.js` and `static/js/health_detail.js`. Health detail loads lazily when the panel opens.
- Find the tests that render these views (`grep -l "tiled_dash\|dashboard.html\|health-expand\|drawer" tests/*.py`) and keep them passing.
- Another agent is editing `README.md`, `docs/PRD.md`, `settings.example.yml` and new `docs/*.md` files right now. **Do not touch those files or `docs/decisions.md`.** Put any decision notes in your report instead; the orchestrator records them.

## Working tree check

Run `git status --porcelain`. The README, PRD, `settings.example.yml`, `docs/*.md` and readme-revamp prompt changes belong to the other agent: ignore them. If any file *you* need is dirty, stop and report.

## What to do

1. **Make one shared partial for the info rows.** Move the drawer's info rows (Host through Widget, not Health and not the action row) into a new partial, e.g. `templates/partials/entry_facts.html`.
   - It takes `entry` from context, plus `widget_values`, `widget_fields` and `stream_health`, which are already in both views' contexts. Check `routes_dashboard.py` and add anything missing to the main dashboard's context.
   - The tile drawer includes the partial, so its output is unchanged.
2. **Lay out the main dashboard expand row in two columns.**
   - Left column: the shared entry facts.
   - Right column: the health detail, `{% with hide_facts=true %}`, so IP, MAC and network aren't shown twice.
   - Wide screens get side-by-side columns (CSS grid, e.g. `grid-template-columns: minmax(0,1fr) minmax(0,1fr)`). Below `md`, the columns stack.
   - Reuse the drawer's label/value styling so both views look consistent. Scope any new CSS so the tile drawer doesn't change.
   - If the facts column is clearly too tall next to the health panel, it's fine to lay the facts out as a two-column label/value grid inside the left column. Use your judgment and say what you chose.
3. **Keep the existing behavior:**
   - the expand button, `aria-expanded`, and lazy-loading health detail on first open;
   - the `entry-health-*` tint on the expand row;
   - group collapse hiding the expand rows (`data-group-id`);
   - the colspan.
   - Don't duplicate actions that are already in the row (Edit, Delete, Dozzle).
4. **Check the main dashboard's other filters and views** (the status filter and search, if they show or hide rows) still treat the expand row correctly.
5. **Tests:**
   - Add a test that the main dashboard expand row renders the shared facts (e.g. Host, Networks, Ports, a stream entry's MAC, an exposure).
   - Add a test that the tile drawer still renders the same facts.
   - Run lint, `uvx ruff@0.15.17 check .`, and the full suite, `uvx --with-requirements requirements-dev.txt pytest -q`. Both must be green.
6. **Docs:**
   - Add a `CHANGELOG.md` entry under `[Unreleased]` → Changed: "The main dashboard's expanded row shows the same details as the tile drawer…".
   - Don't edit the PRD or README (another agent owns them right now). Tell me in your report whether the PRD's dashboard-view description needs a line, and quote the section, so I can add it.

## Conventions to honor

- Jinja/Tailwind style matching the existing templates; Tabler icons; no new JS dependencies.
- Don't change the compact view or the mobile layout, except where the shared partial requires it.

## When done

1. Set this file's frontmatter: `status`, `completed` (the date) and `result` (one line).
2. `git mv` this file into `prompts/done/` (or `prompts/failed/`).
3. Do **not** edit `docs/decisions.md`; put any non-obvious decisions in your report.
4. You are a spawned agent, so do **not** commit. Report back with:
   - the exact files changed and a proposed one-line `feat:` or `fix:` commit message;
   - the layout choices;
   - the test results;
   - the PRD note;
   - anything left for a browser check.
