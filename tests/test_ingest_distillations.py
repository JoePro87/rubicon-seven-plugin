"""Integration test for the ingest_distillations MCP tool.

Exercises the REAL batched-embed contract in server.ingest_distillations
(server.py ~10106-10148):

  * valid entries are BATCH-embedded via get_ollama_embeddings_batch() and
    upserted in one collection.upsert() call per batch slice;
  * entries with empty learning text are dropped to failures BEFORE embedding;
  * if a whole batch's embed/upsert fails, a per-entry fallback re-embeds each
    one via get_ollama_embedding_sync() so a single bad entry cannot sink the
    rest of the batch.

These tests monkeypatch the two embedding entry points the code actually
calls (the old get_embedding_cached path is gone).
"""

import json
import session_tools
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def temp_cache_with_entries(tmp_path, monkeypatch):
    """Set up a temp cache file with two unposted entries and one already-ingested."""
    cache_path = tmp_path / ".canon_distillations.json"
    data = {
        "schema_version": 1,
        "distillations": {
            "varro_amara_relationship": {
                "topic_key": "varro_amara_relationship",
                "learning": "Political peers turned adversaries.",
                "key_facts": ["Varro financed Kael's expedition"],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000, "npc_states_mtime": 1000},
                "created_turn": 1, "created_session": "s1",
                "refined_turn": 1, "refined_count": 1,
                "ingested_at_session": None,
            },
            "kael_varro_history": {
                "topic_key": "kael_varro_history",
                "learning": "Varro sent Kael to a fatal site.",
                "key_facts": ["Site Seven; Chromatic Wound proximity"],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000, "npc_states_mtime": 1000},
                "created_turn": 2, "created_session": "s1",
                "refined_turn": 2, "refined_count": 1,
                "ingested_at_session": None,
            },
            "already_done_event": {
                "topic_key": "already_done_event",
                "learning": "Already ingested.",
                "key_facts": ["fact"],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000, "npc_states_mtime": 1000},
                "created_turn": 3, "created_session": "s0",
                "refined_turn": 3, "refined_count": 1,
                "ingested_at_session": "s0",
            },
        },
    }
    cache_path.write_text(json.dumps(data, indent=2))
    return cache_path


def _stub_batch_embed(monkeypatch, server):
    """Make the batch embedder return one 768-vector per input text."""
    def fake_batch(texts, timeout=120.0):
        return [[0.1] * 768 for _ in texts]
    monkeypatch.setattr(server, "get_ollama_embeddings_batch", fake_batch)
    monkeypatch.setattr(session_tools, "get_ollama_embeddings_batch", server.get_ollama_embeddings_batch)  # Wave 8 fault-line twin


def test_ingest_distillations_processes_unposted(temp_cache_with_entries, monkeypatch):
    """ingest_distillations() batch-embeds and ingests only unposted entries."""
    import server
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", temp_cache_with_entries)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin

    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin

    # Real contract: the batch embedder is what gets called.
    _stub_batch_embed(monkeypatch, server)

    result = server.ingest_distillations(session_id="s_test")

    # Two unposted entries fit in one batch slice -> one upsert call carrying both ids.
    assert mock_coll.upsert.call_count == 1
    upsert_kwargs = mock_coll.upsert.call_args.kwargs
    assert set(upsert_kwargs["ids"]) == {
        "varro_amara_relationship",
        "kael_varro_history",
    }
    assert len(upsert_kwargs["embeddings"]) == 2

    # Cache updated: both unposted now marked ingested for this session.
    data = json.loads(temp_cache_with_entries.read_text())
    assert data["distillations"]["varro_amara_relationship"]["ingested_at_session"] == "s_test"
    assert data["distillations"]["kael_varro_history"]["ingested_at_session"] == "s_test"
    assert data["distillations"]["already_done_event"]["ingested_at_session"] == "s0"  # unchanged

    assert "2" in result or "ingested" in result.lower()


def test_ingest_distillations_with_no_unposted(tmp_path, monkeypatch):
    """When the cache is empty or all entries are already ingested, returns clean."""
    cache_path = tmp_path / ".canon_distillations.json"
    cache_path.write_text('{"schema_version": 1, "distillations": {}}')

    import server
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin
    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin
    _stub_batch_embed(monkeypatch, server)

    result = server.ingest_distillations(session_id="s_test")
    assert mock_coll.upsert.call_count == 0
    assert "0" in result or "no" in result.lower()


def test_ingest_distillations_handles_mixed_batch_with_failures(tmp_path, monkeypatch):
    """Empty learning is dropped pre-embed; a batch embed failure falls back per-entry,
    so a good entry still lands while the bad one is reported."""
    cache_path = tmp_path / ".canon_distillations.json"
    data = {
        "schema_version": 1,
        "distillations": {
            "good_entry_event": {
                "topic_key": "good_entry_event",
                "learning": "A solid learning.",
                "key_facts": ["fact"],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000},
                "created_turn": 1, "created_session": "s1",
                "refined_turn": 1, "refined_count": 1,
                "ingested_at_session": None,
            },
            "empty_learning_event": {
                "topic_key": "empty_learning_event",
                "learning": "",  # empty — dropped to failures BEFORE embedding
                "key_facts": [],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000},
                "created_turn": 2, "created_session": "s1",
                "refined_turn": 2, "refined_count": 1,
                "ingested_at_session": None,
            },
            "embed_error_event": {
                "topic_key": "embed_error_event",
                "learning": "Triggers embed failure.",
                "key_facts": ["fact"],
                "source_pointers": [],
                "verified_against": {"lorebook_mtime": 1000},
                "created_turn": 3, "created_session": "s1",
                "refined_turn": 3, "refined_count": 1,
                "ingested_at_session": None,
            },
        },
    }
    cache_path.write_text(json.dumps(data, indent=2))

    import server
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin

    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin

    # Force the batch path to fail so the per-entry fallback runs.
    def fake_batch(texts, timeout=120.0):
        raise RuntimeError("simulated batch embed failure")
    monkeypatch.setattr(server, "get_ollama_embeddings_batch", fake_batch)
    monkeypatch.setattr(session_tools, "get_ollama_embeddings_batch", server.get_ollama_embeddings_batch)  # Wave 8 fault-line twin

    # Per-entry fallback: succeeds for the good one, fails for the embed_error one.
    def fake_sync(text, *args, **kwargs):
        if text == "Triggers embed failure.":
            raise RuntimeError("simulated ollama timeout")
        return [0.1] * 768
    monkeypatch.setattr(server, "get_ollama_embedding_sync", fake_sync)
    monkeypatch.setattr(session_tools, "get_ollama_embedding_sync", server.get_ollama_embedding_sync)  # Wave 8 fault-line twin

    result = server.ingest_distillations(session_id="s_test")

    # Only the good entry was upserted (per-entry fallback, one id at a time).
    assert mock_coll.upsert.call_count == 1
    good_kwargs = mock_coll.upsert.call_args.kwargs
    assert good_kwargs["ids"] == ["good_entry_event"]

    # One success reported.
    assert "1" in result

    # Failures reported for both the empty-learning entry and the embed error.
    assert "Failures" in result or "failures" in result.lower()
    assert "empty" in result.lower() or "empty_learning" in result
    assert "embed_error" in result or "ollama" in result.lower()

    # Cache reflects only the good entry as ingested.
    data2 = json.loads(cache_path.read_text())
    assert data2["distillations"]["good_entry_event"]["ingested_at_session"] == "s_test"
    assert data2["distillations"]["empty_learning_event"]["ingested_at_session"] is None
    assert data2["distillations"]["embed_error_event"]["ingested_at_session"] is None


def test_ingest_distillations_writes_lorebook_mtime_to_metadata(temp_cache_with_entries, monkeypatch):
    """Verify lorebook_mtime (and other provenance keys) appear in upsert metadata."""
    import server
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", temp_cache_with_entries)
    monkeypatch.setattr(session_tools, "_DISTILLATION_CACHE_PATH", server._DISTILLATION_CACHE_PATH)  # Wave 8 fault-line twin

    mock_coll = MagicMock()
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: mock_coll)
    monkeypatch.setattr(session_tools, "get_canon_distillations_collection", server.get_canon_distillations_collection)  # Wave 8 fault-line twin
    _stub_batch_embed(monkeypatch, server)

    server.ingest_distillations(session_id="s_test")

    saw_metadata = False
    for call in mock_coll.upsert.call_args_list:
        metadatas = call.kwargs.get("metadatas")
        if metadatas is None and len(call.args) > 3:
            metadatas = call.args[3]
        if not metadatas:
            continue
        for meta in metadatas:
            saw_metadata = True
            assert "lorebook_mtime" in meta, f"lorebook_mtime missing from metadata: {meta}"
            assert "topic_key" in meta
            assert "characters" in meta
            assert "created_session" in meta
            assert "refined_count" in meta
            assert meta["lorebook_mtime"] == 1000

    assert saw_metadata, "no metadata was passed to upsert"
