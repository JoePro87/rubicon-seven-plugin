"""C21: _combat_attack attacker-liveness guards.

The damage path already refuses damage TO a defeated/fled enemy, but nothing
refused an attack FROM one — and a PC at HP<=0 (incapacitated), unconscious, or
dead could swing with full engine cooperation. These guards make the engine an
honest layer for a fresh DM-model: a defeated/fled enemy or a downed PC gets a
loud refusal; a healthy attacker (and a malformed hp shape, fail-open) still
attacks.

Fixtures/idioms mirror test_combat_attack.py.
"""
import server
import engine_core


_TRISKELE = {
    "name": "Triskele",
    "type": "exotica_weapon ranged",
    "damage": "3d8",
    "damage_type": "beam",
    "engine_tags": [],
    "primary": True,
}

_ROSCAR = {
    "name": "Roscar",
    "type": "follower",  # not the player PC -> auto-rolls
    "hp": {"current": 23, "max": 23},
    "wound_table": "biological",
    "abilities": {"STR": {"current": 1, "base": 1}, "DEX": {"current": 2, "base": 2}},
    "inventory": {"carried": [_TRISKELE]},
}


def _enemy(hp=15, av=12, **over):
    e = {
        "hp": hp, "max_hp": hp, "av": av, "morale": 0, "lvl": 2,
        "defeated": False, "fled": False, "resist_type": "Biological",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False, "attack_name": "Slash", "attack_damage": "d6", "attacks": [],
    }
    e.update(over)
    return e


def _isolate(monkeypatch, characters, enemies, party_pcs=None):
    monkeypatch.setattr(server, "_load_characters", lambda: (characters, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    snapshot = {n: {"hp": (d.get("hp") or {}).get("current", 1),
                    "max_hp": (d.get("hp") or {}).get("max", 1)}
                for n, d in characters["characters"].items()}
    if party_pcs:
        snapshot.update(party_pcs)
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": dict(enemies), "party_snapshot": snapshot, "log": []})


# --- enemy attacker liveness ------------------------------------------------

def test_defeated_enemy_attack_refused(monkeypatch):
    _isolate(monkeypatch, {"characters": {"Roscar": _ROSCAR}},
             {"Raider (scarred)": _enemy(defeated=True)})
    out = server._combat_attack("Raider (scarred)", None, "Roscar")
    assert "is already defeated" in out


def test_fled_enemy_attack_refused(monkeypatch):
    _isolate(monkeypatch, {"characters": {"Roscar": _ROSCAR}},
             {"Raider (scarred)": _enemy(fled=True)})
    out = server._combat_attack("Raider (scarred)", None, "Roscar")
    assert "has fled" in out


# --- PC attacker liveness ---------------------------------------------------

def test_downed_pc_at_zero_hp_refused_loud(monkeypatch):
    downed = dict(_ROSCAR); downed["hp"] = {"current": 0, "max": 23}
    _isolate(monkeypatch, {"characters": {"Roscar": downed}},
             {"Raider (scarred)": _enemy()})
    # if the guard fails, the engine would roll -> make a roll blow up
    monkeypatch.setattr(server.random, "randint",
                        lambda a, b: (_ for _ in ()).throw(AssertionError("must not roll")))
    out = server._combat_attack("Roscar", "Triskele", "Raider (scarred)")
    assert "BLOCKED" in out
    assert "incapacitated at 0 HP" in out


def test_dead_pc_refused(monkeypatch):
    dead = dict(_ROSCAR); dead["hp"] = {"current": -20, "max": 23}
    _isolate(monkeypatch, {"characters": {"Roscar": dead}},
             {"Raider (scarred)": _enemy()})
    out = server._combat_attack("Roscar", "Triskele", "Raider (scarred)")
    assert "BLOCKED" in out
    assert "dead" in out.lower()


def test_unconscious_pc_refused(monkeypatch):
    ko = dict(_ROSCAR)
    ko["hp"] = {"current": 5, "max": 23}  # still positive, but KO'd by a wound
    ko["wounds"] = [{"name": "Motive Drive Inhibited", "unconscious": True}]
    _isolate(monkeypatch, {"characters": {"Roscar": ko}},
             {"Raider (scarred)": _enemy()})
    out = server._combat_attack("Roscar", "Triskele", "Raider (scarred)")
    assert "BLOCKED" in out
    assert "unconscious" in out.lower()


# --- healthy + fail-open paths unchanged ------------------------------------

def test_healthy_pc_attacks_normally(monkeypatch):
    _isolate(monkeypatch, {"characters": {"Roscar": _ROSCAR}},
             {"Raider (scarred)": _enemy(hp=15, av=12)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)  # 15+DEX2=17>12 hit
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)
    out = server._combat_attack("Roscar", "Triskele", "Raider (scarred)")
    assert "BLOCKED" not in out
    assert "HIT" in out


def test_malformed_hp_shape_still_attacks(monkeypatch):
    """A PC whose hp key is missing/non-dict is treated as alive (fail-open): an
    attack guard must not silently paralyze combat over a malformed sheet. This
    is the OPPOSITE direction from engine_core._all_pcs_down (which fails DOWN)."""
    weird = dict(_ROSCAR); weird.pop("hp", None)  # no hp at all
    _isolate(monkeypatch, {"characters": {"Roscar": weird}},
             {"Raider (scarred)": _enemy(hp=15, av=12)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)
    out = server._combat_attack("Roscar", "Triskele", "Raider (scarred)")
    assert "BLOCKED" not in out
    assert "HIT" in out
