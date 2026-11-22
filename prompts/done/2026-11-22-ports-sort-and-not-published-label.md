---
name: 2026-11-22-ports-sort-and-not-published-label
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: Ports sort by state then name (default), sort in both views, "not published" label; ruff clean, 1953 tests passed
---

# Task: Ports page: sort by state, then by container name; relabel "exposed" as "not published"

Two operator requests for the Ports page (PRD §25, unreleased; `ports.py`,
`templates/ports.html`, `static/js/ports.js`, the `ports_page` route in
`routes_dashboard.py`):

1. **Sort by state first, then by the chosen key.** Published rows always come first, then
   the not-published rows, and within each state the rows are sorted. The default sort is
   **container name, A to Z**. The sort control shows in **both** views; today it is
   flat-only.
2. **"exposed" is the wrong word.** An exposed-only port is a port the image declares but
   doesn't publish on the host, so it isn't reachable from outside on that host. In the UI,
   relabel it **"not published"** everywhere:
   - the State column;
   - the Show filter (`all / published / not published`);
   - the summary bar ("N not published");
   - the empty and no-match text, tooltips, and the PRD/README/CHANGELOG wording.

   The **API is unchanged.** `GET /api/v1/ports` keeps `kind: "exposed"` and
   `summary.exposed`. That's Docker's own term and matches the `exposed_ports` data, so
   there's no wire change. The `kind=exposed` query param keeps working on the page too.
   Document the label/value split in PRD §25.

## Before you start

- Read `CLAUDE.md` and PRD §25.
- Run `git status --porcelain`. The tree should be clean apart from this prompt. If other
  files are dirty, list them and stop.

## What to do

1. **`ports.py`:**
   - Sorts are `name` (default; container name, case-insensitive), `port` (host port for
     published rows, container port for not-published rows), `host` and `protocol`.
   - Every sort orders by state first (published, then exposed) and breaks ties stably
     (host, port, protocol, entry id).
   - `group_by_host` takes the sort, so each host section uses the same order.
   - Keep `host_port` as an accepted alias of `port`, so saved browser states and old
     links keep working.
   - Update `normalize_sort`, `SORTS` and `DEFAULT_SORT`.
2. **Route and template:**
   - Pass the sort to both views and show the Sort select in both. `host` makes no sense
     inside one host's section, so offer only name/port/protocol in the grouped view; if
     `host` arrives there, fall back to the default.
   - Apply the label changes from point 2 above. `data-kind` attributes can stay `exposed`.
3. **Tests:** update `tests/test_ports.py` for the new default order, both views, the alias,
   the labels in the HTML, and the API still answering `kind: "exposed"`.
4. **Docs:**
   - **CHANGELOG:** amend the existing `[Unreleased]` Ports entry; it's unreleased, so
     rewrite it rather than adding a "Changed" item.
   - **PRD §25:** update it and add a revision-history row.
   - **README:** update the `/ports` row.
5. **Verify:** `uvx ruff@0.15.17 check .` and
   `uvx --with-requirements requirements-dev.txt pytest -q` are both green.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `mv` it (it's untracked) to `prompts/done/` or `prompts/failed/`.
3. **You are a spawned agent: do not commit.** Report back the file list, a proposed
   one-line message (e.g. `feat: ports page sorts by state then container name; "not
   published" label`), the lint and test results, and any deviations.
