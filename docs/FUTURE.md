# Future Discussion Area

This file holds design discussions that have been deliberately parked
— ideas that came up during scoped work on another feature and were
set aside rather than being either committed to or rejected.

This is **not** a roadmap. Items here may ship in a future release,
may be reconsidered and rejected, or may sit indefinitely. The PRD
(`docs/PRD.md`) is the document of record for what STD does and what
it is about to do. The CHANGELOG is the record of what shipped. This
file is the record of what was thought about and set aside.

Each entry should capture enough context that picking it up later
doesn't require re-derivation from scratch. Include the date it was
parked, the conversation context, the design as sketched, and the
explicit reason for deferral.

---

## Tools as a first-class concept

**Parked:** 2026-05-16, during v0.6.1 UI rework wrap-up.

### Context

v0.6.1 introduced a "Tools" button inside the Tiled expand drawer
that currently exposes only the Dozzle link. The button is the
visible seed of a broader Tools concept: each `ServiceEntry` could
have one or more tool links surfaced to the operator (Dozzle today,
Dockhand soon, and an unknown set later — Portainer, "jump to
compose file," "open in IDE," etc.).

Today, tools are hardcoded in two places:

- The Dozzle URL pattern is built in templates from
  `STD_DOZZLE_URL` (a single global config value, loaded from
  `settings.yml` / env) plus `entry.container_id`.
- The aspirational per-entry overrides `entry.dozzle_url_override`
  and `entry.container_id_override` were referenced in the old
  Tiled template but never existed on the model. Removed in v0.6.1.

This works for one tool. It will not scale to three.

### Sketched shape

Tools become a configurable concept with a few attributes per tool
definition:

- **Name** — operator-facing label ("Dozzle", "Dockhand").
- **Icon** — Tabler icon name, or a path/SVG reference.
- **URL template** — a string with variable substitution slots
  drawn from the `ServiceEntry` row. Initial variable set:
  `{container_id}`, `{container_id_short}` (first 12 chars),
  `{host}`, `{container_name}`, `{stack_name}`, `{image_name}`.
- **Enabled** — global on/off so a tool can be defined-but-hidden
  without deletion.
- **Applies-when predicate** — optional. A tool may not apply to
  every entry. Dozzle requires a container_id; some tools may
  require an exposure observation, a specific stack, or a host
  match. Keep this simple at first — a single predicate like "only
  if container_id is set" or "always" — and extend if real demand
  appears.

Storage: a new table (`tool_definition`) or a new key in the
existing `Setting` JSON store. Lean toward a real table once there
are more than ~5 fields per tool; the `Setting` JSON store is fine
for the initial small case but gets awkward when the operator wants
to edit, reorder, and validate individual tools.

Per-entry overrides: a `service_entry.tool_overrides` JSON column,
keyed by tool name, holding any of the URL-template variables that
should override the computed default. Use case: a homelab with one
Dozzle per host needs `{dozzle_base_url}` to vary per entry. This
is the proper-implementation of the aspirational override columns
the v0.6.1 cleanup removed.

Defaults: STD ships with a Dozzle tool defined by default, mapped
to today's `STD_DOZZLE_URL` config on first run (a migration job).
Operators add or disable from there.

UI:

- New settings tab ("Tools") for adding, editing, ordering,
  enabling, and disabling tool definitions.
- The Tiled drawer's Tools button renders the enabled, applicable
  tools for the entry. Single tool — direct link. Multiple — a
  small popover.
- The Dashboard table's Tools column does the same (currently
  hardcoded to Dozzle).
- Per-entry overrides exposed on the edit drawer/page in an
  "Advanced" section that's hidden by default.

### Why parked

The current single-tool implementation is genuinely fine for one
tool; it becomes a problem when the second tool (Dockhand) is added.
Designing a full Tools abstraction before there is a concrete second
tool would be designing into a vacuum.

State of the world as of v0.6.6: Dozzle is still the only tool. The
Tiled drawer's Tools popover and the Dashboard table's Tools column
still build URLs from the single global `STD_DOZZLE_URL` config plus
`entry.container_id`. No `tool_definition` table, no per-entry
overrides.

Reconsider when: a second tool is concrete enough to need a URL
pattern, OR the operator finds themselves wanting per-host Dozzle
overrides. Whichever comes first.

### Open questions for when picked up

- Are tool definitions per-installation, or are there "system"
  tools that ship with STD and user-added tools that the operator
  manages? (My instinct: just user-managed, with defaults seeded
  on first run. One concept is better than two.)
- Should tools support actions that mutate state ("restart this
  container") or are they strictly navigation links? Strong lean
  toward strictly navigation. Mutation is a much bigger surface
  (auth model, error handling, rate-limiting, audit), and a
  homelab dashboard isn't where that belongs.
- Per-tool authentication — if a tool URL requires an API key, does
  STD store that and inject it, or does the operator handle auth
  on the tool's own end? Strong lean toward the latter; STD is not
  a credentials vault.

---

## Service identity and duplicate detection

**Parked:** 2026-05-16, during v0.6.1 wrap-up. Design ongoing in
conversation; full design captured here for posterity.

**Design for 0.14.0:** [`docs/design/2026-11-22-moves-and-label-settings.md`](design/2026-11-22-moves-and-label-settings.md)
(awaiting operator approval; this entry stays until it ships).

### Context

When a service moves between hosts, or gets renamed, today's
`(host, container_name)` match key produces a duplicate row: the
old deployment goes stale, the new one starts fresh and empty.
Operator-curated state (group, sort_priority, widget config, manual
URL overrides) lives on the stale row and has to be manually
migrated or re-entered.

Widget detach-on-delete (proposed at the time of parking as a v0.6.3
feature) would have reduced the *cost* of mishandled moves by
preserving widget config when the stale row is deleted. It did not
ship — v0.6.5 introduced a universal delete popover but the delete
itself is still a hard delete that drops the widget row along with
everything else. Either way, detach would only reduce the *cost* of a
mishandled move, not the *frequency* — the operator still needs to
notice the duplicate exists.

### Sketched shape

A **Duplicates** surface in Settings that lists candidate pairs of
service entries STD thinks might be the same logical service.
Computed on-demand when the operator opens the tab — no schema
changes, no continuous background job.

Candidate criteria — a pair `(row_A, row_B)` is a candidate if
**one row is fresh** (last_api_update within 2h) **and one is
stale** (older than 2h or null), AND any of:

- Same primary exposure hostname.
- Same `image_name` AND same normalized `container_name`
  (lowercased, hyphens/underscores stripped — catches
  `homeassistant` ↔ `home-assistant`).
- Same `image_name` AND same `stack_name` on different hosts.
- Same explicit URL (`internalurl` or `externalurl`) where source
  is `ui_edit` or `explicit_label`.

Static entries (`is_static = true`) excluded from both sides.

**Resolution UI:** side-by-side comparison of the two rows. Three
actions:

- **Merge B → A** (where A is the fresh row): transfer
  operator-curated fields from B to A where A's value is null,
  delete B. Specifically: `group_id`, `sort_priority`,
  `widget_id`, `image_icon` (if A's was auto-fetched and B's was
  override), URLs where B's source is `ui_edit` and A's is
  `synthesized`.
- **These aren't the same** — record the dismissal in a new
  `duplicate_dismissal` table so the pair stops being surfaced.
- **Cancel** — close, decide later.

**No auto-merge, ever.** Confidence high enough to bypass operator
confirmation doesn't exist for this kind of operation. Cost of a
wrong merge is exactly the data loss the feature is trying to
prevent.

**Surfacing:** Settings → Duplicates tab. No top-of-dashboard
banner, no popup. Optionally a count badge on the Settings nav if
discoverability proves a problem — but start without it.

### Active-active false positive

If the operator runs a service on two hosts (active-active) and one
side fails (becomes stale), the heuristic will flag the pair as a
candidate. This is technically a false positive but operationally
useful — the operator wants to know one side died anyway. Cost is
a "These aren't the same" click to dismiss, which is cheap.

An explicit "intentionally replicated" mark on a row to suppress
duplicate suggestions even when one side goes stale was considered
and rejected as YAGNI until the false-positive volume actually
proves annoying.

### Why parked

Not yet scheduled. The original parking notes sketched a four-step
sequence (v0.6.1 extraction → v0.6.2 edit drawer → v0.6.3 staleness-
plus-widget-detach → v0.7.0 duplicate detection) that did not pan
out — v0.6.2 became a hotfix, v0.6.3 shipped the changelog-popup
foundations instead, and v0.6.4–v0.6.6 were the mobile / edit-polish
/ widget-drawer arc (see PRD §10).

**Update 2026-11-15:** both prerequisites are now planned for v0.6.9 —
unified staleness with a single `stale_after_minutes` threshold (PRD
§12.7) and widget detach on hard delete (PRD §12.6), alongside
soft-delete (PRD §12.5, formerly parked here). Once those ship, this
entry is unblocked. Note two interactions for whoever picks it up:
soft-deleted rows must be excluded from both sides of a candidate
pair, and the single threshold here should be the §12.7 setting
(default 5 min — far tighter than the 2h sketched above; decide then
whether duplicates need their own, looser threshold).

The more ambitious service identity concept (computed column on
every row, `group_by` axis treatment, move-aware API) remains
explicitly out of scope until manual duplicate resolution exists
and proves insufficient.

### Open questions for when picked up

- Single stale threshold (used for Docker pill yellow, row clock
  icon, AND duplicate eligibility) vs. per-purpose thresholds.
  Lean toward single threshold.
- Cached badge count on Settings nav vs. no badge. Start without;
  add if operator forgets to check.
- Move-aware API endpoint (`/api/v1/move`) for orchestrator-driven
  moves (Ansible, Dockhand) to pre-declare an intended migration.
  Deferred even past v0.7.0; gated on the move workflow actually
  existing.

---

## Monitoring follow-ups (after v0.7.0)

**Parked:** 2026-11-15, during the v0.7.0 "Dashboard and Monitoring"
design session (PRD §13). Each item came up and was deliberately kept
out of 0.7.0 to hold its scope to manual entries, the check model,
history and filters.

- **Alerting rules and push channels.** For example webhook, ntfy,
  Gotify or email when a check goes from ok to failing (or after N
  consecutive failures; `health_check.consecutive_failures` already
  exists for this), with de-duplication and quiet hours. State
  publishing to MQTT and Home Assistant is scoped in PRD §17 and builds
  the channel framework these would plug into.
- **Publish every check result to MQTT.** Operator decision (PRD 17.1):
  state publishing sends changes only, retained. An option to publish every
  result (latency graphs from the broker) was left out of notif-02; if
  wanted, add it as a per-channel setting on top of `notify_state`.
- **Home Assistant "Check now" button.** A `button` entity per entry that
  makes STD run its checks at once (the management API already has
  `POST /entries/{id}/checks/run`). Needs a command subscription, which
  makes STD act on unauthenticated broker messages, so it needs a security
  review (who may publish, rate limits) first. Operator decision (PRD 17.1):
  no command entities in the first version.
- **Per-result latency sensors for Home Assistant.** Requires publishing every
  check result (see above), then a latency `sensor` per check. Left out of
  notif-03.
- **Notifier-defined service checks.** A container label (e.g.
  `dockernotifier.std.check.type=tcp`, `...check.target=...`) that the
  notifier forwards so service checks come from compose, not the UI.
  This is a **register-contract change**: STD must add the field to
  `RegisterPayload` and ship first, then the notifier sends it.
  Ownership also needs deciding (do UI edits beat labels, as with URL
  provenance?). Parked on user direction: the notifier sends nothing
  new in 0.7.0.
- **More check types.** HTTP keyword or
  JSON-path match. The 0.7.0 body mode (`OK` /
  `Error: <msg>`) covers the custom-endpoint case.
- **Longer history and a status page.** 30-day uptime, a public
  read-only status page. 0.7.0 keeps 7 days.
- **Drop the deprecated health columns.** `service_entry.*_health_check_*`
  and the per-entry `health_check_timeout` / `health_check_verify_tls`
  stop being read in 0.7.0 but are kept so a rollback to 0.6.9 still
  works. Drop them in a later release's migration, and stop exporting
  them in backups at the same time.

---

## Register overwrites some operator edits

**Design for 0.14.0:** [`docs/design/2026-11-22-moves-and-label-settings.md`](design/2026-11-22-moves-and-label-settings.md)
§3 (per-field provenance; awaiting operator approval; this entry stays until it ships).

Parked 2026-11-16, during v0.9.0. The operator asked whether a register
zeroes out manually configured items. It doesn't. `upsert_service` in
`routes_api.py` only writes the fields the payload carries, and
ui_edit URLs, group/priority under `user_wins`, description, service
checks and check settings are all safe. Two fields are still clobbered,
though.

### Context

- **Icon.** `resolve_image_metadata` derives an icon from the image name
  on every register, e.g. `traefik.svg`. When one exists,
  `entry.image_icon` is overwritten, so a custom icon picked or uploaded
  on Edit is replaced at the next register. Today the only protection is
  locking the entry.
- **URL-check toggles.** When the payload carries
  `internal_health_check_enabled` / `external_health_check_enabled`, it
  sets `enabled` on the URL check row. A check the operator turned off in
  the UI can therefore be turned back on.
- **Minor: deliberately ungrouped.** Under `user_wins`, a NULL `group_id`
  counts as "unset", so the notifier's group is applied again after the
  operator clears the group.

These findings come from reading the code; no test reproduces them yet.

### Sketched shape

Mirror URL provenance: record when the UI set the value, and have the
register skip it.

- `image_icon_source`: `ui_edit`, or NULL for auto. The register writes
  the icon only when the source isn't `ui_edit`.
- A per-check `enabled_source` (or a `user_set` flag) on the URL-check
  rows, so a register toggle doesn't override a UI toggle.
- Optionally an "explicitly ungrouped" marker, so `user_wins` respects a
  cleared group.
- The notifier's values are still recorded, as with the
  `notifier_reported_*` columns.
- Start with tests that reproduce each clobber.

### Why parked

The operator chose to ship v0.9.0 without it ("leave it as is for now").
Locking the entry is the workaround.

---

## UniFi inventory source and discovered-device inbox

**Parked:** 2026-11-17, during the network-inventory design review
(`docs/design/2026-11-17-network-inventory-and-profiles.md`).

### Context

The first draft of the network-inventory design had two sources:
Technitium DHCP reservations ("what should exist") and the UniFi
Integration API ("what is actually on the wire"). UniFi also fed a
discovered-device inbox (MACs seen but not reserved, with Adopt /
Attach to entry / Ignore) and link facts (AP or switch port, SSID,
RSSI, uplink).

### Why parked

Every IoT device the operator cares about gets a Technitium static
reservation, which already gives hostname, MAC, IP and scope. UniFi
would import phones, laptops and other end-user devices the operator
doesn't want in STD. Hosts with hard-coded IPs (VMs, hypervisors, the
UDM) are added by hand as manual entries. The unknown-device detector
is a security feature nobody asked for.

### If picked up

- UniFi as a sidecar on the stream ingest API (design doc §6), like
  the Technitium one. A filter would be needed to keep end-user
  devices out (e.g. only wired, only named, only certain networks).
  An "inbox" is then just a pending stream's Preview.
- Link facts are volatile (RSSI changes constantly). Keep them off the
  MQTT entry attributes watched by `notify_state._ENTRY_ATTRS`, or
  every sync triggers a full republish. A separate throttled
  attributes topic would work.
- Multi-NIC entries would then need an interfaces table.

---

## Notifier: log STD's API revision

**Parked:** 2026-11-17, after the API revision landed on `dev` (PRD 18.1).
This is work in the docker-api-notifier repo, not STD.

### Context

STD 0.10.0 sends `X-STD-API-Revision` and `X-STD-Version` on every
`/api/...` response and serves a public `GET /api/v1/meta`. Today's
notifier ignores both and still works, because the change is additive:
the register contract and its responses are unchanged. STD logs each
new `User-Agent` once, so a notifier that sends the library default
(e.g. `python-requests/2.x`) shows up under that name.

### Sketched shape

- Send `User-Agent: docker-api-notifier/<version>`.
- Read `X-STD-API-Revision` on each register response and log at INFO
  when it differs from the last value seen.
- Optionally call `GET /api/v1/meta` at startup and log `std_version`
  and `api_revision`. Treat a 404 as "STD older than 0.10.0", not an
  error.

### Why parked

Nothing breaks without it, and it needs no STD change. Pick it up the
next time the notifier gets a release. The sidecar
(`std-source-technitium`) does the same thing and can serve as the
model.

---

## Stream observability follow-ups

**Parked:** 2026-11-20, during inv-08 (stream observability, PRD §18.9).

### Context

inv-08 made stale producers, rejected snapshots and missing records visible and
moved checks with a changed IP. A few adjacent ideas came up and were left out to
keep the change set small.

### Sketched shape

- **Templated check targets** (`{inventory.ip}`, `{inventory.mac}`, hostname)
  resolved at check time. Rejected for now in favour of rewriting targets on IP
  change (see `docs/decisions.md`, 2026-11-20); worth revisiting together with
  monitor profiles (design doc §7), where a profile's checks are templates anyway.
- **Staleness on the ingest status route.** `GET /streams/{id}/status` could carry
  the effective interval and `stale`, so a sidecar can log what STD expects. Needs
  an additive ingest field (a revision bump).
- **Notifications on transitions.** The staleness and missing-expiry events are
  logged and published as retained state; alert policies (design doc slice 5)
  would turn them into pushes.
- **Expiry vs. `deleted_retention_days: 0`.** With retention 0 the purge job
  hard-deletes auto-expired entries in the same run, so the "item returns, entry is
  restored" path cannot happen; the job could skip entries soft-deleted in that run.

### Why parked

None of these is needed to see a dead producer or a vanished record; each adds a
contract or a policy decision that is better made with real use of the first
sidecar.


---

## Small gaps parked after v0.10.1

**Parked:** 2026-11-20, during the post-v0.10.1 gap triage (all browser checks
passed on 0.10.1).

### Context

Two known limits from notif-05 and inv-04 were judged too minor to fix now. Both
work as designed and are recorded in `docs/decisions.md`; they are parked here so
they don't keep coming back as open gaps.

### Sketched shape

- **Persist the "republish: false" purge hold.** `PublishState.held` is in memory
  only, so a restart ends the hold and the channel republishes on connect
  (decisions.md, 2026-11-17 notif-05). It could be stored with the published set in
  the `notify_publish_state` setting and released by the same triggers. It only
  matters if STD restarts between a purge and the operator's next change.
- **Rename a stream.** `display_name` is set when the stream is created and
  snapshots never change it (decisions.md, inv-04). A rename field in Settings →
  Streams (and on the management API) would set it; snapshots would keep ignoring
  the producer's value. Needs the MQTT/HA stream device to be republished with the
  new name.

### Why parked

Neither has come up in real use: a restart during a purge hold is rare and the
outcome (republish) is the unsurprising one, and current stream names come from
the sidecar and are fine.


---

## Settings follow-ups (after 0.11.0)

**Parked:** 2026-11-20, at the end of the Settings modernization (design
`docs/design/2026-11-20-settings-modernization.md` §15).

### Context

The Settings page was rebuilt in the card and dialog pattern in 0.11.0. These
follow-ups were left out on purpose: each is small, none blocks the new layout.

### Sketched shape

- **Toasts on the Dashboard, Tiled and Compact views** ("Entry updated", "Logged
  in"). Today those flashes wait in the session and `_drop_stale_success_flashes`
  drops them.
- **One combined "save stream" route** so the Edit stream dialog has a single Save
  instead of one per block.
- **Edit a user's email or admin flag.** No route exists; Users only sets a password
  or deletes.
- **Search across all of Settings.**
- **A per-entry Home Assistant preview** (which entities each device would get).
- **A JS test runner** for the settings modules (`ui.js`, `nav.js`, `groups.js`,
  `streams.js`, ...). They are checked by hand in a browser today.

### Why parked

The first three change behaviour or routes beyond a restyle, and the rest are
conveniences. Renaming a stream from its card is already parked above.

---

## Ports from manual and stream entry URLs

**Parked:** 2026-11-21, while building the Ports page (GitHub #58).

The Ports page lists only what the notifier observed on Docker containers. Manual and
stream entries have no observed ports, but their `internalurl` often carries one
(`http://nas.lan:5000`). Parsing it would let the page show those too, flagged as
"from URL" (a guess, not an observation) and possibly in conflict checks. Deferred: a URL
port is not a binding, and a conflict claim built on it would often be wrong (proxies,
redirects).

## Remember the last-known ports of stopped containers

**Parked:** 2026-11-21, while building the Ports page (GitHub #58).

Docker clears published ports when a container stops, so a stopped container vanishes from
the page and its port reads as free, though it will reclaim it on start. Remembering the
last-known bindings (a column, shown dimmed as "stopped") would catch that conflict early.
Deferred: it needs a migration and a rule for when a remembered port expires, and the
observation columns are pure overwrite today.

## Image check: a global default for version-tagged images

**Parked:** 2026-11-26, after v0.13.4 (operator: "leave it for now").

An entry on a version tag (`tecnativa/docker-socket-proxy:v0.4.1`) uses the tag model under
the default `auto` policy, so STD suggests newer tags (`v0.4.2`, `v0.5.0`). Komodo only
reports when the running tag itself is republished, so the two disagree and STD's badges
look like "needs a pull" when the fix is a compose edit. The per-entry `digest` policy
already gives Komodo's behavior; what is missing is a global default, so today it means
setting every such entry by hand (13 socket proxies on emmett).

Sketch: a Settings → Image updates choice for **version-tagged images**, the default for
entries whose policy is `auto`:
- **Suggest newer versions** (today's behavior; the default).
- **Only watch for a republished tag** (as if the policy were `digest`).
- **Don't check** (as if `off`).

Tags with no version (`latest`, `stable`) keep the digest model either way, and an entry's
own policy always wins. It goes in `image_tags.choose_model` / `evaluate` (a new
`default_policy` argument beside `default_scope`), the settings store, the Settings page and
the management API's `settings/image-updates` (an API revision bump). A change recomputes
locally like the scope does, with no registry call. No register contract change, so it is
independent of the 0.14.0 label settings (whose per-container `image_update_policy` label
would override it).

## Run the container as a non-root user

**Parked:** 2026-11-22, during the image CVE review (todo; operator wants it done).

STD runs as **root** today: the Dockerfile has no `USER`. A non-root user is a bigger
security win than any base-image change (see `docs/decisions.md`, 2026-11-22 "Image
patching at build time", and the base-image comparison: slim stays).

Sketch:
- `PUID` / `PGID` env (default 1000/1000, matching the crzynet compose convention).
  `entrypoint.sh` runs as root only long enough to `chown` `/config` (existing installs
  are root-owned) and then drops privileges (`gosu` / `setpriv`) for `restore_swap.py`,
  `alembic upgrade head` and gunicorn. `restore_swap.py` must still always exit 0.
- Port 8815 needs no privileges. The ping health check uses unprivileged ICMP
  (`icmplib`), which works under Docker's default `net.ipv4.ping_group_range`. Verify it,
  and document the sysctl for hosts that override it.
- Check every path STD writes: `/config` (DB, icons, backups, restore staging,
  import staging) and anything under `/app` written at runtime (`version.txt` is written
  at build).
- Tests: the entrypoint on a root-owned `/config`, a fresh `/config`, and an
  already-owned `/config`; a ping check as non-root. CHANGELOG under Security, plus README
  compose examples with `PUID`/`PGID`.

Related, smaller: a scheduled weekly rebuild of `:latest`, so Debian fixes reach installs
without a code release (Dependabot doesn't bump a floating `3.11-slim` tag); and the move
from Python 3.11 to 3.13 before 3.11 goes EOL (October 2027).

## Adding entries

Append new sections at the bottom. When an item moves into a real
release plan, remove it here and reference the PRD section that
picks it up.
