# slsync

A Python CLI for talking to the Second Life viewer's editor WebSocket server —
browse and edit in-world object inventories, transfer scripts/notecards
(scp-style), control scripts, stream runtime output, and run viewer commands.

- Protocol: [`external-editor-json-rpc.md`](./external-editor-json-rpc.md)
- Tasks: [`TASKS.md`](./TASKS.md) · Findings & notes: [`NOTES.md`](./NOTES.md) ·
  Architecture: [`ARCHITECTURE.md`](./ARCHITECTURE.md) · Agents: [`AGENTS.md`](./AGENTS.md)

## Quick start

```sh
uv sync
uv run slsync probe        # connect + sanity-check the session
uv run slsync status       # viewer identity, ping, stats
```

The viewer must be running with its editor WebSocket server enabled
(default `ws://127.0.0.1:9020`; override with `--url` or `SLSYNC_URL`).

## Everyday usage

```sh
# Explore an in-world object (needs modify perms), then browse it
slsync objects explore <object_uuid>
slsync objects list
slsync items list <prim>            # prim = uuid or name, or object/child path

# scp-style transfer (names may be uuids or human paths)
slsync get  <item> [FILE]           # FILE omitted/'-' → stdout; dir → write into it
slsync put  FILE <prim> [NAME]      # .lsl/.luau → script, else notecard; '-' = stdin

# Inventory management
slsync items create <prim> NAME --type script --vm lsl2
slsync items delete <item> -y
slsync items rename <item> NEW_NAME

# Script control + output tailing (agent-friendly: --jsonl)
slsync scripts start|stop|reset <item> [--wait-update]
slsync tail --object <object> --jsonl     # streams llOwnerSay/debug until Ctrl-C

# Viewer commands
slsync commands list
slsync commands run viewer.teleport --param object_id=<uuid>
```

Global flags: `--json` (raw JSON output), `--timeout`, `--connect-timeout`.

## Notes

- Objects must be **explored** (published) before their items can be addressed.
- Item names are pure inventory names — no file extensions.
- Worn attachments have flaky local-inventory sync in the current viewer build;
  prefer name-based addressing and re-fetching (see NOTES.md findings).
