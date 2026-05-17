# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.4] — 2026-05-17

UI overhaul, part 2 (release 2 of 3): mobile usability and tile restructure.
The filter bar now collapses cleanly on phones, tile status icons split into two
rows so container names stop truncating, and the drawer scrolls its tile into
view when you tap to expand it.

### Added

- **Mobile filter bar.** Below 640 px the filter bar collapses to just the
  free-text filter plus a "View options" toggle button. Tapping the toggle
  reveals group-by, sort, Show URL-less, auto-refresh, and total count in a
  vertical panel. Tapping outside or pressing Esc collapses it again. Above
  640 px the filter bar is unchanged.
- **Drawer scrolls into view on mobile.** When you tap the chevron on a Tiled
  tile near the bottom of the viewport, the page smoothly scrolls the tile to
  the top so the drawer has room to expand below it. Only triggers below 768 px
  wide — desktop drawers are unaffected.
- **Stack row in the tile drawer.** When a service has a stack name, the Tiled
  drawer now shows it immediately after Host. Saves a trip to the edit page
  when grouped by host.

### Changed

- **Tile status icons now render in two rows.** The single-row icon layout was
  truncating container names aggressively when all affordances were present.
  Status icons (internal URL, external URL, Docker, widget) now occupy the top
  row; action icons (Dozzle, edit pencil, expand chevron) occupy the bottom
  row. Container names get back the horizontal space they need. Tiles are
  roughly 20 % taller as a result.
- **Larger touch targets on mobile.** Tile status icons and drawer action
  buttons have bigger hit boxes below 640 px — same visual size, more
  forgiving for fingers. Desktop appearance unchanged.
- **`icon-sep` separator removed.** The two-row icon layout replaces it
  semantically.

## [0.6.3] — 2026-05-17

Foundations for "UI overhaul, part 2": orphan handler sweep,
inline-style cleanup completing the v0.6.1 CSS extraction, and a
"what's new" popup that fires automatically after each version upgrade.

### Added

- **"What's new" popup.** After upgrading STD, operators see a modal on
  their next page load showing the changelog entries for every version
  since the one they last acknowledged. Dismissal writes the current
  version to `localStorage` and closes. New API route
  `GET /api/v1/changelog?since=<version>` parses `CHANGELOG.md`
  server-side and returns the relevant sections as rendered HTML.
- **`markdown` package** added to `requirements.txt` to support
  server-side rendering of changelog sections.

### Changed

- **Inline `<style>` blocks removed** from `templates/edit_entry.html`
  and `templates/settings.html`. The v0.6.1 CSS extraction is now
  complete — `.form-input`, `.form-checkbox`, `.btn-primary`, and
  `.btn-secondary` are defined only in `static/css/dashboard.css`.
  `.btn-primary` background normalized from `#4299e1` to
  `var(--color-accent)` (`#3b82f6`) — minor visible difference on
  the edit and add pages.
- **`version_info` is now injected globally** into every template that
  extends `base.html` via the app context processor (previously only
  passed explicitly to the settings page). Required by the changelog
  popup to read the current version.

### Fixed

- **`toggleGroupMode` unreachable from inline `onclick=`** on the
  edit-entry and add-entry pages. The function was scoped inside a
  `DOMContentLoaded` closure, making it invisible to inline handler
  attributes. Hoisted to module scope in both templates.

## [0.6.2] — 2026-05-16

### Fixed

- **Restore-from-upload broken on /settings.** The `toggleRestoreSource`
  function was dropped during the v0.6.1 inline-JS extraction, leaving
  `#file-upload-section` permanently hidden with no way to select a local
  YAML backup file. The function has been restored to the settings template.
- **No filename feedback after selecting an upload file.** The
  `#restore_file_input` change event now updates `#file-name-display` with
  the selected filename so operators can confirm their file choice before
  submitting.

## [0.6.1] — 2026-05-16

UI overhaul, part 1: Tiled dashboard redesign, per-tile expand drawer,
icon vocabulary shared across Tiled and Dashboard, inline CSS/JS
extracted to shared static files, Compact tab-highlight fix.

### Added

- **Per-tile expand drawer on Tiled.** Clicking the chevron on any tile
  drops a panel anchored to the tile (overlay, not inline reflow). Drawer
  shows host, internal/external URLs with health status, Docker status and
  image tag, networks, ports, exposure observations, and widget data.
  Action row at the bottom has Edit, Delete, and (when Dozzle is
  configured) a Tools popover with a Dozzle link.
- **Pencil-icon edit affordance** on Tiled tiles (status icon row) and
  Dashboard table Actions column. Both navigate to `/edit/<id>?ref=<path>`.
- **Tabler Icons** (v3.34.0) loaded via cdnjs CDN. Outline set only.
  Used for all new icons in this release.
- **Tools popover in the Tiled drawer.** Seeded with the Dozzle link.
  Renders only when at least one tool is available.

### Changed

- **Tiled dashboard tile redesign.** Host line removed from the tile
  face (now in the drawer). Status area replaced with icon row:
  `ti-home` (internal URL), `ti-world` (external URL),
  `ti-brand-docker` (Docker), plus widget indicator, Dozzle, edit
  pencil, and expand chevron. Colors: green 2xx, amber SSL/stale, red
  non-2xx or bad, gray not-configured.
- **Exposure badges** (Tiled, Dashboard, edit page) now use Tabler
  icons `ti-lock` / `ti-key` instead of 🔒 / 🔑 emoji.
- **Dashboard table status column** now uses icon-and-label pills
  sharing the Tiled icon vocabulary (`ti-home`, `ti-world`,
  `ti-brand-docker`).
- **Dashboard Tools column** uses `ti-terminal-2` instead of the
  Dozzle SVG image.
- **Per-template inline CSS and JS extracted** to
  `static/css/dashboard.css` and `static/js/dashboard.js`. All three
  dashboard views now share these files. Hybrid Tailwind-utilities-
  plus-custom-CSS approach formalized; no frontend build step.

### Removed

- **"Show Widgets" filter-bar toggle on Tiled.** Widget data is now
  accessible via the per-tile expand drawer.

### Fixed

- **Compact tab failed to highlight** in the nav. The missing
  `{% set active_tab = 'compact' %}` declaration has been added.

## [0.6.0] — 2026-05-14

### Added
- **View controls** above the service grid on `/`, `/tiled_dash`, and
  `/compact_dash`, sharing one UI partial:
  - `Group by` axis selector with `group` (default), `stack`, and
    `host`. Designed as an N-axis selector so future axes drop in
    without rework. `axis=stack` collects rows with no `stack_name`
    into an "Unstacked" bucket rendered last; `axis=host` collects
    rows with no host into "Unknown host"; `axis=group` keeps
    "Ungrouped" last as before.
  - `Show URL-less` checkbox (default on). Unchecking hides services
    where both `internalurl` and `externalurl` are null/empty.
- View-control state is URL-driven
  (`?group_by=stack&show_urlless=false&sort_in_group=alphabetical`),
  so dashboards stay bookmarkable and shareable. No per-user
  preference persistence in this release.
- **Network & ports capture (v0.6.0).** Three new optional fields on
  `/api/v1/register`, populated by notifier v0.3.2+:
  - `networks` — list of `{"name", "aliases"}` objects, one per
    Docker network the container is attached to. Names only; IPs
    intentionally not captured.
  - `exposed_ports` — list of `"<port>/<proto>"` strings declared
    via `EXPOSE` in the image or `expose:` in compose.
  - `published_ports` — list of `{"container_port", "protocol",
    "host_ip", "host_port"}` objects describing host-to-container
    port mappings from compose `ports:`.
- Three new nullable JSON columns on `service_entry`
  (`networks`, `exposed_ports`, `published_ports`) storing the above.
  Rows that haven't received a v0.3.2+ register stay NULL — that's
  the expected state, not a bug.
- New "Reported by notifier" section at the bottom of `/edit/<id>`,
  read-only, showing networks, exposed ports, and published ports
  with "Not reported" placeholders when data is absent.
- **Exposure interpreter mechanism.** STD now consumes structured
  exposure observations emitted by notifier YAML interpreters
  (Traefik, Dockflare, etc.), synthesizes `internalurl` /
  `externalurl` from them, and surfaces them as tile badges. Six
  interlocking pieces:
  - New optional `exposure_observations` field on
    `/api/v1/register`, validated by a strict pydantic
    `ExposureObservation` model (`extra="forbid"`). Notifier v0.4.0+
    populates this. `null` in the payload means "no update"; `[]`
    means "clear all observations for this service."
  - New `service_exposure` table (one row per (service, interpreter
    layer) observation), with FK + index on `service_entry_id`.
    Replaced wholesale per service on each register that carries
    `exposure_observations`.
  - New synthesizer module (`synthesizer.py`) that combines
    exposure observations + per-interpreter direction settings to
    produce `internalurl` and `externalurl`. Tiebreaker: TLS over
    non-TLS, no path prefix over path prefix, layer name
    alphabetical (stable). Runs on every register and on settings
    save.
  - URL provenance: two new columns on `service_entry`
    (`internalurl_source`, `externalurl_source`) tracking which
    actor last wrote each URL. Ordering: `ui_edit` >
    `explicit_label` > `synthesized` > NULL. Operator UI edits and
    explicit `dockernotifier.std.internalurl` labels are never
    overwritten by the synthesizer.
  - New DB-stored settings table (`setting`) and module
    (`settings_store.py`). First operator-editable runtime settings
    in STD; backs the per-interpreter direction mapping
    (`traefik = internal`, `dockflare = external`, ...) with
    per-host overrides.
  - New "Exposure" tab on `/settings` showing discovered interpreter
    layers with a direction dropdown each (internal / external /
    neither, defaulting to neither) and a per-host overrides
    section. Saving recomputes synthesized URLs for every service.
- **Exposure badges** on the tiled and table dashboards — small
  pills per `service_exposure` row showing layer name, TLS status
  (🔒), and auth-required indicator (🔑). Capped at 3 visible per
  service with a `+N` overflow indicator.
- **Headless rendering** — services with no exposure observations
  and no URLs render without click affordance on the tiled and
  compact dashboards. Status display falls back to `docker_status`.
- URL source indicator next to the URL inputs on `/edit/<id>` —
  shows whether each URL was edited in the UI, set via explicit
  label, or synthesized. Clearing the field resets provenance and
  re-allows synthesis on the next register.

### Changed
- Grouping/sorting logic for the three dashboard views consolidated
  into `view_helpers.group_and_sort_services` — a single helper that
  takes `(services, axis, show_urlless, sort_in_group)` and returns
  the bucketed list the templates render. (Resolves D2 from PRD §6.2,
  which was deferred from v0.5.0 despite the v0.5.0 changelog
  claiming otherwise.)
- Group buckets are now keyed canonically by `group_id` across all
  three views (was a mix of `group_id` and `group_name`). Two
  distinct `Group` rows that happen to share a display name yield
  two distinct buckets.
- The dashboard view-controls dropdown values changed from
  `group_name`/`stack_name` to `group`/`stack`. Bookmarks built
  against the v0.5.0 query strings will fall back to the default
  `group` axis (logged at DEBUG).
- `RegisterPayload` validates nested `networks` and `published_ports`
  structures with dedicated pydantic models (extra="forbid" applies
  to each). Malformed payloads are rejected at the schema boundary.

### Removed
- **`/api/register` endpoint and the legacy-key compat shim.** Routes
  that used to translate `docker_host`, `group`, `internal.health`,
  `external.health`, `icon`, `sort.priority`, etc. into canonical
  keys are gone. The per-IP deprecation log tracker and the
  `Deprecation: true` / `Link: rel="successor-version"` response
  headers are also removed — they had nowhere to attach. Operators
  must run `docker-api-notifier` v0.3.0 or later; older notifiers
  will see 404 at `/api/register`.

### Fixed
- `compact_dash` tile click handler no longer opens a literal "None"
  URL when both `internalurl` and `externalurl` are empty. Tiles
  without a URL now render as non-clickable text (consistent with the
  headless rendering rule).

---

## [0.5.0] — 2026-05-12

### Added
- New `/api/v1/register` endpoint accepting canonical key names
  (`host`, `group`, `internal_health_check_enabled`, ...) validated by
  pydantic schemas.
- Composite index on `service_entry(host, container_name)` — the
  logical key for the register upsert path. Non-unique; concurrency
  safety comes from the application-level mutex (see below), not
  from a database constraint.
- New `notifier_reported_group_name` and `notifier_reported_sort_priority`
  columns on `service_entry`. The v0.5.0 register handler writes
  what the notifier most recently reported for these user-overridable
  fields, so a planned "export overridden labels" feature can diff
  the user's edited value against the notifier's. Not surfaced in
  the UI in v0.5.0.
- Rolling retention for `widget_value`, enforced by a scheduled
  daily prune job (00:15 server local time). Window is configurable
  via the new `widget_value_retention_days` setting (default 30).
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service.
- New `register_field_ownership` setting (`user_wins` default, or
  `notifier_wins`). Controls whether a notifier register call may
  overwrite a non-NULL UI-edited value for `group_name` or
  `sort_priority` on an existing row. New rows always take
  everything the payload carries. Regardless of mode, the
  `notifier_reported_*` capture columns record what the notifier
  said. Invalid values fall back to `user_wins` with a startup
  WARNING.
- `Deprecation: true` response header on `/api/register`, plus a
  `Link: </api/v1/register>; rel="successor-version"` pointer. A
  per-IP-per-hour rate-limited WARNING log fires when a legacy
  producer hits the shim. (No `Sunset` header in v0.5.0 — a wrong
  Sunset date is worse than none. v0.6.0 will add it once its
  release timeline is firm.)
- `/healthz` liveness endpoint returning `{"status": "ok"}` (HTTP 200)
  as long as the WSGI worker is up. Unauthenticated; intended for
  container orchestrators and external uptime checks.

### Changed
- `app.py` split into focused modules: `routes_dashboard.py`,
  `routes_api.py`, `routes_widgets.py`, `routes_auth.py`, `models.py`,
  `schemas.py`, `jobs.py`, `health.py`. `app.py` becomes a Flask app
  factory.
- Icon fetch consolidated; `image_utils.py` is the single path used by
  `/add`, `/edit`, and the register handler.
- `settings.example.yml` updated to match the keys the code actually
  reads (`url_healthcheck_interval`, not `url_refresh_interval`).
- `load_settings()` is called once at startup; route handlers read
  from the resolved app config.
- Repo layout cleaned up: dashboard screenshots moved from the repo
  root into `docs/screenshots/`; `test-widget.py` moved to
  `scripts/test_widget.py`. README image links updated.

### Deprecated
- `/api/register` endpoint and all legacy key variants
  (`docker_host`, `group_name`, `internal.health`, `external.health`,
  `internalurl`, `externalurl`). Will be removed in v0.6.0. Operators
  must upgrade `docker-api-notifier` to v0.3.0+ before v0.6.0.

### Removed
- Unused `session_token` field on `User`.
- Stray git tag `v.0.4.6` (extra dot) — replaced by `v0.4.6`.
- `docker-compose-alembic.yml` — a one-shot from June 2025 with a
  hardcoded migration message and a maintainer-specific host path.
  Run alembic via `docker compose exec <service> alembic ...`
  against the running app container instead. Workflow documented in
  the new "Database Migrations" section of `README.md`.
- `READMEOLD.md` — pre-v0.4.9 README, superseded by the rewritten
  `README.md`.

### Fixed
- Register endpoint contract documented and enforced via pydantic
  schemas; no more silent key remapping.
- Shell scripts pinned to LF line endings via `.gitattributes`.
  Prevents the container failing to start with
  `exec /entrypoint.sh: no such file or directory` when the repo is
  cloned on Windows with `core.autocrlf=true`.
- SQLite WAL mode is now actually enabled at runtime via a connect-time
  PRAGMA in `extensions.py`. Prior releases documented WAL mode but
  `journal_mode` was the SQLite default (`delete`), so the documented
  backup rules around the WAL sidecar didn't reflect actual on-disk
  state.
- `alembic/env.py` now imports the application module so SQLAlchemy
  model classes register with `db.metadata`. Previously
  `db.metadata.tables` was empty during alembic runs, which would have
  caused `alembic revision --autogenerate` to silently produce empty
  no-op migrations. A guard now raises if metadata is empty rather
  than letting the schema silently drift.
- Background scheduler and URL health-check thread now start only when
  `app.py` is run as the main process, not at module import time.
  Previously they spawned during `alembic upgrade head` in production
  (where `app.debug` is False) and briefly raced alembic for the SQLite
  write lock before being killed when the alembic process exited.
- Removed a duplicate `health_check_loop` thread start that had two
  daemon threads racing each other on every production startup.
- URL health-check loop wrapped in a per-iteration `try / except` so a
  transient `requests` failure, DNS hiccup, or unexpected exception no
  longer escapes the worker thread and silently kills health checks
  until the process restarts. The exception is logged with a full
  traceback and the loop continues.
- "Stale" tile styling on `/tiled_dash` now actually fires.
  `is_docker_status_stale` was defined at the wrong indentation level
  and silently attached to `User` instead of `ServiceEntry`, so the
  template's reference resolved to `Undefined` (always falsy) and stale
  tiles never received the stale colour class. Property is now
  correctly attached to `ServiceEntry`.

---

## [0.4.14] — 2026-XX-XX

Released. Detailed notes not retained.

## [0.4.13] — 2026-XX-XX
Released.

## [0.4.12] — 2026-XX-XX
Released.

## [0.4.11] — 2026-XX-XX
Released.

## [0.4.10] — 2026-XX-XX
Released.

## [0.4.9] — 2026-XX-XX

Breaking change: required a database backup + delete + restore on upgrade.

## [0.4.8] — 2026-XX-XX
Released.

## [0.4.7] — 2026-XX-XX
Released.

## [0.4.6] — 2026-XX-XX
Released.

## [0.4.5] — 2026-XX-XX
Released.

## [0.4.4] — 2026-XX-XX
Released.

## [0.4.3] — 2026-XX-XX
Released.

## [0.4.2] — 2026-XX-XX
Released.

## [0.4.1] — 2026-XX-XX
Released.

## [0.4.0] — 2026-XX-XX
Released.

## [0.3.x] series — 2026-XX-XX

v0.3.0 through v0.3.9 released. Detailed notes not retained.

## [0.2.x] series — 2026-XX-XX

v0.2.0 through v0.2.12 released. Detailed notes not retained.

## [0.1.x] series — 2026-XX-XX

Initial development releases v0.1.0 through v0.1.4.

[Unreleased]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.6.1...HEAD
[0.6.1]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.1
[0.6.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.0
[0.5.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.5.0
[0.4.14]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.14
[0.4.13]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.13
[0.4.12]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.12
[0.4.11]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.11
[0.4.10]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.10
[0.4.9]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.9
[0.4.8]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.8
[0.4.7]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.7
[0.4.6]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.6
[0.4.5]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.5
[0.4.4]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.4
[0.4.3]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.3
[0.4.2]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.2
[0.4.1]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.1
[0.4.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.0
