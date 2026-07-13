"""Tests for the §12 changes: corrections logging cut + rule_refs wiring."""
import sys
from pathlib import Path

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
sys.path.insert(0, str(HOOKS))


def test_corrections_logging_is_neutralized(tmp_path, monkeypatch):
    import importlib
    import correction_logger as cl
    importlib.reload(cl)
    # Point the module at a temp file and confirm logging writes nothing.
    monkeypatch.setattr(cl, "CORRECTIONS_FILE", tmp_path / "corrections.json")
    cl.log_correction("hook", "caught text", "reason", severity="hard")
    cl.mark_false_positive()
    assert not (tmp_path / "corrections.json").exists(), "neutralized logger must not write"
    assert cl.load_corrections() == []
    assert cl.get_recent_corrections() == []


def test_build_rules_in_play_block(monkeypatch):
    import server
    lorebook = {
        "entries": [
            {"category": "people", "keywords": ["creenash"],
             "rule_refs": ["rule-neobloom-flammable", "rule-neobloom-photo"]},
            {"category": "people", "keywords": ["vela"], "rule_refs": []},
        ]
    }
    rules_idx = {
        "rule-neobloom-flammable": "Neobloom: DOUBLE damage from flames.",
        "rule-neobloom-photo": "Neobloom: photosynthesise or perish after 3 days.",
    }
    block = server._build_rules_in_play_block(["Creenash"], lorebook, rules_idx)
    assert "RULES IN PLAY" in block
    assert "DOUBLE damage from flames" in block
    assert "photosynthesise" in block
    # No present character with rules → empty string
    assert server._build_rules_in_play_block(["Vela"], lorebook, rules_idx) == ""
    # Cap is respected
    big_idx = {f"r{i}": f"rule {i}" for i in range(20)}
    big_lore = {"entries": [{"category": "people", "keywords": ["x"],
                             "rule_refs": [f"r{i}" for i in range(20)]}]}
    capped = server._build_rules_in_play_block(["x"], big_lore, big_idx, cap=6)
    assert capped.count("\n- ") == 6
