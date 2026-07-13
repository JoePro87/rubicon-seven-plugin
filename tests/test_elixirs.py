"""B3 Elixirs - certified table, drink action, until_turn substrate.

Spec: docs/superpowers/specs/2026-06-13-b3-elixirs-design.md
Book: CH preview PDF pdfplumber pp.59-60 (printed pp.53-54).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
import engine_core


class TestElixirTablePins:
    def test_forty_rows(self):
        assert len(server.VAARNISH_ELIXIRS) == 40

    def test_band_coverage_exact(self):
        """Every d100 value 1-100 maps to exactly one row (R-B3a fixes the
        book's overlapping 43-45/44-46 typo: even split 43-44 / 45-46)."""
        seen = {}
        for idx, row in server.VAARNISH_ELIXIRS.items():
            lo, hi = row["d100"]
            for v in range(lo, hi + 1):
                assert v not in seen, f"{v} claimed by rows {seen[v]} and {idx}"
                seen[v] = idx
        assert sorted(seen) == list(range(1, 101))

    def test_r_b3a_band_fix(self):
        assert server.VAARNISH_ELIXIRS[15]["name"] == "Glittercough Tonic"
        assert server.VAARNISH_ELIXIRS[15]["d100"] == (43, 44)
        assert server.VAARNISH_ELIXIRS[16]["name"] == "Growth Serum"
        assert server.VAARNISH_ELIXIRS[16]["d100"] == (45, 46)

    def test_verbatim_spot_pins(self):
        t = server.VAARNISH_ELIXIRS
        assert t[1]["name"] == "Babel Beer" and t[1]["pot"] == 1
        assert t[1]["component"] == "A sapient creature's tongue"
        assert t[18]["name"] == "Death Draught" and t[18]["pot"] == 3
        # Table index 30 = Lazarus Tonic (29 = Biothermal). The plan's pin said
        # index 29 but its own table + Tasks 7/8/9 all use 30 for Lazarus /
        # 29 for Biothermal / 31 for Kalotoxin -- index 30 is the consistent one.
        assert t[30]["name"] == "Lazarus Tonic" and t[30]["pot"] == 4
        assert t[40]["name"] == "Immortality Injector" and t[40]["d100"] == (99, 100)
        assert t[40]["pot"] == 5

    def test_r_b3b_pupeteer_duration(self):
        row = server.VAARNISH_ELIXIRS[19]
        assert row["name"] == "Pupeteer Potion"
        assert row["engine_effects"]["duration"] == {"turns": 4}

    def test_every_row_has_engine_effects_kind(self):
        KINDS = {"prose_only", "condition", "av_bonus", "ability_mod",
                 "hp_regen", "hp_set_zero", "hp_floor", "resurrection",
                 "save_fork", "gift_mint", "sheet_surgery", "follower_mint"}
        for idx, row in server.VAARNISH_ELIXIRS.items():
            ee = row["engine_effects"]
            assert ee["kind"] in KINDS, f"row {idx}: bad kind {ee.get('kind')}"
            assert isinstance(row["effect_text"], str) and row["effect_text"]
            assert row["pot"] in (1, 2, 3, 4, 5)
            assert isinstance(row.get("application"), str)


import conditions as cnd


class TestUntilTurnRecords:
    def test_normalize_preserves_until_turn_and_map(self):
        rec, err = cnd.normalize_record(
            {"name": "Plated", "until_turn": 9, "turn_map": "rust-vault",
             "until_day": 141}, day=140)
        assert err == ""
        assert rec["until_turn"] == 9 and rec["turn_map"] == "rust-vault"
        assert rec["until_day"] == 141

    def test_until_turn_must_be_int(self):
        rec, err = cnd.normalize_record(
            {"name": "Plated", "until_turn": "soon"}, day=140)
        assert rec is None and "until_turn" in err

    def test_revert_block_preserved(self):
        rec, err = cnd.normalize_record(
            {"name": "Giant Growth", "until_turn": 5, "turn_map": "m",
             "revert": {"abilities": {"STR": 12}, "hp_max": 20, "hp_current": 14}},
            day=140)
        assert err == ""
        assert rec["revert"] == {"abilities": {"STR": 12}, "hp_max": 20, "hp_current": 14}

    def test_derived_av_bonus_preserved(self):
        rec, err = cnd.normalize_record(
            {"name": "Plated", "derived_effects": {"av_bonus": 5}}, day=140)
        assert err == ""
        assert rec["derived_effects"]["av_bonus"] == 5


class TestTurnExpirySweep:
    def test_pure_expire_clears_and_reports(self):
        char = {"name": "Vela", "conditions": [
            {"name": "Plated (Plating Potion)", "since_day": 140,
             "until_turn": 8, "turn_map": "rust-vault",
             "derived_effects": {"av_bonus": 5}},
            {"name": "Deprived", "since_day": 139},
        ]}
        cleared = cnd.expire_turn_conditions(char, "rust-vault", current_turn=9)
        assert [c["name"] for c in cleared] == ["Plated (Plating Potion)"]
        assert [c["name"] for c in char["conditions"]] == ["Deprived"]

    def test_pure_expire_other_map_untouched(self):
        char = {"name": "Vela", "conditions": [
            {"name": "Plated", "until_turn": 8, "turn_map": "other-vault"}]}
        assert cnd.expire_turn_conditions(char, "rust-vault", 99) == []
        assert len(char["conditions"]) == 1

    def test_pure_expire_revert_restores_abilities(self):
        char = {"name": "Vela", "abilities": {"STR": 17, "EGO": 3},
                "hp": {"current": 33, "max": 40}, "conditions": [
            {"name": "Giant Growth", "until_turn": 5, "turn_map": "m",
             "revert": {"abilities": {"STR": 12, "EGO": 8},
                        "hp_max": 20, "hp_current": 14}}]}
        cleared = cnd.expire_turn_conditions(char, "m", 5)
        assert len(cleared) == 1
        assert char["abilities"] == {"STR": 12, "EGO": 8}
        assert char["hp"]["max"] == 20
        assert char["hp"]["current"] == 14  # min(current, revert) -- never a heal

    def test_map_hook_fires_on_advance_turns(self):
        """MapSystem.advance_turns calls the registered turn_hook with
        (map_name, current_turn) and appends returned lines."""
        from map_system import MapSystem
        ms = MapSystem.__new__(MapSystem)   # no disk IO
        ms.turn_hook = None
        calls = []
        ms.turn_hook = lambda map_name, turn: calls.append((map_name, turn)) or []
        state = {"map_name": "rust-vault", "current_turn": 7,
                 "exploration_log": [], "encounters_rolled": [],
                 "noise_level": "standard"}
        ms.advance_turns(state, 1)
        assert calls == [("rust-vault", 8)]


class TestConditionAvBonus:
    def test_defender_av_adds_condition_av(self, monkeypatch):
        # _defender_av reads char["av"] (a {"base": N} dict) via
        # _load_characters() -> (data, err) with nested "characters".
        char = {"name": "Vela", "av": {"base": 12}, "wounds": [],
                "conditions": [{"name": "Plated (Plating Potion)",
                                "derived_effects": {"av_bonus": 5}}]}
        monkeypatch.setattr(server, "_load_characters",
                            lambda: ({"meta": {}, "characters": {"vela": char}}, None))
        assert server._defender_av("Vela") == 17


class TestGenerateElixir:
    def test_forced_roll_hits_band(self):
        out = server._generate_elixir(forced_roll=51)
        assert "Death Draught" in out and "POT 3" in out

    def test_pushes_drink_call(self):
        out = server._generate_elixir(forced_roll=40)
        assert 'character(action="drink_elixir"' in out

    def test_r_b3a_bands_live(self):
        assert "Glittercough" in server._generate_elixir(forced_roll=44)
        assert "Growth Serum" in server._generate_elixir(forced_roll=45)


class TestDrinkElixirCore:
    def _vela(self):
        return {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20},
                "abilities": {"STR": 10, "EGO": 8}, "conditions": [],
                "inventory": [{"name": "Plating Potion dose"}]}

    def test_physiology_guard_synth_refused(self, monkeypatch):
        char = self._vela(); char["species"] = "Synth"
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        out = server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        assert "cannot drink" in out.lower()

    def test_topical_bypasses_guard(self, monkeypatch):
        char = self._vela(); char["species"] = "Lithling"
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        out = server._character_drink_elixir(char_key="vela", elixir=21, day=140)
        assert "cannot drink" not in out.lower()   # Skulk Salve is topical

    def test_condition_applied_with_turn_stamp_in_vault(self, monkeypatch):
        char = self._vela()
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn",
                            lambda: ("rust-vault", 7))
        server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        cond = char["conditions"][0]
        assert cond["until_turn"] == 13          # 7 + 6 ET (Plating)
        assert cond["turn_map"] == "rust-vault"
        assert cond["until_day"] == 141          # next-day failsafe
        assert cond["derived_effects"]["av_bonus"] == 5

    def test_outside_vault_gets_note_and_failsafe(self, monkeypatch):
        char = self._vela()
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        cond = char["conditions"][0]
        assert "until_turn" not in cond
        assert "Exploration Turns" in cond.get("note", "")
        assert cond["until_day"] == 141

    def test_dose_consumed_from_inventory(self, monkeypatch):
        char = self._vela()
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        assert char["inventory"] == []
        assert "dose consumed" in out.lower()

    def test_no_dose_proceeds_loudly(self, monkeypatch):
        char = self._vela(); char["inventory"] = []
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        assert "no matching dose" in out.lower()

    def test_ability_mod_stamps_revert(self, monkeypatch):
        char = self._vela()
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        server._character_drink_elixir(char_key="vela", elixir=11, day=140)
        assert char["abilities"]["STR"] == 15 and char["abilities"]["EGO"] == 3
        cond = char["conditions"][0]
        assert cond["revert"]["abilities"] == {"STR": 10, "EGO": 8}

    def test_growth_serum_doubles_and_reverts_cleanly(self, monkeypatch):
        char = self._vela(); char["hp"]["current"] = 14
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character",
                            lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn",
                            lambda: ("m", 0))
        server._character_drink_elixir(char_key="vela", elixir=16, day=140)
        assert char["hp"]["max"] == 40 and char["hp"]["current"] == 28
        assert char["abilities"]["STR"] == 20
        cleared = cnd.expire_turn_conditions(char, "m", 4)
        assert len(cleared) == 1
        assert char["hp"]["max"] == 20 and char["hp"]["current"] == 14
        assert char["abilities"]["STR"] == 10


class TestDangerousRows:
    def test_death_draught_zero_hp_wound_fires(self, monkeypatch):
        char = {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20}, "wound_table": "biological",
                "abilities": {}, "conditions": [], "inventory": [],
                "wounds": []}
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=18, day=140)
        assert char["hp"]["current"] == 0
        assert "wound" in out.lower()    # R-B3e: wound ladder fires

    def test_immortality_floor_clamps_damage(self):
        char = {"name": "Vela", "hp": {"current": -15, "max": 20},
                "conditions": [
            {"name": "Deathless (Immortality Injector)", "hp_floor": -19}]}
        assert server._elixir_hp_floor(char) == -19
        char2 = {"name": "Vela", "hp": {"current": -15, "max": 20},
                 "conditions": []}
        assert server._elixir_hp_floor(char2) is None

    def test_kalotoxin_pc_routes_to_gated_death(self, monkeypatch):
        calls = []
        monkeypatch.setattr(server, "_death_gate",
                            lambda key, char, data, **kw:
                            calls.append(kw.get("cause")) or (True, []))
        monkeypatch.setattr(engine_core, "_death_gate", server._death_gate)
        char = {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20},
                "abilities": {}, "conditions": [], "inventory": [], "wounds": []}
        data = {"vela": char}
        monkeypatch.setattr(server, "_load_characters", lambda: data)
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        server._character_drink_elixir(char_key="vela", elixir=31, day=140,
                                       target="Vela")
        assert calls and "Kalotoxin" in calls[0]

    def test_pupeteer_pc_target_two_phase(self, monkeypatch):
        char = {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20},
                "abilities": {}, "conditions": [], "inventory": [], "wounds": []}
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        # phase 1: no save_total -> instructs the PC target to roll EGO
        out = server._character_drink_elixir(char_key="vela", elixir=19,
                                             day=140, target="Vela")
        assert "EGO" in out and "save_total" in out


class TestLazarusTonic:
    def test_catalog_has_lazarus(self):
        spec = cnd.RESURRECTION_CATALOG["lazarus_tonic"]
        assert spec["label"] == "Lazarus Tonic"
        assert spec["timer"] is None          # immediate
        assert "one Level" in spec["reminder"]

    def test_drink_on_living_pc_refused(self, monkeypatch):
        char = {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20},
                "abilities": {}, "conditions": [], "inventory": [], "wounds": []}
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=30,
                                             day=140, target="Vela")
        assert "dead" in out.lower()          # corpse-only

    def test_synthetic_corpse_refused(self):
        corpse = {"name": "Unit-7", "species": "Synth",
                  "hp": {"current": -20, "max": 15}}
        ok, why = server._lazarus_eligible(corpse)
        assert not ok and "biological" in why.lower()


class TestPushKinds:
    def _drink(self, idx, monkeypatch):
        char = {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20},
                "abilities": {}, "conditions": [], "inventory": [], "wounds": []}
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        return char, server._character_drink_elixir(char_key="vela",
                                                    elixir=idx, day=140)

    def test_gift_mint_pushes_gift_tool(self, monkeypatch):
        char, out = self._drink(38, monkeypatch)        # Recursive Infusion
        assert "gift(" in out and "Recursive Gaze" in out

    def test_temporary_gift_mints_expiry_condition(self, monkeypatch):
        char, out = self._drink(29, monkeypatch)        # Biothermal
        assert any("Biothermal" in c["name"] for c in char["conditions"])
        assert char["conditions"][0]["until_day"] == 141

    def test_sheet_surgery_pushes(self, monkeypatch):
        char, out = self._drink(34, monkeypatch)        # Autarch's Ambrosia
        assert "+1" in out and "Ability" in out

    def test_follower_mint_rolls_count_and_pushes(self, monkeypatch):
        char, out = self._drink(28, monkeypatch)        # Broodling Broth
        assert "Broodling" in out and "Lvl 0" in out


class TestDayFailsafeParity:
    def test_day_sweep_applies_revert(self):
        """The until_day sweep must run the SAME revert logic as the turn
        sweep -- a Growth Serum that outlives its vault must restore stats
        at the day failsafe, not leak doubled STR forever."""
        char = {"name": "Vela", "abilities": {"STR": 20},
                "hp": {"current": 28, "max": 40}, "conditions": [
                    {"name": "Giant Growth", "until_day": 140,
                     "revert": {"abilities": {"STR": 10},
                                "hp_max": 20, "hp_current": 14}}]}
        cleared = cnd.expire_day_conditions(char, new_day=141)
        assert [c["name"] for c in cleared] == ["Giant Growth"]
        assert char["abilities"]["STR"] == 10
        assert char["hp"]["max"] == 20 and char["hp"]["current"] == 14


import pytest


class TestDeathlessGateGuard:
    """Adversarial CRITICAL: _death_gate must honour the Immortality floor.
    Four death writers snap hp.current=-20 then call _death_gate directly,
    bypassing the _check_death_conditions short-circuit and the combat clamp.
    One guard at the top of _death_gate closes all four leaks."""

    def _deathless(self):
        return {"name": "Vela", "species": "Neobloom",
                "hp": {"current": -20, "max": 20}, "abilities": {},
                "conditions": [{"name": "Deathless (Immortality Injector)",
                                "hp_floor": -19}], "wounds": []}

    @pytest.mark.parametrize("cause", ["poison", "starvation", "thirst",
                                       "disease", "Gitchghast transform"])
    def test_death_gate_refuses_while_deathless(self, cause):
        char = self._deathless()
        allowed, lines = server._death_gate("vela", char, None, cause=cause)
        assert allowed is False                       # death is refused
        assert char["hp"]["current"] == -19           # clamped up to the floor
        assert any("deathless" in ln.lower() for ln in lines)

    def test_poison_death_site_survives_while_deathless(self):
        char = self._deathless()
        handle = {"kind": "pc", "key": "vela", "char": char, "data": None}
        out = server._poison_death(handle)
        text = "\n".join(out)
        assert "DIES of poison" not in text
        assert char["hp"]["current"] == -19           # held at the floor
        assert "deathless" in text.lower()

    def test_non_deathless_death_still_stands(self):
        # Guard must NOT block ordinary deaths (no floor condition present).
        char = {"name": "Kess", "species": "True-kin",
                "hp": {"current": -20, "max": 20}, "abilities": {},
                "conditions": [], "wounds": []}
        allowed, lines = server._death_gate("kess", char, None, cause="poison")
        assert allowed is True


class TestFloorExpiryWindow:
    """Adversarial HIGH: a sub-floor HP written while Deathless must be raised
    to the floor when Deathless wears off, or it auto-kills on the next sweep."""

    def test_day_expiry_raises_subfloor_hp(self):
        char = {"name": "Vela", "hp": {"current": -25, "max": 20},
                "conditions": [
            {"name": "Deathless (Immortality Injector)", "hp_floor": -19,
             "until_day": 140}]}
        cleared = cnd.expire_day_conditions(char, new_day=141)
        assert [c["name"] for c in cleared] == ["Deathless (Immortality Injector)"]
        assert char["hp"]["current"] == -19           # raised to the floor
        # ... and the PC is NOT dead
        is_dead, _ = server._check_death_conditions(char)
        assert is_dead is False

    def test_turn_expiry_raises_subfloor_hp(self):
        char = {"name": "Vela", "hp": {"current": -30, "max": 20},
                "conditions": [
            {"name": "Deathless (Immortality Injector)", "hp_floor": -19,
             "until_turn": 5, "turn_map": "m"}]}
        cleared = cnd.expire_turn_conditions(char, "m", 5)
        assert len(cleared) == 1
        assert char["hp"]["current"] == -19

    def test_update_hp_clamps_while_floor_active(self, monkeypatch):
        char = {"name": "Vela", "hp": {"current": 5, "max": 20},
                "conditions": [
            {"name": "Deathless (Immortality Injector)", "hp_floor": -19}]}
        data = {"meta": {}, "characters": {"vela": char}}
        monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        server._character_update_hp("Vela", -25)
        assert char["hp"]["current"] == -19           # clamped, not -25


class TestDoseSubstringCollision:
    """Adversarial MINOR: 'Death Draught' (#18) must not consume a carried
    'False Death Draught dose' (#7). Match on a word boundary, not a bare
    substring."""

    def _char_with(self, dose_name):
        return {"name": "Vela", "species": "Neobloom",
                "hp": {"current": 20, "max": 20}, "abilities": {},
                "conditions": [], "wounds": [],
                "inventory": [{"name": dose_name}]}

    def test_death_draught_does_not_eat_false_death_draught(self, monkeypatch):
        char = self._char_with("False Death Draught dose")
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=18, day=140)
        # the wrong dose survives; the drink reports no matching dose
        assert char["inventory"] == [{"name": "False Death Draught dose"}]
        assert "no matching dose" in out.lower()

    def test_false_death_draught_consumes_its_own_dose(self, monkeypatch):
        char = self._char_with("False Death Draught dose")
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=7, day=140)
        assert char["inventory"] == []
        assert "dose consumed" in out.lower()

    def test_plain_dose_suffix_still_matches(self, monkeypatch):
        char = self._char_with("Plating Potion dose")
        monkeypatch.setattr(server, "_load_characters", lambda: {"vela": char})
        monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
        monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
        out = server._character_drink_elixir(char_key="vela", elixir=14, day=140)
        assert char["inventory"] == []
        assert "dose consumed" in out.lower()
