---
name: v090-06-tile-layout-preview
status: completed        # pending | completed | failed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: /tiled_preview added (v2 grid layout, scoped CSS, 3 tests); /tiled_dash byte-identical; 706 tests pass, ruff clean
---

# Task: Preview page for a new Tiled tile layout (current Tiled view untouched)

The operator wants service names easier to read on the Tiled view. Build the
proposed layout as a **separate, unlinked preview page**,
`/tiled_preview`, so they can compare it with real data before deciding.
The existing `/tiled_dash` view must render **byte-for-byte the same as
today**.

## Proposed tile layout (the operator's words, made concrete)

```
┌──────────────────────────────────────────────┐
│ [icon]  traefik-with-a-very-long-name……………… │  ← name uses the full width
│         em-docker02                          │  ← host, tight under the name (only when shown)
│         [exposure badges, if any]            │
│ ●  ⌂  🌐  🐳  📈  ·········  ⌨  ✎  🗑  ⌄     │  ← ONE icon row along the whole bottom
└──────────────────────────────────────────────┘
```

- **Icon** on the left at its current size (32px), vertically aligned with the
  name block.
- **Name** stretches from the icon to the tile's right edge, with nothing
  beside it. Single line, ellipsis on overflow, full name in `title` (as
  today).
- **Host** (when `entry.id in host_label_ids`, the same rule as now) sits
  directly under the name, close to it: no gap, a smaller line-height, small
  and muted.
- **Icons:** the status icons (health, internal, external, docker or link,
  widget) and the action icons (dozzle, edit, trash or lock, chevron) go in
  **one row along the full bottom width** of the tile.
  - Status icons are left-aligned and action icons right-aligned
    (`justify-content: space-between`).
  - Add a subtle top divider (`border-top: 1px solid var(--color-border)`)
    with a little padding above the row. Judge it in the screenshot and drop
    it if it looks heavy.
- The uptime strip, drawer, open state, headless state, hover, the `.show-uptime`
  padding, and the mobile touch-target rules still work.

## Before you start

- `templates/tiled_dash.html` (tile markup, lines ~75–206), the tile rules in
  `static/css/dashboard.css` (`.tile` … `.tile-chevron`, ~144–307, the
  `max-width: 639px` touch-target block, and `body.show-uptime .tile`).
- `routes_dashboard.tiled_dashboard`, plus `static/js/dashboard.js` and any
  JS that builds URLs or auto-refreshes. Check whether anything hard-codes
  `/tiled_dash` (filter selects, refresh, drawer, delete popover), so the
  controls stay on `/tiled_preview` while previewing.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Route.** `GET /tiled_preview` (`login_required`) renders the same
   template with the same context as `/tiled_dash`. Factor the handler body
   into one helper so the context isn't duplicated, and pass
   `tile_layout="v2"`. `/tiled_dash` passes nothing new that changes its
   output. Keep the active nav tab as Tiled, and add **no nav link**.
2. **Template.**
   - When `tile_layout == 'v2'`, add a class (`tile-layout-v2`) on a
     wrapping element such as `<main>` or each `.tile-container`.
   - Show a slim notice above the groups: "Layout preview — the normal
     Tiled view is unchanged." with a link back to the normal Tiled view
     (keep the query string).
   - Markup changes for v2 are allowed **only inside `{% if tile_layout ==
     'v2' %}` branches**. Prefer CSS-only: lay the tile out as a grid
     (`grid-template-columns: 32px 1fr`, with areas `icon details` /
     `bar bar`), turn `.tile-status-row` into a horizontal row spanning both
     columns, and put the two `.tile-icon-row`s at its ends.
   - Only restructure markup in a v2 branch if CSS can't place something.
3. **CSS.** Scope every new rule under `.tile-layout-v2`, so nothing outside
   the preview changes. Keep icon sizes and colours as today.
4. **JS.** Anything in the preview that navigates or refreshes must keep the
   operator on `/tiled_preview`. If the JS hard-codes `/tiled_dash`, make it
   use `location.pathname` or a data attribute. That change must not alter
   `/tiled_dash` behaviour.
5. **Tests:**
   - `/tiled_preview` returns 200 for a logged-in user, and redirects to
     login for anonymous users.
   - It contains the `tile-layout-v2` class and the notice.
   - `/tiled_dash` contains neither.
   - The host label rule still applies in the preview.
6. **Screenshots** with seeded entries: a long name, the duplicate pair
   `technitium` on `em-dns01` and `em-dns02`, a manual entry, one with a
   widget, one with exposure badges, and one locked. Use headless Chromium
   from the scratch venv
   `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`.
   It lacks `dnspython`, so run the server from the uv 3.11 env, and launch
   Chromium via `executable_path` from `~/.cache/ms-playwright`. The sandbox
   has no internet, so the Tailwind CDN won't load; inject minimal CSS as
   earlier agents did.
   - Take these shots:
     - `/tiled_preview` at 1400px and 390px;
     - `/tiled_dash` at 1400px for comparison;
     - the preview with one drawer open;
     - the preview with Show uptime on.
   - Save them in the scratchpad and report the absolute paths. Look at
     them yourself and fix anything clipped or overlapping, with one
     correction pass.
   - Stop the server by PID.
7. **Docs.** This is a temporary preview, not a shipped feature.
   - Don't add a CHANGELOG entry.
   - Add a `docs/decisions.md` entry: the preview exists to compare
     layouts. Before `/release-prep 0.9.0` it is either adopted (v2 becomes
     the Tiled layout, the preview route and the old CSS are removed, and a
     CHANGELOG entry is added) or deleted.
   - PRD: no change; say so in your report.
8. **Verify:**
   - `uvx ruff@0.15.17 check .`
   - The full suite on 3.11:
     `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
     (703 passed before this change).

## Conventions to honor

- `/tiled_dash` output unchanged.
- No new JS or CSS libraries.
- Use the existing CSS variables.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back to the orchestrating session: what you built, test
   and lint results (exact counts), screenshot absolute paths, decisions, and the
   exact file list + a proposed one-line commit message (`feat:` prefix, no
   `Co-authored-by:`). Never `git add -A`, never push.
