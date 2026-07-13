# tests/test_wounds_pure.py
import wounds as w


# --- Data integrity vs the book (extraction batch_03 p.38-39) ---

def test_biological_table_structured_fields():
    assert w.BIOLOGICAL_WOUNDS[0]["special"] == "knocked_out"
    assert w.BIOLOGICAL_WOUNDS[-1]["special"] == "damaged_item"
    assert w.BIOLOGICAL_WOUNDS[-3]["dis_saves"] == ["EGO"]
    assert w.BIOLOGICAL_WOUNDS[-8]["dis_saves"] == ["STR"]
    assert w.BIOLOGICAL_WOUNDS[-9]["max_hp_damage"] == "d8"
    assert w.BIOLOGICAL_WOUNDS[-18]["special"] == "bloody_mess"
    assert w.BIOLOGICAL_WOUNDS[-19]["deaths_door"] is True
    assert w.BIOLOGICAL_WOUNDS[-20]["dead"] is True


def test_synthetic_table_is_book_real_not_fabricated():
    t = w.SYNTHETIC_WOUNDS
    assert t[0]["name"] == "Update Required"            # NOT "Systems Crash"
    assert t[-2]["name"] == "Supercoolant Leak" and t[-2]["deprived"] is True
    assert t[-3] == {**t[-3], "name": "Ego-Engine Stutter", "slots": 1,
                     "ability_damage": {"EGO": "d4"}}
    assert t[-9]["name"] == "Synthskin Damaged" and t[-9]["slots"] == 2
    assert t[-9]["av_penalty_die"] == "d4" and t[-9]["double_damage"] is True
    assert t[-10]["until_fixed_ability"] == {"STR": "d6", "DEX": "d6"}
    assert t[-11]["reroll_abilities"] == ["INT", "PSY", "EGO"]
    assert t[-12]["name"] == "Vischip Disabled" and t[-12]["blind"] is True and t[-12]["slots"] == 3
    assert t[-13]["daily_tick"] == {"STR": 2, "DEX": 2}
    assert t[-14]["slots"] == 4 and t[-15]["slots"] == 4
    assert t[-16]["slots"] == 5 and t[-16]["ability_damage"] == {"STR": 10, "DEX": 10, "CON": 10}
    assert t[-17]["slots"] == 5
    assert t[-18]["name"] == "Terminal Memory Crystal Corruption" and t[-18]["level_loss"] is True
    assert t[-18]["slots"] == 6
    assert "bloody_mess" not in str(t[-18])             # no fabricated 3-wounds analogue
    assert t[-19]["dead"] is True and t[-19].get("ego_engine_salvageable") is True
    assert t[-20]["dead"] is True


def test_every_row_present_0_through_minus_20():
    for table in (w.BIOLOGICAL_WOUNDS, w.SYNTHETIC_WOUNDS):
        assert sorted(table.keys()) == list(range(-20, 1))


def test_wound_for_hp_clamps_at_minus_20():
    assert w.wound_for_hp(-25, w.BIOLOGICAL_WOUNDS)["name"] == "FATALITY" or \
           w.wound_for_hp(-25, w.BIOLOGICAL_WOUNDS)["dead"] is True
    assert w.wound_for_hp(0, w.BIOLOGICAL_WOUNDS)["special"] == "knocked_out"


# --- Record building: rolled-once derived magnitudes live ON the record ---

def test_roll_wound_record_stamps_av_penalty():
    rec = w.roll_wound_record(-9, w.SYNTHETIC_WOUNDS[-9], rng=lambda a, b: 3)
    assert rec["hp_threshold"] == -9
    assert rec["slots"] == 2
    assert rec["av_penalty"] == 3            # d4 rolled once, stored
    assert rec["double_damage"] is True


def test_roll_wound_record_stamps_until_fixed_rolls():
    rec = w.roll_wound_record(-10, w.SYNTHETIC_WOUNDS[-10], rng=lambda a, b: 4)
    assert rec["until_fixed_penalty"] == {"STR": 4, "DEX": 4}


def test_roll_wound_record_plain_dis_wound():
    rec = w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7], rng=lambda a, b: 1)
    assert rec["dis_saves"] == ["DEX"]
    assert rec["slots"] == 1


# --- Derived effects aggregate from active records (never from the sheet) ---

def test_derived_effects_aggregates_and_vanishes():
    recs = [
        w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7], rng=lambda a, b: 1),
        w.roll_wound_record(-6, w.BIOLOGICAL_WOUNDS[-6], rng=lambda a, b: 1),
        w.roll_wound_record(-9, w.SYNTHETIC_WOUNDS[-9], rng=lambda a, b: 2),
    ]
    eff = w.derived_effects(recs)
    assert set(eff["dis_saves"]) == {"DEX", "CON"}
    assert eff["av_penalty"] == 2 and eff["double_damage"] is True
    # heal the Synthskin record -> its derived effects vanish with no reversal code
    eff2 = w.derived_effects(recs[:2])
    assert eff2["av_penalty"] == 0 and eff2["double_damage"] is False


def test_derived_effects_deprived_deaths_door_blind_unconscious():
    recs = [
        w.roll_wound_record(-2, w.SYNTHETIC_WOUNDS[-2], rng=lambda a, b: 1),
        w.roll_wound_record(-12, w.SYNTHETIC_WOUNDS[-12], rng=lambda a, b: 1),
        dict(w.roll_wound_record(-19, w.BIOLOGICAL_WOUNDS[-19], rng=lambda a, b: 1),
             unconscious=True),
    ]
    eff = w.derived_effects(recs)
    assert eff["deprived"] is True and eff["no_hp_regain"] is True
    assert eff["blind"] is True
    assert eff["deaths_door"] is True
    assert eff["unconscious"] is True


def test_derived_effects_tolerates_legacy_minimal_records():
    # Old-format record (name/slots/effect/hp_threshold only) must not crash
    legacy = {"name": "Old Wound", "slots": 1, "effect": "???", "hp_threshold": -5}
    eff = w.derived_effects([legacy])
    assert eff["dis_saves"] == []


def test_derived_effects_empty():
    eff = w.derived_effects([])
    assert eff["dis_saves"] == [] and eff["unconscious"] is False


# --- Forced drop (Joe ruling: wounds evict gear; room = cap - wound slots) ---

def test_forced_drop_slots():
    assert w.forced_drop_slots(gear_load=10, cap=13, wound_slots=2) == 0   # 10 <= 11
    assert w.forced_drop_slots(gear_load=12, cap=13, wound_slots=2) == 1   # 12 > 11
    assert w.forced_drop_slots(gear_load=13, cap=13, wound_slots=5) == 5
    assert w.forced_drop_slots(gear_load=0, cap=13, wound_slots=13) == 0   # death case, no gear


# --- Additional data-integrity assertions (implementer-added; extraction p.38-39) ---

def test_biological_dis_rows_match_book_order():
    # p.38: -3 EGO, -4 PSY, -5 INT, -6 CON, -7 DEX, -8 STR
    expected = {-3: ("Teeth Knocked Out", "EGO"), -4: ("Scrambled Nerves", "PSY"),
                -5: ("Addling Wound", "INT"), -6: ("Stomach Wound", "CON"),
                -7: ("Crippling Wound", "DEX"), -8: ("Weakening Wound", "STR")}
    for hp, (name, stat) in expected.items():
        row = w.BIOLOGICAL_WOUNDS[hp]
        assert row["name"] == name and row["dis_saves"] == [stat] and row["slots"] == 1


def test_synthetic_d4_rows_match_book_order():
    # p.39: -3 EGO, -4 PSY, -5 INT, -6 CON, -7 DEX, -8 STR (all -d4, 1 slot)
    expected = {-3: ("Ego-Engine Stutter", "EGO"), -4: ("Quantum-Reasoning Overflow", "PSY"),
                -5: ("Memory Crystal Fracture", "INT"), -6: ("Coolant Loop Overheat", "CON"),
                -7: ("Kinesthetics Drive Failure", "DEX"), -8: ("Limb Hydraulics Compromised", "STR")}
    for hp, (name, stat) in expected.items():
        row = w.SYNTHETIC_WOUNDS[hp]
        assert row["name"] == name and row["ability_damage"] == {stat: "d4"} and row["slots"] == 1


def test_biological_mutation_rows_match_book():
    # p.38 verbatim values for -10..-17
    b = w.BIOLOGICAL_WOUNDS
    assert b[-10]["ability_damage"] == {"STR": "d6", "DEX": "d6"} and b[-10]["slots"] == 2
    assert b[-11]["ability_damage"] == {"DEX": "d6", "EGO": "d6"} and b[-11]["slots"] == 2
    assert b[-12]["ability_damage"] == {"INT": "d8", "PSY": "d8"} and b[-12]["unconscious"] is True
    assert b[-13]["ability_damage"] == {"CON": "d8"} and b[-13]["max_hp_damage"] == "d10"
    assert b[-14]["ability_damage"] == {"STR": "d8", "DEX": "d8"}
    assert b[-15]["ability_damage"] == {"STR": 10, "DEX": 10} and b[-15]["slots"] == 3
    assert b[-16]["ability_damage"] == {"STR": 10, "DEX": 10} and b[-16]["slots"] == 3
    assert b[-17]["ability_damage"] == {"INT": 10, "PSY": 10, "EGO": 10} and b[-17]["slots"] == 3


def test_synthetic_minus_17_shutdown_values():
    row = w.SYNTHETIC_WOUNDS[-17]
    assert row["ability_damage"] == {"INT": 10, "PSY": 10, "EGO": 10}
    assert row["unconscious"] is True


def test_duration_stamped_from_entry_die_and_unit():
    rec = w.roll_wound_record(-16, w.SYNTHETIC_WOUNDS[-16], rng=lambda a, b: 4)
    assert rec["duration"] == "4 hours"
    # the die is parsed from the entry, not hardcoded d6
    rec2 = w.roll_wound_record(-15, dict(w.SYNTHETIC_WOUNDS[-15], duration="d4 rounds"),
                               rng=lambda a, b: b)
    assert rec2["duration"] == "4 rounds"


def test_daily_tick_aggregates_across_records():
    r1 = w.roll_wound_record(-13, w.SYNTHETIC_WOUNDS[-13])
    r2 = w.roll_wound_record(-13, w.SYNTHETIC_WOUNDS[-13])
    eff = w.derived_effects([r1, r2])
    assert eff["daily_tick"] == {"STR": 4, "DEX": 4}


def test_until_fixed_penalty_surfaces_in_notes():
    rec = w.roll_wound_record(-10, w.SYNTHETIC_WOUNDS[-10], rng=lambda a, b: 5)
    eff = w.derived_effects([rec])
    assert any("Incompatible Motion Interface" in n and "-5 STR" in n and "until fixed" in n
               for n in eff["notes"])
