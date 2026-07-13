"""Cacogen d100 Mutation table parity guard (verified vs Crimson Hound, p.40-41).

There is now ONE mutation source of truth: campaign CACOGEN_MUTATIONS.json, read by
generators._roll_cacogen_mutation — the single mint path reused by Proteus level-ups,
Pseudo-Womb-fail resurrection, AND (via roll_mutation_fn injection) the content forge's
roll(action="mutation")/chargen. The forge's former duplicate `cacogen_mutation` table
was retired (mutation consolidation, 2026-06-17), so the two-source drift this test used
to police can no longer occur — guarded below.

Page-fed + certified 2026-06-07: all 100 names are book-exact (the file, previously only
50 unique mutations padded across 100 rolls, was rebuilt from the verified book text).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_FORGE = Path(__file__).resolve().parent.parent / "data" / "content_forge_tables.json"


def _rules_file():
    """The engine-bundled mutation table — the single source of truth the engine
    actually reads (engine-always-wins; relocated from the campaign dir 2026-06-17)."""
    f = Path(__file__).resolve().parents[1] / "data" / "rules" / "CACOGEN_MUTATIONS.json"
    if f.exists():
        return f
    pytest.skip("engine data/rules/CACOGEN_MUTATIONS.json not found")


def _campaign_map():
    d = json.loads(_rules_file().read_text(encoding="utf-8"))
    return {int(k): (v["name"], v["effect"]) for k, v in d.items()}


def test_single_source_is_full_d100_unique():
    m = _campaign_map()
    assert set(m) == set(range(1, 101))
    assert len({n for n, _ in m.values()}) == 100  # was 50 before the 2026-06-07 rebuild


def test_sentinel_book_entries():
    """Spot-pin verified book values, incl. the mechanically load-bearing ones."""
    m = _campaign_map()
    assert m[6] == ("Armoured Skin", "Your body is protected by natural armour. Add +2 to your base AV.")
    assert m[35] == ("Extra Heart", "+2 CON, +5 max HP.")
    assert m[37][0] == "Extra Liver"
    # Exposed Organs is the double-damage source the combat engine cares about
    assert m[31][0] == "Exposed Organs" and "double damage" in m[31][1]
    assert m[1][0] == "Acid Blood" and "caustic" in m[1][1]


def test_no_fabricated_50_table_residue():
    """The old fabricated names (e.g. 'Acidic Blood', 'Adhesive Skin') are gone."""
    names = {n for n, _ in _campaign_map().values()}
    for fake in ("Acidic Blood", "Adhesive Skin", "Alien Metabolism", "Amphibious"):
        assert fake not in names


def test_forge_no_longer_carries_a_duplicate_mutation_table():
    """Consolidation guard: the content forge must NOT re-grow its own cacogen_mutation
    table (that duplicate was the drift risk). Mutations come from the single source via
    roll_mutation_fn injection."""
    tables = json.loads(_FORGE.read_text(encoding="utf-8"))["tables"]
    assert "cacogen_mutation" not in tables
