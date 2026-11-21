# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Stale inventory streams are flagged.** An enabled stream that sends no
  snapshot for twice its expected interval is **stale**: a red badge in
  Settings → Streams (with "No snapshot for 42 min (expected every 5 min)"), a
  red count on the header's Settings link, a `down` line in the health summary
  (API and MCP `health_summary`), `stale` on the MQTT topic
  `<base>/stream/<stream id>` and a **Problem** binary sensor on the stream's
  Home Assistant device. The interval is the one you set, else the one the
  sidecar advertises, else 15 minutes. Pending, disabled and ignored streams are
  never stale, and the stream's entries keep their own health (their tooltips
  just mention the stale stream). Each change is logged once.
- **Rejected snapshots are recorded.** When STD refuses a sidecar's snapshot
  (invalid payload, a changed key type, too large), the stream row shows
  "Rejected 3 min ago: 400: items.4.ip: ..." in Settings → Streams, and the API
  and MCP report `last_rejected_at`, `last_rejection` and `rejecting`. Apply
  errors are now labelled "Apply error".
- **Per-stream "Staleness and missing entries" settings** (Settings → Streams,
  `PATCH /api/v1/streams/{id}`, MCP `update_stream`): the expected snapshot
  interval, and an optional **soft delete of entries missing for N days** (off by
  default). The daily cleanup job soft-deletes them, and an item that comes back
  restores its entry. Entries you edited are never removed: linked, renamed,
  locked, grouped, described, with an icon, URLs, a sort priority, a widget, Home
  Assistant, or any check other than an untouched default check.
- **"Missing since".** An entry that dropped out of its stream's snapshot shows
  an amber **missing** badge with how long ago (Dashboard), "since" in the
  Tiled/Compact icon tooltip and drawer, the expanded detail and the edit page.
  It is a warning only: the entry's checks still decide its health. The API
  reports `inventory.missing_since`; the MQTT entry state adds `missing` and
  `missing_since`.
- **Checks follow a changed IP.** When a stream reports a new IP for an entry,
  every check that pointed at the old IP (ping, TCP, DNS server, or an HTTP URL
  with the IP as host) moves to the new one and runs at once; the change is
  logged. Checks that use a hostname are left alone.
- **MCP `server_info` re-checks STD's version on every call** (with a 3-second
  timeout; it falls back to the startup values, labelled "as of startup"). It
  says to restart the MCP server when STD changed since it started, and to update
  the script (`uv run .../v<version>/mcp/std_mcp.py` or `git pull`) and restart
  the MCP client when the script is older than STD. `list_streams`, `get_stream`
  and `health_summary` now describe every field they return.
- **API revision 3.** Sidecars may send `snapshot_interval_seconds` (60-86400)
  with a snapshot so STD knows how often to expect one; older STDs reject the
  field, so a sidecar should send it only to revision 3 or later. New stream
  fields (`expected_interval_seconds`, `producer_interval_seconds`,
  `effective_interval_seconds`, `interval_source`, `stale`, `stale_message`,
  `stale_after_seconds`, `snapshot_age_seconds`, `missing_expiry_days`,
  rejection fields), `stale` on the stream list, and `streams` /
  `stale_streams` / `counts.streams_stale` in the health summary. A database
  migration adds five stream columns and `inventory_missing_since` on entries.

## [0.10.0] — 2026-11-19

### Added

- **Linked entries are yours: stream cleanup unlinks them, never deletes them.**
  A manual entry you linked to a stream (Convert, accepting an offer, **Link to
  stream item…** or the API) goes back to being a manual entry, with the host it
  had before, when you disable a stream with soft delete or purge, or delete a
  stream with any option. The Disable…/Delete… dialog lists them and says "N
  linked entries go back to manual entries (with their host); they are never
  deleted." Entries the stream created itself behave as before, and Disable with
  keep still leaves everything attached.
- **Unlink from stream.** A stream entry's edit page has **Unlink from
  stream…**: **Allow re-offering** (a later snapshot may offer to link it again)
  or **Don't re-add** (the item is blocked). The entry keeps its history, checks
  and settings; a linked entry gets its old host back, unless another entry now
  has that host and name (it stays without a host and you are told). The stream
  info box says "Linked from a manual entry". In the API: `POST
  /api/v1/entries/{id}/unlink` (body `{"block": bool}`), entries report
  `inventory.linked`, stream disable/delete report `unlinked`; MCP tool
  `unlink_entry`. A database migration adds two columns to entries; entries
  linked before this release are detected by their id order (a manual entry
  linked earlier has a lower id than the stream's own entries), with their old
  host unknown.
- **Deleting a notification channel cleans its broker.** The Delete dialog
  offers **Remove this channel's data from the broker first** (ticked by
  default): the retained STD topics, the Home Assistant discovery configs and
  `<base>/status` are cleared, then the channel is deleted. If the channel is
  disabled or its broker can't be reached, nothing is deleted and the dialog
  offers **Delete anyway**. Disabling offers the same cleanup, unticked by
  default. In the API, `DELETE /api/v1/notifications/channels/<id>` takes
  `cleanup` (default true) and `PATCH` takes `cleanup` too; MCP:
  `delete_notification_channel`, `update_notification_channel`.
- **Changing a channel's base topic cleans up the old one.** Saving a channel
  with a new base topic (or, with Home Assistant on, a new discovery or device
  name prefix) shows **Remove the old topics from the broker**, ticked by
  default: everything under the old base and this install's old discovery
  configs are cleared before the switch. STD remembers the last 5 previous
  bases per channel (`GET /api/v1/notifications/channels/<id>/previous-bases`,
  MCP `list_notification_previous_bases`).
- **Scan for orphans.** A per-channel button lists the retained STD topics on
  the broker that STD no longer publishes (under the current and remembered
  base topics, one you type, and this install's discovery configs) and clears
  them on request (`POST .../orphans/scan` and `.../orphans/clear`, MCP
  `scan_notification_orphans` and `clear_notification_orphans`).
- **Purge MQTT/HA per stream.** A button on each stream row in Settings →
  Streams clears the MQTT topics and Home Assistant devices of every entry of
  the stream in one batch, then republishes what is still eligible
  (`POST /api/v1/streams/<id>/notifications/purge`, MCP
  `purge_stream_notifications`).
- **Stream status topic and Home Assistant stream devices.** STD publishes a
  retained `<base>/stream/<stream id>` per inventory stream (status, producer,
  last snapshot and apply times, active / missing / pending-offer counts, item
  count). With Home Assistant discovery on, a stream with a published entry gets
  a device with a status sensor and active / missing count sensors, and its
  entries' devices hang off it instead of the STD hub. Entry topics are
  unchanged.

- **Stream default checks.** Each stream can give its entries a ping check on
  their IP and, optionally, a TCP check on a port. New entries start with them;
  **Apply to existing entries** (Settings → Streams → Default checks, or
  `POST /api/v1/streams/<id>/default-checks/apply` and the MCP tool
  `apply_stream_default_checks`) adds the missing ones to every active entry and
  skips an entry that already has a ping or TCP check. Set them with
  `default_checks` on the stream (`PATCH /api/v1/streams/<id>`, `update_stream`).
- **Pending streams are flagged in the header.** While a stream waits for
  review, the **Settings** link gets an amber ring and a count and opens
  Settings → Streams. `GET /api/v1/streams` returns the same count as `pending`.
- **Streams tab shows what enabling would do.** A pending or disabled stream
  with a stored snapshot shows "would: created 5, link offers 2" in Last counts;
  a stream with no snapshot says "Waiting for the next snapshot".
- **IP, MAC and network in the expanded detail** of an entry, on the Dashboard
  view.
- **Home Assistant entries table has a Source column** (Docker, Manual or the
  stream's name) and the filter box matches it, so typing a stream's name and
  **Select all** picks its entries.

- **Inventory streams: sidecars can push device lists into STD.** A small
  separate service (a "sidecar", for example one that reads your DHCP static
  reservations) can post a full list of devices to
  `PUT /api/v1/streams/<stream_id>/snapshot` with an API key of the new
  **`ingest`** scope. That key opens only the two stream routes (snapshot and
  status) and is bound to the streams it creates. **A new stream waits for your
  approval**: STD stores what it sent, and nothing appears on the dashboard
  until you enable the stream. Enabling creates one entry per device (no host,
  source `stream`, with its IP, MAC and network); later snapshots update them,
  and a device that drops out of the list is flagged missing, never deleted.
  Renaming an entry in STD keeps your name; group, icon, description, checks and
  Home Assistant settings are never overwritten. A device whose name matches one
  of your manual entries is not created: STD offers to link them, and you
  accept or decline. Deleting a stream entry can block its key so it does not
  come back, and disabling or deleting a stream asks what to do with its
  entries (keep, soft delete or purge). Manage streams, blocks and link offers
  with the management API (`/api/v1/streams`) or the MCP tools. MQTT entry
  payloads gain `ip`, `mac`, `network` and `stream`, and the Home Assistant
  device model is the stream's name. Manage it all from the new Settings →
  Streams tab (next entry). See the README.
- **Settings → Streams tab.** Manage inventory streams without the API. The
  API key form gains an **Ingest (sidecars)** scope. A new stream shows as
  "New stream waiting: enable it to import N items", with **Preview** (every
  item and what enabling would do, nothing written), **Enable** and **Ignore**.
  **Disable…** and **Delete…** show counts first, then offer keep, soft delete
  or purge for the entries (customised ones are listed by name, and disable
  with purge can clear the block list too). You can edit a stream's display
  name and network include / exclude lists, unblock keys on the **Blocked**
  list, and accept or decline **Link offers**. A read-only **Docker (register)**
  row shows the notifier's entry count and last register.
- **Stream entries in the views and on the edit page.** A stream entry shows a
  pill with the stream's name where Docker entries show their Docker status
  (Dashboard, Tiled and Compact), replacing the grey "Manual" pill, and an item
  that dropped out of the latest snapshot is dimmed with a "missing" marker.
  The **Source** filter lists each stream. On the edit page the MAC, IP, network,
  attributes and stream are read-only and the name stays editable; deleting asks
  **Allow re-adding** or **Don't re-add** (also in the delete popover on the
  views). A manual entry with an open link offer shows **Convert** /
  **Keep separate**, and one without offers **Link to stream item…**.
- **Home Assistant "Since" sensor.** Every entry published to Home Assistant
  gets a **Since** timestamp sensor showing when it last changed state, so the
  device page reads "Up, since 3 days ago". It is unknown until STD has a
  value. It appears on the next sync; nothing to configure.
- **Nightly database snapshot.** The daily backup now also writes
  `<date>-std_backup.sqlite3` (a consistent copy of the database) next to the
  YAML file in `backup_path`, and `backup_days_to_keep` prunes both. A failed
  snapshot is logged and does not stop the YAML backup. See the README for
  restoring from it.
- **API revision.** The `/api/v1` contract now has a revision number (2),
  separate from the STD version. Every `/api/...` response, errors included,
  carries `X-STD-API-Revision` and `X-STD-Version` headers. New public
  `GET /api/v1/meta` returns the STD version, API revision and supported
  features, so producers can log them at startup. `whoami`, the OpenAPI
  document and the MCP `server_info` tool report the revision too. STD logs
  each distinct `User-Agent` seen on `/api/v1/register` once per restart.
- **Notifications: MQTT channels.** New Settings → Notifications tab (admins):
  add an MQTT broker (host, port, TLS, username, password, client id, base
  topic, QoS, keepalive), enable or disable it, and see its live connection
  status. **Send test message** publishes a non-retained message to
  `<base topic>/test` using the form's values, even before you save. STD
  announces itself on `<base topic>/status` (`online`, retained, with an
  `offline` last will, also sent on a clean shutdown) and reconnects on its
  own; changing a channel reconnects it without a restart. The password is
  write-only: never shown, returned, logged or audited. Check and state
  publishing and Home Assistant discovery build on it (below).
- **Notifications: check and entry state on MQTT.** With an MQTT channel
  enabled, STD publishes retained state under the base topic:
  `<base>/entry/<entry id>/state` (up, degraded, down, unknown or none, with
  name, host, group, source, since and check counts),
  `<base>/entry/<entry id>/check/<check id>` (result, latency, message,
  last change) and `<base>/summary` (counts over active entries). Only
  changes are sent, and everything is republished on every (re)connect and
  every 10 minutes. Entries and checks that are deleted, soft-deleted or
  disabled have their topics cleared. Topics use ids, so renaming an entry
  never moves them. Try `mosquitto_sub -t 'std/#' -v`.
- **Notification channels in the management API and MCP.** `GET`/`POST
  /api/v1/notifications/channels`, `GET`/`PATCH`/`DELETE
  /api/v1/notifications/channels/{id}` and `POST .../{id}/test`, plus the
  MCP tools `list_notification_channels`, `get_notification_channel` and
  `test_notification_channel`.
- **Notifications: Home Assistant discovery.** Tick **Add to Home Assistant**
  on an MQTT channel (with an optional discovery prefix, default
  `homeassistant`, and device name prefix, default `STD`) and Home Assistant
  creates one device per STD entry you opt in, named `STD <entry name>
  (<host>)` (just `STD <entry name>` when the entry has no host): a State
  sensor (up, degraded, down, unknown, none) and a problem sensor per check,
  all under an STD hub device with a connectivity sensor and
  up/degraded/down/unknown counts. **No entry is published until you tick
  Publish to Home Assistant**: on the entry's Add or edit page, or for many at
  once in the **Home Assistant entries** table under Settings → Notifications
  (filter, Select all / Select none, one Save). Within a published entry, every
  check appears unless you untick **Publish to Home Assistant** on that check
  (the management API and MCP carry `ha_publish` on entries and `ha_exclude` on
  checks). Entity ids start `std_`, so an auto-entities card can match
  `binary_sensor.std_*`; the group, host, source, check type and target are
  attributes. Unticked, deleted or disabled entries and checks are cleared from
  Home Assistant, and everything is republished when Home Assistant restarts.
- **Notifications: purge MQTT and Home Assistant.** A clean-slate tool for when
  retained messages or Home Assistant devices have piled up or gone stale.
  **Settings → Notifications → Purge MQTT and Home Assistant** (per channel,
  with a confirm dialog and a **Republish afterwards** box, on by default)
  removes every retained STD message under the channel's base topic and every
  STD discovery config (Home Assistant devices and entities) from that broker,
  then shows how many topics it cleared. Only this STD install's Home Assistant
  devices are touched, and `<base>/status` is left alone. With republish on, STD
  publishes everything again after about 2 seconds, so Home Assistant recreates
  the devices; with it off the broker stays empty until something changes or the
  channel reconnects. On an entry's edit page, **Purge and republish to
  MQTT/HA** does the same for just that entry on every channel, which gives it
  fresh entity ids in Home Assistant (for example after a rename). Both are in
  the management API (`POST /api/v1/notifications/channels/<id>/purge`,
  `POST /api/v1/entries/<id>/notifications/purge`) and the MCP server
  (`purge_notification_channel`, `purge_entry_notifications`).
- **More attributes on published state.** The entry state topic adds
  `std_entry_id`; the check topic adds `std_entry_id`, `entry_name`, `host`,
  `group`, `source` and `dashboard_url`.
- Database migrations add `ha_publish` to entries (off for every entry) and
  `ha_exclude` to checks (run automatically on start).
- New dependency `paho-mqtt` 2.x, and a database migration that adds the
  `notification_channel` table (runs automatically on start).
- **Version in the header.** The running version shows next to the page title;
  click it to open the What's New popup. Dev builds show `dev · 0.9.0` with the
  short commit linked to GitHub.
- **Update available link.** When GitHub has a newer release, a subtle
  `update available → vX.Y.Z` link appears next to the version. The check runs
  on the server when pages are loaded (at most every 6 hours, never delaying a
  page) and uses releases only.
- **Update check setting.** Settings → Info can turn the check off or change
  the interval (also `GET`/`PUT /api/v1/settings/update-check`). Settings →
  Info now also shows the build channel, linked commit, latest release seen,
  last checked time and last error.
- `GET /api/v1/whoami` and `GET /api/v1/config` now include `commit`,
  `channel`, `build_time` and an `update` status; the MCP `server_info` tool
  reports them too.

### Changed

- **Link offers match more.** A new stream item is now offered to a manual entry
  whose name, host, or the first part of its host equals the item's name (or its
  first DNS label, so `z-wave-house.crzynet.me` matches `z-wave-house`), host or
  not. Still exactly one match, else the item is created. Converting an entry
  (accept, or link by hand) clears its host, and the edit page says so; the
  "Link to stream item…" picker now also shows for entries that have a host.
- **Disable with purge keeps the stored snapshot**, so you can still preview and
  re-enable without waiting for the sidecar. The Disable… and Delete… dialog now
  states exactly what each choice removes.
- **Tiled and Compact show a small stream icon** (a router; amber when the item
  is missing from the latest snapshot) instead of the stream pill. Compact now
  also shows one source icon on every row: Docker status, stream, or manual
  (link). The full pill stays on the Dashboard view.
- **Add page:** the field is "Docker host (optional)", the example hostname is
  gone, and the help says to leave it blank for a device, VM or anything not
  running in Docker (the edit page says the same for manual entries).

### Fixed

- Auto-refresh now runs only on the Dashboard, Tiled and Compact views.
  Before, Settings and the Add/Edit pages also reloaded every refresh
  interval, which could discard unsaved form changes.

## [0.9.0] — 2026-11-16

### Added

- **One-command MCP install, and a version check.** The MCP server installs
  with one command via `uv run` (no virtualenv needed) and warns when it is
  older or newer than your STD; new `server_info` tool.
- `GET /api/v1/whoami` now includes the STD version.
- **Host on Tiled tiles when a name isn't unique.** Entries with the same name
  on different hosts (for example `technitium` on two DNS servers) used to
  look identical on Tiled. The host now appears in small muted text under the
  name for those entries only; other tiles are unchanged. A new
  `tile_show_host` setting (`TILE_SHOW_HOST`) chooses `duplicates` (default),
  `always` or `never`. Names compare ignoring case and surrounding spaces, and
  deleted entries and entries without a host don't count. It shows in
  Settings → Info and `GET /api/v1/config` like other startup settings.
- **DNS service check.** A new service-check type, **DNS**, asks a DNS server
  for a name and checks the reply, for example to watch a site's resolver.
  Set the server (an IP address, optionally with a port), the query name, the
  record type (A, AAAA, CNAME, TXT, PTR, MX, NS or SRV), the expected rcode
  (default NOERROR) and an optional expected answer. The check queries the
  server you give directly, never the host's own resolver. Without an expected
  answer it passes on the rcode alone; with one, any matching answer record
  passes, and a reply with no answers fails. Failures show what came back
  (`rcode NXDOMAIN`, `answer 10.0.0.5, expected 10.100.17.10`, `timeout`).
  Available on Add and Edit, the health detail panel, the management API
  (`check_type: "dns"` and the `dns_*` fields) and the MCP tools.
- **Certificate-expiry condition on HTTPS checks.** URL checks and HTTP
  service checks have a new optional **Min cert days** (1-365). When it is set,
  the check fails with `cert expires in 5 days (min 7)` once the server's
  certificate is that close to expiring, even if the page itself answers fine
  (an already-expired certificate reads `cert expired 3 days ago`, and a
  certificate that cannot be read reads `cert check failed: ...`). It works with
  Verify TLS turned off, so a self-signed certificate still reports its expiry.
  The field only appears while the URL starts with `https://`; on an `http://`
  URL a saved value is kept but ignored. The health detail panel shows
  "Cert expires <date> (N days)", in red when it is below your minimum. Also
  available in the management API (`cert_min_days`, with `cert_expires_at` on
  checks) and the MCP tools. The certificate is read over its own connection,
  so it does not go through an `HTTPS_PROXY`, and it needs TLS 1.2 or newer.
- **Rotate an API key.** Settings → API has a **Rotate** button on each active
  key. It keeps the key's name, scope and audit history but issues a new
  secret, shown once on the same copy-it-now page as when a key is created. The
  old key stops working immediately (there is no grace period), and "last used"
  starts over. A new **Rotated** column shows when each key was last rotated.
  Update anything that used the old key (for example the MCP client config).

### Changed

- Degraded and down services get a soft amber or red background on the
  Dashboard, Tiled and Compact views, so problems stand out at a glance.
  Up, unknown and not-monitored entries look the same as before.
- **An entry whose URL/service checks are all failing now shows Down even when its container is running (it used to show Degraded).** The Container check counts on its own: if it fails the entry is Down; otherwise the URL and service checks are judged as a group (all failing is Down, some failing is Degraded). The Status filter, the Failing count and `GET /api/v1/health/summary` follow.
- **HTTP check failures now include the reason from the response, e.g. `503: Scope 'Mgmt1' not found`, instead of just the status code.** For a status of 400 or above in Status mode, STD reads the first 4 KB of the reply: a JSON `last_error`, `error`, `message` or `detail`, else the first line of text (at most about 200 characters). An empty or binary body still shows just the code.
- **Tiled view: tiles show the icon on the left, the name across the full tile width (host underneath when shown), and all status, exposure and action icons in one row along the bottom.**
- **The health detail panel always says why a check is down.** A down check shows its reason line under the status; when the probe left no text it reads `status 503 (empty reply)` (or `no reply`) instead of nothing.
- **Upgrades no longer leave you on stale CSS/JS.** The stylesheet and scripts are now requested with a version (`?v=`) that changes when the file does, so a browser fetches the new copy after an upgrade.
- **Exposure icons show once per proxy layer instead of once per route; hover shows the route count and lists them.** A traefik service with several routers used to show the same logo several times. The small lock and pencil marks are gone from the badge; TLS and hostnames are in the hover text. This applies to the Dashboard and Tiled views.
- **Compact view shows the host only where the name isn't unique.** It now
  follows the new `tile_show_host` setting (default `duplicates`) instead of
  showing the host on every row whenever more than one host exists. Set
  `tile_show_host: always` to get the old look back (the host on every entry
  that has one).
- **Settings → Groups has one Save.** Edit any number of groups (name, icon,
  priority), add a new one in the bottom row (left blank, it is ignored) and
  press **Save changes** once. **Delete** now marks the row (struck through,
  with **Undo**) and the delete happens on Save; a group that still has
  entries has no Delete button. Nothing is saved if anything is wrong (empty
  or duplicate name, a priority that is not a number, a group that gained
  entries since the page loaded): the page comes back with what you typed and
  a message on each bad row. Swapping two names, or giving a new group a
  deleted group's name, works in one save. **Discard** reloads the table.
- **Warning before leaving Settings → Groups with unsaved changes.** The
  browser asks before you close the tab or follow a link, and the Save button
  is highlighted with an "Unsaved changes" hint. Typing a change and putting it
  back clears the warning. Switching Settings tabs does not lose your edits.
- The Groups table is always shown, so the first group can be added from an
  empty list.

### Fixed

- **Body-mode HTTP checks now show the reply's reason on a 4xx/5xx response (e.g. `503: <last_error>`) instead of just the status code.** An `Error: ...` body still gives that text as before.
- **Saving a group on Settings → Groups no longer clears its priority.** The
  per-row Save sent only the group's id, so the priority was reset to blank
  (and the name and icon were not saved). A priority of 0 also showed as blank.
- A revoked API key's name can be used again for a new key. Names only have to
  be unique among active keys; the audit-log key filter lists a reused name
  once per key, with the revoked one marked "(revoked)".

## [0.8.0] — 2026-11-15

> The management API and the MCP server are new in this release and have not
> been fully tested against real instances yet. Start with a read key, check
> the audit log after writes, and keep a recent backup.

### Added

- **Admin API keys (Settings → API).** Create named keys with a **read** or
  **write** scope for the upcoming management API. The full key is shown once
  with a Copy button (only a hash is stored); the list shows each key's
  prefix, scope, creation time, last use (time and IP) and status, and a
  Revoke button. Revoked keys stay listed, greyed out. These keys are
  separate from the notifier's `api_token`: the notifier token cannot use the
  management API, and a management key cannot register services. Your
  notifier setup is unchanged.
- **`GET /api/v1/whoami`**, the first management-API endpoint, returns the
  calling key's name, prefix and scope. The management API accepts only
  `Authorization: Bearer <key>` (a logged-in browser session alone gets 401)
  and answers errors as JSON (`{"error", "details"}`).
- **Write audit log.** Every write made through the management API is
  recorded (key name, method, path, result and the fields changed, with
  secret values masked). New setting `api_audit_retention_days` (default 90)
  controls how long rows are kept; a daily job removes older ones. The log is
  shown in Settings → API (see below).
- Database migration `d4a9e2c6b715` adds the `api_key` and `api_audit`
  tables.
- **Management API: entries, checks and health** (needs a write key for
  changes, a read key for reads), all under `/api/v1`:
  - `GET /entries` (filters `source`, `status`, `group`, `host`, `q`,
    `include_deleted`, `deleted_only`; paged with `limit`/`offset`),
    `GET /entries/<id>`, `POST /entries` (a manual entry, with its service
    checks and URL-check settings; a duplicate is a 409), `PATCH /entries/<id>`
    (group, URLs, icon, sort priority, lock, description, and name/host on
    manual entries), `DELETE /entries/<id>` (soft delete; `?permanent=true`
    only for an already deleted entry) and `POST /entries/<id>/restore`.
  - `GET` and `POST /entries/<id>/checks`, `PATCH` and `DELETE /checks/<id>`
    (only service checks can be deleted; disable URL and container checks
    instead) and `POST /entries/<id>/checks/run` (Check now).
  - `GET /entries/<id>/health?range=24h|7d` returns the same data as the
    detail panel, and `GET /health/summary` returns the Total / Passing /
    Failing / Unknown / Stale counts plus every failing service with its
    failing checks, messages and when each started failing.
  - A URL set through the API is an operator edit, like one made in the UI, so
    the notifier will not overwrite it. Fields reported by the notifier cannot
    be changed (400, naming the fields). Every problem in a request is reported
    per field.
- **Management API: groups, widgets, exposure settings and config**
  (write key for changes, read key for reads):
  - `GET`/`POST /groups`, `PATCH`/`DELETE /groups/<id>`. A duplicate name is a
    409. Like the Settings page, deleting a group that still has entries is
    refused (409); add `?force=true` to ungroup them and delete it anyway.
  - `GET /widgets/types` lists the widget plugins with their available fields;
    `GET /widgets` lists widgets with their entries and whether they are
    detached. `PUT /entries/<id>/widget` attaches or reconfigures a widget
    (type, URL, fields and an optional API key, checked against the plugin);
    `DELETE /entries/<id>/widget` detaches it (`?delete=true` removes it and
    its values) and `DELETE /widgets/<id>` deletes a detached widget. A
    widget's API key is never returned (only `widget_api_key_set`) and is
    masked in the audit log.
  - `GET`/`PUT /settings/exposure` read and replace the exposure direction
    mappings and per-host overrides (same rules as Settings → Exposure; saving
    recomputes the synthesized URLs).
  - `GET /config` shows the effective settings and the app version, read-only,
    with `api_token` and any key, token, password or secret masked.
- **Management API: OpenAPI spec, audit log view and docs.**
  - `GET /api/v1/openapi.json` (no key needed) is an OpenAPI 3.1 description
    of every management endpoint: scopes, query options, request bodies,
    response shapes and the error format. It is generated from the code, so it
    cannot drift. `/api/v1/register` is not part of it.
  - **Settings → API → Audit log** lists the most recent 200 management-API
    writes (time, key, method, path, object, status and the fields changed,
    with secrets shown as `***`), with a filter by key.
  - The README has new **Management API** and **Managing STD with Claude**
    sections: creating a key, the endpoint table, curl examples, errors,
    paging and the audit log.
  - An unknown `/api/v1/...` URL or a wrong method now answers in the API's
    JSON error format when the request carries a Bearer key or asks for JSON
    (the browser keeps the normal page).
- **MCP server for Claude Code** (`mcp/` in the repository, not in the
  Docker image). A small stdio server that lets Claude manage STD through the
  management API: see what is failing, list and read entries and health
  history, add a manual entry with checks (including `OK` / `Error: <msg>`
  body checks), edit or delete and restore entries, add, change, disable and
  run checks, create or update groups, attach widgets, and read or change the
  exposure settings. Point it at your STD with `STD_URL` and `STD_API_KEY`
  and register it with `claude mcp add`; the README has the commands. A
  **read** key exposes only the read tools. STD itself is unchanged.

### Fixed

- **Add page no longer files group-less entries under a group named "None".**
  Leaving the group blank now creates an ungrouped entry. Entries already in
  a "None" group stay there; move them on the Edit page or delete the group.

## [0.7.1] — 2026-11-15

### Added

- **"Show uptime" option in the filter bar.** Tick it to see a compact 24-hour
  uptime strip on every service, on Dashboard, Tiled and Compact, without
  opening each detail panel. The strip has 48 half-hour bars (red if any of
  the service's checks failed in that slot, green if all passed, grey with no
  data) and the 24h uptime percentage (Dashboard and Tiled; Compact shows
  just the thin strip). Hover or tap a bar for the time, counts and failure
  messages. It is off by default, remembered in a browser cookie, shows or
  hides instantly without reloading, and fetches nothing while off.

### Changed

- **The filter bar now shows clickable Total, Passing and Failing counts**
  in place of "Total Services". Passing counts healthy (up) services and
  Failing counts degraded or down ones; click a count to apply the matching
  Status filter, and the active one is highlighted. The counts follow the
  Source and Show URL-less filters but not the Status filter, so each number
  matches the list you get when you click it. Unknown and Not monitored
  services appear in Total only. The old `shown / total` text is gone.

## [0.7.0] — 2026-11-15

### Added

- **Docker container state is now an automatic health check.** Every
  notifier (Docker) entry has a **Container** check that passes while the
  notifier reports the container `running` and keeps reporting in, and fails
  with `Container exited` (or the reported state) or `No update from notifier
  for N min` otherwise. A Docker service with no URL or service checks now
  shows Up or Down instead of "Not monitored", and a running container with a
  failing URL check shows Degraded. It appears in the health detail panel with
  history and uptime like any other check, updates within a few seconds when
  the notifier reports a state change, and can be switched off or given its own
  interval in the Health checks section of the Edit page. Locked entries and
  manual entries do not have one. The Docker status pill and stale icon stay.
- **Health detail panel with a 24-hour history strip.** Each service has a
  detail view of its enabled checks: current state, target, last checked,
  response time, last message, uptime for 24 hours and 7 days, and the 20
  most recent failures. A Gatus-style strip of bars shows the history, green
  when every check in that slot passed, red when any failed and grey with no
  data; hover or tap a bar for the time range, pass/fail counts and failure
  messages. A 24h / 7d toggle switches between 48 half-hour bars and 168
  hourly bars, and **Check now** runs the service's checks immediately. It
  opens in the Tiled drawer, in a new expand row on the Dashboard (chevron
  at the start of each row) and on the Edit page under "Health history".
  Compact keeps its badge link to the Edit page.
- **One health badge per service on every view.** Each service shows a single
  rolled-up state from its enabled checks: Up (all passing), Degraded (some
  failing), Down (all failing), Unknown (enabled, not run yet) or Not
  monitored. The Dashboard has a new Health column, Tiled has a state icon in
  the tile, and Compact has a dot that opens the Edit page's health section.
  Hovering shows each failing check and its message.
- **Status and Source filters** next to "Group by" on all three views. Status:
  All, Failing (degraded or down), Healthy (up), Unknown (unknown or not
  monitored), Stale (notifier entries gone quiet). Source: All, Notifier,
  Manual. Both live in the URL, so they survive auto-refresh and bookmarks.
  "Total Services" shows `shown / total` when a filter hides entries.

- **Manual entries are now first-class.** Every entry has a source:
  `notifier` (kept current by the notifier) or `manual` (added on the Add
  page). Manual entries are for sites and services that are not Docker
  containers: they show a link icon (Tiled) or a "Manual" pill (Dashboard)
  instead of a Docker status, are never flagged stale, and hide the
  "Reported by notifier" block on the Edit page.
- **Description field** on manual entries (Add and Edit pages, shown in the
  Tiled drawer and as a tooltip).
- **Backups carry `source` and `description`.** Restoring an older backup
  without them works: an entry the notifier never reported becomes manual.

- **Service checks.** An entry can carry any number of its own checks, added
  and removed on the Edit or Add page: HTTP/HTTPS (a full URL; status code or
  response-body mode), TCP (`host:port`) and Ping (hostname or IP), each with
  a name, interval (30-86400 s), timeout (1-60 s) and enabled switch. A form
  error shows every problem at once and keeps everything you typed. The
  notifier never changes these checks.

- **Health-check results are now stored.** Every check run records its
  status, response time and message in a new history table, and each check
  keeps its latest state (ok or failing, status code, response time,
  consecutive failures). The badges, filters and detail panel read from it.
- **Backups carry each entry's health-check configuration** (enabled,
  timeout, verify-TLS and so on, no results). Restoring an older backup
  still works: its health-check settings are applied to the entry's two URL
  checks.

- **Faster, concurrent health checks.** A scheduler now checks every 5
  seconds for due checks and runs them in parallel (`health_check_workers`,
  default 8), so one slow service no longer holds up the rest. A new check
  runs at the next tick instead of after a full interval. Checks can be
  HTTP status, HTTP body (`OK` passes, `Error: <message>` fails with that
  message), TCP connect or ping.
- **Health history is kept for a week.** Every check sample is stored for 24
  hours (`health_raw_hours`), then successes are merged into one row per
  hour and run while failures are kept as they happened;
  everything older than `health_history_days` (7) is deleted. Hourly
  background jobs do the compaction and cleanup.
- **Check now** button in the health detail panel (backed by
  `POST /service/<id>/checks/run`) runs an entry's enabled checks at the next
  scheduler tick, a few seconds later.
- **Ping needs `NET_RAW`.** Ping checks use the container's raw-socket
  permission, which Docker grants by default. Without it a ping check fails
  with "ICMP not permitted".

### Changed

- **The INT / EXT links no longer carry a health colour.** Dashboard pills and
  Tiled icons are plain links (tooltip shows the URL and its last result);
  health is the new badge. The Tiled drawer shows each URL's last result from
  the stored check data.

- **Health checks are configured in one "Health checks" section** on the Edit
  and Add pages, replacing the two toggles and "Advanced health check". The
  Internal URL and External URL checks each have their own enabled switch,
  mode (status code or response body), interval, timeout and Verify TLS; the
  checked URL is shown read-only. Changing a check (or its URL) makes it run
  again within a few seconds.
- **Add and Edit now show their messages.** Validation errors and warnings
  appear at the top of the page (red or amber) and your input is kept;
  previously they only surfaced later on Settings. Stale "logged in" or
  "updated" notices no longer pile up there.
- **Add page creates manual entries only.** It asks for a Name (formerly
  "Application (Container Name)") and an optional Host, so a host is no
  longer required. Duplicates are matched on host and name, with a blank
  host counting as its own value.
- **A notifier report adopts a matching manual entry.** If you pre-stage an
  entry on the Add page and a container with the same host and name later
  registers, the entry becomes a notifier entry and is updated as usual
  (nothing is duplicated). A locked entry is still left alone.
- **"Locked (Static Entry)" is now "Lock (ignore notifier updates)".** The
  lock only stops notifier updates; it no longer means "not a Docker
  container" and no longer hides the Docker status on its own.
- Entries with no host group under "Unknown host" in the Host view.
- Health-check settings (the two URL toggles, timeout, verify-TLS) now live
  in their own tables instead of on the service entry. The Add and Edit
  pages work the same; the notifier's `internal_health_check_enabled` /
  `external_health_check_enabled` keys set the matching check, and an
  absent key still means no change. A second migration creates the checks
  for every existing entry, copying the enabled flags, timeout, verify-TLS
  and last status, so nothing needs to be re-entered.
- Database migration adds `source` and `description` and lets `host` be empty.
  Existing entries the notifier never reported (no update time) become
  manual; all others stay notifier entries.

## [0.6.9] — 2026-11-15

### Added

- **Per-service health-check options.** The edit and add pages have a new
  "Advanced health check" section: a timeout (1-60 s, blank = default) and a
  "Verify TLS certificate" checkbox. Untick it for self-signed internal URLs
  that used to report `Error: SSLError`. Both are included in backups and
  restores.
- **`health_check_timeout` setting** (default `5`) sets the global health-check
  timeout, previously hard-coded.
- **Stale indicator on every view.** A service whose last notifier update is
  older than the threshold now shows an amber warning icon (tooltip "Stale —
  updated <time>") on the Dashboard table and Compact view as well as Tiled.
- **`stale_after_minutes` setting** (default `5`) sets that threshold.
  Static entries are never stale.
- **Settings → Deleted tab.** Deleted services now land here instead of
  vanishing. Each row shows the name, host, when it was deleted, and the days
  left before it is purged, with **Restore** and **Delete permanently**
  buttons.
- **`deleted_retention_days` setting** (default `30`; `0` removes deleted
  entries at the next nightly run). A daily 00:25 job permanently removes
  entries deleted longer ago than this.

### Changed

- **Production server is now gunicorn** (one worker, four threads) instead of
  the Flask development server. Port 8815 and all configuration are unchanged,
  so no action is needed. Startup log lines now come from gunicorn alongside the
  app's own, and each request is access-logged to the container output. The
  single worker is deliberate: the scheduler, health-check thread and register
  lock are in-process. Setting `FLASK_DEBUG=1` still runs the development
  server with auto-reload.
- **Dependencies are pinned.** Image builds install an exact, resolved set of
  versions, so a rebuild no longer picks up whatever is newest upstream.
- **One staleness rule.** The Tiled view no longer has a separate 2-hour
  clause; the single `stale_after_minutes` threshold decides. The Tiled
  tooltip now reads "stale — updated <time>".
- **Widget settings survive permanent deletion and can be re-attached.**
  Permanently deleting a service (or the nightly purge) now keeps its widget and
  stored values as a detached widget instead of erasing them. Settings →
  Deleted has a new "Detached widgets" list with **Attach** (to an active
  service with no widget) and **Delete**. Detached widgets, and widgets whose
  services are all deleted, are no longer refreshed.
- **Deleting a service is now recoverable.** The trash icon, the tile drawer,
  and the edit page's Delete button hide the entry (and stop its health checks
  and widget refresh) instead of erasing it; the confirm popover and flash
  message say it can be restored from Settings → Deleted for N days. Its
  widget stays attached.
- **A register for a deleted service restores it.** If a container that was
  deleted here registers again before it is purged, STD brings back the same
  entry (group, sort priority, and edits intact) rather than creating a blank
  one.
- YAML backups now include each entry's deletion time, and restore brings it
  back; backups from earlier versions restore as before. `/dbdump` lists
  deleted entries too, struck through with a Deleted At column.

### Fixed

- **`widget_value_retention_days` and `register_field_ownership` now work.**
  Both were documented but silently ignored (from `settings.yml` and from the
  environment); the defaults always applied. They are now read from either.
- **An unset `API_TOKEN` no longer accepts a bogus header.** Previously
  `Authorization: Bearer None` was accepted when no token was configured.
  Now `/api/v1/register` returns `503 {"error": "API token not configured"}`
  until a token is set, and Settings → Service Info shows a notice.
  **Installs that never set `API_TOKEN` will now get 503 on register;** set
  `API_TOKEN` (or `api_token` in `settings.yml`) to restore it.

### Security

- **CSRF protection on every UI POST.** All forms (login, logout, settings,
  groups, users, add/edit, backup/restore) and the in-page delete requests now
  carry a CSRF token. A stale or tokenless form submit shows "Your session
  expired or the form was stale; please retry." and returns you to the page;
  a tokenless JSON request gets `400 {"error": "CSRF token missing or
  invalid"}`. `/api/v1/register` is unaffected (bearer-token API). Tokens last
  as long as the session. Requires `Flask-WTF` (installed with the image).
- API token comparison is now constant-time.
- The API token is masked (`***`) in startup and debug logs.
- STD now warns (log and a dismissible notice on Settings) when
  `FLASK_SECRET_KEY` is unset or the `admin` user still has the default
  `changeme123` password. Nothing is forced; change them when you can.
- **Paths and redirects are confined.** Icon files built from an icon name
  (register, Add, Edit), server-side backup restore filenames and widget names
  can no longer reach outside their own folders; an unsafe icon name is skipped
  (a register still succeeds) or flagged on Add/Edit. After you save or delete
  an entry, STD only redirects to pages within STD, never to another site.
  This closes 13 CodeQL alerts (`py/path-injection`, `py/url-redirection`).

## [0.6.8] — 2026-11-15

### Removed

- **Docker Hub images are no longer published.** Anyone still pulling
  `crzykidd/service-tracker-dashboard` from Docker Hub stays on v0.6.7 and
  should switch to `ghcr.io/crzykidd/service-tracker-dashboard` — see
  [Moving from Docker Hub](https://github.com/crzykidd/service-tracker-dashboard#moving-from-docker-hub). The "moved to
  GHCR" banner (which only appeared in the v0.6.7 Docker Hub image) is
  removed from the app.

### Changed

- **`:dev` and `:latest` images now report the real version.** Settings →
  Service Info previously showed `dev` or `latest` for these images; it now
  shows the actual version number, and the What's New popup works on them.

### Fixed

- **Add Entry no longer errors on a non-numeric sort priority.** Entering
  something other than a number in Sort Priority on the Add page now shows
  the "Sort priority must be a number." message and re-displays the form,
  instead of returning a server error. The group dropdown is also kept
  populated when the form re-displays after a validation error.

## [0.6.7] — 2026-11-15

STD is moving from Docker Hub to GitHub Container Registry (GHCR). If you
pull `crzykidd/service-tracker-dashboard` from Docker Hub, change your
image to `ghcr.io/crzykidd/service-tracker-dashboard` — this is the last
release published to Docker Hub.

### Added

- **Images on GitHub Container Registry.** STD is now published to
  `ghcr.io/crzykidd/service-tracker-dashboard` with the same tags as
  before (`:latest`, `:dev`, `:<version>`, `:<major>`). Switching is a
  one-line image change in your compose file; your config, database,
  and settings carry over unchanged. See "Moving from Docker Hub" in
  the README.
- **"Moved to GHCR" banner in the Docker Hub image.** Installs running
  the Docker Hub image show a banner at the top of every page (and a
  note on Settings → Service Info) with a link to the update
  instructions. Dismissing it hides it until the next browser session.
  The GHCR image does not show the banner.

### Deprecated

- **Docker Hub images.** This is the final release published to Docker
  Hub. Future releases are published to GHCR only; Docker Hub `:latest`
  will stay on this version.

## [0.6.6] — 2026-05-17

Two changes to the Tiled tile face: the v0.6.5 widget modal is
replaced by a mode of the existing drawer, and exposure layer text pills
are replaced with recognizable brand logos.

### Added

- **Brand logo exposure icons.** The text-pill badges that showed a
  truncated layer name are replaced with 18 px brand SVG logos. Each
  icon carries a padlock overlay when TLS is active and a pencil overlay
  when an explicit hostname was configured. Logos for Traefik, Cloudflare,
  DockFlare, nginx, and Caddy are sourced from official brand channels and
  committed to `static/icons/exposure/`; unknown layers fall back to a
  `ti-route` icon.

### Changed

- **Widget drawer replaces widget modal.** The chart icon on a tile now
  opens the tile's existing drawer in widget-only mode — showing just the
  metric cards — rather than a separate centered overlay. Clicking the
  icon again closes the drawer; clicking the chevron while in widget mode
  expands to the full drawer in-place (and vice versa). Esc and
  click-outside still dismiss. The "Refresh paused" detection requires no
  change: the widget view is just an open drawer.

### Removed

- **Widget data modal** (centered overlay with backdrop, introduced in
  v0.6.5). Superseded by widget drawer mode.
- **Old exposure text-pill CSS** (`.exposure-badge` classes). Replaced by
  `.exposure-icons` / `.exposure-icon-*` classes.

## [0.6.5] — 2026-05-17

UI overhaul, part 2 (release 3 of 3): edit page polish, a universal delete
pattern, click-to-view widget data, and an auto-refresh that knows not to wipe
out your work while you're looking at it.

### Added

- **Trash icon on Tiled tiles and Dashboard rows.** One click deletes a dynamic
  entry, with a small inline confirm popover anchored to the icon. Static
  (Locked) entries show a lock icon in the same slot instead — they can only be
  deleted from the edit page, which is the deliberate path for protected entries.
- **Widget data modal.** Clicking the chart icon on a tile now opens a modal
  showing just that service's widget data. Faster than expanding the full drawer,
  especially on mobile. The chevron drawer still works as before.
- **Auto-refresh pauses while you're interacting.** Open a drawer, the widget
  modal, or the changelog popup, and the page won't refresh out from under you.
  The refresh timer shows "Refresh paused" while interaction is active and
  resumes (counter reset to 0) when you close everything.

### Changed

- **Edit page visual polish.** Tighter input padding and border-radius, section
  headings (Identity / URLs & Health / Grouping & Display / Widget), tighter
  spacing within sections and looser between, muted helper text. URL fields now
  group their health-check checkbox inline below the input instead of floating
  it to the side. The "Select Existing / Add New" group selector is now a
  tab-style toggle instead of bullet radios.
- **Universal delete UI.** All delete affordances — drawer Delete button, edit
  page Delete button, and the new trash icons — use the same small inline
  popover with a Confirm button. The typed-name confirmation form is gone;
  static entries are protected by being deletable only from the edit page.
- **Lock icon replaces 🔒 emoji on Dashboard rows.** Consistent visual language
  with the new Tiled lock indicator. Same meaning: "this entry is locked from
  notifier updates; delete from the edit page."
- **Drawer Delete button hidden for static entries.** The tile-level lock icon
  signals the constraint; the drawer no longer duplicates it.

### Removed

- **Danger Zone section on the edit page.** Replaced by a single Delete button
  at the bottom of the form, using the new popover.

## [0.6.4] — 2026-05-17

UI overhaul, part 2 (release 2 of 3): mobile usability and tile restructure.
The filter bar now collapses cleanly on phones, tile status icons split into two
rows so container names stop truncating, and the drawer scrolls its tile into
view when you tap to expand it.

### Added

- **Mobile filter bar.** Below 640 px the filter bar collapses to just the
  free-text filter plus a "View options" toggle button. Tapping the toggle
  reveals group-by, sort, Show URL-less, auto-refresh, and total count in a
  vertical panel. Tapping outside or pressing Esc collapses it again. Above
  640 px the filter bar is unchanged.
- **Drawer scrolls into view on mobile.** When you tap the chevron on a Tiled
  tile near the bottom of the viewport, the page smoothly scrolls the tile to
  the top so the drawer has room to expand below it. Only triggers below 768 px
  wide — desktop drawers are unaffected.
- **Stack row in the tile drawer.** When a service has a stack name, the Tiled
  drawer now shows it immediately after Host. Saves a trip to the edit page
  when grouped by host.

### Changed

- **Tile status icons now render in two rows.** The single-row icon layout was
  truncating container names aggressively when all affordances were present.
  Status icons (internal URL, external URL, Docker, widget) now occupy the top
  row; action icons (Dozzle, edit pencil, expand chevron) occupy the bottom
  row. Container names get back the horizontal space they need. Tiles are
  roughly 20 % taller as a result.
- **Larger touch targets on mobile.** Tile status icons and drawer action
  buttons have bigger hit boxes below 640 px — same visual size, more
  forgiving for fingers. Desktop appearance unchanged.
- **`icon-sep` separator removed.** The two-row icon layout replaces it
  semantically.

## [0.6.3] — 2026-05-17

Foundations for "UI overhaul, part 2": orphan handler sweep,
inline-style cleanup completing the v0.6.1 CSS extraction, and a
"what's new" popup that fires automatically after each version upgrade.

### Added

- **"What's new" popup.** After upgrading STD, operators see a modal on
  their next page load showing the changelog entries for every version
  since the one they last acknowledged. Dismissal writes the current
  version to `localStorage` and closes. New API route
  `GET /api/v1/changelog?since=<version>` parses `CHANGELOG.md`
  server-side and returns the relevant sections as rendered HTML.
- **`markdown` package** added to `requirements.txt` to support
  server-side rendering of changelog sections.

### Changed

- **Inline `<style>` blocks removed** from `templates/edit_entry.html`
  and `templates/settings.html`. The v0.6.1 CSS extraction is now
  complete — `.form-input`, `.form-checkbox`, `.btn-primary`, and
  `.btn-secondary` are defined only in `static/css/dashboard.css`.
  `.btn-primary` background normalized from `#4299e1` to
  `var(--color-accent)` (`#3b82f6`) — minor visible difference on
  the edit and add pages.
- **`version_info` is now injected globally** into every template that
  extends `base.html` via the app context processor (previously only
  passed explicitly to the settings page). Required by the changelog
  popup to read the current version.

### Fixed

- **`toggleGroupMode` unreachable from inline `onclick=`** on the
  edit-entry and add-entry pages. The function was scoped inside a
  `DOMContentLoaded` closure, making it invisible to inline handler
  attributes. Hoisted to module scope in both templates.

## [0.6.2] — 2026-05-16

### Fixed

- **Restore-from-upload broken on /settings.** The `toggleRestoreSource`
  function was dropped during the v0.6.1 inline-JS extraction, leaving
  `#file-upload-section` permanently hidden with no way to select a local
  YAML backup file. The function has been restored to the settings template.
- **No filename feedback after selecting an upload file.** The
  `#restore_file_input` change event now updates `#file-name-display` with
  the selected filename so operators can confirm their file choice before
  submitting.

## [0.6.1] — 2026-05-16

UI overhaul, part 1: Tiled dashboard redesign, per-tile expand drawer,
icon vocabulary shared across Tiled and Dashboard, inline CSS/JS
extracted to shared static files, Compact tab-highlight fix.

### Added

- **Per-tile expand drawer on Tiled.** Clicking the chevron on any tile
  drops a panel anchored to the tile (overlay, not inline reflow). Drawer
  shows host, internal/external URLs with health status, Docker status and
  image tag, networks, ports, exposure observations, and widget data.
  Action row at the bottom has Edit, Delete, and (when Dozzle is
  configured) a Tools popover with a Dozzle link.
- **Pencil-icon edit affordance** on Tiled tiles (status icon row) and
  Dashboard table Actions column. Both navigate to `/edit/<id>?ref=<path>`.
- **Tabler Icons** (v3.34.0) loaded via cdnjs CDN. Outline set only.
  Used for all new icons in this release.
- **Tools popover in the Tiled drawer.** Seeded with the Dozzle link.
  Renders only when at least one tool is available.

### Changed

- **Tiled dashboard tile redesign.** Host line removed from the tile
  face (now in the drawer). Status area replaced with icon row:
  `ti-home` (internal URL), `ti-world` (external URL),
  `ti-brand-docker` (Docker), plus widget indicator, Dozzle, edit
  pencil, and expand chevron. Colors: green 2xx, amber SSL/stale, red
  non-2xx or bad, gray not-configured.
- **Exposure badges** (Tiled, Dashboard, edit page) now use Tabler
  icons `ti-lock` / `ti-key` instead of 🔒 / 🔑 emoji.
- **Dashboard table status column** now uses icon-and-label pills
  sharing the Tiled icon vocabulary (`ti-home`, `ti-world`,
  `ti-brand-docker`).
- **Dashboard Tools column** uses `ti-terminal-2` instead of the
  Dozzle SVG image.
- **Per-template inline CSS and JS extracted** to
  `static/css/dashboard.css` and `static/js/dashboard.js`. All three
  dashboard views now share these files. Hybrid Tailwind-utilities-
  plus-custom-CSS approach formalized; no frontend build step.

### Removed

- **"Show Widgets" filter-bar toggle on Tiled.** Widget data is now
  accessible via the per-tile expand drawer.

### Fixed

- **Compact tab failed to highlight** in the nav. The missing
  `{% set active_tab = 'compact' %}` declaration has been added.

## [0.6.0] — 2026-05-14

### Added
- **View controls** above the service grid on `/`, `/tiled_dash`, and
  `/compact_dash`, sharing one UI partial:
  - `Group by` axis selector with `group` (default), `stack`, and
    `host`. Designed as an N-axis selector so future axes drop in
    without rework. `axis=stack` collects rows with no `stack_name`
    into an "Unstacked" bucket rendered last; `axis=host` collects
    rows with no host into "Unknown host"; `axis=group` keeps
    "Ungrouped" last as before.
  - `Show URL-less` checkbox (default on). Unchecking hides services
    where both `internalurl` and `externalurl` are null/empty.
- View-control state is URL-driven
  (`?group_by=stack&show_urlless=false&sort_in_group=alphabetical`),
  so dashboards stay bookmarkable and shareable. No per-user
  preference persistence in this release.
- **Network & ports capture (v0.6.0).** Three new optional fields on
  `/api/v1/register`, populated by notifier v0.4.0+:
  - `networks` — list of `{"name", "aliases"}` objects, one per
    Docker network the container is attached to. Names only; IPs
    intentionally not captured.
  - `exposed_ports` — list of `"<port>/<proto>"` strings declared
    via `EXPOSE` in the image or `expose:` in compose.
  - `published_ports` — list of `{"container_port", "protocol",
    "host_ip", "host_port"}` objects describing host-to-container
    port mappings from compose `ports:`.
- Three new nullable JSON columns on `service_entry`
  (`networks`, `exposed_ports`, `published_ports`) storing the above.
  Rows that haven't received a v0.4.0+ register stay NULL — that's
  the expected state, not a bug.
- New "Reported by notifier" section at the bottom of `/edit/<id>`,
  read-only, showing networks, exposed ports, and published ports
  with "Not reported" placeholders when data is absent.
- **Exposure interpreter mechanism.** STD now consumes structured
  exposure observations emitted by notifier YAML interpreters
  (Traefik, Dockflare, etc.), synthesizes `internalurl` /
  `externalurl` from them, and surfaces them as tile badges. Six
  interlocking pieces:
  - New optional `exposure_observations` field on
    `/api/v1/register`, validated by a strict pydantic
    `ExposureObservation` model (`extra="forbid"`). Notifier v0.4.0+
    populates this. `null` in the payload means "no update"; `[]`
    means "clear all observations for this service."
  - New `service_exposure` table (one row per (service, interpreter
    layer) observation), with FK + index on `service_entry_id`.
    Replaced wholesale per service on each register that carries
    `exposure_observations`.
  - New synthesizer module (`synthesizer.py`) that combines
    exposure observations + per-interpreter direction settings to
    produce `internalurl` and `externalurl`. Tiebreaker: TLS over
    non-TLS, no path prefix over path prefix, layer name
    alphabetical (stable). Runs on every register and on settings
    save.
  - URL provenance: two new columns on `service_entry`
    (`internalurl_source`, `externalurl_source`) tracking which
    actor last wrote each URL. Ordering: `ui_edit` >
    `explicit_label` > `synthesized` > NULL. Operator UI edits and
    explicit `dockernotifier.std.internalurl` labels are never
    overwritten by the synthesizer.
  - New DB-stored settings table (`setting`) and module
    (`settings_store.py`). First operator-editable runtime settings
    in STD; backs the per-interpreter direction mapping
    (`traefik = internal`, `dockflare = external`, ...) with
    per-host overrides.
  - New "Exposure" tab on `/settings` showing discovered interpreter
    layers with a direction dropdown each (internal / external /
    neither, defaulting to neither) and a per-host overrides
    section. Saving recomputes synthesized URLs for every service.
- **Exposure badges** on the tiled and table dashboards — small
  pills per `service_exposure` row showing layer name, TLS status
  (🔒), and auth-required indicator (🔑). Capped at 3 visible per
  service with a `+N` overflow indicator.
- **Headless rendering** — services with no exposure observations
  and no URLs render without click affordance on the tiled and
  compact dashboards. Status display falls back to `docker_status`.
- URL source indicator next to the URL inputs on `/edit/<id>` —
  shows whether each URL was edited in the UI, set via explicit
  label, or synthesized. Clearing the field resets provenance and
  re-allows synthesis on the next register.

### Changed
- Grouping/sorting logic for the three dashboard views consolidated
  into `view_helpers.group_and_sort_services` — a single helper that
  takes `(services, axis, show_urlless, sort_in_group)` and returns
  the bucketed list the templates render. (Resolves D2 from PRD §6.2,
  which was deferred from v0.5.0 despite the v0.5.0 changelog
  claiming otherwise.)
- Group buckets are now keyed canonically by `group_id` across all
  three views (was a mix of `group_id` and `group_name`). Two
  distinct `Group` rows that happen to share a display name yield
  two distinct buckets.
- The dashboard view-controls dropdown values changed from
  `group_name`/`stack_name` to `group`/`stack`. Bookmarks built
  against the v0.5.0 query strings will fall back to the default
  `group` axis (logged at DEBUG).
- `RegisterPayload` validates nested `networks` and `published_ports`
  structures with dedicated pydantic models (extra="forbid" applies
  to each). Malformed payloads are rejected at the schema boundary.

### Removed
- **`/api/register` endpoint and the legacy-key compat shim.** Routes
  that used to translate `docker_host`, `group`, `internal.health`,
  `external.health`, `icon`, `sort.priority`, etc. into canonical
  keys are gone. The per-IP deprecation log tracker and the
  `Deprecation: true` / `Link: rel="successor-version"` response
  headers are also removed — they had nowhere to attach. Operators
  must run `docker-api-notifier` v0.3.0 or later; older notifiers
  will see 404 at `/api/register`.

### Fixed
- `compact_dash` tile click handler no longer opens a literal "None"
  URL when both `internalurl` and `externalurl` are empty. Tiles
  without a URL now render as non-clickable text (consistent with the
  headless rendering rule).

---

## [0.5.0] — 2026-05-12

### Added
- New `/api/v1/register` endpoint accepting canonical key names
  (`host`, `group`, `internal_health_check_enabled`, ...) validated by
  pydantic schemas.
- Composite index on `service_entry(host, container_name)` — the
  logical key for the register upsert path. Non-unique; concurrency
  safety comes from the application-level mutex (see below), not
  from a database constraint.
- New `notifier_reported_group_name` and `notifier_reported_sort_priority`
  columns on `service_entry`. The v0.5.0 register handler writes
  what the notifier most recently reported for these user-overridable
  fields, so a planned "export overridden labels" feature can diff
  the user's edited value against the notifier's. Not surfaced in
  the UI in v0.5.0.
- Rolling retention for `widget_value`, enforced by a scheduled
  daily prune job (00:15 server local time). Window is configurable
  via the new `widget_value_retention_days` setting (default 30).
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service.
- New `register_field_ownership` setting (`user_wins` default, or
  `notifier_wins`). Controls whether a notifier register call may
  overwrite a non-NULL UI-edited value for `group_name` or
  `sort_priority` on an existing row. New rows always take
  everything the payload carries. Regardless of mode, the
  `notifier_reported_*` capture columns record what the notifier
  said. Invalid values fall back to `user_wins` with a startup
  WARNING.
- `Deprecation: true` response header on `/api/register`, plus a
  `Link: </api/v1/register>; rel="successor-version"` pointer. A
  per-IP-per-hour rate-limited WARNING log fires when a legacy
  producer hits the shim. (No `Sunset` header in v0.5.0 — a wrong
  Sunset date is worse than none. v0.6.0 will add it once its
  release timeline is firm.)
- `/healthz` liveness endpoint returning `{"status": "ok"}` (HTTP 200)
  as long as the WSGI worker is up. Unauthenticated; intended for
  container orchestrators and external uptime checks.

### Changed
- `app.py` split into focused modules: `routes_dashboard.py`,
  `routes_api.py`, `routes_widgets.py`, `routes_auth.py`, `models.py`,
  `schemas.py`, `jobs.py`, `health.py`. `app.py` becomes a Flask app
  factory.
- Icon fetch consolidated; `image_utils.py` is the single path used by
  `/add`, `/edit`, and the register handler.
- `settings.example.yml` updated to match the keys the code actually
  reads (`url_healthcheck_interval`, not `url_refresh_interval`).
- `load_settings()` is called once at startup; route handlers read
  from the resolved app config.
- Repo layout cleaned up: dashboard screenshots moved from the repo
  root into `docs/screenshots/`; `test-widget.py` moved to
  `scripts/test_widget.py`. README image links updated.

### Deprecated
- `/api/register` endpoint and all legacy key variants
  (`docker_host`, `group_name`, `internal.health`, `external.health`,
  `internalurl`, `externalurl`). Will be removed in v0.6.0. Operators
  must upgrade `docker-api-notifier` to v0.3.0+ before v0.6.0.

### Removed
- Unused `session_token` field on `User`.
- Stray git tag `v.0.4.6` (extra dot) — replaced by `v0.4.6`.
- `docker-compose-alembic.yml` — a one-shot from June 2025 with a
  hardcoded migration message and a maintainer-specific host path.
  Run alembic via `docker compose exec <service> alembic ...`
  against the running app container instead. Workflow documented in
  the new "Database Migrations" section of `README.md`.
- `READMEOLD.md` — pre-v0.4.9 README, superseded by the rewritten
  `README.md`.

### Fixed
- Register endpoint contract documented and enforced via pydantic
  schemas; no more silent key remapping.
- Shell scripts pinned to LF line endings via `.gitattributes`.
  Prevents the container failing to start with
  `exec /entrypoint.sh: no such file or directory` when the repo is
  cloned on Windows with `core.autocrlf=true`.
- SQLite WAL mode is now actually enabled at runtime via a connect-time
  PRAGMA in `extensions.py`. Prior releases documented WAL mode but
  `journal_mode` was the SQLite default (`delete`), so the documented
  backup rules around the WAL sidecar didn't reflect actual on-disk
  state.
- `alembic/env.py` now imports the application module so SQLAlchemy
  model classes register with `db.metadata`. Previously
  `db.metadata.tables` was empty during alembic runs, which would have
  caused `alembic revision --autogenerate` to silently produce empty
  no-op migrations. A guard now raises if metadata is empty rather
  than letting the schema silently drift.
- Background scheduler and URL health-check thread now start only when
  `app.py` is run as the main process, not at module import time.
  Previously they spawned during `alembic upgrade head` in production
  (where `app.debug` is False) and briefly raced alembic for the SQLite
  write lock before being killed when the alembic process exited.
- Removed a duplicate `health_check_loop` thread start that had two
  daemon threads racing each other on every production startup.
- URL health-check loop wrapped in a per-iteration `try / except` so a
  transient `requests` failure, DNS hiccup, or unexpected exception no
  longer escapes the worker thread and silently kills health checks
  until the process restarts. The exception is logged with a full
  traceback and the loop continues.
- "Stale" tile styling on `/tiled_dash` now actually fires.
  `is_docker_status_stale` was defined at the wrong indentation level
  and silently attached to `User` instead of `ServiceEntry`, so the
  template's reference resolved to `Undefined` (always falsy) and stale
  tiles never received the stale colour class. Property is now
  correctly attached to `ServiceEntry`.

---

## [0.4.14] — 2025-07-12

Released. Detailed notes not retained.

## [0.4.13] — 2025-06-23
Released.

## [0.4.12] — 2025-06-22
Released.

## [0.4.11] — 2025-06-22
Released.

## [0.4.10] — 2025-06-21
Released.

## [0.4.9] — 2025-06-21

Breaking change: required a database backup + delete + restore on upgrade.

## [0.4.8] — 2025-06-21
Released.

## [0.4.7] — 2025-06-21
Released.

## [0.4.6] — 2025-06-07
Released.

## [0.4.5] — 2025-06-07
Released.

## [0.4.4] — 2025-06-06
Released.

## [0.4.3] — 2025-06-06
Released.

## [0.4.2] — 2025-06-05
Released.

## [0.4.1] — 2025-06-05
Released.

## [0.4.0] — 2025-06-05
Released.

## [0.3.x] series — 2025-05-31

v0.3.0 through v0.3.9 released. Detailed notes not retained.

## [0.2.x] series — 2025-05-27

v0.2.0 through v0.2.12 released. Detailed notes not retained.

## [0.1.x] series — 2025-05-26

Initial development releases v0.1.0 through v0.1.4.

[Unreleased]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.10.0...HEAD
[0.10.0]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.6.9...v0.7.0
[0.6.9]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.6.8...v0.6.9
[0.6.8]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.6.7...v0.6.8
[0.6.7]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.6.6...v0.6.7
[0.6.6]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.6
[0.6.5]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/0.6.5
[0.6.4]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.4
[0.6.3]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.3
[0.6.2]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.2
[0.6.1]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.1
[0.6.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.6.0
[0.5.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.5.0
[0.4.14]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.14
[0.4.13]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.13
[0.4.12]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.12
[0.4.11]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.11
[0.4.10]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.10
[0.4.9]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.9
[0.4.8]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.8
[0.4.7]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.7
[0.4.6]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.6
[0.4.5]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.5
[0.4.4]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.4
[0.4.3]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.3
[0.4.2]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.2
[0.4.1]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.1
[0.4.0]: https://github.com/crzykidd/service-tracker-dashboard/releases/tag/v0.4.0
