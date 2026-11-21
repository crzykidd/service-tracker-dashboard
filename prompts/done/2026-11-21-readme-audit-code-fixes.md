---
name: 2026-11-21-readme-audit-code-fixes
status: completed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: all four fixes done; ruff clean; pytest green apart from the other agent in-progress test_compact_details
---

# Task: Fix the code issues found by the README audit

The README audit found four code problems:

1. `app.py:119` reads `settings.get("STD_DOZZLE_URL")`, an uppercase key that never exists in the settings. It only works because `app.config.update(settings)` overwrites it later. The line is dead and misleading.
2. `jobs.py` `start_background_workers`, around line 734: an invalid `widget_background_reload` falls back to 300, but the documented default is 900.
3. `settings.yml` values are not type-cast; only environment values are (`settings_loader.py`). A quoted `"5"` in the file stays a string, so `isinstance(x, int)` checks silently fall back to defaults. The integer fallback in item 2 is one example.
4. `/api/v1/entries/<id>/delete` (`routes_dashboard.py:1623`, `dashboard_bp`) is a session-login UI route that sits under the management API prefix. It is not in the OpenAPI spec. It is called from `static/js/dashboard.js` (around line 362) and `templates/edit_entry.html` (around line 477).

## Before you start

- Read `CLAUDE.md`, `settings_loader.py` (how env values are cast and which keys are valid), `app.py`, `jobs.py` and `mgmt_openapi.py`.
- Read the completeness tests for the `/api/v1` routes and OpenAPI: `grep -ln "url_map\|OPERATIONS" tests/*.py`. Find out why the delete route is exempt.
- Read `docs/PRD.md`'s settings and route sections.
- **Another agent is working in parallel** on the Compact view's details dialog. It owns:
  - `CHANGELOG.md`, `README.md` and `docs/PRD.md`;
  - `templates/compact_dash.html`, `static/css/dashboard.css` and any new compact JS;
  - a new `/service/<id>/details` route near `/service/<id>/health` in `routes_dashboard.py`.

  **Do not edit those files** (in `routes_dashboard.py`, touch only the delete route). Put your CHANGELOG lines and any PRD/README text in your report; the orchestrator adds them. Don't edit `docs/decisions.md` either; list decision notes in your report.

## Working tree check

Run `git status --porcelain`. The other agent's files will be dirty: ignore them. If a file you need is dirty for another reason, stop and report.

## What to do

1. Change the Dozzle line in `app.py` to read the lowercase key, e.g. `os.getenv("STD_DOZZLE_URL", settings.get("std_dozzle_url", ""))`, or remove it if `app.config.update(settings)` already covers both sources. Check what `load_settings` does with env vars first, and keep the behavior identical.
2. Change the `jobs.py` fallback to 900, from one named constant shared with wherever the default is defined (`settings_loader.py` defaults, if it has them).
3. Cast `settings.yml` values the same way env values are cast. Reuse the existing env casting (int, bool, etc.) for file values, keyed by the same type table.
   - Don't change which keys are valid, and don't change the precedence.
   - An uncastable file value logs a warning and keeps today's behavior (the raw value, or the default if that's what env does today; match env).
   - Add tests: a quoted `"5"` in the file becomes `5`; a bool string becomes a bool; env still overrides the file.
4. Move the delete UI route to a non-API path on `dashboard_bp`, e.g. `POST /entries/<id>/delete`.
   - Keep the endpoint name, unless tests or `url_for` calls need it changed.
   - Update both callers. Prefer a `url_for`-built URL passed through a data attribute, or keep a template literal if that's the existing pattern.
   - Remove any exemption that existed only for this route from the API completeness tests.
   - CSRF and login must behave as before. Make sure a session-less API client calling the old path now gets the normal JSON 404 for unmatched `/api/v1/*`.
   - Update the tests that post to the old path.
5. Run `uvx ruff@0.15.17 check .` and the full `uvx --with-requirements requirements-dev.txt pytest -q`. Both must be green.

## When done

1. Set this file's frontmatter: `status`, `completed` and `result`.
2. Move it to `prompts/done/` with plain `mv` (it is untracked).
3. You are a spawned agent, so do **not** commit. Report back with:
   - the exact files changed;
   - a proposed `fix:` commit message;
   - the CHANGELOG lines (Fixed/Changed);
   - any PRD/README text to change, quoting the current text;
   - decision notes;
   - the test results.
