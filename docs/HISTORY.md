# Service Tracker Dashboard Project History

This file documents structural events in the project's history — things
that don't fit neatly in a changelog entry but are worth knowing about.

For the feature-level changelog, see [CHANGELOG.md](../CHANGELOG.md).

---

## Documentation baseline (v0.5.0 cycle)

Through v0.4.14, the project shipped with a single `README.md` and no
PRD or HISTORY file. As part of the v0.5.0 cleanup work, this document,
[`PRD.md`](./PRD.md), and a project-level [`CLAUDE.md`](../CLAUDE.md)
were added.

### Why

`app.py` had grown to ~1,775 lines and the register endpoint had
accumulated silent key-remapping logic that no document described. The
PRD captures the current state, the planned v0.5.0 changes, and the
v0.6.0 sunset of legacy keys. CLAUDE.md captures workflow conventions
that had been informal up to that point.

### What changed

- `docs/PRD.md` added — current state, planned v0.5.0 / v0.6.0
  changes, scope.
- `docs/HISTORY.md` (this file) added.
- `CLAUDE.md` added at repo root.
- `CHANGELOG.md` reformatted to Keep a Changelog conventions; existing
  v0.1.x through v0.4.x tags listed as stub entries (detailed notes
  for pre-v0.5.0 versions are not retained).

### Impact on existing installs

None. Documentation only.

---

## Stray git tag cleanup (v0.5.0 cycle)

A typo'd tag `v.0.4.6` (extra dot before the major version) existed in
the repo alongside the correctly-named `v0.4.6`. Both tags pointed at
the same commit. The typo'd tag was deleted (locally and from the
remote) as part of v0.5.0 housekeeping.

This had no effect on Docker Hub images or release artifacts — the
typo'd tag was never used by any release workflow.

---

## Register contract canonicalization (v0.5.0)

v0.5.0 is the first release that defines a canonical wire contract for
the register endpoint. Prior to v0.5.0, `/api/register` accepted a
mix of key variants (`docker_host` ↔ `host`, `group_name` ↔ `group`,
`internal.health` ↔ `internal_health_check_enabled`, etc.) and
silently remapped them server-side.

### Why

The remapping was undocumented and made the register contract a
moving target. Every change to label naming on the notifier side
required matching tolerance in STD's remapping logic, and there was
no single document explaining what shape `/api/register` actually
expected.

### What changed

- New endpoint `/api/v1/register` accepts only canonical keys,
  validated by pydantic schemas.
- Existing `/api/register` becomes a compat shim: maps legacy keys to
  canonical, then delegates to the v1 handler. Emits a deprecation
  warning per request and adds `Deprecation` + `Sunset` response
  headers.
- The canonical contract is documented in `README.md` and `PRD.md`.

### Sunset plan

`/api/register` and all legacy key support are removed in v0.6.0.
Operators must upgrade `docker-api-notifier` to v0.3.0+ before that
release.

---

## App factory split (v0.5.0)

v0.5.0 splits the monolithic `app.py` (~1,775 lines as of v0.4.14)
into focused modules while preserving observable behavior. See
PRD §3.1 for the target layout.

### Why

The single-file structure made the project hard to navigate and
review. Models, ~20 routes, 3 background jobs, template filters, and
init code were all in one file. Splitting along surface-area
boundaries (api routes vs dashboard routes vs auth routes vs jobs)
makes each file reviewable on its own and gives new functionality a
natural place to land.

### What changed

- `app.py` becomes a Flask app factory (`create_app()`).
- `models.py`, `schemas.py`, `routes_*.py`, `jobs.py`, `health.py`
  added as peers of `app.py`.
- `extensions.py` (already present) holds extension singletons.

### Impact on existing installs

None. The split is internal; no routes, schemas, or behavior change
as a result of the refactor itself. (The other v0.5.0 changes — the
canonical contract, retention, indexes — are listed separately in
the changelog and PRD.)
