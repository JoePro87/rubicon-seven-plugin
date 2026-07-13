"""C17 — chargen starting_boon dead pushes.

data/content_forge_tables.json /tables/starting_boon annotated its boons with
INVALID tool calls (cybernetic(action='random'), gift(action='random'),
codex(action='random'), roll_exotica(), generate_weapon()). content_forge
relays the Boon field verbatim, so a fresh DM following the push hit "Invalid
action". This guard asserts every action-style push in starting_boon parses to
a live tool + a valid action, and that the retired internal-function names are
gone.
"""
import json
import re
from pathlib import Path

# reuse the wiring-gate harvester so the vocab source can't drift from the gate
from test_skill_tool_names import (
    _harvest_tool_actions,
    _tool_fns,
    ACTION_VALUE_RE,
)

ROOT = Path(__file__).resolve().parents[1]
CALL_RE = re.compile(r"`([a-z_]+)\(")


def _boon_texts():
    d = json.loads((ROOT / "data" / "content_forge_tables.json").read_text(encoding="utf-8"))
    return [e["fields"]["Boon"] for e in d["tables"]["starting_boon"]["entries"]]


def test_no_retired_internal_function_pushes():
    blob = " ".join(_boon_texts())
    for dead in ("generate_weapon(", "roll_exotica(", "action='random'", 'action="random"'):
        assert dead not in blob, f"retired push still present: {dead}"


def test_every_action_push_is_live_tool_and_action():
    fns = _tool_fns()
    vocab = {}
    bad = []
    for text in _boon_texts():
        for name, action in ACTION_VALUE_RE.findall(text):
            assert name in fns, f"{name} is not a registered tool (boon: {text!r})"
            if name not in vocab:
                vocab[name] = _harvest_tool_actions(fns[name])
            valid = vocab[name]
            if valid and action not in valid:
                bad.append(f"{name}(action=\"{action}\") not valid; accepts {sorted(valid)}")
    assert not bad, "starting_boon pushes dead actions:\n" + "\n".join(bad)


def test_every_backticked_call_names_a_registered_tool():
    # catches bare-function pushes like generate_weapon() that ACTION_VALUE_RE misses
    fns = _tool_fns()
    allowed_non_action = set()  # every boon call is action-style now
    bad = []
    for text in _boon_texts():
        for name in CALL_RE.findall(text):
            if name not in fns and name not in allowed_non_action:
                bad.append(f"{name}() in boon {text!r} is not a registered tool")
    assert not bad, "\n".join(bad)
