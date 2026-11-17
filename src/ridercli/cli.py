"""ridercli command-line interface (click)."""

from __future__ import annotations

import json

import anyio
import click

from .session import (
    CLIENT_VERSION,
    DEFAULT_URL,
    HandshakeError,
    ViewerError,
    ViewerRPCError,
    ViewerSession,
)


def _run(func):
    """Run an async zero-argument function under anyio."""
    return anyio.run(func)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option(
    "--url",
    default=DEFAULT_URL,
    show_default=True,
    envvar="RIDERCLI_URL",
    help="WebSocket URL of the viewer's editor server.",
)
@click.version_option(CLIENT_VERSION, prog_name="ridercli")
@click.pass_context
def cli(ctx: click.Context, url: str) -> None:
    """Talk to the Second Life viewer's editor WebSocket server."""
    ctx.obj = url


@cli.command()
@click.option(
    "--timeout",
    default=15.0,
    show_default=True,
    help="Seconds to wait for the handshake.",
)
@click.pass_obj
def probe(url: str, timeout: float) -> None:
    """Connect, complete the handshake, and print basic session info.

    Exercises system.getVersion, system.status, system.listMethods,
    object.list and command.list so a fresh connection can be sanity-checked.
    """

    async def run() -> int:
        async with ViewerSession(url) as s:
            info = s.handshake
            assert info is not None
            click.echo(
                f"connected: {info.viewer_name} v{info.viewer_version} "
                f"(agent: {info.agent_name}, protocol {info.protocol_version})"
            )
            if info.features:
                feats = ", ".join(
                    f"{k}={'on' if v else 'off'}" for k, v in sorted(info.features.items())
                )
                click.echo(f"viewer features: {feats}")

            rc = 0
            for method, params in [
                ("system.getVersion", None),
                ("system.status", None),
                ("system.listMethods", None),
                ("object.list", None),
                ("command.list", None),
            ]:
                click.echo(f"\n== {method} ==")
                try:
                    result = await s.call(method, params)
                    click.echo(json.dumps(result, indent=2))
                except ViewerRPCError as e:
                    click.echo(f"error: {e}")
                    rc = 1

            if s.notifications:
                click.echo("\n== notifications received ==")
                for _, method, _ in s.notifications:
                    click.echo(f"  {method}")
            return rc

    raise SystemExit(_run(run))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
