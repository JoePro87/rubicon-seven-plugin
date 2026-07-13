"""Death-condition guard (`server._check_death_conditions`).

Three independent ways a character dies in Vaarn. This is a pure function over
a character dict, returning (is_dead, reason). A regression here either kills a
PC who should live or fails to flag a fatality — both unacceptable mid-combat.
Pins all three triggers and the healthy case.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _char(**ov):
    c = {
        "name": "Mort",
        "hp": {"current": 10, "max": 20},
        "abilities": {
            "STR": {"current": 0, "base": 0},
            "CON": {"current": 1, "base": 1},
        },
        "wounds_slots_used": 0,
        "slot_capacity_total": 10,
    }
    c.update(ov)
    return c


def test_healthy_character_is_not_dead():
    dead, reason = server._check_death_conditions(_char())
    assert dead is False and reason is None


def test_hp_at_minus_20_is_fatality():
    dead, reason = server._check_death_conditions(_char(hp={"current": -20, "max": 20}))
    assert dead is True and "FATALITY" in reason


def test_hp_minus_19_survives_but_minus_20_dies():
    assert server._check_death_conditions(_char(hp={"current": -19, "max": 20}))[0] is False
    assert server._check_death_conditions(_char(hp={"current": -25, "max": 20}))[0] is True


def test_all_slots_filled_with_wounds_is_death():
    dead, reason = server._check_death_conditions(
        _char(wounds_slots_used=10, slot_capacity_total=10)
    )
    assert dead is True and "wounds" in reason.lower()


def test_ability_below_minus_10_is_death():
    c = _char()
    c["abilities"]["STR"] = {"current": -11, "base": 0}
    dead, reason = server._check_death_conditions(c)
    assert dead is True and "STR" in reason
    # exactly -10 survives (strict < -10)
    c["abilities"]["STR"] = {"current": -10, "base": 0}
    assert server._check_death_conditions(c)[0] is False
