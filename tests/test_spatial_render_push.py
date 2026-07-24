"""Spatial-orientation push (2026-07-20): repeated "where are we?" asks in the
Thyricost transcript went unmet because nothing ever offered a map render.
After 5+ site turns without a render, enter_room pushes the exact render call;
render_map stamps last_render_turn to reset the counter."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem


PREP = """## ROOM: room_a
**Floor:** 1
**Coords:** 5,5
**Name:** Room A
**Entrance:** true
**Connections:** e→room_b

## ROOM: room_b
**Floor:** 1
**Coords:** 6,5
**Name:** Room B
**Connections:** w→room_a

## ENCOUNTERS
Roll d6 every 1 turn
"""


@pytest.fixture
def map_sys(tmp_path):
    ms = MapSystem(tmp_path)
    ms.get_day = lambda: 135
    prep = tmp_path / "TEST_SPATIAL_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    ms.init_map_from_prep("spatial_site", "TEST_SPATIAL_PREP.md", "vault")
    return ms


def _turns(ms, name):
    return ms.get_map_state(name).get("current_turn", 0)


def test_no_push_before_threshold(map_sys):
    out = map_sys.enter_room("spatial_site", "room_a")
    assert "SPATIAL CHECK" not in out


def test_push_fires_after_five_unrendered_turns(map_sys):
    map_sys.enter_room("spatial_site", "room_a")
    out = ""
    while _turns(map_sys, "spatial_site") < 5:
        nxt = "room_b" if "room_a" in map_sys.get_map_state(
            "spatial_site").get("party_location", "room_a") else "room_a"
        out = map_sys.enter_room("spatial_site", nxt)
    assert "SPATIAL CHECK" in out
    assert 'map(action="render", map_name="spatial_site")' in out


def test_render_resets_counter(map_sys):
    map_sys.enter_room("spatial_site", "room_a")
    while _turns(map_sys, "spatial_site") < 5:
        nxt = "room_b" if "room_a" in map_sys.get_map_state(
            "spatial_site").get("party_location", "room_a") else "room_a"
        map_sys.enter_room("spatial_site", nxt)
    map_sys.render_map("spatial_site")
    state = map_sys.get_map_state("spatial_site")
    assert state.get("last_render_turn") == state.get("current_turn")
    nxt = "room_b" if "room_a" in state.get("party_location", "room_a") else "room_a"
    out = map_sys.enter_room("spatial_site", nxt)
    assert "SPATIAL CHECK" not in out


def test_legacy_state_without_stamp_defaults_to_zero(map_sys):
    state = map_sys.get_map_state("spatial_site")
    state.pop("last_render_turn", None)
    state["current_turn"] = 49
    map_sys.save_map_state("spatial_site", state)
    out = map_sys.enter_room("spatial_site", "room_a")
    assert "SPATIAL CHECK" in out
