---
name: v071-02-inline-uptime-strip
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: Show uptime toggle (cookie) + inline 24h strips on all three views, GET /health/strips with a fixed query count; tests, lint, browser check pass
---

# Task: "Show uptime" view toggle with an inline 24h strip per service

Add a **Show uptime** checkbox to the filter bar. It is off by default and
remembered in a browser cookie. When it is on, every service on Dashboard,
Tiled and Compact shows a compact 24-hour uptime strip, so you can scan
history without opening each detail panel. This is a user request after
v0.7.0, and it lands in `[Unreleased]`. It runs after
`v071-01-header-health-counts` (which also edits `filter_bar.html`); build on
that state.

## Before you start

- `CLAUDE.md`, `standards.md`, `docs/PRD.md` §13.6–§13.8.
- Code:
  - `health_history.py`: `RANGES`, `_rows`, `_bucketise`, `bars`,
    `entry_payload`, `check_payload`. The strip must reuse this bucketing.
  - `health_state.py`: `check_counts`, which says which checks count
    (enabled, has a target, container rules).
  - `routes_dashboard.py`: `/service/<id>/health` and the view handlers.
  - `templates/partials/filter_bar.html` (as left by v071-01),
    `templates/partials/health_badge.html`, `templates/dashboard.html`,
    `templates/tiled_dash.html`, `templates/compact_dash.html`.
  - `static/js/health_detail.js` (bar rendering and tooltip; reuse its
    pieces) and `static/js/dashboard.js` (auto-refresh, and how
    `refreshInterval` is persisted).
  - `static/css/dashboard.css` (`.health-bar` tokens).
- Tests: `tests/test_health_detail.py` and `tests/test_rollup_filters.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## Design (decided)

- **The toggle:** a "Show uptime" checkbox in the filter bar next to "Show
  URL-less", on all three views.
  - Persisted in a **cookie** named `std_show_uptime` (`1` or `0`;
    `Path=/`, `SameSite=Lax`, max-age one year). Default is off when the
    cookie is absent.
  - It is a cookie rather than localStorage, as the user asked, so the
    server can render the checkbox state and the strip containers without a
    flash.
  - It is **not** a URL query param and doesn't touch `view-control`
    handling.
  - Toggling sets the cookie and shows or hides the strips **without a page
    reload**: a body class plus a lazy fetch.
- **The strip:**
  - One per **service** (not per check). It shows 48 half-hour bars covering
    the last 24 hours, from the entry's checks that count (same rule as the
    rollup).
  - A bar is red if any of those checks failed in that slot, green if all
    samples passed, and grey with no samples.
  - The overall 24h uptime % (Σ ok samples ÷ Σ samples across those checks)
    is shown next to it.
  - Hovering or tapping a bar shows the slot time, ok/failed counts and up to
    3 failure messages. Reuse the detail panel's tooltip.
  - An entry with no checks that count shows nothing, or a muted "—".
- **Placement:**
  - **Dashboard:** under the badge in the Health column.
  - **Tiled:** a thin strip across the tile under the header row.
  - **Compact:** a very thin strip at the bottom of the tile, with no
    uptime % text.
  - It must fit at 390 px; on narrow screens the bar gaps collapse the same
    way the detail panel's do.
- **Data, in one request per page load:**
  - New endpoint `GET /health/strips?ids=1,2,3` (login required, JSON,
    `ids` capped at 500, unknown or soft-deleted ids silently omitted).
  - It returns `{id: {bars: [{start, end, ok, fail, messages}], uptime}}`
    for each entry.
  - Implement it in `health_history.py` with a **bounded number of
    queries**: one query for all relevant `health_result` rows in the
    window, grouped in Python. Not one query per entry or per check. A test
    must pin this.
  - The JS collects the ids on the page, fetches once when the toggle is on
    (on load if the cookie says so, or when it is ticked), and re-fetches on
    each auto-refresh cycle only while it is on. When it is off, nothing is
    fetched.
- **No schema change.** The register contract is untouched.

## What to do

1. Implement the design.
2. **Tests:**
   - Endpoint auth, shape, the id cap, omission of deleted or unknown ids,
     and the query count staying flat between 3 and 30 entries.
   - Bucket aggregation across multiple checks, including a compacted range
     row spanning buckets and the uptime maths.
   - The checkbox renders checked when the `std_show_uptime=1` cookie is
     sent and unchecked by default, on all three views.
   - The strip containers render on each view.
3. **Browser check:** run the app locally with seeded history. Use headless
   Chromium on Dashboard, Tiled and Compact at desktop and 390 px:
   - It is off by default with no fetch: check the network log for no
     `/health/strips` call.
   - Ticking it shows the strips without a reload.
   - Reloading keeps it on, because of the cookie.
   - Unticking hides the strips and the next refresh does no fetch.
   - The tooltip works.

   Read the desktop screenshots of all three views with the strips on, and
   one 390 px screenshot. There must be no console errors.
4. **Docs, in the same commit:**
   - CHANGELOG `[Unreleased]`.
   - README filter bar and health section.
   - PRD §13.6 or §13.7: a short addition plus a revision row.
   - `docs/decisions.md` for any non-obvious call.

## Conventions to honor

- Work on `dev`. Use the `feat:` prefix. No `Co-authored-by:` trailer. Never
  `git add -A`, never push.
- The cookie value is only ever compared to `'1'`. Never reflect it into the
  page unescaped.
- JS POSTs aren't needed here. Use GET with `credentials: 'same-origin'`.
- Before handing off, run `uvx ruff@0.15.17 check .` and `pytest -q`.
- There is a venv with requirements-dev and Playwright (cached Chromium) at
  `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`.
  Scratch files go in that scratchpad.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed `2026-11-15-v071-02-inline-uptime-strip.md`. It is
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
