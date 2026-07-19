"""Reveal discipline Part C (Task 4): paced room delivery.

map(enter) returns a first_glance layer only (2-3 sensory lines); full
Observables detail moves to map(action="look"). Legacy preps auto-split:
first paragraph of Observables = glance, rest = inspection. An explicit
'### First Glance' section wins when authored.
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem

PREP = """# TEST VAULT

## ROOM: atrium
**Floor:** 1
**Coords:** 0,0
**Name:** Sunken Atrium
**Connections:** north→gallery
**Entrance:** true

### Observables
para one: pale light falls through a cracked oculus onto standing water.

para two: the mosaic beneath the water shows a procession of hooded figures.

para three: a bronze door on the north wall weeps verdigris.

### Loot
- a waxed satchel wedged behind the door hinge

### DM Notes
Keep the water's depth vague until probed.

## ROOM: gallery
**Floor:** 1
**Coords:** 0,1
**Name:** Long Gallery
**Connections:** south→atrium

### First Glance
Cold air and the smell of dust; shelves recede into darkness.

### Observables
The shelves hold clay cylinders stamped with spiral script. A toppled
ladder lies across the aisle.

## ROOM: cell
**Floor:** 1
**Coords:** 1,0
**Name:** Bare Cell
**Connections:** west→gallery

### Observables
A single empty room with scratch marks on the floor.
"""


@pytest.fixture
def map_env(tmp_path):
    (tmp_path / "TEST_PREP.md").write_text(PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    out = ms.init_map_from_prep("testvault", "TEST_PREP.md", "vault")
    assert "❌" not in out
    return ms


def test_glance_is_first_paragraph(map_env):
    state = map_env.get_map_state("testvault")
    glance = map_env.location_content(state, "atrium", "first_glance")
    assert "para one" in glance
    assert "para two" not in glance and "para three" not in glance


def test_inspection_is_remaining_paragraphs(map_env):
    state = map_env.get_map_state("testvault")
    detail = map_env.location_content(state, "atrium", "inspection")
    assert "para two" in detail and "para three" in detail
    assert "para one" not in detail


def test_obvious_tier_unchanged_for_other_callers(map_env):
    state = map_env.get_map_state("testvault")
    obvious = map_env.location_content(state, "atrium", "obvious")
    assert "para one" in obvious and "para two" in obvious and "para three" in obvious


def test_explicit_first_glance_header(map_env):
    state = map_env.get_map_state("testvault")
    glance = map_env.location_content(state, "gallery", "first_glance")
    assert "smell of dust" in glance
    assert "clay cylinders" not in glance
    detail = map_env.location_content(state, "gallery", "inspection")
    # explicit glance section -> ALL of Observables is inspection detail
    assert "clay cylinders" in detail and "toppled" in detail


def test_single_paragraph_observables(map_env):
    state = map_env.get_map_state("testvault")
    glance = map_env.location_content(state, "cell", "first_glance")
    assert "scratch marks" in glance
    assert map_env.location_content(state, "cell", "inspection") == ""


def test_enter_room_returns_glance_only(map_env):
    out = map_env.enter_room("testvault", "atrium")
    assert "para one" in out
    assert "para two" not in out
    assert "Render ONE finding" in out
    assert 'map(action="look"' in out


def test_look_returns_inspection(map_env):
    map_env.enter_room("testvault", "atrium")
    out = map_env.look_room("testvault", "atrium")
    assert "para two" in out and "para three" in out
    assert "Render ONE finding" in out


def test_look_feature_scoped(map_env):
    map_env.enter_room("testvault", "atrium")
    out = map_env.look_room("testvault", "atrium", feature="mosaic")
    assert "mosaic" in out.lower()
    assert "para three" not in out


def test_look_unknown_feature_hints_search(map_env):
    map_env.enter_room("testvault", "atrium")
    out = map_env.look_room("testvault", "atrium", feature="chandelier")
    assert "search" in out.lower()


def test_look_nothing_further(map_env):
    map_env.enter_room("testvault", "atrium")
    map_env.enter_room("testvault", "gallery")
    map_env.enter_room("testvault", "cell")
    out = map_env.look_room("testvault", "cell")
    assert "search" in out.lower()  # nothing further without a search


def test_look_costs_no_turns(map_env):
    map_env.enter_room("testvault", "atrium")
    before = map_env.get_map_state("testvault").get("current_turn", 0)
    map_env.look_room("testvault", "atrium")
    after = map_env.get_map_state("testvault").get("current_turn", 0)
    assert before == after


def test_dm_notes_still_surface_on_enter(map_env):
    out = map_env.enter_room("testvault", "atrium")
    assert "[DM]" in out and "depth vague" in out


def test_loot_never_in_glance_or_inspection(map_env):
    state = map_env.get_map_state("testvault")
    for tier in ("first_glance", "inspection"):
        assert "satchel" not in map_env.location_content(state, "atrium", tier)


def test_search_carries_discipline_line(map_env):
    map_env.enter_room("testvault", "atrium")
    out = map_env.search_room("testvault", "atrium")
    assert "Render ONE finding" in out


def test_first_glance_header_not_warned_as_unmapped(map_env, caplog):
    import logging
    state = map_env.get_map_state("testvault")
    with caplog.at_level(logging.INFO):
        map_env.location_content(state, "gallery", "obvious")
    assert not any("Unmapped room subsection 'first glance'" in r.message
                   for r in caplog.records)
