import json
from pathlib import Path
import pytest
from map_system import MapSystem


def _mk_state(tmp_path, rooms, party_location):
    ms = MapSystem(tmp_path)
    ms.maps_dir.mkdir(parents=True, exist_ok=True)
    state = {"map_name": "testvault", "rooms": rooms, "party_location": party_location,
             "party_floor": 1, "current_turn": 3}
    (ms.maps_dir / "testvault_map.json").write_text(json.dumps(state), encoding="utf-8")
    return ms


# Real state shape, matching what init_map_from_prep / _parse_rooms_from_prep
# actually persist: 'id', 'coords' ([x, y] ints), 'search_state', and
# direction-keyed connections (single target per direction, not a list).
ROOMS = {
    "entry":  {"id": "entry", "name": "Entry Hall", "floor": 1, "coords": [5, 5],
               "is_secret": False, "is_entrance": True, "discovery_state": "explored",
               "search_state": "unsearched",
               "connections": {"north": "shrine", "east": "vault_door"}},
    "shrine": {"id": "shrine", "name": "Shrine", "floor": 1, "coords": [5, 4],
               "is_secret": False, "discovery_state": "noticed", "search_state": "unsearched",
               "connections": {"south": "entry"}},
    "vault_door": {"id": "vault_door", "name": "Vault Door", "floor": 1, "coords": [6, 5],
               "is_secret": False, "discovery_state": "unknown", "search_state": "unsearched",
               "connections": {"west": "entry"}},
    "hidden": {"id": "hidden", "name": "SECRET CACHE ROOM", "floor": 1, "coords": [7, 7],
               "is_secret": True, "discovery_state": "unknown", "search_state": "unsearched",
               "connections": {}},
}


def test_fog_hides_unknown_and_secret_rooms(tmp_path):
    ms = _mk_state(tmp_path, ROOMS, "entry")
    out = ms.render_fog("testvault")
    assert "Entry Hall" in out
    assert "Shrine" in out                 # noticed → visible (marked unexplored)
    assert "Vault Door" not in out         # unknown → hidden
    assert "SECRET CACHE ROOM" not in out  # secret+unknown → hidden


def test_fog_marks_position_and_noticed(tmp_path):
    ms = _mk_state(tmp_path, ROOMS, "entry")
    out = ms.render_fog("testvault")
    assert "⊕" in out          # party position marker
    assert "?" in out          # unexplored-but-noticed marker or unknown-exit stub


def test_fog_no_map(tmp_path):
    ms = MapSystem(tmp_path)
    assert "no active map" in ms.render_fog("nope").lower()


# Coords-less rooms (older/malformed saves) exercise the degraded list-render
# fallback path — same fixture shape the original brief drafted, now repurposed
# to cover the one case _render_ascii can't handle (no 'coords').
ROOMS_NO_COORDS = {
    "entry":  {"name": "Entry Hall", "floor": 1, "is_secret": False, "is_entrance": True,
               "discovery_state": "explored", "connections": {"basic": ["shrine", "vault_door"]}},
    "shrine": {"name": "Shrine", "floor": 1, "is_secret": False,
               "discovery_state": "noticed", "connections": {"basic": ["entry"]}},
    "vault_door": {"name": "Vault Door", "floor": 1, "is_secret": False,
               "discovery_state": "unknown", "connections": {"basic": ["entry"]}},
    "hidden": {"name": "SECRET CACHE ROOM", "floor": 1, "is_secret": True,
               "discovery_state": "unknown", "connections": {"basic": []}},
}


def test_fog_fallback_list_when_coords_absent(tmp_path):
    ms = _mk_state(tmp_path, ROOMS_NO_COORDS, "entry")
    out = ms.render_fog("testvault")
    assert "Entry Hall" in out
    assert "Shrine" in out
    assert "Vault Door" not in out
    assert "SECRET CACHE ROOM" not in out
    assert "⊕" in out
    assert "?" in out


def test_fog_long_room_names_get_full_name_legend(tmp_path):
    """Grid boxes truncate names >14 chars; the fog render must append a
    full-name legend so the player still sees the real names (2026-07-07)."""
    rooms = {
        "entry": {"id": "entry", "name": "Entry Hall", "floor": 1, "coords": [5, 5],
                  "is_secret": False, "is_entrance": True, "discovery_state": "explored",
                  "search_state": "unsearched",
                  "connections": {"north": "choir"}},
        "choir": {"id": "choir", "name": "Chamber of the Unsleeping Choir", "floor": 1,
                  "coords": [5, 4], "is_secret": False, "discovery_state": "explored",
                  "search_state": "unsearched", "connections": {"south": "entry"}},
    }
    ms = _mk_state(tmp_path, rooms, "entry")
    out = ms.render_fog("testvault")
    assert "Chamber of the Unsleeping Choir" in out  # full name somewhere
    # short names that fit their box do NOT enter the legend
    legend = out[out.rfind("FULL NAMES"):]
    assert "Entry Hall" not in legend


def test_fog_no_legend_when_all_names_fit(tmp_path):
    ms = _mk_state(tmp_path, ROOMS, "entry")
    out = ms.render_fog("testvault")
    assert "FULL NAMES" not in out
