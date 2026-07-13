# tests/test_player_view_leak_canary.py
"""THE test that matters: plant secrets in every hidden-content home, emit the
player view, assert none of the distinctive strings surface in any artifact."""
import json
from pathlib import Path

import player_view

SECRET_ANTAGONIST = "ZALGO-PROPHET-SEED-XYZZY"
SECRET_PREP = "HIDDEN-LICH-PHYLACTERY-PLUGH"
SECRET_CLOCK = "PURPOSE-CLOCK-INTERNAL-FNORD"


def test_planted_secrets_never_reach_player_artifacts(tmp_path):
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "_meta.json").write_text(
        json.dumps({"campaign_day": 5}), encoding="utf-8")
    (tmp_path / "ANTAGONIST_CULTIVATION.md").write_text(
        f"## Seed\n{SECRET_ANTAGONIST}\n<!-- spine: due_day=9 -->", encoding="utf-8")
    (tmp_path / "TEST_PREP.md").write_text(
        f"## ROOM: crypt\n### Secrets\n{SECRET_PREP}\n", encoding="utf-8")
    (tmp_path / "npc_states.json").write_text(json.dumps(
        {"npcs": {"x": {"open_purpose": SECRET_CLOCK, "purpose_clock": {"due_day": 9}}}}),
        encoding="utf-8")
    (tmp_path / "game_state.json").write_text(json.dumps(
        {"active_location_name": "Somewhere", "active_prep_file": "TEST_PREP.md",
         "active_combat": None}), encoding="utf-8")

    player_view.write_player_view(tmp_path, fog_map_text="(no active map)")

    view_text = (tmp_path / "player_view.json").read_text(encoding="utf-8")
    map_text = (tmp_path / "player_map.txt").read_text(encoding="utf-8")
    for secret in (SECRET_ANTAGONIST, SECRET_PREP, SECRET_CLOCK):
        assert secret not in view_text
        assert secret not in map_text
    # active prep may surface by NAME only — never by content
    assert "TEST_PREP" in view_text


def test_nameless_inventory_entry_never_dumps_dict_contents(tmp_path):
    """CRITICAL regression lock (review catch): a dict fallback like
    `entry.get("name") or str(entry)` would serialize the WHOLE entry --
    including notes/engine_tags, where a DM secret can live -- into the
    player artifact when the entry has no "name" field. Fix: nameless dict
    entries fall back to a fixed placeholder, never str(dict)."""
    SECRET_ITEM_NOTE = "ITEM-NOTE-NEEDLE-ZORK"
    (tmp_path / "characters").mkdir()
    (tmp_path / "characters" / "_meta.json").write_text(
        json.dumps({"campaign_day": 5}), encoding="utf-8")
    (tmp_path / "characters" / "kess.json").write_text(json.dumps({
        "name": "Kess",
        "inventory": {"carried": [
            {"notes": SECRET_ITEM_NOTE, "engine_tags": ["cursed"]},
        ]},
    }), encoding="utf-8")
    (tmp_path / "game_state.json").write_text(json.dumps(
        {"active_location_name": "Somewhere", "active_prep_file": None,
         "active_combat": None}), encoding="utf-8")

    player_view.write_player_view(tmp_path, fog_map_text="(no active map)")

    view_text = (tmp_path / "player_view.json").read_text(encoding="utf-8")
    assert SECRET_ITEM_NOTE not in view_text
    assert "engine_tags" not in view_text
    view = json.loads(view_text)
    assert view["party"][0]["items"] == [{"name": "(unnamed item)",
                                          "where": "carried"}]


def test_fog_render_never_leaks_room_contents(tmp_path):
    """Final-review carry-forward: run render_fog itself against a secret-bearing
    EXPLORED room — if _render_ascii ever starts drawing contents, this trips."""
    from map_system import MapSystem
    ms = MapSystem(tmp_path)
    ms.maps_dir.mkdir(parents=True, exist_ok=True)
    rooms = {
        "hall": {"id": "hall", "name": "Great Hall", "floor": 1, "coords": [5, 5],
                 "is_secret": False, "discovery_state": "explored", "search_state": "unsearched",
                 "connections": {"north": "crypt"},
                 "notes": ["NOTE-NEEDLE-XYZZY"], "loot": ["LOOT-NEEDLE-PLUGH"],
                 "hazards": ["HAZARD-NEEDLE-FNORD"], "npcs": ["NPC-NEEDLE-QUUX"],
                 "secret_connections": {"s1": {"target": "crypt", "found": False,
                                               "discovery": "SECRET-HINT-NEEDLE-GRUE"}}},
        "crypt": {"id": "crypt", "name": "HIDDEN CRYPT NAME", "floor": 1, "coords": [5, 4],
                  "is_secret": True, "discovery_state": "unknown", "search_state": "unsearched",
                  "connections": {}},
    }
    (ms.maps_dir / "vault_map.json").write_text(
        json.dumps({"map_name": "vault", "rooms": rooms, "party_location": "hall",
                    "party_floor": 1, "current_turn": 1}), encoding="utf-8")
    out = ms.render_fog("vault")
    assert "Great Hall" in out
    for needle in ("NOTE-NEEDLE-XYZZY", "LOOT-NEEDLE-PLUGH", "HAZARD-NEEDLE-FNORD",
                   "NPC-NEEDLE-QUUX", "SECRET-HINT-NEEDLE-GRUE", "HIDDEN CRYPT NAME"):
        assert needle not in out
