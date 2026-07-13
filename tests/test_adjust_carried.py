"""S2: supply(adjust, character=...) credits carried items; pool form refuses
when no pool has been earned (R-S1b / R-S2b)."""
import json
import server


def _seed(dirpath, supply=None, chars=None):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True)
    meta = {"version": 1, "campaign_day": 100}
    if supply is not None:
        meta["supply"] = supply
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    for key, sheet in (chars or {}).items():
        (chars_dir / f"{key}.json").write_text(json.dumps(sheet))


FIELD_NO_POOL = {"mode": "field", "pool": None, "follower_mouths": 0,
                 "separated": [], "ledger": {"day": 100, "consumed": {}}}


def _vela(items=None):
    return {"name": "Vela", "wound_table": "biological",
            "hp": {"current": 10, "max": 12},
            "inventory": {"carried": items or []}, "conditions": []}


def test_adjust_with_character_credits_carried_and_persists(isolate_campaign_dir):
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": _vela()})
    out = server.supply(action="adjust", character="Vela", water=4, food=2)
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    waters = [i for i in sheet["inventory"]["carried"] if i.get("ration_type") == "water"]
    foods = [i for i in sheet["inventory"]["carried"] if i.get("ration_type") == "food"]
    assert sorted(i["rations"] for i in waters) == [1, 3]
    assert [i["rations"] for i in foods] == [2]
    assert "+4 water" in out and "+2 food" in out and "Slots:" in out


def test_adjust_with_character_debits(isolate_campaign_dir):
    items = [{"name": "Water Rations", "ration_type": "water", "rations": 3, "slots": 1}]
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": _vela(items)})
    server.supply(action="adjust", character="Vela", water=-2)
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["inventory"]["carried"][0]["rations"] == 1


def test_adjust_pool_form_refuses_without_earned_base(isolate_campaign_dir):
    # The 2026-06-11 stress-test hole: adjust minted a pool from nothing.
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": _vela()})
    out = server.supply(action="adjust", water=1, food=1)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] is None, "must NOT mint a pool without an earned base"
    assert 'character=' in out, "refusal must push the carried-credit form"


def test_adjust_pool_form_still_works_with_pool(isolate_campaign_dir):
    sup = dict(FIELD_NO_POOL, pool={"food": 2, "water": 2})
    _seed(isolate_campaign_dir, supply=sup, chars={"vela": _vela()})
    server.supply(action="adjust", water=3)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 2, "water": 5}


def test_adjust_unknown_character_errors(isolate_campaign_dir):
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": _vela()})
    out = server.supply(action="adjust", character="Nobody", water=1)
    assert "not found" in out.lower()


def test_adjust_refuses_vehicle_credit(isolate_campaign_dir):
    # Vehicles are loaded from vehicles/*.json and merged into the roster, but
    # the daily tick and arrive both SKIP them — crediting one is a food black
    # hole. The adjust character form must refuse and push the PC-pack form.
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": _vela()})
    vehicles_dir = isolate_campaign_dir / "vehicles"
    vehicles_dir.mkdir(exist_ok=True)
    crawler = {"name": "The Crawler", "type": "vehicle",
               "wound_table": "mechanical", "hp": None,
               "inventory": {"carried": []}}
    (vehicles_dir / "the_crawler.json").write_text(json.dumps(crawler))
    out = server.supply(action="adjust", character="The Crawler", water=4)
    assert "vehicle" in out.lower(), "refusal must explain the vehicle rule"
    assert "character=" in out, "refusal must push the carried-credit form"
    sheet = json.loads((vehicles_dir / "the_crawler.json").read_text())
    assert sheet["inventory"]["carried"] == [], "vehicle sheet must be unchanged"


def test_adjust_corpse_credit_warns_but_works(isolate_campaign_dir):
    # Crediting a dead PC's pack is allowed (looting/transfer is DM freedom)
    # but must never be silent — the tick won't consume a corpse's rations.
    dead = _vela()
    dead["hp"] = {"current": -20, "max": 12}
    _seed(isolate_campaign_dir, supply=FIELD_NO_POOL, chars={"vela": dead})
    out = server.supply(action="adjust", character="Vela", food=3)
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    foods = [i for i in sheet["inventory"]["carried"] if i.get("ration_type") == "food"]
    assert sum(i["rations"] for i in foods) == 3, "credit still lands (allowed)"
    assert "dead" in out.lower(), "output must warn the PC is dead"
