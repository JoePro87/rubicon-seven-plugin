# tests/test_encumbrance.py
import server
import item_slots as isl


def _char(carried_slots=0, wounds=0, capacity=13, gifts=0, codices=0):
    return {
        "name": "Tester",
        "slot_capacity_total": capacity,
        "wounds_slots_used": wounds,
        "mystic_gifts": [{} for _ in range(gifts)],
        "codices": [{} for _ in range(codices)],
        "inventory": {"carried": [{"name": "x", "slots": carried_slots}] if carried_slots else []},
    }


def test_calculate_slots_exposes_encumbered_flag():
    assert server._calculate_slots(_char(carried_slots=5))["encumbered"] is False
    assert server._calculate_slots(_char(carried_slots=14))["encumbered"] is True
    assert server._calculate_slots(_char(carried_slots=13))["encumbered"] is False  # at cap


def test_wounds_push_into_encumbered():
    # 10 gear + 4 wound-slots = 14 > cap 13 -> encumbered, even though gear alone fits
    c = _char(carried_slots=10, wounds=4)
    s = server._calculate_slots(c)
    assert s["encumbered"] is True


def test_refresh_slot_fields_writes_stored_fields():
    c = _char(carried_slots=5, wounds=2)
    server._refresh_slot_fields(c)
    assert c["slots_used"] == 5
    assert c["slots_from_wounds"] == 2
    assert c["effective_slots_free"] == 13 - 5 - 2
    assert c["encumbered"] is False


def test_add_over_cap_is_allowed_and_flags_encumbered(monkeypatch):
    # A char already at 13/13 picks up a 1-slot item -> ALLOWED, now encumbered (14/13)
    data = {"characters": {"tester": _char(carried_slots=13)}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_characters", lambda d: None)
    res = server._apply_inventory_changes(
        [{"character": "Tester", "action": "add", "item": {"name": "Torch", "slots": 1}}], day=1)
    joined = " ".join(res)
    assert "ENCUMBERED" in joined
    assert "REJECTED" not in joined
    assert any(i.get("name") == "Torch" for i in data["characters"]["tester"]["inventory"]["carried"])
    assert data["characters"]["tester"]["encumbered"] is True


def test_add_beyond_hard_ceiling_is_rejected(monkeypatch):
    data = {"characters": {"tester": _char(carried_slots=20)}}  # already at hard 20
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_characters", lambda d: None)
    res = server._apply_inventory_changes(
        [{"character": "Tester", "action": "add", "item": {"name": "Anvil", "slots": 1}}], day=1)
    assert any("REJECTED" in r and "20" in r for r in res)
    assert not any(i.get("name") == "Anvil" for i in data["characters"]["tester"]["inventory"]["carried"])


def test_remove_accepts_nested_item_id_shape(monkeypatch):
    # Swapping armour in one call: remove via the nested {"item":{"id":...}} shape
    # (mirrors 'add') must actually remove. It used to silently no-op while the
    # paired add succeeded -> both items left, slots overfull.
    c = _char()
    c["inventory"]["carried"] = [{"id": "indigo_brigandine", "name": "Indigo Brigandine", "slots": 3}]
    data = {"characters": {"tester": c}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_characters", lambda d: None)
    res = server._apply_inventory_changes([
        {"character": "Tester", "action": "remove", "item": {"id": "indigo_brigandine"}},
        {"character": "Tester", "action": "add",
         "item": {"id": "occult_cuirass", "name": "Occult Cuirass", "slots": 4}},
    ], day=1)
    carried = data["characters"]["tester"]["inventory"]["carried"]
    ids = [i.get("id") for i in carried]
    assert "indigo_brigandine" not in ids  # actually removed, not left behind
    assert "occult_cuirass" in ids
    assert len(carried) == 1  # swapped, not duplicated
    assert any("REMOVED" in r for r in res)


def test_remove_unresolvable_id_warns_and_no_ops(monkeypatch):
    # No item_id AND no item.id -> explicit skip, nothing removed (non-fatal).
    c = _char()
    c["inventory"]["carried"] = [{"id": "torch", "name": "Torch", "slots": 1}]
    data = {"characters": {"tester": c}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_characters", lambda d: None)
    res = server._apply_inventory_changes(
        [{"character": "Tester", "action": "remove"}], day=1)
    assert any("SKIP" in r and "item_id" in r for r in res)
    assert len(data["characters"]["tester"]["inventory"]["carried"]) == 1  # untouched
