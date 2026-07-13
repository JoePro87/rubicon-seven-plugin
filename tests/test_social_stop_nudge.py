"""Task 11: stale-parley nudge in the Stop hook (non-blocking advisory).

Unit-tests the pure helper directly, mirroring how
tests/test_stop_checks_transcript_port.py imports hook internals (the
hooks/ dir is on sys.path so `consolidated_stop_check` imports as a
top-level module, matching the hook's own `from hooks.hook_utils import ...`
package-relative imports at runtime).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

import social_system as ss  # noqa: E402

from consolidated_stop_check import _stale_parley_lines  # noqa: E402


def test_stale_parley_line(tmp_path):
    ss.open_parley(tmp_path, "x", title="Dock dispute", day=100)
    lines = _stale_parley_lines(tmp_path, current_day=110)
    assert len(lines) == 1 and "Dock dispute" in lines[0]


def test_fresh_and_closed_are_silent(tmp_path):
    ss.open_parley(tmp_path, "x", title="Dock dispute", day=100)
    assert _stale_parley_lines(tmp_path, current_day=103) == []


def test_missing_parleys_file_is_silent(tmp_path):
    # No parleys.json at all — must not raise.
    assert _stale_parley_lines(tmp_path, current_day=999) == []


def test_corrupt_parleys_file_is_silent(tmp_path):
    (tmp_path / "parleys.json").write_text("{not json", encoding="utf-8")
    assert _stale_parley_lines(tmp_path, current_day=999) == []


def test_non_int_current_day_is_silent(tmp_path):
    ss.open_parley(tmp_path, "x", title="Dock dispute", day=100)
    assert _stale_parley_lines(tmp_path, current_day=None) == []


def test_log_activity_resets_staleness(tmp_path):
    ss.open_parley(tmp_path, "x", title="Dock dispute", day=100)
    data = ss.load_parleys(tmp_path)
    data["x"]["log"].append({"day": 108, "entry": "checked in"})
    ss.save_parleys(tmp_path, data)
    # Latest activity is day 108, not opened_day 100 — only 2 days quiet.
    assert _stale_parley_lines(tmp_path, current_day=110) == []


def test_closed_parley_is_silent(tmp_path):
    ss.open_parley(tmp_path, "x", title="Dock dispute", day=100)
    data = ss.load_parleys(tmp_path)
    data["x"]["status"] = "closed"
    ss.save_parleys(tmp_path, data)
    assert _stale_parley_lines(tmp_path, current_day=200) == []
