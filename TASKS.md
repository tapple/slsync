# slsync — Tasks

Remaining work, by phase. Findings/decisions/test notes live in [`NOTES.md`](./NOTES.md);
how the code works + protocol gotchas in [`ARCHITECTURE.md`](./ARCHITECTURE.md);
orientation for agents in [`AGENTS.md`](./AGENTS.md).

Collaborator: tapple (she/her). Announce before every live probe.

### Phase 0 — Project setup ✅

- [x] Copy protocol doc into this folder (`external-editor-json-rpc.md`)
- [x] uv project (`click`, `websockets`, `anyio`), src layout, `slsync` entrypoint
- [x] `session.py`: connect → handshake (challenge) → `session.ok`; `call`/`notify`;
      request handlers for viewer→us calls; notification log (+ raw-frame hook)
- [x] `slsync probe` — sanity-check a fresh connection end-to-end

### Phase 1 — Core CLI polish ✅

- [x] `--json` global option (raw JSON out instead of pretty text)
- [x] Friendly error rendering for `ViewerRPCError` (show code + message, exit 1)
- [x] `slsync status` — ping, version, `system.status`, `system.getStats`
- [x] Timeouts: per-call default 60 s; connect/handshake 15 s; `--timeout` /
      `--connect-timeout` global options
- [x] Unit-test the JSON-RPC framing against a fake in-process WebSocket server
      (no live viewer needed): handshake, call/response, error mapping, notifications,
      timeouts, viewer→client requests, disconnect

### Phase 2 — Objects & inventory (the main event) ✅

- [x] `objects.py`: helpers over `object.list` results — find object by id, find prim
      (root or child) by uuid, find item within a prim; render trees as tables
- [x] `slsync objects list` — currently explored objects + their inventories
- [x] `slsync objects explore <object_id>` — `object.request`, then wait for the
      `object.publish` notification (timeout ~15 s), print the tree. LIVE-VERIFIED.
- [x] `slsync objects stop <object_id>` — `object.unpublish` (idempotent)
- [x] `slsync objects show <object_id>` — fetch via `object.list`, pretty-print one
      object's full tree (incl. linked prims). LIVE-VERIFIED.
- [ ] `slsync objects rename|describe|perms <prim_id> ...` — `object.modify`
      (`--wait-update` optional)
- [x] `slsync items list <prim_id>` — inventory of one prim. LIVE-VERIFIED.
- [x] **scp-style transfer** (required — tapple works in batches, no live-sync):
  - [x] `slsync get ADDR [FILE]` — `object.content.get`; to stdout if FILE omitted or `-`;
    FILE may be a directory; notecards come back unwrapped. LIVE-VERIFIED.
  - [x] `slsync put FILE <prim> [NAME]` — upload: existing item by address →
    `object.content.save` (`--vm`, `--run/--no-run`); new NAME in prim →
    `object.item.create` + content upload (type from source file extension); `-` = stdin.
    LIVE-VERIFIED (notecard and script round-trips byte-exact).
- [x] Addressing everywhere: canonical `<prim_uuid>:<item_uuid>` *and* human paths
      `[object]/[child prim]/item name`, resolved against the `object.list` tree
- [x] `slsync items create <prim_id> <name> --type {script,notecard} [--vm ...]
      [--text ...]` — print created item (note possible rename)
- [x] `slsync items delete ITEM_REF` — confirm prompt unless `-y`. LIVE-VERIFIED.
- [ ] `slsync items rename|describe|perms <prim_id> <item_id> ...` —
      `object.item.modify` (implemented; untested live — write-only, low risk)
- [x] Verify against live viewer using tapple's inventory screenshot as ground truth

(Live-testing findings from this phase: see NOTES.md.)

### Phase 3 — Scripts & runtime events ✅

- [x] `slsync scripts list` — `script.list`: editor-session state (subscribed
      scripts), NOT an object inventory. LIVE-SMOKE-TESTED.
- [x] `slsync scripts start|stop <item>` — `object.script.set_running`
      (`--wait-update` to confirm via `object.update`). Implemented; not yet exercised
      live (would toggle a real script — do it with tapple present).
- [x] `slsync scripts reset <item>` — `object.script.reset`. Same caveat.
- [x] `slsync tail [--object REF] [--kinds ...] [--jsonl] [--raw] [--all]` — stream
      events (broadcast to ALL connections; no subscription needed). Display modes:
      human (viewer-console style, TTY colours), `--jsonl` (agent mode), `--raw`
      (wire frames + broadcasts). Kinds: debug,error default; update, compiled,
      publish, unpublish; `--all`. LIVE-VERIFIED 2026-11-19. A running tail also
      keeps the viewer's "Explore in IDE" button in direct-publish mode (NOTES.md B1).

### Phase 4 — Viewer commands ✅

- [x] `slsync commands list` — `command.list` with param tables. LIVE-SMOKE-TESTED.
- [x] `slsync commands run <command> [--param k=v ...] [--json-params ...]` —
      `command.execute` with capability gate. Implemented; not exercised live
      (teleport/focus would move tapple's avatar — do it with her present).
- [ ] Optional: typed shortcuts (`slsync teleport <uuid>` etc.) if desired

### Phase 5 — Agent ergonomics (optional, later)

Decision (tapple): **CLI only**, no MCP server. Agents drive the CLI via bash as
long as `--help` is good and `--json` exists.

- [ ] Optional: a short skill/markdown doc for agents covering the non-obvious
      workflows (explore-before-address, name addressing rules, dispatched-not-applied)

(Design note — bounded tail vs MCP, listen-before-put race: see NOTES.md.)

### Phase 6 — Docs & polish

- [ ] README.md: setup (`uv sync`), usage examples, how to enable the server in the
      viewer, security note (local-only, challenge file)
- [ ] `slsync --help` text for every command; consistent error messages
- [x] `SLSYNC_URL` env var (was `RIDERCLI_URL`; case-sensitive sed missed the
      uppercase form — fixed 2026-11-18); documented in README
