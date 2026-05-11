# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> Targeting v0.5.0. **Must ship before notifier v0.3.0** — this release
> introduces `/api/v1/register`, which notifier v0.3.0 will target.

### Added
- New `/api/v1/register` endpoint accepting canonical key names
  (`host`, `group`, `internal_health_check_enabled`, ...) validated by
  pydantic schemas.
- Composite index on `(host, container_name)` — the logical key for
  the register upsert path.
- 30-day rolling retention for `widget_value`, enforced by a scheduled
  prune job.
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service.
- `Deprecation` and `Sunset` response headers on `/api/register`.

### Changed
- `app.py` split into focused modules: `routes_dashboard.py`,
  `routes_api.py`, `routes_widgets.py`, `routes_auth.py`, `models.py`,
  `schemas.py`, `jobs.py`, `health.py`. `app.py` becomes a Flask app
  factory.
- Grouping/sorting logic for `/`, `/tiled_dash`, `/compact_dash`
  consolidated into a single helper.
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

[Unreleased]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.4.14...HEAD
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
