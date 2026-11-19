# slsync — Follow-ups

Known issues and verification debts that are NOT part of the phased work in
TASKS.md. When an item is resolved, move it (with outcome) into NOTES.md and
remove it from here.

## Open

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
Implemented but untested — they toggle real scripts, so only with tapple present.
Suggested flow: put a trivial llOwnerSay scratch script → `scripts start/stop`
→ watch the tail output stop/resume → clean up.

### F2. `slsync commands run` never exercised live (debt since Phase 4)
Implemented but untested — teleport/focus move tapple's avatar; only with her
present and in-world attention. Check `commands list` first for a harmless
command to start with.

