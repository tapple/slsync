# ridercli — Task List

A Python (click + anyio) CLI client — and later an MCP server — for the Second Life
viewer's editor WebSocket server (`ws://127.0.0.1:9020` by default).

Protocol spec: [`external-editor-json-rpc.md`](./external-editor-json-rpc.md)
(mirrored from `../viewer/doc/`). Reference implementation:
`../sl-vscode-plugin` (TypeScript, esp. `src/synchservice.ts` and
`packages/sl-ide-ws-client/`).

## How it works (verified against a live viewer)

- The **viewer runs the WebSocket server**; we connect as a plain client to
  `ws://127.0.0.1:9020`. Multiple simultaneous connections are supported
  (`system.getStats` reports `connection_count`).
- Immediately after connecting, the viewer sends a **`session.handshake` request**.
  We must answer it (with `challenge_response` = contents of the temp file it names)
  and then wait for the **`session.ok`** notification before making calls.
- JSON-RPC 2.0 framing; failures come back as `error` objects — branch on `error.code`.
- Everything is local-only (loopback + challenge-file auth).

Verified live (Alchemy Test v26.4.0.68220): handshake, `system.getVersion`,
`system.status`, `system.listMethods`, `object.list`, `command.list`, and the
undocumented `system.getStats`.

## Architecture

```
src/ridercli/
  __init__.py
  session.py    # DONE — ViewerSession: connect/handshake/call/notify, anyio+websockets
  cli.py        # click entrypoint (ridercli ...)
  objects.py    # object tree helpers (find prim/item in published trees)   [planned]
  mcp_server.py # FastMCP server exposing the same ops as MCP tools          [planned]
```

Design rules:

- **Stateless CLI.** Every invocation connects fresh. No local inventory cache:
  `object.list` returns *all currently explored objects with full trees*, so any
  item-level command can call it and locate its target by UUID.
- **One shared session core** (`ViewerSession`) used by both the CLI and the MCP
  server, so behaviour stays identical.
- Output: human-readable tables/text by default; `--json` for raw JSON everywhere.
- Viewer is "dispatched, not applied" for many mutating calls (see gotchas) —
  offer a `--wait-update` flag that waits for the confirming `object.update`.

## Gotchas from the spec (do not trip on these)

1. An object must be **published** before any of its items can be addressed by
   `prim_id`/`item_id`. `object.request` only *starts* publishing; the tree arrives
   asynchronously as an `object.publish` notification → wait for it (or poll
   `object.list`) before proceeding.
2. `object.content.get` on a **script** requires copy+modify perms; notecards are
   always readable. Notecard envelopes are stripped by the viewer on get.
3. `object.content.save`: scripts allow up to 60 s (upload + compile); notecards 30 s.
   Compile diagnostics come back **inline in the response** — do *not* wait for a
   `script.compiled` notification after this path.
4. `object.script.set_running` / `reset` / `object.modify` / `object.item.modify` /
   item create/delete: `success: true` means *dispatched*. Confirmation arrives as
   `object.update`.
5. Item names are **pure inventory names, no file extensions** (`.lsl`/`.luau` are
   display-only in the VSCode plugin).
6. The simulator may **rename** an item created with a duplicate name — use the
   response's `name`/`item_id`, not the request's.
7. Notifications (`object.publish/update/unpublish`, `runtime.debug/error`,
   `script.compiled`) are broadcast to all connections; `script.compiled` only to
   the subscribed connection.
8. Feature flags: only call `command.*` if the viewer advertised `commands: true`
   (it does in our build).

## Tasks

### Phase 0 — Project setup ✅

- [x] Copy protocol doc into this folder (`external-editor-json-rpc.md`)
- [x] uv project (`click`, `websockets`, `anyio`), src layout, `ridercli` entrypoint
- [x] `session.py`: connect → handshake (challenge) → `session.ok`; `call`/`notify`;
      request handlers for viewer→us calls; notification log
- [x] `ridercli probe` — sanity-check a fresh connection end-to-end

### Phase 1 — Core CLI polish ✅

- [x] `--json` global option (raw JSON out instead of pretty text)
- [x] Friendly error rendering for `ViewerRPCError` (show code + message, exit 1)
- [x] `ridercli status` — ping, version, `system.status`, `system.getStats`
- [x] Timeouts: per-call default 60 s; connect/handshake 15 s; `--timeout` /
      `--connect-timeout` global options
- [x] Unit-test the JSON-RPC framing against a fake in-process WebSocket server
      (no live viewer needed): handshake, call/response, error mapping, notifications,
      timeouts, viewer→client requests, disconnect (12 tests, all passing)

### Phase 2 — Objects & inventory (the main event)

- [ ] `objects.py`: helpers over `object.list` results — find object by id, find prim
      (root or child) by uuid, find item within a prim; render trees as tables
      (name, type, vm, running/faulted, perms)
- [ ] `ridercli objects list` — currently explored objects + their inventories
- [ ] `ridercli objects explore <object_id>` — `object.request`, then wait for the
      `object.publish` notification (timeout ~10 s), print the tree
- [ ] `ridercli objects stop <object_id>` — `object.unpublish` (idempotent)
- [ ] `ridercli objects show <object_id>` — fetch via `object.list`, pretty-print one
      object's full tree (incl. linked prims)
- [ ] `ridercli objects rename|describe|perms <prim_id> ...` — `object.modify`
      (`--wait-update` optional)
- [ ] `ridercli items list <prim_id>` — inventory of one prim
- [ ] **scp-style transfer** (required — tapple works in batches, no live-sync):
  - `ridercli get ADDR [FILE]` — `object.content.get`; to stdout if FILE omitted or `-`;
    FILE may be a directory (use item's display name); notecards come back unwrapped
  - `ridercli put FILE <prim> [NAME]` — upload: existing item by address →
    `object.content.save` (`--vm`, `--run/--no-run`, inline compile diagnostics);
    new NAME in prim → `object.item.create` (type from extension: `.lsl`→script,
    `.luau`→script/luau, else notecard); `-` = stdin
- [ ] Addressing everywhere: canonical `<prim_uuid>:<item_uuid>` *and* human paths
      `[object]/[child prim]/item name`, resolved against the `object.list` tree
- [ ] `ridercli items create <prim_id> <name> --type {script,notecard} [--vm ...]
      [--text ...]` — print created item (note possible rename)
- [ ] `ridercli items delete <prim_id> <item_id>` — confirm prompt unless `-y`
- [ ] `ridercli items rename|describe|perms <prim_id> <item_id> ...` —
      `object.item.modify`
- [ ] Verify against live viewer using tapple's inventory screenshot as ground truth

### Phase 3 — Scripts & runtime events

- [ ] `ridercli scripts list` — `script.list` (temp dir + subscribed script ids)
- [ ] `ridercli scripts start|stop <prim_id> <item_id>` — `object.script.set_running`
      (`--wait-update` to confirm via `object.update`)
- [ ] `ridercli scripts reset <prim_id> <item_id>` — `object.script.reset`
- [ ] `ridercli tail [--object ID] [--kinds debug,error,update,compiled] [-n N]`
      — connect and stream notifications as they arrive (runtime.debug/error are
      broadcast; object.update filtered by id when given); Ctrl-C to stop

### Phase 4 — Viewer commands

- [ ] `ridercli commands list` — `command.list` with param tables
- [ ] `ridercli commands run <command> [--param k=v ...] [--json-params ...]` —
      `command.execute`; typed shortcuts: `teleport <uuid>`, `focus <uuid>`,
      `save-back <uuid>`, `reset-all <uuid>`, `recompile-all <uuid> --target T`

### Phase 5 — Agent ergonomics (optional, later)

Decision (tapple): **CLI only**, no MCP server. Agents can drive the CLI directly
via bash as long as `--help` is good and `--json` exists.

- [ ] Optional: a short skill/markdown doc for agents covering the non-obvious
      workflows (explore-before-address, name addressing rules, dispatched-not-applied)

### Phase 6 — Docs & polish

- [ ] README.md: setup (`uv sync`), usage examples, how to enable the server in the
      viewer, security note (local-only, challenge file)
- [ ] `ridercli --help` text for every command; consistent error messages
- [ ] Optional: `RIDERCLI_URL` env var already supported — document it

## Decisions (tapple)

1. **No live-sync** — tapple works in batches; object-explorer scope is right.
   scp-style get/put for notecards and scripts is a must-have (Phase 2).
2. **CLI only** — no MCP server. Optional agent skill doc later (Phase 5).
3. Announce before every live probe (tapple may have things turned off in-world).

## Open questions for tapple

1. **Test object** — which in-world object should I use for live testing? Easiest:
   click "Explore in IDE" on it in the viewer (it then appears in `object.list`),
   or give me its UUID for `objects explore`. Is it OK to create/delete a scratch
   notecard on it while testing?
2. **agent_name came back empty** in the handshake — is your avatar actually
   logged into a region when you test? (Some calls may behave differently.)
3. Anything you expect from a "rider" workflow that isn't covered above
   (e.g. searching objects by name, bulk operations)?

## Testing notes

- Live viewer on `127.0.0.1:9020` (Alchemy Test build). `uv run ridercli probe`
  is the smoke test; it must not disturb an existing VSCode plugin connection.
- Inventory ground truth: tapple will screenshot the in-world inventory to compare
  against `objects show` / `items list` output.
- Challenge file lands in the viewer's tmpdir as `sl_script_challenge_<uuid>.tmp`.
