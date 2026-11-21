#!/usr/bin/env bash
# Standalone reproduction of compile-error behaviour in the viewer's editor
# WebSocket server. For attachment to the bug report:
#   https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket
#
# Usage: tools/repro_compile_errors.sh [URL]
#   URL positional, or the URL environment variable, e.g. either of:
#     ./tools/repro_compile_errors.sh ws://127.0.0.1:9021
#     URL=ws://127.0.0.1:9021 ./tools/repro_compile_errors.sh
#   Defaults to ws://127.0.0.1:9020 (Alchemy). Requires one explored object
#   named 'Object' on that viewer (override with SLSYNC_LIVE_OBJECT).
#   Objects are addressed by NAME, not UUID.
#
# All scripts are inline; created items get unique names and are deleted at
# the end. Each case is bounded by --save-timeout 30, so a viewer that hangs
# on failed LSL compiles adds at most ~30 s per such case.
#
# Expected behaviour per spec (external-editor-json-rpc.md): compile
# diagnostics come back INLINE in the object.content.save response. Cases
# where the save call gets no response at all are marked DEVIATION.
#
# Reliability notes (repo FOLLOWUPS.md F5): the viewer's local inventory
# views and broadcast notifications are unreliable. Therefore:
#   - a settle delay (REPRO_SETTLE_DELAY, default 5 s) is inserted between
#     cases so the inventory view can stabilise after each create+save;
#   - every verdict is based solely on request/response (get-query) results:
#     the content.save response and object.list re-reads. Broadcast
#     notifications (object.update etc.) are NEVER consumed by this script.

set -uo pipefail

URL="${1:-${URL:-ws://127.0.0.1:9020}}"
OBJECT_NAME="${SLSYNC_LIVE_OBJECT:-Object}"
SETTLE_DELAY="${REPRO_SETTLE_DELAY:-5}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d)"

slsync() { uv run --project "$REPO_ROOT" slsync --url "$URL" "$@"; }

# Short prefix: the sim TRUNCATES long item names (observed 2026-11-21: a
# 69-char name came back 63 chars, which breaks any exact-name lookup).
# Keep item names = $PREFIX-namebase well under the limit (~45 chars).
PREFIX="repro-$(date -u +%H%M%S)-$$"
CREATED_NAMES=()

# Delete by name with retries: the viewer's inventory view lags after
# mutations, so delete-by-name can fail ("Item not found in prim inventory",
# -32602, observed 2026-11-21 on both viewers) even though the item exists.
# Verify with a get query after each attempt.
cleanup_items() {
    local n attempt
    for n in "${CREATED_NAMES[@]}"; do
        for attempt in 1 2 3 4 5; do
            slsync items delete "$OBJECT_NAME/$n" -y >/dev/null 2>&1
            if ! slsync --json objects list 2>/dev/null | grep -qF "$n"; then
                break
            fi
            sleep 2
        done
        if slsync --json objects list 2>/dev/null | grep -qF "$n"; then
            echo "WARNING: could not delete $OBJECT_NAME/$n (stale inventory view?) — delete it manually"
        fi
    done
}
trap 'rm -rf "$WORKDIR"; cleanup_items' EXIT

echo "=============================================="
echo "Compile-error reproduction — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Target: $URL   Object (by name): $OBJECT_NAME   Settle delay: ${SETTLE_DELAY}s"
echo "=============================================="
echo ""

# Precondition: the object must be explored (addressed by NAME)
if ! slsync --json objects list 2>/dev/null | grep -q "\"object_name\": \"$OBJECT_NAME\""; then
    echo "ERROR: no explored object named $OBJECT_NAME on $URL."
    echo "Explore a scratch prim in the viewer first, or set SLSYNC_LIVE_OBJECT."
    exit 2
fi

# test_case <label> <expect:ok|fail> <ext> <namebase> (script content on stdin)
test_case() {
    local label="$1" expect="$2" ext="$3" namebase="$4"
    local name="${PREFIX}-${namebase}"
    local file="$WORKDIR/${name}.${ext}"
    cat > "$file"

    # Settle delay between cases (skipped before the first): lets the
    # viewer's inventory view stabilise after the previous create+save.
    if [[ ${#CREATED_NAMES[@]} -gt 0 ]]; then
        sleep "$SETTLE_DELAY"
    fi

    echo "--- $label ---"
    local out rc
    out="$(slsync put "$file" "$OBJECT_NAME" "$name" --save-timeout 30 2>&1)"
    rc=$?
    CREATED_NAMES+=("$name")
    echo "$out"

    # Get-query post-check (informational only): the item should be visible
    # in object.list. The view lags after mutations (documented stale/empty
    # windows), so retry briefly. A miss is NOT a verdict factor — the
    # verdict comes from the save response above.
    local visible=""
    local _i
    for _i in 1 2 3; do
        if slsync --json objects list 2>/dev/null | grep -qF "$name"; then
            visible=1
            break
        fi
        sleep 2
    done
    if [[ -n "$visible" ]]; then
        echo ">>> post-check (get query): item visible in object.list"
    else
        echo ">>> post-check (get query): item NOT visible in object.list after ~6s (stale view; not a verdict factor)"
    fi

    if [[ "$expect" == "ok" ]]; then
        if [[ $rc -eq 0 && "$out" == *"compiled: yes"* ]]; then
            echo ">>> CONFORMS (compiled: yes)"
        else
            echo ">>> DEVIATION (expected compiled: yes, exit 0; got rc=$rc)"
        fi
    else
        if [[ "$out" == *"compiled: no"* ]]; then
            echo ">>> CONFORMS (inline diagnostics in save response)"
        elif [[ "$out" == *"did not confirm compilation"* ]]; then
            echo ">>> DEVIATION (save call got NO response; slsync fell back to read-back)"
        else
            echo ">>> UNEXPECTED (rc=$rc; neither known outcome)"
        fi
    fi
    echo ""
}

test_case "Good LSL script (create)" ok lsl good-lsl <<'EOF'
default {
    state_entry() {
        llOwnerSay("ok");
    }
}
EOF

test_case "Bad LSL syntax — missing closing brace" fail lsl bad-lsl-syntax <<'EOF'
default {
    state_entry() {
        llOwnerSay("hi");
EOF

test_case "Bad LSL semantic — undefined variable" fail lsl bad-lsl-semantic <<'EOF'
default {
    state_entry() {
        undefined_var = 5;
        llOwnerSay("test");
    }
}
EOF

test_case "Good Luau script (create)" ok luau good-luau <<'EOF'
print("ok")
EOF

test_case "Bad Luau syntax — missing closing paren" fail luau bad-luau-syntax <<'EOF'
function main()
    print("hi"
end
main()
EOF

echo "=============================================="
echo "Done. Spec: diagnostics come back inline in the"
echo "object.content.save response for all failures."
echo "DEVIATION lines are report-worthy behaviour."
echo "Items named $PREFIX-* were deleted on exit."
echo "=============================================="
