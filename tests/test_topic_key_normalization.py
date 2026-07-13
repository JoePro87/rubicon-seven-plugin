"""Tests for topic-key normalization in hook_utils."""

import pytest
from hooks.hook_utils import normalize_topic_key, VALID_TOPIC_SUFFIXES


def test_basic_two_participant_relationship():
    assert normalize_topic_key(["Amara", "Varro"], "relationship") == \
        "amara_varro_relationship"


def test_participants_sorted_alphabetically():
    # Same call with reversed order produces identical key
    a = normalize_topic_key(["Amara", "Varro"], "relationship")
    b = normalize_topic_key(["Varro", "Amara"], "relationship")
    assert a == b


def test_full_name_normalizes_to_first_name_via_alias(monkeypatch):
    # Mock alias map so test doesn't depend on real npc_states.json
    monkeypatch.setattr(
        "hooks.hook_utils._load_alias_map",
        lambda: {"amara vane": "amara", "amara": "amara"}
    )
    # Also clear the module-level cache so the monkeypatch takes effect
    import hooks.hook_utils as hu
    hu._ALIAS_MAP_CACHE = None

    a = normalize_topic_key(["Amara Vane", "Varro"], "relationship")
    b = normalize_topic_key(["Amara", "Varro"], "relationship")
    assert a == b


def test_three_participants_all_sorted():
    assert normalize_topic_key(
        ["Mira", "Amara", "Varro"], "history"
    ) == "amara_mira_varro_history"


def test_single_participant_event():
    assert normalize_topic_key(["Varro"], "event") == "varro_event"


def test_invalid_suffix_raises():
    with pytest.raises(ValueError, match="Invalid suffix"):
        normalize_topic_key(["Amara"], "gibberish")


def test_valid_suffixes_constant():
    assert "relationship" in VALID_TOPIC_SUFFIXES
    assert "event" in VALID_TOPIC_SUFFIXES
    assert "history" in VALID_TOPIC_SUFFIXES
    assert "location" in VALID_TOPIC_SUFFIXES
    assert "belief" in VALID_TOPIC_SUFFIXES
    assert "policy" in VALID_TOPIC_SUFFIXES


def test_whitespace_stripped():
    a = normalize_topic_key(["  Amara  ", "Varro"], "relationship")
    b = normalize_topic_key(["Amara", "Varro"], "relationship")
    assert a == b


def test_special_characters_in_name():
    # Brek/AUGUR — slash-separated compound name
    result = normalize_topic_key(["Brek/AUGUR", "Mira"], "relationship")
    # First component used, slug-friendly
    assert "brek" in result
    assert "augur" not in result  # only first component of slash-split is kept
    assert "mira" in result
    assert result.endswith("_relationship")
