"""Combat morale-trigger guard (`server._check_morale_triggers`).

Morale is checked once per round when half the enemies are down OR a leader is
killed; on a failed d20+morale vs DC 16 the survivors flee. This reads/writes
the module-global GAME_STATE active_combat, so each test installs a throwaway
combat and restores the previous state afterward. The d20 is monkeypatched for
deterministic pass/fail.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


@pytest.fixture
def combat_slot():
    """Save/restore GAME_STATE['active_combat'] around a test."""
    prev = server.GAME_STATE.get("active_combat")
    yield
    server.GAME_STATE["active_combat"] = prev


def _enemy(defeated=False, fled=False, morale=2):
    return {"defeated": defeated, "fled": fled, "morale": morale}


def _combat(enemies):
    return {"enemies": enemies, "morale_checked": False, "log": []}


def test_no_active_combat_returns_none(combat_slot):
    server.GAME_STATE["active_combat"] = None
    assert server._check_morale_triggers() is None


def test_below_half_defeated_no_trigger(combat_slot):
    server.GAME_STATE["active_combat"] = _combat({
        "a": _enemy(defeated=True), "b": _enemy(), "c": _enemy(), "d": _enemy(),
    })
    assert server._check_morale_triggers() is None  # 1/4 down, no leader


def test_half_defeated_triggers_and_can_succeed(combat_slot, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)  # 20+2 >= 16
    server.GAME_STATE["active_combat"] = _combat({
        "a": _enemy(defeated=True), "b": _enemy(defeated=True),
        "c": _enemy(), "d": _enemy(),
    })
    out = server._check_morale_triggers()
    assert out is not None and "SUCCESS" in out
    assert server.GAME_STATE["active_combat"]["morale_checked"] is True


def test_half_defeated_failure_breaks_morale_and_flees(combat_slot, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # 1+2 < 16
    combat = _combat({
        "a": _enemy(defeated=True), "b": _enemy(defeated=True),
        "c": _enemy(), "d": _enemy(),
    })
    server.GAME_STATE["active_combat"] = combat
    out = server._check_morale_triggers()
    assert "FAILED" in out and combat.get("morale_broken") is True
    assert combat["enemies"]["c"]["fled"] is True


def test_leader_killed_triggers_even_below_half(combat_slot, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
    server.GAME_STATE["active_combat"] = _combat({
        "leader_grik": _enemy(defeated=True),
        "b": _enemy(), "c": _enemy(), "d": _enemy(), "e": _enemy(),
    })
    out = server._check_morale_triggers()
    assert out is not None and "leader killed" in out


def test_already_checked_this_round_returns_none(combat_slot):
    combat = _combat({"a": _enemy(defeated=True), "b": _enemy(defeated=True)})
    combat["morale_checked"] = True
    server.GAME_STATE["active_combat"] = combat
    assert server._check_morale_triggers() is None
