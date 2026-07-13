# tests/test_pets_steeds.py
import copy
import pets_steeds as ps


def test_new_actions_registered():
    # Mirror tests/test_d3_mercenaries.py: the authoritative registration
    # surface in this codebase is the module-level VALID_CHARACTER_ACTIONS
    # list (the FastMCP-decorated character() tool's __doc__ is not a reliable
    # surface). The five D4 actions must be dispatchable.
    import server
    for a in ("acquire_pet", "acquire_steed", "level_up_pet", "ride_steed",
              "dismiss_companion"):
        assert a in server.VALID_CHARACTER_ACTIONS, \
            f"{a} missing from VALID_CHARACTER_ACTIONS"


def test_dead_pet_and_steed_get_no_resurrection(monkeypatch):
    import server
    # resurrection_push returns identifiable marker lines; assert they are ABSENT
    res_marker = "RESURRECTION"
    monkeypatch.setattr(server._cnd, "resurrection_push",
                        lambda: [f"{res_marker}: p.229 paths"])
    data = {"characters": {}}
    for t in ("pet", "steed"):
        char = {"name": f"a_{t}", "type": t, "hp": {"current": -20, "max": 5}}
        lines = server._death_seam_lines(char, data, f"a_{t}")
        assert not any(res_marker in l for l in lines), f"{t} wrongly offered resurrection"
    # control: a PC-shaped sheet (ancestry in type) still gets it
    pc = {"name": "vela", "type": "True-kin", "hp": {"current": -20, "max": 5}}
    pc_lines = server._death_seam_lines(pc, data, "vela")
    assert any(res_marker in l for l in pc_lines)


def test_is_pc_sheet_excludes_animals():
    import server
    assert server._is_pc_sheet({"type": "pet"}) is False
    assert server._is_pc_sheet({"type": "steed"}) is False
    assert server._is_pc_sheet({"type": "follower"}) is False
    assert server._is_pc_sheet({"type": "mercenary"}) is False
    assert server._is_pc_sheet({"type": "True-kin"}) is True   # ancestry-typed PC
    assert server._is_pc_sheet({"type": None}) is True


def test_catalog_counts():
    assert len(ps.PETS) == 11
    assert len(ps.STEEDS) == 8


def test_every_row_has_core_keys():
    for slug, row in {**ps.PETS, **ps.STEEDS}.items():
        for key in ("name", "kind", "level", "av", "morale", "attack", "special", "survival"):
            assert key in row, f"{slug} missing {key}"
        assert isinstance(row["level"], int)
        assert isinstance(row["av"], int)
        assert isinstance(row["survival"], dict)


def test_level_zero_hawk_preserved():
    hawk = ps.PETS["exultants_hawk"]
    assert hawk["level"] == 0
    assert hawk["hp"] == 1  # block reads "0 (1 HP)"


def test_steeds_carry_item_slots():
    # every steed has an item_slots value; Thin Mare is the "Special" sentinel
    for slug, row in ps.STEEDS.items():
        assert "item_slots" in row
    assert ps.STEEDS["thin_mare"]["item_slots"] == "Special"
    assert ps.STEEDS["destrier"]["item_slots"] == 20


def test_non_eaters_exempt():
    assert ps.PETS["pet_rock"]["survival"] == {"needs_food": False, "needs_water": False}
    assert ps.STEEDS["crysteed"]["survival"] == {"needs_food": False, "needs_water": False}
    assert ps.PETS["exultants_hawk"]["survival"] == {"needs_food": False, "needs_water": False}


def test_eaters_food_only():
    # book: "one ration per day" -> model as 1 food, no separate water charge
    z = ps.STEEDS["zorse"]["survival"]
    assert z["needs_food"] is True and z["needs_water"] is False and z["food_per_day"] == 1


def test_accessors_return_copies():
    a = ps.pet_block("ray_cat")
    a["level"] = 99
    assert ps.PETS["ray_cat"]["level"] == 1  # deep copy, not a live ref
    assert ps.steed_block("zorse")["name"] == "Zorse"


def test_cap_pools_followers_pets_steeds():
    import followers
    chars = {
        "boss": {"abilities": {"EGO": {"current": 6}}},
        "f1": {"type": "follower", "leader": "boss", "level": 2},
        "p1": {"type": "pet", "leader": "boss", "level": 1},
        "s1": {"type": "steed", "leader": "boss", "level": 3},
        "hawk": {"type": "pet", "leader": "boss", "level": 0},   # excluded from sum
        "merc": {"type": "mercenary", "leader": "boss", "level": 4},  # separate pool
        "other": {"type": "pet", "leader": "someone_else", "level": 5},  # not this leader
    }
    cap, used = followers.follower_level_cap(chars, "boss")
    assert cap == 6
    assert used == 6  # 2 + 1 + 3 ; hawk(0) adds 0, merc excluded, other leader excluded


# ---------------------------------------------------------------------------
# acquire_pet / acquire_steed — real-roster fixture
# ---------------------------------------------------------------------------
# The conftest `isolate_campaign_dir` autouse fixture already points
# server.CAMPAIGN_DIR at a fresh temp dir per test (via RUBICON_CAMPAIGN_DIR).
# This fixture just writes a leader PC sheet "boss" into that temp roster using
# the real split-sheet save path, so acquire_* goes through real load/save.
# (Mirrors the sandbox-roster style of tests/test_d3_mercenaries.py's _leader,
# but persisted to disk because acquire_* reloads via _load_characters.)

import pytest


def _write_leader(ego):
    import server
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    boss = {
        "name": "boss", "type": "True-kin", "pronouns": "they/them",
        "level": 3, "hp": {"current": 12, "max": 12},
        "av": {"base": 12, "source": "armour", "conditional": []},
        "abilities": {ab: {"current": (ego if ab == "EGO" else 0), "base": 0}
                      for ab in server.PC_ABILITY_ORDER},
        "inventory": {"carried": [], "stored": [], "installed_permanent": [],
                      "given_away": []},
    }
    data = {"meta": {"campaign_day": 12}, "characters": {"boss": boss}}
    server._save_characters(data)


@pytest.fixture
def tmp_campaign():
    """Leader PC 'boss' with EGO current 2 (pet-cap tests: two Level-1 pets fit)."""
    _write_leader(2)
    yield


@pytest.fixture
def tmp_campaign_ego6():
    """Leader PC 'boss' with EGO current 6 (steed-variant tests)."""
    _write_leader(6)
    yield


def test_acquire_pet_writes_sheet_and_enforces_cap(tmp_campaign):
    import server
    out = server._character_acquire_pet("boss", "ray_cat")
    assert "PET ACQUIRED" in out
    data, _ = server._load_characters()
    sheet = data["characters"]["ray_cat"]
    assert sheet["type"] == "pet"
    assert sheet["leader"] == "boss"
    assert sheet["level"] == 1
    assert sheet["av"]["base"] == 13
    assert sheet["hp"] == {"current": 1, "max": 1} or sheet["hp"]["max"] >= 1
    assert sheet["survival"]["needs_food"] is True

    # second Level-1 pet would push pooled level 2 == cap 2 -> still OK
    server._character_acquire_pet("boss", "skunkey")
    # a Level-1 third pet now exceeds EGO bonus 2 -> REJECTED
    rej = server._character_acquire_pet("boss", "volt_rat")
    assert "REJECTED" in rej and "cap" in rej.lower()


def test_acquire_level0_pet_always_allowed(tmp_campaign):
    import server
    # fill the cap, then a Level-0 hawk is still allowed (does not count)
    server._character_acquire_pet("boss", "ray_cat")
    server._character_acquire_pet("boss", "skunkey")
    out = server._character_acquire_pet("boss", "exultants_hawk")
    assert "PET ACQUIRED" in out
    data, _ = server._load_characters()
    assert data["characters"]["exultants_hawk"]["level"] == 0
    assert data["characters"]["exultants_hawk"]["survival"] == {
        "needs_food": False, "needs_water": False}


def test_acquire_steed_cargo_and_rider(tmp_campaign_ego6):
    import server
    # boss EGO 6 in this fixture variant; acquire a Zorse (Level 5) + set rider
    out = server._character_acquire_steed("boss", "zorse", rider="boss")
    assert "STEED ACQUIRED" in out
    data, _ = server._load_characters()
    s = data["characters"]["zorse"]
    assert s["type"] == "steed"
    assert s["slot_capacity_total"] == 50          # full item_slots integration
    assert s["mounted_by"] == "boss"
    assert s["av"]["base"] == 13


def test_acquire_thin_mare_special_slots(tmp_campaign_ego6):
    import server
    server._character_acquire_steed("boss", "thin_mare")
    data, _ = server._load_characters()
    s = data["characters"]["thin_mare"]
    assert s["slot_capacity_total"] == 100
    assert "hypergeometric" in s["item_slots_label"].lower()


def test_level_up_pet_adds_hp_and_slot(tmp_campaign_ego6):
    import server
    server._character_acquire_pet("boss", "companion_ooze")  # Level 1, item_slots 10
    data, _ = server._load_characters()
    before = data["characters"]["companion_ooze"]
    before["xp"] = {"current": 1, "needed": 1}
    server._save_single_character("companion_ooze", before, data)

    out = server._character_level_up_pet("companion_ooze", hp_roll=5)
    assert "LEVELS UP" in out
    data2, _ = server._load_characters()
    p = data2["characters"]["companion_ooze"]
    assert p["level"] == 2
    assert p["hp"]["max"] == before["hp"]["max"] + 5
    assert p["slot_capacity_total"] == 10 + 1   # +1 item slot


def test_level_up_pet_rejects_steed(tmp_campaign_ego6):
    import server
    server._character_acquire_steed("boss", "burden_bird")
    out = server._character_level_up_pet("burden_bird")
    assert "not a pet" in out.lower()


def test_ride_steed_one_per_pc(tmp_campaign_ego6):
    import server
    server._character_acquire_steed("boss", "burden_bird")  # Level 2
    server._character_acquire_steed("boss", "weeping_lizard")  # Level 3 (EGO 6)
    assert "MOUNTS" in server._character_ride_steed("burden_bird", rider="boss")
    # a second steed for the same PC is refused
    out = server._character_ride_steed("weeping_lizard", rider="boss")
    assert "only ONE steed" in out or "already rides" in out
    # dismount frees the PC
    assert "dismounts" in server._character_ride_steed(
        "burden_bird", rider="none").lower()
    assert "MOUNTS" in server._character_ride_steed("weeping_lizard", rider="boss")


def test_dismiss_companion_moves_pet_and_steed(tmp_campaign_ego6):
    import server
    server._character_acquire_pet("boss", "ray_cat")
    out = server._character_dismiss_companion("ray_cat", reason="released")
    assert "DEPARTS" in out
    data, _ = server._load_characters()
    assert "ray_cat" not in data["characters"]  # off the roster

    server._character_acquire_steed("boss", "burden_bird")
    out2 = server._character_dismiss_companion("burden_bird")
    assert "DEPARTS" in out2


def test_dismiss_companion_rejects_pc(tmp_campaign_ego6):
    import server
    out = server._character_dismiss_companion("boss")
    assert "not a pet or steed" in out.lower()


# ---------------------------------------------------------------------------
# Task 9: feeding tick (DEATH SEAM) — pets starve like PCs; steeds run away at
# 7 unfed days (CH p.69) and NEVER starve to death. These drive the live S1
# supply tick inside advance_day, mirroring tests/test_supply_tick.py's harness
# (field-mode supply + empty pool + a stamped Deprived starvation record).
# ---------------------------------------------------------------------------
import json


def _seed_feeding(day, companion_key, companion_sheet, since_day, death_day=None):
    """Write _meta.json (campaign_day + empty-pool field supply) and one
    companion sheet carrying a Deprived(starvation) record. Mirrors the
    _seed/_field_supply pattern from test_supply_tick.py."""
    import server
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    rec = {"name": "Deprived", "cause": "starvation", "since_day": since_day}
    if death_day is not None:
        rec["death_day"] = death_day
    companion_sheet.setdefault("conditions", []).append(rec)
    (chars_dir / f"{companion_key}.json").write_text(json.dumps(companion_sheet))
    meta = {
        "version": 1, "campaign_day": day,
        "supply": {"mode": "field", "pool": {"food": 0, "water": 0},
                   "pool_location": "wagon", "follower_mouths": 0,
                   "separated": [], "ledger": {"day": day, "consumed": {}}},
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (server.CAMPAIGN_DIR / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _companion_sheet(name, kind):
    """A catalog-faithful pet/steed sheet (EATS survival block: food only).
    Matches _write_companion_sheet's shape for the fields the tick reads."""
    return {
        "name": name, "type": kind, "leader": "boss", "level": 1,
        "hp": {"current": 5, "max": 5},
        "wound_table": "biological",
        "survival": {"needs_food": True, "needs_water": False, "food_per_day": 1},
        "inventory": {"carried": [], "stored": [], "installed_permanent": [],
                      "given_away": []},
        "conditions": [],
    }


def test_pet_starves_like_a_pc(isolate_campaign_dir):
    import server
    # ray_cat unfed since Day 1, death clock fires Day 4; pool is empty.
    _seed_feeding(1, "ray_cat", _companion_sheet("Ray Cat", "pet"),
                  since_day=1, death_day=4)
    out = server.advance_day(4, "no food")
    data, _ = server._load_characters()
    pet = data["characters"]["ray_cat"]
    assert pet["hp"]["current"] <= -20            # died of starvation
    assert "DIES of starvation" in out
    assert "RESURRECTION" not in out               # animal: no p.229 menu


def test_steed_runs_away_at_7_unfed_days_not_death(isolate_campaign_dir):
    import server
    # burden_bird unfed since Day 1. Its generic clock would fire Day 4, but the
    # steed death-exemption (Step 3a) blocks starvation death; at 7 consecutive
    # unfed days it runs away (Step 3b) instead.
    _seed_feeding(1, "burden_bird", _companion_sheet("Burden Bird", "steed"),
                  since_day=1, death_day=4)
    out = server.advance_day(7, "still no food")
    data, _ = server._load_characters()
    steed = data["characters"]["burden_bird"]
    assert steed["hp"]["current"] > -20            # NOT dead by starvation
    assert "RUNAWAY" in out or "runs away" in out.lower()
    # and the steed did NOT die of starvation
    assert "Burden Bird DIES of starvation" not in out
