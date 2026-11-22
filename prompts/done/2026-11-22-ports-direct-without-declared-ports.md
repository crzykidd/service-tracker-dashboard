---
name: 2026-11-22-ports-direct-without-declared-ports
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: ports_unknown rows, URL-derived ports, API revision 7; docs and tests updated; ruff and pytest green; not committed
---

# Task: Ports page shows macvlan / ipvlan / host-network containers that declare no ports (fix for 0.13.1)

**Bug, found live on 2026-11-22.** Home Assistant runs on macvlan networks. It's on four
networks:
- `ha-crzynet` 10.100.20.11 and `ha-iot` 10.100.32.11 (macvlan);
- `ha-backend` and `traefik` (bridge).

Its image declares **no ports**: `docker inspect` gives `Config.ExposedPorts = null`, and
it has no `ports:` either. The notifier (0.6.0 dev) sends the network details correctly.
But `ports.build_rows` (`ports.py` ~L196-209) only creates `direct` / `host_network` rows
for ports it knows, so **Home Assistant doesn't appear on the Ports page at all.** The same
gap hits any host-network container whose image declares nothing; Home Assistant itself is
often run with `network_mode: host`.

## Before you start

- Read `CLAUDE.md`, PRD §25 and §18.1, `ports.py`, `templates/ports.html`,
  `tests/test_ports.py`, the `list_ports` MCP tool in `mcp/std_mcp.py`, and the ports
  response types in `mgmt_schemas.py` and `mgmt_openapi.py`.
- Run `git status --porcelain`. The tree should be clean apart from this prompt; if not,
  list the files and stop.

## What to do

1. **Ports learned from the entry's own URLs** (`ports.py`).
   - For each `direct` network IP of an entry: if `internalurl` or `externalurl` parses
     with `urlsplit(url).hostname == <that IP>`, add the URL's port as `(port, "tcp")`
     to that entry's listening ports.
     - The URL's port is `urlsplit(url).port`, or 80 / 443 from the scheme when the URL
       has no port.
     - Compare IPs in canonical form, e.g. with `ipaddress`.
   - For `host_network`, there's no reliable host IP to match, so skip this.
   - Add the row key `port_source`: `"declared"` (the image's exposed ports, or the
     container side of a published binding) or `"url"`.
2. **A row when no ports are known.**
   - **Which entries:** one whose listening set is still empty after step 1, on a
     macvlan/ipvlan network with an IP, or on the host network.
   - **The row:** one row per direct network, or one row for the host network, with
     `container_port = None`, `host_port = None`, `protocol = None` and the new key
     `ports_unknown = True`. Every other row gets `ports_unknown = False`.
   - **Conflicts:** these rows never conflict.
   - **Sorting:** they sort after the rows of the same kind that have ports. Make every
     sort key None-safe.
   - **Search and filter:** they match the search on name, IP and network, and they
     count in the summary under their kind.
3. **UI** (`templates/ports.html`): for a `ports_unknown` row, show the IP(s) and network
   as usual, and in the port columns show **"all ports (none declared)"**.
   - Add a tooltip: "The image declares no ports and none are published; any port the
     container listens on is reachable at this address. Set the entry's internal URL to
     `http://<ip>:<port>` to show the port here."
   - Mark URL-derived ports subtly, e.g. "from URL" in the tooltip.
4. **API** (`GET /api/v1/ports`): this is an additive response change, so bump
   **`API_REVISION` to 7** in `api_version.py`.
   - Add a revision-history entry: "ports rows: `ports_unknown` and `port_source`;
     `container_port` / `host_port` / `protocol` may be null when `ports_unknown`".
   - Add the PRD §18.1 row for 7, version 0.13.1.
   - Update the response TypedDict and OpenAPI types to nullable.
   - Update the `list_ports` MCP docstring.
   - **The design note `docs/design/2026-11-22-moves-and-label-settings.md` plans its
     label fields as "API revision 7".** Renumber every mention there to **8**, and say
     in one line why: 7 went to this 0.13.1 fix.
5. **Tests** (`tests/test_ports.py`):
   - A Home-Assistant-shaped entry gives two `direct` rows with `ports_unknown`, and no
     `exposed` rows. Its shape is four networks (two macvlan with IPs, two bridge),
     `exposed_ports` None and `published_ports` [].
   - With `internalurl = "http://10.100.20.11:8123"`, the `ha-crzynet` row becomes
     8123/tcp with `port_source == "url"`, and `ha-iot` still shows `ports_unknown`.
   - The scheme default port: `https://10.100.20.11/`.
   - A URL host that isn't the IP (a hostname) is not used.
   - A host-network entry with no ports gives one row.
   - These rows never conflict.
   - Sorting with None values, under every sort, in both views.
   - Search and the kind filter.
   - The API row shape and `/api/v1/meta` revision 7.
   - The existing query-count guard still passes.
6. **Docs, all in the same commit:**
   - **CHANGELOG:** add a new `## [Unreleased]` → `### Fixed` entry in operator words:
     "Containers on macvlan, ipvlan or the host network whose image declares no ports
     (Home Assistant, for example) now show on the Ports page, as 'all ports (none
     declared)', or with the port from the entry's internal or external URL when it
     points at the container's address." Also mention API revision 7.
   - **PRD:** §25 (rows and inclusion, the page, the API), the §18.1 row, and a
     revision-history row.
   - **README:** the `/ports` row and the API revision table row 7.
   - **`docs/decisions.md`:**
     - why a row shows with no port;
     - why URL ports only count when the URL host is the container's own IP;
     - revision 7 used for a patch, with the label work moved to 8.
7. **Verify:** `uvx ruff@0.15.17 check .` and
   `uvx --with-requirements requirements-dev.txt pytest -q` are both green.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `mv` it (it's untracked) to `prompts/done/` or `prompts/failed/`.
3. **You are a spawned agent: do not commit.** Report back the file list, a proposed
   one-line message (e.g. `fix: ports page shows macvlan/ipvlan/host-network containers
   that declare no ports (API revision 7)`), the lint and test results, and any
   deviations.
