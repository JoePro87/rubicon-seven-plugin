"""E2 Task 4 (DEATH SEAM): advance_day consumes the new tick grammar -
save-gated ticks, max_hp drains, on_max_hp_zero clock, transformation deaths
through the gated/Twinning-aware seam. Reuses the test_condition_ticks.py
seeding pattern + isolate_campaign_dir autouse fixture."""
import json
import pytest
import server
import diseases as dz


def _creenash_char(day=100, hp=19, conditions=None, survival=None):
    ch = {
        "name": "Creenash",
        "species": "True-kin",
        "hp": {"current": hp, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 4, "base": 4},
            "DEX": {"current": 6, "base": 6},
            "CON": {"current": 1, "base": 1},   # low so Lumenrot can dissolve fast
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 1, "base": 1},   # low so Hivey Hump converts fast
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }
    if survival is not None:
        ch["survival"] = survival
    return ch


def _vela_char(conditions=None):
    return {
        "name": "Vela", "species": "True-kin",
        "hp": {"current": 24, "max": 24}, "wound_table": "biological",
        "abilities": {a: {"current": 4, "base": 4}
                      for a in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed(dirpath, day=100, creenash=None, vela=None):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash if creenash is not None else _creenash_char(day)))
    (chars_dir / "vela.json").write_text(
        json.dumps(vela if vela is not None else _vela_char()))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get(name="creenash"):
    data, err = server._load_characters()
    assert not err
    key, ch = server._find_character(data, name)
    return data, key, ch


def _apply_disease(name, char_name="creenash"):
    out = server.affliction(kind="disease", action="apply", character=char_name, disease=name)
    assert "contracts" in out, out


def test_jellybones_week_drains_str_con(isolate_campaign_dir, monkeypatch):
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _apply_disease("Jellybones")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Jellybones")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    str0 = ch["abilities"]["STR"]["current"]
    con0 = ch["abilities"]["CON"]["current"]
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 2})
    server.advance_day(day + 7, "one week")
    _, _, ch2 = _get()
    assert ch2["abilities"]["STR"]["current"] == str0 - 2
    assert ch2["abilities"]["CON"]["current"] == con0 - 2


def test_labyrinth_pox_drains_max_hp_and_clamps_current(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day, hp=23)   # current == max
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Labyrinth Pox")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Labyrinth Pox")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})
    out = server.advance_day(day + 7, "pox week one")
    assert "max HP" in out or "max_hp" in out.lower() or "Labyrinth Pox" in out
    _, _, ch2 = _get()
    assert ch2["hp"]["max"] == 23 - 8
    assert ch2["hp"]["current"] <= ch2["hp"]["max"]   # current clamped down with max


def test_labyrinth_pox_max_hp_zero_stamps_death_day_once(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day, hp=8)
    creenash["hp"]["max"] = 8
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Labyrinth Pox")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Labyrinth Pox")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})
    # week-one drain takes max HP 8 -> 0, stamping death_day = tick_day + 3
    server.advance_day(day + 7, "pox to zero")
    _, _, ch2 = _get()
    rec2 = next(c for c in ch2["conditions"] if c["name"] == "Labyrinth Pox")
    assert rec2["death_day"] == (day + 7) + 3
    assert ch2["hp"]["max"] == 0
    assert ch2["hp"]["current"] > -20            # not yet dead - the 3-day clock runs
    # idempotency: re-advancing the same day does not re-stamp a later death_day
    server.advance_day(day + 7, "same day again")
    _, _, ch3 = _get()
    rec3 = next(c for c in ch3["conditions"] if c["name"] == "Labyrinth Pox")
    assert rec3["death_day"] == (day + 7) + 3


def test_labyrinth_pox_vanish_at_death_day_gated(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day, hp=8)
    creenash["hp"]["max"] = 8
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Labyrinth Pox")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Labyrinth Pox")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})
    out = server.advance_day(day + 10, "to the vanishing")  # past death_day 110
    assert "DIES" in out and "p.229" in out
    assert "TRANSFORMATION" in out    # _disease_death_prose at the clock branch
    _, _, ch2 = _get()
    assert ch2["hp"]["current"] == -20


def test_lumenrot_save_gated_drain_miss_fires(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["CON"]["current"] = 4
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Lumenrot")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Lumenrot")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    # force the engine save to MISS (low d20)
    monkeypatch.setattr(server.dice, "roll_notation",
                        lambda n: {"total": 1} if "d20" in str(n) else {"total": 1})
    server.advance_day(day + 1, "lumenrot day - save misses")
    _, _, ch2 = _get()
    assert ch2["abilities"]["CON"]["current"] == 4 - 1   # flat -1 CON on the miss


def test_lumenrot_save_gated_drain_pass_skips(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["CON"]["current"] = 4
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Lumenrot")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Lumenrot")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    # force the engine save to PASS (high d20)
    monkeypatch.setattr(server.dice, "roll_notation",
                        lambda n: {"total": 20} if "d20" in str(n) else {"total": 1})
    out = server.advance_day(day + 1, "lumenrot day - save passes")
    _, _, ch2 = _get()
    assert ch2["abilities"]["CON"]["current"] == 4   # no drain on a pass
    assert "save" in out.lower()                     # the save is logged


def test_hivey_hump_ego_to_zero_dies_gated(isolate_campaign_dir):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["EGO"]["current"] = 1   # flat -1/day -> 0 then below
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Hivey Hump")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Hivey Hump")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    # several days so EGO drains past -10 (death threshold)
    out = server.advance_day(day + 12, "the bees take hold")
    assert "p.229" in out
    _, _, ch2 = _get()
    assert ch2["hp"]["current"] == -20


def test_hivey_hump_twinning_holds_at_brink(isolate_campaign_dir):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["EGO"]["current"] = 1
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _apply_disease("Hivey Hump")
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Hivey Hump")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    out = server.advance_day(day + 12, "the bees take hold but twinned")
    assert "TWINNING" in out and "death prevented" in out
    _, _, ch2 = _get()
    assert ch2["abilities"]["EGO"]["current"] == -10   # gate clamps the floor
    assert ch2["hp"]["current"] > -20                  # alive


def test_corpse_stops_ticking_one_death_readout(isolate_campaign_dir, monkeypatch):
    """Opus T4 review: an ability-drain death must break the day-tick loop -
    one resurrection menu, no post-mortem drains saved to the corpse."""
    day = 100
    creenash = _creenash_char(day=day, hp=23)
    creenash["conditions"] = [
        {"name": "Hivey Hump", "cause": "disease", "since_day": day,
         "tick": {"cadence": "day", "abilities": {"EGO": "12"},
                  "label": "Hivey Hump"}},
        {"name": "Labyrinth Pox", "cause": "disease", "since_day": day,
         "tick": {"cadence": "day", "max_hp": "d8", "label": "Labyrinth Pox"}},
    ]
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    monkeypatch.setattr(server.dice, "roll_notation",
                        lambda n: {"total": 8, "notation": n})
    out = server.advance_day(day + 1, "double lethal day")
    assert out.count("RESURRECTION & DEATH") == 1     # exactly one menu
    _, _, ch = _get()
    assert ch["hp"]["current"] == -20
    assert ch["hp"]["max"] == 23      # Pox did NOT drain the corpse post-mortem


# --- E3 Task 4: Gitch crystal loop + Dreamcage + AV hook ---

def _gitch_on(slot="CON", char_name="creenash"):
    """Apply The Gitch with a forced rolled slot via monkeypatch at the call site."""
    out = server.affliction(kind="disease", action="apply", character=char_name, disease="The Gitch")
    assert "Gitch" in out, out


def test_gitch_missed_save_adds_crystal_and_av(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["CON"]["current"] = 6
    creenash["av"] = {"base": 12}
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 3)   # 3 -> CON
    _gitch_on()
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "The Gitch")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    # force the engine CON save to MISS
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 1})
    out = server.advance_day(day + 1, "gitch day one - save misses")
    _, _, ch2 = _get()
    crystals = [w for w in ch2.get("wounds", []) if w.get("gitch")]
    assert len(crystals) == 1
    assert crystals[0]["slots"] == 1 and crystals[0]["av_bonus"] == 1
    assert ch2["wounds_slots_used"] == 1
    assert ch2["abilities"]["CON"]["current"] == 5     # -1 drain
    assert "AV" in out                                 # +N AV surfaced


def test_gitch_passed_save_no_crystal(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["CON"]["current"] = 6
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 3)
    _gitch_on()
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "The Gitch")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 20})
    server.advance_day(day + 1, "gitch day - save passes")
    _, _, ch2 = _get()
    assert not [w for w in ch2.get("wounds", []) if w.get("gitch")]
    assert ch2["abilities"]["CON"]["current"] == 6     # no drain


def test_gitch_av_bonus_reaches_resolve_target_av(isolate_campaign_dir):
    # a Gitch crystal raises the PC's resolved AV by 1 (_defender_av is the
    # combat AV lookup; _resolve_target_av is the plan's alias -- use actual name)
    day = 100
    creenash = _creenash_char(day=day)
    creenash["av"] = {"base": 12}
    creenash["wounds"] = [{"name": "Gitch Crystals", "slots": 1,
                           "av_bonus": 1, "gitch": True, "day": day}]
    creenash["wounds_slots_used"] = 1
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    assert server._defender_av("creenash") == 13


def test_gitch_fills_all_slots_transforms_gated(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["EGO"]["current"] = 9
    creenash["av"] = {"base": 12}
    creenash["slot_capacity_total"] = 2     # tiny capacity so 2 crystals fill it
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 6)   # 6 -> EGO
    _gitch_on()
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "The Gitch")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 1})  # all misses
    out = server.advance_day(day + 5, "gitch fills up")
    assert "Gitchghast" in out and "p.229" in out
    _, _, ch2 = _get()
    assert ch2["hp"]["current"] == -20


def test_gitch_transform_twinning_holds(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["EGO"]["current"] = 9
    creenash["slot_capacity_total"] = 2
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 6)
    _gitch_on()
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "The Gitch")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 1})
    out = server.advance_day(day + 5, "gitch fills but twinned")
    assert "TWINNING" in out and "death prevented" in out
    _, _, ch2 = _get()
    assert ch2["hp"]["current"] > -20    # held at the brink


def test_gitch_idempotent_same_day(isolate_campaign_dir, monkeypatch):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["CON"]["current"] = 6
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 3)
    _gitch_on()
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "The Gitch")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 1})
    server.advance_day(day + 1, "first")
    server.advance_day(day + 1, "same day again")     # no second day elapsed
    _, _, ch2 = _get()
    assert len([w for w in ch2.get("wounds", []) if w.get("gitch")]) == 1


def test_gitch_crystal_heals_via_wound_flow(isolate_campaign_dir):
    day = 100
    creenash = _creenash_char(day=day)
    creenash["wounds"] = [{"name": "Gitch Crystals", "slots": 1,
                           "av_bonus": 1, "gitch": True, "day": day}]
    creenash["wounds_slots_used"] = 1
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    out = server.affliction(kind="wound", action="heal", character="creenash", wound="Gitch Crystals")
    _, _, ch = _get()
    assert not [w for w in ch.get("wounds", []) if w.get("gitch")]


def test_dreamcage_psy_fray_to_somnambulist_gated(isolate_campaign_dir):
    # NO new advance_day code for Dreamcage - this verifies the existing grammar
    day = 100
    creenash = _creenash_char(day=day)
    creenash["abilities"]["PSY"]["current"] = 1
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Dreamcage")
    data, key, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Dreamcage")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    out = server.advance_day(day + 13, "the dreamless wasting")   # PSY past -10
    assert "p.229" in out
    _, _, ch2 = _get()
    assert ch2["hp"]["current"] == -20


def test_dreamcage_no_hp_regain_blocks_rest(isolate_campaign_dir):
    day = 100
    creenash = _creenash_char(day=day, hp=5)
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Dreamcage")
    out = server.rest(action="long", characters="creenash")
    assert "cannot regain HP" in out
