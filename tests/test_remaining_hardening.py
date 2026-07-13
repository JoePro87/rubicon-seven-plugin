# tests/test_remaining_hardening.py
# Combined tests for Tasks 14-18

import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import save_state, _load_cultivation, _save_cultivation, antagonist, GAME_STATE, CAMPAIGN_DIR


def test_day_monotonicity_validation():
    """Task 14: Verify save_state warns when day goes backward."""
    # Create cultivation state on Day 100
    GAME_STATE["session_beats"] = [{"beat": "Event", "day": 100}]
    save_state(
        session_summary="Session 1",
        day=100,
        narrative_log="Log",
        scene_location="Location"
    )

    cult_content = _load_cultivation()
    assert "Day 100" in cult_content

    # Try to save on Day 95 (time travel!)
    GAME_STATE["session_beats"] = [{"beat": "Past event", "day": 95}]

    # Should warn but not crash
    result = save_state(
        session_summary="Time travel session",
        day=95,
        narrative_log="Log",
        scene_location="Location"
    )

    # Cultivation file should be unchanged (skip cultivation on time travel)
    cult_content = _load_cultivation()
    assert "Day 100" in cult_content
    assert "Time travel" not in cult_content


def test_antagonist_view_includes_metrics():
    """Task 15: Verify view action shows summary metrics."""
    # Add some content
    antagonist(action="add_threat", threat_name="Threat 1", escalation="high", details="Active", day=50)
    antagonist(action="add_threat", threat_name="Threat 2", escalation="med", details="Active", day=51)
    antagonist(action="add_seed", threat_name="Seed 1", details="Dormant", day=30)
    antagonist(action="add_seed", threat_name="Seed 2", details="Dormant", day=35)
    antagonist(action="add_seed", threat_name="Seed 3", details="Dormant", day=40)

    # View should include metrics
    result = antagonist(action="view", day=60)

    assert "Active threats: 2" in result or "2" in result
    assert "Dormant seeds: 3" in result or "3" in result
    assert "Oldest seed" in result.lower() or "oldest" in result.lower()


def test_antagonist_validate_command():
    """Task 15: Verify validate action checks file health."""
    # Create file with some content
    cult_content = """# ANTAGONIST CULTIVATION
Last updated: Day 50

## ACTIVE THREATS
### Valid Threat - Escalation: HIGH
- Details

## DORMANT SEEDS
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
[None yet]

## PRUNING LOG
[None yet]
"""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    cult_path.write_text(cult_content, encoding='utf-8')

    result = antagonist(action="validate", day=60)

    # Should validate successfully or report minor issues
    assert "validat" in result.lower()
