"""G1 - gifts.py data integrity + pure helpers (book: CH printed pp. 47-50)."""
from gifts import (GIFT_QUALITY, GIFT_FORM, GIFT_SAMPLE, GLEAM_TEST,
                   roll_gift_name, gleam_outcome)


def test_quality_and_form_are_80_entries_each():
    for table in (GIFT_QUALITY, GIFT_FORM):
        assert sorted(table.keys()) == [(1, 5), (6, 10), (11, 15), (16, 20)]
        for rows in table.values():
            assert len(rows) == 20


def test_quality_entries_unique():
    flat = [e for rows in GIFT_QUALITY.values() for e in rows]
    assert len(set(flat)) == 80


def test_form_has_the_books_stone_duplicate():
    """'Stone' is printed in BOTH the 1-5 and 6-10 bands - book-literal, kept."""
    flat = [e for rows in GIFT_FORM.values() for e in rows]
    assert len(flat) == 80
    assert flat.count("Stone") == 2
    assert len(set(flat)) == 79


def test_book_corner_entries():
    # First and last of each table as printed
    assert GIFT_QUALITY[(1, 5)][0] == "Bashing"
    assert GIFT_QUALITY[(16, 20)][19] == "Subtle"
    assert GIFT_FORM[(1, 5)][0] == "Claw"
    assert GIFT_FORM[(16, 20)][19] == "Entropy"


def test_sample_table_20_rows_and_row_12_geometry_fix():
    assert len(GIFT_SAMPLE) == 20
    # Row 12 column-wrap resolved by PDF word x-positions
    assert GIFT_SAMPLE[12] == ("Devouring Memories", "Inhuman Speed")
    assert GIFT_SAMPLE[1] == ("Mystical Crystal", "Telekinesis")
    assert GIFT_SAMPLE[20] == ("Studied in Lost Archives", "Induce Sleep")


def test_roll_gift_name_forced():
    name, detail = roll_gift_name(None, quality_rolls=(20, 20), form_rolls=(20, 20))
    assert name == "Subtle Entropy"
    assert detail["quality_rolls"] == (20, 20)


def test_roll_gift_name_random_uses_rng():
    rolls = iter([3, 1, 7, 3])  # quality col 3 row 1 -> Bashing; form col 7 row 3 -> Silk
    name, _ = roll_gift_name(lambda a, b: next(rolls))
    assert name == "Bashing Silk"


def test_gleam_outcome_bands():
    assert gleam_outcome(1) is None
    assert gleam_outcome(15) is None
    assert "vision" in gleam_outcome(16)["text"]
    assert gleam_outcome(35)["threat"].startswith("Extradimensional")
    assert gleam_outcome(99) == gleam_outcome(35)  # 35+ cap


def test_gleam_test_covers_16_through_35():
    assert sorted(GLEAM_TEST.keys()) == list(range(16, 36))


def test_threat_rows_carry_clock_metadata():
    for total in (20, 27, 30, 31, 33, 34):
        row = GLEAM_TEST[total]
        assert "threat" in row, total
        assert row["arrival_die"] == 6, total
    # immediate rows: no arrival clock
    assert GLEAM_TEST[35]["arrival_die"] is None
    assert GLEAM_TEST[29]["arrival_die"] is None
