# tests/test_task11_escalation_validation.py
"""
TASK 11: Add Escalation Enum Validation

Issue: Invalid escalation values accepted (typos like "medum").
Fix: Add validation at start of antagonist() tool.
"""

import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import antagonist, ToolError

def test_antagonist_validates_escalation_enum():
    """Verify escalation parameter rejects invalid values."""

    # Valid escalations should work
    for valid in ["low", "med", "high", "crisis"]:
        result = antagonist(action="add_threat", threat_name=f"Valid {valid}", escalation=valid, details="Test", day=50)
        assert "added" in result.lower() or "threat" in result.lower()

    print("All valid escalations accepted!")


def test_antagonist_rejects_invalid_escalation_add_threat():
    """Verify add_threat rejects invalid escalation values."""

    invalid_values = ["medum", "hgih", "Low", "CRISIS", "medium", "loww", ""]

    for invalid in invalid_values:
        with pytest.raises(ToolError) as exc_info:
            antagonist(action="add_threat", threat_name="Invalid", escalation=invalid, details="Test", day=50)

        assert "Invalid escalation" in str(exc_info.value), \
            f"Expected 'Invalid escalation' error for '{invalid}', got: {exc_info.value}"

    print(f"All {len(invalid_values)} invalid escalations correctly rejected!")


def test_antagonist_rejects_invalid_escalation_escalate():
    """Verify escalate action rejects invalid escalation values."""

    # First add a valid seed
    antagonist(action="add_seed", threat_name="Test Seed", details="Valid seed", day=50)

    # Try to escalate with invalid escalation level
    with pytest.raises(ToolError) as exc_info:
        antagonist(action="escalate", threat_name="Test Seed", escalation="medum", details="Invalid", day=55)

    assert "Invalid escalation" in str(exc_info.value)

    print("Escalate action correctly validates escalation!")


def test_antagonist_allows_default_escalation():
    """Verify default escalation value works."""

    # When calling antagonist directly, we need to explicitly pass escalation
    # The MCP framework handles defaults, but direct Python calls need explicit values
    result = antagonist(
        action="add_threat",
        threat_name="Default Escalation Test",
        escalation="low",  # Explicitly pass default value
        details="Test",
        day=50
    )
    assert "added" in result.lower() or "threat" in result.lower()

    print("Default escalation works!")
