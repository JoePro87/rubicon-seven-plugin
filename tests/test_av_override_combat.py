"""R3: Vibroactive / Dimensional Edge cap the hit contest at AV 10 (never raise)."""
import server
from test_combat_attack import (_base_isolate, _make_biological_enemy,
                                _extract_dm_block)


_VIBRO_SWORD = {
    "name": "Vibroactive Sword", "type": "exotica_weapon", "damage": "d8",
    "damage_type": "kinetic", "kinetic_subtype": "slashing",
    "engine_tags": ["vibroactive"], "range": "melee",
}

# prose-tag-only (engine_tags EMPTY): exercises the registry-backed prose
# fallback in _weapon_has_tag -- the hand-authored / pre-backfill shape.
_LETTER_OPENER = {
    "name": "Extradimensional Letter Opener", "type": "exotica_weapon",
    "damage": "d4", "damage_type": "kinetic", "kinetic_subtype": "piercing",
    "engine_tags": [],
    "tags": ["Dimensional Edge — attacks treat target AV as 10 (unarmored)"],
    "range": "melee",
}

_PLAIN_SWORD = {
    "name": "Sword", "type": "weapon", "damage": "d8",
    "damage_type": "kinetic", "kinetic_subtype": "slashing",
    "engine_tags": [], "range": "melee",
}


def _pc(weapon):
    return {
        "name": "Roscar",
        "hp": {"current": 23, "max": 23},
        "wound_table": "biological",
        "abilities": {"STR": {"current": 2, "base": 2},
                      "DEX": {"current": 2, "base": 2}},
        "inventory": {"carried": [weapon]},
    }


def _attack(monkeypatch, weapon, enemy_av, d20=13):
    """d20=13 + STR 2 = 15: misses AV 16, hits AV 10."""
    fixture = {"characters": {"Roscar": _pc(weapon)}}
    _base_isolate(monkeypatch, fixture,
                  {"Knight (plated)": _make_biological_enemy(hp=20, av=enemy_av)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: d20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 4)
    return server._combat_attack("Roscar", weapon["name"], "Knight (plated)")


def test_vibroactive_caps_av16_to_10(monkeypatch):
    out = _attack(monkeypatch, _VIBRO_SWORD, enemy_av=16)
    assert "HIT" in out
    assert "vs AV 10" in out
    assert "real AV 16" in out
    block = _extract_dm_block(out)
    assert block["defender_av"] == 10
    assert block["av_override"] == {"real": 16, "effective": 10,
                                    "source": "vibroactive"}


def test_plain_weapon_misses_av16_control(monkeypatch):
    out = _attack(monkeypatch, _PLAIN_SWORD, enemy_av=16)
    assert "MISS" in out
    block = _extract_dm_block(out)
    assert block["defender_av"] == 16
    assert block["av_override"] is None


def test_override_never_raises_av9(monkeypatch):
    out = _attack(monkeypatch, _VIBRO_SWORD, enemy_av=9)
    assert "vs AV 9" in out
    assert "armour ignored" not in out
    assert _extract_dm_block(out)["av_override"] is None


def test_av10_target_silent_noop(monkeypatch):
    out = _attack(monkeypatch, _VIBRO_SWORD, enemy_av=10)
    assert "armour ignored" not in out
    assert _extract_dm_block(out)["av_override"] is None


def test_dimensional_edge_prose_tag_only(monkeypatch):
    out = _attack(monkeypatch, _LETTER_OPENER, enemy_av=16)
    assert "HIT" in out
    assert "vs AV 10" in out
    assert "Dimensional Edge" in out
    assert _extract_dm_block(out)["av_override"]["source"] == "dimensional-edge"


def test_kinetic_subtype_piercing_never_overrides(monkeypatch):
    # subtype is NOT a tag -- a regular spear must change nothing
    spear = dict(_PLAIN_SWORD, name="Spear", kinetic_subtype="piercing")
    out = _attack(monkeypatch, spear, enemy_av=16)
    assert "MISS" in out
    assert _extract_dm_block(out)["av_override"] is None
