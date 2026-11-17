---
name: v090-11-health-tinted-rows
status: completed         # pending | completed | failed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: Soft amber/red tint on degraded/down entries across Dashboard, Tiled, Compact; tests, docs done
---

# Task: Soft amber/red background for degraded/down entries on all three views

When an entry's rolled-up health is **degraded** (amber) or **down** (red),
give its Dashboard table row, its Tiled tile and its Compact tile a **soft**
tinted background, so problems stand out at a glance. Up, unknown and none
are unchanged.

## Before you start

- `templates/partials/health_badge.html`, which uses the `entry_health(entry)`
  Jinja global.
- `templates/dashboard.html`: the entry `<tr class="... group-entry">` around
  line 51, and the `health-expand-row` around line 247.
- `templates/tiled_dash.html`: `.tile`.
- `templates/compact_dash.html`: `.compact-tile`.
- `static/css/dashboard.css`: `--color-status-warn` and
  `--color-status-bad`, the `.tile` rules, hover and open states, and the
  compact rules.
- Any JS that refreshes health in place (auto-refresh in
  `static/js/dashboard.js`, `uptime_strip.js`). Find out whether
  auto-refresh reloads the whole page or patches nodes, so the tint stays
  correct after a refresh.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Template.** Add a class `entry-health-<state>` to:
   - the Dashboard entry row (and its expanded health row, if that looks
     right);
   - the `.tile`;
   - the `.compact-tile`.

   Compute the state once per entry (`{% set _h = entry_health(entry) %}`),
   or pass it in. Don't call it repeatedly in a loop body if avoidable.
2. **CSS.**
   - Use soft tints from the existing tokens:
     `color-mix(in srgb, var(--color-status-warn) 12%, var(--color-bg-surface))`
     for degraded, and the same with `--color-status-bad` for down. Tune it
     to around 10–15%, so the text keeps contrast and the tint reads as
     "soft".
   - Optionally add a slightly stronger left border or edge in the same
     hue.
   - For the Dashboard table, beat the Tailwind `hover:bg-*` and row classes
     without `!important` if you can. If not, scope a hover variant (a
     slightly stronger tint on hover) so hover still gives feedback.
   - Keep the tile hover border, `.tile-open` accent and drawer joins
     working. The open drawer may keep a neutral background.
   - If `color-mix` is a concern, add a fallback `rgba(...)` declaration
     before it.
3. **Refresh.** If auto-refresh patches the DOM instead of reloading,
   update the class there too. If it reloads, nothing extra is needed. Say
   which in your report.
4. **Tests.** Seed one entry each that is up, degraded and down, with checks
   whose `last_ok` gives those states. Assert that each view (`/`,
   `/tiled_dash`, `/compact_dash`) renders `entry-health-degraded` and
   `entry-health-down` on the right elements, and no tint class on the up
   entry.
5. **Screenshots** (same harness as previous agents: the scratch venv
   Playwright with `executable_path`, the server from the uv 3.11 env,
   injected CSS because there's no Tailwind CDN). Show up, degraded and down
   entries on all three views at 1400px, and Tiled at 390px. Look at them,
   do one fix pass if the tint is too strong or too weak, and report the
   absolute paths. Stop the server by PID.
6. **Docs:**
   - `CHANGELOG.md` `[Unreleased]` → Changed: "Degraded and down services
     get a soft amber or red background on the Dashboard, Tiled and Compact
     views."
   - README: the views and health section.
   - PRD: add §15.10, with the health-state UI in §13.6, and bump the
     revision history.
7. **Verify:**
   - `uvx ruff@0.15.17 check .`
   - The full suite on 3.11:
     `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
     (762 passed before this change).

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back: what you built, test and lint results (exact
   counts), screenshot paths, refresh behaviour, and the exact file list + a proposed
   one-line commit message (`feat:` prefix, no `Co-authored-by:`). Never `git add -A`,
   never push.
