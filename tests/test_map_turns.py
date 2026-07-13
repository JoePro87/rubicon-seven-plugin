"""Tests for map_system turn-tracking and auto-encounter checks (ported from explore)."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem


PREP = """## ROOM: entrance
**Floor:** 1
**Coords:** 5,5
**Name:** Entrance Hall
**Entrance:** true
**Connections:** e→gallery

## ROOM: gallery
**Floor:** 1
**Coords:** 6,5
**Name:** Gallery
**Connections:** w→entrance

## ENCOUNTERS
Roll d6 every 1 turn
"""


@pytest.fixture
def map_dir(tmp_path):
    prep = tmp_path / "TEST_VAULT_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    m.init_map_from_prep("testvault", "TEST_VAULT_PREP.md", "vault")
    return m


def test_initial_turn_is_zero(map_dir):
    state = map_dir.get_map_state("testvault")
    assert state["current_turn"] == 0
    assert state["noise_level"] == "standard"
    assert state["has_light"] is True


def test_enter_room_costs_one_turn_with_light(map_dir):
    map_dir.enter_room("testvault", "gallery")
    state = map_dir.get_map_state("testvault")
    assert state["current_turn"] == 1


def test_enter_room_costs_three_turns_in_darkness(map_dir):
    map_dir.set_light("testvault", False)
    map_dir.enter_room("testvault", "gallery")
    state = map_dir.get_map_state("testvault")
    assert state["current_turn"] == 3


def test_search_costs_one_turn(map_dir):
    map_dir.enter_room("testvault", "gallery")
    map_dir.search_room("testvault", "gallery")
    state = map_dir.get_map_state("testvault")
    assert state["current_turn"] == 2  # 1 move + 1 search


def test_search_blocked_in_darkness(map_dir):
    map_dir.set_light("testvault", False)
    result = map_dir.search_room("testvault", "entrance")
    assert "without light" in result.lower() or "darkness" in result.lower()


def test_encounter_roll_recorded(map_dir):
    map_dir.enter_room("testvault", "gallery")
    state = map_dir.get_map_state("testvault")
    assert len(state["encounters_rolled"]) == 1
    rec = state["encounters_rolled"][0]
    assert rec["formula"] == "1d6"
    assert 1 <= rec["roll"] <= 6


def test_roll_one_yields_encounter(map_dir, monkeypatch):
    import random
    monkeypatch.setattr(random.SystemRandom, "randint", lambda self, a, b: 1)
    out = map_dir.enter_room("testvault", "gallery")
    assert "ENCOUNTER" in out.upper()


def test_roll_two_yields_omen(map_dir, monkeypatch):
    import random
    monkeypatch.setattr(random.SystemRandom, "randint", lambda self, a, b: 2)
    out = map_dir.enter_room("testvault", "gallery")
    assert "OMEN" in out.upper()


def test_roll_high_yields_nothing(map_dir, monkeypatch):
    import random
    monkeypatch.setattr(random.SystemRandom, "randint", lambda self, a, b: 5)
    out = map_dir.enter_room("testvault", "gallery")
    assert "ENCOUNTER" not in out.upper() and "OMEN" not in out.upper()


def test_noisy_uses_two_dice(map_dir, monkeypatch):
    import random
    monkeypatch.setattr(random.SystemRandom, "randint", lambda self, a, b: 4)
    map_dir.set_noise("testvault", "noisy")
    map_dir.enter_room("testvault", "gallery")
    state = map_dir.get_map_state("testvault")
    assert state["encounters_rolled"][-1]["formula"] == "2d6"


def test_set_noise_rejects_bad_value(map_dir):
    out = map_dir.set_noise("testvault", "whisper")
    assert "must be" in out.lower() or "standard" in out.lower()
