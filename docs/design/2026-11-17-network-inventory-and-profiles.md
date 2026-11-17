# Design: network inventory, tags and views, monitor profiles and alert policies

**Status:** draft for review (2026-11-17). Nothing here is scheduled. This file is input to the
PRD; once a slice is planned it moves into a PRD section and this file links there.
**Author:** operator + Claude (design session in homelab-configs, 2026-11-17).
**Reviewer ask:** read this against the code and list gotchas, wrong assumptions and
cheaper alternatives (see [§12](#12-reviewer-checklist)). Code paths named here were
read on `dev` at `8bd2233`; trust the code where they disagree.

---

## 1. Goal

STD becomes the inventory and health record for **everything on the network**, not
just Docker containers: ESPHome nodes, Shelly relays, Wi-Fi bulbs, cameras, APs, switches,
VMs and hypervisors. Three outcomes:

1. **One place to see health and history for any device.** "Is the hot-water circ pump
   flapping?" is answered by the device's 7-day uptime strip.
2. **A troubleshooting signal inside Home Assistant.** The HA device page for an ESPHome
   node shows an `STD Health` value (green / yellow / red) and when STD last saw it. If STD
   says it's up but HA can't see it, the problem is HA or the integration. If neither sees
   it, the problem is physical (power, Wi-Fi, cabling).
3. **Manageable at hundreds of entries.** Device-type defaults are set once and inherited.
   Changing a default updates every device that uses it. Views keep the everyday dashboard
   clean.

Non-goals: replacing HA's own device availability; controlling devices; a public status
page (still parked in FUTURE.md).

## 2. Operator decisions (2026-11-17)

- Everything on the network gets an entry.
- **Tags are separate from groups.** An entry has one group (category, as today) and any
  number of tags. A tag filter still renders the group / host / stack breakdown.
- **Saved views** in a drop-down: a name plus filters and layout, recalled exactly. One view
  is the home page.
- **Notification/monitoring rules as named profiles**, e.g. `Default` (today's behaviour)
  and `Shelly`. An entry either uses a profile or customises it. **Changing a profile
  updates every entry that uses it.**
- HA shows STD health on the **existing** device (e.g. the ESPHome device), not only on a
  separate STD device.
- A quick 7-day view to spot flapping.
- Every IP device has a DHCP reservation (Technitium). Host ↔ MAC comes from there.
- **Network inventory is off by default, behind one global enable switch**, and disabling
  it offers to **clean up the entries it created** (§6.3).

## 3. What already exists (don't rebuild)

| Need | Already in STD | Gap |
|---|---|---|
| Ping | `checker.probe_ping` (icmplib, NET_RAW) | none |
| TCP / HTTP / DNS / cert checks | `checker.py`, §13.4, §15 | none |
| 7-day history | `health_result` + compaction, `health_history.bars(range=7d)` in the detail panel | The inline strip (`/health/strips`) is 24h only. No flap metric. |
| Health colours | `health_state.entry_health`: up / degraded / down / unknown / none | No threshold or "pending" state (see §7.3) |
| Per-check interval / timeout | `health_check.interval_seconds` / `timeout_seconds`, NULL = global | The NULL-inherits pattern is reused for profiles |
| HA entity per entry | `notify_ha.py`: one device per entry, `State` enum sensor, check `problem` sensors | Device is STD-owned; no `connections`; no "last seen" |
| Channels | `notify.py` registry, `mqtt` type, write-only secret, `test()` | No push/alert channel types; no alert engine |
| Filters / grouping | `view_helpers.group_and_sort_services`; `group_by` group/stack/host; status filter; query-string state | No tags, no saved views, no per-user home |
| Sources | `service_entry.source`: `notifier` / `manual` | No inventory sources |

## 4. Data model overview

New concepts, each one table unless noted:

```
tag ──< entry_tag >── service_entry ──< entry_interface
                          │  kind (service | device)
                          │  monitor_profile_id?  alert_policy_id?   (explicit assignment)
                          │  profile_overrides JSON                   (per-field overrides)
                          └──< health_check  (+ template_id?, + override cols already NULL-able)

monitor_profile ──< check_template
alert_policy  >── notification_channel (many-to-many)
assignment_rule  (match tag/group/kind/source → monitor_profile, alert_policy; priority)
saved_view
inventory_source  (technitium | unifi | ha; like notification_channel)
discovered_device (inbox of MACs seen but not adopted, + ignore flag)
```

All schema via Alembic, with FK indexes in the same migration (CLAUDE.md). Backups export
every new table.

## 5. Entries for devices

### 5.1 `kind`

`service_entry.kind`: `service` (default, all existing rows) or `device`. It's orthogonal
to `source`: a device can be `manual` or come from an inventory source; a service can be
`notifier` or `manual`. Views and alert policies can key off `kind`. Display:
- device entries show the MAC / IP / network instead of the Docker pill;
- device entries are never "stale" in the Docker sense.

### 5.2 Interfaces

`entry_interface`: `entry_id`, `mac` (normalised lower-case colon form, **unique** across
active rows), `ip`, `hostname`, `network` (scope or VLAN name), `is_primary`, `source`
(`technitium` / `unifi` / `manual`), `last_seen_at`, plus `observed` JSON for link facts
(UniFi: AP or switch + port, SSID, RSSI, uplink, online flag).
- Multi-NIC hosts (em-dockha01 has 3) get one entry with several interfaces.
- `observed` is pure observation, overwritten on each sync. Same rule as the notifier
  capture columns: never editable in the UI.

### 5.3 Identity

- Device identity is the **MAC of an interface**, not `(host, container_name)`.
- A device entry stores its display name in `container_name` (as manual entries do today)
  with `host` NULL.
- The `(host, container_name)` duplicate check must not block two devices that share a
  name. **Reviewer: check the Add duplicate check and the register adoption path.**
  `upsert_service` adopts an unlocked *manual* entry with a matching `(host,
  container_name)`. Device entries must never be adopted by a register.

### 5.4 Placeholders

Check targets may use `{ip}`, `{hostname}`, `{mac}` and `{name}`, resolved from the primary
interface. Resolution happens when the check is materialised or re-rendered (§7.2), not
in the worker. The scheduler stays as it is and never touches the DB from workers.

## 6. Inventory sources (getting devices in)

### 6.1 Sources and what each covers

| Source | Gives | Misses |
|---|---|---|
| **Technitium DHCP reservations** (API, all scopes) | intended inventory: name, MAC, IP, scope | static-IP hosts (VMs from `new-vm.sh`, UDM), anything the UDM serves (Cameras/48, Guest), macvlan containers |
| **UniFi** (Integration API clients + devices) | everything actually on the wire, incl. static and camera hosts; online flag; AP/port/RSSI | the names you intended; offline devices age out of its client list |
| **Home Assistant** (later) | Zigbee / Z-Wave devices (no IP) and HA's own availability | — |

Recommended split: **Technitium = what should exist, UniFi = what does exist plus link
facts.**

### 6.2 Shape

An `inventory_source` table, modelled on `notification_channel`:
- `type` (registry with pydantic config, `extra="forbid"`), `name`, `enabled`, JSON
  `config`, write-only `secret`, `test()`, `sync()`.
- A sync job (APScheduler, e.g. every 5 min) runs each source.
- Sync is reconcile-style. Network I/O runs off the scheduler thread; writes happen in one
  place.

Rules:
- **Create:** a Technitium reservation with no matching MAC → new `device` entry, `source =
  technitium`. Auto-create vs inbox is per source (`auto_create`: default on for Technitium,
  off for UniFi).
- **Update:** observation fields (IP, hostname, scope, `observed`) are overwritten.
  Operator-owned fields (name after a UI rename, group, tags, profile, description) follow
  the provenance rule: `ui_edit` beats sync, mirroring URL provenance. Fields without a
  provenance column today (icon, see FUTURE "register overwrites") must not be clobbered
  by sync.
- **Gone:** a reservation removed → the entry is flagged `inventory_missing`. Never
  auto-deleted. The operator soft-deletes.
- **UniFi-only MACs** (not reserved, not an existing interface) go to the
  `discovered_device` inbox: MAC, last IP, hostname, vendor (OUI), first/last seen. Actions:
  **Adopt** (creates an entry, optionally with a reservation-style name), **Attach to
  entry** (adds an interface, e.g. a VM's static NIC), **Ignore** (sticky). This is also an
  unknown-device detector.

Open: should sources live in STD (pull) or in a separate producer that uses the management
API (as the notifier does for Docker)? Leaning **in STD**: there's no per-host agent to run,
and credentials sit next to the channel secrets. **Reviewer: weigh against the "notifier is
a separate app" principle.**

### 6.3 Global enable switch and cleanup

**Scope.** Network inventory covers device entries, inventory sources, the
discovered-device inbox, and the HA merge mode for devices. It sits behind one setting,
`inventory_enabled`, **default off**. Tags, saved views, monitor profiles and alert
policies are core features. They are not behind this switch, because they apply to Docker
and manual entries too.

**Off (default or after disabling):**
- No source syncs run. The sync job checks the flag every tick, so no restart is needed.
- Sources, the inbox and the device-specific UI (the MAC/IP/network columns and the
  "Devices" settings tab) are hidden.
- The API returns 404 or `feature_disabled` for inventory endpoints, and MCP tools say the
  feature is off.
- Fresh installs and upgrades see no change.

**Turning it on:** Settings → Inventory → Enable. Sources are then added one by one, each
also `enabled` off by default. Nothing is created until a source is enabled and has synced.

**Turning it off:** a confirm dialog with three choices:
1. **Keep entries.** Sync stops. Existing device entries stay as ordinary entries and keep
   their checks, history and HA entities. They're simply no longer updated.
2. **Remove entries created by inventory (soft delete).** Every entry whose `source` is an
   inventory source type (`technitium`, `unifi`, `ha`) is soft-deleted. They can be
   restored from the existing soft-delete view. Their checks stop, and the MQTT/HA
   reconcile clears their topics and discovery configs, as for any soft delete.
3. **Remove and purge.** Same as 2, then a hard delete of those entries, their interfaces,
   checks and history, plus the inbox and ignore list.

**Rules:**
- The dialog shows counts first: "N device entries, M checks, K inbox rows".
- Device entries created **by hand** (`source = manual`, `kind = device`) are never
  removed by cleanup. They're listed separately as "kept (manual)".
- Inventory-created entries the operator adopted further are still inventory-created.
  Cleanup removes them, but they're listed by name so nothing disappears unseen.
  "Adopted further" means renamed, or given a group, tags or extra checks.
- **An interface attached to a manual or notifier entry** (e.g. a VM's static NIC) is
  removed. The entry itself stays.
- Source definitions (config + secret) are kept unless purge is chosen, so re-enabling
  doesn't mean re-entering credentials.
- The audit log records the disable and the cleanup choice with counts.
- Cleanup also runs on its own, without disabling: "Remove entries from source X". This is
  used when one source is deleted.

**Re-enabling after a soft-delete cleanup:** sync must **restore** soft-deleted rows with
a matching MAC rather than create duplicates. That keeps the operator's history and
settings. The unique-MAC constraint must therefore consider soft-deleted interfaces.

## 7. Monitor profiles

### 7.1 What a profile holds

`monitor_profile`: `name` (unique), `description`, and nullable fields:
- `interval_seconds`, `timeout_seconds`
- `fail_threshold`: consecutive failures before a check counts as **down** (default 1 =
  today)
- `recover_threshold`: consecutive successes before it counts as **up** again (default 1)
- `flap_window_minutes` + `flap_max_changes`: more state changes than this in the window →
  the entry shows a flapping marker
- `degraded_is_problem` (does yellow count as a problem for alerting / HA)

Plus its `check_template` rows: `kind` = service, `check_type`, `target` template (`tcp
{ip}:6053`, `http http://{ip}/`, `ping {ip}`), `mode`, `verify_tls`, DNS / cert fields,
`enabled`, `name`.

Seeded profile **`Default`**: every field NULL. NULL means use the global settings, so
upgrading changes nothing.

### 7.2 Inheritance, not forking

Resolution order for every field, first non-NULL wins:

```
check row field  →  entry.profile_overrides[field]  →  effective monitor profile  →  global setting
```

- `health_check.interval_seconds` / `timeout_seconds` already mean "NULL = global"; they
  become "NULL = inherit".
- **Templates are materialised**: each template creates a real `health_check` row per
  entry (`template_id` set), so the scheduler, history, MQTT topics and HA discovery all
  keep working unchanged.
- Editing a template updates its materialised rows' template-owned fields in one reconcile.
  Fields the operator overrode on the row are kept.
- Removing a template disables its rows. It doesn't delete them, so history isn't lost.
- An entry can still add its own service checks (`template_id` NULL).
- UI marks every inherited vs overridden field and offers **reset to profile** per field.
  "Fully custom" is just every field overridden. There is no separate mode.
- Saving a profile shows "affects N entries / M checks" first.
- A profile in use can't be deleted (reassign first).
- All profile edits go to the audit log.

### 7.3 Thresholds change health semantics

Today a check's state is `last_ok`. With `fail_threshold > 1`:
- **check state:** `up` | `pending` (failing, below threshold) | `down` | `unknown`;
- **roll-up:** `pending` counts as **degraded** (yellow), never down.

This touches `health_state.entry_health`, `check_counts`, the MQTT check payload (`ok`
stays the raw last result; `state` gains `pending`), HA (the `problem` sensor is ON only for
`down`; the entry enum gains no new value), and the badges.
**Reviewer: this is the riskiest change. Check every reader of `last_ok` and
`consecutive_failures`.** It also needs a `consecutive_successes` counter for
`recover_threshold`.

### 7.4 Assignment (which profile an entry gets)

First match wins:
1. **Explicit** `service_entry.monitor_profile_id`. This is set in the UI or API, and
   later by a notifier label (`dockernotifier.std.profile`). The label is a **register
   contract change**: STD ships the field first and the notifier follows.
2. **Assignment rules**, ordered by priority. Each rule matches any of tag, group, kind and
   source (AND within a rule), and sets a monitor profile and/or an alert policy. Example:
   tag `shelly` → monitor `Shelly`, alert `Record only`.
3. **Group default** (`group.monitor_profile_id`).
4. **Global default** (setting, initially `Default`).

The entry page shows the effective profile **and why** ("via rule #3: tag `shelly`").
- The effective profile is computed on read; cache it if needed. **Reviewer: decide where
  the cache lives given the single gunicorn worker.**
- A change to rules, tags or group triggers the template reconcile for the affected entries
  (same pattern as `notify.request_sync()`, a debounced commit listener).

## 8. Alert policies

Alerting doesn't exist yet. STD publishes state, and HA automations alert. This section
adds the engine. **It's the largest slice and the last one (§11).**

`alert_policy`: `name`, channels (many-to-many to `notification_channel`),
`alert_on` (`down` | `down_or_degraded`), `delay_minutes` (state must hold this long),
`renotify_minutes` (0 = once), `notify_recovery` (bool), `quiet_hours` (start/end/days, or
none), `record_only` (never send; health still tracked).

Seeds:
- `Default`: today's behaviour, sends nothing, because no push channel exists yet.
- `Record only`.

Same inheritance and assignment as §7. An entry override is per field, and rules can set
both profiles.

Engine:
- Transitions come from the scheduler's existing change detection
  (`record_check_result` → roll-up change).
- An `alert_state` row per entry holds `since`, last sent, the episode id and whether
  recovery was sent.
- A job evaluates delays, renotify and quiet hours each minute.
- Sends go through `notify.enqueue`, never blocking.

New channel types:
- `ntfy` (first; simple HTTP)
- `webhook`
- later `email` and `gotify`

The `mqtt` channel gains an optional alert event topic. HA can then automate on alert
events instead of raw state.

Maintenance / snooze (per entry, until a time) suppresses alerts but keeps history.

## 9. Tags and saved views

### 9.1 Tags

- `tag` (`name` unique, `colour`) plus `entry_tag`. Assign them in the edit UI or the API,
  through assignment by sync sources (e.g. "tag every entry from scope CrzyIoT as `iot`"),
  and later through a notifier label (contract change).
- Tags are a **filter**, never a grouping axis by default.
- Optional `group_by=tag` (an entry appears once per tag, in every matching bucket) is an
  extension. **Reviewer: does `view_helpers` assume one bucket per entry?**

### 9.2 Saved views

`saved_view`: `name`, `view` (`/`, `tiled`, `compact`), and `query` (JSON of everything the
query string carries today: `group_by`, `sort_in_group`, `show_urlless`, status filter,
plus new `tags_any`, `tags_all`, `tags_none`, `kind`, `source`, `host`, `group`), and
`show_uptime` / strip range.
- Views are **shared** (one homelab, one set).
- The **home view** is per user (`user.home_view_id`), falling back to a global default.
- A drop-down in the filter bar lists views. **Save as view** stores the current state.
  The URL stays the source of truth, so a view is just a named query string and is still
  bookmarkable.
- Editing a view's filters changes what everyone sees under that name.

### 9.3 Flapping at a glance

- The inline strip gains a **7d** option (168 hourly bars; `health_history.strips()` today
  is 24h only).
- Tiles and rows get a small **flap badge** when the entry changed state more than N times
  in 24h. It's computed from `health_result` transitions, or from a per-check
  `transitions_24h` counter maintained in `record_check_result`. That's cheaper.
  **Reviewer: pick one.**

## 10. Home Assistant: STD health on the existing device

### 10.1 Mechanism

- HA's device registry merges devices that share an identifier **or a connection**.
- If the STD entry device config carries `connections: [["mac", "<mac>"]]` for a device
  entry, HA attaches STD's entities to the device ESPHome (or Shelly, or UniFi) already
  created with that MAC.
- The `State` enum sensor then appears on the "hotwater circ pump" device page.

Per entry: `ha_device_mode` = `own` (today, an STD device) | `merge` (add connections, so
STD's entities join the existing device). Default: `merge` for `kind=device` with a MAC,
`own` otherwise.

**Gotchas to verify before building (HA behaviour, not STD):**
- When the second integration supplies `name`, `model`, `manufacturer`, `sw_version` or
  `via_device`, does HA overwrite the ESPHome device's values? If yes, merge-mode configs
  must send **only** `identifiers` + `connections`. Also check that MQTT discovery accepts a
  device block without `name`.
- `via_device: <hub>` must not be sent in merge mode, or the ESPHome device would show as
  "connected via STD".
- Removal: an empty retained config removes STD's entities. Confirm the merged device
  keeps its ESPHome side and only drops STD's config entry.
- ESPHome reports its MAC as a connection in the format HA normalises (`format_mac`).
  Confirm STD's normalised MAC matches.

### 10.2 What the entity shows

- **`STD Health`**: the existing entry `State` enum (up / degraded / down / unknown /
  none). In merge mode, name it `STD Health` rather than `State`, because it sits among the
  device's own entities.
- **`STD Last seen`**: a `sensor` with `device_class: timestamp`. HA renders it as "x
  minutes ago" natively.
  - Value: the most recent successful check time across the entry's counted checks.
  - **Conflict:** PRD 17.1 publishes **changes only**, so a last-seen value would freeze
    while the device stays up. Options:
    - (a) publish `last_seen` on a throttle (at most every 5 min per entry, only while up),
      a narrow exception to 17.1;
    - (b) show `since` (last state change) instead, which is "up since 3 days ago".
      Accurate, and needs no extra publishing.
  - Recommend **(b) now, (a) as an opt-in per channel**.
- Attributes (already on the state topic): failing checks and messages, plus for devices
  the IP, network, AP/port and RSSI from `observed`. These are the facts you need when
  troubleshooting at the physical layer.

## 11. Suggested release split

Each slice ships standalone and is useful on its own.

| # | Slice | Why this order |
|---|---|---|
| 1 | **Tags + saved views + home view + 7d inline strip + flap badge** | Pure STD, no external systems; improves today's 52 entries |
| 2 | **Monitor profiles**: thresholds / `pending`, templates (materialised), inheritance, assignment rules (tag/group/global) | Needed before devices arrive in bulk; riskiest semantics change, so ship it alone |
| 3 | **Device entries**: `inventory_enabled` switch + cleanup (§6.3), `kind`, interfaces, placeholders, Technitium source, `inventory_missing` | Devices arrive tagged and pick up profiles through rules |
| 4 | **UniFi source + discovered-device inbox + link facts** | Fills the static/camera gaps and adds the unknown-device list |
| 5 | **HA merge mode + `STD Health` / `STD Last seen`** | Needs MACs (slice 3); small once the HA gotchas are verified |
| 6 | **Alert policies + ntfy/webhook channels + snooze** | Largest; depends on thresholds (2) |
| later | HA inventory source (Zigbee/Z-Wave), notifier labels for tags/profile (contract change, STD first), `group_by=tag` | |

## 12. Reviewer checklist

Please answer against the code on `dev`:

1. §5.3: the duplicate check, register adoption and the `(host, container_name)` index with
   many `host IS NULL` device rows.
2. §7.3: every reader of `last_ok`, `consecutive_failures` and check state
   (`health_state`, `notify_state`, `notify_ha`, `health_history`, templates, the
   management API serializers, MCP). What breaks if `pending` is added?
3. §7.2: does materialising template checks fit the `check_counts` / URL-kind rules and the
   "exactly one internal_url / external_url per entry" invariant? Device entries have no
   URLs. Do they still need the two URL check rows?
4. §6.2: where sync writes happen given the scheduler-thread-does-all-writes rule and one
   gunicorn worker. Run it as an APScheduler job or on the health thread?
5. §9.2: how the query-string view state is parsed today. Can a saved view be a stored
   query string without a second parser?
6. §9.3: cost of a 7d strip for ~300 entries via `/health/strips` (the 500-id cap, one
   query).
7. Scale: ~300 entries × 2–3 checks at 60 s with 8 workers and `ping` sending 3 packets.
   Tick or pool limits? HA discovery for ~300 devices on reconnect: is the full sync
   bounded by the 1000-event queue?
8. Backups / restore: new tables and the "older backup without the field" defaults.
9. Management API + OpenAPI registry (`mgmt_openapi.OPERATIONS`, tests enforce it) and MCP
   tool surface for every new object.
10. Anything here that contradicts the PRD, decisions.md or CLAUDE.md rules.
11. §6.3: the enable switch and cleanup.
    - Where to gate it (blueprint-level check vs per route; scheduler job; MCP).
    - Can cleanup reuse the existing soft-delete / purge paths and the MQTT reconcile
      unchanged?
    - Does restore-on-re-enable by MAC conflict with the soft-delete semantics in PRD
      §12.5?
