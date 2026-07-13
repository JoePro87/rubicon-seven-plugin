"""Phase 5: fog-aware + glyph rendering for the overworld."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem, register_geography_tools


@pytest.fixture
def world(tmp_path):
    g = GeographySystem(tmp_path)
    g._save_geography({
        "meta": {"party_location": "hub"},
        "regions": {"central_wastes": {"terrain": "badlands", "description": "x", "encounter_table": "Featureless Sands"}},
        "routes": {},
        "locations": {
            "hub":        {"x": 0, "y": 0, "type": "crossroads", "region": "central_wastes", "module": None, "explored": True,  "known": True,  "description": ""},
            "big_wall":   {"x": 1, "y": 0, "type": "landmark",   "region": "central_wastes", "module": None, "explored": False, "known": True,  "description": ""},
            "ruined_arc": {"x": 0, "y": 1, "type": "arcology_ruin","region": "central_wastes","module": None, "explored": True, "known": True,  "description": ""},
            "secret_den": {"x": 1, "y": 1, "type": "cave_system","region": "central_wastes", "module": None, "explored": False, "known": False, "description": ""},
        },
    })
    return g


def test_render_map_runs_and_shows_locations(world):
    out = world.render_map(center="hub", radius=4, fog_of_war=False)
    assert "secret" in out.lower()   # DM view (fog off) shows the fogged location
    assert "hub" in out.lower()


def test_render_map_accepts_fog_param(world):
    # fog_of_war param must exist (consumed by a later task; just accept it now)
    out = world.render_map(center="hub", radius=4, fog_of_war=True)
    assert isinstance(out, str) and len(out) > 0


def test_render_svg_accepts_fog_param(world):
    svg = world.render_svg(center="hub", radius=4, fog_of_war=True)
    assert "svg" in svg.lower()


def test_fog_hides_fogged_location(world):
    out = world.render_map(center="hub", radius=4, fog_of_war=True)
    assert "secret" not in out.lower()   # fogged cave hidden in player view


def test_fog_shows_known_as_dashed(world):
    out = world.render_map(center="hub", radius=4, fog_of_war=True)
    assert ("big" in out.lower()) or ("wall" in out.lower())  # known landmark still shown
    assert "- - -" in out  # known-not-explored renders dashed


def test_no_fog_shows_fogged(world):
    out = world.render_map(center="hub", radius=4, fog_of_war=False)
    assert "secret" in out.lower()  # DM view shows fogged


def test_svg_fog_omits_fogged(world):
    svg = world.render_svg(center="hub", radius=4, fog_of_war=True)
    assert "secret den" not in svg.lower() and "secret_den" not in svg.lower()


def test_svg_no_fog_includes_fogged(world):
    svg = world.render_svg(center="hub", radius=4, fog_of_war=False)
    assert "secret" in svg.lower()


def test_svg_label_not_truncated(world):
    # add a long-named explored location and confirm the full name appears in the SVG text
    data = world._load_geography()
    data["locations"]["sandwhisper_station"] = {"x": 2, "y": 0, "type": "crossroads",
        "region": "central_wastes", "module": None, "explored": True, "known": True, "description": ""}
    world._save_geography(data)
    svg = world.render_svg(center="hub", radius=5, fog_of_war=False)
    assert "Sandwhisper Station" in svg   # full label, not 'Sandwhisper…'


def test_geography_tool_render_map_fog_param(tmp_path):
    captured = {}
    class _FakeMCP:
        def tool(self, *a, **k):
            def deco(fn): captured[fn.__name__] = fn; return fn
            return deco
    register_geography_tools(_FakeMCP(), tmp_path)
    geography = captured["geography"]
    g = GeographySystem(tmp_path)
    g._save_geography({"meta": {"party_location": "hub"},
        "regions": {"central_wastes": {"terrain": "x", "description": "y", "encounter_table": "Featureless Sands"}},
        "routes": {},
        "locations": {
            "hub": {"x":0,"y":0,"type":"crossroads","region":"central_wastes","module":None,"explored":True,"known":True,"description":""},
            "secret_den": {"x":1,"y":0,"type":"cave_system","region":"central_wastes","module":None,"explored":False,"known":False,"description":""}}})
    out = geography(action="render_map", center="hub", radius=3, fog_of_war=True)
    assert "secret" not in out.lower()   # tool honors fog_of_war
    out2 = geography(action="render_map", center="hub", radius=3, fog_of_war=False)
    assert "secret" in out2.lower()      # DM view via tool shows it


def test_svg_new_type_has_distinct_color(world):
    svg = world.render_svg(center="hub", radius=4, fog_of_war=False)
    assert "#a16207" in svg   # arcology_ruin color present (ruined_arc is on the map)
    assert "Arcology(ruin)" in svg  # legend entry


def test_svg_fog_suppresses_dm_status_text(world):
    svg = world.render_svg(center="hub", radius=4, fog_of_war=True)
    assert "prepped" not in svg.lower()   # no DM jargon on player render
