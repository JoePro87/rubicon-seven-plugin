"""R3: Piercing/Mauling -- extra die / halved damage by the target's REAL AV."""
import server
from test_combat_attack import (_base_isolate, _make_biological_enemy,
                                _extract_dm_block, _CREENASH)


def _weapon(name="Piercing Sword", damage="d8", engine_tags=("piercing",),
            **kw):
    w = {"name": name, "type": "weapon", "damage": damage,
         "damage_type": "kinetic", "kinetic_subtype": "slashing",
         "engine_tags": list(engine_tags), "range": "melee"}
    w.update(kw)
    return w


def _pc(weapon, name="Roscar"):
    return {"name": name, "hp": {"current": 23, "max": 23},
            "wound_table": "biological",
            "abilities": {"STR": {"current": 2, "base": 2},
                          "DEX": {"current": 2, "base": 2}},
            "inventory": {"carried": [weapon]}}


def _attack(monkeypatch, weapon, enemy_av, d20=18, dmg=5):
    fixture = {"characters": {"Roscar": _pc(weapon)}}
    _base_isolate(monkeypatch, fixture,
                  {"Knight (plated)": _make_biological_enemy(hp=30, av=enemy_av)})
    monkeypatch.setattr(server.random, "randint", lambda a, b: d20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: dmg)
    return server._combat_attack("Roscar", weapon["name"], "Knight (plated)")


def test_piercing_extra_die_vs_av16(monkeypatch):
    out = _attack(monkeypatch, _weapon(), enemy_av=16)   # d20 18+2=20 > 16
    block = _extract_dm_block(out)
    # _roll_stat_expr patched to 5: base 5 + extra die 5 = 10
    assert block["damage_sent"] == 10
    assert block["av_damage_mod"] == {"tag": "piercing", "bracket": "extra-die",
                                      "real_av": 16}
    assert "extra d8" in out


def test_piercing_halved_vs_av13(monkeypatch):
    out = _attack(monkeypatch, _weapon(), enemy_av=13)
    block = _extract_dm_block(out)
    assert block["damage_sent"] == 2          # 5 // 2 = 2
    assert block["av_damage_mod"]["bracket"] == "halved"
    assert "halved" in out


def test_piercing_dead_zone_14_15(monkeypatch):
    for av in (14, 15):
        out = _attack(monkeypatch, _weapon(), enemy_av=av)
        block = _extract_dm_block(out)
        assert block["damage_sent"] == 5
        assert block["av_damage_mod"] is None


def test_mauling_mirrored(monkeypatch):
    out = _attack(monkeypatch, _weapon(engine_tags=("mauling",)), enemy_av=12)
    assert _extract_dm_block(out)["av_damage_mod"]["bracket"] == "extra-die"
    out = _attack(monkeypatch, _weapon(engine_tags=("mauling",)), enemy_av=16)
    assert _extract_dm_block(out)["av_damage_mod"]["bracket"] == "halved"


def test_crit_doubles_extra_die_too(monkeypatch):
    out = _attack(monkeypatch, _weapon(), enemy_av=16, d20=20)
    # (5 base + 5 extra) * 2 = 20
    assert _extract_dm_block(out)["damage_sent"] == 20


def test_crit_plus_halved_display_coherent(monkeypatch):
    # crit (x2) then halve: 5 -> 10 -> 5. The x2 segment must show the
    # PRE-halving product so the arithmetic reads true.
    out = _attack(monkeypatch, _weapon(), enemy_av=12, d20=20)
    blk = _extract_dm_block(out)
    assert blk["damage_sent"] == 5            # max(1, (5*2)//2)
    assert "= 10" in out                       # post-crit, pre-halve product
    assert "-> 5" in out                       # halved note carries the final


def test_halving_floors_with_min_1(monkeypatch):
    out = _attack(monkeypatch, _weapon(damage="d4"), enemy_av=10, dmg=1)
    assert _extract_dm_block(out)["damage_sent"] == 1   # max(1, 1//2)


def test_piercing_wins_if_both_tags(monkeypatch):
    w = _weapon(engine_tags=("piercing", "mauling"))
    out = _attack(monkeypatch, w, enemy_av=16)
    blk = _extract_dm_block(out)["av_damage_mod"]
    assert blk["tag"] == "piercing" and blk["bracket"] == "extra-die"


def test_piercing_plus_vibroactive_hit_vs_10_bracket_vs_real(monkeypatch):
    w = _weapon(engine_tags=("piercing", "vibroactive"))
    out = _attack(monkeypatch, w, enemy_av=16, d20=12)   # 12+2=14: >10, <16
    assert "HIT" in out
    assert "vs AV 10" in out
    blk = _extract_dm_block(out)
    assert blk["av_override"]["real"] == 16
    assert blk["av_damage_mod"]["real_av"] == 16          # bracket reads REAL
    assert blk["av_damage_mod"]["bracket"] == "extra-die"


def test_subtype_piercing_alone_no_mod(monkeypatch):
    w = _weapon(name="Spear", engine_tags=(), kinetic_subtype="piercing")
    out = _attack(monkeypatch, w, enemy_av=16)
    assert _extract_dm_block(out)["av_damage_mod"] is None


def test_creenash_prompt_extra_die(monkeypatch):
    cre = dict(_CREENASH)
    cre["inventory"] = {"carried": [_weapon()]}
    fixture = {"characters": {"Creenash": cre}}
    _base_isolate(monkeypatch, fixture,
                  {"Knight (plated)": _make_biological_enemy(hp=30, av=17)})
    out = server._combat_attack("Creenash", "Piercing Sword",
                                "Knight (plated)", to_hit=18)
    assert "Hit confirmed" in out
    assert "TWICE" in out and "d8" in out and "Piercing" in out


def test_creenash_supplied_roll_halved_by_engine(monkeypatch):
    cre = dict(_CREENASH)
    cre["inventory"] = {"carried": [_weapon()]}
    fixture = {"characters": {"Creenash": cre}}
    enemy = _make_biological_enemy(hp=30, av=12)
    _base_isolate(monkeypatch, fixture, {"Raider (scarred)": enemy})
    out = server._combat_attack("Creenash", "Piercing Sword",
                                "Raider (scarred)", to_hit=18, damage_roll=9)
    blk = _extract_dm_block(out)
    assert blk["damage_sent"] == 4            # max(1, 9 // 2)
    assert blk["av_damage_mod"]["bracket"] == "halved"


# ---------------------------------------------------------------------------
# TEST: TOX weapon reroutes before AV bracket — spec testing-list item
# ---------------------------------------------------------------------------

def test_tox_weapon_reroutes_before_bracket(monkeypatch):
    # A TOX/poison hit imposes the Toxin Die (CON save flow) INSTEAD of flat
    # damage -- the reroute returns before the R3 bracket is computed.
    # Assertions verified against actual output: no piercing-extra-die note,
    # and the toxin CON-save flow is confirmed present.
    w = _weapon(name="Toxic Stinger", damage="d6",
                engine_tags=("piercing",), damage_type="TOX",
                kinetic_subtype=None)
    out = _attack(monkeypatch, w, enemy_av=16)
    # Toxin flow happened: output names the TOX die and prompts a CON save
    assert "TOX" in out
    assert "CON save" in out
    # No piercing extra-die note -- the bracket never ran
    assert "piercing extra" not in out


# ---------------------------------------------------------------------------
# TEST: auto-hit (unconscious PC target) still applies the AV bracket
# ---------------------------------------------------------------------------

def _pc_unconscious(weapon, name="Valna"):
    """A PC with AV 16 and a wound record that sets unconscious=True."""
    return {"name": name, "hp": {"current": 8, "max": 20},
            "wound_table": "biological",
            "av": {"base": 16},
            "wounds": [{"unconscious": True}],
            "abilities": {"STR": {"current": 1, "base": 1},
                          "DEX": {"current": 1, "base": 1}},
            "inventory": {"carried": []}}


def test_auto_hit_unconscious_target_applies_bracket(monkeypatch):
    # An unconscious PC target auto-hits (no d20 contest). The AV bracket
    # (piercing vs AV 16 -> extra-die) must still run using the PC's sheet AV.
    w = _weapon()                             # piercing d8
    valna = _pc_unconscious(w)
    fixture = {"characters": {
        "Roscar": _pc(w),
        "Valna":  valna,
    }}
    _base_isolate(monkeypatch, fixture,
                  {"Knight (plated)": _make_biological_enemy(hp=30, av=16)})
    # Patch to prevent any real d20 roll (auto-hit must skip it entirely)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 5)
    out = server._combat_attack("Roscar", "Piercing Sword", "Valna")
    # Must be an auto-hit, not a regular hit/miss
    assert "AUTO-HIT" in out
    # AV bracket fired: piercing vs real AV 16 -> extra-die
    blk = _extract_dm_block(out)
    assert blk["av_damage_mod"] == {"tag": "piercing", "bracket": "extra-die",
                                    "real_av": 16}
    # damage_sent: base 5 + extra die 5 = 10 (no crit on auto-hit)
    assert blk["damage_sent"] == 10
