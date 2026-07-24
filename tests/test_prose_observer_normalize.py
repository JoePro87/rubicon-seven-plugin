"""Fix 2b — _normalize_category case-folds to the canonical VIOLATION_CATEGORIES.

Haiku returns category labels in inconsistent casing (e.g. "Density drift"
where the enum key is "Density Drift"), which split analytics into two buckets
for one family. Normalization must coerce case to the canonical enum casing.
"""

import sys
from pathlib import Path

HOOKS_DIR = str(Path(__file__).parent.parent / "hooks")
if HOOKS_DIR not in sys.path:
    sys.path.insert(0, HOOKS_DIR)

import prose_observer as po


def test_case_fold_to_canonical():
    """Lower/mixed-case variants fold to the exact VIOLATION_CATEGORIES key."""
    assert po._normalize_category("Density drift") == "Density Drift"
    assert po._normalize_category("density drift") == "Density Drift"
    assert po._normalize_category("DENSITY DRIFT") == "Density Drift"
    assert po._normalize_category("Reaction shot") == "Reaction Shot"
    assert po._normalize_category("the pause") == "The Pause"


def test_canonical_casing_is_idempotent():
    """Already-canonical labels pass through unchanged."""
    for cat in po.VIOLATION_CATEGORIES:
        assert po._normalize_category(cat) == cat


def test_long_label_map_still_applies_then_folds():
    """The long-label normalization map still applies, and its output folds to
    the canonical enum casing."""
    assert po._normalize_category("Transition duration-padding") == "Transition"
    assert po._normalize_category("The Pause as actor") == "The Pause"
    assert po._normalize_category("Voice modulation tags") == "Voice Modulation"


def test_unknown_category_passes_through():
    """A category not in the enum is returned as-is (stripped)."""
    assert po._normalize_category("Totally Made Up") == "Totally Made Up"
    assert po._normalize_category("  Unknown  ") == "Unknown"


def test_non_string_returns_unknown():
    assert po._normalize_category(None) == "Unknown"
    assert po._normalize_category(123) == "Unknown"
