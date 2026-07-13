"""E2 Task 3: the disease tool - apply (immunity, duplicate, resist-save,
Brain Coral trade), expose (odds parsing + push chain), list/info."""
import json
import pytest
import server
import diseases as dz


def _creenash_char(day=100, hp=19, species="True-kin", conditions=None):
    return {
        "name": "Creenash",
        "species": species,
        "hp": {"current": hp, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 6, "base": 6},
            "DEX": {"current": 6, "base": 6},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 2, "base": 2},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": conditions if conditions is not None else [],
        "inventory": {"carried": []},
    }


def _seed(dirpath, day=100, creenash=None):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash if creenash is not None else _creenash_char(day)))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _get(name="creenash"):
    data, err = server._load_characters()
    assert not err
    return server._find_character(data, name)


def test_list_shows_all_six(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="list")
    for name in dz.DISEASES:
        assert name in out
    assert "Virulence" in out or "TN" in out


def test_info_one_disease(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="info", disease="Lumenrot")
    assert "Lumenrot" in out and "15" in out      # TN 15
    assert "cure" in out.lower() and "vector" in out.lower()


def test_apply_mints_condition_record(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones")
    assert "Jellybones" in out
    assert 'affliction(kind="condition", action="status")' in out
    assert 'affliction(kind="condition", action="save"' in out        # treat-save push
    _, ch = _get()
    rec = next(c for c in ch["conditions"] if c["name"] == "Jellybones")
    assert rec["cause"] == "disease"
    assert rec["save_to_end"] == {"ability": "CON", "dc": 12}


def test_apply_immune_synth_refused(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_creenash_char(species="Synthetic"))
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones")
    assert "immune" in out.lower()
    _, ch = _get()
    assert not any(c.get("name") == "Jellybones" for c in ch.get("conditions", []))


def test_apply_force_overrides_immunity(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_creenash_char(species="Synthetic"))
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones",
                         force=True)
    assert "Jellybones" in out
    _, ch = _get()
    assert any(c.get("name") == "Jellybones" for c in ch["conditions"])


def test_apply_duplicate_refused(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones")
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones")
    assert "already" in out.lower()


def test_apply_with_resist_save_pass_blocks(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    # Jellybones TN 12; a total of 12 resists
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones",
                         save_total=12)
    assert "resist" in out.lower()
    _, ch = _get()
    assert not any(c.get("name") == "Jellybones" for c in ch.get("conditions", []))


def test_apply_with_resist_save_fail_infects(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Jellybones",
                         save_total=11)   # below TN 12
    _, ch = _get()
    assert any(c.get("name") == "Jellybones" for c in ch["conditions"])


def test_brain_coral_trade(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir)
    _, ch0 = _get()
    str0 = ch0["abilities"]["STR"]["current"]
    psy0 = ch0["abilities"]["PSY"]["current"]
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 3})
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Brain Coral")
    assert "STR" in out and "PSY" in out
    _, ch = _get()
    assert ch["abilities"]["STR"]["current"] == str0 - 3
    assert ch["abilities"]["PSY"]["current"] == psy0 + 3


def test_expose_with_odds_pushes_resist_save(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir)
    # force the odds roll to land on exposure (1-in-6 -> roll a 1)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 1})
    out = server.affliction(kind="disease", action="expose", character="creenash", disease="Lumenrot",
                         odds="1-in-6")
    assert "EXPOSED" in out.upper()
    # the resist-save push names the literal apply call with save_total placeholder
    assert 'affliction(kind="disease", action="apply"' in out and "save_total" in out


def test_expose_odds_miss_no_infection(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 4})
    out = server.affliction(kind="disease", action="expose", character="creenash", disease="Lumenrot",
                         odds="1-in-6")
    assert "no exposure" in out.lower() or "not exposed" in out.lower()


def test_expose_no_odds_straight_to_resist_push(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="expose", character="creenash", disease="Hivey Hump")
    assert 'affliction(kind="disease", action="apply"' in out and "save_total" in out


def test_apply_unknown_disease_errors(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Spicy Flu")
    assert "Unknown disease" in out


def test_apply_vehicle_refused(isolate_campaign_dir):
    # vehicles persist under vehicles/<key>.json (type == "vehicle"); write the
    # file directly so _load_characters merges it back into the roster.
    _seed(isolate_campaign_dir)
    vdir = isolate_campaign_dir / "vehicles"
    vdir.mkdir(exist_ok=True, parents=True)
    (vdir / "truck.json").write_text(json.dumps({"name": "Truck", "type": "vehicle"}))
    out = server.affliction(kind="disease", action="apply", character="truck", disease="Jellybones")
    assert "vehicle" in out.lower()


def test_brain_coral_trade_death_is_twinning_gated(isolate_campaign_dir, monkeypatch):
    """A trade STR drain that floors the ability routes through the death
    gate - a Twinned PC is held at the brink, no PSY gain on a corpse path."""
    cre = _creenash_char()
    cre["abilities"]["STR"] = {"current": -5, "base": 6}
    cre["conditions"] = [{"name": "Twinning", "since_day": 31,
                          "effects": {"twinned": {"partner": "Vela"}}}]
    vela = _creenash_char()
    vela["name"] = "Vela"
    vela["conditions"] = [{"name": "Twinning", "since_day": 31,
                           "effects": {"twinned": {"partner": "Creenash"}}}]
    _seed(isolate_campaign_dir, creenash=cre)
    (isolate_campaign_dir / "characters" / "vela.json").write_text(
        json.dumps(vela))
    monkeypatch.setattr(server.dice, "roll_notation",
                        lambda n: {"total": 8, "notation": n})
    out = server.affliction(kind="disease", action="apply", character="Creenash",
                         disease="Brain Coral")
    assert "TWINNING" in out.upper()
    _, c = _get("creenash")
    assert c["abilities"]["STR"]["current"] == -10        # brink clamp
    assert c["hp"]["current"] > -20                        # not dead
    assert c.get("twinning_pending")                       # window stamped


def test_apply_on_corpse_warns(isolate_campaign_dir):
    cre = _creenash_char(hp=-20)
    _seed(isolate_campaign_dir, creenash=cre)
    out = server.affliction(kind="disease", action="apply", character="Creenash",
                         disease="Wrathworms")
    assert "DEAD" in out and "tombstone" in out


def test_synth_can_catch_nanomachine_infection(isolate_campaign_dir):
    """E3: nanomachine infections infect ALL creature types - the organic
    Synth immunity must not fire for the nanomachine family."""
    cre = _creenash_char(species="Synth")
    _seed(isolate_campaign_dir, creenash=cre)
    out = server.affliction(kind="disease", action="apply", character="Creenash",
                         disease="Goldencough")
    assert "immune" not in out.lower()
    assert "contracts" in out


# --- E3 Task 2: slot occupancy / implant overwrite / markers ---

def _creenash_with_aug(slot, implant):
    ch = _creenash_char()
    ch["augmentations"] = {slot: implant}
    return ch


def test_nano_apply_writes_infection_marker(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    assert "Janus Lenses" in out
    _, ch = _get()
    assert ch["augmentations"]["PSY"]["infection"] is True
    assert "Janus Lenses" in ch["augmentations"]["PSY"]["name"]


def test_nano_apply_overwrites_implant_and_reverses_bonus(isolate_campaign_dir):
    implant = {"name": "Neural Lace", "stat_bonus": {"PSY": 2}}
    ch = _creenash_with_aug("PSY", implant)
    # reflect the +2 the implant gave (so reversal returns to base)
    ch["abilities"]["PSY"]["current"] = 4   # base 2 + 2
    _seed(isolate_campaign_dir, creenash=ch)
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    assert "Neural Lace" in out and "overwritten" in out.lower()
    _, ch2 = _get()
    assert ch2["abilities"]["PSY"]["current"] == 2          # +2 reversed
    assert ch2["augmentations"]["PSY"]["infection"] is True  # marker replaced it


def test_nano_apply_two_slots_marks_both(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Usurper Arm")
    _, ch = _get()
    assert ch["augmentations"]["DEX"]["infection"] is True
    assert ch["augmentations"]["EGO"]["infection"] is True


def test_gitch_apply_marks_rolled_slot(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir)
    import diseases
    monkeypatch.setattr(diseases, "_roll_d6", lambda: 1)   # 1 -> STR
    server.affliction(kind="disease", action="apply", character="creenash", disease="The Gitch")
    _, ch = _get()
    assert ch["augmentations"]["STR"]["infection"] is True


def test_cybernetic_install_refused_on_infected_slot(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    out = server._cybernetic_install("creenash", "Aug", "PSY", "boost")
    assert "infect" in out.lower()
    assert 'affliction(kind="condition", action="save"' in out      # pushes the cure


def test_condition_clear_removes_infection_marker(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    _, ch = _get()
    assert ch["augmentations"]["PSY"] is not None
    server.affliction(kind="condition", action="clear", character="creenash", name="Janus Lenses")
    _, ch2 = _get()
    assert ch2["augmentations"].get("PSY") is None       # marker cleared


def test_clear_all_conditions_removes_markers(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Usurper Arm")
    server.affliction(kind="condition", action="clear", character="creenash", all_conditions=True)
    _, ch = _get()
    assert ch["augmentations"].get("DEX") is None
    assert ch["augmentations"].get("EGO") is None


def test_nano_apply_synth_allowed_with_dis_line(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_creenash_char(species="Synthetic"))
    out = server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    assert "Janus Lenses" in out          # NOT immune
    assert "DIS" in out                    # resist-DIS surfaced
    _, ch = _get()
    assert any(c.get("name") == "Janus Lenses" for c in ch["conditions"])


def test_nano_expose_synth_carries_dis_line(isolate_campaign_dir):
    _seed(isolate_campaign_dir, creenash=_creenash_char(species="Synthetic"))
    out = server.affliction(kind="disease", action="expose", character="creenash", disease="Janus Lenses")
    assert "DIS" in out and "lower" in out.lower()


def test_cure_save_success_frees_infected_slot(isolate_campaign_dir):
    """CRITICAL pin: a PASSED cure save (the normal end of a disease) must
    remove the infection marker, not just the condition record."""
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Janus Lenses")
    _, ch = _get()
    assert ch["augmentations"]["PSY"]["infection"] is True
    out = server.affliction(kind="condition", action="save", character="creenash",
                           name="Janus Lenses", save_total=12)  # TN 12 (V2)
    assert "PASS" in out
    _, ch2 = _get()
    assert ch2["augmentations"].get("PSY") is None       # slot freed


def test_nano_apply_overwrites_list_slot_and_reverses_bonuses(isolate_campaign_dir):
    """MAJOR pin: a list-shaped slot (multiple implants) must have EVERY
    member's stat_bonus reversed on overwrite, not just reported."""
    implants = [{"name": "Reflex Coil", "stat_bonus": {"DEX": 2}},
                {"name": "Eye Jewel", "stat_bonus": {"EGO": 1}}]
    ch = _creenash_with_aug("DEX", implants)
    ch["abilities"]["DEX"]["current"] = 8   # base 6 + 2
    ch["abilities"]["EGO"]["current"] = 6   # base 5 + 1
    _seed(isolate_campaign_dir, creenash=ch)
    out = server.affliction(kind="disease", action="apply", character="creenash",
                         disease="Usurper Arm")   # slots DEX+EGO
    assert "Reflex Coil" in out and "overwritten" in out.lower()
    _, ch2 = _get()
    assert ch2["abilities"]["DEX"]["current"] == 6   # +2 reversed
    assert ch2["abilities"]["EGO"]["current"] == 5   # +1 reversed
    assert ch2["augmentations"]["DEX"]["infection"] is True
    assert ch2["augmentations"]["EGO"]["infection"] is True


def test_nano_resist_dis_infection_marker_not_counted(isolate_campaign_dir):
    """INFECTION markers in augmentations must not trigger DIS for nano_resist_dis
    - only real cybernetic implants count (T1 review fix)."""
    # A plain True-kin with only an infection marker should NOT get DIS
    ch = _creenash_char()
    ch["augmentations"] = {"PSY": {"name": "INFECTION: Janus Lenses",
                                   "infection": True, "disease": "Janus Lenses"}}
    assert dz.nano_resist_dis(ch) is False
    # A True-kin with a real implant SHOULD get DIS
    ch2 = _creenash_char()
    ch2["augmentations"] = {"PSY": {"name": "Neural Lace", "effect": "psi boost"}}
    assert dz.nano_resist_dis(ch2) is True


# ---------------------------------------------------------------------------
# E3 Goldencough coughing-fit note
# ---------------------------------------------------------------------------

def test_condition_save_note_goldencough_coughing_fit(isolate_campaign_dir):
    _seed(isolate_campaign_dir)
    server.affliction(kind="disease", action="apply", character="creenash", disease="Goldencough")
    _, ch = _get()
    note = server._condition_save_note(ch, "CON")
    assert "coughing fit" in note.lower()
    # not surfaced on a non-CON save
    assert "coughing fit" not in server._condition_save_note(ch, "STR").lower()
