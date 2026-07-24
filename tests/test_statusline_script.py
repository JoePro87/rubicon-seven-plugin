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


def test_conditions_count_and_last_event(tmp_path):
    (tmp_path / "player_view.json").write_text(json.dumps({
        "day": 135, "weather": None, "location": "Thyricost",
        "party": [{"name": "Creenash", "hp": 18, "hp_max": 25,
                   "conditions": ["Burning", "Deprived"]}],
        "supply": {}, "in_combat": True, "open_parleys": [],
        "last_events": [{"kind": "pc_damage", "name": "Creenash", "amount": 7,
                         "new_hp": 18, "hp_max": 25}],
        "wealth_tokens": 0, "active_prep": None, "updated_at": "x"
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    line = r.stdout.strip()
    assert "Creenash 18/25!2c" in line   # 2 conditions
    assert "[Creenash -7]" in line       # most recent delta
    assert "\n" not in line


def test_enemy_last_event_is_qualitative(tmp_path):
    (tmp_path / "player_view.json").write_text(json.dumps({
        "day": 135, "weather": None, "location": None,
        "party": [], "supply": {}, "in_combat": True, "open_parleys": [],
        "last_events": [{"kind": "enemy_damage", "name": "Desiccator", "pct": 0.3}],
        "wealth_tokens": 0, "active_prep": None, "updated_at": "x"
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[Desiccator: bloodied]" in r.stdout   # word, never a number
    assert "0.3" not in r.stdout


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
