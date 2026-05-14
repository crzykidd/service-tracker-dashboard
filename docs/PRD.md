# Service Tracker Dashboard (STD) — Product Requirements Document

> **Status:** living document. Update alongside any change that affects
> architecture, the register contract, schema, jobs, or supported
> dashboard views.

## Revision History

| Version | Date       | Changes |
|---------|------------|---------|
| 0.1     | 2026-05-10 | Initial PRD. Documents current shipped behavior at v0.4.14 and the planned v0.5.0 cleanup. |
| 0.2     | 2026-05-13 | Added §8 (v0.5.x — view controls + grouping/sorting helper consolidation). Corrected §6.2 D2 row: the v0.5.0 entry claimed the helper consolidation was resolved, but it was deferred — the work actually lands in v0.5.x. |
| 0.3     | 2026-05-13 | v0.6.0 delivered. Removed /api/register compat shim. Added §5.3 (v0.6.0 schema additions: networks, exposed_ports, published_ports). §9 rewritten from "planned" to "delivered." Added §10 (v0.7.0 — interpreter / exposure synthesis, planned). |
| 0.4     | 2026-05-13 | Exposure interpreter mechanism folded into v0.6.0 rather than shipping as a separate v0.7.0 release. §9 expanded with §§9.4–9.8 (wire contract, synthesizer, URL provenance, per-interpreter settings, badges + headless rendering). New §5.4 documents the v0.6.0 schema additions for the interpreter (`service_exposure`, two URL source columns on `service_entry`, `setting` table). §10 retired (no scoped features for the next release). |
| 0.5     | 2026-05-14 | v0.6.0 released. The originally-planned v0.5.x (view controls + helper consolidation), v0.6.0 (compat shim removal + capture columns), and v0.7.0 (exposure interpreter) work shipped together as a single v0.6.0 release. Former §8 (v0.5.x planning) folded into the new §8 (Delivered in v0.6.0). §6.2 D2 marked Resolved in v0.6.0. Cross-repo coordination (now §10.2) collapsed the v0.3.2 / v0.4.0 notifier split into a single notifier v0.4.0 pairing. Later sections renumbered: §10/§11/§12 → §9/§10/§11. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Data Model](#5-data-model)
6. [Current State (v0.4.14)](#6-current-state-v0414)
7. [v0.5.0 — Cleanup Release](#7-v050--cleanup-release)
8. [v0.6.0 — Delivered](#8-v060--delivered)
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

### 3.1 Module layout (v0.6.0)

```
app.py              ← thin Flask app factory; wires extensions, blueprints
extensions.py       ← SQLAlchemy + Flask-Login singletons
models.py           ← SQLAlchemy models (ServiceEntry, ServiceExposure,
                      Setting, User, Widget, WidgetValue, Group)
schemas.py          ← pydantic request/response schemas
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /dbdump, /settings,
                      /settings/exposure, /add, /edit/<id>, group CRUD,
                      /images/<filename>
routes_api.py       ← /api/v1/register
routes_widgets.py   ← /widget_config/<widget_name>
routes_auth.py      ← /login, /logout, user mgmt; is_admin_required;
                      Flask-Login user_loader
jobs.py             ← URL health-check loop, widget refresh loop,
                      daily backup, widget_value retention prune,
                      verify-and-fetch-missing-icons startup sweep
health.py           ← /healthz (liveness). /readyz deferred to a later
                      release.
settings_loader.py  ← file/ENV settings; loaded once at startup
settings_store.py   ← DB-stored runtime settings (per-interpreter directions)
synthesizer.py      ← exposure → internalurl/externalurl translation +
                      URL provenance tracking
image_utils.py      ← icon fetch + cache
view_helpers.py     ← grouping/sorting for dashboard views
templates/          ← Jinja templates
static/             ← static assets
widgets/            ← per-widget plugin dirs
alembic/            ← migrations
```

### 3.2 Module responsibilities

- **`app.py`** — `create_app()` factory: load settings once, init
  extensions, register blueprints, register error handlers, register
  template filters. Does not start background work on import —
  `start_background_workers(app)` is invoked from the `__main__`
  block once migrations have completed.
- **`extensions.py`** — extension singletons (`db`, `login_manager`).
  No app context here; the factory binds them.
- **`models.py`** — SQLAlchemy models. Single source of truth for the
  schema; migrations track changes.
- **`schemas.py`** — pydantic schemas for inbound payloads (register
  endpoint specifically). Decouples wire format from DB columns.
- **`routes_*.py`** — Flask blueprints. Each file is one cohesive
  surface area; routes don't reach into unrelated tables.
- **`jobs.py`** — APScheduler-driven background work plus the
  startup icon-verification sweep. Each function takes the app
  explicitly and pushes its own context, so jobs.py keeps no
  module-level `app` reference.
- **`health.py`** — process-level health for ops/monitoring; not the
  same as URL health checks (those live in `jobs.py`).
- **`settings_store.py`** — read/write the `setting` table for
  operator-editable runtime settings (the per-interpreter direction
  mapping in v0.6.0). Distinct from `settings_loader.py`, which
  loads `settings.yml` once at startup. DB reads happen per call —
  the rows are tiny and edit rate is human-scale.
- **`synthesizer.py`** — exposure interpreter logic. Combines
  `ServiceExposure` rows + per-interpreter settings + URL
  provenance to produce synthesized `internalurl` / `externalurl`
  values on `ServiceEntry`. Runs on every register and on settings
  save. Idempotent; safe to call repeatedly.

---

## 4. Configuration Model

- ENV vars override `settings.yml` values.
- `settings.yml` is optional; defaults apply when missing.
- `settings_loader.load_settings()` is called **once at startup**, and
  the resulting config dict is stored on the app for downstream code to
  read. It is not re-read inside route handlers.

The configuration surface is documented in the `README.md`.

---

## 5. Data Model

Seven SQLAlchemy models (defined in `models.py` from v0.5.0 onward;
they lived in `app.py` through v0.4.14):

| Model            | Table              | Purpose                                                   |
|------------------|--------------------|-----------------------------------------------------------|
| `ServiceEntry`   | `service_entry`    | One row per registered service. PK on `id`; logical key on `(host, container_name)` — indexed from v0.5.0. Holds URLs, health flags, group_id (FK), sort_priority, status, last-checked timestamps, image metadata, icon, the `is_static` flag, the v0.5.0 `notifier_reported_*` capture columns, the v0.6.0 `networks` / `exposed_ports` / `published_ports` capture columns, and the v0.6.0 `internalurl_source` / `externalurl_source` URL provenance columns. |
| `ServiceExposure`| `service_exposure` | New in v0.6.0. One row per (service, interpreter layer) observation — many rows per service possible. Wholesale-replaced per register when the payload carries `exposure_observations`. FK to `service_entry.id` (ON DELETE CASCADE), indexed. |
| `Group`          | `group`            | Optional grouping. Unique `group_name`, optional `group_sort_priority` and `group_icon`. Referenced by `ServiceEntry.group_id`. |
| `Widget`         | `widget`           | Widget configuration (name, URL, API key, JSON-encoded field list). Referenced by `ServiceEntry.widget_id`. |
| `WidgetValue`    | `widget_value`     | Most-recent value per `(widget_id, widget_value_key)` — upserted in place by the widget refresh job, not a time series. The retention job (v0.5.0+) prunes rows whose `last_updated` is older than `widget_value_retention_days`. |
| `Setting`        | `setting`          | New in v0.6.0. KV-style store for operator-editable runtime settings. Distinct from `settings.yml` (which is immutable for the process lifetime). Backs the per-interpreter direction mapping used by the synthesizer. JSON values. |
| `User`           | `user`             | Local user accounts for the web UI.                       |

### 5.1 v0.5.0 schema changes

| Change | Detail |
|--------|--------|
| Index  | Non-unique `ix_service_entry_host_container_name` on `service_entry(host, container_name)`. Concurrency safety lives in the application-level register mutex, not in a database constraint, so duplicate cleanup is deferrable. |
| Column | `service_entry.notifier_reported_group_name` (`String(100)`, nullable). Captures what the notifier most recently sent for the `group` label. |
| Column | `service_entry.notifier_reported_sort_priority` (`Integer`, nullable). Captures what the notifier most recently sent for the `sort.priority` label. |
| Drop   | `user.session_token` removed (see §5.2 S3). |

The two `notifier_reported_*` columns are populated by the v0.5.0
register handler on every register call. No reader yet — they exist
so a planned overridden-labels export can compare the user's edited
value against the notifier's latest report. Restoring from a v0.4.x
backup leaves them NULL; the next register call fills them in.

### 5.2 Schema gaps from v0.4.14 (status)

| ID  | Issue | Status |
|-----|-------|--------|
| S1  | No indexes beyond primary keys. `(host, container_name)` is hit on every register call and needs an index. | Resolved in v0.5.0 (`ix_service_entry_host_container_name`). |
| S2  | `widget_value` has no retention. At ~45 services × frequent samples, this grows unboundedly. | Resolved in v0.5.0 (configurable retention prune job, default 30 days). |
| S3  | `User.session_token` is never read (it is *written* by `generate_session_token()` on user creation, but no code ever reads it back) — half-finished feature; remove. | Resolved in v0.5.0. |
| S4  | `is_docker_status_stale` property was defined at the wrong indentation level and silently attached to `User` instead of `ServiceEntry`. `templates/tiled_dash.html` references `entry.is_docker_status_stale` on `ServiceEntry` rows, so Jinja resolved it to `Undefined` (always falsy) and the stale tile styling never fired. | Fixed in v0.5.0: property re-attached to `ServiceEntry`. |

### 5.3 v0.6.0 schema changes

| Change | Detail |
|--------|--------|
| Column | `service_entry.networks` (`JSON`, nullable). List of `{"name": str, "aliases": [str]}` capturing Docker network membership as reported by the notifier. Pure observation; overwritten on every register. Names only — IPs/gateways are intentionally not captured. |
| Column | `service_entry.exposed_ports` (`JSON`, nullable). List of `"<port>/<proto>"` strings (e.g. `"5173/tcp"`). The container's `EXPOSE` declarations / compose `expose:` entries. |
| Column | `service_entry.published_ports` (`JSON`, nullable). List of `{"container_port", "protocol", "host_ip", "host_port"}` objects — the host-to-container port mappings from compose `ports:`. Distinct from `exposed_ports`: published is what reaches the host, exposed is what the container declares it listens on. |

All three are populated by notifier v0.4.0+. Rows that haven't seen a
v0.4.0+ register call have NULL for these columns — that's the
expected state, not a bug. The read-only block at the bottom of the
edit page shows "Not reported" when the columns are NULL.

The v0.6.0 synthesizer (§8.6) does not currently read these columns —
exposure observations from interpreters (§5.4) carry the same
hostname information more directly. They remain captured as
diagnostic data, visible on `/edit/<id>`, and as a future fallback
evidence source if a "proxy-adjacent without explicit labels" rule
ever lands.

### 5.4 v0.6.0 schema changes (exposure interpreter)

| Change | Detail |
|--------|--------|
| Table  | `service_exposure` — one row per (service, interpreter layer) observation. Columns: `id` (PK), `service_entry_id` (FK to `service_entry.id` ON DELETE CASCADE, indexed), `layer` (`String(64)`, NOT NULL), `hostname` (`String(255)`, nullable), `tls` (Boolean, nullable), `path_prefix` (`String(255)`, nullable), `auth` (`String(128)`, nullable), `details` (JSON, nullable), `last_updated` (DateTime, NOT NULL). Replaced wholesale per service on each register that carries `exposure_observations`. |
| Column | `service_entry.internalurl_source` (`String(20)`, nullable). URL provenance — one of `"ui_edit"`, `"explicit_label"`, `"synthesized"`, or NULL. Ordering enforced by the register handler, UI edit handler, and synthesizer: `ui_edit` > `explicit_label` > `synthesized` > NULL. |
| Column | `service_entry.externalurl_source` (`String(20)`, nullable). Same semantics as `internalurl_source` but for `externalurl`. |
| Table  | `setting` — KV-style runtime settings. Columns: `key` (`String(64)`, PK), `value` (JSON, nullable), `updated_at` (DateTime, NOT NULL). v0.6.0 uses two keys: `exposure_layers` (dict of layer → direction) and `exposure_layers_per_host` (dict of host → dict of layer → direction). Future settings can re-use this table. |

Restoring from a v0.5.0 backup leaves `internalurl_source` and
`externalurl_source` NULL — the next register call may write
`explicit_label`, and the next UI edit will write `ui_edit`. Rows
imported from backup without exposure observations get NULL source
columns, meaning the synthesizer is free to fill them in once
exposure data arrives.

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

### 6.2 Known issues at v0.4.14 (resolved in v0.5.0)

| ID  | Area                | Issue |
|-----|---------------------|-------|
| D1  | `app.py` size       | ~1,775 lines holding 4 models, ~20 routes, 3 background jobs, template filters, and init code. Hard to navigate and review. *(Resolved in v0.5.0.)* |
| D2  | View duplication    | `/`, `/tiled_dash`, `/compact_dash` duplicate ~150 lines of grouping/sorting logic. *(Deferred from v0.5.0; resolved in v0.6.0 — see §8.1.)* |
| D3  | Icon fetch dup.     | Icon fetching is duplicated between `image_utils.py` and inline calls in `/add`, `/edit`. *(Resolved in v0.5.0.)* |
| D4  | Auth half-finished  | `User.session_token` written on user creation but never read. *(Resolved in v0.5.0.)* |
| D5  | Stale styling broken | `is_docker_status_stale` property indented onto `User` instead of `ServiceEntry`. Template references it on `ServiceEntry`, so stale tile styling never fired. *(Resolved in v0.5.0.)* |
| D6  | Settings drift      | `settings.example.yml` says `url_refresh_interval`; code reads `url_healthcheck_interval`. *(Resolved in v0.5.0.)* |
| D7  | Retention           | `widget_value` table grows unbounded. *(Resolved in v0.5.0.)* |
| D8  | Schema              | No indexes beyond PKs; `(host, container_name)` is the upsert key. *(Resolved in v0.5.0.)* |
| D9  | Settings reload     | `load_settings()` is called at module level **and** inside some route handlers. Single load at startup is the right shape. *(Resolved in v0.5.0.)* |
| D10 | Job error handling  | URL health check loop has no top-level try/except; one bad URL or transient error can kill the loop until restart. *(Resolved in v0.5.0.)* |
| D11 | Register contract   | `/api/register` quietly remaps `group ↔ group_name`, `internal.health ↔ internal_health_check_enabled`, `docker_host ↔ host`, etc. Contract drift; no canonical schema. *(Resolved in v0.5.0.)* |
| D12 | Concurrency         | `/api/register` upsert has no locking. With multiple notifier hosts, two near-simultaneous registers for the same `(host, container_name)` can race. *(Resolved in v0.5.0.)* |

---

## 7. v0.5.0 — Cleanup Release

**Shipped before notifier v0.3.0.** STD v0.5.0 introduces the
`/api/v1/register` endpoint that notifier v0.3.0 will target.

### 7.1 Goals

- Resolve every issue in §5.2 and §6.2.
- Establish a stable, canonical register contract with a clear sunset
  for legacy keys.
- Split `app.py` into reviewable modules without changing observable
  behavior.
- Add the schema indexes and retention policies the homelab-scale
  workload actually needs.

### 7.2 Behavior changes visible to operators

- `/api/v1/register` is the new canonical endpoint. Strict: unknown
  keys are rejected with 400 + the list of offending keys.
- `/api/register` continues to work but emits `Deprecation: true`
  and a `Link` header pointing to `/api/v1/register` on every
  response. A WARNING log fires at most once per client IP per
  hour. No `Sunset` header in v0.5.0 — a wrong Sunset date is
  worse than none. (v0.6.0 ultimately removed the endpoint
  outright, making a Sunset header moot.)
- The `sort.priority` legacy key (with the dot) now actually populates
  `sort_priority`. The v0.4.x handler read it directly with the dot
  but never wired it to the canonical name, so payloads that sent
  `sort.priority` silently had no effect. Now they do.
- New rows still take every field the payload carries. Existing
  rows: `register_field_ownership` (default `user_wins`) decides
  whether the notifier may overwrite UI-edited `group_name` and
  `sort_priority`. The `notifier_reported_*` capture columns are
  written either way.
- The web UI, dashboard views, login flow, and existing settings
  keys work unchanged.
- `settings.example.yml` is corrected to match the keys the code
  actually reads, and documents the two new settings
  (`widget_value_retention_days`, `register_field_ownership`).

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
- `(host, container_name)` index added (`ix_service_entry_host_container_name`,
  non-unique).
- `notifier_reported_group_name` and `notifier_reported_sort_priority`
  capture columns added to `service_entry`. Populated by the v0.5.0
  register handler; not read in v0.5.0 itself — forward-compat for
  the planned overridden-labels export.
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service. Coarse
  (single `threading.Lock` covering all keys); homelab-scale write
  rate doesn't justify per-key locking. In-process only — under
  Gunicorn with multiple workers, SQLite's WAL single-writer
  behavior is the actual cross-process safety net.
- New `register_field_ownership` setting (`user_wins` default or
  `notifier_wins`) controls whether the notifier may overwrite a
  non-NULL UI-edited value for `group_name` or `sort_priority` on
  an existing row. Invalid values fall back to `user_wins` with a
  startup WARNING.
- `widget_value` retention: rolling window enforced by a daily
  prune job at 00:15. Window configurable via
  `widget_value_retention_days` (default 30).
- Dead code removed: `User.session_token` (never read; the half-finished
  auth feature it was meant for never landed).
- `is_docker_status_stale` re-attached to `ServiceEntry` (previously
  bound to `User` via an indentation bug, which made the template's
  stale tile styling silently dead).

### 7.4 Out of scope for v0.5.0

- New dashboard views.
- New widgets.
- New notifier targets (those live in the notifier repo).
- Any change to user auth model beyond removing the dead
  `session_token` field.
- Replacing APScheduler.

---

## 8. v0.6.0 — Delivered

Originally planned across three releases — v0.5.x (view controls +
grouping/sorting helper consolidation), v0.6.0 (compat-shim sunset +
container network/port capture), and v0.7.0 (exposure interpreter
mechanism + synthesizer + badges + settings UI). All of it shipped
together as a single v0.6.0 release on 2026-05-14.

The interpreter work transforms STD's role from "operator restates
infrastructure facts via `dockernotifier.std.*` labels" into "STD
reads facts the notifier already extracts from other tools' labels,
infers URLs and exposure layers, and surfaces them with badges."
The operator writes *less* configuration; STD does more inference.

### 8.1 View controls + helper consolidation

Resolves D2 (§6.2) — the v0.5.0 changelog incorrectly claimed the
grouping/sorting helper had been consolidated; the work actually
landed here. Bundled with the introduction of dashboard view
controls because both touch the same code paths.

Operator-visible behavior:

- All three dashboard views (`/`, `/tiled_dash`, `/compact_dash`)
  render a shared view-controls partial above the service grid: a
  `Group by` dropdown, an in-bucket sort selector, and a `Show
  URL-less` checkbox.
- View-control state lives in the URL query string
  (`?group_by=stack&show_urlless=false&sort_in_group=alphabetical`)
  so dashboards are bookmarkable and shareable. Per-user
  persistence is intentionally out of scope.
- Defaults match v0.5.0 behavior. With no query params, the
  dashboard groups by group (Ungrouped last), shows every
  registered service, and sorts within bucket per the existing
  per-view default (`priority` for `/` and `/tiled_dash`,
  `alphabetical` for `/compact_dash`).
- `Group by` axes: `group` (default), `stack`, `host`. N-axis
  design — future axes (image, exposure layer, ...) drop in
  without rework. Bucket labels:
  - `axis=group` — group display name; rows with no group land in
    "Ungrouped" rendered last.
  - `axis=stack` — stack name; rows with no stack land in
    "Unstacked" rendered last. Stack is a deployment unit (compose
    project), not a fallback group; it's surfaced as its own axis
    rather than silently merged with `group`.
  - `axis=host` — host string; rows with no host land in "Unknown
    host" rendered last.
- `?show_urlless=false` filters out entries whose `internalurl` and
  `externalurl` are both null/empty before grouping, so empty
  buckets disappear cleanly.
- Unknown axis values fall back to `group` (logged at DEBUG).

Internal changes:

- New module `view_helpers.py` exposing `group_and_sort_services` —
  the single grouping/sorting entry point. Returns a list of
  `(bucket_label, [entries])` tuples in render order.
- `routes_dashboard.py` view handlers shrunk to "read query params,
  load entries, hand off to the helper, render." The three
  handlers no longer carry their own grouping/sorting code.
- Group buckets are keyed canonically by `group_id`, not
  `group_name`. (Two distinct `Group` rows that happen to share a
  display name get two distinct buckets.) The previous mix of
  `group_id` keying in `dashboard()` and `group_name` keying in
  the other two handlers is reconciled toward `group_id`.
- Templates iterate the helper's tuple list directly; the
  `group_lookup` dict the dashboard view used to construct in
  Python is gone — the bucket label is the helper's output.
- Per-view JS handlers for the group-by/sort dropdowns are
  removed in favour of a single shared submit-on-change handler
  in the view-controls partial.

### 8.2 Sunset of /api/register

- `/api/register` removed.
- Legacy-key remap (`_LEGACY_KEY_MAP`, `_remap_legacy_to_canonical`)
  removed.
- `Deprecation: true` / `Link: rel="successor-version"` response
  headers, the per-IP deprecation log tracker, and `_add_deprecation_headers`
  removed — they have no surface to attach to anymore.
- pydantic schemas (`RegisterPayload`) are the only accepted shape.
- Operators must run notifier v0.3.0 or later. Anything older returns
  404 at the (now gone) `/api/register` path.

### 8.3 Container facts captured

Three new nullable JSON columns on `service_entry` — see §5.3 for the
full schema. Wire contract: three new optional fields on
`RegisterPayload` (`networks`, `exposed_ports`, `published_ports`)
with nested pydantic types so malformed payloads are rejected at the
schema boundary rather than at write time.

Pure observation, no ownership semantics — the notifier overwrites
these on every register. If the notifier sends `null` or `[]`, that's
written as-is (so the operator can see when a container loses its
network membership / port mapping). Pre-v0.4.0 notifiers continue to
work; they just don't populate the new columns.

### 8.4 Detail surface

A read-only "Reported by notifier" block at the bottom of the edit
page (`/edit/<id>`) shows networks, exposed ports, published ports,
and exposure observations for the service. Empty / NULL state
renders "Not reported" / "No exposure observations" text rather
than empty sections. Static entries (`is_static=True`) also render
the empty state — they don't receive notifier registers.

### 8.5 Exposure observations — wire contract

New optional field on `RegisterPayload`:

```
exposure_observations: Optional[List[ExposureObservation]] = None
```

Nested `ExposureObservation` model (`extra="forbid"`):

- `layer` (str, required) — interpreter identifier, e.g., `"traefik"`,
  `"dockflare"`. Lowercase, underscore-separated by convention.
- `hostname` (Optional[str]) — public-facing hostname.
- `tls` (Optional[bool]) — true if TLS-terminated at this layer.
- `path_prefix` (Optional[str]) — path prefix when exposed at non-root.
- `auth` (Optional[str]) — auth indicator (`"cloudflare_access:authenticate"`,
  `"none"`, etc.). Rendered as a `🔑` icon on the tile badge.
- `details` (Optional[Dict[str, Any]]) — per-layer extras that don't
  fit the typed columns. Use sparingly; fields used by multiple
  interpreters should be promoted to typed columns.

Wholesale-replace semantics on register: `null` in the payload means
"no update — leave existing rows alone" (so a pre-v0.4.0 notifier
that doesn't emit the field doesn't accidentally clear observations
from an earlier register). `[]` means "this container has no
interpreter matches — clear all rows." A non-empty list replaces
all rows for the service.

### 8.6 Synthesizer

`synthesizer.py` consumes `ServiceExposure` rows + operator
per-interpreter direction settings (§8.8) + the service's existing
URL provenance, and produces `internalurl` / `externalurl` values
on `ServiceEntry` with `_source = "synthesized"`.

Algorithm (per direction, internal vs external):

1. For each `ServiceExposure` row attached to the service, look up
   the direction for `(layer, host)` using
   `settings_store.direction_for(layer, host)`. Per-host settings
   override the global mapping; unknown / unset = "neither".
2. Build candidate URLs from rows whose direction matches the one
   we're computing. URL shape:
   `{scheme}://{hostname}{path_prefix}/` where scheme is `https`
   when `tls=true` else `http`. Skip rows missing hostname.
3. Tiebreaker (first one wins): TLS over non-TLS, no path prefix
   over path prefix, layer name alphabetical (stable, deterministic).
4. Write the winning URL only when the existing `_source` is NULL
   or `"synthesized"`. `ui_edit` and `explicit_label` are
   preserved.
5. When no candidate exists and `_source` is NULL or
   `"synthesized"`, clear the URL and set source to NULL. (Removing
   a Traefik label makes the synthesized URL disappear; a UI edit
   would stay.)

Runs on every register after `ServiceExposure` rows are updated,
and on every save of the exposure settings page (which calls
`recompute_all()` to iterate every service). Synchronous, no
background job — at homelab scale (~50 services) the recompute
runs in milliseconds.

### 8.7 URL provenance

Two new columns on `service_entry`: `internalurl_source` and
`externalurl_source` (see §5.4). Values: `"ui_edit"`,
`"explicit_label"`, `"synthesized"`, or NULL.

Writers and ordering (later beats earlier):

- The **UI edit handler** in `routes_dashboard.py` sets
  `"ui_edit"` when the operator sets a URL via the form. Clearing
  the field resets source to NULL so synthesis can re-fill from
  remaining exposure observations.
- The **register handler** in `routes_api.py` sets
  `"explicit_label"` when the payload carries `internalurl` or
  `externalurl` (corresponding to a `dockernotifier.std.internalurl`
  or `.externalurl` operator label). Won't overwrite `"ui_edit"`.
- The **synthesizer** sets `"synthesized"`. Won't overwrite
  `"ui_edit"` or `"explicit_label"`.
- NULL is overwritten by anything.

The existing `register_field_ownership` setting (v0.5.0) governs
`group_name` and `sort_priority` only — it's not what protects URL
edits. URL provenance is the v0.6.0 mechanism for that, scoped to
URLs and aware of the synthesizer.

### 8.8 Per-interpreter settings

`Setting` table (§5.4) backs runtime-editable settings. v0.6.0
populates two keys:

- `exposure_layers` — `{"traefik": "internal", "dockflare": "external"}`.
  Layer → direction (`"internal"`, `"external"`, or `"neither"`).
  Default for any layer not listed: `"neither"`. A layer set to
  `"neither"` still produces a badge (so the operator can see it
  exists) but doesn't contribute to URL synthesis.
- `exposure_layers_per_host` —
  `{"docker-edge-vm": {"traefik": "external"}}`. Per-host override.
  Same layer name, different deployment direction (Traefik on a home
  network = internal; Traefik on an edge VPS = external).

New settings tab on `/settings`: lists every layer ever observed in
`service_exposure` (so operators don't see empty config screens
before any interpreter has run) with a direction dropdown per
layer. Per-host overrides section appears when at least one host
has exposure observations attached. Saving calls
`synthesizer.recompute_all()` so the dashboard reflects the new
direction mapping immediately, not on the next register cycle.

### 8.9 Badges + headless rendering

Each tile / table row renders up to three exposure badges, one per
`ServiceExposure` row, capped with a `+N` overflow indicator.
Badge content:

- Layer name (truncated to 8 chars).
- `🔒` prefix when `tls=true`.
- `🔑` suffix when `auth` is present and not `"none"`.

Tile-level visual budget: badges live in the tile-details block
below the host name, ahead of any widget data. The tiled view and
the table view both render them via `templates/partials/exposure_badges.html`.
The compact view does not — its single-line tile shape has no room.

Headless rendering — a service with zero `ServiceExposure` rows and
no `internalurl` / `externalurl`:

- The tile renders without click affordance (no link wrapping the
  title, no hover-border highlight).
- Status display continues to use `docker_status` (independent of
  URL health checks).
- The `show_urlless=false` filter (§8.1) hides these tiles when
  the operator wants a dashboard that's only clickable services.

### 8.10 Out of scope for v0.6.0

- **Loading YAML interpreters in STD.** The notifier (v0.4.0+) owns
  interpreter execution. STD only consumes outputs over the wire.
- **`kind` field for semantic container categorization** — group +
  exposure data covers the use cases.
- **Graph view.** Network data captured in §5.3 is the seed if it's
  ever revisited.
- **Host-as-entity model** (a `host` table, per-host detail pages,
  aggregation of published ports across all containers on a host).
  Deferred indefinitely — useful but architecturally separate from
  STD's "one row per registered service" shape.
- **Logical service identity** (host-independent). Acknowledged as
  the right long-term direction. `(host, container_name)` remains
  the identity key for v0.6.0.
- **Per-service interpreter overrides.** The operator can't say
  "for this specific service, treat Traefik as external." They use
  an explicit `dockernotifier.std.externalurl` label instead.
- **Badge customization.** Each layer gets a default badge style;
  operators can't change icon/color per layer.
- **Interpreter conflict UI.** If two interpreters disagree on the
  hostname for the same direction (rare — usually they agree), the
  tiebreaker picks deterministically. No conflict-resolution UI in
  v0.6.0; operators who care use an explicit label.

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

### 10.2 Release history

1. STD v0.5.0 shipped `/api/v1/register` (canonical keys) alongside
   the `/api/register` compat shim that translated legacy keys.
2. Notifier v0.3.0 switched to canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 removed `/api/register` and all legacy-key handling.
   Operators on notifier v0.3.0+ are unaffected.
4. Notifier v0.4.0 (ships after STD v0.6.0) is the paired release
   for everything new in STD v0.6.0: it populates the
   `networks` / `exposed_ports` / `published_ports` capture fields
   and introduces the YAML interpreter mechanism that emits
   `exposure_observations`. STD's synthesizer reads those
   observations and writes synthesized URLs into `internalurl` /
   `externalurl`. Pre-v0.4.0 notifiers continue to register
   successfully — they just don't send the new fields, so the
   capture columns stay NULL and STD treats the missing
   `exposure_observations` as "no update" (existing exposure rows
   are preserved).

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
