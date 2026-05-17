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

Current shipped release: **v0.6.4** (latest tag on `main`)

Status:

- v0.5.0 — cleanup release (split, pydantic, retention, indexes): DONE
- v0.6.0 — sunset + capture + interpreter: DONE
- v0.6.1 — UI overhaul part 1 (tiled redesign, drawer, shared CSS/JS): DONE
- v0.6.2 — hotfix: restore `toggleRestoreSource`, upload filename feedback: DONE
- v0.6.3 — UI overhaul part 2 foundations (orphan sweep, inline-style cleanup, what's new popup): DONE
- v0.6.4 — UI overhaul part 2: mobile usability + tile icon restructure: DONE
- v0.6.5 — UI overhaul part 2 (edit page polish, universal delete, widget modal, refresh pause): IN PROGRESS (on dev)
- v0.7.0+ — TBD (no scoped features at present)

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
- v0.5.0 introduced `/api/v1/register`; notifier v0.3.0 switched to
  canonical keys against it.
- v0.6.0 removed `/api/register` and the legacy-key compat shim.
  Operators must be on notifier v0.3.0+.
- Notifier v0.3.2 (ships after STD v0.6.0) populates the new
  `networks` / `exposed_ports` / `published_ports` capture fields.
  Older notifiers continue to work; those columns stay NULL.
- Notifier v0.4.0 (ships after STD v0.6.0) introduces YAML
  interpreters that populate the `exposure_observations` field on
  `/api/v1/register`. STD's synthesizer reads those observations
  and writes synthesized URLs into `internalurl` / `externalurl`.
  Pre-v0.4.0 notifiers don't send the field — STD treats absence as
  "no update" and leaves any existing exposure rows alone.

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

## Register Contract Rules (v0.6.0+)

- **Canonical key names** are the only shape accepted. `/api/v1/register`
  is the only register endpoint; legacy `/api/register` and the
  remap function were removed in v0.6.0.
- **pydantic schemas** in `schemas.py` are the source of truth for the
  wire contract. Nested structures (`networks`, `published_ports`,
  `exposure_observations`) use dedicated pydantic models with
  `extra="forbid"` so malformed payloads are caught at the schema
  boundary.
- **Network and port capture columns are pure observation** —
  overwritten on every register, no ownership semantics. The
  notifier owns them. Don't add UI editing for these columns.
- **Exposure observations are wholesale-replaced per register.**
  `null` in the payload means "no update — leave existing rows
  alone"; `[]` means "clear all rows for this service." Don't merge
  partial updates into the existing rows.
- **URL provenance ordering is `ui_edit` > `explicit_label` >
  `synthesized` > NULL.** The synthesizer (`synthesizer.py`) only
  ever writes `synthesized`. The register handler writes
  `explicit_label` when the payload carries `internalurl` /
  `externalurl`. The UI edit handler writes `ui_edit`. Never
  invert this ordering; it's the contract operators rely on to
  protect their UI edits from being clobbered.

## Module Layout (current, v0.6.0)

```
app.py              ← thin Flask app factory; wires extensions, blueprints, jobs
extensions.py       ← SQLAlchemy, login manager, scheduler instances
models.py           ← SQLAlchemy models (ServiceEntry, ServiceExposure, Setting, ...)
schemas.py          ← pydantic request/response schemas
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /add, /edit/<id>,
                      /settings, /settings/exposure
routes_api.py       ← /api/v1/register
routes_widgets.py   ← widget endpoints
routes_auth.py      ← /login, /logout, user mgmt
jobs.py             ← health check loop, widget refresh, backup, retention
health.py           ← /healthz, /readyz
settings_loader.py  ← file/ENV settings; loaded once at startup
settings_store.py   ← DB-stored runtime settings (per-interpreter directions)
synthesizer.py      ← exposure → internalurl/externalurl translation + provenance
image_utils.py      ← icon fetch + cache
view_helpers.py     ← grouping/sorting for dashboard views
templates/          ← Jinja templates
static/             ← static assets
widgets/            ← per-widget plugin dirs
alembic/            ← migrations
```

## Git Rules

- Do NOT add `Co-authored-by` lines to commit messages.
