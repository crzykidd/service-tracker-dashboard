---
name: 2026-11-16-notif-03-home-assistant-discovery
status: completed        # pending | completed | failed
created: 2026-11-16
model: sonnet
completed: 2026-11-16
result: HA discovery per entry/check via the notif-02 reconcile, ha_exclude opt-outs (migration d8e2a6f4b915), birth-message resync, UI/API/MCP, tests (20 new), docs.
---

# Task: Home Assistant MQTT discovery — one device per STD entry

When a channel's "Add to Home Assistant" box is ticked, publish MQTT
discovery config so Home Assistant creates one device per STD entry. Each
device gets a roll-up state sensor and one problem `binary_sensor` per check,
all linked to an STD hub device. New entries and checks appear automatically.
Per-entry and per-check opt-outs remove them.

## Before you start

- notif-01 and notif-02 must be completed (both in `prompts/done/`). If
  not, stop and report.
- Read `CLAUDE.md` and the `docs/PRD.md` §17 "Next release —
  Notifications: MQTT and Home Assistant".
- Read the notif-02 topic/payload contract and its `full_sync()` /
  published-set reconcile. Discovery reuses that mechanism; don't build a
  second one.
- Check the current HA MQTT discovery docs for field names, especially
  `default_entity_id` vs the deprecated `object_id`, the device keys, and
  the `homeassistant/status` birth topic. Use what current HA accepts and
  record it in `docs/decisions.md`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

### Operator decisions (2026-11-16, binding)

- One HA device **per STD entry**, linked to an STD hub device (`via_device`).
- **Global opt-in per channel** (`ha_discovery`). Then every active entry
  and check is published automatically, including new ones.
- **Per-entry opt-out** and **per-check opt-out** remove that device or
  entity from HA with an empty retained config.
- Findable naming:
  - the device name is `<ha_device_prefix> <entry name>`;
    `ha_device_prefix` defaults to `STD` and is changeable;
  - suggest entity ids starting `std_…` so `*.std_*` globs work in
    auto-entities.
- The STD group is an **attribute only**. No `suggested_area`.
- **No command entities** (no "Check now" button). Park that in
  `docs/FUTURE.md` as needing a security review.
- State-change publishing only (from notif-02). No per-result latency
  sensors.

### Steps

1. **Schema (Alembic).**
   - Add `service_entries.ha_exclude` (bool, default false, NOT NULL) and
     `health_check.ha_exclude` (bool, default false, NOT NULL).
   - Use opt-out columns so "publish all" picks up new rows automatically.
   - Run `alembic check` and add a migration test.
2. **Discovery configs.** Discovery prefix: `ha_prefix`, default
   `homeassistant`. Use node id `std_<instance short id>` so two STD
   instances never collide.
   - **Hub device** (`identifiers: ["std_<instance>"]`):
     - `name`: `<prefix>` (e.g. `STD`);
     - `manufacturer`: `Service Tracker Dashboard`;
     - `model`: `STD`;
     - `sw_version`: the STD version;
     - `configuration_url`: the STD base URL, if known.
     - Entities:
       - `binary_sensor` connectivity, reading `<base>/status`;
       - `sensor`s for `up`/`degraded`/`down`/`unknown` counts, reading
         `<base>/summary` via `value_template`.
   - **Entry device** (`identifiers: ["std_<instance>_entry_<entry_id>"]`):
     - `name`: `<prefix> <entry name>`;
     - `manufacturer`: `Service Tracker Dashboard`;
     - `model`: the entry source (`Docker container` / `Manual`);
     - `sw_version`: the image tag if the entry has one, else omit;
     - `configuration_url`: the entry's STD edit/detail URL;
     - `via_device`: the hub.
   - **Entry entities:**
     - `sensor` `…_state`: `device_class: enum`, `options` =
       `[up, degraded, down, unknown, none]`;
       `state_topic` = `<base>/entry/<id>/state`; `value_template` for
       `state`; `json_attributes_topic` = the same topic;
       `unique_id` = `std_<instance>_entry_<id>_state`.
     - Per check, a `binary_sensor`: `device_class: problem`, ON when
       failing; `state_topic` = `<base>/entry/<id>/check/<check_id>`;
       `json_attributes_topic` = the same topic;
       `unique_id` = `std_<instance>_check_<check_id>`; the entity name is
       the check's label/type, e.g. `HTTP`, `TCP 443`, `Container`.
   - **All entities** set `availability_topic` = `<base>/status`. Make sure
     the notif-02 payloads carry the attributes auto-entities users will
     filter on: `std_entry_id`, `host`, `group`, `source`, `check_type`,
     `target`, `latency_ms`, `message`, `last_change`, `dashboard_url`.
     Extend the notif-02 payloads if any are missing; additive only.
   - All discovery configs are retained.
   - Renaming an entry republishes its configs; the `unique_id` stays, so
     HA updates in place.
3. **Lifecycle (extend notif-02 `full_sync()` / published set).**
   - The desired discovery configs are: enabled channel with
     `ha_discovery` × active entries without `ha_exclude` × their checks
     without `ha_exclude`.
   - Anything previously published and no longer desired gets an empty
     retained payload on its config topic. That covers removed checks,
     deleted/soft-deleted/purged entries, opt-outs, and turning
     `ha_discovery` off.
   - Subscribe to `<ha_prefix>/status`. On `online` (HA restarted),
     republish all configs and then all states. This is the only
     subscription; it is read-only.
   - Publish configs before states on connect.
4. **UI.**
   - The channel form gets "Add to Home Assistant" (checkbox), "Discovery
     prefix" and "Device name prefix".
   - The entry edit page gets "Exclude from Home Assistant". The check
     config gets a per-check "Publish to Home Assistant" toggle (default
     on, stored as `ha_exclude`).
   - Show these controls only when an HA-enabled channel exists, or keep
     them always visible but disabled with a hint; your call.
5. **Management API / MCP.**
   - Expose `ha_exclude` on entries and checks (read/write), and the HA
     fields in the channel config. Update `mgmt_schemas.py`,
     `mgmt_serializers.py`, `mgmt_openapi.py` and the MCP tools.
6. **Tests**, using the fake paho client:
   - the config payload shape (identifiers, `via_device`,
     `unique_id`s, `availability`, `device_class`);
   - a new check auto-publishes;
   - entry/check opt-out sends an empty config;
   - delete, soft delete and purge clear configs;
   - turning `ha_discovery` off clears everything;
   - a rename keeps the `unique_id`;
   - the HA birth message triggers a republish;
   - two instance ids don't collide;
   - migration up and down.
   - `ruff check .` and `pytest -q` must pass.
7. **Docs (same change).**
   - `CHANGELOG.md` `[Unreleased]`.
   - `docs/PRD.md`: the discovery contract; mark the step Delivered;
     bump the revision history.
   - `README.md`: a Home Assistant section with what gets created, the
     naming, and example **auto-entities** cards. Examples:
     - all failing checks: `binary_sensor.std_*` with `state: "on"`;
     - by group: `attributes: {group: Media}`;
     - by `device_manufacturer: Service Tracker Dashboard`.
   - `docs/FUTURE.md`: the "Check now" button and per-result publishing.
   - `docs/decisions.md`.

## Conventions to honor

- No network I/O on checker/scheduler threads.
- Opt-out flags are operator-owned. Register must never overwrite them;
  add them to whatever ownership/preservation the register handler uses,
  and add a test.
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
