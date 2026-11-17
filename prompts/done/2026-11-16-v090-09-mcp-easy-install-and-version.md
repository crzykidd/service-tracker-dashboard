---
name: v090-09-mcp-easy-install-and-version
status: completed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: uv run header, whoami.version, startup version check, server_info; 755 passed, ruff clean
---

# Task: One-command MCP install (uv inline deps) and a version check against STD

Two operator requests for the stdio MCP server (`mcp/std_mcp.py`):

1. **Easier install.** No venv, and no copying `requirements.txt` around.
   Declare the dependencies inside the script (PEP 723 inline metadata) so
   `uv run std_mcp.py` (or `uv run <raw GitHub URL>`) just works.
2. **Version awareness.** Today the MCP server doesn't know its own version
   and never compares it with the STD it talks to. Claude should be told when
   the MCP script is older or newer than the STD instance, so it can say
   "update the MCP server" instead of failing on a tool that doesn't exist.

## Before you start

- `mcp/std_mcp.py` (startup, `StdClient`, `build_server`, the `whoami` probe,
  the FastMCP `instructions`), `mcp/README.md`, `mcp/requirements.in` and
  `mcp/requirements.txt` (pins), `requirements-dev.txt` (includes the MCP
  requirements for CI), and `tests/test_mcp_server.py`.
- `routes_mgmt_api.whoami` (returns name, prefix, scope) and how the app
  version is read (`current_app.config["VERSION_INFO"]["version"]`, used by
  `/config` and `openapi.json`), plus `mgmt_schemas` and `mgmt_openapi` for
  whoami.
- `.claude/commands/release-prep.md` Step 1 (bumps `VERSION`).
- `README.md`, the "Managing STD with Claude" / MCP section.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **PEP 723 header.** At the top of `mcp/std_mcp.py` add:
   ```python
   # /// script
   # requires-python = ">=3.10"
   # dependencies = ["mcp==<pin>", "httpx==<pin>"]
   # ///
   ```
   - Use the same pins as `mcp/requirements.in`.
   - Keep `requirements.in` and `requirements.txt`: CI and the dev install
     still use them.
   - Add a test that parses the header and asserts its dependencies equal
     the pins in `mcp/requirements.in`, so they can't drift.
   - Check that `uv run mcp/std_mcp.py` resolves. Run it with a dummy
     `STD_URL` pointing at a closed port and confirm it fails fast with the
     connection error message, not a dependency error. A failing whoami is
     expected.
   - If the sandbox has no network for uv to fetch packages, say so and rely
     on the test.

2. **`whoami` returns the STD version.** Add `"version": "<app version>"`
   to `GET /api/v1/whoami`, using the same source as `/config`. Update the
   response schema, OpenAPI and the tests. This is additive, so older MCP
   scripts ignore it.

3. **The MCP script knows its own version.**
   - Add `MCP_VERSION = "0.9.0"` near the top of `std_mcp.py`. Add a test
     asserting it equals the repo's `VERSION` file, so it can't silently
     drift.
   - Add a step to `.claude/commands/release-prep.md` Step 1: also set
     `MCP_VERSION` in `mcp/std_mcp.py` to the new version, and stage
     `mcp/std_mcp.py` in Step 7.
   - That file is tooling, so record the change in `docs/decisions.md`, not
     the CHANGELOG.

4. **Compare at startup.** After the whoami probe, read `version` (missing
   means older than 0.9.0) and compare it with `MCP_VERSION` as
   `MAJOR.MINOR.PATCH` integers. Treat anything that isn't plain semver,
   such as `dev`, as unknown.
   - **Same major.minor:** OK. A patch difference is OK; mention it only in
     the stderr line.
   - **STD newer:** it may have API features or tools this script lacks.
   - **STD older:** some tools may call endpoints that don't exist yet and
     return 404.
   - **Unknown:** say the version couldn't be determined.
   - When they differ:
     - write one stderr line, e.g.
       `std_mcp 0.9.0 talking to STD 0.10.1: update std_mcp.py (see mcp/README.md)`;
     - add one sentence to the FastMCP `instructions` telling Claude about
       the mismatch and to tell the operator to update the MCP server if a
       tool is missing or returns 404. Instructions reach the client at
       initialize, so Claude sees it without calling anything.
   - **Never refuse to start** because of a version mismatch.
   - Extend the existing startup line to include both versions:
     `connected to STD 0.9.0 as key 'name' (write); std_mcp 0.9.0`.

5. **A `server_info` read tool** (any key). It returns `{"mcp_version",
   "std_version", "status": "match" | "std_newer" | "std_older" |
   "unknown", "advice"}`, with no network call beyond what's cached from
   startup. Its docstring says to call it when a tool seems missing or the
   operator asks about versions. List it in `mcp/README.md`.

6. **Docs:**
   - `mcp/README.md`: rewrite Install around uv, recommended first.
     - **From a checkout:**
       `claude mcp add std -s user -e STD_URL=... -e STD_API_KEY=... -- uv run /abs/path/to/mcp/std_mcp.py`
     - **No checkout, pinned to a release:**
       `claude mcp add std -s user -e STD_URL=... -e STD_API_KEY=... -- uv run https://raw.githubusercontent.com/crzykidd/service-tracker-dashboard/v0.9.0/mcp/std_mcp.py`
     - Explain that updating means changing the tag in that URL, that
       pinning to a tag (not `main`) means the code only changes when you
       change it, and that uv caches the dependencies after the first run.
     - Keep the venv / pip path as an alternative for people without uv.
     - Add a Claude Desktop JSON example using `"command": "uv"` with
       `"args": ["run", "<path or URL>"]`. Note that Desktop may need the
       absolute path to `uv` (`which uv`), because GUI apps don't always see
       your shell PATH.
     - Add a "Versions" section: what the mismatch notice means and how to
       update.
   - `README.md`: update the MCP install snippet in the same way.
   - `CHANGELOG.md` `[Unreleased]`:
     - Added: "The MCP server installs with one command via `uv run` (no
       virtualenv needed) and warns when it is older or newer than your STD;
       new `server_info` tool."
     - Added: "`GET /api/v1/whoami` now includes the STD version."
   - `docs/PRD.md`:
     - §14.7 (MCP): add the version check and the uv install.
     - §14.2 or §14.3: add the whoami field.
     - Add a §15.7 entry and bump the revision history.

7. **Tests** (`tests/test_mcp_server.py` style, with a fake HTTP layer):
   - the version comparison for equal, patch-only difference, STD newer, STD
     older, missing version and a non-semver version;
   - the instructions contain the mismatch sentence only when there is a
     mismatch;
   - `server_info` output;
   - startup never fails on a mismatch;
   - the whoami `version` field via the API test client;
   - the header-pins test and the `MCP_VERSION == VERSION` test.

8. **Verify:**
   - `uvx ruff@0.15.17 check .`
   - The full suite on 3.11:
     `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back: what you built, test and lint results (exact
   counts), whether `uv run` was exercised for real, decisions, and the exact file
   list + a proposed one-line commit message (`feat:` prefix, no `Co-authored-by:`).
   Never `git add -A`, never push.
