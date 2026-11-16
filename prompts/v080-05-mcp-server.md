---
name: v080-05-mcp-server
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: MCP server for managing STD from Claude

Add a small stdio MCP server, outside the Docker image, that wraps the
management REST API as tools so Claude Code can manage an STD instance. Spec:
PRD §14.7. Depends on v080-04.

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§14** (the v0.8.0 plan) in full, plus **§5.7**. The
  subsection named below is your spec. Where it and the code disagree, trust
  the code, follow the spirit of the PRD and record the call in
  `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.8.0 Management API design calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with tests.
- Code: the management API (`routes_mgmt_api.py`, `/api/v1/openapi.json`,
  `/api/v1/whoami`), the README "Management API" and "Managing STD with
  Claude" sections, `.dockerignore` and `Dockerfile` (make sure `mcp/` is
  **not** copied into the image), and `.github/workflows/ci.yml` (the lint
  and test jobs).
- Read the official MCP Python SDK docs (the `mcp` package, FastMCP stdio
  server) for the current API. Pin a version that is at least two weeks
  old.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **`mcp/std_mcp.py`** (FastMCP, stdio):
   - Configured by the env vars `STD_URL` and `STD_API_KEY`, with an
     optional `STD_VERIFY_TLS` (default true) and a timeout.
   - Uses `httpx` or `requests` against the REST API only.
   - At startup it calls `/api/v1/whoami`. With a `read` key it registers
     only the read tools.
   - Tools, as typed thin wrappers (§14.7 list): `list_entries`,
     `get_entry`, `health_summary`, `get_health_history`,
     `create_manual_entry`, `update_entry`, `delete_entry`,
     `restore_entry`, `add_check`, `update_check`, `delete_check`,
     `run_checks`, `list_groups`, `upsert_group`, `list_widgets`,
     `set_widget`, `get_exposure_settings`, `set_exposure_settings`,
     `get_config`.
   - Each tool has a clear description, with examples where useful (body
     mode `OK` / `Error: <msg>`; manual vs notifier entries).
   - API errors are returned as readable tool errors that keep the API's
     `details`.
2. **Packaging:**
   - `mcp/requirements.txt`, pinned.
   - `mcp/README.md` covering install (`uv` or `pip`), and
     `claude mcp add std -e STD_URL=... -e STD_API_KEY=... -- python
     /path/to/mcp/std_mcp.py` (verify the exact `claude mcp add` syntax
     against current Claude Code docs).
   - `mcp/` is excluded from the Docker build context or image.
3. **Tests** (`tests/test_mcp_server.py`, or `mcp/tests` wired into the CI
   `Test` job):
   - Each tool maps to the right method, path and body against a fake HTTP
     transport (no network).
   - Read-key gating.
   - Error mapping.
   - Every write tool's endpoint exists in `/api/v1/openapi.json`, which you
     can load from the Flask test client.
   - Add the MCP deps to `requirements-dev.txt` only if CI needs them; keep
     them out of the runtime `requirements.txt`.
4. **Smoke test:**
   - Run STD locally with a scratch config, create a write key, start the
     MCP server, and drive it with the SDK's client (or a minimal stdio
     client) to list entries, add a manual site with a body-mode check, and
     read `health_summary`.
   - Report the transcript summary.
5. **Docs:**
   - Fill in the README "Managing STD with Claude" placeholder.
   - CHANGELOG `[Unreleased]`.
   - PRD §14.7 delivered, plus a revision row.
   - Since this is the last chunk, tick §14's status line to "all chunks
     delivered (unreleased)". Do **not** run `/release-prep`.
   - Update the CLAUDE.md module layout and Build Status in-flight line
     ("v0.8.0 … fully built on `dev`; awaiting `/release-prep 0.8.0`").

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
   failure), renamed `2026-11-15-v080-05-mcp-server.md`.
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
