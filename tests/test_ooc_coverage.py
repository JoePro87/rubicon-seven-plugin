"""OOC coverage — the regression that names the 2026-07-24 failure (spec §F.5).

On a turn of pure out-of-character exposition, the number of gates that could
BLOCK a canon fabrication was zero. That is why ten turns of invention flowed
through uninterrupted. These tests assert the hole is closed.
"""
import importlib
import inspect
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _csc(tmp_path=None, monkeypatch=None):
    """Reload the stop check, optionally pointed at a hermetic fake campaign.

    conftest isolates RUBICON_CAMPAIGN_DIR to a temp dir, and
    _check_spatial_source WRITES the session register — so these tests stage
    their own minimal campaign rather than reading (or touching) the real one.
    """
    import hooks.consolidated_stop_check as csc
    csc = importlib.reload(csc)
    if tmp_path is not None:
        (tmp_path / "VAARN_GEOGRAPHY.json").write_text(json.dumps({
            "locations": {"ceruline": {}, "thyricost": {}},
            "regions": {"central_wastes": {}},
        }), encoding="utf-8")
        (tmp_path / "maps").mkdir(exist_ok=True)
        (tmp_path / "maps" / "thyricost_map.json").write_text(json.dumps({
            "map_name": "Thyricost", "rooms": {"a": {"name": "Root Gallery"}},
            "revealed_ledger": [],
        }), encoding="utf-8")
        (tmp_path / "npc_states.json").write_text(json.dumps({
            "npcs": {"thresh": {"name": "Thresh"}, "kess": {"name": "Kess"}},
        }), encoding="utf-8")
        monkeypatch.setattr(csc, "CAMPAIGN_DIR", tmp_path)
        # Force a lexicon rebuild against the staged dir.
        from hooks import place_lexicon
        place_lexicon._LEXICON_CACHE["key"] = None
    return csc


def _hook_input(tool_names=()):
    return {"transcript_messages": [{
        "role": "assistant",
        "content": [{"type": "tool_use", "name": n, "input": {}} for n in tool_names],
    }]}


GAMEPLAY = {"maintenance_mode": False, "session_type": "gameplay", "session_id": "t1"}

# Plain OOC exposition: no quotes, no "What do you do?", and carrying the very
# meta-signal words ("check_canon", "hook") that used to buy a free pass.
OOC_SPATIAL = (
    "To orient you out-of-character, before I call check_canon or trip a hook: "
    "Thyricost sits due west of Ceruline, and the fold comes out on the far side."
)
OOC_ATTRIBUTED = (
    "Out of character, so the record is clear before any hook or check_canon run: "
    "Thresh told you the keeper is fair, that the price is not fixed in advance, "
    "and that a caravan pays more than a pilgrim."
)


def test_ooc_spatial_exposition_blocks(tmp_path, monkeypatch):
    csc = _csc(tmp_path, monkeypatch)
    blocked, reason, _ = csc._check_spatial_source(
        _hook_input(), dict(GAMEPLAY), OOC_SPATIAL)
    assert blocked, "OOC exposition asserting a bearing must block"
    assert "SPATIAL" in reason
    assert "not established" in reason


def test_ooc_spatial_exposition_passes_with_geography_call(tmp_path, monkeypatch):
    csc = _csc(tmp_path, monkeypatch)
    blocked, _, _ = csc._check_spatial_source(
        _hook_input(["mcp__rubicon-seven__geography"]), dict(GAMEPLAY), OOC_SPATIAL)
    assert not blocked


def test_ooc_attributed_claim_blocks(tmp_path, monkeypatch):
    csc = _csc(tmp_path, monkeypatch)
    blocked, reason, _ = csc._check_attributed_claims(
        _hook_input(), dict(GAMEPLAY), OOC_ATTRIBUTED)
    assert blocked, "OOC exposition laundering a claim through an NPC must block"
    assert "ATTRIBUTED" in reason


def test_ooc_attributed_claim_passes_with_search_call(tmp_path, monkeypatch):
    csc = _csc(tmp_path, monkeypatch)
    blocked, _, _ = csc._check_attributed_claims(
        _hook_input(["mcp__rubicon-seven__search"]), dict(GAMEPLAY), OOC_ATTRIBUTED)
    assert not blocked


@pytest.mark.parametrize("check", ["_check_spatial_source", "_check_attributed_claims"])
def test_only_sanctioned_exemptions(check, tmp_path, monkeypatch):
    """Maintenance, non-gameplay and meta-only are the ONLY ways out."""
    csc = _csc(tmp_path, monkeypatch)
    fn = getattr(csc, check)
    text = OOC_SPATIAL if "spatial" in check else OOC_ATTRIBUTED
    assert not fn(_hook_input(), {**GAMEPLAY, "maintenance_mode": True}, text)[0]
    assert not fn(_hook_input(), {**GAMEPLAY, "session_type": "development"}, text)[0]
    assert not fn(_hook_input(), dict(GAMEPLAY), f"({text})")[0]


def test_new_gates_do_not_consult_the_narrative_turn_filters():
    """_is_narrative_turn's 300-char floor / turn_count<=3 bypass / tool-heavy
    ratio would each independently have let the 2026-07-24 turns through."""
    csc = _csc()
    for name in ("_check_spatial_source", "_check_attributed_claims"):
        src = inspect.getsource(getattr(csc, name))
        assert "_is_narrative_turn" not in src, f"{name} must not use _is_narrative_turn"


def test_short_ooc_turn_still_blocks(tmp_path, monkeypatch):
    """No length floor: a one-line bearing is exactly the failure class."""
    csc = _csc(tmp_path, monkeypatch)
    blocked, _, _ = csc._check_spatial_source(
        _hook_input(), {**GAMEPLAY, "turn_count": 1},
        "Thyricost is due west of Ceruline.")
    assert blocked


def test_npc_fabrication_meta_signal_skip_is_gone():
    """C.2: the >=2-engineering-words bypass was deleted."""
    csc = _csc()
    src = inspect.getsource(csc._check_npc_fabrication)
    assert "meta_signals" not in src
    assert "meta_count" not in src


def test_in_dialogue_fabrication_can_now_block():
    """C.3: it used to compute a violation and discard it unconditionally."""
    csc = _csc()
    src = inspect.getsource(csc._check_in_dialogue_fabrication)
    assert "return True, reason, {}" in src


def test_main_registers_both_gates_before_the_advisory_checks():
    csc = _csc()
    src = inspect.getsource(csc.main)
    for name in ("_check_spatial_source", "_check_attributed_claims"):
        assert name in src, f"{name} not registered in main()"
    assert (src.index("_check_mechanics_source")
            < src.index("_check_spatial_source")
            < src.index("_check_attributed_claims")
            < src.index("_check_anti_pattern")), "gate ordering wrong"
