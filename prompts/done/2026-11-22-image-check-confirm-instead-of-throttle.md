---
name: 2026-11-22-image-check-confirm-instead-of-throttle
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: Check now confirms inside the cooldown (UI), API keeps 429; scheduler fix kept; ruff and pytest green
---

# Task: Image update "Check now" asks for confirmation instead of refusing within the hour

Today, "Check now" (Settings → Sources → Image updates, and the per-entry button) refuses with
"checked recently; try again later" if pressed within the cooldown: an hour for everything,
15 minutes for one image. The operator wants to be able to check **whenever they want**.
Within the cooldown they should get a **confirmation pop-up** instead, for example:

> The last image check ran **27 minutes ago**. Image registries (Docker Hub, GitHub's
> GHCR) limit how many anonymous requests STD can make per day, and every check uses part
> of that allowance. Check again anyway?

Pressing OK runs the check; Cancel does nothing.

## Before you start

- Read `CLAUDE.md` and PRD §24 (especially the Check now and throttle text near
  `docs/PRD.md` ~L4095 and the Settings section ~L4157).
- **The working tree already holds an uncommitted fix. Keep it, and don't redo it:**
  - `image_update.execute()` now reads `enabled_providers()` inside `app.app_context()`.
    Before that, every scheduler run failed with "Working outside of application
    context", so the last run stayed "never".
  - The fix also added the test
    `test_scheduler_runs_outside_an_app_context_record_the_last_run` in
    `tests/test_image_updates.py` and a CHANGELOG `[Unreleased]` → `### Fixed` entry.
  - It goes into the same commit as this work.
- **Relevant code:**
  - `image_update.py`: `GLOBAL_COOLDOWN_SECONDS` and `REF_COOLDOWN_SECONDS`,
    `request_check()`, `CheckRequestError`, `_THROTTLE`, `last_run()`, `_parse_iso`,
    and `ImageReference.checked_at`;
  - `routes_dashboard.py`: `_check_now_json`, `check_image_update_now`,
    `check_image_updates_now`;
  - `static/js/image_update.js`, the delegated `[data-image-check]` click handler with
    toasts;
  - `static/js/settings/ui.js`, which has `ui.confirm({title, body, confirmLabel})` that
    returns a Promise. It is only loaded on Settings, so fall back to `window.confirm`
    elsewhere (the dashboards and the Compact details dialog).
  - The management API Check now is in `routes_mgmt_api.py` ~L1507, and the MCP calls
    it.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below. **Exception:** the dirty `image_update.py`,
`tests/test_image_updates.py` and `CHANGELOG.md` are the expected scheduler fix described
above. Build on them; don't stop to ask.

## What to do

1. **Engine (`image_update.py`):** give `request_check(app, entry=None, force=False)` a
   confirmation step.
   - **How long ago a check last happened:**
     - for **everything**: the later of the persisted last run (`last_run()["at"]`,
       which survives a restart) and the last accepted Check now request for everything;
     - for **one entry**: the later of that reference's `ImageReference.checked_at` and
       the last accepted per-reference request.
     - Store the request times as wall-clock UTC, not monotonic, so they can be compared
       with the stored timestamps.
   - **Within the cooldown (1 h for everything, 15 min for one) and `force` false:** raise
     `CheckRequestError` with a new `confirm_required=True` flag, plus `retry_after` and
     `ago_seconds`.
   - **With `force=True`:** queue the check whatever the cooldown.
   - **A run already pending or in progress:** don't queue a second one. Return normally,
     with a message along the lines of "A check is already running; the result shows here
     when it ends". This is the only guard against double clicks.
2. **Session routes (`_check_now_json` and the two routes):**
   - Accept `force` as `request.form`, a JSON body `{"force": true}`, or `?force=1`.
   - When confirmation is required, answer **409** with JSON
     `{"ok": false, "confirm_required": true, "ago_seconds": N, "ago_text": "27 minutes ago", "message": "<the full sentence above>"}`.
   - Write `ago_text` in plain words: "less than a minute ago", "1 minute ago", "27
     minutes ago".
   - Every other refusal stays as it is.
3. **Page script (`static/js/image_update.js`):** on a 409 with `confirm_required`, show
   the confirmation, using `window.STDSettingsUI?.confirm`, or whatever global
   `settings/ui.js` exposes, with a fallback to `window.confirm(message)`.
   - **On OK:** POST again with `force=1` and toast the result.
   - **On Cancel:** do nothing; no toast is needed.
   - Keep the existing behavior for every other answer.
4. **Management API and MCP are unchanged:** `force` is not added there. They keep
   answering 429 with `Retry-After` inside the cooldown, so the wire contract and
   `API_REVISION` don't change. Make sure that path still works on the new wall-clock
   bookkeeping.
   - Record in `docs/decisions.md` that the confirmation is UI-only and why: the API has
     no human to confirm, and a script hammering the registries is the case the cooldown
     exists for.
5. **Tests**, in `tests/test_image_updates.py` / `tests/test_image_updates_ui.py`, or
   wherever the current Check now throttle tests are. Update the ones that expect a 429
   from the session routes. Cover:
   - **Session routes, everything:** the first request gives 202. A second within the
     hour gives 409 with `confirm_required` and a sane `ago_text`. The same request with
     `force=1` gives 202.
   - **Session routes, one entry:** the same flow on the 15-minute cooldown.
   - **Persisted last run:** a last run 27 minutes old, with no in-memory request (as
     after a restart), still asks for confirmation. One 2 hours old doesn't.
   - **Pending run:** a run already pending gives "already running", not a second
     queue.
   - **Management API:** still 429 with `Retry-After` inside the cooldown.
   - **Script check (optional):** `node --check static/js/image_update.js`.
6. **Docs, all in the same commit:**
   - **CHANGELOG:** add an `[Unreleased]` → `### Changed` entry: "Check now always
     works; within an hour of the last check (15 minutes for one image) it asks you to
     confirm, because registries limit anonymous requests." Keep the existing Fixed
     entry.
   - **PRD §24:** update the Check now and throttle text and the Settings line, and add
     a revision-history row (0.104).
   - **README:** update the "throttled to once an hour…" line (~L380).
   - **`docs/decisions.md`:** the entry from step 4.
7. **Verify:** `uvx ruff@0.15.17 check .` is clean, and
   `uvx --with-requirements requirements-dev.txt pytest -q` passes in full.

## Conventions to honor

- No migration and no wire-contract change. If you find you need one, stop and report.
- Write host checks as `urlsplit(url).hostname == ...` (CodeQL).
- No `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file with a plain `mv` (it's untracked) into `prompts/done/` or
   `prompts/failed/`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. **You are a spawned agent: do not commit.** Report back:
   - the full file list, including the scheduler fix files and this prompt in
     `prompts/done/`;
   - a proposed one-line message (e.g. `fix: image update check runs from the
     scheduler; Check now asks to confirm within the cooldown instead of refusing`);
   - the lint and test results;
   - any deviations from this prompt.
