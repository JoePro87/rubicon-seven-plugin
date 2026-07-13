"""PC generation Task 2 - character(action="create"/"create_finalize") (CH p.5-6).

Two-step formal method: step 1 rolls six abilities IN ORDER (3d6, bonus =
LOWEST die) + a d10 ancestry suggestion and stashes the pending rolls; step 2
applies the player's swap/ancestry/take5 choices and WRITES a real split sheet.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


@pytest.fixture
def roster(monkeypatch):
    """One existing PC (duplicate-guard target); day 100; saves captured."""
    data = {
        "characters": {
            "tesslyn": {"name": "Tesslyn", "species": "Neobloom",
                        "hp": {"current": 17, "max": 17}},
        },
        "meta": {"campaign_day": 100},
    }
    saved = []
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda key, char, d=None: saved.append((key, char)))
    monkeypatch.setattr(server, "_save_game_state", lambda: None)
    server.GAME_STATE.pop("world_tick", None)
    yield {"data": data, "saved": saved}
    server.GAME_STATE.pop("world_tick", None)


def _seed_pending(abilities=None, day=100):
    server.GAME_STATE.setdefault("world_tick", {})["pc_create_pending"] = {
        "abilities": abilities or {"STR": 1, "DEX": 2, "CON": 3,
                                   "INT": 4, "PSY": 5, "EGO": 6},
        "day": day,
    }


# --- step 1: create -----------------------------------------------------------

def test_create_rolls_six_abilities_in_order_lowest_die(roster, monkeypatch):
    # 18 d6 faces (six abilities in order) then the d10 ancestry suggestion.
    seq = iter([4, 2, 6,  1, 1, 5,  3, 3, 3,  6, 6, 2,  5, 1, 2,  4, 4, 6,  7])
    monkeypatch.setattr(server.random, "randint", lambda a, b: next(seq))
    out = server.character(action="create")
    pend = server.GAME_STATE["world_tick"]["pc_create_pending"]
    assert pend["abilities"] == {"STR": 2, "DEX": 1, "CON": 3,
                                 "INT": 2, "PSY": 1, "EGO": 4}
    # the report shows the abilities IN ORDER, with the raw dice
    idx = [out.index(ab) for ab in ["STR", "DEX", "CON", "INT", "PSY", "EGO"]]
    assert idx == sorted(idx)
    assert "[4, 2, 6]" in out
    assert "faa-nomad" in out  # d10=7 suggestion


def test_create_stashes_pending_and_pushes_finalize(roster, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)
    out = server.character(action="create")
    pend = server.GAME_STATE["world_tick"]["pc_create_pending"]
    assert pend["day"] == 100
    assert sorted(pend["abilities"]) == ["CON", "DEX", "EGO", "INT", "PSY", "STR"]
    assert 'character(action="create_finalize"' in out
    assert 'ancestry="cacogen"' in out  # d10=2 prefilled
    assert "take5=False" in out
    assert "swap" in out.lower()  # the swap rule is surfaced


# --- step 2: finalize guards --------------------------------------------------

def test_finalize_without_pending_rejected(roster):
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin")
    assert "No pending" in out
    assert 'character(action="create")' in out
    assert roster["saved"] == []


def test_finalize_duplicate_name_rejected(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out = server.character(action="create_finalize", name="Tesslyn",
                           ancestry="true-kin")
    assert "REJECTED" in out
    assert roster["saved"] == []
    # guard failures keep the stash so the player can retry
    assert "pc_create_pending" in server.GAME_STATE["world_tick"]


def test_finalize_clears_stash(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out1 = server.character(action="create_finalize", name="Zara",
                            ancestry="true-kin")
    assert "REJECTED" not in out1
    assert "pc_create_pending" not in server.GAME_STATE.get("world_tick", {})
    out2 = server.character(action="create_finalize", name="Borf",
                            ancestry="true-kin")
    assert "No pending" in out2


# --- step 2: mechanics --------------------------------------------------------

def test_finalize_applies_swap(roster, monkeypatch):
    _seed_pending()  # STR 1 ... PSY 5
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin", swap="STR,PSY")
    key, char = roster["saved"][-1]
    assert char["abilities"]["STR"] == {"current": 5, "base": 5}
    assert char["abilities"]["PSY"] == {"current": 1, "base": 1}
    assert "STR" in out and "PSY" in out


def test_finalize_invalid_swap_rejected(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin", swap="STR,WIS")
    assert "swap" in out.lower()
    assert roster["saved"] == []


def test_finalize_take5_hp(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 3)
    server.character(action="create_finalize", name="Zara",
                     ancestry="true-kin", take5=True)
    key, char = roster["saved"][-1]
    assert char["hp"] == {"current": 5, "max": 5}


def test_lithling_hp_override_10d8(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    out = server.character(action="create_finalize", name="Okenit",
                           ancestry="lithling", take5=True)
    key, char = roster["saved"][-1]
    # the Inevitable hook overrides BOTH the d8 and take5: 10d8 of forced 4s
    assert char["hp"] == {"current": 40, "max": 40}
    assert "never" in char["physiology"].lower()  # never healable, on the sheet
    assert "10d8" in out
    # Crystalline Flesh: base AV 10 + Level; no eating or drinking
    assert char["av"]["base"] == 11
    assert char["survival"] == {"needs_water": False, "needs_food": False}
    import survival
    assert survival.daily_needs(char) == {"water": 0, "food": 0}
    # Mineral kind: biological wound table used DELIBERATELY (no mineral table)
    assert char["wound_table"] == "biological"
    assert "mineral wound table" in char["physiology"].lower()


def test_neobloom_starting_bloomboon_at_creation(roster, monkeypatch):
    # CH p.049: a Neobloom "begins play with one Bloomboon, rolled d20". The
    # engine must roll + stamp exactly one at creation (was a gap - none rolled).
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    out = server.character(action="create_finalize", name="Bloomwood",
                           ancestry="neobloom")
    key, char = roster["saved"][-1]
    bbs = char.get("bloomboons", [])
    assert len(bbs) == 1, "Neobloom must start with exactly one Bloomboon"
    assert "creation" in bbs[0]["source"].lower()
    assert bbs[0]["name"] and bbs[0]["name"] != "Unknown"
    assert "Starting Bloomboon" in out  # surfaced in the creation report


def test_non_neobloom_gets_no_starting_bloomboon(roster, monkeypatch):
    # The creation Bloomboon is Neobloom-only; no other ancestry gets one.
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    server.character(action="create_finalize", name="Zara", ancestry="true-kin")
    key, char = roster["saved"][-1]
    assert char.get("bloomboons", []) == []


def test_finalize_writes_loadable_sheet(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out = server.character(action="create_finalize", name="Zara Vex",
                           ancestry="true-kin")
    key, char = roster["saved"][-1]
    assert key == "zara_vex"  # valid filename slug
    # round-trips through the loader's lookup by BOTH key and display name
    data2 = {"characters": {key: char}}
    assert server._find_character(data2, "Zara Vex")[1] is char
    assert server._find_character(data2, "zara_vex")[1] is char
    assert char["species"] == "True-kin"
    assert char["level"] == 1
    assert char["xp"] == {"current": 0, "needed": 1}
    assert char["av"]["base"] == 10
    assert char["slot_capacity_total"] == 13  # 10 + CON 3
    assert char["slots_used"] == 2
    assert char["slots_remaining"] == 11
    assert char["ancestry_special_rules"][0]["name"] == "Pure of Blood"
    # the delegation pushes ride the output — combat kit comes from chargen (the
    # SINGLE source: weapon choice + armour + helm + shield), NOT generate(), and
    # NOT chargen(full) (full re-rolls gear+boon → the kit-divergence bug).
    assert 'roll(action="chargen", table="weapon")' in out
    assert 'roll(action="chargen", table="armour")' in out
    assert 'table="full"' not in out
    # the OLD starting-weapon/armour push is gone (chargen supersedes it). NB the
    # boon may still push generate(weapon, tier="advanced") — that's a separate item.
    assert 'generate(action="weapon", tier="basic")' not in out
    assert 'generate(action="armour")' not in out
    assert "inventory_changes" in out  # gear-recording push


def test_rations_in_carried_and_slots_counted(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.character(action="create_finalize", name="Zara",
                     ancestry="true-kin")
    key, char = roster["saved"][-1]
    carried = char["inventory"]["carried"]
    # The SUPPLY ENGINE'S schema: ration_type + integer rations
    # (survival.consume_day reads exactly these; live sheet ground truth).
    water = next(i for i in carried if i.get("ration_type") == "water")
    food = next(i for i in carried if i.get("ration_type") == "food")
    assert water["name"] == "Water Rations" and water["rations"] == 3
    assert food["name"] == "Food Rations" and food["rations"] == 3
    assert all(i["slots"] == 1 for i in carried)
    assert char["slots_used"] == 2
    assert char["slots_remaining"] == char["slot_capacity_total"] - 2
    # and the supply engine can actually drink/eat from them
    import survival
    short = survival.consume_day({"water": 1, "food": 1}, None, carried, False)
    assert short == {"water": 0, "food": 0}
    assert water["rations"] == 2 and food["rations"] == 2


def test_cacogen_finalize_pushes_three_mutations(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    rolled = []
    def fake_mutation():
        rolled.append(1)
        return {"name": "Extra Eyes", "effect": "See behind you",
                "source": f"d100={len(rolled)}"}
    monkeypatch.setattr(server, "_roll_cacogen_mutation", fake_mutation)
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="cacogen")
    assert len(rolled) == 3  # Corrupted Blood: d100 x3 at creation
    key, char = roster["saved"][-1]
    assert len(char["special_traits"]["mutations"]) == 3
    assert "Extra Eyes" in out


def test_boon_2_stamps_b3_placeholder(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)  # boon d6=2
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin")
    key, char = roster["saved"][-1]
    ids = [i["id"] for i in char["inventory"]["carried"]]
    assert "alchemists_crucible" in ids  # stamped BEFORE the save
    assert char["slots_used"] == 3
    assert "B3 pending" in out


# --- final-review fixes ---------------------------------------------------------

def test_finalize_stale_stash_rejected(roster, monkeypatch):
    _seed_pending(day=99)  # roster meta says Day 100
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin")
    assert "stale creation rolls from Day 99" in out
    assert 'character(action="create")' in out
    assert roster["saved"] == []
    # the stale stash is CLEARED, not kept for a later replay
    assert "pc_create_pending" not in server.GAME_STATE.get("world_tick", {})


def test_gear_push_uses_engine_depletion_schema(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    # d20=1 on both gear columns: Flashbang (x5) + Sleeping Gas Bomb (x5)
    out = server.character(action="create_finalize", name="Zara",
                           ancestry="true-kin")
    assert '"uses": 5' in out          # integer depletion counter, not "(x5)" prose
    assert '"count"' not in out        # the engine-inert field is gone
    import json as _json
    payload = out.split("inventory_changes=", 1)[1]
    changes = _json.JSONDecoder().raw_decode(payload)[0]
    import item_slots
    assert all(item_slots.item_is_depletable(c["item"]) for c in changes)


def test_neobloom_photosynthesis_armed(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.character(action="create_finalize", name="Sprig",
                     ancestry="neobloom")
    key, char = roster["saved"][-1]
    # the E1 death-window engine reads exactly these fields
    assert char["survival"] == {"needs_food": False,
                                "photosynthesis_window_days": 3,
                                "photosynthesis_last_fed_day": 100}
    import survival
    assert survival.daily_needs(char) == {"water": 1, "food": 0}


def test_faa_nomad_thirst_clock_three_weeks(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.character(action="create_finalize", name="Kotesh",
                     ancestry="faa-nomad")
    key, char = roster["saved"][-1]
    assert char["survival"] == {"death_days_thirst": 21}
    import survival
    assert survival.deprivation_clock(char, "thirst") == 21
    assert survival.deprivation_clock(char, "starvation") == 3
    assert "Desert Metabolism" in char["physiology"]


def test_synth_starts_with_three_synth_parts(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.character(action="create_finalize", name="Ojasin",
                     ancestry="synth")
    key, char = roster["saved"][-1]
    parts = next(i for i in char["inventory"]["carried"]
                 if i["id"] == "synth_parts")
    assert parts["uses"] == 3 and parts["slots"] == 1  # stack in one slot
    assert char["slots_used"] == 3
    assert char["wound_table"] == "synthetic"
    import survival
    # wound_table 'synthetic' switches needs off (fail-safe default)
    assert survival.daily_needs(char) == {"water": 0, "food": 0}


def test_sheet_schema_parity_fields(roster, monkeypatch):
    _seed_pending()
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.character(action="create_finalize", name="Zara",
                     ancestry="true-kin")
    key, char = roster["saved"][-1]
    assert char["pronouns"] == ""
    assert char["role"] == ""
    assert char["motivation"] == ""
    assert char["gleam"] == 0


def test_lithling_level_up_recomputes_crystalline_av(roster, monkeypatch):
    """Crystalline Flesh: base AV = 10 + Level (max 20), recomputed on level-up."""
    roster["data"]["characters"]["grond"] = {
        "name": "Grond", "species": "Lithling",
        "level": 1, "xp": {"current": 1, "needed": 1},
        "hp": {"current": 12, "max": 12},
        "av": {"base": 11, "source": "Crystalline Flesh (AV 10 + Level, max 20)",
               "conditional": []},
        "abilities": {ab: {"current": 0, "base": 0}
                      for ab in ["STR", "DEX", "CON", "INT", "PSY", "EGO"]},
    }
    out = server.character(action="level_up", name="Grond",
                           stat_increases="STR,DEX,CON", hp_roll=4)
    assert "Crystalline Flesh" in out
    key, char = roster["saved"][-1]
    assert char["av"]["base"] == 12  # 10 + new level 2
