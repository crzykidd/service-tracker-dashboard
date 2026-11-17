# Start a new session: plan the post-0.9.0 work

Paste this into a fresh Claude Code session in this repo, or say "read
prompts/startnewsession.md and start".

## Where things stand

- **Shipped:** v0.9.0 (check `git tag -l 'v0.9*'` and `CLAUDE.md` Build
  Status to confirm it was cut).
- **What 0.9.0 added:**
  - DNS checks and a cert-expiry condition;
  - API key rotation, and reuse of a revoked key's name;
  - Settings → Groups saved with one Save, with an unsaved-changes guard;
  - the host shown on tiles when a name is duplicated (`tile_show_host`);
  - one exposure icon per proxy layer;
  - roll-up: a passing Container check no longer softens a failing service;
  - HTTP failures carry the reason from the reply body;
  - MCP install via `uv run` plus a version check.
- **Parked:** `docs/FUTURE.md`. In particular, "Register overwrites some
  operator edits" (custom icon and URL-check toggles clobbered by register).
- **Before starting:** read `CLAUDE.md`, `standards.md`, `docs/PRD.md` (§13
  monitoring, §14 management API, §15 v0.9.0) and `docs/decisions.md`
  (newest first).

## This session's job: plan, don't build

Scope the next release in the PRD and write handoff prompts, the same way
v0.8.0 and v0.9.0 were done. Discuss the open questions below with the
operator before writing prompts. Item 2 explicitly needs design thinking
first.

### 1. Version in the UI, with update and dev-build awareness

- Show the running version right after the "Service Tracker Dashboard"
  header, e.g. `v0.9.0`.
- **Update available:** check GitHub for a newer release
  (`crzykidd/service-tracker-dashboard` releases) and show a subtle
  "update available → vX.Y.Z" link to the release page.
- **Dev build:** when running a dev image (`:dev` / `:sha-…`), show that it's
  a dev build (e.g. `dev · 0.9.0+sha-abc1234`) and link to that commit or
  the `dev` branch on GitHub.

Open questions:
- How does the image know it's a dev build and which commit? Today
  `publish.yml` writes `/app/version.txt` from `VERSION` only. It could add
  the git SHA, the build channel (release/main/dev) and the build date as
  build args or a JSON `version.txt`. Check what `VERSION_INFO` already
  holds.
- The GitHub check:
  - server-side, cached (e.g. every 12–24 h by a scheduler job), so
    browsers don't hit the GitHub API;
  - a setting to turn it off (offline or air-gapped homelabs);
  - no auth needed; respect rate limits;
  - never block page render.
- Should a dev build compare against the latest `dev` commit, or only
  against releases?
- Expose it via `/api/v1/config` or `whoami` (the MCP already compares
  versions).
- The What's New popup already parses CHANGELOG. Should the version link
  open it?

### 2. Notification service (plan only; needs thinking)

Goal: an **external notification channel** framework, with **MQTT** as the
first channel.

- **Channels:** a generic notion of a notification channel (type, enabled,
  settings) so later channels (ntfy, webhook, email, Gotify…) plug in. MQTT
  is the first.
- **MQTT settings:** broker host/port, TLS, username/password (secret:
  write-only, masked, like `widget_api_key`), client id, and a **default
  topic path that the operator can change** (e.g. `std/` as the base).
- **What gets published:**
  - check results and state changes per entry and per check;
  - the roll-up state (up/degraded/down/unknown);
  - possibly the summary counts.
  - Decide between every result and state transitions only, and between
    retained and non-retained messages.
- **"Add to Home Assistant" checkbox:** when set, publish **MQTT discovery**
  config (`homeassistant/<component>/<node>/<object>/config`) so HA
  auto-creates a **device** per STD entry, with an entity per check result.
  This needs thinking through:
  - device granularity: one HA device per STD entry, or one STD device
    with many entities;
  - entity types: `binary_sensor` (problem) per check, a `sensor` for
    state, latency or message attributes;
  - unique ids, so renames don't duplicate entities;
  - availability topic and LWT, so HA marks things unavailable when STD
    stops;
  - cleanup: removing an entry or check must remove its discovery config
    (an empty retained payload);
  - discovery prefix configurable (default `homeassistant`);
  - opt-in globally or per entry?
- **Where it hooks in:** `jobs.py` records check results on the scheduler
  thread. Publishing must not slow the checker; use a queue plus a
  publisher thread or the paho-mqtt loop. Reconnect handling.
- **Dependency:** `paho-mqtt`, pinned. Possibly `aiomqtt`; check which fits
  the threaded APScheduler model.
- **UI:** Settings → Notifications tab, with a "send test message" button.
- **API and MCP:** expose channel config through the management API (secrets
  write-only), and maybe a "test channel" endpoint.
- **Relation to FUTURE.md "Alerting / notifications on failure":** this is
  that item; move it into the PRD when scoped.

## Housekeeping to remember

- The CHANGELOG archive step is skipped at release-prep; the operator keeps
  the full CHANGELOG (memory: no-changelog-archive).
- Commit each chunk as it finishes. Push only when asked.
- No `Co-authored-by:` trailers (CLAUDE.md wins over the harness reminder).
