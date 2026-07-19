"""Blacklist v9 mutation-family patterns (2026-07-19 Thyricost audit).

The prose migrated off the banned surface forms onto grammatically-adjacent
variants ('the way X <verbs>' 66x, participle/bare-appositive cat-6 24x,
'a very long time' 19x, re-lexicalized pause-as-actor 5x). These tests pin
the new structural_patterns against transcript-positive examples and a
false-positive guard set, THROUGH the real validate_prose scanner.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402

POSITIVES = [
    # the-way-X-verbs epistemic simile
    "She goes quiet the way archives go quiet.",
    "He reads the rim the way Vela reads maps.",
    "The room returns slowly, the way weather clears.",
    # participle variant of the who/that template
    "It is the gesture of a woman preparing a surface for work.",
    "She hands it over with the reluctance of a child handing over a pet.",
    # bare portent appositive
    "Dim amber, steady, patient, the color of an evacuation notice no one ever read.",
    "He says it in the tone of a man at a wedding.",
    # mutated duration padding
    "She looks at it for a very long time.",
    "A pause the length of a breath.",
    "They stand there a long while.",
    # re-lexicalized pause-as-actor
    "A stillness with contents.",
    "Nobody speaks. The afternoon does the work.",
]

FALSE_POSITIVE_GUARDS = [
    "The rest of the party waits by the edge of the pit.",
    "The way west opens onto blue sand.",
    "She leads the way through the arch.",
    "The way back to camp is shorter at night.",
    "The way out is blocked by fallen chitin.",
    "He measures the length of the corridor with paces.",
]


def _structural_hits(text: str) -> list:
    """Scan text with the compiled structural patterns directly — no semantic
    judges, no API calls, no NPC/backstory layers."""
    _, _, st_patterns = server._load_prose_patterns()
    return [(cat, m.group(0)) for pat, cat in st_patterns
            for m in pat.finditer(text)]


def test_all_positive_examples_flagged():
    for text in POSITIVES:
        hits = _structural_hits(text)
        assert hits, f"structural patterns failed to flag: {text!r}"


def test_false_positive_guards_clean():
    new_cats = {"Characterization", "Transition duration-padding", "The Pause"}
    for text in FALSE_POSITIVE_GUARDS:
        bad = [h for h in _structural_hits(text) if h[0] in new_cats]
        assert not bad, f"False positive on clean text {text!r}: {bad}"


def test_refrains_now_use_sparingly():
    import json
    data = json.loads((Path(__file__).resolve().parent.parent
                       / "hooks" / "blacklist.json").read_text(encoding="utf-8"))
    for phrase in ("four thousand years", "through the bond"):
        assert phrase in data["use_sparingly"]
    assert data["_meta"]["version"] >= 9
