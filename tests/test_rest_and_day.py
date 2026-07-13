"""Rest + day-advance guards (`_rest_short_calculate`, `_rest_long`, `advance_day`).

Short rest calculates d8+CON healing (and heals nothing at full HP). Long rest
restores all HP, resets codex usage, and regenerates damaged abilities by 1.
advance_day writes the new day into CURRENT_STATUS.md and syncs it to the
character/party JSON. These are state-mutating, save-backed paths; a bug
silently corrupts a sheet or desynchronizes the campaign day.
"""
import json
import sys
from pathlib import Path

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


def _char(**ov):
    c = {
        "name": "Kess",
        "species": "cacogen",
        "hp": {"current": 5, "max": 29},
        "abilities": {"CON": {"current": 3, "base": 3}},
    }
    c.update(ov)
    return c


# --- short rest -----------------------------------------------------------

def test_short_rest_reports_d8_plus_con():
    _write_char("kess", _char())
    out = server._rest_short_calculate("Kess")
    assert "heals d8 + 3" in out


def test_short_rest_at_full_hp_heals_nothing():
    _write_char("kess", _char(hp={"current": 29, "max": 29}))
    out = server._rest_short_calculate("Kess")
    assert "Full HP" in out and "no healing needed" in out


# --- long rest ------------------------------------------------------------

def test_long_rest_restores_all_hp_and_persists():
    _write_char("kess", _char(hp={"current": 5, "max": 29}))
    server._rest_long("Kess")
    assert _reload("Kess")["hp"]["current"] == 29


def test_long_rest_resets_codex_usage():
    _write_char("kess", _char(can_use_codices=False))
    server._rest_long("Kess")
    assert _reload("Kess")["can_use_codices"] is True


def test_long_rest_regenerates_damaged_ability_by_one():
    # at full HP so the ability-regen branch runs
    c = _char(hp={"current": 29, "max": 29})
    c["abilities"]["STR"] = {"current": -2, "base": 0}
    _write_char("kess", c)
    server._rest_long("Kess")
    assert _reload("Kess")["abilities"]["STR"]["current"] == -1  # +1 toward base


# --- advance_day ----------------------------------------------------------

def test_advance_day_updates_status_and_syncs_meta():
    _write_char("kess", _char())
    party = server.CAMPAIGN_DIR / "party.json"
    party.write_text(json.dumps({"meta": {"campaign_day": 50}}))

    server.advance_day(55, "time skip")

    status = (server.CAMPAIGN_DIR / "CURRENT_STATUS.md").read_text()
    assert "DAY 55" in status
    assert "**Day:** 55" in status
    meta = json.loads((server.CAMPAIGN_DIR / "characters" / "_meta.json").read_text())
    assert meta["campaign_day"] == 55
    assert json.loads(party.read_text())["meta"]["campaign_day"] == 55
