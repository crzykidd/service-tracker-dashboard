# Start a new session: 0.11.0 built on dev, awaiting browser test

Say "read prompts/startnewsession.md and start".

## Where things stand (2026-11-21)

- **Released:** v0.10.1 on `main`. No 0.10.2 was cut; its two fixes ship in 0.11.0.
- **On `dev`, unreleased (0.11.0):**
  - `d69d769` fix: MQTT test bounded to ~5 s; entry names 128 chars (migration `d7a3e9b2c418`).
  - Settings modernization (PRD §19, design `docs/design/2026-11-20-settings-modernization.md`):
    `dfc73e8` phase 1 foundation, `06756b5` notifications + HA, `ab31a38` streams,
    `bd3828e` remaining sections.
  - Backup / export / import (PRD §20, design `docs/design/2026-11-20-backup-export-import.md`):
    `9f32a3f` scheduled backups, `3c68318` export v1 + API revision 4, `0183523` import
    engine, `a5ce3ca` import UI/API/MCP, `94a32e9` staged restore.
- Handoff-prompt queue is empty (all in `prompts/done/`). Nothing was browser-tested;
  every phase is green on ruff + pytest only.

## This session's job

1. Ask the operator what they found testing `:dev` in a browser; fix it (small fixes
   in-session, bigger ones via a handoff prompt).
2. Browser checklists per phase are in each phase's prompt in `prompts/done/` and in the
   end-of-night report; the riskiest items:
   - API key create/rotate: key shown once in a dialog; reload must not re-POST.
   - Channel / stream / user / group dialogs reopen on a validation error with input kept.
   - HA section: grouped by source, tri-state group checkbox, search, sticky save bar.
   - Backup: schedule save + live reschedule, Run now, env-pinned fields read-only.
   - Import: upload → stream mapping → preview → apply; stale-plan 409; users imported
     with no password can't sign in.
   - Staged restore: stage, restart the container, check `[restore]` log lines,
     `pre-restore-*` kept, green banner; a corrupted `pending.json` sha256 must still
     start STD on the old DB.
3. Then `/release-prep 0.11.0`.

## Known follow-ups

- Settings follow-ups parked in `docs/FUTURE.md` ("Settings follow-ups (after 0.11.0)"),
  backup "Later" list in the backup design doc §15.
- Older parked items: stream observability follow-ups, small gaps after v0.10.1,
  notifier API-revision logging, the network-inventory design.

## Housekeeping

- Lint: `uvx ruff@0.15.17 check .`. Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.
- No `Co-authored-by:` trailers (CLAUDE.md wins). CHANGELOG archive step is skipped.
- Release prep labels API revision 4's release in `api_version.py` (already "0.11.0").
