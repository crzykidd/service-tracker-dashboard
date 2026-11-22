---
name: 2026-11-22-network-details-macvlan
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: "network details accepted on register; ports page has host_network and direct kinds; ruff clean, 1981 tests pass"
---

# Task: Network details on register (driver, IPs, MAC) and macvlan / ipvlan / host-network awareness on the Ports page

Today the register payload's `networks` items are `{"name", "aliases"}`. That was a
deliberate early decision ("names only, IPs are intentionally not captured", PRD §5 ~L450 and
`schemas.NetworkMembership`). Because of it, STD can't see the cases the Ports page gets
wrong:

- **macvlan / ipvlan:** the container has its **own LAN IP**, so every port it listens on is
  reachable at `<container IP>:<port>` without being published. Docker ignores published
  ports on these drivers.
- **host network** (`network_mode: host`, network name `host`): the container's ports are
  bound **directly on the host**. They can clash with the host ports other containers
  publish.

This task is the **STD half**: STD accepts the fields first (the ordering rule). The notifier
(docker-api-notifier 0.5.x) sends them later, from its own repo. **Don't touch the notifier
repo.**

## Before you start

- Read `CLAUDE.md`: the Register Contract Rules, the Cross-Repo ordering rule, and the
  safe-degradation guarantee. Also read `docs/register-api.md`, PRD §5 (`networks` column),
  §18.1, §22 and §25 (the Ports page), and `ports.py`.
- Run `git status --porcelain`. The tree should be clean apart from this prompt; if not,
  list the dirty files and stop.

## What to do

1. **Schema (`schemas.py`, `NetworkMembership`):** add **optional** fields, all defaulting
   to None, and keep `extra="forbid"`:
   - `driver: str | None`. Lowercase it, at most 32 characters, and accept any value
     (`bridge`, `macvlan`, `ipvlan`, `host`, `overlay`, `none`, plugins).
   - `ip_address: str | None` (IPv4) and `ipv6_address: str | None`. Validate them with
     `ipaddress` and store the canonical form. An empty string means None. Docker sends
     `""` when there is no address.
   - `mac_address: str | None`. Normalize it with the same rule as
     `streams.normalize_mac`; an empty string means None.
   - **Errors:** an invalid IP or MAC is a 400 like any schema error. Check how the
     register handler reports these and stay consistent.
   - **Old notifiers:** a payload that omits all of these (an older notifier) must work
     exactly as before.
2. **Storage:** the values live inside the existing `service_entry.networks` JSON items.
   That needs **no migration**; confirm it. The column stays pure observation: overwritten
   on every register, with no UI editing.
3. **API revision:** API revision 6 is unreleased (it added `/api/v1/ports`), so **extend
   the revision 6 row** instead of adding a 7. This follows the precedent of revision 5,
   which was extended within 0.12.0.
   - Add a `network_details` entry to `api_version.FEATURES`. The notifier will gate on
     it via `/api/v1/meta`, the same way it gates `image_info`.
   - Update the revision history in `api_version.py` and the PRD §18.1 row.
4. **Entry details** (`templates/partials/entry_facts.html` and wherever the networks
   list renders, including the edit page if it shows them): show each network's name plus,
   when known, its driver, IPv4/IPv6 and MAC, e.g. `lan_macvlan (macvlan) 192.168.1.50`.
   Older data without these keys renders as today.
5. **Ports page (`ports.py`, template, API rows):**
   - **New row kinds:**
     - **`direct`** is for an entry attached to a `macvlan` or `ipvlan` network that has
       an IP. Its exposed ports (and the container ports of any published ones, which
       Docker ignores on these drivers anyway) become reachable at that IP. Set
       `host_ips` to the network IP(s), `host_port` to the container port, and add a new
       row key `network` with the network name.
     - **`host_network`** is for an entry on the `host` network. Its exposed ports are
       bound on the host: set `host_port` to the container port and `host_ips` to
       wildcard.
   - **Conflicts:**
     - `host_network` rows take part in the host-port conflict rule with published rows,
       on the same host, protocol and port.
     - `direct` rows never conflict with host ports. They conflict only with another
       `direct` row with the same IP, protocol and port.
   - **Order:** published, then host network, then direct, then not published.
   - **UI labels:** "host network" and "direct (macvlan)" / "direct (ipvlan)".
   - **Show filter:** gains these kinds. If the ports-sort prompt has already landed,
     check how it did the labels and filter and follow the same pattern.
   - **Summary:** gains counts for the new kinds.
   - **API:** `kind` accepts `direct` and `host_network`, and the summary gains the new
     counts. This is part of revision 6, so it's additive.
   - **Older data:** an entry whose networks have no driver behaves exactly as today. An
     entry on the network named `host` is treated as host network **even without a
     driver** (the name is reserved by Docker). Write that down in PRD §25.
6. **MCP:** update the `list_ports` docstring for the new kinds. If the MCP shows
   networks anywhere, show the new fields there too.
7. **Export/import:** check `export_format.py` and the ownership table (PRD §20.2). If
   networks are exported, make sure the new keys round-trip or are deliberately excluded,
   and say which you chose.
8. **Tests:**
   - schema accept and reject: a valid IP, an invalid IP, `""` treated as None, MAC
     normalization, and an unknown key in a network item still giving 400;
   - an older payload without the fields;
   - the details rendering;
   - the Ports rows for macvlan, ipvlan and host network, with and without a driver;
   - the conflict rules for the new kinds;
   - the API `kind` filter;
   - `/api/v1/meta` FEATURES containing `network_details`;
   - the query count still flat.
9. **Docs, all in the same commit:**
   - **CHANGELOG `[Unreleased]`:**
     - **Added:** STD accepts network driver, IPs and MAC from docker-api-notifier, shown
       in the details and used by the Ports page. Note that it needs a notifier version
       that sends them, coming in docker-api-notifier 0.5.x.
     - Also amend the Ports entry.
   - **PRD:**
     - §5 networks column: revise "names only";
     - §18.1 revision 6 row;
     - §22 cross-repo, with the pending notifier change (the driver needs a network
       inspect, cached per network id);
     - §25;
     - a revision-history row.
   - **`docs/register-api.md`:** the new optional fields in the example and the field
     table.
   - **README:** if it lists the register fields.
   - **`docs/decisions.md`:**
     - reversing "names only", and why: the Ports page needs addresses to be correct for
       macvlan/ipvlan, and the STD install is the operator's own network;
     - the `host` name rule.
   - **`CLAUDE.md` Cross-Repo "Version pairing history":** add a line saying STD accepts
     `networks[].driver/ip_address/ipv6_address/mac_address` from the next release, and
     the notifier sends them from 0.5.x.
10. **Verify:** `uvx ruff@0.15.17 check .` and
    `uvx --with-requirements requirements-dev.txt pytest -q` are both green. Write host
    checks as `urlsplit(url).hostname == ...` (CodeQL).

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. `mv` it (it's untracked) to `prompts/done/` or `prompts/failed/`.
3. **You are a spawned agent: do not commit.** Report back:
   - the file list;
   - a proposed one-line message (e.g. `feat: network driver, IPs and MAC on register;
     ports page understands macvlan, ipvlan and host network`);
   - the lint and test results;
   - any deviations;
   - the exact field shapes the notifier must send, for its handoff prompt.
