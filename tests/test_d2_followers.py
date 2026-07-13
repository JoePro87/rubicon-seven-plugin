"""D2 Followers Task 2 - character(action="recruit_follower"/"follower_level_up"/
"dismiss_follower") (CH p.61-62).

Recruitment rolls d20 + leader EGO on the p.62 table with the command cap
(combined follower Levels <= leader EGO bonus) enforced BEFORE any write;
advancement is +d8 max HP ONLY; dismissal stamps the departure and moves the
sheet to characters/departed/.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


def _follower_sheet(name, leader="vela", level=1, xp_current=0):
    return {
        "name": name, "type": "follower", "leader": leader,
        "level": level,
        "xp": {"current": xp_current, "needed": max(1, level)},
        "hp": {"current": 4, "max": 4},
        "av": {"base": 11, "source": "follower", "conditional": []},
        "ml": 2,
        "abilities": {ab: {"current": 0, "base": 0}
                      for ab in server.PC_ABILITY_ORDER},
        "slot_capacity_total": 10 + level,
        "slots_used": 1, "slots_remaining": 9 + level,
        "wound_table": "biological",
        "inventory": {"carried": [{"name": "Rusted Dagger", "slots": 1}],
                      "stored": [], "installed_permanent": [], "given_away": []},
        "notes": {},
    }


@pytest.fixture
def roster(monkeypatch):
    """Two PCs (EGO +3 and EGO 0), day 50, saves captured in-memory."""
    data = {
        "characters": {
            "vela": {"name": "Vela", "species": "True-kin", "level": 3,
                     "hp": {"current": 10, "max": 10},
                     "abilities": {"EGO": {"current": 3, "base": 3}}},
            "kess": {"name": "Kess", "species": "Cacogen", "level": 2,
                     "hp": {"current": 8, "max": 8},
                     "abilities": {"EGO": {"current": 0, "base": 0}}},
        },
        "meta": {"campaign_day": 50},
    }
    saved = []
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda key, char, d=None: saved.append((key, char)))
    yield {"data": data, "saved": saved}


# --- recruit_follower ----------------------------------------------------------

def test_recruit_happy_path_round_trip(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=24)  # Goldwin, Level 2 Synth
    assert "FOLLOWER RECRUITED" in out
    assert "Goldwin" in out
    key, sheet = roster["saved"][-1]
    assert key == "goldwin"
    assert roster["data"]["characters"]["goldwin"] is sheet
    assert sheet["type"] == "follower"
    assert sheet["leader"] == "vela"
    assert sheet["species"] == "Synth"
    assert sheet["level"] == 2
    assert sheet["hp"] == {"current": 8, "max": 8}
    assert sheet["av"]["base"] == 12
    assert sheet["ml"] == 4
    # abilities all six, all zero (book: followers have none)
    assert set(sheet["abilities"]) == set(server.PC_ABILITY_ORDER)
    assert all(v == {"current": 0, "base": 0}
               for v in sheet["abilities"].values())
    assert sheet["xp"] == {"current": 0, "needed": 2}
    assert sheet["slot_capacity_total"] == 12
    # 0 carried rations - they eat from the party pool
    assert not any(i.get("ration_type")
                   for i in sheet["inventory"]["carried"])
    # the rolled attack, weapon-schema minted
    weapon = sheet["inventory"]["carried"][0]
    assert weapon["name"] == "Volt Baton"
    assert weapon["damage"] == "d6"
    assert weapon["damage_type"] == "electrical"
    assert weapon["range"] == "melee"
    # Synth description -> synthetic wound table
    assert sheet["wound_table"] == "synthetic"
    assert sheet["appearance"].startswith("Synth with an ape-like body")
    assert sheet["notes"]["recruited"] == {"day": 50, "total": 24,
                                           "leader": "vela"}
    # cap line reports the math
    assert "EGO bonus 3" in out


def test_recruit_rolls_d20_plus_ego(roster, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 10)
    out = server.character(action="recruit_follower", name="Vela")
    assert "d20 + EGO 3 = 13" in out
    key, sheet = roster["saved"][-1]
    assert key == "bluebliss"  # table row 13
    assert sheet["level"] == 1


def test_recruit_ranged_attack_marked_ranged(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=16)  # Longdream, Old Revolver
    weapon = roster["saved"][-1][1]["inventory"]["carried"][0]
    assert weapon["name"] == "Old Revolver"
    assert weapon["range"] == "ranged"
    assert "Longdream" in out


def test_recruit_grenades_blast_and_note(roster):
    # Row 29 is Level 3 > the recruiter's cap alone; clear the room with forced math:
    # raise EGO so the cap admits a Level 3 recruit.
    roster["data"]["characters"]["vela"]["abilities"]["EGO"]["current"] = 4
    server.character(action="recruit_follower", name="Vela", recruit_roll=29)
    weapon = roster["saved"][-1][1]["inventory"]["carried"][0]
    assert weapon["name"] == "3 Ancient Grenades"
    assert weapon["range"] == "ranged"
    assert weapon["damage_type"] == "blast"
    assert weapon["notes"] == "50% chance won't detonate"


def test_recruit_cap_rejection_reports_math(roster):
    # EGO +1 leader, Level 2 recruit -> reject, nothing written
    roster["data"]["characters"]["vela"]["abilities"]["EGO"]["current"] = 1
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=16)
    assert "RECRUIT REJECTED" in out
    assert "EGO bonus 1" in out
    assert "levels already in service 0" in out
    assert "dismiss_follower" in out
    assert roster["saved"] == []
    assert "longdream" not in roster["data"]["characters"]


def test_recruit_ego_zero_leader_only_level_zero(roster):
    out = server.character(action="recruit_follower", name="Kess",
                           recruit_roll=11)  # Level 1
    assert "RECRUIT REJECTED" in out
    assert roster["saved"] == []
    out = server.character(action="recruit_follower", name="Kess",
                           recruit_roll=5)  # Level 0 fits a 0 cap
    assert "FOLLOWER RECRUITED" in out
    assert roster["saved"][-1][1]["level"] == 0


def test_recruit_levels_in_service_count_against_cap(roster):
    # EGO 3 leader with a Level 2 already sworn: another Level 2 is over cap
    roster["data"]["characters"]["abrax"] = _follower_sheet("Abrax", level=2)
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=16)
    assert "RECRUIT REJECTED" in out
    assert "levels already in service 2" in out
    # but a Level 1 (total 3) fits exactly
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=12)
    assert "FOLLOWER RECRUITED" in out
    assert "now 3/3" in out


def test_recruit_level0_xp_needed_is_1(roster):
    server.character(action="recruit_follower", name="Vela", recruit_roll=5)
    assert roster["saved"][-1][1]["xp"] == {"current": 0, "needed": 1}


def test_recruit_forced_roll_out_of_range(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=31)
    assert "0-30" in out
    assert roster["saved"] == []


def test_recruit_forced_roll_zero_is_valid(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=0)
    assert "Herta" in out
    assert roster["saved"][-1][0] == "herta"


def test_recruit_duplicate_name_rejected(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=24, follower_name="Kess")
    assert "REJECTED" in out
    assert roster["saved"] == []


def test_recruit_follower_name_override(roster):
    server.character(action="recruit_follower", name="Vela",
                     recruit_roll=24, follower_name="Smokes")
    key, sheet = roster["saved"][-1]
    assert key == "smokes"
    assert sheet["name"] == "Smokes"


def test_recruit_leader_must_not_be_follower(roster):
    roster["data"]["characters"]["abrax"] = _follower_sheet("Abrax")
    out = server.character(action="recruit_follower", name="Abrax",
                           recruit_roll=5)
    assert "cannot recruit" in out
    assert roster["saved"] == []


def test_recruit_unknown_leader(roster):
    out = server.character(action="recruit_follower", name="Nobody",
                           recruit_roll=5)
    assert "not found" in out


def test_recruit_pushes_relationship_supply_and_offer_note(roster):
    out = server.character(action="recruit_follower", name="Vela",
                           recruit_roll=24)
    assert ('relationship(action="set", entity1="Vela", entity2="Goldwin", '
            'status="follower"') in out
    assert "last_interaction_day=50" in out
    assert 'supply(action="status")' in out
    assert "OFFER, not a hire" in out
    assert 'character(action="dismiss_follower", name="Goldwin")' in out


def test_recruit_zero_ability_sheet_safe_for_engine_consumers(roster):
    server.character(action="recruit_follower", name="Vela", recruit_roll=24)
    sheet = roster["saved"][-1][1]
    # slot math never KeyErrors on a zero-ability sheet
    slots = server._calculate_slots(sheet)
    assert slots["capacity"] == 12
    # condition-save surfacing never KeyErrors either
    note = server._condition_save_note(sheet, "CON")
    assert isinstance(note, str)


# --- follower_level_up ----------------------------------------------------------

def test_level_up_d8_only_and_xp_reset(roster, monkeypatch):
    roster["data"]["characters"]["abrax"] = _follower_sheet(
        "Abrax", level=1, xp_current=1)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 5)
    out = server.character(action="follower_level_up", name="Abrax")
    sheet = roster["saved"][-1][1]
    assert sheet["level"] == 2
    assert sheet["hp"] == {"current": 9, "max": 9}  # 4 + 5
    assert sheet["xp"] == {"current": 0, "needed": 2}
    assert sheet["slot_capacity_total"] == 12
    assert sheet["slots_remaining"] == 11
    # abilities untouched - still all zero
    assert all(v == {"current": 0, "base": 0}
               for v in sheet["abilities"].values())
    assert "rolled 5" in out
    # The recruiter's EGO 3 still covers Level 2: no warning
    assert "WARNING" not in out


def test_level_up_over_cap_warns_not_rejects(roster, monkeypatch):
    roster["data"]["characters"]["vela"]["abilities"]["EGO"]["current"] = 1
    roster["data"]["characters"]["abrax"] = _follower_sheet(
        "Abrax", level=1, xp_current=1)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 3)
    out = server.character(action="follower_level_up", name="Abrax")
    # level-up still applied
    assert roster["saved"][-1][1]["level"] == 2
    assert "WARNING" in out
    assert "OVER the command cap" in out
    assert 'character(action="dismiss_follower"' in out


def test_level_up_xp_guard(roster):
    roster["data"]["characters"]["abrax"] = _follower_sheet(
        "Abrax", level=2, xp_current=1)
    out = server.character(action="follower_level_up", name="Abrax")
    assert "1/2 XP" in out
    assert roster["saved"] == []


def test_level_up_type_guard(roster):
    out = server.character(action="follower_level_up", name="Vela")
    assert "not a follower" in out
    assert roster["saved"] == []


# --- dismiss_follower -----------------------------------------------------------

def test_dismiss_type_guard(roster):
    out = server.character(action="dismiss_follower", name="Vela")
    assert "not a follower" in out
    assert roster["saved"] == []


def test_dismiss_stamps_departure(roster):
    roster["data"]["characters"]["abrax"] = _follower_sheet("Abrax")
    out = server.character(action="dismiss_follower", name="Abrax",
                           reason="deserted")
    key, sheet = roster["saved"][-1]
    assert key == "abrax"
    assert sheet["notes"]["departed"] == {"day": 50, "reason": "deserted"}
    assert "DEPARTS" in out
    # roster handle forgets them even when no file existed to move
    assert "abrax" not in roster["data"]["characters"]


def test_dismiss_moves_file_and_roster_forgets():
    """Real files in the conftest-isolated CAMPAIGN_DIR (never the live repo)."""
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / "_meta.json").write_text(
        json.dumps({"campaign_day": 50}), encoding="utf-8")
    (chars_dir / "torble.json").write_text(
        json.dumps(_follower_sheet("Torble")), encoding="utf-8")
    data, err = server._load_characters()
    assert err is None and "torble" in data["characters"]

    out = server.character(action="dismiss_follower", name="Torble",
                           reason="went home")
    assert "TORBLE DEPARTS" in out
    assert "characters/departed/torble.json" in out
    # the file moved
    assert not (chars_dir / "torble.json").exists()
    departed = chars_dir / "departed" / "torble.json"
    assert departed.exists()
    stamped = json.loads(departed.read_text(encoding="utf-8"))
    assert stamped["notes"]["departed"] == {"day": 50, "reason": "went home"}
    # the roster loader no longer finds them
    data, err = server._load_characters()
    assert err is None
    assert "torble" not in data["characters"]


def test_dismiss_missing_file_warns():
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / "_meta.json").write_text(
        json.dumps({"campaign_day": 50}), encoding="utf-8")
    (chars_dir / "ghost.json").write_text(
        json.dumps(_follower_sheet("Ghost")), encoding="utf-8")
    # the save stamps the sheet, then we yank the file before the move
    real_save = server._save_single_character

    def stamp_then_vanish(key, char, d=None):
        real_save(key, char, d)
        (chars_dir / f"{key}.json").unlink(missing_ok=True)

    import unittest.mock as mock
    with mock.patch.object(server, "_save_single_character",
                           side_effect=stamp_then_vanish):
        out = server.character(action="dismiss_follower", name="Ghost")
    assert "WARNING" in out
    assert "no file moved" in out


# --- dispatcher wiring ----------------------------------------------------------

def test_actions_registered():
    for a in ("recruit_follower", "follower_level_up", "dismiss_follower"):
        assert a in server.VALID_CHARACTER_ACTIONS


def test_actions_require_name(roster):
    for a in ("recruit_follower", "follower_level_up", "dismiss_follower"):
        out = server.character(action=a)
        assert "requires 'name'" in out
