---
name: 2026-11-16-version-in-ui
status: completed
created: 2026-11-16
model: sonnet
completed: 2026-11-16
result: Version in header (channel-aware, click for What's New), cached server-side GitHub update check with settings, API/MCP fields; ruff clean, 804 tests pass
---

# Task: Show the running version in the UI, with update and dev-build awareness

Show the running STD version next to the "Service Tracker Dashboard" header.
Flag dev builds and link them to their commit. Show a subtle "update
available → vX.Y.Z" link when GitHub has a newer release. The GitHub check
runs server-side, is driven by page loads, is cached, can be turned off, and
never blocks a page render.

## Before you start

- Read `CLAUDE.md`, `standards.md`, `docs/PRD.md` (§3 architecture, §14
  management API, §15 v0.9.0) and the newest entries in `docs/decisions.md`.
- Current version plumbing (already there; build on it, don't replace it):
  - `Dockerfile` writes `/app/version.txt` as `key=value` lines: `version`
    (from `VERSION`), `commit` (from the `GIT_COMMIT` build arg = full SHA),
    and `build_time`.
  - `.github/workflows/publish.yml` passes `GIT_COMMIT=${{ github.sha }}` and
    builds `:dev`/`:sha-` on push to dev, `:latest`/`:sha-` on push to main,
    and `:latest`/`:X.Y.Z`/`:X` on a published release.
  - `app.py` `read_version_info()` loads it into `app.config['VERSION_INFO']`
    and falls back to the repo `VERSION` file on local runs. A context
    processor exposes `version_info` to every template.
  - `templates/settings.html` About shows version/commit/build time.
    `templates/base.html` sets `data-std-version`. The What's New popup uses
    `/api/v1/changelog` (in `routes_dashboard.py`).
  - `routes_mgmt_api.py` `whoami` returns `version`. The MCP
    (`mcp/std_mcp.py`) compares versions from it.
  - Dashboard auto-refresh (`static/js/dashboard.js`) reloads the whole page
    (default 60s; 0 = off).
- gunicorn runs exactly ONE worker, so a process-local cache plus a
  background thread is safe.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

### 1. Build channel

- Add a `BUILD_CHANNEL` build arg (default `local`) in the `Dockerfile` and
  write `channel=<value>` into `version.txt`.
- In `publish.yml`, set it from the trigger: a published release →
  `release`; push to `main` → `main`; push to `dev` → `dev`; PR builds →
  `pr` (or `dev`; pick one and record it).
- In `read_version_info()`, a local run with no `version.txt` gets
  `channel=local` and `commit=unknown`. Make sure the keys `version`,
  `commit`, `channel` and `build_time` are always present.
- Add a small helper (e.g. a `version_check.py` module) that derives a short
  SHA and a display string:
  - `release` → `v0.9.0`;
  - `main` → `v0.9.0` with a "main" marker;
  - `dev` / `local` / `pr` → `dev · 0.9.0+sha-abc1234`, or `dev · 0.9.0`
    when the commit is unknown.
  - The `v` prefix appears only in display. `VERSION` stays bare.

### 2. Header display

- After the "Service Tracker Dashboard" header in `templates/base.html` (on
  every page that uses it), show the version subtly, at low emphasis and
  small size.
- **Clicking the version opens the existing What's New popup** for the
  running version. Reuse the popup's JS; don't build a new one.
- Dev, main and local builds also link the short SHA to
  `https://github.com/crzykidd/service-tracker-dashboard/commit/<sha>`,
  when the commit is known.
- When an update is available, show a separate subtle link,
  `update available → vX.Y.Z`, to that release's `html_url`.
- Keep it compact at phone width (390px); it may wrap under the title or
  hide the dev SHA on narrow screens.

### 3. Update check (operator decisions, 2026-11-16, binding)

- **Releases only.** Use
  `GET https://api.github.com/repos/crzykidd/service-tracker-dashboard/releases/latest`.
  Don't compare against the dev branch head.
- **Page-load driven, not a scheduler job.** On a page render, if the
  cached result is older than the interval (**default 6 hours**), start a
  refresh in a background thread. Allow at most one in flight (use a lock).
  The page renders with the cached value immediately; it never waits on
  GitHub. If nobody loads a page, no check runs.
- **While a page stays open:** dashboard auto-refresh reloads the page, so
  the page-load path already covers it. For pages without auto-refresh, or
  with auto-refresh off, add a small JS timer. Every interval, it calls a
  lightweight login-protected endpoint (e.g. `GET /api/update-status`,
  inside the dashboard blueprint, not the management API). The endpoint
  starts a refresh if the cache is stale and returns the cached status. The
  JS updates the header link in place. Keep the timer simple; checking once
  an hour that the cache isn't stale is fine.
- **Server-side only.** Browsers never call GitHub.
- **No auth.** Send a generic `User-Agent` (e.g.
  `service-tracker-dashboard/<version>`; no personal data), a short timeout
  (~5s), and `Accept: application/vnd.github+json`. Respect rate limits:
  honour `X-RateLimit-Remaining`/`Reset` and `Retry-After`, and optionally
  use `ETag`/`If-None-Match`.
- **On error, keep the last good value and back off.** Use exponential
  backoff from the interval base, capped at e.g. 24h. Log at warning level,
  not on every page load.
- **Comparison:** parse the release `tag_name` (strip `v`) as semver and
  compare it with `VERSION`. `update_available` is true only when
  latest > running. A dev build `0.9.0+sha…` against latest `0.9.0` is
  **not** an update. Skip drafts and prereleases (`releases/latest` already
  does). If the version can't be parsed, show no update link.
- **Persistence:** an in-memory cache is enough. Optionally persist the last
  good result (latest version, `html_url`, `checked_at`) in the DB settings
  store so a restart doesn't refetch at once. Your call; record it.
- **Setting (DB runtime setting, in the Settings UI and the management
  API):**
  - `update_check_enabled` (default **on**);
  - `update_check_interval_hours` (default **6**, minimum 1).
  - Follow the existing DB runtime-settings pattern (see
    `settings_store.py`, the Setting model and how existing runtime settings
    appear on the Settings page and in the management API `settings`
    endpoints, `mgmt_schemas.py`, `mgmt_openapi.py`). When disabled: no
    fetch at all, no update link, and About says "Update check disabled".
- **Settings → About:** show channel, short commit (linked), build time,
  latest release seen, last checked time, and last error (if any).

### 4. API / MCP

- Extend management API `whoami` (and/or `/api/v1/config`, whichever
  already carries instance facts; check both) with `commit`, `channel`,
  `build_time`, and `update: {enabled, latest_version, update_available,
  release_url, checked_at}`. These fields are additive; don't change
  existing ones. Update `mgmt_openapi.py` and the response TypedDicts.
- Have the MCP surface the new fields where it already reports the STD
  version. Don't change the MCP's version-compatibility logic.

### 5. Tests (pytest, `tests/`)

- Mock HTTP; never hit GitHub in tests. Cover:
  - `read_version_info` defaults (no file / file without `channel`);
  - display strings per channel;
  - the semver comparison (newer, equal, dev-of-same, unparseable);
  - stale vs fresh cache: a refresh starts only when stale, and only one at
    a time;
  - an error keeps the last good value and sets the backoff;
  - disabled means no fetch;
  - the status endpoint needs login;
  - the header renders the version and the update link;
  - `whoami` / config fields;
  - the OpenAPI registry test still passes.
- Run `ruff check .` and `pytest -q` and make sure both pass.

### 6. Docs (Definition of Done, same change)

- `CHANGELOG.md` `[Unreleased]` → Added: version in header, dev-build
  marker, update-available link, update-check setting.
- `docs/PRD.md`:
  - add a new section for this work, scoped as the next release (don't pick
    a version number; title it e.g. "Next release — Version in the UI"
    unless one already exists);
  - cover the build-channel arg, the update-check design and the new API
    fields;
  - bump the revision-history table.
- `README.md`: mention the header version / update check and the new
  setting in the Configuration / Settings section.
- `docs/decisions.md`: record the non-obvious calls (PR-build channel,
  persistence choice, backoff, endpoint location).

## Conventions to honor

- Bare version everywhere in code and data; `v` only in display and the git
  tag.
- `load_settings()` only at startup; runtime settings come from the DB
  store.
- Every new management route goes in `mgmt_openapi.py` OPERATIONS (tests
  enforce it).
- CSRF: the new status endpoint is a GET, read-only.
- Commit prefix `feat:`. No `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. By default the message
   is a plain one-liner and the branch is whatever the session is on. **Only if** the
   project also adopts `code-checkin-and-pr` do its branch rules (`dev`, never `main`)
   and commit-prefix conventions (`feat:` / `fix:` / `chore:` / `docs:`, no
   `Co-authored-by:`) apply on top.
