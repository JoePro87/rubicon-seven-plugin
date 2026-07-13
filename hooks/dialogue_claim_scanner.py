"""Detect factual claims inside dialogue.

This module is the in-dialogue half of the fabrication gate. It scans
quoted dialogue (straight and smart quotes) for:
  - Duration claims  ("seventy-nine days", "two weeks")
  - Quantity claims  ("seven daughters", "three letters")
  - Date references  ("Day 122", "the seventeenth")
  - Relationship verbs ("married", "betrayed", "lived with")

Each detected claim returns (claim_type, claim_text) tuples that the
fabrication gate cross-references against the distillation cache.
"""

import re


# Dialogue extractor handles three quote styles:
#   - Straight:     "..."   (U+0022)
#   - Smart double: “...”   (U+201C / U+201D)
#   - Smart single: ‘...’   (U+2018 / U+2019)
_DIALOGUE_RE = re.compile(
    r'(?:"([^"]*)"|“([^”]*)”|‘([^’]*)’)',
    re.DOTALL,
)


# Build the number words list with compounds FIRST so longer forms match
# before their base forms (e.g. "seventy-nine" before "seventy").
_TENS = ["twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
_ONES = ["one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
_COMPOUNDS = [f"{t}-{o}" for t in _TENS for o in _ONES]
_BASE_NUMBERS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety",
    "hundred", "thousand", "million",
    "many", "several", "few", "countless", "dozens", "hundreds", "thousands",
]
# COMPOUNDS first so "seventy-nine" matches before "seventy"
_NUMBER_WORDS = r"(?:" + "|".join(_COMPOUNDS + _BASE_NUMBERS) + r")"

# Duration: number + time unit
_DURATION_RE = re.compile(
    rf'\b(?:\d+|{_NUMBER_WORDS})[\s-]+'
    r'(?:days?|weeks?|months?|years?|hours?|minutes?|seconds?|'
    r'decades?|centuries|millennia)\b',
    re.IGNORECASE,
)

# Conversational-idiom guard (2026-07-06 table report): "one thing," "the two
# of us," "section three of the accord" are speech rhythm, not testimony, and
# every false positive costs a full rewrite round-trip. So quantity detection
# skips "zero"/"one" as triggers (never claim-shaped on their own) and skips
# any number followed by one of these continuations. Duration/date detection
# is untouched — "one year" is still a checkable claim.
_IDIOM_CONTINUATIONS = (
    "of", "or", "and", "more", "less", "last", "first", "other", "others",
    "thing", "things", "moment", "moments", "way", "ways", "word", "words",
    "question", "questions", "step", "steps", "breath", "breaths",
    "time", "times", "chance", "chances",
)
_QTY_NUMBER_WORDS = r"(?:" + "|".join(
    _COMPOUNDS + [n for n in _BASE_NUMBERS if n not in ("zero", "one")]
) + r")"

# Quantity: number + noun (not a time unit, not an idiom continuation)
_QUANTITY_RE = re.compile(
    rf'\b(?:\d+|{_QTY_NUMBER_WORDS})[\s-]+'
    r'(?:(?!days?\b|weeks?\b|months?\b|years?\b|hours?\b|minutes?\b|seconds?\b|'
    r'decades?\b|centuries\b|millennia\b|'
    + r'|'.join(rf'{w}\b' for w in _IDIOM_CONTINUATIONS) +
    r')[a-z]+)\b',
    re.IGNORECASE,
)

# Day reference: "Day 122", "the 17th"
_DATE_RE = re.compile(
    r'\b(?:Day\s+\d+|the\s+\d+(?:st|nd|rd|th))\b',
    re.IGNORECASE,
)

# Relationship verbs (with context window)
_RELATIONSHIP_VERBS = {
    # Dramatic
    "married", "betrayed", "killed", "loved", "raised", "abandoned",
    "saved", "served", "fought", "lived with", "lived alongside",
    "stole from", "promised", "swore to", "deceived",
    # Common (added)
    "trusted", "knew", "met", "feared", "hated", "trained",
    "followed", "hired", "worked with", "worked for", "taught",
    "studied with", "studied under", "apprenticed to",
}
_RELATIONSHIP_RE = re.compile(
    r'\b(' + '|'.join(re.escape(v) for v in sorted(_RELATIONSHIP_VERBS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)


def extract_dialogue_segments(text):
    """Return a list of the contents of all quoted dialogue in text.

    Handles both straight quotes and smart quotes. Returns segments without
    the surrounding quote characters.
    """
    segments = []
    for match in _DIALOGUE_RE.finditer(text):
        # match has three groups (one per quote style); only one will be populated
        for group in match.groups():
            if group is not None and group.strip():
                segments.append(group)
                break
    return segments


def detect_claims(text):
    """Scan a single dialogue segment for factual claims.

    Returns list of (claim_type, claim_text) tuples.
    claim_type is one of: 'duration', 'quantity', 'date', 'relationship'.
    """
    claims = []

    # Duration first (guards quantity)
    duration_spans = []
    for m in _DURATION_RE.finditer(text):
        claims.append(("duration", m.group(0)))
        duration_spans.append((m.start(), m.end()))

    # Date second (also guards quantity)
    date_spans = []
    for m in _DATE_RE.finditer(text):
        claims.append(("date", m.group(0)))
        date_spans.append((m.start(), m.end()))

    # Quantity, skipping spans covered by duration OR date
    for m in _QUANTITY_RE.finditer(text):
        if any(s <= m.start() < e for s, e in duration_spans):
            continue
        if any(s <= m.start() < e for s, e in date_spans):
            continue
        claims.append(("quantity", m.group(0)))

    # Relationship verbs with surrounding context
    for m in _RELATIONSHIP_RE.finditer(text):
        start = max(0, m.start() - 60)
        end = min(len(text), m.end() + 60)
        context = text[start:end].strip()
        claims.append(("relationship", context))

    return claims


def detect_claims_in_response(response_text):
    """Extract all dialogue from the response and detect claims in each segment.

    This is the entry point the fabrication gate calls.
    """
    all_claims = []
    for segment in extract_dialogue_segments(response_text):
        all_claims.extend(detect_claims(segment))
    return all_claims
