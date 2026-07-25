"""Smoke test for _check_in_dialogue_fabrication integration."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from hooks.consolidated_stop_check import _check_in_dialogue_fabrication


def _hook_input(tool_names=()):
    return {"transcript_messages": [{
        "role": "assistant",
        "content": [{"type": "tool_use", "name": n, "input": {}} for n in tool_names],
    }]}


def test_blocks_fabricated_duration():
    """Canon gate hardening §C.3 (2026-07-24): blocks when nothing was consulted.

    The old contract soft-logged unconditionally because "validate_prose is the
    primary gate" — untrue for any turn the DM never validates, which is how ten
    turns of invention reached the player on 2026-07-24.
    """
    state = {"session_type": "gameplay"}
    response = 'Amara leaned back. "I have known him seventy-nine days," she said.'
    blocked, reason, _ = _check_in_dialogue_fabrication(_hook_input(), state, response)
    from hooks.dialogue_claim_scanner import detect_claims_in_response
    assert detect_claims_in_response(response), "Scanner should still detect the claim"
    assert blocked is True
    assert "seventy-nine days" in reason


def test_stays_advisory_when_the_turn_consulted_canon():
    """A turn that DID check canon keeps the old soft-log behaviour."""
    state = {"session_type": "gameplay"}
    response = 'Amara leaned back. "I have known him seventy-nine days," she said.'
    blocked, _, _ = _check_in_dialogue_fabrication(
        _hook_input(["mcp__rubicon-seven__check_canon"]), state, response)
    assert blocked is False


def test_passes_neutral_dialogue():
    hook_input = {}
    state = {"session_type": "gameplay"}
    response = 'Amara leaned back. "The tea is cold," she said.'
    blocked, _, _ = _check_in_dialogue_fabrication(hook_input, state, response)
    assert not blocked


def test_passes_pure_narrative():
    hook_input = {}
    state = {"session_type": "gameplay"}
    response = "Amara leaned back. The cup cooled between them."
    blocked, _, _ = _check_in_dialogue_fabrication(hook_input, state, response)
    assert not blocked


def test_maintenance_bypass():
    hook_input = {}
    state = {"session_type": "gameplay", "skip_canon_enforcement": True}
    response = 'Amara said, "I lived with him for seventy-nine days."'
    blocked, _, _ = _check_in_dialogue_fabrication(hook_input, state, response)
    assert not blocked, "Maintenance bypass should suppress the check"


def test_passes_verified_dialogue_claim(tmp_path, monkeypatch):
    """A dialogue claim whose specifics are in the cache should pass."""
    from hooks.distillation_cache import DistillationCache

    # Build a temp cache with a fact that supports the dialogue claim
    cache_path = tmp_path / ".canon_distillations.json"
    cache = DistillationCache(cache_path)
    cache.put({
        "topic_key": "amara_event",
        "learning": "Amara has stood at his side for twenty years.",
        "key_facts": ["twenty years at his side"],
        "source_pointers": [],
        "verified_against": {"lorebook_mtime": 1, "npc_states_mtime": 1},
        "created_turn": 1, "created_session": "test",
        "refined_turn": 1, "refined_count": 1,
        "ingested_at_session": None,
    })

    # Patch the module-level cache path constant
    import hooks.consolidated_stop_check as cs
    monkeypatch.setattr(cs, "_DEFAULT_CACHE_PATH", cache_path)

    hook_input = {}
    state = {"session_type": "gameplay"}
    response = 'Amara leaned back. "I have been with him for twenty years," she said.'
    blocked, reason, _ = _check_in_dialogue_fabrication(hook_input, state, response)
    assert not blocked, f"Should pass when cache covers the claim. Got: {reason}"
