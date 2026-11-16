---
name: v071-01-header-health-counts
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: Filter bar shows clickable Total/Passing/Failing count chips (server-built links, active chip marked); tests, browser check and docs done
---

# Task: Clickable Total / Passing / Failing counts in the filter bar

Replace the filter bar's "Total Services: N" with three counts: **Total**,
**Passing** and **Failing**. Each one is a link that applies the matching
Status filter. This is a user request after v0.7.0 shipped, and it lands in
`[Unreleased]` for the next release.

## Before you start

- `CLAUDE.md` and `standards.md`.
- `docs/PRD.md` §13.6 (health rollup, badges and filters) and §13.1
  (health states).
- Code:
  - `templates/partials/filter_bar.html`: the "Total Services" span. Today
    it shows `total_entries` or `shown / all_entries_count`.
  - `view_helpers.py`: `matches_status`, `matches_source`, `_STATUS_STATES`,
    `normalize_status_filter`, `group_and_sort_services`.
  - `routes_dashboard.py`: `_load_view_entries` and the three view handlers.
  - `health_state.py`: `entry_health`.
  - `static/js/dashboard.js`: how the `.view-control` selects write query
    params and how auto-refresh keeps them.
- Tests: `tests/test_rollup_filters.py` (its filter/total tests and its
  query-count test).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## Design (decided)

- **Three counts** in the filter bar, in place of "Total Services":
  - `Total N`
  - `Passing N`: entries whose rollup state is `up` (the same set as
    `status=healthy`).
  - `Failing N`: `degraded` or `down` (the same set as `status=failing`).
- **What the counts cover:** the entries left after the **Source** and
  **Show URL-less** filters, but **ignoring the Status filter**, and
  ignoring the client-side text box. So each number equals what you see when
  you click it.
  - Compute all three in one pass, reusing `entry_health` (one rollup per
    entry), with no extra queries.
  - Pass them to the template as `health_counts = {total, passing, failing}`
    from all three views.
- **Each count is a link.** Total sets `status=all`, Passing sets
  `status=healthy` and Failing sets `status=failing`.
  - Keep every other current query param (`group_by`, `sort_in_group`,
    `show_urlless`, `source`, and the refresh param if one exists).
  - Build the link server-side from `request.args` and `url_for` the
    current endpoint, not in JS.
  - The link for the currently active status is highlighted
    (`aria-current="true"` plus an active style). The Status select stays and
    stays in sync, because it is driven by the same param.
- **Styling:**
  - Compact chips matching the existing filter-bar look.
  - Failing uses the red/down token when its count is above 0, otherwise
    neutral.
  - Passing uses the green/up token.
  - They must fit on mobile, inside the collapsible filter panel at 390 px.
- **Unknown and Not monitored** entries don't get their own count. They are
  in Total only, and the Status select still reaches them.
- Remove the old `shown / total` text. If a non-"all" Status filter is
  active, the highlighted chip already shows what is shown.

## What to do

1. Implement the design.
2. **Tests** (extend `tests/test_rollup_filters.py`, or add a new file):
   - The counts are correct for a seeded mix of states.
   - The counts ignore the Status filter but respect Source and Show
     URL-less.
   - Each link's href carries the right `status` and keeps the other
     params.
   - The active chip is marked.
   - Rendering works on all three views.
   - The query-count test still stays flat as entries are added.
3. **Browser check:** run the app locally with seeded entries in several
   health states. With headless Chromium, click each chip on Dashboard,
   Tiled and Compact. Confirm that the list matches the count, the Status
   select is in sync, and the params persist across a reload. Check desktop
   and 390 px, and read at least the desktop Dashboard screenshot and one
   390 px screenshot.
4. **Docs, in the same commit:**
   - CHANGELOG `[Unreleased]` (Added or Changed, in operator language).
   - README, where it describes the filter bar.
   - PRD §13.6: note the counts and add a revision row.
   - `docs/decisions.md` only if you make a non-obvious call.

## Conventions to honor

- Work on `dev`. Use the `feat:` prefix. No `Co-authored-by:` trailer.
  Never `git add -A`, never push.
- No schema change is expected.
- Before handing off, run `uvx ruff@0.15.17 check .` and `pytest -q`.
- There is a venv with requirements-dev and Playwright (cached Chromium) at
  `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`.
  Scratch files go in that scratchpad.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed `2026-11-15-v071-01-header-health-counts.md`. It is
   untracked, so use a plain `mv`.
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
