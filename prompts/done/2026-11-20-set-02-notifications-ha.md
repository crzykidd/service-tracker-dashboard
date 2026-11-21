---
name: 2026-11-20-set-02-notifications-ha
status: completed        # pending | completed | failed
created: 2026-11-20
model: sonnet
completed: 2026-11-20
result: Notification cards + channel dialog and grouped Home Assistant section built; tests and docs updated; not committed.
---

# Task: Settings modernization phase 2: Notifications cards + channel modal, Home Assistant section

Give Settings → Notifications the card list + ⋯ menu + Add/Edit channel modal, and
build the Home Assistant section (discovery status line, entries grouped by source,
tri-state group checkbox, search, sticky save bar). This uses the components phase 1
landed. Routes, field names and the JSON fetch flows stay as they are.

## Before you start

- Phase 1 (`prompts/done/2026-11-20-set-01-foundation.md`) must be in the tree,
  committed or not. Check that `settings_sections.py`, `templates/partials/settings/_macros.html`
  and `static/js/settings/ui.js` exist. If they don't, stop and report.
- Read `CLAUDE.md`, the design doc `docs/design/2026-11-20-settings-modernization.md`
  (§3.4, §3.5, §6, §7, **§9.6 and §9.7 in full**, §10, §11 phase 2), the mockup
  `docs/design/2026-11-20-settings-modernization-mockup.html` (this phase is exactly
  what it shows), and the newest `docs/decisions.md` entries (the design entry and
  set-01's).
- Read the current `templates/partials/settings/notifications.html`,
  `home_assistant.html`, `_macros.html`, `static/js/settings/ui.js`, `nav.js`,
  `static/js/unsaved_guard.js`, and in `routes_dashboard.py`: `_render_settings`,
  `_notification_form_data`, `save_notification_channel`, `save_ha_entries`,
  `_channel_action_result`, `toggle_/delete_/test_/purge_/scan_/clear_…`,
  `notification_status`. Also read `mgmt_serializers.notification_channel_out` (the
  JSON the page embeds) and PRD §17.2–§17.5.

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
that are not phase 1's own work (the two partials, `routes_dashboard.py`, the JS/CSS
files, the tests below, `CHANGELOG.md`, `docs/PRD.md`, `README.md`, `docs/decisions.md`),
list them and ask before touching them. This file is exempt.

## What to do

1. **Notifications cards** (design §9.6): `#notification-list` of
   `div.settings-card-row[data-channel-id]`: status dot + `.notification-state[data-state]`,
   name, "MQTT" and "HA" tags, mono summary `host:port[ TLS] · <base>/…`,
   `.notification-error` shown only while `state == 'error'`,
   `.notification-purge-result` (`role=status`), **Edit** (`data-notification-edit`),
   the Enable/Disable **switch** (enabled → `data-channel-remove="disable"` + the existing
   `data-channel-*` attributes; cancelling the dialog flips it back; disabled → submits
   the toggle form), ⋯ = Send test, Scan for orphans (`data-notification-orphans` +
   urls), **Purge MQTT and Home Assistant** (`data-notification-purge` + url; keep that
   exact label), separator, Delete (`data-channel-remove="delete"`). Keep
   `#notification-empty`. The header has **Add channel**, and Learn more holds today's
   paragraph.
2. **Card "Send test"** posts the saved channel's config (from the embedded JSON) with
   `channel_id` and a blank password to the existing `test_notification_channel_form`
   route (the stored secret is used), and shows the result in the card's result line.
   No new route.
3. **Channel modal** `#channel-modal` (shared `modal` macro, `size='md'`) wrapping the
   existing `#notification-form` (`data-unsaved-guard`, same action, same field names,
   same `#nf-*` ids): blocks **Connection** (name, enabled switch, host, port, TLS,
   **base topic**), **Authentication** (username, write-only password with
   "(set; leave blank to keep)" + "Remove the stored password"), **Home Assistant**
   (discovery switch, discovery prefix, device name prefix; the prefixes are dimmed but
   still submitted while it is off), **Advanced** collapsed (client id, QoS, keepalive,
   skip certificate verification). The cleanup prompt `#nf-cleanup-row` (same logic and
   wording) goes at the end of the body as an amber inline warning. Footer:
   `#nf-test-result` · Cancel · **Send test** (`#nf-test`) · **Save channel**
   (`data-unsaved-save`). Add and Edit both open it. `fill()` then calls
   `form._unsavedGuard.reset()` (a fresh modal is clean). Close/Esc asks before
   discarding a dirty form (ui.js).
4. **Errors reopen the modal.** `save_notification_channel` error path calls
   `_render_settings(section='notifications', open_modal='channel-modal',
   forms={'notification': form}, status=…)`. The flashes render as a banner inside the
   modal (`flash_slot('channel-modal')`). Map each error `field` (`name`, `config.host`,
   `config.port`, …, `cleanup`) to its input, set `aria-invalid="true"`, and open
   Advanced when the field is in it. The modal keeps `data-unsaved-start-dirty`, and the
   password is never echoed.
5. **Dialogs:** `#purge-dialog`, `#channel-remove-dialog` and `#orphan-dialog` keep
   their ids, wording and fetch flows. Change the result-row lookups from
   `btn.closest('tr')` to `btn.closest('[data-channel-id]')`, and update the 5 s status
   poll selector to `#notification-list [data-channel-id]`. The poll also toggles
   `.notification-error`'s `hidden`.
6. **Extract** the notifications script into `static/js/settings/notifications.js`.
   Data comes from `<script type="application/json" id="notification-channels-data">{{
   notification_channels|tojson }}</script>` (the same serializer output, so
   `"secret_set": true` stays and the secret never appears) and URLs from `data-*` on
   the section.
7. **Home Assistant section** (design §9.7, `home_assistant.html`):
   - Server: build `ha_groups` in `_render_settings`: Docker, Manual, then one per
     stream by display name, empty groups omitted, entries sorted by name then host.
     Also build `ha_channels` (channels with discovery on: name, prefix, device prefix,
     enabled), `ha_published` (count of active `ha_publish`), `ha_total`, and
     `ha_discovery_live = any(enabled and discovery on)`. Keep `ha_discovery_on` if
     anything else still reads it, else remove it.
   - Header + Learn more; status line ("Discovery: mqtt-main (`homeassistant/`, devices
     "STD …")", a disabled channel marked "(disabled)"; "**N of M** entries
     published"). When `not ha_discovery_live`, an amber inline warning with a link to
     `#notifications` (the wording in design §9.7). The Notifications nav link gets no
     badge; the Home Assistant link gets an amber dot when no live channel exists and at
     least one entry is ticked.
   - Toolbar: `#ha-filter` (placeholder "Search by name, host or group"), **Select all**
     / **Select none** (on matching rows).
   - `#ha-entries-form` (unchanged action, `data-unsaved-guard`): one `settings_group`
     per source, **collapsed by default**, tri-state checkbox (`aria-label="Publish all
     <label> entries"`) and a live count "<label> — N of M". Rows are
     `div.ha-row[data-ha-row][data-ha-source="<label>"]` with the hidden `ha_entry_ids`
     + checkbox `ha_publish` (`aria-label="Publish <name>"`), name, host, group pill.
   - Search behaviour as in design §9.7 (expand groups with matches, hide groups without,
     restore the expand state when cleared). Tri-state over visible rows while
     searching.
   - Sticky save bar (`save_bar` macro, reset-based Discard).
   - Extract its script to `static/js/settings/home_assistant.js` (use ui.js's group
     helper).
   - `save_ha_entries` keeps its path and logic. It redirects to `home-assistant`
     (phase 1 did this; check).
8. **Tests:**
   - Keep unmodified: `test_notify_cleanup.py:551-552` (`data-channel-remove="delete"`
     / `="disable"`, `data-notification-orphans`, `id="nf-cleanup-row"`), `:711` (409
     page has "Nothing was saved" and "Remove the old topics"), `test_notifications.py:627-628,646`,
     `test_purge.py:476`, `test_notify_cleanup.py:360-362`.
   - Update deliberately: `test_stream_followups.py:235-237` (the Source column is gone:
     assert the DHCP group renders with `data-ha-source="DHCP"` ×10, a Manual row, and
     the new placeholder); `test_ha_discovery.py:526` if the "Home Assistant entries"
     heading text changed (keep "Select all").
   - Add (in `tests/test_settings_layout.py` or a new `tests/test_settings_notifications_ui.py`):
     the channel save error re-render has `data-open-modal="channel-modal"`, the banner
     inside `#channel-modal`, `aria-invalid` on the port input for a bad port, and no
     secret; the HA groups in order Docker → Manual → DHCP with "N of M" counts; the
     amber warning when only a **disabled** channel has discovery on, and none when an
     enabled one does; `save_ha_entries` → `Location` has `section=home-assistant`.
   - `pip install -r requirements-dev.txt && pytest -q` and `ruff check .` both clean.
9. **Docs, same change:**
   - `CHANGELOG.md` `[Unreleased]` → **Changed**: notification channels as cards with a
     status dot, an Enable switch and a ⋯ menu (Send test, Scan for orphans, Purge,
     Delete); add/edit in a dialog with Advanced options folded away and **Send test**
     beside Save; errors keep the dialog open with what you typed. Settings → Home
     Assistant: entries grouped by source (Docker, Manual, each stream), collapsed, with
     a select-all checkbox per group, search that opens matching groups, the channels
     that publish discovery and "N of M published" on top, and a Save bar that appears
     only with unsaved changes. The "no channel publishes discovery" warning now ignores
     disabled channels.
   - `docs/PRD.md`: in the new §19 mark phase 2 delivered on `dev`. In §17.2 / §17.4 /
     §17.5 update the UI descriptions (cards, modal, HA section location and grouping,
     enabled-channel warning). Add a revision row.
   - `README.md`: the Notifications and Home Assistant paragraphs (where the picker
     lives, the card actions, Send test in the dialog).
10. **Manual check list** for the report: add, edit, test-before-save, the error keeps
    input, the cleanup prompt on a base-topic change, the switch to disable (dialog,
    cancel flips back), enable, every ⋯ item incl. keyboard, the live status dot on a
    broker stop/start, HA groups/tri-state/search/save bar/discard, mobile width.

## Conventions to honor

- No new routes, no API/MCP/schema change. Field names, ids and fetch payloads as listed.
- Don't touch Streams, Users, API keys, Groups or the other sections (phases 3–4).
- Commit style: `feat:`. No `Co-authored-by:` unless the user asks. Docs in the same commit.
- Record non-obvious calls in `docs/decisions.md` under a "set-02" heading, newest at top.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (or `prompts/failed/`): `git mv` if
   `git ls-files --error-unmatch prompts/2026-11-20-set-02-notifications-ha.md`
   succeeds, plain `mv` otherwise.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.**
   Report back: the file list (including this prompt's new path), the proposed commit
   message `feat: notification channels as cards with an add/edit dialog, and a grouped
   Home Assistant section (settings modernization phase 2)`, the test result, and the
   manual check list.
