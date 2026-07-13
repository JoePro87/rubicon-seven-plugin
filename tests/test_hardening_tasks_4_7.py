"""
Tests for hardening tasks 4-7 (TDD approach).

Task 4: Preview mode skips cultivation
Task 5: Regex escaping for seed names
Task 6: Auto-recreate missing sections
Task 7: Unicode console output handling
"""

import pytest
import re
from pathlib import Path
import sys

# Import server.py functions
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))
import server
from server import (
    save_state, antagonist, sync_campaign_day,
    CAMPAIGN_DIR, GAME_STATE, _load_cultivation, _save_cultivation
)


# ============================================
# TASK 4: Preview Mode Skips Cultivation
# ============================================

def test_preview_mode_skips_cultivation():
    """Verify preview mode has zero side effects on cultivation file AND logic."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Create initial cultivation state
    initial_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 40

## ACTIVE THREATS
*Things currently in motion, escalating*
[None yet]

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*
[None yet]

---

## ESCALATION LOG
[None yet]

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*
[None yet]

---

## PRUNING LOG
[None yet]
"""
    cult_path.write_text(initial_content, encoding='utf-8')

    # Track if _review_cultivation was called (indicates side effects)
    import server
    original_review = server._review_cultivation
    review_called = {"called": False}

    def mock_review(*args, **kwargs):
        review_called["called"] = True
        return original_review(*args, **kwargs)

    server._review_cultivation = mock_review

    try:
        # Run save_state in preview mode with new opportunities
        GAME_STATE["session_beats"] = [
            {"beat": "Creenash abandoned Haldib", "day": 45}
        ]

        result = save_state(
            session_summary="Preview test session with opportunity that should trigger cultivation",
            day=45,
            narrative_log="Preview narrative",
            scene_location="Test location",
            preview=True
        )

        # Cultivation logic should NOT have been called at all
        assert not review_called["called"], "Preview mode executed cultivation logic (side effect violation)!"

        # Cultivation file should be unchanged
        final_content = cult_path.read_text(encoding='utf-8')
        assert final_content == initial_content, "Preview mode modified cultivation file!"
        assert "Day 45" not in final_content
        assert "abandoned" not in final_content.lower()
    finally:
        # Restore original function
        server._review_cultivation = original_review


# ============================================
# TASK 5: Regex Escaping for Seed Names
# ============================================

def test_seed_names_with_special_chars():
    """Verify seed names with regex metacharacters work correctly."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    special_names = [
        "NPC (parentheses)",
        "Event [brackets]",
        "Choice: option A vs. option B",
    ]

    for name in special_names:
        # Reset cultivation file
        template = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

## ACTIVE THREATS
[None yet]

## DORMANT SEEDS
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
[None yet]

## PRUNING LOG
[None yet]
"""
        cult_path.write_text(template, encoding='utf-8')

        # Add seed
        result = antagonist(
            action="add_seed",
            threat_name=name,
            details="Test seed",
            day=50
        )
        assert "planted" in result.lower() or "added" in result.lower(), f"Failed to add seed '{name}'"

        # Verify in file
        cult_content = _load_cultivation()
        assert name in cult_content, f"Seed '{name}' not found in cultivation file"

        # Prune it
        result = antagonist(
            action="prune",
            threat_name=name,
            day=55
        )
        assert "pruned" in result.lower(), f"Failed to prune seed '{name}'"

        # Verify removed
        cult_content = _load_cultivation()
        assert name not in cult_content or "Pruned" in cult_content, f"Seed '{name}' not properly pruned"


def test_escalate_with_special_chars():
    """Verify escalation works with special character names."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Reset cultivation file
    template = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

## ACTIVE THREATS
[None yet]

## DORMANT SEEDS
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
[None yet]

## PRUNING LOG
[None yet]
"""
    cult_path.write_text(template, encoding='utf-8')

    # Add seed with special chars
    name = "Threat (complex) [urgent]"
    antagonist(
        action="add_seed",
        threat_name=name,
        details="Test threat",
        day=50
    )

    # Escalate it
    result = antagonist(
        action="escalate",
        threat_name=name,
        escalation="high",
        details="Now active",
        day=70
    )

    assert "escalated" in result.lower()

    # Verify in ACTIVE THREATS
    cult_content = _load_cultivation()
    assert "## ACTIVE THREATS" in cult_content
    # Check it's after ACTIVE THREATS section
    threats_section = cult_content.split("## ACTIVE THREATS")[1].split("## DORMANT SEEDS")[0]
    assert name in threats_section


# ============================================
# TASK 6: Auto-Recreate Missing Sections
# ============================================

def test_missing_sections_are_recreated():
    """Verify missing cultivation sections are automatically recreated."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Create malformed file missing OPPORTUNITIES and PRUNING LOG
    malformed_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

## ACTIVE THREATS
[None yet]

## DORMANT SEEDS
[None yet]

## ESCALATION LOG
[None yet]
"""
    cult_path.write_text(malformed_content, encoding='utf-8')

    # Trigger save_state with opportunities
    GAME_STATE["session_beats"] = [
        {"beat": "Creenash broke his promise", "day": 51}
    ]

    save_state(
        session_summary="Test session",
        day=51,
        narrative_log="Test log",
        scene_location="Test location"
    )

    # File should have all sections now
    cult_content = cult_path.read_text(encoding='utf-8')
    assert "## OPPORTUNITIES" in cult_content, "OPPORTUNITIES section not recreated"
    assert "## PRUNING LOG" in cult_content, "PRUNING LOG section not recreated"


def test_all_required_sections_checked():
    """Verify all required sections are recreated if missing."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Create minimal file with only header
    minimal_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50
"""
    cult_path.write_text(minimal_content, encoding='utf-8')

    # Trigger save_state
    save_state(
        session_summary="Test session",
        day=51,
        narrative_log="Test log",
        scene_location="Test location"
    )

    # All required sections should exist
    cult_content = cult_path.read_text(encoding='utf-8')
    required_sections = [
        "## ACTIVE THREATS",
        "## DORMANT SEEDS",
        "## ESCALATION LOG",
        "## OPPORTUNITIES",
        "## PRUNING LOG"
    ]

    for section in required_sections:
        assert section in cult_content, f"Required section '{section}' not recreated"


# ============================================
# TASK 7: Unicode Console Output Handling
# ============================================

def test_unicode_in_seed_names_and_beats():
    """Verify Unicode characters in seeds/beats don't crash console output."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Reset cultivation file
    template = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

## ACTIVE THREATS
[None yet]

## DORMANT SEEDS
[None yet]

## ESCALATION LOG
[None yet]

## OPPORTUNITIES
[None yet]

## PRUNING LOG
[None yet]
"""
    cult_path.write_text(template, encoding='utf-8')

    # Add seed with Unicode (should not crash)
    try:
        result = antagonist(
            action="add_seed",
            threat_name="Unicode Test 🎭",
            details="Testing emoji support",
            day=50
        )
        assert "planted" in result.lower() or "added" in result.lower()
    except UnicodeEncodeError:
        pytest.fail("antagonist() crashed on Unicode in seed name")

    # Trigger cultivation with Unicode beats (should not crash)
    unicode_beats = [
        "Haldib's worldview 🔥 shattered",
        "Party visited café in Ceruline",
    ]
    GAME_STATE["session_beats"] = [{"beat": beat, "day": 51} for beat in unicode_beats]

    try:
        save_state(
            session_summary="Unicode test session 世界",
            day=51,
            narrative_log="Test log",
            scene_location="Test location"
        )
    except UnicodeEncodeError:
        pytest.fail("save_state() crashed on Unicode in beats")

    # Verify content was saved correctly
    cult_content = cult_path.read_text(encoding='utf-8')
    assert "Day 51" in cult_content, "Save failed with Unicode content"


def test_safe_print_fallback():
    """Verify _safe_print() handles Unicode gracefully."""
    # This test verifies the function exists and works
    from server import _safe_print

    # Should not crash on Unicode
    try:
        _safe_print("Test message 🎭 with emoji")
        _safe_print("Café résumé naïve")
        _safe_print("世界 Chinese characters")
    except UnicodeEncodeError:
        pytest.fail("_safe_print() failed to handle Unicode")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
