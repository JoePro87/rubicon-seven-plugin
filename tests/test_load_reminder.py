# tests/test_load_reminder.py
import json
from pathlib import Path
import importlib.util

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "phrase_reminder.py"
spec = importlib.util.spec_from_file_location("phrase_reminder", HOOK)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


def _write_char(dirpath, name, carried, capacity=13, wounds=0):
    (dirpath / "characters").mkdir(exist_ok=True)
    (dirpath / "characters" / f"{name.lower()}.json").write_text(json.dumps({
        "name": name, "slot_capacity_total": capacity, "wounds_slots_used": wounds,
        "mystic_gifts": [], "codices": [], "inventory": {"carried": carried},
    }))


def test_load_block_lists_depletables_and_call(tmp_path):
    _write_char(tmp_path, "Petros", [
        {"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"},
        {"name": "Rope", "slots": 1},
    ])
    block = pr._build_load_block(tmp_path)
    assert "LOAD:" in block
    assert "Blowtorch (Ud8)" in block
    assert 'usage(action="use"' in block
    assert "Rope" not in block


def test_load_block_flags_encumbered(tmp_path):
    _write_char(tmp_path, "Vela", [{"name": "Loot", "slots": 14}], capacity=13)
    block = pr._build_load_block(tmp_path)
    assert "ENCUMBERED" in block


def test_load_block_empty_when_no_depletables(tmp_path):
    _write_char(tmp_path, "Kess", [{"name": "Rope", "slots": 1}])
    assert pr._build_load_block(tmp_path) == ""


def test_load_block_apostrophe_item_name(tmp_path):
    _write_char(tmp_path, "Petros", [
        {"name": "Kronophage's Echo", "slots": 1, "usage_die": "Ud6"},
    ])
    block = pr._build_load_block(tmp_path)
    assert 'item="Kronophage\'s Echo"' in block   # double-quoted args survive the apostrophe


def test_load_block_skips_malformed_json(tmp_path):
    _write_char(tmp_path, "Petros", [{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"}])
    (tmp_path / "characters" / "bad.json").write_text("{ this is not valid json ")
    block = pr._build_load_block(tmp_path)
    assert "Blowtorch (Ud8)" in block   # valid char still rendered; bad file skipped, no crash
