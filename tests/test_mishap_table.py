"""The d20 Hypergeometric Mishaps table must match the book (CH p.64,
extraction batch_04). The previous in-engine table was largely invented -
caught 2026-06-12 during the E4 roadmap audit ('Temporal Echo / permanent
madness' does not exist in the book)."""
import server

BOOK_NAMES = {
    1: "Antithesis", 2: "Brainstorm", 3: "Chromashadow", 4: "Codex Collapse",
    5: "Entropy-withered", 6: "Giant Item", 7: "Gigantism",
    8: "Inverted Anatomy", 9: "Inverted Fate", 10: "Labyrinth Pox",
    11: "Lost Past", 12: "Petrified", 13: "Planeyfied", 14: "Quantum Daemon",
    15: "Revelation", 16: "Shrunken Head", 17: "Space-Time Vortex",
    18: "Spirit Hand", 19: "The Yellow Door", 20: "Tiny Item",
}


def test_mishap_table_matches_book_names():
    assert {k: v["name"] for k, v in server.HYPERGEOMETRIC_MISHAPS.items()} == BOOK_NAMES


def test_no_hallucinated_madness():
    blob = str(server.HYPERGEOMETRIC_MISHAPS).lower()
    assert "madness" not in blob and "temporal echo" not in blob


def test_pox_entry_pushes_the_disease_tool():
    assert 'affliction(kind="disease", action="apply"' in server.HYPERGEOMETRIC_MISHAPS[10]["effect"]


def test_mishap_roll_renders(monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 17)
    out = server._codex_mishap_roll()
    assert "Space-Time Vortex" in out and "rolled 17" in out
