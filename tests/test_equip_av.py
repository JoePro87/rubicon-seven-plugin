"""Worn armour + AV recomputation (Bug 5, macOS playtest 1).

av.base is DERIVED: av.base = av.unarmoured + sum(av_bonus of every worn piece).
The DM equips an inventory item; the engine recomputes AV. No hand-editing the
sheet, and combat (which reads av.base) is correct without a manual AV set —
the bug that nearly killed Slurr (worn Occult Cuirass AV 14, sheet stuck at 10).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


def _pc(av_base=10, carried=None):
    return {
        "name": "Slurr", "species": "Cacogen",
        "hp": {"current": 5, "max": 5},
        "av": {"base": av_base, "unarmoured": av_base, "source": "unarmoured",
               "conditional": []},
        "abilities": {k: {"current": 0, "base": 0}
                      for k in ["STR", "DEX", "CON", "INT", "PSY", "EGO"]},
        "inventory": {"carried": carried or [], "stored": [],
                      "installed_permanent": [], "given_away": []},
    }


@pytest.fixture
def one_pc(monkeypatch):
    """A single PC on disk; saves captured so we can read the persisted sheet."""
    data = {"characters": {"slurr": _pc()}, "meta": {"campaign_day": 5}}
    saved = []

    def _save(key, char, d=None):
        saved.append((key, char))
        data["characters"][key] = char

    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", _save)
    return {"data": data, "saved": saved}


def _set_carried(one_pc, items):
    one_pc["data"]["characters"]["slurr"]["inventory"]["carried"] = items


# --- core recompute -----------------------------------------------------------

def test_equip_body_armour_with_av_bonus(one_pc):
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4}])
    out = server.character(action="equip", name="Slurr", item="Occult Cuirass")
    sheet = one_pc["data"]["characters"]["slurr"]
    assert sheet["av"]["base"] == 14          # 10 unarmoured + 4
    assert sheet["av"]["unarmoured"] == 10    # baseline preserved
    assert sheet["inventory"]["carried"][0]["worn"] is True
    assert sheet["inventory"]["carried"][0]["slot"] == "body"
    assert "10 -> 14" in out


def test_equip_derives_bonus_from_worn_av_field(one_pc):
    # Hand-authored/registered item carries 'av' (worn AV) not av_bonus.
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av": 14}])
    server.character(action="equip", name="Slurr", item="cuirass")
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 14  # 14-10 = +4


def test_equip_av_bonus_override(one_pc):
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass"}])
    server.character(action="equip", name="Slurr", item="cuirass", av_bonus=4)
    sheet = one_pc["data"]["characters"]["slurr"]
    assert sheet["av"]["base"] == 14
    assert sheet["inventory"]["carried"][0]["av_bonus"] == 4


def test_helm_and_body_stack_separate_slots(one_pc):
    _set_carried(one_pc, [
        {"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4},
        {"id": "helm", "name": "Fascinator Helm", "av_bonus": 1},
    ])
    server.character(action="equip", name="Slurr", item="cuirass")
    server.character(action="equip", name="Slurr", item="Fascinator Helm")
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 15  # 10+4+1


def test_second_body_armour_displaces_first(one_pc):
    _set_carried(one_pc, [
        {"id": "leather", "name": "Leather Jerkin", "av_bonus": 1},
        {"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4},
    ])
    server.character(action="equip", name="Slurr", item="leather")
    out = server.character(action="equip", name="Slurr", item="cuirass")
    carried = one_pc["data"]["characters"]["slurr"]["inventory"]["carried"]
    worn = {it["name"]: it.get("worn", False) for it in carried}
    assert worn["Occult Cuirass"] is True
    assert worn["Leather Jerkin"] is False           # one body slot only
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 14
    assert "Unequipped from body: Leather Jerkin" in out


def test_unequip_restores_unarmoured(one_pc):
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4}])
    server.character(action="equip", name="Slurr", item="cuirass")
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 14
    out = server.character(action="unequip", name="Slurr", item="cuirass")
    sheet = one_pc["data"]["characters"]["slurr"]
    assert sheet["av"]["base"] == 10
    assert sheet["av"]["source"] == "unarmoured"
    assert sheet["inventory"]["carried"][0]["worn"] is False
    assert "14 -> 10" in out


# --- error/edge behavior ------------------------------------------------------

def test_equip_missing_item_lists_carried(one_pc):
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4}])
    out = server.character(action="equip", name="Slurr", item="nonexistent")
    assert "No carried item matching" in out
    assert "Occult Cuirass" in out
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 10  # unchanged


def test_unequip_when_nothing_worn(one_pc):
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4}])
    out = server.character(action="unequip", name="Slurr", item="cuirass")
    assert "No WORN item" in out


def test_recompute_backfills_unarmoured_on_legacy_sheet(one_pc):
    # Legacy sheet: no 'unarmoured' key. Current base IS the no-armour baseline
    # (armour was never applied pre-fix). Backfill must not change a no-armour AV.
    sheet = one_pc["data"]["characters"]["slurr"]
    sheet["av"] = {"base": 10, "source": "unarmoured", "conditional": []}
    from character_tools import _recompute_av
    assert _recompute_av(sheet) == 10
    assert sheet["av"]["unarmoured"] == 10


def test_legacy_handedited_base_with_worn_item_no_double_count(one_pc):
    # Review #1: a hand-edited av.base that ALREADY folded in worn armour (Slurr's
    # mid-combat 10->15 with the cuirass worn) must NOT double-count on recompute.
    sheet = one_pc["data"]["characters"]["slurr"]
    sheet["av"] = {"base": 15, "source": "hand-edited", "conditional": []}  # no 'unarmoured'
    sheet["inventory"]["carried"] = [
        {"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4, "worn": True,
         "slot": "body"}]
    from character_tools import _recompute_av
    assert _recompute_av(sheet) == 15        # 11 baseline + 4 worn, NOT 19
    assert sheet["av"]["unarmoured"] == 11


def test_slot_inference_no_substring_false_positive(one_pc):
    # Review #2: 'cap'/'mask' substrings must not mis-slot body items as helm.
    from character_tools import _infer_av_slot
    assert _infer_av_slot({"name": "Capacitor Vest"}) == "body"
    assert _infer_av_slot({"name": "Caparison"}) == "body"
    assert _infer_av_slot({"name": "Visualiser Helm"}) == "helm"
    assert _infer_av_slot({"name": "Bronze Buckler"}) == "shield"
    assert _infer_av_slot({"name": "Helmsman's Shield"}) == "shield"  # collision -> shield


def test_string_av_bonus_is_not_silently_zero(one_pc):
    # Review #4: a registered item with a STRING av_bonus must still protect.
    from character_tools import _item_av_bonus
    assert _item_av_bonus({"av_bonus": "4"}) == 4
    assert _item_av_bonus({"av": "14"}) == 4
    _set_carried(one_pc, [{"id": "cuirass", "name": "Occult Cuirass", "av_bonus": "4"}])
    server.character(action="equip", name="Slurr", item="cuirass")
    assert one_pc["data"]["characters"]["slurr"]["av"]["base"] == 14


# --- standing AV mutation composes with armour --------------------------------

def test_mutation_av_bonus_lifts_baseline_and_stacks_with_armour(one_pc):
    from character_tools import _apply_bloomboon_to_sheet, _recompute_av
    sheet = one_pc["data"]["characters"]["slurr"]
    sheet["inventory"]["carried"] = [
        {"id": "cuirass", "name": "Occult Cuirass", "av_bonus": 4, "worn": True,
         "slot": "body"}]
    _recompute_av(sheet)
    assert sheet["av"]["base"] == 14
    # A standing +1 AV mutation/bloomboon lifts the UNARMOURED baseline so it
    # composes with worn armour (coral-crown +1 that the playtest lost).
    _apply_bloomboon_to_sheet(
        sheet, {"name": "Coral Crown", "effect": "+1 AV",
                "engine_effects": {"av_base_bonus": 1}}, source="mutation")
    assert sheet["av"]["unarmoured"] == 11
    assert sheet["av"]["base"] == 15  # 11 + 4 worn armour


# --- the engine pushes the equip step after chargen(armour) -------------------

def test_chargen_armour_pushes_equip_directive():
    # roll(action="chargen", table="armour") is a closure registered on mcp, so
    # assert the push directive ships in the armour branch (source-presence check,
    # the same stable pattern the hook tests use).
    src = (Path(__file__).resolve().parent.parent / "content_forge.py").read_text(encoding="utf-8")
    assert 'character(action=\\"equip\\"' in src
    assert "do not hand-edit the sheet" in src
