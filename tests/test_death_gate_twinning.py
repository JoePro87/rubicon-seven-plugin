"""E1 Task 2: the death gate. Twinning refuses solo deaths, allows paired
ones, brink-clamps state, and real deaths push the five resurrection paths.

NOTE: Uses isolate_campaign_dir (conftest.py autouse) + a _seed helper
to write minimal character files into the temp dir. The plan referenced
_base_isolate(tmp_path, monkeypatch) but that signature does not exist
in test_combat_attack.py (which requires a characters_fixture dict, not
file I/O). We use the file-based seeding pattern instead (test_supply_tool.py
/ test_supply_tick.py precedent).
"""
import json
import pytest
import server
import conditions as cnd


# ---------------------------------------------------------------------------
# Minimal character fixtures
# ---------------------------------------------------------------------------

def _brek():
    return {
        "name": "Brek",
        "hp": {"current": 19, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 6, "base": 4},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": [],
    }


def _mira():
    return {
        "name": "Mira",
        "hp": {"current": 24, "max": 24},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 2, "base": 2},
            "DEX": {"current": 4, "base": 4},
            "CON": {"current": 3, "base": 3},
            "INT": {"current": 4, "base": 4},
            "PSY": {"current": 3, "base": 3},
            "EGO": {"current": 5, "base": 3},
        },
        "conditions": [],
    }


def _seed(dirpath, brek_data=None, mira_data=None, day=100):
    """Write minimal character split-sheets into the temp campaign dir."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "brek.json").write_text(
        json.dumps(brek_data if brek_data is not None else _brek()))
    (chars_dir / "mira.json").write_text(
        json.dumps(mira_data if mira_data is not None else _mira()))


# ---------------------------------------------------------------------------
# Helper: stamp mutual Twinning bond on both sheets already in the temp dir
# ---------------------------------------------------------------------------

def _twin_pair(dirpath):
    """Stamp a mutual Twinning bond on the on-disk brek + mira sheets."""
    data, err = server._load_characters()
    assert not err, err
    for me, partner_name in (("brek", "Mira"), ("mira", "Brek")):
        key, ch = server._find_character(data, me)
        assert ch, me
        ch.setdefault("conditions", []).append({
            "name": "Twinning", "since_day": 31,
            "effects": {"twinned": {"partner": partner_name}},
        })
        server._save_single_character(key, ch, data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_gate_open_without_twinning(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char["hp"]["current"] = -25
    allowed, lines = server._death_gate(key, char, data, window_key="day:100")
    assert allowed is True and lines == []


def test_twinning_refuses_solo_death_and_clamps(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char["hp"]["current"] = -25
    allowed, lines = server._death_gate(key, char, data, window_key="combat:r3")
    assert allowed is False
    assert char["hp"]["current"] == -19                       # brink clamp R-E1g
    assert char["twinning_pending"] == {"window": "combat:r3"}
    joined = "\n".join(lines)
    assert "TWINNING" in joined and "Mira" in joined


def test_ability_floor_clamped_on_refusal(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char["abilities"]["STR"]["current"] = -12
    allowed, _ = server._death_gate(key, char, data, window_key="day:101")
    assert allowed is False
    assert char["abilities"]["STR"]["current"] == -10


def test_same_window_kills_both(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    akey, creen = server._find_character(data, "brek")
    creen["hp"]["current"] = -25
    assert server._death_gate(akey, creen, data, window_key="combat:r5")[0] is False
    # persist the twinning_pending mark (the gate stamps it; caller must save)
    server._save_single_character(akey, creen, data)
    # now Mira goes down in the SAME round
    data2, _ = server._load_characters()
    bkey, mira = server._find_character(data2, "mira")
    mira["hp"]["current"] = -22
    allowed, lines = server._death_gate(bkey, mira, data2, window_key="combat:r5")
    assert allowed is True
    assert any("BOTH" in l or "SUNDERED" in l.upper() for l in lines)
    # the pending partner was re-killed for real and persisted
    data3, _ = server._load_characters()
    _, creen2 = server._find_character(data3, "brek")
    assert creen2["hp"]["current"] == -20
    assert "twinning_pending" not in creen2


def test_different_window_refuses_again(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    akey, creen = server._find_character(data, "brek")
    creen["hp"]["current"] = -25
    server._death_gate(akey, creen, data, window_key="combat:r5")
    data2, _ = server._load_characters()
    bkey, mira = server._find_character(data2, "mira")
    mira["hp"]["current"] = -22
    allowed, _ = server._death_gate(bkey, mira, data2, window_key="combat:r6")
    assert allowed is False and mira["hp"]["current"] == -19


def test_partner_already_dead_opens_gate(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    bkey, mira = server._find_character(data, "mira")
    mira["hp"]["current"] = -20
    server._save_single_character(bkey, mira, data)
    data2, _ = server._load_characters()
    akey, creen = server._find_character(data2, "brek")
    creen["hp"]["current"] = -25
    allowed, lines = server._death_gate(akey, creen, data2, window_key="day:103")
    assert allowed is True
    assert any("already dead" in l for l in lines)


def test_one_sided_bond_is_severed(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    # Only stamp brek's side, NOT mira's — one-sided bond
    data, _ = server._load_characters()
    k, ch = server._find_character(data, "brek")
    ch.setdefault("conditions", []).append(
        {"name": "Twinning", "effects": {"twinned": {"partner": "Mira"}}})
    ch["hp"]["current"] = -25
    server._save_single_character(k, ch, data)
    data2, _ = server._load_characters()
    k2, ch2 = server._find_character(data2, "brek")
    allowed, lines = server._death_gate(k2, ch2, data2, window_key="day:104")
    assert allowed is True
    assert any("one-sided" in l or "mismatch" in l for l in lines)


def test_apply_damage_routes_through_gate(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char["hp"]["current"] = 2
    lines, lethal = server._apply_hp_damage_and_wounds(key, char, data, 40,
                                                       window_key="day:105")
    assert char["hp"]["current"] == -19            # refused + clamped
    assert lethal is False
    assert any("TWINNING" in l for l in lines)
    # No death declaration banner (the "!!! FATALITY !!!" line); the wound name
    # at the -20 row is also "FATALITY" so check for the banner format specifically.
    assert not any(l.startswith("**!!!") and "FATALITY" in l for l in lines)
    # the killing wound still landed (R-E1g)
    assert char.get("wounds")


def test_real_death_pushes_five_paths(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")   # no Twinning stamped
    char["hp"]["current"] = 2
    lines, _ = server._apply_hp_damage_and_wounds(key, char, data, 40,
                                                  window_key="day:106")
    joined = "\n".join(lines)
    assert "FATALITY" in joined
    for needle in ("p.229", "Mycomorph", "Necrotech", "Pseudo-Womb",
                   "Spirit", "Ego-Engine"):
        assert needle in joined, needle


def test_deaths_door_gated(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char.setdefault("wounds", []).append(
        {"name": "Death's Door", "hp_threshold": -15, "slots": 1, "deaths_door": True})
    char["hp"]["current"] = -15
    lines, lethal = server._apply_hp_damage_and_wounds(key, char, data, 3,
                                                       window_key="day:107")
    assert lethal is False and char["hp"]["current"] == -19
    assert any("TWINNING" in l for l in lines)


def test_paired_death_notes_both_need_rulings(isolate_campaign_dir):
    """Same-window both-die via the caller path: the SUNDERED branch adds the
    both-rulings note and the caller emits the five-path menu exactly ONCE."""
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    # First: brek falls and is refused (pending stamped + persisted)
    data, _ = server._load_characters()
    akey, creen = server._find_character(data, "brek")
    creen["hp"]["current"] = -25
    assert server._death_gate(akey, creen, data, window_key="day:108")[0] is False
    server._save_single_character(akey, creen, data)
    # Now: mira falls in the SAME window through the unified damage path
    data2, _ = server._load_characters()
    bkey, mira = server._find_character(data2, "mira")
    mira["hp"]["current"] = 2
    lines, _ = server._apply_hp_damage_and_wounds(bkey, mira, data2, 40,
                                                  window_key="day:108")
    joined = "\n".join(lines)
    assert "SUNDERED" in joined
    assert "Two deaths, two rulings" in joined
    assert "EACH of them separately" in joined
    # the five-path menu appears exactly once (its header line carries p.229)
    assert joined.count("RESURRECTION & DEATH (book p.229)") == 1
    # both are dead on disk / in memory
    data3, _ = server._load_characters()
    _, creen2 = server._find_character(data3, "brek")
    assert creen2["hp"]["current"] == -20
    assert mira["hp"]["current"] <= -20


def test_cross_round_windows_do_not_pair(isolate_campaign_dir):
    """Pending at combat:r5; partner falls at combat:r6 - refused, BOTH alive."""
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    akey, creen = server._find_character(data, "brek")
    creen["hp"]["current"] = -25
    assert server._death_gate(akey, creen, data, window_key="combat:r5")[0] is False
    server._save_single_character(akey, creen, data)
    data2, _ = server._load_characters()
    bkey, mira = server._find_character(data2, "mira")
    mira["hp"]["current"] = -22
    allowed, _ = server._death_gate(bkey, mira, data2, window_key="combat:r6")
    assert allowed is False
    server._save_single_character(bkey, mira, data2)
    # BOTH still alive (brink-clamped, never snapped to -20)
    data3, _ = server._load_characters()
    _, creen3 = server._find_character(data3, "brek")
    _, mira3 = server._find_character(data3, "mira")
    assert creen3["hp"]["current"] == -19
    assert mira3["hp"]["current"] == -19


def test_slots_full_perpetual_brink(isolate_campaign_dir):
    """Wound-slots-full death on a Twinned PC: every gated check refuses
    (the slots stay full - perpetual brink), re-stamping the pending window."""
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    key, char = server._find_character(data, "brek")
    char["wounds_slots_used"] = 10          # capacity defaults to 10 -> full
    is_dead, reason, lines = server._check_death_gated(
        key, char, data, window_key="day:110")
    assert is_dead is False and reason is None
    assert char["twinning_pending"] == {"window": "day:110"}
    assert any("TWINNING" in l for l in lines)
    # a later window: still refused, pending re-stamped to the LATEST window
    is_dead2, reason2, lines2 = server._check_death_gated(
        key, char, data, window_key="day:111")
    assert is_dead2 is False and reason2 is None
    assert char["twinning_pending"] == {"window": "day:111"}
    # alive throughout (HP untouched - the slots condition, not HP, triggered)
    assert char["hp"]["current"] > -20


def test_gate_survives_int_hp(isolate_campaign_dir):
    """Partner sheet with hp as a bare int and a matching pending window:
    no crash; the both-die branch warns instead of writing, death stands."""
    _seed(isolate_campaign_dir)
    _twin_pair(isolate_campaign_dir)
    data, _ = server._load_characters()
    bkey, mira = server._find_character(data, "mira")
    mira["hp"] = 24                                  # bare int, malformed sheet
    mira["twinning_pending"] = {"window": "day:112"}
    server._save_single_character(bkey, mira, data)
    data2, _ = server._load_characters()
    akey, creen = server._find_character(data2, "brek")
    creen["hp"]["current"] = -25
    allowed, lines = server._death_gate(akey, creen, data2, window_key="day:112")
    assert allowed is True                           # pairing still completes
    joined = "\n".join(lines)
    assert "SUNDERED" in joined
    assert "not a dict" in joined                    # the guard warned
    # pending was consumed even though the HP write was skipped
    data3, _ = server._load_characters()
    _, mira3 = server._find_character(data3, "mira")
    assert "twinning_pending" not in mira3
    assert mira3["hp"] == 24                         # untouched, warned instead
