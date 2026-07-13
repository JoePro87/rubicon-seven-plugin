"""Tests for phrase_reminder.py semantic-catch integration."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks import phrase_reminder, analytics_utils


import pytest


@pytest.fixture
def temp_analytics(tmp_path, monkeypatch):
    """Redirect analytics file to a temp location."""
    analytics_file = tmp_path / "catch_analytics.json"
    monkeypatch.setattr(analytics_utils, "ANALYTICS_FILE", analytics_file)
    return analytics_file


def test_top_semantic_catches_returns_most_frequent(temp_analytics):
    """Top-N by frequency across the session."""
    # Seed: Reaction Shot x3, The Pause x2, Landing x1
    for i in range(3):
        analytics_utils.log_semantic_catch(
            f"quote {i}", "Reaction Shot", "high", "sess-1", i,
        )
    for i in range(2):
        analytics_utils.log_semantic_catch(
            f"pause-q {i}", "The Pause", "high", "sess-1", i + 10,
        )
    analytics_utils.log_semantic_catch(
        "land-q", "Landing", "medium", "sess-1", 20,
    )

    top = phrase_reminder.top_semantic_categories(session_id="sess-1", limit=2)
    assert len(top) == 2
    assert top[0][0] == "Reaction Shot"
    assert top[0][1] == 3
    assert top[1][0] == "The Pause"
    assert top[1][1] == 2


def test_top_semantic_catches_empty_when_no_data(temp_analytics):
    """No data: returns empty list, no error."""
    top = phrase_reminder.top_semantic_categories(session_id="sess-new", limit=3)
    assert top == []


def test_build_reminder_includes_semantic_section_when_data_exists(temp_analytics):
    """Reminder string includes a 'Session semantic patterns' section."""
    analytics_utils.log_semantic_catch(
        "goes very still", "Reaction Shot", "high", "sess-live", 1
    )
    analytics_utils.log_semantic_catch(
        "stays still", "Reaction Shot", "high", "sess-live", 2
    )

    reminder = phrase_reminder.build_semantic_reminder(session_id="sess-live")
    assert "Reaction Shot" in reminder
    assert "2" in reminder  # count


def test_build_reminder_degrades_gracefully_without_semantic_data(temp_analytics):
    """No semantic data: reminder still returns (empty string or graceful degradation)."""
    reminder = phrase_reminder.build_semantic_reminder(session_id="sess-empty")
    # Does not crash; returns some string (may be empty or regex-only)
    assert isinstance(reminder, str)


def test_main_includes_semantic_reminder_in_output(temp_analytics, monkeypatch, capsys):
    """main() output concatenates semantic reminder after regex reminder."""
    import json as _json
    import io

    # Seed analytics with a semantic catch
    analytics_utils.log_semantic_catch(
        "goes very still", "Reaction Shot", "high", "main-test-session", 1
    )

    # Mock stdin to simulate hook input with session_id
    hook_input = {"session_id": "main-test-session"}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(hook_input)))

    # Monkeypatch load_state on phrase_reminder's namespace (it imports the name directly)
    # to return a gameplay session, bypassing the early-exit guards
    monkeypatch.setattr(
        phrase_reminder,
        "load_state",
        lambda: {
            "session_type": "gameplay",
            "skip_canon_enforcement": False,
            "catch_count": 0,
            "catch_log": {},
            "session_vocabulary": [],
        },
    )

    # Run main — exit code should be 0; output may go to stdout (hook context) or stderr
    try:
        phrase_reminder.main()
    except SystemExit as e:
        assert e.code in (0, None), f"main() exited with {e.code}"

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err
    # The semantic reminder contains "Session semantic patterns"
    assert "Session semantic patterns" in combined_output or "Reaction Shot" in combined_output, \
        f"Expected semantic reminder in output. Got: {combined_output[:500]}"
