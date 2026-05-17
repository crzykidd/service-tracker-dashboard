# 🧭 Service Tracker Dashboard (STD)

![Python](https://img.shields.io/badge/python-3.11-blue?logo=python)
![Flask](https://img.shields.io/badge/flask-web-black?logo=flask)
![SQLite](https://img.shields.io/badge/db-sqlite-blue?logo=sqlite)
![License](https://img.shields.io/badge/license-MIT-green)

A homelab-scale Flask dashboard that tracks Docker services across multiple
hosts, runs background URL health checks, and renders a small set of
dashboard views (full, tiled, compact). Service entries are populated and
kept current by a sidecar process — typically
[docker-api-notifier](https://github.com/crzykidd/docker-api-notifier) —
posting to STD's register endpoint, but you can also add entries by hand
through the web UI or directly via API.

> **v0.6.0 removes the legacy `/api/register` endpoint.** All registers
> must use `/api/v1/register` with canonical key names. If you're
> running `docker-api-notifier`, v0.3.0 or later is required for basic
> registration; v0.4.0 is the paired release that populates the new
> network / port / exposure-observation fields.

---

## Table of Contents

1. [What It Does](#what-it-does)
2. [Screenshots](#screenshots)
3. [Configuration](#configuration)
4. [Docker Compose Setup](#docker-compose-setup)
5. [Database Migrations](#database-migrations)
6. [API: Registering Services](#api-registering-services)
7. [Container Labels (via docker-api-notifier)](#container-labels-via-docker-api-notifier)
8. [Files and Paths](#files-and-paths)
9. [Health Checks](#health-checks)
10. [Routes](#routes)
11. [Widgets](#widgets)
12. [Behavior Notes](#behavior-notes)
13. [Versioning & Releases](#versioning--releases)

---

## What It Does

- Three dashboard views (table, tiled, compact). Tiled view shows each service as a tile with a per-tile expand drawer for full host, URL, Docker, network, port, exposure, and widget detail. Icons use [Tabler Icons](https://tabler.io/icons) v3.34.0 (loaded via CDN). Clicking the chart icon on a tile opens the drawer in widget-only mode (showing just the metric cards); the chevron opens the full drawer. The two modes switch in-place without closing and reopening.
- **Dashboard view controls (v0.6.0+).** A `Group by` axis selector
  (`group` / `stack` / `host`) and a `Show URL-less` filter render
  above the service grid on all three views. State is URL-driven, so
  dashboards stay bookmarkable.
- Internal + external URL health checks on a configurable interval.
- Auto-downloads container icons from
  [Homarr Labs Dashboard Icons](https://github.com/homarr-labs/dashboard-icons).
- Register endpoint for pushing container metadata from external tools.
- SQLite backing store, file-based, no external DB server.
- Daily YAML backups with retention.
- Manual add / edit / delete through the web UI. Tiled tiles and Dashboard rows have a one-click trash icon with an inline confirm popover. Static (Locked) entries show a lock icon and can only be deleted from the edit page.
- Optional Dozzle log link integration.
- Local user accounts with session-based auth.
- Per-entry sort priority within groups; grouping and group sort.
- Pluggable widget system (Sonarr, Radarr, Bazarr, Overseerr, Prowlarr,
  Syncthing today; more under `widgets/`).
- **Exposure interpreter (v0.6.0+).** Reads structured exposure
  observations from the notifier's YAML interpreters (Traefik,
  Dockflare, etc.) and synthesizes `internalurl` / `externalurl`
  without requiring operator-written `dockernotifier.std.*` labels.
  Operator UI edits and explicit labels always win over synthesized
  values.

---

## Screenshots

<!-- TODO(v0.6.1): Screenshots below predate the v0.6.1 tile redesign (host line removed from tile face, icon-row status strip, expand drawer replacing inline widget data, Tabler icons replacing emoji badges). Refresh before next public announcement. -->

| Main Dashboard | Tiled View | Compact View |
|---|---|---|
| [![](docs/screenshots/std_main_dashboard.png)](docs/screenshots/std_main_dashboard.png) | [![](docs/screenshots/std_tile_dashboard.png)](docs/screenshots/std_tile_dashboard.png) | [![](docs/screenshots/std_compact_dashboard.png)](docs/screenshots/std_compact_dashboard.png) |

| Mobile View | Widgets | Settings |
|---|---|---|
| [![](docs/screenshots/std_mobile.png)](docs/screenshots/std_mobile.png) | [![](docs/screenshots/std_widgets.png)](docs/screenshots/std_widgets.png) | [![](docs/screenshots/std_settings.png)](docs/screenshots/std_settings.png) |

---

## Configuration

STD reads config from environment variables and an optional
`/config/settings.yml`. Environment variables take priority. If
`settings.yml` is missing, defaults apply and a `settings.example.yml`
is dropped into `/config` for reference.

Default login: `admin` / `changeme123`. Change it on first run.

### Settings reference

| Setting                    | Type   | ENV                          | Default            | What it does |
|----------------------------|--------|------------------------------|--------------------|--------------|
| `api_token`                | string | `API_TOKEN`                  | —                  | Bearer token required by `/api/v1/register`. |
| `std_dozzle_url`           | string | `STD_DOZZLE_URL`             | —                  | Optional link to a Dozzle instance; enables a Tools section in the UI. |
| `backup_path`              | string | `BACKUP_PATH`                | `/config/backups`  | Where YAML backups are written. |
| `backup_days_to_keep`      | int    | `BACKUP_DAYS_TO_KEEP`        | `7`                | Backup retention. |
| `url_healthcheck_interval` | int    | `URL_HEALTHCHECK_INTERVAL`   | `300`              | Seconds between health check passes. |
| `widget_background_reload` | int    | `WIDGET_BACKGROUND_RELOAD`   | `900`              | Seconds between widget data refreshes. |
| `widget_value_retention_days` | int | `WIDGET_VALUE_RETENTION_DAYS` | `30`            | Days of `widget_value` history to retain. A daily 00:15 background job prunes older rows. |
| `register_field_ownership` | string | `REGISTER_FIELD_OWNERSHIP`   | `user_wins`        | How register calls handle conflicts with UI edits on `group_name` and `sort_priority`. `user_wins` (default) preserves non-NULL UI values on update; `notifier_wins` always overwrites. Invalid values fall back to `user_wins` with a startup warning. |
| `user_session_length`      | int    | `USER_SESSION_LENGTH`        | `120`              | User session length in minutes. |
| `flask_secret_key`         | string | `FLASK_SECRET_KEY`           | —                  | Required for production. Used to sign session cookies. |

### Example `settings.yml`

```yaml
api_token: supersecrettoken
std_dozzle_url: http://dozzle.local
backup_path: /config/backups
backup_days_to_keep: 7
url_healthcheck_interval: 300
widget_background_reload: 900
widget_value_retention_days: 30
register_field_ownership: user_wins
user_session_length: 120
```

---

## Docker Compose Setup

```yaml
services:
  service-tracker-dashboard:
    image: crzykidd/service-tracker-dashboard:latest
    container_name: service-tracker-dashboard
    ports:
      - 8815:8815
    environment:
      - API_TOKEN=supersecrettoken
      - STD_DOZZLE_URL=http://dozzle.local
      - FLASK_DEBUG=0
      - FLASK_SECRET_KEY=changeme-in-prod
    volumes:
      - ./config:/config
    restart: unless-stopped
```

---

## Database Migrations

Schema changes are tracked with [Alembic](https://alembic.sqlalchemy.org/).
Migrations live in `alembic/versions/` and `alembic upgrade head` runs
automatically on container start (see `entrypoint.sh`).

To create a new migration after changing models, exec into a running
container:

```bash
docker compose exec <service-name> \
  alembic revision --autogenerate -m "describe the change"
```

The new revision file lands under `alembic/versions/`. Review it before
committing — autogenerate doesn't catch every kind of change
(constraint renames, default-only changes, SQLite-specific quirks).

To check whether models and the live database have diverged without
writing a migration:

```bash
docker compose exec <service-name> alembic check
```

---

## API: Registering Services

`/api/v1/register` is the only register endpoint. The legacy
`/api/register` shim that bridged v0.4.x producers through v0.5.0
was removed in v0.6.0; producers must run `docker-api-notifier`
v0.3.0+ or send canonical-key payloads directly.

### Endpoint

```
POST /api/v1/register
Authorization: Bearer <API_TOKEN>
Content-Type: application/json
```

### Canonical payload

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

### Required fields

- `host` — Docker host name. Composite key with `container_name`.
- `container_name` — name of the container.

Everything else is optional. STD applies sensible defaults for any
field that's missing.

`/api/v1/register` is **strict** — unknown keys are rejected with a
400 and the list of offending keys in the response body. Nested
structures (`networks`, `published_ports`) are also validated via
pydantic; malformed entries are rejected at the schema boundary.

### Field ownership: user_wins vs notifier_wins

`group_name` and `sort_priority` can be edited in the web UI. When a
notifier register arrives for a row whose UI value differs, the
`register_field_ownership` setting decides who wins:

- **`user_wins`** (default) — UI edits stick. The notifier may
  populate these fields on a new row or one where they're still
  NULL, but it won't overwrite a value the operator has set.
- **`notifier_wins`** — every register call overwrites everything,
  including UI edits. Choose this if your container labels are the
  source of truth.

Regardless of mode, STD records what the notifier sent in
`notifier_reported_group_name` and `notifier_reported_sort_priority`
columns. These columns aren't surfaced in the UI yet — they support
a planned overridden-labels export.

### Network and ports capture (v0.6.0+)

The three optional `networks` / `exposed_ports` / `published_ports`
fields are pure observation — STD overwrites them on every register
call with no ownership semantics. They're populated by
`docker-api-notifier` v0.4.0+; pre-v0.4.0 notifiers continue to work
and just leave the columns NULL.

The read-only "Reported by notifier" block at the bottom of
`/edit/<id>` surfaces this data. Empty / NULL columns render as "Not
reported." Static entries (created manually via the UI) won't have
this data either, and that's expected.

### Exposure observations + URL synthesis (v0.6.0+)

The optional `exposure_observations` field carries structured output
from the notifier's YAML interpreters (Traefik, Dockflare, …).
Notifier v0.4.0+ runs these interpreters and emits one entry per
interpreter that recognizes the container. STD writes them into the
new `service_exposure` table and runs a synthesizer that may
populate `internalurl` / `externalurl` automatically.

Operators tell STD what each layer means at `/settings` →
**Exposure** tab. Each discovered layer (only layers that have been
observed appear) gets a direction dropdown:

- **internal** — synthesized hostname populates `internalurl`.
- **external** — synthesized hostname populates `externalurl`.
- **neither** (default) — STD records the observation and shows a
  badge, but doesn't synthesize a URL from this layer.

Per-host overrides let you say "Traefik on the home host is
internal, but Traefik on the edge VPS is external" without writing
different YAML per host.

#### URL provenance

The two `internalurl` / `externalurl` columns now track who last
wrote them via two new `_source` columns. Ordering, strongest last:

1. **NULL** — no value, no opinion. Synthesizer is free to fill in.
2. **`synthesized`** — value came from the synthesizer. Re-runs on
   every register and on settings save may change it.
3. **`explicit_label`** — value came from a
   `dockernotifier.std.internalurl` / `.externalurl` label on the
   container. Synthesizer won't overwrite. A new explicit label
   updates it; a UI edit overrides.
4. **`ui_edit`** — operator typed a value in the web UI. Nothing
   overrides until another UI edit. Clearing the field resets the
   source to NULL so synthesis can resume.

The edit page (`/edit/<id>`) shows a small badge next to each URL
indicating the current source.

#### Wire-level semantics

- `exposure_observations` **absent** or **null** — "no update."
  Existing exposure rows for the service are preserved. This is the
  state for pre-v0.4.0 notifiers and any producer that doesn't emit
  interpreter output.
- `exposure_observations: []` — "this container has no interpreter
  matches." All existing exposure rows for the service are
  cleared. The synthesizer may then clear any URL whose source is
  `synthesized`.
- `exposure_observations: [ ... ]` — wholesale replacement. All
  prior rows for this service are dropped, the new rows are
  inserted, and the synthesizer recomputes URLs (respecting
  provenance).

#### Badges and headless rendering

Each tile (tiled view) and row (table view) renders up to three
exposure badges showing the layer name, a lock icon (`ti-lock`) if
TLS-terminated, and a key icon (`ti-key`) if auth is required. A `+N`
overflow badge appears when a service is observed by more than three
interpreters.

Services with no exposure observations **and** no URLs (manual,
explicit, or synthesized) are considered "headless." Their tiles
render without click affordance and rely on `docker_status` for
state. Combine with the `?show_urlless=false` view-control filter
(v0.6.0) to hide them entirely.

---

## Container Labels (via docker-api-notifier)

If you run [docker-api-notifier](https://github.com/crzykidd/docker-api-notifier)
on each Docker host, you can drive STD entirely from labels in your
compose files:

```yaml
labels:
  dockernotifier.notifiers: service-tracker-dashboard
  dockernotifier.std.internalurl: http://nginx:80
  dockernotifier.std.externalurl: https://nginx.domain.com
  dockernotifier.std.group: web
  dockernotifier.std.internal.health: "true"
  dockernotifier.std.sort.priority: "1"
```

Notifier v0.3.0+ emits canonical keys to `/api/v1/register` automatically.

---

## Files and Paths

| Path                     | Purpose                          |
|--------------------------|----------------------------------|
| `/config/services.db`    | SQLite database (WAL mode).      |
| `/config/std.log`        | Main app log (rotated).          |
| `/config/images/`        | Cached service icons.            |
| `/config/backups/`       | YAML backups (manual + nightly). |
| `/config/settings.yml`   | Optional config file.            |

---

## Health Checks

- Run on the `url_healthcheck_interval` (default 300 seconds).
- Internal and external URLs are pinged if their respective
  `*_health_check_enabled` flags are set.
- Status code, response time, and timestamp are recorded per check.
- A failed check logs and moves on; it does not crash the loop.
- UI shows color-coded status (green / yellow / red) with last-checked time.

---

## Routes

| Route                | Purpose                                  |
|----------------------|------------------------------------------|
| `/`                  | Main dashboard (table view).             |
| `/tiled_dash`        | Grid-style dashboard.                    |
| `/compact_dash`      | High-density compact view.               |
| `/add`               | Manually add a new entry.                |
| `/edit/<id>`         | Edit or delete an existing entry.        |
| `/settings`          | Settings + backup/restore UI (incl. Exposure tab). |
| `/settings/exposure` | Save per-interpreter direction settings + recompute synthesized URLs (admin POST). |
| `/dbdump`            | Raw dump of all DB entries (admin).      |
| `/images/<file>`     | Serve cached icon files.                 |
| `/api/v1/register`   | Register/update entry (canonical keys).  |
| `/login` `/logout`   | Local user auth.                         |

---

## Widgets

Widgets live under `widgets/<name>/` and are loaded dynamically. Each
widget directory contains:

- `__init__.py`
- `fetch_data.py` — pulls data from the upstream service.
- `settings.json` — declarative config schema.
- `README.md` — widget docs.

Built-in widgets: Sonarr, Radarr, Bazarr, Overseerr, Prowlarr, Syncthing.

Widget data is sampled on the `widget_background_reload` interval and
cached in the `widget_value` table. Retention: rolling 30 days
(introduced in v0.5.0).

---

## Behavior Notes

- Entries marked `static` are not overwritten by API register calls.
- Icon fetch falls back to a lowercased, hyphenated container name when
  no explicit icon is provided.
- Nightly backups run shortly after midnight; old backups are pruned
  per `backup_days_to_keep`.
- Version metadata is shown in `/settings`.
- Tile drawers on the Tiled view are transient view state and not bookmarkable; full edit remains at `/edit/<id>` and is bookmarkable.

---

## Versioning & Releases

- `:latest` follows `main` — CI-verified pre-release.
- `:dev` follows `dev` — work in progress.
- `:sha-<short>` published for every push.
- Semver-tagged images (`:0.6.0`, `:0`) published from GitHub Releases.

Branch protection: PRs into `main` must pass the build check; force-push
and branch deletion are blocked. Work happens on `dev`, opens a PR to
`main`, and merges only when CI is green. Release tags are cut from the
GitHub Releases UI on `main`.

---

## License

MIT — see [LICENSE](LICENSE).
