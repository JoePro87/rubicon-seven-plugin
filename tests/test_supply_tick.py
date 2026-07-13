"""advance_day supply tick: consumption, Deprived clocks, death, silence at home."""
import json
import server

# Reuse the seeding helpers from tests/test_supply_tool.py by importing them,
# or copy _seed/_vela verbatim here (they are 20 lines; copying is fine and
# keeps the files independent).
from tests.test_supply_tool import _seed, _vela


def _meta(dirpath):
    return json.loads((dirpath / "characters" / "_meta.json").read_text())


def _sheet(dirpath, key):
    return json.loads((dirpath / "characters" / f"{key}.json").read_text())


def _status_md(dirpath, day):
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _field_supply(day, pool, mouths=0):
    return {"mode": "field", "pool": pool, "pool_location": "wagon",
            "follower_mouths": mouths, "separated": [],
            "ledger": {"day": day, "consumed": {}}}


def test_abundant_mode_is_silent_and_inert(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir,
          supply={"mode": "abundant", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.advance_day(101, "quiet day at home")
    assert "SUPPLY" not in out
    assert _sheet(isolate_campaign_dir, "vela").get("conditions", []) == []


def test_field_tick_decrements_pool_by_headcount(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    out = server.advance_day(101, "march")
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool == {"food": 9, "water": 9}
    assert "SUPPLY" in out


def test_followers_eat_too(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir,
          supply=_field_supply(100, {"food": 10, "water": 10}, mouths=2),
          chars={"vela": _vela()})
    server.advance_day(101, "march")
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool == {"food": 7, "water": 7}  # 1 PC + 2 followers


def test_shortfall_creates_deprived_with_warning(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 0, "water": 0}),
          chars={"vela": _vela()})
    out = server.advance_day(101, "dry march")
    conds = _sheet(isolate_campaign_dir, "vela")["conditions"]
    causes = {c["cause"] for c in conds}
    assert causes == {"thirst", "starvation"}
    assert "DEPRIVED" in out and "Vela" in out
    assert 'supply(action="status")' in out  # push present


def test_carried_rations_consumed_when_no_pool(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    items = [{"name": "Water Rations", "ration_type": "water", "rations": 2, "slots": 1},
             {"name": "Food Rations", "ration_type": "food", "rations": 2, "slots": 1}]
    _seed(isolate_campaign_dir, supply=_field_supply(100, None),
          chars={"vela": _vela(items=items)})
    server.advance_day(101, "march")
    inv = _sheet(isolate_campaign_dir, "vela")["inventory"]["carried"]
    assert inv[0]["rations"] == 1 and inv[1]["rations"] == 1


def test_recovery_clears_deprived(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 5, "water": 5}),
          chars={"vela": _vela(conditions=conds)})
    out = server.advance_day(101, "found a spring")
    assert _sheet(isolate_campaign_dir, "vela")["conditions"] == []
    assert "recovered" in out.lower() or "cleared" in out.lower()


def test_death_at_clock_limit(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 98, "death_day": 101}]
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 0, "water": 0}),
          chars={"vela": _vela(conditions=conds)})
    out = server.advance_day(101, "the waste takes its due")
    sheet = _sheet(isolate_campaign_dir, "vela")
    assert sheet["hp"]["current"] == -20  # state-true death (Death's Door precedent)
    assert "DIES" in out or "DEAD" in out


def test_warning_day_before_death(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 5, "water": 0}),
          chars={"vela": _vela(conditions=conds)})
    out = server.advance_day(101, "still dry")
    assert "Day 102" in out  # names the death day while still alive


def test_same_day_recall_does_not_double_tick(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    server.advance_day(101, "march")
    server.advance_day(101, "march (retry)")  # idempotency guard
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool == {"food": 9, "water": 9}


def test_ledger_credit_from_rest_respected(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    sup = _field_supply(100, {"food": 10, "water": 10})
    sup["ledger"] = {"day": 100, "consumed": {"vela": {"water": 1}}}
    _seed(isolate_campaign_dir, supply=sup, chars={"vela": _vela()})
    server.advance_day(101, "march")
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool == {"food": 9, "water": 10}  # water already covered by the rest


def _pc(name, conditions=None):
    return {"name": name, "wound_table": "biological",
            "hp": {"current": 10, "max": 12},
            "inventory": {"carried": []},
            "conditions": conditions or []}


def test_multiday_death_stops_corpse_feeding(isolate_campaign_dir):
    # Trace (pool food=10 water=0; ticked days 101, 102, 103):
    #   Day 101: Aila consumes 1 food (consumption precedes the death check),
    #            then her thirst clock fires (101 >= death_day 101) -> DIES,
    #            joins s_dead. Vela eats 1 food, water short -> thirst record
    #            (since 101, death_day 104).
    #   Day 102: Aila skipped (corpse). Vela eats 1 food, still short, alive.
    #   Day 103: Vela eats 1 food, alive (103 < 104).
    #   Pool food: 10 - 1 (Aila, day 101 only) - 3 (Vela) = 6.
    _status_md(isolate_campaign_dir, 100)
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 98, "death_day": 101}]
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 0}),
          chars={"aila": _pc("Aila", conds), "vela": _vela()})
    out = server.advance_day(103, "long dry march")
    assert _sheet(isolate_campaign_dir, "aila")["hp"]["current"] == -20
    assert "DIES" in out
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool["food"] == 6  # corpse ate at most through its death day


def test_vehicle_not_charged_rations(isolate_campaign_dir):
    # C1: _load_characters merges vehicles into the roster (wound_table
    # "mechanical", hp None) — they must consume nothing and never crash
    # the death write.
    _status_md(isolate_campaign_dir, 100)
    crawler = {"type": "vehicle", "name": "Crawler",
               "wound_table": "mechanical", "hp": None}
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela(), "crawler": crawler})
    server.advance_day(101, "march")
    pool = _meta(isolate_campaign_dir)["supply"]["pool"]
    assert pool == {"food": 9, "water": 9}  # only Vela charged
    assert _sheet(isolate_campaign_dir, "crawler").get("conditions", []) == []


def test_multiday_record_then_death_in_one_call(isolate_campaign_dir):
    # Clean PC, zero supply, 100 -> 104: record created Day 101 (death_day
    # 104), clock fires on Day 104 within the same call.
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 0, "water": 0}),
          chars={"vela": _vela()})
    out = server.advance_day(104, "lost in the waste")
    sheet = _sheet(isolate_campaign_dir, "vela")
    assert sheet["hp"]["current"] == -20
    assert "DIES" in out
    assert any(c.get("cause") == "thirst" and c.get("since_day") == 101
               for c in sheet["conditions"])
    # M1 pin: the standing DEPRIVED line renders at most once per cause,
    # not once per caught-up day (4 days here).
    assert out.count("DEPRIVED:") <= 2


# --- Weather nag (W hex-walk): field-mode only ---

def test_weather_nag_fires_in_field_mode(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir, supply=_field_supply(100, {"food": 10, "water": 10}),
          chars={"vela": _vela()})
    out = server.advance_day(101, "desert march")
    assert "**WEATHER**" in out
    assert 'roll(action="weather")' in out          # the daily-roll baton


def test_weather_nag_silent_in_abundant_mode(isolate_campaign_dir):
    _status_md(isolate_campaign_dir, 100)
    _seed(isolate_campaign_dir,
          supply={"mode": "abundant", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.advance_day(101, "resting in the arcology")
    assert "WEATHER" not in out
