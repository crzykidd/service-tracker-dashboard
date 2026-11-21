---
name: 2026-11-20-bak-00-backup-export-import-design
status: completed        # pending | completed | failed
created: 2026-11-20
model: opus
completed: 2026-11-20
result: Design doc, mockup and five build prompts (bak-01..05) for scheduled backups, export format v1, import engine + UI, and optional staged restore; no code changed.
---

# Task: design backup, export and import for 0.11.0 (design doc + mockup + build prompts)

Redesign Settings → Data → Backup into two features: (1) scheduled + manual **database
backups** (disaster recovery) and (2) **export / import** of operator-set state as YAML or
JSON, where import matches records on a fresh or different install and fills in missing
settings after a dry-run preview. **No application code changes in this task.**

## The operator's scenario (the main design driver)

Docker entries, DHCP stream entries and HA publishing are all set up. The operator
exports. They move to another machine or lose the DB. They start STD, the notifier
and the stream sidecars post, and the base entries land again (Docker via register,
DHCP via the stream). Then they import: a **preview** shows every matched record and
the settings it is missing; they select all or a subset to apply. Records in the file
that match nothing locally can be **imported as new**.

## Operator decisions (final, do not re-open)

- **Two scheduled jobs, both daily, each with its own retention** (default 7 days,
  settable in the UI): a **database snapshot** (`sqlite3.Connection.backup()`, WAL-safe,
  as today) and an **export file** in the new format. The new export **replaces today's
  daily YAML entry list**. **Manual "run now"** for both. The operator chooses the
  **backup path** in the UI.
- UI-editable backup settings (enabled per job, time of day, keep-days per kind, path)
  are DB-stored (`settings_store.py`) and the job reschedules live. Precedence to
  design and justify: `settings.yml` supplies initial values; a value set by an
  environment variable wins and is shown read-only ("set by environment"). Path
  validation (writable dir, created if missing; warning when outside `/config` that it
  must be a mounted volume).
- **Export contains only operator-set state, never observed data** (status, IP/MAC,
  exposure observations, health results rebuild themselves). Versioned document:
  `format: std-export`, `format_version`, `exported_at`, `std_version`, `instance_id`,
  then sections. YAML and JSON are the same schema.
- **No secrets, ever.** No MQTT password, no API key hashes, no user password hashes.
  Those are re-set-up on a new install. API keys are not exported at all (state this;
  the doc should say what the operator must redo: new ingest keys for sidecars, MQTT
  password, user passwords).
- **Users:** exported without passwords; import offers a "user import" that creates
  missing users **with no usable password** (design how they get one: e.g. an admin
  sets it from Users; they can't log in until then; never auto-generate and display).
  Existing local users are never modified by import beyond fields you justify.
- **Import default mode: "fill missing only"**; "also overwrite differences" is an
  explicit opt-in. Never overwrite silently.
- Preview statuses (refine as needed): *Matched — missing settings* (ticked),
  *Matched — differs* (unticked, per-field values shown), *Matched — identical*
  (collapsed count), *Ambiguous* (operator picks the target), *Not found* ("Import as
  new", off by default). Grouped by source in collapsible groups with tri-state
  group checkboxes and select all / none, reusing the settings-redesign components
  (`docs/design/2026-11-20-settings-modernization.md`).
- **Import as new reuses existing mechanisms:** a not-found Docker entry becomes a
  manual entry with host + name so register adoption takes it over when the container
  appears; a not-found stream item becomes a manual entry that the existing link-offer
  matching pairs when the item appears. Verify both mechanisms against the code and
  say exactly what conditions must hold (e.g. unlocked, `source = manual`).
- **Streams are mapped first** (file stream id → local stream, auto by id, operator can
  change). Streams not present locally show "not present yet — re-run the import after
  the sidecar posts". Import must be **idempotent / re-runnable**.
- **Old YAML backups stay importable** (legacy format → format version 0).
- Apply is one transaction, audited (decide where: `api_audit` for API, app log for UI,
  matching the existing convention — see decisions.md), with a result summary.

## Open item to propose (the operator asked what it means)

**Database restore from a snapshot.** Today restoring a `.sqlite3` snapshot means
stopping the container and swapping the file by hand. Propose (recommended) a **staged
restore**: pick or upload a snapshot in the UI → STD validates it (`PRAGMA
integrity_check`, readable `alembic_version` not newer than the code) → saves it as a
pending restore → on the next container start, before migrations, it is swapped in and
the current DB is kept as `pre-restore-<timestamp>.sqlite3`. No live swap. Design it as
its own phase so the operator can drop it; also describe the manual fallback.

## Before you start

- Read `CLAUDE.md` (Database Rules: WAL + `backup()`; Configuration: `load_settings()`
  once at startup), `docs/PRD.md` (search "backup", "restore", §5 schema, §12.5 deleted,
  §17 notifications, §18 streams incl. §18.6–§18.7 link offers and adoption, §14
  management API), `docs/FUTURE.md` "Backup contents and format", and
  `docs/design/2026-11-20-settings-modernization.md` (components, the Data group, §9.12).
- Code: `jobs.py` (`run_scheduled_backup`, `_write_sqlite_snapshot`, retention, job
  registration), `settings_loader.py`, `settings_store.py`, `routes_dashboard.py`
  (backup/restore routes, `_restore_checks`, restore clash checks), `models.py`
  (every model's `to_dict` / `to_config`, which columns are operator-owned vs observed;
  URL provenance `ui_edit` > `explicit_label` > `synthesized`), `streams.py` (plan/apply
  shape to mirror, link matching), `routes_api.py` (register adoption of manual
  entries), `entrypoint.sh` + `gunicorn.conf.py` (where a pre-migration swap could run),
  `mgmt_openapi.py` / `routes_mgmt_api.py` (if export/import gets API routes).
- A settings-modernization phase is running **concurrently** in this tree and is
  editing templates, routes, `docs/decisions.md` and `docs/PRD.md`. **Do not edit any
  existing file.** Only create the new files listed below. Put your decisions in the
  design doc's "Decisions" section; the orchestrator copies them into
  `docs/decisions.md` later.

## What to do

1. **Design doc** `docs/design/2026-11-20-backup-export-import.md`:
   - Goals / non-goals; the scenario walk-through end to end.
   - Backup jobs: settings model, precedence, scheduling (APScheduler reschedule; one
     gunicorn worker), file naming (keep `<date>-std_backup.sqlite3`; name the export
     e.g. `<date>-std_export.yml|json`), retention per kind, manual run, the backup
     list (download, delete), path validation, failure surfacing in the UI.
   - **Export format v1**: full schema (pydantic models, field by field), with a
     **field ownership table** for every `service_entry` / `health_check` /
     group / widget / channel / stream / block / settings column: exported or not, and
     why. Identity block per record type: Docker `(host, container_name)`; stream
     `(stream_id, stream_key)`; manual `(container_name, host)`; linked entries carry
     both. Relationships by natural key (group name, widget name), never DB ids.
     Version policy (reject a newer `format_version` than supported; unknown keys in
     an older/newer minor → warn or reject, decide).
   - **Matching rules** per record type, incl. case sensitivity, ambiguous cases, a
     stream entry that was manual-linked, entries soft-deleted locally (do they match?
     restore?), the stream mapping step, groups/widgets/channels/streams/blocks/users
     and runtime settings.
   - **Import engine**: `plan()` (pure, dry-run, returns per-record status + per-field
     diffs "missing" vs "differs") and `apply(plan, selection, mode)`; how the plan is
     held between preview and apply (token + server-side temp file with TTL, or
     re-plan on apply and verify a checksum — pick and justify; stale-plan detection if
     the DB changed in between); size limits; one transaction; idempotency; what the
     result summary reports.
   - Legacy YAML (v0) mapping.
   - Staged DB restore (separate phase) + manual fallback.
   - UI: the Backup section layout (cards: Database snapshots, Exports, Import, Restore),
     the import flow (upload → stream mapping → preview → apply → summary), using the
     settings-redesign components.
   - Management API + MCP: propose routes (`GET /api/v1/export`, `POST
     /api/v1/import/plan`, `POST /api/v1/import/apply`, backup list/run) with scopes;
     every new route goes in `mgmt_openapi.py`. Decide whether these need an
     `API_REVISION` bump (they do if added to `/api/v1`).
   - Testing approach (fixtures: export → wipe → re-register/re-stream → import;
     legacy file; ambiguous; idempotent re-run).
   - Risks; a "Later" list; a few concrete open questions; a **Decisions** section.
2. **Mockup** `docs/design/2026-11-20-backup-export-import-mockup.html`: self-contained
   static HTML matching `docs/design/2026-11-20-settings-modernization-mockup.html`'s
   look (reuse its inline CSS). Show the Backup section (snapshot card with schedule,
   keep-days, path, Run now, file list; export card likewise), and the import preview:
   stream mapping row, three source groups (Docker expanded with missing / differs /
   ambiguous / not-found rows and one expanded per-field diff), the mode switch, the
   sticky apply bar with counts, and a result summary. Fake data only.
3. **Build prompts** (status `pending`, model `sonnet`, from `prompts/TEMPLATE.md`),
   each self-contained with read list, exact scope, tests, CHANGELOG/PRD/README duties,
   and "When done" (plain `mv` to `prompts/done/`, report back, don't commit):
   - `2026-11-20-bak-01-scheduled-backups.md` — DB-stored backup settings, both daily
     jobs + retention + manual run, backup list/download/delete, the Backup section
     shell in the new settings components (depends on settings phase set-01 having
     landed; say so). The export job can write the v1 file only once bak-02 exists:
     sequence it so bak-01 keeps today's YAML until bak-02 swaps it, or merge as you
     see fit.
   - `2026-11-20-bak-02-export.md` — export format v1, UI download (YAML/JSON), the
     scheduled export, management API route (+ MCP tool), API_REVISION handling.
   - `2026-11-20-bak-03-import-engine.md` — parse v1 + legacy v0, matcher, plan/apply,
     exhaustive tests; no UI.
   - `2026-11-20-bak-04-import-ui.md` — upload → mapping → preview → apply → summary,
     users import without passwords, management API + MCP plan/apply.
   - `2026-11-20-bak-05-staged-restore.md` — optional phase for the staged restore.
   The PRD gets a planned section (with revision row) in bak-01 and is marked delivered
   in the last phase built; `docs/FUTURE.md` "Backup contents and format" is removed
   when the work ships (say which phase does it).

## Conventions to honor

- Docs-only task: no CHANGELOG, no PRD, no edits to existing files.
- Don't invent features beyond the decisions; park extras in "Later".

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (untracked: plain `mv`).
3. You are a spawned agent: do **not** commit. Report back: file list, proposed message
   (`docs: backup, export and import design, mockup and build prompts`), a short design
   summary (backup settings + precedence, export format and ownership highlights,
   matching rules, plan/apply handoff, restore), the decisions you made (for the
   orchestrator to copy into `docs/decisions.md`), open questions, mockup path.
   Never `git add -A`, never push.
