"""Tests for the session_mode() MCP tool — the engine-owned, cross-platform
replacement for the old `cd hooks && python3 -c "...poke .hook_state.json..."`
shell blocks in the /maintenance, /session-end, /dm-design, /session-start skills.

Why this tool exists: the session skills must toggle maintenance OUT OF BAND of
check_canon (it IS the canon bypass), and must do so on every OS without a
filesystem path. session_mode is tagged ALWAYS (not GATED) so the gate can't
deadlock the bypass, and writes the same .hook_state.json the hooks read.
"""
import server
from hooks.hook_utils import in_maintenance
from tool_tags import Safety, TOOL_TAGS


def test_maintenance_on_sets_all_bypass_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    result = server.session_mode(action="maintenance_on")
    assert "ON" in result
    state = server._read_hook_state()
    assert state.get("maintenance_mode") is True
    assert state.get("skip_canon_enforcement") is True
    assert state.get("skip_semantic_observer") is True
    # The shared reader agrees we are in maintenance.
    assert in_maintenance(state) is True


def test_maintenance_off_clears_flags_and_counters(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    # Simulate a dirty mid-maintenance state with accrued prose-catch counters.
    server._write_hook_state({
        "maintenance_mode": True,
        "skip_canon_enforcement": True,
        "skip_semantic_observer": True,
        "catch_count": 7,
        "catch_log": {"echoed": 3},
        "session_vocabulary": ["foo", "bar"],
        "session_started": True,
    })
    result = server.session_mode(action="maintenance_off")
    assert "OFF" in result
    state = server._read_hook_state()
    assert state.get("maintenance_mode") is False
    assert state.get("skip_canon_enforcement") is False
    assert state.get("skip_semantic_observer") is False
    assert state.get("catch_count") == 0
    assert state.get("catch_log") == {}
    assert state.get("session_vocabulary") == []
    # Unrelated state survives the reset.
    assert state.get("session_started") is True
    assert in_maintenance(state) is False


def test_off_then_on_roundtrips(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    server.session_mode(action="maintenance_on")
    assert in_maintenance(server._read_hook_state()) is True
    server.session_mode(action="maintenance_off")
    assert in_maintenance(server._read_hook_state()) is False


def test_invalid_action_is_inert(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    server._write_hook_state({"maintenance_mode": False})
    result = server.session_mode(action="bogus")
    assert "Invalid" in result
    # No state change on an unknown action.
    assert server._read_hook_state().get("maintenance_mode") is False


def test_field_default_is_treated_as_maintenance_on(tmp_path, monkeypatch):
    """Direct (non-MCP) call with the unset Field default must not crash — the
    FieldInfo-vs-str guard defaults to maintenance_on."""
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    result = server.session_mode()  # action left as its Field() default
    assert "ON" in result
    assert server._read_hook_state().get("maintenance_mode") is True


def test_session_mode_is_always_never_gated():
    """The gate must never block session_mode (it IS the canon bypass). ALWAYS
    exempts the pre-session-start gate; GATED must be absent so check_canon is
    never a prerequisite."""
    tags = TOOL_TAGS["session_mode"]
    assert Safety.ALWAYS in tags
    assert Safety.GATED not in tags
