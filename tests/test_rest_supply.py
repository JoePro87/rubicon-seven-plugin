"""rest() x S1: condition-Deprived blocks healing; field rests consume + credit the ledger."""
import json
import server
from tests.test_supply_tool import _seed, _vela


def _field(day=100, pool=None):
    return {"mode": "field", "pool": pool, "pool_location": "wagon",
            "follower_mouths": 0, "separated": [],
            "ledger": {"day": day, "consumed": {}}}


def test_condition_deprived_blocks_short_rest(isolate_campaign_dir):
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": _vela(conditions=conds)})
    out = server.rest(action="short", characters="Vela")
    assert "cannot regain HP" in out and "thirst" in out.lower()


def test_condition_deprived_blocks_long_rest_hp(isolate_campaign_dir):
    conds = [{"name": "Deprived", "cause": "starvation", "since_day": 99, "death_day": 102}]
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": _vela(conditions=conds)})
    out = server.rest(action="long", characters="Vela")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["hp"]["current"] == 10  # NOT restored to 12


def test_wound_deprived_still_blocks(isolate_campaign_dir):
    # Regression: the Supercoolant Leak path must keep working
    wounds = [{"name": "Supercoolant Leak", "deprived": True, "slots": 1,
               "effect": "Deprived; cannot regain HP until this Wound is fixed"}]
    sheet = _vela()
    sheet["wounds"] = wounds
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": sheet})
    out = server.rest(action="short", characters="Vela")
    assert "cannot regain HP" in out


def test_field_short_rest_consumes_and_credits_ledger(isolate_campaign_dir):
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": _vela()})
    server.rest(action="short", characters="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    pool = meta["supply"]["pool"]
    assert pool["food"] + pool["water"] == 9  # exactly one ration consumed
    credited = meta["supply"]["ledger"]["consumed"]["vela"]
    assert sum(credited.values()) == 1


def test_field_long_rest_consumes_water_and_food(isolate_campaign_dir):
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": _vela()})
    server.rest(action="long", characters="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 4, "water": 4}
    assert meta["supply"]["ledger"]["consumed"]["vela"] == {"water": 1, "food": 1}


def test_abundant_rest_is_free(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "abundant", "pool": {"food": 5, "water": 5},
                  "pool_location": "Ceruline", "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    server.rest(action="long", characters="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 5, "water": 5}


def test_carried_only_rest_persists_consumption(isolate_campaign_dir):
    # C1 regression: carried-ration consumption must be SAVED to the sheet,
    # not silently rolled back on next load (free rations + bogus ledger).
    items = [{"name": "Water Rations", "ration_type": "water", "rations": 3, "slots": 1},
             {"name": "Food Rations", "ration_type": "food", "rations": 3, "slots": 1}]
    _seed(isolate_campaign_dir, supply=_field(pool=None),
          chars={"vela": _vela(items=items)})
    server.rest(action="long", characters="Vela")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    carried = sheet["inventory"]["carried"]
    assert carried[0]["rations"] == 2 and carried[1]["rations"] == 2


def test_water_only_pc_long_rest_charges_only_water(isolate_campaign_dir):
    # I2 regression: a needs_food=False PC (Creenash) pays no meal at long rest.
    sheet = _vela()
    sheet["survival"] = {"needs_food": False}
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 5, "water": 5}),
          chars={"vela": sheet})
    server.rest(action="long", characters="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 5, "water": 4}
    credited = meta["supply"]["ledger"]["consumed"]["vela"]
    assert credited.get("food", 0) == 0


def test_short_rest_water_shortfall_names_food_alternative(isolate_campaign_dir):
    # Book: a Short Rest ration may be water OR food. When the water-first
    # default comes up SHORT but food IS available, the line must say so.
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 4, "water": 0}),
          chars={"vela": _vela()})
    out = server.rest(action="short", characters="Vela")
    short_line = next(l for l in out.split("\n") if ": SHORT" in l)
    assert "food instead" in short_line
    assert 'supply(action="status")' in out  # push stays


def test_field_rest_with_nothing_to_consume_warns(isolate_campaign_dir):
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 0, "water": 0}),
          chars={"vela": _vela()})
    out = server.rest(action="short", characters="Vela")
    assert "no ration" in out.lower() or "0 food" in out or "short" in out.lower()
    assert 'supply(action="status")' in out  # push the lever


# ---------------------------------------------------------------------------
# E3 Janus Lenses (hp_regain_half) + Fabricator Stoma (double_rations)
# ---------------------------------------------------------------------------

def _janus_cond(day=99):
    return {"name": "Janus Lenses", "cause": "nanomachine", "since_day": day,
            "effects": {"hp_regain_half": True}}


def _stoma_cond(day=99):
    return {"name": "Fabricator Stoma", "cause": "nanomachine", "since_day": day,
            "effects": {"double_rations": True}}


def test_janus_halves_long_rest_hp(isolate_campaign_dir):
    v = _vela(conditions=[_janus_cond()])
    v["hp"] = {"current": 4, "max": 12}
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 9, "water": 9}),
          chars={"vela": v})
    server.rest(action="long", characters="Vela")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    # heal would be 12-4=8; half (round down) = 4 -> 4 + 4 = 8
    assert sheet["hp"]["current"] == 8


def test_janus_half_regain_min_one(isolate_campaign_dir):
    v = _vela(conditions=[_janus_cond()])
    v["hp"] = {"current": 11, "max": 12}   # heal would be 1; half -> min 1
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 9, "water": 9}),
          chars={"vela": v})
    server.rest(action="long", characters="Vela")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["hp"]["current"] == 12


def test_no_hp_regain_beats_half(isolate_campaign_dir):
    conds = [_janus_cond(),
             {"name": "Dreamcage", "cause": "nanomachine", "since_day": 99,
              "effects": {"no_hp_regain": True}}]
    v = _vela(conditions=conds)
    v["hp"] = {"current": 4, "max": 12}
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 9, "water": 9}),
          chars={"vela": v})
    out = server.rest(action="long", characters="Vela")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["hp"]["current"] == 4          # NOT restored at all
    assert "cannot regain HP" in out


def test_stoma_doubles_daily_needs():
    import survival as sv
    base = sv.daily_needs({"wound_table": "biological"})
    doubled = sv.daily_needs({"wound_table": "biological",
                              "conditions": [_stoma_cond()]})
    assert doubled["water"] == base["water"] * 2
    assert doubled["food"] == base["food"] * 2


def test_stoma_doubles_rest_consume(isolate_campaign_dir):
    v = _vela(conditions=[_stoma_cond()])
    _seed(isolate_campaign_dir, supply=_field(pool={"food": 10, "water": 10}),
          chars={"vela": v})
    server.rest(action="long", characters="Vela")   # long = 1 water + 1 food each
    meta = json.loads(
        (isolate_campaign_dir / "characters" / "_meta.json").read_text())
    consumed = meta["supply"]["ledger"]["consumed"]
    # doubled: 2 water + 2 food credited for vela
    assert consumed["vela"]["water"] == 2
    assert consumed["vela"]["food"] == 2
