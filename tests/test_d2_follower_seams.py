"""D2 Followers Task 3 - the two seam pushes (CH p.61).

Both are PUSH-ONLY: the engine computes and pushes; it NEVER resolves the
save or the desertion. Tests cover:
  * MORALE-on-allied-death: living followers get a prefilled morale-save line
    with correct max(own ML, leader EGO) math; the dying sheet is excluded;
    no followers -> no lines.
  * The PC-only resurrection gate: follower deaths emit NO resurrection push;
    PC deaths still emit it (regression).
  * The helper is wired into every death-emission site (asserted via the
    combat/damage site _apply_hp_damage_and_wounds AND the advance_day-gated
    supply-tick site).
  * DESERTION WATCH: a follower unfed 3 consecutive days draws the desertion
    line + a copy-paste-valid dismiss push; absent at 2 days; non-follower
    deprived sheets get no desertion line.

Direct-helper unit tests follow the test_g1_gift_generator.py pattern (pure
functions, no I/O); the integration tests reuse the file-seeding +
isolate_campaign_dir pattern from test_condition_ticks.py.
"""
import json

import pytest

import server


# ---------------------------------------------------------------------------
# Builders (pure-helper unit tests)
# ---------------------------------------------------------------------------

def _pc(name, ego=3, hp=10):
    return {"name": name, "level": 3, "hp": {"current": hp, "max": hp},
            "abilities": {"EGO": {"current": ego, "base": ego}}}


def _follower(name, leader="vela", ml=2, hp_current=4):
    return {"name": name, "type": "follower", "leader": leader, "level": 1,
            "ml": ml, "hp": {"current": hp_current, "max": 4},
            "wound_table": "biological",
            "abilities": {ab: {"current": 0, "base": 0}
                          for ab in server.PC_ABILITY_ORDER}}


# ---------------------------------------------------------------------------
# A) MORALE on allied death - pure helper math
# ---------------------------------------------------------------------------

def test_morale_lines_max_math_ml_beats_ego():
    """Follower whose own ML (4) beats the leader EGO bonus (2) -> use ML."""
    data = {"characters": {
        "vela": _pc("Vela", ego=2),
        "dying": _pc("Bob"),
        "scout": _follower("Scout", leader="vela", ml=4),
    }}
    lines = server._follower_morale_lines(data, "dying")
    assert len(lines) == 1
    ln = lines[0]
    assert ln.startswith("MORALE: Scout witnessed an allied death")
    assert "roll d20 + 4 vs 15" in ln
    assert "max(own ML 4, leader EGO 2)" in ln
    assert "(CH p.61)" in ln


def test_morale_lines_max_math_ego_beats_ml():
    """Follower whose leader EGO bonus (5) beats own ML (1) -> use EGO."""
    data = {"characters": {
        "vela": _pc("Vela", ego=5),
        "dying": _pc("Bob"),
        "grunt": _follower("Grunt", leader="vela", ml=1),
    }}
    lines = server._follower_morale_lines(data, "dying")
    assert len(lines) == 1
    assert "roll d20 + 5 vs 15" in lines[0]
    assert "max(own ML 1, leader EGO 5)" in lines[0]


def test_morale_lines_two_followers_distinct_math():
    """Two living followers -> two lines; one ML-wins, one EGO-wins."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "dying": _pc("Bob"),
        "scout": _follower("Scout", leader="vela", ml=4),   # ML 4 > EGO 3
        "grunt": _follower("Grunt", leader="vela", ml=1),   # EGO 3 > ML 1
    }}
    lines = server._follower_morale_lines(data, "dying")
    assert len(lines) == 2
    by_name = {l.split()[1]: l for l in lines}
    assert "roll d20 + 4 vs 15" in by_name["Scout"]
    assert "roll d20 + 3 vs 15" in by_name["Grunt"]


def test_morale_lines_dying_follower_excluded():
    """A dying follower does not save Morale for its own death."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "scout": _follower("Scout", leader="vela", ml=4),
        "grunt": _follower("Grunt", leader="vela", ml=1),
    }}
    lines = server._follower_morale_lines(data, "scout")
    assert len(lines) == 1
    assert lines[0].split()[1] == "Grunt"


def test_morale_lines_corpse_follower_excluded():
    """An already-dead follower (hp<=-20) does not save Morale."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "dying": _pc("Bob"),
        "corpse": _follower("Corpse", leader="vela", ml=4, hp_current=-20),
        "grunt": _follower("Grunt", leader="vela", ml=1),
    }}
    lines = server._follower_morale_lines(data, "dying")
    assert len(lines) == 1
    assert lines[0].split()[1] == "Grunt"


def test_morale_lines_no_followers_no_lines():
    data = {"characters": {"vela": _pc("Vela"), "dying": _pc("Bob")}}
    assert server._follower_morale_lines(data, "dying") == []


def test_morale_lines_missing_leader_falls_back_to_ml():
    """A follower whose leader key is missing -> EGO bonus 0, so own ML wins."""
    data = {"characters": {
        "dying": _pc("Bob"),
        "orphan": _follower("Orphan", leader="ghost", ml=2),
    }}
    lines = server._follower_morale_lines(data, "dying")
    assert "roll d20 + 2 vs 15" in lines[0]
    assert "leader EGO 0" in lines[0]


# ---------------------------------------------------------------------------
# B) PC-only resurrection gate via _death_seam_lines
# ---------------------------------------------------------------------------

def _has_resurrection(lines):
    return any("p.229" in l or "resurrect" in l.lower() for l in lines)


def test_death_seam_pc_emits_resurrection():
    data = {"characters": {"vela": _pc("Vela")}}
    lines = server._death_seam_lines(data["characters"]["vela"], data, "vela")
    assert _has_resurrection(lines)


def test_death_seam_follower_emits_no_resurrection():
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "scout": _follower("Scout", leader="vela", ml=2),
    }}
    f = data["characters"]["scout"]
    lines = server._death_seam_lines(f, data, "scout")
    assert not _has_resurrection(lines)


def test_death_seam_pc_death_also_pushes_morale():
    """A PC death gets BOTH the resurrection menu and a morale line per
    surviving follower."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "scout": _follower("Scout", leader="vela", ml=4),
    }}
    lines = server._death_seam_lines(data["characters"]["vela"], data, "vela")
    assert _has_resurrection(lines)
    assert any(l.startswith("MORALE: Scout") for l in lines)


# ---------------------------------------------------------------------------
# Integration: the helper is wired into the combat/damage death site
# ---------------------------------------------------------------------------

def test_combat_site_pc_death_emits_resurrection_and_morale():
    """_apply_hp_damage_and_wounds (the combat/damage seam) routes a PC death
    through _death_seam_lines: resurrection menu + a follower morale line."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3, hp=2),
        "scout": _follower("Scout", leader="vela", ml=4),
    }}
    vela = data["characters"]["vela"]
    vela["wound_table"] = "biological"
    lines, _ = server._apply_hp_damage_and_wounds(
        "vela", vela, data, 30, window_key="day:1")
    assert _has_resurrection(lines)
    assert any(l.startswith("MORALE: Scout") for l in lines)


def test_combat_site_follower_death_no_resurrection():
    """A follower dying on the combat seam emits NO resurrection push (the
    gate excludes type=='follower')."""
    data = {"characters": {
        "vela": _pc("Vela", ego=3),
        "scout": _follower("Scout", leader="vela", ml=2, hp_current=2),
        "grunt": _follower("Grunt", leader="vela", ml=1),
    }}
    scout = data["characters"]["scout"]
    scout["wound_table"] = "biological"
    lines, _ = server._apply_hp_damage_and_wounds(
        "scout", scout, data, 30, window_key="day:1")
    assert not _has_resurrection(lines)
    # the OTHER living follower still rolls Morale on the death
    assert any(l.startswith("MORALE: Grunt") for l in lines)


# ---------------------------------------------------------------------------
# Integration: the advance_day-gated supply-tick death site + desertion watch
# ---------------------------------------------------------------------------

def _seed_field(dirpath, day, chars, pool=None):
    """Write split-sheets + field-mode supply meta (empty pool -> unfed)."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {
        "version": 1,
        "campaign_day": day,
        "supply": {"mode": "field",
                   "pool": pool if pool is not None else {"food": 0, "water": 0},
                   "follower_mouths": 0, "separated": [],
                   "ledger": {"day": day, "consumed": {}}},
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    for key, ch in chars.items():
        (chars_dir / f"{key}.json").write_text(json.dumps(ch))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _deprived(cause, since_day, death_day):
    return {"name": "Deprived", "cause": cause,
            "since_day": since_day, "death_day": death_day}


def test_supply_tick_follower_thirst_death_no_resurrection(isolate_campaign_dir):
    """A follower dying of thirst on the supply tick (the advance_day-gated
    death site) emits NO resurrection push; a surviving follower gets MORALE."""
    day = 100
    dying = _follower("Scout", leader="vela", ml=2)
    dying["conditions"] = [_deprived("thirst", since_day=day - 3, death_day=day + 1)]
    chars = {
        "vela": dict(_pc("Vela", ego=3), conditions=[],
                     inventory={"carried": []}),
        "scout": dict(dying, inventory={"carried": []}),
        "grunt": dict(_follower("Grunt", leader="vela", ml=1),
                      inventory={"carried": []}),
    }
    _seed_field(isolate_campaign_dir, day, chars)
    out = server.advance_day(day + 1, "thirst clock due for the follower")
    assert "DIES of thirst" in out
    # PC-only gate: a follower corpse draws no p.229 menu
    assert "p.229" not in out
    # the surviving follower still rolls Morale on the death
    assert "MORALE: Grunt witnessed an allied death" in out


def test_supply_tick_desertion_line_at_three_days(isolate_campaign_dir):
    """Follower unfed exactly 3 consecutive days -> DESERTION RISK + a
    copy-paste-valid dismiss push. (death_day kept far off so the clock
    doesn't kill first.)"""
    day = 100
    scout = _follower("Scout", leader="vela", ml=2)
    # unfed since day-1; advancing to day+1 => 3 consecutive days (99,100,101)
    scout["conditions"] = [_deprived("thirst", since_day=day - 1, death_day=day + 50)]
    chars = {
        "vela": dict(_pc("Vela", ego=3), conditions=[], inventory={"carried": []}),
        "scout": dict(scout, inventory={"carried": []}),
    }
    _seed_field(isolate_campaign_dir, day, chars)
    out = server.advance_day(day + 1, "follower starving")
    assert "DESERTION RISK: Scout unfed 3 days" in out
    assert "(CH p.61)" in out
    assert 'character(action="dismiss_follower", name="Scout", reason="deserted")' in out


def test_supply_tick_no_desertion_at_two_days(isolate_campaign_dir):
    """Two consecutive days unfed -> no desertion line yet."""
    day = 100
    scout = _follower("Scout", leader="vela", ml=2)
    # unfed since day; advancing to day+1 => only 2 consecutive days (100,101)
    scout["conditions"] = [_deprived("thirst", since_day=day, death_day=day + 50)]
    chars = {
        "vela": dict(_pc("Vela", ego=3), conditions=[], inventory={"carried": []}),
        "scout": dict(scout, inventory={"carried": []}),
    }
    _seed_field(isolate_campaign_dir, day, chars)
    out = server.advance_day(day + 1, "follower starving")
    assert "DESERTION RISK" not in out


def test_supply_tick_non_follower_no_desertion(isolate_campaign_dir):
    """A non-follower PC deprived 3+ days draws NO desertion line (desertion
    is a follower-only rule)."""
    day = 100
    vela = dict(_pc("Vela", ego=3),
                conditions=[_deprived("thirst", since_day=day - 5, death_day=day + 50)],
                inventory={"carried": []})
    _seed_field(isolate_campaign_dir, day, {"vela": vela})
    out = server.advance_day(day + 1, "PC starving")
    assert "DESERTION RISK" not in out
