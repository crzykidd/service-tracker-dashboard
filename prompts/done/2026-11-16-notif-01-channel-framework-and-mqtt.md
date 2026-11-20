---
name: 2026-11-16-notif-01-channel-framework-and-mqtt
status: completed
created: 2026-11-16
model: sonnet
completed: 2026-11-16
result: notification_channel table, notify.py publisher + MQTT channel, Settings tab, management API and MCP tools; ruff clean, 863 tests pass
---

# Task: Notification channel framework with MQTT as the first channel (connection, settings, test)

Add a generic notification-channel model and a background publisher. Add MQTT
as the first channel type, with a Settings → Notifications tab and a "send
test message" button. This step publishes **only** the STD availability topic
and test messages. Check/state publishing is notif-02; Home Assistant
discovery is notif-03.

## Before you start

- Read `CLAUDE.md`, `standards.md`, and `docs/PRD.md`, especially the
  §17 "Next release — Notifications: MQTT and Home Assistant". The
  planning session adds it. If it is missing, stop and report.
- Read the newest `docs/decisions.md` entries.
- Patterns to copy:
  - write-only secrets: `widget_api_key` (`mgmt_schemas.py` and
    `mgmt_serializers.py` return `*_set: bool`, never the value; an omitted
    field keeps the stored value, `null` clears it);
  - DB runtime settings: `settings_store.py`, the `Setting` model;
  - Settings page tabs in `templates/settings.html` with `routes_dashboard.py`;
  - management API: `routes_mgmt_api.py`, `mgmt_schemas.py`,
    `mgmt_openapi.py` (every route must be in OPERATIONS; tests enforce
    this);
  - background threads: `jobs.py` `start_background_workers` and the health
    loop's safety-net style.
- gunicorn runs exactly ONE worker, so a single in-process publisher is
  correct. Startup runs in `post_worker_init`; see `gunicorn.conf.py`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Dependency.**
   - Add `paho-mqtt` (2.x, which uses the `CallbackAPIVersion.VERSION2`
     API) to `requirements.in`.
   - Regenerate `requirements.txt` with `uv pip compile` as the README
     describes.
   - Use paho's threaded `loop_start()`. No asyncio; `aiomqtt` doesn't fit
     the threaded model, so record that rejection in `docs/decisions.md`.
2. **Schema (Alembic migration).** Add a `notification_channel` table:
   - `id`;
   - `type` (string, e.g. `mqtt`);
   - `name` (unique);
   - `enabled` (bool, default false);
   - `config` (JSON: non-secret settings);
   - `secret` (string, nullable: the password; write-only everywhere);
   - `created_at` / `updated_at`.

   Add indexes per the Database Rules. Use `alembic check` and the
   migration test pattern in `tests/`.
3. **Channel-type registry** (new module, e.g. `notifications/` package or
   `notify.py`; don't name a package `mqtt` because it would shadow
   libraries):
   - Each channel type has a config validator (pydantic, `extra="forbid"`),
     defaults, a `test()` method and a `publish(event)` method.
   - MQTT config fields:
     - `host`, `port` (default 1883, or 8883 with TLS);
     - `tls` (bool), `tls_insecure` (bool, default false);
     - `username`;
     - `client_id` (default `std-<instance short id>`);
     - `base_topic` (default `std`, changeable; strip any trailing `/`);
     - `qos` (0/1, default 1);
     - `keepalive` (default 60).
   - The HA discovery fields (`ha_discovery` bool, `ha_prefix` default
     `homeassistant`, `ha_device_prefix` default `STD`) belong to notif-03.
     Reserve them in the schema now, unused, so notif-03 needs no config
     reshuffle.
   - Add a stable **instance id**: a UUID generated once and stored in the
     `Setting` store. MQTT client ids and HA unique ids use it.
4. **Publisher service.**
   - One background thread owns a bounded `queue.Queue` and the paho
     client(s) for enabled channels.
   - Producers call a non-blocking `notify.enqueue(event_dict)`. It never
     raises and never blocks the caller. When the queue is full, drop the
     oldest event and log a rate-limited warning.
   - Events are plain dicts, never ORM objects.
   - **LWT and availability:** set will `<base>/status` = `offline`
     (retained). On connect, publish `online` (retained). On clean
     shutdown, publish `offline`.
   - Reconnect with paho's `reconnect_delay_set` and backoff. Log connection
     state changes once each, not per retry.
   - Expose an `on_connect` hook list so notif-02/03 can republish
     everything after a (re)connect.
   - When channel config changes in the UI or API, reload the publisher:
     disconnect cleanly and reconnect with the new config, without
     restarting STD.
   - The publisher is not started in tests unless a test asks for it. Use
     an injectable client factory so tests use a fake paho client and never
     open sockets.
5. **Settings → Notifications tab** (admin only):
   - list channels, add or edit an MQTT channel, enable/disable, delete;
   - the password field is write-only, like `widget_api_key` (shows "set",
     blank keeps it, a clear checkbox removes it);
   - show live connection status (connected / connecting / error + last
     error);
   - a **"Send test message"** button that publishes a non-retained JSON
     message to `<base>/test` and reports success or failure inline. For an
     unsaved form, test with the submitted values.
   - CSRF as for other forms; use the unsaved-changes guard
     (`static/js/unsaved_guard.js`) like other settings tabs.
6. **Management API (admin key).**
   - CRUD for channels at `/api/v1/notifications/channels[/<id>]`. The
     secret is write-only (`secret_set: bool` in responses).
   - Add `POST /api/v1/notifications/channels/<id>/test`.
   - Use read scope for GET and admin scope for writes, matching existing
     settings endpoints.
   - Add everything to `mgmt_openapi.py`.
7. **MCP.** Add read tools for channels and status, plus a test-channel
   tool, following `mcp/std_mcp.py` conventions. Bump `MCP_VERSION` only if
   that is the existing convention for tool additions; check
   `docs/decisions.md`.
8. **Tests.**
   - config validation (bad port, unknown keys);
   - secret write-only semantics (UI and API);
   - migration up and down;
   - `enqueue` never blocks and drops the oldest when full;
   - LWT and `online` publish via the fake client;
   - config change triggers reconnect;
   - the test endpoint, success and failure;
   - OpenAPI registry.
   - `ruff check .` and `pytest -q` must pass.
9. **Docs (same change).**
   - `CHANGELOG.md` `[Unreleased]` → Added.
   - In `docs/PRD.md`, mark this step Delivered in the notifications
     section, update §3 module layout and §5 data model (new schema
     subsection), and bump the revision history.
   - `README.md`: add a Notifications section covering broker setup and
     the test button.
   - `CLAUDE.md` Module Layout: add the new module(s).
   - `docs/decisions.md`: record the decisions.

## Conventions to honor

- Never block the scheduler/checker threads on network I/O.
- Never return or log the MQTT password.
- Commit prefix `feat:`. No `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. By default the message
   is a plain one-liner and the branch is whatever the session is on. **Only if** the
   project also adopts `code-checkin-and-pr` do its branch rules (`dev`, never `main`)
   and commit-prefix conventions (`feat:` / `fix:` / `chore:` / `docs:`, no
   `Co-authored-by:`) apply on top.
