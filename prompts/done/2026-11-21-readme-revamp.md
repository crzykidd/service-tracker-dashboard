---
name: 2026-11-21-readme-revamp
status: completed        # pending | completed | failed
created: 2026-11-21
model: opus
completed: 2026-11-21
result: README rewritten top-down (pitch, short What's New, audited config reference); deep reference moved to three docs/ pages
---

# Task: Full evaluation and rewrite of README.md

The README (about 1,700 lines) grew by accretion, one release at a time. It needs:

- a clean, concise pitch for what STD actually is now: an infrastructure-defining dashboard;
- a short What's New section;
- a configuration reference checked against the code.

The operator is capturing new screenshots in parallel.

## Before you start

- Read `CLAUDE.md`, `docs/PRD.md` (skim it; use it as a reference), `CHANGELOG.md` (the whole file, including `[Unreleased]`, which is 0.11.0 on `dev`), and the current `README.md`.
- 0.11.0 is not released yet, but the README describes what is on `dev`. That includes:
  - the Settings modernization (sidebar groups and sections);
  - scheduled backups and exports;
  - import with preview;
  - staged restore;
  - API revision 4.
- **Trust the code over the docs.** Where the README, PRD and code disagree, the code and CHANGELOG win. Flag any PRD contradiction you find in your report; don't propagate it.

## Working tree check

Before editing, run `git status --porcelain`. If `README.md` or any other file you plan to touch has uncommitted changes, stop and report. This prompt file is exempt.

## What to do

1. **Evaluate first.** Audit every README section against the code:
   - routes;
   - settings keys and env vars (`settings_loader.py`, `backups.py`, `settings.example.yml`, `.env.example`, `docker-compose.yml`, `Dockerfile`, `entrypoint.sh`);
   - the register payload (`schemas.py`);
   - the management API (`mgmt_openapi.py`);
   - the MCP server (`mcp/`);
   - notifications and Home Assistant;
   - streams;
   - health checks;
   - widgets;
   - Settings section names and paths (`settings_sections.py`).

   List what is stale, wrong, missing or duplicated. Include that list in your report.
2. **Rewrite the intro and "What It Does".** Keep it clean and concise. The framing: STD is a self-populating infrastructure dashboard. It builds itself from sources and is the operator's single view of what runs on their network:
   - **Docker:** docker-api-notifier registers containers automatically (labels, networks, ports, exposure → synthesized URLs).
   - **Inventory streams:** sidecars push full snapshots, e.g. DHCP leases from Technitium via `std-source-technitium`, so devices appear on their own. The pending → enabled lifecycle, link offers to existing entries.
   - **Manual entries:** for anything else.
   - Then: grouping and sorting across dashboard views (main, tiled, compact, mobile); full health checking (http/tcp/ping/dns, rollups, history); widgets; MQTT / Home Assistant publishing; a management API and MCP for automation and Claude; backup, export and import.

   Aim for a short paragraph plus a tight feature list, not a wall of text. A small source-flow diagram (ASCII or mermaid) is fine if it earns its place.
3. **What's New:** one compact block per version, newest first. Each block has the version, the date and 2–4 key-feature bullets (one line each), and links to the full entry in `CHANGELOG.md`. Use anchors on GitHub's CHANGELOG rendering if they are reliable, otherwise just link `CHANGELOG.md`. Cover 0.11.0 as "unreleased / on dev" (release-prep will finalize the heading) and the recent releases. Drop the long-form per-version prose; the CHANGELOG is the record.
4. **Configuration:** a complete, current reference. Cover every `settings.yml` key and every env var actually read by the code, with defaults and the env > UI > settings.yml precedence where it applies (backups, for example). Include the env-pinned (read-only in UI) behavior. Check the example `settings.yml` and the compose example still work as written.
5. **Restructure the rest for an operator reading top-down:**
   - quick start / compose;
   - configuration;
   - sources (notifier register, streams, manual);
   - dashboards and health;
   - notifications and HA;
   - management API and MCP;
   - backup, export, import and restore;
   - development and releases.

   Move deep reference material where it fits (e.g. the full register payload and exposure rules can stay but sit lower, or move to a `docs/` page with a link, your call; record the call in `docs/decisions.md`). Remove duplication. Fix the table of contents.
6. **Screenshots:**
   - Keep the Screenshots section, with image references to `docs/screenshots/` using the existing filenames (`std_main_dashboard.png`, `std_tile_dashboard.png`, `std_compact_dashboard.png`, `std_mobile.png`, `std_settings.png`, `std_widgets.png`).
   - The operator will replace the images. Where a new image would help (e.g. streams, import preview, HA section), add a reference with a clear proposed filename and an HTML comment `<!-- screenshot needed: ... -->`.
   - List all needed shots in your report.
7. Keep version strings bare in prose, except git tags and release names (`v` prefix only there; see CLAUDE.md release rules). Don't touch `VERSION` or the CHANGELOG version headings.
8. Docs only: no code changes. If a doc fix needs a code change (e.g. a setting documented but not read), report it; don't make it.

## Conventions to honor

- Plain, direct operator language; no marketing fluff. Short sentences, tables for reference data.
- This is docs-only. Record it in `docs/decisions.md` (newest at top), not in the CHANGELOG. Confirm "PRD reviewed": change the PRD only if you find it wrong about something the README now states, and if so bump its revision table.
- Check every internal README link and anchor still resolves after the restructure.

## When done

1. Update this file's frontmatter: set `status` (completed or failed), `completed` (the date) and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on failure).
3. Record non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent, so do **not** commit. Report back with:
   - the files changed and a proposed one-line `docs:` commit message;
   - the audit list (stale, wrong or missing items fixed);
   - any code/doc contradictions needing a code change;
   - the list of screenshots needed.
