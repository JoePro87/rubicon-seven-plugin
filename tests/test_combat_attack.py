"""Tests for combat(action='attack') — Task 11b.

Covers:
1. Non-Creenash PC (Roscar, psyche-suppressant railgun) vs Psychic enemy:
   engine auto-rolls, damage doubles via weapon tag.
2. Creenash, no auto_roll, no to_hit → returns gating message, HP unchanged.
3. Creenash, to_hit=18 + damage_roll=5, auto_roll unset → supplied numbers used.
4. Creenash, auto_roll=True → engine rolls (monkeypatched random), no supplied needed.
5. Miss: low d20 so total <= AV → no damage, miss result.
6. Crit: d20==20 → always hits, damage doubled.
7. Enemy attacker vs PC defender: auto-rolls (not Creenash), hits, PC takes damage.

Monkeypatch idioms follow test_combat_pc_damage.py + test_combat_init_profile.py.
"""
import server
import engine_core


# ---------------------------------------------------------------------------
# Shared weapon / character fixtures
# ---------------------------------------------------------------------------

_RAILGUN = {
    "name": "Blasphemous Psyche-Suppressant Nano-edged Railgun",
    "type": "exotica_weapon",
    "damage": "3d12",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": ["psyche-suppressant"],
}

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
    "type": "follower",  # a companion, not the player PC -> auto-rolls (Iron Law 3)
    "hp": {"current": 23, "max": 23},
    "wound_table": "biological",
    "abilities": {
        "STR": {"current": 1, "base": 1},
        "DEX": {"current": 2, "base": 2},
    },
    "inventory": {"carried": [_RAILGUN]},
}

_CREENASH = {
    "name": "Creenash",
    "player": True,  # the designated player PC -> Iron Law 3 (must supply own rolls)
    "hp": {"current": 19, "max": 23},
    "wound_table": "biological",
    "av": {"base": 16},
    "abilities": {
        "STR": {"current": 1, "base": 1},
        "DEX": {"current": 6, "base": 4},
    },
    "inventory": {"carried": [_TRISKELE]},
    "special_traits": {},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_psychic_enemy(hp=20, av=12):
    return {
        "hp": hp,
        "max_hp": hp,
        "av": av,
        "morale": 0,
        "lvl": 2,
        "defeated": False,
        "fled": False,
        "resist_type": "Psychic",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False,
        "attack_name": "Psychic Blast",
        "attack_damage": "d8, electrical",
        "attacks": [],
    }


def _make_biological_enemy(hp=15, av=12):
    return {
        "hp": hp,
        "max_hp": hp,
        "av": av,
        "morale": 0,
        "lvl": 2,
        "defeated": False,
        "fled": False,
        "resist_type": "Biological",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False,
        "attack_name": "Slash",
        "attack_damage": "d6",
        "attacks": [],
    }


def _base_isolate(monkeypatch, characters_fixture, enemies, party_pcs=None):
    """Inject minimal mocks for all combat-attack tests."""
    monkeypatch.setattr(server, "_load_characters", lambda: (characters_fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)

    snapshot = {name: {"hp": data["hp"]["current"], "max_hp": data["hp"]["max"]}
                for name, data in characters_fixture["characters"].items()}
    if party_pcs:
        snapshot.update(party_pcs)

    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {
            "enemies": dict(enemies),
            "party_snapshot": snapshot,
            "log": [],
        },
    )


# ---------------------------------------------------------------------------
# Test 1: Non-Creenash PC auto-rolls; psyche-suppressant doubles vs Psychic
# ---------------------------------------------------------------------------

def test_non_creenash_pc_auto_rolls_and_tag_doubles(monkeypatch):
    """Roscar attacks with the railgun (psyche-suppressant) vs a Psychic enemy.
    Engine auto-rolls (Roscar is not Creenash). The d20 is forced to 15
    (15 + DEX 2 = 17 > AV 12 -> hit). _roll_stat_expr is patched to return 5
    so damage = 5 → psyche-suppressant doubles to 10 → HP 20→10."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    enemy_hp = 20
    _base_isolate(monkeypatch, fixture, {"Mind Eater (psionic)": _make_psychic_enemy(hp=enemy_hp, av=12)})

    # Force d20=15 only (the to-hit roll); patch _roll_stat_expr for damage.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)

    out = server._combat_attack("Roscar", "Railgun", "Mind Eater (psionic)")

    # Must be a hit
    assert "HIT" in out
    # Must NOT be waiting for DM-supplied rolls
    assert "to_hit=" not in out
    # psyche-suppressant doubles 5 -> 10; HP 20-10=10
    assert "10/20 HP" in out

    # DM block must carry the TRUE post-resistance damage.
    block = _extract_dm_block(out)
    assert block["damage_sent"] == 5            # pre-resistance amount handed to the pipeline
    # psyche-suppressant doubling reflected in the authoritative field
    assert block["damage_dealt"] == 2 * block["damage_sent"]   # 10
    assert block["damage_dealt"] == block["target_max_hp"] - block["target_hp_after"]


# ---------------------------------------------------------------------------
# Test 2: Creenash, no auto_roll, no to_hit → gating message, HP unchanged
# ---------------------------------------------------------------------------

def test_creenash_no_auto_roll_no_to_hit_returns_gate_message(monkeypatch):
    """Engine refuses to roll for Creenash — returns a message asking for to_hit."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    out = server._combat_attack("Creenash", "Triskele", "Raider (scarred)")

    assert "to_hit" in out
    # HP must be untouched
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15


# ---------------------------------------------------------------------------
# Test 3: Creenash with to_hit=18, damage_roll=5 — supplied numbers used
# ---------------------------------------------------------------------------

def test_creenash_supplied_to_hit_and_damage_uses_those_numbers(monkeypatch):
    """Creenash with to_hit=18 and damage_roll=5.
    Triskele is ranged (type contains 'ranged'), DEX=6, total=24 > av=12 → hit.
    Engine should NOT call random.randint at all."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    # If engine calls random.randint it would raise to expose the error
    def _no_roll(a, b):
        raise AssertionError("Engine should not roll dice for Creenash when to_hit is supplied")
    monkeypatch.setattr(server.random, "randint", _no_roll)

    out = server._combat_attack("Creenash", "Triskele", "Raider (scarred)",
                                to_hit=18, damage_roll=5)

    assert "HIT" in out
    # 18 + DEX(6) = 24 should appear in the output
    assert "24" in out
    # Damage: 5 beam, no resistance for Biological -> HP 15-5=10
    assert "10/15 HP" in out


# ---------------------------------------------------------------------------
# Test 4: Creenash with auto_roll=True → engine rolls (no supplied needed)
# ---------------------------------------------------------------------------

def test_creenash_auto_roll_true_engine_rolls(monkeypatch):
    """auto_roll=True bypasses Iron Law 3 gate; engine calls random.randint for d20.
    _roll_stat_expr is patched to return 4 for the damage so we get a clean count."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    # d20 forced to 15 (15+6=21 > 12 → hit)
    roll_called = []

    def _mock_roll(a, b):
        roll_called.append((a, b))
        return 15

    monkeypatch.setattr(server.random, "randint", _mock_roll)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 4)

    out = server._combat_attack("Creenash", "Triskele", "Raider (scarred)", auto_roll=True)

    assert "HIT" in out
    # Engine must have called random.randint at least once (the d20 roll)
    assert len(roll_called) >= 1
    # HP should have dropped
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] < 15


# ---------------------------------------------------------------------------
# Test 5: Miss — low d20, total <= AV, no damage applied
# ---------------------------------------------------------------------------

def test_miss_no_damage(monkeypatch):
    """Force d20=2; 2 + DEX(2) = 4, which does not exceed AV 12 → MISS."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)

    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)")

    assert "MISS" in out
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15


# ---------------------------------------------------------------------------
# Test 6: Crit (d20 == 20) — always hits and damage is doubled
# ---------------------------------------------------------------------------

def test_crit_doubles_damage(monkeypatch):
    """Force d20=20 (crit): must hit regardless of AV, damage doubled.
    _roll_stat_expr patched to return 5 → doubled to 10 → HP 30-10=20."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    # High AV enemy that would not be hit by a non-crit
    enemy = _make_biological_enemy(hp=30, av=18)
    _base_isolate(monkeypatch, fixture, {"Hardened Sentinel": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)

    out = server._combat_attack("Roscar", "Railgun", "Hardened Sentinel")

    assert "CRIT" in out or "crit" in out.lower()
    # Doubled damage: 5*2=10 → HP 30-10=20
    assert "20/30 HP" in out


# ---------------------------------------------------------------------------
# Test 7: Enemy attacker vs PC defender — auto-rolls, uses attack_damage + lvl
# ---------------------------------------------------------------------------

def test_enemy_attacker_vs_pc_auto_rolls_and_hits_pc(monkeypatch):
    """An enemy attacks Creenash: engine auto-rolls (enemy is not Creenash).
    Enemy has lvl=3, av not relevant here (enemy is attacker).
    Creenash AV base=16. Force d20=14; 14+3=17 > 16 → hit.
    attack_damage='d8, electrical'; damage forced to 4; HP drops."""
    enemy_entry = _make_biological_enemy(hp=20, av=12)
    enemy_entry["lvl"] = 3
    enemy_entry["attack_damage"] = "d8, electrical"
    enemy_entry["attack_name"] = "Claw"

    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture,
                  {"Raider (scarred)": enemy_entry},
                  party_pcs={"Creenash": {"hp": 19, "max_hp": 23}})

    # d20=14 → total 17 > AV 16; damage=4
    rolls = iter([14, 4])
    monkeypatch.setattr(server.random, "randint", lambda a, b: next(rolls))

    # Patch _character_take_damage to record the call without touching real disk
    calls = []
    def _mock_take_damage(name, dmg, dtype):
        calls.append((name, dmg, dtype))
        return f"{name}: 19 -> {19 - dmg}/{23} HP (took {dmg} damage)"
    monkeypatch.setattr(server, "_character_take_damage", _mock_take_damage)

    out = server._combat_attack("Raider (scarred)", None, "Creenash")

    assert "HIT" in out
    # Damage type should be electrical (parsed from attack_damage string)
    assert calls, "Expected _character_take_damage to be called"
    name, dmg, dtype = calls[0]
    assert name == "Creenash"
    assert dmg == 4
    assert dtype == "electrical"


# ---------------------------------------------------------------------------
# Test 8: Fumble (d20 == 1) — always a miss, weapon drops/jams
# ---------------------------------------------------------------------------

def test_fumble_is_always_miss_and_no_damage(monkeypatch):
    """Force d20=1 (fumble): miss regardless of AV, weapon drops/jams."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    enemy = _make_biological_enemy(hp=15, av=8)  # Very low AV — but fumble always misses
    _base_isolate(monkeypatch, fixture, {"Weakling": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)

    out = server._combat_attack("Roscar", "Railgun", "Weakling")

    assert "FUMBLE" in out
    assert server.GAME_STATE["active_combat"]["enemies"]["Weakling"]["hp"] == 15


# ---------------------------------------------------------------------------
# Test 9: Creenash supplies to_hit but not damage_roll when hit — partial gate
# ---------------------------------------------------------------------------

def test_creenash_to_hit_supplied_but_no_damage_roll_asks_for_it(monkeypatch):
    """When Creenash supplies to_hit that would hit, but omits damage_roll,
    the engine asks for damage_roll before applying damage."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    # No random calls expected
    monkeypatch.setattr(server.random, "randint",
                        lambda a, b: (_ for _ in ()).throw(AssertionError("no roll expected")))

    out = server._combat_attack("Creenash", "Triskele", "Raider (scarred)", to_hit=18)

    # Should ask for damage_roll, not apply damage
    assert "damage_roll" in out
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15


# ---------------------------------------------------------------------------
# Test 10: No active combat → appropriate error
# ---------------------------------------------------------------------------

def test_no_active_combat_returns_error(monkeypatch):
    """_combat_attack with no active combat returns an error message."""
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._combat_attack("Roscar", "Railgun", "Someone")
    assert "No active combat" in out


# ---------------------------------------------------------------------------
# Test 11: Enemy multi-hit clause "d8 (2x)" — rolls base d8, surfaces a NOTE
# ---------------------------------------------------------------------------

def test_enemy_multihit_clause_rolls_base_and_notes(monkeypatch):
    """attack_damage='d8 (2x)' must roll the leading d8 (not silently deal 1) and
    append an adjudication NOTE about the unhandled multi-hit clause."""
    enemy_entry = _make_biological_enemy(hp=20, av=12)
    enemy_entry["lvl"] = 3
    enemy_entry["attack_damage"] = "d8 (2x)"
    enemy_entry["attack_name"] = "Alzabo Claw"

    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture,
                  {"Alzabo": enemy_entry},
                  party_pcs={"Creenash": {"hp": 19, "max_hp": 23}})

    # d20=14 → 14+3=17 > AV 16 → hit. Patch the d8 roll to 6.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 14)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 6)

    calls = []
    monkeypatch.setattr(server, "_character_take_damage",
                        lambda name, dmg, dtype: calls.append((name, dmg, dtype))
                        or f"{name}: 19 -> {19 - dmg} HP")

    out = server._combat_attack("Alzabo", None, "Creenash")

    assert "HIT" in out
    # The base d8 (6) was rolled — NOT silently 1.
    assert calls and calls[0][1] == 6, f"expected rolled 6, got {calls}"
    # The unhandled clause NOTE must be surfaced.
    assert "[NOTE:" in out
    assert "adjudicate" in out.lower()
    assert "multi-hit" in out.lower() or "conditional" in out.lower()


# ---------------------------------------------------------------------------
# Test 12: Enemy save-based attack "CON Save vs ..." — special NOTE, no crash
# ---------------------------------------------------------------------------

def test_enemy_save_based_attack_surfaces_special_note(monkeypatch):
    """attack_damage='CON Save vs Amaranthine Venom' has no dice expr — must not
    crash and must surface a 'special/save-based — adjudicate' NOTE."""
    enemy_entry = _make_biological_enemy(hp=20, av=12)
    enemy_entry["lvl"] = 3
    enemy_entry["attack_damage"] = "CON Save vs Amaranthine Venom"
    enemy_entry["attack_name"] = "Venom Sting"

    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture,
                  {"Venomous Thing": enemy_entry},
                  party_pcs={"Creenash": {"hp": 19, "max_hp": 23}})

    # d20=14 → 14+3=17 > AV 16 → hit.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 14)

    calls = []
    monkeypatch.setattr(server, "_character_take_damage",
                        lambda name, dmg, dtype: calls.append((name, dmg, dtype))
                        or f"{name}: 19 -> {19 - dmg} HP")

    out = server._combat_attack("Venomous Thing", None, "Creenash")

    assert "HIT" in out
    assert "[NOTE:" in out
    assert "special/save-based" in out.lower()
    assert "adjudicate" in out.lower()


# ---------------------------------------------------------------------------
# DM-ONLY result block helpers
# ---------------------------------------------------------------------------

import json as _json

_DM_OPEN  = "=== DM-ONLY COMBAT RESULT (classified — render as prose, never show the player) ==="
_DM_CLOSE = "=== END DM-ONLY COMBAT RESULT ==="


def _extract_dm_block(text: str) -> dict:
    """Parse the JSON payload from the DM-only result block in `text`."""
    start = text.index(_DM_OPEN) + len(_DM_OPEN)
    end   = text.index(_DM_CLOSE)
    return _json.loads(text[start:end].strip())


# ---------------------------------------------------------------------------
# Task 12 — Test 13: Non-Creenash PC hit → DM block present with correct keys
# ---------------------------------------------------------------------------

def test_dm_block_present_on_hit(monkeypatch):
    """Roscar hits a Biological enemy (d20=15, damage=7).
    Block must be present; parse it and assert hit=True, to_hit_total, damage_type,
    target_hp_after, and target_defeated."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    enemy_hp = 20
    _base_isolate(monkeypatch, fixture, {"Grunt (fodder)": _make_biological_enemy(hp=enemy_hp, av=12)})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)   # d20=15 → 15+DEX(2)=17 > 12
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 7)

    out = server._combat_attack("Roscar", "Railgun", "Grunt (fodder)")

    # Block must be present
    assert _DM_OPEN in out
    assert _DM_CLOSE in out

    block = _extract_dm_block(out)

    assert block["hit"] is True
    # to_hit_total: d20(15) + DEX(2) = 17
    assert block["to_hit_total"] == 17
    # Biological enemy: kinetic/piercing, no double tag for biological
    assert block["damage_type"] == "piercing"
    # HP: 20 - 7 = 13  (no resistance for biological against piercing)
    assert block["target_hp_after"] == enemy_hp - 7
    assert isinstance(block["target_defeated"], bool)
    # No resistance change: damage_dealt equals damage_sent (and the real HP delta).
    assert block["damage_sent"] == 7
    assert block["damage_dealt"] == 7
    assert block["damage_dealt"] == block["damage_sent"]
    assert block["damage_dealt"] == block["target_max_hp"] - block["target_hp_after"]


# ---------------------------------------------------------------------------
# Task 12 — Test 14: Miss → DM block present with hit=False, damage_sent=None
# ---------------------------------------------------------------------------

def test_dm_block_present_on_miss(monkeypatch):
    """Roscar misses (d20=2 → 2+2=4, does not exceed AV 12).
    Block must be present; hit=False, damage_sent=None, damage_dealt=None."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Grunt (fodder)": _make_biological_enemy(hp=15, av=12)})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)

    out = server._combat_attack("Roscar", "Railgun", "Grunt (fodder)")

    assert _DM_OPEN in out
    assert _DM_CLOSE in out
    assert "MISS" in out  # existing summary still present

    block = _extract_dm_block(out)

    assert block["hit"] is False
    assert block["damage_sent"] is None
    assert block["damage_dealt"] is None
    assert block["fumble"] is False


# ---------------------------------------------------------------------------
# Task 12 — Test 15: Crit → block has crit=True, damage_doubled=True,
#                    and damage_sent == 2 * damage_raw
# ---------------------------------------------------------------------------

def test_dm_block_on_crit_raw_vs_applied(monkeypatch):
    """Force d20=20 (crit). _roll_stat_expr returns 5.
    Block: crit=True, damage_doubled=True, damage_raw=5, damage_sent=10."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    enemy = _make_biological_enemy(hp=30, av=18)
    _base_isolate(monkeypatch, fixture, {"Hardened Sentinel": enemy})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)

    out = server._combat_attack("Roscar", "Railgun", "Hardened Sentinel")

    assert _DM_OPEN in out
    block = _extract_dm_block(out)

    assert block["crit"] is True
    assert block["damage_doubled"] is True
    assert block["damage_raw"] == 5
    assert block["damage_sent"] == 10
    assert block["damage_sent"] == 2 * block["damage_raw"]
    # Biological enemy, no resistance change: dealt equals sent.
    assert block["damage_dealt"] == block["damage_sent"]


# ---------------------------------------------------------------------------
# Task 12 — Test 16: Existing HIT summary line still present alongside block
# ---------------------------------------------------------------------------

def test_hit_summary_line_still_present_alongside_dm_block(monkeypatch):
    """The DM block is additive. The original HIT summary substring must still
    appear in the output alongside the new structured block."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Grunt (fodder)": _make_biological_enemy(hp=15, av=12)})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Roscar", "Railgun", "Grunt (fodder)")

    # Original summary line still present
    assert "HIT" in out
    assert "12/15 HP" in out  # 15 - 3 = 12 (no resistance)
    # Block is also present (additive, not replacement)
    assert _DM_OPEN in out


# ---------------------------------------------------------------------------
# Production-key regression tests — characters dict keyed LOWERCASE (filename
# stem reality). These tests MUST use lowercase keys to lock out the bugs.
# ---------------------------------------------------------------------------

_RAILGUN_PROD = {
    "name": "Blasphemous Psyche-Suppressant Nano-edged Railgun",
    "type": "exotica_weapon",
    "damage": "3d12",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": ["psyche-suppressant"],
}

_TRISKELE_PROD = {
    "name": "Triskele",
    "type": "exotica_weapon ranged",
    "damage": "3d8",
    "damage_type": "beam",
    "engine_tags": [],
    "primary": True,
}

# Production-style fixture: keys are LOWERCASE (filename stems), name field is
# the display name.  This mirrors what _load_characters() actually returns.
_PROD_FIXTURE = {
    "characters": {
        "roscar": {
            "name": "Brek + AUGUR",
            "type": "follower",  # companion -> auto-rolls
            "hp": {"current": 23, "max": 23},
            "wound_table": "biological",
            "abilities": {
                "STR": {"current": 1, "base": 1},
                "DEX": {"current": 3, "base": 3},
            },
            "inventory": {"carried": [_RAILGUN_PROD]},
        },
        "creenash": {
            "name": "Creenash",
            "player": True,  # the designated player PC -> Iron Law 3
            "hp": {"current": 19, "max": 23},
            "wound_table": "biological",
            "av": {"base": 16},
            "abilities": {
                "STR": {"current": 1, "base": 1},
                "DEX": {"current": 6, "base": 4},
            },
            "inventory": {"carried": [_TRISKELE_PROD]},
            "special_traits": {},
        },
    }
}


def _prod_isolate(monkeypatch, enemies, party_pcs=None):
    """Inject production-style (lowercase-keyed) fixtures."""
    _base_isolate(monkeypatch, _PROD_FIXTURE, enemies, party_pcs=party_pcs)


# ---------------------------------------------------------------------------
# Test 17: attacker resolves case-insensitively (capitalized input, lowercase key)
# ---------------------------------------------------------------------------

def test_attacker_resolves_case_insensitively(monkeypatch):
    """Calling _combat_attack('Roscar', ...) against a lowercase-keyed fixture
    must resolve, auto-roll, hit, and deal damage — NOT return 'not found'."""
    _prod_isolate(monkeypatch, {"Mind Eater (psionic)": _make_psychic_enemy(hp=20, av=12)})

    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)   # 15+DEX(3)=18 > AV 12
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)

    out = server._combat_attack("Roscar", "Railgun", "Mind Eater (psionic)")

    assert "HIT" in out, f"Expected HIT, got: {out[:300]}"
    assert "not found" not in out.lower()


# ---------------------------------------------------------------------------
# Test 18: Creenash gate fires for BOTH 'creenash' and 'Creenash' (Iron Law 3)
# ---------------------------------------------------------------------------

def test_creenash_gate_fires_on_lowercase_key(monkeypatch):
    """Iron Law 3 regression lock.

    With a lowercase-keyed fixture ('creenash'), the gate must fire for BOTH
    'creenash' and 'Creenash' input strings.  random.randint is patched to
    RAISE — proving the engine did NOT roll for Creenash in either case.
    """
    enemy = _make_biological_enemy(hp=15, av=12)
    _prod_isolate(monkeypatch, {"Raider (scarred)": enemy})

    def _must_not_roll(a, b):
        raise AssertionError(
            "Engine must NOT roll dice for Creenash without DM opt-in (Iron Law 3)"
        )

    monkeypatch.setattr(server.random, "randint", _must_not_roll)

    for input_name in ("creenash", "Creenash"):
        out = server._combat_attack(input_name, "Triskele", "Raider (scarred)")
        assert "to_hit" in out, (
            f"Gate message expected for input '{input_name}', got: {out[:300]}"
        )
        # HP must be untouched
        assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15, (
            f"HP was modified for input '{input_name}' — engine rolled or applied damage"
        )


# ---------------------------------------------------------------------------
# Test 19: Creenash auto_roll=True opt-in still works with lowercase key
# ---------------------------------------------------------------------------

def test_creenash_autoroll_optin_still_works(monkeypatch):
    """auto_roll=True with a lowercase-keyed fixture allows the engine to roll.
    random is allowed to be called; result must be HIT or MISS (not a gate msg)."""
    enemy = _make_biological_enemy(hp=15, av=12)
    _prod_isolate(monkeypatch, {"Raider (scarred)": enemy})

    roll_called = []

    def _mock_roll(a, b):
        roll_called.append((a, b))
        return 15  # 15+DEX(6)=21 > AV 12 → hit

    monkeypatch.setattr(server.random, "randint", _mock_roll)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 4)

    out = server._combat_attack("creenash", "Triskele", "Raider (scarred)", auto_roll=True)

    assert "HIT" in out, f"Expected HIT, got: {out[:300]}"
    assert len(roll_called) >= 1, "Engine should have called random.randint for the d20"


# ---------------------------------------------------------------------------
# Test 20: _resolve_attacker_weapon case-insensitive (capitalized input)
# ---------------------------------------------------------------------------

def test_resolve_attacker_weapon_case_insensitive(monkeypatch):
    """_resolve_attacker_weapon('Roscar', 'Railgun') against a lowercase-keyed
    fixture must return the weapon dict (not None, not an error string)."""
    monkeypatch.setattr(server, "_load_characters", lambda: (_PROD_FIXTURE, None))

    result = server._resolve_attacker_weapon("Roscar", "Railgun")

    assert result is not None, "_resolve_attacker_weapon returned None for a valid PC"
    assert not isinstance(result, str), (
        f"_resolve_attacker_weapon returned error string: {result}"
    )
    assert result.get("name") == _RAILGUN_PROD["name"]


# ---------------------------------------------------------------------------
# Test 21: PC target resolves case-insensitively (enemy attacker vs 'Roscar')
# ---------------------------------------------------------------------------

def test_pc_target_resolves_case_insensitively(monkeypatch):
    """An enemy attacks a PC defender passed as capitalized 'Roscar' while
    party_snapshot is keyed lowercase 'roscar'.  Must resolve and call
    _character_take_damage (PC path), not return 'target not found'."""
    enemy_entry = _make_biological_enemy(hp=20, av=12)
    enemy_entry["lvl"] = 2
    enemy_entry["attack_damage"] = "d6"
    enemy_entry["attack_name"] = "Slash"

    # party_snapshot keyed lowercase (production reality)
    _prod_isolate(
        monkeypatch,
        {"Raider (scarred)": enemy_entry},
        party_pcs={"roscar": {"hp": 23, "max_hp": 23}},
    )

    # d20=15 → 15+lvl(2)=17 > AV 10 (default for PC without av field in snapshot)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)

    calls = []

    def _mock_take_damage(name, dmg, dtype):
        calls.append((name, dmg, dtype))
        return f"{name}: 23 -> {23 - dmg}/{23} HP (took {dmg} damage)"

    monkeypatch.setattr(server, "_character_take_damage", _mock_take_damage)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 4)

    out = server._combat_attack("Raider (scarred)", None, "Roscar")

    assert "target not found" not in out.lower(), f"Target not resolved: {out[:300]}"
    assert "HIT" in out, f"Expected HIT, got: {out[:300]}"
    # _character_take_damage must have been called (PC damage path)
    assert calls, "Expected _character_take_damage to be called for PC defender"


# ---------------------------------------------------------------------------
# Thrown melee weapons (HOUSE RULE — "our Vaarn"): a thrown attack is a ranged
# attack, so it uses DEX even though the weapon is a melee weapon. RAW has no
# thrown mechanic (stat keys off weapon type); this is a deliberate homebrew.
# ---------------------------------------------------------------------------

_LETTER_OPENER = {
    "name": "Extradimensional Letter Opener",
    "type": "exotica_weapon",
    "damage": "d4",
    "damage_type": "kinetic",
    "kinetic_subtype": "piercing",
    "engine_tags": [],
    "range": "melee",
}

_CREENASH_MELEE = {
    "name": "Creenash",
    "hp": {"current": 19, "max": 23},
    "wound_table": "biological",
    "av": {"base": 16},
    "abilities": {"STR": {"current": 1, "base": 1}, "DEX": {"current": 6, "base": 4}},
    "inventory": {"carried": [_LETTER_OPENER]},
    "special_traits": {},
}


def test_melee_weapon_uses_str_by_default(monkeypatch):
    """A melee weapon (Letter Opener) used normally adds STR (+1)."""
    fixture = {"characters": {"Creenash": _CREENASH_MELEE}}
    _base_isolate(monkeypatch, fixture, {"Kronophage": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Letter Opener", "Kronophage",
                                to_hit=10, damage_roll=3)
    assert "d20=10 + 1 =" in out, out[:200]   # STR +1


def test_thrown_melee_weapon_uses_dex(monkeypatch):
    """House rule: thrown=True makes the melee weapon a ranged attack → DEX (+6)."""
    fixture = {"characters": {"Creenash": _CREENASH_MELEE}}
    _base_isolate(monkeypatch, fixture, {"Kronophage": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Letter Opener", "Kronophage",
                                to_hit=10, damage_roll=3, thrown=True)
    assert "d20=10 + 6 =" in out, out[:200]   # DEX +6 (thrown = ranged attack)


def test_thrown_is_noop_for_ranged_weapon(monkeypatch):
    """Throwing a weapon never downgrades the stat — a ranged weapon stays DEX."""
    fixture = {"characters": {"Creenash": _CREENASH}}  # Triskele (ranged)
    _base_isolate(monkeypatch, fixture, {"Kronophage": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Triskele", "Kronophage",
                                to_hit=10, damage_roll=3, thrown=True)
    assert "d20=10 + 6 =" in out, out[:200]   # DEX +6 either way


# ---------------------------------------------------------------------------
# A3: morale_broken in the DM result block is PER-ATTACK (did THIS attack break
# morale?), not the persistent combat-wide carryover flag.
# ---------------------------------------------------------------------------

def test_morale_broken_false_when_not_triggered(monkeypatch):
    """A hit that doesn't break morale reports morale_broken=false."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture, {"Shade": _make_biological_enemy(av=12)})
    out = server._combat_attack("Creenash", "Triskele", "Shade", to_hit=18, damage_roll=5)
    assert "HIT" in out
    assert '"morale_broken": false' in out


def test_attack_that_breaks_morale_reports_true(monkeypatch):
    """When THIS attack breaks morale, the block reports morale_broken=true."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture, {"Shade": _make_biological_enemy(av=12)})

    def _break_morale():
        server.GAME_STATE["active_combat"]["morale_broken"] = True
        return ""
    monkeypatch.setattr(server, "_check_morale_triggers", _break_morale)

    out = server._combat_attack("Creenash", "Triskele", "Shade", to_hit=18, damage_roll=5)
    assert "HIT" in out
    assert '"morale_broken": true' in out


def test_already_broken_morale_not_reattributed(monkeypatch):
    """Morale broken on a PRIOR attack must not be re-reported by this one."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture, {"Shade": _make_biological_enemy(av=12)})
    server.GAME_STATE["active_combat"]["morale_broken"] = True  # already broken before
    out = server._combat_attack("Creenash", "Triskele", "Shade", to_hit=18, damage_roll=5)
    assert "HIT" in out
    assert '"morale_broken": false' in out


def test_fumble_does_not_report_morale_break(monkeypatch):
    """A fumble deals no damage, so it never reports a morale break — even if
    morale was already broken combat-wide."""
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture, {"Shade": _make_biological_enemy(av=12)})
    server.GAME_STATE["active_combat"]["morale_broken"] = True
    out = server._combat_attack("Creenash", "Triskele", "Shade", to_hit=1)  # nat-1 fumble
    assert "FUMBLE" in out
    assert '"morale_broken": false' in out


# ---------------------------------------------------------------------------
# Bug 6 (macOS playtest 1): an enemy keyed with a position descriptor resolves
# from the DM's bare base name, when unambiguous. The DM's natural name
# ("Moonbeast Nymph") must hit "Moonbeast Nymph (left flank)" on the first try.
# ---------------------------------------------------------------------------

def test_enemy_attacker_bare_name_resolves_position_descriptor(monkeypatch):
    """attacker='Moonbeast Nymph' resolves to the keyed 'Moonbeast Nymph
    (left flank)' and that enemy's profile is used."""
    enemy = _make_biological_enemy(hp=20, av=12)
    enemy["lvl"] = 3
    enemy["attack_damage"] = "d8, electrical"
    enemy["attack_name"] = "Claw"
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture,
                  {"Moonbeast Nymph (left flank)": enemy},
                  party_pcs={"Creenash": {"hp": 19, "max_hp": 23}})
    rolls = iter([14, 4])
    monkeypatch.setattr(server.random, "randint", lambda a, b: next(rolls))
    monkeypatch.setattr(server, "_character_take_damage",
                        lambda name, dmg, dtype: f"{name} took {dmg}")

    out = server._combat_attack("Moonbeast Nymph", None, "Creenash")
    # Resolved (no "not found"), used the descriptor-keyed enemy's Claw profile.
    assert "not found in party or combat enemies" not in out
    assert "Claw" in out


def test_enemy_attacker_bare_name_ambiguous_is_not_resolved(monkeypatch):
    """Two enemies share a base name → the bare name must NOT silently resolve
    to one of them (no wrong-target attack)."""
    e1 = _make_biological_enemy(hp=20, av=12); e1["attack_name"] = "Claw"
    e2 = _make_biological_enemy(hp=20, av=12); e2["attack_name"] = "Claw"
    fixture = {"characters": {"Creenash": _CREENASH}}
    _base_isolate(monkeypatch, fixture,
                  {"Moonbeast Nymph (left flank)": e1,
                   "Moonbeast Nymph (right flank)": e2},
                  party_pcs={"Creenash": {"hp": 19, "max_hp": 23}})
    out = server._combat_attack("Moonbeast Nymph", None, "Creenash")
    assert "not found in party or combat enemies" in out


# ---------------------------------------------------------------------------
# Bugs 9 & 10 (macOS playtest 1): route a NON-Creenash PC's own physical roll
# through the engine. The engine adds the ability bonus and surfaces the gambit,
# so the DM never hand-resolves (dropping a DEX modifier or missing a gambit).
# ---------------------------------------------------------------------------

def test_non_creenash_pc_supplied_roll_adds_ability_bonus(monkeypatch):
    """Roscar (DEX +2) supplies his own d20=17 AND damage. The engine must USE 17
    and ADD DEX (17+2=19), not auto-roll and not drop the modifier."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy(hp=15, av=12)})
    # If the engine wrongly auto-rolled, this would force a different d20.
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)

    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)",
                                to_hit=17, damage_roll=5)
    block = _extract_dm_block(out)
    assert block["to_hit_d20"] == 17          # the player's roll was honored
    assert block["to_hit_bonus"] == 2         # DEX +2 added by the engine
    assert block["to_hit_total"] == 19        # NOT 17 (the dropped-modifier bug)
    assert "HIT" in out


def test_non_creenash_pc_supplied_roll_resolves_in_one_call(monkeypatch):
    """to_hit + damage_roll together resolve in a single call (no second
    round-trip asking for damage)."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy(hp=15, av=12)})
    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)",
                                to_hit=17, damage_roll=5)
    assert "pass `damage_roll" not in out      # not waiting on a second call
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] < 15


def test_non_creenash_pc_supplied_roll_surfaces_gambit(monkeypatch):
    """A supplied roll whose TOTAL exceeds 20 surfaces the gambit menu — the
    missed-gambit fumble can't happen when routed through the engine."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy(hp=30, av=12)})
    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)",
                                to_hit=19, damage_roll=5)  # 19 + DEX 2 = 21 > 20
    block = _extract_dm_block(out)
    assert block["gambit_available"] is True
    assert "GAMBIT AVAILABLE" in out


def test_non_creenash_pc_supplied_to_hit_without_damage_asks_for_it(monkeypatch):
    """Supplying only to_hit confirms the hit and asks for damage_roll (the
    player's dice), leaving HP unchanged until it arrives."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy(hp=15, av=12)})
    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)", to_hit=17)
    assert "damage_roll" in out
    assert server.GAME_STATE["active_combat"]["enemies"]["Raider (scarred)"]["hp"] == 15


def test_non_creenash_pc_omitting_to_hit_still_auto_rolls(monkeypatch):
    """Regression: with no to_hit, a non-Creenash PC still auto-rolls everything
    (the default path is unchanged)."""
    fixture = {"characters": {"Roscar": _ROSCAR}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy(hp=15, av=12)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)
    out = server._combat_attack("Roscar", "Railgun", "Raider (scarred)")
    assert "pass `damage_roll" not in out
    assert "to_hit=" not in out
    assert "HIT" in out
