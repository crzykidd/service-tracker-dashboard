---
name: 2026-11-20-set-01-foundation
status: completed        # pending | completed | failed
created: 2026-11-20
model: sonnet
completed: 2026-11-20
result: Settings regrouped into 13 deep-linkable sections with the shared UI kit, flash policy and restyle; 1348 + 36 tests, ruff clean; manual browser checklist pending.
---

# Task: Settings modernization phase 1: structure, deep links, shared components, flash policy, restyle

Split the 1,416-line `templates/settings.html` into one partial per section. Regroup the
sidebar into the six labelled groups and give every section a deep link
(`/settings#<slug>`). Land the shared macros, JS and CSS that phases 2–4 build on, apply
the new flash policy (toasts and in-section banners), and restyle every section to the
Add/Edit visual language. **This is structure and styling only.** No section gets its
new list/modal layout yet (that is phases 2–4). Every form, route, field name and
behaviour keeps working.

## Before you start

- Read `CLAUDE.md` (Definition of Done, commit rules, module layout).
- Read the design doc **in full**: `docs/design/2026-11-20-settings-modernization.md`.
  This phase implements §4, §5, §6 (all components; the section layouts come later), §7,
  §8 (sidebar/select, toast, modal sizing), §10 and the phase-1 rows of §3.5 and §11. Open
  `docs/design/2026-11-20-settings-modernization-mockup.html` in a browser for the look.
- Read the newest `docs/decisions.md` entry ("Settings modernization design"). Its
  calls are final. Do not reopen them.
- Read the whole current UI: `templates/settings.html`, `templates/partials/settings_streams.html`,
  `templates/partials/flash_messages.html`, `templates/base.html`, `templates/add_entry.html`,
  `templates/edit_entry.html`, `templates/api_key_created.html`, `static/css/dashboard.css`,
  `static/js/unsaved_guard.js`. Read the settings routes in `routes_dashboard.py`
  (`settings`, `_render_settings`, every `flash(` and `redirect(` that targets Settings)
  and `routes_auth.py`.
- Design doc open question **Q2** (`bg-dashboard-info-box`): **answered yes** by the
  operator: define it (the Edit page panels gain the card background).

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
(the templates, `routes_dashboard.py`, `routes_auth.py`, `app.py`, `static/css/dashboard.css`,
`static/js/*`, the tests named below, `CHANGELOG.md`, `docs/PRD.md`, `README.md`,
`CLAUDE.md`, `docs/decisions.md`), list them and stop to ask. Unrelated dirty files:
mention them once. This file is exempt.

## What to do

1. **Section registry: `settings_sections.py`** (new, pure, no Flask import). It holds
   `GROUPS` / `SECTIONS` in the order of design §4 (slug, label, group), `DEFAULT =
   'about'`, `ALIASES = {'info': 'about', 'exposure': 'docker', 'api': 'api-keys'}`,
   and `resolve(raw) -> slug | None` (a slug or an alias resolves; anything else gives
   None).
2. **`_render_settings` plumbing** (`routes_dashboard.py`):
   - New signature `_render_settings(*, section=None, open_modal=None, forms=None,
     status=200, **extra)`. `forms` is a dict: `forms['group']` replaces `group_form`
     and `forms['notification']` replaces `notification_form`. Keep passing
     `group_form` / `notification_form` to the template under their current names for
     now, so the sections don't change. Update the two callers.
   - Compute `initial_section` (precedence in design §5.2), `open_modal` and
     `flash_target = open_modal or initial_section or 'page'`. Pass them, plus
     `settings_sections` data (groups and sections for the nav), to the template.
     Remove `force_section`.
   - A helper `_settings_redirect(section, **params)` returns
     `redirect(url_for('dashboard.settings', section=section, **params))`. Use it for
     **every** redirect to Settings, with the new slugs: `info`→`about`,
     `exposure`→`docker`, `api`→`api-keys` (the revoke/rotate/create failure paths),
     `save_ha_entries` → `home-assistant`. Fix the ten redirects that have no section
     (design §3.2): the seven backup/restore errors → `backup`, and in `routes_auth.py`
     `set_user_password` (all three) → `users`, using `url_for('dashboard.settings',
     section='users')`. Also update `api_key_created.html`'s back link (`api-keys`) and
     the channel remove dialog's reload URL. `base.html`'s header link may keep
     `section='streams'`.
   - The audit filter form posts `section=audit-log`.
3. **Template split.** `templates/settings.html` becomes the shell (design §6.1).
   Create `templates/partials/settings/_macros.html` and one partial per section under
   `templates/partials/settings/`: `about.html`, `configuration.html`, `groups.html`,
   `widgets.html`, `docker.html`, `streams.html` (move `partials/settings_streams.html`
   here with `git mv`, then edit), `notifications.html`, `home_assistant.html`,
   `users.html`, `api_keys.html`, `audit_log.html`, `backup.html`, `deleted.html`.
   - Each section is `<section id="section-<slug>" class="settings-section{% if not
     current %} hidden{% endif %}">`, where `current` means slug == `initial_section or
     'about'`. The server hides the others, and `nav.js` takes over.
   - **Content moves as is:** Info splits into About (warnings, version, update check)
     and Configuration (config table). The HA entries picker (heading, form, filter
     script) moves out of Notifications into Home Assistant. The Audit log (heading,
     filter, table) moves out of API into Audit log. Nothing else moves between sections.
   - No element may get an `id` equal to a bare slug (design §5.1).
4. **Sidebar + mobile select** built from the registry: `<nav class="settings-nav"
   aria-label="Settings">` with a group label (`h3.settings-nav-label`) and links
   `a.settings-nav-link[href="#slug"][data-section]`, `aria-current="page"` on the
   active one. Badges: Streams pending (amber) + stale (red) counts, Deleted count
   (muted). Below `md`, a `select.settings-nav-select` with an `<optgroup>` per group
   and the counts in the option text. The root element
   `#settings-root` carries `data-initial-section`, `data-open-modal`,
   `data-settings-url="{{ url_for('dashboard.settings') }}"` and
   `data-section-aliases` (JSON).
5. **JS** (no build step; plain scripts loaded with `static_v()`, `defer` or at the end
   of the body, attaching to `window.STDSettings`):
   - `static/js/settings/nav.js`: design §5.3 exactly (pick the section, show it, sync
     nav and select, `replaceState` canonicalisation, open `data-open-modal`,
     `hashchange`, select `change`). A `showSection(slug)` replacement stays exported
     for any old caller.
   - `static/js/settings/ui.js`: modal helpers (design §6.6: open with opener memory,
     focus return, guarded `cancel`/✕/Cancel, backdrop rule), ⋯ menu (§6.5, full
     keyboard), shared confirm dialog + `data-confirm` forms (§6.7), the collapsible
     group + tri-state helper (§6.8, written and unit-checked in the browser now, first
     used in phase 2), and the reset bridge (§6.9).
   - `static/js/flash.js` (loaded from `base.html`, `defer`): toast auto-dismiss (5 s,
     pause on hover/focus, ✕), banner dismiss, reduced motion.
   - Move the page-wide inline scripts into `static/js/settings/backup.js`
     (`toggleRestoreSource`, file name), `groups.js` (`sortTable`, delete toggle) and
     `access.js` (credential warning dismiss, `copyToClipboard`). The notifications
     script (`notification_channels|tojson`, url_for strings) and the streams scripts
     **move with their partials, unchanged** apart from selector fixes. Phases 2 and 3
     extract them.
   - `static/js/unsaved_guard.js`: add `form._unsavedGuard.reset()` (new baseline, clear
     start-dirty, re-arm, refresh) and document it in the header comment. Nothing else
     changes.
6. **Flash policy** (design §7):
   - `templates/partials/_flash.html` macros: `toast`, `banner`, and the category →
     kind mapping (`success|info|message` → toast; `danger|error` → error banner;
     `warning` → warning banner).
   - Settings: a toast region (`#toast-region`, `role=status`, `aria-live=polite`) in the
     shell. A `flash_slot(target)` macro goes under each section header (target = slug),
     at the top of every existing `<dialog>` body that a re-render can open (none yet;
     add the slot to the macro), and above the sections (target `page`). The template
     reads the messages once.
   - `partials/flash_messages.html` (Add/Edit): toasts to a toast region, banners in
     place. **Banners keep `class="flash-alert …"` with `flash-alert` first**; toasts
     use `class="toast …"`.
   - Register a `flash_text` Jinja filter in `app.py` that strips one leading
     pictograph (and a variation selector) plus spaces, and use it in toasts. Do not edit
     the flash message strings.
7. **Restyle every section** to the shared language without changing its pattern:
   `bg-gray-*` buttons → `btn-primary` / `btn-secondary` / new `btn-danger` / `btn-ghost`
   (+ `btn-sm`), `form-input` and ad-hoc inputs → `input-clean`, containers →
   `.settings-card`, bordered tables → `table.settings-table`. Each section gets the
   `section_header` macro with its one-line subtitle from design §9, and today's long
   paragraph goes into the "ⓘ Learn more" disclosure (same text). Existing
   `<dialog>`s get the `std-modal` classes (keep their ids and inner hooks). Every
   `onclick` / `onsubmit` `confirm(…)` becomes `data-confirm` with the **same text**,
   and the stream purge `confirm()` becomes `STDSettings.ui.confirm` with the same text.
   **Keep every id, class, data attribute, field name and visible string that §3.5 of
   the design marks "keep"**, including table markup that phase 4 will replace
   (`<th class="px-4 py-2">Rotated</th>`, `<td class="px-4 py-2">—</td>`, the
   `stream-row-docker` `<td class="px-3 py-2">1</td>`, the HA `<th class="py-2
   px-3">Source</th>` and `data-ha-source>…<`). Leave those cells' classes alone in
   this phase.
8. **CSS** (`static/css/dashboard.css`): one "Settings & shared UI" block with every
   class in design §6.2–§6.9 and §8 (nav, select, section header, learn more, card, card
   row, status dot + the `[data-state]` mapping, kebab, modal, modal block / advanced,
   confirm, toast, banner, inline warning, settings group, save bar, switch,
   `settings-table`, `btn-danger`, `btn-ghost`, `btn-sm`, `settings-label`,
   `settings-empty`, `sr-only` if missing). Define `.bg-dashboard-info-box` (unless Q2
   was answered no). Use the existing tokens. Add no new colours beyond Tailwind's
   red/amber shades used today.
9. **Tests**:
   - Update `tests/test_groups_save.py::test_form_wraps_every_input_in_one_form`: slice
     from `id="section-groups"` to the next `<section` (not to `id="section-users"`),
     because the order changed.
   - Add `tests/test_settings_layout.py` covering the phase-1 list in design §11 (nav
     order and groups from the registry, single section ids, no bare-slug ids,
     `resolve()`, `data-initial-section` for slugs, aliases, `audit_key`, `preview`,
     redirect sections for the listed POST routes, toast vs banner placement, groups 400
     → `groups`).
   - Everything else in design §3.5 must pass **unmodified**. Run
     `pip install -r requirements-dev.txt && pytest -q` and `ruff check .`. Both clean.
10. **Docs, same change:**
    - `docs/PRD.md`: add a new section **"19. v0.11.0 — Settings modernization
      (Planned)"** before "Versioning, Branches, and Releases". Renumber 19–21 to 20–22,
      fix the TOC, and grep `docs/`, `README.md`, `CLAUDE.md` and `prompts/` (not
      `prompts/done/`) for `§19`, `§20`, `§21` and fix live references. Content: the IA
      table, the deep-link scheme, the flash policy, the shared components list, the
      phase list with prompt names (phase 1 marked delivered on `dev`), and a link to the
      design doc. Add a revision row (next number after the last row, 0.81 → **0.82**).
      Update §3.1 module layout (new `settings_sections.py`, `templates/partials/settings/`,
      `static/js/settings/`, `static/js/flash.js`).
    - `CHANGELOG.md` `[Unreleased]` → **Changed**: Settings sidebar grouped (General,
      Dashboard, Sources, Integrations, Access, Data), each section has its own link
      (`/settings#streams`) and saves/reloads return to it; Info is now About +
      Configuration; Exposure is now Docker; API keys and Audit log, and Home Assistant
      are their own sections; success messages show as a toast that fades, errors stay
      in the section until dismissed; confirm prompts use the app's dialog; restyled
      to match Add/Edit. **Fixed**: setting a user's password returned to Info and
      showed errors as green success bars; restore errors returned to Info. Operator
      language, as in the existing entries.
    - `README.md`: rename Settings references (Settings → Info → **About**, Settings →
      API → **API keys** / **Audit log**, Exposure → **Docker**, Home Assistant entries
      → **Settings → Home Assistant**). Update the `/settings` route row
      (`?section=` still works; `#<section>` deep links). Keep it short.
    - `CLAUDE.md` Module Layout: add `settings_sections.py`,
      `templates/partials/settings/`, `static/js/settings/`. (List this file in the
      report, so the orchestrator surfaces it in the commit y/n.)
11. **Manual check list** for the report (the operator runs it in a browser): every
    sidebar link and the mobile select; reload stays on the section; a save in each
    section returns to it with a toast; an error stays as a banner in that section;
    `?section=info|exposure|api` lands on About / Docker / API keys; ⋯ / confirm / dialogs
    keyboard-usable; the unsaved prompt still fires on Groups and the channel form.

## Conventions to honor

- No change to the management API, MCP, schemas, wire contracts, `API_REVISION` or the
  database. No new routes. Route paths stay.
- Don't build phase 2–4 layouts (channel cards/modal, HA groups, stream cards, users/keys
  modals). Don't invent features (design §15 is "Later").
- Commit style: `feat:` (operator-visible). No `Co-authored-by:` unless the user asks.
  The doc updates are in the same commit.
- Record any non-obvious call you make in `docs/decisions.md` (newest at top, under a
  "set-01" heading).

## When done

1. Update this file's frontmatter: `status` (completed/failed), `completed` (date),
   `result` (one line).
2. Move this file into `prompts/done/` (success) or `prompts/failed/` (failure). If
   `git ls-files --error-unmatch prompts/2026-11-20-set-01-foundation.md` succeeds (the
   file is tracked), use `git mv`. Otherwise use plain `mv`.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.**
   Report back: the file list (including this prompt's new path), the proposed commit
   message `feat: settings regrouped with deep links, toasts and the shared UI kit
   (settings modernization phase 1)`, the test result, and the manual check list.
