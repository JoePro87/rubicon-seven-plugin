# tests/test_item_slots.py
import item_slots as isl


def test_hard_ceiling_constant():
    assert isl.HARD_CEILING == 20


def test_slot_cap_is_ten_plus_con():
    assert isl.slot_cap(3) == 13
    assert isl.slot_cap(0) == 10
    assert isl.slot_cap(3, bonus=2) == 15      # mutation (e.g. Kangaroo Pouch)
    assert isl.slot_cap(-1) == 9


def test_is_encumbered():
    assert isl.is_encumbered(used=14, cap=13) is True
    assert isl.is_encumbered(used=13, cap=13) is False   # at cap is NOT over
    assert isl.is_encumbered(used=5, cap=13) is False


def test_item_usage_die_reads_usage_die_then_ammo_alias():
    assert isl.item_usage_die({"usage_die": "Ud8"}) == "Ud8"
    assert isl.item_usage_die({"ammo": "Ud6"}) == "Ud6"          # weapon alias
    assert isl.item_usage_die({"usage_die": "Ud8", "ammo": "Ud6"}) == "Ud8"  # canonical wins
    assert isl.item_usage_die({"name": "Rope"}) is None


def test_item_is_depletable():
    assert isl.item_is_depletable({"usage_die": "Ud8"}) is True
    assert isl.item_is_depletable({"ammo": "Ud6"}) is True
    assert isl.item_is_depletable({"uses": 3}) is True
    assert isl.item_is_depletable({"uses": 0}) is True           # 0 still a discrete item
    assert isl.item_is_depletable({"uses": "1/day per INT"}) is False  # non-int -> DM-managed
    assert isl.item_is_depletable({"name": "Rope"}) is False


def test_depletable_label():
    assert isl.depletable_label({"name": "Blowtorch", "usage_die": "Ud8"}) == "Blowtorch (Ud8)"
    assert isl.depletable_label({"name": "Bolts", "ammo": "Ud20"}) == "Bolts (Ud20)"
    assert isl.depletable_label({"name": "Draught", "uses": 1}) == "Draught (x1)"
    assert isl.depletable_label({"name": "Spent", "uses": 0}) == "Spent (x0)"
    assert isl.depletable_label({"name": "Rope"}) is None


def test_parse_slots_uses_usage_die():
    r = isl.parse_slots_uses("1/Ud8")
    assert r == {"slots": 1, "kind": "usage_die", "usage_die": "Ud8", "uses": None}


def test_parse_slots_uses_discrete():
    assert isl.parse_slots_uses("1/x6 uses") == {"slots": 1, "kind": "discrete", "usage_die": None, "uses": 6}
    assert isl.parse_slots_uses("1/x1 use") == {"slots": 1, "kind": "discrete", "usage_die": None, "uses": 1}


def test_parse_slots_uses_slots_only_and_unlimited():
    assert isl.parse_slots_uses("3 slots")["slots"] == 3
    assert isl.parse_slots_uses("3 slots")["kind"] == "none"
    assert isl.parse_slots_uses("1/Unlimited")["kind"] == "none"
    assert isl.parse_slots_uses("2/Unlimited") == {"slots": 2, "kind": "none", "usage_die": None, "uses": None}


def test_parse_slots_uses_pointer_and_garbage_default_safe():
    assert isl.parse_slots_uses("See p.200") == {"slots": 1, "kind": "none", "usage_die": None, "uses": None}
    assert isl.parse_slots_uses("") == {"slots": 1, "kind": "none", "usage_die": None, "uses": None}
    assert isl.parse_slots_uses(None) == {"slots": 1, "kind": "none", "usage_die": None, "uses": None}
