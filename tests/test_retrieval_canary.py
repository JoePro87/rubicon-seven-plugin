"""Task 5 (RAG hardening sprint) — the retrieval canary.

The hole this closes: tests/conftest.py's autouse ``isolate_campaign_dir``
points every test at an empty campaign dir, so nothing in the suite ever
exercises REAL retrieval — a renamed collection, a broken query construction,
or an empty-result regression would ship green (see the module docstring
discussion in the sprint spec, Task 5).

This file builds a REAL temporary ``chromadb.PersistentClient`` collection
(named whatever ``get_chroma_collection`` actually resolves to in production —
never hardcoded at the creation call site, see ``_resolve_and_create_v2_collection``),
seeds it with a handful of docs across tiers using deterministic hash-based stub
embeddings (no Ollama, no network — see ``_stub_embed``), then drives the REAL
``check_canon`` and ``_search_history_tiered_impl`` retrieval paths end-to-end
(post-Task-4, so the BM25 lexical-fusion lane rides along too) and asserts the
seeded content actually comes back out, correctly tiered, with no degradation
marker. Dedicated negative-control tests then break each failure mode the spec
calls out (renamed collection, broken query construction, empty results) and
prove the SAME healthy-path assertions would have caught it.
"""

import asyncio
import hashlib
import json
import math
import re
from unittest.mock import MagicMock

import pytest

import lexical_lane
import server


# ----------------------------------------------------------------------
# Deterministic stub embedding — no Ollama, no network.
#
# Bag-of-hashed-tokens, L2-normalized: each token increments its hashed
# dimension, so two texts sharing vocabulary land close together in cosine
# space (low distance) and texts with disjoint vocabulary land near-orthogonal
# (cosine distance ~1.0). That's enough signal to drive chromadb's REAL cosine
# math deterministically without any actual semantic understanding.
# ----------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_EMBED_DIM = 768  # matches nomic-embed-text's dimensionality


def _stub_embed(text: str) -> list:
    text = (text or "").lower()
    for prefix in ("search_query: ", "search_document: "):
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    tokens = _TOKEN_RE.findall(text)
    vec = [0.0] * _EMBED_DIM
    if not tokens:
        vec[0] = 1.0
        return vec
    for tok in tokens:
        h = int(hashlib.sha256(tok.encode()).hexdigest(), 16)
        vec[h % _EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _patch_embedders(monkeypatch):
    """Stub every embedding entry point the retrieval path (or its writers)
    could reach, all backed by the SAME deterministic function above."""
    monkeypatch.setattr(
        server, "get_embedding_cached",
        lambda prompt, timeout=30.0: _stub_embed(f"search_query: {prompt}"),
    )
    monkeypatch.setattr(
        server, "get_ollama_embedding_sync",
        lambda prompt, timeout=30.0: _stub_embed(f"search_document: {prompt}"),
    )
    monkeypatch.setattr(
        server, "get_ollama_embeddings_batch",
        lambda prompts, timeout=120.0: [_stub_embed(f"search_document: {p}") for p in prompts],
    )


def _seed_campaign_files(tmp_path, day=130, location="Ashfall Reliquary", present="Creenash, Vela"):
    (tmp_path / "lorebook.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n"
        "**Last Updated:** 2026-01-01 00:00\n\n---\n\n"
        "## SCENE STATE (check_canon reads this section)\n\n"
        f"**Day:** {day}\n"
        f"**Location:** {location}\n"
        f"**Present:** {present}\n",
        encoding="utf-8",
    )


def _resolve_and_create_v2_collection(client):
    """Discover the collection name ``get_chroma_collection`` actually resolves
    to by spying on the client it's handed (BEFORE any collection exists), then
    create a REAL collection under that resolved name — the creation call site
    below never hardcodes the literal. If production's resolution logic itself
    breaks (e.g. it stops trying the v2 name first), this raises here, loudly,
    before a single doc is seeded.

    The one pinned assertion below is the ONLY place in this whole test suite
    that hardcodes the expected name; it exists specifically so an accidental
    rename of the live collection is caught immediately rather than silently
    starving retrieval.
    """
    requested_names = []
    real_get_collection = client.get_collection

    def _spy(name, *a, **k):
        requested_names.append(name)
        return real_get_collection(name, *a, **k)

    client.get_collection = _spy
    try:
        with pytest.raises(Exception):
            # Nothing exists yet in this fresh client — this call is expected
            # to raise, we only care WHICH name(s) it asked for on the way.
            server.get_chroma_collection("campaign_history_tiered")
    finally:
        client.get_collection = real_get_collection

    assert requested_names, "get_chroma_collection never asked the chroma client for a collection name"
    resolved_name = requested_names[0]
    assert resolved_name == "campaign_history_tiered_v2", (
        "get_chroma_collection's resolved collection name changed — this pin "
        "is deliberate; update it AND the production rebuild scripts/docs "
        "together, don't just bump it to silence the test"
    )
    return client.create_collection(resolved_name, metadata={"hnsw:space": "cosine"})


class _MockCtx:
    """Minimal MCP Context stand-in for check_canon calls (same pattern as
    tests/test_rag_task2_loud_failures.py and test_rag_task4_bm25.py)."""
    pass


def _assert_recall_healthy(out: str, marker: str):
    """The reusable 'is retrieval actually working' assertion. Positive tests
    assert this passes; negative-control tests assert (via pytest.raises) that
    it does NOT — proving the assertion is sensitive to the exact failure
    modes the sprint spec calls out, not a tautology."""
    assert "SEMANTIC RECALL OFFLINE" not in out, (
        "semantic lane reported itself offline — retrieval did not run at all"
    )
    assert marker in out, f"seeded content ({marker!r}) never made it into the output"


# ----------------------------------------------------------------------
# Collection-name resolution wiring — standalone, explicit.
# ----------------------------------------------------------------------

def test_collection_name_resolves_via_production_code_path(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "_chroma_client", None)
    client = server.get_chroma_client()
    collection = _resolve_and_create_v2_collection(client)
    assert collection.name == "campaign_history_tiered_v2"


# ----------------------------------------------------------------------
# Happy path — check_canon auto-light (tier 1) recall.
# ----------------------------------------------------------------------

@pytest.fixture
def happy_path_env(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "_chroma_client", None)
    _seed_campaign_files(tmp_path, day=130)
    lexical_lane._PROCESS_CACHE.clear()

    client = server.get_chroma_client()
    collection = _resolve_and_create_v2_collection(client)

    target_doc = (
        "Ashgrave finally admitted she broke the cinderglass seal herself, "
        "back at the Vaarn outpost gate."
    )
    noise_doc_1 = (
        "The party rests by the fire and shares dried rations before the "
        "night watch shift."
    )
    noise_doc_2 = (
        "Rain drums on the tin roof of the caravan as merchants haggle over "
        "spice prices in the bazaar."
    )
    docs = [target_doc, noise_doc_1, noise_doc_2]
    ids = ["canary_target", "canary_noise_1", "canary_noise_2"]
    metas = [
        {"day": 120, "tier": 1, "arc": "delta", "scene_type": "dialogue",
         "characters": "ashgrave", "location": "Vaarn Outpost", "source": "tiered_reindex"},
        {"day": 115, "tier": 1, "arc": "delta", "scene_type": "travel",
         "characters": "", "location": "the road", "source": "tiered_reindex"},
        {"day": 118, "tier": 1, "arc": "delta", "scene_type": "travel",
         "characters": "", "location": "the bazaar", "source": "tiered_reindex"},
    ]
    collection.add(
        ids=ids,
        embeddings=[_stub_embed(d) for d in docs],
        documents=docs,
        metadatas=[server._stringify_metadata(m) for m in metas],
    )

    _patch_embedders(monkeypatch)

    return {
        "query": "Ask Ashgrave whether she broke the cinderglass seal at the Vaarn outpost",
        "marker": "cinderglass seal",
    }


def test_check_canon_recalls_seeded_history_healthy(happy_path_env):
    out = server.check_canon(_MockCtx(), user_input=happy_path_env["query"], needs=[])
    _assert_recall_healthy(out, happy_path_env["marker"])
    assert "RELEVANT HISTORY" in out
    assert "[T1]" in out


# ----------------------------------------------------------------------
# Negative controls — prove the healthy assertion above is non-vacuous by
# breaking each failure mode the spec calls out and showing it gets caught.
# ----------------------------------------------------------------------

def test_negative_control_renamed_collection_is_caught(happy_path_env, monkeypatch):
    """A renamed/missing live collection -> get_chroma_collection raises.
    The healthy assertion must fail if run against this broken state."""
    def _boom(*a, **k):
        raise RuntimeError("simulated rename: collection not found")

    monkeypatch.setattr(server, "get_chroma_collection", _boom)
    out = server.check_canon(_MockCtx(), user_input=happy_path_env["query"], needs=[])

    assert "SEMANTIC RECALL OFFLINE" in out  # the degradation marker DOES fire here
    with pytest.raises(AssertionError):
        _assert_recall_healthy(out, happy_path_env["marker"])


def test_negative_control_broken_query_construction_is_caught(happy_path_env, monkeypatch):
    """Simulates a broken query so thoroughly that NEITHER retrieval lane can
    find the seeded content: the vector embedding is unrelated garbage (e.g.
    the wrong field got embedded) AND the BM25 lexical lane's index build also
    fails. A vector-only break is deliberately NOT enough here — Task 4's dual
    -lane fusion means a lexical hit alone still surfaces the doc from the raw
    query text, which is correct resilience, not a gap. This negative control
    proves the healthy assertion still catches it when BOTH lanes go dark."""
    monkeypatch.setattr(
        server, "get_embedding_cached",
        lambda prompt, timeout=30.0: _stub_embed(
            "completely unrelated vocabulary about weather patterns and tides"
        ),
    )

    def _boom(*a, **k):
        raise RuntimeError("simulated lexical index failure")

    monkeypatch.setattr(lexical_lane, "get_or_build_index", _boom)

    out = server.check_canon(_MockCtx(), user_input=happy_path_env["query"], needs=[])

    with pytest.raises(AssertionError):
        _assert_recall_healthy(out, happy_path_env["marker"])


def test_negative_control_wrong_named_empty_collection_is_caught(happy_path_env, monkeypatch):
    """The textbook silent-regression case: a rename lands on an EMPTY
    collection. No exception, no degradation marker -- just quietly empty
    results, indistinguishable from 'no history exists yet' unless something
    asserts the seeded content is actually present. This is exactly the hole
    Task 5 exists to close."""
    empty_collection = MagicMock()
    empty_collection.name = "campaign_history_wrong_v9"
    empty_collection.count.return_value = 0
    empty_collection.query.return_value = {
        "documents": [[]], "metadatas": [[]], "distances": [[]],
    }
    empty_collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}

    monkeypatch.setattr(server, "get_chroma_collection", lambda name: empty_collection)
    out = server.check_canon(_MockCtx(), user_input=happy_path_env["query"], needs=[])

    assert "SEMANTIC RECALL OFFLINE" not in out  # exactly the danger: no loud failure
    with pytest.raises(AssertionError):
        _assert_recall_healthy(out, happy_path_env["marker"])


# ----------------------------------------------------------------------
# Progressive multi-tier drill (check_canon, needs=["history"]).
# ----------------------------------------------------------------------

def test_check_canon_progressive_drills_to_tier2(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "_chroma_client", None)
    _seed_campaign_files(tmp_path, day=130)
    lexical_lane._PROCESS_CACHE.clear()

    client = server.get_chroma_client()
    collection = _resolve_and_create_v2_collection(client)

    query = "Tell me what Ashgrave said about the cinderglass seal at the Vaarn outpost"
    tier1_noise = "Merchants argue over spice prices while rain drums on the caravan roof."
    tier2_target = (
        "Ashgrave admitted she broke the cinderglass seal herself, back at "
        "the Vaarn outpost gate."
    )
    docs = [tier1_noise, tier2_target]
    ids = ["drill_tier1_noise", "drill_tier2_target"]
    metas = [
        {"day": 100, "tier": 1, "arc": "delta", "scene_type": "travel",
         "characters": "", "location": "the road", "source": "tiered_reindex"},
        {"day": 128, "tier": 2, "arc": "delta", "scene_type": "dialogue",
         "characters": "ashgrave", "location": "Vaarn Outpost", "source": "tiered_reindex"},
    ]
    collection.add(
        ids=ids,
        embeddings=[_stub_embed(d) for d in docs],
        documents=docs,
        metadatas=[server._stringify_metadata(m) for m in metas],
    )

    _patch_embedders(monkeypatch)

    out = server.check_canon(_MockCtx(), user_input=query, needs=["history"])
    _assert_recall_healthy(out, "cinderglass seal")
    assert "PROGRESSIVE" in out
    assert "[T2]" in out
    # tier 1 never had a good/weak match -- confirms this is a real drill-through,
    # not a lucky tier-1 hit.
    assert "[T1]" not in out


# ----------------------------------------------------------------------
# Second consumer: _search_history_tiered_impl, multi-tier sweep (tier=0).
# ----------------------------------------------------------------------

def test_search_history_tiered_impl_multi_tier_sweep(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(server, "_chroma_client", None)
    _seed_campaign_files(tmp_path, day=145)
    lexical_lane._PROCESS_CACHE.clear()

    client = server.get_chroma_client()
    collection = _resolve_and_create_v2_collection(client)

    query = "What happened with the throneglass ledger at the sunken archive"
    docs = {
        "sweep_t1": (
            1, 140,
            "The throneglass ledger surfaced at the sunken archive.",
        ),
        "sweep_t2": (
            2, 141,
            "Scouts found the throneglass ledger half-buried in silt near the "
            "sunken archive entrance, worth a closer look.",
        ),
        "sweep_t3": (
            3, 142,
            "The party spent the better part of an afternoon prying the "
            "throneglass ledger free from the silt at the sunken archive "
            "entrance. Its pages, warped by decades underwater, still held "
            "faint impressions of a merchant's hand — names, dates, debts "
            "long since forgotten by everyone but the archive itself.",
        ),
        "sweep_t4": (
            4, 145,
            "By lamplight the throneglass ledger finally gave up its secrets. "
            "Page after page of the sunken archive's old accounts detailed a "
            "trade in relics nobody was supposed to know left the vault. The "
            "party read late into the night, piecing together who profited "
            "and who paid the price when the archive first flooded.",
        ),
        "sweep_noise": (
            1, 143,
            "A quiet evening at the tavern, dice rattling across a warped table.",
        ),
    }
    ids = list(docs.keys())
    texts = [v[2] for v in docs.values()]
    metas = [
        {"day": v[1], "tier": v[0], "arc": "delta", "scene_type": "exploration",
         "characters": "", "location": "the sunken archive", "source": "tiered_reindex"}
        for v in docs.values()
    ]
    collection.add(
        ids=ids,
        embeddings=[_stub_embed(t) for t in texts],
        documents=texts,
        metadatas=[server._stringify_metadata(m) for m in metas],
    )

    _patch_embedders(monkeypatch)

    out = asyncio.run(server._search_history_tiered_impl(
        query=query, tier=0, n_results=None, arc=None, scene_type=None,
        character=None, day_min=None, day_max=None,
    ))

    assert "ERROR" not in out
    assert "No results found" not in out
    assert "throneglass ledger" in out
    # correctly tiered: each surfaced result is tagged with its OWN metadata
    # tier, not some default/mislabeled value.
    for tier_num, _day, text in docs.values():
        if text in out:
            marker_index = out.index(text)
            preceding = out[:marker_index]
            last_result_header = preceding.rfind("--- Result")
            assert last_result_header != -1
            assert f"(T{tier_num})" in preceding[last_result_header:]
    # at least the strongest, most-tokened matches (T3/T4) must have made it in
    assert docs["sweep_t3"][2] in out or docs["sweep_t4"][2] in out
