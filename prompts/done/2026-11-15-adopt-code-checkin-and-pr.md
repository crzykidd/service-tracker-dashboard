---
name: 2026-11-15-adopt-code-checkin-and-pr
status: completed
created: 2026-11-15
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-15
result: Added ruff.toml, ci.yml (4 checks), retention.yml; fixed F821 bug in /add; docs and CLAUDE snippet updated.
---

# Task: Adopt `code-checkin-and-pr` @ v1.2.0

Wire STD's CI, registry retention, and agent guidance to the
`code-checkin-and-pr` standard v1.2.0. Branch protection, the image-publish
matrix, and CodeQL already exist. What's missing is the required CI checks
(lint, config validation, migration check, compose validation), GHCR registry
retention, and the CLAUDE snippet.

## Before you start

- Read the standard: `~/projects/homelab-configs/standards/code-checkin-and-pr/README.md`
  and its `CLAUDE-snippet.md` (canonical URL:
  `https://gitea.crzynet.com/crzynet/homelab-configs/src/branch/main/standards/code-checkin-and-pr/README.md`).
- Read `CLAUDE.md`, `standards.md`, and `docs/decisions.md` in this repo.
- Reference implementation (same owner, GHCR, Python + Alembic): 
  `~/projects/filament-bridge/.github/workflows/ci.yml` and `retention.yml`.
  Adapt it, don't copy blindly. filament-bridge has a `backend/` subdir, while STD
  is flat at the repo root.
- You are on branch `dev`. Don't switch branches and don't push.

### Current state (verified 2026-11-15)

- `.github/workflows/publish.yml` builds and pushes images to **GHCR**
  (`ghcr.io/crzykidd/service-tracker-dashboard`) **and** a deprecated Docker Hub
  image. Its job is named `build`, which is a required status check. **Do not
  modify publish.yml in this task.** Docker Hub removal is a separate prompt.
  The workflow's display name is `Build and Push Docker Image`.
- The PR-only image build (standard check #5) is already covered: publish.yml
  builds without pushing on `pull_request`.
- `main` ruleset id `16196342` ("Require PR for Main") requires the PR and the status
  check `build` (integration_id 15368 = GitHub Actions) plus CodeQL code scanning. It
  blocks deletion and non-fast-forward. CodeQL **default setup** is configured, which
  satisfies SAST (#7).
- There is no test suite (`scripts/test_widget.py` is a manual script, not tests).
  Check #6 is exempt until tests exist. Record that in `standards.md`.
- Ruff with `--select E9,F` currently reports 2 findings: one `F401` unused import
  and one `F821` undefined name. **Investigate the F821. It may be a real runtime
  bug.** Fix it properly if it is, and report what it was.
- `alembic.ini` hardcodes `sqlalchemy.url = sqlite:////config/services.db` and
  `alembic/env.py` reads it via `config.get_main_option`. The migration check needs
  a throwaway DB. Pick the least invasive option and justify it in the report.
  Options: create a writable `/config` on the runner (`sudo mkdir -p /config &&
  sudo chown $USER /config`), or add an env-var override in `env.py`. The override
  is a code change, so only do it if it's clearly better, and keep the production
  default unchanged.
- Configs worth validating: `docker-compose.yml`, `settings.example.yml`,
  `widgets/*/settings.json`, `.claude/settings.json`, and the workflow YAMLs.
- `docker-compose.yml` uses an external `proxy` network and `build: .`.
  `docker compose config --quiet` should pass without the network existing. Verify.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt. It's
expected to be modified by "When done" below.

## What to do

1. **Ruff config.** Add a `ruff.toml` (or `[tool.ruff]` in a new minimal
   `pyproject.toml`; prefer `ruff.toml` since there's no pyproject) selecting
   `E9`, `F`, excluding `alembic/versions/` only if needed. Target Python 3.11.
   Fix both current findings. `ruff check .` must pass locally.
2. **`.github/workflows/ci.yml`** named `CI`, with jobs named exactly:
   `Lint`, `Config validation`, `Migration check`, `Compose validation`.
   - Trigger on **push to `dev` and `main` only, not `pull_request`**.
     filament-bridge learned that push+PR triggers produce duplicate same-named
     check runs that leave required checks stuck "Expected — Waiting". Copy their
     explanatory comment. The ruleset is non-strict, so the dev head commit's push run
     satisfies the PR.
   - Python 3.11 (the project's stack). Pin ruff (`ruff==0.15.17`, same as
     filament-bridge) and leave a comment explaining the pin.
   - Migration check: `pip install -r requirements.txt`, then `alembic upgrade head`
     on an empty DB, and assert `alembic current` shows `(head)`. Also assert
     there's exactly one head (`alembic heads` returns one line). That catches
     branched chains.
   - Use current action major versions consistent with what `publish.yml` uses or
     newer (checkout, setup-python). Least-privilege `permissions: contents: read`.
3. **`.github/workflows/retention.yml`** named `Registry retention`. Adapt
   filament-bridge's: trigger on `workflow_run` of `Build and Push Docker Image`
   (completed, success) and a weekly cron. Package `service-tracker-dashboard` under
   `/user/packages/container/...`. Keep the 30 most recent `sha-*` versions and the
   15 most recent semver versions, and never delete versions tagged `latest`, `dev`,
   or a bare major (`^[0-9]+$`). **Also never delete untagged-but-referenced
   versions**. If you're unsure whether multi-arch/attestation manifests exist, leave
   untagged versions alone entirely and note it.
   - Caveat to evaluate and report: `GITHUB_TOKEN` can delete versions of a package
     **only if the repo has Admin access to the package** (Package settings → Manage
     Actions access). The package was created by this repo's workflow, so it should
     be linked, but say clearly in the report that the user may need to grant it.
     Docker Hub gets **no** retention job (it's frozen at v0.6.7 and being removed).
4. **Validate locally** before reporting: `ruff check .`; parse every YAML/JSON you
   listed; run the migration check the way CI will (use a temp dir, not the real
   `/config`); `docker compose config --quiet`. If `actionlint` is available, run it.
   Otherwise parse the workflow YAMLs with PyYAML.
5. **CLAUDE.md.** Paste `~/projects/homelab-configs/standards/code-checkin-and-pr/CLAUDE-snippet.md`
   **verbatim** (including its HTML source comment), directly after the
   "Handoff prompts (operational rules)" block. Then reconcile the existing
   project sections so they don't contradict it. Leave the project-specific
   `refactor:` prefix in "Commit style" but annotate it as a project extension to
   the standard. Trim the "Git Workflow" bullets that the snippet now covers
   (no direct push to main, no Co-authored-by) only where they duplicate it word
   for word; keep the release-UI tagging line (a later prompt replaces it).
   Update the "Branch protection" bullet to name the new required checks.
6. **`standards.md`.** Add a row `code-checkin-and-pr | 1.2.0 | 2026-11-15` with
   honest notes: tests exempt (no suite yet); SAST via CodeQL default setup; image
   build check satisfied by publish.yml's PR build (job `build`); retention on GHCR
   only (Docker Hub frozen); `refactor:` prefix is a project extension.
7. **Docs per CLAUDE.md "Definition of Done":** PRD §11 (Versioning, Branches,
   and Releases) gets the CI checks and retention, plus a revision-history row (next
   number after the current top row). README "Versioning & Releases" gets the
   branch-protection sentence updated to list the checks. CHANGELOG: per
   `docs/decisions.md` (2026-11-15 vexp entry), tooling-only changes don't go in the
   operator-facing CHANGELOG. **Exception:** if the F821 fix changes runtime
   behavior, add a `### Fixed` entry under `[Unreleased]` in user-facing language.
8. **Do NOT change the ruleset yourself.** Report the exact `gh api` command to add
   the four new required checks (`Lint`, `Config validation`, `Migration check`,
   `Compose validation`, integration_id 15368) to ruleset 16196342, preserving its
   existing rules. The orchestrating session will run it after the user approves and
   after CI has run once on `dev`, so the check names exist.

## Conventions to honor

- Commit prefix `chore:`. No `Co-authored-by` trailer.
- Stage only specific paths; never `git add -A`.
- Don't modify `publish.yml`, the app's runtime code (except the F821/F401 fixes),
  or anything Docker Hub / banner related.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet. Since the file isn't tracked
   yet, `git add` it first and then `git mv` it.
3. Record any non-obvious decisions in the project's `docs/decisions.md`, for example
   the migration-check DB approach or the untagged-version retention choice.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed; it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user. Also report: the F821 finding, the ruleset
     `gh api` command, and the package Actions-access caveat.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit. This project adopts
   `code-checkin-and-pr`, so: branch `dev`, `chore:` prefix, no `Co-authored-by:`.
