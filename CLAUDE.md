# Service Tracker Dashboard (STD) — Claude Code Instructions

## Always — Definition of Done

No change is complete until its documentation is updated **in the same
commit as the code**. This is not optional and not deferrable:

1. **CHANGELOG.md — every change, no exceptions.** Add an entry under
   `[Unreleased]` describing what changed for the operator. A code
   change with no CHANGELOG entry is an incomplete change.
2. **PRD (`docs/PRD.md`) — confirm on every change.** Before
   finishing, explicitly check whether the change touches anything the
   PRD documents (architecture, the register contract, schema, jobs,
   supported dashboard views). If yes, update the PRD and bump its
   revision-history table. If no, confirm that in your summary ("PRD
   reviewed, no change needed") rather than silently skipping it.
3. **README.md — when operator-facing behavior changes.** Keep it
   current with what has been built.
4. **FUTURE.md — when parking an idea** rather than building it. Park
   in `docs/FUTURE.md`, not the PRD. When a parked item ships, remove
   it from FUTURE.md and document it in the PRD.
5. Never leave CHANGELOG, PRD, or README out of sync with the code.

> **Known debt:** the PRDs and CLAUDE.md files in both this repo and
> the notifier have drifted from shipped reality before (this repo's
> own build-status and the notifier's were both stale). A full audit
> of both repos' `docs/` against actual shipped state is a pending
> task. Until that audit happens, trust the code and CHANGELOG over
> the PRD where they disagree, and flag any contradiction you notice
> rather than propagating it.

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

Current shipped release: **v0.6.6** (latest tag on `main`; v0.6.5 was
also released but its tag is the typo'd bare `0.6.5` — see the audit
finding in this commit's history).
In flight: nothing — `[Unreleased]` in CHANGELOG is empty.

> Keep this to the two lines above — "latest tag" and "in flight."
> Do not maintain a long per-version history here; the CHANGELOG and
> git tags are the record of what shipped. Update these two lines on
> each release / when work starts on `dev`.

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
They are **two independent apps** — separate version lines, separate
Docker images, separate release cadences. The notifier is not an STD
component: it also drives Technitium DNS and runs fine with DNS only,
STD only, or both.

The two are coupled at exactly one seam: this app's `/api/v1/register`
wire contract.

- **STD owns the contract.** `schemas.py` defines a valid payload and
  uses `extra="forbid"` — unknown keys are rejected with HTTP 422, not
  ignored. (See Register Contract Rules below.)
- **The notifier is the producer.** It sends what this app documents.

### The ordering rule

Because STD's validator rejects unknown keys, **the schema-accepting
side (STD) must ship before the schema-sending side (the notifier).**

- A new field the notifier will send → STD must accept it first. Land
  the schema change in `schemas.py` and ship STD, *then* the notifier
  ships the emitter. If the notifier leads, STD 422s every payload
  from upgraded hosts.
- A new field STD wants to consume → STD can add the column/UI now, but
  it stays empty until a notifier version populates it. The feature
  isn't live until both ship, notifier last.

**Consumer leads, producer follows. STD may lead arbitrarily far
ahead; the notifier may lag; the notifier must not lead the schema.**

### Safe-degradation guarantee (don't break it)

A newer STD with an older notifier must keep working:

- Capture columns (`networks` / `exposed_ports` / `published_ports`)
  stay NULL when an older notifier doesn't send them — never make them
  required.
- `exposure_observations` absent from a payload means "no update —
  preserve existing exposure rows." `[]` means "clear all rows for
  this service." Never collapse absent and empty into the same
  behavior; the register handler in `routes_api.py` depends on the
  distinction.

### Version pairing history (informational, not the rule)

- STD v0.5.0 introduced `/api/v1/register`; notifier v0.3.0 switched
  to canonical keys against it.
- STD v0.6.0 removed the legacy `/api/register` shim; requires
  notifier v0.3.0+.
- Notifier v0.4.0 added both the capture fields and the
  `exposure_observations` interpreter mechanism; both require STD
  v0.6.0+. STD's synthesizer reads those observations and writes
  synthesized URLs into `internalurl` / `externalurl`. (A v0.3.2 was
  developed for the capture fields but never cut as a tag — it shipped
  inside v0.4.0. Do not reference v0.3.2 as a release boundary.)

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
