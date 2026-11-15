---
name: 2026-11-15-docs-refresh-after-standards
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15    # filled when the work is done
result: CLAUDE.md consolidated, PRD s11 added and renumbered, README Development section, HISTORY entry, standards.md wording fixed
---

# Task: Refresh project docs after the v0.6.7 / v0.6.8 work

Over 2026-11-15 STD did the following, mostly through targeted edits:
- moved images to GHCR (v0.6.7)
- removed vexp
- adopted three standards (handoff-prompt-workflow, code-checkin-and-pr, release-prep-and-cut)
- removed Docker Hub (v0.6.8)
- fixed the release-prep migration snippet

Make the docs read as one coherent, current set. Remove duplication and stale
"current state" claims, and make sure the layout and process docs describe the
repo as it is now. **This is a docs-only task. Don't change code, workflows,
or the slash commands.**

## Before you start

- Read in full: `CLAUDE.md`, `README.md`, `standards.md`, `docs/decisions.md`,
  `docs/HISTORY.md`, `docs/PRD.md` (at least the TOC, §3, §6, §11, §13, and the
  revision table), and `docs/FUTURE.md` headings.
- `git log --oneline 2c78f30..HEAD` shows what changed since v0.6.6.
- `ls` the repo root, `.github/workflows/`, `.claude/`, `prompts/`, `docs/`.
- You are on `dev`. Don't switch branches and don't push.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. So is
`prompts/startnewsession.md`, which the orchestrating session is writing; don't
edit it.

## What to do

1. **CLAUDE.md: consolidate and fix stale content.**
   - **Never edit the three pasted standards snippets.** These are the blocks headed
     "Handoff prompts (operational rules)", "Code check-in (operational rules)", and
     "Release process (operational rules)", each with its HTML source comment. Treat
     them as read-only.
   - Remove or merge project sections that now just repeat those snippets. Likely
     candidates are "Git Workflow", "Release Process", "Git Rules", and parts of
     "Commit style". Keep only project-specific facts the snippets don't carry, such
     as the `refactor:` extension, GHCR as the only registry, the required check
     names, the `/release-prep` → merge → `/release-cut` flow, the `VERSION` file,
     and "Changelog Process" specifics (user-facing language, categories, tooling
     changes stay out per `docs/decisions.md`). Aim for one place per fact.
   - Update "Module Layout (current, v0.6.0)" to the actual tree, and drop the
     stale version from the heading. Add the root files and dirs that now exist and
     matter: `VERSION`, `ruff.toml`, `standards.md`, `Dockerfile`/`entrypoint.sh`,
     `.github/workflows/{ci,publish,retention}.yml`, `.claude/commands/`,
     `prompts/`, `docs/decisions.md`, `scripts/`. Verify every listed module still
     exists.
   - "Project Documentation": make sure it lists every doc, including
     `standards.md` and `docs/FUTURE.md`.
   - Keep "Build Status" exactly two lines. Shipped is **v0.6.8**. The "once cut"
     wording is now stale, so fix it. In flight: `dev` holds the release-prep
     snippet fix (`2df45f1`) and this docs refresh; nothing else is scoped.
   - Keep the "Known debt" note, but update it if part of the audit it describes
     has been done (the 2026-05-23 reconciliation). Don't claim more than is true.
2. **PRD.**
   - §3 module layout: same correction as CLAUDE.md, so both agree.
   - Add a section **"v0.6.7–v0.6.8 — Registry move and engineering standards
     (Delivered)"** after §10, in the style of §§8–10, and renumber the later
     sections and the TOC. It covers: the GHCR move and the banner-only final Docker
     Hub release; Docker Hub removal; the `VERSION` file as the version source and
     the tag==VERSION guard; the CI checks and GHCR retention; the release commands;
     and the Add Entry fix. Keep §11 (Versioning) as the reference and cross-link
     rather than duplicate.
   - §6 "Current State (v0.4.14)" is historical. Don't rewrite it. If its heading
     reads as current, retitle it to make clear it's a historical baseline.
   - Add a revision-history row: next number, appended at the **bottom** (rows are
     ascending).
3. **README.**
   - Accuracy sweep of the sections touched today: What's New, Docker Compose
     Setup, Moving from Docker Hub, Versioning & Releases. Fix anything wrong. Keep
     it operator-facing.
   - Add a short **"Development"** section near the end (before License), with a
     TOC entry. Cover: work on `dev`; required CI checks (name them); `ruff.toml`
     lint scope; releases via `/release-prep` / `/release-cut`; and
     `standards.md`, `prompts/`, and `docs/decisions.md` for contributors. Link
     rather than restate.
   - Leave the screenshots TODO comment. Refreshing screenshots is out of scope.
4. **HISTORY.md:** append a section **"Engineering standards adoption (v0.6.8)"**
   in the file's Why / What changed / Impact format. Cover: vexp de-adoption, the
   three standards adopted with their pins, the `VERSION` file, and v0.6.8 as the
   first release through the new commands. Keep it short and link to
   `standards.md` and `docs/decisions.md`.
5. **standards.md:** check the rows are accurate against the repo, for example
   whether the code-checkin notes still mention Docker Hub correctly. Fix the
   wording only; don't change pins.
6. **CHANGELOG:** no entry. This is docs/tooling only, per `docs/decisions.md`.
7. **Validate:**
   - Every relative link you added or touched resolves (files exist; anchors match
     GitHub slug rules).
   - The PRD TOC numbering matches the section headings.
   - `grep -n "v0.6.0)" CLAUDE.md` shows no stale "current" labels.
   - Run the config-validation script from `ci.yml` (see
     `.claude/commands/release-prep.md` Step 6). Markdown isn't checked by it, but
     confirm nothing else broke.

## Conventions to honor

- Commit prefix `docs:`. No `Co-authored-by` trailer. Stage only specific paths.
- Don't edit the pasted snippets, code, workflows, `.claude/commands/`, CHANGELOG
  version sections, `prompts/done/*`, or `prompts/startnewsession.md`.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `git add` this file, then `git mv` it into `prompts/done/` (or `prompts/failed/`).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top), but only
   real judgment calls, such as which CLAUDE.md sections you merged or removed and why.
4. Hand off ONE commit covering this prompt file, the files you modified, and the
   prompt move. Present the file list and a one-line message.
   - **If you are a spawned agent:** do **not** commit. Prepare the tree and report
     back, with a short per-file summary of what changed and what you removed from
     CLAUDE.md.
   - **If you are running directly (manual fallback):** ask
     `commit these as "<message>"? (y/n)` yourself.
   Either way: never `git add -A`, never push, never auto-commit. Branch `dev`,
   `docs:` prefix, no `Co-authored-by:`.
