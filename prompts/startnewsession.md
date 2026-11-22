# Start a new session: v0.11.0 released, nothing scoped

Say "read prompts/startnewsession.md and start".

## Where things stand (2026-11-21)

- **Released:** v0.11.0 on `main`.
  - Tag `v0.11.0` is on merge commit `c18a19b`, and the GitHub release is published.
  - The `:latest`, `:0.11.0` and `:0` images are in GHCR.
  - Nothing new is on `dev` since the release.
- **What 0.11.0 shipped** (the CHANGELOG `[0.11.0]` section has the full list):
  - the 0.10.2 fixes: the MQTT test is capped at about 5 s, and entry names can be 128 characters;
  - the Settings modernization (PRD §19);
  - backup, export, import and staged restore (PRD §20), API revision 4;
  - the expanded Dashboard row and the Compact details dialog, both built on
    `partials/entry_facts.html` (PRD §13.7);
  - the full Docker image shown in entry details;
  - removal of the `/reset_user_password` route;
  - `settings.yml` values cast to their types the same way env values are;
  - the UI delete route moved to `/entries/<id>/delete`;
  - fixes for the CodeQL findings.
- **Docs:**
  - The README was rewritten top-down; What's New shows only the latest two releases.
  - Detailed reference pages: `docs/register-api.md`, `docs/inventory-streams.md` and
    `docs/mqtt-home-assistant.md`.
  - The screenshot gallery is `docs/screenshots.md`, with images named `std_*.png`.
- The handoff-prompt queue is empty; everything is in `prompts/done/`.

## This session's job

Nothing is scoped. Ask the operator what's next. Candidates:

- **GitHub issues still open:**
  - #58: a "ports in use" page across all hosts. Per-container ports already shipped; I
    commented on the issue.
  - #6: link the container name to its image repo.
  - #9: Discord notifications, or "alert after N failed checks".
- **Parked in `docs/FUTURE.md`:**
  - Settings follow-ups (after 0.11.0);
  - small gaps parked after v0.10.1;
  - stream observability follow-ups;
  - the UniFi inventory source;
  - register overwriting some operator edits;
  - service identity and duplicate detection;
  - tools as a first-class concept;
  - the notifier logging STD's API revision.
- **Backup "Later" list:** `docs/design/2026-11-20-backup-export-import.md` §15.

## Known follow-ups (small, unscheduled)

- **Registry retention race:** two retention runs triggered in the same second can try to
  delete the same version, and one fails with a 404. It's harmless, and the operator said
  to leave it. If it's wanted later: add a `concurrency` group to
  `.github/workflows/retention.yml` and treat a 404 on delete as "already gone".
- **The README still needs two screenshots:** the Compact view with the expand chevron
  (`std_compact.png` predates it), and widgets on tiles.
- **The Tiled drawer overlays the tile below** instead of pushing it down. The operator
  noticed it and didn't ask for a change.
- **PRD numbering:** the subsections under §22 are numbered 21.1–21.3 (flagged by the
  README audit, not fixed).
- **A missing setting in `VALID_KEYS`:** `FLASK_SECRET_KEY` can only be set as an env
  variable (documented). Add it to `VALID_KEYS` masked only if the operator wants it
  settable from the file.

## Housekeeping

- Lint: `uvx ruff@0.15.17 check .`. Tests (1,637): `uvx --with-requirements requirements-dev.txt pytest -q`.
- No `Co-authored-by:` trailers (CLAUDE.md wins). The CHANGELOG archive step is skipped on
  minor releases (standing preference).
- MCP version tests are tied to `MCP_VERSION`, so a release bump no longer breaks them.
- CodeQL runs on pull requests to `main`. Five false positives were dismissed for 0.11.0,
  each with a reason. Expect similar flags on path handling and the YAML loader.
