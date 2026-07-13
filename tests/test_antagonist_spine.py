"""Antagonist spine — fire the write-only cultivation store. The engine clocks +
surfaces + pushes a decision; it judges nothing and never auto-resolves."""
import pytest
import server


SAMPLE = """# ANTAGONIST CULTIVATION

## ACTIVE THREATS
*Things currently in motion*

### Hegemony Friction - Escalation: MED
<!-- spine: due_day=135; trigger=hegemony,watcher; level=med; fired=false; fired_day= -->
- Source: the public creed armed it

## DORMANT SEEDS
*Resentments, mistakes, vulnerabilities not yet active*

### Kronophage Awareness - Day planted: 122
<!-- spine: due_day=128; trigger=northeast,standing stones; level=high; fired=false; fired_day= -->
- LVL 7 time-eater aware of Creenash; NE travel risk

### Kelemer Retaliation - Day planted: 122
- A cornered House (no spine tag yet)

## ESCALATION LOG

[None yet]
"""


# ---- parse / format ----

def test_parse_tag_full():
    spine = server._antag_parse_spine_tag(
        "<!-- spine: due_day=128; trigger=northeast,standing stones; level=high; fired=true; fired_day=130 -->")
    assert spine["due_day"] == 128
    assert spine["trigger"] == ["northeast", "standing stones"]
    assert spine["level"] == "high"
    assert spine["fired"] is True and spine["fired_day"] == 130


def test_parse_tag_absent_returns_defaults():
    spine = server._antag_parse_spine_tag("no tag here")
    assert spine == {"due_day": None, "trigger": [], "level": "low",
                     "fired": False, "fired_day": None}


def test_parse_tag_empty_values():
    spine = server._antag_parse_spine_tag(
        "<!-- spine: due_day=; trigger=; level=low; fired=false; fired_day= -->")
    assert spine["due_day"] is None and spine["trigger"] == [] and spine["fired_day"] is None


def test_format_then_parse_roundtrips():
    spine = {"due_day": 50, "trigger": ["ne", "stones"], "level": "med",
             "fired": True, "fired_day": 55}
    assert server._antag_parse_spine_tag(server._antag_format_spine_tag(spine)) == spine


# ---- iterate ----

def test_iter_seeds_reads_both_sections():
    seeds = server._antag_iter_seeds(SAMPLE)
    names = {s["name"]: s for s in seeds}
    assert "Hegemony Friction" in names and names["Hegemony Friction"]["section"] == "active"
    assert names["Kronophage Awareness"]["section"] == "dormant"
    assert names["Kronophage Awareness"]["planted_day"] == 122
    assert names["Kronophage Awareness"]["spine"]["due_day"] == 128
    # a seed with no tag parses to defaults, not an error
    assert names["Kelemer Retaliation"]["spine"]["due_day"] is None


def test_iter_seeds_empty_is_silent():
    assert server._antag_iter_seeds("") == []
    assert server._antag_iter_seeds("# ANTAGONIST CULTIVATION\n\n## DORMANT SEEDS\n\n[None yet]\n") == []


# ---- set ----

def test_set_spine_inserts_when_absent():
    out = server._antag_set_spine(SAMPLE, "Kelemer Retaliation",
                                  {"due_day": 130, "trigger": [], "level": "med",
                                   "fired": False, "fired_day": None})
    seeds = {s["name"]: s for s in server._antag_iter_seeds(out)}
    assert seeds["Kelemer Retaliation"]["spine"]["due_day"] == 130


def test_set_spine_replaces_when_present():
    out = server._antag_set_spine(SAMPLE, "Kronophage Awareness",
                                  {"due_day": 200, "trigger": ["ne"], "level": "high",
                                   "fired": True, "fired_day": 131})
    seeds = {s["name"]: s for s in server._antag_iter_seeds(out)}
    assert seeds["Kronophage Awareness"]["spine"]["due_day"] == 200
    assert seeds["Kronophage Awareness"]["spine"]["fired"] is True
    # exactly one tag line for that seed (no duplication)
    assert out.count("due_day=200") == 1


# ---- protected ----

def test_is_protected():
    assert server._antag_seed_is_protected({"due_day": 5, "trigger": [], "fired": False})
    assert server._antag_seed_is_protected({"due_day": None, "trigger": ["ne"], "fired": False})
    assert server._antag_seed_is_protected({"due_day": None, "trigger": [], "fired": True})
    assert not server._antag_seed_is_protected({"due_day": None, "trigger": [], "fired": False})


# ---- the antagonist tool writes spine tags (file-backed) ----

@pytest.fixture
def cult_env(tmp_path, monkeypatch):
    """Point the cultivation store at a temp campaign dir. NEVER touches the real
    campaign file."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    return tmp_path


def _read_cult(tmp_path):
    return (tmp_path / "ANTAGONIST_CULTIVATION.md").read_text(encoding="utf-8")


def test_add_seed_with_clock_writes_tag(cult_env):
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered House", day=122, due_day=130)
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Kelemer Retaliation"]["spine"]["due_day"] == 130


def test_add_seed_with_pace_maps_to_due_day(cult_env):
    # pace 'warm' = +7 days from the planted day
    server.antagonist(action="add_seed", threat_name="Brenn Probe",
                      details="watch the assessment", day=123, pace="warm")
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Brenn Probe"]["spine"]["due_day"] == 130


def test_add_seed_with_trigger_writes_keywords(cult_env):
    server.antagonist(action="add_seed", threat_name="Kronophage",
                      details="NE time-eater", day=122,
                      trigger="northeast,standing stones")
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Kronophage"]["spine"]["trigger"] == ["northeast", "standing stones"]


def test_escalate_rearms_clock_on_the_active_threat(cult_env):
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered House", day=122, due_day=130)
    server.antagonist(action="escalate", threat_name="Kelemer Retaliation",
                      escalation="high", details="they move on Joss", day=131, due_day=138)
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Kelemer Retaliation"]["section"] == "active"
    assert seeds["Kelemer Retaliation"]["spine"]["due_day"] == 138
    assert seeds["Kelemer Retaliation"]["spine"]["fired"] is False  # re-armed
    assert seeds["Kelemer Retaliation"]["spine"]["level"] == "high"


# ---- ANTAGONIST TICK (advance_day) ----

def test_tick_fires_due_seed_and_pushes(cult_env):
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered House", day=122, due_day=128)
    out = server._antagonist_tick(130)
    assert "ANTAGONIST TICK" in out and "Kelemer Retaliation" in out
    # fired flag persisted
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Kelemer Retaliation"]["spine"]["fired"] is True
    assert seeds["Kelemer Retaliation"]["spine"]["fired_day"] == 130


def test_tick_is_idempotent_no_refire(cult_env):
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered House", day=122, due_day=128)
    server._antagonist_tick(130)
    out2 = server._antagonist_tick(131)
    assert "ANTAGONIST TICK" not in out2  # already fired, does not re-fire


def test_tick_not_yet_due_is_silent(cult_env):
    server.antagonist(action="add_seed", threat_name="Future Threat",
                      details="later", day=122, due_day=200)
    assert server._antagonist_tick(130) == ""


def test_tick_empty_board_is_silent(cult_env):
    assert server._antagonist_tick(130) == ""


# ---- trigger injection (loud, in-scene) ----

def test_trigger_block_surfaces_on_keyword(cult_env):
    server.antagonist(action="add_seed", threat_name="Kronophage",
                      details="NE time-eater", day=122, trigger="standing stones")
    blocks = server._antagonist_trigger_blocks("we head out to the standing stones")
    assert len(blocks) == 1 and "Kronophage" in blocks[0]


def test_trigger_block_absent_without_keyword(cult_env):
    server.antagonist(action="add_seed", threat_name="Kronophage",
                      details="NE time-eater", day=122, trigger="standing stones")
    assert server._antagonist_trigger_blocks("we visit the market") == []


def test_trigger_block_empty_board_silent(cult_env):
    assert server._antagonist_trigger_blocks("standing stones") == []


# ---- end-to-end: trigger surfaces through check_canon ----

class _MockCtx:
    """Minimal MCP Context stand-in for check_canon calls."""
    pass


def test_trigger_surfaces_through_check_canon(cult_env):
    import json as _json
    # check_canon requires a lorebook.json to avoid early-return
    (cult_env / "lorebook.json").write_text(
        _json.dumps({"entries": []}), encoding="utf-8")
    server.antagonist(action="add_seed", threat_name="Kronophage",
                      details="NE time-eater", day=122, trigger="standing stones")
    out = server.check_canon(_MockCtx(), user_input="we ride out to the standing stones", needs=[])
    assert "ANTAGONIST TRIGGER" in out and "Kronophage" in out


# ---- session-start briefing (read-back) ----

def test_briefing_surfaces_active_threat(cult_env):
    server.antagonist(action="add_threat", threat_name="Hegemony Friction",
                      details="armed public", day=130, escalation="med")
    lines = server._antagonist_briefing_lines()
    assert any("Hegemony Friction" in ln for ln in lines)


def test_briefing_surfaces_fired_seed(cult_env):
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered", day=122, due_day=128)
    server._antagonist_tick(130)  # fires it
    lines = server._antagonist_briefing_lines()
    assert any("Kelemer Retaliation" in ln for ln in lines)


def test_briefing_empty_board_silent(cult_env):
    assert server._antagonist_briefing_lines() == []


# ---- stop composting unfired threats ----

def test_clocked_seed_is_not_pruned_even_when_old(cult_env):
    # a 25-day-dormant seed WITH a live clock must survive
    server.antagonist(action="add_seed", threat_name="Kronophage",
                      details="time-eater", day=100, due_day=140)
    content = server._load_cultivation()
    review = server._review_cultivation([], 125, "")  # day 125, planted 100 -> age 25
    assert "Kronophage" not in review["prunes"]


def test_unclocked_old_seed_is_still_pruned(cult_env):
    server.antagonist(action="add_seed", threat_name="Forgotten Grudge",
                      details="went nowhere", day=100)  # no clock, no trigger
    review = server._review_cultivation([], 125, "")  # age 25
    assert "Forgotten Grudge" in review["prunes"]


# ---- end-to-end + zero-state ----

def test_full_loop_cultivate_fire_surface_rearm(cult_env):
    # cultivate a clocked seed
    server.antagonist(action="add_seed", threat_name="Kelemer Retaliation",
                      details="cornered House", day=122, due_day=128)
    # it fires on advance past due
    assert "Kelemer Retaliation" in server._antagonist_tick(130)
    # it surfaces in the session-start briefing (the read-back that never existed)
    assert any("Kelemer Retaliation" in ln for ln in server._antagonist_briefing_lines())
    # DM walks the ladder: escalate re-arms for the next rung
    server.antagonist(action="escalate", threat_name="Kelemer Retaliation",
                      escalation="high", details="moves on Joss", day=131, due_day=137)
    seeds = {s["name"]: s for s in server._antag_iter_seeds(_read_cult(cult_env))}
    assert seeds["Kelemer Retaliation"]["section"] == "active"
    assert seeds["Kelemer Retaliation"]["spine"]["fired"] is False
    assert seeds["Kelemer Retaliation"]["spine"]["due_day"] == 137


def test_zero_state_all_silent(cult_env):
    assert server._antagonist_tick(130) == ""
    assert server._antagonist_trigger_blocks("standing stones") == []
    assert server._antagonist_briefing_lines() == []


def test_iter_seeds_preserves_name_with_dashes():
    content = ("# ANTAGONIST CULTIVATION\n\n## DORMANT SEEDS\n\n"
               "### Brenn - Joss Double - Day planted: 123\n"
               "<!-- spine: due_day=130; trigger=; level=med; fired=false; fired_day= -->\n"
               "- watch the assessment\n")
    seeds = {s["name"]: s for s in server._antag_iter_seeds(content)}
    assert "Brenn - Joss Double" in seeds
    assert seeds["Brenn - Joss Double"]["spine"]["due_day"] == 130


def test_set_spine_round_trips_organic_headings():
    # the REAL cultivation file has organic headings authored before the spine
    # existed (no strict " - Day planted: N"). set_spine must still attach a tag,
    # and the tick's fire-once stamping (re-calls set_spine by the iter-derived
    # name) must round-trip.
    for heading in ("### The Laughing Court (Day 102, player-seeded)",
                    "### Torven (Water Authority clerk) — APPREHENDED Day 126",
                    "### Three-Houses Exposure Ripening (Day 124, ACTIVE)"):
        content = ("# ANTAGONIST CULTIVATION\n\n## DORMANT SEEDS\n\n"
                   + heading + "\n- some terse detail\n")
        name = heading[4:]  # name as iter_seeds derives it from this organic heading
        out = server._antag_set_spine(content, name,
                                      {"due_day": 131, "trigger": [], "level": "med",
                                       "fired": False, "fired_day": None})
        seeds = {s["name"]: s for s in server._antag_iter_seeds(out)}
        assert name in seeds, f"organic heading not matched: {heading}"
        assert seeds[name]["spine"]["due_day"] == 131
        # round-trip: stamp fired the way the tick does; exactly one tag remains
        again = server._antag_set_spine(out, name,
                                        {"due_day": 131, "trigger": [], "level": "med",
                                         "fired": True, "fired_day": 131})
        assert again.count("<!-- spine:") == 1
        assert {s["name"]: s for s in server._antag_iter_seeds(again)}[name]["spine"]["fired"] is True
