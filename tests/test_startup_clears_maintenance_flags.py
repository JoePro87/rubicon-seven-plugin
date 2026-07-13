"""Regression: full_session_startup must clear ALL maintenance-bypass flags.

The bug (2026-07-02): a /maintenance session set skip_semantic_observer=True
(muting the Haiku prose observer). Returning to play via full_session_startup
cleared skip_canon_enforcement + maintenance_mode but NOT skip_semantic_observer,
so the observer stayed silently muted through live play. CLAUDE.md promises
"maintenance can't ride into a real play session" — that guarantee was only true
for two of the three flags. This locks in the third.

The gate_check.py PreToolUse hook owns the startup flag reset (session_tools.py's
full_session_startup does not touch these flags), so the test drives the hook's
main() with a full_session_startup tool-call and a dirty starting state.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import hooks.hook_utils as hook_utils
import hooks.gate_check as gate_check


def _isolate_state(tmp_path, monkeypatch):
    """Point the shared hook state + lock at a temp dir so we never touch the
    live hooks/.hook_state.json."""
    state_file = tmp_path / ".hook_state.json"
    monkeypatch.setattr(hook_utils, "STATE_FILE", state_file)
    monkeypatch.setattr(hook_utils, "LOCK_FILE", tmp_path / ".hook_state.lock")
    return state_file


def test_full_session_startup_clears_all_three_maintenance_flags(tmp_path, monkeypatch):
    state_file = _isolate_state(tmp_path, monkeypatch)
    # A dirty "just left maintenance" state: all three bypass flags stuck on.
    hook_utils.save_state({
        "maintenance_mode": True,
        "skip_canon_enforcement": True,
        "skip_semantic_observer": True,
        "session_started": False,
    })

    hook_input = {"tool_name": "full_session_startup", "tool_input": {}}
    with patch.object(gate_check, "read_hook_input", return_value=hook_input):
        # allow() exits 0 once the startup handler has written state.
        with pytest.raises(SystemExit) as exc:
            gate_check.main()
    assert exc.value.code == 0

    state = json.loads(state_file.read_text())
    assert state["maintenance_mode"] is False
    assert state["skip_canon_enforcement"] is False
    assert state["skip_semantic_observer"] is False, (
        "startup left the prose observer muted — the exact stuck-flag bug"
    )
    assert state["session_started"] is True
