# MQTT and Home Assistant

The full guide to notification channels, published state and Home Assistant
discovery. The overview is in the [README](../README.md#notifications-and-home-assistant).

## Channels

STD can publish to an MQTT broker (the first notification channel; state
publishing and Home Assistant discovery build on it). Configure it under **Settings → Notifications** (admins only).

1. **Add the broker.** Click **Add channel**. In the dialog: name, host, port
   (1883, or 8883 with TLS), a **base topic** (default `std`; a trailing `/`
   is dropped), and optional username and password. Under **Advanced**: a
   client id (default `std-<instance id>`), QoS (1 by default), keepalive and
   "skip certificate verification" for a self-signed broker. Turn on
   **Enabled** and save. Each channel is a card; **Edit** reopens the dialog,
   and a save that fails keeps it open with what you typed.
2. **Check it.** **Send test** (next to Save in the dialog, or in a saved
   channel's ⋯ menu) connects with the values currently in
   the form (saved or not) and publishes a JSON message to
   `<base topic>/test` (not retained). Success or the reason for the failure
   shows right next to the button (a broker that does not answer is reported within about 5 seconds). Subscribe with
   `mosquitto_sub -t 'std/#' -v` to watch.
3. **Watch the status.** Each card shows connected, connecting,
   error (with the last error) or disabled, and refreshes while the section is
   open. The **Enabled** switch turns a channel off (it asks first) or on; the
   ⋯ menu also has **Scan for orphans**, **Purge MQTT and Home Assistant** and
   **Delete**.

STD announces itself on `<base topic>/status`: `online` (retained) when it
connects, and `offline` (retained) as the broker's last will if STD
disappears, or when it shuts down cleanly. STD reconnects by itself, and
editing, disabling or deleting a channel takes effect at once, without a
restart.

## Published state

Everything below is retained, and topics use database ids so a rename never
moves them (`<base>` is the channel's base topic, `std` by default):

| Topic | What it carries |
|-------|-----------------|
| `<base>/status` | `online` / `offline` |
| `<base>/entry/<entry id>/state` | JSON: roll-up `state` (`up`, `degraded`, `down`, `unknown`, `none`), `std_entry_id`, `name`, `host`, `group`, `source`, `dashboard_url` (a path), `since`, `checks` (`{up, down, unknown}`) |
| `<base>/entry/<entry id>/check/<check id>` | JSON: `ok`, `state`, `std_entry_id`, `entry_name`, `host`, `group`, `source`, `dashboard_url`, `check_type`, `target`, `latency_ms`, `status_code`, `message`, `consecutive_failures`, `last_checked_at`, `last_change` |
| `<base>/summary` | JSON: `{up, degraded, down, unknown, none, total}` over active entries |
| `<base>/stream/<stream id>` | JSON, one per inventory stream: `stream_id`, `display_name`, `status` (`pending`, `enabled`, `disabled`, `ignored`), `producer`, `producer_version`, `last_snapshot_at`, `last_applied_at`, `counts` (`{active, missing, pending_offers}`), `item_count`. Entry topics stay under `entry/<entry id>`; they never move under a stream. |

```sh
mosquitto_sub -t 'std/#' -v
```

STD publishes when a check's result flips between ok and failing (and for its
first result) or an entry's roll-up changes, not on every result. The full set
is republished whenever STD (re)connects to the broker and every 10 minutes,
and a subscriber that joins late gets the current state at once because it is
retained. Deleted, soft-deleted or disabled entries and checks have their
topics cleared (an empty retained message). Checks that are disabled or
cannot run (for example no URL) have no topic.

## Home Assistant

Tick **Add to Home Assistant** on the channel (Home Assistant's MQTT
integration must use the same broker) and STD publishes retained MQTT
discovery. Optional: **Discovery prefix** (default `homeassistant`, Home
Assistant's default) and **Device name prefix** (default `STD`).

What gets created:

- An **STD hub device** with a connectivity sensor (STD online or not) and
  sensors for the number of entries that are up, degraded, down and unknown.
- One **device per published entry**, named `<prefix> <entry name> (<host>)`
  (for example `STD Plex (nas1)`; an entry with no host is `STD Plex`, and the
  host tells apart same-named entries on different hosts), linked to the hub (a stream entry is linked to its stream's device instead), with a **State** sensor (`up`, `degraded`,
  `down`, `unknown`, `none`) and one **problem** binary sensor per check named
  after the check (`HTTP`, `TCP 443`, `Container`, ...). The sensor is on when
  the check is failing, plus a **Since** timestamp sensor (when the entry
  last changed state). Docker entries show the image tag as the software
  version.
- One **device per inventory stream** that has at least one published entry,
  named `<prefix> <stream name> stream`, linked to the hub, with a **Status**
  sensor, **Active entries** and **Missing entries** count sensors and a
  **Problem** binary sensor (on while the stream is stale) read from
  `<base>/stream/<stream id>` (which also carries `stale`). Its configs are
  removed with the stream. An entry's state topic carries `missing` and
  `missing_since` for stream entries.
- Entity ids start with `std_` and include the host (for example
  `binary_sensor.std_plex_nas1_http`), so
  they are easy to find. The entry's group, host, source, check type, target,
  latency, message and last change are **attributes**, not areas.

Entries are **opt-in**: nothing is published until you tick **Publish to Home
Assistant** on an entry (Add or edit page), or pick several in **Settings →
Home Assistant**, your entries grouped by source (Docker, Manual, each stream;
collapsed, with a checkbox per group), a search box that opens the groups that
match, **Select all** / **Select none** (they act on the entries the search
shows) and one **Save** that applies every change at once. The top of the
section lists the channels that publish discovery and how many entries are
published. Within a published
entry its checks appear automatically; untick **Publish to Home Assistant** on
a single check to leave it out. The management API and MCP carry `ha_publish`
on entries and `ha_exclude` on checks. Unticked, deleted or disabled entries
and checks are removed from Home Assistant, as is everything when you untick
**Add to Home Assistant**. The hub device always appears while the channel's
**Add to Home Assistant** is on. Deleting a channel offers to remove its data
from the broker first (see [Cleaning the broker](#cleaning-the-broker)). When
Home Assistant restarts, STD republishes everything.

## Purge and republish

Two clean-slate tools, both admin only, for when Home Assistant shows stale
devices or old entity ids:

- **Settings → Notifications → Purge MQTT and Home Assistant** (per channel)
  empties the broker of STD: every retained message under the channel's base
  topic and every STD discovery config (this STD install's devices only;
  other STD installs and other Home Assistant devices are left alone, and so is
  `<base topic>/status`). The confirm dialog has **Republish afterwards**, on
  by default: STD waits about 2 seconds for Home Assistant to process the
  removals and publishes everything again, so devices come back as new. Turn it
  off to leave the broker empty (for example before removing STD); it stays
  empty until something changes or the channel reconnects, and the periodic
  10-minute republish does not undo it. The result (topics cleared, state and
  discovery) shows next to the channel. The channel must be enabled and
  connected.
- **Purge and republish to MQTT/HA** on an **entry's edit page** (shown when a
  channel is enabled) does this for one entry on every channel: its state
  topic, check topics and device are removed, then published again. Use it
  after renaming an entry, since Home Assistant keeps entity ids it has
  already registered; the recreated device gets fresh ones. An entry that is
  not published to Home Assistant only has its state topics cleared and
  republished.

- **Purge MQTT/HA** on a **stream's row** in Settings → Streams (shown when a
  channel is enabled) does this for every entry of the stream in one batch,
  soft-deleted ones included, plus the stream's status topic and its Home
  Assistant device. Afterwards STD publishes what is still eligible: entries
  that are gone, or not published to Home Assistant, stay cleared.

The same actions are `POST /api/v1/notifications/channels/<id>/purge`
(`{"republish": true}`), `POST /api/v1/entries/<id>/notifications/purge` and
`POST /api/v1/streams/<stream id>/notifications/purge` in the management API,
and the `purge_notification_channel`, `purge_entry_notifications` and
`purge_stream_notifications` MCP tools (write key). They take several seconds.

## Cleaning the broker

- **Delete** (Settings → Notifications) shows **Remove this channel's data from
  the broker first**, ticked by default: the retained topics, the discovery
  configs and `<base>/status` are cleared (no republish), then the channel is
  deleted. If the channel is disabled or its broker can't be reached, nothing
  is deleted and the dialog offers **Delete anyway**.
- **Disable** offers the same option, unticked by default; `<base>/status`
  then reads `offline`.
- **Changing the base topic** (or, with Home Assistant on, the discovery prefix
  or device name prefix) shows **Remove the old topics from the broker**, ticked
  by default: STD clears everything under the old base (its `status` too) and
  this install's old discovery configs, then switches. The last 5 previous
  bases are remembered per channel.
- **Scan for orphans** (per channel) lists the retained STD topics that STD no
  longer publishes, under the current base, the remembered previous bases, a
  base you type, and this install's discovery configs. It is a preview; **Clear
  N orphans** removes exactly what was listed. Only topics shaped like STD's own
  (`status`, `summary`, `entry/<id>/...`, `stream/<id>`, discovery configs) are
  listed.

In the management API: `DELETE /api/v1/notifications/channels/<id>?cleanup=false`
skips the cleanup (default true), `PATCH` takes `cleanup` (default true for a base
change, false for a disable), `GET .../previous-bases`, and `POST
.../orphans/scan` and `.../orphans/clear`. MCP: `delete_notification_channel`,
`update_notification_channel`, `list_notification_previous_bases`,
`scan_notification_orphans`, `clear_notification_orphans`.

## Dashboard card examples

Example [auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
cards:

```yaml
# Every failing check
type: custom:auto-entities
card: {type: entities, title: STD failing checks}
filter:
  include:
    - entity_id: "binary_sensor.std_*"
      state: "on"
```

```yaml
# Every check in one STD group
type: custom:auto-entities
card: {type: entities, title: Media}
filter:
  include:
    - entity_id: "binary_sensor.std_*"
      attributes: {group: Media}
```

```yaml
# Everything STD created, by device manufacturer
type: custom:auto-entities
card: {type: entities, title: Service Tracker Dashboard}
filter:
  include:
    - device_manufacturer: Service Tracker Dashboard
```

## Channel password and threading

The password is write-only: the form shows only that one is set, a blank
field keeps it and a checkbox removes it; it is never returned by the API,
written to the log or recorded in the audit log. Channels are also managed
through the [management API](../README.md#management-api)
(`/api/v1/notifications/channels`) and the MCP server.

STD sends its MQTT traffic from one background thread, so a slow or offline
broker never delays health checks or the dashboard.

## Not included

A "Check now" button and per-result latency sensors (see
[FUTURE.md](FUTURE.md)).
