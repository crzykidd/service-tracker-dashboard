---
name: 2026-11-15-v069-09-gunicorn-and-pins
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Run under gunicorn (single worker) and pin dependencies (PRD §12.9)

The image runs the Werkzeug dev server via `python app.py`, and `requirements.txt` is unpinned. Switch production to gunicorn with exactly one worker, and pin the dependency set.

## Before you start

- Read `CLAUDE.md` (project rules + the three standards snippets — they apply).
- Read `docs/PRD.md` §12 intro and this task's subsection (named below);
  read the 2026-11-15 "v0.6.9 scope" entry in `docs/decisions.md`. The design
  calls there are settled — don't re-litigate them; if the code makes one
  impossible, stop and report rather than improvising.
- Part of the v0.6.9 sequence (`prompts/2026-11-15-v069-*.md`, run in number
  order). Confirm earlier prompts in the sequence are in `prompts/done/`; if one
  isn't, stop and report.
- PRD subsection: **§12.9**. The one-worker rule is non-negotiable (see `docs/decisions.md`).
- Read `app.py` (`__main__`), `jobs.py` (`start_background_workers`), `entrypoint.sh`, `Dockerfile`, `docker-compose.yml`, `requirements.txt`, and `.github/workflows/ci.yml`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. Move the startup work in `__main__` (`create_default_admin`, `verify_and_fetch_missing_icons`, `start_background_workers`) into one function, e.g. `app.run_startup_tasks(app)`, that is idempotent within a process. `__main__` calls it, keeping the Werkzeug reloader guard.
2. Add `gunicorn.conf.py`: `bind = "0.0.0.0:8815"`, `workers = 1` with a comment explaining why it must stay 1, `threads = 4` (or similar), access log to stdout, and a `post_worker_init` hook that calls the startup function. Do not use `preload_app`, because threads started in the master don't survive a fork.
3. `entrypoint.sh`: keep `alembic upgrade head`, then `exec gunicorn -c gunicorn.conf.py app:app`. `FLASK_DEBUG=1` may keep using `python app.py`; document which mode does what.
4. Pin dependencies: move the current list to `requirements.in` (add `gunicorn`, and `Flask-WTF` if v069-04 added it), then generate a fully pinned `requirements.txt` with `uv pip compile --python-version 3.11 requirements.in -o requirements.txt`. Update `requirements-dev.txt` if needed. Put a header comment in `requirements.txt` saying how to regenerate it. Update the release-prep `<LOCAL_CHECKS>` migration snippet only if it breaks.
5. Verify: `docker build` succeeds; the container starts; `/healthz` responds; logs show the scheduler and health thread starting **once**; a register works. Report what you actually ran. If Docker isn't available, say so explicitly, and at least run `gunicorn -c gunicorn.conf.py app:app` locally with `STD_CONFIG_DIR`.
6. Update CLAUDE.md Stack (add gunicorn) and Module Layout (add `gunicorn.conf.py`, `requirements.in`, `requirements-dev.txt`, `tests/`). Update PRD §3 architecture/runtime if it describes the dev server.

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

- CHANGELOG `### Changed`: production server is now gunicorn; startup log lines look different; no config change needed. README Development: how to regenerate the pins.
- Commit prefix: `chore:` for pins, or `feat:`; a single commit, so pick `chore:` unless something operator-facing dominates.

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
