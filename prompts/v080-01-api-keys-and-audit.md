---
name: v080-01-api-keys-and-audit
status: pending          # pending | completed | failed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed:               # filled when the work is done
result:                  # one-line summary of the outcome
---

# Task: Admin API keys, management blueprint, and write audit log

Add DB-stored admin API keys with read/write scopes, the authenticated
`/api/v1` management blueprint skeleton (auth decorator, JSON errors,
`whoami`), and the write audit log model plus retention. Spec: PRD §14.1,
§14.2 and §14.6 (the audit model and retention; its Settings view comes in
v080-04).

## Before you start

- `CLAUDE.md` (project rules, Database Rules, Register Contract Rules) and
  `standards.md`.
- `docs/PRD.md` **§14** (the v0.8.0 plan) in full, plus **§5.7**. The
  subsection named below is your spec. Where it and the code disagree, trust
  the code, follow the spirit of the PRD and record the call in
  `docs/decisions.md`.
- `docs/decisions.md` top entry ("v0.8.0 Management API design calls").
- `tests/conftest.py` and the existing tests. New behaviour ships with tests.
- Code: `routes_api.py` (`_check_bearer_auth`, `_UPSERT_LOCK`, the
  `csrf.exempt` pattern), `app.py` (blueprint and job wiring), `extensions.py`,
  `models.py`, `routes_auth.py` (`is_admin_required`), `jobs.py` (APScheduler
  jobs such as the purge jobs), `templates/settings.html` (tab structure), and
  `templates/partials/flash_messages.html`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Models and migration:** `ApiKey` and `ApiAudit` exactly per §5.7.
   `down_revision` is the current head; check it with `alembic heads`. It
   should be `c1d7a3e5f2b8`.
2. **`api_keys.py`:**
   - `generate_key()` returns `(full_key, prefix, key_hash)`, with the
     format `std_<prefix>_<secret>` and `secrets.token_urlsafe(32)`.
   - `verify(presented)` looks up by prefix, compares the hash with
     `hmac.compare_digest`, rejects revoked keys, and returns the key or
     None.
   - The scope check: `write` includes `read`.
3. **`routes_mgmt_api.py`:**
   - Blueprint at `/api/v1`, registered in `app.py`, the whole blueprint
     `csrf.exempt`.
   - Decorator `require_api_key(scope)`:
     - It reads only the `Authorization: Bearer` header. It ignores
       sessions, so a logged-in browser without a key gets a 401.
     - 401 when the key is missing or invalid, 403 on a scope mismatch.
     - It sets `g.api_key` and updates `last_used_at`/`last_used_ip` at
       most once a minute per key.
   - The notifier `api_token` must **not** authenticate here. Add a test.
     `/api/v1/register` must not accept a management key. Also add a test.
   - JSON error handlers for this blueprint: `{"error", "details"}`.
   - `GET /api/v1/whoami` (read scope) returns `{name, prefix, scope}`.
4. **Audit:**
   - An `after_request` hook on the blueprint writes one `ApiAudit` row for
     every POST, PATCH, PUT or DELETE that passed auth (key id and name
     snapshot, method, path, status). Writes that failed validation are
     audited too.
   - Endpoints set `g.audit = {object_type, object_id, changes}`, where
     `changes` is `{field: [old, new]}`, through a helper `audit(...)` that
     masks secret fields as `"***"`.
   - Unauthenticated requests are not audited; they are only logged.
   - New setting `api_audit_retention_days` (default 90) and a daily purge
     job.
5. **Settings → API tab** (admin, CSRF):
   - Create key: a name (unique, at most 64 chars) and a scope. The full key
     is shown once on the response page with a copy button and a "you won't
     see this again" note. It must not be stored in a flash or the session.
   - List keys: name, prefix, scope, created, last used (time and IP),
     status, and Revoke.
   - Revoked keys stay listed and greyed out.
6. **Tests:**
   - Key generation and verification: a good key, a wrong secret, an unknown
     prefix, a revoked key.
   - The scope matrix on `whoami`, plus a dummy write route registered in
     the test.
   - The session cookie alone gives 401.
   - `api_token` gives 401 on the management API, and a management key
     gives 401 on register.
   - Throttling of `last_used_at`.
   - Audit rows on writes, including a 400, and none on reads.
   - Secret masking.
   - Retention purge.
   - Settings tab create, show-once and revoke, with CSRF.
   - Migration up, down and up again.

## Conventions to honor

- Work on `dev`. Commit prefix `feat:`. No `Co-authored-by:` trailer. Never
  `git add -A`, never push.
- **Schema changes:**
  - Use one Alembic migration with a single head and write a downgrade.
  - Every FK gets its index in the same migration.
  - Run `alembic upgrade head` on an empty DB **and** on a DB at the
    previous head with seeded data.
  - Migration tests use the subprocess + temp `alembic.ini` pattern from
    `tests/test_health_schema.py`, because the real `alembic.ini` hardcodes
    `/config/services.db`.
- **Settings:** read them from `app.config`. New settings go in
  `settings_loader.py`, `settings.example.yml` and the README settings
  reference.
- **Register contract:** `schemas.py`'s `RegisterPayload` and
  `/api/v1/register` are untouched.
- **Never log or return a secret:** API key secrets after creation,
  `widget_api_key`, `api_token`, `secret_key`.
- **Definition of done, in the same commit:**
  - a CHANGELOG `[Unreleased]` entry in operator language;
  - the PRD subsection marked "— Delivered (unreleased)" with an "As
    built:" paragraph, plus a revision row at the bottom of the table;
  - README updated where operator-facing behaviour changes;
  - the CLAUDE.md module layout updated for new files;
  - `docs/decisions.md` for any non-obvious call.
- **Before handing off, run:**
  - `uvx ruff@0.15.17 check .`
  - `pytest -q` from the venv at `/tmp/claude-1000/-home-manderse-projects-service-tracker-dashboard/4c746645-e543-471f-a244-66c582de68d1/scratchpad/venv`, which has requirements-dev,
    icmplib and Playwright with cached Chromium
  - `alembic upgrade head` on a fresh scratch DB

  Report results verbatim if anything fails. Scratch files go in that
  scratchpad, not the repo.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure), renamed `2026-11-15-v080-01-api-keys-and-audit.md`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on `dev`.
   Never `git add -A`, never push, never auto-commit.
