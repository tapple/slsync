# ridercli

A Python CLI (and later MCP server) for talking to the Second Life viewer's editor
WebSocket server — browse and edit in-world object inventories, scripts, and run
viewer commands from your terminal.

- Protocol: [`external-editor-json-rpc.md`](./external-editor-json-rpc.md)
- Plan & status: [`TASKS.md`](./TASKS.md)

## Quick start

```sh
uv sync
uv run ridercli probe        # connect + sanity-check the session
uv run ridercli --help
```

The viewer must be running with its editor WebSocket server enabled
(default `ws://127.0.0.1:9020`; override with `--url` or `RIDERCLI_URL`).
