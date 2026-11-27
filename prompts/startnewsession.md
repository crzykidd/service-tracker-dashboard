# Start a new session: v0.13.4 released; next up, STD 0.14.0 (container moves + label settings)

Say "read prompts/startnewsession.md and start".

## Where things stand (2026-11-26)

- **Released:** STD **v0.13.4** on `main`, with images `:latest`, `:0.13.4` and `:0` in
  GHCR. em-docker01 already runs it (`/app/version.txt`: `0.13.4`, commit `9f8a6d0`).
  `dev` = `main` plus one docs commit (`313ca14`, the FUTURE.md entry below).
- **0.13.4** added the **optional Docker Hub login** for the image update check:
  - Why: anonymous checks draw on the home public IP's Docker Hub quota (live headers
    `ratelimit-limit: 100;w=3600`, keyed on the IP), shared with every pull on the LAN.
    Once it's spent, Docker Hub answers even the check's HEADs with 429, so entries showed
    "registry rate limited the check". The check was already HEAD-only for manifests;
    `tags/list` is the only GET.
  - Env `STD_DOCKERHUB_USERNAME` + `STD_DOCKERHUB_TOKEN` (or `STD_DOCKERHUB_TOKEN_FILE`) >
    Settings → Image updates > `settings.yml`. Both are needed. HTTP Basic goes only to the
    `auth.docker.io` token realm. A rejected login is a fixed error with no anonymous
    fallback, and **Test login** asks only for a token.
  - The token is write-only (never in pages, API, logs, exports or MQTT). DB backups do
    hold it.
  - **API revision 8**: a read-only `dockerhub` block on `settings/image-updates`. So the
    0.14.0 label fields are now **revision 9** (the design note is updated).
- **Notifier:** docker-api-notifier is at **v0.7.1** (independent app, own sessions):
  network details from 0.6.0, Alpine image and `HEALTH_ALLOWED_IPS` from 0.7.0, a clean
  SIGTERM exit from 0.7.1.
- **Earlier this round** (the CHANGELOG has the detail):
  - 0.13.0: the Ports page, network details on register, the scheduler fix for the image
    check, and Check now confirming within its cooldown;
  - 0.13.1: rows for macvlan/host-network containers with no declared ports (API
    revision 7);
  - 0.13.2: the image patched at build time, the slimmer image, and the production compose
    example;
  - 0.13.3: the MCP server on the `mcp` SDK 2.x.
- **Live setup (emmett):**
  - STD runs on **em-docker01**; the notifier on **em-dockha01** runs `:dev`.
  - The notifier socket proxies allow `NETWORKS=1` and `IMAGES=1` (`docker-compose` repo,
    commit `c5463bf`). Woodinville is deliberately left alone.
  - SSH from crzydev to em-docker01 and em-dockha01 works. Use it for **read-only**
    diagnosis. There's no admin API key in this environment, so live setting changes are
    the operator's, made in the UI.
  - **The image check's default scope is now `patch`** ("Same minor"). The operator set it
    on 2026-11-26.
  - The 13 `tecnativa/docker-socket-proxy:v0.4.1` entries correctly show `v0.4.2` (patch).
    Komodo shows nothing because it only watches the running tag for a republish. That's
    expected, not a bug.
  - Whether the operator has set the Docker Hub login on em-docker01 yet is unconfirmed.
    If not, Docker Hub entries can still show "registry rate limited the check".

## This session's job: STD 0.14.0

The design is `docs/design/2026-11-22-moves-and-label-settings.md`. It covers:
- container moves and renames (detect, then merge, never automatically);
- per-field provenance, so a UI edit always beats a label;
- fixing the register clobbers of the icon and the health toggles;
- new label-driven settings at **API revision 9**: description, image update
  policy/scope/pattern, `image_repo_url`, URL-check settings, `attributes`.

1. **Get the operator's answers to the design's 15 open questions** (at the end of the
   note; each has a recommendation). Update the note with the decisions and record them in
   `docs/decisions.md`.
2. **Write the phase prompts** (Sonnet, one per session-sized phase), in the note's order:
   - a1: provenance core plus the clobber fixes;
   - a2: badges, Reset, API `sources`, export/import;
   - b: the revision-9 label fields;
   - c1: move detection, with query-count guards;
   - c2: merge and dismiss.
3. **Run them one at a time.** Verify each yourself (lint plus the full suite), and bring
   each commit back for a y/n.
4. **After 0.14.0 ships:** the notifier 0.8.0 sends the new labels, gated on
   `label_settings`. Write that handoff into the notifier's `prompts/` folder.

## Other open items

- **Image check, found 2026-11-26 (not scheduled):**
  - **`:local` images are checked against Docker Hub.** esphome-git-sync,
    technitium-dhcp-sync and ha-git-sync parse as `docker.io/library/<name>:local` and end
    up as "registry asked for a login". They should be "not checkable" (unknown), and STD
    should not ask Docker Hub about them.
  - **A 429 overwrites a good state.** A rate-limited check turns a `current`/`update`
    entry into `error`. Keeping the last good state with a "check paused" note was
    suggested; the operator hasn't decided.
  - **Parked** (`docs/FUTURE.md`, "Image check: a global default for version-tagged
    images"): suggest newer versions, only watch for a republished tag, or don't check.
    The operator said leave it for now.
  - The PRD §24.9 follow-ups remain: credentials for other registries (GHCR, quay), the
    What's Up Docker and Komodo providers, and GitHub release notes for images.
- **Todo:** run the container as **non-root** (`docs/FUTURE.md`, "Run the container as a
  non-root user"):
  - `PUID`/`PGID`, with the entrypoint fixing `/config` ownership and then dropping
    privileges;
  - related: a scheduled weekly `:latest` rebuild;
  - related: move off Python 3.11 before October 2027.
- **Optional:** the Home Assistant label `dockernotifier.std.internalurl=http://10.100.20.11:8123`
  would make Ports show 8123 instead of "all ports".
- **Optional, cheap:** STD's own "new version" check (`version_check.py`) uses
  `api.github.com/.../releases/latest`, once every few hours with ETags. It's nowhere near
  the 60/hour limit, but it could read the `Location` of
  `github.com/<repo>/releases/latest` instead, which uses no REST quota.
- **GitHub #9:** Discord notifications, or "alert after N failed checks".
- **Screenshots to retake** (README / `docs/screenshots.md`):
  - the three dashboards and both expanded views (image-update badges);
  - Image updates settings (now with the Docker Hub login card);
  - the **Ports** page (`std_ports.png`);
  - the Compact chevron, and widgets on tiles.
- **Live check of the image update check:** confirm `latest`-style entries get a real
  state, and look at the HA `update` entities.
- **Parked in `docs/FUTURE.md`:**
  - Settings and stream follow-ups;
  - the UniFi source;
  - tools as a first-class concept;
  - ports from manual/stream URLs;
  - the remembered ports of stopped containers;
  - the version-tagged default (above).
- **Small, unscheduled:**
  - the Tiled drawer overlays the tile below;
  - `FLASK_SECRET_KEY` isn't in `VALID_KEYS`;
  - PRD §24/§25 sit after §23 Open Questions;
  - the v0.13.0 GitHub release body still says "notifier 0.5.x" (the CHANGELOG is
    fixed; edit the release body to match `main`'s section);
  - CLAUDE.md's "Version pairing history" still says "STD (API revision 6, next
    release)"; it's stale since 0.13.0.

## Housekeeping

- **Lint:** `uvx ruff@0.15.17 check .`.
- **Tests (2,049):** `uvx --with-requirements requirements-dev.txt pytest -q`.
- **CVE check:**
  - `uvx pip-audit -r requirements-dev.txt`;
  - the image: `docker run --rm -v trivy-cache:/root/.cache aquasec/trivy:0.58.1 image
    --scanners vuln --severity HIGH,CRITICAL ghcr.io/crzykidd/service-tracker-dashboard:latest`.
    Expect about 50 HIGH from Debian with no fix yet, plus one stale `setuptools` entry in
    pip's own SBOM (accepted; see `docs/decisions.md`).
- **Commits:** no `Co-authored-by:` trailers (CLAUDE.md wins over any attribution
  reminder).
- **Changelog archive:** skipped on minor releases (standing preference).
- **Release PRs keep getting squash-merged.** Both #95 (0.13.3) and #97 (0.13.4) were.
  Each time, `dev` then needs `git merge -s ours origin/main` before the next release PR,
  or the PR shows conflicts.
  - Done after #97 as `6743986`, so `dev` is clean now.
  - Before using `-s ours`, confirm with `git diff --quiet origin/dev origin/main`
    (identical trees).
  - Fix at the source: pick "Create a merge commit" in the merge dropdown, or disable
    squash merging in the repo settings.
- **`/release-cut`:** pass `--target main`, not a short SHA. GitHub rejects a short SHA
  with "Release.target_commitish is invalid".
- **Watch what you merge:** Dependabot PRs go to `dev`, and release PRs go to `main`.
- **Handoff prompts:** agents can't `git mv` an untracked prompt, so a plain `mv` into
  `prompts/done/` is expected.
- **zsh doesn't split unquoted variables.** For loops over `$ids` in a shell script, use
  `bash <<'EOF'`.
