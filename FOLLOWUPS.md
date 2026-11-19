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

