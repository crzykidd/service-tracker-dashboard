# Register API reference

How [docker-api-notifier](https://github.com/crzykidd/docker-api-notifier) (or any
producer) registers containers in STD. The overview is in the
[README](../README.md#docker-docker-api-notifier); this page is the full contract. The
source of truth is `schemas.py` (`RegisterPayload`).

`/api/v1/register` is the only register endpoint. The legacy `/api/register` shim
was removed in 0.6.0; producers must run docker-api-notifier 0.3.0+ or send
canonical-key payloads directly.

## Endpoint

```
POST /api/v1/register
Authorization: Bearer <API_TOKEN>
Content-Type: application/json
```

The token is `api_token` (`API_TOKEN`). If it is not set, register answers `503`
until it is. The token is register-only: it cannot call the management API, and a
management API key is rejected here. Give your producer a `User-Agent:
name/version`; STD logs each distinct one once per restart.

## Canonical payload

```json
{
  "host": "docker01",
  "container_name": "nginx",
  "container_id": "abc123...",
  "image_name": "ghcr.io/user/nginx:latest",
  "image_icon": "nginx.svg",
  "docker_status": "running",
  "stack_name": "frontend",
  "started_at": "2026-05-10T12:34:56Z",
  "timestamp": "2026-05-10T12:35:00Z",
  "internalurl": "http://nginx:80",
  "externalurl": "https://my.domain.com",
  "internal_health_check_enabled": true,
  "external_health_check_enabled": true,
  "group_name": "web",
  "sort_priority": 1,
  "networks": [
    {"name": "proxy", "aliases": ["frontend"]},
    {"name": "ammoledger_default", "aliases": ["frontend"]}
  ],
  "exposed_ports": ["5173/tcp"],
  "published_ports": [
    {"container_port": 5173, "protocol": "tcp",
     "host_ip": "0.0.0.0", "host_port": 8080}
  ],
  "exposure_observations": [
    {"layer": "traefik", "hostname": "nginx.internal.example",
     "tls": true, "path_prefix": null, "auth": null, "details": null},
    {"layer": "dockflare", "hostname": "nginx.example.com",
     "tls": true, "path_prefix": null,
     "auth": "cloudflare_access:authenticate", "details": null}
  ]
}
```

## Required fields

- `host`: the Docker host name. Together with `container_name` it is the key of an
  entry.
- `container_name`: the name of the container.

Everything else is optional, and STD applies defaults for any field that is missing.

`/api/v1/register` is **strict**: unknown keys are rejected with a `400` and the list
of offending keys in the response body. Nested structures (`networks`,
`published_ports`, `exposure_observations`) are validated too, and malformed entries
are rejected at the schema boundary.

## Matching, adoption and locks

- A register for a `(host, container_name)` that has no entry creates one (source
  Docker). One that matches a soft-deleted entry restores it, with its group, sort
  priority and edits.
- An unlocked **manual** entry with the same host and name is adopted: it becomes a
  Docker entry and keeps its id, checks and history.
- An entry with **Lock (ignore notifier updates)** ticked is not touched by register.
- Inventory stream entries are never matched by register.

## Field ownership: user_wins vs notifier_wins

`group_name` and `sort_priority` can also be edited in the web UI. When a register
arrives for an entry whose UI value differs, the `register_field_ownership` setting
decides who wins:

- **`user_wins`** (default): UI edits stick. The notifier may fill these fields on a
  new entry or one where they are still empty, but it does not overwrite a value you
  set.
- **`notifier_wins`**: every register overwrites them, UI edits included. Choose this
  if your container labels are the source of truth.

Either way STD records what the notifier sent in `notifier_reported_group_name` and
`notifier_reported_sort_priority`. These are not shown in the UI.

## Network and port capture

`networks`, `exposed_ports` and `published_ports` are pure observation: STD overwrites
them on every register, with no ownership rules. docker-api-notifier 0.4.0+ sends them;
older notifiers leave them empty.

The read-only **Reported by notifier** block at the bottom of the Edit page shows
them ("Not reported" when empty). Manual entries have no such block.

## Exposure observations and URL synthesis

`exposure_observations` carries the output of the notifier's YAML interpreters
(Traefik, Dockflare, ...). docker-api-notifier 0.4.0+ emits one observation per
interpreter that recognizes the container. STD stores them and runs a synthesizer
that may fill `internalurl` / `externalurl` for you.

Tell STD what each layer means in **Settings → Docker**. Each layer that has been
observed gets a direction:

- **internal**: the synthesized hostname fills `internalurl`.
- **external**: the synthesized hostname fills `externalurl`.
- **neither** (default): STD records the observation and shows a badge, but does not
  build a URL from it.

Per-host overrides (one collapsible group per host) let you say "Traefik on the home
host is internal, but Traefik on the edge VPS is external". Changes are saved with
**Save & recompute URLs** in the bar that appears at the bottom. The **Docker
(register)** card at the top shows how many entries the notifier registered and when
it last did.

### URL provenance

STD tracks who last wrote each URL. Weakest first:

1. **empty**: no value. The synthesizer may fill it.
2. **`synthesized`**: from the synthesizer. Every register and every Docker settings
   save may change it.
3. **`explicit_label`**: from a `dockernotifier.std.internalurl` / `.externalurl`
   label. The synthesizer does not overwrite it; a new label value updates it; a UI
   edit overrides it.
4. **`ui_edit`**: you typed it in the UI. Nothing overrides it until another UI edit.
   Clearing the field resets it to empty so synthesis can resume.

The Edit page shows the source next to each URL.

### Wire-level semantics

- `exposure_observations` **absent** or **null**: "no update". Existing exposure rows
  are kept. This is what pre-0.4.0 notifiers send.
- `exposure_observations: []`: "no interpreter matches this container". All exposure
  rows of the entry are cleared, and the synthesizer may clear a `synthesized` URL.
- `exposure_observations: [ ... ]`: wholesale replacement. The old rows are dropped,
  the new ones stored, and the synthesizer recomputes the URLs (respecting provenance).

### Badges and headless entries

Each tile (Tiled) and row (Dashboard) shows up to three exposure badges, one brand logo
per proxy layer (Traefik, Cloudflare, ...) however many routes it has. Hover a logo for
the route count and each route's hostname, TLS and auth. A `+N` badge appears when more
than three layers see the entry.

An entry with no exposure observations **and** no URLs is "headless": its tile has no
click target and relies on the Docker status. **Show URL-less** off
(`?show_urlless=false`) hides them.

## Container labels

With docker-api-notifier on each Docker host you can drive STD from compose labels:

```yaml
labels:
  dockernotifier.notifiers: service-tracker-dashboard
  dockernotifier.std.internalurl: http://nginx:80
  dockernotifier.std.externalurl: https://nginx.domain.com
  dockernotifier.std.group: web
  dockernotifier.std.internal.health: "true"
  dockernotifier.std.sort.priority: "1"
```

The full label list belongs to the notifier; see its README.

## Compatibility

| STD | docker-api-notifier | Notes |
|---|---|---|
| 0.5.0 | 0.3.0 | `/api/v1/register` with canonical keys |
| 0.6.0+ | 0.3.0+ | `/api/register` removed |
| 0.6.0+ | 0.4.0+ | network, port and exposure capture |

A newer STD always accepts an older notifier: the capture fields stay empty and a
missing `exposure_observations` keeps the existing rows.
