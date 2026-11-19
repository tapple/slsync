# slsync — Follow-ups

Known issues and verification debts that are NOT part of the phased work in
TASKS.md. When an item is resolved, move it (with outcome) into NOTES.md and
remove it from here.

## Open

### F1. `slsync scripts start|stop|reset` never exercised live (debt since Phase 3)
Implemented but untested — they toggle real scripts, so only with tapple present.
Suggested flow: put a trivial llOwnerSay scratch script → `scripts start/stop`
→ watch the tail output stop/resume → clean up.

### F2. `slsync commands run` never exercised live (debt since Phase 4)
Implemented but untested — teleport/focus move tapple's avatar; only with her
present and in-world attention. Check `commands list` first for a harmless
command to start with.

### F3. Manual `slsync tail` showed no script output from Pippin's published prim (2026-11-19 evening)
Tapple ran `slsync tail` herself; nothing printed from the scripts on Pippin's
published prims. Hypotheses, check in order:
1. **Chat ownership routing** (see NOTES.md live-testing findings): llOwnerSay /
   DEBUG_CHANNEL output from a prim is relayed ONLY by the viewer whose avatar
   receives the chat — for Pippin's prims that is PippinGao's viewer (official,
   9021). Tailing 9020 (Alchemy/tapple) would see nothing from those prims.
2. **The scripts are quiet**: the Key/uuid-to-Hovertext script updates its
   hovertext once and then stays silent — no new output = nothing to print.
Verification: fresh terminal, `uv run slsync --url ws://127.0.0.1:9021 tail`
(the OFFICIAL viewer!), then either reset the Key/uuid script
(`slsync scripts reset 689a7470-5030-b7f6-324b-36a90c4a436b:6bff6cc2-712a-e26d-
efd7-165ec82a9b92` — item id as of 2026-11-19, re-check with `items list`) or
put a scratch script that llOwnerSays on a timer — expect lines immediately.
If 9021 stays silent too → real notification-routing bug; viewer logs are the
next stop.
Open question: which port did tapple tail? (record the answer when she replies)
