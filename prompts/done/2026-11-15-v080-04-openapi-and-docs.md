---
name: v080-04-openapi-and-docs
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: OpenAPI 3.1 spec from a route registry, Settings audit log view, README Management API + Claude sections, JSON 404/405 for API clients; suite green on 3.11 and 3.14
---

# Task: OpenAPI spec, audit-log view, and API docs

Generate an OpenAPI 3.1 document for the management API, add the audit-log
view to Settings → API, and document the API in the README. Spec: PRD §14.5
and the Settings view in §14.6. Depends on v080-03.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§14** (the v0.8.0 plan) in full, plus **§5.7**. The
  subsection named below is your spec. Where it and the code disagree, trust
  the code, follow the spirit of the PRD and record the call in
  `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.8.0 Management API design calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with tests.
- Code: `routes_mgmt_api.py`, `mgmt_schemas.py`, the Settings → API tab from
  v080-01, the `ApiAudit` model, and the README.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **`GET /api/v1/openapi.json`** (no auth):
   - Build it from a single **route registry**: each management endpoint is
     declared once with method, path, scope, summary, request model,
     response model and query params, and the spec is generated from that
     plus pydantic's `model_json_schema()`.
   - Include the `bearerAuth` security scheme and per-operation scope notes.
   - Don't add a heavy dependency (no flask-smorest or apispec unless it is
     clearly simpler; record the call).
   - Tests:
     - every rule in the management blueprint appears in the spec, so a
       future route can't be forgotten;
     - the document validates as OpenAPI 3.1 structurally (at least
       `openapi`, `info`, `paths` and `components`, and that every `$ref`
       resolves);
     - `/api/v1/register` is **not** in this spec.
2. **Audit view** in Settings → API: the most recent 200 rows (time, key
   name, method, path, object, status, changes), with a filter by key.
   Changes are rendered escaped and secrets stay masked.
3. **README "Management API" section:**
   - creating a key and choosing a scope;
   - the auth header;
   - an endpoint table that matches the spec;
   - curl examples: list failing services via `/health/summary`, add a
     manual site with an HTTP body-mode check, disable a check, move an
     entry to a group, attach a widget;
   - error format, pagination, the audit log, and the fact that the
     notifier's `api_token` is register-only.
4. **README "Managing STD with Claude":** a short how-to. Create a write
   key, give Claude the base URL and key (or use the MCP server from
   v080-05; leave a placeholder sentence that v080-05 fills in), and
   example asks.
5. **Browser check:** with headless Chromium, load Settings → API with some
   audit rows and read the screenshot.
6. **Tests:**
   - Spec completeness and `$ref` resolution.
   - Audit view rendering, the filter, and that it requires admin.
   - XSS escaping of `changes`.

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
   failure), renamed `2026-11-15-v080-04-openapi-and-docs.md`.
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
