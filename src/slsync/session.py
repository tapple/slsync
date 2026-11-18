"""Async WebSocket + JSON-RPC 2.0 session to the Second Life viewer's editor server.

Built on ``anyio`` for structured concurrency and the ``websockets`` asyncio client
for the transport (anyio runs on top of asyncio by default).

Protocol reference: external-editor-json-rpc.md (copied from the viewer repo).

Connection flow:
  1. We connect as a WebSocket *client* to the viewer (default ws://127.0.0.1:9020).
  2. The viewer immediately sends a ``session.handshake`` REQUEST (with an id).
  3. We respond with a SessionHandshakeResponse (reading the challenge file if present).
  4. The viewer sends a ``session.ok`` notification; the session is then ready for calls.
"""

from __future__ import annotations

import inspect
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import anyio
import websockets
from websockets.asyncio.client import ClientConnection

DEFAULT_URL = "ws://127.0.0.1:9020"
CLIENT_NAME = "slsync"
CLIENT_VERSION = "0.1.0"
PROTOCOL_VERSION = "1.0"

# Feature flags we advertise in the handshake response (mirrors sl-vscode-plugin).
CLIENT_FEATURES: dict[str, bool] = {
    "live_sync": True,
    "error_reporting": True,
    "unified_diagnostics": True,
    "debugging": False,
    "breakpoints": False,
    "object_publish": True,
    "commands": True,
}


class ViewerError(Exception):
    """Base error for slsync viewer interactions."""


class HandshakeError(ViewerError):
    """The session handshake failed or timed out."""


class ViewerRPCError(ViewerError):
    """A JSON-RPC error response was returned by the viewer."""

    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message


@dataclass
class HandshakeInfo:
    """What we learned from the viewer's session.handshake request."""

    server_version: str
    protocol_version: str
    viewer_name: str
    viewer_version: str
    agent_id: str
    agent_name: str
    languages: list[str]
    syntax_id: str
    features: dict[str, bool]


RequestHandler = Callable[[dict | None], Awaitable[Any] | Any]
NotificationCallback = Callable[[str, dict | None], None]


@dataclass
class _PendingCall:
    """Holds the outcome of an in-flight JSON-RPC call."""

    event: anyio.Event
    result: Any = None
    error: BaseException | None = None


class ViewerSession:
    """A single connected session to the viewer's WebSocket server.

    Use as an async context manager::

        async with ViewerSession(url) as s:
            version = await s.call("system.getVersion")
    """

    def __init__(
        self,
        url: str = DEFAULT_URL,
        client_name: str = CLIENT_NAME,
        client_version: str = CLIENT_VERSION,
        timeout: float = 15.0,
    ):
        self.url = url
        self.client_name = client_name
        self.client_version = client_version
        self.timeout = timeout  # connect + handshake timeout
        self.handshake: HandshakeInfo | None = None

        self._ws: ClientConnection | None = None
        self._tg: anyio.TaskGroup | None = None
        self._next_id = 1
        self._pending: dict[int, _PendingCall] = {}
        self._request_handlers: dict[str, RequestHandler] = {}

        # Handshake coordination.
        self._handshake_event: anyio.Event | None = None
        self._handshake_params: dict | None = None
        self._handshake_id: int | None = None
        self._ok_event: anyio.Event | None = None

        # Bounded log of notifications received (newest last).
        self.notifications: list[tuple[float, str, dict | None]] = []
        self.on_notification: NotificationCallback | None = None

    # ------------------------------------------------------------- lifecycle

    async def __aenter__(self) -> "ViewerSession":
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self, timeout: float | None = None) -> HandshakeInfo:
        """Open the WebSocket and complete the session handshake."""
        if timeout is None:
            timeout = self.timeout
        self._ws = await websockets.connect(self.url, max_size=None)
        self._handshake_event = anyio.Event()
        self._ok_event = anyio.Event()

        self._tg = anyio.create_task_group()
        await self._tg.__aenter__()
        self._tg.start_soon(self._read_loop)

        try:
            # The viewer initiates with a session.handshake request; wait for it.
            with anyio.fail_after(timeout):
                await self._handshake_event.wait()
        except TimeoutError as e:
            await self.close()
            raise HandshakeError(
                f"timed out waiting for session.handshake from viewer at {self.url}"
            ) from e

        params = self._handshake_params or {}
        info = HandshakeInfo(
            server_version=params.get("server_version", ""),
            protocol_version=params.get("protocol_version", ""),
            viewer_name=params.get("viewer_name", ""),
            viewer_version=params.get("viewer_version", ""),
            agent_id=params.get("agent_id", ""),
            agent_name=params.get("agent_name", ""),
            languages=list(params.get("languages", [])),
            syntax_id=params.get("syntax_id", ""),
            features=dict(params.get("features", {})),
        )
        self.handshake = info

        response: dict[str, Any] = {
            "client_name": self.client_name,
            "client_version": self.client_version,
            "protocol_version": PROTOCOL_VERSION,
            "languages": ["lsl", "luau"],
            "features": CLIENT_FEATURES,
        }
        challenge = params.get("challenge")
        if challenge:
            response["challenge_response"] = self._read_challenge(challenge)

        # Respond to the viewer's handshake request using its id.
        await self._send_result(self._handshake_id, response)

        # Wait for session.ok.
        try:
            with anyio.fail_after(timeout):
                await self._ok_event.wait()
        except TimeoutError as e:
            await self.close()
            raise HandshakeError("timed out waiting for session.ok after handshake") from e
        return info

    def _read_challenge(self, path: str) -> str:
        """Read the UUID from the viewer's challenge temp file."""
        try:
            return Path(path).read_text().strip()
        except OSError as e:
            raise HandshakeError(f"cannot read challenge file {path!r}: {e}") from e

    # ------------------------------------------------------------------ io

    async def call(
        self, method: str, params: dict | None = None, timeout: float = 60.0
    ) -> Any:
        """Make a JSON-RPC call and await its result."""
        if self._ws is None:
            raise ViewerError("not connected")
        mid = self._next_id
        self._next_id += 1
        pending = _PendingCall(event=anyio.Event())
        self._pending[mid] = pending
        try:
            await self._send_request(mid, method, params)
            with anyio.fail_after(timeout):
                await pending.event.wait()
        except TimeoutError as e:
            raise ViewerRPCError(-32001, f"request timed out: {method}") from e
        finally:
            self._pending.pop(mid, None)
        if pending.error is not None:
            raise pending.error
        return pending.result

    async def notify(self, method: str, params: dict | None = None) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if self._ws is None:
            raise ViewerError("not connected")
        await self._send_request(None, method, params)

    def on_request(self, method: str, handler: RequestHandler) -> None:
        """Register a handler for requests the viewer may send us."""
        self._request_handlers[method] = handler

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self.notify(
                    "session.disconnect", {"reason": 0, "message": "slsync closing"}
                )
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self._tg is not None:
            self._tg.cancel_scope.cancel()
            try:
                await self._tg.__aexit__(None, None, None)
            except Exception:
                pass
            self._tg = None
        for pending in self._pending.values():
            if not pending.event.is_set():
                pending.error = ViewerRPCError(-32000, "connection closed unexpectedly")
                pending.event.set()
        self._pending.clear()

    # --------------------------------------------------------------- internals

    async def _send_request(
        self, mid: int | None, method: str, params: dict | None = None
    ) -> None:
        assert self._ws is not None
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if mid is not None:
            msg["id"] = mid
        await self._ws.send(json.dumps(msg))

    async def _send_result(self, mid: int | None, result: Any) -> None:
        if self._ws is None or mid is None:
            return
        await self._ws.send(
            json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})
        )

    async def _send_error(self, mid: int | None, code: int, message: str) -> None:
        if self._ws is None or mid is None:
            return
        await self._ws.send(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "error": {"code": code, "message": message},
                }
            )
        )

    async def _read_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            # Connection went away: fail anything still waiting.
            for pending in self._pending.values():
                if not pending.event.is_set():
                    pending.error = ViewerRPCError(
                        -32000, "connection closed unexpectedly"
                    )
                    pending.event.set()

    async def _dispatch(self, msg: dict) -> None:
        has_method = isinstance(msg.get("method"), str)
        mid = msg.get("id")

        if has_method and mid is not None:
            await self._handle_request(msg["method"], mid, msg.get("params"))
        elif has_method:
            await self._handle_notification(msg["method"], msg.get("params"))
        elif mid is not None:
            pending = self._pending.get(mid)
            if pending is None or pending.event.is_set():
                return
            if "error" in msg and msg["error"] is not None:
                err = msg["error"]
                pending.error = ViewerRPCError(
                    err.get("code", -32603), err.get("message", "")
                )
            else:
                pending.result = msg.get("result")
            pending.event.set()

    async def _handle_request(
        self, method: str, mid: int | None, params: dict | None
    ) -> None:
        if method == "session.handshake":
            # Store and signal connect(); it sends the actual response.
            self._handshake_params = params
            self._handshake_id = mid
            self._handshake_event.set()
            return

        handler = self._request_handlers.get(method)
        if handler is None:
            await self._send_error(mid, -32601, f"Method not found: {method}")
            return
        try:
            result = handler(params)
            if inspect.iscoroutine(result):
                result = await result
        except Exception as e:
            await self._send_error(mid, -32603, f"Internal error: {e}")
            return
        await self._send_result(mid, result)

    async def _handle_notification(self, method: str, params: dict | None) -> None:
        if method == "session.ok":
            assert self._ok_event is not None
            self._ok_event.set()
        self.notifications.append((time.time(), method, params))
        if len(self.notifications) > 500:
            del self.notifications[:250]
        if self.on_notification is not None:
            try:
                cb = self.on_notification(method, params)
                if inspect.iscoroutine(cb):
                    await cb
            except Exception:
                pass
