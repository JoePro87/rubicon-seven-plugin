import json
from pathlib import Path
import pytest

import player_view


@pytest.fixture
def camp(tmp_path):
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "_meta.json").write_text(json.dumps({
        "campaign_day": 132, "supply": {"mode": "abundant", "pool": None, "pool_location": "Ceruline"}
    }), encoding="utf-8")
    (tmp_path / "characters" / "kess.json").write_text(json.dumps({
        "name": "Kess", "hp": {"current": 29, "max": 29}, "av": {"base": 18, "source": "armor"},
        "wounds": [], "slots_free": 3, "slot_capacity_total": 12,
        "inventory": {
            "carried": [
                {"name": "Heavy Crossbow", "slots": 4, "notes": "SECRET-DO-NOT-SURFACE"},
                "Bedroll",
            ],
            "stored_ceruline": [{"name": "Spare Boots"}],
        },
    }), encoding="utf-8")
    (tmp_path / "party.json").write_text(json.dumps({"wealth": {"tokens": 22280}}), encoding="utf-8")
    (tmp_path / "game_state.json").write_text(json.dumps({
        "active_location_name": "Dust Pilgrim's Rest", "active_prep_file": None, "active_combat": None
    }), encoding="utf-8")
    return tmp_path


def test_view_whitelist_fields(camp):
    v = player_view.build_view(camp)
    assert v["day"] == 132
    assert v["location"] == "Dust Pilgrim's Rest"
    assert v["wealth_tokens"] == 22280
    assert v["supply"]["mode"] == "abundant"
    assert v["party"] == [{
        "name": "Kess", "hp": 29, "hp_max": 29, "av": 18,
        "wounds": 0, "conditions": [], "slots_free": 3, "slots_total": 12,
        "items": [
            {"name": "Heavy Crossbow", "where": "carried"},
            {"name": "Bedroll", "where": "carried"},
            {"name": "Spare Boots", "where": "stored_ceruline"},
        ],
    }]
    assert v["in_combat"] is False
    assert v["open_parleys"] == []
    assert v["last_events"] == []  # no ticker ledger yet
    assert "updated_at" in v


def test_conditions_and_last_events_surface(camp):
    """Per-PC condition names and the top-level mechanics deltas cross into the
    view (both are player-known: PC numbers are theirs, enemy entries are
    qualitative)."""
    import mechanics_ticker
    (camp / "characters" / "kess.json").write_text(json.dumps({
        "name": "Kess", "hp": {"current": 18, "max": 29}, "av": {"base": 18},
        "conditions": [{"name": "Burning", "cause": "torch"},
                       {"name": "Deprived"}],
    }), encoding="utf-8")
    mechanics_ticker.record_events(camp, [
        {"kind": "pc_damage", "name": "Kess", "amount": 7, "dtype": "fire",
         "old_hp": 25, "new_hp": 18, "hp_max": 29}])
    v = player_view.build_view(camp)
    kess = v["party"][0]
    assert kess["conditions"] == ["Burning", "Deprived"]
    assert v["last_events"][-1]["name"] == "Kess"
    assert v["last_events"][-1]["kind"] == "pc_damage"
    # items carry name/where/effect ONLY -- notes/engine_tags/stats never surface
    assert "SECRET-DO-NOT-SURFACE" not in json.dumps(v)


def test_item_effects_and_cybernetics_surface(camp):
    """2026-07-07 owner ask: the dashboard must show what items DO. The
    effect* power fields cross into the artifact; notes still never do."""
    (camp / "characters" / "kess.json").write_text(json.dumps({
        "name": "Kess", "hp": {"current": 29, "max": 29}, "av": {"base": 18},
        "inventory": {"carried": [
            {"name": "Whisper Lens", "effect": "See through fog",
             "effect_daily": "reveal one hidden door",
             "notes": "SECRET-DO-NOT-SURFACE"},
        ]},
        "augmentations": {"DEX": [{"name": "Reflex Splice",
                                   "effect": "+1 DEX", "stat_bonus": 1}]},
    }), encoding="utf-8")
    v = player_view.build_view(camp)
    items = v["party"][0]["items"]
    lens = next(i for i in items if i["name"] == "Whisper Lens")
    assert lens["effect"] == "See through fog · daily: reveal one hidden door"
    splice = next(i for i in items if i["name"] == "Reflex Splice")
    assert splice["where"] == "cybernetic"
    assert splice["effect"] == "+1 DEX"
    assert "SECRET-DO-NOT-SURFACE" not in json.dumps(v)


def test_cold_start_empty_campaign(tmp_path):
    v = player_view.build_view(tmp_path)   # nothing exists
    assert v["day"] is None and v["party"] == [] and v["location"] is None


def test_write_is_atomic_and_valid_json(camp):
    player_view.write_player_view(camp, fog_map_text="(no active map)")
    on_disk = json.loads((camp / "player_view.json").read_text(encoding="utf-8"))
    assert on_disk["day"] == 132
    assert (camp / "player_map.txt").read_text(encoding="utf-8") == "(no active map)"
    assert not list(camp.glob("player_view.json.tmp"))


def test_journal_from_active_site_ledger(tmp_path):
    import json as _json
    (tmp_path / "maps").mkdir()
    (tmp_path / "characters").mkdir()
    (tmp_path / "maps" / "old_site_map.json").write_text(_json.dumps(
        {"map_name": "old_site", "last_seen_day": 100,
         "revealed_ledger": [{"fact": "Old fact", "day": 100}]}), encoding="utf-8")
    (tmp_path / "maps" / "thyricost_map.json").write_text(_json.dumps(
        {"map_name": "thyricost", "last_seen_day": 135,
         "revealed_ledger": [{"fact": "First fact", "day": 134},
                             {"fact": "Second fact", "day": 135}],
         "tracks": [{"id": "t1", "title": "T1", "status": "OPEN", "stand": "s"},
                    {"id": "t2", "title": "T2", "status": "RESOLVED", "stand": "s"}]}),
        encoding="utf-8")
    view = player_view.build_view(tmp_path)
    j = view["journal"]
    assert j["site"] == "thyricost"
    assert j["entries"][0]["fact"] == "Second fact"  # newest first
    assert [t["title"] for t in j["tracks"]] == ["T1"]  # resolved excluded


def test_journal_absent_maps_dir_is_empty(tmp_path):
    (tmp_path / "characters").mkdir()
    assert player_view.build_view(tmp_path)["journal"] == {}
