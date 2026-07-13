# tests/test_wound_specials.py
# Task 3: special wounds — Damaged Item d20, Bloody Mess 3x3d6 (reroll 18),
# KO pending-save record. _pc/_wire duplicated from test_wound_application.py
# per the plan note.
import server
import wounds as w


def _pc(hp=5, max_hp=10, table="biological", wounds=None, carried=None, cap=13):
    return {"name": "Tester", "wound_table": table,
            "hp": {"current": hp, "max": max_hp},
            "abilities": {s: {"current": 2} for s in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
            "slot_capacity_total": cap, "wounds": list(wounds or []),
            "wounds_slots_used": sum(x.get("slots", 0) for x in (wounds or [])),
            "mystic_gifts": [], "codices": [],
            "inventory": {"carried": list(carried or [])}}


def _wire(monkeypatch, char):
    data = {"characters": {"tester": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    return data


def test_damaged_item_breaks_the_d20_slot(monkeypatch):
    char = _pc(hp=1, carried=[{"name": "Rifle", "slots": 2}, {"name": "Rope", "slots": 1}])
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 3 if (a, b) == (1, 20) else 1)
    out = server._character_take_damage("Tester", 2, "kinetic")    # -> -1 Damaged Item
    # slots expand in carried order: Rifle occupies 1-2, Rope occupies 3 -> Rope breaks
    assert char["inventory"]["carried"][1].get("broken") is True
    assert "Rope" in out and "unusable" in out.lower()


def test_damaged_item_lucky_miss_on_empty_slot(monkeypatch):
    char = _pc(hp=1, carried=[{"name": "Rope", "slots": 1}])
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15 if (a, b) == (1, 20) else 1)
    out = server._character_take_damage("Tester", 2, "kinetic")
    assert not char["inventory"]["carried"][0].get("broken")
    assert "empty" in out.lower() or "nothing" in out.lower()


def test_bloody_mess_applies_three_rolled_wounds(monkeypatch):
    char = _pc(hp=2)
    _wire(monkeypatch, char)
    rolls = iter([2, 2, 1,   1, 1, 1,   3, 2, 2])   # 3d6 sums: 5, 3, 7
    monkeypatch.setattr(server.random, "randint",
                        lambda a, b: next(rolls) if (a, b) == (1, 6) else 4)
    out = server._character_take_damage("Tester", 20, "kinetic")   # -> -18 Bloody Mess
    names = [r["name"] for r in char["wounds"]]
    assert "Bloody Mess" in names
    assert "Addling Wound" in names      # -5
    assert "Teeth Knocked Out" in names  # -3
    assert "Crippling Wound" in names    # -7
    assert "PASS" in out.upper() or "unconscious" in out.lower()


def test_bloody_mess_rerolls_nested_18(monkeypatch):
    char = _pc(hp=2)
    _wire(monkeypatch, char)
    rolls = iter([6, 6, 6,   2, 2, 1,   1, 1, 1,   3, 2, 2])  # first sum 18 -> reroll
    monkeypatch.setattr(server.random, "randint",
                        lambda a, b: next(rolls) if (a, b) == (1, 6) else 4)
    server._character_take_damage("Tester", 20, "kinetic")
    assert sum(1 for r in char["wounds"] if r["name"] == "Bloody Mess") == 1   # no nesting


def test_ko_record_carries_pending_save(monkeypatch):
    char = _pc(hp=4)
    _wire(monkeypatch, char)
    server._character_take_damage("Tester", 4, "kinetic")
    assert char["wounds"][0].get("pending_con_save") is True


def test_damaged_item_zero_slot_items_occupy_no_position(monkeypatch):
    # Zero-slot items match _calculate_slots geometry: they can't be struck and
    # don't shift later items. d20=1 must strike Rope, not the 0-slot token.
    char = _pc(hp=1, carried=[{"name": "Token", "slots": 0},
                              {"name": "Rope", "slots": 1}])
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server._character_take_damage("Tester", 2, "kinetic")          # -> -1 Damaged Item
    assert not char["inventory"]["carried"][0].get("broken")       # token untouchable
    assert char["inventory"]["carried"][1].get("broken") is True   # Rope at position 1


def test_bloody_mess_children_apply_mutations(monkeypatch):
    # Constant 3d6 rolls of 4 -> three sums of 12 -> three Cracked Skull children
    # (-d8 INT/-d8 PSY, 2 slots each). Ability dice go through SystemRandom
    # (not patchable), so assert structurally: records present, stats reduced.
    char = _pc(hp=2)
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    server._character_take_damage("Tester", 20, "kinetic")         # -> -18 Bloody Mess
    skulls = [r for r in char["wounds"] if r["name"] == "Cracked Skull"]
    assert len(skulls) == 3 and all(r["slots"] == 2 for r in skulls)
    assert char["wounds_slots_used"] == 6                          # parent 0 + 3x2
    assert char["abilities"]["INT"]["current"] < 2                 # mutations landed
    assert char["abilities"]["PSY"]["current"] < 2


def test_bloody_mess_emits_single_authoritative_must_drop(monkeypatch):
    # cap 13, gear 12; 6 wound slots -> room 7 -> drop 5. Children must not
    # print their own intermediate MUST DROP lines.
    char = _pc(hp=2, carried=[{"name": "Pack", "slots": 12}])
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    out = server._character_take_damage("Tester", 20, "kinetic")   # -> -18 Bloody Mess
    assert out.upper().count("MUST DROP") == 1
    assert "MUST DROP 5" in out.upper()
