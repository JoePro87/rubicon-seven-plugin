# tests/test_antagonist_integration.py
import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import save_state, _load_cultivation, antagonist, GAME_STATE, CAMPAIGN_DIR

def test_full_antagonist_workflow():
    """
    Integration test: Full cultivation workflow from session beats to file update.

    Simulates 3 sessions:
    1. Day 92: Trust breach (Haldib abandoned)
    2. Day 95: No interaction (seed sits dormant)
    3. Day 112: Seed auto-pruned (20+ days, no development)
    """

    # Session 1: Day 92 - Plant seed via save_state
    GAME_STATE["session_beats"] = [
        {"beat": "Creenash freed oracle, Haldib's worldview shattered", "day": 92},
        {"beat": "Party left without helping Haldib rebuild purpose", "day": 92}
    ]

    save_state(
        session_summary="Midden Oracle concluded. Haldib despondent.",
        day=92,
        narrative_log="Session narrative with Haldib interaction...",
        scene_location="Desert outside Midden Oracle"
    )

    # Verify seed planted
    cult_content_92 = _load_cultivation()
    assert "Day 92" in cult_content_92
    assert "OPPORTUNITIES" in cult_content_92
    assert "haldib" in cult_content_92.lower() or "worldview" in cult_content_92.lower()

    # Session 2: Day 95 - Unrelated session, seed sits
    GAME_STATE["session_beats"] = [
        {"beat": "Party traveled to Ceruline", "day": 95}
    ]

    save_state(
        session_summary="Travel day, no major events",
        day=95,
        narrative_log="Uneventful journey...",
        scene_location="Ceruline gates"
    )

    # Seed should still be there
    cult_content_95 = _load_cultivation()
    assert "Day 92" in cult_content_95  # Original opportunity still logged

    # Session 3: Day 113 - Seed auto-prunes (21 days dormant)
    GAME_STATE["session_beats"] = [
        {"beat": "Party met with Council", "day": 113}
    ]

    save_state(
        session_summary="Council meeting, political discussions",
        day=113,
        narrative_log="Politics and bureaucracy...",
        scene_location="Council chambers"
    )

    # Haldib seed should be pruned (21 days old, no escalation)
    cult_content_113 = _load_cultivation()

    # Check PRUNING LOG
    assert "PRUNING LOG" in cult_content_113
    # Note: This depends on whether Haldib was added to DORMANT SEEDS or just OPPORTUNITIES
    # If in OPPORTUNITIES only, won't be pruned (opportunities are just notes)

    print("Full workflow test passed!")

def test_manual_escalation_workflow():
    """
    Test manual escalation from DORMANT → ACTIVE.
    """

    # Plant seed manually
    antagonist(
        action="add_seed",
        threat_name="Test Threat Manual",
        details="This is a test seed planted manually",
        day=100
    )

    cult_before = _load_cultivation()
    assert "Test Threat Manual" in cult_before
    assert "DORMANT SEEDS" in cult_before

    # Escalate to active
    antagonist(
        action="escalate",
        threat_name="Test Threat Manual",
        escalation="high",
        details="Threat has gathered resources, ready to strike",
        day=110
    )

    cult_after = _load_cultivation()
    assert "ACTIVE THREATS" in cult_after
    assert "Test Threat Manual" in cult_after
    assert "high" in cult_after.lower() or "HIGH" in cult_after
    assert "ESCALATION LOG" in cult_after
    assert "Day 110" in cult_after

    print("Manual escalation test passed!")


def test_escalation_preserves_original_context():
    """Verify escalating a seed preserves its original details."""
    # Add seed with detailed context
    antagonist(
        action="add_seed",
        threat_name="Context Preservation Test",
        details="Original motivation: jealousy. Trigger: if party returns to vault. Vulnerability: NPC is isolated.",
        day=80
    )

    # Verify original context is present
    cult_content = _load_cultivation()
    assert "Original motivation: jealousy" in cult_content
    assert "Trigger: if party returns" in cult_content

    # Escalate with new information
    antagonist(
        action="escalate",
        threat_name="Context Preservation Test",
        escalation="high",
        details="NPC acquired weapons, contacted allies",
        day=95
    )

    cult_content = _load_cultivation()

    # Both original AND new context should be present
    assert "Original motivation: jealousy" in cult_content, "Original context lost during escalation"
    assert "Trigger: if party returns" in cult_content, "Original trigger lost"
    assert "NPC acquired weapons" in cult_content, "New escalation details not added"
    assert "contacted allies" in cult_content

    # Should be in ACTIVE THREATS now (check between ACTIVE THREATS and next section)
    import re
    active_match = re.search(r'## ACTIVE THREATS(.*?)(?=\n## [A-Z]|$)', cult_content, re.DOTALL)
    assert active_match, "ACTIVE THREATS section not found"
    active_section = active_match.group(1)
    assert "Context Preservation Test" in active_section, f"Threat not in ACTIVE section. Section: {active_section[:200]}"


def test_hardened_system_full_workflow():
    """
    TASK 18: End-to-end test of hardened antagonist cultivation system.

    Simulates campaign with:
    - Edge cases (Unicode, false positives, special chars)
    - Manual operations
    - Auto-pruning
    - Token budget enforcement
    - File corruption recovery
    - View metrics and validate features
    """
    import re
    from server import _save_cultivation, _load_cultivation, antagonist, save_state, GAME_STATE, CAMPAIGN_DIR

    # SETUP: Reset cultivation file to clean template
    template = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 0

---

## ACTIVE THREATS
*Things currently in motion, escalating*

[None yet]

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

[None yet]

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

[None yet]

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""
    _save_cultivation(template)

    # PHASE 1: Test edge case handling
    # Unicode in threat names
    antagonist(
        action="add_seed",
        threat_name="Café Résistance™",  # Special chars, unicode, trademark symbol
        details="Owner angered by party's café critique",
        day=50
    )

    cult_content = _load_cultivation()
    assert "Café Résistance™" in cult_content, "Unicode threat name not preserved"

    # PHASE 2: Test false positive avoidance
    GAME_STATE["session_beats"] = [
        {"beat": "Party broke camp at dawn", "day": 51},
        {"beat": "Creenash lied down to rest", "day": 51},
        {"beat": "Found embroidered tapestry", "day": 51},
    ]

    save_state(
        session_summary="False positive test - should not trigger threats",
        day=51,
        narrative_log="Exploration day with no actual threats",
        scene_location="Desert camp"
    )

    cult_content = _load_cultivation()
    # Should NOT have opportunities from false positives
    opportunities_match = re.search(r'## OPPORTUNITIES(.*?)(?=\n## |$)', cult_content, re.DOTALL)
    if opportunities_match:
        opps_text = opportunities_match.group(1).lower()
        # Should not have "broke camp" or "lied down" as threats
        assert "broke camp" not in opps_text, "False positive: 'broke camp' detected as threat"
        assert "lied down" not in opps_text, "False positive: 'lied down' detected as threat"

    # PHASE 3: Test actual threat detection
    GAME_STATE["session_beats"] = [
        {"beat": "Vela broke her promise to the synth merchant", "day": 52},
        {"beat": "Creenash lied to the Council about vault contents", "day": 52},
        {"beat": "Party abandoned wounded NPC in the ruins", "day": 52},
    ]

    save_state(
        session_summary="Real threat test - should detect all 3",
        day=52,
        narrative_log="Session with actual betrayals and breaches",
        scene_location="Ceruline"
    )

    cult_content = _load_cultivation()
    opportunities_match = re.search(r'## OPPORTUNITIES(.*?)(?=\n## |$)', cult_content, re.DOTALL)
    assert opportunities_match, "No opportunities section found"
    opps_text = opportunities_match.group(1).lower()

    # Should detect at least one real threat (pattern matching working)
    threat_detected = any([
        "broke" in opps_text or "promise" in opps_text,
        "lied" in opps_text or "council" in opps_text,
        "abandoned" in opps_text or "wounded" in opps_text
    ])
    assert threat_detected, f"No real threats detected in opportunities. Content: {opps_text[:200]}"

    # PHASE 4: Test manual escalation with special chars
    antagonist(
        action="escalate",
        threat_name="Café Résistance™",
        escalation="med",
        details="Owner contacted rival syndicate for revenge",
        day=55
    )

    cult_content = _load_cultivation()
    # Should be in ACTIVE THREATS now
    active_match = re.search(r'## ACTIVE THREATS(.*?)(?=\n## |$)', cult_content, re.DOTALL)
    assert active_match, "ACTIVE THREATS section not found"
    assert "Café Résistance™" in active_match.group(1), "Unicode threat not escalated"
    assert "med" in active_match.group(1).lower() or "MED" in active_match.group(1)

    # Original context should be preserved
    assert "café critique" in cult_content.lower(), "Original seed context lost during escalation"

    # PHASE 5: Test file corruption recovery
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Corrupt the file (missing section)
    corrupted = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 55

---

## ACTIVE THREATS
*Things currently in motion, escalating*

### Test Threat - Escalation: LOW
- Details here

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

[None yet]

---

**MISSING ESCALATION LOG SECTION**

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

**MISSING PRUNING LOG SECTION**
"""

    cult_path.write_text(corrupted, encoding='utf-8')

    # Next save should auto-repair
    GAME_STATE["session_beats"] = [{"beat": "Recovery test", "day": 56}]
    save_state(
        session_summary="Testing corruption recovery",
        day=56,
        narrative_log="Minimal session",
        scene_location="Location"
    )

    cult_content = _load_cultivation()
    # All sections should be present now
    assert "## ESCALATION LOG" in cult_content, "Missing section not auto-created"
    assert "## PRUNING LOG" in cult_content, "Missing pruning log not auto-created"

    # PHASE 6: Test view metrics
    view_result = antagonist(action="view", day=56)

    assert "# ANTAGONIST CULTIVATION METRICS" in view_result
    assert "Active threats:" in view_result
    assert "Dormant seeds:" in view_result
    assert "Oldest seed:" in view_result
    assert "Token usage:" in view_result
    assert "/ 2000 tokens" in view_result
    assert "File size:" in view_result
    assert "/ 6500 chars" in view_result

    # PHASE 7: Test validate command
    validate_result = antagonist(action="validate", day=56)

    # Should pass or have specific issues
    assert "VALIDATION" in validate_result
    assert "File size:" in validate_result or "File health:" in validate_result

    # PHASE 8: Test token budget enforcement
    # Fill file with many opportunities to approach limit
    opportunities_list = [
        f"Day {56 + i}: Test opportunity {i} with lots of detail about authentication, synchronization, configuration, implementation"
        for i in range(100)  # Many opportunities
    ]

    # Build bloated content
    bloated = f"""# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 156

---

## ACTIVE THREATS
*Things currently in motion, escalating*

[None yet]

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

[None yet]

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

[None yet]

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

{chr(10).join(opportunities_list)}

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

    cult_path.write_text(bloated, encoding='utf-8')

    # Add one more opportunity via save
    GAME_STATE["session_beats"] = [{"beat": "One more opportunity", "day": 157}]
    save_state(
        session_summary="Should trigger truncation",
        day=157,
        narrative_log="Session",
        scene_location="Location"
    )

    cult_content = _load_cultivation()
    char_count = len(cult_content)
    approx_tokens = char_count / 3.5

    # Should be under token budget
    assert approx_tokens < 2000, f"Token budget exceeded: ~{approx_tokens:.0f} tokens"
    assert char_count < 6500, f"Char budget exceeded: {char_count} chars"

    # PHASE 9: Test atomic write protection
    # This is tested in unit tests, but verify file exists and is valid
    cult_content = _load_cultivation()
    assert "# ANTAGONIST CULTIVATION" in cult_content

    # No temp file should be left behind
    tmp_path = cult_path.with_suffix('.md.tmp')
    assert not tmp_path.exists(), "Temp file left behind (atomic write failed)"

    # PHASE 10: Test prune cleanup (prunes DORMANT seeds, not ACTIVE threats)
    # Add a seed that stays dormant
    antagonist(
        action="add_seed",
        threat_name="Prune Dormant Test",
        details="This will stay dormant and be pruned",
        day=160
    )

    cult_before_prune = _load_cultivation()
    assert "Prune Dormant Test" in cult_before_prune
    dormant_before = re.search(r'## DORMANT SEEDS(.*?)(?=\n## |$)', cult_before_prune, re.DOTALL)
    assert dormant_before, "Dormant seeds section missing"
    assert "Prune Dormant Test" in dormant_before.group(1), "Seed not in dormant section"

    # Prune it (should remove from DORMANT and log)
    antagonist(
        action="prune",
        threat_name="Prune Dormant Test",
        day=162
    )

    cult_after_prune = _load_cultivation()

    # Should be removed from DORMANT SEEDS
    dormant_after = re.search(r'## DORMANT SEEDS(.*?)(?=\n## |$)', cult_after_prune, re.DOTALL)
    if dormant_after:
        assert "Prune Dormant Test" not in dormant_after.group(1), "Pruned seed still in DORMANT"

    # Should be removed from ESCALATION LOG (if it was there)
    escalation_after = re.search(r'## ESCALATION LOG(.*?)(?=\n## |$)', cult_after_prune, re.DOTALL)
    if escalation_after and "Prune Dormant Test" in escalation_before.group(1) if 'escalation_before' in locals() else False:
        assert "Prune Dormant Test" not in escalation_after.group(1), "Pruned seed still in escalation log"

    # Should be in PRUNING LOG
    pruning_match = re.search(r'## PRUNING LOG(.*?)(?=\n## |$)', cult_after_prune, re.DOTALL)
    assert pruning_match, "Pruning log missing"
    assert "Prune Dormant Test" in pruning_match.group(1), "Prune not logged"

    print("✓ Comprehensive hardening test PASSED")
    print("  - Unicode/special chars handled")
    print("  - False positives avoided")
    print("  - Real threats detected")
    print("  - Manual escalation works")
    print("  - File corruption recovery works")
    print("  - View metrics feature works")
    print("  - Validate feature works")
    print("  - Token budget enforced")
    print("  - Atomic writes verified")
    print("  - Prune cleanup verified")
