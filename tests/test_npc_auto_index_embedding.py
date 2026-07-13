"""RAG hardening sprint, Task 1 item 1: the NPC auto-index writer (_npc_set's
ChromaDB path) must embed with the DOCUMENT-prefix embedder (get_ollama_embedding_sync),
never the QUERY-prefix cache (get_embedding_cached) — and must stamp day/arc/scene_type
so day-filtered queries can find these cards (they were previously silent-dropped).
"""
import json
from unittest.mock import MagicMock

import server


def _seed_lorebook(campaign_dir):
    (campaign_dir / "lorebook.json").write_text(json.dumps({"entries": []}), encoding="utf-8")


def _patch_embedders(monkeypatch):
    doc_calls = []
    query_calls = []
    monkeypatch.setattr(
        server, "get_ollama_embedding_sync",
        lambda prompt, timeout=30.0: (doc_calls.append(prompt), [0.1] * 8)[1])
    monkeypatch.setattr(
        server, "get_embedding_cached",
        lambda prompt, timeout=30.0: (query_calls.append(prompt), [0.1] * 8)[1])
    return doc_calls, query_calls


def test_npc_auto_index_uses_document_prefix_embedder(isolate_campaign_dir, monkeypatch):
    _seed_lorebook(isolate_campaign_dir)
    coll = MagicMock()
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    doc_calls, query_calls = _patch_embedders(monkeypatch)

    server._npc_set("Test Wanderer", "friendly", "smuggling routes", "safe passage",
                     "", "Old Docks", 131)

    assert doc_calls, "expected the document-prefix embedder (get_ollama_embedding_sync) to run"
    assert not query_calls, "the query-prefix embedder must never index a document"
    assert coll.upsert.called


def test_npc_auto_index_card_carries_day_arc_scene_type(isolate_campaign_dir, monkeypatch):
    _seed_lorebook(isolate_campaign_dir)
    coll = MagicMock()
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    _patch_embedders(monkeypatch)

    server._npc_set("Test Wanderer", "friendly", "smuggling routes", "safe passage",
                     "", "Old Docks", 131)

    meta = coll.upsert.call_args.kwargs["metadatas"][0]
    assert meta["source"] == "npc_auto_index"
    assert meta["day"] == "131"          # metadata is stringified (_stringify_metadata)
    assert meta["arc"] == "current"
    assert meta["scene_type"] in {
        "combat", "intimate", "travel", "political", "dialogue", "exploration"}


def test_npc_auto_index_falls_back_to_current_day_when_last_day_unset(isolate_campaign_dir, monkeypatch):
    _seed_lorebook(isolate_campaign_dir)
    (isolate_campaign_dir / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS - DAY 200\n\n**Day:** 200\n", encoding="utf-8")
    coll = MagicMock()
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    _patch_embedders(monkeypatch)

    server._npc_set("Another NPC", "neutral", "", "", "", "unknown", 0)

    meta = coll.upsert.call_args.kwargs["metadatas"][0]
    assert meta["day"] == "200"
