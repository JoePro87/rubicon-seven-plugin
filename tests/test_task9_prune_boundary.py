# tests/test_task9_prune_boundary.py
"""
TASK 9: Fix Prune Boundary Documentation

Issue: Docs say "20+ days" but implementation uses >= 20 (exactly 20 days).
Fix: Update documentation to match implementation and add test to verify boundary.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _review_cultivation, _save_cultivation

def test_prune_boundary_at_exactly_20_days():
    """Verify seeds are pruned at EXACTLY 20 days, not 21+.

    This test documents the expected behavior:
    - Seed planted Day 80, pruned Day 100 (age = 20)
    - Seed planted Day 81, NOT pruned Day 100 (age = 19)
    """

    cult_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 100

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Seed Planted Day 80 - Day planted: 80
- Should be pruned at Day 100 (exactly 20 days)

### Seed Planted Day 81 - Day planted: 81
- Should NOT be pruned at Day 100 (only 19 days)

### Seed Planted Day 79 - Day planted: 79
- Should be pruned at Day 100 (21 days, definitely old enough)

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
[None yet]

## PRUNING LOG
[None yet]
"""

    _save_cultivation(cult_content)

    review = _review_cultivation(recent_beats=[], current_day=100, session_summary="")

    print("\nPrune review results:")
    print(f"  Prunes: {review['prunes']}")

    # Verify Day 80 seed IS pruned (age = 20)
    assert any("Day 80" in p for p in review["prunes"]), "Seed planted Day 80 should be pruned at Day 100 (age=20)"

    # Verify Day 81 seed is NOT pruned (age = 19)
    assert not any("Day 81" in p for p in review["prunes"]), "Seed planted Day 81 should NOT be pruned at Day 100 (age=19)"

    # Verify Day 79 seed IS pruned (age = 21)
    assert any("Day 79" in p for p in review["prunes"]), "Seed planted Day 79 should be pruned at Day 100 (age=21)"

    print("Prune boundary test passed!")
    print("  - Confirmed: age >= 20 triggers pruning")
    print("  - Confirmed: age < 20 does NOT trigger pruning")


def test_prune_boundary_edge_cases():
    """Test various edge cases around the 20-day boundary."""

    cult_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Day 30 seed - Day planted: 30
- Age 20 exactly

### Day 29 seed - Day planted: 29
- Age 21

### Day 31 seed - Day planted: 31
- Age 19

### Day 0 seed - Day planted: 0
- Age 50

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
[None yet]

## PRUNING LOG
[None yet]
"""

    _save_cultivation(cult_content)

    review = _review_cultivation(recent_beats=[], current_day=50, session_summary="")

    # All seeds with age >= 20 should be pruned
    assert len(review["prunes"]) == 3, f"Expected 3 prunes (age >= 20), got {len(review['prunes'])}"

    # Verify the correct seeds
    pruned_names = set(review["prunes"])
    assert "Day 30 seed" in pruned_names, "Age 20 should be pruned"
    assert "Day 29 seed" in pruned_names, "Age 21 should be pruned"
    assert "Day 0 seed" in pruned_names, "Age 50 should be pruned"
    assert "Day 31 seed" not in pruned_names, "Age 19 should NOT be pruned"

    print("Edge case test passed!")
