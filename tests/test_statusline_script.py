import json, subprocess, sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "statusline_rubicon.py"


def _run(campaign):
    return subprocess.run([sys.executable, str(SCRIPT), str(campaign)],
                          capture_output=True, text=True, encoding="utf-8")


def test_golden_line(tmp_path):
    (tmp_path / "player_view.json").write_text(json.dumps({
        "day": 132, "weather": "Dust Storm", "location": "Dust Pilgrim's Rest",
        "party": [{"name": "Kess", "hp": 29, "hp_max": 29}],
        "supply": {"mode": "abundant"}, "in_combat": False,
        "open_parleys": [{"slug": "outer-reach", "tier": 2}],
        "wealth_tokens": 22280, "active_prep": None, "updated_at": "x"
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    line = r.stdout.strip()
    assert "Day 132" in line and "Dust Pilgrim's Rest" in line
    assert "Kess 29/29" in line and "🤝 1" in line
    assert "\n" not in line


def test_missing_file_fallback(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no live view" in r.stdout.lower()


def test_dashboard_hint_when_not_running(tmp_path):
    (tmp_path / "player_view.json").write_text(json.dumps({
        "day": 1, "party": [], "supply": {}, "in_combat": False,
        "open_parleys": [], "weather": None, "location": None,
        "wealth_tokens": 0, "active_prep": None, "updated_at": "x"
    }), encoding="utf-8")
    import os
    env = dict(os.environ, RUBICON_DASH_HINT="vaarn-dash")
    r = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    assert r.returncode == 0
    # In the test environment no dashboard.py process exists. On platforms with
    # /proc the hint must appear; where detection is unavailable it must not.
    if os.path.isdir("/proc"):
        expected = "vaarn-dash" in r.stdout
    else:
        expected = "vaarn-dash" not in r.stdout
    assert expected


def test_no_hint_on_fallback_line(tmp_path):
    r = _run(tmp_path)
    assert "dash" not in r.stdout.lower() or "no live view" in r.stdout.lower()
    assert "▸" not in r.stdout
