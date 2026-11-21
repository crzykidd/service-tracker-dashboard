---
name: 2026-11-21-image-repo-link
status: completed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: image repo link, override column, API revision 5, tests, docs done; uncommitted
---

# Task: link the container name to its image repo (GitHub issue #6)

Entry details show the full image (`registry/owner/name:tag`, shipped in v0.11.0).
Make the container name (and/or the image string) a link to the image's repository page,
derived from the image fields, with an optional operator override.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Database Rules, Register Contract Rules) and
  `standards.md`.
- Read PRD §13.7 (entry facts) and the export field-ownership table (PRD §20.2).
- Look at `templates/partials/entry_facts.html` (~line 59: the image line), `models.py`
  (`image_registry`, `image_owner`, `image_name`, `image_tag`), `routes_api.py`
  (`resolve_image_metadata` usage ~line 290/346), `mgmt_schemas.py`,
  `mgmt_serializers.py`, `export_format.py`, `entry_rules.py`, the `/add` and `/edit`
  forms in `routes_dashboard.py` and their templates.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. Another agent
may be writing a design doc under `docs/design/` in parallel; that is not yours, leave it.

## What to do

1. **Derivation helper** (pure function, e.g. `image_repo_url(registry, owner, name)` in
   `view_helpers.py` or a small new module; unit-test it):
   - Docker Hub (registry empty, `docker.io`, `index.docker.io`, `registry-1.docker.io`):
     official images (owner empty or `library`) → `https://hub.docker.com/_/<name>`;
     otherwise `https://hub.docker.com/r/<owner>/<name>`.
   - `ghcr.io` → `https://github.com/<owner>/<name>/pkgs/container/<name>` is NOT reliable
     (repo name ≠ package name); use `https://github.com/users/<owner>/packages/container/package/<name>`
     — verify which form GitHub redirects correctly for orgs too and note it in decisions.md.
   - `quay.io` → `https://quay.io/repository/<owner>/<name>`.
   - `lscr.io` (owner `linuxserver`) → `https://github.com/linuxserver/docker-<name>`.
   - `gcr.io`, `mcr.microsoft.com`, `registry.gitlab.com`, others: add only where the URL
     form is well known; unknown registry → no link (return None). Never guess for
     private/self-hosted registries.
   - Name containing `/` (nested paths) must not break; owner/name values must be
     URL-quoted.
2. **Override column**: add `image_repo_url` (nullable, String 512) to `services` via an
   Alembic migration (no FK, no index needed). Editable on `/add` and `/edit` (an
   "Image repo URL" field, optional, validated as http(s) URL in `entry_rules.py`),
   settable through the management API entry create/update schema
   (`mgmt_schemas.py`, `extra=forbid` stays), serialized in `mgmt_serializers.py`, and
   included in export/import per the ownership table (operator-owned field). It is NOT a
   register field — do not touch `schemas.py`; the register never writes it.
   Any additive management API change bumps `API_REVISION` in `api_version.py` + a PRD
   §18.1 row; update `mgmt_openapi.py` if the schema list needs it (tests enforce).
3. **Display**: effective URL = override if set, else derived. In
   `partials/entry_facts.html` (used by the Dashboard row and the Compact dialog) make the
   image string a link (`target="_blank" rel="noopener noreferrer"`). Also link the
   container name where it's displayed in the details if that reads naturally — keep it
   consistent across Dashboard / Compact / Tiled drawer. No link when neither exists.
4. **Tests**: derivation cases (each registry, official image, unknown registry, missing
   owner/name, quoting), override precedence, the form validation, management API
   round-trip, export/import round-trip, the template renders the link. Run lint
   (`uvx ruff@0.15.17 check .`) and the full suite
   (`uvx --with-requirements requirements-dev.txt pytest -q`); both must pass.

## Conventions to honor

- CHANGELOG `[Unreleased]` → Added: the link + override field (closes #6).
- PRD: entry facts §13.7, schema section, export ownership table §20.2, API revision
  table §18.1; bump the PRD revision-history table.
- README: mention it where entry details / editing are described if relevant.
- Commit prefix `feat:`; no `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top).
4. You are a spawned agent: do **not** commit. Prepare the working tree, then report the
   exact file list + proposed one-line message (e.g.
   `feat: link the container image to its registry page, with an override (closes #6)`)
   back to the orchestrating session. Never `git add -A`, never push.
