"""E1 Task 7: the backfill stamps Twinning (both directions) and migrates the
photosynthesis fed-day; idempotent; leaves other sheets untouched. The fed-day
parser handles BOTH prose formats: the LIVE CURRENT_STATUS.md block
('**Last Fed:** Day N (...)') and the update_photosynthesis tool's line
('**PHOTOSYNTHESIS:** Fed Day N -> ...')."""
import json
from pathlib import Path
import importlib.util

spec = importlib.util.spec_from_file_location(
    "backfill_conditions_e1",
    Path(__file__).resolve().parents[1] / "scripts" / "backfill_conditions_e1.py")
bf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bf)

# The LIVE campaign repo format (primary)
LIVE_STATUS = (
    "# CURRENT STATUS - DAY 132\n\n"
    "## PHOTOSYNTHESIS TRACKING\n\n"
    "**Last Fed:** Day 130 (morning photosynthesis, Ceruline)\n"
    "**Due:** Day 134 (4-day window from Desert Endurance graft)\n")

# The update_photosynthesis tool's format (fallback - post-restart files)
TOOL_STATUS = (
    "# CURRENT STATUS - DAY 132\n"
    "**PHOTOSYNTHESIS:** Fed Day 130 -> Due Day 134 (2 days margin)\n")


def _campaign(tmp_path, status_text=LIVE_STATUS):
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "creenash.json").write_text(json.dumps({
        "name": "Creenash",
        "survival": {"photosynthesis_window_days": 4}}))
    (cdir / "vela.json").write_text(json.dumps({"name": "Vela"}))
    (cdir / "roscar.json").write_text(json.dumps({"name": "Roscar"}))
    (tmp_path / "CURRENT_STATUS.md").write_text(status_text)
    return tmp_path


def test_backfill_stamps_and_migrates(tmp_path):
    root = _campaign(tmp_path)
    changed = bf.backfill(root, dry_run=False)
    assert changed >= 2
    creen = json.loads((root / "characters" / "creenash.json").read_text())
    vela = json.loads((root / "characters" / "vela.json").read_text())
    roscar = json.loads((root / "characters" / "roscar.json").read_text())
    ct = next(c for c in creen["conditions"] if c["name"] == "Twinning")
    vt = next(c for c in vela["conditions"] if c["name"] == "Twinning")
    assert ct["effects"]["twinned"]["partner"] == "Vela"
    assert vt["effects"]["twinned"]["partner"] == "Creenash"
    assert ct["since_day"] == 31 and vt["since_day"] == 31
    assert creen["survival"]["photosynthesis_last_fed_day"] == 130
    assert "conditions" not in roscar


def test_fed_day_tool_format_fallback(tmp_path):
    root = _campaign(tmp_path, status_text=TOOL_STATUS)
    bf.backfill(root, dry_run=False)
    creen = json.loads((root / "characters" / "creenash.json").read_text())
    assert creen["survival"]["photosynthesis_last_fed_day"] == 130


def test_no_fed_day_line_warns_and_skips_migration(tmp_path, capsys):
    root = _campaign(tmp_path, status_text="# CURRENT STATUS - DAY 132\n"
                                           "No photosynthesis block here.\n")
    changed = bf.backfill(root, dry_run=False)
    assert changed == 2  # Twinning stamps only - no fed-day migration
    creen = json.loads((root / "characters" / "creenash.json").read_text())
    assert "photosynthesis_last_fed_day" not in creen["survival"]
    assert "supply(action=\"photosynthesis\")" in capsys.readouterr().out


def test_backfill_idempotent(tmp_path):
    root = _campaign(tmp_path)
    bf.backfill(root, dry_run=False)
    assert bf.backfill(root, dry_run=False) == 0
    creen = json.loads((root / "characters" / "creenash.json").read_text())
    assert sum(1 for c in creen["conditions"] if c["name"] == "Twinning") == 1


def test_dry_run_touches_nothing(tmp_path):
    root = _campaign(tmp_path)
    before = (root / "characters" / "creenash.json").read_text()
    bf.backfill(root, dry_run=True)
    assert (root / "characters" / "creenash.json").read_text() == before
