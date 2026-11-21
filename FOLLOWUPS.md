# slsync — Follow-ups

Known issues and verification debts that are NOT part of the phased work in
TASKS.md. When an item is resolved, move it (with outcome) into NOTES.md and
remove it from here.

## Open

### F4. Compile-error reporting — finish evidence gathering for bug-report item #4 (2026-11-19)
Context: tapple is updating the POSTED bug report; the master copy is on the web
(https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket,
fetchable via curl — do not trust local copies). Item #4 ("Compile errors return
no result") needs rewriting with today's A/B findings. Code from this session is
committed incrementally (tapple reviewed each step; see git log). Announce every
live probe.

**Environment:** official viewer 26.5.0 on ws://127.0.0.1:9021 with scratch
object "Object" [260d253b-6f65-f110-ac0f-9e70699fad60] explored (leftover test
items inside — clean up when done: `slsync --url ws://127.0.0.1:9021 items
delete Object/<name> -y`, inventory view is flaky, retry + verify via objects
show). Alchemy's scratch df7f06ef was DELETED in-world ~19:00Z — tapple
re-exposes one on 9020 or F4 runs against 9021 only. The committed `put
--save-timeout` flag is used by the repro; live tests in
tests/test_live.py use it too (`SLSYNC_LIVE_URL=ws://127.0.0.1:9021 uv run
pytest -m live`).

**Established this session (both viewers live):**
- Alchemy 9020: bad LSL + bad Luau → inline `compiled: no` + diagnostics in the
  save response. Good scripts → `compiled: yes`.
- Official 9021: bad Luau → inline diagnostics; **bad LSL → the save call gets NO
  response** (client timeout at 75 s default / `--save-timeout`); slsync read-back
  note "viewer did not confirm compilation", exit 0. Good scripts fine.
- Official 9021 nuance: its Luau diagnostics can arrive with an EMPTY message body
  ("ERROR line 4:              (to close '(' at line 3), got 'end'" — expected-text
  blank/garbled) while Alchemy rendered the full "Expected ')' ..." text. Include
  in the item #4 rewrite.
- `script.compiled` notification: never observed — EXPLAINED BY SPEC (full read
  2026-11-19): it is routed only to the connection subscribed via script.subscribe
  AND only produced while the viewer's script editor for that script is open.
  slsync never subscribes, so absence is by design, NOT a bug — do not report it.
  The object-explorer path gets compile feedback inline in the content.save
  response (which is where the real bugs are: see below).

**Steps:**
1. Run `tools/repro_compile_errors.sh` against each available viewer (default
   9020; pass ws://127.0.0.1:9021 for official). It is written per tapple's spec
   (one viewer, object by NAME "Object", inline scripts, unique names,
   --save-timeout 30, CONFORMS/DEVIATION verdicts vs spec, self-cleanup) but has
   NOT been run live yet — verify it first.
2. ~~Prove script.compiled absence with raw capture~~ — MOOT after full spec read
   (see Established): its absence is by design for non-subscribed clients.
3. **ASK TAPPLE (exit-code semantics):** put exits 0 when content is saved but
   compile state unknown (read-back path). Keep 0 vs exit non-zero so agents treat
   unconfirmed compiles as failures?
4. Rewrite bug-report item #4 around the REAL deviation: on official 26.5.0 a
   content.save of bad LSL returns NO response at all — spec guarantees inline
   compiled/diagnostics, or -32001 within 60 s ("Scripts allow 60 seconds for
   upload and compilation ... Exceeding either fails the call with -32001").
   Include the A/B table (Alchemy responds inline; official hangs) plus the
   empty-Luau-diagnostic-message nuance. Drop any script.compiled claim.
   DO NOT post; tapple reviews and posts.

### F7. item.create returns a pre-existing item id — investigate (suspected viewer bug, official 26.5.0)
Context: separate from F4 (different RPC method); observed correlation with a
preceding HUNG bad-LSL save is an open question, not established causation.
Environment/cleanup: see F4. Announce live probes. NOTE: the client-side guards
(name filter + pre-create snapshot check) are being consolidated into the
find_new_item primitive per F5 step 4 — they stay (the viewer bug is real and
unfixed); only their home moves.

**Evidence so far — exact sequence** (pytest run, SLSYNC_LIVE_URL=ws://127.0.0.1:9021,
official SL viewer Release 26.5.0.42122621216, scratch object "Object" [260d253b-6f65-
f110-ac0f-9e70699fad60]):
- (a) The save attempted before the failing create: `test_put_bad_lsl_reports_compile_failure`
  created item live-bad-lsl-<hex> (VM **lsl2**) and ran content.save with
  **BAD_SYNTAX_LSL** — 3 lines, missing closing brace:
    default {
        state_entry() {
            llOwnerSay("hi");
  The save call got NO response (timed out at --save-timeout 30; read-back confirmed
  the content was stored). This is the "hung" save with its compile-wait left dangling.
- (b) The failing create, immediately after: `test_put_bad_luau_reports_compile_failure`
  called object.item.create for a new item live-bad-luau-<hex> (VM **luau**, content
  **BAD_SYNTAX_LUAU** — 4 lines, missing closing paren in print). The RESPONSE carried
  {item_id: 9148c000-dff4-d33c-87e8-d33084471c77, name: "test-official-good"} — a
  PRE-EXISTING unrelated item — while live-bad-luau-* appeared in inventory. slsync's
  name filter was active, so the response itself was wrong (not our workaround).
  Consequence: slsync then saved the Luau content to 9148c000, clobbering
  test-official-good's content with BAD_SYNTAX_LUAU.
- Script texts live in tests/test_live.py (constants BAD_SYNTAX_LSL / BAD_SYNTAX_LUAU);
  identical texts are inline in tools/repro_compile_errors.sh.
- Solo runs of the identical create (no preceding hung save) pass. Reproduction not
  yet confirmed on demand.
- Client-side audit done: session.py correlates responses by JSON-RPC id (not
  arrival order); TCP ordering rules out intra-connection reordering; duplicate
  resolved ids are ignored (session.py _dispatch, verified by full read). Two
  dispatch edge cases for the wire scan to watch: (1) an inbound frame with an id
  but NEITHER result NOR error resolves the pending call with result=None; (2) a
  notification carrying an id is treated as a viewer→client REQUEST (method+id
  branch), not a response — it would get -32601 back if unhandled.
- Prior wire evidence: evidence/create-race-wire-20261119T2058Z.log — clean
  framing, single responses, no dupes/reordering in the documented race; also
  shows the viewer uses STRING ids ("rpc_1083") for its own requests vs our ints.
- Related known issue: the systematic "Item was not found in updated inventory"
  create race — likely the same unreliable post-creation inventory check failing
  in the other direction (returns an item instead of erroring).

**Steps:**
1. `uv run pytest -q` → all pass/skip; then `SLSYNC_LIVE_URL=ws://127.0.0.1:9021
   uv run pytest -m live -v` — the bad-luau test previously failed only after a
   hung bad-LSL save in the same process; with the committed pre-create guard it
   should pass, or fail loudly with "create response referenced a pre-existing item".
2. Reproduce under wire capture: `uv run --project . python tools/probe_create_wire.py
   ws://127.0.0.1:9021` (handles the step-1 race; writes /tmp/wire-capture-*.log —
   salvage any interesting log into evidence/). Success = it prints "BUG
   REPRODUCED" AND the wire log shows the VIEWER itself sent that item_id in its
   response. Note the wire-scan results (duplicate frames / non-response frames
   carrying ids).
3. If reproduced: draft a NEW bug-report item (master copy on the web, see F4);
   tapple reviews and posts. Also run against Alchemy 9020 once a scratch object
   exists there.
4. The slsync guards (now committed, see git log): create-race workaround now
   name-filters candidates (`_is_sim_rename`) — the old code overwrote an
   UNRELATED item when the viewer's inventory snapshot was stale (observed live);
   plus the pre-create snapshot guard rejecting create responses that reference a
   pre-existing id.

**Open questions:** is the dangling compile-wait from a timed-out save actually
the trigger, or timing coincidence? Does it also happen on Alchemy?

### F6. How agents invoke slsync needs a canonical story (noted 2026-11-19)
Two consecutive agent sessions fumbled this: hardcoded repo paths + `uv run
--directory` in one-off scripts, `uvx` vs `uv run` confusion, repeated
re-derivation of how to call the CLI. Candidates: document ONE canonical
invocation in AGENTS.md (e.g. `cd ~/cabbage/secondlife/slsync && uv run slsync ...`
or an installed entrypoint via `uv tool install`); keep repo scripts
(self-locating like tools/repro_compile_errors.sh) free of hardcoded paths.
Tapple: "I need to stop just vibecoding this tool" — pair with a proper test/
docs pass rather than ad-hoc live poking.

### F5. Cleanup plan: timeouts, waits & reconciliation (revised 2026-11-19 from code review)
Umbrella refactor task. Motivation: vibecoding left timeouts as 4+ scattered
constants/knobs and "reconciliation" as ad-hoc per-command loops; the
viewer-unreliability workarounds sit inline in `put` (~100 lines). Target shape:
tapple's three-stage invocation model, refined by code review — (1) connect,
(2) primary calls, (3) reconciliation via small named primitives with explicit
bounds. session.py is the clean part; cli.py is the mess.

Stage-model corrections (review of tapple's 2026-11-19 draft):
- Stage 1: TCP+WS upgrade currently sit OUTSIDE --connect-timeout (websockets lib
  default governs them); the protocol handshake uses TWO separate windows. → make ONE
  window cover connect→handshake→session.ok.
- Stage 2: correct as-is — id-correlated responses are sound; harden _dispatch to
  REQUIRE result|error on response frames (a malformed id-only frame would currently
  resolve a pending call with None).
- Stage 3: NO collective bound exists today; every loop is hand-rolled (put's
  create-race 20×(fetch+1 s), scripts --wait-update hardcoded 15 s, explore --wait,
  _save_with_verify read-back GET_TIMEOUT=45). → named primitives, bounds in one place.

Steps (each independently shippable; unit-test with FakeViewer where noted):
1. session.py: single connect window; require result|error in response dispatch;
   wrap OS/websockets errors as ViewerConnectionError(ViewerError).
2. cli._execute: catch ViewerConnectionError → friendly "cannot connect to <url> —
   is the viewer running with the editor server enabled?" exit 1. Closes F13.
3. Timeout unification: drop GET_TIMEOUT/SAVE_TIMEOUT constants and the
   --save-timeout knob (added+committed this session; deliberate reversal). One global
   --timeout as the unit for a single viewer op; per-op floors via max(--timeout, floor):
   save/create 75 s, get/read-back 45 s — spec-justified (full read 2026-11-19):
   content.save allows 60 s for scripts / 30 s for notecards and "a client's own
   timeout must exceed the longer of the two"; content.get times out at 30 s.
   Document the floors in help text.
   Reconciliation primitives take an explicit budget (default 2× call timeout).
   Update tests/test_live.py SAVE_TIMEOUT_ARG → --timeout. Rewrite ARCHITECTURE.md
   "Invocation lifecycle" section to match reality afterwards.
4. Extract the reconciliation core as `object_inventory.py` (name per tapple): a
   sync engine keeping a synced copy of ONE prim's inventory — metadata only
   (items: id/name/type/vm/running); content bytes stay direct object.content.get
   calls (verify_saved_content remains a separate small helper).

   Core model (expanded 2026-11-19, tapple + agent):
   - Async event loop (anyio task group) with cache states FRESH | STALE | POLLING.
     "Clean" (FRESH) means QUIESCENCE: a poll completed with no dirty mark arriving
     during it. That is NOT the same as "the poll a waiter was waiting for came
     back": waiters are evaluated against the latest cache after EVERY poll and may
     be satisfied while the cache is still STALE (more changes in flight) — fine,
     provided every waiter carries its own deadline regardless; the viewer may never
     converge (stale views observed 20+ s).
   - Dirty-marking sources (asymmetric rule — this is what prevents the
     notify→poll→dirty→poll loop):
     a) our own mutating calls (create/save/delete/modify/set_running/rename) →
        mark STALE immediately (optimistic invalidation);
     b) broadcast notifications for the tracked object (object.update/publish/
        unpublish) → mark STALE. POLL RESPONSES NEVER MARK DIRTY — only broadcasts
        do — so each real change produces finitely many re-triggers and the loop
        converges. Coalesce: dirty is a plain bool consumed at poll completion; a
        mark during a poll buys exactly one more pass;
     c) connection loss/reconnect (MCP mode) → STALE.
   - Granularity: per-PRIM (whole object), not per-item — the invalidation unit must
     match the fetch unit, and the only read primitive known is whole-prim
     (object.list returns full trees; no named-item-collection fetch observed).
     Per-item tracking stays useful at the WAITER layer (predicate "item X has
     running==false"). The full spec read (NOTES, archived F15) found no finer-
     grained read method — object.list is the only inventory read primitive.
     Delta-applying object.update payloads instead of re-fetching is NOT possible
     today anyway: the spec's delta sub-protocol (changes.inventory.added/removed/
     modified/content_changed/running_changed) is specified but "not currently
     emitted by the viewer" — only five full-replacement shapes are sent. Re-fetch
     on dirty is the only viable base design.
   - Driver-agnostic: CLI mode = engine lives for ONE command, polls until its
     predicate is satisfied or the reconciliation budget (default 2× call timeout)
     expires; MCP mode (F17) = one long-lived engine per tracked prim, broadcasts
     keep it warm, polls on dirty with debounce. Same library, different lifetime —
     so the engine must not assume persistence.
   - Rough public surface: ObjectInventory(session, object_ref); .snapshot() (may be
     STALE; caller decides); .wait_until(predicate, budget) → bool — the primitive
     that put's create-race workaround, scripts --wait-update, and objects explore
     all reduce to; explicit .invalidate() hooks for mutating calls.
   - _is_sim_rename is absorbed here as the predicate helper "which new-looking item
     did WE just create", renamed per F16 (e.g. _plausibly_created_item).
   Unit-test with FakeViewer: create-race error, wrong-id response (F7), stale
   snapshot, duplicate broadcasts, mark-during-poll coalescing. put() becomes a thin
   composition of named steps over this engine.
5. Rebuild scripts start|stop --wait-update on the primitives: POLL inventory
   (bounded) instead of waiting for an object.update that never arrives for
   set_running (observed live; old F1 remainder). Spec context: set_running/reset
   responses are documented as "success means dispatched, not applied" with
   confirmation arriving only "if it arrives" as object.update — the hedge is real;
   polling is the intended client behaviour. Fixes the misleading "now: running
   (no update observed)" output; keep the notification as an early-exit fast path.
   objects explore likewise.
6. Live-test expansion per F8–F12 as those land.

Supersedes/absorbs: old F5 knob gaps, F13 (step 2), F16 (step 4), the --wait-update
half of old F1 (step 5). F7's client-side guards move into find_new_item (step 4);
F7's investigation steps are unchanged.
DOC UPDATES ON COMPLETION: ARCHITECTURE.md lifecycle section + "Stateless CLI"
design rule (forward pointers already added there); TASKS.md Phase 3
`scripts start|stop` line — its "--wait-update to confirm via object.update"
description is superseded by step 5's poll-based behaviour.

### F3. Verify "Explore in IDE" multi-select behaviour (disputed claim, 2026-11-19)
An earlier draft bug-report item (#8, NOT posted) claimed that clicking Explore in
IDE with several prims selected silently processes only the first root. Tapple
disputes having done that — and she is right: the source shows the button is
DISABLED for multi-root selections (`new_button_enabled = editable && all_volume
&& (single_root || (object_count == 1))` in llpanelcontents.cpp, both viewers),
so the click could never have happened. The log evidence fits her actual actions:
two launch attempts per viewer ≈ one click per prim.
Still worth verifying with tapple present (low priority):
1. Select 2 prims → confirm the button is greyed out (expected).
2. Select a single CHILD prim of a linkset → the handler uses
   `getFirstRootObject()`, so it should publish the whole root linkset; confirm
   that's what happens and whether that's desirable UX.

### F8. `scripts reset` never exercised live (remainder of old F1)
Old F1 is split: start/stop verified 2026-11-19 (NOTES.md "F1 test result");
`--wait-update` moved to F5; this is what's left. `slsync scripts reset <item>`
dispatches object.script.reset — never run live.
Safe test on a scratch object: timer script with llOwnerSay in state_entry → reset
while running → tail should show the state_entry message again (re-initialised).
Edge case: reset on a STOPPED script — does it start it, no-op, or error?
DOC UPDATE ON COMPLETION: TASKS.md Phase 3 `scripts reset` line (currently
"Same caveat") — mark live-verified with date.

### F9. `commands run viewer.script.recompile_all` untested (split of old F2)
Params: --object-id (required), --target luau|lsl2|mono|auto (required).
Recompiles ALL scripts in the object — changes VM/running state; scratch object only.
The `commands run` machinery itself (param parsing, capability gate) is verified
via viewer.camera.focus 2026-11-19 (NOTES.md); untested here is the command's effect.
Test: scratch object with one LSL + one Luau script → recompile_all --target auto →
objects show (vm fields intact) + tail (scripts still run). Open question: behaviour
when one of the scripts has a compile error (interacts with F4 findings).
DOC UPDATE ON COMPLETION (applies to F9–F12): TASKS.md Phase 4 `commands run`
line — "Implemented; not exercised live ... See FOLLOWUPS.md F2" grows stale as
each command is verified; update it per command.

### F10. `commands run viewer.script.reset_all` untested (split of old F2)
Params: --object-id (required). Resets ALL scripts in the object — affects running
state; scratch object only, tapple present.
Test: two running timer scripts (llOwnerSay in state_entry) → reset_all → tail shows
both re-initialise. Compare with per-item `scripts reset` (F8) — effects should match.

### F11. `commands run viewer.object.save_back_to_contents` untested (split of old F2)
Params: --object-id (required). Writes the in-world object back to its SOURCE
inventory contents — potentially destructive for non-scratch objects; never run.
Negative test first (safe): all scratch objects report "save-back available: no" →
call it on one, expect a clean error. Positive test needs an object with save-back
enabled — tapple decides whether to create/expose one.

### F12. `commands run viewer.teleport` untested (split of old F2)
Params: --object-id (required). Moves tapple's avatar — disruptive; only with her
present and in-world attention. Start same-region (scratch prim) to keep it quick;
cross-region later if wanted. Verify arrival in-world + no viewer error.

### F13. Raw Python traceback when the viewer is not reachable (observed 2026-11-19, twice)
Any command against a down viewer (e.g. `slsync status`, `slsync commands list`)
prints a full ConnectionRefusedError traceback instead of a friendly error. Root
cause: `_execute` in cli.py only catches ViewerError; the OSError from
websockets.connect escapes. Fix: catch connection failures and print e.g.
"error: cannot connect to ws://127.0.0.1:9020 — is the viewer running with the
editor server enabled?" (exit 1). Observed twice 2026-11-19: start of session
(status on both ports) and tapple re-checking `commands list`. Small fix in
_execute and/or ViewerSession.connect.

### F14. Evaluate whether the `slsync commands` group is necessary (raised 2026-11-19)
tapple: it looks like an unnecessary extra layer — the viewer's command.execute
commands could perhaps just live in a different help section of top-level `slsync`
("things unrelated to moving inventory") instead of a subcommand group with its own
list/run verbs. Evaluate: discoverability via --help, agent ergonomics (Phase 5
decision: CLI only, good --help matters), and whether the generic
`run --param k=v` interface earns its keep vs typed shortcuts (old Phase 4 optional
item). Decide BEFORE Phase 6 help-text polish so we don't polish a layer we remove.
DOC UPDATE IF THE GROUP IS REMOVED/RESHAPED: TASKS.md Phase 4 items (commands
list/run, optional typed shortcuts) and the Phase 6 help-text scope;
ARCHITECTURE.md is unaffected (its Layout description is command-agnostic).

Related (tapple): `commands list` shouldn't need a network connection at all — it
could be a static help page. Counter-consideration: today it calls the live
command.list method, which reports what THIS viewer build supports (command set is
feature-gated, ARCHITECTURE.md gotcha #8); a static page risks drift. Candidate
resolution: static list from the spec's documented command set (spec-vs-surface
note in NOTES.md) for discovery, with the live check available if/when it still earns its place.

### F16. Revisit `_is_sim_rename` in cli.py (tapple review, 2026-11-19)
Three objections to the helper used by put's create-race workaround:
1. Name is unclear.
2. It incompletely encapsulates SL's duplicate-rename logic: the sim increments
   the trailing number until it finds a free slot ("name", "name 1", "name 2"...);
   the helper only RECOGNISES "name <digits>", doesn't model/predict assignment —
   and its name/docstring overstate that it does.
3. Is it needed at all? Alternatives: trust the viewer's create response, or
   verify with a plain inventory diff.
Context for whoever picks this up (why it exists): trusting the response is
empirically unsafe on current viewers — both failure modes were observed live:
the "Item was not found in updated inventory" race AND F7's response naming a
pre-existing unrelated item. A plain ID diff is also unsafe: when the viewer's
inventory snapshot is stale/empty, pre-existing items appear as "new" and the old
code overwrote one (observed live). The name pattern is currently the only
remaining discriminator for "which new-looking item did WE just create". Possible
resolutions: rename to something like `_plausibly_created_item` with a docstring
saying it's a recognizer, not a model of sim naming; or rework the workaround to
search by name instead of diffing ids (caveat: if the snapshot was stale, an
existing "name N" and our genuinely new "name M" can BOTH be candidates — the ID
diff is what excludes the former when it's fresh); or drop the workaround entirely
if F7 gets fixed viewer-side.
RESOLUTION ADOPTED: F5 step 4 (extract into find_new_item + rename + FakeViewer unit
tests). This item closes when that lands.

### F17. MCP server question — mechanism half resolved by F5 step 4 (tapple, 2026-11-19)
Original framing: snapshotting/diffing prim inventory would work better inside an
MCP server because the snapshot could stay cached and kept fresh by a persistent
connection instead of being recomputed per CLI invocation. **The mechanism half is
now designed**: F5 step 4's object_inventory.py IS that cached, dirty-tracked,
continuously-updatable per-prim snapshot — driver-agnostic (CLI mode: lives one
command; MCP mode: long-lived per prim). No separate snapshot design work remains
here.
What REMAINS for F17 is purely the decision: do we build an MCP server at all, as a
long-lived DRIVER of that engine plus multi-agent coordination/audit and full
request/response visibility on one connection (NOTES pro-MCP argument)? That is
Decision #2 (CLI-only) territory. BLOCKED ON: tapple thinking it through.
DOC UPDATE IF PURSUED TO COMPLETION: ARCHITECTURE.md Layout note ("mcp_server.py
was planned, descoped 2026-11-18") + the "Stateless CLI" design rule; TASKS.md
Phase 5 decision line ("CLI only, no MCP server").

Protocol fact reinforcing this (2026-11-19): the protocol has NO stream-level
sequence numbers — only per-call JSON-RPC ids (ours are ints; the viewer's own
requests carry string ids like "rpc_1083", a server-side counter), and
NOTIFICATIONS CARRY NO ID AT ALL (session.ok, object.update, runtime.debug,
script.compiled are bare method+params). Consequences: no way to correlate a
broadcast update with the call that caused it (root of the --wait-update problem;
F5 step 5 polls instead), and no "events since last seq" primitive exists. If a
future protocol revision exposed sequence numbers on notifications, that would make
the MCP cached-snapshot/buffer design dramatically stronger — likely the real reason
it feels right.

### F18. `put -` stdin mode advertised but broken (noted 2026-11-19)
`slsync put`'s help/docstring claims "'-' reads stdin", but the click argument is
click.Path(exists=True), which rejects "-" with "Path '-' does not exist" (hit
live). Either fix (special-case "-" before path validation) or remove the claim
from help/docstring. DOC UPDATE EITHER WAY: TASKS.md Phase 2 put item documents
"`-` = stdin" — keep it if fixed, strike it if the claim is removed. Small.

