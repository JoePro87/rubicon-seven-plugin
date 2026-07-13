# tests/test_task8_escalation_cleanup.py
"""
TASK 8: Clean Up Escalation Log During Pruning

Issue: When seeds are pruned, references in ESCALATION LOG remain.
Fix: Add escalation log cleanup to pruning logic.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import save_state, _load_cultivation, _save_cultivation, antagonist, GAME_STATE, CAMPAIGN_DIR

def test_pruning_cleans_escalation_log():
    """Verify pruned seeds are also removed from escalation log."""

    # Clean cultivation file first
    clean_cult = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 80

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
[None yet]

## PRUNING LOG
[None yet]
"""
    _save_cultivation(clean_cult)

    # Step 1: Add seed and escalate it
    antagonist(action="add_seed", threat_name="Test Escalation Cleanup", details="Initial seed", day=80)
    antagonist(action="escalate", threat_name="Test Escalation Cleanup", escalation="med", details="Escalated", day=85)

    # Verify it's in ACTIVE THREATS and ESCALATION LOG
    cult_content = _load_cultivation()
    assert "Test Escalation Cleanup" in cult_content
    assert "ACTIVE THREATS" in cult_content
    assert "ESCALATION LOG" in cult_content

    # Extract escalation log to verify entry exists
    if "## ESCALATION LOG" in cult_content:
        escalation_section = cult_content.split("## ESCALATION LOG")[1].split("## ")[0]
        assert "Test Escalation Cleanup" in escalation_section, "Escalation should be logged"

    # Step 2: Manually move back to DORMANT SEEDS (simulate de-escalation)
    # We need to completely rebuild the file to ensure proper format
    cult_parts = cult_content.split("## ESCALATION LOG")
    escalation_log_part = cult_parts[1] if len(cult_parts) > 1 else "\n[None yet]\n"

    # Rebuild with seed in DORMANT SEEDS
    cult_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 85

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Test Escalation Cleanup - Day planted: 80
- Initial seed
- Escalated

## ESCALATION LOG""" + escalation_log_part + """
## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
[None yet]

## PRUNING LOG
[None yet]
"""

    _save_cultivation(cult_content)

    # Step 3: Run save_state to trigger auto-pruning (Day 105, seed is 25 days old)
    GAME_STATE["session_beats"] = [{"beat": "Pruning test event", "day": 105}]
    save_state(
        session_summary="Pruning test",
        day=105,
        narrative_log="Log",
        scene_location="Location"
    )

    # Step 4: Verify seed is removed from BOTH DORMANT SEEDS and ESCALATION LOG
    cult_content = _load_cultivation()

    # Should be pruned from DORMANT SEEDS
    if "## DORMANT SEEDS" in cult_content:
        dormant_section = cult_content.split("## DORMANT SEEDS")[1].split("## ")[0]
        assert "Test Escalation Cleanup" not in dormant_section, "Seed should be pruned from DORMANT SEEDS"

    # Should be removed from ESCALATION LOG
    if "## ESCALATION LOG" in cult_content:
        escalation_section = cult_content.split("## ESCALATION LOG")[1].split("## ")[0]
        assert "Test Escalation Cleanup" not in escalation_section, "Escalation reference should be cleaned up"

    # Should appear in PRUNING LOG
    assert "PRUNING LOG" in cult_content
    if "## PRUNING LOG" in cult_content:
        prune_section = cult_content.split("## PRUNING LOG")[1].split("## ")[0]
        assert "Test Escalation Cleanup" in prune_section, "Should be logged in PRUNING LOG"

    print("✓ Escalation log cleanup test passed!")


def test_manual_prune_cleans_escalation_log():
    """Verify manual prune action also cleans escalation log."""

    # Clean cultivation file first
    clean_cult = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 70

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
[None yet]

## PRUNING LOG
[None yet]
"""
    _save_cultivation(clean_cult)

    # Add seed and escalate it
    antagonist(action="add_seed", threat_name="Manual Prune Test", details="Seed", day=70)
    antagonist(action="escalate", threat_name="Manual Prune Test", escalation="low", details="Escalated", day=75)

    # Move back to dormant manually
    cult_content = _load_cultivation()
    cult_content = cult_content.replace("## ACTIVE THREATS", "## ACTIVE THREATS\n*Things currently in motion, escalating*\n[None yet]")
    dormant_entry = f"""
### Manual Prune Test - Day planted: 70
- Seed
- Escalated
"""
    cult_content = cult_content.replace("## DORMANT SEEDS\n*Resentments, mistakes, vulnerabilities not yet active*\n[None yet]",
                                       f"## DORMANT SEEDS\n*Resentments, mistakes, vulnerabilities not yet active*{dormant_entry}")
    _save_cultivation(cult_content)

    # Verify escalation logged
    cult_content = _load_cultivation()
    if "## ESCALATION LOG" in cult_content:
        escalation_section = cult_content.split("## ESCALATION LOG")[1].split("## ")[0]
        assert "Manual Prune Test" in escalation_section

    # Manually prune
    antagonist(action="prune", threat_name="Manual Prune Test", day=90)

    # Verify cleaned from escalation log
    cult_content = _load_cultivation()
    if "## ESCALATION LOG" in cult_content:
        escalation_section = cult_content.split("## ESCALATION LOG")[1].split("## ")[0]
        assert "Manual Prune Test" not in escalation_section, "Manual prune should clean escalation log"

    print("✓ Manual prune escalation cleanup test passed!")
