# Start a new session: review the network-inventory design, then plan the next work

Paste this into a fresh Claude Code session in this repo, or say "read
prompts/startnewsession.md and start".

## Where things stand (2026-11-17)

- **Shipped:** v0.9.0 is the latest tag on `main`.
- **On `dev`, unreleased** (all under CHANGELOG `[Unreleased]`; release
  number **not decided**, 0.10.0 is likely given the scope):
  - Version in the UI (PRD §16): header version + What's New link,
    dev-build SHA, GitHub update-available check, `BUILD_CHANNEL` build
    arg.
  - Notifications (PRD §17):
    - MQTT channel framework and Settings → Notifications (§17.2);
    - retained state publishing (§17.3);
    - Home Assistant discovery, opt-in per entry with a bulk picker and
      `STD <name> (<host>)` device names (§17.4);
    - channel and entry purge (§17.5).
  - Fix: auto-refresh only on the dashboard views.
- **Handoff prompts:** all done (`prompts/done/2026-11-16-version-in-ui.md`,
  `2026-11-16-notif-01..03`, `2026-11-17-notif-04..05`).

## Not yet verified for real (do this before `/release-prep`)

Every notification test used a fake paho client. Nothing has been checked
against a real broker or Home Assistant, and no UI has been checked in a
browser. Ask the operator what they have checked on the `:dev` image.

The checklist:
- **Header:** the version label opens What's New; the hourly update poll
  works.
- **Settings → Notifications:**
  - Send test message;
  - live status;
  - the HA entries bulk picker (filter, Select all/none, Save);
  - the Purge dialog.
- **Retained messages:** `mosquitto_sub -t 'std/#' -v` shows status, entry,
  check and summary messages.
- **HA:** devices appear only for opted-in entries, with good names and
  `std_…` entity ids. Unticking an entry removes its device. A HA restart
  triggers a republish.
- **Purge timing:** the retained-collect timing (1 s settle, 0.6 s quiet,
  6 s cap) is a guess. Check a channel purge on a broker with many topics.

## Known gaps (decide: fix, park in FUTURE.md, or accept)

- Deleting or disabling a channel while HA discovery is on leaves its configs
  on that broker. Untick discovery or use Purge first.
- Changing the base topic leaves the old retained topics behind. Purge covers
  the new base only.
- The test button can block up to about 13 s against a broker that doesn't
  answer.
- The "republish: false" purge hold is in memory only, so a restart ends it.
- The published-state set is shared across channels (multi-broker edge
  cases; see `docs/decisions.md`).

## This session's job

1. **Review the operator's draft design**
   `docs/design/2026-11-17-network-inventory-and-profiles.md`: network
   inventory beyond containers, tags/views, monitor profiles and alert
   policies, and an `STD Health` value in HA.
   - Do what its §12 reviewer checklist asks: read it against the code and
     list gotchas, wrong assumptions and cheaper alternatives.
   - It was written against `8bd2233`. Since then, notif-04 changed HA to
     opt-in per entry (`service_entry.ha_publish`) with host in device names,
     and notif-05 added purge. Check the draft's HA assumptions against
     that.
2. Discuss the open questions with the operator, then scope the first slice
   in the PRD and write handoff prompts (the same flow as v0.9.0 and the
   notifications work).
3. Separately, with the operator: pick the release number for what is on
   `dev`, once the real-world checks above pass, and run `/release-prep`.

## Before starting

- Read `CLAUDE.md`, `standards.md`, `docs/PRD.md` (§13 monitoring, §16, §17)
  and `docs/decisions.md` (newest first).

## Housekeeping to remember

- Lint with CI's pinned ruff: `uvx ruff@0.15.17 check .`. Other versions
  disagree on import sorting.
- A Docker container `std-mosq-test`, bound to `127.0.0.1:18830`, was stuck
  on the dev host (docker exec, rm and kill all hung). Ask the operator
  whether it has been cleared; don't rely on Docker for broker tests until it
  is.
- Check what subagents report about docs against `git diff`. One claimed PRD
  edits it hadn't made.
- The CHANGELOG archive step is skipped at release-prep (memory:
  no-changelog-archive).
- No `Co-authored-by:` trailers (CLAUDE.md wins over the harness reminder).
