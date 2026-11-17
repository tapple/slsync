"""ridercli command-line interface (click)."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

import anyio
import click

from .session import (
    CLIENT_VERSION,
    DEFAULT_URL,
    ViewerError,
    ViewerSession,
)

Obj = dict[str, Any]


def _execute(obj: Obj, run: Callable[[], Any]) -> Any:
    """Run an async zero-arg function under anyio with uniform error handling.

    Returns the coroutine's result (used for --json output).
    """
    try:
        return anyio.run(run)
    except ViewerError as e:
        click.echo(f"error: {e}", err=True)
        raise SystemExit(1)


def _emit(obj: Obj, text: str, payload: Any = None) -> None:
    """Print command output: raw JSON with --json, formatted text otherwise."""
    if obj.get("json"):
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(text)


@click.group(
    name="ridercli", context_settings={"help_option_names": ["-h", "--help"]}
)
@click.option(
    "--url",
    default=DEFAULT_URL,
    show_default=True,
    envvar="RIDERCLI_URL",
    help="WebSocket URL of the viewer's editor server.",
)
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit raw JSON instead of formatted text.",
)
@click.option(
    "--timeout",
    default=60.0,
    show_default=True,
    type=float,
    help="Per-call timeout in seconds.",
)
@click.option(
    "--connect-timeout",
    default=15.0,
    show_default=True,
    type=float,
    help="Timeout for connect + handshake in seconds.",
)
@click.version_option(CLIENT_VERSION, prog_name="ridercli")
@click.pass_context
def cli(ctx: click.Context, url: str, as_json: bool, timeout: float, connect_timeout: float) -> None:
    """Talk to the Second Life viewer's editor WebSocket server."""
    ctx.obj = {
        "url": url,
        "json": as_json,
        "timeout": timeout,
        "connect_timeout": connect_timeout,
    }


@cli.command()
@click.pass_obj
def status(obj: Obj) -> None:
    """Show viewer identity, session health, and server stats."""

    async def run() -> dict[str, Any]:
        async with ViewerSession(obj["url"], timeout=obj["connect_timeout"]) as s:
            info = s.handshake
            assert info is not None

            payload: dict[str, Any] = {
                "viewer": {
                    "name": info.viewer_name,
                    "version": info.viewer_version,
                    "agent_id": info.agent_id,
                    "agent_name": info.agent_name,
                    "protocol_version": info.protocol_version,
                    "server_version": info.server_version,
                    "languages": info.languages,
                    "features": info.features,
                }
            }

            t0 = time.monotonic()
            ping = await s.call(
                "system.ping", {"timestamp": int(time.time() * 1000)}, timeout=obj["timeout"]
            )
            payload["ping"] = {**(ping or {}), "rtt_ms": round((time.monotonic() - t0) * 1000, 1)}

            payload["version"] = await s.call("system.getVersion", timeout=obj["timeout"])
            payload["status"] = await s.call("system.status", timeout=obj["timeout"])
            try:
                payload["stats"] = await s.call("system.getStats", timeout=obj["timeout"])
            except ViewerError:
                pass  # undocumented method; not all viewers have it

            return payload

    p = _execute(obj, run)
    if obj["json"]:
        click.echo(json.dumps(p, indent=2))
        return

    v = p["viewer"]
    ping = p["ping"]
    lines = [
        f"viewer:   {v['name']} v{v['version']}",
        f"agent:    {v['agent_name'] or '(unknown)'} ({v['agent_id']})",
        f"protocol: {v['protocol_version']} (server api {v['server_version']})",
        f"ping:     {ping.get('pong', '?')} in {ping.get('rtt_ms')} ms",
        f"status:   {(p.get('status') or {}).get('status', '?')}",
    ]
    if v["features"]:
        feats = ", ".join(f"{k}={'on' if val else 'off'}" for k, val in sorted(v["features"].items()))
        lines.append(f"features: {feats}")
    stats = p.get("stats")
    if stats:
        lines.append(
            "stats:    "
            + ", ".join(f"{k}={val}" for k, val in sorted(stats.items()) if k != "uptime")
            + f", uptime={stats.get('uptime')}"
        )
    click.echo("\n".join(lines))


@cli.command()
@click.pass_obj
def probe(obj: Obj) -> None:
    """Connect and exercise the basic read-only methods (sanity check).

    Runs system.getVersion, system.status, system.listMethods, object.list and
    command.list so a fresh connection can be sanity-checked.
    """

    async def run() -> dict[str, Any]:
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        async with ViewerSession(obj["url"], timeout=obj["connect_timeout"]) as s:
            for method in (
                "system.getVersion",
                "system.status",
                "system.listMethods",
                "object.list",
                "command.list",
            ):
                try:
                    results[method] = await s.call(method, timeout=obj["timeout"])
                except ViewerError as e:
                    errors[method] = str(e)
        return {"results": results, "errors": errors}

    p = _execute(obj, run)
    if obj["json"]:
        click.echo(json.dumps(p, indent=2))
        return

    for method, result in p["results"].items():
        click.echo(f"== {method} ==")
        click.echo(json.dumps(result, indent=2))
        click.echo()
    for method, err in p["errors"].items():
        click.echo(f"== {method} ==\nerror: {err}\n", err=True)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
