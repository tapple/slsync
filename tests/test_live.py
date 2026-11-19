"""Live integration tests against a running viewer.

NOT a hard gate: every test skips when no viewer is reachable at
SLSYNC_LIVE_URL (default ws://127.0.0.1:9020). They exercise the real CLI
surface (including name-based object addressing) against the scratch object
named SLSYNC_LIVE_OBJECT (default 'Object'; see NOTES.md Decisions #4) and
delete their items afterwards.

Run explicitly with:  uv run pytest -m live
Point at another viewer:  SLSYNC_LIVE_URL=ws://127.0.0.1:9021 uv run pytest -m live
"""

from __future__ import annotations

import json
import os
import socket
import uuid

import pytest
from click.testing import CliRunner, Result

from slsync.cli import cli

pytestmark = pytest.mark.live

LIVE_URL = os.environ.get("SLSYNC_LIVE_URL", "ws://127.0.0.1:9020")
OBJECT_NAME = os.environ.get("SLSYNC_LIVE_OBJECT", "Object")

# Bounded so a viewer that hangs on failed compiles (see bug-report notes)
# does not make the suite wait the full default save timeout.
SAVE_TIMEOUT_ARG = ["--save-timeout", "30"]

GOOD_LSL = 'default {\n    state_entry() {\n        llOwnerSay("ok");\n    }\n}\n'
BAD_SYNTAX_LSL = 'default {\n    state_entry() {\n        llOwnerSay("hi");\n'  # missing brace
BAD_SYNTAX_LUAU = 'function main()\n    print("hi"\nend\nmain()\n'


def _reachable(url: str) -> bool:
    hostport = url.split("//", 1)[1].split("/", 1)[0]
    host, _, port = hostport.rpartition(":")
    try:
        with socket.create_connection((host or "127.0.0.1", int(port or 80)), timeout=2.0):
            return True
    except OSError:
        return False


def _require_object() -> None:
    """Skip (not fail) when the viewer is down or the scratch object isn't explored."""
    if not _reachable(LIVE_URL):
        pytest.skip(f"no viewer reachable at {LIVE_URL}")
    r = CliRunner().invoke(cli, ["--url", LIVE_URL, "--json", "objects", "list"])
    if r.exit_code != 0:
        pytest.skip(f"objects list failed at {LIVE_URL}: {r.output.strip()}")
    objs = json.loads(r.output)
    if not any(o.get("object_name") == OBJECT_NAME for o in objs):
        pytest.skip(f"object {OBJECT_NAME!r} not explored at {LIVE_URL}")


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def _put(tmp_path, content: str, ext: str, name: str, *extra: str) -> Result:
    f = tmp_path / f"{name}.{ext}"
    f.write_text(content, encoding="utf-8")
    return CliRunner().invoke(
        cli, ["--url", LIVE_URL, "put", str(f), OBJECT_NAME, name, *extra]
    )


def _cleanup(name: str) -> None:
    CliRunner().invoke(cli, ["--url", LIVE_URL, "items", "delete", f"{OBJECT_NAME}/{name}", "-y"])


def test_put_good_lsl_compiles(tmp_path):
    _require_object()
    name = _unique("live-good-lsl")
    try:
        r = _put(tmp_path, GOOD_LSL, "lsl", name)
        assert r.exit_code == 0, r.output
        assert "compiled: yes" in r.output
    finally:
        _cleanup(name)


def test_put_bad_lsl_reports_compile_failure(tmp_path):
    """Bad LSL must surface a failure, one of two known viewer behaviours:

    - inline diagnostics in the save response ('compiled: no' + error,
      exit 1), or
    - no response at all; slsync then verifies by read-back and reports
      'viewer did not confirm compilation' (exit 0 — upload itself succeeded).
    """
    _require_object()
    name = _unique("live-bad-lsl")
    try:
        r = _put(tmp_path, BAD_SYNTAX_LSL, "lsl", name, *SAVE_TIMEOUT_ARG)
        out = r.output
        if "compiled: no" in out:
            assert r.exit_code == 1, out
        else:
            assert "did not confirm compilation" in out, (
                f"neither known failure mode observed:\n{out}"
            )
    finally:
        _cleanup(name)


def test_put_bad_luau_reports_compile_failure(tmp_path):
    """Bad Luau returns inline diagnostics on both viewers tested so far."""
    _require_object()
    name = _unique("live-bad-luau")
    try:
        r = _put(tmp_path, BAD_SYNTAX_LUAU, "luau", name, *SAVE_TIMEOUT_ARG)
        assert r.exit_code == 1, r.output
        assert "compiled: no" in r.output, r.output
    finally:
        _cleanup(name)
