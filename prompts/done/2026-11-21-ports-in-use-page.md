---
name: 2026-11-21-ports-in-use-page
status: completed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: Ports page, GET /api/v1/ports (API revision 6), list_ports MCP tool, tests and docs done; ruff clean, full pytest green
---

# Task: "Ports in use" page, management API route and MCP tool (GitHub #58)

Add one page that lists container ports across **all hosts**, so the operator can answer
"what's on 8080 on host X" and "which ports are free". The same data is also available
as `GET /api/v1/ports` (API revision 6) and as an MCP tool. **No notifier change is
needed:** notifier 0.4.x already sends `exposed_ports` and `published_ports` on every
register (see `~/projects/docker-api-notifier/main.py` `_extract_published_ports`). The
"update DAN" line in #58 is already done, so do **not** touch the register contract or
`schemas.py`.

## Before you start

- Read `CLAUDE.md` (Definition of Done, Register Contract Rules, Module Layout) and
  `standards.md`.
- Read PRD §18.1 (API revision table), §14 (management API conventions) and §24 (the
  most recent feature section, as a model for the shape of a new section).
- Data shapes (`models.py` ~L149):
  - `ServiceEntry.exposed_ports` is JSON like `["5173/tcp", "9000/tcp"]`.
  - `ServiceEntry.published_ports` is JSON like
    `[{"container_port": 5173, "protocol": "tcp", "host_ip": "0.0.0.0", "host_port": 5173}]`.
  - Both can be NULL (an older notifier, or manual and stream entries). Treat malformed
    items defensively: skip them, never 500.
  - These are pure observation. **No UI editing of ports, anywhere.**
- Docker facts the design depends on:
  - Docker usually publishes the same port twice, once for `0.0.0.0` and once for `::`.
    That is **one** binding to the operator, not a conflict.
  - Docker clears `NetworkSettings.Ports` when a container stops, so stopped containers
    report no published ports, but `exposed_ports` (from the image config) remains.
  - `network_mode: host` containers have no published ports; their ports show up only
    as exposed ports, and only if the image declares them.
- Look at these as patterns to match:
  - `routes_dashboard.py` and the three views (`/`, `/tiled_dash`, `/compact_dash`),
    including how they pass `active_tab`;
  - the tab nav in `templates/base.html` (~L46);
  - `view_helpers.py`;
  - `routes_mgmt_api.py` together with `mgmt_openapi.OPERATIONS`, `mgmt_serializers.py`
    and `api_version.py` (`API_REVISION`, revision history, `FEATURES`);
  - `mcp/std_mcp.py` (`@read_tool`);
  - `tests/test_image_updates_ui.py::test_view_query_count_stays_flat` (the
    query-count guard pattern).

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## Scope decided with the operator (2026-11-21)

- **Layout:** both a **grouped-by-host** view (the default; one section per host,
  sorted by host port) and a **flat table**, with a toggle between them.
- **Rows:**
  - published ports;
  - **exposed-only** ports, meaning an exposed `port/proto` that has no published binding
    for the same container port and protocol on that entry. Show these visually dimmed,
    with a "published / exposed / all" **filter**.
- **Out of scope:** ports parsed from manual or stream entry URLs, and remembering the
  last-known ports of stopped containers.
- **Conflicts:** highlight conflicting rows, and show a **conflict count** at the top of
  the page.
- **Placement:**
  - a new top-level **"Ports"** tab in the nav, between Compact and Add;
  - `GET /api/v1/ports` (read scope);
  - an MCP read tool.

## What to do

1. **Pure module `ports.py`** (no Flask and no DB queries; it takes a list of entries
   and returns plain data):
   - **`build_rows(entries)`** returns a list of row dicts with these keys: `entry_id`,
     `name` (display name, same rule as the dashboards), `host`, `container_name`,
     `stack_name`, `docker_status`, `kind` (`"published"` or `"exposed"`), `host_ips`
     (list), `host_port` (int, or None for exposed), `container_port`, `protocol`,
     `conflict` (bool) and `conflict_with` (entry ids).
   - **Collapse** bindings of one entry that share
     `(host_port, container_port, protocol)` into one row with all their `host_ips`
     (this handles the `0.0.0.0` + `::` pair).
   - **Conflict rule:** two rows from **different entries** conflict when all of these
     hold:
     - they are on the same `host` (exact match; skip host NULL);
     - they share the same `protocol` and `host_port`;
     - their IP sets overlap. A wildcard (`""`, `0.0.0.0`, `::`) overlaps everything in
       the same family; to keep it simple, treat any wildcard as overlapping any IP.
       Two different specific IPs do not overlap.
   - **Exposed-only rows never conflict.**
   - **Entries included:**
     - only active entries (`ServiceEntry.active()`, not soft-deleted);
     - skip entries whose `docker_status` is set and isn't `running`, since stopped
       containers are out of scope. Record this in `docs/decisions.md`.
   - **`summarize(rows)`** returns the counts: hosts, published, exposed-only and
     conflicts (the number of conflicting rows, or groups; pick one, document it, and
     use the same definition in the UI and the API).
   - **`filter_rows(rows, kind=, host=, q=, conflicts_only=)`** does the filtering.
     `q` matches name, container name, stack and port as text.
2. **UI route `/ports`** on the dashboard blueprint (login required, like the other
   views). Add the "Ports" tab to `templates/base.html` with `active_tab == 'ports'`.
   - **Query params:**
     - `view=grouped|flat` (default `grouped`);
     - `kind=all|published|exposed` (default `all`);
     - `host`;
     - `q`;
     - `conflicts=true`;
     - for the flat table, `sort` (host, host_port, name, protocol; default host then
       host_port).
     Unknown values fall back to the defaults; they never cause an error.
   - **Rendering:** server-rendered, Tailwind classes matching the existing views.
   - **Rows:**
     - Each row links to the entry. Use the same target the dashboards use for an
       entry; if none fits, use `/edit/<id>`.
     - Conflict rows get a clear red marker with a title or tooltip that names the other
       entries.
     - Exposed-only rows are dimmed and show "exposed".
   - **Summary bar:** "N hosts · N published · N exposed · N conflicts". The conflicts
     count is a link that applies `conflicts=true`.
   - **Grouped view:** one section per host with a per-host count, hosts sorted
     alphabetically, rows by `host_port` (exposed rows last, by container port).
   - **Empty state:** say that ports come from docker-api-notifier 0.4.0+.
   - **No client JS is required.** If you add any, put it in `static/js/` and keep the
     page fully working without it.
   - **Queries:** one query for the entries, whatever their count. Use
     `test_view_query_count_stays_flat` as the pattern for a test.
3. **Management API `GET /api/v1/ports`** (read scope; same filters as query params:
   `kind`, `host`, `q`, `conflicts`). The response is
   `{"summary": {...}, "ports": [...rows...]}`, with the rows from `ports.build_rows`.
   - Validate the query params the same way the other list routes do. An invalid
     `kind` gives the API's standard 400 JSON error.
   - Add the operation to `mgmt_openapi.OPERATIONS` (the tests enforce this), with a
     response TypedDict in `mgmt_schemas.py` if that's the pattern.
   - **Bump `API_REVISION` to 6** with a revision-history entry in `api_version.py`
     (and `FEATURES` if the pattern calls for a feature flag, e.g. `"ports"`).
   - Add the matching PRD §18.1 table row.
4. **MCP tool** `list_ports(kind="all", host=None, query=None, conflicts_only=False)` in
   `mcp/std_mcp.py` as a `@read_tool` calling `GET /api/v1/ports`. Write the docstring
   for an LLM caller: what a conflict means, and that exposed-only ports aren't bound on
   the host. Update `mcp/README.md`'s tool list, and if the MCP has a version or
   minimum-revision check, update it the way previous revisions did.
5. **Tests** (pytest, `tests/test_ports*.py`):
   - **`ports.py` unit tests:**
     - NULL and malformed JSON;
     - collapsing `0.0.0.0` and `::`;
     - exposed-only detection;
     - conflicts: same host and port on two entries; different hosts (none); tcp vs
       udp (none); two different specific IPs (none); wildcard vs a specific IP (yes);
       the same entry twice (none);
     - soft-deleted and stopped entries are excluded;
     - the summary counts.
   - **UI tests:**
     - the page renders the grouped and flat views;
     - the filters and sort work;
     - unknown params fall back to the defaults;
     - the conflict marker and summary are present;
     - the empty state;
     - the tab is in the nav;
     - login is required;
     - the query count stays flat as entries grow.
   - **API tests:**
     - the shape, the filters, and a 400 on a bad `kind`;
     - the read scope is enough;
     - no key gives a 401;
     - `/api/v1/meta` reports revision 6.
   - **MCP test,** if the MCP has tests.
6. **Docs, all in the same commit:**
   - **`CHANGELOG.md`:** under `[Unreleased]` → Added, an operator-facing entry for the
     Ports page, the API route (API revision 6) and the MCP tool.
   - **`docs/PRD.md`:**
     - Add a new **§25** after §24 ("Ports in use (Unreleased)"; the release prep will
       rename it) covering: the data source, the inclusion rules, the conflict rule,
       the UI, the API and the MCP tool, and what's out of scope (URL ports, stopped
       containers, host-network containers being visible only through exposed ports).
     - Add the §18.1 row for revision 6.
     - Bump the revision-history table.
   - **`README.md`:** mention the Ports view where the views are described, and the
     API route and MCP tool where those are listed.
   - **`docs/screenshots.md`:** add `std_ports.png` (grouped view, ideally with a
     conflict) to the list of screenshots to take. Don't create the image.
   - **`docs/FUTURE.md`:** park "ports from manual/stream URLs" and "remember last-known
     ports of stopped containers".
   - **`docs/decisions.md`** (newest at top):
     - stopped containers are excluded;
     - the wildcard-overlaps-everything simplification;
     - the `0.0.0.0` + `::` collapse;
     - the definition of the conflict count.
7. **Verify:**
   - `uvx ruff@0.15.17 check .` is clean;
   - `uvx --with-requirements requirements-dev.txt pytest -q` passes in full (1,915+
     tests);
   - write host checks as `urlsplit(url).hostname == ...`, never substring checks
     (CodeQL).

## Conventions to honor

- Server-side code reads settings from the app config, never `load_settings()` in a route.
- No migration is needed: this reads existing columns. If you find you need one, stop and
  report instead.
- Commit prefix: `feat:`. No `Co-authored-by:` trailers (CLAUDE.md wins).
- Keep `ports.py` pure so the UI and the API share exactly one implementation.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. Move this file into `prompts/done/` (on success) or `prompts/failed/` (on failure).
   It is untracked, so use a plain `mv`, not `git mv`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. **You are a spawned agent: do not commit.** Prepare the working tree, then report
   back:
   - the file list;
   - the proposed one-line message (e.g. `feat: ports in use page, GET /api/v1/ports
     (API revision 6) and list_ports MCP tool`);
   - the lint and test results.
   Never `git add -A`, never push.
