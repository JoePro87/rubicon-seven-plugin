"""Connection-based auto-layout for fog/DM maps whose rooms share coords.

The bug: `_parse_rooms_from_prep` defaults every room's coords to [5, 5] when
the prep has no `**Coords:**` lines. `_render_ascii` then stacks every box on
one grid cell (last drawn wins), collapsing an 11-room vault to one box. These
tests pin the deterministic render-time relayout that fixes it, and guard that
maps with genuine distinct coords are left untouched.
"""
import json
from pathlib import Path
import pytest
from map_system import MapSystem


def _mk_state(tmp_path, rooms, party_location, name="testvault"):
    ms = MapSystem(tmp_path)
    ms.maps_dir.mkdir(parents=True, exist_ok=True)
    state = {"map_name": name, "rooms": rooms, "party_location": party_location,
             "party_floor": 1, "current_turn": 3,
             "floors": {"1": {"name": "Floor 1"}}}
    (ms.maps_dir / f"{name}_map.json").write_text(json.dumps(state), encoding="utf-8")
    return ms


def _room(rid, name, conns, coords=None, entrance=False, disc="explored"):
    r = {"id": rid, "name": name, "floor": 1, "coords": coords or [5, 5],
         "is_secret": False, "is_entrance": entrance, "discovery_state": disc,
         "search_state": "unsearched", "connections": conns}
    return r


# Five rooms in a plus/line shape, ALL defaulted to [5, 5]. Chain:
# entry -e-> east_hall -e-> far_hall ; entry -n-> north_room ; entry -s-> south_room
def _stacked_rooms():
    return {
        "entry":      _room("entry", "Entry Hall",
                            {"east": "east_hall", "north": "north_room", "south": "south_room"},
                            entrance=True),
        "east_hall":  _room("east_hall", "East Hall", {"west": "entry", "east": "far_hall"}),
        "far_hall":   _room("far_hall", "Far Hall", {"west": "east_hall"}),
        "north_room": _room("north_room", "North Room", {"south": "entry"}),
        "south_room": _room("south_room", "South Room", {"north": "entry"}),
    }


def _glyph_in_boxes(out, glyph):
    """Count a party glyph only within room boxes, excluding the footer legend
    line (which always spells out '<glyph> Party')."""
    return sum(line.count(glyph) for line in out.splitlines() if "Party" not in line)


def test_stacked_rooms_render_as_distinct_boxes_fog(tmp_path):
    ms = _mk_state(tmp_path, _stacked_rooms(), "entry")
    out = ms.render_fog("testvault")
    assert out.count("╔") == 5, f"expected 5 distinct boxes, got:\n{out}"
    assert _glyph_in_boxes(out, "⊕") == 1, f"party marker must appear once in a box:\n{out}"
    for nm in ("Entry Hall", "East Hall", "Far Hall", "North Room", "South Room"):
        assert nm in out


def test_distinct_authored_coords_not_relayouted(tmp_path):
    # Two rooms with real, distinct coords — no collision, so no relayout.
    rooms = {
        "a": _room("a", "Alpha", {"east": "b"}, coords=[2, 3]),
        "b": _room("b", "Beta", {"west": "a"}, coords=[3, 3]),
    }
    ms = _mk_state(tmp_path, rooms, "a")
    out = ms.render_fog("testvault")
    assert out.count("╔") == 2
    # Alpha is west of Beta on the same row: Alpha's box must start left of Beta's.
    lines = out.splitlines()
    row = next(l for l in lines if "Alpha" in l and "Beta" in l)
    assert row.index("Alpha") < row.index("Beta")


def test_dict_shaped_connection_targets(tmp_path):
    rooms = _stacked_rooms()
    # Rewrite entry->east_hall as a dict target ({'room': ..., 'floor': ...}).
    rooms["entry"]["connections"]["east"] = {"room": "east_hall", "floor": 1}
    rooms["east_hall"]["connections"]["west"] = {"room": "entry", "floor": 1}
    ms = _mk_state(tmp_path, rooms, "entry")
    out = ms.render_fog("testvault")
    assert out.count("╔") == 5
    assert _glyph_in_boxes(out, "⊕") == 1


def test_disconnected_room_still_appears(tmp_path):
    rooms = _stacked_rooms()
    rooms["orphan"] = _room("orphan", "Orphan Cell", {})  # no connections, coords [5,5]
    ms = _mk_state(tmp_path, rooms, "entry")
    out = ms.render_fog("testvault")
    assert out.count("╔") == 6
    assert "Orphan Cell" in out


def test_deterministic_output(tmp_path):
    ms = _mk_state(tmp_path, _stacked_rooms(), "entry")
    a = ms.render_fog("testvault")
    b = ms.render_fog("testvault")
    assert a == b


def test_dm_render_map_also_destacks(tmp_path):
    ms = _mk_state(tmp_path, _stacked_rooms(), "entry")
    out = ms.render_map("testvault", floor=1)
    assert out.count("╔") == 5, f"DM render_map must de-stack too:\n{out}"
    assert _glyph_in_boxes(out, "◈") == 1


def test_auto_layout_helper_distinct_cells(tmp_path):
    ms = MapSystem(tmp_path)
    rooms = _stacked_rooms()
    layout = ms._auto_layout(rooms, "entry")
    assert len(set(layout.values())) == len(rooms)  # all cells unique
    # East neighbour is to the +x of entry.
    ex, ey = layout["entry"]
    hx, hy = layout["east_hall"]
    assert hx > ex and hy == ey
