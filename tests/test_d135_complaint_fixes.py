"""D135 player-complaint fixes (docs/reports/PLAYER_COMPLAINTS_2026-07-20.md).

Complaint 2c: "a way to file four petitions" — wrong count asserted in NARRATION
sailed through because the quantity scanner only reads quoted dialogue. Fix:
check_narration_claims gains a tracked-entity quantity pass, noun-list-driven
from the campaign's fabrication_tripwires.json (``tracked_quantity_nouns``).

Complaint 3: out-of-character meta answers (entirely parenthetical) armed the
prose gate, forcing junk validate calls. Fix: meta-only turns neither arm the
gate nor feed the blacklist scan / template corpus / prose observer.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks import consolidated_stop_check as csc  # noqa: E402
from hooks.fabrication_detectors import (  # noqa: E402
    check_narration_claims, check_tripwires)


# ---------------- tracked-entity quantity claims in narration ----------------

def _seed_tracked_nouns(tmp_path, monkeypatch, nouns):
    (tmp_path / "fabrication_tripwires.json").write_text(
        json.dumps({"tracked_quantity_nouns": nouns}), encoding="utf-8")
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))


def test_unverified_tracked_count_in_narration_flags(tmp_path, monkeypatch):
    _seed_tracked_nouns(tmp_path, monkeypatch, ["petition", "petitions"])
    hits = check_narration_claims(
        "Somewhere in this hall there is a way to file four petitions.",
        set(), "three outstanding departure petitions remain")
    assert any("four petitions" in h for h in hits), hits


def test_verified_count_passes_even_with_words_between(tmp_path, monkeypatch):
    _seed_tracked_nouns(tmp_path, monkeypatch, ["petition", "petitions"])
    hits = check_narration_claims(
        "Three petitions still wait for the council's stamp.",
        set(), "three outstanding departure petitions remain")
    assert hits == []


def test_digit_form_flags_too(tmp_path, monkeypatch):
    _seed_tracked_nouns(tmp_path, monkeypatch, ["vote", "votes"])
    hits = check_narration_claims(
        "The tally board shows 9 votes already cast.", set(), "")
    assert any("9 votes" in h for h in hits), hits


def test_untracked_noun_never_flags(tmp_path, monkeypatch):
    _seed_tracked_nouns(tmp_path, monkeypatch, ["petition", "petitions"])
    hits = check_narration_claims(
        "Three doors lead off the gallery, and seven lanterns gutter above.",
        set(), "")
    assert hits == []


def test_vague_quantifier_is_not_a_count(tmp_path, monkeypatch):
    _seed_tracked_nouns(tmp_path, monkeypatch, ["petition", "petitions"])
    hits = check_narration_claims(
        "Several petitions have crossed that desk over the years.", set(), "")
    assert hits == []


def test_quoted_dialogue_is_not_scanned_by_narration_pass(tmp_path, monkeypatch):
    # In-dialogue quantities belong to the dialogue claim scanner; the
    # narration pass must not double-flag them.
    _seed_tracked_nouns(tmp_path, monkeypatch, ["petition", "petitions"])
    hits = check_narration_claims(
        '"There are four petitions," the clerk says.', set(), "")
    assert hits == []


def test_no_campaign_noun_list_means_no_quantity_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("RUBICON_CAMPAIGN_DIR", str(tmp_path))  # no file at all
    hits = check_narration_claims(
        "There is a way to file four petitions here.", set(), "")
    assert hits == []


# ---------------- tripwire negation guard (live-corpus probe find) ----------------

def test_rule_stating_negation_does_not_trip(synthetic_tripwires):
    # "X never eats" asserts the rule — the live corpus probe showed the
    # corrective sentence itself tripping the wire it enforces.
    assert check_tripwires("Thornback never eats.") == []
    assert check_tripwires("Thornback never drinks, of course.") == []
    assert check_tripwires("Thornback passes the bowl without eating.") == []
    assert check_tripwires("Thornback never actually ate a thing.") == []


def test_actual_violation_still_trips_despite_guard(synthetic_tripwires):
    assert check_tripwires("Thornback ate the bread slowly.") != []
    # Negation elsewhere in the sentence must not mask a real violation.
    assert check_tripwires(
        "Thornback ate the bread, never pausing.") != []


# ---------------- meta-only turns don't arm the prose gate ----------------

META_TURN = ("(Yes — 'seam' is on the blacklist as of v10; the carve-outs "
             "for the salt seam and Seam-Between-Strata both pass. The gate "
             "fires at validate, and the Stop-hook scan is the backstop. "
             "Nothing else changed this session.)")

META_TWO_PARAGRAPHS = META_TURN + "\n\n(And to your second question: " \
    "no, the model config didn't change — same cap as the burn study set.)"

NARRATIVE_TURN = ("Kess checks the bolt-count twice and hands the crossbow "
                  "back. The stairwell smells of wet chalk and old brine. "
                  "Below, the winch begins to turn. What do you do? " * 3)


def test_meta_only_predicate():
    assert csc._is_meta_only_response(META_TURN) is True
    assert csc._is_meta_only_response(META_TWO_PARAGRAPHS) is True
    assert csc._is_meta_only_response(NARRATIVE_TURN) is False
    assert csc._is_meta_only_response(META_TURN + "\n\n" + NARRATIVE_TURN) is False
    assert csc._is_meta_only_response("") is False
    assert csc._is_meta_only_response("   ") is False


def test_meta_turn_does_not_arm_prose_gate():
    state = {"validate_prose_called": False, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    blocked, _, updates = csc._check_anti_pattern({}, state, META_TURN)
    assert blocked is False
    assert "validate_prose_required" not in updates, updates


def test_meta_turn_with_banned_phrase_logs_no_catch():
    # Discussing a ban ("the phrase 'her hand finds' is banned") must not
    # log a phantom catch into the analytics.
    meta = ("(Confirming: 'her hand finds' and 'for a long moment' are both "
            "hard-banned — the scan catches them at Stop and validate blocks "
            "them pre-output. That is why the rewrite was forced last turn.)")
    state = {"validate_prose_called": False, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    _, _, updates = csc._check_anti_pattern({}, state, meta)
    assert updates.get("catch_count", 0) == 0, updates


def test_narrative_turn_still_arms_gate():
    state = {"validate_prose_called": False, "session_type": "gameplay",
             "catch_count": 0, "catch_log": {}, "turn_count": 10}
    _, _, updates = csc._check_anti_pattern({}, state, NARRATIVE_TURN)
    assert updates.get("validate_prose_required") is True


def test_meta_turn_is_not_narrative_for_observer():
    state = {"turn_count": 10}
    long_meta = META_TURN + "\n\n" + META_TWO_PARAGRAPHS
    assert csc._is_narrative_turn({}, long_meta, state) is False
    assert csc._is_narrative_turn({}, NARRATIVE_TURN, state) is True
