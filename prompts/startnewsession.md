# Start a new session: after v0.10.0

Paste this into a fresh Claude Code session in this repo, or say "read
prompts/startnewsession.md and start".

## Where things stand (2026-11-19)

- **Release:** v0.10.0 prepared on `dev` (`chore(release): prepare v0.10.0`),
  PR `dev` → `main` open. If `v0.10.0` is not yet a tag: the human merges the
  PR, waits for `main` CI and the `:latest` build, then `/release-cut 0.10.0`.
- **What 0.10.0 holds:** version in the UI (PRD §16), MQTT + Home Assistant
  notifications with cleanup / orphan scan / purge (§17), inventory streams
  and API revision 2 (§18), including the 2026-11-19 follow-ups from the first
  live `std-source-technitium` test (inv-06, notif-06, inv-07: broader link
  matching, default checks, pending flag, stream topic + HA stream device,
  linked entries are unlinked never deleted).
- **Browser checks not yet reported** for inv-06 / notif-06 / inv-07 UI (stream
  icons on Tiled/Compact, pending flag, Default checks panel, channel cleanup
  dialogs, orphan scan, stream purge, Unlink, HA stream device). Ask the
  operator; fix in a 0.10.x patch if needed.
- **Handoff prompts:** queue empty; everything in `prompts/done/`.
- **Sidecar:** `std-source-technitium` lives in `~/projects/technitium-sync`
  and doesn't report back here. Open question for it: whether it keeps pushing
  snapshots while its stream is disabled (STD stores them; it should).

## Known gaps (decide: fix, park in FUTURE.md, or accept)

From notifications:
- The test button can block up to about 13 s against a broker that doesn't
  answer.
- The "republish: false" purge hold is in memory only, so a restart ends it.
- The published-state set is shared across channels (see
  `docs/decisions.md`).

From streams (see PRD §18 "As built" notes and `docs/decisions.md`):
- Deleting a stream drops its blocks and offers; `clear_blocks` only matters
  for disable + purge.
- A stream's display name is set at creation; snapshots never change it.
- UI stream actions go to the app log, not `api_audit` (API actions still
  audit).
- `container_name` is `String(100)` while the contract allows 128-char names
  (SQLite doesn't enforce it).
- Entries linked before migration `b4e7a1c9d325` were detected by id order and
  have no `pre_link_host`.

## Later (parked)

- docker-api-notifier: send its own `User-Agent`, log STD's API revision,
  optional `meta` at startup (`docs/FUTURE.md`, "Notifier: log STD's API
  revision").
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
