"""Unit tests for _progressive_tier_search() helper in server.py."""

from unittest.mock import MagicMock
import pytest


def _mock_collection(name="campaign_history_tiered_v2"):
    coll = MagicMock()
    coll.name = name
    return coll


@pytest.fixture
def mock_server(monkeypatch):
    """Mock _search_single_tier so tests don't hit real ChromaDB."""
    import server
    return server


def test_tier_1_good_match_returns_only_tier_1(mock_server, monkeypatch):
    """Tier 1 strong match → return only those results."""
    def fake_search(coll, emb, tier, where, n):
        if tier == 1:
            return [("doc1", {"day": 1}, 0.3), ("doc2", {"day": 2}, 0.4)]
        return []
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "sufficient"
    assert tier == 1
    assert [r[0] for r in results] == ["doc1", "doc2"]


def test_tier_1_weak_tier_2_good_returns_only_tier_2_good(mock_server, monkeypatch):
    """Tier 1 only weak, tier 2 good → return tier 2 only (no tier 1 leak)."""
    def fake_search(coll, emb, tier, where, n):
        if tier == 1:
            return [("weak", {}, 0.6)]  # weak (>0.5, <0.7)
        if tier == 2:
            return [("good", {}, 0.3)]  # good
        return []
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "sufficient"
    assert tier == 2
    assert [r[0] for r in results] == ["good"]
    # CRITICAL: tier 1 weak result must not leak into return
    assert "weak" not in [r[0] for r in results]


def test_all_weak_returns_drill_recommended(mock_server, monkeypatch):
    """All tiers return only weak results → drill_recommended with accumulated weak."""
    def fake_search(coll, emb, tier, where, n):
        return [(f"weak_t{tier}", {}, 0.65)]  # weak everywhere
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "drill_recommended"
    assert tier == 3
    assert len(results) <= 5
    assert all("weak" in r[0] for r in results)


def test_no_matches_returns_no_match(mock_server, monkeypatch):
    """All tiers empty → no_match with empty results."""
    monkeypatch.setattr(mock_server, "_search_single_tier", lambda *a, **k: [])
    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "no_match"
    assert results == []


def test_exception_in_tier_continues_to_next(mock_server, monkeypatch):
    """Exception in tier 1 → log + continue. Tier 2 success returns normally."""
    def fake_search(coll, emb, tier, where, n):
        if tier == 1:
            raise RuntimeError("simulated chroma failure")
        if tier == 2:
            return [("recovered", {}, 0.3)]
        return []
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "sufficient"
    assert tier == 2  # tier_reached reflects the tier that actually succeeded
    assert results[0][0] == "recovered"


def test_all_exceptions_returns_no_match_with_tier_reached_0(mock_server, monkeypatch):
    """All tiers raise → no_match, tier_reached stays at 0 (no successful searches)."""
    def fake_search(coll, emb, tier, where, n):
        raise RuntimeError(f"tier {tier} broken")
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10
    )
    assert signal == "no_match"
    assert results == []
    assert tier == 0  # NO tier completed successfully


def test_l2_collection_uses_l2_thresholds(mock_server, monkeypatch):
    """Non-v2 collection name → L2 thresholds (300/350) instead of cosine (0.5/0.7)."""
    def fake_search(coll, emb, tier, where, n):
        if tier == 1:
            return [("doc", {}, 250)]  # 250 < 300 = good in L2 mode
        return []
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    coll = _mock_collection(name="campaign_history_tiered")  # no v2 suffix
    results, tier, signal = mock_server._progressive_tier_search(coll, [0.1]*10)
    assert signal == "sufficient"
    assert results[0][0] == "doc"


def test_max_tier_caps_iteration(mock_server, monkeypatch):
    """max_tier=1 only searches tier 1, never escalates."""
    tier_calls = []
    def fake_search(coll, emb, tier, where, n):
        tier_calls.append(tier)
        return [("weak", {}, 0.6)]  # weak only
    monkeypatch.setattr(mock_server, "_search_single_tier", fake_search)

    results, tier, signal = mock_server._progressive_tier_search(
        _mock_collection(), [0.1]*10, max_tier=1
    )
    assert tier_calls == [1]  # only tier 1 called, no escalation
    assert tier == 1
    assert signal == "drill_recommended"
