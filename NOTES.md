# slsync — Notes

Findings, decisions, test notes, and the bug-report master copies.
**Append new findings here** (live-test results under the matching section;
viewer anomalies go to "Viewer bug report notes"). Dates are UTC.

## Live-testing findings (official SL viewer + Alchemy, Equestrian)

- `object.item.create` post-check **systematically races** the inventory sync and
  fails with "Item was not found in updated inventory" even though the item is
  created in-world → client workaround: diff inventories with retries (~20 s).
- `item.create`'s `text` param (notecards) is silently dropped by the sim-side cap
  handler → always create empty, then `object.content.save`.
- `object.content.save` on scripts can hang past its own 60 s timeout without any
  response (seen once on a worn attachment; later saves responded fine with
  `compiled: yes`) → client verifies by read-back on timeout.
- The viewer's local inventory view can go stale or transiently empty (e.g. during
  linkset changes, and right after item deletes — seen on BOTH viewers) → prefer
  name-based addressing; re-fetch before acting. (tapple 2026-11-19: object UUIDs
  are assigned once when instantiated from avatar inventory — attachments get a NEW
  uuid every login, which fully explains the attachment uuid churn.)
- Sim renames duplicate names ("ground-script" → "ground-script 1"); new LSL
  scripts are seeded with the default template; new notecards are empty (null asset).
- The avatar sitting on an object appears as a child prim in published linksets.
- (2026-11-19 protocol probes, official viewer) `runtime.debug` channels that
  actually arrive: `owner_say` (llOwnerSay) and `debug` (llSay DEBUG_CHANNEL).
  llSay(PUBLIC_CHANNEL) does NOT arrive — the protocol only exposes those two
  channels. Delivery follows CHAT OWNERSHIP: a message is relayed only by the
  viewer whose avatar receives the chat (llOwnerSay on Pippin's prim reached
  only PippinGao's viewer; tapple's Alchemy tail saw nothing) — cross-viewer
  capture needs a message addressed to that avatar.
- Luau runtime errors (`error("...")` in a .luau script): arrive as
  `runtime.error` with the short text in `error`, the FULL viewer-console text
  in `message` ("Object [script:name] Script run-time error\nlua_script:1: ..."),
  and lua_script frames in `stack`. The spec's ItemRef.language field is
  UNRELIABLE — it reported "lsl" for the Luau script (object.list correctly
  shows vm=luau); slsync detects Luau via the lua_script markers.
- Compile errors are SILENT over the protocol: saving a syntactically invalid
  script (`]`) returns success:true with NO compiled field/diagnostics, and no
  `script.compiled` notification arrives. (Spec promises inline diagnostics.)
  Related known upstream issue (closed as expected, NOT re-reporting): scripts
  that failed compilation forget their intended VM — our bad-test script showed
  vm=mono after its compile failure:
  https://feedback.secondlife.com/slua-alpha/p/scripts-with-a-compiler-error-forget-their-vm
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
     SLua). Luau allows 32 KB HTTP replies vs LSL's 16 KB. Region requirement
     partially verified 2026-11-19: websocket works fine in a luau-enabled region
     (Equestrian); non-lua behaviour untested and moot — all regions go luau
     within ~3 months.
  2. Fix the viewer's websocket/inventory code ourselves.
  3. Ask Rye (Alchemy author) — tapple is in regular contact with him.
  4. An MCP-style buffer could capture notifications that arrive while no agent is
     watching (see "Design notes: tail for agents" below).
- (tapple 2026-11-19, pro-MCP argument for the record) separate CLI connections
  each see only their OWN request/response pairs; broadcasts reach everyone.
  A single persistent MCP connection would have full protocol visibility —
  including the viewer's responses to sibling calls — in one place. Weigh this
  against the CLI-only decision (Decisions #2) if debugging needs grow.

## Viewer bug report notes (master copy until posted; started 2026-11-18)

Viewer under test: Alchemy Test v26.4.0.68225. Comparison: official SL viewer
Release v26.5.0.42122621216. Log format per finding: date — method/call —
expected vs actual — repro steps.

**Status (posted 2026-11-19):**
- Official viewer report: POSTED by tapple —
  https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket
  She merged the shared-bug items in and rewrote for readability. Her item 6 =
  the Explore-in-IDE publish conditions (B1 resolution). Note: her first draft of
  item 6's evidence lines cited the getStats counters, which are zero regardless
  of state (that's the separate counters bug) — a corrected version citing
  `object.list` + viewer log lines was handed back in-session.
- Alchemy report: SENT to Rye (trimmed form: B2 + B6 + confirmed-working list +
  pointer to this repo; shared bugs referenced via the official report link).

Original item inventory for reference — Alchemy-specific: **B2**, **B6**.
Shared/by-design context: B1 resolution (silent no-op UX), B3/B4 (ask semantics).
Official items: port-in-use crash, ping `timestamp` int32 truncation (B5), ping
`server_time` INT32_MIN (B3), silent compile errors, ItemRef.language wrong for
Luau. The "Stop Exploring" label is NOT a bug on official — do not include it there.

### B1. "Explore in IDE" → objects never appear in `object.list` (2026-11-19)

**RESOLVED — not a bug: by-design behaviour, identical in both viewers.**

Root cause found in source (`llpanelcontents.cpp::onClickPublish`, same code in
`~/cabbage/secondlife/viewer` [official] and `~/cabbage/secondlife/NewAlchemy`
[Alchemy]):

```cpp
if (server->getConnectionCount())   // a websocket CLIENT is connected
    → toggle publish directly       // works without VS Code
else                                // no client connected
    → launchVSCode(object_id)       // opens vscode://lindenlab.sl-vscode-plugin/connect?port=…&object=…
```

The button presses failed because BOTH preconditions were unmet:
1. **No websocket client was connected** at press time (slsync not running)
   → handler took the launchVSCode branch.
2. **VS Code is not installed** (`code` not on PATH; Alchemy's ExternalEditor
   setting points to missing `/usr/share/code/code`) → launch failed.

Viewer logs prove it (both viewers, every button press):
```
WARNING LLProcess::launch : Could not locate 'code' on PATH -- launch will likely fail
WARNING ScriptEditorWS launchVSCode : Failed to launch VS Code. …
```
…and ZERO `buildAndSendPublish` entries for any button press (only for our
protocol probes).

- Why objects appeared in `object.list` on 2026-11-17: almost certainly our
  protocol `objects explore` calls (which publish regardless of connections),
  conflated with the button in the notes. (Tapple's correct objection: slsync
  CLI connections last <1 s, so "happened to be connected at press time" is
  unlikely; a long-running `slsync tail` would have been needed — and Nov-17
  logs are rotated, so unverifiable.)
- The official viewer's "Stop Exploring" label tapple saw was CORRECT state
  reflection: after our protocol probe published her prims (08:21Z), the panel
  refresh synced toggle state from `isObjectPublished()` = true. Not a bug.
- Also found: the button only processes `getFirstRootObject()` — selecting 4
  prims and clicking once only acts on ONE of them (no error, no feedback).
- UX issues worth flagging to Rye (both viewers): silent failure when the
  external editor can't launch (log-only warning); no indication which mode
  (direct-publish vs launch-editor) applies; multi-select ignored.

**How to make the button work on this machine:**
1. Keep a websocket client connected — e.g. background `slsync tail`
   (persistent connection; also tapple's planned agent workflow), OR
2. Install VS Code so `code` is on PATH (+ sl-vscode-plugin).
   (Tapple has VSCodium, but it provides `codium`, not `code` — and she does
   NOT want the VS-Code path anyway: prior experience with sl-vscode-plugin
   was poor due to its workspace handling, though its sync client itself is
   fine — that's the part slsync studied/copied. The connected-client route
   via slsync is the preferred usage.)

#### LIVE VERIFICATION (2026-11-19 ~11:32Z) — button works with a connected client

Setup: unpublished b8af6575 from 9021 and e5f103bb from 9020; started two
persistent `slsync tail` listeners (one per viewer). Tapple pressed Explore in
IDE on each target prim, no VS Code involved:
- **11:32:04Z — official 9021: b8af6575 appeared** (tail saw its object event
  at 11:32:02Z)
- **11:32:29Z — Alchemy 9020: e5f103bb appeared** (tail saw its object event
  at 11:32:27Z)

Conclusion: the button's direct-publish branch works on BOTH viewers. B1 is
fully closed as a bug; the only remaining gripe for Rye is the silent-failure
UX. Side findings: Alchemy did NOT drop published objects this time — all 4
stayed listed 3+ h (the 2026-11-18 gObjectList-drop symptom did not reproduce);
and `object.request` via protocol works perfectly on both viewers for all 4
UUIDs including non-owned prims (2×2 matrix, ~07:45Z — ownership irrelevant).

### B2. Handshake reports empty agent identity despite logged-in avatar (2026-11-19)
- `session.handshake` response: `agent_id: ""`, `agent_name: ""` while tapple's
  avatar is logged into a region (Alchemy). Official SL viewer returned real
  values in the same scenario.
- A/B 2026-11-19, both avatars in Equestrian (luau region): official reports
  `agent_name: "PippinGao"` + UUID; Alchemy still empty → luau-region hypothesis
  ruled out; this is an Alchemy-specific bug.

### B3. `system.ping` response `server_time` = -2147483648 (INT32_MIN) (2026-11-19)
- Every ping: `"server_time": -2147483648` — exact int32 min, looks like an
  uninitialised/failed 32-bit read.
- The server clearly knows its own time: `system.getStats.uptime` advanced
  correctly between calls (07:01:58Z → 07:04:38Z), so not a clock issue.
  (Side note: that field is named "uptime" but reports current server time.)
- **A/B (2026-11-19): the official viewer returns the SAME -2147483648** — common
  to both viewers (unimplemented field?), not Alchemy-specific.
- Context (tapple): the viewer UI displays server time in PST; protocol timestamp
  fields are UTC ISO-8601 with Z — whether the protocol conveys timezone at all is
  unknown.

### B4. `system.getStats` counters stuck at zero (2026-11-19, possibly by design)
- After ~8 successful calls across 2 connections, `total_requests_handled: 0`
  and `total_notifications_sent: 0` (each connection's `session.ok` notification
  alone should make the latter ≥ 2 if it counts notifications).
- Same response: `global_method_count: 1` despite many advertised methods.
- **A/B (2026-11-19): official viewer returns identical counters** — common to
  both viewers, not Alchemy-specific. getStats is undocumented; please clarify
  expected semantics for Rye.

### B5. Official viewer truncates ping `timestamp` echo to signed int32 (2026-11-19)
- Spec: `timestamp` = "The original timestamp from the request, echoed by the
  editor server." We send a ms epoch (~1.795e12).
- Official (9021): echo came back as `-222971890` — exactly our value mod 2^32
  interpreted as signed int32 (verified against the send time). Any real ms epoch
  overflows int32, so the official echo is always negative.
- Alchemy (9020): echoes correctly as a 64-bit double (`1795071878704.0`).

### B6. Alchemy: publish button's toggle state shows only as greyed colour; label never swaps (2026-11-19)
- After a successful publish (client-connected path, see B1 verification), the
  button's TOGGLE STATE is applied — pressed/dark-grey look (visible after
  re-selecting the prim) — but its LABEL stays "Explore in IDE" and never swaps
  to "Stop Exploring" as on the official viewer. The pressed colour is also
  dark grey, unlike the bright blue used by other active toggle buttons in the
  UI (tapple: purely a style/label bug).
- Repro: with a websocket client connected (e.g. `slsync tail`), press Explore
  in IDE on an editable prim → object publishes (verify via `objects list`) but
  button text unchanged; re-selecting the prim reveals the pressed look.
- Code pointer for Rye's agent: XUI defines `label_selected="Stop Exploring"`
  (floater_tools.xml, `name="button publish"`, is_toggle=true), and
  llpanelcontents.cpp `getState()` does
  `mPublishButton->setToggleState(server && server->isObjectPublished(...))` —
  but Alchemy additionally overwrites the base label on every refresh via
  `mPublishButton->setLabel(getString(ide ? "ide_label" : "studio_label"))`
  (official has no such setLabel call); that apparently suppresses the
  selected-label swap and/or the active-colour styling.

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
   scratch items permitted per Decisions #4.
2. ✅ RESOLVED 2026-11-19 (A/B): empty `agent_name` is Alchemy-specific, not
   luau-region-related — see bug note B2.
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

## Design notes: tail for agents (tapple 2026-11-18 + agent analysis)

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
  coordination/audit + full request/response visibility (see pro-MCP argument in
  live-testing findings). Context: tapple can fit ~4 models in RAM at once and
  hasn't used subagents yet.

## Testing notes

- Live viewers (2026-11-19 A/B setup): Alchemy Test v26.4.0.68225 on **9020**,
  official SL viewer Release v26.5.0.42122621216 on **9021**
  (`slsync --url ws://127.0.0.1:9021` or `SLSYNC_URL`). Both avatars in Equestrian
  (luau region). **Record every anomaly observed during probing** (bug notes above).
- Current viewer state (2026-11-19 ~14:50Z): 9021 has b8af6575 + 689a7470
  published; 9020 has e5f103bb + 7a01ff67 (TH AO) published.
- PippinGao is tapple's ALT; Pippin has edit permission on tapple's objects and
  vice versa (so cross-ownership Explore-in-IDE works). Without edit perms the
  button is greyed/unresponsive — matches source gating (`new_button_enabled`
  requires `permModify`).
- Persistent listeners (keep "Explore in IDE" working; see B1): one per viewer,
  human mode, kinds debug,error,publish,unpublish → /tmp/tail-902{0,1}-human.txt.
  Stop: `pkill -f "slsync.*tail"` (mind self-matching compound commands — use a
  bracketed pattern like `tail --js[o]nl`); restart:
  `setsid nohup uv run slsync --url ws://127.0.0.1:90NN tail --kinds
  debug,error,publish,unpublish > /tmp/tail-90NN-human.txt 2>/dev/null &`.
- Viewer logs (great for debugging — they log every editor-server event, incl.
  `buildAndSendPublish`, `launchVSCode` failures): official =
  `~/.secondlife/logs/SecondLife.log`; Alchemy =
  `~/.local/state/alchemynext/Alchemy.log`. Viewer sources: official checkout at
  `../viewer` (v26.5.0, matches installed build), Alchemy built locally from
  `../NewAlchemy` (build number changes on rebuild).
- Test prim UUIDs (Equestrian, 2026-11-19): PippinGao's b8af6575-09a9-27e9-
  3584-738de2a8336e, 689a7470-5030-b7f6-324b-36a90c4a436b; tapple's
  e5f103bb-667f-c8c1-e4d9-0783dce9fcb8, 7a01ff67-47c2-d32f-24a4-ebe2819f8000
  (TH AO). All three non-AO prims are named "Object" (the SL default name —
  not a slsync fallback). The AO carries a "Show Object uuid/key" script that
  llOwnerSays its own key.
- Challenge file lands in the viewer's tmpdir as `sl_script_challenge_<uuid>.tmp`.
- Announce before every live probe (tapple may have things turned off in-world).
- Scratch test scripts used 2026-11-19 for protocol probes (all deleted after):
  llOwnerSay/llSay channel script, `error("...")` Luau script, `]` compile-error
  script — see live-testing findings above.

## Resolved: morning checklist (after unattended night work, 2026-11-18)

1. ✅ CONFIRMED by tapple: AO scripts intact, no stray notecards seen.
2. ✅ CONFIRMED: ground prim was empty; tapple was still sitting on it.
3. ✅ RESUMED & done: test objects created and exposed (see B1 round).
4. ⏸ DEFERRED (tapple's other project): the models.json image-input fix was lost
   in a botched restart; she wants a permanent fix (may move from unsloth studio
   toward lemonade — the fix may become moot).
