"""Tests for the in-dialogue factual claim scanner."""

from hooks.dialogue_claim_scanner import (
    extract_dialogue_segments,
    detect_claims,
    detect_claims_in_response,
)


# ------------------------------------------------------------------
# Dialogue extraction
# ------------------------------------------------------------------

def test_extract_simple_quoted_dialogue():
    text = 'She said, "I have known him for many years."'
    segments = extract_dialogue_segments(text)
    assert "I have known him for many years." in segments


def test_extract_smart_quotes():
    text = 'She said, “I have known him for many years.”'
    segments = extract_dialogue_segments(text)
    assert "I have known him for many years." in segments


def test_extract_multiple_dialogue_blocks():
    text = '"First line." Then later, "Second line."'
    segments = extract_dialogue_segments(text)
    assert "First line." in segments
    assert "Second line." in segments


def test_extract_ignores_narrative():
    text = "Amara poured tea while the kettle sang."
    segments = extract_dialogue_segments(text)
    assert segments == []


# ------------------------------------------------------------------
# Claim detection
# ------------------------------------------------------------------

def test_detect_duration_digit():
    claims = detect_claims("I've known him for 79 days.")
    types = [c[0] for c in claims]
    assert "duration" in types
    duration_match = next(c for c in claims if c[0] == "duration")
    assert "79 days" in duration_match[1] or "79" in duration_match[1]


def test_detect_duration_spelled():
    claims = detect_claims("Seventy-nine days I lived with that man.")
    types = [c[0] for c in claims]
    assert "duration" in types
    # NEW: verify the full duration phrase was captured
    duration_claim = next(c for c in claims if c[0] == "duration")
    assert "seventy-nine" in duration_claim[1].lower()
    assert "days" in duration_claim[1].lower()


def test_detect_quantity_digit():
    # "7 of them" is deliberately NOT flagged since the 2026-07-06 idiom
    # guard ("N of ..." reads as speech rhythm) — digit+noun still is.
    claims = detect_claims("There are 7 guards inside.")
    types = [c[0] for c in claims]
    assert "quantity" in types


def test_detect_quantity_spelled():
    claims = detect_claims("She had seven daughters.")
    types = [c[0] for c in claims]
    assert "quantity" in types
    # NEW: noun must appear in claim text
    quantity_claim = next(c for c in claims if c[0] == "quantity")
    assert "daughters" in quantity_claim[1].lower()


def test_detect_quantity_compound_number_keeps_noun():
    """'seventy-nine daughters' must capture both the number and the noun."""
    claims = detect_claims("She had seventy-nine daughters.")
    quantity_claim = next(c for c in claims if c[0] == "quantity")
    assert "seventy-nine" in quantity_claim[1].lower()
    assert "daughters" in quantity_claim[1].lower()


def test_detect_day_reference():
    claims = detect_claims("On Day 122 the rupture happened.")
    types = [c[0] for c in claims]
    assert "date" in types


def test_date_does_not_double_match_as_quantity():
    """'Day 122' must match as date only — not also as quantity."""
    claims = detect_claims("On Day 122 the rupture happened.")
    types = [c[0] for c in claims]
    assert "date" in types
    # The "122 the" false-positive quantity match should be suppressed
    quantity_matches = [c for c in claims if c[0] == "quantity"]
    assert not any("122" in c[1] for c in quantity_matches)


def test_detect_relationship_verb():
    claims = detect_claims("She married him in secret.")
    types = [c[0] for c in claims]
    assert "relationship" in types


def test_detect_no_claims_in_neutral_text():
    claims = detect_claims("The light was warm.")
    assert claims == []


# ------------------------------------------------------------------
# End-to-end response scan
# ------------------------------------------------------------------

def test_scan_response_picks_up_in_dialogue_claim():
    response = 'Amara leaned back. “I’ve known him seventy-nine days,” she said.'
    claims = detect_claims_in_response(response)
    types = [c[0] for c in claims]
    assert "duration" in types


def test_scan_response_ignores_narrative_only():
    response = "Amara leaned back. The light was warm on her shoulders."
    claims = detect_claims_in_response(response)
    # Narrative-only — no dialogue to scan
    assert claims == []


def test_scan_response_mixed_dialogue_and_narrative():
    response = '''Amara leaned back. "I have known him many years," she said.
The cup cooled between them. "Three letters arrived yesterday."'''
    claims = detect_claims_in_response(response)
    types = [c[0] for c in claims]
    # "many years" is vague — duration scanner should still catch "many years"
    assert any(t in {"duration", "quantity"} for t in types)
    # "Three letters arrived yesterday" — quantity claim
    quantity_matches = [c for c in claims if c[0] == "quantity"]
    assert any("three letters" in c[1].lower() or "three" in c[1].lower() for c in quantity_matches)


# ------------------------------------------------------------------
# Conversational-idiom guard (2026-07-06 table report: "one thing,"
# "section three" false positives each cost a rewrite round-trip)
# ------------------------------------------------------------------

def test_idiomatic_number_phrases_not_flagged_as_quantity():
    idioms = [
        '"There is one thing I need from you."',
        '"Give me one moment."',
        '"The two of us will go."',
        '"Section three of the accord forbids it."',
        '"I have told you a hundred times."',
        '"One more word and we leave."',
    ]
    for phrase in idioms:
        claims = detect_claims_in_response(phrase)
        quantity = [c for c in claims if c[0] == "quantity"]
        assert not quantity, f"idiom wrongly flagged: {phrase} -> {quantity}"


def test_real_quantity_claims_still_flagged():
    real = [
        ('"She had seven daughters."', "daughters"),
        ('"Three letters arrived yesterday."', "letters"),
        ('"We lost forty soldiers at the pass."', "soldiers"),
    ]
    for phrase, noun in real:
        claims = detect_claims_in_response(phrase)
        quantity = [c for c in claims if c[0] == "quantity"]
        assert any(noun in c[1].lower() for c in quantity), f"real claim missed: {phrase}"
