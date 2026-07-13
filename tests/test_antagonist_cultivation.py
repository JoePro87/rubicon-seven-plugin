# tests/test_antagonist_cultivation.py
import pytest
import sys
from pathlib import Path
sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from server import _load_cultivation, _save_cultivation, _review_cultivation, CAMPAIGN_DIR, save_state, GAME_STATE

def test_load_cultivation_creates_if_missing():
    """Should create template if file doesn't exist."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Remove if exists
    if cult_path.exists():
        backup = cult_path.read_text(encoding='utf-8')
        cult_path.unlink()

    try:
        content = _load_cultivation()
        assert "# ANTAGONIST CULTIVATION" in content
        assert "ACTIVE THREATS" in content
        assert cult_path.exists()
    finally:
        # Restore if we had backup
        if 'backup' in locals():
            cult_path.write_text(backup, encoding='utf-8')

def test_save_cultivation_writes_content():
    """Should write content to cultivation file."""
    test_content = "# TEST\\n\\nThis is test content."
    _save_cultivation(test_content)

    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    saved = cult_path.read_text(encoding='utf-8')
    assert "TEST" in saved

def test_review_cultivation_returns_dict():
    """Should return dict with opportunities, escalations, prunes."""
    # Mock recent beats
    beats = ["Creenash broke promise to Haldib", "Verdantis filed counter-motion"]

    result = _review_cultivation(
        recent_beats=beats,
        current_day=95,
        session_summary="Party left Midden Oracle without helping Haldib"
    )

    assert isinstance(result, dict)
    assert "opportunities" in result
    assert "escalations" in result


def test_load_cultivation_handles_corrupted_utf8():
    """Verify corrupted UTF-8 falls back to template."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Write invalid UTF-8 bytes
    cult_path.write_bytes(b'\xff\xfe\x00\x00 invalid UTF-8 sequence')

    # Should not crash, should return template
    result = _load_cultivation()
    assert "# ANTAGONIST CULTIVATION" in result
    assert "TOP SECRET" in result


def test_load_cultivation_handles_empty_file():
    """Verify empty file falls back to template."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    cult_path.write_text("", encoding='utf-8')

    result = _load_cultivation()
    assert "# ANTAGONIST CULTIVATION" in result
    assert "TOP SECRET" in result


def test_load_cultivation_handles_missing_file():
    """Verify missing file creates template."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    if cult_path.exists():
        cult_path.unlink()

    result = _load_cultivation()
    assert "# ANTAGONIST CULTIVATION" in result
    assert cult_path.exists()  # File should be created
    assert "PRUNING LOG" in result


def test_save_state_handles_corrupted_cultivation_file():
    """Verify save_state recovers from corrupted cultivation file."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Write corrupted content
    cult_path.write_text("CORRUPTED DATA - NOT VALID MARKDOWN", encoding='utf-8')

    # Should not crash, should recreate template
    GAME_STATE["session_beats"] = [{"beat": "Test beat", "day": 50}]
    save_state(
        session_summary="Recovery test",
        day=50,
        narrative_log="Log",
        scene_location="Location"
    )

    # File should be valid now
    cult_content = cult_path.read_text(encoding='utf-8')
    assert "# ANTAGONIST CULTIVATION" in cult_content
    assert "Day 50" in cult_content

def test_save_state_calls_cultivation():
    """save_state should call cultivation review before main save."""
    from server import save_state, _load_cultivation, _save_cultivation, GAME_STATE

    # Reset cultivation file to clean template
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

    # Mock recent beats with opportunity
    GAME_STATE["session_beats"] = [
        {"beat": "Creenash abandoned Haldib at Midden Oracle", "day": 95}
    ]

    # Call save_state
    result = save_state(
        session_summary="Party left vault",
        day=95,
        narrative_log="Session narrative here",
        scene_location="Ceruline"
    )

    # Cultivation file should have been updated
    cult_content = _load_cultivation()
    assert "Last updated: Day 95" in cult_content
    assert "OPPORTUNITIES" in cult_content

    # Should contain the opportunity from beats
    assert "abandoned" in cult_content.lower() or "haldib" in cult_content.lower()

def test_cultivation_before_main_save():
    """Cultivation review should complete before file writes."""
    import time
    from server import save_state, _load_cultivation, _save_cultivation, CAMPAIGN_DIR

    # Reset cultivation file to clean template
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

    start = time.time()
    result = save_state(
        session_summary="Test session",
        day=96,
        narrative_log="Narrative text here"
    )
    elapsed = time.time() - start

    # Cultivation should add minimal overhead (<2 seconds total)
    assert elapsed < 2.0, f"save_state took {elapsed}s, cultivation may be blocking"

    # Cultivation file should exist and be updated
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    assert cult_path.exists()
    content = cult_path.read_text(encoding='utf-8')
    assert "Day 96" in content

def test_cultivation_checks_content_forge():
    """Cultivation should reference content-forge conflicts when appropriate."""
    beats = ["Party traveled through wasteland", "Encountered sandstorm"]

    result = _review_cultivation(
        recent_beats=beats,
        current_day=100,
        session_summary="Uneventful travel day"
    )

    # Should have checked for environmental threats
    # (Implementation will vary based on content-forge structure)
    assert isinstance(result, dict)
    assert "opportunities" in result
    # Should detect travel vulnerability
    assert len(result["opportunities"]) > 0

def test_token_budget_enforces_under_2000_tokens():
    """Verify token budget keeps file under 2000 tokens, not just 8000 chars."""
    from server import save_state, _save_cultivation, GAME_STATE

    # Create cultivation file with many opportunities (dense token content)
    # Each opportunity has dense technical terms that consume ~1 token per 3 chars
    opportunities_section = "\n".join([
        f"- Day {i}: Party authentication, synchronization, authorization, configuration, implementation vulnerability detected"
        for i in range(1, 50)
    ])

    dense_content = f"""# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

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

{opportunities_section}

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"

    # Backup existing file if present
    backup = None
    if cult_path.exists():
        backup = cult_path.read_text(encoding='utf-8')

    try:
        cult_path.write_text(dense_content, encoding='utf-8')

        # Trigger save_state with a few more opportunities
        GAME_STATE["session_beats"] = [{"beat": f"Event {i}", "day": 51} for i in range(5)]
        save_state(
            session_summary="Dense session with many events",
            day=51,
            narrative_log="Session log",
            scene_location="Location"
        )

        # Calculate actual tokens (rough approximation: 1 token per 3.5 chars for dense text)
        cult_content = cult_path.read_text(encoding='utf-8')
        approx_tokens = len(cult_content) / 3.5  # Dense content ratio

        assert approx_tokens < 2000, f"File has ~{approx_tokens:.0f} tokens (should be <2000)"
        assert len(cult_content) < 7000, f"File has {len(cult_content)} chars (should be <7000 for safety margin)"
    finally:
        # Restore original file
        if backup is not None:
            cult_path.write_text(backup, encoding='utf-8')
        elif cult_path.exists():
            # If there was no backup, remove the test file
            cult_path.unlink()


def test_pattern_detection_avoids_false_positives(monkeypatch):
    """Verify pattern detection uses word boundaries to avoid false matches.

    Isolate from the real ~/.claude auto-memory: _review_cultivation also scans
    MEMORY.md for cultivation signals and appends it to the beat pool, and the
    dev's real memory can contain a trigger word ('broke'/'lied'/...). This is a
    unit test of the pattern logic, so it must control its own inputs.
    """
    monkeypatch.setattr("os.path.expanduser", lambda p: "/__rubicon_test_no_memory__")
    false_positive_beats = [
        "Party broke camp at dawn",
        "Creenash lied down to rest",
        "Found abandoned ruins in the wastes",
        "The embroidered tapestry depicted ancient battles",
    ]

    review = _review_cultivation(
        recent_beats=false_positive_beats,
        current_day=50,
        session_summary="Exploration session"
    )

    # None of these should trigger threat opportunities
    assert len(review["opportunities"]) == 0, f"False positives detected: {review['opportunities']}"


def test_pattern_detection_catches_real_threats():
    """Verify pattern detection catches actual threats."""
    real_threat_beats = [
        "Creenash broke his promise to Sahar",
        "Party lied to the Council about their findings",
        "Vela abandoned the wounded NPC at the vault entrance",
        "Haldib feels dismissed by the envoy's casual approach",
    ]

    review = _review_cultivation(
        recent_beats=real_threat_beats,
        current_day=50,
        session_summary="Consequences mounting"
    )

    # All four should trigger opportunities
    assert len(review["opportunities"]) >= 4, f"Only {len(review['opportunities'])} threats detected (expected 4)"

    # Verify specific patterns caught
    opps_text = " ".join(review["opportunities"]).lower()
    assert "broke" in opps_text or "promise" in opps_text
    assert "lied" in opps_text or "council" in opps_text
    assert "abandoned" in opps_text or "wounded" in opps_text
    assert "dismissed" in opps_text or "haldib" in opps_text


def test_save_cultivation_uses_temp_file():
    """Verify cultivation writes use temp file for atomicity."""
    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    tmp_path = cult_path.with_suffix('.md.tmp')

    # Clean up any existing temp file
    if tmp_path.exists():
        tmp_path.unlink()

    # Write some content
    _save_cultivation("# TEST CONTENT\n\nSome data here")

    # Temp file should NOT exist after successful write (already replaced)
    assert not tmp_path.exists(), "Temp file should be replaced, not left behind"

    # Main file should have the content
    content = cult_path.read_text(encoding='utf-8')
    assert "TEST CONTENT" in content


def test_save_cultivation_is_atomic():
    """Verify cultivation writes are atomic (no partial writes on crash)."""
    import unittest.mock as mock

    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    cult_path.write_text("Original content", encoding='utf-8')

    # Mock write_text on the TEMP path to simulate crash during write
    original_write = Path.write_text

    def mock_write_text(self, *args, **kwargs):
        if str(self).endswith('.tmp'):
            raise IOError("Simulated crash during temp write")
        return original_write(self, *args, **kwargs)

    with mock.patch('pathlib.Path.write_text', mock_write_text):
        try:
            _save_cultivation("New content that should not be written")
        except IOError:
            pass  # Expected to raise

    # Original content should be intact (atomic write failed safely)
    content = cult_path.read_text(encoding='utf-8')
    assert content == "Original content", f"File corrupted: {content[:50]}"


def test_save_cultivation_cleans_up_temp_file():
    """Verify temp files are cleaned up on failure."""
    import unittest.mock as mock

    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    tmp_path = cult_path.with_suffix('.md.tmp')

    # Clean up any existing temp file
    if tmp_path.exists():
        tmp_path.unlink()

    # Ensure main file exists
    cult_path.write_text("Original", encoding='utf-8')

    # Mock replace to simulate failure during atomic replace
    original_replace = Path.replace

    def mock_replace(self, target):
        if str(self).endswith('.tmp'):
            raise IOError("Replace failed")
        return original_replace(self, target)

    with mock.patch('pathlib.Path.replace', mock_replace):
        try:
            _save_cultivation("Test content")
        except IOError:
            pass  # Expected

    # Temp file should be cleaned up
    assert not tmp_path.exists(), "Temp file not cleaned up after failure"


def test_save_cultivation_retries_transient_permission_error(monkeypatch):
    """Regression: _save_cultivation must survive a TRANSIENT Windows file lock.

    The tmp->final rename can be briefly locked on Windows (AV scanner / search
    indexer / an unreleased handle), surfacing as PermissionError (WinError 5).
    This was the full-suite-only antagonist flake: a lost cultivation save read
    back as stale/missing seed state, so a randomly-ordered run occasionally
    failed a tick/briefing/trigger assertion that a rerun passed. The save now
    retries the rename a few times (shared _atomic_replace_with_retry) before
    giving up, instead of a bare .replace().
    """
    import pathlib

    cult_path = CAMPAIGN_DIR / "ANTAGONIST_CULTIVATION.md"
    real_replace = pathlib.Path.replace
    calls = {"n": 0}

    def flaky_replace(self, dst):
        if str(self).endswith(".tmp"):
            calls["n"] += 1
            if calls["n"] < 3:       # fail the first two attempts, then succeed
                raise PermissionError(13, "WinError 5 simulated: target locked")
        return real_replace(self, dst)

    monkeypatch.setattr(pathlib.Path, "replace", flaky_replace)
    _save_cultivation("# ANTAGONIST CULTIVATION\n\nretry probe\n")

    assert calls["n"] == 3                 # retried, didn't give up on the first lock
    assert "retry probe" in cult_path.read_text(encoding="utf-8")
    assert not cult_path.with_suffix(".md.tmp").exists()


def test_antagonist_view_shows_metrics():
    """TASK 15: Verify antagonist(action='view') prepends metrics."""
    from server import antagonist, _save_cultivation

    # Create cultivation file with known content
    test_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 60

---

## ACTIVE THREATS
*Things currently in motion, escalating*

### Haldib's Resentment - Escalation: MED
- Planted: Day 45
- Creenash dismissed Haldib's expertise

### Verdantis Sanctions - Escalation: HIGH
- Planted: Day 50
- Council noticed party's deception

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Salt Bones Feud - Day planted: 40
- Party stole from local synth gang

### Broken Promise to Sahar - Day planted: 35
- Creenash promised to help but never returned

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

Day 45: Haldib's Resentment escalated from dormant → med

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

    _save_cultivation(test_content)

    # Call antagonist view
    result = antagonist(action="view", day=60)

    # Should have metrics prepended
    assert "# ANTAGONIST CULTIVATION METRICS" in result
    assert "Active threats: 2" in result
    assert "Dormant seeds: 2" in result
    assert "Oldest seed:" in result
    assert "Broken Promise to Sahar" in result  # Oldest seed name
    assert "25 days old" in result  # 60 - 35 = 25
    assert "Token usage:" in result
    assert "/ 2000 tokens" in result
    assert "File size:" in result
    assert "/ 6500 chars" in result

    # Should still have original content after metrics
    assert "## ACTIVE THREATS" in result
    assert "Haldib's Resentment" in result


def test_antagonist_view_without_day_resolves_via_safe_helper():
    """Regression: antagonist() with no day must resolve it through get_current_day_safe(),
    not the retired get_current_day.fn() (which raised NameError — get_current_day no longer
    exists, it merged into sync_campaign_day). Real MCP passes day=None when the arg is omitted;
    every prior antagonist test passed day= explicitly and so never hit this branch. day=None
    forces the exact resolution path the live tool takes."""
    from server import antagonist, _save_cultivation

    _save_cultivation(
        "# ANTAGONIST CULTIVATION\n*DM-ONLY*\n\n## ACTIVE THREATS\n\n"
        "### Test Threat - Escalation: MED\n- Planted: Day 10\n\n## DORMANT SEEDS\n\n"
        "### Test Seed - Day planted: 5\n- placeholder\n"
    )

    # Pre-fix this raised NameError on get_current_day.fn(); post-fix it resolves day and returns.
    result = antagonist(action="view", day=None)

    assert isinstance(result, str)
    assert "ANTAGONIST CULTIVATION METRICS" in result


def test_antagonist_validate_passes_healthy_file():
    """TASK 15: Verify antagonist(action='validate') passes for healthy file."""
    from server import antagonist, _save_cultivation

    healthy_content = """# ANTAGONIST CULTIVATION
*DM-ONLY - NEVER SHOW PLAYER - TOP SECRET ULTRA-CLASSIFIED-10*

Last updated: Day 50

---

## ACTIVE THREATS
*Things currently in motion, escalating*

### Test Threat - Escalation: LOW
- Planted: Day 45
- Details here

---

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Test Seed - Day planted: 40
- Details here

---

## ESCALATION LOG
*Chronicle of how threats develop over time*

Day 45: Test Threat escalated from dormant → low

---

## OPPORTUNITIES
*Player mistakes, vulnerabilities, blind spots noticed THIS SESSION*

[None yet]

---

## PRUNING LOG
*Seeds removed after going nowhere for 20+ days*

[None yet]
"""

    _save_cultivation(healthy_content)

    result = antagonist(action="validate", day=50)

    # Should pass validation
    assert "VALIDATION PASSED" in result
    assert "File health: Good" in result
    assert "Active threats: 1" in result
    assert "Dormant seeds: 1" in result
    assert "All required sections present" in result
    assert "Day monotonicity validated" in result
