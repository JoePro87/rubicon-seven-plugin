import json
import server

import hooks.gate_check as gate_check
import hooks.consolidated_stop_check as stop_check


class _MockCtx:
    """Minimal MCP Context stand-in; mirrors tests/test_d1_factions.py."""
    pass


def _seed_lorebook(campaign_dir):
    """check_canon early-returns if lorebook.json is missing; seed an empty one."""
    (campaign_dir / "lorebook.json").write_text(
        json.dumps({"entries": []}), encoding="utf-8")


def _seed_npc(campaign_dir, slug, record):
    path = campaign_dir / "npc_states.json"
    data = {"npcs": {slug: record}, "meta": {"last_updated": "2026-06-13"}}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_dossier_continuity_fields_surface_on_name(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "minius", {
        "name": "Minius",
        "disposition": "friendly",
        "knows": ["smuggling routes"],
        "left_off": "Negotiating a discount on the void-pistol.",
        "open_purpose": "Source a dimensional sidearm before the Faa expedition.",
    })
    out = server.check_canon(_MockCtx(), user_input="I go to see Minius.", needs=[])
    assert "Negotiating a discount on the void-pistol." in out
    assert "Source a dimensional sidearm" in out


def test_dossier_surfaces_without_npc_knowledge_block(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "minius", {
        "name": "Minius", "disposition": "friendly",
        "left_off": "Owed him a favour.", "open_purpose": "",
    })
    out = server.check_canon(_MockCtx(), user_input="I go to see Minius.", needs=["voice"])
    assert "Owed him a favour." in out


def test_changed_while_away_suppressed_when_surfaced(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "minius", {
        "name": "Minius", "disposition": "friendly",
        "changed_while_away": {"note": "He lost the arm.", "surfaced": True},
    })
    out = server.check_canon(_MockCtx(), user_input="I go to see Minius.", needs=[])
    assert "He lost the arm." not in out


def test_continuity_write_roundtrips(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius", "disposition": "friendly"})
    msg = server._npc_continuity("Minius",
                                 "Agreed to the favour; pistol on hold.",
                                 "Get the dimensional sidearm.", 131)
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    rec = data["npcs"]["minius"]
    assert rec["left_off"] == "Agreed to the favour; pistol on hold."
    assert rec["open_purpose"] == "Get the dimensional sidearm."
    assert rec["last_seen_day"] == 131
    assert "Minius" in msg


def test_continuity_caps_left_off_length(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    long = "x" * 500
    server._npc_continuity("Minius", long, "", 0)
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    assert len(data["npcs"]["minius"]["left_off"]) <= 240


def test_continuity_dispatch_via_tool(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    out = server.npc(action="continuity", name="Minius",
                     left_off="Parted on good terms.", open_purpose="", last_seen_day=131)
    assert "Minius" in out
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    assert data["npcs"]["minius"]["left_off"] == "Parted on good terms."


def test_continuity_unknown_npc_is_graceful(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    out = server.npc(action="continuity", name="Nobody", left_off="x", open_purpose="")
    assert "not found" in out.lower() or "unknown" in out.lower()


def test_continuity_flips_changed_while_away_surfaced(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {
        "name": "Minius",
        "changed_while_away": {"note": "Dock war lost.", "stamped_day": 128, "surfaced": False},
    })
    server._npc_continuity("Minius", "Talked it over.", "", 130)
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    assert data["npcs"]["minius"]["changed_while_away"]["surfaced"] is True


# ===================================================================
# Task 3: door gate (hook-level pure functions)
# ===================================================================

def test_detect_open_npcs_finds_named_roster_member():
    roster = {"minius": "Minius", "vela": "Vela"}
    opened = stop_check.detect_open_npcs("I go to see Minius about the pistol.", roster)
    assert opened == {"minius"}


def test_detect_open_npcs_ignores_unnamed():
    roster = {"minius": "Minius"}
    assert stop_check.detect_open_npcs("We cross the empty dunes.", roster) == set()


def test_boundary_block_fires_when_open():
    state = {"open_npc_scene": {"minius": {"name": "Minius"}}}
    msg = gate_check.npc_boundary_block("advance_day", {}, state)
    assert msg is not None and "Minius" in msg


def test_boundary_block_silent_when_no_open_npc():
    state = {"open_npc_scene": {}}
    assert gate_check.npc_boundary_block("advance_day", {}, state) is None


def test_boundary_block_only_on_boundary_tools():
    state = {"open_npc_scene": {"minius": {"name": "Minius"}}}
    assert gate_check.npc_boundary_block("roll", {}, state) is None


def test_continuity_call_clears_flag():
    state = {"open_npc_scene": {"minius": {"name": "Minius"}, "vela": {"name": "Vela"}}}
    gate_check.clear_npc_on_continuity({"action": "continuity", "name": "Minius"}, state)
    assert "minius" not in state["open_npc_scene"]
    assert "vela" in state["open_npc_scene"]


def test_detect_open_npcs_no_false_positive_on_suffix():
    roster = {"ted": "Ted", "vosh": "Dr. Mirena Vosh"}
    # "-ted" verbs and a bare honorific must NOT open anyone.
    assert stop_check.detect_open_npcs("We waited, rested, and noted the dr. on call.", roster) == set()


def test_detect_open_npcs_matches_whole_token():
    roster = {"ted": "Ted"}
    assert stop_check.detect_open_npcs("Ted greets us.", roster) == {"ted"}


def test_stamp_changed_while_away_sets_unsurfaced(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    server._stamp_npc_changed_while_away("minius", "His backers lost the dock war.", 128)
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    cwa = data["npcs"]["minius"]["changed_while_away"]
    assert cwa["note"] == "His backers lost the dock war."
    assert cwa["stamped_day"] == 128
    assert cwa["surfaced"] is False


def test_stamped_change_surfaces_then_clears(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    server._stamp_npc_changed_while_away("minius", "Dock war lost.", 128)
    out = server.check_canon(_MockCtx(), user_input="I go to see Minius.", needs=[])
    assert "Dock war lost." in out
    server._npc_continuity("Minius", "Talked it over.", "", 130)
    out2 = server.check_canon(_MockCtx(), user_input="I go to see Minius.", needs=[])
    assert "Dock war lost." not in out2


def test_stamp_unknown_npc_is_noop(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius"})
    server._stamp_npc_changed_while_away("nobody", "x", 1)
    data = json.loads((isolate_campaign_dir / "npc_states.json").read_text(encoding="utf-8"))
    assert "nobody" not in data["npcs"]


def test_world_tick_name_match_is_word_bounded():
    # The World-Tick stamp matches NPC names with \b boundaries, so a thread
    # label like "The Wanted Poster Campaign" must NOT match an NPC "Ted".
    import re as _re
    label = "The Wanted Poster Campaign".lower()
    assert _re.search(rf"\b{_re.escape('ted')}\b", label) is None
    assert _re.search(rf"\b{_re.escape('minius')}\b", "Minius lost the dock war.".lower()) is not None


def test_echo_writes_npc_dossiers_to_cache(isolate_campaign_dir):
    path = isolate_campaign_dir / "npc_states.json"
    data = {"npcs": {
        "minius": {"name": "Minius", "disposition": "friendly",
                   "left_off": "Owed a favour.", "open_purpose": "Find the sidearm."},
        "blank": {"name": "Blank"},
    }, "meta": {"last_updated": "2026-06-13"}}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    n = server._echo_npc_dossiers_to_distillation_cache()
    assert n == 1  # only Minius (has continuity); Blank skipped

    entries = server._get_distillation_cache().all_entries()
    keys = [e.get("topic_key", "") for e in entries]
    assert any(k == "npc:minius:profile" for k in keys)
    assert not any(k == "npc:blank:profile" for k in keys)


def test_echo_is_idempotent(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {
        "name": "Minius", "left_off": "x", "open_purpose": "y"})
    server._echo_npc_dossiers_to_distillation_cache()
    server._echo_npc_dossiers_to_distillation_cache()
    keys = [e.get("topic_key", "") for e in server._get_distillation_cache().all_entries()]
    assert keys.count("npc:minius:profile") == 1


def test_echo_handles_open_purpose_only(isolate_campaign_dir):
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius", "open_purpose": "Find the sidearm."})
    assert server._echo_npc_dossiers_to_distillation_cache() == 1
    keys = [e.get("topic_key", "") for e in server._get_distillation_cache().all_entries()]
    assert "npc:minius:profile" in keys


def test_npc_block_renders_once_per_npc(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "minius", {"name": "Minius", "left_off": "once-marker"})
    out = server.check_canon(_MockCtx(), user_input="Minius, Minius, I seek Minius.", needs=["npc_knowledge"])
    assert out.count("once-marker") == 1


def test_injection_no_false_positive_on_suffix(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "ted", {"name": "Ted", "left_off": "ted-marker"})
    # "-ted" suffix words must NOT inject Ted's dossier.
    out = server.check_canon(_MockCtx(), user_input="We waited, rested, and noted the path.", needs=[])
    assert "ted-marker" not in out


def test_injection_still_matches_whole_token(isolate_campaign_dir):
    _seed_lorebook(isolate_campaign_dir)
    _seed_npc(isolate_campaign_dir, "ted", {"name": "Ted", "left_off": "ted-marker"})
    out = server.check_canon(_MockCtx(), user_input="I greet Ted warmly.", needs=[])
    assert "ted-marker" in out
