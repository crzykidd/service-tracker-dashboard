---
name: 2026-11-17-inv-02-ha-since-and-db-snapshot
status: completed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: Since sensor + nightly SQLite snapshot built; ruff and full suite green
---

# Task: Home Assistant "Since" sensor and a nightly SQLite snapshot

Build PRD §18.2: two small, independent additions for 0.10.0.

## Before you start

- inv-01 must be completed (`prompts/done/2026-11-17-inv-01-api-revision.md`). If
  it isn't, stop and report.
- Read `CLAUDE.md` (Database Rules: WAL + `Connection.backup()`), PRD §17.3,
  §17.4, §18.2, `notify_ha.py`, `notify_state.py` (`entry_payload`, `since`,
  `_iso`), `jobs.py` (`run_scheduled_backup`, the backup prune loop) and
  `extensions.py` (how the SQLite URI and connection are set up).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **"Since" sensor** in `notify_ha.entry_configs`. For every published entry,
   add a `sensor`:
   - name `Since`, `device_class: timestamp`;
   - unique id `<node>_entry_<id>_since`, config topic object id
     `entry_<id>_since`, `default_entity_id` `sensor.<device slug>_since`;
   - state topic and availability as for the `State` sensor;
   - a value template that renders HA "unknown" when `since` is null (test it,
     don't guess the template). Confirm the `since` value format is one HA's
     timestamp sensor accepts (ISO 8601 with a timezone).
   - The reconcile (`full_sync`) and purge (`notify_purge`) must pick up the new
     config with no special-casing. Check per-entry purge clears it. Extend the
     discovery and purge tests.
2. **Nightly SQLite snapshot** in the daily backup job:
   - after the YAML file, write `<YYYY-MM-DD>-std_backup.sqlite3` into the same
     `backup_path` using `sqlite3.Connection.backup()` from the live database to
     a new file connection. Never use `shutil.copy*`;
   - a failure logs an error and never stops the YAML backup;
   - extend the prune loop so `backup_days_to_keep` also removes old
     `-std_backup.sqlite3` files, without touching anything else in the folder;
   - test: the snapshot opens, has the same tables and row counts, and pruning
     works.
3. **Docs:**
   - README backup section: the snapshot file and the manual restore (stop the
     container, replace the DB file in the config volume with the snapshot,
     start it). Say where the live DB lives. The YAML restore stays as it is;
   - PRD §17.4 entity list gets the Since sensor; §18.2 marked delivered;
   - CHANGELOG Added entries for both.

## Conventions to honor

- CLAUDE.md "Always — Definition of Done":
  - add a CHANGELOG `[Unreleased]` entry in operator language (not for a
    refactor-only change);
  - mark the PRD subsection "Delivered on `dev`" with an "As built" note for any
    deviation, and add a revision-history row;
  - update README where operator-facing behaviour changes.
- Lint with CI's pinned ruff, `uvx ruff@0.15.17 check .` (other versions disagree
  on import sorting). Run the full suite with `pytest -q`. Both must be green.
- Every new management route is registered in `mgmt_openapi.OPERATIONS` (tests
  enforce it) and gets MCP tools in `mcp/std_mcp.py` (read key: read tools only).
- Schema changes only through Alembic, with FK indexes in the same migration.
  `Migration check` (one head, upgrade on an empty DB) must pass.
- Keep the register contract and its safe-degradation guarantees intact
  (CLAUDE.md "Register Contract Rules").
- In your report, only claim doc edits that `git diff` shows.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top).
4. Do **not** commit. Prepare the working tree, then report back to the
   orchestrating session:
   - the file list (this prompt file and its move included);
   - a one-line commit message with the right prefix (`feat:` / `fix:` /
     `refactor:` / `docs:`), no `Co-authored-by:`;
   - test and lint results;
   - anything you deviated from or left undone.
   Never `git add -A`, never push.
