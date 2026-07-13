"""Tests for _parse_enemy_attack — bestiary attack_damage string parsing.

A2: damage type may be space-separated ("d8 TOX", "d10 beam"), not only
comma-separated ("d8, electrical"). The type must be recognized in both forms
and must NOT be mistaken for an unhandled multi-hit/conditional clause.
"""
import server


def _parse(s):
    return server._parse_enemy_attack(s)


# --- existing comma form + plain dice (must keep working) -------------------

def test_plain_dice():
    assert _parse("d8") == ("d8", "kinetic", "")

def test_comma_type_still_works():
    assert _parse("d8, electrical") == ("d8", "electrical", "")

def test_dice_with_modifier_plain():
    assert _parse("2d6 + 1") == ("2d6 + 1", "kinetic", "")


# --- A2: space-separated damage type ----------------------------------------

def test_space_separated_tox():
    assert _parse("d8 TOX") == ("d8", "tox", "")

def test_space_separated_beam():
    assert _parse("d10 beam") == ("d10", "beam", "")

def test_space_separated_with_modifier():
    assert _parse("2d6 + 1 TOX") == ("2d6 + 1", "tox", "")

def test_space_separated_case_insensitive():
    assert _parse("d12 Blast") == ("d12", "blast", "")


# --- clauses still flagged; type consumed before the clause -----------------

def test_clause_still_noted_no_type():
    dice, dtype, note = _parse("d8 (2x)")
    assert (dice, dtype) == ("d8", "kinetic")
    assert note  # unhandled clause flagged

def test_type_consumed_then_clause_noted():
    dice, dtype, note = _parse("d8 TOX (2x)")
    assert (dice, dtype) == ("d8", "tox")
    assert note  # the "(2x)" remains an unhandled clause

def test_save_based_attack():
    dice, dtype, note = _parse("CON Save vs Amaranthine Venom")
    assert dice is None
    assert note
