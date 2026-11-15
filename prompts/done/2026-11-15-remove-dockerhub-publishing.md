---
name: 2026-11-15-remove-dockerhub-publishing
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15   # filled when the work is done
result: Removed Docker Hub publish steps, REGISTRY_NOTICE arg, and banner (HTML/JS/CSS); docs updated; lint, config, YAML, docker build and /login checks pass
---

# Task: Remove Docker Hub publishing and the "moved to GHCR" banner

v0.6.7 was the planned final Docker Hub release (see `docs/decisions.md`, entry
"Docker Hub → GHCR via a banner-only final Docker Hub release", and
`docs/HISTORY.md` "Registry move"). This task removes Docker Hub from CI and
removes the banner code, which only existed for the Docker Hub image. GHCR is the
only registry from here on.

## Before you start

- Read `CLAUDE.md` (especially "Release Process", which says what to remove after
  v0.6.7), `docs/decisions.md`, the "Registry move" section in `docs/HISTORY.md`,
  the CHANGELOG `[0.6.7]` section, and `.github/workflows/publish.yml`.
- You are on `dev`. Don't switch branches and don't push.

### What exists (added in v0.6.7, commit 7b01f9d)

- `.github/workflows/publish.yml`:
  - "Log in to Docker Hub" step (uses `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`)
  - "Compute tags (Docker Hub)" step (`meta_dockerhub`)
  - "Build and push (Docker Hub, deprecated — shows move banner)" step with
    `REGISTRY_NOTICE=dockerhub`
  - the header comment block describing the v0.6.7 transition

  Keep everything else, in particular the job name `build` (a required check),
  the `Verify release tag matches VERSION` step, GHCR login/meta/build, and the
  gha cache. Since the GHCR build no longer shares cache with a second build,
  check whether `cache-to`/`cache-from` still make sense. Keep them; they speed up
  rebuilds.
- `Dockerfile`: `ARG REGISTRY_NOTICE=` plus its comment, and the
  `registry_notice=` line in the `/app/version.txt` RUN.
- `templates/base.html`: the `{% if version_info.registry_notice == 'dockerhub' %}`
  banner block.
- `templates/settings.html`: the matching "Image source" `<li>` block.
- `static/js/dashboard.js`: `initRegistryNotice()` and its call in the bootstrap.
- `static/css/dashboard.css`: the `/* ── Docker Hub deprecation banner (v0.6.7) */`
  block (`.registry-notice*`).

Use `grep -rn -i "registry_notice\|registry-notice\|registryNotice\|dockerhub\|docker hub"`
to find everything, including docs.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. It's
expected to be modified by "When done" below.

## What to do

1. Remove every item listed above. Leave no dead references (`version_info`
   just won't have `registry_notice` anymore, which is fine).
2. **README:** **keep the "Moving from Docker Hub" section and its anchor
   `#moving-from-docker-hub`**. The v0.6.7 Docker Hub banner links to it forever,
   because Docker Hub users stay frozen on that image. Reword it to past tense:
   Docker Hub images are no longer published, the last one is v0.6.7, and here's
   the one-line switch. Update "Versioning & Releases" so it says Docker Hub is
   no longer published. Remove nothing else.
3. **CLAUDE.md:** in "Release Process", replace the transition bullet ("Through
   v0.6.7 the workflow also pushes a Docker Hub image… After v0.6.7, remove…") with
   a plain statement that images publish to GHCR only and Docker Hub stopped at
   v0.6.7. Don't touch the pasted standards snippets.
4. **PRD §11:** drop the dual-publish/`REGISTRY_NOTICE` description and state GHCR
   only (Docker Hub frozen at v0.6.7). Add a revision-history row: next number
   after the current last row, appended at the **bottom** (rows are ascending).
5. **HISTORY.md:** append a short "Follow-up" paragraph to the existing "Registry
   move" section (don't create a new section) noting that Docker Hub publishing
   and the banner were removed in the release after v0.6.7.
6. **CHANGELOG `[Unreleased]`:** add a `### Removed` entry in operator language:
   Docker Hub images are no longer published. Anyone still pulling
   `crzykidd/service-tracker-dashboard` from Docker Hub stays on v0.6.7 and should
   switch to `ghcr.io/crzykidd/service-tracker-dashboard` (link to the README
   section). Keep the existing entries.
7. **`standards.md`:** the `code-checkin-and-pr` row's notes mention retention on
   GHCR only with Docker Hub frozen. Update the wording if it implies Docker Hub
   is still published. Don't change the pinned version.
8. **Validate locally:**
   - The grep from "What exists" returns only intentional historical mentions:
     CHANGELOG `[0.6.7]`, HISTORY, decisions, the README migration section, and
     the PRD revision rows. List them.
   - `uvx ruff@0.15.17 check .`
   - Run the config-validation script from `ci.yml`, the same way
     `.claude/commands/release-prep.md` Step 6 does.
   - Parse `publish.yml` with PyYAML.
   - `docker build` the image, then confirm `/app/version.txt` has no
     `registry_notice` line and `version=0.6.7`
     (`docker run --rm --entrypoint cat <img> /app/version.txt`).
   - Run the container (`-e API_TOKEN=x`, a temp dir mounted at `/config`, a spare
     host port) and confirm `/login` returns 200 and the HTML contains no
     `registry-notice`.
   - Remove the container and image afterward.

## Conventions to honor

- Commit prefix `chore:`. It removes deprecated distribution, not a feature, and
  operator impact is covered by the CHANGELOG entry. No `Co-authored-by` trailer.
- Stage only specific paths; never `git add -A`.
- Don't touch retention, ci.yml, the release commands, or the VERSION wiring.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git add` this file, then `git mv` it into `prompts/done/` (or `prompts/failed/`).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top). Only
   add one if you made a real judgment call.
4. Hand off ONE commit covering this prompt file, the modified files, and the prompt
   move. Present the file list and a one-line message.
   - **If you are a spawned agent:** do **not** commit. Prepare the tree and report
     back. Also list the **manual follow-ups for the user**: delete the
     `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` repo secrets, and optionally update
     the Docker Hub repo description to point at GHCR.
   - **If you are running directly (manual fallback):** ask
     `commit these as "<message>"? (y/n)` yourself.
   Either way: never `git add -A`, never push, never auto-commit. Branch `dev`,
   `chore:` prefix, no `Co-authored-by:`.
