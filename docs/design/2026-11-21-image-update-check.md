# Design: "Newer image available" check for tracked containers

**Status:** design, awaiting operator approval (2026-11-21). No code has changed.
**Author:** Claude (design session, 2026-11-21), from the operator's request: "every X hours,
check whether a newer image exists than the one each tracked container runs, and show it,
in the spirit of Diun / What's Up Docker".
**Code read:** STD `dev` at `3323239` (v0.11.0 plus the issue #5 image line), and
`crzykidd/docker-api-notifier` `main` (v0.4.1: `main.py`, `notifiers/service_tracker_dashboard.py`).
Where this doc and the code disagree, trust the code.
**Operator decisions (2026-11-21, §14):** the check runs **once every 24 hours**, with no
tighter schedule; it has an **on/off switch** in Settings (this design recommends default
off, §5). "Check GitHub for Docker containers" is read as checking the **image registries**
(GHCR, Docker Hub, quay, ...) for the tracked containers' images; Q11 asks whether GitHub
*releases* of the source repositories were meant instead.
**Related:** issue #6 (image repo link, `image_repo_url` override, built in parallel):
it shares the image reference parsing described in §3.2.

---

## 1. Goals and non-goals

Goals:

- For every Docker entry (`source = notifier`) with an image, STD answers one question
  on a schedule: **is a newer image available than the one this container runs?**
- Two detection models, picked per entry from the tag's shape (§2):
  - **Tag model** for pinned versions (`1.4.2`, `v2.3`, `16.4-alpine`,
    `4.0.14.2939-ls263`): list the registry's tags and find a higher one of the same
    shape. Needs **no notifier change**, so it ships in STD alone.
  - **Digest model** for moving tags (`latest`, `stable`, `16`): compare the registry's
    current digest for the tag with the digest the container **runs**. Needs the
    notifier to send the running digest (§2.3). Without it the answer is "unknown",
    never an error.
- Show it on the Dashboard, Tiled and Compact views (a badge and a filter), in the entry
  details, in the management API and MCP, and over MQTT / Home Assistant (an HA `update`
  entity).
- Be a good registry citizen: one request per **unique image reference** per run (many
  containers share one), `HEAD` for manifests (free on Docker Hub, §4.4), backoff,
  `Retry-After`, and a concurrency cap.

Non-goals:

- **STD never updates a container.** No pull, no recreate, no "Update" button. STD has no
  Docker socket and should not get one. (WUD does this; that is its job, not STD's.)
- No HA `update` *install* action (no `command_topic`), matching the "no command
  entities" decision of PRD §17.1.
- No changelog scraping. A release-notes link is derived when the image carries the OCI
  `source` label (§2.3), nothing more.
- No vulnerability scanning, no image size or layer diffing.

## 2. Detection models

### 2.1 Choosing the model per entry

Per entry `image_update_policy` (operator-owned, §6.2): `auto` (default), `tags`,
`digest`, `off`. `auto` picks from the tag:

| Tag | Model under `auto` | Why |
|---|---|---|
| none / `latest` / any tag with no digit (`stable`, `edge`, `release`, `lts`) | digest | It moves; there is no version to compare. |
| one numeric component (`16`, `v3`, `2024`) | digest | A major-line tag moves within the line (`16` gets 16.5). A newer line (`17`) is shown only under `tags`. |
| two or more numeric components (`1.4`, `1.4.2`, `16.4-alpine`, `2024.11.01`) | tags | A pinned version: a newer *version* is the interesting fact. |
| `@sha256:...` reference (pinned by digest) | none (`pinned`) | The operator froze it on purpose. Shown as "pinned by digest". |

`tags` and `digest` force a model; `off` hides the entry from the check entirely (no
registry request for its reference unless another entry needs it).

A pinned-version tag can *also* be rebuilt in place (linuxserver and many vendors re-push
`1.4.2` with base-image fixes). Under `auto` the tag model is used, and when the notifier
sends the running digest the digest of the *same* tag is compared too, shown as a weaker
"rebuilt upstream" note, not as an update badge (open question Q4).

### 2.2 Tag model (STD alone)

1. List tags: `GET /v2/<repository>/tags/list?n=1000`, following the `Link` header for
   pagination. Cap at 10 pages (10 000 tags); `linuxserver/*` and `library/node` reach
   thousands. Docker Hub alternative in §4.2.
2. **Shape matching.** Split a tag into runs of digits and non-digits. Its *skeleton*
   is the tag with every digit run replaced by `N`; its *version* is the tuple of digit
   runs as integers.

   | Tag | Skeleton | Version |
   |---|---|---|
   | `1.4.2` | `N.N.N` | (1, 4, 2) |
   | `v1.4.2` | `vN.N.N` | (1, 4, 2) |
   | `16.4-alpine` | `N.N-alpine` | (16, 4) |
   | `16.4-alpine3.20` | `N.N-alpineN.N` | (16, 4, 3, 20) |
   | `4.0.14.2939-ls263` | `N.N.N.N-lsN` | (4, 0, 14, 2939, 263) |
   | `1.5.0-rc1` | `N.N.N-rcN` | (1, 5, 0, 1) |

   Candidates are tags with **the same skeleton** as the running tag and a **greater
   version tuple**. This handles `v` prefixes, suffix variants (`-alpine` never jumps to
   `-bookworm`), linuxserver build numbers, and calendar versions, and it excludes
   pre-releases by construction (`-rcN` has a different skeleton) unless the operator
   already runs an rc. A suffix that embeds its own version (`-alpine3.20`) is compared
   too, so `16.4-alpine3.21` counts as newer; that is usually right (base image update).
3. **Scope.** A global default, overridable per entry: `any` (default: highest candidate),
   `minor` (same first component), `patch` (same first two). The result is classified
   `major` / `minor` / `patch` / `build` (first differing component) so the UI can say
   "1.5.0 (minor)".
4. **Per-entry include pattern** (`image_tag_pattern`, optional regex, full match): when
   set, it replaces the skeleton rule; candidates are tags matching the pattern, ordered
   by version tuple. This is the escape hatch for odd schemes (WUD's `wud.tag.include`,
   Diun's `include_tags`). Validated on save (compiles, length ≤ 200), evaluated with a
   per-tag time budget (Python `re` has no timeout; reject patterns with nested
   quantifiers, or evaluate only against tags ≤ 128 chars, which bounds the cost).
5. Store the candidates (up to 50 highest of the running tag's skeleton, plus the raw tag
   list hash) on the reference row (§6.1), so a per-entry pattern or scope change is
   recomputed locally without a registry call.

Pitfall: some vendors publish a higher version that is **not** newer (`2.0.0` → later
re-tagged `1.9.9` hotfix lines) or bogus tags (`9999`). The scope setting and the include
pattern cover this; no heuristic tries to be clever.

### 2.3 Digest model (needs the notifier)

**Comparison.** `HEAD /v2/<repository>/manifests/<tag>` → `Docker-Content-Digest` (the
*remote digest*). The entry is `update` when the remote digest differs from the
**running digest** the notifier reported, `current` when equal.

**The running digest, defined.** It is an entry of the **`RepoDigests`** of the image the
container was **created from** (`container.attrs["Image"]`, the image id), resolved with
`client.images.get(<image id>)`. Not `client.images.get(<image_name>)`: after
`docker compose pull` without a recreate, the tag points at the new image locally while the
container still runs the old one. Resolving by image id makes "pulled but not recreated"
correctly show `update`.

**Multi-arch pitfall (the important one).** For a multi-arch tag, `docker pull` records
the digest of the **manifest list / OCI image index** in `RepoDigests`, not the digest of
the platform manifest it actually ran. The registry returns whichever object matches the
request's `Accept` header. So STD must send **all four** media types on the HEAD:

```
Accept: application/vnd.oci.image.index.v1+json,
        application/vnd.docker.distribution.manifest.list.v2+json,
        application/vnd.oci.image.manifest.v1+json,
        application/vnd.docker.distribution.manifest.v2+json
```

Then a multi-arch tag returns the index digest (comparable to `RepoDigests`) and a
single-arch tag returns the manifest digest (also what `RepoDigests` holds). If STD sent
only the v2 manifest type, Docker Hub would answer with a platform manifest (or 404 for
an OCI index) and every multi-arch image would show "changed" forever. A test pins the
header. STD never compares platform digests and never needs the container's platform.

Other cases:

| Situation | `RepoDigests` | STD shows |
|---|---|---|
| Locally built / `docker load` / never pushed | empty | `unknown` "local image, no registry digest" |
| Image tagged under several repositories | several entries | STD picks the one whose repository equals the entry's normalized repository (§3.2); none matches → `unknown` |
| Pulled through a mirror (`registry-mirrors`) | `docker.io/...` names, same content digest | compares fine |
| Old notifier (does not send it) | n/a, column NULL | `unknown` "needs notifier ≥ 0.5.0" (version per §8) |
| Registry returns no `Docker-Content-Digest` on HEAD (rare, old registries, some proxies) | | GET the manifest with the same Accept and SHA-256 the body. **Never on Docker Hub** (a GET counts as a pull, §4.4). |
| containerd image store (Docker Engine 29 default for new installs) | still present; image id is the index digest itself | the same comparison works; the notifier prefers `RepoDigests` and falls back to the image id when it is an index digest. Verify on both stores in the notifier phase. |

**Register field.** One new optional nested object on `RegisterPayload`, `extra="forbid"`
like the other nested models:

```python
class ImageInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None                 # local image id, "sha256:<64 hex>"
    repo_digests: Optional[List[str]] = None # raw RepoDigests, "<repo>@sha256:<64 hex>", max 20
    created: Optional[str] = None            # image Created, ISO 8601
    version: Optional[str] = None            # OCI label org.opencontainers.image.version
    revision: Optional[str] = None           # OCI label org.opencontainers.image.revision
    source: Optional[str] = None             # OCI label org.opencontainers.image.source (http(s) only)

# RegisterPayload:
    image_info: Optional[ImageInfo] = None
```

The notifier sends the raw `RepoDigests`; **STD** picks the matching one (it owns the
reference normalization, so the rule lives in one place). The OCI labels are cheap to send
and make the digest model readable: "running 1.27.2 (latest@a1b2c3d), newer pushed",
and `source` gives a release-notes link (and feeds the issue #6 link derivation as a
lower-priority source, open question Q8).

**Semantics (safe degradation, CLAUDE.md):**

- `image_info` absent or `null` → **no update**: keep the stored values. An older
  notifier never sends it, so the columns stay NULL and the entry shows `unknown`.
- Present → **replace** all stored `image_info` values (observation, no ownership, no UI
  editing, like the network / port capture columns).
- If `image_name` changes in a payload that has **no** `image_info`, STD **clears** the
  stored digest values: a digest of the previous image must never be compared with the
  new image's tag.
- Validation: each `repo_digests` item must match `^[^@\s]{1,255}@sha256:[0-9a-f]{64}$`;
  a bad item is a 400 like any schema error (the notifier sends Docker's own values).

## 3. What STD has today, and what has to change first

### 3.1 Register today

The notifier sends `image_name` = `container.attrs["Config"]["Image"]`, the string the
container was created with (`nginx`, `lscr.io/linuxserver/sonarr:latest`,
`ghcr.io/org/team/app:1.2`, `localhost:5000/app:1`, `nginx@sha256:...`). STD splits it in
`image_utils.resolve_image_metadata` into `image_registry`, `image_owner`, `image_name`,
`image_tag` and **does not keep the raw string**. No digest is sent.

### 3.2 The parser has bugs that matter here (fix first)

`resolve_image_metadata` splits on `:` and `/` naively:

| Input | Today | Correct |
|---|---|---|
| `localhost:5000/app:1` | name `localhost`, tag `5000/app` | registry `localhost:5000`, repository `app`, tag `1` |
| `ghcr.io/org/team/app:1.2` (4 path parts) | everything NULL | registry `ghcr.io`, repository `org/team/app` |
| `nginx@sha256:abc...` | name `nginx@sha256`, tag `abc...` | repository `library/nginx`, digest `sha256:abc...` |
| `quay.io/app:1` (2 parts) | owner `quay.io` | registry `quay.io`, repository `app` |

Phase 1 adds `image_ref.py`, a pure parser following the distribution reference grammar
(first component is a registry when it contains `.` or `:` or is `localhost`; default
registry `docker.io`, official images under `library/`; tag after the last `:` of the last
path component; `@` digest). It returns `registry`, `repository`, `tag`, `digest`, and a
canonical string `registry/repository:tag`. `resolve_image_metadata` uses it for the
existing four columns (a `Fixed` CHANGELOG line: the details showed wrong or empty image
fields for registries with a port, nested paths and digest references), and a new
observed column `image_ref` keeps the canonical string (§6.2). Issue #6's link derivation
should call the same parser; coordinate at build time (the issue #6 prompt is in flight
and touches `image_utils` users but not the parser).

For Docker Hub the registry API host is `registry-1.docker.io`; `docker.io`,
`index.docker.io` and `registry-1.docker.io` all normalize to `docker.io` in the
canonical string.

## 4. Registry access

### 4.1 One generic client (`registry_client.py`)

All of Docker Hub, GHCR, quay.io, lscr.io, gcr.io, GitLab, Harbor, Gitea/Forgejo and the
plain `registry:2` speak the OCI distribution API v2. So there is **one** client, no
per-registry code paths except the Docker Hub host mapping and the Hub rule in §4.4:

1. Request (`HEAD /v2/<repo>/manifests/<tag>` or `GET /v2/<repo>/tags/list`).
2. `401` with `WWW-Authenticate: Bearer realm="...",service="...",scope="repository:<repo>:pull"`
   → `GET <realm>?service=...&scope=...` anonymously, or with HTTP Basic when the
   operator stored credentials for that registry (§4.3); retry once with
   `Authorization: Bearer <token>`. `WWW-Authenticate: Basic` → retry with Basic creds
   if any, else the error "registry requires login".
3. Tokens are cached in memory per `(realm, service, scope, credential id)` until
   `expires_in` (default 60 s when absent) minus a margin.
4. Redirects are followed only for `GET` on tags (lscr.io and others proxy to other
   hosts); the token is never forwarded to a different host.

Per-request timeout 10 s (connect 5 s), one retry on connection errors, `User-Agent:
service-tracker-dashboard/<version>`. Plain HTTP registries: only when the registry is
listed in a setting `image_update_insecure_registries` (like Docker's
`insecure-registries`); `tls_verify` off per credential row for self-signed homelab
registries. Private / self-hosted registries need nothing else; a registry STD cannot
reach shows an error on that reference only.

Examples of the flow: GHCR realm `https://ghcr.io/token`, quay `https://quay.io/v2/auth`,
Docker Hub `https://auth.docker.io/token` with service `registry.docker.io`. STD does not
hardcode these; it reads them from the challenge.

### 4.2 Tag listing cost on Docker Hub

`/v2/<repo>/tags/list` returns tags in lexical order with no dates, so the whole list is
needed. For Hub repositories with very many tags an optional optimization is the Hub API
`https://hub.docker.com/v2/namespaces/<ns>/repositories/<repo>/tags?page_size=100&ordering=last_updated`
(newest first, stop after a few pages). It is Hub-only and has its own rate limits;
recommend implementing the generic path first and the Hub API only if real repositories
hit the 10-page cap.

### 4.3 Credentials (optional, per registry)

A table `registry_credential` (§6.3): registry host (unique), username, **write-only**
secret (same posture as `notification_channel.secret`: plain in the DB, never returned by
the UI or API, `secret_set` in responses, blank keeps, a checkbox clears; never in an
export, present in the DB snapshot like every secret), `tls_verify`, `enabled`. A **Test**
button does one token request plus one `HEAD` on a reference the operator types. A
credential is used only for its exact registry host.

Anonymous access covers every public image, so credentials are a later phase (§8) unless
the operator has private registries (open question Q5).

### 4.4 Docker Hub rate limits

Verified against `docs.docker.com/docker-hub/usage/pulls/` (2026-11-21): unauthenticated
100 pulls per 6 hours per IPv4 address or IPv6 /64; authenticated Personal 200 per 6 hours.
"Using GET emulates a real pull and counts towards the limit. Using HEAD won't." So:

- The digest model uses **HEAD only** on Docker Hub. The GET fallback of §2.3 is disabled
  for `docker.io`.
- `tags/list` is not a manifest pull. It is still subject to Hub's general abuse limits;
  the run spreads requests (§5) and honors `429` + `Retry-After`.
- A `429` from any registry pauses **that registry** for the rest of the run and sets the
  next attempt for its references to `max(Retry-After, backoff)`.
- The check shares the host's IP with the Docker daemon's own pulls. HEAD costs nothing,
  so the check never eats the operator's pull budget.

## 5. Scheduling and load

- **One APScheduler job** `image_update_check_job`, `IntervalTrigger(hours=24)` with a
  `jitter` of 30 minutes, added in `jobs.start_background_workers`. **The interval is fixed
  at 24 hours (decided).** There is no interval setting and no way to schedule it tighter;
  the only other trigger is the manual, throttled Check now below. The first run after
  start is 24 h after the last persisted run (`image_update_last_run` in `setting`), so a
  restart never causes an extra round of registry traffic; when the check is first turned
  on, the first run is a few minutes later.
- **On/off switch (decided):** `image_update_enabled`, a DB `setting` row edited in
  Settings → Image updates (also via the management API, and overridable by
  `STD_IMAGE_UPDATE_ENABLED` like other env > UI precedence). Off means no job runs, no
  registry request is made, badges and the filter are hidden and the HA entities are
  withdrawn by the next reconcile; stored results are kept so turning it back on shows
  the last answers immediately (marked with their age).
- **Recommended default: off**, on new installs and on upgrade. Reasons: it is new
  outbound traffic to third parties (registries learn which images this install runs),
  which an upgrade should not start silently; the operator may already run Diun or WUD;
  and on a host already close to Docker Hub's anonymous limit an operator should choose
  it knowingly (HEAD is free, but tag listing is not nothing). Turning it on is one
  switch, and the Docker section shows a one-line hint pointing to it. (The STD self-update
  check is on by default, but that is one request to one host, about STD itself.)
- Other setting: `image_update_scope` (`any`), the default scope for the tag model.
- **Dedupe:** the run collects the distinct `(registry, repository, tag)` of active Docker
  entries whose policy is not `off`, and which model(s) each needs. One reference row,
  one tag list per repository (two tags of the same repository share one `tags/list`),
  one HEAD per tag. A homelab of 80 containers is typically 40 to 60 references.
- **Concurrency:** a `ThreadPoolExecutor(max_workers=4)` and at most 2 in flight per
  registry host. A run budget (30 min) stops a pathological run; unfinished references
  are retried next run.
- **Per-reference backoff:** on error the reference is skipped for `2^(failures-1)`
  daily runs (1, 2, 4 days), capped at 7 days; success resets. The daily cadence already
  keeps load low, so there is no in-run retry beyond one connection retry. A reference that is still erroring after the cap shows
  its last error and keeps retrying weekly.
- **Never on a request thread.** Pages read stored results only. The job is the only code
  that makes registry calls (plus the credential Test button, which runs under a ~5 s
  budget like the MQTT Send test).
- **Check now:** a global button (Settings) and a per-entry button (entry details / edit).
  It is a manual action, not a schedule, and it is throttled: a global Check now at most
  once per hour, a per-entry one at most once per 15 minutes per reference (the button
  says "checked 3 min ago, try again later"). Both set a request (like `jobs.request_run` for health checks) and trigger the job via
  `scheduler.modify_job(next_run_time=now)`; per-entry "check now" ignores backoff for
  that one reference. A module-level `_RUN_LOCK.acquire(blocking=False)`: if a run is in
  progress the request is kept and served by a follow-up mini-run when it ends.
  gunicorn runs exactly one worker, so a process-local lock is enough (same reasoning as
  `version_check.py`).
- **Writes:** registry I/O happens outside any DB transaction. Results are written per
  reference in short transactions, then the affected entries' states are recomputed
  (§5.1) and committed, which fires the notification commit listener (§7.4). No lock with
  `routes_api._UPSERT_LOCK` is held during network I/O.
- **Register path:** when a register changes `image_ref` or the running digest, the
  entry's state is recomputed in the upsert from the stored reference row (no network).
  A new reference never seen before is `unknown` "not checked yet" until the next run (or
  the run is nudged if the reference is new, debounced to once per 5 minutes).

### 5.1 State per entry

`state` is one of:

| State | Meaning | Badge |
|---|---|---|
| `update` | tag model found a newer tag, or digest model remote ≠ running | yes |
| `current` | checked, nothing newer | no |
| `unknown` | cannot tell: no running digest (old notifier, local build), not checked yet | no (details explain) |
| `error` | the last check of its reference failed (registry unreachable, 401, 404 repo) | no badge, a muted icon in details; listed in Settings |
| `pinned` | digest reference | no |
| `off` | policy `off`, or the global check disabled | no |

The update state is **not** part of the health roll-up (Q7): an available update is
information, not a fault, and must not tint rows or flip HA "State" sensors.

## 6. Data model

### 6.1 New table `image_reference` (remote facts, keyed by reference)

Remote facts are a property of the reference, not of the container, so they live in one
row per canonical reference, shared by every entry that uses it.

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `ref` | str(400), unique, indexed | canonical `registry/repository:tag` |
| `registry`, `repository`, `tag` | str | parsed parts |
| `remote_digest` | str(80) null | last HEAD result |
| `remote_digest_changed_at` | datetime null | when `remote_digest` last changed (HA `release_summary`, "pushed 3 d ago") |
| `candidates` | JSON null | tag model: up to 50 newer tags of the running skeleton, version-sorted, plus `tags_total` |
| `checked_at` | datetime null | last successful check |
| `last_error`, `last_error_at` | str(300) / datetime | short, no raw exception text (the CodeQL rule from `d08cf69`) |
| `failures`, `next_check_at` | int / datetime | backoff |
| `last_wanted_at` | datetime | last run in which an active entry needed it |

**Retention:** a nightly job deletes rows with `last_wanted_at` older than 30 days (the
image is no longer used). Nothing else grows: one row per reference, overwritten.
No history table (Q9: "when did 1.5.0 appear" can be added later from
`remote_digest_changed_at`).

No FK from `service_entry`: the join is by `service_entry.image_ref = image_reference.ref`
(both indexed). Entries come and go via register; a dangling reference is harmless and
pruned by retention.

### 6.2 New columns on `service_entry`

Observed (written by register only, never in the UI, not exported):

- `image_ref` str(400) null, indexed: canonical reference (§3.2).
- `image_running_digest` str(80) null: the `RepoDigests` entry matching the repository.
- `image_info` JSON null: the stored `ImageInfo` (id, created, version, revision, source).

Operator-owned (UI / API / export, never written by register, round-trip through export
per the PRD §20.2 ownership table):

- `image_update_policy` str(8) NOT NULL default `auto`: `auto|tags|digest|off`.
- `image_tag_pattern` str(200) null.
- `image_update_scope` str(8) null: null = the global default.

Computed and stored (written by the job and the register recompute, so the dashboard
filter is a plain SQL predicate and change events can be detected):

- `image_update_state` str(10) null (§5.1), `image_update_latest` str(128) null (the
  newer tag, or the short remote digest), `image_update_kind` str(8) null
  (`major|minor|patch|build|digest`), `image_update_since` datetime null (when the state
  became `update`).

Considered and rejected: putting the remote facts on `service_entry` (no dedupe; N
containers on the same image would mean N registry requests and N divergent answers).

### 6.3 `registry_credential` (phase 3)

`id`, `registry` (unique), `username`, `secret` (write-only), `tls_verify` (default true),
`enabled`, `created_at`, `updated_at`, `last_used_at`, `last_error`.

All schema changes in one Alembic migration per phase; no FK columns, so no FK indexes
needed; the two `ref` columns are indexed.

## 7. UI, API and notifications

### 7.1 Views

- **Badge** on Dashboard rows, Tiled tiles and Compact cards: a small Tabler
  `arrow-big-up-line` (or `package`) next to the name, tooltip "Newer image: 1.5.0
  (minor)" / "Image updated upstream (latest, pushed 2 d ago)". Only for `update`.
- **Filter:** a new `?updates=1` toggle beside the existing status / source filters
  ("Updates available (N)"), handled in `view_helpers` like `normalize_status_filter`.
- **Entry details** (`partials/entry_facts.html`, under the Docker image line from issue #5):
  - `update`: "Update: **1.5.0** available (minor) · checked 2 h ago" or
    "Update: newer `latest` pushed 2 d ago (running 1.27.2) · checked 2 h ago", with a
    release-notes link when `image_info.source` is a GitHub URL (`<source>/releases`).
  - `current`: "Image up to date · checked 2 h ago".
  - `unknown`: the reason ("needs notifier 0.5.0 or later for `latest` tags").
  - `error`: "Could not check: registry asked for a login" (muted).
  - A **Check now** link (admin).
- **Entry edit:** an "Image updates" block (Docker entries only): Policy (Auto / Newer
  tags / Digest / Off), Scope (Default / Any / Same major / Same minor), Tag pattern
  (regex, with a hint and a live "matches: 1.5.0, 1.4.3" preview computed from the stored
  candidates, no registry call).

### 7.2 Settings

A new section **Image updates** in the **Sources** group (beside Docker), slug
`image-updates`, built from the §19 shared components:

- **Enabled** switch (default off, §5) with the one-line explanation of what it sends
  where, and Default scope. No interval field: the text says "Checks once a day".
- Status card: last run (time, references checked, updates found, errors), next run,
  **Check now** (throttled, §5).
- Problems list: references in `error`, with the error and the entries using them.
- Registry credentials (phase 3): cards with host, username, Test, Edit, Delete; write-only
  password.
- Insecure (HTTP) registries list (phase 3).

### 7.3 Management API and MCP

All additive, one `API_REVISION` bump for the release plus a PRD §18.1 row, feature
`image_updates` in `/api/v1/meta` (and `image_info` for the register field, §8):

- Entry responses gain `image_update`: `{state, latest, kind, since, checked_at, error,
  policy, scope, tag_pattern, running_digest, ref}`. `PATCH /entries/{id}` accepts
  `image_update_policy`, `image_update_scope`, `image_tag_pattern`.
- `GET /api/v1/image-updates` (read): the per-reference list with the entries using
  each, filter `?state=update`.
- `GET`/`PUT /api/v1/settings/image-updates` (read / write): `enabled`, `scope`; the
  response also carries the fixed `interval_hours: 24`, `last_run`, `next_run` (read-only).
- `POST /api/v1/image-updates/run` (write; optional `entry_id`) → 202.
- Phase 3: `GET`/`POST /api/v1/registry-credentials`, `GET`/`PATCH`/`DELETE .../{id}`,
  `secret` write-only.
- Every route registered in `mgmt_openapi.OPERATIONS` (tests enforce it).
- MCP: `list_image_updates` (read), entries carry the block, `run_image_update_check`
  (write-scoped key only).

### 7.4 MQTT and Home Assistant (PRD §17.3 / §17.4)

- **State topic** `<base>/entry/<id>/image` (retained), for entries whose state is not
  `off`: `{installed_version, latest_version, title, release_url, release_summary,
  state, kind, checked_at, std_entry_id}`. For the tag model `installed_version` = the
  running tag, `latest_version` = the newer tag or the running tag when current. For the
  digest model both are `<tag>@<first 7 hex>` (`latest@a1b2c3d`), with the OCI `version`
  label in `release_summary` when known. `unknown` / `error`: `installed_version` null
  (Home Assistant shows the entity as unknown).
- `<base>/summary` gains `updates` (count of `update`). `<base>/entry/<id>/state` gains
  `image_update_state` (additive).
- **HA discovery:** one `update` entity per published entry (`ha_publish`) that has an
  image and a policy other than `off`: object id `entry_<id>_image`, unique id
  `<node>_entry_<id>_image`, `state_topic` = the image topic, no `command_topic` (read-only,
  PRD §17.1), `entity_category: diagnostic`, `availability_topic` `<base>/status`,
  `entity_picture` omitted (STD has no public base URL). Hub `sensor` "Updates available"
  (`hub_updates`, `value_json.updates`). Both go through `notify_ha.py` and the
  `notify_state.full_sync()` reconcile, so purge, opt-out and soft delete clear them like
  every other entity (no second mechanism). Verified against the HA MQTT update docs
  (2026-11-21): `command_topic` is optional, the JSON state keys are `installed_version`,
  `latest_version`, `title`, `release_summary`, `release_url`, `entity_picture`.
- Change detection: the job compares each entry's previous and new
  `(image_update_state, image_update_latest)` and requests a non-forced sync; nothing is
  published when nothing changed.
- No other channel types exist; "notification" in this design means the MQTT topic and
  the HA entity (HA automations do the alerting).

## 8. Cross-repo plan (consumer leads, producer follows)

STD's `RegisterPayload` rejects unknown keys, so the order is strict.

| Step | Repo | Ships | Useful on its own? |
|---|---|---|---|
| 1 | STD 0.12.0 | Parser fix + `image_ref` (§3.2); `image_reference` table, registry client, job, **tag model**, UI, settings, API, MCP; **and** the optional `image_info` register field accepted and stored, digest model compares when present; `API_REVISION` bump, features `image_updates` and `image_info` | Yes: pinned-version images get "newer tag" badges with any notifier. `latest`-style entries show `unknown` "needs notifier 0.5.0". |
| 2 | notifier 0.5.0 | Resolves the container's image by id, sends `image_info` (RepoDigests + OCI labels + created + id). **Gated:** it sends the field only when STD's `GET /api/v1/meta` lists `image_info` (re-checked when the `X-STD-API-Revision` header changes); otherwise it omits it and logs once. | Digest model goes live. |
| 3 | STD 0.12.x / 0.13.0 | MQTT topic + HA `update` entity + hub sensor; registry credentials and insecure registries | |

Notes:

- Shipping the schema in step 1, before the notifier code exists, follows "STD may lead
  arbitrarily far ahead".
- The notifier's gate is belt and braces: an operator who upgrades the notifier before
  STD would otherwise get a 400 on every register from that host. It also closes the
  parked FUTURE.md item "Notifier: log STD's API revision" as a side effect.
- Safe degradation: a newer STD with an older notifier keeps working (`image_info` absent
  → stored values kept, NULL → `unknown`); a newer notifier with an older STD omits the
  field because of the gate.
- PRD §22 gets a release-history line for the pair; the notifier's own docs record its
  requirement (STD ≥ 0.12.0 for `image_info`).

## 9. Phasing and MVP recommendation

**MVP = STD step 1**, built as three prompts:

1. `img-01-image-ref-parser`: `image_ref.py`, the parser fix, `image_ref` column +
   backfill migration (parse is not possible from the split columns for the broken cases;
   backfill from the columns where they are sound, the next register fixes the rest),
   `Fixed` CHANGELOG line. Small, independently useful, unblocks issue #6 link quality.
2. `img-02-check-engine`: `registry_client.py`, `image_reference` table, the job, tag and
   digest models, per-entry state, `image_info` register field (schema + storage + API
   revision), management API and MCP read/run, tests with a fake registry (token
   challenge, pagination, 429, the Accept header, multi-arch index digest).
3. `img-03-ui`: badge, filter, entry details, edit block, Settings section.

Then step 2 (notifier) and step 3 (MQTT/HA, `img-04`; credentials, `img-05`).

Why this order: the tag model is the part that needs nothing from anyone, and for a
homelab that pins versions it is most of the value. The digest model costs little extra in
STD once the client exists, and accepting the field early lets the notifier ship whenever.

## 10. Rejected alternatives (evaluated honestly)

**A. Integrate Diun or What's Up Docker instead of building a checker.**
Both are mature and cover more registries' quirks than STD will on day one. WUD in
particular already publishes Home Assistant MQTT `update` entities and can trigger
updates.

- *Diun* is event-only: it notifies on new/changed images via webhook / MQTT, with the
  image, digest and provider metadata (container name). STD could accept a
  `POST /api/v1/hooks/diun` and map it to entries by host + container. But Diun reports
  *changes*, not *state*: after a restart, a missed webhook or a recreate STD would not
  know whether an entry is still behind, and "current" is never asserted. It also runs
  one Diun per Docker host (or remote sockets), and the mapping from Diun's watch
  identity to STD's `(host, container_name)` is ambiguous across hosts.
- *WUD* has a REST API (`/api/containers` with `updateAvailable`, current and remote
  tags/digests). STD polling WUD is a reasonable integration with real state. Cost: one
  more service per host (or a WUD with several Docker endpoints), a second inventory of
  the same containers that can drift from the notifier's, and a hard dependency for a
  feature that STD's own data (it already knows every image on every host, deduped
  centrally) makes cheap to do natively.
- Verdict: **native** for the MVP, because STD already has the cross-host inventory, the
  check is a few hundred lines on a generic v2 client, and the badge / filter / HA
  entity fit STD's existing model. If the operator already runs WUD and is happy with it,
  "read WUD's API" is the better buy and could replace phases 2 and 3; that is open
  question Q10. A WUD/Diun ingest is a candidate for FUTURE.md if the native path is
  approved.

**B. Let the notifier check registries itself and send "update available".** Each host
would check the same images (no cross-host dedupe), credentials would spread to every
host, and the notifier (which also drives DNS and is not an STD component) would grow a
second responsibility. Its one advantage is access to the host's `~/.docker/config.json`
credentials. Rejected; the notifier only reports facts it alone can see (the running
digest).

**C. Remote facts as columns on `service_entry`.** No dedupe, divergent answers for
containers on the same image. Rejected (§6.2).

**D. `GET` manifests, or compare image `Created` dates.** GET counts as a Docker Hub
pull; `Created` is set by the build, is often reproducible-build zero (1970) and says
nothing about the tag. Rejected.

**E. Give STD a Docker socket and ask the daemon (`docker manifest inspect`, pull
dry-run).** STD is deliberately socketless and central. Rejected.

**F. Compute state on every page render instead of storing it.** Cheap to compute, but
the filter and the MQTT change events need a stored previous state anyway. Rejected in
favor of the stored, job-written columns.

## 11. Risks

- **False "update" on multi-arch images** if the Accept header regresses. Mitigated by a
  pinned test and by comparing only against `RepoDigests`.
- **Odd tag schemes** produce wrong "newer" answers. Mitigated by skeleton matching,
  scope, the per-entry pattern and `off`; the details always show *which* tag was found.
- **Large tag lists** (thousands): page cap, run budget, and the candidates cache.
- **Regex DoS** from the per-entry pattern: admin-only input, length cap, tag length cap.
- **New outbound traffic** to third parties revealing which images run here. Mitigated by
  the on/off switch, default off (§5), and a one-line explanation in Settings.
- **Parser change** alters existing `image_*` values for the broken cases (they become
  correct). Called out in the CHANGELOG.

## 12. Open questions for the operator

1. *(Decided: daily, with an on/off switch.)* Confirm the recommended **default off**
   (§5), or prefer on?
2. **Default scope** for the tag model: `any` (show 2.0.0 when running 1.4.2) or
   `minor` (same major only)? Recommendation `any`, with the kind shown.
3. **One-component tags** (`16`, `v3`): digest only under `auto` (recommended), or also
   show "newer line 17 exists"?
4. **Rebuilt pinned tags** (`1.4.2` re-pushed): show nothing, a muted "rebuilt upstream"
   note (recommended), or a full badge?
5. **Registry credentials in the MVP?** Only needed for private registries. Do you run
   any (self-hosted `registry:2`, private GHCR packages)?
6. **Parser fix as its own small release first** (0.11.1, `img-01`), or folded into 0.12.0?
7. **Keep updates out of the health roll-up** (recommended), or should "update available"
   count as `degraded`?
8. **Use the OCI `source` label** for the issue #6 repo link when no override is set and
   the registry-derived link is unknown?
9. **History:** is "current state + since" enough, or do you want a log of update events?
10. **Do you already run Diun or WUD?** If WUD is in place, reading its API (§10 A) might
    be preferred over phases 2 and 3.
11. **Registries or GitHub releases?** This design reads "check GitHub for Docker
    containers" as checking the image registries (GHCR included) for newer images. If you
    meant the GitHub *releases* of each container's source repository (the OCI `source`
    label, or the issue #6 link), that is a different check: it says "a new upstream
    release exists" even before an image is published, works only for GitHub-hosted
    projects, and uses the GitHub API (60 requests/h anonymous). It could be a later add-on
    using the same daily job; which did you mean?

## 13. Later (not in the MVP)

- Hub API tag listing optimization (§4.2).
- Release-notes summary from GitHub releases for GHCR/GitHub-sourced images.
- What's Up Docker / Komodo (and possibly Diun) as additional update providers (§14).
- A per-group or per-stack policy default.
- Notifier: read host Docker credentials and forward nothing (stays rejected unless
  private-registry demand appears).

## 14. Decisions

- **2026-11-21, operator:** the registry check runs once every 24 hours, fixed, with no
  tighter schedule (keeps registry traffic and rate-limit exposure minimal). Manual
  Check now stays, throttled (§5).
- **2026-11-21, operator:** the check has an on/off switch in Settings. This design
  recommends default off (§5); the operator confirms (Q1).
- **2026-11-21, operator (Q11):** "check GitHub for Docker containers" means the image
  registries (GHCR, Docker Hub, quay, lscr), as designed. GitHub releases stay a possible
  later add-on (§13).
- **2026-11-21, operator (Q1):** the switch defaults to **off**.
- **2026-11-21, operator (Q2):** the tag model's default scope is **`any`** newer version.
- **2026-11-21, operator (Q5):** **no private registries**; credentials (`img-05`) stay out
  of the MVP.
- **2026-11-21, operator (Q6):** the parser fix (`img-01`) is **folded into 0.12.0**, not a
  separate 0.11.1.
- **2026-11-21, operator (Q10, providers):** the check is built as an **update provider**
  behind a small interface. The built-in registry checker is the first and default provider,
  with its own on/off switch (default off). What's Up Docker and Komodo (which tracks image
  updates for its stacks/deployments) may be added later as optional providers that report
  the same per-entry state; they're not in the MVP. `img-02` must keep the provider seam
  (provider id on the stored result, the job iterating enabled providers) so adding one later
  needs no schema change.
- Q3, Q4, Q7, Q8, Q9 not answered yet; the recommendations in §12 stand as defaults.
