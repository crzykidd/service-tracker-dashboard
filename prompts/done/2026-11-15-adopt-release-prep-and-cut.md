---
name: 2026-11-15-adopt-release-prep-and-cut
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15    # filled when the work is done
result: VERSION file + Dockerfile/publish.yml wiring, /release-prep and /release-cut commands, README/CLAUDE/PRD/standards/CHANGELOG synced; local checks and image build pass
---

# Task: Adopt `release-prep-and-cut` @ v1.1.0

Give STD a bare-version source-of-truth file and the `/release-prep` +
`/release-cut` slash commands from the `release-prep-and-cut` standard v1.1.0,
with every placeholder filled in for this repo. Add the README version badge
and "What's New" section the commands maintain, and paste the CLAUDE snippet.

## Before you start

- Read the standard: `~/projects/homelab-configs/standards/release-prep-and-cut/README.md`,
  `release-prep.md`, `release-cut.md`, and `CLAUDE-snippet.md` (canonical URL:
  `https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/release-prep-and-cut/README.md`).
  Pin **1.1.0** (the README frontmatter version). The snippet and template
  comments still say v1.0.0, but paste them verbatim anyway.
- Read `CLAUDE.md`, `standards.md`, `docs/decisions.md`, `CHANGELOG.md` (top ~60
  lines and the link-reference block at the bottom), `Dockerfile`, `app.py`
  (`read_version_info`), and `.github/workflows/publish.yml` + `ci.yml`.
- You are on `dev`. Don't switch branches, don't push, and don't create tags or releases.

### Current state (verified 2026-11-15)

- **There is no version file.** The in-app version comes from
  `/app/version.txt`, which the Dockerfile writes from the `APP_VERSION` build arg.
  `publish.yml` passes `APP_VERSION=${{ steps.meta_*.outputs.version }}`, which is the
  semver only on release events and `dev`/`latest`/`pr-N` otherwise. So `:dev` and
  `:latest` images report a non-semver version, and the What's New popup
  (`static/js/dashboard.js` `initChangelogModal`, which keys on `data-std-version`)
  is skipped or confused for them.
- The latest release is **v0.6.7** (tag `v0.6.7`). `[Unreleased]` in CHANGELOG has a
  `### Fixed` entry. Tag history includes a bare `0.6.5` tag that must never be
  re-tagged (see `docs/decisions.md`).
- `publish.yml` currently dual-publishes to GHCR and a deprecated Docker Hub image.
  **Another prompt will remove Docker Hub from it.** In this task, touch
  `publish.yml` only as needed for versioning (step 2). Leave the Docker Hub steps,
  the `REGISTRY_NOTICE` arg, and the banner alone.
- CI workflow `CI` (`ci.yml`) has jobs `Lint`, `Config validation`, `Migration check`,
  and `Compose validation`. The publish workflow is named `Build and Push Docker
  Image` (job `build`). All five are required checks on `main`.
- README has shields.io badges at lines 3–6 but no version badge, and **no "What's
  New" section**. Its TOC is a numbered list.
- `CLAUDE.md` has "Build Status" (two lines: shipped / in flight, now stale: it
  says shipped v0.6.6), "Git Workflow", "Release Process" (manual Releases-UI
  steps), and "Changelog Process" sections.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. It's
expected to be modified by "When done" below.

## What to do

1. **`VERSION` file** at the repo root containing exactly `0.6.7` and a newline. Bare,
   with no `v`.
2. **Make the image read it.** The in-app version should come from `VERSION` on every
   build (dev, main, release, local), not from the metadata-action output:
   - In the Dockerfile, derive `version=` in `/app/version.txt` from the copied
     `VERSION` file. Keep `commit=`, `build_time=`, and `registry_notice=` as they are.
     Remove the `APP_VERSION` build arg, or keep it only as an explicit override if
     you judge that useful, and explain your choice.
   - In `publish.yml`, drop the `APP_VERSION=` build-arg lines if they're no longer
     used, and nothing else. On `release` events, add a step **before the builds**
     that fails the job if the tag (minus its leading `v`) doesn't equal `VERSION`.
     That's a cheap guard against tagging the wrong commit.
   - `app.py`'s `read_version_info` fallback (no version.txt, e.g. a local
     `python app.py`) should read `VERSION` from the repo dir if present. Keep it
     minimal.
3. **Slash commands.** Copy the standard's `release-prep.md` and `release-cut.md` to
   `.claude/commands/`, keep their frontmatter and template comment, and **substitute
   every placeholder** (grep for `<[A-Z_]+>` afterward; none may remain outside the
   comment block's own documentation):
   - `<VERSION_FILE>` = `VERSION`; `<VERSION_LITERAL>` = the whole file content (the
     bare version on a single line).
   - `<README_BADGE_PATTERN>` = `version-<current>-blue` (badge you add in step 4).
   - `<README_WHATSNEW_SECTION>` = `## What's New`.
   - `<DOCS_TO_SYNC>`:
     - `docs/PRD.md`: add a Revision History row (next number, today, one-line
       summary). Rows are in **ascending order**, so append at the bottom of the table.
     - `CLAUDE.md` Build Status: rewrite the two lines (shipped `v<version>` / in
       flight).
   - `<LOCAL_CHECKS>`: the same checks `ci.yml` runs, as commands runnable on a dev
     box: `ruff check .` (pinned 0.15.17; `uvx ruff@0.15.17 check .` is fine), the
     config-validation Python (reference `ci.yml` rather than duplicating it if you
     can do so cleanly), `docker compose config --quiet`, and the migration check
     against a **temp** DB. `alembic.ini` hardcodes `/config/services.db`, so use a
     temp copy of `alembic.ini` with the URL swapped (`alembic -c <tmp>.ini upgrade
     head`, single-head + `(head)` asserts). Never touch a real `/config`.
   - `<CHANGELOG_ARCHIVE_DIR>` = `docs/`.
   - `<MAIN_CI_WORKFLOW>` = `CI`; `<PUBLISH_WORKFLOW>` = `Build and Push Docker Image`.
   - `<RELEASE_IMAGE_TAGS>` = `ghcr.io/crzykidd/service-tracker-dashboard` `:latest`,
     `:<version>`, `:<major>`.
   - Project specifics to add **inside** the commands without restating the standard:
     prep's CHANGELOG roll must also update the link-reference block at the bottom
     (`[Unreleased]` compare link → `v<version>...HEAD`, add a `[<version>]` line),
     matching the existing format. Prep must STOP if `[Unreleased]` has no entries.
     Prep should note that the What's New popup reads CHANGELOG, so the rolled header
     must keep the `## [X.Y.Z] — YYYY-MM-DD` form (em dash) that
     `routes_dashboard.py`'s `_CHANGELOG_SECTION_RE` parses. Check that regex and say
     exactly what form it needs.
4. **README.**
   - Add `![Version](https://img.shields.io/badge/version-0.6.7-blue)` as the first badge.
   - Add a `## What's New` section near the top (after the intro, before the TOC or
     right after it, whichever reads better), seeded with a `### v0.6.7 (2026-11-15)`
     entry in user-facing language drawn from the CHANGELOG `[0.6.7]` section. Add it
     to the TOC and renumber.
   - Update "Versioning & Releases" so releases are described as cut via
     `/release-prep` → merge → `/release-cut`, not the Releases UI.
5. **CLAUDE.md.**
   - Paste `CLAUDE-snippet.md` **verbatim** (with its HTML source comment) after the
     "Code check-in (operational rules)" block.
   - Replace the manual steps in "Release Process" with a short pointer:
     `/release-prep <version>` on dev → human merges PR + waits for CI/`:latest` →
     `/release-cut <version>`. Keep the GHCR/Docker Hub bullet as is, since the other
     prompt owns it.
   - In "Git Workflow", replace "Tag release from `main` via the GitHub Releases UI"
     with the `/release-cut` flow.
   - Keep "Changelog Process", but make "On release: move `[Unreleased]`…" point at
     `/release-prep`.
   - Fix the stale Build Status lines: shipped **v0.6.7**. In flight: the cleanup
     release (vexp removal, standards adoption, Docker Hub removal); `[Unreleased]`
     has entries.
6. **`standards.md`:** add a row `release-prep-and-cut | 1.1.0 | 2026-11-15` with
   notes: `VERSION` file added; publish workflow guards tag == VERSION; first
   real use will be the next release; the bare `0.6.5` historical tag is a known,
   un-fixable deviation.
7. **Docs per Definition of Done:**
   - PRD §11: versioning now uses the `VERSION` file and the two commands. Add a
     revision row appended at the bottom of the table.
   - CHANGELOG `[Unreleased]`: add a `### Changed` entry **only** for the
     operator-visible effect, i.e. `:dev`/`:latest` images now report the real
     version number in Settings → Service Info (and the What's New popup works on
     them). The tooling itself stays out of CHANGELOG (see `docs/decisions.md`).
8. **Validate locally:**
   - Run every `<LOCAL_CHECKS>` command exactly as written in your `release-prep.md`.
   - `docker build` the image and confirm `/app/version.txt` says `version=0.6.7`
     (`docker run --rm <img> cat /app/version.txt`). Clean up the image.
   - Parse `publish.yml`.
   - Grep the two commands for leftover `<PLACEHOLDER>`s.

## Conventions to honor

- Commit prefix `chore:`. No `Co-authored-by` trailer.
- Stage only specific paths; never `git add -A`.
- Don't run the commands you created, don't tag, and don't touch Docker Hub, banner,
  or retention code.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git add` this file, then `git mv` it into `prompts/done/` (on success) or
   `prompts/failed/` (on failure).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top), e.g. the
   APP_VERSION choice, the tag==VERSION guard, and how LOCAL_CHECKS reuses ci.yml.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move. Present the file list and a one-line message.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree and
     report the file list + proposed message back to the orchestrating session.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those paths and
     commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. Branch `dev`,
   `chore:` prefix, no `Co-authored-by:`.
