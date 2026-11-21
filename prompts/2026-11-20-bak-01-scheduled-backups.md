---
name: 2026-11-20-bak-01-scheduled-backups
status: pending          # pending | completed | failed
created: 2026-11-20
model: sonnet
completed:
result:
---

# Task: Backup phase 1: UI-editable backup settings, two daily jobs, manual run, backup list

Make the backup settings editable in Settings → Backup & restore (DB-stored, with env >
UI > `settings.yml` > default precedence). Split today's single daily job into a
**database snapshot** job and an **export** job, each with its own time, keep days and
**Run now**. Add a backup file list with download and delete, path validation, and
last-run status with failure surfacing. In this phase the export job still writes
today's YAML entry list. bak-02 swaps it for the v1 export.

**Depends on:** settings modernization phase 1 (`prompts/done/2026-11-20-set-01-foundation.md`)
having landed: `templates/partials/settings/backup.html`, `_macros.html`,
`static/js/settings/ui.js` and `backup.js`, the flash policy and `_settings_redirect`.
If they are not in the tree, stop and report. Run it after set-04 if that phase is
queued, because set-04 also touches `backup.html` (the inline list error). Re-read the file
as it is now.

## Before you start

- Read `CLAUDE.md` (Definition of Done; Database Rules: WAL + `Connection.backup()`;
  Configuration: `load_settings()` once at startup; commit rules).
- Read the design doc **in full**: `docs/design/2026-11-20-backup-export-import.md`.
  This phase implements §4 (all), §10.2 (README manual restore steps), §12.1 cards 1–3
  (Location, Database snapshots, Exports without "Download export"), and the bak-01 row
  of §16. Its §17 decisions are final. Open
  `docs/design/2026-11-20-backup-export-import-mockup.html` for the look.
- Read `docs/design/2026-11-20-settings-modernization.md` §6 (components), §7 (flash
  policy) and §9.12.
- Code: `jobs.py` (`run_scheduled_backup`, `_write_sqlite_snapshot`, `BACKUP_SUFFIXES`,
  `start_background_workers`), `settings_loader.py`, `settings_store.py`,
  `routes_dashboard.py` (`settings()` backup/restore branches, `_render_settings`
  backup listing, `_settings_redirect`), `templates/partials/settings/backup.html`,
  `static/js/settings/backup.js`, `templates/settings.html` (nav badges),
  `tests/test_db_snapshot.py`, `tests/test_security_paths.py` (server-file confinement),
  `tests/conftest.py`.

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
(`jobs.py`, `settings_store.py`, `settings_loader.py`, `routes_dashboard.py`,
`templates/partials/settings/backup.html`, `templates/settings.html`,
`static/js/settings/backup.js`, `static/css/dashboard.css`, `settings.example.yml`,
`CHANGELOG.md`, `docs/PRD.md`, `README.md`, `CLAUDE.md`), list them and stop to ask. Unrelated
dirty files: mention them once. This file is exempt.

## What to do

1. **`backups.py`** (new module; add it to the CLAUDE.md module layout):
   - `effective_settings(app) -> dict`: each of `path`, `snapshot.{enabled,time,keep_days}`,
     `export.{enabled,time,keep_days,format}` with its value and `origin` (`env` / `ui` /
     `file` / `default`), following design §4.2. Env is detected through
     `app.config['CONFIG_FROM_ENV']`. `backup_days_to_keep` seeds both keep-days values.
     It never calls `load_settings()`.
   - `save_settings(app, values) -> (errors, warnings)`: validates (time `HH:MM`
     00:00–23:59, keep days 1–365, format yaml/json, path rules §4.5) and refuses to
     write an env-set key. Caller commits. `reset(key)` deletes the DB row.
   - `validate_path(path) -> (realpath, errors, warnings)` (§4.5).
   - `run_snapshot(app, trigger)` and `run_export(app, trigger)`: per-kind lock
     (`_RUN_LOCKS`, non-blocking acquire → "already running"), file names per §4.4
     (manual = `YYYY-MM-DD_HHMMSS-…`), `.tmp` + `os.replace`, retention for that kind
     only, and `backup_last_runs` written (and committed) on success and on failure.
     The snapshot keeps `_write_sqlite_snapshot`'s `Connection.backup()` logic (move it
     here; keep a `jobs._write_sqlite_snapshot` alias only if a test needs it). In this
     phase `run_export` writes today's entry-list YAML to `YYYY-MM-DD-std_backup.yml`
     (unchanged content), and bak-02 replaces it.
   - `prune(kind, keep_days)` by suffix: snapshots `-std_backup.sqlite3`. Exports
     `-std_export.yml` / `-std_export.json` (none exist yet) **and** legacy
     `-std_backup.yml`. Never anything else.
   - `list_files() -> {"snapshots": [...], "exports": [...]}`, each `{name, kind, size,
     modified, manual, legacy}`, newest first. `backup.yml` is listed as a legacy export.
   - `resolve_file(name)`: bare filename, known suffix (or `backup.yml`), realpath
     inside the backup folder. Move the confinement logic from the restore branch here
     and use it there too.
2. **`settings_store.py`:** the keys of design §4.1 with typed getters/setters and the
   module docstring list updated. Store `backup_last_runs` as one dict.
3. **Scheduler (`jobs.py`):** keep the scheduler in `_SCHEDULER`. Replace
   `scheduled_backup_job` with `backup_snapshot_job` and `backup_export_job` (CronTrigger
   from the effective times; a disabled job is added and then paused). Add
   `reschedule_backups(app)` (reschedule / pause / resume) and `next_run_times()` for the UI.
   Remove `run_scheduled_backup`, or keep it as a thin wrapper if a test imports it.
4. **Routes (`routes_dashboard.py`, admin + CSRF, every redirect via
   `_settings_redirect('backup')`):**
   - `POST /settings/backups/settings`: save, then reschedule. A validation error
     re-renders (400) with the banner in the section and the typed values kept. Path
     warnings go in a `warning` flash. On success, a toast.
   - `POST /settings/backups/settings/reset`: `key=` one of the resettable keys.
   - `POST /settings/backups/run`: `kind=snapshot|export`. Synchronous. A toast with
     the file name and size, or an error banner.
   - `GET /settings/backups/<name>/download` and `POST /settings/backups/<name>/delete`
     (confirm dialog via `data-confirm`), both through `resolve_file`.
   - `_render_settings` passes `backup_settings`, `backup_files`, `backup_last_runs`,
     `backup_next_runs` and `backup_list_error` (inline warning). Keep the existing
     restore form working: it lists `.yml` / `.yaml` files from the same folder.
5. **Template `partials/settings/backup.html`:** design §12.1 cards 1–3 with the
   settings components. Location (path, origin label, read-only when env-set, Reset,
   outside-`/config` warning), Database snapshots and Exports (switch, `input
   type=time`, keep days, the format select on Exports, next / last run or the failure
   `inline_warning`, **Run now** as its own small form, the file list with Download and a
   ⋯ menu with Delete). One guarded settings form with the sticky save bar (§6.9).
   Below them, the existing Backup and Restore cards stay **as they are**, under one
   heading "Import (legacy)". bak-04 replaces them. Next to the snapshot Download, the
   line "Snapshots contain every secret (password hashes, API key hashes, the MQTT
   password)." Subtitle: "Daily database snapshots and exports, and restore."
6. **Nav badge:** in `templates/settings.html`, a red "!" badge on Backup & restore while
   either kind's last run failed (same markup as the Streams badge).
7. **JS (`static/js/settings/backup.js`):** only what the markup needs (the existing
   restore-source toggle stays). No new behaviour beyond the components.
8. **`settings.example.yml`:** comment that `backup_path` / `backup_days_to_keep` are
   initial values, the UI can change them, and env vars win (read-only in the UI).

## Tests (new `tests/test_backups.py`; keep everything else green)

- Precedence: default; file value; a UI value beats file; env beats UI (save refused,
  origin `env`); reset falls back to file; `backup_days_to_keep` seeds both keep-days values.
- `validate_path`: relative refused; a file refused; unwritable refused (chmod a temp dir;
  skip as root); created when missing; a warning outside `CONFIG_DIR`, none inside.
- Scheduler: after `reschedule_backups`, the job triggers carry the saved hour/minute; a
  disabled job is paused (`next_run_time is None`); re-enable resumes. Use a real
  `BackgroundScheduler` not started, or patch `_SCHEDULER`.
- `run_snapshot` (manual): a timestamped name, a valid SQLite file (`PRAGMA
  integrity_check`), `backup_last_runs.snapshot.ok`; a forced failure (patch
  `sqlite3.connect`) records `ok: false` with the error and leaves no `.tmp`; a
  concurrent run → "already running".
- Retention: per kind by mtime (`os.utime`); a non-matching file is never deleted;
  legacy `-std_backup.yml` is pruned with export retention.
- Routes: settings save 400 re-render on a bad time (banner inside `section-backup`);
  run → redirect `section=backup` + toast; download confinement (`../x`, an unknown
  suffix, an absolute path → 404/400), delete works and confirms via `data-confirm`
  text; the nav badge appears after a failed run.
- Update `tests/test_db_snapshot.py` to the new functions without weakening it.
- `pytest -q` and `ruff check .` pass.

## Docs (same commit)

- **CHANGELOG `[Unreleased]` → Added:** backup settings editable in Settings (path,
  daily snapshot and daily export, each with time and keep days, Run now), a backup file
  list with download and delete, last-run status and a warning when a run fails.
  **Changed:** `backup_path` / `backup_days_to_keep` in `settings.yml` are now initial
  values. Env vars still win and show read-only.
- **PRD:** add a planned section "v0.11.0 — Backup, export and import (Planned)" right
  after the settings-modernization section (§19 at the time of writing; check the
  numbering, and renumber following sections and the TOC only if the PRD already did so
  for §19). Summarise design §1, §4, §5.1, §6.1, §7.2, §10 and §16 in a few paragraphs
  each, link the design doc, mark §4 (backup jobs) "Delivered (unreleased)" and the rest
  "Planned". Update the §3 architecture job list (the 00:05 job becomes two jobs). Add a
  revision-history row.
- **README:** Configuration (the two keys are now initial values; UI editing; env
  read-only), the Backup section description, and **manual database restore steps**
  (design §10.2).
- **CLAUDE.md:** module layout gains `backups.py`. Nothing else.

## Conventions to honor

- No export format, import, API routes or restore in this phase (bak-02..05). No new
  `settings.yml` / env keys.
- Every SQLite copy uses `Connection.backup()`. Never `shutil.copy*` on the live DB.
- Commit style: `feat:`. No `Co-authored-by:`. Docs in the same commit.
- Record non-obvious calls in `docs/decisions.md` (newest at top, heading "bak-01").

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (success) or `prompts/failed/` (failure): `git mv`
   if `git ls-files --error-unmatch <this file>` succeeds, otherwise plain `mv`.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.** Report
   back the file list (including this prompt's new path), the proposed message `feat:
   UI-editable backup settings with daily snapshot and export jobs, Run now and a backup
   list (backup phase 1)`, the test result, and a short manual browser checklist.
