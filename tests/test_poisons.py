"""B2 Poisons - generator table, application, coating, sap harvest."""
import json
import pytest
import server
import substances
import engine_core
import conditions as cnd


BOOK_ROWS = {
    1:  ("Crimson",    "Liquid",  "Must be ingested",  "d6 TOX damage"),
    2:  ("Azure",      "Liquid",  "Must be ingested",  "d8 TOX damage"),
    3:  ("Ochre",      "Liquid",  "Must be ingested",  "d10 TOX damage"),
    4:  ("Ash-grey",   "Oil",     "Must be ingested",  "d12 TOX damage"),
    5:  ("Black",      "Oil",     "Must be ingested",  "d20 TOX damage"),
    6:  ("White",      "Oil",     "Must be ingested",  "d4 STR loss / d10 STR loss"),
    7:  ("Jade",       "Oil",     "Must be ingested",  "d4 DEX loss / d10 DEX loss"),
    8:  ("Golden",     "Powder",  "Must be ingested",  "d4 CON loss / d10 CON loss"),
    9:  ("Silver",     "Powder",  "Contact with skin", "d4 PSY loss / d10 PSY loss"),
    10: ("Brassy",     "Powder",  "Contact with skin", "d4 EGO loss / d10 EGO loss"),
    11: ("Colourless", "Paste",   "Contact with skin", "Hallucinations for d6 days / d8 INT + PSY loss"),
    12: ("Pink",       "Paste",   "Airborne",          "d6 INT loss / d10 INT loss"),
    13: ("Indigo",     "Paste",   "Airborne",          "d6 INT loss / Permanent loss of language"),
    14: ("Purple",     "Sand",    "Coated on weapon",  "Blindness for d8 days / Permanent blindness"),
    15: ("Iridescent", "Glass",   "Coated on weapon",  "Vomiting for d6 days, cannot eat to recover HP / Lose d12 CON"),
    16: ("Orange",     "Leaf",    "Coated on weapon",  "Unable to use Mystic Gifts for d6 days"),
    17: ("Teal",       "Blood",   "Coated on weapon",  "Paralysis for d6 days"),
    18: ("Brown",      "Crystal", "Coated on weapon",  "Must EGO save to refuse direct commands"),
    19: ("Turquoise",  "Fungus",  "Harmless until mixed with catalyst", "Take double damage from all sources"),
    20: ("Octarine",   "Sugar",   "Harmless until mixed with catalyst", "Lose d8 Max HP / Death"),
}


class TestPoisonTablePin:
    def test_twenty_rows(self):
        assert set(server.VAARNISH_POISONS.keys()) == set(range(1, 21))

    @pytest.mark.parametrize("roll", range(1, 21))
    def test_book_text_verbatim(self, roll):
        colour, form, delivery, effect = BOOK_ROWS[roll]
        row = server.VAARNISH_POISONS[roll]
        assert row["colour"] == colour
        assert row["form"] == form
        assert row["delivery"] == delivery
        assert row["effect_text"] == effect

    @pytest.mark.parametrize("roll", range(1, 21))
    def test_engine_effects_schema(self, roll):
        fx = server.VAARNISH_POISONS[roll]["engine_effects"]
        assert fx["save"] in ("none", "con_vs_15")
        assert "greater" in fx  # greater always exists; lesser may be None
        for side in ("lesser", "greater"):
            eff = fx.get(side)
            if eff is None:
                continue
            assert eff["kind"] in ("tox", "ability_loss", "condition",
                                   "max_hp_loss", "death")

    def test_tox_rows_have_no_application_save(self):
        # Rows 1-5: the Toxin Die mechanic IS the save (R-B2a corollary)
        for roll in range(1, 6):
            fx = server.VAARNISH_POISONS[roll]["engine_effects"]
            assert fx["save"] == "none"
            assert fx["greater"]["kind"] == "tox"

    def test_row_11_greater_is_single_roll_int_psy(self):
        fx = server.VAARNISH_POISONS[11]["engine_effects"]["greater"]
        assert fx["kind"] == "ability_loss"
        assert fx["abilities"] == {"INT": "d8", "PSY": "d8"}
        assert fx.get("single_roll") is True

    def test_row_20_death_routes(self):
        fx = server.VAARNISH_POISONS[20]["engine_effects"]
        assert fx["lesser"] == {"kind": "max_hp_loss", "die": "d8"}
        assert fx["greater"] == {"kind": "death"}


# ---------------------------------------------------------------------------
# Task 2: until_day condition auto-expiry (advance_day sweep)
# Harness mirrors tests/test_disease_ticks.py (isolate_campaign_dir seeding).
# ---------------------------------------------------------------------------

def _kess_char(day=100, conditions=None):
    return {
        "name": "Kess", "species": "True-kin",
        "hp": {"current": 18, "max": 18}, "wound_table": "biological",
        "abilities": {a: {"current": 8, "base": 8}
                      for a in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed_campaign(dirpath, day=100, kess=None):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "kess.json").write_text(
        json.dumps(kess if kess is not None else _kess_char(day)))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get_kess():
    data, err = server._load_characters()
    assert not err
    key, ch = server._find_character(data, "kess")
    return data, key, ch


class TestConditionExpiry:
    def test_until_day_survives_normalization(self):
        rec, err = cnd.normalize_record(
            {"name": "Blinded", "until_day": 109, "note": "poison"}, day=104)
        assert not err
        assert rec["until_day"] == 109
        assert rec["note"] == "poison"

    def test_expired_condition_cleared_on_advance(self, isolate_campaign_dir):
        kess = _kess_char(day=100, conditions=[
            {"name": "Blinded", "since_day": 100, "until_day": 104}])
        _seed_campaign(isolate_campaign_dir, day=100, kess=kess)
        out = server.advance_day(105, "five days pass")
        _, _, ch = _get_kess()
        assert all(c["name"] != "Blinded" for c in ch.get("conditions", []))
        assert "Blinded" in out and "expire" in out.lower()

    def test_unexpired_condition_survives(self, isolate_campaign_dir):
        kess = _kess_char(day=100, conditions=[
            {"name": "Blinded", "since_day": 100, "until_day": 110}])
        _seed_campaign(isolate_campaign_dir, day=100, kess=kess)
        server.advance_day(105, "five days pass")
        _, _, ch = _get_kess()
        assert any(c["name"] == "Blinded" for c in ch.get("conditions", []))


# ---------------------------------------------------------------------------
# Task 3: poison resolution core (_poison_resolve_effect / _toxin_dispatch)
# ---------------------------------------------------------------------------

def _mk_pc(**over):
    base = {"name": "Testa", "type": "True-kin",
            "hp": {"current": 10, "max": 10},
            "abilities": {s: {"current": 12, "max": 12}
                          for s in ("STR", "DEX", "CON", "PSY", "EGO", "INT")}}
    base.update(over)
    return base


def _pc_handle(char=None):
    char = char if char is not None else _mk_pc()
    return {"kind": "pc", "key": char["name"], "char": char, "data": None}


def _enemy_handle(enemy=None):
    enemy = enemy if enemy is not None else {
        "hp": 15, "max_hp": 15, "lvl": 2, "resist_type": "Biological"}
    return {"kind": "enemy", "key": "Raider", "enemy": enemy, "data": None}


def _patch_resolve(monkeypatch, handle):
    # _toxin_resolve moved to substances (slice 2) and is called via mover->mover
    # edges, so patch BOTH namespaces (server alias + substances home).
    monkeypatch.setattr(server, "_toxin_resolve", lambda name: handle)
    monkeypatch.setattr(substances, "_toxin_resolve", lambda name: handle)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)


class TestPoisonApply:
    def test_tox_row_delegates_to_toxin_die(self, monkeypatch):
        # Row 2 (d8 TOX) on a PC: no application save - output must surface
        # the TD save DC (10+8=18) and the toxin resolve call (B1 two-phase).
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        out = "\n".join(server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[2], save_passed=False))
        assert "DC 18" in out
        assert 'affliction(kind="toxin", action="resolve"' in out

    def test_save_pass_applies_lesser(self, monkeypatch):
        # Row 6, save_total 15 (>= TN 15 passes): STR drops by a d4 roll.
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        monkeypatch.setattr(server.dice, "roll_notation",
                            lambda n: {"total": 3})
        out = server._toxin_dispatch("poison_resolve", target="Testa",
                                     save_total=15, poison=6)
        assert "PASS" in out and "d4" in out
        assert h["char"]["abilities"]["STR"]["current"] == 9

    def test_save_fail_applies_greater(self, monkeypatch):
        # Row 6, save_total 14: STR drops by the d10 roll.
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        monkeypatch.setattr(server.dice, "roll_notation",
                            lambda n: {"total": 7})
        out = server._toxin_dispatch("poison_resolve", target="Testa",
                                     save_total=14, poison=6)
        assert "FAIL" in out and "d10" in out
        assert h["char"]["abilities"]["STR"]["current"] == 5

    def test_slashless_row_negates_on_save(self, monkeypatch):
        # Row 17 (Paralysis, no slash), save_total 15: nothing minted.
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        out = server._toxin_dispatch("poison_resolve", target="Testa",
                                     save_total=15, poison=17)
        assert "resists" in out.lower()
        assert not h["char"].get("conditions")

    def test_ability_death_routes_through_death_gate(self, monkeypatch):
        # Adversarial M2: a greater ability loss that drives a stat below -10
        # is a real death - it must route through the gated seam like row 20
        # (Twinning honored, HP -20, p.229 push), never a prose-only flag.
        h = _pc_handle()
        h["char"]["abilities"]["STR"]["current"] = -8
        calls = {}

        def fake_gate(key, char, data, window_key=None, cause="damage"):
            calls["cause"] = cause
            return True, []

        monkeypatch.setattr(server, "_death_gate", fake_gate)
        monkeypatch.setattr(engine_core, "_death_gate", server._death_gate)
        monkeypatch.setattr(server.dice, "roll_notation",
                            lambda n: {"total": 8})  # STR -8 -> -16
        out = "\n".join(server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[6], save_passed=False))
        assert calls["cause"] == "poison"
        assert h["char"]["hp"]["current"] == -20
        assert "RESURRECTION" in out.upper()

    def test_row_11_single_roll_hits_both_stats_equally(self):
        # save fail, rng forced to 5: INT and PSY each drop exactly 5.
        h = _pc_handle()
        server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[11], save_passed=False,
            rng=lambda a, b: 5)
        assert h["char"]["abilities"]["INT"]["current"] == 7
        assert h["char"]["abilities"]["PSY"]["current"] == 7

    def test_condition_with_duration_mints_until_day(self):
        # Row 14 lesser (save pass): Blinded with until_day = day + d8 roll.
        h = _pc_handle()
        out = "\n".join(server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[14], save_passed=True,
            rng=lambda a, b: 4, day=100))
        conds = h["char"]["conditions"]
        rec = next(c for c in conds if c["name"] == "Blinded")
        assert rec["until_day"] == 104
        assert "4 days" in out

    def test_permanent_condition_has_no_until_day(self):
        # Row 14 greater: Blinded minted with no until_day; DM-lever line.
        h = _pc_handle()
        out = "\n".join(server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[14], save_passed=False, day=100))
        rec = next(c for c in h["char"]["conditions"]
                   if c["name"] == "Blinded")
        assert "until_day" not in rec
        assert "DM adjudicates" in out

    def test_row_20_lesser_cuts_max_hp(self):
        # save pass, rng 5: max HP 10 -> 5; current clamps to new max.
        h = _pc_handle()
        server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[20], save_passed=True,
            rng=lambda a, b: 5)
        assert h["char"]["hp"]["max"] == 5
        assert h["char"]["hp"]["current"] == 5

    def test_row_20_greater_routes_death_gate(self, monkeypatch):
        # save fail: the real gated death seam is exercised, cause="poison".
        h = _pc_handle()
        calls = {}

        def fake_gate(key, char, data, window_key=None, cause="damage"):
            calls["cause"] = cause
            return True, []

        monkeypatch.setattr(server, "_death_gate", fake_gate)
        monkeypatch.setattr(engine_core, "_death_gate", server._death_gate)
        out = "\n".join(server._poison_resolve_effect(
            h, server.VAARNISH_POISONS[20], save_passed=False))
        assert calls["cause"] == "poison"
        assert h["char"]["hp"]["current"] == -20
        assert "RESURRECTION" in out.upper()

    def test_poison_immunity_short_circuits(self, monkeypatch):
        # Physiology immunity blocks a NON-TOX row too: no save, no effect.
        h = _pc_handle(_mk_pc(physiology="Immune to poison and disease"))
        _patch_resolve(monkeypatch, h)
        out = server._toxin_dispatch("poison_apply", target="Testa", poison=6)
        assert "immune" in out.lower()
        assert "save" not in out.lower()
        assert h["char"]["abilities"]["STR"]["current"] == 12

    def test_enemy_target_auto_resolves(self, monkeypatch):
        # Enemy handle, row 17, forced save failure: save detail surfaced +
        # greater effect as DM prose (enemies carry no condition records).
        h = _enemy_handle()
        _patch_resolve(monkeypatch, h)
        # dual-patch: mover->mover edge bypasses a server-only patch (slice 2)
        _pes_stub = lambda enemy, rng=None: (False, "d20=2+2=4 vs TN 15")
        monkeypatch.setattr(server, "_poison_enemy_save", _pes_stub)
        monkeypatch.setattr(substances, "_poison_enemy_save", _pes_stub)
        out = server._toxin_dispatch("poison_apply", target="Raider", poison=17)
        assert "d20=2+2=4 vs TN 15" in out
        assert "DM adjudicates" in out
        assert "greater" in out.lower()

    def test_resolve_rechecks_immunity(self, monkeypatch):
        # Review minor 1: a stray poison_resolve call on an immune PC must
        # short-circuit exactly like poison_apply (no save, no effect).
        h = _pc_handle(_mk_pc(physiology="Immune to poison and disease"))
        _patch_resolve(monkeypatch, h)
        out = server._toxin_dispatch("poison_resolve", target="Testa",
                                     save_total=14, poison=6)
        assert "immune" in out.lower()
        assert h["char"]["abilities"]["STR"]["current"] == 12

    def test_resolve_on_save_none_row_applies_not_resists(self, monkeypatch):
        # Review minor 1: resolving a pure-TOX row (no application save) must
        # apply the TD machinery, never report the poison "resisted".
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        out = server._toxin_dispatch("poison_resolve", target="Testa",
                                     save_total=15, poison=2)
        assert "resists" not in out.lower()
        assert "DC 18" in out  # d8 TOX -> CON save vs 10+8

    def test_inline_record_accepted(self, monkeypatch):
        # poison= an inline dict (the sap-dose shape) instead of a row number.
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        sap = {"name": "Toxic Sap dose", "effect_text": "d10 TOX damage",
               "engine_effects": {"save": "none", "lesser": None,
                                  "greater": {"kind": "tox", "tox_die": "d10"}}}
        out = server._toxin_dispatch("poison_apply", target="Testa", poison=sap)
        assert "POISON" in out
        assert "DC 20" in out  # d10 TOX -> CON save vs 10+10


# ---------------------------------------------------------------------------
# Task 4: toxin tool wiring (poison param + trigger-line/push discipline)
# ---------------------------------------------------------------------------

class TestToxinToolWiring:
    def test_tool_poison_apply_pushes_prefilled_resolve(self, monkeypatch):
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        out = server.affliction(kind="toxin", action="poison_apply", target="Testa", poison="6")
        assert "poison_resolve" in out
        assert f"TN {server.POISON_SAVE_TN}" in out
        assert "save_total=<roll>" in out

    def test_tool_accepts_inline_json_poison(self, monkeypatch):
        h = _pc_handle()
        _patch_resolve(monkeypatch, h)
        sap = ('{"name": "Toxic Sap dose", "effect_text": "d10 TOX damage", '
               '"engine_effects": {"save": "none", "lesser": null, '
               '"greater": {"kind": "tox", "tox_die": "d10"}}}')
        out = server.affliction(kind="toxin", action="poison_apply", target="Testa", poison=sap)
        assert "POISON" in out
        assert "DC 20" in out

    def test_docstring_trigger_line_mentions_poison(self):
        doc = server.affliction.__doc__  # poison docstring moved to the affliction face
        assert "poison_apply" in doc and "poison_resolve" in doc
        trigger = doc.strip().splitlines()[0]
        assert trigger.startswith("Reach for this WHEN")
        assert "poison" in doc.lower()


# ---------------------------------------------------------------------------
# Task 5: generate(action="poison") - single-roll d20 generator
# ---------------------------------------------------------------------------

class TestPoisonGenerator:
    def test_single_roll_reads_whole_row(self):
        out = server._generate_poison(rng=lambda a, b: 14)
        assert "Purple" in out and "Sand" in out.lower() or "sand" in out
        assert "Coated on weapon" in out
        assert "Blindness for d8 days / Permanent blindness" in out
        assert "d20=14" in out.lower()

    def test_roll_override(self):
        out = server._generate_poison(roll=20)
        assert "Octarine" in out

    def test_pushes_apply_call(self):
        out = server._generate_poison(roll=6)
        assert ('affliction(kind="toxin", action="poison_apply"' in out
                or "affliction(kind='toxin', action='poison_apply'" in out)

    def test_coat_row_pushes_coat_call(self):
        out = server._generate_poison(roll=14)
        assert "poison_coat" in out

    def test_tool_dispatch(self):
        out = server.generate(action="poison")
        assert "POISON" in out.upper()


# ---------------------------------------------------------------------------
# Task 6: weapon coating (R-B2b) - coat stamps, next successful hit fires.
# Combat harness copied from tests/test_reactive_triggers.py /
# tests/test_combat_attack.py (fixture idioms + sequenced rng).
# ---------------------------------------------------------------------------

from tests.test_combat_attack import _make_biological_enemy, _base_isolate  # noqa: E402


def _coated_weapon(coated=True):
    w = {"name": "Stinger Blade", "type": "melee weapon", "damage": "d6",
         "primary": True, "slots": 1}
    if coated:
        w["poison_coating"] = {
            "label": "Teal poison (Paralysis for d6 days)", "poison": 17}
    return w


def _roscar(weapon):
    return {
        "name": "Roscar",
        "hp": {"current": 20, "max": 20},
        "wound_table": "biological",
        "av": {"base": 10},
        "abilities": {"STR": {"current": 2, "base": 2},
                      "DEX": {"current": 2, "base": 2}},
        "inventory": {"carried": [weapon]},
        "special_traits": {},
    }


def _combat_chars(pc):
    return {"characters": {pc["name"].lower(): pc},
            "meta": {"campaign_day": 1}}


def _force_poison_enemy_save(monkeypatch, passed, detail="d20=2+2=4 vs TN 15"):
    # _poison_enemy_save moved to substances (slice 2); called via mover->mover edge,
    # so patch BOTH namespaces (server alias + substances home).
    monkeypatch.setattr(server, "_poison_enemy_save",
                        lambda enemy, rng=None: (passed, detail))
    monkeypatch.setattr(substances, "_poison_enemy_save",
                        lambda enemy, rng=None: (passed, detail))


class TestWeaponCoating:
    def test_coat_stamps_weapon_record(self, monkeypatch):
        w = _coated_weapon(coated=False)
        char = _mk_pc(inventory={"carried": [w]})
        h = _pc_handle(char)
        _patch_resolve(monkeypatch, h)
        out = server.affliction(kind="toxin", action="poison_coat", target="Testa",
                           weapon="Stinger", poison="14")
        assert "Purple" in out
        assert w["poison_coating"]["label"].startswith("Purple")
        assert "R-B2b" in out

    def test_coat_consumes_named_dose_item(self, monkeypatch):
        w = _coated_weapon(coated=False)
        dose = {"name": "Toxic Sap dose", "type": "poison", "slots": 0,
                "poison": {"effect_text": "d10 TOX damage",
                           "engine_effects": {"save": "none", "lesser": None,
                                              "greater": {"kind": "tox",
                                                          "tox_die": "d10"}}}}
        char = _mk_pc(inventory={"carried": [w, dose]})
        h = _pc_handle(char)
        _patch_resolve(monkeypatch, h)
        sap = ('{"name": "Toxic Sap dose", "effect_text": "d10 TOX damage", '
               '"engine_effects": {"save": "none", "lesser": null, '
               '"greater": {"kind": "tox", "tox_die": "d10"}}}')
        out = server.affliction(kind="toxin", action="poison_coat", target="Testa",
                           weapon="Stinger", poison=sap)
        assert "poison_coating" in str(w)
        assert dose not in char["inventory"]["carried"]
        assert "consumed" in out.lower()

    def test_hit_fires_and_clears(self, monkeypatch):
        w = _coated_weapon()
        pc = _roscar(w)
        enemy = _make_biological_enemy(hp=15, av=12)
        _base_isolate(monkeypatch, _combat_chars(pc), {"Raider": enemy})
        monkeypatch.setattr(server.random, "randint", lambda a, b: 15)  # hit
        monkeypatch.setattr(server, "_roll_stat_expr",
                            lambda expr, default=1: 3)
        _force_poison_enemy_save(monkeypatch, passed=False)
        out = server._combat_attack("Roscar", "Stinger", "Raider")
        assert "HIT" in out
        assert "POISON" in out
        assert "d20=2+2=4 vs TN 15" in out
        assert "poison_coating" not in w
        assert '"poison_coating_fired"' in out

    def test_miss_does_not_consume(self, monkeypatch):
        w = _coated_weapon()
        pc = _roscar(w)
        enemy = _make_biological_enemy(hp=15, av=12)
        _base_isolate(monkeypatch, _combat_chars(pc), {"Raider": enemy})
        monkeypatch.setattr(server.random, "randint", lambda a, b: 5)  # 7 < 12
        out = server._combat_attack("Roscar", "Stinger", "Raider")
        assert "MISS" in out
        assert "poison_coating" in w
        assert "POISON" not in out

    def test_second_hit_clean(self, monkeypatch):
        w = _coated_weapon()
        pc = _roscar(w)
        enemy = _make_biological_enemy(hp=30, av=12)
        _base_isolate(monkeypatch, _combat_chars(pc), {"Raider": enemy})
        monkeypatch.setattr(server.random, "randint", lambda a, b: 15)
        monkeypatch.setattr(server, "_roll_stat_expr",
                            lambda expr, default=1: 3)
        _force_poison_enemy_save(monkeypatch, passed=False)
        first = server._combat_attack("Roscar", "Stinger", "Raider")
        assert "POISON" in first
        second = server._combat_attack("Roscar", "Stinger", "Raider")
        assert "HIT" in second
        assert "POISON" not in second

    def test_consume_persists_pop_despite_ambiguous_names(self, monkeypatch):
        # Adversarial M1: two carried items whose names substring-collide
        # ("Knife" / "Bone Knife"). The disk pop must still land - a spent
        # dose surviving on disk would re-fire every hit (R-B2b violation).
        coating = {"label": "Teal poison (Paralysis for d6 days)", "poison": 17}
        disk_w = {"name": "Knife", "type": "melee weapon", "damage": "d6",
                  "poison_coating": dict(coating)}
        other = {"name": "Bone Knife", "type": "melee weapon", "damage": "d4"}
        disk_char = {"name": "Dual",
                     "inventory": {"carried": [disk_w, other]}}
        data = {"characters": {"dual": disk_char}, "meta": {"campaign_day": 1}}
        monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        # the resolver's in-call copy is a SEPARATE object (fresh disk read)
        in_call = {"name": "Knife", "type": "melee weapon", "damage": "d6",
                   "poison_coating": dict(coating)}
        got, warn = server._consume_weapon_coating("Dual", in_call)
        assert got == coating
        assert warn is None
        assert "poison_coating" not in disk_w

    def test_consume_warns_when_disk_pop_fails(self, monkeypatch):
        # Adversarial M1: if no disk record can be matched, surface a loud
        # warning instead of silently letting the coating survive.
        coating = {"label": "Teal poison (Paralysis for d6 days)", "poison": 17}
        disk_char = {"name": "Dual", "inventory": {"carried": []}}
        data = {"characters": {"dual": disk_char}, "meta": {"campaign_day": 1}}
        monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        in_call = {"name": "Knife", "poison_coating": dict(coating)}
        got, warn = server._consume_weapon_coating("Dual", in_call)
        assert got == coating
        assert warn and "WARNING" in warn

    def test_recoat_surfaces_replaced_dose(self, monkeypatch):
        # Adversarial m1: coating an already-coated weapon must say so.
        w = _coated_weapon()  # already Teal-coated
        char = _mk_pc(inventory={"carried": [w]})
        h = _pc_handle(char)
        _patch_resolve(monkeypatch, h)
        out = server.affliction(kind="toxin", action="poison_coat", target="Testa",
                           weapon="Stinger", poison="14")
        assert "REPLACED" in out
        assert "Teal" in out
        assert w["poison_coating"]["label"].startswith("Purple")

    def test_crit_consumes_one_dose_only(self, monkeypatch):
        w = _coated_weapon()
        pc = _roscar(w)
        enemy = _make_biological_enemy(hp=30, av=12)
        _base_isolate(monkeypatch, _combat_chars(pc), {"Raider": enemy})
        monkeypatch.setattr(server.random, "randint", lambda a, b: 20)  # crit
        monkeypatch.setattr(server, "_roll_stat_expr",
                            lambda expr, default=1: 3)
        _force_poison_enemy_save(monkeypatch, passed=False)
        out = server._combat_attack("Roscar", "Stinger", "Raider")
        assert "CRIT" in out
        assert out.count("**POISON**") == 1
        assert "poison_coating" not in w


# ---------------------------------------------------------------------------
# Task 7: daily-use runner + sap dose minting (R-B2c)
# ---------------------------------------------------------------------------

def _sap_daily():
    return {
        "name": "Harvest Toxic Sap",
        "note": "1 dose of poisonous (d10 TOX) sap per day (Bloomboon #10)",
        "engine_effect": {"mint_item": {
            "name": "Toxic Sap dose",
            "type": "poison",
            "poison": {"form": "Liquid",
                       "delivery": "ingested or coated on weapon",
                       "effect_text": "d10 TOX damage",
                       "engine_effects": {"save": "none", "lesser": None,
                                          "greater": {"kind": "tox",
                                                      "tox_die": "d10"}}},
        }}}


def _count_doses(char, name="Toxic Sap dose"):
    return len([i for c in char.get("inventory", {}).values()
                for i in c if isinstance(i, dict) and i.get("name") == name])


class TestDailyUse:
    def test_use_stamps_day_and_mints_item(self):
        char = _mk_pc()
        char["special_traits"] = {"daily_uses": [_sap_daily()]}
        out = server._character_use_daily(char, "Harvest Toxic Sap", day=104)
        du = char["special_traits"]["daily_uses"][0]
        assert du["last_used_day"] == 104
        assert _count_doses(char) == 1
        assert "poison_coat" in out or "poison_apply" in out  # push line

    def test_second_use_same_day_refused(self):
        char = _mk_pc()
        char["special_traits"] = {"daily_uses": [_sap_daily()]}
        server._character_use_daily(char, "Harvest Toxic Sap", day=104)
        out = server._character_use_daily(char, "Harvest Toxic Sap", day=104)
        assert "already used" in out.lower()
        assert _count_doses(char) == 1

    def test_next_day_available_again(self):
        char = _mk_pc()
        char["special_traits"] = {"daily_uses": [_sap_daily()]}
        server._character_use_daily(char, "Harvest Toxic Sap", day=104)
        out = server._character_use_daily(char, "Harvest Toxic Sap", day=105)
        assert "already used" not in out.lower()
        assert _count_doses(char) == 2

    def test_unknown_daily_listed(self):
        char = _mk_pc()
        char["special_traits"] = {"daily_uses": [_sap_daily()]}
        out = server._character_use_daily(char, "Photosynthesise", day=104)
        assert "no daily use named" in out.lower()
        assert "Harvest Toxic Sap" in out

    def test_no_engine_effect_still_stamps(self):
        # C2's existing data-only entries keep working: stamp + note only.
        char = _mk_pc()
        char["special_traits"] = {"daily_uses": [{
            "name": "Prismatic Display",
            "note": "Dazzle nearby creatures once per day (DM adjudicates)."}]}
        out = server._character_use_daily(char, "Prismatic Display", day=104)
        assert char["special_traits"]["daily_uses"][0]["last_used_day"] == 104
        assert "Dazzle" in out
        assert _count_doses(char, "Prismatic Display") == 0
