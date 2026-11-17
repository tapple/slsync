"""Tests for object-tree lookup and address resolution (no viewer needed)."""

import uuid

import pytest

from ridercli import objects as O


def _uuid(tag: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, tag))


ROOT_ID = _uuid("root")
CHILD_ID = _uuid("child1")
ITEM_A = _uuid("item-a")
ITEM_B = _uuid("item-b")
ITEM_C = _uuid("item-c")

OBJECTS = [
    {
        "object_id": ROOT_ID,
        "object_name": "Avatar",
        "region": "Test Region",
        "owner_id": _uuid("owner"),
        "can_save_back": False,
        "inventory": [
            {"item_id": ITEM_A, "name": "Tavatar Plugin", "type": "script", "vm": "lsl2", "running": True},
            {"item_id": ITEM_B, "name": "Notes", "type": "notecard"},
        ],
        "linked_objects": [
            {
                "link_id": CHILD_ID,
                "link_number": 2,
                "link_name": "Bone",
                "inventory": [
                    {"item_id": ITEM_C, "name": "Bone Script", "type": "script", "vm": "luau", "running": False},
                ],
            }
        ],
    },
    {
        "object_id": _uuid("other"),
        "object_name": "Other Thing",
        "inventory": [
            {"item_id": _uuid("dup-a"), "name": "Notes", "type": "notecard"},
        ],
    },
]


def test_find_object_by_uuid_and_name():
    assert O.find_object(OBJECTS, ROOT_ID)["object_name"] == "Avatar"
    assert O.find_object(OBJECTS, "avatar")["object_id"] == ROOT_ID  # case-insensitive
    with pytest.raises(O.AddressError):
        O.find_object(OBJECTS, "nope")
    with pytest.raises(O.AddressError):
        O.find_object([], "Avatar")  # nothing explored


def test_find_prim():
    assert O.find_prim(OBJECTS[0], None)["id"] == ROOT_ID
    assert O.find_prim(OBJECTS[0], CHILD_ID)["name"] == "Bone"
    assert O.find_prim(OBJECTS[0], "bone")["id"] == CHILD_ID
    with pytest.raises(O.AddressError):
        O.find_prim(OBJECTS[0], "ghost")


def test_find_item():
    inv = OBJECTS[0]["inventory"]
    assert O.find_item(inv, ITEM_A)["name"] == "Tavatar Plugin"
    assert O.find_item(inv, "notes")["type"] == "notecard"
    with pytest.raises(O.AddressError):
        O.find_item(inv, "missing")


def test_resolve_bare_unique_item():
    _, prim, item = O.resolve_item(OBJECTS, ITEM_A)
    assert item["name"] == "Tavatar Plugin"
    assert prim["id"] == ROOT_ID


def test_resolve_ambiguous_bare_item():
    # "Notes" exists in two objects -> ambiguous
    with pytest.raises(O.AddressError, match="ambiguous"):
        O.resolve_item(OBJECTS, "Notes")


def test_resolve_canonical_uuid_pair():
    obj, prim, item = O.resolve_item(OBJECTS, f"{CHILD_ID}:{ITEM_C}")
    assert obj["object_id"] == ROOT_ID
    assert prim["id"] == CHILD_ID
    assert item["name"] == "Bone Script"


def test_resolve_name_path():
    obj, prim, item = O.resolve_item(OBJECTS, "Avatar/Bone/Bone Script")
    assert prim["id"] == CHILD_ID
    assert item["item_id"] == ITEM_C

    obj, prim, item = O.resolve_item(OBJECTS, "avatar/tavatar plugin")
    assert item["name"] == "Tavatar Plugin"


def test_resolve_object_uuid_child_name():
    _, prim, item = O.resolve_item(OBJECTS, f"{ROOT_ID}/bone/{ITEM_C}")
    assert item["item_id"] == ITEM_C


def test_display_name():
    assert (
        O._display_name({"name": "X", "type": "script", "vm": "lsl2"}) == "X.lsl"
    )
    assert (
        O._display_name({"name": "X", "type": "script", "vm": "luau"}) == "X.luau"
    )
    assert (
        O._display_name({"name": "my card.txt", "type": "notecard"}) == "my card.txt"
    )


def test_render_object_contains_items():
    text = O.render_object(OBJECTS[0])
    assert "Avatar" in text
    assert "Tavatar Plugin" in text
    assert "Bone Script" in text
    assert "child prim: Bone" in text
