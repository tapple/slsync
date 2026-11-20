# slsync — Follow-ups

Known issues and verification debts that are NOT part of the phased work in
TASKS.md. When an item is resolved, move it (with outcome) into NOTES.md and
remove it from here.

## Open

### F4. Compile-error reporting — finish evidence gathering for bug-report item #4 (2026-11-19)
Context: tapple is updating the POSTED bug report; the master copy is on the web
(https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket,
fetchable via curl — do not trust local copies). Item #4 ("Compile errors return
no result") needs rewriting with today's A/B findings. All code changes from this
session are UNCOMMITTED — tapple reviews notes + `git diff` before any commit.
Announce every live probe.

**Environment:** official viewer 26.5.0 on ws://127.0.0.1:9021 with scratch
object "Object" [260d253b-6f65-f110-ac0f-9e70699fad60] explored (leftover test
items inside — clean up when done: `slsync --url ws://127.0.0.1:9021 items
delete Object/<name> -y`, inventory view is flaky, retry + verify via objects
show). Alchemy's scratch df7f06ef was DELETED in-world ~19:00Z — tapple
re-exposes one on 9020 or F4 runs against 9021 only. Uncommitted `put
--save-timeout` (see `git diff`) is used by the repro; live tests in
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
- `script.compiled` notification: never observed on either viewer — including a
  success case, but NOT yet proven with raw wire capture (step 2 below).

**Steps:**
1. Run `tools/repro_compile_errors.sh` against each available viewer (default
   9020; pass ws://127.0.0.1:9021 for official). It is written per tapple's spec
   (one viewer, object by NAME "Object", inline scripts, unique names,
   --save-timeout 30, CONFORMS/DEVIATION verdicts vs spec, self-cleanup) but has
   NOT been run live yet — verify it first.
2. Prove `script.compiled` absence with raw capture: one connection with
   on_raw_frame logging (pattern: tools/probe_create_wire.py), save a GOOD
   script, grep the log for "script.compiled". If absent on success too, report
   wording = "never observed", not "missing on failure".
3. **ASK TAPPLE (exit-code semantics):** put exits 0 when content is saved but
   compile state unknown (read-back path). Keep 0 vs exit non-zero so agents treat
   unconfirmed compiles as failures?
4. Rewrite NOTES.md bug-report item #4 text from the repro output + step 2 result.
   DO NOT post; tapple reviews and posts.

### F7. item.create returns a pre-existing item id — investigate (suspected viewer bug, official 26.5.0)
Context: separate from F4 (different RPC method); observed correlation with a
preceding HUNG bad-LSL save is an open question, not established causation.
Environment/cleanup: see F4. All code changes UNCOMMITTED; announce live probes.

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
  resolved ids are ignored. One theoretical hole to rule out with the wire scan:
  a notification carrying an `id` would be misdispatched as a response.
- Prior wire evidence: evidence/create-race-wire-20261119T2058Z.log — clean
  framing, single responses, no dupes/reordering in the documented race; also
  shows the viewer uses STRING ids ("rpc_1083") for its own requests vs our ints.
- Related known issue: the systematic "Item was not found in updated inventory"
  create race — likely the same unreliable post-creation inventory check failing
  in the other direction (returns an item instead of erroring).

**Steps:**
1. `uv run pytest -q` → all pass/skip; then `SLSYNC_LIVE_URL=ws://127.0.0.1:9021
   uv run pytest -m live -v` — the bad-luau test previously failed only after a
   hung bad-LSL save in the same process; with the uncommitted pre-create guard it
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
4. Keep the uncommitted slsync guards (`git diff`): create-race workaround now
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

### F5. Timeouts & wait semantics are inconsistent (noted 2026-11-19)
Three knobs cover disjoint scopes: `--connect-timeout` (connect+handshake),
`--timeout` (all other calls), `put --save-timeout` (create+save inside put). Gaps:
`slsync get` and the read-back in `_save_with_verify` use a hardcoded GET_TIMEOUT=45 s
ignoring `--timeout`; standalone `items create` times its item.create with `--timeout`
while put's create path uses `--save-timeout`. Candidate fix: effective timeout =
max(--timeout, per-op floor) so one global knob scales everything. Small; pairs
naturally with the Phase 6 help-text polish in TASKS.md.

Also here (remainder of old F1): **`scripts start|stop --wait-update` is broken** —
it waits up to 15 s (HARDCODED, not a knob) for an `object.update` notification,
but none ever arrives for set_running operations (observed live on Alchemy), then
re-fetches inventory which shows STALE state — so the flag currently reports
misleading output like "now: running (no update observed)" after a stop. Open
question: does the viewer send `object.update` for running-state changes at all?
If not, either fix the client to poll inventory with retries instead of waiting
for a notification that never comes, or add a bug-report item (ARCHITECTURE.md
gotcha #4 says confirmation arrives as object.update).

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

### F9. `commands run viewer.script.recompile_all` untested (split of old F2)
Params: --object-id (required), --target luau|lsl2|mono|auto (required).
Recompiles ALL scripts in the object — changes VM/running state; scratch object only.
The `commands run` machinery itself (param parsing, capability gate) is verified
via viewer.camera.focus 2026-11-19 (NOTES.md); untested here is the command's effect.
Test: scratch object with one LSL + one Luau script → recompile_all --target auto →
objects show (vm fields intact) + tail (scripts still run). Open question: behaviour
when one of the scripts has a compile error (interacts with F4 findings).

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

Related (tapple): `commands list` shouldn't need a network connection at all — it
could be a static help page. Counter-consideration: today it calls the live
command.list method, which reports what THIS viewer build supports (command set is
feature-gated, ARCHITECTURE.md gotcha #8); a static page risks drift. Candidate
resolution: static list from the spec's documented command set (ties into F15) for
discovery, with the live check available if/when it still earns its place.

### F15. Review protocol spec for features not exposed in slsync (raised 2026-11-19)
Unknown: does external-editor-json-rpc.md define more commands than the 5 that
command.list returned at runtime (viewer.script.recompile_all, viewer.script.reset_all,
viewer.object.save_back_to_contents, viewer.camera.focus, viewer.teleport)? Walk the
spec method by method and diff against slsync's surface (system.*, object.*,
script.*, command.*); record gaps as tasks or explicit non-goals in ARCHITECTURE.md.
Note the spec may lag the implementation in BOTH directions: system.getStats is NOT
in the public spec (undocumented; see NOTES B4).

### F16. Revisit `_is_sim_rename` in cli.py (tapple review, 2026-11-19)
Three objections to the uncommitted helper used by put's create-race workaround:
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

### F17. MCP-cached inventory snapshots (tapple, 2026-11-19 — she wants to think on this first)
New angle for the parked MCP question (NOTES.md "Design notes: tail for agents" +
Decision #2 CLI-only; ARCHITECTURE.md descope note): snapshotting and diffing prim
inventory would work better inside an MCP server, because the snapshot wouldn't
need to be recomputed on demand per CLI invocation — it could stay cached and kept
fresh by the persistent connection. This session's F7/F16 stale-snapshot problems
are exactly the pain a cached, continuously-updated snapshot would remove. Good idea
in theory; needs followup and review before any design work. BLOCKED ON: tapple
thinking it through.

### F18. `put -` stdin mode advertised but broken (noted 2026-11-19)
`slsync put`'s help/docstring claims "'-' reads stdin", but the click argument is
click.Path(exists=True), which rejects "-" with "Path '-' does not exist" (hit
live). Either fix (special-case "-" before path validation) or remove the claim
from help/docstring. Small.

