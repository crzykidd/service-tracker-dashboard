---
name: 2026-11-19-inv-07-linked-entries-unlink
status: completed
created: 2026-11-19
model: sonnet
completed: 2026-11-19
result: Linked stream entries are unlinked, never deleted, by cleanup; unlink on edit page, API and MCP; migration b4e7a1c9d325; docs updated; lint and tests green.
---

# Task: linked stream entries are unlinked, never deleted, by stream cleanup (0.10.0)

Operator decision (2026-11-19): an entry that was a manual entry and was linked
to a stream (Convert / accept offer / "Link to stream item…" / `POST .../link`)
belongs to the operator. Stream cleanup must **unlink** it (back to manual),
never soft-delete or purge it. Entries the stream created itself keep today's
cleanup behavior. Disable with `keep` stays as is (linked and own entries stay
attached and keep publishing to MQTT/HA).

## Before you start

- Read `CLAUDE.md` (Inventory Stream Ingest Rules, Database Rules), `standards.md`,
  `docs/PRD.md` §5.10 and §18.6–§18.8 (incl. "As built"), newest
  `docs/decisions.md` entries (inv-06 matching, notif-06).
- Key code: `streams.py` (`_convert`, `accept_offer`, `link_entry`,
  `_become_manual`, `_cleanup_entries`, `disable`, `delete`, `customised_entries`,
  `soft_delete_entry`, blocks), `models.py` (`ServiceEntry`), `routes_dashboard.py`
  (stream + edit routes), `routes_mgmt_api.py`, `mgmt_schemas.py`,
  `mgmt_serializers.py`, `mgmt_openapi.py`, `mcp/std_mcp.py`,
  `templates/edit_entry.html`, `templates/partials/settings_streams.html`
  (Disable…/Delete… dialog), `templates/partials/delete_popover.html` (pattern).
- Lint: `uvx ruff@0.15.17 check .` Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.

## Working tree check

Run `git status --porcelain`; the tree should be clean except this file. Anything
else touching the files below — list it and stop and report back.

## What to do

1. **Schema (Alembic).** On `service_entry`: `stream_linked` Boolean NOT NULL
   default false (server_default), `pre_link_host` String(100) nullable. No FK.
   **Backfill heuristic** for entries linked before this migration (there is no
   created timestamp): for each stream, a stream entry with
   `name_source = 'ui_edit'` whose `id` is lower than the smallest id of that
   stream's entries with `name_source = 'stream'` is marked `stream_linked = true`
   (host unknown → `pre_link_host` NULL). Document the heuristic in the migration
   docstring and `docs/decisions.md`.
2. **Set on link.** `_convert` (used by accept / link) sets `stream_linked = True`
   and `pre_link_host = entry.host` before clearing host.
3. **Unlink helper.** `unlink_entry(entry, block=False)`: `_become_manual` plus
   restore `host = pre_link_host`, clear `stream_linked` / `pre_link_host`;
   `block=True` adds the item key to the stream's block list (so the next
   snapshot doesn't re-create or re-offer it); `block=False` means the next
   snapshot may offer the link again (it will, via matching). Under `_LOCK`.
   Works on any stream entry (linked or stream-created) — for a stream-created
   entry it just becomes manual. Check the restored `(host, container_name)`
   against `find_duplicate` / the logical-key rule; on clash keep host NULL and
   say so in the result.
4. **Cleanup respects linked entries.** In `_cleanup_entries` (disable and
   delete), for `soft_delete` and `purge`: linked entries are **unlinked**
   (`unlink_entry`, no block) instead of deleted; counts gain `unlinked`. `delete`
   with `keep` already makes everything manual — linked ones also get their host
   restored. Disable `keep`: unchanged. The Disable…/Delete… dialog shows the
   linked count and says "N linked entries go back to manual entries (with their
   host); they are never deleted." `customised_entries` / counts used by the
   dialog include it.
5. **UI: Unlink on the edit page** of a stream entry (stream info box): button
   with a popover like delete — "Allow re-offering" vs "Don't re-add" (block).
   Linked entries show "Linked from a manual entry" in the stream info box.
6. **API + MCP parity (required).** `POST /api/v1/entries/<id>/unlink` (body
   `{"block": bool}`, `extra="forbid"`, write scope, audited) registered in
   `mgmt_openapi.py`; entry `inventory` object gains `linked: bool`; stream
   disable/delete responses gain `unlinked`. MCP tool `unlink_entry`, updated
   descriptions for disable/delete; `mcp/README.md`.
7. **MQTT/HA:** an unlinked entry keeps its id, so topics don't move; the commit
   listener sync updates its payload (`source`, `stream`). Confirm with a test
   that its HA device moves back from the stream hub device to the STD hub
   (`via_device`).
8. **Tests:** migration backfill heuristic; link sets flags; unlink restores host
   (and the clash case); block vs no block on next snapshot (blocked vs link
   offer); disable/delete in each mode with a mix of linked and own entries
   (linked never deleted, counts); API route + OpenAPI registry; MCP tool; HA
   `via_device` after unlink.
9. **Docs:** CHANGELOG `[Unreleased]` (operator language); PRD §5.10 schema,
   §18.7 lifecycle, §18.8 UI, revision row; README if the stream section covers
   cleanup; `docs/decisions.md` (linked entries are the operator's; backfill
   heuristic; unlink restores host).

## Conventions to honor

- Stream ingest contract unchanged (no `/api/v1/streams/<id>/snapshot` change).
- Register adoption / restore clash rules: stream entries still excluded; an
  unlinked entry is a normal manual entry again.
- Migration passes the CI Migration check.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move it into `prompts/done/` (or `prompts/failed/`) with plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Run lint + tests, report back the
   file list, results, doc contradictions, deviations, and a proposed one-line
   message (`feat: ...`).
