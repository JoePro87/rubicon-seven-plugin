import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server  # noqa: E402  (registers session_tools deps incl. _pf)
import session_tools  # noqa: E402


def test_empty_removals_no_nudge(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    assert session_tools._crystallize_nudge_block([], 141) == ""


def test_nudge_names_items_and_current_place(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "game_state.json").write_text(
        json.dumps({"active_location_name": "Pilgrim's Rest"}), encoding="utf-8")
    out = session_tools._crystallize_nudge_block(["chromatic flower"], 141)
    assert "CRYSTALLIZE" in out
    assert "chromatic flower" in out
    assert "update_location_progress" in out
    assert "Pilgrim" in out  # current place made it into the pushed call


def test_nudge_without_game_state_uses_placeholder(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    out = session_tools._crystallize_nudge_block(["rope"], 10)
    assert "<current place>" in out


def test_apostrophe_item_survives(tmp_path, monkeypatch):
    monkeypatch.setattr(session_tools, "CAMPAIGN_DIR", tmp_path)
    out = session_tools._crystallize_nudge_block(["Yam's lantern"], 10)
    assert "Yam's lantern" in out
