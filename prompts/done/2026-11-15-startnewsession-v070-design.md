---
name: startnewsession
status: completed        # pending | completed | failed
created: 2026-11-15
model: opus              # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: User redirected to a Dashboard + Monitoring theme; v0.7.0 scoped as PRD §13 with six prompts (prompts/v070-01..06), follow-ups parked in FUTURE.md, design calls in decisions.md
---

# Task: Pick and design the next STD features

This is a **feature design session, not a build session.** v0.6.9 closed out the
hardening and safety-net work; this session's job is to pick the next
**operator-facing features** with the user, scope them, and turn them into a
planned PRD section plus handoff prompts. The output is decisions and written
plans, **not code**.

Run it from the repo root:
`claude --model opus "Read prompts/startnewsession.md and execute it as your task."`

## Before you start

Read these first, in this order:

1. `CLAUDE.md`: project rules and the three standards snippets. They apply here.
2. `standards.md`, then `docs/decisions.md` (newest first; the v0.6.9 entries
   explain the current shape of delete, staleness, CSRF, and the runtime).
3. `docs/FUTURE.md`: read in full. This is the main feature backlog.
4. `docs/PRD.md`: TOC, §3 architecture, §5 data model (incl. §5.5 v0.6.9
   schema), §12 (v0.6.9 as delivered), §14 cross-repo, §15 Open Questions.
5. `CHANGELOG.md` `[0.6.9]` and `README.md` What It Does / Settings reference.
6. `git log --oneline -20` and `ls prompts/ prompts/done/`.

### Where things stand (as of 2026-11-15)

- **Shipped:** v0.6.9 (GHCR `:latest`, `:0.6.9`, `:0`). Nothing unreleased on
  `dev` except a docs-only label re-sync (`8ecd232`).
- **New foundations to build on:** pytest suite in `tests/` (107 tests; `Test` is
  a required check — new features ship with tests); soft-delete with
  Settings → Deleted; detached widgets; one `stale_after_minutes` threshold on
  all views; per-service health-check options; CSRF everywhere (`stdPost` for
  JS POSTs); gunicorn single worker; pinned deps (`requirements.in` →
  `uv pip compile`).
- **Notifier:** latest release v0.4.1; nothing pending that STD must accept
  first. Repo isn't checked out locally — use `gh` to read it.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

### Phase 1: Present the candidate features (read-only)

Build a short, prioritized menu for the user. For each candidate: what it is,
what it gives the operator, rough size, dependencies, and whether it touches
the register contract. Check each against the code — don't trust the docs alone.
Known candidates:

- **Duplicate detection** (FUTURE.md "Service identity and duplicate
  detection"). Its two prerequisites, staleness and widget detach, shipped in
  v0.6.9, so it is now **unblocked**. Open points: soft-deleted rows must be
  excluded from both sides; decide whether it reuses `stale_after_minutes`
  (5 min) or needs its own looser threshold (the sketch assumed 2h).
- **Tools as a first-class concept** (FUTURE.md). Still gated on a concrete
  second tool. Ask the user whether one exists (Dockhand? Portainer?) or whether
  per-host Dozzle URLs are wanted.
- **Per-source API tokens** (PRD §15): per-host tokens, revoke one notifier,
  last-seen per token.
- **Per-widget retention** (PRD §15).
- **Concurrent health checks** (deferred out of v0.6.9; matters more now that
  per-service timeouts can lengthen a pass).
- **Quality-of-life items from the v0.6.9 run:**
  - Add/Edit pages don't render flash messages (validation feedback shows up
    later on Settings).
  - Edit page "none" widget deletes a widget another entry shares.
  - What's New shows the 0.1.x–0.3.x series text under 0.4.0.
  - `settings.example.yml` ships `api_token: supersecrettoken` uncommented.
  - README screenshots predate v0.6.1 (needs a live instance).
- Anything the user brings. **Ask what they want before ranking.** They said
  this session is about new features.

Give a recommendation, not just a list. **Stop and let the user choose before
designing anything.**

### Phase 2: Design (with the user)

1. Agree a theme and version. A feature release is a natural **0.7.0** minor.
   Note that a minor fires `/release-prep`'s per-minor CHANGELOG archive step
   (0.1.x–0.5.x get summarized into `docs/CHANGELOG-<minor>.x.md`). The
   placeholder dates were fixed in v0.6.9, so the archive should run clean, but
   check the `[0.x.x] series` headers against the archive step's expectations.
2. For each chosen feature:
   - **Committed, scoped:** a planned PRD section (new §, revision row at the
     bottom of the table; renumber later sections and the TOC if needed), and
     **one handoff prompt per buildable chunk** in `prompts/` from
     `prompts/TEMPLATE.md` (`model: sonnet` for coding). Each prompt names its
     tests. Don't run the prompts unless the user asks.
   - **Discussed but deferred:** park in `docs/FUTURE.md` with context and the
     reason. When an item moves into the PRD, remove it from FUTURE.md.
   - **Rejected or redirected:** an entry in `docs/decisions.md`.
3. **Cross-repo ordering rule:** if a feature needs new register fields, STD
   must accept them (and ship) before the notifier sends them. Call that out
   in the PRD section, and say whether a notifier change is needed at all.

## Conventions to honor

- No code changes in this session. Docs and prompts only.
- Commit prefix `docs:`. No `Co-authored-by` trailer. Stage only specific paths.
- Keep the CHANGELOG untouched: nothing here ships to operators.
- Update CLAUDE.md "Build Status" in-flight line to name the scoped release.

## When done

1. Update this file's frontmatter: `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (success) or `prompts/failed/` (failure),
   renamed with a date prefix (e.g. `prompts/done/<date>-startnewsession.md`).
   Offer to leave a fresh `prompts/startnewsession.md` for the session after.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the docs and prompts written, and
   the prompt move. Present the file list and a one-line message, and ask
   `commit these as "<message>"? (y/n)`. On `y`, stage those specific paths and
   commit on `dev`. Never `git add -A`, never push, never auto-commit.
