"""The `character(action="register")` lever — crystallize an inference-authored sheet.

The DM authors the stat block; the engine validates the STRUCTURE (so combat/wounds/
slots never read a malformed sheet), computes the derived slot fields, and persists.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


def _abils(**over):
    base = {k: 1 for k in ("STR", "DEX", "CON", "INT", "PSY", "EGO")}
    base.update(over)
    return {k: {"current": v, "base": v} for k, v in base.items()}


def _good_sheet(**over):
    s = {
        "species": "Newbeast",
        "level": 2,
        "hp": {"current": 9, "max": 9},
        "av": {"base": 13, "source": "hide", "conditional": []},
        "abilities": _abils(CON=1),
        "wound_table": "biological",
        "inventory": {"carried": [{"name": "Spear", "slots": 1}]},
    }
    s.update(over)
    return s


@pytest.fixture
def captured(monkeypatch):
    """Stub persistence to in-memory so nothing touches live campaign data."""
    saved = {}
    monkeypatch.setattr(server, "_load_characters", lambda: ({"characters": {}}, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda slug, sheet, data=None: saved.__setitem__(slug, sheet))
    return saved


def _register(name, sheet):
    return server._character_register(name, json.dumps(sheet) if isinstance(sheet, (dict, list)) else sheet)


def test_valid_sheet_persists_and_computes_slots(captured):
    out = _register("Vex the Scout", _good_sheet())
    assert out.startswith("✓ Registered")
    s = captured["vex_the_scout"]
    # carry capacity = 10 + CON(1); used = the 1-slot spear
    assert s["slot_capacity_total"] == 11
    assert s["slots_used"] == 1
    assert "NEXT" in out  # reflex push to verify the sheet


def test_optional_containers_filled(captured):
    _register("Vex", _good_sheet())
    s = captured["vex"]
    for k in ("augmentations", "mystic_gifts", "bloomboons", "codices", "wounds", "special_traits"):
        assert k in s
    assert s["wounds"] == [] and s["mystic_gifts"] == []


def test_author_supplied_capacity_respected(captured):
    _register("Hauler", _good_sheet(slot_capacity_total=20))
    assert captured["hauler"]["slot_capacity_total"] == 20


def test_malformed_sheet_rejected_and_not_saved(captured):
    bad = {"species": "X", "level": "two", "hp": {"current": 5},
           "abilities": {"STR": {"current": 1}}, "wound_table": "bogus"}
    out = _register("Broken", bad)
    assert out.lower().startswith("sheet rejected")
    assert "broken" not in captured  # nothing persisted
    # each load-bearing problem is surfaced
    assert "'level'" in out and "'hp'" in out and "'av'" in out and "wound_table" in out


def test_missing_ability_key_rejected(captured):
    sheet = _good_sheet()
    del sheet["abilities"]["EGO"]
    out = _register("NoEgo", sheet)
    assert out.lower().startswith("sheet rejected") and "EGO" in out
    assert "noego" not in captured


def test_bad_json_handled(captured):
    out = server._character_register("X", "{not valid json")
    assert "not valid JSON" in out
    assert not captured


def test_missing_args_give_guidance(captured):
    assert "name" in server._character_register(None, "{}").lower()
    assert "sheet" in server._character_register("X", None).lower()
    assert not captured
