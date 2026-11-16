---
name: v070-07-container-check
status: completed         # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15    # filled when the work is done
result: Container check (docker state) per notifier entry, migration c1d7a3e5f2b8, scheduler-thread eval, Edit row, tests and docs
---

# Task: Docker container state as an automatic health check

Make every notifier (Docker) entry carry an automatic **Container** check, so
the notifier's report that a container is running counts as health. Today an
entry with no URL or service checks shows "Not monitored" even while the
notifier reports it running. The user chose this over a rollup-only fallback
(2026-11-15). This supersedes the v0.7.0 design call that kept Docker state
out of the health rollup.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` §13 in full (v0.7.0, delivered on `dev`, unreleased) and §5.6.
- `docs/decisions.md`: the v0.7.0 entries (the design-calls entry says
  "Docker state is not a check"; you are reversing that).
- `docs/FUTURE.md` "Monitoring follow-ups": the "Docker state as a check"
  bullet moves into the PRD with this work.
- Code: `models.py` (`HealthCheck`, kind constants, `ensure_url_checks`,
  `is_docker_status_stale`, `to_dict`), `jobs.py` (`select_due_jobs`,
  `HealthScheduler`, `record_check_result`, `request_run`), `routes_api.py`
  (`upsert_service`, adoption), `health_state.py`, `health_history.py`,
  `check_form.py`, `templates/partials/health_checks_form.html`,
  `static/js/health_detail.js`, backup/restore in `routes_dashboard.py`.
- Tests: `tests/test_health_schema.py` (`_SyncExecutor`, migration-test
  subprocess pattern), `tests/test_rollup_filters.py`, `tests/test_checker.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## Design (decided; implement as written)

- **New check kind `container`** (`CHECK_KIND_CONTAINER`), `check_type`
  `docker`, `target` NULL. Exactly **one per notifier entry**; manual entries
  have none. Add `ensure_container_check(entry)` (or extend the ensure helper)
  and call it wherever URL rows are ensured: register create, adoption (manual
  → notifier), restore, and the scheduler's ensure pass. Enabled by default.
- **Evaluated by the scheduler, not by register.** It is due on the normal
  interval (`interval_seconds` or `url_healthcheck_interval`). Evaluation is a
  DB read, so do it **on the scheduler thread** (no pool submission, no
  network):
  - ok when `docker_status` is `running` (case-insensitive) **and** the
    entry is not stale (`last_api_update` within `stale_after_minutes`);
  - failing with message `Container <status>` (e.g. `Container exited`)
    when the status is anything else;
  - failing with `No update from notifier for <N> min` when stale, or
    `No update from notifier yet` when `last_api_update` is NULL.
  - `status_code` NULL, `latency_ms` NULL.
  - Results go through the same `record_check_result` path, so history,
    compaction, purge, uptime and bars all work unchanged.
- **Immediate transitions:** when a register changes `docker_status`, call
  `jobs.request_run([container_check.id])` so the change shows within about
  5 s instead of waiting for the interval. Don't write results from the
  register request thread.
- **Locked entries** (`is_static`) receive no registers, so the container
  check is skipped while locked: not scheduled and not counted in the rollup.
  Treat it like a disabled check. Unlocking resumes it.
- **Soft-deleted entries** are skipped as today.
- **Rollup** (`health_state.py`): the container check counts like any other
  check. Consequences, which tests should pin:
  - a Docker entry with no other checks shows Up when running and fresh, and
    Down when exited or stale;
  - running, but with one URL check failing, shows Degraded;
  - only a disabled container check plus no others shows Not monitored.
- **Filters:** unchanged. `stale` still means notifier staleness. A stale
  entry now also reads as failing through its container check, which is
  intended.
- **Configuration UI:** in the Health checks section on Edit, notifier entries
  show a "Container (Docker state)" row with **enabled** and **interval** only.
  Manual entries don't show it. The Add page (manual-only) doesn't show it.
  Validation is the same as the other checks (interval 30–86400).
- **Detail panel:** the container check renders like the others: its name is
  "Container", it has no target line, it shows the last message and bars. The
  existing Docker pill and stale icon on the views stay.
- **Migration** (`down_revision = 'b8e4d6a2c1f9'`):
  - Insert one enabled `container` check for every `source='notifier'` entry.
  - The downgrade deletes the `container` rows and their results; results
    cascade, but delete them explicitly if SQLite FK enforcement is off in
    migrations.
  - No new columns are expected. If you need one, its index follows the FK
    rule.
- **Backups:** container check config round-trips. Restoring a backup without
  one creates it for notifier entries.
- **Register contract:** unchanged. `schemas.py` is not touched and the
  notifier sends nothing new.

## What to do

1. Implement the design above.
2. **Tests:**
   - Migration creates container rows for notifier entries only (subprocess
     pattern).
   - The evaluation function: running and fresh, exited, stale, never
     reported, and case-insensitivity.
   - Scheduler: a container check runs on the scheduler thread, records a
     result, and is never submitted to the pool.
   - Register changing `docker_status` queues a run request; register with an
     unchanged status doesn't.
   - Adoption creates the container check.
   - A locked entry's container check is neither scheduled nor counted.
   - Rollup truth table with the container check: Up, Down, Degraded, Not
     monitored when disabled.
   - Edit page shows the container row for notifier entries only and saves
     enabled and interval.
   - Backup round-trip, and an old backup without the row.
   - The health endpoint includes the container check.
3. **Verify in a browser:** run the app locally against a scratch config dir.
   Seed a running/fresh entry, an exited one, a stale one, a locked one and a
   manual one. Load all three views and the Tiled drawer panel at desktop
   width, and confirm the badges and the Container block look right. Read at
   least the Dashboard and Tiled-drawer screenshots.
4. **Docs, in the same commit:**
   - PRD: add §13.8 "Container check", Delivered (unreleased), with an "As
     built" paragraph. Renumber the current §13.8 "Out of scope" to §13.9 and
     drop "Docker state as a check" from it. Update §13.1's state notes (the
     "Docker state … is not a check" sentence) and §5.6 (the `kind` list).
     Add a revision row.
   - FUTURE.md: remove the "Docker state as a check" bullet.
   - decisions.md: a new entry, superseding the earlier call; don't edit old
     entries.
   - CHANGELOG `[Unreleased]`: describe it for the operator, as part of the
     0.7.0 description.
   - README: the health-checks section.

## Conventions to honor

- Work on `dev`. Commit prefix `feat:`. No `Co-authored-by:` trailer. Never
  `git add -A`, never push.
- One Alembic migration, single head, downgrade written. Run it on an empty DB
  **and** on a DB at `b8e4d6a2c1f9` with seeded notifier and manual entries.
- Settings are read from `app.config`. UI POSTs carry CSRF.
- Before handing off, run `ruff check .`, `pytest -q` and `alembic upgrade head`
  on a fresh DB, and report the results.
- A venv with requirements-dev, ruff, icmplib and Playwright (cached Chromium)
  is at
  `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`.
  Scratch files go in that scratchpad, not the repo.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed `2026-11-15-v070-07-container-check.md`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on `dev`.
   Never `git add -A`, never push, never auto-commit.
