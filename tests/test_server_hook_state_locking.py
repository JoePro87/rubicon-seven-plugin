"""C18 + C26 — the MCP server process must serialize its .hook_state.json
read-modify-writes against the hooks' own locked writes.

The hooks all guard their RMWs with hook_utils.file_lock() and write atomically.
Before this fix the server wrote the state file with plain, unlocked, sometimes
non-atomic open('w')/write_text calls (reset_gate, _set_bell_impl, session_mode,
check_canon's injected_npcs + end-of-call delta, and _validate_prose_impl's
validate_prose_called). A torn read landing inside a hook's write window falls to
hook_utils' default state (session_type='development', canon flags False) — which,
if persisted, silently drops canon enforcement for the rest of the session.

These tests prove every server-side write now happens INSIDE the shared lock.
"""
from contextlib import contextmanager
from pathlib import Path

import server


def _install_lock_spy(monkeypatch):
    """Replace hook_utils.file_lock with a spy that tracks 'are we inside the
    lock right now', and wrap server._write_hook_state to record whether each
    write fired while the lock was held."""
    import hooks.hook_utils as hu

    tracker = {"inside": False, "entered": 0, "writes_inside": []}

    @contextmanager
    def spy_lock(**_kwargs):
        tracker["inside"] = True
        tracker["entered"] += 1
        try:
            yield
        finally:
            tracker["inside"] = False

    monkeypatch.setattr(hu, "file_lock", spy_lock)

    real_write = server._write_hook_state

    def spy_write(state):
        tracker["writes_inside"].append(tracker["inside"])
        return real_write(state)

    monkeypatch.setattr(server, "_write_hook_state", spy_write)
    return tracker


def test_hook_state_lock_acquires_shared_file_lock(tmp_path, monkeypatch):
    """_hook_state_lock must acquire hook_utils.file_lock (the SAME cross-process
    lock the hooks use), not a private/no-op lock."""
    import hooks.hook_utils as hu
    entered = []

    @contextmanager
    def spy_lock(**_kwargs):
        entered.append(True)
        yield

    monkeypatch.setattr(hu, "file_lock", spy_lock)
    with server._hook_state_lock():
        pass
    assert entered == [True]


def test_reset_gate_writes_under_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    tracker = _install_lock_spy(monkeypatch)
    result = server.reset_gate()
    assert tracker["entered"] == 1
    assert tracker["writes_inside"] == [True], "reset_gate wrote outside the lock"
    st = server._read_hook_state()
    assert st.get("canon_verified") is True
    assert st.get("canon_succeeded") is True
    assert st.get("vault_action_required") is False
    assert "reset" in result.lower()


def test_set_bell_writes_under_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    tracker = _install_lock_spy(monkeypatch)
    server._set_bell_impl(9)
    assert tracker["entered"] == 1
    assert tracker["writes_inside"] == [True], "_set_bell_impl wrote outside the lock"
    assert server._read_hook_state().get("current_bell") == 9


def test_session_mode_writes_under_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "HOOK_STATE_FILE", tmp_path / ".hook_state.json")
    tracker = _install_lock_spy(monkeypatch)
    server.session_mode(action="maintenance_on")
    assert tracker["entered"] == 1
    assert tracker["writes_inside"] == [True], "session_mode wrote outside the lock"
    assert server._read_hook_state().get("maintenance_mode") is True

    # A second toggle also stays under the lock.
    tracker["entered"] = 0
    tracker["writes_inside"] = []
    server.session_mode(action="maintenance_off")
    assert tracker["entered"] == 1
    assert tracker["writes_inside"] == [True]
    assert server._read_hook_state().get("maintenance_mode") is False


def test_no_unlocked_hook_state_writes_remain_in_server():
    """Guard-the-guard: no plain (unlocked/non-atomic) hook-state writer may
    reappear in server.py. All writes go through _write_hook_state under the lock."""
    src = Path(server.__file__).read_text(encoding="utf-8", errors="ignore")
    assert "hook_state_path.write_text" not in src
    assert "json.dump(hs, f" not in src
    assert "open(hook_state_path, 'w')" not in src
