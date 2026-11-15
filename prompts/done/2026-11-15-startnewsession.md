---
name: startnewsession
status: completed        # pending | completed | failed
created: 2026-11-15
model: opus              # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: Reviewed v0.6.8; scoped one large 0.6.9 patch (hardening + safety net) in PRD §12; 10 sonnet prompts written (v069-01…10)
---

# Task: Review the current state of STD and design the next updates

This is a **review + design session, not a build session.** Get a grounded picture of
what STD is today, surface what's worth doing next, and work with the user to choose
and scope the next release. The output is decisions and written plans (PRD / FUTURE
updates + handoff prompts), **not code**.

Run it from the repo root:
`claude --model opus "Read prompts/startnewsession.md and execute it as your task."`

## Before you start

Read these first, in this order:

1. `CLAUDE.md`: project rules, plus the three pasted standards snippets (handoff
   prompts, code check-in, release process). They apply to this session.
2. `standards.md`, then `docs/decisions.md` (newest first).
3. `README.md` (What's New and Development sections), `CHANGELOG.md` (`[Unreleased]`
   through `[0.6.0]`).
4. `docs/PRD.md`: TOC, §3 architecture, the delivered sections, §11 versioning, and
   Open Questions.
5. `docs/FUTURE.md`: parked design discussions, read in full.
6. `docs/HISTORY.md`: structural events.
7. `git log --oneline -30` and `ls prompts/ prompts/done/`.

### Where things stand (as of 2026-11-15)

- **Shipped:** v0.6.8 (GHCR only). v0.6.7 was the last Docker Hub image and
  shows a "moved to GHCR" banner. Docker Hub tags stay frozen there on purpose.
- **On `dev`, unreleased:** a release-prep migration-snippet fix (`2df45f1`) and a
  docs refresh. Both are tooling/docs only, with no CHANGELOG entries.
- **Process now in force:**
  - handoff-prompt-workflow 2.0.0: edits beyond about two files go into a
    `prompts/` file, run by a spawned Sonnet agent, with one y/n commit at the end.
  - code-checkin-and-pr 1.2.0: work on `dev`; `main` requires `build`, `Lint`,
    `Config validation`, `Migration check`, `Compose validation`, and CodeQL.
  - release-prep-and-cut 1.1.0: `VERSION` file, `/release-prep` → human merge →
    `/release-cut`.
- **Next version:** if the next release is a **minor (0.7.0)**, `/release-prep`
  will archive every closed minor series in CHANGELOG (0.1.x–0.5.x) into
  `docs/CHANGELOG-<minor>.x.md` with summary blocks. **The 0.4.x entries are dated
  `2026-XX-XX`**, which will produce odd headers and anchors. Decide how to handle
  that before the first minor release.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. It's
expected to be modified by "When done" below.

## What to do

### Phase 1: Review (read-only)

Build an honest picture of the current state. Check claims against the code; don't
trust the docs alone (CLAUDE.md's "Known debt" note explains why). Cover:

1. **Product:** what the dashboard views, register API, widgets, health checks,
   exposure synthesizer, and settings actually do today. Note rough edges you find
   in the code or templates.
2. **Parked and open design items.** Summarize each one in a sentence or two, with
   its current relevance:
   - `docs/FUTURE.md`: Tools as a first-class concept; Service identity and
     duplicate detection; Soft-delete for service entries; Adding entries.
   - PRD Open Questions: per-widget retention granularity; per-source API tokens;
     per-service health-check timeouts; read-replica for dashboard reads.
3. **Engineering gaps.** Known candidates; confirm and size each:
   - **No test suite.** The code-checkin `Test` check is exempt until one exists.
     This is probably the highest-leverage gap.
   - Lint scope is deliberately narrow (`ruff.toml`: E9 and F only). Decide whether
     to widen it.
   - `repo-sandbox-permissions` standard not adopted.
   - README screenshots predate the v0.6.1 redesign (a TODO comment is in the README).
   - Security posture: the `FLASK_SECRET_KEY` fallback default, a single shared
     `API_TOKEN`, and auth on the API vs. the UI.
   - The CHANGELOG `2026-XX-XX` dates vs. the minor-release archive step (above).
   - Docs-vs-reality audit of **both** this repo and `docker-api-notifier` (the
     "Known debt" note in CLAUDE.md). Check how much of it is still outstanding.
   - Loose ends noticed during the 2026-11-15 docs refresh:
     - README links to `LICENSE`, but the repo has no LICENSE file.
     - The README top banner still headlines the v0.6.0 `/api/register` removal.
     - The release-prep snippet comment in CLAUDE.md and the template header in
       `.claude/commands/release-prep.md` say `@ v1.0.0`, while `standards.md`
       pins 1.1.0. Both are upstream text, so the fix probably belongs in
       `homelab-configs`.
     - PRD §5.2 (schema gaps) and §14 (Open Questions) were not re-verified, for
       example "worth considering for v0.6.x".
     - README's "GHCR images start at v0.6.7" line will age awkwardly.
4. **Cross-repo:** the register contract with `docker-api-notifier`. Are there
   pending notifier changes STD must accept first (the ordering rule)? Check the
   notifier repo if it's available locally; otherwise ask the user.

Present the review to the user as a concise, prioritized list (what it is, why it
matters, rough size). **Stop and let the user react before designing anything.**

### Phase 2: Design (with the user)

1. Help the user choose a theme and scope for the next release (0.6.9 patch vs.
   0.7.0 minor). Recommend; don't just list options.
2. For each chosen item, write it up where it belongs:
   - **Committed, scoped work:** add a planned section to `docs/PRD.md` (a revision
     row appended at the bottom of the ascending table), and write **one handoff
     prompt per buildable chunk** in `prompts/` from `prompts/TEMPLATE.md`
     (`model: sonnet` for coding). Don't run them unless the user asks. Execution
     can be a later session.
   - **Discussed but deferred:** park it in `docs/FUTURE.md` with the context and
     the reason for deferral, per that file's conventions.
   - **Rejected or redirected:** add an entry in `docs/decisions.md`.
3. Respect the cross-repo ordering rule. If a design needs new register fields, STD
   must accept them before the notifier sends them. Call that out in the PRD
   section.

## Conventions to honor

- No code changes in this session. Docs and prompts only.
- Commit prefix `docs:`. No `Co-authored-by` trailer. Stage only specific paths.
- Keep the CHANGELOG untouched: nothing here ships to operators.

## When done

1. Update this file's frontmatter: `status` (completed/failed), `completed` (the
   date), and `result` (one line, e.g. "Reviewed v0.6.8; scoped 0.7.0 = X, Y; 3
   prompts written").
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Before moving, consider leaving a fresh `prompts/startnewsession.md`
   for the session after, if the user wants a standing kickoff file.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the docs and prompts written, and
   the prompt move. Present the file list and a one-line message, and ask
   `commit these as "<message>"? (y/n)`. On `y`, stage those specific paths and
   commit on `dev`. Never `git add -A`, never push, never auto-commit.
