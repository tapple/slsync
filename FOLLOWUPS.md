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

### F5. Timeout knobs are inconsistent (noted 2026-11-19, from --save-timeout review)
Three knobs cover disjoint scopes: `--connect-timeout` (connect+handshake),
`--timeout` (all other calls), `put --save-timeout` (create+save inside put). Gaps:
`slsync get` and the read-back in `_save_with_verify` use a hardcoded GET_TIMEOUT=45 s
ignoring `--timeout`; standalone `items create` times its item.create with `--timeout`
while put's create path uses `--save-timeout`. Candidate fix: effective timeout =
max(--timeout, per-op floor) so one global knob scales everything. Small; pairs
naturally with the Phase 6 help-text polish in TASKS.md.

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

### F1. `slsync scripts start|stop|reset` never exercised live (debt since Phase 3)
**RESOLVED 2026-11-19**: Start/stop WORK — script output starts/stops via tail.
BUT: `--wait-update` does NOT work (no `object.update` notification arrives).
Inventory re-fetch also unreliable. Verified with a simple llOwnerSay timer script.
See NOTES.md for details.

### F2. `slsync commands run` never exercised live (debt since Phase 4)
**RESOLVED 2026-11-19**: Tested `viewer.camera.focus` — works fine, camera zooms
to the target object. Teleport and other disruptive commands NOT tested.

