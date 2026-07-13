"""E1 Task 3: condition(action=apply|clear|status|save) + DIS surfacing +
generic no-HP-regain rest reason.

Uses isolate_campaign_dir (conftest.py autouse) + _seed helper mirroring
the pattern from tests/test_death_gate_twinning.py.
"""
import json
import pytest
import server


# ---------------------------------------------------------------------------
# Minimal character fixtures
# ---------------------------------------------------------------------------

def _creenash():
    return {
        "name": "Creenash",
        "hp": {"current": 19, "max": 23},
        "wound_table": "biological",
        "type": "character",
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 6, "base": 4},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": [],
    }


def _vela():
    return {
        "name": "Vela",
        "hp": {"current": 24, "max": 24},
        "wound_table": "biological",
        "type": "character",
        "abilities": {
            "STR": {"current": 2, "base": 2},
            "DEX": {"current": 4, "base": 4},
            "CON": {"current": 3, "base": 3},
            "INT": {"current": 4, "base": 4},
            "PSY": {"current": 3, "base": 3},
            "EGO": {"current": 5, "base": 3},
        },
        "conditions": [],
    }


def _sandwalker():
    """A vehicle entry to test vehicle refusal."""
    return {
        "name": "Sandwalker",
        "type": "vehicle",
        "hp": {"current": 20, "max": 20},
    }


def _seed(dirpath, creenash_data=None, vela_data=None, day=100, include_vehicle=True):
    """Write minimal character split-sheets into the temp campaign dir."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {
        "version": 1,
        "campaign_day": day,
        "supply": {
            "mode": "abundant",
            "pool": None,
            "follower_mouths": 0,
            "separated": [],
            "ledger": {"day": day, "consumed": {}},
        },
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash_data if creenash_data is not None else _creenash()))
    (chars_dir / "vela.json").write_text(
        json.dumps(vela_data if vela_data is not None else _vela()))
    if include_vehicle:
        (chars_dir / "sandwalker.json").write_text(json.dumps(_sandwalker()))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(name="creenash"):
    data, err = server._load_characters()
    assert not err
    return server._find_character(data, name)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_apply_minimal_and_status(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="condition", action="apply", character="creenash", name="Marked",
                           note="the Kronophage remembers")
    assert "Marked" in out and "DM rules" in out
    _, ch = _get()
    assert any(c.get("name") == "Marked" for c in ch["conditions"])
    st = server.affliction(kind="condition", action="status")
    assert "Marked" in st


def test_apply_structured_burning(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                           cause="lava floe", tick_cadence="round", tick_hp="d8",
                           note="until extinguished")
    assert "round" in out and "d8" in out
    _, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Burning")
    assert rec["tick"] == {"cadence": "round", "hp": "d8"}


def test_apply_validation_errors(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    assert "needs at least a name" in server.affliction(kind="condition", action="apply",
                                                       character="creenash")
    bad = server.affliction(kind="condition", action="apply", character="creenash", name="X",
                           tick_cadence="hour", tick_hp="d4")
    assert "cadence" in bad
    _, ch = _get()
    assert not any(c.get("name") == "X" for c in ch.get("conditions", []))


def test_apply_round_abilities_only_refused(isolate_campaign_dir):
    """Round-cadence with only tick_abilities (no tick_hp) would never fire
    anywhere - the mint refuses it and nothing is stored."""
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="condition", action="apply", character="creenash", name="Withering",
                           tick_cadence="round", tick_abilities='{"STR": "d4"}')
    assert "tick.hp" in out
    _, ch = _get()
    assert not any(c.get("name") == "Withering"
                   for c in ch.get("conditions", []))


def test_apply_duplicate_refused(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Marked")
    out = server.affliction(kind="condition", action="apply", character="creenash", name="Marked")
    assert "already" in out.lower()


def test_vehicle_refused_corpse_warned(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    data, _ = server._load_characters()
    # vehicles in the roster should be refused
    vkey = next((k for k, c in data["characters"].items()
                 if c.get("type") == "vehicle"), None)
    if vkey:
        out = server.affliction(kind="condition", action="apply", character=vkey, name="Rust")
        assert "vehicle" in out.lower()
    # dead character: warn but still apply
    key, ch = _get("vela")
    ch["hp"]["current"] = -20
    server._save_single_character(key, ch, data)
    out = server.affliction(kind="condition", action="apply", character="vela", name="Marked")
    assert "dead" in out.lower() or "corpse" in out.lower()  # warn, not refuse
    _, ch2 = _get("vela")
    assert any(c.get("name") == "Marked" for c in ch2["conditions"])


def test_clear_one_and_all(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8")
    server.affliction(kind="condition", action="apply", character="creenash", name="Marked")
    out = server.affliction(kind="condition", action="clear", character="creenash", name="Burning")
    assert "cleared" in out.lower()
    _, ch = _get()
    assert not any(c["name"] == "Burning" for c in ch["conditions"])
    out = server.affliction(kind="condition", action="clear", character="creenash",
                           all_conditions=True)
    assert "p.229" in out or "revival" in out.lower()   # revival-lever reminder
    _, ch = _get()
    assert ch.get("conditions", []) == []


def test_apply_all_params_round_trip(isolate_campaign_dir):
    """Every structured field minted by normalize_record survives the trip
    through the tool to the stored record."""
    _seed(isolate_campaign_dir, day=120)
    out = server.affliction(kind="condition", 
        action="apply", character="creenash", name="Jellybones",
        cause="coral spores", note="glows in the dark",
        no_hp_regain=True, dis_saves="DEX,CON",
        tick_cadence="week", tick_hp="d4",
        tick_abilities='{"STR": "d4", "CON": "d4"}',
        save_ability="CON", save_dc=12, death_day=150)
    assert "Jellybones" in out
    _, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Jellybones")
    assert rec["since_day"] == 120
    assert rec["cause"] == "coral spores"
    assert rec["note"] == "glows in the dark"
    assert rec["death_day"] == 150
    assert rec["effects"]["no_hp_regain"] is True
    assert rec["effects"]["dis_saves"] == ["DEX", "CON"]
    assert rec["tick"] == {"cadence": "week", "hp": "d4",
                           "abilities": {"STR": "d4", "CON": "d4"}}
    assert rec["save_to_end"] == {"ability": "CON", "dc": 12}
    # malformed tick_abilities JSON -> error returned, nothing stored
    bad = server.affliction(kind="condition", action="apply", character="creenash", name="Glitch",
                           tick_cadence="day", tick_abilities='{not json')
    assert "JSON" in bad
    _, ch2 = _get()
    assert not any(c.get("name") == "Glitch" for c in ch2["conditions"])


def test_apply_pushes_next_calls(isolate_campaign_dir):
    """PUSH-over-PULL: apply output carries the literal next call for
    save-to-end and the partner-side Twinning stamp."""
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="condition", action="apply", character="creenash",
                           name="Brain Coral", save_ability="CON", save_dc=11)
    assert ('affliction(kind="condition", action="save", character="Creenash", '
            'name="Brain Coral", save_total=<roll>)') in out
    out2 = server.affliction(kind="condition", action="apply", character="creenash",
                            name="Twinning", twin_partner="Vela")
    assert ('affliction(kind="condition", action="apply", character="Vela", '
            'name="Twinning", twin_partner="Creenash")') in out2


def test_clear_ambiguous_substring_refused(isolate_campaign_dir):
    """A substring matching MULTIPLE differently-named conditions must error
    out, not silently clear them all (mirrors wound heal ambiguity)."""
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8")
    server.affliction(kind="condition", action="apply", character="creenash", name="Brain Coral",
                     save_ability="CON", save_dc=11)
    out = server.affliction(kind="condition", action="clear", character="creenash", name="b")
    assert "ambiguous" in out.lower()
    assert "Burning" in out and "Brain Coral" in out
    # BOTH conditions still present
    _, ch = _get()
    names = {c.get("name") for c in ch["conditions"]}
    assert {"Burning", "Brain Coral"} <= names


def test_status_death_clock_countdown(isolate_campaign_dir):
    """status renders death clocks as a countdown when campaign_day is known."""
    _seed(isolate_campaign_dir, day=130)
    server.affliction(kind="condition", action="apply", character="creenash", name="Doom Mark",
                     cause="ritual", death_day=134)
    st = server.affliction(kind="condition", action="status")
    assert "DIES Day 134" in st
    assert "in 4 day(s)" in st


def test_save_no_matching_condition(isolate_campaign_dir):
    """save against a name with no save_to_end -> error, nothing cleared."""
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Marked")
    out = server.affliction(kind="condition", action="save", character="creenash",
                           name="Marked", save_total=15)
    assert "No save-to-end condition matching" in out
    _, ch = _get()
    assert any(c.get("name") == "Marked" for c in ch["conditions"])


def test_save_to_end_pass_clears_fail_keeps(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Brain Coral",
                     save_ability="CON", save_dc=11)
    prompt = server.affliction(kind="condition", action="status")
    assert "CON" in prompt and "11" in prompt
    out = server.affliction(kind="condition", action="save", character="creenash",
                           name="Brain Coral", save_total=10)
    assert "FAIL" in out
    _, ch = _get()
    assert any(c["name"] == "Brain Coral" for c in ch["conditions"])
    out = server.affliction(kind="condition", action="save", character="creenash",
                           name="Brain Coral", save_total=11)
    assert "PASS" in out
    _, ch = _get()
    assert not any(c["name"] == "Brain Coral" for c in ch["conditions"])


def test_condition_save_note_in_prompts(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Jellybones",
                     dis_saves="DEX,CON")
    _, ch = _get()
    note = server._condition_save_note(ch, "CON")
    assert "DISADVANTAGE" in note and "Jellybones" in note
    assert server._condition_save_note(ch, "PSY") == ""


def test_generic_no_hp_regain_blocks_rest(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Curse of Rust",
                     no_hp_regain=True)
    _, ch = _get()
    ch["hp"]["current"] = max(1, ch["hp"]["current"] - 3)
    reason = server._deprived_block_reason(ch)
    assert "Curse of Rust" in reason
