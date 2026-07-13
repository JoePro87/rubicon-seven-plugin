"""End-to-end seam test: combat init -> resolved resistance/incorporeal profile
stored on the enemy dict -> _combat_damage honours it.

Born from the 2026-06-07 parity audit finding [HIGH]: the two halves of the
resistance engine (_resolve_resistance_profile / _apply_creature_resistance) and
the combat init wiring (_combat_init) are unit-tested separately but never
together. An init regression that dropped `incorporeal=True` or the resolved
`resistances` profile from the stored enemy dict would let a ghost take
conventional damage with no failing test. This test exercises the FULL seam:

    init combat (real _combat_init reading the bestiary cache)
        -> assert the stored enemy dict carries the resolved profile + flag
        -> feed it through _combat_damage
        -> confirm conventional damage is zeroed for incorporeal
           and that double/half resistances apply.

To stay deterministic and independent of which named creatures survive future
content edits, we inject controlled fixture entries straight into the bestiary
cache that _combat_init reads (server.rulebook_system._cache["bestiary"], via
_get_bestiary_entry). The CODE PATH under test is the real one end to end.
"""

import pytest

import server


# Fixture creatures injected into the bestiary cache that _combat_init reads.
# - An incorporeal Outsider (the ghost case).
# - A Mineral creature whose type default doubles bludgeoning (double via matrix).
# - A creature with an EXPLICIT per-creature profile that both doubles fire and
#   halves kinetic, so we assert double AND half deterministically in one block.
_FIXTURE_BESTIARY = [
    {
        "id": "creature-test-wraith",
        "keywords": ["test wraith"],
        "stats": {
            "level": 3,
            "hp": 12,
            "av": 13,
            "morale": 1,
            "type": "Outsider",
            "incorporeal": True,
        },
    },
    {
        "id": "creature-test-golem",
        "keywords": ["test golem"],
        "stats": {
            "level": 4,
            "hp": 20,
            "av": 15,
            "morale": 2,
            "type": "Mineral",  # matrix default: double bludgeoning
        },
    },
    {
        "id": "creature-test-salamander",
        "keywords": ["test salamander"],
        "stats": {
            "level": 3,
            "hp": 16,
            "av": 12,
            "morale": 0,
            "type": "Biological",
            # Explicit per-creature override: double fire, half kinetic.
            "resistances": {
                "immune": [],
                "double": ["fire"],
                "half": ["kinetic"],
                "minimum": [],
                "varies": False,
            },
        },
    },
]


@pytest.fixture(autouse=True)
def _install_fixture_bestiary(monkeypatch):
    """Point the bestiary cache that _combat_init reads at our fixtures, give it a
    minimal party (the temp test campaign dir has no characters.json), keep state
    in-memory, and guarantee no stale combat leaks between tests. The combat code
    path under test stays the real one end to end."""
    cache = server.rulebook_system._cache
    saved_bestiary = cache.get("bestiary")
    cache["bestiary"] = _FIXTURE_BESTIARY

    # _combat_init builds a party snapshot from _load_characters(); the isolated
    # test campaign dir has none, so supply a minimal one.
    party = {"characters": {"Creenash": {"hp": {"current": 19, "max": 23}}}}
    monkeypatch.setattr(server, "_load_characters", lambda: (party, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)

    server.GAME_STATE["active_combat"] = None
    try:
        yield
    finally:
        cache["bestiary"] = saved_bestiary
        server.GAME_STATE["active_combat"] = None


def _enemy(combat, prefix):
    """Return the single stored enemy dict whose key starts with `prefix`."""
    matches = [v for k, v in combat["enemies"].items() if k.lower().startswith(prefix.lower())]
    assert len(matches) == 1, f"expected one '{prefix}' enemy, got {list(combat['enemies'])}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. Init wiring: the resolved profile + incorporeal flag land on the enemy dict
# ---------------------------------------------------------------------------

def test_init_stores_incorporeal_flag_and_outsider_profile():
    out = server._combat_init(["test wraith", "test golem"], encounter_name="seam_test")
    assert "Combat initialized" in out

    combat = server.GAME_STATE["active_combat"]
    assert combat is not None

    wraith = _enemy(combat, "test wraith")
    # The incorporeal flag survived init and is on the stored dict.
    assert wraith["incorporeal"] is True
    # The resistance TYPE was captured...
    assert wraith["resist_type"] == "Outsider"
    # ...and a resolved profile object is present (Outsider = varies).
    assert isinstance(wraith["resistances"], dict)
    assert wraith["resistances"].get("varies") is True

    golem = _enemy(combat, "test golem")
    assert golem["incorporeal"] is False
    assert golem["resist_type"] == "Mineral"
    # Mineral type default doubles bludgeoning -- resolved at init, not at damage.
    assert "bludgeoning" in golem["resistances"]["double"]


# ---------------------------------------------------------------------------
# 2. The stored profile actually drives _combat_damage (the seam closes)
# ---------------------------------------------------------------------------

def test_incorporeal_zeroes_conventional_damage_through_combat_damage():
    server._combat_init(["test wraith"], encounter_name="seam_ghost")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))
    start_hp = combat["enemies"][key]["hp"]

    # Conventional (kinetic) damage must be zeroed for an incorporeal creature.
    server._combat_damage(key, 8, "kinetic")
    assert combat["enemies"][key]["hp"] == start_hp, "incorporeal took conventional damage"


def test_incorporeal_pierced_by_hypergeometric_through_combat_damage():
    server._combat_init(["test wraith"], encounter_name="seam_ghost2")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))
    start_hp = combat["enemies"][key]["hp"]

    # Hypergeometric damage bypasses incorporeal immunity -> full damage lands.
    server._combat_damage(key, 5, "hypergeometric")
    assert combat["enemies"][key]["hp"] == start_hp - 5


def test_incorporeal_pierced_by_anti_paradoxical_weapon_tag():
    server._combat_init(["test wraith"], encounter_name="seam_ghost3")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))
    start_hp = combat["enemies"][key]["hp"]

    # Anti-paradoxical weapon tag bypasses incorporeal on a conventional type.
    server._combat_damage(key, 6, "kinetic", weapon_tags=["anti-paradoxical"])
    assert combat["enemies"][key]["hp"] < start_hp


def test_type_default_double_applies_through_combat_damage():
    server._combat_init(["test golem"], encounter_name="seam_golem")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))
    start_hp = combat["enemies"][key]["hp"]

    # Mineral doubles bludgeoning: 5 -> 10 off the stored profile.
    server._combat_damage(key, 5, "bludgeoning")
    assert combat["enemies"][key]["hp"] == start_hp - 10


def test_explicit_double_and_half_apply_through_combat_damage():
    server._combat_init(["test salamander"], encounter_name="seam_sala")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))

    # Explicit per-creature profile: double fire, half kinetic.
    start_hp = combat["enemies"][key]["hp"]
    server._combat_damage(key, 4, "fire")          # x2 -> 8
    assert combat["enemies"][key]["hp"] == start_hp - 8

    mid_hp = combat["enemies"][key]["hp"]
    server._combat_damage(key, 6, "kinetic")       # /2 -> 3
    assert combat["enemies"][key]["hp"] == mid_hp - 3


def test_non_resisted_type_lands_normally_on_resistant_creature():
    """A damage type the creature neither doubles nor halves passes through 1:1,
    proving the stored profile is consulted (not blanket-applied)."""
    server._combat_init(["test salamander"], encounter_name="seam_sala2")
    combat = server.GAME_STATE["active_combat"]
    key = next(iter(combat["enemies"]))
    start_hp = combat["enemies"][key]["hp"]

    server._combat_damage(key, 5, "poison")        # neither double nor half -> 5
    assert combat["enemies"][key]["hp"] == start_hp - 5


# ---------------------------------------------------------------------------
# Task 11a: enemy attack data at init + _defender_av helper
# ---------------------------------------------------------------------------

# Fixture entry for attack-data tests: a Biological creature with one named attack.
_ADVOCATE_ENTRY = {
    "id": "creature-test-advocate",
    "keywords": ["advocate"],
    "stats": {
        "level": 3,
        "hp": 12,
        "av": 14,
        "morale": 1,
        "type": "Biological",
        "attacks": [{"name": "Shock Baton", "damage": "d8, electrical"}],
    },
}

# Fixture entry for the no-attacks fallback test.
_EMPTY_ATTACKS_ENTRY = {
    "id": "creature-test-noattack",
    "keywords": ["no attack thing"],
    "stats": {
        "level": 2,
        "hp": 8,
        "av": 11,
        "morale": 0,
        "type": "Biological",
        "attacks": [],
    },
}


@pytest.fixture
def _attack_bestiary(monkeypatch):
    """Extend the fixture bestiary (already installed by autouse fixture) with the
    attack-data fixtures.  Also ensures clean combat state before each test."""
    cache = server.rulebook_system._cache
    saved = cache.get("bestiary", [])
    cache["bestiary"] = saved + [_ADVOCATE_ENTRY, _EMPTY_ATTACKS_ENTRY]
    server.GAME_STATE["active_combat"] = None
    yield
    cache["bestiary"] = saved
    server.GAME_STATE["active_combat"] = None


def test_enemy_init_stores_attack_data(_attack_bestiary):
    """_combat_init stores attack_damage, attack_name, and lvl for an enemy that has
    attacks in its bestiary entry."""
    out = server._combat_init(["Advocate"], encounter_name="attack_data_test")
    assert "Combat initialized" in out

    combat = server.GAME_STATE["active_combat"]
    enemy = _enemy(combat, "advocate")

    assert enemy["attack_damage"] == "d8, electrical"
    assert enemy["attack_name"] == "Shock Baton"
    assert enemy["lvl"] == 3


def test_enemy_init_defaults_attack_when_none(_attack_bestiary):
    """When a bestiary entry has an empty attacks list, the stored dict falls back to
    attack_damage='d4' and attack_name='Unarmed' (book default for improvised)."""
    out = server._combat_init(["no attack thing"], encounter_name="no_attack_test")
    assert "Combat initialized" in out

    combat = server.GAME_STATE["active_combat"]
    enemy = _enemy(combat, "no attack")

    assert enemy["attack_damage"] == "d4"
    assert enemy["attack_name"] == "Unarmed"


def test_defender_av_reads_enemy_av(monkeypatch):
    """_defender_av returns the integer AV stored on the enemy dict when the target
    is an active combat enemy."""
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    # Inject a minimal active_combat with one enemy.
    server.GAME_STATE["active_combat"] = {
        "enemies": {
            "Iron Shepherd (Alpha)": {
                "hp": 20, "max_hp": 20, "av": 16, "morale": 0,
                "defeated": False, "fled": False,
            }
        },
        "party_snapshot": {},
        "log": [],
    }
    try:
        result = server._defender_av("Iron Shepherd (Alpha)")
        assert result == 16
    finally:
        server.GAME_STATE["active_combat"] = None


# ---------------------------------------------------------------------------
# XS fix wave: unmatched-creature warning is LOUD (in tool output, not log-only)
# ---------------------------------------------------------------------------

def test_init_unmatched_creature_shows_warning_in_output():
    """A combatant name with no bestiary match still initializes combat with
    generic Lv1/4HP/AV12 stats, but the tool OUTPUT now carries a visible
    warning (previously this was log-only, per the fix wave brief)."""
    out = server._combat_init(["Totally Unregistered Creature XYZ"], encounter_name="unmatched_test")
    assert "Combat initialized" in out
    assert "NO BESTIARY MATCH" in out
    assert "Totally Unregistered Creature XYZ" in out

    combat = server.GAME_STATE["active_combat"]
    enemy = _enemy(combat, "totally unregistered creature xyz")
    # Fight still initializes with the generic fallback stats.
    assert enemy["hp"] == 4 and enemy["av"] == 12 and enemy["lvl"] == 1


def test_init_known_creature_shows_no_warning():
    """A combatant that DOES match the bestiary produces no warning line."""
    out = server._combat_init(["test wraith"], encounter_name="matched_test")
    assert "Combat initialized" in out
    assert "NO BESTIARY MATCH" not in out


def test_defender_av_reads_pc_base_no_double_count(monkeypatch):
    """_defender_av returns av['base'] for a PC whose armour is already folded into
    the base — it does NOT re-add a carried armour's av_bonus (no double-count)."""
    pc_sheet = {
        "name": "TestDefender",
        "hp": {"current": 20, "max": 20},
        "av": {"base": 15, "source": "Brigandine(13)+Shield(2)"},
        # A carried armour item with av_bonus that must NOT be double-counted.
        "inventory": {
            "carried": [
                {"name": "Brigandine", "type": "armour", "av_bonus": 3}
            ]
        },
    }
    fixture = {"characters": {"TestDefender": pc_sheet}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    # No active combat — target should resolve as a PC.
    server.GAME_STATE["active_combat"] = None

    result = server._defender_av("TestDefender")
    # Must be 15 (av.base), NOT 18 (which would double-count the carried armour).
    assert result == 15, f"Expected 15 (av.base only), got {result}"
