"""The `/api/v1` contract revision (PRD 18.1).

The revision is separate from the STD app version. An additive change to any
`/api/v1` contract (register, management, ingest) bumps `API_REVISION` by one in
the release that ships it, plus one row in `API_REVISION_HISTORY` and in the PRD
18.1 table. Breaking changes need `/api/v2`.
"""

API_REVISION = 4

# (revision, STD release, what it adds): the PRD 18.1 table as data.
API_REVISION_HISTORY = (
    (1, "<= 0.9.0",
     "/api/v1/register (v0.5.0+, canonical since v0.6.0); management API (v0.8.0, v0.9.0 additions)"),
    (2, "0.10.0",
     "meta, revision headers; update-check settings; notification channels, purge, cleanup, orphan scan; "
     "ha_publish; inventory streams and the ingest key scope"),
    (3, "0.10.1",
     "stream observability: optional snapshot_interval_seconds on the snapshot PUT; stream staleness, "
     "rejections, expected interval and missing expiry; health summary streams; inventory.missing_since"),
    (4, "0.11.0", "backup settings, backup list and run, export"),
)

# `streams` is advertised from 0.10.0 even though the endpoints land in a later
# prompt (inv-04) of the same release.
FEATURES = ("register", "management", "notifications", "streams", "backup")
