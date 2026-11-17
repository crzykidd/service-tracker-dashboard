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

## Adding entries

Append new sections at the bottom. When an item moves into a real
release plan, remove it here and reference the PRD section that
picks it up.
