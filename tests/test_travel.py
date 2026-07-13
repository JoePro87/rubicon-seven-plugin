import json
import sys
from pathlib import Path
import pytest

# Load the worktree's modules regardless of pytest cwd (judge-against-the-real-runner).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geography_system import GeographySystem


@pytest.fixture
def geo(tmp_path):
    g = {
        "meta": {"party_location": "ceruline"},
        "locations": {
            "ceruline": {"x": 0, "y": 0, "type": "settlement", "region": "core"},
            "salt_bones": {"x": 2, "y": 0, "type": "ruin", "region": "core"},
        },
        "routes": {
            "ceruline_to_salt_bones": {"from": "ceruline", "to": "salt_bones",
                                       "hexes": 2, "days_foot": 4.0, "days_ornithopter": 1.0,
                                       "hazard_level": "low"},
        },
    }
    (tmp_path / "VAARN_GEOGRAPHY.json").write_text(json.dumps(g), encoding="utf-8")
    return GeographySystem(tmp_path)


def test_depart_writes_state_with_route_days(geo):
    out = geo.travel_depart("salt_bones", mode="foot")
    st = geo.get_travel_state()
    assert st["active"] is True
    assert st["destination"] == "salt_bones"
    assert st["days_total"] == 4.0 and st["days_remaining"] == 4.0
    assert "travel_day" in out


def test_depart_vehicle_halves_days(geo):
    geo.travel_depart("salt_bones", mode="vehicle")
    assert geo.get_travel_state()["days_total"] == 2.0


def test_depart_unknown_route_rolls_band(geo, monkeypatch):
    g = geo._load_geography()
    g["locations"]["far_ruin"] = {"x": 6, "y": 0, "type": "ruin", "region": "edge"}
    geo._save_geography(g)
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [4] * n)  # 3d6 -> 12
    geo.travel_depart("far_ruin", mode="foot")
    assert geo.get_travel_state()["days_total"] == 12.0


def test_arrive_sets_location_and_clears_state(geo):
    geo.travel_depart("salt_bones", mode="foot")
    out = geo.travel_arrive()
    assert geo.get_party_location() == "salt_bones"
    assert geo.get_travel_state().get("active") is not True
    assert "enter_site" in out or "arrived" in out.lower()


def test_travel_day_normal_progress(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")  # 4 days
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Still", "travel": "normal"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [3] * n)  # all 3 = nothing
    out = geo.travel_day()
    st = geo.get_travel_state()
    assert st["days_remaining"] == 3.0  # 4 - 1
    assert "travel_day" in out


def test_half_speed_weather_decrements_half(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Dust Storm", "travel": "half"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [4] * n)
    geo.travel_day()
    assert geo.get_travel_state()["days_remaining"] == 3.5  # 4 - 0.5


def test_no_travel_weather_no_progress(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Sand Storm", "travel": "none"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [4] * n)
    out = geo.travel_day()
    assert geo.get_travel_state()["days_remaining"] == 4.0  # no progress
    assert "no travel" in out.lower() or "hunker" in out.lower()


def test_encounter_pauses_and_pushes_reaction(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Still", "travel": "normal"})
    seq = iter([[1], [3], [5]])  # day enc, night nothing, vigilance
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: next(seq))
    out = geo.travel_day()
    assert "ENCOUNTER" in out.upper()
    assert "reaction" in out.lower()


def test_last_day_pushes_arrive(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Still", "travel": "normal"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [3] * n)
    for _ in range(3):
        geo.travel_day()
    out = geo.travel_day()  # 4th day -> 0 remaining
    assert "arrive" in out.lower()


def test_forced_march_pushes_exhaustion(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Still", "travel": "normal"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [3] * n)
    out = geo.travel_day(pace="forced")
    assert geo.get_travel_state()["days_remaining"] == 2.0  # 4 - (1*2)
    assert "exhaustion" in out.lower()


def test_lost_under_sandstorm_adds_days(geo, monkeypatch):
    geo.travel_depart("salt_bones", mode="foot")
    monkeypatch.setattr(geo, "_roll_weather", lambda: {"name": "Sand Storm", "travel": "none"})
    monkeypatch.setattr("geography_system._roll_dice", lambda n, sides: [3] * n)
    out = geo.travel_day(pace="forced")  # pushing through the storm
    assert "lost" in out.lower()
    assert geo.get_travel_state()["days_remaining"] > 4.0  # days added
