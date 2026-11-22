# Service Tracker Dashboard (STD) — Claude Code Instructions

## Always — Definition of Done

No change is complete until its documentation is updated **in the same
commit as the code**. This is not optional and not deferrable:

1. **CHANGELOG.md — every operator-visible change.** Add an entry under
   `[Unreleased]` describing what changed for the operator. A code
   change with no CHANGELOG entry is an incomplete change. Tooling-only
   and docs-only changes (agent guidance, `.claude/` config, CI, doc
   refreshes) have no operator effect: record them in `docs/HISTORY.md`
   or `docs/decisions.md` instead (see `docs/decisions.md`).
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

> **Known debt:** this repo's docs drifted from shipped reality before.
> The 2026-05-23 reconciliation audited `docs/` against shipped state
> (PRD revisions 0.9 and 0.10), and the 2026-11-15 refresh brought
> CLAUDE.md, the PRD, and the README current through v0.6.8. The
> notifier repo's docs audit is not recorded here and may still be
> pending. Where docs and code disagree, trust the code and CHANGELOG
> over the PRD, and flag the contradiction rather than propagating it.

## Standards

This project adopts crzynet engineering standards from `homelab-configs`.
**Read [`standards.md`](standards.md) at session start** whenever the work
could touch anything a standard governs (branching, commits, CI, releases,
handoff prompts). It lists each adopted standard with its pinned version.

<!--
Source: standards/handoff-prompt-workflow @ v2.0.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (the plan→decide→execute→document principle, model selection,
TEMPLATE, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/handoff-prompt-workflow/README.md
-->

## Handoff prompts (operational rules)

This project adopts the `handoff-prompt-workflow` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts an agent must honor by
default:

- **Edit-size threshold — decide by how much you'll change:**
  - A genuinely small change — roughly **one or two files and a few lines** (a typo, one
    config value, a one-line fix) — do it **in-session**, no prompt.
  - **Anything bigger requires a handoff prompt** — more than ~2 files, a multi-step
    change, a new feature, or any edit large enough that a fresh context would run it
    more cleanly. **When in doubt, write the prompt.**
- **A handoff prompt is a file in `prompts/`** — one per task, from `prompts/TEMPLATE.md`,
  with frontmatter (`name`, `status`, `created`, `model`, `completed`, `result`). Set
  `model:` from the task type: **Opus** for research/planning, **Sonnet** for coding;
  mixed defaults to Opus.
- **Execute the prompt by spawning a subagent — don't hand the user a command.** Spawn an
  agent on the prompt's `model:`, let it run the prompt end-to-end, and **report the
  outcome back**. The agent gets a fresh context; you stay in the loop.
  - **Manual fallback only on explicit request.** If the user says e.g. "use manual
    prompts for this," give them
    `claude --model <model> "Read prompts/<file>.md and execute it as your task."`
    instead of spawning.
- **Check the working tree before editing.** Run `git status --porcelain`, cross-reference
  the files the plan touches; if any have uncommitted changes, list them and ask before
  touching. Surface unrelated dirty files once; they don't block.
- **The prompt self-updates and moves when done.** The executing agent sets its
  frontmatter (`status`/`completed`/`result`) and `git mv`s the file into `prompts/done/`
  (success) or `prompts/failed/` (failure).
- **One commit at the end; the prompt bundles in.** The prompt file is **not** committed
  up front — it lands in the single end commit alongside the work and the prompt move.
  Propose ONE commit (files list + one-line message), ask `y/n`, stage only those specific
  paths. **Never `git add -A`, never auto-commit, never push.** A spawned agent prepares
  the tree and reports the proposed commit back; the orchestrating session surfaces the
  `y/n`.
- **Record non-obvious decisions** (approach changes, rejected alternatives, workarounds)
  in `docs/decisions.md`, newest at top.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/code-checkin-and-pr @ v1.2.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (publishing matrix, retention, CI check definitions) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md
-->

## Code check-in (operational rules)

This project adopts the `code-checkin-and-pr` standard. The full why-and-how lives at
the source above; the rules below are the per-session do/don'ts a coding agent must
honor by default:

- **Never push directly to `main`.** `main` is protected. All changes land via a pull
  request from `dev` → `main`, and only when every required check is green.
- **Day-to-day work happens on `dev`** (or a short-lived branch off `dev`). Push to
  `dev` freely.
- **Commit message prefixes are required** — Conventional-Commits style:
  - `feat:` — new user-facing feature
  - `fix:` — bug fix
  - `chore:` — config, tooling, dependencies, maintenance
  - `docs:` — documentation-only changes
- **Do not add `Co-authored-by:` trailers** unless the user explicitly asks.
- **Doc updates ship in the same commit as the code they describe** — never as a
  follow-up commit.
- **Never bypass hooks** (no `--no-verify`, `--no-gpg-sign`, etc.) unless the user
  explicitly asks. If a hook fails, fix the underlying issue.
- **Stable releases are tagged from `main` only.** Don't tag from `dev`.

If you're unsure whether an action would violate one of the above, stop and ask before
acting.

<!--
Source: standards/release-prep-and-cut @ v1.1.0 (crzynet/homelab-configs).
Paste the section below verbatim into the adopting project's CLAUDE.md.
The full standard (two-phase prep/cut workflow, archive trigger, validation
steps, adoption checklist) lives at:
https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md
-->

## Release process (operational rules)

This project adopts the `release-prep-and-cut` standard. The full why-and-how
lives at the source above; the rules below are the per-session do/don'ts a
coding agent must honor by default:

- **The version is stored BARE in the source-of-truth file** — no `v` prefix
  anywhere in code. The `v` prefix is added in exactly one place: the git tag
  and matching GitHub release name. Don't add it to README badges, CHANGELOG
  headers, in-code image tags, or anywhere else.
- **`CHANGELOG.md` is the single source of truth for release notes.** The PR
  description (set by `/release-prep`) and the GitHub release body (set by
  `/release-cut`) reuse the **same section verbatim**. Never author release
  notes twice.
- **One commit per release prep.** Version bump + changelog roll + every doc
  sync ship in a single `chore(release): prepare v<version>` commit. No
  `Co-authored-by:` trailers.
- **Never re-tag.** If `v<version>` already exists as a local tag, a remote
  tag, or a GitHub release, STOP. Never delete-and-recreate; never `--force`.
  Pick the next version instead.
- **`/release-cut` only after the PR has merged and CI is green.** The
  publish-to-`main` workflow must have already pushed `:latest` images to the
  registry before `/release-cut` runs. If you cannot confirm both — STOP and
  tell the user to wait.
- **The release tag is the only thing the cut command writes to `main`.** Both
  the prep commit and any follow-up docs commit land on `dev` and reach `main`
  only via PR. Never push directly to `main` as part of a release.

If you're unsure whether an action would violate one of the above, stop and
ask before acting.

## Commit style

The prefixes (`feat:`, `fix:`, `chore:`, `docs:`) and the no-`Co-authored-by`
rule come from the `code-checkin-and-pr` snippet above. Project extension:
`refactor:` for non-behavior-changing internal cleanup. A release prep uses
`chore(release): prepare v<version>`.

## Stack

- Python 3.11
- Flask, Flask-SQLAlchemy, Flask-Login
- SQLAlchemy + Alembic (migrations)
- APScheduler (background jobs)
- gunicorn (production server; exactly ONE worker, see `gunicorn.conf.py`)
- pydantic v2 (request validation; introduced in v0.5.0)
- SQLite (WAL mode)
- Jinja templates
- Container: single-image Docker
  - `Dockerfile` — production image
  - `docker-compose.yml` — local dev compose (builds from source, mounts
    the repo); the deployment example is in `README.md` → Docker Compose Setup

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
- Parked ideas (not built, not in the PRD) at `docs/FUTURE.md`.
- Operator reference pages linked from the README: `docs/register-api.md`,
  `docs/inventory-streams.md`, `docs/mqtt-home-assistant.md`.
- Decision log (non-obvious calls, rejected alternatives) at
  `docs/decisions.md`, newest at top.
- Adopted engineering standards and their pinned versions at `standards.md`.
- Handoff prompts (live queue) in `prompts/`; finished ones in
  `prompts/done/` / `prompts/failed/`. New prompts start from
  `prompts/TEMPLATE.md`.
- `CHANGELOG.md` at the root — operator-facing release notes (see
  Changelog Process).
- `README.md` at the root — keep it current with what has been built.
- Commit doc updates in the same commit as the code changes they describe.

## Build Status

Current shipped release: **v0.12.0** (latest tag on `main`).
In flight: nothing scoped (the notifier 0.5.0 `image_info` sender is on hold in its own repo).

> Keep this to the two lines above; CHANGELOG and git tags are the record
> of what shipped. Update them on each release / when work starts on `dev`.

## CI, Registry, and Releases

Branching, PR flow, and the release rules are in the snippets above; the
project-specific facts are:

- **Required checks on `main`:** `build` (image build, `publish.yml`),
  `Lint`, `Test`, `Config validation`, `Migration check`,
  `Compose validation`, and CodeQL. `CI` (`.github/workflows/ci.yml`) runs
  on push to `dev`/`main` only. The `Test` job runs the pytest suite in
  `tests/` (`pip install -r requirements-dev.txt && pytest -q`).
- **GHCR is the only registry** (`ghcr.io/crzykidd/service-tracker-dashboard`,
  via `.github/workflows/publish.yml`). Docker Hub is frozen at v0.6.7.
  Push to `dev` builds `:dev` and `:sha-<short>`; push to `main` builds
  `:latest` and `:sha-<short>`; a published release builds `:latest`,
  `:X.Y.Z`, and `:X`. `retention.yml` prunes old GHCR versions.
- **The version lives in the bare-semver `VERSION` file** at the repo root;
  the Dockerfile writes `/app/version.txt` from it. `publish.yml` fails a
  release whose tag (minus `v`) != `VERSION`.
- **To ship:** `/release-prep <version>` on `dev` (bumps `VERSION`, rolls
  CHANGELOG, syncs docs, opens the PR) → human merges the PR and waits for
  CI and the `:latest` build → `/release-cut <version>` (tags `v<version>`,
  publishes the release). Commands live in `.claude/commands/`.

## Changelog Process

- `CHANGELOG.md` lives at repo root; Keep a Changelog format.
- Add entries to `[Unreleased]` as features are built.
- User-facing language only — describe what changed for the operator.
  Tooling-only changes stay out (see Always, item 1).
- Categories: Added, Changed, Fixed, Security, Deprecated, Removed.
- On release: `/release-prep` moves `[Unreleased]` to a new version section
  dated today (`## [X.Y.Z] — YYYY-MM-DD`, em dash; the What's New popup parses it).
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
  uses `extra="forbid"` — unknown keys are rejected with HTTP 400, not
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

## Inventory Stream Ingest Rules (v0.10.0+)

`PUT /api/v1/streams/<stream_id>/snapshot` is the second wire contract STD owns
(PRD §18.5; sidecars such as `std-source-technitium` produce it). Same ordering
rule as register: STD ships a schema change before any sidecar sends it.

- **STD owns the contract.** `StreamSnapshotPut` / `StreamSnapshotItem` in
  `mgmt_schemas.py` use `extra="forbid"` at every level; unknown keys are a 400.
  Don't change wire shapes, status codes or field names without a new
  `API_REVISION` row and a PRD §18.5 update.
- **Core fields stay optional when added.** An older sidecar must keep working
  against a newer STD, so a new core field is never required.
- **`attributes` are uninterpreted.** Shown in STD, never acted on. A sidecar
  adds facts there without an STD release; don't read them in logic.
- **A snapshot is applied whole or not at all** (one transaction under
  `streams._LOCK`) and is full, not a delta: absent means `inventory_missing`,
  never delete. STD makes no outbound calls while applying.
- **`ingest` keys open only the two ingest routes**, bound to the key that
  created the stream. `scope_allows("ingest", "read" | "write")` must stay false.
- **Stream entries (`source = stream`) are never touched by register adoption
  or the restore clash checks.** They are unique by `(stream_id, stream_key)`.
  `find_duplicate` does see them on purpose: adding a host-less manual entry
  with a stream entry's name is rejected as a duplicate (one device, one entry).
- **Snapshot PUTs are not audited**; operator status changes, cleanups,
  unblocks and link answers are.

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
  The staged-restore swap (`restore_swap.py`) follows this too: it keeps the current
  database with `Connection.backup()`, never a file copy, and a failed swap never blocks startup.
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
- **Any additive `/api/v1` change bumps `API_REVISION`** in `api_version.py`
  plus a row in the PRD §18.1 table. Breaking changes need `/api/v2`.
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

## Module Layout

```
app.py              ← thin Flask app factory; wires extensions, blueprints, jobs
extensions.py       ← SQLAlchemy, login manager, scheduler instances
models.py           ← SQLAlchemy models (ServiceEntry, ServiceExposure, Setting, ApiKey, ApiAudit,
                      NotificationChannel, ...)
schemas.py          ← pydantic request/response schemas
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /add, /edit/<id>,
                      /settings, /settings/exposure
routes_api.py       ← /api/v1/register
routes_mgmt_api.py  ← management API blueprint (/api/v1, admin API key only, CSRF-exempt):
                      require_api_key(scope), audit() + after_request audit hook, JSON errors;
                      entries, checks, health, groups, widgets, settings, config, openapi.json
mgmt_openapi.py     ← management API route registry (OPERATIONS) + OpenAPI 3.1 generator;
                      add every new management route here (tests enforce it)
api_version.py      ← API_REVISION, revision history, FEATURES; headers + GET /api/v1/meta use it
api_keys.py         ← admin API key generate/verify/scope check (std_<prefix>_<secret>, SHA-256)
mgmt_schemas.py     ← management API pydantic requests (extra=forbid) + response TypedDicts
mgmt_serializers.py ← model -> response-dict functions for the management API
mcp/                ← stdio MCP server (std_mcp.py), HTTP client of the management API only;
                      own requirements.in/.txt + README; NOT in the Docker image (.dockerignore);
                      no __init__.py (a package named `mcp` would shadow the SDK)
notify.py           ← notification channels: registry, CRUD helpers, bounded-queue publisher
                      thread, non-blocking `enqueue(event)`; never block producers on the broker
notify_state.py     ← retained state publishing (PRD 17.3): topic/payload builders, change events,
                      `full_sync()` reconcile, commit listener that requests a sync
notify_ha.py        ← Home Assistant discovery config builders (PRD 17.4); reconciled by
                      `notify_state.full_sync()`, never published from anywhere else
notify_purge.py     ← channel/entry purge of retained topics + HA devices (PRD 17.5); runs on the
                      publisher thread via `Publisher.call()`, never on a request thread
notify_mqtt.py      ← MQTT channel type (paho 2.x threaded, LWT/availability, test message);
                      the password (`NotificationChannel.secret`) is write-only everywhere
streams.py          ← inventory streams (PRD 18): ingest value rules (`normalize_mac`), `plan()` /
                      `apply()` engine under a module lock, lifecycle, blocks, link offers; plain
                      functions raising `StreamError`, shared by the management API and the UI
export_format.py    ← export format v1 (PRD 20.2): pydantic models (lenient on read), `build_export()`
                      applying the field ownership table, `dump(doc, yaml|json)`; never a secret;
                      `from_legacy()` reads the old entry list (format 0)
importer.py         ← import engine (PRD 20.3-20.4): `parse` (v1 + legacy, record validation),
                      pure `plan()` (matcher, per-field missing/differs), `fingerprint`, `apply()`
                      (takes `routes_api._UPSERT_LOCK` then `streams._LOCK`, re-plans, one
                      transaction; no secret is ever written), and the `import-staging/` store
                      (it also keeps the preview state, `plan.digests`: the UI hashes the submitted
                      selection with `fingerprint_from_digests`)
restore_staging.py  ← staged database restore, app side (PRD 20.5): validate a snapshot, stage it as
                      `<CONFIG_DIR>/restore/pending.sqlite3`; routes in `routes_restore.py`
restore_swap.py     ← the swap at container start: STDLIB ONLY, no app import; run by
                      `entrypoint.sh` before `alembic upgrade head`; must always exit 0
routes_import.py    ← Settings import routes on `dashboard_bp` (upload, preview, stream mapping,
                      apply, cancel); templates/settings_import.html +
                      partials/settings/import_rows.html, static/js/settings/import.js; the
                      management API's `/import/plan` and `/import/apply` live in routes_mgmt_api.py
backups.py          ← backup settings (env > UI > settings.yml > default), snapshot/export runs,
                      per-kind retention, file list + confined `resolve_file`; run functions record
                      `backup_last_runs`
image_update_ui.py  ← read-only view helpers for the image update badge, details line and Check now
                      (Jinja globals `image_update_info`, `image_updates_enabled`); reads stored state only
widget_rules.py     ← widget plugin discovery + validation for the management API
entry_rules.py      ← entry-level rules shared by /add, /edit and the management API
check_form.py       ← health-check form parsing + dict-based validators shared with the API
routes_widgets.py   ← widget endpoints
routes_auth.py      ← /login, /logout, user mgmt
jobs.py             ← concurrent health scheduler, widget refresh, backup, retention/compaction, API audit purge
checker.py          ← health-check probes (http/tcp/ping/dns); pure network, no DB
health.py           ← /healthz (liveness; /readyz not implemented)
health_state.py     ← per-entry health rollup (up/degraded/down/unknown/none) for the badges + status filter
health_history.py   ← bars/uptime/recent failures over health_result for the detail panel (/service/<id>/health)
settings_loader.py  ← file/ENV settings; loaded once at startup
settings_store.py   ← DB-stored runtime settings (per-interpreter directions, update check)
settings_sections.py ← Settings section registry (groups, slugs, labels, legacy `?section=` aliases,
                      `resolve()`); pure data, the sidebar and the routes both read it
version_check.py    ← build channel + display strings; cached GitHub update check (page-load driven)
synthesizer.py      ← exposure → internalurl/externalurl translation + provenance
image_utils.py      ← icon fetch + cache; `resolve_image_metadata` (image string -> registry/owner/name/tag/ref)
image_ref.py        ← pure stdlib image reference parser (`parse()`); the one place an image string is split;
                      feeds `resolve_image_metadata`, `image_repo.py` and `service_entry.image_ref`
image_repo.py       ← image repository link: pure `image_repo_url()` derivation (Docker Hub, GHCR, Quay,
                      lscr.io; None for anything else) + the `image_repo_url` override rule
registry_client.py  ← OCI distribution v2 client for the image update check (PRD 24): anonymous Bearer
                      flow, HEAD manifests with the four Accept types, tag lists, 429 pause; no DB;
                      errors are short fixed messages, never raw exception text
image_tags.py       ← pure tag model, digest model and `evaluate()` (the state of one entry)
image_update.py     ← the update provider seam (`PROVIDERS`; `registry` is the built-in one), settings
                      (OFF by default, env `STD_IMAGE_UPDATE_ENABLED`), the run engine (`_RUN_LOCK`,
                      dedupe, backoff), Check now throttles, register-time recompute, retention;
                      registry I/O never inside a DB transaction or `routes_api._UPSERT_LOCK`
view_helpers.py     ← grouping/sorting for dashboard views
templates/          ← Jinja templates; templates/partials/settings/ = one partial per Settings
                      section + _macros.html (see PRD §19)
static/             ← static assets (css/, js/, icons/); static/js/settings/ = Settings scripts
                      (nav, ui, per-section), static/js/flash.js = toasts and banners
widgets/            ← per-widget plugin dirs
alembic/            ← migrations (alembic.ini at root)
scripts/            ← manual helper scripts (test_widget.py; not a test suite)
tests/              ← pytest suite (conftest.py sets STD_CONFIG_DIR before importing app)
requirements-dev.txt ← pytest + runtime deps; CI/dev only, not in the image
VERSION             ← bare-semver version source of truth
ruff.toml           ← lint config for CI (E, W, F, I, B; E501 ignored)
Dockerfile, entrypoint.sh, docker-compose.yml
gunicorn.conf.py    ← gunicorn config; workers MUST stay 1; post_worker_init runs startup
requirements.in     ← direct deps; edit this, then `uv pip compile` (see README)
requirements.txt    ← fully pinned, generated from requirements.in
requirements-dev.txt ← pinned pytest + -r requirements.txt; CI/dev only
tests/              ← pytest suite
settings.example.yml, .env.example
standards.md        ← adopted standards + pinned versions
.github/workflows/  ← ci.yml, publish.yml, retention.yml
.claude/commands/   ← release-prep.md, release-cut.md
prompts/            ← handoff prompts (TEMPLATE.md, done/, failed/)
docs/               ← PRD.md, HISTORY.md, FUTURE.md, decisions.md, screenshots/
```
