---
name: 2026-11-15-v069-08-health-check-options
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: Added health_check_timeout setting, per-service timeout and verify-TLS columns with edit/add UI, backup round-trip, check_url + tests
---

# Task: Per-service health-check timeout and TLS-verify override (PRD §12.8)

Health checks use a hardcoded 5 s timeout and always verify TLS, so self-signed internal URLs report `Error: SSLError`. Add a global timeout setting and per-service timeout and verify-TLS overrides.

## Before you start

- Read `CLAUDE.md` (project rules + the three standards snippets — they apply).
- Read `docs/PRD.md` §12 intro and this task's subsection (named below);
  read the 2026-11-15 "v0.6.9 scope" entry in `docs/decisions.md`. The design
  calls there are settled — don't re-litigate them; if the code makes one
  impossible, stop and report rather than improvising.
- Part of the v0.6.9 sequence (`prompts/2026-11-15-v069-*.md`, run in number
  order). Confirm earlier prompts in the sequence are in `prompts/done/`; if one
  isn't, stop and report.
- PRD subsection: **§12.8**.
- Read `jobs.py` (`health_check_loop`), `models.py`, `routes_dashboard.py` (`/edit`, `/add`), `templates/edit_entry.html`, `templates/add_entry.html`, and backup/restore in `routes_dashboard.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. Migration: `service_entry.health_check_timeout` (Integer, nullable) and `service_entry.health_check_verify_tls` (Boolean, NOT NULL, `server_default=sa.true()`).
2. Setting `health_check_timeout` (int, default 5).
3. `health_check_loop`: timeout = the entry's value or the global setting; `verify=entry.health_check_verify_tls`. When verify is false, suppress `urllib3.exceptions.InsecureRequestWarning` for that call only (a `warnings.catch_warnings()` block), not process-wide.
4. Edit page and Add page: an "Advanced health check" section with timeout (blank = default, validated as a positive int with a sane max such as 60) and a "Verify TLS certificate" checkbox. Neither field is a register field: don't touch `schemas.py`, and don't let `upsert_service` overwrite them.
5. Backup/restore round-trips both fields (defaults when absent).
6. Extract the per-URL check into a small function so it can be unit-tested with a mocked `requests.get`. Test the timeout precedence and that the verify flag is passed through.

## Conventions to honor

- Work on `dev`. Commit prefix per CLAUDE.md (`feat:` / `fix:` / `chore:` /
  `docs:` / `refactor:`), no `Co-authored-by:` trailer.
- **Definition of Done (CLAUDE.md "Always"):** in the same commit —
  CHANGELOG `[Unreleased]` entry for anything operator-visible (user-facing
  language; tooling-only changes go in `docs/HISTORY.md` / `docs/decisions.md`
  instead); README updated if operator-facing behavior or settings changed
  (settings reference table included); PRD §12 subsection status flipped from
  "Planned" to "Delivered (unreleased)" with any as-built deviations noted, plus a
  PRD revision-history row appended at the bottom of the table.
- Schema changes only via a new Alembic migration chained on the current head;
  FK/lookup columns get their index in the same migration.
- Run locally before handing off: `uvx ruff@0.15.17 check .`, `pytest` (once
  `tests/` exists), and the migration check from `.claude/commands/release-prep.md`
  `<LOCAL_CHECKS>` if you touched `alembic/`. Report the results verbatim.
- New settings must be added to `settings_loader.VALID_KEYS` / `DEFAULT_VALUES`,
  `settings.example.yml`, and the README settings table.

- CHANGELOG `### Added`. README settings table and Health Checks section. PRD §5.5 (v0.6.9 schema changes): add the two columns. PRD §15: the health-check timeouts item is already struck through; confirm the wording.
- No register-contract change. Say so in the PRD subsection as built.
- Commit prefix: `feat:`.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. By default the message
   is a plain one-liner and the branch is whatever the session is on. **Only if** the
   project also adopts `code-checkin-and-pr` do its branch rules (`dev`, never `main`)
   and commit-prefix conventions (`feat:` / `fix:` / `chore:` / `docs:`, no
   `Co-authored-by:`) apply on top.
