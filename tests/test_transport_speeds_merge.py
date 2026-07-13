"""Campaign-side TRANSPORT_SPEEDS.json merges over the engine's generic base.

Campaign transport modes are play-state (they never ship with the engine); the
engine file carries only generic modes. A campaign file, when present, wins
per top-level entry and its transport_modes are unioned in. A malformed
campaign file must fail open to the engine base (travel math must never break).
"""
import json

from geography_system import GeographySystem


def _geo(tmp_path):
    return GeographySystem(tmp_path)


def test_engine_base_has_generic_modes_only(tmp_path):
    modes = _geo(tmp_path)._load_transport_speeds()["transport_modes"]
    assert "foot" in modes
    assert "ornithopter" in modes
    # No campaign-specific formation modes in the shipped base.
    assert not any(k.endswith("_mode") for k in modes)


def test_campaign_file_modes_merge_over_base(tmp_path):
    campaign = {
        "transport_modes": {
            "sprint_formation": {"name": "Sprint Formation", "base_speed_mph": 20},
            "foot": {"name": "Walking/Marching", "base_speed_mph": 3.0},
        }
    }
    (tmp_path / "TRANSPORT_SPEEDS.json").write_text(json.dumps(campaign), encoding="utf-8")
    modes = _geo(tmp_path)._load_transport_speeds()["transport_modes"]
    assert modes["sprint_formation"]["base_speed_mph"] == 20   # campaign addition present
    assert modes["foot"]["base_speed_mph"] == 3.0              # campaign override wins
    assert "ornithopter" in modes                              # engine base retained


def test_malformed_campaign_file_fails_open(tmp_path):
    (tmp_path / "TRANSPORT_SPEEDS.json").write_text("{not json", encoding="utf-8")
    modes = _geo(tmp_path)._load_transport_speeds()["transport_modes"]
    assert "foot" in modes  # engine base still served
