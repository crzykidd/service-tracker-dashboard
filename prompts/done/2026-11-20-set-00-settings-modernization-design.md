---
name: 2026-11-20-set-00-settings-modernization-design
status: completed        # pending | completed | failed
created: 2026-11-20
model: opus
completed: 2026-11-20
result: Design doc, static mockup, decisions entry and four sonnet build prompts (set-01 foundation, set-02 notifications+HA, set-03 streams, set-04 remaining) written; no application code changed.
---

# Task: design the Settings modernization for 0.11.0 (design doc + mockup + build prompts)

The Settings page doesn't match the rest of the app. Produce the design the operator will
approve before any code is written, plus the implementation handoff prompts that will
build it. **No application code changes in this task.**

## Operator decisions already made (do not re-open)

- Regroup the sidebar into labelled groups, one deep-linkable section each
  (`/settings#<section>`; reload and post-save redirects return to the section):
  - **General:** About (version, update check), Configuration (read-only) — today's Info tab.
  - **Dashboard:** Groups, Widgets.
  - **Sources:** Docker (today's Exposure interpreter), Streams (incl. Blocked, Link offers).
  - **Integrations:** Notifications, Home Assistant (its own section, out of Notifications).
  - **Access:** Users, API keys, Audit log (its own section).
  - **Data:** Backup & restore, Deleted (incl. detached widgets).
- **Banners:** success flashes become an auto-dismissing toast; errors stay as a
  persistent, dismissible banner *in the section/modal where they happened*
  (validation errors reopen the modal with input kept); warnings that ask the operator
  to act (pending/stale streams, HA discovery off) stay inline. The long explanatory
  paragraph at the top of each section shrinks to a one-line subtitle; detail goes behind
  an "ⓘ / Learn more" disclosure.
- **List + Add + modal pattern** everywhere it fits: header (title, one-line subtitle,
  **Add …** button) → list of cards (name, status dot, short summary, Edit, a **⋯** menu).
  Add and Edit share one modal. Applies to notification channels, users, API keys
  (show-once key shown in the modal), groups, stream actions. Destructive actions
  (Delete, Purge, Disable-with-cleanup) live in ⋯ and keep their confirm dialogs,
  restyled to the shared modal.
- **Notifications:** channel cards with status dot, `host:port · base/…`, last error
  only when in error, Edit, Enable/Disable switch; ⋯ = Send test, Scan for orphans,
  Purge MQTT and HA, Delete. Modal blocks: Connection (name, host, port, TLS) ·
  Authentication (username, write-only password) · Home Assistant (discovery on/off,
  discovery prefix, device prefix) · **Advanced**, collapsed (client id, QoS, keepalive,
  skip cert verification). Footer: **Send test** beside Save (test before saving). The
  base-topic cleanup prompt appears inside the modal when the base topic changes.
- **Home Assistant section:** header shows which channel(s) publish discovery and
  "N of M entries published" (amber line linking to Notifications if none). Entries are
  **grouped by source** (Docker, Manual, one group per stream) in collapsible groups,
  **collapsed by default**; each header has name, count ("Docker — 12 of 40") and a
  tri-state group checkbox. Search expands groups with matches. A sticky Save bar
  appears only while there are unsaved changes.
- Visual language: use what Add/Edit already use (`btn-primary`, `btn-secondary`,
  `input-clean`, `bg-dashboard-info-box` cards, `rounded-lg`, the CSS variables in
  `static/css/dashboard.css`), not the old `bg-gray-700` buttons / `form-input` /
  bordered tables.

## Before you start

- Read `CLAUDE.md`, `docs/PRD.md` (sections that describe Settings: search "Settings →",
  §14 API tab, §17 notifications UI, §18.8 streams UI, §12.5 deleted), the newest
  `docs/decisions.md` entries, and `docs/design/2026-11-17-network-inventory-and-profiles.md`
  for the house style of a design doc.
- Read the whole current UI: `templates/settings.html`, `templates/partials/settings_streams.html`,
  `templates/partials/flash_messages.html`, `templates/base.html`, `templates/edit_entry.html`,
  `templates/add_entry.html`, `static/css/dashboard.css`, the JS in `static/js/` that settings
  uses (unsaved-changes guard, notifications, streams), and the settings routes in
  `routes_dashboard.py` (every `flash(...)`, every redirect to settings and how it picks the
  section today, `notification_form` re-render on error).
- Inventory existing behavior that must survive: every form, dialog, data-attribute hook,
  JS behavior and test that targets Settings markup (`grep -rn "settings" tests/`). The
  build prompts must name what tests rely on so agents don't silently break them.

## Working tree check

Run `git status --porcelain`. This task only adds files under `docs/design/` and
`prompts/` and edits `docs/decisions.md`; if any of those have uncommitted changes, stop
and report. This file is exempt.

## What to do

1. **Design doc** `docs/design/2026-11-20-settings-modernization.md`:
   - Goals / non-goals (no behavior or API changes beyond what's listed; the
     management API and MCP are untouched).
   - Current-state inventory (sections, forms, dialogs, routes, flash sites, JS hooks,
     tests depending on markup).
   - Target information architecture (the grouping above), deep-link scheme, how the
     server tells the page which section/modal to open after a POST redirect or a
     validation error (e.g. a `section` + `open_modal` template var or URL hash —
     pick one and justify).
   - Shared components as Jinja macros / partials + small JS modules: section header,
     card list, status dot, ⋯ menu (keyboard accessible), modal (native `<dialog>`
     preferred, focus handling, Esc, unsaved guard integration), toast, error banner,
     collapsible group with tri-state checkbox, sticky save bar. Specify class names
     and file locations (e.g. `templates/partials/settings/_macros.html`,
     `templates/partials/settings/<section>.html`, `static/js/settings/*.js`).
   - Per-section design for all sections (Notifications and HA in full detail; the rest
     can be shorter), including which flashes become toasts, which stay errors.
   - Flash policy: map every current `flash()` category to toast / error banner /
     inline warning; propose whether to add a new category (e.g. `toast`) or map
     `success`/`info` → toast in the template. Flashes on Add/Edit pages share the
     partial: state what happens there (keep consistent with the app).
   - Mobile behaviour (sidebar collapses to a select or horizontal scroller).
   - Accessibility basics (labels, focus traps in modals, aria for tri-state, menus).
   - Testing approach (which pytest assertions change, new ones for section deep-links
     and modal-reopen-on-error).
   - Risks and an explicit phase plan (below).
2. **Mockup** `docs/design/2026-11-20-settings-modernization-mockup.html`: one
   self-contained static HTML file (inline CSS mirroring the app's dark palette /
   CSS variables, no external assets beyond optional Tailwind CDN with an exact pinned
   version) showing: the grouped sidebar; the Notifications list with two channel
   cards (one connected, one in error) and an open ⋯ menu; the Add/Edit channel modal
   with Advanced collapsed; the Home Assistant section with three source groups (one
   expanded, tri-state partial checkbox), search box and the sticky save bar; a toast
   and an error banner. Fake data only; minimal JS just to toggle states is fine.
3. **Build prompts** (status `pending`, model `sonnet`, from `prompts/TEMPLATE.md`), one
   per phase, each self-contained (what to read, exact scope, tests to keep green,
   CHANGELOG/PRD/README duties, "When done" with plain `mv` for the untracked prompt and
   report-back-don't-commit since they are spawned agents):
   - `2026-11-20-set-01-foundation.md` — split `settings.html` into per-section partials,
     grouped sidebar + deep links + section restore after redirects, shared macros/JS,
     toast + error banner + flash policy, restyle to the shared visual language.
     Structure only otherwise; no section gets its new layout yet beyond styling.
   - `2026-11-20-set-02-notifications-ha.md` — Notifications list/modal, HA section.
   - `2026-11-20-set-03-streams.md` — Streams, Blocked, Link offers in the new pattern.
   - `2026-11-20-set-04-remaining.md` — About/Configuration, Groups, Widgets, Docker
     (exposure), Users, API keys, Audit log, Backup, Deleted.
   Each phase leaves the app fully working and tests green; one commit per phase
   (`feat:` or `refactor:` as appropriate). The PRD gets a new planned section for
   0.11.0 Settings in phase 1 (with a revision row) and is marked delivered by the
   last phase; each phase updates the CHANGELOG `[Unreleased]` with operator-visible
   changes.
4. `docs/decisions.md`: a newest-first entry recording the operator's decisions above
   and any non-obvious design calls you made (e.g. deep-link mechanism, flash mapping).
5. Note in the design doc any open questions you could not settle; keep them few and
   concrete.

## Conventions to honor

- Docs-only task: no CHANGELOG entry (CLAUDE.md, Always 1); no PRD edit in this task
  (the PRD section is added by phase 1 when work starts).
- Don't invent features beyond the decisions above; park extras in the design doc's
  "Later" list.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (untracked: plain `mv`).
3. You are a spawned agent: do **not** commit. Report back: file list, proposed message
   (`docs: settings modernization design, mockup and build prompts`), a short summary of
   the design (IA, components, deep-link and flash decisions), the open questions, and
   the path of the mockup. Never `git add -A`, never push.
