"""Port of the soft stop checks onto the real Stop-hook transcript.

Real Claude Code Stop-hook stdin provides transcript_path (a JSONL file),
NOT transcript_messages. The dm-design gate already handles this via
_get_turn_messages; the legacy soft checks (response text, state-changing
tools, canon-was-called, narrative classifier, NPC tool-target scan) read
hook_input["transcript_messages"] directly and were silent no-ops live.

The fix: _hydrate_transcript_messages(hook_input) populates the in-memory
key once from the same tail-read, so every legacy reader works unchanged.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from consolidated_stop_check import (  # noqa: E402
    _check_canon_was_called,
    _check_prep_file_edited,
    _check_state_changing_tools_called,
    _get_response_text,
    _hydrate_transcript_messages,
    _is_narrative_turn,
)


# --- JSONL record builders (same shape as the real transcript) -----------

def _jl_user(text):
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "text", "text": text}]}}


def _jl_tool_result():
    return {"type": "user",
            "message": {"role": "user",
                        "content": [{"type": "tool_result",
                                     "tool_use_id": "t1", "content": "ok"}]}}


def _jl_assistant(tool_uses=None, text="Narration."):
    content = [{"type": "text", "text": text}]
    for name, tool_input in (tool_uses or []):
        content.append({"type": "tool_use", "name": name, "input": tool_input})
    return {"type": "assistant",
            "message": {"role": "assistant", "content": content}}


def _write_jsonl(tmp_path, records):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return str(p)


def _real_stdin(tmp_path, records):
    """Hook input shaped like real Stop-hook stdin: path only, no messages."""
    return {"session_id": "s",
            "transcript_path": _write_jsonl(tmp_path, records)}


# --- Hydration behavior ---------------------------------------------------

def test_hydrate_populates_turn_messages_from_path(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("old turn"),
        _jl_assistant(text="old narration"),
        _jl_user("this turn"),
        _jl_assistant([("mcp__rubicon-seven__save_state", {"action": "save"})],
                      text="Saved."),
    ])
    _hydrate_transcript_messages(hook_input)
    messages = hook_input["transcript_messages"]
    # This turn only: the assistant message after the last human prompt
    assert len(messages) == 1
    assert messages[0]["role"] == "assistant"


def test_hydrate_leaves_inmemory_transcript_alone(tmp_path):
    in_memory = [{"role": "assistant", "content": [{"type": "text", "text": "hi"}]}]
    hook_input = {"session_id": "s",
                  "transcript_messages": in_memory,
                  "transcript_path": _write_jsonl(tmp_path, [
                      _jl_user("x"), _jl_assistant(text="from disk")])}
    _hydrate_transcript_messages(hook_input)
    assert hook_input["transcript_messages"] is in_memory


def test_hydrate_fail_open_on_bad_path(tmp_path):
    for bad in [str(tmp_path / "nope.jsonl"), "", 42, None]:
        hook_input = {"session_id": "s", "transcript_path": bad}
        _hydrate_transcript_messages(hook_input)
        assert not hook_input.get("transcript_messages")


# --- Downstream consumers come alive on real-shaped stdin ----------------

def test_response_text_from_real_stdin(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("narrate"),
        _jl_assistant(text="The vault door grinds open."),
    ])
    _hydrate_transcript_messages(hook_input)
    assert "vault door" in _get_response_text(hook_input)


def test_state_changing_tools_seen_from_real_stdin(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("attack it"),
        _jl_assistant([("mcp__rubicon-seven__combat",
                        {"action": "attack"})], text="You strike."),
        _jl_tool_result(),
        _jl_assistant(text="The blow lands."),
    ])
    _hydrate_transcript_messages(hook_input)
    tools = _check_state_changing_tools_called(hook_input)
    assert "mcp__rubicon-seven__combat" in tools


def test_prior_turn_tools_not_seen(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("attack it"),
        _jl_assistant([("mcp__rubicon-seven__combat",
                        {"action": "attack"})], text="You strike."),
        _jl_user("just chat now"),
        _jl_assistant(text="Sure, talking only."),
    ])
    _hydrate_transcript_messages(hook_input)
    assert _check_state_changing_tools_called(hook_input) == []


def test_canon_was_called_from_real_stdin(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("go on"),
        _jl_assistant([("mcp__rubicon-seven__check_canon",
                        {"query": "scene"})], text="Checking."),
    ])
    _hydrate_transcript_messages(hook_input)
    assert _check_canon_was_called(hook_input, {}) is True


def test_prep_file_edit_seen_from_real_stdin(tmp_path):
    hook_input = _real_stdin(tmp_path, [
        _jl_user("log progress"),
        _jl_assistant([("mcp__rubicon-seven__edit_file",
                        {"filename": "preps/SITE_PREP.md",
                         "content": "x"})], text="Updated."),
    ])
    _hydrate_transcript_messages(hook_input)
    assert _check_prep_file_edited(hook_input, "SITE_PREP.md") is True


def test_narrative_classifier_tool_heavy_from_real_stdin(tmp_path):
    long_text = "scene " * 80  # clears the min-length bar
    hook_input = _real_stdin(tmp_path, [
        _jl_user("do things"),
        _jl_assistant(
            [("mcp__rubicon-seven__roll", {"action": "encounter"}),
             ("mcp__rubicon-seven__combat", {"action": "attack"})],
            text=long_text),
    ])
    _hydrate_transcript_messages(hook_input)
    state = {"turn_count": 10}
    # 2 tool blocks vs 1 text block -> tool-heavy -> not narrative
    assert _is_narrative_turn(hook_input, long_text, state) is False
