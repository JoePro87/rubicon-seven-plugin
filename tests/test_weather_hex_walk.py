"""Book-faithful weather: the Referee's Toolbox hex-chart walk (pp.155-156).

Joe ruling 2026-06-12: replace the invented d20 weather table with the
book's system - a 37-hex chart, marker starts at center, d6 each desert
day moves it (1=NW 2=N 3=NE 4=SE 5=S 6=SW). Off-chart moves wrap to the
opposite side; the 10 X-marked void cells block instead (marker stays).
Chart transcribed from the PDF p.156 figure (programmatic texture match
against the legend swatches, visually verified).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

DATA_FILE = Path(__file__).parent.parent / "data" / "content_forge_tables.json"


def _chart():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return data["tables"]["_weather_hex_chart"]


def _capture_roll_tool(campaign_dir):
    from content_forge import register_content_forge_tools
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    register_content_forge_tools(_FakeMCP(), Path(campaign_dir))
    return captured["roll"]


# --- chart data integrity --------------------------------------------------

def test_chart_has_37_cells_with_book_distribution():
    cells = _chart()["cells"]
    assert len(cells) == 37
    counts = {}
    for label, cell in cells.items():
        counts[cell["weather"]] = counts.get(cell["weather"], 0) + 1
    assert counts == {
        "Still": 10, "Dust Storm": 7, "Sand Storm": 6, "Hazy": 5,
        "Heatwave": 4, "Worm-pollen": 3, "Rain": 1, "Prismatic Tempest": 1,
    }


def test_chart_poles_and_start():
    cells = _chart()["cells"]
    assert _chart()["start"] == "D4"
    assert cells["D4"]["weather"] == "Still"
    assert cells["D1"]["weather"] == "Rain"
    assert cells["D7"]["weather"] == "Prismatic Tempest"
    assert all(cells[f"G{i}"]["weather"] == "Heatwave" for i in range(1, 5))


def test_chart_blocked_cells_centrally_symmetric():
    blocked = {tuple(c) for c in _chart()["blocked_void_cells"]}
    assert len(blocked) == 10
    assert {(-q, -r) for q, r in blocked} == blocked


def test_effects_are_book_text():
    effects = _chart()["effects"]
    assert set(effects) == {"Still", "Hazy", "Dust Storm", "Sand Storm",
                            "Heatwave", "Worm-pollen", "Rain",
                            "Prismatic Tempest"}
    assert "twice their normal ration of water" in effects["Heatwave"]
    assert "2d6" in effects["Rain"]
    assert "3d6" in effects["Prismatic Tempest"]
    assert "d4 rations" in effects["Worm-pollen"]
    # the invented d4-damage sandstorm is gone; book sandstorm = no travel
    assert "d4 damage" not in effects["Sand Storm"]
    assert "hunker" in effects["Sand Storm"].lower()


def test_old_d20_weather_table_gone():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    assert "weather" not in data["tables"], (
        "the invented d20 weather table must be replaced by _weather_hex_chart"
    )


# --- the walk ---------------------------------------------------------------

def test_first_roll_moves_from_start(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    out = roll(action="environment", table="weather", specific_roll=2)  # N
    # From D4 (Start) north -> D3 (Hazy)
    assert "Hazy" in out
    assert "D3" in out
    state = json.loads((tmp_path / "weather_state.json").read_text())
    assert state["position"] == "D3"


def test_marker_persists_across_days(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    roll(action="environment", table="weather", specific_roll=2)  # D4 -> D3
    roll(action="environment", table="weather", specific_roll=2)  # D3 -> D2
    out = roll(action="environment", table="weather", specific_roll=2)  # D2 -> D1
    assert "Rain" in out and "D1" in out


def test_blocked_edge_stays_put(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    for _ in range(3):
        roll(action="environment", table="weather", specific_roll=2)  # to D1
    out = roll(action="environment", table="weather", specific_roll=2)  # N of D1 = X
    assert "D1" in out and "Rain" in out
    assert "stays" in out.lower() or "X" in out
    state = json.loads((tmp_path / "weather_state.json").read_text())
    assert state["position"] == "D1"


def test_unblocked_edge_wraps_to_opposite_side(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    # Drive marker to B1 (-2,-1): from D4 go NW (1) twice -> B... D4=(0,0)
    # NW: (0,0)->(-1,0)=C3 ->(-2,0)=B2; then N: (-2,-1)=B1
    for sr in (1, 1, 2):
        roll(action="environment", table="weather", specific_roll=sr)
    # B1 north -> void (-2,-2), NOT an X cell -> wrap south along column B to B5
    out = roll(action="environment", table="weather", specific_roll=2)
    assert "B5" in out and "Sand Storm" in out
    assert "wrap" in out.lower()


def test_weather_reset(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    roll(action="environment", table="weather", specific_roll=4)
    out = roll(action="environment", table="weather_reset")
    assert "D4" in out
    state = json.loads((tmp_path / "weather_state.json").read_text())
    assert state["position"] == "D4"


def test_random_roll_reports_direction_die(tmp_path):
    roll = _capture_roll_tool(tmp_path)
    out = roll(action="environment", table="weather", specific_roll=None)
    assert "d6" in out
