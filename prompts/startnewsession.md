# Start a new session: v0.13.3 released; next up, STD 0.14.0 (container moves + label settings)

Say "read prompts/startnewsession.md and start".

## Where things stand (2026-11-23)

- **Released:** STD **v0.13.3** on `main`, with images `:latest`, `:0.13.3` and `:0` in
  GHCR. `dev` holds only the Dependabot `setup-python` 6 → 7 bump (#96) since then.
- **Notifier:** docker-api-notifier is at **v0.7.1**. It's an independent app with its own
  sessions.
  - 0.6.0 sends network details (driver, IPv4, IPv6, MAC; gated on `network_details`),
    adds `dockernotifier.std.skip`, fixes the label collision and bool-typo bugs, and warns
    once when a socket proxy blocks a lookup.
  - 0.7.0 moved its image to Alpine, added `HEALTH_ALLOWED_IPS` and a production compose
    example.
  - 0.7.1 exits cleanly on SIGTERM.
- **What shipped this round** (the CHANGELOG has the detail):
  - **0.13.0:**
    - the **Ports page** (#58, closed): grouped or flat view, state-first sort, the
      "not published" label, conflicts counted, filters remembered per browser,
      `GET /api/v1/ports` and the `list_ports` MCP tool;
    - **network details on register** (`driver`, `ip_address`, `ipv6_address`,
      `mac_address`; feature `network_details`);
    - host-network and macvlan/ipvlan ("direct") rows on the Ports page;
    - the **image update check fix**: it never ran from the scheduler before (it was
      missing an app context);
    - Check now **asks to confirm** within its cooldown instead of refusing.
  - **0.13.1:** rows for macvlan/host-network containers that declare no ports (for
    example Home Assistant), shown as "all ports (none declared)" or with the port taken
    from the entry's URL when the URL points at the container's own IP. API revision 7.
  - **0.13.2:**
    - the image is **patched at build time** (`apt-get upgrade`, current
      pip/setuptools/wheel), leaving no fixable HIGH/CRITICAL CVE;
    - dependencies updated;
    - a slimmer image (`.dockerignore`);
    - `docker-compose.example.yml` + `.env.example`: a production example with a
      hardened STD (all capabilities dropped except `DAC_OVERRIDE`, `no-new-privileges`,
      a healthcheck) and the notifier behind a read-only socket proxy. CI validates it.
  - **0.13.3:** the MCP server moved to the **`mcp` SDK 2.x** (`MCPServer`; tools
    unchanged).
- **Tooling:**
  - **Dependabot**, configured in `.github/dependabot.yml`:
    - PRs are grouped weekly, one per ecosystem, against `dev`. pip majors come on
      their own.
    - The root pip scan also covers `mcp/`, so there's no separate `/mcp` entry.
    - Dependabot reads the config from `main` only.
  - The GitHub Actions are all on their current majors.
- **Live setup (emmett):**
  - STD runs on **em-docker01**; the notifier on **em-dockha01** runs `:dev`.
  - The emmett notifier socket proxies (`docker-compose` repo, `emmett/host-utils/
    docker-api-notifier/*/compose.yml`, commit `c5463bf`) now allow `NETWORKS=1` and
    `IMAGES=1`. The Woodinville stacks are deliberately left alone, since they'll be
    rebuilt as they move.
  - SSH from crzydev to em-docker01 and em-dockha01 works (key installed 2026-11-22).
    Use it for **read-only** diagnosis.

## This session's job: STD 0.14.0

The design is `docs/design/2026-11-22-moves-and-label-settings.md`. It covers:
- container moves and renames (detect, then merge, never automatically);
- per-field provenance, so a UI edit always beats a label;
- fixing the register clobbers of the icon and the health toggles;
- new label-driven settings at **API revision 9** (8 went to the 0.13.4 Docker Hub login): description, image update
  policy/scope/pattern, `image_repo_url`, URL-check settings, `attributes`. Revision 7 went
  to 0.13.1.

1. **Get the operator's answers to the design's 15 open questions** (the end of the note;
   each has a recommendation). Update the note with the decisions and record them in
   `docs/decisions.md`.
2. **Write the phase prompts** (Sonnet, one per session-sized phase), in the note's order:
   - a1: provenance core plus the clobber fixes;
   - a2: badges, Reset, API `sources`, export/import;
   - b: the revision-8 label fields;
   - c1: move detection, with query-count guards;
   - c2: merge and dismiss.
3. **Run them one at a time.** Verify each yourself (lint plus the full suite), and bring
   each commit back for a y/n.
4. **After 0.14.0 ships:** the notifier 0.8.0 sends the new labels, gated on
   `label_settings`. Write that handoff into the notifier's `prompts/` folder.

## Other open items

- **Todo:** run the container as **non-root** (`docs/FUTURE.md`, "Run the container as a
  non-root user"):
  - `PUID`/`PGID`, with the entrypoint fixing `/config` ownership and then dropping
    privileges;
  - related: a scheduled weekly `:latest` rebuild;
  - related: move off Python 3.11 before October 2027.
- **Optional:** the Home Assistant label `dockernotifier.std.internalurl=http://10.100.20.11:8123`
  would make Ports show 8123 instead of "all ports".
- **GitHub #9:** Discord notifications, or "alert after N failed checks".
- **Screenshots to retake** (README / `docs/screenshots.md`):
  - the three dashboards and both expanded views (image-update badges);
  - Image updates settings;
  - the new **Ports** page (`std_ports.png`);
  - the Compact chevron, and widgets on tiles.
- **Live check of the image update check:** now that `IMAGES=1` is set on emmett, confirm
  `latest`-style entries get a real state, and look at the HA `update` entities.
- **Image check follow-ups** (PRD §24.9): registry credentials, What's Up Docker and Komodo
  providers, GitHub release notes for images.
- **Parked in `docs/FUTURE.md`:**
  - Settings and stream follow-ups;
  - the UniFi source;
  - tools as a first-class concept;
  - ports from manual/stream URLs;
  - the remembered ports of stopped containers.
- **Small, unscheduled:**
  - the Tiled drawer overlays the tile below;
  - `FLASK_SECRET_KEY` isn't in `VALID_KEYS`;
  - PRD §24/§25 sit after §23 Open Questions;
  - the v0.13.0 GitHub release body still says "notifier 0.5.x" (the CHANGELOG is
    fixed; edit the release body to match `main`'s section).

## Housekeeping

- **Lint:** `uvx ruff@0.15.17 check .`.
- **Tests (1,994):** `uvx --with-requirements requirements-dev.txt pytest -q`.
- **CVE check:**
  - `uvx pip-audit -r requirements-dev.txt`;
  - the image: `docker run --rm -v trivy-cache:/root/.cache aquasec/trivy:0.58.1 image
    --scanners vuln --severity HIGH,CRITICAL ghcr.io/crzykidd/service-tracker-dashboard:latest`.
    Expect about 50 HIGH from Debian with no fix yet, plus one stale `setuptools` entry in
    pip's own SBOM (accepted; see `docs/decisions.md`).
- **Commits:** no `Co-authored-by:` trailers (CLAUDE.md wins over any attribution
  reminder).
- **Changelog archive:** skipped on minor releases (standing preference).
- **Release PRs: merge with "Create a merge commit", not squash.** #95 (0.13.3) was
  squash-merged. That was harmless, but squash commits on `main` that `dev` lacks make
  later `dev` → `main` PRs messy.
- **Watch what you merge:** Dependabot PRs go to `dev`, and release PRs go to `main`.
- **Handoff prompts:** agents can't `git mv` an untracked prompt, so a plain `mv` into
  `prompts/done/` is expected.
- **zsh doesn't split unquoted variables.** For loops over `$ids` in a shell script, use
  `bash <<'EOF'`.
