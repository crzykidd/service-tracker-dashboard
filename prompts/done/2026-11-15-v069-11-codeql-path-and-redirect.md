---
name: 2026-11-15-v069-11-codeql-path-and-redirect
status: completed        # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15    # filled when the work is done
result: Icon, restore, widget paths confined and redirects made same-site; 13 CodeQL alerts addressed, 107 tests pass
---

# Task: Fix CodeQL path-injection and open-redirect alerts (PRD §12.11)

CodeQL has 13 open alerts on `main`. Eleven are `py/path-injection` (high) and two are `py/url-redirection` (medium). All predate v0.6.9. Fix them on `dev` so they ship in v0.6.9: release PR #75 is open and not yet merged.

## Before you start

- Read `CLAUDE.md` (project rules + the three standards snippets — they apply).
- Read `docs/PRD.md` §12 intro and this task's subsection (named below);
  read the 2026-11-15 "v0.6.9 scope" entry in `docs/decisions.md`. The design
  calls there are settled — don't re-litigate them; if the code makes one
  impossible, stop and report rather than improvising.
- Part of the v0.6.9 sequence (`prompts/2026-11-15-v069-*.md`, run in number
  order). Confirm earlier prompts in the sequence are in `prompts/done/`; if one
  isn't, stop and report.

- PRD subsection: **§12.11**. It doesn't exist yet; you add it (see "What to do").
- This prompt runs **after** `/release-prep 0.6.9`. `VERSION` is already `0.6.9` and CHANGELOG already has `## [0.6.9] — 2026-11-15`. Do not re-roll anything.
- List the alerts with `gh api "repos/crzykidd/service-tracker-dashboard/code-scanning/alerts?state=open&per_page=50"` (read-only). Line numbers are for `main`. Find the same code on `dev`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

Alert map (main line numbers; locate the equivalent code on `dev`):
- #4, #5 `image_utils.py` `resolve_image_metadata`: the icon name, which comes from the register payload, is joined into `image_dir` and written to.
- #11, #12 `routes_dashboard.py` `/add`: `image_icon` form field → `os.path.join(image_dir, image_icon)` → write.
- #13, #14 `routes_dashboard.py` `/edit`: same pattern with `raw_icon`.
- #8, #9, #10 `routes_dashboard.py` `/settings` restore from a server file: `selected_filename` is joined into `BACKUP_DIR` (there's an existing `..` check).
- #6, #7 `routes_widgets.py` `/widget_config/<widget_name>`: `os.path.join('/app/widgets', widget_name, 'settings.json')`.
- #2, #3 `routes_dashboard.py` `/edit`: `redirect(referrer)` after delete and after save; `referrer` comes from the request (`ref` arg or form/header).

1. **Icon names:** add one helper, e.g. `image_utils.safe_icon_filename(name) -> str | None`. It lowercases, strips a trailing `.svg`, accepts only `^[a-z0-9][a-z0-9._-]*$` (no slashes, no `..`, length ≤ 100), and returns `<name>.svg` or None. Use it in all three places. Invalid names: in register, skip the icon with a WARNING and continue the register (never 400 a register over an icon). In add/edit, flash a validation message and don't download. Also confirm the final path's `os.path.realpath` is inside `realpath(image_dir)` before any `open()`. CodeQL recognises that containment check pattern.
2. **Backup restore:** take `os.path.basename(selected_filename)`, reject anything that changes under basename or doesn't end in the backup extension(s) the code produces, then check `realpath(join(BACKUP_DIR, name))` starts with `realpath(BACKUP_DIR) + os.sep`. Keep the existing flash messages. Check any other `BACKUP_DIR` join on user input (e.g. a download route) and apply the same check.
3. **Widget config:** accept `widget_name` only if it is one of the directory names actually present under the widgets dir (list it). Otherwise return `jsonify([])` as today. Derive the widgets dir from the app root (`os.path.dirname(__file__)`), not the hardcoded `/app/widgets`, so it also works locally and in tests. Keep the container behavior identical.
4. **Open redirect:** add `view_helpers.safe_redirect_target(target, fallback)`. It allows only relative paths: no scheme, no netloc, starting with a single `/`, and not `//` or `/\`. Everything else falls back to `url_for('dashboard.dashboard')`. Use it everywhere `referrer`/`ref`/`request.referrer` feeds `redirect()`. Grep for all of them, including the CSRF error handler in `app.py` and the soft-delete/restore routes added in v0.6.9.
5. **Tests** (new `tests/test_security_paths.py`):
   - the icon sanitiser: good names, `../x`, `a/b`, `..`, absolute paths, and overlong names
   - a register with a traversal icon still succeeds and writes nothing outside `image_dir`
   - edit with a bad icon flashes and writes nothing
   - restore with `../x.yml` is rejected
   - `/widget_config/..%2f..` returns `[]`
   - `safe_redirect_target` with `https://evil`, `//evil`, `/\evil` and `/tiled_dash?x=1`
   - edit save with `ref=https://evil` redirects to the dashboard
   Mock network icon fetches (`requests.get`).
6. **Docs:**
   - CHANGELOG: add bullets to the **existing `[0.6.9]` section's `### Security`** (not `[Unreleased]`, which stays empty), in operator language. Paths built from icon names, backup filenames and widget names are now confined to their folders; post-save/delete redirects only go to pages within STD.
   - PRD: add `### 12.11 CodeQL path and redirect fixes [\`v069-11-codeql-path-and-redirect\`] — Delivered in v0.6.9` at the end of §12 (before the `---` that precedes §13), plus a revision row appended at the bottom.
   - README What's New `v0.6.9` entry: extend the existing **Security** bullet by a few words. Don't add a new section.
7. Do **not** dismiss alerts in GitHub. They close automatically when CodeQL re-scans `main` after the merge.

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

- **Overrides the generic CHANGELOG rule above:** entries go in `[0.6.9]`, not `[Unreleased]`. The release is prepped but not cut.
- Commit prefix: `fix:`. After committing, the orchestrator must also update PR #75's description, because it must equal the `[0.6.9]` CHANGELOG section. Note that in your report; don't do it yourself.

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
