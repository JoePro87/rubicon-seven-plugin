"""Task 3 (RAG hardening sprint) — recency weighting in the raw-history lane.

Covers _apply_recency_weight() directly (synthetic scored sets, deterministic,
no live collection / no Ollama) plus its wiring into the two raw-history call
sites that share it: _search_history_tiered_impl (search(action='history'|
'tiered')) and check_canon's auto-light tier-1 lane.
"""

from unittest.mock import MagicMock

import server


# ----------------------------------------------------------------------
# Core algorithm: _apply_recency_weight
# ----------------------------------------------------------------------

def test_no_op_when_current_day_unavailable():
    """current_day=None (day unavailable) must be a pure no-op."""
    results = [("old", {"day": 1}, 0.6), ("new", {"day": 130}, 0.6)]
    out = server._apply_recency_weight(results, None)
    assert out == results


def test_no_op_when_current_day_zero():
    """Day 0 is the CURRENT_STATUS parse default for 'unparseable' — treat as unavailable."""
    results = [("old", {"day": 1}, 0.6), ("new", {"day": 130}, 0.6)]
    out = server._apply_recency_weight(results, 0)
    assert out == results


def test_no_op_on_empty_results():
    assert server._apply_recency_weight([], 131) == []


def test_recent_doc_ranks_above_older_doc_at_equal_similarity():
    """Same raw distance, different age -> recent doc must sort first."""
    results = [("old", {"day": 1}, 0.6), ("recent", {"day": 130}, 0.6)]
    out = server._apply_recency_weight(results, 131, good_match_threshold=0.5)
    assert [r[0] for r in out] == ["recent", "old"]


def test_docs_without_day_metadata_are_neutral():
    """Missing/unparseable day -> untouched distance, no penalty or bonus."""
    results = [("no_day", {}, 0.6), ("bad_day", {"day": "?"}, 0.6)]
    out = server._apply_recency_weight(results, 131, good_match_threshold=0.5)
    assert dict((d, dist) for d, _, dist in out) == {"no_day": 0.6, "bad_day": 0.6}


def test_penalty_is_capped_regardless_of_age():
    """A 500-day-old doc can't be penalized worse than a 5000-day-old one — both hit the cap."""
    old = [("old", {"day": 1}, 0.6)]
    ancient = [("ancient", {"day": -4869}, 0.6)]  # current_day - day = 5000
    out_old = server._apply_recency_weight(old, 500, good_match_threshold=0.5)
    out_ancient = server._apply_recency_weight(ancient, 500, good_match_threshold=0.5)
    assert out_old[0][2] == out_ancient[0][2]
    assert out_old[0][2] <= 0.6 * (1 + server._RECENCY_MAX_PENALTY) + 1e-9


def test_strong_match_bypasses_decay():
    """A distance already at/below the strong-match bypass threshold is untouched,
    even if the doc is ancient — a great old match still beats a weak recent one."""
    good_match_threshold = 0.5
    bypass_dist = good_match_threshold * server._RECENCY_STRONG_BYPASS_FACTOR
    strong_old = ("strong_old", {"day": 1}, bypass_dist)  # exactly at the bypass line
    weak_recent = ("weak_recent", {"day": 130}, bypass_dist + 0.01)
    out = server._apply_recency_weight(
        [weak_recent, strong_old], 131, good_match_threshold=good_match_threshold
    )
    # Strong old match is untouched and must still outrank the weak recent one.
    assert out[0][0] == "strong_old"
    assert out[0][2] == bypass_dist


def test_deterministic_repeated_calls():
    results = [("a", {"day": 10}, 0.6), ("b", {"day": 100}, 0.62), ("c", {}, 0.61)]
    out1 = server._apply_recency_weight(results, 131, good_match_threshold=0.5)
    out2 = server._apply_recency_weight(results, 131, good_match_threshold=0.5)
    assert out1 == out2


# ----------------------------------------------------------------------
# Wiring: _search_history_tiered_impl (search(action='history'|'tiered'))
# ----------------------------------------------------------------------

def test_search_history_tiered_impl_applies_recency(monkeypatch):
    """Two equally-similar docs, one recent one old -> recent one surfaces first."""
    import asyncio

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"  # cosine metric -> 0.5/0.7 thresholds
    coll.query.return_value = {
        "documents": [["An old scene about the relay.", "A recent scene about the relay."]],
        "metadatas": [[{"day": 1, "tier": "1"}, {"day": 130, "tier": "1"}]],
        "distances": [[0.6, 0.6]],
    }
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)
    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    monkeypatch.setattr(server, "get_current_day_safe", lambda: 131)

    out = asyncio.run(server._search_history_tiered_impl(
        query="relay", tier=1, n_results=3, arc=None, scene_type=None,
        character=None, day_min=None, day_max=None,
    ))
    recent_idx = out.find("recent scene")
    old_idx = out.find("old scene")
    assert recent_idx != -1 and old_idx != -1
    assert recent_idx < old_idx, "recency weighting should surface the recent doc first"


# ----------------------------------------------------------------------
# Wiring: check_canon's raw-history (auto-light tier-1) lane
# ----------------------------------------------------------------------

def _seed_campaign(tmp_path, day=131):
    import json
    (tmp_path / "lorebook.json").write_text(json.dumps({"entries": []}), encoding="utf-8")
    (tmp_path / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n"
        "**Last Updated:** 2026-01-01 00:00\n\n---\n\n"
        "## SCENE STATE (check_canon reads this section)\n\n"
        f"**Day:** {day}\n"
        "**Location:** Ashfall Reliquary\n"
        "**Present:** Creenash, Vela\n",
        encoding="utf-8",
    )


def test_check_canon_raw_history_lane_applies_recency(tmp_path, monkeypatch):
    class _MockCtx:
        pass

    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path, day=131)

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)

    coll = MagicMock()
    coll.name = "campaign_history_tiered_v2"
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: coll)

    def fake_search(c, emb, tier, where, n):
        return [
            ("An old scene about the standing stones.", {"day": 1, "tier": "1"}, 0.6),
            ("A recent scene about the standing stones.", {"day": 130, "tier": "1"}, 0.6),
        ]

    monkeypatch.setattr(server, "_search_single_tier", fake_search)

    out = server.check_canon(_MockCtx(), user_input="I check the standing stones", needs=[])
    recent_idx = out.find("recent scene")
    old_idx = out.find("old scene")
    assert recent_idx != -1 and old_idx != -1
    assert recent_idx < old_idx, "recency weighting should surface the recent doc first"


def test_check_canon_distillations_lane_unaffected_by_recency(tmp_path, monkeypatch):
    """Distillations lane is curated/current by construction — Task 3 must not touch it."""
    class _MockCtx:
        pass

    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path, day=131)

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)

    dist = MagicMock()
    dist.count.return_value = 2
    dist.query.return_value = {
        "documents": [["An old nugget.", "A recent nugget."]],
        "metadatas": [[{"topic_key": "old_nugget", "day": 1}, {"topic_key": "recent_nugget", "day": 130}]],
        "distances": [[0.1, 0.1]],
    }
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: MagicMock())

    out = server.check_canon(_MockCtx(), user_input="tell me about the nugget", needs=[])
    # Original (query) order preserved -- old nugget still listed before recent one,
    # since _apply_recency_weight is never invoked on distillation_hits.
    old_idx = out.find("An old nugget")
    recent_idx = out.find("A recent nugget")
    assert old_idx != -1 and recent_idx != -1
    assert old_idx < recent_idx
