# Service Tracker Dashboard Project History

This file documents structural events in the project's history — things
that don't fit neatly in a changelog entry but are worth knowing about.

For the feature-level changelog, see [CHANGELOG.md](../CHANGELOG.md).

---

## Documentation baseline (v0.5.0 cycle)

Through v0.4.14, the project shipped with a single `README.md` and no
PRD or HISTORY file. As part of the v0.5.0 cleanup work, this document,
[`PRD.md`](./PRD.md), and a project-level [`CLAUDE.md`](../CLAUDE.md)
were added.

### Why

`app.py` had grown to ~1,775 lines and the register endpoint had
accumulated silent key-remapping logic that no document described. The
PRD captures the current state, the planned v0.5.0 changes, and the
v0.6.0 sunset of legacy keys. CLAUDE.md captures workflow conventions
that had been informal up to that point.

### What changed

- `docs/PRD.md` added — current state, planned v0.5.0 / v0.6.0
  changes, scope.
- `docs/HISTORY.md` (this file) added.
- `CLAUDE.md` added at repo root.
- `CHANGELOG.md` reformatted to Keep a Changelog conventions; existing
  v0.1.x through v0.4.x tags listed as stub entries (detailed notes
  for pre-v0.5.0 versions are not retained).

### Impact on existing installs

None. Documentation only.

---

## Stray git tag cleanup (v0.5.0 cycle)

A typo'd tag `v.0.4.6` (extra dot before the major version) existed in
the repo alongside the correctly-named `v0.4.6`. Both tags pointed at
the same commit. The typo'd tag was deleted (locally and from the
remote) as part of v0.5.0 housekeeping.

This had no effect on Docker Hub images or release artifacts — the
typo'd tag was never used by any release workflow.

---

## Register contract canonicalization (v0.5.0)

v0.5.0 is the first release that defines a canonical wire contract for
the register endpoint. Prior to v0.5.0, `/api/register` accepted a
mix of key variants (`docker_host` ↔ `host`, `group_name` ↔ `group`,
`internal.health` ↔ `internal_health_check_enabled`, etc.) and
silently remapped them server-side.

### Why

The remapping was undocumented and made the register contract a
moving target. Every change to label naming on the notifier side
required matching tolerance in STD's remapping logic, and there was
no single document explaining what shape `/api/register` actually
expected.

### What changed

- New endpoint `/api/v1/register` accepts only canonical keys,
  validated by pydantic schemas.
- Existing `/api/register` becomes a compat shim: maps legacy keys to
  canonical, then delegates to the v1 handler. Emits a deprecation
  warning per request and adds `Deprecation` + `Sunset` response
  headers.
- The canonical contract is documented in `README.md` and `PRD.md`.

### Sunset plan

`/api/register` and all legacy key support are removed in v0.6.0.
Operators must upgrade `docker-api-notifier` to v0.3.0+ before that
release.

---

## App factory split (v0.5.0)

v0.5.0 splits the monolithic `app.py` (~1,775 lines as of v0.4.14)
into focused modules while preserving observable behavior. See
PRD §3.1 for the target layout.

### Why

The single-file structure made the project hard to navigate and
review. Models, ~20 routes, 3 background jobs, template filters, and
init code were all in one file. Splitting along surface-area
boundaries (api routes vs dashboard routes vs auth routes vs jobs)
makes each file reviewable on its own and gives new functionality a
natural place to land.

### What changed

- `app.py` becomes a Flask app factory (`create_app()`).
- `models.py`, `schemas.py`, `routes_*.py`, `jobs.py`, `health.py`
  added as peers of `app.py`.
- `extensions.py` (already present) holds extension singletons.

### Impact on existing installs

None. The split is internal; no routes, schemas, or behavior change
as a result of the refactor itself. (The other v0.5.0 changes — the
canonical contract, retention, indexes — are listed separately in
the changelog and PRD.)

---

## Frontend asset consolidation (v0.6.1, completed in v0.6.3)

Through v0.5.0 every dashboard template carried its own inline
`<style>` and `<script>` blocks. There was no shared CSS, and the
three dashboard views (`/`, `/tiled_dash`, `/compact_dash`)
re-defined overlapping component styling and behavior independently.

### Why

The Tiled redesign in v0.6.1 introduced a shared icon vocabulary and
component classes (`.tile`, `.tile-drawer`, `.status-icon`,
`.status-pill`, etc.) that all three dashboards needed to render
consistently. Keeping the new components inline per-template would
have multiplied the divergence the redesign was trying to eliminate.

### What changed

- `static/css/dashboard.css` introduced as the single stylesheet for
  the dashboard surface. Design tokens (CSS custom properties) and
  shared component classes live here.
- `static/js/dashboard.js` introduced as the single behavior file.
  Auto-refresh, drawer open/close, view-control submit-on-change,
  tile click, filter input, group collapse, tools popover, delete
  confirmation, clipboard helpers.
- View detection via `<body data-view="...">` so the shared JS can
  branch per-view without duplicating handlers.
- Tabler Icons v3.34.0 loaded via cdnjs CDN. Tailwind CDN retained
  for layout utilities. No frontend build step introduced.
- Two inline-style blocks survived v0.6.1 (in `edit_entry.html` and
  `settings.html`) and were removed in v0.6.3 along with a stray
  `toggleGroupMode` scoping bug. v0.6.5 universal delete and v0.6.6
  brand exposure icons / drawer modes layer on top of this same CSS
  / JS pair.

### Impact on existing installs

None on the wire side. Visual output changed substantially (this is
the Tiled redesign release); operators see new tile layout and icon
vocabulary on first reload.

---

## Registry move: Docker Hub → GHCR (v0.6.7)

### Why

Docker Hub registry retention (pruning old `:sha-*` and semver tags)
needs a Docker Hub token with delete rights and a custom cleanup job;
GHCR retention runs on the built-in `GITHUB_TOKEN`, and every other
crzynet project already publishes to GHCR.

### What changed

- `.github/workflows/dockerhub.yml` renamed to `publish.yml`; it pushes
  to `ghcr.io/crzykidd/service-tracker-dashboard`.
- v0.6.7 is a transition release published to **both** registries. The
  Docker Hub image is built with `REGISTRY_NOTICE=dockerhub`, which
  renders an in-app banner pointing operators at the README's "Moving
  from Docker Hub" section. The GHCR build has no banner.

### Impact on existing installs

Docker Hub users keep working but are frozen at v0.6.7 (with the
banner) until they switch the image line to GHCR. No data, config, or
volume changes are involved. GHCR has no images older than v0.6.7.

### Follow-up

Docker Hub publishing and the banner were removed in the release after
v0.6.7: the Docker Hub steps and `REGISTRY_NOTICE` build arg left
`publish.yml` and the Dockerfile, and the banner code left the templates,
JS, and CSS. The README's "Moving from Docker Hub" section stays, since
the frozen v0.6.7 Docker Hub image links to it.

---

## vexp removal (post-v0.6.7)

### Why

The repo had been wired for the vexp context engine (an MCP graph-RAG
search tool): a `PreToolUse` hook that blocked Claude Code's Grep/Glob
tools while the vexp daemon ran, plus vexp-generated agent instructions
telling agents not to search the codebase directly. vexp was retired
homelab-wide (the `vexp-context-engine` standard is sunset at v3.0.0)
because its provisioning and per-session overhead outweighed its benefit.

### What changed

- Removed `.claude/hooks/vexp-guard.sh`, the hook entry and
  `mcp__vexp__*` permissions in `.claude/settings.json`, the
  vexp-generated `.claude/CLAUDE.md` and `.github/copilot-instructions.md`,
  and the `.vexp/` line in `.gitignore`.
- Added `standards.md` at the repo root recording the de-adoption, and a
  pointer to it from `CLAUDE.md`.

### Impact on existing installs

None. Developer tooling only — no change to the app or images.

---

## Test suite added (v0.6.9 cycle)

STD had no automated tests, so the `Test` check from `code-checkin-and-pr`
was exempt. A pytest suite now lives in `tests/` (register auth, the
`extra="forbid"` contract, `exposure_observations` absent vs `[]`, URL
provenance, `register_field_ownership`, settings precedence), with a `Test`
job in `ci.yml`. To make the app testable, the hardcoded `/config/...` paths
now derive from a `STD_CONFIG_DIR` env var (default `/config`, behavior
unchanged when unset); it is documented only under README Development, not as
an operator setting. The operator must add `Test` as a required check in
branch protection (manual).

---

## Engineering standards adoption (v0.6.8)

### Why

Project process had grown informally (hand-written workflow notes in
`CLAUDE.md`, a Docker Hub-era release flow, and a vexp setup that was never
recorded as an adoption). The crzynet `homelab-configs` repo defines shared
standards; aligning with them makes check-in, release, and agent-handoff
behavior consistent across projects.

### What changed

- vexp de-adopted (see "vexp removal" above).
- Three standards adopted, each with a verbatim snippet in `CLAUDE.md`:
  `handoff-prompt-workflow` 2.0.0, `code-checkin-and-pr` 1.2.0, and
  `release-prep-and-cut` 1.1.0. Pins live in [`standards.md`](../standards.md).
- `VERSION` file added as the single source of the in-app version, with a
  tag==`VERSION` guard in `publish.yml`.
- v0.6.8 was the first release cut through `/release-prep` and
  `/release-cut`; it also removed Docker Hub publishing.
- Judgment calls are logged in [`decisions.md`](./decisions.md).

### Impact on existing installs

Operators see only that `:dev` / `:latest` images now report the real version
and that Docker Hub is no longer published. Everything else is developer
process.

---

## Docs loose ends (v0.6.9 cycle)

CHANGELOG historical dates corrected from git tags (the 0.1.x-0.4.x
`2026-XX-XX` placeholders were 2025 dates); MIT `LICENSE` added (the README
badge and link already pointed at one); README compatibility banner and
registry wording refreshed.
