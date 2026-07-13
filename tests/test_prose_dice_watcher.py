"""Dice-honesty hardening item 2: prose-dice watcher in the Stop hook
(non-blocking advisory).

Mirrors tests/test_social_stop_nudge.py's import idiom for hook internals
(the hooks/ dir is on sys.path so `consolidated_stop_check` imports as a
top-level module, matching the hook's own `from hooks.hook_utils import ...`
package-relative imports at runtime).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from consolidated_stop_check import (  # noqa: E402
    _check_prose_dice,
    _dice_resolution_language,
    prose_dice_narrated,
)


# ---------------------------------------------------------------------------
# Pure helper: _dice_resolution_language (resolution language, not notation)
# ---------------------------------------------------------------------------

def test_fires_on_give_me_a_roll():
    text = "Give me a roll: **d20 + DEX, with advantage** — beat 15"
    assert _dice_resolution_language(text) is True


def test_fires_on_rolled_a_number():
    assert _dice_resolution_language("You rolled a 17 against the DC.") is True


def test_fires_on_natural_20():
    assert _dice_resolution_language("A natural 20 — the blade finds its mark.") is True


def test_fires_on_roll_tied_to_check():
    assert _dice_resolution_language("The rolls against the DC come up short.") is True


def test_silent_on_weapon_notation_line():
    line = "- **Weapons:** Elegant Saber (d8) · Sniper Rifle (d10)"
    assert _dice_resolution_language(line) is False


def test_silent_on_codex_notation_line():
    line = "- **Codex:** Hypergeometric (INT save DC 15, 4/day…)"
    assert _dice_resolution_language(line) is False


def test_silent_on_gift_notation():
    text = "Kronophage's Echo (d6 HP/use)"
    assert _dice_resolution_language(text) is False


def test_silent_on_plain_narration():
    assert _dice_resolution_language("The party crosses the ruined causeway.") is False


def test_silent_on_empty_or_non_string():
    assert _dice_resolution_language("") is False
    assert _dice_resolution_language(None) is False
    assert _dice_resolution_language(12345) is False


# ---------------------------------------------------------------------------
# Pure helper: prose_dice_narrated (cue + tool-absence gate)
# ---------------------------------------------------------------------------

def test_narrated_fires_with_no_dice_tool():
    text = "Give me a roll: d20 + DEX, beat 15"
    assert prose_dice_narrated(text, ["mcp__rubicon-seven__save_state"]) is True


def test_narrated_silent_when_roll_ran():
    text = "Give me a roll: d20 + DEX, beat 15"
    assert prose_dice_narrated(text, ["mcp__rubicon-seven__roll"]) is False


def test_narrated_silent_when_test_dice_ran():
    text = "Give me a roll: d20 + DEX, beat 15"
    assert prose_dice_narrated(text, ["mcp__rubicon-seven__test_dice"]) is False


def test_narrated_silent_when_combat_ran():
    text = "Give me a roll: d20 + DEX, beat 15"
    assert prose_dice_narrated(text, ["mcp__rubicon-seven__combat"]) is False


def test_narrated_silent_when_map_ran():
    # map counts -- its encounter die is real engine randomness.
    text = "Give me a roll: d20 + DEX, beat 15"
    assert prose_dice_narrated(text, ["mcp__rubicon-seven__map"]) is False


def test_narrated_silent_when_no_cue_at_all():
    assert prose_dice_narrated("The party rests for the night.", []) is False


# ---------------------------------------------------------------------------
# Wrapper check: _check_prose_dice
# ---------------------------------------------------------------------------

def _hook_input_with_tools(tool_names):
    """Build a minimal hydrated hook_input whose assistant message carries the
    given tool_use names (matches what _iter_assistant_tool_uses reads)."""
    return {
        "transcript_messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": name, "input": {}}
                    for name in tool_names
                ],
            }
        ]
    }


def test_check_never_blocks(capsys):
    hi = _hook_input_with_tools([])
    state = {}
    blocked, reason, updates = _check_prose_dice(
        hi, state, "Give me a roll: d20 + DEX, beat 15"
    )
    assert blocked is False
    assert reason == ""
    assert updates == {}


def test_check_fires_advisory_when_no_dice_tool(capsys):
    hi = _hook_input_with_tools(["mcp__rubicon-seven__save_state"])
    state = {}
    _check_prose_dice(hi, state, "Give me a roll: **d20 + DEX, with advantage** — beat 15")
    out = capsys.readouterr().out
    assert "dice narrated without an engine roll" in out
    assert "roll(...)" in out


def test_check_silent_when_roll_tool_ran(capsys):
    hi = _hook_input_with_tools(["mcp__rubicon-seven__roll"])
    state = {}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_when_test_dice_ran(capsys):
    hi = _hook_input_with_tools(["mcp__rubicon-seven__test_dice"])
    state = {}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_when_combat_ran(capsys):
    hi = _hook_input_with_tools(["mcp__rubicon-seven__combat"])
    state = {}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_when_map_ran(capsys):
    hi = _hook_input_with_tools(["mcp__rubicon-seven__map"])
    state = {}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_on_sheet_notation(capsys):
    hi = _hook_input_with_tools([])
    state = {}
    for line in (
        "- **Weapons:** Elegant Saber (d8) · Sniper Rifle (d10)",
        "- **Codex:** Hypergeometric (INT save DC 15, 4/day…)",
        "Kronophage's Echo (d6 HP/use)",
    ):
        _check_prose_dice(hi, state, line)
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_in_maintenance_mode(capsys):
    hi = _hook_input_with_tools([])
    state = {"maintenance_mode": True}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_silent_via_legacy_skip_canon_flag(capsys):
    hi = _hook_input_with_tools([])
    state = {"skip_canon_enforcement": True}
    _check_prose_dice(hi, state, "Give me a roll: d20 + DEX, beat 15")
    out = capsys.readouterr().out
    assert out == ""


def test_check_never_raises_on_garbage_input():
    garbage_inputs = [
        (None, {}, None),
        ("not a dict", {}, 12345),
        ({"transcript_messages": "not a list"}, None, object()),
        ({"transcript_messages": [{"role": "assistant", "content": "oops"}]}, {}, ""),
        ({"transcript_messages": [123, "x", {"role": "assistant"}]}, {}, "roll something"),
    ]
    for hi, state, text in garbage_inputs:
        blocked, reason, updates = _check_prose_dice(hi, state, text)
        assert blocked is False
        assert reason == ""
        assert updates == {}
