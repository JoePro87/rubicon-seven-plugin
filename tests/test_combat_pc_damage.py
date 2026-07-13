"""Regression tests for combat damage dealt to a PARTY MEMBER.

Background: the PC branch of `_combat_damage` used to read `char["hp"]` as an int
and subtract from it, but characters store HP as a nested dict
({"current": N, "max": M}). Any enemy hit on a PC raised TypeError. It also
bypassed vulnerability doubling (e.g. a sheet's fire weakness, a tripwire fact)
and reached a stale wound table. The fix delegates the PC branch to
`_character_take_damage`, the authoritative path.

These tests lock that in. They mock the disk + unrelated combat machinery so no
real character data is touched.

Also covers Task 10: combat(action='damage') auto-reads attacker weapon
damage_type + engine_tags when `attacker` + (optionally) `weapon` are supplied.
"""
import server
import engine_core


def _make_char():
    """A PC with a FIRE vulnerability and nested HP — the shape that used to crash."""
    return {
        "name": "TestPC",
        "hp": {"current": 10, "max": 10},
        "wound_table": "biological",
        "special_traits": {
            "vulnerabilities": [
                {"type": "fire", "effect": "double damage", "source": "flammable"}
            ]
        },
    }


def _isolate(monkeypatch, fixture):
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(
        server, "_find_character",
        lambda data, name: ("TestPC", fixture["characters"]["TestPC"]),
    )
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {"enemies": {}, "party_snapshot": {"TestPC": {}}, "log": []},
    )


def test_pc_damage_does_not_crash_on_nested_hp(monkeypatch):
    """Plain (non-vulnerable) damage decrements nested HP without raising."""
    fixture = {"characters": {"TestPC": _make_char()}}
    _isolate(monkeypatch, fixture)

    out = server._combat_damage("TestPC", 4, "kinetic")

    assert "DOUBLED" not in out          # kinetic is not a vulnerability
    assert "10 -> 6" in out              # nested HP math, no crash


def test_pc_fire_vulnerability_is_doubled(monkeypatch):
    """Fire damage to a fire-vulnerable PC is doubled (the Creenash tripwire)."""
    fixture = {"characters": {"TestPC": _make_char()}}
    _isolate(monkeypatch, fixture)

    out = server._combat_damage("TestPC", 5, "fire")

    assert "DOUBLED" in out              # 5 -> 10
    assert "10 -> 0" in out              # 10 HP, doubled 10 damage


# ---------------------------------------------------------------------------
# Task 10: attacker weapon auto-read tests
# ---------------------------------------------------------------------------

_RAILGUN = {
    "name": "Blasphemous Psyche-Suppressant Nano-edged Railgun",
    "type": "exotica_weapon",
    "damage": "3d12",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": ["psyche-suppressant"],
}

_STAFF = {
    "name": "Luminous Piercing Nano-edged Quarterstaff",
    "type": "exotica_weapon",
    "damage": "3d8",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": [],
}

_ROSCAR = {
    "name": "Roscar",
    "hp": {"current": 23, "max": 23},
    "wound_table": "biological",
    "inventory": {
        "carried": [_RAILGUN, _STAFF],
    },
}


def _isolate_attacker(monkeypatch):
    """Set up a combat with a Psychic enemy and Roscar in the party snapshot."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {
            "enemies": {
                "Mind Eater": {
                    "hp": 20,
                    "max_hp": 20,
                    "defeated": False,
                    "fled": False,
                    "resist_type": "Psychic",
                },
            },
            "party_snapshot": {"Roscar": {}},
            "log": [],
        },
    )


def test_attacker_weapon_auto_read_doubles_vs_psychic(monkeypatch):
    """When attacker='Roscar' + weapon='Railgun', engine_tags are auto-fed and
    psyche-suppressant doubles damage against a Psychic enemy (5 -> 10)."""
    _isolate_attacker(monkeypatch)

    out = server._combat_damage("Mind Eater", 5, "kinetic", attacker="Roscar", weapon="Railgun")

    # Psyche-suppressant tag doubles vs Psychic: 20 - 10 = 10
    assert "10/20 HP" in out


def test_attacker_weapon_auto_read_no_attacker_backward_compat(monkeypatch):
    """When attacker is omitted, no auto-read occurs and manual params apply (no doubling)."""
    _isolate_attacker(monkeypatch)

    # Reset HP to 20 (each call uses a fresh GAME_STATE injection via _isolate_attacker,
    # but we call _isolate_attacker only once above — re-inject here for a clean state)
    server.GAME_STATE["active_combat"]["enemies"]["Mind Eater"]["hp"] = 20
    server.GAME_STATE["active_combat"]["enemies"]["Mind Eater"]["defeated"] = False

    out = server._combat_damage("Mind Eater", 5, "kinetic")

    # No weapon_tags passed -> no doubling -> 20 - 5 = 15
    assert "15/20 HP" in out


def test_attacker_weapon_not_found_returns_error(monkeypatch):
    """Passing weapon='Nonexistent' returns a descriptive error."""
    _isolate_attacker(monkeypatch)

    out = server._combat_damage("Mind Eater", 5, "kinetic", attacker="Roscar", weapon="Nonexistent")

    assert "not found" in out.lower()
    assert "Roscar" in out


def test_attacker_weapon_ambiguous_returns_error(monkeypatch):
    """Passing weapon='Nano-edged' (matches both weapons) returns an ambiguous error."""
    _isolate_attacker(monkeypatch)

    out = server._combat_damage("Mind Eater", 5, "kinetic", attacker="Roscar", weapon="Nano-edged")

    assert "ambiguous" in out.lower()


def test_attacker_not_a_pc_falls_through_to_manual_params(monkeypatch):
    """If attacker is an enemy name (not a PC), auto-read is skipped and manual params apply."""
    _isolate_attacker(monkeypatch)

    # Pass weapon_tags manually with attacker='Mind Eater' (not a PC)
    out = server._combat_damage("Mind Eater", 5, "kinetic", attacker="Some Enemy")

    # No doubling because no weapon_tags passed and enemy has no sheet
    assert "15/20 HP" in out


def _make_combat_with_enemy(monkeypatch, fixture):
    """Inject a Psychic enemy + party snapshot for an arbitrary PC fixture."""
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    name = next(iter(fixture["characters"]))
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {
            "enemies": {
                "Mind Eater": {
                    "hp": 20, "max_hp": 20, "defeated": False,
                    "fled": False, "resist_type": "Psychic",
                },
            },
            "party_snapshot": {name: {}},
            "log": [],
        },
    )


def test_armour_with_damage_field_is_not_selected_as_weapon(monkeypatch):
    """A spiked shield (type=armour, damage field, no av_bonus) must NOT be
    treated as a weapon — the sole real weapon is selected with no ambiguity."""
    shield = {"name": "Spiny Shield", "type": "armour", "damage": "1d4"}
    pc = {
        "name": "Shielder",
        "hp": {"current": 20, "max": 20},
        "wound_table": "biological",
        "inventory": {"carried": [shield, _RAILGUN]},
    }
    fixture = {"characters": {"Shielder": pc}}

    # Set up the combat + character load patch first.
    _make_combat_with_enemy(monkeypatch, fixture)

    # The resolver should pick the railgun, ignoring the shield entirely.
    resolved = server._resolve_attacker_weapon("Shielder", None)
    assert isinstance(resolved, dict)
    assert resolved["name"] == _RAILGUN["name"]

    # And a no-weapon= damage call resolves cleanly (no ambiguity error) and
    # auto-doubles via the railgun's psyche-suppressant tag (5 -> 10).
    out = server._combat_damage("Mind Eater", 5, "kinetic", attacker="Shielder")
    assert "ambiguous" not in out.lower()
    assert "10/20 HP" in out


def test_weapon_without_engine_tags_keeps_caller_tags(monkeypatch):
    """A resolved weapon with NO engine_tags key must not wipe caller-supplied
    weapon_tags — the manual psyche-suppressant tag survives and doubles."""
    weapon_no_tags = {
        "name": "Plain Saber",
        "type": "weapon",
        "damage": "1d8",
        "damage_type": "kinetic",
        "kinetic_subtype": "slashing",
        # NOTE: no "engine_tags" key at all
    }
    pc = {
        "name": "Saberist",
        "hp": {"current": 20, "max": 20},
        "wound_table": "biological",
        "inventory": {"carried": [weapon_no_tags]},
    }
    fixture = {"characters": {"Saberist": pc}}
    _make_combat_with_enemy(monkeypatch, fixture)

    out = server._combat_damage(
        "Mind Eater", 5, "kinetic",
        attacker="Saberist", weapon_tags=["psyche-suppressant"],
    )

    # Caller's manual tag survives (weapon defines no engine_tags): 5 -> 10
    assert "10/20 HP" in out
