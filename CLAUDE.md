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
Source: standards/release-prep-and-cut @ v1.0.0 (crzynet/homelab-configs).
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

- `feat:` new feature
- `chore:` config, tooling, maintenance
- `fix:` bug fix
- `docs:` documentation only changes
- `refactor:` non-behavior-changing internal cleanup (project extension to
  the `code-checkin-and-pr` standard's prefix set)

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
- Decision log (non-obvious calls, rejected alternatives) at
  `docs/decisions.md`, newest at top.
- Handoff prompts (live queue) in `prompts/`; finished ones in
  `prompts/done/` / `prompts/failed/`. New prompts start from
  `prompts/TEMPLATE.md`.
- `README.md` at the root — keep it current with what has been built.
- Commit doc updates in the same commit as the code changes they describe.

## Build Status

Current shipped release: **v0.6.7** (latest tag on `main`; v0.6.5 was
also released but its tag is the typo'd bare `0.6.5` — see the audit
finding in this commit's history).
In flight: cleanup release on `dev` — vexp removal, standards adoption,
Docker Hub removal (`[Unreleased]` has entries).

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
  - Cut the release with `/release-cut <version>` (see Release Process).
- Branch protection on `main` requires a PR plus green required checks
  (`build`, `Lint`, `Config validation`, `Migration check`,
  `Compose validation`, CodeQL), and blocks force-push and deletion.
  `CI` (`.github/workflows/ci.yml`) runs on push to `dev`/`main` only.
  The `Test` check is exempt until a test suite exists (see `standards.md`).

## Release Process

- Images publish to GHCR (`ghcr.io/crzykidd/service-tracker-dashboard`)
  via `.github/workflows/publish.yml`. Through v0.6.7 the workflow also
  pushes a Docker Hub image built with `REGISTRY_NOTICE=dockerhub` (shows
  the "moved to GHCR" banner). After v0.6.7, remove the Docker Hub steps,
  the build arg, the banner code, and the `DOCKERHUB_*` secrets.
- Push to `dev` — GitHub Actions builds and pushes `:dev` and
  `:sha-<short>` images.
- Push to `main` (via PR from `dev`) — GitHub Actions builds and pushes
  `:latest` and `:sha-<short>` images.
- The version lives in the bare-semver `VERSION` file at the repo root; the
  Dockerfile writes `/app/version.txt` from it, so every image reports it.
- To ship: `/release-prep <version>` on `dev` (bumps `VERSION`, rolls
  CHANGELOG, syncs docs, opens the PR) → human merges the PR and waits for
  CI and the `:latest` build → `/release-cut <version>` (tags `v<version>`,
  publishes the release; GitHub Actions then builds `:latest`, `:X.Y.Z`,
  and `:X`). `publish.yml` fails a release whose tag != `VERSION`.

## Changelog Process

- `CHANGELOG.md` lives at repo root.
- Follow Keep a Changelog format (keepachangelog.com).
- Add entries to `[Unreleased]` section as features are built.
- User-facing language only — describe what changed for the operator.
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
