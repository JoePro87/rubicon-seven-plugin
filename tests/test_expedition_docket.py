"""Expedition Docket (2026-07-20): per-track state on a site's map JSON, the
docket injection above the revealed ledger, the player-facing render, and the
ledger write-time dedup. Tracks are the party's open business at a site — one
strand each, with a status stamp — surfaced every vault/prep turn so ~8 live
tracks stop collapsing invisible. See docs/superpowers/specs/2026-07-20-*.md."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem, register_map_tools
import server


PREP = """## ROOM: room_a
**Floor:** 1
**Coords:** 5,5
**Name:** Room A
**Entrance:** true
**Connections:** e→room_b

## ROOM: room_b
**Floor:** 1
**Coords:** 6,5
**Name:** Room B
**Connections:** w→room_a

## ENCOUNTERS
Roll d6 every 1 turn
"""


@pytest.fixture
def map_sys(tmp_path):
    ms = MapSystem(tmp_path)
    ms.get_day = lambda: 135
    return ms


@pytest.fixture
def sitemap(map_sys, tmp_path):
    prep = tmp_path / "TEST_DOCKET_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    map_sys.init_map_from_prep("thyricost", "TEST_DOCKET_PREP.md", "vault")
    return "thyricost"


def _capture_map_tool(campaign_dir, day=135):
    """Register the map tool against a fake MCP and return (map_fn, map_sys)."""
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    ms = register_map_tools(_FakeMCP(), campaign_dir)
    ms.get_day = lambda: day
    return captured["map"], ms


# ---------------------------------------------------------------------------
# A1 — track CRUD
# ---------------------------------------------------------------------------

def test_track_add_creates_and_persists(map_sys, sitemap):
    out = map_sys.track_add(sitemap, "departure_petitions", "Departure petitions",
                            stand="3 filed", status="BLOCKED",
                            blocked_by="conduit access", next_step="file at conduit",
                            clock="D140 failsafe")
    assert "✅" in out
    t = map_sys.get_map_state(sitemap)["tracks"][-1]
    assert t["id"] == "departure_petitions"
    assert t["title"] == "Departure petitions"
    assert t["status"] == "BLOCKED"
    assert t["stand"] == "3 filed"
    assert t["blocked_by"] == "conduit access"
    assert t["next_step"] == "file at conduit"
    assert t["clock"] == "D140 failsafe"
    assert t["updated_day"] == 135


def test_track_add_defaults_status_open(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Some strand")
    t = map_sys.get_map_state(sitemap)["tracks"][-1]
    assert t["status"] == "OPEN"
    assert t["stand"] == ""


def test_track_add_bad_status_falls_back_open(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Some strand", status="MAYBE")
    assert map_sys.get_map_state(sitemap)["tracks"][-1]["status"] == "OPEN"


def test_track_add_duplicate_id_errors(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "First")
    out = map_sys.track_add(sitemap, "t1", "Second")
    assert "❌" in out and "already exists" in out
    assert "update" in out
    assert len(map_sys.get_map_state(sitemap)["tracks"]) == 1


def test_track_add_empty_title_errors(map_sys, sitemap):
    out = map_sys.track_add(sitemap, "t1", "   ")
    assert "❌" in out
    assert not map_sys.get_map_state(sitemap).get("tracks")


def test_track_add_empty_id_errors(map_sys, sitemap):
    out = map_sys.track_add(sitemap, "  ", "Title")
    assert "❌" in out


def test_track_add_truncates_stand_to_200(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Title", stand="x" * 500)
    assert len(map_sys.get_map_state(sitemap)["tracks"][-1]["stand"]) == 200


def test_track_update_patches_only_provided_fields(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Title", stand="old stand",
                      blocked_by="old blocker", status="OPEN")
    map_sys.get_day = lambda: 140
    map_sys.track_update(sitemap, "t1", stand="new stand")
    t = map_sys.get_map_state(sitemap)["tracks"][-1]
    assert t["stand"] == "new stand"
    assert t["blocked_by"] == "old blocker"   # untouched
    assert t["title"] == "Title"              # untouched
    assert t["status"] == "OPEN"              # untouched
    assert t["updated_day"] == 140            # always re-stamped


def test_track_update_status_and_clock(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Title")
    map_sys.track_update(sitemap, "t1", status="waiting", clock="months")
    t = map_sys.get_map_state(sitemap)["tracks"][-1]
    assert t["status"] == "WAITING"
    assert t["clock"] == "months"


def test_track_update_unknown_id_errors(map_sys, sitemap):
    out = map_sys.track_update(sitemap, "nope", stand="x")
    assert "❌" in out and "not found" in out


def test_track_resolve_marks_resolved_and_keeps_in_array(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Title")
    out = map_sys.track_resolve(sitemap, "t1")
    assert "✅" in out
    assert "reveal" in out   # nudge
    tracks = map_sys.get_map_state(sitemap)["tracks"]
    assert len(tracks) == 1
    assert tracks[0]["status"] == "RESOLVED"


def test_track_resolve_unknown_errors(map_sys, sitemap):
    out = map_sys.track_resolve(sitemap, "nope")
    assert "❌" in out


def test_track_list_renders_all(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "First", stand="standing", blocked_by="door")
    map_sys.track_add(sitemap, "t2", "Second")
    out = map_sys.track_list(sitemap)
    assert "First" in out and "Second" in out
    assert "BY: door" in out


def test_track_list_empty(map_sys, sitemap):
    assert "No tracks declared" in map_sys.track_list(sitemap)


# ---------------------------------------------------------------------------
# A1 — autocreate scoping parity with reveal_fact
# ---------------------------------------------------------------------------

def test_track_add_autocreates_for_sanctioned_prep(map_sys):
    map_sys.ledger_autocreate_ok = lambda name: name == "hollow_market_prep"
    out = map_sys.track_add("hollow_market_prep", "t1", "Broker debt")
    assert "✅" in out
    state = map_sys.get_map_state("hollow_market_prep")
    assert state and state.get("kind") == "ledger"
    assert state["tracks"][-1]["id"] == "t1"


def test_track_add_unknown_name_errors(map_sys):
    map_sys.ledger_autocreate_ok = lambda name: False
    out = map_sys.track_add("no_such_site", "t1", "X")
    assert "Map not found" in out


def test_track_list_unknown_name_errors(map_sys):
    map_sys.ledger_autocreate_ok = lambda name: False
    assert "Map not found" in map_sys.track_list("no_such_site")


# ---------------------------------------------------------------------------
# A2 — docket_lines (injection form)
# ---------------------------------------------------------------------------

def _state_with(tracks, map_name="thyricost"):
    return {"map_name": map_name, "tracks": tracks}


def test_docket_lines_empty():
    assert MapSystem.docket_lines(MapSystem.__new__(MapSystem), _state_with([]), 135) == []
    assert MapSystem.docket_lines(MapSystem.__new__(MapSystem), {}, 135) == []


def test_docket_lines_numbered_with_tags(map_sys):
    tracks = [
        {"id": "a", "title": "Departure petitions", "status": "BLOCKED",
         "stand": "3 filed", "blocked_by": "conduit", "next_step": "file",
         "clock": "D140", "updated_day": 135},
    ]
    lines = map_sys.docket_lines(_state_with(tracks), 135)
    assert lines[0].startswith("  1. Departure petitions — BLOCKED: 3 filed")
    assert "[BY: conduit]" in lines[0]
    assert "[NEXT: file]" in lines[0]
    assert "[CLOCK: D140]" in lines[0]
    assert "!stale" not in lines[0]


def test_docket_lines_excludes_resolved(map_sys):
    tracks = [
        {"id": "a", "title": "Open one", "status": "OPEN", "updated_day": 135},
        {"id": "b", "title": "Done one", "status": "RESOLVED", "updated_day": 135},
    ]
    lines = map_sys.docket_lines(_state_with(tracks), 135)
    assert len(lines) == 1
    assert "Open one" in lines[0]


def test_docket_lines_stale_marker(map_sys):
    tracks = [{"id": "a", "title": "Stale one", "status": "OPEN", "updated_day": 130}]
    assert "!stale" in map_sys.docket_lines(_state_with(tracks), 135)[0]
    # within 2 days -> not stale
    assert "!stale" not in map_sys.docket_lines(_state_with(tracks), 132)[0]
    # no current day -> never stale
    assert "!stale" not in map_sys.docket_lines(_state_with(tracks), None)[0]


def test_docket_lines_caps_at_12_with_overflow(map_sys):
    tracks = [{"id": f"t{i}", "title": f"Track {i}", "status": "OPEN",
               "updated_day": 135} for i in range(15)]
    lines = map_sys.docket_lines(_state_with(tracks), 135)
    assert len(lines) == 13   # 12 tracks + 1 overflow line
    assert lines[-1].strip().startswith("(+3 more")
    assert 'track_op="list"' in lines[-1]


# ---------------------------------------------------------------------------
# A2 — render_docket (player-facing document)
# ---------------------------------------------------------------------------

def test_render_docket_default_header(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Departure petitions", stand="3 filed")
    out = map_sys.render_docket(sitemap)
    assert out.splitlines()[0] == "EXPEDITION LEDGER — thyricost"
    assert "Day 135" in out
    assert "Departure petitions" in out
    assert "Stand: 3 filed" in out


def test_render_docket_custom_style_header(map_sys, sitemap):
    state = map_sys.get_map_state(sitemap)
    state["docket_style"] = "THYRICOST NODE 13 — EXPEDITION DOCKET"
    map_sys.save_map_state(sitemap, state)
    map_sys.track_add(sitemap, "t1", "Departure petitions")
    out = map_sys.render_docket(sitemap)
    assert out.splitlines()[0] == "THYRICOST NODE 13 — EXPEDITION DOCKET"


def test_render_docket_resolved_tail(map_sys, sitemap):
    map_sys.track_add(sitemap, "t1", "Open strand")
    map_sys.track_add(sitemap, "t2", "Finished strand")
    map_sys.track_resolve(sitemap, "t2")
    out = map_sys.render_docket(sitemap)
    assert "1. Open strand" in out
    assert "— settled: Finished strand" in out
    assert "1. Finished strand" not in out   # resolved not in the open list


def test_render_docket_no_open_tracks(map_sys, sitemap):
    out = map_sys.render_docket(sitemap)
    assert "(No open tracks.)" in out


# ---------------------------------------------------------------------------
# A3 — dispatcher routing + error strings
# ---------------------------------------------------------------------------

def test_dispatch_track_add_and_list(tmp_path):
    prep = tmp_path / "TEST_DISP_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    map_fn, ms = _capture_map_tool(tmp_path)
    ms.init_map_from_prep("thyricost", "TEST_DISP_PREP.md", "vault")
    out = map_fn(action="track", map_name="thyricost", track_op="add",
                 track_id="t1", title="A strand", stand="here", status="BLOCKED")
    assert "✅" in out
    listed = map_fn(action="track", map_name="thyricost", track_op="list")
    assert "A strand" in listed


def test_dispatch_docket(tmp_path):
    prep = tmp_path / "TEST_DISP2_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    map_fn, ms = _capture_map_tool(tmp_path)
    ms.init_map_from_prep("thyricost", "TEST_DISP2_PREP.md", "vault")
    map_fn(action="track", map_name="thyricost", track_op="add",
           track_id="t1", title="A strand")
    out = map_fn(action="docket", map_name="thyricost")
    assert "EXPEDITION LEDGER" in out
    assert "A strand" in out


def test_dispatch_track_requires_track_op(tmp_path):
    map_fn, ms = _capture_map_tool(tmp_path)
    out = map_fn(action="track", map_name="thyricost")
    assert "Error: track requires track_op" in out


def test_dispatch_track_add_missing_args(tmp_path):
    map_fn, ms = _capture_map_tool(tmp_path)
    out = map_fn(action="track", map_name="thyricost", track_op="add", track_id="t1")
    assert "Error: track add requires track_id, title" in out


def test_dispatch_track_update_missing_id(tmp_path):
    map_fn, ms = _capture_map_tool(tmp_path)
    out = map_fn(action="track", map_name="thyricost", track_op="update")
    assert "Error: track update requires track_id" in out


def test_dispatch_unknown_action_lists_track_docket(tmp_path):
    map_fn, ms = _capture_map_tool(tmp_path)
    out = map_fn(action="frobnicate", map_name="thyricost")
    assert "Unknown action" in out
    assert "track" in out and "docket" in out


# ---------------------------------------------------------------------------
# A4 — ledger dedup
# ---------------------------------------------------------------------------

def test_ledger_dedup_identical_skipped(map_sys):
    state = {"revealed_ledger": []}
    map_sys._ledger_append(state, "The seal bears a hound sigil", "r", "reveal")
    map_sys._ledger_append(state, "The seal bears a hound sigil", "r", "reveal")
    assert len(state["revealed_ledger"]) == 1


def test_ledger_dedup_near_identical_kept(map_sys):
    state = {"revealed_ledger": []}
    map_sys._ledger_append(state, "The seal bears a hound sigil", "r", "reveal")
    map_sys._ledger_append(state, "The seal bears a HOUND sigil", "r", "reveal")
    assert len(state["revealed_ledger"]) == 2


def test_ledger_dedup_only_last_10(map_sys):
    state = {"revealed_ledger": []}
    map_sys._ledger_append(state, "old fact", "r", "reveal")
    for i in range(10):
        map_sys._ledger_append(state, f"filler {i}", "r", "reveal")
    # "old fact" is now 11 back -> outside the last-10 window -> re-appends
    map_sys._ledger_append(state, "old fact", "r", "reveal")
    assert sum(1 for e in state["revealed_ledger"] if e["fact"] == "old fact") == 2


# ---------------------------------------------------------------------------
# A5 — server injection
# ---------------------------------------------------------------------------

def _mock_state(tracks=None, ledger=None):
    return {"map_name": "thyricost", "tracks": tracks or [],
            "revealed_ledger": ledger or []}


def test_injection_contains_docket_when_tracks(monkeypatch):
    tracks = [{"id": "a", "title": "Departure petitions", "status": "BLOCKED",
               "stand": "3 filed", "updated_day": 135}]
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("thyricost", 3))
    monkeypatch.setattr(server.map_system, "get_map_state",
                        lambda name: _mock_state(tracks=tracks))
    monkeypatch.setattr(server, "get_current_day_safe", lambda: 135)
    block = server._revealed_ledger_injection()
    assert "DOCKET (thyricost)" in block
    assert "Departure petitions" in block
    assert "ANCHOR" in block
    # ledger block still present, unchanged, below the docket
    assert "REVEALED LEDGER (thyricost)" in block
    assert block.index("DOCKET (thyricost)") < block.index("REVEALED LEDGER (thyricost)")


def test_injection_no_docket_when_no_tracks(monkeypatch):
    ledger = [{"fact": "A known fact", "day": 3}]
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("thyricost", 3))
    monkeypatch.setattr(server.map_system, "get_map_state",
                        lambda name: _mock_state(ledger=ledger))
    monkeypatch.setattr(server, "get_current_day_safe", lambda: 135)
    block = server._revealed_ledger_injection()
    assert "DOCKET" not in block
    assert "REVEALED LEDGER (thyricost)" in block
    assert "A known fact" in block


def test_injection_resolved_tracks_dont_show(monkeypatch):
    tracks = [{"id": "a", "title": "Done", "status": "RESOLVED", "updated_day": 135}]
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("thyricost", 3))
    monkeypatch.setattr(server.map_system, "get_map_state",
                        lambda name: _mock_state(tracks=tracks))
    monkeypatch.setattr(server, "get_current_day_safe", lambda: 135)
    block = server._revealed_ledger_injection()
    assert "DOCKET" not in block


# ---------------------------------------------------------------------------
# A6 — push wiring
# ---------------------------------------------------------------------------

def test_init_pushes_track_declaration_when_empty(map_sys, tmp_path):
    prep = tmp_path / "TEST_PUSH_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    out = map_sys.init_map_from_prep("pushvault", "TEST_PUSH_PREP.md", "vault")
    assert "NO TRACKS DECLARED" in out
    assert 'track_op="add"' in out


def test_enter_pushes_when_empty_and_silent_after_declared(map_sys, sitemap):
    out = map_sys.enter_room(sitemap, "room_b")
    assert "NO TRACKS DECLARED" in out
    map_sys.track_add(sitemap, "t1", "A strand")
    out2 = map_sys.enter_room(sitemap, "room_a")
    assert "NO TRACKS DECLARED" not in out2


def test_resume_pushes_when_empty(map_sys, tmp_path):
    prep = tmp_path / "TEST_RESUME_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    map_sys.init_or_resume_map("resumesite", "TEST_RESUME_PREP.md", "vault", current_day=135)
    out = map_sys.init_or_resume_map("resumesite", "TEST_RESUME_PREP.md", "vault",
                                     current_day=135)
    assert "RESUMING" in out
    assert "NO TRACKS DECLARED" in out


def test_no_push_without_prep(map_sys):
    # A ledger-only state (social scene, no prep_file) never pushes track-declaration.
    state = map_sys._new_ledger_only_state("social_scene")
    assert map_sys._no_tracks_push(state) == ""
