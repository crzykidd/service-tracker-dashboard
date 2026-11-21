# Service Tracker Dashboard (STD) — Product Requirements Document

> **Status:** living document. Update alongside any change that affects
> architecture, the register contract, schema, jobs, or supported
> dashboard views.

## Revision History

| Version | Date       | Changes |
|---------|------------|---------|
| 0.1     | 2026-05-10 | Initial PRD. Documents current shipped behavior at v0.4.14 and the planned v0.5.0 cleanup. |
| 0.2     | 2026-05-13 | Added §8 (v0.5.x — view controls + grouping/sorting helper consolidation). Corrected §6.2 D2 row: the v0.5.0 entry claimed the helper consolidation was resolved, but it was deferred — the work actually lands in v0.5.x. |
| 0.3     | 2026-05-13 | v0.6.0 delivered. Removed /api/register compat shim. Added §5.3 (v0.6.0 schema additions: networks, exposed_ports, published_ports). §9 rewritten from "planned" to "delivered." Added §10 (v0.7.0 — interpreter / exposure synthesis, planned). |
| 0.4     | 2026-05-13 | Exposure interpreter mechanism folded into v0.6.0 rather than shipping as a separate v0.7.0 release. §9 expanded with §§9.4–9.8 (wire contract, synthesizer, URL provenance, per-interpreter settings, badges + headless rendering). New §5.4 documents the v0.6.0 schema additions for the interpreter (`service_exposure`, two URL source columns on `service_entry`, `setting` table). §10 retired (no scoped features for the next release). |
| 0.5     | 2026-05-14 | v0.6.0 released. The originally-planned v0.5.x (view controls + helper consolidation), v0.6.0 (compat shim removal + capture columns), and v0.7.0 (exposure interpreter) work shipped together as a single v0.6.0 release. Former §8 (v0.5.x planning) folded into the new §8 (Delivered in v0.6.0). §6.2 D2 marked Resolved in v0.6.0. Cross-repo coordination (now §10.2) collapsed the v0.3.2 / v0.4.0 notifier split into a single notifier v0.4.0 pairing. Later sections renumbered: §10/§11/§12 → §9/§10/§11. |
| 0.6     | 2026-05-16 | v0.6.1 delivered. UI overhaul part 1: tiled drawer, Tabler Icons v3.34.0 icon vocabulary, per-template inline CSS/JS extracted to shared static files. §9 added. |
| 0.7     | 2026-05-16 | v0.6.2 hotfix. Restored `toggleRestoreSource` dropped during v0.6.1 JS extraction; wired file-input change event for filename feedback on /settings restore. |
| 0.8     | 2026-05-17 | v0.6.3–v0.6.6 UI Overhaul Part 2 arc delivered. Added §10 documenting v0.6.3 foundations, v0.6.4 mobile/tile restructure, v0.6.5 edit polish/delete UX/widget modal, and v0.6.6 widget drawer mode + brand exposure icons (modal removed). |
| 0.9     | 2026-05-23 | Documentation reconciliation audit. §9.6 forecast rewritten — the predicted v0.6.2 edit drawer / v0.6.3 staleness work did not ship; the actual v0.6.2–v0.6.6 arc is described in §10. §12 subsection numbering corrected (was using §10.x). §12.2 release history split notifier v0.3.2 (capture fields) from v0.4.0 (interpreters). FUTURE.md fictional release sequence references stripped. No code or schema changes. |
| 0.10    | 2026-05-23 | §12.2 correction. The v0.3.2 / v0.4.0 split introduced in 0.9 was wrong — notifier tags confirm no v0.3.2 release was ever cut; the capture fields and the interpreter mechanism both shipped in v0.4.0. Collapsed back to a single v0.4.0 pairing, with a parenthetical noting v0.3.2 as a developed-but-unreleased label so a future reader doesn't re-split from the stale `models.py` / `schemas.py` comments. |
| 0.11    | 2026-11-15 | v0.6.7 — registry move. §11 documents GHCR as the primary image registry and the final dual-publish to Docker Hub with the `REGISTRY_NOTICE` build arg driving the in-app deprecation banner. Workflow renamed `dockerhub.yml` → `publish.yml`. No schema, contract, or job changes. |
| 0.12    | 2026-11-15 | §11 documents the `CI` required checks and GHCR registry retention (adoption of `code-checkin-and-pr` v1.2.0). No schema, contract, or job changes. |
| 0.13    | 2026-11-15 | §11: versioning now uses a bare-semver `VERSION` file (Dockerfile writes `/app/version.txt` from it; `APP_VERSION` build arg removed) and releases are cut with `/release-prep` + `/release-cut` (adoption of `release-prep-and-cut` v1.1.0). No schema, contract, or job changes. |
| 0.14    | 2026-11-15 | §11: Docker Hub publishing removed; GHCR is the only registry (Docker Hub frozen at v0.6.7). The `REGISTRY_NOTICE` build arg, `registry_notice=` line in `/app/version.txt`, and in-app "moved to GHCR" banner were removed. No schema, contract, or job changes. |
| 0.15    | 2026-11-15 | v0.6.8 released. First release under the adopted standards (code-checkin-and-pr 1.2.0, handoff-prompt-workflow 2.0.0, release-prep-and-cut 1.1.0); GHCR-only publishing; `VERSION` file drives the in-app version; Add Entry non-numeric sort-priority 500 fixed. No schema or contract changes. |
| 0.16    | 2026-11-15 | Docs refresh after the standards adoption. Added §11 (v0.6.7–v0.6.8 registry move and engineering standards); later sections renumbered (§11→§12, §12→§13, §13→§14). §3.1 module layout updated to the current tree. §6 retitled as a historical baseline. No code, schema, or contract changes. |
| 0.17    | 2026-11-15 | Added §12 (v0.6.9 — Hardening and Safety Net, planned): test suite, wider lint, settings/API-token fixes, CSRF, soft-delete, widget detach, unified staleness, per-service health-check options, gunicorn + pinned deps, docs loose ends. Later sections renumbered (§12→§13, §13→§14, §14→§15). §15 Open Questions refreshed. No code changes yet. |
| 0.18    | 2026-11-15 | §12.1 delivered (unreleased): pytest suite, `STD_CONFIG_DIR` testability seam, CI `Test` job; §13 required-checks text updated. No schema, contract, or job changes. |
| 0.19    | 2026-11-15 | §12.2 delivered (unreleased): `ruff.toml` widened to `E, W, F, I, B` (E501 ignored); §3.1 lint note updated. No schema, contract, or job changes. |
| 0.20    | 2026-11-15 | §12.3 delivered (unreleased): `widget_value_retention_days` / `register_field_ownership` now load; unset `api_token` returns 503 on register; constant-time token compare; token masked in logs; default-credential warnings. No schema or wire-contract changes. |
| 0.21    | 2026-11-15 | §12.4 delivered (unreleased): Flask-WTF `CSRFProtect` on all UI POSTs and fetch calls; `/api/v1/register` exempt; `CSRFError` handler (flash+redirect or JSON 400). No schema or wire-contract changes. |
| 0.22    | 2026-11-15 | §12.5 delivered (unreleased): soft-delete (`service_entry.deleted_at`, §5.5), Settings → Deleted tab, `deleted_retention_days` and the 00:25 purge job, resurrect-on-register, `deleted_at` in YAML backups. Wire contract unchanged. |
| 0.23    | 2026-11-15 | §12.6 delivered (unreleased): hard delete keeps the widget and its values as a detached widget; Settings → Deleted lists detached widgets with Attach/Delete; refresh job skips detached widgets. No schema or wire-contract changes. |
| 0.24    | 2026-11-15 | §12.7 delivered (unreleased): `stale_after_minutes` setting (default 5) drives `is_docker_status_stale`; Tiled 120-minute clause removed; stale icon added to Dashboard and Compact. No schema or wire-contract changes. |
| 0.25    | 2026-11-15 | §12.8 delivered (unreleased): `health_check_timeout` setting; per-service `health_check_timeout` / `health_check_verify_tls` columns (§5.5) editable on Edit and Add; backups round-trip both. Wire contract unchanged. |
| 0.26    | 2026-11-15 | §12.9 delivered (unreleased): production runs gunicorn (one worker, four threads) via `gunicorn.conf.py`; startup work consolidated in `app.run_startup_tasks()`; `requirements.txt` fully pinned from `requirements.in`. §3 architecture and module layout updated. Wire contract unchanged. |
| 0.27    | 2026-11-15 | §12.10 delivered (unreleased): CHANGELOG historical dates corrected from tags; MIT `LICENSE` added; README compatibility note and registry wording refreshed. No code, schema, or wire-contract changes. |
| 0.28    | 2026-11-15 | v0.6.9 released. §12 retitled Delivered: pytest suite + required `Test` check, wider lint, settings and API-token fixes, CSRF protection, soft-delete with widget detach, unified staleness indicator, per-service health-check options, gunicorn + pinned dependencies. Schema: `deleted_at`, `health_check_timeout`, `health_check_verify_tls` (§5.5). No register-contract change. |
| 0.29    | 2026-11-15 | §12.11 added (delivered in v0.6.9, folded into the prepared release): icon names, server-side restore filenames and `/widget_config` widget names confined to their folders; edit/CSRF redirects limited to same-site paths (`image_utils.safe_icon_filename`, `view_helpers.safe_redirect_target`). Closes 13 CodeQL alerts. No schema, contract, or job changes. |
| 0.30    | 2026-11-15 | Added §13 (v0.7.0 — Dashboard and Monitoring, planned): entry sources (notifier vs manual), health checks as their own tables with service checks (HTTP/HTTPS status or body mode, TCP, ping), concurrent checker, 7-day history with 24h raw + hourly-compacted successes, health rollup and status/source filters, Gatus-style 24h history in the detail surface. Planned schema in §5.6. Later sections renumbered (§13→§14, §14→§15, §15→§16). No register-contract change. No code changes yet. |
| 0.31    | 2026-11-15 | §13.2 delivered (unreleased): `service_entry.source` / `description` / nullable `host` (migration `a7c3e9f15d28`, §5.6), register adoption of unlocked manual entries, manual-only Add page, source icon on Dashboard and Tiled, backups carry `source`/`description`. Lock relabelled "Lock (ignore notifier updates)". Register wire contract unchanged. |
| 0.32    | 2026-11-15 | §13.3 delivered (unreleased): `health_check` / `health_result` tables and models (migration `b8e4d6a2c1f9`, §5.6) with the two URL-kind rows per entry copied from the legacy columns; register toggles, Add/Edit and backup/restore read and write the rows; the interim sequential checker records results and mirrors into the legacy status columns until §13.5. Register wire contract unchanged. |
| 0.33    | 2026-11-15 | §13.4 delivered (unreleased): concurrent checker (`checker.py` probes for HTTP status/body, TCP and ping via pinned `icmplib`; `jobs.HealthScheduler`), settings `health_check_workers` / `health_raw_hours` / `health_history_days`, hourly compaction and purge jobs for `health_result`, `POST /service/<id>/checks/run`. No schema change. Register wire contract unchanged. |
| 0.34    | 2026-11-15 | §13.5 delivered (unreleased): "Health checks" section on Add and Edit (per-URL-check enabled/mode/interval/timeout/verify, repeatable service checks of type HTTP, TCP, Ping), server-side validation with input kept, flash messages on Add/Edit. No schema change. Register wire contract unchanged. |
| 0.35    | 2026-11-15 | §13.6 delivered (unreleased): `health_state.py` rollup (up/degraded/down/unknown/none), shared `health_badge.html` on Dashboard (new Health column), Tiled and Compact, `status` / `source` filters beside `show_urlless` with filtered/total count, `checks` eager-loaded per page, legacy status mirror and `checker.legacy_status` removed (backups derive the legacy keys from the rows). No schema change. Register wire contract unchanged. |
| 0.36    | 2026-11-15 | §13.7 delivered (unreleased), completing §13: `health_history.py`, `GET /service/<id>/health`, `partials/health_detail.html` + `static/js/health_detail.js`, panel in the Tiled drawer, a Dashboard expand row and the Edit page ("Health history"). §13 retitled Delivered (unreleased); §5.6 retitled. No schema change. Register wire contract unchanged. |
| 0.37    | 2026-11-15 | §13.8 added, delivered (unreleased): Container check, Docker state as an automatic health check on every notifier entry (migration `c1d7a3e5f2b8`, kind `container`, evaluated by the scheduler). §13.1 state note and §5.6 `kind` list updated; former §13.8 (out of scope) is now §13.9 and no longer lists Docker state. Register contract unchanged. |
| 0.38    | 2026-11-15 | v0.7.0 released. §13 retitled Delivered: entry sources (notifier vs manual), health checks as their own tables with URL, service (HTTP/HTTPS status or body, TCP, ping) and automatic Container checks, concurrent checker with 24h raw + hourly-compacted 7-day history, health rollup badge and Status/Source filters, health detail panel with 24h/7d history. Schema in §5.6. Register wire contract unchanged; no notifier change needed. |
| 0.39    | 2026-11-15 | §13.6 filter bar (unreleased, post-v0.7.0): "Total Services" replaced by clickable Total / Passing / Failing count chips that set the `status` filter; counts follow `source` / `show_urlless` but ignore `status`. No schema or register-contract change. |
| 0.40    | 2026-11-15 | §13.7: inline 24h uptime strips (unreleased, post-v0.7.0): "Show uptime" filter-bar checkbox kept in the `std_show_uptime` cookie, `GET /health/strips`, `health_history.strips()`, `static/js/uptime_strip.js`. No schema change. Register wire contract unchanged. |
| 0.41    | 2026-11-15 | v0.7.1 released: clickable Total / Passing / Failing count chips in the filter bar (§13.6) and the "Show uptime" toggle with inline 24h uptime strips (§13.7). No schema or register-contract change. |
| 0.42    | 2026-11-15 | Added §14 (v0.8.0 — Management API, planned): admin API keys with read/write scopes, `/api/v1` REST for entries, checks, health, groups, widgets and runtime settings, OpenAPI spec, write audit log, stdio MCP server. Planned schema §5.7. Later sections renumbered (§14→§15, §15→§16, §16→§17). Register contract unchanged. No code changes yet. |
| 0.43    | 2026-11-15 | §14.2 and §14.6 delivered (unreleased, v080-01): admin API keys (`api_key`, Settings → API tab, show-once), management blueprint skeleton (`require_api_key`, JSON errors, `GET /api/v1/whoami`), write audit log (`api_audit`, `audit()` helper, `after_request` hook, `api_audit_retention_days` + daily purge). Migration `d4a9e2c6b715`; §5.7 updated. Register wire contract unchanged. |
| 0.44    | 2026-11-15 | §14.3 delivered (unreleased, v080-02): management endpoints for entries, checks, Check now, entry health and `/health/summary`; shared validation (`entry_rules.py`, dict-based validators in `check_form.py`) used by the UI and API; `mgmt_schemas.py` / `mgmt_serializers.py`. No schema change. Register wire contract unchanged. |
| 0.45    | 2026-11-15 | §14.4 delivered (unreleased, v080-03): management endpoints for groups, widget types and instances (attach, detach, delete), exposure direction settings and a read-only masked `GET /config`; `widget_rules.py`. No schema change. Register wire contract unchanged. |
| 0.46    | 2026-11-15 | §14.5 and the §14.6 Settings view delivered (unreleased, v080-04): `GET /api/v1/openapi.json` generated from a route registry (`mgmt_openapi.py`) plus the pydantic/TypedDict models, with completeness tests against `app.url_map`; Settings → API audit log view; README Management API and Managing STD with Claude sections; JSON 404/405 for unmatched `/api/v1/*` API-client requests. No schema change. Register wire contract unchanged. |
| 0.47    | 2026-11-15 | §14.7 delivered (unreleased, v080-05), the last v0.8.0 chunk; §14 status line now "all chunks delivered": stdio MCP server `mcp/std_mcp.py` (read key = read tools only, write key = all), outside the Docker image (`.dockerignore`), tested in CI. No STD server change, no schema change. Register wire contract unchanged. |
| 0.48    | 2026-11-15 | v0.8.0 released. §14 retitled Delivered: admin API keys (read/write scopes) and write audit log, `/api/v1` management API for entries, checks, health, groups, widgets, exposure settings and config, generated OpenAPI spec, stdio MCP server in `mcp/`. Schema §5.7 (`api_key`, `api_audit`). Add-page "None" group fix. Register contract unchanged; no notifier change. |
| 0.49    | 2026-11-16 | Added §15 (v0.9.0 — DNS and certificate-expiry checks, in progress) and delivered §15.1 on `dev` (v090-01): new `dns` service check (server IP, query name, record type, expected rcode, optional expected answer; NODATA handling), migration `a1c5e8d2f093` (four nullable `health_check` columns), `dnspython`, Add/Edit/detail/API/MCP support; §15.2 certificate expiry stubbed as planned. Later sections renumbered (§15→§16, §16→§17, §17→§18) and cross-references fixed. §5.6 `check_type` list and §14.3 add-check row updated. Register wire contract unchanged. |
| 0.50    | 2026-11-16 | §15.2 delivered on `dev` (v090-02): optional certificate-expiry condition (`cert_min_days`, 1-365) on URL checks and HTTP service checks, failing with `cert expires in N days (min M)`; separate unverified TLS handshake parsed with `cryptography`; migration `b7d3f1a94e26` (`cert_min_days`, `last_cert_expires_at`); "Min cert days" field shown only for https targets, detail-panel expiry line, API/OpenAPI/MCP support. §5.6 `health_check` columns updated. Register wire contract unchanged. |
| 0.51    | 2026-11-16 | §15.3 delivered on `dev` (v090-03): rotate an API key from Settings → API (`api_key.rotated_at`, new key shown once, old key invalid at once), and API key names unique among active keys only (partial index `ux_api_key_name_active`, migration `c2e8a5b3d917`). §14.2 updated. |
| 0.52    | 2026-11-16 | §15.4 delivered on `dev` (v090-04): Settings → Groups saves the whole table with one `POST /settings/groups/save` (all-or-nothing, per-row errors, delete applies on Save) and warns before leaving with unsaved changes (`static/js/unsaved_guard.js`); `/update_group`, `/add_group`, `/delete_group` removed; per-row Save priority-wipe bug fixed. Group name/icon rules moved to `entry_rules.validate_group`, shared with the management API. No schema or register-contract change. |
| 0.53    | 2026-11-16 | §15.5 delivered on `dev` (v090-05): `tile_show_host` setting (`duplicates` default, `always`, `never`) shows the host under the name on Tiled tiles, and after it on Compact rows, where the same name exists on another host (`view_helpers.duplicate_name_ids` / `host_label_ids`, computed over all active entries). Compact's old `more than one host` rule replaced. No schema or register-contract change. |
| 0.54    | 2026-11-16 | §8.9 updated (v090-07, `dev`): exposure badges render once per layer instead of once per `ServiceExposure` row. No schema or register-contract change. |
| 0.55    | 2026-11-16 | §8.9: exposure badges are the brand logo only; TLS and hostname overlays removed, details moved to the hover text. |
| 0.56    | 2026-11-16 | §15.6 delivered on `dev` (v090-08): roll-up no longer lets a passing Container check soften failing URL/service checks (all failing = down); status-mode HTTP failures carry the reply's reason (`503: ...`). §13.1, §13.4, §13.6 updated. No schema or register-contract change. |
| 0.57    | 2026-11-16 | §15.7 delivered on `dev` (v090-09): the MCP server installs with `uv run` (PEP 723 inline dependencies), knows its own version (`MCP_VERSION`), compares it with the STD version now returned by `GET /api/v1/whoami`, and adds a `server_info` tool. §14.2 and §14.7 updated. No schema or register-contract change. |
| 0.58    | 2026-11-16 | §15.8 delivered on `dev` (v090-10 B): the v2 layout is the Tiled tile layout; `/tiled_preview` removed; §8.9 and §9.4 updated. No schema or register-contract change. |
| 0.59    | 2026-11-16 | §15.9 delivered on `dev` (v090-10 A): Body-mode HTTP checks use the same reply-reason extraction as Status mode on 4xx/5xx; health detail panel always shows a reason line for a down check; static CSS/JS carry `?v=<mtime>`. §15.6 note corrected. No schema or register-contract change. |
| 0.60    | 2026-11-16 | §15.10 delivered on `dev` (v090-11): degraded/down entries get a soft amber/red background on the Dashboard, Tiled and Compact views (`entry-health-<state>` class). §13.6 updated. No schema or register-contract change. |
| 0.61    | 2026-11-16 | v0.9.0 released: §15 marked Delivered (DNS check, cert expiry, API key rotation, Groups single Save, host on tiles, roll-up and HTTP failure reasons, MCP uv install + version check, Tiled layout, health tints). |
| 0.62    | 2026-11-16 | Added §16 (Next release — Version in the UI, delivered on `dev`): `BUILD_CHANNEL` build arg and `channel` in `version.txt`, header version with What's New link and dev-build SHA link, GitHub update check (page-load driven, cached, backoff, DB settings `update_check_enabled` / `update_check_interval_hours`), `whoami`/`config` build and update fields, `/api/v1/settings/update-check`. §3.1 module layout updated. No schema or register-contract change. |
| 0.63    | 2026-11-16 | Added the §16 body (the 0.62 row described it, but the section text was missing) and §17 (Next release — Notifications: MQTT and Home Assistant, planned: channel framework, retained state publishing, HA discovery; operator decisions in §17.1). Former §16–§18 renumbered §18–§20 and cross-references updated. FUTURE.md alerting item split: state publishing moved here; alert rules and push channels stay parked. |
| 0.64    | 2026-11-16 | §17.2 delivered on `dev` (notif-01): `notification_channel` table (migration `a2f4c6e8b031`, new §5.8), `notify.py` / `notify_mqtt.py` (channel registry, bounded-queue publisher thread, MQTT via `paho-mqtt` 2.x, availability + LWT, reload on config change), instance id in the `setting` store, Settings → Notifications tab with **Send test message**, management API `/api/v1/notifications/channels` (+ `/test`) and MCP tools; §3.1 and §3.2 updated. §17.3 and §17.4 remain planned. No register-contract change. |
| 0.65    | 2026-11-16 | §17.3 delivered on `dev` (notif-02): retained state publishing. The topic and payload contract (`<base>/entry/<entry_id>/state`, `.../check/<check_id>`, `<base>/summary`) is public and documented in §17.3; change detection at `jobs.record_check_result()`, the `full_sync()` reconcile in new `notify_state.py` (connect, debounced mutation requests via a commit listener, a 10-minute forced safety net), published set persisted in the `setting` key `notify_publish_state` (§5.8); §3.1 and §3.2 updated. §17.4 remains planned. No register-contract change. |
| 0.66    | 2026-11-16 | §17.4 delivered on `dev` (notif-03): Home Assistant MQTT discovery. New `notify_ha.py`; discovery configs reconcile through `notify_state.full_sync()` (configs before states, per-channel published set in `notify_publish_state.ha`, cleared on opt-out/delete/purge/discovery off), birth-message subscription `<ha_prefix>/status` in `MqttSession`, additive state-payload attributes (`std_entry_id`, and `entry_name`/`host`/`group`/`source`/`dashboard_url` on checks), `ha_exclude` on `service_entry` and `health_check` (migration `d8e2a6f4b915`, new §5.9), Settings/edit-page controls, management API and MCP fields. §17 marked Delivered on `dev`. No register-contract change. |
| 0.67    | 2026-11-17 | §17.1/§17.4/§5.9 (notif-04, on `dev`): Home Assistant entries become opt-in (`service_entry.ha_publish`, default false; migration `e3b7c1d9a204` drops `service_entry.ha_exclude`, every entry starts unpublished; checks keep `ha_exclude`). Device names and `default_entity_id` include the host (`<prefix> <name> (<host>)`). Settings → Notifications "Home Assistant entries" bulk picker, `ha_publish` on the Add page, management API (`ha_publish` on entries) and MCP, `ha_publish`/check `ha_exclude` in backups. No register-contract change. |
| 0.68    | 2026-11-17 | §17.5 delivered on `dev` (notif-05): purge. New `notify_purge.py` (§3.1); channel purge (subscribe to `<base>/#` and this instance's `<ha_prefix>/+/std_<inst>/#`, clear retained + tracked topics except `<base>/status`, optional republish with a hold when off) and per-entry purge-and-republish on every channel, run on the publisher thread via `Publisher.call()`; Settings → Notifications button with confirm dialog, entry edit page button, management API `POST /notifications/channels/{id}/purge` and `POST /entries/{id}/notifications/purge`, MCP tools. The periodic safety net no longer releases a held channel. No schema or register-contract change. |
| 0.69    | 2026-11-17 | Added §18 (Next release — Inventory streams and API revision, planned for 0.10.0): `/api/v1` API revision (`X-STD-API-Revision` header, `GET /api/v1/meta`, revision history), HA "Since" sensor, nightly SQLite snapshot, source refactor (`is_docker`), inventory streams (schema, the `ingest` key scope, the snapshot ingest contract for sidecars, apply rules, lifecycle, blocks, link offers, Settings → Streams). Added §20.3 (inventory stream producers; std-source-technitium). Former §18–§20 renumbered §19–§21 and cross-references updated. No code changes yet. |
| 0.70    | 2026-11-17 | §18.1 delivered on `dev`: `api_version.py`, `X-STD-API-Revision` / `X-STD-Version` headers on every `/api/` response, public `GET /api/v1/meta`, `api_revision` in `whoami` / OpenAPI / MCP `server_info`, once-per-User-Agent register logging. |
| 0.71    | 2026-11-17 | §18.2 delivered on `dev`: Home Assistant "Since" timestamp sensor per published entry (§17.4 entity table); the daily backup job also writes `<date>-std_backup.sqlite3` via `sqlite3.Connection.backup()`, pruned by `backup_days_to_keep`. No register-contract change. |
| 0.72    | 2026-11-17 | §18.3 delivered on `dev`: `ServiceEntry.is_docker`; "not Docker" branches (tiled/dashboard/edit templates, stale guard, HA model) moved off `is_manual`; source filters and restore generalised over `VALID_SOURCES`. No operator-visible change. |
| 0.73    | 2026-11-17 | §18.4–§18.7 delivered on `dev` (inv-04): inventory streams backend. Migration `f4c8a2e6d173` (new §5.10: `inventory_stream`, `inventory_block`, `stream_link_offer`, stream columns and a partial unique index on `service_entry`; `source = stream`); `ingest` API key scope; the sidecar ingest contract `PUT /api/v1/streams/<stream_id>/snapshot` and `GET .../status` (§18.5, as specified); new `streams.py` apply engine and lifecycle (§18.6, §18.7); management routes under `/api/v1/streams`, `inventory` on entries, `block` on entry delete, MCP tools; MQTT payload `ip`/`mac`/`network`/`stream` and the HA device model. §3.1 and §3.2 updated. §18.8 (Settings → Streams UI) remains planned. |
| 0.74    | 2026-11-17 | §18.8 delivered on `dev` (inv-05): Settings → Streams tab (rows, pending highlight, read-only Docker row, Preview, Enable / Ignore, Disable… / Delete… cleanup dialog, inline name and network-filter edit, Blocked and Link offers lists), **Ingest (sidecars)** in the API key scope picker, stream pill and "missing" marker on Dashboard / Tiled / Compact, per-stream Source filter (`stream:<stream_id>`), stream edit page (read-only observations, Allow re-adding / Don't re-add), manual edit page (Convert / Keep separate banner, Link to stream item…). New session routes under `/settings/streams/` and `/edit/<id>/stream-link`. §18 retitled Delivered on `dev`; §18.8 "As built" notes; §13.6 `source` filter updated. No schema, register-contract or `/api/v1` change. |
| 0.75    | 2026-11-19 | §18 follow-ups from the first live test (inv-06), still API revision 2: link-offer matching widened (any active manual entry; name, host or host's first label; convert clears `host`); disable + purge keeps the stored snapshot; dry-run counts for pending/disabled streams; pending-stream flag in the header; per-stream `default_checks` (migration `a9d3c5e7f102`, `PATCH /streams/{id}`, `POST /streams/{id}/default-checks/apply`, MCP `apply_stream_default_checks`); `pending` in `GET /streams`; IP/MAC/network in the detail panel; Tiled and Compact stream icon and Compact source icon; HA entries table Source column; Add page "Docker host" wording. §5.10, §18.6–§18.8 updated. |
| 0.76    | 2026-11-19 | Notification cleanup (notif-06), still API revision 2: §17.5 channel delete cleans the broker first (default on; `cleanup` on `DELETE`/`PATCH`), disable offers it (default off), a base topic / discovery prefix change clears the old one and remembers the last 5 bases (`setting` key `notify_previous_bases`, §5.8), per-stream purge (`POST /streams/{id}/notifications/purge`), orphan scan and clear (`/notifications/channels/{id}/orphans/scan` and `/clear`, `GET .../previous-bases`), MCP tools for all; §17.3/§18.6 per-stream retained status topic `<base>/stream/<stream_id>` (part of the desired set, so `full_sync` reconciles and clears it); §17.4 one HA hub device per stream with a published entry (status and active / missing count sensors; its entry devices use `via_device` the stream device). The "channel delete/disable leaves its configs" caveat is gone. No schema migration, no register-contract change. |
| 0.77    | 2026-11-19 | Linked stream entries are unlinked, never deleted (inv-07), still API revision 2: §5.10 migration `b4e7a1c9d325` (`service_entry.stream_linked`, `pre_link_host`, backfill heuristic); §18.7 `POST /entries/{id}/unlink`, `unlinked` in disable/delete results, `inventory.linked`, `linked` in the stream entry counts, MCP `unlink_entry`; §18.8 dialog linked box, edit page Unlink from stream…. |
| 0.78    | 2026-11-19 | v0.10.0 release prep: §16, §17 and §18 (version in the UI, MQTT and Home Assistant notifications, inventory streams and API revision 2) marked Delivered in v0.10.0. No content change. |
| 0.79    | 2026-11-20 | Stream observability (inv-08), API revision 3 (unreleased, next after 0.10.0): new §18.9 (rejected snapshots, staleness with grace factor 2 and the expected / advertised interval, `missing` lifecycle with `inventory_missing_since` and the optional per-stream auto soft-delete and its "edited by a human" exemptions, IP-following checks instead of templated targets, MCP `server_info` re-check); §5.10 migration `c6f2a8d4e157`; §18.1 revision 3 row; §18.5 optional `snapshot_interval_seconds` and rejection recording; §18.7 `PATCH` fields; §14.3 health summary `streams` / `stale_streams` / `counts.streams_stale`; §17.3 stream topic `stale` etc. and entry `missing` / `missing_since`; §17.4 stream hub `problem` binary sensor. Register contract unchanged. |
| 0.80    | 2026-11-20 | v0.10.1 release prep: §18.9 stream observability (API revision 3) marked Delivered in v0.10.1; §18.1 revision 3 row names 0.10.1. No content change. |
| 0.81    | 2026-11-20 | 0.10.2 fixes (unreleased): `service_entry.container_name` widened to `String(128)` (migration `d7a3e9b2c418`, §5.10) to match the 128-character stream item name; entry name limit 128 in `/add` and the management API (register `container_name` has no length cap, unchanged); notification **Send test message** bounded to about 5 s in total (§17.2). Register and stream contracts unchanged, API revision stays 3. |
| 0.82    | 2026-11-20 | Added §19 (v0.11.0 — Settings modernization, planned; design in `docs/design/2026-11-20-settings-modernization.md`) and delivered its phase 1 on `dev`: section registry, grouped sidebar with deep links, flash policy, shared UI kit and restyle. Former §19–§21 renumbered §20–§22 and live cross-references updated (older revision rows keep the numbers of their day). §3.1 module layout updated. No schema, wire-contract or `/api/v1` change. |
| 0.83    | 2026-11-20 | §19 phase 2 delivered on `dev` (set-02): Settings → Notifications channel cards with ⋯ menu and Enabled switch, Add/Edit channel dialog (Send test beside Save, validation errors reopen it), Settings → Home Assistant grouped by source with search and a sticky Save bar; §17.2/§17.4 UI text updated; the "no channel publishes discovery" warning counts enabled channels only. No schema, wire-contract or `/api/v1` change. |
| 0.84    | 2026-11-20 | §19 phase 3 delivered on `dev` (set-03): Settings → Streams as cards (status dot, ⋯ menu, read-only Docker card), an Edit stream dialog with three independent blocks (name and networks, staleness and missing entries, default checks) that reopens with the typed values on a value or `StreamError` failure (400 re-render), Preview in a wide dialog, pending and stale inline warnings with Preview / Enable / Ignore, compact Blocked and Link offers lists, an amber open-offers badge on the Streams link. §18.8 UI text updated. Routes, `streams.py`, the wire contract and `/api/v1` are unchanged. |
| 0.85    | 2026-11-20 | §19 phase 4 delivered on `dev` (set-04), completing the Settings modernization except Backup & restore, which the separate backup project (`docs/design/2026-11-20-backup-export-import.md`) rebuilds: Groups as cards with a staging dialog inside the single form; Widgets as cards (⋯ Copy API key); Docker with a Layer directions card, collapsible per-host overrides and a sticky **Save & recompute URLs** bar, and the Docker (register) card moved there from Streams; Users as cards with Add user and Set password dialogs; API keys as cards with a Create key dialog and the key shown once in a dialog on the Settings page (`api_key_created.html` removed); About, Configuration, Deleted and detached widgets restyled. §12.5, §12.6, §14.2, §14.6, §15.3, §15.4, §16 and §18.8 UI text updated; §19 marked Delivered. No schema, wire-contract or `/api/v1` change. |
| 0.86    | 2026-11-20 | Added §20 (v0.11.0 — Backup, export and import, planned; design in `docs/design/2026-11-20-backup-export-import.md`) and delivered its phase 1 (§20.1, bak-01) on `dev`: backup path, snapshot and export settings editable in Settings with env > UI > `settings.yml` > default precedence, two daily jobs (snapshot 00:05, export 00:10) replacing the single 00:05 job, per-kind retention and Run now, a backup file list with download and delete, last-run status with a failure warning and navigation badge, new `backups.py`. §3 job list, §3.1 module layout and §4 settings table updated. Former §20–§22 renumbered §21–§23 and live cross-references updated (older revision rows keep the numbers of their day); the §19 TOC entry now says Delivered. No schema (the existing `setting` table is used), wire-contract or `/api/v1` change. |
| 0.87    | 2026-11-20 | §20.2 delivered on `dev` (bak-02): export format v1 (`std-export`, YAML or JSON, same document, never a secret) built by the new `export_format.py` with the §5.3 field ownership rules, the daily and manual export job now writes `<date>-std_export.yml\|json` (replacing the entry-list YAML; old `-std_backup.yml` files stay listed and age out with export retention), `GET /settings/backups/export` download with Download YAML / JSON buttons on the Exports card, and management API routes `GET`/`PUT /settings/backup`, `GET /backups`, `POST /backups/run`, `GET /export` with MCP tools `backup_settings`, `list_backups`, `export_config`, `run_backup`. **`API_REVISION` 4** (§18.1) and the `backup` feature. §3.1 module layout, §14.4 route list and §20.6 updated. No schema change; register and stream-ingest wire contracts unchanged. |

---

## Table of Contents

1. [Product Overview](#1-product-overview)
2. [Scope](#2-scope)
3. [Architecture](#3-architecture)
4. [Configuration Model](#4-configuration-model)
5. [Data Model](#5-data-model)
6. [Historical Baseline: State at v0.4.14](#6-historical-baseline-state-at-v0414)
7. [v0.5.0 — Cleanup Release](#7-v050--cleanup-release)
8. [v0.6.0 — Delivered](#8-v060--delivered)
9. [v0.6.1 — UI Rework Part 1 (Delivered)](#9-v061--ui-rework-part-1-delivered)
10. [v0.6.3–v0.6.6 — UI Overhaul Part 2 (Delivered)](#10-v063v066--ui-overhaul-part-2-delivered)
11. [v0.6.7–v0.6.8 — Registry move and engineering standards (Delivered)](#11-v067v068--registry-move-and-engineering-standards-delivered)
12. [v0.6.9 — Hardening and Safety Net (Delivered)](#12-v069--hardening-and-safety-net-delivered)
13. [v0.7.0 — Dashboard and Monitoring (Delivered)](#13-v070--dashboard-and-monitoring-delivered)
14. [v0.8.0 — Management API (Delivered)](#14-v080--management-api-delivered)
15. [v0.9.0 — DNS and certificate-expiry checks (Delivered)](#15-v090--dns-and-certificate-expiry-checks-delivered)
16. [Next release — Version in the UI (Delivered on `dev`)](#16-next-release--version-in-the-ui-delivered-on-dev)
17. [Next release — Notifications: MQTT and Home Assistant (Delivered on `dev`)](#17-next-release--notifications-mqtt-and-home-assistant-delivered-on-dev)
18. [Next release — Inventory streams and API revision (Delivered on `dev`)](#18-next-release--inventory-streams-and-api-revision-delivered-on-dev)
19. [v0.11.0 — Settings modernization (Delivered on `dev`)](#19-v0110--settings-modernization-delivered-on-dev)
20. [v0.11.0 — Backup, export and import (In progress)](#20-v0110--backup-export-and-import-in-progress)
21. [Versioning, Branches, and Releases](#21-versioning-branches-and-releases)
22. [Cross-Repo Coordination](#22-cross-repo-coordination)
23. [Open Questions](#23-open-questions)

---

## 1. Product Overview

STD is a homelab-scale service dashboard. It tracks Docker services
across multiple hosts, runs background URL health checks against them,
and renders a small set of dashboard views.

The dashboard is a **consumer** of metadata pushed by external tools
(typically `docker-api-notifier`, one per Docker host), with manual
add/edit/delete as a fallback for non-Docker services or one-offs.

### 1.1 Original problem

- Existing dashboards required hand-edited config to know about each
  service.
- `docker-compose` already encodes most of what a dashboard needs in
  labels. STD treats labels as the source of truth and uses the
  dashboard's own DB only as a cache + a place for things labels can't
  express (manual entries, widget state, user accounts).

### 1.2 Design principles

- **Push, don't poll.** The notifier sidecar pushes events; STD
  doesn't connect outward to Docker hosts.
- **Labels are the source of truth.** UI edits are allowed for
  exception cases (manual entries, `static` overrides) but the
  expected workflow is `dockernotifier.std.*` labels in compose files.
- **Single-instance, file-backed.** SQLite + WAL is enough at homelab
  scale (~50 services, 5–10 hosts). No external DB.
- **Fail open.** A bad URL or transient network error never crashes
  the app; it logs and moves on.

---

## 2. Scope

### 2.1 In scope

- Receive container metadata from external tools via a register
  endpoint.
- Run periodic URL health checks against registered services.
- Render dashboard views: full, tiled, compact.
- Provide a widget system for richer per-service info.
- Local user accounts with session-based auth.
- Manual add/edit/delete via the web UI.
- YAML backups of the database with retention.

### 2.2 Out of scope

- Container orchestration. STD never touches a Docker socket directly.
- Multi-tenant or org-style account boundaries.
- Push notifications, alerting, paging.
- Distributed deployment. Single-instance, single-DB by design.
- Acting as a CI/CD or deployment dashboard.

---

## 3. Architecture

```
        ┌──────────────────────┐         ┌──────────────────────┐
        │ Docker host A        │         │ Docker host B        │
        │  └─ notifier sidecar │         │  └─ notifier sidecar │
        └──────────┬───────────┘         └──────────┬───────────┘
                   │                                │
                   │  POST /api/v1/register         │
                   │  (canonical JSON payload)      │
                   ▼                                ▼
              ┌─────────────────────────────────────────┐
              │ STD                                     │
              │  ┌───────────────────────────────────┐  │
              │  │  Flask app (gunicorn, 1 worker)   │  │
              │  │  ├─ register routes (api)         │  │
              │  │  ├─ dashboard routes (html)       │  │
              │  │  ├─ widget routes                 │  │
              │  │  └─ auth routes                   │  │
              │  └───────────────────────────────────┘  │
              │  ┌───────────────────────────────────┐  │
              │  │  Background jobs (APScheduler)    │  │
              │  │  ├─ URL health check loop         │  │
              │  │  ├─ widget refresh loop           │  │
              │  │  └─ daily snapshot + export       │  │
              │  └───────────────────────────────────┘  │
              │  ┌───────────────────────────────────┐  │
              │  │  SQLite (WAL)                     │  │
              │  │  ├─ services                      │  │
              │  │  ├─ users                         │  │
              │  │  ├─ widget_value                  │  │
              │  │  └─ ...                           │  │
              │  └───────────────────────────────────┘  │
              └─────────────────────────────────────────┘
```

### 3.1 Module layout

```
app.py              ← thin Flask app factory; wires extensions, blueprints
extensions.py       ← SQLAlchemy + Flask-Login singletons
models.py           ← SQLAlchemy models (ServiceEntry, ServiceExposure,
                      Setting, User, Widget, WidgetValue, Group)
schemas.py          ← pydantic request/response schemas
version_check.py    ← build channel/display strings + cached GitHub update check
notify.py           ← notification channel registry + CRUD helpers, the
                      bounded-queue publisher thread, `enqueue()`
notify_state.py     ← retained state publishing: topic/payload builders,
                      change events, `full_sync()` reconcile (§17.3)
notify_mqtt.py      ← MQTT channel type: pydantic config, paho session
                      (LWT/availability, HA birth subscription), test message
notify_ha.py        ← Home Assistant discovery config builders (§17.4)
notify_purge.py     ← channel-wide, per-entry and per-stream purge of retained
                      topics and HA devices, base-change cleanup, remembered
                      bases and the orphan scan, all run on the publisher
                      thread (§17.5)
streams.py          ← inventory streams: ingest helpers, apply engine
                      (`plan` / `apply`), lifecycle, blocks, link offers
                      (§18.4–§18.7)
routes_dashboard.py ← /, /tiled_dash, /compact_dash, /dbdump, /settings,
                      /settings/exposure, /add, /edit/<id>, group CRUD,
                      /images/<filename>
routes_api.py       ← /api/v1/register
routes_widgets.py   ← /widget_config/<widget_name>
routes_auth.py      ← /login, /logout, user mgmt; is_admin_required;
                      Flask-Login user_loader
jobs.py             ← concurrent health-check scheduler, health-result
                      compaction/purge, widget refresh loop, daily
                      snapshot and export jobs, widget_value retention prune,
                      verify-and-fetch-missing-icons startup sweep
checker.py          ← health-check probes (http/tcp/ping/dns); network only, no DB
check_form.py       ← Add/Edit health-check form parsing + validation
health_state.py     ← per-entry health rollup (up/degraded/down/unknown/none)
health_history.py   ← history bars, uptime, recent failures for the detail panel
health.py           ← /healthz (liveness). /readyz not implemented.
settings_loader.py  ← file/ENV settings; loaded once at startup
settings_store.py   ← DB-stored runtime settings (per-interpreter directions, backup settings)
export_format.py    ← export format v1 (PRD 20.2): pydantic models, `build_export()`, `dump()`
backups.py          ← backup settings (env > UI > settings.yml > default), snapshot and export
                      runs, retention, file list and confined file lookup (§20.1)
settings_sections.py ← Settings section registry: groups, slugs, labels, legacy
                      `?section=` aliases, `resolve()` (§19)
synthesizer.py      ← exposure → internalurl/externalurl translation +
                      URL provenance tracking
image_utils.py      ← icon fetch + cache
view_helpers.py     ← grouping/sorting for dashboard views
templates/          ← Jinja templates; `templates/partials/settings/` holds one
                      partial per Settings section plus `_macros.html` (§19)
static/             ← static assets (css/, js/, icons/); `static/js/settings/`
                      holds the Settings scripts, `static/js/flash.js` the
                      toasts and banners (§19)
widgets/            ← per-widget plugin dirs
alembic/            ← migrations (alembic.ini at root)
scripts/            ← manual helper scripts (test_widget.py; not a test suite)
tests/              ← pytest suite (v0.6.9)
requirements-dev.txt ← pytest + runtime deps; CI/dev only
VERSION             ← bare-semver version source of truth
ruff.toml           ← lint config for CI (E, W, F, I, B; E501 ignored)
Dockerfile, entrypoint.sh, docker-compose.yml, requirements.txt
gunicorn.conf.py    ← production server config (workers must stay 1)
requirements.in     ← direct deps; requirements.txt is compiled from it
settings.example.yml, .env.example
standards.md        ← adopted standards + pinned versions
.github/workflows/  ← ci.yml, publish.yml, retention.yml
.claude/commands/   ← release-prep.md, release-cut.md
prompts/            ← handoff prompts (TEMPLATE.md, done/, failed/)
docs/               ← PRD.md, HISTORY.md, FUTURE.md, decisions.md, screenshots/
```

### 3.2 Module responsibilities

- **`app.py`** — `create_app()` factory: load settings once, init
  extensions, register blueprints, register error handlers, register
  template filters. Does not start background work on import —
  `run_startup_tasks(app)` (admin, icon sweep, `start_background_workers`)
  is invoked once per process: from the `__main__` block under
  `python app.py` (dev), or from the gunicorn `post_worker_init` hook in
  production, after migrations have completed.
- **`extensions.py`** — extension singletons (`db`, `login_manager`).
  No app context here; the factory binds them.
- **`models.py`** — SQLAlchemy models. Single source of truth for the
  schema; migrations track changes.
- **`schemas.py`** — pydantic schemas for inbound payloads (register
  endpoint specifically). Decouples wire format from DB columns.
- **`routes_*.py`** — Flask blueprints. Each file is one cohesive
  surface area; routes don't reach into unrelated tables.
- **`jobs.py`** — APScheduler-driven background work plus the
  startup icon-verification sweep. Each function takes the app
  explicitly and pushes its own context, so jobs.py keeps no
  module-level `app` reference.
- **`health.py`** — process-level health for ops/monitoring; not the
  same as URL health checks (those live in `jobs.py`).
- **`settings_store.py`** — read/write the `setting` table for
  operator-editable runtime settings (the per-interpreter direction
  mapping in v0.6.0). Distinct from `settings_loader.py`, which
  loads `settings.yml` once at startup. DB reads happen per call —
  the rows are tiny and edit rate is human-scale.
- **`notify.py` / `notify_mqtt.py`** — notification channels (§17).
  `notify.py` holds the channel-type registry, the shared create/update/
  delete helpers used by the Settings page and the management API, and the
  publisher: one daemon thread owning a bounded `queue.Queue` and one live
  session per enabled channel. Producers call the non-blocking
  `enqueue(event_dict)`; the thread is the only code that talks to a broker.
  `notify_mqtt.py` is the MQTT channel type (paho 2.x `loop_start()`
  threading, `connect_async`, an injectable client factory for tests).
  Started from `start_background_workers`; never started under pytest.
- **`streams.py`** — inventory streams (§18). Plain functions over the
  `inventory_stream` / `inventory_block` / `stream_link_offer` tables and
  `service_entry` rows with `source = stream`: value rules for the ingest
  contract (`normalize_mac`, `normalize_items`), `plan()` (what a snapshot
  would do, no writes, also behind Preview), `apply()` (one transaction under a
  module lock), and the lifecycle (enable, disable, ignore, delete, update,
  blocks, link offers). It raises `StreamError`; the management API maps it to
  the error shape and the Settings UI (§18.8) will call the same functions.
- **`synthesizer.py`** — exposure interpreter logic. Combines
  `ServiceExposure` rows + per-interpreter settings + URL
  provenance to produce synthesized `internalurl` / `externalurl`
  values on `ServiceEntry`. Runs on every register and on settings
  save. Idempotent; safe to call repeatedly.

---

## 4. Configuration Model

- ENV vars override `settings.yml` values.
- `settings.yml` is optional; defaults apply when missing.
- `settings_loader.load_settings()` is called **once at startup**, and
  the resulting config dict is stored on the app for downstream code to
  read. It is not re-read inside route handlers.

The configuration surface is documented in the `README.md`.

---

## 5. Data Model

Seven SQLAlchemy models (defined in `models.py` from v0.5.0 onward;
they lived in `app.py` through v0.4.14):

| Model            | Table              | Purpose                                                   |
|------------------|--------------------|-----------------------------------------------------------|
| `ServiceEntry`   | `service_entry`    | One row per registered service. PK on `id`; logical key on `(host, container_name)` — indexed from v0.5.0. Holds URLs, health flags, group_id (FK), sort_priority, status, last-checked timestamps, image metadata, icon, the `is_static` flag (the lock), the v0.7.0 `source` / `description` columns, the v0.5.0 `notifier_reported_*` capture columns, the v0.6.0 `networks` / `exposed_ports` / `published_ports` capture columns, and the v0.6.0 `internalurl_source` / `externalurl_source` URL provenance columns. |
| `ServiceExposure`| `service_exposure` | New in v0.6.0. One row per (service, interpreter layer) observation — many rows per service possible. Wholesale-replaced per register when the payload carries `exposure_observations`. FK to `service_entry.id` (ON DELETE CASCADE), indexed. |
| `Group`          | `group`            | Optional grouping. Unique `group_name`, optional `group_sort_priority` and `group_icon`. Referenced by `ServiceEntry.group_id`. |
| `Widget`         | `widget`           | Widget configuration (name, URL, API key, JSON-encoded field list). Referenced by `ServiceEntry.widget_id`. |
| `WidgetValue`    | `widget_value`     | Most-recent value per `(widget_id, widget_value_key)` — upserted in place by the widget refresh job, not a time series. The retention job (v0.5.0+) prunes rows whose `last_updated` is older than `widget_value_retention_days`. |
| `Setting`        | `setting`          | New in v0.6.0. KV-style store for operator-editable runtime settings. Distinct from `settings.yml` (which is immutable for the process lifetime). Backs the per-interpreter direction mapping used by the synthesizer. JSON values. |
| `User`           | `user`             | Local user accounts for the web UI.                       |

### 5.1 v0.5.0 schema changes

| Change | Detail |
|--------|--------|
| Index  | Non-unique `ix_service_entry_host_container_name` on `service_entry(host, container_name)`. Concurrency safety lives in the application-level register mutex, not in a database constraint, so duplicate cleanup is deferrable. |
| Column | `service_entry.notifier_reported_group_name` (`String(100)`, nullable). Captures what the notifier most recently sent for the `group` label. |
| Column | `service_entry.notifier_reported_sort_priority` (`Integer`, nullable). Captures what the notifier most recently sent for the `sort.priority` label. |
| Drop   | `user.session_token` removed (see §5.2 S3). |

The two `notifier_reported_*` columns are populated by the v0.5.0
register handler on every register call. No reader yet — they exist
so a planned overridden-labels export can compare the user's edited
value against the notifier's latest report. Restoring from a v0.4.x
backup leaves them NULL; the next register call fills them in.

### 5.2 Schema gaps from v0.4.14 (status)

| ID  | Issue | Status |
|-----|-------|--------|
| S1  | No indexes beyond primary keys. `(host, container_name)` is hit on every register call and needs an index. | Resolved in v0.5.0 (`ix_service_entry_host_container_name`). |
| S2  | `widget_value` has no retention. At ~45 services × frequent samples, this grows unboundedly. | Resolved in v0.5.0 (configurable retention prune job, default 30 days). |
| S3  | `User.session_token` is never read (it is *written* by `generate_session_token()` on user creation, but no code ever reads it back) — half-finished feature; remove. | Resolved in v0.5.0. |
| S4  | `is_docker_status_stale` property was defined at the wrong indentation level and silently attached to `User` instead of `ServiceEntry`. `templates/tiled_dash.html` references `entry.is_docker_status_stale` on `ServiceEntry` rows, so Jinja resolved it to `Undefined` (always falsy) and the stale tile styling never fired. | Fixed in v0.5.0: property re-attached to `ServiceEntry`. |

### 5.3 v0.6.0 schema changes

| Change | Detail |
|--------|--------|
| Column | `service_entry.networks` (`JSON`, nullable). List of `{"name": str, "aliases": [str]}` capturing Docker network membership as reported by the notifier. Pure observation; overwritten on every register. Names only — IPs/gateways are intentionally not captured. |
| Column | `service_entry.exposed_ports` (`JSON`, nullable). List of `"<port>/<proto>"` strings (e.g. `"5173/tcp"`). The container's `EXPOSE` declarations / compose `expose:` entries. |
| Column | `service_entry.published_ports` (`JSON`, nullable). List of `{"container_port", "protocol", "host_ip", "host_port"}` objects — the host-to-container port mappings from compose `ports:`. Distinct from `exposed_ports`: published is what reaches the host, exposed is what the container declares it listens on. |

All three are populated by notifier v0.4.0+. Rows that haven't seen a
v0.4.0+ register call have NULL for these columns — that's the
expected state, not a bug. The read-only block at the bottom of the
edit page shows "Not reported" when the columns are NULL.

The v0.6.0 synthesizer (§8.6) does not currently read these columns —
exposure observations from interpreters (§5.4) carry the same
hostname information more directly. They remain captured as
diagnostic data, visible on `/edit/<id>`, and as a future fallback
evidence source if a "proxy-adjacent without explicit labels" rule
ever lands.

### 5.4 v0.6.0 schema changes (exposure interpreter)

| Change | Detail |
|--------|--------|
| Table  | `service_exposure` — one row per (service, interpreter layer) observation. Columns: `id` (PK), `service_entry_id` (FK to `service_entry.id` ON DELETE CASCADE, indexed), `layer` (`String(64)`, NOT NULL), `hostname` (`String(255)`, nullable), `tls` (Boolean, nullable), `path_prefix` (`String(255)`, nullable), `auth` (`String(128)`, nullable), `details` (JSON, nullable), `last_updated` (DateTime, NOT NULL). Replaced wholesale per service on each register that carries `exposure_observations`. |
| Column | `service_entry.internalurl_source` (`String(20)`, nullable). URL provenance — one of `"ui_edit"`, `"explicit_label"`, `"synthesized"`, or NULL. Ordering enforced by the register handler, UI edit handler, and synthesizer: `ui_edit` > `explicit_label` > `synthesized` > NULL. |
| Column | `service_entry.externalurl_source` (`String(20)`, nullable). Same semantics as `internalurl_source` but for `externalurl`. |
| Table  | `setting` — KV-style runtime settings. Columns: `key` (`String(64)`, PK), `value` (JSON, nullable), `updated_at` (DateTime, NOT NULL). v0.6.0 uses two keys: `exposure_layers` (dict of layer → direction) and `exposure_layers_per_host` (dict of host → dict of layer → direction). Future settings can re-use this table. |

Restoring from a v0.5.0 backup leaves `internalurl_source` and
`externalurl_source` NULL — the next register call may write
`explicit_label`, and the next UI edit will write `ui_edit`. Rows
imported from backup without exposure observations get NULL source
columns, meaning the synthesizer is free to fill them in once
exposure data arrives.

### 5.5 v0.6.9 schema changes

| Change | Detail |
|--------|--------|
| Column | `service_entry.deleted_at` (`DateTime`, nullable, indexed as `ix_service_entry_deleted_at`). NULL = active; a timestamp = soft-deleted at that time (naive server-local). Rows past `deleted_retention_days` are hard-deleted by the 00:25 purge job (§12.5). |

| Column | `service_entry.health_check_timeout` (`Integer` seconds, nullable; NULL = use the global `health_check_timeout` setting). Not indexed (not a lookup column). |
| Column | `service_entry.health_check_verify_tls` (`Boolean`, NOT NULL, server default true). Existing rows keep verifying TLS. |

Restoring a v0.6.8 backup leaves `deleted_at` NULL and the health-check
options at their defaults.

### 5.6 v0.7.0 schema changes

Shipped in v0.7.0 (§13); v070-06 added no schema. One Alembic migration per chunk; each FK gets
its index in the same migration.

| Change | Detail |
|--------|--------|
| Column | `service_entry.source` (`String(16)`, NOT NULL, server default `'notifier'`): `notifier` or `manual`. Backfill: `manual` where `last_api_update IS NULL`, else `notifier` (§13.2). |
| Column | `service_entry.host` becomes nullable (manual entries may omit it). `(host, container_name)` index unchanged. |
| Column | `service_entry.description` (`String(255)`, nullable). Operator text, mainly for manual entries. |
| Table  | `health_check`: one row per configured check. `service_entry_id` FK (ON DELETE CASCADE, indexed), `kind` (`internal_url` / `external_url` / `service` / `container`), `name`, `check_type` (`http` / `tcp` / `ping` / `dns` / `docker`), `target` (NULL for URL kinds: they follow the entry's URL), `mode` (`status` / `body`), `interval_seconds` / `timeout_seconds` (nullable = global default), `verify_tls`, `enabled`, the DNS query columns (§15.1), `cert_min_days` and cached `last_cert_expires_at` (§15.2), cached state `last_ok`, `last_checked_at`, `last_status_code`, `last_latency_ms`, `last_message`, `consecutive_failures`. Exactly one `internal_url` and one `external_url` row per entry; zero or more `service` rows; exactly one `container` row per notifier entry (none for manual entries). |
| Table  | `health_result`: one row per check sample or compacted success range. `check_id` FK (ON DELETE CASCADE), `ts`, `ts_end` (NULL for a single sample), `samples` (default 1), `ok`, `latency_ms` (average for a range), `latency_max_ms`, `status_code`, `message`. Composite index `(check_id, ts)` (also serves the FK). Timestamps are naive UTC. |
| Data   | Migration creates the two URL-kind `health_check` rows for every entry, copying `*_health_check_enabled`, `health_check_timeout`, `health_check_verify_tls` and the last status. |
| Data   | Migration `c1d7a3e5f2b8` inserts one enabled `container` row for every `source='notifier'` entry (soft-deleted included). No new columns or indexes; the downgrade deletes the rows and their results. |
| Deprecated | `service_entry.internal_/external_health_check_enabled/_status/_update`, `health_check_timeout`, `health_check_verify_tls`: no longer read after v0.7.0; kept for rollback, dropped in a later release (FUTURE.md). |


### 5.7 v0.8.0 schema changes

Planned for v0.8.0 (§14). FKs get their index in the same migration. `api_key` and `api_audit` shipped in migration `d4a9e2c6b715` (v080-01); column types: `object_type` `String(32)`, `object_id` `String(64)` (ids are stored as text), `path` `String(255)`, `method` `String(8)`; indexes `ix_api_key_prefix`, `ix_api_key_created_by`, `ix_api_audit_ts`, `ix_api_audit_api_key_id`.

| Change | Detail |
|--------|--------|
| Table | `api_key`: `id`, `name` (unique), `prefix` (indexed), `key_hash` (SHA-256 hex), `scope` (`read`/`write`), `created_at`, `created_by` (FK `user.id`, nullable, indexed), `last_used_at`, `last_used_ip`, `revoked_at`. |
| Table | `api_audit`: `id`, `ts` (naive UTC, indexed), `api_key_id` (FK `api_key.id` ON DELETE SET NULL, indexed), `key_name`, `method`, `path`, `object_type`, `object_id`, `status_code`, `changes` (JSON). Pruned by `api_audit_retention_days`. |

### 5.8 Notification schema changes

Migration `a2f4c6e8b031` (§17.2). No foreign keys.

| Change | Detail |
|--------|--------|
| Table | `notification_channel`: `id`, `type` (`String(32)`, indexed `ix_notification_channel_type`), `name` (`String(64)`, unique index `ux_notification_channel_name`), `enabled` (bool, default false), `config` (JSON, non-secret settings), `secret` (`String(512)`, nullable, the MQTT password; write-only in the UI, API, logs and audit), `created_at`, `updated_at`. |
| Setting key | `instance_id` in `setting`: a UUID created on first use and never changed (MQTT client ids; Home Assistant unique ids in §17.4). |
| Setting key | `notify_previous_bases` in `setting` (§17.5): JSON `{channel id: [{base_topic, ha_prefix}]}`, newest first, at most 5 per channel; the pairs a channel used before a change, for the orphan scan. Dropped with the channel. |
| Setting key | `notify_publish_state` in `setting` (§17.3): JSON `{topics, entries, checks}`: every retained topic believed to be on the broker, each entry's last published roll-up (`state`, `since`, `checks`) and each check's last `ok` with the time it changed. Lets the reconcile clear deleted topics after a restart. |

### 5.9 Home Assistant schema changes

Migrations `d8e2a6f4b915` and `e3b7c1d9a204` (§17.4). No foreign keys, no new index (flags, not lookup columns).

| Change | Detail |
|--------|--------|
| Column | `service_entry.ha_publish` (Boolean, NOT NULL, default false). Opt-in to Home Assistant discovery. Operator-owned: register never writes it. Added by `e3b7c1d9a204`, which dropped the interim `ha_exclude` on entries; every existing entry is false after it (clean slate). Part of `to_dict()` (backups). |
| Column | `health_check.ha_exclude` (Boolean, NOT NULL, default false). Per-check opt-out. Part of `to_config()` (backups). |
| Setting key | `notify_publish_state` gains `ha`: `{channel id: [discovery config topics]}` (§17.4). |

### 5.10 Inventory stream schema changes

Migrations `f4c8a2e6d173` (§18.4), `a9d3c5e7f102` (`inventory_stream.default_checks`, below), `b4e7a1c9d325` (`service_entry.stream_linked`, `pre_link_host`, below), `c6f2a8d4e157` (stream observability, §18.9, below) and `d7a3e9b2c418` (`service_entry.container_name` widened from `String(100)` to `String(128)`, so a 128-character stream item name fits; `batch_alter_table`, the `ix_service_entry_host_container_name` index survives the rebuild). Every FK column has its index in the same migration.

| Change | Detail |
|--------|--------|
| Table | `inventory_stream`: `id`, `stream_id` (`String(63)`, unique: the slug in the URL), `display_name` (`String(32)`), `producer` (`String(64)`), `producer_version` (`String(32)`), `key_type` (`String(16)`), `status` (`pending` / `enabled` / `disabled` / `ignored`, default `pending`), `api_key_id` (FK `api_key.id` ON DELETE SET NULL, indexed `ix_inventory_stream_api_key_id`), `network_include` / `network_exclude` (JSON lists, NULL = no filter), `snapshot` (JSON, the latest accepted items), `first_seen_at`, `last_snapshot_at`, `last_applied_at`, `last_item_count`, `last_counts` (JSON), `last_error` (`String(255)`), `created_at`, `updated_at`. |
| Column | `inventory_stream.default_checks` (JSON, nullable; migration `a9d3c5e7f102`): `{"ping": bool, "tcp_port": int \| null}`, port 1-65535; NULL = no default checks. Plain column, no FK, no index. |
| Table | `inventory_block`: `id`, `stream_id` (FK `inventory_stream.id` ON DELETE CASCADE, indexed), `key` (`String(128)`), `name`, `ip`, `blocked_at`, `blocked_by`; unique `ux_inventory_block_stream_key` on `(stream_id, key)`. Not tied to the entry, so it outlives the entry's hard delete. |
| Table | `stream_link_offer`: `id`, `stream_id` (FK ON DELETE CASCADE, indexed), `key`, `entry_id` (FK `service_entry.id` ON DELETE CASCADE, indexed), `item` (JSON, the stored snapshot item), `created_at`; unique `ux_stream_link_offer_stream_key` on `(stream_id, key)`. |
| Columns | `service_entry.stream_id` (FK `inventory_stream.id`, nullable, indexed `ix_service_entry_stream_id`), `stream_key` (`String(128)`), `mac` (`String(17)`), `ip` (`String(64)`), `network` (`String(64)`), `attributes` (JSON), `inventory_missing` (Boolean, NOT NULL, default false), `name_source` (`String(16)`: NULL, `stream` or `ui_edit`). NULL for notifier and manual entries. |
| Columns | `service_entry.stream_linked` (Boolean, NOT NULL, server default false) and `pre_link_host` (`String(100)`, nullable); migration `b4e7a1c9d325`, plain columns, no FK, no index. `_convert` (accept / link / Convert) sets `stream_linked` and keeps the old host in `pre_link_host`; unlinking clears both and restores the host. **Backfill** for entries linked before the migration (no created timestamp exists): per stream, an entry with `name_source = 'ui_edit'` and an `id` lower than the smallest id of the stream's `name_source = 'stream'` entries is marked linked (host unknown, `pre_link_host` NULL); a stream with no stream-named entry has no reference point, so nothing is marked. |
| Columns | Migration `c6f2a8d4e157` (§18.9), plain nullable columns, no FK, no index: `inventory_stream.expected_interval_seconds`, `producer_interval_seconds`, `missing_expiry_days` (Integer), `last_rejected_at` (DateTime, naive UTC), `last_rejection` (`String(255)`); `service_entry.inventory_missing_since` (DateTime, naive UTC). **Backfill:** entries already flagged missing get the upgrade time (`CURRENT_TIMESTAMP`), which can only delay an auto soft-delete. |
| Index | `ux_service_entry_stream_key`: partial unique index on `(stream_id, stream_key)` where `stream_id IS NOT NULL`. Soft-deleted rows count. |
| Value | `service_entry.source` gains `stream` (`VALID_SOURCES`). The downgrade turns `stream` entries into `manual` ones. |
| Value | `api_key.scope` gains `ingest` (the column was already wide enough; no DDL). |
| Backups | `to_dict()` carries `mac`, `ip`, `network` and `attributes`. A stream entry restores as a manual entry (it has no stream to rejoin); a backup record never overwrites a live stream entry. |

---

## 6. Historical Baseline: State at v0.4.14

> Historical snapshot of the pre-v0.5.0 codebase, kept for context. It does
> not describe the current state; see §§7–11 for what shipped since.

Tags shipped on `main`: v0.1.0 → v0.4.14. (One stray tag `v.0.4.6` with
an extra dot will be deleted as part of v0.5.0 housekeeping.)

### 6.1 What works today

- `/api/register` accepts container metadata; quietly remaps several
  inbound key variants.
- Three dashboard views render from the `services` table.
- Background URL health checks via APScheduler.
- Widget system with six built-in widgets (Sonarr, Radarr, Bazarr,
  Overseerr, Prowlarr, Syncthing).
- Local user auth, session-based.
- Daily YAML backups.
- Icon auto-fetch from Homarr Labs CDN.

### 6.2 Known issues at v0.4.14 (resolved in v0.5.0)

| ID  | Area                | Issue |
|-----|---------------------|-------|
| D1  | `app.py` size       | ~1,775 lines holding 4 models, ~20 routes, 3 background jobs, template filters, and init code. Hard to navigate and review. *(Resolved in v0.5.0.)* |
| D2  | View duplication    | `/`, `/tiled_dash`, `/compact_dash` duplicate ~150 lines of grouping/sorting logic. *(Deferred from v0.5.0; resolved in v0.6.0 — see §8.1.)* |
| D3  | Icon fetch dup.     | Icon fetching is duplicated between `image_utils.py` and inline calls in `/add`, `/edit`. *(Resolved in v0.5.0.)* |
| D4  | Auth half-finished  | `User.session_token` written on user creation but never read. *(Resolved in v0.5.0.)* |
| D5  | Stale styling broken | `is_docker_status_stale` property indented onto `User` instead of `ServiceEntry`. Template references it on `ServiceEntry`, so stale tile styling never fired. *(Resolved in v0.5.0.)* |
| D6  | Settings drift      | `settings.example.yml` says `url_refresh_interval`; code reads `url_healthcheck_interval`. *(Resolved in v0.5.0.)* |
| D7  | Retention           | `widget_value` table grows unbounded. *(Resolved in v0.5.0.)* |
| D8  | Schema              | No indexes beyond PKs; `(host, container_name)` is the upsert key. *(Resolved in v0.5.0.)* |
| D9  | Settings reload     | `load_settings()` is called at module level **and** inside some route handlers. Single load at startup is the right shape. *(Resolved in v0.5.0.)* |
| D10 | Job error handling  | URL health check loop has no top-level try/except; one bad URL or transient error can kill the loop until restart. *(Resolved in v0.5.0.)* |
| D11 | Register contract   | `/api/register` quietly remaps `group ↔ group_name`, `internal.health ↔ internal_health_check_enabled`, `docker_host ↔ host`, etc. Contract drift; no canonical schema. *(Resolved in v0.5.0.)* |
| D12 | Concurrency         | `/api/register` upsert has no locking. With multiple notifier hosts, two near-simultaneous registers for the same `(host, container_name)` can race. *(Resolved in v0.5.0.)* |

---

## 7. v0.5.0 — Cleanup Release

**Shipped before notifier v0.3.0.** STD v0.5.0 introduces the
`/api/v1/register` endpoint that notifier v0.3.0 will target.

### 7.1 Goals

- Resolve every issue in §5.2 and §6.2.
- Establish a stable, canonical register contract with a clear sunset
  for legacy keys.
- Split `app.py` into reviewable modules without changing observable
  behavior.
- Add the schema indexes and retention policies the homelab-scale
  workload actually needs.

### 7.2 Behavior changes visible to operators

- `/api/v1/register` is the new canonical endpoint. Strict: unknown
  keys are rejected with 400 + the list of offending keys.
- `/api/register` continues to work but emits `Deprecation: true`
  and a `Link` header pointing to `/api/v1/register` on every
  response. A WARNING log fires at most once per client IP per
  hour. No `Sunset` header in v0.5.0 — a wrong Sunset date is
  worse than none. (v0.6.0 ultimately removed the endpoint
  outright, making a Sunset header moot.)
- The `sort.priority` legacy key (with the dot) now actually populates
  `sort_priority`. The v0.4.x handler read it directly with the dot
  but never wired it to the canonical name, so payloads that sent
  `sort.priority` silently had no effect. Now they do.
- New rows still take every field the payload carries. Existing
  rows: `register_field_ownership` (default `user_wins`) decides
  whether the notifier may overwrite UI-edited `group_name` and
  `sort_priority`. The `notifier_reported_*` capture columns are
  written either way.
- The web UI, dashboard views, login flow, and existing settings
  keys work unchanged.
- `settings.example.yml` is corrected to match the keys the code
  actually reads, and documents the two new settings
  (`widget_value_retention_days`, `register_field_ownership`).

### 7.3 Internal changes

- App factory pattern. `app.py` becomes a thin wiring file.
- Models, schemas, blueprints, jobs each in their own modules.
- `pydantic` v2 used for inbound register validation; replaces ad-hoc
  key-remapping. Compat shim is one well-defined function that maps
  legacy keys to canonical.
- Single `load_settings()` call at startup; downstream code reads from
  the resolved app-level config dict.
- URL health check loop wrapped in a top-level try/except so a
  transient exception in one pass doesn't kill the loop.
- `(host, container_name)` index added (`ix_service_entry_host_container_name`,
  non-unique).
- `notifier_reported_group_name` and `notifier_reported_sort_priority`
  capture columns added to `service_entry`. Populated by the v0.5.0
  register handler; not read in v0.5.0 itself — forward-compat for
  the planned overridden-labels export.
- Application-level mutex around the register upsert to serialize
  near-simultaneous writes for the same logical service. Coarse
  (single `threading.Lock` covering all keys); homelab-scale write
  rate doesn't justify per-key locking. In-process only — under
  Gunicorn with multiple workers, SQLite's WAL single-writer
  behavior is the actual cross-process safety net.
- New `register_field_ownership` setting (`user_wins` default or
  `notifier_wins`) controls whether the notifier may overwrite a
  non-NULL UI-edited value for `group_name` or `sort_priority` on
  an existing row. Invalid values fall back to `user_wins` with a
  startup WARNING.
- `widget_value` retention: rolling window enforced by a daily
  prune job at 00:15. Window configurable via
  `widget_value_retention_days` (default 30).
- Dead code removed: `User.session_token` (never read; the half-finished
  auth feature it was meant for never landed).
- `is_docker_status_stale` re-attached to `ServiceEntry` (previously
  bound to `User` via an indentation bug, which made the template's
  stale tile styling silently dead).

### 7.4 Out of scope for v0.5.0

- New dashboard views.
- New widgets.
- New notifier targets (those live in the notifier repo).
- Any change to user auth model beyond removing the dead
  `session_token` field.
- Replacing APScheduler.

---

## 8. v0.6.0 — Delivered

Originally planned across three releases — v0.5.x (view controls +
grouping/sorting helper consolidation), v0.6.0 (compat-shim sunset +
container network/port capture), and v0.7.0 (exposure interpreter
mechanism + synthesizer + badges + settings UI). All of it shipped
together as a single v0.6.0 release on 2026-05-14.

The interpreter work transforms STD's role from "operator restates
infrastructure facts via `dockernotifier.std.*` labels" into "STD
reads facts the notifier already extracts from other tools' labels,
infers URLs and exposure layers, and surfaces them with badges."
The operator writes *less* configuration; STD does more inference.

### 8.1 View controls + helper consolidation

Resolves D2 (§6.2) — the v0.5.0 changelog incorrectly claimed the
grouping/sorting helper had been consolidated; the work actually
landed here. Bundled with the introduction of dashboard view
controls because both touch the same code paths.

Operator-visible behavior:

- All three dashboard views (`/`, `/tiled_dash`, `/compact_dash`)
  render a shared view-controls partial above the service grid: a
  `Group by` dropdown, an in-bucket sort selector, and a `Show
  URL-less` checkbox.
- View-control state lives in the URL query string
  (`?group_by=stack&show_urlless=false&sort_in_group=alphabetical`)
  so dashboards are bookmarkable and shareable. Per-user
  persistence is intentionally out of scope.
- Defaults match v0.5.0 behavior. With no query params, the
  dashboard groups by group (Ungrouped last), shows every
  registered service, and sorts within bucket per the existing
  per-view default (`priority` for `/` and `/tiled_dash`,
  `alphabetical` for `/compact_dash`).
- `Group by` axes: `group` (default), `stack`, `host`. N-axis
  design — future axes (image, exposure layer, ...) drop in
  without rework. Bucket labels:
  - `axis=group` — group display name; rows with no group land in
    "Ungrouped" rendered last.
  - `axis=stack` — stack name; rows with no stack land in
    "Unstacked" rendered last. Stack is a deployment unit (compose
    project), not a fallback group; it's surfaced as its own axis
    rather than silently merged with `group`.
  - `axis=host` — host string; rows with no host land in "Unknown
    host" rendered last.
- `?show_urlless=false` filters out entries whose `internalurl` and
  `externalurl` are both null/empty before grouping, so empty
  buckets disappear cleanly.
- Unknown axis values fall back to `group` (logged at DEBUG).

Internal changes:

- New module `view_helpers.py` exposing `group_and_sort_services` —
  the single grouping/sorting entry point. Returns a list of
  `(bucket_label, [entries])` tuples in render order.
- `routes_dashboard.py` view handlers shrunk to "read query params,
  load entries, hand off to the helper, render." The three
  handlers no longer carry their own grouping/sorting code.
- Group buckets are keyed canonically by `group_id`, not
  `group_name`. (Two distinct `Group` rows that happen to share a
  display name get two distinct buckets.) The previous mix of
  `group_id` keying in `dashboard()` and `group_name` keying in
  the other two handlers is reconciled toward `group_id`.
- Templates iterate the helper's tuple list directly; the
  `group_lookup` dict the dashboard view used to construct in
  Python is gone — the bucket label is the helper's output.
- Per-view JS handlers for the group-by/sort dropdowns are
  removed in favour of a single shared submit-on-change handler
  in the view-controls partial.

### 8.2 Sunset of /api/register

- `/api/register` removed.
- Legacy-key remap (`_LEGACY_KEY_MAP`, `_remap_legacy_to_canonical`)
  removed.
- `Deprecation: true` / `Link: rel="successor-version"` response
  headers, the per-IP deprecation log tracker, and `_add_deprecation_headers`
  removed — they have no surface to attach to anymore.
- pydantic schemas (`RegisterPayload`) are the only accepted shape.
- Operators must run notifier v0.3.0 or later. Anything older returns
  404 at the (now gone) `/api/register` path.

### 8.3 Container facts captured

Three new nullable JSON columns on `service_entry` — see §5.3 for the
full schema. Wire contract: three new optional fields on
`RegisterPayload` (`networks`, `exposed_ports`, `published_ports`)
with nested pydantic types so malformed payloads are rejected at the
schema boundary rather than at write time.

Pure observation, no ownership semantics — the notifier overwrites
these on every register. If the notifier sends `null` or `[]`, that's
written as-is (so the operator can see when a container loses its
network membership / port mapping). Pre-v0.4.0 notifiers continue to
work; they just don't populate the new columns.

### 8.4 Detail surface

A read-only "Reported by notifier" block at the bottom of the edit
page (`/edit/<id>`) shows networks, exposed ports, published ports,
and exposure observations for the service. Empty / NULL state
renders "Not reported" / "No exposure observations" text rather
than empty sections. Static entries (`is_static=True`) also render
the empty state — they don't receive notifier registers.

### 8.5 Exposure observations — wire contract

New optional field on `RegisterPayload`:

```
exposure_observations: Optional[List[ExposureObservation]] = None
```

Nested `ExposureObservation` model (`extra="forbid"`):

- `layer` (str, required) — interpreter identifier, e.g., `"traefik"`,
  `"dockflare"`. Lowercase, underscore-separated by convention.
- `hostname` (Optional[str]) — public-facing hostname.
- `tls` (Optional[bool]) — true if TLS-terminated at this layer.
- `path_prefix` (Optional[str]) — path prefix when exposed at non-root.
- `auth` (Optional[str]) — auth indicator (`"cloudflare_access:authenticate"`,
  `"none"`, etc.). Rendered as a `🔑` icon on the tile badge.
- `details` (Optional[Dict[str, Any]]) — per-layer extras that don't
  fit the typed columns. Use sparingly; fields used by multiple
  interpreters should be promoted to typed columns.

Wholesale-replace semantics on register: `null` in the payload means
"no update — leave existing rows alone" (so a pre-v0.4.0 notifier
that doesn't emit the field doesn't accidentally clear observations
from an earlier register). `[]` means "this container has no
interpreter matches — clear all rows." A non-empty list replaces
all rows for the service.

### 8.6 Synthesizer

`synthesizer.py` consumes `ServiceExposure` rows + operator
per-interpreter direction settings (§8.8) + the service's existing
URL provenance, and produces `internalurl` / `externalurl` values
on `ServiceEntry` with `_source = "synthesized"`.

Algorithm (per direction, internal vs external):

1. For each `ServiceExposure` row attached to the service, look up
   the direction for `(layer, host)` using
   `settings_store.direction_for(layer, host)`. Per-host settings
   override the global mapping; unknown / unset = "neither".
2. Build candidate URLs from rows whose direction matches the one
   we're computing. URL shape:
   `{scheme}://{hostname}{path_prefix}/` where scheme is `https`
   when `tls=true` else `http`. Skip rows missing hostname.
3. Tiebreaker (first one wins): TLS over non-TLS, no path prefix
   over path prefix, layer name alphabetical (stable, deterministic).
4. Write the winning URL only when the existing `_source` is NULL
   or `"synthesized"`. `ui_edit` and `explicit_label` are
   preserved.
5. When no candidate exists and `_source` is NULL or
   `"synthesized"`, clear the URL and set source to NULL. (Removing
   a Traefik label makes the synthesized URL disappear; a UI edit
   would stay.)

Runs on every register after `ServiceExposure` rows are updated,
and on every save of the exposure settings page (which calls
`recompute_all()` to iterate every service). Synchronous, no
background job — at homelab scale (~50 services) the recompute
runs in milliseconds.

### 8.7 URL provenance

Two new columns on `service_entry`: `internalurl_source` and
`externalurl_source` (see §5.4). Values: `"ui_edit"`,
`"explicit_label"`, `"synthesized"`, or NULL.

Writers and ordering (later beats earlier):

- The **UI edit handler** in `routes_dashboard.py` sets
  `"ui_edit"` when the operator sets a URL via the form. Clearing
  the field resets source to NULL so synthesis can re-fill from
  remaining exposure observations.
- The **register handler** in `routes_api.py` sets
  `"explicit_label"` when the payload carries `internalurl` or
  `externalurl` (corresponding to a `dockernotifier.std.internalurl`
  or `.externalurl` operator label). Won't overwrite `"ui_edit"`.
- The **synthesizer** sets `"synthesized"`. Won't overwrite
  `"ui_edit"` or `"explicit_label"`.
- NULL is overwritten by anything.

The existing `register_field_ownership` setting (v0.5.0) governs
`group_name` and `sort_priority` only — it's not what protects URL
edits. URL provenance is the v0.6.0 mechanism for that, scoped to
URLs and aware of the synthesizer.

### 8.8 Per-interpreter settings

`Setting` table (§5.4) backs runtime-editable settings. v0.6.0
populates two keys:

- `exposure_layers` — `{"traefik": "internal", "dockflare": "external"}`.
  Layer → direction (`"internal"`, `"external"`, or `"neither"`).
  Default for any layer not listed: `"neither"`. A layer set to
  `"neither"` still produces a badge (so the operator can see it
  exists) but doesn't contribute to URL synthesis.
- `exposure_layers_per_host` —
  `{"docker-edge-vm": {"traefik": "external"}}`. Per-host override.
  Same layer name, different deployment direction (Traefik on a home
  network = internal; Traefik on an edge VPS = external).

New settings tab on `/settings`: lists every layer ever observed in
`service_exposure` (so operators don't see empty config screens
before any interpreter has run) with a direction dropdown per
layer. Per-host overrides section appears when at least one host
has exposure observations attached. Saving calls
`synthesizer.recompute_all()` so the dashboard reflects the new
direction mapping immediately, not on the next register cycle.

### 8.9 Badges + headless rendering

Each tile / table row renders up to three exposure badges, one per
exposure **layer** (rows of the same layer collapse into one badge;
`view_helpers.exposure_layers`), capped with a `+N` overflow indicator
counted in layers. The hover title gives the route count and the distinct
routes.
Badge content:

- Layer name (truncated to 8 chars).
- `🔒` prefix when `tls=true`.
- `🔑` suffix when `auth` is present and not `"none"`.

Tile-level visual budget: on the Tiled view the badges sit in the tile's
bottom row, after the status icons (§15.8); on the table view they sit under
the name. The tiled view and
the table view both render them via `templates/partials/exposure_badges.html`.
The compact view does not — its single-line tile shape has no room.

Headless rendering — a service with zero `ServiceExposure` rows and
no `internalurl` / `externalurl`:

- The tile renders without click affordance (no link wrapping the
  title, no hover-border highlight).
- Status display continues to use `docker_status` (independent of
  URL health checks).
- The `show_urlless=false` filter (§8.1) hides these tiles when
  the operator wants a dashboard that's only clickable services.

### 8.10 Out of scope for v0.6.0

- **Loading YAML interpreters in STD.** The notifier (v0.4.0+) owns
  interpreter execution. STD only consumes outputs over the wire.
- **`kind` field for semantic container categorization** — group +
  exposure data covers the use cases.
- **Graph view.** Network data captured in §5.3 is the seed if it's
  ever revisited.
- **Host-as-entity model** (a `host` table, per-host detail pages,
  aggregation of published ports across all containers on a host).
  Deferred indefinitely — useful but architecturally separate from
  STD's "one row per registered service" shape.
- **Logical service identity** (host-independent). Acknowledged as
  the right long-term direction. `(host, container_name)` remains
  the identity key for v0.6.0.
- **Per-service interpreter overrides.** The operator can't say
  "for this specific service, treat Traefik as external." They use
  an explicit `dockernotifier.std.externalurl` label instead.
- **Badge customization.** Each layer gets a default badge style;
  operators can't change icon/color per layer.
- **Interpreter conflict UI.** If two interpreters disagree on the
  hostname for the same direction (rare — usually they agree), the
  tiebreaker picks deterministically. No conflict-resolution UI in
  v0.6.0; operators who care use an explicit label.

---

## 9. v0.6.1 — UI Rework Part 1 (Delivered)

Patch release shipped 2026-05-16. No schema, API, config, or backend
changes. Templates and static files only.

### 9.1 Goals

Formalize the visual language across all three dashboard views, extract
per-template CSS/JS into shared static files, and deliver the core Tiled
redesign that replaces text pills with an icon vocabulary and adds an
expand drawer for per-service detail.

### 9.2 Extraction

Per-template inline `<style>` and `<script>` blocks consolidated into:

- `static/css/dashboard.css` — design tokens (CSS custom properties),
  shared component classes: `.tile`, `.tile-drawer`, `.status-icon`,
  `.status-pill`, `.exposure-badge`, `.drawer-*`, etc.
- `static/js/dashboard.js` — shared behaviors: auto-refresh, group
  collapse, view-control submit-on-change, filter-input (view-detected
  via `data-view` on `<body>`), tile-click, drawer open/close, tools
  popover, delete confirmation, `toggleGroup`, `copyToClipboard`.

Tailwind CDN stays for layout utilities; custom CSS handles components.
No frontend build step introduced.

### 9.3 Icon vocabulary

Tabler Icons (v3.34.0) loaded via cdnjs CDN. Outline set only.

| Purpose | Icon |
| ------- | ---- |
| Internal URL health | `ti-home` |
| External URL health | `ti-world` |
| Docker status | `ti-brand-docker` |
| Widget indicator | `ti-chart-line` |
| Dozzle logs | `ti-terminal-2` |
| Edit | `ti-edit` |
| Delete | `ti-trash` |
| Tools popover | `ti-tools` |
| Expand/collapse | `ti-chevron-down` / `ti-chevron-up` |

Status colors: green `#22c55e` (ok), amber `#f59e0b` (warn/stale),
red `#ef4444` (bad), gray `#6b7280` (not configured / static).

### 9.4 Tiled redesign

- Tile face: icon + container name; the status/exposure/action row is along
  the bottom (superseded by §15.8; the host shows under the name only when the
  name isn't unique, §15.5).
- Status icon row: internal URL, external URL, Docker,
  separator, widget indicator (if present), Dozzle (if configured),
  edit pencil, expand chevron.
- Tile-headless treatment unchanged: no click affordance or hover border
  on tiles with no URL, no exposures, and no widget. Chevron still shown.
- Expand drawer: absolutely-positioned overlay beneath the tile. Closes
  on outside click or second chevron press. Only one drawer open at a
  time. Contains: host, URLs with health status, Docker with image tag,
  networks, ports, exposure observations, widget data grid. Action row:
  Edit button, Delete button (JS `confirm()` / `prompt()` for static
  entries), Tools popover (Dozzle link when available).

### 9.5 Other view changes

- **Dashboard table:** status pills updated to icon-and-label pairs
  sharing the Tiled vocabulary. Edit column uses pencil icon.
  Dozzle Tools column uses `ti-terminal-2`.
- **Compact tab:** missing `active_tab = 'compact'` variable added;
  tab now correctly highlights in the nav.
- **Exposure badges** (all views): 🔒 / 🔑 emoji replaced with
  `ti-lock` / `ti-key` Tabler icons.
- **Widget toggle removed** from Tiled filter bar; widget data now
  lives in the per-tile drawer.

### 9.6 UI rework arc

v0.6.1 is the first of a multi-release UI overhaul. The actual
sequence that shipped on top of v0.6.1 is documented in §10:

- **v0.6.2** — Hotfix: restored `toggleRestoreSource` dropped during
  the v0.6.1 JS extraction; wired the filename-display feedback on
  /settings restore. (The originally-forecast "edit drawer" did not
  ship and is no longer planned — the edit page got in-place polish
  in v0.6.5 instead.)
- **v0.6.3** — Orphan inline-CSS/JS sweep completing the v0.6.1
  extraction; "what's new" popup; `version_info` context processor.
- **v0.6.4** — Mobile filter bar, two-row tile icon layout, drawer
  scroll-into-view on mobile.
- **v0.6.5** — Edit-page polish, universal delete popover, widget
  modal, auto-refresh pause on interaction.
- **v0.6.6** — Widget drawer mode (replaces the v0.6.5 modal), brand
  exposure icons (replace text-pill exposure badges).

No backend, schema, or API changes shipped in this arc except the
v0.6.6 brand SVG assets under `static/icons/exposure/`. v0.7.0 will
cut when there is a non-UI scoped change to deliver; no fixed date.

---

## 10. v0.6.3–v0.6.6 — UI Overhaul Part 2 (Delivered)

No schema, API, config, or backend changes in this arc except the
addition of `static/icons/exposure/` brand SVG assets in v0.6.6.

### 10.1 v0.6.3 — Foundations

- Orphan sweep: removed remaining per-template inline CSS/JS not cleaned
  up in v0.6.1.
- "What's New" popup: `changelog_modal.html` partial fetches
  `/api/v1/changelog`, compares a `localStorage`-stored last-seen version,
  and surfaces only the new sections. Dismissible, Esc-friendly.

### 10.2 v0.6.4 — Mobile Usability + Tile Icon Restructure

- Filter bar collapses below 640 px behind a toggle button; dismisses on
  click-outside and Esc.
- Status icons split into two rows: status (home, world, docker, widget)
  and actions (Dozzle, edit, trash/lock, chevron). Prevents name
  truncation at mobile font sizes.
- Drawer auto-scrolls the tile into view on mobile on chevron click.

### 10.3 v0.6.5 — Edit Polish, Universal Delete, Widget Modal

- Edit page: tighter inputs, section headings, inline health-check
  checkboxes, tab-style group selector.
- Universal delete popover: all delete affordances share a single
  position-fixed confirm popover. `prompt()`-based confirmation removed.
- Widget data modal: clicking the chart icon opened a centered modal
  overlay showing just that service's widget cards.
- Auto-refresh pause while a drawer, the widget modal, or the changelog
  popup is open.
- One-click trash icons on Tiled tiles and Dashboard rows; static entries
  show a lock icon instead.

### 10.4 v0.6.6 — Widget Drawer + Brand Exposure Icons

**Widget drawer mode.** The v0.6.5 widget modal replaced by a mode of
the existing tile drawer. The `tile-drawer` element gains a two-class
system (`drawer-mode-full` / `drawer-mode-widget`):

- Full mode (`drawer-mode-full`): all drawer sections visible, same as
  the prior chevron behavior.
- Widget mode (`drawer-mode-widget`): CSS hides every `drawer-row`
  except `.drawer-row-widget`, hides the divider and action row.

Clicking the chart icon: opens widget mode if closed; closes if already
widget mode; switches from full to widget mode in-place. Clicking the
chevron: opens full mode if closed; promotes widget mode to full in-place;
closes if already full. Esc and click-outside always close. The
`isInteracting()` refresh-pause check requires no changes — the widget
view is an open drawer (`currentOpenDrawer !== null`). The widget modal
partial, its `base.html` include, `initWidgetModal()`, and the
`.widget-modal` CSS block are removed.

**Brand exposure icons.** Text-pill `.exposure-badge` badges replaced
with 18 × 18 px brand SVG logos. Per layer: brand logo only (v0.9.0
dropped the `ti-lock` TLS and `ti-pencil` hostname overlays; the hover
text carries the route count and each route's hostname/TLS/auth).
Unknown layers fall back to `ti-route`. SVGs committed to
`static/icons/exposure/` with a `README.md` documenting sources.

| Layer | File | Source |
| ----- | ---- | ------ |
| traefik | `traefik.svg` | `traefik/traefik` GitHub — vertical logo, teal symbol crop |
| cloudflare | `cloudflare.svg` | cloudflare.com — `logo-cloudflare-dark.svg`, cloud crop |
| dockflare | `dockflare.svg` | Same as cloudflare.svg (DockFlare = Cloudflare Tunnel wrapper) |
| nginx | `nginx.svg` | nginx.org — `nginx_logo.svg`, green N crop |
| caddy | `caddy.svg` | `caddyserver/website` GitHub — `caddy-circle-lock.svg`, 1:1 icon |

Old `.exposure-badge` CSS replaced with `.exposure-icons` /
`.exposure-icon-layer` / `.exposure-icon-img` / `.exposure-icon-tls` /
`.exposure-icon-label` / `.exposure-icon-fallback` classes.

---

## 11. v0.6.7–v0.6.8 — Registry move and engineering standards (Delivered)

No schema, register-contract, or job changes. Reference for the resulting
release mechanics is §21 (Versioning, Branches, and Releases); this section
records what was delivered and why.

### 11.1 v0.6.7 — Registry move

- Images moved to GHCR (`ghcr.io/crzykidd/service-tracker-dashboard`);
  `dockerhub.yml` was renamed `publish.yml`.
- v0.6.7 was published to both registries. The Docker Hub build set
  `REGISTRY_NOTICE=dockerhub`, which rendered an in-app "moved to GHCR"
  banner; the GHCR build did not. This was the banner-only final Docker Hub
  release. Rationale: [`decisions.md`](./decisions.md).

### 11.2 v0.6.8 — Standards adoption and Docker Hub removal

- Docker Hub publishing, the `REGISTRY_NOTICE` build arg, and the banner were
  removed. Docker Hub tags stay frozen at v0.6.7.
- `VERSION` (bare semver) is the single source of the in-app version; the
  Dockerfile writes `/app/version.txt` from it and the `APP_VERSION` build arg
  is gone. `publish.yml` fails a release whose tag (minus `v`) != `VERSION`.
- CI checks (`Lint`, `Config validation`, `Migration check`,
  `Compose validation`) added in `ci.yml`; GHCR retention added in
  `retention.yml`; CodeQL and the image `build` job are the other required
  checks (§21).
- Release commands `/release-prep` and `/release-cut` added in
  `.claude/commands/`.
- Fixed: Add Entry (`/add`) raised a 500 on a non-numeric sort priority
  (`NameError`); the group dropdown is now also populated on every
  validation re-render.
- Developer tooling: vexp removed; `standards.md`, `prompts/`, and
  `docs/decisions.md` added. See [`HISTORY.md`](./HISTORY.md).

---

## 12. v0.6.9 — Hardening and Safety Net (Delivered)

> **Status:** shipped in v0.6.9 (2026-11-15). Scoped 2026-11-15; each
> subsection was one handoff prompt (named in brackets, now in
> `prompts/done/`), run in the order listed.

A deliberately large **patch** release that bundles the post-v0.6.8
review findings: two real bugs, a security pass, a test suite, a
delete safety net, and runtime/operational upgrades. It is a patch,
not 0.7.0, so `/release-prep` does not run the minor-release CHANGELOG
archive step (decision: [`decisions.md`](./decisions.md), 2026-11-15).

**Cross-repo:** no register-contract change. Nothing in this release
adds, removes, or re-types a `RegisterPayload` field, so the
consumer-leads ordering rule (§22) is not engaged and every notifier
version that works with v0.6.8 works with v0.6.9. The only
register-path behavior change is §12.5's resurrect-on-register for
soft-deleted rows, which is server-side only.

### 12.1 Test suite and CI `Test` check [`v069-01-test-suite`] — Delivered in v0.6.9

- `pytest` suite under `tests/`, dev dependencies in
  `requirements-dev.txt` (not shipped in the image).
- **Testability seam:** `app.py` and `settings_loader.py` hardcode
  `/config/...` paths and `app.py` builds the app at import. Introduce a
  `STD_CONFIG_DIR` environment variable (default `/config`) that every
  `/config` path derives from, so tests run against a temp dir. Tests
  build the schema with `db.create_all()`; Alembic correctness stays
  with the `Migration check` job.
- Initial coverage, written against the *current* behavior (pins what
  v0.6.8 does, including the bugs §12.3 fixes — those tests are
  `xfail` until §12.3 flips them): register auth, `extra="forbid"` → 400,
  `exposure_observations` absent vs `[]`, URL provenance ordering,
  `register_field_ownership` modes, settings loader precedence
  (ENV > file > default).
- New `Test` job in `ci.yml`. The `Test` exemption in `standards.md` is
  removed. Adding `Test` as a **required** check in GitHub branch
  protection is a manual operator step (the prompt does not touch
  GitHub settings).
- **As built:** `STD_CONFIG_DIR` (read in `settings_loader.CONFIG_DIR`) also
  drives the `backup_path` default and the `/config/backups` fallbacks in
  `jobs.py` / `routes_dashboard.py`. `tests/conftest.py` sets the env and
  creates a temp config dir at import time, before `app` is imported (so
  `app.py` is unchanged structurally). Icon downloads are stubbed in tests.
  Two `xfail(strict=True)` tests pin the §12.3 bugs.

### 12.2 Wider lint [`v069-02-widen-lint`] — Delivered in v0.6.9

- `ruff.toml` widens from `E9, F` to `E, W, F, I, B` (E501 ignored —
  line length is not worth the churn). One mechanical cleanup pass;
  no behavior changes. Any `B` finding that is a real bug is fixed and
  gets a CHANGELOG `Fixed` entry; anything ambiguous is
  `# noqa`-annotated with a reason rather than "fixed" blind.
- **As built:** the cleanup found 30 findings (20 `I001`, 4 `E402`,
  2 `B009`, 2 `B010`, 2 `W291`); none was a real bug (the `B009`/`B010`
  were constant-name `getattr`/`setattr`, rewritten as plain attribute
  access). `alembic/versions/*` is exempt from `I001`/`W291` and
  `alembic/env.py` from `E402` (intentional `sys.path` setup) via
  `per-file-ignores`.

### 12.3 Settings and API-token hardening [`v069-03-settings-and-token-hardening`] — Delivered in v0.6.9

- **Fix:** `settings_loader.VALID_KEYS` omits
  `widget_value_retention_days` and `register_field_ownership`, so both
  documented settings are silently dropped and their defaults always
  apply. Add them (and every other key `settings.example.yml`
  documents). A test asserts every key in `settings.example.yml` is in
  `VALID_KEYS`, so new settings can't regress this.
- **Fix:** with `API_TOKEN` unset, `_check_bearer_auth` compares against
  the string `"Bearer None"` and accepts it. New behavior: no token
  configured → `/api/v1/register` returns **503**
  `{"error": "API token not configured"}`; a WARNING at startup; a
  notice on Settings → Service Info. The UI keeps working (rejected:
  failing startup — it breaks UI-only installs).
- Token comparison uses `hmac.compare_digest`.
- Startup settings logging masks `api_token` (and any future secret
  keys) instead of printing them.
- **Default-credential warnings:** if `FLASK_SECRET_KEY` is unset (the
  `"changeme-in-prod"` fallback is in use) or the `admin` user still
  has the `changeme123` password, log a WARNING at startup and show a
  dismissible notice on Settings for admins. No forced change.
- **As built:** `widget_value_retention_days` (int, 30) and
  `register_field_ownership` (str, `user_wins`) added to `VALID_KEYS`; a test
  parses `settings.example.yml` (including `#key:` lines) against
  `VALID_KEYS`. `settings_loader.SECRET_KEYS` / `mask_value()` mask secrets
  in all startup/debug settings logs. `routes_auth.refresh_default_password_flag()`
  computes the `changeme123` check once at startup and after password
  set/reset, caching it in `app.config["DEFAULT_ADMIN_PASSWORD_IN_USE"]`
  (`DEFAULT_SECRET_KEY_IN_USE` likewise). The Settings dismissal is per
  browser session (`sessionStorage`). The two §12.1 `xfail` tests are now
  passing tests.

### 12.4 CSRF protection [`v069-04-csrf`] — Delivered in v0.6.9

- `Flask-WTF` `CSRFProtect` on the app. Every HTML form posts
  `csrf_token()`; `base.html` carries a `<meta name="csrf-token">` and
  every JS `fetch` POST sends it as `X-CSRFToken`.
- `/api/v1/register` is exempt (bearer-token API, no cookies).
- `WTF_CSRF_TIME_LIMIT = None` — tokens live as long as the session, so
  a dashboard left open for hours doesn't 400 on the next delete.
- CSRF failure: HTML forms flash an error and redirect back; JSON
  endpoints return `400 {"error": "CSRF token missing or invalid"}`.
- As built: `csrf = CSRFProtect()` in `extensions.py`, initialized in
  `create_app()`; a `CSRFError` handler in `app.py` treats a request as
  JSON when `request.is_json`, the path starts with `/api/`, an
  `X-CSRFToken` header is present, or `Accept` includes `application/json`.
  JS POSTs go through the shared `window.stdPost(url, options)` helper in
  `static/js/dashboard.js`. Tests enable CSRF only in `tests/test_csrf.py`.

### 12.5 Soft-delete for service entries [`v069-05-soft-delete`] — Delivered in v0.6.9

Picks up the FUTURE.md "Soft-delete for service entries" entry.

- **Schema:** `service_entry.deleted_at` (`DateTime`, nullable,
  indexed) via Alembic.
- **Delete** (edit page, `/api/v1/entries/<id>/delete`, tile/row trash
  icons) sets `deleted_at` instead of deleting. Widget rows are left
  attached.
- **Filtering:** soft-deleted rows are excluded from all three
  dashboards, the health-check loop, widget refresh, badges, and the
  `/dbdump` default view. Implement as one model-level helper
  (e.g. `ServiceEntry.active()`), and audit every `ServiceEntry.query`
  call site — there are ~18.
- **Settings → Deleted** lists soft-deleted entries as cards (name, host,
  deleted at, days until purge) with **Restore** and a ⋯ menu with
  **Delete permanently** (the latter goes through §12.6's hard-delete
  path; the confirm dialog keeps its text).
- **Purge job:** daily at 00:25 hard-deletes rows whose `deleted_at` is
  older than `deleted_retention_days` (new setting, default `30`,
  `0` = purge on the next run).
- **Resurrect on register:** a register for a `(host, container_name)`
  that matches a soft-deleted row **clears `deleted_at`** and updates
  that row, keeping all curated state. Rationale: today a hard-deleted
  running container reappears empty on its next register; resurrecting
  the curated row is strictly better, and keeping a live container
  invisible would be worse. Logged at INFO.
- **Backup/restore:** YAML backups include `deleted_at`; restore
  round-trips it. Backups from v0.6.8 restore with `deleted_at` NULL.

As built: migration `e5a1c7d93b02`; `ServiceEntry.active()` /
`.deleted()` helpers and a single `hard_delete_entry(entry)` in
`models.py` (the pre-existing widget-if-unused delete moved there
unchanged; §12.6 changes only that function). Deviations from the plan
above: `/dbdump` shows deleted rows **marked** (struck through, Deleted
At column) rather than hiding them; the register lookup prefers an
active row over a deleted one; a static-locked deleted entry is not
resurrected by register (static skip wins); the Group `services_count`
badge counts active entries only and deleting a group detaches its
soft-deleted entries (`group_id` → NULL); the widget refresh skips
widgets whose services are all soft-deleted; `recompute_all` and the
scheduled/manual backups deliberately include deleted rows. New routes:
`POST /settings/deleted/<id>/restore` and `/delete` (admin, CSRF).

### 12.6 Widget detach on hard delete [`v069-06-widget-detach`] — Delivered in v0.6.9

- When a service entry is hard-deleted (purge job or Delete
  permanently), its widget is **detached**, not deleted: the `Widget`
  row and its `widget_value` history are kept (retention still prunes
  values normally).
- A widget is **detached** when no service entry (active or
  soft-deleted) references it. Detached widgets are skipped by the
  widget refresh job.
- **Settings → Deleted** gains a "Detached widgets" list of cards:
  **Attach to service** (picker of entries with no widget) or, in the ⋯
  menu, **Delete** (removes the widget and its values).

As built: `Widget.detached()` (no `ServiceEntry` references it);
`hard_delete_entry` now only deletes the entry. Routes (admin, CSRF):
`POST /settings/widgets/<id>/attach` (form field `entry_id`, active entries
with `widget_id IS NULL` only) and `POST /settings/widgets/<id>/delete`. The
refresh job now refreshes only widgets with at least one **active** service,
so it skips both detached widgets and widgets referenced only by soft-deleted
entries (this also stops refreshing pre-existing unreferenced widget rows).
The edit page was left unchanged (it edits a widget in place; choosing "none"
still deletes it deliberately).

### 12.7 Unified staleness indicator [`v069-07-staleness`] — Delivered in v0.6.9

- Today staleness is shown only on the Tiled view, and the logic is
  split: the model property uses 5 minutes and the template adds a
  redundant 120-minute clause.
- One threshold, new setting `stale_after_minutes` (default `5`, which
  keeps current Tiled behavior; the notifier re-scans every 60 s by
  default). `ServiceEntry.is_docker_status_stale` reads it; the
  template clause is removed.
- The stale indicator (same icon/tooltip vocabulary as Tiled) appears
  on the Dashboard table and Compact views too. Static entries are
  never stale. This is the staleness-visualization prerequisite named
  in FUTURE.md's duplicate-detection entry; the same threshold will be
  reused there.
- **As built:** Dashboard shows a `ti-clock-exclamation` warn icon beside
  the Docker pill; Compact shows the same icon right-aligned in the tile
  (the Tiled icon turns amber as before). Both appear only for dynamic
  entries that have a `last_api_update` and are stale; a never-updated
  dynamic entry still counts as stale in the model but Tiled keeps its
  separate red "no update received" state, and Dashboard keeps its red
  pill. Outside an app context the threshold falls back to 5.

### 12.8 Per-service health-check options [`v069-08-health-check-options`] — Delivered in v0.6.9

Resolves the Open Question on health-check timeouts (§23).

- **Schema:** `service_entry.health_check_timeout` (Integer seconds,
  nullable → use the global default) and
  `service_entry.health_check_verify_tls` (Boolean, NOT NULL, server
  default true).
- New global setting `health_check_timeout` (default `5`, today's
  hardcoded value).
- Edit page gains both fields in an advanced section. Both are
  operator-curated, not register fields — the notifier never sends them
  (no contract change).
- `verify_tls = false` passes `verify=False` to `requests` and
  suppresses the urllib3 InsecureRequestWarning for that call only.
- **As built:** the per-URL check is `jobs.check_url(url, entry,
  default_timeout)`; timeout is `entry.health_check_timeout` or the
  global setting. The edit page has an "Advanced health check" section;
  the Add page carries the same two fields (verify defaults on).
  Timeout is validated as a whole number 1-60 (blank = default); an
  invalid edit-page value is rejected with a warning and the stored
  value kept. Both fields round-trip through YAML backup/restore
  (absent in older backups = global timeout, verify on). No register
  contract change: `schemas.py` untouched and `upsert_service` never
  writes either column.
- Out of scope: concurrent health checks. Sequential checks with longer
  per-service timeouts lengthen a pass; acceptable at homelab scale.

### 12.9 Production WSGI server and pinned dependencies [`v069-09-gunicorn-and-pins`] — Delivered in v0.6.9

- The image runs **gunicorn** instead of the Werkzeug dev server
  (`python app.py`). **Exactly one worker** (`--workers 1`, several
  threads): the register mutex, APScheduler, and the health-check
  thread are all in-process and must not be duplicated. Startup work
  now in `__main__` (default admin, icon verify, background workers)
  moves to a function invoked once from a `gunicorn.conf.py` hook.
- `python app.py` keeps working for local development.
- `requirements.txt` becomes fully pinned (generated from a
  `requirements.in` with `uv pip compile`); the Dockerfile installs the
  pinned set.
- Operator-visible: log format at startup changes (gunicorn lines); no
  config change required. Port stays 8815.
- **As built:** `app.run_startup_tasks(app)` (idempotent per process) does the
  default admin, icon sweep and `start_background_workers`; `__main__` and
  `gunicorn.conf.py`'s `post_worker_init` both call it. `workers = 1`,
  `threads = 4`, no `preload_app`. `entrypoint.sh` runs gunicorn unless
  `FLASK_DEBUG=1`, which keeps `python app.py`. Pins come from
  `requirements.in` via `uv pip compile --python-version 3.11`; the image
  is built for linux/amd64 only (publish.yml sets no platforms).

### 12.10 Docs loose ends [`v069-10-docs-loose-ends`] — Delivered in v0.6.9

- CHANGELOG: replace the `2026-XX-XX` placeholder dates on 0.1.x–0.4.x
  with the real git-tag dates (all **2025**; e.g. v0.4.0 2025-06-05,
  v0.4.14 2025-07-12; series headers use the first tag's date).
- Add an MIT `LICENSE` file (the README already links one).
- README: replace the v0.6.0 `/api/register` top banner with a short
  current-compatibility note; reword "GHCR images start at v0.6.7" so it
  doesn't age.
- Out of scope (upstream): the stale `release-prep-and-cut @ v1.0.0`
  text in the CLAUDE.md snippet and `.claude/commands/` headers is
  stale in `homelab-configs` itself; fix it there, then re-sync.
- README screenshots remain stale (needs a live instance; not
  agent-doable).
- As built: dates taken from tags (0.3.x/0.2.x/0.1.x series use v0.3.0
  2025-05-31, v0.2.0 2025-05-27, v0.1.0 2025-05-26). The What's New
  parser skips `[0.x.x] series` headers (no match), so they are inert.

### 12.11 CodeQL path and redirect fixes [`v069-11-codeql-path-and-redirect`] — Delivered in v0.6.9

Closes 13 open CodeQL alerts on `main`: 11 `py/path-injection` and 2
`py/url-redirection`.

- **Icon names** (register `image_icon` and derived names, `/add`, `/edit`)
  go through `image_utils.safe_icon_filename` (lowercase, optional `.svg`
  stripped, `^[a-z0-9][a-z0-9._-]*$`, no `..`, at most 100 chars including
  `.svg`). The path is then checked with `icon_path_in_dir` (`realpath`
  containment in `IMAGE_DIR`) before any write. Register skips an unsafe icon
  with a WARNING and still succeeds; Add/Edit flash a message and download
  nothing (Edit leaves the stored icon unchanged and saves the other fields).
- **Backup restore from a server file** accepts only a bare filename ending
  `.yaml`/`.yml` whose resolved path stays inside the backup folder.
- **`/widget_config/<widget_name>`** accepts only directory names present
  under `widgets/`, resolved from the app root rather than `/app/widgets`.
- **Redirects:** `view_helpers.safe_redirect_target` allows only same-site
  relative paths (single leading `/`, no scheme/netloc, no `//` or `/\`).
  Used for the edit page's `ref` (save, delete, and the wrong-confirmation
  bounce) and the CSRF error handler's referrer fallback.
- As built: the Add page's `ref` was parsed but never used, so that dead code
  was removed rather than hardened. The Add and Edit templates do not render
  flashed messages (only Settings does), so the invalid-icon message is
  queued for the next Settings view rather than shown inline; see
  `docs/decisions.md`.

---

## 13. v0.7.0 — Dashboard and Monitoring (Delivered)

> **Status:** shipped in v0.7.0 (2026-11-15). Scoped 2026-11-15. Each subsection is one handoff
> prompt (named in brackets, in `prompts/`), run in the order listed.
> Each chunk left the app working and the test suite green.

A **minor** release with one theme: turn STD from a Docker inventory
with URL pings into a **dashboard with simple monitoring**. That means
three things:

1. Non-Docker sites (router, NAS, SaaS, a printer) are a first-class
   **manual** entry, not a fake container.
2. Health checks become their own model, with a new **service check**
   (HTTP/HTTPS status or body, TCP, ping) next to the internal and
   external URL checks.
3. **7 days of check history** with a Gatus-style 24-hour bar strip in
   the detail view, plus a health **status filter** on every view.

Because it is a minor, `/release-prep 0.7.0` runs the per-minor
CHANGELOG archive step, which archives every closed series (0.1.x–0.6.x)
into `docs/CHANGELOG-<minor>.x.md`. The 0.1.x–0.3.x blocks are
`## [0.N.x] series — <date>` headers, not `## [0.N.PATCH]`. The
release-prep run must treat each as the whole of its series and archive
it as `docs/CHANGELOG-0.N.x.md`.

**Cross-repo:** **no register-contract change.** The notifier keeps
sending exactly what it sends today; `schemas.py` is untouched, so the
ordering rule (§22) is not engaged. Every notifier version that works
with v0.6.9 works with v0.7.0. `internal_health_check_enabled` /
`external_health_check_enabled` keep their meaning: they enable or
disable the entry's `internal_url` / `external_url` check rows. A
notifier-defined service check (from container labels) would be a
new register field. That is parked in FUTURE.md; if picked up, STD
accepts the field and ships first.

### 13.1 Concepts

- **Entry**: one thing on the dashboard. Its **source** is `notifier`
  (created and kept current by `/api/v1/register`) or `manual` (created
  on the Add page).
- **Check**: one configured probe on an entry. Three kinds:
  - `internal_url` and `external_url` probe the entry's URL of that
    name, so they always follow the current URL, including synthesizer
    changes. Each entry has exactly one of each (possibly disabled).
  - `service` checks have their own target and type. An entry can
    have zero or more.
- **Result**: one sample (`ok` true/false, latency, status code,
  message). Every check produces a **health or failure**. The detail
  is in the message.
- **Health state** of an entry, rolled up from its enabled checks:

  | State      | Meaning |
  |------------|---------|
  | `up`       | nothing that has run is failing |
  | `degraded` | some URL/service checks ok and some failing (Container passing) |
  | `down`     | the Container check is failing, or every URL/service check that has run is failing (even with the container running) |
  | `unknown`  | checks are enabled but none has run yet |
  | `none`     | no enabled checks |

  Docker state counts: every notifier entry has an automatic **Container**
  check (§13.8). The Container check counts on its own; the other checks
  (URL and service) are judged as a group (§13.6, v0.9.0 step 8). The Docker pill and stale icon on the views stay as well.

### 13.2 Entry sources and manual entries [`v070-01-entry-sources`] — Delivered in v0.7.0

**As built:** migration `a7c3e9f15d28` adds `service_entry.source` (backfilled
by the rule below), `description`, and makes `host` nullable.
`ServiceEntry.is_manual` is true for `source == 'manual'`;
`is_docker_status_stale` is false for manual or locked entries.
`upsert_service` adopts an unlocked manual match (INFO log, `source` becomes
`notifier`); a soft-deleted manual match is adopted and resurrected by the same
path. New register rows are `notifier`; `schemas.py` is untouched. The Add
page (`name`/`container_name`, optional host, description) creates manual
entries; the duplicate check matches `host IS NULL` explicitly and prefers an
active row over a soft-deleted one. Edit hides the "Reported by notifier"
block for manual entries and shows Description; blank Host saves as NULL for
manual entries only. Dashboard shows a "Manual" pill and Tiled a `ti-link`
icon where the Docker pill sits; Compact is unchanged apart from the stale
icon no longer appearing for manual entries. Backups export `source` and
`description`; restore without `source` applies the backfill rule, and a
record without a host is skipped unless it is manual.

- **Schema** (§5.6): `service_entry.source`, nullable `host`,
  `description`.
- **Backfill:** `last_api_update IS NULL` → `manual`, else `notifier`.
- **Manual entries**:
  - Fields: Name (stored in `container_name`, labelled "Name" in the
    UI), optional Host, Description, Group, Icon, URLs, sort priority.
  - No Docker fields: container id, stack, image, Docker status,
    started-at and the "Reported by notifier" block are hidden on Edit.
  - Never stale. Duplicate check on Add is (host, name), with an empty
    host treated as its own value.
- **Notifier entries**: behave as today. `is_static` is relabelled
  **"Lock (ignore notifier updates)"**. It no longer means "manual",
  and staleness is suppressed by `source == 'manual'` or the lock.
- **The Add page creates manual entries only**; Docker entries come
  from the notifier. Its wording changes from "application" or
  container to "Name".
- **Register adoption:** a register whose (host, container_name)
  matches an unlocked **manual** entry adopts it: `source` becomes
  `notifier` and the register updates it as usual. This preserves
  today's "pre-stage an entry, then the notifier fills it in"
  behaviour. A locked manual entry still returns `skipped`. A manual
  entry with no host can never be matched.
- **Backups** carry `source` and `description`. An older backup with no
  `source` is backfilled by the same rule as the migration.
- Dashboard and Tiled show a small source icon (Docker vs manual) where
  the Docker pill sits today; manual entries show no Docker pill.

### 13.3 Health-check schema and data migration [`v070-02-health-schema`] — Delivered in v0.7.0

**As built:** migration `b8e4d6a2c1f9` creates `health_check` and
`health_result` (indexes `ix_health_check_service_entry_id` and
`ix_health_result_check_id_ts`) and inserts both URL-kind rows for every
entry from the legacy columns; its downgrade copies `enabled`, timeout and
verify-TLS back to the legacy columns, then drops both tables. Models
`HealthCheck` / `HealthResult` and `ServiceEntry.checks` are in `models.py`,
with `ServiceEntry.url_check('internal'|'external')`, `.service_checks`,
the convenience properties `internal_check_enabled`, `external_check_enabled`,
`url_check_timeout`, `url_check_verify_tls`, and `ensure_url_checks(entry)`
(called by register create and update, Add, Edit and restore). The legacy
`last_checked_at` is converted from server-local to naive UTC in the
migration. The interim checker is `jobs.run_url_checks_once(app)` (called by
`health_check_loop`), using `jobs.probe_url(url, check, default_timeout)`
(replacing `check_url`); a status below 400 is ok. It writes one
`HealthResult` per check per pass, updates the check's `last_*` and
`consecutive_failures`, and mirrors the status string and a local
timestamp into the legacy `*_status` / `*_update` columns (marked
`# TEMP: removed in v070-05`). The Dashboard, Tiled and Edit templates read
`enabled` and the shared timeout/verify values from the check rows. Backups
export `checks` (config only, via `HealthCheck.to_config()`); the legacy
`*_enabled`, `health_check_timeout` and `health_check_verify_tls` keys are
still written, derived from the rows, so an older STD can restore them.
Restore of a backup with `checks` applies URL rows by kind and replaces
service rows wholesale; a backup without `checks` maps the legacy keys onto
both URL rows. The migration test and the interim loop are in
`tests/test_health_schema.py`.

- **Tables** `health_check` and `health_result` (§5.6), with models
  `HealthCheck` and `HealthResult`, and `ServiceEntry.checks`
  (cascade delete).
- **The migration** creates an `internal_url` and an `external_url`
  check for every entry. It copies enabled, timeout and verify-TLS
  from the entry columns, and seeds `last_*` from the legacy status
  strings (a numeric code under 400 = ok; anything else = failing,
  with the string as the message).
- **New entries get both URL-kind rows:** the register create path, the
  Add page and backup restore all create them.
- **Register:** `internal_health_check_enabled` /
  `external_health_check_enabled` set `enabled` on the matching row.
  Absent means no change, as today.
- **Add/Edit:** the existing toggles plus the timeout and verify-TLS
  fields now read and write the check rows, so no visible change yet.
- **Backups** export each entry's check *configuration* as a list (no
  results). An older backup without `checks` is mapped from the legacy
  columns.
- **Legacy columns are deprecated:** no new code reads them. Until
  §13.6 swaps the templates, the checker (§13.4) mirrored URL-kind
  results into the legacy `*_status` / `*_update` columns so the
  old badges kept working; §13.6 removed that mirror.

### 13.4 Checker engine and history retention [`v070-03-checker-engine`] — Delivered in v0.7.0

- **Replaces `health_check_loop`.**
  - A scheduler thread wakes every 5 s, finds due checks (enabled, entry
    active, URL-kind with a URL present, `last_checked_at + interval <=
    now`) and submits them to a `ThreadPoolExecutor`.
  - Pool size: new setting `health_check_workers`, default 8.
  - Workers do network I/O only and return a result. The scheduler
    thread does every DB write (SQLite single-writer; no session use in
    worker threads). An in-flight set prevents double submission.
- **Intervals**: per-check `interval_seconds` (minimum 30) or the
  existing global `url_healthcheck_interval`. The timeout is per-check
  or the global `health_check_timeout`.
- **Check types**:
  - `http`: covers HTTP and HTTPS, chosen by the URL scheme. A GET that
    follows redirects, with verify-TLS per check. Two modes:
    - **`status`** (default): an HTTP status below 400 = ok. The
      message is the exception class and text, or for a failing code
      (400+) `<code>: <reason>` from the body (§15.6), else the code.
    - **`body`**: reads at most 4 KB of the response.
      - Body (trimmed) equals `OK` (case-insensitive) → ok.
      - Body starts with `Error:` → failing, message = the text after
        the prefix (trimmed, up to 200 chars).
      - Anything else → failing, `Unexpected response: <first 60
        chars>`.
      - Status 400 or above → failing, using the `Error:` text if
        present, else the status.
  - `tcp`: target `host:port`. A connect within the timeout = ok, and
    latency is the connect time.
  - `ping`: ICMP echo via `icmplib` (new pinned dependency), 3 packets,
    ok if any reply. The image runs as root and Docker's default
    capability set includes `NET_RAW`. If a privileged socket fails, it
    retries unprivileged; if both fail, the result is failing with
    `ICMP not permitted`.
- **Results**: each run writes one `health_result` row and updates the
  check's cached `last_*` fields and `consecutive_failures`.
- **History retention** (new settings):
  - `health_raw_hours` (default 24): every sample is kept raw for this
    long.
  - `health_history_days` (default 7): total history.
  - An hourly compaction job (at :05) handles raw rows older than
    `health_raw_hours`:
    - **Failures are kept as individual rows** until
      `health_history_days`.
    - **Successes** are merged into one range row per (check, clock
      hour, unbroken run of successes): `ts` = first sample, `ts_end` =
      last, `samples` = count, average and maximum latency. A failure
      inside an hour splits the range.
  - Rows older than `health_history_days` are deleted. Bound per check:
    about 24h of raw samples plus at most 2 rows per hour for the rest
    of the week, plus failures.
  - **Uptime %** = Σ `samples` where ok ÷ Σ `samples`, over 24 h or 7 d.
- **Check now**: `POST /service/<id>/checks/run` (login and CSRF)
  queues all of that entry's enabled checks for the next scheduler tick.
  The request is held in memory (`jobs.request_run`), not by clearing
  `last_checked_at`, so the last result stays visible until the new one
  lands.

**As built:** probes live in `checker.py` (`probe_http`, `probe_tcp`,
`probe_ping`, `run_probe`; each returns a `ProbeResult(ok, latency_ms,
status_code, message, error_type)` and never raises). The scheduler is
`jobs.HealthScheduler` (`select_due_jobs` builds plain-dict jobs, workers run
`_run_job`, `collect()` and `record_check_result()` do every write on the
`health-check-loop` thread, 5 s tick, per-tick app context). Service-kind
checks with a target are scheduled too, ahead of their UI (§13.5). The URL
rows mirrored into the legacy `*_status` / `*_update` columns until §13.6
(removed there). Settings: `health_check_workers` (8), `health_raw_hours` (24),
`health_history_days` (7). Jobs: `compact_health_results` (hourly at :05) and
`purge_health_results` (hourly at :03). Compaction only touches clock hours
that lie wholly before `health_raw_hours` ago (one commit per check and
hour), a lone sample becomes a range of one (`ts_end = ts`), and purge
treats a range as old once its `ts_end` is. `icmplib==3.0.4` is pinned. No
schema change.

### 13.5 Check configuration UI [`v070-04-check-config-ui`] — Delivered in v0.7.0

- **Edit page "Health checks" section** replaces the two toggles and the
  v0.6.9 "Advanced health check" block:
  - **Internal URL check / External URL check**: enabled, mode (status
    or body), interval, timeout and verify TLS. The target is shown
    read-only as the current URL.
  - **Service checks**: a list with add and remove. Each has a name,
    type (HTTP/HTTPS, TCP, Ping), target, mode (HTTP only), interval,
    timeout, verify TLS (HTTP only) and enabled.
- **Validation**:
  - HTTP target must be an `http(s)://` URL.
  - TCP target must be `host:port` with a port from 1 to 65535.
  - Ping target must be a hostname or IP.
  - Interval must be 30–86400 s; timeout 1–60 s.
- **Add page**: the same section. A manual site usually gets one service
  check.
- **Flash messages on Add and Edit:** validation errors are shown inline
  on these pages; today they only appear later on Settings (closes the
  v0.6.9 QoL item).
- Notifier entries can carry service checks too. They are operator
  data; register never touches `service` rows.
- **As built:** `check_form.py` parses, validates and applies the section
  (shared by Add and Edit); `partials/health_checks_form.html` renders it
  and `static/js/health_checks_form.js` clones a `<template>` row. Fields:
  `uc_<internal|external>_<enabled|mode|interval|timeout|verify>` and, per
  service row, `svc_row` plus `svc_<key>_<id|name|type|target|mode|interval|timeout|verify|enabled>`;
  a hidden `checks_form` marker means "section submitted" (absent leaves
  checks untouched). Every error is flashed (`danger`) and the page
  re-renders with all input kept; nothing is saved. Rows are matched by id;
  saved service checks missing from the post are deleted, results cascade;
  an id belonging to another entry is rejected. A blank service-check name
  defaults to its target; at most 20 service checks per entry. Non-HTTP
  checks store mode `status` and verify on. A changed check or URL clears
  `last_checked_at`. `partials/flash_messages.html` is shared by Settings,
  Add and Edit. The old single timeout / verify-TLS fields are gone.

### 13.6 Health rollup, badges, and filters [`v070-05-rollup-and-filters`] — Delivered in v0.7.0

- **Tint (v0.9.0, §15.10).** Degraded and down entries also get a soft
  amber/red background on all three views.
- **`health.py` is unchanged** (liveness). The rollup lives in a new
  `health_state.py`:
  - `entry_health(entry)` returns the state (§13.1), the counts, and the
    worst message.
  - Loaded with one query per page (checks joined, no N+1).
- **One badge partial** (`partials/health_badge.html`) used by Dashboard,
  Tiled and Compact:
  - Shows a single coloured state dot or pill (up / degraded / down /
    unknown / none), with the failing check names and messages in the
    tooltip.
  - Replaces every template-side parse of the legacy status strings
    (`.isdigit()`, `'Error: SSLError'`).
  - The legacy-column mirror from §13.3 is removed.
- **Filter bar** (all three views; query params handled in
  `view_helpers.py` next to `show_urlless`, kept across refresh):
  - `status` = `all` (default) / `failing` (degraded or down) /
    `healthy` (up) / `unknown` (unknown or none) / `stale` (notifier
    entries that are stale).
  - `source` = `all` / `notifier` / `manual` / `stream` / `stream:<stream_id>`
    (one inventory stream, §18.8).
- The filter bar shows **Total / Passing / Failing** count chips (v0.7.1), each a link
  that sets `status` to `all` / `healthy` / `failing`. They count entries
  after `source` and `show_urlless` but ignoring `status`, so each number
  equals what its link shows.

**As built:** `health_state.entry_health(entry)` returns a frozen
`EntryHealth(state, total, failing, failures)` (plus `label` / `tooltip`).
A check counts when it is enabled and has something to probe (a URL check
whose URL is empty is skipped, since the scheduler never runs it). `none` =
nothing counts; `unknown` = none has run; otherwise failing checks among those
that have run decide the state. Since v0.9.0 step 8 (§15.6): a failing
Container check = `down`; otherwise the URL/service checks form a group
where all-failing = `down`, some = `degraded`, none = `up`. Every consumer
(badge, `status` filter, count chips, `/health/summary`, `GET /entries`) goes
through `entry_health`; `health_summary` no longer has its own rule.
Checks still waiting for a first run do not hold `up` back. The three view
handlers share `_load_view_entries()`, which `selectinload`s `checks`, so the
page query count is flat in entry count (tested). `partials/health_badge.html`
has three variants (`pill` Dashboard, `icon` Tiled, `compact` dot linking to
`/edit/<id>#health`; the Edit page's checks section carries `id="health"`).
Dashboard gets a Health column; its INT/EXT pills and Tiled's URL icons are
plain links. `view_helpers` adds `normalize_status_filter` /
`normalize_source_filter` (unknown values fall back to `all`) and applies both
before grouping. `stale` is `source == notifier and is_docker_status_stale`.
The filter selects use `view-control`, so the existing JS keeps them in the
URL. The count chips come from `view_helpers.health_counts` (one rollup per
entry, no extra queries; Unknown and Not monitored count in Total only) and
`routes_dashboard._health_count_context`, which builds each link server-side
from `request.args` so all other params persist and marks the active chip with
`aria-current="true"`. The old `shown / total` text is gone. The legacy
mirror and `checker.legacy_status` are gone: nothing reads the deprecated
`*_health_check_status` / `_update` columns except `dbdump.html` and restore;
backups still emit those keys, derived from the check rows. New filter
`time_since_utc` renders the naive-UTC check timestamps.

### 13.7 Health detail and 24h history [`v070-06-health-detail`] — Delivered in v0.7.0

- **Endpoint** `GET /service/<id>/health?range=24h|7d` (login required,
  JSON). For each check it returns the config summary, the current
  state, uptime % for 24 h and 7 d, the most recent failures (up to 20)
  and a bar series:
  - `24h`: 48 half-hour bars.
  - `7d`: 168 hourly bars, each with `ok_samples`, `fail_samples` and
    up to 3 failure messages. A range row that spans bars is split by
    time-proportional sample count.
  - A bar is green when all its samples are ok, red when any failed,
    and grey when there were no samples.
- **Detail panel** (`partials/health_detail.html` plus
  `static/js/health_detail.js`), fetched lazily when opened:
  - One block per check: name/kind, type and target, state, last
    checked, latency, last message, and uptime for 24 h / 7 d.
  - A Gatus-style bar strip with a hover tooltip (time range, ok/fail
    counts, messages), a 24h / 7d toggle, and a list of recent
    failures.
  - A **Check now** button (uses `stdPost`).
- **Where it appears:**
  - **Tiled**: inside the existing tile drawer.
  - **Dashboard**: a new expand row under each entry.
  - **Edit page**: above "Reported by notifier".
  - **Compact** has no drawer; its badge links to the Edit page's
    health section.
- Rendering uses plain divs and CSS (no chart library).

**As built:** `health_history.py` holds the pure functions: `bars(check,
range, now)`, `uptime(check, hours, now)`, `recent_failures(check, limit=20)`
and the payload builders. Buckets are aligned to the clock (half-hour or
hour boundaries, the last bar is the current partial one). A range row is
split across the buckets it overlaps by time-proportional sample count
(largest-remainder rounding, total preserved; portions outside the window
are dropped); a range of one or a raw row lands in a single bucket. Up to 3
distinct failure messages per bar. `GET /service/<id>/health?range=` (login,
404 for missing or soft-deleted; an unknown `range` falls back to `24h`)
returns every *enabled check with a target*: config summary, state
(`up`/`down`/`unknown`), last checked (ISO, `Z`), latency, message, 24 h and
7 d uptime (null with no samples), `failures`, `bars`. The shell is
`partials/health_detail.html`; `static/js/health_detail.js` fetches lazily
(Tiled drawer open, Dashboard row expand; autoloaded on Edit), re-fetches
on the 24h/7d toggle, renders with DOM calls (no innerHTML of server text),
and drives the tooltip and Check now (`stdPost`, then re-fetch every 2 s until every shown check has a result newer than the request's `requested_at`, up to 75 s).
Dashboard gets a leading chevron column and an expand row (group-header
`colspan` is now 13); an open row pauses auto-refresh like an open drawer.
The Edit page panel is a "Health history" block after the form, above
"Reported by notifier".

**Inline uptime strips (v0.7.1).** A "Show uptime" checkbox
in the filter bar (all three views, next to Show URL-less) is remembered in
the `std_show_uptime` cookie (`1`/`0`, `Path=/`, `SameSite=Lax`, one year;
only ever compared to `'1'`). On, each service shows one 24h strip: 48
half-hour bars merged from every check that counts (red if any check failed
in the slot, green if all samples passed, grey with none) plus the 24h uptime
% (Σ ok ÷ Σ samples; the Compact strip omits the %). It sits under the badge
on Dashboard, along the bottom of a Tiled tile, and as a thin line on a
Compact tile; a service with no check that counts shows a muted "—". Bars and
tooltip reuse the detail panel's. Data comes from `GET /health/strips?ids=`
(login; at most 500 ids; unknown or soft-deleted ids are omitted), served by
`health_history.strips()` with a fixed number of queries (one `health_result`
query for all checks, grouped in Python). `static/js/uptime_strip.js` fetches
once per page load while the toggle is on (auto-refresh reloads the page, so
refreshes re-fetch only while on) and never when off. No schema change.

### 13.8 Container check [`v070-07-container-check`] — Delivered in v0.7.0

Every notifier entry carries an automatic **Container** check, so the
notifier's report that a container is running counts as health. This
supersedes the earlier 0.7.0 call that kept Docker state out of the rollup.

- **Kind** `container`, `check_type` `docker`, `target` NULL, name
  "Container". Exactly one per notifier entry, enabled by default; manual
  entries have none. Created on register (new entry), on adoption of a manual
  entry, on restore, by the migration, and by the scheduler's ensure pass.
- **Evaluated by the scheduler thread**, never the pool and never the register
  request. Due on the normal interval (its own `interval_seconds` or
  `url_healthcheck_interval`). Result: ok when `docker_status` is `running`
  (case-insensitive) and the entry is not stale (`last_api_update` within
  `stale_after_minutes`); otherwise failing with `Container <status>`,
  `No update from notifier for <N> min`, or `No update from notifier yet`.
  `status_code` and `latency_ms` are NULL. Results use the same
  `record_check_result` path, so history, compaction, purge, uptime and bars
  need no changes.
- **Immediate transitions:** a register that changes `docker_status` queues
  `jobs.request_run([check id])`, so the change shows within about 5 s.
- **Locked entries** (`is_static`) receive no registers, so the check is
  neither scheduled nor counted while locked (like a disabled check); unlocking
  resumes it. Soft-deleted entries are skipped as before.
- **Rollup:** counts like any check. A Docker entry with no other checks is Up
  when running and fresh and Down when exited or stale; running with a failing
  URL check is Degraded; a disabled container check alone is Not monitored.
  Filters are unchanged (`stale` still means notifier staleness).
- **Configuration:** Edit shows a "Container (Docker state)" row (enabled and
  interval, 30-86400) for notifier entries only. Add and manual entries do not.
- **Detail panel:** renders like other checks (name "Container", no target
  line, last message, bars). The Docker pill and stale icon stay.
- **Backups:** the check's enabled/interval round-trip in `checks`; restoring a
  backup without one creates it for notifier entries.
- **Register contract:** unchanged; `schemas.py` is not touched.

**As built:** `models.py` has `CHECK_KIND_CONTAINER`, `ensure_container_check`,
`evaluate_container(entry, now)` (a pure read) and `check_counts(entry,
check)`, the shared "can run / counts" rule now used by the rollup, the
scheduler, the detail payload and Check now. `jobs.run_container_checks`
runs inside `HealthScheduler.tick` after the pool submission pass.
`select_due_jobs` never returns container checks. `check_form` has
`container_row_from_entry`, `parse_container` (guarded by a hidden `cc_row`
marker so a stale page does not disable the check) and `apply_container`. A
register also queues a run when the container check is currently failing, so
recovery after a stale spell shows at the next tick.

### 13.9 Out of scope for v0.7.0

Parked in FUTURE.md: alerting/notifications on failure;
notifier-defined service checks (register field); DNS and keyword-match check
types; uptime beyond 7 days and a public status page; dropping the deprecated
health columns.

---

## 14. v0.8.0 — Management API (Delivered)

> **Status:** shipped in v0.8.0 (2026-11-15). The management API and MCP server
> have not yet been fully tested against real instances (README note).
> Scoped 2026-11-15. Each subsection is one handoff
> prompt (named in brackets, in `prompts/`), run in the order listed.
> Each chunk leaves the app working and the test suite green.

A **minor** release with one theme: everything an operator can do in the UI
can also be done through an authenticated JSON API, so an agent such as
Claude (or a script) can maintain an STD instance. That covers reading every
entry and its health, adding manual sites and web checks, editing fields,
groups, widgets and runtime settings, and triaging failures.

Because it is a minor, `/release-prep 0.8.0` reaches the per-minor CHANGELOG
archive step. The operator chose to keep the full CHANGELOG at 0.7.0; ask
again at prep time.

**Cross-repo:** **no register-contract change.** `POST /api/v1/register`
and its `api_token` are untouched. The notifier keeps its register-only
token and needs no update.

### 14.1 Principles

- **Separate credentials.** The notifier's `api_token` (in `settings.yml`,
  present on every Docker host) stays **register-only**. Management uses
  **admin API keys** created in the UI. A leaked notifier config can never
  read or change the dashboard. The management API rejects `api_token`, and
  register rejects management keys.
- **Key-only auth.** Management endpoints authenticate with
  `Authorization: Bearer <key>` only. They ignore session cookies, so they
  are CSRF-exempt by construction. The existing browser endpoints (UI JSON
  such as `/service/<id>/health`) are unchanged and stay session-only.
- **Same rules as the UI.** One validation path per object.
  - The Add/Edit check validation (`check_form.py`) and entry rules are
    shared with the API, not copied.
  - URL edits through the API take `ui_edit` provenance (operator intent,
    protected from the notifier and synthesizer).
  - Notifier-owned fields are read-only: `docker_status`, `container_id`,
    `stack_name`, image fields, `started_at`, networks, ports, exposure
    observations and the `notifier_reported_*` columns.
  - API entry writes take the register handler's `_UPSERT_LOCK`, so they
    serialize with registers.
- **Strict schemas.** Request bodies are pydantic models with
  `extra="forbid"`, as on register. Unknown fields are a 400 listing the
  bad keys.
- **Secrets are write-only.** API key secrets are shown once at creation.
  The widget `widget_api_key` is never returned; reads return
  `"widget_api_key_set": true|false`.
- **Every write is audited** (§14.6).

### 14.2 API keys [`v080-01-api-keys-and-audit`] — Delivered in v0.8.0

- **Model `ApiKey`** (table `api_key`): `id`, `name` (≤64; unique among
  active keys only since v0.9.0, see §15.3),
  `prefix` (first 8 chars, for display and lookup), `key_hash`
  (SHA-256 hex of the full key), `scope` (`read` or `write`, where `write`
  includes read), `created_at`, `created_by` (FK `user.id`, nullable,
  indexed), `last_used_at`, `last_used_ip`, `revoked_at`, `rotated_at`
  (v0.9.0).
- **Key format:** `std_<prefix>_<secret>`. It holds 32+ random bytes from
  `secrets.token_urlsafe`. Because the key is high-entropy, a plain SHA-256
  is sufficient (no KDF). Lookup is by `prefix`, then the hash is compared
  with `hmac.compare_digest`.
- **Settings → API keys** (admin only; the Audit log is its own section, §14.6):
  - **Create key** opens a dialog (name and scope) and shows the full key
    **once**, in a dialog on the Settings page with a copy button (§19.6).
  - Key cards: name, scope, prefix, active or revoked, created, rotated
    (v0.9.0), last used (time and IP), ⋯ **Rotate** (v0.9.0) and **Revoke**.
- **Decorator `require_api_key(scope)`:**
  - Missing or invalid key → 401 JSON. Revoked → 401. Read key on a write
    endpoint → 403.
  - Sets `g.api_key`.
  - Updates `last_used_at` and IP, throttled to once a minute per key.
  - Log lines show the key's name and prefix, never the secret.
- **Blueprint `routes_mgmt_api.py`** (`/api/v1/...`, CSRF-exempt), with JSON
  error handlers for 400, 401, 403, 404, 405, 409 and 422:
  `{"error": "...", "details": ...}`.

**As built (v080-01):** `api_keys.py` (`generate_key`, `verify`,
`scope_allows`, `create_key`, `revoke_key`), `routes_mgmt_api.py` (blueprint
`mgmt_api`, `require_api_key(scope)`, `audit()`, `json_error()`,
`GET /api/v1/whoami`) and models `ApiKey` / `ApiAudit`. From v0.9.0 whoami
also returns `version` (the STD version, same source as `/config`); see §15.7.
- The prefix is 8 hex characters (`secrets.token_hex(4)`), so it never
  contains `_`; the secret is `token_urlsafe(32)` and may. A key is parsed
  with `split("_", 2)`.
- A 403 (read key on a write endpoint) still counts as an authenticated
  request: `last_used_at` is touched and a write is audited.
- Blueprint handlers return the JSON error shape for 400, 401, 403, 404, 405,
  409 and 422 raised inside the blueprint, plus pydantic `ValidationError`
  (400, field-level `details`) and unhandled exceptions (500). Routing-level
  404/405 (no matching URL) are not handled by a blueprint and keep Flask's
  default response.
- Settings → API keys (admin, CSRF): create shows the key once in the response's
  show-once dialog (`Cache-Control: no-store`; v0.8.0 used `api_key_created.html`,
  removed in v0.11.0), never via flash or session; revoke keeps the row greyed out. (Superseded in v0.9.0, §15.3: names are unique among active keys only; originally unique including
  revoked keys.) The audit list on this tab arrives with v080-04.

### 14.3 Entries, checks and health [`v080-02-entries-checks-health`] — Delivered in v0.8.0

All paths are under `/api/v1`. Every list endpoint takes `limit` (default
200, maximum 1000) and `offset`, and returns `{items, total, limit, offset}`.

| Method + path | Scope | Purpose |
|---|---|---|
| `GET /entries` | read | List, with filters `source`, `status` (`all`/`failing`/`healthy`/`unknown`/`stale`, the same as the UI), `group`, `host`, `q` (substring of name, host, stack, description), `include_deleted`, `deleted_only`. Each item has the entry fields, `health` (state, counts, failures) and `checks` (config plus last result). |
| `GET /entries/<id>` | read | One entry in full, including `notifier` (read-only observed facts) and `widget` (no secret). |
| `POST /entries` | write | Create a **manual** entry: name, host, description, group (name; created if missing), URLs, icon, sort priority, lock, and `checks` (a list of service checks plus URL-check settings). It follows the same duplicate rules as Add, so a duplicate is a 409. |
| `PATCH /entries/<id>` | write | Partial update of operator fields: group, URLs, icon, sort priority, lock, description; also name and host on manual entries only. Notifier-owned fields → 400. |
| `DELETE /entries/<id>` | write | Soft delete. `?permanent=true` hard-deletes, but only an already soft-deleted entry; otherwise 409. |
| `POST /entries/<id>/restore` | write | Restore a soft-deleted entry. |
| `GET /entries/<id>/checks` | read | The entry's checks. |
| `POST /entries/<id>/checks` | write | Add a service check (http/tcp/ping/dns). |
| `PATCH /checks/<id>` | write | Update any check. URL-kind checks: enabled, mode, interval, timeout, verify. Container check: enabled, interval. Service checks: everything. |
| `DELETE /checks/<id>` | write | Delete a **service** check. URL and container checks can't be deleted (409); disable them instead. |
| `POST /entries/<id>/checks/run` | write | Check now (uses `jobs.request_run`). Returns `requested_at`. |
| `GET /entries/<id>/health?range=24h\|7d` | read | The same payload as the UI detail panel. |
| `GET /health/summary` | read | Counts (total, passing, failing, unknown, stale) plus every failing entry with its failing checks and messages, so an agent can triage in one call. |

- **`check_form.py` validation is refactored** into functions that take
  plain dicts, used by both the form parser and the API, so there is one
  rule set. Form behaviour stays the same; existing tests prove it.
- **Status codes:** a create returns 201 with the object. A validation
  failure returns 400 with every problem listed, per field.

**As built (v080-02):**
- Modules: `entry_rules.py` (name/host/description limits, duplicate check,
  sort priority, icon name and download, group lookup, URL provenance
  via `set_url`), `check_form.py` (now has `validate_service_check`,
  `validate_url_check_settings`, `validate_container_check` over plain dicts
  returning `(values, [{field, message}])`; the form parser wraps them and
  keeps its messages), `mgmt_schemas.py` (pydantic requests `EntryCreate`,
  `EntryPatch`, `ServiceCheckCreate`, `CheckPatch`, all `extra="forbid"` and
  strict; response `TypedDict`s such as `EntryOut`, `CheckOut`, `Page`),
  `mgmt_serializers.py` (plain functions returning those dicts) and the
  endpoints in `routes_mgmt_api.py`. `/add` and `/edit/<id>` use the same rule
  functions; their behaviour and messages are unchanged.
- JSON names: `name` (not `container_name`), `icon`, `locked`, `group`
  (`{id, name}` out, a name in), and checks use the backup vocabulary
  (`check_type`, `interval_seconds`, `timeout_seconds`, `verify_tls`).
  Create takes `checks` (service checks) and `url_checks`
  (`{internal, external}` settings). Entry detail adds `notifier` (observed
  facts and exposure rows) and `widget` (`widget_api_key_set`, never the key).
- A service check created through the API is enabled unless `enabled:false`;
  an entry created without a group is ungrouped (the UI's literal "None"
  group is not reproduced).
- Errors: validation problems are a 400 whose `details` is a list of
  `{loc, msg, type}` (the same shape as a pydantic failure) with every
  problem; a duplicate or a state conflict is 409 with `details`
  (`{id, deleted}` for a duplicate); a PATCH naming notifier-owned or derived
  fields, or name/host on a notifier entry, is a 400 that names them.
  `limit` above 1000 is clamped; a non-numeric or negative one is a 400.
- `GET /entries` with `status=all` paginates in SQL; with another status it
  filters in Python (the state is derived) after one eager-loaded query, so
  the query count does not grow with the number of entries.
- `GET /health/summary` counts are `matches_status` over active entries (the
  same rule as the filter-bar chips); `since` is the earliest failed sample
  after the latest passing one, falling back to the last check time.
  Revision 3 (§18.9) adds `streams` (one compact row per inventory stream),
  `stale_streams` (a `down` line per stale stream) and `counts.streams_stale`;
  `failing` stays entry-only.

### 14.4 Groups, widgets and runtime settings [`v080-03-groups-widgets-settings`] — Delivered in v0.8.0

| Method + path | Scope | Purpose |
|---|---|---|
| `GET /groups` | read | Groups with priority, icon and active entry count. |
| `POST /groups` | write | Create a group (unique name → 409 on duplicate). |
| `PATCH /groups/<id>` | write | Rename, re-prioritise, set the icon. |
| `DELETE /groups/<id>` | write | Delete. Its entries become ungrouped (same as the UI). |
| `GET /widgets/types` | read | The widget plugins under `widgets/` with their `available_fields`. |
| `GET /widgets` | read | Widget instances: type, URL, fields, `widget_api_key_set`, attached entry ids, `detached`. |
| `PUT /entries/<id>/widget` | write | Attach or configure the entry's widget (type, URL, fields, optional API key). Validates the type and fields against the plugin. |
| `DELETE /entries/<id>/widget` | write | Remove it from the entry. `?delete=true` deletes the widget and its values; otherwise it is detached. |
| `DELETE /widgets/<id>` | write | Delete a detached widget. |
| `GET /settings/exposure` | read | Per-interpreter direction mappings, per-host overrides, and discovered layers and hosts (`settings_store`). |
| `PUT /settings/exposure` | write | Replace them, with the same validation as Settings → Exposure. |
| `GET /settings/backup` | read | Backup settings (folder, snapshot and export jobs) each with its `origin` (`env`, `ui`, `file`, `default`), plus `last_runs` and `next_runs` (§20, API revision 4). |
| `PUT /settings/backup` | write | Change them with the UI's validation; an env-pinned field is a 409; reschedules the jobs. Audited as `backup_settings`. |
| `GET /backups` | read | Backup files, newest first: `{name, kind, size, modified, manual, legacy}`. No download route: a snapshot holds every secret. |
| `POST /backups/run` | write | `{kind: snapshot\|export}`, synchronous; 409 when that kind is already running. Audited as `backup_run`. |
| `GET /export` | read | The export document (§20.2), `?format=json` (default) or `yaml` (`application/yaml`). Not audited. |
| `GET /config` | read | Effective `settings.yml`/env values, read-only, with **secrets masked** (`api_token`, `secret_key`, widget keys) plus the app version. These are not editable through the API (they are loaded once at startup). |

Users and passwords are **not** exposed through the API (out of scope).

**As built (v080-03):**
- `widget_rules.py` discovers plugins under `widgets/` (paths built from
  `os.listdir` entries only) and validates type, URL (required, 255 max),
  fields (non-empty, each a plugin `available_fields` key) and the API key
  length. `/edit` is unchanged and still does not validate plugins.
- JSON: group `{id, name, sort_priority, icon, entry_count}`; widget
  `{id, type, url, fields, widget_api_key_set}` plus `entry_ids` and
  `detached` on `GET /widgets`; `GET /widgets/types` items are
  `{type, description, available_fields: [{key, label, description}]}`.
  Responses are typed in `mgmt_schemas.py`.
- Groups: deleting one with active entries is a 409, as in the UI (the
  "entries become ungrouped" wording above is the `?force=true` behaviour);
  deleted entries are always ungrouped. Names are trimmed, 100 max.
- `PUT /entries/<id>/widget` replaces type/URL/fields; an omitted
  `widget_api_key` keeps the stored one and `null` clears it. 201 when it
  creates the widget, 200 when it updates. Refused (409) on a deleted entry.
  `DELETE /entries/<id>/widget` is 404 when there is no widget.
- `PUT /settings/exposure` takes `{layer_directions, host_overrides}`,
  validates directions against `VALID_DIRECTIONS` (the UI silently drops bad
  ones; the API answers 400), saves via `settings_store.save_exposure_settings`,
  runs `synthesizer.recompute_all()` and returns the settings plus
  `recomputed`.
- `GET /config` returns `{version, settings, sources}`: every key in
  `settings_loader.VALID_KEYS` plus `display_tools`, `sources` saying
  env/file/default. Names that are secrets (`api_token`, anything ending
  `_key`, `_token`, `_password`, `_secret`) show `"***"` (null if unset).

### 14.5 OpenAPI spec and docs [`v080-04-openapi-and-docs`] — Delivered in v0.8.0

- `GET /api/v1/openapi.json` (no auth; it describes shapes, not data) is an
  OpenAPI 3.1 document. It is generated from the pydantic request and
  response models plus a route table, not hand-written, and a test fails if
  a management route is missing from it.
- **README "Management API"**: creating a key, the auth header, the endpoint
  table, curl examples (list failing services, add a manual site with an
  HTTP body check, disable a check), and a "Managing STD with Claude"
  section.

**As built (v080-04):** `mgmt_openapi.py` holds the route registry
(`OPERATIONS`: one `Op` per endpoint with method, path, scope, summary,
request model, response type and query parameters) and `build_spec()`, which
emits OpenAPI 3.1 using `pydantic.TypeAdapter(...).json_schema()` for the
`mgmt_schemas.py` models (no extra dependency). `GET /api/v1/openapi.json` is
public and lives on the management blueprint, so it is in the registry too.
`require_api_key` tags each view with `required_scope`, and
`tests/test_mgmt_openapi.py` fails if any `mgmt_api.*` rule in `app.url_map`
is missing from the registry (or the reverse), if a scope differs, if a
`$ref` does not resolve, if `/api/v1/register` appears, or if the README
endpoint table drifts. Filtering is by blueprint, so the browser-session JSON
routes under `/api/v1` are never listed. Unmatched `/api/v1/*` URLs answer
with the JSON error shape when the caller sends a Bearer header or
`Accept: application/json`.

### 14.6 Write audit log [in `v080-01`; Settings view in `v080-04`] — Delivered in v0.8.0

- **Model `ApiAudit`** (table `api_audit`): `id`, `ts` (UTC), `api_key_id`
  (FK, indexed, `ON DELETE SET NULL`), `key_name` (a snapshot), `method`,
  `path`, `object_type`, `object_id`, `status_code`, `changes` (JSON
  `{field: [old, new]}`, with secrets replaced by `"***"`).
- **One row per write request** (POST, PATCH, PUT, DELETE), including
  failures (4xx). Reads are not logged.
- **Retention:** new setting `api_audit_retention_days` (default 90), with a
  daily purge job.
- **Settings → Audit log** shows the most recent 200 rows, filterable by key.

**As built (v080-01):** model, retention and the hook are in. The hook is
`routes_mgmt_api.audit_response`, registered with `mgmt_bp.after_request`; it
writes one row for each POST/PATCH/PUT/DELETE that carried a valid key
(including 4xx and 403). Endpoints describe the change with
`audit(object_type, object_id, {field: [old, new]})`, which masks secret
fields (`widget_api_key`, `api_token`, `secret_key`, `key_hash`, `api_key`,
or any name containing `secret`, `password` or `token`) as `"***"` for both
old and new values before they reach the database. Unauthenticated requests
are only logged. `jobs.purge_api_audit` runs daily at 00:35. The Settings
view of the log is not built yet.

**As built (v080-04):** Settings → Audit log lists the 200 most recent rows (time UTC, key, method, path, object, status, changes) with a filter by key name (`?audit_key=`, from the stored snapshot so deleted keys still filter). Changes render as escaped text lines, shortened to 120 characters per value; secrets are already `***`.

### 14.7 MCP server [`v080-05-mcp-server`] — Delivered in v0.8.0

- A small **stdio MCP server** at `mcp/std_mcp.py` (its own
  `mcp/requirements.txt`, using the official `mcp` Python SDK). It is **not
  in the Docker image**; it runs on the operator's machine, next to Claude
  Code.
- It is configured with `STD_URL` and `STD_API_KEY` and talks only to the
  REST API. It holds no DB access and duplicates no business logic.
- **Tools**, as thin wrappers with typed inputs: `list_entries`,
  `get_entry`, `health_summary`, `get_health_history`,
  `create_manual_entry`, `update_entry`, `delete_entry`, `restore_entry`,
  `add_check`, `update_check`, `delete_check`, `run_checks`,
  `list_groups`, `upsert_group`, `list_widgets`, `set_widget`,
  `get_exposure_settings`, `set_exposure_settings`, `get_config`.
- A **read-only key exposes only the read tools**; it probes the key's scope
  at startup via `GET /api/v1/whoami`, which is added in v080-01.
- **README:** a `claude mcp add` example.
- **Tests:** each tool runs against a fake HTTP layer, with no network.

**As built (v080-05):** `mcp/std_mcp.py` (FastMCP over stdio, `mcp==1.30.0`, `httpx` client) with its own `mcp/requirements.in` / `requirements.txt` and `mcp/README.md`. Env: `STD_URL`, `STD_API_KEY`, optional `STD_VERIFY_TLS` and `STD_TIMEOUT`. `main()` calls `GET /whoami` and exits with the reason on a bad key; a `read` key registers 9 read tools, a `write` key adds 12 write tools (21 in all). Beyond the §14.7 list: `list_widget_types` (so `set_widget` can be filled in) and `remove_widget`. `update_entry` / `update_check` take a `fields` object so that absent (untouched) and null (clear) stay distinct; `upsert_group` is client-side (list, then create or patch by exact name; optional `new_name`). Errors become tool errors as `HTTP <status> (<meaning>): <error>` plus the API's `details`. `.dockerignore` keeps `mcp/` out of the image; `requirements-dev.txt` includes `mcp/requirements.txt` so `tests/test_mcp_server.py` runs in the CI `Test` job (fake transport for every tool, scope gating, error mapping, every tool's method and path checked against `/api/v1/openapi.json`, and a flow against the real app via `httpx.WSGITransport`). No STD server change, no schema change.

**v0.9.0 addition (§15.7):** one-command install with `uv run` (PEP 723 header in `std_mcp.py`), a startup version comparison against `whoami.version`, and a `server_info` tool.

### 14.8 Out of scope for v0.8.0

- Per-host notifier tokens (§23), users and passwords through the API, and
  rate limiting.
- An HTTP-hosted MCP endpoint inside STD.
- Editing `settings.yml` values through the API.
- Webhooks or outbound alerts (FUTURE.md "Monitoring follow-ups").

---

## 15. v0.9.0 — DNS and certificate-expiry checks (Delivered)

Two new kinds of check, so STD can take over what Gatus checks at the Emmett
site: a DNS check (§15.1) and certificate expiry on HTTPS checks (§15.2). Chunks are tracked as handoff prompts `v090-NN-*`.

### 15.1 DNS check [`v090-01-dns-check`] — Delivered in v0.9.0

A fourth service-check type, `dns`, that asks a given DNS server a question
and judges the reply. It goes through every place the other types do: model
and migration, Add/Edit, the management API and OpenAPI spec, the MCP tools,
the detail panel and rollup.

- **Schema** (migration `a1c5e8d2f093`, nullable columns on `health_check`,
  no indexes needed): `dns_name` (query name), `dns_record_type` (`A`, `AAAA`,
  `CNAME`, `TXT`, `PTR`, `MX`, `NS`, `SRV`; default `A`), `dns_expected_rcode`
  (default `NOERROR`, stored upper-case) and `dns_expected_answer` (empty or
  NULL means "rcode only"). All four are NULL on other check types and are
  part of `to_config()` and backup restore (older backups restore them as
  NULL). `check_type` `dns` fits the existing `String(8)`.
- **Server** = `target`: an IP literal, `ip`, `ip:port`, `[v6]` or
  `[v6]:port` (a bare IPv6 without a port is also accepted), port 53 by
  default. A hostname is rejected: the check must never use the system
  resolver, so the server has to be an address.
- **Probe** `checker.probe_dns(server, name, record_type, expected_rcode,
  expected_answer, timeout)`: low-level dnspython
  (`dns.message.make_query` + `dns.query.udp_with_fallback`, TCP on
  truncation); `dns.resolver` is never used. Latency is the query round trip;
  `status_code` stays NULL.
  - PTR accepts an IP as the name (converted with `dns.reversename`); a name
    already under `in-addr.arpa` / `ip6.arpa` is used as is.
  - An rcode mismatch fails with `rcode <ACTUAL>` (e.g. `rcode NXDOMAIN`).
  - Answers are the answer-section rdatas of the queried type at any owner
    name, so a CNAME chain followed by an A record still matches the A record.
    The comparison is an exact match on **any** answer, after normalizing:
    case-insensitive, trailing dot removed, whitespace collapsed, IP addresses
    in canonical form, TXT as its joined strings without quotes; MX and SRV
    compare the full presentation form.
  - NODATA (NOERROR, no answers) passes when no answer is expected, and fails
    with `no answer, expected <x>` when one is.
  - A wrong answer fails with `answer <a> | <b>, expected <x>` (answers joined
    with ` | `, clipped to the 255-character message column).
  - A timeout gives exactly `timeout`; any other exception follows the usual
    failing-result path. The probe never raises.
- **Validation** (`check_form.py`, one rule set for the form and the API):
  the server per the rules above; `dns_name` required and a valid DNS name (an
  IP for PTR); record type in the list above; rcode a known rcode name
  (numeric codes rejected); expected answer optional and trimmed. `mode` and
  `verify` do not apply and are stored as `status` and true. The DNS fields are
  part of the change signature, so editing them makes the check due at the
  next tick. Switching a check away from DNS clears the DNS columns.
- **UI**: the type select has DNS. With DNS selected the target relabels to
  "DNS server", four fields appear (query name, record type, expected rcode
  among NOERROR / NXDOMAIN / SERVFAIL / REFUSED, expected answer) and Mode and
  Verify TLS hide. Form fields `svc_<key>_dns_name`, `_dns_type`,
  `_dns_rcode`, `_dns_answer`. A failed submit re-renders the input.
- **Detail panel**: shows `A em-pve01.crzynet.me @ 10.100.16.16` and, below,
  `expect NOERROR + 10.100.17.10`. Bars, uptime, the rollup badge and status
  filters work unchanged; a failing DNS check makes the entry down (or
  degraded alongside passing checks).
- **Management API and MCP**: `check_type: "dns"` plus the four `dns_*`
  fields on `POST /entries/<id>/checks`, on the inline `checks` of
  `POST /entries` and on `PATCH /checks/<id>` (service checks only: URL and
  container checks return 400, as for `target`). `CheckOut` always carries the
  four fields, null on other types. The OpenAPI spec picks them up. MCP
  `add_check` takes the four fields and `update_check` accepts them.
- **Dependency**: `dnspython` (pinned in `requirements.txt`).
- **Example (Emmett)**: `check_type=dns`, `target=10.100.16.16`,
  `dns_name=em-pve01.crzynet.me`, `dns_record_type=A`,
  `dns_expected_answer=10.100.17.10`.

### 15.2 Certificate expiry on HTTPS checks [`v090-02-cert-expiry`] — Delivered in v0.9.0

An optional **minimum days left** on HTTPS checks, for URL checks (internal
and external) and HTTP service checks. When set, a check fails with
`cert expires in N days (min M)` once the leaf certificate is that close to
expiry, even though the HTTP status is fine.

- **Schema** (migration `b7d3f1a94e26`, two nullable columns on
  `health_check`, no indexes needed): `cert_min_days` (Integer; NULL = off) and
  `last_cert_expires_at` (DateTime, naive UTC; the certificate's notAfter as
  the checker last saw it). `cert_min_days` is in `to_config()` and backup
  restore (older backups, and values outside 1-365 or on non-http checks,
  restore as NULL); `last_cert_expires_at` is a cache and is never backed up.
- **Probe** `checker.probe_http(..., cert_min_days=None)`. With a minimum set
  and an `https://` target, the probe makes a separate TLS handshake to the
  target URL's host and port (443 by default) with SNI set to the hostname,
  through `_read_cert_expiry(host, port, timeout)`: an unverified context
  (`check_hostname` off, `CERT_NONE`) so it also works with Verify TLS off,
  `getpeercert(binary_form=True)` parsed with `cryptography.x509`
  (`not_valid_after_utc`), the probe's timeout. The expiry comes back in the new
  `ProbeResult.cert_expires_at` (naive UTC, like everything `jobs.py`
  stores). Result rules, in order:
  1. HTTP fails: today's HTTP failure message is kept, and the expiry is still
     reported if the handshake got one.
  2. HTTP ok but less than `cert_min_days` days left: failing,
     `cert expires in N days (min M)` (N = whole days left, floored); an
     already-expired certificate reads `cert expired N days ago`.
  3. HTTP ok but the certificate could not be read: failing,
     `cert check failed: <reason>`.
  4. Otherwise ok; the status code is kept.

  `http://` targets ignore the condition (no handshake, `cert_expires_at`
  None). The handshake is its own connection, so it does not honour an
  `HTTPS_PROXY` that `requests` would. The probe never raises.
- **Jobs**: the due-job dict carries `cert_min_days`; `record_check_result`
  always overwrites `last_cert_expires_at` from the result, so it is cleared
  when the check has no condition, the target is plain http, or the
  certificate could not be read. URL checks use the entry's current URL, so
  a URL that turns into http ignores the stored condition.
- **Validation** (`check_form.py`, one rule set for the form and the API):
  optional; when set a whole number from 1 to 365. Allowed on URL checks and
  http service checks; a 400 on tcp/ping/dns service checks in the API (the
  form never submits it for them and ignores it if present). Saving an
  `http://` URL with a value is allowed: it is stored and ignored at runtime,
  because the URL can change underneath. In the change signature, so editing
  it makes the check due at the next tick. Switching a check away from http
  clears it.
- **UI**: a "Min cert days" number input (placeholder "off") beside Verify
  TLS on URL-check rows and HTTP service rows, shown only while the effective
  URL starts with `https://` (the entry's internal/external URL input for URL
  checks, the row's own target for service checks), updated live as you type.
  Form fields `uc_<which>_cert_min_days` and `svc_<key>_cert_min_days`; a
  failed submit re-renders the value.
- **Detail panel**: `check_payload` carries `cert_min_days` and
  `cert_expires_at` (ISO-Z); when an expiry is known the panel shows
  "Cert expires <local date> (N days)", in the failing colour when below the
  minimum.
- **Management API and MCP**: `cert_min_days` (nullable; null clears it) on
  `POST /entries/<id>/checks`, the inline `checks` and `url_checks` of
  `POST /entries`, and `PATCH /checks/<id>` (URL checks and http service
  checks; a 400 on other kinds and types). `CheckOut` carries `cert_min_days`
  and `cert_expires_at`; the OpenAPI spec picks them up. MCP `add_check` takes
  `cert_min_days` and `update_check` accepts it.
- **Dependency**: `cryptography` (pinned in `requirements.txt`; manylinux
  wheels, so `python:3.11-slim` needs no compiler).
- **Example (Emmett)**: a URL check on `https://em-pve01.crzynet.me:8006/`
  with `cert_min_days=7`; Proxmox's self-signed certificate with Verify TLS off
  still reports its expiry.

### 15.3 API key rotation [`v090-03-api-key-rotate`] — Delivered in v0.9.0

- **Rotate** on each active key in Settings → API keys (`POST
  /settings/api-keys/<id>/rotate`, admin and CSRF, like revoke). It keeps the
  row (id, name, scope, `created_at`, audit history) and issues a fresh key
  from `generate_key()`, so the prefix and the secret are both new.
  `api_keys.rotate_key(key)` replaces `prefix` and `key_hash`, sets
  `rotated_at`, clears `last_used_at` / `last_used_ip` (they described the old
  secret) and returns the full key. A revoked key raises `ValueError`.
- No grace period: `verify` looks up by prefix and hash, so the old secret is
  rejected at once.
- The new key is shown once in the show-once dialog on the Settings page (headed
  "Key rotated"; v0.9.0 used `api_key_created.html`, removed in v0.11.0),
  with `Cache-Control: no-store, no-cache`. A revoked or unknown id flashes an
  error and redirects to the API tab. The log line carries the key id only.
- New column `api_key.rotated_at` (nullable, naive UTC); the list shows it as
  "rotated" in the key card's summary ("—" when never rotated).
- **Name reuse.** `api_key.name` is no longer unique across all rows: the
  column constraint `uq_api_key_name` is replaced by the partial unique index
  `ux_api_key_name_active` (`name WHERE revoked_at IS NULL`), so a revoked
  key's name can be used again. `validate_name` checks active keys only. The
  audit-log key filter uses the key id (`audit_key=id:<n>`), with a revoked
  key labelled "(revoked)"; rows whose key was deleted keep a name-only
  option. The downgrade refuses, with a message listing the names, if a name
  is shared by more than one row.
- Migration `c2e8a5b3d917` (on top of `b7d3f1a94e26`) does both changes.
- Not in the management API: users and keys stay UI-only (§14.8).
### 15.4 Groups: one Save, unsaved-changes warning [`v090-04-groups-save-all`] — Delivered in v0.9.0

- **One form, one route.** Settings → Groups is a single `<form>` posting to
  `POST /settings/groups/save` (admin and CSRF). Rows post
  `group-<id>-name|icon|priority|delete`; the optional new row posts
  `new-name|icon|priority` and is ignored when the name is blank. The per-row
  Save/Delete forms and `POST /update_group`, `/add_group`, `/delete_group` were
  removed (the nested per-row forms were invalid HTML and the per-row Save
  posted only `group_id`, which reset `group_sort_priority` to NULL).
- **All or nothing.** The submission is validated first: names non-empty (<= 100
  characters) and unique across the resulting set (so an A<->B swap, or a new
  group taking a deleted row's name, is fine), icon <= 255 characters,
  priority blank or an integer (negatives and 0 allowed), every submitted
  group id still exists and no existing group is missing from the form, and a
  delete-marked group has no active entries. The name, icon and priority rules
  are `entry_rules.validate_group` / `parse_sort_priority`, shared with the
  management API. Any failure writes nothing and re-renders Settings (HTTP 400)
  on the Groups section with the submitted values and per-row messages (v0.11.0:
  as cards, and the staging dialog opens on the first row with a message; §19.6).
- **Applying.** One transaction: deletes (soft-deleted entries detached), renamed
  rows parked on a placeholder name so SQLite's per-statement UNIQUE check
  allows swaps, then the final values and the new row. Flash: "Saved: N updated,
  N added, N deleted." or "No changes."
- **Unsaved-changes guard.** `static/js/unsaved_guard.js` (no dependencies,
  `data-unsaved-guard` on a form) snapshots the form on load, is dirty while the
  values differ from it, arms a `beforeunload` prompt, highlights Save and shows
  an "Unsaved changes" hint. Submit and Discard disarm it. A failed save
  re-renders with `data-unsaved-start-dirty`. Applied to the groups form only.

### 15.5 Host on tiles when the name isn't unique [`v090-05-tile-show-host`] — Delivered in v0.9.0

- **Setting.** `tile_show_host` (`TILE_SHOW_HOST`): `duplicates` (default),
  `always`, `never`. Lower-cased and trimmed at startup in `settings_loader`;
  an unknown value logs a warning and falls back to `duplicates`. Startup-only
  like every `settings.yml` value; it appears in Settings → Configuration and in
  `GET /api/v1/config` (not a secret) with no schema change.
- **Detection.** `view_helpers.duplicate_name_ids(entries)` returns ids whose
  name (case-insensitive, trimmed) is shared by another active entry on a
  different host; soft-deleted and host-less entries are ignored.
  `host_label_ids(entries, mode)` applies the mode (`always` = every entry with
  a host). The handlers compute it over all active entries (not the filtered
  view) and pass the id set to the templates.
- **Views.** Tiled: a `.tile-host` line (small, muted, ellipsis, full host in
  `title`) directly under the name, only for ids in the set; other tiles are
  unchanged. Compact: replaces the old `more than one host` rule with the same
  set (`always` approximates the old behavior). The Dashboard table already
  has a Host column and is unchanged.
- No schema, register-contract or job change.

---

### 15.6 Roll-up and HTTP failure messages [`v090-08-rollup-and-http-messages`] — Delivered in v0.9.0

- **Roll-up.** `health_state.entry_health`: Container failing = `down`;
  otherwise URL and service checks that have run are judged as a group
  (all failing = `down`, some = `degraded`). Container-only entries are
  unchanged. The duplicate rule in `routes_mgmt_api.health_summary` was
  replaced with `entry_health(e).state`.
- **Status-mode message.** A status of 400 or above (threshold unchanged)
  reads at most `BODY_READ_LIMIT` (4 KB) of the body (`stream=True` now in
  status mode too; only read on failure; response always closed). JSON object:
  first non-empty string among `last_error`, `error` (or `error.message`),
  `message`, `detail`, else the raw text; text: first non-empty line.
  Format `<code>: <text>`, whitespace collapsed, whole message at most 200
  characters (`…`); empty, whitespace-only or binary bodies give just the code.
  The cert condition is unchanged. (Body mode got the same extraction in §15.9.)
- No schema, register-contract or job change.

---

### 15.7 MCP easy install and version check [`v090-09-mcp-easy-install-and-version`] — Delivered in v0.9.0

- **uv install.** `mcp/std_mcp.py` starts with a PEP 723 block
  (`requires-python >= 3.10`, `mcp==1.30.0`, `httpx==0.28.1`), so
  `uv run std_mcp.py` (or `uv run <raw GitHub URL at a tag>`) needs no virtualenv.
  `requirements.in` / `requirements.txt` stay for CI and the venv path; a test
  asserts the header pins equal `requirements.in`.
- **`whoami.version`.** `GET /api/v1/whoami` adds `version` (from
  `VERSION_INFO`, as `/config` and `openapi.json` do). Additive; `WhoamiOut`
  and the OpenAPI description updated.
- **MCP version.** `MCP_VERSION` in `std_mcp.py` is set by `/release-prep`
  alongside `VERSION`; a test fails if it is behind `VERSION`.
- **Startup comparison** (`compare_versions`): `MAJOR.MINOR.PATCH` integers;
  same major.minor = `match` (a patch difference is noted only on stderr);
  `std_newer`; `std_older` (a missing `version` means STD older than 0.9.0);
  `unknown` for anything not plain semver. A difference gives one stderr line
  and one "Version notice" sentence in the FastMCP instructions. It never
  refuses to start. The startup line is
  `connected to STD <v> as key '<name>' (<scope>); std_mcp <v>`.
- **`server_info`** read tool: `{mcp_version, std_version, status, advice}`
  from the startup result, no network call.
- No schema, register-contract or job change.

---

### 15.8 Tiled tile layout [`v090-10-adopt-tile-v2-and-detail-message`] — Delivered in v0.9.0

- Each Tiled tile is a two-row grid: the icon on the left and the name across
  the full remaining width (host in small text underneath when §15.5 shows
  it); below, a divided bottom row with, left to right, the status icons
  (health badge, internal/external URL, widget), the exposure badges (one logo
  per proxy layer, §8.9), and right-aligned actions (Dozzle, edit, trash/lock,
  chevron). The uptime strip (Show uptime) sits along the tile's bottom edge.
- This replaces the earlier right-hand two-row icon block. The temporary
  `/tiled_preview` route and its `tile_layout` plumbing were removed (unknown
  URL = 404). Mobile touch targets (< 640 px) are unchanged.
- No schema, register-contract or job change.

---

### 15.9 Body-mode failure reason and panel message [`v090-10-adopt-tile-v2-and-detail-message`] — Delivered in v0.9.0

- **Body mode, status >= 400.** An `Error:`-prefixed body still gives that
  text; otherwise the message is `<code>: <reason>` using the §15.6
  extraction (JSON `last_error` / `error` / `message` / `detail`, else first
  line), else just the code. Body mode's 2xx outcomes (`OK`, `Error:`,
  `Unexpected response`) are unchanged.
- **Panel.** A down check always shows a message line in the health detail
  panel: the stored message, else `status N (empty reply)`, else `no reply`.
- **Cache busting.** `base.html` and the edit/add/settings templates request
  shared static CSS/JS with `?v=<file mtime>` (`static_v()` template helper).
- No schema, register-contract or job change.

### 15.10 Health-tinted entries [`v090-11-health-tinted-rows`] — Delivered in v0.9.0

- An entry whose rolled-up health (§13.6) is **degraded** or **down** gets
  the class `entry-health-degraded` / `entry-health-down` on its Dashboard
  row (and its expanded health row), its Tiled `.tile` and its Compact
  `.compact-tile`. Up, unknown and none get no class and look unchanged.
- CSS (`static/css/dashboard.css`): a 12% `color-mix` of `--color-status-warn`
  / `--color-status-bad` into `--color-bg-surface` (18% on row and compact
  hover), with an `rgba` fallback line and a 3px left edge in the same hue.
  The open Tiled drawer keeps its neutral background.
- Auto-refresh reloads the page, so the tint follows the server render; no
  JS change.
- No schema, register-contract or job change.

---

## 16. v0.10.0 — Version in the UI (Delivered)

Prompt: `prompts/done/2026-11-16-version-in-ui.md`. No schema or
register-contract change.

- **Build channel.** The `Dockerfile` takes a `BUILD_CHANNEL` build arg
  (default `local`) and writes `channel=` into `/app/version.txt` next to
  `version`, `commit` (full SHA from `GIT_COMMIT`) and `build_time`.
  `publish.yml` sets `release` (published release), `main` (push to main),
  `dev` (push to dev) or `pr` (PR build). `read_version_info()` always
  returns all four keys; a local run or an older image gets `local` /
  `unknown`.
- **Display** (`version_check.display_info`): `v0.9.0` for a release,
  `v0.9.0 · main` for main, `dev · 0.9.0` (one-line form
  `dev · 0.9.0+sha-abc1234`) for dev, pr and local. Main and dev-style builds
  link the short SHA to the GitHub commit (hidden below the `sm`
  breakpoint). The `v` prefix is display-only; `VERSION` stays bare.
- **Header** (`templates/base.html`, every page): a low-emphasis version label
  after the title; clicking it opens the What's New popup. When an update is
  available, a separate `update available → vX.Y.Z` link goes to the release
  page.
- **Update check** (`version_check.py`):
  - releases only, via `GET /repos/crzykidd/service-tracker-dashboard/releases/latest`;
    drafts and prereleases are ignored, and a dev build of the same version is
    not an update;
  - page-load driven: the template context processor starts a background
    refresh (one at a time, behind a lock) when the cache is older than the
    interval; pages never wait on GitHub; no page loads means no checks;
  - an open page re-reads `GET /api/update-status` (login-protected,
    dashboard blueprint) hourly, which also starts a refresh when stale;
  - server-side only, no auth, generic `User-Agent`, 5 s timeout, `ETag` /
    `If-None-Match`, honours `Retry-After` and `X-RateLimit-Reset`;
  - on error it keeps the last good value and backs off
    `interval × 2^failures`, capped at 24 h;
  - the last good result (with ETag) persists in the `setting` table;
    backoff and the last error are in memory only.
- **Settings** (DB runtime, Settings → About): `update_check_enabled`
  (default on) and `update_check_interval_hours` (default 6, minimum 1).
  Disabled means no fetch and no link. About also shows channel, linked
  commit, build time, latest release seen, last checked and last error, in
  a Version grid with the settings in an Update check card (v0.11.0).
- **Management API / MCP:** `whoami` and `config` add `commit`, `channel`,
  `build_time` and `update {enabled, latest_version, update_available,
  release_url, checked_at}`; `GET/PUT /api/v1/settings/update-check`. MCP
  `server_info` adds `std_commit`, `std_channel`, `std_update`; the version
  compatibility logic is unchanged.

---

## 17. v0.10.0 — Notifications: MQTT and Home Assistant (Delivered)

The FUTURE.md item "Alerting / notifications on failure", scoped down to
**state publishing**: STD publishes check and roll-up state to an external
channel. Alert rules (N consecutive failures, de-duplication, quiet hours)
and push channels (ntfy, webhook, Gotify, email) stay in FUTURE.md and will
reuse this channel framework. Home Assistant users can already alert from
the published state with HA automations.

No register-contract change: the notifier is not involved.

### 17.1 Decisions (operator, 2026-11-16)

- Publish **state changes only, retained**, plus a full republish on every
  (re)connect. Not every check result (that is parked in FUTURE.md).
- Topics use **ids, not names**, so a rename never moves a topic.
- Home Assistant: **one device per STD entry**, linked to an STD hub device.
- HA discovery is **opt-in per channel** (master switch; the hub device
  publishes whenever it is on). **Entries are opt-in** (`ha_publish`, default
  false); inside a published entry every check publishes unless **opted out**
  per check (`ha_exclude`). Changed 2026-11-17 (notif-04): notif-03 shipped
  entries as opt-out and the operator got ~50 unwanted devices; the migration
  starts every entry unpublished.
- Devices are named `<prefix> <entry name> (<host>)` (prefix default `STD`;
  no host, as on a manual entry, gives `<prefix> <entry name>`), so same-named
  entries on different hosts are distinguishable (2026-11-17) and entity ids
  start `std_` for auto-entities globs.
- The STD group is an **attribute**, not a `suggested_area`.
- **No command entities** (no "Check now" button from HA); parked in
  FUTURE.md pending a security review.

### 17.2 Channel framework and MQTT [`notif-01-channel-framework-and-mqtt`] — Delivered

- `notification_channel` table (§5.8: `type`, unique `name`, `enabled`, JSON
  `config`, write-only `secret`). Channel types register a pydantic config
  (`extra="forbid"`), `defaults()`, `test()` and `publish()`; only `mqtt`
  exists.
- MQTT via `paho-mqtt` 2.x (`CallbackAPIVersion.VERSION2`), threaded
  `loop_start()` with `connect_async` (no asyncio). Config: `host`, `port`
  (default 1883, 8883 with TLS), `tls`, `tls_insecure`, `username`, password
  (the write-only `secret`), `client_id` (default `std-<first 8 hex of the
  instance id>`), `base_topic` (default `std`, trailing `/` stripped),
  `qos` (0 or 1, default 1), `keepalive` (default 60). The Home Assistant
  fields `ha_discovery`, `ha_prefix` (`homeassistant`) and `ha_device_prefix`
  (`STD`) drive Home Assistant discovery (§17.4). The instance id is a UUID in
  the `setting` table.
- One publisher thread with a bounded queue (1000). Producers call the
  non-blocking `notify.enqueue(event_dict)`, which never raises or blocks;
  when full the oldest event is dropped with a rate-limited warning. An MQTT
  event is `{"topic": <suffix under base_topic>, "payload": str|dict|list,
  "retain": bool}`. `notify.on_connect_hooks` run after every (re)connect so
  §17.3/§17.4 can republish.
- LWT: `<base>/status` = `offline` (retained); `online` (retained) on every
  connect; `offline` published on a clean stop. paho reconnects with
  `reconnect_delay_set(1, 60)`; each connection state change is logged once.
- Saving, enabling, disabling or deleting a channel (UI or API) makes the
  publisher reload: a changed channel is stopped cleanly and reconnected
  with the new settings, without restarting STD.
- Settings → Notifications tab (admin): channel list with live status
  (connected / connecting / error with the last error / disabled) as cards (status
  dot, broker and base topic, Edit, an Enabled switch, a ⋯ menu with Send test,
  Scan for orphans, Purge and Delete), add and edit in one dialog (Connection,
  Authentication, Home Assistant, a collapsed Advanced block; a failed save reopens
  it with the typed values), enable/disable, delete; write-only password (blank keeps it, a checkbox
  clears it); **Send test** (in the dialog, or on a saved channel's ⋯ menu, which uses the stored password) publishes a non-retained JSON message to
  `<base>/test` using the submitted, possibly unsaved, values (a throwaway
  client with a `-test` client id, so the live connection is not dropped). The test runs on the request thread under one budget of about 5 s in total (connect wait 4 s, the publish wait gets the remainder, at least 1 s), so a broker that does not answer ends with "No answer from host:port within 4 seconds."
- Management API: `GET`/`POST /api/v1/notifications/channels`,
  `GET`/`PATCH`/`DELETE .../channels/{id}`, `POST .../channels/{id}/test`
  (read scope for GET, write for the rest). `secret` is write-only
  (`secret_set` in responses; PATCH omitted keeps, null clears); responses
  carry the live `status`. MCP: `list_notification_channels`,
  `get_notification_channel`, `test_notification_channel`.

### 17.3 State publishing [`notif-02-state-publishing`] — Delivered

Retained messages only (except `<base>/test`), QoS from the channel config.
`<base>` is the channel's base topic (default `std`). Topics use database ids,
so a rename never moves a topic. Payloads are compact JSON; timestamps are
UTC ISO 8601 (`2026-11-16T21:25:12Z`).

| Topic | Payload |
|-------|---------|
| `<base>/status` | `online` / `offline` (§17.2). |
| `<base>/entry/<entry_id>/state` | Roll-up of the entry (`health_state.entry_health`): `state` (`up`, `degraded`, `down`, `unknown`, `none`), `entry_id`, `name`, `host` (null for manual entries), `group` (group name or null), `source` (`notifier` / `manual`), `dashboard_url`, `since` (when `state` last changed), `checks` (`{up, down, unknown}` counts of the checks that count). Stream entries (§18.9): `missing` and `missing_since` (null for other sources); they never change `state`. |
| `<base>/entry/<entry_id>/check/<check_id>` | One check: `ok` (true / false / null before its first run), `state` (`up` / `down` / `unknown`), `entry_id`, `check_id`, `name`, `kind` (`container`, `internal_url`, `external_url`, `service`), `check_type` (`http`, `tcp`, `ping`, `dns`, or `container`), `target`, `latency_ms`, `status_code`, `message`, `consecutive_failures`, `last_checked_at`, `last_change` (when `ok` last changed). |
| `<base>/summary` | `{up, degraded, down, unknown, none, total}` over active (not soft-deleted) entries. |
| `<base>/stream/<stream_id>` | One inventory stream (§18.6): `stream_id`, `display_name`, `status` (`pending`, `enabled`, `disabled`, `ignored`), `producer`, `producer_version`, `last_snapshot_at`, `last_applied_at` (null before the first), `counts` (`{active, missing, pending_offers}`: entries not soft-deleted, those flagged missing, open link offers), `item_count` (the last snapshot's item count). §18.9 adds `stale` (computed at publish time; the health tick requests a sync when it flips), `expected_interval_seconds` (the effective one), `last_error`, `last_rejected_at` and `last_rejection`. |

- **Stream topic (notif-06).** Published for every stream, whatever its status
  (a `pending` stream shows an automation that it is waiting for review). It is
  part of the desired set, so `full_sync()` publishes it and clears it when the
  stream is deleted; entry topics never move under a stream path (topics use
  ids, and Convert / link must never move one). A commit that changes the
  stream's status, producer, display name, counts bookkeeping (`last_*`) or its
  link offers, or creates or deletes a stream, requests a sync like any other
  change (non-forced: only topics whose payload changed go out).
- Only checks that take part in the roll-up (`check_counts`: enabled and able
  to run) have a topic. `dashboard_url` is the path `/edit/<entry_id>`: STD has
  no configured public base URL, so it is never absolute.
- Change detection at `jobs.record_check_result()`, which returns True for the
  first result or an `ok` change. The scheduler thread, after the tick's writes
  commit, builds plain dicts and enqueues them (no ORM objects cross threads,
  no network I/O): a check event per changed check; an entry event when the
  roll-up or the per-state counts differ from what was last published; a
  summary event when any roll-up changed. Unchanged results publish nothing.
- **Reconcile, don't chase deletes:** `notify_state.full_sync()` runs on the
  publisher thread. It publishes the desired set (active entries, counted
  checks, summary) and an empty retained payload to every previously
  published topic that is no longer desired (soft delete, purge, a disabled
  or removed check). It runs, forced (every topic republished), on every MQTT
  (re)connect and every 10 minutes (an APScheduler job, the safety net); and,
  not forced (only topics whose payload changed), 2 seconds after any commit
  that changed what a topic carries (entry name, host, group, URLs, source,
  soft delete, a check's enabled/kind/name/type/target, a group's name), via
  `notify.request_sync()`. Nothing is published, and nothing remembered, while
  no channel has a live session; the connect that follows forces a sync.
- The published topic set persists in the `setting` key
  `notify_publish_state` (§5.8), so cleanup survives a restart. It is shared
  across channels: a topic cleared while a channel was unreachable stays
  retained on that broker.
- Out of scope: publishing every result (parked in FUTURE.md).

### 17.4 Home Assistant discovery [`notif-03-home-assistant-discovery`] — Delivered

Per channel, **Add to Home Assistant** (`ha_discovery`, default off) publishes
MQTT discovery so Home Assistant creates one device per STD entry that is
opted in (`ha_publish`, default false). Within a published entry every counted
check is published unless its `ha_exclude` is set; checks added later appear
on their own. Implemented in
`notify_ha.py` (pure config builders) and reconciled by `notify_state.full_sync()`
(§17.3), not by a second mechanism.

**Topics and ids.** Discovery topic
`<ha_prefix>/<component>/<node>/<object_id>/config` (`ha_prefix` default
`homeassistant`), retained. `<node>` is `std_<first 8 hex of the instance id>`,
so two STD installs never collide. The discovery topic is not under the base
topic; the events carry `absolute: true`, and discovery is sent per channel
(each carries that channel's base topic and prefixes).

| Device | Identifiers / fields |
|--------|----------------------|
| Hub | `identifiers: [<node>]`, `name` = `ha_device_prefix` (`STD`), `manufacturer: Service Tracker Dashboard`, `model: STD`, `sw_version` = the STD version. No `configuration_url`: STD has no configured public base URL. |
| Entry | `identifiers: [<node>_entry_<entry_id>]`, `name` = `<ha_device_prefix> <entry name> (<host>)` (`<ha_device_prefix> <entry name>` when the entry has no host), same `manufacturer`, `model` = `Docker container`, `Manual` or the stream's display name, `sw_version` = the image tag when the entry has one, `via_device: <node>` (a stream entry: `<node>_stream_<stream_id>`, see below). No `suggested_area` (the group is an attribute). |
| Stream hub | One per inventory stream that has at least one published (`ha_publish`, active) entry: `identifiers: [<node>_stream_<stream_id>]`, `name` = `<ha_device_prefix> <stream display name> stream`, `manufacturer`, `model: Stream`, `sw_version` = the STD version, `via_device: <node>`. |

| Entity | Config |
|--------|--------|
| Hub `binary_sensor` connectivity | object id `hub_connectivity`, unique id `<node>_hub_connectivity`; state topic `<base>/status`, on `online` / off `offline`. No separate availability topic (it would turn "off" into "unavailable"). |
| Hub `sensor`s `up`, `degraded`, `down`, `unknown` | object ids `hub_<state>`, unique ids `<node>_hub_<state>`; state topic `<base>/summary`, `value_template` `{{ value_json.<state> }}`. |
| Entry `sensor` "Since" | object id `entry_<id>_since`, unique id `<node>_entry_<id>_since`, `device_class: timestamp`; state topic `<base>/entry/<id>/state` with `value_template` `{{ value_json.since if value_json.since else None }}` (ISO 8601 UTC; null renders `None`, which MQTT sensors read as unknown). |
| Entry `sensor` "State" | object id `entry_<id>_state`, unique id `<node>_entry_<id>_state`, `device_class: enum`, `options: [up, degraded, down, unknown, none]`; state and `json_attributes_topic` = `<base>/entry/<id>/state`. |
| Stream hub `sensor` "Status" | object id `stream_<stream_id>_status`, unique id `<node>_stream_<stream_id>_status`, `device_class: enum`, `options: [pending, enabled, disabled, ignored]`; state and `json_attributes_topic` = `<base>/stream/<stream_id>`, `value_template` `{{ value_json.status }}`. |
| Stream hub `binary_sensor` "Problem" (§18.9) | object id `stream_<stream_id>_problem`, unique id `<node>_stream_<stream_id>_problem`, `device_class: problem`, ON while the stream is stale (`value_json.stale`); state and `json_attributes_topic` = `<base>/stream/<stream_id>`. On the existing stream hub device (streams have no `ha_publish` of their own). Cleared by the stream purge. |
| Stream hub `sensor`s "Active entries", "Missing entries" | object ids `stream_<stream_id>_active` / `_missing`, unique ids `<node>_stream_<stream_id>_<field>`, `state_class: measurement`; state topic `<base>/stream/<stream_id>`, `value_template` `{{ value_json.counts.active }}` / `.missing`. |
| Check `binary_sensor` | object id `check_<check_id>`, unique id `<node>_check_<check_id>`, `device_class: problem`, ON when the check's `state` is `down`; state and `json_attributes_topic` = `<base>/entry/<id>/check/<check_id>`. Name is the check's label (`HTTP`, `TCP 443`, `Container`, ...). |

Every entity except the connectivity sensor uses `availability_topic`
`<base>/status` (`online` / `offline`). Entity ids are suggested with
`default_entity_id` (`<component>.<slug of the device name>_<slug of entity
name>`, so they start `std_` by default and include the slugified host, e.g.
`sensor.std_traefik_host1_state`) for auto-entities globs; Home
Assistant keeps an id once registered. A rename republishes the config with the
same unique ids, so Home Assistant updates the device in place.

**Attributes.** The state payloads of §17.3 carry what auto-entities filters
need: both add `std_entry_id`; the check payload also carries `entry_name`,
`host`, `group`, `source` and `dashboard_url` (additive; no field was removed).

**Lifecycle.** The desired discovery set is: channel enabled with
`ha_discovery` on, times active entries with `ha_publish`, times their
counted checks without `ha_exclude`, plus the hub (always) and a stream hub device for every stream with at least one such entry. Everything previously
published for that channel and no longer desired (opt-outs, removed or disabled
checks, soft delete, purge, `ha_discovery` turned off or the prefix changed)
gets an empty retained payload on its config topic. Configs are published
before states on every sync. The published config topics are remembered per
channel id in the `setting` key `notify_publish_state` (`ha`). With
`ha_discovery` on the session subscribes to `<ha_prefix>/status` (the only
subscription, read-only); `online` (Home Assistant restarted) requests a forced
sync, republishing every config and then every state. A channel that is
deleted or disabled while discovery is on keeps its configs on that broker
unless the operator asked for the cleanup (§17.5, notif-06; STD no longer has a
session to clear them afterwards).

**Schema** (§5.9): `service_entry.ha_publish` (opt-in) and
`health_check.ha_exclude` (opt-out), both NOT NULL default false, operator-owned,
never written by register (tested). Both round-trip through backups. The state
topics are still published for an unpublished entry; only discovery is withheld.

**UI, API and MCP.** Settings → Notifications has the **Add to Home Assistant**
checkbox, **Discovery prefix** and **Device name prefix**. The entry edit page
and the Add Entry page have **Publish to Home Assistant** (default off; a hidden
marker keeps a form without the field from changing the stored value). Settings →
Home Assistant (its own section) lists active entries grouped by source (Docker,
Manual, then one group per stream; collapsed, tri-state group checkbox, live
"N of M"), each with a Publish checkbox, name, host and group, a search that opens
matching groups, Select all / Select none (visible rows) and a sticky Save bar,
shown only while dirty, that applies every change in a single commit (one sync).
A status line names the channels with discovery on and "N of M entries published";
when no *enabled* channel has discovery on (a disabled one publishes nothing) it
is an amber warning instead, and the section's nav link gets an amber dot if any
entry is ticked. Every check row (URL, container, service)
has **Publish to Home Assistant** (default on; stored inverted as `ha_exclude`;
a form that lacks the toggle's hidden marker leaves the stored value alone). The
controls are always visible and say they only matter with a Home Assistant
channel. The management API carries `ha_publish` on entries (read, create, PATCH) and
`ha_exclude` on checks (read and write; PATCH accepts it on every kind of
check) and the three `ha_*` channel config keys; the MCP `create_manual_entry`
/ `update_entry` accept `ha_publish`, `update_check` accepts `ha_exclude`.

Out of scope, parked in FUTURE.md: a "Check now" button entity (needs a
security review) and per-result latency sensors.

### 17.5 Purge [`notif-05-purge`] — Delivered

Two clean-slate tools, implemented in `notify_purge.py` and run on the publisher
thread (`Publisher.call()`): the request thread only queues the job and waits up
to 15 s for the counts (409 when the publisher is not running, 504 on timeout).
No new table, setting or migration.

**Channel purge.** For one enabled, connected channel the session subscribes
briefly (at least 1 s, until 0.6 s pass without a retained message, at most 6 s)
to `<base>/#` and `<ha_prefix>/+/<node>/#`, where `<node>` is this instance's
`std_<8 hex>` id (§17.4), so another STD install's devices are never touched.
Every topic that arrives with the retained flag, plus every topic in the
persisted published set for that channel, gets an empty retained payload,
**except `<base>/status`** (the last will). The channel's discovery bookkeeping
(`notify_publish_state.ha`) is cleared; the state-topic set (`topics`,
`payloads`) is one set shared by all channels and is emptied only when this is
the only live channel. Result: `topics_cleared`, `state_topics`,
`discovery_topics`, `republished`. Option `republish` (default true): true waits
2 s for Home Assistant, then runs a forced `full_sync()`; false puts the channel
on a **hold** (`PublishState.held`, in memory): every publish skips it until
something changes (any sync request from a commit or a health change releases it
and forces a full republish) or it reconnects. The 10-minute safety net runs
with `keep_held` and does not release it.

**Entry purge.** For one entry, on every live session: its state topic, every
check topic (all checks of the entry, enabled or not, plus any remembered) and
its discovery configs (`entry_<id>_state`, `check_<id>`) get an empty retained
payload and are dropped from the published sets; after 2 s a non-forced
`full_sync()` publishes whatever is still desired, so Home Assistant recreates
the device with fresh entity ids. An entry that is not opted in (`ha_publish`)
or is soft-deleted gets no discovery configs back; an opted-in active entry
gets state topics and configs. Result: `entry_id`, `topics_cleared`,
`channels[{id, name, state_topics, discovery_topics}]`, `republished`.

**Stream purge (notif-06).** For one inventory stream, one publisher job on every
live session: the state and check topics and discovery configs of every entry of
the stream (all of its checks, soft-deleted entries too), plus the stream's own
status topic (§17.3) and its hub device configs (§17.4). It is the entry purge
batched (`_purge_entries`), not N round trips; after 2 s a non-forced
`full_sync()` publishes whatever is still eligible, so a stream whose entries
were soft-deleted or purged brings back only its status topic (and the changed
summary), and entries that are not opted in to Home Assistant get no configs.
Result: `stream_id`, `entries`, `topics_cleared`, `channels[{id, name,
state_topics, discovery_topics}]`, `republished`.

**Channel delete and disable (notif-06).** Delete runs the channel purge with
`republish=false` and also clears `<base>/status`, last; the session is told not
to publish `offline` over it when it stops, then the channel row is deleted.
Default **on** (UI dialog ticked; management API `cleanup`, default true; MCP).
Disable offers the same purge, default **off**, and leaves `<base>/status` to
read `offline`. If the channel is disabled, not running or not connected, the
request is refused (409) and nothing is changed: the operator picks **Delete
anyway** (`cleanup=false`). The cleanup runs before the change is saved.

**Base topic / prefix change (notif-06).** Saving a channel whose `base_topic`
changed, or whose `ha_prefix` / `ha_device_prefix` changed while discovery was on,
first runs `clear_old_namespace()` on the channel's current session (so it works
even if the host changes too): a changed base clears every retained topic under
`<old>/#` (the old `status` too, and the session does not republish `offline` to
it); a changed prefix or device prefix clears this install's discovery configs
under the old prefix (a device prefix change republishes them with the new names
after the save). UI checkbox **Remove the old topics from the broker**, default on;
API `cleanup` on `PATCH`, default true for this case. A channel with no live
session (disabled) skips the cleanup silently; an enabled one that cannot be
reached refuses (409, nothing saved; send `cleanup: false`). Every such change
remembers the old `{base_topic, ha_prefix}` pair per channel (the last 5, newest
first; `notify_previous_bases`, §5.8), whether or not the cleanup ran.

**Orphan scan (notif-06).** `scan_orphans()` subscribes with the channel-purge
timing to `<base>/#` for the current base, every remembered previous base and an
optional operator-typed `extra_base`, plus this install's `<prefix>/+/<node>/#`
under the current and remembered prefixes, and diffs the retained topics against
the desired set: the desired state topics and `<base>/status` of every channel on
the same broker (host and port), and their discovery configs. Only topics shaped
like STD's own count (`status`, `summary`, `entry/<id>/state`,
`entry/<id>/check/<id>`, `stream/<stream_id>`, this node's discovery configs), so
an operator-typed base cannot sweep up another application; an `extra_base` equal
to a discovery prefix is refused. It is a preview. `clear_orphans()` with `topics`
(the scan's list) clears exactly those that are still inside the scanned
namespaces and still not desired (the rest return as `skipped`); without `topics`
it scans again and clears everything found. Results: scan `{channel_id, scanned,
count, orphans[{topic, kind}]}`; clear `{channel_id, topics_cleared, topics,
skipped}`.

**UI, API, MCP.** Settings → Notifications has **Purge MQTT and Home
Assistant** per channel (confirm dialog with **Republish afterwards**, counts
inline); the entry edit page has **Purge and republish to MQTT/HA** when a
channel is enabled. Both are POST, CSRF-protected and admin only
(`/settings/notifications/<id>/purge`, `/edit/<id>/purge-notifications`).
Management API (write scope; error shape as elsewhere, 404/409/504):
`POST /api/v1/notifications/channels/<id>/purge` (body optional,
`{republish: bool}`) and `POST /api/v1/entries/<id>/notifications/purge`; MCP
tools `purge_notification_channel` and `purge_entry_notifications`. Added by
notif-06 (revision 2): Settings → Streams has **Purge MQTT/HA** per stream row
(`/settings/streams/<slug>/purge-notifications`); Settings → Notifications has
a Delete / Disable dialog, **Scan for orphans** (`/settings/notifications/<id>/orphans/scan`
and `/clear`) and the base-change checkbox. Management API (write scope unless
noted; 404/409/504): `POST /streams/{stream_id}/notifications/purge`,
`DELETE /notifications/channels/{id}?cleanup=` (default true; the answer carries
`cleanup`), `PATCH` takes `cleanup`, `GET .../previous-bases` (read),
`POST .../orphans/scan` and `POST .../orphans/clear`. MCP: `purge_stream_notifications`,
`delete_notification_channel`, `update_notification_channel`,
`list_notification_previous_bases`, `scan_notification_orphans`,
`clear_notification_orphans`.

---

## 18. v0.10.0 — Inventory streams and API revision (Delivered)

For **0.10.0** (every subsection is delivered on `dev`, unreleased), together with §16 and §17. The goal is an STD that is
ready for the first inventory sidecar (`std-source-technitium`, a new repo,
§22.3). The stream code ships in 0.10.0 before any sidecar exists. It isn't
fully tested end to end yet, but nothing happens until an operator creates an
`ingest` key and enables a stream, so general users never touch it. Fixes found
while building the sidecar land in 0.10.x.

Design and rationale: `docs/design/2026-11-17-network-inventory-and-profiles.md`
(§5, §6, §10.2, §12) and `docs/decisions.md` (2026-11-17). Not in this release:
tags and saved views, thresholds and stored check state, monitor profiles,
HA merge mode, alert policies (design doc §11, slices 1, 2a, 2b, 4 and 5).

Prompts, run in order (each one depends on the one before):

| Prompt | Section |
|---|---|
| `inv-01-api-revision` | §18.1 |
| `inv-02-ha-since-and-db-snapshot` | §18.2 |
| `inv-03-source-refactor` | §18.3 |
| `inv-04-stream-ingest-backend` | §18.4–§18.7 |
| `inv-05-streams-ui` | §18.8 |

### 18.1 API revision [`inv-01-api-revision`]

**Delivered on `dev`.** As built: `meta` is registered in `mgmt_openapi.OPERATIONS` with no security requirement; the register User-Agent set is capped at 100 entries and each value is truncated to 200 characters; `std_version` comes from the build's version info (the `VERSION` file until the 0.10.0 prep).

The `/api/v1` surface gets a real contract version, separate from the STD app
version, so producers (the notifier, sidecars, the MCP server) can tell what the
server supports and log it.

- **`api_version.py`** holds `API_REVISION` (an integer) and
  `API_REVISION_HISTORY`, the table below in code.
- **Rule:** an additive change to any `/api/v1` contract (register, management,
  ingest) bumps the revision by one in the release that ships it, plus one row
  here. Breaking changes don't happen under `/api/v1`. They'd need `/api/v2`,
  with `/api/v1` kept for at least one release. CLAUDE.md's contract rules get
  the same line.
- **Header on every `/api/...` response**, errors included: `X-STD-API-Revision:
  <n>` and `X-STD-Version: <bare semver>`. It's set by one app-level
  `after_request` that checks `request.path.startswith("/api/")`.
- **`GET /api/v1/meta`**, unauthenticated, cheap, no DB access:
  `{"std_version": "0.10.0", "api_revision": 2, "features": ["register",
  "management", "notifications", "streams"]}`. Producers call it at startup.
  It reveals no more than the response headers do.
- `GET /api/v1/whoami` adds `api_revision`. The OpenAPI `info` adds
  `x-api-revision`. MCP `server_info` adds `std_api_revision`.
- **Producers** (documented in §22): send `User-Agent: <producer>/<version>`;
  log STD's version and API revision at startup and whenever the header value
  changes; when a feature they need is missing from `features`, log it clearly and
  keep retrying rather than exiting.
- **Register logging:** STD logs at INFO the first time it sees each distinct
  `User-Agent` on `/api/v1/register` (an in-memory set, so the log is once per
  restart and never per request).

| Revision | STD release | Adds |
|---|---|---|
| 1 | ≤ 0.9.0 | `/api/v1/register` (v0.5.0+, canonical since v0.6.0); management API (v0.8.0, v0.9.0 additions) |
| 2 | 0.10.0 | `meta`, revision headers; update-check settings (§16); notification channels, purge, cleanup and orphan scan (§17); stream purge; `ha_publish`; inventory streams and the `ingest` key scope (§18.4–§18.7) |
| 3 | 0.10.1 | Stream observability (§18.9): optional `snapshot_interval_seconds` on the snapshot PUT (ingest contract); stream `expected_interval_seconds`, `producer_interval_seconds`, `effective_interval_seconds`, `interval_source`, `stale`, `stale_message`, `stale_after_seconds`, `snapshot_age_seconds`, `missing_expiry_days`, `last_rejected_at`, `last_rejection`, `rejecting`; `stale` on `GET /streams`; `PATCH` takes the interval and the expiry; health summary `streams`, `stale_streams`, `counts.streams_stale`; `inventory.missing_since` |
| 4 | 0.11.0 | Backup settings, backup list and run, export (§20): `GET`/`PUT /settings/backup`, `GET /backups`, `POST /backups/run`, `GET /export`; feature `backup`. bak-04 extends this row with the import routes (one bump for the whole 0.11.0 set) |

### 18.2 HA "Since" sensor and nightly database snapshot [`inv-02-ha-since-and-db-snapshot`] — Delivered

*As built:* the snapshot is written to `<name>.tmp` and renamed into place, so
a half-written file never carries the `.sqlite3` name; the prune matches only
`-std_backup.yml` and `-std_backup.sqlite3`.

- **"Since" sensor.** Every published entry device (`ha_publish`) gains a
  `sensor` entity:
  - name "Since", `device_class: timestamp`, unique id `<node>_entry_<id>_since`,
    `default_entity_id` `sensor.<device slug>_since`;
  - it reads `value_json.since` from the entry state topic, which already carries
    it, so nothing new is published and PRD §17.1 (changes only) holds;
  - a null `since` must render as unknown, not as an invalid timestamp;
  - the device page then reads "Up · since 3 days ago".
- The "STD Health" naming from the design doc applies only to merge mode, which is
  not in this release.
- **Nightly SQLite snapshot.** The daily backup job also writes
  `<date>-std_backup.sqlite3` next to the YAML file in `backup_path`, made with
  `sqlite3.Connection.backup()` (WAL-safe, CLAUDE.md). It's pruned by the same
  `backup_days_to_keep`. A failure is logged and never stops the YAML backup.
  README documents the manual restore: stop the container, replace the database
  file, start it. The YAML format question stays in FUTURE.md.

### 18.3 Source refactor [`inv-03-source-refactor`]

**Delivered on `dev`.** No operator-visible change. `refactor:` commit, no CHANGELOG entry (recorded in
`docs/decisions.md`). It prepares the code for a third source value.

- Add `ServiceEntry.is_docker` (`source == notifier`).
- Switch every branch that uses `is_manual` / `!= manual` to mean "not Docker"
  over to `is_docker`: the Docker pill and container fields
  (`tiled_dash.html`, `edit_entry.html`, `dashboard.html`), `models.py`
  (`is_docker_status_stale` guard), and the HA `model` string.
- Keep `is_manual` where it really means "operator-made" (the Name label, the
  editable name and host rule in the management API).
- Generalise the two-value source filters (`view_helpers.normalize_source_filter`
  / `matches_source`, the `source` query on `GET /api/v1/entries`) to match any
  value in `VALID_SOURCES`.
- Make restore's source fallback (`routes_dashboard.py` restore loop) handle an
  unknown source by restoring as manual.
- Behaviour is identical. The existing suite must pass unchanged, plus tests
  for `is_docker` and the generalised filters.
- **As built:** `is_docker` treats an unflushed instance (`source` None) as
  Docker, matching the column default. Restore keeps the pre-0.7 backfill rule
  (never registered -> manual) for a backup with no `source` key at all; only a
  present-but-unknown value restores as manual. The HA `model` string comes from
  a `SOURCE_MODELS` map in `notify_ha.py` that inv-04 extends. The API `source`
  filter enum is built from `VALID_SOURCES`. Decision log entry 2026-11-17.

### 18.4 Schema [`inv-04`] — Delivered

**As built:** migration `f4c8a2e6d173`, documented in §5.10. Deviations from the list below: `inventory_stream.api_key_id` and the two `ON DELETE CASCADE` FKs are enforced by the ORM (`cascade="all, delete-orphan"`), because SQLite runs without foreign-key enforcement. `service_entry.container_name` stayed `String(100)` at first (SQLite doesn't enforce VARCHAR length, so a 128-character item name was stored whole anyway); migration `d7a3e9b2c418` (§5.10) widened it to 128 to match the contract.

One Alembic migration, FK indexes in the same migration. §5.10 is written when it
ships.

- **`inventory_stream`:**
  - `id`, `stream_id` (unique, the slug in the URL), `display_name`, `producer`,
    `producer_version`, `key_type`;
  - `status` (`pending` | `enabled` | `disabled` | `ignored`);
  - `api_key_id` (FK `api_key`, nullable, indexed), the key that created the
    stream;
  - `network_include` / `network_exclude` (JSON lists, NULL = no filter);
  - `snapshot` (JSON, the latest accepted items);
  - `first_seen_at`, `last_snapshot_at`, `last_applied_at`, `last_item_count`,
    `last_counts` (JSON), `last_error`, `created_at`, `updated_at`.
- **`service_entry`:**
  - `stream_id` (FK `inventory_stream.id`, nullable, indexed), `stream_key`;
  - `mac`, `ip`, `network`, `attributes` (JSON), `inventory_missing`
    (bool, default false);
  - `name_source` (NULL | `stream` | `ui_edit`).
  - Partial unique index on `(stream_id, stream_key)` where `stream_id IS NOT
    NULL`, soft-deleted rows included.
  - `source` gains the value `stream` (`VALID_SOURCES`).
- **`inventory_block`:** `id`, `stream_id` (FK, indexed), `key`, `name`, `ip`,
  `blocked_at`, `blocked_by`; unique `(stream_id, key)`. Kept when the entry is
  hard-deleted.
- **`stream_link_offer`:** `id`, `stream_id` (FK, indexed), `key`, `entry_id`
  (FK `service_entry`, indexed, cascade on delete), `item` (JSON),
  `created_at`; unique `(stream_id, key)`.
- **`api_key.scope`** gains `ingest`.

### 18.5 Ingest contract [`inv-04`] — the contract sidecars code against — Delivered

**As built:** wire shapes, status codes and field names are as specified below. Details the text leaves open:
- **Order of checks:** key (401) → `stream_id` pattern (400) → binding (403) → ignored (202) → body size (413) → JSON and pydantic validation (400) → `key_type` (409). An `ignored` stream is answered before the body is read, so it never returns 400 or 413.
- **Binding:** an `ingest` key may use a stream only when it is the key that created it. A stream whose creating key row is gone (`api_key_id` NULL) can only be used with a `write` key.
- **400 `details`** is the management list of `{loc, msg, type}`. A duplicate key, or a key that isn't a MAC when `key_type` is `mac`, reports `loc: ["items", "<index>", "key"]`.
- **Normalisation:** `key`, `name`, `network`, `display_name`, `producer` and `producer_version` are trimmed. `ip` is stored in canonical form (`str(ipaddress.ip_address(...))`). `mac` is always normalised, whatever the `key_type`.
- **`display_name`** is read only when the stream is created. A later snapshot never renames it.
- **Timestamps** in `GET .../status` are UTC ISO strings ending in `Z`; `last_counts` is null until the first apply.
- **The 202 `message`** reads `Snapshot stored, not applied. Enable the stream in Settings → Streams to import its N items.`
- The route is registered in `mgmt_openapi.OPERATIONS` (scope `ingest`) with the 200/202/400/401/403/409/413 responses; it is not audited (the after_request hook skips it by endpoint).

**Auth.** `Authorization: Bearer std_<prefix>_<secret>`, an admin API key with
scope **`ingest`** (or `write`, for testing with curl).
- An `ingest` key can call only the two routes below. It fails `read` and
  `write` checks everywhere else.
- A stream is bound to the key that created it. A later snapshot from a
  different `ingest` key gets 403. A `write` key may post to any stream.
- Rotating the key keeps the binding, because the key id is unchanged.

**`PUT /api/v1/streams/<stream_id>/snapshot`**

- `stream_id`: `^[a-z0-9][a-z0-9_-]{0,62}$`.
- Body (pydantic, `extra="forbid"` at every level):

| Field | Type | Rules |
|---|---|---|
| `display_name` | string | 1–32 chars. Used when the stream is created; later the operator may rename it in STD, and the producer's value is then ignored |
| `producer` | string | 1–64 chars, e.g. `std-source-technitium` |
| `producer_version` | string | 1–32 chars, bare semver recommended |
| `key_type` | string | `^[a-z0-9_]{1,16}$`. `mac` means every `key` must be a MAC. Can't change for an existing stream (409) |
| `items` | list | 0–5000 items. Keys must be unique within the snapshot (400 on a duplicate). `[]` is valid: everything goes missing |
| `items[].key` | string | 1–128 chars. For `key_type: mac`, any common MAC form (`aa:bb:..`, `AA-BB-..`, `aabb.ccdd.eeff`, `aabbccddeeff`), normalised to lower-case colon form |
| `items[].name` | string | 1–128 chars, the entry name (e.g. the reservation hostname) |
| `items[].ip` | string? | an IPv4 or IPv6 address |
| `items[].mac` | string? | as `key` for MAC forms. With `key_type: mac` and no `mac`, STD copies the key |
| `items[].network` | string? | 1–64 chars (for DHCP, the scope name). The stream's network filter matches on it |
| `items[].attributes` | object? | ≤ 32 keys matching `^[A-Za-z0-9_.-]{1,64}$`. Values are string (≤ 256 chars), number, boolean or null. Shown in STD, never interpreted |
| `snapshot_interval_seconds` | int? | **Revision 3** (§18.9). 60–86400: how often the producer posts. STD uses it for staleness unless the operator set an expected interval. Absent clears the stored value. An STD before revision 3 rejects it (`extra="forbid"`), so send it only when `meta` reports `api_revision >= 3` |

- Request body ≤ 2 MiB (413 above that). A snapshot is applied whole or not at
  all.

**Responses** (JSON; every response carries the §18.1 headers):

| Status | When | Body |
|---|---|---|
| 200 | stream `enabled`, snapshot applied | `{"stream_id", "stream_status": "enabled", "applied": true, "item_count", "counts": {"created", "updated", "unchanged", "restored", "missing", "blocked", "link_offers", "filtered"}}` |
| 202 | stream new (now `pending`) or `pending` / `disabled`: stored, not applied | `{"stream_id", "stream_status", "applied": false, "item_count", "message"}`. The message tells the operator to enable it in Settings → Streams |
| 202 | stream `ignored`: discarded, not stored | `{"stream_id", "stream_status": "ignored", "applied": false}` |
| 400 | validation failed | the management API error shape, with field errors |
| 401 / 403 | no or invalid key / wrong scope or another key's stream | the management API error shape |
| 409 | `key_type` differs from the stream's | the management API error shape |
| 413 | body too large | the management API error shape |

**`GET /api/v1/streams/<stream_id>/status`** (same auth): `{"stream_id",
"stream_status", "display_name", "last_snapshot_at", "last_applied_at",
"last_item_count", "last_counts"}`, or 404 if the stream doesn't exist yet. A
sidecar may log it at startup.

**Producer expectations** (the reference sidecar does all of these):
- post a full snapshot at startup, then every N minutes (default 5);
- retry with backoff on 5xx and network errors, and never exit on a failed post;
- log the response counts and `stream_status`;
- follow §18.1 (User-Agent, revision logging, `meta` at startup).

Snapshot PUTs aren't written to the API audit log, because they'd flood it every
few minutes. The stream row keeps the last counts. A 400, 409 or 413 answered to a
key bound to an existing stream is also kept on the row (`last_rejected_at`,
`last_rejection` = `"<status>: <first error>"`, §18.9); a 403 or a rejection before
the stream exists is not. Stream status changes made by
the operator are audited.

### 18.6 Applying a snapshot [`inv-04`] — Delivered

**As built:** `streams.plan()` / `streams.apply()`. `plan()` loads the stream's entries, blocks and open offers and the active manual entries once each (four queries) and diffs in Python; a test pins an apply of 5,000 items to at most 15 SELECTs. Details the text leaves open:
- **Filter:** matching is exact and case-insensitive. When `network_include` is set, an item with no `network` is filtered. An empty list means no filter. A filter change takes effect with the next snapshot (or Enable); nothing is re-applied when it is saved.
- **Counts** partition the items: `created + updated + unchanged + restored + blocked + link_offers + filtered = item_count`. `link_offers` counts items held back for an offer, new or still waiting. `missing` counts entries (not deleted) now flagged missing, not only the newly flagged ones.
- A key that is in the snapshot but filtered or blocked is not "missing", and its entry is left untouched.
- **Link offer matching (inv-06):** candidates are all active manual entries, with or without a host. An item matches an entry when the item's name, or its first DNS label (`z-wave-house.crzynet.me` -> `z-wave-house`), equals case-insensitively the entry's `container_name`, its `host`, or the first label of its `host`. Exactly one candidate makes an offer, else the item is created. A manual entry already offered to another key of the stream is not a candidate for a second one. The lookup is built in Python, so the query budget is unchanged. Accepting an offer or linking by hand **clears the entry's `host`** (stream entries have none). Register adoption, `find_duplicate` and the restore clash checks are unchanged.
- **Link offers:** an offer whose manual entry is gone, deleted or already converted is dropped at the next apply, and the item is processed as a new key. Accepting an offer, or linking by hand, removes the entry's other offers. The linked entry gets `name_source = ui_edit`, so a snapshot never renames the operator's entry.
- Register never matches, adopts or updates a `source = stream` row (a `source != stream` filter in `upsert_service`).
- **Entry edit:** the management API and the Edit page let the operator rename a stream entry (`name_source` becomes `ui_edit` when the name actually changes). `host` stays NULL, and a rename skips `find_duplicate`. The restore clash checks (Settings → Deleted, `POST /entries/{id}/restore`) skip stream entries.
- **MQTT:** `ip`, `mac`, `network` and `stream` are always present in an entry's payload (null for notifier and manual entries). `InventoryStream.display_name` is watched too, so renaming a stream republishes its entries and updates the HA device `model`. Each stream also has a retained status topic `<base>/stream/<stream_id>` (§17.3) and, with Home Assistant discovery on and at least one published entry, a hub device with status and active / missing count sensors that its entry devices hang off (§17.4); entry topics stay under `entry/<id>` and never move.
- A failed apply rolls back, records `last_error` on the stream and answers 500.

Applied in the ingest request, in one transaction, under an in-process lock (the
`upsert_service` pattern). STD makes no outbound calls here. For an `enabled`
stream:

1. **Filter.** Drop items whose `network` fails the stream's include/exclude
   lists (`filtered`).
2. **Blocked.** Skip keys in `inventory_block` (`blocked`).
3. **Known key** (an entry of this stream with this key):
   - overwrite `ip`, `mac`, `network`, `attributes`; clear `inventory_missing`;
   - `container_name` follows `name_source`: overwritten unless `ui_edit`;
   - a soft-deleted row is **restored** (`deleted_at` cleared; `restored`);
   - group, description, icon, checks and `ha_publish` are never written.
4. **New key:**
   - if exactly one active manual entry matches the item (name, host or first DNS
     label of either, ignoring case; see the matching note above) and no open offer
     exists, record a `stream_link_offer` (`link_offers`)
     and create nothing;
   - with an open offer for the key, keep waiting;
   - otherwise create an entry: `source = stream`, `host` NULL, `container_name` =
     name, `name_source = stream` (`created`).
5. **Missing.** Every entry of this stream whose key isn't in the snapshot, and
   isn't soft-deleted, gets `inventory_missing = true` (`missing`) and, when newly
   flagged, `inventory_missing_since` (§18.9). Nothing is deleted here; an optional
   per-stream expiry soft-deletes long-missing entries later (§18.9).

Also:
- **Enable** applies the stored snapshot immediately, with the same rules.
- **Default checks (inv-06).** A stream's `default_checks` (`{"ping": bool,
  "tcp_port": int | null}`) gives each *new* stream entry an enabled Ping check on
  its IP and, when a port is set, a TCP check on `ip:port` (service checks, built
  with `check_form`); an entry without an IP gets none. Without `default_checks` a
  stream entry has only the dormant URL rows. **Apply to existing entries** (UI
  button, `POST /streams/{id}/default-checks/apply`, MCP `apply_stream_default_checks`)
  adds the missing ones to every active entry and skips an entry that already has a
  check of that kind (any Ping, any TCP), so nothing is duplicated and customised
  checks are untouched. Saving `default_checks` never changes existing entries.
  Templates come with monitor profiles (design doc §7).
- The MQTT entry payload adds `ip`, `mac`, `network` and `stream` (the display
  name). `notify_state._ENTRY_ATTRS` adds `ip`, `mac`, `network`, `stream_id` and
  `inventory_missing`. `attributes` isn't published in this release. The HA
  `model` string for a stream entry is the stream's display name.

### 18.7 Stream lifecycle, blocks and link offers [`inv-04`] — Delivered

**As built:** the lifecycle is plain functions in `streams.py` (each commits once); the management routes below wrap them. All are in `mgmt_openapi.OPERATIONS`, with an MCP tool each. They take the stream's slug, not its numeric id.

| Route | Scope | What it does |
|---|---|---|
| `GET /streams`, `GET /streams/{stream_id}` | read | status, producer and version, counts, filters, `default_checks`, last error, entry counts, blocks and offers. The list also returns `pending` (streams waiting for review). Additive inside revision 2 |
| `PATCH /streams/{stream_id}` | write | `display_name`, `network_include`, `network_exclude`, `default_checks` (null clears); revision 3: `expected_interval_seconds` (60–86400, null = producer's or 15 min), `missing_expiry_days` (1–3650, null = off) (§18.9) |
| `POST /streams/{stream_id}/default-checks/apply` | write | add the stream's missing default checks to its active entries; returns `{stream, entries, entries_changed, checks_added}` |
| `GET /streams/{stream_id}/preview` | read | counts plus the per-item action, and the entries that would go missing (409 with no stored snapshot) |
| `POST .../enable`, `.../disable`, `.../ignore` | write | `enable`: pending, disabled or ignored, applies the stored snapshot. `disable` (body `cleanup`, `clear_blocks`): enabled only. `ignore`: pending or disabled; discards the stored snapshot. Any other state is 409 |
| `DELETE /streams/{stream_id}?cleanup=` | write | delete a stream |
| `GET .../blocks`, `DELETE .../blocks/{block_id}` | read / write | list, unblock |
| `GET .../offers`, `POST .../offers/{offer_id}/accept`, `.../decline` | read / write | list, answer (enabled streams only) |
| `GET .../unmatched`, `POST .../link` (`entry_id`, `key`) | read / write | items with no entry yet; link an active manual entry by hand (its host is cleared) |
| `POST /entries/{id}/unlink` (`block`) | write | a stream entry goes back to manual (inv-07); not under `/streams` because it acts on an entry. 409 for a non-stream or deleted entry |

- `DELETE /api/v1/entries/{id}` takes `block=true` (a stream entry, first delete only; 400 otherwise or with `permanent`). The session routes (`POST /api/v1/entries/<id>/delete` and the Edit page delete) take a `block` flag too; the dialog that sets it is §18.8.
- **Delete a stream** removes its blocks and link offers with it, so `clear_blocks` only means something for `disable` with `purge`; `disable` ignores it for the other cleanups. With `keep`, `mac`, `ip`, `network` and `attributes` stay on the entries that become manual. `soft_delete` also turns the soft-deleted entries into manual ones, so they stay restorable from Settings → Deleted.
- `streams.customised_entries()` and `streams.entry_stats()` back the cleanup dialog's counts and its list of customised entries (renamed, grouped, described, with an icon, checks or Home Assistant).
- **Linked entries (inv-07).** An entry that was a manual entry and joined the stream (`stream_linked`, §5.10) belongs to the operator. `soft_delete` and `purge` on a disable, and every option on a stream delete, **unlink** it (`streams.unlink_entry`: back to `source = manual`, `stream_id`/`stream_key`/`name_source` cleared, `host` restored from `pre_link_host`) instead of deleting it, and count it in `unlinked` (`result.unlinked` on the disable and delete responses). Disable with `keep` leaves it attached and publishing. Entries the stream created keep the old behavior. An already soft-deleted linked entry is unlinked too (it stays deleted), never purged. `unlink_entry(entry, block=False)` also works on a stream-created entry (it just becomes manual); `block` adds the key to the block list, otherwise the next snapshot may offer the link again. If the restored `(host, name)` is taken (`find_duplicate`) the host stays NULL and the result says so (`host_clash`). The unlinked entry keeps its id, so MQTT topics don't move; the commit listener republishes its payload and its HA device moves from the stream hub to the STD hub. `entry_stats()` gains `linked`; `streams.linked_entries()` backs the dialog; linked entries are left out of `customised_entries()` (nothing is lost for them). `inventory.linked` on entries.
- Audited: status changes (with the counts), cleanups, unblocks, link answers and the entry delete's `stream_block`. Snapshot PUTs are not.

**Operator actions.** The same functions sit behind the UI (§18.8), the management
API (read / write scope) and MCP:

- **List / get streams:** status, producer and version, counts, filters, last
  error (and, from revision 3, the §18.9 observability fields).
- **Preview** a stream's stored snapshot: what an apply would do (counts plus the
  per-item action), with no writes.
- **Enable** (applies now), **Disable**, **Ignore**.
  - Disable takes `cleanup`: `keep` (entries stay, no longer updated) |
    `soft_delete` | `purge` (hard delete through `hard_delete_entry`, plus the
    link offers and last counts; the stored snapshot is kept in every mode). Purge also takes `clear_blocks` (default
    false).
  - The response gives counts.
- **Delete a stream** takes the same `cleanup` options. With `keep`, its entries
  become manual (`source = manual`, `stream_id`/`stream_key` cleared, `mac`/`ip`
  kept).
- **Update a stream:** `display_name`, `network_include`, `network_exclude`,
  `default_checks`.
- **Blocks:** list, unblock (the next snapshot restores the row or creates a new
  one).
- **Link offers:** list, accept, decline.
  - **Accept:** the manual entry becomes `source = stream` with the key and
    observation fields, keeping its id, history, checks and `ha_publish`.
  - **Decline:** a new stream entry is created from the stored item.
  - **Link by hand:** the operator links a manual entry to an unmatched item of the
    stream's latest snapshot.
- **Delete a stream entry:** the entry delete (UI and `POST
  /api/v1/entries/<id>/delete`) takes `block` (default false). True also writes an
  `inventory_block` row for `(stream_id, key)`.
- **Rename a stream entry** in the UI or API: `name_source = ui_edit`.

Every new management route is registered in `mgmt_openapi.OPERATIONS` (tests
enforce it). Stream status changes, cleanups, unblocks and link answers are
audited.

### 18.8 Streams UI [`inv-05`] — Delivered

**As built:** server-rendered, no new JSON endpoints. The lifecycle rules stay in
`streams.py`; the session routes in `routes_dashboard.py` (admin, CSRF-protected,
POST) read the form, call one function and flash the outcome (a `StreamError`
becomes a flash, never a 500). Deviations and details:

- **Settings UI (settings modernization phase 3, §19):** one card per stream (status
  dot, producer, last snapshot, interval, counts, errors) with **Edit** and a ⋯ menu
  (Preview, Enable, Ignore, Purge MQTT/HA, Disable…, Delete…); the read-only Docker
  (register) card moved to the top of Settings → Docker in phase 4. Pending and stale streams are flagged inline above the
  list (pending carries Preview / Enable / Ignore). **Edit stream** is one dialog per
  stream with three independent forms (`update`, `monitoring`, `default-checks`, plus
  **Apply to existing entries**); a value error or `StreamError` from those three routes
  re-renders Settings with the dialog open and the typed values (HTTP 400) instead of
  flash + redirect; success still flashes (a toast) and redirects. Preview opens in a
  wide dialog (`stream-preview-modal`, opened by the server; closing drops `?preview=`
  from the URL). Blocked and Link offers are compact lists, and the Streams link shows
  an amber count for open offers beside the pending and stale counts. The lifecycle
  routes below keep flash + redirect. The notes below describe the original table
  layout where they mention rows or panels.
- **Routes:** `POST /settings/streams/<stream_id>/{enable,ignore,disable,delete,update}`,
  `.../blocks/<id>/unblock`, `.../offers/<id>/{accept,decline}` (takes a same-site
  `next`, so the edit page's banner returns to the edit page), and
  `POST /edit/<id>/stream-link` (`target` = `<stream_id>:<key>`).
- **Preview** is the same page with `?section=streams&preview=<stream_id>` (a GET):
  a table of the items with their would-be action plus the entries that would go
  missing, capped at 1,000 rows.
- **One cleanup dialog per stream** serves both Disable… and Delete…; `clear_blocks`
  shows only for disable with purge. Deleting a stream always drops its blocks and
  offers, and the dialog says so.
- **Network filters** are two textareas (one per line, commas also split); empty
  clears.
- **Source filter** value for one stream is `stream:<stream_id>` (`all`, `notifier`,
  `manual` and `stream` still work). An unknown stream id matches nothing; text that
  is not a stream id falls back to `all`.
- **Views:** the full pill (`partials/stream_pill.html`, with the ghost marker for a
  missing item) is on the Dashboard view only, replacing the grey "Manual" pill.
  Tiled and Compact (inv-06) use `partials/stream_icon.html`: a `ti-router`
  `status-icon`, `status-icon-ok`, or `status-icon-warn` when the item is missing,
  tooltip "Stream: <name> — <ip>" plus "— missing from the latest snapshot"; no
  ghost marker there. On Tiled it takes the Docker icon's slot (and the drawer keeps
  its Stream/Network rows). Compact shows one source icon per row
  (`partials/source_icon.html`): `ti-brand-docker` with Tiled's status classes and
  tooltips, the stream icon, or the muted `ti-link` for manual entries; nothing else
  from Tiled's status row. The Dashboard's expanded detail (and the edit page's
  health panel) show a stream entry's stream, IP, MAC and network
  (`.health-detail-facts`, read-only).
- **inv-06 additions:** a pending or disabled stream with a stored snapshot shows
  "would: created 5, link offers 2" in Last counts (one read-only `plan()`); a
  stream with no stored snapshot shows "Waiting for the next snapshot" in place of
  Preview. `inject_globals` supplies `pending_streams` to every page for
  authenticated users (try/except, never breaks a page); while it is above zero the
  header's Settings link gets an amber ring and count badge and goes to Settings →
  Streams. A "Default checks" panel per stream row (ping, TCP port, **Apply to
  existing entries**; `POST /settings/streams/<id>/default-checks[/apply]`). The
  Disable…/Delete… dialog states what each mode removes. Settings → Notifications'
  Home Assistant entries table has a **Source** column (Docker, Manual or the
  stream's display name) that the filter box matches. The Add page's field is
  "Docker host (optional)" with help that says to leave it blank for a device or VM
  (mirrored on the edit page for manual entries); the Convert banner and the link
  picker say the host will be cleared.
- **Delete popover:** the trash popover on Dashboard and Tiled and the edit page's
  Delete button show **Allow re-adding** / **Don't re-add** for stream entries
  (`data-stream="1"`) and send `block` to `POST /api/v1/entries/<id>/delete`.
- **inv-07 (unlink):** the Disable…/Delete… dialog has a "linked entries" box naming them and their restored host ("N linked entries go back to manual entries (with their host); they are never deleted"). A stream entry's edit page has **Unlink from stream…** in the stream info box (`POST /edit/<id>/stream-unlink`, a `<details>` with **Allow re-offering** and **Don't re-add** submit buttons) and a "Linked from a manual entry" note for a linked one.
- **Edit page:** a stream entry has no Host field. The "Link to stream item…"
  picker lists unmatched items of every stream and shows for any manual entry
  (host or not) with no open offer.
- The UI actions are logged, not written to `api_audit` (that log is for API keys).


- **Settings → API:** the key scope select gains **Ingest (sidecars)**, with a
  one-line explanation.
- **Settings → Streams** (new tab):
  - one row per stream: display name, `stream_id`, producer and version, status,
    last snapshot (relative time), item count, last counts, last error;
  - actions: **Preview** (a table of items with their would-be action), **Enable**,
    **Disable…** / **Delete…** (a dialog with counts first, the three cleanup
    choices, and the customised entries listed by name), **Ignore**;
  - inline edit of the display name and the network include/exclude lists;
  - a read-only **Docker (register)** row (now in Settings → Docker): the number of
    notifier entries and the last register time;
  - a pending stream is highlighted with "New stream waiting: enable it to import
    N items";
  - **Blocked** sub-list with **Unblock**; **Link offers** sub-list with
    **Accept** / **Decline**.
- **Entries:**
  - stream entries show a pill with the stream's display name where Docker
    entries show the Docker pill (Dashboard, Tiled, Compact);
  - "missing from the latest snapshot" shows as a muted marker (an amber warning badge with "since" from §18.9);
  - the source filter lists each stream.
- **Edit page** for a stream entry:
  - read-only MAC, IP, network, attributes and stream;
  - the name is editable, and editing it sets `ui_edit`;
  - deleting asks **Allow re-adding** / **Don't re-add**.
- **Edit page for a manual entry:**
  - with an open offer, a banner: "Stream DHCP item `shelly-pump` (aa:bb:…)
    matches this entry. **Convert** / **Keep separate**";
  - otherwise **Link to stream item…**, which picks from unmatched items.
- README: an "Inventory streams and sidecars" section (what a stream is, the
  `ingest` key, the pending → enable flow, cleanup, the block list, a link to
  §18.5 for sidecar authors) — delivered.

### 18.9 Stream observability [`inv-08-stream-observability`] — Delivered in v0.10.1

A dead producer or a removed record must not go unnoticed. API revision 3. Design
decisions and rejected alternatives: `docs/decisions.md` (2026-11-20).

**Per-stream state.** `inventory_stream` gains (migration `c6f2a8d4e157`, §5.10)
`expected_interval_seconds`, `producer_interval_seconds`, `missing_expiry_days`,
`last_rejected_at` and `last_rejection`.
- **Rejected snapshots:** a 400 (pydantic or the value rules), 409 (`key_type`) or
  413 answered to a key bound to an existing stream sets `last_rejected_at` and
  `last_rejection` (`"<status>: <first error>"`, truncated to 255) in its own commit
  (`streams.record_rejection`). Kept apart from `last_error` (an STD-side apply
  failure, cleared by a good apply); a later good snapshot does not clear the
  rejection, `rejecting` (rejected after the last accepted snapshot) says whether it
  is current. Not audited. A 403, or a rejection before the stream row exists, is not
  recorded.
- **Exposed** on `GET /streams` (plus `stale`, the count of stale streams), `GET
  /streams/{id}`, MCP `list_streams` / `get_stream`, and a compact `streams` block in
  `GET /health/summary` (`stream_id`, `display_name`, `status`, `stale`,
  `last_snapshot_at`, `last_item_count`, `effective_interval_seconds`, `last_error`,
  `last_rejected_at`, `last_rejection`, `entries_active`, `entries_missing`). The
  Settings → Streams row shows the interval and its source, a red **stale** badge
  with the reason, "Apply error: ..." and "Rejected <time>: ...".

**Staleness** (`streams.stream_health`, computed on read):
- effective interval = the operator's `expected_interval_seconds`, else the
  producer's advertised `snapshot_interval_seconds` (§18.5, stored as
  `producer_interval_seconds` on every accepted snapshot), else 900 s;
  `interval_source` is `operator` | `producer` | `default`.
- **stale** = status `enabled` and `now - (last_snapshot_at or first_seen_at) > 2 x
  interval` (`STALE_GRACE_FACTOR = 2`, strictly greater). Pending, disabled and
  ignored streams are never stale.
- Surfaced as: the Settings badge; a red count beside the pending count on the
  header's Settings link (`inject_globals` supplies `stale_streams`); in the health
  summary one `stale_streams` line per stale stream (`state: "down"`, `message` such
  as "No snapshot for 42 min (expected every 5 min)" plus the last rejection when the
  stream is rejecting, `since`) and `counts.streams_stale`; MQTT `stale` on
  `<base>/stream/<id>` (§17.3) and a `problem` binary sensor on the stream hub device
  (§17.4).
- **Entries of a stale stream are not marked stale**: their checks decide their
  health. They get a muted "stream stale" hint (pill and icon tooltips, Tiled
  drawer, detail facts, edit page).
- MQTT follows the clock through the existing health scheduler tick:
  `streams.watch_staleness()` runs at most every 30 s (one query), logs each
  transition once and calls `notify.request_sync()` when the stale set changes. No
  new thread.

**`missing` lifecycle.**
- An entry absent from the latest snapshot gets `inventory_missing = true` and
  `inventory_missing_since` (naive UTC, kept while it stays missing, cleared when the
  key returns, on unlink and on link). It is a **warning**, never Down: the health
  roll-up ignores it and checks keep running. UI: an amber **missing** badge with
  "since" on the Dashboard, the amber router icon with "since" in its tooltip on
  Tiled and Compact (and the Tiled drawer), a "Missing ... since" fact in the
  detail panel and a note on the edit page. API: `inventory.missing_since`. MQTT
  entry state: `missing`, `missing_since` (null for other sources).
- **Auto soft-delete (optional, per stream):** `missing_expiry_days` (1–3650, NULL =
  off, the default; Settings → Streams "Staleness and missing entries", `PATCH`,
  MCP `update_stream`). `streams.expire_missing()` runs in the daily soft-delete
  purge job (00:25) before the purge, for enabled streams only, and soft-deletes
  every active entry missing for longer, **except** entries edited by a human
  (`streams.human_edits`): `stream_linked`, renamed (`name_source = ui_edit`),
  locked, a group, a description, an icon, an internal or external URL, a sort
  priority, a widget, `ha_publish`, or any service check that is not an untouched
  default check (exactly as `add_default_checks` made it). Each delete and each kept
  entry is logged. The item coming back restores the entry by key (§18.6 step 3);
  after `deleted_retention_days` the normal purge hard-deletes it (with retention 0,
  in the same run).

**Checks follow the IP** (templated targets rejected, see decisions). When an
apply or a link changes an entry's IP, `streams.follow_ips()` rewrites each service
check whose target points at the old IP (ping target; TCP / DNS host of
`host[:port]`; HTTP URL host, keeping port, path and userinfo; IPv6 bracketed),
logs it and requests a run at the next tick. Hostname targets are untouched. If the
item loses its IP the checks keep their target and a warning is logged. One query
loads the service checks of every IP-changed entry.

**Not monitored by default** (unchanged, now pinned by a test): a new stream entry
has only the dormant URL rows unless the stream has `default_checks`.

**MCP `server_info`** calls `GET /api/v1/meta` (3 s timeout) on every call and
returns the startup values (`startup`: version, revision, `checked_at`) beside the
current ones (`current`); on failure it falls back to the startup values with
`std_version_source: "as of startup <time>"`. `restart_advised` when STD's version or
revision changed since the MCP started; `update_advised` when the script is older
than STD (major.minor), with the `uv run .../v<std>/mcp/std_mcp.py` / `git pull`
command and "restart the MCP client". The startup notice stays. `list_streams`,
`get_stream` and `health_summary` describe every field they return.

---

## 19. v0.11.0 — Settings modernization (Delivered on `dev`)

The Settings page grew one tab per release and no longer looks like Add and Edit.
0.11.0 regroups it, gives every section a link, changes how messages are shown and
brings the page into the visual language of Add/Edit. Operator decisions and the full
design (component specs, per-section layouts, tests, risks) are in
[`docs/design/2026-11-20-settings-modernization.md`](design/2026-11-20-settings-modernization.md)
(mockup alongside) and `docs/decisions.md`. No schema, wire-contract, `/api/v1`
or API-revision change; the only route changes are where a route redirects to and a
few validation errors that re-render instead of redirecting.

### 19.1 Information architecture

Thirteen sections in six labelled groups, from `settings_sections.py`:

| Group | Section | Slug | Legacy `?section=` |
|---|---|---|---|
| General | About | `about` (default) | `info` |
| General | Configuration | `configuration` | |
| Dashboard | Groups | `groups` | |
| Dashboard | Widgets | `widgets` | |
| Sources | Docker (exposure interpreter) | `docker` | `exposure` |
| Sources | Streams (incl. Blocked, Link offers) | `streams` | |
| Integrations | Notifications | `notifications` | |
| Integrations | Home Assistant | `home-assistant` | |
| Access | Users | `users` | |
| Access | API keys | `api-keys` | `api` |
| Access | Audit log | `audit-log` | |
| Data | Backup & restore | `backup` | |
| Data | Deleted | `deleted` | |

Below `md` the sidebar becomes a `<select>` with one `<optgroup>` per group. Streams
shows pending (amber) and stale (red) counts, Deleted its count.

### 19.2 Deep links

The canonical URL of a section is `/settings#<slug>`. Section elements are
`id="section-<slug>"` (no element id equals a bare slug, so a hash never scrolls).
`?section=<slug-or-legacy>` is still accepted and is what every redirect uses, because
the server must know the section to place an error banner in it. The server renders
`data-initial-section` and `data-open-modal` on `#settings-root` (precedence: a
validation re-render's `section` > `?section=` > `streams` for `?preview=` >
`audit-log` for `?audit_key=` > the default), hides every other section itself, and
`static/js/settings/nav.js` canonicalises the URL with `replaceState`. Every redirect
to Settings goes through `_settings_redirect()` and carries its section.

### 19.3 Flash policy

The `flash()` categories keep describing the outcome; the template maps them
(`partials/_flash.html`): `success` / `info` / `message` become a toast that fades
after 5 s (paused on hover or focus); `danger` / `error` become a persistent,
dismissible error banner and `warning` an amber one, placed in the section (or modal)
where the action happened (`flash_target`). Things that ask the operator to act (pending
or stale streams, HA discovery off, API token missing, default credentials) stay inline.
Fetch results (test, purge, orphan scan) stay inline. A `flash_text` filter strips one
leading pictograph in toasts. Add and Edit share the partial: banners keep
`class="flash-alert"` first, toasts use `class="toast"`.

### 19.4 Shared components

`partials/settings/_macros.html` (section header with "Learn more", flash slot, inline
warning, status dot, card and card row, ⋯ menu, modal, modal block, switch, collapsible
group with tri-state checkbox, sticky save bar, empty state), `static/js/settings/ui.js`
(modal opener memory and guarded close, ⋯ menu keyboard support, the shared confirm
dialog and `data-confirm` forms, groups, the reset bridge), `static/js/flash.js`,
`unsaved_guard.js` `reset()`, and one "Settings & shared UI" block in
`static/css/dashboard.css` (including `btn-danger`, `btn-ghost`, `btn-sm` and the
previously undefined `bg-dashboard-info-box`).

### 19.5 Phases

| Phase | Prompt | Status |
|---|---|---|
| 1 | `prompts/2026-11-20-set-01-foundation.md`: registry, partial split, grouped sidebar, deep links, flash policy, shared kit, restyle of every section (no new layouts) | Delivered on `dev` |
| 2 | `prompts/2026-11-20-set-02-notifications-ha.md`: Notifications cards and channel modal; Home Assistant groups | Delivered on `dev` |
| 3 | `prompts/2026-11-20-set-03-streams.md`: Streams cards, Edit stream modal, Preview modal | Delivered on `dev` |
| 4 | `prompts/2026-11-20-set-04-remaining.md`: Groups, Widgets, Docker, Users, API keys (show-once modal), Audit log, Deleted, About, Configuration | Delivered on `dev` |

**Backup & restore is not part of this work.** Its section keeps the phase-1 restyle only;
the backup, export and import project rebuilds it (`docs/design/2026-11-20-backup-export-import.md`).

### 19.6 As built (phase 4)

- **Groups.** One card per group in priority then name order. The dialog `#group-modal`
  lives inside `#groups-form` with unnamed inputs and no second `<form`; **Apply** writes
  into the card's hidden `group-<id>-name|icon|priority` inputs and **Add group** into
  `new-name|icon|priority` (one at a time; the button then reads "Edit new group"). Delete
  toggles "Will be deleted · Undo" (only offered when the group has no active entries). A
  400 re-render shows the submitted values and per-row messages on the cards and opens the
  dialog on the first row with a message (`open_modal='group-modal'`, `data-group-id`). A
  stale table (no row to edit) keeps its banner in the section. Column sorting is gone.
- **Docker.** The always-on Docker (register) card (`id="stream-row-docker"`) moved here
  from Streams (operator decision). Layer directions are a card, per-host overrides are
  collapsible groups without a checkbox ("N overrides"), the form is guarded and its
  sticky bar reads **Save & recompute URLs** (disabled with no layers). Field names
  `layer:<L>` and `override:<host>:<L>` are unchanged.
- **Users.** Cards (username, Admin tag, email, last login) with **Set password**
  (`#password-modal`, `POST /settings/users/<id>/set_password`), ⋯ Delete (non-admins) and
  **Add user** (`#user-modal`, `POST /add_user`). A duplicate username or email re-renders
  (400) with the dialog open and username and email kept; the password is never echoed. A
  too-short password re-renders (400) with the set-password dialog open. Flashes use
  `danger`.
- **API keys.** Cards (name, scope tag, prefix, active or revoked, created / rotated / last
  used) with ⋯ Rotate and Revoke (revoked keys last, dimmed, no menu) and a **Create key**
  dialog. A validation error re-renders (400) with the dialog open and the name kept.
  Create and Rotate render Settings itself with `#api-key-secret-modal` holding the key
  (`#new-api-key`, `#copy-api-key`), keeping the old response headers (`no-store`; rotate
  also `no-cache` and `Pragma`). `nav.js` replaces the POST URL, so a reload is a plain GET
  without the key.
- **Deleted, About, Configuration, Widgets.** Deleted entries and detached widgets are
  cards (Restore or Attach, ⋯ Delete). About has the Version grid and an Update check card.
  Configuration is a table with a Source pill. Widgets are cards with ⋯ Copy API key (no
  more password field in the page).
- **Routes.** No new routes. `routes_dashboard.render_settings_for()` lets `routes_auth`
  re-render Settings without an import cycle.

---

## 20. v0.11.0 — Backup, export and import (In progress)

Settings → Backup & restore becomes two features: **database backups** for disaster
recovery and **export and import** of operator-set state. The full design (field
ownership tables, matching rules, the import engine, API and UI) is
[`docs/design/2026-11-20-backup-export-import.md`](design/2026-11-20-backup-export-import.md)
(mockup alongside) and its operator decisions are in `docs/decisions.md`. It is built in
five phases (`prompts/2026-11-20-bak-01` … `bak-05`); §20.1 and §20.2 have shipped on `dev`.
No change to the register or stream-ingest wire contracts.

**Goals (design §1).** The scenario "new machine, empty `/config`, restore what the
operator set" works with no hand edits. Import is safe by default (fill missing settings
only, every write previewed, nothing that differs overwritten without an opt-in), can be
re-run (idempotent), never deletes local data, and **an export never contains a secret**.
Old YAML backups (today's entry list) stay importable. Not in scope: a live database swap,
syncing two running installs, scheduled import, remote targets (S3, SFTP).

### 20.1 Backup jobs (Delivered, unreleased; bak-01)

- **Two daily jobs replace the single 00:05 job.** `backup_snapshot_job` (default 00:05)
  writes a WAL-safe copy of the database (`sqlite3.Connection.backup()` through a `.tmp`
  file and `os.replace`), and `backup_export_job` (default 00:10) writes the export. Each
  has its own switch, time of day (container local time), keep days and **Run now**. In
  the export job writes the versioned export (§20.2; until bak-02 it wrote the YAML
  entry list `<date>-std_backup.yml`).
- **Settings are editable in the UI** (Settings → Backup & restore) and stored in the
  `setting` table: `backup_path`, `backup_snapshot_enabled|time|keep_days`,
  `backup_export_enabled|time|keep_days|format`, plus the observed `backup_last_runs`.
  **Precedence is env > UI > `settings.yml` > default.** An environment variable
  (`BACKUP_PATH`, `BACKUP_DAYS_TO_KEEP`) shows the field read-only; `settings.yml` only
  seeds the value until the operator saves in the UI; **Reset** deletes the DB row.
  `backup_days_to_keep` seeds both keep-days values. No new file or env keys.
  `backups.effective_settings(app)` resolves them from the startup dict plus the DB and
  never calls `load_settings()`.
- **Scheduling.** The scheduler is kept in `jobs._SCHEDULER`; a settings save calls
  `jobs.reschedule_backups(app)` (reschedule, then pause a disabled job; a disabled job is
  registered and paused so the UI still shows its state). This relies on the single
  gunicorn worker. `backups._RUN_LOCKS` allows one run per kind at a time.
- **Files and retention.** Scheduled names are `YYYY-MM-DD-std_backup.sqlite3` and
  `YYYY-MM-DD-std_export.yml` (or `.json`, per the export format setting); a manual run puts a time in the name
  (`YYYY-MM-DD_HHMMSS-...`) so it never overwrites the day's scheduled file. Retention
  runs at the end of each job for that kind only, by mtime and by suffix; legacy
  `-std_backup.yml` files age out with the export retention; `backup.yml` and any other
  file are never deleted.
- **Path validation.** Absolute, created if missing, writable (a probe file); a folder
  outside `CONFIG_DIR` is a warning, not an error. Changing the path does not move files.
- **List, download, delete.** A list per kind (newest first, `manual` and `legacy` tags),
  `GET /settings/backups/<name>/download`, `POST /settings/backups/<name>/delete`, both
  through `backups.resolve_file` (bare filename, known suffix, real path inside the
  folder). Snapshots are downloadable from the UI only, never through the API, because
  they hold every secret.
- **Failure surfacing.** Each run records `backup_last_runs[kind]` (ok or the error). A
  failed run shows a persistent inline warning on its card and a red "!" on the Backup &
  restore navigation link until a later run succeeds. A manual run is synchronous.
- **Routes.** `POST /settings/backups/settings`, `/settings/backups/settings/reset`,
  `/settings/backups/run`, plus the two file routes above; all admin + CSRF, and every
  redirect lands on the Backup section.
- **Manual database restore** (until the staged restore, §20.5, ships) is documented in
  the README: stop the container, keep the current file, copy the snapshot over
  `services.db`, delete the `-wal` and `-shm` files, start the container.

### 20.2 Export format v1 (Delivered, unreleased; bak-02)

A versioned `std-export` document, the same content as YAML (default) or JSON, holding
**only operator-set state** (design §5), built by `export_format.build_export()` and
serialised by `export_format.dump(doc, "yaml" | "json")`. Natural keys, never database
ids; records are sorted (entries by kind, host, name; the rest by name or key) so two
exports diff cleanly; datetimes are UTC ISO 8601 with `Z`; a null field is left out.
YAML opens with a short comment listing what is not included.

- **Header:** `format: std-export`, `format_version: 1`, `exported_at`, `std_version`,
  `api_revision`, `instance_id` (informational; omitted until the install has one, and
  an export never creates it).
- **Top-level sections:** `settings` (exposure layers and per-host overrides,
  update-check, the backup schedule without the folder path), `groups` (name, priority,
  icon), `widgets` (name, URL, fields, `api_key_set`), `notification_channels` (name,
  type, enabled, non-secret `config`, `secret_set`), `streams` (identity, `key_type`,
  `producer`, `display_name`, informational `status`, filters, default checks, intervals,
  `blocks`), `entries`, `users` (username, email, admin, active).
- **Entry ownership (design §5.3).** `kind` is `docker`, `manual` or `stream`;
  identity is `(host, container_name)` for Docker and manual entries and `(stream,
  stream_key)` for stream entries (plus `name_source`, `linked`, `pre_link_host`).
  Exported: lock, description, group (by name), sort priority, `ha_publish`, widget
  reference, every check's configuration (`HealthCheck.to_config()`), **a URL only when
  operator-owned** (source `ui_edit`, or any URL on a manual or stream entry; the source
  is written so import can restore it), and **`image_icon` only for manual, stream and
  locked Docker entries** (an unlocked Docker entry's icon is rewritten on every
  register). Not exported: status, container ids, image metadata, networks and ports,
  IP, MAC, `attributes`, missing markers, exposure observations, label-owned
  (`explicit_label`) and `synthesized` URLs, health results, link offers, snapshots,
  timestamps.
- **Never a secret.** No MQTT password (`secret_set` instead), no widget API key
  (`api_key_set`), no password hash, no API key or its hash, no `api_audit`. A channel
  config key that looks like a secret is dropped as a second line of defence.
  Soft-deleted entries, widgets only they used and detached widgets are not exported
  (the database snapshot has them).
- **Reading.** The models are lenient (`extra="allow"`); `unknown_keys()` lists unknown
  keys by path for the import warning. `SUPPORTED_VERSIONS = (0, 1)`. Adding an optional
  field keeps `format_version` 1; a newer version is rejected. Per-record validation and
  the v0 reader belong to the import (bak-03).
- **Surfaces.** The daily and Run now export job writes `<date>-std_export.yml|json`
  (manual runs timestamped); `GET /settings/backups/export?format=yaml|json` (admin
  session; `Content-Disposition: attachment; filename="std_export_YYYYMMDD_HHMMSS.yml"`,
  `Cache-Control: no-store`) backs the **Download YAML** / **Download JSON** buttons on
  the Exports card; the management API (§14.4) has `GET /export` and the backup routes;
  the MCP server has `backup_settings`, `list_backups`, `export_config` and `run_backup`.
  `API_REVISION` is 4 (§18.1).

### 20.3 Import (Planned; bak-03, bak-04)

Import matches the file's records against the database **now** and shows a dry-run
preview; only ticked rows apply. A row is one of: matched with missing settings
(default ticked), matched but different (applies only in the overwrite mode),
identical, matched but deleted locally, ambiguous (the operator picks), not found
("Import as new"), waiting (its stream is not mapped or enabled), conflict, or invalid.
"Missing" means the local value is the value a freshly created row has. Matching is exact
and case-sensitive, to agree with what register adoption does later. Import never creates
streams or changes a stream's status, never modifies existing users, and creates new
users with no usable password.

### 20.4 Import engine and plan handoff (Planned; bak-03)

`importer.plan()` and `apply()` mirror `streams.plan()` / `apply()`. The plan is never
kept as an object: the UI stages the parsed upload as a JSON file in
`CONFIG_DIR/import-staging/` (60 minute TTL, bound to the user) and `apply()` **re-plans
under the register and stream locks** and compares a sha256 fingerprint of the selected
rows with the one shown; a difference writes nothing (the UI asks for a re-review; the API
answers 409). One transaction. The legacy entry-list YAML is read as format version 0.

### 20.5 Staged database restore (Planned; bak-05)

Pick or upload a `.sqlite3`, validate it read-only (`integrity_check`, an STD schema, a
migration revision known to this code), then **stage** it: nothing is swapped live. A
banner offers **Cancel restore** until the next start, when `restore_swap.py` (stdlib
only, run by `entrypoint.sh` before `alembic upgrade head`) keeps the current database as
`pre-restore-<timestamp>.sqlite3` through `Connection.backup()`, swaps the file, and never
stops STD from starting if anything fails. No management API for it.

### 20.6 Phases (design §16)

| Phase | Prompt | Scope | Status |
|---|---|---|---|
| 1 | `bak-01-scheduled-backups` | Backup settings, two jobs, manual run, list, path validation, last-run status (§20.1) | Delivered (unreleased) |
| 2 | `bak-02-export` | Export format v1, scheduled export, API revision 4, MCP (§20.2) | Delivered (unreleased) |
| 3 | `bak-03-import-engine` | `importer.py`, legacy v0 reader, tests; no UI | Planned |
| 4 | `bak-04-import-ui` | Import flow, API `import/plan` and `import/apply`, removal of the old restore | Planned |
| 5 | `bak-05-staged-restore` | Staged restore (§20.5) | Planned |

---

## 21. Versioning, Branches, and Releases

- `main` is the default branch and the source of truth for releases.
- All work happens on `dev`. PR `dev` → `main` when ready to release.
- Branch protection: require PR + green required checks, block
  force-push, block deletion. Required checks: `build` (image build,
  `publish.yml`), CodeQL, and the `CI` workflow jobs `Lint` (ruff,
  `ruff.toml`), `Config validation` (YAML/JSON parse), `Migration check`
  (`alembic upgrade head` on an empty DB, exactly one head),
  `Compose validation` (`docker compose config --quiet`), and `Test`
  (pytest, `tests/`; added in v0.6.9 — pending operator action to mark it
  required in branch protection). `CI` triggers on push to `dev`/`main`
  only.
- Registry retention: `.github/workflows/retention.yml` prunes GHCR
  versions weekly and after each publish — keeps the 30 most recent
  `sha-*` and 15 most recent semver versions, never deletes `latest`,
  `dev`, major tags, or untagged versions. Docker Hub has no retention
  (frozen at v0.6.7).
- Images are published by `.github/workflows/publish.yml` to
  `ghcr.io/crzykidd/service-tracker-dashboard`, the only registry.
  Docker Hub (`crzykidd/service-tracker-dashboard`) is frozen at v0.6.7
  and no longer published; there is no in-app registry banner.
- Image tags:
  - push to `dev` → `:dev`, `:sha-<short>`
  - push to `main` → `:latest`, `:sha-<short>`
  - GitHub Release published → `:latest`, `:<semver>`, `:<major>`
- The version is the single bare-semver line in the repo-root `VERSION`
  file. The Dockerfile copies it and writes `version=` into
  `/app/version.txt` (there is no `APP_VERSION` build arg), so `:dev`,
  `:latest`, and release images all report the real version. `app.py`
  falls back to `VERSION` for local runs without an image.
- Releases are cut with `/release-prep <version>` (on `dev`: bump
  `VERSION`, roll CHANGELOG, sync README/PRD/CLAUDE.md, open the PR) then,
  after merge and green `main` CI, `/release-cut <version>` (tag
  `v<version>` on `main` and publish the GitHub Release). `publish.yml`
  fails a `release` build whose tag (minus `v`) differs from `VERSION`.

---

## 22. Cross-Repo Coordination

This project is paired with
[docker-api-notifier](https://github.com/crzykidd/docker-api-notifier).

### 21.1 Contract ownership

STD owns the wire contract for the register endpoint. The notifier is
a producer — it sends what STD documents. Wire-format changes start
here; the notifier follows.

Because STD's `RegisterPayload` uses `extra="forbid"`, unknown keys
are rejected with HTTP 400 (not silently ignored). The
consumer-leads-producer-follows ordering rule is therefore strict:
any new field the notifier intends to send must be added to STD's
schema and shipped first. The notifier may lag arbitrarily; it must
not lead.

### 21.2 Release history

1. STD v0.5.0 shipped `/api/v1/register` (canonical keys) alongside
   the `/api/register` compat shim that translated legacy keys.
2. Notifier v0.3.0 switched to canonical keys against
   `/api/v1/register`.
3. STD v0.6.0 removed `/api/register` and all legacy-key handling.
   Operators on notifier v0.3.0+ are unaffected.
4. Notifier v0.4.0 is the paired release for everything new in STD
   v0.6.0: it populates the `networks` / `exposed_ports` /
   `published_ports` capture fields **and** introduces the YAML
   interpreter mechanism that emits `exposure_observations`. STD's
   synthesizer reads those observations and writes synthesized URLs
   into `internalurl` / `externalurl`. Pre-v0.4.0 notifiers continue
   to register successfully — they just don't send the new fields,
   so the capture columns stay NULL and STD treats the missing
   `exposure_observations` as "no update" (existing exposure rows
   are preserved). (A v0.3.2 was developed for the capture fields
   but was never cut as a release tag — it shipped inside v0.4.0
   alongside the interpreter mechanism. Do not present v0.3.2 as a
   shipped boundary; the only notifier release boundaries that
   exist on this axis are v0.3.0 and v0.4.0.)

---

### 21.3 Inventory stream producers (planned, §18)

From 0.10.0 STD also owns the **ingest contract** (§18.5), and inventory
sidecars are its producers. The first is
[std-source-technitium](https://github.com/crzykidd/std-source-technitium)
(new repo; Technitium DHCP static reservations), with its own version line,
image and release cadence. The same rules apply as for the notifier:

- **STD leads, producers follow.** The ingest schema uses `extra="forbid"`, so a
  new core field ships in STD first. New facts that STD doesn't interpret go in
  `items[].attributes`, which needs no STD release.
- **Safe degradation.** A newer STD must keep accepting an older sidecar's
  snapshots: new core fields are optional.
- **API revision** (§18.1): every producer (notifier and sidecars) logs STD's
  `X-STD-API-Revision` at startup and on change, and sends
  `User-Agent: <producer>/<version>`. The notifier picks this up in its next
  release. Until then STD works with it unchanged.

---

## 23. Open Questions

- **Widget retention granularity.** A flat retention window
  (`widget_value_retention_days`, made actually configurable in §12.3)
  may be too much for some widgets and not enough for others. A
  per-widget policy via the widget's `settings.json` is unscheduled;
  revisit once §12.3 ships and the global knob works.
- **API tokens per-source.** (Admin/management keys are planned in §14;
  this item is now only about the notifier's register token.) A single shared token works for a homelab
  but doesn't let you revoke a single notifier host. Per-host tokens +
  last-seen tracking? Unscheduled; §12.3 only closes the
  unset-token hole.
- ~~**Health check timeouts.**~~ Resolved in §12.8 (per-service timeout
  and TLS-verify override).
- **Read-replica for dashboard reads.** WAL handles concurrent reads
  fine at this scale, but if widget growth pushes DB size up, worth
  measuring. No evidence it's needed.
