"""Helpers for working with published object trees from `object.list`.

The protocol is stateless-friendly: `object.list` returns *all* currently
explored objects with their full inventories, so every command can fetch it
fresh. These helpers locate objects/prims/items by UUID or by human-readable
name paths and render trees for display.

Address forms accepted by resolve_item():
  <item_uuid>                     search all explored objects
  <prim_uuid>:<item_uuid>         canonical form
  <object_name>/<item_name>       by name (root prim inventory)
  <object_name>/<child>/<item>    via a linked child prim
  <object_uuid>/<child_uuid>/<item_uuid>
  ...any mix of uuids and names in the path segments.
"""

from __future__ import annotations

import re
from typing import Any

from .session import ViewerSession

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


class AddressError(Exception):
    """An address could not be resolved to a unique object/prim/item."""


def is_uuid(s: str) -> bool:
    return bool(UUID_RE.match(s))


# ------------------------------------------------------------------ fetching


async def fetch_published(session: ViewerSession, timeout: float = 30.0) -> list[dict]:
    """Return all currently explored objects (full trees)."""
    r = await session.call("object.list", timeout=timeout)
    return list(r.get("objects", []))


def require_explored(objects: list[dict]) -> None:
    if not objects:
        raise AddressError(
            "no objects are currently explored. Start one with:\n"
            "  ridercli objects explore <object_uuid>\n"
            "(or use 'Explore in IDE' in the viewer UI)"
        )


# ------------------------------------------------------------------ lookup


def _match(ref: str, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Filter (id, name) candidates by uuid or (case-insensitive) name."""
    if is_uuid(ref):
        return [c for c in candidates if c[0].lower() == ref.lower()]
    return [c for c in candidates if c[1].lower() == ref.lower()]


def find_object(objects: list[dict], ref: str) -> dict:
    """Find an explored object by uuid or name."""
    require_explored(objects)
    hits = _match(ref, [(o["object_id"], o.get("object_name", "")) for o in objects])
    if not hits:
        known = ", ".join(sorted(o.get("object_name", "?") for o in objects))
        raise AddressError(f"no explored object matches {ref!r} (explored: {known})")
    if len(hits) > 1:
        raise AddressError(f"ambiguous object reference {ref!r}")
    return next(o for o in objects if o["object_id"] == hits[0][0])


def find_prim(obj: dict, ref: str | None = None) -> dict:
    """Find the root or a linked child prim of an explored object.

    Returns {'id', 'name', 'inventory'}. With ref=None the root prim is
    returned; otherwise ref may be a uuid or name of any prim in the linkset.
    """
    cands = _all_prims(obj)
    if ref is None:
        return cands[0]
    hits = _match(ref, [(c["id"], c["name"]) for c in cands])
    if not hits:
        names = [c["name"] for c in cands]
        raise AddressError(
            f"no prim matches {ref!r} in object {obj.get('object_name')!r} (prims: {', '.join(names)})"
        )
    if len(hits) > 1:
        raise AddressError(f"ambiguous prim reference {ref!r}")
    return next(c for c in cands if c["id"] == hits[0][0])


def find_item(inventory: list[dict], ref: str) -> dict:
    """Find an inventory item by uuid or name."""
    hits = _match(ref, [(it["item_id"], it.get("name", "")) for it in inventory])
    if not hits:
        names = ", ".join(sorted(it.get("name", "?") for it in inventory)) or "(empty)"
        raise AddressError(f"no item matches {ref!r} (items: {names})")
    if len(hits) > 1:
        raise AddressError(f"ambiguous item reference {ref!r}")
    return next(it for it in inventory if it["item_id"] == hits[0][0])


def resolve_item(session_objects: list[dict], address: str) -> tuple[dict, dict, dict]:
    """Resolve an address string to (object, prim, item).

    See module docstring for accepted forms.
    """
    require_explored(session_objects)
    address = address.strip()
    if not address:
        raise AddressError("empty address")

    if ":" in address:
        prim_ref, item_ref = address.split(":", 1)
        parts = [p for p in prim_ref.split("/") if p]
        # Canonical "<prim_uuid>:<item_uuid>": the prim may live in any object.
        if len(parts) == 1 and is_uuid(prim_ref):
            obj, prim = _find_prim_anywhere(session_objects, prim_ref)
        else:
            # Path form: first segment is the object, rest resolve inside it.
            obj = find_object(session_objects, parts[0])
            prim = find_prim(obj, "/".join(parts[1:]) or None)
        item = find_item(prim["inventory"], item_ref)
        return obj, prim, item

    parts = [p for p in address.split("/") if p]
    if len(parts) == 1:
        # Bare item ref: search every explored object's inventories.
        ref = parts[0]
        hits: list[tuple[dict, dict, dict]] = []
        for obj in session_objects:
            for prim in _all_prims(obj):
                try:
                    item = find_item(prim["inventory"], ref)
                except AddressError:
                    continue
                hits.append((obj, prim, item))
        if not hits:
            raise AddressError(
                f"no item matches {ref!r} in any explored object "
                "(use <object>/<item> or <prim_uuid>:<item_uuid>)"
            )
        if len(hits) > 1:
            where = "; ".join(
                f"{o.get('object_name')} / {p['name']} / {i.get('name')}" for o, p, i in hits
            )
            raise AddressError(f"item {ref!r} is ambiguous (found in: {where})")
        return hits[0]

    obj = find_object(session_objects, parts[0])
    prim_ref = "/".join(parts[1:-1]) if len(parts) > 2 else None
    # A single uuid child segment resolves within the object first, then in any.
    if prim_ref and len(parts[1:-1]) == 1 and is_uuid(prim_ref):
        try:
            prim = find_prim(obj, prim_ref)
        except AddressError:
            obj, prim = _find_prim_anywhere(session_objects, prim_ref)
    else:
        prim = find_prim(obj, prim_ref)
    item = find_item(prim["inventory"], parts[-1])
    return obj, prim, item


def _all_prims(obj: dict) -> list[dict]:
    root = {"id": obj["object_id"], "name": obj.get("object_name", ""), "inventory": list(obj.get("inventory", []))}
    children = [
        {"id": lo["link_id"], "name": lo.get("link_name", ""), "inventory": list(lo.get("inventory", []))}
        for lo in obj.get("linked_objects") or []
    ]
    return [root] + children


def display_name(item: dict) -> str:
    """Synthesise a file name for an item (display only, per protocol doc)."""
    name = item.get("name", "unnamed")
    if item.get("type") == "script":
        if item.get("subtype") == 1 or item.get("vm") == "luau":
            return f"{name}.luau"
        return f"{name}.lsl"
    return name


_display_name = display_name  # backwards-compatible alias


def _find_prim_anywhere(objects: list[dict], prim_ref: str) -> tuple[dict, dict]:
    """Find a prim (by uuid or name) inside any explored object."""
    for obj in objects:
        for prim in _all_prims(obj):
            if is_uuid(prim_ref):
                if prim["id"].lower() == prim_ref.lower():
                    return obj, prim
            elif prim["name"].lower() == prim_ref.lower():
                return obj, prim
    names = sorted({p["name"] for o in objects for p in _all_prims(o)})
    raise AddressError(f"no prim matches {prim_ref!r} (prims: {', '.join(names) or '(none)'})")


# ------------------------------------------------------------------ display


def item_line(item: dict, indent: str = "  ") -> str:
    bits = [item.get("name", "?")]
    meta = [item.get("type", "?")]
    if item.get("type") == "script":
        meta.append(f"vm={item.get('vm') or '?'}")
        meta.append("running" if item.get("running") else "stopped")
        if item.get("faulted"):
            meta.append("FAULTED")
    bits.append(f"({', '.join(meta)})")
    bits.append(f"[{item['item_id']}]")
    return f"{indent}{' '.join(bits)}"


def render_object(obj: dict) -> str:
    lines = [f"{obj.get('object_name', '?')} [{obj['object_id']}]"]
    if obj.get("region"):
        lines.append(f"   region: {obj['region']}")
    if obj.get("owner_id") and obj["owner_id"] != "00000000-0000-0000-0000-000000000000":
        lines.append(f"   owner:  {obj['owner_id']}")
    if obj.get("can_save_back") is not None:
        lines.append(f"   save-back available: {'yes' if obj['can_save_back'] else 'no'}")
    for it in obj.get("inventory", []):
        lines.append(item_line(it))
    for lo in obj.get("linked_objects") or []:
        lines.append(
            f"  -- child prim: {lo.get('link_name', '?')} (#{lo.get('link_number')}) [{lo['link_id']}]"
        )
        for it in lo.get("inventory", []):
            lines.append(item_line(it, indent="     "))
    return "\n".join(lines)
