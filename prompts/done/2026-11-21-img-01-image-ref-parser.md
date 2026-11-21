---
name: 2026-11-21-img-01-image-ref-parser
status: completed         # pending | completed | failed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: image_ref.py parser, image_ref column + backfill migration a2c6e8f1b345, register/API/display/link use it; full suite and ruff green
---

# Task: img-01, a correct image reference parser plus the `image_ref` column

This is phase 1 of the image update check (`docs/design/2026-11-21-image-update-check.md`,
§3.2, §6.2 and §9 item 1). It replaces the naive image-string split with a parser that
follows the distribution reference grammar. It also keeps the canonical reference string
on each entry, and makes the issue #6 repo link use the same parser. It ships in 0.12.0.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Database Rules, Register Contract Rules) and
  `standards.md`.
- Read the design doc: all of it for context, and closely §3, §6.2, §9 and §14. The
  decisions in §14 are final.
- Look at the following code:
  - `image_utils.py` (`resolve_image_metadata`) and its callers in `routes_api.py`
    (around lines 290 and 346);
  - `image_repo.py` (the issue #6 link derivation, just shipped);
  - `models.py` (the `image_*` columns);
  - `templates/partials/entry_facts.html`;
  - `export_format.py` and `mgmt_serializers.py`;
  - the existing tests for these, `tests/test_image_repo.py` among them.

## Working tree check

Run `git status --porcelain` and cross-reference the files this plan touches. If any of
them have uncommitted changes, list them and ask before you touch them. Surface unrelated
dirty files once; they don't block. This prompt file is exempt.

## What to do

1. **`image_ref.py`**: a pure, stdlib-only `parse(ref) -> ImageRef | None`.
   - Follow the reference grammar:
     - The first path component is a registry when it contains `.` or `:`, or is
       `localhost`.
     - The default registry is `docker.io`. A one-component Docker Hub name gets the
       `library/` prefix.
     - `index.docker.io` and `registry-1.docker.io` normalize to `docker.io`.
     - The tag comes after the last `:` of the last path component. Default to `latest`
       when there is no tag and no digest.
     - `@sha256:...` is a digest.
     - Lowercase the registry host. Reject empty or garbage input by returning None, and
       never raise.
   - Return `registry`, `repository` (the full path, e.g. `org/team/app`), `tag` (None
     for a digest-only reference), `digest`, plus helpers: `owner` and `name` for the
     legacy columns, and a `canonical` string (`registry/repository:tag`, or `@digest`
     when there is no tag).
   - Write table-driven tests covering at least these cases from design §3.2:
     - `nginx`
     - `nginx:1.27`
     - `library/nginx`
     - `docker.io/nginx`
     - `index.docker.io/library/nginx:latest`
     - `lscr.io/linuxserver/sonarr:latest`
     - `ghcr.io/org/team/app:1.2`
     - `localhost:5000/app:1`
     - `registry.example.com:5000/a/b:tag`
     - `nginx@sha256:<64 hex>`
     - `nginx:1.27@sha256:<64 hex>`
     - `quay.io/app:1`
     - uppercase registry
     - whitespace, empty and None
2. **Use it in `resolve_image_metadata`**, so the existing four columns come out right:
   - `image_registry`, `image_owner`, `image_name` and `image_tag`.
   - For nested paths, decide how owner and name map (e.g. owner = everything before the
     last component, name = the last component) and record the choice in
     `docs/decisions.md`.
   - Keep the icon behavior unchanged.
   - Check what `image_registry` held before for Docker Hub images (NULL vs `docker.io`).
     If it changes, `image_repo.py` and the display must still work. Don't regress
     existing entries' display.
3. **`image_ref` column** on `service_entry`: nullable, String 512.
   - Add it through an Alembic migration, with no index unless design §6 asks for one.
   - The register writes it from the raw `image_name` on every register. It is pure
     observation, like the capture columns: not operator-editable, and NULL when absent.
   - Backfill in the migration from the split columns where they are sound. The next
     register fixes the rest.
   - Expose it read-only in the management API entry response and the OpenAPI schema.
     That's additive, so bump `API_REVISION` and add a PRD §18.1 row. Fold it into the
     revision-5 row if that is still marked unreleased ("next after 0.11.0").
   - Export: follow the field-ownership table (observed fields; check how the other
     `image_*` columns are treated and match them).
4. **Make `image_repo.py` use `image_ref.parse`** wherever that reads better. It should
   at least give correct links for nested GHCR paths. A registry with a port or a
   localhost registry still gets no derived link.
5. **Display**: `partials/entry_facts.html` should show the canonical reference when
   `image_ref` is set. Otherwise it falls back to the current join.
6. Run `uvx ruff@0.15.17 check .` and the full suite
   (`uvx --with-requirements requirements-dev.txt pytest -q`). Both must pass, and you
   must run the FULL suite at the end, not only the touched files. Update stale pins
   (`API_REVISION`, the Alembic head) where tests assert them.

## Conventions to honor

- **CHANGELOG `[Unreleased]` → Fixed:** entry details showed wrong or empty image fields
  for registries with a port, nested image paths and digest references. Keep it in
  operator language.
- **PRD:** the schema section, the register handling notes (that `image_ref` is
  observed), §18.1, the §3.1 module list (add `image_ref.py`), and bump the revision
  table. Docs and code disagreeing is a reason to flag the contradiction, not to copy it.
- **CLAUDE.md module layout:** add `image_ref.py`.
- **Register contract:** do not touch `schemas.py`, since this phase adds no wire field.
- **Commits:** prefix `fix:` (or `feat:` if you judge the column the main point). No
  `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It is untracked, so a plain
   `mv` is fine.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. You are a spawned agent, so do **not** commit. Report back:
   - the exact file list;
   - a proposed one-line message;
   - the full-suite and lint results;
   - any decisions.

   Never `git add -A`, never push.
