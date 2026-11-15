# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-15 — CodeQL path and redirect fixes (v069-11)

- **Invalid icon on Add/Edit flashes, but those templates don't render
  flashes** (only `settings.html` does). The message is queued and shows on
  the next Settings view; nothing is written either way. Adding flash display
  to the Add/Edit pages was out of scope.
- **Edit with a bad icon keeps the stored icon** and still saves the other
  fields, mirroring the invalid-timeout handling.
- **Add page's `ref` handling removed**: it was computed and never used.
- **`fetch_icon_if_missing` also validates** (it is the path used for
  derived names from container/image names), so a container name that does
  not fit the icon charset simply gets no auto-fetched icon.
- **Widget list is `widgets/` under the app root**, not `/app/widgets`; same
  directory in the container (`WORKDIR /app`). The edit page still lists
  `/app/widgets` (not part of the alerts); left alone.

---

## 2026-11-15 — Docs loose ends (v069-10)

- **Series headers keep the `[0.x.x] series` form**: the What's New regex needs
  `\d+.\d+.\d+`, so they never match. Side effect: the `[0.4.0]` section body
  runs to EOF and swallows the 0.3.x/0.2.x/0.1.x series text in the popup.
  Left as is (cosmetic, only seen when upgrading from <0.4.0); not worth a
  parser change.

---

## 2026-11-15 — gunicorn and pins (v069-09)

- **Startup via `post_worker_init`, not `preload_app`**: threads started in
  the master don't survive the fork. `run_startup_tasks()` is guarded by a
  module flag so it is a no-op if called twice in one process.
- **`gunicorn.conf.py` timeout = 60 s** (default 30) so slow register/icon
  fetches aren't killed; a worker kill would restart the scheduler.
- **Pins resolved for Python 3.11 only**, no platform markers: publish.yml
  builds linux/amd64 only. CI `Test`/`Migration check` install the pinned set
  unchanged; `requirements-dev.txt` stays `-r requirements.txt` + pytest.
- **Docker verification note**: this host's default log driver is `loki`,
  which swallows `docker logs`; verify with `--log-driver json-file`.

---

## 2026-11-15 — Health-check options (v069-08)

- **Invalid timeout on edit keeps the stored value** (flash warning, rest of the
  form still saves), mirroring how sort priority is handled there. On Add an
  invalid value re-renders the form.
- **Restore sets the options explicitly** (defaults when absent) rather than
  leaving an existing row's values, so a v0.6.8 backup restores to the
  documented defaults.
- **`verify` treats only an explicit `False` as off** in `check_url`, so a
  missing attribute fails safe to verifying.

---

## 2026-11-15 — Staleness indicator (v069-07)

- **Never-updated dynamic entries:** model still returns stale (unchanged);
  the new Dashboard/Compact icon is shown only when `last_api_update` is set,
  because Tiled already renders that case as a distinct red "no update
  received" and Dashboard as a red pill. Avoids double-flagging.
- **Threshold read** via `has_app_context()`/`current_app.config`, default 5
  on missing, invalid, or negative values.
- **Tooltip wording** unified as "stale — updated <time_since>".

## 2026-11-15 — Widget detach and refresh filter (v069-06)

- **Refresh filter:** `Widget.services.any(deleted_at IS NULL)`, i.e. only
  widgets with an active service refresh. A widget referenced only by
  soft-deleted entries stays skipped (as in v069-05): a restorable entry is
  hidden and unchecked, so polling its upstream is wasted work; Restore
  resumes it. Detached widgets are skipped by the same rule. Side effect:
  legacy widget rows with no services (previously refreshed) are now skipped
  too; they show up under Detached widgets.
- **`hard_delete_entry`** only deletes the entry; widget and values are kept.
  Retention pruning of `widget_value` is unchanged.
- **Edit page not changed:** it updates the attached widget in place and only
  creates a new row when the entry had none (or a dangling id), so it never
  orphans a widget. Selecting "none" deletes the widget and values outright,
  even if another entry shares it (pre-existing; widgets are not shared in
  normal use) -- left as is, noted for the operator.

## 2026-11-15 — Soft-delete call-site decisions (v069-05)

`ServiceEntry.active()` is the filter for anything user-facing; the choices
that weren't obvious:

- **Deliberately all rows:** the register lookup (needs deleted rows to
  resurrect; orders active before deleted), backups (scheduled and manual, so
  `deleted_at` round-trips), both restore lookups, `recompute_all` (keeps
  deleted rows' synthesized URLs fresh for a later restore), the add-entry
  duplicate check (a deleted twin gets a "restore it instead" message),
  `/dbdump` (raw-table view: shows deleted rows marked and struck through
  rather than adding a filter), and `hard_delete_entry`'s "other services use
  this widget" count (a soft-deleted entry still holds its widget).
- **Static-locked deleted entry:** register skips it before resurrecting, so a
  locked entry stays deleted until restored by hand.
- **Widget refresh:** (superseded by v069-06 below) filters widgets (it queries `Widget`, not entries) to
  those with no services or at least one active service.
- **Group delete:** only active entries block it; the group's soft-deleted
  entries get `group_id = NULL` so none dangle.
- **`hard_delete_entry`** lives at the bottom of `models.py` (shared by
  `routes_dashboard.py` and `jobs.py`; caller commits). The old inline
  widget-if-unused code moved there unchanged so v069-06 edits one function.
- Retention comparison uses naive local `datetime.now()`, matching
  `last_updated`; `0` days purges everything soft-deleted at the next run.

---

## 2026-11-15 — CSRF: JSON detection and general-suite opt-out

The `CSRFError` handler answers JSON (400) when `request.is_json`, the path
is under `/api/`, an `X-CSRFToken` header is present, or `Accept` asks for
JSON; otherwise flash + redirect to the referrer (dashboard fallback). The
header check covers `stdPost` fetches that carry no body/Accept (the delete
calls). Tests set `WTF_CSRF_ENABLED=False` on the shared app in `conftest.py`;
`tests/test_csrf.py` flips it on per test via a fixture.

---

## 2026-11-15 — Default-credential check cached, dismissal is per-session

The `changeme123` check hashes a password, so it runs once at startup (and
again from `routes_auth.set_user_password` / `reset_user_password`) and is
cached on `app.config`, not computed per request. `create_default_admin` also
refreshes it because the admin row is created after `create_app()`. The Settings
notice is dismissed client-side via `sessionStorage` (reappears next session),
so dismissal needs no DB state. `FLASK_SECRET_KEY` set-but-empty is treated as
unset. The "reset password" admin action sets `changeme123`, so it re-raises the
warning by design.

---

## 2026-11-15 — Lint widened to E, W, F, I, B

`ruff.toml` now selects `E, W, F, I, B` with `E501` ignored (line length is
churn). Initial run: 30 findings (I001 x20, E402 x4, B009 x2, B010 x2, W291 x2);
none was a real bug, so no CHANGELOG entry. B009/B010 were constant-name
`getattr`/`setattr`, rewritten as plain attribute access (identical behavior).
`per-file-ignores`: `alembic/versions/*.py` skips `I001`/`W291` (applied
migrations are history; sorting them is pure churn, and the one W291 is inside
a docstring); `alembic/env.py` skips `E402` (it must edit `sys.path` before
importing app modules). No file-wide or rule-wide ignores otherwise.

---

## 2026-11-15 — Test seam: `STD_CONFIG_DIR`, env set in conftest

`app.py` builds the app at import and reads `/config` paths there, so
`STD_CONFIG_DIR` (default `/config`) is resolved once in
`settings_loader.CONFIG_DIR` and everything derives from it. `tests/conftest.py`
sets the env and a temp dir at import time, before `app` is imported, instead of
restructuring the factory. Kept as a dev/test knob (README Development only, no
CHANGELOG entry). Tests stub `routes_api.resolve_image_metadata` to avoid icon
downloads, and the loader tests monkeypatch `CONFIG_PATH`. `alembic.ini` and the
`Migration check` job still use `/config` and are untouched.

---

## 2026-11-15 — v0.6.9 scope: one large patch, and its design calls

Review of v0.6.8 found two bugs, a security pass, a missing test suite,
and the delete-safety-net features. Recommended split was 0.6.9
(hardening) + 0.7.0 (safety net); **the operator chose to ship both as
one 0.6.9.** Plan in PRD §12, one prompt per subsection.

- **Patch, not minor.** Side effect: `/release-prep` won't run the
  per-minor CHANGELOG archive step this time. The `2026-XX-XX` dates
  that would have broken it are fixed anyway (§12.10) — git tags show
  the real dates, and they're 2025, not 2026.
- **Unset `API_TOKEN` → register returns 503**, UI keeps working.
  Rejected: refusing to start (breaks UI-only installs).
- **Soft-delete *and* widget detach** (operator choice). Soft-delete is
  the recovery window; detach applies only at the eventual hard delete.
- **Register resurrects a soft-deleted row** rather than leaving it
  hidden or creating a fresh duplicate. A hard-deleted running container
  already reappears on its next register today; resurrecting keeps the
  curated state, which is the point of the feature.
- **Single staleness threshold, default 5 min** (the model's current
  value; the template's 120-min clause is redundant under OR). Notifier
  re-scans every 60 s by default.
- **CSRF tokens have no time limit** (`WTF_CSRF_TIME_LIMIT=None`) —
  long-open dashboards otherwise 400 on the next POST.
- **gunicorn with exactly one worker.** The register mutex, scheduler,
  and health thread are in-process; multiple workers would duplicate
  jobs and break the upsert lock.
- **Testability via `STD_CONFIG_DIR`** (default `/config`) rather than
  monkeypatching module constants; tests use `create_all()`, Alembic
  stays covered by `Migration check`.
- **Not in 0.6.9:** concurrent health checks, per-source API tokens,
  `repo-sandbox-permissions` adoption (offered, not chosen). The stale
  `release-prep-and-cut @ v1.0.0` text is upstream in `homelab-configs`.

---

## 2026-11-15 — CLAUDE.md consolidation after the standards adoption

- **Removed** "Git Workflow" and "Git Rules" (fully covered by the
  `code-checkin-and-pr` snippet) and the four standard prefixes in "Commit
  style" (kept only the `refactor:` extension and the release-prep message).
  **Merged** "Git Workflow" (required checks, CI trigger, `Test` exemption) and
  "Release Process" (GHCR, tags, `VERSION`, `/release-prep` -> `/release-cut`)
  into one "CI, Registry, and Releases" section: project-specific facts only,
  one place per fact.
- **Always item 1 narrowed** from "every change" to "every operator-visible
  change", matching the existing rule that tooling-only changes go in
  HISTORY/decisions, not CHANGELOG.
- **Snippets left untouched**, including the stale `release-prep-and-cut @ v1.0.0`
  source comment (pin in `standards.md` is 1.1.0); snippets are read-only.
- CLAUDE.md said unknown register keys return HTTP 422; the code and PRD say
  400. Corrected to 400.

---

## 2026-11-15 — Adopting release-prep-and-cut: VERSION file, no APP_VERSION, tag guard

- **`VERSION` is the single source of the in-app version.** The Dockerfile
  derives `version=` in `/app/version.txt` from the copied `VERSION` file
  (`tr -d '[:space:]'`). Previously `APP_VERSION` came from the
  metadata-action output, which is `dev`/`latest`/`pr-N` off release events,
  so `:dev`/`:latest` reported a non-semver and the What's New popup
  (keys on the version) misbehaved.
- **`APP_VERSION` build arg removed outright, not kept as an override.** An
  override would let a build disagree with `VERSION`, recreating the drift
  this fixes; nothing needs it (local builds also read `VERSION`).
- **`publish.yml` guard:** on `release` events a step before the builds fails
  if the tag minus leading `v` != `VERSION` — cheap protection against
  tagging the wrong commit. Only the version build-args and this step were
  touched; Docker Hub steps and `REGISTRY_NOTICE` left for the other prompt.
- **`app.py` fallback** (no `/app/version.txt`, e.g. `python app.py`) reads
  `VERSION` beside `app.py`, else `"unknown"`.
- **`<LOCAL_CHECKS>` reuse `ci.yml`.** Config validation extracts and runs
  the `config-validate` step's script from `ci.yml` via PyYAML, so the file
  lists can't drift. Lint is `uvx ruff@0.15.17 check .`. Migration check uses
  a temp copy of `alembic.ini` (URL and `%(here)s` script_location rewritten)
  and `uv run --python 3.11 --with-requirements requirements.txt alembic` (no global alembic on the dev box), never a real `/config` (contrast with CI, which
  creates a runner-local `/config`).
- **Tooling stays out of CHANGELOG** (per the vexp entry); only the
  operator-visible "images report the real version" effect was logged.
- The bare `0.6.5` tag remains an un-fixable historical deviation.

---

## 2026-11-15 — Adopting code-checkin-and-pr: migration-check DB, retention scope, F821

- **Migration check uses a runner-local `/config`** (`sudo mkdir -p /config &&
  sudo chown $USER /config`) rather than an env-var override in
  `alembic/env.py`. `alembic.ini` hardcodes `sqlite:////config/services.db`;
  creating the dir keeps the check running against the unmodified production
  config and avoids a code change. Rejected: env override (runtime-adjacent
  change for a CI-only need).
- **Untagged GHCR versions are never pruned.** `publish.yml` uses
  `build-push-action` with default provenance, so per-platform/attestation
  manifests exist as untagged versions referenced by tagged indexes. Telling
  referenced from orphaned is not worth the risk; accepted cost is some
  untagged residue after tagged versions are pruned.
- **F821 in `routes_dashboard.py` `/add` was a real bug.** A non-numeric sort
  priority raised `NameError` (`groups` undefined) -> HTTP 500. Fixed by
  loading `groups` at the top of the POST branch and passing it to all three
  error re-renders (the other two silently rendered an empty group dropdown).
  Operator-visible, so it has a CHANGELOG `### Fixed` entry.
- **CI is push-only** (no `pull_request` trigger) to avoid duplicate
  same-named check runs that leave required checks stuck "Expected".
- Test check exempt (no suite); recorded in `standards.md`.

---

## 2026-11-15 — vexp removal recorded in HISTORY, not CHANGELOG

CLAUDE.md requires a CHANGELOG entry for every change, but CHANGELOG is
operator-facing and is rendered in the in-app "What's new" popup. The vexp
removal is developer tooling with no operator-visible effect, so it was
recorded in `docs/HISTORY.md` instead. Same reasoning applies to future
tooling-only changes (agent guidance, `.claude/` config).

## 2026-11-15 — Docker Hub → GHCR via a banner-only final Docker Hub release

v0.6.7 was published to both registries from one workflow, with the
in-app "moved to GHCR" banner gated on a `REGISTRY_NOTICE=dockerhub`
build arg so only the Docker Hub image shows it. Rejected: a Docker
Hub-only final release (GHCR would have had nothing to switch to) and
an unconditional banner (users who had already moved would keep seeing
it). Driver: GHCR retention runs on `GITHUB_TOKEN`; Docker Hub retention
would need a delete-scoped token and a custom cleanup job. Docker Hub
publishing, the build arg, and the banner are removed in the next
release; Docker Hub tags stay frozen on the v0.6.7 banner build.

## 2026-11-15 — The `0.6.5` tag stays un-prefixed

v0.6.5 was tagged `0.6.5` (no `v`), unlike every other release. It is
left as-is: re-tagging a published release is never done (moving a tag
under consumers breaks pins and image provenance). CHANGELOG's link
reference already points at `releases/tag/0.6.5`. All new tags use the
`vX.Y.Z` form.
