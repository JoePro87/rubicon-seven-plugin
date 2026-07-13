import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "csc",
    pathlib.Path(__file__).resolve().parent.parent / "hooks" / "consolidated_stop_check.py",
)
csc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(csc)


# ---------------------------------------------------------------------------
# Pure helper: ceruline_session_change
# ---------------------------------------------------------------------------

def test_fires_on_session_end_after_ceruline():
    assert csc.ceruline_session_change("We met Amara in Ceruline.", ["save_state"], False) is True


def test_silent_when_ceruline_not_seen():
    assert csc.ceruline_session_change("A desert trek.", ["save_state"], False) is False


def test_silent_when_not_session_end():
    # Ceruline mentioned but no save/distill this turn -> only sets the seen flag, no fire
    assert csc.ceruline_session_change("In Ceruline today.", ["roll"], False) is False


def test_fires_when_seen_flag_already_set_and_session_ends():
    assert csc.ceruline_session_change("no mention this turn", ["distill_session"], True) is True


def test_prepare_save_state_also_session_end():
    assert csc.ceruline_session_change("Ceruline visit.", ["prepare_save_state"], False) is True


def test_case_insensitive_mention():
    assert csc.ceruline_session_change("Back at CERULINE.", ["save_state"], False) is True


# ---------------------------------------------------------------------------
# Wrapper check: _check_ceruline_reconcile_nudge
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


def test_check_never_blocks():
    hi = _hook_input_with_tools(["save_state"])
    state = {}
    blocked, reason, updates = csc._check_ceruline_reconcile_nudge(
        hi, state, "We were in Ceruline."
    )
    assert blocked is False
    assert reason == ""


def test_check_maintenance_bypass():
    hi = _hook_input_with_tools(["save_state"])
    state = {"skip_canon_enforcement": True}
    blocked, reason, updates = csc._check_ceruline_reconcile_nudge(
        hi, state, "We were in Ceruline."
    )
    assert blocked is False
    assert updates == {}


def test_check_sets_seen_flag_when_mentioned_midsession(capsys):
    # Ceruline mentioned but NOT a session-end turn -> persist seen flag, no print
    hi = _hook_input_with_tools(["roll"])
    state = {}
    blocked, reason, updates = csc._check_ceruline_reconcile_nudge(
        hi, state, "We arrive in Ceruline."
    )
    assert blocked is False
    assert updates.get("ceruline_seen_session") is True
    out = capsys.readouterr().out
    assert "Ceruline came up this session" not in out


def test_check_fires_and_clears_on_session_end(capsys):
    hi = _hook_input_with_tools(["save_state"])
    state = {"ceruline_seen_session": True}
    blocked, reason, updates = csc._check_ceruline_reconcile_nudge(
        hi, state, "Wrapping up."
    )
    assert blocked is False
    out = capsys.readouterr().out
    assert "Ceruline came up this session" in out
    assert "CERULINE_PLAYER_REFERENCE.md" in out
    assert updates.get("ceruline_seen_session") is False


def test_check_silent_when_no_ceruline(capsys):
    hi = _hook_input_with_tools(["save_state"])
    state = {}
    blocked, reason, updates = csc._check_ceruline_reconcile_nudge(
        hi, state, "A quiet desert march."
    )
    assert blocked is False
    out = capsys.readouterr().out
    assert "Ceruline" not in out
    assert updates == {}
