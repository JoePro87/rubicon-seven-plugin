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
        "wounds": 0, "slots_free": 3, "slots_total": 12,
        "items": [
            {"name": "Heavy Crossbow", "where": "carried"},
            {"name": "Bedroll", "where": "carried"},
            {"name": "Spare Boots", "where": "stored_ceruline"},
        ],
    }]
    assert v["in_combat"] is False
    assert v["open_parleys"] == []
    assert "updated_at" in v
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
