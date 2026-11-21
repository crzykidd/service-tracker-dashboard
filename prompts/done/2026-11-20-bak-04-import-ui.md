---
name: 2026-11-20-bak-04-import-ui
status: completed        # pending | completed | failed
created: 2026-11-20
model: sonnet
completed: 2026-11-20
result: Import UI (card, preview page with stream mapping, mode switch, tri-state groups, apply bar, summary), routes_import.py, users without passwords tag, old restore removed with its tests ported to the import flow, API import/plan + import/apply (revision 4 row extended, feature import), MCP import_plan/import_apply, docs. Decisions in docs/decisions.md (bak-04).
---

# Task: Backup phase 4: import UI (upload → mapping → preview → apply → summary), API + MCP

Put the bak-03 import engine in front of the operator: the Import card, the import
page with stream mapping, the grouped preview with the mode switch and the sticky apply
bar, the summary, users created without passwords, and the management API + MCP
plan/apply. Remove today's restore and "Save to server" path, because the new import
handles legacy files.

**Depends on:** bak-03 (`importer.py`, `export_format.from_legacy`), bak-01 (Backup
section), settings set-01 components.

## Before you start

- Read `CLAUDE.md` (Definition of Done, commit rules, management API module notes).
- Read the design doc: `docs/design/2026-11-20-backup-export-import.md` §6.1, §7.1–§7.8,
  §11 (the bak-04 rows), §12 (all), §14 Q1 (**answered no**: do not build an "adopt install id" row; `instance_id`
  stays informational in the header only) and
  §17. Open `docs/design/2026-11-20-backup-export-import-mockup.html` (`#import`,
  `#summary`) for the look.
- Read `docs/design/2026-11-20-settings-modernization.md` §6.8 (collapsible group +
  tri-state), §6.9 (sticky bar), §6.7 (confirm), §7 (flash policy).
- Code: `importer.py`, `export_format.py`, `backups.py`, `routes_dashboard.py` (the
  `settings()` `action=backup|restore` branches to remove, `_render_settings`, the
  restore listing), `templates/partials/settings/backup.html`,
  `templates/partials/settings/users.html`, `templates/settings.html`,
  `static/js/settings/ui.js`, `static/js/settings/backup.js`, `routes_mgmt_api.py`,
  `mgmt_openapi.py`, `mgmt_schemas.py`, `api_version.py`, `mcp/std_mcp.py`, the tests
  that exercise the old restore (`grep -rn "action.*restore\|restore_source\|backup_operation" tests/`).

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
(the files above, `static/css/dashboard.css`, `CHANGELOG.md`, `docs/PRD.md`,
`docs/FUTURE.md`, `README.md`, `CLAUDE.md`), list them and stop to ask. This file is exempt.

## What to do

1. **Routes** (admin + CSRF; Settings shell; every redirect via `_settings_redirect`):
   - `POST /settings/import`: an upload (`import_file`) or a server file
     (`server_file`, through `backups.resolve_file`); per-route 10 MB limit;
     `importer.parse` → `stage` → redirect to `/settings/import/<token>`. A parse error
     shows a banner in the Backup section's Import card.
   - `GET /settings/import/<token>`: `load` (another user's or an expired token →
     redirect with "This import expired. Upload the file again."), `plan(doc,
     stream_map)`, render `templates/settings_import.html` (the Settings shell with Data →
     Backup & restore current).
   - `POST /settings/import/<token>/map`: save `stream_map` into the staged file,
     re-render.
   - `POST /settings/import/<token>/apply`: build the `Selection` from the form fields
     of design §12.2 step 4 and call `importer.apply`. `ImportStale` → re-render the
     preview (409) with the stale banner and the operator's ticks kept where the rows
     still exist. `ImportError` → re-render with the error banner, nothing changed.
     Success → `discard(token)`, render the summary (200) and a toast.
   - `POST /settings/import/<token>/cancel`: discard, redirect to `backup`.
   - **Remove** the `action == 'backup'` and `action == 'restore'` branches of
     `settings()` and the `server_backup_files` listing, plus the legacy cards in
     `backup.html` (bak-01's "Import (legacy)"). Legacy files are imported through the new
     flow. Delete or rewrite the tests of the old restore. Each must become an
     import-flow test with the same intent (static scope → the lock rules; skipping live
     stream entries → *matched by key*; confinement → `resolve_file`). Do not just drop
     them.
2. **Templates:**
   - `partials/settings/backup.html`: the Import card (§12.1 card 4): drop zone / file
     input, the server-export select (exports + legacy files), **Preview import**. Each
     export / legacy row's ⋯ menu gets **Import…** (posts `server_file`).
   - `settings_import.html` (+ `partials/settings/import_rows.html` if it helps): the
     stepper, the file header and warnings, stream mapping (one row per file stream,
     `select.input-clean` limited to same-`key_type` local streams + Skip, status notes),
     the mode radio group, toolbar (search, status chips, Select all / none), the source
     groups with the `settings_group` macro and tri-state in the §12.2 order, rows with
     status pill, summary, per-field table (missing ticked; differs unticked and disabled
     in fill mode), ambiguous target select, the "Import as new" / "Create user (no
     password)" switch, row options (restore, soft-delete entry), the identical-count
     line, and the sticky apply bar with live counts plus **Cancel** / **Apply import**
     (a `data-confirm` when overwrite mode is chosen). Hidden `fingerprint` and `mode`.
     The summary card (§7.7) with "Still to do" and the two buttons.
   - `partials/settings/users.html`: a muted "No password set, cannot sign in" tag for
     users without a usable password (`User.has_password` or the sentinel check).
3. **JS** `static/js/settings/import.js` (row disclosure, greying of differs fields in
   fill mode, apply-bar counts, status-chip filtering, search). It reuses `ui.js` for
   groups and tri-state and confirm. The page must still post correctly without JS.
   Styles go in the existing "Settings & shared UI" block of `dashboard.css` (status
   pills, per-field table, segmented control, stepper, apply bar). No `:has()`.
4. **Management API:** `POST /import/plan` and `POST /import/apply` (write; request
   models in `mgmt_schemas.py` `extra="forbid"`: `document` (object) or `document_text`
   (str; YAML/JSON/legacy), `stream_map`, `selection`, `mode`, `fingerprint`), stateless
   (no staging), 409 + the fresh plan on `ImportStale`, 400 on parse errors, audited
   (`object_type="import"`, `changes` = counts only). Both in `mgmt_openapi.OPERATIONS`.
   Extend the revision-4 row text in `api_version.py` and the PRD §18.1 table with
   "import plan and apply" and add `"import"` to `FEATURES`. **No new revision number.**
5. **MCP:** write tools `import_plan(document_text, stream_map=None)` and
   `import_apply(document_text, stream_map, selection, mode, fingerprint)`. The docstring
   says to call `import_plan` first and show the operator the plan. Update `mcp/README.md`.

## Tests

- New `tests/test_import_ui.py`: upload → 302 to the token page; the page renders the
  groups in order with the right default ticks (missing ticked, differs / not-found /
  users unticked); an expired or foreign token; remap a stream and re-render; apply in
  fill mode writes only missing fields (and the summary lists "still to do"); overwrite
  mode with a ticked differs field; a stale apply → 409 with the banner and the ticks
  kept; a parse error → banner in `section-backup`; cancel deletes the staged file; a
  server-file import through `resolve_file` (confinement cases); a legacy v0 upload;
  users created without a password show the tag and cannot log in; the old
  `action=restore` POST no longer restores anything.
- API: plan / apply happy path, 409 stale, 400 parse error, read key → 403, the audit
  row (counts only), OpenAPI completeness, the revision row text and `FEATURES`.
- MCP tool tests.
- `pytest -q` and `ruff check .` pass.

## Docs (same commit)

- **CHANGELOG `[Unreleased]`:** Added: import of an export or an old YAML backup with
  stream mapping, a preview of every matched record and the settings it is missing,
  fill-missing (default) or overwrite mode, import as new, users imported without
  passwords, and the import API and MCP tools. Removed: the old Restore form and "Save
  backup to server" (use export and import). Note that old YAML backups import through the
  new flow.
- **PRD:** the planned section's backup, export and import parts → "Delivered
  (unreleased)". The staged-restore subsection stays "Planned (optional, bak-05)".
  Update §14 (management API routes), §18.1 (row text), the Settings section's Backup
  description, and the revision-history row.
- **`docs/FUTURE.md`:** remove "Backup contents and format". It is answered by this
  work. If an item from it is still open, move that item to the design doc's Later list.
- **README:** Backup & restore (export, import walkthrough = design §2 steps 3–7, what to
  redo), the API and MCP lists.
- **CLAUDE.md:** module layout (`templates/settings_import.html`,
  `static/js/settings/import.js` if the layout lists such files).

## Conventions to honor

- The engine's rules are bak-03's. Do not re-implement matching in routes or templates.
- No staged restore (bak-05). Nothing from design §15.
- Commit style: `feat:`. No `Co-authored-by:`. Docs in the same commit.
- Non-obvious calls → `docs/decisions.md` (heading "bak-04").

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (or `prompts/failed/`): `git mv` if tracked,
   otherwise plain `mv`.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.** Report
   back the file list, the proposed message `feat: import with stream mapping, preview,
   fill-missing or overwrite, users without passwords, import API and MCP (backup phase
   4)`, the test result, and a manual browser checklist (upload, mapping, groups and
   tri-state, mode switch, apply bar counts, stale banner, summary, phone width).
