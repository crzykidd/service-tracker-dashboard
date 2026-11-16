---
name: v070-02-health-schema
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Health checks as their own tables

Move health-check configuration and state off `service_entry` columns into
`health_check` / `health_result` tables, with no visible behaviour change
yet. Spec: PRD §13.3 and §5.6. Depends on v070-01 having landed.

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
- Read `models.py`, `jobs.py` (`check_url`, `health_check_loop`),
  `routes_api.py` (health-toggle handling), `routes_dashboard.py`
  (add/edit health fields, `_parse_health_timeout`, backup/restore),
  `tests/test_health_check.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Models** `HealthCheck` and `HealthResult`, columns exactly as in
   §5.6:
   - `ServiceEntry.checks` relationship (cascade delete-orphan).
   - Helpers `entry.url_check('internal'|'external')` and
     `entry.service_checks`.
   - Constants for kinds, types and modes.
   - The `health_result` composite index `(check_id, ts)`.
   - Timestamps are naive UTC (`datetime.utcnow()`).
2. **Migration:**
   - Create both tables.
   - For every existing entry, insert `internal_url` and `external_url`
     rows. `enabled` comes from the legacy `*_enabled` (NULL → False);
     `timeout_seconds`/`verify_tls` from the entry columns.
   - Seed `last_ok`/`last_message`/`last_status_code`/`last_checked_at`
     from the legacy status and update strings (numeric code < 400 → ok;
     otherwise failing, with the string as the message; unparsable
     update time → NULL).
   - Downgrade drops both tables.
3. **Every path that creates an entry** (register create, Add, restore)
   also creates the two URL-kind rows. Add one helper,
   `ensure_url_checks(entry)`, and use it everywhere.
4. **Register:**
   - The `internal/external_health_check_enabled` keys set `enabled` on
     the matching row; absent means no change.
   - Stop writing the legacy `*_enabled` columns.
5. **Add/Edit:** the existing toggles and the timeout/verify fields
   read and write the URL-kind rows (the timeout and verify-TLS form
   values apply to both URL checks). No template layout change beyond
   the field bindings.
6. **Checker (interim):**
   - `health_check_loop` iterates enabled URL-kind checks and writes a
     `HealthResult` plus the check's `last_*` fields.
   - It also **mirrors** the result into the legacy `*_status`/`*_update`
     columns so the current templates stay correct. Mark the mirror
     `# TEMP: removed in v070-05`.
   - Keep it sequential; v070-03 replaces it.
7. **Backups:**
   - Export `checks` (config only) per entry.
   - Restore maps an older backup's legacy fields onto the URL-kind rows.
8. **Tests:**
   - Migration data copy (seed a DB at the previous head with legacy
     values, upgrade, assert rows).
   - New entries get both rows on all three create paths.
   - The register toggle maps onto rows.
   - Interim loop writes a result and mirrors.
   - Backup round-trip for new-format and old-format backups.
   - Update `test_health_check.py` for the new shape.

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
   failure), renamed with a date prefix (`<YYYY-MM-DD>-v070-02-health-schema.md`).
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
