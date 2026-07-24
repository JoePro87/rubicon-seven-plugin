"""Tests for context injection optimization (2026-03-08 design)."""

import re
import pytest


class TestBeatsRegexDedup:
    """Task 1: Verify beats regex doesn't capture subsequent field headers."""

    SAMPLE_STATUS = """**Last 3 Beats:**
1. Intimate scene in progress — Creenash pleasuring Vela in rooftop garden
2. Rain from microclimate, Polly roosting in canopy above
3. Session ended mid-foreplay before rook formation
**Last Speaker:** Creenash
**Tension/Mood:** Post-revelation intimacy
**Next Expected:** Complete intimate scene"""

    def test_beats_regex_stops_at_field_headers(self):
        """Beats regex must NOT capture lines starting with **field:**."""
        pattern = r'\*\*Last 3 Beats:\*\*\s*\n((?:\d+\.\s*(?:(?!\*\*).)+(?:\n|$))*)'
        match = re.search(pattern, self.SAMPLE_STATUS)
        assert match is not None
        beats_text = match.group(1)
        assert "Intimate scene" in beats_text
        assert "Rain from microclimate" in beats_text
        assert "Session ended" in beats_text
        assert "Last Speaker" not in beats_text
        assert "Tension/Mood" not in beats_text
        assert "Next Expected" not in beats_text

    def test_beats_regex_handles_no_blank_line_separator(self):
        """Beats are followed immediately by field headers with no blank line."""
        status_no_gap = """**Last 3 Beats:**
1. Beat one text here
**Last Speaker:** Someone"""
        pattern = r'\*\*Last 3 Beats:\*\*\s*\n((?:\d+\.\s*(?:(?!\*\*).)+(?:\n|$))*)'
        match = re.search(pattern, status_no_gap)
        assert match is not None
        beats_text = match.group(1)
        assert "Beat one" in beats_text
        assert "Last Speaker" not in beats_text

    def test_beats_post_processing_strips_field_headers(self):
        """Safety guard: strip any lines starting with ** from beats text."""
        raw_beats = "1. Some beat\n**Last Speaker:** Oops\n2. Another beat\n"
        cleaned = "\n".join(
            line for line in raw_beats.split("\n")
            if not re.match(r'\*\*[A-Z]', line)
        )
        assert "Last Speaker" not in cleaned
        assert "Some beat" in cleaned
        assert "Another beat" in cleaned


class TestFullSessionStartupIntegration:
    """Task 2: Verify startup output excludes redundant sections."""

    def test_startup_source_excludes_voice_guide(self):
        """The full_session_startup function must not load VOICE.md."""
        import re
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')

        # Find full_session_startup function body
        func_start = source.find('def full_session_startup(')
        assert func_start != -1, "full_session_startup function not found"

        # Find next top-level def after it
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]

        # Must NOT contain voice guide loading
        assert 'load_voice_guide_for' not in func_body, "full_session_startup still loads voice guide"
        # Must NOT contain relationship lexicon loading
        assert 'RELATIONSHIP_LEXICON' not in func_body, "full_session_startup still loads relationship lexicon"
        # Must NOT contain tripwires loading
        assert 'CONTINUITY_CORRECTIONS_LOG' not in func_body, "full_session_startup still loads tripwires"

    def test_startup_source_contains_skip_note(self):
        """The function must contain the efficiency skip note."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')

        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]

        assert 'skipped' in func_body.lower() or 'Loaded via' in func_body or 'DEFERRED' in func_body, \
            "full_session_startup missing skip/deferred note"

    def test_startup_source_excludes_scene_state_extraction(self):
        """Scene state is provided by check_canon; startup should not extract it."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert '=== SCENE STATE ===' not in func_body, "full_session_startup still emits SCENE STATE"

    def test_startup_source_excludes_arc_context(self):
        """Arc context is included in check_canon's scene state block."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert '=== ARC CONTEXT ===' not in func_body, "full_session_startup still emits ARC CONTEXT"

    def test_startup_source_excludes_emotional_state(self):
        """Emotional state is included in check_canon's scene state block."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert '=== EMOTIONAL STATE ===' not in func_body, "full_session_startup still emits EMOTIONAL STATE"

    def test_startup_source_excludes_vector_search(self):
        """Vector search is run by check_canon with better parameters."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert '=== RELEVANT HISTORY ===' not in func_body, "full_session_startup still emits RELEVANT HISTORY"
        assert 'get_chroma_collection' not in func_body, "full_session_startup still queries ChromaDB"

    def test_startup_source_excludes_knowledge_boundaries(self):
        """Knowledge boundaries are loaded by check_canon per-turn."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert '=== KNOWLEDGE BOUNDARIES' not in func_body, "full_session_startup still emits KNOWLEDGE BOUNDARIES"

    def test_startup_contains_deferred_note(self):
        """Startup must document what was deferred and why."""
        from pathlib import Path
        server_path = Path(__file__).parent.parent / "session_tools.py"  # Wave 8: full_session_startup moved here
        source = server_path.read_text(encoding='utf-8')
        func_start = source.find('def full_session_startup(')
        next_def = source.find('\ndef ', func_start + 1)
        func_body = source[func_start:next_def] if next_def != -1 else source[func_start:]
        assert 'DEFERRED' in func_body, "full_session_startup missing DEFERRED note"


class TestLorebookEntryCap:
    """Task 3: Verify lorebook entries are smart-truncated in check_canon."""

    LONG_ENTRY = {
        "keywords": ["polly"],
        "category": "companion",
        "context": "Polly is a synthetic rook (Corvus sinteticus) bonded to Creenash via quantum resonance. " * 20,
        "short_context": "Synthetic rook bonded to Creenash. Female. Roosts in canopy.",
        "status": "active",
        "pronouns": "she/her",
        "species": "synthetic rook",
    }

    SHORT_ENTRY = {
        "keywords": ["tessik well"],
        "category": "location",
        "context": "Small settlement in the blue desert.",
        "short_context": "Small settlement.",
        "status": "active",
    }

    def test_smart_truncate_extracts_identity_fields(self):
        """Truncated entry must lead with pronouns, species."""
        from server import _smart_truncate_lorebook_entry
        result = _smart_truncate_lorebook_entry(self.LONG_ENTRY, max_chars=300)
        assert "she/her" in result
        assert "synthetic rook" in result
        assert len(result) <= 350  # 300 + suffix allowance

    def test_smart_truncate_preserves_short_entries(self):
        """Entries under max_chars prefer short_context when available."""
        from server import _smart_truncate_lorebook_entry
        result = _smart_truncate_lorebook_entry(self.SHORT_ENTRY, max_chars=300)
        # No identity fields, so returns base text (short_context preferred)
        assert result == self.SHORT_ENTRY["short_context"]

    def test_smart_truncate_appends_fetch_hint(self):
        """Truncated entries must include a hint to fetch full entry."""
        from server import _smart_truncate_lorebook_entry
        # Use an entry whose short_context exceeds max_chars so truncation kicks in
        entry = {**self.LONG_ENTRY, "short_context": "Y " * 200}
        result = _smart_truncate_lorebook_entry(entry, max_chars=300)
        assert "lorebook" in result.lower()

    def test_smart_truncate_handles_missing_identity_fields(self):
        """Entries without pronouns/species still truncate cleanly."""
        entry = {"keywords": ["some place"], "category": "location",
                 "context": "A very long description. " * 30, "status": "active"}
        from server import _smart_truncate_lorebook_entry
        result = _smart_truncate_lorebook_entry(entry, max_chars=300)
        assert len(result) <= 350

    def test_prefers_short_context_when_available(self):
        """When short_context exists and fits, use it instead of truncating context."""
        from server import _smart_truncate_lorebook_entry
        entry = {
            "keywords": ["mneme"], "category": "people",
            "pronouns": "she/her", "species": "pre-collapse consciousness",
            "context": "Very long context. " * 50,
            "short_context": "Pre-Collapse consciousness, co-architect of Ceruline.",
            "status": "ESTABLISHED",
        }
        result = _smart_truncate_lorebook_entry(entry, max_chars=500)
        assert "Pre-Collapse consciousness, co-architect" in result
        assert "[she/her" in result
        assert "Very long context" not in result

    def test_falls_back_to_context_when_no_short(self):
        """When short_context is missing, truncate context as before."""
        from server import _smart_truncate_lorebook_entry
        entry = {
            "keywords": ["someone"], "category": "people",
            "pronouns": "he/him",
            "context": "Someone (he/him). A very long description. " * 30,
            "status": "ESTABLISHED",
        }
        result = _smart_truncate_lorebook_entry(entry, max_chars=500)
        assert "Someone" in result
        assert "[he/him" in result
        assert len(result) <= 550

    def test_identity_prefix_from_structured_fields(self):
        """New pronouns/species fields produce identity prefix."""
        from server import _smart_truncate_lorebook_entry
        entry = {
            "keywords": ["saphora"], "category": "people",
            "pronouns": "she/her", "species": "cacogen",
            "context": "Saphora. Cacogen mechanic. " * 30,
            "short_context": "Cacogen mechanic, chosen sister to Creenash.",
            "status": "CANONICAL",
        }
        result = _smart_truncate_lorebook_entry(entry, max_chars=500)
        assert "[she/her, cacogen]" in result

    def test_short_context_over_cap_still_truncates(self):
        """If short_context itself exceeds cap, truncate it."""
        from server import _smart_truncate_lorebook_entry
        entry = {
            "keywords": ["verbose"], "category": "people",
            "context": "X" * 1000,
            "short_context": "Y " * 300,
            "status": "ESTABLISHED",
        }
        result = _smart_truncate_lorebook_entry(entry, max_chars=500)
        assert len(result) <= 550


class TestConsolidatedStopHook:
    """Task 5: Verify consolidated hook exists and covers all four checks."""

    def test_consolidated_hook_exists(self):
        """consolidated_stop_check.py must exist."""
        from pathlib import Path
        hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
        assert hook_path.exists()

    def test_consolidated_hook_covers_all_checks(self):
        """Must reference all four check domains."""
        from pathlib import Path
        hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
        source = hook_path.read_text(encoding="utf-8")
        assert "canon" in source.lower(), "Missing canon enforcement check"
        assert "pattern" in source.lower() or "blacklist" in source.lower(), "Missing anti-pattern check"
        assert "prep" in source.lower(), "Missing prep file check"
        assert "backstory" in source.lower() or "creenash" in source.lower(), "Missing backstory check"

    def test_consolidated_hook_has_short_circuit(self):
        """Must exit on first block, not run remaining checks."""
        from pathlib import Path
        hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
        source = hook_path.read_text(encoding="utf-8")
        assert "sys.exit" in source

    def test_settings_json_has_one_stop_hook(self):
        """settings.json Stop section must have exactly one matcher entry."""
        import json
        from pathlib import Path
        settings_path = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign" / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        stop_hooks = settings.get("hooks", {}).get("Stop", [])
        assert len(stop_hooks) == 1, f"Expected 1 Stop hook entry, got {len(stop_hooks)}"
        hook_cmd = stop_hooks[0]["hooks"][0]["command"]
        assert "consolidated_stop_check" in hook_cmd


class TestAdaptivePhraseReminder:
    """Task 6: Verify phrase_reminder scales output with catch count."""

    def test_clean_session_short_output(self):
        """0 catches = one-line reminder, under 150 chars."""
        import sys
        from pathlib import Path
        hooks_dir = str(Path(__file__).parent.parent / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from phrase_reminder import build_reminder
        result = build_reminder(
            catch_count=0, catch_log={},
            blacklisted=["pattern1", "pattern2"], sparingly=["word1"],
            session_vocab=[], scene_type="settlement"
        )
        # Clean-session output is a single concise line: scene hint + ~130-char
        # lorebook nudge + a compact one-line BANNED FAMILIES marker (the banned
        # prime now renders at every tier, not Tier-3-only). Lands ~350 chars.
        # Threshold guards against the full glossed banned dump (Tier 3 only).
        assert len(result) < 400, f"Clean session output too long: {len(result)} chars"
        assert "clean" in result.lower()
        assert "BANNED PATTERNS:" not in result

    def test_low_catches_medium_output(self):
        """1-5 catches = medium output with offenders, no BANNED PATTERNS."""
        import sys
        from pathlib import Path
        hooks_dir = str(Path(__file__).parent.parent / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from phrase_reminder import build_reminder
        result = build_reminder(
            catch_count=3, catch_log={"bad phrase": 2, "worse phrase": 1},
            blacklisted=["pattern1"], sparingly=[],
            session_vocab=[], scene_type="intimate"
        )
        # Tier-2 output lists session offenders, a scene line, the lorebook
        # nudge, and a compact one-line BANNED FAMILIES marker (names only, not
        # the full glossed dump), landing ~640 chars. Threshold raised; the
        # structural intent (offenders shown, no full banned-pattern dump) still
        # holds — "BANNED PATTERNS:" is Tier-3-only and asserted absent below.
        assert len(result) < 760, f"Medium output too long: {len(result)} chars"
        assert "SESSION OFFENDERS:" in result
        assert "bad phrase" in result
        assert "BANNED PATTERNS:" not in result

    def test_high_catches_full_output(self):
        """6+ catches = full output including BANNED PATTERNS."""
        import sys
        from pathlib import Path
        hooks_dir = str(Path(__file__).parent.parent / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        from phrase_reminder import build_reminder
        result = build_reminder(
            catch_count=8, catch_log={"phrase": 8},
            blacklisted=["pattern1"], sparingly=[],
            session_vocab=["used1"], scene_type="intimate"
        )
        assert "BANNED PATTERNS:" in result
        assert len(result) > 400
