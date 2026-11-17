---
name: v090-07-exposure-icons
status: completed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: Exposure badges one per layer (no count, route count in hover), v2 bottom-row placement, tests, docs
---

# Task: One exposure icon per layer, and put them in the v2 tile's bottom icon row

The operator looked at `/tiled_preview` with real data and asked:

1. Why do traefik services show **two traefik icons**?
   `templates/partials/exposure_badges.html` renders one badge per
   `ServiceExposure` row, and a typical traefik container has several routers
   (for example an HTTP→HTTPS redirect router plus the HTTPS router, or an
   internal and an external hostname). So it shows the same logo once per
   router.
2. Shouldn't the exposure icons be in the bottom icon row? Yes, on the v2
   layout.

## Before you start

- `templates/partials/exposure_badges.html` and the `.exposure-*` CSS in
  `static/css/dashboard.css` (~line 87).
- Every include of the partial (`grep -rn exposure_badges templates`).
- `templates/tiled_dash.html`, including the `tile_layout == 'v2'` branches
  and `.tile-layout-v2` CSS added in `prompts/done/2026-11-16-v090-06-tile-layout-preview.md`.
- `models.ServiceExposure` fields: layer, hostname, path_prefix, tls, auth,
  …

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Group by layer (all views).** Change the partial so it shows **one
   badge per layer**, in first-seen order, instead of one per row. Do the
   grouping in Python, not in Jinja: add a small helper (e.g.
   `view_helpers.exposure_layers(exposures)` or a filter) that returns, for
   each layer:
   - `layer`;
   - `count`;
   - `tls`: true if any row has TLS;
   - `labeled`: true if any row has an explicit hostname;
   - `auth`: true if any row requires auth;
   - `routes`: a list of `hostname + path_prefix`, each with its TLS and auth,
     de-duplicated.

   The badge keeps today's look: the brand logo, a lock if TLS, a pencil if
   labeled. Its `title` lists every route, one per line, e.g.
   `traefik — 2 routes\nsonarr.crzynet.me (TLS)\nsonarr.lan`. When `count
   > 1`, show a small superscript-style count beside the logo (`×2`), styled
   like the existing overflow `+N`.
   - Keep the "up to 3 shown, +N overflow" rule, now counted in layers.
   - This applies everywhere the partial is used: the normal Tiled view,
     Dashboard table, Compact if used, and the preview.
2. **v2: move the exposure icons into the bottom row.**
   - In the `tile_layout == 'v2'` path only, render the exposure badges
     **inside the bottom icon row**, after the status icons (health,
     internal, external, docker or link, widget) and before the right-aligned
     action icons. Put a small gap or thin separator between the status
     icons and the exposure badges.
   - Don't render them in the name block in v2, so the name block is just
     name and host and tiles with and without exposures line up at the same
     height.
   - Markup changes go only inside `{% if tile_layout == 'v2' %}` branches;
     `/tiled_dash` keeps the badges under the name as today, apart from the
     per-layer grouping in step 1.
   - Size the badges to sit on the same baseline as the 16px status icons.
   - At 390px the row must still fit, so let the exposure group shrink or
     wrap neatly inside the row; it must never push the action icons off the
     tile.
3. **Tests:**
   - The helper:
     - two traefik rows give one layer with count 2 and both routes;
     - a mix of traefik and cloudflare keeps order;
     - TLS, labeled and auth aggregate as "any";
     - duplicate routes are de-duplicated;
     - the overflow is counted in layers.
   - Rendering:
     - an entry with two traefik exposures renders one traefik logo plus `×2`
       on `/tiled_dash` and on the Dashboard table;
     - on `/tiled_preview` the badges are inside the bottom row element and
       not in `.tile-details`.
4. **Screenshots** (same harness as the previous agent, described in the
   v090-06 prompt: the scratch venv Playwright with `executable_path`, the
   server from the uv 3.11 env, injected CSS because there's no Tailwind
   CDN).
   - Seed:
     - an entry with two traefik routers (one TLS with a hostname, one plain);
     - one with traefik and cloudflare;
     - one with four layers, to show the overflow;
     - plain entries.
   - Take `/tiled_preview` at 1400px and 390px, and `/tiled_dash` at 1400px.
     Look at them, fix anything clipped (one pass), and report the absolute
     paths. Stop the server by PID.
5. **Docs:**
   - `CHANGELOG.md` `[Unreleased]` → Changed: "Exposure icons show once per
     proxy layer (with a count when a service has several routes) instead
     of once per route; hover lists every route."
   - Add to the existing preview entry in `docs/decisions.md`.
   - PRD: check whether the exposure-badge rendering is described (it may be
     in the v0.6.x sections). Update it and bump the revision history, or say
     "PRD reviewed, no change needed".
6. **Verify:**
   - `uvx ruff@0.15.17 check .`
   - The full suite on 3.11:
     `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
     (706 passed before this change).

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back: what you built, test and lint results (exact
   counts), screenshot absolute paths, decisions, and the exact file list + a proposed
   one-line commit message (`feat:` prefix, no `Co-authored-by:`). Never `git add -A`,
   never push.
