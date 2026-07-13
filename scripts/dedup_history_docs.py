"""One-off: remove cross-source, same-day duplicate docs from the live tiered
ChromaDB collection.

RAG hardening sprint, Task 1 item 2b. Days ~124-131 were triple-indexed by three
writers (an archived tiered_reindex script, reindex_recent, and save_state's
per-session auto-index) before reindex_recent's pre-delete was extended to cover
other sources going forward (see the forward fix in server.py's reindex_recent).
This script is the BACKWARD half: it finds docs already sitting in the live
collection that are byte-identical duplicates for the same day/tier and removes
all but one survivor.

Match key: (day, tier, exact document text). Docs are only considered duplicates
if their text is BYTE-IDENTICAL -- no fuzzy matching, no cross-day merging.

Survivor choice (deterministic, documented, not owner-negotiated -- doesn't matter
which byte-identical copy survives, only that exactly one does): prefer a doc from
an ACTIVE writer over the retired one, then lowest id for full determinism.
    reindex_recent > save_state > npc_auto_index > tiered_reindex > (anything else)

Safe by construction:
  - Reuses server.py's own collection resolution (get_chroma_collection) -- the
    exact live store the engine touches, no re-derived path to drift from it.
  - MANDATORY dry-run: prints exact counts + doc ids that WOULD be deleted, and
    requires --execute to actually delete anything.
  - Only ever deletes; never adds, edits, or re-embeds a document.

Usage:
    .venv/Scripts/python.exe scripts/dedup_history_docs.py            # dry-run (default)
    .venv/Scripts/python.exe scripts/dedup_history_docs.py --execute  # apply
"""
import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402

_SOURCE_PRIORITY = {
    "reindex_recent": 0,
    "save_state": 1,
    "npc_auto_index": 2,
    "tiered_reindex": 3,
}


def _survivor_sort_key(doc_id: str, meta: dict):
    source = meta.get("source", "")
    return (_SOURCE_PRIORITY.get(source, 99), doc_id)


def find_duplicate_groups(ids, docs, metas):
    """Group ids by (day, tier, text); return only groups with >1 member,
    each as (day, tier, survivor_id, [stale_ids...])."""
    groups = defaultdict(list)
    for doc_id, text, meta in zip(ids, docs, metas):
        day = meta.get("day", "0")
        tier = meta.get("tier", "0")
        groups[(day, tier, text)].append((doc_id, meta))

    result = []
    for (day, tier, _text), members in groups.items():
        if len(members) < 2:
            continue
        members_sorted = sorted(members, key=lambda m: _survivor_sort_key(*m))
        survivor_id = members_sorted[0][0]
        stale_ids = [doc_id for doc_id, _meta in members_sorted[1:]]
        result.append((day, tier, survivor_id, stale_ids))
    return result


def main(execute: bool) -> int:
    collection = server.get_chroma_collection("campaign_history_tiered")
    total_before = collection.count()
    all_docs = collection.get(include=["documents", "metadatas"])
    ids = all_docs.get("ids", [])
    docs = all_docs.get("documents", [])
    metas = all_docs.get("metadatas", [])

    print(f"Live collection: {total_before} total docs.")

    groups = find_duplicate_groups(ids, docs, metas)
    total_stale = sum(len(stale) for *_rest, stale in groups)

    print(f"Found {len(groups)} duplicate groups covering {total_stale} stale docs "
          f"to remove (byte-identical text, same day+tier).")
    for day, tier, survivor_id, stale_ids in groups:
        print(f"  day={day} tier={tier}: keep {survivor_id}, remove {stale_ids}")

    if not execute:
        print(f"\nDRY RUN: would remove {total_stale} docs, leaving "
              f"{total_before - total_stale}. Re-run with --execute to apply.")
        return 0

    all_stale_ids = [doc_id for *_rest, stale in groups for doc_id in stale]
    if all_stale_ids:
        collection.delete(ids=all_stale_ids)
    print(f"\nDone. Removed {len(all_stale_ids)} docs. "
          f"Collection now has {collection.count()} docs.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true",
                         help="Apply the deletions. Without this flag, the script "
                              "only PRINTS what it would remove.")
    args = parser.parse_args()
    sys.exit(main(args.execute))
