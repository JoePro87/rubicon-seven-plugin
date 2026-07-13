"""E1 review fix: twinning_pending marks EXPIRE - nothing pairs outside
its exact window (R-E1h), so stale marks must be popped, not shout forever.

Lifecycle owners:
  (a) advance_day pops any mark whose window != the new day (before ticks);
  (b) combat(action='end') pops combat-window marks (the fight is over);
  (c) condition(action='clear', name='Twinning') pops the mark with the bond.

Seeding pattern mirrors test_condition_ticks.py / test_death_gate_twinning.py
(isolate_campaign_dir autouse conftest + split-sheet file writes).
"""
import json
import pytest
import server


# ---------------------------------------------------------------------------
# Seed helpers (mirror test_condition_ticks.py)
# ---------------------------------------------------------------------------

def _brek_char(day=100, hp=19, conditions=None):
    return {
        "name": "Brek",
        "hp": {"current": hp, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 4, "base": 4},
            "DEX": {"current": 6, "base": 6},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _mira_char(conditions=None):
    return {
        "name": "Mira",
        "hp": {"current": 24, "max": 24},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 2, "base": 2},
            "DEX": {"current": 4, "base": 4},
            "CON": {"current": 3, "base": 3},
            "INT": {"current": 4, "base": 4},
            "PSY": {"current": 3, "base": 3},
            "EGO": {"current": 5, "base": 3},
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed(dirpath, day=100, brek=None, mira=None):
    """Write minimal split-sheet structure; abundant supply keeps the supply tick silent."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {
        "version": 1,
        "campaign_day": day,
        "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                   "separated": [], "ledger": {"day": day, "consumed": {}}},
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "brek.json").write_text(
        json.dumps(brek if brek is not None else _brek_char(day)))
    (chars_dir / "mira.json").write_text(
        json.dumps(mira if mira is not None else _mira_char()))


def _status_md(dirpath, day):
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get_brek():
    data, err = server._load_characters()
    assert not err
    key, ch = server._find_character(data, "brek")
    return data, key, ch


def _twin_pair():
    """Stamp a mutual Twinning bond via the condition tool."""
    for me, partner in (("brek", "Mira"), ("mira", "Brek")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)


def _seed_combat(monkeypatch, round_num=4):
    """Full combat dict so _combat_end can summarize/archive without crashing."""
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": round_num,
        "initiative": "pcs",
        "pcs_acted": True,
        "enemies_acted": True,
        "morale_checked": False,
        "encounter_name": "test_fight",
        "started_at": "2026-06-11T00:00:00",
        "party_snapshot": {"brek": {"hp": 19, "max_hp": 23}},
        "enemies": {
            "Raider (scarred)": {
                "hp": 0, "max_hp": 15, "lvl": 2,
                "defeated": True, "fled": False,
                "resist_type": "Biological",
            }
        },
        "log": [],
        "weapons_fired": [],
    })


# ---------------------------------------------------------------------------
# (a) advance_day expires stale day/combat windows; same-call marks survive
# ---------------------------------------------------------------------------

def test_stale_day_pending_cleared_by_advance_day(isolate_campaign_dir):
    """A prior-day pending mark is popped by the next advance_day, with a note."""
    day = 100
    creen = _brek_char(day)
    creen["twinning_pending"] = {"window": "day:95"}
    _seed(isolate_campaign_dir, day=day, brek=creen)
    _status_md(isolate_campaign_dir, day)
    out = server.advance_day(day + 1, "stale mark expiry")
    assert "expired" in out and "day:95" in out
    _, _, ch = _get_brek()
    assert "twinning_pending" not in ch


def test_stale_combat_pending_cleared_by_advance_day(isolate_campaign_dir):
    """A leftover combat-round mark also expires at the day boundary."""
    day = 100
    creen = _brek_char(day)
    creen["twinning_pending"] = {"window": "combat:r7"}
    _seed(isolate_campaign_dir, day=day, brek=creen)
    _status_md(isolate_campaign_dir, day)
    out = server.advance_day(day + 1, "stale combat mark")
    assert "expired" in out and "combat:r7" in out
    _, _, ch = _get_brek()
    assert "twinning_pending" not in ch


def test_fresh_mark_from_same_call_tick_survives(isolate_campaign_dir):
    """A mark stamped by THIS call's tick (window == the new day) is kept:
    the cleanup runs before the ticks, so same-call pairing is unaffected."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _status_md(isolate_campaign_dir, day)
    _twin_pair()
    server.affliction(kind="condition", action="apply", character="brek", name="Doom Mark",
                     death_day=day + 1)
    out = server.advance_day(day + 1, "mark due but twinned")
    assert "death prevented" in out
    _, _, ch = _get_brek()
    assert ch.get("twinning_pending") == {"window": f"day:{day + 1}"}


# ---------------------------------------------------------------------------
# (b) combat end pops combat-window marks
# ---------------------------------------------------------------------------

def test_combat_end_clears_combat_window_pending(isolate_campaign_dir, monkeypatch):
    """Ending combat pops any combat:* pending mark - the window cannot recur."""
    day = 100
    creen = _brek_char(day)
    creen["twinning_pending"] = {"window": "combat:r3"}
    _seed(isolate_campaign_dir, day=day, brek=creen)
    _seed_combat(monkeypatch)
    out = server._combat_end()
    assert "death-pending" in out and "combat:r3" in out
    _, _, ch = _get_brek()
    assert "twinning_pending" not in ch


def test_combat_end_keeps_day_window_pending(isolate_campaign_dir, monkeypatch):
    """A day-window mark is NOT combat's to clear - advance_day owns it."""
    day = 100
    creen = _brek_char(day)
    creen["twinning_pending"] = {"window": f"day:{day}"}
    _seed(isolate_campaign_dir, day=day, brek=creen)
    _seed_combat(monkeypatch)
    out = server._combat_end()
    assert "death-pending" not in out
    _, _, ch = _get_brek()
    assert ch.get("twinning_pending") == {"window": f"day:{day}"}


# ---------------------------------------------------------------------------
# (c) single-name clear of Twinning pops the mark (clear-all already does)
# ---------------------------------------------------------------------------

def test_single_clear_twinning_pops_pending(isolate_campaign_dir):
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _twin_pair()
    data, key, ch = _get_brek()
    ch["twinning_pending"] = {"window": f"day:{day}"}
    server._save_single_character(key, ch, data)
    out = server.affliction(kind="condition", action="clear", character="brek", name="Twinning")
    assert "cleared" in out
    _, _, ch2 = _get_brek()
    assert "twinning_pending" not in ch2


def test_single_clear_other_condition_keeps_pending(isolate_campaign_dir):
    """Clearing a NON-twinned condition leaves the pending mark alone."""
    day = 100
    _seed(isolate_campaign_dir, day=day)
    _twin_pair()
    server.affliction(kind="condition", action="apply", character="brek", name="Burning",
                     tick_cadence="round", tick_hp="d8")
    data, key, ch = _get_brek()
    ch["twinning_pending"] = {"window": f"day:{day}"}
    server._save_single_character(key, ch, data)
    server.affliction(kind="condition", action="clear", character="brek", name="Burning")
    _, _, ch2 = _get_brek()
    assert ch2.get("twinning_pending") == {"window": f"day:{day}"}
