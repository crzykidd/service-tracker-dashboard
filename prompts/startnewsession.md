# Start a new session: verify 0.10.0 on `:dev`, fix what's found, release

Paste this into a fresh Claude Code session in this repo, or say "read
prompts/startnewsession.md and start".

## Where things stand (2026-11-18)

- **Shipped:** v0.9.0 is the latest tag on `main`.
- **On `dev`, unreleased, all going out as 0.10.0** (decided). Everything is
  under CHANGELOG `[Unreleased]`. CI and the `:dev` image are green at
  `8ce1ad8`.
  - Version in the UI (PRD §16).
  - Notifications: MQTT channels, retained state, HA discovery (opt-in per
    entry), purge (PRD §17). The operator tested these on `:dev` and
    reported them good.
  - Fix: auto-refresh only on the dashboard views.
  - Inventory streams and API revision (PRD §18, all delivered on `dev`):
    - §18.1 API revision 2: `X-STD-API-Revision` / `X-STD-Version` headers,
      public `GET /api/v1/meta` (`c61166d`);
    - §18.2 HA "Since" sensor and nightly SQLite snapshot (`1ef0be0`);
    - §18.3 `is_docker` refactor (`b93245b`);
    - §18.4–§18.7 stream ingest backend, `ingest` key scope, apply engine,
      lifecycle, block list, link offers, management API + MCP (`81852a6`);
    - §18.8 Settings → Streams UI, stream pill, edit-page flows (`8ce1ad8`).
- **Handoff prompts:** inv-01..05 all in `prompts/done/`. The queue is empty.
- **Sidecar:** `std-source-technitium` is being built in a separate session
  in `~/projects/technitium-sync` (its own repo, its own copy of the kickoff
  prompt). It doesn't report back here. Its live test needs STD `:dev`,
  which now has everything it needs.

## This session's job

1. **Ask the operator what they've checked on `:dev`** and what the sidecar
   live test turned up. Fix anything found (handoff prompt if it's more than
   a small change).
2. **Browser checks still owed** (the tests used the Flask test client only;
   the JS was never run in a browser):
   - Settings → API: create an "Ingest (sidecars)" key.
   - Settings → Streams: pending highlight + nav count, Preview, Enable,
     Ignore; the Disable…/Delete… dialog (mode switch, counts, customised
     entries, "Also clear the block list" only for disable + purge); inline
     edit of display name and network filters; Unblock; offer Accept/Decline.
   - Dashboard / Tiled / Compact: blue stream pill, "missing from latest
     snapshot" marker, Source filter `stream:<id>`.
   - Delete popover on a stream entry: Allow re-adding vs Don't re-add.
   - Edit page: read-only stream fields, Convert / Keep separate banner,
     "Link to stream item…" on a host-less manual entry.
   - HA: the "Since" sensor shows a timestamp, and unknown when `since` is
     null.
   - Backups: a `<date>-std_backup.sqlite3` appears next to the YAML and is
     pruned with it.
3. **Contract feedback from the sidecar** (PRD §18.5): the operator relays
   it. STD owns the contract; change it here first, then the sidecar
   follows. Any additive `/api/v1` change bumps `API_REVISION` (rule in
   CLAUDE.md), but a fix inside 0.10.0 before release stays revision 2.
4. **Release:** when the operator is happy, `/release-prep 0.10.0`, then the
   human merges the PR, then `/release-cut 0.10.0`. Update the CLAUDE.md
   Build Status lines and this file as part of that.

## Known gaps (decide: fix, park in FUTURE.md, or accept)

From notifications (carried over, not yet decided; the delete/disable and
base-topic gaps were fixed by notif-06):
- The test button can block up to about 13 s against a broker that doesn't
  answer.
- The "republish: false" purge hold is in memory only, so a restart ends it.
- The published-state set is shared across channels (see
  `docs/decisions.md`).

From streams (as built; see PRD §18 "As built" notes and `docs/decisions.md`):
- Deleting a stream drops its blocks and offers; `clear_blocks` only matters
  for disable + purge.
- A stream's display name is set at creation; snapshots never change it.
- UI stream actions go to the app log, not `api_audit` (API actions still
  audit).
- `container_name` is `String(100)` while the contract allows 128-char names
  (SQLite doesn't enforce it).
- `meta` advertises `std_version` from `VERSION`, so it reads 0.9.0 until
  release prep bumps it.

## Later (parked)

- docker-api-notifier: send its own `User-Agent`, log STD's API revision,
  optional `meta` at startup. In `docs/FUTURE.md` ("Notifier: log STD's API
  revision"); nothing breaks without it.
- The rest of the network-inventory design (tags/views, thresholds, monitor
  profiles, HA merge mode, alerting) stays in
  `docs/design/2026-11-17-network-inventory-and-profiles.md` and
  `docs/FUTURE.md`.

## Before starting

- Read `CLAUDE.md`, `standards.md`, `docs/PRD.md` §18 and
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
