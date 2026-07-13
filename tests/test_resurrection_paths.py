"""E5 Task 1: character(action="resurrect") begin -- corpse-only, one-per-corpse,
per-path timers (mycomorph d4, pseudo-womb +7, spirit/necrotech/ego immediate push).
Seeding pattern copied from test_disease_ticks.py."""
import json
import pytest
import server


def _creenash_char(day=100, hp=19, conditions=None, survival=None):
    ch = {
        "name": "Creenash",
        "species": "True-kin",
        "level": 3,
        "hp": {"current": hp, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 4, "base": 4},
            "DEX": {"current": 6, "base": 6},
            "CON": {"current": 1, "base": 1},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 1, "base": 1},
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }
    if survival is not None:
        ch["survival"] = survival
    return ch


def _vela_char(conditions=None):
    return {
        "name": "Vela", "species": "True-kin",
        "level": 2,
        "hp": {"current": 24, "max": 24}, "wound_table": "biological",
        "abilities": {a: {"current": 4, "base": 4}
                      for a in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed(dirpath, day=100, creenash=None, vela=None):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash if creenash is not None else _creenash_char(day)))
    (chars_dir / "vela.json").write_text(
        json.dumps(vela if vela is not None else _vela_char()))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get(name="creenash"):
    data, err = server._load_characters()
    assert not err
    key, ch = server._find_character(data, name)
    return data, key, ch


def _corpse_char(**kw):
    ch = _creenash_char(**kw)
    ch["hp"]["current"] = -20      # the death sentinel
    return ch


def test_resurrect_refused_on_living(isolate_campaign_dir):
    _seed(isolate_campaign_dir)                       # creenash alive (hp 19)
    out = server._character_resurrect("creenash", path="pseudo_womb")
    assert "corpse" in out.lower() and "not" in out.lower()


def test_resurrect_pseudo_womb_stamps_due_day_plus_7(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out = server._character_resurrect("creenash", path="pseudo_womb")
    _, _, ch = _get()
    assert ch["resurrection"]["path"] == "pseudo_womb"
    assert ch["resurrection"]["due_day"] == 100 + 7      # seed day 100
    assert ch["resurrection"]["resolved"] is False
    assert 'character(action="resurrect_resolve"' in out   # pushes resolve
    assert "CON" in out                                    # the save


def test_resurrect_mycomorph_rolls_d4(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    monkeypatch.setattr(server, "_roll_d4", lambda: 3)
    server._character_resurrect("creenash", path="mycomorph")
    _, _, ch = _get()
    assert ch["resurrection"]["due_day"] == 100 + 3


def test_resurrect_spirit_no_record_pushes_bid(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out = server._character_resurrect("creenash", path="spirit")
    _, _, ch = _get()
    # spirit carries no in-progress record; it pushes the immediate bid
    assert "resurrection" not in ch or ch.get("resurrection") is None
    assert 'path="spirit"' in out and "save_total" in out
    assert "d20" in out                                   # the bid syntax


def test_resurrect_necrotech_and_ego_push_resolve_directly(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out_n = server._character_resurrect("creenash", path="necrotech")
    assert 'path="necrotech"' in out_n and "resurrect_resolve" in out_n
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out_e = server._character_resurrect("creenash", path="ego_engine")
    assert 'path="ego_engine"' in out_e and "resurrect_resolve" in out_e


def test_resurrect_one_per_corpse_refused(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo_womb")
    out = server._character_resurrect("creenash", path="mycomorph")
    assert "already" in out.lower() and "replace" in out.lower()


def test_resurrect_replace_true_overrides(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo_womb")
    monkeypatch.setattr(server, "_roll_d4", lambda: 2)
    server._character_resurrect("creenash", path="mycomorph", replace=True)
    _, _, ch = _get()
    assert ch["resurrection"]["path"] == "mycomorph"


def test_resurrect_prefix_matched_path(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo")   # prefix
    _, _, ch = _get()
    assert ch["resurrection"]["path"] == "pseudo_womb"


# ---------------------------------------------------------------------------
# Task 2: advance_day RESURRECTION TICK
# ---------------------------------------------------------------------------

def test_due_day_push_fires_on_multi_day_jump(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo_womb")   # due 107
    out = server.advance_day(110, "ten days pass")                # jump past
    assert "creenash" in out.lower()
    assert 'character(action="resurrect_resolve"' in out          # pushed
    assert "CON" in out
    _, _, ch = _get()
    assert ch["resurrection"]["resolved"] is False                # NOT auto-resolved


def test_due_day_push_idempotent_not_double_fired(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo_womb")
    server.advance_day(107, "decant day")
    out2 = server.advance_day(108, "the next day")
    # the due-day push fires AT/after due_day; an unresolved record keeps nudging
    # but must not crash or double-stamp. Assert it still references the path.
    assert "resurrect_resolve" in out2   # the daily re-nudge is real


def test_corpse_resurrection_record_survives_the_condition_tick(isolate_campaign_dir):
    # the condition tick skips corpses; the resurrection record must persist
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect("creenash", path="pseudo_womb")
    server.advance_day(102, "two days")
    _, _, ch = _get()
    assert ch["resurrection"]["path"] == "pseudo_womb"   # not wiped


def test_spirit_sunrise_unfades_at_full_essence(isolate_campaign_dir):
    ch = _corpse_char()
    ch["spirit"] = {"essence": 0, "faded_until": 101, "max_essence": 23}
    ch["conditions"] = [{"name": "Spirit", "since_day": 100,
                         "note": "faded"}]
    _seed(isolate_campaign_dir, creenash=ch)
    out = server.advance_day(101, "sunrise")
    _, _, ch2 = _get()
    assert ch2["spirit"]["faded_until"] is None
    assert ch2["spirit"]["essence"] == 23          # FULL essence at sunrise
    assert "sunrise" in out.lower() or "essence" in out.lower()


def test_spirit_not_yet_sunrise_stays_faded(isolate_campaign_dir):
    ch = _corpse_char()
    ch["spirit"] = {"essence": 0, "faded_until": 105, "max_essence": 23}
    _seed(isolate_campaign_dir, creenash=ch)
    server.advance_day(102, "earlier")
    _, _, ch2 = _get()
    assert ch2["spirit"]["faded_until"] == 105       # not yet


def test_resolved_record_inert_in_tick(isolate_campaign_dir):
    ch = _corpse_char()
    ch["resurrection"] = {"path": "pseudo_womb", "began_day": 90,
                          "due_day": 97, "resolved": True,
                          "outcome": "fail", "resolved_day": 97}
    _seed(isolate_campaign_dir, creenash=ch)
    out = server.advance_day(110, "long after")
    # a resolved record must not re-push a resolution
    assert 'resurrect_resolve' not in out   # resolved record is inert


# ---------------------------------------------------------------------------
# Task 3: resurrect_resolve -- five outcome tests
# ---------------------------------------------------------------------------

def _begin(path, char_name="creenash", **kw):
    return server._character_resurrect(char_name, path=path, **kw)


def _force_d4():
    # mycomorph begin rolls a d4; _force_d4 returns {} so _begin signature stays clean.
    return {}


def test_resolve_pseudo_womb_pass_full_restore(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("pseudo_womb")
    out = server._character_resurrect_resolve("creenash", path="pseudo_womb", save_total=18)
    _, _, ch = _get()
    assert ch["hp"]["current"] == ch["hp"]["max"]        # restored
    assert ch["conditions"] == []                        # revival cleanup
    assert ch["resurrection"]["resolved"] is True
    assert ch["resurrection"]["outcome"] == "pass"
    assert "exact copy" in out.lower()


def test_resolve_pseudo_womb_fail_rolls_two_mutations(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("pseudo_womb")
    calls = {"n": 0}
    def fake_mut():
        calls["n"] += 1
        return {"name": f"Mut{calls['n']}", "effect": "x", "source": "d100=1"}
    monkeypatch.setattr(server, "_roll_cacogen_mutation", fake_mut)
    out = server._character_resurrect_resolve("creenash", path="pseudo_womb", save_total=10)
    _, _, ch = _get()
    muts = ch["special_traits"]["mutations"]
    assert calls["n"] == 2 and len(muts) == 2            # exactly two
    assert "Mut1" in out and "Mut2" in out
    assert ch["hp"]["current"] == ch["hp"]["max"]        # then restore


def test_resolve_pseudo_womb_nat1_forces_fail(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("pseudo_womb")
    monkeypatch.setattr(server, "_roll_cacogen_mutation",
                        lambda: {"name": "M", "effect": "x", "source": "d100=1"})
    server._character_resurrect_resolve("creenash", path="pseudo_womb",
                                        save_total=99, natural_die=1)
    _, _, ch = _get()
    assert len(ch["special_traits"]["mutations"]) == 2   # nat-1 = fail


def test_resolve_mycomorph_pass_swaps_species(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("mycomorph", **_force_d4())
    out = server._character_resurrect_resolve("creenash", path="mycomorph", save_total=17)
    _, _, ch = _get()
    assert ch["species"] == "Mycomorph"
    assert "ancestry" in out.lower()                      # swap pushed
    assert ch["level"] == _corpse_char()["level"]         # Level kept on pass


def test_resolve_mycomorph_fail_level_1(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("mycomorph", **_force_d4())
    out = server._character_resurrect_resolve("creenash", path="mycomorph", save_total=5)
    _, _, ch = _get()
    assert ch["species"] == "Mycomorph"
    assert ch["level"] == 1 and ch["xp"] == {"current": 0, "needed": 1}
    assert "rebuild" in out.lower()                       # rebuild pushed


def test_resolve_spirit_pass_mints_block_and_condition(isolate_campaign_dir):
    ch0 = _corpse_char()
    _seed(isolate_campaign_dir, creenash=ch0)
    server._character_resurrect_resolve("creenash", path="spirit", save_total=16)
    _, _, ch = _get()
    assert ch["spirit"]["essence"] == ch0["hp"]["max"]    # essence = old max HP
    assert ch["spirit"]["faded_until"] is None
    assert any(c.get("name") == "Spirit" for c in ch["conditions"])
    assert ch["hp"]["current"] == -20                     # body stays a corpse


def test_resolve_spirit_fail_refuses_rebid(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out1 = server._character_resurrect_resolve("creenash", path="spirit", save_total=10)
    assert "scatter" in out1.lower() or "fail" in out1.lower()
    _, _, ch = _get()
    assert ch["resurrection"]["outcome"] == "spirit_failed"
    assert "spirit" not in ch or ch.get("spirit") is None
    # the other four paths re-pushed
    assert "mycomorph" in out1.lower() and "pseudo" in out1.lower()
    # a re-bid is refused
    out2 = server._character_resurrect_resolve("creenash", path="spirit", save_total=20)
    assert "one bid" in out2.lower() or "already" in out2.lower()


def test_resolve_lazarus_tonic_costs_one_level(isolate_campaign_dir):
    """B3 R-B3c: the Lazarus Tonic resolve (the sixth E5 path) restores a
    biological corpse to life at the cost of one Level, no save. Creenash is
    Level 3 -> 2, HP back to max, wounds survive."""
    _seed(isolate_campaign_dir, creenash=_corpse_char())     # Level 3 corpse
    out = server._character_resurrect_resolve("creenash", path="lazarus_tonic")
    _, _, ch = _get()
    assert ch["level"] == 2                                   # R-B3c: -1 Level
    assert ch["hp"]["current"] == ch["hp"]["max"]            # restored to life
    assert ch["resurrection"]["resolved"] is True
    assert "Level" in out and "2" in out


def test_resolve_lazarus_tonic_floors_at_level_1(isolate_campaign_dir):
    """R-B3c edge: the -1 Level cost never drops below Level 1."""
    corpse = _corpse_char()
    corpse["level"] = 1
    _seed(isolate_campaign_dir, creenash=corpse)
    server._character_resurrect_resolve("creenash", path="lazarus_tonic")
    _, _, ch = _get()
    assert ch["level"] == 1                                   # max(1, 1-1)


def test_resolve_necrotech_stamps_synthetic_type(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("necrotech")
    out = server._character_resurrect_resolve("creenash", path="necrotech")
    _, _, ch = _get()
    assert ch["synthetic_type"] is True
    assert ch["conditions"] == []
    assert "downside" in out.lower()
    import diseases
    assert diseases.nano_resist_dis(ch) is True            # consumed by the OR


def test_resolve_ego_engine_rerolls_str_dex_con(isolate_campaign_dir, monkeypatch):
    ch0 = _corpse_char()
    ch0["abilities"]["INT"]["current"] = 5
    _seed(isolate_campaign_dir, creenash=ch0)
    _begin("ego_engine")
    monkeypatch.setattr(server, "_roll_3d6_lowest", lambda: (2, [2, 4, 5]))
    server._character_resurrect_resolve("creenash", path="ego_engine",
                                        intact_core=True)
    _, _, ch = _get()
    assert ch["level"] == 1 and ch["xp"] == {"current": 0, "needed": 1}
    for ab in ("STR", "DEX", "CON"):
        assert ch["abilities"][ab]["current"] == 2         # rerolled
        assert ch["abilities"][ab]["base"] == 2
    assert ch["abilities"]["INT"]["current"] == 5          # kept


def test_resolve_clears_conditions_via_revival_lever(isolate_campaign_dir):
    ch = _corpse_char()
    ch["conditions"] = [{"name": "Poisoned", "since_day": 99}]
    _seed(isolate_campaign_dir, creenash=ch)
    _begin("pseudo_womb")
    server._character_resurrect_resolve("creenash", path="pseudo_womb", save_total=18)
    _, _, ch2 = _get()
    assert ch2["conditions"] == []


# ---------------------------------------------------------------------------
# Task 3 adversarial-review fixes
# ---------------------------------------------------------------------------

def test_resolve_refused_when_already_resolved(isolate_campaign_dir, monkeypatch):
    # MEDIUM 1: a second resolve on a resolved death must refuse (no re-cleanup,
    # no extra mutations on the now-living PC)
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    _begin("pseudo_womb")
    server._character_resurrect_resolve("creenash", path="pseudo_womb", save_total=18)
    monkeypatch.setattr(server, "_roll_cacogen_mutation",
                        lambda: {"name": "M", "effect": "x", "source": "d100=1"})
    out2 = server._character_resurrect_resolve("creenash", path="pseudo_womb",
                                               save_total=5)
    assert "already resolved" in out2.lower()
    assert "fresh corpse" in out2.lower()
    _, _, ch = _get()
    assert ch.get("special_traits", {}).get("mutations", []) == []  # no re-roll
    assert ch["resurrection"]["outcome"] == "pass"                  # not overwritten


def test_spirit_failed_still_allows_other_paths(isolate_campaign_dir):
    # MEDIUM 1 exception: spirit_failed blocks ONLY path="spirit"; the other
    # four paths remain legal on the corpse.
    # MEDIUM 2: a stale spirit block is popped by the revival cleanup.
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    server._character_resurrect_resolve("creenash", path="spirit", save_total=10)
    _, _, ch = _get()
    assert ch["resurrection"]["outcome"] == "spirit_failed"
    # the spirit re-bid itself stays refused (one bid per death)
    out_bid = server._character_resurrect_resolve("creenash", path="spirit",
                                                  save_total=20)
    assert "one" in out_bid.lower() and "bid" in out_bid.lower()
    # seed a stale spirit block manually (spirit_failed mints none)
    ch["spirit"] = {"essence": 5, "max_essence": 23, "faded_until": None}
    server._save_single_character("creenash", ch)
    out = server._character_resurrect_resolve("creenash", path="necrotech")
    assert "already resolved" not in out.lower()
    _, _, ch2 = _get()
    assert ch2["synthetic_type"] is True          # necrotech went through
    assert "spirit" not in ch2                    # stale block popped


def test_pseudo_womb_malformed_hp_warns_not_crashes(isolate_campaign_dir):
    # LOW 3: a malformed hp box must warn, not crash
    ch = _corpse_char()
    ch["hp"] = {"current": -20}                   # no "max"
    _seed(isolate_campaign_dir, creenash=ch)
    _begin("pseudo_womb")
    out = server._character_resurrect_resolve("creenash", path="pseudo_womb",
                                              save_total=18)
    assert "warning" in out.lower() and "hp" in out.lower()


def test_ego_engine_bare_int_ability_slots(isolate_campaign_dir, monkeypatch):
    # LOW 4: bare-int ability slots must be replaced with dicts, not TypeError
    ch = _corpse_char()
    ch["abilities"] = {"STR": 4, "DEX": 6, "CON": 1, "INT": 5, "PSY": 1, "EGO": 1}
    _seed(isolate_campaign_dir, creenash=ch)
    _begin("ego_engine")
    monkeypatch.setattr(server, "_roll_3d6_lowest", lambda: (2, [2, 4, 5]))
    server._character_resurrect_resolve("creenash", path="ego_engine",
                                        intact_core=True)
    _, _, ch2 = _get()
    for ab in ("STR", "DEX", "CON"):
        assert ch2["abilities"][ab] == {"current": 2, "base": 2}
    assert ch2["abilities"]["INT"] == 5            # untouched paths keep shape


def test_pseudo_womb_clears_wounds_brand_new_body(isolate_campaign_dir):
    # Joe-facing rule: a clone is a brand-new body - Gitch crystals do not
    # carry over (pass AND fail; pinned on pass)
    ch = _corpse_char()
    ch["wounds"] = [{"name": "Gitch Crystals", "slots": 1, "av_bonus": 1,
                     "gitch": True, "day": 95}]
    ch["wounds_slots_used"] = 1
    _seed(isolate_campaign_dir, creenash=ch)
    _begin("pseudo_womb")
    out = server._character_resurrect_resolve("creenash", path="pseudo_womb",
                                              save_total=18)
    _, _, ch2 = _get()
    assert ch2["wounds"] == []
    assert ch2["wounds_slots_used"] == 0
    assert "brand-new body" in out.lower()


def test_necrotech_keeps_wounds_and_emits_line(isolate_campaign_dir):
    # the non-clone paths leave wounds untouched but say so
    ch = _corpse_char()
    ch["wounds"] = [{"name": "Gitch Crystals", "slots": 1, "av_bonus": 1,
                     "gitch": True, "day": 95}]
    ch["wounds_slots_used"] = 1
    _seed(isolate_campaign_dir, creenash=ch)
    _begin("necrotech")
    out = server._character_resurrect_resolve("creenash", path="necrotech")
    _, _, ch2 = _get()
    assert len(ch2["wounds"]) == 1                 # untouched
    assert ch2["wounds_slots_used"] == 1
    assert "survived death" in out.lower()


# ---------------------------------------------------------------------------
# Task 4: spirit_spend
# ---------------------------------------------------------------------------

def _spirit_corpse(essence=23):
    ch = _corpse_char()
    ch["spirit"] = {"essence": essence, "max_essence": 23, "faded_until": None}
    ch["conditions"] = [{"name": "Spirit", "since_day": 100,
                         "note": f"unquiet spirit -- essence {essence}/23"}]
    return ch


def test_spirit_spend_touch_deducts_d6(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_spirit_corpse(23))
    monkeypatch.setattr(server, "_roll_d6", lambda: 4)
    out = server._character_spirit_spend("creenash", kind="touch")
    _, _, ch = _get()
    assert ch["spirit"]["essence"] == 19          # 23 - 4
    assert "19" in out


def test_spirit_spend_possess_adds_target_level(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_spirit_corpse(23))
    monkeypatch.setattr(server, "_roll_d6", lambda: 3)
    out = server._character_spirit_spend("creenash", kind="possess", target_level=4)
    _, _, ch = _get()
    assert ch["spirit"]["essence"] == 23 - (3 + 4)   # 16
    assert "possess" in out.lower()


def test_spirit_spend_fade_at_zero(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, creenash=_spirit_corpse(3))
    monkeypatch.setattr(server, "_roll_d6", lambda: 5)
    out = server._character_spirit_spend("creenash", kind="touch")
    _, _, ch = _get()
    assert ch["spirit"]["essence"] <= 0
    assert ch["spirit"]["faded_until"] == 100 + 1    # day+1 sunrise
    assert "fade" in out.lower() and "sunrise" in out.lower()


def test_spirit_spend_while_faded_refused(isolate_campaign_dir):
    ch = _spirit_corpse(0)
    ch["spirit"]["faded_until"] = 101
    _seed(isolate_campaign_dir, creenash=ch)
    out = server._character_spirit_spend("creenash", kind="touch")
    assert "faded" in out.lower() and "sunrise" in out.lower()


def test_spirit_spend_no_spirit_block_refused(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_corpse_char())
    out = server._character_spirit_spend("creenash", kind="touch")
    assert "not a spirit" in out.lower() or "no spirit" in out.lower()


def test_spirit_spend_possess_requires_target_level(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_spirit_corpse(23))
    out = server._character_spirit_spend("creenash", kind="possess")
    assert "target_level" in out
