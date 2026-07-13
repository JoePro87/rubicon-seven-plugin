"""B5 Alchemy - reference card + Crucible flavor generator.

Spec: docs/superpowers/specs/2026-06-13-b5-alchemy-design.md
R-B5a/b/c: reference build - harvest+brew are DM-manual.
Book: CH preview PDF pdfplumber pp.57-58 (printed pp.51-52).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class TestCrucibleTables:
    def test_twenty_each(self):
        assert sorted(server.CRUCIBLE_QUALITIES) == list(range(1, 21))
        assert sorted(server.CRUCIBLE_SHAPES) == list(range(1, 21))

    def test_spot_pins(self):
        assert server.CRUCIBLE_QUALITIES[1] == "Ultraviolet"
        assert server.CRUCIBLE_QUALITIES[20] == "Lurid"
        assert server.CRUCIBLE_SHAPES[1] == "Cauldron"
        assert server.CRUCIBLE_SHAPES[7] == "Pyramid"
        assert server.CRUCIBLE_SHAPES[17] == "Barrel"
        assert server.CRUCIBLE_SHAPES[20] == "Eyeball"


class TestGenerateCrucible:
    def test_forced_rolls(self):
        out = server._generate_crucible(rolls=[7, 7])
        assert "Quicksilver Pyramid" in out

    def test_rolls_string(self):
        assert "Ultraviolet Cauldron" in server._generate_crucible(rolls="1,1")

    def test_random_path(self):
        seq = iter([20, 20])
        out = server._generate_crucible(rng=lambda a, b: next(seq))
        assert "Lurid Eyeball" in out


class TestAlchemyCard:
    def test_lookup_alchemy_nonempty(self):
        out = server.lookup(action="alchemy")
        assert isinstance(out, str) and len(out) > 400

    def test_all_essence_type_pairings_present(self):
        out = server.lookup(action="alchemy")
        for essence, ctype in [
                ("Blood", "Biological"), ("Blue Ikor", "Synthetic"),
                ("Mycelium", "Fungal"), ("Psychespinal Fluid", "Psychic"),
                ("Manifold Marrow", "Hypergeometric"),
                ("Living Dust", "Mineral"), ("Paradox Bile", "Outsider")]:
            assert essence in out and ctype in out

    def test_brewing_different_types_rule(self):
        out = server.lookup(action="alchemy")
        assert "different types" in out
        assert "Exploration Turn" in out          # POT ET brew time

    def test_potency_calibration(self):
        out = server.lookup(action="alchemy")
        for marker in ("POT 1", "POT 3", "POT 5"):
            assert marker in out

    def test_antidote_mapping_exact(self):
        out = server.lookup(action="alchemy")
        for pair in ("d6 TOX", "d8", "d10", "d12", "d20"):
            assert pair in out
        assert "POT 1" in out and "POT 5" in out

    def test_synth_mineral_cannot_drink(self):
        out = server.lookup(action="alchemy")
        assert "Synthetic" in out and "Mineral" in out and "cannot" in out.lower()

    def test_dispatch_invalid_unchanged(self):
        out = server.lookup(action="nonsense", query="x")
        assert "Invalid action" in out and "alchemy" in out
