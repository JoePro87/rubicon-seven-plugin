"""D134 Thyricost travel/supply fixes (dm_scratchpad findings, 2026-07-17).

1. Fast transport modes (ornithopter) must resolve travel days from the
   transport-speed table, never foot-days (15-day estimate for a 2-hour flight).
2. depart accepts an explicit origin, correcting a stale stored party location.
3. geography(depart) passes pool seeds (food/water/follower_mouths) through to
   supply(depart) and surfaces its output instead of swallowing it.
4. geography(arrive) never auto-flips supply to abundant — whether an arrival
   is a supplied base is DM judgment; the pushed supply(action="arrive") call
   is the lever.
"""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geography_system import GeographySystem, register_geography_tools


@pytest.fixture
def geo(tmp_path):
    g = {
        "meta": {"party_location": "ceruline"},
        "locations": {
            "ceruline": {"x": 0, "y": 0, "type": "settlement", "region": "core"},
            "salt_bones": {"x": 2, "y": 0, "type": "ruin", "region": "core"},
            "thyricost": {"x": 8, "y": 0, "type": "arcology_coastal", "region": "coast"},
        },
        "routes": {
            "ceruline_to_salt_bones": {"from": "ceruline", "to": "salt_bones",
                                       "hexes": 2, "days_foot": 4.0,
                                       "days_ornithopter": 1.0},
            "ceruline_to_thyricost": {"from": "ceruline", "to": "thyricost",
                                      "hexes": 8, "days_foot": 15.0,
                                      "distance_miles": 264},
        },
    }
    (tmp_path / "VAARN_GEOGRAPHY.json").write_text(json.dumps(g), encoding="utf-8")
    speeds = {"transport_modes": {"ornithopter": {
        "base_speed_mph": 120, "daily_range_miles": 960, "sustained_hours": 24}}}
    (tmp_path / "TRANSPORT_SPEEDS.json").write_text(json.dumps(speeds), encoding="utf-8")
    return GeographySystem(tmp_path)


# ---- 1. mode-aware travel days ----

def test_ornithopter_uses_speed_table_not_foot_days(geo):
    geo.travel_depart("thyricost", mode="ornithopter")
    st = geo.get_travel_state()
    assert st["days_total"] == 1.0  # 264 mi / 960 mi-per-day -> 1 travel day, not 15


def test_canonical_per_mode_route_days_win(geo):
    geo.travel_depart("salt_bones", mode="ornithopter")
    assert geo.get_travel_state()["days_total"] == 1.0  # days_ornithopter on the route


def test_foot_and_vehicle_unchanged(geo):
    geo.travel_depart("salt_bones", mode="foot")
    assert geo.get_travel_state()["days_total"] == 4.0
    geo.travel_depart("salt_bones", mode="vehicle")
    assert geo.get_travel_state()["days_total"] == 2.0


def test_unknown_speed_mode_falls_back_to_foot_path(geo):
    geo.travel_depart("salt_bones", mode="sandship")
    assert geo.get_travel_state()["days_total"] == 4.0  # days_foot fallback


# ---- 2. explicit origin ----

def test_depart_origin_overrides_stale_party_location(geo):
    out = geo.travel_depart("thyricost", mode="ornithopter", origin="salt_bones")
    st = geo.get_travel_state()
    assert st["origin"] == "salt_bones"
    assert "salt_bones" in out
    # the correction persists for the next depart
    assert geo._load_geography()["meta"]["party_location"] == "salt_bones"


def test_depart_unknown_origin_errors(geo):
    out = geo.travel_depart("thyricost", origin="nowhere_town")
    assert out.startswith("Error")


def test_depart_without_origin_flags_stored_source(geo):
    out = geo.travel_depart("salt_bones", mode="foot")
    assert "stored party location" in out


# ---- 3+4. tool wiring: supply passthrough / no auto-abundant ----

def _tool_and_geo(campaign_dir):
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    geo = register_geography_tools(_FakeMCP(), campaign_dir)
    return captured["geography"], geo


def test_tool_depart_passes_pool_seeds_and_surfaces_output(geo, tmp_path):
    tool, g = _tool_and_geo(tmp_path)
    calls = {}

    def on_depart(food=None, water=None, follower_mouths=None):
        calls.update(food=food, water=water, follower_mouths=follower_mouths)
        return "Supply tracking is LIVE (field mode)."

    g.on_depart = on_depart
    out = tool(action="depart", destination="salt_bones",
               food=40, water=55, follower_mouths=2)
    assert calls == {"food": 40, "water": 55, "follower_mouths": 2}
    assert "Supply tracking is LIVE" in out  # surfaced, not swallowed


def test_tool_depart_error_skips_supply_flip(geo, tmp_path):
    tool, g = _tool_and_geo(tmp_path)
    fired = []
    g.on_depart = lambda **k: fired.append(k) or ""
    out = tool(action="depart", destination="nowhere_town")
    assert out.startswith("Error")
    assert fired == []  # a failed depart must not flip supply to field


def test_tool_arrive_never_flips_supply(geo, tmp_path):
    tool, g = _tool_and_geo(tmp_path)
    fired = []
    g.on_arrive = lambda loc: fired.append(loc)  # even if wired, must not fire
    tool(action="depart", destination="salt_bones")
    out = tool(action="arrive")
    assert fired == []
    assert 'supply(action="arrive"' in out       # the judgment push instead
    assert "supplied base" in out


def test_travel_arrive_push_names_field_stays(geo):
    geo.travel_depart("salt_bones", mode="foot")
    out = geo.travel_arrive()
    assert "FIELD" in out
