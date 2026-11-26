---
name: 2026-11-26-dockerhub-auth-image-check
status: completed        # pending | completed | failed
created: 2026-11-26
model: sonnet
completed: 2026-11-26
result: Optional Docker Hub login (env > Settings > settings.yml, write-only token, Basic only to auth.docker.io) implemented; API revision 8; lint and full suite green
---

# Task: optional Docker Hub credentials for the image update check

The image update check talks to Docker Hub anonymously, so its quota is the home public IP's
(live headers: `ratelimit-limit: 100;w=3600`, `docker-ratelimit-source` = the IP). Every pull
on the LAN spends that, and once it is gone Docker Hub answers even the check's HEADs with 429,
so entries end up "registry rate limited the check". Let the operator give a Docker Hub
username + access token so the check authenticates and draws on the account's quota instead.

Manifests are already HEAD-only on Docker Hub (`registry_client.head_manifest` refuses the GET
fallback there); the only GET is `/v2/<repo>/tags/list`, which is not a pull. Do not change
that request shape. This task is authentication only.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Database Rules, module layout) and `standards.md`.
- Read PRD §24 (`docs/PRD.md`, "v0.12.0 — Image update check"), especially 24.2, 24.6, 24.7
  and 24.9 ("Not built yet" lists registry credentials).
- Read `registry_client.py` (anonymous Bearer flow: `_token`, `_request`, `_follow`, the
  "a token is never forwarded off the registry host" rule), `image_update.py` (settings,
  `RegistryClient` construction per run), `settings_store.py` (`get/set_image_update_value`),
  `backups.py` (the env > UI > settings.yml > default resolution pattern to copy),
  `templates/partials/settings/` (the Image updates section) and how the MQTT channel
  password (`NotificationChannel.secret`, `notify_mqtt.py`) is kept write-only everywhere.
- Lint: `uvx ruff@0.15.17 check .`. Tests: `uvx --with-requirements requirements-dev.txt pytest -q`
  (about 1,994 today; all must pass).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Settings.** Two values, `dockerhub_username` and `dockerhub_token` (a Docker Hub personal
   access token, read-only scope is enough). Resolution like backups: env > UI (DB) >
   `settings.yml` > unset.
   - Env: `STD_DOCKERHUB_USERNAME`, `STD_DOCKERHUB_TOKEN`, and `STD_DOCKERHUB_TOKEN_FILE`
     (path to a file holding the token, for Docker secrets; `_TOKEN` wins if both set).
   - `settings.yml` keys: add them to the loader and `VALID_KEYS` (or the equivalent
     validation list) and to `settings.example.yml` commented out.
   - Both values must be set to count as configured; one without the other is "not
     configured" and the Settings page says so.
2. **Secret handling (non-negotiable).** The token is write-only: never rendered back into a
   form, never returned by any API, never logged, never in an error message, never in an
   export (`export_format.py`), never in MQTT/HA payloads. Show only "set" / "not set" and the
   source (environment / Settings / settings.yml). A DB snapshot backup will contain it like
   the MQTT password does; say so in the README.
3. **Client.** In `registry_client.RegistryClient`, accept optional Docker Hub credentials.
   Use them only when the registry is `docker.io` **and** the Bearer challenge realm is
   `https://auth.docker.io/...`: send HTTP Basic on that token request. Never send them to any
   other host, never on a redirect, never to the registry itself. Everything else stays
   anonymous exactly as now. If the token request answers 401/403 with credentials, raise a
   new fixed message (e.g. `ERR_HUB_LOGIN = "Docker Hub rejected the configured login"`) and
   do not silently retry anonymously. `image_update` passes the resolved credentials when it
   builds the client for a run.
4. **Settings UI** (Image updates section): username field, token field (password input,
   empty = keep current), a "Clear Docker Hub login" action, the source/status line, and when
   the env sets them the fields are read-only with "set by environment". Add a **Test login**
   button that asks only `auth.docker.io` for a token (no manifest request, no pull) and
   reports ok / rejected / unreachable with fixed messages. CSRF and admin-only like the rest of
   Settings.
5. **Management API.** If image-update settings are exposed there today, add read-only
   `dockerhub: {configured, username, source}` (never the token). Do not add a way to set the
   token over the API. If you add any response field, follow the rules: bump `API_REVISION`
   in `api_version.py`, add the PRD §18.1 row, keep `mgmt_openapi.py` and its tests in step.
   If nothing there exposes these settings, leave the API alone and say so.
6. **Tests.** Credentials sent as Basic only to the `auth.docker.io` realm; never to GHCR,
   quay, a non-https realm, a different realm host, or a redirect target; anonymous when
   unconfigured or half-configured; the rejected-login error; env > UI > yml resolution and
   `_FILE`; the token absent from rendered Settings HTML, API responses, exports and logs
   (assert on caplog); the Test login route.
7. **Docs (same commit):**
   - `CHANGELOG.md` `[Unreleased]` → Added: optional Docker Hub login for the image check.
   - `README.md`: configuration table rows for the three env vars + yml keys, a short note on
     why (shared IP quota), how to make a read-only PAT, and that the DB backup holds it.
   - `docs/PRD.md` §24: document the credentials (24.2/24.6, and 24.7 if the API changed),
     narrow §24.9 to "credentials for other registries", bump the revision-history table.
   - `.env.example` / `docker-compose.example.yml`: commented-out `STD_DOCKERHUB_*` lines.
   - `docs/decisions.md` (newest at top): Docker Hub only for now; Basic only to the
     `auth.docker.io` realm; no silent anonymous fallback; token not settable via the API.

## Out of scope (do not build; mention in your report if you think it matters)

- Credentials for GHCR / quay / other registries.
- Changing how a 429 is stored (keeping the last good state). The orchestrator will decide.
- `:local` images being checked against Docker Hub ("registry asked for a login").

## Conventions to honor

- No migration should be needed (the DB settings store is key/value); if you find you need
  one, it goes through Alembic.
- Commit prefix `feat:`; no `Co-authored-by:` trailer.
- Plain functions, short fixed error strings, no raw exception text stored or shown.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (on success) or `prompts/failed/` (on failure) with a
   plain `mv` (it is untracked, so `git mv` will fail).
3. Record any non-obvious decisions in `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Run lint and the full test suite, then report
   back: the result counts, the file list, the proposed one-line message
   (`feat: optional Docker Hub login for the image update check`), whether the API changed
   (and the new revision), and anything you were unsure about. Never `git add -A`, never push.
