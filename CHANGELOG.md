# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/crzykidd/service-tracker-dashboard/compare/v0.7.0...HEAD
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
