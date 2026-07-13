"""supply() tool — DM levers for S1. Runs against the conftest temp campaign dir."""
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


def _vela(conditions=None, items=None):
    return {"name": "Vela", "wound_table": "biological",
            "hp": {"current": 10, "max": 12},
            "inventory": {"carried": items or []},
            "conditions": conditions or []}


def test_status_abundant_mode(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "abundant", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.supply(action="status")
    assert "abundant" in out.lower()


def test_depart_enters_field_mode_with_pool(isolate_campaign_dir):
    _seed(isolate_campaign_dir, chars={"vela": _vela()})
    out = server.supply(action="depart", food=10, water=12, follower_mouths=2)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    s = meta["supply"]
    assert s["mode"] == "field" and s["pool"] == {"food": 10, "water": 12}
    assert s["follower_mouths"] == 2
    assert "field" in out.lower()


def test_depart_without_pool_is_carried_only(isolate_campaign_dir):
    # Early-game party: no earned base, no pool — carried rations only.
    _seed(isolate_campaign_dir, chars={"vela": _vela()})
    server.supply(action="depart")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] is None and meta["supply"]["mode"] == "field"


def test_arrive_returns_to_abundant(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 1, "water": 1},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.supply(action="arrive")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["mode"] == "abundant"


def test_arrive_with_deprived_clears_records(isolate_campaign_dir):
    # R-S1a: home base = unfettered water/food access, so arriving IS
    # eating/drinking — Deprived records clear on arrive. Non-Deprived
    # conditions survive untouched.
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102},
             {"name": "Deprived", "cause": "starvation", "since_day": 99, "death_day": 102},
             {"name": "Cursed", "cause": "witch", "since_day": 90}]
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela(conditions=conds)})
    out = server.supply(action="arrive")
    sheet = json.loads((isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert sheet["conditions"] == [{"name": "Cursed", "cause": "witch", "since_day": 90}]
    assert "Recovered" in out and "Vela" in out
    assert "supply(" not in out  # recovery just happened — nothing to push


def test_arrive_resets_ledger(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 1, "water": 1},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 97, "consumed": {"vela": {"water": 1}}}},
          chars={"vela": _vela()})
    server.supply(action="arrive")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["ledger"]["consumed"] == {}
    assert meta["supply"]["ledger"]["day"] == meta["campaign_day"]


def test_adjust_pool(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 5, "water": 5},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    server.supply(action="adjust", food=3, water=-2)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 8, "water": 3}


def test_status_field_mode_days_at_burn(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 9, "water": 6},
                  "follower_mouths": 2, "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.supply(action="status")
    assert "~2 day(s)" in out
    assert "3F/3W" in out


def test_adjust_refuses_to_mint_pool_without_earned_base(isolate_campaign_dir):
    # R-S1b / R-S2b: the pool-form of adjust must NOT create a pool when none
    # exists (pool requires an earned base). Updated from old "creates pool"
    # contract which was the stress-test hole closed in S2 Task 3.
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    out = server.supply(action="adjust", food=5, water=8)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] is None, "must not mint a pool without an earned base"
    assert "character=" in out, "refusal must push the carried-credit form"


def test_abundant_status_does_not_report_burn(isolate_campaign_dir):
    # I1: a pool lingering after arrive() must not render the days-at-burn
    # line alongside "not tracked here" — contradictory output.
    _seed(isolate_campaign_dir,
          supply={"mode": "abundant", "pool": {"food": 9, "water": 6},
                  "pool_location": "Ceruline", "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    status = server.supply(action="status")
    assert "not tracked" in status
    assert "at current burn" not in status
    # the pool itself survives in the record — stores still exist at base
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 9, "water": 6}


def test_separated_list_uses_display_names(isolate_campaign_dir):
    # I2: status must render "Vela" (sheet display name), not the raw key "vela"
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 5, "water": 5},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    server.supply(action="separate", character="Vela")
    out = server.supply(action="status")
    assert "Separated from pool: Vela" in out


def test_depart_with_one_arg_notes_the_zeroed_other(isolate_campaign_dir):
    # M1: depart(food=10) still seeds both keys, but says so out loud
    _seed(isolate_campaign_dir, chars={"vela": _vela()})
    out = server.supply(action="depart", food=10)
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] == {"food": 10, "water": 0}
    assert "NOTE: water set to 0" in out
    assert 'supply(action="adjust"' in out


def test_noop_adjust_does_not_create_pool(isolate_campaign_dir):
    # M2: adjust with no args is a status read, not a pool-from-nothing write
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    server.supply(action="adjust")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["pool"] is None


def test_separate_and_rejoin(isolate_campaign_dir):
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": {"food": 5, "water": 5},
                  "follower_mouths": 0, "separated": [],
                  "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela()})
    server.supply(action="separate", character="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert "vela" in meta["supply"]["separated"]
    server.supply(action="rejoin", character="Vela")
    meta = json.loads((isolate_campaign_dir / "characters" / "_meta.json").read_text())
    assert meta["supply"]["separated"] == []


def test_arrive_skips_dead_pcs_tombstone_records_persist(isolate_campaign_dir):
    # Stress-test finding 2026-06-11: arrive was "recovering" corpses.
    # Dead PCs (HP <= -20) keep their Deprived records until resurrection
    # tooling clears them (the tombstone convention from the S1 tick).
    dead = {"name": "Smoke Test", "wound_table": "biological",
            "hp": {"current": -20, "max": 10},
            "inventory": {"carried": []},
            "conditions": [{"name": "Deprived", "cause": "thirst",
                            "since_day": 97, "death_day": 100}]}
    alive = _vela(conditions=[{"name": "Deprived", "cause": "thirst",
                               "since_day": 99, "death_day": 102}])
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"smoke_test": dead, "vela": alive})
    out = server.supply(action="arrive")
    dead_sheet = json.loads(
        (isolate_campaign_dir / "characters" / "smoke_test.json").read_text())
    alive_sheet = json.loads(
        (isolate_campaign_dir / "characters" / "vela.json").read_text())
    assert dead_sheet["conditions"], "tombstone Deprived record must persist on the corpse"
    assert alive_sheet["conditions"] == [], "living PC's Deprived must clear on arrive"
    assert "Smoke Test" not in out, "a corpse must not be reported as recovered"
    assert "Vela" in out


def test_status_field_mode_lists_per_pc_carried(isolate_campaign_dir):
    # Spec section 6: status shows per-PC carried rations. In carried-only
    # (early-game) mode this is the ONLY supply picture the DM has.
    items = [{"name": "Water Rations", "ration_type": "water", "rations": 2, "slots": 1},
             {"name": "Food Rations", "ration_type": "food", "rations": 1, "slots": 1}]
    _seed(isolate_campaign_dir,
          supply={"mode": "field", "pool": None, "follower_mouths": 0,
                  "separated": [], "ledger": {"day": 100, "consumed": {}}},
          chars={"vela": _vela(items=items)})
    out = server.supply(action="status")
    assert "Vela" in out and "1F/2W" in out
