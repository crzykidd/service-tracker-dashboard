# Design: container moves and duplicates, and label-driven settings with provenance (0.14.0)

**Status:** design, awaiting operator approval (2026-11-22). No code has changed.
**Author:** Claude (design session, 2026-11-22), from
`prompts/2026-11-22-design-moves-and-label-settings.md`.
**Code read:** STD `dev` at `de5c42d` (v0.13.0 prepared, `API_REVISION = 6`); docker-api-notifier
`main` at `ed3274e` (v0.5.1) plus its queued 0.6.0 prompt
`prompts/2026-11-22-std-network-details-and-label-hardening.md`. Where this note and the code
disagree, trust the code.
**Revision numbering:** the label fields are API revision 8, not 7: revision 7 went to the 0.13.1 Ports fix (`ports_unknown`).
**Builds on:** `docs/design/2026-11-22-notifier-labels.md` (the label list and pitfalls),
`docs/FUTURE.md` → "Service identity and duplicate detection" and "Register overwrites some
operator edits".

**One root cause, two symptoms:** operator settings live on a row that register either
abandons (a move creates a new row) or overwrites (a clobber). Provenance fixes the second and
is what makes a safe merge possible for the first.

---

## 1. Goals and non-goals

Goals:

- **Per-field provenance** for every operator-settable field register can write, so a UI edit
  always wins and a label can own a value without freezing it.
- **Fix the existing clobbers:** the icon and the URL-check toggles (§3.5).
- **New label-driven register fields** (API revision 8): `description`, the three image-update
  fields, `image_repo_url`, URL-check settings, and a display-only `attributes` pass-through.
- **Move and rename detection** with an operator-confirmed merge or dismiss.

Non-goals:

- **No auto-merge, ever.** Not at register time, not by a job, not with a "high confidence"
  bypass (FUTURE.md:188-191 still holds).
- **No auto-flagging of the old row's state.** A suspected move never silences checks, changes
  `docker_status`, or suppresses an HA/MQTT "down". The operator wants to see that the old side
  is dead until they say it moved (Q3).
- No move-aware API (`/api/v1/move`) for orchestrators: still deferred (FUTURE.md:241-245).
  The merge endpoint (§2.7) covers "after the fact".
- No new labels for `ha_publish`, widgets, service checks, group icon/sort, `locked`, name or
  host (notifier-labels §2 says why). Service checks from labels stay parked
  (FUTURE.md:274-281).
- Nothing the 0.6.0 notifier prompt already does: `std.skip`, reserved-key stripping, bool/int
  label warnings, the per-feature gate (its tasks 1, 3, 4).

## 2. Move and duplicate detection

### 2.1 Today (from the code)

- Register matches on `(host, container_name)` only, stream rows excluded, soft-deleted rows
  included and resurrected (`routes_api.py:209-248`). A move creates a fresh row
  (`routes_api.py:330-373`).
- The old row goes stale: the notifier's refresh loop lists running containers only
  (`docker-api-notifier/main.py:99`), so an exited container stops reporting. The Container
  check then reads "Container exited", later "No update from notifier for N min"
  (`models.py:432-447`, threshold `stale_after_minutes`, default 5, `models.py:466-474`).
- MQTT state and HA discovery are keyed by **entry id**: topics `entry/<id>/…`
  (`notify_state.py:76-85`), HA device `<node>_entry_<id>` and check entities
  `<node>_check_<check_id>` (`notify_ha.py:92`, `notify_ha.py:226`).
- **FUTURE.md is out of date here (trust the code):** delete is a soft delete now
  (`models.py:164-168`), hard delete keeps the widget (`models.py:827-836`), and the threshold
  is `stale_after_minutes`, not the 2 h of FUTURE.md:162.

### 2.2 Candidate rules

A pair is **(N, O)**: N the new row, O the possible old twin.

**Eligibility (all must hold):**

| Rule | Why |
|---|---|
| Both `source = notifier`, both active (`deleted_at IS NULL`), neither locked (`is_static`) | Manual rows are already adopted by key (`routes_api.py:234-241`); stream rows have their own link offers; a locked row gets no registers, so "stale" means nothing. |
| Keys differ: different `host` (move) or same host, different `container_name` (rename) | |
| N is fresh (`not is_docker_status_stale`, `models.py:359-370`) | |
| O is stale **or** O's `docker_status` is not `running` | At register time O is often still fresh but just sent `die`/`stop`. |
| The pair has no `dismissed` record (§2.6) | |

**Evidence (at least one strong, or two medium):**

| Evidence | Strength | Notes |
|---|---|---|
| Same `container_name` and same image repository (`image_ref` minus tag, via `image_ref.parse()`) | strong | The plain move. Tag may differ (moved and upgraded). |
| A shared exposure `hostname` (`service_exposure.hostname`) | strong | Covers moves and renames. |
| A shared URL whose source is `ui_edit` or `explicit_label` | strong | Same as FUTURE.md. |
| Same `stack_name` and same image repository | medium | The compose-service rename. |
| Same normalized `container_name` (lowercase, `-`/`_` stripped) and same image repository | medium | `homeassistant` ↔ `home-assistant`. |
| Same published host port + protocol, or same network alias | weak | Shown in the comparison only; never a trigger (ports differ by host, aliases repeat across stacks). |

`image_name` alone (`models.py:86`) is not used: it is the short repo name and collides
(`postgres`). `image_ref` (`models.py:91`) is the canonical form. Several O for one N: all are
listed, ranked by evidence; the notice shows the best one.

**Active-active** (both sides fresh and running) is never a candidate. When one side dies it
becomes one; that is the FUTURE.md "useful false positive", answered by Dismiss.

### 2.3 When it is computed

- **At register time, only when a new row is created** (the `else` branch,
  `routes_api.py:330-373`), after the flush, inside `_UPSERT_LOCK`. DB only, no network. One
  query over active notifier rows (tens to hundreds; no index needed, but the query is bounded
  to `source = notifier AND deleted_at IS NULL`). The result is stored, not recomputed per page.
- **On demand:** opening Settings → Duplicates, and `POST /api/v1/duplicates/scan`, rescan all
  active notifier rows (dict buckets by name, image repo, hostname: O(n), not O(n²)) and
  upsert open matches. This catches O going stale after N was created (notifier on docker01
  down, not "exited").
- **No background job.** The two triggers cover it; a job would only find pairs nobody looks at.
- A match whose eligibility no longer holds (O came back and is running, or either row was
  deleted) is dropped on the next scan or register of either row.

### 2.4 Storage: table `entry_match`

Same shape as `stream_link_offer` (`models.py:931-952`):

| Column | Notes |
|---|---|
| `id` | |
| `new_entry_id` FK `service_entry.id` ON DELETE CASCADE, indexed | |
| `old_entry_id` FK `service_entry.id` ON DELETE CASCADE, indexed | |
| `kind` | `move` / `rename` |
| `reasons` JSON | evidence list, for the notice and comparison |
| `status` | `open` / `merged` / `dismissed` |
| `created_at`, `resolved_at`, `resolved_by` (username or API key name) | |
| `snapshot` JSON | on merge: the losing values of every field that changed (§2.7, Q11) |

Unique `(new_entry_id, old_entry_id)`. FK indexes in the same migration (CLAUDE.md Database
Rules). Rows survive as the record of merges and dismissals.

### 2.5 Where it surfaces

- **Notice on N's Edit page**, the link-offer shape (`templates/edit_entry.html:10-30`):
  "Looks like `foo` on docker01 (stale since 10:42): same image, same hostname. **Move here** /
  **Not the same**". O's Edit page gets the mirror notice ("may have moved to docker02").
- **Settings → Duplicates** (new section in `settings_sections.py`): open matches, side-by-side
  comparison (§2.7 table, differing fields only), Merge, Not the same; a "Resolved" list below.
- **Count badge** on the Settings nav, as the streams section does for offers
  (`templates/settings.html:32-36`). One `COUNT(*)` of open matches per Settings render.
- **Dashboard views:** a small "possible move" marker on N and O is optional (Q9). If built, it
  comes from **one** query of open-match entry ids per page, never per row.
- **Management API / MCP:** `GET /duplicates`, `POST /duplicates/scan`,
  `POST /duplicates/{id}/merge`, `POST /duplicates/{id}/dismiss`. MQTT: none (no new topic).

### 2.6 Dismiss

"Not the same" sets `status = dismissed`. That pair is never offered again (the scan skips
it). A third host appearing is a new pair. No "intentionally replicated" flag (still YAGNI,
FUTURE.md:205-208).

### 2.7 Merge: keep O's id (recommended), absorb N

**Two options:**

| | A: merge into N, soft-delete O | **B: O survives, takes N's key and observations; N soft-deleted** |
|---|---|---|
| HA device / entity ids | change (device `<node>_entry_<id>`): HA automations and history break | **unchanged** |
| MQTT topics | move to N's id | **unchanged** |
| Health history, uptime bars | re-parent O's checks to N (history follows the check FK, `models.py:573-576`) | **stays put** (O's checks) |
| Widget, widget values | re-point `widget_id` | **stays put** |
| Work | re-parent many rows | update one row, move N's few rows |
| Loser | O (old key) soft-deleted: a later register for docker01/foo **resurrects it** (`routes_api.py:243-248`) | N (same key as the survivor): register prefers the active row (`routes_api.py:221`); a restore of N is refused by the clash check (`routes_mgmt_api.py:884-889`, `routes_dashboard.py:1990-1993`) |

**Recommend B** (Q1). N is minutes old and holds almost nothing the operator made; O holds
everything. Both options soft-delete the loser, so Settings → Deleted keeps it until the purge.

**Field by field (B), in one transaction under `_UPSERT_LOCK`:**

| Field(s) | Survivor (O) gets | Rule |
|---|---|---|
| `host`, `container_name` | N's | The new key. |
| Observation: `container_id`, `docker_status`, `started_at`, `stack_name`, `image_registry/owner/name/tag/ref`, `image_running_digest`, `image_info`, `networks`, `exposed_ports`, `published_ports`, `last_api_update`, `last_updated`, `notifier_reported_*`, `attributes` | N's | Pure observation; N's is current. |
| Exposures (`service_exposure`) | N's rows re-parented, O's deleted | Then `synthesizer.synthesize_for_entry` (`synthesizer.py:148`). |
| URLs | by provenance (§5) | O's `ui_edit` kept; otherwise N's `explicit_label`/synthesized value. |
| `group`, `sort_priority`, `image_icon`, `description`, `image_repo_url`, `image_update_policy/scope`, `image_tag_pattern` | by provenance (§5) | |
| Image update state (`image_update_state/latest/kind/since/provider/detail`) | recomputed | `image_update.apply_register(entry, …, old_ref)` (`image_update.py:212`) with O's old ref, then nudge. |
| `ha_publish` | O's, OR'ed with N's | Operator-owned, register never writes it (`models.py:185-187`). |
| Widget | O's; N's only if O has none | A losing widget stays on N and detaches at purge (`models.py:827-836`). |
| URL checks (rows) | O's rows; enabled/settings by provenance per check (§5) | Keeps check ids, history, HA entities. |
| Container check | O's row; `last_ok` reset, run requested (`jobs.request_run`) | |
| Service checks | O's kept; N's (if the operator added any) re-parented to O | |
| N's check history | dropped with N | Minutes of data. |
| `is_static`, `source` | unchanged | Both unlocked notifier rows by eligibility. |
| Other open matches | those naming N deleted; those naming O re-evaluated | |

**MQTT / Home Assistant:** nothing special to call. O's `host` change is in `_ENTRY_ATTRS`
(`notify_state.py:60`), so the commit listener requests a sync that republishes O's payloads; N's
`deleted_at` takes it out of `_active_entries()` (`notify_state.py:298-302`), so `full_sync`
clears its state topics and `sync_discovery` clears its discovery configs
(`notify_state.py:490-540`), which removes N's HA device if it had `ha_publish`. A test asserts
both.

**Audit:** the management API merge/dismiss writes an `ApiAudit` row via `audit()`
(`routes_mgmt_api.py:293-309`) with the changed fields. UI writes are not audited today (the log
is API-only, `templates/partials/settings/audit_log.html:3`); the `entry_match` row
(`resolved_by`, `snapshot`) plus an INFO log line is the UI record. Not a new audit mechanism.

**Undo:** none beyond the soft-deleted N. `snapshot` keeps O's overwritten values for manual
repair (Q11).

### 2.8 Rename

Same flow, `kind = rename`: same host, different name, evidence from stack + image, hostname or
URL (§2.2). The merge rewrites O's `container_name`. Recommend in scope (Q10); it costs one rule
row.

## 3. Per-field provenance

### 3.1 Which fields

| Field | Where | Label today | Label in rev 8 |
|---|---|---|---|
| `internalurl`, `externalurl` | `service_entry` | yes | unchanged (already have provenance, `models.py:161-162`) |
| `image_icon` | `service_entry` | yes (`.icon`) | |
| `group_id`, `sort_priority` | `service_entry` | yes | (replaces `register_field_ownership`, §3.4) |
| `description` | `service_entry` | | yes |
| `image_update_policy`, `image_update_scope`, `image_tag_pattern` | `service_entry` | | yes |
| `image_repo_url` | `service_entry` | | yes |
| URL check `enabled` | `health_check` (internal/external rows) | yes (`.internal.health`) | |
| URL check settings (`mode`, `interval_seconds`, `timeout_seconds`, `verify_tls`, `cert_min_days`) | `health_check` | | yes |

Not given provenance: `ha_publish`, `ha_exclude`, `is_static`, widget, service checks (operator
only, register never writes them); observation columns (no ownership, CLAUDE.md).

### 3.2 Storage: `<field>_source` columns (recommended)

- `service_entry`: `image_icon_source`, `group_source`, `sort_priority_source`,
  `description_source`, `image_repo_url_source`, `image_update_policy_source`,
  `image_update_scope_source`, `image_tag_pattern_source` (String(16), nullable).
- `health_check`: `enabled_source`, `settings_source` (the five settings travel as one object
  from a label and one form from the UI, so one source covers them).
- Values: `ui_edit`, `explicit_label`, NULL (auto). URLs keep `synthesized` too.

**Why columns, not one JSON map:** the existing pattern is columns (`internalurl_source`,
`externalurl_source`, `name_source`, `models.py:161-162`, `204`), the field set is closed and
small, the export already models a source per value (`UrlValue`, `export_format.py:135-137`),
and a JSON column needs reassign-on-write to be tracked. A JSON map would only win if label
fields arrived without migrations; every rev-8 field already has its value column.

**Migration (one, phase a), with backfill:**

| Column | Backfill |
|---|---|
| `description_source`, `image_repo_url_source` | `ui_edit` where the value is non-NULL (register never wrote them) |
| `image_update_*_source` | `ui_edit` where policy ≠ `auto` / scope or pattern non-NULL |
| `group_source` / `sort_priority_source` | Docker rows: `explicit_label` if equal to `notifier_reported_*`, `ui_edit` if different or nothing reported; manual/stream rows: `ui_edit` where set |
| `image_icon_source` | Docker rows: `ui_edit` if the icon ≠ the derived `<image name>.svg` (`image_utils.py:128-133`, `safe_icon_filename`), else NULL; manual/stream: `ui_edit` where set (Q7) |
| `settings_source` | `ui_edit` where any setting is non-default (register never wrote them) |
| `enabled_source` | NULL: no record of what the notifier sent, and today's register overwrites it anyway |

### 3.3 The rules

One helper (`provenance.py`, pure) used by register, UI, management API, importer and merge:

1. **A UI edit wins.** UI and management API writes set `ui_edit`, **only for fields whose
   value actually changed** (the `entry_rules.set_url` pattern, `entry_rules.py:153-166`).
   Today the Edit form rewrites the icon on every save (`routes_dashboard.py:1566-1576`); with a
   blanket rule, saving a description would freeze the icon.
2. **A label writes only when the source is not `ui_edit`**, and sets `explicit_label`.
3. **Auto** (derived icon, synthesized URL, default) writes only when the source is NULL (or
   `synthesized` for URLs).
4. **Absent means leave alone.** Detected with `payload.model_fields_set`, never `in canonical`:
   `canonical = payload.model_dump()` (`routes_api.py:435`) puts every key in the dict.
   - Today `key in canonical` at `routes_api.py:287` is always true; it only works because
     `parse_bool(None)` is None (`image_utils.py:94-99`).
   - **Flag (trust the code):** `routes_api.py:311-316` therefore clears `networks` /
     `exposed_ports` / `published_ports` when a payload omits them, despite the comment.
     Harmless with today's notifier (it always sends them) and consistent with the
     safe-degradation rule, but phase (a) switches these to `model_fields_set` too and a test
     pins it.
5. **Explicit `null` from a label-aware producer clears a label-owned value** (rev 8, §4.2):
   when the field is in `model_fields_set`, the value is null, and the source is
   `explicit_label`, the field returns to auto (source NULL, value NULL / default / re-derived).
   A `ui_edit` value is untouched; a NULL-source value is untouched. This fixes "a removed URL
   label sticks forever" (notifier-labels §4) without guessing (Q4).
   - **Exception, toggles:** a removed `.health` label drops ownership (source NULL) but keeps
     the current `enabled` value, so no check turns itself off (Q5).
6. **Clearing a field in the UI resets it to auto** (source NULL), as URLs already do (PRD
   §8.7). The one exception is group: the Edit page gets "No group (keep ungrouped)", which
   stores NULL with `ui_edit`. That fixes the FUTURE.md "deliberately ungrouped" bug.
7. **Reset to label/auto:** each provenance-carrying field on the Edit page shows a small badge
   (`set in UI` / `from label` / `auto`) and, when `ui_edit`, a **Reset** link. Reset = rule 6
   (source NULL, value cleared); the next register refills it from the label or auto. The
   management API takes `"reset": ["icon", "description", …]` on `PATCH /entries/{id}` (and
   `reset: true` on the URL check settings), and `EntryOut` / `CheckOut` gain a `sources` map.
8. **Locked entries** stay as today: register skips them entirely (`routes_api.py:227-232`).

### 3.4 `register_field_ownership`

Today it governs only group and sort (`routes_api.py:318-329`, validated at `app.py:134-145`).
Under provenance:

- `user_wins` (default) = the rules above. Behaviour change: a NULL group no longer means
  "unset" when the operator chose "No group".
- `notifier_wins` = labels beat `ui_edit` for group and sort only (today's behaviour).
  **Deprecated** in 0.14.0 with a startup warning; removed in a later minor (Q6). The importer
  warning at `importer.py:1399` stays until removal.
- The `notifier_reported_*` capture columns stay (the importer reads them,
  `importer.py:756-764`).

### 3.5 Fixing the existing clobbers

- **Icon** (`routes_api.py:298-299`, the derived icon from `image_utils.py:128-133`): write
  `image_icon` only when `image_icon_source` is not `ui_edit`. A payload `image_icon` (label)
  sets `explicit_label`; a derived icon writes only when the source is NULL. The icon download
  in `resolve_image_metadata` still runs before the lock (cached on disk); skipping it for
  `ui_edit` rows is an optimisation, not required.
- **Toggles** (`routes_api.py:285-290`): write `enabled` only when the check's `enabled_source`
  is not `ui_edit`; set `explicit_label` when written. UI toggles (`check_form.apply_rows`,
  `check_form.py:527`) and the API (`check_form.apply_check_values`, `check_form.py:565`) set
  `ui_edit` on change.
- **New rows** (`routes_api.py:366-369`): an absent toggle produces `enabled = False`, which is
  the same as `ensure_url_checks`' default (`models.py:395-412`); the value is fine, but it must
  record source NULL, not `explicit_label`, so a merge (§5) or a later label treats it as
  "nobody chose". Only a toggle in `model_fields_set` gets `explicit_label`.
- **Adopted manual rows** (`routes_api.py:234-241`): their operator values are `ui_edit` by
  the backfill (manual rows) or by the Add page, so adoption no longer lets labels overwrite
  them. This is a behaviour change (today labels overwrite an adopted row's toggles and icon);
  CHANGELOG says so.

### 3.6 Export and import (PRD §20.2)

- **Entry fields:** keep the existing rule, made general: a Docker entry exports a field only
  when its source is `ui_edit` (today URLs, `export_format.py:270-280`; the icon only when
  locked, `export_format.py:300`). Manual and stream entries export every set field, as today.
  Label-owned values are not exported: compose re-supplies them at the next register, and
  importing them would turn them into `ui_edit` and freeze them.
- **Import writes `ui_edit`** for every entry field it sets (it is operator state), including
  the icon, now that an imported icon survives register.
- **Checks** are exported whole (`CheckRecord`, `export_format.py:155-170`). Add optional
  `enabled_source` / `settings_source` to `CheckRecord`; import restores them, so a label-owned
  toggle stays label-owned. Older files lack them: import treats them as `ui_edit` when the value
  differs from the default, else NULL.
- Format stays `format_version: 1`: the readers are lenient (`extra="allow"`,
  `export_format.py:11-13`), additions are optional. Legacy (format 0) import unchanged.
- `entry_match` rows are not exported (they describe this install's rows).

## 4. New register fields and labels (API revision 8)

### 4.1 Fields

All optional, all non-strict like the rest of `RegisterPayload` (labels arrive as strings), all
validated by the same functions the management API uses. Provenance per §3.3.

| Label | Payload key | Type | Validation (shared with) | Clear (rev 8 null) resets to |
|---|---|---|---|---|
| `dockernotifier.std.description` | `description` | str | ≤ 255 (`entry_rules.validate_basic`, `entry_rules.py:35-47`) | NULL |
| `dockernotifier.std.image_update.policy` | `image_update_policy` | str | `auto`/`tags`/`digest`/`off` (`image_tags.POLICIES`, `image_tags.py:15`; API at `routes_mgmt_api.py:738-742`) | `auto` |
| `dockernotifier.std.image_update.scope` | `image_update_scope` | str | `any`/`minor`/`patch` (`image_tags.SCOPES`, `image_tags.py:16`) | NULL (global default) |
| `dockernotifier.std.image_update.tag_pattern` | `image_tag_pattern` | str | `image_tags.validate_tag_pattern` (`image_tags.py:154`) | NULL |
| `dockernotifier.std.image_repo_url` | `image_repo_url` | str | http(s), ≤ 512 (`entry_rules.validate_image_repo_url`, `entry_rules.py:70-78`) | NULL (derived link) |
| `dockernotifier.std.internal.check.<setting>` / `.external.check.<setting>`, settings `mode`, `interval`, `timeout`, `verify_tls`, `cert_min_days` | `url_checks: {internal: {...}, external: {...}}` | nested model, `extra="forbid"`, fields as `mgmt_schemas.UrlCheckSettings` (`mgmt_schemas.py:137-146`) **minus `enabled` and `ha_exclude`** | ranges via `check_form.validate_url_check_settings` (`check_form.py:280-306`): interval 30-86400, timeout 1-60, cert 1-365 | each setting NULL / default |
| `dockernotifier.std.attr.<k>` | `attributes` | dict | `streams.check_attributes` (`streams.py:145`): ≤ 32 keys `^[A-Za-z0-9_.-]{1,64}$`, scalar values ≤ 256 chars | n/a: observation, overwritten when present |

Notes:

- **Validation failure is a 400 for the whole payload**, like every register field today. The
  notifier must therefore validate before sending (§4.3), or one bad label stops that container
  registering. Alternative (Q15): STD drops an invalid label field with a warning instead. Recommend
  400, consistent with `extra="forbid"`, plus notifier-side validation.
- `enabled` stays on the existing flat keys (`internal_health_check_enabled`), not inside
  `url_checks`: no second way to say the same thing.
- `url_checks.<which>` as a unit owns `settings_source`; a label object that sets only
  `interval` still owns the whole settings group (the other settings keep their values).
- `attributes` reuses the existing column (`models.py:200`, stream entries today). Display
  only, never read in logic (the stream rule). Docker entries show it in the details panel.
  No provenance: pure observation. Absent leaves it alone; `{}` clears it.
- `image_update_*` written by a label nudges the image check as a policy change does today.

### 4.2 Revision and feature flag

- `API_REVISION = 8` (`api_version.py:9`), one row in `API_REVISION_HISTORY` and the PRD §18.1
  table: the register fields above, the rev-8 null semantics, `sources` / `reset` in the
  management API (§3.3), and the duplicates endpoints (§2.5). One row for the release, as
  revision 5 and 6 did (`docs/decisions.md`, 2026-11-22 entry).
- **One feature flag `label_settings`** in `FEATURES` (`api_version.py:38-39`) for the register
  side, and `duplicates` for the management API. One flag is enough because STD ships all rev-8
  register fields together; a later field gets its own flag.
- **The null semantics are part of `label_settings`.** A producer that advertises nothing new
  (older notifier) never sends null for these keys (`_to_canonical` only copies present labels,
  `notifiers/service_tracker_dashboard.py:112-152`), so absent stays "leave alone".

### 4.3 Notifier 0.7.0 follow-up (ships after STD 0.14.0)

Consumer leads, producer follows (CLAUDE.md ordering rule). A notifier prompt, written when STD
0.14.0 is tagged:

- **Gate:** send any rev-8 key only when `feature_supported("label_settings")` (the per-feature
  gate 0.6.0 adds). Unsupported: drop them with one log line, as for `network_details`.
- **Map labels:** add the keys to `_PASSTHROUGH` / `_LEGACY_TO_CANONICAL`
  (`notifiers/service_tracker_dashboard.py:20-57`); build `url_checks` from
  `internal.check.*` / `external.check.*`; build `attributes` from `attr.*`.
- **Validate locally** with the same limits (§4.1); an invalid label is dropped with a warning,
  never sent.
- **Send null for a removed label:** on every register to a `label_settings` STD, every
  label-capable key the notifier knows (the rev-8 keys plus `internalurl`, `externalurl`,
  `image_icon`, the two toggles, `group_name`, `sort_priority`) is sent: the value, or `null`
  when the label is absent. That is what lets STD clear a label-owned value (§3.3 rule 5).
- **Rejection retry:** a 400 blaming a rev-8 key marks `label_settings` rejected, per the 0.6.0
  mechanism.

## 5. How the two parts interact

**Merge applies provenance field by field** (§2.7 rows "by provenance"):

1. The higher source wins: `ui_edit` > `explicit_label` > `synthesized` > NULL.
2. Tie on `ui_edit`: **O's** value (the long-lived operator choice), unless the operator flips it
   on the comparison screen.
3. Tie on `explicit_label` or NULL: **N's** value (it is what compose says now).
4. The survivor's `<field>_source` becomes the winner's source.

So **a label on N does not beat a UI value on O**: that would break "a UI edit always wins".
The comparison screen shows it ("label on docker02 says `Media`; your UI edit `Apps` is kept;
Reset after the merge to hand it to the label"). The comparison preselects each differing
field's winner by these rules and lets the operator flip any of them (only differing,
operator-settable fields are listed; usually 0-3 rows) (Q2).

Labels also shrink the problem: settings kept in compose follow the container, so after a
move N already carries them and the merge has little to decide.

## 6. Phasing

Each phase is one Sonnet build prompt, one session, one commit with its docs. Phases a1→a2→b→c1→c2
in that order; the release is 0.14.0 after c2. The notifier 0.7.0 prompt follows the tag.

| Phase | Scope | Tests (highlights) | CHANGELOG / PRD |
|---|---|---|---|
| **a1 `prov-01`** provenance core | Migration (columns + backfill + nothing else); `provenance.py`; register rules incl. `model_fields_set`; icon and toggle fixes; group/sort onto provenance, `notifier_wins` deprecation warning; UI/API writes set `ui_edit` on change only | Icon chosen in UI survives N registers; derived icon still fills NULL; UI-disabled check stays off with label `true`; label still drives a NULL-source toggle; new-row absent toggle has NULL source; saving the Edit page unchanged sets no source; "No group" survives `user_wins`; `notifier_wins` keeps today's behaviour; absent `networks` no longer clears; migration backfill cases; adopted manual row keeps its icon | Fixed: icon and toggles no longer overwritten; Changed: adopted manual entries keep their settings; Deprecated: `notifier_wins`. PRD: §8.7 generalized to all provenance fields, §5.4 schema, new §26 |
| **a2 `prov-02`** provenance surfaces | Edit page badges + Reset; `sources` in `EntryOut`/`CheckOut`; `reset` on PATCH; export rule and `CheckRecord` sources; import writes `ui_edit`; MCP passes through | Reset then register refills from label; API `sources` values; export omits label-owned values, keeps `ui_edit`; round trip of check sources; old export file defaults; OpenAPI registry lists the change (`mgmt_openapi.py` test) | Added: "set in UI / from label" badges and Reset. PRD: §20.2, §14 entries, §26 |
| **b `labels-01`** rev-8 register fields | Schema fields + nested `url_checks` model (`extra="forbid"`); shared validators; rev-8 null clearing (§3.3 rule 5); `API_REVISION = 8`, `label_settings`; docs/register-api.md label table | Each field: absent leaves alone, value writes `explicit_label`, `ui_edit` blocks it, null clears only `explicit_label`; toggle null keeps value; unknown nested key 400; invalid policy/pattern/URL/interval 400 with the API's message; `attributes` limits; `/meta` lists `label_settings`; older-notifier payload unchanged behaviour (safe degradation) | Added: description, image update, repo link, check settings and attributes from labels (needs notifier 0.7.0). PRD: §18.1 row 8, §22 contract, §26 |
| **c1 `moves-01`** detection | `entry_match` table + migration (FK indexes); rules engine (pure, from rows); register-time hook; Settings → Duplicates list (read-only) + nav badge; notices on both Edit pages; `GET /duplicates`, `POST /duplicates/scan` | Each evidence rule; eligibility (locked, manual, stream, deleted, active-active excluded); exited-but-fresh O counts; dismissed pair not re-offered; scan is O(n) (bucket test); **query-count guard: Dashboard, Tiled and Compact issue a constant number of queries for 10 vs 50 entries with open matches**; Settings badge is one query; register with no twin adds no match | Added: possible-move detection. PRD: §26, §19 sections list |
| **c2 `moves-02`** merge and dismiss | Merge (option B) per §2.7 + §5 with per-field flips; dismiss; `snapshot`; MQTT/HA effects; `POST /duplicates/{id}/merge`, `/dismiss`; MCP tools; FUTURE.md sections removed | Field table row by row; survivor keeps id, check ids, history, widget; N soft-deleted and restore refused; N's service checks re-parented; exposures re-synthesized; image state recomputed; HA: N's configs cleared, O's republished with new host (publisher stub); audit row via API; merge refused when eligibility no longer holds (409) | Added: merge a moved container into its old entry, keeping history and HA devices. PRD: §26, §17 note, §18.1 (already in row 8) |

Sizing note: if a1 runs long, split the group/sort move to `notifier_wins` into its own prompt.

## 7. Open questions for the operator

1. **Merge survivor.** Keep the old entry's id and re-point it (B), or merge into the new row
   (A)? **Recommend B:** HA devices, MQTT topics, check history and the widget stay intact.
2. **Merge conflicts.** Provenance order with ties to O for `ui_edit` and to N for labels/auto,
   plus a per-field flip on the comparison screen? **Recommend yes.** Alternative: no flips, the
   rules decide.
3. **Auto-flag the old row?** **Recommend no state change** (checks, HA "down" stay real); only
   the notices and the badge. Alternative: mute O's HA entities while a match is open.
4. **Removed label clears its value** (explicit null from a `label_settings` producer, only when
   the source is `explicit_label`), including the existing URL, icon, group and sort keys?
   **Recommend yes**; it is the only clean fix for "a removed URL label sticks forever".
5. **Removed `.health` label:** keep the check's current on/off and drop ownership, or turn it
   off? **Recommend keep the value.**
6. **`register_field_ownership: notifier_wins`.** Deprecate in 0.14.0 and remove later, or
   remove now? **Recommend deprecate**; it is a settings.yml key someone may set.
7. **Icon backfill.** Mark a Docker entry's icon `ui_edit` when it differs from the derived
   `<image>.svg`? It may be a label icon, which then freezes until Reset. **Recommend yes**: a
   frozen label icon is visible and one click to fix; a clobbered UI icon is lost.
8. **Staleness for candidates.** Reuse `stale_after_minutes` (default 5) plus "not running", or a
   looser duplicates-only threshold? **Recommend reuse** (FUTURE.md:236-238 leaned the same way).
9. **Dashboard marker.** A "possible move" marker on rows in the three views (one extra query
   per page), or only the Edit notices and the Settings badge? **Recommend notices + badge
   only** for 0.14.0; add the marker if moves go unnoticed.
10. **Renames in scope?** **Recommend yes**, same flow, `kind = rename`.
11. **Undo.** Accept "no undo" with the `snapshot` of overwritten values kept on the match row?
    **Recommend yes**; a real undo would have to reverse re-parented rows and HA republishes.
12. **Export of label-owned values.** Omit them (compose re-supplies them), or export with their
    source? **Recommend omit**, as URLs already do.
13. **Settings badge from day one.** FUTURE.md said start without one; the streams section
    already badges link offers. **Recommend a badge.**
14. **One feature flag** `label_settings` for all rev-8 register fields, or one per field?
    **Recommend one**, new flags for later fields.
15. **An invalid label value:** 400 the whole register (today's contract), or STD drops the
    field with a warning? **Recommend 400** plus notifier-side validation in 0.7.0.
