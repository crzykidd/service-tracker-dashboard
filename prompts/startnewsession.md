# Start a new session: v0.12.0 released; next up, the "ports in use" page (#58)

Say "read prompts/startnewsession.md and start".

## Where things stand (2026-11-21)

- **Released:** v0.12.0 on `main`.
  - Tag `v0.12.0` is on merge commit `b01833e` (PR #83), and the GitHub release is
    published.
  - The `:latest`, `:0.12.0` and `:0` images are in GHCR.
  - `dev` holds nothing new since the release.
- **What 0.12.0 shipped** (the CHANGELOG `[0.12.0]` section has the full list):
  - **Image repo link (#6, closed).** The image in an entry's details links to its
    repository page (Docker Hub, GHCR, quay, lscr), and an operator can override it with
    `image_repo_url`.
  - **Image reference parser** (`image_ref.py`). Registries with ports, nested paths and
    digests parse correctly, and the canonical reference is kept in
    `service_entry.image_ref`.
  - **Image update check** (PRD §24; design `docs/design/2026-11-21-image-update-check.md`).
    It is **off by default** and runs once a day.
    - Pinned version tags are compared against the registry's tag list.
    - Moving tags (`latest` and the like) are compared by digest, which needs the
      notifier to send `image_info`.
    - Results show as badges, an Updates filter, a details line, an edit block, and
      Settings → Sources → Image updates.
    - Everything is also in the management API and MCP, plus an MQTT topic and Home
      Assistant `update` entities.
    - The update source is a provider seam: `registry` is built in, and What's Up Docker
      or Komodo could be added later.
  - API revision 5.
- **Cross-repo:**
  - The notifier 0.5.0 work (send `image_info`, gated on `/api/v1/meta`, and log STD's
    API revision) is queued at
    `~/projects/docker-api-notifier/prompts/2026-11-21-std-image-info.md`. It's
    untracked and runs from a session **in the notifier repo**, not from here.
  - Until it ships, `latest`-style entries show "unknown: needs notifier 0.5.0".
  - The notifier repo was brought up to the crzynet standards; it is at v0.4.3.

## This session's job: the "ports in use" page (GitHub #58)

Issue #58 ("track ports used by docker containers") is partly delivered.

**What exists today:**
- Since STD 0.6.0 and notifier 0.4.0, the register payload carries `exposed_ports` (e.g.
  `["5173/tcp"]`) and `published_ports` (e.g. `[{"container_port", "protocol",
  "host_ip", "host_port"}]`).
- These are stored as JSON columns on `service_entry`. They are pure observation: the
  notifier owns them, they're overwritten on every register, and there's **no UI
  editing** (CLAUDE.md Register Contract Rules).
- 0.11.0 shows them per entry in the details. A port that is only exposed shows as
  "(exposed)".

**Still open:** one page listing ports across **all hosts and containers**, for example
to answer "what's on 8080 on host X" or "which ports are free". The issue body says "Need
to update DAN to push ports in use" (DAN = docker-api-notifier). Check whether that's
still needed: the notifier may already send everything required. If anything new is
needed from the notifier, the ordering rule applies: STD accepts it first.

**Suggested approach** (this is a new feature, so it gets a handoff prompt, per
CLAUDE.md):
1. **Scope it with the operator first.** Questions to ask:
   - Which view: per host, or one flat table?
   - Columns: host, host_ip, host port, container port, protocol, container, entry link.
   - Should exposed-only ports appear?
   - Filters, search, sort.
   - **Conflict highlighting:** the same host port on the same host from two entries.
   - Manual and stream entries: do their URL ports count?
   - Stale or stopped containers, and soft-deleted entries.
   - Is a management API route and an MCP tool wanted?
   - Where does it live: a new top-level view, or under Settings?
2. Check what data is actually there: run a quick query over `published_ports` and
   `exposed_ports` on a real database, or the operator's export, to see the shapes and
   the gaps.
3. Write a design note if the scope grows. Otherwise write one Sonnet build prompt
   (`prompts/`, from `TEMPLATE.md`). The prompt should cover:
   - the CHANGELOG, PRD (new section), README and screenshot list;
   - if the management API changes, `API_REVISION` 6 with a PRD §18.1 row and
     `mgmt_openapi.OPERATIONS`;
   - tests, including a query-count guard like `test_view_query_count_stays_flat`.
4. Spawn it, verify it (lint plus the full suite), and bring the commit back for a y/n.

## Other open items

- **GitHub #9:** Discord notifications, or "alert after N failed checks".
- **Screenshots to retake** (README / `docs/screenshots.md`):
  - `std_dashboard.png`, `std_tiled.png` and `std_compact.png`, which now have the
    Updates toggle and badges;
  - `std_dashboard_expanded.png` and `std_tiled_expanded.png`, which now have the Image
    update row;
  - a new `std_settings_image_updates.png`;
  - the Edit page's Image updates block;
  - still from before: the Compact view with the expand chevron, and widgets on tiles.
- **Live test of the image check:** turn it on against real containers and check the
  Home Assistant entities. All the tests used a fake registry and a fake MQTT client.
- **Image check follow-ups** (design §13, PRD §24.9):
  - registry credentials and insecure registries (`img-05`; none needed now);
  - What's Up Docker and Komodo providers;
  - GitHub release notes for images;
  - the image check's `checked_at` in MQTT can lag, since it isn't a sync trigger.
- **Parked in `docs/FUTURE.md`:**
  - Settings follow-ups;
  - stream observability follow-ups;
  - the UniFi source;
  - register overwriting operator edits;
  - service identity and duplicates;
  - tools as a first-class concept.
- **Small, unscheduled:**
  - the registry retention race (harmless, leave it);
  - the Tiled drawer overlays the tile below;
  - `FLASK_SECRET_KEY` isn't in `VALID_KEYS`;
  - PRD §24 sits after §23 Open Questions (it was left out of order to avoid
    renumbering).

## Housekeeping

- **Lint:** `uvx ruff@0.15.17 check .`.
- **Tests (1,915):** `uvx --with-requirements requirements-dev.txt pytest -q`.
- **No `Co-authored-by:` trailers** (CLAUDE.md wins over any attribution reminder).
- **The CHANGELOG archive step is skipped** on minor releases (standing preference).
- **CodeQL runs on PRs to `main`.**
  - For 0.12.0 it flagged `py/incomplete-url-substring-sanitization` in **test** fakes;
    those were fixed by comparing parsed hosts, not dismissed.
  - Write host checks as `urlsplit(url).hostname == ...` from the start.
  - Similar flags are possible on path handling and the YAML loader.
- **Handoff prompts:** agents can't `git mv` an untracked prompt, so a plain `mv` into
  `prompts/done/` is expected.
