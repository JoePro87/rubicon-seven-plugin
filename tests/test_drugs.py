"""B4 Drugs - certified d20 generator table (CH printed p.45).

Spec: docs/superpowers/specs/2026-06-13-b4-drugs-design.md
R-B4a: addiction DEFERRED until the full edition - no mechanics here.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestDrugTablePins:
    def test_four_columns_twenty_rows(self):
        t = server.VAARNISH_DRUGS
        for col in ("hue", "form", "ingested_by", "effect"):
            assert sorted(t[col]) == list(range(1, 21)), col

    def test_verbatim_oddities_are_book_real(self):
        t = server.VAARNISH_DRUGS
        assert t["hue"][19] == "Octarine" and t["hue"][20] == "Ulfire"
        assert t["ingested_by"][15] == "Drunk in Urine"
        assert t["ingested_by"][19] == "Only Affects Synths"
        assert t["effect"][14] == "Behold Azathoth"
        assert t["effect"][18] == "Can't Stop Dancing"

    def test_spot_pins(self):
        t = server.VAARNISH_DRUGS
        assert t["hue"][1] == "Red" and t["form"][1] == "Sugar"
        assert t["ingested_by"][1] == "Snorting" and t["effect"][1] == "Euphoria"
        assert t["form"][15] == "Biotech"
        assert t["ingested_by"][13] == "Burn and Watch the Flames"
        assert t["effect"][9] == "Anxious Sweats"


class TestGenerateDrug:
    def test_forced_rolls_deterministic(self):
        out = server._generate_drug(rolls=[8, 8, 8, 1, 14])
        assert "Viridian Slime" in out
        assert "Hold on Tongue" in out
        assert "Euphoria" in out and "Behold Azathoth" in out

    def test_double_effect_collapses_with_note(self):
        out = server._generate_drug(rolls=[1, 1, 1, 5, 5])
        assert out.count("No Pain") == 1
        assert "rolled twice" in out

    def test_pushes_condition_apply(self):
        out = server._generate_drug(rolls=[1, 1, 1, 1, 2])
        assert 'condition(' in out and 'action="apply"' in out
        assert "Euphoria + Paranoia" in out

    def test_rolls_as_comma_string(self):
        out = server._generate_drug(rolls="19,20,15,14,17")
        assert "Octarine Tooth" in out and "Drunk in Urine" in out

    def test_random_path_runs(self):
        seq = iter([3, 7, 12, 5, 9])
        out = server._generate_drug(rng=lambda a, b: next(seq))
        assert "Yellow Pearl" in out and "Stare at It" in out
        assert "No Pain" in out and "Anxious Sweats" in out
