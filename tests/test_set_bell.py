"""Tests for the set_bell() MCP tool — advances the in-game clock during play."""
import server


def test_set_bell_sets_current_bell(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    result = server.sync_campaign_day(action='set_bell', bell=14)
    assert "14" in result
    assert server._read_hook_state().get("current_bell") == 14


def test_set_bell_clamps_high(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    server.sync_campaign_day(action='set_bell', bell=99)
    assert server._read_hook_state().get("current_bell") == 24


def test_set_bell_clamps_low(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    server.sync_campaign_day(action='set_bell', bell=0)
    assert server._read_hook_state().get("current_bell") == 1


def test_set_bell_preserves_other_state(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    server._write_hook_state({"session_started": True, "current_bell": 9})
    server.sync_campaign_day(action='set_bell', bell=17)
    state = server._read_hook_state()
    assert state.get("current_bell") == 17
    assert state.get("session_started") is True


def test_set_bell_invalid_input(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    assert "Invalid" in server.sync_campaign_day(action='set_bell', bell="not-a-number")
