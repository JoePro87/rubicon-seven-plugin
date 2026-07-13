"""C13 — XP/carousing advancement loop surfaced at the settlement seam.

The book's ONLY advancement path (trade Exotica at a settlement = 1 XP each;
carousing = +1 XP + a d20+EGO mishap on table-carousing) had engine machinery
but zero surfacing. supply(action="arrive") — the settlement-arrival seam that
already pushes the settlement-changes roll — now also pushes the XP/carousing
loop on every arrival. Push-only, fail-soft; no new roll/generate action.
"""
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


def _vela():
    return {"name": "Vela", "wound_table": "biological",
            "hp": {"current": 10, "max": 12},
            "inventory": {"carried": []}, "conditions": []}


def _arrive(dirpath):
    _seed(dirpath,
          supply={"mode": "field", "pool": {"food": 1, "water": 1},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    return server.supply(action="arrive")


def test_arrive_pushes_gain_xp_for_exotica(isolate_campaign_dir):
    out = _arrive(isolate_campaign_dir)
    assert 'character(action="gain_xp"' in out
    assert "Exotica" in out


def test_arrive_pushes_carousing_table(isolate_campaign_dir):
    out = _arrive(isolate_campaign_dir)
    assert 'rulebook(action="get", id="table-carousing"' in out
    assert "d20+EGO" in out


def test_carousing_table_exists_in_rulebook_data():
    import engine_core
    d = json.loads(engine_core.read_rules_data("rulebook/tables.json"))
    t = next(x for x in d["rolling_tables"] if x["id"] == "table-carousing")
    assert t["die"] == "d20" and len(t["entries"]) >= 20
