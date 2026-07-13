"""T4 — the monolithic characters.json fallback is retired.

Split sheets (characters/*.json + _meta.json) are the SOLE source of truth.
A stale monolithic characters.json must never be read (it silently drifted —
missing weapons / range markers) and no code path may recreate it.
"""
import json
import shutil

import server


def _make_split(campaign_dir, characters: dict, day: int = 50):
    """Stage split character sheets in the (temp) campaign dir."""
    chars_dir = campaign_dir / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / "_meta.json").write_text(
        json.dumps({"campaign_day": day, "last_updated": "2026-06-08"}), encoding="utf-8"
    )
    for key, char in characters.items():
        (chars_dir / f"{key}.json").write_text(json.dumps(char), encoding="utf-8")
    return chars_dir


def _clear_split(campaign_dir):
    chars_dir = campaign_dir / "characters"
    if chars_dir.exists():
        shutil.rmtree(chars_dir)


def test_load_characters_reads_split_sheets():
    camp = server.CAMPAIGN_DIR
    _make_split(camp, {"creenash": {"name": "Creenash", "type": "pc",
                                    "hp": {"current": 10, "max": 10}}})
    data, err = server._load_characters()
    assert err is None
    assert data["characters"]["creenash"]["name"] == "Creenash"


def test_split_sheets_win_over_any_stale_monolithic():
    """A leftover monolithic file must NEVER override the authoritative split sheets."""
    camp = server.CAMPAIGN_DIR
    _make_split(camp, {"creenash": {"name": "Creenash", "type": "pc"}})
    (camp / "characters.json").write_text(
        json.dumps({"meta": {}, "characters": {"ghost": {"name": "StaleGhost"}}}), encoding="utf-8"
    )
    data, err = server._load_characters()
    assert err is None
    assert "creenash" in data["characters"]
    assert "ghost" not in data["characters"]  # monolithic ignored entirely


def test_monolithic_fallback_is_retired():
    """With no split sheets, a monolithic characters.json must NOT be silently served.

    The whole point of the retire: better a clear error than stale combat stats.
    """
    camp = server.CAMPAIGN_DIR
    _clear_split(camp)
    (camp / "characters.json").write_text(
        json.dumps({"meta": {}, "characters": {"ghost": {"name": "StaleGhost"}}}), encoding="utf-8"
    )
    data, err = server._load_characters()
    assert data is None
    assert err is not None  # clear error, never the stale monolithic


def test_inventory_change_never_creates_monolithic():
    """Applying an inventory change writes split sheets only, never characters.json."""
    camp = server.CAMPAIGN_DIR
    _make_split(camp, {"creenash": {
        "name": "Creenash", "type": "pc",
        "inventory": {"carried": [], "stored": [], "installed_permanent": [], "given_away": []},
    }})
    server._apply_inventory_changes(
        [{"character": "Creenash", "action": "add", "item": {"name": "Test Knife", "slots": 1}}],
        day=50,
    )
    assert not (camp / "characters.json").exists()
    data, _ = server._load_characters()
    carried = data["characters"]["creenash"]["inventory"]["carried"]
    assert any(i["name"] == "Test Knife" for i in carried)


def test_inventory_remove_accepts_bare_string_name():
    """remove with a bare string item used to crash ('str' has no attribute
    'get'); it now matches by display name (Corelia bug #7)."""
    camp = server.CAMPAIGN_DIR
    _make_split(camp, {"val": {
        "name": "Val", "type": "pc",
        "inventory": {
            "carried": [{"id": "water_rations", "name": "Water Rations", "slots": 1}],
            "stored": [], "installed_permanent": [], "given_away": [],
        },
    }})
    results = server._apply_inventory_changes(
        [{"character": "Val", "action": "remove", "item": "Water Rations"}],
        day=50,
    )
    assert any("REMOVED" in r for r in results), results
    data, _ = server._load_characters()
    assert data["characters"]["val"]["inventory"]["carried"] == []


def test_inventory_remove_accepts_bare_string_id():
    """A bare string that is the stable id (not the display name) also matches."""
    camp = server.CAMPAIGN_DIR
    _make_split(camp, {"val": {
        "name": "Val", "type": "pc",
        "inventory": {
            "carried": [{"id": "water_rations", "name": "Water Rations", "slots": 1}],
            "stored": [], "installed_permanent": [], "given_away": [],
        },
    }})
    server._apply_inventory_changes(
        [{"character": "Val", "action": "remove", "item": "water_rations"}],
        day=50,
    )
    data, _ = server._load_characters()
    assert data["characters"]["val"]["inventory"]["carried"] == []


def test_source_has_no_monolithic_writer():
    """Guard against re-introduction: no legacy monolithic writer remains in source."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert "legacy_char_path" not in src
    assert "Also sync legacy monolithic" not in src
