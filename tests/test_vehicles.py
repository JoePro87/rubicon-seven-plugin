# tests/test_vehicles.py
import vehicles as V


def test_catalog_has_11_entries():
    assert len(V.VEHICLES) == 11


def test_book_nine_present():
    for slug in ("auto_chariot", "colossus", "dune_skuggy", "ornithopter", "skiff",
                 "stilt_strutter", "touring_orb", "vimana", "wind_barge"):
        assert slug in V.VEHICLES and V.VEHICLES[slug]["homebrew"] is False


def test_two_homebrews_flagged():
    assert V.VEHICLES["crawler"]["homebrew"] is True
    assert V.VEHICLES["ornithopter_titan"]["homebrew"] is True


def test_required_keys_and_types():
    for slug, r in V.VEHICLES.items():
        for k in ("name", "kind", "hull", "av", "speed", "item_slots", "attack",
                  "crew", "special", "homebrew"):
            assert k in r, f"{slug} missing {k}"
        assert isinstance(r["hull"], int)
        assert isinstance(r["av"], int)


def test_known_stat_blocks():
    c = V.VEHICLES["colossus"]
    assert (c["hull"], c["av"], c["speed"], c["item_slots"]) == (10, 20, 3, 100)
    assert V.VEHICLES["wind_barge"]["speed"] == "d6/day"   # sentinel string
    assert V.VEHICLES["crawler"]["hull"] == 12 and V.VEHICLES["crawler"]["item_slots"] == 150


def test_titan_matches_book_stats_but_larger_crew():
    book = V.VEHICLES["ornithopter"]
    titan = V.VEHICLES["ornithopter_titan"]
    assert (titan["hull"], titan["av"], titan["speed"], titan["item_slots"]) == \
           (book["hull"], book["av"], book["speed"], book["item_slots"])
    assert titan["crew"] != book["crew"]            # whole-crew capacity is the homebrew part
    assert titan["travel"]["mph"] == 120 and titan["travel"]["daily_range_miles"] == 960


def test_vimana_damage_immune():
    assert V.VEHICLES["vimana"]["damage_immune"] is True


def test_accessor_is_a_copy():
    a = V.vehicle_block("skiff")
    a["hull"] = 99
    assert V.VEHICLES["skiff"]["hull"] == 2
    assert V.vehicle_block("nope") is None


# ---------------------------------------------------------------------------
# acquire_vehicle - real-roster fixture
# ---------------------------------------------------------------------------
# The conftest `isolate_campaign_dir` autouse fixture already points
# server.CAMPAIGN_DIR at a fresh temp dir per test (via RUBICON_CAMPAIGN_DIR).
# This fixture writes a leader PC sheet "boss" into that temp roster through the
# real split-sheet save path, mirroring tests/test_pets_steeds.py::tmp_campaign,
# so acquire_vehicle round-trips through real _load_characters/_save.

import pytest


@pytest.fixture
def tmp_campaign():
    """Leader PC 'boss' on a fresh temp roster (vehicles have no command cap)."""
    import server
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    boss = {
        "name": "boss", "type": "True-kin", "pronouns": "they/them",
        "level": 3, "hp": {"current": 12, "max": 12},
        "av": {"base": 12, "source": "armour", "conditional": []},
        "abilities": {ab: {"current": 0, "base": 0}
                      for ab in server.PC_ABILITY_ORDER},
        "inventory": {"carried": [], "stored": [], "installed_permanent": [],
                      "given_away": []},
    }
    data = {"meta": {"campaign_day": 12}, "characters": {"boss": boss}}
    server._save_characters(data)
    yield


def test_acquire_vehicle_writes_sheet(tmp_campaign):
    import server
    out = server._character_acquire_vehicle("boss", "dune_skuggy")
    assert "VEHICLE ACQUIRED" in out
    data, _ = server._load_characters()
    v = data["characters"]["dune_skuggy"]
    assert v["type"] == "vehicle"
    assert v["hull"] == {"current": 5, "max": 5}
    assert v["av"]["base"] == 13
    assert v["slot_capacity_total"] == 30
    assert v["owner"] == "boss"
    # weapon built onto the sheet
    assert any("Flak Cannon" in (i.get("name", "")) for i in v["inventory"]["carried"])


def test_acquire_unarmed_vehicle(tmp_campaign):
    import server
    out = server._character_acquire_vehicle("boss", "wind_barge")
    assert "VEHICLE ACQUIRED" in out
    data, _ = server._load_characters()
    assert data["characters"]["wind_barge"]["hull"]["max"] == 15
    # Wind Barge has no attack -> no weapon in carried
    assert data["characters"]["wind_barge"]["inventory"]["carried"] == []


def test_acquire_unknown_vehicle(tmp_campaign):
    import server
    assert "Unknown vehicle" in server._character_acquire_vehicle("boss", "nope")


def test_repair_vehicle(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "colossus")  # Hull 10
    data, _ = server._load_characters()
    v = data["characters"]["colossus"]; v["hull"]["current"] = 4
    server._save_single_character("colossus", v, data)
    out = server._character_repair_vehicle("colossus", 3)
    assert "REPAIRED" in out and "3 day" in out
    data2, _ = server._load_characters()
    assert data2["characters"]["colossus"]["hull"]["current"] == 7


def test_repair_caps_at_max(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "skiff")  # Hull 2
    out = server._character_repair_vehicle("skiff", 9)
    data, _ = server._load_characters()
    assert data["characters"]["skiff"]["hull"]["current"] == 2  # capped at max


def test_repair_rejects_non_vehicle(tmp_campaign):
    import server
    assert "not a vehicle" in server._character_repair_vehicle("boss", 1).lower()


def test_hull_1to10_and_nostack(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "colossus")  # Hull 10
    # a 9-damage hit removes 0 Hull
    server._vehicle_take_damage("colossus", 9, [])
    assert server._load_characters()[0]["characters"]["colossus"]["hull"]["current"] == 10
    # a 19-damage hit removes exactly 1 Hull
    server._vehicle_take_damage("colossus", 19, [])
    assert server._load_characters()[0]["characters"]["colossus"]["hull"]["current"] == 9
    # a 25-damage hit removes 2
    server._vehicle_take_damage("colossus", 25, [])
    assert server._load_characters()[0]["characters"]["colossus"]["hull"]["current"] == 7


def test_hull_zero_wrecks(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "skiff")  # Hull 2
    out = server._vehicle_take_damage("skiff", 30, [])  # 3 Hull loss -> floored at 0
    v = server._load_characters()[0]["characters"]["skiff"]
    assert v["hull"]["current"] == 0 and v["operational"] is False
    assert "WRECKED" in out
    assert "RESURRECTION" not in out  # never the PC death menu


def test_vimana_immune_unless_anti_paradox(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "vimana")  # Hull 1, damage_immune
    server._vehicle_take_damage("vimana", 100, [])       # normal weapon: no effect
    assert server._load_characters()[0]["characters"]["vimana"]["hull"]["current"] == 1
    server._vehicle_take_damage("vimana", 100, ["anti_paradox"])  # unravels
    assert server._load_characters()[0]["characters"]["vimana"]["hull"]["current"] == 0


# ---------------------------------------------------------------------------
# Task 5: _combat_damage delegates a vehicle target to the Hull-Points path
# ---------------------------------------------------------------------------
# Minimal active_combat stub (empty enemies/party_snapshot, acted flags False so
# _check_round_advance is a no-op); _save_game_state stubbed to avoid writing
# game state. A vehicle name (neither enemy nor PC) must route to the Hull path.

def test_combat_damage_routes_vehicle_to_hull(tmp_campaign, monkeypatch):
    import server
    server._character_acquire_vehicle("boss", "colossus")  # Hull 10
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {"enemies": {}, "party_snapshot": {}, "log": [],
         "pcs_acted": False, "enemies_acted": False},
    )
    out = server._combat_damage("colossus", 25, "kinetic")
    assert "Hull" in out and "colossus" in out.lower()
    # 25 raw -> 2 Hull loss (1:10, no-stack): 10 -> 8
    assert server._load_characters()[0]["characters"]["colossus"]["hull"]["current"] == 8


def test_combat_damage_nonvehicle_still_not_found(tmp_campaign, monkeypatch):
    import server
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {"enemies": {}, "party_snapshot": {}, "log": [],
         "pcs_acted": False, "enemies_acted": False},
    )
    # "boss" is a PC sheet, not type:"vehicle", and not in party_snapshot here
    out = server._combat_damage("boss", 5, "kinetic")
    assert "not found in combat" in out


# ---------------------------------------------------------------------------
# Task 6: synthetic self-attack to-hit + opposed Speed-save chase (CH p.73)
# ---------------------------------------------------------------------------
def test_synthetic_attack_bonus_is_current_hull(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "auto_chariot")  # Synthetic, Hull 8
    data, _ = server._load_characters()
    assert server._vehicle_attack_bonus(data["characters"]["auto_chariot"]) == 8
    # mechanical vehicle: no self-attack bonus (needs an operator)
    server._character_acquire_vehicle("boss", "dune_skuggy")
    data2, _ = server._load_characters()
    assert server._vehicle_attack_bonus(data2["characters"]["dune_skuggy"]) is None


def test_speed_save_lines(tmp_campaign):
    import server
    server._character_acquire_vehicle("boss", "skiff")     # Speed +8
    server._character_acquire_vehicle("boss", "wind_barge")  # Speed d6/day
    lines = server._vehicle_speed_save_lines("skiff", "wind_barge")
    assert any("Speed" in l for l in lines)
    assert any("+8" in l for l in lines)  # skiff's speed surfaced


# ---------------------------------------------------------------------------
# Task 7: discoverability - vehicle actions registered in the character tool
# ---------------------------------------------------------------------------
def test_vehicle_actions_registered():
    import server
    for a in ("acquire_vehicle", "repair_vehicle"):
        assert a in server.VALID_CHARACTER_ACTIONS


# ---------------------------------------------------------------------------
# Adversarial hardening: a hand-malformed sheet with a non-dict hull must not
# crash any vehicle op (the `or {}` guard let a bare-int/str hull through).
# ---------------------------------------------------------------------------
def test_non_dict_hull_does_not_crash(tmp_campaign):
    import server
    data, _ = server._load_characters()
    bad = {"name": "Junker", "type": "vehicle", "species": "Mechanical",
           "hull": 7,  # malformed: an int, not a {current,max} dict
           "av": {"base": 12, "source": "vehicle", "conditional": []}}
    data.setdefault("characters", {})["junker"] = bad
    server._save_single_character("junker", bad, data)
    # none of these may raise
    server._vehicle_take_damage("junker", 50, [])
    server._vehicle_attack_bonus(bad)
    out = server._character_repair_vehicle("junker", 2)
    assert isinstance(out, str)  # returned a message, did not crash
