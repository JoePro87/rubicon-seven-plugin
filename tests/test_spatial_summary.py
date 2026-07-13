"""Tests for map_system.spatial_summary() — inject-ready live vault state."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from map_system import MapSystem

PREP = """## ROOM: entrance
**Floor:** 1
**Coords:** 5,5
**Name:** Entrance Hall
**Entrance:** true
**Connections:** e→gallery, n→sealed_vault
**Secrets:** panel→hidden_cache (search + INT DC 14)

## ROOM: gallery
**Floor:** 1
**Coords:** 6,5
**Name:** Gallery
**Connections:** w→entrance

## ROOM: sealed_vault
**Floor:** 1
**Coords:** 5,4
**Name:** Sealed Vault
**Connections:** s→entrance
"""


@pytest.fixture
def m(tmp_path):
    (tmp_path / "V_PREP.md").write_text(PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("v", "V_PREP.md", "vault")
    return ms


def test_summary_none_for_missing_map(m):
    assert m.spatial_summary("does_not_exist") is None


def test_summary_reports_party_room_and_turn(m):
    out = m.spatial_summary("v")
    assert "Entrance Hall" in out
    assert "Turn" in out
    assert "Floor 1" in out


def test_summary_lists_adjacent_rooms(m):
    out = m.spatial_summary("v")
    assert "gallery" in out.lower()
    assert "sealed_vault" in out.lower()


def test_summary_flags_unexplored_exits(m):
    out = m.spatial_summary("v")
    assert "Unexplored exits:" in out


def test_summary_notes_undiscovered_secret(m):
    out = m.spatial_summary("v")
    assert "secret" in out.lower()


CROSS_PREP = """## ROOM: lobby
**Floor:** 1
**Coords:** 0,0
**Name:** Lobby
**Entrance:** true
**Connections:** up→upper_hall@2

## ROOM: upper_hall
**Floor:** 2
**Coords:** 0,0
**Name:** Upper Hall
**Connections:** down→lobby@1
"""


def test_summary_handles_cross_floor_connection(tmp_path):
    (tmp_path / "C_PREP.md").write_text(CROSS_PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("c", "C_PREP.md", "vault")
    out = ms.spatial_summary("c")
    assert "upper_hall" in out  # dict-form target resolved


def test_summary_invalid_party_location_returns_diagnostic(tmp_path):
    (tmp_path / "V2_PREP.md").write_text(PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("v2", "V2_PREP.md", "vault")
    state = ms.get_map_state("v2")
    state["party_location"] = "nonexistent_room"
    ms.save_map_state("v2", state)
    out = ms.spatial_summary("v2")
    assert "missing or invalid" in out.lower()
