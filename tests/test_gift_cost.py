"""Mystic Gift HP-cost scaling guard (`server._gift_calculate_cost`).

The cost die scales by the TARGET's level (not the caster's). Gifts always
hit but cost HP equal to the die roll; an off-by-one in the band boundaries
would mis-price every communion (this is the function the DM calls before
spending the caster's HP on Dissolving Thread). Pins the exact d6/d8/d10/d12/d20
band edges from the rulebook.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _die(level):
    out = server._gift_calculate_cost(level)
    # "  HP Cost: dX" — the cost die is the load-bearing value
    line = next(l for l in out.splitlines() if "HP Cost:" in l)
    return line.split("HP Cost:")[1].strip()


def test_band_boundaries_exact():
    # <=2 -> d6, 3-4 -> d8, 5-6 -> d10, 7-8 -> d12, >8 -> d20
    expected = {
        1: "d6", 2: "d6",
        3: "d8", 4: "d8",
        5: "d10", 6: "d10",
        7: "d12", 8: "d12",
        9: "d20", 12: "d20", 99: "d20",
    }
    for level, die in expected.items():
        assert _die(level) == die, f"level {level} -> {_die(level)} (want {die})"


def test_cost_die_matches_heal_die():
    """HP cost and Damage/Heal use the same die (die+PSY for the effect)."""
    out = server._gift_calculate_cost(4)
    assert "HP Cost: d8" in out
    assert "Damage/Heal: d8+PSY" in out


def test_always_hits_reminder_present():
    assert "always hit" in server._gift_calculate_cost(1).lower()
