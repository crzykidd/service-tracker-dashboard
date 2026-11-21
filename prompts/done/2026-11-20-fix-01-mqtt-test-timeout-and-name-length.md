---
name: 2026-11-20-fix-01-mqtt-test-timeout-and-name-length
status: completed
created: 2026-11-20
model: sonnet
completed: 2026-11-20
result: MQTT test bounded to ~5 s; container_name widened to 128 (migration d7a3e9b2c418); no API revision bump; lint and tests green
---

# Task: 0.10.2 fixes — shorter MQTT test timeout, 128-char entry names

Two small fixes for 0.10.2: (A) the notification channel Test button can block a
request thread ~13 s against a broker that doesn't answer; (B) `service_entry.container_name`
is `String(100)` while the stream ingest contract (PRD §18.5, `mgmt_schemas.py`
`StreamSnapshotItem.name`/`key` = `_text(128)`) allows 128-char names.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Database Rules, commit rules), `docs/PRD.md`
  §5 (schema; find the `service_entry` table/column notes and §5.10), §17 (notifications,
  search for "Test" / `test_connection`), §18.5, and the newest entries of
  `docs/decisions.md` (the "Known-gap triage after v0.10.1" entry lists these two fixes;
  the notif-01 entry around "up to ~13 s" explains why the test runs on the request thread).
- Lint with CI's pinned ruff: `uvx ruff@0.15.17 check .`.
  Tests: `uvx --with-requirements requirements-dev.txt pytest -q`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and stop (report back). Surface unrelated dirty files once as awareness; don't block.
This file (the handoff prompt itself) is exempt.

## What to do

### A. MQTT test timeout (`notify_mqtt.py`)

`test_connection()` waits `TEST_TIMEOUT_SECONDS = 8` for connect, then
`PUBLISH_WAIT_SECONDS = 5` for the publish (8 + 5 = the ~13 s). It runs on a request
thread by design — keep that.

1. Bound the **total** test to a short budget (target ~5 s overall: e.g. connect wait
   ~4 s, publish wait = whatever remains, minimum 1 s). Use test-specific constants;
   do NOT change `PUBLISH_WAIT_SECONDS` if the live publisher path (line ~247 /
   other callers) depends on it — check its uses first and introduce a separate
   constant if needed.
2. If paho's own socket connect can block longer than the wait (connect_async +
   loop_start should not block the caller, but confirm), make sure the function
   still returns within the budget; the `finally` disconnect/loop_stop must not
   re-introduce a long block (check `loop_stop` behavior on a client still trying
   to connect; if it can hang, stop the loop without joining or otherwise bound it).
3. Keep the messages operator-friendly ("No answer from host:port within N seconds.").
   Update the docstring ("Blocks up to ~13s").
4. Tests: extend the existing MQTT test-connection tests (find them in `tests/`, they
   use a fake client `factory`) to assert a non-answering broker returns `False`
   within the budget (patch the constants small or measure with a fake that never
   calls back), and that the success path still works.

### B. 128-char entry names

1. New Alembic migration widening `service_entry.container_name` to `String(128)`.
   Use `op.batch_alter_table` (SQLite) like the existing migrations; chain it off the
   current head (`alembic heads`; last is `c6f2a8d4e157` per PRD §5.10 — verify).
   Downgrade narrows back. The composite index `ix_service_entry_host_container_name`
   must survive the batch rebuild (verify after upgrade). Also widen `pre_link_host`
   only if it can hold a name (it holds a host — leave it unless code copies a name
   into it).
2. Update `models.py`.
3. Audit every place a name length is enforced or assumed and align with 128 where it
   is the entry name: `schemas.py` register `container_name`, `mgmt_schemas.py` entry
   create/update, `entry_rules.py`, `/add` / `/edit` form `maxlength` in templates,
   any truncation in `streams.py`. Do NOT change the register wire contract shape; if
   the register schema currently caps at 100, raising the cap is additive-compatible
   (accepts more) — decide whether it needs an `API_REVISION` bump per CLAUDE.md
   ("Any additive `/api/v1` change bumps `API_REVISION`"). Prefer: no revision bump if
   only an internal DB limit changes and every wire max is already 128; if you widen a
   wire max, record the reasoning in `docs/decisions.md` (a looser max that no producer
   needs to detect arguably isn't a new feature) — do not bump without recording why.
4. Tests: a stream snapshot item with a 128-char name applies and round-trips the full
   name; an entry created/edited with a 128-char name via the management API works;
   129 is rejected where the schema caps it. The migration check: run
   `alembic upgrade head` and `downgrade -1` against a scratch SQLite DB (see how CI's
   `Migration check` job does it in `.github/workflows/ci.yml` and mirror it).

### Docs (same change set)

- `CHANGELOG.md` `[Unreleased]` → `### Fixed`: one operator-facing line per fix.
- `docs/PRD.md`: schema note for `container_name` (128, new migration id), the
  notification test timeout wherever the PRD states it, and a new revision-history
  row (next number after the latest) describing both.
- `README.md` only if it states either limit.
- `docs/decisions.md`: anything non-obvious (timeout split, revision-bump call).

## Conventions to honor

- Doc updates in the same change set as code. No `Co-authored-by:` trailers.
- Lint and full test suite must pass before you finish; report the exact results.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure) — it is untracked, so use plain `mv`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Prepare the working tree, then report
   back: the file list, the proposed one-line message
   (`fix: ...`), lint + test results, and whether the migration upgrade/downgrade was
   verified. Never `git add -A`, never push.
