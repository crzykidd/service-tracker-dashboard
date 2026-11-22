---
name: 2026-11-21-img-02-check-engine
status: completed        # pending | completed | failed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: Engine, API, MCP, register field and docs built; full suite and ruff pass; not committed (orchestrator proposes the commit). See docs/decisions.md 2026-11-21 img-02 entry.
---

# Task: img-02, the image update check engine (back end, API, MCP)

This is phase 2 of the image update check: STD step 1 in design §8, item 2 of §9. It
builds the built-in registry provider and the daily job that checks for newer images. It
also stores the results, accepts the optional `image_info` register field, and exposes
everything through the management API and MCP.

There is **no dashboard or Settings UI** in this phase; that is `img-03`. It ships in
0.12.0.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Database Rules, Register Contract Rules,
  Cross-Repo Coordination and the ordering rule, plus the safe-degradation guarantee) and
  `standards.md`.
- Read `docs/design/2026-11-21-image-update-check.md` in full. §2, §4, §5, §6, §7.3 and
  §8 are the spec.
  - **§14 Decisions are final and override anything earlier in the doc**: default off,
    scope `any`, no credentials, and the provider seam.
  - Open questions Q3, Q4, Q7, Q8 and Q9 take the doc's recommendations:
    - one-component tags use the digest model only;
    - a rebuilt pinned tag gives a muted "rebuilt" note, not `update`;
    - updates stay out of health;
    - no OCI-source fallback for the #6 link;
    - no history table.
- `img-01` already shipped, in commit `cd450dd`:
  - `image_ref.py` (`parse()` and `ImageRef`);
  - the `service_entry.image_ref` column, String(512), indexed. Use it as is, don't
    re-add it.
  - API revision 5 is still unreleased ("next after 0.11.0"). Fold this phase's additive
    changes into that row rather than adding revision 6.
- Patterns to match:
  - `version_check.py`: a cached, backed-off outbound check with a lock.
  - `jobs.py`: APScheduler wiring and `request_run`.
  - `settings_store.py`: DB settings with env > UI precedence.
  - `notify_mqtt.py` / `notification_channel.secret`: the write-only posture. There are
    no secrets in this phase.
  - `routes_mgmt_api.py` + `mgmt_openapi.OPERATIONS`: every new route is registered
    there, and tests enforce it.
  - `mcp/std_mcp.py`.

## Working tree check

Run `git status --porcelain` and cross-reference the files this plan touches. If any have
uncommitted changes, list them and ask before you touch them. Surface unrelated dirty
files once. This prompt file is exempt.

## What to do

1. **Provider seam (§14).** Write a small interface, e.g. `image_updates/` or
   `image_update.py` + `registry_client.py`.
   - The interface: a provider has an id (`registry` for the built-in one) and produces
     per-entry results in the §5.1 state vocabulary. The job iterates over the
     **enabled** providers.
   - Store the provider id with each entry's computed result, e.g. an
     `image_update_provider` column. Then a later What's Up Docker or Komodo provider
     needs no schema change.
   - Only the `registry` provider is built now. Don't over-engineer: one ABC or Protocol
     plus a registry dict is enough.
2. **`registry_client.py`** (§4.1, §4.4).
   - One generic OCI distribution v2 client: the anonymous Bearer challenge flow read
     from `WWW-Authenticate` (no hardcoded realms), and the Docker Hub host mapping
     (`docker.io` → `registry-1.docker.io`).
   - `HEAD` manifests with **all four** Accept media types (§2.3; a test pins the
     header). `tags/list` with `Link` pagination, capped at 10 pages.
   - The token cache, 10 s timeouts (5 s connect), one connection retry, and the
     `User-Agent: service-tracker-dashboard/<version>`.
   - `429` handling: honor `Retry-After` and pause that registry for the rest of the run.
   - No GET-manifest fallback on Docker Hub. Elsewhere, GET + SHA-256 only when HEAD
     returns no digest.
   - Never put raw exception text into stored errors (the CodeQL rule from `d08cf69`);
     use short, fixed messages.
   - Plain HTTPS only. Insecure registries and credentials are out of scope.
3. **Tag model** (§2.2): skeleton/version matching, scope (`any` | `minor` | `patch`),
   classification (`major` | `minor` | `patch` | `build`), and the per-entry
   `image_tag_pattern`.
   - The pattern is validated on save: it compiles, is at most 200 characters, and is
     rejected if it has nested quantifiers. Only tags of at most 128 characters are
     evaluated.
   - Store up to 50 candidates on the reference row, so a scope or pattern change is
     recomputed locally.
4. **Digest model** (§2.3) and the **`image_info` register field**.
   - Add the `ImageInfo` pydantic model (`extra="forbid"`) and
     `RegisterPayload.image_info: Optional[ImageInfo] = None` in `schemas.py`, with the
     `repo_digests` item regex and a maximum of 20 items.
   - Semantics:
     - absent or null → keep the stored values;
     - present → replace them;
     - `image_name` changed with no `image_info` → clear the stored digest values.
   - STD picks the `RepoDigests` entry matching the normalized repository, using
     `image_ref.parse`.
   - States as in the §2.3 table: no digest → `unknown` with a reason; a digest
     reference → `pinned`.
   - This is a register contract change, so the PRD §18.1 row, `/api/v1/meta` features
     (`image_updates`, `image_info`) and `docs/register-api.md` must be updated.
5. **Data model** (§6.1, §6.2), in one Alembic migration.
   - The `image_reference` table: unique, indexed `ref`, sized to match
     `service_entry.image_ref`.
   - Observed columns: `image_running_digest` and `image_info` (JSON).
   - Operator columns: `image_update_policy` (NOT NULL, default `auto`),
     `image_tag_pattern` and `image_update_scope`.
   - Computed columns: `image_update_state`, `image_update_latest`, `image_update_kind`,
     `image_update_since` and `image_update_provider`.
   - No FKs.
   - Export/import: the operator columns round-trip per the PRD §20.2 ownership table.
     Observed and computed columns are not exported.
6. **Job and settings** (§5).
   - Add `image_update_check_job`: `IntervalTrigger(hours=24)` with a 30-minute jitter.
     **The interval is fixed, with no setting.**
   - The first run comes 24 hours after the persisted last run. When the check is first
     enabled, the first run comes a few minutes later.
   - Settings, stored in DB `setting` rows: `image_update_enabled` (**default off**,
     overridable by the env var `STD_IMAGE_UPDATE_ENABLED`) and `image_update_scope`
     (default `any`).
   - Off means no registry request at all. Stored results are kept.
   - Dedupe by reference, and one tag list per repository.
   - Concurrency: `ThreadPoolExecutor(4)`, at most 2 requests in flight per registry
     host, and a 30-minute run budget.
   - Per-reference backoff: skip for 1, 2 and 4 days, capped at 7.
   - `_RUN_LOCK` acquired non-blocking.
   - Check now: once per hour globally, once per 15 minutes per reference; per-entry
     Check now ignores backoff.
   - Registry I/O happens outside DB transactions and outside `routes_api._UPSERT_LOCK`.
   - The register recomputes an entry's state from the stored reference row, with no
     network. A new reference nudges a run, debounced to once per 5 minutes and only
     when the check is enabled.
   - Nightly retention: delete `image_reference` rows not wanted for 30 days. Hook it
     into the existing retention job.
   - Updates are **not** part of the health roll-up.
7. **Management API and MCP** (§7.3).
   - Entry responses gain the `image_update` block.
   - `PATCH /entries/{id}` accepts the three operator fields.
   - New routes, all in `mgmt_openapi.OPERATIONS`:
     - `GET /api/v1/image-updates` (accepts `?state=`);
     - `GET`/`PUT /api/v1/settings/image-updates` (`enabled`, `scope`, plus read-only
       `interval_hours: 24`, `last_run` and `next_run`);
     - `POST /api/v1/image-updates/run` (optional `entry_id`), returning 202, or 429
       when throttled.
   - Existing scopes: read for GETs, write for PUT/POST.
   - MCP: `list_image_updates` and `run_image_update_check`. Entries carry the block.
8. **MQTT / Home Assistant is NOT in this phase** (that's `img-04`). Make sure the state
   changes don't break the existing commit listener.
9. **Tests**:
   - Use a fake registry (e.g. `responses` or a monkeypatched session; check
     `requirements-dev.txt` for what's available and don't add a heavy dependency).
   - Cover:
     - the token challenge;
     - pagination and the 10-page cap;
     - 429 with `Retry-After`;
     - the Accept header;
     - the multi-arch index digest;
     - HEAD with no digest on Hub vs elsewhere;
     - tag model shapes, including every row of the §2.2 table, scopes and the pattern;
     - digest model states;
     - `image_info` absent, null, present and image-changed;
     - schema rejection of bad digests;
     - dedupe;
     - backoff;
     - the throttles;
     - the off switch (no requests at all);
     - retention;
     - API routes and OpenAPI;
     - export round-trip;
     - safe degradation with an old payload.
   - No real network in tests.
   - Run `uvx ruff@0.15.17 check .` and the FULL suite
     (`uvx --with-requirements requirements-dev.txt pytest -q`); both must pass. Update
     stale pins: the Alembic head, and `API_REVISION` if it is asserted.

## Conventions to honor

- **CHANGELOG `[Unreleased]` → Added**, in operator language. Say that the check is off
  by default and that a UI follows, or word it so it isn't misleading before `img-03`
  lands (e.g. "available through the management API; enable with
  `STD_IMAGE_UPDATE_ENABLED`").
- **PRD:** add a new section for image updates (architecture, the job, the data model,
  the register field, the API), plus §18.1, §22 cross-repo notes (notifier 0.5.0 will
  send `image_info`, gated on `/api/v1/meta`), the §3.1 module list and the revision
  table.
- **README:** mention the env var in the Configuration section.
- **`settings.example.yml` / `.env.example`:** add the env var if that's the pattern.
- **CLAUDE.md module layout:** add the new modules.
- **Commits:** prefix `feat:`. No `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. Move this file into `prompts/done/` (or `prompts/failed/`). It is untracked, so a plain
   `mv` is fine.
3. Record non-obvious decisions in `docs/decisions.md`, newest at top.
4. You are a spawned agent, so do **not** commit. Report back:
   - the exact file list;
   - a proposed one-line message;
   - the full-suite and lint results;
   - decisions;
   - anything `img-03` (UI) or `img-04` (MQTT/HA) needs to know.

   Never `git add -A`, never push.
