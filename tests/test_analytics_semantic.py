"""Tests for semantic catch logging and v2 schema."""

import json
import pytest
import sys
from pathlib import Path

# Hooks directory isn't on the default path
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks import analytics_utils


@pytest.fixture
def temp_analytics(tmp_path, monkeypatch):
    """Redirect analytics file to a temp location per test."""
    analytics_file = tmp_path / "catch_analytics.json"
    monkeypatch.setattr(analytics_utils, "ANALYTICS_FILE", analytics_file)
    return analytics_file


def test_log_semantic_catch_creates_entry(temp_analytics):
    """log_semantic_catch appends an entry keyed by (session_id, turn_id)."""
    analytics_utils.log_semantic_catch(
        quote="goes very still",
        category="Reaction Shot",
        confidence="high",
        session_id="sess-abc",
        turn_id=42,
    )

    data = json.loads(temp_analytics.read_text())
    assert "semantic_catches" in data
    assert len(data["semantic_catches"]) == 1
    entry = data["semantic_catches"][0]
    assert entry["quote"] == "goes very still"
    assert entry["category"] == "Reaction Shot"
    assert entry["confidence"] == "high"
    assert entry["session_id"] == "sess-abc"
    assert entry["turn_id"] == 42


def test_log_semantic_catch_idempotent_on_duplicate_quote(temp_analytics):
    """Same (session_id, turn_id, quote) overwrites. Different quotes on same turn append."""
    # Same quote, same turn, same session — idempotent, should overwrite
    analytics_utils.log_semantic_catch(
        quote="goes still",
        category="Reaction Shot",
        confidence="high",
        session_id="sess-abc",
        turn_id=42,
    )
    analytics_utils.log_semantic_catch(
        quote="goes still",
        category="Reaction Shot",
        confidence="medium",  # confidence changed — should overwrite
        session_id="sess-abc",
        turn_id=42,
    )

    data = json.loads(temp_analytics.read_text())
    assert len(data["semantic_catches"]) == 1
    assert data["semantic_catches"][0]["confidence"] == "medium"


def test_log_semantic_catch_multiple_violations_per_turn(temp_analytics):
    """A single turn with multiple distinct violations yields multiple entries."""
    analytics_utils.log_semantic_catch(
        quote="goes still", category="Reaction Shot", confidence="high",
        session_id="sess-abc", turn_id=42,
    )
    analytics_utils.log_semantic_catch(
        quote="silence stretches", category="The Pause", confidence="high",
        session_id="sess-abc", turn_id=42,
    )
    analytics_utils.log_semantic_catch(
        quote="for a long moment", category="Transition", confidence="medium",
        session_id="sess-abc", turn_id=42,
    )

    data = json.loads(temp_analytics.read_text())
    assert len(data["semantic_catches"]) == 3
    quotes = {e["quote"] for e in data["semantic_catches"]}
    assert quotes == {"goes still", "silence stretches", "for a long moment"}


def test_log_semantic_catch_preserves_existing_catches(temp_analytics):
    """Adding semantic catches must not corrupt existing regex `catches` list."""
    # Seed file with v1-shaped data
    v1_data = {
        "_meta": {"version": 1, "last_pruned": "2026-04-01", "total_sessions_tracked": 5},
        "catches": [{"phrase": "goes still", "scene_type": "social", "timestamp": "2026-04-01"}],
        "phrase_stats": {"goes still": 3},
    }
    temp_analytics.write_text(json.dumps(v1_data))

    analytics_utils.log_semantic_catch(
        quote="grows still",
        category="Reaction Shot",
        confidence="high",
        session_id="sess-xyz",
        turn_id=1,
    )

    data = json.loads(temp_analytics.read_text())
    # v1 sections intact
    assert data["catches"] == v1_data["catches"]
    assert data["phrase_stats"] == v1_data["phrase_stats"]
    # v2 schema applied
    assert data["_meta"]["version"] == 2
    # New section exists
    assert len(data["semantic_catches"]) == 1


def test_get_recent_semantic_catches_filters_by_session(temp_analytics):
    """get_recent_semantic_catches returns only catches for the given session."""
    analytics_utils.log_semantic_catch("a", "Reaction Shot", "high", "sess-1", 1)
    analytics_utils.log_semantic_catch("b", "The Pause", "high", "sess-2", 1)
    analytics_utils.log_semantic_catch("c", "Reaction Shot", "medium", "sess-1", 2)

    catches = analytics_utils.get_recent_semantic_catches(session_id="sess-1")
    assert len(catches) == 2
    assert {c["quote"] for c in catches} == {"a", "c"}


def test_get_recent_semantic_catches_returns_empty_when_no_data(temp_analytics):
    """Graceful: empty file yields empty list, no error."""
    catches = analytics_utils.get_recent_semantic_catches(session_id="sess-new")
    assert catches == []


def test_log_semantic_catch_records_iso_timestamp(temp_analytics):
    """Each entry carries an ISO-formatted timestamp field."""
    from datetime import datetime
    analytics_utils.log_semantic_catch(
        quote="q", category="Reaction Shot", confidence="high",
        session_id="sess-ts", turn_id=1,
    )
    data = json.loads(temp_analytics.read_text())
    entry = data["semantic_catches"][0]
    assert "timestamp" in entry
    # Should parse as ISO 8601 without raising
    datetime.fromisoformat(entry["timestamp"])
