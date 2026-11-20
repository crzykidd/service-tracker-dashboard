---
name: 2026-11-19-notif-06-mqtt-cleanup-and-stream-topics
status: completed        # pending | completed | failed
created: 2026-11-19
model: sonnet
completed: 2026-11-19
result: Items 1-10 done: channel delete/disable cleanup, base-change cleanup + remembered bases, per-stream purge, orphan scan/clear, stream status topic, HA stream hub device, API/OpenAPI/MCP parity, tests (1263 passed), docs.
---

# Task: MQTT/HA cleanup tools and per-stream topics (0.10.0)

Close the notification "known gaps" before 0.10.0 ships (MQTT/HA is unreleased, so
topic additions are free now). Runs after `inv-06` (same working tree; its changes
may be uncommitted — that's expected, build on them).

## Before you start

- Read `CLAUDE.md`, `standards.md`, `docs/PRD.md` §17 (17.3 state, 17.4 HA
  discovery, 17.5 purge) and §18.6 (MQTT payload for streams), and the
  notification entries in `docs/decisions.md` (shared published-state set).
- Key code: `notify.py` (publisher thread, `Publisher.call()`), `notify_state.py`
  (`PublishState`, `desired_state`, `full_sync`, `sync_discovery`),
  `notify_ha.py` (device/config builders), `notify_purge.py` (`purge_channel`,
  `purge_entry`, retained scan pattern), `notify_mqtt.py`, channel routes in
  `routes_dashboard.py` and `routes_mgmt_api.py`, `mgmt_openapi.py`, `mcp/std_mcp.py`,
  `templates/settings.html` (Notifications section).
- Rule: never block a request thread on the broker beyond the existing patterns;
  purge/scan work runs on the publisher thread via `Publisher.call()` / Job.
- Lint: `uvx ruff@0.15.17 check .` Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.

## Working tree check

Run `git status --porcelain`. Uncommitted inv-06 changes are expected; anything
else touching the files below — list it and stop and report back.

## What to do

1. **Channel delete cleans the broker.** The delete confirmation for a channel
   offers "Remove this channel's data from the broker first" (**checked by
   default**). When checked: run the channel purge with `republish=false` (state
   topics, check topics, summary, discovery configs; `<base>/status` too since the
   channel is going away — publish an empty retained `status` last), then delete.
   If the channel isn't connected/reachable, return a clear error and let the
   operator choose "Delete anyway". Same option on the management API delete
   (`cleanup: bool`, default true) and MCP.
2. **Channel disable** offers the same cleanup, **unchecked by default**.
3. **Per-stream purge.** "Purge MQTT/HA" action per stream row in Settings →
   Streams: one publisher Job that clears state/check topics and discovery configs
   for every entry of the stream (all live sessions), then lets the next sync
   republish what's still eligible (disabled stream → nothing comes back). Reuse
   `purge_entry` logic batched, not N round trips. Management API route + OpenAPI
   registry + MCP tool. Result counts like entry purge.
4. **Base topic / HA prefix change cleans the old one.** When saving a channel
   whose `base_topic` (or `ha_prefix` / `ha_device_prefix` when discovery is on)
   changed, a checkbox (checked by default) clears retained topics under the old
   base (scan `<old>/#`, clear all incl. old `status`) and the old discovery
   configs, then switches. Persist a short per-channel list of previous bases
   (last 5) for the orphan scan.
5. **Orphan scan.** Settings → Notifications per channel: "Scan for orphans" —
   subscribe briefly (same timing as channel purge) to `<base>/#`, each remembered
   previous base, an optional operator-typed base, and our node's discovery
   wildcard under `ha_prefix`; diff retained topics against the current desired
   set (state + discovery); show the orphan list (preview, nothing cleared), then
   "Clear N orphans". Management API (scan returns list; clear takes the list or
   re-scans) + MCP.
6. **Per-stream status topic.** Retained `<base>/stream/<stream_id>` with
   `{stream_id, display_name, status, producer, producer_version,
   last_snapshot_at, last_applied_at, counts: {active, missing, pending_offers},
   item_count}`. Part of `desired_state` (so it's cleared when the stream is
   deleted and reconciled by `full_sync`); a commit that changes stream status /
   counts requests a sync like other changes. Entry topics do **not** move (topics
   use ids; Convert must never move a topic).
7. **HA hub device per stream.** When discovery is on, each stream with at least
   one published entry gets a device (`identifiers: [<node>_stream_<stream_id>]`,
   name `<device_prefix> <display name> stream`, `via_device: <node>`) with a
   status sensor and an active/missing count sensor from the stream topic; that
   stream's entry devices use `via_device: <node>_stream_<stream_id>` instead of
   the hub. Configs removed with the stream. Follow §17.4 lifecycle (configs before
   states, remembered per channel).
8. **MCP parity (required).** Every new or changed operation — channel delete /
   disable with cleanup, stream purge, base-change cleanup, orphan scan + clear,
   previous-bases list — is exposed through the management API (schemas,
   `mgmt_openapi.py`) **and** a tool in `mcp/std_mcp.py`; update `mcp/README.md`
   and MCP tests.
9. **Tests** for each: delete/disable cleanup (connected / unreachable), stream
   purge, base change cleanup + remembered bases, orphan scan diff, stream topic
   payload + lifecycle, stream hub device and `via_device`, OpenAPI registry.
10. **Docs:** CHANGELOG `[Unreleased]`; PRD §17.3–17.5 (and §18.6 stream topic),
   revision row; remove the now-fixed items from the "Known gaps" text in PRD and
   `prompts/startnewsession.md`; `docs/decisions.md` for: stream topic instead of
   moving entry topics under a stream path, cleanup defaults (delete on, disable
   off), remembered-bases limit.

## Conventions to honor

- Never block producers on the broker; all broker work on the publisher thread.
- The channel password stays write-only.
- Management API: `extra="forbid"` schemas, every route in `mgmt_openapi.py`.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move it into `prompts/done/` (or `prompts/failed/`) with plain `mv`.
3. Record non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Run lint + tests, report back the
   file list (only your files, separate from inv-06's), results, doc
   contradictions found, and a proposed one-line message (`feat: ...`).
