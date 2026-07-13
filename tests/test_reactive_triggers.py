"""C1 Reactive Triggers (spec 2026-06-12-c1-reactive-triggers-design.md).

Defender-sheet reactive abilities (special_traits.triggers) fire on the
enemy->PC hit path of _combat_attack:
- Acid Blood (effect=retaliate): melee attacker that damages the PC takes
  the trigger's damage die, applied through the enemy-damage path.
- Toxic Sap (effect=tox_attack): a bite-named attack that damages the PC
  puts the trigger's tox_die on the attacker via the B1 toxin machinery.
- Mirrored Leaves (effect=reflect_save): a beam hit is WITHHELD; the result
  pushes the FAIL/SUCCESS combat(action='damage') fork for the player save.
- Unknown effect values degrade to a REACTIVE FLAG line (no crash).

Fixture idioms from test_combat_attack.py; deterministic dice via a
sequenced server.random.randint monkeypatch (test_gambits idiom).
"""
import copy
import substances

import server
from tests.test_combat_attack import (_CREENASH, _make_biological_enemy,
                                      _base_isolate)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_ACID_BLOOD = {
    "name": "Acid Blood",
    "when": "melee_damage_taken",
    "effect": "retaliate",
    "damage": "d4", "damage_type": "acid",
    "source": "Cacogen mutation #01 (CH bk3 d100 table)",
}

_TOXIC_SAP = {
    "name": "Toxic Sap",
    "when": "bitten",
    "effect": "tox_attack",
    "tox_die": "d10",
    "note": "Also: one harvestable dose of d10 TOX sap per day.",
    "source": "Bloomboon #10 (CH p.049)",
}

_MIRRORED_LEAVES = {
    "name": "Mirrored Leaves",
    "when": "beam_attack_hit",
    "effect": "reflect_save",
    "save": "DEX",
    "source": "Bloomboon #2 (CH p.049)",
}

_BARBED_BARK = {
    "name": "Barbed Bark",
    "when": "melee_missed",
    "effect": "retaliate",
    "damage": "d4", "damage_type": "kinetic",
    "source": "Bloomboon #3 (CH p.049)",
}


def _pc(name, triggers=None):
    """Minimal PC sheet carrying reactive triggers (AV 10 so lvl-2 enemies hit)."""
    return {
        "name": name.title(),
        "hp": {"current": 20, "max": 20},
        "wound_table": "biological",
        "av": {"base": 10},
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 2, "base": 2},
        },
        "inventory": {"carried": []},
        "special_traits": ({"triggers": list(triggers)} if triggers is not None
                          else {}),
    }


def _chars(*pcs):
    return {"characters": {p["name"].lower(): p for p in pcs},
            "meta": {"campaign_day": 1}}


def _seq_rng(monkeypatch, d20s, other=None):
    """d20 rolls come from the d20s sequence (to-hit first, then any enemy
    CON saves); other die sizes resolve via the {faces: value} map."""
    other = other or {}
    seq = iter(d20s)

    def rng(a, b):
        if (a, b) == (1, 20):
            return next(seq)
        return other.get(b, a)

    monkeypatch.setattr(server.random, "randint", rng)


def _force_enemy_save_d20(monkeypatch, value):
    """Pin the enemy CON-save d20. _toxin_enemy_save's rng default is bound
    at import time (rng=random.randint), so patching random.randint cannot
    reach it - wrap the real function and inject a fixed-roll rng instead."""
    orig = server._toxin_enemy_save

    def forced(enemy, tox_die, rng=None):
        return orig(enemy, tox_die, rng=lambda a, b: value)

    # _toxin_enemy_save moved to substances (slice 2); called via mover->mover edge,
    # so patch BOTH namespaces (server alias + substances home).
    monkeypatch.setattr(server, "_toxin_enemy_save", forced)
    monkeypatch.setattr(substances, "_toxin_enemy_save", forced)


# ---------------------------------------------------------------------------
# Acid Blood (retaliate)
# ---------------------------------------------------------------------------

def test_acid_blood_retaliation_damages_attacker(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)   # attack_name "Slash" (melee)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})  # hit 17>10; d6=4; d4=3
    out = server._combat_attack("Raider", None, "kess")
    assert "HIT" in out
    assert "REACTIVE - Acid Blood: Raider takes 3 acid (assumed melee - DM may waive)" in out
    assert enemy["hp"] == 12
    assert '"Acid Blood"' in out          # dm_result reactive list


def test_acid_blood_respects_enemy_resistances(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["resistances"]["immune"] = ["acid"]
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Acid Blood" in out
    assert enemy["hp"] == 15              # immunity ate the retaliation
    assert not enemy["defeated"]


def test_acid_blood_retaliation_can_defeat_enemy(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=2, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Acid Blood" in out
    assert enemy["hp"] == 0
    assert enemy["defeated"] is True
    assert "defeated" in out.lower()
    assert "combat" in out and "end" in out   # combat-end push (sole enemy down)


def test_acid_blood_does_not_fire_on_ranged_name(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Sling Stone"
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "HIT" in out
    assert "REACTIVE" not in out
    assert enemy["hp"] == 15


def test_acid_blood_does_not_fire_on_range_field(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["range"] = "ranged"
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "HIT" in out
    assert "REACTIVE" not in out
    assert enemy["hp"] == 15


def test_acid_blood_does_not_fire_on_miss(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={6: 4, 4: 3})   # 5+2=7 vs AV 10: miss
    out = server._combat_attack("Raider", None, "kess")
    assert "MISS" in out
    assert "REACTIVE" not in out
    assert enemy["hp"] == 15
    assert '"reactive": []' in out


def test_pc_without_triggers_unaffected(monkeypatch):
    chars = {"characters": {"creenash": copy.deepcopy(_CREENASH)},
             "meta": {"campaign_day": 1}}
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, chars, {"Raider": enemy})
    _seq_rng(monkeypatch, [19], other={6: 4})        # 19+2=21 vs AV 16: hit
    out = server._combat_attack("Raider", None, "Creenash")
    assert "HIT" in out
    assert "REACTIVE" not in out
    assert '"reactive": []' in out


# ---------------------------------------------------------------------------
# Toxic Sap (tox_attack on bite)
# ---------------------------------------------------------------------------

def test_toxic_sap_bite_failed_save_enemy_gains_toxin(monkeypatch):
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Bite"
    _base_isolate(monkeypatch, _chars(cree), {"Hound": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})          # to-hit 15+2=17: hit
    _force_enemy_save_d20(monkeypatch, 3)              # 3+2=5 < DC 20: FAIL
    out = server._combat_attack("Hound", None, "creenash")
    assert "REACTIVE - Toxic Sap" in out
    assert "TOX" in out
    assert "poison" not in out.lower()               # R-C1d: toxin, never poison
    assert enemy.get("toxin_die") == "d10"
    assert '"Toxic Sap"' in out


def test_toxic_sap_bite_passed_save_no_toxin(monkeypatch):
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Bite"
    _base_isolate(monkeypatch, _chars(cree), {"Hound": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    _force_enemy_save_d20(monkeypatch, 18)             # 18+2=20 >= DC 20: PASS
    out = server._combat_attack("Hound", None, "creenash")
    assert "REACTIVE - Toxic Sap" in out
    assert "succeeded" in out
    assert "toxin_die" not in enemy


def test_toxic_sap_does_not_fire_on_claw(monkeypatch):
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Claw"
    _base_isolate(monkeypatch, _chars(cree), {"Hound": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    out = server._combat_attack("Hound", None, "creenash")
    assert "HIT" in out
    assert "REACTIVE" not in out
    assert "toxin_die" not in enemy


def test_toxic_sap_synth_attacker_immune(monkeypatch):
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Bite"
    enemy["resist_type"] = "Synthetic"
    _base_isolate(monkeypatch, _chars(cree), {"Auto-Hound": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    out = server._combat_attack("Auto-Hound", None, "creenash")
    assert "REACTIVE - Toxic Sap" in out
    assert "immune" in out.lower()
    assert "toxin_die" not in enemy


# ---------------------------------------------------------------------------
# Mirrored Leaves (reflect_save on beam)
# ---------------------------------------------------------------------------

def test_mirrored_leaves_beam_withheld_with_save_fork(monkeypatch):
    tess = _pc("tesslyn", [_MIRRORED_LEAVES])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Eye Lance"
    enemy["attack_damage"] = "d8, beam"
    _base_isolate(monkeypatch, _chars(tess), {"Watcher": enemy})
    _seq_rng(monkeypatch, [15], other={8: 5})
    out = server._combat_attack("Watcher", None, "tesslyn")
    assert "HIT" in out
    assert "WITHHELD" in out
    assert "REACTIVE - Mirrored Leaves" in out
    assert "DEX save" in out
    # Both pre-filled calls present (FAIL -> PC, SUCCESS -> reflected at enemy)
    assert 'combat(action="damage", target="tesslyn", amount=5, damage_type="beam")' in out
    assert 'combat(action="damage", target="Watcher", amount=5, damage_type="beam")' in out
    assert '"reactive_pending": true' in out
    assert '"reactive_withheld": 5' in out
    # Damage NOT applied to the PC
    assert tess["hp"]["current"] == 20


def test_mirrored_leaves_kinetic_hit_applies_normally(monkeypatch):
    tess = _pc("tesslyn", [_MIRRORED_LEAVES])
    enemy = _make_biological_enemy(hp=15, av=12)   # "Slash", d6 kinetic
    _base_isolate(monkeypatch, _chars(tess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    out = server._combat_attack("Raider", None, "tesslyn")
    assert "HIT" in out
    assert "WITHHELD" not in out
    assert "REACTIVE" not in out
    assert tess["hp"]["current"] == 16


# ---------------------------------------------------------------------------
# Unknown effect -> flag-and-push degradation
# ---------------------------------------------------------------------------

def test_unknown_effect_flags_without_changing_damage(monkeypatch):
    weird = {"name": "Weird Bloom", "when": "sometimes",
             "effect": "frobnicate", "note": "DM adjudicates the bloom."}
    kess = _pc("kess", [weird])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    out = server._combat_attack("Raider", None, "kess")
    assert "HIT" in out
    assert "REACTIVE FLAG - Weird Bloom" in out
    assert "DM adjudicates the bloom." in out
    assert kess["hp"]["current"] == 16             # damage applied unchanged
    assert enemy["hp"] == 15                       # no retaliation invented


# ---------------------------------------------------------------------------
# Coexistence seams
# ---------------------------------------------------------------------------

def test_tox_reroute_bite_still_fires_toxic_sap(monkeypatch):
    """An enemy TOX bite reroutes the PC damage to the Toxin Die mechanic;
    the Toxic Sap retaliation must still fire back at the biter."""
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Venom Bite"
    enemy["attack_damage"] = "d10 TOX"
    _base_isolate(monkeypatch, _chars(cree), {"Serpent": enemy})
    _seq_rng(monkeypatch, [15], other={10: 4})         # to-hit only
    _force_enemy_save_d20(monkeypatch, 3)              # sap save FAILs
    out = server._combat_attack("Serpent", None, "creenash")
    # The PC-side reroute push (player rolls the CON save)
    assert "roll CON save" in out
    # The reactive sap landed on the biter
    assert "REACTIVE - Toxic Sap" in out
    assert enemy.get("toxin_die") == "d10"


def test_trigger_and_gambit_coexist(monkeypatch):
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Duelist": enemy})
    _seq_rng(monkeypatch, [19], other={6: 4, 4: 3})  # 19+2=21 > 20: gambit
    out = server._combat_attack("Duelist", None, "kess")
    assert "GAMBIT AVAILABLE" in out
    assert "REACTIVE - Acid Blood" in out
    assert enemy["hp"] == 12


def test_retaliation_kill_suppresses_gambit(monkeypatch):
    """MAJOR-1: a gambit-qualifying hit whose attacker dies to the
    retaliation must NOT advertise a stunt for the corpse."""
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=2, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Duelist": enemy})
    _seq_rng(monkeypatch, [19], other={6: 4, 4: 3})  # 21 > 20; d4=3 kills hp 2
    out = server._combat_attack("Duelist", None, "kess")
    assert enemy["defeated"] is True
    assert "defeated" in out.lower()
    assert "GAMBIT AVAILABLE" not in out
    assert '"gambit_available": false' in out
    assert "(no gambit - attacker defeated by retaliation)" in out


def test_retaliation_kill_morale_break_stamped(monkeypatch):
    """MAJOR-2: a retaliation kill that breaks the remaining enemies' morale
    must agree between the prose and dm_result's morale_broken flag."""
    kess = _pc("kess", [_ACID_BLOOD])
    attacker = _make_biological_enemy(hp=2, av=12)
    bystander = _make_biological_enemy(hp=10, av=12)
    orig_morale = server._check_morale_triggers
    _base_isolate(monkeypatch, _chars(kess),
                  {"Raider": attacker, "Grunt": bystander})
    monkeypatch.setattr(server, "_check_morale_triggers", orig_morale)
    # d20s: to-hit 15 (17 > 10, no gambit noise); morale check 2 (2 < 16: FAIL)
    _seq_rng(monkeypatch, [15, 2], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert attacker["defeated"] is True
    assert "Morale broken" in out
    assert bystander["fled"] is True
    assert '"morale_broken": true' in out


def test_retaliation_does_not_invoke_round_advance(monkeypatch):
    """MINOR-3: the retaliation _combat_damage is not an action - only the
    attack's own PC-damage call may run the round-advance check."""
    kess = _pc("kess", [_ACID_BLOOD])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    calls = []
    monkeypatch.setattr(server, "_check_round_advance",
                        lambda: calls.append(1) or "")
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Acid Blood" in out
    assert len(calls) == 1            # PC-damage call only, not the retaliation


def test_skip_round_advance_param(monkeypatch):
    """MINOR-3 unit pin: skip_round_advance=True never ticks the round;
    a normal damage call in the same both-acted state still does."""
    kess = _pc("kess", [])
    enemy = _make_biological_enemy(hp=15, av=12)
    orig_cra = server._check_round_advance
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    monkeypatch.setattr(server, "_check_round_advance", orig_cra)
    combat = server.GAME_STATE["active_combat"]
    combat.update({"round": 1, "pcs_acted": True, "enemies_acted": True,
                   "initiative": "pcs", "morale_checked": False})
    _seq_rng(monkeypatch, [], other={6: 2})  # initiative d6 when it DOES tick
    server._combat_damage("Raider", 3, "acid", skip_round_advance=True)
    assert combat["round"] == 1          # retaliation-style call: no tick
    server._combat_damage("Raider", 2, "acid")
    assert combat["round"] == 2          # normal damage call still advances


def test_invalid_tox_die_flags_instead_of_firing(monkeypatch):
    """MINOR-4: a garbage tox_die must surface loudly, not degrade to a
    'cured' no-op through dice_chain normalization."""
    bad_sap = dict(_TOXIC_SAP, tox_die="d100")
    cree = _pc("creenash", [bad_sap])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Bite"
    _base_isolate(monkeypatch, _chars(cree), {"Hound": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4})
    out = server._combat_attack("Hound", None, "creenash")
    assert "REACTIVE FLAG - Toxic Sap" in out
    assert "'d100'" in out
    assert "not a legal rank" in out
    assert "toxin_die" not in enemy          # nothing applied
    assert "cured" not in out.lower()


def test_beam_bite_withhold_surfaces_bitten_lever(monkeypatch):
    """MINOR-5: a beam attack that is also a bite withholds (reflect_save)
    but must still surface the bitten trigger as a pre-filled DM lever."""
    tess = _pc("tesslyn", [_MIRRORED_LEAVES, _TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Bite"
    enemy["attack_damage"] = "d8, beam"
    _base_isolate(monkeypatch, _chars(tess), {"Watcher": enemy})
    _seq_rng(monkeypatch, [15], other={8: 5})
    out = server._combat_attack("Watcher", None, "tesslyn")
    assert "WITHHELD" in out
    assert "also a bite" in out
    assert 'affliction(kind="toxin", action="check", target="Watcher", tox_die="d10")' in out
    assert "toxin_die" not in enemy          # lever only - DM applies it


def test_barbed_bark_fires_on_melee_miss(monkeypatch):
    """C2 (R-C2b): an enemy melee MISS against a Barbed Bark PC deals d4 to
    the attacker via the real enemy-damage path, stamped on the miss
    dm_result."""
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)   # attack_name "Slash" (melee)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={4: 3})       # 5+2=7 vs AV 10: miss; d4=3
    out = server._combat_attack("Raider", None, "kess")
    assert "MISS" in out
    assert "REACTIVE - Barbed Bark: Raider takes 3 kinetic" in out
    assert enemy["hp"] == 12
    assert '"Barbed Bark"' in out                  # dm_result reactive list
    assert kess["hp"]["current"] == 20             # the miss dealt nothing


def test_barbed_bark_fires_on_fumble(monkeypatch):
    """Pinned decision: a fumble is also a miss - a flailing natural 1 still
    meets the barbs."""
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [1], other={4: 3})       # natural 1: FUMBLE
    out = server._combat_attack("Raider", None, "kess")
    assert "FUMBLE" in out
    assert "REACTIVE - Barbed Bark: Raider takes 3 kinetic" in out
    assert enemy["hp"] == 12
    assert '"Barbed Bark"' in out


def test_barbed_bark_does_not_fire_on_ranged_miss(monkeypatch):
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Sling Stone"
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "MISS" in out
    assert "REACTIVE" not in out
    assert enemy["hp"] == 15
    assert '"reactive": []' in out


def test_barbed_bark_never_fires_on_hit(monkeypatch):
    """A melee_missed trigger NEVER fires when the attack lands."""
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})  # 17 > 10: hit
    out = server._combat_attack("Raider", None, "kess")
    assert "HIT" in out
    assert "REACTIVE" not in out
    assert enemy["hp"] == 15
    assert kess["hp"]["current"] == 16             # PC damage applied normally


def test_barbed_bark_and_acid_blood_phase_disjoint(monkeypatch):
    """A PC with Barbed Bark + Acid Blood: a miss fires barbs ONLY, a hit
    fires blood ONLY."""
    kess = _pc("kess", [_ACID_BLOOD, _BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={4: 3})       # miss
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Barbed Bark" in out
    assert "Acid Blood" not in out
    assert enemy["hp"] == 12

    enemy["hp"] = 15
    _seq_rng(monkeypatch, [15], other={6: 4, 4: 3})  # hit
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Acid Blood" in out
    assert "Barbed Bark" not in out
    assert enemy["hp"] == 12


def test_barbed_bark_miss_kill_defeats_attacker(monkeypatch):
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=2, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Barbed Bark" in out
    assert enemy["hp"] == 0
    assert enemy["defeated"] is True
    assert "defeated" in out.lower()
    assert "combat" in out and "end" in out        # combat-end push


def test_barbed_bark_miss_kill_morale_break_stamped(monkeypatch):
    """A barbs kill on a miss that breaks the remaining enemies' morale must
    stamp morale_broken on the MISS dm_result."""
    kess = _pc("kess", [_BARBED_BARK])
    attacker = _make_biological_enemy(hp=2, av=12)
    bystander = _make_biological_enemy(hp=10, av=12)
    orig_morale = server._check_morale_triggers
    _base_isolate(monkeypatch, _chars(kess),
                  {"Raider": attacker, "Grunt": bystander})
    monkeypatch.setattr(server, "_check_morale_triggers", orig_morale)
    # d20s: to-hit 5 (miss); morale check 2 (2 < 16: FAIL)
    _seq_rng(monkeypatch, [5, 2], other={4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert attacker["defeated"] is True
    assert "Morale broken" in out
    assert bystander["fled"] is True
    assert '"morale_broken": true' in out


def test_barbed_bark_miss_does_not_tick_round(monkeypatch):
    """The retaliation is not an action: a miss with barbs must never invoke
    the round-advance check."""
    kess = _pc("kess", [_BARBED_BARK])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    calls = []
    monkeypatch.setattr(server, "_check_round_advance",
                        lambda: calls.append(1) or "")
    _seq_rng(monkeypatch, [5], other={4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "REACTIVE - Barbed Bark" in out
    assert len(calls) == 0


def test_plain_miss_without_triggers_unchanged(monkeypatch):
    kess = _pc("kess", [])
    enemy = _make_biological_enemy(hp=15, av=12)
    _base_isolate(monkeypatch, _chars(kess), {"Raider": enemy})
    _seq_rng(monkeypatch, [5], other={4: 3})
    out = server._combat_attack("Raider", None, "kess")
    assert "MISS" in out
    assert "REACTIVE" not in out
    assert '"reactive": []' in out


def test_tox_reroute_gambit_and_reactive_triple_coexist(monkeypatch):
    """H-3: a TOX-reroute hit at total>20 on a bitten-trigger PC renders all
    three blocks - the PC CON-save push, the gambit, and the REACTIVE sap."""
    cree = _pc("creenash", [_TOXIC_SAP])
    enemy = _make_biological_enemy(hp=15, av=12)
    enemy["attack_name"] = "Venom Bite"
    enemy["attack_damage"] = "d10 TOX"
    _base_isolate(monkeypatch, _chars(cree), {"Serpent": enemy})
    _seq_rng(monkeypatch, [19], other={10: 4})        # 19+2=21 > 20: gambit
    _force_enemy_save_d20(monkeypatch, 3)             # sap save FAILs
    out = server._combat_attack("Serpent", None, "creenash")
    assert "roll CON save" in out                     # TOX reroute (PC side)
    assert "GAMBIT AVAILABLE" in out
    assert "REACTIVE - Toxic Sap" in out
    assert enemy.get("toxin_die") == "d10"
