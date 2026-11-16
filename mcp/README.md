# STD MCP server

A small [MCP](https://modelcontextprotocol.io) server that lets Claude Code (or
any MCP client) manage a Service Tracker Dashboard through its management API:
ask what is failing, add a manual entry with checks, edit groups, attach
widgets, and so on.

It runs **on your own machine**, next to the client. It is not part of the STD
Docker image, talks only to `<STD_URL>/api/v1`, and has no database access.

## Install

You need Python 3.10 or newer.

```bash
cd service-tracker-dashboard/mcp
uv venv && uv pip install -r requirements.txt        # with uv
# or
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Create a key

In STD, open **Settings → API** and create a key. Use **write** if Claude should
be able to change things, **read** to let it look only. A read key exposes only
the read tools; the server checks the key with `GET /api/v1/whoami` when it
starts. Revoke the key from the same page at any time.

## Add it to Claude Code

```bash
claude mcp add std \
  -e STD_URL=http://std.lan:8815 \
  -e STD_API_KEY=std_xxxxxxxx \
  -- /path/to/service-tracker-dashboard/mcp/.venv/bin/python /path/to/service-tracker-dashboard/mcp/std_mcp.py
```

Use the Python from the environment where you installed the requirements.
Everything after `--` is the command that starts the server. Add
`-s user` to make it available in every project (the default scope is just the
current project, kept private to you). Check it with `claude mcp list`.

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
`get_exposure_settings`, `get_config` (secrets are masked).

Write (write key only): `create_manual_entry`, `update_entry`, `delete_entry`
(soft by default), `restore_entry`, `add_check`, `update_check`, `delete_check`,
`run_checks`, `upsert_group`, `set_widget`, `remove_widget`,
`set_exposure_settings`.

`update_entry` and `update_check` take a `fields` object: name only what should
change, and send `null` to clear a value. Errors come back as tool errors that
keep the API's message and details, for example `HTTP 409 (conflicts with the
current state): ...`.

Every change made through a write key is recorded in STD's audit log
(Settings → API) under the key's name.

## Try it without Claude

```bash
STD_URL=http://std.lan:8815 STD_API_KEY=std_xxxxxxxx python std_mcp.py
```

It prints one line to stderr (`connected ... as key 'name' (write)`) and then
waits for an MCP client on stdin. An unusable key exits immediately with the
reason.

## Developing

The tests are in `tests/test_mcp_server.py` and run with the normal suite
(`requirements-dev.txt` includes this directory's requirements). This directory
has no `__init__.py` on purpose: a package named `mcp` would shadow the SDK.
Dependencies are pinned in `requirements.txt`, generated from
`requirements.in`; see the header of that file for the command.
