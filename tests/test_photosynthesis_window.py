# tests/test_photosynthesis_window.py
"""Photosynthesis window comes from sheet data (a graft/augment can extend it),
book default 3. A hardcoded '+ 4' would bake one sheet's augment in undocumented."""
import json
import server
from tests.test_supply_tool import _seed, _vela


def _status(dirpath, day, last_fed):
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n\n"
        f"**PHOTOSYNTHESIS:** Fed Day {last_fed} - Due Day {last_fed + 4} (margin)\n")


def test_window_read_from_sheet(isolate_campaign_dir):
    creenash = _vela()
    creenash["name"] = "Creenash"
    creenash["survival"] = {"needs_food": False, "photosynthesis_window_days": 4}
    _seed(isolate_campaign_dir, chars={"creenash": creenash})
    _status(isolate_campaign_dir, 100, 98)
    out = server.supply(action='photosynthesis', last_fed_day=100, current_day=100)
    assert "Due Day 104" in out  # 100 + sheet window 4


def test_window_default_three_without_sheet_field(isolate_campaign_dir):
    creenash = _vela()
    creenash["name"] = "Creenash"
    creenash["survival"] = {"needs_food": False}  # no window override
    _seed(isolate_campaign_dir, chars={"creenash": creenash})
    _status(isolate_campaign_dir, 100, 98)
    out = server.supply(action='photosynthesis', last_fed_day=100, current_day=100)
    assert "Due Day 103" in out  # book default 3
