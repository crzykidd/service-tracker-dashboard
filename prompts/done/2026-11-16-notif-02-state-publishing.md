---
name: 2026-11-16-notif-02-state-publishing
status: completed
created: 2026-11-16
model: sonnet
completed: 2026-11-16
result: Retained MQTT state publishing (entry, check, summary) with change detection, full_sync reconcile and tests; docs updated.
---

# Task: Publish check and roll-up state changes to MQTT (retained)

Use the notif-01 publisher to send per-check state, per-entry roll-up state
and summary counts to MQTT as **retained** messages. Publish only when a state
changes, and republish the full set on every (re)connect.

## Before you start

- notif-01 (`prompts/done/2026-11-16-notif-01-channel-framework-and-mqtt.md`)
  must be completed. If it isn't, stop and report.
- Read `CLAUDE.md` and the `docs/PRD.md` §17 "Next release —
  Notifications: MQTT and Home Assistant".
- Read `jobs.py`:
  - `record_check_result()` is the single write path for check results,
    including container checks via `run_container_checks`;
  - the health loop's `tick()` does the DB writes on one thread.
- Read `health_state.py` `entry_health()`, the roll-up rule. Reuse it; don't
  re-implement it.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Topics** (`<base>` is the channel's `base_topic`, default `std`). Use
   ids, not names, so renames never move topics.
   - `<base>/status`: `online`/`offline`, already done in notif-01.
   - `<base>/entry/<entry_id>/state` (retained). JSON fields:
     - `state`: `up|degraded|down|unknown|none`;
     - `entry_id`, `name`, `host`, `group`, `source`;
     - `dashboard_url`: the absolute URL if a base URL is known, else a
       path;
     - `since`: when the state last changed;
     - `checks`: a count by state.
   - `<base>/entry/<entry_id>/check/<check_id>` (retained). JSON fields:
     - `ok`, `state`;
     - `check_type`, `target`, `name`/label;
     - `latency_ms`, `status_code`, `message`;
     - `consecutive_failures`;
     - `last_checked_at`, `last_change`.
   - `<base>/summary` (retained): `{up, degraded, down, unknown, none,
     total}` over active entries.
   - Write the topic and payload shapes in the PRD; they become a public
     contract.
2. **Change detection.**
   - In `record_check_result()`, or right after it in the same thread,
     compare the previous `last_ok` with the new result:
     - an `ok` change → enqueue a check event;
     - the first ever result (previous `None`) counts as a change.
   - After the tick's writes commit, recompute `entry_health()` for the
     affected entries. If the roll-up differs from the last *published*
     roll-up (an in-memory map in the publisher), enqueue an entry event
     and a summary event.
   - Build the dicts on the scheduler thread, then enqueue (non-blocking).
     Never pass ORM objects across threads.
   - Also publish when an entry's checks are added, removed or edited (the
     roll-up may change), and when an entry is soft-deleted, restored or
     purged.
3. **Reconcile instead of chasing every delete path.**
   - Implement `full_sync()`. It builds the desired set of
     entry/check topics from the DB (active entries only) and publishes all
     of them retained.
   - It publishes an **empty retained payload** to any previously
     published topic that is no longer desired. That clears entries or
     checks that were deleted or soft-deleted.
   - Persist the published-topic set (e.g. JSON in the `Setting` store, or
     a small table; your call, record it) so cleanup still works after a
     restart.
   - Run `full_sync()` on every MQTT (re)connect (the notif-01 `on_connect`
     hook), after channel config changes, and on a light periodic safety
     net (e.g. every 10 min, or as a scheduler job; record the choice).
   - Mutation paths (UI edit/delete, management API, purge job) just call a
     cheap `notify.request_sync()`, debounced in the publisher thread.
4. **Options.** "Publish every result" is NOT in scope (operator decision:
   state changes + retained only). Leave a note in `docs/FUTURE.md`.
5. **Tests**, using the fake paho client:
   - the first result publishes;
   - an unchanged result doesn't publish;
   - an ok → fail change publishes the check, entry and summary;
   - the roll-up uses `entry_health`;
   - full sync on connect publishes every entry and check;
   - a deleted or soft-deleted entry gets an empty retained payload on
     sync;
   - the published set survives a "restart" (a new publisher instance);
   - a rename keeps the topic;
   - a disabled channel publishes nothing;
   - the checker path never blocks when the queue is full.
   - `ruff check .` and `pytest -q` must pass.
6. **Docs (same change).**
   - `CHANGELOG.md` `[Unreleased]`.
   - `docs/PRD.md`: the topic/payload contract; mark the step Delivered;
     bump the revision history.
   - `README.md`: a topic table plus an example `mosquitto_sub -t 'std/#' -v`.
   - `docs/decisions.md`.

## Conventions to honor

- No network I/O on the checker/scheduler threads; enqueue only.
- Retained everywhere except `<base>/test`.
- Commit prefix `feat:`. No `Co-authored-by:` trailers.

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
