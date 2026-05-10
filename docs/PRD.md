# Service Tracker Dashboard (STD) — Product Requirements Document

> **Status:** living document. Update alongside any change that affects
> architecture, the register contract, schema, jobs, or supported
> dashboard views.

## Revision History

| Version | Date       | Changes |
|---------|------------|---------|
| 0.1     | 2026-05-10 | Initial PRD. Documents current shipped behavior at v0.4.14 and the planned v0.5.0 cleanup. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Data Model (current, v0.4.14)](#5-data-model-current-v0414)
6. [Current State (v0.4.14)](#6-current-state-v0414)
7. [v0.5.0 — Cleanup Release](#7-v050--cleanup-release)
8. [v0.6.0 — Sunset Release (planned)](#8-v060--sunset-release-planned)
9. [Versioning, Branches, and Releases](#9-versioning-branches-and-releases)
10. [Cross-Repo Coordination](#10-cross-repo-coordination)
11. [Open Questions](#11-open-questions)

---

## 1. Product Overview

STD is a homelab-scale service dashboard. It tracks Docker services
across multiple hosts, runs background URL health checks against them,
and renders a small set of dashboard views.

The dashboard is a **consumer** of metadata pushed by external tools
(typically `docker-api-notifier`, one per Docker host), with manual
add/edit/delete as a fallback for non-Docker services or one-offs.

### 1.1 Original problem

- Existing dashboards required hand-edited config to know about each
  service.
- `docker-compose` already encodes most of what a dashboard needs in
  labels. STD treats labels as the source of truth and uses the
  dashboard's own DB only as a cache + a place for things labels can't
  express (manual entries, widget state, user accounts).

### 1.2 Design principles

- **Push, don't poll.** The notifier sidecar pushes events; STD
  doesn't connect outward to Docker hosts.
- **Labels are the source of truth.** UI edits are allowed for
  exception cases (manual entries, `static` overrides) but the
  expected workflow is `dockernotifier.std.*` labels in compose files.
- **Single-instance, file-backed.** SQLite + WAL is enough at homelab
  scale (~50 services, 5–10 hosts). No external DB.
- **Fail open.** A bad URL or transient network error never crashes
  the app; it logs and moves on.

---

## 2. Scope

### 2.1 In scope

- Receive container metadata from external tools via a register
  endpoint.
- Run periodic URL health checks against registered services.
- Render dashboard views: full, tiled, compact.
- Provide a widget system for richer per-service info.
- Local user accounts with session-based auth.
- Manual add/edit/delete via the web UI.
- YAML backups of the database with retention.

### 2.2 Out of scope

- Container orchestration. STD never touches a Docker socket directly.
- Multi-tenant or org-style account boundaries.
- Push notifications, alerting, paging.
- Distributed deployment. Single-instance, single-DB by design.
- Acting as a CI/CD or deployment dashboard.

---

## 3. Architecture

```
        ┌──────────────────────┐         ┌──────────────────────┐
        │ Docker host A        │         │ Docker host B        │
        │  └─ notifier sidecar │         │  └─ notifier sidecar │
        └──────────┬───────────┘         └──────────┬───────────┘
                   │                                │
                   │  POST /api/v1/register         │
                   │  (canonical JSON payload)      │
                   ▼                                ▼
              ┌─────────────────────────────────────────┐
              │ STD                                     │
              │  ┌───────────────────────────────────┐  │
              │  │  Flask app                        │  │
              │  │  ├─ register routes (api)         │  │
              │  │  ├─ dashboard routes (html)       │  │
              │  │  ├─ widget routes                 │  │
              │  │  └─ auth routes                   │  │
              │  └───────────────────────────────────┘  │
              │  ┌───────────────────────────────────┐  │
              │  │  Background jobs (APScheduler)    │  │
              │  │  ├─ URL health check loop         │  │
              │  │  ├─ widget refresh loop           │  │
              │  │  └─ nightly backup + retention    │  │
              │  └───────────────────────────────────┘  │
              │  ┌───────────────────────────────────┐  │
              │  │  SQLite (WAL)                     │  │
              │  │  ├─ services                      │  │
              │  │  ├─ users                         │  │
              │  │  ├─ widget_value                  │  │
              │  │  └─ ...                           │  │
              │  └───────────────────────────────────┘  │
              └─────────────────────────────────────────┘
```

### 3.1 Module layout (target, v0.5.0)

```
app.py              ← thin Flask app factory; wires extensions, blueprints, jobs
extensions.py       ← SQLAlchemy, login manager, scheduler instances
models.py           ← SQLAlchemy models (Service, User, WidgetValue, ...)
schemas.py          ← pydantic request/response schemas (register payloads, etc.)
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /add, /edit/<id>
routes_api.py       ← /api/v1/register, /api/register (compat)
routes_widgets.py   ← widget endpoints
routes_auth.py      ← /login, /logout, user mgmt
jobs.py             ← health check loop, widget refresh loop, backup + retention
health.py           ← /healthz (liveness), /readyz (readiness)
settings_loader.py  ← unchanged in spirit; loaded once at startup
image_utils.py      ← icon fetch + cache
templates/          ← Jinja templates
static/             ← static assets
widgets/            ← per-widget plugin dirs
alembic/            ← migrations
```

### 3.2 Module responsibilities

- **`app.py`** — `create_app()` factory: load settings once, init
  extensions, register blueprints, register error handlers, register
  template filters, schedule jobs.
- **`extensions.py`** — extension singletons. No app context here; the
  factory binds them.
- **`models.py`** — SQLAlchemy models. Single source of truth for the
  schema; migrations track changes.
- **`schemas.py`** — pydantic schemas for inbound payloads (register
  endpoint specifically). Decouples wire format from DB columns.
- **`routes_*.py`** — Flask blueprints. Each file is one cohesive
  surface area; routes don't reach into unrelated tables.
- **`jobs.py`** — APScheduler-driven background work. Single place to
  define schedules, named jobs, and shutdown hooks.
- **`health.py`** — process-level health for ops/monitoring; not the
  same as URL health checks (those live in `jobs.py`).

---

## 4. Configuration Model

- ENV vars override `settings.yml` values.
- `settings.yml` is optional; defaults apply when missing.
- `settings_loader.load_settings()` is called **once at startup**, and
  the resulting config dict is stored on the app for downstream code to
  read. It is not re-read inside route handlers.

The configuration surface is documented in the `README.md`.

---

## 5. Data Model (current, v0.4.14)

Four core SQLAlchemy models in `app.py`:

| Model         | Purpose                                                   |
|---------------|-----------------------------------------------------------|
| `Service`     | One row per registered service. PK on `id`; logical key on `(host, container_name)`. Holds URLs, health flags, group, sort priority, status, last-checked timestamps, image metadata, icon, etc. |
| `User`        | Local user accounts for the web UI. Includes a `session_token` field that is currently unused. |
| `WidgetValue` | Time-series of widget samples. Grows unbounded today.     |
| `Setting`     | Persisted UI/admin settings.                              |

### 5.1 Schema gaps targeted for v0.5.0

| ID  | Issue |
|-----|-------|
| S1  | No indexes beyond primary keys. `(host, container_name)` is hit on every register call and needs an index. |
| S2  | `widget_value` has no retention. At ~45 services × frequent samples, this grows unboundedly. |
| S3  | `User.session_token` is never read or written — half-finished feature; remove. |
| S4  | `is_docker_status_stale` property exists on `Service` but is never referenced — dead code. |

---

## 6. Current State (v0.4.14)

Tags shipped on `main`: v0.1.0 → v0.4.14. (One stray tag `v.0.4.6` with
an extra dot will be deleted as part of v0.5.0 housekeeping.)

### 6.1 What works today

- `/api/register` accepts container metadata; quietly remaps several
  inbound key variants.
- Three dashboard views render from the `services` table.
- Background URL health checks via APScheduler.
- Widget system with six built-in widgets (Sonarr, Radarr, Bazarr,
  Overseerr, Prowlarr, Syncthing).
- Local user auth, session-based.
- Daily YAML backups.
- Icon auto-fetch from Homarr Labs CDN.

### 6.2 Known issues at v0.4.14 (targeted for v0.5.0)

| ID  | Area                | Issue |
|-----|---------------------|-------|
| D1  | `app.py` size       | ~1,775 lines holding 4 models, ~20 routes, 3 background jobs, template filters, and init code. Hard to navigate and review. |
| D2  | View duplication    | `/`, `/tiled_dash`, `/compact_dash` duplicate ~150 lines of grouping/sorting logic. |
| D3  | Icon fetch dup.     | Icon fetching is duplicated between `image_utils.py` and inline calls in `/add`, `/edit`. |
| D4  | Auth half-finished  | `User.session_token` never written or read. |
| D5  | Dead code           | `is_docker_status_stale` property never used. |
| D6  | Settings drift      | `settings.example.yml` says `url_refresh_interval`; code reads `url_healthcheck_interval`. *(Resolved in v0.5.0.)* |
| D7  | Retention           | `widget_value` table grows unbounded. |
| D8  | Schema              | No indexes beyond PKs; `(host, container_name)` is the upsert key. |
| D9  | Settings reload     | `load_settings()` is called at module level **and** inside some route handlers. Single load at startup is the right shape. *(Resolved in v0.5.0.)* |
| D10 | Job error handling  | URL health check loop has no top-level try/except; one bad URL or transient error can kill the loop until restart. |
| D11 | Register contract   | `/api/register` quietly remaps `group ↔ group_name`, `internal.health ↔ internal_health_check_enabled`, `docker_host ↔ host`, etc. Contract drift; no canonical schema. |
| D12 | Concurrency         | `/api/register` upsert has no locking. With multiple notifier hosts, two near-simultaneous registers for the same `(host, container_name)` can race. |

---

## 7. v0.5.0 — Cleanup Release

**Ships before notifier v0.3.0.** STD v0.5.0 introduces the
`/api/v1/register` endpoint that notifier v0.3.0 will target.

### 7.1 Goals

- Resolve every issue in §5.1 and §6.2.
- Establish a stable, canonical register contract with a clear sunset
  for legacy keys.
- Split `app.py` into reviewable modules without changing observable
  behavior.
- Add the schema indexes and retention policies the homelab-scale
  workload actually needs.

### 7.2 Behavior changes visible to operators

- `/api/v1/register` is the new canonical endpoint.
- `/api/register` continues to work but emits a deprecation warning
  per request and adds `Deprecation` + `Sunset` response headers.
- The web UI, dashboard views, login flow, and existing settings keys
  work unchanged.
- `settings.example.yml` is corrected to match the keys the code
  actually reads.

### 7.3 Internal changes

- App factory pattern. `app.py` becomes a thin wiring file.
- Models, schemas, blueprints, jobs each in their own modules.
- `pydantic` v2 used for inbound register validation; replaces ad-hoc
  key-remapping. Compat shim is one well-defined function that maps
  legacy keys to canonical.
- Single `load_settings()` call at startup; downstream code reads from
  the resolved app-level config dict.
- URL health check loop wrapped in a top-level try/except so a
  transient exception in one pass doesn't kill the loop.
- `(host, container_name)` index added.
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service.
- `widget_value` retention: rolling 30-day window enforced by a
  scheduled prune job.
- Dead code removed: `is_docker_status_stale`, `User.session_token`.

### 7.4 Out of scope for v0.5.0

- New dashboard views.
- New widgets.
- New notifier targets (those live in the notifier repo).
- Any change to user auth model beyond removing the dead
  `session_token` field.
- Replacing APScheduler.

---

## 8. v0.6.0 — Sunset Release (planned)

- Remove `/api/register` endpoint.
- Remove all legacy-key handling.
- pydantic schemas become the only accepted shape.
- Deprecation headers and warnings removed from the codebase.

### 8.1 Pre-flight checklist for v0.6.0

- Confirm all in-the-wild notifier deployments are at v0.3.0 or later.
- Confirm v0.5.0 has been live "long enough" — at minimum one minor
  release cycle, ideally with confirmed deprecation warnings showing
  zero hits in the access log for a week.

---

## 9. Versioning, Branches, and Releases

- `main` is the default branch and the source of truth for releases.
- All work happens on `dev`. PR `dev` → `main` when ready to release.
- Branch protection: require PR + green build check, block force-push,
  block deletion.
- Image tags follow `.github/workflows/dockerhub.yml`:
  - push to `dev` → `:dev`, `:sha-<short>`
  - push to `main` → `:latest`, `:sha-<short>`
  - GitHub Release published → `:latest`, `:<semver>`, `:<major>`
- Tags are cut from the GitHub Releases UI against `main`.

---

## 10. Cross-Repo Coordination

This project is paired with
[docker-api-notifier](https://github.com/crzykidd/docker-api-notifier).

### 10.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start
here; the notifier follows.

### 10.2 Release ordering for the v0.5.0 / v0.3.0 cycle

1. STD v0.5.0 ships with `/api/v1/register` (canonical keys) and the
   compat shim on `/api/register` (legacy keys, deprecated).
2. Notifier v0.3.0 ships with canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 (later) removes `/api/register` and the compat shim.

Operators must upgrade the notifier to v0.3.0+ before STD v0.6.0.

---

## 11. Open Questions

- **Widget retention granularity.** A flat 30-day window may be too
  much for some widgets and not enough for others. Per-widget
  retention policy via `settings.json` worth considering for v0.6.x.
- **API tokens per-source.** A single shared token works for a homelab
  but doesn't let you revoke a single notifier host. Per-host tokens +
  last-seen tracking?
- **Health check timeouts.** Currently a fixed timeout per check. A
  per-service timeout override may be useful for slow-to-respond
  services.
- **Read-replica for dashboard reads.** WAL handles concurrent reads
  fine at this scale, but if widget growth pushes DB size up, worth
  measuring.
