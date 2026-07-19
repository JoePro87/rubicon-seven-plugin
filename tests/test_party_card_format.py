"""Party-tab card formatting (model.render_party_text) — 2026-07-19 pass.

Owner report: long names broke the stat columns, duplicate items listed N
times, long effect texts ran as one unwrapped line.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dashboard import model  # noqa: E402


def _card(name="Hero", items=None):
    return {"name": name, "hp_text": "10/10", "av": 12, "wounds": 0,
            "slots_text": "2/15", "items": items or []}


def _item(name, where="carried", effect=None):
    return {"name": name, "where": where, "effect": effect}


def test_long_name_never_breaks_stat_line():
    text = model.render_party_text([_card(name="Roscar + MNEMOSYNE")])
    lines = text.splitlines()
    assert lines[0] == "Roscar + MNEMOSYNE"          # name on its own line
    assert lines[1].startswith("=")                   # underline
    assert "HP 10/10" in lines[2]                     # stats on their own line


def test_duplicate_items_collapse_with_count():
    items = [_item("Water Rations")] * 4 + [_item("Rope")]
    text = model.render_party_text([_card(items=items)])
    assert "Water Rations x 4" in text
    assert text.count("Water Rations") == 1
    assert "Rope" in text and "Rope x" not in text


def test_long_effect_wraps_with_hanging_indent():
    items = [_item("Gadget", effect="word " * 40)]
    text = model.render_party_text([_card(items=items)], width=60)
    long_lines = [ln for ln in text.splitlines() if len(ln) > 60]
    assert not long_lines
    assert any(ln.startswith(" " * 8 + "word") for ln in text.splitlines())


def test_where_groups_ordered_carried_cyber_then_rest_given_away_last():
    items = [_item("A", where="stored"), _item("B", where="given_away"),
             _item("C", where="cybernetic"), _item("D", where="carried")]
    text = model.render_party_text([_card(items=items)])
    order = [w for w in ("carried", "cybernetic", "stored", "given_away")]
    positions = [text.index(f"  {w}\n") for w in order]
    assert positions == sorted(positions)


def test_no_items_placeholder():
    text = model.render_party_text([_card()])
    assert "(no items)" in text
