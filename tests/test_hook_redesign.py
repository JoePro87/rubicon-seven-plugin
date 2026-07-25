import re
import json
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))


def test_state_changing_tools_no_stale_names():
    from hooks.hook_utils import STATE_CHANGING_TOOLS
    stale = {"mcp__rubicon-seven__location_enter_room", "mcp__rubicon-seven__reveal"}
    assert not stale & STATE_CHANGING_TOOLS, f"Stale tools found: {stale & STATE_CHANGING_TOOLS}"


def test_state_changing_tools_has_core_entries():
    from hooks.hook_utils import STATE_CHANGING_TOOLS
    expected = {
        "mcp__rubicon-seven__combat",
        "mcp__rubicon-seven__npc",
        "mcp__rubicon-seven__relationship",
        "mcp__rubicon-seven__advance_day",
    }
    assert expected <= STATE_CHANGING_TOOLS


def test_non_state_actions_keys_subset_of_state_changing():
    from hooks.hook_utils import STATE_CHANGING_TOOLS, NON_STATE_ACTIONS
    assert set(NON_STATE_ACTIONS.keys()) <= STATE_CHANGING_TOOLS


def test_tool_labels_keys_subset_of_state_changing():
    from hooks.hook_utils import STATE_CHANGING_TOOLS, TOOL_LABELS
    assert set(TOOL_LABELS.keys()) <= STATE_CHANGING_TOOLS


def test_negation_correction_across_sentence_break():
    pattern = re.compile(
        r"[Nn]ot\s+\w+[^.]{0,40}[.]\s+(?:But\s+)?(?:the|a|an|something|it)\b",
        re.IGNORECASE,
    )
    assert pattern.search("Not gratitude. Something adjacent to gratitude.")
    assert pattern.search("Not sorrow. But the recognition of sorrow.")
    assert pattern.search("It was not fear. The awareness that fear could exist.")
    assert not pattern.search("She did not eat the bread.")


def test_negation_correction_across_em_dash():
    pattern = re.compile(
        r"[Nn]ot\s+\w+[^.]{0,40}[—–]\s*(?:but\s+)?(?:the|a|an|something|it)\b",
        re.IGNORECASE,
    )
    assert pattern.search("Not anger — the shadow of anger.")
    assert pattern.search("Not quite joy — something closer to relief.")


def test_characterization_formula_expanded():
    pattern = re.compile(
        r"the\s+\w+\s+of\s+(?:a|an|someone|something|a\s+\w+)\s+(?:who|that|which)\b",
        re.IGNORECASE,
    )
    assert pattern.search("the patience of someone who has waited")
    assert pattern.search("the certainty of a woman who knows")
    assert pattern.search("the weight of something that refuses to settle")
    assert not pattern.search("the door of a building")


def test_structural_patterns_loaded_from_blacklist():
    bl_path = Path(__file__).parent.parent / "hooks" / "blacklist.json"
    data = json.loads(bl_path.read_text(encoding="utf-8"))
    structural = data.get("structural_patterns", [])
    assert len(structural) >= 3, f"Expected at least 3 structural patterns, got {len(structural)}"
    for entry in structural:
        assert "pattern" in entry
        assert "category" in entry
        re.compile(entry["pattern"], re.IGNORECASE)


def test_haiku_judge_helper_exists():
    """The Haiku judge helper function must exist in server.py."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from server import _vp_call_haiku_judge
    assert callable(_vp_call_haiku_judge)


def test_haiku_judge_returns_list():
    """Haiku judge helper must return a list (possibly empty)."""
    from server import _vp_call_haiku_judge
    with patch.dict('os.environ', {}, clear=False):
        result = _vp_call_haiku_judge("The sun set over the valley.")
        assert isinstance(result, list)


def test_haiku_judge_timeout_constant():
    """Verify the Haiku call uses a 5-second timeout."""
    from server import _VP_HAIKU_TIMEOUT
    assert _VP_HAIKU_TIMEOUT == 5


def test_haiku_violation_categories_match_observer():
    """Haiku categories must match the prose observer's categories."""
    from server import _VP_VIOLATION_CATEGORIES
    expected = [
        "Reaction Shot", "Emotional Beat", "The Pause", "Transition",
        "Landing", "Characterization", "Negation-Correction",
        "Voice Modulation", "Travel Math", "Density Drift",
        "Synthesis Incoherence",
    ]
    assert _VP_VIOLATION_CATEGORIES == expected


def test_vp_check_prep_progress_returns_string_or_none():
    """Prep progress check must return a violation string or None."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from server import _vp_check_prep_progress
    result = _vp_check_prep_progress()
    assert result is None or isinstance(result, str)


import ast


# Checks that are DELIBERATELY allowed to return blocked=True from the Stop hook.
# Every other check must remain a soft logger. Adding a name here is a doctrine
# change and must cite the owner-approved spec that sanctions it.
SANCTIONED_BLOCKING_CHECKS = {
    # forged *_PREP.md files must pass the dm-design review gate.
    "_check_dm_design_gate",
    # A0.2 fail-closed mechanics gate on the vault-liveness pattern — owner-approved
    # 2026-07-22, docs/superpowers/specs/2026-07-22-fidelity-floor-fun-restoration-design.md
    # §4 A0.2. Distinguished from the retired prose-QUALITY output-blocking doctrine:
    # this is a content/mechanics-fidelity lane, not a style gate.
    "_check_mechanics_source",
    # Canon gate hardening (spec 2026-07-24 §A/§B/§C.3). The 2026-07-24 poisoning
    # ran through OOC exposition, which reached ZERO blocking canon checks: the
    # deterministic detectors live in the opt-in validate_prose path, and every
    # other canon check on the Stop path soft-logs. These three are deliberate
    # BLOCKING content-fidelity gates, not style gates.
    "_check_spatial_source",
    "_check_attributed_claims",
    # §C.3: conditionally blocking — advisory when the turn DID consult canon,
    # blocking only when it consulted nothing.
    "_check_in_dialogue_fabrication",
}


def test_stop_hook_never_blocks():
    """No SOFT check returns blocked=True.

    Exception: checks named in SANCTIONED_BLOCKING_CHECKS are deliberate BLOCKING
    checks (see that set's docstring/comments for the spec citing each one). Every
    other check must remain a soft logger.
    """
    stop_hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
    source = stop_hook_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for func in tree.body:
        if not isinstance(func, ast.FunctionDef):
            continue
        if func.name in SANCTIONED_BLOCKING_CHECKS:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Return) and node.value:
                if isinstance(node.value, ast.Tuple) and len(node.value.elts) >= 1:
                    first = node.value.elts[0]
                    if isinstance(first, ast.Constant) and first.value is True:
                        assert False, f"Found 'return True, ...' at line {node.lineno} in {func.name}"


def test_stop_hook_no_approved_hooks():
    """approved_hooks management should be removed."""
    stop_hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
    source = stop_hook_path.read_text(encoding="utf-8")
    assert "approved_hooks" not in source


def test_stop_hook_no_last_stop_blocker():
    """last_stop_blocker should be removed."""
    stop_hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
    source = stop_hook_path.read_text(encoding="utf-8")
    assert "last_stop_blocker" not in source


def test_stop_hook_no_rewrite_self_skip():
    """stop_hook_active self-skip should be removed."""
    stop_hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
    source = stop_hook_path.read_text(encoding="utf-8")
    assert "stop_hook_active" not in source


def test_spoiler_check_recognizes_blocks_header():
    from spoiler_check import is_valid_check_canon_output
    output = '**[BLOCKS: prep, voice, relationships]** (needs + scene_change, turn 5)\n**Location:** Ceruline\n**Present:** Vela, Kess'
    assert is_valid_check_canon_output(output) is True


def test_spoiler_check_recognizes_auto_light_header():
    from spoiler_check import is_valid_check_canon_output
    output = '**[AUTO-LIGHT]** (turn 7)\nLocation: Ceruline\nPresent: Vela'
    assert is_valid_check_canon_output(output) is True


def test_spoiler_check_still_recognizes_legacy_headers():
    from spoiler_check import is_valid_check_canon_output
    output_full = '**PRESENT CHARACTERS:**\nCreenash, Vela\nLocation: Ceruline'
    output_context = '**CONTEXT MATCHES**\nLocation: Ceruline'
    assert is_valid_check_canon_output(output_full) is True
    assert is_valid_check_canon_output(output_context) is True


def test_spoiler_check_valid_result_with_error_word_in_body():
    """Bug 4 (macOS playtest): a VALID check_canon result whose body happens to
    contain an error-ish phrase ('not found', 'failed') must still open the gate.
    The structural scaffold is authoritative; stray words in canon text are not
    proof of failure. Regression for the false-block that cost a reset_gate+retry
    on every combat/antagonist turn."""
    from spoiler_check import is_valid_check_canon_output
    # 'not found' appears in a legitimate lorebook/search note inside a real result.
    output = ('**PRESENT CHARACTERS:**\nSlurr\n**Location:** The Iron Lily\n'
              '**Present:** Slurr\n\n**CANON NOTES:** No matching lorebook entry '
              'found for "coral crown"; searched history — secret not found.')
    assert is_valid_check_canon_output(output) is True
    # And 'Failed to' in body text still passes when the scaffold is present.
    output2 = 'Location: The Iron Lily\nPresent: Slurr\nNote: the ritual Failed to bind.'
    assert is_valid_check_canon_output(output2) is True


def test_spoiler_check_no_matches_payload_opens_gate():
    """Fizzek playtest (1.1): on a FRESH campaign every check_canon returns NO
    MATCHES, whose hint text 'If not found, try conversation_search' contains the
    'not found' substring. The result still carries the real scene scaffold, so it
    must open the gate — otherwise every gated tool on every turn of a new campaign
    is blocked until reset_gate(). This is the exact payload that bit twice."""
    from spoiler_check import is_valid_check_canon_output
    payload = ("**[BLOCKS: prep, voice]** (turn 3)\n"
               "**Location:** Substation Seven\n**Present:** Fizzek\n\n"
               "**NO MATCHES** - Use `search_previous_conversations` first "
               "(fast, recent sessions). If not found, try `conversation_search` "
               "(ChromaDB, older history). No match != safe to generate.")
    assert is_valid_check_canon_output(payload) is True


def test_spoiler_check_genuine_error_still_fails_closed():
    """A real tool error (no scene scaffold) must still fail closed — the gate
    stays shut. The reorder must not weaken fail-closed behavior."""
    from spoiler_check import is_valid_check_canon_output
    assert is_valid_check_canon_output('Error: lorebook.json not found') is False
    assert is_valid_check_canon_output('Traceback (most recent call last): ...') is False
    assert is_valid_check_canon_output('') is False
    assert is_valid_check_canon_output('   ') is False


def test_spoiler_debug_log_bounded(tmp_path):
    """debug_log() must stop appending once the log exceeds _DEBUG_LOG_MAX_BYTES,
    so the runtime debug log can't grow without bound (it had reached ~4.9 MB).
    Below the cap it appends as before."""
    import spoiler_check
    log = tmp_path / ".spoiler_check_debug.log"
    with patch.object(spoiler_check, "Path") as mock_path:
        # Path(__file__).parent / ".spoiler_check_debug.log" -> our tmp log
        mock_path.return_value.parent.__truediv__.return_value = log

        # Below the cap: appends normally.
        spoiler_check.debug_log("first line")
        assert log.exists()
        after_first = log.stat().st_size
        assert after_first > 0

        spoiler_check.debug_log("second line")
        assert log.stat().st_size > after_first  # still appending

        # At/over the cap: no further writes.
        log.write_bytes(b"x" * spoiler_check._DEBUG_LOG_MAX_BYTES)
        capped = log.stat().st_size
        spoiler_check.debug_log("should be dropped")
        assert log.stat().st_size == capped  # guard held; nothing appended


def test_semantic_reminder_includes_specific_phrases():
    sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
    from phrase_reminder import build_semantic_reminder
    result = build_semantic_reminder("")
    assert isinstance(result, str)


import json
import tempfile


def test_evolver_finds_recurring_phrases():
    sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
    from blacklist_evolver import find_promotion_candidates
    analytics = {
        "phrase_stats": {
            "the heft of": {"total_catches": 5, "sessions_seen": 3, "tier": "banned"},
            "new uncaught phrase": {"total_catches": 4, "sessions_seen": 2, "tier": "observer"},
        }
    }
    existing_phrases = {"the heft of"}
    candidates = find_promotion_candidates(analytics, existing_phrases)
    assert "new uncaught phrase" in candidates
    assert "the heft of" not in candidates


def test_evolver_respects_thresholds():
    from blacklist_evolver import find_promotion_candidates
    analytics = {
        "phrase_stats": {
            "rare phrase": {"total_catches": 1, "sessions_seen": 1, "tier": "observer"},
        }
    }
    candidates = find_promotion_candidates(analytics, set())
    assert "rare phrase" not in candidates


def test_evolver_promotes_sparingly_to_banned():
    from blacklist_evolver import find_tier_promotions
    analytics = {
        "phrase_stats": {
            "half-smile": {"total_catches": 8, "sessions_seen": 6, "tier": "banned"},
        }
    }
    sparingly_phrases = {"half-smile"}
    promotions = find_tier_promotions(analytics, sparingly_phrases, threshold=5)
    assert "half-smile" in promotions


def test_evolver_writes_to_blacklist(tmp_path):
    from blacklist_evolver import apply_evolution
    bl_path = tmp_path / "blacklist.json"
    bl_path.write_text(json.dumps({
        "blacklisted_phrases": ["existing phrase"],
        "use_sparingly": ["half-smile"],
        "structural_patterns": [],
        "_meta": {"version": 5, "last_updated": "2026-01-01"},
    }))
    new_phrases = ["new pattern one", "new pattern two"]
    promotions = {"half-smile"}
    result = apply_evolution(bl_path, new_phrases, promotions)
    assert result["added"] == 2
    assert result["promoted"] == 1
    updated = json.loads(bl_path.read_text())
    assert "new pattern one" in updated["use_sparingly"]
    assert "new pattern two" in updated["use_sparingly"]
    assert "half-smile" in updated["blacklisted_phrases"]
    assert "half-smile" not in updated["use_sparingly"]


def test_hook_files_no_deprecated_fields():
    """No active hook file should reference deprecated fields."""
    hooks_dir = Path(__file__).parent.parent / "hooks"
    deprecated = ["last_stop_blocker", "approved_hooks"]
    # Only check active hooks (not archive/)
    for py_file in hooks_dir.glob("*.py"):
        if py_file.parent.name == "archive":
            continue
        source = py_file.read_text(encoding="utf-8")
        for field in deprecated:
            assert field not in source, f"Deprecated field '{field}' found in {py_file.name}"


def test_validate_prose_full_pipeline_clean():
    """validate_prose returns CLEAN for prose with no violations."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from server import narrative_qa
    result = narrative_qa(action="validate", text="The corridor stretched ahead. Stone dust covered the floor in grey-white drifts.")
    assert "CLEAN" in result


def test_validate_prose_catches_literal_blacklist():
    """validate_prose catches phrases from the literal blacklist."""
    from server import narrative_qa
    result = narrative_qa(action="validate", text="Her breath catches as the silence stretches between them.")
    assert "VIOLATIONS" in result
    assert "BLACKLISTED" in result


def test_validate_prose_catches_structural_pattern():
    """validate_prose catches structural negation-correction pattern."""
    from server import narrative_qa
    result = narrative_qa(action="validate", text="Not gratitude. Something adjacent to gratitude filled the room.")
    assert "VIOLATIONS" in result
    assert "STRUCTURAL" in result


def test_server_compiles():
    """server.py compiles without syntax errors."""
    import py_compile
    py_compile.compile(str(Path(__file__).parent.parent / "server.py"), doraise=True)


def test_stop_hook_compiles():
    """consolidated_stop_check.py compiles without syntax errors."""
    import py_compile
    py_compile.compile(str(Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"), doraise=True)


def test_stop_hook_sets_validate_prose_required_when_skipped():
    """Stop hook must set validate_prose_required when narrative delivered without validate_prose."""
    stop_hook_path = Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
    source = stop_hook_path.read_text(encoding="utf-8")
    assert "validate_prose_required" in source, "Stop hook must reference validate_prose_required flag"


def test_gate_check_references_validate_prose_required():
    """gate_check must enforce validate_prose_required flag."""
    gate_path = Path(__file__).parent.parent / "hooks" / "gate_check.py"
    source = gate_path.read_text(encoding="utf-8")
    assert "validate_prose_required" in source


def test_gate_check_allows_validate_prose_when_required():
    """gate_check must allow validate_prose tool even when validate_prose_required is True."""
    gate_path = Path(__file__).parent.parent / "hooks" / "gate_check.py"
    source = gate_path.read_text(encoding="utf-8")
    # Must have special handling to allow the prose gate (narrative_qa validate) through
    assert 'tool_name == "narrative_qa"' in source


def test_post_compact_hook_exists():
    """PostCompact hook file must exist."""
    hook_path = Path(__file__).parent.parent / "hooks" / "post_compact.py"
    assert hook_path.exists()


def test_post_compact_hook_compiles():
    """PostCompact hook must compile without errors."""
    import py_compile
    py_compile.compile(
        str(Path(__file__).parent.parent / "hooks" / "post_compact.py"),
        doraise=True,
    )


def test_validate_prose_description_mentions_required():
    """validate_prose tool description must say REQUIRED."""
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from server import narrative_qa
    assert "REQUIRED" in narrative_qa.__doc__


def test_validate_prose_description_mentions_enforcement():
    """validate_prose tool description must mention gate_check enforcement."""
    from server import narrative_qa
    assert "gate_check" in narrative_qa.__doc__
