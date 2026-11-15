---
name: 2026-11-15-v069-10-docs-loose-ends
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Docs loose ends: CHANGELOG dates, LICENSE, README banner (PRD §12.10)

Fix the placeholder CHANGELOG dates using the real git-tag dates, add the missing MIT LICENSE the README links to, and refresh stale README wording.

## Before you start

- Read `CLAUDE.md` (project rules + the three standards snippets — they apply).
- Read `docs/PRD.md` §12 intro and this task's subsection (named below);
  read the 2026-11-15 "v0.6.9 scope" entry in `docs/decisions.md`. The design
  calls there are settled — don't re-litigate them; if the code makes one
  impossible, stop and report rather than improvising.
- Part of the v0.6.9 sequence (`prompts/2026-11-15-v069-*.md`, run in number
  order). Confirm earlier prompts in the sequence are in `prompts/done/`; if one
  isn't, stop and report.
- PRD subsection: **§12.10**.
- Get the dates with `git tag -l --format='%(refname:short) %(creatordate:short)' | sort -V`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. CHANGELOG: replace every `2026-XX-XX` on `[0.4.0]`–`[0.4.14]` with that tag's date (they are **2025** dates). Series headers `[0.3.x]`, `[0.2.x]`, `[0.1.x]` use the date of the series' first tag (v0.3.0, v0.2.0, v0.1.0). Keep the em-dash header format exactly (`## [X.Y.Z] — YYYY-MM-DD`), because the What's New popup parses it. Check the popup parser (`/api/v1/changelog` in `routes_dashboard.py`) tolerates the `[0.3.x] series` headers, and report what you find.
2. Add `LICENSE`: the standard MIT text, `Copyright (c) 2025 crzykidd`.
3. README: replace the top-of-file v0.6.0 `/api/register` removal banner with a one-to-two line current compatibility note (STD v0.6.0+ needs notifier v0.3.0+; v0.4.0+ for network/port/exposure data). Reword any "GHCR images start at v0.6.7" phrasing so it states a fact that won't age (e.g. "Docker Hub images stop at v0.6.7"). Leave the screenshots TODO, but update its comment to say it's still outstanding as of v0.6.9.
4. Don't touch the `release-prep-and-cut @ v1.0.0` text in CLAUDE.md or `.claude/commands/`. It's upstream; see `docs/decisions.md`.

## Conventions to honor

- Work on `dev`. Commit prefix per CLAUDE.md (`feat:` / `fix:` / `chore:` /
  `docs:` / `refactor:`), no `Co-authored-by:` trailer.
- **Definition of Done (CLAUDE.md "Always"):** in the same commit —
  CHANGELOG `[Unreleased]` entry for anything operator-visible (user-facing
  language; tooling-only changes go in `docs/HISTORY.md` / `docs/decisions.md`
  instead); README updated if operator-facing behavior or settings changed
  (settings reference table included); PRD §12 subsection status flipped from
  "Planned" to "Delivered (unreleased)" with any as-built deviations noted, plus a
  PRD revision-history row appended at the bottom of the table.
- Schema changes only via a new Alembic migration chained on the current head;
  FK/lookup columns get their index in the same migration.
- Run locally before handing off: `uvx ruff@0.15.17 check .`, `pytest` (once
  `tests/` exists), and the migration check from `.claude/commands/release-prep.md`
  `<LOCAL_CHECKS>` if you touched `alembic/`. Report the results verbatim.
- New settings must be added to `settings_loader.VALID_KEYS` / `DEFAULT_VALUES`,
  `settings.example.yml`, and the README settings table.

- CHANGELOG date corrections and the LICENSE are not operator-visible feature changes, so no `[Unreleased]` entry. Record "CHANGELOG historical dates corrected from tags; LICENSE added" in `docs/HISTORY.md`.
- Commit prefix: `docs:`.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. By default the message
   is a plain one-liner and the branch is whatever the session is on. **Only if** the
   project also adopts `code-checkin-and-pr` do its branch rules (`dev`, never `main`)
   and commit-prefix conventions (`feat:` / `fix:` / `chore:` / `docs:`, no
   `Co-authored-by:`) apply on top.
