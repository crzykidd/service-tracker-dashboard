---
name: 2026-11-20-set-04-remaining
status: pending          # pending | completed | failed
created: 2026-11-20
model: sonnet
completed:
result:
---

# Task: Settings modernization phase 4: the remaining sections, and close out the PRD section

Bring About, Configuration, Groups, Widgets, Docker, Users, API keys, Audit log,
Backup & restore and Deleted to the final design. That means cards + ⋯ + modals where the
pattern fits, a staging modal for Groups, the show-once API key in a modal, and
re-render-with-modal on validation errors. Then mark the Settings modernization
delivered in the PRD.

## Before you start

- Phases 1–3 must be in the tree, committed or not (`settings_sections.py`,
  `templates/partials/settings/_macros.html`, `static/js/settings/{ui,nav,notifications,home_assistant,streams}.js`).
  If they are missing, stop and report.
- Read `CLAUDE.md`, the design doc `docs/design/2026-11-20-settings-modernization.md`
  (§3.4, §3.5, §6, §7, **§9.1–§9.5 and §9.9–§9.13 in full**, §10, §11 phase 4), the
  mockup, and the newest `docs/decisions.md` entries (design, set-01 … set-03).
- Read the partials `about.html`, `configuration.html`, `groups.html`, `widgets.html`,
  `docker.html`, `users.html`, `api_keys.html`, `audit_log.html`, `backup.html`,
  `deleted.html`, plus `_macros.html`, `ui.js`, `groups.js`, `backup.js`, `access.js`,
  `templates/api_key_created.html`. In `routes_dashboard.py` read `settings`
  (backup/restore), `_render_settings`, `save_update_check`, `save_exposure_settings`,
  `_parse_group_form`, `save_groups`, `create_api_key`, `rotate_api_key`,
  `revoke_api_key`, the deleted/detached-widget routes. Read all of `routes_auth.py`'s
  user routes. Read PRD §12.5–§12.6, §14.2, §14.6, §15.3–§15.4, §16.

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
from something other than phases 1–3 (those partials, `routes_dashboard.py`,
`routes_auth.py`, `templates/api_key_created.html`, `static/js/settings/*`,
`static/css/dashboard.css`, the tests below, `CHANGELOG.md`, `docs/PRD.md`, `README.md`,
`docs/decisions.md`), list them and ask. This file is exempt.

## What to do

1. **About** (§9.1): the inline warnings first. Keep "API token not set", "Default
   credentials in use" and `#credential-warning` with its session dismiss. Then a Version
   definition grid (keep "Latest release seen", "Last checked", "Update check
   disabled") and an Update check card (switch, interval, Save).
2. **Configuration** (§9.2): `table.settings-table` with Key, Value (`api_token`
   masked) and a Source pill (ENV / YAML / Default).
3. **Groups** (§9.3): cards in priority/name order (icon, name, "Priority p · N
   entries", Edit, ⋯ Delete only when there are no active entries). Everything stays in
   the single `#groups-form` (`data-unsaved-guard`, same action, same field names; the
   hidden `group-<id>-name|icon|priority|delete` inputs keep `name` **before** `value`).
   - The modal `#group-modal` is a `<dialog>` **inside** the form with **unnamed**
     inputs and no `<form>` element (the section must still contain exactly one
     `<form`). **Apply** writes into the card's hidden inputs and redraws the card;
     **Add group** stages into `new-name|icon|priority` (one at a time; the button then
     reads "Edit new group").
   - Delete toggles "Will be deleted · Undo" (the `[data-group-delete-toggle]`
     semantics).
   - The sticky save bar commits. On a 400 re-render, the cards show the staged values
     and per-row errors, and `open_modal='group-modal'` with `data-group-id` of the first
     errored row (`nav.js`/`groups.js` fill the modal from that row).
   - Drop `sortTable`.
4. **Widgets** (§9.4): cards (name, connected entry, last update, fields, mono URL);
   ⋯ = Copy API key (from a `data-` attribute or the hidden input; move `copyToClipboard`
   into `ui.js`). No Add.
5a. **Move the Docker (register) card** (operator answer to design Q3): the read-only
   "Docker (register)" card that phase 3 left at the top of Streams moves to the top of
   the Docker section (same content and `id="stream-row-docker"`); remove it from the
   Streams partial and update `tests/test_streams_ui.py` (it asserts the card inside
   `#section-streams`) to look for it in `#section-docker` instead. Record the
   operator decision in the CHANGELOG line for the Docker section if relevant.
5. **Docker** (§9.5): a Layer directions card, per-host overrides as collapsible groups
   (no checkbox), field names `layer:<L>` / `override:<host>:<L>` unchanged,
   `data-unsaved-guard` + a sticky save bar labelled **Save & recompute URLs**
   (disabled when no layers), Learn more with today's paragraph.
6. **Users** (§9.9): cards (username, Admin tag, email, last login), **Set password**
   (modal `#password-modal`, posting to `auth.set_user_password`), ⋯ Delete (non-admin,
   `data-confirm` with today's text), and **Add user** (modal `#user-modal` → `auth.add_user`).
   In `routes_auth.py`:
   - `add_user` on "already exists" re-renders Settings through a function you can
     import without a cycle (e.g. move the call behind a small
     `routes_dashboard.render_settings_for(...)` wrapper or import inside the function):
     400, `section='users'`, `open_modal='user-modal'`, username and email kept, the
     password never echoed.
   - `set_user_password` too short → re-render with `open_modal='password-modal'`
     (`data-user-id`). Its flashes use `danger` (not `error`), and it redirects to
     `section='users'` (phase 1 did the section; check).
   - Success paths still flash + redirect.
7. **API keys** (§9.10): cards (name, scope tag, prefix, dot active/revoked, summary
   created/rotated/last used). ⋯ = Rotate (`data-confirm` with **today's text**, which
   includes "The current key stops working immediately") and Revoke (danger, today's
   text). Revoked keys go after the active ones, with `opacity-50` and no menu. **Create
   key** modal `#api-key-modal` (name, scope select with
   `<option value="ingest">Ingest (sidecars)</option>` exactly, a help line per scope).
   - `create_api_key`: a validation error → 400 re-render, `open_modal='api-key-modal'`,
     name kept. Success → render Settings itself with `section='api-keys'`,
     `open_modal='api-key-secret-modal'` and the key only in that modal:
     `<input id="new-api-key" … value="…">` (id **before** value), `#copy-api-key`, the
     text "Copy this key now. You won't see it again." (+ the rotated note when
     rotating). Response headers stay as they are: create `Cache-Control: no-store`;
     rotate `no-store, no-cache` + `Pragma: no-cache`.
   - `rotate_api_key` does the same with `rotated=True`. The not-found/revoked path
     stays flash + redirect.
   - Delete `templates/api_key_created.html` (`git rm`) and make sure nothing
     references it.
8. **Audit log** (§9.11): header + Learn more, the filter `select.input-clean` (GET,
   `section=audit-log`, `<option value="alpha" selected>` formatting unchanged), and
   `table.settings-table#api-audit-table` / `#api-audit-empty`, with escaping as today.
9. **Backup & restore — OUT OF SCOPE for this phase.** The operator decided (2026-11-20)
   to redesign backup, export and import as a separate project
   (`docs/design/2026-11-20-backup-export-import.md`, prompts `bak-01` … `bak-04`), which
   rebuilds this section. Leave `templates/partials/settings/backup.html` exactly as
   phase 1 left it; don't create `backup.js`, and don't touch the backup/restore routes
   or their tests. Ignore every other mention of Backup in this prompt.
10. **Deleted** (§9.13): cards with Restore + ⋯ Delete permanently (`data-confirm`,
    today's text); a Detached widgets sub-list with the Attach select + button and ⋯
    Delete (today's text). Keep the retention wording.
11. **Tests:**
    - Keep unmodified: `test_groups_save.py` (all, incl. `value="77"`, `typed-new`,
      `data-unsaved-start-dirty`, the priority regex, one `id="groups-form"`, one
      `<form` in the section, the session flash texts), `test_streams_ui.py:52`,
      `test_mgmt_api_keys.py:293-297,308-317,547,585`, `test_mgmt_openapi.py:205-251`,
      `test_soft_delete.py:69,172`, `test_settings_loader.py:114,122`,
      `test_version_check.py:344,350`, `test_csrf.py`.
    - Update deliberately: `test_mgmt_api_keys.py:595` (the Rotated `<td>` regex) and
      `:605,608` (`<th class="px-4 py-2">Rotated</th>`, `<td class="px-4 py-2">—</td>`).
      Assert the card summary instead ("rotated —" / a date) and keep `:606-607` (rotate
      URL, confirm text).
    - Add: create/rotate render `data-open-modal="api-key-secret-modal"` with the
      headers unchanged, and a following GET has no key; a duplicate key name → 400 with
      `data-open-modal="api-key-modal"` and the name kept; add-user duplicate → 400 with
      `data-open-modal="user-modal"`, username kept, password absent;
      `set_user_password` short → 400 with `password-modal`, success → `Location` has
      `section=users`; the groups section still holds exactly one `<form` and the
      `#group-modal` inputs have no `name`; the Groups 400 re-render opens `group-modal`.
    - `pip install -r requirements-dev.txt && pytest -q` and `ruff check .` both clean.
12. **Docs, same change:**
    - `CHANGELOG.md` `[Unreleased]` → **Changed**: users, API keys, groups and deleted
      items as cards with ⋯ menus; add user, set password, create key and edit group in
      dialogs (a mistake keeps the dialog open with what you typed); a new or rotated API
      key is shown once in a dialog on the Settings page, and reloading doesn't create
      another; groups are edited in a dialog and saved together with the Save bar; Docker
      layer settings and per-host overrides with a Save bar; About, Configuration, Audit
      log, Backup & restore restyled. **Removed**: column sorting on the groups table
      (cards are in priority order).
    - `docs/PRD.md`: mark §19 **Delivered on `dev`** (all four phases), with an "As built"
      paragraph for deviations. Update the UI descriptions in §12.5–§12.6 (Deleted),
      §14.2 / §14.6 / §15.3 (API keys, show-once modal, audit log section), §15.4 (groups
      modal staging; the single form is unchanged) and §16 (About). Add a revision row.
    - `README.md`: the Users, API keys (create/rotate flow), Audit log, Groups,
      Backup and Deleted references.
    - `docs/FUTURE.md`: add the design doc's §15 "Later" items that aren't already
      parked, under one heading "Settings follow-ups (after 0.11.0)".
13. **Manual check list** for the report: each section's add/edit/delete; the show-once
    key and Copy, then a reload (no key, no resubmit); a Groups staged
    rename/add/delete + Save, discard, and a duplicate name (modal reopens); Docker save
    bar; restore from server and from upload; Deleted restore/purge/attach; keyboard on
    ⋯ and modals; mobile width.

## Conventions to honor

- No management API, MCP, schema or contract change. Route paths stay
  (`/settings/api-keys`, `/add_user`, `/settings/users/<id>/set_password`, …).
- Don't invent features: no email/admin editing for users, no restore confirm (design §15).
- Commit style: `feat:`. No `Co-authored-by:` unless the user asks. Docs in the same commit.
- Record non-obvious calls in `docs/decisions.md` under a "set-04" heading.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (or `prompts/failed/`): `git mv` if
   `git ls-files --error-unmatch prompts/2026-11-20-set-04-remaining.md` succeeds, plain
   `mv` otherwise.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.**
   Report back: the file list (including this prompt's new path and the removed
   `templates/api_key_created.html`), the proposed commit message `feat: users, API keys,
   groups and the remaining settings sections in the card and dialog pattern (settings
   modernization phase 4)`, the test result, and the manual check list.
