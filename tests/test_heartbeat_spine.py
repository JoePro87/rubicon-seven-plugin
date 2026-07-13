import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server
import pytest


def test_pace_to_due_day_known_paces():
    assert server._pace_to_due_day("hot", 40) == 43
    assert server._pace_to_due_day("warm", 40) == 47
    assert server._pace_to_due_day("cool", 40) == 70


def test_pace_to_due_day_still_and_unknown_are_none():
    assert server._pace_to_due_day("still", 40) is None
    assert server._pace_to_due_day("", 40) is None
    assert server._pace_to_due_day("banana", 40) is None
    assert server._pace_to_due_day("HOT", 40) == 43  # case-insensitive


@pytest.fixture
def _spine_env(tmp_path, monkeypatch):
    npc_file = tmp_path / "npc_states.json"
    npc_file.write_text(json.dumps({"npcs": {
        "minius": {"name": "Minius", "disposition": "friendly",
                   "open_purpose": "Source a dimensional sidearm before the Faa expedition."}
    }, "meta": {"last_updated": "2026-06-17"}}), encoding="utf-8")
    monkeypatch.setattr(server, "NPC_STATE_FILE", npc_file)
    monkeypatch.setattr(server, "_thread_current_day", lambda: 42)
    return npc_file


def _read_npcs(npc_file):
    return json.loads(npc_file.read_text(encoding="utf-8"))["npcs"]


def test_continuity_with_hot_pace_winds_purpose_clock(_spine_env):
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    clk = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert clk == {"due_day": 45, "label": "Source a dimensional sidearm before the Faa expedition.",
                   "wound_day": 42, "pace": "hot", "fired": False}


def test_continuity_still_pace_clears_clock(_spine_env):
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    server._npc_continuity("Minius", "", "", 42, pace="still")
    assert "purpose_clock" not in _read_npcs(_spine_env)["minius"]


def test_continuity_no_pace_leaves_clock_untouched(_spine_env):
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    server._npc_continuity("Minius", "saw him at the bench", "", 43)  # no pace arg
    clk = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert clk["due_day"] == 45 and clk["fired"] is False


def test_continuity_echoes_resolved_due_day(_spine_env):
    out = server._npc_continuity("Minius", "", "", 42, pace="warm")
    assert "fires day 49" in out   # 42 + 7 (warm)


# --- Task 3: advance_day fires due NPC purpose-clocks (stamp + push) --------

@pytest.fixture
def _advance_env(_spine_env, tmp_path, monkeypatch):
    """Extend _spine_env so advance_day runs end-to-end in isolation.

    advance_day touches threads (world tick), characters (photosynthesis /
    world progress / gleam / merc pay), and the module-level GAME_STATE
    world_tick key. Isolate the threads file, stub characters, and wipe the
    world_tick key so the NPC purpose-tick is the only moving part.
    """
    threads_file = tmp_path / "narrative_threads.json"
    monkeypatch.setattr(server, "THREADS_FILE", threads_file)
    import session_tools
    monkeypatch.setattr(session_tools, "THREADS_FILE", server.THREADS_FILE)
    monkeypatch.setattr(
        server, "_load_characters",
        lambda: ({"characters": {}, "meta": {"campaign_day": 42}}, None),
    )
    server.GAME_STATE.pop("world_tick", None)
    yield _spine_env
    server.GAME_STATE.pop("world_tick", None)


def test_advance_day_fires_due_purpose_clock_once(_advance_env, monkeypatch):
    # wind a hot clock (due day 45) as of day 42
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    # campaign now at day 46 -> the clock is due
    out = server.advance_day(46, "two weeks pass in the deep desert")
    npcs = _read_npcs(_advance_env)
    clk = npcs["minius"]["purpose_clock"]
    assert clk["fired"] is True and clk["fired_day"] == 46
    assert "Minius" in out                                  # the person is named in the push
    cwa = npcs["minius"]["changed_while_away"]
    assert cwa["surfaced"] is False                          # fired != surfaced
    # second advance must NOT re-fire: an already-fired clock emits no new PEOPLE tick
    out2 = server.advance_day(47, "another day")
    assert "WORLD TICK — PEOPLE" not in out2


# --- Task 4: briefing surfaces fired-unsurfaced people -------------------------

def test_fired_unsurfaced_person_appears_in_briefing(_advance_env, monkeypatch):
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    server.advance_day(46, "time passes")              # fires + stamps (surfaced False)
    line = server._world_forces_people_lines()          # new pure-ish render helper
    assert any("Minius" in l for l in line)


def test_surfaced_person_drops_from_briefing(_advance_env, monkeypatch):
    server._npc_continuity("Minius", "", "", 42, pace="hot")
    server.advance_day(46, "time passes")
    server._npc_continuity("Minius", "re-engaged", "", 46)   # flips surfaced True
    assert server._world_forces_people_lines() == []


# --- Task 1: Auto-plant + re-arm in the no-pace branch -------------------------

def test_autoplant_purpose_no_clock_winds_default_cool(_spine_env):
    # open_purpose present, no pace, no existing clock -> auto cool (day 42 + 30 = 72)
    out = server._npc_continuity("Minius", "", "", 42)   # no pace
    clk = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert clk == {"due_day": 72, "label": "Source a dimensional sidearm before the Faa expedition.",
                   "wound_day": 42, "pace": "cool", "fired": False}
    assert "auto-set (cool" in out


def test_autoplant_no_purpose_no_clock_stays_clockless(_spine_env, monkeypatch):
    # strip the open_purpose first
    import json as _json
    p = _spine_env
    data = _json.loads(p.read_text()); data["npcs"]["minius"].pop("open_purpose", None)
    p.write_text(_json.dumps(data))
    server._npc_continuity("Minius", "saw him pass", "", 42)   # no purpose, no pace
    assert "purpose_clock" not in _read_npcs(_spine_env)["minius"]


def test_autoplant_unfired_clock_left_untouched(_spine_env):
    server._npc_continuity("Minius", "", "", 42, pace="hot")   # explicit -> due 45
    before = dict(_read_npcs(_spine_env)["minius"]["purpose_clock"])
    server._npc_continuity("Minius", "chatted again", "", 43)  # no pace, clock not fired
    after = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert after == before   # unchanged: due still 45, fired still False


def test_autoplant_fired_clock_rearms_at_existing_pace(_spine_env):
    server._npc_continuity("Minius", "", "", 42, pace="warm")  # due 49
    # simulate a fire
    import json as _json
    data = _json.loads(_spine_env.read_text())
    data["npcs"]["minius"]["purpose_clock"].update({"fired": True, "fired_day": 50})
    _spine_env.write_text(_json.dumps(data))
    # re-engage on day 60, no pace -> re-arm at warm (60 + 7 = 67), fired cleared
    out = server._npc_continuity("Minius", "re-engaged", "", 60)
    clk = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert clk["due_day"] == 67 and clk["fired"] is False and clk["pace"] == "warm"
    assert "fired_day" not in clk
    assert "re-armed (warm" in out


def test_explicit_pace_still_overrides_default(_spine_env):
    out = server._npc_continuity("Minius", "", "", 42, pace="hot")   # explicit hot beats cool default
    clk = _read_npcs(_spine_env)["minius"]["purpose_clock"]
    assert clk["pace"] == "hot" and clk["due_day"] == 45
