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
| 0.6     | 2026-05-16 | v0.6.1 delivered. UI overhaul part 1: tiled drawer, Tabler Icons v3.34.0 icon vocabulary, per-template inline CSS/JS extracted to shared static files. §9 added. |
| 0.7     | 2026-05-16 | v0.6.2 hotfix. Restored `toggleRestoreSource` dropped during v0.6.1 JS extraction; wired file-input change event for filename feedback on /settings restore. |
| 0.8     | 2026-05-17 | v0.6.3–v0.6.6 UI Overhaul Part 2 arc delivered. Added §10 documenting v0.6.3 foundations, v0.6.4 mobile/tile restructure, v0.6.5 edit polish/delete UX/widget modal, and v0.6.6 widget drawer mode + brand exposure icons (modal removed). |
| 0.9     | 2026-05-23 | Documentation reconciliation audit. §9.6 forecast rewritten — the predicted v0.6.2 edit drawer / v0.6.3 staleness work did not ship; the actual v0.6.2–v0.6.6 arc is described in §10. §12 subsection numbering corrected (was using §10.x). §12.2 release history split notifier v0.3.2 (capture fields) from v0.4.0 (interpreters). FUTURE.md fictional release sequence references stripped. No code or schema changes. |
| 0.10    | 2026-05-23 | §12.2 correction. The v0.3.2 / v0.4.0 split introduced in 0.9 was wrong — notifier tags confirm no v0.3.2 release was ever cut; the capture fields and the interpreter mechanism both shipped in v0.4.0. Collapsed back to a single v0.4.0 pairing, with a parenthetical noting v0.3.2 as a developed-but-unreleased label so a future reader doesn't re-split from the stale `models.py` / `schemas.py` comments. |
| 0.11    | 2026-11-15 | v0.6.7 — registry move. §11 documents GHCR as the primary image registry and the final dual-publish to Docker Hub with the `REGISTRY_NOTICE` build arg driving the in-app deprecation banner. Workflow renamed `dockerhub.yml` → `publish.yml`. No schema, contract, or job changes. |
| 0.12    | 2026-11-15 | §11 documents the `CI` required checks and GHCR registry retention (adoption of `code-checkin-and-pr` v1.2.0). No schema, contract, or job changes. |
| 0.13    | 2026-11-15 | §11: versioning now uses a bare-semver `VERSION` file (Dockerfile writes `/app/version.txt` from it; `APP_VERSION` build arg removed) and releases are cut with `/release-prep` + `/release-cut` (adoption of `release-prep-and-cut` v1.1.0). No schema, contract, or job changes. |
| 0.14    | 2026-11-15 | §11: Docker Hub publishing removed; GHCR is the only registry (Docker Hub frozen at v0.6.7). The `REGISTRY_NOTICE` build arg, `registry_notice=` line in `/app/version.txt`, and in-app "moved to GHCR" banner were removed. No schema, contract, or job changes. |
| 0.15    | 2026-11-15 | v0.6.8 released. First release under the adopted standards (code-checkin-and-pr 1.2.0, handoff-prompt-workflow 2.0.0, release-prep-and-cut 1.1.0); GHCR-only publishing; `VERSION` file drives the in-app version; Add Entry non-numeric sort-priority 500 fixed. No schema or contract changes. |
| 0.16    | 2026-11-15 | Docs refresh after the standards adoption. Added §11 (v0.6.7–v0.6.8 registry move and engineering standards); later sections renumbered (§11→§12, §12→§13, §13→§14). §3.1 module layout updated to the current tree. §6 retitled as a historical baseline. No code, schema, or contract changes. |
| 0.17    | 2026-11-15 | Added §12 (v0.6.9 — Hardening and Safety Net, planned): test suite, wider lint, settings/API-token fixes, CSRF, soft-delete, widget detach, unified staleness, per-service health-check options, gunicorn + pinned deps, docs loose ends. Later sections renumbered (§12→§13, §13→§14, §14→§15). §15 Open Questions refreshed. No code changes yet. |
| 0.18    | 2026-11-15 | §12.1 delivered (unreleased): pytest suite, `STD_CONFIG_DIR` testability seam, CI `Test` job; §13 required-checks text updated. No schema, contract, or job changes. |
| 0.19    | 2026-11-15 | §12.2 delivered (unreleased): `ruff.toml` widened to `E, W, F, I, B` (E501 ignored); §3.1 lint note updated. No schema, contract, or job changes. |
| 0.20    | 2026-11-15 | §12.3 delivered (unreleased): `widget_value_retention_days` / `register_field_ownership` now load; unset `api_token` returns 503 on register; constant-time token compare; token masked in logs; default-credential warnings. No schema or wire-contract changes. |
| 0.21    | 2026-11-15 | §12.4 delivered (unreleased): Flask-WTF `CSRFProtect` on all UI POSTs and fetch calls; `/api/v1/register` exempt; `CSRFError` handler (flash+redirect or JSON 400). No schema or wire-contract changes. |
| 0.22    | 2026-11-15 | §12.5 delivered (unreleased): soft-delete (`service_entry.deleted_at`, §5.5), Settings → Deleted tab, `deleted_retention_days` and the 00:25 purge job, resurrect-on-register, `deleted_at` in YAML backups. Wire contract unchanged. |
| 0.23    | 2026-11-15 | §12.6 delivered (unreleased): hard delete keeps the widget and its values as a detached widget; Settings → Deleted lists detached widgets with Attach/Delete; refresh job skips detached widgets. No schema or wire-contract changes. |
| 0.24    | 2026-11-15 | §12.7 delivered (unreleased): `stale_after_minutes` setting (default 5) drives `is_docker_status_stale`; Tiled 120-minute clause removed; stale icon added to Dashboard and Compact. No schema or wire-contract changes. |
| 0.25    | 2026-11-15 | §12.8 delivered (unreleased): `health_check_timeout` setting; per-service `health_check_timeout` / `health_check_verify_tls` columns (§5.5) editable on Edit and Add; backups round-trip both. Wire contract unchanged. |
| 0.26    | 2026-11-15 | §12.9 delivered (unreleased): production runs gunicorn (one worker, four threads) via `gunicorn.conf.py`; startup work consolidated in `app.run_startup_tasks()`; `requirements.txt` fully pinned from `requirements.in`. §3 architecture and module layout updated. Wire contract unchanged. |
| 0.27    | 2026-11-15 | §12.10 delivered (unreleased): CHANGELOG historical dates corrected from tags; MIT `LICENSE` added; README compatibility note and registry wording refreshed. No code, schema, or wire-contract changes. |
| 0.28    | 2026-11-15 | v0.6.9 released. §12 retitled Delivered: pytest suite + required `Test` check, wider lint, settings and API-token fixes, CSRF protection, soft-delete with widget detach, unified staleness indicator, per-service health-check options, gunicorn + pinned dependencies. Schema: `deleted_at`, `health_check_timeout`, `health_check_verify_tls` (§5.5). No register-contract change. |
| 0.29    | 2026-11-15 | §12.11 added (delivered in v0.6.9, folded into the prepared release): icon names, server-side restore filenames and `/widget_config` widget names confined to their folders; edit/CSRF redirects limited to same-site paths (`image_utils.safe_icon_filename`, `view_helpers.safe_redirect_target`). Closes 13 CodeQL alerts. No schema, contract, or job changes. |
| 0.30    | 2026-11-15 | Added §13 (v0.7.0 — Dashboard and Monitoring, planned): entry sources (notifier vs manual), health checks as their own tables with service checks (HTTP/HTTPS status or body mode, TCP, ping), concurrent checker, 7-day history with 24h raw + hourly-compacted successes, health rollup and status/source filters, Gatus-style 24h history in the detail surface. Planned schema in §5.6. Later sections renumbered (§13→§14, §14→§15, §15→§16). No register-contract change. No code changes yet. |
| 0.31    | 2026-11-15 | §13.2 delivered (unreleased): `service_entry.source` / `description` / nullable `host` (migration `a7c3e9f15d28`, §5.6), register adoption of unlocked manual entries, manual-only Add page, source icon on Dashboard and Tiled, backups carry `source`/`description`. Lock relabelled "Lock (ignore notifier updates)". Register wire contract unchanged. |
| 0.32    | 2026-11-15 | §13.3 delivered (unreleased): `health_check` / `health_result` tables and models (migration `b8e4d6a2c1f9`, §5.6) with the two URL-kind rows per entry copied from the legacy columns; register toggles, Add/Edit and backup/restore read and write the rows; the interim sequential checker records results and mirrors into the legacy status columns until §13.5. Register wire contract unchanged. |
| 0.33    | 2026-11-15 | §13.4 delivered (unreleased): concurrent checker (`checker.py` probes for HTTP status/body, TCP and ping via pinned `icmplib`; `jobs.HealthScheduler`), settings `health_check_workers` / `health_raw_hours` / `health_history_days`, hourly compaction and purge jobs for `health_result`, `POST /service/<id>/checks/run`. No schema change. Register wire contract unchanged. |
| 0.34    | 2026-11-15 | §13.5 delivered (unreleased): "Health checks" section on Add and Edit (per-URL-check enabled/mode/interval/timeout/verify, repeatable service checks of type HTTP, TCP, Ping), server-side validation with input kept, flash messages on Add/Edit. No schema change. Register wire contract unchanged. |
| 0.35    | 2026-11-15 | §13.6 delivered (unreleased): `health_state.py` rollup (up/degraded/down/unknown/none), shared `health_badge.html` on Dashboard (new Health column), Tiled and Compact, `status` / `source` filters beside `show_urlless` with filtered/total count, `checks` eager-loaded per page, legacy status mirror and `checker.legacy_status` removed (backups derive the legacy keys from the rows). No schema change. Register wire contract unchanged. |
| 0.36    | 2026-11-15 | §13.7 delivered (unreleased), completing §13: `health_history.py`, `GET /service/<id>/health`, `partials/health_detail.html` + `static/js/health_detail.js`, panel in the Tiled drawer, a Dashboard expand row and the Edit page ("Health history"). §13 retitled Delivered (unreleased); §5.6 retitled. No schema change. Register wire contract unchanged. |
| 0.37    | 2026-11-15 | §13.8 added, delivered (unreleased): Container check, Docker state as an automatic health check on every notifier entry (migration `c1d7a3e5f2b8`, kind `container`, evaluated by the scheduler). §13.1 state note and §5.6 `kind` list updated; former §13.8 (out of scope) is now §13.9 and no longer lists Docker state. Register contract unchanged. |
| 0.38    | 2026-11-15 | v0.7.0 released. §13 retitled Delivered: entry sources (notifier vs manual), health checks as their own tables with URL, service (HTTP/HTTPS status or body, TCP, ping) and automatic Container checks, concurrent checker with 24h raw + hourly-compacted 7-day history, health rollup badge and Status/Source filters, health detail panel with 24h/7d history. Schema in §5.6. Register wire contract unchanged; no notifier change needed. |
| 0.39    | 2026-11-15 | §13.6 filter bar (unreleased, post-v0.7.0): "Total Services" replaced by clickable Total / Passing / Failing count chips that set the `status` filter; counts follow `source` / `show_urlless` but ignore `status`. No schema or register-contract change. |
| 0.40    | 2026-11-15 | §13.7: inline 24h uptime strips (unreleased, post-v0.7.0): "Show uptime" filter-bar checkbox kept in the `std_show_uptime` cookie, `GET /health/strips`, `health_history.strips()`, `static/js/uptime_strip.js`. No schema change. Register wire contract unchanged. |
| 0.41    | 2026-11-15 | v0.7.1 released: clickable Total / Passing / Failing count chips in the filter bar (§13.6) and the "Show uptime" toggle with inline 24h uptime strips (§13.7). No schema or register-contract change. |
| 0.42    | 2026-11-15 | Added §14 (v0.8.0 — Management API, planned): admin API keys with read/write scopes, `/api/v1` REST for entries, checks, health, groups, widgets and runtime settings, OpenAPI spec, write audit log, stdio MCP server. Planned schema §5.7. Later sections renumbered (§14→§15, §15→§16, §16→§17). Register contract unchanged. No code changes yet. |
| 0.43    | 2026-11-15 | §14.2 and §14.6 delivered (unreleased, v080-01): admin API keys (`api_key`, Settings → API tab, show-once), management blueprint skeleton (`require_api_key`, JSON errors, `GET /api/v1/whoami`), write audit log (`api_audit`, `audit()` helper, `after_request` hook, `api_audit_retention_days` + daily purge). Migration `d4a9e2c6b715`; §5.7 updated. Register wire contract unchanged. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Data Model](#5-data-model)
6. [Historical Baseline: State at v0.4.14](#6-historical-baseline-state-at-v0414)
7. [v0.5.0 — Cleanup Release](#7-v050--cleanup-release)
8. [v0.6.0 — Delivered](#8-v060--delivered)
9. [v0.6.1 — UI Rework Part 1 (Delivered)](#9-v061--ui-rework-part-1-delivered)
10. [v0.6.3–v0.6.6 — UI Overhaul Part 2 (Delivered)](#10-v063v066--ui-overhaul-part-2-delivered)
11. [v0.6.7–v0.6.8 — Registry move and engineering standards (Delivered)](#11-v067v068--registry-move-and-engineering-standards-delivered)
12. [v0.6.9 — Hardening and Safety Net (Delivered)](#12-v069--hardening-and-safety-net-delivered)
13. [v0.7.0 — Dashboard and Monitoring (Delivered)](#13-v070--dashboard-and-monitoring-delivered)
14. [v0.8.0 — Management API (Planned)](#14-v080--management-api-planned)
15. [Versioning, Branches, and Releases](#15-versioning-branches-and-releases)
16. [Cross-Repo Coordination](#16-cross-repo-coordination)
17. [Open Questions](#17-open-questions)

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
              │  │  Flask app (gunicorn, 1 worker)   │  │
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

### 3.1 Module layout

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
jobs.py             ← concurrent health-check scheduler, health-result
                      compaction/purge, widget refresh loop, daily
                      backup, widget_value retention prune,
                      verify-and-fetch-missing-icons startup sweep
checker.py          ← health-check probes (http/tcp/ping); network only, no DB
check_form.py       ← Add/Edit health-check form parsing + validation
health_state.py     ← per-entry health rollup (up/degraded/down/unknown/none)
health_history.py   ← history bars, uptime, recent failures for the detail panel
health.py           ← /healthz (liveness). /readyz not implemented.
settings_loader.py  ← file/ENV settings; loaded once at startup
settings_store.py   ← DB-stored runtime settings (per-interpreter directions)
synthesizer.py      ← exposure → internalurl/externalurl translation +
                      URL provenance tracking
image_utils.py      ← icon fetch + cache
view_helpers.py     ← grouping/sorting for dashboard views
templates/          ← Jinja templates
static/             ← static assets (css/, js/, icons/)
widgets/            ← per-widget plugin dirs
alembic/            ← migrations (alembic.ini at root)
scripts/            ← manual helper scripts (test_widget.py; not a test suite)
tests/              ← pytest suite (v0.6.9)
requirements-dev.txt ← pytest + runtime deps; CI/dev only
VERSION             ← bare-semver version source of truth
ruff.toml           ← lint config for CI (E, W, F, I, B; E501 ignored)
Dockerfile, entrypoint.sh, docker-compose.yml, requirements.txt
gunicorn.conf.py    ← production server config (workers must stay 1)
requirements.in     ← direct deps; requirements.txt is compiled from it
settings.example.yml, .env.example
standards.md        ← adopted standards + pinned versions
.github/workflows/  ← ci.yml, publish.yml, retention.yml
.claude/commands/   ← release-prep.md, release-cut.md
prompts/            ← handoff prompts (TEMPLATE.md, done/, failed/)
docs/               ← PRD.md, HISTORY.md, FUTURE.md, decisions.md, screenshots/
```

### 3.2 Module responsibilities

- **`app.py`** — `create_app()` factory: load settings once, init
  extensions, register blueprints, register error handlers, register
  template filters. Does not start background work on import —
  `run_startup_tasks(app)` (admin, icon sweep, `start_background_workers`)
  is invoked once per process: from the `__main__` block under
  `python app.py` (dev), or from the gunicorn `post_worker_init` hook in
  production, after migrations have completed.
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
| `ServiceEntry`   | `service_entry`    | One row per registered service. PK on `id`; logical key on `(host, container_name)` — indexed from v0.5.0. Holds URLs, health flags, group_id (FK), sort_priority, status, last-checked timestamps, image metadata, icon, the `is_static` flag (the lock), the v0.7.0 `source` / `description` columns, the v0.5.0 `notifier_reported_*` capture columns, the v0.6.0 `networks` / `exposed_ports` / `published_ports` capture columns, and the v0.6.0 `internalurl_source` / `externalurl_source` URL provenance columns. |
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

### 5.5 v0.6.9 schema changes

| Change | Detail |
|--------|--------|
| Column | `service_entry.deleted_at` (`DateTime`, nullable, indexed as `ix_service_entry_deleted_at`). NULL = active; a timestamp = soft-deleted at that time (naive server-local). Rows past `deleted_retention_days` are hard-deleted by the 00:25 purge job (§12.5). |

| Column | `service_entry.health_check_timeout` (`Integer` seconds, nullable; NULL = use the global `health_check_timeout` setting). Not indexed (not a lookup column). |
| Column | `service_entry.health_check_verify_tls` (`Boolean`, NOT NULL, server default true). Existing rows keep verifying TLS. |

Restoring a v0.6.8 backup leaves `deleted_at` NULL and the health-check
options at their defaults.

### 5.6 v0.7.0 schema changes

Shipped in v0.7.0 (§13); v070-06 added no schema. One Alembic migration per chunk; each FK gets
its index in the same migration.

| Change | Detail |
|--------|--------|
| Column | `service_entry.source` (`String(16)`, NOT NULL, server default `'notifier'`): `notifier` or `manual`. Backfill: `manual` where `last_api_update IS NULL`, else `notifier` (§13.2). |
| Column | `service_entry.host` becomes nullable (manual entries may omit it). `(host, container_name)` index unchanged. |
| Column | `service_entry.description` (`String(255)`, nullable). Operator text, mainly for manual entries. |
| Table  | `health_check`: one row per configured check. `service_entry_id` FK (ON DELETE CASCADE, indexed), `kind` (`internal_url` / `external_url` / `service` / `container`), `name`, `check_type` (`http` / `tcp` / `ping` / `docker`), `target` (NULL for URL kinds: they follow the entry's URL), `mode` (`status` / `body`), `interval_seconds` / `timeout_seconds` (nullable = global default), `verify_tls`, `enabled`, cached state `last_ok`, `last_checked_at`, `last_status_code`, `last_latency_ms`, `last_message`, `consecutive_failures`. Exactly one `internal_url` and one `external_url` row per entry; zero or more `service` rows; exactly one `container` row per notifier entry (none for manual entries). |
| Table  | `health_result`: one row per check sample or compacted success range. `check_id` FK (ON DELETE CASCADE), `ts`, `ts_end` (NULL for a single sample), `samples` (default 1), `ok`, `latency_ms` (average for a range), `latency_max_ms`, `status_code`, `message`. Composite index `(check_id, ts)` (also serves the FK). Timestamps are naive UTC. |
| Data   | Migration creates the two URL-kind `health_check` rows for every entry, copying `*_health_check_enabled`, `health_check_timeout`, `health_check_verify_tls` and the last status. |
| Data   | Migration `c1d7a3e5f2b8` inserts one enabled `container` row for every `source='notifier'` entry (soft-deleted included). No new columns or indexes; the downgrade deletes the rows and their results. |
| Deprecated | `service_entry.internal_/external_health_check_enabled/_status/_update`, `health_check_timeout`, `health_check_verify_tls`: no longer read after v0.7.0; kept for rollback, dropped in a later release (FUTURE.md). |


### 5.7 v0.8.0 schema changes (planned; `api_key` and `api_audit` delivered, unreleased)

Planned for v0.8.0 (§14). FKs get their index in the same migration. `api_key` and `api_audit` shipped in migration `d4a9e2c6b715` (v080-01); column types: `object_type` `String(32)`, `object_id` `String(64)` (ids are stored as text), `path` `String(255)`, `method` `String(8)`; indexes `ix_api_key_prefix`, `ix_api_key_created_by`, `ix_api_audit_ts`, `ix_api_audit_api_key_id`.

| Change | Detail |
|--------|--------|
| Table | `api_key`: `id`, `name` (unique), `prefix` (indexed), `key_hash` (SHA-256 hex), `scope` (`read`/`write`), `created_at`, `created_by` (FK `user.id`, nullable, indexed), `last_used_at`, `last_used_ip`, `revoked_at`. |
| Table | `api_audit`: `id`, `ts` (naive UTC, indexed), `api_key_id` (FK `api_key.id` ON DELETE SET NULL, indexed), `key_name`, `method`, `path`, `object_type`, `object_id`, `status_code`, `changes` (JSON). Pruned by `api_audit_retention_days`. |

---

## 6. Historical Baseline: State at v0.4.14

> Historical snapshot of the pre-v0.5.0 codebase, kept for context. It does
> not describe the current state; see §§7–11 for what shipped since.

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

## 9. v0.6.1 — UI Rework Part 1 (Delivered)

Patch release shipped 2026-05-16. No schema, API, config, or backend
changes. Templates and static files only.

### 9.1 Goals

Formalize the visual language across all three dashboard views, extract
per-template CSS/JS into shared static files, and deliver the core Tiled
redesign that replaces text pills with an icon vocabulary and adds an
expand drawer for per-service detail.

### 9.2 Extraction

Per-template inline `<style>` and `<script>` blocks consolidated into:

- `static/css/dashboard.css` — design tokens (CSS custom properties),
  shared component classes: `.tile`, `.tile-drawer`, `.status-icon`,
  `.status-pill`, `.exposure-badge`, `.drawer-*`, etc.
- `static/js/dashboard.js` — shared behaviors: auto-refresh, group
  collapse, view-control submit-on-change, filter-input (view-detected
  via `data-view` on `<body>`), tile-click, drawer open/close, tools
  popover, delete confirmation, `toggleGroup`, `copyToClipboard`.

Tailwind CDN stays for layout utilities; custom CSS handles components.
No frontend build step introduced.

### 9.3 Icon vocabulary

Tabler Icons (v3.34.0) loaded via cdnjs CDN. Outline set only.

| Purpose | Icon |
| ------- | ---- |
| Internal URL health | `ti-home` |
| External URL health | `ti-world` |
| Docker status | `ti-brand-docker` |
| Widget indicator | `ti-chart-line` |
| Dozzle logs | `ti-terminal-2` |
| Edit | `ti-edit` |
| Delete | `ti-trash` |
| Tools popover | `ti-tools` |
| Expand/collapse | `ti-chevron-down` / `ti-chevron-up` |
| TLS badge | `ti-lock` |
| Auth badge | `ti-key` |

Status colors: green `#22c55e` (ok), amber `#f59e0b` (warn/stale),
red `#ef4444` (bad), gray `#6b7280` (not configured / static).

### 9.4 Tiled redesign

- Tile face: icon + container name + exposure badges + status icon row.
  Host line removed from tile face; moved to drawer.
- Status icon row (right-aligned): internal URL, external URL, Docker,
  separator, widget indicator (if present), Dozzle (if configured),
  edit pencil, expand chevron.
- Tile-headless treatment unchanged: no click affordance or hover border
  on tiles with no URL, no exposures, and no widget. Chevron still shown.
- Expand drawer: absolutely-positioned overlay beneath the tile. Closes
  on outside click or second chevron press. Only one drawer open at a
  time. Contains: host, URLs with health status, Docker with image tag,
  networks, ports, exposure observations, widget data grid. Action row:
  Edit button, Delete button (JS `confirm()` / `prompt()` for static
  entries), Tools popover (Dozzle link when available).

### 9.5 Other view changes

- **Dashboard table:** status pills updated to icon-and-label pairs
  sharing the Tiled vocabulary. Edit column uses pencil icon.
  Dozzle Tools column uses `ti-terminal-2`.
- **Compact tab:** missing `active_tab = 'compact'` variable added;
  tab now correctly highlights in the nav.
- **Exposure badges** (all views): 🔒 / 🔑 emoji replaced with
  `ti-lock` / `ti-key` Tabler icons.
- **Widget toggle removed** from Tiled filter bar; widget data now
  lives in the per-tile drawer.

### 9.6 UI rework arc

v0.6.1 is the first of a multi-release UI overhaul. The actual
sequence that shipped on top of v0.6.1 is documented in §10:

- **v0.6.2** — Hotfix: restored `toggleRestoreSource` dropped during
  the v0.6.1 JS extraction; wired the filename-display feedback on
  /settings restore. (The originally-forecast "edit drawer" did not
  ship and is no longer planned — the edit page got in-place polish
  in v0.6.5 instead.)
- **v0.6.3** — Orphan inline-CSS/JS sweep completing the v0.6.1
  extraction; "what's new" popup; `version_info` context processor.
- **v0.6.4** — Mobile filter bar, two-row tile icon layout, drawer
  scroll-into-view on mobile.
- **v0.6.5** — Edit-page polish, universal delete popover, widget
  modal, auto-refresh pause on interaction.
- **v0.6.6** — Widget drawer mode (replaces the v0.6.5 modal), brand
  exposure icons (replace text-pill exposure badges).

No backend, schema, or API changes shipped in this arc except the
v0.6.6 brand SVG assets under `static/icons/exposure/`. v0.7.0 will
cut when there is a non-UI scoped change to deliver; no fixed date.

---

## 10. v0.6.3–v0.6.6 — UI Overhaul Part 2 (Delivered)

No schema, API, config, or backend changes in this arc except the
addition of `static/icons/exposure/` brand SVG assets in v0.6.6.

### 10.1 v0.6.3 — Foundations

- Orphan sweep: removed remaining per-template inline CSS/JS not cleaned
  up in v0.6.1.
- "What's New" popup: `changelog_modal.html` partial fetches
  `/api/v1/changelog`, compares a `localStorage`-stored last-seen version,
  and surfaces only the new sections. Dismissible, Esc-friendly.

### 10.2 v0.6.4 — Mobile Usability + Tile Icon Restructure

- Filter bar collapses below 640 px behind a toggle button; dismisses on
  click-outside and Esc.
- Status icons split into two rows: status (home, world, docker, widget)
  and actions (Dozzle, edit, trash/lock, chevron). Prevents name
  truncation at mobile font sizes.
- Drawer auto-scrolls the tile into view on mobile on chevron click.

### 10.3 v0.6.5 — Edit Polish, Universal Delete, Widget Modal

- Edit page: tighter inputs, section headings, inline health-check
  checkboxes, tab-style group selector.
- Universal delete popover: all delete affordances share a single
  position-fixed confirm popover. `prompt()`-based confirmation removed.
- Widget data modal: clicking the chart icon opened a centered modal
  overlay showing just that service's widget cards.
- Auto-refresh pause while a drawer, the widget modal, or the changelog
  popup is open.
- One-click trash icons on Tiled tiles and Dashboard rows; static entries
  show a lock icon instead.

### 10.4 v0.6.6 — Widget Drawer + Brand Exposure Icons

**Widget drawer mode.** The v0.6.5 widget modal replaced by a mode of
the existing tile drawer. The `tile-drawer` element gains a two-class
system (`drawer-mode-full` / `drawer-mode-widget`):

- Full mode (`drawer-mode-full`): all drawer sections visible, same as
  the prior chevron behavior.
- Widget mode (`drawer-mode-widget`): CSS hides every `drawer-row`
  except `.drawer-row-widget`, hides the divider and action row.

Clicking the chart icon: opens widget mode if closed; closes if already
widget mode; switches from full to widget mode in-place. Clicking the
chevron: opens full mode if closed; promotes widget mode to full in-place;
closes if already full. Esc and click-outside always close. The
`isInteracting()` refresh-pause check requires no changes — the widget
view is an open drawer (`currentOpenDrawer !== null`). The widget modal
partial, its `base.html` include, `initWidgetModal()`, and the
`.widget-modal` CSS block are removed.

**Brand exposure icons.** Text-pill `.exposure-badge` badges replaced
with 18 × 18 px brand SVG logos. Per layer: brand logo + `ti-lock`
overlay (TLS) + `ti-pencil` overlay (explicit hostname configured).
Unknown layers fall back to `ti-route`. SVGs committed to
`static/icons/exposure/` with a `README.md` documenting sources.

| Layer | File | Source |
| ----- | ---- | ------ |
| traefik | `traefik.svg` | `traefik/traefik` GitHub — vertical logo, teal symbol crop |
| cloudflare | `cloudflare.svg` | cloudflare.com — `logo-cloudflare-dark.svg`, cloud crop |
| dockflare | `dockflare.svg` | Same as cloudflare.svg (DockFlare = Cloudflare Tunnel wrapper) |
| nginx | `nginx.svg` | nginx.org — `nginx_logo.svg`, green N crop |
| caddy | `caddy.svg` | `caddyserver/website` GitHub — `caddy-circle-lock.svg`, 1:1 icon |

Old `.exposure-badge` CSS replaced with `.exposure-icons` /
`.exposure-icon-layer` / `.exposure-icon-img` / `.exposure-icon-tls` /
`.exposure-icon-label` / `.exposure-icon-fallback` classes.

---

## 11. v0.6.7–v0.6.8 — Registry move and engineering standards (Delivered)

No schema, register-contract, or job changes. Reference for the resulting
release mechanics is §15 (Versioning, Branches, and Releases); this section
records what was delivered and why.

### 11.1 v0.6.7 — Registry move

- Images moved to GHCR (`ghcr.io/crzykidd/service-tracker-dashboard`);
  `dockerhub.yml` was renamed `publish.yml`.
- v0.6.7 was published to both registries. The Docker Hub build set
  `REGISTRY_NOTICE=dockerhub`, which rendered an in-app "moved to GHCR"
  banner; the GHCR build did not. This was the banner-only final Docker Hub
  release. Rationale: [`decisions.md`](./decisions.md).

### 11.2 v0.6.8 — Standards adoption and Docker Hub removal

- Docker Hub publishing, the `REGISTRY_NOTICE` build arg, and the banner were
  removed. Docker Hub tags stay frozen at v0.6.7.
- `VERSION` (bare semver) is the single source of the in-app version; the
  Dockerfile writes `/app/version.txt` from it and the `APP_VERSION` build arg
  is gone. `publish.yml` fails a release whose tag (minus `v`) != `VERSION`.
- CI checks (`Lint`, `Config validation`, `Migration check`,
  `Compose validation`) added in `ci.yml`; GHCR retention added in
  `retention.yml`; CodeQL and the image `build` job are the other required
  checks (§15).
- Release commands `/release-prep` and `/release-cut` added in
  `.claude/commands/`.
- Fixed: Add Entry (`/add`) raised a 500 on a non-numeric sort priority
  (`NameError`); the group dropdown is now also populated on every
  validation re-render.
- Developer tooling: vexp removed; `standards.md`, `prompts/`, and
  `docs/decisions.md` added. See [`HISTORY.md`](./HISTORY.md).

---

## 12. v0.6.9 — Hardening and Safety Net (Delivered)

> **Status:** shipped in v0.6.9 (2026-11-15). Scoped 2026-11-15; each
> subsection was one handoff prompt (named in brackets, now in
> `prompts/done/`), run in the order listed.

A deliberately large **patch** release that bundles the post-v0.6.8
review findings: two real bugs, a security pass, a test suite, a
delete safety net, and runtime/operational upgrades. It is a patch,
not 0.7.0, so `/release-prep` does not run the minor-release CHANGELOG
archive step (decision: [`decisions.md`](./decisions.md), 2026-11-15).

**Cross-repo:** no register-contract change. Nothing in this release
adds, removes, or re-types a `RegisterPayload` field, so the
consumer-leads ordering rule (§16) is not engaged and every notifier
version that works with v0.6.8 works with v0.6.9. The only
register-path behavior change is §12.5's resurrect-on-register for
soft-deleted rows, which is server-side only.

### 12.1 Test suite and CI `Test` check [`v069-01-test-suite`] — Delivered in v0.6.9

- `pytest` suite under `tests/`, dev dependencies in
  `requirements-dev.txt` (not shipped in the image).
- **Testability seam:** `app.py` and `settings_loader.py` hardcode
  `/config/...` paths and `app.py` builds the app at import. Introduce a
  `STD_CONFIG_DIR` environment variable (default `/config`) that every
  `/config` path derives from, so tests run against a temp dir. Tests
  build the schema with `db.create_all()`; Alembic correctness stays
  with the `Migration check` job.
- Initial coverage, written against the *current* behavior (pins what
  v0.6.8 does, including the bugs §12.3 fixes — those tests are
  `xfail` until §12.3 flips them): register auth, `extra="forbid"` → 400,
  `exposure_observations` absent vs `[]`, URL provenance ordering,
  `register_field_ownership` modes, settings loader precedence
  (ENV > file > default).
- New `Test` job in `ci.yml`. The `Test` exemption in `standards.md` is
  removed. Adding `Test` as a **required** check in GitHub branch
  protection is a manual operator step (the prompt does not touch
  GitHub settings).
- **As built:** `STD_CONFIG_DIR` (read in `settings_loader.CONFIG_DIR`) also
  drives the `backup_path` default and the `/config/backups` fallbacks in
  `jobs.py` / `routes_dashboard.py`. `tests/conftest.py` sets the env and
  creates a temp config dir at import time, before `app` is imported (so
  `app.py` is unchanged structurally). Icon downloads are stubbed in tests.
  Two `xfail(strict=True)` tests pin the §12.3 bugs.

### 12.2 Wider lint [`v069-02-widen-lint`] — Delivered in v0.6.9

- `ruff.toml` widens from `E9, F` to `E, W, F, I, B` (E501 ignored —
  line length is not worth the churn). One mechanical cleanup pass;
  no behavior changes. Any `B` finding that is a real bug is fixed and
  gets a CHANGELOG `Fixed` entry; anything ambiguous is
  `# noqa`-annotated with a reason rather than "fixed" blind.
- **As built:** the cleanup found 30 findings (20 `I001`, 4 `E402`,
  2 `B009`, 2 `B010`, 2 `W291`); none was a real bug (the `B009`/`B010`
  were constant-name `getattr`/`setattr`, rewritten as plain attribute
  access). `alembic/versions/*` is exempt from `I001`/`W291` and
  `alembic/env.py` from `E402` (intentional `sys.path` setup) via
  `per-file-ignores`.

### 12.3 Settings and API-token hardening [`v069-03-settings-and-token-hardening`] — Delivered in v0.6.9

- **Fix:** `settings_loader.VALID_KEYS` omits
  `widget_value_retention_days` and `register_field_ownership`, so both
  documented settings are silently dropped and their defaults always
  apply. Add them (and every other key `settings.example.yml`
  documents). A test asserts every key in `settings.example.yml` is in
  `VALID_KEYS`, so new settings can't regress this.
- **Fix:** with `API_TOKEN` unset, `_check_bearer_auth` compares against
  the string `"Bearer None"` and accepts it. New behavior: no token
  configured → `/api/v1/register` returns **503**
  `{"error": "API token not configured"}`; a WARNING at startup; a
  notice on Settings → Service Info. The UI keeps working (rejected:
  failing startup — it breaks UI-only installs).
- Token comparison uses `hmac.compare_digest`.
- Startup settings logging masks `api_token` (and any future secret
  keys) instead of printing them.
- **Default-credential warnings:** if `FLASK_SECRET_KEY` is unset (the
  `"changeme-in-prod"` fallback is in use) or the `admin` user still
  has the `changeme123` password, log a WARNING at startup and show a
  dismissible notice on Settings for admins. No forced change.
- **As built:** `widget_value_retention_days` (int, 30) and
  `register_field_ownership` (str, `user_wins`) added to `VALID_KEYS`; a test
  parses `settings.example.yml` (including `#key:` lines) against
  `VALID_KEYS`. `settings_loader.SECRET_KEYS` / `mask_value()` mask secrets
  in all startup/debug settings logs. `routes_auth.refresh_default_password_flag()`
  computes the `changeme123` check once at startup and after password
  set/reset, caching it in `app.config["DEFAULT_ADMIN_PASSWORD_IN_USE"]`
  (`DEFAULT_SECRET_KEY_IN_USE` likewise). The Settings dismissal is per
  browser session (`sessionStorage`). The two §12.1 `xfail` tests are now
  passing tests.

### 12.4 CSRF protection [`v069-04-csrf`] — Delivered in v0.6.9

- `Flask-WTF` `CSRFProtect` on the app. Every HTML form posts
  `csrf_token()`; `base.html` carries a `<meta name="csrf-token">` and
  every JS `fetch` POST sends it as `X-CSRFToken`.
- `/api/v1/register` is exempt (bearer-token API, no cookies).
- `WTF_CSRF_TIME_LIMIT = None` — tokens live as long as the session, so
  a dashboard left open for hours doesn't 400 on the next delete.
- CSRF failure: HTML forms flash an error and redirect back; JSON
  endpoints return `400 {"error": "CSRF token missing or invalid"}`.
- As built: `csrf = CSRFProtect()` in `extensions.py`, initialized in
  `create_app()`; a `CSRFError` handler in `app.py` treats a request as
  JSON when `request.is_json`, the path starts with `/api/`, an
  `X-CSRFToken` header is present, or `Accept` includes `application/json`.
  JS POSTs go through the shared `window.stdPost(url, options)` helper in
  `static/js/dashboard.js`. Tests enable CSRF only in `tests/test_csrf.py`.

### 12.5 Soft-delete for service entries [`v069-05-soft-delete`] — Delivered in v0.6.9

Picks up the FUTURE.md "Soft-delete for service entries" entry.

- **Schema:** `service_entry.deleted_at` (`DateTime`, nullable,
  indexed) via Alembic.
- **Delete** (edit page, `/api/v1/entries/<id>/delete`, tile/row trash
  icons) sets `deleted_at` instead of deleting. Widget rows are left
  attached.
- **Filtering:** soft-deleted rows are excluded from all three
  dashboards, the health-check loop, widget refresh, badges, and the
  `/dbdump` default view. Implement as one model-level helper
  (e.g. `ServiceEntry.active()`), and audit every `ServiceEntry.query`
  call site — there are ~18.
- **Settings → Deleted** tab lists soft-deleted entries with
  **Restore** and **Delete permanently** (the latter goes through
  §12.6's hard-delete path).
- **Purge job:** daily at 00:25 hard-deletes rows whose `deleted_at` is
  older than `deleted_retention_days` (new setting, default `30`,
  `0` = purge on the next run).
- **Resurrect on register:** a register for a `(host, container_name)`
  that matches a soft-deleted row **clears `deleted_at`** and updates
  that row, keeping all curated state. Rationale: today a hard-deleted
  running container reappears empty on its next register; resurrecting
  the curated row is strictly better, and keeping a live container
  invisible would be worse. Logged at INFO.
- **Backup/restore:** YAML backups include `deleted_at`; restore
  round-trips it. Backups from v0.6.8 restore with `deleted_at` NULL.

As built: migration `e5a1c7d93b02`; `ServiceEntry.active()` /
`.deleted()` helpers and a single `hard_delete_entry(entry)` in
`models.py` (the pre-existing widget-if-unused delete moved there
unchanged; §12.6 changes only that function). Deviations from the plan
above: `/dbdump` shows deleted rows **marked** (struck through, Deleted
At column) rather than hiding them; the register lookup prefers an
active row over a deleted one; a static-locked deleted entry is not
resurrected by register (static skip wins); the Group `services_count`
badge counts active entries only and deleting a group detaches its
soft-deleted entries (`group_id` → NULL); the widget refresh skips
widgets whose services are all soft-deleted; `recompute_all` and the
scheduled/manual backups deliberately include deleted rows. New routes:
`POST /settings/deleted/<id>/restore` and `/delete` (admin, CSRF).

### 12.6 Widget detach on hard delete [`v069-06-widget-detach`] — Delivered in v0.6.9

- When a service entry is hard-deleted (purge job or Delete
  permanently), its widget is **detached**, not deleted: the `Widget`
  row and its `widget_value` history are kept (retention still prunes
  values normally).
- A widget is **detached** when no service entry (active or
  soft-deleted) references it. Detached widgets are skipped by the
  widget refresh job.
- **Settings → Deleted** gains a "Detached widgets" list: **Attach to
  service** (picker of entries with no widget) or **Delete** (removes
  the widget and its values).

As built: `Widget.detached()` (no `ServiceEntry` references it);
`hard_delete_entry` now only deletes the entry. Routes (admin, CSRF):
`POST /settings/widgets/<id>/attach` (form field `entry_id`, active entries
with `widget_id IS NULL` only) and `POST /settings/widgets/<id>/delete`. The
refresh job now refreshes only widgets with at least one **active** service,
so it skips both detached widgets and widgets referenced only by soft-deleted
entries (this also stops refreshing pre-existing unreferenced widget rows).
The edit page was left unchanged (it edits a widget in place; choosing "none"
still deletes it deliberately).

### 12.7 Unified staleness indicator [`v069-07-staleness`] — Delivered in v0.6.9

- Today staleness is shown only on the Tiled view, and the logic is
  split: the model property uses 5 minutes and the template adds a
  redundant 120-minute clause.
- One threshold, new setting `stale_after_minutes` (default `5`, which
  keeps current Tiled behavior; the notifier re-scans every 60 s by
  default). `ServiceEntry.is_docker_status_stale` reads it; the
  template clause is removed.
- The stale indicator (same icon/tooltip vocabulary as Tiled) appears
  on the Dashboard table and Compact views too. Static entries are
  never stale. This is the staleness-visualization prerequisite named
  in FUTURE.md's duplicate-detection entry; the same threshold will be
  reused there.
- **As built:** Dashboard shows a `ti-clock-exclamation` warn icon beside
  the Docker pill; Compact shows the same icon right-aligned in the tile
  (the Tiled icon turns amber as before). Both appear only for dynamic
  entries that have a `last_api_update` and are stale; a never-updated
  dynamic entry still counts as stale in the model but Tiled keeps its
  separate red "no update received" state, and Dashboard keeps its red
  pill. Outside an app context the threshold falls back to 5.

### 12.8 Per-service health-check options [`v069-08-health-check-options`] — Delivered in v0.6.9

Resolves the Open Question on health-check timeouts (§17).

- **Schema:** `service_entry.health_check_timeout` (Integer seconds,
  nullable → use the global default) and
  `service_entry.health_check_verify_tls` (Boolean, NOT NULL, server
  default true).
- New global setting `health_check_timeout` (default `5`, today's
  hardcoded value).
- Edit page gains both fields in an advanced section. Both are
  operator-curated, not register fields — the notifier never sends them
  (no contract change).
- `verify_tls = false` passes `verify=False` to `requests` and
  suppresses the urllib3 InsecureRequestWarning for that call only.
- **As built:** the per-URL check is `jobs.check_url(url, entry,
  default_timeout)`; timeout is `entry.health_check_timeout` or the
  global setting. The edit page has an "Advanced health check" section;
  the Add page carries the same two fields (verify defaults on).
  Timeout is validated as a whole number 1-60 (blank = default); an
  invalid edit-page value is rejected with a warning and the stored
  value kept. Both fields round-trip through YAML backup/restore
  (absent in older backups = global timeout, verify on). No register
  contract change: `schemas.py` untouched and `upsert_service` never
  writes either column.
- Out of scope: concurrent health checks. Sequential checks with longer
  per-service timeouts lengthen a pass; acceptable at homelab scale.

### 12.9 Production WSGI server and pinned dependencies [`v069-09-gunicorn-and-pins`] — Delivered in v0.6.9

- The image runs **gunicorn** instead of the Werkzeug dev server
  (`python app.py`). **Exactly one worker** (`--workers 1`, several
  threads): the register mutex, APScheduler, and the health-check
  thread are all in-process and must not be duplicated. Startup work
  now in `__main__` (default admin, icon verify, background workers)
  moves to a function invoked once from a `gunicorn.conf.py` hook.
- `python app.py` keeps working for local development.
- `requirements.txt` becomes fully pinned (generated from a
  `requirements.in` with `uv pip compile`); the Dockerfile installs the
  pinned set.
- Operator-visible: log format at startup changes (gunicorn lines); no
  config change required. Port stays 8815.
- **As built:** `app.run_startup_tasks(app)` (idempotent per process) does the
  default admin, icon sweep and `start_background_workers`; `__main__` and
  `gunicorn.conf.py`'s `post_worker_init` both call it. `workers = 1`,
  `threads = 4`, no `preload_app`. `entrypoint.sh` runs gunicorn unless
  `FLASK_DEBUG=1`, which keeps `python app.py`. Pins come from
  `requirements.in` via `uv pip compile --python-version 3.11`; the image
  is built for linux/amd64 only (publish.yml sets no platforms).

### 12.10 Docs loose ends [`v069-10-docs-loose-ends`] — Delivered in v0.6.9

- CHANGELOG: replace the `2026-XX-XX` placeholder dates on 0.1.x–0.4.x
  with the real git-tag dates (all **2025**; e.g. v0.4.0 2025-06-05,
  v0.4.14 2025-07-12; series headers use the first tag's date).
- Add an MIT `LICENSE` file (the README already links one).
- README: replace the v0.6.0 `/api/register` top banner with a short
  current-compatibility note; reword "GHCR images start at v0.6.7" so it
  doesn't age.
- Out of scope (upstream): the stale `release-prep-and-cut @ v1.0.0`
  text in the CLAUDE.md snippet and `.claude/commands/` headers is
  stale in `homelab-configs` itself; fix it there, then re-sync.
- README screenshots remain stale (needs a live instance; not
  agent-doable).
- As built: dates taken from tags (0.3.x/0.2.x/0.1.x series use v0.3.0
  2025-05-31, v0.2.0 2025-05-27, v0.1.0 2025-05-26). The What's New
  parser skips `[0.x.x] series` headers (no match), so they are inert.

### 12.11 CodeQL path and redirect fixes [`v069-11-codeql-path-and-redirect`] — Delivered in v0.6.9

Closes 13 open CodeQL alerts on `main`: 11 `py/path-injection` and 2
`py/url-redirection`.

- **Icon names** (register `image_icon` and derived names, `/add`, `/edit`)
  go through `image_utils.safe_icon_filename` (lowercase, optional `.svg`
  stripped, `^[a-z0-9][a-z0-9._-]*$`, no `..`, at most 100 chars including
  `.svg`). The path is then checked with `icon_path_in_dir` (`realpath`
  containment in `IMAGE_DIR`) before any write. Register skips an unsafe icon
  with a WARNING and still succeeds; Add/Edit flash a message and download
  nothing (Edit leaves the stored icon unchanged and saves the other fields).
- **Backup restore from a server file** accepts only a bare filename ending
  `.yaml`/`.yml` whose resolved path stays inside the backup folder.
- **`/widget_config/<widget_name>`** accepts only directory names present
  under `widgets/`, resolved from the app root rather than `/app/widgets`.
- **Redirects:** `view_helpers.safe_redirect_target` allows only same-site
  relative paths (single leading `/`, no scheme/netloc, no `//` or `/\`).
  Used for the edit page's `ref` (save, delete, and the wrong-confirmation
  bounce) and the CSRF error handler's referrer fallback.
- As built: the Add page's `ref` was parsed but never used, so that dead code
  was removed rather than hardened. The Add and Edit templates do not render
  flashed messages (only Settings does), so the invalid-icon message is
  queued for the next Settings view rather than shown inline; see
  `docs/decisions.md`.

---

## 13. v0.7.0 — Dashboard and Monitoring (Delivered)

> **Status:** shipped in v0.7.0 (2026-11-15). Scoped 2026-11-15. Each subsection is one handoff
> prompt (named in brackets, in `prompts/`), run in the order listed.
> Each chunk left the app working and the test suite green.

A **minor** release with one theme: turn STD from a Docker inventory
with URL pings into a **dashboard with simple monitoring**. That means
three things:

1. Non-Docker sites (router, NAS, SaaS, a printer) are a first-class
   **manual** entry, not a fake container.
2. Health checks become their own model, with a new **service check**
   (HTTP/HTTPS status or body, TCP, ping) next to the internal and
   external URL checks.
3. **7 days of check history** with a Gatus-style 24-hour bar strip in
   the detail view, plus a health **status filter** on every view.

Because it is a minor, `/release-prep 0.7.0` runs the per-minor
CHANGELOG archive step, which archives every closed series (0.1.x–0.6.x)
into `docs/CHANGELOG-<minor>.x.md`. The 0.1.x–0.3.x blocks are
`## [0.N.x] series — <date>` headers, not `## [0.N.PATCH]`. The
release-prep run must treat each as the whole of its series and archive
it as `docs/CHANGELOG-0.N.x.md`.

**Cross-repo:** **no register-contract change.** The notifier keeps
sending exactly what it sends today; `schemas.py` is untouched, so the
ordering rule (§16) is not engaged. Every notifier version that works
with v0.6.9 works with v0.7.0. `internal_health_check_enabled` /
`external_health_check_enabled` keep their meaning: they enable or
disable the entry's `internal_url` / `external_url` check rows. A
notifier-defined service check (from container labels) would be a
new register field. That is parked in FUTURE.md; if picked up, STD
accepts the field and ships first.

### 13.1 Concepts

- **Entry**: one thing on the dashboard. Its **source** is `notifier`
  (created and kept current by `/api/v1/register`) or `manual` (created
  on the Add page).
- **Check**: one configured probe on an entry. Three kinds:
  - `internal_url` and `external_url` probe the entry's URL of that
    name, so they always follow the current URL, including synthesizer
    changes. Each entry has exactly one of each (possibly disabled).
  - `service` checks have their own target and type. An entry can
    have zero or more.
- **Result**: one sample (`ok` true/false, latency, status code,
  message). Every check produces a **health or failure**. The detail
  is in the message.
- **Health state** of an entry, rolled up from its enabled checks:

  | State      | Meaning |
  |------------|---------|
  | `up`       | every enabled check's last result is ok |
  | `degraded` | at least one ok and at least one failing |
  | `down`     | every enabled check that has run is failing |
  | `unknown`  | checks are enabled but none has run yet |
  | `none`     | no enabled checks |

  Docker state counts: every notifier entry has an automatic **Container**
  check (§13.8). The Docker pill and stale icon on the views stay as well.

### 13.2 Entry sources and manual entries [`v070-01-entry-sources`] — Delivered in v0.7.0

**As built:** migration `a7c3e9f15d28` adds `service_entry.source` (backfilled
by the rule below), `description`, and makes `host` nullable.
`ServiceEntry.is_manual` is true for `source == 'manual'`;
`is_docker_status_stale` is false for manual or locked entries.
`upsert_service` adopts an unlocked manual match (INFO log, `source` becomes
`notifier`); a soft-deleted manual match is adopted and resurrected by the same
path. New register rows are `notifier`; `schemas.py` is untouched. The Add
page (`name`/`container_name`, optional host, description) creates manual
entries; the duplicate check matches `host IS NULL` explicitly and prefers an
active row over a soft-deleted one. Edit hides the "Reported by notifier"
block for manual entries and shows Description; blank Host saves as NULL for
manual entries only. Dashboard shows a "Manual" pill and Tiled a `ti-link`
icon where the Docker pill sits; Compact is unchanged apart from the stale
icon no longer appearing for manual entries. Backups export `source` and
`description`; restore without `source` applies the backfill rule, and a
record without a host is skipped unless it is manual.

- **Schema** (§5.6): `service_entry.source`, nullable `host`,
  `description`.
- **Backfill:** `last_api_update IS NULL` → `manual`, else `notifier`.
- **Manual entries**:
  - Fields: Name (stored in `container_name`, labelled "Name" in the
    UI), optional Host, Description, Group, Icon, URLs, sort priority.
  - No Docker fields: container id, stack, image, Docker status,
    started-at and the "Reported by notifier" block are hidden on Edit.
  - Never stale. Duplicate check on Add is (host, name), with an empty
    host treated as its own value.
- **Notifier entries**: behave as today. `is_static` is relabelled
  **"Lock (ignore notifier updates)"**. It no longer means "manual",
  and staleness is suppressed by `source == 'manual'` or the lock.
- **The Add page creates manual entries only**; Docker entries come
  from the notifier. Its wording changes from "application" or
  container to "Name".
- **Register adoption:** a register whose (host, container_name)
  matches an unlocked **manual** entry adopts it: `source` becomes
  `notifier` and the register updates it as usual. This preserves
  today's "pre-stage an entry, then the notifier fills it in"
  behaviour. A locked manual entry still returns `skipped`. A manual
  entry with no host can never be matched.
- **Backups** carry `source` and `description`. An older backup with no
  `source` is backfilled by the same rule as the migration.
- Dashboard and Tiled show a small source icon (Docker vs manual) where
  the Docker pill sits today; manual entries show no Docker pill.

### 13.3 Health-check schema and data migration [`v070-02-health-schema`] — Delivered in v0.7.0

**As built:** migration `b8e4d6a2c1f9` creates `health_check` and
`health_result` (indexes `ix_health_check_service_entry_id` and
`ix_health_result_check_id_ts`) and inserts both URL-kind rows for every
entry from the legacy columns; its downgrade copies `enabled`, timeout and
verify-TLS back to the legacy columns, then drops both tables. Models
`HealthCheck` / `HealthResult` and `ServiceEntry.checks` are in `models.py`,
with `ServiceEntry.url_check('internal'|'external')`, `.service_checks`,
the convenience properties `internal_check_enabled`, `external_check_enabled`,
`url_check_timeout`, `url_check_verify_tls`, and `ensure_url_checks(entry)`
(called by register create and update, Add, Edit and restore). The legacy
`last_checked_at` is converted from server-local to naive UTC in the
migration. The interim checker is `jobs.run_url_checks_once(app)` (called by
`health_check_loop`), using `jobs.probe_url(url, check, default_timeout)`
(replacing `check_url`); a status below 400 is ok. It writes one
`HealthResult` per check per pass, updates the check's `last_*` and
`consecutive_failures`, and mirrors the status string and a local
timestamp into the legacy `*_status` / `*_update` columns (marked
`# TEMP: removed in v070-05`). The Dashboard, Tiled and Edit templates read
`enabled` and the shared timeout/verify values from the check rows. Backups
export `checks` (config only, via `HealthCheck.to_config()`); the legacy
`*_enabled`, `health_check_timeout` and `health_check_verify_tls` keys are
still written, derived from the rows, so an older STD can restore them.
Restore of a backup with `checks` applies URL rows by kind and replaces
service rows wholesale; a backup without `checks` maps the legacy keys onto
both URL rows. The migration test and the interim loop are in
`tests/test_health_schema.py`.

- **Tables** `health_check` and `health_result` (§5.6), with models
  `HealthCheck` and `HealthResult`, and `ServiceEntry.checks`
  (cascade delete).
- **The migration** creates an `internal_url` and an `external_url`
  check for every entry. It copies enabled, timeout and verify-TLS
  from the entry columns, and seeds `last_*` from the legacy status
  strings (a numeric code under 400 = ok; anything else = failing,
  with the string as the message).
- **New entries get both URL-kind rows:** the register create path, the
  Add page and backup restore all create them.
- **Register:** `internal_health_check_enabled` /
  `external_health_check_enabled` set `enabled` on the matching row.
  Absent means no change, as today.
- **Add/Edit:** the existing toggles plus the timeout and verify-TLS
  fields now read and write the check rows, so no visible change yet.
- **Backups** export each entry's check *configuration* as a list (no
  results). An older backup without `checks` is mapped from the legacy
  columns.
- **Legacy columns are deprecated:** no new code reads them. Until
  §13.6 swaps the templates, the checker (§13.4) mirrored URL-kind
  results into the legacy `*_status` / `*_update` columns so the
  old badges kept working; §13.6 removed that mirror.

### 13.4 Checker engine and history retention [`v070-03-checker-engine`] — Delivered in v0.7.0

- **Replaces `health_check_loop`.**
  - A scheduler thread wakes every 5 s, finds due checks (enabled, entry
    active, URL-kind with a URL present, `last_checked_at + interval <=
    now`) and submits them to a `ThreadPoolExecutor`.
  - Pool size: new setting `health_check_workers`, default 8.
  - Workers do network I/O only and return a result. The scheduler
    thread does every DB write (SQLite single-writer; no session use in
    worker threads). An in-flight set prevents double submission.
- **Intervals**: per-check `interval_seconds` (minimum 30) or the
  existing global `url_healthcheck_interval`. The timeout is per-check
  or the global `health_check_timeout`.
- **Check types**:
  - `http`: covers HTTP and HTTPS, chosen by the URL scheme. A GET that
    follows redirects, with verify-TLS per check. Two modes:
    - **`status`** (default): an HTTP status below 400 = ok. The
      message is the status code, or the exception class and text.
    - **`body`**: reads at most 4 KB of the response.
      - Body (trimmed) equals `OK` (case-insensitive) → ok.
      - Body starts with `Error:` → failing, message = the text after
        the prefix (trimmed, up to 200 chars).
      - Anything else → failing, `Unexpected response: <first 60
        chars>`.
      - Status 400 or above → failing, using the `Error:` text if
        present, else the status.
  - `tcp`: target `host:port`. A connect within the timeout = ok, and
    latency is the connect time.
  - `ping`: ICMP echo via `icmplib` (new pinned dependency), 3 packets,
    ok if any reply. The image runs as root and Docker's default
    capability set includes `NET_RAW`. If a privileged socket fails, it
    retries unprivileged; if both fail, the result is failing with
    `ICMP not permitted`.
- **Results**: each run writes one `health_result` row and updates the
  check's cached `last_*` fields and `consecutive_failures`.
- **History retention** (new settings):
  - `health_raw_hours` (default 24): every sample is kept raw for this
    long.
  - `health_history_days` (default 7): total history.
  - An hourly compaction job (at :05) handles raw rows older than
    `health_raw_hours`:
    - **Failures are kept as individual rows** until
      `health_history_days`.
    - **Successes** are merged into one range row per (check, clock
      hour, unbroken run of successes): `ts` = first sample, `ts_end` =
      last, `samples` = count, average and maximum latency. A failure
      inside an hour splits the range.
  - Rows older than `health_history_days` are deleted. Bound per check:
    about 24h of raw samples plus at most 2 rows per hour for the rest
    of the week, plus failures.
  - **Uptime %** = Σ `samples` where ok ÷ Σ `samples`, over 24 h or 7 d.
- **Check now**: `POST /service/<id>/checks/run` (login and CSRF)
  queues all of that entry's enabled checks for the next scheduler tick.
  The request is held in memory (`jobs.request_run`), not by clearing
  `last_checked_at`, so the last result stays visible until the new one
  lands.

**As built:** probes live in `checker.py` (`probe_http`, `probe_tcp`,
`probe_ping`, `run_probe`; each returns a `ProbeResult(ok, latency_ms,
status_code, message, error_type)` and never raises). The scheduler is
`jobs.HealthScheduler` (`select_due_jobs` builds plain-dict jobs, workers run
`_run_job`, `collect()` and `record_check_result()` do every write on the
`health-check-loop` thread, 5 s tick, per-tick app context). Service-kind
checks with a target are scheduled too, ahead of their UI (§13.5). The URL
rows mirrored into the legacy `*_status` / `*_update` columns until §13.6
(removed there). Settings: `health_check_workers` (8), `health_raw_hours` (24),
`health_history_days` (7). Jobs: `compact_health_results` (hourly at :05) and
`purge_health_results` (hourly at :03). Compaction only touches clock hours
that lie wholly before `health_raw_hours` ago (one commit per check and
hour), a lone sample becomes a range of one (`ts_end = ts`), and purge
treats a range as old once its `ts_end` is. `icmplib==3.0.4` is pinned. No
schema change.

### 13.5 Check configuration UI [`v070-04-check-config-ui`] — Delivered in v0.7.0

- **Edit page "Health checks" section** replaces the two toggles and the
  v0.6.9 "Advanced health check" block:
  - **Internal URL check / External URL check**: enabled, mode (status
    or body), interval, timeout and verify TLS. The target is shown
    read-only as the current URL.
  - **Service checks**: a list with add and remove. Each has a name,
    type (HTTP/HTTPS, TCP, Ping), target, mode (HTTP only), interval,
    timeout, verify TLS (HTTP only) and enabled.
- **Validation**:
  - HTTP target must be an `http(s)://` URL.
  - TCP target must be `host:port` with a port from 1 to 65535.
  - Ping target must be a hostname or IP.
  - Interval must be 30–86400 s; timeout 1–60 s.
- **Add page**: the same section. A manual site usually gets one service
  check.
- **Flash messages on Add and Edit:** validation errors are shown inline
  on these pages; today they only appear later on Settings (closes the
  v0.6.9 QoL item).
- Notifier entries can carry service checks too. They are operator
  data; register never touches `service` rows.
- **As built:** `check_form.py` parses, validates and applies the section
  (shared by Add and Edit); `partials/health_checks_form.html` renders it
  and `static/js/health_checks_form.js` clones a `<template>` row. Fields:
  `uc_<internal|external>_<enabled|mode|interval|timeout|verify>` and, per
  service row, `svc_row` plus `svc_<key>_<id|name|type|target|mode|interval|timeout|verify|enabled>`;
  a hidden `checks_form` marker means "section submitted" (absent leaves
  checks untouched). Every error is flashed (`danger`) and the page
  re-renders with all input kept; nothing is saved. Rows are matched by id;
  saved service checks missing from the post are deleted, results cascade;
  an id belonging to another entry is rejected. A blank service-check name
  defaults to its target; at most 20 service checks per entry. Non-HTTP
  checks store mode `status` and verify on. A changed check or URL clears
  `last_checked_at`. `partials/flash_messages.html` is shared by Settings,
  Add and Edit. The old single timeout / verify-TLS fields are gone.

### 13.6 Health rollup, badges, and filters [`v070-05-rollup-and-filters`] — Delivered in v0.7.0

- **`health.py` is unchanged** (liveness). The rollup lives in a new
  `health_state.py`:
  - `entry_health(entry)` returns the state (§13.1), the counts, and the
    worst message.
  - Loaded with one query per page (checks joined, no N+1).
- **One badge partial** (`partials/health_badge.html`) used by Dashboard,
  Tiled and Compact:
  - Shows a single coloured state dot or pill (up / degraded / down /
    unknown / none), with the failing check names and messages in the
    tooltip.
  - Replaces every template-side parse of the legacy status strings
    (`.isdigit()`, `'Error: SSLError'`).
  - The legacy-column mirror from §13.3 is removed.
- **Filter bar** (all three views; query params handled in
  `view_helpers.py` next to `show_urlless`, kept across refresh):
  - `status` = `all` (default) / `failing` (degraded or down) /
    `healthy` (up) / `unknown` (unknown or none) / `stale` (notifier
    entries that are stale).
  - `source` = `all` / `notifier` / `manual`.
- The filter bar shows **Total / Passing / Failing** count chips (v0.7.1), each a link
  that sets `status` to `all` / `healthy` / `failing`. They count entries
  after `source` and `show_urlless` but ignoring `status`, so each number
  equals what its link shows.

**As built:** `health_state.entry_health(entry)` returns a frozen
`EntryHealth(state, total, failing, failures)` (plus `label` / `tooltip`).
A check counts when it is enabled and has something to probe (a URL check
whose URL is empty is skipped, since the scheduler never runs it). `none` =
nothing counts; `unknown` = none has run; otherwise failing checks among those
that have run decide `down` (all fail), `degraded` (some) or `up` (none).
Checks still waiting for a first run do not hold `up` back. The three view
handlers share `_load_view_entries()`, which `selectinload`s `checks`, so the
page query count is flat in entry count (tested). `partials/health_badge.html`
has three variants (`pill` Dashboard, `icon` Tiled, `compact` dot linking to
`/edit/<id>#health`; the Edit page's checks section carries `id="health"`).
Dashboard gets a Health column; its INT/EXT pills and Tiled's URL icons are
plain links. `view_helpers` adds `normalize_status_filter` /
`normalize_source_filter` (unknown values fall back to `all`) and applies both
before grouping. `stale` is `source == notifier and is_docker_status_stale`.
The filter selects use `view-control`, so the existing JS keeps them in the
URL. The count chips come from `view_helpers.health_counts` (one rollup per
entry, no extra queries; Unknown and Not monitored count in Total only) and
`routes_dashboard._health_count_context`, which builds each link server-side
from `request.args` so all other params persist and marks the active chip with
`aria-current="true"`. The old `shown / total` text is gone. The legacy
mirror and `checker.legacy_status` are gone: nothing reads the deprecated
`*_health_check_status` / `_update` columns except `dbdump.html` and restore;
backups still emit those keys, derived from the check rows. New filter
`time_since_utc` renders the naive-UTC check timestamps.

### 13.7 Health detail and 24h history [`v070-06-health-detail`] — Delivered in v0.7.0

- **Endpoint** `GET /service/<id>/health?range=24h|7d` (login required,
  JSON). For each check it returns the config summary, the current
  state, uptime % for 24 h and 7 d, the most recent failures (up to 20)
  and a bar series:
  - `24h`: 48 half-hour bars.
  - `7d`: 168 hourly bars, each with `ok_samples`, `fail_samples` and
    up to 3 failure messages. A range row that spans bars is split by
    time-proportional sample count.
  - A bar is green when all its samples are ok, red when any failed,
    and grey when there were no samples.
- **Detail panel** (`partials/health_detail.html` plus
  `static/js/health_detail.js`), fetched lazily when opened:
  - One block per check: name/kind, type and target, state, last
    checked, latency, last message, and uptime for 24 h / 7 d.
  - A Gatus-style bar strip with a hover tooltip (time range, ok/fail
    counts, messages), a 24h / 7d toggle, and a list of recent
    failures.
  - A **Check now** button (uses `stdPost`).
- **Where it appears:**
  - **Tiled**: inside the existing tile drawer.
  - **Dashboard**: a new expand row under each entry.
  - **Edit page**: above "Reported by notifier".
  - **Compact** has no drawer; its badge links to the Edit page's
    health section.
- Rendering uses plain divs and CSS (no chart library).

**As built:** `health_history.py` holds the pure functions: `bars(check,
range, now)`, `uptime(check, hours, now)`, `recent_failures(check, limit=20)`
and the payload builders. Buckets are aligned to the clock (half-hour or
hour boundaries, the last bar is the current partial one). A range row is
split across the buckets it overlaps by time-proportional sample count
(largest-remainder rounding, total preserved; portions outside the window
are dropped); a range of one or a raw row lands in a single bucket. Up to 3
distinct failure messages per bar. `GET /service/<id>/health?range=` (login,
404 for missing or soft-deleted; an unknown `range` falls back to `24h`)
returns every *enabled check with a target*: config summary, state
(`up`/`down`/`unknown`), last checked (ISO, `Z`), latency, message, 24 h and
7 d uptime (null with no samples), `failures`, `bars`. The shell is
`partials/health_detail.html`; `static/js/health_detail.js` fetches lazily
(Tiled drawer open, Dashboard row expand; autoloaded on Edit), re-fetches
on the 24h/7d toggle, renders with DOM calls (no innerHTML of server text),
and drives the tooltip and Check now (`stdPost`, then re-fetch every 2 s until every shown check has a result newer than the request's `requested_at`, up to 75 s).
Dashboard gets a leading chevron column and an expand row (group-header
`colspan` is now 13); an open row pauses auto-refresh like an open drawer.
The Edit page panel is a "Health history" block after the form, above
"Reported by notifier".

**Inline uptime strips (v0.7.1).** A "Show uptime" checkbox
in the filter bar (all three views, next to Show URL-less) is remembered in
the `std_show_uptime` cookie (`1`/`0`, `Path=/`, `SameSite=Lax`, one year;
only ever compared to `'1'`). On, each service shows one 24h strip: 48
half-hour bars merged from every check that counts (red if any check failed
in the slot, green if all samples passed, grey with none) plus the 24h uptime
% (Σ ok ÷ Σ samples; the Compact strip omits the %). It sits under the badge
on Dashboard, along the bottom of a Tiled tile, and as a thin line on a
Compact tile; a service with no check that counts shows a muted "—". Bars and
tooltip reuse the detail panel's. Data comes from `GET /health/strips?ids=`
(login; at most 500 ids; unknown or soft-deleted ids are omitted), served by
`health_history.strips()` with a fixed number of queries (one `health_result`
query for all checks, grouped in Python). `static/js/uptime_strip.js` fetches
once per page load while the toggle is on (auto-refresh reloads the page, so
refreshes re-fetch only while on) and never when off. No schema change.

### 13.8 Container check [`v070-07-container-check`] — Delivered in v0.7.0

Every notifier entry carries an automatic **Container** check, so the
notifier's report that a container is running counts as health. This
supersedes the earlier 0.7.0 call that kept Docker state out of the rollup.

- **Kind** `container`, `check_type` `docker`, `target` NULL, name
  "Container". Exactly one per notifier entry, enabled by default; manual
  entries have none. Created on register (new entry), on adoption of a manual
  entry, on restore, by the migration, and by the scheduler's ensure pass.
- **Evaluated by the scheduler thread**, never the pool and never the register
  request. Due on the normal interval (its own `interval_seconds` or
  `url_healthcheck_interval`). Result: ok when `docker_status` is `running`
  (case-insensitive) and the entry is not stale (`last_api_update` within
  `stale_after_minutes`); otherwise failing with `Container <status>`,
  `No update from notifier for <N> min`, or `No update from notifier yet`.
  `status_code` and `latency_ms` are NULL. Results use the same
  `record_check_result` path, so history, compaction, purge, uptime and bars
  need no changes.
- **Immediate transitions:** a register that changes `docker_status` queues
  `jobs.request_run([check id])`, so the change shows within about 5 s.
- **Locked entries** (`is_static`) receive no registers, so the check is
  neither scheduled nor counted while locked (like a disabled check); unlocking
  resumes it. Soft-deleted entries are skipped as before.
- **Rollup:** counts like any check. A Docker entry with no other checks is Up
  when running and fresh and Down when exited or stale; running with a failing
  URL check is Degraded; a disabled container check alone is Not monitored.
  Filters are unchanged (`stale` still means notifier staleness).
- **Configuration:** Edit shows a "Container (Docker state)" row (enabled and
  interval, 30-86400) for notifier entries only. Add and manual entries do not.
- **Detail panel:** renders like other checks (name "Container", no target
  line, last message, bars). The Docker pill and stale icon stay.
- **Backups:** the check's enabled/interval round-trip in `checks`; restoring a
  backup without one creates it for notifier entries.
- **Register contract:** unchanged; `schemas.py` is not touched.

**As built:** `models.py` has `CHECK_KIND_CONTAINER`, `ensure_container_check`,
`evaluate_container(entry, now)` (a pure read) and `check_counts(entry,
check)`, the shared "can run / counts" rule now used by the rollup, the
scheduler, the detail payload and Check now. `jobs.run_container_checks`
runs inside `HealthScheduler.tick` after the pool submission pass.
`select_due_jobs` never returns container checks. `check_form` has
`container_row_from_entry`, `parse_container` (guarded by a hidden `cc_row`
marker so a stale page does not disable the check) and `apply_container`. A
register also queues a run when the container check is currently failing, so
recovery after a stale spell shows at the next tick.

### 13.9 Out of scope for v0.7.0

Parked in FUTURE.md: alerting/notifications on failure;
notifier-defined service checks (register field); DNS and keyword-match check
types; uptime beyond 7 days and a public status page; dropping the deprecated
health columns.

---

## 14. v0.8.0 — Management API (Planned)

> **Status:** planned. Scoped 2026-11-15. Each subsection is one handoff
> prompt (named in brackets, in `prompts/`), run in the order listed.
> Each chunk leaves the app working and the test suite green.

A **minor** release with one theme: everything an operator can do in the UI
can also be done through an authenticated JSON API, so an agent such as
Claude (or a script) can maintain an STD instance. That covers reading every
entry and its health, adding manual sites and web checks, editing fields,
groups, widgets and runtime settings, and triaging failures.

Because it is a minor, `/release-prep 0.8.0` reaches the per-minor CHANGELOG
archive step. The operator chose to keep the full CHANGELOG at 0.7.0; ask
again at prep time.

**Cross-repo:** **no register-contract change.** `POST /api/v1/register`
and its `api_token` are untouched. The notifier keeps its register-only
token and needs no update.

### 14.1 Principles

- **Separate credentials.** The notifier's `api_token` (in `settings.yml`,
  present on every Docker host) stays **register-only**. Management uses
  **admin API keys** created in the UI. A leaked notifier config can never
  read or change the dashboard. The management API rejects `api_token`, and
  register rejects management keys.
- **Key-only auth.** Management endpoints authenticate with
  `Authorization: Bearer <key>` only. They ignore session cookies, so they
  are CSRF-exempt by construction. The existing browser endpoints (UI JSON
  such as `/service/<id>/health`) are unchanged and stay session-only.
- **Same rules as the UI.** One validation path per object.
  - The Add/Edit check validation (`check_form.py`) and entry rules are
    shared with the API, not copied.
  - URL edits through the API take `ui_edit` provenance (operator intent,
    protected from the notifier and synthesizer).
  - Notifier-owned fields are read-only: `docker_status`, `container_id`,
    `stack_name`, image fields, `started_at`, networks, ports, exposure
    observations and the `notifier_reported_*` columns.
  - API entry writes take the register handler's `_UPSERT_LOCK`, so they
    serialize with registers.
- **Strict schemas.** Request bodies are pydantic models with
  `extra="forbid"`, as on register. Unknown fields are a 400 listing the
  bad keys.
- **Secrets are write-only.** API key secrets are shown once at creation.
  The widget `widget_api_key` is never returned; reads return
  `"widget_api_key_set": true|false`.
- **Every write is audited** (§14.6).

### 14.2 API keys [`v080-01-api-keys-and-audit`] — Delivered (unreleased)

- **Model `ApiKey`** (table `api_key`): `id`, `name` (unique, ≤64),
  `prefix` (first 8 chars, for display and lookup), `key_hash`
  (SHA-256 hex of the full key), `scope` (`read` or `write`, where `write`
  includes read), `created_at`, `created_by` (FK `user.id`, nullable,
  indexed), `last_used_at`, `last_used_ip`, `revoked_at`.
- **Key format:** `std_<prefix>_<secret>`. It holds 32+ random bytes from
  `secrets.token_urlsafe`. Because the key is high-entropy, a plain SHA-256
  is sufficient (no KDF). Lookup is by `prefix`, then the hash is compared
  with `hmac.compare_digest`.
- **Settings → API tab** (admin only):
  - **Create key** asks for a name and scope and shows the full key
    **once**, with a copy button.
  - Key list: name, prefix, scope, created, last used (time and IP),
    **Revoke**.
  - The recent audit log is shown here too (§14.6).
- **Decorator `require_api_key(scope)`:**
  - Missing or invalid key → 401 JSON. Revoked → 401. Read key on a write
    endpoint → 403.
  - Sets `g.api_key`.
  - Updates `last_used_at` and IP, throttled to once a minute per key.
  - Log lines show the key's name and prefix, never the secret.
- **Blueprint `routes_mgmt_api.py`** (`/api/v1/...`, CSRF-exempt), with JSON
  error handlers for 400, 401, 403, 404, 405, 409 and 422:
  `{"error": "...", "details": ...}`.

**As built (v080-01):** `api_keys.py` (`generate_key`, `verify`,
`scope_allows`, `create_key`, `revoke_key`), `routes_mgmt_api.py` (blueprint
`mgmt_api`, `require_api_key(scope)`, `audit()`, `json_error()`,
`GET /api/v1/whoami`) and models `ApiKey` / `ApiAudit`.
- The prefix is 8 hex characters (`secrets.token_hex(4)`), so it never
  contains `_`; the secret is `token_urlsafe(32)` and may. A key is parsed
  with `split("_", 2)`.
- A 403 (read key on a write endpoint) still counts as an authenticated
  request: `last_used_at` is touched and a write is audited.
- Blueprint handlers return the JSON error shape for 400, 401, 403, 404, 405,
  409 and 422 raised inside the blueprint, plus pydantic `ValidationError`
  (400, field-level `details`) and unhandled exceptions (500). Routing-level
  404/405 (no matching URL) are not handled by a blueprint and keep Flask's
  default response.
- Settings → API (admin, CSRF): create shows the key on the POST response page
  (`api_key_created.html`, `Cache-Control: no-store`), never via flash or
  session; revoke keeps the row greyed out. Key names are unique including
  revoked keys. The audit list on this tab arrives with v080-04.

### 14.3 Entries, checks and health [`v080-02-entries-checks-health`]

All paths are under `/api/v1`. Every list endpoint takes `limit` (default
200, maximum 1000) and `offset`, and returns `{items, total, limit, offset}`.

| Method + path | Scope | Purpose |
|---|---|---|
| `GET /entries` | read | List, with filters `source`, `status` (`all`/`failing`/`healthy`/`unknown`/`stale`, the same as the UI), `group`, `host`, `q` (substring of name, host, stack, description), `include_deleted`, `deleted_only`. Each item has the entry fields, `health` (state, counts, failures) and `checks` (config plus last result). |
| `GET /entries/<id>` | read | One entry in full, including `notifier` (read-only observed facts) and `widget` (no secret). |
| `POST /entries` | write | Create a **manual** entry: name, host, description, group (name; created if missing), URLs, icon, sort priority, lock, and `checks` (a list of service checks plus URL-check settings). It follows the same duplicate rules as Add, so a duplicate is a 409. |
| `PATCH /entries/<id>` | write | Partial update of operator fields: group, URLs, icon, sort priority, lock, description; also name and host on manual entries only. Notifier-owned fields → 400. |
| `DELETE /entries/<id>` | write | Soft delete. `?permanent=true` hard-deletes, but only an already soft-deleted entry; otherwise 409. |
| `POST /entries/<id>/restore` | write | Restore a soft-deleted entry. |
| `GET /entries/<id>/checks` | read | The entry's checks. |
| `POST /entries/<id>/checks` | write | Add a service check (http/tcp/ping). |
| `PATCH /checks/<id>` | write | Update any check. URL-kind checks: enabled, mode, interval, timeout, verify. Container check: enabled, interval. Service checks: everything. |
| `DELETE /checks/<id>` | write | Delete a **service** check. URL and container checks can't be deleted (409); disable them instead. |
| `POST /entries/<id>/checks/run` | write | Check now (uses `jobs.request_run`). Returns `requested_at`. |
| `GET /entries/<id>/health?range=24h\|7d` | read | The same payload as the UI detail panel. |
| `GET /health/summary` | read | Counts (total, passing, failing, unknown, stale) plus every failing entry with its failing checks and messages, so an agent can triage in one call. |

- **`check_form.py` validation is refactored** into functions that take
  plain dicts, used by both the form parser and the API, so there is one
  rule set. Form behaviour stays the same; existing tests prove it.
- **Status codes:** a create returns 201 with the object. A validation
  failure returns 400 with every problem listed, per field.

### 14.4 Groups, widgets and runtime settings [`v080-03-groups-widgets-settings`]

| Method + path | Scope | Purpose |
|---|---|---|
| `GET /groups` | read | Groups with priority, icon and active entry count. |
| `POST /groups` | write | Create a group (unique name → 409 on duplicate). |
| `PATCH /groups/<id>` | write | Rename, re-prioritise, set the icon. |
| `DELETE /groups/<id>` | write | Delete. Its entries become ungrouped (same as the UI). |
| `GET /widgets/types` | read | The widget plugins under `widgets/` with their `available_fields`. |
| `GET /widgets` | read | Widget instances: type, URL, fields, `widget_api_key_set`, attached entry ids, `detached`. |
| `PUT /entries/<id>/widget` | write | Attach or configure the entry's widget (type, URL, fields, optional API key). Validates the type and fields against the plugin. |
| `DELETE /entries/<id>/widget` | write | Remove it from the entry. `?delete=true` deletes the widget and its values; otherwise it is detached. |
| `DELETE /widgets/<id>` | write | Delete a detached widget. |
| `GET /settings/exposure` | read | Per-interpreter direction mappings, per-host overrides, and discovered layers and hosts (`settings_store`). |
| `PUT /settings/exposure` | write | Replace them, with the same validation as Settings → Exposure. |
| `GET /config` | read | Effective `settings.yml`/env values, read-only, with **secrets masked** (`api_token`, `secret_key`, widget keys) plus the app version. These are not editable through the API (they are loaded once at startup). |

Users and passwords are **not** exposed through the API (out of scope).

### 14.5 OpenAPI spec and docs [`v080-04-openapi-and-docs`]

- `GET /api/v1/openapi.json` (no auth; it describes shapes, not data) is an
  OpenAPI 3.1 document. It is generated from the pydantic request and
  response models plus a route table, not hand-written, and a test fails if
  a management route is missing from it.
- **README "Management API"**: creating a key, the auth header, the endpoint
  table, curl examples (list failing services, add a manual site with an
  HTTP body check, disable a check), and a "Managing STD with Claude"
  section.

### 14.6 Write audit log [in `v080-01`; Settings view in `v080-04`] — Delivered (unreleased; model, hook, retention)

- **Model `ApiAudit`** (table `api_audit`): `id`, `ts` (UTC), `api_key_id`
  (FK, indexed, `ON DELETE SET NULL`), `key_name` (a snapshot), `method`,
  `path`, `object_type`, `object_id`, `status_code`, `changes` (JSON
  `{field: [old, new]}`, with secrets replaced by `"***"`).
- **One row per write request** (POST, PATCH, PUT, DELETE), including
  failures (4xx). Reads are not logged.
- **Retention:** new setting `api_audit_retention_days` (default 90), with a
  daily purge job.
- **Settings → API** shows the most recent 200 rows, filterable by key.

**As built (v080-01):** model, retention and the hook are in. The hook is
`routes_mgmt_api.audit_response`, registered with `mgmt_bp.after_request`; it
writes one row for each POST/PATCH/PUT/DELETE that carried a valid key
(including 4xx and 403). Endpoints describe the change with
`audit(object_type, object_id, {field: [old, new]})`, which masks secret
fields (`widget_api_key`, `api_token`, `secret_key`, `key_hash`, `api_key`,
or any name containing `secret`, `password` or `token`) as `"***"` for both
old and new values before they reach the database. Unauthenticated requests
are only logged. `jobs.purge_api_audit` runs daily at 00:35. The Settings
view of the log is not built yet.

### 14.7 MCP server [`v080-05-mcp-server`]

- A small **stdio MCP server** at `mcp/std_mcp.py` (its own
  `mcp/requirements.txt`, using the official `mcp` Python SDK). It is **not
  in the Docker image**; it runs on the operator's machine, next to Claude
  Code.
- It is configured with `STD_URL` and `STD_API_KEY` and talks only to the
  REST API. It holds no DB access and duplicates no business logic.
- **Tools**, as thin wrappers with typed inputs: `list_entries`,
  `get_entry`, `health_summary`, `get_health_history`,
  `create_manual_entry`, `update_entry`, `delete_entry`, `restore_entry`,
  `add_check`, `update_check`, `delete_check`, `run_checks`,
  `list_groups`, `upsert_group`, `list_widgets`, `set_widget`,
  `get_exposure_settings`, `set_exposure_settings`, `get_config`.
- A **read-only key exposes only the read tools**; it probes the key's scope
  at startup via `GET /api/v1/whoami`, which is added in v080-01.
- **README:** a `claude mcp add` example.
- **Tests:** each tool runs against a fake HTTP layer, with no network.

### 14.8 Out of scope for v0.8.0

- Per-host notifier tokens (§17), users and passwords through the API, and
  rate limiting.
- An HTTP-hosted MCP endpoint inside STD.
- Editing `settings.yml` values through the API.
- Webhooks or outbound alerts (FUTURE.md "Monitoring follow-ups").

---

## 15. Versioning, Branches, and Releases

- `main` is the default branch and the source of truth for releases.
- All work happens on `dev`. PR `dev` → `main` when ready to release.
- Branch protection: require PR + green required checks, block
  force-push, block deletion. Required checks: `build` (image build,
  `publish.yml`), CodeQL, and the `CI` workflow jobs `Lint` (ruff,
  `ruff.toml`), `Config validation` (YAML/JSON parse), `Migration check`
  (`alembic upgrade head` on an empty DB, exactly one head),
  `Compose validation` (`docker compose config --quiet`), and `Test`
  (pytest, `tests/`; added in v0.6.9 — pending operator action to mark it
  required in branch protection). `CI` triggers on push to `dev`/`main`
  only.
- Registry retention: `.github/workflows/retention.yml` prunes GHCR
  versions weekly and after each publish — keeps the 30 most recent
  `sha-*` and 15 most recent semver versions, never deletes `latest`,
  `dev`, major tags, or untagged versions. Docker Hub has no retention
  (frozen at v0.6.7).
- Images are published by `.github/workflows/publish.yml` to
  `ghcr.io/crzykidd/service-tracker-dashboard`, the only registry.
  Docker Hub (`crzykidd/service-tracker-dashboard`) is frozen at v0.6.7
  and no longer published; there is no in-app registry banner.
- Image tags:
  - push to `dev` → `:dev`, `:sha-<short>`
  - push to `main` → `:latest`, `:sha-<short>`
  - GitHub Release published → `:latest`, `:<semver>`, `:<major>`
- The version is the single bare-semver line in the repo-root `VERSION`
  file. The Dockerfile copies it and writes `version=` into
  `/app/version.txt` (there is no `APP_VERSION` build arg), so `:dev`,
  `:latest`, and release images all report the real version. `app.py`
  falls back to `VERSION` for local runs without an image.
- Releases are cut with `/release-prep <version>` (on `dev`: bump
  `VERSION`, roll CHANGELOG, sync README/PRD/CLAUDE.md, open the PR) then,
  after merge and green `main` CI, `/release-cut <version>` (tag
  `v<version>` on `main` and publish the GitHub Release). `publish.yml`
  fails a `release` build whose tag (minus `v`) differs from `VERSION`.

---

## 16. Cross-Repo Coordination

This project is paired with
[docker-api-notifier](https://github.com/crzykidd/docker-api-notifier).

### 16.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start
here; the notifier follows.

Because STD's `RegisterPayload` uses `extra="forbid"`, unknown keys
are rejected with HTTP 400 (not silently ignored). The
consumer-leads-producer-follows ordering rule is therefore strict:
any new field the notifier intends to send must be added to STD's
schema and shipped first. The notifier may lag arbitrarily; it must
not lead.

### 16.2 Release history

1. STD v0.5.0 shipped `/api/v1/register` (canonical keys) alongside
   the `/api/register` compat shim that translated legacy keys.
2. Notifier v0.3.0 switched to canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 removed `/api/register` and all legacy-key handling.
   Operators on notifier v0.3.0+ are unaffected.
4. Notifier v0.4.0 is the paired release for everything new in STD
   v0.6.0: it populates the `networks` / `exposed_ports` /
   `published_ports` capture fields **and** introduces the YAML
   interpreter mechanism that emits `exposure_observations`. STD's
   synthesizer reads those observations and writes synthesized URLs
   into `internalurl` / `externalurl`. Pre-v0.4.0 notifiers continue
   to register successfully — they just don't send the new fields,
   so the capture columns stay NULL and STD treats the missing
   `exposure_observations` as "no update" (existing exposure rows
   are preserved). (A v0.3.2 was developed for the capture fields
   but was never cut as a release tag — it shipped inside v0.4.0
   alongside the interpreter mechanism. Do not present v0.3.2 as a
   shipped boundary; the only notifier release boundaries that
   exist on this axis are v0.3.0 and v0.4.0.)

---

## 17. Open Questions

- **Widget retention granularity.** A flat retention window
  (`widget_value_retention_days`, made actually configurable in §12.3)
  may be too much for some widgets and not enough for others. A
  per-widget policy via the widget's `settings.json` is unscheduled;
  revisit once §12.3 ships and the global knob works.
- **API tokens per-source.** (Admin/management keys are planned in §14;
  this item is now only about the notifier's register token.) A single shared token works for a homelab
  but doesn't let you revoke a single notifier host. Per-host tokens +
  last-seen tracking? Unscheduled; §12.3 only closes the
  unset-token hole.
- ~~**Health check timeouts.**~~ Resolved in §12.8 (per-service timeout
  and TLS-verify override).
- **Read-replica for dashboard reads.** WAL handles concurrent reads
  fine at this scale, but if widget growth pushes DB size up, worth
  measuring. No evidence it's needed.
