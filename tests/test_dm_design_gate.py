"""Tests for the dm-design review gate in consolidated_stop_check.py (Task 6).

The gate is the ONE blocking check in the stop runner: forging a *_PREP.md
file arms pending_dm_design and blocks the stop until a dm-design agent
dispatch releases it, the player waives it (skip_dm_design_gate), or
maintenance mode bypasses it (without clearing the obligation).

hook_input fixtures mirror the real runner shape: read_hook_input() returns
the parsed stdin JSON, and every check scans
hook_input["transcript_messages"] -> assistant messages -> content blocks
of {"type": "tool_use", "name": ..., "input": {...}} (see
_check_prep_file_edited / _check_state_changing_tools_called).
"""

import ast
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))

from hooks.consolidated_stop_check import _check_dm_design_gate

# The gate resolves the Active Prep the same way _check_prep_file does.
# Tests patch it for a deterministic active-prep context.
ACTIVE_PREP_TARGET = "hooks.consolidated_stop_check._get_active_prep_file"

HOOK_SOURCE_PATH = (
    Path(__file__).parent.parent / "hooks" / "consolidated_stop_check.py"
)


# ---------------------------------------------------------------------------
# Fixture builders — same transcript shape as the live Stop hook input
# ---------------------------------------------------------------------------

def make_hook_input(tool_uses=None):
    """Build a hook_input with one assistant message containing tool_use blocks.

    tool_uses: list of (tool_name, tool_input_dict)
    """
    content = [{"type": "text", "text": "Some narration."}]
    for name, tool_input in (tool_uses or []):
        content.append({"type": "tool_use", "name": name, "input": tool_input})
    return {
        "session_id": "test-session",
        "transcript_messages": [
            {"role": "user", "content": "do the thing"},
            {"role": "assistant", "content": content},
        ],
    }


def base_state(**overrides):
    state = {
        "turn_count": 7,
        "session_type": "gameplay",
        "skip_canon_enforcement": False,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Trigger + block
# ---------------------------------------------------------------------------

def test_write_prep_arms_and_blocks():
    hook_input = make_hook_input([
        ("Write", {"file_path": "/mnt/c/path/to/campaign/preps/GLASS_GARDEN_PREP.md",
                   "content": "# prep"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert "GLASS_GARDEN_PREP.md" in reason
    assert "dm-design integrate" in reason
    assert "skip review" in reason
    pending = updates.get("pending_dm_design")
    assert pending == {"file": "GLASS_GARDEN_PREP.md", "set_turn": 7}


def test_edit_non_active_prep_arms_and_blocks():
    # Edit-family arms only when the target is NOT the current Active Prep.
    hook_input = make_hook_input([
        ("Edit", {"file_path": "C:\\path\\to\\campaign\\preps\\RUST_VAULT_PREP.md",
                  "old_string": "a", "new_string": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert "RUST_VAULT_PREP.md" in reason
    assert updates["pending_dm_design"]["file"] == "RUST_VAULT_PREP.md"


def test_mcp_update_file_non_active_arms_and_blocks():
    hook_input = make_hook_input([
        ("mcp__rubicon-seven__edit_file",
         {"filename": "preps/HEX_0407_PREP.md", "content": "..."}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "HEX_0407_PREP.md"


def test_mcp_replace_in_file_non_active_arms_and_blocks():
    hook_input = make_hook_input([
        ("mcp__rubicon-seven__edit_file",
         {"filename": "SALT_SPIRE_PREP.md", "old_text": "a", "new_text": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "SALT_SPIRE_PREP.md"


# ---------------------------------------------------------------------------
# Active-prep exemption (progress-log edits must NOT arm the gate)
# ---------------------------------------------------------------------------

def test_edit_active_prep_does_not_arm():
    # Routine progress-log edit to the ACTIVE prep — the _check_prep_file
    # nudge tells the model to do this every state-changing turn.
    hook_input = make_hook_input([
        ("Edit", {"file_path": "/mnt/c/path/to/campaign/preps/GLASS_GARDEN_PREP.md",
                  "old_string": "a", "new_string": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_mcp_edit_active_prep_does_not_arm():
    hook_input = make_hook_input([
        ("mcp__rubicon-seven__edit_file",
         {"filename": "preps/GLASS_GARDEN_PREP.md", "old_text": "a", "new_text": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_write_active_prep_still_arms():
    # A full Write/overwrite of the active prep is forging-scale change.
    hook_input = make_hook_input([
        ("Write", {"file_path": "preps/GLASS_GARDEN_PREP.md", "content": "# rebuilt"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value="GLASS_GARDEN_PREP.md"):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "GLASS_GARDEN_PREP.md"


def test_edit_with_unresolvable_active_prep_does_not_arm():
    # Active prep unknown (None): edit-family must NOT arm, or every
    # progress-log edit while game_state is unreadable would false-positive.
    hook_input = make_hook_input([
        ("Edit", {"file_path": "preps/RUST_VAULT_PREP.md",
                  "old_string": "a", "new_string": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value=None):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_write_with_unresolvable_active_prep_still_arms():
    hook_input = make_hook_input([
        ("Write", {"file_path": "preps/RUST_VAULT_PREP.md", "content": "#"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value=None):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "RUST_VAULT_PREP.md"


def test_non_prep_write_passes_and_does_not_arm():
    hook_input = make_hook_input([
        ("Write", {"file_path": "/tmp/notes.md", "content": "x"}),
        ("Edit", {"file_path": "/tmp/CURRENT_STATUS.md", "old_string": "a",
                  "new_string": "b"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_pending_from_prior_turn_blocks_with_no_tool_uses():
    state = base_state(
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
    )
    hook_input = make_hook_input([])  # nothing happened this turn
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is True
    assert "OLD_RUIN_PREP.md" in reason
    assert "dm-design integrate OLD_RUIN_PREP.md" in reason


# ---------------------------------------------------------------------------
# Release
# ---------------------------------------------------------------------------

def test_agent_dispatch_description_releases():
    state = base_state(
        pending_dm_design={"file": "GLASS_GARDEN_PREP.md", "set_turn": 5},
    )
    hook_input = make_hook_input([
        ("Agent", {"description": "dm-design integrate pass",
                   "prompt": "Review GLASS_GARDEN_PREP.md for narrative soul."}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert "pending_dm_design" in updates
    assert not updates["pending_dm_design"]


def test_task_dispatch_description_releases():
    state = base_state(
        pending_dm_design={"file": "GLASS_GARDEN_PREP.md", "set_turn": 5},
    )
    hook_input = make_hook_input([
        ("Task", {"description": "DM narrative design agent",
                  "prompt": "Review the prep for narrative soul."}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_prompt_only_mention_does_not_release():
    # The release matcher is DESCRIPTION-only: a stray "dm-design" inside a
    # long prompt (e.g. quoting these instructions) must not open the gate.
    state = base_state(
        pending_dm_design={"file": "GLASS_GARDEN_PREP.md", "set_turn": 5},
    )
    hook_input = make_hook_input([
        ("Agent", {"description": "fix the parser bug",
                   "prompt": "Unrelated dev work; mentions dm-design in passing."}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is True


def test_release_beats_trigger_in_same_turn():
    # Forge writes the prep AND dispatches dm-design in one turn: pass, no arm.
    hook_input = make_hook_input([
        ("Write", {"file_path": "preps/NEW_SITE_PREP.md", "content": "#"}),
        ("Agent", {"description": "dm-design integrate NEW_SITE_PREP.md",
                   "prompt": "review it"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


# ---------------------------------------------------------------------------
# Skip (player waiver)
# ---------------------------------------------------------------------------

def test_skip_flag_waives_and_clears_both_keys():
    state = base_state(
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
        skip_dm_design_gate=True,
    )
    hook_input = make_hook_input([])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert "pending_dm_design" in updates and not updates["pending_dm_design"]
    assert "skip_dm_design_gate" in updates
    assert not updates["skip_dm_design_gate"]


def test_skip_flag_beats_fresh_trigger():
    state = base_state(skip_dm_design_gate=True)
    hook_input = make_hook_input([
        ("Write", {"file_path": "preps/FRESH_PREP.md", "content": "#"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert not updates.get("pending_dm_design")
    assert not updates.get("skip_dm_design_gate", False)


# ---------------------------------------------------------------------------
# Bypass (maintenance) — pass WITHOUT clearing pending
# ---------------------------------------------------------------------------

def test_maintenance_mode_bypasses_without_clearing_pending():
    state = base_state(
        maintenance_mode=True,
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
    )
    hook_input = make_hook_input([
        ("Write", {"file_path": "preps/ANOTHER_PREP.md", "content": "#"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    # Obligation survives: the bypass must not touch pending_dm_design.
    assert "pending_dm_design" not in updates


def test_skip_canon_enforcement_bypasses_without_clearing_pending():
    state = base_state(
        skip_canon_enforcement=True,
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
    )
    hook_input = make_hook_input([])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert "pending_dm_design" not in updates


def test_bypass_beats_release():
    # Precedence: bypass first — even a dm-design dispatch must not clear
    # pending while in maintenance mode (the dispatch may be unrelated dev work).
    state = base_state(
        maintenance_mode=True,
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
    )
    hook_input = make_hook_input([
        ("Agent", {"description": "dm-design integrate", "prompt": "x"}),
    ])
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert "pending_dm_design" not in updates


# ---------------------------------------------------------------------------
# Fail-silent
# ---------------------------------------------------------------------------

def test_malformed_hook_input_never_raises():
    garbage_inputs = [
        {},
        {"transcript_messages": "not a list"},
        {"transcript_messages": [None, 42, "string"]},
        {"transcript_messages": [{"role": "assistant", "content": "plain string"}]},
        {"transcript_messages": [{"role": "assistant",
                                  "content": [{"type": "tool_use"},
                                              {"type": "tool_use",
                                               "name": "Write",
                                               "input": "not a dict"}]}]},
        [],          # not even a dict
        None,
        "garbage",
    ]
    for garbage in garbage_inputs:
        blocked, reason, updates = _check_dm_design_gate(garbage, base_state())
        assert blocked is False, f"blocked on garbage input: {garbage!r}"
        assert isinstance(updates, dict)


def test_malformed_state_never_raises():
    hook_input = make_hook_input([])
    # Garbage pending value: must not crash; passing is the fail-silent outcome.
    state = base_state(pending_dm_design=12345)
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False


# ---------------------------------------------------------------------------
# C1: annotated live status line — token extraction, not basename mangling
# ---------------------------------------------------------------------------

# EXACT live Active Prep value from the reviewer's reproduction: annotated
# free text with two preps, one of them a bare stem without .md.
LIVE_STATUS_VALUE = (
    "CERULINE_ARCOLOGY_PREP.md (forward base = ...); "
    "PLANEYFOLK_CONTACT_PREP / _TRUTH for ..."
)


def test_live_status_line_edit_to_first_active_prep_does_not_arm():
    hook_input = make_hook_input([
        ("Edit", {"file_path": "preps/CERULINE_ARCOLOGY_PREP.md",
                  "old_string": "a", "new_string": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value=LIVE_STATUS_VALUE):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_live_status_line_bare_stem_prep_does_not_arm():
    # "PLANEYFOLK_CONTACT_PREP" appears WITHOUT .md in the status value.
    hook_input = make_hook_input([
        ("mcp__rubicon-seven__edit_file",
         {"filename": "preps/PLANEYFOLK_CONTACT_PREP.md",
          "old_text": "a", "new_text": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value=LIVE_STATUS_VALUE):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_live_status_line_edit_to_other_prep_still_arms():
    hook_input = make_hook_input([
        ("Edit", {"file_path": "preps/RUST_VAULT_PREP.md",
                  "old_string": "a", "new_string": "b"}),
    ])
    with patch(ACTIVE_PREP_TARGET, return_value=LIVE_STATUS_VALUE):
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "RUST_VAULT_PREP.md"


# ---------------------------------------------------------------------------
# I1: turn scoping — only tool uses AFTER the last human user message count
# ---------------------------------------------------------------------------

def test_prior_turn_prep_write_in_memory_does_not_arm():
    hook_input = {
        "session_id": "test-session",
        "transcript_messages": [
            {"role": "user", "content": "forge the site"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "preps/OLD_SITE_PREP.md", "content": "#"}},
            ]},
            {"role": "user", "content": "now something unrelated"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Just narration this turn."},
            ]},
        ],
    }
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_prior_turn_dispatch_does_not_release():
    state = base_state(
        pending_dm_design={"file": "OLD_RUIN_PREP.md", "set_turn": 3},
    )
    hook_input = {
        "session_id": "test-session",
        "transcript_messages": [
            {"role": "user", "content": "review it"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Agent",
                 "input": {"description": "dm-design integrate OLD_RUIN_PREP.md",
                           "prompt": "x"}},
            ]},
            {"role": "user", "content": "forge another site"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Narration, no review dispatched."},
            ]},
        ],
    }
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is True


def test_tool_result_user_message_is_not_a_turn_boundary():
    # Mid-turn tool_result messages come back with role "user" in the real
    # transcript; they must NOT reset the turn slice.
    hook_input = {
        "session_id": "test-session",
        "transcript_messages": [
            {"role": "user", "content": "forge the site"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "preps/NEW_SITE_PREP.md", "content": "#"}},
            ]},
            {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "ok"},
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Prep written."},
            ]},
        ],
    }
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


# ---------------------------------------------------------------------------
# C3: real Stop-hook stdin — no transcript_messages, parse transcript_path JSONL
# ---------------------------------------------------------------------------

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


def test_jsonl_prior_turn_prep_write_does_not_arm(tmp_path):
    path = _write_jsonl(tmp_path, [
        _jl_user("forge the site"),
        _jl_assistant([("Write", {"file_path": "preps/OLD_SITE_PREP.md",
                                  "content": "#"})]),
        _jl_user("now something unrelated"),
        _jl_assistant(text="Just narration this turn."),
    ])
    hook_input = {"session_id": "s", "transcript_path": path}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_jsonl_last_turn_prep_write_arms(tmp_path):
    path = _write_jsonl(tmp_path, [
        _jl_user("hello"),
        _jl_assistant(text="hi"),
        _jl_user("forge the site"),
        _jl_assistant([("Write", {"file_path": "preps/NEW_SITE_PREP.md",
                                  "content": "#"})]),
        _jl_tool_result(),
        _jl_assistant(text="Prep written."),
    ])
    hook_input = {"session_id": "s", "transcript_path": path}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


def test_jsonl_last_turn_dispatch_releases(tmp_path):
    state = base_state(
        pending_dm_design={"file": "NEW_SITE_PREP.md", "set_turn": 3},
    )
    path = _write_jsonl(tmp_path, [
        _jl_user("review the prep"),
        _jl_assistant([("Agent", {"description": "DM narrative design agent",
                                  "prompt": "Review NEW_SITE_PREP.md."})]),
    ])
    hook_input = {"session_id": "s", "transcript_path": path}
    blocked, reason, updates = _check_dm_design_gate(hook_input, state)
    assert blocked is False
    assert not updates.get("pending_dm_design")


def test_jsonl_missing_or_garbage_path_fail_silent(tmp_path):
    for bad_path in [str(tmp_path / "nope.jsonl"), "", 42]:
        hook_input = {"session_id": "s", "transcript_path": bad_path}
        blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
        assert blocked is False
    garbage = tmp_path / "garbage.jsonl"
    garbage.write_text("not json\n{broken", encoding="utf-8")
    hook_input = {"session_id": "s", "transcript_path": str(garbage)}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is False


# ---------------------------------------------------------------------------
# N1: reverse tail-read — never parse the whole transcript per stop
# ---------------------------------------------------------------------------

def _filler_assistant_line():
    return json.dumps(_jl_assistant(text="filler narration " + "x" * 150))


def test_tail_reader_returns_lines_from_last_human(tmp_path):
    from hooks.consolidated_stop_check import _tail_lines_to_last_human
    # ~200 filler assistant records, then the real last turn.
    records = [_filler_assistant_line() for _ in range(200)]
    records.append(json.dumps(_jl_user("forge the site")))
    records.append(json.dumps(_jl_assistant(
        [("Write", {"file_path": "preps/NEW_SITE_PREP.md", "content": "#"})])))
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(records), encoding="utf-8")
    lines = _tail_lines_to_last_human(str(p), block_bytes=4096,
                                      max_bytes=1024 * 1024)
    parsed = [json.loads(l) for l in lines if l.strip()]
    assert parsed[0]["message"]["content"][0]["text"] == "forge the site"
    assert parsed[-1]["message"]["content"][-1]["type"] == "tool_use"
    assert len(parsed) == 2  # nothing before the last human prompt


def test_tail_reader_cap_fail_open(tmp_path):
    from hooks.consolidated_stop_check import _tail_lines_to_last_human
    # Human boundary sits beyond the cap: must return [] (fail-open),
    # never fall back to reading the whole file.
    records = [json.dumps(_jl_user("ancient prompt"))]
    records += [_filler_assistant_line() for _ in range(500)]  # ~90KB of tail
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(records), encoding="utf-8")
    lines = _tail_lines_to_last_human(str(p), block_bytes=4096,
                                      max_bytes=16 * 1024)
    assert lines == []


def test_gate_with_large_prefix_still_correct(tmp_path):
    # Big dummy prefix + final forging turn: gate arms on tail data alone.
    records = [_filler_assistant_line() for _ in range(300)]
    records.append(json.dumps(_jl_user("forge the site")))
    records.append(json.dumps(_jl_assistant(
        [("Write", {"file_path": "preps/NEW_SITE_PREP.md", "content": "#"})])))
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(records), encoding="utf-8")
    hook_input = {"session_id": "s", "transcript_path": str(p)}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


# ---------------------------------------------------------------------------
# N2: isMeta records are injected, not human turn boundaries
# ---------------------------------------------------------------------------

def test_jsonl_ismeta_user_record_is_not_a_turn_boundary(tmp_path):
    meta_record = {"type": "user", "isMeta": True,
                   "message": {"role": "user",
                               "content": [{"type": "text",
                                            "text": "<injected reminder>"}]}}
    path = _write_jsonl(tmp_path, [
        _jl_user("forge the site"),
        _jl_assistant([("Write", {"file_path": "preps/NEW_SITE_PREP.md",
                                  "content": "#"})]),
        meta_record,
        _jl_assistant(text="Prep written."),
    ])
    hook_input = {"session_id": "s", "transcript_path": path}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


def test_inmemory_ismeta_user_message_is_not_a_turn_boundary():
    hook_input = {
        "session_id": "s",
        "transcript_messages": [
            {"role": "user", "content": "forge the site"},
            {"role": "assistant", "content": [
                {"type": "tool_use", "name": "Write",
                 "input": {"file_path": "preps/NEW_SITE_PREP.md", "content": "#"}},
            ]},
            {"role": "user", "isMeta": True, "content": "<injected reminder>"},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Prep written."},
            ]},
        ],
    }
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


# ---------------------------------------------------------------------------
# N3: present-but-EMPTY transcript_messages falls back to transcript_path
# ---------------------------------------------------------------------------

def test_empty_transcript_messages_falls_back_to_path(tmp_path):
    path = _write_jsonl(tmp_path, [
        _jl_user("forge the site"),
        _jl_assistant([("Write", {"file_path": "preps/NEW_SITE_PREP.md",
                                  "content": "#"})]),
    ])
    hook_input = {"session_id": "s", "transcript_messages": [],
                  "transcript_path": path}
    blocked, reason, updates = _check_dm_design_gate(hook_input, base_state())
    assert blocked is True
    assert updates["pending_dm_design"]["file"] == "NEW_SITE_PREP.md"


# ---------------------------------------------------------------------------
# C2: turn_reset.py must preserve the gate's state keys across user prompts
# ---------------------------------------------------------------------------

TURN_RESET_HOOK = Path(__file__).resolve().parents[1] / "hooks" / "turn_reset.py"
STATE_FILE = Path(__file__).resolve().parents[1] / "hooks" / ".hook_state.json"


@pytest.fixture
def preserve_hook_state():
    """Back up and restore the live .hook_state.json (same pattern as
    test_turn_reset_canon_delivered.py)."""
    backup = STATE_FILE.read_text() if STATE_FILE.exists() else None
    try:
        yield
    finally:
        if backup is not None:
            STATE_FILE.write_text(backup)
        elif STATE_FILE.exists():
            STATE_FILE.unlink()


def test_turn_reset_preserves_dm_design_gate_keys(preserve_hook_state):
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    state["pending_dm_design"] = {"file": "NEW_SITE_PREP.md", "set_turn": 9}
    state["skip_dm_design_gate"] = True
    state["maintenance_mode"] = True
    STATE_FILE.write_text(json.dumps(state))

    result = subprocess.run(
        [sys.executable, str(TURN_RESET_HOOK)],
        input=json.dumps({"prompt": "I walk to the garden."}),
        text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, f"turn_reset failed: {result.stderr}"

    after = json.loads(STATE_FILE.read_text())
    assert after.get("pending_dm_design") == {"file": "NEW_SITE_PREP.md",
                                              "set_turn": 9}
    assert after.get("skip_dm_design_gate") is True
    assert after.get("maintenance_mode") is True


# ---------------------------------------------------------------------------
# Runner wiring (source-level, same style as test_hook_redesign.py)
# ---------------------------------------------------------------------------

def test_gate_registered_after_canon_before_soft_checks():
    source = HOOK_SOURCE_PATH.read_text(encoding="utf-8")
    main_src = source[source.index("def main()"):]
    canon_idx = main_src.index("_check_canon(")
    gate_idx = main_src.index("_check_dm_design_gate(")
    anti_idx = main_src.index("_check_anti_pattern(")
    assert canon_idx < gate_idx < anti_idx


def test_runner_acts_on_block():
    """main() must exit 2 with the reason on stderr when a check blocks."""
    source = HOOK_SOURCE_PATH.read_text(encoding="utf-8")
    main_src = source[source.index("def main()"):]
    assert "sys.exit(2)" in main_src
    assert "sys.stderr" in main_src
