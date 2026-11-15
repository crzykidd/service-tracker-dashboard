# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-15 — Adopting release-prep-and-cut: VERSION file, no APP_VERSION, tag guard

- **`VERSION` is the single source of the in-app version.** The Dockerfile
  derives `version=` in `/app/version.txt` from the copied `VERSION` file
  (`tr -d '[:space:]'`). Previously `APP_VERSION` came from the
  metadata-action output, which is `dev`/`latest`/`pr-N` off release events,
  so `:dev`/`:latest` reported a non-semver and the What's New popup
  (keys on the version) misbehaved.
- **`APP_VERSION` build arg removed outright, not kept as an override.** An
  override would let a build disagree with `VERSION`, recreating the drift
  this fixes; nothing needs it (local builds also read `VERSION`).
- **`publish.yml` guard:** on `release` events a step before the builds fails
  if the tag minus leading `v` != `VERSION` — cheap protection against
  tagging the wrong commit. Only the version build-args and this step were
  touched; Docker Hub steps and `REGISTRY_NOTICE` left for the other prompt.
- **`app.py` fallback** (no `/app/version.txt`, e.g. `python app.py`) reads
  `VERSION` beside `app.py`, else `"unknown"`.
- **`<LOCAL_CHECKS>` reuse `ci.yml`.** Config validation extracts and runs
  the `config-validate` step's script from `ci.yml` via PyYAML, so the file
  lists can't drift. Lint is `uvx ruff@0.15.17 check .`. Migration check uses
  a temp copy of `alembic.ini` (URL and `%(here)s` script_location rewritten)
  and `uv run --python 3.11 --with-requirements requirements.txt alembic` (no global alembic on the dev box), never a real `/config` (contrast with CI, which
  creates a runner-local `/config`).
- **Tooling stays out of CHANGELOG** (per the vexp entry); only the
  operator-visible "images report the real version" effect was logged.
- The bare `0.6.5` tag remains an un-fixable historical deviation.

---

## 2026-11-15 — Adopting code-checkin-and-pr: migration-check DB, retention scope, F821

- **Migration check uses a runner-local `/config`** (`sudo mkdir -p /config &&
  sudo chown $USER /config`) rather than an env-var override in
  `alembic/env.py`. `alembic.ini` hardcodes `sqlite:////config/services.db`;
  creating the dir keeps the check running against the unmodified production
  config and avoids a code change. Rejected: env override (runtime-adjacent
  change for a CI-only need).
- **Untagged GHCR versions are never pruned.** `publish.yml` uses
  `build-push-action` with default provenance, so per-platform/attestation
  manifests exist as untagged versions referenced by tagged indexes. Telling
  referenced from orphaned is not worth the risk; accepted cost is some
  untagged residue after tagged versions are pruned.
- **F821 in `routes_dashboard.py` `/add` was a real bug.** A non-numeric sort
  priority raised `NameError` (`groups` undefined) -> HTTP 500. Fixed by
  loading `groups` at the top of the POST branch and passing it to all three
  error re-renders (the other two silently rendered an empty group dropdown).
  Operator-visible, so it has a CHANGELOG `### Fixed` entry.
- **CI is push-only** (no `pull_request` trigger) to avoid duplicate
  same-named check runs that leave required checks stuck "Expected".
- Test check exempt (no suite); recorded in `standards.md`.

---

## 2026-11-15 — vexp removal recorded in HISTORY, not CHANGELOG

CLAUDE.md requires a CHANGELOG entry for every change, but CHANGELOG is
operator-facing and is rendered in the in-app "What's new" popup. The vexp
removal is developer tooling with no operator-visible effect, so it was
recorded in `docs/HISTORY.md` instead. Same reasoning applies to future
tooling-only changes (agent guidance, `.claude/` config).

## 2026-11-15 — Docker Hub → GHCR via a banner-only final Docker Hub release

v0.6.7 was published to both registries from one workflow, with the
in-app "moved to GHCR" banner gated on a `REGISTRY_NOTICE=dockerhub`
build arg so only the Docker Hub image shows it. Rejected: a Docker
Hub-only final release (GHCR would have had nothing to switch to) and
an unconditional banner (users who had already moved would keep seeing
it). Driver: GHCR retention runs on `GITHUB_TOKEN`; Docker Hub retention
would need a delete-scoped token and a custom cleanup job. Docker Hub
publishing, the build arg, and the banner are removed in the next
release; Docker Hub tags stay frozen on the v0.6.7 banner build.

## 2026-11-15 — The `0.6.5` tag stays un-prefixed

v0.6.5 was tagged `0.6.5` (no `v`), unlike every other release. It is
left as-is: re-tagging a published release is never done (moving a tag
under consumers breaks pins and image provenance). CHANGELOG's link
reference already points at `releases/tag/0.6.5`. All new tags use the
`vX.Y.Z` form.
