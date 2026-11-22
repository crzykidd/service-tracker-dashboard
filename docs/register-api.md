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
    {"name": "proxy", "aliases": ["frontend"], "driver": "bridge",
     "ip_address": "172.18.0.5", "ipv6_address": null,
     "mac_address": "02:42:ac:12:00:05"},
    {"name": "lan_macvlan", "aliases": [], "driver": "macvlan",
     "ip_address": "192.168.1.50", "ipv6_address": "", "mac_address": ""}
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
  ],
  "image_info": {
    "id": "sha256:1f2e...",
    "repo_digests": ["ghcr.io/user/nginx@sha256:9a8b...c0de"],
    "created": "2026-11-01T08:00:00Z",
    "version": "1.27.2",
    "revision": "4d5e6f7",
    "source": "https://github.com/nginx/nginx"
  }
}
```

## Required fields

- `host`: the Docker host name. Together with `container_name` it is the key of an
  entry.
- `container_name`: the name of the container.

Everything else is optional, and STD applies defaults for any field that is missing.

`/api/v1/register` is **strict**: unknown keys are rejected with a `400` and the list
of offending keys in the response body. Nested structures (`networks`,
`published_ports`, `exposure_observations`, `image_info`) are validated too, and malformed entries
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

Each `networks` item has `name` (required), `aliases` (list, default `[]`) and, since API
revision 6, four optional fields (feature `network_details` in `GET /api/v1/meta`):

| Field | Type | Rule |
|-------|------|------|
| `driver` | string | Lowercased, at most 32 characters; any value (`bridge`, `macvlan`, `ipvlan`, `host`, `overlay`, `none`, plugin names). |
| `ip_address` | string | IPv4; stored in canonical form. |
| `ipv6_address` | string | IPv6; stored in canonical form. |
| `mac_address` | string | Stored as lowercase `aa:bb:cc:dd:ee:ff`; `-`, dotted and bare forms are accepted. |

`null`, absent and `""` (what Docker sends for "no address") all mean not reported; the key is
then not stored. An invalid address or MAC is a 400 like any schema error, and an unknown key
in an item is still rejected. An older notifier that omits them keeps working unchanged. They
show in the entry details and drive the macvlan, ipvlan and host-network rows of the Ports
page: a macvlan/ipvlan container is reachable at its own address, and a network named `host`
means the container's ports are bound on the host. They are not exported.

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

### The running image (`image_info`, API revision 5)

`image_info` tells STD which image the container was created from, so the optional
[image update check](../README.md#image-update-check) can compare it with the registry.
It is observation only: STD stores it, never lets anyone edit it, and does not export it.
Every field is optional and the object is strict (unknown keys are a `400`):

| Field | Meaning |
|---|---|
| `id` | the local image id, `sha256:<hex>` (at most 100 characters) |
| `repo_digests` | Docker's raw `RepoDigests`: up to 20 items, each `<repo>@sha256:<64 hex>`. A malformed item is a `400`. STD picks the item whose repository matches the entry's image (so `nginx` matches `docker.io/library/nginx`); none matching means "local build, no registry digest". |
| `created` | the image's `Created` time (at most 64 characters) |
| `version`, `revision` | the OCI labels `org.opencontainers.image.version` / `.revision` (at most 128 characters) |
| `source` | the OCI label `org.opencontainers.image.source` (at most 512 characters); only an `http(s)` value is kept |

Resolve the digests from the image the container was **created from** (its image id), not
from the tag's current image: after a `docker compose pull` without a recreate the tag
already points at the new image while the container still runs the old one.

- `image_info` **absent** or **null**: "no update". The stored values are kept. This is
  what older notifiers send.
- `image_info: {...}`: the stored values are **replaced** (a field you leave out is
  cleared).
- `image_name` changed and no `image_info`: the stored digest values are **cleared**, so
  a digest of the old image is never compared with the new image's tag.

A producer should send the field only when `GET /api/v1/meta` lists `image_info` in
`features`: STD rejects an unknown key.

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
| 0.12.0+ | 0.5.0+ | `image_info` (the running image), for the digest model of the image update check |

A newer STD always accepts an older notifier: the capture fields stay empty, a
missing `exposure_observations` keeps the existing rows, and a missing `image_info`
keeps the stored image facts (moving tags such as `latest` then show "unknown" until the
notifier reports the running image; pinned versions work without it).
