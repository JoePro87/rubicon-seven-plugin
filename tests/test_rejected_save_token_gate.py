"""C19 — a verify_save-rejected save must not be committable via confirm_save.

prepare_save_state mints and prints a confirmation token BEFORE the PostToolUse
verify_save hook runs, and confirm_save only checks token match + age. So a
hallucination-flagged save's token stays live and confirm_save(token) would
commit it. Fix: verify_save records the rejected token into .hook_state.json, and
gate_check blocks confirm_save when its token matches a recorded rejected token.
Self-clearing — a re-called prepare_save_state mints a fresh token.
"""
import io
import json
import sys
from pathlib import Path

import pytest


# --- verify_save side -------------------------------------------------------

def test_extract_token_from_string_response():
    import hooks.verify_save as vs
    resp = "diff...\nCONFIRMATION TOKEN: a1b2c3d4\nnext block..."
    assert vs._extract_save_token({}, resp) == "a1b2c3d4"


def test_extract_token_from_structured_response():
    import hooks.verify_save as vs
    resp = {"content": [{"type": "text", "text": "CONFIRMATION TOKEN: deadbeef"}]}
    assert vs._extract_save_token({}, resp) == "deadbeef"


def test_extract_token_falls_back_to_tool_input():
    import hooks.verify_save as vs
    assert vs._extract_save_token({"token": "feedface"}, "no token here") == "feedface"


def test_extract_token_returns_empty_when_absent():
    import hooks.verify_save as vs
    assert vs._extract_save_token({}, "nothing to see") == ""


def test_record_rejected_token_persists_under_lock(tmp_path, monkeypatch):
    import hooks.hook_utils as hu
    import hooks.verify_save as vs
    monkeypatch.setattr(hu, "STATE_FILE", tmp_path / ".hook_state.json")
    monkeypatch.setattr(hu, "LOCK_FILE", tmp_path / ".hook_state.lock")
    hu.save_state({"session_started": True})

    vs._record_rejected_token({}, "CONFIRMATION TOKEN: a1b2c3d4")
    state = hu.load_state()
    assert state.get("rejected_save_tokens") == ["a1b2c3d4"]

    # A second distinct rejection appends; unrelated state survives.
    vs._record_rejected_token({}, "CONFIRMATION TOKEN: 99887766")
    state = hu.load_state()
    assert state["rejected_save_tokens"] == ["a1b2c3d4", "99887766"]
    assert state["session_started"] is True


def test_record_rejected_token_is_capped(tmp_path, monkeypatch):
    import hooks.hook_utils as hu
    import hooks.verify_save as vs
    monkeypatch.setattr(hu, "STATE_FILE", tmp_path / ".hook_state.json")
    monkeypatch.setattr(hu, "LOCK_FILE", tmp_path / ".hook_state.lock")
    hu.save_state({})
    for i in range(vs._MAX_REJECTED_TOKENS + 10):
        vs._record_rejected_token({}, f"CONFIRMATION TOKEN: {i:08x}")
    tokens = hu.load_state()["rejected_save_tokens"]
    assert len(tokens) == vs._MAX_REJECTED_TOKENS  # bounded, no unbounded growth


# --- gate_check side --------------------------------------------------------

def _run_gate(monkeypatch, tmp_path, hook_input, state):
    """Run gate_check.main() in-process against an isolated state file. Returns
    the SystemExit code (0=allow, 2=block)."""
    import hooks.hook_utils as hu
    monkeypatch.setattr(hu, "STATE_FILE", tmp_path / ".hook_state.json")
    monkeypatch.setattr(hu, "LOCK_FILE", tmp_path / ".hook_state.lock")
    hu.save_state(state)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook_input)))
    import hooks.gate_check as gc
    with pytest.raises(SystemExit) as exc:
        gc.main()
    return exc.value.code


_ALLOW_BASE = {
    "session_started": True,
    "canon_verified": True,
    "canon_succeeded": True,
    "canon_required": False,
}


def test_confirm_save_blocked_for_rejected_token(tmp_path, monkeypatch):
    state = dict(_ALLOW_BASE, rejected_save_tokens=["a1b2c3d4"])
    hook_input = {
        "tool_name": "mcp__rubicon-seven__confirm_save",
        "tool_input": {"token": "a1b2c3d4"},
    }
    assert _run_gate(monkeypatch, tmp_path, hook_input, state) == 2


def test_confirm_save_allowed_for_fresh_token(tmp_path, monkeypatch):
    # A different (freshly-minted) token is NOT trapped by the stale rejection.
    state = dict(_ALLOW_BASE, rejected_save_tokens=["a1b2c3d4"])
    hook_input = {
        "tool_name": "mcp__rubicon-seven__confirm_save",
        "tool_input": {"token": "0f0f0f0f"},
    }
    assert _run_gate(monkeypatch, tmp_path, hook_input, state) == 0


def test_confirm_save_allowed_when_no_rejections(tmp_path, monkeypatch):
    hook_input = {
        "tool_name": "mcp__rubicon-seven__confirm_save",
        "tool_input": {"token": "a1b2c3d4"},
    }
    assert _run_gate(monkeypatch, tmp_path, hook_input, dict(_ALLOW_BASE)) == 0


def test_rejected_token_gate_ignores_maintenance_mode(tmp_path, monkeypatch):
    # The save-write guard must fire even under maintenance mode (it guards the
    # live canon write, not the advisory prose layer).
    state = dict(_ALLOW_BASE, maintenance_mode=True, skip_canon_enforcement=True,
                 rejected_save_tokens=["a1b2c3d4"])
    hook_input = {
        "tool_name": "mcp__rubicon-seven__confirm_save",
        "tool_input": {"token": "a1b2c3d4"},
    }
    assert _run_gate(monkeypatch, tmp_path, hook_input, state) == 2


def test_prepare_save_state_never_blocked_by_rejected_tokens(tmp_path, monkeypatch):
    # Hard rule: the gate must never block prepare_save_state itself.
    state = dict(_ALLOW_BASE, rejected_save_tokens=["a1b2c3d4"])
    hook_input = {
        "tool_name": "mcp__rubicon-seven__prepare_save_state",
        "tool_input": {},
    }
    assert _run_gate(monkeypatch, tmp_path, hook_input, state) == 0
