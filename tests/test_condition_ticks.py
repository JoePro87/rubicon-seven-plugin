"""E1 Task 4: advance_day day/week drains, generic death clocks via the gate,
photosynthesis mint/clear, arrive-does-not-clear.

Uses the same isolate_campaign_dir (autouse conftest) + seeding pattern as
test_supply_tick.py and test_death_gate_twinning.py.
"""
import json
import pytest
import server


# ---------------------------------------------------------------------------
# Seed helpers (mirror test_death_gate_twinning.py)
# ---------------------------------------------------------------------------

def _creenash_char(day=100, hp=19, conditions=None, survival=None):
    ch = {
        "name": "Creenash",
        "hp": {"current": hp, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 4, "base": 4},
            "DEX": {"current": 6, "base": 6},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }
    if survival is not None:
        ch["survival"] = survival
    return ch


def _vela_char(conditions=None):
    return {
        "name": "Vela",
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
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed(dirpath, day=100, creenash=None, vela=None):
    """Write minimal split-sheet structure; abundant supply so supply tick stays silent."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {
        "version": 1,
        "campaign_day": day,
        "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                   "separated": [], "ledger": {"day": day, "consumed": {}}},
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash if creenash is not None else _creenash_char(day)))
    (chars_dir / "vela.json").write_text(
        json.dumps(vela if vela is not None else _vela_char()))


def _status_md(dirpath, day):
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get_creenash():
    data, err = server._load_characters()
    assert not err
    key, ch = server._find_character(data, "creenash")
    return data, key, ch


def _current_day(dirpath):
    return json.loads(
        (dirpath / "characters" / "_meta.json").read_text()
    ).get("campaign_day")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_day_tick_hp_drain(isolate_campaign_dir, monkeypatch):
    """Day-cadence condition drains HP once per elapsed day."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Slow Rot",
                     tick_cadence="day", tick_hp="d4")
    _, _, ch = _get_creenash()
    hp0 = ch["hp"]["current"]
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 3})
    out = server.advance_day(day + 1, "test")
    assert "CONDITION TICK" in out and "Slow Rot" in out
    _, _, ch2 = _get_creenash()
    assert ch2["hp"]["current"] == hp0 - 3


def test_day_tick_idempotent_same_day(isolate_campaign_dir, monkeypatch):
    """Calling advance_day again on the same day does NOT re-tick."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Slow Rot",
                     tick_cadence="day", tick_hp="d4")
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 3})
    server.advance_day(day + 1, "tick once")
    _, _, ch = _get_creenash()
    hp1 = ch["hp"]["current"]
    # Re-advance same day - should be idempotent (elapsed=0)
    out = server.advance_day(day + 1, "same day again")
    _, _, ch2 = _get_creenash()
    assert ch2["hp"]["current"] == hp1            # no double tick
    assert "CONDITION TICK" not in out


def test_week_cadence_fires_on_7th_day_only(isolate_campaign_dir, monkeypatch):
    """Week-cadence drain fires only on multiples of 7 from since_day."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Jellybones",
                     tick_cadence="week", tick_abilities='{"STR": "d4"}')
    # pin since_day so the week math is deterministic
    data, key, ch = _get_creenash()
    rec = next(c for c in ch["conditions"] if c["name"] == "Jellybones")
    rec["since_day"] = day
    server._save_single_character(key, ch, data)
    str0 = ch["abilities"]["STR"]["current"]
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 2})
    server.advance_day(day + 6, "six days")       # no week boundary yet
    _, _, ch2 = _get_creenash()
    assert ch2["abilities"]["STR"]["current"] == str0
    server.advance_day(day + 7, "day seven")      # boundary: one tick
    _, _, ch3 = _get_creenash()
    assert ch3["abilities"]["STR"]["current"] == str0 - 2


def test_two_day_conditions_first_lethal_breaks(isolate_campaign_dir, monkeypatch):
    """Two day-cadence HP conditions, first tick lethal: exactly ONE death
    banner, ONE resurrection menu, the second condition never ticks the
    corpse (mirror of the combat round-tick death-break)."""
    day = 100
    _seed(isolate_campaign_dir, day=day, creenash=_creenash_char(day, hp=-15))
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Slow Rot",
                     tick_cadence="day", tick_hp="d8")
    server.affliction(kind="condition", action="apply", character="creenash", name="Caustic Drip",
                     tick_cadence="day", tick_hp="d6")
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})

    out = server.advance_day(day + 1, "lethal first tick")

    assert out.count("!!! FATALITY: HP dropped to -20 or below !!!") == 1
    assert out.count("p.229") == 1                # ONE resurrection menu
    assert "Caustic Drip" not in out              # second tick never fired

    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -23             # -15 - 8, NOT double-drained


def test_generic_death_clock_kills_via_gate(isolate_campaign_dir):
    """A generic death_day clock kills the PC when the day arrives."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Doom Mark",
                     cause="ritual", death_day=day + 2)
    out = server.advance_day(day + 2, "the mark comes due")
    assert "DIES" in out and "p.229" in out
    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -20


def test_twinning_blocks_clock_death(isolate_campaign_dir):
    """Twinning prevents the death when a clock fires — brink-clamps HP."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    server.affliction(kind="condition", action="apply", character="creenash", name="Doom Mark",
                     death_day=day + 1)
    out = server.advance_day(day + 1, "mark due but twinned")
    assert "TWINNING" in out and "death prevented" in out
    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -19


def test_twinning_blocks_thirst_clock_death(isolate_campaign_dir):
    """Supply tick parity: a Twinning-refused thirst death lands at the
    R-E1g brink (-19), not untouched HP; the Deprived record stays (unfed)."""
    day = 100
    creenash = _creenash_char(
        day=day,
        conditions=[{"name": "Deprived", "cause": "thirst",
                     "since_day": day - 3, "death_day": day + 1}]
    )
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    # field mode with an empty pool: thirst stays unmet, the clock fires
    meta_path = isolate_campaign_dir / "characters" / "_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["supply"] = {"mode": "field", "pool": {"food": 0, "water": 0},
                      "follower_mouths": 0, "separated": [],
                      "ledger": {"day": day, "consumed": {}}}
    meta_path.write_text(json.dumps(meta))
    _status_md(isolate_campaign_dir, day)
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    out = server.advance_day(day + 1, "thirst clock due but twinned")
    assert "TWINNING" in out and "death prevented" in out
    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -19
    # the record stays - still unfed; only drinking clears it
    assert any(c.get("name") == "Deprived" and c.get("cause") == "thirst"
               for c in ch.get("conditions", []))


def test_photosynthesis_mints_deprived_first_missed_day(isolate_campaign_dir):
    """First missed photosynthesis day mints Deprived(photosynthesis)."""
    day = 100
    _seed(isolate_campaign_dir, day=day, creenash=_creenash_char(
        day=day,
        survival={"photosynthesis_window_days": 4,
                  "photosynthesis_last_fed_day": day}
    ))
    _status_md(isolate_campaign_dir, day)
    out = server.advance_day(day + 1, "first day unfed")
    assert "photosynthesis" in out.lower()
    _, _, ch2 = _get_creenash()
    rec = next(
        (c for c in ch2["conditions"]
         if c.get("name") == "Deprived" and c.get("cause") == "photosynthesis"),
        None
    )
    assert rec is not None
    assert rec["since_day"] == day + 1
    assert rec["death_day"] == day + 4


def test_photosynthesis_death_at_window(isolate_campaign_dir):
    """Death lands on the window day itself (R-E1c)."""
    day = 100
    _seed(isolate_campaign_dir, day=day, creenash=_creenash_char(
        day=day,
        survival={"photosynthesis_window_days": 4,
                  "photosynthesis_last_fed_day": day}
    ))
    _status_md(isolate_campaign_dir, day)
    out = server.advance_day(day + 4, "window day - perish")
    assert "DIES" in out
    _, _, ch2 = _get_creenash()
    assert ch2["hp"]["current"] == -20


def test_update_photosynthesis_writes_field_and_clears(isolate_campaign_dir):
    """update_photosynthesis writes structured fed-day and clears the Deprived(photosynthesis) record."""
    day = 100
    creenash = _creenash_char(
        day=day,
        survival={"photosynthesis_window_days": 4,
                  "photosynthesis_last_fed_day": day - 2},
        conditions=[
            {"name": "Deprived", "cause": "photosynthesis",
             "since_day": day - 1, "death_day": day + 2}
        ]
    )
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _status_md(isolate_campaign_dir, day)
    out = server.supply(action='photosynthesis', last_fed_day=day, current_day=day)
    assert "recovered" in out.lower() or "cleared" in out.lower()
    _, _, ch2 = _get_creenash()
    assert ch2["survival"]["photosynthesis_last_fed_day"] == day
    assert not any(c.get("cause") == "photosynthesis"
                   for c in ch2.get("conditions", []))


def test_arrive_does_not_clear_photosynthesis(isolate_campaign_dir):
    """supply(action='arrive') clears thirst/starvation Deprived but NOT photosynthesis."""
    day = 100
    creenash = _creenash_char(
        day=day,
        conditions=[
            {"name": "Deprived", "cause": "thirst", "since_day": 1, "death_day": 4},
            {"name": "Deprived", "cause": "photosynthesis", "since_day": 1,
             "death_day": 4}
        ]
    )
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    # Set field mode so arrive actually clears
    data, key, ch = _get_creenash()
    meta_path = isolate_campaign_dir / "characters" / "_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["supply"]["mode"] = "field"
    meta_path.write_text(json.dumps(meta))
    server.supply(action="arrive")
    _, _, ch2 = _get_creenash()
    causes = [c.get("cause") for c in ch2.get("conditions", [])
              if c.get("name") == "Deprived"]
    assert causes == ["photosynthesis"]      # thirst cleared, sunlight is not food


# ---------------------------------------------------------------------------
# Opus review fixes (round 2)
# ---------------------------------------------------------------------------

def test_update_photosynthesis_refuses_stale_fed_day(isolate_campaign_dir):
    """A fed-day whose death window is already closed is refused outright -
    accepting it would clear the record and re-mint a past clock (kill)."""
    day = 100
    creenash = _creenash_char(
        day=day,
        survival={"photosynthesis_window_days": 4,
                  "photosynthesis_last_fed_day": 97},
        conditions=[{"name": "Deprived", "cause": "photosynthesis",
                     "since_day": 98, "death_day": 101}]
    )
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _status_md(isolate_campaign_dir, day)
    # 96 + 4 = 100 <= today (100): a PC alive today cannot have fed Day 96
    out = server.supply(action='photosynthesis', last_fed_day=96, current_day=day)
    assert "REFUSED" in out and "Sheet unchanged" in out
    _, _, ch = _get_creenash()
    assert ch["survival"]["photosynthesis_last_fed_day"] == 97   # unchanged
    assert any(c.get("cause") == "photosynthesis"
               for c in ch.get("conditions", []))                # record intact


def test_update_photosynthesis_past_but_valid_fed_day_reminting(isolate_campaign_dir):
    """A past fed-day that still leaves the PC alive is accepted; the next
    advance_day re-mints with the correct since/death anchors."""
    day = 100
    creenash = _creenash_char(
        day=day,
        survival={"photosynthesis_window_days": 4,
                  "photosynthesis_last_fed_day": 97},
        conditions=[{"name": "Deprived", "cause": "photosynthesis",
                     "since_day": 98, "death_day": 101}]
    )
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _status_md(isolate_campaign_dir, day)
    # 98 + 4 = 102 > today (100): valid - clears the record
    out = server.supply(action='photosynthesis', last_fed_day=98, current_day=day)
    assert "REFUSED" not in out
    _, _, ch = _get_creenash()
    assert ch["survival"]["photosynthesis_last_fed_day"] == 98
    assert not any(c.get("cause") == "photosynthesis"
                   for c in ch.get("conditions", []))
    # still unfed: the next advance_day re-mints anchored to the NEW fed-day
    server.advance_day(day + 1, "still unfed since Day 98")
    _, _, ch2 = _get_creenash()
    rec = next(c for c in ch2["conditions"]
               if c.get("name") == "Deprived"
               and c.get("cause") == "photosynthesis")
    assert rec["since_day"] == 99 and rec["death_day"] == 102


def test_twinning_blocks_wound_tick_ability_death(isolate_campaign_dir):
    """Degenerative wound drains an ability past -10 on a twinned PC: the
    gate refuses, clamps the ability to -10, PC lives, TWINNING surfaces."""
    day = 100
    creenash = _creenash_char(day=day)
    creenash["wounds"] = [{"name": "Cascading Kinesthetics Debilitation",
                           "slots": 3, "daily_tick": {"STR": 15}}]
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _status_md(isolate_campaign_dir, day)
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    out = server.advance_day(day + 1, "the wound gnaws")
    assert "TWINNING" in out and "death prevented" in out
    _, _, ch = _get_creenash()
    assert ch["abilities"]["STR"]["current"] == -10   # gate clamps the floor
    assert ch["hp"]["current"] > -20                  # alive


def test_wound_tick_ability_death_untwinned(isolate_campaign_dir):
    """Same drain, no Twinning: the death stands - HP snaps to -20 and the
    five resurrection paths are pushed."""
    day = 100
    creenash = _creenash_char(day=day)
    creenash["wounds"] = [{"name": "Cascading Kinesthetics Debilitation",
                           "slots": 3, "daily_tick": {"STR": 15}}]
    _seed(isolate_campaign_dir, day=day, creenash=creenash)
    _status_md(isolate_campaign_dir, day)
    out = server.advance_day(day + 1, "the wound finishes it")
    assert "p.229" in out
    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -20


def test_week_cadence_without_since_day_skips_with_warning(isolate_campaign_dir,
                                                           monkeypatch):
    """A week-cadence record with no since_day anchor must NOT fire on
    arbitrary day % 7 boundaries - skip it and warn by name."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    server.affliction(kind="condition", action="apply", character="creenash", name="Jellybones",
                     tick_cadence="week", tick_abilities='{"STR": "d4"}')
    data, key, ch = _get_creenash()
    rec = next(c for c in ch["conditions"] if c["name"] == "Jellybones")
    rec["since_day"] = 0          # legacy/hand-edited: no anchor
    server._save_single_character(key, ch, data)
    str0 = ch["abilities"]["STR"]["current"]
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 2})
    out = server.advance_day(day + 5, "to day 105")   # 105 % 7 == 0 would fire
    _, _, ch2 = _get_creenash()
    assert ch2["abilities"]["STR"]["current"] == str0   # skipped, no drain
    assert "since_day" in out and "Jellybones" in out   # warning names it


def test_one_refusal_block_for_multiple_clocks_same_day(isolate_campaign_dir):
    """Two death clocks landing the same tick_day on a twinned PC emit ONE
    TWINNING refusal block, not one per clock."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    server.affliction(kind="condition", action="apply", character="creenash", name="Doom Mark",
                     death_day=day + 1)
    server.affliction(kind="condition", action="apply", character="creenash", name="Counting Curse",
                     death_day=day + 1)
    out = server.advance_day(day + 1, "both clocks land")
    assert out.count("death prevented") == 1
    _, _, ch = _get_creenash()
    assert ch["hp"]["current"] == -19
