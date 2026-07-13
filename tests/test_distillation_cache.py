"""Tests for the canon distillation cache."""

import json

import pytest

from hooks.distillation_cache import DistillationCache


@pytest.fixture
def tmp_cache(tmp_path):
    """Provide a DistillationCache instance using a temp file."""
    cache_path = tmp_path / "test_cache.json"
    return DistillationCache(cache_path)


@pytest.fixture
def sample_entry():
    return {
        "topic_key": "varro_amara_relationship",
        "learning": "They were political peers for decades; he betrayed her trust.",
        "key_facts": [
            "Varro financed Kael's expedition",
            "Varro edited Amara's memories",
        ],
        "source_pointers": ["lorebook:varro_truth"],
        "verified_against": {
            "lorebook_mtime": 1729872000,
            "npc_states_mtime": 1729872100,
        },
        "created_turn": 47,
        "created_session": "session-abc",
        "refined_turn": 47,
        "refined_count": 1,
        "ingested_at_session": None,
    }


def test_get_missing_returns_none(tmp_cache):
    assert tmp_cache.get("nonexistent_key") is None


def test_put_then_get(tmp_cache, sample_entry):
    tmp_cache.put(sample_entry)
    result = tmp_cache.get("varro_amara_relationship")
    assert result is not None
    assert result["learning"] == sample_entry["learning"]
    assert result["key_facts"] == sample_entry["key_facts"]


def test_put_updates_existing(tmp_cache, sample_entry):
    tmp_cache.put(sample_entry)
    # Modify and re-put
    updated = dict(sample_entry)
    updated["learning"] = "Refined: still political peers, but truth surfacing."
    updated["refined_count"] = 2
    tmp_cache.put(updated)
    result = tmp_cache.get("varro_amara_relationship")
    assert result["learning"].startswith("Refined:")
    assert result["refined_count"] == 2


def test_cache_persists_to_disk(tmp_path, sample_entry):
    cache_path = tmp_path / "persist.json"
    c1 = DistillationCache(cache_path)
    c1.put(sample_entry)

    # New instance, same file
    c2 = DistillationCache(cache_path)
    result = c2.get("varro_amara_relationship")
    assert result is not None
    assert result["learning"] == sample_entry["learning"]


def test_is_stale_returns_true_when_lorebook_newer(tmp_cache, sample_entry, tmp_path):
    # Simulate lorebook with a newer mtime
    sample_entry["verified_against"]["lorebook_mtime"] = 1000
    tmp_cache.put(sample_entry)

    # Mock a "current" lorebook mtime in the future
    current_mtimes = {"lorebook_mtime": 2000, "npc_states_mtime": 1000}
    assert tmp_cache.is_stale(sample_entry, current_mtimes) is True


def test_is_stale_returns_false_when_mtimes_match(tmp_cache, sample_entry):
    current_mtimes = sample_entry["verified_against"].copy()
    assert tmp_cache.is_stale(sample_entry, current_mtimes) is False


def test_get_unposted_returns_entries_with_null_ingestion(tmp_cache, sample_entry):
    tmp_cache.put(sample_entry)
    unposted = tmp_cache.get_unposted()
    assert len(unposted) == 1
    assert unposted[0]["topic_key"] == "varro_amara_relationship"


def test_get_unposted_excludes_already_ingested(tmp_cache, sample_entry):
    sample_entry["ingested_at_session"] = "session-xyz"
    tmp_cache.put(sample_entry)
    assert tmp_cache.get_unposted() == []


def test_mark_ingested(tmp_cache, sample_entry):
    tmp_cache.put(sample_entry)
    tmp_cache.mark_ingested("varro_amara_relationship", "session-xyz")
    result = tmp_cache.get("varro_amara_relationship")
    assert result["ingested_at_session"] == "session-xyz"


def test_mark_ingested_on_missing_key_is_safe(tmp_cache, caplog):
    """Calling mark_ingested on a key that doesn't exist should not raise."""
    import logging
    with caplog.at_level(logging.WARNING):
        tmp_cache.mark_ingested("nonexistent_key", "session-xyz")
    assert tmp_cache.get("nonexistent_key") is None
    assert any("nonexistent_key" in record.message for record in caplog.records)


def test_sequential_writes_preserve_all_entries(tmp_path, sample_entry):
    """Sequential writes from two cache instances must preserve both entries (read-modify-write roundtrip)."""
    cache_path = tmp_path / "concurrent.json"
    c1 = DistillationCache(cache_path)
    c2 = DistillationCache(cache_path)

    entry_a = dict(sample_entry, topic_key="key_a")
    entry_b = dict(sample_entry, topic_key="key_b")

    c1.put(entry_a)
    c2.put(entry_b)

    # Both should be present
    assert c1.get("key_a") is not None
    assert c2.get("key_b") is not None

    # File should be valid JSON
    data = json.loads(cache_path.read_text())
    assert "key_a" in data["distillations"]
    assert "key_b" in data["distillations"]


def test_corrupted_cache_returns_empty_and_rebuilds(tmp_path, sample_entry):
    """If the cache file is corrupted, the cache returns empty and rebuilds on next write."""
    cache_path = tmp_path / "corrupt.json"
    cache_path.write_text("{not valid json")

    c = DistillationCache(cache_path)
    assert c.get("anything") is None  # corrupt file → empty

    # Writing recovers
    c.put(sample_entry)
    assert c.get("varro_amara_relationship") is not None


def test_is_stale_returns_true_when_current_mtimes_has_unknown_key(tmp_cache, sample_entry):
    """If current_mtimes has a key not in verified_against, entry is stale (default 0)."""
    current_mtimes = {"lorebook_mtime": 1729872000, "npc_states_mtime": 1729872100, "new_source_mtime": 5000}
    assert tmp_cache.is_stale(sample_entry, current_mtimes) is True
