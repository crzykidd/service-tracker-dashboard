# Inventory streams

An inventory stream is a list of devices that a sidecar keeps current, for example
every static DHCP reservation. The sidecar posts the **whole** list every few minutes;
STD never pulls from your DHCP server. The first stream sidecar is
[std-source-technitium](https://github.com/crzykidd/std-source-technitium) (its own
repo). Anyone can write one for another source: the wire contract is
[PRD §18.5](PRD.md) and the OpenAPI document (`GET /api/v1/openapi.json`).

The overview is in the [README](../README.md#inventory-streams); this page is the full
guide.

## In the UI (Settings → Streams)

1. Settings → **API keys**: create a key with the scope **Ingest (sidecars)** and
   give it to the sidecar.
2. The sidecar's first snapshot creates the stream as **pending**. The section
   shows "New stream waiting: enable it to import N items" at the top, with
   **Preview**, **Enable** and **Ignore** right there, and nothing appears
   on the dashboard yet. **Preview** opens a dialog listing every item with what
   enabling would do (create, link offer, filtered, ...) and writes nothing.
3. **Enable** imports the items; later snapshots update them. **Ignore** drops
   a stream you don't want. While a stream is pending or disabled, its card
   shows what enabling would do ("would: created 5, link offers 2"), and the
   **Settings** link in the header carries an amber ring and count while any
   stream is pending review; the **Streams** link shows an amber count while
   link offers wait for an answer. A stream with no stored snapshot says
   "Waiting for the next snapshot" instead of Preview. (The read-only **Docker
   (register)** card lives in Settings → Docker.)
4. Each stream card has an **Edit** button that opens one dialog with its
   display name and network include / exclude lists (applied from the next
   snapshot; entries already imported are not removed), the staleness and
   missing-entry settings, and **Default checks**: a ping check on
   each entry's IP and, optionally, a TCP check on a port. New entries of the
   stream start with them; **Apply to existing entries** adds the missing ones
   to every active entry (an entry that already has a ping or TCP check is
   skipped).
5. **Disable…** and **Delete…** (in the card's ⋯ menu) open a dialog that shows the counts first, then
   asks what happens to the entries: **keep** (disable: they stay but stop
   updating; delete: they become manual entries), **soft delete** (restorable
   from Settings → Deleted) or **purge** (gone for good). The stored snapshot is
   kept when you disable, so Preview and Enable still work. Entries you
   customised (renamed, grouped, described, with an icon, checks or Home
   Assistant) are listed by name. Manual entries you linked to the stream are
   never deleted: soft delete and purge (and deleting the stream) turn them back
   into manual entries with their old host. Disable with purge can also clear the
   block list; deleting a stream always removes its blocks and link offers.
6. A stream entry's edit page has **Unlink from stream…**: the entry becomes a
   manual entry again (a linked one gets its old host back). **Allow
   re-offering** lets a later snapshot offer the link again; **Don't re-add**
   blocks the item.
7. **Staleness and missing entries** (a panel per stream): an enabled stream
   that sends nothing for **twice** its expected interval is **stale**: a red
   badge on the row ("No snapshot for 42 min (expected every 5 min)"), a red
   count on the header's Settings link, a `down` line in the health summary and a
   **Problem** sensor in Home Assistant. The interval is the one you set here,
   else the one the sidecar advertises, else 15 minutes. Its entries keep their
   own health. The same panel can **soft-delete entries missing for N days** (off
   by default; the daily cleanup job does it, and an item that comes back restores
   its entry). Entries you edited are never removed: linked, renamed, locked,
   grouped, described, with an icon, URLs, a sort priority, a widget, Home
   Assistant, or any check other than an untouched default check. A snapshot STD
   refused shows on the row as "Rejected 3 min ago: 400: ...".
8. **Blocked** lists items you deleted with "Don't re-add", with **Unblock**.
   **Link offers** lists manual entries that match a new item, with **Accept**
   and **Decline**.

## In the dashboard views

Stream entries show a blue pill with the stream's name on the Dashboard view.
Tiled and Compact show a small router icon instead (green; amber when the item
dropped out of the latest snapshot); Compact shows one source icon on every row
(Docker status, stream or manual). On the Dashboard an item that dropped out of
the latest snapshot gets an amber **missing** badge with how long ago ("missing
3 days ago"); Tiled and Compact say "since" in the icon tooltip and the drawer.
It is a warning, never Down: the entry's checks still decide its health, and it
is never deleted unless you turn on the stream's missing-entry expiry (below). The
expanded detail shows a stream entry's IP, MAC and network (and "Missing ...
since").
The **Source** filter lists each stream by name (`?source=stream:dhcp`). On a
stream entry's edit page the MAC, IP, network, attributes and stream are
read-only and the name stays editable (your name then wins over the sidecar's).
Deleting one asks **Allow re-adding** (the next snapshot may bring it back) or
**Don't re-add** (it is blocked). A manual entry with an open link offer shows a
**Convert** / **Keep separate** banner on its edit page; one without an offer
offers **Link to stream item…** to pick an unmatched item by hand.

## Over the API

The same operations, with an example:

```bash
# KEY is an `ingest` (or, for testing, a `write`) key. "dhcp" is the stream id.
curl -s -X PUT -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  "$STD/api/v1/streams/dhcp/snapshot" -d '{
  "display_name": "DHCP", "producer": "my-sidecar", "producer_version": "0.1.0",
  "key_type": "mac",
  "items": [
    {"key": "AA-BB-CC-00-00-01", "name": "shelly-pump", "ip": "10.0.40.21",
     "network": "IoT", "attributes": {"reservation_comment": "boiler room"}}
  ]
}'
# 202 {"stream_id":"dhcp","stream_status":"pending","applied":false,"item_count":1,"message":"..."}
```

- **A new stream is `pending`.** STD stores the snapshot (answering `202`) and
  applies nothing. Look at what it would do with
  `GET /api/v1/streams/dhcp/preview`, then
  `POST /api/v1/streams/dhcp/enable` applies the stored snapshot at once, and
  every later one as it arrives (`200` with counts of created, updated,
  unchanged, restored, missing, blocked, link offers and filtered items).
  `ignore` drops a stream you don't want.
- **What a snapshot does.** Each item becomes an entry (no host, source
  `stream`) with its IP, MAC and network. A device missing from a later
  snapshot is flagged missing, never deleted. Your edits stay: a rename of the
  entry wins over the sidecar's name, and group, icon, description, checks and
  Home Assistant settings are never written. `network_include` and
  `network_exclude` (set with `PATCH /api/v1/streams/dhcp`) leave networks out.
  Stream entries get no health checks unless the stream has
  `default_checks` (`{"ping": true, "tcp_port": 22}`, set with `PATCH` and
  applied to existing entries with `POST .../default-checks/apply`). When the
  sidecar reports a new IP, checks that pointed at the old IP (ping, TCP, DNS
  server, an HTTP URL with the IP as host) move to the new one; hostname targets
  are left alone.
- **Staleness and rejections (API revision 3).** A sidecar may add
  `"snapshot_interval_seconds": 300` to its snapshot (send it only when
  `GET /api/v1/meta` reports `api_revision` 3 or later; older STDs reject it).
  `PATCH /api/v1/streams/dhcp` takes `expected_interval_seconds` (wins over the
  sidecar's) and `missing_expiry_days`. `GET /api/v1/streams` reports `stale`,
  `stale_message`, `effective_interval_seconds`, `last_rejected_at`,
  `last_rejection`, `rejecting` and more, plus a `stale` count;
  `GET /api/v1/health/summary` adds `streams`, `stale_streams` and
  `counts.streams_stale`; entries report `inventory.missing_since`.
- **Link offers.** A new item whose name (or first DNS label) equals, ignoring
  case, exactly one active manual entry's name, host or host's first label is
  not created. It waits as a link offer: accept it
  and your entry joins the stream, keeping its id, history and checks (its host
  is cleared); decline
  it and a new entry is created.
- **Deleting a stream entry** (`DELETE /api/v1/entries/{id}?block=true`) can
  also put its key on the stream's block list, so a snapshot does not bring it
  back; unblock it with `DELETE .../blocks/{block_id}`. Without `block` the next
  snapshot that still holds the key restores it.
- **Disabling or deleting a stream** takes `cleanup`: `keep` (entries stay, no
  longer updated; deleting the stream turns them into manual entries),
  `soft_delete` (restorable from Settings → Deleted) or `purge` (gone for good).
  The stored snapshot is kept when disabling. Entries that were manual entries
  linked to the stream (`inventory.linked`) are never deleted: `soft_delete` and
  `purge` unlink them (back to manual, old host restored; counted in
  `result.unlinked`). `POST /api/v1/entries/{id}/unlink` (`{"block": bool}`) does
  the same for one entry.
- Snapshot posts are not written to the audit log; changes you make to a
  stream are. Limits: 5,000 items and 2 MiB per snapshot.
