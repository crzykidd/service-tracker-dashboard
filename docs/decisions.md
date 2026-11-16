# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-15 — v0.8.0 Management API design calls

Scoped with the operator; plan in PRD §14.

- **Separate admin keys, not the notifier token.** `api_token` lives in
  `settings.yml` on every Docker host running the notifier. Giving it
  management power would turn any leaked host config into full dashboard
  control. It stays register-only, and management uses DB-stored, named,
  revocable keys with `read` and `write` scopes (operator's choice).
  Rejected: reusing `api_token`; a single `admin_api_token` in settings
  (it can't be revoked per key and rotating it needs a restart).
- **SHA-256 for key hashes, not a password KDF.** Keys are 32+ random
  bytes, so there is nothing to brute-force; a slow KDF would only add
  latency to every API call.
- **Management endpoints accept only the bearer key, never the session
  cookie.** That makes them CSRF-exempt by construction instead of
  half-exempt. Browser-side JSON endpoints stay session-only and
  unchanged.
- **API URL edits are `ui_edit`** (operator's choice). An agent acting for
  the operator has the same intent as the browser, so the notifier and
  synthesizer must not overwrite it. Rejected: a separate `api_edit`
  provenance value.
- **One validation path.** The Add/Edit check rules are refactored into
  shared functions instead of copying them into API schemas, so the UI and
  API can't drift.
- **The MCP server is a separate stdio client in `mcp/`, not part of the
  image.** The MCP SDK is async, while STD is Flask/gunicorn with one
  worker. A stdio wrapper over the REST API keeps the image and attack
  surface unchanged, and it runs next to Claude Code. Rejected: an MCP
  endpoint hosted inside STD.
- **`settings.yml` stays read-only over the API.** It is loaded once at
  startup, so editing it remotely would mean writing the host's config
  file and restarting. Only DB-stored runtime settings (exposure
  directions) are writable.
- **Users and passwords are excluded from the API.** An API key must not be
  able to mint logins.

---

## 2026-11-15 — Inline uptime strips: cookie, merged bars, id cap, reload refresh

- **Cookie, not localStorage or a URL param**, as requested: the server reads
  `std_show_uptime` to render the checkbox and the `show-uptime` body class
  without a flash. It is only compared to `'1'`.
- **One merged strip per service.** A slot is red if any counting check failed
  in it; the % is Σ ok ÷ Σ samples over the 48 buckets (so it covers the
  window ending at the current half-hour, slightly different from the detail
  panel's rolling 24h figure).
- **`/health/strips` caps at 500 ids by taking the first 500** (extra ids are
  ignored, not a 400); the JS chunks at 500 so a huge page still gets every
  strip. Non-numeric ids are skipped.
- **Auto-refresh already reloads the page**, so "re-fetch each cycle while on"
  needs no extra timer: the reload re-fetches only when the cookie is on.
- **Strip containers are always in the markup** and hidden by CSS unless the
  body has `show-uptime`, so toggling needs no reload. Clicking a strip does
  not open the tile's URL (Tiled and Compact tile handlers ignore it).

---

## 2026-11-15 — Count chips ignore the Status filter; Stale has no chip

The Total / Passing / Failing chips count entries after Source and Show
URL-less but ignoring Status, so each number equals what its link shows and
the chips stay stable while you switch between them. Unknown / Not monitored
are in Total only and the `stale` status keeps only the Status select, as the
design specified. The chip links are built server-side from `request.args`
(not JS) and keep every other param. The Status select's `Healthy` option and
the `Passing` chip label are the same filter (`status=healthy`).

---

## 2026-11-15 — `/widget_config` path built from the listdir name (CodeQL)

CodeQL kept two `py/path-injection` alerts open on `routes_widgets.py`
after v069-11: a `widget_name not in known` membership test is not a
sanitizer it recognises, so the request value still reached
`os.path.join`. The route now picks the matching entry *from*
`os.listdir(widgets/)` and builds the path (and the warning log) from
that name, so no request data reaches the filesystem. Behaviour is
unchanged (unknown or traversal names still return `[]`); no CHANGELOG
entry because operators see no difference.

---

## 2026-11-15 — v070-07 Container check: Docker state is a check (supersedes "Docker state is not a check")

Reverses the v0.7.0 design call that kept Docker state out of the health
rollup: the user chose an automatic per-entry check over a rollup-only
fallback. Implementation calls:

- **A real `health_check` row, not a rollup special case**, so history,
  uptime, bars, compaction and the detail panel work unchanged.
- **Evaluated on the scheduler thread** (a DB read; no pool, no network) and
  never in the register request, which only queues `jobs.request_run`.
- **Stale wins over status** in the message: with no recent report the stored
  status is not trustworthy, so `No update from notifier for N min` is shown
  even if the last status was `exited`.
- **Register also queues a run while the container check is failing**, not
  only when `docker_status` changes. Otherwise a stale entry that comes back
  with the same `running` status would stay Down until the interval.
- **Locked entries are skipped like a disabled check** (frozen state is not
  evidence). Unlocking on Edit clears `last_checked_at` so it re-evaluates.
- **`docker` is not in `CHECK_TYPES`**, so it cannot be picked on a service
  check; the form's `cc_row` marker stops an old page from disabling it.
- **No new column**, so no FK index; the migration is data-only and idempotent.
- Test helpers in `test_checker.py` / `test_health_schema.py` now default to
  manual entries so URL-check tests are not perturbed by the notifier-only check.

---

## 2026-11-15 — v070-06 health detail panel: implementation calls

- **Only enabled checks with a target appear in the panel** (the same
  "can run" rule as the rollup). Disabled checks keep their stored history
  but are not shown; re-enabling brings the bars back.
- **Buckets are clock-aligned,** the last bar being the current partial
  half-hour (24h) or hour (7d), so a bar's edges do not move between
  fetches. Window = 48 x 30 min / 168 x 1 h ending at the next boundary.
- **Range rows are clipped to the window after splitting:** the sample count
  is divided across every bucket the range overlaps (largest remainder), then
  buckets outside the window are dropped, so a range straddling the edge
  contributes only its inside share. Uptime reuses the same code with one
  bucket, so 24h/7d uptime is a sample-weighted figure that agrees with the
  bars.
- **Unknown `range` falls back to `24h`** (like the other query params)
  rather than 400.
- **Uptime is `null` with no samples** (shown "n/a"), not 0 or 100.
- **Edit-page panel sits outside the `<form>`** as its own "Health history"
  block (anchor `#health-history`); the existing `#health` anchor still
  points at the checks form, which Compact links to. It loads on page load.
  Tiled loads when the drawer opens; Dashboard when the row expands.
- **Open Dashboard expand row pauses auto-refresh** (as an open drawer
  does), otherwise the 30 s reload would collapse it. The expand row follows
  its entry on text filter and group collapse.
- **Dashboard row panel is `position: sticky; left: 0`** with a capped width
  so it stays in view when the table scrolls sideways on a phone.
- **Server text is rendered with `textContent`** (failure messages come from
  remote hosts); no innerHTML.
- **Dark theme only.** The app has no light theme, so bar colours use the
  existing status tokens. At 390 px the 7d strip drops its 1 px gap (168 bars
  in ~330 px aliased to grey).
- **CHANGELOG [Unreleased] was reconciled across chunks 01-06:** three
  earlier lines described interim states ("nothing new is shown yet", "a
  button for it comes later", "screens to configure them follow") and were
  rewritten to describe 0.7.0 as shipped.
- **PRD §3.1 module layout still omits `checker.py`, `health_state.py` and
  `health_history.py`** (earlier chunks did not add them either); left for a
  docs refresh. CLAUDE.md's layout lists all three.

---

## 2026-11-15 — v070-05 rollup and filters: implementation calls

- **Only checks that can run count in the rollup.** An enabled URL check
  whose URL is empty (or a service check with no target) is skipped: the
  scheduler never runs it, so counting it would leave the entry `unknown`
  forever, or show a stale failure after the URL was cleared. A cleared URL
  with only that check enabled therefore reads `none`.
- **`up` when nothing that has run is failing,** even if another enabled check
  is still waiting for its first run (a freshly added service check should
  not flip a green entry to `unknown`). `unknown` is only "none has run".
  Reading the PRD table as "every enabled check ok" would be stricter;
  rejected because new checks would flap state.
- **URL link icons lost their health colour.** The "keep the per-URL link
  icons; only the health signal changes" instruction was read as: Dashboard
  pills become neutral "Open" links and Tiled icons are blue links (grey
  when no URL), with the last result in the tooltip / drawer. The status code
  label on the Dashboard pill is gone (the badge replaces it).
- **Dashboard gets a new Health column** (after URLs) rather than reusing the
  Status (Docker) column; Docker stays a separate signal (decision earlier
  today). The group-header `colspan` went 11 -> 12.
- **Legacy mirror removed; backups still emit the legacy keys,** now derived
  from the check rows (`_legacy_status` / `_legacy_update` in `models.py`,
  update time converted to server-local) so a backup stays restorable by an
  older STD. Restore still writes the status strings into the old columns
  (generic field loop); nothing reads them but `dbdump.html`. Dropping the
  columns is a later migration (not in this chunk).
- **`time_since_utc` filter** added: check timestamps are naive UTC and
  `time_since` assumes local time.
- **"Total Services" format:** `shown / total` only when a filter (including
  `show_urlless=false`) hides entries; plain number otherwise. Total is the
  count of active entries.
- **Unknown `status`/`source` values fall back to `all`** (as `group_by`
  does), so a mangled bookmark never yields an empty page.
- **Compact badge links to `/edit/<id>#health`;** the Edit page's checks
  section got `id="health"` (a wrapper div).

---

## 2026-11-15 — v070-04 check configuration UI: implementation calls

- **Supersedes the v0.6.9 note that Add/Edit don't render flashes.** They do
  now (`partials/flash_messages.html`, shared with Settings, colour by
  category: `danger` red, `warning` amber, else green). Validation errors on
  Add/Edit flash and re-render with the operator's input kept.
- **Stale flashes.** The Dashboard views still render no flashes, so
  "Logged in" / "Entry updated" notices queue until a page that does. Add and
  Edit drop queued non-warning/non-danger flashes on entry
  (`_drop_stale_success_flashes`) so they do not surface as noise; warnings
  and errors are kept (the failed delete confirmation redirects to Edit).
  Rejected: rendering flashes in `base.html` (touches every page, out of
  scope). Existing tests that read flashes from the session after an Add
  error now assert on the rendered page.
- **`checks_form` marker.** Edit only touches checks when the hidden marker is
  posted, so scripted or older POSTs that do not know the section leave
  checks alone (the old toggles meant "absent = off").
- **Whole form rejected on any check error;** all errors are listed at once.
  Rejected: saving the valid parts (partial saves are confusing).
- **Blank service-check name defaults to the target** (clipped to 100)
  instead of erroring; a name is not needed to run a check.
- **Service-check ids that do not belong to the entry are an error,** not
  silently recreated, so a stale form (check deleted in another tab) cannot
  resurrect or cross-edit checks. Cap of 20 service checks per entry.
- **Non-HTTP checks store mode `status` and verify on,** whatever the hidden
  HTTP-only fields posted.
- **Ping target accepts hostname or IP only** (no port, no path); IPv6 with
  or without brackets for TCP, bare for ping. `checker._split_host_port` is
  now public `split_host_port`.
- **Add page URL fields** keep their old names (`internal_url`,
  `external_url`); the Add page now keeps the typed URLs, group, sort
  priority, icon and lock on an error re-render.
- **Mobile.** Verified at 390 px with headless Chromium: the form fits. The
  existing top nav overflows horizontally at that width on every page
  (pre-existing, not touched).

---

## 2026-11-15 — v070-03 checker engine: implementation calls

- **Compaction works on whole clock hours only.** The cutoff is
  `now - health_raw_hours` floored to the hour, so a run inside an hour is
  merged exactly once and never split across two compaction passes (a literal
  cutoff would leave two adjacent range rows for the cutoff hour). Samples
  stay raw up to one hour longer than `health_raw_hours`. A single raw
  success becomes a range of one (`ts_end = ts`) so it is not rescanned.
  Range rows have `status_code` / `message` cleared.
- **Purge uses `coalesce(ts_end, ts)`** so a compacted range survives until
  its last sample is older than `health_history_days`. Purge is hourly at
  :03 (before compaction at :05) and deletes in batches of 2000.
- **Latency average is weighted by samples**, `latency_max_ms` is the max of
  the maxima.
- **Service-kind checks are already scheduled.** The selection handles any
  enabled check with a target, not just URL kinds, so v070-04 only needs UI.
  No legacy mirror for them.
- **`ProbeResult` has a fifth field, `error_type`.** The legacy badge strings
  (`Error: SSLError`, a digit for pass) are derived by `legacy_status()`;
  `message` now carries `ExceptionName: text` as PRD 13.4 says (it was just
  the legacy string before). Failing bodies on a 2xx status map to
  `Error: CheckFailed` in the mirror; they only occur on non-URL-default
  modes and the mirror goes in v070-05.
- **Tick uses its own app context per pass** so the loop thread never
  carries a stale identity map between ticks; `collect()` then `submit_due()`
  in one tick, so a result lands at most one tick (5 s) after its probe
  finishes.
- **Ping timeout is per reply** (3 packets, 0.2 s apart), so a dead host can
  take up to about 3x the timeout. `avg_rtt` is rounded to whole ms (a LAN
  host shows 0).
- **Ping fallback:** `SocketPermissionError` (or `PermissionError`) on the
  privileged socket retries unprivileged; both failing gives `ICMP not
  permitted`. Verified in the built image: with default caps and with
  `--cap-drop NET_RAW` (the kernel's `ping_group_range` still allows the
  datagram socket) pinging 127.0.0.1 and the default gateway succeeded.
- **Check now needs login only**, not admin, matching "login, CSRF" in the
  prompt; it only clears timestamps.
- **`requirements.txt` regenerated with `uv pip compile`** (adds
  `icmplib==3.0.4`; nothing else changed).

---

## 2026-11-15 — v070-02 health schema: implementation calls

- **Templates read `enabled` from the check rows, not the legacy column.**
  The prompt says to stop writing the legacy `*_enabled` columns, but the
  Dashboard/Tiled badges and the Edit toggles read them. Rather than keep
  mirroring `enabled`, those bindings moved to `entry.internal_check_enabled`
  / `external_check_enabled` (properties over the rows). Only the status and
  update strings are still mirrored (the TEMP mirror).
- **Backup keeps the legacy keys, derived from the rows.** `to_dict()` still
  writes `internal/external_health_check_enabled`, `health_check_timeout` and
  `health_check_verify_tls` (from the rows) next to the new `checks` list, so
  a backup taken now restores correctly on an older STD (rollback story).
  Restore ignores those keys when `checks` is present.
- **Downgrade copies state back.** Because the legacy `*_enabled` / timeout /
  verify columns are no longer written, the migration downgrade copies them
  from the check rows before dropping the tables; otherwise a rollback would
  silently revert operators' toggles to their pre-upgrade values.
- **Legacy update time converted to UTC.** `*_health_check_update` is
  server-local; `last_checked_at` is naive UTC (PRD 5.6). The migration
  converts using the migrating host's local zone. An unparsable string gives
  NULL.
- **Status below 400 is ok, everything else failing**, in both the
  migration seed and the checker. A numeric >=400 status stores the code and
  uses the code string as the message; `Error: X` stores no code.
- **Timeout/verify-TLS apply to both URL rows.** One form value writes both
  rows; reads (Edit page, legacy backup keys) use the internal row, falling
  back to external.
- **`check_url` became `probe_url`** and takes a check (reads
  `timeout_seconds` / `verify_tls`) and returns a dict (ok, status_code,
  latency_ms, message, status) instead of just the status string.
- **Restore replaces service-kind checks wholesale** with the backup's list
  (an empty `checks` removes them); URL rows are matched by kind. Rejected:
  merging, which would leave deleted checks behind.
- **No uniqueness constraint on (entry, kind).** "Exactly one per URL kind"
  is kept by `ensure_url_checks`; a partial unique index is a possible
  hardening for a later chunk.
- **No result pruning yet.** The interim loop writes a `health_result` row
  per enabled check per pass with nothing deleting them; retention and
  compaction belong to v070-03. Do not release between the two chunks.

---

## 2026-11-15 — v070-01 entry sources: implementation calls

- **Adoption also applies to a soft-deleted manual match.** The register
  path already resurrects a soft-deleted row it matches; adoption runs before
  that, so a deleted manual entry that the notifier reports comes back as a
  notifier entry. Rejected: skipping deleted manual rows (would create a
  duplicate beside the deleted one, the thing resurrect-on-register avoids).
- **Adoption keeps operator-owned fields.** `description`, group, sort priority
  and UI-edited URLs are untouched; only `source` flips, and the usual register
  merge then applies.
- **Lock hides nothing by itself.** Templates used `is_static` for both "locked"
  and "no Docker pill". The Docker pill/drawer row/stale icon now key off
  `is_manual`; the lock icon and "no trash button" still key off `is_static`.
  A locked notifier entry therefore shows its Docker status again (it is not
  stale, by `is_docker_status_stale`).
- **Add form field renamed `application` to `container_name`,** matching the
  Edit form. Hand-written POSTs to `/add` using the old name will get "Name is
  required".
- **Edit page host rules.** Blank Host saves as NULL for manual entries only; a
  notifier entry keeps the old behaviour (empty string) so its logical key
  is not silently changed. Description is saved from the Edit form for manual
  entries only.
- **Restore skips hostless non-manual records** (the logical key needs a host)
  and counts them as skipped. Restore ignores a backup's `source` value if it is
  not `notifier` or `manual` and falls back to the backfill rule.
- **Lock hint wording** is one line, "register calls from the notifier for this
  entry are ignored", and the Add page checkbox uses the same label.
- **Migration test runs alembic in a subprocess** against a temp copy of
  `alembic.ini`, so `fileConfig()` cannot reconfigure logging in the pytest
  process.

---

## 2026-11-15 — v0.7.0 "Dashboard and Monitoring" design calls

Scoped in a design session; plan in PRD §13, follow-ups in FUTURE.md.

- **No notifier change.** The user directed that the notifier keep
  sending today's payload. Every 0.7.0 feature is STD-side; the URL-check
  toggles in the payload map onto the new check rows.
- **Manual vs notifier is a `source` column, not `is_static`.**
  `is_static` was doing two jobs (lock and "not Docker"). It is now only
  the lock. A register matching an unlocked manual entry *adopts* it,
  which keeps the existing "pre-stage, then the notifier fills it in"
  behaviour instead of creating a duplicate. Rejected: a separate
  "adopt" button; matching manual rows never.
- **Manual entries keep an optional host** (user call). The name is
  stored in `container_name` rather than a new column, so the logical
  key, its index and every query stay as they are.
- **Checks are rows, not columns.** URL checks are `health_check` rows
  whose target follows the entry URL. Service checks are separate rows.
  This gives one engine and one history table for every kind. Rejected:
  more columns on `service_entry`.
- **Retention: raw 24 h, then hourly success ranges, failures kept
  7 days** (the user's proposal, bounded per clock hour so 7-day hourly
  bars and uptime % stay exact). Rejected: unbounded success ranges
  (they force proportional splitting everywhere) and keeping all samples
  for 7 days (about 10k rows per check at a 60 s interval).
- **History bars are fixed time buckets** (48 × 30 min for 24 h), not
  Gatus's "last N results" (user call). This keeps the strip's meaning
  stable whatever the interval.
- **Worker threads never touch the DB.** The scheduler thread writes
  everything, because SQLite has a single writer and Flask-SQLAlchemy
  sessions are not shared across threads.
- **Ping uses `icmplib`, not the `ping` binary.** There is no subprocess
  or extra apt package, and the image runs as root with Docker's default
  `NET_RAW`. It falls back to an unprivileged socket and then reports
  "ICMP not permitted".
- **Legacy health columns are deprecated, not dropped,** in 0.7.0 so a
  rollback to 0.6.9 keeps working. A temporary mirror keeps the old
  badges correct between chunks 03 and 05.
- **New health timestamps are naive UTC**, unlike the naive-local
  `last_updated`. Converted for display.
- **Compact gets no drawer;** its badge links to the Edit page's health
  section instead of adding a third detail surface.

---

## 2026-11-15 — release-prep-and-cut label corrected upstream, then re-synced

The `@ v1.0.0` labels flagged in the two entries below were fixed at the
source (`homelab-configs/standards/release-prep-and-cut`: snippet, both
command templates, README adoption step and example prompt now say
`v1.1.0`). STD's verbatim copies (CLAUDE.md snippet source line,
`.claude/commands/release-prep.md` and `release-cut.md` headers) were then
re-synced to match. Label only; the command content was already 1.1.0.

---

## 2026-11-15 — CodeQL path and redirect fixes (v069-11)

- **Invalid icon on Add/Edit flashes, but those templates don't render
  flashes** (only `settings.html` does). The message is queued and shows on
  the next Settings view; nothing is written either way. Adding flash display
  to the Add/Edit pages was out of scope.
- **Edit with a bad icon keeps the stored icon** and still saves the other
  fields, mirroring the invalid-timeout handling.
- **Add page's `ref` handling removed**: it was computed and never used.
- **`fetch_icon_if_missing` also validates** (it is the path used for
  derived names from container/image names), so a container name that does
  not fit the icon charset simply gets no auto-fetched icon.
- **Widget list is `widgets/` under the app root**, not `/app/widgets`; same
  directory in the container (`WORKDIR /app`). The edit page still lists
  `/app/widgets` (not part of the alerts); left alone.

---

## 2026-11-15 — Docs loose ends (v069-10)

- **Series headers keep the `[0.x.x] series` form**: the What's New regex needs
  `\d+.\d+.\d+`, so they never match. Side effect: the `[0.4.0]` section body
  runs to EOF and swallows the 0.3.x/0.2.x/0.1.x series text in the popup.
  Left as is (cosmetic, only seen when upgrading from <0.4.0); not worth a
  parser change.

---

## 2026-11-15 — gunicorn and pins (v069-09)

- **Startup via `post_worker_init`, not `preload_app`**: threads started in
  the master don't survive the fork. `run_startup_tasks()` is guarded by a
  module flag so it is a no-op if called twice in one process.
- **`gunicorn.conf.py` timeout = 60 s** (default 30) so slow register/icon
  fetches aren't killed; a worker kill would restart the scheduler.
- **Pins resolved for Python 3.11 only**, no platform markers: publish.yml
  builds linux/amd64 only. CI `Test`/`Migration check` install the pinned set
  unchanged; `requirements-dev.txt` stays `-r requirements.txt` + pytest.
- **Docker verification note**: this host's default log driver is `loki`,
  which swallows `docker logs`; verify with `--log-driver json-file`.

---

## 2026-11-15 — Health-check options (v069-08)

- **Invalid timeout on edit keeps the stored value** (flash warning, rest of the
  form still saves), mirroring how sort priority is handled there. On Add an
  invalid value re-renders the form.
- **Restore sets the options explicitly** (defaults when absent) rather than
  leaving an existing row's values, so a v0.6.8 backup restores to the
  documented defaults.
- **`verify` treats only an explicit `False` as off** in `check_url`, so a
  missing attribute fails safe to verifying.

---

## 2026-11-15 — Staleness indicator (v069-07)

- **Never-updated dynamic entries:** model still returns stale (unchanged);
  the new Dashboard/Compact icon is shown only when `last_api_update` is set,
  because Tiled already renders that case as a distinct red "no update
  received" and Dashboard as a red pill. Avoids double-flagging.
- **Threshold read** via `has_app_context()`/`current_app.config`, default 5
  on missing, invalid, or negative values.
- **Tooltip wording** unified as "stale — updated <time_since>".

## 2026-11-15 — Widget detach and refresh filter (v069-06)

- **Refresh filter:** `Widget.services.any(deleted_at IS NULL)`, i.e. only
  widgets with an active service refresh. A widget referenced only by
  soft-deleted entries stays skipped (as in v069-05): a restorable entry is
  hidden and unchecked, so polling its upstream is wasted work; Restore
  resumes it. Detached widgets are skipped by the same rule. Side effect:
  legacy widget rows with no services (previously refreshed) are now skipped
  too; they show up under Detached widgets.
- **`hard_delete_entry`** only deletes the entry; widget and values are kept.
  Retention pruning of `widget_value` is unchanged.
- **Edit page not changed:** it updates the attached widget in place and only
  creates a new row when the entry had none (or a dangling id), so it never
  orphans a widget. Selecting "none" deletes the widget and values outright,
  even if another entry shares it (pre-existing; widgets are not shared in
  normal use) -- left as is, noted for the operator.

## 2026-11-15 — Soft-delete call-site decisions (v069-05)

`ServiceEntry.active()` is the filter for anything user-facing; the choices
that weren't obvious:

- **Deliberately all rows:** the register lookup (needs deleted rows to
  resurrect; orders active before deleted), backups (scheduled and manual, so
  `deleted_at` round-trips), both restore lookups, `recompute_all` (keeps
  deleted rows' synthesized URLs fresh for a later restore), the add-entry
  duplicate check (a deleted twin gets a "restore it instead" message),
  `/dbdump` (raw-table view: shows deleted rows marked and struck through
  rather than adding a filter), and `hard_delete_entry`'s "other services use
  this widget" count (a soft-deleted entry still holds its widget).
- **Static-locked deleted entry:** register skips it before resurrecting, so a
  locked entry stays deleted until restored by hand.
- **Widget refresh:** (superseded by v069-06 below) filters widgets (it queries `Widget`, not entries) to
  those with no services or at least one active service.
- **Group delete:** only active entries block it; the group's soft-deleted
  entries get `group_id = NULL` so none dangle.
- **`hard_delete_entry`** lives at the bottom of `models.py` (shared by
  `routes_dashboard.py` and `jobs.py`; caller commits). The old inline
  widget-if-unused code moved there unchanged so v069-06 edits one function.
- Retention comparison uses naive local `datetime.now()`, matching
  `last_updated`; `0` days purges everything soft-deleted at the next run.

---

## 2026-11-15 — CSRF: JSON detection and general-suite opt-out

The `CSRFError` handler answers JSON (400) when `request.is_json`, the path
is under `/api/`, an `X-CSRFToken` header is present, or `Accept` asks for
JSON; otherwise flash + redirect to the referrer (dashboard fallback). The
header check covers `stdPost` fetches that carry no body/Accept (the delete
calls). Tests set `WTF_CSRF_ENABLED=False` on the shared app in `conftest.py`;
`tests/test_csrf.py` flips it on per test via a fixture.

---

## 2026-11-15 — Default-credential check cached, dismissal is per-session

The `changeme123` check hashes a password, so it runs once at startup (and
again from `routes_auth.set_user_password` / `reset_user_password`) and is
cached on `app.config`, not computed per request. `create_default_admin` also
refreshes it because the admin row is created after `create_app()`. The Settings
notice is dismissed client-side via `sessionStorage` (reappears next session),
so dismissal needs no DB state. `FLASK_SECRET_KEY` set-but-empty is treated as
unset. The "reset password" admin action sets `changeme123`, so it re-raises the
warning by design.

---

## 2026-11-15 — Lint widened to E, W, F, I, B

`ruff.toml` now selects `E, W, F, I, B` with `E501` ignored (line length is
churn). Initial run: 30 findings (I001 x20, E402 x4, B009 x2, B010 x2, W291 x2);
none was a real bug, so no CHANGELOG entry. B009/B010 were constant-name
`getattr`/`setattr`, rewritten as plain attribute access (identical behavior).
`per-file-ignores`: `alembic/versions/*.py` skips `I001`/`W291` (applied
migrations are history; sorting them is pure churn, and the one W291 is inside
a docstring); `alembic/env.py` skips `E402` (it must edit `sys.path` before
importing app modules). No file-wide or rule-wide ignores otherwise.

---

## 2026-11-15 — Test seam: `STD_CONFIG_DIR`, env set in conftest

`app.py` builds the app at import and reads `/config` paths there, so
`STD_CONFIG_DIR` (default `/config`) is resolved once in
`settings_loader.CONFIG_DIR` and everything derives from it. `tests/conftest.py`
sets the env and a temp dir at import time, before `app` is imported, instead of
restructuring the factory. Kept as a dev/test knob (README Development only, no
CHANGELOG entry). Tests stub `routes_api.resolve_image_metadata` to avoid icon
downloads, and the loader tests monkeypatch `CONFIG_PATH`. `alembic.ini` and the
`Migration check` job still use `/config` and are untouched.

---

## 2026-11-15 — v0.6.9 scope: one large patch, and its design calls

Review of v0.6.8 found two bugs, a security pass, a missing test suite,
and the delete-safety-net features. Recommended split was 0.6.9
(hardening) + 0.7.0 (safety net); **the operator chose to ship both as
one 0.6.9.** Plan in PRD §12, one prompt per subsection.

- **Patch, not minor.** Side effect: `/release-prep` won't run the
  per-minor CHANGELOG archive step this time. The `2026-XX-XX` dates
  that would have broken it are fixed anyway (§12.10) — git tags show
  the real dates, and they're 2025, not 2026.
- **Unset `API_TOKEN` → register returns 503**, UI keeps working.
  Rejected: refusing to start (breaks UI-only installs).
- **Soft-delete *and* widget detach** (operator choice). Soft-delete is
  the recovery window; detach applies only at the eventual hard delete.
- **Register resurrects a soft-deleted row** rather than leaving it
  hidden or creating a fresh duplicate. A hard-deleted running container
  already reappears on its next register today; resurrecting keeps the
  curated state, which is the point of the feature.
- **Single staleness threshold, default 5 min** (the model's current
  value; the template's 120-min clause is redundant under OR). Notifier
  re-scans every 60 s by default.
- **CSRF tokens have no time limit** (`WTF_CSRF_TIME_LIMIT=None`) —
  long-open dashboards otherwise 400 on the next POST.
- **gunicorn with exactly one worker.** The register mutex, scheduler,
  and health thread are in-process; multiple workers would duplicate
  jobs and break the upsert lock.
- **Testability via `STD_CONFIG_DIR`** (default `/config`) rather than
  monkeypatching module constants; tests use `create_all()`, Alembic
  stays covered by `Migration check`.
- **Not in 0.6.9:** concurrent health checks, per-source API tokens,
  `repo-sandbox-permissions` adoption (offered, not chosen). The stale
  `release-prep-and-cut @ v1.0.0` text is upstream in `homelab-configs`.

---

## 2026-11-15 — CLAUDE.md consolidation after the standards adoption

- **Removed** "Git Workflow" and "Git Rules" (fully covered by the
  `code-checkin-and-pr` snippet) and the four standard prefixes in "Commit
  style" (kept only the `refactor:` extension and the release-prep message).
  **Merged** "Git Workflow" (required checks, CI trigger, `Test` exemption) and
  "Release Process" (GHCR, tags, `VERSION`, `/release-prep` -> `/release-cut`)
  into one "CI, Registry, and Releases" section: project-specific facts only,
  one place per fact.
- **Always item 1 narrowed** from "every change" to "every operator-visible
  change", matching the existing rule that tooling-only changes go in
  HISTORY/decisions, not CHANGELOG.
- **Snippets left untouched**, including the stale `release-prep-and-cut @ v1.0.0`
  source comment (pin in `standards.md` is 1.1.0); snippets are read-only.
- CLAUDE.md said unknown register keys return HTTP 422; the code and PRD say
  400. Corrected to 400.

---

## 2026-11-15 — Adopting release-prep-and-cut: VERSION file, no APP_VERSION, tag guard

- **`VERSION` is the single source of the in-app version.** The Dockerfile
  derives `version=` in `/app/version.txt` from the copied `VERSION` file
  (`tr -d '[:space:]'`). Previously `APP_VERSION` came from the
  metadata-action output, which is `dev`/`latest`/`pr-N` off release events,
  so `:dev`/`:latest` reported a non-semver and the What's New popup
  (keys on the version) misbehaved.
- **`APP_VERSION` build arg removed outright, not kept as an override.** An
  override would let a build disagree with `VERSION`, recreating the drift
  this fixes; nothing needs it (local builds also read `VERSION`).
- **`publish.yml` guard:** on `release` events a step before the builds fails
  if the tag minus leading `v` != `VERSION` — cheap protection against
  tagging the wrong commit. Only the version build-args and this step were
  touched; Docker Hub steps and `REGISTRY_NOTICE` left for the other prompt.
- **`app.py` fallback** (no `/app/version.txt`, e.g. `python app.py`) reads
  `VERSION` beside `app.py`, else `"unknown"`.
- **`<LOCAL_CHECKS>` reuse `ci.yml`.** Config validation extracts and runs
  the `config-validate` step's script from `ci.yml` via PyYAML, so the file
  lists can't drift. Lint is `uvx ruff@0.15.17 check .`. Migration check uses
  a temp copy of `alembic.ini` (URL and `%(here)s` script_location rewritten)
  and `uv run --python 3.11 --with-requirements requirements.txt alembic` (no global alembic on the dev box), never a real `/config` (contrast with CI, which
  creates a runner-local `/config`).
- **Tooling stays out of CHANGELOG** (per the vexp entry); only the
  operator-visible "images report the real version" effect was logged.
- The bare `0.6.5` tag remains an un-fixable historical deviation.

---

## 2026-11-15 — Adopting code-checkin-and-pr: migration-check DB, retention scope, F821

- **Migration check uses a runner-local `/config`** (`sudo mkdir -p /config &&
  sudo chown $USER /config`) rather than an env-var override in
  `alembic/env.py`. `alembic.ini` hardcodes `sqlite:////config/services.db`;
  creating the dir keeps the check running against the unmodified production
  config and avoids a code change. Rejected: env override (runtime-adjacent
  change for a CI-only need).
- **Untagged GHCR versions are never pruned.** `publish.yml` uses
  `build-push-action` with default provenance, so per-platform/attestation
  manifests exist as untagged versions referenced by tagged indexes. Telling
  referenced from orphaned is not worth the risk; accepted cost is some
  untagged residue after tagged versions are pruned.
- **F821 in `routes_dashboard.py` `/add` was a real bug.** A non-numeric sort
  priority raised `NameError` (`groups` undefined) -> HTTP 500. Fixed by
  loading `groups` at the top of the POST branch and passing it to all three
  error re-renders (the other two silently rendered an empty group dropdown).
  Operator-visible, so it has a CHANGELOG `### Fixed` entry.
- **CI is push-only** (no `pull_request` trigger) to avoid duplicate
  same-named check runs that leave required checks stuck "Expected".
- Test check exempt (no suite); recorded in `standards.md`.

---

## 2026-11-15 — vexp removal recorded in HISTORY, not CHANGELOG

CLAUDE.md requires a CHANGELOG entry for every change, but CHANGELOG is
operator-facing and is rendered in the in-app "What's new" popup. The vexp
removal is developer tooling with no operator-visible effect, so it was
recorded in `docs/HISTORY.md` instead. Same reasoning applies to future
tooling-only changes (agent guidance, `.claude/` config).

## 2026-11-15 — Docker Hub → GHCR via a banner-only final Docker Hub release

v0.6.7 was published to both registries from one workflow, with the
in-app "moved to GHCR" banner gated on a `REGISTRY_NOTICE=dockerhub`
build arg so only the Docker Hub image shows it. Rejected: a Docker
Hub-only final release (GHCR would have had nothing to switch to) and
an unconditional banner (users who had already moved would keep seeing
it). Driver: GHCR retention runs on `GITHUB_TOKEN`; Docker Hub retention
would need a delete-scoped token and a custom cleanup job. Docker Hub
publishing, the build arg, and the banner are removed in the next
release; Docker Hub tags stay frozen on the v0.6.7 banner build.

## 2026-11-15 — The `0.6.5` tag stays un-prefixed

v0.6.5 was tagged `0.6.5` (no `v`), unlike every other release. It is
left as-is: re-tagging a published release is never done (moving a tag
under consumers breaks pins and image provenance). CHANGELOG's link
reference already points at `releases/tag/0.6.5`. All new tags use the
`vX.Y.Z` form.
