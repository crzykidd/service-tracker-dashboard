---
name: v090-10-adopt-tile-v2-and-detail-message
status: completed         # pending | completed | failed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: A root cause = Body-mode probe dropped the 4xx/5xx reply reason (fixed); B v2 tile layout adopted, preview removed
---

# Task: (A) Detail panel failure message, (B) adopt the v2 tile layout

Two separate changes. Report them as **two commits** (two file lists and two
messages). Do A first.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## A. Detail panel shows "503" instead of the new failure message

### Operator report (v0.9.0 `:dev`, real data)

`/health/summary` and `GET /api/v1/entries/41` return `last.message =
"503: Mgmt1: Scope 'Mgmt1' not found ..."`. But the expanded Internal URL
check, in both the Tiled drawer and the Dashboard row, shows only `503`
under `Checked 1m ago · 2 ms · status 503`. The panel's message line should
render the same text the API returns, falling back to the status code only
when the message is empty. Check the history strip tooltips too: they may
read result rows rather than `last.message`.

### What the orchestrator already checked (verify, don't trust)

- `static/js/health_detail.js` (~line 139) renders `c.message` when
  `c.state === 'down'`.
- `health_history.check_payload` sets `message: check.last_message`.
- `mgmt_serializers.check_out` uses the same `check.last_message`.
- `templates/partials/check_result_text.html` prefers `last_message` too.

So on paper the panel and the API read the same column. Find out why the
operator sees a difference. Candidates:

1. **Different checks.** The API value may come from a different check
   (e.g. a service check on `/healthz`) than the panel's *Internal URL* check
   (the entry's internal URL, possibly a different path whose 503 has an
   empty body, which correctly gives just `503`). Look at the entry and
   check payload shapes to see how an operator could conflate them.
2. **Bar tooltips and Recent failures read `HealthResult.message`** from
   history rows. Rows written before v090-08 legitimately say `503`. That's
   expected for old rows; confirm new rows carry the full text.
3. **A genuine bug.** For example a code path that writes `last_message`
   from something other than `result.message`: "Check now"
   (`jobs.request_run`), compaction, the cert-condition wrapper, or
   `record_check_result`. Or the panel requesting a stale or cached
   response, or a Jinja/JS path rendering `status_code` instead. Grep
   `last_message`, `message` and `status_code` across `jobs.py`,
   `checker.py`, `health_history.py`, `routes_dashboard.py`,
   `templates/` and `static/js/`.
4. **Browser cache of `health_detail.js` / the JSON.** Check how static
   files are versioned (cache busting) and whether `/service/<id>/health`
   sets cache headers.

### Do

- **Reproduce with a test.** Use an entry with a URL check whose last result
  has `last_message = "503: something"` and `last_status_code = 503`, plus
  a `HealthResult` row with the same message. Assert that
  `GET /service/<id>/health` returns that message for the check, in
  `message`, in the bar's `messages` and in `failures[].message`. Also
  exercise the real probe → `record_check_result` path with a mocked 503
  JSON reply, including the "Check now" path, and assert that
  `last_message` and the stored result row both carry the full text.
- **If you find a bug, fix it.** Also make the panel's message line
  explicitly fall back: `c.message || ('status ' + c.status_code)` when
  down.
- **If there is no bug** (the explanation is candidate 1 or 2), make the
  panel clearer so the confusion can't recur:
  - each check block shows its check name and target clearly (it may
    already);
  - for down checks, always show the message line, falling back to
    `status <code>` when the message is empty, so an empty-body 503 reads
    `status 503 (empty reply)`.
- **Static cache busting.** If static JS isn't versioned, add a version
  query string (`?v=<app version or file mtime>`) to the JS and CSS includes
  in `base.html`, so operators get new JS after an upgrade. Do this either
  way: it's cheap and avoids this class of confusion.
- **Report the root cause plainly** in your hand-back, so the orchestrator
  can tell the operator what was going on.
- **Docs:**
  - CHANGELOG `[Unreleased]` → Fixed, only if there was a real bug,
    worded for the operator. Cache busting goes under Changed or Fixed as
    appropriate.
  - `docs/decisions.md` entry.

## B. Adopt the v2 tile layout as the Tiled view

The operator chose the `/tiled_preview` layout. Make it **the** Tiled
layout and remove the preview:

- Make the v2 structure the default rendering in `templates/tiled_dash.html`:
  - name and host at the top, full width;
  - one bottom row: status icons, then exposure badges, then
    right-aligned actions;
  - the divider.

  Remove the `tile_layout` branches and the preview notice. Keep the markup
  simple: write v2 as the only path, not a renamed copy of the branch.
- CSS: fold the `.tile-layout-v2` rules into the base tile rules and delete
  the old layout's rules that no longer apply (the two-row
  `.tile-status-row` column layout and so on). Don't leave dead CSS.
  Keep the mobile touch-target and `show-uptime` rules working.
- Remove the `/tiled_preview` route. Unknown URLs give a 404, which is fine.
  Fold `_render_tiled` back if it now has one caller, or keep it if that
  reads cleaner.
- Tests: update the preview tests into tests of `/tiled_dash`:
  - exposure badges in the bottom row, not in `.tile-details`;
  - the host label under the name;
  - `/tiled_preview` returns 404.
- Screenshots: headless, using the same harness as previous agents (the
  scratch venv Playwright with `executable_path`, the server from the uv 3.11
  env, injected CSS because there's no Tailwind CDN).
  - Seed:
    - long names;
    - a duplicate-host pair;
    - exposures (several layers);
    - a widget;
    - a lock;
    - a manual entry.
  - Take `/tiled_dash` at 1400px and 390px, one with a drawer open and one
    with Show uptime on. Look at them, do one fix pass, and report the
    absolute paths. Stop the server by PID.
- Docs:
  - CHANGELOG `[Unreleased]` → Changed: "Tiled view: tiles show the icon on
    the left, the name across the full tile width (host underneath when
    shown), and all status, exposure and action icons in one row along the
    bottom."
  - README: the Tiled view description.
  - PRD: the Tiled tile description (§8.x; find it), add §15.8, and bump
    the revision history.
  - `docs/decisions.md`: update the preview entry to "adopted".

## Verify (after each part)

- `uvx ruff@0.15.17 check .`
- The full suite on 3.11:
  `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
  (755 passed before this change).

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
   Include it in commit B's file list.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back:
   - the A root cause;
   - for each part: what changed, test and lint results (exact counts), and
     screenshot paths;
   - **two** file lists with a proposed message each (A: `fix:`, B: `feat:`;
     no `Co-authored-by:`).
   If a file has changes for both parts (e.g. CHANGELOG, decisions.md,
   base.html), say which hunks belong where, or propose that it goes
   entirely in commit B and say so. Never `git add -A`, never push.
