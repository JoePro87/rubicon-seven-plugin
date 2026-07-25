"""End-to-end smoke tests — definition of done for Phase 1 of check_canon redesign.

These tests cover the four scenarios listed in the spec under "Smoke tests
(definition of done for Phase 1)".
"""

import json
import session_tools
from pathlib import Path
from unittest.mock import MagicMock


# ------------------------------------------------------------------
# Smoke 1: Pure environmental prose passes without check_canon.
# ------------------------------------------------------------------

def test_smoke_1_pure_environmental_prose_passes():
    """Pure environmental description triggers no risk markers in the Stop hook."""
    from hooks.consolidated_stop_check import _check_in_dialogue_fabrication

    response = "Afternoon light fills the kitchen. The cup sits cooling between them."
    state = {"session_type": "gameplay"}
    blocked, reason, _ = _check_in_dialogue_fabrication({}, state, response)
    assert not blocked, f"Should not block pure environmental prose: {reason}"


# ------------------------------------------------------------------
# Smoke 2: NPC dialogue with a fabricated duration blocks.
# ------------------------------------------------------------------

def test_smoke_2_fabricated_duration_blocks():
    """A fabricated 'seventy-nine days' claim in dialogue must be blocked.

    No cache is provided, so the claim is unverified. The default cache path
    is used — if it's empty or missing, the claim has no backing.
    Uses monkeypatch to redirect the cache to an empty tmp file, ensuring
    the test is hermetic regardless of what's in the real cache.
    """
    import hooks.consolidated_stop_check as cs
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        cache_path = Path(td) / ".canon_distillations.json"
        # Empty cache — write valid schema but no entries
        cache_path.write_text(json.dumps({"schema_version": 1, "distillations": {}}))

        original_path = cs._DEFAULT_CACHE_PATH
        cs._DEFAULT_CACHE_PATH = cache_path
        try:
            response = 'Amara leaned back. "I have known him seventy-nine days," she said.'
            state = {"session_type": "gameplay"}
            blocked, reason, _ = cs._check_in_dialogue_fabrication({}, state, response)
        finally:
            cs._DEFAULT_CACHE_PATH = original_path

    # Canon gate hardening §C.3 (2026-07-24): this check used to soft-log
    # unconditionally on the rationale that "validate_prose is the primary gate".
    # That is false for any turn the DM never routes through validate_prose.
    # Now: a turn that consulted NO canon tool blocks; a turn that did stays
    # advisory. This hook_input carries no tool calls, so it blocks.
    from hooks.dialogue_claim_scanner import detect_claims_in_response
    claims = detect_claims_in_response(response)
    assert claims, "Scanner should still detect the fabricated duration claim"
    assert any("duration" in t for t, _ in claims)
    assert blocked is True
    assert "seventy-nine days" in reason


# ------------------------------------------------------------------
# Smoke 3: Same NPC dialogue with a verified fact passes.
# ------------------------------------------------------------------

def test_smoke_3_verified_dialogue_passes(tmp_path, monkeypatch):
    """When the cache contains a fact supporting the dialogue claim, it passes.

    The dialogue says "twenty years old" (matched claim_text = "twenty years").
    The cache entry has "twenty years at his side" in key_facts, which contains
    "twenty years", satisfying the substring check in _check_in_dialogue_fabrication.
    """
    import hooks.consolidated_stop_check as cs
    from hooks.distillation_cache import DistillationCache

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

    # Patch the module-level cache path constant — same pattern as
    # test_in_dialogue_check_integration.py::test_passes_verified_dialogue_claim
    monkeypatch.setattr(cs, "_DEFAULT_CACHE_PATH", cache_path)

    # "twenty years old" → scanner extracts claim_text = "twenty years"
    # cache key_facts blob contains "twenty years at his side" → substring match → pass
    response = 'Amara leaned back. "I have been at his side since I was twenty years old," she said.'
    state = {"session_type": "gameplay"}
    blocked, reason, _ = cs._check_in_dialogue_fabrication({}, state, response)
    assert not blocked, f"Should pass when cache covers the claim. Blocked because: {reason}"


# ------------------------------------------------------------------
# Smoke 4: The feedback loop closes at session-end.
# ------------------------------------------------------------------

def test_smoke_4_feedback_loop_closes(tmp_path, monkeypatch):
    """ingest_distillations() embeds and ingests unposted entries into ChromaDB."""
    from hooks.distillation_cache import DistillationCache
    import server

    cache_path = tmp_path / ".canon_distillations.json"
    cache = DistillationCache(cache_path)
    for i in range(3):
        cache.put({
            "topic_key": f"test_topic_{i}_event",
            "learning": f"Synthesized learning number {i}.",
            "key_facts": [f"fact {i}"],
            "source_pointers": [],
            "verified_against": {"lorebook_mtime": 1, "npc_states_mtime": 1},
            "created_turn": i, "created_session": "test-session",
            "refined_turn": i, "refined_count": 1,
            "ingested_at_session": None,
        })

    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    mock_coll = MagicMock()
    mock_coll.upsert = MagicMock(return_value=None)
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin
    # Real contract: ingest_distillations BATCH-embeds via get_ollama_embeddings_batch
    # (the old per-entry get_embedding_cached path is gone), so the three entries
    # land in a single upsert call.
    monkeypatch.setattr(
        server, "get_ollama_embeddings_batch",
        lambda texts, timeout=120.0: [[0.1] * 768 for _ in texts],
    )

    result = server.ingest_distillations(session_id="test-session")

    assert mock_coll.upsert.call_count == 1
    upserted_ids = mock_coll.upsert.call_args.kwargs["ids"]
    assert set(upserted_ids) == {f"test_topic_{i}_event" for i in range(3)}
    data = json.loads(cache_path.read_text())
    for i in range(3):
        assert data["distillations"][f"test_topic_{i}_event"]["ingested_at_session"] == "test-session"
    assert "3" in result
