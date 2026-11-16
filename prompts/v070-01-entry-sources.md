---
name: v070-01-entry-sources
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Separate manual entries from notifier entries

Give every service entry a `source` (`notifier` or `manual`) so non-Docker
sites are clean, first-class dashboard entries instead of fake containers.
Spec: PRD §13.2.

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
- Read `models.py` (`ServiceEntry`, `is_docker_status_stale`),
  `routes_api.py` (`upsert_service`, the `is_static` short-circuit),
  `routes_dashboard.py` (`/add`, `/edit/<id>`, backup/restore around
  `restore_scope`), `templates/add_entry.html`, `edit_entry.html`,
  `dashboard.html`, `tiled_dash.html`, `compact_dash.html`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Migration + model:**
   - Add `service_entry.source` (String(16), NOT NULL, server default
     `'notifier'`), backfilled to `manual` where `last_api_update IS NULL`.
   - Make `host` nullable and add `description` (String(255), nullable).
   - Add `ServiceEntry.is_manual`.
   - `is_docker_status_stale` returns False for manual or locked entries.
2. **Register (`upsert_service`):**
   - A matching row that is `manual` and not locked is **adopted**: set
     `source='notifier'`, log it at INFO, then continue the normal update.
   - Locked rows keep returning `skipped`.
   - New rows are created as `notifier`.
   - `schemas.py` is **not** touched.
3. **Add page:**
   - Creates `manual` entries only.
   - Fields: Name (`container_name`), Host (optional), Description,
     Group, Icon, URLs, sort priority, URL health toggles and the v0.6.9
     timeout/verify fields.
   - Drop "application"/container wording.
   - Duplicate check is (host or NULL, name) among active rows; keep the
     soft-deleted message.
4. **Edit page:**
   - Manual entries hide the Docker-only fields and the "Reported by
     notifier" block, and show Description.
   - Relabel `is_static` as "Lock (ignore notifier updates)" with a
     one-line hint.
5. **Views:**
   - Manual entries show a manual-source icon (e.g. `ti-world` or
     `ti-link`) and no Docker pill or stale icon.
   - Notifier entries are unchanged.
   - The text filter and grouping must handle a NULL host (Host axis
     bucket = "Unknown host").
6. **Backups:**
   - Export `source` and `description`.
   - Restore without `source` uses the backfill rule. `host` may be null.
7. **Tests:**
   - Migration backfill.
   - Adoption (unlocked manual → notifier; locked manual → skipped).
   - Manual entries never stale.
   - Add creates manual with and without a host.
   - Duplicate check with a NULL host.
   - Backup round-trip of `source`/`description`, and an old backup
     without them.
   - Templates render a manual entry without errors on all three views.

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
   failure), renamed with a date prefix (`<YYYY-MM-DD>-v070-01-entry-sources.md`).
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
