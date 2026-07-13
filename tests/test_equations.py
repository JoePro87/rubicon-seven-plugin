"""G2 Hypergeometric Equations - certified d100 + codex appearances d20.

Spec: docs/superpowers/specs/2026-06-13-g2-equations-design.md
Book: CH preview PDF pdfplumber pp.63, 65-66 (printed pp.57, 59-60).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestEquationTablePins:
    def test_forty_entries(self):
        assert len(server.HYPERGEOMETRIC_EQUATIONS) == 40

    def test_band_coverage_exact(self):
        """1-100 exactly once (R-G2a fixes the book's 43-45/44-46 overlap:
        even split per the R-B3a precedent)."""
        seen = {}
        for idx, row in server.HYPERGEOMETRIC_EQUATIONS.items():
            lo, hi = row["d100"]
            for v in range(lo, hi + 1):
                assert v not in seen, f"{v}: rows {seen[v]} and {idx}"
                seen[v] = idx
        assert sorted(seen) == list(range(1, 101))

    def test_r_g2a_band_fix(self):
        t = server.HYPERGEOMETRIC_EQUATIONS
        assert t[15]["name"] == "Return Fixed Coordinates"
        assert t[15]["d100"] == (43, 44)
        assert t[16]["name"] == "Return Random Coordinates"
        assert t[16]["d100"] == (45, 46)
        assert t[17]["name"] == "Singularity" and t[17]["d100"] == (47, 50)

    def test_verbatim_spot_pins(self):
        t = server.HYPERGEOMETRIC_EQUATIONS
        assert t[1]["name"] == "Antithetical Copy" and t[1]["d100"] == (1, 3)
        assert "[INT] hours" in t[1]["effect_text"]
        assert "STR save vs 10+[INT]" in t[17]["effect_text"]
        assert t[32]["name"] == "Map of Fate"
        assert "Hypergeometric Mishap" in t[32]["effect_text"]
        assert t[40]["name"] == "Web" and t[40]["d100"] == (98, 100)

    def test_int_notation_preserved(self):
        assert sum("[INT]" in r["effect_text"]
                   for r in server.HYPERGEOMETRIC_EQUATIONS.values()) >= 30


class TestCodexAppearancePins:
    def test_twenty_entries(self):
        assert sorted(server.CODEX_APPEARANCES) == list(range(1, 21))

    def test_spot_pins(self):
        a = server.CODEX_APPEARANCES
        assert "goblet" in a[1] and "drinks in light" in a[1]
        assert "toad" in a[2]
        assert "Mobius" in a[20]          # ASCII-normalised from the book
        assert "Fallen Autarchy" in a[19]


class TestGenerateCodex:
    def test_forced_equation_roll(self):
        out = server._generate_codex(roll=47)
        assert "Singularity" in out and "47-50" in out
        assert "[INT]" in out                  # notation preserved on the card

    def test_r_g2a_bands_live(self):
        assert "Return Fixed Coordinates" in server._generate_codex(roll=44)
        assert "Return Random Coordinates" in server._generate_codex(roll=45)

    def test_pushes_codex_add(self):
        out = server._generate_codex(roll=98)
        assert 'codex(' in out and 'action="add"' in out
        assert "Web" in out

    def test_appearance_included(self):
        seq = iter([98, 1])                    # d100 then d20
        out = server._generate_codex(
            rng=lambda a, b: next(seq))
        assert "drinks in light" in out and "Web" in out

    def test_bad_roll_rejected(self):
        assert "1-100" in server._generate_codex(roll=101)
