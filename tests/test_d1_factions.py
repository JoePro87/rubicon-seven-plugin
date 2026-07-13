import server


def test_faction_slug():
    assert server._faction_slug("Mycomorph Colony") == "mycomorph_colony"
    assert server._faction_slug("Seekers of Eyeless Wisdom") == "seekers_of_eyeless_wisdom"
    assert server._faction_slug("47 Cistern Researchers") == "47_cistern_researchers"


def test_load_factions_default_when_absent(isolate_campaign_dir):
    data, err = server._load_factions()
    assert err is None
    assert data["factions"] == {}
    assert "last_updated" in data["meta"]


def test_save_then_load_roundtrip(isolate_campaign_dir):
    data, _ = server._load_factions()
    data["factions"]["test_guild"] = {"name": "Test Guild", "rep": 3}
    server._save_factions(data)
    again, err = server._load_factions()
    assert err is None
    assert again["factions"]["test_guild"]["rep"] == 3


def test_add_then_status_one(isolate_campaign_dir):
    server.faction(action="add", name="Mycomorph Colony", scope="alliance",
                   type="Fungal collective", rep=6, reason="Alliance established", day=15)
    out = server.faction(action="status", name="Mycomorph Colony")
    assert "Mycomorph Colony" in out
    assert "+6" in out and "Friend" in out
    assert "help you in any way" in out
    assert "favorable" in out


def test_add_is_logged_in_history(isolate_campaign_dir):
    server.faction(action="add", name="Test Guild", rep=2, reason="seed", day=10)
    data, _ = server._load_factions()
    h = data["factions"]["test_guild"]["history"]
    assert h[-1] == {"day": 10, "delta": 2, "reason": "seed", "rep_after": 2}


def test_duplicate_add_refused(isolate_campaign_dir):
    server.faction(action="add", name="Test Guild", rep=1)
    out = server.faction(action="add", name="Test Guild", rep=5)
    assert "already exists" in out.lower()


def test_status_all_lists_sorted(isolate_campaign_dir):
    server.faction(action="add", name="Low Guild", rep=-3)
    server.faction(action="add", name="High Guild", rep=8)
    out = server.faction(action="status")
    assert out.index("High Guild") < out.index("Low Guild")


def test_status_unknown_faction(isolate_campaign_dir):
    out = server.faction(action="status", name="Ghosts")
    assert "no faction" in out.lower() or "not found" in out.lower()


def test_earn_raises_rep_and_logs(isolate_campaign_dir):
    server.faction(action="add", name="Test Guild", rep=1, day=5)
    out = server.faction(action="earn", name="Test Guild", amount=3, reason="saved their envoy", day=7)
    assert "+4" in out and "Friend" in out
    data, _ = server._load_factions()
    h = data["factions"]["test_guild"]["history"][-1]
    assert h == {"day": 7, "delta": 3, "reason": "saved their envoy", "rep_after": 4}


def test_earn_clamps_at_plus_ten(isolate_campaign_dir):
    server.faction(action="add", name="Test Guild", rep=9)
    out = server.faction(action="earn", name="Test Guild", amount=5, reason="hero deed")
    assert "+10" in out and "Hero" in out
    assert "cap" in out.lower()
    data, _ = server._load_factions()
    assert data["factions"]["test_guild"]["rep"] == 10


def test_earn_negative_is_a_loss(isolate_campaign_dir):
    server.faction(action="add", name="Test Guild", rep=2)
    server.faction(action="earn", name="Test Guild", amount=-5, reason="betrayed them")
    data, _ = server._load_factions()
    assert data["factions"]["test_guild"]["rep"] == -3


def test_earn_mirrors_opposed(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=0)
    server.faction(action="add", name="Moon Cult", rep=0)
    server.faction(action="oppose", name="Sun Cult", other="Moon Cult")
    out = server.faction(action="earn", name="Sun Cult", amount=4, reason="aided them")
    assert "Moon Cult" in out
    data, _ = server._load_factions()
    assert data["factions"]["sun_cult"]["rep"] == 4
    assert data["factions"]["moon_cult"]["rep"] == -4
    mh = data["factions"]["moon_cult"]["history"][-1]
    assert mh["delta"] == -4 and "opposed to Sun Cult" in mh["reason"]


def test_earn_mirror_skips_absent_faction(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=0, opposed="Ghost Cult")
    out = server.faction(action="earn", name="Sun Cult", amount=3, reason="x")
    assert "ghost_cult" in out   # opposed slug reported as skipped
    data, _ = server._load_factions()
    assert "ghost_cult" not in data["factions"]


def test_earn_unknown_faction(isolate_campaign_dir):
    out = server.faction(action="earn", name="Nobody", amount=2, reason="x")
    assert "no faction" in out.lower() or "not tracked" in out.lower()


def test_oppose_is_idempotent_and_bidirectional(isolate_campaign_dir):
    server.faction(action="add", name="A Guild", rep=0)
    server.faction(action="add", name="B Guild", rep=0)
    server.faction(action="oppose", name="A Guild", other="B Guild")
    server.faction(action="oppose", name="A Guild", other="B Guild")
    data, _ = server._load_factions()
    assert data["factions"]["a_guild"]["opposed"] == ["b_guild"]
    assert data["factions"]["b_guild"]["opposed"] == ["a_guild"]


def test_spend_reduces_rep_no_mirror(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=6)
    server.faction(action="add", name="Moon Cult", rep=0)
    server.faction(action="oppose", name="Sun Cult", other="Moon Cult")
    out = server.faction(action="spend", name="Sun Cult", amount=2, reason="safe passage")
    assert "+4" in out
    data, _ = server._load_factions()
    assert data["factions"]["sun_cult"]["rep"] == 4
    assert data["factions"]["moon_cult"]["rep"] == 0
    assert data["factions"]["sun_cult"]["history"][-1]["reason"] == "safe passage"
    assert data["factions"]["sun_cult"]["history"][-1]["delta"] == -2


def test_spend_floor_minus_ten(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=-9)
    out = server.faction(action="spend", name="Sun Cult", amount=5, reason="x")
    assert "cannot spend" in out.lower() or "below -10" in out.lower()
    data, _ = server._load_factions()
    assert data["factions"]["sun_cult"]["rep"] == -9


def test_spend_requires_positive_amount(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=5)
    out = server.faction(action="spend", name="Sun Cult", amount=0, reason="x")
    assert "positive" in out.lower()


def test_set_overrides_absolutely_no_mirror(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=2)
    server.faction(action="add", name="Moon Cult", rep=0)
    server.faction(action="oppose", name="Sun Cult", other="Moon Cult")
    server.faction(action="set", name="Sun Cult", rep=-4, reason="retcon", day=12)
    data, _ = server._load_factions()
    assert data["factions"]["sun_cult"]["rep"] == -4
    assert data["factions"]["moon_cult"]["rep"] == 0
    assert data["factions"]["sun_cult"]["history"][-1] == {
        "day": 12, "delta": -6, "reason": "retcon", "rep_after": -4}


def test_set_clamps(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=0)
    server.faction(action="set", name="Sun Cult", rep=99, reason="x")
    data, _ = server._load_factions()
    assert data["factions"]["sun_cult"]["rep"] == 10


def test_generate_faction_returns_record_and_baton(isolate_campaign_dir):
    out = server.generate(action="faction")
    assert "MINOR FACTION" in out.upper()
    for token in ("Type:", "Goal:", "Leader:", "Assets:", "Rival:"):
        assert token in out
    assert "faction" in out and "add" in out


def test_briefing_lists_factions_sorted(isolate_campaign_dir):
    server.faction(action="add", name="High Guild", rep=8)
    server.faction(action="add", name="Low Guild", rep=-6)
    out = server.full_session_startup()
    assert "FACTION STANDINGS" in out
    assert out.index("High Guild") < out.index("Low Guild")
    assert "Friend" in out and "Enemy" in out


def test_briefing_omitted_when_empty(isolate_campaign_dir):
    out = server.full_session_startup()
    assert "FACTION STANDINGS" not in out


# ---------------------------------------------------------------------------
# Task 9: Channel-2 faction-name injection in check_canon
# ---------------------------------------------------------------------------

def test_faction_injection_helper_hits_named(isolate_campaign_dir):
    server.faction(action="add", name="Mycomorph Colony", rep=6)
    lines = server._faction_injection_lines("We meet the Mycomorph Colony envoy.")
    assert len(lines) == 1
    assert "Mycomorph Colony" in lines[0] and "+6" in lines[0] and "Friend" in lines[0]


def test_faction_injection_helper_silent_when_absent(isolate_campaign_dir):
    server.faction(action="add", name="Mycomorph Colony", rep=6)
    assert server._faction_injection_lines("We walk north across the dunes.") == []


def test_faction_injection_helper_caps_at_three(isolate_campaign_dir):
    for i in range(5):
        server.faction(action="add", name=f"Guild {i}", rep=i)
    msg = "We deal with Guild 0, Guild 1, Guild 2, Guild 3, Guild 4 at once."
    assert len(server._faction_injection_lines(msg)) <= 3


class _MockCtx:
    """Minimal MCP Context stand-in (check_canon never touches ctx before the
    faction-injection block, verified by grep)."""
    pass


def test_injection_surfaces_through_check_canon_end_to_end(isolate_campaign_dir):
    """Channel-2 PROOF: the faction line actually appears in check_canon output
    (not just the helper). Seeds a minimal lorebook.json so check_canon doesn't
    early-return on 'lorebook.json not found'."""
    import json as _json
    (isolate_campaign_dir / "lorebook.json").write_text(
        _json.dumps({"entries": []}), encoding="utf-8")
    server.faction(action="add", name="Mycomorph Colony", rep=6, scope="alliance")
    out = server.check_canon(_MockCtx(), user_input="We head to meet the Mycomorph Colony envoy.", needs=[])
    assert "Mycomorph Colony" in out
    assert "+6" in out and "Friend" in out
    assert "FACTION:" in out


def test_injection_silent_through_check_canon_when_unnamed(isolate_campaign_dir):
    import json as _json
    (isolate_campaign_dir / "lorebook.json").write_text(
        _json.dumps({"entries": []}), encoding="utf-8")
    server.faction(action="add", name="Mycomorph Colony", rep=6)
    out = server.check_canon(_MockCtx(), user_input="We walk north across the empty dunes.", needs=[])
    assert "FACTION:" not in out


# --- Final-review regression tests (self-oppose, word-boundary, silent mirror clamp) ---

def test_oppose_self_is_rejected(isolate_campaign_dir):
    server.faction(action="add", name="Alpha", rep=5)
    out = server.faction(action="oppose", name="Alpha", other="Alpha")
    assert "cannot oppose itself" in out.lower()
    data, _ = server._load_factions()
    assert data["factions"]["alpha"]["opposed"] == []


def test_earn_does_not_self_mirror_even_if_opposed_lists_self(isolate_campaign_dir):
    # defensively force a self-entry into opposed, then earn must not cancel itself
    server.faction(action="add", name="Alpha", rep=5)
    data, _ = server._load_factions()
    data["factions"]["alpha"]["opposed"] = ["alpha"]
    server._save_factions(data)
    server.faction(action="earn", name="Alpha", amount=3, reason="deed")
    data, _ = server._load_factions()
    assert data["factions"]["alpha"]["rep"] == 8  # +3, not self-cancelled back to 5


def test_injection_no_midword_false_positive(isolate_campaign_dir):
    server.faction(action="add", name="Ra", rep=4)
    assert server._faction_injection_lines("the brain controls the terrain") == []
    # but a real word-boundary mention still hits
    hits = server._faction_injection_lines("we petition Ra for aid")
    assert len(hits) == 1 and "Ra" in hits[0]


def test_mirror_at_floor_reports_unchanged_no_phantom_history(isolate_campaign_dir):
    server.faction(action="add", name="Sun Cult", rep=0)
    server.faction(action="add", name="Moon Cult", rep=-10)
    server.faction(action="oppose", name="Sun Cult", other="Moon Cult")
    before_hist = len(server._load_factions()[0]["factions"]["moon_cult"]["history"])
    out = server.faction(action="earn", name="Sun Cult", amount=5, reason="aided")
    assert "unchanged" in out.lower() and "bound" in out.lower()
    data, _ = server._load_factions()
    assert data["factions"]["moon_cult"]["rep"] == -10  # still floored
    # no phantom history entry for the no-op mirror
    assert len(data["factions"]["moon_cult"]["history"]) == before_hist


def test_mirror_partial_clamp_logs_actual_delta(isolate_campaign_dir):
    # Moon at -8, opposed; Sun earns +5 -> mirror -8-5=-13 clamps to -10 (actual delta -2)
    server.faction(action="add", name="Sun Cult", rep=0)
    server.faction(action="add", name="Moon Cult", rep=-8)
    server.faction(action="oppose", name="Sun Cult", other="Moon Cult")
    server.faction(action="earn", name="Sun Cult", amount=5, reason="aided")
    data, _ = server._load_factions()
    mh = data["factions"]["moon_cult"]["history"][-1]
    assert data["factions"]["moon_cult"]["rep"] == -10
    assert mh["delta"] == -2 and mh["rep_after"] == -10  # honest applied delta, not -5
