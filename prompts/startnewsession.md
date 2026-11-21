# Start a new session: after v0.10.1

Paste this into a fresh Claude Code session in this repo, or say "read
prompts/startnewsession.md and start".

## Where things stand (2026-11-20)

- **Shipped:** v0.10.1 is the latest tag on `main` (v0.10.0 the day before).
  `dev` == `main` apart from merge commits; nothing is in flight and the
  handoff-prompt queue is empty (everything in `prompts/done/`).
- **v0.10.0:** version in the UI (PRD §16), MQTT + Home Assistant
  notifications with cleanup, orphan scan and purge (§17), inventory streams and
  API revision 2 (§18.1–§18.8), plus the first-live-test follow-ups (broader link
  matching incl. host, per-stream default checks, pending-stream header flag,
  Tiled/Compact stream icons, stream status topic + HA stream device, linked
  entries are unlinked never deleted).
- **v0.10.1:** stream observability, API revision 3 (§18.9): stale streams
  (grace factor 2 × interval; operator interval > producer's
  `snapshot_interval_seconds` > 15 min), rejected snapshots recorded, amber
  "missing since" badge + optional per-stream auto soft-delete (off by default,
  human-edited entries exempt), checks follow a changed IP (templated targets
  rejected, parked), MCP `server_info` re-checks the STD version per call.
- **Sidecar (`~/projects/technitium-sync`, separate session, doesn't report
  back):** the operator has a prompt to send `snapshot_interval_seconds` only
  when `GET /api/v1/meta` reports `api_revision >= 3`, and to keep pushing full
  snapshots whatever the stream status. Ask whether it shipped and whether the
  stream shows its advertised interval in Settings → Streams.
- **MCP server:** runs in a different session/client, not this one. It must be
  updated to the `v0.10.1` script and restarted there.

## This session's job

1. **Ask the operator what they've checked in a browser** on 0.10.1 and what
   broke; fix it (handoff prompt if more than a small change; ship as 0.10.2).
   Never browser-checked so far:
   - Settings → Streams: Preview / Enable / Ignore, the Disable… / Delete…
     dialog (modes, linked-entries box, kept snapshot), "Waiting for the next
     snapshot", "would: …" dry-run counts, Default checks + Apply to existing,
     "Staleness and missing entries" panel, stale badge, rejection line,
     Purge MQTT/HA, Unblock, offer Accept / Decline.
   - Header: amber pending flag and red stale count on the Settings link.
   - Views: Dashboard pill + amber missing-since badge; Tiled / Compact router
     icon (amber when missing), Compact source icon per row; IP / MAC / network
     in the expanded detail; Source filter `stream:<id>`.
   - Edit page: Convert / Keep separate banner (host cleared), Link to stream
     item… (also on entries with a host), Unlink from stream… (Allow
     re-offering / Don't re-add), delete popover on a stream entry.
   - Notifications: channel Delete / Disable cleanup + "Delete anyway",
     base-topic change cleanup, Scan for orphans, HA entries Source column.
   - Home Assistant: entry "Since" sensor; stream device with status, active /
     missing and Problem sensors; entries grouped under it (`via_device`).
   - Backups: `<date>-std_backup.sqlite3` next to the YAML, pruned with it.
2. **Contract feedback from the sidecar** (PRD §18.5): STD owns it; change it
   here first. A new optional field needs an `API_REVISION` bump + PRD §18.1 row.
3. **Then pick the next work** from the parked list below with the operator.

## Known gaps (decide: fix, park in FUTURE.md, or accept)

From notifications:
- The test button can block up to about 13 s against a broker that doesn't
  answer.
- The "republish: false" purge hold is in memory only, so a restart ends it.
- The published-state set is shared across channels (see `docs/decisions.md`).

From streams (PRD §18 / §18.9 "As built", `docs/decisions.md`):
- Deleting a stream drops its blocks and offers; `clear_blocks` only matters
  for disable + purge.
- A stream's display name is set at creation; snapshots never change it.
- UI stream actions go to the app log, not `api_audit` (API actions audit).
- `container_name` is `String(100)` while the contract allows 128-char names.
- Entries linked before migration `b4e7a1c9d325` were detected by id order and
  have no `pre_link_host`.
- `find_duplicate` sees stream entries on purpose (one device, one entry).
- With `deleted_retention_days: 0`, auto-expired missing entries are hard
  deleted in the same job run and can't be restored by the item returning
  (parked in `docs/FUTURE.md`).

## Later (parked, `docs/FUTURE.md`)

- Stream observability follow-ups: templated check targets (with monitor
  profiles), `stale` + interval on the ingest status route (needs a revision
  bump), push notifications on transitions.
- docker-api-notifier: send its own `User-Agent`, log STD's API revision,
  optional `meta` at startup ("Notifier: log STD's API revision").
- The rest of the network-inventory design (tags/views, thresholds, monitor
  profiles, HA merge mode, alerting) in
  `docs/design/2026-11-17-network-inventory-and-profiles.md`.

## Before starting

- Read `CLAUDE.md`, `standards.md`, `docs/PRD.md` §17–§18 (incl. §18.9) and
  `docs/decisions.md` (newest first).

## Housekeeping to remember

- Lint with CI's pinned ruff: `uvx ruff@0.15.17 check .`. Other versions
  disagree on import sorting.
- System python has no pytest: `uvx --with-requirements requirements-dev.txt pytest -q`.
- Check what subagents report about docs against `git diff`.
- Spawned agents move untracked prompts with plain `mv`, not `git mv`; stage
  the `prompts/done/` file as a new path.
- The CHANGELOG archive step is skipped at release-prep (memory:
  no-changelog-archive).
- No `Co-authored-by:` trailers (CLAUDE.md wins over the harness reminder).
- Release-prep on a version bump: tests that hard-code the running version
  were fixed in 0.10.0 prep; `api_version.py` labels the new revision's
  release ("next after X" → the version) during prep.
