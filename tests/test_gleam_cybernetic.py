"""Gleam score + cybernetic slot accounting guards.

gleam_check: Gleam = (number of Mystic Gifts) + PSY bonus; drives the weekly
"does a psychic entity notice you" roll. cybernetic install: one implant per
ability slot, rejects a second install into an occupied slot, and applies its
stat bonus to the ability's current value (capped). Both are save-backed.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _write_char(char_id, char):
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta = chars_dir / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({"last_updated": "2026-01-01", "campaign_day": 50}))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _reload(name):
    data, _ = server._load_characters()
    _, char = server._find_character(data, name)
    return char


# --- gleam ----------------------------------------------------------------

def test_gleam_is_gifts_plus_psy():
    _write_char("cree", {
        "name": "Creenash",
        "mystic_gifts": [{"name": "Dissolving Thread"}, {"name": "Kronophage's Echo"}],
        "abilities": {"PSY": {"current": 1, "base": 1}},
    })
    out = server.gift(action='gleam', character_name="Creenash")
    assert "GLEAM:** 3" in out  # 2 gifts + PSY 1
    assert "Gifts: 2" in out


def test_gleam_zero_gifts_zero_psy():
    _write_char("plain", {"name": "Plain", "mystic_gifts": [], "abilities": {"PSY": {"current": 0}}})
    assert "GLEAM:** 0" in server.gift(action='gleam', character_name="Plain")


# --- cybernetic slot accounting -------------------------------------------

def _bare(name="Cyborg"):
    return {"name": name, "species": "true-kin",
            "abilities": {"DEX": {"current": 1, "base": 1}}}


def test_install_into_empty_slot_applies_stat_bonus():
    _write_char("cyborg", _bare())
    out = server._cybernetic_install("Cyborg", "Hyper Tendons", "DEX",
                                     "+2 DEX, jump 50ft", stat_bonus='{"DEX": 2}')
    assert "installed" in out.lower()
    char = _reload("Cyborg")
    assert char["augmentations"]["DEX"]["name"] == "Hyper Tendons"
    assert char["abilities"]["DEX"]["current"] == 3  # 1 + 2


def test_install_into_occupied_slot_is_rejected():
    c = _bare()
    c["augmentations"] = {"DEX": {"name": "Existing Aug"}}
    _write_char("cyborg", c)
    with pytest.raises(server.ToolError):
        server._cybernetic_install("Cyborg", "Second Aug", "DEX", "conflict")


def test_install_rejects_invalid_ability_slot():
    _write_char("cyborg", _bare())
    out = server._cybernetic_install("Cyborg", "Weird", "WIS", "not a Vaarn stat")
    assert "Invalid ability slot" in out
