---
name: v090-04-groups-save-all
status: completed
created: 2026-11-16
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-16
result: Settings → Groups saves the whole table via POST /settings/groups/save with all-or-nothing validation, delete-on-save, and an unsaved-changes guard; per-row priority-wipe bug fixed; 690 tests pass, ruff clean.
---

# Task: Settings → Groups saves the whole page, warns on unsaved changes

Today each row of Settings → Groups has its own Save button. The operator
wants one **Save** for the whole table, and a browser "leave page?" prompt when
there are unsaved changes. This is the fourth chunk of v0.9.0. Run it after
`v090-03` (API key rotate), which also edits `templates/settings.html`.

## Before you start

- `CLAUDE.md`. Code: `templates/settings.html`, the `section-groups` block
  (around line 369) and its `sortTable` JS; and the `update_group`,
  `add_group` and `delete_group` routes in `routes_dashboard.py` (around line
  775).
- Look at `entry_rules.py` and the management API group routes in
  `routes_mgmt_api.py` for the group-name rules already in use. Reuse them,
  don't add a third copy. If there's no shared helper yet, factor one out
  (e.g. in `entry_rules.py`) and point the API and this form at it.
- **Existing bug, fix it here:** each row's per-row Save is its own `<form>`
  that only carries `group_id`. The name, icon and priority inputs sit in a
  *different* form (one that spans `<td>`s, which is invalid HTML). So
  clicking Save sends no fields, and `update_group` sets
  `group_sort_priority` to None. Confirm this with a test first, then the
  rewrite removes it. Note it in CHANGELOG → Fixed.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **One form.**
   - Wrap the whole groups table in a single `<form method="POST">` to a new
     route, `POST /settings/groups/save` (admin, CSRF).
   - Each existing row posts indexed fields: `group-<id>-name`,
     `group-<id>-icon`, `group-<id>-priority` and `group-<id>-delete`
     (a checkbox or hidden flag).
   - The "new" row becomes optional `new-name`, `new-icon` and
     `new-priority`. It's ignored when the name is blank, so drop `required`.
   - Put one **Save changes** button below the table (and optionally above),
     plus a **Discard** link that reloads the section.
   - Remove the per-row Save buttons and the nested per-row forms.

2. **Delete applies on save.**
   - The per-row Delete button becomes a toggle. It marks the row for
     deletion (strike-through or dimmed, with an "Undo" option) and makes the
     form dirty; the delete happens on Save.
   - Rows with active entries keep no delete control, the same rule as
     today.
   - The server re-checks this rule, because entries may have changed since
     the page loaded.
   - Soft-deleted entries are detached, exactly as `delete_group` does now.

3. **Route `save_groups`.**
   - Validate the whole submission before writing anything:
     - names are non-empty and unique across the resulting set, so a swap
       like A↔B in one save works, and so does a new group taking a name
       freed by a deleted row;
     - priorities are blank or an integer, and negative numbers are allowed
       if the model allows them (check how the dashboard sorts);
     - every group id still exists;
     - a delete-marked row has no active entries.
   - On any error, apply nothing.
     - Re-render Settings on the groups section with the operator's
       submitted values still in the inputs and per-row error messages.
     - Don't redirect: the input must not be lost.
     - Return status 400.
   - On success, apply all the changes in one transaction and flash a
     summary such as "Saved: 2 updated, 1 added, 1 deleted". If nothing
     changed, flash "No changes", then redirect to `section=groups`.
   - Keep `update_group`, `add_group` and `delete_group` working only if
     something else uses them (grep the templates, JS and tests). Otherwise
     remove them, along with their tests or by moving those tests over.

4. **Unsaved-changes warning.**
   - Add a small vanilla JS module, `static/js/unsaved_guard.js`, with no
     dependencies. Given a form, it snapshots the form's values on load and
     marks the form dirty when the current values differ. It compares
     against the snapshot, so typing a value and then reverting it counts as
     clean.
   - While the form is dirty:
     - a `beforeunload` handler asks for confirmation. Browsers show their
       own generic text; set `returnValue` anyway;
     - the Save button looks highlighted and an "Unsaved changes" hint shows
       next to it.
   - Submitting the form itself must not trigger the prompt: disarm the
     guard on `submit`.
   - Settings tabs switch client-side (`showSection`), so switching tabs
     doesn't lose input and needs no prompt. Any real navigation, including
     submitting another section's form or clicking a nav link, triggers the
     browser prompt.
   - When the page re-renders after a validation error, start it dirty
     (compare against the values from the DB, or set a flag from the
     template), so the operator is still protected.
   - Write it generically (`data-unsaved-guard` on the form), but apply it
     only to the groups form in this task.

5. **Keep the existing column sort** (`sortTable`) working with the new
   markup, or note why it can't.

6. **Tests:**
   - Save with several rows updated at once.
   - Add, plus update, plus delete in one save.
   - The name-swap case.
   - A duplicate name gives a 400, nothing is written, and the submitted
     values are re-rendered.
   - A priority that isn't a number gives a 400.
   - Deleting a group that gained an active entry is refused with a 400.
   - A stale or unknown group id.
   - A non-admin is refused, and CSRF is enforced, matching the existing
     patterns.
   - The old priority-wipe bug is gone.
   - JS:
     - if the repo has no JS test setup, do a headless Playwright check
       (the scratch venv at
       `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`
       has Playwright);
     - edit a field → the `beforeunload` prompt is armed (check via
       `page.on('dialog')`, or the handler's `returnValue`);
     - revert the edit → disarmed;
     - submit → no prompt.
   - Stop any server you start, by PID.

7. **Docs** (same commit):
   - `CHANGELOG.md` `[Unreleased]`:
     - Changed: Settings → Groups now has a single Save, deletes apply on
       Save, and you're warned before leaving with unsaved changes;
     - Fixed: the per-row Save cleared a group's priority.
   - `README.md` if it describes the groups settings.
   - PRD: check whether a settings/groups section describes per-row saves.
     Update it and bump the revision history, or say "PRD reviewed, no change
     needed".
   - Add `static/js/unsaved_guard.js` to the Module Layout `static/` notes
     only if CLAUDE.md lists individual JS files (it doesn't today, so
     probably no change).

8. **Verify:**
   - `uvx ruff@0.15.17 check .`
   - The full suite on 3.11:
     `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`

## Conventions to honor

- No new JS libraries. Tailwind classes matching the page.
- Server-side validation is authoritative; the JS is a convenience.

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
   Either way: never `git add -A`, never push, never auto-commit. Branch is `dev`;
   message prefix `feat:`; no `Co-authored-by:`.
