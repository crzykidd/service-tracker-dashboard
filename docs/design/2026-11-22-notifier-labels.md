# Design note: what docker-api-notifier sends, and which STD settings Docker labels could set

**Status:** research, awaiting operator decisions (2026-11-22). No code has changed.
**Code read:** STD `dev` at `ceceaae`; docker-api-notifier at v0.4.3 (`main.py`,
`notifiers/service_tracker_dashboard.py`, `image_info.py`). Where this note and the code
disagree, trust the code.
**Purpose:** input for the next notifier handoff (0.5.x). That handoff already carries
`image_info`, and the network details (driver, IPs, MAC) are planned in
`prompts/2026-11-22-network-details-macvlan.md`.

## 1. What the notifier sends today

The base payload is built at `main.py:197-209` and translated at
`notifiers/service_tracker_dashboard.py:19-86`.

| Payload key | Source |
|---|---|
| `host` | the `HOST_NAME_OVERRIDE` env, else `/etc/host_hostname`, else `uname` |
| `container_name`, `container_id`, `docker_status`, `started_at`, `image_name` | container attributes |
| `stack_name` | the label `com.docker.compose.project` |
| `networks` | `NetworkSettings.Networks`: name and aliases only |
| `exposed_ports`, `published_ports` | `Config.ExposedPorts`, `NetworkSettings.Ports` |
| `exposure_observations` | interpreters (Traefik, Dockflare, YAML files in `/app/interpreters/`) |
| `image_info` | image inspect; only sent when `STD_SEND_IMAGE_INFO` is on and STD's `/meta` lists `image_info` |

**Labels the notifier reads:**
- `dockernotifier.notifiers`: `dns` and/or `service-tracker-dashboard`.
  `STD_REPORT_ALL_CONTAINERS` overrides it for STD.
- **DNS:** `dockernotifier.dns.containerhostname`, `.containerzone`, `.dockerdomain`.
- **STD:** the prefix is stripped, then a whitelist applies:
  - `dockernotifier.std.internalurl` and `.externalurl`;
  - `.internal.health` and `.external.health` (bool);
  - `.group` → `group_name`;
  - `.icon` → `image_icon`;
  - `.sort.priority` → `sort_priority` (int);
  - anything else is dropped.

**Gaps:** every field STD's register schema accepts is already reachable from the notifier.
Nothing more can be set from labels without an STD schema change.

## 2. STD settings that only the UI or the management API can set

| Setting | From a label? | Notes |
|---|---|---|
| `description` | **Yes** | Natural compose metadata. |
| `image_update_policy` / `image_update_scope` / `image_tag_pattern` | **Yes, high value** | Pinning a database, or "patch only", belongs in compose. Needs a provenance column, because the policy defaults to `auto`, not NULL. |
| `image_repo_url` | **Yes** | An operator override today; needs provenance, and a UI edit wins. |
| URL-check settings (mode, interval, timeout, verify_tls, cert_min_days) | Maybe | Send them as a typed nested object, not flat keys. |
| `ha_publish` | Maybe | Changes the "register never writes it" rule. |
| Service checks | Later | Already parked in FUTURE.md. |
| `locked` / `is_static` | **No** | A locked entry skips register, so a label could never unlock it. |
| Widget config | **No** | It carries a secret, and labels are readable by anyone who can run `docker inspect`. |
| Group icon / group sort | **No** | Group-level, so several containers would fight over it. |
| `name` / `host` | **No** | They are the register key. |

## 3. Recommended order

**Rule for every new label-driven field:**
- STD ships first and advertises the field in `/api/v1/meta` `FEATURES`; the notifier sends
  it only once it is advertised.
- Each field gets a `<field>_source` column. A UI edit wins.
- An absent label means "leave alone".

1. **`dockernotifier.std.skip=true`.** Notifier-only, with no payload change, so it can ship
   alone.
2. **Prerequisite: fix the existing clobbers.**
   - **Icon:** register overwrites a UI-chosen icon on every call (`routes_api.py` ~L283).
     Add `image_icon_source`.
   - **Health toggles:** they overwrite UI edits (FUTURE.md "Register overwrites some
     operator edits"). Fix this before adding more label-owned fields, or the new ones
     inherit the same bug.
3. **`dockernotifier.std.description`.**
4. **`dockernotifier.std.image_update.policy` / `.scope` / `.tag_pattern`.**
5. **`dockernotifier.std.image_repo_url`.**
6. **URL-check settings** as a typed nested object.
7. **A generic pass-through** `dockernotifier.std.attr.<k>` → `attributes` (display only,
   never interpreted, like stream `attributes`).

## 4. Pitfalls found in the code

- **Notifier: label and base-key collision.** A label such as
  `dockernotifier.std.container_name` / `.networks` / `.image_name` makes
  `register(**base_kwargs, **std_extras)` raise `TypeError` (`main.py:252`), and that
  container never registers. Strip the reserved keys.
- **Notifier: `dockernotifier.std.host`** silently overrides the host.
- **Notifier: bad bool labels.** A typo like `ture` reads as False and turns a check off.
  Unparsable ints are dropped silently. Log a warning for both.
- **Notifier: capability gate.** The gate and the 400-retry cover only `image_info`
  (`service_tracker_dashboard.py:264-312`). One unknown network key would 400 every payload
  from that host. Make the gate a generic per-feature check: `image_info`,
  `network_details`, and future fields.
- **STD: absent vs null.** The register handler reads `payload.model_dump()`, so a top-level
  key is always present (as None when absent). Any new "absent = leave alone" field must use
  `payload.model_fields_set`, not `in canonical`.
- **STD: an empty label can't clear a URL.** Removing a URL label leaves the `explicit_label`
  value in place forever.
- **STD: health toggles on new rows.** On a new row, an absent health toggle creates the
  check as disabled. On an existing row, an absent toggle means "no change".
