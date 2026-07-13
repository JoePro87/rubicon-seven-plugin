# tests/test_toxin_wound_integration.py
"""
Regression: PC toxin tick must flow through the unified HP<=0 wound trigger
(_character_take_damage), not the old bare mutation + _check_death_conditions.

Test plan
---------
T1  PC at low HP, toxin tick drops to <=0  -> wound record on sheet, output mentions wound
T2  PC tick leaving HP > 0                 -> NO wound, die still ticks/steps down
T3  Enemy tick path                        -> byte-identical behaviour to before (guard)
T4  Persistence: after full round-advance, sheet carries BOTH wound AND correct toxin state
T5  Toxin die step-down still happens (damage 1-2) even when PC drops <=0
T6  PC already at Death's Door, toxin tick -> lethal path fires
"""

import server
import wounds as _wnd

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pc(hp=5, max_hp=10, toxin_die=None, wounds=None, cap=13):
    c = {
        "name": "Ferris",
        "wound_table": "biological",
        "hp": {"current": hp, "max": max_hp},
        "abilities": {s: {"current": 2} for s in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
        "slot_capacity_total": cap,
        "wounds": list(wounds or []),
        "wounds_slots_used": sum(r.get("slots", 0) for r in (wounds or [])),
        "mystic_gifts": [], "codices": [],
        "inventory": {"carried": []},
    }
    if toxin_die:
        c["toxin_die"] = toxin_die
    return c


def _wire(monkeypatch, char):
    """Stub load/save so tests run in-process without hitting the filesystem."""
    saves = []
    data = {"characters": {"ferris": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda *a, **k: saves.append(True))
    return data, saves


# ---------------------------------------------------------------------------
# T1: PC drops to <=0 from toxin tick -> wound applied
# ---------------------------------------------------------------------------

def test_toxin_tick_drops_pc_to_zero_applies_wound(monkeypatch):
    """PC with 3 HP and d6 toxin die; tick rolls 4+ -> <=0 -> wound record exists."""
    char = _pc(hp=3, max_hp=10, toxin_die="d6")
    _wire(monkeypatch, char)
    handle = {"kind": "pc", "char": char, "key": "ferris",
              "data": {"characters": {"ferris": char}}}
    # Force damage > HP so we definitely drop to <=0
    line = server._toxin_tick(handle, rng=lambda a, b: 6)   # d6 rolls 6 -> HP 3-6 = -3
    assert char["wounds"], f"Expected wound on sheet after drop; got: {char['wounds']}"
    assert line is not None
    assert "WOUND" in line.upper(), f"Expected wound mention in output; got: {line!r}"
    # HP reflects the drop
    assert char["hp"]["current"] <= 0


# ---------------------------------------------------------------------------
# T2: Tick that leaves HP > 0 -> NO wound
# ---------------------------------------------------------------------------

def test_toxin_tick_above_zero_no_wound(monkeypatch):
    """PC with 10 HP and d4 toxin die; tick rolls 2 -> 8 HP -> no wound."""
    char = _pc(hp=10, max_hp=10, toxin_die="d4")
    _wire(monkeypatch, char)
    handle = {"kind": "pc", "char": char, "key": "ferris",
              "data": {"characters": {"ferris": char}}}
    # Force damage = 2 -> HP goes to 8 (safe) AND die steps down (dmg in 1-2)
    line = server._toxin_tick(handle, rng=lambda a, b: 2)
    assert not char["wounds"], f"Expected NO wound; got: {char['wounds']}"
    assert char["hp"]["current"] == 8
    # Die should have stepped down (rng returned 2 which is in step-down range)
    assert char.get("toxin_die") != "d4" or char.get("toxin_die") == "cured"
    assert line is not None
    assert "Toxin Die" in line


# ---------------------------------------------------------------------------
# T3: Enemy tick path unchanged
# ---------------------------------------------------------------------------

def test_enemy_tick_path_unchanged(monkeypatch):
    """Enemy tick still just subtracts HP; no wound logic (enemies have no wound table)."""
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    enemy = {"hp": 8, "max_hp": 10, "toxin_die": "d6", "defeated": False, "fled": False}
    handle = {"kind": "enemy", "enemy": enemy, "key": "Crawler (a)"}
    line = server._toxin_tick(handle, rng=lambda a, b: 5)   # dmg=5, hp 8->3
    assert enemy["hp"] == 3
    assert "wounds" not in enemy
    assert "Toxin Die" in line


# ---------------------------------------------------------------------------
# T4: Persistence — round advance leaves wound AND toxin die on the sheet
# ---------------------------------------------------------------------------

def test_round_advance_persistence_wound_and_toxin_state(monkeypatch):
    """
    Full _check_round_advance flow:
    - PC has toxin_die and low HP
    - Tick drops HP <=0 -> wound applied in-memory
    - _toxin_set writes toxin_die back to sheet
    - Both wound and toxin state survive (no lost update)
    """
    char = _pc(hp=2, max_hp=10, toxin_die="d8")
    data = {"characters": {"ferris": char}}

    saved_chars = {}

    def fake_save(char_id, char_data, d=None):
        # Capture each save with a snapshot so we can check the LAST write
        import copy
        saved_chars[char_id] = copy.deepcopy(char_data)

    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", fake_save)
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)

    # Force the toxin damage roll = 8 (drops HP 2-8 = -6, definitely <=0).
    # NOTE: must patch _dc.roll, NOT random.randint -- _toxin_tick's default
    # rng=random.randint is bound at definition time, so patching the module
    # attribute after import never reaches a tick invoked without rng=.
    monkeypatch.setattr(server._dc, "roll", lambda die, rng=None: 8)

    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1, "initiative": "pcs",
        "pcs_acted": True, "enemies_acted": True, "morale_checked": False,
        "party_snapshot": {"ferris": {"hp": 2, "max_hp": 10}},
        "enemies": {},   # no enemies, so we don't hit the all-down path
        "log": [],
    })

    server._check_round_advance()

    # The final saved state for "ferris" must have:
    assert "ferris" in saved_chars, "Sheet was never saved during round advance"
    sheet = saved_chars["ferris"]
    assert sheet["wounds"], f"Expected wound on saved sheet; got: {sheet.get('wounds')}"
    # roll=8 is outside the 1-2 deplete range, so the die must NOT step down --
    # and crucially must NOT be lost by the wound write (the lost-update net).
    assert sheet.get("toxin_die") == "d8", (
        f"Expected toxin_die 'd8' preserved on saved sheet; got {sheet.get('toxin_die')!r}")
    # HP must reflect the drop
    assert sheet["hp"]["current"] <= 0, f"Expected HP <=0 in saved sheet; got {sheet['hp']['current']}"


# ---------------------------------------------------------------------------
# T5: Die step-down still happens on damage 1-2 even when PC drops <=0
# ---------------------------------------------------------------------------

def test_toxin_die_steps_down_even_when_pc_drops(monkeypatch):
    """d4 rolls 1 -> HP drops to <=0 AND die steps down (both side-effects fire)."""
    char = _pc(hp=1, max_hp=10, toxin_die="d4")
    _wire(monkeypatch, char)
    handle = {"kind": "pc", "char": char, "key": "ferris",
              "data": {"characters": {"ferris": char}}}
    # Damage = 1 -> step-down (1-2 range) AND hp 1-1=0 which is <=0 -> wound
    line = server._toxin_tick(handle, rng=lambda a, b: 1)
    # Wound was applied (hp 0 triggers the unified path)
    assert char["wounds"], f"Expected wound; got {char['wounds']}"
    # Die stepped down (d4 -> d2 or cured)
    assert char.get("toxin_die") != "d4", (
        f"Expected die to step down from d4; got {char.get('toxin_die')!r}")
    assert line is not None


# ---------------------------------------------------------------------------
# T6: Death's Door PC hit by toxin tick -> lethal path (snap HP <=−20, dead message)
# ---------------------------------------------------------------------------

def test_toxin_tick_deaths_door_is_lethal(monkeypatch):
    """PC at Death's Door (has DD wound, HP positive after heal) hit by toxin -> instant death."""
    dd_wound = _wnd.roll_wound_record(-19, _wnd.BIOLOGICAL_WOUNDS[-19])
    char = _pc(hp=4, max_hp=10, toxin_die="d4", wounds=[dd_wound])
    _wire(monkeypatch, char)
    handle = {"kind": "pc", "char": char, "key": "ferris",
              "data": {"characters": {"ferris": char}}}
    # Any damage amount (roll 3) triggers Death's Door lethality
    line = server._toxin_tick(handle, rng=lambda a, b: 3)
    assert "DEAD" in (line or "").upper() or "LETHAL" in (line or "").upper(), (
        f"Expected lethal/dead message for Death's Door PC; got: {line!r}")
    assert char["hp"]["current"] <= -20, (
        f"Expected HP snapped to <=-20 at Death's Door; got {char['hp']['current']}")


# ---------------------------------------------------------------------------
# T7 (I1): Synthskin Damaged doubles toxin tick damage (book rule via unified path)
# ---------------------------------------------------------------------------

def test_synthskin_damaged_doubles_toxin_tick(monkeypatch):
    """A PC with Synthskin Damaged (double_damage) takes 2x the tick roll.
    Pre-refactor the inlined tick path skipped this -- half the book damage."""
    ss_wound = _wnd.roll_wound_record(-9, _wnd.SYNTHETIC_WOUNDS[-9])
    assert ss_wound.get("double_damage"), "fixture sanity: Synthskin row carries the flag"
    char = _pc(hp=10, max_hp=10, toxin_die="d4", wounds=[ss_wound])
    _wire(monkeypatch, char)
    handle = {"kind": "pc", "char": char, "key": "ferris",
              "data": {"characters": {"ferris": char}}}
    line = server._toxin_tick(handle, rng=lambda a, b: 2)   # roll 2 -> doubled to 4
    assert char["hp"]["current"] == 6, (
        f"Expected HP 10-4=6 (roll 2 doubled by Synthskin); got {char['hp']['current']}")
    assert "DOUBLED" in line.upper(), f"Expected doubling note in output; got: {line!r}"
    # Depletion keys off the RAW roll (2 -> step-down), not the doubled damage
    assert char.get("toxin_die") != "d4", (
        f"Expected step-down on raw roll 2; got {char.get('toxin_die')!r}")


# ---------------------------------------------------------------------------
# T8 (M1): dispatch-path tick — toxin(action="tick") saves the wound
# ---------------------------------------------------------------------------

def test_dispatch_tick_low_hp_pc_saves_wound(monkeypatch):
    """toxin(action='tick') via _toxin_dispatch on a low-HP PC: the saved
    payload carries the wound (full resolve -> tick -> save plumbing)."""
    import copy
    char = _pc(hp=2, max_hp=10, toxin_die="d6")
    data = {"characters": {"ferris": char}}
    saved = {}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: saved.update({k: copy.deepcopy(c)}))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    # Pin damage at the dice-chain layer (the tick's default rng is bound at
    # definition time, so patching random.randint would silently miss it).
    monkeypatch.setattr(server._dc, "roll", lambda die, rng=None: 6)  # HP 2 -> -4

    out = server._toxin_dispatch("tick", target="ferris")

    assert "WOUND" in out.upper(), f"Expected wound in dispatch output; got: {out!r}"
    assert saved.get("ferris", {}).get("wounds"), (
        f"Expected wound on the SAVED payload; got: {saved.get('ferris', {}).get('wounds')}")
    assert saved["ferris"]["hp"]["current"] <= 0
