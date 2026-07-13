"""C24 — uncrystallized-names advisory (Stop-hook soft channel).

Never blocks. Surfaces a named proper noun with no canonical record only after it
recurs across >=2 turns. Known-name union (setting vocab, ancestries, roster,
lorebook, geography, bestiary) suppresses false positives.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hooks.consolidated_stop_check as csc


# --- pure scanner (no hook machinery) --------------------------------------

def test_scan_flags_unknown_proper_noun():
    known = {"vela", "kael"}
    out = csc._scan_uncrystallized_candidates(
        "Vela met a stranger named Brannoch at the door.", known)
    assert "Brannoch" in out
    assert "Vela" not in out


def test_scan_ignores_phrase_of_known_tokens():
    known = {"faa", "nomad"}
    out = csc._scan_uncrystallized_candidates("A Faa Nomad approached.", known)
    assert "Faa Nomad" not in out


def test_setting_vocab_suppresses_sentence_openers():
    known = csc._SETTING_VOCAB
    out = csc._scan_uncrystallized_candidates(
        "The wind rose. They fled. Then silence fell over Vaarn.", known)
    assert out == set()


# --- the check (with a hermetic known-union + lorebook guard) --------------

@pytest.fixture
def hermetic(tmp_path, monkeypatch):
    (tmp_path / "lorebook.json").write_text('{"entries": []}', encoding="utf-8")
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(csc, "_uncrystallized_known_names",
                        lambda: {"watched", "rafters"})
    return tmp_path


def test_recurrence_threshold_two_turns(hermetic):
    text = "Old Marrow watched from the rafters."
    b1, r1, u1 = csc._check_uncrystallized_names({}, {"turn_count": 1}, text)
    assert b1 is False and r1 == ""
    tracker = u1["uncrystallized_name_turns"]
    assert tracker["Old Marrow"]["count"] == 1

    state2 = {"turn_count": 2, "uncrystallized_name_turns": tracker}
    b2, r2, u2 = csc._check_uncrystallized_names({}, state2, text)
    assert b2 is False and r2 == ""
    assert u2["uncrystallized_name_turns"]["Old Marrow"]["count"] == 2


def test_never_blocks_and_maintenance_bypass(hermetic):
    b, r, u = csc._check_uncrystallized_names(
        {}, {"maintenance_mode": True}, "Brannoch appeared.")
    assert (b, r, u) == (False, "", {})


def test_thin_union_guard_skips_when_no_lorebook(tmp_path, monkeypatch):
    # No lorebook.json in the campaign dir -> skip (avoid false-positive storm).
    monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setattr(csc, "_uncrystallized_known_names", lambda: set())
    b, r, u = csc._check_uncrystallized_names({}, {"turn_count": 1}, "Brannoch here.")
    assert (b, r, u) == (False, "", {})
