import server
import engine_core


def _combat_with_pc(monkeypatch, weapon):
    """Stage a minimal active_combat with one low-AV enemy and a PC carrying
    `weapon`. Returns the enemy descriptor. Guaranteed hit with to_hit=20."""
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "wound_table": "biological",
            "abilities": {"STR": {"current": 1}, "DEX": {"current": 2}},
            "inventory": {"carried": [weapon]}, "attacks": []}
    monkeypatch.setattr(server, "_load_characters",
                        lambda: ({"characters": {"roscar": char}}, None))
    monkeypatch.setattr(server, "_resolve_attacker_weapon",
                        lambda attacker, weapon=None: char["inventory"]["carried"][0])
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)   # deterministic hit (no flaky d20)
    desc = "Sand Brute (alpha)"
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1,
        "enemies": {desc: {"hp": 20, "max_hp": 20, "av": 5, "morale": 0, "lvl": 2,
                           "defeated": False, "fled": False,
                           "resist_type": "Biological",
                           "resistances": {"immune": [], "double": [], "half": [],
                                           "minimum": [], "varies": False},
                           "incorporeal": False, "attack_name": "Slam",
                           "attack_damage": "d6", "attacks": []}},
        "party_snapshot": {"roscar": {"hp": 23, "max_hp": 23}},
        "log": [],
    })
    return desc, char


def test_expended_weapon_is_hard_blocked(monkeypatch):
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
              "range": "ranged", "ammo": "Expended", "ammo_max": "Ud6",
              "damage_type": "kinetic"}
    desc, _ = _combat_with_pc(monkeypatch, weapon)
    out = server._combat_attack("roscar", "Railgun", desc, to_hit=20)
    assert "OUT OF AMMO" in out
    assert server.GAME_STATE["active_combat"]["enemies"][desc]["hp"] == 20


def test_firing_records_weapon(monkeypatch):
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6",
              "damage_type": "kinetic"}
    desc, _ = _combat_with_pc(monkeypatch, weapon)
    # A supplied to_hit means the player rolled their own dice, so damage_roll
    # comes too (routes through the engine in one call — Bugs 9/10).
    server._combat_attack("roscar", "Railgun", desc, to_hit=20, damage_roll=12)
    fired = server.GAME_STATE["active_combat"].get("weapons_fired", [])
    assert {"character": "roscar", "weapon": "Railgun"} in fired
    assert server.GAME_STATE["active_combat"]["enemies"][desc]["hp"] < 20  # attack still resolved (took damage)


def test_firing_twice_records_once(monkeypatch):
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6",
              "damage_type": "kinetic"}
    desc, _ = _combat_with_pc(monkeypatch, weapon)
    server._combat_attack("roscar", "Railgun", desc, to_hit=20)
    server._combat_attack("roscar", "Railgun", desc, to_hit=20)
    fired = server.GAME_STATE["active_combat"].get("weapons_fired", [])
    assert fired.count({"character": "roscar", "weapon": "Railgun"}) == 1


def test_parasitic_weapon_not_tracked(monkeypatch):
    weapon = {"name": "Gut Render", "type": "ranged_weapon", "damage": "3d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6",
              "tags": ["Parasitic"], "damage_type": "kinetic"}
    desc, _ = _combat_with_pc(monkeypatch, weapon)
    server._combat_attack("roscar", "Gut Render", desc, to_hit=20)
    fired = server.GAME_STATE["active_combat"].get("weapons_fired", [])
    assert fired == []


def test_combat_end_rolls_each_fired_weapon_once(monkeypatch, tmp_path):
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [
                {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
                 "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6"}]},
            "attacks": []}
    monkeypatch.setattr(server, "_load_characters",
                        lambda: ({"characters": {"roscar": char}}, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: None)
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # force deplete
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "encounter_name": "Test Skirmish", "round": 2, "started_at": "now",
        "enemies": {"Brute (a)": {"hp": 0, "max_hp": 10, "defeated": True, "fled": False}},
        "party_snapshot": {"roscar": {"hp": 23}},
        "weapons_fired": [{"character": "roscar", "weapon": "Railgun"}],
        "log": [],
    })
    out = server._combat_end()
    assert char["inventory"]["carried"][0]["ammo"] == "Ud4"   # Ud6 depleted once
    assert "Railgun" in out
