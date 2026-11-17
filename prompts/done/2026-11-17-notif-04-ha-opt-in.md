---
name: 2026-11-17-notif-04-ha-opt-in
status: completed
created: 2026-11-17
model: sonnet
completed: 2026-11-17
result: ha_publish opt-in per entry with bulk picker, host in HA device names, tests and docs updated
---

# Task: Home Assistant discovery becomes opt-in per entry (default: not published)

The operator turned on "Add to Home Assistant" and got ~50 HA devices they
didn't want. Change the per-entry model from **opt-out** (`ha_exclude`,
default false = published) to **opt-in**: an entry is published to HA only
when its "Publish to Home Assistant" box is ticked. Existing and new entries
default to **not** published. Add a bulk picker so the operator can tick a
handful of entries at once.

## Before you start

- Read `CLAUDE.md` and PRD §17.1 and §17.4.
- Read the 2026-11-16 notif-03 entry in `docs/decisions.md`, plus
  `notify_ha.py`, `notify_state.py` (commit listener `_ENTRY_ATTRS`),
  `models.py`, and migration `alembic/versions/d8e2a6f4b915_ha_exclude.py`.
- notif-03 shipped on `dev` only (commit 8bd2233) and is unreleased, so no
  release carries `service_entry.ha_exclude`. Still use a **new forward
  migration**; never edit `d8e2a6f4b915`, because the operator's dev
  database has already run it.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

### Operator decision (2026-11-17, binding)

- **Entries:** opt-in. New column `service_entry.ha_publish` (bool, NOT NULL,
  default false). After the migration, **every existing entry is false**,
  whatever its old `ha_exclude` value was. The operator wants a clean slate.
  Drop `service_entry.ha_exclude` in the same migration, using batch mode for
  SQLite. The downgrade restores `ha_exclude` (false) and drops `ha_publish`.
- **Checks:** keep `health_check.ha_exclude` (opt-out) unchanged. Inside a
  published entry, checks publish unless excluded.
- The channel-level "Add to Home Assistant" box stays as the master switch.
  The hub device (connectivity + counts) publishes whenever the master
  switch is on, even if no entry is opted in.

### Steps

1. **Migration and model**, as above. Run `alembic upgrade head` then
   `alembic check` with a single head. Add a migration test (existing entries
   come out with `ha_publish` false; downgrade works).
2. **Discovery** (`notify_ha.py`): an entry's device and entities are
   desired only when `entry.ha_publish` is true (and the entry is active, its
   checks are not excluded, and the master switch is on). Unticking it clears
   the device's configs through the existing reconcile, with an empty
   retained payload.
3. **Commit listener** (`notify_state.py`): watch `ha_publish` instead of
   the entry `ha_exclude`.
4. **UI.**
   - **Edit and Add pages:** replace "Exclude from Home Assistant" with
     **"Publish to Home Assistant"** (unchecked by default). Add it to the
     Add Entry page too, which notif-03 left out. Keep the hidden-marker
     pattern so a form without the field doesn't change the stored value.
   - **Settings → Notifications:** add a **"Home Assistant entries"** panel,
     shown when any channel has discovery on, or always with a hint:
     - a table of active entries (name, host, group) with a Publish
       checkbox, a filter box, and "Select all" / "Select none";
     - one Save that applies all changes (CSRF, the unsaved-changes guard,
       and one commit, so one sync).
   - Per-check "Publish to Home Assistant" toggles are unchanged.
5. **Register:** must never touch `ha_publish`. Replace the notif-03
   `ha_exclude` preservation test with an `ha_publish` one.
6. **Management API / MCP:**
   - **Entries:** replace the `ha_exclude` field with `ha_publish` in the
     schemas, serializers, OpenAPI and MCP `update_entry`. Add it to
     `create_manual_entry` too.
   - **Checks:** keep `ha_exclude`.
   - **Compatibility:** the field change on entries is fine without a shim
     because nothing released carries `ha_exclude`.
7. **Backup/restore:** include `ha_publish` (entries) and `ha_exclude`
   (checks) in whatever `to_dict` / `to_config` / restore paths carry other
   operator-owned entry and check fields. notif-03 left this gap.
8. **Tests:** update `tests/test_ha_discovery.py` and any other
   `ha_exclude`-on-entry tests. Cover:
   - default false, meaning no entry devices but the hub is published;
   - opting in publishes, and opting out clears;
   - the bulk Save publishes and clears in one sync;
   - an Add Entry form with the box ticked;
   - API read/write;
   - backup round trip.

   `uvx ruff@0.15.17 check .` and `/tmp/claude-1000/venv/bin/pytest -q`
   must pass.
9. **Docs (same change):**
   - **CHANGELOG `[Unreleased]`:** edit the existing notif-03 HA entry
     rather than adding a contradicting one. Nothing is released, so the
     operator-facing text should just describe opt-in.
   - **PRD:** in §17.1, change the decision bullet to opt-in per entry and
     note the 2026-11-17 change. Update §17.4 and §5.9, and add revision row
     0.67.
   - **README:** update the Home Assistant section; describe the bulk
     picker.
   - **`docs/decisions.md`:** a new top entry explaining why
     (50 unwanted devices; opt-in is the safe default) and the clean-slate
     migration.
   - Do not use docker. The Docker daemon on this host is misbehaving.

## Conventions to honor

- New forward migration only; never edit a migration that has run.
- Commit prefix `feat:`. No `Co-authored-by:` trailers.
- Before reporting, check every doc change you claim with grep or
  `git diff`.

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
