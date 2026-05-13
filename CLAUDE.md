# Service Tracker Dashboard (STD) — Claude Code Instructions

## Always

- After any change that affects architecture, the register contract,
  schema, jobs, or supported dashboard views, update `docs/PRD.md` and
  `README.md` accordingly.
- After completing a phase, update `README.md` with what has been built.
- Never leave PRD or README out of sync with the codebase.

## Commit style

- `feat:` new feature
- `chore:` config, tooling, maintenance
- `fix:` bug fix
- `docs:` documentation only changes
- `refactor:` non-behavior-changing internal cleanup

## Stack

- Python 3.11
- Flask, Flask-SQLAlchemy, Flask-Login
- SQLAlchemy + Alembic (migrations)
- APScheduler (background jobs)
- pydantic v2 (request validation; introduced in v0.5.0)
- SQLite (WAL mode)
- Jinja templates
- Container: single-image Docker
  - `Dockerfile` — production image
  - `docker-compose.yml` — example deployment

## Configuration

- Settings live in `/config/settings.yml` (mounted from the host).
- Environment variables override `settings.yml` values.
- `settings_loader.load_settings()` is called **once at startup**;
  the resolved config dict is held on the app and read from there.
  Do not call `load_settings()` from inside route handlers.
- Full settings reference: `README.md` → Configuration section.

## Project Documentation

- Full PRD is at `docs/PRD.md` — read this before starting any phase.
- Project history (structural events, milestones) at `docs/HISTORY.md`.
- `README.md` at the root — keep it current with what has been built.
- Commit doc updates in the same commit as the code changes they describe.

## Build Status

Current shipped release: **v0.4.14** (latest tag on `main`)

Next release target: **v0.5.0** — cleanup release. Must ship **before**
notifier v0.3.0 because v0.5.0 introduces `/api/v1/register` (the
endpoint notifier v0.3.0 will target).

- Phase 1 — Documentation baseline: IN PROGRESS
- Phase 2 — Settings + dead code cleanup: NOT STARTED
- Phase 3 — Schema indexes + retention: NOT STARTED
- Phase 4 — `app.py` split into focused modules: NOT STARTED
- Phase 5 — pydantic register schemas + `/api/v1/register`: NOT STARTED
- Phase 6 — Compat shim on `/api/register` with deprecation headers: NOT STARTED
- Phase 7 — Job error handling + concurrency lock: NOT STARTED
- Phase 8 — Stray `v.0.4.6` tag removal: DONE

## Git Workflow

- Work on `dev` branch for all changes.
- Push to `dev` freely — builds `:dev` images.
- When ready to release:
  - Create PR `dev` → `main` on GitHub.
  - Merge after CI passes.
  - Tag release from `main` via the GitHub Releases UI.
- Never push directly to `main`.
- Branch protection on `main` requires PR + green build, blocks
  force-push and deletion.
- Do NOT add `Co-authored-by` to commits.

## Release Process

- Push to `dev` — GitHub Actions builds and pushes `:dev` and
  `:sha-<short>` images to Docker Hub.
- Push to `main` (via PR from `dev`) — GitHub Actions builds and pushes
  `:latest` and `:sha-<short>` images.
- When the build is stable and ready to ship:
  1. GitHub → Releases → Draft new release.
  2. Create a new tag in `vX.Y.Z` format.
  3. Publish the release.
  4. GitHub Actions builds and pushes `:latest`, `:X.Y.Z`, and `:X` to
     Docker Hub.

## Changelog Process

- `CHANGELOG.md` lives at repo root.
- Follow Keep a Changelog format (keepachangelog.com).
- Add entries to `[Unreleased]` section as features are built.
- User-facing language only — describe what changed for the operator.
- Categories: Added, Changed, Fixed, Security, Deprecated, Removed.
- On release: move `[Unreleased]` to a new version section dated today.
- GitHub release body = that version's CHANGELOG section.

## Cross-Repo Coordination

This project is paired with
[docker-api-notifier](https://github.com/crzykidd/docker-api-notifier).
The contract is:

- **STD** owns the wire contract for the register endpoint.
- **Notifier** is a producer — it sends what STD documents.
- Wire-format changes start here. The notifier follows.
- For v0.5.0 specifically: this release ships first; notifier v0.3.0
  switches to canonical keys + `/api/v1/register` afterward.
- v0.6.0 will remove `/api/register` and the compat shim. Operators
  must be on notifier v0.3.0+ before v0.6.0.

## Database Rules

- **All schema changes go through Alembic.** Hand-editing tables is not
  acceptable; the migration is the source of truth that runs on every
  deployment.
- **FK columns added in a migration must have their index added in the
  same migration.** Don't ship a migration that creates an FK without
  the index — it'll just be cleanup work later.
- **WAL mode is enabled.** All SQLite backup operations must use
  `sqlite3.Connection.backup()` rather than `shutil.copy*`. The WAL
  sidecar can hold uncommitted writes that `shutil.copy2` silently misses.
- **`(host, container_name)` is the logical key for `services`** — every
  register call hits this column pair. It must be indexed.
- **`widget_value` retention is enforced by a scheduled job** (introduced
  in v0.5.0). Do not write code that assumes unbounded retention.

## Register Contract Rules (v0.5.0+)

- **Canonical key names** are the only shape accepted by
  `/api/v1/register`. No silent remapping.
- **The compat shim on `/api/register`** is the only place legacy key
  remapping happens. It's a single, well-defined function — not
  scattered remapping in multiple route handlers.
- **pydantic schemas** in `schemas.py` are the source of truth for the
  wire contract. The README documents what the schema enforces.
- **Removing legacy support** is a v0.6.0 task. Do not silently start
  rejecting legacy keys before v0.6.0 — emit deprecation warnings
  instead.

## Module Layout (target, v0.5.0)

```
app.py              ← thin Flask app factory; wires extensions, blueprints, jobs
extensions.py       ← SQLAlchemy, login manager, scheduler instances
models.py           ← SQLAlchemy models (Service, User, WidgetValue, ...)
schemas.py          ← pydantic request/response schemas
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /add, /edit/<id>
routes_api.py       ← /api/v1/register, /api/register (compat)
routes_widgets.py   ← widget endpoints
routes_auth.py      ← /login, /logout, user mgmt
jobs.py             ← health check loop, widget refresh, backup, retention
health.py           ← /healthz, /readyz
settings_loader.py  ← unchanged in spirit; loaded once at startup
image_utils.py      ← icon fetch + cache
templates/          ← Jinja templates
static/             ← static assets
widgets/            ← per-widget plugin dirs
alembic/            ← migrations
```

## Git Rules

- Do NOT add `Co-authored-by` lines to commit messages.
