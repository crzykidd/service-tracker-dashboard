# Design: network inventory, tags and views, monitor profiles and alert policies

**Status:** draft, revised after code review (2026-11-17). Nothing here is scheduled.
This file is input to the PRD. Once a slice is planned it moves into a PRD section and
this file links there.
**Author:** operator + Claude (design session in homelab-configs, 2026-11-17; code review
and operator decisions in this repo the same day).
**Code read:** first draft against `8bd2233`, review against `dev` at `091d291` (after
notif-04 HA opt-in and notif-05 purge). Trust the code where they disagree.
**Review:** findings are in [§12](#12-review-findings). The revision folded the
operator's answers into §2, §5, §6 and §11. A second revision the same day replaced the
in-STD Technitium source with a **stream ingest API plus a Technitium sidecar in its own
repo** (§6). UniFi, the discovered-device inbox and the backup-format change are parked in
`docs/FUTURE.md`.

---

## 1. Goal

STD becomes the inventory and health record for **everything on the network**, not just
Docker containers: ESPHome nodes, Shelly relays, Wi-Fi bulbs, cameras, APs, switches, VMs
and hypervisors. Three outcomes:

1. **One place to see health and history for any device.** "Is the hot-water circ pump
   flapping?" is answered by the device's 7-day uptime strip.
2. **A troubleshooting signal inside Home Assistant.** The HA device page for an ESPHome
   node shows an `STD Health` value (green / yellow / red) and how long STD has seen it in
   that state. If STD says it's up but HA can't see it, the problem is HA or the
   integration. If neither sees it, the problem is physical (power, Wi-Fi, cabling).
3. **Manageable at hundreds of entries.** Device-type defaults are set once and inherited.
   Changing a default updates every device that uses it. Views keep the everyday dashboard
   clean.

Non-goals:
- replacing HA's own device availability;
- controlling devices;
- a public status page (still parked in FUTURE.md);
- an unknown-device detector (UniFi; parked, see §6.9).

## 2. Operator decisions (2026-11-17)

From the design session:
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
- **Network inventory is off by default**, and disabling it offers to **clean up the entries
  it created**. With streams this is per stream: a new stream arrives pending and does
  nothing until enabled (§6.3, §6.6).

From the code review:
- **Sources, each with its own pill** (§5.1): `notifier` (Docker), `stream` (one pill per
  inventory stream, e.g. "DHCP") and `manual`. Manual is everything else, including hosts
  with hard-coded IPs and a static A record, such as em-pve01 and em-dockha01. The sources
  never overlap.
- **Inventory arrives through a stream ingest API, pushed by sidecars** (§6). STD owns the
  contract. The first producer is a **Technitium reference sidecar in a new repo** (§6.8)
  reading static reservations only. Every IoT device gets one, and that gives hostname, MAC,
  IP and scope. Anyone can write a sidecar for what they run (Pi-hole, …).
- **UniFi is dropped**: it would bring in phones and end-user devices that aren't wanted.
  The discovered-device inbox goes with it.
- **The Docker notifier stays on `/api/v1/register`.** It isn't moved onto streams.
- **Network filter per stream:** the operator picks which networks (DHCP scopes) to import,
  e.g. not Guest.
- **Deleting a stream entry asks whether to block it** (§6.7): "Allow re-adding" or "Don't
  re-add". Blocks are kept forever, in a list the operator can see and unblock.
- **A manual entry that matches a new stream item is offered for linking, never
  auto-converted** (§6.5), so its history, checks and HA settings are kept.
- **Backups:** the format question is parked. For now, add a nightly SQLite snapshot
  (§12.8).
- **Thresholds store a check state** (§7.3) rather than deriving it in each reader.

## 3. What already exists (don't rebuild)

| Need | Already in STD | Gap |
|---|---|---|
| Ping | `checker.probe_ping` (icmplib, NET_RAW) | 3 packets × 5 s timeout per reply; too slow for many dead devices (§12.7) |
| TCP / HTTP / DNS / cert checks | `checker.py`, §13.4, §15 | none |
| 7-day history | `health_result` + compaction, `health_history.bars(range=7d)` in the detail panel | The inline strip (`/health/strips`) is 24h only, and it loads raw rows through the ORM (§12.6). No flap metric. |
| Health colours | `health_state.entry_health`: up / degraded / down / unknown / none | No threshold or "pending" state; state is derived in 8 places (§12.2) |
| Per-check interval / timeout | `health_check.interval_seconds` / `timeout_seconds`, NULL = global | The NULL-inherits pattern is reused for profiles |
| HA entity per entry | `notify_ha.py`: one device per entry, opt-in per entry (`service_entry.ha_publish`, default off), `STD <name> (<host>)` device names, `State` enum sensor, check `problem` sensors, purge per channel and per entry | Device is STD-owned; no `connections`; no "since" sensor |
| Channels | `notify.py` registry, `mqtt` type, write-only secret, `test()` | No push/alert channel types; no alert engine |
| Filters / grouping | `view_helpers.group_and_sort_services`; `group_by` group/stack/host; status and source filters; query-string state | No tags, no saved views, no per-user home; source filter knows only two values |
| Sources | `service_entry.source`: `notifier` / `manual` | No stream sources; about 12 branches treat "not manual" as "Docker" (§5.1) |
| Producer auth | `api_keys.py` scoped keys + `api_audit` | No `ingest` scope |
| Backups | Nightly YAML export of entries with nested checks | Not a table dump; no database snapshot (§12.8) |

## 4. Data model overview

New concepts:

```
tag ──< entry_tag >── service_entry
                          │  source (notifier | stream | manual)
                          │  stream_id?, stream_key?   (unique per stream, incl. soft-deleted)
                          │  mac, ip, network, attributes JSON   (stream entries; observation)
                          │  inventory_missing
                          │  monitor_profile_id?  alert_policy_id?   (explicit assignment)
                          │  profile_overrides JSON                   (per-field overrides)
                          └──< health_check  (+ template_id?, + state, + consecutive_successes)

monitor_profile ──< check_template
alert_policy  >── notification_channel (many-to-many)
assignment_rule  (match tag / group / source → monitor_profile, alert_policy, ha_publish; priority)
saved_view
inventory_stream  (one per producer stream; pending | enabled | disabled; latest snapshot)
inventory_block   ((stream_id, key) never to re-add)
stream_link_offer (stream item ↔ manual entry, awaiting an answer)
```

All schema goes through Alembic, with FK indexes in the same migration (CLAUDE.md).

Dropped from the first draft:
- `entry_interface`: a stream entry is one item, and the multi-NIC hosts are manual;
- `discovered_device` (the UniFi inbox);
- `inventory_source` (STD-side pullers), replaced by `inventory_stream`;
- `kind`: `source` covers it, and tags can mark manual hosts.

"DHCP entries" below is shorthand for entries of the Technitium sidecar's stream.

## 5. Entries for devices

### 5.1 Sources

| Source | What it is | Kept current by | Pill |
|---|---|---|---|
| `notifier` | Docker containers. Their DNS name is a CNAME to the parent host, so they never have a reservation | `/api/v1/register` | Docker |
| `stream` | Items from an enabled inventory stream, e.g. every Technitium static reservation | the stream's sidecar, by snapshot (§6) | the stream's `display_name`, e.g. DHCP |
| `manual` | Everything else: hard-coded IPs with a static A record (em-pve01, em-dockha01, the UDM, VMs), manual services | the operator | Manual |

They never claim the same thing, so there's no cross-source identity problem:
- Register adoption stays as it is: it only adopts unlocked `manual` entries with the same
  `(host, container_name)`. Stream entries are never adopted.
- Stream entries are matched by `(stream_id, stream_key)`, never by name.

**Prerequisite refactor** (start of the inventory slice). Today the code treats `source`
as two-valued, in two patterns:
1. `source == notifier`, meaning "this is Docker": stale check, Container check, adoption.
   These already behave correctly for `stream`.
2. `is_manual` / `!= manual`, used where the code means "not Docker":
   - the Docker pill and container fields in `tiled_dash.html` (134, 264) and
     `edit_entry.html` (216);
   - `models.py:276`;
   - the HA `model` string (`notify_ha.py:67`);
   - the two-value source filters (`view_helpers.py:88`, `routes_mgmt_api.py:512`);
   - restore (`routes_dashboard.py:536`, `540`).

Add `ServiceEntry.is_docker` and switch pattern 2 to it. Generalise the filters, the pill
and `VALID_SOURCES` to any source value. The pill reads the stream's `display_name`, and
the source filter gains one value per stream. Then adding `stream` touches only stream code.

### 5.2 Device fields

On `service_entry`, NULL for other sources:
- `stream_id` (FK, indexed) and `stream_key`: unique per stream, including soft-deleted
  rows (§6.6).
- `mac` (normalised lower-case colon form), `ip`, `network` (for DHCP, the scope name),
  `attributes` (JSON, the producer's free-form facts).
- `inventory_missing`: the key was absent from the latest snapshot (§6.4).

These are pure observation, overwritten by each snapshot and never editable in the UI.
That's the same rule as the notifier capture columns. The name is stored in
`container_name`, as manual entries do today, from the item's `name`. `host` is NULL.

The duplicate check (`entry_rules.find_duplicate`) and the restore clash checks key on
`(host, container_name)`. Stream entries skip them and are unique by stream key instead, so
a duplicate hostname never blocks a snapshot.

### 5.3 Placeholders

Check targets may use `{ip}`, `{hostname}`, `{mac}` and `{name}`. Resolution happens when
the check is materialised or re-rendered (§7.2), not in the worker. The scheduler stays as
it is and never touches the DB from workers. For a manual entry, `{ip}` and `{mac}` are
unavailable, and a template using them is skipped for that entry (shown in the UI).

## 6. Inventory: stream ingest API and sidecars

**Decision (2026-11-17):** STD doesn't pull from Technitium itself. It exposes a generic
**stream ingest API**. Separate sidecar services push inventory into it. The first is a
**Technitium reference sidecar in its own repo**. Anyone can write a sidecar for what they
run (Pi-hole, Kea, a Zigbee bridge) without a change to STD. This is the same split as
Docker today: STD owns the contract and producers follow it (CLAUDE.md ordering rule).

### 6.1 Streams

An `inventory_stream` row per producer stream:
- `stream_id` (producer-chosen slug, unique), `display_name` (the pill label, e.g. "DHCP"),
  `producer` + `producer_version`, `key_type` (`mac` for DHCP; `ieee` for Zigbee, …);
- `status`: `pending` | `enabled` | `disabled`;
- `api_key_id` (the key that created it), `first_seen_at`, `last_snapshot_at`,
  `last_item_count`, `last_error`;
- STD-side options: a `network` include/exclude list (e.g. leave out Guest). It's generic,
  because every item may carry `network`, and editable in the UI. The sidecar can also
  filter on its side.

The Docker notifier is **not** moved onto this API. It stays on `/api/v1/register`
(per-container upserts, the most-used contract) and is shown in Settings → Streams as the
built-in Docker stream.

### 6.2 Contract

`PUT /api/v1/streams/<stream_id>/snapshot` with an API key carrying the new **`ingest`**
scope (`api_keys.py` scopes, audited like the management API).

```json
{
  "display_name": "DHCP",
  "producer": "std-source-technitium",
  "producer_version": "0.1.0",
  "key_type": "mac",
  "items": [
    {"key": "aa:bb:cc:dd:ee:ff", "name": "shelly-pump", "ip": "10.0.40.21",
     "mac": "aa:bb:cc:dd:ee:ff", "network": "CrzyIoT",
     "attributes": {"scope": "CrzyIoT", "reservation_comment": "boiler room"}}
  ]
}
```

- **Full snapshot, not deltas.** Each PUT is the stream's complete current set. "Gone" is
  simply "in STD but not in this snapshot", with no TTLs or heartbeats to tune.
- **Core fields** (`key`, `name`, `ip`, `mac`, `network`) are validated strictly by
  pydantic (`extra="forbid"`), as `schemas.py` does for register.
- **`attributes`** is a free-form dict of string, number and boolean values, size-capped.
  STD shows it on the entry and passes stable values to MQTT, but never interprets it. A
  sidecar can add facts without an STD release, so the strict part of the contract stays
  small.
- `key` is the stream's identity for an item. `mac` is a separate optional core field,
  because HA merge mode (§10) needs a MAC whatever the key type is.
- Response: counts (created / updated / missing / blocked / pending-link / skipped by
  filter) so a sidecar can log what happened.
- Limits: a max item count and body size per snapshot. A snapshot over the limit is
  rejected whole, never applied partly.
- The contract gets its own PRD section and an OpenAPI entry, so third parties have
  something to code against.

### 6.3 Pending streams and enabling

- A snapshot from an unknown `stream_id` creates the stream as **`pending`**. It's accepted
  (`202`) and stored as the latest snapshot, but not applied.
- Settings → Streams shows: "New stream: DHCP (std-source-technitium 0.1.0), N items,
  last seen 2 min ago — **Preview** / **Enable** / **Ignore**".
  - Preview lists what would be created, linked or blocked.
- **Enable** applies the stored snapshot right away and every later one.
- **Disable** stops applying snapshots and runs the cleanup dialog (§6.6). Later PUTs are
  still accepted and stored.
- Pending is about the data, not trust: only a holder of an `ingest` key can create a stream
  at all. Revoking the key stops the producer.
- This replaces the first draft's single global `inventory_enabled` switch. A fresh install
  with no sidecars sees nothing new.

### 6.4 Applying a snapshot

Snapshots are applied in a request thread, in one transaction, under the same kind of
in-process lock as `upsert_service`. STD does no outbound network I/O here (the sidecar
did it), so nothing slow runs while the lock is held.

For each item that passes the stream's network filter:
- **New key** (not an existing entry of this stream and not blocked): first look for a
  manual entry to link (§6.5). Otherwise create an entry for the stream, named from `name`.
- **Known key:** overwrite the observation fields (`ip`, `mac`, `network`, `attributes`).
  The name follows provenance: a UI rename wins over the producer's name, mirroring URL
  provenance. Group, tags, profile, description and icon are operator-owned and never
  written by a snapshot.
- **Blocked key:** skipped (§6.7).

Then for every entry of this stream whose key isn't in the snapshot: flag
`inventory_missing`. Never auto-delete. The flag clears if the key comes back.

A soft-deleted entry of this stream whose key is in the snapshot (and not blocked) is
restored by clearing `deleted_at`, the same way register resurrects a deleted container
(PRD §12.5).

### 6.5 Linking a manual entry (offer, never automatic)

When a new item's `name` matches an active manual entry's name with no host (exact, ignoring
case), no entry is created. A pending link offer is recorded instead, shown in Settings →
Streams and on that entry's edit page: "Stream DHCP item `shelly-pump` (aa:bb:…) matches
this entry. Convert?"
- **Accept:** the manual entry joins the stream (source, stream, key and observation
  fields set). It keeps its id, history, checks, tags and HA settings.
- **Decline:** a new stream entry is created and the manual one is left alone.
- **Until answered:** nothing is created for that key.

A link can also be started from the manual entry's edit page ("Link to stream item…", pick
from the stream's unmatched items in its latest snapshot).

### 6.6 Disabling a stream and cleanup

Disabling a stream (or deleting it) opens a dialog with counts first ("N entries, M
checks"). Entries the operator customised (renamed, given a group, tags or extra checks)
are listed by name.
1. **Keep entries.** They stay, with their checks, history and HA entities, and are no
   longer updated.
2. **Remove (soft delete).** Every entry of this stream is soft-deleted and can be restored
   from Settings → Deleted. The commit listener's MQTT/HA reconcile clears their topics and
   discovery configs, as for any soft delete. One bulk commit means one sync.
3. **Remove and purge.** As 2, then a hard delete through `hard_delete_entry`, plus the
   stored snapshot and link offers. The block list is kept unless "also clear this stream's
   block list" is ticked.

Manual entries are never touched by cleanup. Linked entries (§6.5) belong to the stream
and are included. The audit log records the choice with counts. Re-enabling restores
soft-deleted rows by key (§6.4), so key uniqueness `(stream_id, key)` includes soft-deleted
rows.

### 6.7 Deleting a stream entry and the block list

Deleting an entry that belongs to a stream asks:
- **Allow re-adding:** an ordinary soft delete. The next snapshot that still contains the
  key restores it.
- **Don't re-add:** a soft delete, plus `(stream_id, key)` goes on `inventory_block`. The
  block records the name and IP at the time, when it was blocked and by whom. It's kept
  forever, including after the soft-delete retention purge hard-deletes the entry.

**Settings → Streams → Blocked** lists blocks with **Unblock**. The next snapshot then
restores the row or creates a new one. Whether a deleted stream entry returns depends only
on the block list.

### 6.8 Technitium reference sidecar (new repo)

A new repo and image, working name **`std-source-technitium`**: small, documented, and meant
to be copied.
- Reads **static reservations only** (never dynamic leases) from the Technitium API,
  optionally limited to configured scopes.
- Posts one full snapshot every N minutes (default 5) and once at start.
- Config by env: Technitium URL + token, STD URL + `ingest` key, `stream_id`,
  `display_name`, scopes, interval.
- Items:
  - `key` and `mac`: reservation MAC, normalised lower-case colon form;
  - `name`: the reservation hostname;
  - `ip`;
  - `network`: the scope name;
  - `attributes`: scope and reservation comment.
- Logs the STD response counts. Retries with backoff and never crashes on a failed post.
- Its own version line, CHANGELOG and GHCR image, adopting the same crzynet standards.
- Ordering: STD ships the ingest API first, then the sidecar.

Why a new repo rather than a mode in docker-api-notifier (which already talks to Technitium
DNS): a small standalone sidecar is the reference others copy for Pi-hole and the rest, and
it keeps the notifier's job (Docker → STD + DNS) unchanged.

### 6.9 Not now

- **UniFi:** dropped. It would import phones and laptops. It's now possible as a third-party
  or later sidecar (FUTURE.md).
- **Discovered-device inbox:** went with UniFi. A pending stream's Preview covers "what
  would arrive".
- **HA inventory sidecar** (Zigbee / Z-Wave, `key_type` `ieee`): later.
- **Multi-NIC entries:** the multi-NIC hosts are manual. If a stream ever needs several
  keys on one entry, add an interfaces table then.
- **Moving the Docker notifier onto streams:** not planned (§6.1).

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
- `ping_count`, `ping_timeout_seconds` (a device profile wants 1 packet / 1–2 s; §12.7)

Plus its `check_template` rows: `check_type`, `target` template (`tcp {ip}:6053`,
`http http://{ip}/`, `ping {ip}`), `mode`, `verify_tls`, DNS / cert fields, `enabled`,
`name`.

Seeded profile **`Default`**: every field NULL. NULL means use the global settings, so
upgrading changes nothing.

### 7.2 Inheritance, not forking

Resolution order for every field, first non-NULL wins:

```
check row field  →  entry.profile_overrides[field]  →  effective monitor profile  →  global setting
```

- `health_check.interval_seconds` / `timeout_seconds` already mean "NULL = global"; they
  become "NULL = inherit".
- **Templates are materialised**: each template creates a real service-kind `health_check`
  row per entry (`template_id` set). The scheduler, history, MQTT topics and HA discovery
  keep working unchanged.
- Materialising service-kind rows doesn't touch the "exactly one `internal_url` /
  `external_url` row per entry" invariant. DHCP entries keep their two dormant URL rows,
  which `check_counts` already ignores. Don't special-case them.
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

Today a check's state is derived from `last_ok`. With `fail_threshold > 1`:
- **check state:** `up` | `pending` (failing, below threshold) | `down` | `unknown`;
- **roll-up:** `pending` counts as **degraded** (yellow), never down.

**Decision: store the state.** Add a `health_check.state` column and
`consecutive_successes`, both written by `record_check_result` from the raw result and the
effective thresholds. Every reader uses `state`, and `last_ok` stays the raw last result.

This is required, not a tidy-up. Today change detection keys on `last_ok` flipping
(`record_check_result`'s return, `notify_state.py:227`, `:273`). With a threshold of 3, the
step from `pending` to `down` happens on the third failure while `last_ok` stays `False`, so
nothing would publish and HA would never see `down`. Change detection must key on `state`.

Readers to switch, as found in review (§12.2):
- `notify_state.check_state` and the change tracker;
- `health_history.py:134`, `mgmt_serializers.py:30`, the tint in `models.py:288`;
- `health_state.entry_health`;
- `routes_mgmt_api.py:952`, `routes_api.py:252`;
- `partials/check_result_text.html`.

History bars and strips keep the raw results, so flapping stays visible. The MQTT check
payload keeps `ok` (raw) and `state` gains `pending`. In HA, the `problem` sensor is ON only
for `down`, and the entry enum gains no new value.

Ship this alone (slice 2a, §11). It's the riskiest change.

### 7.4 Assignment (which profile an entry gets)

First match wins:
1. **Explicit** `service_entry.monitor_profile_id`. It's set in the UI or API, and later by
   a notifier label (`dockernotifier.std.profile`). The label is a **register contract
   change**: STD ships the field first and the notifier follows.
2. **Assignment rules**, ordered by priority. Each rule matches any of tag, group, source,
   stream and network (AND within a rule). It sets a monitor profile, an alert policy and/or
   `ha_publish`. Examples:
   - tag `shelly` → monitor `Shelly`, alert `Record only`;
   - stream DHCP + network `CrzyIoT` → monitor `IoT`, `ha_publish` on.
3. **Group default** (`group.monitor_profile_id`).
4. **Global default** (setting, initially `Default`).

The entry page shows the effective profile **and why** ("via rule #3: tag `shelly`").
- The effective profile is computed on read. If a cache is needed, keep it in process:
  there's one gunicorn worker. Invalidate it from the same commit listener that triggers
  the reconcile.
- A change to rules, tags or group triggers the template reconcile for the affected entries
  (same pattern as `notify.request_sync()`, a debounced commit listener).
- `ha_publish` from a rule: an explicit per-entry setting wins. Otherwise the rule decides.
  Ticking 300 boxes in the bulk picker isn't realistic.

## 8. Alert policies

Alerting doesn't exist yet. STD publishes state, and HA automations alert. This section adds
the engine. **It's the largest slice and the last one (§11).**

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
- Transitions come from the stored check state (§7.3) and the roll-up change.
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

- `tag` (`name` unique, `colour`) plus `entry_tag`. Tags are assigned in the edit UI or the
  API, and later through a notifier label (contract change).
- Tags are a **filter**, never a grouping axis by default.
- Optional `group_by=tag` (an entry appears once per tag, in every matching bucket) is an
  extension. `view_helpers` builds a dict of lists, so the bucketing itself is easy.
  **Unverified:** whether templates and JS (strips, detail panel) assume one DOM element per
  entry id. Check that before promising it.

### 9.2 Saved views

`saved_view`: `name`, `view` (`/`, `tiled`, `compact`), and `query` (the query string: today's
`group_by`, `sort_in_group`, `show_urlless`, `status`, `source`, plus new `tags_any`,
`tags_all`, `tags_none`, `host`, `group`), and `show_uptime` / strip range.
- View state is read only from the query string today (`_read_view_controls`,
  `_read_filters` in `routes_dashboard.py`). A saved view is a stored query string applied
  by redirect, with no second parser. It stays bookmarkable.
- Views are **shared** (one homelab, one set).
- The **home view** is per user (`user.home_view_id`), falling back to a global default.
  - The home redirect fires only on a bare `/` (no query string).
  - "Clear filters" needs a sentinel (`?view=none`). Otherwise you can never reach the
    unfiltered dashboard when a home view is set.
- A drop-down in the filter bar lists views. **Save as view** stores the current state.
- Editing a view's filters changes what everyone sees under that name.

### 9.3 Flapping at a glance

- **First, move the strip bucketing into SQL** (`GROUP BY check_id, bucket` with sample and
  failure sums). Today `strips()` loads every raw row through the ORM, which is already
  about 1.3 M objects at 300 entries for the 24h strip (§12.6).
- Then the inline strip gains a **7d** option (168 hourly bars).
- Tiles and rows get a small **flap badge**: the number of passing ↔ failing alternations
  between buckets in the last 24h, from the same aggregate query. No extra counter needs
  maintaining or rolling off. Bucket alternations approximate state changes, which is fine
  for a badge.

## 10. Home Assistant: STD health on the existing device

### 10.1 Mechanism

- HA's device registry merges devices that share an identifier **or a connection**.
- If the STD entry device config carries `connections: [["mac", "<mac>"]]`, HA attaches
  STD's entities to the device ESPHome (or Shelly) already created with that MAC.
- The `State` enum sensor then appears on the "hotwater circ pump" device page.

Per entry: `ha_device_mode` = `own` (today, an STD device) | `merge` (add connections, so
STD's entities join the existing device). Default: `merge` for entries with a MAC (stream
entries that send `mac`), `own` otherwise.
- Merge mode only applies to entries with `ha_publish` on (notif-04 opt-in). Rules can set
  `ha_publish` (§7.4).
- Option for later: an operator-entered MAC on manual entries, so a hard-coded-IP host could
  merge too.

**STD changes for merge mode.** `notify_ha.entry_device()` always sends `name`, `model`,
`manufacturer` and `via_device`. Merge mode needs a branch that sends **only**
`identifiers` + `connections`, subject to the checks below.

**Gotchas to verify before building (HA behaviour, not STD):**
- When the second integration supplies `name`, `model`, `manufacturer`, `sw_version` or
  `via_device`, does HA overwrite the ESPHome device's values? Does MQTT discovery accept a
  device block without `name`?
- `via_device: <hub>` must not be sent in merge mode, or the ESPHome device would show as
  "connected via STD".
- Removal: an empty retained config (or the notif-05 per-entry purge) removes STD's
  entities. Confirm the merged device keeps its ESPHome side and only drops STD's config
  entry.
- ESPHome reports its MAC as a connection in the format HA normalises (`format_mac`).
  Confirm STD's normalised MAC matches.

### 10.2 What the entity shows

- **`STD Health`**: the existing entry `State` enum (up / degraded / down / unknown / none).
  In merge mode, name it `STD Health` rather than `State`, because it sits among the
  device's own entities.
- **`STD Since`**: a `sensor` with `device_class: timestamp` reading `value_json.since` from
  the existing entry state topic (the payload already carries `since`). HA renders it as
  "up since 3 days ago". It needs no extra publishing, so PRD §17.1 (changes only) holds.
  - A real "last seen" value would freeze under changes-only publishing. If it's ever
    wanted, make it an opt-in per channel, published on a throttle (at most every 5 min per
    entry, only while up).
- Attributes (already on the state topic): failing checks and messages, plus `ip`,
  `network` and the stream's `attributes` for stream entries.
  - Add only stable fields to `notify_state._ENTRY_ATTRS`. A field that changes on every
    snapshot would trigger a full sync every 5 minutes. Producer `attributes` are free-form,
    so compare them by value before counting them as a change.

Both items are small and don't need MACs, so they can ship before merge mode.

## 11. Suggested release split

Each slice ships standalone and is useful on its own.

| # | Slice | Why this order |
|---|---|---|
| — | **HA naming + `STD Since`** (§10.2), DB snapshot backup (§12.8) | Small, no MACs needed; candidates for 0.10.0 with the notifications work |
| 1 | **Strip bucketing in SQL**, then tags + saved views + home view + 7d inline strip + flap badge | Pure STD, no external systems; the SQL rework makes the strips survive 300 entries |
| 2a | **Thresholds + stored check state** (§7.3) | Riskiest semantics change; also fixes the threshold publish blind spot; ship alone |
| 2b | **Monitor profiles**: templates (materialised), inheritance, assignment rules (tag/group/source/global, incl. `ha_publish`), ping count/timeout | Needed before devices arrive in bulk |
| 3a | **Stream ingest API** in STD: `is_docker` refactor, `inventory_stream` + `ingest` key scope, snapshot apply, pending / enable / disable + cleanup, network filter, link offers, block list, `inventory_missing`, Settings → Streams, OpenAPI + MCP | STD is the consumer, so it ships first (ordering rule); testable with `curl` and a fixture snapshot |
| 3b | **`std-source-technitium` sidecar** (new repo, §6.8) | Producer follows; devices arrive and pick up profiles through rules |
| 4 | **HA merge mode** | Needs MACs (slice 3b); small once the HA gotchas are verified |
| 5 | **Alert policies + ntfy/webhook channels + snooze** | Largest; depends on stored state (2a) |
| later | HA inventory sidecar (Zigbee/Z-Wave), third-party sidecars (Pi-hole, UniFi), notifier labels for tags/profile (contract change, STD first), `group_by=tag`, manual-entry MAC for merge mode | |

Open: what goes in 0.10.0 beyond what's on `dev`. The candidates are the first row.

## 12. Review findings

Code review on `dev` at `091d291`, against the first draft's checklist.

### 12.1 Duplicate check and register adoption (§5.3 of the draft)

- `find_duplicate` treats `host IS NULL` as one value, so two host-less devices with the
  same name would collide. The restore clash checks do the same
  (`routes_mgmt_api.py:759`, `routes_dashboard.py:1735`).
  **Resolved:** DHCP entries skip them and are unique by MAC (§5.2).
- Many `host IS NULL` rows don't hurt the non-unique `(host, container_name)` index.
- Register adoption matches `(host, container_name)` and only adopts `manual` rows.
  **Resolved:** DHCP entries are never `manual`, and Docker never has reservations (§5.1).

### 12.2 Readers of check state (§7.3)

State is derived from `last_ok` in 8 places, listed in §7.3. Change detection keys on
`last_ok`, which misses `pending` → `down`. **Resolved:** store `state` (§7.3).
`consecutive_failures` is only written by `record_check_result` and read by the payload
serializers, so it's safe.

### 12.3 Materialised templates and URL rows (§7.2)

These fit. Templates create service-kind rows only, so the URL-row invariant is untouched,
and dormant URL rows on devices are harmless.

### 12.4 Where inventory writes happen (§6.4)

First review: run an in-STD sync as an APScheduler job, not on the health thread. **Superseded
by the stream design:** STD makes no outbound calls. A snapshot is applied in the ingest
request, in one transaction, under an in-process lock (the `upsert_service` pattern). With one
gunicorn worker and SQLite WAL, no new rule is needed.
- Keep the apply fast at about 300 items: one query for the stream's existing rows, one for
  blocks, then a diff in Python.
- If it ever gets slow, store the snapshot and apply it on a scheduler job instead. The
  contract doesn't change.

### 12.5 Saved views and query-string state (§9.2)

There's one parser (`_read_view_controls` / `_read_filters`). A view is a stored query
string. Watch the home-view redirect loop (§9.2).

### 12.6 Strip cost (§9.3)

`strips()` loads every result row in range through the ORM, then buckets in Python. At 60 s
intervals that's about 1,440 raw rows per check per 24h. At 300 entries × 3 checks it's about
1.3 M ORM objects per page load, even before 7d. `MAX_STRIP_IDS = 500` caps entries, not
rows. **Resolved:** SQL aggregation first (§9.3).

### 12.7 Scale (~300 entries × 2–3 checks at 60 s, 8 workers)

- **Ping saturation.** `probe_ping` sends 3 packets with a 5 s timeout per reply, so a dead
  device holds a worker for up to about 15 s. With 8 workers (480 worker-seconds a minute),
  about 30 or more dead devices at 60 s saturate the pool. An IoT VLAN power cut would delay
  every check and distort thresholds and flap counts.
  **Resolved:** profile `ping_count` / `ping_timeout_seconds` (§7.1). Raising
  `health_check_workers` or icmplib `async_multiping` are fallbacks.
- **Per-tick re-read.** `select_due_jobs` runs every 5 s, loads every active entry, and
  lazy-loads `entry.checks` one query per entry (about 300 queries per tick).
  **Fix:** `selectinload(ServiceEntry.checks)`. Do it in slice 2b or 3.
- **HA discovery on reconnect is fine.** `full_sync` sends through `publisher.dispatch`, not
  the 1,000-event queue (`notify_state.py:406`), so the queue limit doesn't apply.
- **Volatile attributes.** Don't put fields that change often on watched entry attributes
  (§10.2).

### 12.8 Backups

The nightly backup is a YAML list of entries with nested checks (`jobs.py:555`). It isn't a
table dump: groups are carried by name, and notification channels aren't included. Restore
also skips host-less entries unless `source = manual` (`routes_dashboard.py:540`).

**Decision:** park the format question in FUTURE.md: back up everything, or only
operator-set state; format versioning; secrets. For now, add a nightly SQLite snapshot made
with `sqlite3.Connection.backup()` (CLAUDE.md, WAL mode), saved next to the YAML backups
with the same retention. Restore is manual: stop the container, swap the file. It covers
every new table with no format work. The YAML restore still needs the source fix (§5.1)
when stream entries land.

### 12.9 Management API and MCP

Every new object needs its routes registered in `mgmt_openapi.OPERATIONS` (tests enforce
it) and MCP tools. That's a lot of surface, so each slice's PRD section lists its API and
MCP additions explicitly.

### 12.10 Contradictions with the PRD and CLAUDE.md

- The draft's `last_seen` (option a) contradicts PRD §17.1 (changes only).
  **Resolved:** `STD Since` (§10.2).
- The draft assumed HA devices publish by default. Since notif-04 they're opt-in
  (`ha_publish`). **Resolved:** rules can set it (§7.4).
- `models.py` documents `source` as `notifier` / `manual`. The slice 3 PRD section must
  update it, along with the register-adoption docstring in `routes_api.py`.
- Notifier labels for profile and tags are register contract changes: STD ships first
  (CLAUDE.md ordering rule). The draft already said this.
- **New cross-repo pairing.** CLAUDE.md "Cross-Repo Coordination" and PRD §19 describe one
  producer (the notifier). The slice 3a PRD section must add the stream contract and the
  Technitium sidecar repo, with the same ordering rule and a safe-degradation note (an older
  sidecar against a newer STD keeps working; `attributes` absorbs new facts).

### 12.11 Enable switch and cleanup (§6.3, §6.6)

- First review: one global `inventory_enabled` flag in `settings_store`, gated by a
  blueprint `before_request`. **Superseded:** enabling is per stream (pending → enabled), so
  there's no global flag. The ingest blueprint still checks the `ingest` scope in one place.
- Cleanup reuses the existing paths unchanged. A soft delete sets `deleted_at`, which the
  commit listener already turns into the MQTT/HA reconcile. Hard delete uses
  `hard_delete_entry`.
- Restore-by-key matches PRD §12.5's resurrect-on-register precedent. The case where an
  operator deliberately deleted a device is handled by the block list (§6.7).
