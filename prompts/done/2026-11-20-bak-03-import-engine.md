---
name: 2026-11-20-bak-03-import-engine
status: completed        # pending | completed | failed
created: 2026-11-20
model: sonnet
completed: 2026-11-20
result: importer.py (parse, plan, fingerprint, apply, staging), export_format.from_legacy, User.has_password; 40 tests in tests/test_import_engine.py; decisions recorded under bak-03
---

# Task: Backup phase 3: import engine (parse v1 + legacy v0, matcher, plan/apply), no UI

Build the import engine that bak-04 puts a UI and API on. It parses v1 exports and
legacy YAML entry lists, matches every record against the current database, returns a
pure dry-run plan with per-record status and per-field "missing" / "differs" diffs, and
applies a selection in one transaction after re-planning and checking a fingerprint.
**No routes, no templates, no UI in this phase.** The tests are the deliverable's
proof, so they must be exhaustive.

**Depends on:** bak-02 (`export_format.py` with the v1 models and `build_export`).

## Before you start

- Read `CLAUDE.md` (Database Rules; Register Contract Rules: URL provenance order,
  capture columns; Inventory Stream Ingest Rules: stream entries are never touched by
  register adoption, `find_duplicate` sees them; locks).
- Read the design doc **in full**, with particular care for §5.3, §6 (all matching rules),
  §7 (engine), §9 (legacy) and §17 decisions (final):
  `docs/design/2026-11-20-backup-export-import.md`.
- Code, read closely:
  - `routes_api.py` register (the lookup by exact `(host, container_name)`, `source !=
    stream`, active first then lowest id; locked → skipped; manual → adopted; deleted →
    restored; `user_wins` / `notifier_wins`; URL provenance) and `_UPSERT_LOCK`;
  - `streams.py` (`plan`, `_entry_tokens` / `_name_tokens` link-offer matching,
    `_convert`, `soft_delete_entry`, `link_entry`, `normalize_mac`, `clean_default_checks`,
    `_clean_filter`, `_LOCK`);
  - `routes_mgmt_api.py` (`_UPSERT_LOCK` taken before `streams.unlink_entry`: the lock
    order this engine uses);
  - `entry_rules.py` (`find_duplicate`, `get_or_create_group`), `check_form.py`
    (validators), `models.py` (`ensure_url_checks`, `ensure_container_check`, fresh
    values), `notify.py` (`validate_config`, `request_reload`; `create_channel` /
    `update_channel` commit, so they are **not** called), `notify_state.py` (the commit
    listener), `settings_store.py`, `routes_dashboard.py` (`_restore_checks` legacy
    mapping, `restore_deleted_entry` clash check), `routes_auth.py` (`login`), werkzeug
    `check_password_hash`.

## Working tree check

Run `git status --porcelain`. If any file this plan modifies has uncommitted changes
(`export_format.py`, `backups.py`, `CHANGELOG.md`, `docs/PRD.md`, `CLAUDE.md`, the tests
named here), list them and stop to ask. New files are not a conflict. This file is exempt.

## What to do

1. **`export_format.from_legacy(records) -> (ExportDoc, warnings)`** per design §9:
   source rule, `source: stream` with `mac` → a v0 stream identity (no stream id; the
   matcher tries all `mac` streams), `group_name` → group, URL inclusion rule, checks or
   the legacy fields (reuse the `_restore_checks` mapping logic as a pure function),
   widget without its key (with the clear-text-key warning), `deleted_at` → a flag that
   makes the row *Deleted in file*.
2. **`importer.py`** (new; add it to the CLAUDE.md module layout):
   - `parse(raw: bytes, filename) -> ParsedDoc`: size ≤ 10 MB, JSON by content or
     extension, YAML via a `SafeLoader` subclass that rejects anchors and aliases, list →
     v0, mapping without `format: std-export` → error, `format_version` > 1 → error
     (§5.5 message), unknown keys → warnings, per-record validation errors → *Invalid*
     rows (not a whole-file failure), record caps (§7.4).
   - `plan(doc, stream_map=None) -> ImportPlan` (design §7.1 dataclasses), **pure**.
     It reads only and opens no locks. It loads each table once and diffs in Python
     (like `streams.plan`). It implements every rule in §6: statuses §6.1, fresh values
     §6.2 (incl. `notifier_reported_*`, URL provenance, `name_source`, checks by kind /
     `(check_type, name)`, `notifier_wins`), entry matching §6.3 (incl. linked entries,
     open link offers, the manual fallback, the duplicate hint, soft-deleted local),
     groups / widgets / channels (namespace keys never applied) / users (never modified)
     / settings §6.4, stream mapping §6.5 (auto by id, same `key_type`, one target once,
     not-present → *Waiting*), streams and blocks §6.6. Row ids (`rid`) are stable strings
     (§7.1).
   - `fingerprint(plan, selection, stream_map) -> str` over the selected rows only
     (§7.2).
   - `apply(doc, stream_map, selection, mode, fingerprint, actor) -> ImportResult`:
     takes `routes_api._UPSERT_LOCK`, then `streams._LOCK`; re-plans; on a fingerprint
     mismatch raises `ImportStale(plan)` and writes nothing; otherwise writes in the §7.3
     order in **one transaction**. It writes rows directly with the shared non-committing
     helpers and validators. Import as new follows §7.5 exactly (manual entry, never
     `is_static`, `find_duplicate` refusal, stream records with `host = pre_link_host`).
     The `soft_delete_entry` block option. New users with `password_hash = "!unset"`
     (§7.6). New channels disabled when `secret_set`. Never writes a secret, never
     answers a link offer, never changes a stream's status or creates a stream. Rollback
     on any error (`ImportError` with the message). After commit: `notify.request_reload()`
     if channels changed, `jobs.reschedule_backups(app)` if backup settings changed. It
     returns the §7.7 summary including "still to do". It logs one INFO line (§7.8).
   - **Staging store** for bak-04's UI: `stage(parsed, user_id) -> token`,
     `load(token, user_id)`, `discard(token)`, `prune_expired()` in
     `<CONFIG_DIR>/import-staging/` (JSON, 60 min TTL, bound to the user id).
     `backups.run_snapshot` (or the export job) calls `prune_expired()`.
3. A tiny addition to the Users data only if needed for tests (e.g. a `User.has_password`
   property true unless the hash is the sentinel). bak-04 shows the tag.

## Tests (new `tests/test_import_engine.py`, plus fixtures under `tests/fixtures/`)

Build a fixture helper that seeds a realistic source DB (Docker entries through the
register endpoint with labels, `ui_edit` URLs, groups, sort priorities, checks, locked
entries, `ha_publish`; a manual host-less entry; a `mac` stream with an ingest key,
enabled, items, a renamed item, a linked manual entry, blocks, filters, default checks,
missing expiry; a widget; an MQTT channel with a password; two users; exposure and update
settings), then exports it, **wipes** the DB (`drop_all` / `create_all` or a fresh
temp `CONFIG_DIR` app) and re-creates the base entries the way a new install would
(register again with the same payloads; the sidecar PUTs a snapshot to a new stream with
a new ingest key; enable).

Cover at least:
- Full scenario: plan → the expected status per row (Docker *missing*, stream rows
  *Waiting* while the stream is pending, then *missing* after enable) → apply (fill) →
  every operator field equals the source → **re-plan: every row identical or Waiting**
  (idempotency) → a third apply changes nothing.
- Fill vs overwrite: a *differs* field is not written in fill mode, and is written in
  overwrite mode only when its field box is selected. Never-applied fields (channel
  namespace keys, existing users) are not written in either mode.
- Fresh-value rules: a notifier-reported group counts as missing; a local
  `explicit_label` URL is *differs*; a synthesized URL is missing and gets imported as
  `ui_edit` (a later register with an explicit label does not overwrite it);
  `notifier_wins` excludes group / sort priority.
- Ambiguous: two active entries with the same `(host, name)` → *Ambiguous* with both
  candidates; apply with a picked `target_id` writes only that one. Group case-near-match.
- Soft-deleted local → *Matched — deleted locally*; apply with `restore` restores and
  fills; the clash with an active twin → *Conflict*.
- Import as new, Docker: creates a manual entry with `is_static` false even when the
  file says locked; then a register for that `(host, name)` **adopts** it (source
  notifier, group kept); a re-plan shows `is_static` missing.
- Import as new, stream record: a manual entry; then a snapshot with that item on the
  enabled stream creates a **link offer** for it (`StreamLinkOffer` row); accepting
  links it; a re-plan matches by `(stream, key)`. A renamed record whose name does not
  match gets no offer (documented limitation).
- Open link offer: a stream record whose key has an offer is matched to the offered
  manual entry, and import does not accept the offer.
- Stream mapping: auto by id; a remap to another same-`key_type` stream; a different
  `key_type` refused; a missing stream → *Waiting*; stream settings and blocks apply to a
  **pending** stream; status never changes; a block for a key with an existing entry and
  the soft-delete option.
- Users: created with no usable password (`check_password(x)` False for several x;
  `POST /login` fails); an existing user is untouched even in overwrite mode; an email
  clash → *Conflict*.
- Channels: created disabled when `secret_set`; `secret` stays NULL; `validate_config`
  errors → *Invalid*.
- Stale plan: plan, then change a selected entry (or register a new container that turns
  a not-found row into a match), then apply with the old fingerprint → `ImportStale`,
  nothing written. An unrelated observed change (`docker_status`) does **not** make it
  stale.
- Transaction: force an exception mid-apply → nothing written.
- Legacy v0: a fixture built from `to_dict()` of the seeded DB (the scheduled format, no
  `group_name`) and one with `group_name` (the UI format); widget keys ignored with the
  warning; a stream record matched by MAC; `deleted_at` rows unselected by default; the
  pre-0.7 legacy check fields mapped.
- Parse limits: > 10 MB, a YAML alias, `format_version: 2`, unknown keys → warning, a
  mapping that is not an export.
- `pytest -q` and `ruff check .` pass.

## Docs (same commit)

- **CHANGELOG:** nothing operator-visible yet. Add no entry. bak-04 adds the import
  entry. Record the phase in `docs/HISTORY.md` only if that file tracks internal phases.
  Otherwise skip it.
- **PRD:** in the planned section, describe the matching rules and plan/apply handoff
  as implemented (still "Planned": not operator-visible until bak-04). Revision-history
  row. If nothing in the PRD needs changing beyond that, say "PRD reviewed" in the report.
- **CLAUDE.md:** module layout gains `importer.py`.

## Conventions to honor

- No routes, no templates, no API, no MCP. No schema change (the sentinel hash fits the
  existing column). No secrets written.
- Every multi-row write is in the one transaction. Lock order `_UPSERT_LOCK` →
  `streams._LOCK`.
- Commit style: `feat:` (the engine is the feature's core; operator-visible in bak-04)
  or `refactor:` if you judge nothing is reachable. Prefer `feat:` with the CHANGELOG
  note deferred to bak-04. No `Co-authored-by:`.
- Non-obvious calls → `docs/decisions.md` (heading "bak-03").

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (or `prompts/failed/`): `git mv` if tracked,
   otherwise plain `mv`.
3. You are a spawned agent: **do not commit, do not push, never `git add -A`.** Report
   back the file list, the proposed message `feat: import engine for v1 exports and legacy
   YAML (match, dry-run plan, apply with fingerprint) (backup phase 3)`, the test
   result, and any design rule you could not implement as written (with the reason).
