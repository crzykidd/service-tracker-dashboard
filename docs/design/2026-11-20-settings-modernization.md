# Design: Settings modernization (0.11.0)

**Status:** design, awaiting operator approval (2026-11-20). No code has changed. Once
approved, phase 1 (`prompts/2026-11-20-set-01-foundation.md`) adds a planned PRD section
for it and this file becomes the reference for the four build prompts.
**Author:** operator decisions + Claude (design session, 2026-11-20).
**Code read:** `dev` at `d69d769` (after the 0.10.2 fixes). Trust the code where they
disagree.
**Mockup:** [`2026-11-20-settings-modernization-mockup.html`](2026-11-20-settings-modernization-mockup.html)
(static, fake data; open it in a browser).

---

## 1. Goals and non-goals

The Settings page grew one tab per release and no longer matches the rest of the app.
It has ten flat tabs, grey `bg-gray-700` buttons, `form-input` fields, bordered tables,
a long paragraph on top of every tab, and a green flash bar that stays on the page.
Add and Edit already look different.

Goals:

1. **Findable.** Thirteen sections in six labelled groups. Each section has a deep link
   (`/settings#<section>`), and reloads and post-save redirects return to it.
2. **One pattern.** Where it fits, a section is a header (title, one-line subtitle,
   **Add …**), a list of cards (name, status dot, short summary, **Edit**, a **⋯** menu),
   and one modal shared by Add and Edit.
3. **Quiet feedback.** A success shows as a toast that disappears by itself. An error
   stays as a dismissible banner in the section or modal where it happened. A
   validation error reopens the modal with the typed input kept.
4. **The same visual language as Add/Edit:** `btn-primary`, `btn-secondary`,
   `input-clean`, info-box cards, `rounded-lg`, the tokens in `static/css/dashboard.css`.

Non-goals:

- **No behaviour or API change beyond what is listed here.** The management API
  (`routes_mgmt_api.py`, `mgmt_*`), the OpenAPI registry, the MCP server, the register
  and stream wire contracts, `API_REVISION`, the database schema and the settings
  files stay as they are. The only route changes are where a route redirects to, a
  few validation-error paths that re-render instead of redirecting (§7, §9), and
  `create_api_key`/`rotate_api_key` rendering their show-once key inside Settings (§9.10).
- No new settings, channel types or stream features. Extras go in §15 (Later).
- No change to the Dashboard, Tiled or Compact views. The Add and Edit pages only
  change where they share the flash partial (§7.4).

## 2. Operator decisions (2026-11-20, final)

These are recorded in `docs/decisions.md` and are not reopened here:

- Sidebar groups: **General** (About, Configuration), **Dashboard** (Groups, Widgets),
  **Sources** (Docker, Streams), **Integrations** (Notifications, Home Assistant),
  **Access** (Users, API keys, Audit log), **Data** (Backup & restore, Deleted). One
  deep-linkable section each.
- Banners: success → auto-dismissing toast; errors → persistent dismissible banner in
  the section/modal; warnings that ask the operator to act (pending/stale streams, HA
  discovery off) stay inline. Long explanations shrink to a one-line subtitle plus an
  "ⓘ Learn more" disclosure.
- List + Add + modal everywhere it fits. Destructive actions sit in ⋯ and keep their
  confirm dialogs, restyled to the shared modal.
- The Notifications card and modal layout, and the Home Assistant section layout, are
  specified in the task and in §9.6–§9.7 below.
- Visual language: reuse what Add/Edit use.

## 3. Current state (inventory at `d69d769`)

### 3.1 Sections today

`templates/settings.html` (1,416 lines) holds nine sections inline. A tenth,
`partials/settings_streams.html` (375 lines), is included at the top of the main
column. The sidebar is a flat list of `<button onclick="showSection(id)">` in this
order: Info, Backup, Widgets, Groups, Users, Exposure, Notifications, Streams (with
"(N new)"), API, Deleted (with "(N)").

| Today (`section-<id>`) | Contents | Forms / dialogs | Inline JS |
|---|---|---|---|
| `info` | API-token-missing banner; default-credentials banner (`#credential-warning`, sessionStorage dismiss); version list; update-check form; config table (Key / Value / Source) | `save_update_check` | credential dismiss |
| `backup` | Backup card (Download / Save to server); Restore card (server or upload, scope) | `POST /settings` `action=backup` / `action=restore` (multipart) | `toggleRestoreSource`, file-name display |
| `widgets` | Read-only widget cards (URL, masked key + Copy, fields, last update, container) | none | `copyToClipboard` |
| `deleted` | Deleted entries table (Restore / Delete permanently with `confirm()`); Detached widgets table (Attach select / Delete with `confirm()`) | `restore_deleted_entry`, `purge_deleted_entry`, `attach_detached_widget`, `delete_detached_widget` | inline `confirm()` |
| `groups` | One `#groups-form` (`data-unsaved-guard`), sortable `#group-table`, per-row name/icon/priority/delete toggle, a "new" row, two save bars | `save_groups` | `sortTable`, `[data-group-delete-toggle]` |
| `users` | Users table (Set Password inline form; Delete with `confirm()` for non-admins); Add New User form | `auth.set_user_password`, `auth.delete_user`, `auth.add_user` | inline `confirm()` |
| `api` | Create key form (name, scope incl. **Ingest (sidecars)**); `#api-key-table` (Rotate / Revoke with `confirm()`); Audit log with key filter (`#audit-filter-form`, GET `section=api&audit_key=`), `#api-audit-table` / `#api-audit-empty` | `create_api_key` (renders `api_key_created.html`), `rotate_api_key` (same), `revoke_api_key` | none |
| `notifications` | `#notification-table` (Edit, Enable/Disable, Purge, Scan for orphans, Delete); `#purge-dialog`, `#channel-remove-dialog`, `#orphan-dialog`; `#notification-form` (`data-unsaved-guard`, add/edit in place); **Home Assistant entries** picker `#ha-entries-form` (filter, Select all/none, table with Source column) | `save_notification_channel`, `toggle_…`, `delete_…`, `test_…_form`, `purge_…`, `scan_…_orphans`, `clear_…_orphans`, `notification_status` (poll), `save_ha_entries` | about 300 lines: `fill()`, cleanup row, three dialogs, test, 5 s status poll, HA filter/select |
| `exposure` | Layer directions table; per-host overrides tables; Save & Recompute URLs | `save_exposure_settings` | none |
| `streams` (partial) | Pending banners; `#stream-table` with a read-only `#stream-row-docker`; per stream a row plus a details row (name/filters, `#stream-monitoring-<slug>`, `#stream-checks-<slug>`); Preview table `#stream-preview` (`?preview=`); Blocked `#stream-blocks`; Link offers `#stream-offers`; one `<dialog id="stream-dialog-<slug>">` per stream (Disable…/Delete…) | `stream_enable`, `_ignore`, `_disable`, `_delete`, `_update`, `_monitoring`, `_default_checks`, `_default_checks_apply`, `_purge_notifications` (fetch, `confirm()`), `_unblock`, `_answer_offer` | dialog mode switch; purge |

### 3.2 How the section is chosen today

- `_render_settings(group_form=None, status=200, notification_form=None)` passes
  `force_section` = `groups` (failed Groups save), `notifications` (failed channel
  save) or `streams` (preview present), else `''`.
- `settings.html` runs `showSection({{ force_section|tojson }} || ?section || 'info')`
  on `DOMContentLoaded`. Clicking a tab does not change the URL, so a reload goes
  back to the `?section` the page was loaded with, or to Info.
- Redirects after a POST use `url_for('dashboard.settings', section=…)` with `backup`,
  `info`, `groups`, `notifications`, `exposure`, `api`, `deleted`, `streams` or `users`.
  **Ten redirects have no section** and land on Info: the seven backup/restore error
  paths in `settings()` (backup exception, no file uploaded, invalid / missing /
  unselected server file, invalid source, records not loaded) and `routes_auth.py`
  `set_user_password`'s three (both errors and the success).
- The channel delete/disable dialog reloads to
  `url_for("dashboard.settings", section="notifications")` after its JSON call.
- `base.html`'s pending/stale header link and `api_key_created.html`'s "Back to API
  keys" use `?section=streams` / `?section=api`.

### 3.3 Flash sites

Every `flash()` that can surface on Settings, by category:

| Category | Where | Count |
|---|---|---|
| `success` | backup saved, restore done; channel saved; HA entries saved; channel toggle/delete (`_channel_action_result`); exposure saved; update check saved; groups saved / "No changes."; API key revoked; deleted restore / purge; detached widget attach / delete; every stream action (`_stream_action`, update, monitoring, default checks, apply, unblock, offer); `auth`: password updated, user created, user deleted | ~30 |
| `danger` | backup/restore failures; channel save field errors (one per error, re-render 400/409); channel action `PurgeError` (no-JS path); update-check interval; groups stale / "Nothing was saved" (re-render 400) / failed; API key name/scope, rotate of revoked; deleted restore clash; every `StreamError`; preview of an unknown stream; stream form value errors; `auth`: user exists, cannot delete admin, user not found | ~25 |
| `warning` | "No file uploaded for restore.", "No server backup file selected.", "Could not list server backup files" (flashed **during render**) | 3 |
| `error` | `auth.set_user_password` ("Password must be at least 6 characters", "User not found"), and login (not on Settings) | 2 + 1 |
| `info` | `auth.reset_user_password` (no UI calls it), logout (login page has no flash area) | 2 |

`partials/flash_messages.html` colours `danger` red, `warning` amber and **everything
else green**, so the `error` flashes from `set_user_password` show as green success
bars today. `_drop_stale_success_flashes()` (Add/Edit GET) keeps only `warning` and
`danger`.

### 3.4 JS hooks that must survive (or move deliberately)

- `static/js/unsaved_guard.js`: `form[data-unsaved-guard]`, `data-unsaved-start-dirty`,
  `data-unsaved-save`, `data-unsaved-hint`, `data-unsaved-discard`; sets
  `data-unsaved-dirty="true|false"` on the form; `form._unsavedGuard.{isDirty,disarm,refresh}`.
  Used by `#groups-form`, `#notification-form`, `#ha-entries-form` and the three
  stream details forms.
- Notifications: `[data-notification-edit]`, `[data-channel-remove="delete|disable"]`
  with `data-channel-id/-name/-connected/action-url`, `[data-notification-purge]` with
  `data-purge-url`, `[data-notification-orphans]` with `data-scan-url/-clear-url`,
  `.notification-state[data-state]`, `.notification-error`, `.notification-purge-result`,
  `tr[data-channel-id]`, `#nf-*` ids, `channels` JSON from
  `{{ notification_channels|tojson }}` (holds `secret_set`, never the secret).
- HA picker: `tr[data-ha-row]`, `[data-ha-source]`, `ha_entry_ids` (every row seen) +
  `ha_publish` (ticked) field names, `#ha-filter`, `#ha-select-all/none`.
- Streams: `.stream-dialog-open[data-dialog][data-mode]`, `.stream-dialog` with
  `data-disable-action/-delete-action`, `.stream-dialog-title/-submit/-cancel`,
  `.stream-keep-delete/-disable`, `.stream-delete-note/-disable-note`,
  `.stream-clear-blocks`, `.stream-notify-purge[data-url][data-name]`,
  `.stream-notify-result`.
- Groups: `[data-group-delete-toggle]`, `group-<id>-name|icon|priority|delete`,
  `new-name|icon|priority`.
- Global: `meta[name=csrf-token]` (fetch calls send `X-CSRFToken`).

### 3.5 Tests that read Settings markup

These pass today and break if the markup changes without care. Each build prompt lists
the ones in its scope. Unless noted, the "keep" column must survive as is.

| Test | Asserts | Phase |
|---|---|---|
| `test_groups_save.py:106-107` | `value="77"`, `value="typed-new"`, `data-unsaved-start-dirty` on 400 | 4 (keep) |
| `test_groups_save.py:147` | regex `name="group-\d+-priority" value="0"` (name **before** value) | 4 (keep) |
| `test_groups_save.py:196-197` | no `/update_group` etc.; `id="groups-form"` exactly once | 4 (keep) |
| `test_groups_save.py:202-207` | slices `id="section-groups"` … `id="section-users"` and expects **one** `<form` | **1** (section order changes: slice to the next `<section` instead), 4 (the group modal must add no `<form`) |
| `test_groups_save.py` `_flashes` | "Saved: 3 updated." etc. read from the session | keep |
| `test_ha_discovery.py:526` | "Home Assistant entries", "Select all" | 2 (update heading if renamed) |
| `test_stream_followups.py:235-237` | `<th class="py-2 px-3">Source</th>`, `data-ha-source>DHCP<` ×10, `data-ha-source>Manual<`, "Filter by name, host, source or group" | 2 (rewrite for groups) |
| `test_notify_cleanup.py:551-552` | `data-channel-remove="delete"` and `="disable"`, `data-notification-orphans`, `id="nf-cleanup-row"` | 2 (keep) |
| `test_notify_cleanup.py:711` | 409 re-render contains "Nothing was saved", "Remove the old topics" | 2 (keep) |
| `test_notify_cleanup.py:360-362` | `stream-notify-purge` only when a channel is enabled | 3 (keep) |
| `test_notifications.py:627-628,646` | "broker" in page, no secret; regex `"secret_set":\s*true`; 400 re-render has "config.port" | 2 (keep) |
| `test_purge.py:476` | "Purge MQTT and Home Assistant" in `/settings` | 2 (keep as the ⋯ label) |
| `test_streams_ui.py:52` | `<option value="ingest">Ingest (sidecars)</option>` | 4 (keep exact) |
| `test_streams_ui.py:65-68` | `id="section-streams"`, "Docker (register)", `id="stream-empty"`, regex `id="stream-row-docker">(.*?)</tr>` with `<td class="px-3 py-2">1</td>` | 3 (rewrite the row regex) |
| `test_streams_ui.py:74-77` | "New stream waiting:", `"to import\n    10 items"` (whitespace-exact), `data-stream-status="pending"`, `>Enable</button>`, `>Ignore</button>`, `>Preview</a>`, no `Disable…</button>` | 3 |
| `test_streams_ui.py:84-86,93` | `id="stream-preview"`, `class="preview-action"` ×10, `data-action="created"`/`"link_offer"`; unknown preview flashes "That stream … exist" | 3 (keep) |
| `test_streams_ui.py:185-190` | regex `<dialog id="stream-dialog-dhcp".*?</dialog>`; counts; `name="cleanup" value=…`; `name="clear_blocks"`; customised list; `Disable…</button>`, `Delete…</button>` | 3 (keep) |
| `test_streams_ui.py:207` | `_flashes()` has "display_name" after a bad stream update | 3 (update if the route re-renders: assert on the 400 page instead) |
| `test_streams_ui.py:217,231` | `id="stream-blocks"`, `>Unblock</button>`; `id="stream-offers"`, `>Accept</button>`, `>Decline</button>` | 3 (keep) |
| `test_streams_ui.py:99`, `test_mgmt_api_keys.py:624` | redirect `Location` contains `section=streams` / `section=api` | 1 (`section=api-keys` still contains `section=api`) |
| `test_stream_followups.py:88-106,209` | "would: created 9, link offers 1", `stream-waiting`, `stream-would-counts`, "Waiting for the next snapshot", "The stored snapshot is kept in every mode", "stored snapshot, its", "Default checks", "Apply to existing entries" | 3 (keep) |
| `test_stream_followups.py:117-119`, `test_stream_observability.py:197` | header `id="settings-pending-streams"`, `section=streams`, `ring-amber-400`, `id="settings-stale-streams"` (base.html) | keep |
| `test_stream_observability.py:200,428` | `stream-stale-badge`; `id="stream-monitoring-<slug>"`, "every 15 min (default)" | 3 (keep) |
| `test_stream_linked.py:280` | "2 linked entries go back to manual entries (with their host); they are never deleted" | 3 (keep) |
| `test_mgmt_api_keys.py:293-297` | create returns 200, `Cache-Control: no-store`, regex `id="new-api-key"[^>]*value="(std_…)"`, "won't see it again", `copy-api-key` | 4 (keep inside the show-once modal) |
| `test_mgmt_api_keys.py:308-317` | key not on the page later; "agent", "active", "revoked", `opacity-50` | 4 (keep) |
| `test_mgmt_api_keys.py:547` | `value="id:<n>"`, "agent (revoked)" in the audit filter | 4 (keep) |
| `test_mgmt_api_keys.py:585,594-595` | rotate `no-store` + `no-cache`; "Rotated"; regex `<td[^>]*>\d{4}-…UTC</td>` | 4 (rewrite the cell regex) |
| `test_mgmt_api_keys.py:605-608` | `<th class="px-4 py-2">Rotated</th>`, rotate URL, "The current key stops working immediately", `<td class="px-4 py-2">—</td>` | 4 (rewrite table asserts; keep the confirm text) |
| `test_mgmt_openapi.py:205-251` | `id="api-audit-table"`, audit row content, `<option value="alpha" selected>` (exact), "No API writes recorded[ for this key]", escaping | 4 (keep) |
| `test_soft_delete.py:69,172` | "Restore", "Attach" | 4 (keep) |
| `test_settings_loader.py:114,122` | "Default credentials in use", "API token not set" | 4 (keep) |
| `test_version_check.py:344,350` | "Latest release seen", "Last checked", "Update check disabled" | 4 (keep) |
| `test_check_config_ui.py:220,239,304`, `test_dns_check.py:335` (Add/Edit) | `class="flash-alert` present / counted twice (class attribute **starts** with `flash-alert`) | **1** (banners keep `class="flash-alert …"` first; toasts must not use that prefix) |
| `test_check_config_ui.py:370` | `_drop_stale_success_flashes` keeps the warning | keep |

## 4. Target information architecture

| Group | Section | Slug (`#…`, `section-<slug>`) | Legacy `?section=` | Content (moved from) |
|---|---|---|---|---|
| General | About | `about` *(default)* | `info` | warnings, version, update check (Info) |
| General | Configuration | `configuration` | — | read-only config table (Info) |
| Dashboard | Groups | `groups` | `groups` | Groups |
| Dashboard | Widgets | `widgets` | `widgets` | Widgets |
| Sources | Docker | `docker` | `exposure` | Exposure interpreter |
| Sources | Streams | `streams` | `streams` | Streams, Blocked, Link offers |
| Integrations | Notifications | `notifications` | `notifications` | channels |
| Integrations | Home Assistant | `home-assistant` | — | HA entries picker (Notifications) |
| Access | Users | `users` | `users` | Users |
| Access | API keys | `api-keys` | `api` | keys (API) |
| Access | Audit log | `audit-log` | — | audit log (API); `?audit_key=` with no section opens it |
| Data | Backup & restore | `backup` | `backup` | Backup |
| Data | Deleted | `deleted` | `deleted` | Deleted entries, detached widgets |

The sections and their order live in one registry, the new module `settings_sections.py`
(pure data: groups, slugs, labels, legacy aliases, `resolve(raw) -> slug | None`). The
template builds the sidebar and the mobile select from it, the routes use it to
validate `section`, and a test pins the order.

**Nav badges:** Streams shows the pending count (amber) and the stale count (red),
like the header link. Deleted shows its count (muted). Home Assistant shows an amber dot
when no enabled channel has discovery on and at least one entry is ticked.

## 5. Deep links and section restore

### 5.1 Scheme

- The canonical URL of a section is **`/settings#<slug>`**. Sidebar items are real
  links (`<a href="#streams">`). Middle-click, copy-link and the back button work, and
  each click adds a history entry (back walks through the sections).
- Section elements keep the id **`section-<slug>`**. **No element may have an id equal
  to a bare slug**, so the browser never scrolls to a hash target. A test checks this.
- `?section=<slug-or-legacy>` stays accepted, for bookmarks, `base.html`'s header link,
  every redirect and the tests. JS replaces it with the hash on load (§5.3).

### 5.2 How the server says where to land (chosen mechanism)

**The server passes `initial_section` and `open_modal` as template variables. The root
element renders them as `data-initial-section` and `data-open-modal`. Redirects keep
using `?section=<slug>`.**

```
redirect(url_for('dashboard.settings', section='notifications'))   # after a POST
_render_settings(section='notifications', open_modal='channel-modal',
                 forms={'notification': …}, status=400)              # validation error
```

`initial_section` precedence on the server: the `section` argument of `_render_settings`
(validation re-render) > `settings_sections.resolve(request.args['section'])` >
`streams` when `?preview=` is present > `audit-log` when `?audit_key=` is present > `''`.
In the browser: `data-initial-section` > the URL hash (aliases resolved) > `about`.

Why this rather than a hash in the redirect `Location`:

1. **The server must know the section to place errors.** An error banner belongs in
   the section where the action happened (§7). A fragment never reaches the server, so
   with `Location: /settings#streams` the template could not tell where to render the
   banner. With `?section=streams` it can.
2. **A validation error is a re-render, not a redirect.** It is a 400 response to the
   POST URL (for example `/settings/notifications/save`). There is no URL to put a hash
   on, so the page has to carry the section and the modal itself.
3. **The tests and existing links already use `?section=`.** Keeping it means no
   rewrite of redirect assertions, and old bookmarks keep working.
4. A query-only scheme would lose the "click a section, reload, stay there" behaviour,
   because clicks would need `pushState` with a query and a full reload would go to the
   server each time. The hash gives that for free.

### 5.3 Canonicalising the URL on load (`static/js/settings/nav.js`)

On `DOMContentLoaded`:

1. Pick the section (precedence above), show it, mark the nav link `aria-current="page"`
   and sync the mobile select.
2. `history.replaceState` to `<settings path>?<kept query>#<slug>`, where `settings
   path` comes from `data-settings-url` (`url_for('dashboard.settings')`). On the
   settings path, the kept query is the current query minus `section`; `audit_key` and
   `preview` stay. On any other path (a re-render of a POST such as
   `/settings/notifications/save` or `/settings/api-keys`), nothing is kept.
   **Effect:** a reload after a failed save or after creating an API key is a plain
   GET, not a form resubmission that would create a second key. (The unsaved guard
   still warns about the kept input.)
3. If `data-open-modal` names a dialog, open it (§6.6).
4. On `hashchange`, show that section. The mobile select's `change` event sets
   `location.hash`.
5. Closing the stream preview modal removes `preview` from the query with
   `replaceState`, so a reload does not reopen it.

Without JS, nothing changes compared with today: sections are server-rendered and the
initial one is not hidden. The server already knows `initial_section`, so it renders
the `hidden` class on every other section. This also avoids a flash of About before JS
switches the section on a `?section=` load.

## 6. Shared components

### 6.1 Files

| File | Holds |
|---|---|
| `settings_sections.py` | section registry, aliases, `resolve()` (§4) |
| `templates/settings.html` | shell only: layout, sidebar + mobile select, page-level flash slot, one `{% include %}` per section, toast region, scripts |
| `templates/partials/settings/_macros.html` | settings-only macros (§6.2) |
| `templates/partials/settings/<slug>.html` | one per section: `about`, `configuration`, `groups`, `widgets`, `docker`, `streams` (moved from `partials/settings_streams.html`), `notifications`, `home_assistant`, `users`, `api_keys`, `audit_log`, `backup`, `deleted` |
| `templates/partials/_flash.html` | `toast(category, message)`, `banner(category, message, dismissible=True)`, `flash_category_kind(category)`, shared by Settings and `flash_messages.html` |
| `templates/partials/flash_messages.html` | kept (Add/Edit include it): toasts for toast categories, banners for the rest |
| `static/js/flash.js` | toast auto-dismiss, banner dismiss; loaded by `base.html` (defer) |
| `static/js/settings/nav.js` | §5.3 |
| `static/js/settings/ui.js` | modal, ⋯ menu, confirm dialog + `data-confirm`, disclosure, tri-state groups, form-reset bridge (§6.3–§6.9) |
| `static/js/settings/notifications.js`, `home_assistant.js`, `streams.js`, `groups.js`, `backup.js`, `access.js` | per-section behaviour, moved out of inline `<script>` |
| `static/css/dashboard.css` | a new "Settings & shared UI" block (classes below) |

Page data that inline scripts got from Jinja now comes from markup. URLs go in
`data-*` attributes on the section root (`data-test-url`, `data-status-url`, …), and
lists go in `<script type="application/json" id="notification-channels-data">`. That
JSON keeps the same serializer output, so `"secret_set": true` is still in the page and
the secret is not.

### 6.2 Macros (`partials/settings/_macros.html`)

| Macro | Output / classes |
|---|---|
| `section_header(title, subtitle, add_label=None, add_attrs='')` + optional `caller()` for the Learn-more body | `<header class="settings-section-header">` with `h2.settings-section-title`, `p.settings-section-subtitle`, the **Add …** `button.btn-primary`, and `details.settings-learn-more > summary` "ⓘ Learn more" when a caller body is given |
| `flash_slot(target)` | the banners for this target when `flash_target == target` (§7.2) |
| `inline_warning(kind='warn'\|'bad', id=None)` + caller | `div.inline-warning.inline-warning--warn` for things that ask the operator to act |
| `status_dot(kind, label)` | `span.status-dot.status-dot--{ok,warn,bad,off,info}` (`aria-hidden="true"`) plus a visible state word, or `sr-only` text when the word is shown elsewhere |
| `card()` + caller | `div.settings-card` (surface background, 1 px border, `rounded-lg`) |
| `card_row(id=None, attrs='')` + caller | `div.settings-card-row`, a flex row with `.settings-card-main` (`.settings-card-title`, `.settings-card-summary`, `.settings-card-error`) and `.settings-card-actions` |
| `kebab(id, label)` + caller | `button.kebab[aria-haspopup=menu][aria-expanded][aria-controls]` "⋯" with `aria-label="More actions for <label>"`, then `div.kebab-menu[role=menu][hidden]` |
| `menu_item(label, attrs='', danger=False)` | `button.kebab-item[role=menuitem][tabindex=-1]` (`.kebab-item--danger`); attrs carry the existing data hooks |
| `menu_form_item(action, label, danger=False, confirm=None)` | a POST `<form>` (CSRF) whose submit is a menu item; `confirm` adds `data-confirm` |
| `menu_sep()` | `div.kebab-sep[role=separator]` |
| `modal(id, title, size='md', form_attrs=None)` + `caller(part)` with `part` = `'body'` / `'footer'` | `<dialog class="std-modal std-modal--{sm,md,lg}" aria-labelledby>`: `.std-modal-header` (title, ✕ close), `.std-modal-body` (with `flash_slot(id)` first), `.std-modal-footer`. With `form_attrs` the whole dialog content is one `<form>` |
| `modal_block(title, advanced=False, open=False)` + caller | `fieldset.std-modal-block > legend`; `advanced=True` renders `details.std-modal-advanced` (collapsed unless `open`) |
| `switch(name, checked, label, attrs='')` | `input[type=checkbox][role=switch].switch` + label |
| `settings_group(key, label, total, checked_count, collapsed=True)` + caller | the collapsible group with tri-state checkbox (§6.8) |
| `save_bar(discard='reset'\|url)` | `div.settings-savebar` (sticky; §6.9) |
| `empty_state(text, id=None)` | `p.settings-empty` |

### 6.3 Buttons, fields, cards (CSS)

- Buttons: `btn-primary` (main action), `btn-secondary` (Edit, Cancel, row actions),
  new **`btn-danger`** (destructive confirm), new **`btn-ghost`** (text-only, such as
  Discard). Size modifier **`btn-sm`** (`px-3 py-1 text-xs`). All are `rounded-lg`.
- Fields: `input-clean` everywhere, `select.input-clean`, `textarea.input-clean`.
  Labels are `label.settings-label` (`text-sm`, secondary colour, `mb-1`) and help is
  `.edit-helper` (exists). `[aria-invalid=true]` gets a red border.
- Cards: `.settings-card` = `background: var(--color-bg-surface); border: 1px solid
  var(--color-border); border-radius: .5rem`. **`bg-dashboard-info-box` is used by the
  Edit page but defined nowhere** (no Tailwind config, no CSS rule), so it renders with
  no background today. Phase 1 defines it as the same surface (see §14 Q2).
- Tables that stay (Configuration, Audit log, Preview, Per-host overrides) use
  `table.settings-table`: no outer border, muted header, row dividers in
  `--color-border`.

### 6.4 Status dot

`status-dot--ok` (`--color-status-ok`), `--warn` (`--color-status-warn`), `--bad`
(`--color-status-bad`), `--off` (`--color-status-muted`), `--info` (`--color-status-blue`),
8 px, round. The live notification status keeps `.notification-state[data-state]`.
CSS maps `[data-state=connected]` to ok, `connecting` to warn, `error` to bad and
`disabled|stopped` to off, so the existing 5 s poll recolours the dot without new JS.

### 6.5 ⋯ menu (keyboard accessible)

- Trigger `button.kebab` with `aria-haspopup="menu"`, `aria-expanded`,
  `aria-controls`. Enter, Space or ArrowDown opens the menu and focuses the first item;
  ArrowUp opens it and focuses the last.
- In the menu: ArrowUp/Down move (wrapping), Home/End jump, Enter/Space activate, and
  Esc closes and returns focus to the trigger. Tab closes the menu and lets focus move
  on. A click outside closes it. Only one menu is open at a time.
- Items are `button[role=menuitem]` or a form's submit button. They keep the existing
  data hooks (`data-notification-purge`, `data-channel-remove`, `.stream-dialog-open`, …),
  so the delegated `closest('[data-…]')` handlers keep working. Choosing an item closes
  the menu first.
- Position: right-aligned under the trigger, flipped above it when there is no room
  below, kept inside the viewport on phones.
- Code that found its output row with `btn.closest('tr')` now uses
  `btn.closest('[data-channel-id]')` or `[data-stream-row]`, because the button lives
  in a menu inside the card.

### 6.6 Modal (native `<dialog>`)

- `showModal()` makes the page inert and traps focus natively. On open, focus goes to
  the element with `autofocus`, else the first field. `ui.js` remembers the opener and
  gives it focus back on `close`.
- Esc fires `cancel`. When the dialog holds a `form[data-unsaved-guard]` that is dirty,
  `ui.js` calls `preventDefault()` and asks "Discard unsaved changes?" in the shared
  confirm dialog (§6.7). The ✕ button and **Cancel** do the same. A click on the
  backdrop closes only dialogs without a guarded form.
- **Unsaved-guard integration:** `unsaved_guard.js` gains `form._unsavedGuard.reset()`
  (take a new baseline, clear start-dirty, re-arm). Opening a modal for Add or Edit fills
  the fields, then calls `reset()`, so a freshly opened modal is clean and its Save is
  not highlighted. (Today, clicking Edit on a channel makes the form dirty at once.)
  When a modal is reopened after a validation error, it keeps `data-unsaved-start-dirty`.
  A discard refills the defaults and calls `reset()`, so `beforeunload` does not fire
  for a closed modal.
- Layout: `.std-modal` width is `min(40rem, 100vw - 2rem)` (`--lg` 56rem, `--sm` 28rem)
  and `max-height: calc(100dvh - 2rem)`. The body scrolls, and the header and footer
  stay put. `::backdrop` is `rgba(0,0,0,.6)`.
- `open_modal` on page load (§5.2) opens one dialog by id after the section is shown.

### 6.7 Confirm dialog

There is one shared `<dialog id="confirm-modal" class="std-modal std-modal--sm">` in
`settings.html`. `STDSettings.ui.confirm({title, body, confirmLabel, danger})` returns a
`Promise<boolean>`. Forms that used `onsubmit="return confirm(…)"` or
`onclick="return confirm(…)"` get `data-confirm="<text>"` (plus optional
`data-confirm-title` / `data-confirm-label` / `data-confirm-danger`). `ui.js` intercepts
the submit, asks, and calls `form.requestSubmit()` only on OK. The text stays in the
attribute, so tests that grep it still pass (for example "The current key stops working
immediately"). The purpose-built dialogs (channel purge / remove / orphans, stream
Disable…/Delete…) keep their own content and get the `std-modal` classes.

### 6.8 Collapsible group with tri-state checkbox

```
<section class="settings-group" data-group-key="docker" data-collapsed="true">
  <div class="settings-group-header">
    <input type="checkbox" class="settings-group-check" aria-label="Publish all Docker entries">
    <button type="button" class="settings-group-toggle" aria-expanded="false" aria-controls="grp-docker">
      <span class="chevron" aria-hidden="true"></span> Docker
      <span class="settings-group-count">12 of 40</span></button>
  </div>
  <div id="grp-docker" class="settings-group-body" hidden> …rows… </div>
</section>
```

- The disclosure is a real `<button>` with `aria-expanded`. It is not a `<summary>`,
  because a checkbox inside a summary toggles the details element and is announced
  badly. Collapsed rows stay in the form (`hidden` does not stop submission).
- The group checkbox is a native checkbox. `ui.js` sets `.checked` and `.indeterminate`
  from the rows the click would affect: the visible rows while a search is active, all
  rows otherwise. A native checkbox with `indeterminate` is announced as "mixed", so no
  `aria-checked` is needed. A click on a partial or empty group ticks all of those rows;
  a click on a full group clears them. Each changed row dispatches `change` so the
  guard sees it.
- The count text ("12 of 40") updates live.

### 6.9 Sticky save bar

`div.settings-savebar` sits at the end of a guarded form, with `position: sticky;
bottom: 0`: "Unsaved changes", **Discard** (`btn-ghost`), **Save** (`btn-primary`,
`data-unsaved-save`). CSS shows it only while the guard says the form is dirty:
`form[data-unsaved-dirty="false"] .settings-savebar { display: none }`. No new JS.
Discard is `<button type="reset">`. `ui.js` turns the form's `reset` event into a
`change` after one tick so the guard sees the baseline again.

## 7. Flash policy

### 7.1 Mapping (no new category)

| Flash category | Shown as | Where |
|---|---|---|
| `success`, `info`, `message` (Flask default) | **toast**, auto-dismiss after 5 s (paused on hover/focus), ✕ to close | `#toast-region`, bottom-right (bottom, full width on phones), `role="status"` `aria-live="polite"` |
| `danger`, `error` | **error banner**, persistent, dismissible | the flash target (§7.2), `role="alert"` |
| `warning` | **warning banner** (amber), persistent, dismissible | the flash target |
| not a flash: pending/stale streams, HA discovery off, API token missing, default credentials, stream apply error / rejection, channel last error | **inline warning** rendered by the section template | its section/card, unchanged by flashes |

**Decision: map categories in the template; do not add a `toast` category.** The ~60
`flash()` calls keep their meaning (outcome, not presentation). Tests read messages from
the session and never see categories. Presentation stays in one macro. Two cleanups ride
along:

- `routes_auth.py` uses `"error"` where the app uses `"danger"` (`set_user_password`,
  login). The template treats `error` as `danger`. Phase 4 also changes the
  `set_user_password` calls to `"danger"`, so `_drop_stale_success_flashes` (which keeps
  `warning` and `danger`) and the banner treat them the same.
- Several success messages start with an emoji ("✅ ", "🗑️ ", "🔁 "). The toast already
  has a status icon, so a `flash_text` Jinja filter (registered in `app.py`) strips one
  leading pictograph plus spaces. The messages themselves stay unchanged, because tests
  match substrings of them.

"Could not list server backup files" is flashed during the render. It becomes an inline
warning in Backup & restore (a template variable `backup_list_error`), because a flash
raised mid-render would land in whatever section is open.

### 7.2 Flash target

`_render_settings` computes `flash_target = open_modal or initial_section or 'page'`.
The template reads `get_flashed_messages(with_categories=true)` once (Flask caches the
list for the request). Toast categories go to the toast region. Banners go to:

- the `flash_slot(id)` at the top of the modal body when `flash_target` is a modal id
  (a validation error with the modal reopened);
- the `flash_slot(slug)` right under the section header otherwise (redirect with
  `?section=`);
- `flash_slot('page')` above all sections when no section is known.

Every redirect to Settings carries its section (phase 1 fixes the ten listed in §3.2),
so `page` is only a fallback.

### 7.3 Channel dialogs and fetch actions

The channel remove dialog calls the route as JSON, and the route flashes on success
before the dialog reloads to `?section=notifications`. That flash becomes a toast on
the reloaded page. Fetch-based results (test, purge, orphan scan, stream purge) keep
their inline `role="status"` result line in the card or dialog. They are not toasts,
because the result is part of what the operator is looking at and can include counts
worth reading.

### 7.4 Add and Edit pages

`flash_messages.html` stays included in the same place. Errors and warnings render as
the same `flash-alert` banner (restyled to the shared banner look). Success and info
render as toasts, consistent with Settings, although on these pages they are rare:
`_drop_stale_success_flashes` removes old successes on GET, and a successful Add or Edit
redirects to a dashboard view, which renders no flashes. **Banners keep `class="flash-alert …"`
as the first class** (tests count `class="flash-alert`). Toasts use `class="toast …"`.

## 8. Mobile

- Below `md` (768 px) the sidebar is replaced by a full-width
  `<select class="input-clean settings-nav-select" aria-label="Settings section">` with
  one `<optgroup>` per group. Its option text carries the badges ("Streams (2 new, 1
  stale)"). A select was chosen over a horizontal scroller because thirteen chips do not
  fit, the scroller hides the group labels, and a select gives the native picker.
- Card rows wrap: the title and summary come first, the actions move under them and
  align right, and ⋯ stays reachable. The summary truncates with an ellipsis (the full
  text is in `title`).
- Modals are full width minus 1 rem with a scrolling body. The footer stays at the
  bottom, and its buttons stack when narrow (Save last, so it is closest to the thumb).
- The toast region spans the bottom edge. The save bar is sticky at the bottom and full
  width.
- Tables that stay scroll horizontally inside their card (`overflow-x-auto`), as the
  audit log does today.

## 9. Per-section design

### 9.1 About (General)

- Header: "About", subtitle "Version, build and the update check." No Add.
- Inline warnings stay first, with their exact wording and ids: **API token not set**
  (bad) and **Default credentials in use** (`#credential-warning`, warn, dismissible per
  session as today).
- Card "Version" as a definition grid: Version, Channel, Commit (link), Build time,
  Latest release seen (with the amber **update available** link), Last checked, Last
  error. "Update check disabled" when off.
- Card "Update check": a switch "Check GitHub for new releases", "Every [n] hours",
  **Save** (`btn-primary btn-sm`). A bad interval → error banner in About (redirect
  `section=about`); saved → toast.

### 9.2 Configuration (General)

- Header: "Configuration", subtitle "Read-only. Set in `settings.yml` or environment
  variables, then restart." Learn more: the precedence rule (env over file over default).
- `table.settings-table`: Key (mono), Value (mono, `api_token` masked as today), Source
  pill (ENV green, YAML amber, Default muted).

### 9.3 Groups (Dashboard)

- Header: "Groups", subtitle "Categories entries are grouped by on the dashboard.",
  **Add group**.
- One card per group, ordered by priority then name (the same order as the query): icon
  name (mono, muted), name, "Priority 10 · 7 entries", **Edit**, ⋯ = **Delete** (only
  when the group has no active entries).
- Everything stays inside the single `#groups-form` (`save_groups` is all-or-nothing and
  checks that every group id is submitted). The modal is a staging editor: its inputs
  have **no `name`** and live in a `<dialog>` inside the form, so they never submit and
  the section still holds exactly one `<form`. **Apply** copies the values into the
  card's hidden `group-<id>-*` inputs (name before value, as today) and updates the card.
  **Add group** stages into `new-*` (one new group per save, as the route allows; once
  staged, the button reads "Edit new group").
- Delete marks the card "Will be deleted · Undo" (the existing toggle semantics, no
  confirm, because nothing happens until Save).
- The sticky save bar commits. A 400 re-render shows the staged values on the cards,
  the per-row errors on their cards, and opens the modal for the first row with an error
  (`open_modal='group-modal'`, `data-group-id` of that row).
- Column sorting (`sortTable`) is dropped: the cards are in priority order already.

### 9.4 Widgets (Dashboard)

- Header: "Widgets", subtitle "Widgets attached to entries. Configure them on an
  entry's edit page." No Add (widgets are created on Edit).
- A card per widget: name, the connected entry ("svc (host)" or "not attached"), "Last
  update 3 min ago", fields. ⋯ = **Copy API key** (the clipboard code moves from
  `copyToClipboard` to `ui.js`). The API URL shows in the summary, mono and truncated.
- Empty: "No widgets yet."

### 9.5 Docker (Sources): exposure interpreter

- Header: "Docker", subtitle "How exposure layers (Traefik, Dockflare, …) turn into
  internal and external URLs." Learn more: the existing paragraph (recompute on save;
  UI edits and explicit labels are never overwritten).
- Card "Layer directions": one row per layer (mono name) with a `select.input-clean`
  (neither / internal / external). Field names stay `layer:<L>`.
- "Per-host overrides": one collapsible `settings-group` per host (no checkbox; the
  header shows "2 overrides"), with rows `override:<host>:<L>` (use global / neither /
  internal / external).
- The form gets `data-unsaved-guard` and the sticky save bar labelled **Save &
  recompute URLs**. Saved → toast "Exposure settings saved. Recomputed URLs for N
  service(s)." Empty state as today.

### 9.6 Notifications (Integrations), in full

**Header.** Title "Notifications", subtitle "Brokers STD publishes entry state to.",
**Add channel**. Learn more: the availability topic `<base>/status` (`online` retained,
`offline` last will), the per-entry topics, and that **Send test** checks the settings
before saving.

**Cards** (`#notification-list`, one `div.settings-card-row[data-channel-id]` per channel):

```
● mqtt-main  MQTT · HA                                  [Edit] [⏽ Enabled] [⋯]
  mqtt.lan:1883 · std/…
● mqtt-lab   MQTT                                        [Edit] [⏽ Enabled] [⋯]
  10.0.0.9:8883 TLS · lab/…
  Error: Connection refused (10.0.0.9:8883)
```

- Status dot + `.notification-state[data-state]` word (connected / connecting / error /
  disabled / stopped), updated by the 5 s poll (now `#notification-list
  [data-channel-id]`).
- Title: name, a muted type tag "MQTT", and an "HA" tag when discovery is on.
- Summary (mono): `host:port` + "TLS" when on + ` · <base>/…`.
- `.notification-error`: shown **only while the state is `error`** (the poll toggles
  `hidden`).
- `.notification-purge-result` (`role=status`) under the summary for fetch results.
- **Edit** (`btn-secondary btn-sm`, `data-notification-edit`).
- **Enable/Disable switch.** When the channel is enabled, the switch carries
  `data-channel-remove="disable"` plus the existing `data-channel-*` attributes, so
  turning it off opens the existing Disable dialog (cleanup unchecked by default). If
  the dialog is cancelled, the switch flips back. When the channel is disabled, turning
  it on submits the toggle form (POST, redirect, toast).
- **⋯:** **Send test**, **Scan for orphans** (`data-notification-orphans`), **Purge
  MQTT and Home Assistant** (`data-notification-purge`), separator, **Delete**
  (danger, `data-channel-remove="delete"`).
  - Send test on a card posts the saved config to the existing
    `test_notification_channel_form` route with `channel_id` and a blank password (the
    route then uses the stored secret). No new route. The result goes to the card's
    result line.
- Empty: `#notification-empty` "No notification channels yet." with **Add channel**.

**Add/Edit channel modal** (`#channel-modal`, one form `#notification-form`,
`data-unsaved-guard`, posting to `save_notification_channel`; the field names and `#nf-*`
ids are unchanged):

| Block | Fields |
|---|---|
| **Connection** | Name · Enabled (switch) · Host · Port (placeholder "1883 (8883 with TLS)") · Use TLS · **Base topic** |
| **Authentication** | Username · Password (write-only: "Set; leave blank to keep" + "Remove the stored password", never echoed) |
| **Home Assistant** | Add to Home Assistant (switch) · Discovery prefix · Device name prefix (the two prefixes are dimmed while the switch is off, still submitted) |
| **Advanced** (collapsed `details`) | Client id · QoS · Keepalive (seconds) · Skip certificate verification (not recommended) |

- **Base topic sits in Connection.** The decision did not place it. It is a required,
  everyday setting shown on every card, so it is not "advanced".
- **Cleanup prompt** (`#nf-cleanup-row`, the existing logic): it appears at the end of
  the body as an amber inline warning while editing a saved channel whose base topic
  (or, with discovery on, a prefix) differs from the stored value. It is checked by
  default.
- **Footer:** result line (`#nf-test-result`, `role=status`) on the left, then
  **Cancel**, **Send test** (`#nf-test`, `btn-secondary`) and **Save channel**
  (`btn-primary`, `data-unsaved-save`). Send test uses the form values, so the operator
  can test before saving.
- **Errors:** `save_notification_channel` already re-renders (400, or 409 for a failed
  cleanup). It now passes `section='notifications'`, `open_modal='channel-modal'` and
  the typed values (as it does today via `notification_form`). The flashes render as an
  error banner inside the modal. Each `config.<field>` error also sets `aria-invalid` on
  its input, and when the field is in Advanced, that block opens.
- **Saved:** redirect `section=notifications`, toast "Notification channel 'x' saved."
- **Dialogs:** `#purge-dialog`, `#channel-remove-dialog` and `#orphan-dialog` keep
  their ids, content, fetch flows and wording, restyled with `std-modal` classes and
  `btn-danger` / `btn-secondary`.

### 9.7 Home Assistant (Integrations), in full

**Header.** Title "Home Assistant", subtitle "Choose which entries get a device in Home
Assistant." Learn more: discovery creates one device per entry (a roll-up state sensor
plus a problem sensor per check) under an STD hub device, new checks appear
automatically, and checks can be opted out on the entry's edit page; none are published
by default.

**Status line** under the header:

- "Discovery: **mqtt-main** (`homeassistant/`, devices "STD …")". This lists every
  channel with discovery on, and a disabled one is marked "(disabled)".
- "**14 of 52** entries published". This is the saved count of `ha_publish` among
  active entries.
- When **no enabled channel** has discovery on, it is an amber inline warning instead:
  "No channel publishes discovery, so nothing reaches Home Assistant. Turn on **Add to
  Home Assistant** on a channel in Notifications →" (link `#notifications`). Today's
  check is "any channel, enabled or not". Counting only enabled channels is the truthful
  version of the same warning (a disabled channel publishes nothing).

**Toolbar:** search `#ha-filter` ("Search by name, host or group"), **Select all** /
**Select none** (text buttons; act on matching rows, as today).

**Groups** (`#ha-entries-form`, `data-unsaved-guard`, posting to `save_ha_entries`,
unchanged route and field names):

- Order: **Docker**, **Manual**, then one group per stream by display name. Empty
  groups are omitted. The server builds `ha_groups = [{key, label, entries}]`, with
  key `docker`, `manual` or `stream:<stream_id>`.
- Header: tri-state checkbox, chevron + name, count "Docker — 12 of 40" (ticked of
  total, live). **Collapsed by default.**
- Rows `div.ha-row[data-ha-row][data-ha-source="<label>"]`: checkbox `ha_publish`, name,
  host (muted), group pill (muted). The hidden `ha_entry_ids` stays per row. Rows are
  sorted by name, then host.
- **Search** matches name, host and group (and the source label, which matches the
  whole group). Groups with matches expand while the search is active, groups without
  matches hide, and clearing the search restores the expand/collapse state from before.
- **Sticky save bar** while dirty: "Unsaved changes · Discard · **Save**". Saved →
  redirect `section=home-assistant`, toast "Home Assistant entries saved (3 changed)."
- Empty: "No entries yet."

### 9.8 Streams (Sources), with Blocked and Link offers

- Header: "Streams", subtitle "Inventory pushed by sidecars with an ingest key." No
  Add: streams appear when a sidecar posts. Learn more: pending → enable, the ingest key
  (link `#api-keys`), stale = 2 × interval, missing entries soft-delete rules (the
  paragraph from today's monitoring panel).
- **Inline warnings (stay):** one per pending stream, keeping the exact text "New
  stream waiting: enable **DHCP** to import\n    10 items." and
  `data-pending-stream`, with **Preview**, **Enable** and **Ignore** buttons inside the
  warning. One per stale stream (bad), with its `sh.message`.
- **Docker (register)** read-only card first: ok dot, "Docker (register)", summary
  "docker-api-notifier · `/api/v1/register` · 40 entries · last register 2 min ago",
  the tag "always on" and no actions. It keeps `id="stream-row-docker"`.
- **Stream cards** `div.settings-card-row[data-stream-row][data-stream-status]`
  (`id="stream-row-<slug>"`):
  - dot: pending warn, enabled ok, stale bad (with `stream-stale-badge` "stale"),
    disabled/ignored off;
  - title: display name + mono `stream_id`;
  - summary: "producer version · last snapshot 3 min ago · every 5 min (producer) · 42
    items · 40 active, 2 missing";
  - second line: last counts, or the muted `stream-would-counts` "would: …" for a
    non-enabled stream, or `stream-waiting` "Waiting for the next snapshot";
  - error lines only when present: "Apply error: …" (bad), `stream-rejection` (bad
    while rejecting, muted after);
  - actions: **Edit**; for a pending/disabled/ignored stream, **Enable** (and
    **Ignore**) are visible buttons too, because they are the action the card asks for.
    ⋯ = **Preview** (or nothing while waiting), **Enable**, **Ignore**, **Purge
    MQTT/HA** (`.stream-notify-purge`, when notifications are enabled), separator,
    **Disable…** (enabled only), **Delete…** (danger). Both open
    `#stream-dialog-<slug>` as today.
- **Edit stream modal** (`#stream-edit-<slug>`, one per stream, server-rendered), with
  three blocks. Each is its own `<form>` and **Save**, because the three routes stay as
  they are:
  1. **Name and networks** → `stream_update`;
  2. **Staleness and missing entries** (`id="stream-monitoring-<slug>"` moves to this
     block, "every 15 min (default)" stays in its subtitle) → `stream_monitoring`;
  3. **Default checks** (+ **Apply to existing entries**) → `stream_default_checks` /
     `_apply` (`id="stream-checks-<slug>"`).

  The value errors of these three routes re-render with
  `open_modal='stream-edit-<slug>'` and the typed values (`forms['stream:<slug>:<block>']`)
  instead of redirecting. A `StreamError` from the service layer does the same. Success
  redirects with a toast.
- **Preview** (`?section=streams&preview=<slug>`) renders inside a wide modal
  `#stream-preview-modal` opened by `open_modal`. The inner `id="stream-preview"`,
  `.preview-action[data-action]` and the "missing" list are unchanged. Closing it drops
  `preview` from the URL.
- **Blocked** (sub-header with count): compact rows "name · key (mono) · IP · stream ·
  blocked 3 days ago by admin" + **Unblock** (`btn-secondary btn-sm`). `#stream-blocks`
  / `#stream-blocks-empty` stay.
- **Link offers** (sub-header with count, amber dot on the nav when > 0): rows "stream
  item (name, key, IP) ↔ manual entry (link to Edit)" + **Accept** (`btn-primary btn-sm`)
  / **Decline** (`btn-secondary btn-sm`), visible because they ask for an answer.
  `#stream-offers` / `#stream-offers-empty` stay.
- **Disable…/Delete… dialog** is restyled. The ids, classes, radio values, notes,
  linked and customised boxes and all wording stay.
- The per-stream purge `confirm()` becomes the shared confirm dialog.

### 9.9 Users (Access)

- Header: "Users", subtitle "People who can sign in. Admins can open Settings.",
  **Add user**.
- Cards: username, an "Admin" tag, email, "Last login 2 h ago" / "Never". Actions:
  **Set password** (modal with a new password field; the only edit the routes support),
  ⋯ = **Delete** (non-admins only; confirm dialog).
- Add user modal: Username, Email, Password, Admin (switch). `auth.add_user` re-renders
  on "already exists" (400, `open_modal='user-modal'`, username and email kept, the
  password never echoed). `set_user_password` re-renders a too-short password with the
  set-password modal open. Success redirects `section=users` with a toast.
  `set_user_password` uses `danger` and redirects to `users` (it lands on Info today).

### 9.10 API keys (Access)

- Header: "API keys", subtitle "Keys for the management API, sidecars and agents.",
  **Create key**. Learn more: Bearer header; separate from the notifier's `api_token`;
  read / write / ingest meaning.
- Cards: name, scope tag (read / write / ingest), prefix (mono), dot ok "active" / off
  "revoked", summary "Created 2026-11-01 · rotated — · last used 3 min ago from
  10.0.0.5". ⋯ = **Rotate** (confirm with today's text) and **Revoke** (danger,
  confirm). Revoked keys come after the active ones, dimmed (`opacity-50`), with no menu.
- Create modal: Name, Scope (`select.input-clean` with
  `<option value="ingest">Ingest (sidecars)</option>` unchanged, plus a help line per
  scope). An error re-renders (400) with the modal open and the name kept.
- **Show-once key in a modal.** Create and Rotate render the Settings page itself
  (`section='api-keys'`, `open_modal='api-key-secret-modal'`) with the full key only
  in that modal: `input#new-api-key` (id before value), `#copy-api-key`, "Copy this key
  now. You won't see it again." The response headers stay as they are (`no-store`;
  rotate `no-store, no-cache` + `Pragma`). `nav.js` replaces the POST URL, so a reload
  shows plain Settings without the key. `api_key_created.html` is removed.

### 9.11 Audit log (Access)

- Header: "Audit log", subtitle "Writes made through the management API, newest first
  (the last 200)." Learn more: secrets masked, reads not logged, retention
  `api_audit_retention_days`.
- Filter: `select.input-clean` "All keys / …", GET with `section=audit-log`
  (`<option value="alpha" selected>` formatting unchanged).
- It stays a table (a log reads best as one): `table.settings-table#api-audit-table`,
  with status coloured, changes as mono lines, and `#api-audit-empty`.

### 9.12 Backup & restore (Data)

- Header: "Backup & restore", subtitle "YAML export of every entry, and restore from
  one."
- Card "Backup": **Download backup (YAML)** (`btn-primary`), **Save to server**
  (`btn-secondary`).
- Card "Restore": source as two radio cards (Server backups / Upload a file), the server
  select or the upload drop zone (the `toggleRestoreSource` logic moves to `backup.js`),
  scope select, **Restore** (`btn-primary`). `backup_list_error` shows as an inline
  warning (§7.1). Every error redirects to `section=backup`.

### 9.13 Deleted (Data)

- Header: "Deleted", subtitle with the retention ("Kept 30 days, then removed by the
  nightly purge (00:25)."; the `deleted_retention_days == 0` wording stays).
- Cards: name, host, "Deleted 2026-11-18 10:02 · purged in 28 days", **Restore**
  (`btn-secondary btn-sm`), ⋯ = **Delete permanently** (danger, confirm).
- "Detached widgets" sub-header with a one-line subtitle: cards with "Attach to…"
  `select.input-clean` + **Attach**, ⋯ = **Delete** (danger, confirm).

## 10. Accessibility basics

- Every field has a `<label for>` (or wraps its input). Modal blocks are
  `fieldset`/`legend`. Help text is linked with `aria-describedby`. Errors set
  `aria-invalid` and the banner is `role="alert"`.
- Nav: `<nav aria-label="Settings">`, with a visible heading per group (`h3`, not a
  link) and `aria-current="page"` on the active link. The mobile select has an
  `aria-label`.
- Status is never colour-only: every dot has a word next to it or `sr-only` text.
- Modals: native `<dialog>` + `showModal()` (focus is kept inside, the page is inert),
  `aria-labelledby` on the title, focus returns to the opener, Esc closes (with the
  unsaved check). Menus as in §6.5. The tri-state checkbox as in §6.8. Switches are
  `role="switch"` checkboxes with labels.
- Toasts: `role="status"`, `aria-live="polite"`. They pause on hover and focus, and with
  `prefers-reduced-motion` they do not animate. Errors are never toasts.
- Focus rings use the existing `--color-border-focus` / `--color-accent-dim`.

## 11. Testing approach

- **Keep green, every phase:** `pip install -r requirements-dev.txt && pytest -q` and
  `ruff check .`. The tests in §3.5 marked "keep" must pass unmodified. The ones marked
  for a phase are updated in that phase's commit, and the prompt says so.
- **New in phase 1** (`tests/test_settings_layout.py`):
  - the sidebar renders 6 group labels and 13 links in the §4 order (from
    `settings_sections.SECTIONS`); each `id="section-<slug>"` appears once; no element
    has `id="<bare slug>"`;
  - `settings_sections.resolve()`: slugs, legacy aliases (`info`→`about`,
    `exposure`→`docker`, `api`→`api-keys`), unknown → `None`;
  - `GET /settings?section=<x>` renders `data-initial-section="<resolved>"`;
    `?audit_key=…` alone → `audit-log`; `?preview=dhcp` → `streams`;
  - every Settings POST route redirects with a `section` that `resolve()` accepts
    (parametrised over the routes: backup/restore errors, update-check, exposure,
    groups failure path, API key revoke, deleted, streams, users, notifications);
  - flash placement: after a success redirect the page has a `class="toast` and no
    `class="flash-alert`; after an error redirect the banner sits inside that section's
    markup (slice between `id="section-<slug>"` and the next `<section`);
  - the Groups 400 re-render sets `data-initial-section="groups"`.
- **Phase 2:** the channel save error re-render has `data-open-modal="channel-modal"`
  and the banner inside `#channel-modal`; the HA groups (Docker, Manual, DHCP) render
  in that order with counts "N of M"; `data-ha-source="DHCP"` ×10; the amber warning
  appears when only a disabled channel has discovery on; `save_ha_entries` redirects to
  `section=home-assistant`.
- **Phase 3:** preview → `data-open-modal="stream-preview-modal"`; a bad monitoring
  value re-renders 400 with `open_modal="stream-edit-<slug>"` and the typed value; the
  pending warning has the Enable/Ignore/Preview buttons; the Docker card count.
- **Phase 4:** create/rotate key render `data-open-modal="api-key-secret-modal"` and
  keep the headers; a reload (plain GET) has no key; add-user duplicate → 400 with the
  modal open and no password in the HTML; `set_user_password` redirects to `users`; the
  groups modal adds no `<form`.
- **No JS test runner** exists. The JS is checked in the browser by the operator (each
  prompt ends with a short manual checklist). Markup hooks that the JS needs are
  asserted from pytest where cheap.

## 12. Risks

| Risk | Mitigation |
|---|---|
| One huge template split into 13 files breaks a test that slices by section order | §3.5 lists them. Phase 1 changes no section's content beyond styling, and it updates `test_groups_save.py:202` to slice to the next `<section`. |
| Moving inline JS into static files loses Jinja values (URLs, channel JSON) | Data attributes and JSON script tags (§6.1). Keep the `"secret_set"` JSON shape. |
| `replaceState` on a POST re-render surprises the operator | The guard still warns before leaving with typed input. The URL shown is the section they are on. |
| The show-once key now lives in the Settings page | Same headers (`no-store`), the key is only in the modal, and the page after a reload has none. The test for "key not in page" stays. |
| Re-rendering instead of redirecting on stream/user/key validation errors changes status codes (302 → 400) | Only for validation errors. Tests that read `_flashes()` after such a POST are listed for update (`test_streams_ui.py:207`). Success paths still redirect. |
| Groups: staging in a modal hides the "one table" overview | Cards show every staged value, and the save bar names unsaved changes. The route is unchanged. |
| `bg-dashboard-info-box` gets a real style and changes the Edit page | Intended look. It is open question Q2 and easy to scope to `.settings-card` only. |
| Browser support for `<dialog>` / `:has` | `<dialog>` has been in every evergreen browser since 2022. Use no `:has()`. |
| Tailwind CDN (`cdn.tailwindcss.com`, unpinned in `base.html`) | Unchanged in this work. New classes live in `dashboard.css`, not in Tailwind utilities that might not exist. |

## 13. Phase plan

Each phase leaves the app fully working with tests green, as one commit, `feat:` (each
has operator-visible changes). Each adds its `[Unreleased]` CHANGELOG lines. Phase 1
adds the planned PRD section and phase 4 marks it delivered.

| Phase | Prompt | Scope |
|---|---|---|
| 1 | `prompts/2026-11-20-set-01-foundation.md` | `settings_sections.py`; split into section partials; grouped sidebar, mobile select, hash deep links, `?section` aliases, `initial_section`/`open_modal`/`flash_target` plumbing in `_render_settings`; redirect fixes (§3.2); HA entries moved to its own section, Audit log to its own, Info split into About/Configuration (content as is); macros, `ui.js` (modal, menu, confirm, `data-confirm`, groups, reset bridge), `nav.js`, `flash.js`; toast + banner + flash policy (`flash_text`, `flash_messages.html`); `unsaved_guard.reset()`; restyle every section to the shared visual language (buttons, inputs, cards, light tables, section headers with subtitle + Learn more) **without** changing any section's layout pattern; existing dialogs get `std-modal`; all `confirm()` → shared confirm; `.bg-dashboard-info-box` + new CSS block; PRD planned section + revision row; CHANGELOG; README wording (Info→About, API→API keys/Audit log, Exposure→Docker). |
| 2 | `prompts/2026-11-20-set-02-notifications-ha.md` | Notifications cards + switch + ⋯ + channel modal (blocks, Advanced, Send test in footer, cleanup prompt, errors in modal, field `aria-invalid`); `notifications.js`; Home Assistant section in full (status line, groups, tri-state, search, sticky save bar); `home_assistant.js`; tests updated/added; CHANGELOG, PRD §17 UI notes, README Notifications/HA paragraphs. |
| 3 | `prompts/2026-11-20-set-03-streams.md` | Streams cards, Docker card, pending/stale inline warnings with actions, ⋯, Edit stream modal (three blocks, re-render on error), Preview modal, Blocked/Link offers lists, restyled dialog; `streams.js`; tests; CHANGELOG, PRD §18.8 notes, README streams walkthrough. |
| 4 | `prompts/2026-11-20-set-04-remaining.md` | About, Configuration, Groups (staging modal), Widgets, Docker, Users (modals, auth route fixes), API keys (modal, show-once modal, retire `api_key_created.html`), Audit log, Backup (inline list error), Deleted; tests; CHANGELOG; PRD section marked delivered + revision row; README. |

Phases 2–4 depend on phase 1. They are independent of each other but touch the same
`dashboard.css` block, `ui.js` and the test file, so **run them in order**, one commit
each.

## 14. Open questions

**Answered by the operator (2026-11-20):** Q1 — no separate 0.10.2; its fixes ship
inside 0.11.0. Q2 — yes, define `bg-dashboard-info-box` (the Edit page panels gain the
card background). Q3 — move the Docker (register) card to the top of the Docker
section; phase 3 leaves it in Streams, phase 4 moves it (and updates
`test_streams_ui.py`). The questions as asked are kept below for the record.

1. **Release order.** `[Unreleased]` already holds the 0.10.2 fixes (MQTT test
   budget, 128-character names). Should 0.10.2 be cut before phase 1 lands, or should
   those fixes ship inside 0.11.0? The prompts assume either works. Each phase only adds
   lines under `[Unreleased]`.
2. **`bg-dashboard-info-box`.** It is undefined, so the Edit page's panels (notify
   purge, health history, stream info / link) have no background today. Phase 1 defines
   it as the card surface, so those panels gain a background and border on the Edit page
   too. The alternative is to leave it undefined and style only `.settings-card`. The
   default in the prompt is to define it. Say no to keep Edit untouched.
3. **Docker (register) card placement.** Phase 3 keeps the read-only "Docker
   (register)" card at the top of Streams (today's row; tests expect it in
   `#section-streams`). Should it move to the Docker section's header instead?

Settled here and recorded in `docs/decisions.md`, not open: hash deep links +
`?section` for redirects; template-side flash mapping without a new category; Base
topic in the Connection block; HA warning counts enabled channels; the Groups modal
stages into the one form; the stream edit modal has three forms; the mobile select.

## 15. Later (not in 0.11.0)

- Toasts on the Dashboard / Tiled / Compact views ("Entry updated", "Logged in"). Today
  those flashes wait in the session and `_drop_stale_success_flashes` drops them.
- One combined "save stream" route so the Edit stream modal has a single Save.
- Editing a user's email or admin flag (no route exists).
- Renaming a stream from the card (already parked in `docs/FUTURE.md`).
- Search across all of Settings.
- A per-entry HA preview (which entities each device gets).
- A JS test runner for the settings modules.
