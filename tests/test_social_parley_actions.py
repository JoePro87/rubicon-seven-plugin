# tests/test_social_parley_actions.py
import social_system as ss
from tests.test_social_parley_parser import SAMPLE
from tests.test_social_parley_tool import make_tool

def setup_parley(tmp_path):
    (tmp_path / "X_PREP.md").write_text(SAMPLE, encoding="utf-8")
    parley = make_tool(tmp_path)
    parley(action="open", slug="outer_reach_accord", prep="X_PREP.md", title="OR")
    return parley

def test_move_logs_and_satisfies_beat(tmp_path):
    parley = setup_parley(tmp_path)
    parley(action="move", slug="outer_reach_accord", note="purpose stated", beat="assessment_b1")
    state = ss.load_parleys(tmp_path)["outer_reach_accord"]
    assert state["log"][-1]["entry"] == "purpose stated"
    b = [b for t in state["tiers"] for b in t["beats"] if b["id"] == "assessment_b1"][0]
    assert b["satisfied"] is True

def test_move_on_checked_tier_pushes_roll(tmp_path):
    parley = setup_parley(tmp_path)
    parley(action="tier", slug="outer_reach_accord", to="assessment", reason="audience granted")
    out = parley(action="move", slug="outer_reach_accord", note="Creenash makes his case")
    assert "roll(" in out and "EGO" in out and "15" in out.replace('"', "")
    assert 'ability="EGO"' in out  # live roll(action="check") tool takes ability=, not stat=
    assert "stat=" not in out

def test_move_needle_shift_requires_both_npc_and_needle(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="move", slug="outer_reach_accord", note="she leans in", npc="She-Who-Keeps")
    assert "requires both npc" in out.lower()
    p = ss.load_parleys(tmp_path)["outer_reach_accord"]["parties"][0]
    assert p["needle"] == "wary"  # unchanged

def test_tier_warns_but_applies_on_unsatisfied_beats(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="tier", slug="outer_reach_accord", to="accord", reason="she offered her palm")
    assert "WARN" in out
    assert ss.load_parleys(tmp_path)["outer_reach_accord"]["current_tier"] == "accord"

def test_tier_requires_reason(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="tier", slug="outer_reach_accord", to="assessment")
    assert "reason" in out.lower()
    assert ss.load_parleys(tmp_path)["outer_reach_accord"]["current_tier"] == "contact"

def test_needle_shift_history_stamped(tmp_path):
    parley = setup_parley(tmp_path)
    parley(action="needle", slug="outer_reach_accord", npc="She-Who-Keeps", to="neutral", reason="disarm gesture")
    p = ss.load_parleys(tmp_path)["outer_reach_accord"]["parties"][0]
    assert p["needle"] == "neutral"
    assert p["history"][-1] == {"day": 131, "from": "wary", "to": "neutral", "note": "disarm gesture"}

def test_reveal_gated_then_unlocked_at_tier(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="reveal", slug="outer_reach_accord", label="matriarch_true_name")
    assert "GATED" in out and "roll(" in out  # gate has an OR-check → pushed
    parley(action="tier", slug="outer_reach_accord", to="accord", reason="alliance sealed")
    out2 = parley(action="reveal", slug="outer_reach_accord", label="matriarch_true_name")
    assert "UNLOCKED" in out2
    assert "parley(" in out2  # forward-pushes orientation, doesn't dead-end

def test_reveal_override_with_reason(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="reveal", slug="outer_reach_accord", label="secondary_cache", reason="she volunteers it as proof of good faith")
    assert "UNLOCKED" in out
    assert "parley(" in out  # forward-pushes orientation, doesn't dead-end
    state = ss.load_parleys(tmp_path)["outer_reach_accord"]
    assert any("override" in e["entry"] for e in state["log"])

def test_close_pushes_crystallization(tmp_path):
    parley = setup_parley(tmp_path)
    out = parley(action="close", slug="outer_reach_accord", outcome="alliance")
    assert "update_location_progress" in out
    assert ss.load_parleys(tmp_path)["outer_reach_accord"]["status"] == "closed"
