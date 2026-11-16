---
name: v070-05-rollup-and-filters
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: health_state rollup, shared health badge on all three views, status/source filters with filtered total, legacy mirror removed; tests, ruff and migration check green
---

# Task: Health rollup badge and status/source filters

Replace template-side status parsing with one rolled-up health state per
entry, rendered by one badge partial on all views, and add status and source
filters to the filter bar. Spec: PRD §13.6. Depends on v070-04.

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
- Read `view_helpers.py` (`group_and_sort_services`, `normalize_show_urlless`),
  the three view handlers in `routes_dashboard.py`,
  `templates/partials/filter_bar.html`, `static/js/dashboard.js` (filter
  input and `.view-control` handling), and the health-badge markup in
  `dashboard.html`, `tiled_dash.html`, `compact_dash.html`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **`health_state.py`:**
   - `entry_health(entry)` returns a small dataclass: `state` (up /
     degraded / down / unknown / none), `total`, `failing`, and
     `failures` (name plus message).
   - The rules are exactly the §13.1 table.
   - View handlers eager-load checks (`selectinload`), so there is no
     N+1.
2. **`partials/health_badge.html`:**
   - A state dot or pill with a tooltip listing failing checks and their
     messages, plus a compact variant for Compact.
   - Replace every legacy status parse in the three views (`.isdigit()`,
     `'Error: SSLError'`, `*_health_check_status`). Keep the per-URL
     link icons; only the health signal changes.
   - Compact's badge links to `/edit/<id>#health`.
3. **Remove the legacy mirror** (`# TEMP: removed in v070-05`) from the
   checker. `grep` must show no remaining reads of the deprecated
   columns outside migrations, backup export and `dbdump.html`.
4. **Filters:**
   - Add `status` and `source` params next to `show_urlless` (normalize
     functions plus filtering inside or before `group_and_sort_services`).
   - Add selects in `filter_bar.html` with the `view-control` class, so
     the existing JS keeps them in the URL across refresh.
   - `stale` = notifier entries where `is_docker_status_stale`.
   - "Total Services" shows filtered/total.
5. **Tests:**
   - The rollup truth table, including disabled checks and never-run.
   - Each filter value on each view (status, source and their
     combination with `show_urlless`).
   - Badge renders for every state.
   - No N+1: assert the query count stays flat with more entries, using
     SQLAlchemy event counting.

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
   failure), renamed with a date prefix (`<YYYY-MM-DD>-v070-05-rollup-and-filters.md`).
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
