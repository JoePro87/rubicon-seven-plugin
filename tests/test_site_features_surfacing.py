import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import site_features as sf  # noqa: E402
from geography_system import GeographySystem  # noqa: E402


def _geo_with_journey(tmp_path):
    geo = GeographySystem(tmp_path)
    geo.add_location("Ceruline", 0, 0, "arcology", "Test Region")
    geo.add_location("Quills Camp", 1, 1, "camp", "Test Region")
    geo._save_travel_state({"active": True, "origin": "ceruline",
                            "destination": "quills_camp", "mode": "foot",
                            "days_total": 1, "days_remaining": 0,
                            "pace": "normal", "noisy": False, "log": []})
    return geo


def test_travel_arrive_surfaces_features(tmp_path):
    geo = _geo_with_journey(tmp_path)
    sf.stamp_feature(tmp_path, "Quills Camp", "a chromatic flower on the shrine", 141)
    out = geo.travel_arrive()
    assert "ARRIVED" in out
    assert "📍 SITE FEATURES — Quills Camp:" in out
    assert "chromatic flower" in out


def test_travel_arrive_silent_without_features(tmp_path):
    geo = _geo_with_journey(tmp_path)
    out = geo.travel_arrive()
    assert "ARRIVED" in out
    assert "SITE FEATURES" not in out


def test_travel_arrive_failsoft_on_corrupt_ledger(tmp_path):
    geo = _geo_with_journey(tmp_path)
    (tmp_path / "site_features.json").write_text("{corrupt", encoding="utf-8")
    out = geo.travel_arrive()
    assert "ARRIVED" in out  # never breaks arrival


import json  # noqa: E402
from player_view import build_view  # noqa: E402


def test_player_view_carries_current_place_features(tmp_path):
    (tmp_path / "game_state.json").write_text(
        json.dumps({"active_location_name": "Quills Camp"}), encoding="utf-8")
    sf.stamp_feature(tmp_path, "Quills Camp", "a chromatic flower on the shrine", 141)
    view = build_view(tmp_path)
    assert view["site_features"] == [{"text": "a chromatic flower on the shrine", "day": 141}]


def test_player_view_site_features_empty_when_elsewhere(tmp_path):
    sf.stamp_feature(tmp_path, "Quills Camp", "a flower", 141)
    view = build_view(tmp_path)  # no game_state → no current place
    assert view["site_features"] == []


import server  # noqa: E402
import session_tools  # noqa: E402


def test_check_canon_helper_matches_named_place(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "GAME_STATE", {}, raising=False)
    sf.stamp_feature(tmp_path, "Quills Camp", "a flower on the shrine", 141)
    out = server._site_features_injection("we ride back toward Quills Camp")
    assert "📍 SITE FEATURES — Quills Camp:" in out
    assert server._site_features_injection("a quiet day in the dunes") == ""


def test_check_canon_helper_includes_active_location(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    sf.stamp_feature(tmp_path, "Quills Camp", "a flower", 141)
    monkeypatch.setattr(server, "GAME_STATE", {"active_location_name": "Quills Camp"}, raising=False)
    out = server._site_features_injection("we look around")
    assert "Quills Camp" in out


def test_startup_briefing_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "game_state.json").write_text(
        json.dumps({"active_location_name": "Quills Camp"}), encoding="utf-8")
    sf.stamp_feature(tmp_path, "Quills Camp", "a flower", 141)
    lines = session_tools._site_features_briefing_lines()
    assert any("SITE FEATURES" in ln for ln in lines)


def test_startup_briefing_falls_back_to_current_status(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "**Location:** Quills Camp — north edge\n", encoding="utf-8")
    sf.stamp_feature(tmp_path, "Quills Camp", "a flower", 141)
    assert session_tools._site_features_briefing_lines() != []


def test_startup_briefing_empty_cases(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    assert session_tools._site_features_briefing_lines() == []
