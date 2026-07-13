"""Broken-item guard at use/attack time — Wounds Task 7.

The Damaged Item wound (Task 3) sets `broken: true` on a carried item. The
flag is ITEM-level — independent of the wound, persisting after the wound
heals. Repair (clearing it) is out of scope: a DM-fiat seam.

Covers:
1. usage(action='use') on a broken item -> blocked: no usage-die roll, no
   uses decrement, no removal; message says unusable until fixed + repair seam.
2. _combat_attack with a broken weapon -> BLOCKED naming the item; no dice,
   no damage, no weapons_fired record.
3. _combat_damage attacker-weapon auto-read with a broken weapon -> BLOCKED
   (the action='damage' path is independently callable, so the broken
   weapon's damage profile must not silently apply).
4. Controls: non-broken paths unchanged.
5. Persistence e2e: heal the originating Damaged Item wound via
   _wound_dispatch -> item still broken, use still blocked.

Fixtures adapted from tests/test_equipment_usage.py (usage) and
tests/test_wound_combat_integration.py (combat).
"""
import copy

import server
import engine_core


# ---------------------------------------------------------------------------
# Usage fixtures (mirrors test_equipment_usage.py)
# ---------------------------------------------------------------------------

def _pc(items, wounds=None):
    return {"name": "Petros", "slot_capacity_total": 13, "wounds_slots_used": 0,
            "mystic_gifts": [], "codices": [], "abilities": {"CON": {"current": 3}},
            "wounds": list(wounds or []),
            "inventory": {"carried": list(items)}}


def _handle(server_mod, monkeypatch, char):
    data = {"characters": {"petros": char}}
    monkeypatch.setattr(server_mod, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server_mod, "_save_single_character", lambda *a, **k: None)
    return data


def _no_roll(a, b):
    raise AssertionError("No dice may be rolled on a broken-item block")


# ---------------------------------------------------------------------------
# Combat fixtures (mirrors test_wound_combat_integration.py)
# ---------------------------------------------------------------------------

_TRISKELE = {
    "name": "Triskele",
    "type": "exotica_weapon ranged",
    "damage": "3d8",
    "damage_type": "beam",
    "engine_tags": [],
    "primary": True,
}


def _make_pc(name="Vex", hp=23, max_hp=23, av=16, weapon=None, wounds=None):
    return {
        "name": name,
        "hp": {"current": hp, "max": max_hp},
        "wound_table": "synthetic",
        "av": {"base": av},
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 2, "base": 2},
        },
        "inventory": {"carried": [copy.deepcopy(weapon or _TRISKELE)]},
        "wounds": list(wounds or []),
        "special_traits": {},
    }


def _make_biological_enemy(hp=15, av=12, lvl=3):
    return {
        "hp": hp,
        "max_hp": hp,
        "av": av,
        "morale": 0,
        "lvl": lvl,
        "defeated": False,
        "fled": False,
        "resist_type": "Biological",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False,
        "attack_name": "Slash",
        "attack_damage": "d6",
        "attacks": [],
    }


def _base_isolate(monkeypatch, characters_fixture, enemies):
    monkeypatch.setattr(server, "_load_characters", lambda: (characters_fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda char: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    snapshot = {name: {"hp": data["hp"]["current"], "max_hp": data["hp"]["max"]}
                for name, data in characters_fixture["characters"].items()}
    monkeypatch.setitem(
        server.GAME_STATE, "active_combat",
        {"enemies": dict(enemies), "party_snapshot": snapshot, "log": []},
    )


# ---------------------------------------------------------------------------
# 1. usage(action='use') blocked on a broken item
# ---------------------------------------------------------------------------

def test_use_blocked_broken_usage_die_item_not_rolled(monkeypatch):
    """Broken usage-die item: blocked, usage die never rolled, die unchanged."""
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8",
                 "usage_max": "Ud8", "broken": True}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", _no_roll)

    out = server._usage_dispatch(action="use", character="Petros", item="Blowtorch")

    assert "BROKEN" in out
    assert "unusable until fixed" in out
    assert "DM ruling" in out
    assert char["inventory"]["carried"][0]["usage_die"] == "Ud8"  # untouched


def test_use_blocked_broken_discrete_not_decremented(monkeypatch):
    """Broken discrete-uses item: blocked, uses not decremented, item stays."""
    char = _pc([{"name": "Med Kit", "slots": 1, "uses": 3, "uses_max": 3,
                 "broken": True}])
    _handle(server, monkeypatch, char)

    out = server._usage_dispatch(action="use", character="Petros", item="Med Kit")

    assert "BROKEN" in out
    assert char["inventory"]["carried"][0]["uses"] == 3            # not decremented
    assert any(i.get("name") == "Med Kit"
               for i in char["inventory"]["carried"])              # not removed


def test_use_blocked_broken_last_use_item_not_removed(monkeypatch):
    """Broken item at 1 use: blocked BEFORE the consume-and-remove path."""
    char = _pc([{"name": "Draught", "slots": 1, "uses": 1, "uses_max": 1,
                 "broken": True}])
    _handle(server, monkeypatch, char)

    out = server._usage_dispatch(action="use", character="Petros", item="Draught")

    assert "BROKEN" in out
    assert any(i.get("name") == "Draught"
               for i in char["inventory"]["carried"])  # still carried


def test_use_non_broken_item_unchanged_control(monkeypatch):
    """Control: an unbroken usage-die item still rolls and depletes normally."""
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8",
                 "usage_max": "Ud8"}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)  # force deplete

    out = server._usage_dispatch(action="use", character="Petros", item="Blowtorch")

    assert "BROKEN" not in out
    assert "Ud6" in out
    assert char["inventory"]["carried"][0]["usage_die"] == "Ud6"


# ---------------------------------------------------------------------------
# 2. _combat_attack blocked with a broken weapon
# ---------------------------------------------------------------------------

def test_attack_blocked_with_broken_weapon_names_item(monkeypatch):
    """PC attacking with a broken weapon: BLOCKED naming the item; no dice
    rolled, no damage, no weapons_fired record."""
    broken_triskele = dict(_TRISKELE, broken=True)
    pc = _make_pc(name="Vex", weapon=broken_triskele)
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})
    monkeypatch.setattr(server.random, "randint", _no_roll)

    out = server._combat_attack("Vex", "Triskele", "Raider (scarred)")

    assert "BLOCKED" in out
    assert "Triskele" in out
    assert "BROKEN" in out
    assert "DM ruling" in out
    assert enemy["hp"] == 15  # no damage applied
    assert not server.GAME_STATE["active_combat"].get("weapons_fired")


def test_attack_non_broken_weapon_proceeds_control(monkeypatch):
    """Control: the same attack with an unbroken weapon resolves normally."""
    pc = _make_pc(name="Vex", weapon=_TRISKELE)
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})
    monkeypatch.setattr(server.random, "randint", lambda a, b: 15)  # 15+DEX(2)=17 > 12
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 3)

    out = server._combat_attack("Vex", "Triskele", "Raider (scarred)")

    assert "BLOCKED" not in out
    assert "HIT" in out


# ---------------------------------------------------------------------------
# 3. _combat_damage attacker-weapon auto-read blocked on a broken weapon
# ---------------------------------------------------------------------------

def test_damage_auto_read_blocked_with_broken_weapon(monkeypatch):
    """action='damage' with attacker= a PC carrying a broken weapon: BLOCKED
    (the damage path is independently callable; the broken weapon's damage
    profile must not silently apply). Enemy HP untouched."""
    broken_triskele = dict(_TRISKELE, broken=True)
    pc = _make_pc(name="Vex", weapon=broken_triskele)
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    out = server._combat_damage(target="Raider (scarred)", amount=5,
                                damage_type="kinetic", attacker="Vex")

    assert "BLOCKED" in out
    assert "Triskele" in out
    assert "BROKEN" in out
    assert enemy["hp"] == 15


def test_damage_auto_read_non_broken_control(monkeypatch):
    """Control: damage with an unbroken sheet weapon applies normally."""
    pc = _make_pc(name="Vex", weapon=_TRISKELE)
    fixture = {"characters": {"Vex": pc}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})

    out = server._combat_damage(target="Raider (scarred)", amount=5,
                                damage_type="kinetic", attacker="Vex")

    assert "BLOCKED" not in out
    assert enemy["hp"] == 10


# ---------------------------------------------------------------------------
# 4. Persistence e2e: broken flag survives healing the originating wound
# ---------------------------------------------------------------------------

def test_broken_flag_persists_past_wound_heal(monkeypatch):
    """Heal the Damaged Item wound via _wound_dispatch: the wound record goes,
    but the item-level broken flag stays and use remains blocked (spec section
    6: brokenness lives on the item; repair is the deferred DM seam)."""
    char = _pc(
        [{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8",
          "usage_max": "Ud8", "broken": True}],
        wounds=[{"name": "Damaged Item", "hp_threshold": -1, "slots": 0,
                 "effect": "An item is unusable until fixed"}],
    )
    _handle(server, monkeypatch, char)

    out = server._wound_dispatch(action="heal", character="Petros",
                                 wound="Damaged Item")

    assert "healed" in out.lower()
    assert char["wounds"] == []                                  # record gone
    item = char["inventory"]["carried"][0]
    assert item.get("broken") is True                            # flag persists

    monkeypatch.setattr(server.random, "randint", _no_roll)
    out2 = server._usage_dispatch(action="use", character="Petros",
                                  item="Blowtorch")
    assert "BROKEN" in out2                                      # still blocked
    assert item["usage_die"] == "Ud8"


# ---------------------------------------------------------------------------
# Precedence + sibling-path pins (Task 7 review)
# ---------------------------------------------------------------------------

def test_broken_trumps_blind_on_attack(monkeypatch):
    """A blind PC with a broken weapon gets the BROKEN block, not blind-DIS."""
    import wounds as w
    blind = w.roll_wound_record(-12, w.SYNTHETIC_WOUNDS[-12])
    weapon = dict(_TRISKELE, broken=True)
    pc = _make_pc(weapon=weapon, wounds=[blind])
    fixture = {"characters": {"Vex": pc}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy()})
    monkeypatch.setattr(server.random, "randint", _no_roll)
    out = server._combat_attack("Vex", "Triskele", "Raider (scarred)")
    assert "BROKEN" in out
    assert "DISADVANTAGE" not in out and "blind" not in out.lower()


def test_broken_weapon_never_prompts_creenash(monkeypatch):
    """Creenash with a broken weapon gets BLOCKED, not the Iron-Law-3
    roll-the-d20 prompt."""
    pc = _make_pc(name="Creenash", weapon=dict(_TRISKELE, broken=True))
    fixture = {"characters": {"Creenash": pc}}
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": _make_biological_enemy()})
    monkeypatch.setattr(server.random, "randint", _no_roll)
    out = server._combat_attack("Creenash", "Triskele", "Raider (scarred)")
    assert "BROKEN" in out
    assert "to_hit" not in out                     # no Iron-Law-3 prompt


def test_usage_roll_blocked_on_broken_weapon(monkeypatch):
    """usage(action='roll') on a broken weapon blocks instead of silently
    depleting the die of an unusable weapon."""
    char = _pc([{"name": "Bolts", "slots": 1, "ammo": "Ud8", "ammo_max": "Ud8",
                 "range": "ranged", "broken": True}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", _no_roll)
    out = server._usage_dispatch(action="roll", character="Petros", weapon="Bolts")
    assert "BROKEN" in out
    assert char["inventory"]["carried"][0]["ammo"] == "Ud8"   # die untouched


def test_usage_status_tags_broken_items(monkeypatch):
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8", "broken": True},
                {"name": "Med Kit", "slots": 1, "uses": 3}])
    _handle(server, monkeypatch, char)
    out = server._usage_dispatch(action="status")
    assert "Blowtorch: BROKEN" in out
    assert 'item="Blowtorch"' not in out           # no use-call pushed for it
    assert 'item="Med Kit"' in out                 # unbroken still pushed
