import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "turn_reset.py"
STATE = Path(__file__).resolve().parents[1] / "hooks" / ".hook_state.json"


@pytest.fixture
def preserve_state():
    """Back up and restore the live .hook_state.json so the test can't corrupt it."""
    backup = STATE.read_text() if STATE.exists() else None
    try:
        yield
    finally:
        if backup is not None:
            STATE.write_text(backup)
        elif STATE.exists():
            STATE.unlink()


def _run(prompt):
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"hook failed: {result.stderr}"
    return json.loads(STATE.read_text())


def test_canon_delivered_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["canon_delivered"] = {"voice:Creenash": {"h": "abc", "t": 3}}
    STATE.write_text(json.dumps(state))
    after = _run("I walk to the garden.")
    assert after.get("canon_delivered") == {"voice:Creenash": {"h": "abc", "t": 3}}


def test_canon_delivered_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["canon_delivered"] = {"voice:Creenash": {"h": "abc", "t": 3}}
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("canon_delivered") == {}


def test_reflex_snapshot_preserved_on_normal_turn(preserve_state):
    """turn_reset must NOT wipe the reflex Δ baseline on a normal turn —
    phrase_reminder runs after it and needs last turn's snapshot."""
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["reflex_snapshot"] = {"die:Vela|Blowtorch": "Ud8", "wounds:Vela wounds": "1"}
    STATE.write_text(json.dumps(state))
    after = _run("I walk to the garden.")
    assert after.get("reflex_snapshot") == {
        "die:Vela|Blowtorch": "Ud8", "wounds:Vela wounds": "1"}


def test_reflex_snapshot_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["reflex_snapshot"] = {"die:Vela|Blowtorch": "Ud8"}
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("reflex_snapshot") == {}


# --- Stop-armed enforcement flags must survive turn_reset (audit 2026-06-16) ---
# consolidated_stop_check arms these at Stop; gate_check reads them next turn.
# turn_reset rebuilt state from scratch and dropped them, so three cross-turn
# enforcements silently never blocked. Each has its own satisfier (gate_check
# clear / per-NPC pop / session-start), so preserving them can't make them stick.

def test_validate_prose_required_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["validate_prose_required"] = True
    STATE.write_text(json.dumps(state))
    after = _run("I describe the market stalls.")
    assert after.get("validate_prose_required") is True


def test_vault_action_required_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["vault_action_required"] = True
    STATE.write_text(json.dumps(state))
    after = _run("I keep exploring the vault.")
    assert after.get("vault_action_required") is True


def test_open_npc_scene_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["open_npc_scene"] = {"Creenash": {"t": 3}}
    STATE.write_text(json.dumps(state))
    after = _run("I talk with the gathered crowd.")
    assert after.get("open_npc_scene") == {"Creenash": {"t": 3}}


def test_current_bell_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["current_bell"] = 14
    STATE.write_text(json.dumps(state))
    after = _run("I wander the plaza.")
    assert after.get("current_bell") == 14


def test_ceruline_seen_session_preserved_on_normal_turn(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["ceruline_seen_session"] = True
    STATE.write_text(json.dumps(state))
    after = _run("I press deeper into the dunes.")
    assert after.get("ceruline_seen_session") is True


def test_ceruline_seen_session_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["ceruline_seen_session"] = True
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("ceruline_seen_session") is False


# The obligation gates are about the response just given; a NEW session has no
# such response, so they must clear on /session-start — else a stale obligation
# from last session would block full_session_startup at the next session's start.

def test_validate_prose_required_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["validate_prose_required"] = True
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("validate_prose_required") is False


def test_vault_action_required_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["vault_action_required"] = True
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("vault_action_required") is False


def test_open_npc_scene_cleared_on_session_start(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["open_npc_scene"] = {"Creenash": {"t": 3}}
    STATE.write_text(json.dumps(state))
    after = _run("/session-start")
    assert after.get("open_npc_scene") == {}
