"""C16 — table-vault-merchants was missing rolls 1-5 (half the d10 table).

The five book entries (CH printed p.117: Callista the Martyr, Fairfrond,
Doormonger Arstan, Razorhair Jo, Mauve the Alchemist) are now transcribed
faithfully into data/rules/rulebook/tables.json, the self-admitting 'partial'
field is gone, and the table is a complete d10 (rolls 1-10).
"""
import json

import engine_core


def _table():
    d = json.loads(engine_core.read_rules_data("rulebook/tables.json"))
    return next(t for t in d["rolling_tables"] if t["id"] == "table-vault-merchants")


def test_complete_d10_no_gaps():
    t = _table()
    assert t["die"] == "d10"
    assert [e["roll"] for e in t["entries"]] == list(range(1, 11))


def test_partial_field_removed():
    assert "partial" not in _table()


def test_missing_five_present_by_name():
    names = {e["name"] for e in _table()["entries"]}
    for n in (
        "Callista the Martyr",
        "Fairfrond",
        "Doormonger Arstan",
        "Razorhair Jo",
        "Mauve the Alchemist",
    ):
        assert n in names, n


def test_new_entries_have_full_columns():
    for e in _table()["entries"][:5]:
        assert e["description"].strip()
        assert e["they_sell"].strip()
        assert e["they_want"].strip()


def test_spot_content_faithful():
    by_roll = {e["roll"]: e for e in _table()["entries"]}
    # Callista's Gift and Fairfrond's healing plums are load-bearing book facts
    assert "Sympathetic Flesh" in by_roll[1]["description"]
    assert "porcelain mask" in by_roll[1]["description"]
    assert "golden plums" in by_roll[2]["they_sell"]
    assert "hypergeometric doorway" in by_roll[3]["they_sell"]
    assert "fractal blades" in by_roll[4]["description"]
    assert "Elixirs" in by_roll[5]["they_sell"]
