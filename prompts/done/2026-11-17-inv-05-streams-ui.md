---
name: 2026-11-17-inv-05-streams-ui
status: completed        # pending | completed | failed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: Settings → Streams tab, stream pill/missing marker/source filter in the views, stream and manual edit-page changes, ingest scope in the key picker; tests, ruff green.
---

# Task: Streams UI — Settings → Streams, stream entries in the views and edit page

Build PRD §18.8 on top of the inv-04 backend. Use the `streams.py` functions;
don't duplicate their logic in routes.

## Before you start

- inv-04 must be completed. If it isn't, stop and report.
- Read `CLAUDE.md`, PRD §18 (all), `templates/settings.html` (how tabs, the
  Notifications tab and the Deleted tab are built), the Settings → API key form,
  `routes_dashboard.py` (settings routes, edit page, delete flow, filter bar),
  `templates/tiled_dash.html`, `dashboard.html`, `compact_dash.html`,
  `edit_entry.html`, and `static/js/` for the existing confirm-dialog and
  unsaved-guard patterns.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Settings → API:** the key scope select adds **Ingest (sidecars)** with a
   one-line hint.
2. **Settings → Streams** tab, per §18.8:
   - the rows, the pending highlight and the read-only Docker (register) row;
   - Preview (server-rendered table, or a JSON endpoint plus JS, matching the
     existing pattern);
   - Enable, Ignore, and Disable… / Delete… with a dialog that shows counts first,
     the three cleanup choices, "also clear the block list" on purge, and the
     customised entries listed by name;
   - inline edit of the display name and network filters;
   - the Blocked list with Unblock, and Link offers with Accept / Decline;
   - all POSTs CSRF-protected and admin only, with flash messages as elsewhere.
3. **Views:**
   - the stream pill (the stream's display name) where Docker entries show the
     Docker pill, on Dashboard, Tiled and Compact;
   - the "missing from latest snapshot" muted marker;
   - the source filter lists each stream.
4. **Edit page:**
   - stream entries: read-only MAC, IP, network, attributes and stream; the name
     stays editable (sets `ui_edit`); delete asks **Allow re-adding** / **Don't
     re-add**;
   - manual entries: the link-offer banner (Convert / Keep separate) and **Link to
     stream item…**.
5. **Tests:**
   - route tests for each action (CSRF on, admin only);
   - template rendering for a stream entry on each view;
   - the delete dialog's `block` path;
   - the link banner.
6. **Docs:**
   - README "Inventory streams and sidecars" section (see §18.8), with screenshots
     only if the existing README pattern uses them;
   - PRD §18.8 marked delivered, and the §18 title changed to "Delivered on `dev`"
     if every subsection is;
   - CLAUDE.md "Build Status" in-flight line;
   - CHANGELOG Added entry.

## Conventions to honor

- CLAUDE.md "Always — Definition of Done":
  - add a CHANGELOG `[Unreleased]` entry in operator language (not for a
    refactor-only change);
  - mark the PRD subsection "Delivered on `dev`" with an "As built" note for any
    deviation, and add a revision-history row;
  - update README where operator-facing behaviour changes.
- Lint with CI's pinned ruff, `uvx ruff@0.15.17 check .` (other versions disagree
  on import sorting). Run the full suite with `pytest -q`. Both must be green.
- Every new management route is registered in `mgmt_openapi.OPERATIONS` (tests
  enforce it) and gets MCP tools in `mcp/std_mcp.py` (read key: read tools only).
- Schema changes only through Alembic, with FK indexes in the same migration.
  `Migration check` (one head, upgrade on an empty DB) must pass.
- Keep the register contract and its safe-degradation guarantees intact
  (CLAUDE.md "Register Contract Rules").
- In your report, only claim doc edits that `git diff` shows.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top).
4. Do **not** commit. Prepare the working tree, then report back to the
   orchestrating session:
   - the file list (this prompt file and its move included);
   - a one-line commit message with the right prefix (`feat:` / `fix:` /
     `refactor:` / `docs:`), no `Co-authored-by:`;
   - test and lint results;
   - anything you deviated from or left undone.
   Never `git add -A`, never push.
