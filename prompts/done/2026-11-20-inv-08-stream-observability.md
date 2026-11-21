---
name: 2026-11-20-inv-08-stream-observability
status: completed        # pending | completed | failed
created: 2026-11-20
model: opus
completed: 2026-11-20
result: Stream observability shipped on dev (API revision 3, migration c6f2a8d4e157) - rejected snapshots, staleness (grace 2x, operator > producer > 15 min), health_summary streams/stale_streams, MQTT stale + HA problem sensor, missing badge/since + optional per-stream auto soft-delete with human-edit exemptions, IP-following checks (templating rejected), MCP server_info re-check; lint clean, 1343 tests pass, migration check OK.
---

# Task: make inventory streams observable (stale producers, missing records, IP-following checks, MCP version)

A dead producer or a removed record must not go unnoticed. First producer:
technitium-sync, stream_id `technitium-dhcp`, full snapshot every 5 min. Target:
next release after 0.10.0 (work on `dev`; CHANGELOG `[Unreleased]`).

## Before you start

- Read `CLAUDE.md` (Definition of Done, Inventory Stream Ingest Rules, Register
  Contract Rules, Database Rules), `standards.md`, `docs/PRD.md` §13 (health
  rollup), §17 (MQTT/HA), §18 (all, incl. "As built"), and `docs/decisions.md`
  newest first.
- Key code: `streams.py`, `models.py` (`InventoryStream`, `ServiceEntry`,
  `HealthCheck`), `health_state.py`, `jobs.py`, `checker.py`, `check_form.py`,
  `notify_state.py`, `notify_ha.py`, `routes_mgmt_api.py` (snapshot PUT + stream
  routes), `mgmt_schemas.py`, `mgmt_serializers.py`, `mgmt_openapi.py`,
  `api_version.py`, `mcp/std_mcp.py`, `templates/partials/settings_streams.html`,
  the views and the health detail panel.
- Lint: `uvx ruff@0.15.17 check .` Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.
  Migration check: see `.claude/commands/release-prep.md` Step 6.4.

## What already exists (verified 2026-11-20; don't rebuild)

- `inventory_stream.last_snapshot_at`, `last_applied_at`, `last_item_count`,
  `last_counts`, `last_error` (String 255). `last_error` is only set by
  `_record_failure` (apply exceptions), **not** for rejected payloads (400/409
  from the PUT).
- Settings → Streams shows last snapshot time and counts; `GET /api/v1/streams`
  (+ `pending`), `GET /api/v1/streams/{id}`, and MCP `list_streams`,
  `get_stream`, `preview_stream` exist.
- Retained `<base>/stream/<stream_id>` MQTT topic and an HA stream hub device
  (status + active/missing sensors) when the stream has a published entry. Streams
  have **no** `ha_publish` column.
- `inventory_missing` on entries: a marker only, no health effect, no expiry.
- Per-stream `default_checks` (off unless set). Requirement 6 below is already
  true; keep it (no automatic checks unless the operator sets defaults).
- MCP `server_info` answers from the startup `whoami` (no request).

## Working tree check

Run `git status --porcelain`; it should be clean except this file. Otherwise
list and stop.

## What to do

1. **Per-stream state, incl. rejected payloads.** Record the last rejected
   snapshot on the stream (when the stream row exists and the key is bound to it):
   `last_rejected_at` + reason (status code + first error, truncated), kept
   separate from the apply `last_error` (or fold both into one with a kind —
   decide, record it). Not audited (snapshot PUTs aren't). Expose
   `last_snapshot_at`, `last_item_count`, `last_error`, the rejection fields and
   staleness (item 2) on the stream resource, `list_streams`, and a compact
   per-stream block in `health_summary` (API + MCP). UI: show them in the stream
   row.
2. **Stream staleness.**
   - Per-stream `expected_interval_seconds` (nullable; effective default 15 min).
     Optionally let a producer advertise its interval: that is an **additive
     optional field on the ingest contract** (`StreamSnapshotPut`), so it needs an
     `API_REVISION` bump (3) + PRD §18.1/§18.5 rows; STD ships first, the sidecar
     follows. Decide whether to do it now or park it (FUTURE.md); record it.
     Operator-set value always wins.
   - A stream is **stale** when enabled and `now - last_snapshot_at > 2 ×
     expected interval` (pick and justify the grace factor). Pending, disabled
     and ignored streams are never stale.
   - Surface it: a stale badge in Settings → Streams, the header (count of
     stale streams, with the pending flag pattern), `health_summary` (a
     failure/`down` line per stale stream, API + MCP), and MQTT: a `stale` field
     on `<base>/stream/<id>` and a `problem` binary_sensor on the HA stream
     device (it exists whenever the stream has a published entry, so no new
     `ha_publish`; record that this replaces the task's "stream's ha_publish").
   - **Decide and record** whether entries of a stale stream are marked stale.
     Recommendation to evaluate: no — entry health comes from its own checks; the
     stream's staleness is one signal on the stream (entries get at most a muted
     "stream stale" hint in tooltips), so a dead producer doesn't flip 50
     entries.
   - Evaluate it cheaply: computed on read (UI/API) and on the existing periodic
     job for MQTT (no new thread). Transitions log once.
3. **`missing` lifecycle.** Define and document (PRD §18.6/§18.7):
   - missing → visible **warning** badge (amber, not Down) on all views and in
     the detail panel, with "missing since <time>" (add `inventory_missing_since`
     if needed — migration). Health rollup is unchanged by `missing` (checks keep
     running and decide health). Include `missing` + since in the MQTT entry
     payload.
   - optional **auto soft-delete after N days**, per stream
     (`missing_expiry_days`, nullable = off, default off), run by an existing
     scheduled job. **Never** auto-delete an entry that is `stream_linked`,
     renamed (`name_source = ui_edit`), or otherwise edited by a human (define
     "edited" concretely — e.g. any check added/edited, group/description/URLs
     set — and record it). Soft-deleted this way restores by key if the item
     returns (existing restore path). Log each.
   - UI + API + MCP for the setting.
4. **Check target templating — design first.** Before code, write a decisions
   entry: should a stream entry's check target reference `{inventory.ip}` (and
   maybe `{inventory.mac}`/hostname) so it follows reservation changes?
   Evaluate against: checker purity (`checker.py` has no DB), the dict-based
   validators in `check_form.py`, API/MCP round-trip of the raw vs resolved
   target, what happens when the entry is unlinked or the field is null, and
   whether default checks (inv-06) should be created templated. If you build it:
   store the template, resolve at check time, show both in the UI, validate the
   placeholder set strictly, null → check result `unknown` with a clear reason;
   make inv-06 default checks use `{inventory.ip}`. If you reject it, record why
   and instead update the stored target on IP change for checks whose target
   equals the old IP. Either way, a changed IP must not leave a check silently
   probing the old host.
5. **MCP `server_info`.** Re-check the STD version with a cheap call
   (`GET /api/v1/meta`, public) on each `server_info` call (short timeout; on
   failure fall back to the startup value labelled "as of startup <timestamp>").
   Report both startup and current values; when STD is newer than at startup or
   than the MCP, the advice says to restart the MCP server (and update it if
   `mcp_version` is behind). Keep the startup notice.
6. **Not monitored by default:** keep it so. New stream entries get no checks
   unless the stream's `default_checks` is set; add a test that pins it.
7. **API + MCP parity (required)** for everything above (schemas `extra=forbid`,
   `mgmt_openapi.py`, `mcp/README.md`, MCP tests). Management API additions are
   additive; bump `API_REVISION` if the change set calls for it (it must, if the
   ingest contract changes) and add a PRD §18.1 row.
8. **Tests:** rejected payload recording, staleness (enabled/disabled/pending,
   boundary, grace factor), health_summary + MCP output, MQTT `stale` + HA
   problem sensor, missing badge + since, auto soft-delete (and every never-delete
   exemption), templating or IP-follow behavior, `server_info` re-check +
   fallback + restart advice, no checks by default. Migration check.
9. **Docs:** CHANGELOG `[Unreleased]`; PRD §18 (incl. §18.5 if the contract
   changes) + §13 if health_summary changes + §17 for MQTT/HA + revision row;
   README (streams section, MCP); `docs/decisions.md` entries for every "decide"
   above; `docs/FUTURE.md` for anything parked.

## Conventions to honor

- STD owns the contracts: schema first, sidecar follows; core ingest fields stay
  optional; `attributes` uninterpreted.
- No outbound calls while applying a snapshot; no new threads.
- Stream entries stay excluded from register adoption and restore clash checks.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move it into `prompts/done/` (or `prompts/failed/`) with plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Run lint, tests and the migration
   check, then report back the file list, results, every decision you made (one
   line each), anything parked, whether the ingest contract / `API_REVISION`
   changed (the sidecar must then follow), and a proposed one-line message.
