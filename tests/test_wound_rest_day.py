# tests/test_wound_rest_day.py
# Task 6: Rest & day integration -- Deprived blocks HP regain (short + long rest),
# long-rest wound listing PUSHES the exact wound() heal call, advance_day applies
# the daily-tick mutation per elapsed day while the wound is active (spec section 5/8).
#
# Real-file pattern from tests/test_rest_and_day.py: conftest's autouse
# isolate_campaign_dir fixture redirects server.CAMPAIGN_DIR (and therefore the
# read_file/write_file helpers and _load_characters/_save_single_character) to a
# temp dir, so these tests write real split sheets + CURRENT_STATUS.md safely.
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server
import wounds as w


def _write_char(char_id, char, day=50):
    """Write a split-sheet character; meta carries campaign_day (None = omit it)."""
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta = {"last_updated": "2026-01-01"}
    if day is not None:
        meta["campaign_day"] = day
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _write_status(day):
    (server.CAMPAIGN_DIR / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n"
        "**Last Updated:** 2026-01-01 00:00\n\n---\n\n"
        "## SCENE STATE\n\n"
        f"**Day:** {day}\n**Location:** Test Location\n",
        encoding="utf-8")


def _reload(name):
    data, _ = server._load_characters()
    _, char = server._find_character(data, name)
    return char


def _char(**ov):
    c = {
        "name": "Kess",
        "species": "cacogen",
        "hp": {"current": 5, "max": 29},
        "abilities": {"CON": {"current": 3, "base": 3},
                      "STR": {"current": 2, "base": 2},
                      "DEX": {"current": 2, "base": 2}},
        "wounds": [],
    }
    c.update(ov)
    return c


def _supercoolant():
    return w.roll_wound_record(-2, w.SYNTHETIC_WOUNDS[-2])     # deprived: True


def _cascading():
    return w.roll_wound_record(-13, w.SYNTHETIC_WOUNDS[-13])   # daily_tick STR/DEX 2


# --- short rest: Deprived blocks regain --------------------------------------

def test_short_rest_deprived_pc_heals_zero_and_names_wound():
    _write_char("roscar", _char(name="Roscar", hp={"current": 3, "max": 20},
                                wounds=[_supercoolant()]))
    out = server._rest_short_calculate("Roscar")
    roscar_line = next(l for l in out.split("\n") if "Roscar" in l)
    assert "cannot regain HP" in roscar_line
    assert "Supercoolant Leak" in roscar_line
    assert "Deprived until fixed" in roscar_line
    assert "heals" not in roscar_line          # no d8+CON offered


def test_short_rest_other_pcs_heal_normally_beside_deprived():
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / "_meta.json").write_text(json.dumps({"campaign_day": 50}))
    (chars_dir / "roscar.json").write_text(json.dumps(
        _char(name="Roscar", hp={"current": 3, "max": 20}, wounds=[_supercoolant()])))
    (chars_dir / "kess.json").write_text(json.dumps(_char()))
    out = server._rest_short_calculate("Roscar,Kess")
    kess_line = next(l for l in out.split("\n") if "Kess" in l)
    assert "heals d8 + 3" in kess_line          # unaffected by Roscar's wound


def test_short_rest_nondeprived_wound_does_not_block():
    _write_char("kess", _char(wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])]))
    out = server._rest_short_calculate("Kess")
    assert "heals d8 + 3" in out
    assert "cannot regain HP" not in out


# --- long rest: Deprived blocks the HP restore --------------------------------

def test_long_rest_deprived_pc_hp_not_restored():
    _write_char("roscar", _char(name="Roscar", hp={"current": 3, "max": 20},
                                wounds=[_supercoolant()]))
    out = server._rest_long("Roscar")
    assert "cannot regain HP" in out
    assert "Supercoolant Leak" in out
    assert "Deprived until fixed" in out
    assert _reload("Roscar")["hp"]["current"] == 3   # persisted: NOT restored


def test_long_rest_nondeprived_pc_still_restored_beside_deprived():
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    (chars_dir / "_meta.json").write_text(json.dumps({"campaign_day": 50}))
    (chars_dir / "roscar.json").write_text(json.dumps(
        _char(name="Roscar", hp={"current": 3, "max": 20}, wounds=[_supercoolant()])))
    (chars_dir / "kess.json").write_text(json.dumps(_char(hp={"current": 5, "max": 29})))
    server._rest_long("Roscar,Kess")
    assert _reload("Kess")["hp"]["current"] == 29
    assert _reload("Roscar")["hp"]["current"] == 3


# --- long rest: PUSH the exact heal call ---------------------------------------

def test_long_rest_wound_listing_pushes_exact_heal_call():
    rec = w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])     # Crippling Wound
    _write_char("kess", _char(hp={"current": 29, "max": 29}, wounds=[rec]))
    out = server._rest_long("Kess")
    assert "choose one to heal" in out
    assert 'affliction(kind="wound", action="heal", character="Kess", wound="Crippling Wound")' in out


def test_long_rest_push_lists_every_wound_with_its_own_call():
    recs = [w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7]),
            w.roll_wound_record(-8, w.BIOLOGICAL_WOUNDS[-8])]
    _write_char("kess", _char(hp={"current": 29, "max": 29}, wounds=recs))
    out = server._rest_long("Kess")
    assert 'affliction(kind="wound", action="heal", character="Kess", wound="Crippling Wound")' in out
    assert 'affliction(kind="wound", action="heal", character="Kess", wound="Weakening Wound")' in out


def test_long_rest_push_survives_apostrophe_wound_names():
    # "Death's Door" must not break the pushed call's quoting (U2 pattern:
    # double quotes inside the call string).
    rec = w.roll_wound_record(-19, w.BIOLOGICAL_WOUNDS[-19])
    _write_char("kess", _char(hp={"current": 29, "max": 29}, wounds=[rec]))
    out = server._rest_long("Kess")
    assert 'wound="Death\'s Door"' in out


def test_long_rest_deprived_pc_at_full_hp_still_offered_wound_heal():
    # Deprived blocks HP REGAIN only -- a deprived PC already at full HP must
    # still get the heal-one-wound offer (the book's own escape from the Leak).
    recs = [_supercoolant()]
    _write_char("roscar", _char(name="Roscar", hp={"current": 20, "max": 20},
                                wounds=recs))
    out = server._rest_long("Roscar")
    assert "choose one to heal" in out
    assert 'wound="Supercoolant Leak"' in out


# --- advance_day: daily tick ---------------------------------------------------

def test_advance_day_two_elapsed_days_tick_minus_2_per_day_each_stat():
    c = _char(wounds=[_cascading()])
    _write_char("kess", c, day=50)
    _write_status(50)
    out = server.advance_day(52, "travel")
    kess = _reload("Kess")
    assert kess["abilities"]["STR"]["current"] == -2   # 2 - (2 * 2 days)
    assert kess["abilities"]["DEX"]["current"] == -2
    assert "Cascading Kinesthetics" in out             # warning names the wound
    assert "WOUND DAILY TICK" in out                   # loud block
    assert "STR -4" in out and "DEX -4" in out         # per-stat totals


def test_advance_day_single_day_ticks_once():
    c = _char(wounds=[_cascading()])
    _write_char("kess", c, day=50)
    _write_status(50)
    server.advance_day(51, "overnight")
    kess = _reload("Kess")
    assert kess["abilities"]["STR"]["current"] == 0
    assert kess["abilities"]["DEX"]["current"] == 0


def test_advance_day_unknown_old_day_floors_elapsed_at_one():
    c = _char(wounds=[_cascading()])
    _write_char("kess", c, day=None)                   # _meta.json has no campaign_day
    _write_status(50)
    server.advance_day(99, "time skip")
    kess = _reload("Kess")
    assert kess["abilities"]["STR"]["current"] == 0    # ticked exactly once
    assert kess["abilities"]["DEX"]["current"] == 0


def test_advance_day_same_day_recall_does_not_tick_again():
    # advance_day is annotated idempotent: a retry/correction with the same
    # (or earlier) day number must NOT re-apply the permanent mutation.
    c = _char(wounds=[_cascading()])
    _write_char("kess", c, day=50)
    _write_status(50)
    server.advance_day(51, "overnight")                # ticks once: 2 -> 0
    out = server.advance_day(51, "retry same day")     # must NOT tick again
    kess = _reload("Kess")
    assert kess["abilities"]["STR"]["current"] == 0
    assert kess["abilities"]["DEX"]["current"] == 0
    assert "WOUND DAILY TICK" not in out


def test_advance_day_no_tick_when_wound_healed():
    c = _char(wounds=[])                               # healed -> derived read is empty
    _write_char("kess", c, day=50)
    _write_status(50)
    out = server.advance_day(52, "travel")
    kess = _reload("Kess")
    assert kess["abilities"]["STR"]["current"] == 2    # untouched
    assert kess["abilities"]["DEX"]["current"] == 2
    assert "WOUND DAILY TICK" not in out
