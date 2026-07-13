"""Tests for the never-again fabrication ban list."""
import pytest
from hooks.fabrication_bans import FabricationBans


@pytest.fixture
def bans(tmp_path):
    return FabricationBans(tmp_path / "bans.json")


def test_empty_list_flags_nothing(bans):
    assert bans.check_draft("Joss poured the tea.") == []


def test_add_then_flag(bans):
    bans.add_ban(entity="Joss", wrong_terms=["botanist"],
                 correct_fact="Joss is a navigator, Mira's father.",
                 failure_mode="wrong_relationship", session_id="s1", turn=5)
    hits = bans.check_draft("Joss, the botanist, smiled.")
    assert len(hits) == 1
    assert hits[0]["entity"] == "joss"
    assert "navigator" in hits[0]["correct_fact"]


def test_entity_without_wrong_terms_not_flagged(bans):
    bans.add_ban(entity="Joss", wrong_terms=["botanist"],
                 correct_fact="Joss is a navigator.",
                 failure_mode="wrong_relationship", session_id="s1", turn=5)
    assert bans.check_draft("Joss studied the stars.") == []


def test_all_wrong_terms_required(bans):
    bans.add_ban(entity="Amara", wrong_terms=["chose", "son"],
                 correct_fact="Amara is Brek's mother-in-law; she drugged him.",
                 failure_mode="wrong_relationship", session_id="s1", turn=5)
    assert bans.check_draft("Amara chose to leave.") == []
    assert len(bans.check_draft("Amara chose him as a son.")) == 1


def test_matching_is_case_insensitive(bans):
    bans.add_ban(entity="Joss", wrong_terms=["botanist"],
                 correct_fact="navigator", failure_mode="wrong_relationship",
                 session_id="s1", turn=5)
    assert len(bans.check_draft("JOSS the BOTANIST")) == 1


def test_persists_to_disk(tmp_path):
    p = tmp_path / "bans.json"
    FabricationBans(p).add_ban(entity="Joss", wrong_terms=["botanist"],
                               correct_fact="navigator", failure_mode="wrong_relationship",
                               session_id="s1", turn=5)
    assert len(FabricationBans(p).check_draft("Joss the botanist")) == 1


def test_duplicate_ban_not_double_added(bans):
    for _ in range(2):
        bans.add_ban(entity="Joss", wrong_terms=["botanist"], correct_fact="navigator",
                     failure_mode="wrong_relationship", session_id="s1", turn=5)
    assert len(bans.all_bans()) == 1


def test_corrupt_file_returns_empty(tmp_path):
    p = tmp_path / "bans.json"
    p.write_text("{not json")
    assert FabricationBans(p).check_draft("anything") == []
