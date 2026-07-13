"""RAG hardening sprint, Task 1 item 3: the health-check freshness line only checked
'indexed_at' (written by a manual tiered_reindex run), never 'timestamp' (written by
save_state's per-session auto-index) or reindex_recent (writes neither). It reported
the last full rebuild as "latest", not the last actual save. It must now take the max
across both stamp fields, and fall back to day metadata when neither is present.
"""
from unittest.mock import MagicMock

import server


def _fake_client_no_v2():
    client = MagicMock()
    client.get_collection.side_effect = Exception("no v2 collection in this test")
    return client


def test_health_check_prefers_max_across_indexed_at_and_timestamp(monkeypatch):
    coll = MagicMock()
    coll.count.return_value = 3
    coll.get.return_value = {
        "metadatas": [
            {"day": "40", "source": "tiered_reindex", "tier": "4", "indexed_at": "2026-06-01T10:00:00"},
            {"day": "131", "source": "save_state", "tier": "4", "timestamp": "2026-07-02"},
            {"day": "50", "source": "reindex_recent", "tier": "4"},
        ],
        "embeddings": [[0.1] * 8, [0.1] * 8, [0.1] * 8],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(server, "get_chroma_client", lambda: _fake_client_no_v2())
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: True)

    out = server._chroma_health_check_impl()

    assert "**Last Indexed:** 2026-07-02" in out, out


def test_health_check_falls_back_to_day_metadata_when_no_stamps(monkeypatch):
    coll = MagicMock()
    coll.count.return_value = 1
    coll.get.return_value = {
        "metadatas": [{"day": "131", "source": "reindex_recent", "tier": "4"}],
        "embeddings": [[0.1] * 8],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(server, "get_chroma_client", lambda: _fake_client_no_v2())
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: True)

    out = server._chroma_health_check_impl()

    assert "no indexed_at/timestamp metadata" in out
    assert "Day 131" in out


def test_health_check_ignores_docs_with_older_stamps(monkeypatch):
    coll = MagicMock()
    coll.count.return_value = 2
    coll.get.return_value = {
        "metadatas": [
            {"day": "10", "source": "tiered_reindex", "tier": "4", "indexed_at": "2026-01-01T00:00:00"},
            {"day": "20", "source": "tiered_reindex", "tier": "4", "indexed_at": "2025-12-01T00:00:00"},
        ],
        "embeddings": [[0.1] * 8, [0.1] * 8],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(server, "get_chroma_client", lambda: _fake_client_no_v2())
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: True)

    out = server._chroma_health_check_impl()

    assert "**Last Indexed:** 2026-01-01T00:00:00" in out
