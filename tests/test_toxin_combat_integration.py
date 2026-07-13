import server
import substances
import engine_core


def test_round_advance_ticks_afflicted_enemy(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1, "initiative": "pcs",
        "pcs_acted": True, "enemies_acted": True, "morale_checked": False,
        "party_snapshot": {},
        "enemies": {"Ooze (alpha)": {"hp": 10, "max_hp": 10, "lvl": 2,
                                     "defeated": False, "fled": False,
                                     "resist_type": "Biological", "toxin_die": "d8"}},
        "log": [],
    })
    msg = server._check_round_advance()
    e = server.GAME_STATE["active_combat"]["enemies"]["Ooze (alpha)"]
    assert e["hp"] < 10
    assert "Toxin Die" in (msg or "")


def test_tox_hit_on_biological_enemy_incurs_die(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    # _toxin_enemy_save moved to substances (slice 2); called via mover->mover edge,
    # so patch BOTH namespaces (server alias + substances home).
    _tox_save_stub = lambda enemy, tox_die, rng=None: (False, "d20=1+2=3 vs DC 18")
    monkeypatch.setattr(server, "_toxin_enemy_save", _tox_save_stub)
    monkeypatch.setattr(substances, "_toxin_enemy_save", _tox_save_stub)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1, "enemies": {"Ooze (alpha)": {"hp": 16, "max_hp": 16, "lvl": 2,
                                                 "defeated": False, "fled": False,
                                                 "resist_type": "Biological"}},
        "party_snapshot": {}, "log": [],
    })
    out = server._toxin_attack_reroute(
        attacker=None, target="Ooze (alpha)", tox_die="d8", attacker_kind="pc")
    e = server.GAME_STATE["active_combat"]["enemies"]["Ooze (alpha)"]
    assert e.get("toxin_die") == "d8"
    assert e["hp"] == 16
    assert "Toxin Die" in out


def test_tox_hit_on_synthetic_enemy_immune(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1, "enemies": {"Drone (a)": {"hp": 12, "max_hp": 12, "lvl": 2,
                                              "defeated": False, "fled": False,
                                              "resist_type": "Synthetic"}},
        "party_snapshot": {}, "log": [],
    })
    out = server._toxin_attack_reroute(
        attacker=None, target="Drone (a)", tox_die="d8", attacker_kind="pc")
    assert "immune" in out.lower()
    assert "toxin_die" not in server.GAME_STATE["active_combat"]["enemies"]["Drone (a)"]


def test_toxin_die_from_dice():
    assert server._toxin_die_from_dice("d8") == "d8"
    assert server._toxin_die_from_dice("d8+2") == "d8"
    assert server._toxin_die_from_dice("2d6") == "d6"
    assert server._toxin_die_from_dice(None) == "d6"


# ---------------------------------------------------------------------------
# End-to-end regression: TOX weapon hit wired through _combat_attack
# ---------------------------------------------------------------------------

_ROSCAR_TOX = {
    "name": "Roscar",
    "hp": {"current": 23, "max": 23},
    "wound_table": "biological",
    "abilities": {
        "STR": {"current": 1, "base": 1},
        "DEX": {"current": 2, "base": 2},
    },
    "inventory": {"carried": []},
}


def test_tox_weapon_attack_through_combat_flow_incurs_die(monkeypatch):
    """End-to-end: a PC hits a Biological enemy with a TOX weapon via _combat_attack;
    the reroute imposes a Toxin Die and applies NO flat HP damage."""
    monkeypatch.setattr(server, "_load_characters",
                        lambda: ({"characters": {"Roscar": _ROSCAR_TOX}}, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    # Roscar is NOT Creenash, so `to_hit=` is ignored (Iron Law 3 gating) and the
    # engine rolls a live d20 — stub it to a guaranteed hit, else this flakes ~15%.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)

    # PC's resolved weapon is a TOX weapon (d8 TOX)
    monkeypatch.setattr(server, "_resolve_attacker_weapon",
                        lambda attacker, weapon=None: {"name": "Venom Stinger", "damage": "d8",
                                                       "damage_type": "TOX"})
    # Force the enemy save to FAIL so the die lands deterministically
    # _toxin_enemy_save moved to substances (slice 2); called via mover->mover edge,
    # so patch BOTH namespaces (server alias + substances home).
    _tox_save_stub = lambda enemy, tox_die, rng=None: (False, "d20=1+2=3 vs DC 18")
    monkeypatch.setattr(server, "_toxin_enemy_save", _tox_save_stub)
    monkeypatch.setattr(substances, "_toxin_enemy_save", _tox_save_stub)

    enemy_hp = 15
    enemy_descriptor = "Venom Crawler (alpha)"
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "enemies": {
            enemy_descriptor: {
                "hp": enemy_hp,
                "max_hp": enemy_hp,
                "av": 5,            # low AV; stubbed d20=20 (crit) -> guaranteed hit
                "morale": 0,
                "lvl": 2,
                "defeated": False,
                "fled": False,
                "resist_type": "Biological",
                "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
                "incorporeal": False,
                "attack_name": "Claw",
                "attack_damage": "d6",
                "attacks": [],
            }
        },
        "party_snapshot": {"Roscar": {"hp": 23, "max_hp": 23}},
        "log": [],
    })

    out = server._combat_attack("Roscar", "Venom Stinger", enemy_descriptor, to_hit=20)

    enemy = server.GAME_STATE["active_combat"]["enemies"][enemy_descriptor]
    assert enemy.get("toxin_die") == "d8", (
        f"Expected toxin_die='d8' to be set on enemy, got: {enemy.get('toxin_die')!r}\nOutput: {out[:400]}"
    )
    assert enemy["hp"] == enemy["max_hp"], (
        f"Expected NO flat HP damage (hp should stay {enemy['max_hp']}), got hp={enemy['hp']}\nOutput: {out[:400]}"
    )
    assert "Toxin" in out or "TOX" in out, (
        f"Expected 'Toxin' or 'TOX' in output, got: {out[:400]}"
    )
