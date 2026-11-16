---
name: v070-03-checker-engine
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Concurrent checker, service-check types, history retention

Replace the sequential health loop with a concurrent scheduler supporting
HTTP/HTTPS (status and body modes), TCP and ping checks, plus the 24h-raw /
hourly-compacted / 7-day retention. Spec: PRD §13.4. Depends on v070-02.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§13** (the v0.7.0 plan) in full, plus **§5.6** (planned
  schema). The subsection named below is your spec. Where it and the code
  disagree, trust the code, follow the spirit of the PRD and record the
  call in `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.7.0 Dashboard and Monitoring design
  calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with
  tests, because `Test` is a required check.
- Read `jobs.py` (worker startup in `start_background_workers`, the
  APScheduler jobs), `extensions.py`, `gunicorn.conf.py` (one worker),
  `settings_loader.py`, `requirements.in` / README "pinned
  dependencies".

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **New module `checker.py`:**
   - Pure probe functions `probe_http(target, mode, timeout, verify)`,
     `probe_tcp(target, timeout)` and `probe_ping(target, timeout)`.
   - Each returns a small dataclass `(ok, latency_ms, status_code,
     message)` and never raises.
   - Body-mode rules exactly as in §13.4: 4 KB cap, `OK`
     case-insensitive, `Error:` prefix → message (≤200 chars), otherwise
     `Unexpected response: …`, and status ≥ 400 handling.
   - `verify=False` suppresses the urllib3 warning for that call only
     (reuse the v0.6.9 approach).
2. **Ping:**
   - Add `icmplib` to `requirements.in` and regenerate `requirements.txt`
     with `uv pip compile --python-version 3.11` (see README).
   - Try `privileged=True`, then `privileged=False`; on permission
     failure return failing with `ICMP not permitted`.
   - Verify it actually works in the built image (`docker build`, then
     run a one-off probe against the gateway). Use
     `--log-driver json-file` if you need logs; see decisions.md.
3. **Scheduler:** replace `health_check_loop`.
   - A thread ticks every 5 s and selects due checks: enabled, entry
     active, URL-kind with a non-empty URL, `last_checked_at IS NULL or
     + interval <= now`.
   - Resolves the target (URL-kind → the entry's current URL) and
     interval/timeout (per-check or the globals `url_healthcheck_interval`
     / `health_check_timeout`).
   - Submits to a `ThreadPoolExecutor(max_workers=health_check_workers)`,
     tracking in-flight check ids.
   - Collects completed futures, then writes `HealthResult` rows and
     updates `last_*` and `consecutive_failures` in **this thread only**.
   - Keep the legacy mirror for URL-kind checks.
   - Wrap each tick in the same keep-alive try/except as today.
4. **Settings:**
   - Add `health_check_workers` (int, default 8),
     `health_raw_hours` (24) and `health_history_days` (7).
   - Update `settings.example.yml` and the README.
5. **Compaction job** (APScheduler, hourly at :05) and a purge job:
   - Compaction follows §13.4 exactly: per check, raw ok rows older than
     `health_raw_hours` become one range row per (clock hour, unbroken ok
     run), with `ts`, `ts_end`, `samples`, average and maximum latency.
     Failures are untouched.
   - Purge deletes rows older than `health_history_days`.
   - Batch the work so a large backlog doesn't hold the write lock for
     long.
6. **Check now:** `POST /service/<id>/checks/run` (login, CSRF, JSON
   response) clears `last_checked_at` on that entry's enabled checks so
   the next tick runs them. No UI button yet (v070-06 adds it).
7. **Tests:** no real network.
   - Probe functions against a local `http.server`/socket fixture or a
     mocked `requests`; cover every body-mode branch, TCP up/down and
     ping permission failure (mock `icmplib`).
   - Due-selection logic.
   - Single-writer behaviour: worker functions take no session.
   - Compaction: mixed ok/fail across hour boundaries gives the expected
     ranges and sample totals, and uptime totals are preserved.
   - Purge boundary.
   - Check-now endpoint (auth and CSRF).

## Conventions to honor

- Work on `dev`. Commit prefix `feat:` (or `fix:`/`refactor:` if that is
  more accurate). No `Co-authored-by:` trailer. Never `git add -A`, never
  push.
- Schema changes go through **one** new Alembic migration with a single
  head. Every FK gets its index in the same migration. Use
  `batch_alter_table` for SQLite column changes. `alembic upgrade head`
  must work on an empty DB **and** on a DB at the current head with data.
  Write a downgrade.
- Read settings from `app.config`. Never call `load_settings()` in
  handlers. New settings go in `settings_loader.py` (type and default),
  `settings.example.yml` and the README settings reference.
- UI POSTs carry CSRF (`stdPost` for JS). Templates match the existing
  Tabler-icon and Tailwind vocabulary.
- **Definition of done (same commit as the code):**
  - A CHANGELOG `[Unreleased]` entry in operator language.
  - The PRD subsection is marked "— Delivered (unreleased)" with a short
    "As built:" paragraph, and a revision-history row is added at the
    bottom of the table.
  - The README is updated where operator-facing behaviour changed.
  - Non-obvious calls go in `docs/decisions.md`.
- Before handing off, run `ruff check .`, `pytest -q` and
  `alembic upgrade head` on a fresh DB. Report the results verbatim if
  anything fails.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed with a date prefix (`<YYYY-MM-DD>-v070-03-checker-engine.md`).
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
