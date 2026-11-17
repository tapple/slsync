"""Tests for ViewerSession against a fake in-process viewer WebSocket server."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from contextlib import asynccontextmanager

import anyio
import pytest
from websockets.asyncio.server import serve

from ridercli.session import ViewerRPCError, ViewerSession


class FakeViewer:
    """Speaks just enough of the editor protocol to exercise ViewerSession."""

    def __init__(self) -> None:
        self.received: list[dict] = []
        self.challenge_file: str | None = None
        self.challenge_uuid = str(uuid.uuid4())
        self.handshake_result: dict | None = None  # our response to session.handshake
        self.client_call_responses: dict[int, dict] = {}
        self.results: dict[str, object] = {}  # method -> result override
        self.errors: dict[str, dict] = {}  # method -> error override
        self.hang: set[str] = set()  # methods to never answer (timeout tests)
        self.notifications_after_ok: list[tuple[str, dict | None]] = []
        self.call_client_after_ok: tuple[str, dict] | None = None

    async def handler(self, ws) -> None:
        fd, path = tempfile.mkstemp(prefix="sl_script_challenge_test_")
        with os.fdopen(fd, "w") as f:
            f.write(self.challenge_uuid)
        self.challenge_file = path
        try:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "session.handshake",
                        "params": {
                            "server_version": "1.0.0",
                            "protocol_version": "1.0",
                            "viewer_name": "FakeViewer",
                            "viewer_version": "9.9.9",
                            "agent_id": str(uuid.uuid4()),
                            "agent_name": "Testy McTestface",
                            "challenge": path,
                            "languages": ["lsl", "luau"],
                            "syntax_id": str(uuid.uuid4()),
                            "features": {"commands": True, "live_sync": True},
                        },
                    }
                )
            )
            async for raw in ws:
                msg = json.loads(raw)
                self.received.append(msg)
                await self._handle(ws, msg)
        finally:
            if self.challenge_file and os.path.exists(self.challenge_file):
                os.unlink(self.challenge_file)

    async def _handle(self, ws, msg: dict) -> None:
        mid = msg.get("id")
        method = msg.get("method")

        if "result" in msg or "error" in msg:
            # A response to one of our calls.
            if mid == 1 and "result" in msg:
                self.handshake_result = msg["result"]
                await ws.send(json.dumps({"jsonrpc": "2.0", "method": "session.ok"}))
                for m, p in self.notifications_after_ok:
                    payload = {"jsonrpc": "2.0", "method": m}
                    if p is not None:
                        payload["params"] = p
                    await ws.send(json.dumps(payload))
                if self.call_client_after_ok:
                    cm, cp = self.call_client_after_ok
                    await ws.send(
                        json.dumps(
                            {"jsonrpc": "2.0", "id": 999, "method": cm, "params": cp}
                        )
                    )
            elif mid == 999 and "result" in msg:
                self.client_call_responses[999] = msg
            return

        if method is None or method in ("session.disconnect",):
            return  # notification; nothing to do
        if method in self.hang:
            return  # deliberately never answer

        error = self.errors.get(method)
        if error is not None:
            await ws.send(json.dumps({"jsonrpc": "2.0", "id": mid, "error": error}))
            return

        if method == "system.ping":
            payload = {
                "pong": "pong",
                "timestamp": (msg.get("params") or {}).get("timestamp"),
                "server_time": 123,
            }
        elif method == "object.list":
            payload = {"objects": []}
        elif method in self.results:
            payload = self.results[method]
        else:
            await ws.send(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "error": {"code": -32601, "message": f"Method not found: {method}"},
                    }
                )
            )
            return
        await ws.send(json.dumps({"jsonrpc": "2.0", "id": mid, "result": payload}))


@asynccontextmanager
async def fake_viewer():
    fake = FakeViewer()
    server = await serve(fake.handler, "127.0.0.1", 0)
    try:
        yield fake, f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.anyio
async def test_handshake_and_challenge():
    async with fake_viewer() as (fake, url):
        async with ViewerSession(url) as s:
            info = s.handshake
            assert info is not None
            assert info.viewer_name == "FakeViewer"
            assert info.viewer_version == "9.9.9"
            assert info.agent_name == "Testy McTestface"
            assert info.features["commands"] is True

    assert fake.handshake_result is not None
    assert fake.handshake_result["client_name"] == "ridercli"
    assert fake.handshake_result["protocol_version"] == "1.0"
    assert fake.handshake_result["challenge_response"] == fake.challenge_uuid


@pytest.mark.anyio
async def test_call_roundtrip():
    async with fake_viewer() as (fake, url):
        async with ViewerSession(url) as s:
            ping = await s.call("system.ping", {"timestamp": 42})
            assert ping["pong"] == "pong"
            assert ping["timestamp"] == 42
            listing = await s.call("object.list")
            assert listing == {"objects": []}


@pytest.mark.anyio
async def test_error_mapping():
    async with fake_viewer() as (fake, url):
        fake.errors["object.request"] = {
            "code": -32602,
            "message": "Invalid params: No object_id specified",
        }
        async with ViewerSession(url) as s:
            with pytest.raises(ViewerRPCError) as ei:
                await s.call("object.request", {"object_id": ""})
            assert ei.value.code == -32602
            assert "No object_id" in ei.value.message


@pytest.mark.anyio
async def test_method_not_found():
    async with fake_viewer() as (fake, url):
        async with ViewerSession(url) as s:
            with pytest.raises(ViewerRPCError) as ei:
                await s.call("nope.nope")
            assert ei.value.code == -32601


@pytest.mark.anyio
async def test_call_timeout():
    async with fake_viewer() as (fake, url):
        fake.hang.add("system.status")
        async with ViewerSession(url) as s:
            with pytest.raises(ViewerRPCError) as ei:
                await s.call("system.status", timeout=0.5)
            assert ei.value.code == -32001


@pytest.mark.anyio
async def test_notifications_recorded_and_callback():
    async with fake_viewer() as (fake, url):
        fake.notifications_after_ok = [
            ("runtime.debug", {"object_id": "x" * 36, "message": "hello"}),
        ]
        seen: list[tuple[str, dict | None]] = []
        s = ViewerSession(url)
        s.on_notification = lambda m, p: seen.append((m, p))
        await s.connect()  # handler registered before the read loop starts
        try:
            await anyio.sleep(0.1)  # let the read loop drain post-ok traffic
            methods = [m for _, m, _ in s.notifications]
            assert "session.ok" in methods
            assert "runtime.debug" in methods
        finally:
            await s.close()
        assert ("runtime.debug", {"object_id": "x" * 36, "message": "hello"}) in seen


@pytest.mark.anyio
async def test_viewer_request_handler():
    async with fake_viewer() as (fake, url):
        fake.call_client_after_ok = (
            "command.execute",
            {"command": "editor.show_message", "params": {"message": "hi"}},
        )
        s = ViewerSession(url)
        s.on_request("command.execute", lambda params: {"success": True})
        await s.connect()  # handler registered before the read loop starts
        try:
            await anyio.sleep(0.1)
        finally:
            await s.close()
    assert 999 in fake.client_call_responses
    assert fake.client_call_responses[999]["result"] == {"success": True}


@pytest.mark.anyio
async def test_close_sends_disconnect():
    async with fake_viewer() as (fake, url):
        async with ViewerSession(url) as s:
            pass
    methods = [m.get("method") for m in fake.received]
    assert "session.disconnect" in methods
