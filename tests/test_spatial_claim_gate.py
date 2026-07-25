"""Spatial-claim gate (canon gate hardening spec §F.2, 2026-07-24).

The 2026-07-24 failure: ~10 live turns of fabricated canon geography, none of
which any gate could block because the deterministic detectors only run inside
the opt-in validate_prose path.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.spatial_claim_gate import (  # noqa: E402
    scan_unbacked_spatial, TICKER_HEADER,
)

LEX = {
    "overworld": frozenset({"ceruline", "thyricost"}),
    "site": frozenset({"the fault", "fault", "root gallery"}),
    "regions": frozenset({"central wastes"}),
}
EMPTY_LEX = {"overworld": frozenset(), "site": frozenset(), "regions": frozenset()}


# --- must block ------------------------------------------------------------

def test_bearing_between_canon_places_blocks():
    hits = scan_unbacked_spatial("Ceruline lies due west of here.", [], LEX)
    assert hits and "bearing" in hits[0]


def test_distance_between_canon_places_blocks():
    hits = scan_unbacked_spatial("Thyricost is about 280 miles from Ceruline.", [], LEX)
    assert hits and "distance" in hits[0]


def test_site_containment_blocks():
    hits = scan_unbacked_spatial(
        "The keeper stands at the mouth of the Fault.", [], LEX)
    assert hits and "containment" in hits[0]


def test_the_literal_2026_07_24_string_blocks():
    hits = scan_unbacked_spatial("Ceruline's western approach", [], LEX)
    assert hits, "the literal 2026-07-24 fabrication must not pass"


# --- must pass -------------------------------------------------------------

@pytest.mark.parametrize("text,tool", [
    ("Ceruline lies due west of here.", "geography"),
    ("Ceruline lies due west of here.", "check_canon"),
    ("Thyricost is about 280 miles from Ceruline.", "geography"),
    ("The keeper stands at the mouth of the Fault.", "map"),
    ("Ceruline's western approach", "geography"),
])
def test_satisfying_tool_disarms(text, tool):
    assert scan_unbacked_spatial(text, [tool], LEX) == []


def test_direction_without_a_place_name_never_fires():
    assert scan_unbacked_spatial("The wind came out of the west.", [], LEX) == []


def test_place_and_direction_beyond_the_window_do_not_pair():
    filler = "and the crew moved on through the dust in silence for a while " * 3
    text = f"Ceruline was behind them. {filler} The corridor ran north."
    assert scan_unbacked_spatial(text, [], LEX) == []


def test_fenced_map_render_is_exempt():
    text = "Here is the picture:\n\n```\nCeruline ---- west ---- Thyricost\n```\n"
    assert scan_unbacked_spatial(text, [], LEX) == []


def test_text_after_ticker_header_is_exempt():
    text = "The room settles.\n\n" + TICKER_HEADER + "\nCeruline lies due west."
    assert scan_unbacked_spatial(text, [], LEX) == []


def test_empty_lexicon_fails_open():
    assert scan_unbacked_spatial("Ceruline lies due west of here.", [], EMPTY_LEX) == []
    assert scan_unbacked_spatial("Ceruline lies due west of here.", [], {}) == []


def test_one_violation_per_class_and_tier():
    text = ("Ceruline lies due west. Thyricost lies due east. "
            "Ceruline is north. Thyricost is south.")
    hits = scan_unbacked_spatial(text, [], LEX)
    assert len([h for h in hits if "bearing, overworld" in h]) == 1


def test_block_message_offers_the_honest_exit():
    hits = scan_unbacked_spatial("Ceruline lies due west of here.", [], LEX)
    assert "not established" in hits[0], "the gate must never force invention"


# --- corpus regression (the important one) ---------------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "prose_window_200.jsonl"


@pytest.mark.skipif(not FIXTURE.exists(), reason="live-prose corpus fixture not shipped")
def test_corpus_overworld_bearing_arm_rate_stays_tight():
    """Guards against lexicon growth silently degrading precision.

    Measured 2026-07-24 on 200 real turns: overworld-tier BEARING hits fire on
    12/200 turns, matching the spec's §0.4 probe exactly. Ceiling 15 leaves
    headroom; if a future change pushes past it, this fails loudly and forces a
    retune rather than letting the noise ride into live play.
    """
    from conftest import REAL_CAMPAIGN_DIR
    from hooks.place_lexicon import load_place_lexicon
    lex = load_place_lexicon(REAL_CAMPAIGN_DIR)
    if not lex["overworld"]:
        pytest.skip("live campaign lexicon unavailable")

    armed = 0
    total = 0
    for line in FIXTURE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        total += 1
        text = json.loads(line).get("text", "")
        hits = scan_unbacked_spatial(text, [], lex)
        if any("bearing, overworld" in h for h in hits):
            armed += 1
    assert total == 200
    assert armed <= 15, f"overworld bearing arm rate regressed to {armed}/200"
