# tests/test_slots_uses_parse.py
import server


def test_stamp_slots_uses_usage_die():
    item = {"name": "Oneiric Bridge", "slots_uses": "1/Ud8"}
    server._stamp_slots_uses(item)
    assert item["slots"] == 1
    assert item["usage_die"] == "Ud8"
    assert item["usage_max"] == "Ud8"
    assert "uses" not in item


def test_stamp_slots_uses_discrete():
    item = {"name": "C-Foam Puddings", "slots_uses": "1/x6 uses"}
    server._stamp_slots_uses(item)
    assert item["uses"] == 6 and item["uses_max"] == 6
    assert "usage_die" not in item


def test_stamp_slots_uses_unlimited_sets_slots_only():
    item = {"name": "Ansible", "slots_uses": "1/Unlimited"}
    server._stamp_slots_uses(item)
    assert item["slots"] == 1
    assert "usage_die" not in item and "uses" not in item


def test_stamp_multi_slot():
    item = {"name": "Mirror Armour", "slots_uses": "3 slots"}
    server._stamp_slots_uses(item)
    assert item["slots"] == 3


def test_stamp_pointer_sets_slots_only():
    item = {"name": "Exotic Melee Weapon", "slots_uses": "See p.200"}
    server._stamp_slots_uses(item)
    assert item["slots"] == 1
    assert "usage_die" not in item and "uses" not in item
