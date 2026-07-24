"""A0.2 mechanics-from-tools detector (spec §4; failure report F6/F7/F9 class)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.mechanics_source_gate import scan_unbacked_mechanics, TICKER_HEADER  # noqa: E402


def test_hp_cost_without_tool_flags():
    hits = scan_unbacked_mechanics("The thread bites deep. You lose 12 HP.", [])
    assert len(hits) == 1 and "12 HP" in hits[0]


def test_hp_cost_with_gift_call_passes():
    assert scan_unbacked_mechanics("The thread bites deep. You lose 4 HP.", ["gift"]) == []


def test_forced_check_without_roll_flags():
    hits = scan_unbacked_mechanics("The fold pins you — make a STR check.", [])
    assert hits and "check" in hits[0].lower()


def test_ticker_block_is_exempt():
    text = ("The blow lands hard.\n\n" + TICKER_HEADER + "\n   Thornback: 4 damage (12/16 HP)")
    assert scan_unbacked_mechanics(text, []) == []


def test_house_rule_label_needs_rulebook():
    hits = scan_unbacked_mechanics("Trading exotica for XP is a house rule we use.", [])
    assert hits and "house" in hits[0].lower()
    assert scan_unbacked_mechanics("Trading exotica for XP is a house rule we use.", ["rulebook"]) == []


def test_condition_applied_needs_tool():
    hits = scan_unbacked_mechanics("Without sunlight you are now Deprived.", [])
    assert hits
    assert scan_unbacked_mechanics("Without sunlight you are now Deprived.", ["affliction"]) == []


def test_pure_atmosphere_passes():
    text = ("The corridor smells of brine and ozone. The walls pulse faintly, "
            "and somewhere below, water moves against stone.")
    assert scan_unbacked_mechanics(text, []) == []


def test_header_matches_ticker_module():
    import mechanics_ticker
    assert TICKER_HEADER == mechanics_ticker.TICKER_HEADER


# ---------------------------------------------------------------------------
# Task 5: the blocking Stop check _check_mechanics_source
# ---------------------------------------------------------------------------


def _stop_mod():
    import importlib
    import hooks.consolidated_stop_check as csc
    return importlib.reload(csc)


def _hook_input_with_tools(names):
    """Minimal hydrated hook_input whose assistant message carries the given
    tool_use names — the same transcript shape _iter_assistant_tool_uses reads
    (copied from tests/test_prose_dice_watcher.py)."""
    return {
        "transcript_messages": [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "name": name, "input": {}}
                    for name in names
                ],
            }
        ]
    }


def test_stop_check_blocks_unbacked_hp(tmp_path, monkeypatch):
    csc = _stop_mod()
    blocked, reason, _ = csc._check_mechanics_source(
        _hook_input_with_tools([]), {"maintenance_mode": False},
        "The thread bites. You lose 12 HP.")
    assert blocked and "12 HP" in reason


def test_stop_check_passes_with_backing_tool(tmp_path):
    csc = _stop_mod()
    blocked, _, _ = csc._check_mechanics_source(
        _hook_input_with_tools(["gift"]), {"maintenance_mode": False},
        "The thread bites. You lose 4 HP.")
    assert not blocked


def test_stop_check_passes_with_prefixed_tool_name():
    # Real transcripts carry the mcp__rubicon-seven__ prefix; the check strips it.
    csc = _stop_mod()
    blocked, _, _ = csc._check_mechanics_source(
        _hook_input_with_tools(["mcp__rubicon-seven__gift"]),
        {"maintenance_mode": False},
        "The thread bites. You lose 4 HP.")
    assert not blocked


def test_stop_check_muted_in_maintenance():
    csc = _stop_mod()
    blocked, _, _ = csc._check_mechanics_source(
        _hook_input_with_tools([]), {"maintenance_mode": True},
        "You lose 12 HP.")
    assert not blocked


def test_stop_check_ignores_non_narrative_turns():
    csc = _stop_mod()
    blocked, _, _ = csc._check_mechanics_source(
        _hook_input_with_tools([]), {"maintenance_mode": False},
        "(meta: yes, the suite passed — 12 HP was the bug)")
    assert not blocked


def test_stop_check_reason_caps_at_four_and_names_ticker():
    csc = _stop_mod()
    # Five distinct unbacked mechanic classes; reason lists at most four.
    text = (
        "You lose 12 HP. He has AV 3. Make a STR check. Roll 2d6. "
        "This is a house rule."
    )
    blocked, reason, _ = csc._check_mechanics_source(
        _hook_input_with_tools([]), {"maintenance_mode": False}, text)
    assert blocked
    assert reason.count("MECHANICS WITHOUT TOOL:") <= 4
    assert ">> MECHANICS" in reason
