"""Tests for combat reading derived wound effects — Wounds Task 5.

Covers (the five planned shapes from the 2026-06-09 wounds-application plan):
1. PC target with an unconscious wound record -> enemy attack AUTO-HITs (no d20 contest).
2. PC defender AV reduced by Synthskin Damaged av_penalty (derived, floor 0).
3. Blind PC attacker: ranged attack blocked naming the wound; melee proceeds
   with a 'DISADVANTAGE (blind)' instruction line (Iron Law 3: instruct, not roll).
4. Wound DIS-on-CON surfaces on the toxin CON-save prompt (rides the
   encumbrance-note pattern; PC saves are player-rolled).
5. E2E: enemy forced hit drops a PC below 0 -> wound record lands on the sheet
   and 'WOUND' appears in the output (pins the whole chain, no new code).

Setup adapted from tests/test_combat_attack.py (same monkeypatch idioms).
"""
import copy

import server
import engine_core


# ---------------------------------------------------------------------------
# Shared weapon / character fixtures (mirrors test_combat_attack.py)
# ---------------------------------------------------------------------------

_TRISKELE = {
    "name": "Triskele",
    "type": "exotica_weapon ranged",
    "damage": "3d8",
    "damage_type": "beam",
    "engine_tags": [],
    "primary": True,
}

_LETTER_OPENER = {
    "name": "Extradimensional Letter Opener",
    "type": "exotica_weapon",
    "damage": "d4",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": [],
    "range": "melee",
}


def _make_pc(name="Roscar", hp=23, max_hp=23, av=16, weapon=None, wounds=None,
             wound_table="biological"):
    return {
        "name": name,
        "hp": {"current": hp, "max": max_hp},
        "wound_table": wound_table,
        "av": {"base": av},
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 2, "base": 2},
        },
        "inventory": {"carried": [copy.deepcopy(weapon or _TRISKELE)]},
        "wounds": list(wounds or []),
        "special_traits": {},
    }


def _make_biological_enemy(hp=15, av=12, lvl=3):
    return {
        "hp": hp,
        "max_hp": hp,
        "av": av,
        "morale": 0,
        "lvl": lvl,
        "defeated": False,
        "fled": False,
        "resist_type": "Biological",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False,
        "attack_name": "Slash",
        "attack_damage": "d6",
        "attacks": [],
    }


def _base_isolate(monkeypatch, characters_fixture, enemies):
    """Inject minimal mocks for all wound-combat-integration tests."""
    monkeypatch.setattr(server, "_load_characters", lambda: (characters_fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)

    snapshot = {name: {"hp": data["hp"]["current"], "max_hp": data["hp"]["max"]}
                for name, data in characters_fixture["characters"].items()}
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {
            "enemies": dict(enemies),
            "party_snapshot": snapshot,
            "log": [],
        },
    )


# ---------------------------------------------------------------------------
# Shape 1: PC target unconscious -> AUTO-HIT, no d20 contest
# ---------------------------------------------------------------------------

def test_attack_on_unconscious_pc_auto_hits(monkeypatch):
    """An enemy attacks a PC carrying an unconscious wound record. The engine
    must skip the to-hit roll entirely (random.randint raises if touched for
    the d20) and report AUTO-HIT; damage still flows to the PC pipeline."""
    pc = _make_pc(name="Roscar", av=16,
                  wounds=[{"name": "Cracked Skull", "hp_threshold": -12,
                           "slots": 2, "effect": "Pass out.", "unconscious": True}])
    fixture = {"characters": {"Roscar": pc}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy()})

    # The to-hit d20 must NEVER be rolled — auto-hit skips the contest.
    def _no_roll(a, b):
        raise AssertionError("Engine must not roll a to-hit d20 vs an unconscious target")
    monkeypatch.setattr(server.random, "randint", _no_roll)
    # Damage dice avoid random.randint via the patched expr roller.
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 4)

    calls = []
    monkeypatch.setattr(server, "_character_take_damage",
                        lambda name, dmg, dtype: calls.append((name, dmg, dtype))
                        or f"{name}: 23 -> {23 - dmg}/23 HP (took {dmg} damage)")

    out = server._combat_attack("Raider (scarred)", None, "Roscar")

    assert "AUTO-HIT (target unconscious - all attacks automatically hit)" in out
    assert "HIT" in out
    assert calls, "Expected damage to be applied via _character_take_damage"
    assert calls[0][0] == "Roscar"
    assert calls[0][1] == 4


def test_attack_on_conscious_pc_still_contested(monkeypatch):
    """Control: a PC without an unconscious record still gets a to-hit contest
    (a low enemy roll misses)."""
    pc = _make_pc(name="Roscar", av=16, wounds=[])
    fixture = {"characters": {"Roscar": pc}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy()})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)  # 2+3=5 <= AV 16

    out = server._combat_attack("Raider (scarred)", None, "Roscar")

    assert "MISS" in out
    assert "AUTO-HIT" not in out


# ---------------------------------------------------------------------------
# Shape 2: PC defender AV reduced by Synthskin av_penalty (derived, floor 0)
# ---------------------------------------------------------------------------

def test_pc_defender_av_reduced_by_synthskin(monkeypatch):
    """A PC with an av_penalty=3 wound record defends at base AV - 3."""
    pc = _make_pc(name="Vex", av=16, wound_table="synthetic",
                  wounds=[{"name": "Synthskin Damaged", "hp_threshold": -9,
                           "slots": 2, "effect": "-d4 AV; suffer double damage",
                           "av_penalty": 3, "double_damage": True}])
    fixture = {"characters": {"Vex": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)

    assert server._defender_av("Vex") == 13


def test_pc_defender_av_floors_at_zero(monkeypatch):
    """The derived AV penalty can never push AV below 0."""
    pc = _make_pc(name="Vex", av=2, wound_table="synthetic",
                  wounds=[{"name": "Synthskin Damaged", "hp_threshold": -9,
                           "slots": 2, "effect": "-d4 AV; suffer double damage",
                           "av_penalty": 4, "double_damage": True}])
    fixture = {"characters": {"Vex": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)

    assert server._defender_av("Vex") == 0


def test_unwounded_pc_av_unchanged(monkeypatch):
    """Control: no wounds -> AV is the sheet base, untouched."""
    pc = _make_pc(name="Vex", av=16, wounds=[])
    fixture = {"characters": {"Vex": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)

    assert server._defender_av("Vex") == 16


def test_enemy_av_never_wound_penalized(monkeypatch):
    """Enemies resolve from active_combat and never read PC wound penalties."""
    monkeypatch.setattr(server, "_load_characters", lambda: ({"characters": {}}, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": {"Raider (scarred)": _make_biological_enemy(av=12)},
                         "party_snapshot": {}, "log": []})

    assert server._defender_av("Raider (scarred)") == 12


# ---------------------------------------------------------------------------
# Shape 3: blind PC attacker — ranged blocked, melee DIS-instructed
# ---------------------------------------------------------------------------

_BLIND_WOUND = {"name": "Vischip Disabled", "hp_threshold": -12, "slots": 3,
                "effect": "Blind: cannot make ranged attacks; melee attacks at DIS",
                "blind": True}


def test_blind_pc_ranged_attack_blocked(monkeypatch):
    """A blind PC attacker with a ranged weapon is blocked outright; the block
    names the blinding wound and no dice are rolled, no damage applied."""
    pc = _make_pc(name="Vex", weapon=_TRISKELE, wound_table="synthetic",
                  wounds=[_BLIND_WOUND])
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    def _no_roll(a, b):
        raise AssertionError("No dice may be rolled for a blocked blind ranged attack")
    monkeypatch.setattr(server.random, "randint", _no_roll)

    out = server._combat_attack("Vex", "Triskele", "Raider (scarred)")

    assert "BLOCKED" in out
    assert "Vischip Disabled" in out
    assert "blind" in out.lower()
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15


def test_blind_pc_melee_attack_proceeds_with_dis_note(monkeypatch):
    """A blind PC attacker in melee still attacks, but the output carries the
    DISADVANTAGE (blind) instruction line (engine instructs, never rerolls)."""
    pc = _make_pc(name="Vex", weapon=_LETTER_OPENER, wound_table="synthetic",
                  wounds=[_BLIND_WOUND])
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)  # 15+STR(1)=16 > 12
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Vex", "Letter Opener", "Raider (scarred)")

    assert "BLOCKED" not in out
    assert "HIT" in out
    assert "DISADVANTAGE (blind" in out
    assert "Vischip Disabled" in out


def test_sighted_pc_attack_has_no_blind_note(monkeypatch):
    """Control: no blind record -> no DIS note, ranged attack not blocked."""
    pc = _make_pc(name="Vex", weapon=_TRISKELE, wounds=[])
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Vex", "Triskele", "Raider (scarred)")

    assert "BLOCKED" not in out
    assert "DISADVANTAGE (blind" not in out
    assert "HIT" in out


# ---------------------------------------------------------------------------
# Shape 4: wound DIS surfaces on the toxin CON-save prompt
# ---------------------------------------------------------------------------

_STOMACH_WOUND = {"name": "Stomach Wound", "hp_threshold": -6, "slots": 1,
                  "effect": "DIS on CON saves", "dis_saves": ["CON"]}


def test_wound_dis_appears_on_con_save_prompt(monkeypatch):
    """A PC with Stomach Wound (DIS CON) hit by TOX: the player-facing CON-save
    prompt from _toxin_attack_reroute carries the DISADVANTAGE wound note."""
    pc = _make_pc(name="Roscar", wounds=[_STOMACH_WOUND])
    fixture = {"characters": {"Roscar": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)

    out = server._toxin_attack_reroute(attacker="Venom Crawler", target="Roscar",
                                       tox_die="d6", attacker_kind="enemy")

    assert "CON save" in out
    assert "DISADVANTAGE" in out
    assert "Stomach Wound" in out


def test_wound_dis_absent_without_matching_wound(monkeypatch):
    """Control: no DIS-CON wound -> the CON-save prompt has no wound note."""
    pc = _make_pc(name="Roscar", wounds=[])
    fixture = {"characters": {"Roscar": pc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)

    out = server._toxin_attack_reroute(attacker="Venom Crawler", target="Roscar",
                                       tox_die="d6", attacker_kind="enemy")

    assert "CON save" in out
    assert "DISADVANTAGE" not in out


def test_wound_save_note_helper_direct():
    """_wound_save_note: matching stat -> note naming the wound; other stat -> ''."""
    pc = _make_pc(name="Roscar", wounds=[_STOMACH_WOUND])
    note = server._wound_save_note(pc, "CON")
    assert "DISADVANTAGE" in note
    assert "Stomach Wound" in note
    assert server._wound_save_note(pc, "STR") == ""
    assert server._wound_save_note(_make_pc(name="X", wounds=[]), "CON") == ""


# ---------------------------------------------------------------------------
# Shape 5: E2E — enemy forced hit drops the PC below 0, wound chain fires
# ---------------------------------------------------------------------------

def test_e2e_enemy_hit_drops_pc_and_wound_applies(monkeypatch):
    """Full _combat_attack chain, no PC-damage mocks: forced enemy hit (d20=20,
    the T6 pattern) drops the PC from 3 HP below zero; the wound record must
    land on the sheet and 'WOUND' must appear in the output."""
    pc = _make_pc(name="Roscar", hp=3, max_hp=23, av=16, wounds=[])
    fixture = {"characters": {"Roscar": pc}}
    enemy = _make_biological_enemy(hp=20, av=12, lvl=3)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    # Forced hit: d20=20 (crit, always hits). Damage comes via _roll_stat_expr
    # (patched to 3 -> crit doubles to 6): HP 3 -> -3 => Teeth Knocked Out,
    # whose record needs no further random rolls.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Raider (scarred)", None, "Roscar")

    assert "HIT" in out
    assert "WOUND" in out
    sheet = fixture["characters"]["Roscar"]
    assert sheet["hp"]["current"] == -3
    assert sheet["wounds"], "Expected a wound record on the sheet"
    rec = sheet["wounds"][-1]
    assert rec["hp_threshold"] == -3
    assert rec["name"] == "Teeth Knocked Out"


def test_blind_pc_melee_dis_is_mechanical_engine_keeps_worse_die(monkeypatch):
    """When the engine owns the roll (non-Creenash PC), blind DIS rolls 2d20 and
    keeps the WORSE: 18 then 4 -> kept 4 -> 4+1=5 vs AV 12 -> MISS."""
    pc = _make_pc(name="Vex", weapon=_LETTER_OPENER, wound_table="synthetic",
                  wounds=[_BLIND_WOUND])
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    rolls = iter([18, 4])
    monkeypatch.setattr(server.random, "randint", lambda a, b: next(rolls))
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Vex", "Letter Opener", "Raider (scarred)")

    assert "MISS" in out
    assert "kept 4" in out                      # worse die kept, surfaced
    assert enemy["hp"] == 15                    # no damage on the miss
