# tests/test_wound_application.py
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


def test_landing_exactly_at_zero_triggers_knocked_out(monkeypatch):
    char = _pc(hp=3)
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 3, "kinetic")
    assert "Knocked Out" in out
    assert any(r.get("special") == "knocked_out" for r in char["wounds"])
    assert "CON save" in out                       # the prompt is pushed


def test_drop_below_zero_applies_wound_at_landing_hp(monkeypatch):
    char = _pc(hp=2)
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 9, "kinetic")    # -> -7
    assert "Crippling Wound" in out
    assert char["wounds"][0]["hp_threshold"] == -7
    assert char["wounds_slots_used"] == 1


def test_damage_while_already_down_applies_again_THE_BUG(monkeypatch):
    char = _pc(hp=-3, wounds=[w.roll_wound_record(-3, w.BIOLOGICAL_WOUNDS[-3])])
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 4, "kinetic")    # -3 -> -7
    assert "Crippling Wound" in out
    assert len(char["wounds"]) == 2                # APPLIED, not just printed


def test_clamp_below_minus_20_is_fatal(monkeypatch):
    char = _pc(hp=-10)
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 50, "kinetic")
    assert "DEAD" in out.upper()
    # the clamp applies exactly one wound: the -20 row (old code looped thresholds)
    assert len(char["wounds"]) == 1
    assert char["wounds"][0]["hp_threshold"] == -20


def test_duplicates_stack_slots(monkeypatch):
    char = _pc(hp=-6, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    _wire(monkeypatch, char)
    server._character_take_damage("Tester", 1, "kinetic")          # -> -7 again
    assert sum(1 for r in char["wounds"] if r["name"] == "Crippling Wound") == 2
    assert char["wounds_slots_used"] == 2


def test_deaths_door_makes_further_damage_lethal(monkeypatch):
    # HP healed back ABOVE the fatal range while the wound is active — the exact
    # case the rule exists for: lethality comes from the wound, not the HP math.
    # (At hp=-19 the old code passed this by accident via plain HP clamping.)
    dd = w.roll_wound_record(-19, w.BIOLOGICAL_WOUNDS[-19])
    char = _pc(hp=3, wounds=[dd])
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 1, "kinetic")
    assert "LETHAL" in out.upper() and "DEAD" in out.upper()
    # death is self-representing in state, not just narrated
    assert char["hp"]["current"] <= -20


def test_personality_nexus_reroll_resets_current_and_base(monkeypatch):
    # Synthetic -11: reroll INT/PSY/EGO (3d6, lowest die = bonus). The reroll IS
    # the new score — base must move with current or Long Rest un-rerolls it.
    char = _pc(hp=2, table="synthetic")
    for s in char["abilities"]:
        char["abilities"][s]["base"] = 5
        char["abilities"][s]["current"] = 5
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server._character_take_damage("Tester", 13, "kinetic")        # -> -11
    for s in ("INT", "PSY", "EGO"):
        assert char["abilities"][s]["current"] == 1
        assert char["abilities"][s]["base"] == 1
    for s in ("STR", "DEX", "CON"):
        assert char["abilities"][s]["current"] == 5               # untouched


def test_synthskin_double_damage_is_derived(monkeypatch):
    sk = w.roll_wound_record(-9, w.SYNTHETIC_WOUNDS[-9], rng=lambda a, b: 2)
    char = _pc(hp=8, table="synthetic", wounds=[sk])
    _wire(monkeypatch, char)
    server._character_take_damage("Tester", 3, "kinetic")
    assert char["hp"]["current"] == 8 - 6          # doubled by the active wound


def test_forced_drop_surfaced_when_wound_evicts_gear(monkeypatch):
    # cap 13, gear 12; a 2-slot wound leaves room 11 -> must drop 1
    char = _pc(hp=2, carried=[{"name": "Pack", "slots": 12}])
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 12, "kinetic")   # -> -10, 2 slots
    assert "MUST DROP 1" in out.upper()


def test_no_wound_on_nonlethal_damage(monkeypatch):
    char = _pc(hp=5)
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 2, "kinetic")
    assert char["wounds"] == [] and "WOUND" not in out


def test_pass_out_line_pushes_wake_call(monkeypatch):
    # Table pass-outs (the common unconsciousness) must push the wake call
    # in-band at application, or a fresh DM narrates the wake-up and leaves
    # all-attacks-auto-hit live on the sheet (DoD push rule).
    char = _pc(hp=2)
    _wire(monkeypatch, char)
    out = server._character_take_damage("Tester", 14, "kinetic")   # -> -12 Cracked Skull
    assert "PASSES OUT" in out
    assert 'affliction(kind="wound", action="wake", character="Tester")' in out
