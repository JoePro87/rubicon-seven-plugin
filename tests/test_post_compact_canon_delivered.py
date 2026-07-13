import json
import subprocess
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "post_compact.py"
STATE = Path(__file__).resolve().parents[1] / "hooks" / ".hook_state.json"


@pytest.fixture
def preserve_state():
    backup = STATE.read_text() if STATE.exists() else None
    try:
        yield
    finally:
        if backup is not None:
            STATE.write_text(backup)
        elif STATE.exists():
            STATE.unlink()


def _run():
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input="{}", text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"hook failed: {result.stderr}"
    return json.loads(STATE.read_text())


def test_post_compact_clears_canon_delivered_in_gameplay(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["session_type"] = "gameplay"
    state["skip_canon_enforcement"] = False
    # in_maintenance() honors BOTH flag names (d702995); the inherited live
    # state may carry maintenance_mode=true from engine-dev work.
    state["maintenance_mode"] = False
    state["canon_delivered"] = {"voice:Vela": {"h": "abc", "t": 4}}
    STATE.write_text(json.dumps(state))
    after = _run()
    assert after.get("canon_delivered") == {}


def test_post_compact_preserves_canon_delivered_in_maintenance(preserve_state):
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state["session_type"] = "gameplay"
    state["skip_canon_enforcement"] = True  # maintenance mode -> early exit, no clear
    state["canon_delivered"] = {"voice:Vela": {"h": "abc", "t": 4}}
    STATE.write_text(json.dumps(state))
    after = _run()
    assert after.get("canon_delivered") == {"voice:Vela": {"h": "abc", "t": 4}}
