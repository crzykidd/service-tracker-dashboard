---
name: 2026-11-20-bak-05-staged-restore
status: pending          # pending | completed | failed
created: 2026-11-20
model: sonnet
completed:
result:
---

# Task: Backup phase 5 (optional): staged database restore from a snapshot

Let the operator pick or upload a `.sqlite3` snapshot in the UI. STD validates it,
saves it as a pending restore, and swaps it in on the next container start, before
migrations, keeping the current database as `pre-restore-<timestamp>.sqlite3`. **There is
no live swap.** This phase is optional. Run it only if the operator approved it (design
§14 Q4). If they dropped it, do not run this prompt. The orchestrator moves the PRD's
restore subsection to `docs/FUTURE.md` instead.

**Depends on:** bak-01 (backup list, `backups.resolve_file`, the Backup section).
bak-04 is not strictly needed, but run this after it so the Backup section layout is
final.

## Before you start

- Read `CLAUDE.md` (Database Rules: WAL, **`Connection.backup()` for every copy**,
  Alembic is the schema's source of truth).
- Read the design doc: `docs/design/2026-11-20-backup-export-import.md` §10 (all),
  §12.1 card 5, §13 (restore risks), §17 (the restore decision). Mockup: the "Restore
  database" card.
- Code: `entrypoint.sh`, `gunicorn.conf.py`, `app.py` (`DATABASE_PATH`, `CONFIG_DIR`,
  startup), `alembic.ini`, `alembic/env.py`, `alembic/versions/` (to see how heads are
  laid out), `backups.py`, `settings_store.py`, `templates/partials/settings/backup.html`,
  `templates/settings.html`, `Dockerfile` (which files land in the image),
  `docker-compose.yml`.

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
(`entrypoint.sh`, `Dockerfile`, `backups.py`, `routes_dashboard.py`, the backup template,
`settings.html`, `static/js/settings/backup.js`, `CHANGELOG.md`, `docs/PRD.md`,
`README.md`, `CLAUDE.md`), list them and stop to ask. This file is exempt.

## What to do

1. **`restore_staging.py`** (app side; stdlib `sqlite3` + alembic `ScriptDirectory`):
   - `validate(path) -> dict | raises RestoreError`: open with a `file:...?mode=ro` URI;
     `PRAGMA integrity_check` == `ok`; the tables `alembic_version`, `service_entry` and
     `setting` exist; `version_num` is known to this code and is `head` or an ancestor of
     head (walk `ScriptDirectory.from_config(Config("alembic.ini"))`); a newer or unknown
     revision → "made by a newer STD". It returns `{revision, entries, latest_update,
     instance_id, same_install}`.
   - `stage(path, source_name, user) -> dict`: copy into `<CONFIG_DIR>/restore/pending.sqlite3`
     with `sqlite3.Connection.backup()` (from the validated file, not a raw copy) and
     write `pending.json` `{source_name, sha256, revision, staged_at, staged_by,
     keep_dir}` (`keep_dir` = the effective backup path).
   - `pending() -> dict | None`, `cancel()`, `last_result() -> dict | None` (reads
     `restore/last.json`), `mark_seen()` (`settings_store` key `restore_last_seen`).
2. **`restore_swap.py`** (repo root, **stdlib only, no app import**). Runs before
   migrations. Implement design §10.1 step 5 exactly: exit 0 when nothing is pending;
   re-check sha256 + integrity; keep the current DB with `Connection.backup()` to
   `<keep_dir>/pre-restore-YYYYMMDD-HHMMSS.sqlite3`; remove `services.db`, `-wal`, `-shm`;
   `os.replace(pending, services.db)`; write `last.json`; on **any** failure keep or
   put back the current DB, rename the pending files to `failed-<ts>.*`, write
   `last.json` with the error, and still exit 0. Print one line per step (the container
   log). Paths come from `STD_CONFIG_DIR` (default `/config`), the same way
   `settings_loader.CONFIG_DIR` gets them.
3. **`entrypoint.sh`:** run `python restore_swap.py` before `alembic upgrade head`.
   Make sure the Dockerfile copies `restore_swap.py` into the image (check `.dockerignore`).
4. **Routes** (admin + CSRF, `_settings_redirect('backup')`):
   `POST /settings/restore/stage` (`server_file` via `backups.resolve_file`, snapshots
   only, or an upload `snapshot_file` ≤ 200 MB streamed to `restore/upload-<token>.sqlite3`
   and deleted after staging). It validates, then renders a confirmation (the found
   metadata) with a danger confirm ("Everything since the snapshot is lost, including API
   keys created since. The current database is kept as pre-restore-….sqlite3.") posting
   to `POST /settings/restore/confirm`. Also `POST /settings/restore/cancel` and
   `POST /settings/restore/dismiss` (mark the last result seen).
5. **UI:** the Restore database card (§12.1 card 5), **Restore…** in each snapshot
   row's ⋯ menu, the "restore staged" inline warning with **Cancel restore** shown at the top of
   Settings on every section while one is pending, and the last-result banner (ok or
   error) in the Backup section until it is dismissed. `pre-restore-*` files appear in the
   snapshot list with a "pre-restore" tag (never auto-pruned; bak-01's prune must not
   match them; verify).
6. No management API route (design §10.1 notes; Later).

## Tests (new `tests/test_staged_restore.py`)

- `validate`: a good snapshot (made with `backups.run_snapshot`); a corrupt file
  (truncated bytes); a non-STD SQLite file; a revision not in the script directory; an
  older known revision is accepted.
- `stage` + `pending` + `cancel`; `pending.json` fields; sha256.
- `restore_swap.py` run as a subprocess with `STD_CONFIG_DIR` = a temp dir: nothing
  pending → exit 0, no change; a pending restore → `services.db` replaced (row counts
  equal the snapshot), `pre-restore-*` exists and is a valid copy of the old DB **including
  a row committed only in its WAL** (open the old DB in WAL mode, insert, do not
  checkpoint, then run the swap), the `-wal` / `-shm` files gone, `last.json` ok; a
  sha256 mismatch → current DB untouched, `failed-*` files, `last.json` error, exit 0.
- After the swap, `alembic upgrade head` succeeds on the restored file (an older revision
  is migrated forward).
- Routes: staging from a server file and from an upload (size limit), confinement, the
  pending banner on another section, cancel, dismiss.
- `pytest -q` and `ruff check .` pass.

## Docs (same commit)

- **CHANGELOG `[Unreleased]` → Added:** restore the database from a snapshot in Settings
  (validated, applied on the next container restart, the current database kept as
  `pre-restore-<timestamp>.sqlite3`).
- **PRD:** the restore subsection → "Delivered (unreleased)". Mark the whole planned
  section delivered (this is the last phase). Update §3 (startup sequence: the swap
  before migrations). Revision-history row.
- **README:** Backup & restore (staged restore steps, the restart requirement, that
  `python app.py` outside the entrypoint does not swap), and keep the manual fallback.
- **CLAUDE.md:** module layout (`restore_staging.py`, `restore_swap.py`). Database Rules:
  one line noting that the restore swap uses `Connection.backup()` for the kept copy.

## Conventions to honor

- No live swap, ever. No `shutil.copy*` of a live database. `restore_swap.py` imports no
  app module.
- A failed swap never blocks startup.
- Commit style: `feat:`. No `Co-authored-by:`. Docs in the same commit.
- Non-obvious calls → `docs/decisions.md` (heading "bak-05").

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (or `prompts/failed/`): `git mv` if tracked,
   otherwise plain `mv`.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.** Report
   back the file list, the proposed message `feat: staged database restore from a
   snapshot, swapped in at container start (backup phase 5)`, the test result, and a
   manual checklist (stage, restart the container, verify, pre-restore file, cancel).
