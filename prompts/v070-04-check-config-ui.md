---
name: v070-04-check-config-ui
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Health-check configuration UI on Add and Edit

Let operators configure URL checks and add/remove service checks (HTTP/HTTPS,
TCP, Ping) on the Edit and Add pages, and show flash messages on those pages.
Spec: PRD §13.5. Depends on v070-03.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§13** (the v0.7.0 plan) in full, plus **§5.6** (planned
  schema). The subsection named below is your spec. Where it and the code
  disagree, trust the code, follow the spirit of the PRD and record the
  call in `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.7.0 Dashboard and Monitoring design
  calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with
  tests, because `Test` is a required check.
- Read `templates/edit_entry.html`, `add_entry.html`, `routes_dashboard.py`
  add/edit handlers, `static/js/` for existing form JS patterns, and how
  `settings.html` renders flashes.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Edit page "Health checks" section** replaces the two toggles and
   the "Advanced health check" block:
   - Rows for the internal and external URL checks: enabled, mode,
     interval, timeout and verify TLS, with the target shown read-only.
   - A repeatable service-check list (name, type, target, mode/verify for
     HTTP only, interval, timeout, enabled) with add and remove.
   - Keep the JS small (template-row clone) in a static file. Mobile
     layout must work.
2. **Server-side validation** as in §13.5:
   - A failing field re-renders the page with the operator's input kept,
     plus an inline flash.
   - It must not drop other checks' edits.
   - Check rows are identified by id for updates; removed rows are
     deleted (their results cascade).
3. **Add page:** the same section (no ids yet).
4. **Flash display:** render flashed messages on Add and Edit (reuse the
   Settings markup in a partial). Then remove the "queued for Settings"
   caveat from the v0.6.9 decisions note by adding a superseding
   decisions entry; don't edit the old one.
5. **Register never touches `service` rows.** Add a test that proves it.
6. **Tests:**
   - Create, update and delete service checks via Edit.
   - Validation for each type (bad URL, bad port, empty ping target,
     interval/timeout bounds) re-renders with input kept and a flash
     visible.
   - Add with a service check.
   - Register leaves service checks alone.
   - CSRF is required.

## Conventions to honor

- Work on `dev`. Commit prefix `feat:` (or `fix:`/`refactor:` if that is
  more accurate). No `Co-authored-by:` trailer. Never `git add -A`, never
  push.
- Schema changes go through **one** new Alembic migration with a single
  head. Every FK gets its index in the same migration. Use
  `batch_alter_table` for SQLite column changes. `alembic upgrade head`
  must work on an empty DB **and** on a DB at the current head with data.
  Write a downgrade.
- Read settings from `app.config`. Never call `load_settings()` in
  handlers. New settings go in `settings_loader.py` (type and default),
  `settings.example.yml` and the README settings reference.
- UI POSTs carry CSRF (`stdPost` for JS). Templates match the existing
  Tabler-icon and Tailwind vocabulary.
- **Definition of done (same commit as the code):**
  - A CHANGELOG `[Unreleased]` entry in operator language.
  - The PRD subsection is marked "— Delivered (unreleased)" with a short
    "As built:" paragraph, and a revision-history row is added at the
    bottom of the table.
  - The README is updated where operator-facing behaviour changed.
  - Non-obvious calls go in `docs/decisions.md`.
- Before handing off, run `ruff check .`, `pytest -q` and
  `alembic upgrade head` on a fresh DB. Report the results verbatim if
  anything fails.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed with a date prefix (`<YYYY-MM-DD>-v070-04-check-config-ui.md`).
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on `dev`.
   Never `git add -A`, never push, never auto-commit.
