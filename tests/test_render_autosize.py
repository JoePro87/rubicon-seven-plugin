"""Phase 5: render label auto-sizing — no truncation."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem
from map_system import MapSystem


@pytest.fixture
def geo_longname(tmp_path):
    g = GeographySystem(tmp_path)
    g._save_geography({
        "meta": {"party_location": "ceruline"},
        "regions": {"central_wastes": {"terrain": "x", "description": "y", "encounter_table": "Featureless Sands"}},
        "routes": {},
        "locations": {
            "ceruline": {"x": 0, "y": 0, "type": "arcology", "region": "central_wastes", "module": None, "explored": True, "known": True, "description": ""},
            "sandwhisper_station": {"x": 2, "y": 0, "type": "crossroads", "region": "central_wastes", "module": None, "explored": True, "known": True, "description": ""},
        },
    })
    return g


def test_hex_label_full_at_large_resolution(geo_longname):
    out = geo_longname.render_map(center="ceruline", radius=3, resolution="large")
    assert "Sandwhisper Station" in out   # full label, no truncation at large res


def test_hex_label_not_aggressively_truncated_default(geo_longname):
    out = geo_longname.render_map(center="ceruline", radius=3)
    assert "Sandwhisper" in out   # at least the full first word survives (was 'Sandwhisp')


def test_vault_room_name_not_truncated(tmp_path):
    from map_system import MapSystem
    ms = MapSystem(tmp_path)
    prep = """# V - PREP

**Type:** vault

## ROOM: a

**Name:** Rubicon Seven Command Deck
**Entrance:** true
**Coords:** 0,0
**Connections:** n->b

## ROOM: b

**Name:** B
**Coords:** 0,-1
**Connections:** s->a
"""
    (tmp_path / "V.md").write_text(prep, encoding="utf-8")
    ms.init_map_from_prep("v", "V.md", "vault")   # entrance 'a' is auto-explored on init
    out = ms.render_map("v", resolution="large")
    assert "Rubicon Seven Command Deck" in out   # full name, not 'Rubicon Se'


def test_room_name_has_no_leading_space(tmp_path):
    from map_system import MapSystem
    ms = MapSystem(tmp_path)
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Name:** Command Deck\n**Connections:** n->b\n")
    assert rooms["a"]["name"] == "Command Deck"  # no leading space
