"""E2 Task 2: diseases.py catalog integrity, builders (validate through
normalize_record), and species susceptibility."""
import pytest
import diseases as dz
import conditions as cnd


SIX = ["Brain Coral", "Wrathworms", "Jellybones", "Hivey Hump",
       "Labyrinth Pox", "Lumenrot"]


def test_all_six_present():
    # E2 original six organic diseases (E3 expands to 12 total; see test_twelve_total_entries)
    for name in SIX:
        assert name in dz.DISEASES, name


def test_tn_is_ten_plus_virulence():
    for name, d in dz.DISEASES.items():
        assert d["tn"] == 10 + d["virulence"], name
        assert 1 <= d["virulence"] <= 5, name


def test_every_entry_has_prose_riders():
    for name, d in dz.DISEASES.items():
        assert d.get("vector"), name
        assert d.get("cure"), name
        assert d.get("symptoms"), name


def test_build_validates_through_normalize_record():
    for name in SIX:
        rec, push, err = dz.build_disease_record(name, day=100)
        assert err == "", f"{name}: {err}"
        assert rec is not None and push
        # round-trip the minted record through the validator: it must survive
        rec2, verr = cnd.normalize_record(rec, day=100)
        assert verr == "", f"{name} re-validate: {verr}"
        assert rec["cause"] == "disease"
        v = dz.DISEASES[name]["virulence"]
        assert rec["save_to_end"] == {"ability": "CON", "dc": 10 + v}


def test_build_unknown_disease_errors():
    rec, push, err = dz.build_disease_record("Spicy Flu", day=100)
    assert rec is None and push is None and err


def test_jellybones_week_ability_tick():
    rec, _, err = dz.build_disease_record("Jellybones", day=50)
    assert err == ""
    assert rec["tick"]["cadence"] == "week"
    assert rec["tick"]["abilities"] == {"STR": "d4", "CON": "d4"}


def test_hivey_hump_flat_ego_day_tick():
    rec, _, err = dz.build_disease_record("Hivey Hump", day=50)
    assert err == ""
    assert rec["tick"]["cadence"] == "day"
    assert rec["tick"]["abilities"] == {"EGO": "1"}


def test_labyrinth_pox_max_hp_and_death_clock():
    rec, _, err = dz.build_disease_record("Labyrinth Pox", day=50)
    assert err == ""
    assert rec["tick"] == {"cadence": "week", "max_hp": "d8"}
    assert rec["on_max_hp_zero"] == {"death_in_days": 3}


def test_lumenrot_save_gated_con_tick():
    rec, _, err = dz.build_disease_record("Lumenrot", day=50)
    assert err == ""
    assert rec["tick"]["cadence"] == "day"
    assert rec["tick"]["abilities"] == {"CON": "1"}
    assert rec["tick"]["save"] == {"ability": "CON", "dc": 15}


def test_wrathworms_no_tick():
    rec, _, err = dz.build_disease_record("Wrathworms", day=50)
    assert err == "" and "tick" not in rec


def test_brain_coral_on_apply_trade():
    d = dz.DISEASES["Brain Coral"]
    assert d["on_apply"]["roll"] == "d8"
    assert d["on_apply"]["ability_down"] == "STR"
    assert d["on_apply"]["ability_up"] == "PSY"


def test_susceptibility_synth_and_lithling_immune():
    assert dz.disease_susceptible_pc({"species": "True-kin"}) is True
    assert dz.disease_susceptible_pc({"species": "Cacogen"}) is True
    assert dz.disease_susceptible_pc({"species": "Synthetic"}) is False
    assert dz.disease_susceptible_pc({"species": "Lithling"}) is False
    assert dz.disease_susceptible_pc({"species": "Lithing"}) is False   # extraction typo stem
    assert dz.disease_susceptible_pc({}) is True


def test_ascii_only_strings():
    import diseases
    src = open(diseases.__file__, encoding="utf-8").read()
    assert all(ord(ch) < 128 for ch in src), "diseases.py must be ASCII-only"


# --- E3 Task 1: nanomachine family entries ---

NANO = ["Goldencough", "Janus Lenses", "Usurper Arm", "Dreamcage",
        "Fabricator Stoma", "The Gitch"]


def test_twelve_total_entries():
    assert len(dz.DISEASES) == 12
    for n in NANO:
        assert n in dz.DISEASES, n


def test_family_field_on_every_entry():
    for name, d in dz.DISEASES.items():
        fam = d.get("family")
        assert fam in ("organic", "nanomachine"), name
    for n in NANO:
        assert dz.DISEASES[n]["family"] == "nanomachine", n
    # the original six stay organic
    for n in ["Brain Coral", "Wrathworms", "Jellybones", "Hivey Hump",
              "Labyrinth Pox", "Lumenrot"]:
        assert dz.DISEASES[n]["family"] == "organic", n


def test_nano_tn_is_ten_plus_virulence():
    expected = {"Goldencough": (1, 11), "Janus Lenses": (2, 12),
                "Usurper Arm": (2, 12), "Dreamcage": (3, 13),
                "Fabricator Stoma": (4, 14), "The Gitch": (5, 15)}
    for n, (v, tn) in expected.items():
        assert dz.DISEASES[n]["virulence"] == v, n
        assert dz.DISEASES[n]["tn"] == tn, n


def test_nano_slots_fields():
    assert dz.DISEASES["Goldencough"]["slots"] == ["CON"]
    assert dz.DISEASES["Janus Lenses"]["slots"] == ["PSY"]
    assert dz.DISEASES["Usurper Arm"]["slots"] == ["DEX", "EGO"]
    assert dz.DISEASES["Dreamcage"]["slots"] == ["INT", "PSY"]
    assert dz.DISEASES["Fabricator Stoma"]["slots"] == ["STR", "CON"]
    assert dz.DISEASES["The Gitch"]["slots"] == "d6"


def test_dreamcage_source_note_present():
    d = dz.DISEASES["Dreamcage"]
    assert "source" in d and "R-E3a" in d["source"]


def test_gitch_flag_and_tick():
    d = dz.DISEASES["The Gitch"]
    assert d.get("gitch") is True
    assert d["tick"]["cadence"] == "day"
    assert d["tick"]["save"] == {"ability": "CON", "dc": 15}


def test_janus_hp_regain_half_effect():
    assert dz.DISEASES["Janus Lenses"]["effects"]["hp_regain_half"] is True


def test_stoma_double_rations_effect():
    assert dz.DISEASES["Fabricator Stoma"]["effects"]["double_rations"] is True


def test_dreamcage_no_hp_regain_and_psy_tick():
    d = dz.DISEASES["Dreamcage"]
    assert d["effects"]["no_hp_regain"] is True
    assert d["tick"]["cadence"] == "day"
    assert d["tick"]["abilities"] == {"PSY": "1"}


def test_goldencough_coughing_fit_flag_and_on_apply():
    d = dz.DISEASES["Goldencough"]
    assert d.get("coughing_fit") is True
    assert d["on_apply"]["roll"] == "d6"
    assert d["on_apply"]["ability_down"] == "CON"
    assert "ability_up" not in d["on_apply"]   # no gain side


# --- build_disease_record: nanomachine cause + Gitch rolled slot ---

def test_nano_build_sets_cause_nanomachine():
    for n in NANO:
        rec, push, err = dz.build_disease_record(n, day=100)
        assert err == "", f"{n}: {err}"
        assert rec["cause"] == "nanomachine", n
        v = dz.DISEASES[n]["virulence"]
        assert rec["save_to_end"] == {"ability": "CON", "dc": 10 + v}
        rec2, verr = cnd.normalize_record(rec, day=100)
        assert verr == "", f"{n} re-validate: {verr}"


def test_organic_build_keeps_cause_disease():
    rec, _, err = dz.build_disease_record("Jellybones", day=100)
    assert err == "" and rec["cause"] == "disease"


def test_gitch_build_rolls_slot(monkeypatch):
    # d6 -> 3 maps to CON (1=STR,2=DEX,3=CON,4=INT,5=PSY,6=EGO)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 3)
    rec, push, err = dz.build_disease_record("The Gitch", day=100)
    assert err == ""
    assert rec["tick"]["abilities"] == {"CON": "1"}
    assert rec["tick"]["save"] == {"ability": "CON", "dc": 15}
    assert rec.get("gitch") is True
    assert "CON" in " ".join(push)   # the rolled slot is surfaced


def test_nano_resist_dis_synth_species():
    assert dz.nano_resist_dis({"species": "Synthetic"}) is True
    assert dz.nano_resist_dis({"species": "Lithling"}) is True


def test_nano_resist_dis_installed_augment():
    char = {"species": "True-kin",
            "augmentations": {"DEX": {"name": "Hyper Tendons"}}}
    assert dz.nano_resist_dis(char) is True


def test_nano_resist_dis_none_for_plain_biological():
    assert dz.nano_resist_dis({"species": "True-kin"}) is False
    assert dz.nano_resist_dis({"species": "True-kin",
                               "augmentations": {"DEX": None}}) is False
    assert dz.nano_resist_dis({}) is False


def test_susceptibility_flip_synth_can_catch_nanomachine():
    # nanomachines infect ALL types; the organic immunity does NOT bar them
    synth = {"species": "Synthetic"}
    assert dz.disease_susceptible_pc(synth, family="nanomachine") is True
    # organic still bars synth/lith
    assert dz.disease_susceptible_pc(synth, family="organic") is False
    assert dz.disease_susceptible_pc(synth) is False   # default organic


def test_gitch_record_carries_gitch_flag_through_normalize():
    rec, _, err = dz.build_disease_record("The Gitch", day=5)
    assert err == ""
    # gitch flag must survive on the stored record (normalize keeps unknown? NO -
    # build_disease_record stamps it AFTER normalize). Assert it is present.
    assert rec["gitch"] is True


def test_usurper_arm_locale_rolled_into_note(monkeypatch):
    monkeypatch.setattr(dz, "_roll_d6", lambda: 5)
    rec, push, err = dz.build_disease_record("Usurper Arm", day=100)
    assert not err
    assert "protruding from the back" in rec["note"]
    assert any("protruding from the back" in p for p in push)


def test_stoma_extruded_object_rolled_into_note(monkeypatch):
    monkeypatch.setattr(dz, "_roll_d6", lambda: 6)
    rec, push, err = dz.build_disease_record("Fabricator Stoma", day=100)
    assert not err
    assert "gaming dice" in rec["note"]


def test_nano_resist_dis_synthetic_type_flag():
    assert dz.nano_resist_dis({"species": "True-kin", "synthetic_type": True}) is True
    assert dz.nano_resist_dis({"species": "True-kin"}) is False
