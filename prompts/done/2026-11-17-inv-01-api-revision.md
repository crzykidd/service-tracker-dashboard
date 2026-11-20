---
name: 2026-11-17-inv-01-api-revision
status: completed        # pending | completed | failed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: api_version.py, headers, GET /api/v1/meta, whoami/OpenAPI/MCP revision, register UA logging, tests and docs done
---

# Task: Give the /api/v1 surface a real API revision

Build PRD §18.1. Producers (docker-api-notifier, inventory sidecars, the MCP
server) need to know which contract revision STD speaks, and to log it.

## Before you start

- Read `CLAUDE.md`, `standards.md`, PRD §18 (intro + §18.1), §20 (all), and the
  newest `docs/decisions.md` entries.
- Read `app.py` (factory, blueprints, `after_request` hooks), `routes_api.py`
  (register, `_check_bearer_auth`), `routes_mgmt_api.py` (`whoami`, error
  handling, JSON 404/405 for `/api/v1/*`), `mgmt_openapi.py` (`build_spec`,
  `OPERATIONS`), `mcp/std_mcp.py` (`server_info`), `version_check.py` /
  `read_version_info()`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **`api_version.py`** (new, in the CLAUDE.md module layout):
   - `API_REVISION = 2`;
   - `API_REVISION_HISTORY`: the §18.1 table as data;
   - `FEATURES = ("register", "management", "notifications", "streams")`.
     Note in a comment that `streams` is advertised from 0.10.0 even though the
     endpoints land in inv-04 of the same release.
2. **Headers:**
   - one app-level `after_request` that sets `X-STD-API-Revision` and
     `X-STD-Version` (bare semver from the version info) on every response whose
     path starts with `/api/`;
   - it covers errors too (400/401/403/404/405/503 from register and the
     management API) and must not break the CSRF exemption or the JSON error
     handlers.
3. **`GET /api/v1/meta`:**
   - unauthenticated, no DB access;
   - returns `{std_version, api_revision, features}`;
   - registered in `mgmt_openapi.OPERATIONS` (no security requirement on this
     operation) or wherever the completeness test expects it;
   - reachable without an admin key. Check that `require_api_key` isn't applied
     blueprint-wide.
4. **Revision in other outputs:** `whoami` adds `api_revision`; the OpenAPI
   `info` gets `x-api-revision`; the MCP `server_info` tool adds
   `std_api_revision`. Update `mgmt_schemas` TypedDicts.
5. **Register `User-Agent` logging:** log at INFO the first time each distinct
   `User-Agent` is seen on `/api/v1/register`. Use an in-memory set under a lock,
   capped at about 100 entries. Never log per request. Don't log the token.
6. **Tests:**
   - headers on success and error responses for register, the management API and
     `meta`;
   - `meta` without auth;
   - `whoami` and OpenAPI fields;
   - the once-per-UA log.
7. **Docs:**
   - CLAUDE.md "Register Contract Rules" gets one bullet: any additive
     `/api/v1` change bumps `API_REVISION` plus a row in the PRD §18.1 table, and
     breaking changes need `/api/v2`;
   - CLAUDE.md module layout gets `api_version.py`;
   - README Management API section documents the headers and `meta`;
   - CHANGELOG `[Unreleased]` Added entry.

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
