# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-21 — Ports in use page (GitHub #58)

- **Stopped containers are excluded.** Docker clears `NetworkSettings.Ports` on stop, so a
  stopped container reports no published ports; its `exposed_ports` (image config) survive, and
  listing them would show a stopped service as using ports. Excluded: an entry whose
  `docker_status` is set and not running. `start` counts as running, as it does on the dashboards
  (`dashboard.html` treats `start` and `running` alike); a NULL status (older notifier, manual) is
  included. Remembering last-known ports is parked in FUTURE.md.
- **Any wildcard address overlaps everything.** `""`, `0.0.0.0` and `::` conflict with any other
  address on the same host, protocol and port, without a per-family check. A `0.0.0.0` vs `::`
  split across two entries would strictly not clash on some stacks; it is rare, and a false
  positive is cheaper than a missed clash. Two different specific IPs never conflict.
- **`0.0.0.0` and `::` collapse into one row.** Docker publishes both for a plain `-p 8080:80`;
  to the operator it is one binding. One entry's bindings sharing (host port, container port,
  protocol) become one row with all its `host_ips`.
- **The conflict count is the number of conflicting rows** (both sides of a clash count, so one
  clash of two entries is 2), computed over all ports, not the filtered ones. The page and
  `GET /api/v1/ports` use the same `ports.summarize`, so the summary bar and the API summary match
  and the count stays visible while filtering (its link applies `conflicts=true`).
- **Display name is `container_name`**, which is what all three dashboard views show; rows link to
  `/edit/<id>`, the dashboards' edit target (they have no entry detail page).
- **An exposed-only row** is an exposed `port/proto` with no published binding of the same
  container port and protocol on that entry. Exposed rows never conflict.

---

## 2026-11-21 — Image update over MQTT and Home Assistant (img-04)

- **Sync trigger: add the computed columns to `notify_state._ENTRY_ATTRS`** (`image_ref`,
  `image_update_policy`, `image_update_state`, `image_update_latest`, `image_update_kind`) instead of
  calling `request_sync` from the job. `image_update._set` writes only a changed value, so the
  commit listener fires only on a real change, and the 2 s debounce collapses any burst into one
  sync: no double sync, and the job (which already commits) never touches the publisher.
- **Toggle:** `image_update.on_settings_changed` requests a forced sync when the effective switch
  flips (both the UI and the API call it).
- **Switch off withdraws the hub "Updates available" sensor** as well as the entities (consistent,
  and an operator who never enables the check sees no new entity). `summary.updates` stays in the
  topic, as 0; the key is additive and always present.
- **`pinned` shows `@<7 hex>` on both sides**, not null: nothing is meant to update, so HA shows an
  up-to-date entity instead of "unknown". `unknown` and `error` stay null.
- **The image topic follows every active entry with a shown state, not only `ha_publish` ones**,
  matching the other entry topics; `ha_publish` gates only the discovery entity.
- **Entity existence = image topic existence** (effective state not `off`/none, `ha_publish`), so
  the entity never points at a topic that is not there.
- **Purge:** the image topic is cleared by the entry/stream purge only when it is remembered as
  published, so purge counts for installs with the check off are unchanged; the `update` config is
  cleared through the remembered `ha_topics` like the other entry configs. The orphan scan
  recognises `entry/<id>/image` as an STD topic shape.
- **`checked_at` can lag:** it is in the payload but not a sync trigger (a sync per daily run for
  every entry would publish when nothing meaningful changed); it refreshes on the next publish.
- Existing test `test_first_result_publishes_check_entry_and_summary` now expects `updates: 0`
  in the summary (additive key).

---

## 2026-11-21 — Image update UI (img-03)

- **Check now is a fetch POST with a toast, not a form redirect.** The three dashboard views
  render no flash messages (only Settings and Add/Edit do), so a redirect would lose the
  throttle message. `static/js/image_update.js` (delegated, so it also works in the
  fetched Compact dialog) posts with the meta CSRF token and builds a toast. The routes
  answer JSON: 202, 409 (off or nothing to check), 429 with `Retry-After`.
- **The `?updates=true` filter is ignored while the check is off**, as well as the toggle
  being hidden. The stored `image_update_state` outlives the switch (img-02), so honouring
  a bookmarked `?updates=true` would filter on stale answers. The predicate itself stays a
  plain test on the stored column; the route drops it when off.
- **The view tabs carry only `?updates=true`**, not the status/source/group filters (those
  have never followed the tabs). Widening that to every filter is a separate change.
- **No live "matches" preview.** The page shows what matched at the last check (the saved
  pattern's stored pool, or the newer tags of the running shape) and says a changed pattern
  applies at the next check. A preview of unsaved text would need the registry.
- **Edit block only saves when `image_update_form` is posted**, so a client posting the
  older edit form never resets policy, scope or pattern. Validation runs before any field is
  changed, like the image repo URL.
- **The badge tooltip is built in Python (`image_update_ui`)**, not the template, so the
  tag and digest wording lives once and is the `aria-label` too.
- **Rendering N+1:** the view query `selectinload`s `ServiceEntry.image_reference`
  (the digest tooltip and the details read its times), and the enabled flag is cached in `g`.
  `test_view_query_count_stays_flat` guards all three views.
- **The Settings page needs no new settings helper:** save goes through `image_update.save_settings`
  and `on_settings_changed`, as the API does; with the env var set the submitted switch is
  ignored and the control renders disabled with the env lock text.

---

## 2026-11-21 — Image update check engine (img-02)

- **Where the columns live.** Observed (`image_running_digest`, `image_info`), operator
  (`image_update_policy`, `image_tag_pattern`, `image_update_scope`) and computed
  (`image_update_*`) columns are on `service_entry`, per design 6.2; `image_reference`
  holds only the remote facts per canonical reference (design 6.1). The two are joined
  by `image_ref = ref` with a read-only ORM relationship that carries no database FK.
  `image_reference.ref` is `String(512)` (matches `service_entry.image_ref`; the design said 400).
  The ORM attribute for the `registry` column is `registry_name` (`registry` is reserved
  on a declarative class).
- **Extra computed column `image_update_detail` (JSON: reason, model, rebuilt).** Not in
  the design's list. Without it "unknown, with a reason" and the muted "rebuilt" note could
  only be derived per read by re-running the model for every entry in every list; stored,
  the serializer and the UI read one column. Same transaction as the state, so they
  cannot disagree.
- **Switched off means shown as `off`, stored results kept.** `effective_state()` overlays
  `off` while the check is disabled; the stored columns are not rewritten, so turning it
  back on shows the last answers at once. The register recompute and local recomputes
  therefore run whether or not the check is on (no network). `img-03` must apply the same
  overlay to the `?updates=1` filter (the stored `image_update_state` is not enough on
  its own) and to badges.
- **Retention skips while the check is off.** `last_wanted_at` is only refreshed by a run,
  so pruning at 30 days while the check is off would delete the stored results the design
  promises to keep. Pruning resumes after it is turned on.
- **Candidates are stored with a per-pattern pool.** The design stores up to 50 newer tags
  of the running skeleton, but a per-entry pattern *replaces* the skeleton rule, so its
  candidates may lie outside that set. The run therefore also stores up to 50 per distinct
  pattern in use (`candidates.patterns[<regex>]`). A scope change recomputes locally. A
  pattern that has no stored pool yet (just saved) shows `unknown` "applies at the next
  check" until a run; a live "matches" preview for an unsaved pattern is not possible from
  stored data alone.
- **Nested-quantifier rule.** A repeat that can run more than once (`+`, `*`, `{n,}`,
  `{n,m}` with m > 1) containing a repeat of variable length is rejected, found by walking
  `re._parser`'s tree (a regex heuristic is the fallback where that module is missing).
  `(\d{2})+` and `(-alpine)?` pass; `(\d+\.)+` does not. Tags over 128 characters are
  never evaluated, which bounds the cost of anything that slips through.
- **A failed HEAD does not fail a tag-model reference.** For the tag model the HEAD only
  feeds the muted "rebuilt" note, so a 404 or timeout there leaves the tag result intact;
  for the digest model it is the whole check and fails the reference.
- **What a run requests.** Digest model with no running digest, pinned references and
  policy `off` make no request (their state is `unknown`/`pinned`/`off` without one). A
  tag-model reference is HEAD-ed too only when some entry on it reports a running digest.
- **Backoff slack.** A reference is skipped when `next_check_at` is more than one hour in
  the future. With the job's 30-minute jitter a 1-day backoff would otherwise skip the next
  daily run (24 h later minus jitter) and make it 2 days. So "skipped for 1, 2, 4 days"
  means the retries happen 1, 2, 4 days after the failure.
- **Manual and nudge runs are one-shot jobs** (`DateTrigger`, id `image_update_run_job`),
  not `modify_job(next_run_time=now)` as the design sketched: the daily interval job keeps
  its own cadence. Pending requests (everything / never-checked / specific references) live
  in memory behind `_STATE_LOCK` and are drained by whichever run starts next, so a request
  that arrives during a run is served by a follow-up run. Throttle clocks are in memory
  too: a restart clears them (politeness limit, not a security control).
- **`image_update_last_run` is saved for full and nudge runs**, not for single-reference
  Check now, so an entry check never moves the "24 h after the last run" start.
- **Digest `latest` is stored as `sha256:<12 hex>`**; `img-04` builds `<tag>@<7 hex>` from it.
- **`image_info.source`** is length-limited by the schema but only an http(s) value is
  stored (a git@ URL is dropped, not a 400: a weird OCI label must not fail a register).
  `id`, `created`, `version`, `revision` are length-limited only; only `repo_digests` items
  have a strict pattern (the design). `repo_digests` is reduced to the running digest and
  not stored.
- **Register 400s no longer carry validator `ctx`.** A `field_validator` error puts the
  raised `ValueError` in `errors()[i]["ctx"]`, which is not JSON; the handler now calls
  `errors(include_context=False)`. (The first validator on the register schema exposed it.)
- **Check now with the check off is a 409**, not a quiet no-op; a throttled one is a 429
  with `Retry-After` and `details.retry_after_seconds`.
- **PRD section is new §24**, appended, so §21 to §23 and their many cross-references keep
  their numbers.

---

## 2026-11-21 — Image reference parser (img-01)

- **Legacy columns map from the parse like this:** `image_name` = last path component,
  `image_owner` = everything before it (`org/team` for `ghcr.io/org/team/app`),
  `image_registry` = the registry host[:port]. Docker Hub keeps the old shape: registry
  stays NULL (not `docker.io`) and the implicit `library` owner is NULL, so existing
  entries, `image_repo.py` and the display don't change meaning; the canonical string
  lives in the new `image_ref`. Rejected: storing `docker.io` / `library` in the legacy
  columns (rewrites every existing Hub row's meaning for no gain).
- **`image_tag` now defaults to `latest`** when the reference has neither tag nor digest
  (it was NULL), matching the canonical string; a digest-only reference leaves it NULL.
- **`image_ref` is `String(512)` and indexed.** The prompt said 512 and no index unless
  design section 6 asks; the design asks for an index (the check groups entries by
  reference) and says 400. 512 wins on length (a superset); the index follows the design.
- **Register overwrites `image_ref` only when it carries `image_name`**, like the other
  `image_*` fields, so an absent field never clobbers it; an invalid string sets NULL.
- **Not exported or imported**: it is observed (design 6.2), like the other `image_*` columns.
- **Backfill reimplements the rules inside the migration** (migrations stay independent of
  app code) and skips rows the old parser mangled (owner that is a host, tag with a `/`,
  name with `@`); the next register fixes those.
- **Nested GHCR links:** `ghcr.io/org/team/app` is the package `team/app` under `org`, so
  the package segment is percent-encoded (`team%2Fapp`). Docker Hub nested namespaces and
  registries with a port get no link.
- **The conftest `fake_resolve` is left as is;** register reads `image_ref` with `.get`.

---

## 2026-11-21 — Image repo link (GitHub #6)

- **GHCR uses `github.com/users/<owner>/packages/container/package/<name>`.** Checked
  against github.com: the `/users/` form redirects to the right package page for both a
  user (`crzykidd/service-tracker-dashboard`) and an organisation (`home-assistant`,
  which lands on `home-assistant/core`), and `/orgs/` gives the same result. The
  `<owner>/<name>/pkgs/container/<name>` form is wrong whenever the repo name differs
  from the package name.
- **Only four registries are derived** (Docker Hub, `ghcr.io`, `quay.io`, `lscr.io` for
  `linuxserver`). `gcr.io`, `mcr.microsoft.com` and `registry.gitlab.com` have no stable,
  browsable page URL from `owner/name` alone (GitLab nests groups), and private registries
  must never be guessed; those entries get no link unless the operator sets the override.
  A two-part reference whose "owner" looks like a host (`ghcr.io/app`, `localhost:5000/app`;
  the notifier-side parser files it as owner/name) is treated as unknown, not as a Hub user.
- **The container name is not linked.** It already opens the entry's URL on every view and
  is not in the shared facts partial; the image string carries the link. An entry with an
  override but no Docker image gets a "Repo" row instead.
- **The override is operator-owned for every kind** in export/import (unlike `image_icon`,
  which register rewrites on an unlocked Docker entry), because register never writes it.
  It is left out of the legacy `ServiceEntry.to_dict()` list on purpose; that format is only
  read for old files.
- **`API_REVISION` 5**, labelled "next after 0.11.0" until `/release-prep` assigns the
  version. The MCP `update_entry` field list gained `image_repo_url`.

---

## 2026-11-21 — CodeQL findings on the 0.11.0 pull request

CodeQL raised 15 alerts on PR #82. Fixed: an unexpected exception during import apply no
longer puts its text in the `ImportApplyError` message (it reached API clients and the UI;
it is logged instead); `importer._staging_path` and `restore_staging._path` resolve the
path and refuse anything outside their folder, on top of the existing token regex (CodeQL
does not see the regex as a sanitizer, and the containment check is a real second guard);
the Set password dialog only accepts a same-site path as its form action. Dismissed as
false positives: unsafe deserialization (the loader is a `yaml.SafeLoader` subclass that
also refuses aliases), clear-text password logging (the line logs import counts only), and
stack-trace exposure in `json_error` where the remaining sources are our own messages.

---

## 2026-11-21 — Code fixes from the README audit

- **The UI delete route moved to `/entries/<id>/delete`** instead of staying under
  `/api/v1`, where it looked like a management API route but used a session login. No
  alias for the old path: the only callers were our own templates and JS, and the old
  path now gets the normal JSON 404 for unmatched `/api/v1/*`.
- **`settings.yml` values are cast with the same table as env values** (`cast_value`).
  A file value that fails to cast is kept raw with a warning (today's file behavior),
  not replaced by the default; env handling is unchanged. Bool parsing is explicit
  because `bool("false")` is True, though no bool keys exist yet.
- **The widget reload fallback reads one constant** (`WIDGET_BACKGROUND_RELOAD_DEFAULT`,
  900) instead of a hard-coded 300. The dead `STD_DOZZLE_URL` line in `app.py` is gone;
  `load_settings` plus `app.config.update(settings)` already cover env and file.

---

## 2026-11-21 — Compact view details open in a dialog, loaded on demand

The Compact grid flows by column (10 rows), so an inline drawer would reshuffle every
tile after it; the expand button opens one shared `<dialog>` instead. Its body comes from
`GET /service/<id>/details` (session login, HTML fragment) when it opens, so the page
doesn't render facts for every tile. It is a browser route, not `/api/v1`, so no
`API_REVISION` bump. Delete closes the dialog first and anchors the shared delete popover
on the tile's chevron, because the popover would otherwise sit under the modal. The
delete URL comes from `url_for`, so the route move to `/entries/<id>/delete` (same day)
can't break it.

---

## 2026-11-21 — Dashboard expand row reuses the tile drawer's facts

The Dashboard expand row showed only the health detail, while the tile drawer showed host,
URLs, Docker, stream, networks, ports, exposure and widgets. The drawer's info rows moved
into `partials/entry_facts.html`, included by both views (no wrapper, so the drawer's
output is unchanged), rather than duplicating the markup. In the expand row the health
panel renders with `hide_facts=true`, because the facts column already carries IP, MAC
and network. A two-column label/value grid inside the facts column was considered and
not used: for typical entries the facts are no taller than the health panel.

---

## 2026-11-21 — README revamp: deep reference moves to docs/ pages

Calls made while rewriting the README (`prompts/2026-11-21-readme-revamp.md`). Docs only.

- **Three reference pages under `docs/`, the README keeps an overview of each.** The
  full register contract (payload, ownership, capture, exposure, provenance, wire
  semantics, labels) is `docs/register-api.md`; the full stream guide (UI steps, view
  markers, API semantics, limits) is `docs/inventory-streams.md`; channels, topic
  payloads, every Home Assistant entity, purge and broker clean-up are
  `docs/mqtt-home-assistant.md`. The text moved mostly as written and was corrected
  where it was stale. Rejected: one `docs/reference.md` (too long to navigate) and
  leaving it all in the README (1,700 lines, operator setup buried under reference).
  The README sections link to them, and the pages link back.
- **The management API endpoint table stays in the README.** It is the reference most
  operators and agents look for, and it matches the code route for route (checked
  against `routes_mgmt_api.py`).
- **What's New headings keep the `v` prefix** (`### v0.10.1 (2026-11-20)`): they name a
  release, which is the one place the release standard allows it, and `/release-prep`
  step 4 writes exactly that heading. Each block links to its CHANGELOG entry by GitHub
  anchor (`#0101--2026-11-20`); all anchors were checked. The 0.11.0 block is headed
  "unreleased, on `dev`" and links `#unreleased`, with an HTML comment telling
  `/release-prep` to replace the heading and the link rather than add a second block.
- **The UI route table is gone.** It listed about a third of the routes and was the
  most stale part. The README now lists the Settings sections (from
  `settings_sections.py`) and the stable pages; the UI's own POST/JSON routes are
  described as internal (login + CSRF, not a stable interface).
- **Proposed screenshots are real image references** (`std_streams.png`,
  `std_import_preview.png`, `std_home_assistant.png`, `std_health_detail.png`) with a
  `<!-- screenshot needed: ... -->` comment each, so the operator only drops files in.
  They show as broken images until then.
- **`TZ` is documented** although STD does not read it: the image has tzdata, and the
  daily job times are container local time (checked: `TZ=America/Chicago` gives CST in
  the `:dev` image).
- **`settings.example.yml` comment fixes only** (the widget reload default said 300,
  the code and value say 900; "static entries" became manual, locked and stream
  entries). No key or value changed; it still parses and loads every key.

## 2026-11-20 — Backup, export and import, bak-05 (staged restore)

Calls made while building phase 5 (`prompts/2026-11-20-bak-05-staged-restore.md`), with the
operator asleep. The operator chose to build this phase (design Q4).

- **Immutable read-only opens.** `validate`, `stage` and the swap's integrity check open the
  snapshot with `file:...?mode=ro&immutable=1`. A plain `mode=ro` open of a WAL-mode file
  creates `-wal` / `-shm` files beside it (a snapshot is a backup of a WAL database, so its
  header says WAL), which litters the backup folder and fails on a read-only folder.
  `immutable=1` skips locking and sidecars, which is right for a file nothing writes.
- **The swap moves the old files aside instead of deleting them first.** `services.db`,
  `-wal` and `-shm` are renamed to `*.restore-old`, the staged file is `os.replace`d in, and
  the aside files are deleted only after that succeeds. A failure puts them back, so "put
  back the current database" is a rename and cannot itself fail halfway. The design said
  "remove" the three files; the end state is the same.
- **An unreadable current database does not block the restore.** The restore is often the
  fix for a damaged database, so if `Connection.backup()` of the current file fails the swap
  keeps the raw file as `pre-restore-<ts>-unreadable.sqlite3` and goes on. A *good* current
  database is always kept through `backup()`.
- **Confirmation is the Backup section re-rendered, not a modal.** The stage route validates
  and renders Settings with `restore_confirm` (the found metadata and a danger-confirm
  form); nothing is staged until `/settings/restore/confirm`. A server file is re-resolved
  and re-validated on confirm (never trusted from the form); an upload is kept as
  `restore/upload-<token>.sqlite3` between the two requests (the token must match a strict
  pattern) and deleted after staging or on a validation failure.
- **`pre-restore-*.sqlite3` count as snapshots in the list** (tag "pre-restore", Download,
  Delete, Restore...) but retention matches `-std_backup.sqlite3` only, so they are never
  pruned. Tested.
- **`keep_dir` is the effective backup path at staging time**, as the design says; if it is
  gone or unwritable at start the swap fails safe (the restore does not happen) rather than
  writing the kept copy somewhere surprising.
- **The last-result banner reuses the `at` timestamp as its identity**: dismissing stores that
  value in `restore_last_seen`. The restored database brings its own `restore_last_seen`, so
  a result is always newer than what a snapshot knows and shows once.
- **`entrypoint.sh` calls the swap with `|| echo ...`** on top of the script's own exit 0, a
  second guard for the one case the script cannot cover (the interpreter failing to start it).
  No Dockerfile change: `COPY . .` already includes `restore_swap.py` (`.dockerignore` only
  excludes `mcp/`).

## 2026-11-20 — Backup, export and import, bak-04 (import UI, API, MCP)

Calls made while building phase 4 (`prompts/2026-11-20-bak-04-import-ui.md`), with the
operator asleep. Operator answers honoured: no "adopt install id" row (design Q1 is no;
`instance_id` is shown only as "from another install"), no secret is ever read or written,
the default mode is fill missing only, and users are created without a password.

- **The preview state lives beside the staged upload.** `importer.save_state` /
  `load_state` keep `stream_map` (the operator's explicit mapping), `digests`, `plan_fp`
  (the fingerprint of the default selection) and `eff_map` (the effective stream map) in the
  staging JSON. Each render of the preview re-plans and replaces them. On apply the route
  hashes the submitted selection against the stored digests with
  `fingerprint_from_digests` (bak-03's note) and passes that to `importer.apply`, which
  re-plans under the locks and raises `ImportStale` if a selected row changed. A hidden
  `fingerprint` field (the page's `plan_fp`) must equal the stored one, so a form from an
  older tab (another tab re-planned after a mapping change) is refused as out of date (409)
  instead of being applied against digests it never showed.
- **Form field names.** `sel-<rid>`, `create-<rid>`, `target-<rid>` as in design 12.2, but
  the per-field and option ticks are multi-valued fields `field-<rid>` and `opt-<rid>`
  whose values are the field / option names, not `field-<rid>-<field>`. A rid and a field
  name can both contain `-`, `:` and `/`, so splitting a combined name is ambiguous; the
  multi-valued form needs no parsing. A `fieldset` hidden marker (one per row that renders
  field boxes) says "send exactly the ticked fields", so unticking every field does not
  fall back to "every actionable field".
- **A changed stream mapping redirects to the preview** instead of
  re-rendering the POST, so a reload does not resubmit it. The mapping select submits on
  change with JS and has an **Update mapping** button without it.
- **Import routes sit in `routes_import.py` on `dashboard_bp`** (endpoint names stay
  `dashboard.*`). `routes_dashboard.py` is already very large, and the new module imports
  `_settings_redirect` from it, so it is imported once from `app.py`.
- **The import page is its own template with the Settings sidebar markup**, not a section
  of `settings.html`: the sidebar links go back to `/settings?section=<slug>` (Backup &
  restore is `aria-current`), `nav.js` is not loaded. It reuses `ui.js` (groups, confirm,
  toasts).
- **`ui.js` group counting.** A group counts only checkboxes marked `data-group-row` when
  its body has any, otherwise every checkbox as before. The import rows hold per-field boxes
  and option switches that must not count as records.
- **`/settings` is GET only now.** The `action=backup|restore` POST branches, the
  `server_backup_files` listing, `static/js/settings/backup.js` (the restore-source toggle),
  `_restore_checks` and `_parse_backup_datetime` are removed; an old form POST is a 405 and
  restores nothing. Their tests became import-flow tests (`tests/import_helpers.py` drives
  upload, preview and apply the way a browser does), with the intent kept where the new
  rules allow it:
  - *restore skips live stream entries / never overwrites a stream entry* -> a matched
    stream entry only gets operator settings filled; its observed facts (IP) stay;
  - *static scope* -> an imported record is never created locked and the summary says to
    re-run after the container registers; a ticked row locks an existing entry;
  - *confinement* -> `backups.resolve_file(name, suffixes=(.yml, .yaml, .json))` (snapshots
    and path tricks refused, a symlink out of the folder refused);
  - *restore replaced service checks wholesale* -> import never removes a check
    (`test_import_never_removes_a_local_service_check`);
  - *deleted_at round trip, observed status strings, source `notifier`* -> not carried any
    more (import creates an active manual entry, the trash is restored only with the option,
    observed columns are never imported, a Docker record created as new is manual until the
    container registers). A check that fails validation makes the whole record Invalid.
- **"Import as new" is the switch itself.** A not-found row has a `create-<rid>` switch
  (that is its row box) rather than a row checkbox plus a switch, so a group's tri-state
  and Select all tick the creates too, and "N new" counts them.
- **Ticking a field or choosing an ambiguous target ticks its row** (JS only), because a
  field the operator wants is a row they want.
- **API plan takes an optional `selection`, and returns `default_selection`.** The
  fingerprint is a hash of the *selected* rows, so a plan with no selection can only carry
  the one for the default selection, and an agent that picks other rows would have no way
  to get a matching fingerprint without hashing digests it never sees. `POST /import/plan`
  therefore accepts `selection` (additive, optional) and answers with the fingerprint for
  it; apply must send the same `selection`, `stream_map` and `fingerprint`. The per-row
  digests are not in the response. Still one revision-4 row (text extended, `import` added
  to `FEATURES`).
- **`import/plan` is not audited, `import/apply` is.** The management hook audits every
  authenticated write, so the plan route is exempted by endpoint name (like the snapshot
  PUT); apply records `object_type = "import"` with the result counts only, also for 400
  and 409 answers (those have no counts).
- **API status codes.** A file that cannot be read, a bad stream mapping, a bad choice and
  an apply that rolled back are 400 (`ImportApplyError` text in `error`); a stale
  fingerprint is 409 with a fresh `plan`; a body over 10 MB + 64 KB is 413.
- **MCP.** `import_plan` is a *write* tool (the route needs the write scope) with an
  optional `selection`; `import_apply` refuses a mode other than fill / overwrite before
  any request; a 409 carries "Nothing was written. Call import_plan again, show the
  operator the new plan, then apply."
- **Out of scope, parked in the design's Later list:** answering link offers from the
  preview, a mirror mode, staged restore (bak-05).

---

## 2026-11-20 — Backup, export and import, bak-03 (import engine)

Calls made while building phase 3 (`prompts/2026-11-20-bak-03-import-engine.md`), with the
operator asleep. The design stays the reference; these are the places it left a choice.

- **The fingerprint is built from per-row digests.** The design hashes "the selected rows"
  but the preview cannot know what the operator will tick. Every plan row therefore has a
  digest (`plan.digests`: rid, status, target, candidates and the field diffs, never
  observed data), and `fingerprint_from_digests(digests, selection, stream_map)` hashes the
  digests of the rows that are selected at apply time. `plan.fingerprint` is the one for the
  default selection; `fingerprint(plan, selection)` is the same thing from a plan object.
  bak-04 keeps the digests with the staged upload (or the page) so a changed selection does
  not read as a stale plan. A vanished row hashes as absent, so it still counts as stale.
- **A field the file leaves empty is not compared.** `None` in the file never reports a
  difference against a local value (group, sort priority, description, icon, URLs, widget).
  The design says "None == absent" for equality, but reading it strictly would make every
  legacy file from the daily job (no groups) show a difference on every row, and an export
  only carries what is set. Booleans are always compared.
- **Checks are compared and written as units** (`check:<kind>` or
  `check:service:<type>:<name>`), not per column. *Missing* means the local check still
  has the fresh configuration of a new row. Partial per-column merging would need
  cross-field validation (target against check type) for every combination. A check is
  validated and written through `check_form` (`validate_*`, `apply_check_values`,
  `new_service_check`), and an invalid one in the file makes the whole entry *Invalid* at
  parse time.
- **A Container check in the file is skipped, with a note, when the local entry has none**
  (a manual entry that the notifier has not adopted yet). It is filled on the re-run. An
  entry created with "Import as new" never gets one.
- **An applied URL is always `ui_edit`**, whatever source the file carried. Equal values
  count as identical even when the local source is `synthesized` (nothing visible changes,
  and the synthesizer keeps its value).
- **The icon is compared in its stored form** (`resolve_icon`: `name` becomes `name.svg`)
  on both sides, so a hand-written `name` does not differ forever from `name.svg`.
  Icons are not downloaded: an import makes no outbound call, least of all under the locks.
- **`notifier_wins` fields are left out of the diff**, not shown as non-applicable, so the
  row can still be identical on the re-run. A note and a plan warning say why.
- **Other never-applied fields are shown as `differs` with `applicable: False`**: the
  channel topic namespace keys and every difference on an existing user. Those rows stay
  *differs* on a re-plan, which is the truth (the file and the install disagree and import
  will not change it).
- **A new channel created disabled does not make the re-plan differ.** The `enabled`
  difference of a channel whose file says `secret_set` and enabled, and whose local copy has
  no secret yet, is not reported ("needs its password"), so plan, apply and plan reach
  *identical*.
- **Matched stream entries keep what they are.** Import does not set `stream_linked` or
  `pre_link_host` on an entry the stream created itself, and `linked` in the file only
  selects the identity used to match or re-create it. Setting it would change what stream
  cleanup does (unlink instead of delete) without the operator asking.
- **A stream record's manual fallback match also tries an offer first**, in the design's
  order: the stream's own entry by key, an open offer for the key, then a manual entry with
  `(pre_link_host, name)`. Two manual candidates make the row *Ambiguous*. When the stream is
  not enabled and nothing matches, the row is *Waiting*, otherwise *Not found*.
- **Two records of one file that would import as the same new entry make the second one a
  *Conflict*.** The legacy daily file has two devices called `dup-name`, and applying both
  as new would otherwise roll the whole import back at the second.
- **A not-found legacy stream row falls back to the manual identity** `(host, name)`, with
  `source_group` `manual`; its `rid` keeps `entry:stream:-/<mac>`. `ExportDoc` gained
  `EntryRecord.deleted_in_file` (never written by v1) for the legacy `deleted_at` flag.
- **Group choices.** An *Ambiguous* group row (`media` against `Media`) is answered with
  `target_id` (use the local group; entries naming the file's group then use it too) or
  `create`. It stays ambiguous on a re-plan while no exact-case group exists. A missing
  group is created by its own row or, when only an entry names it, by that entry.
- **Restore is an option, not implied.** A *deleted locally* row applies only with
  `options: ["restore"]`; ticking the row without it is skipped ("restore not ticked").
- **Selection details.** A row without `apply` in its selection entry counts as selected;
  `fields: None` means every actionable field of the mode (fill: *missing*; overwrite:
  both). A `differs` field named in `fields` is still not written in fill mode.
- **A bad stream mapping stops the apply** (`ImportApplyError`, nothing written) rather than
  silently skipping the rows that depend on it. The plan reports it per stream.
- **`ImportError` is an alias of `ImportApplyError`** because the design and the prompt
  use that name; the builtin is not used in `importer.py`.
- **Settings rows** cover exposure layers (one row per layer, per host and layer), the
  update check and each backup schedule. Applying exposure changes runs
  `synthesizer.recompute_all()` in the same transaction, as the Docker settings page does.
  A backup value is applied through `backups.save_settings` (the UI's validator), and a
  value pinned by an environment variable is skipped with a note.
- **Measured:** 5,000 Docker entries, each with a field to fill and a check to change: plan
  1.4 s, apply including its re-plan 1.8 s. The locks are held for that time. At the 20,000
  record cap expect roughly 6 to 8 s, which blocks registers for that long.
- **Staging files are 0600**, named by a 16-byte token (the token is checked against a
  strict pattern before it becomes a path), and `backups._run` prunes expired ones after
  each backup job's retention.

---

## 2026-11-20 — Backup, export and import, bak-02 (export format v1)

Calls made while building phase 2 (`prompts/2026-11-20-bak-02-export.md`).

- **Null fields are left out of the file; free-form dicts are kept as they are.** The
  writer walks the models and skips `None`, so the file reads like the design example and
  reading it back gives the same defaults. Every optional field therefore defaults to
  `None` (or its false/empty default), which keeps YAML and JSON round trips equal. `config`
  and `default_checks` are dicts and keep their own nulls (`tcp_port: null`).
- **Widgets in the export are the ones an active entry points at.** The design says
  "attached widgets only". A widget used only by a soft-deleted entry is not exported,
  because the entry that would reference it is not either (the snapshot has the trash).
  Two widgets with the same `(name, url)` collapse to one record.
- **The export header never creates `instance_id`.** `settings_store.peek_instance_id()`
  reads without writing, so `GET /export` and the daily job stay read-only. An install that
  never used MQTT simply has no `instance_id` in its header (the field is optional).
- **A channel `config` key that looks like a secret is dropped** (`secret`, `password`,
  `token`, `api_key` in the name), on top of `config` being non-secret by design. The cost
  is a key the channel type might legitimately want back; today `MqttConfig` has none.
- **Per-record validation and the v0 reader are left to bak-03.** The models only check
  types and the header literal. The cross-record rules of design 5.2 ("a docker entry needs
  a host", group and widget names must resolve) are import-time, per-row errors, so they
  live with the importer, not in the model validators that would reject the whole file.
- **`PUT /settings/backup` answers 409 for an env-pinned field before calling
  `backups.save_settings`**, comparing the submitted value with the effective one (an
  unchanged value passes, as in the UI). Other failures are 400 with the dotted field in
  `details[].loc` (`snapshot.time`). The nested request models are strict, and `format` is
  only accepted on `export`.
- **`POST /backups/run` returns 200 with `ok: false` and `error` when the run fails**
  (the run itself happened and was recorded), and 409 only for "already running". The
  UI toast does the same split.
- **`GET /backups` has no `total` / paging** (design 11: `{items}`), carries a `legacy`
  flag beside `manual`, and answers 409 when the folder cannot be read.
- **`GET /export` uses the `ExportDoc` model as its OpenAPI response schema**, so the spec
  documents the whole document. YAML is served as `application/yaml` and is not described
  separately (the spec generator emits JSON content only).
- **`API_REVISION` is 4 now, with the history row `(4, "0.11.0", "backup settings, backup
  list and run, export")`.** bak-04 extends the row text (and adds the `import` feature)
  and does not bump again. Three existing tests that hard-coded revision 3
  (`test_stream_observability.py`, `test_mcp_server.py`) now compare with `API_REVISION`,
  and the stream test keeps checking that revision 3 still has its row.
- **The MCP server keeps `MCP_VERSION` as is.** It follows `VERSION`, which `/release-prep`
  bumps. `export_config` takes no format argument (it returns the JSON document); an agent
  that wants YAML has no reason to.

---

## 2026-11-20 — Backup, export and import, bak-01 (scheduled backups)

Calls made while building phase 1 (`prompts/2026-11-20-bak-01-scheduled-backups.md`).

- **A save only writes values that changed.** Saving the form with a keep-days value equal
  to the current effective one (for example the `settings.yml` value) writes no row, so an
  unrelated save never turns a file value into a "set in the UI" value. Reset is only
  offered when the origin is `ui`. An env-pinned field submits its read-only value and is
  accepted if unchanged, refused if different.
- **No schema change.** The settings use the existing `setting` key-value table, so there
  is no migration. `backup_last_runs` is one JSON row holding both kinds.
- **Run now, Reset and Delete are separate forms outside the settings form.** HTML forms
  cannot nest, and the design wants one guarded settings form with a sticky save bar. The
  buttons point at hidden forms with `form="..."`, so `data-confirm` and the CSRF token
  work as in the other sections. Run now with unsaved edits does not save them.
- **Manual and scheduled exports both use the legacy name in this phase.** The export job
  still writes the entry list as `YYYY-MM-DD[_HHMMSS]-std_backup.yml` (the spec'd content
  and name), so new files carry the "legacy" tag until bak-02 writes `-std_export.*`. The
  export **format** setting is stored and shown, but the file stays YAML until bak-02
  (the card says so).
- **A run records its result in `setting`, so the snapshot of a fresh database contains
  that row.** `tests/test_db_snapshot.py` now runs the export before the snapshot so the
  live and snapshot row counts match (both runs update the same single row).
- **`resolve_file` serves both the new routes and the legacy restore form.** The restore
  branch passes `suffixes=('.yml', '.yaml')` and keeps its old messages; the new routes
  accept only the known backup suffixes plus `backup.yml`. A symlink pointing out of the
  folder is refused because the real path is checked.
- **`jobs.run_scheduled_backup`, `_write_sqlite_snapshot` and `BACKUP_SUFFIXES` were
  removed** (no alias kept; only `tests/test_db_snapshot.py` used them and it now calls
  `backups`). `jobs.reschedule_backups` pauses a disabled job after `reschedule_job`,
  because APScheduler's `reschedule_job` resumes a paused job.
- **PRD numbering.** The new planned section is §20 (renumbering Versioning, Cross-Repo and
  Open Questions to §21 to §23 and their live cross-references), as the settings section
  did for §19. The §19 TOC line now says Delivered to match its heading.

---

## 2026-11-20 — Settings modernization, set-04 (the remaining sections)

Calls made while building phase 4 (`prompts/2026-11-20-set-04-remaining.md`).

- **Backup & restore is out of this phase.** The operator decided to redesign backup,
  export and import as a separate project (`bak-01` onward), which rebuilds the section.
  `backup.html`, `backup.js` and the backup and restore routes and tests were not touched.
  The PRD §19 marks the modernization delivered except for that section.
- **The Docker (register) card moved to the top of Docker** (the operator's design Q3
  answer, deferred from set-03). Same markup and `id="stream-row-docker"`. The Streams list
  wrapper `#stream-list` stays in the markup but is `hidden` while there are no streams, so
  the Phase-1 layout test that looks for it still holds.
- **Groups stage in a `<dialog>` inside the one form.** The dialog's inputs have no
  `name`, so they never submit and the section keeps exactly one `<form`. Apply copies
  into the card's hidden inputs (name before value, as the tests read them) and dispatches
  `change` on the form so the unsaved guard sees it. Discard on the save bar is the
  existing reload link. The new group is a hidden card row that appears when staged, with
  a "Discard new group" ⋯ item. `save_groups` computes the first row with a message and
  passes `group_modal_id`; a stale-table failure has no row to edit, so it keeps its banner
  in the section (the phase-1 test for `data-flash-slot="groups"`).
- **Show-once key: `_render_settings` renders it, not a separate template.** The key reaches
  the page only as `api_key_secret` in that one response. Create keeps
  `Cache-Control: no-store`; rotate keeps `no-store, no-cache` and `Pragma: no-cache`.
  `api_key_created.html` was removed. It relies on `nav.js` `replaceState` to make a
  reload a plain GET (check it in a browser, since a re-POST on reload would otherwise
  create or rotate a second key).
- **Key and user validation errors now re-render with HTTP 400** (they redirected with a
  flash). `routes_auth` reaches Settings through the new
  `routes_dashboard.render_settings_for()`, imported inside the function because
  `routes_dashboard` imports `routes_auth`. `set_user_password` checks the user before the
  password length, so an unknown user is still a redirect with a `danger` flash.
- **A re-render does not echo secrets.** The Add user dialog gets `user_form` (username,
  email, admin) and never the password; the dialogs are blanked by JS on open (not
  `form.reset()`, which would restore the re-rendered values).
- **Tests changed on purpose:** `test_mgmt_api_keys.py` (bad key input and a duplicate name
  now 400 with `data-open-modal="api-key-modal"`; the Rotated cell and column assertions
  became the card summary "rotated <date>" / "rotated —"), `test_settings_layout.py` (a
  short password is no longer a redirect, and the key-name error is no longer a redirect),
  `test_streams_ui.py` (the Docker card is looked up in `#section-docker`).
- **Small shared additions:** `modal()` takes `attrs`, `card_row()` takes `cls`,
  `settings_group()` takes `check=False` and `count_text`, `save_bar()` takes `disabled`.
  `ui.js` gained `copyText`, `toast` and `[data-copy-text]` (widgets' Copy API key; the
  old `window.copyToClipboard` override in `access.js` was dropped). `.settings-root
  [hidden]` is now `display: none !important`, because `.settings-card-row` and the
  button rules set `display` and would otherwise beat the attribute.

---

## 2026-11-20 — Backup, export and import design (0.11.0)

Design in `docs/design/2026-11-20-backup-export-import.md` (mockup alongside), built by
`prompts/2026-11-20-bak-01` … `bak-05`.

- **Operator decisions:** two daily jobs (DB snapshot + export), each with its own
  keep-days (default 7) and a manual run; backup path chosen in the UI; the export
  replaces the old daily YAML; no secrets in exports, ever; users exported without
  passwords; import defaults to "fill missing only"; staged restore at next start is in
  scope (bak-05); no "adopt install id" on import (HA devices are recreated after a
  move); scheduled export defaults to YAML; default times 00:05 / 00:10.
- **Backup section is out of settings phase 4** (`set-04`): bak-01 rebuilds it.
- **Precedence for backup settings: env > UI (DB) > `settings.yml` > default.** Env is
  shown read-only. `settings.yml` only seeds, so a UI save is never silently ignored.
  Reset deletes the DB row. `backup_days_to_keep` seeds both keep-days values. No new
  file or env keys.
- **Two scheduler jobs with their own cron triggers, rescheduled in process.** A disabled
  job is paused, not removed. This relies on the single gunicorn worker. The scheduler is
  kept in `jobs._SCHEDULER`.
- **Manual runs are synchronous** and get a timestamped name (`YYYY-MM-DD_HHMMSS-…`),
  so they never overwrite the scheduled file of the day. Retention is per kind, by mtime,
  by suffix only. Legacy `-std_backup.yml` files age out with export retention.
  `backup.yml` and `pre-restore-*` are never auto-deleted.
- **A path outside `CONFIG_DIR` is a warning, not an error.**
- **Snapshots are downloadable from the UI only, never through the API**, because they
  hold every secret.
- **The export leaves out soft-deleted entries and detached widgets.** The snapshot covers
  the trash.
- **URLs are exported only when operator-owned** (`ui_edit`, or any URL on a manual or
  stream entry), and imported as `ui_edit`. `image_icon` is exported only where register
  does not rewrite it (manual, stream, locked Docker).
- **"Missing" means the local value is the fresh-row value.** For Docker group and sort
  priority, a value equal to `notifier_reported_*` also counts as fresh. Under
  `notifier_wins` those two fields are not importable.
- **Unknown fields in a supported format version warn; a newer `format_version` is
  rejected.** Adding an optional field keeps version 1.
- **Plan handoff: re-plan on apply under `_UPSERT_LOCK` → `streams._LOCK`, and compare a
  sha256 fingerprint of the selected rows.** The UI stages the parsed file in
  `CONFIG_DIR/import-staging/<token>.json` (60 min TTL, bound to the user). The API is
  stateless.
- **Import never creates streams and never changes a stream's status.** Stream settings
  and blocks apply to a mapped stream even while it is pending, so filters and blocks can
  land before Enable.
- **Import never modifies existing users**, in either mode. New users get the
  `"!unset"` hash: no password works, nothing is generated or shown, and an admin sets one
  in Users.
- **Channel namespace keys (`base_topic`, `ha_prefix`, `ha_device_prefix`) are never
  changed on an existing channel by import.** New channels with `secret_set` are created
  disabled.
- **Import as new never sets `is_static`.** A locked manual entry is not adopted by
  register, so the lock is applied by a re-run after adoption.
- **Import never answers link offers.** A stream record whose key has an open offer is
  matched to the offered manual entry, with a note.
- **Legacy v0 files: `widget_api_key` is ignored with a warning; `source: stream`
  records are matched by MAC across `mac` streams.**
- **The import preview is its own Settings page, not a modal** (it can hold thousands of
  rows).
- **One `API_REVISION` bump (to 4) for the whole 0.11.0 backup/export/import set.**
  bak-02 bumps it, bak-04 extends the row. The plan route needs `write`.
- **Staged restore swaps in `entrypoint.sh` before `alembic upgrade head`, using
  stdlib-only `restore_swap.py`.** The current DB is kept via `Connection.backup()`. A
  failure never blocks startup.

---

## 2026-11-20 — Settings modernization, set-03 (streams)

Calls made while building phase 3 (`prompts/2026-11-20-set-03-streams.md`).

- **The Docker (register) card stays in Streams this phase.** The operator wants it in the
  Docker section, but that move is phase 4 (set-04); moving it now would break
  `test_streams_ui.py` and half-build Docker.
- **The Edit dialog's three blocks are three forms, not one.** Each posts to its existing
  route (`update`, `monitoring`, `default-checks`), so no route, field or rule changed. The
  cost is that a dialog holds up to three dirty forms: `ui.js` `guardedForm` now returns
  the first dirty guarded form (else the first), and `streams.js` resets every form of an
  Edit dialog on `std:modal-discard`.
- **Only the three Edit routes re-render on error.** Typed values go in
  `forms['stream:<slug>:name|monitoring|checks']` and reach the template as
  `stream_forms`; the form is also marked `data-unsaved-start-dirty`. The lifecycle routes
  (enable, ignore, disable, delete, unblock, offers, apply) stay on flash + redirect, as in
  the design.
- **Preview stays a GET link** (`?section=streams&preview=<slug>`). `_render_settings` sets
  `open_modal='stream-preview-modal'` when a preview exists; `nav.js` drops `preview` from
  the URL when that dialog closes (it did not before). An unknown slug still flashes, now
  as a banner in Streams, because no modal opens.
- **`menu_item` got an optional `cls` argument** so ⋯ items can carry `stream-dialog-open`
  / `stream-notify-purge` for the delegated JS. The Preview item in the menu is a plain
  `<a role="menuitem">` (a navigation, not an action).
- **The open-offers badge reuses the amber badge style** with a ↔ prefix, so it reads
  differently from the pending count beside it. `open_offers` comes from `_streams_context`.
- **`test_settings_layout.py` (phase 1 test) was edited**: it asserted `id="stream-table"`,
  which no longer exists; it now asserts `id="stream-list"`.

---

## 2026-11-20 — Settings modernization, set-02 (notifications and Home Assistant)

Calls made while building phase 2 (`prompts/2026-11-20-set-02-notifications-ha.md`).

- **Field errors are rendered server-side.** The save error path passes
  `notification_error_fields` (the `config.` prefix stripped) to the template, which
  sets `aria-invalid` and opens Advanced; no client script maps errors, so the state is
  correct before JS runs and testable from pytest. The cleanup error has no input, so
  it shows only as the banner.
- **The Enabled switch is two shapes.** Enabled: a checkbox carrying
  `data-channel-remove="disable"` (clicking opens the existing dialog; the dialog's
  `close` flips it back unless the call succeeded). Disabled: a checkbox inside the toggle
  form that submits on change. Both keep the existing routes and fetch flow.
- **Card Send test reuses the form route** with the embedded saved config and a blank
  password, so no route was added; the dialog Send test posts the live form as before.
- **`ha_discovery_on` was removed.** `ha_discovery_live` (enabled channels only) replaces
  it; nothing else read it. A disabled channel publishes nothing, so counting it was the
  wrong answer for the warning.
- **When no channel is live the warning replaces the discovery line**, but the
  "N of M entries published" count stays, since it is the saved state either way.
- **The HA toolbar sits outside the form.** The search box and Select links are not
  form fields, so Discard (a form reset) does not clear the search or confuse the guard.
- **Group key `stream:<id>` becomes `stream-<id>` in the DOM** (the macro uses the key in
  an element id); `ha_groups` itself keeps the design's key.
- **`settings_group` got a `check_label` argument** for the "Publish all <label> entries"
  aria-label; the default stays "Select all in <label>".
- **A new channel still defaults to Enabled off**, as before the redesign.

---

## 2026-11-20 — Settings modernization, set-01 (foundation)

Calls made while building phase 1 (`prompts/2026-11-20-set-01-foundation.md`).

- **`flash_slot` reads the messages itself.** The macro calls `get_flashed_messages`
  (Flask caches the list for the request), so the shell and every section read the
  same list without passing it around, and "the template reads the messages once"
  holds. Toasts render in the shell's `#toast-region`, banners in the slot whose
  target equals `flash_target`.
- **Button shape is scoped to `.settings-root`.** `btn-primary` / `btn-secondary`
  stayed colour-only for Add/Edit (which add Tailwind padding classes); `btn-danger`
  and `btn-ghost` are global colours, and the padding, radius and font size for all
  four live under `.settings-root`, so the Add/Edit pages are untouched.
- **Focus return is a `showModal` wrapper.** `ui.js` wraps `HTMLDialogElement.prototype.showModal`
  to remember the opener, so the existing channel and stream scripts (which call
  `showModal()` directly and move unchanged until phases 2 and 3) get focus return
  without edits. Menu items close their menu in a capture-phase click, so the
  remembered opener is the visible ⋯ trigger.
- **Stream dialog ✕ uses `data-modal-close`.** The existing script binds
  `.stream-dialog-cancel` with `querySelector` (first match only), so the header ✕
  must not carry that class or the footer Cancel would lose its handler.
- **`set_user_password` keeps category `error`** in phase 1. The template already maps
  `error` to a danger banner; phase 4 changes the calls to `danger`.
- **Pending-stream warning keeps its raw text.** The test matches `to import\n    10
  items` whitespace-exactly, so it is a plain `inline-warning` div, not the macro
  (whose call block would re-indent it).
- **`.settings-tag` instead of `.tag`**, and the sidebar title/label classes carry
  the `settings-` prefix, to keep generic names free in the shared stylesheet.
- **`api_key_created.html` stays** (only its back link changed): the show-once modal
  and the file's removal are phase 4.
- **PRD numbering.** Old §19–§21 became §20–§22; older revision-history rows keep the
  numbers of their day, live references in the PRD body and the network-inventory
  design doc were updated. Prompts 02–04 mean the new §19.

---

## 2026-11-20 — Settings modernization design (0.11.0)

Design in `docs/design/2026-11-20-settings-modernization.md` (mockup alongside),
built by `prompts/2026-11-20-set-01` … `set-04`.

- **Operator answers to the design's open questions:** no separate 0.10.2 release (its
  fixes ship in 0.11.0); `bg-dashboard-info-box` gets defined (Edit page panels gain the
  card background); the Docker (register) card moves to the Docker section (in phase 4,
  so phase 3 stays green).

**Operator decisions (final):**
- Sidebar in six labelled groups, one deep-linkable section each (`/settings#<section>`,
  reload and post-save redirects return to it): General (About, Configuration),
  Dashboard (Groups, Widgets), Sources (Docker = today's Exposure interpreter, Streams
  incl. Blocked and Link offers), Integrations (Notifications, Home Assistant as its own
  section), Access (Users, API keys, Audit log as its own section), Data (Backup &
  restore, Deleted incl. detached widgets).
- Success flashes become an auto-dismissing toast. Errors stay as a persistent,
  dismissible banner in the section or modal where they happened, and validation errors
  reopen the modal with the input kept. Warnings that ask the operator to act stay
  inline. The long paragraph on top of each section shrinks to a one-line subtitle, with
  detail behind "ⓘ Learn more".
- List + Add + modal pattern (cards with a status dot, summary, Edit and a ⋯ menu; one
  modal for Add and Edit) for channels, users, API keys (show-once key in the modal),
  groups and stream actions. Destructive actions sit in ⋯ and keep their confirm dialogs,
  restyled.
- The Notifications card and modal layout (Connection, Authentication, Home Assistant,
  and a collapsed Advanced block; Send test beside Save; the cleanup prompt inside the
  modal). The Home Assistant section: discovery channels and "N of M entries published"
  in the header, entries grouped by source, collapsed by default, tri-state group
  checkbox, search expands matches, sticky Save bar only while dirty.
- Visual language of Add/Edit (`btn-primary`/`btn-secondary`, `input-clean`, info-box
  cards, `rounded-lg`, the `dashboard.css` tokens).

**Design calls:**
- **Deep links: hash for the browser, `?section=` for the server.** Sidebar items are
  `<a href="#slug">`. Redirects keep `url_for('dashboard.settings', section=…)`, because
  the server must know the section to put an error banner inside it, and a fragment never
  reaches the server. A validation error is a re-render of the POST URL, so the page
  carries `data-initial-section` / `data-open-modal` itself. On load, `nav.js`
  `replaceState`s to `/settings?<query minus section>#slug`. This also turns a reload
  after a failed save, or after creating an API key, into a plain GET instead of a
  resubmission. Legacy values (`info`, `exposure`, `api`) are aliases in a new
  `settings_sections.py` registry. Rejected: a hash in the redirect `Location` (the
  server can't place errors) and query-only (every section click would be a reload or a
  `pushState` dance). Section elements keep `id="section-<slug>"`, so a hash never
  scrolls.
- **Flash mapping in the template, no new `toast` category.** `success` / `info` /
  `message` become toasts, `danger` / `error` become error banners, and `warning`
  becomes an amber persistent banner. The ~60 `flash()` calls keep describing the
  outcome, not the presentation, and tests (which read messages from the session) are
  unaffected. A `flash_text` filter strips one leading emoji ("✅ ", "🗑️ ") in toasts.
  The messages themselves stay unchanged. `routes_auth.set_user_password` moves from
  `error` to `danger` and gets a section. Banners keep `class="flash-alert"` first
  (Add/Edit tests count it).
- **Fetch results stay inline** (test, purge, orphan scan, stream purge): they carry
  counts the operator is reading, so they are not toasts.
- **Base topic goes in the Connection block** of the channel modal (the decision didn't
  place it; it is required and shown on every card, so it is not "advanced").
- **The HA "discovery off" warning counts enabled channels.** Today's check counts any
  channel with discovery on, including a disabled one, which publishes nothing.
- **Groups' modal stages into the one form.** `save_groups` is all-or-nothing and needs
  every group id, so the modal's inputs have no `name` and Apply writes into the card's
  hidden `group-<id>-*` fields. The sticky save bar commits. Column sorting is dropped
  (cards are in priority order).
- **The Edit stream modal has three forms** (name and networks, staleness and missing,
  default checks), because the three routes stay. A combined route is under "Later".
- **Mobile: a `<select>` with an `<optgroup>` per group**, not a horizontal scroller
  (13 chips don't fit, and a scroller hides the group labels).
- **`unsaved_guard.js` gains `reset()`.** A modal filled by JS takes a new baseline, so
  opening Edit no longer marks the form dirty.
- **`bg-dashboard-info-box` is undefined today.** No CSS rule or Tailwind config defines
  it, so the Edit page's panels have no background. Phase 1 defines it as the card
  surface unless the operator objects (open question Q2 in the design).

---

## 2026-11-20 — 0.10.2: MQTT test budget and 128-char entry names

- **Test budget split.** `test_connection` had `TEST_TIMEOUT_SECONDS = 8` plus
  `PUBLISH_WAIT_SECONDS = 5`. Now `TEST_TOTAL_SECONDS = 5`, `TEST_CONNECT_SECONDS = 4`
  and a publish wait of the remainder, minimum `TEST_MIN_PUBLISH_SECONDS = 1` (so the
  worst case is a little over 5 s when connect takes the full 4 s). `PUBLISH_WAIT_SECONDS`
  was used only by the test and was removed; the live publisher never used it.
  It still runs on the request thread (notif-01 reasoning unchanged).
- **`loop_stop()` is run on a throwaway daemon thread, joined for at most 0.5 s.**
  paho's `loop_stop()` joins the network thread, which can be inside a blocking
  socket connect against a dead broker (paho's connect timeout is 5 s), re-adding
  the delay in `finally`. The thread finishes on its own; the caller does not wait.
- **No `API_REVISION` bump.** The register schema's `container_name` has no length
  cap (a bare `str`) and the stream item `name`/`key` were already `_text(128)`, so
  no wire maximum changed. Only the DB column (an internal limit) and the UI /
  management-API entry-name limit (`entry_rules.NAME_MAX`, 100 -> 128) moved; the
  latter loosens a check on operator-created entries, not a producer-visible contract.
  Group names stay 100 (`GROUP_NAME_MAX`), `pre_link_host` stays 100 (it holds a host).
- Migration `d7a3e9b2c418` uses `batch_alter_table`; the downgrade narrows the
  declared type only (SQLite does not enforce VARCHAR length), so no data is cut.

---

## 2026-11-20 — Known-gap triage after v0.10.1

All of 0.10.1 passed the operator's browser checks. The known gaps from the
handoff were sorted so they stop coming back as open items:

- **Accepted (works as designed, already recorded below):** the published-state
  set is shared across channels (notif-05); deleting a stream drops its blocks and
  offers, so `clear_blocks` only matters for disable + purge (inv-04); UI stream
  actions go to the app log, not `api_audit` (inv-04); entries linked before
  migration `b4e7a1c9d325` have no `pre_link_host` (inv-07); `find_duplicate` sees
  stream entries (one device, one entry).
- **Parked in `docs/FUTURE.md`:** persisting the "republish: false" purge hold, and
  renaming a stream ("Small gaps parked after v0.10.1"); expiry vs.
  `deleted_retention_days: 0` ("Stream observability follow-ups").
- **Fixed in 0.10.2 (see the entry above):** the MQTT test button blocking about 13 s against a
  broker that doesn't answer, and `container_name` being `String(100)` while the
  contract allows 128 characters.

---

## 2026-11-20 — inv-08 stream observability

- **Check targets follow the IP by rewrite, not by template (decided before code).**
  A `{inventory.ip}` placeholder was evaluated and rejected. The checker would stay
  pure (resolution would happen in `select_due_jobs`), but everything around it gets
  harder: the dict-based validators in `check_form.py` validate a literal host/URL
  per type and would need a second, placeholder-aware grammar; the API and MCP would
  have to round-trip a raw and a resolved target (and every consumer would need to
  know which one a `target` is); backups would carry templates that mean nothing on
  a manual entry after an unlink; a null IP would need a new "skipped" state because
  `health_result.ok` is NOT NULL; and the UI would show two values. Instead, when a
  snapshot (or a link) changes an entry's IP, `streams.follow_ips()` rewrites every
  *service* check whose target points at the old IP: ping (the target), TCP and DNS
  (the host of `host[:port]`, IPv6 bracketed), HTTP (the URL host; port, path and
  userinfo kept). Each move is logged and the check is asked to run at the next
  tick. A target that names a hostname is left alone (it follows DNS, not the
  stream). One query loads the service checks of all IP-changed entries, so the
  5,000-item query budget holds. If the IP disappears from the item, nothing can be
  followed: the checks keep their target and a warning is logged per check. inv-06
  default checks stay literal and keep counting as "untouched defaults" after a move.
- **Rejections are their own fields.** `last_rejected_at` + `last_rejection`
  (`"<status>: <first error>"`, 255 chars) beside `last_error`, not one field with a
  kind: `last_error` is an STD-side apply failure that a good apply clears, a
  rejection is the producer's fault and stays for the record. `rejecting` (derived:
  rejected after the last accepted snapshot) says whether it is current. Recorded
  only when the stream row exists and the key passed the binding (400 from pydantic
  or the value rules, 409 `key_type`, 413); a 403 is never written to a stream the
  caller doesn't own. Not audited, like every snapshot PUT. `record_rejection` rolls
  back first and commits only the two columns.
- **The producer may advertise its interval now (API revision 3).** The bump was
  needed anyway (0.10.0 shipped revision 2 and this release adds management fields),
  so the optional `snapshot_interval_seconds` (60-86400) rides on the same revision
  instead of being parked. STD ships first; std-source-technitium sends it only
  against revision 3+. Stored as `producer_interval_seconds` on every accepted
  snapshot (absent clears it: an older producer). The operator's
  `expected_interval_seconds` always wins; with neither, 15 minutes.
- **Grace factor 2.** Stale when enabled and `now - last_snapshot_at > 2 x
  interval` (strictly greater; first seen is the reference when an enabled stream
  never sent one). One late post (restart, backoff) is not an outage; two missed
  posts in a row are. A 5-minute producer that advertises its interval is flagged
  after 10 minutes; one that doesn't, after 30. Pending, disabled and ignored
  streams are never stale.
- **Entries of a stale stream are not marked stale.** Entry health comes from the
  entry's own checks; a dead producer is one signal on the stream (Settings badge,
  header count, a `stale_streams` line in the health summary, MQTT `stale`, HA
  problem sensor). Entries only get a muted "stream stale" hint in tooltips, the
  Tiled drawer, the detail facts and the edit page, so one dead sidecar does not flip
  50 devices.
- **health_summary keeps `failing` entry-only.** Stale streams are a separate
  `stale_streams` list (`state: "down"`, `message`, `since`) plus
  `counts.streams_stale`, rather than rows mixed into `failing`, whose items are
  entries with an `id` that agents follow up with `get_entry`. A compact `streams`
  block lists every stream.
- **Staleness is computed on read; the existing health tick drives MQTT.** No new
  column or thread: `stream_health()` is pure, the UI/API call it per request, and
  `HealthScheduler.tick()` calls `streams.watch_staleness()` (throttled to every 30
  s, one query). It logs each transition once and calls `notify.request_sync()` when
  the stale set changes, so `stale` on `<base>/stream/<id>` follows the clock.
- **The HA problem sensor lives on the stream hub device.** The task said "the
  stream's `ha_publish`"; streams have no such column, and the hub device already
  exists whenever the stream has a published entry, so the `problem` binary_sensor
  (`stream_<id>_problem`, ON while `stale`) is added there; no new opt-in. The stream
  purge clears it too.
- **`inventory_missing_since` is naive UTC; the backfill uses the upgrade time.**
  Rows already flagged missing get `CURRENT_TIMESTAMP` at upgrade: later than the
  truth, which can only delay an auto soft-delete. `last_updated` was rejected as a
  source because it is local time and moves with every snapshot change.
- **"Edited by a human" for auto soft-delete, concretely:** linked
  (`stream_linked`), renamed (`name_source = ui_edit`), locked, a group, a
  description, an icon, an internal or external URL, a sort priority, a widget,
  Home Assistant publishing, or any service check that is not an untouched default
  check (exactly as `add_default_checks` made it: `Ping` on the entry's IP or `TCP
  <port>` on `ip:port`, enabled, no interval/timeout/cert/HA overrides). Untouched
  default checks do not protect an entry, so turning defaults on does not disable
  the expiry.
- **Expiry runs in the daily soft-delete purge job, before the purge**, only for
  enabled streams with `missing_expiry_days` set (default off). It only soft-deletes;
  the item coming back restores the entry by key (the existing apply path). Each
  delete and each kept entry is logged. With `deleted_retention_days: 0` the same run
  then hard-deletes them; documented rather than special-cased.
- **Missing is a warning badge, never Down.** The Dashboard marker became an amber
  badge ("missing 3 days ago", full time in the tooltip); Tiled and Compact keep the
  amber router icon (the tooltip and the drawer carry "since"); the detail panel and
  the edit page say "Missing ... since". The roll-up is unchanged.
- **MCP `server_info` re-checks on every call** with `GET /api/v1/meta` (public,
  3 s timeout) and keeps the startup values beside the current ones; on failure it
  answers with the startup values labelled "as of startup <time>". `restart_advised`
  when STD's version or revision changed since the MCP started; `update_advised` (and
  an explicit `uv run .../v<std>/mcp/std_mcp.py` or `git pull`, then restart the MCP
  client) when the script is behind STD's major.minor. `MCP_VERSION` stays 0.10.0
  until `/release-prep` sets the next version.

---

## 2026-11-19 — inv-07 linked entries are the operator's; cleanup unlinks them

- **Linked entries are unlinked, never deleted, by cleanup.** A manual entry that
  joined a stream (Convert / accept / link) carries the operator's history, checks
  and settings, so `soft_delete` / `purge` (disable) and every delete option
  unlink it. Disable `keep` leaves it attached. The flag is `stream_linked`, set
  by `_convert`, not inferred from `name_source` (a renamed stream-created entry
  is also `ui_edit`, and is not the operator's in this sense).
- **Backfill heuristic.** No created timestamp exists, so for rows linked before
  the migration: per stream, `name_source = 'ui_edit'` and `id` below the stream's
  smallest `name_source = 'stream'` id means linked (the stream's own entries are
  created after a pre-existing manual one). It misses an entry linked after
  the stream created its first entry (higher id; it stays unmarked and is treated
  as the stream's, the old behavior), and wrongly marks a stream-created entry
  renamed while holding the lowest id, which errs on the safe side (unlinked, not
  deleted). `pre_link_host` stays NULL for them (host unknown).
- **Unlink restores the host, unless it would clash.** `find_duplicate` is
  checked (soft-deleted rows count, as for restore); on a clash the host stays
  NULL and the result carries `host_clash` rather than failing the cleanup.
- **Already soft-deleted linked entries are unlinked, not purged**, so a purge
  never removes anything that was the operator's; they stay in Settings → Deleted
  as manual entries.
- **Linked entries are left out of `customised_entries()`** (the "lose these
  settings" warning would be false) and get their own list in the dialog;
  `entry_stats()` gains `linked`.
- **No `API_REVISION` bump.** Revision 2 is unreleased; the unlink route and the
  additive fields ride in it, as notif-06 did.
- **Unlink lives at `/entries/{id}/unlink`**, not under `/streams`, because it
  acts on one entry and works for any stream entry. The edit-page UI is a
  `<details>` with two submit buttons rather than the JS delete popover, since
  that popover is wired to the delete flow.

## 2026-11-19 — notif-06 MQTT/HA cleanup tools and per-stream topics

- **A stream status topic, not entry topics under a stream path.** Retained
  `<base>/stream/<stream_id>` carries the stream's status and counts. Moving
  entry topics to `stream/<id>/entry/<n>/...` was rejected: topics use ids so a
  rename never moves one, and Convert (a manual entry joining a stream) would
  have moved a topic and orphaned the old retained message and HA entity. The
  stream topic is part of `desired_state`, so `full_sync` publishes it and clears
  it when the stream goes; it is published for every stream whatever its status
  (a pending stream is useful to an automation) and the commit listener now
  watches the stream's `status`/`last_*` columns, new/deleted streams and link
  offers. Cost: a sync (debounced, non-forced) after each snapshot, since
  `last_snapshot_at` is in the payload.
- **Stream hub device with two count sensors.** The brief said "an active/missing
  count sensor"; I made it two sensors (Active entries, Missing entries), the same
  pattern as the hub's per-state counts, instead of one sensor with the other
  number as an attribute. Stream entry devices use `via_device` the stream device;
  the stream device exists only while at least one of its entries is published, so
  `via_device` never points at a device that has no configs.
- **Cleanup defaults: delete on, disable off, base change on.** Deleting a channel
  is the last chance to reach its broker, so the dialog ticks the box; disabling is
  reversible and the broker is often down when someone disables, so it is unticked;
  a base change is the only moment the old base is known, so it is ticked. The API
  mirrors them (`cleanup` default true on `DELETE`, null on `PATCH` meaning on for a
  base change and off for a disable). A cleanup that can't reach the broker refuses
  with 409 and changes nothing (the operator picks "Delete anyway" /
  `cleanup=false`), except that a base change on a channel with no live session
  (disabled) skips the cleanup silently, otherwise every edit of a disabled channel
  would error. Existing `DELETE` callers that expect a plain delete now need
  `cleanup=false` or a connected channel (revision 2 is unreleased, so no bump).
- **Delete clears `<base>/status` last and suppresses the session's `offline`.**
  `MqttSession.stop()` publishes `offline` (retained) before disconnecting, which
  would re-create the topic just cleared; `suppress_offline` skips it. A disable
  keeps the normal `offline`. The same flag is set for the old base on a base change.
- **Remembered bases: 5, newest first, per channel, in the `setting` store.** No
  migration; they only feed the orphan scan, so a short list is enough and an old
  base the operator no longer remembers can still be typed in. The pair
  `(base_topic, ha_prefix)` is kept so a prefix change is scanned too. A base the
  channel switches back to leaves the list.
- **Orphans are STD-shaped topics only, diffed against every channel on the same
  broker.** A scan of `<old>/#` would otherwise list another app's topics or a
  sibling channel's live topics. Only `status`, `summary`, `entry/<id>/state`,
  `entry/<id>/check/<id>`, `stream/<slug>` and this node's discovery configs are
  candidates, a base equal to a discovery prefix is refused, and a clear with an
  explicit list re-checks each topic. Clear takes the previewed list so the operator
  clears what they saw; clear without a list re-scans.
- **Stream purge is `purge_entry` batched; "disabled stream, nothing comes back"
  holds only when its entries are gone.** `_purge_entries` serves both. A disabled
  stream with `keep` leaves active entries, which stay eligible and are published
  again, so I did not change eligibility (no new rule that hides entries of
  disabled streams from MQTT).
- **Scan and clear are POST + write scope.** They subscribe to the broker for
  several seconds like the test and purge calls; a GET with such side effects, or a
  read key doing broker I/O, seemed wrong.
- **No new module.** The cleanup, remembered bases and orphan scan live in
  `notify_purge.py`, so the CLAUDE.md module layout needs no new line.

---

## 2026-11-19 — Stream follow-ups from the first live test (inv-06)

- **Link matching compares host.** Operators put a device's hostname in the add
  page's Host field, so name-only matching on host-less entries missed real
  matches. Candidates are now every active manual entry; an item matches on its
  name or first DNS label against the entry's name, host or host's first label.
  Still "exactly one candidate or create": a wrong offer is cheap (the operator
  answers it), a wrong silent link is not, so ambiguity creates. An entry already
  claimed by an offer for another key is not offered twice. Convert/link clear
  `host` because stream entries never have one.
- **Purge keeps `stream.snapshot`.** The snapshot is the sidecar's latest word, not
  entry data; keeping it lets Preview and Enable work right after a purge without
  waiting for the next post. `ignore` still discards it (that is its point) and
  `delete` removes the row.
- **Default checks are a stream column, not a template system.** `default_checks`
  JSON `{ping, tcp_port}` is the smallest thing that makes stream devices
  monitorable; monitor profiles stay parked. Apply-to-existing skips an entry that
  has any check of the kind rather than comparing targets, so customised checks are
  never touched or duplicated.
- **`pending` rides on the `GET /streams` list** (an extra key next to `items`/`total`)
  so MCP can report the pending count; additive inside the unreleased revision 2.
- **Dry-run counts are computed on page render** (one read-only `plan()` per
  pending/disabled stream) rather than stored, so they never go stale.
- **Compact source icon** (operator scope addition): `partials/source_icon.html`
  duplicates Tiled's Docker status classification instead of refactoring Tiled's
  template, to keep the Tiled diff small.

---

## 2026-11-17 — Streams UI (inv-05)

Calls made while implementing PRD 18.8 (also recorded as "As built" notes there):

- **Server-rendered, no new JSON endpoints.** Preview is a GET on the settings page
  (`?section=streams&preview=<id>`), not a fetch; every action is a plain form POST
  to a thin route that calls `streams.py` and flashes. Matches the Notifications
  and Deleted tabs, keeps CSRF to the usual hidden field, and needs no JS beyond
  opening the dialog.
- **One cleanup dialog per stream, two modes.** Disable… and Delete… share it; JS
  swaps the form action and wording. The counts and customised entries are rendered
  server-side from `streams.entry_stats()` / `customised_entries()`, so the dialog
  never goes stale relative to the page load and no extra endpoint is needed.
  `clear_blocks` only shows for disable + purge, because deleting a stream drops
  its blocks and offers through the FK anyway.
- **Source filter value `stream:<stream_id>`** rather than a numeric id: bookmarks
  survive a stream being recreated, and the value is validated against the stream-id
  pattern. The bare `stream` value is kept.
- **Delete popover grew a second button** instead of a new modal, so the same
  popover serves Dashboard, Tiled and the edit page: `showDeletePopover(..., {stream})`
  calls back with `block`.
- **Offer answers take a same-site `next`** (checked with `safe_redirect_target`) so
  the banner on a manual entry's edit page returns there, while the Streams tab uses
  the same routes.
- **UI stream actions are logged, not audited.** `api_audit` is keyed to API keys;
  a session has none. The API's audit stays the record for API-driven changes.

---

## 2026-11-17 — Inventory streams backend (inv-04)

Calls made while implementing PRD 18.4-18.7 (also recorded as "As built" notes there):

- **Ingest routes live on the management blueprint** (scope `ingest`), not a
  sibling blueprint. `require_api_key("ingest")` reuses the auth, last-used and
  JSON-error code; `scope_allows` makes `ingest` satisfy only `ingest` (and
  `write` satisfies it), so an ingest key fails every read/write route. The
  audit hook skips the snapshot endpoint by name instead of a per-request flag,
  so 4xx answers to snapshots are not audited either.
- **`ignored` is answered before the body is read.** Cheap, and a producer for a
  stream the operator ignored can't get 400/413.
- **`display_name` is creation-only.** The contract says the producer's value is
  ignored once the operator renames; with no column to record "renamed", the
  simple rule is that a snapshot never touches it.
- **Deleting a stream removes its blocks and offers** (FK to the stream row, so
  they can't outlive it). `clear_blocks` therefore only matters for `disable` +
  `purge`. A sidecar that keeps posting recreates the stream as pending.
- **Delete + `soft_delete` turns the entries manual** (still soft-deleted), since
  a `source = stream` row can't outlive its stream; they restore from Settings -> Deleted.
- **Accepting an offer sets `name_source = ui_edit`**: the manual name is the
  operator's, so the next snapshot must not rename it to the producer's casing.
- **A stream entry restores from a YAML backup as manual**, and a backup record
  never overwrites a live stream entry. `stream` is in `VALID_SOURCES` now, so
  without this a restore would create `source = stream` rows with no stream.
- **Edit page / `is_manual` -> `not is_docker`** for the Name label, Description
  field and host handling in `edit_entry.html` and the `/edit` handler (stream
  entries are operator-nameable but not Docker); `host` stays NULL for them, and
  Description is only written when the form carries it.
- **`name` is VARCHAR(100) in `service_entry`** but the contract allows 128. SQLite
  doesn't enforce the length, so names are stored whole rather than widening a
  column through a table rebuild.
- **`ingest` is not in the Settings key picker yet** (inv-05 owns the UI); the
  API accepts it, so a `write` key serves for testing until then.

---

## 2026-11-17 — Source refactor: `is_manual` vs `is_docker` (inv-03)

Added `ServiceEntry.is_docker` (`source == notifier`; an unflushed instance with
`source` None counts as Docker, matching the column default). Each branch:

- Means "not Docker" -> `is_docker`: `tiled_dash.html` (docker status classes,
  source icon, Docker drawer row), `dashboard.html` (status pill),
  `edit_entry.html` (container section), `models.py` stale guard,
  `ensure_container_check`, container-check eligibility, `view_helpers`
  stale filter, `mgmt_serializers` `stale`.
- Means "operator-made" -> kept `is_manual`: Name label and name field in
  `edit_entry.html`, host editable only for manual in the `/edit` handler,
  management API name/host rule and `POST /entries` source, register's
  adopt-manual-entry branch (`routes_api.py`).
- Filters: `normalize_source_filter`, `matches_source` and the `source` query on
  `GET /api/v1/entries` match any `VALID_SOURCES` value exactly (OpenAPI enum
  built from it).
- Restore: a present-but-unknown `source` restores as manual (host optional);
  a missing key keeps the pre-0.7 backfill rule.
- HA `model`: `SOURCE_MODELS` map in `notify_ha.py`, defaulting to "Manual".

---

## 2026-11-17 — "Since" sensor reads the existing state topic; snapshot via tmp + rename

- The Since sensor reuses `<base>/entry/<id>/state` (`since` is already there), so
  §17.1 "publish changes only" holds and nothing new is published. A null
  `since` renders the string `None`, which HA's MQTT sensor treats as unknown.
- The SQLite snapshot backs up from SQLAlchemy's raw connection (the live,
  WAL-aware handle) into `<name>.tmp`, then `os.replace`s it, so an interrupted
  run never leaves a partial `.sqlite3` that looks like a valid backup.

---

## 2026-11-17 — API revision headers set app-wide, `meta` public

- The `X-STD-API-Revision` / `X-STD-Version` headers come from one app-level
  `after_request` keyed on `request.path.startswith("/api/")`, not a blueprint
  hook, so register, the management API, and unrouted 404/405 all get them.
- `GET /api/v1/meta` is public and reads only in-memory state. It reveals no
  more than the headers do.


## 2026-11-17 — Network-inventory design review: stream ingest API, Technitium sidecar

- **Inventory arrives through a generic stream ingest API, pushed by
  sidecars, not pulled by STD.** STD owns the contract
  (`PUT /api/v1/streams/<id>/snapshot`, `ingest` key scope, strict core
  fields plus a free-form `attributes` dict). Producers follow it, the
  same split as the Docker notifier. Rejected: a Technitium source
  inside STD (the first revision). It saved a repo, but every new feed
  (Pi-hole, Kea, Zigbee) would have been a change to STD, and source
  credentials would have lived in STD.
- **Full snapshots, not per-item upserts.** "Reservation gone" is then
  just "absent from the latest snapshot", with no TTLs or heartbeats.
- **New streams arrive pending; enabling is per stream.** This replaces
  a global `inventory_enabled` switch. A key holder can create a
  stream, but nothing is applied until the operator previews and
  enables it.
- **The Technitium producer is a new repo (`std-source-technitium`),
  not a mode in docker-api-notifier**, even though the notifier already
  talks to Technitium DNS. A small standalone sidecar is the reference
  others copy, and the notifier's job stays unchanged.
- **The Docker notifier stays on `/api/v1/register`.** Moving the
  most-used contract onto streams would gain little.
- **`stream` is a third `source` value; the pill shows the stream's
  display name.** Docker containers never have DHCP reservations (their
  DNS is a CNAME to the parent host), and hard-coded-IP hosts
  (em-pve01, em-dockha01) have static A records and stay manual. So
  the sources never overlap. The cost is a small refactor first: about
  12 branches use `is_manual` to mean "not Docker" and switch to a new
  `is_docker`. Rejected: `source = manual` + a `kind` flag. It needed
  no refactor, but it hides where an entry came from.
- **UniFi dropped.** It would import phones and end-user devices. The
  discovered-device inbox and the `entry_interface` table went with it
  (FUTURE.md). A stream entry is one item, and the multi-NIC hosts are
  manual.
- **A manual entry matching a new stream item is offered for linking,
  never auto-converted**, so its history, checks and HA settings
  survive. Name matching isn't reliable enough to do it silently.
- **Deleting a stream entry asks "allow re-adding" or "don't re-add".**
  "Don't re-add" puts the stream key on a permanent, visible block list.
  This replaces tracking why an entry was deleted. Without it, a
  snapshot would resurrect a device the operator had deliberately
  deleted.
- **Thresholds store `health_check.state`** instead of each reader
  deriving it from `last_ok`. Change detection keys on `last_ok`
  flipping, so `pending` → `down` (still failing) would never publish.
- **Backup format change parked; nightly SQLite snapshot instead.**
  The YAML export is entries-only. Deciding what a backup should hold
  is a separate discussion (FUTURE.md).

---

## 2026-11-17 — notif-05 purge MQTT and Home Assistant

- **"Republish: false" holds the channel, it does not untick `ha_discovery`.**
  Unticking would change the operator's config behind their back and covers
  only discovery, not the state topics. Instead `PublishState.held` (a set of
  channel ids, in memory) makes every publish skip that channel until
  something changes: any `request_sync()` (commit listener, health change via
  `publish_changes`) releases it, and a (re)connect releases that channel.
  Releasing forces a full republish, because the payload cache is shared and
  would otherwise make a non-forced sync think the channel is current. A restart
  also ends the hold (connect republishes), which is the unsurprising outcome.
- **The 10-minute safety net must not undo a purge.** It was a forced sync
  that would have republished within minutes, defeating "leave the broker
  empty". It now calls `notify.safety_net_sync()` (`keep_held=True`), which
  syncs the other channels and leaves held ones alone.
- **State-topic bookkeeping is shared across channels.** `topics` and
  `payloads` have no per-channel key (state events go to every session), so a
  channel purge empties them only when it is the only live channel; with
  several, they stay (the other brokers still have those topics) and the forced
  or release-time sync republishes to the purged one. Splitting the set per
  channel was rejected as a larger change than this feature needs.
- **Waits.** Collecting the retained burst waits at least 1 s, until 0.6 s of
  quiet, at most 6 s (the broker gives no end-of-burst marker). The 2 s
  pause before republishing is Home Assistant's processing time, per the task.
  Worst case for a channel purge is about 6 + 2 s, under the request's 15 s
  wait. A timeout is a 504 and the job still finishes on the publisher thread.
- **Channel purge reaches the whole base topic.** Everything under
  `<base>/#` is cleared, not only STD's known topics: the base topic carries no
  instance id, so two STD installs sharing a base topic would clear each other
  (they would already fight over `<base>/status`). Home Assistant configs, which do
  carry the instance node id, are filtered to this instance only.
- **Entry purge clears every check of the entry**, enabled or not, plus
  remembered topics, because a disabled or opted-out check may still have a
  retained topic or config. It also clears the entry's discovery topics
  defensively when the entry is not opted in (nothing is republished).
- **API scope.** The management API has only `read` and `write` scopes (an
  "admin API key" is the write scope), so both routes are `write`.
- **Purge UI uses fetch + JSON** (inline counts, no page reload) and a native
  `<dialog>` for the confirm so the Republish checkbox can sit in it.

---

## 2026-11-17 — notif-04 Home Assistant entries are opt-in; host in device names

- **Opt-in, not opt-out.** notif-03 published every entry once "Add to Home
  Assistant" was on; the operator got ~50 unwanted devices. Publishing is now
  opt-in per entry (`service_entry.ha_publish`, default false) because an
  unwanted device in HA is noisy to clean up while a missing one is one tick
  away. Checks stay opt-out (`health_check.ha_exclude`) inside a published
  entry. The channel box remains the master switch and the hub publishes
  whenever it is on.
- **Clean-slate migration `e3b7c1d9a204`.** Every existing entry becomes
  `ha_publish = false` regardless of its old `ha_exclude` (operator decision);
  `service_entry.ha_exclude` is dropped (batch mode). A new forward migration
  rather than editing `d8e2a6f4b915`, which has already run on the operator's
  dev database. Downgrade restores `ha_exclude` (false). Nothing released
  carries `ha_exclude` on entries, so the API field was renamed with no shim.
- **Bulk picker.** Settings -> Notifications -> "Home Assistant entries" posts
  the ids it displayed plus the ticked ones; only displayed ids are changed, so
  an entry added meanwhile is not silently unpublished. All changes are one
  commit, so the commit listener causes one sync. Select all / none apply to the
  rows the filter shows.
- **Host in the device name** (operator, same day): `<prefix> <name> (<host>)`
  always, not only on collisions; no host (manual entries) gives
  `<prefix> <name>`. `default_entity_id` is the slug of that device name, so it
  includes the slugified host. `unique_id` is unchanged (instance id and
  database ids). HA keeps entity ids it has already registered, which is moot
  because the migration starts everyone with nothing published.
- **Backups.** `ha_publish` (entries) and `ha_exclude` (checks) now round-trip;
  notif-03 had left them out. Older backups without the keys leave the value
  at its default (unpublished / published check).

---

## 2026-11-16 — notif-03 Home Assistant discovery

- **`default_entity_id`, not `object_id`.** The HA MQTT docs (fetched
  2026-11-16, home-assistant.io/integrations/mqtt) say the `<object_id>` in the
  discovery topic does not influence the entity id and that
  `default_entity_id` (a full `sensor.xyz`) controls it. They do not state a
  release or an explicit deprecation of the payload key `object_id`, so that is
  unverified; I used `default_entity_id` only and never `object_id`. If an old
  HA ignores `default_entity_id`, entity ids simply come from device name +
  entity name, which also start `std_` with the default prefix.
- **Per-channel discovery inside the existing reconcile.** Discovery configs
  contain the channel's own base topic and are published under that channel's
  `ha_prefix`, so they cannot go through the shared "dispatch to every
  session" path. `full_sync()` now calls `sync_discovery()` first, which
  builds the set per live session and uses `Publisher.dispatch_to`; events
  carry `absolute: true` (topic not prefixed with the base). The published set
  is `ha_topics[channel id]`, persisted in `notify_publish_state.ha`. No
  second reconcile.
- **Channel delete/disable leaves its configs on that broker.** There is no
  session left to clear them with. The remembered set for a deleted channel is
  dropped. The operator turns `ha_discovery` off first to clear.
- **Hub connectivity sensor has no availability topic.** The prompt says all
  entities use `<base>/status` for availability, but this sensor's state *is*
  that topic; with availability it would read "unavailable" instead of "off"
  when STD is down.
- **No `configuration_url`.** STD has no configured public base URL
  (`dashboard_url` is a path, PRD 17.3), so a valid absolute URL cannot be
  built on the publisher thread. Add one with a base-URL setting later.
- **Check state mapping.** The problem sensor is ON only when `state ==
  down`; a check that has never run (`unknown`) is OFF rather than a false alarm.
- **Check payload gained entry attributes** (`entry_name`, `host`, `group`,
  `source`, `dashboard_url`, `std_entry_id`) so `group`/`host` filters work on
  `binary_sensor`s. Side effect: renaming an entry or changing its group now
  republishes its check topics too (test updated).
- **Per-check toggle uses a hidden `ha_seen` marker.** The form field is a
  checkbox "Publish" (unticked = excluded). Without a marker, a form missing
  the field (older page) would exclude every check; the server leaves the
  stored value alone unless the marker is present. Same for the entry box
  (`ha_form`).
- **Controls always visible** rather than hidden when no HA channel exists:
  a hidden control would also be absent from the submit.
- **Birth message forces a full sync for all channels**, not just the one that
  sent it. Simpler and harmless (payloads are identical retained messages).
- **Migration table name.** The prompt says `service_entries`; the table is
  `service_entry`.

---

## 2026-11-16 — notif-02 state publishing

- **A commit listener, not a call in every mutation path.** The prompt asked
  mutation paths to call `notify.request_sync()`. Entries and checks change
  in a dozen places (UI add/edit/delete/restore/purge, the management API,
  register adoption and restore, backup restore, the purge job). Instead
  `notify_state.install_listeners()` flags a session in `before_flush` when a
  watched object changes (new or deleted ServiceEntry, HealthCheck or Group, or
  a changed name/host/group/source/URL/soft delete/check config) and calls
  `request_sync()` in `after_commit`. The cached `last_*` result columns are
  deliberately not watched, or every health tick would trigger a sync.
- **`full_sync` runs on the publisher thread and dispatches directly**, not
  through the 1000-slot queue: a sync of a large install would overflow it and
  drop its own events. Change events from the scheduler do use the queue.
- **Sync is debounced (2 s) and diffed.** A sync only republishes topics
  whose payload changed (an in-memory map in the publisher); connect and the
  safety net force a full republish. The safety net is a 10-minute APScheduler
  job (forced, so it also repairs a broker that lost its retained messages).
  The "after channel config changes" trigger is covered by the connect: any
  config change restarts the session, which reconnects and forces a sync.
- **No sync while no channel has a session**, and nothing is remembered then.
  Otherwise a delete while the broker is down would drop the topic from the
  persisted set without clearing it on the broker. The next connect forces.
- **The published set is global, not per channel.** One JSON value in the
  `setting` store (`notify_publish_state`; no table, no migration) holds the
  topics, each entry's last roll-up with `since`, and each check's `ok` with
  its change time. Known limits: a topic cleared while one broker was
  unreachable stays retained there, and changing a channel's base topic leaves
  the old retained topics behind.
- **Only counted checks get a topic** (`check_counts`: enabled, able to run);
  the roll-up counts and the topics then agree, and a disabled check is
  cleared like a deleted one.
- **Entry events also fire when the per-state check counts change**, not only
  when the roll-up does (e.g. an extra check's first pass leaves the entry
  `up`), so the retained payload never lags. The summary fires only on a
  roll-up change.
- **`dashboard_url` is the path `/edit/<id>`.** STD has no configured public
  base URL, and the scheduler thread has no request to derive one from.

---

## 2026-11-16 — notif-01 channel framework and MQTT

- **`paho-mqtt` 2.x, not `aiomqtt`.** STD is threaded (gunicorn threads,
  APScheduler, a health thread), not asyncio. `aiomqtt` would need its own
  event loop thread plus a bridge to every producer; paho's `loop_start()` is
  already a network thread and `publish()` is thread-safe. Pinned
  `paho-mqtt>=2,<3` in `requirements.in` (2.2.0 compiled), using
  `CallbackAPIVersion.VERSION2`.
- **One publisher thread, one bounded queue (1000), drop oldest.** Producers
  call `notify.enqueue()`, which only does `put_nowait` and never raises. A
  state change is superseded by the next one, so the oldest event is the right
  one to lose; the full-queue warning is rate limited to once a minute. The
  thread is the only code that touches brokers.
- **`connect_async` + `loop_start`, never a blocking `connect`.** Applying a
  channel never waits on the network, and a broker that is down at startup
  does not delay STD. paho's own `reconnect_delay_set(1, 60)` does the
  backoff. State changes are logged only when the (state, error) pair
  changes, so retries stay silent.
- **The test button uses a throwaway client with a `-test` client id.** Two
  clients sharing a client id make the broker disconnect the older one, so
  testing with the live id would knock the real connection offline. The test
  client has no will (it must not flip `<base>/status` to `offline`). It runs
  in the request thread (up to ~13 s), not on the publisher.
- **Reload = diff by fingerprint.** `reload_now` compares each enabled
  channel's (type, config, secret, instance id) with its live session; only
  changed, removed or new channels are stopped/started. A clean stop publishes
  `offline` itself because a clean disconnect does not fire the will.
- **Port is resolved at validation.** `port` blank becomes 1883, or 8883 with
  TLS, and is stored, so the config always carries the real port. `client_id`
  stays NULL (resolved to `std-<instance>` at connect) so the default follows
  the instance id. `tls_insecure` without `tls` is rejected.
- **`ha_discovery`, `ha_prefix`, `ha_device_prefix` are stored now, unused.**
  notif-03 needs no config reshuffle; the UI does not expose them yet and a
  UI edit preserves them (config is merged).
- **The secret is a plain column, like `widget_api_key`.** No at-rest
  encryption: the same trust model as the existing widget keys and the
  SQLite file. It is write-only: `secret_set` in responses, never logged,
  never in the audit (the audit records only a `credential_set` flag), and a
  failed-save re-render never echoes it.
- **A failed test is HTTP 200 `ok: false`**, not an error status: the request
  worked and the answer is "the broker said no". Unknown config keys and bad
  values are still 400; a duplicate name is 409. The test endpoint needs the
  `write` scope (it is a POST that opens a connection and publishes).
- **Event shape for MQTT is `{topic, payload, retain}`** with `topic` relative
  to `base_topic`; richer event kinds arrive with notif-02. Events that do not
  fit are ignored by the channel.
- **`on_connect_hooks` are called from paho's network thread** with the
  session; hooks must not block for long.
- **Not started under pytest.** `request_reload()` is a no-op unless the
  publisher thread runs; conftest installs a client factory that raises, so a
  test can never open a real socket. `test_checker.py` now patches
  `jobs.notify.start` where it patches the threads.
- **No `MCP_VERSION` bump.** It is set only by `/release-prep` (v090-09
  decision), so the three new MCP tools leave it alone.

---

## 2026-11-16 — version in the UI (update check design)

- **PR builds get `channel=pr`**, not `dev`: a PR image is neither the dev
  branch nor main, and the display treats `pr` like `dev` anyway
  (`dev · 0.9.0+sha-…`), so nothing is lost by being precise.
- **Persisted the last good result** in the `setting` table
  (`update_check_cache`: latest version, release URL, checked_at, ETag), in
  addition to the in-memory cache, so a restart does not refetch at once and
  the ETag survives. Failure state (backoff, last error) stays in memory only:
  a restart is a fair moment to retry.
- **Backoff:** `interval * 2^failures`, capped at 24h, pushed further by
  `Retry-After` or `X-RateLimit-Reset` when remaining is 0. Only the first
  failure of a run logs a warning, so page loads never spam the log.
- **Status endpoint is `GET /api/update-status` in the dashboard blueprint**
  (login-protected), not the management API: it serves the browser header, not
  API keys. The management API instead gets the same data in `whoami`/`config`
  plus `GET/PUT /settings/update-check`.
- **The check is triggered from the template context processor**, so every
  rendered page starts a stale refresh with no per-route code; it swallows all
  errors so the header can never break a page. A lock allows one refresh in
  flight; saving the settings calls `version_check.reset()` so the new interval
  applies at once.
- **Tests:** conftest stubs `version_check._spawn` and `_http_get` for every
  test (no threads, no network); tests that exercise the check drive
  `refresh_now()` / `maybe_refresh()` directly.
- **MCP:** the new fields are merged into `server_info` after
  `compare_versions`, leaving the compatibility logic untouched.

---

## 2026-11-16 — v090-11 health-tinted entries

- Tint is a plain `entry-health-<state>` class set in the templates, CSS-only
  (no `!important`: the Dashboard rows carry no Tailwind background or hover
  class, so a `tr.group-entry.entry-health-*` selector wins). Auto-refresh
  reloads the page, so no JS patching was needed. Only degraded/down are
  classed; up/unknown/none stay untouched.


## 2026-11-16 — v090-10 (B) v2 tile layout adopted as the Tiled view

- The operator chose the preview layout. `tile_layout` plumbing, the notice,
  `.tile-layout-v2` scoping, the old two-row `.tile-status-row` column layout
  and `/tiled_preview` were removed; v2 is the only markup/CSS path (the
  `exposure_inline` flag stays: the Dashboard view includes the same partial
  non-inline). `_render_tiled` folded back into `tiled_dashboard`.

---

## 2026-11-16 — v090-10 (A) detail panel "503" vs the API's full message: Body-mode gap

- Root cause (confirmed by the operator: Status mode showed the full text,
  Body mode only `503`): `probe_http`'s body branch returned
  `error_text or str(code)` for status >= 400, never extracting the JSON
  reason added to Status mode in v090-08. The panel and API were fine. Fix:
  body mode reuses `_code_with_reason` (an `Error:` prefix still wins; 2xx
  handling unchanged). Tests use the operator's exact `/healthz` body in
  both modes, plus probe -> rows -> panel JSON and Check now.
- Hardening: a down check always renders its message line, falling back to
  `status N (empty reply)` / `no reply`; static CSS/JS get `?v=<file mtime>`
  via a `static_v()` template helper (mtime, not app version, so dev edits
  bust the cache too).

---

## 2026-11-16 — v090-09 MCP: PEP 723 install, version check, `MCP_VERSION` test

- Install is `uv run` with the dependencies in a PEP 723 header, duplicated
  from `mcp/requirements.in` (kept for CI and the venv path). A test parses
  the header and compares it with `requirements.in` so they cannot drift.
- `MCP_VERSION` is a constant in `std_mcp.py` (the script must work from a raw
  URL with no `VERSION` file beside it). The prompt asked for a test that it
  equals `VERSION`, but on `dev` `VERSION` is still the last release (0.8.0)
  while `MCP_VERSION` is already 0.9.0, so strict equality fails until
  `/release-prep` bumps `VERSION`. The test asserts `MCP_VERSION >= VERSION`:
  a release that bumps `VERSION` without `MCP_VERSION` fails, and
  `/release-prep` Step 1 now sets both (and stages `mcp/std_mcp.py`).
- Comparison uses major.minor only; patch differences are `match`. A missing
  `whoami.version` is `std_older` (STD < 0.9.0); non-semver is `unknown`.
  `unknown` also adds a (softer) notice to the instructions; `build_server`
  without version info (older callers/tests) adds none.
- The 3.11-only `tomllib` is used by the header test; CI runs 3.11.

---

## 2026-11-16 — v090-08 roll-up: Container fails alone, URL/service checks judged as a group

- Container failing is always `down`; URL/service checks (http, tcp, ping,
  dns) all failing is `down` even when the container passes (the Emmett
  negative test showed Degraded for a 503 `/healthz`). Container-only entries
  unchanged. `routes_mgmt_api.health_summary` had its own copy of the
  down/degraded rule; replaced by `entry_health` so there is one rule.
- Status-mode HTTP checks now always pass `stream=True` and read the body
  only when the code is >= 400 (threshold unchanged), so the failure reason
  surfaces; message capped at 200 chars (`ERROR_MESSAGE_LIMIT`), under the
  255 column limit. A JSON object with none of the known keys falls back to
  the raw body text, per the prompt.

---

## 2026-11-16 — v090-06 temporary Tiled layout preview (`/tiled_preview`) — ADOPTED in v090-10

- **Why it exists:** to compare a proposed Tiled tile layout (name across the
  full width, host tight under it, one status/action icon row along the tile
  bottom) against the current one with real data. It is unlinked (no nav
  entry) and not a shipped feature; no CHANGELOG entry.
- **Decision required before `/release-prep 0.9.0`:** either *adopt* v2 (it
  becomes the Tiled layout; remove the `/tiled_preview` route, the
  `tile_layout` plumbing, the notice, the `.tile-layout-v2` scoping and the old
  tile CSS; add a CHANGELOG entry) or *delete* the preview (route, template
  branches, `.tile-layout-v2` / `.tile-preview-notice` CSS, the three
  `test_preview_*` tests).
- **CSS-only, scoped:** all new rules sit under `.tile-layout-v2`; the template
  changes are only `{% if tile_layout == 'v2' %}` wrappers (notice + one
  `<div>`), so `/tiled_dash` renders byte-identical (checked against HEAD,
  modulo the per-request CSRF token). The handler body was factored into
  `_render_tiled(**extra)`.
- **No JS change needed:** the controls use `window.location.search` and the
  edit link uses `request.full_path`, so the operator stays on the preview.
- **Exposure badges (v090-07):** one badge per layer (`view_helpers.exposure_layers`,
  registered as a Jinja filter) in all views; no `×N` count beside the logo
  (operator call). Hover says `<layer> — N routes` (raw row count) then the
  routes de-duplicated by hostname+path only, so web/websecure routers on one
  host give one line; TLS/auth aggregate as "any". In v2 the badges render
  inside the bottom status row (after the status icons, thin separator),
  nowrap and clipped rather than pushing the action icons off; the v2 status
  row gap was tightened to 2px so three badges plus `+N` fit at 390px.

---

## 2026-11-16 — v090-05 implementation calls (host on tiles)

- **Compact's `always` is not identical to the old rule.** The old rule showed
  the host on every row only when more than one host existed; `always` shows it
  on every entry that has a host, even with a single host. Close enough, and
  the default `duplicates` is the intended new behavior. Noted in CHANGELOG.
- **Normalization in `settings_loader`, not `app.py`.** Unlike
  `register_field_ownership` (validated in `app.py`), the value is lower-cased,
  trimmed and validated inside `load_settings()` so it is correct wherever the
  loader is used and testable without building the app.
- **Id set computed in Python and passed to templates**, over all active
  entries (the unfiltered list), so a status/source filter can't make a
  duplicate look unique. Rejected: computing in Jinja or over the visible set.
- **Host-less entries are neutral.** They are never marked and a NULL host is
  not "a different host" for hosted entries, so a manual twin doesn't label a
  notifier entry.

---

## 2026-11-16 — v090-04 implementation calls (Groups: one Save, unsaved guard)

- **Group name/icon rules live in `entry_rules.validate_group`.** The
  management API had its own copy (`_group_problems`); it now delegates, so the
  Settings form and the API share one rule set. Priority reuses
  `entry_rules.parse_sort_priority` (negatives and 0 allowed; the dashboard
  sorts on plain ints with NULL as 9999).
- **Swap-safe apply.** `group_name` is UNIQUE and SQLite checks per statement,
  so an A<->B swap would fail mid-flush. Renamed rows are first parked on a
  placeholder name (flushed), then given final values. Rejected: dropping the
  unique constraint (a migration for a UI nicety).
- **Stale table is refused, not merged.** A submitted id that no longer exists,
  or an existing group missing from the form (added elsewhere after load), is a
  400 with nothing written; the operator reloads with Discard. Applying a
  partial table could silently undo someone else's change.
- **Re-render after a 400 starts dirty via `data-unsaved-start-dirty`**, not by
  diffing against DB values: simpler, and the failed submission is by
  definition unsaved. `_render_settings()` was split out of `settings()` so the
  400 path renders the full page without a redirect.
- **The guard's snapshot is order-independent** (sorted `name=value` pairs), so
  `sortTable` re-ordering rows is not an edit. `sortTable` now skips the "new"
  row (`data-no-sort`) and reads only text/number inputs (the hidden delete flag
  sits in the Controls cell).
- **The Groups table always renders**, even with no groups, because the new row
  is now the only way to add the first group.
- **JS verified with a throwaway headless Playwright script, not a committed
  test**: the repo has no JS test setup and CI has no browser. Server behaviour
  is covered by `tests/test_groups_save.py`.

---

## 2026-11-16 — v090-03 implementation calls (API key rotation, name reuse)

- **Key management stays out of the management API.** Rotate, like create and
  revoke, is Settings-UI only (admin + CSRF). §14.8 keeps users and keys out of
  `/api/v1`, so a leaked key could never mint or rotate keys. No OpenAPI or MCP
  change.
- **Rotate replaces the prefix too.** It reuses `generate_key()`, so the new key
  is a different prefix and secret on the same row. Rejected: keeping the
  prefix (the displayed prefix would no longer tell old from new key).
- **`rotate_key` raises `ValueError` on a revoked key**, matching the module's
  guard style; the route checks `revoked_at` first and flashes instead.
- **Name uniqueness moved to a partial index.** `uq_api_key_name` is dropped
  (batch mode) and `ux_api_key_name_active` (`name WHERE revoked_at IS NULL`)
  added in the same migration as `rotated_at`. Rotation keeps the name and the
  row, so it never trips the index. The downgrade raises a `RuntimeError`
  naming the duplicated names rather than silently dropping rows.
- **Audit filter switched from name to key id** (`audit_key=id:<n>`), because a
  reused name would otherwise merge two different keys. Audit rows whose key row
  was deleted (`api_key_id` NULL) still get a name-only option; the old
  `?audit_key=<name>` URLs keep working for those.

---

## 2026-11-16 — v090-02 implementation calls (certificate expiry)

- **`cryptography` to parse the certificate.** The stdlib cannot decode a
  certificate from an unverified handshake: `getpeercert()` returns an empty
  dict when `verify_mode` is `CERT_NONE`, and only the DER form is available.
  Rejected: a hand-rolled ASN.1 walker (more code than the feature, easy to get
  wrong on odd validity encodings) and the private
  `ssl._ssl._test_decode_cert` (undocumented, can change or vanish between
  Python releases). `cryptography` was already in the MCP server's pins (via
  PyJWT), now a direct app dependency at the same pin (50.0.2); it ships
  manylinux wheels, and `docker build .` on `python:3.11-slim` still works.
  `requirements.txt` was regenerated with `--upgrade-package cryptography`
  only (new pins: `cryptography`, `cffi`, `pycparser`).
- **The handshake is a separate connection** (`checker._read_cert_expiry`):
  `requests` does not expose the peer certificate, and with Verify TLS on a
  failing certificate would never reach us. Consequence: it connects straight
  to the target host and ignores an `HTTPS_PROXY` / `NO_PROXY` that `requests`
  would honour. A proxied setup would therefore read a different path (or fail
  with `cert check failed`). Accepted; documented in the README and CHANGELOG.
- **A failed HTTP result is attempted for its expiry too**, and keeps its HTTP
  message: the panel still shows the date when the service is down. When both
  fail, the HTTP failure wins and no date is recorded.
- **`record_check_result` always overwrites `last_cert_expires_at`** from the
  result instead of the job deciding when to clear it. No condition, plain
  http, or an unreadable certificate all produce None, which is the "never
  show a stale date" rule in one line. Editing the minimum to blank also clears
  it at once (the form/API assign path), so the panel does not wait for the next
  run.
- **Validator value is `cert_days_value`** (like `interval_value` /
  `timeout_value`), while the API/DB field is `cert_min_days`. The form parses
  the hidden input of a non-HTTP service row as blank rather than erroring
  ("the form never submits it"), while the API rejects it with a 400. A PATCH
  that switches a service check away from http drops a stored minimum unless
  the request sends one (which is then a 400), so retyping a check does not need
  an extra `cert_min_days: null`.
- **`last_cert_expires_at` is not in `to_config()`** (a cache, like the other
  `last_*` columns); `cert_min_days` is, and restore range-checks it.
- **The detail panel date uses the browser's locale** (`toLocaleDateString`
  with the year), like the panel's other times, rather than a fixed
  `YYYY-MM-DD`; the day count is floored client-side so it matches the probe's
  message.

---

## 2026-11-16 — v090-01 implementation calls (DNS check)

- **The server must be an IP literal.** The check exists to ask one specific
  server, and a hostname would need the system resolver to find it. Bare IPv6
  without a port (`2001:db8::1`) is accepted because it is unambiguous; with a
  port it must be bracketed (`[2001:db8::1]:53`), so `2001:db8::1:53` reads as
  an address, not as an address plus a port.
- **`dns.resolver` is not used anywhere**; `udp_with_fallback` talks to the
  given server (TCP only on truncation). A test patches the resolver (and
  `socket.getaddrinfo`) to explode while a probe runs.
- **Answer comparison is exact-match-on-any after normalizing**, not a
  substring or regex match: case-insensitive, trailing dot stripped,
  whitespace collapsed, IPs compared in canonical form (so `2001:0DB8::1`
  equals `2001:db8::1`), TXT as joined strings without quotes. MX and SRV
  compare the full presentation form (`10 mail.example.com`). The IP
  canonicalization goes beyond the written rules; it only removes false
  mismatches.
- **` | ` joins several answers in the failure message** (readable in the
  tooltip and unlikely to occur inside a record).
- **Numeric rcodes are rejected** (`dns.rcode.from_text("3")` would accept
  them) so the stored value is always the name that the probe compares with.
- **The expected rcode is stored explicitly as `NOERROR`** when left blank
  (blank means NOERROR per the spec); `dns_expected_answer` blank is stored
  NULL. The probe still treats a NULL/blank rcode as NOERROR, for rows from
  older backups or direct writes.
- **`dns_*` fields on a non-DNS service check are silently dropped** (stored
  NULL) rather than rejected, matching how mode/verify are handled for
  non-HTTP types. On URL and container checks, PATCH rejects them with 400
  like `target`.
- **`CheckOut` carries the four fields always** (null for other types),
  matching how it already carries `mode` and `verify_tls` for every type.
- **Downgrade drops the four columns but leaves `check_type='dns'` rows**;
  they would fail as unknown types on an older version. Documented in the
  migration; remove DNS checks before a real downgrade.

---

## 2026-11-15 — v080-05 implementation calls (MCP server)

- **Pinned `mcp==1.30.0` (the v1 line), not 2.x.** 2.x (latest 2.3.0, October)
  renamed FastMCP to `MCPServer` and moved the import; the prompt and PRD say
  FastMCP, and 1.30.0 (7 Sep) is a stable release well over two weeks old.
  Moving to 2.x later is a one-import change plus a re-run of the tests.
- **`httpx` for the client** (already an `mcp` dependency, and it has
  `MockTransport` for tests and `WSGITransport` for running the server against
  the real Flask app in-process).
- **`mcp/requirements.txt` is compiled with `-c requirements.txt`**, so shared
  packages (pydantic and others) stay on the app's pins and the CI `Test` job
  can install both. `requirements-dev.txt` includes it: CI actually runs
  the MCP tests, and the test module imports `httpx` directly, so a missing
  install fails loudly, not silently skips. The runtime `requirements.txt` is
  untouched.
- **No `.dockerignore` existed and the Dockerfile does `COPY . .`**, so a new
  one lists `mcp/`. No other entries were added; widening it is a separate call.
- **No `mcp/__init__.py`, module loaded by path in tests.** A package named
  `mcp` in the repo root would otherwise compete with the SDK on `sys.path`.
- **PATCH tools take a `fields` object** (`update_entry`, `update_check`),
  because a typed signature cannot tell "absent" from "null", and the API gives
  those different meanings. Keys are checked against an allowed set client-side
  for a readable error; the server remains the authority.
- **`upsert_group` is client-side** (list, find by exact name, then POST or
  PATCH). It cannot clear an icon or sort priority; use the UI or the API for
  that. No server endpoint was added and `OPERATIONS` is unchanged.
- **Two tools beyond the PRD list:** `list_widget_types` (needed to fill in
  `set_widget`) and `remove_widget`. Both are thin wrappers of existing
  endpoints. `whoami` is not a tool; it is used at startup.
- **Scope gating registers tools, it does not replace the API check.** A read
  key never sees write tools, and the API still returns 403 if one were called.
  A key that fails `whoami` at startup exits with the reason (no tools).
- **Tools return JSON text** (`-> dict` yields unstructured text content), and
  failures raise `ToolError`, which the SDK turns into an `isError` result.
- **httpx's INFO request logging is silenced** so the stdio server's stderr
  stays quiet (URLs only, never the key, but still noise).

---

## 2026-11-15 — v080-04 implementation calls (OpenAPI, audit view, docs)

- **Own registry + pydantic, no flask-smorest/apispec.** `mgmt_openapi.OPERATIONS`
  is one declaration per endpoint; the spec is built with `TypeAdapter.json_schema()`.
  Fewer dependencies, and the tests compare it to `app.url_map` and to each
  view's `required_scope` (set by `require_api_key`). The registry is declared
  beside, not on, the routes, so a new route needs two edits and a test fails
  if either is forgotten.
- **Response TypedDicts use `typing_extensions.TypedDict`.** pydantic refuses
  `typing.TypedDict` below Python 3.12 and CI is 3.11. Both pythons run the suite.
- **Generic `Page[T]` components are named `PageOf<Item>`** (pydantic titles
  them all just "Page", which would collide). Union responses
  (`DELETE /entries/{id}`) are inline `anyOf`.
- **Spec is filtered by blueprint, not URL prefix**, so `/api/v1/register` and
  the browser JSON routes under `/api/v1` stay out. `/openapi.json` itself is
  public and listed.
- **Unmatched `/api/v1/*` gets JSON only if `url_rule is None` and the caller
  sends a Bearer header or `Accept: application/json`.** Routed requests
  (browser routes, register) are never touched, and a plain browser still gets
  the Flask page. Handled app-wide because blueprints cannot catch unrouted URLs.
- **Audit filter is by `key_name` (the snapshot)**, via a dropdown of names
  seen in the log, so revoked or deleted keys can still be filtered.
- **README endpoint table is generated from the registry** and a test checks
  every row is present, so docs cannot silently drift.
- **MCP sentence left as a placeholder** in "Managing STD with Claude" for v080-05.

---

## 2026-11-15 — v080-03 implementation calls (groups, widgets, settings, config)

- **Group delete matches the UI (409 with active entries); `?force=true`
  ungroups them.** The PRD said "its entries become ungrouped (same as the
  UI)", but the UI refuses. The code wins by default and `force` gives the PRD
  behaviour on request. Soft-deleted entries are always ungrouped.
- **Group PATCH rename to a taken name is a 409** (the UI handler would hit the
  unique constraint); renaming to its own name is allowed. Names are trimmed
  and limited to 100 characters, icons to 255. The UI handlers were not
  changed.
- **Widget validation lives in `widget_rules.py`; `/edit` is untouched.** The
  API requires a known type, a non-empty URL and at least one field, all of
  them valid for the plugin; `/edit` accepts anything.
- **`PUT /entries/<id>/widget` key semantics:** omitted `widget_api_key` keeps
  the stored key, `null` clears it, a string sets it. Fields are de-duplicated
  keeping order. The audit only lists changed fields; the key is always `***`
  (so a changed and an unchanged key look alike, as decided in v080-01).
- **`?delete=true` only removes the widget if no other entry uses it**;
  otherwise it just detaches. Widgets are normally one-per-entry so this is a
  safety net.
- **Widget and group writes are audited before the lookup**, so a 404 still
  carries the object type in the audit row.
- **Exposure PUT is strict where the UI is lenient.** The form drops invalid
  directions silently; the API rejects them with a 400 and changes nothing.
  Layers and hosts need not be "discovered" (the UI also accepts any).
  `"neither"` values are stored, as with the form.
- **`GET /config` adds a `sources` map** (env/file/default/derived) from the
  startup snapshots, and masks by name: the known secret names plus the
  `_key`/`_token`/`_password`/`_secret` suffixes. Only `settings_loader`'s
  known keys are returned, never Flask internals. `secret_key` is not a
  loaded setting, so it never appears.
- **Widget types list is a `Page` envelope** (`total` = count, no real paging)
  to keep every list endpoint one shape; items expose `key`, `label`,
  `description` only (not the internal `api_path`).

---

## 2026-11-15 — v080-02 implementation calls (entries, checks, health)

- **API field names follow the dashboard, not the table.** `name` (not
  `container_name`), `icon`, `locked`, `group` (a name in, `{id, name}` out);
  checks reuse the backup vocabulary (`check_type`, `interval_seconds`,
  `timeout_seconds`, `verify_tls`). Create takes service checks as `checks`
  and URL-check settings as `url_checks: {internal, external}` (the PRD said
  "a list of service checks plus URL-check settings" without a shape).
- **Defaults differ from the form in two places.** A service check created
  through the API is enabled unless `enabled:false` (the form's checkbox
  defaults off, but an agent that adds a check wants it running), and an entry
  with no `group` is ungrouped rather than put in the UI's literal "None"
  group. URL checks still default to disabled.
- **Strict string/number/bool types in request bodies.** `"60"` or `"yes"` is a
  400 rather than being coerced (JSON `true` must not become `1`); value rules
  stay in `check_form` / `entry_rules`, so pydantic checks shape only.
- **Notifier-owned fields are a fixed deny-list, checked before pydantic.**
  `NOTIFIER_OWNED_FIELDS` names them in a 400 (also derived/read-only output
  fields such as `health` or `source`, so a GET-then-PATCH round trip fails
  loudly instead of silently ignoring them). Other unknown keys fall to
  `extra="forbid"`. Name and host on a notifier entry are a 400 even when the
  value is unchanged.
- **`limit` above 1000 is clamped, below 1 or non-numeric is a 400.** Same for
  `offset` below 0.
- **`status` filtering is done in Python.** Health state is derived, so any
  status other than `all` loads the SQL-filtered rows (checks eager-loaded) and
  filters with `matches_status`; `all` paginates in SQL. Fine at homelab scale;
  the query count is flat either way.
- **`since` for a failing check** is the earliest failed sample after the
  latest passing one (two cheap aggregate queries per failing check), falling
  back to `last_checked_at`, instead of walking `consecutive_failures` rows,
  which breaks if the run is longer than the retained history.
- **Edit's icon download and the quirky Edit behaviours were left alone.**
  `/edit` still downloads in place (the security tests patch
  `routes_dashboard.requests`) and still does not validate the name; only the
  URL provenance and sort-priority parsing moved into `entry_rules`. Add moved
  fully (basic limits, duplicate, icon, group). Messages and statuses are
  unchanged.
- **Check writes are refused on a deleted entry (409)**, as are entry PATCH,
  Check now and add-check; reads still work on deleted entries.
- **A check-id route 404s only for an unknown id.** `PATCH`/`DELETE
  /checks/<id>` find the check, then the deleted-entry rule applies.

---

## 2026-11-15 — v080-01 implementation calls (API keys and audit)

- **Prefix is 8 hex chars, not a slice of the urlsafe secret.** `token_urlsafe`
  can contain `_`, which would break `std_<prefix>_<secret>` parsing. A hex
  prefix has no `_`, and the key is split with `split("_", 2)` so a secret
  containing `_` still parses.
- **A scope mismatch (403) counts as an authenticated request.** The key was
  valid, so `last_used_at` is touched and a write attempt is audited. This
  keeps a read key probing write endpoints visible. Unauthenticated (401)
  requests are only logged.
- **Admin UI routes live in `routes_dashboard.py`, not the management
  blueprint.** `/settings/api-keys` is a browser form route (session + CSRF
  + admin), so it belongs with the other `/settings/*` routes; the
  CSRF-exempt, key-only blueprint stays pure API.
- **The create response is a dedicated page, not the Settings page.**
  Re-rendering Settings would need its large context rebuilt; a small
  `api_key_created.html` (no-store) shows the key once and links back.
- **Key names are unique including revoked keys** (DB unique constraint per
  the PRD), so a revoked name cannot be reused. The error message says so.
- **Audit masking is by field name** (the known secret names plus any name
  containing `secret`, `password` or `token`) and replaces both old and new
  values, so an audit row never reveals a secret or whether it changed.
  Conservative over precise.
- **No `/api/v1` routing-level JSON 404/405 yet.** Flask blueprints do not
  handle unmatched URLs, and `/api/v1/*` already holds browser JSON routes, so
  a blanket app-level handler would change their behaviour. Raised views get
  JSON errors; revisit in v080-04 with the OpenAPI work if wanted.
- **Existing migration test adjusted.** `test_container_check.py` upgraded to
  `head` and downgraded `-1`, which now removes this migration instead of the
  container one; it now pins the container revision explicitly.

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
