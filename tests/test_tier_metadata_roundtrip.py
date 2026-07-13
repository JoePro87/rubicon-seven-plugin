"""C5 — save_state-indexed session chunks must be reachable by tier-filtered reads.

The tiered read path filters on a STRING tier ({"tier": str(tier)}). save_state's
auto-index used to write chunk metadata raw (tier as INT), so its docs never
matched a tier-filtered query — 508 live session docs were invisible. The fix
routes both writers through _stringify_metadata. This test locks the write->read
type contract with a type-sensitive fake collection (ChromaDB equality is
type-sensitive: 2 != "2").
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server

_LONG_TEXT = (
    "## SESSION SAVED - Day 131\n\n"
    "Amara crossed the courtyard at dusk, the sage canister still warm in her hands. "
    "Mira traced the navigator's route across the cracked table while Brek watched the "
    "far door. The accord with the exile clan held through the night, and the first caravan "
    "reached the outer wall before the twin moons rose over the glass dunes of Vaarn. "
    "Nothing moved in the ruined tiers below, but the wind carried the smell of rust and salt."
) * 2


def _where_match(meta, where):
    """Type-sensitive exact-match, mirroring ChromaDB equality semantics."""
    return all(meta.get(k) == v for k, v in (where or {}).items())


class FakeCollection:
    name = "campaign_history_tiered_v2"

    def __init__(self):
        self.docs = []

    def add(self, ids, embeddings, documents, metadatas):
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.docs.append({"id": i, "embedding": e, "document": d, "metadata": m})

    def query(self, query_embeddings, n_results, where, include):
        matched = [x for x in self.docs if _where_match(x["metadata"], where)][:n_results]
        return {
            "documents": [[x["document"] for x in matched]],
            "metadatas": [[x["metadata"] for x in matched]],
            "distances": [[0.1 for _ in matched]],
        }


def _chunks():
    return server.chunk_text_tiered(
        text=_LONG_TEXT,
        metadata={"day": 131, "arc": "current", "source": "save_state"},
        session_id="session_day_131",
    )


def test_stringified_save_state_chunk_is_tier_searchable():
    coll = FakeCollection()
    chunks = _chunks()
    # Write exactly as the fixed save_state auto-index does (via _stringify_metadata).
    coll.add(
        ids=[c["id"] for c in chunks],
        embeddings=[[0.1] * 3 for _ in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[server._stringify_metadata(c["metadata"]) for c in chunks],
    )
    res = server._search_single_tier(coll, [0.1] * 3, tier=2, where_filter={}, n_request=20)
    assert res, "tier-2 filtered read found no save_state chunk (write/read type mismatch)"
    for _doc, meta, _dist in res:
        assert meta["tier"] == "2"


def test_raw_int_tier_is_invisible_regression_guard():
    """The old buggy path (raw int metadata) must be unreachable — proves the bug."""
    coll = FakeCollection()
    chunks = _chunks()
    coll.add(
        ids=[c["id"] for c in chunks],
        embeddings=[[0.1] * 3 for _ in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],  # RAW: tier is int
    )
    res = server._search_single_tier(coll, [0.1] * 3, tier=2, where_filter={}, n_request=20)
    assert res == [], "raw int-tier docs should NOT match a string tier filter"


def test_stringify_metadata_coerces_all_values():
    out = server._stringify_metadata({"tier": 2, "day": 131, "arc": "current"})
    assert out == {"tier": "2", "day": "131", "arc": "current"}
    assert all(isinstance(v, str) for v in out.values())
