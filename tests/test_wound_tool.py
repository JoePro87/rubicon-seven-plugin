# tests/test_wound_tool.py
# Task 4: wound() tool — status/heal/ko_save/wake via _wound_dispatch, with
# _remove_wound as the single wound-removal seam (spec section 8).
# _pc/_wire duplicated from test_wound_application.py per the plan note.
import server
import wounds as w


def _pc(hp=5, max_hp=10, table="biological", wounds=None, carried=None, cap=13):
    return {"name": "Tester", "wound_table": table,
            "hp": {"current": hp, "max": max_hp},
            "abilities": {s: {"current": 2} for s in ("STR", "DEX", "CON", "INT", "PSY", "EGO")},
            "slot_capacity_total": cap, "wounds": list(wounds or []),
            "wounds_slots_used": sum(x.get("slots", 0) for x in (wounds or [])),
            "mystic_gifts": [], "codices": [],
            "inventory": {"carried": list(carried or [])}}


def _wire(monkeypatch, char):
    data = {"characters": {"tester": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    return data


def test_heal_removes_record_frees_slots_and_derived_effects_vanish(monkeypatch):
    rec = w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])
    char = _pc(hp=-7, wounds=[rec])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="Crippling")
    assert char["wounds"] == []
    assert char["wounds_slots_used"] == 0
    assert "healed" in out.lower()
    assert w.derived_effects(char["wounds"])["dis_saves"] == []   # vanished, no reversal code


def test_heal_does_not_touch_mutations_or_broken_items(monkeypatch):
    char = _pc(hp=-3, wounds=[w.roll_wound_record(-3, w.SYNTHETIC_WOUNDS[-3])],
               carried=[{"name": "Rifle", "slots": 2, "broken": True}], table="synthetic")
    char["abilities"]["EGO"]["current"] = 0      # the rolled-once -2 already applied
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="Stutter")
    assert "healed" in out.lower() and char["wounds"] == []   # the heal really happened
    assert char["abilities"]["EGO"]["current"] == 0          # mutation untouched (deferred seam)
    assert char["inventory"]["carried"][0]["broken"] is True  # brokenness lives on the item


def test_heal_stacked_identical_wounds_heals_exactly_one(monkeypatch):
    # Duplicates stack (spec) and are field-identical — heal must not dead-end
    # on "be more specific"; it heals one copy and says so.
    recs = [w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7]),
            w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])]
    char = _pc(hp=-7, wounds=recs)
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="Crippling")
    assert "healed" in out.lower()
    assert len(char["wounds"]) == 1                # exactly one removed
    assert char["wounds_slots_used"] == 1
    assert "stacked" in out.lower()                # the remainder is surfaced


def test_ko_save_fail_sets_unconscious_with_rolled_rounds(monkeypatch):
    rec = w.roll_wound_record(0, w.BIOLOGICAL_WOUNDS[0])
    char = _pc(hp=0, wounds=[rec])
    _wire(monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 4)
    out = server._wound_dispatch(action="ko_save", character="Tester", result="fail")
    assert char["wounds"][0]["unconscious"] is True
    assert not char["wounds"][0].get("pending_con_save")
    assert "4" in out and ("auto-hit" in out.lower() or "automatically hit" in out.lower())


def test_ko_save_pass_clears_pending(monkeypatch):
    rec = w.roll_wound_record(0, w.BIOLOGICAL_WOUNDS[0])
    char = _pc(hp=0, wounds=[rec])
    _wire(monkeypatch, char)
    server._wound_dispatch(action="ko_save", character="Tester", result="pass")
    assert not char["wounds"][0].get("pending_con_save")
    assert not char["wounds"][0].get("unconscious")


def test_wake_clears_unconscious_keeps_wound(monkeypatch):
    rec = dict(w.roll_wound_record(-12, w.BIOLOGICAL_WOUNDS[-12]), unconscious=True)
    char = _pc(hp=-12, wounds=[rec])
    _wire(monkeypatch, char)
    server._wound_dispatch(action="wake", character="Tester")
    assert not char["wounds"][0].get("unconscious")
    assert char["wounds"]                                     # wound itself remains


def test_status_lists_wounds_and_derived(monkeypatch):
    char = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="status", character="Tester")
    assert "Crippling Wound" in out and "DEX" in out


def test_heal_ambiguous_or_missing_names_options(monkeypatch):
    char = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="zzz")
    assert "Crippling Wound" in out                           # options listed
    assert char["wounds"]                                     # nothing removed


# --- Local additions (contract allows adding, never weakening) ---

def test_status_party_wide_skips_unwounded_and_empty_says_so(monkeypatch):
    char = _pc(hp=5, wounds=[])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="status")
    assert "no active wounds" in out.lower()


def test_heal_ambiguous_lists_both_matches(monkeypatch):
    char = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7]),
                              w.roll_wound_record(-8, w.BIOLOGICAL_WOUNDS[-8])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="Wound")
    assert "Crippling Wound" in out and "Weakening Wound" in out
    assert len(char["wounds"]) == 2                           # nothing removed


def test_heal_persists_via_save_single_character(monkeypatch):
    char = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    data = {"characters": {"tester": char}}
    saved = []
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda *a, **k: saved.append(a))
    server._wound_dispatch(action="heal", character="Tester", wound="Crippling")
    assert saved                                              # mutating action persisted


def test_heal_notes_lifted_derived_effect(monkeypatch):
    # Synthetic -2 Supercoolant Leak carries deprived — heal line says it lifted.
    char = _pc(hp=-2, table="synthetic",
               wounds=[w.roll_wound_record(-2, w.SYNTHETIC_WOUNDS[-2])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="heal", character="Tester", wound="Supercoolant")
    assert "deprived" in out.lower()


def test_ko_save_requires_valid_result(monkeypatch):
    char = _pc(hp=0, wounds=[w.roll_wound_record(0, w.BIOLOGICAL_WOUNDS[0])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="ko_save", character="Tester", result="maybe")
    assert "pass" in out.lower() and "fail" in out.lower()
    assert char["wounds"][0].get("pending_con_save")          # untouched


def test_ko_save_no_pending_is_clear_message(monkeypatch):
    char = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="ko_save", character="Tester", result="fail")
    assert "no pending" in out.lower()
    assert not char["wounds"][0].get("unconscious")


def test_wake_clears_rounds_field_too(monkeypatch):
    rec = dict(w.roll_wound_record(0, w.BIOLOGICAL_WOUNDS[0]),
               unconscious=True, unconscious_rounds=3)
    rec.pop("pending_con_save", None)
    char = _pc(hp=0, wounds=[rec])
    _wire(monkeypatch, char)
    server._wound_dispatch(action="wake", character="Tester")
    assert "unconscious" not in char["wounds"][0]
    assert "unconscious_rounds" not in char["wounds"][0]


def test_unknown_action_lists_the_four(monkeypatch):
    char = _pc()
    _wire(monkeypatch, char)
    out = server._wound_dispatch(action="bogus")
    for a in ("status", "heal", "ko_save", "wake"):
        assert a in out


def test_ko_save_and_wake_persist(monkeypatch):
    # ko_save and wake must save the sheet, not just mutate memory.
    rec = w.roll_wound_record(0, w.BIOLOGICAL_WOUNDS[0])
    char = _pc(hp=0, wounds=[rec])
    data = {"characters": {"tester": char}}
    saves = []
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character",
                        lambda *a, **k: saves.append(a))
    monkeypatch.setattr(server.random, "randint", lambda a, b: 3)
    server._wound_dispatch(action="ko_save", character="Tester", result="fail")
    assert len(saves) == 1
    server._wound_dispatch(action="wake", character="Tester")
    assert len(saves) == 2


def test_status_party_wide_shows_wounded_skips_unwounded(monkeypatch):
    wounded = _pc(hp=-7, wounds=[w.roll_wound_record(-7, w.BIOLOGICAL_WOUNDS[-7])])
    clean = _pc()
    clean["name"] = "Cleanie"
    data = {"characters": {"tester": wounded, "cleanie": clean}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    out = server._wound_dispatch(action="status")
    assert "Tester" in out and "Crippling Wound" in out
    assert "Cleanie" not in out


def test_wake_clears_stale_duration(monkeypatch):
    # Waking from a timed shutdown must clear the duration too, or status/push
    # render a stale "(4 hours)" forever.
    rec = dict(w.roll_wound_record(-16, w.SYNTHETIC_WOUNDS[-16], rng=lambda a, b: 4),
               unconscious=True)
    char = _pc(hp=-16, wounds=[rec], table="synthetic")
    _wire(monkeypatch, char)
    server._wound_dispatch(action="wake", character="Tester")
    assert "duration" not in char["wounds"][0]
    assert not char["wounds"][0].get("unconscious")
