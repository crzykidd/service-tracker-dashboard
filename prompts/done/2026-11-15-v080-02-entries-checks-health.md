---
name: v080-02-entries-checks-health
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15      # filled when the work is done
result: Shared validation (entry_rules.py, dict validators in check_form.py), mgmt_schemas/serializers, 13 entries/checks/health endpoints with tests; full suite green
---

# Task: Management API: entries, checks, and health

Implement the entries, checks and health endpoints of the management API,
including the shared validation refactor so the UI and API use one rule set.
Spec: PRD §14.3. Depends on v080-01.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§14** (the v0.8.0 plan) in full, plus **§5.7**. The
  subsection named below is your spec. Where it and the code disagree, trust
  the code, follow the spirit of the PRD and record the call in
  `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.8.0 Management API design calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with tests.
- Code: `routes_mgmt_api.py` and `api_keys.py` (from v080-01),
  `check_form.py`, `routes_dashboard.py` (the `/add` and `/edit/<id>`
  handlers, duplicate rules, delete/restore/purge handlers, `_UPSERT_LOCK`
  usage via `routes_api`), `models.py`, `health_state.py`,
  `health_history.py` (`entry_payload`), `view_helpers.py` (`matches_status`,
  `matches_source`), `jobs.py` (`request_run`), `synthesizer.py`
  (`SOURCE_UI_EDIT`), and `image_utils.py` (`safe_icon_filename`, icon fetch).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Shared validation:**
   - Refactor `check_form.py` so validation is plain functions over dicts
     (`validate_service_check(d)`, `validate_url_check_settings(d)`,
     `validate_container_check(d)`) that return normalized values or a list
     of `{field, message}` errors.
   - The form parser and the API both call them.
   - Do the same for entry-level rules: name, host, duplicate check, sort
     priority, icon. Pull them out of `routes_dashboard.py` into a small
     module, e.g. `entry_rules.py`, used by `/add`, `/edit` and the API.
   - The existing UI tests must still pass unchanged, apart from import
     paths.
2. **pydantic request models** (`extra="forbid"`) in a new `mgmt_schemas.py`
   (keep `schemas.py` for the register contract only): `EntryCreate`,
   `EntryPatch`, `ServiceCheckCreate`, `CheckPatch`. Response serializers are
   plain functions returning dicts; v080-04 builds OpenAPI from these models
   plus a route table, so keep response shapes in typed models or
   TypedDicts too.
3. **Endpoints**, per the §14.3 table:
   - Entry writes take `routes_api._UPSERT_LOCK`.
   - URL edits set `*_source = ui_edit`.
   - Notifier-owned fields in a PATCH return a 400 that names the fields.
   - Name and host are editable only on manual entries; otherwise 400.
   - Group by name creates the group if missing, like the UI.
   - Icons go through the same safe-name and fetch path as Add/Edit.
   - Deleting a URL or container check returns 409.
   - `?permanent=true` on a non-deleted entry returns 409.
   - Every write calls `audit(...)` with an old→new diff.
4. **`GET /health/summary`** returns:
   - counts `{total, passing, failing, unknown, stale}`, using the same
     definitions as the filter-bar chips and `matches_status`;
   - `failing`, a list of `{id, name, host, state, failures: [{check, kind,
     message, since}]}`, where `since` is the first failure in the current
     run of failures, derived from `consecutive_failures` and the result
     history.
5. **Query efficiency:** list endpoints eager-load checks (`selectinload`).
   Add a test that the query count stays flat between 3 and 30 entries.
6. **Tests:**
   - Every endpoint for both scopes (read key on a write endpoint → 403).
   - Validation errors per field.
   - Notifier-owned field rejection.
   - Manual-only name and host.
   - URL edit provenance: a later register must not overwrite it.
   - Duplicate 409.
   - Delete, restore and permanent delete rules.
   - Check add, patch and delete rules per kind.
   - Run-now queues the request.
   - The health payload matches the UI endpoint.
   - The summary counts match the filter-bar counts.
   - Audit rows with diffs.
   - Pagination.

## Conventions to honor

- Work on `dev`. Commit prefix `feat:`. No `Co-authored-by:` trailer. Never
  `git add -A`, never push.
- **Schema changes:**
  - Use one Alembic migration with a single head and write a downgrade.
  - Every FK gets its index in the same migration.
  - Run `alembic upgrade head` on an empty DB **and** on a DB at the
    previous head with seeded data.
  - Migration tests use the subprocess + temp `alembic.ini` pattern from
    `tests/test_health_schema.py`, because the real `alembic.ini` hardcodes
    `/config/services.db`.
- **Settings:** read them from `app.config`. New settings go in
  `settings_loader.py`, `settings.example.yml` and the README settings
  reference.
- **Register contract:** `schemas.py`'s `RegisterPayload` and
  `/api/v1/register` are untouched.
- **Never log or return a secret:** API key secrets after creation,
  `widget_api_key`, `api_token`, `secret_key`.
- **Definition of done, in the same commit:**
  - a CHANGELOG `[Unreleased]` entry in operator language;
  - the PRD subsection marked "— Delivered (unreleased)" with an "As
    built:" paragraph, plus a revision row at the bottom of the table;
  - README updated where operator-facing behaviour changes;
  - the CLAUDE.md module layout updated for new files;
  - `docs/decisions.md` for any non-obvious call.
- **Before handing off, run:**
  - `uvx ruff@0.15.17 check .`
  - `pytest -q` from the venv at `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`, which has requirements-dev,
    icmplib and Playwright with cached Chromium
  - `alembic upgrade head` on a fresh scratch DB

  Report results verbatim if anything fails. Scratch files go in that
  scratchpad, not the repo.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed `2026-11-15-v080-02-entries-checks-health.md`.
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
