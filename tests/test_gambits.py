"""Gambits (CH p.29): an attack total HIGHER THAN 20 earns a stunt attempt in
addition to damage. Engine flags availability + pushes the book's menu; choosing,
the target's save, and the forgo-damage-to-deny-the-save trade are DM-adjudicated.
Hit-only (the book: 'in addition to rolling their attack's damage'). Enemies flag
too ('Intelligent NPCs and monsters can use gambits').
Fixture idioms from test_combat_attack.py; Creenash supplies the raw d20
(Iron Law 3), Triskele is ranged so the bonus is DEX 6."""
import copy

import server
from tests.test_combat_attack import (_CREENASH, _make_biological_enemy,
                                      _base_isolate)


def _chars():
    # Deep-copy: tests below mutate nested hp/inventory; a shallow dict() would
    # share those with the module-level _CREENASH and leak across tests.
    return {"characters": {"creenash": copy.deepcopy(_CREENASH)},
            "meta": {"campaign_day": 1}}


def test_gambit_flagged_on_hit_total_over_20(monkeypatch):
    _base_isolate(monkeypatch, _chars(), {"Bandit": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Triskele", "Bandit",
                                to_hit=15, damage_roll=3)     # 15 + DEX 6 = 21
    assert "GAMBIT AVAILABLE" in out
    assert '"gambit_available": true' in out          # dm_result JSON key
    assert "Disarm" in out and "forgo" in out.lower()   # menu + the trade


def test_no_gambit_at_exactly_20(monkeypatch):
    _base_isolate(monkeypatch, _chars(), {"Bandit": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Triskele", "Bandit",
                                to_hit=14, damage_roll=3)     # 14 + 6 = 20: NOT >20
    assert "HIT" in out
    assert "GAMBIT AVAILABLE" not in out
    assert '"gambit_available": false' in out


def test_no_gambit_on_miss_even_with_high_total(monkeypatch):
    # enemy AV 25 (enemy AV is uncapped): total 22 misses - no gambit without a hit
    _base_isolate(monkeypatch, _chars(), {"Tank": _make_biological_enemy(av=25)})
    out = server._combat_attack("Creenash", "Triskele", "Tank",
                                to_hit=16, damage_roll=3)     # 16 + 6 = 22 < 25
    assert "MISS" in out
    assert "GAMBIT AVAILABLE" not in out
    assert '"gambit_available": false' in out


def test_enemy_attack_flags_gambit_for_the_dm(monkeypatch):
    _base_isolate(monkeypatch, _chars(), {"Duelist": _make_biological_enemy(av=12)})
    # force the enemy d20 to 19 (no crit-path noise): 19 + lvl 2 = 21 vs PC AV
    monkeypatch.setattr(server.random, "randint",
                        lambda a, b: 19 if (a, b) == (1, 20) else a)
    out = server._combat_attack("Duelist", None, "Creenash")
    assert "HIT" in out
    assert "GAMBIT AVAILABLE" in out and "DM:" in out
    assert '"gambit_available": true' in out


def test_no_gambit_on_auto_hit_unconscious(monkeypatch):
    chars = _chars()
    chars["characters"]["creenash"]["hp"]["current"] = 0    # unconscious
    _base_isolate(monkeypatch, chars, {"Duelist": _make_biological_enemy(av=12)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: a)
    out = server._combat_attack("Duelist", None, "Creenash")
    assert "GAMBIT AVAILABLE" not in out


def test_tox_reroute_hit_still_flags_gambit(monkeypatch):
    """A poison-weapon hit at total>20 takes the Toxin-Die reroute - the
    gambit prompt must survive that early return (review catch)."""
    chars = _chars()
    chars["characters"]["creenash"]["inventory"]["carried"] = [{
        "name": "Venom Spine", "type": "exotica_weapon ranged",
        "damage": "d8", "damage_type": "TOX", "engine_tags": [], "primary": True,
    }]
    _base_isolate(monkeypatch, chars, {"Bandit": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Venom Spine", "Bandit",
                                to_hit=15, damage_roll=3)    # 15 + DEX 6 = 21
    assert "TOX" in out.upper()
    assert "GAMBIT AVAILABLE" in out
