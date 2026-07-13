"""The unified maintenance bypass: in_maintenance() honors BOTH state keys.

Before this helper, ~11 bypass points checked only `skip_canon_enforcement`,
while a separate `maintenance_mode` key was honored at exactly one (the
dm-design gate). So anything that set `maintenance_mode` alone left most of the
prose layer running. in_maintenance() makes every bypass point honor both keys.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))

from hooks.hook_utils import in_maintenance  # noqa: E402
import consolidated_stop_check as csc  # noqa: E402
from consolidated_stop_check import _check_semantic_observer  # noqa: E402


def test_helper_honors_both_keys():
    assert in_maintenance({"skip_canon_enforcement": True}) is True
    assert in_maintenance({"maintenance_mode": True}) is True
    assert in_maintenance({"maintenance_mode": True,
                           "skip_canon_enforcement": False}) is True
    assert in_maintenance({}) is False
    assert in_maintenance({"skip_canon_enforcement": False,
                           "maintenance_mode": False}) is False


def test_helper_fail_open_on_non_dict():
    assert in_maintenance(None) is False
    assert in_maintenance("nope") is False


def test_observer_muted_by_maintenance_mode_key_alone(monkeypatch):
    """The bug fix: maintenance_mode alone now mutes the critic (it didn't before)."""
    spawned = []
    monkeypatch.setattr(csc, "_spawn_observer",
                        lambda text, sid, tid: spawned.append(text))
    long_text = "The vault yawns wide and the dust settles slowly. " * 8
    hook_input = {"session_id": "s", "transcript_messages": [
        {"role": "assistant", "content": [{"type": "text", "text": long_text}]}]}
    _check_semantic_observer(hook_input,
                             {"turn_count": 9, "maintenance_mode": True},
                             long_text)
    assert spawned == []
