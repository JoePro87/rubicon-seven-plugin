"""Task 9: TDD tests for usage-die decision-point push formatting.

Tests verify:
1. _usage_deplete_roll: Expended -> pushes reload (+ feed only when Fungal)
2. _usage_deplete_roll: step-down (not Expended) -> NO push
3. _usage_deplete_roll: no step-down -> NO push
4. _combat_attack OUT-OF-AMMO: uses formatter, no single-quoted apostrophe bug
5. _usage_feed: die changed -> pushes status; die unchanged -> no push
6. _combat_end: expended weapon flows through _usage_deplete_roll, shows push
7. Apostrophe in weapon name renders inside double quotes in the push
"""
import server
import engine_core


# ---------------------------------------------------------------------------
# Shared fixture helper — mirrors _mk_pc_weapon from test_usage_die.py
# ---------------------------------------------------------------------------

def _mk_pc_weapon(monkeypatch, **weapon_fields):
    """Stage one PC carrying one ranged weapon; patch the loaders."""
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6", **weapon_fields}
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": [{"name": "Railgun", "damage": "3d12", "ammo": "Ud6"}]}
    data = {"meta": {}, "characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    saved = {}
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: saved.update({k: c}))
    return char, saved


# ---------------------------------------------------------------------------
# Test 1a: FUNGAL Ud4 rolls 1 -> Expended -> NEXT block with reload + feed
# ---------------------------------------------------------------------------

def test_deplete_to_expended_pushes_reload_and_feed(monkeypatch):
    """Force a FUNGAL Ud4 to roll 1 -> steps to Expended.
    Output must contain 'Expended', double-quoted usage(action="reload") and
    usage(action="feed") with the correct character and weapon names.
    Must NOT contain single-quoted action='reload' (the old apostrophe-bug form).
    """
    _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud4",
                  tags=["Fungal (regains a step when fed)"])
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 1)

    assert "Expended" in out
    assert 'usage(action="reload"' in out
    assert 'usage(action="feed"' in out
    assert 'character="Roscar"' in out
    assert 'weapon="Railgun"' in out
    assert "action='reload'" not in out   # no single-quoted form
    assert "NEXT" in out


# ---------------------------------------------------------------------------
# Test 1b: NON-Fungal Expended -> reload push only, NO feed (feeding a
# non-Fungal weapon is an error — never push a call the engine will bounce)
# ---------------------------------------------------------------------------

def test_deplete_to_expended_non_fungal_no_feed_push(monkeypatch):
    """A non-Fungal Ud4 depletes to Expended: the NEXT block pushes reload
    but must NOT push feed."""
    _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud4")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 1)

    assert "Expended" in out
    assert "NEXT" in out
    assert 'usage(action="reload"' in out
    assert 'action="feed"' not in out


# ---------------------------------------------------------------------------
# Test 2: Ud8 rolls 1 -> steps to Ud6 -> NO push (only Expended triggers push)
# ---------------------------------------------------------------------------

def test_deplete_stepdown_no_push(monkeypatch):
    """Ud8 rolls 1 -> steps to Ud6 (not Expended) -> no NEXT block."""
    _mk_pc_weapon(monkeypatch, ammo="Ud8", ammo_max="Ud8")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 1)

    assert "depletes" in out
    assert "Ud6" in out
    assert "NEXT" not in out


# ---------------------------------------------------------------------------
# Test 3: No step-down (roll >= 3) -> no push
# ---------------------------------------------------------------------------

def test_deplete_no_depletion_no_push(monkeypatch):
    """Roll of 5 -> no step-down, no NEXT."""
    _mk_pc_weapon(monkeypatch, ammo="Ud8", ammo_max="Ud8")
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 5)

    assert "NEXT" not in out


# ---------------------------------------------------------------------------
# Test 4: OUT-OF-AMMO block in _combat_attack uses formatter
# ---------------------------------------------------------------------------

def _combat_setup(monkeypatch, weapon):
    """Minimal combat setup for out-of-ammo test."""
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
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
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


def test_out_of_ammo_block_uses_formatter(monkeypatch):
    """_combat_attack with Expended ranged weapon returns OUT OF AMMO message
    using push_format double-quoted calls, NOT single-quoted action='reload'.
    """
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
              "range": "ranged", "ammo": "Expended", "ammo_max": "Ud6",
              "damage_type": "kinetic", "ammo_note": "scavenged cells only"}
    desc, char = _combat_setup(monkeypatch, weapon)
    out = server._combat_attack("roscar", "Railgun", desc, to_hit=20)

    assert "OUT OF AMMO" in out
    assert 'usage(action="reload"' in out
    assert 'character="Roscar"' in out
    assert 'weapon="Railgun"' in out
    assert "action='reload'" not in out   # no single-quoted form
    # Non-Fungal weapon: feed would bounce, must not be pushed
    assert 'action="feed"' not in out
    # ammo_note surfaces as its own Note clause
    assert "Note: scavenged cells only." in out
    # Sentence break between the NEXT block and what follows it
    assert 'weapon="Railgun"). Note: scavenged cells only. Carried ammo: none.' in out


# ---------------------------------------------------------------------------
# Test 5a: _usage_feed SUCCESS -> pushes status
# ---------------------------------------------------------------------------

def test_feed_success_pushes_status(monkeypatch):
    """Fungal weapon at Ud4 (below max Ud8) -> feed succeeds, die changes ->
    output appends a usage(action="status") NEXT push."""
    _mk_pc_weapon(monkeypatch, ammo="Ud4", ammo_max="Ud8",
                  tags=["Fungal (regains a step when fed)"])
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_feed(h)

    # Feed succeeded (die changed Ud4 -> Ud6)
    assert "Ud6" in out
    assert 'usage(action="status"' in out
    assert "NEXT" in out


# ---------------------------------------------------------------------------
# Test 5b: _usage_feed already-at-max -> NO push
# ---------------------------------------------------------------------------

def test_feed_at_max_no_push(monkeypatch):
    """Fungal weapon already at max -> feed returns 'already at max' message,
    die did not change -> no NEXT push."""
    _mk_pc_weapon(monkeypatch, ammo="Ud8", ammo_max="Ud8",
                  tags=["Fungal (regains a step when fed)"])
    h = server._usage_resolve("roscar", "Railgun")
    out = server._usage_feed(h)

    assert "already at max" in out
    assert "NEXT" not in out


# ---------------------------------------------------------------------------
# Test 6: _combat_end -> expended weapon shows reload/feed push in output
# ---------------------------------------------------------------------------

def test_combat_end_inherits_push(monkeypatch, tmp_path):
    """A FUNGAL weapon that depletes to Expended during combat-end roll-once
    should show the reload/feed NEXT push in the combat-end output string."""
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [
                {"name": "Railgun", "type": "ranged_weapon", "damage": "3d12",
                 "range": "ranged", "ammo": "Ud4", "ammo_max": "Ud4",
                 "tags": ["Fungal (regains a step when fed)"]}]},
            "attacks": []}
    monkeypatch.setattr(server, "_load_characters",
                        lambda: ({"characters": {"roscar": char}}, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: None)
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # force Expended
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "encounter_name": "Test Skirmish", "round": 2, "started_at": "now",
        "enemies": {"Brute (a)": {"hp": 0, "max_hp": 10, "defeated": True, "fled": False}},
        "party_snapshot": {"roscar": {"hp": 23}},
        "weapons_fired": [{"character": "roscar", "weapon": "Railgun"}],
        "log": [],
    })
    out = server._combat_end()

    # Die should have gone Ud4 -> Expended
    assert char["inventory"]["carried"][0]["ammo"] == "Expended"
    # Combat-end output should surface the reload/feed push
    assert 'usage(action="reload"' in out
    assert 'usage(action="feed"' in out


# ---------------------------------------------------------------------------
# Test 7: Apostrophe in weapon name -> renders inside double quotes (no bug)
# ---------------------------------------------------------------------------

def test_apostrophe_weapon_name_renders_in_double_quotes(monkeypatch):
    """A weapon named with an apostrophe (Kronophage's Echo) in the Expended
    push must be wrapped in double quotes, not break the call syntax."""
    weapon = {"name": "Kronophage's Echo", "type": "ranged_weapon", "damage": "d10",
              "range": "ranged", "ammo": "Ud4", "ammo_max": "Ud4"}
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": []}
    data = {"meta": {}, "characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: None)
    h = server._usage_resolve("roscar", "Kronophage's Echo")
    out = server._usage_deplete_roll(h, rng=lambda a, b: 1)

    assert "Expended" in out
    # The apostrophe weapon name should appear inside double quotes
    assert 'weapon="Kronophage\'s Echo"' in out
    # No single-quote form that would break the call
    assert "action='reload'" not in out
