"""slsync command-line interface (click)."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Any, Callable

import anyio
import click

from . import objects as O
from .session import (
    CLIENT_VERSION,
    DEFAULT_URL,
    ViewerError,
    ViewerRPCError,
    ViewerSession,
)

Obj = dict[str, Any]

# Protocol timeouts: viewer allows 30 s to fetch an asset and up to 60 s for a
# script upload+compile; our client timeouts must exceed those.
GET_TIMEOUT = 45.0
SAVE_TIMEOUT = 75.0


def _execute(obj: Obj, run: Callable[[], Any]) -> Any:
    """Run an async zero-arg function under anyio with uniform error handling."""
    try:
        return anyio.run(run)
    except ViewerError as e:
        click.echo(f"error: {e}", err=True)
        raise SystemExit(1)


def _session(obj: Obj) -> ViewerSession:
    return ViewerSession(obj["url"], timeout=obj["connect_timeout"])


def _emit_json(payload: Any) -> None:
    click.echo(json.dumps(payload, indent=2))


def _resolve_item_or_die(objs: list[dict], address: str):
    try:
        return O.resolve_item(objs, address)
    except O.AddressError as e:
        raise click.ClickException(str(e)) from e


def _resolve_prim_or_die(objs: list[dict], address: str):
    """Resolve a prim address (uuid/name, or object[/child] path)."""
    try:
        parts = [p for p in address.strip().split("/") if p]
        if not parts:
            raise O.AddressError("empty address")
        obj = O.find_object(objs, parts[0])
        prim_ref = "/".join(parts[1:]) or None
        if prim_ref and len(parts[1:]) == 1 and O.is_uuid(prim_ref):
            found = O.find_prim(obj, prim_ref)
            return obj, found
        return obj, O.find_prim(obj, prim_ref)
    except O.AddressError as e:
        raise click.ClickException(str(e)) from e


# --------------------------------------------------------------------- group


@click.group(
    name="slsync", context_settings={"help_option_names": ["-h", "--help"]}
)
@click.option(
    "--url",
    default=DEFAULT_URL,
    show_default=True,
    envvar="SLSYNC_URL",
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
@click.version_option(CLIENT_VERSION, prog_name="slsync")
@click.pass_context
def cli(ctx: click.Context, url: str, as_json: bool, timeout: float, connect_timeout: float) -> None:
    """Talk to the Second Life viewer's editor WebSocket server."""
    ctx.obj = {
        "url": url,
        "json": as_json,
        "timeout": timeout,
        "connect_timeout": connect_timeout,
    }


# ------------------------------------------------------------------ session


@cli.command()
@click.pass_obj
def status(obj: Obj) -> None:
    """Show viewer identity, session health, and server stats."""

    async def run() -> dict[str, Any]:
        async with _session(obj) as s:
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
        _emit_json(p)
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
    """Connect and exercise the basic read-only methods (sanity check)."""

    async def run() -> dict[str, Any]:
        results: dict[str, Any] = {}
        errors: dict[str, str] = {}
        async with _session(obj) as s:
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
        _emit_json(p)
        return

    for method, result in p["results"].items():
        click.echo(f"== {method} ==")
        click.echo(json.dumps(result, indent=2))
        click.echo()
    for method, err in p["errors"].items():
        click.echo(f"== {method} ==\nerror: {err}\n", err=True)


# ------------------------------------------------------------------- objects


@cli.group("objects")
def objects_group() -> None:
    """Manage explored in-world objects (linksets)."""


@objects_group.command("list")
@click.pass_obj
def objects_list(obj: Obj) -> None:
    """List currently explored objects and their inventories."""

    async def run() -> list[dict]:
        async with _session(obj) as s:
            return await O.fetch_published(s, timeout=obj["timeout"])

    objs = _execute(obj, run)
    if obj["json"]:
        _emit_json(objs)
        return
    if not objs:
        click.echo(
            "no objects explored. Use 'slsync objects explore <object_uuid>' "
            "or 'Explore in IDE' in the viewer."
        )
        return
    for i, o in enumerate(objs):
        if i:
            click.echo()
        click.echo(O.render_object(o))


@objects_group.command("explore")
@click.argument("object_ref")
@click.option(
    "--wait",
    default=15.0,
    show_default=True,
    type=float,
    help="Seconds to wait for the object to be published.",
)
@click.pass_obj
def objects_explore(obj: Obj, object_ref: str, wait: float) -> None:
    """Ask the viewer to start exploring an object (by UUID).

    Requires modify permission on the object. Waits for the object to be
    published and prints its tree.
    """

    async def run() -> dict:
        async with _session(obj) as s:
            r = await s.call(
                "object.request", {"object_id": object_ref}, timeout=obj["timeout"]
            )
            published = None
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                for _, m, p in s.notifications:
                    if m == "object.publish" and p and p.get("object", {}).get("object_id") == object_ref:
                        published = p["object"]
                if published is None:
                    for o in await O.fetch_published(s, timeout=obj["timeout"]):
                        if o["object_id"] == object_ref:
                            published = o
                            break
                if published is not None:
                    break
                await anyio.sleep(0.5)
            return {"request": r, "object": published}

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    if p["object"] is None:
        raise click.ClickException(f"object was accepted but not published within {wait:.0f}s")
    click.echo(O.render_object(p["object"]))


@objects_group.command("stop")
@click.argument("object_ref")
@click.pass_obj
def objects_stop(obj: Obj, object_ref: str) -> None:
    """Stop exploring an object (by UUID or name). Idempotent."""

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            try:
                target = O.find_object(objs, object_ref)
            except O.AddressError:
                target = None  # may already be unpublished; let the viewer decide
            if target is None:
                return {"success": False, "object_id": object_ref}
            return await s.call(
                "object.unpublish", {"object_id": target["object_id"]}, timeout=obj["timeout"]
            )

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    if p.get("success"):
        click.echo(f"unpublished {p.get('object_id', object_ref)}")
    else:
        click.echo(f"{object_ref} is not (or no longer) explored")


@objects_group.command("show")
@click.argument("object_ref")
@click.pass_obj
def objects_show(obj: Obj, object_ref: str) -> None:
    """Show one explored object's full tree (by UUID or name)."""

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            try:
                return O.find_object(objs, object_ref)
            except O.AddressError as e:
                raise click.ClickException(str(e)) from e

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(O.render_object(p))


def _prim_modify(obj: Obj, prim_ref: str, props: dict) -> None:
    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim = _resolve_prim_or_die(objs, prim_ref)
            return await s.call(
                "object.modify", {"prim_id": prim["id"], **props}, timeout=obj["timeout"]
            )

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"dispatched (confirmation arrives via object.update): {p}")


@objects_group.command("rename")
@click.argument("prim_ref")
@click.argument("name")
@click.pass_obj
def objects_rename(obj: Obj, prim_ref: str, name: str) -> None:
    """Rename a prim (root or child)."""
    _prim_modify(obj, prim_ref, {"name": name})


@objects_group.command("describe")
@click.argument("prim_ref")
@click.argument("description")
@click.pass_obj
def objects_describe(obj: Obj, prim_ref: str, description: str) -> None:
    """Set a prim's description."""
    _prim_modify(obj, prim_ref, {"description": description})


@objects_group.command("perms")
@click.argument("prim_ref")
@click.argument("next_owner", type=int)
@click.pass_obj
def objects_perms(obj: Obj, prim_ref: str, next_owner: int) -> None:
    """Set a prim's next-owner permission mask (integer)."""
    _prim_modify(obj, prim_ref, {"permissions": {"next_owner": next_owner}})


# --------------------------------------------------------------------- items


@cli.group("items")
def items_group() -> None:
    """Manage inventory items (scripts and notecards).

    Item addresses: <item>, <prim>:<item>, <object>/<item>,
    <object>/<child>/<item> — each segment a UUID or name.
    """


@items_group.command("list")
@click.argument("prim_ref")
@click.pass_obj
def items_list(obj: Obj, prim_ref: str) -> None:
    """List the scripts and notecards in a prim."""

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim = _resolve_prim_or_die(objs, prim_ref)
            return prim

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"{p['name']} [{p['id']}]")
    for it in p["inventory"]:
        click.echo(O.item_line(it))


@items_group.command("create")
@click.argument("prim_ref")
@click.argument("name")
@click.option("--type", "item_type", required=True, type=click.Choice(["script", "notecard"]))
@click.option(
    "--vm",
    default="lsl2",
    show_default=True,
    type=click.Choice(["lsl2", "mono", "luau"]),
    help="Compile target (scripts only).",
)
@click.option("--text", default=None, help="Initial body text (notecards only).")
@click.pass_obj
def items_create(obj: Obj, prim_ref: str, name: str, item_type: str, vm: str, text: str | None) -> None:
    """Create a new script or notecard in a prim.

    The simulator may rename the item if a duplicate name exists; the
    response shows the actual result.
    """

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim = _resolve_prim_or_die(objs, prim_ref)
            params: dict[str, Any] = {"prim_id": prim["id"], "name": name, "type": item_type}
            if item_type == "script":
                params["vm"] = vm
            if text is not None:
                params["text"] = text
            return await s.call("object.item.create", params, timeout=obj["timeout"])

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(O.item_line(p))


@items_group.command("delete")
@click.argument("item_ref")
@click.option("-y", "--yes", is_flag=True, help="Do not ask for confirmation.")
@click.pass_obj
def items_delete(obj: Obj, item_ref: str, yes: bool) -> None:
    """Delete a script or notecard (requires modify permission)."""

    async def run() -> dict:
        if not yes:
            click.confirm(f"delete item {item_ref!r}?", abort=True)
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim, item = _resolve_item_or_die(objs, item_ref)
            return await s.call(
                "object.item.delete",
                {"prim_id": prim["id"], "item_id": item["item_id"]},
                timeout=obj["timeout"],
            )

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"deleted {p.get('item_id')}")


def _item_modify(obj: Obj, item_ref: str, props: dict) -> None:
    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim, item = _resolve_item_or_die(objs, item_ref)
            return await s.call(
                "object.item.modify",
                {"prim_id": prim["id"], "item_id": item["item_id"], **props},
                timeout=obj["timeout"],
            )

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"dispatched (confirmation arrives via object.update): {p}")


@items_group.command("rename")
@click.argument("item_ref")
@click.argument("new_name")
@click.pass_obj
def items_rename(obj: Obj, item_ref: str, new_name: str) -> None:
    """Rename an item (pure inventory name, no file extension)."""
    _item_modify(obj, item_ref, {"name": new_name})


@items_group.command("describe")
@click.argument("item_ref")
@click.argument("description")
@click.pass_obj
def items_describe(obj: Obj, item_ref: str, description: str) -> None:
    """Set an item's description."""
    _item_modify(obj, item_ref, {"description": description})


@items_group.command("perms")
@click.argument("item_ref")
@click.argument("next_owner", type=int)
@click.pass_obj
def items_perms(obj: Obj, item_ref: str, next_owner: int) -> None:
    """Set an item's next-owner permission mask (integer)."""
    _item_modify(obj, item_ref, {"permissions": {"next_owner": next_owner}})


# ------------------------------------------------------------- get / put


def _safe_filename(name: str) -> str:
    """Make an inventory name safe to use as a local file name."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


@cli.command("get")
@click.argument("item_ref")
@click.argument("file", required=False, type=click.Path())
@click.pass_obj
def get(obj: Obj, item_ref: str, file: str | None) -> None:
    """Fetch a script or notecard's content (scp-style).

    ITEM_REF is an item address; FILE may be omitted or '-' for stdout, or a
    directory in which to write the file. Notecard envelopes are unwrapped
    by the viewer. Scripts require copy+modify permission on the item.
    """

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim, item = _resolve_item_or_die(objs, item_ref)
            r = await s.call(
                "object.content.get",
                {"prim_id": prim["id"], "item_id": item["item_id"]},
                timeout=GET_TIMEOUT,
            )
            return {
                "object": None,
                "prim_id": prim["id"],
                "item_id": item["item_id"],
                "name": item.get("name"),
                "type": item.get("type"),
                "display_name": O.display_name(item),
                "content": r.get("content", ""),
            }

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return

    content: str = p["content"]
    if file in (None, "-"):
        sys.stdout.write(content)
        if content and not content.endswith("\n"):
            sys.stdout.write("\n")
        return

    path = file
    if os.path.isdir(path):
        path = os.path.join(path, _safe_filename(p["display_name"]))
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    click.echo(f"wrote {len(content)} chars to {path}", err=True)


@cli.command("put")
@click.argument("file", type=click.Path(exists=True))
@click.argument("prim_ref")
@click.argument("name", required=False)
@click.option(
    "--vm",
    default=None,
    type=click.Choice(["lsl2", "mono", "luau"]),
    help="Compile target when saving a script (default: keep current).",
)
@click.option("--run", "running", flag_value=True, default=None, help="Run the script after save.")
@click.option("--no-run", "running", flag_value=False, help="Stop the script after save.")
@click.option(
    "--save-timeout",
    default=SAVE_TIMEOUT,
    show_default=True,
    type=float,
    help="Timeout in seconds for item creation and content save (viewer needs up to ~60 s).",
)
@click.pass_obj
def put(obj: Obj, file: str, prim_ref: str, name: str | None, vm: str | None, running: bool | None,
        save_timeout: float) -> None:
    """Upload a file to an object (scp-style).

    If NAME names an existing item in the prim, its content is replaced.
    Otherwise a new item is created: '.lsl' files become LSL scripts,
    '.luau' files Luau scripts, anything else a notecard. '-' reads stdin.
    """

    src_ext: str | None = None
    if file != "-" and (os.path.basename(file).lower().endswith(".lsl") or os.path.basename(file).lower().endswith(".luau")):
        src_ext = os.path.basename(file).rsplit(".", 1)[-1].lower()

    if file == "-":
        content = sys.stdin.read()
        base = name or "pasted"
    else:
        with open(file, "r", encoding="utf-8") as f:
            content = f.read()
        base = name or os.path.basename(file)

    def infer_kind(n: str) -> tuple[str, str | None]:
        low = n.lower()
        if low.endswith(".lsl"):
            return "script", "lsl2"
        if low.endswith(".luau"):
            return "script", "luau"
        return "notecard", None

    # The source file's extension is the strongest signal of content type;
    # fall back to the (target) name's extension.
    item_type, default_vm = (
        infer_kind(base) if src_ext is None else ("script", {"lsl": "lsl2", "luau": "luau"}[src_ext])
    )
    # Inventory names carry no extension.
    inv_name = base[:-4] if base.lower().endswith((".lsl", ".luau")) else base

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim = _resolve_prim_or_die(objs, prim_ref)
            existing = next(
                (it for it in prim["inventory"] if it.get("name", "").lower() == inv_name.lower()),
                None,
            )
            if existing is not None:
                params: dict[str, Any] = {
                    "prim_id": prim["id"],
                    "item_id": existing["item_id"],
                    "content": content,
                }
                if vm:
                    params["vm"] = vm
                if running is not None:
                    params["running"] = running
                r = await _save_with_verify(s, prim["id"], existing["item_id"], params, content, obj,
                                            save_timeout=save_timeout)
                return {"action": "updated", "item_id": existing["item_id"], **r}

            # Create the item first.
            cparams: dict[str, Any] = {
                "prim_id": prim["id"],
                "name": inv_name,
                "type": item_type,
            }
            if item_type == "script":
                cparams["vm"] = vm or default_vm or "lsl2"
            # Snapshot before creating: validates the create response and
            # feeds the diff-based workaround below.
            before_ids = {it["item_id"] for it in prim["inventory"]}
            created: dict | None = None
            create_err: ViewerRPCError | None = None
            try:
                created = await s.call("object.item.create", cparams, timeout=save_timeout)
                # The viewer's post-creation inventory check is unreliable in
                # BOTH directions (see NOTES.md): besides the systematic
                # "Item was not found in updated inventory" race, it has been
                # observed to return a PRE-EXISTING unrelated item as the
                # result (official 26.5.0, 2026-11-19). An id present in our
                # pre-create snapshot cannot be the new item — fall through to
                # the diff-based search rather than overwrite that item.
                if created.get("item_id") in before_ids:
                    click.echo(
                        "warning: create response referenced a pre-existing item; "
                        "re-identifying via inventory diff",
                        err=True,
                    )
                    created = None
            except ViewerRPCError as e:
                # The documented race: the item is created in-world but the
                # viewer's post-creation check fails. Detect the new item by
                # diffing inventories, with retries.
                create_err = e
            if created is None:
                for _ in range(20):  # up to ~20 s
                    after = await O.fetch_published(s, timeout=obj["timeout"])
                    try:
                        _, prim_now = _resolve_prim_or_die(after, prim_ref)
                    except click.ClickException:
                        raise
                    new_items = [
                        it for it in prim_now["inventory"] if it["item_id"] not in before_ids
                    ]
                    # Only accept a candidate whose name is inv_name or a sim
                    # duplicate-rename of it. If the viewer's inventory snapshot
                    # was stale/empty, before_ids misses existing items and the
                    # diff would report them as "new" — accepting the first such
                    # item would overwrite an UNRELATED item with the uploaded
                    # content (observed live 2026-11-19). Keep polling instead.
                    cands = [
                        it for it in new_items if _is_sim_rename(it.get("name", ""), inv_name)
                    ]
                    if cands:
                        created = {
                            "item_id": cands[0]["item_id"],
                            "name": cands[0].get("name", inv_name),
                        }
                        break
                    await anyio.sleep(1.0)
                if created is None:
                    if create_err is not None:
                        raise create_err
                    raise click.ClickException(
                        f"item {inv_name!r} was created but could not be identified in "
                        f"the prim's inventory; check for a new item there and retry"
                    )
            item_id = created["item_id"]
            actual_name = created.get("name", inv_name)
            # Upload content after creation for both types. (item.create's
            # `text` param is not reliably honoured by sim-side cap handlers,
            # which can leave an empty notecard; content.save always works.)
            sparams: dict[str, Any] = {
                "prim_id": prim["id"],
                "item_id": item_id,
                "content": content,
            }
            if vm:
                sparams["vm"] = vm
            if running is not None:
                sparams["running"] = running
            r = await _save_with_verify(s, prim["id"], item_id, sparams, content, obj,
                                        save_timeout=save_timeout)
            return {"action": "created+updated", "item_id": item_id, "name": actual_name, **r}

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return

    click.echo(f"{p['action']}: item {p.get('item_id')}")
    if p.get("name") and p.get("name") != inv_name:
        click.echo(f"  (simulator renamed it to {p['name']!r})")
    if p.get("note"):
        click.echo(f"  {p['note']}")
    elif "compiled" in p:
        click.echo(f"  compiled: {'yes' if p['compiled'] else 'no'}")
        for d in p.get("diagnostics") or []:
            click.echo(
                f"  {d.get('level', '?')} line {d.get('row', '?')}: {d.get('message', '')}",
                err=True,
            )
        if not p["compiled"]:
            raise SystemExit(1)


def _is_sim_rename(candidate: str, wanted: str) -> bool:
    """True if candidate is wanted or a sim duplicate-rename of it.

    The simulator renames items with duplicate names by appending a counter
    (e.g. 'ground-script' -> 'ground-script 1'). Used to identify the item
    just created when diffing inventories, so an unrelated item is never
    mistaken for the new one.
    """
    c = candidate.strip()
    w = wanted.strip()
    if not w:
        return False
    if c.lower() == w.lower():
        return True
    prefix = w + " "
    if c.lower().startswith(prefix.lower()):
        return c[len(prefix):].isdigit()
    return False


async def _save_with_verify(s: ViewerSession, prim_id: str, item_id: str, params: dict, content: str,
                            obj: Obj, save_timeout: float = SAVE_TIMEOUT) -> dict:
    """object.content.save with a read-back fallback.

    On some viewer paths (seen with worn attachments) the upload completes but
    the viewer's compile-wait never responds, so the call times out even though
    the content is saved. Verify by reading the item back before failing.
    """
    try:
        return await s.call("object.content.save", params=params, timeout=save_timeout)
    except ViewerRPCError as e:
        if e.code != -32001:  # only timeouts are worth verifying
            raise
        rb = await s.call(
            "object.content.get",
            {"prim_id": prim_id, "item_id": item_id},
            timeout=GET_TIMEOUT,
        )
        if rb.get("content") == content:
            return {
                "success": True,
                "compiled": None,
                "note": "viewer did not confirm compilation; verified by read-back",
            }
        raise


# ------------------------------------------------------------------- scripts


@cli.group("scripts")
def scripts_group() -> None:
    """Start, stop, and reset scripts in explored objects."""


@scripts_group.command("list")
@click.pass_obj
def scripts_list(obj: Obj) -> None:
    """List scripts the viewer currently tracks (live-sync subscriptions)."""

    async def run() -> dict:
        async with _session(obj) as s:
            return await s.call("script.list", timeout=obj["timeout"])

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"temp dir: {p.get('temp_dir')}")
    ids = p.get("script_ids") or []
    if not ids:
        click.echo("no subscribed scripts")
    for sid in ids:
        click.echo(f"  {sid}")


def _set_running_cmd(obj: Obj, item_ref: str, running: bool, wait_update: bool) -> None:
    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            o, prim, item = _resolve_item_or_die(objs, item_ref)
            r = await s.call(
                "object.script.set_running",
                {"prim_id": prim["id"], "item_id": item["item_id"], "running": running},
                timeout=obj["timeout"],
            )
            result = {**r, "item_id": item["item_id"], "object_id": o["object_id"]}
            if wait_update:
                # Confirmation arrives as an object.update (inventory replacement
                # carrying the new running state); wait for one, then re-check.
                deadline = time.monotonic() + 15.0
                seen = False
                while time.monotonic() < deadline and not seen:
                    for _, m, p in s.notifications:
                        if m == "object.update" and p and p.get("object_id") == o["object_id"]:
                            seen = True
                    if not seen:
                        await anyio.sleep(0.5)
                objs2 = await O.fetch_published(s, timeout=obj["timeout"])
                try:
                    _, prim2, item2 = _resolve_item_or_die(objs2, f"{prim['id']}:{item['item_id']}")
                    result["confirmed"] = seen
                    result["running_now"] = bool(item2.get("running"))
                except click.ClickException:
                    result["confirmed"] = seen
                if not seen:
                    result["note"] = "no object.update received within 15s"
            return result

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    verb = "start" if running else "stop"
    click.echo(f"{verb} dispatched for {p.get('item_id')}")
    if "running_now" in p:
        state = "running" if p["running_now"] else "stopped"
        click.echo(f"  now: {state}" + ("" if p.get("confirmed") else " (no update observed)"))


@scripts_group.command("start")
@click.argument("item_ref")
@click.option("--wait-update", is_flag=True, help="Wait for the confirming object.update (~15 s).")
@click.pass_obj
def scripts_start(obj: Obj, item_ref: str, wait_update: bool) -> None:
    """Start a script (requires modify permission)."""
    _set_running_cmd(obj, item_ref, True, wait_update)


@scripts_group.command("stop")
@click.argument("item_ref")
@click.option("--wait-update", is_flag=True, help="Wait for the confirming object.update (~15 s).")
@click.pass_obj
def scripts_stop(obj: Obj, item_ref: str, wait_update: bool) -> None:
    """Stop a script (requires modify permission)."""
    _set_running_cmd(obj, item_ref, False, wait_update)


@scripts_group.command("reset")
@click.argument("item_ref")
@click.pass_obj
def scripts_reset(obj: Obj, item_ref: str) -> None:
    """Reset a script to its default state (requires modify permission)."""

    async def run() -> dict:
        async with _session(obj) as s:
            objs = await O.fetch_published(s, timeout=obj["timeout"])
            _, prim, item = _resolve_item_or_die(objs, item_ref)
            r = await s.call(
                "object.script.reset",
                {"prim_id": prim["id"], "item_id": item["item_id"]},
                timeout=obj["timeout"],
            )
            return {**r, "item_id": item["item_id"]}

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"reset dispatched for {p.get('item_id')}")


# ---------------------------------------------------------------------- tail

# All notification kinds tail can render; default is the console-relevant ones.
TAIL_KINDS = ("debug", "error", "update", "compiled", "publish", "unpublish")
DEFAULT_TAIL_KINDS = ("debug", "error")


def _use_color() -> bool:
    """ANSI colours only on a terminal, and never when NO_COLOR is set."""
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _paint(text: str, code: str, color: bool) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if color else text


def _fmt_tail_line(kind: str, params: dict, color: bool = False) -> str:
    ts = time.strftime("%H:%M:%S")
    if kind == "runtime.debug":
        # Viewer-console style: [HH:MM:SS] ObjectName: message
        # Colours mirror the viewer's console: owner_say yellow, debug red.
        code = "33" if params.get("channel") == "owner_say" else "31"
        return _paint(
            f"[{ts}] {params.get('object_name', '?')}: {params.get('message', '')}",
            code, color,
        )
    if kind == "runtime.error":
        line = (
            f"[{ts}] ERR  {params.get('object_name', '?')} "
            f"line {params.get('line', 0)}: {params.get('error', params.get('message', ''))}"
        )
        for frame in (params.get("stack") or [])[1:]:
            line += f"\n       at {frame}"
        # Luau errors are fatal to the script: white on red. item.language is
        # unreliable (reports lsl), so detect via the lua_script stack frames.
        is_luau = "lua_script:" in (params.get("message") or "") or any(
            f.startswith("lua_script:") for f in (params.get("stack") or [])
        )
        return _paint(line, "41;97" if is_luau else "31", color)
    if kind == "object.update":
        what = []
        if params.get("inventory") is not None:
            what.append("root-inventory")
        ch = (params.get("changes") or {}).get("linked_objects") or {}
        if ch.get("modified"):
            what.append(f"children:{len(ch['modified'])}")
        if params.get("linked_objects") is not None:
            what.append("linkset")
        if params.get("object_name") is not None:
            what.append("name")
        # System kinds (not produced by any script): light grey.
        return _paint(
            f"[{ts}] UPD  {params.get('object_id', '?')} ({', '.join(what) or '?'})",
            "90", color,
        )
    if kind == "script.compiled":
        diag = params.get("diagnostics") or []
        extra = "; ".join(f"{d.get('level')}: {d.get('message')}" for d in diag[:3])
        return _paint(
            f"[{ts}] CMP  script {params.get('script_id', '?')}: "
            f"compiled={'yes' if params.get('success') else 'NO'} running={params.get('running')}"
            + (f" [{extra}]" if extra else ""),
            "90", color,
        )
    if kind == "object.publish":
        o = params.get("object") or {}
        n = len(o.get("linked_objects") or [])
        return _paint(
            f"[{ts}] PUB  {o.get('object_name') or o.get('object_id', '?')} "
            f"[{o.get('object_id', '?')}]"
            + (f" ({n} linked prim(s))" if n else ""),
            "90", color,
        )
    if kind == "object.unpublish":
        reason = f" ({params['reason']})" if params.get("reason") else ""
        return _paint(f"[{ts}] UNPUB {params.get('object_id', '?')}{reason}", "90", color)
    return f"[{ts}] {kind} {json.dumps(params)}"


@cli.command("tail")
@click.option("--object", "object_ref", default=None, help="Only events for this object (UUID or name). Ignored with --raw.")
@click.option(
    "--kinds",
    default=",".join(DEFAULT_TAIL_KINDS),
    show_default=True,
    help=f"Comma-separated subset of: {','.join(TAIL_KINDS)}. Ignored with --raw.",
)
@click.option("--jsonl", is_flag=True, help="Emit one JSON object per line on stdout (agent mode).")
@click.option(
    "--raw",
    is_flag=True,
    help="Print every wire frame of THIS connection exactly as received/sent, "
    "[in]/[out]-prefixed (handshake + own calls), plus ALL broadcast "
    "notifications from any source. Sibling connections' request/response pairs "
    "are NOT visible (they go only to that connection). Protocol debugging. "
    "Ignores --kinds/--jsonl/--object.",
)
@click.option(
    "--all",
    "all_kinds",
    is_flag=True,
    help="Show every kind, incl. system events (alias for --kinds=debug,error,update,compiled,publish,unpublish).",
)
@click.pass_obj
def tail(obj: Obj, object_ref: str | None, kinds: str, jsonl: bool, raw: bool,
         all_kinds: bool) -> None:
    """Stream events from the viewer's editor WebSocket until Ctrl-C.

    The viewer broadcasts notifications to ALL connected clients, so this
    connection passively receives script output (llOwnerSay/print →
    runtime.debug, faults → runtime.error) and object lifecycle events for
    every explored object — no subscription needed. Keeping a tail running
    also means the viewer's "Explore in IDE" button publishes directly
    instead of trying to launch an external editor.

    Display modes:
      (default)  human-readable, viewer-console style: [HH:MM:SS] ObjectName: message
      --jsonl    one JSON object per line on stdout (status → stderr); agent mode
      --raw      every wire frame as received/sent; protocol debugging

    Kinds (default: debug,error): debug, error, update, compiled, publish,
    unpublish. 'compiled' events carry no object id and bypass --object.
    --all shows every kind; system kinds render light grey.

    Colours (terminal only; NO_COLOR disables): owner_say yellow, debug red,
    errors red (Luau errors white-on-red — fatal to the script), system
    events light grey. Mirrors the viewer's console colouring.

    Examples:
      slsync tail                          # watch script output of explored objects
      slsync tail --object "TH AO"         # one object, by name or UUID
      slsync tail --all                    # everything, incl. system events
      slsync tail --jsonl > events.jsonl & # agent: capture in background
    """
    if raw and jsonl:
        raise click.ClickException("--raw and --jsonl are mutually exclusive")
    kind_set = {k.strip() for k in kinds.split(",") if k.strip()}
    bad = kind_set - set(TAIL_KINDS)
    if bad:
        raise click.ClickException(f"unknown kinds: {', '.join(sorted(bad))}")
    if all_kinds:
        kind_set = set(TAIL_KINDS)

    def make_session() -> ViewerSession:
        s = _session(obj)

        if raw:
            s.on_raw_frame = lambda direction, text: click.echo(
                f"[{direction}] {text}"
            )
            return s

        def on_notification(method: str, params: dict | None) -> None:
            kind = None
            if method == "runtime.debug" and "debug" in kind_set:
                kind = "debug"
            elif method == "runtime.error" and "error" in kind_set:
                kind = "error"
            elif method == "object.update" and "update" in kind_set:
                kind = "update"
            elif method == "script.compiled" and "compiled" in kind_set:
                kind = "compiled"
            elif method == "object.publish" and "publish" in kind_set:
                kind = "publish"
            elif method == "object.unpublish" and "unpublish" in kind_set:
                kind = "unpublish"
            if kind is None or params is None:
                return
            # compiled events carry no object id; pass them through the filter.
            if obj_id_filter[0] and kind != "compiled":
                if kind == "publish":  # id is nested under params["object"]
                    oid = (params.get("object") or {}).get("object_id")
                else:
                    oid = params.get("object_id")
                if oid is not None and oid != obj_id_filter[0]:
                    return
            if jsonl:
                click.echo(json.dumps({"ts": time.time(), "kind": kind, **params}), err=False)
            else:
                click.echo(_fmt_tail_line(method, params, color=_use_color()))

        s.on_notification = on_notification
        return s

    obj_id_filter: list[str | None] = [None]

    async def run() -> int:
        s = make_session()
        await s.connect()
        try:
            if object_ref and not raw:
                objs = await O.fetch_published(s, timeout=obj["timeout"])
                try:
                    target = O.find_object(objs, object_ref)
                except O.AddressError as e:
                    raise click.ClickException(str(e)) from e
                obj_id_filter[0] = target["object_id"]
            click.echo(
                "tail: connected; mode="
                + ("raw" if raw else f"kinds={','.join(sorted(kind_set))}")
                + (f" object={obj_id_filter[0]}" if obj_id_filter[0] else "")
                + " — Ctrl-C to stop",
                err=True,
            )
            while True:
                await anyio.sleep(3600)  # keep the task alive; events arrive via callback
        finally:
            await s.close()
        return 0

    try:
        _execute(obj, run)
    except KeyboardInterrupt:
        click.echo("\ntail: stopped", err=True)


# ------------------------------------------------------------------- commands


@cli.group("commands")
def commands_group() -> None:
    """Run viewer commands (teleport, camera focus, save-back, ...)."""


@commands_group.command("list")
@click.pass_obj
def commands_list(obj: Obj) -> None:
    """List the commands the viewer supports, with their parameters."""

    async def run() -> dict:
        async with _session(obj) as s:
            return await s.call("command.list", timeout=obj["timeout"])

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    for c in p.get("commands") or []:
        click.echo(f"{c['command']}")
        if c.get("description"):
            click.echo(f"    {c['description']}")
        for pname, info in (c.get("params") or {}).items():
            req = "required" if info.get("required") else "optional"
            desc = f" — {info['description']}" if info.get("description") else ""
            click.echo(f"    --{pname.replace('_', '-')} <{info.get('type', '?')}> ({req}){desc}")


def _parse_param(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


@commands_group.command("run")
@click.argument("command_id")
@click.option(
    "--param",
    multiple=True,
    metavar="KEY=VALUE",
    help="Command parameter (repeatable). VALUE is JSON-parsed when possible.",
)
@click.option("--json-params", default=None, help="Full params object as a JSON string.")
@click.pass_obj
def commands_run(obj: Obj, command_id: str, param: tuple[str, ...], json_params: str | None) -> None:
    """Run a viewer command, e.g. 'commands run viewer.teleport --param object_id=...'."""
    params: dict[str, Any] = {}
    if json_params:
        try:
            params.update(json.loads(json_params))
        except json.JSONDecodeError as e:
            raise click.ClickException(f"invalid --json-params: {e}") from e
    for p in param:
        if "=" not in p:
            raise click.ClickException(f"--param expects KEY=VALUE, got {p!r}")
        k, v = p.split("=", 1)
        params[k] = _parse_param(v)

    async def run() -> dict:
        async with _session(obj) as s:
            if not (s.handshake and s.handshake.features.get("commands")):
                raise ViewerError("viewer did not advertise the 'commands' feature")
            return await s.call(
                "command.execute", {"command": command_id, "params": params}, timeout=obj["timeout"]
            )

    p = _execute(obj, run)
    if obj["json"]:
        _emit_json(p)
        return
    click.echo(f"{command_id}: {'ok' if p.get('success') else 'FAILED'}")
    if p.get("result") is not None:
        click.echo(json.dumps(p["result"], indent=2))
    if not p.get("success"):
        raise SystemExit(1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
