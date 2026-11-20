# slsync — Architecture

A Python (click + anyio) CLI client for the Second Life viewer's editor
WebSocket server (`ws://127.0.0.1:9020` by default).

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

## Layout

```
src/slsync/
  __init__.py
  session.py    # ViewerSession: connect/handshake/call/notify, anyio+websockets;
                # on_notification + on_raw_frame hooks (raw = every wire frame)
  cli.py        # click entrypoint (slsync ...); all commands incl. tail
  objects.py    # object tree helpers (find prim/item in published trees)
```

(`mcp_server.py` was planned, descoped 2026-11-18 — Decision: CLI only, see
NOTES.md. The pro-MCP argument is on record there if it's reconsidered.)

Design rules:

- **Stateless CLI.** Every invocation connects fresh. No local inventory cache:
  `object.list` returns *all currently explored objects with full trees*, so any
  item-level command can call it and locate its target by UUID.
- **One shared session core** (`ViewerSession`) used by every command, so
  behaviour stays identical.
- Output: human-readable tables/text by default; `--json` for raw JSON everywhere.
- Viewer is "dispatched, not applied" for many mutating calls (see gotchas) —
  a `--wait-update` flag waits for the confirming `object.update`.

## Invocation lifecycle and timeouts

Every invocation is a fresh connection (Design rules) running three stages.
("Stage" here means an invocation stage; the project's implementation phases
live in TASKS.md.)

1. **Connect.** TCP + WebSocket upgrade first (bounded by the websockets
   library's own default, not ours — loopback, no TLS). Then the protocol
   handshake under `--connect-timeout` (default 15 s): wait for the viewer's
   `session.handshake` request, answer it (reading its challenge file), wait for
   the `session.ok` notification. These are two separate timeout windows — up to
   2× `--connect-timeout` worst case.
2. **Primary calls.** One or more JSON-RPC calls, each bounded individually by
   `--timeout` (default 60 s) — except inside `put`, where `object.item.create`
   and `object.content.save` use `--save-timeout` (default 75 s; the viewer needs
   up to ~60 s for upload+compile). Responses are correlated by JSON-RPC id, so
   interleaved notifications can never satisfy a pending call.
3. **Reconciliation** (only when step 2 was inconclusive). Each follow-up is
   bounded individually; there is NO collective bound, so total wall time can
   exceed any single knob:
   - content.save timeout → one `object.content.get` read-back (hardcoded
     GET_TIMEOUT = 45 s)
   - create race ("Item was not found in updated inventory") or a create response
     naming a pre-existing item → up to 20 × (`object.list` at `--timeout` + 1 s)
   - `scripts start|stop --wait-update` → up to 15 s for an `object.update`
   - `objects explore` → up to `--wait` (default 15 s) for the publish

Known inconsistency in these bounds: see FOLLOWUPS.md F5.

## Gotchas from the spec (do not trip on these)

1. An object must be **published** before any of its items can be addressed by
   `prim_id`/`item_id`. `object.request` only *starts* publishing; the tree arrives
   asynchronously as an `object.publish` notification → wait for it (or poll
   `object.list`) before proceeding.
2. `object.content.get` on a **script** requires copy+modify perms; notecards are
   always readable. Notecard envelopes are stripped by the viewer on get.
3. `object.content.save`: scripts allow up to 60 s (upload + compile); notecards 30 s.
   Compile diagnostics come back **inline in the response** — do *not* wait for a
   `script.compiled` notification after this path. (Caveat found live: for a
   syntactically invalid script the viewer returns success with NO diagnostics at
   all — see NOTES.md.)
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

## tail display design (2026-11-19, tapple spec)

- human (default): viewer-console style `[HH:MM:SS] ObjectName: message`;
  colours on a TTY only (`NO_COLOR` disables; files stay clean): owner_say yellow,
  debug red, errors red, Luau errors white-on-red (fatal), system kinds grey.
- `--jsonl`: one JSON object per line on stdout (agent mode; status → stderr).
- `--raw`: every wire frame of THIS connection as received/sent (`[in]`/`[out]`)
  plus ALL broadcast notifications from any source. Sibling connections'
  request/response pairs are NOT visible (they go only to that connection).
