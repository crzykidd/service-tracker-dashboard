---
name: 2026-11-17-inv-03-source-refactor
status: completed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: is_docker added, not-Docker branches switched, filters and restore generalised; ruff + pytest green
---

# Task: Refactor "not manual" branches to `is_docker` (no behaviour change)

Build PRD §18.3. This prepares the code for a third `source` value (`stream`,
inv-04) without changing anything an operator sees.

## Before you start

- inv-02 must be completed. If it isn't, stop and report.
- Read `CLAUDE.md`, PRD §18.3, design doc
  `docs/design/2026-11-17-network-inventory-and-profiles.md` §5.1, and
  `models.py` (`SOURCE_*`, `VALID_SOURCES`, `is_manual`,
  `is_docker_status_stale`, `ensure_container_check`, `check_counts`).
- Find every branch: `grep -rn "is_manual\|SOURCE_MANUAL\|SOURCE_NOTIFIER\|source ==\|source !=" --include='*.py' --include='*.html' --include='*.js' .`
  (excluding tests and alembic).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. Add `ServiceEntry.is_docker` (`source == SOURCE_NOTIFIER`).
2. Classify each branch. For each, decide "means not Docker", "means
   operator-made" or "already correct". Switch the "not Docker" ones to
   `is_docker`. Known ones:
   - `tiled_dash.html` (Docker pill and container fields);
   - `edit_entry.html` (container section);
   - `dashboard.html`;
   - `models.py` (the `is_manual or is_static` guard);
   - `notify_ha.entry_device` model string. Keep "Manual" / "Docker container"
     for now, structured so inv-04 can add the stream's display name.

   Keep `is_manual` where it means operator-made (the Name label, the management
   API rule that only manual entries may change name and host).
3. Generalise the source filters so any value in `VALID_SOURCES` filters exactly,
   and unknown values fall back to `all`:
   - `view_helpers.normalize_source_filter` / `matches_source`;
   - the `source` query on `GET /api/v1/entries` in `routes_mgmt_api.py`.
4. Restore (`routes_dashboard.py` restore loop): an unknown `source` in a backup
   is restored as manual. Keep the host-required rule only for `notifier`.
5. Tests:
   - the whole suite must pass unchanged;
   - add tests for `is_docker`, the filters with every `VALID_SOURCES` value, and
     restore of an unknown source.
6. Docs:
   - `docs/decisions.md`: a short entry listing each branch and how it was
     classified;
   - PRD §18.3 marked delivered;
   - no CHANGELOG entry (no operator-visible change). Use the `refactor:` prefix.

## Conventions to honor

- CLAUDE.md "Always — Definition of Done":
  - add a CHANGELOG `[Unreleased]` entry in operator language (not for a
    refactor-only change);
  - mark the PRD subsection "Delivered on `dev`" with an "As built" note for any
    deviation, and add a revision-history row;
  - update README where operator-facing behaviour changes.
- Lint with CI's pinned ruff, `uvx ruff@0.15.17 check .` (other versions disagree
  on import sorting). Run the full suite with `pytest -q`. Both must be green.
- Every new management route is registered in `mgmt_openapi.OPERATIONS` (tests
  enforce it) and gets MCP tools in `mcp/std_mcp.py` (read key: read tools only).
- Schema changes only through Alembic, with FK indexes in the same migration.
  `Migration check` (one head, upgrade on an empty DB) must pass.
- Keep the register contract and its safe-degradation guarantees intact
  (CLAUDE.md "Register Contract Rules").
- In your report, only claim doc edits that `git diff` shows.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure).
3. Record any non-obvious decisions in `docs/decisions.md` (newest at top).
4. Do **not** commit. Prepare the working tree, then report back to the
   orchestrating session:
   - the file list (this prompt file and its move included);
   - a one-line commit message with the right prefix (`feat:` / `fix:` /
     `refactor:` / `docs:`), no `Co-authored-by:`;
   - test and lint results;
   - anything you deviated from or left undone.
   Never `git add -A`, never push.
