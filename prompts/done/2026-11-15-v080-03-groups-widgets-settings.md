---
name: v080-03-groups-widgets-settings
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15      # filled when the work is done
result: groups, widgets, exposure settings and masked config endpoints with tests and docs # one-line summary of the outcome
---

# Task: Management API: groups, widgets, and runtime settings

Add the groups, widgets, exposure-settings and read-only config endpoints of
the management API. Spec: PRD §14.4. Depends on v080-02.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§14** (the v0.8.0 plan) in full, plus **§5.7**. The
  subsection named below is your spec. Where it and the code disagree, trust
  the code, follow the spirit of the PRD and record the call in
  `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.8.0 Management API design calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with tests.
- Code: `routes_mgmt_api.py`, `mgmt_schemas.py`, `entry_rules.py` (or
  whatever v080-02 named it), `routes_dashboard.py` (group add/update/delete
  handlers, the widget handling in `/edit/<id>` around `widget_api_key`, the
  detached-widget attach/delete routes, `/settings/exposure`),
  `routes_widgets.py` (the widget-type listing pattern from the CodeQL fix:
  build paths from `os.listdir`, never from request values), `widgets/*/settings.json`,
  `settings_store.py`, `settings_loader.py` and `models.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Groups:** list, create, patch and delete, with the same rules as the
   UI handlers. Refactor shared logic out of `routes_dashboard.py` if it's
   needed to avoid duplication. A duplicate name returns 409.
2. **Widgets:**
   - `GET /widgets/types` lists the plugins from `widgets/`, building paths
     from listdir entries only (keep the CodeQL-safe shape), with
     `available_fields`.
   - `GET /widgets` returns `widget_api_key_set`, never the key.
   - `PUT /entries/<id>/widget` validates the type and fields against the
     plugin's `available_fields`.
   - `DELETE /entries/<id>/widget` detaches by default; `?delete=true`
     deletes the widget and its values.
   - `DELETE /widgets/<id>` deletes a detached widget only; otherwise 409.
   - Audit with the key masked.
3. **Runtime settings:**
   - `GET /settings/exposure` returns the layer directions, per-host
     overrides, and discovered layers and hosts.
   - `PUT /settings/exposure` validates with `VALID_DIRECTIONS` and saves
     through `settings_store.save_exposure_settings`, the same path as the UI.
   - After saving, it triggers the same synthesizer recompute the UI does,
     if any.
4. **`GET /config`:**
   - Returns the effective `app.config` values from `settings_loader`'s
     known keys plus the version.
   - Masks `api_token`, `secret_key` and anything ending `_key`,
     `_token`, `_password` or `_secret`.
   - It is read-only.
5. **Tests:**
   - Group CRUD and 409.
   - Widget type listing (including that a traversal-ish type name in PUT
     returns 400).
   - Field validation.
   - The key is never returned and is masked in audit.
   - Detach versus delete semantics.
   - Exposure get/put round-trip, invalid direction → 400, and the result
     matches what the Settings UI shows.
   - Config masking.
   - Scope checks.
   - Audit rows.

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
   failure), renamed `2026-11-15-v080-03-groups-widgets-settings.md`.
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
