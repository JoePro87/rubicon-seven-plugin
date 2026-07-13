"""Phase 4: geography.validate_consistency() — coord collisions, dangling routes, unknown regions."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem


@pytest.fixture
def geo(tmp_path):
    return GeographySystem(tmp_path)


def test_clean_world_reports_ok(geo):
    data = geo._load_geography()
    data["regions"]["central_wastes"] = {"terrain": "wastes", "description": "test region"}
    geo._save_geography(data)
    geo.add_location("Hub", 0, 0, "crossroads", "central_wastes")
    geo.add_location("Spire", 1, 0, "landmark", "central_wastes")
    geo.add_route("Hub", "Spire", 1.0)
    out = geo.validate_consistency()
    assert "ok" in out.lower() or "no issues" in out.lower() or "clean" in out.lower()


def test_detects_route_to_missing_location(geo):
    geo.add_location("Hub", 0, 0, "crossroads", "central_wastes")
    geo.add_location("Spire", 1, 0, "landmark", "central_wastes")
    geo.add_route("Hub", "Spire", 1.0)
    data = geo._load_geography()
    del data["locations"]["spire"]
    geo._save_geography(data)
    out = geo.validate_consistency()
    assert "spire" in out.lower()
    assert "route" in out.lower()


def test_detects_unknown_region(geo):
    geo.add_location("Orphan", 2, 2, "landmark", "nowhere_region")
    out = geo.validate_consistency()
    assert "nowhere_region" in out.lower()
    assert "region" in out.lower()


def test_detects_coordinate_collision(geo):
    geo.add_location("First", 3, 3, "landmark", "central_wastes")
    data = geo._load_geography()
    data["locations"]["second"] = {"x": 3, "y": 3, "type": "ruin",
                                   "region": "central_wastes", "module": None,
                                   "explored": False, "known": False, "description": ""}
    geo._save_geography(data)
    out = geo.validate_consistency()
    assert "(3, 3)" in out or "3, 3" in out
    assert "collision" in out.lower() or "occupied" in out.lower() or "duplicate" in out.lower()


def test_detects_missing_coords(geo):
    data = geo._load_geography()
    data["regions"]["central_wastes"] = {"terrain": "wastes", "description": "t"}
    data["locations"]["ghost_a"] = {"x": None, "y": None, "type": "ruin",
                                    "region": "central_wastes", "module": None,
                                    "explored": False, "known": False, "description": ""}
    data["locations"]["ghost_b"] = {"x": None, "y": None, "type": "ruin",
                                    "region": "central_wastes", "module": None,
                                    "explored": False, "known": False, "description": ""}
    geo._save_geography(data)
    out = geo.validate_consistency()
    assert "missing coords" in out.lower()
    assert "collision" not in out.lower()  # must NOT be mis-reported as a collision


def test_detects_malformed_route(geo):
    data = geo._load_geography()
    data["regions"]["central_wastes"] = {"terrain": "wastes", "description": "t"}
    data["locations"]["hub"] = {"x": 0, "y": 0, "type": "crossroads",
                                "region": "central_wastes", "module": None,
                                "explored": False, "known": False, "description": ""}
    data["routes"]["broken"] = {"hexes": 1}  # no from/to
    geo._save_geography(data)
    out = geo.validate_consistency()
    assert "malformed route" in out.lower()
