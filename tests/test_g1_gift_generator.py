"""G1 - generate(action='gift'), gleam_check book-true test mode, advance_day GLEAM TICK.

Book: CH printed pp. 47-50. The old gleam_check thresholds (20+/25+/30+) were
invented - these tests pin the real Gleam Test table (1-15 nothing, 16-34
individual, 35+ cap) and the engine-owned weekly cadence (Joe ruling 2026-06-12).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import server


def _pc(name, gifts=None, psy=1):
    return {
        "name": name,
        "abilities": {"PSY": {"current": psy}},
        "hp": {"current": 20, "max": 20},
        "mystic_gifts": gifts if gifts is not None else [],
    }


@pytest.fixture
def roster(monkeypatch, tmp_path):
    """Two gifted PCs + one giftless; deterministic day 100; isolated threads/state."""
    data = {
        "characters": {
            "creenash": _pc("Creenash", gifts=[{"name": "Dissolving Thread"},
                                               {"name": "Kronophage's Echo"}], psy=1),
            "vela": _pc("Vela", gifts=[{"name": "Telepathy"}], psy=0),
            "petros": _pc("Petros", gifts=[], psy=0),
        },
        "meta": {"campaign_day": 100},
    }
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda key, char, d: None)
    monkeypatch.setattr(server, "THREADS_FILE", tmp_path / "narrative_threads.json")
    server.GAME_STATE.pop("world_tick", None)
    yield data
    server.GAME_STATE.pop("world_tick", None)


# --- generate(action="gift") -------------------------------------------------

def test_generate_gift_forced_rolls():
    out = server._generate_gift(roll="20,20,20,20")
    assert "Subtle Entropy" in out
    assert "agree" in out.lower()  # the book's collaborative-effect rule
    assert 'gift(action="add"' in out  # push the persistence call


def test_generate_gift_random_returns_name():
    out = server.generate(action="gift")
    # name = "<Quality> <Form>" - both words must come from the book tables
    import gifts as g
    q_all = {e for rows in g.GIFT_QUALITY.values() for e in rows}
    f_all = {e for rows in g.GIFT_FORM.values() for e in rows}
    import re
    m = re.search(r"\*\*(\S+) (\S+)\*\*", out)
    assert m, out
    assert m.group(1) in q_all and m.group(2) in f_all


def test_generate_gift_sample_mode():
    out = server.generate(action="gift", sample=True, roll=12)
    assert "Devouring Memories" in out  # source (PDF geometry fix)
    assert "Inhuman Speed" in out      # gift


# --- gleam_check: book table replaces invented thresholds ---------------------

def test_gleam_check_no_invented_thresholds(roster):
    out = server.gift(action='gleam', character_name="Creenash")
    assert "GLEAM:** 3" in out  # 2 gifts + PSY 1
    for invented in ("20+", "25+", "30+"):
        assert invented not in out
    assert "16" in out and "35+" in out  # book bands


def test_gleam_test_quiet_result(roster, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # d20=1, total 4
    out = server.gift(action='gleam', character_name="Creenash", test=True)
    assert "Nothing" in out or "nothing" in out
    assert "thread" not in out.lower() or "clock_due_day" not in out


def test_gleam_test_threat_winds_clock_push(roster, monkeypatch):
    # Creenash Gleam 3; force d20=17 -> total 20 = d4 Seekers, arrive d6 days.
    monkeypatch.setattr(server.random, "randint", lambda a, b: {20: 17}.get(b, 3))
    out = server.gift(action='gleam', character_name="Creenash", test=True)
    assert "Seekers of Eyeless Wisdom" in out
    assert 'thread(action="add"' in out
    assert "clock_due_day=103" in out  # day 100 + forced d6=3


def test_gleam_test_stamps_cadence(roster, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.gift(action='gleam', character_name="Creenash", test=True)
    assert server.GAME_STATE["world_tick"]["gleam_last_test_day"] == 100


def test_gleam_test_cap_at_35(roster, monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)  # total 23.. need higher
    # Vela gleam 1: d20=20 -> 21. Use Creenash gleam 3 + 20 = 23. Force via psy:
    roster["characters"]["creenash"]["abilities"]["PSY"]["current"] = 15  # gleam 17, total 37
    out = server.gift(action='gleam', character_name="Creenash", test=True)
    assert "Extradimensional Mystic Hunter" in out
    assert "IMMEDIATE" in out


# --- advance_day GLEAM TICK ---------------------------------------------------

def test_first_advance_seeds_stamp_no_nag(roster):
    out = server.advance_day(101, "march")
    assert "GLEAM TEST DUE" not in out
    assert server.GAME_STATE["world_tick"]["gleam_last_test_day"] == 101


def test_week_elapsed_nags_per_gifted_pc(roster):
    server.GAME_STATE["world_tick"] = {"gleam_last_test_day": 94}
    out = server.advance_day(101, "a week passes")
    assert "GLEAM TEST DUE" in out
    assert 'gift(action="gleam", character_name="creenash", test=true)' in out.lower()  # Wave: gleam_check -> gift(action="gleam")
    assert "Vela" in out
    assert "Petros" not in out  # giftless - no test


def test_under_a_week_is_silent(roster):
    server.GAME_STATE["world_tick"] = {"gleam_last_test_day": 95}
    out = server.advance_day(101, "six days")
    assert "GLEAM TEST DUE" not in out


def test_nag_repeats_until_test_runs(roster, monkeypatch):
    server.GAME_STATE["world_tick"] = {"gleam_last_test_day": 90}
    out1 = server.advance_day(101, "overdue")
    assert "GLEAM TEST DUE" in out1
    out2 = server.advance_day(102, "still overdue")
    assert "GLEAM TEST DUE" in out2  # nags every day until stamped
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    server.gift(action='gleam', character_name="Creenash", test=True)
    out3 = server.advance_day(103, "tested now")
    assert "GLEAM TEST DUE" not in out3


def test_gleam_tick_fail_soft(roster, monkeypatch):
    server.GAME_STATE["world_tick"] = {"gleam_last_test_day": 90}
    monkeypatch.setattr(server, "_load_characters",
                        lambda: (None, "boom"))
    out = server.advance_day(101, "broken roster")
    assert "Advanced to Day 101" in out  # advance_day survives
