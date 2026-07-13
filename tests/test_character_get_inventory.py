"""_character_get must surface what items DO — effects, stored, installed.

2026-07-07 owner ask: party items vary wildly in what they can do; the sheet
render is where the DM (and the /menu character card) learns an item's powers.
Before this, effect/effect_daily/notes were dropped and the stored +
installed_permanent inventories were not rendered at all.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402


def _write_sheet(campaign_dir):
    chars = Path(campaign_dir) / "characters"
    chars.mkdir(exist_ok=True, parents=True)
    (chars / "_meta.json").write_text(
        json.dumps({"version": 1, "campaign_day": 50}), encoding="utf-8")
    sheet = {
        "name": "Testa", "player": True, "species": "True-Kin", "level": 2,
        "hp": {"current": 10, "max": 12}, "av": {"base": 12},
        "abilities": {s: {"current": 1, "base": 1}
                      for s in ["STR", "DEX", "CON", "INT", "PSY", "EGO"]},
        "inventory": {
            "carried": [
                {"id": "whisper_lens", "name": "Whisper Lens", "slots": 1,
                 "effect": "See through any fog or smoke",
                 "effect_daily": "Once per day: reveal one hidden door",
                 "uses_per": "day", "uses_max": 1,
                 "tags": ["optic"], "notes": "Hums near vault glass"},
                {"id": "vibro_knife", "name": "Vibro Knife", "slots": 1,
                 "type": "weapon", "damage": "d6",
                 "power_cell_required": True, "power_cell_status": "charged"},
            ],
            "stored": [
                {"id": "spare_coil", "name": "Spare Coil", "slots": 2,
                 "location": "Ceruline quarters",
                 "effect": "Recharges one power cell"}],
            "installed_permanent": [
                {"name": "Gut Flora Symbiote", "location": "gut",
                 "effect": "Digest any organic matter safely"}],
        },
        "augmentations": {"DEX": [{"name": "Reflex Splice", "type": "cybernetic",
                                   "effect": "+1 DEX (counted)", "stat_bonus": 1}]},
        "wound_table": "flesh",
    }
    (chars / "testa.json").write_text(json.dumps(sheet), encoding="utf-8")


def test_get_surfaces_item_effects_and_all_sections():
    _write_sheet(server.CAMPAIGN_DIR)
    out = server.character(action="get", name="Testa")

    # carried: every effect field rendered, indented under the item line
    assert "See through any fog or smoke" in out
    assert "Once per day: reveal one hidden door" in out
    assert "Hums near vault glass" in out
    assert "charged" in out                       # power-cell state

    # stored inventory rendered, with where it is and what it does
    assert "STORED" in out
    assert "Spare Coil" in out
    assert "Ceruline quarters" in out
    assert "Recharges one power cell" in out

    # permanent installs rendered (distinct from carried equipment)
    assert "INSTALLED" in out
    assert "Gut Flora Symbiote" in out
    assert "Digest any organic matter safely" in out

    # cybernetics stay their own section
    assert "AUGMENTATIONS" in out
    assert "Reflex Splice" in out


def test_get_effect_lines_are_indented_list_items():
    _write_sheet(server.CAMPAIGN_DIR)
    out = server.character(action="get", name="Testa")
    line = next(l for l in out.splitlines() if "See through any fog" in l)
    assert line.startswith("  "), f"effect line not indented: {line!r}"
