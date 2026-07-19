"""The deterministic blacklist scan is an UNCONDITIONAL backstop (2026-07-19).

Regression for the Thyricost leak: commit 173999d made _check_anti_pattern
early-return whenever validate_prose wasn't called that turn, switching the
Stop-hook scan OFF on exactly the unvalidated turns — 27 hard-banned phrases
reached live narration. The scan must now run regardless, while still arming
the validate_prose_required flag.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks import consolidated_stop_check as csc  # noqa: E402

BANNED_TURN = (
    "She watches him for a long moment before answering, and her hand finds "
    "the rail without her deciding it. The corridor breathes salt and old "
    "voltage; somewhere below, the city keeps its accounts. " * 2
)


def test_scan_runs_even_when_validate_prose_skipped():
    state = {"validate_prose_called": False, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    blocked, msg, updates = csc._check_anti_pattern({}, state, BANNED_TURN)
    assert blocked is False  # soft logger, never blocks
    assert updates.get("catch_count", 0) >= 1, \
        f"backstop scan did not run on unvalidated turn: {updates}"
    assert any("her hand finds" in k or "for a long moment" in k
               for k in updates.get("catch_log", {})), updates
    assert updates.get("validate_prose_required") is True  # flag still armed


def test_flag_not_armed_when_validated():
    state = {"validate_prose_called": True, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    _, _, updates = csc._check_anti_pattern({}, state, BANNED_TURN)
    assert updates.get("catch_count", 0) >= 1
    assert "validate_prose_required" not in updates


def test_prose_window_appends_and_caps(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))
    import rubicon_paths
    wpath = rubicon_paths.prose_window_path()
    assert str(tmp_path) in str(wpath)
    for i in range(csc._PROSE_WINDOW_CAP + 25):
        csc._append_prose_window(f"turn {i} " + "prose " * 40)
    lines = wpath.read_text(encoding="utf-8").splitlines()
    assert len(lines) == csc._PROSE_WINDOW_CAP
    import json as _json
    assert _json.loads(lines[-1])["text"].startswith(
        f"turn {csc._PROSE_WINDOW_CAP + 24} ")


def test_clean_unvalidated_turn_still_arms_flag():
    clean = ("Kess checks the bolt-count twice and hands the crossbow back. "
             "The stairwell smells of wet chalk. What do you do? " * 4)
    state = {"validate_prose_called": False, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    _, _, updates = csc._check_anti_pattern({}, state, clean)
    assert updates.get("validate_prose_required") is True
    assert updates.get("catch_count", 0) == 0
