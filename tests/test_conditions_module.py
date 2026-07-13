"""E1 Task 1: pure conditions.py -- record normalization, effects aggregation,
S1 back-compat, resurrection constant."""
import pytest
import conditions as cnd
import survival as sv


# --- back-compat: existing S1 Deprived records pass through UNCHANGED ---

def test_s1_deprived_record_backcompat():
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 5, "death_day": 8}]
    eff = cnd.condition_effects(conds)
    assert eff["deprived"] is True
    assert eff["no_hp_regain"] is True
    assert eff["deprived_causes"] == ["thirst"]
    assert eff["dying"] == [("thirst", 8)]


def test_survival_delegates_to_conditions():
    # rest/hooks call _sv.condition_effects -- one implementation, no fork
    assert sv.condition_effects is cnd.condition_effects


def test_garbage_tolerant():
    eff = cnd.condition_effects([None, "junk", {}, {"name": 7}])
    assert eff["no_hp_regain"] is False and eff["dis_saves"] == []
    assert cnd.condition_effects(None)["active"] == 0


# --- generic effects vocabulary ---

def test_generic_no_hp_regain_and_dis_saves():
    conds = [{"name": "Curse of Rust", "effects": {"no_hp_regain": True,
                                                   "dis_saves": ["DEX", "CON"]}}]
    eff = cnd.condition_effects(conds)
    assert eff["no_hp_regain"] is True
    assert eff["deprived"] is False          # generic != Deprived
    assert eff["dis_saves"] == ["CON", "DEX"]  # sorted union


def test_dis_saves_union_dedup():
    conds = [{"name": "A", "effects": {"dis_saves": ["DEX"]}},
             {"name": "B", "effects": {"dis_saves": ["dex", "STR"]}}]
    assert cnd.condition_effects(conds)["dis_saves"] == ["DEX", "STR"]


def test_twinned_partner():
    conds = [{"name": "Twinning", "effects": {"twinned": {"partner": "Vela"}}}]
    assert cnd.condition_effects(conds)["twinned_partner"] == "Vela"
    assert cnd.condition_effects([])["twinned_partner"] is None


def test_round_ticks_and_day_ticks_split():
    conds = [
        {"name": "Burning", "since_day": 10,
         "tick": {"cadence": "round", "hp": "d8", "label": "burning"}},
        {"name": "Jellybones", "since_day": 12,
         "tick": {"cadence": "week", "abilities": {"STR": "d4", "CON": "d4"}}},
        {"name": "Slow Rot", "since_day": 12, "tick": {"cadence": "day", "hp": "d4"}},
    ]
    eff = cnd.condition_effects(conds)
    assert [t["name"] for t in eff["round_ticks"]] == ["Burning"]
    assert eff["round_ticks"][0]["hp"] == "d8"
    day_names = sorted(t["name"] for t in eff["day_ticks"])
    assert day_names == ["Jellybones", "Slow Rot"]
    jelly = next(t for t in eff["day_ticks"] if t["name"] == "Jellybones")
    assert jelly["cadence"] == "week" and jelly["since_day"] == 12
    assert jelly["abilities"] == {"STR": "d4", "CON": "d4"}


def test_save_to_end_and_death_clocks():
    conds = [{"name": "Brain Coral", "save_to_end": {"ability": "CON", "dc": 11}},
             {"name": "Doom Mark", "cause": "ritual", "death_day": 140}]
    eff = cnd.condition_effects(conds)
    assert eff["save_to_end"] == [("Brain Coral", "CON", 11)]
    assert eff["death_clocks"] == [("Doom Mark (ritual)", 140)]
    # Deprived death_day lands in dying (S1), NOT duplicated in death_clocks
    dep = [{"name": "Deprived", "cause": "thirst", "death_day": 9}]
    deff = cnd.condition_effects(dep)
    assert deff["dying"] == [("thirst", 9)] and deff["death_clocks"] == []


def test_active_count():
    assert cnd.condition_effects([{"name": "X"}, {"name": "Y"}])["active"] == 2


# --- normalize_record (the condition tool's validator) ---

def test_normalize_record_minimal():
    rec, err = cnd.normalize_record({"name": "Marked"}, day=100)
    assert err == "" and rec["name"] == "Marked" and rec["since_day"] == 100


def test_normalize_record_full():
    rec, err = cnd.normalize_record({
        "name": "Burning", "cause": "lava", "note": "until extinguished",
        "effects": {"no_hp_regain": True, "dis_saves": ["dex"],
                    "twinned": {"partner": "Vela"}},
        "tick": {"cadence": "round", "hp": "d8"},
        "save_to_end": {"ability": "con", "dc": 12},
        "death_day": 110}, day=100)
    assert err == ""
    assert rec["effects"]["dis_saves"] == ["DEX"]
    assert rec["save_to_end"] == {"ability": "CON", "dc": 12}
    assert rec["tick"] == {"cadence": "round", "hp": "d8"}


def test_normalize_record_rejects_non_dict_substructures():
    assert cnd.normalize_record({"name": "X", "effects": "bad"}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "tick": "bad"}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "save_to_end": "bad"}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "effects": {"twinned": "bad"}}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "effects": {"dis_saves": 5}}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "tick": {"cadence": "day", "abilities": "STR"}}, day=1)[1]
    # falsy non-dicts must NOT slip past the guards (the `or {}` bypass)
    assert cnd.normalize_record({"name": "X", "effects": []}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "tick": []}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "save_to_end": []}, day=1)[1]
    # explicit None / absent stays fine
    rec, err = cnd.normalize_record({"name": "X", "effects": None}, day=1)
    assert err == "" and "effects" not in rec


def test_normalize_record_drops_whitespace_cause_and_note():
    rec, err = cnd.normalize_record({"name": "X", "cause": "   ", "note": "\t "}, day=1)
    assert err == ""
    assert "cause" not in rec
    assert "note" not in rec


def test_normalize_record_rejects_bad_input():
    assert cnd.normalize_record({}, day=1)[1]                      # no name
    assert cnd.normalize_record({"name": "X", "tick": {"cadence": "hour", "hp": "d4"}}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "tick": {"cadence": "day"}}, day=1)[1]   # no hp/abilities
    assert cnd.normalize_record({"name": "X", "tick": {"cadence": "day", "hp": "bad"}}, day=1)[1]  # not dice or amount
    assert cnd.normalize_record({"name": "X", "save_to_end": {"ability": "LCK", "dc": 10}}, day=1)[1]
    assert cnd.normalize_record({"name": "X", "effects": {"dis_saves": ["LCK"]}}, day=1)[1]


def test_round_cadence_requires_hp():
    """Round-cadence ability-only ticks would be silently inert (the combat
    round tick only rolls hp; advance_day never sees round cadence) - so
    minting refuses them. Round with hp + abilities stays valid: the
    abilities ride along (documented: only the hp die rolls per round)."""
    rec, err = cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "round",
                               "abilities": {"STR": "d4"}}}, day=1)
    assert rec is None and "tick.hp" in err
    rec, err = cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "round", "hp": "d8",
                               "abilities": {"STR": "d4"}}}, day=1)
    assert err == "" and rec["tick"]["hp"] == "d8"
    assert rec["tick"]["abilities"] == {"STR": "d4"}


# --- resurrection constant (R-E1e) ---

def test_resurrection_push_contents():
    text = "\n".join(cnd.resurrection_push())
    for needle in ("p.229", "Mycomorph", "Necrotech", "Pseudo-Womb", "Spirit",
                   "Ego-Engine", "INT save", "CON save", "d20 + Level >= 16",
                   "reroll STR/DEX/CON", 'affliction(kind="condition", action="clear"'):
        assert needle in text, needle


# --- E2 Task 1: flat amounts, tick.max_hp, tick.save, on_max_hp_zero ---

def test_is_amount_helper():
    assert cnd._is_amount(1) and cnd._is_amount("1") and cnd._is_amount("3")
    assert not cnd._is_amount(0) and not cnd._is_amount(-1)
    assert not cnd._is_amount("d4") and not cnd._is_amount("x") and not cnd._is_amount(None)


def test_flat_amount_in_tick_hp():
    rec, err = cnd.normalize_record(
        {"name": "Aches", "tick": {"cadence": "day", "hp": 1}}, day=10)
    assert err == "" and rec["tick"]["hp"] == "1"          # normalized to str
    rec2, err2 = cnd.normalize_record(
        {"name": "Aches", "tick": {"cadence": "day", "hp": "2"}}, day=10)
    assert err2 == "" and rec2["tick"]["hp"] == "2"


def test_flat_amount_in_tick_abilities():
    rec, err = cnd.normalize_record(
        {"name": "Hivey Hump", "tick": {"cadence": "day", "abilities": {"EGO": 1}}},
        day=10)
    assert err == "" and rec["tick"]["abilities"] == {"EGO": "1"}


def test_tick_max_hp_dice_and_flat():
    rec, err = cnd.normalize_record(
        {"name": "Pox", "tick": {"cadence": "week", "max_hp": "d8"}}, day=10)
    assert err == "" and rec["tick"]["max_hp"] == "d8"
    rec2, err2 = cnd.normalize_record(
        {"name": "Pox", "tick": {"cadence": "week", "max_hp": 2}}, day=10)
    assert err2 == "" and rec2["tick"]["max_hp"] == "2"


def test_tick_max_hp_alone_satisfies_requirement():
    # max_hp counts as a valid drain; hp/abilities not required when max_hp present
    rec, err = cnd.normalize_record(
        {"name": "Pox", "tick": {"cadence": "week", "max_hp": "d8"}}, day=10)
    assert err == ""


def test_tick_max_hp_rejects_garbage():
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "day", "max_hp": "x"}}, day=1)[1]


def test_round_cadence_still_requires_plain_hp():
    # max_hp does NOT satisfy the round-cadence hp requirement
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "round", "max_hp": "d8"}}, day=1)[1]
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "round", "abilities": {"STR": "d4"}}}, day=1)[1]


def test_tick_save_validated():
    rec, err = cnd.normalize_record(
        {"name": "Lumenrot", "tick": {"cadence": "day", "abilities": {"CON": 1},
                                      "save": {"ability": "con", "dc": 15}}}, day=10)
    assert err == "" and rec["tick"]["save"] == {"ability": "CON", "dc": 15}


def test_tick_save_rejects_bad_ability_and_dc():
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "day", "hp": "d4",
                               "save": {"ability": "LCK", "dc": 10}}}, day=1)[1]
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "day", "hp": "d4",
                               "save": {"ability": "CON", "dc": "x"}}}, day=1)[1]


def test_on_max_hp_zero_normalized():
    rec, err = cnd.normalize_record(
        {"name": "Pox", "tick": {"cadence": "week", "max_hp": "d8"},
         "on_max_hp_zero": {"death_in_days": 3}}, day=10)
    assert err == "" and rec["on_max_hp_zero"] == {"death_in_days": 3}


def test_on_max_hp_zero_rejects_bad_value():
    assert cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "week", "max_hp": "d8"},
         "on_max_hp_zero": {"death_in_days": "soon"}}, day=1)[1]


def test_condition_effects_passes_max_hp_and_save():
    conds = [{"name": "Pox", "since_day": 10,
              "tick": {"cadence": "week", "max_hp": "d8"}},
             {"name": "Lumenrot", "since_day": 10,
              "tick": {"cadence": "day", "abilities": {"CON": "1"},
                       "save": {"ability": "CON", "dc": 15}}}]
    eff = cnd.condition_effects(conds)
    pox = next(t for t in eff["day_ticks"] if t["name"] == "Pox")
    assert pox["max_hp"] == "d8" and pox["save"] is None
    lum = next(t for t in eff["day_ticks"] if t["name"] == "Lumenrot")
    assert lum["save"] == {"ability": "CON", "dc": 15} and lum["max_hp"] is None


def test_on_max_hp_zero_requires_tick_max_hp():
    rec, err = cnd.normalize_record(
        {"name": "X", "on_max_hp_zero": {"death_in_days": 3}}, day=1)
    assert rec is None and "tick.max_hp" in err


def test_on_max_hp_zero_rejects_nonpositive_days():
    rec, err = cnd.normalize_record(
        {"name": "X", "tick": {"cadence": "week", "max_hp": "d8"},
         "on_max_hp_zero": {"death_in_days": 0}}, day=1)
    assert rec is None and "positive" in err


# --- E3 Task 1: hp_regain_half + double_rations effect keys ---

def test_hp_regain_half_normalized_and_aggregated():
    rec, err = cnd.normalize_record(
        {"name": "Janus Lenses", "effects": {"hp_regain_half": True}}, day=10)
    assert err == "" and rec["effects"]["hp_regain_half"] is True
    eff = cnd.condition_effects([rec])
    assert eff["hp_regain_half"] is True
    # absent -> False
    assert cnd.condition_effects([{"name": "X"}])["hp_regain_half"] is False


def test_double_rations_normalized_and_aggregated():
    rec, err = cnd.normalize_record(
        {"name": "Fabricator Stoma", "effects": {"double_rations": True}}, day=10)
    assert err == "" and rec["effects"]["double_rations"] is True
    eff = cnd.condition_effects([rec])
    assert eff["double_rations"] is True
    assert cnd.condition_effects([{"name": "X"}])["double_rations"] is False


def test_new_effect_keys_falsey_dropped():
    # a falsey value does not write the key (matches no_hp_regain behavior)
    rec, err = cnd.normalize_record(
        {"name": "X", "effects": {"hp_regain_half": False, "double_rations": 0}}, day=1)
    assert err == "" and "effects" not in rec


# --- E5 Task 1: resurrection catalog + record validator ---

def test_catalog_has_six_paths():
    # B3 R-B3c added the Lazarus Tonic as the sixth resurrection path.
    assert set(cnd.RESURRECTION_CATALOG) == {
        "mycomorph", "necrotech", "pseudo_womb", "spirit", "ego_engine",
        "lazarus_tonic"}
    for p, spec in cnd.RESURRECTION_CATALOG.items():
        assert "timer" in spec and "save" in spec and "label" in spec, p


def test_d6_ability_map():
    assert cnd.D6_ABILITY == {1: "STR", 2: "DEX", 3: "CON",
                              4: "INT", 5: "PSY", 6: "EGO"}


def test_validate_record_minimal():
    rec, err = cnd.validate_resurrection_record(
        {"path": "pseudo_womb", "began_day": 10, "due_day": 17}, day=10)
    assert err == ""
    assert rec == {"path": "pseudo_womb", "began_day": 10,
                   "due_day": 17, "resolved": False}


def test_validate_record_rejects_unknown_path():
    rec, err = cnd.validate_resurrection_record(
        {"path": "zombie", "began_day": 1}, day=1)
    assert rec is None and "path" in err.lower()


def test_validate_record_no_timer_paths_have_null_due_day():
    for p in ("spirit", "necrotech", "ego_engine"):
        rec, err = cnd.validate_resurrection_record(
            {"path": p, "began_day": 5, "due_day": None}, day=5)
        assert err == "" and rec["due_day"] is None, p
