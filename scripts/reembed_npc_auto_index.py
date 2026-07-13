"""One-off: re-embed the live 'npc_auto_index' ChromaDB docs.

RAG hardening sprint, Task 1 item 1. The NPC auto-index writer (server.py's
_npc_set) used to embed each card with the QUERY-prefix embedder
(get_embedding_cached -> 'search_query: ') instead of the DOCUMENT-prefix
embedder (get_ollama_embedding_sync -> 'search_document: '). The writer is
fixed (server.py), but the docs already sitting in the live collection were
embedded with the wrong prefix and need re-embedding. Those same docs also
predate the day/arc/scene_type metadata the fixed writer now stamps, so this
pass backfills that too (additive — no field is removed, only added/replaced).

Safe by construction:
  - Reuses server.py's own path/collection resolution (get_chroma_collection,
    CAMPAIGN_DIR) so it touches the exact live store the engine touches --
    no re-derived path to drift from the real one.
  - update() in place by existing doc id -- never deletes, never adds new ids.
  - DRY-RUN BY DEFAULT. Nothing is written until --execute is passed.

Usage:
    .venv/Scripts/python.exe scripts/reembed_npc_auto_index.py            # dry-run (default)
    .venv/Scripts/python.exe scripts/reembed_npc_auto_index.py --execute  # apply
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402


def _current_day_for(npc_key: str) -> int:
    """Best-effort day for this card: the NPC's own last_seen_day, else the
    live campaign's current day, else 0 (never fabricate a specific day)."""
    try:
        data, err = server._load_npc_states()
        if not err:
            rec = data.get("npcs", {}).get(npc_key, {})
            day = rec.get("last_seen_day")
            if day:
                return int(day)
    except Exception:
        pass
    return server.get_current_day_safe() or 0


def main(execute: bool) -> int:
    if not execute and not server.check_ollama_health():
        print("NOTE: Ollama is not reachable — dry-run can still enumerate docs, "
              "but --execute would fail. Start Ollama (`ollama serve`) before applying.")

    collection = server.get_chroma_collection("campaign_history_tiered")
    existing = collection.get(where={"source": "npc_auto_index"}, include=["documents", "metadatas"])
    ids = existing.get("ids", [])
    docs = existing.get("documents", [])
    metas = existing.get("metadatas", [])

    print(f"Found {len(ids)} npc_auto_index docs in the live collection.")
    if not ids:
        return 0

    planned = []
    for doc_id, text, meta in zip(ids, docs, metas):
        npc_key = doc_id[len("npc_"):].replace("_", " ") if doc_id.startswith("npc_") else doc_id
        day = _current_day_for(npc_key)
        new_meta = dict(meta)
        new_meta["day"] = day
        new_meta.setdefault("arc", "current")
        new_meta["scene_type"] = server._infer_scene_type(text)
        planned.append((doc_id, text, new_meta))
        print(f"  {doc_id}: day={meta.get('day', '<absent>')} -> {day}, "
              f"arc={meta.get('arc', '<absent>')} -> {new_meta['arc']}, "
              f"scene_type={meta.get('scene_type', '<absent>')} -> {new_meta['scene_type']}")

    if not execute:
        print(f"\nDRY RUN: would re-embed + update {len(planned)} docs. "
              f"Re-run with --execute to apply.")
        return 0

    if not server.check_ollama_health():
        print("ERROR: Ollama unavailable — cannot re-embed. Start `ollama serve` and retry.")
        return 1

    updated = 0
    for doc_id, text, new_meta in planned:
        embedding = server.get_ollama_embedding_sync(text)
        collection.update(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[server._stringify_metadata(new_meta)],
        )
        updated += 1
        print(f"  updated {doc_id}")

    print(f"\nDone. Re-embedded + updated {updated}/{len(planned)} npc_auto_index docs.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                         help="Apply the re-embed + metadata backfill. Without this flag, "
                              "the script only PRINTS what it would do.")
    args = parser.parse_args()
    sys.exit(main(args.execute))
