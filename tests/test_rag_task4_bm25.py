"""Task 4 (RAG hardening sprint) — BM25 lexical lane + rank fusion.

Covers:
  - lexical_lane.py pure functions: tokenize, reciprocal_rank_fusion,
    fuse_lexical_into_vector, search() filtering — synthetic data, no live
    collection / no Ollama.
  - get_or_build_index staleness (rebuild on collection-count change, reuse
    otherwise).
  - Leaf-module discipline: lexical_lane never imports server.
  - Wiring into the two raw-history call sites that share the lane:
    _search_history_tiered_impl and check_canon's auto-light tier-1 lane —
    exact-name recall (a doc the vector lane misses but BM25 finds must
    surface), and lane-failure fallback (BM25 breaks -> vector-only, no
    SEMANTIC RECALL OFFLINE marker, never raises).
"""

import asyncio
import json
from unittest.mock import MagicMock

import pytest

import lexical_lane
import server


# ----------------------------------------------------------------------
# tokenize
# ----------------------------------------------------------------------

def test_tokenize_lowercases_and_splits_on_non_alnum():
    assert lexical_lane.tokenize("The Kronophage's Relay-Node!") == [
        "the", "kronophage", "s", "relay", "node",
    ]


def test_tokenize_empty_input():
    assert lexical_lane.tokenize("") == []
    assert lexical_lane.tokenize(None) == []


# ----------------------------------------------------------------------
# reciprocal_rank_fusion — pure fusion math
# ----------------------------------------------------------------------

def test_rrf_matches_standard_formula():
    # doc "a": rank 1 in list1, rank 2 in list2. doc "b": rank 2 in list1 only.
    # doc "c": rank 1 in list2 only.
    fused = lexical_lane.reciprocal_rank_fusion([["a", "b"], ["c", "a"]], k=60)
    scores = dict(fused)
    assert scores["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert scores["b"] == pytest.approx(1 / 62)
    assert scores["c"] == pytest.approx(1 / 61)


def test_rrf_doc_present_in_both_lists_outranks_single_list_doc():
    fused = lexical_lane.reciprocal_rank_fusion([["x", "y"], ["y", "z"]], k=60)
    order = [key for key, _ in fused]
    assert order[0] == "y"  # present (and high-ranked) in both lists


def test_rrf_deterministic_and_empty_safe():
    assert lexical_lane.reciprocal_rank_fusion([], k=60) == []
    assert lexical_lane.reciprocal_rank_fusion([[], []], k=60) == []
    out1 = lexical_lane.reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    out2 = lexical_lane.reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    assert out1 == out2


# ----------------------------------------------------------------------
# search() — BM25 query against a built index
# ----------------------------------------------------------------------

def _build(docs, metas=None, ids=None):
    metas = metas or [{} for _ in docs]
    ids = ids or [str(i) for i in range(len(docs))]
    return lexical_lane.build_index(ids, docs, metas)


def test_search_finds_rare_token_doc():
    idx = _build([
        "the party travels through the misty fen at dusk",
        "Kronophage stalks the delta ruins, a time-eater from before the fall",
        "the party rests and shares rations by the fire",
    ])
    hits = lexical_lane.search(idx, "Kronophage", top_k=5)
    assert hits
    assert "Kronophage" in hits[0][0]


def test_search_excludes_zero_overlap_docs():
    idx = _build(["completely unrelated text about weather", "another unrelated passage"])
    hits = lexical_lane.search(idx, "Kronophage", top_k=5)
    assert hits == []


def test_search_applies_filter_fn():
    # A third, unrelated doc keeps "Kronophage" from appearing in EVERY doc in
    # the corpus -- a term common to the whole corpus gets a degenerate
    # (non-positive) BM25 idf, which is a real quirk of the library, not a
    # bug here; a realistic 13k-doc corpus never has this problem for a rare
    # proper name.
    idx = _build(
        [
            "Kronophage sighted at the relay",
            "Kronophage sighted at the fount",
            "the party rests and shares rations by the fire",
        ],
        metas=[{"tier": "1"}, {"tier": "2"}, {"tier": "1"}],
    )
    hits = lexical_lane.search(idx, "Kronophage", top_k=5, filter_fn=lambda m: m.get("tier") == "2")
    assert len(hits) == 1
    assert hits[0][1]["tier"] == "2"


def test_search_on_empty_index_is_safe():
    idx = _build([])
    assert lexical_lane.search(idx, "anything") == []
    assert lexical_lane.search(None, "anything") == []


# ----------------------------------------------------------------------
# fuse_lexical_into_vector — exact-name recall (the core Task 4 promise)
# ----------------------------------------------------------------------

def test_fusion_surfaces_lexically_strong_vector_weak_doc():
    """A rare-token doc the vector lane never returned (embeds poorly) but
    that BM25 matches strongly MUST appear in the fused output."""
    vector_results = [
        ("a generic scene about travel and rest", {"day": 10}, 0.55),
        ("another generic travel scene", {"day": 20}, 0.58),
    ]
    lexical_hits = [
        ("Kronophage stalks the delta ruins, a time-eater from before the fall", {"day": 15}, 4.2),
    ]
    fused = lexical_lane.fuse_lexical_into_vector(vector_results, lexical_hits, weak_match_dist=0.7)
    fused_docs = [doc for doc, _meta, _dist in fused]
    assert "Kronophage" in fused_docs[0] or any("Kronophage" in d for d in fused_docs)


def test_fusion_keeps_real_distance_for_vector_hits():
    vector_results = [("doc a", {"day": 1}, 0.3)]
    lexical_hits = [("doc a", {"day": 1}, 9.0)]
    fused = lexical_lane.fuse_lexical_into_vector(vector_results, lexical_hits, weak_match_dist=0.7)
    assert fused[0] == ("doc a", {"day": 1}, 0.3)


def test_fusion_empty_inputs():
    assert lexical_lane.fuse_lexical_into_vector([], [], weak_match_dist=0.7) == []


def test_fusion_respects_max_results():
    vector_results = [(f"doc {i}", {}, 0.1 * i) for i in range(10)]
    fused = lexical_lane.fuse_lexical_into_vector(vector_results, [], weak_match_dist=0.7, max_results=3)
    assert len(fused) == 3


# ----------------------------------------------------------------------
# get_or_build_index — staleness / rebuild-on-count-change
# ----------------------------------------------------------------------

def test_get_or_build_index_rebuilds_on_count_change():
    coll = MagicMock()
    coll.name = "test_collection_staleness"
    coll.count.return_value = 2
    coll.get.return_value = {
        "ids": ["1", "2"],
        "documents": ["first doc about foxes", "second doc about hounds"],
        "metadatas": [{}, {}],
    }
    cache = {}
    idx1 = lexical_lane.get_or_build_index(coll, cache=cache)
    assert idx1.documents == ["first doc about foxes", "second doc about hounds"]
    assert coll.get.call_count == 1

    # Same count -> cache reused, no rebuild.
    idx2 = lexical_lane.get_or_build_index(coll, cache=cache)
    assert idx2 is idx1
    assert coll.get.call_count == 1

    # Count changes -> rebuild triggered.
    coll.count.return_value = 3
    coll.get.return_value = {
        "ids": ["1", "2", "3"],
        "documents": ["first doc about foxes", "second doc about hounds", "third doc about wolves"],
        "metadatas": [{}, {}, {}],
    }
    idx3 = lexical_lane.get_or_build_index(coll, cache=cache)
    assert idx3 is not idx1
    assert len(idx3.documents) == 3
    assert coll.get.call_count == 2


# ----------------------------------------------------------------------
# Leaf-module discipline
# ----------------------------------------------------------------------

def test_lexical_lane_never_imports_server():
    import pathlib
    source = pathlib.Path(lexical_lane.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("import server"), f"leaf-module violation: {line!r}"
        assert "from server" not in stripped, f"leaf-module violation: {line!r}"
    assert "server" not in dir(lexical_lane) or not callable(getattr(lexical_lane, "server", None))


# ----------------------------------------------------------------------
# Wiring: _search_history_tiered_impl (search(action='history'|'tiered'))
# ----------------------------------------------------------------------

def test_search_history_tiered_impl_bm25_surfaces_lexical_only_doc(monkeypatch):
    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    coll.query.return_value = {
        "documents": [["a generic scene about travel and rest"]],
        "metadatas": [[{"day": 10, "tier": "1"}]],
        "distances": [[0.6]],
    }
    coll.count.return_value = 3
    coll.get.return_value = {
        "ids": ["a", "b", "c"],
        "documents": [
            "a generic scene about travel and rest",
            "Kronophage stalks the delta ruins near the standing stones",
            # A third, unrelated doc: with only 2 docs a term in exactly 1 of
            # them gets a degenerate (exactly zero) BM25 idf under rank_bm25's
            # formula -- a tiny-corpus artifact, not realistic for the live
            # 13k-doc collection. See test_search_applies_filter_fn.
            "the party rests and shares rations by the fire",
        ],
        "metadatas": [{"day": 10, "tier": "1"}, {"day": 12, "tier": "1"}, {"day": 11, "tier": "1"}],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)
    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    monkeypatch.setattr(server, "get_current_day_safe", lambda: None)
    lexical_lane._PROCESS_CACHE.clear()

    out = asyncio.run(server._search_history_tiered_impl(
        query="Kronophage", tier=1, n_results=3, arc=None, scene_type=None,
        character=None, day_min=None, day_max=None,
    ))
    assert "delta ruins" in out


def test_search_history_tiered_impl_bm25_failure_falls_back_to_vector_only(monkeypatch):
    """BM25 lane raising must not affect the vector-only result or raise."""
    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    coll.query.return_value = {
        "documents": [["a scene about the relay"]],
        "metadatas": [[{"day": 10, "tier": "1"}]],
        "distances": [[0.6]],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)
    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    monkeypatch.setattr(server, "get_current_day_safe", lambda: None)

    def _boom(*a, **k):
        raise RuntimeError("index build failed")

    monkeypatch.setattr(lexical_lane, "get_or_build_index", _boom)

    out = asyncio.run(server._search_history_tiered_impl(
        query="relay", tier=1, n_results=3, arc=None, scene_type=None,
        character=None, day_min=None, day_max=None,
    ))
    assert "ERROR" not in out
    assert "a scene about the relay" in out


# ----------------------------------------------------------------------
# Wiring: check_canon's raw-history (auto-light tier-1) lane
# ----------------------------------------------------------------------

class _MockCtx:
    pass


def _seed_campaign(tmp_path, day=131, location="Ashfall Reliquary", present="Creenash, Vela"):
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


def test_check_canon_bm25_surfaces_lexical_only_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path, day=0)  # day=0 -> recency is a no-op, isolates this test to fusion

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    coll.count.return_value = 3
    coll.get.return_value = {
        "ids": ["a", "b", "c"],
        "documents": [
            "a generic scene about travel and rest",
            "Kronophage stalks the delta ruins near the standing stones",
            # Third, unrelated doc -- avoids the degenerate zero-idf case a
            # rare term gets in a 2-doc corpus (see test_search_applies_filter_fn).
            "the party rests and shares rations by the fire",
        ],
        "metadatas": [{"day": 10, "tier": "1"}, {"day": 12, "tier": "1"}, {"day": 11, "tier": "1"}],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)

    def fake_search(c, emb, tier, where, n):
        # Vector lane misses the Kronophage doc entirely -- BM25 must supply it.
        # A "good" (below GOOD_MATCH) hit at tier 1 makes _progressive_tier_search
        # stop at tier 1 deterministically, matching the BM25 corpus's tier-1
        # metadata below (this check_canon call takes the PROGRESSIVE branch,
        # not auto-light tier-1-only, since default active_blocks are non-empty).
        if tier == 1:
            return [("a generic scene about travel and rest", {"day": 10, "tier": "1"}, 0.3)]
        return []

    monkeypatch.setattr(server, "_search_single_tier", fake_search)
    lexical_lane._PROCESS_CACHE.clear()

    out = server.check_canon(_MockCtx(), user_input="tell me about Kronophage", needs=[])
    # Assert on the DOCUMENT text, not just the bare word "Kronophage" -- the
    # user_input itself contains that word too, so a weaker assertion could
    # pass on the echoed query rather than the actually-surfaced document.
    assert "delta ruins" in out
    assert "SEMANTIC RECALL OFFLINE" not in out


def test_check_canon_bm25_failure_falls_back_without_offline_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path)

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)

    def fake_search(c, emb, tier, where, n):
        return [("a scene about the standing stones", {"day": 10, "tier": "1"}, 0.6)]

    monkeypatch.setattr(server, "_search_single_tier", fake_search)

    def _boom(*a, **k):
        raise RuntimeError("bm25 index build failed")

    monkeypatch.setattr(lexical_lane, "get_or_build_index", _boom)

    out = server.check_canon(_MockCtx(), user_input="I check the standing stones", needs=[])
    assert "a scene about the standing stones" in out
    assert "SEMANTIC RECALL OFFLINE" not in out


def test_check_canon_bm25_rescues_no_match_vector_lane(tmp_path, monkeypatch):
    """When _progressive_tier_search returns "no_match" (vector lane totally
    empty across all 3 tiers), the BM25 pool must NOT be tier-filtered at all
    -- a lexically-strong tier-1 doc has to reach the output via fusion alone."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path, day=0)  # day=0 -> recency is a no-op

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    coll.count.return_value = 3
    coll.get.return_value = {
        "ids": ["a", "b", "c"],
        "documents": [
            "Kronophage stalks the delta ruins near the standing stones",
            "a generic scene about travel and rest",
            "the party rests and shares rations by the fire",
        ],
        "metadatas": [{"day": 12, "tier": "1"}, {"day": 10, "tier": "1"}, {"day": 11, "tier": "1"}],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)

    def fake_search(c, emb, tier, where, n):
        # Vector lane misses everything at every tier -- "no_match".
        return []

    monkeypatch.setattr(server, "_search_single_tier", fake_search)
    lexical_lane._PROCESS_CACHE.clear()

    out = server.check_canon(_MockCtx(), user_input="tell me about Kronophage", needs=[])
    assert "delta ruins" in out
    assert "SEMANTIC RECALL OFFLINE" not in out


def test_check_canon_bm25_admits_tier_present_in_drill_recommended_results(tmp_path, monkeypatch):
    """drill_recommended accumulates weak matches across tiers 1..3 but
    tier_reached lands on 3 regardless of which tiers actually contributed.
    A tier-2 lexical-only doc must be admitted because tier 2 IS one of the
    tiers present in the accumulated vector results -- filtering to the bare
    tier_reached value (3) would have hidden it."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path, day=0)  # day=0 -> recency is a no-op

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"  # GOOD=0.5, WEAK=0.7
    coll.count.return_value = 4
    coll.get.return_value = {
        "ids": ["a", "b", "c", "d"],
        "documents": [
            "a generic scene about travel and rest",
            "the party rests and shares rations by the fire",
            "Kronophage stalks the delta ruins near the standing stones",
            "an unrelated scene about weather and supply",
        ],
        "metadatas": [
            {"day": 10, "tier": "1"},
            {"day": 11, "tier": "1"},
            {"day": 12, "tier": "2"},
            {"day": 13, "tier": "3"},
        ],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)

    def fake_search(c, emb, tier, where, n):
        # Weak (not "good") matches at tier 1 and tier 2; nothing at tier 3 --
        # drill_recommended, tier_reached ends at 3, accumulated vector tiers
        # actually present are {"1", "2"}.
        if tier == 1:
            return [("a generic scene about travel and rest", {"day": 10, "tier": "1"}, 0.6)]
        if tier == 2:
            return [("the party rests and shares rations by the fire", {"day": 11, "tier": "2"}, 0.6)]
        return []

    monkeypatch.setattr(server, "_search_single_tier", fake_search)
    lexical_lane._PROCESS_CACHE.clear()

    out = server.check_canon(_MockCtx(), user_input="tell me about Kronophage", needs=[])
    assert "delta ruins" in out
    assert "SEMANTIC RECALL OFFLINE" not in out


# ----------------------------------------------------------------------
# Finding 2: fallback minimal-BM25 backend (used when rank_bm25 isn't
# installed) has its own exact-name recall test, independent of whichever
# backend happens to be importable in this environment.
# ----------------------------------------------------------------------

def test_fallback_bm25_backend_exact_name_recall(monkeypatch):
    """Force the rank_bm25 import to fail (as if the package weren't
    installed) and load a fresh copy of lexical_lane so its except-branch
    fallback Okapi BM25 implementation is the one actually exercised --
    then confirm it still recovers an exact-name doc the vector lane would
    miss, same contract as the rank_bm25-backed path."""
    import importlib.util
    import sys

    monkeypatch.setitem(sys.modules, "rank_bm25", None)  # forces ImportError on import

    spec = importlib.util.spec_from_file_location(
        "lexical_lane_fallback_test", lexical_lane.__file__
    )
    fallback_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fallback_module)

    assert fallback_module._USING_RANK_BM25 is False

    index = fallback_module.build_index(
        ids=["a", "b", "c"],
        documents=[
            "Kronophage stalks the delta ruins near the standing stones",
            "a generic scene about travel and rest",
            "the party rests and shares rations by the fire",
        ],
        metadatas=[{"tier": "1"}, {"tier": "1"}, {"tier": "1"}],
    )
    hits = fallback_module.search(index, "Kronophage", top_k=5)
    assert hits
    assert "Kronophage" in hits[0][0]
