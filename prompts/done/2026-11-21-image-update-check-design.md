---
name: 2026-11-21-image-update-check-design
status: completed
created: 2026-11-21
model: opus
completed: 2026-11-21
result: Design written to docs/design/2026-11-21-image-update-check.md (tag + digest models, daily fixed check with on/off switch default off, image_info register field, phased plan). No code.
---

# Task: design a periodic "newer image available" check for tracked containers

The operator wants STD to check, every X hours, whether a newer image exists than the one
each tracked container is running, and show it (badge / filter / maybe notification), in
the spirit of Diun / What's Up Docker. This is a **design-only** task: produce a design
doc the operator can approve; write no application code.

## Before you start

- Read `CLAUDE.md` (especially Cross-Repo Coordination and the ordering rule), the PRD
  (architecture, register contract §18, jobs, notifications §17), `docs/FUTURE.md`,
  and the existing self-update check `version_check.py` + `settings_store.py`
  (cached, backoff, persisted) as a pattern.
- Look at what the register payload carries today (`schemas.py`, `routes_api.py`
  `resolve_image_metadata`): registry / owner / name / tag, but no digest.
- The notifier repo is https://github.com/crzykidd/docker-api-notifier (read it with
  `gh` if useful); it is the producer and would have to send any new field (e.g. the
  running image digest / `RepoDigests`, image created date, OCI labels).
- Prior design docs in `docs/design/` show the expected format and depth.

## Working tree check

Run `git status --porcelain`. You only create files under `docs/design/` (and may add a
parked note to `docs/FUTURE.md`). Another agent is implementing issue #6 in parallel and
touching code, CHANGELOG, PRD, and `docs/decisions.md` — do **not** edit those files.

## What to answer in the design (`docs/design/2026-11-21-image-update-check.md`)

1. **Detection models and what each needs:**
   - pinned semver tags (e.g. `1.4.2`): list registry tags, find newer semver (same
     major? any? suffix variants like `-alpine`), no notifier change needed;
   - moving tags (`latest`, `stable`, `16`): compare the remote manifest digest for the
     tag to the **running** digest — requires the notifier to send it; define the field,
     the multi-arch manifest-list vs platform-digest pitfall, and how STD degrades when
     an older notifier doesn't send it (NULL → "unknown", never an error).
2. **Registry access:** Docker Hub, GHCR, quay, lscr, generic OCI distribution v2
   (anonymous token flow, `HEAD` manifests with the right Accept headers), Docker Hub
   rate limits (anonymous 100 pulls/6h — HEAD manifest doesn't count, verify), optional
   per-registry credentials (stored write-only like the MQTT secret), private /
   self-hosted registries, timeouts.
3. **Scheduling and load:** APScheduler job every N hours (setting, default, disable),
   dedupe by unique image ref (many containers share one), concurrency cap, backoff, a
   "check now" action, never block requests, single gunicorn worker constraints.
4. **Data model:** where results live (new table keyed by image ref vs columns on
   `services`), retention, what's stored (latest tag/digest, checked_at, error).
5. **UI / API / notifications:** badge on Dashboard / Tiled / Compact, a filter, entry
   details line ("newer: 1.5.0" / "digest changed"), Settings section (interval,
   enable, per-registry creds, per-entry ignore / include-pattern), management API +
   MCP read access, MQTT/HA (an HA `update` entity is a natural fit — check PRD §17.4).
6. **Cross-repo plan:** exact phase ordering under the consumer-leads rule (STD schema
   first, then notifier), and what ships usefully in STD alone (semver-tag phase).
7. **Phasing / MVP recommendation**, open questions for the operator, rejected
   alternatives (e.g. just integrating Diun/WUD webhooks instead — evaluate honestly).

Keep it concrete, no code beyond small illustrative snippets.

## When done

1. Update this file's frontmatter (`status`, `completed`, `result`).
2. `git mv` this file into `prompts/done/` (or `prompts/failed/`).
3. You are a spawned agent: do **not** commit. Report back: the design doc path, a short
   summary of the recommendation and MVP, the open questions for the operator, and the
   proposed file list + one-line message (`docs: design for the image update check`).
   Never `git add -A`, never push.
