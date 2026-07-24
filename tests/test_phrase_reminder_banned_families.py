"""Fix 1 — banned-pattern prime is built FROM blacklist.json at every tier.

The old prime was a hand-authored string literal that (a) drifted from
blacklist.json and (b) only rendered at Tier 3. These tests pin the new
behaviour: the v9 structural mutation FAMILIES drive the prime, it renders at
all tiers, and the stale sentinel text is gone.
"""

import sys
from pathlib import Path

# Hooks directory isn't on the default path
HOOKS_DIR = str(Path(__file__).parent.parent / "hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

import phrase_reminder as pr


# A structural_patterns fixture mirroring the shape of the live v9 families,
# including the "the way X <verbs>" mutation family the 2026-07-19 audit added.
STRUCTURAL = [
    {"pattern": "x", "category": "Negation-Correction",
     "description": "Not X. [But] the/a/something Y — negation-correction split"},
    {"pattern": "x", "category": "Characterization",
     "description": "The [quality] of a/someone/something who/that — stock formula"},
    {"pattern": "x", "category": "Characterization",
     "description": "'the way X <verbs>' epistemic simile — cat-6 characterization template"},
    {"pattern": "x", "category": "The Pause",
     "description": "re-lexicalized pause-as-actor ('a stillness with contents')"},
]

# The exact sentinel fragments the retired hardcoded literal used to carry.
OLD_SENTINELS = [
    "no silence-as-actor",
    "no vocal-adjective delivery tags",
    "breathing-as-shock",
]


def test_full_tier_contains_v9_family_gloss():
    """High tier renders the 'the way X <verbs>' mutation-family gloss."""
    result = pr.build_reminder(
        catch_count=8, catch_log={"phrase": 8},
        blacklisted=["goes still", "voice drops"], sparingly=[],
        session_vocab=[], scene_type="intimate", structural=STRUCTURAL,
    )
    assert "BANNED PATTERNS:" in result
    assert "the way X <verbs>" in result
    # Category headers are present (families, not a flat phrase list)
    assert "Characterization:" in result
    assert "Negation-Correction:" in result


def test_full_tier_drops_old_hardcoded_sentinel():
    """The retired hand-authored literal's sentinel text no longer appears."""
    result = pr.build_reminder(
        catch_count=9, catch_log={"phrase": 9},
        blacklisted=["goes still"], sparingly=[],
        session_vocab=[], scene_type="combat", structural=STRUCTURAL,
    )
    for sentinel in OLD_SENTINELS:
        assert sentinel not in result, f"stale sentinel still present: {sentinel!r}"


def test_families_render_at_clean_tier():
    """Clean session (0 catches) still surfaces the families marker — not
    Tier-3-only. Uses the compact 'BANNED FAMILIES' marker (not the full dump)."""
    result = pr.build_reminder(
        catch_count=0, catch_log={},
        blacklisted=["goes still"], sparingly=[],
        session_vocab=[], scene_type="settlement", structural=STRUCTURAL,
    )
    assert "BANNED FAMILIES" in result
    assert "Characterization" in result
    # Compact marker only — the full glossed dump stays Tier-3
    assert "BANNED PATTERNS:" not in result


def test_families_render_at_low_tier():
    """1-5 catches surfaces the families marker too (minimal form)."""
    result = pr.build_reminder(
        catch_count=3, catch_log={"bad": 2},
        blacklisted=["goes still"], sparingly=[],
        session_vocab=[], scene_type="social", structural=STRUCTURAL,
    )
    assert "BANNED FAMILIES" in result
    assert "BANNED PATTERNS:" not in result


def test_families_deduped_by_category():
    """Two Characterization entries collapse to one category, both glosses kept."""
    fams = pr._banned_families(STRUCTURAL)
    cats = [c for c, _ in fams]
    assert cats.count("Characterization") == 1
    char_glosses = dict(fams)["Characterization"]
    assert any("the way X <verbs>" in g for g in char_glosses)
    assert any("who/that" in g for g in char_glosses)


def test_prime_built_from_live_blacklist_when_structural_omitted():
    """When structural is not passed, build_reminder loads the live blacklist.json
    families (single source of truth) rather than a hand-authored list."""
    live = pr._load_structural_patterns()
    assert live, "live blacklist.json should carry structural_patterns"
    result = pr.build_reminder(
        catch_count=8, catch_log={"p": 8},
        blacklisted=["goes still"], sparingly=[],
        session_vocab=[], scene_type="intimate",  # structural omitted -> auto-load
    )
    # The live blacklist carries the 'the way X <verbs>' family (v9 audit).
    assert "the way X" in result


def test_sparingly_only_surfaced_when_used_this_session():
    """use_sparingly entries surface ONLY when already spent this session; the
    full list is never dumped."""
    sparingly = ["weighted pause", "small smile", "half-smile"]
    # None used -> no SPARINGLY line
    clean = pr.build_reminder(
        catch_count=8, catch_log={"p": 8},
        blacklisted=["goes still"], sparingly=sparingly,
        session_vocab=[], scene_type="intimate", structural=STRUCTURAL,
    )
    assert "SPARINGLY" not in clean
    # One used -> only that one surfaces
    used = pr.build_reminder(
        catch_count=8, catch_log={"p": 8},
        blacklisted=["goes still"], sparingly=sparingly,
        session_vocab=["weighted pause"], scene_type="intimate", structural=STRUCTURAL,
    )
    assert "SPARINGLY" in used
    assert "weighted pause" in used
    assert "half-smile" not in used  # unused entries not dumped
