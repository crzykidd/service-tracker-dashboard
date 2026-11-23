---
name: 2026-11-23-mcp-sdk-2x-upgrade
status: completed
created: 2026-11-23
model: sonnet
completed: 2026-11-23
result: MCP server ported to mcp 2.3.0 (MCPServer); 1994 tests pass, ruff and pip-audit clean; stdio smoke test OK. Not committed.
---

# Task: Port the STD MCP server (`mcp/std_mcp.py`) to the `mcp` Python SDK 2.x

Dependabot PR #93 bumps `mcp` from **1.30.0** to **2.3.0** in `mcp/requirements.in` and
`mcp/requirements.txt`. That is a major release of the MCP Python SDK, and it is on hold:
merging a bare version bump would break the server. This task does the real upgrade in
one commit on `dev`, and **replaces #93**. Don't merge #93; the orchestrator closes it
after your commit lands.

The MCP server runs on the operator's machine, not in the STD image (`.dockerignore`
excludes `mcp/`). Its tools are a plain HTTP client of STD's management API (`/api/v1`).
**Its tool names, arguments, results and behavior must not change**; only the SDK
underneath it changes.

## Before you start

- **Read:**
  - `CLAUDE.md` (Module Layout: `mcp/` has no `__init__.py`, because a package named
    `mcp` would shadow the SDK);
  - `mcp/README.md`, `mcp/std_mcp.py` and `tests/test_mcp_server.py`;
  - PRD §14.7 / §15.7 (the "As built" notes on the MCP server).
- **What 1.30 code we use:**
  - `from mcp.server.fastmcp import FastMCP` and `...fastmcp.exceptions import ToolError`
    (`std_mcp.py` ~L37-38);
  - `FastMCP(...)` in `build_server` (~L306);
  - `server.tool()` decorators via `read_tool` / `write_tool` (~L320);
  - the PEP 723 header (`# dependencies = ["mcp==1.30.0", "httpx==0.28.1"]`, L2-5), which
    is how operators run it with `uv run`.
- **The tests call SDK internals:** `asyncio.run(server.call_tool(name, args))` and
  `server.list_tools()` (`tests/test_mcp_server.py` ~L181-208, L551, L667). They also run
  a flow against the real app through `httpx.WSGITransport`.
- **Read the SDK's own migration notes before changing anything.** The 2.3.0 notes in
  PR #93 (`gh pr view 93`) already show 2.x naming the server class `MCPServer` and
  depending on **`httpx2`**. Read the release notes for **2.0.0** (the breaking
  release), then 2.1, 2.2 and 2.3, plus the migration guide at
  https://py.sdk.modelcontextprotocol.io/. Don't guess the new API from memory.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Dependencies.** Set `mcp==2.3.0` (or the newest 2.x) in `mcp/requirements.in`.
   - **`httpx`:** 2.x may depend on `httpx2` instead of `httpx`. Decide whether
     `std_mcp.py` should keep using `httpx` (STD's client, `StdClient`) or move to what
     the SDK uses.
     - Keep the client code working either way.
     - Note that `tests/test_mcp_server.py` uses `httpx.MockTransport` and
       `httpx.WSGITransport`.
     - Record the choice in `docs/decisions.md`.
   - **Shared packages:** re-lock with
     `uvx uv pip compile --python-version 3.11 mcp/requirements.in -c requirements.txt -o mcp/requirements.txt`.
     - The `-c requirements.txt` constraint keeps shared packages (pydantic, anyio,
       starlette, …) on the versions the app pins, so CI can install both files
       together.
     - If 2.x needs a newer shared package than the app pins, **stop and report**.
       Bumping app dependencies is a separate decision.
   - **PEP 723 header:** update it in `std_mcp.py` to the same pins.
2. **Port the code** to the 2.x server API: the class, the imports, the tool
   registration, `ToolError` (or its 2.x replacement), and `server.run()` over stdio.
   - Keep the same server name and instructions text, and the version-notice logic.
   - Keep the read/write scope gating (a read key registers read tools only).
   - Keep every tool's name, docstring, signature and return shape. The test suite
     already checks each tool's method and path against `/api/v1/openapi.json`, so it
     will catch drift.
3. **Port the tests** to whatever 2.x offers for calling and listing tools. Prefer a
   public API, e.g. an in-process `Client(server)`, if 2.x has one, over private
   internals.
   - The existing assertions must keep their meaning: the tool set per scope, the error
     mapping (`HTTP <status> (<meaning>): <error>` plus `details`), each tool's method
     and path, and the real-app flow.
   - Don't weaken an assertion to make it pass.
4. **Smoke-test the real thing.**
   - Start the server over stdio against a running STD: a local container is fine
     (`docker run` the `:dev` image, create an admin API key through the UI or the
     management API).
   - Then drive it with the SDK's own stdio client, or `uv run` the script.
   - Check that `initialize`, `tools/list` and one read tool (`server_info`) work, and
     that a write tool is refused with a read key.
   - Clients today, such as Claude Code, may still speak an older protocol revision than
     2.x's newest. Confirm that 2.x still negotiates an older protocol version, and say
     which versions you saw.
5. **Docs, all in the same commit:**
   - **CHANGELOG `[Unreleased]` → Changed:** "The MCP server (`mcp/std_mcp.py`) now
     uses the MCP Python SDK 2.x. Tools are unchanged. If you run it with `uv run`, the
     next run fetches the new dependencies; if you installed `mcp/requirements.txt`
     into a virtualenv yourself, reinstall it."
   - **`mcp/README.md`:** versions and any changed run instructions.
   - **PRD §14.7 "As built":** the SDK version, and a revision-history row.
   - **`docs/decisions.md`:** the httpx/httpx2 choice, and anything non-obvious from the
     port.
6. **Verify:**
   - `uvx ruff@0.15.17 check .` is clean;
   - `uvx --with-requirements requirements-dev.txt pytest -q` passes in full, with
     `tests/test_mcp_server.py` included and not skipped;
   - `uvx pip-audit -r requirements-dev.txt` is clean.

## Conventions to honor

- No change to STD itself: the app, the API or the image. If you find one is needed,
  stop and report.
- Write host checks as `urlsplit(url).hostname == ...` (CodeQL).
- Commit prefix `chore:` (or `feat:` if operators get something new). No
  `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `mv` it (it's untracked) into `prompts/done/` or `prompts/failed/`.
3. **You are a spawned agent: do not commit.** Report back:
   - the file list;
   - a proposed one-line message (e.g. `chore: port the MCP server to the mcp SDK 2.x
     (replaces dependabot #93)`);
   - the lint, test and pip-audit results;
   - the smoke-test result, with the protocol versions seen;
   - every deviation, including any shared-package conflict you stopped on.
