# tests/test_task10_opportunity_truncation.py
"""
TASK 10: Fix Opportunity Truncation to Preserve Day Context

Issue: Line-based truncation cuts mid-day, losing context.
Fix: Group by day and keep last 8 complete days.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import save_state, _load_cultivation, _save_cultivation, GAME_STATE

def test_opportunity_truncation_preserves_day_context():
    """Verify opportunity truncation keeps complete days, not partial."""

    # Create a cultivation file with many opportunities across multiple days
    opportunities = []
    for day in range(85, 100):  # 15 days of history
        for i in range(3):  # 3 opportunities per day
            opportunities.append(f"- Day {day}: Opportunity {i} for this day")

    cult_content = f"""# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 99

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
""" + "\n".join(opportunities) + """

## PRUNING LOG
[None yet]
"""

    _save_cultivation(cult_content)

    # Run save_state which should trigger truncation
    GAME_STATE["session_beats"] = [{"beat": "Test event", "day": 100}]
    save_state(
        session_summary="Test",
        day=100,
        narrative_log="Log",
        scene_location="Location"
    )

    cult_content = _load_cultivation()
    opps_section = cult_content.split("## OPPORTUNITIES")[1].split("## ")[0]

    # Extract all days mentioned in opportunities
    import re
    day_matches = re.findall(r'Day (\d+):', opps_section)
    remaining_days = sorted(set(int(d) for d in day_matches))

    print(f"\nRemaining days in opportunities: {remaining_days}")
    print(f"Total days: {len(remaining_days)}")

    # Verify we kept complete days only
    for day in remaining_days:
        day_lines = [line for line in opps_section.split("\n") if f"Day {day}:" in line]
        # Each day should have either 0 or 3 opportunities (complete or absent)
        if day < 100:  # Day 100 might have different count (just added)
            assert len(day_lines) == 0 or len(day_lines) == 3, \
                f"Day {day} has partial data ({len(day_lines)} opportunities) - should be 0 or 3"

    print("Opportunity truncation preserves complete days!")


def test_opportunity_truncation_keeps_last_8_days():
    """Verify we keep approximately the last 8 days of opportunities."""

    # Create 30 days of opportunities (5 per day) to force truncation
    # Each line is ~60 chars, so 150 lines * 60 = 9000 chars total file
    opportunities = []
    for day in range(70, 100):  # 30 days
        for i in range(5):  # 5 opportunities per day to make file larger
            opportunities.append(f"- Day {day}: Opportunity {i} with extra text to make it longer and force truncation sooner")

    cult_content = f"""# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 99

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
""" + "\n".join(opportunities) + """

## PRUNING LOG
[None yet]
"""

    _save_cultivation(cult_content)

    # Trigger save_state with truncation
    GAME_STATE["session_beats"] = [{"beat": "Event", "day": 100}]
    save_state(
        session_summary="Test",
        day=100,
        narrative_log="Log",
        scene_location="Location"
    )

    cult_content = _load_cultivation()
    opps_section = cult_content.split("## OPPORTUNITIES")[1].split("## ")[0]

    # Extract days
    import re
    day_matches = re.findall(r'Day (\d+):', opps_section)
    remaining_days = sorted(set(int(d) for d in day_matches))

    print(f"\nKept {len(remaining_days)} days: {remaining_days}")

    # Should keep roughly 8 days (might be a bit more depending on implementation)
    assert len(remaining_days) <= 10, f"Should keep ~8 days, got {len(remaining_days)}"
    assert len(remaining_days) >= 6, f"Should keep at least 6 days, got {len(remaining_days)}"

    # Oldest day should be relatively recent (within last ~10 days)
    if remaining_days:
        oldest_day = min(remaining_days)
        assert oldest_day >= 88, f"Oldest day should be >= 88, got {oldest_day}"

    print(f"Successfully kept last ~8 days (actual: {len(remaining_days)} days)")
