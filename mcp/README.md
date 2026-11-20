# STD MCP server

> **Not fully tested yet.** This MCP server and the management API it wraps are
> new in v0.8.0. They pass the automated test suite but have not been fully tested
> against real instances. Start with a **read** key, check the audit log in
> Settings → API after any writes, and keep a recent backup before letting an
> agent make changes.

A small [MCP](https://modelcontextprotocol.io) server that lets Claude Code (or
any MCP client) manage a Service Tracker Dashboard through its management API:
ask what is failing, add a manual entry with checks, edit groups, attach
widgets, and so on.

It runs **on your own machine**, next to the client. It is not part of the STD
Docker image, talks only to `<STD_URL>/api/v1`, and has no database access.

## Install

The easiest way is [uv](https://docs.astral.sh/uv/). `std_mcp.py` declares its
own dependencies in a header (PEP 723), so `uv run` fetches them on first use:
no virtualenv, no `requirements.txt` to copy around. uv caches the dependencies,
so only the first start is slow. It needs Python 3.10 or newer (uv finds or
fetches one).

**From a checkout** (updating means `git pull`):

```bash
claude mcp add std -s user \
  -e STD_URL=http://std.lan:8815 \
  -e STD_API_KEY=std_xxxxxxxx \
  -- uv run /abs/path/to/service-tracker-dashboard/mcp/std_mcp.py
```

**No checkout, pinned to a release:**

```bash
claude mcp add std -s user \
  -e STD_URL=http://std.lan:8815 \
  -e STD_API_KEY=std_xxxxxxxx \
  -- uv run https://raw.githubusercontent.com/crzykidd/service-tracker-dashboard/v0.9.0/mcp/std_mcp.py
```

Updating means changing the tag in that URL (and re-running `claude mcp add`).
Pinning to a tag, not `main`, means the code you run only changes when you
change it.

**Without uv** (a virtualenv):

```bash
cd service-tracker-dashboard/mcp
python -m venv .venv && .venv/bin/pip install -r requirements.txt
claude mcp add std -s user \
  -e STD_URL=http://std.lan:8815 -e STD_API_KEY=std_xxxxxxxx \
  -- /abs/path/to/service-tracker-dashboard/mcp/.venv/bin/python /abs/path/to/service-tracker-dashboard/mcp/std_mcp.py
```

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "std": {
      "command": "uv",
      "args": ["run", "/abs/path/to/service-tracker-dashboard/mcp/std_mcp.py"],
      "env": { "STD_URL": "http://std.lan:8815", "STD_API_KEY": "std_xxxxxxxx" }
    }
  }
}
```

Use a URL instead of the path to run a pinned release. Desktop is a GUI app and
may not see your shell `PATH`: if it cannot start `uv`, put the absolute path
(`which uv`) in `"command"`.

## Create a key

In STD, open **Settings → API** and create a key. Use **write** if Claude should
be able to change things, **read** to let it look only. A read key exposes only
the read tools; the server checks the key with `GET /api/v1/whoami` when it
starts. Revoke the key from the same page at any time. **Rotate** on the same
page issues a new secret for the key and invalidates the old one at once; after
rotating, put the new key in the MCP client config (`STD_API_KEY`) or the server
gets 401s.

## Add it to Claude Code

The `claude mcp add` commands are in Install above. Everything after `--` is the
command that starts the server. `-s user` makes it available in every project
(the default scope is just the current project, kept private to you). Check it
with `claude mcp list`.

The key ends up in your Claude configuration, so keep that file private.

## Settings

| Variable         | Meaning                                              | Default |
| ---------------- | ---------------------------------------------------- | ------- |
| `STD_URL`        | Base URL of your STD, for example `http://std.lan:8815` | required |
| `STD_API_KEY`    | The API key from Settings → API                      | required |
| `STD_VERIFY_TLS` | `false` to accept a self-signed certificate          | `true`  |
| `STD_TIMEOUT`    | Request timeout in seconds                           | `15`    |

## Tools

Read (any key): `list_entries`, `get_entry`, `health_summary`,
`get_health_history`, `list_groups`, `list_widgets`, `list_widget_types`,
`get_exposure_settings`, `list_notification_channels`, `get_notification_channel`,
`list_notification_previous_bases`,
`list_streams`, `get_stream`, `preview_stream`, `list_stream_blocks`,
`list_stream_offers`, `list_stream_unmatched_items` (inventory streams),
`get_config` (secrets are masked), `server_info` (the
versions of this script and of your STD, and whether they match).

Write (write key only): `create_manual_entry`, `update_entry`, `delete_entry`
(soft by default), `restore_entry`, `add_check`, `update_check`, `delete_check`,
`run_checks`, `upsert_group`, `set_widget`, `remove_widget`,
`set_exposure_settings`, `test_notification_channel`, `purge_notification_channel`,
`purge_entry_notifications`, `purge_stream_notifications`, `delete_notification_channel`,
`update_notification_channel`, `scan_notification_orphans`, `clear_notification_orphans`, `update_stream`, `enable_stream`, `disable_stream`,
`ignore_stream`, `delete_stream`, `unblock_stream_key`, `answer_link_offer`,
`link_entry_to_stream_item`, `apply_stream_default_checks`. `update_stream` also sets a
stream's `default_checks`; `list_streams` returns the `pending` stream count.

`update_entry` and `update_check` take a `fields` object: name only what should
change, and send `null` to clear a value. Errors come back as tool errors that
keep the API's message and details, for example `HTTP 409 (conflicts with the
current state): ...`.

Every change made through a write key is recorded in STD's audit log
(Settings → API) under the key's name.

## Versions

`std_mcp.py` carries its own version (`MCP_VERSION`, the STD release it was
cut with). At startup it asks STD for its version (`GET /api/v1/whoami`) and
compares the two as `MAJOR.MINOR.PATCH`:

- **Same major.minor** is fine, even when the patch differs (noted only on stderr).
- **STD newer**: STD may have features or tools this script lacks. Update
  `std_mcp.py` (new checkout, or a newer tag in the URL).
- **STD older**: some tools may call endpoints STD does not have yet and
  return 404. Upgrade STD. An STD older than 0.9.0 does not report a version
  and counts as older.
- **Unknown**: the STD version is not plain `X.Y.Z` (a dev build), so it could
  not be compared.

On a difference the server prints one line to stderr and tells Claude in its
instructions, so Claude can say "update the MCP server" when a tool is missing
or returns 404. It never refuses to start over a version difference. Ask Claude
to run `server_info` to see both versions.

## Try it without Claude

```bash
STD_URL=http://std.lan:8815 STD_API_KEY=std_xxxxxxxx uv run std_mcp.py
```

It prints one line to stderr (`connected to STD 0.9.0 as key 'name' (write);
std_mcp 0.9.0`) and then waits for an MCP client on stdin. An unusable key exits immediately with the
reason.

## Developing

The tests are in `tests/test_mcp_server.py` and run with the normal suite
(`requirements-dev.txt` includes this directory's requirements). This directory
has no `__init__.py` on purpose: a package named `mcp` would shadow the SDK.
Dependencies are pinned in `requirements.txt`, generated from
`requirements.in`; see the header of that file for the command. The same two
pins are repeated in the `# /// script` header of `std_mcp.py` (for `uv run`);
a test fails if they differ. `MCP_VERSION` follows the repo's `VERSION`
(`/release-prep` sets it; a test checks it).
