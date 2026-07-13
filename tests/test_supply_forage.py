"""S2: supply(action='forage') — d100 per forager, shared discoveries,
yield suggestion pushes, cache chain-roll, scene presentation."""
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


FIELD = {"mode": "field", "pool": None, "follower_mouths": 0,
         "separated": [], "ledger": {"day": 100, "consumed": {}}}
ABUNDANT = {"mode": "abundant", "pool": None, "follower_mouths": 0,
            "separated": [], "ledger": {"day": 100, "consumed": {}}}


def _pc(name):
    return {"name": name, "wound_table": "biological",
            "hp": {"current": 10, "max": 10},
            "inventory": {"carried": []}, "conditions": []}


FAKE_FORAGING = {
    "id": "table-desert-foraging", "die": "d100",
    "entries": [
        {"roll": "01-10", "result": "A resident of the wastes finds you."},
        {"roll": "11-30", "result": "You find nothing."},
        {"roll": 43, "result": "You find 3 rations of dried meat.",
         "yield": {"food": 3}},
        {"roll": 59, "result": "You find d8 jars, each a water ration.",
         "yield": {"water": "d8"}},
        {"roll": 47, "result": "You find d6 Glass Tigers guarding a camel."},
        {"roll": 72, "result": "You discover a Small Survival Cache.",
         "cache": "Small"},
    ],
}
FAKE_CACHE = {
    "id": "table-treasure-cache-survival",
    "entries": [{"size": "Small",
                 "contents": ["D6 Water Rations", "D6 Dried Food Rations",
                              "Medgel (D10 Heal)"]}],
}


def _patch_tables(monkeypatch):
    def fake_get(table_id, section="rolling"):
        return {"table-desert-foraging": FAKE_FORAGING,
                "table-treasure-cache-survival": FAKE_CACHE}.get(table_id)
    monkeypatch.setattr(server, "_get_rulebook_table", fake_get)


def _patch_rolls(monkeypatch, d100s, inner=4):
    seq = list(d100s)
    def fake_roll(notation):
        if notation == "d100" and seq:
            return seq.pop(0)
        return inner
    monkeypatch.setattr(server, "_forage_roll", fake_roll)


def test_forage_requires_field_mode(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, supply=ABUNDANT, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "field" in out.lower() and "depart" in out


def test_forage_yield_pushes_filled_credit_call(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [43])
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "3 rations of dried meat" in out
    # push_call always double-quotes values: food="3"
    assert 'supply(action="adjust", character="Vela", food="3")' in out
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["inventory"]["carried"] == [], "forage must NOT auto-credit (R-S2a)"


def test_forage_dice_yield_is_rolled(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [59], inner=5)
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "water d8=5" in out
    # push_call double-quotes: water="5"
    assert 'water="5"' in out


def test_forage_scene_presents_no_credit(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [47], inner=2)
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "d6=2 Glass Tigers" in out
    assert 'supply(action="adjust"' not in out


def test_forage_duplicates_are_shared_discovery(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [43, 43])
    _seed(isolate_campaign_dir, supply=FIELD,
          chars={"vela": _pc("Vela"), "rook": _pc("Rook")})
    out = server.supply(action="forage", character="Vela, Rook")
    assert "shared discovery" in out
    assert out.count("dried meat") == 1
    assert out.count('supply(action="adjust"') == 1


def test_forage_cache_chain_rolls_and_credits_rations(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [72], inner=4)
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "Small Survival Cache" in out
    assert "D6 Water Rations [=4]" in out and "Medgel (D10 Heal)" in out
    # push_call double-quotes: water="4", food="4"
    assert 'water="4"' in out and 'food="4"' in out


def test_forage_unknown_character_errors(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch)
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Nobody")
    assert "not found" in out.lower()


def test_forage_refuses_vehicle_forager(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch)
    _seed(isolate_campaign_dir, supply=FIELD,
          chars={"vela": _pc("Vela"),
                 "the_crawler": {"name": "The Crawler", "type": "vehicle",
                                 "wound_table": "mechanical", "hp": None,
                                 "inventory": {"carried": []}}})
    out = server.supply(action="forage", character="The Crawler")
    assert "vehicle" in out and "can't forage" in out


def test_forage_refuses_dead_forager(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch)
    dead = _pc("Vela")
    dead["hp"]["current"] = -20
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": dead})
    out = server.supply(action="forage", character="Vela")
    assert "dead" in out


def test_forage_reminds_encounter_check(isolate_campaign_dir, monkeypatch):
    _patch_tables(monkeypatch); _patch_rolls(monkeypatch, [15])
    _seed(isolate_campaign_dir, supply=FIELD, chars={"vela": _pc("Vela")})
    out = server.supply(action="forage", character="Vela")
    assert "encounter check" in out.lower()
