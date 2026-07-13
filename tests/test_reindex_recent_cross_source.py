"""RAG hardening sprint, Task 1 item 2a: reindex_recent's pre-delete used to purge
ONLY its own prior 'reindex_recent' docs, leaving same-day docs from OTHER writers
(save_state, a manual tiered_reindex run) as byte-identical duplicates once this
batch re-lands them. It must now also purge same-day docs from those sources.

The purge must NOT touch npc_auto_index docs (standalone NPC cards, not reindex
duplicates) even when they share a covered day — a blanket $ne filter used to
catch those too and would silently delete them with no writer to re-create them.
"""
from unittest.mock import MagicMock

import server


def test_reindex_recent_purges_cross_source_same_day_duplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "MASTER_CONTINUITY_CURRENT.md").write_text(
        "## SESSION SAVED - Day 50\nA beat.", encoding="utf-8")
    monkeypatch.setattr(server, "check_ollama_health", lambda: True)

    coll = MagicMock()

    # A realistic underlying doc set spanning every writer, so the mock actually
    # applies the where-clause (rather than pattern-matching a hand-written dict)
    # and the test genuinely exercises the code's query path.
    all_docs = [
        {"id": "dup_save_state", "source": "save_state", "day": "50"},
        {"id": "dup_tiered_reindex", "source": "tiered_reindex", "day": "50"},
        {"id": "keep_other_day", "source": "save_state", "day": "999"},
        {"id": "keep_npc_card", "source": "npc_auto_index", "day": "50"},
    ]

    def matches(meta, where):
        for key, cond in where.items():
            val = meta.get(key)
            if isinstance(cond, dict):
                if "$in" in cond and val not in cond["$in"]:
                    return False
                if "$ne" in cond and val == cond["$ne"]:
                    return False
            elif val != cond:
                return False
        return True

    def fake_get(where=None, include=None):
        if where == {"source": "reindex_recent"}:
            return {"ids": []}
        matched = [d for d in all_docs if matches(d, where or {})]
        return {
            "ids": [d["id"] for d in matched],
            "metadatas": [{"source": d["source"], "day": d["day"]} for d in matched],
        }

    coll.get.side_effect = fake_get
    coll.count.return_value = 4
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(
        server, "chunk_text_tiered",
        lambda text, metadata, session_id: [
            {"id": "c1", "text": "Day 50 beat", "embedding_text": "x",
             "metadata": {"tier": 4, "day": 50}}])
    monkeypatch.setattr(server, "get_ollama_embeddings_batch",
                        lambda texts, timeout=120.0: [[0.1] * 8 for _ in texts])

    out = server.reindex_recent()

    assert "ERROR" not in out, out
    assert "Removed 2 cross-source duplicate documents" in out

    delete_id_sets = [set(c.kwargs.get("ids", c.args[0] if c.args else []))
                       for c in coll.delete.call_args_list]
    assert {"dup_save_state", "dup_tiered_reindex"} in delete_id_sets
    # the other-day doc must survive
    assert not any("keep_other_day" in s for s in delete_id_sets)
    # the standalone NPC card sharing the covered day must survive — it is NOT
    # a reindex duplicate, and there is no writer to re-create it if purged
    assert not any("keep_npc_card" in s for s in delete_id_sets)


def test_reindex_recent_skips_cross_source_purge_when_no_days_detected(monkeypatch, tmp_path):
    """No 'Day N' header anywhere -> covered_days is empty -> no cross-source get/delete call."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "MASTER_CONTINUITY_CURRENT.md").write_text("No day marker here.", encoding="utf-8")
    monkeypatch.setattr(server, "check_ollama_health", lambda: True)

    coll = MagicMock()
    coll.get.return_value = {"ids": []}
    coll.count.return_value = 1
    monkeypatch.setattr(server, "get_chroma_collection", lambda *a, **k: coll)
    monkeypatch.setattr(
        server, "chunk_text_tiered",
        lambda text, metadata, session_id: [
            {"id": "c1", "text": "No day marker here.", "embedding_text": "x",
             "metadata": {"tier": 4, "day": 0}}])
    monkeypatch.setattr(server, "get_ollama_embeddings_batch",
                        lambda texts, timeout=120.0: [[0.1] * 8 for _ in texts])

    out = server.reindex_recent()

    assert "ERROR" not in out, out
    assert "cross-source duplicate" not in out
    where_args = [c.kwargs.get("where") for c in coll.get.call_args_list]
    assert {"source": {"$in": ["save_state", "tiered_reindex"]}} not in where_args
