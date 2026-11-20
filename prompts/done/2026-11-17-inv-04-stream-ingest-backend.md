---
name: 2026-11-17-inv-04-stream-ingest-backend
status: completed        # pending | completed | failed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: Streams backend delivered on dev: migration f4c8a2e6d173, ingest scope and contract, streams.py apply engine and lifecycle, management routes, MCP tools, tests, docs. Not committed.
---

# Task: Inventory streams backend — schema, ingest contract, apply, lifecycle

Build PRD §18.4–§18.7: everything behind the stream ingest API except the
Settings UI (inv-05). The PRD §18.5 contract is what the `std-source-technitium`
sidecar is being written against in parallel, so implement it **exactly**. If
something in it can't work, stop and report rather than changing it silently.

## Before you start

- inv-03 must be completed. If it isn't, stop and report.
- Read `CLAUDE.md`, PRD §5.6–§5.9, §12.5 (soft delete), §14 (management API),
  §17.3, §18 (all), §20.3, and design doc
  `docs/design/2026-11-17-network-inventory-and-profiles.md` §5, §6, §12.
- Read `api_keys.py` (scopes, `scope_allows`), `routes_mgmt_api.py`
  (`require_api_key`, `json_error`, audit hook, entry delete), `mgmt_openapi.py`,
  `mgmt_schemas.py`, `mgmt_serializers.py`, `routes_api.py`
  (`upsert_service`, `_UPSERT_LOCK`), `models.py` (`hard_delete_entry`,
  `ServiceEntry.active()`), `notify_state.py` (`entry_payload`,
  `_ENTRY_ATTRS`), `notify_ha.py`, `entry_rules.py` (`find_duplicate`),
  `mcp/std_mcp.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Migration and models** (§18.4):
   - `inventory_stream`, `inventory_block` and `stream_link_offer` tables;
   - the new `service_entry` columns and the partial unique index;
   - `stream` added to `VALID_SOURCES`;
   - `ingest` added to `api_keys.SCOPES`. `scope_allows("ingest", "read"|"write")`
     must be false;
   - add §5.10 to the PRD.
2. **Ingest routes** (§18.5), on the management blueprint or a small sibling
   blueprint, CSRF-exempt:
   - `PUT /api/v1/streams/<stream_id>/snapshot` and
     `GET /api/v1/streams/<stream_id>/status`;
   - auth: an `ingest` or `write` key, with the stream bound to its creating key;
   - pydantic models with `extra="forbid"`, every limit in the table;
   - MAC normalisation as a shared helper with tests for each accepted form;
   - check the body size before parsing (413);
   - status codes and bodies exactly as the §18.5 response table;
   - snapshot PUTs skip the audit hook;
   - register both routes in `OPERATIONS`.
3. **Apply engine** (§18.6), in a new module (e.g. `streams.py`; add it to the
   CLAUDE.md module layout):
   - a pure-ish `plan(stream, items)` that returns per-item actions and counts,
     used by Preview;
   - `apply(stream, items)` that executes the plan in one transaction under a
     module lock;
   - stream entries skip `find_duplicate` and the restore clash checks;
   - register adoption must never touch `source = stream` rows. Add a test;
   - keep it to a few queries at 5,000 items: load existing rows, blocks and
     offers once, diff in Python;
   - add the notify payload and attrs changes and the HA `model` string.
4. **Lifecycle** (§18.7), as plain functions in `streams.py` used by both the
   management API and (later) the UI:
   - enable (applies the stored snapshot), disable and delete with `cleanup` and
     `clear_blocks`, ignore;
   - update the display name and filters;
   - list and unblock blocks;
   - list, accept and decline link offers, and link by hand;
   - entry delete with `block`;
   - rename sets `name_source = ui_edit`;
   - cleanup reuses soft delete and `hard_delete_entry`, with one commit per
     action;
   - management routes (read or write scope), `OPERATIONS` entries, response
     TypedDicts, serializers, audit for status changes, cleanups, unblocks and
     link answers;
   - MCP tools.
5. **Tests**, with a fixture snapshot (e.g. `tests/fixtures/stream_snapshot.json`,
   about 10 items with a duplicate-name case and a manual-entry match). Cover:
   - every §18.5 status code;
   - key binding;
   - the `ingest` key rejected on other routes;
   - pending → enable applying the stored snapshot;
   - each apply rule (filter, blocked, update, restore, offer, create, missing);
   - name provenance;
   - each cleanup option, including delete with `keep` turning entries manual;
   - block and unblock;
   - accept and decline;
   - MQTT payload fields;
   - API revision headers on the new routes.
6. **Docs:**
   - PRD §18.4–§18.7 marked delivered with "As built" notes;
   - §5.10 and §3.1;
   - CLAUDE.md module layout plus a Register Contract-style bullet list for the
     ingest contract (STD owns it, `extra="forbid"`, attributes uninterpreted,
     new core fields optional);
   - README: a short curl example of a snapshot PUT (the full section comes in
     inv-05);
   - CHANGELOG Added entry (operator language: "Inventory streams: sidecars can
     push device lists into STD; new streams wait for approval…").

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
