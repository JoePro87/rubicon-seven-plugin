# tests/test_survival_pure.py
"""Pure-module tests for survival.py (S1). No I/O, no server import."""
import survival as sv


def _bio(extra_survival=None, inventory=None):
    c = {"name": "Test", "wound_table": "biological"}
    if extra_survival is not None:
        c["survival"] = extra_survival
    if inventory is not None:
        c["inventory"] = inventory
    return c


class TestDailyNeeds:
    def test_biological_default_needs_one_of_each(self):
        assert sv.daily_needs(_bio()) == {"water": 1, "food": 1}

    def test_synthetic_needs_nothing_by_default(self):
        assert sv.daily_needs({"wound_table": "synthetic"}) == {"water": 0, "food": 0}

    def test_mechanical_needs_nothing_by_default(self):
        # C1: _load_characters merges vehicles into the roster with
        # wound_table "mechanical" -- fail-safe default is consume-nothing.
        assert sv.daily_needs({"wound_table": "mechanical"}) == {"water": 0, "food": 0}

    def test_missing_wound_table_needs_nothing_by_default(self):
        # Fail-safe: only an explicit "biological" (or sheet survival block)
        # turns consumption on.
        assert sv.daily_needs({}) == {"water": 0, "food": 0}

    def test_explicit_survival_block_wins_over_wound_table(self):
        # Lithling: biological wounds, mineral metabolism (Joe ruling R-S1d)
        c = _bio({"needs_water": False, "needs_food": False})
        assert sv.daily_needs(c) == {"water": 0, "food": 0}

    def test_water_only_consumer(self):
        # Creenash: drinks, photosynthesizes instead of eating
        c = _bio({"needs_food": False})
        assert sv.daily_needs(c) == {"water": 1, "food": 0}

    def test_gills_water_per_day_override(self):
        c = _bio({"water_per_day": 2})
        assert sv.daily_needs(c) == {"water": 2, "food": 1}

    def test_parasitic_equipped_doubles_both(self):
        inv = {"carried": [{"name": "Bonefruit Rifle", "tags": ["parasitic"]}]}
        assert sv.daily_needs(_bio(inventory=inv)) == {"water": 2, "food": 2}

    def test_parasitic_stacks_with_gills(self):
        inv = {"carried": [{"name": "Bonefruit Rifle", "tags": ["parasitic"]}]}
        c = _bio({"water_per_day": 2}, inventory=inv)
        assert sv.daily_needs(c) == {"water": 4, "food": 2}


class TestDeprivationClock:
    def test_default_three_days(self):
        assert sv.deprivation_clock(_bio(), "thirst") == 3
        assert sv.deprivation_clock(_bio(), "starvation") == 3

    def test_faa_override(self):
        c = _bio({"death_days_thirst": 21})
        assert sv.deprivation_clock(c, "thirst") == 21
        assert sv.deprivation_clock(c, "starvation") == 3


class TestConsumeDay:
    def test_pool_covers_need(self):
        pool = {"food": 5, "water": 5}
        short = sv.consume_day({"water": 1, "food": 1}, pool, [], with_pool=True)
        assert short == {"water": 0, "food": 0}
        assert pool == {"food": 4, "water": 4}

    def test_carried_covers_when_no_pool(self):
        items = [{"name": "Water Rations", "ration_type": "water", "rations": 3},
                 {"name": "Food Rations", "ration_type": "food", "rations": 2}]
        short = sv.consume_day({"water": 1, "food": 1}, None, items, with_pool=True)
        assert short == {"water": 0, "food": 0}
        assert items[0]["rations"] == 2 and items[1]["rations"] == 1

    def test_pool_first_then_carried(self):
        pool = {"food": 0, "water": 1}
        items = [{"ration_type": "food", "rations": 1}]
        short = sv.consume_day({"water": 1, "food": 1}, pool, items, with_pool=True)
        assert short == {"water": 0, "food": 0}
        assert pool["water"] == 0 and items[0]["rations"] == 0

    def test_separated_pc_cannot_touch_pool(self):
        pool = {"food": 5, "water": 5}
        short = sv.consume_day({"water": 1, "food": 1}, pool, [], with_pool=False)
        assert short == {"water": 1, "food": 1}
        assert pool == {"food": 5, "water": 5}

    def test_shortfall_reported_per_need(self):
        short = sv.consume_day({"water": 2, "food": 0}, {"food": 0, "water": 1}, [], True)
        assert short == {"water": 1, "food": 0}

    def test_pool_missing_key_not_injected(self):
        pool = {"water": 5}  # no food key
        sv.consume_day({"water": 1, "food": 0}, pool, [], with_pool=True)
        assert "food" not in pool
        assert pool["water"] == 4

    def test_ledger_credit_reduces_charge(self):
        # R-S1c: a ration consumed at a rest counts toward the day
        pool = {"food": 5, "water": 5}
        short = sv.consume_day({"water": 1, "food": 1}, pool, [], True,
                               already={"water": 1})
        assert short == {"water": 0, "food": 0}
        assert pool == {"food": 4, "water": 5}


class TestTickDeprivation:
    def test_first_missed_day_creates_record(self):
        conds = []
        sv.tick_deprivation(conds, "thirst", met=False, day=97, clock_days=3)
        assert conds == [{"name": "Deprived", "cause": "thirst",
                          "since_day": 97, "death_day": 100}]

    def test_meeting_need_clears_record(self):
        conds = [{"name": "Deprived", "cause": "thirst", "since_day": 97, "death_day": 100}]
        sv.tick_deprivation(conds, "thirst", met=True, day=98, clock_days=3)
        assert conds == []

    def test_existing_record_not_duplicated(self):
        conds = [{"name": "Deprived", "cause": "thirst", "since_day": 97, "death_day": 100}]
        sv.tick_deprivation(conds, "thirst", met=False, day=98, clock_days=3)
        assert len(conds) == 1 and conds[0]["since_day"] == 97

    def test_causes_independent(self):
        conds = []
        sv.tick_deprivation(conds, "thirst", met=False, day=97, clock_days=3)
        sv.tick_deprivation(conds, "starvation", met=False, day=97, clock_days=3)
        assert {c["cause"] for c in conds} == {"thirst", "starvation"}


class TestConditionEffects:
    def test_empty(self):
        eff = sv.condition_effects([])
        assert eff["deprived"] is False and eff["no_hp_regain"] is False

    def test_deprived_blocks_regain_and_reports_clock(self):
        conds = [{"name": "Deprived", "cause": "thirst", "since_day": 97, "death_day": 100}]
        eff = sv.condition_effects(conds)
        assert eff["deprived"] and eff["no_hp_regain"]
        assert eff["dying"] == [("thirst", 100)]

    def test_garbage_tolerated(self):
        assert sv.condition_effects([None, "x", {}])["deprived"] is False
