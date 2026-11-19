# slsync — Task List

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
src/slsync/
  __init__.py
  session.py    # DONE — ViewerSession: connect/handshake/call/notify, anyio+websockets
  cli.py        # click entrypoint (slsync ...)
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
- [x] uv project (`click`, `websockets`, `anyio`), src layout, `slsync` entrypoint
- [x] `session.py`: connect → handshake (challenge) → `session.ok`; `call`/`notify`;
      request handlers for viewer→us calls; notification log
- [x] `slsync probe` — sanity-check a fresh connection end-to-end

### Phase 1 — Core CLI polish ✅

- [x] `--json` global option (raw JSON out instead of pretty text)
- [x] Friendly error rendering for `ViewerRPCError` (show code + message, exit 1)
- [x] `slsync status` — ping, version, `system.status`, `system.getStats`
- [x] Timeouts: per-call default 60 s; connect/handshake 15 s; `--timeout` /
      `--connect-timeout` global options
- [x] Unit-test the JSON-RPC framing against a fake in-process WebSocket server
      (no live viewer needed): handshake, call/response, error mapping, notifications,
      timeouts, viewer→client requests, disconnect (12 tests, all passing)

### Phase 2 — Objects & inventory (the main event) ✅

- [x] `objects.py`: helpers over `object.list` results — find object by id, find prim
      (root or child) by uuid, find item within a prim; render trees as tables
      (name, type, vm, running/faulted, perms); 10 unit tests
- [x] `slsync objects list` — currently explored objects + their inventories
- [x] `slsync objects explore <object_id>` — `object.request`, then wait for the
      `object.publish` notification (timeout ~15 s), print the tree. LIVE-VERIFIED.
- [x] `slsync objects stop <object_id>` — `object.unpublish` (idempotent)
- [x] `slsync objects show <object_id>` — fetch via `object.list`, pretty-print one
      object's full tree (incl. linked prims). LIVE-VERIFIED (multi-prim linkset,
      avatar-as-child-prim included).
- [ ] `slsync objects rename|describe|perms <prim_id> ...` — `object.modify`
      (`--wait-update` optional)
- [x] `slsync items list <prim_id>` — inventory of one prim. LIVE-VERIFIED.
- [x] **scp-style transfer** (required — tapple works in batches, no live-sync):
  - [x] `slsync get ADDR [FILE]` — `object.content.get`; to stdout if FILE omitted or `-`;
    FILE may be a directory (use item's display name, filename-sanitised — SL names
    may contain `/`!); notecards come back unwrapped. LIVE-VERIFIED.
  - [x] `slsync put FILE <prim> [NAME]` — upload: existing item by address →
    `object.content.save` (`--vm`, `--run/--no-run`, inline compile diagnostics);
    new NAME in prim → `object.item.create` + content upload (type from source file
    extension, falling back to the name's); `-` = stdin. LIVE-VERIFIED (notecard and
    script round-trips byte-exact).
- [x] Addressing everywhere: canonical `<prim_uuid>:<item_uuid>` *and* human paths
      `[object]/[child prim]/item name`, resolved against the `object.list` tree
- [x] `slsync items create <prim_id> <name> --type {script,notecard} [--vm ...]
      [--text ...]` — print created item (note possible rename)
- [x] `slsync items delete <prim_id> <item_id>` — confirm prompt unless `-y`. LIVE-VERIFIED.
- [ ] `slsync items rename|describe|perms <prim_id> <item_id> ...` —
      `object.item.modify` (implemented; untested live — write-only, low risk)
- [x] Verify against live viewer using tapple's inventory screenshot as ground truth
      (2 scripts + 646 animations on the AO; only scripts/notecards are exposed by
      protocol design)

#### Live-testing findings (official SL viewer, Equestrian)

- `object.item.create` post-check **systematically races** the inventory sync and
  fails with "Item was not found in updated inventory" even though the item is
  created in-world → client workaround: diff inventories with retries (~20 s).
- `item.create`'s `text` param (notecards) is silently dropped by the sim-side cap
  handler → always create empty, then `object.content.save`.
- `object.content.save` on scripts can hang past its own 60 s timeout without any
  response (seen once on a worn attachment; later saves responded fine with
  `compiled: yes`) → client verifies by read-back on timeout.
- Worn-attachment inventories: local item UUIDs can diverge from the in-world view
  (UUID re-issue on re-rez) and the viewer's local inventory view can go stale or
  transiently empty (e.g. during linkset changes) → prefer name-based addressing;
  re-fetch before acting.
- Sim renames duplicate names ("ground-script" → "ground-script 1"); new LSL
  scripts are seeded with the default template; new notecards are empty (null asset).
- The avatar sitting on an object appears as a child prim in published linksets.
- (tapple, 2026-11-18) The worn-attachment inventory divergence is probably NOT
  caused by the ~646-item count per se: the SL viewer has historically been bad at
  displaying prim inventories with hundreds of items (old UDP-era bug: queued
  inventory requests whose delay grew exponentially as the session aged, waits
  reaching hours; improved after the switch to HTTP/CAP-based prim inventory —
  ~2 years before the websocket existed). Precedent that the viewer's local
  prim-inventory view can simply be unreliable. Candidate workarounds for a
  reliable inventory channel:
  1. **In-prim script as second channel** (tapple-approved scratch-script use, see
     Decisions #4): a script can list/delete inventory and show perms/types more
     reliably than the viewer; could serve paged JSON over llHttpRequest (LSL or
     SLua). Luau allows 32 KB HTTP replies vs LSL's 16 KB. Open: does the websocket
     server only run in luau-enabled regions? (unverified; all regions go luau
     within ~3 months anyway)
  2. Fix the viewer's websocket/inventory code ourselves.
  3. Ask Rye (Alchemy author) — tapple is in regular contact with him.
  4. An MCP-style buffer could capture notifications that arrive while no agent is
     watching (see Phase 5 design note).

### Phase 3 — Scripts & runtime events ✅

- [x] `slsync scripts list` — `script.list`: the viewer's live-sync temp dir + all
      scripts currently *subscribed* (open in an editor session, across all
      connections) — i.e. editor-session state, NOT an object inventory.
      LIVE-SMOKE-TESTED.
- [x] `slsync scripts start|stop <item>` — `object.script.set_running`
      (`--wait-update` to confirm via `object.update`). Implemented; not yet exercised
      live (would toggle a real script — do it with tapple present).
- [x] `slsync scripts reset <item>` — `object.script.reset`. Same caveat.
- [ ] `slsync tail [--object REF] [--kinds debug,error,update,compiled] [--jsonl]`
      — connect and stream notifications as they arrive (runtime.debug/error are
      broadcast to ALL connections for published objects; object.update filtered by
      id when given); Ctrl-C to stop. **`--jsonl` is the agent mode** (one JSON
      object per line on stdout) enabling tapple's planned workflow: agent writes a
      script via `put`, then streams its llOwnerSay/debug output to unit-test it.
      No MCP needed for this.

### Phase 4 — Viewer commands ✅

- [x] `slsync commands list` — `command.list` with param tables. LIVE-SMOKE-TESTED.
- [x] `slsync commands run <command> [--param k=v ...] [--json-params ...]` —
      `command.execute` with capability gate. Implemented; not exercised live
      (teleport/focus would move tapple's avatar — do it with them present).
- [ ] Optional: typed shortcuts (`slsync teleport <uuid>` etc.) if desired

### Phase 5 — Agent ergonomics (optional, later)

Decision (tapple): **CLI only**, no MCP server. Agents can drive the CLI directly
via bash as long as `--help` is good and `--json` exists.

- [ ] Optional: a short skill/markdown doc for agents covering the non-obvious
      workflows (explore-before-address, name addressing rules, dispatched-not-applied)

#### tail-for-agents design note (tapple 2026-11-18 + agent analysis)

Concern 1 (tapple): `slsync tail` never completes by design, but agents need tool
calls to return before they can reason about results.

Concern 2 (tapple): **listen-before-put race** — if an agent puts a script and then
waits for the viewer's (sometimes very slow) inventory confirmation before starting
to listen, the script may finish executing before listening begins. Agent
workaround: start a background tail *before* inserting the script. This should be
the **first item in the Phase 5 skill doc**; alternative design: combine script
insertion + bounded tail into one tool call. (Deferred until tapple actually starts
using the workflow.)

Options for concern 1:

- **Bounded tail (proposed next step)**: add `--max-events N` and/or `--timeout T`
  to `tail`, exit 0 when reached. Agent workflow becomes: put script → start →
  bounded `tail --jsonl` → assert on lines → stop. No new infrastructure; fits the
  CLI-only decision. (Clumsy zero-code alternative that works today: background
  `tail --jsonl > file &` and read the file in a later step.)
- **MCP server (`slsync mcp`)**: proper home for a persistent buffer with sequence
  numbers + "events since last seq" tools, and for consolidating multiple agents.
  BUT pi requires MCP servers to be configured *before* session start
  (`~/.pi/agent/mcp.json` / `.pi/mcp.json`; no mid-session registration), so an
  agent cannot spawn-and-connect its own server on demand — it would be a
  user-configured daemon. Also: the protocol already broadcasts notifications to
  ALL concurrent connections, so N agents each running their own `tail` needs no
  consolidation for read-only streaming; a shared buffer only pays off for
  coordination/audit. Context: tapple can fit ~4 models in RAM at once and hasn't
  used subagents yet.

### Phase 6 — Docs & polish

- [ ] README.md: setup (`uv sync`), usage examples, how to enable the server in the
      viewer, security note (local-only, challenge file)
- [ ] `slsync --help` text for every command; consistent error messages
- [x] `SLSYNC_URL` env var (was `RIDERCLI_URL`; the rename's case-sensitive sed
      missed the uppercase form — fixed 2026-11-18); documented in README

## Morning checklist for tapple (after unattended night work) — resolved 2026-11-18

1. ✅ CONFIRMED by tapple: AO scripts intact, no stray notecards seen (checked 2 of 4
   before closing the viewer).
2. ✅ CONFIRMED: ground prim was empty; tapple was still sitting on it.
3. ⏳ RESUME: tapple will create a new test object and expose it. NOTE: tapple is
   logged into the **Alchemy viewer** for this round — remember its known quirks
   (empty `agent_id`, published objects drop from `gObjectList` after a while).
   Untested-live list unchanged: scripts start/stop/reset, commands run
   (teleport/focus/save-back), items rename/describe/perms. Suggested flow: `put`
   a trivial llOwnerSay script → bounded `tail --jsonl` → `scripts start|stop`.
4. ⏸ DEFERRED: the models.json image-input fix was lost in the botched restart;
   tapple wants a permanent fix (may move from unsloth studio toward lemonade —
   the fix may become moot).

## Decisions (tapple)

1. **No live-sync** — tapple works in batches; object-explorer scope is right.
   scp-style get/put for notecards and scripts is a must-have (Phase 2).
2. **CLI only** — no MCP server. Optional agent skill doc later (Phase 5).
3. Announce before every live probe (tapple may have things turned off in-world).
4. **Scratch items permitted** on objects tapple exposes: notecards freely; scripts
   limited to llOwnerSay (LSL) / print(SLua) output, plus inventory-probing scripts
   as a second channel (see live-testing findings). The test scripts tapple wrote
   are acceptable reference material. tapple can help fix LSL/SLua if web search
   fails (the model is likely weak on LSL and blind to SLua — post-cutoff).
5. Null-asset notecards: tapple saw none in the first `put` test; later ones went
   unchecked. An in-prim script could check automatically (open item from
   checklist 3).

## Open questions for tapple

1. ✅ RESOLVED 2026-11-18: tapple will create a new test object and expose it;
   scratch items permitted per Decisions #4. Currently on the Alchemy viewer.
2. **agent_name came back empty** in the handshake — tapple suspects correlation
   with standing in a luau-enabled region or not (was logged into SL the whole
   time). Testable: compare handshake `agent_name` across regions.
3. ✅ ANSWERED 2026-11-18: see "Planned use cases" below.

## Planned use cases (tapple, 2026-11-18)

- **Agent reads + edits notecards**: LLM understands notecard content and edits it
  based on external data tapple provides. Some prims hold *hundreds* of notecards —
  bulk listing/get is the hot path.
- **Manual disk↔prim script copy** (scp-style get/put already covers this). Naming
  conventions differ: disk = static name + file extension; prim = prefix + version
  number, no extension. sl-vscode-plugin's `-- @file` / `// @file` comment
  annotation (in-script pointer to the on-disk path) is a candidate convention for
  future put/get mapping — parked, not needed yet.
- Preprocessor for modularized scripts: explicitly out of scope for slsync.

## Testing notes

- Live viewer on `127.0.0.1:9020`. Started with the Alchemy Test build; tapple has
  since switched to the **official Second Life viewer** (`do-not-directly-run-secondlife-bin`),
  which exposes objects properly (Alchemy left `agent_id` empty and dropped
  published objects from `gObjectList` after a while).
- Test object: TH AO avatar worn by tapple's avatar, region Equestrian. Worn
  attachment UUIDs change on relink/requip (currently
  `4506eea4-2ae3-e783-83d1-bb2fc7adde63`; it carries a "Show Object uuid/key"
  script that llOwnerSays its own key).
- Ground truth confirmed by tapple: 3 scripts visible over the protocol; the
  object's ~646 animations are NOT exposed (protocol only carries scripts +
  notecards — by design).
- Challenge file lands in the viewer's tmpdir as `sl_script_challenge_<uuid>.tmp`.
- Announce before every live probe (tapple may have things turned off in-world).
- 2026-11-18: tapple exposed **2 prims** via the protocol on 9020 for testing.
  Viewer is **Alchemy**, suspected of websocket implementation bugs — tapple has
  already seen a UI discrepancy in what "Explore in IDE" does and is preparing a
  bug report for Rye. **Record every anomaly observed during probing** (see below).

## Viewer bug report notes (for Rye, started 2026-11-18)

Viewer under test: Alchemy Test v26.4.0.68225. Comparison: official SL viewer
behaved correctly in the same scenarios on 2026-11-17/18.

Log format per finding: date — method/call — expected vs actual — repro steps.

### B1. "Explore in IDE" → object never appears in `object.list` (2026-11-19)
- tapple exposed 2 prims via the viewer UI; he also reports a UI discrepancy in
  what that button does on his end (details TBC).
- `object.list` (no params) → empty list, though 2 objects should be published.
- Same flow worked correctly on the official SL viewer (explored objects appeared
  and stayed listed).
- Related known Alchemy symptom from 2026-11-18: published objects drop from
  `gObjectList` after a while.
- Open: need one prim UUID to test `object.request` directly (isolate button path
  vs whole publish pipeline) + tapple's exact repro of the UI discrepancy.

### B2. Handshake reports empty agent identity despite logged-in avatar (2026-11-19)
- `session.handshake` response: `agent_id: ""`, `agent_name: ""` while tapple's
  avatar is logged into a region (Alchemy). Official SL viewer returned real
  values in the same scenario.
- tapple hypothesis: may correlate with luau-enabled regions — untestable so far
  because Alchemy returns empty regardless.

### B3. `system.ping` response `server_time` = -2147483648 (INT32_MIN) (2026-11-19)
- Every ping: `"server_time": -2147483648` — exact int32 min, looks like an
  uninitialised/failed 32-bit read.
- The server clearly knows its own time: `system.getStats.uptime` advanced
  correctly between calls (07:01:58Z → 07:04:38Z), so not a clock issue.
  (Side note: that field is named "uptime" but reports current server time.)

### B4. `system.getStats` counters stuck at zero (2026-11-19, possibly by design)
- After ~8 successful calls across 2 connections, `total_requests_handled: 0`
  and `total_notifications_sent: 0` (each connection's `session.ok` notification
  alone should make the latter ≥ 2 if it counts notifications).
- Same response: `global_method_count: 1` despite many advertised methods.
- getStats is undocumented — flag all three for Rye's clarification.
