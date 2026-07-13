"""Tests for the narrative-turn classifier in consolidated_stop_check."""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks import consolidated_stop_check as csc


def _mk_hook_input(response_text: str, tool_calls_in_last_msg: int = 0) -> dict:
    """Build a minimal hook_input dict for classifier testing."""
    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": response_text}]
    for _ in range(tool_calls_in_last_msg):
        content_blocks.append({"type": "tool_use", "name": "some_tool", "input": {}})
    return {
        "transcript_messages": [
            {"role": "assistant", "content": content_blocks}
        ],
        "last_assistant_message": response_text,
    }


def test_maintenance_mode_is_not_narrative():
    """skip_canon_enforcement means maintenance — never narrative."""
    hook_input = _mk_hook_input("A" * 1000)
    state = {"skip_canon_enforcement": True}
    assert csc._is_narrative_turn(hook_input, "A" * 1000, state) is False


def test_short_response_is_not_narrative():
    """Responses under 300 chars are acknowledgments, not narrative."""
    short = "Got it. Calling the tool now."
    hook_input = _mk_hook_input(short)
    state = {"skip_canon_enforcement": False}
    assert csc._is_narrative_turn(hook_input, short, state) is False


def test_long_prose_is_narrative():
    """Long prose with no heavy tool-call weight is narrative."""
    long_prose = ("The vine-work at Mira's temple catches the red light. " * 15)  # ~800 chars
    hook_input = _mk_hook_input(long_prose)
    # turn_count > 3 to clear the session-start bypass
    # (consolidated_stop_check.py:164-166 short-circuits the first 4 turns).
    state = {"skip_canon_enforcement": False, "turn_count": 4}
    assert csc._is_narrative_turn(hook_input, long_prose, state) is True


def test_tool_heavy_turn_is_not_narrative():
    """A turn dominated by tool calls is not a narrative turn."""
    long_text = "Checking the lorebook. " * 20  # ~460 chars, clears length gate
    hook_input = _mk_hook_input(long_text, tool_calls_in_last_msg=5)
    state = {"skip_canon_enforcement": False}
    assert csc._is_narrative_turn(hook_input, long_text, state) is False


def test_long_prose_with_minimal_tool_use_is_narrative():
    """Narrative that also has one tool call still counts as narrative."""
    long_prose = ("The arcology hums in its old tongue, a frequency felt through the feet. " * 10)
    hook_input = _mk_hook_input(long_prose, tool_calls_in_last_msg=1)
    # turn_count > 3 to clear the session-start bypass
    # (consolidated_stop_check.py:164-166 short-circuits the first 4 turns).
    state = {"skip_canon_enforcement": False, "turn_count": 4}
    assert csc._is_narrative_turn(hook_input, long_prose, state) is True


def test_empty_response_is_not_narrative():
    """Empty or whitespace-only responses never count."""
    hook_input = _mk_hook_input("   \n  ")
    state = {"skip_canon_enforcement": False}
    assert csc._is_narrative_turn(hook_input, "   \n  ", state) is False


def test_stop_hook_active_suppresses_narrative():
    """Rewrite turns (stop_hook_active=True) do not re-trigger the observer."""
    long_prose = ("Narrative rewrite content. " * 30)
    hook_input = _mk_hook_input(long_prose)
    hook_input["stop_hook_active"] = True
    state = {"skip_canon_enforcement": False}
    assert csc._is_narrative_turn(hook_input, long_prose, state) is False


# ===================================================================
# Spawn integration tests (Task 5)
# ===================================================================

import time
import json as _json
from unittest.mock import MagicMock


def test_spawn_observer_returns_fast(monkeypatch, tmp_path):
    """_spawn_observer must return in <200ms even if observer will run long."""
    monkeypatch.setattr(csc, "_TEMP_DIR", str(tmp_path))

    import subprocess
    calls = []

    def fake_popen(*args, **kwargs):
        calls.append((args, kwargs))
        proc = MagicMock()
        proc.pid = 99999
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    start = time.time()
    csc._spawn_observer(
        response_text="Long narrative prose here." * 50,
        session_id="sess-test",
        turn_id=5,
    )
    elapsed = time.time() - start

    assert elapsed < 0.2, f"spawn took {elapsed}s; should be < 200ms"
    assert len(calls) == 1
    _, kwargs = calls[0]
    # The spawn must be detached. The exact kwargs are platform-specific
    # (POSIX: start_new_session=True; Windows: DETACHED_PROCESS creationflags),
    # so assert against the same cross-platform helper the hook uses.
    from hooks.hook_utils import detached_popen_kwargs
    for key, value in detached_popen_kwargs().items():
        assert kwargs.get(key) == value


def test_spawn_observer_writes_temp_file(monkeypatch, tmp_path):
    """_spawn_observer writes a temp file with session_id, turn_id, response_text."""
    monkeypatch.setattr(csc, "_TEMP_DIR", str(tmp_path))

    import subprocess

    def fake_popen(*args, **kwargs):
        return MagicMock(pid=12345)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    csc._spawn_observer(
        response_text="Scene prose.",
        session_id="sess-write-test",
        turn_id=99,
    )

    temp_files = list(tmp_path.glob("rubicon_observer_sess-write-test_99.json"))
    assert len(temp_files) == 1
    payload = _json.loads(temp_files[0].read_text())
    assert payload["session_id"] == "sess-write-test"
    assert payload["turn_id"] == 99
    assert payload["response_text"] == "Scene prose."
