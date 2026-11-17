---
name: v090-08-rollup-and-http-messages
status: completed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: Roll-up fixed (container no longer softens failing URL/service checks); status-mode HTTP failures carry the reply reason; 735 tests pass, ruff clean.
---

# Task: Container check no longer softens a failing service; HTTP failures say why

Two fixes came out of a negative test at Emmett. `technitium-dhcp-sync`'s
`/healthz` returned 503 with the JSON
`{"status":"Error","last_error":"Mgmt1: Scope 'Mgmt1' not found on destination ...","failing_scopes":["Mgmt","Mgmt1"]}`.
STD showed the check as Down with the message `503`, and the entry badge as
**Degraded**, because the Container check still passed.

## Before you start

- `health_state.py`: `entry_health` (the single roll-up; check that the badge,
  status filter, Total/Passing/Failing counts (`view_helpers.health_counts`),
  `/health/summary` and the management API all go through it, with
  `grep -rn "entry_health\|STATE_DEGRADED\|STATE_DOWN" .`), and
  `check_counts`.
- `checker.probe_http`, which now wraps `_probe_http_request` plus the cert
  condition from v090-02. Also `_read_body`, `_error_text`, `BODY_READ_LIMIT`
  and `MESSAGE_COLUMN_LIMIT`.
- `docs/PRD.md` §13.1, §13.4 and §13.6.
- The existing tests for health_state and checker.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

### 1. Roll-up rule

The Container check (`kind == container`) counts on its own; the other checks
(URL and service: http, tcp, ping, dns) are judged as a group. Among the
checks that count and have run:

- No checks counting: `none`, as today.
- Checks counting but none has run: `unknown`, as today.
- **Container failing** → `down`.
- Otherwise, if any URL or service check is failing:
  - all URL and service checks that have run are failing → `down`, **even if
    the Container check passes**;
  - some pass and some fail → `degraded`.
- Otherwise → `up`. Checks still waiting for their first run don't hold the
  state back, as today.
- An entry with **only** a Container check keeps today's behaviour: up when
  it passes, down when it fails.
- Failures, counts and the tooltip are unchanged.

Update the `entry_health` docstring. Make sure every consumer picks this up
without its own logic: the badge, the status filter (`failing` and so on),
the header counts, `/health/summary` `state` and its counts, the
`GET /entries` `health` field, and the MCP (which only reads the API). Remove
any duplicate rule you find.

Tests:
- container up and the only URL check failing → down;
- container up, two URL or service checks, one failing → degraded;
- container down, URL checks passing → down;
- container down and nothing else → down; container up only → up;
- a URL check failing with a second service check not yet run → down,
  because every check that has run in the group is failing;
- the status filter and header counts reflect the new state (one
  route-level test);
- `/api/v1/health/summary` reports `down` for the first case.

Fix any existing test that encoded the old "container softens it"
behaviour, and list those tests in your report.

### 2. Failure message for non-2xx replies (status mode)

When an HTTP check in **status** mode fails on its status code (≥400 today;
keep the existing threshold and note it), build the message from the body:

- Read at most `BODY_READ_LIMIT` (4 KB) of the body, as body mode does. That
  means `stream=True` is needed in status mode too. Only read the body when
  the status code is failing, and always close the response.
- If the body parses as JSON and is an object, use the first non-empty
  **string** among `last_error`, `error`, `message` and `detail`. If `error`
  is itself an object with a string `message`, use that.
- If it is JSON but no such key exists, fall back to the raw body text.
- Otherwise, for a text body, use the first non-empty line.
- Format it as `"<code>: <text>"`. Collapse whitespace runs to one space,
  trim, and limit the text so the whole message is at most ~200 characters,
  with `…` when cut. It must also stay within `MESSAGE_COLUMN_LIMIT`.
- Keep just `"503"` when the body is empty, only whitespace, or binary (fails
  to decode as UTF-8, or more than ~10% control characters).
- Body mode is unchanged: it already uses `Error: <msg>`.
- With the cert condition from v090-02, an HTTP failure keeps this richer
  message.
- Status codes below 400 are unaffected, and their body is not read.

The same text then appears everywhere `last_message` and
`HealthResult.message` are used: the detail panel, recent failures, the
badge tooltip, `/health/summary` and the MCP. Check that nothing
re-truncates it to the bare code.

Tests (mock `requests.get` the way the existing checker tests do):
- the exact Emmett JSON gives `503: Mgmt1: Scope 'Mgmt1' not found on destination ...`;
- `{"error": "boom"}`, `{"error": {"message": "nested"}}` and
  `{"detail": "x"}`;
- JSON without those keys falls back to the raw body;
- plain text with several lines uses the first non-empty line;
- an empty body gives `503`;
- a binary body gives `503`;
- a large body, or one longer than 4 KB, never reads past the limit and the
  message is ≤ 200 characters with `…`;
- whitespace collapses;
- a 200 response does not read the body;
- body mode is unchanged (existing tests still pass);
- the cert condition plus an HTTP failure keeps the HTTP message.

### 3. Docs (same commit)

- `CHANGELOG.md` `[Unreleased]` → Changed:
  - "An entry whose URL/service checks are all failing now shows Down even
    when its container is running (it used to show Degraded)."
  - "HTTP check failures now include the reason from the response, e.g. `503:
    Scope 'Mgmt1' not found`, instead of just the status code."
- `README.md`: the health-states and check descriptions, wherever they define
  Degraded or Down or describe the failure message.
- `docs/PRD.md`: update §13.1 and §13.6 (roll-up) and §13.4 (status-mode
  message), add a short §15.6 entry for this chunk, and bump the revision
  history.
- `mcp/std_mcp.py` docstrings: only if they describe the states.

### 4. Verify

- `uvx ruff@0.15.17 check .`
- The full suite on 3.11:
  `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
  (714 passed before this change).

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It's untracked: plain `mv`.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Do **not** commit. Report back: what you built, test and lint results (exact
   counts), changed existing tests, decisions, and the exact file list + a proposed
   one-line commit message (`fix:` prefix, no `Co-authored-by:`). Never `git add -A`,
   never push.
