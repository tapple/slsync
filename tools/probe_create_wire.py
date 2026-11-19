#!/usr/bin/env python3
"""Wire-level probe: does the viewer's object.item.create response lie, and
does a hung LSL save contaminate subsequent creates?

Captures every frame (in/out) with timestamps to /tmp/wire-capture-*.log, then
replays the failing sequence from the 2026-11-19 pytest run:
  1. create an item (retries through the documented "Item was not found in
     updated inventory" race — each failed attempt still creates the item
     in-world; final cleanup diffs the inventory and removes everything new)
  2. save bad LSL content to it (save hangs -> client timeout at 30 s, leaving
     a dangling compile-wait on the viewer side)
  3. immediately: object.item.create again -> compare the response's item_id
     against the pre-create snapshot and the inventory diff

Also scans the capture for duplicate inbound frames and inbound messages
carrying an id that are not responses (a notification with an id would be
misdispatched as a response by slsync — see session.py _dispatch).

Usage: uv run --project <repo> python tests/probe_create_wire.py [URL]
       (default ws://127.0.0.1:9021)
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import anyio
from anyio import sleep
from slsync import objects as O
from slsync.session import ViewerRPCError, ViewerSession

URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:9021"
LOG = f"/tmp/wire-capture-{int(time.time())}.log"

frames: list[tuple[float, str, str]] = []


def log_frame(direction: str, text: str) -> None:
    frames.append((time.time(), direction, text))
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}.{int(time.time() % 1 * 1000):03d} {direction}] {text}\n")


GOOD_LSL = 'default {\n    state_entry() {\n        llOwnerSay("ok");\n    }\n}\n'
BAD_LSL = 'default {\n    state_entry() {\n        llOwnerSay("hi");\n'  # missing brace


async def main() -> None:
    s = ViewerSession(URL, timeout=15.0)
    s.on_raw_frame = log_frame
    await s.connect()
    try:
        objs = await O.fetch_published(s, timeout=60.0)
        obj = O.find_object(objs, "Object")
        prim_id = obj["object_id"]
        before = {it["item_id"]: it.get("name") for it in obj.get("inventory", [])}

        # Step 1: item that will hold the hung bad save (retry through the race)
        n1 = f"diag-hang-{uuid.uuid4().hex[:6]}"
        r1 = None
        for attempt in range(5):
            try:
                r1 = await s.call("object.item.create",
                                  {"prim_id": prim_id, "name": n1, "type": "script", "vm": "lsl2"},
                                  timeout=75.0)
                break
            except ViewerRPCError as e:
                print(f"step1 create attempt {attempt + 1}: [{e.code}] {e.message} (retrying)")
                await sleep(1.0)
        if r1 is None or r1.get("item_id") in before:
            print("step1: could not get a usable item; aborting (cleanup runs below)")
            return
        print(f"step1 create {n1}: id={r1.get('item_id')} name={r1.get('name')!r}")

        # Step 2: save bad LSL; expect client-side timeout (viewer hangs)
        t0 = time.monotonic()
        try:
            r2 = await s.call("object.content.save",
                              {"prim_id": prim_id, "item_id": r1["item_id"], "content": BAD_LSL},
                              timeout=30.0)
            print(f"step2 save responded after {time.monotonic() - t0:.1f}s: {r2}")
        except ViewerRPCError as e:
            print(f"step2 save TIMED OUT after {time.monotonic() - t0:.1f}s ({e.code}) "
                  f"— compile wait left dangling")

        # Step 3: create again right after the hang
        n2 = f"diag-after-{uuid.uuid4().hex[:6]}"
        t0 = time.monotonic()
        try:
            r3 = await s.call("object.item.create",
                              {"prim_id": prim_id, "name": n2, "type": "script", "vm": "lsl2"},
                              timeout=75.0)
            dt = time.monotonic() - t0
            resp_id = r3.get("item_id")
            print(f"step3 create {n2} after {dt:.1f}s: id={resp_id} name={r3.get('name')!r}")
            if resp_id in before:
                print(f"*** BUG REPRODUCED: response id is PRE-EXISTING item {before[resp_id]!r}")
        except ViewerRPCError as e:
            print(f"step3 create errored after {time.monotonic() - t0:.1f}s: [{e.code}] {e.message}")

        # What actually exists now? (final diff also catches items left by step 1 retries)
        await sleep(2.0)
        objs2 = await O.fetch_published(s, timeout=60.0)
        obj2 = O.find_object(objs2, "Object")
        new = [(it["item_id"], it.get("name")) for it in obj2.get("inventory", [])
               if it["item_id"] not in before]
        print(f"newly appeared: {new}")

        # Cleanup everything new
        for i, n in new:
            try:
                await s.call("object.item.delete", {"prim_id": prim_id, "item_id": i}, timeout=30.0)
                print(f"cleaned up {n!r}")
            except Exception as e:
                print(f"cleanup failed for {n!r}: {e}")
    finally:
        await s.close()

    # Scan the capture for anomalies
    print(f"\n--- wire scan ({len(frames)} frames, log at {LOG}) ---")
    seen: dict[tuple, float] = {}
    dupes = 0
    odd_ids: list[str] = []
    for ts, d, text in frames:
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            continue
        if d != "in":
            continue
        key = (msg.get("method"), str(msg.get("id")),
               json.dumps(msg.get("result"), sort_keys=True),
               json.dumps(msg.get("error"), sort_keys=True))
        if key in seen:
            dupes += 1
            print(f"DUPLICATE frame at +{ts - frames[0][0]:.1f}s: {text[:160]}")
        seen[key] = ts
        # Inbound messages with an id must be responses (result/error present).
        if msg.get("id") is not None and "result" not in msg and "error" not in msg:
            odd_ids.append(text[:160])
    print(f"duplicate inbound frames: {dupes}")
    print(f"inbound non-response frames carrying an id: {len(odd_ids)}")
    for t in odd_ids[:5]:
        print(f"  {t}")


anyio.run(main)
