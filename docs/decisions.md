# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

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
