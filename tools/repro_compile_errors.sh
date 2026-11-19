#!/usr/bin/env bash
# Standalone reproduction of compile-error behaviour in the viewer's editor
# WebSocket server. For attachment to the bug report:
#   https://feedback.secondlife.com/slua-alpha/p/bugs-with-the-lua-plugin-websocket
#
# Usage: tests/repro_compile_errors.sh [URL]
#   URL defaults to ws://127.0.0.1:9020 (Alchemy); use ws://127.0.0.1:9021 for
#   the official viewer. Requires one explored object named 'Object' on that
#   viewer (override with SLSYNC_LIVE_OBJECT). Objects are addressed by NAME,
#   not UUID.
#
# All scripts are inline; created items get unique names and are deleted at
# the end. Each case is bounded by --save-timeout 30, so a viewer that hangs
# on failed LSL compiles adds at most ~30 s per such case.
#
# Expected behaviour per spec (external-editor-json-rpc.md): compile
# diagnostics come back INLINE in the object.content.save response. Cases
# where the save call gets no response at all are marked DEVIATION.

set -uo pipefail

URL="${1:-ws://127.0.0.1:9020}"
OBJECT_NAME="${SLSYNC_LIVE_OBJECT:-Object}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="$(mktemp -d)"

slsync() { uv run --project "$REPO_ROOT" slsync --url "$URL" "$@"; }

PREFIX="repro-$(date -u +%Y%m%d-%H%M%S)-$$"
CREATED_NAMES=()

cleanup_items() {
    for n in "${CREATED_NAMES[@]}"; do
        slsync items delete "$OBJECT_NAME/$n" -y >/dev/null 2>&1 || true
    done
}
trap 'rm -rf "$WORKDIR"; cleanup_items' EXIT

echo "=============================================="
echo "Compile-error reproduction — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Target: $URL   Object (by name): $OBJECT_NAME"
echo "=============================================="
echo ""

# Precondition: the object must be explored (addressed by NAME)
if ! slsync --json objects list 2>/dev/null | grep -q "\"object_name\": \"$OBJECT_NAME\""; then
    echo "ERROR: no explored object named $OBJECT_NAME on $URL."
    echo "Explore a scratch prim in the viewer first, or set SLSYNC_LIVE_OBJECT."
    exit 2
fi

# test_case <label> <expect:ok|fail> <ext> (script content on stdin)
test_case() {
    local label="$1" expect="$2" ext="$3"
    local name="${PREFIX}-$(echo "$label" | tr ' —' '--' | tr -cd 'a-zA-Z0-9-')"
    local file="$WORKDIR/${name}.${ext}"
    cat > "$file"

    echo "--- $label ---"
    local out rc
    out="$(slsync put "$file" "$OBJECT_NAME" "$name" --save-timeout 30 2>&1)"
    rc=$?
    CREATED_NAMES+=("$name")
    echo "$out"

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

test_case "Good LSL script (create)" ok lsl <<'EOF'
default {
    state_entry() {
        llOwnerSay("ok");
    }
}
EOF

test_case "Bad LSL syntax — missing closing brace" fail lsl <<'EOF'
default {
    state_entry() {
        llOwnerSay("hi");
EOF

test_case "Bad LSL semantic — undefined variable" fail lsl <<'EOF'
default {
    state_entry() {
        undefined_var = 5;
        llOwnerSay("test");
    }
}
EOF

test_case "Good Luau script (create)" ok luau <<'EOF'
print("ok")
EOF

test_case "Bad Luau syntax — missing closing paren" fail luau <<'EOF'
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
