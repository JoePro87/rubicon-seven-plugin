"""Tests for _inject_spatial_state — scene-type-driven spatial injection."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import server
from map_system import MapSystem

VAULT_PREP = """## ROOM: entrance
**Floor:** 1
**Coords:** 5,5
**Name:** Entrance Hall
**Entrance:** true
**Connections:** e→hall
## ROOM: hall
**Floor:** 1
**Coords:** 6,5
**Name:** Hall
**Connections:** w→entrance
"""

NO_ROOM_PREP = "## FACTIONS\nThe Hegemon watches.\n"


def _status(scene_type, active_prep="V_PREP.md", active_map="None", location="Test"):
    return {
        "scene_type": scene_type, "active_prep": active_prep,
        "active_map": active_map, "location": location,
    }


def test_derive_map_name():
    assert server._derive_map_name("CERULINE_ARCOLOGY_PREP.md") == "ceruline_arcology"
    assert server._derive_map_name("V_PREP.md") == "v"


def test_vault_autoinit_writes_field_and_injects(tmp_path, monkeypatch):
    (tmp_path / "V_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "**Scene Type:** vault_exploration\n**Active Map:** None\n", encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "map_system", MapSystem(tmp_path))
    out = server._inject_spatial_state(_status("vault_exploration", "V_PREP.md", "None"))
    assert out and "ACTIVE MAP" in out
    assert "**Active Map:** v" in (tmp_path / "CURRENT_STATUS.md").read_text(encoding="utf-8")


def test_vault_no_room_markers_falls_back_silently(tmp_path, monkeypatch):
    (tmp_path / "NR_PREP.md").write_text(NO_ROOM_PREP, encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "**Scene Type:** vault_exploration\n**Active Map:** None\n", encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "map_system", MapSystem(tmp_path))
    out = server._inject_spatial_state(_status("vault_exploration", "NR_PREP.md", "None"))
    assert out is None
    assert "**Active Map:** None" in (tmp_path / "CURRENT_STATUS.md").read_text(encoding="utf-8")


def test_vault_existing_map_not_reinited(tmp_path, monkeypatch):
    (tmp_path / "V_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("v", "V_PREP.md", "vault")
    ms.enter_room("v", "hall")  # progress state: party now in Hall
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "map_system", ms)
    out = server._inject_spatial_state(_status("vault_exploration", "V_PREP.md", "v"))
    assert "Hall" in out  # injects progressed state, not reset to entrance


def test_settlement_injects_only_if_active_map_set(tmp_path, monkeypatch):
    (tmp_path / "V_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("townmap", "V_PREP.md", "settlement")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "map_system", ms)
    assert server._inject_spatial_state(_status("settlement", "V_PREP.md", "None")) is None
    out = server._inject_spatial_state(_status("settlement", "V_PREP.md", "townmap"))
    assert out and "ACTIVE MAP" in out


def test_vault_set_map_does_not_rewrite_field(tmp_path, monkeypatch):
    (tmp_path / "V_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    ms = MapSystem(tmp_path)
    ms.init_map_from_prep("v", "V_PREP.md", "vault")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "map_system", ms)
    calls = []
    monkeypatch.setattr(server, "_update_current_status_active_map",
                        lambda name: calls.append(name) or True)
    out = server._inject_spatial_state(_status("vault_exploration", "V_PREP.md", "v"))
    assert out and "ACTIVE MAP" in out
    assert calls == []  # already-set Active Map -> no field write on the hot path


def test_social_scene_injects_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    assert server._inject_spatial_state(_status("social")) is None


def test_travel_uses_party_location(monkeypatch):
    class FakeGeo:
        def get_party_location(self): return "ceruline"
        def position_context(self, center, radius=6): return f"**OVERWORLD — near {center}**\n- x"
    monkeypatch.setattr(server, "geography_system", FakeGeo())
    out = server._inject_spatial_state(_status("travel"))
    assert out and "OVERWORLD" in out


def test_travel_no_party_location_returns_none(monkeypatch):
    class FakeGeo:
        def get_party_location(self): return None
        def position_context(self, center, radius=6): return "should not be called"
    monkeypatch.setattr(server, "geography_system", FakeGeo())
    assert server._inject_spatial_state(_status("travel")) is None


def test_hexpedition_uses_party_location(monkeypatch):
    class FakeGeo:
        def get_party_location(self): return "ceruline"
        def position_context(self, center, radius=6): return f"**OVERWORLD — near {center}**\n- y"
    monkeypatch.setattr(server, "geography_system", FakeGeo())
    out = server._inject_spatial_state(_status("hexpedition"))
    assert out and "OVERWORLD" in out
