---
name: 2026-11-15-v069-03-settings-and-token-hardening
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Fix dropped settings, the unset-token bypass, and add credential warnings (PRD §12.3)

Two documented settings are silently ignored, and an unset `API_TOKEN` accepts `Bearer None`. Fix both, harden token comparison and logging, and warn when default credentials are still in use.

## Before you start

- Read `CLAUDE.md` (project rules + the three standards snippets — they apply).
- Read `docs/PRD.md` §12 intro and this task's subsection (named below);
  read the 2026-11-15 "v0.6.9 scope" entry in `docs/decisions.md`. The design
  calls there are settled — don't re-litigate them; if the code makes one
  impossible, stop and report rather than improvising.
- Part of the v0.6.9 sequence (`prompts/2026-11-15-v069-*.md`, run in number
  order). Confirm earlier prompts in the sequence are in `prompts/done/`; if one
  isn't, stop and report.
- PRD subsection: **§12.3**.
- Read `settings_loader.py`, `app.py`, `routes_api.py` (`_check_bearer_auth`), `routes_dashboard.py` (`/settings`), `templates/settings.html`, `settings.example.yml`, `tests/`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Dropped settings.** Add `widget_value_retention_days` (int, default 30) and `register_field_ownership` (str, default `user_wins`) to `VALID_KEYS`/`DEFAULT_VALUES`, so both ENV and `settings.yml` reach `app.config`. Audit `settings.example.yml` and the README table for any other documented-but-unloaded key. Add a test that parses `settings.example.yml` (including commented-out `#key:` lines) and asserts every key is in `VALID_KEYS`. Remove the matching `xfail` from v069-01.
2. **Unset token.** If `api_token` is falsy, `/api/v1/register` returns `503 {"error": "API token not configured"}` (no comparison attempted), with one WARNING at startup. Settings → Service Info shows a visible notice that registers are disabled until `API_TOKEN` is set. Remove the matching `xfail`, and add a test for the 503.
3. Compare with `hmac.compare_digest` (encode both sides; handle a missing header).
4. **Masked logging.** In the startup settings logs (`app.py`, both loops, and the `settings_loader` debug lines), print `api_token` as `***` (or `***<last4>`). Use a small `SECRET_KEYS` set so future secrets are covered.
5. **Default-credential warnings.** At startup, WARN if `FLASK_SECRET_KEY` is unset (the fallback is in use), and WARN if the `admin` user exists and `check_password("changeme123")` is true. Show a dismissible notice on the Settings page for admins naming whichever applies, with how to fix it. Do not force a change. Check the password once at startup and cache the result on `app.config` rather than hashing on every request. Recompute it when an admin changes a password (`routes_auth.py`).
6. Tests for 3–5 where practical (masking, and the flags for each warning).

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

- Operator-visible: CHANGELOG `### Fixed` (the two settings now work; an unset token no longer accepts a bogus header) and `### Security` (constant-time compare, masked token in logs, default-credential warnings). Note in the CHANGELOG that installs without `API_TOKEN` will now get 503 on register.
- Commit prefix: `fix:`.

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
