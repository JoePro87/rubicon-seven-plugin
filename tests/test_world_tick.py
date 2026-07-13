"""World Tick - Task 1: thread clocks (wind/clear/list/get).

Covers the optional `clock` dict on narrative-thread records:
- wind on add (clock_due_day > 0), wound_day from introduced_day or campaign day
- wind/rewind/clear on update (-1 clears, 0 no-op)
- resolve drops the clock
- list renders due / fired / pending suffix lines
- get renders a **Clock:** line
"""

import json
import session_tools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


@pytest.fixture(autouse=True)
def _world_tick_env(tmp_path, monkeypatch):
    """Isolated threads file + deterministic campaign day (42)."""
    threads_file = tmp_path / "narrative_threads.json"
    monkeypatch.setattr(server, "THREADS_FILE", threads_file)
    monkeypatch.setattr(session_tools, "THREADS_FILE", server.THREADS_FILE)  # Wave 8 fault-line twin
    monkeypatch.setattr(
        server, "_load_characters",
        lambda: ({"characters": {}, "meta": {"campaign_day": 42}}, None),
    )
    yield threads_file


def _read_threads(threads_file):
    return json.loads(threads_file.read_text(encoding="utf-8"))


def _add(thread_id="vacuum", title="Power Vacuum", **kw):
    return server.thread(
        action="add", thread_id=thread_id, title=title,
        description="The satrap is dead; nobody holds the seal.", **kw,
    )


def test_wind_clock_on_add(_world_tick_env):
    _add(clock_due_day=47, clock_label="power vacuum ripens", introduced_day=41)
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["clock"] == {
        "due_day": 47,
        "label": "power vacuum ripens",
        "wound_day": 41,
        "fired": False,
    }


def test_add_without_clock_has_no_clock_key(_world_tick_env):
    _add()
    data = _read_threads(_world_tick_env)
    assert "clock" not in data["threads"]["vacuum"]


def test_add_clock_wound_day_falls_back_to_campaign_day(_world_tick_env):
    _add(clock_due_day=50, clock_label="ripens")
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["clock"]["wound_day"] == 42


def test_update_winds_clock(_world_tick_env):
    _add()
    result = server.thread(
        action="update", thread_id="vacuum",
        clock_due_day=47, clock_label="power vacuum ripens",
    )
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["clock"] == {
        "due_day": 47,
        "label": "power vacuum ripens",
        "wound_day": 42,
        "fired": False,
    }
    assert "Clock wound: 'power vacuum ripens' due day 47" in result


def test_update_clears_clock(_world_tick_env):
    _add(clock_due_day=47, clock_label="ripens", introduced_day=41)
    result = server.thread(action="update", thread_id="vacuum", clock_due_day=-1)
    data = _read_threads(_world_tick_env)
    assert "clock" not in data["threads"]["vacuum"]
    assert "Clock cleared" in result


def test_update_rewinds_fired_clock(_world_tick_env):
    _add(clock_due_day=40, clock_label="ripens", introduced_day=39)
    raw = _read_threads(_world_tick_env)
    raw["threads"]["vacuum"]["clock"]["fired"] = True
    _world_tick_env.write_text(json.dumps(raw), encoding="utf-8")
    server.thread(action="update", thread_id="vacuum",
                     clock_due_day=60, clock_label="ripens again")
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["clock"] == {
        "due_day": 60,
        "label": "ripens again",
        "wound_day": 42,
        "fired": False,
    }


def test_clock_label_defaults_to_title(_world_tick_env):
    _add(clock_due_day=47)
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["clock"]["label"] == "Power Vacuum"


def test_resolve_drops_clock(_world_tick_env):
    _add(clock_due_day=47, clock_label="ripens")
    server.thread(action="resolve", thread_id="vacuum",
                     resolution="A new satrap is crowned.", resolution_day=45)
    data = _read_threads(_world_tick_env)
    assert "vacuum" in data["resolved"]
    assert "clock" not in data["resolved"]["vacuum"]


def test_list_shows_due_marker(_world_tick_env):
    _add(thread_id="due_one", title="Due Thread",
         clock_due_day=40, clock_label="vacuum ripens")
    _add(thread_id="later_one", title="Later Thread",
         clock_due_day=50, clock_label="caravan arrives")
    _add(thread_id="fired_one", title="Fired Thread",
         clock_due_day=41, clock_label="bomb went off")
    raw = _read_threads(_world_tick_env)
    raw["threads"]["fired_one"]["clock"]["fired"] = True
    _world_tick_env.write_text(json.dumps(raw), encoding="utf-8")

    out = server.thread(action="list", include_resolved=False)
    assert "⏳ DUE (day 40): vacuum ripens" in out
    assert "⏳ caravan arrives - due day 50" in out
    assert "\U0001f514 FIRED day 41 - awaiting narrative surfacing: bomb went off" in out


def test_list_fail_soft_without_characters(_world_tick_env, monkeypatch):
    monkeypatch.setattr(server, "_load_characters",
                        lambda: (None, "characters.json missing"))
    _add(clock_due_day=47, clock_label="ripens")
    out = server.thread(action="list", include_resolved=False)
    # Current day treated as 0 -> nothing due, just pending line.
    assert "ripens - due day 47" in out
    assert "DUE" not in out


def test_get_renders_clock_line(_world_tick_env):
    _add(clock_due_day=47, clock_label="power vacuum ripens", introduced_day=41)
    out = server.thread(action="get", thread_id="vacuum")
    assert "**Clock:**" in out
    assert "power vacuum ripens" in out
    assert "47" in out
    assert "41" in out
    assert "not fired" in out.lower() or "fired: false" in out.lower() or "pending" in out.lower()


# --- Task 2: advance_day WORLD TICK (fire due clocks once, push-only) ------

def test_due_clock_fires_once_on_multiday_jump(_world_tick_env):
    _add(clock_due_day=45, clock_label="power vacuum ripens")
    out = server.advance_day(50, "long march")
    assert "WORLD TICK" in out
    assert "power vacuum ripens" in out
    assert "thread" in out and 'action="get"' in out and "vacuum" in out
    assert "search" in out and 'action="history"' in out
    # Adjudication contract: the push tells the DM to DECIDE, carries the
    # recording call (with the day prefilled), and gates it on live play.
    assert "DECIDE" in out
    assert 'action="update"' in out and "development_day=50" in out
    assert "LIVE NARRATIVE PLAY ONLY" in out
    assert "maintenance" in out  # pillar reminder in the header
    clk = _read_threads(_world_tick_env)["threads"]["vacuum"]["clock"]
    assert clk["fired"] is True
    assert clk["fired_day"] == 50
    # Fired-guard: the next day must not re-fire it.
    out2 = server.advance_day(51, "next day")
    assert "WORLD TICK" not in out2


def test_not_due_clock_silent(_world_tick_env):
    _add(clock_due_day=60, clock_label="caravan arrives")
    out = server.advance_day(50, "march")
    assert "WORLD TICK" not in out
    clk = _read_threads(_world_tick_env)["threads"]["vacuum"]["clock"]
    assert clk["fired"] is False
    assert "fired_day" not in clk


def test_world_tick_never_resolves(_world_tick_env):
    _add(clock_due_day=45, clock_label="ripens")
    server.advance_day(50, "march")
    data = _read_threads(_world_tick_env)
    assert "vacuum" in data["threads"]
    assert data["threads"]["vacuum"].get("status", "active") == "active"
    assert "vacuum" not in data.get("resolved", {})


def test_fired_records_fire_day(_world_tick_env):
    _add(clock_due_day=45, clock_label="ripens", introduced_day=40)
    server.advance_day(50, "jump from 40 to 50")
    clk = _read_threads(_world_tick_env)["threads"]["vacuum"]["clock"]
    assert clk["fired_day"] == 50  # the arrival day, not the due day


def test_malformed_clock_does_not_break_advance_day(_world_tick_env):
    _add()
    raw = _read_threads(_world_tick_env)
    raw["threads"]["vacuum"]["clock"] = "garbage"
    _world_tick_env.write_text(json.dumps(raw), encoding="utf-8")
    out = server.advance_day(50, "march")
    assert out.startswith("Advanced to Day")
    assert "WORLD TICK" not in out
    assert "world tick skipped" not in out



# =========================================================================
# Task 3: supply(action="arrive", location=...) stamps last_visited and
# pushes the book's settlement-changes roll on return after absence.
# The day comes from the supply meta (characters/_meta.json campaign_day),
# the same source the arrive ledger uses.
# =========================================================================

@pytest.fixture(autouse=True)
def _clear_world_tick_state():
    """GAME_STATE is a module-level dict — wipe the world_tick key per test."""
    server.GAME_STATE.pop("world_tick", None)
    yield
    server.GAME_STATE.pop("world_tick", None)


def _seed_supply_meta(day=42):
    """Seed characters/_meta.json in the isolated campaign dir.

    campaign_day here is THE day source for both the arrive ledger and the
    world-tick stamp (they read the same meta dict by design).
    """
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    (chars_dir / "_meta.json").write_text(json.dumps(
        {"version": 1, "campaign_day": day,
         "supply": {"mode": "field", "pool": None, "follower_mouths": 0,
                    "separated": [], "ledger": {"day": day, "consumed": {}}}}))


def test_arrive_stamps_last_visited():
    _seed_supply_meta(day=30)
    out = server.supply(action="arrive", location="Gnomon")
    assert server.GAME_STATE["world_tick"]["last_visited"]["gnomon"] == 30
    assert "days without you" not in out  # first visit: no prior stamp, no changes roll


def test_return_after_threshold_pushes_changes_roll():
    _seed_supply_meta(day=45)
    server.GAME_STATE["world_tick"] = {"last_visited": {"gnomon": 30}}
    out = server.supply(action="arrive", location="Gnomon")
    assert "rulebook" in out
    assert "table-changes-in-gnomon" in out
    assert "<d6>" in out  # Gnomon's changes table is a d6
    assert "table-settlement-changes" not in out  # not the generic d20 table
    assert "15 days" in out
    assert server.GAME_STATE["world_tick"]["last_visited"]["gnomon"] == 45


def test_return_at_exact_threshold_pushes():
    # Pins the boundary: gap == WORLD_TICK_RETURN_DAYS (7) fires (>=, not >).
    _seed_supply_meta(day=45)
    server.GAME_STATE["world_tick"] = {"last_visited": {"gnomon": 38}}
    out = server.supply(action="arrive", location="Gnomon")
    assert "rulebook" in out
    assert "7 days" in out


def test_return_within_threshold_silent():
    _seed_supply_meta(day=45)
    server.GAME_STATE["world_tick"] = {"last_visited": {"gnomon": 40}}
    out = server.supply(action="arrive", location="Gnomon")
    assert "days without you" not in out
    assert server.GAME_STATE["world_tick"]["last_visited"]["gnomon"] == 45


def test_non_gnomon_uses_generic_table():
    _seed_supply_meta(day=45)
    server.GAME_STATE["world_tick"] = {"last_visited": {"bask": 30}}
    out = server.supply(action="arrive", location="Bask")
    assert "table-settlement-changes" in out
    assert "table-changes-in-gnomon" not in out
    assert "<d20>" in out  # generic settlement-changes table is a d20


def test_arrive_without_location_unchanged():
    _seed_supply_meta(day=45)
    out = server.supply(action="arrive")
    assert "abundant" in out.lower()
    assert "days without you" not in out
    assert server.GAME_STATE.get("world_tick", {}).get("last_visited", {}) == {}


def test_day_zero_never_clobbers_a_real_stamp():
    # Fail-soft day source: campaign_day 0 (unreadable/unset meta) must NOT
    # overwrite a genuine last-visited day with 0 — that would make the next
    # real arrival fire a spurious whole-campaign-gap push. Skip entirely.
    _seed_supply_meta(day=0)
    server.GAME_STATE["world_tick"] = {"last_visited": {"gnomon": 30}}
    out = server.supply(action="arrive", location="Gnomon")
    assert "abundant" in out.lower()  # arrive output normal
    assert "days without you" not in out  # no changes push
    assert server.GAME_STATE["world_tick"]["last_visited"]["gnomon"] == 30


def test_stamp_failure_does_not_break_arrive(monkeypatch):
    _seed_supply_meta(day=45)

    def _boom():
        raise RuntimeError("disk on fire")
    monkeypatch.setattr(server, "_save_game_state", _boom)
    out = server.supply(action="arrive", location="Gnomon")
    assert "abundant" in out.lower()  # arrive still completes normally
    assert "WARNING: world-tick stamp skipped" in out


# =========================================================================
# Task 4: WORLD FORCES section in full_session_startup.
# Read-only briefing: fired-unsurfaced clocks persist on EVERY session start
# until a development with day >= fired_day exists (the PILLAR); due/pending
# one-liners; stale-thread summary; section omitted entirely when empty.
# =========================================================================

def _write_threads(threads_file, threads):
    threads_file.write_text(json.dumps(
        {"threads": threads, "resolved": {}, "meta": {}}), encoding="utf-8")


def _thread_rec(title, clock=None, developments=None, introduced_day=40,
                status="active"):
    rec = {
        "title": title,
        "description": "desc",
        "status": status,
        "introduced_day": introduced_day,
        "developments": developments or [],
    }
    if clock is not None:
        rec["clock"] = clock
    return rec


def test_world_forces_section_lists_due_and_pending_in_order(_world_tick_env):
    _write_threads(_world_tick_env, {
        "pend": _thread_rec("Pending Thread", clock={
            "due_day": 50, "label": "caravan arrives",
            "wound_day": 40, "fired": False}),
        "fired": _thread_rec("Fired Thread", clock={
            "due_day": 40, "label": "bomb went off",
            "wound_day": 39, "fired": True, "fired_day": 41},
            developments=[{"text": "old news", "day": 40}]),
        "due": _thread_rec("Due Thread", clock={
            "due_day": 41, "label": "vacuum ripens",
            "wound_day": 40, "fired": False}),
    })
    out = server.full_session_startup()
    assert "WORLD FORCES" in out
    i_fired = out.index("bomb went off")
    i_due = out.index("vacuum ripens")
    i_pend = out.index("caravan arrives")
    assert i_fired < i_due < i_pend
    assert "NOT YET SURFACED" in out
    assert "DUE (day 41)" in out
    assert "due day 50" in out
    for tid in ("fired", "due", "pend"):
        assert f'thread(action="get", thread_id="{tid}")' in out


def test_fired_unsurfaced_persists_across_briefings(_world_tick_env):
    _write_threads(_world_tick_env, {
        "fired": _thread_rec("Fired Thread", clock={
            "due_day": 44, "label": "bomb went off",
            "wound_day": 40, "fired": True, "fired_day": 45},
            developments=[{"text": "before the fire", "day": 44}]),
    })
    out1 = server.full_session_startup()
    assert "bomb went off" in out1 and "NOT YET SURFACED" in out1
    # The clear-hint rides the section whenever a fired item is present.
    assert "clears ONLY by surfacing in-fiction" in out1
    # PILLAR: until surfaced in fiction it reappears on EVERY briefing.
    out2 = server.full_session_startup()
    assert "bomb went off" in out2 and "NOT YET SURFACED" in out2


def test_development_after_fire_day_marks_surfaced(_world_tick_env):
    _write_threads(_world_tick_env, {
        "fired": _thread_rec("Fired Thread", clock={
            "due_day": 44, "label": "bomb went off",
            "wound_day": 40, "fired": True, "fired_day": 45},
            developments=[{"text": "the blast echoes in fiction", "day": 45}]),
    })
    out = server.full_session_startup()
    assert "bomb went off" not in out
    assert "WORLD FORCES" not in out  # only candidate was surfaced


def test_section_omitted_when_no_clocks(_world_tick_env):
    _write_threads(_world_tick_env, {
        "plain": _thread_rec("Plain Thread", introduced_day=41),
        "fresh": _thread_rec("Fresh Thread", introduced_day=40,
                             developments=[{"text": "recent", "day": 41}]),
    })
    out = server.full_session_startup()
    assert "WORLD FORCES" not in out


def test_stale_threads_one_summary_line(_world_tick_env):
    # Day 42; both idle since day <= 22 (20+ days, > the 14-day window).
    _write_threads(_world_tick_env, {
        "old1": _thread_rec("Old One", introduced_day=20),
        "old2": _thread_rec("Old Two", introduced_day=10,
                            developments=[{"text": "long ago", "day": 22}]),
    })
    out = server.full_session_startup()
    assert "WORLD FORCES" in out
    stale_lines = [l for l in out.splitlines() if "stale" in l]
    assert len(stale_lines) == 1
    assert "2 thread" in stale_lines[0]
    assert 'thread(action="list"' in stale_lines[0]


def test_world_forces_readonly(_world_tick_env):
    _write_threads(_world_tick_env, {
        "fired": _thread_rec("Fired Thread", clock={
            "due_day": 40, "label": "bomb went off",
            "wound_day": 39, "fired": True, "fired_day": 41}),
        "due": _thread_rec("Due Thread", clock={
            "due_day": 41, "label": "vacuum ripens",
            "wound_day": 40, "fired": False}),
        "old": _thread_rec("Old One", introduced_day=20),
    })
    before = _world_tick_env.read_bytes()
    server.full_session_startup()
    assert _world_tick_env.read_bytes() == before


def test_stamp_survives_save_load_round_trip():
    # The stamp must survive a server restart: _save_game_state (called by
    # arrive) writes game_state.json; _load_game_state restores world_tick.
    _seed_supply_meta(day=30)
    server.supply(action="arrive", location="Gnomon")
    assert server.GAME_STATE_FILE.exists()
    # Snapshot the in-memory state so the load's side effects on OTHER keys
    # don't leak into later tests, then wipe and reload.
    snapshot = dict(server.GAME_STATE)
    try:
        server.GAME_STATE.pop("world_tick", None)
        assert server._load_game_state() is True
        assert server.GAME_STATE["world_tick"]["last_visited"]["gnomon"] == 30
    finally:
        server.GAME_STATE.clear()
        server.GAME_STATE.update(snapshot)


# --- Generator day-defaults (review follow-up to Task 4) -------------------
# The world-forces briefing's predicates inherit the thread generator's day
# defaults: a day-0 development can never satisfy `day >= fired_day`, and a
# day-0 introduced_day reads as ancient to the stale scan. Both default to
# the current campaign day when unsupplied.


def test_development_day_defaults_to_campaign_day(_world_tick_env):
    _add()
    server.thread(action="update", thread_id="vacuum",
                  development="The seal resurfaces in a pawnshop.")
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["developments"][0]["day"] == 42


def test_introduced_day_defaults_to_campaign_day(_world_tick_env):
    _add()
    data = _read_threads(_world_tick_env)
    assert data["threads"]["vacuum"]["introduced_day"] == 42
