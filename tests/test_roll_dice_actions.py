"""First-class ad-hoc dice: roll(action="check"/"save"/"damage") (Fizzek 2b).

Before this, the DM shelled out to dice_roller.py via Bash for every save, check,
and damage roll — invisible to the player, unlogged, with advantage/DC logic living
in the DM's head. Now the engine owns the canonical path: d20+ability vs DC (Vaarn
standard 15, advantage/disadvantage, nat 20/1 auto), and arbitrary-notation rolls
for damage/HP costs. Same family as the player-roll routing in Bugs 9/10.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


# --- saves / checks -----------------------------------------------------------

def test_save_with_flat_bonus_passes_and_fails_on_dc(monkeypatch):
    # Force d20=15; 15 + 2 = 17 vs DC 15 -> PASS.
    monkeypatch.setattr(server.dice, "roll",
                        lambda sides, n=1, mod=0: {"total": 15 + mod, "rolls": [15],
                                                   "modifier": mod, "breakdown": ""})
    out = server._roll_ability_check(kind="save", bonus=2, dc=15, reason="CON vs toxin")
    assert "PASS" in out and "CON vs toxin" in out and "DC 15" in out
    # Same roll vs a harder DC 18 -> 17 < 18 -> FAIL.
    out2 = server._roll_ability_check(kind="save", bonus=2, dc=18)
    assert "FAIL" in out2


def test_check_reads_ability_off_the_sheet(monkeypatch):
    data = {"characters": {"fizzek": {"name": "Fizzek",
            "abilities": {"INT": {"current": 3}}}}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server.dice, "roll",
                        lambda sides, n=1, mod=0: {"total": 12 + mod, "rolls": [12],
                                                   "modifier": mod, "breakdown": ""})
    out = server._roll_ability_check(kind="check", ability="INT", character="Fizzek", dc=15)
    assert "Fizzek's INT +3" in out
    assert "PASS" in out          # 12 + 3 = 15 >= 15


def test_natural_20_auto_passes_and_natural_1_auto_fails(monkeypatch):
    monkeypatch.setattr(server.dice, "roll",
                        lambda sides, n=1, mod=0: {"total": 20 + mod, "rolls": [20],
                                                   "modifier": mod, "breakdown": ""})
    # nat 20 passes even against an absurd DC and a negative modifier.
    out = server._roll_ability_check(kind="save", bonus=-5, dc=30)
    assert "PASS" in out and "NATURAL 20" in out

    monkeypatch.setattr(server.dice, "roll",
                        lambda sides, n=1, mod=0: {"total": 1 + mod, "rolls": [1],
                                                   "modifier": mod, "breakdown": ""})
    out2 = server._roll_ability_check(kind="save", bonus=10, dc=2)
    assert "FAIL" in out2 and "NATURAL 1" in out2


def test_advantage_routes_to_advantage_roll(monkeypatch):
    called = {}
    def _adv(sides, mod=0):
        called["adv"] = True
        return {"total": 18 + mod, "rolls": [18], "modifier": mod,
                "breakdown": "", "other_roll": 4}
    monkeypatch.setattr(server.dice, "roll_with_advantage", _adv)
    out = server._roll_ability_check(kind="save", bonus=0, dc=15, advantage=True)
    assert called.get("adv") is True
    assert "advantage" in out and "other d20 4" in out


def test_named_ability_without_character_asks_for_one():
    out = server._roll_ability_check(kind="check", ability="DEX")
    assert "character=" in out or "bonus=" in out


def test_missing_character_errors():
    out = server._roll_ability_check(kind="check", ability="INT", character="ghost")
    # _load_characters is the real one here; "ghost" won't resolve -> a clear miss,
    # not a crash.
    assert "not found" in out.lower() or "could not load" in out.lower()


# --- damage / notation --------------------------------------------------------

def test_damage_rolls_notation(monkeypatch):
    monkeypatch.setattr(server.dice, "roll_notation",
                        lambda expr: {"total": 14, "breakdown": "3d8 = [4,6,4] = 14"})
    out = server._roll_damage(notation="3d8", reason="shotgun")
    assert "14" in out and "shotgun" in out


def test_damage_requires_notation():
    out = server._roll_damage(notation=None)
    assert "notation" in out


def test_damage_bad_notation_is_graceful(monkeypatch):
    def _boom(expr):
        raise ValueError("bad expr")
    monkeypatch.setattr(server.dice, "roll_notation", _boom)
    out = server._roll_damage(notation="garbage")
    assert "Could not" in out
