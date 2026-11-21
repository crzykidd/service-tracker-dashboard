# Design: Backup, export and import (0.11.0)

**Status:** design, awaiting operator approval (2026-11-20). No code has changed. Once
approved, phase 1 (`prompts/2026-11-20-bak-01-scheduled-backups.md`) adds a planned PRD
section, and this file is the reference for the five build prompts.
**Author:** operator decisions + Claude (design session, 2026-11-20).
**Code read:** `dev` at `7ec22ea`, with the settings-modernization phase 1 in progress
in the working tree. Where this doc and the code disagree, trust the code.
**Mockup:** [`2026-11-20-backup-export-import-mockup.html`](2026-11-20-backup-export-import-mockup.html)
(static, fake data; open it in a browser).
**Builds on:** [`2026-11-20-settings-modernization.md`](2026-11-20-settings-modernization.md)
(components §6, flash policy §7, the Data group and §9.12).

---

## 1. Goals and non-goals

Settings → Data → Backup & restore becomes two features:

1. **Database backups (disaster recovery).** A daily SQLite snapshot made with
   `sqlite3.Connection.backup()`, kept for N days, plus **Run now**. It is a full copy:
   secrets, history and observed data included. It is restored as a whole file.
2. **Export and import of operator-set state.** A versioned YAML or JSON document that
   holds only what the operator chose (groups, URLs they typed, checks, Home Assistant
   picks, stream filters, blocks, channels without passwords, ...). It is never a table
   dump. Import matches the records in the file against what is in the database **now**,
   shows a dry-run preview, and applies only what the operator ticks.

Goals:

- The operator's scenario (§2) works end to end on a fresh install with no hand edits.
- Import is **safe by default**. The default mode only fills settings that are missing,
  every write is previewed first, and nothing that differs is overwritten without an
  explicit opt-in.
- Import can be **re-run** (it is idempotent). Running it again after the sidecars and
  the notifier have posted picks up the records that were not there the first time.
- **No secrets in an export, ever.**
- Old YAML backups (today's entry list) can still be imported.
- The backup settings (enabled, time of day, keep days, path) can be edited in the UI.

Non-goals:

- No live database swap. The optional staged restore (§10) swaps the file only at
  container start.
- No sync between two running installs, no scheduled import, no remote targets (S3,
  SFTP). These are listed under Later (§15).
- Import never deletes anything local. A local record missing from the file is left alone.
- No change to the register or stream-ingest wire contracts.

## 2. The scenario, end to end

The operator has Docker entries, a DHCP stream and Home Assistant publishing set up.

1. **Export.** The daily export job writes `2026-11-20-std_export.yml` to the backup
   path, or the operator clicks **Download export**. The file holds groups, entry
   settings, checks, `ha_publish` flags, the `dhcp` stream's filters, default checks and
   blocks, the MQTT channel (no password), users (no password hashes) and the runtime
   settings.
2. **Loss or move.** The operator starts STD on a new machine with an empty `/config`.
   They log in as the default admin.
3. **Credentials.** The things an export cannot carry are set up again (the import
   summary repeats this list, §7.7):
   - a new **ingest key** for each stream sidecar (Settings → API keys → Create key,
     scope Ingest), set in the sidecar's config;
   - the notifier's `api_token` (it lives in `settings.yml` / env, not in the database);
   - the **MQTT password** after the import creates the channel;
   - **user passwords** (Users → Set password) for the users the import creates;
   - widget **API keys** (Edit entry → widget) for the widgets the import creates;
   - new management API keys for scripts and the MCP server.
4. **Base entries return on their own.** The notifier re-registers every container, so
   Docker entries appear with `source = notifier`. The DHCP sidecar posts its first
   snapshot and the `dhcp` stream appears as **pending**.
5. **First import.** Settings → Backup & restore → Import → upload the file.
   - **Stream mapping:** the file's `dhcp` stream maps to the local `dhcp` stream (same
     id; the operator can change it). It is pending, so the preview says
     "Stream pending. Its settings and blocks can be applied now; its entries appear when
     you enable it. Re-run the import after enabling."
   - **Preview:** Docker entries are *Matched — missing settings* (their group, URLs the
     operator typed, checks and `ha_publish` are missing on the fresh rows), ticked. The
     stream's filters, default checks and blocks are *missing*, ticked. The MQTT channel
     is *Not found* ("Import as new", off). Users are *Not found* (off). A container
     that has not registered yet is *Not found* ("Import as new" creates a manual entry
     the notifier adopts later).
   - The operator ticks the channel and the two users and clicks **Apply import**. One
     transaction. The summary lists what was filled and created, and what to redo.
6. **Enable the stream.** Because the filters and blocks were imported first, enabling
   the stream creates only the entries that should exist. Blocked devices never appear.
7. **Second import** (the same file). Docker rows are now *identical*. The DHCP rows
   match by `(stream, key)` and show *missing settings* (names, groups, checks,
   `ha_publish`). Apply. A third run shows everything *identical*. That is the
   idempotency check.
8. **Home Assistant.** The `ha_publish` flags and the channel's discovery setting are
   back, so once the MQTT password is set and the channel is enabled, the publisher's
   full sync republishes discovery for the ticked entries. See Q1 in §14 about the
   install's `instance_id`.

## 3. Current state (at `7ec22ea`)

- **Daily job** `jobs.run_scheduled_backup` at 00:05 (`CronTrigger(hour=0, minute=5)`,
  id `scheduled_backup_job`) writes `<date>-std_backup.yml`, a list of
  `ServiceEntry.to_dict()` (soft-deleted rows included, **no `group_name`**, the widget
  **with its API key**), then `_write_sqlite_snapshot` writes
  `<date>-std_backup.sqlite3` (WAL-safe, through a `.tmp` file and `os.replace`).
  Retention deletes files ending in `BACKUP_SUFFIXES` whose mtime is older than
  `backup_days_to_keep`.
- **Settings.** `backup_path` and `backup_days_to_keep` come from `settings.yml` / env
  (`BACKUP_PATH`, `BACKUP_DAYS_TO_KEEP`) through `settings_loader.load_settings()`, once
  at startup. They cannot be edited at runtime.
- **UI** (Settings → Backup): *Download backup* / *Save to server* (writes
  `backup.yml`, `to_dict()` + `group_name`). *Restore* from upload or a server
  `.yml`/`.yaml` file with scope `all` / `static`. It matches by
  `(container_name, host)`, overwrites nearly every column it finds (including observed
  data such as `docker_status`, `networks`, `ip`), skips live stream entries, turns
  stream records into manual entries, and writes the widget API key. There is no preview.
- **Restoring a `.sqlite3` snapshot** means stopping the container and swapping the file
  by hand.

## 4. Backup jobs

### 4.1 Settings model

New DB-stored keys in `settings_store.py`, with typed getters and setters like
`get_update_check_settings()`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `backup_path` | str | `settings.yml` `backup_path`, else `<CONFIG_DIR>/backups` | One folder for both kinds. |
| `backup_snapshot_enabled` | bool | `true` | |
| `backup_snapshot_time` | `"HH:MM"` | `"00:05"` | Container local time (the scheduler's zone). |
| `backup_snapshot_keep_days` | int 1–365 | `settings.yml` `backup_days_to_keep`, else 7 | |
| `backup_export_enabled` | bool | `true` | |
| `backup_export_time` | `"HH:MM"` | `"00:10"` | |
| `backup_export_keep_days` | int 1–365 | `settings.yml` `backup_days_to_keep`, else 7 | |
| `backup_export_format` | `"yaml"` \| `"json"` | `"yaml"` | Scheduled export only. Download offers both. |
| `backup_last_runs` | dict | `{}` | Observed. `{"snapshot": {...}, "export": {...}}`, each `{at, ok, file, size, error, trigger: "schedule"\|"manual"}`. |

`backup_days_to_keep` stays a valid `settings.yml` / env key. It now supplies the
initial value of **both** keep-days settings. No new file or env keys are added (Later:
per-kind env keys).

### 4.2 Precedence (decided)

For `backup_path` and the two keep-days values:

1. **Environment variable set** (`BACKUP_PATH`, `BACKUP_DAYS_TO_KEEP`, already recorded in
   `app.config['CONFIG_FROM_ENV']`): the env value wins. The UI shows it read-only with
   "Set by environment (`BACKUP_PATH`)". A save never writes it.
2. **A DB row exists** (the operator saved it in the UI): the DB value wins.
3. **`settings.yml`** value: the initial value until the operator saves in the UI.
4. The built-in default.

Why: env is how a container deployment pins things (compose files, orchestrators), and a
UI edit that the next restart silently undoes would be worse than a read-only field. A
`settings.yml` value is the old way to set it. If `settings.yml` won over the DB, a UI
save would have no effect, so the file only seeds. Each field has **Reset**, which
deletes the DB row so the value falls back to `settings.yml` or the default. The UI
labels where the shown value comes from ("from settings.yml", "default", "set in the UI").
`load_settings()` still runs once at startup. The resolver reads the startup dict plus
the DB row (`backups.effective_settings(app)`) and never calls `load_settings()`.

The other keys (enabled, time, format) have only a DB value or a default.

### 4.3 Scheduling

- Two APScheduler jobs replace `scheduled_backup_job`: `backup_snapshot_job` and
  `backup_export_job`, each a `CronTrigger(hour, minute)` built from its time setting.
  A disabled job is registered and then paused (`scheduler.pause_job`), so the UI can
  show "next run" and re-enabling is a `resume_job`.
- `jobs.start_background_workers` keeps the scheduler in a module global
  (`jobs._SCHEDULER`). `jobs.reschedule_backups(app)` reads the effective settings and
  calls `reschedule_job` / `pause_job` / `resume_job`. The settings save route calls it
  after commit. There is exactly one gunicorn worker (`gunicorn.conf.py`), so the
  in-process scheduler is the only one, and no cross-process signal is needed. Under
  `FLASK_DEBUG=1` the Werkzeug reloader is the same single process.
- The time is the container's local time (APScheduler's default zone, set by `TZ`). The
  card shows "Next run 2026-11-21 00:05 (container time)".
- A module lock per kind (`backups._RUN_LOCKS`) prevents two runs of the same kind at
  once. A manual run while one is running returns "A snapshot is already running."

### 4.4 File naming and retention

| Kind | Scheduled name | Manual name | Pruned by |
|---|---|---|---|
| Snapshot | `YYYY-MM-DD-std_backup.sqlite3` (unchanged) | `YYYY-MM-DD_HHMMSS-std_backup.sqlite3` | snapshot keep days |
| Export | `YYYY-MM-DD-std_export.yml` or `.json` | `YYYY-MM-DD_HHMMSS-std_export.yml\|.json` | export keep days |
| Legacy YAML | `YYYY-MM-DD-std_backup.yml` (no longer written after bak-02) | — | export keep days (they age out) |
| Legacy manual | `backup.yml` (today's *Save to server*) | — | never (no suffix); listed as Legacy |
| Pre-restore (phase 5) | `pre-restore-YYYYMMDD-HHMMSS.sqlite3` | — | never; the operator deletes it |

- A manual run gets a time in its name, so it never overwrites the scheduled file of the
  same day. It counts toward retention like any file of its kind.
- Retention runs at the end of each job, for that kind only. It uses the file mtime, as
  today. Files that do not match a known suffix are never deleted.
- Every write goes to `<name>.tmp`, then `os.replace` (the snapshot does this today, and
  the export does the same).

### 4.5 Path validation (on save)

- Must be an absolute path. `os.path.realpath` is applied.
- Created if missing (`os.makedirs(exist_ok=True)`). If it exists it must be a
  directory.
- Writable: create and remove `.std-write-test` in it. On failure the value is not saved,
  and the field shows the OS error in its banner.
- **Warning, not an error**, when the real path is not under `CONFIG_DIR`: "This folder
  is outside /config. Make sure it is a mounted volume, or backups are lost when the
  container is recreated." The value is saved.
- Changing the path does not move existing files. The list shows the new folder, and the
  save toast says "Existing backups stay in the old folder."

### 4.6 Backup list, download, delete

- One list under each card (snapshots / exports), newest first: name, size,
  modified time, a "manual" tag for manual runs, and a "legacy" tag for `-std_backup.yml`
  and `backup.yml`. The actions are **Download**, then a ⋯ menu with **Import…**
  (exports and legacy YAML; opens the import flow with that server file), **Restore…**
  (snapshots, phase 5) and **Delete** (danger, confirm).
- Routes (admin session, CSRF): `GET /settings/backups/<name>/download` and
  `POST /settings/backups/<name>/delete`. `<name>` must be a bare filename with a
  known suffix, and its real path must stay inside the backup folder. The existing
  server-restore check is moved into one helper, `backups.resolve_file(name)`.
- A snapshot download is the whole database: API key hashes, password hashes and the
  MQTT password. The UI says so next to the Download button. Snapshots are **not**
  downloadable through the management API (§11).

### 4.7 Failure surfacing

- Each run writes `backup_last_runs[kind]` (ok or the error text, file, size, trigger)
  and logs as today.
- The card shows "Last run today 00:05: ok, 2.1 MB" or a persistent **inline warning**
  (design §7.1 calls these "not a flash") "Last snapshot failed 2026-11-20 00:05:
  <error>". The warning stays until a later run succeeds.
- The Backup & restore nav item gets a red badge "!" while either kind's last run failed
  (the same nav-badge markup the Streams and Deleted items use since settings phase 1).
- A manual run is synchronous. It returns a toast ("Snapshot saved:
  2026-11-20_142233-std_backup.sqlite3, 2.1 MB") or an error banner in the Backup
  section. A snapshot of a homelab database takes well under a second. Gunicorn's 60 s
  timeout is the upper bound.

## 5. Export format v1

### 5.1 Principles

- **Operator-set state only.** Anything that rebuilds itself is left out: status,
  health results, IPs and MACs, exposure observations, networks and ports, container ids,
  image metadata reported by the notifier, stream snapshots, link offers, counters and
  timestamps.
- **No secrets:** no `notification_channel.secret`, no `api_key` rows at all, no
  `user.password_hash`, no `widget.widget_api_key`. Booleans `secret_set` and
  `api_key_set` say that something has to be set again.
- **Natural keys, never DB ids.** Groups by name, widgets by `(widget_name, widget_url)`,
  streams by `stream_id` (the slug), channels by name, users by username.
- **Soft-deleted entries are not exported.** They are in the trash, waiting to be purged.
  The database snapshot covers the trash. (Legacy files that carry `deleted_at` are
  handled in §9.)
- YAML and JSON carry **the same document**. YAML is written with
  `yaml.safe_dump(sort_keys=False, allow_unicode=True)`, JSON with `indent=2`. Records
  are sorted (entries by kind, host, name; everything else by name or key), so two
  exports diff cleanly.

### 5.2 Document (pydantic, `export_format.py`)

Models use `extra="allow"` on read so unknown keys can be reported (§5.5), and the
writer only emits known fields.

```python
class ExportDoc(BaseModel):
    format: Literal["std-export"]
    format_version: int                      # 1
    exported_at: datetime                    # UTC, ISO 8601 with Z
    std_version: str                         # bare semver from VERSION
    api_revision: int                        # api_version.API_REVISION
    instance_id: str | None                  # settings_store instance_id (informational)
    settings: RuntimeSettings = RuntimeSettings()
    groups: list[GroupRecord] = []
    widgets: list[WidgetRecord] = []
    notification_channels: list[ChannelRecord] = []
    streams: list[StreamRecord] = []
    entries: list[EntryRecord] = []
    users: list[UserRecord] = []

class RuntimeSettings(BaseModel):
    exposure_layers: dict[str, Literal["internal", "external", "neither"]] | None = None
    exposure_layers_per_host: dict[str, dict[str, Literal["internal", "external", "neither"]]] | None = None
    update_check: UpdateCheck | None = None          # {enabled: bool, interval_hours: int}
    backup: BackupSchedule | None = None             # see below; never the path

class BackupSchedule(BaseModel):
    snapshot: JobSchedule | None = None              # {enabled, time "HH:MM", keep_days}
    export: JobSchedule | None = None                # same + format: "yaml" | "json"

class GroupRecord(BaseModel):
    name: str                                        # identity
    sort_priority: int | None = None
    icon: str | None = None

class WidgetRecord(BaseModel):
    widget_name: str                                 # identity part 1 (the plugin, e.g. "sonarr")
    widget_url: str                                  # identity part 2
    widget_fields: list = []
    api_key_set: bool = False                        # the key itself is never exported

class ChannelRecord(BaseModel):
    name: str                                        # identity
    type: str                                        # "mqtt"
    enabled: bool
    config: dict                                     # the type's non-secret config (MqttConfig fields)
    secret_set: bool                                 # a password was stored; not the password

class StreamRecord(BaseModel):
    stream_id: str                                   # identity (slug)
    key_type: str                                    # must equal the local stream's to map
    producer: str                                    # informational (shown in mapping)
    display_name: str
    status: str                                      # informational, never applied (§6.6)
    network_include: list[str] | None = None
    network_exclude: list[str] | None = None
    default_checks: dict | None = None               # {"ping": bool, "tcp_port": int | None}
    expected_interval_seconds: int | None = None
    missing_expiry_days: int | None = None
    blocks: list[BlockRecord] = []

class BlockRecord(BaseModel):
    key: str                                         # identity within the stream
    name: str | None = None
    ip: str | None = None                            # the label shown in Blocked; not observation
    blocked_at: datetime | None = None
    blocked_by: str | None = None

class EntryRecord(BaseModel):
    kind: Literal["docker", "manual", "stream"]     # from service_entry.source
    identity: EntryIdentity
    is_static: bool = False
    description: str | None = None
    image_icon: str | None = None                    # only when not register-owned (§5.3)
    group: str | None = None                         # GroupRecord.name
    sort_priority: int | None = None
    internalurl: UrlValue | None = None              # only operator-owned URLs (§5.3)
    externalurl: UrlValue | None = None
    ha_publish: bool = False
    widget: WidgetRef | None = None                  # {widget_name, widget_url}
    checks: list[CheckRecord] = []

class EntryIdentity(BaseModel):
    container_name: str                              # docker/manual: identity; stream: the name
    host: str | None = None                          # docker: required; manual: optional; stream: None
    stream: str | None = None                        # stream: StreamRecord.stream_id
    stream_key: str | None = None                    # stream: the item key
    name_source: Literal["stream", "ui_edit"] | None = None   # stream only
    linked: bool = False                             # stream only: a manual entry that joined
    pre_link_host: str | None = None                 # stream + linked: its host before joining

class UrlValue(BaseModel):
    value: str
    source: Literal["ui_edit", "explicit_label", "synthesized"] | None

class CheckRecord(BaseModel):                        # HealthCheck.to_config(), unchanged keys
    kind: Literal["internal_url", "external_url", "service", "container"]
    name: str | None = None
    check_type: str
    target: str | None = None
    mode: str
    interval_seconds: int | None = None
    timeout_seconds: int | None = None
    verify_tls: bool = True
    enabled: bool = False
    dns_name: str | None = None
    dns_record_type: str | None = None
    dns_expected_rcode: str | None = None
    dns_expected_answer: str | None = None
    cert_min_days: int | None = None
    ha_exclude: bool = False

class UserRecord(BaseModel):
    username: str                                    # identity
    email: str
    is_admin: bool
    is_active: bool
```

**Validation on read:** an `EntryRecord` of kind `docker` needs `host`; kind `stream`
needs `stream` and `stream_key`, and `host` must be empty; `group` and `widget` must
name a record in the same document or a local one (otherwise there is a per-row
warning and that field is skipped); `stream` must name a `StreamRecord`. Errors are
per record (the row shows *Invalid* with the message), not per document. Only a bad
header, an unknown `format`, or an unsupported `format_version` rejects the whole file.

### 5.3 Field ownership

"Exported" means written to the document. **Missing** (§6.2) is decided against the
"fresh value" column: the value a row has when it is created by register, a snapshot or
the Add page.

**`service_entry`**

| Column | Exported | Fresh value | Why |
|---|---|---|---|
| `id` | no | — | DB id. |
| `host`, `container_name` | identity | — | Docker / manual identity; for a stream entry `container_name` is its name. |
| `source` | as `kind` | — | Record type. |
| `stream_id` (→ slug), `stream_key` | identity (stream) | — | `(stream, stream_key)`. |
| `name_source` | identity (stream) | `stream` | `ui_edit` means the operator renamed it; import renames to match. |
| `stream_linked`, `pre_link_host` | identity (stream) | false / NULL | Lets a linked entry match or be recreated as manual. |
| `container_id`, `stack_name`, `docker_status`, `started_at`, `last_updated`, `last_api_update` | no | — | Notifier observation. |
| `image_registry`, `image_owner`, `image_name`, `image_tag` | no | — | Derived from the image on every register. |
| `image_icon` | **manual, stream and locked Docker entries only** | NULL | An unlocked Docker entry's icon is rewritten on every register (`resolve_image_metadata`), so it is not durable operator state. |
| `internalurl`, `externalurl` + `*_source` | **when `_source = ui_edit`, or the entry is manual or stream** (any non-NULL value) | NULL / NULL | `explicit_label` comes back from the container labels, and `synthesized` is recomputed from exposure observations. Only UI edits (and URLs on non-Docker entries, which only an operator can set) are operator state. The source is exported so the importer writes `ui_edit`. |
| `is_static` | yes | false | The lock. |
| `description` | yes | NULL | |
| `group_id` (→ name) | yes | NULL, or the notifier's `notifier_reported_group_name` | Under `user_wins` the first register writes the label's group, so a fresh Docker entry may already have one (§6.2). |
| `sort_priority` | yes | NULL, or `notifier_reported_sort_priority` | Same rule as the group. |
| `notifier_reported_group_name`, `notifier_reported_sort_priority` | no | — | Capture columns, observation. Used by the matcher, not exported. |
| `widget_id` (→ ref) | yes | NULL | `{widget_name, widget_url}`. |
| `ha_publish` | yes | false | Operator-owned (PRD 17.4). |
| `networks`, `exposed_ports`, `published_ports` | no | — | Pure observation (CLAUDE.md). |
| `mac`, `ip`, `network`, `attributes` | no | — | Stream observation. |
| `inventory_missing`, `inventory_missing_since` | no | — | Observation. |
| `deleted_at` | no | — | Soft-deleted entries are not exported. |
| legacy `internal_/external_health_check_*`, `health_check_timeout`, `health_check_verify_tls` | no | — | Superseded by `health_check` rows. |

**`health_check`** (per entry, under `checks`)

| Column | Exported | Fresh value | Why |
|---|---|---|---|
| `kind`, `name`, `check_type`, `target`, `mode`, `interval_seconds`, `timeout_seconds`, `verify_tls`, `enabled`, `dns_*`, `cert_min_days`, `ha_exclude` | yes (`to_config()`) | URL rows: disabled, http, status, NULL timeout, verify on. Container: enabled. Service: — | Configuration. |
| `last_ok`, `last_checked_at`, `last_status_code`, `last_latency_ms`, `last_message`, `consecutive_failures`, `last_cert_expires_at` | no | — | Cached state. |
| `health_result` rows | no | — | History. |

**Other tables**

| Table / column | Exported | Why |
|---|---|---|
| `group.group_name`, `group_sort_priority`, `group_icon` | yes | Operator state. |
| `widget.widget_name`, `widget_url`, `widget_fields` | yes (attached widgets only) | Detached widgets are in the Deleted trash; the snapshot covers them. |
| `widget.widget_api_key` | **no** (`api_key_set` only) | Secret. |
| `widget_value` | no | Fetched data. |
| `notification_channel.type`, `name`, `enabled`, `config` | yes | `config` is non-secret by design (`MqttConfig`); it includes `username`, which is not a secret. |
| `notification_channel.secret` | **no** (`secret_set` only) | The MQTT password. |
| `inventory_stream.stream_id`, `key_type`, `producer` | identity / informational | Needed for mapping. |
| `inventory_stream.display_name`, `network_include`, `network_exclude`, `default_checks`, `expected_interval_seconds`, `missing_expiry_days` | yes | Operator settings (PRD 18.8–18.9). |
| `inventory_stream.status` | yes, informational | See §6.6. |
| `inventory_stream.api_key_id`, `snapshot`, `producer_version`, `producer_interval_seconds`, counts, times, `last_error`, `last_rejection` | no | Binding and observation. |
| `inventory_block.key`, `name`, `ip`, `blocked_at`, `blocked_by` | yes | The block list is operator state. `name`/`ip` are the labels it shows. |
| `stream_link_offer` | no | Rebuilt from the next snapshot. |
| `service_exposure` | no | Observation. |
| `user.username`, `email`, `is_admin`, `is_active` | yes | |
| `user.password_hash` | **no** | Secret. |
| `user.created_at`, `last_login_at`, `password_changed_at`, `oauth_provider`, `oauth_id` | no | Bookkeeping; no OAuth login exists. |
| `api_key`, `api_audit` | **no** | Keys are re-created; the audit is history. |
| `setting.exposure_layers`, `exposure_layers_per_host`, `update_check_enabled`, `update_check_interval_hours` | yes | Runtime settings. |
| `setting.backup_*` (enabled, time, keep days, format) | yes | Not the path; it is host-specific. |
| `setting.instance_id` | header only | Informational; never applied by default (Q1). |
| `setting.update_check_cache`, `notify_publish_state`, `backup_last_runs` | no | Observation. |
| `settings.yml` / env values (`api_token`, retention days, `register_field_ownership`, ...) | no | Files the operator keeps. The export says so in a header comment (YAML) and the summary repeats it. |

### 5.4 Example (YAML, abridged)

```yaml
format: std-export
format_version: 1
exported_at: "2026-11-20T00:10:02Z"
std_version: "0.11.0"
api_revision: 4
instance_id: 1a2b3c4d-....
settings:
  exposure_layers: {traefik: internal, dockflare: external}
  update_check: {enabled: true, interval_hours: 6}
groups:
  - {name: Media, sort_priority: 10, icon: mdi-play}
widgets:
  - {widget_name: sonarr, widget_url: "http://sonarr:8989", widget_fields: [queue], api_key_set: true}
notification_channels:
  - name: home-broker
    type: mqtt
    enabled: true
    config: {host: mqtt.lan, port: 1883, username: std, base_topic: std, ha_discovery: true, ...}
    secret_set: true
streams:
  - stream_id: dhcp
    key_type: mac
    producer: std-source-technitium
    display_name: DHCP
    status: enabled
    network_exclude: [guest]
    default_checks: {ping: true, tcp_port: null}
    missing_expiry_days: 14
    blocks:
      - {key: "aa:bb:cc:00:11:22", name: old-printer, ip: 10.0.40.9}
entries:
  - kind: docker
    identity: {host: em-dock01, container_name: grafana}
    group: Monitoring
    externalurl: {value: "https://grafana.example", source: ui_edit}
    ha_publish: true
    checks:
      - {kind: external_url, check_type: http, mode: status, enabled: true, verify_tls: true, ...}
  - kind: stream
    identity: {stream: dhcp, stream_key: "aa:bb:cc:00:11:33", container_name: boiler, name_source: ui_edit}
    group: IoT
    ha_publish: true
    checks:
      - {kind: service, name: Ping, check_type: ping, target: 10.0.40.30, enabled: true, ...}
users:
  - {username: alice, email: alice@example.com, is_admin: false, is_active: true}
```

### 5.5 Version policy

- `format_version` is one integer. The reader supports **0** (legacy, §9) and **1**.
- **Newer than supported → reject the file** (HTTP 400 / an error banner): "This export
  was made by STD 0.13.0 (format 2). This STD reads up to format 1. Upgrade STD first."
  Guessing at a newer major format could write wrong values.
- **Unknown keys inside a supported version → warn, do not reject.** A later 0.11.x or
  0.12 may add optional fields without changing `format_version`. Import is a reviewed,
  human-driven operation, unlike the wire contracts (which use `extra="forbid"`), so the
  preview shows "Ignored fields this STD does not know: `entries[].foo` (12×)". The
  fields are not applied.
- Rule for later releases: **adding an optional field keeps `format_version` 1.**
  Renaming or removing a field, or changing its meaning, bumps it to 2, and the reader
  keeps a v1 path.
- `std_version` and `api_revision` are informational. An export from an older STD with
  format 1 is read as is. Fields it lacks are simply absent (not "missing").

## 6. Matching rules

All matching runs in `importer.plan()` against the database as it is now. String
comparisons are **exact and case-sensitive** unless stated otherwise, because register
(`filter_by(host=..., container_name=...)`) and the SQLite unique indexes are
case-sensitive, and matching must agree with what register adoption will do later.

### 6.1 Statuses

| Status | Meaning | Default |
|---|---|---|
| **Matched — missing settings** | A target was found, and at least one exported field is at its fresh value locally (§6.2) while the file has a value. | ticked |
| **Matched — differs** | A target was found, nothing is missing, and at least one field differs. | unticked; its fields apply only in *overwrite* mode |
| **Matched — identical** | Nothing to do. | collapsed count per group |
| **Matched — deleted locally** | The only target is soft-deleted. Ticking it restores the entry and fills it (same clash check as Settings → Deleted → Restore). | unticked |
| **Ambiguous** | More than one candidate. The operator picks the target from a select (or "Skip"). | unticked until picked |
| **Not found** | No candidate. "Import as new" (§7.5). | off |
| **Waiting** | Its stream is not mapped (not present yet, or skipped), or it is a stream record whose stream is not enabled. "Re-run the import after the sidecar posts / after enabling the stream." | not selectable |
| **Conflict** | It cannot be applied as asked: a user email in use by another user, a type mismatch, "import as new" would duplicate an existing `(host, name)`. The row says why. | not selectable |
| **Invalid** | The record failed validation (§5.2). | not selectable |

A row with both missing and differing fields is *Matched — missing settings*. Its
differing fields are listed separately, and they apply only in overwrite mode when their
own field box is ticked.

### 6.2 Missing vs differs (per field)

- **Identical:** the local value equals the file value (after normalising: trimmed
  strings, `None` == absent, lists of networks compared case-insensitively as sets).
- **Missing:** the local value is the **fresh value** (§5.3) and the file has a
  different value. A fresh row cannot record intent, so a value at its default is
  treated as never chosen. Special cases:
  - **Docker group / sort priority:** the local value counts as fresh when it is NULL
    **or equals `notifier_reported_group_name` / `notifier_reported_sort_priority`**.
    That covers the first register under `user_wins` writing the label's group. This is
    the use the `models.py` comment on those capture columns plans for ("export
    overridden labels").
  - **URLs:** fresh when the local value is NULL or its source is NULL / `synthesized`.
    A local `explicit_label` or `ui_edit` value that differs is *differs*. When imported,
    a URL is written with `_source = ui_edit`, so the synthesizer and later registers
    leave it alone (the provenance order `ui_edit` > `explicit_label` > `synthesized`).
  - **Stream entry name:** fresh when `name_source = stream`. A file `name_source =
    ui_edit` with a different name is missing. Importing it sets the name and
    `name_source = ui_edit`.
  - **Checks:** URL rows and the Container row are matched by `kind`, and each field is
    compared to the fresh row. Service checks are matched by `(check_type, name)`. A file
    service check with no local match is *missing* (it is added). A matched one with a
    different config is *differs*. Local service checks that are not in the file are
    never removed. A stream's default checks (Ping on the IP) are created by the stream
    and usually come out identical. When several local service checks share
    `(check_type, name)`, that entry's service checks are *differs*, never filled.
- **Differs:** anything else.

**`register_field_ownership = notifier_wins`:** importing a Docker group or sort priority
would be overwritten by the next register, so those fields show the note "the notifier
owns this field (`notifier_wins`)" and are excluded.

### 6.3 Entries

Candidates are looked up per record kind. Stream entries (`source = stream`) are never
candidates for Docker or manual records. That is the same rule register follows.

| File kind | Step 1 | Step 2 | Step 3 |
|---|---|---|---|
| `docker` | Non-stream entries with exactly `(host, container_name)`, active ones first. One active → matched. More than one active → *Ambiguous*. | No active, one or more soft-deleted → *Matched — deleted locally* (lowest id). | None → *Not found*. |
| `manual` | Same as docker. `host` NULL matches `IS NULL`, as `entry_rules.find_duplicate` does. A local **notifier** entry with the same pair is a valid match (the notifier adopted the pre-staged entry). | as docker | *Not found*. Import as new is refused (*Conflict*) when `find_duplicate(host, name)` finds an active entry, including a host-less stream entry with the same name ("one device, one entry", CLAUDE.md). |
| `stream` | The stream is mapped (§6.5) and enabled: the local entry with `(mapped stream, stream_key)`, soft-deleted included (the next snapshot would restore it by key). Found → matched (deleted → *deleted locally*). | An **open link offer** on the mapped stream for that key → matched to the offer's manual entry, with the note "Accept the link offer in Streams to join it to the stream". Its settings can be filled now. | A **manual** entry with `(pre_link_host or NULL, container_name)` → matched with the note "manual, not linked yet" (this is how a re-run finds what an earlier "import as new" created). None → *Not found*. Mapped stream not enabled → *Waiting*. |

**Linked entries** (`identity.linked = true`) carry both identities. They go through the
`stream` column, and step 3 uses `pre_link_host`, which is where the entry would be
before it is linked again.

**Duplicate hint:** when a stream record matches in step 1 **and** a manual entry
also matches its step-3 identity, the row notes "A manual entry 'boiler' also exists,
probably from an earlier import as new. Link or delete it." The import itself never
deletes it.

### 6.4 Groups, widgets, channels, users, settings

- **Groups:** matched by exact `group_name`. When no exact match exists but a
  case-insensitive one does (`media` vs `Media`), the row is *Ambiguous* with the
  choices "Use 'Media'" or "Create 'media'". Not found → *missing* (ticked). A missing
  group is plain configuration, and an entry that needs it creates it anyway. Fields:
  `sort_priority`, `icon` (fresh value NULL).
- **Widgets:** no rows of their own. They are dependencies of entries. An entry's
  `widget` field matches a local widget by `(widget_name, widget_url)`. With no match,
  the widget is created (no API key) when the entry's widget field is applied. A local
  widget's `widget_fields` are filled only when empty, and its API key is never touched.
  When the file says `api_key_set: true` and the local widget has none, the field note
  says "needs its API key (Edit entry → widget)".
- **Notification channels:** matched by exact `name`. A different `type` → *Conflict*.
  Config keys are compared to `MqttChannelType.defaults()` for the fresh value. Three
  namespace keys, `base_topic`, `ha_prefix` and `ha_device_prefix`, are **never applied
  to an existing channel**, even in overwrite mode. They show as differs with "change
  this in Notifications, which offers to clear the old topics" (changing them needs the
  broker cleanup `notify.update_channel` runs). Not found → "Import as new" (off). A new
  channel is created **disabled** when `secret_set` is true (it cannot connect without
  its password); the summary says "set the password, then enable". When `secret_set` is
  false it keeps the file's `enabled`. The secret is never written.
- **Users:** matched by exact `username`. An existing user is **never modified**. Any
  differences are shown read-only ("not changed by import"), in both modes. Importing
  `is_admin` from a file into an existing account would be a privilege change made by a
  file, and email and active state are account matters the operator changes in Users.
  Not found → "Create user" (off). Creation is refused (*Conflict*) when the email
  belongs to another user (the email column is unique). See §7.6.
- **Runtime settings:** one row per key (`exposure_layers` per layer,
  `exposure_layers_per_host` per host and layer, `update_check`, the backup schedule
  fields). Missing = the key or layer is absent locally, or at its default. Differs = a
  different value. `instance_id` is never a row (Q1).

### 6.5 Stream mapping (first step of every import)

- Each `StreamRecord` maps to a local `inventory_stream`, **automatically by equal
  `stream_id`**. The operator can change the target to any local stream with the **same
  `key_type`** (a mac stream cannot map to a hostname stream) or choose "Skip".
- A file stream with no local stream: "Not present yet. Re-run the import after the
  sidecar posts." Its settings, blocks and entries are *Waiting*. **Import never creates
  a stream.** A stream exists only once a sidecar with an ingest key has posted, and it
  is bound to that key.
- Two file streams mapped to one local stream → the mapping step refuses it ("each local
  stream can be the target once").
- The mapping is part of the plan input (`stream_map: {file_id: local_id | null}`) and
  of the fingerprint (§7.3).

### 6.6 Streams and blocks

- **Stream settings** (`display_name`, filters, default checks, expected interval,
  missing expiry) fill a mapped stream **whatever its status**, pending included.
  Importing filters and blocks **before** enabling a pending stream means enabling
  creates only the entries the operator wants. The preview recommends this order.
  `display_name` always has a local value (the sidecar's), so a different name is
  *differs*.
- **`status` is never applied.** Enabling a stream applies its whole stored snapshot (a
  lifecycle action under `streams._LOCK`, with its own UI and preview), and ignoring or
  disabling has cleanup choices. The mapping row shows "enabled in the file, pending
  here: enable it in Streams".
- **Blocks:** one row per `(stream, key)`. Not present locally → *missing*, ticked. When
  a local entry already exists for that key (the sidecar posted before the import), the
  row adds an opt-in "Also soft-delete the entry" (off). It uses
  `streams.soft_delete_entry(entry, block=True)`. Without it, the block is added and the
  entry stays.

### 6.7 Re-running (idempotency)

After an apply, the applied fields equal the file, so they are *identical* on the next
plan. Created entries, groups, users, channels and blocks match by their identity.
Nothing is ever applied twice. A test runs plan → apply → plan and asserts that every
row is *identical* or *Waiting* (§12).

## 7. Import engine (`importer.py`)

### 7.1 Shape (mirrors `streams.plan()` / `apply()`)

```python
def parse(raw: bytes, filename: str | None) -> ParsedDoc           # v0 or v1 → ExportDoc + warnings
def plan(doc: ExportDoc, stream_map: dict | None = None) -> ImportPlan   # pure, reads only
def apply(doc: ExportDoc, stream_map: dict, selection: Selection,
          mode: Literal["fill", "overwrite"], fingerprint: str, actor: str) -> ImportResult
```

`ImportPlan`:

```python
@dataclass
class FieldDiff:   field: str; file: Any; local: Any; kind: Literal["missing", "differs"]; note: str | None
@dataclass
class RowPlan:
    rid: str                 # stable row id, e.g. "entry:docker:em-dock01/grafana",
                             # "entry:stream:dhcp/aa:bb:cc:00:11:33", "group:Media",
                             # "block:dhcp/aa:bb:...", "channel:home-broker", "user:alice",
                             # "setting:exposure_layers/traefik"
    section: str             # entries | groups | channels | streams | blocks | users | settings
    source_group: str        # docker | manual | stream:<slug> | groups | channels | users | settings
    label: str
    status: str              # §6.1
    target_id: int | None
    candidates: list[dict]   # ambiguous: [{id, label}]
    fields: list[FieldDiff]
    can_create: bool         # not-found rows that "import as new" can create
    options: list[str]       # "restore", "soft_delete_entry", ...
    notes: list[str]
    default_selected: bool
@dataclass
class ImportPlan:
    header: dict             # format_version, exported_at, std_version, instance_id (+ "differs from this install")
    stream_mapping: list[dict]
    rows: list[RowPlan]
    counts: dict             # per status and per group
    warnings: list[str]      # ignored fields, legacy secrets present, notifier_wins, ...
```

`Selection` is `{rid: {"apply": bool, "fields": [field, ...] | None, "target_id": int |
None, "create": bool, "options": [str]}}`. A row left out of the selection is not
applied. `fields: None` means every field that is actionable in the chosen mode.

### 7.2 Holding the plan between preview and apply (decided)

**Re-plan on apply and compare a fingerprint.** The plan is never kept as an object.
What is kept is the *input*:

- **UI:** the upload is parsed, then stored normalised as JSON in
  `<CONFIG_DIR>/import-staging/<token>.json` (token = `secrets.token_urlsafe(16)`,
  bound to the user id in the file). The TTL is 60 minutes. Each new upload and the
  daily backup job prune expired files, and a successful apply deletes its file. The
  preview page carries the token. A server-side file (rather than a hidden form field)
  keeps multi-megabyte documents out of the page, and it survives a page reload.
- **API:** stateless. `POST /import/plan` takes the document. `POST /import/apply` takes
  the same document plus `stream_map`, `selection`, `mode` and the `fingerprint` that
  `plan` returned.
- **`apply()`** takes `routes_api._UPSERT_LOCK`, then `streams._LOCK` (always in that
  order, the same order the management API's unlink route already uses:
  `_UPSERT_LOCK`, then `streams.unlink_entry` takes `streams._LOCK`), **re-runs `plan()`** against the current DB, and computes the fingerprint of the
  **selected rows only**: sha256 over `(rid, status, target_id, sorted field diffs)` plus
  the stream map. If it differs from the one shown, nothing is written. The UI re-renders
  the preview with "Something changed since the preview (a register or a snapshot
  arrived). Review and apply again." The API answers **409** with the fresh plan.

Why not keep the plan object with a token: the plan holds ORM rows from another request
and session, so it would be stale by design. Re-planning under the locks is the only
way to know that what is applied is what was shown. Observed data is not in the
fingerprint, so routine register and snapshot traffic does not trip it. Only a change
that affects a selected row does.

### 7.3 Apply

- **One transaction**, under the two locks. The order is groups → widgets → channels →
  stream settings → blocks → users → runtime settings → entries (create as new, restore,
  fill fields, checks). Any exception rolls the whole import back, and the result says
  "Nothing was changed: <error>".
- Writes go through the same helpers the UI uses wherever those helpers **do not commit**
  (`ensure_url_checks`, `ensure_container_check`, `entry_rules`, `check_form`
  validators, `streams.soft_delete_entry`, which leaves the commit to the caller).
  Helpers that commit (`notify.create_channel` / `update_channel`, `streams.accept_offer`)
  are not called. The importer validates with the same functions
  (`notify.validate_config`, `streams.clean_default_checks`, `_clean_filter`) and writes
  the rows itself. After commit it calls `notify.request_reload()` when a channel
  changed and `jobs.reschedule_backups()` when a backup setting changed. The
  `notify_state` commit listener already requests a full sync, so `ha_publish` and
  group changes republish.
- `mode = fill`: only *missing* fields of selected rows. `mode = overwrite`: also the
  *differs* fields whose field box is ticked (except the never-applied ones in §6.4).
- `entry.last_updated` is stamped on every entry touched.

### 7.4 Size limits

- Upload ≤ **10 MB**, checked against `request.content_length` before reading and
  enforced while reading. The limit is per route, so the app-wide `MAX_CONTENT_LENGTH`
  is not changed.
- ≤ **20,000** entry records and ≤ 5,000 blocks per stream (the ingest limit), or the
  file is rejected.
- YAML is parsed with a `SafeLoader` subclass that **rejects aliases and anchors** (the
  exporter never writes them), which rules out alias-expansion bombs. JSON is parsed
  with `json.loads`.

### 7.5 Import as new

- **Docker record** → a **manual** entry: `source = manual`, the record's `host` and
  `container_name`, `is_static = false`, URL rows, plus the record's settings. Register
  adoption (`routes_api.register`, verified at `7ec22ea`) takes it over when the
  container registers, **if all of these hold**:
  1. the register payload's `host` and `container_name` equal the entry's exactly
     (case-sensitive, no normalisation beyond what the notifier sends);
  2. the entry's `source` is `manual` (a stream entry is never matched);
  3. the entry is **not locked** (`is_static` false). A locked row is skipped with
     "static lock" and never adopted. So import as new **never sets the lock** even when
     the file has `is_static: true`. The row notes "the lock is applied on a re-run,
     after the container registers", and the re-run sees `is_static` as missing;
  4. there is no other non-stream active row with the same pair and a lower id (register
     takes active rows first, then the lowest id).

  Adoption sets `source = notifier` and adds the Container check. A soft-deleted match
  is restored by register too. Under `user_wins` the imported group and sort priority
  survive the adopting register.
- **Manual record** → a manual entry, refused on a `find_duplicate` clash (§6.3).
- **Stream record** → a **manual** entry: `container_name` from the record and `host =
  pre_link_host` (NULL when unknown), plus its settings. The existing link-offer match
  (`streams.plan()`) pairs it when the item appears, **if all of these hold**:
  1. the mapped stream is **enabled** (only an enabled stream applies snapshots;
     enabling applies the stored one);
  2. the item's key has no entry in that stream, is not blocked, and passes the
     stream's network filter;
  3. the manual entry is active with `source = manual` (locked is allowed);
  4. the item's name, or its first DNS label, casefolded, equals the entry's
     `container_name`, its `host`, or the first label of its host;
  5. it is the **only** such manual entry not already claimed by another open offer;
  6. the operator **accepts** the offer (Streams → Link offers, or the API). Offers are
     never auto-accepted, and import never answers one.

  On accept, `_convert` sets `stream_linked = true` and `pre_link_host`. So a
  stream-created entry that comes back through import as new becomes *linked* (cleanup
  unlinks it instead of deleting it). That is a small change of meaning (§13). If the
  operator renamed the entry (`name_source = ui_edit`) and its name no longer matches the
  item's, no offer is made. The operator can then use **Link** by hand (Streams → an
  unmatched item, `streams.link_entry`). **The recommended path for stream records is
  to wait for the sidecar and re-run the import.** Import as new is for devices the
  operator wants on the dashboard right away.

### 7.6 Users without passwords

- A created user gets `password_hash = "!unset"`. It is not a werkzeug hash, and
  werkzeug 3.1 `check_password_hash` returns False for a hash without `$` separators, so
  **no password works**. bak-03 adds a test that `check_password(anything)` is False and
  that `/login` refuses the user. `password_changed_at` stays NULL.
- Nothing is generated or displayed. Users shows "No password set, cannot sign in" (a
  muted tag) for any user whose hash is the sentinel, and the existing **Set password**
  is how they get one. The default-credentials warning is unaffected.
- `is_active` and `is_admin` are taken from the file for a **new** user only.

### 7.7 Result summary

`ImportResult` (also the API response body):

- counts per group: rows applied, fields filled, fields overwritten, entries created
  (manual, waiting for adoption or a link offer), entries restored, groups / widgets /
  channels / users / blocks created, settings changed;
- skipped rows by reason (unticked, Waiting, Conflict, Invalid);
- **"Still to do"**: users created without a password (names), channels created
  disabled (names), widgets that need an API key (names), streams not present yet (ids),
  pending streams to enable, open link offers to answer, the generic list (ingest keys,
  `api_token`, management keys);
- the UI shows it as a card that replaces the preview, with a toast "Import applied"
  plus a link back to Backup & restore.

### 7.8 Audit and logging (decided)

This follows the existing convention (decisions.md: "UI stream actions are logged, not
audited. `api_audit` is keyed to API keys; a session has none").

- **UI import:** one app-log line at INFO with the user, the file name, mode and counts,
  plus one DEBUG line per applied row.
- **API import:** the management blueprint's audit hook records `POST /import/apply` with
  `object_type = "import"` and `changes` = the counts (not the per-field values, which
  can be large and include URLs). A 409 stale answer is audited like any write attempt.
- Export and plan are reads/dry-runs and are not audited.

## 8. Export engine (`export_format.py`)

- `build_export() -> ExportDoc` reads in one session: groups, attached widgets,
  channels, streams + blocks, active entries + checks, users, settings. It applies the
  ownership rules of §5.3. `dump(doc, "yaml" | "json") -> bytes`.
- The scheduled job and the UI **Download export** (`GET
  /settings/backups/export?format=yaml|json`, `Content-Disposition` with
  `std_export_<host-less timestamp>.yml`) share it.
- A secrets test serialises an export of a database seeded with a known MQTT
  password, widget key, user password and API key, and asserts that none of those
  strings, no `password_hash`, no `key_hash` and no `secret` key appear in it.

## 9. Legacy YAML (format version 0)

**Detection:** the top-level YAML value is a **list** → format 0 (today's scheduled
`-std_backup.yml` and the UI `backup.yml` / `service_backup_all_*.yaml`). A mapping
without `format: std-export` → rejected ("not an STD export").

**Mapping** (`export_format.from_legacy(records) -> ExportDoc`):

| v0 field | v1 |
|---|---|
| `source` absent | the migration rule as today: `last_api_update` set → `docker`, else `manual` |
| `source: notifier` / `manual` | `docker` / `manual` |
| `source: stream` | `stream` with **no stream id** (v0 never carried one). If the record has a `mac`, the matcher tries every local stream with `key_type = mac` for `stream_key = normalize_mac(mac)`. One hit → matched. Several → *Ambiguous*. None → falls back to the manual identity `(host, container_name)`. |
| `group_name` (UI backups only; the scheduled job never wrote it) | `group` (a group record is synthesised by name). Scheduled v0 files carry no groups; the preview warns "This file has no groups (made by the daily job before 0.11.0)." |
| `internalurl`/`externalurl` + `*_source` | URL value. Included when the source is `ui_edit`, or the entry is manual, or the source key is absent (pre-0.6 backups). Never `explicit_label` / `synthesized`. |
| `is_static`, `description`, `sort_priority`, `ha_publish`, `image_icon` | as v1 (icon by the §5.3 rule) |
| `checks` | as v1. Absent → mapped from `internal/external_health_check_enabled`, `health_check_timeout`, `health_check_verify_tls` (the `_restore_checks` legacy branch) |
| `widget` | `{widget_name, widget_url}` + a `WidgetRecord` with `widget_fields`. **`widget_api_key` is ignored.** The preview warns "This file contains widget API keys in clear text. They are not imported. Delete old copies stored where others can read them." |
| `deleted_at` set | the row is shown as *Deleted in file*, unticked, applied only if ticked (it then imports as an active entry). |
| everything else (`docker_status`, `networks`, `ip`, `mac`, `last_*`, ...) | ignored (observation) |

A v0 file has no streams, channels, users or settings sections, so those groups are
absent from its preview.

## 10. Staged database restore (phase 5, optional)

### 10.1 Flow

1. **Pick or upload.** Restore card → choose a snapshot from the list or upload a
   `.sqlite3` (≤ 200 MB, per-route limit). An upload is streamed to
   `<CONFIG_DIR>/restore/upload-<token>.sqlite3`.
2. **Validate** (`restore_staging.validate(path)`, plain `sqlite3`, `mode=ro` URI):
   - `PRAGMA integrity_check` returns exactly `ok`;
   - the file is an STD database: the `alembic_version`, `service_entry` and `setting`
     tables exist;
   - `alembic_version.version_num` is a revision **known to this code** (alembic
     `ScriptDirectory.from_config(...).get_revision()` finds it, and it is `head` or an
     ancestor of `head`). A newer or unknown revision is rejected: "made by a newer STD".
     An older revision is fine: the migrations run on start.
   - The page shows what was found: revision, entry count, latest `last_updated`, and
     `instance_id` (and whether it equals this install's).
3. **Stage.** On confirm (a danger confirm dialog naming the file and "the current
   database is kept as pre-restore-<timestamp>.sqlite3"), copy it to
   `<CONFIG_DIR>/restore/pending.sqlite3` and write `pending.json` `{source_name, sha256,
   revision, staged_at, staged_by, keep_dir: <effective backup path>}`. **No live swap.**
4. **Banner.** While a restore is pending, every Settings page load shows an inline
   warning "A database restore is staged and will be applied on the next container
   restart. **Cancel restore**". Cancel deletes `pending.*`.
5. **Swap at start.** `entrypoint.sh` runs `python restore_swap.py` **before** `alembic
   upgrade head`. The script uses only the stdlib (no app import, no SQLAlchemy engine):
   - no `pending.json` → exit 0 at once;
   - re-check sha256 and `integrity_check`;
   - **keep the current DB:** open `services.db` with `sqlite3` and
     `Connection.backup()` it to `<keep_dir>/pre-restore-YYYYMMDD-HHMMSS.sqlite3`. That
     is WAL-safe (CLAUDE.md), and it captures committed WAL frames that a file copy would
     miss;
   - remove `services.db`, `services.db-wal`, `services.db-shm`, then `os.replace(pending,
     services.db)`;
   - write `restore/last.json` `{ok, at, source_name, kept_as}` and remove
     `pending.json`;
   - **on any failure:** leave or put back the current DB, rename `pending.*` to
     `failed-<ts>.*`, write `last.json` with `ok: false, error`, and **exit 0**, so a
     failed restore never stops STD from starting. Any error goes to stdout (the
     container log).
   Then `alembic upgrade head` migrates the restored file forward, as on any start.
6. **After start.** If `last.json` is newer than the last time it was shown, Backup &
   restore shows "Restored from <name> at <time>. The previous database was kept as
   <file>." (ok) or an error banner. It is dismissible and stored as seen in
   `settings_store` (`restore_last_seen`).

Notes:

- `python app.py` run outside the container (dev without the entrypoint) does not swap.
  The dev compose uses the entrypoint. This is documented.
- The restored database brings its own users, API keys, channels and `instance_id`. That
  is intended for disaster recovery. The confirm dialog says "Everything since the
  snapshot is lost, including API keys created since."
- Management API: none in phase 5 (a whole-database swap through an API key is too
  sharp). Later.

### 10.2 Manual fallback (documented in the README in bak-01, so it exists even without phase 5)

1. `docker compose stop std`.
2. Keep the current file: `cp /config/services.db /config/backups/pre-restore-manual.sqlite3`
   (the container is stopped, so a plain copy is consistent once the `-wal` file has been
   checkpointed; to be safe, copy `services.db-wal` too, if present).
3. Copy the snapshot over `/config/services.db` and **delete** `services.db-wal` and
   `services.db-shm`. A stale WAL from the old database must not be replayed over the
   restored one.
4. `docker compose start std`. The migrations bring an older snapshot up to date.

## 11. Management API and MCP

All routes are under `/api/v1`. Each one is registered in `mgmt_openapi.OPERATIONS`
(the completeness test enforces this), uses `require_api_key(scope)`, and returns JSON
errors.

| Method + path | Scope | Phase | Notes |
|---|---|---|---|
| `GET /settings/backup` | read | bak-02 | Effective values, each with `origin: env\|ui\|file\|default`, plus `last_runs` and `next_runs`. |
| `PUT /settings/backup` | write | bak-02 | Same validation as the UI. An env-set field → 409 "set by environment". Reschedules. |
| `GET /backups` | read | bak-02 | `{items: [{name, kind, size, modified, manual}]}`. No download route: snapshots hold secrets, and exports have `GET /export`. |
| `POST /backups/run` | write | bak-02 | `{kind: "snapshot" \| "export"}` → the run result (synchronous); 409 when already running. |
| `GET /export` | read | bak-02 | `?format=json` (default) or `yaml`. The v1 document. Not audited (a read). |
| `POST /import/plan` | write | bak-04 | Body `{document: <v1 object> \| null, document_text: str \| null, stream_map?}` (JSON, or YAML/legacy as text). Returns the plan + `fingerprint`. A dry run, but `write` because only a writer can act on it and it accepts large uploads. |
| `POST /import/apply` | write | bak-04 | `{document \| document_text, stream_map, selection, mode, fingerprint}` → `ImportResult`. 409 on a stale fingerprint (with the fresh plan). Audited (§7.8). |

- **`API_REVISION`:** these are additive `/api/v1` changes, so they need a bump. 0.11.0
  ships **revision 4**, with one `API_REVISION_HISTORY` row and one PRD §18.1 row. bak-02
  bumps it and writes the row. bak-04 extends the same row's text (same release, one
  revision). `FEATURES` gains `"backup"` (bak-02) and `"import"` (bak-04).
- Request models go in `mgmt_schemas.py` with `extra="forbid"` (the API boundary
  convention). The export document inside them is validated by `export_format`
  (lenient, §5.5).
- **MCP** (`mcp/std_mcp.py`): read tools `backup_settings`, `list_backups`,
  `export_config`; write tools `run_backup`, `import_plan`, `import_apply`. `import_apply`
  requires the fingerprint from `import_plan`, so an agent has to look at a plan before
  it applies one. The MCP README lists them.

## 12. UI

### 12.1 Backup & restore section (replaces design §9.12)

Header: "Backup & restore", subtitle "Daily database snapshots, exports of your
settings, and import." ⓘ Learn more: what a snapshot is versus an export, that exports
hold no secrets, the list of things to set up again, and the manual restore steps
(§10.2).

Cards, top to bottom (settings components: `card`, `switch`, `input-clean`, `kebab`,
`inline_warning`, `save_bar`):

1. **Location**: backup path field (read-only "Set by environment (`BACKUP_PATH`)" when
   env-set), origin label, outside-`/config` warning, Reset. The section's form has a
   sticky save bar (§6.9).
2. **Database snapshots**: switch "Daily snapshot", time (`input type=time`), "Keep
   days" (number, or read-only when env-set), "Next run …", "Last run …" or the failure
   warning, **Run now** (`btn-secondary`, its own POST form, outside the settings form),
   then the snapshot list (§4.6) with Download and a ⋯ menu (Restore…, Delete).
3. **Exports**: switch "Daily export", time, keep days, format select (YAML / JSON),
   next / last run, **Run now**, **Download export** (YAML / JSON split button), then the
   export list with Download and a ⋯ menu (Import…, Delete).
4. **Import**: drop zone / file input (`.yml`, `.yaml`, `.json`) or "Pick a server
   export" select, **Preview import** (`btn-primary`). One line: "Nothing changes until
   you review and apply."
5. **Restore database** (phase 5 only): "Pick a snapshot above (⋯ → Restore…) or
   upload one". The staged banner and the last-restore result live here.

The old *Backup* / *Restore* cards and the `action=backup|restore` branches of
`/settings` are removed in bak-04. Legacy files go through the new import.

### 12.2 Import flow

Its own page, `GET /settings/import/<token>` (a full page in the Settings shell, Data →
Backup & restore highlighted). A preview of thousands of rows does not fit a modal.
Steps are shown as a small stepper: **Upload → Map streams → Preview → Apply →
Summary**.

1. **Upload** (`POST /settings/import`, CSRF): parse, stage (§7.2), redirect to the
   token page. A parse error re-renders Backup & restore with an error banner in the
   Import card.
2. **Map streams** (shown at the top of the preview, not a separate page): one row per
   file stream with a `select.input-clean` of local streams with the same `key_type`
   (plus "Skip"), the local status, and the "not present yet" / "pending, enable after
   import" notes. Changing a mapping re-plans (`POST`, same token, re-render). Without
   file streams, the block is hidden.
3. **Preview**:
   - The header shows the file name, `exported_at`, `std_version`, format version, and
     "from another install" when `instance_id` differs. Warnings are inline warnings.
   - **Mode switch** (segmented radio group): *Fill missing only* (default) / *Also
     overwrite differences*. In fill mode, differing fields are shown greyed out with
     "Switch to overwrite to apply".
   - Toolbar: search (name / host), status filter chips (Missing · Differs · Ambiguous ·
     Not found · Waiting · Conflict), **Select all / Select none** (they act on the
     visible, selectable rows).
   - **Groups** (§6.8 collapsible group, tri-state checkbox, "N of M selected"), in this
     order: Docker, Manual, one per stream (`DHCP`), Groups, Notification channels,
     Streams & blocks, Users, Settings. Groups with something to do start expanded.
   - **Row:** checkbox, name, host or key, status pill, a short summary ("3 missing ·
     1 differs"), and a disclosure that opens the **per-field table**: field · in file ·
     here · a per-field checkbox (missing ticked; differs unticked and enabled only in
     overwrite). Ambiguous rows have the target select. Not-found rows have an "Import as
     new" switch and say what it becomes. Identical rows are collapsed into "12
     identical" per group (expandable, read-only).
   - **Sticky apply bar** (the save-bar component, always visible on this page):
     "14 records · 31 fields · 2 new · fill missing only", **Cancel** (`btn-ghost`,
     deletes the staged file), **Apply import** (`btn-primary`, confirm dialog when
     overwrite mode is on: "Overwrite 3 values that differ?").
4. **Apply** (`POST /settings/import/<token>/apply` with the selection as form fields
   `sel-<rid>`, `field-<rid>-<field>`, `target-<rid>`, `create-<rid>`, `opt-<rid>-<opt>`,
   `mode`, `fingerprint`). A stale fingerprint re-renders the preview with the banner of
   §7.2 and keeps the operator's ticks where the rows still exist.
5. **Summary**: the result card (§7.7), with "Back to Backup & restore" and "Run the
   import again" (same file, a new plan). The staged file is deleted, so "again"
   re-uploads it from the server copy when it came from the backup folder, or asks for
   the file.

JS: `static/js/settings/import.js` (row disclosure, mode switch greying, counts in the
apply bar, filter chips). It reuses `ui.js` for groups, tri-state and confirm. Without
JS the form still posts the ticked boxes.

**Users group:** each not-found user has "Create user (no password)" (off), and the
group subtitle says "Created users cannot sign in until an admin sets a password in
Users."

## 13. Risks

| Risk | Mitigation |
|---|---|
| The "fresh value" heuristic calls a deliberate default "missing" (an operator who disabled the Container check on purpose, then imports a file where it was enabled) | Fill mode only touches fields that are at the fresh value, and the per-field table shows every one. The common case (fresh install) is exactly a database of fresh values. |
| Import as new for stream records turns a once-stream-created entry into a *linked* one after the offer is accepted | Documented in the row note and the README. Off by default. The recommended path is wait + re-run. |
| A renamed stream entry imported as new never gets an offer | The row note points to Link by hand. Re-run after the sidecar posts is the main path. |
| Check targets carry literal IPs (`Ping 10.0.40.30`) that may have changed on the new network | Stream default checks are re-created by the stream on the new IP, and match by `(check_type, name)`, so the file's target shows as *differs* (not applied in fill mode). `follow_ips` keeps targets current after that. |
| Applying under `_UPSERT_LOCK` blocks registers for the duration | The apply is bounded (≤ 20,000 rows, one transaction, no network). Measure in bak-03. A typical homelab apply takes well under a second. |
| A stale plan after a snapshot arrives annoys the operator | The fingerprint covers only selected rows and no observed fields. The re-render keeps their ticks. |
| `instance_id` differs on a new install, so Home Assistant sees new devices | Q1. |
| The legacy file holds widget API keys in clear text | Ignored on import, with a preview warning (§9). |
| Snapshot downloads hold every secret | Session-only, admin-only, a warning next to Download, not in the API. |
| The pre-migration swap runs on every start | It exits at once without `pending.json`. It uses only the stdlib, and it is tested with a temp `CONFIG_DIR`. |
| The settings-modernization phases are still landing | bak-01 depends on set-01 (shared components and `partials/settings/backup.html`). Each prompt re-reads the code it touches. |

## 14. Open questions

**Answered by the operator (2026-11-20):** Q1 — **no**: no "adopt install id" row; after a
move Home Assistant devices are simply recreated under the new install (per-entry HA
publish / exclude flags are still exported and imported). Q2 — YAML default, JSON
selectable. Q3 — keep 00:05 (snapshot) and 00:10 (export). Q4 — build bak-05 (staged
restore). The questions as asked are kept below for the record.

1. **`instance_id` on import.** Home Assistant unique ids and MQTT client ids are built
   from `instance_id` (PRD 17.2). A new install has a new one, so after the import Home
   Assistant sees a second set of devices, and the old retained discovery topics stay on
   the broker until purged. **Proposal:** a Settings row "Adopt this file's install id",
   off by default, shown only when the ids differ, with a note that the old install
   must not run at the same time. Applying it changes `instance_id` and requests a full
   sync. It is not in the build prompts until the operator says yes. (If yes, bak-04
   adds it.)
2. **Scheduled export format default.** YAML (readable, today's habit) or JSON
   (exact round trip, no YAML edge cases)? The design defaults to YAML.
3. **Default times.** Snapshot 00:05 (today), export 00:10. Is a later default (e.g.
   03:00) better for hosts that do their own nightly jobs at midnight?
4. **Phase 5.** Build the staged restore now, or park it in `docs/FUTURE.md` and rely on
   the manual fallback (§10.2)?

## 15. Later (not in 0.11.0)

- Per-kind env / `settings.yml` keys (`BACKUP_SNAPSHOT_KEEP_DAYS`, ...), and env control
  of enabled and time.
- Off-host targets (S3, SFTP, rclone) and backup encryption.
- A "mirror" import mode that also removes local records missing from the file.
- Scheduled or API-triggered automatic import.
- Answering link offers from the import preview.
- Exporting soft-deleted entries and detached widgets.
- A management API staged restore, and restore of a single table.
- Per-entry export (from the Edit page) and partial export (by group or source).
- Diffing two exports in the UI.

## 16. Phase plan

| Phase | Prompt | Scope | Depends on |
|---|---|---|---|
| 1 | `bak-01-scheduled-backups` | DB-stored backup settings + precedence, `backups.py`, two jobs + per-kind retention + manual run, `last_runs`, list / download / delete, path validation, Backup section shell (Location, Snapshots, Exports cards; the existing Backup/Restore cards stay, restyled, as an "Import (legacy)" card). The export job keeps writing today's YAML list until bak-02. PRD planned section + revision row. README (settings, manual restore steps). | settings **set-01** landed |
| 2 | `bak-02-export` | `export_format.py` (v1 models, `build_export`, `dump`), Download export, the scheduled export writes v1 `-std_export.*`, management API (`/settings/backup`, `/backups`, `/backups/run`, `/export`), API_REVISION 4, MCP tools. | bak-01 |
| 3 | `bak-03-import-engine` | `importer.py` (`parse` v0 + v1, matcher, `plan`, `apply`, fingerprint, staging store), `export_format.from_legacy`, exhaustive tests. No UI, no routes. | bak-02 |
| 4 | `bak-04-import-ui` | Import card, upload → mapping → preview → apply → summary, users without passwords (Users tag), removal of the old restore branch, API `import/plan` + `import/apply`, MCP. PRD sections marked delivered (except §restore); `docs/FUTURE.md` "Backup contents and format" removed. | bak-03 |
| 5 | `bak-05-staged-restore` | `restore_staging.py`, `restore_swap.py`, entrypoint hook, Restore card, banners. Marks the PRD restore subsection delivered. If the operator drops it, the orchestrator moves PRD's restore subsection to `docs/FUTURE.md`. | bak-01 (bak-04 for the section layout) |

Each phase is one `feat:` commit with its own CHANGELOG `[Unreleased]` lines, and leaves
the suite green (`pytest -q`, `ruff check .`).

## 17. Decisions

For the orchestrator to copy into `docs/decisions.md` (newest at top):

- **Precedence for backup settings: env > UI (DB) > `settings.yml` > default.** Env is
  shown read-only. `settings.yml` only seeds, so a UI save is never silently ignored.
  Reset deletes the DB row. `backup_days_to_keep` seeds both keep-days values. No new
  file or env keys.
- **Two scheduler jobs with their own cron triggers, rescheduled in process.** A disabled
  job is paused, not removed. This relies on the single gunicorn worker. The scheduler is
  kept in `jobs._SCHEDULER`.
- **Manual runs are synchronous** and get a timestamped name (`YYYY-MM-DD_HHMMSS-…`),
  so they never overwrite the scheduled file of the day. Retention is per kind, by mtime,
  by suffix only. Legacy `-std_backup.yml` files age out with export retention.
  `backup.yml` and `pre-restore-*` are never auto-deleted.
- **A path outside `CONFIG_DIR` is a warning, not an error.**
- **Snapshots are downloadable from the UI only, never through the API**, because they
  hold every secret.
- **The export leaves out soft-deleted entries and detached widgets.** The snapshot covers
  the trash.
- **URLs are exported only when operator-owned** (`ui_edit`, or any URL on a manual or
  stream entry), and imported as `ui_edit`. `image_icon` is exported only where register
  does not rewrite it (manual, stream, locked Docker).
- **"Missing" means the local value is the fresh-row value.** For Docker group and sort
  priority, a value equal to `notifier_reported_*` also counts as fresh. Under
  `notifier_wins` those two fields are not importable.
- **Unknown fields in a supported format version warn; a newer `format_version` is
  rejected.** Adding an optional field keeps version 1.
- **Plan handoff: re-plan on apply under `_UPSERT_LOCK` → `streams._LOCK`, and compare a
  sha256 fingerprint of the selected rows.** The UI stages the parsed file in
  `CONFIG_DIR/import-staging/<token>.json` (60 min TTL, bound to the user). The API is
  stateless.
- **Import never creates streams and never changes a stream's status.** Stream settings
  and blocks apply to a mapped stream even while it is pending, so filters and blocks can
  land before Enable.
- **Import never modifies existing users**, in either mode. New users get the
  `"!unset"` hash: no password works, nothing is generated or shown, and an admin sets one
  in Users.
- **Channel namespace keys (`base_topic`, `ha_prefix`, `ha_device_prefix`) are never
  changed on an existing channel by import.** New channels with `secret_set` are created
  disabled.
- **Import as new never sets `is_static`.** A locked manual entry is not adopted by
  register, so the lock is applied by a re-run after adoption.
- **Import never answers link offers.** A stream record whose key has an open offer is
  matched to the offered manual entry, with a note.
- **Legacy v0 files: `widget_api_key` is ignored with a warning; `source: stream`
  records are matched by MAC across `mac` streams.**
- **The import preview is its own Settings page, not a modal** (it can hold thousands of
  rows).
- **One `API_REVISION` bump (to 4) for the whole 0.11.0 backup/export/import set.**
  bak-02 bumps it, bak-04 extends the row. The plan route needs `write`.
- **Staged restore swaps in `entrypoint.sh` before `alembic upgrade head`, using
  stdlib-only `restore_swap.py`.** The current DB is kept via `Connection.backup()`. A
  failure never blocks startup.
