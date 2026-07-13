from canon_delivery import filter_elements, filter_elements_with_stats


def _state(turn, delivered=None, last_canon_turn=0):
    return {
        "turn_count": turn,
        "last_canon_turn": last_canon_turn,
        "canon_delivered": delivered or {},
    }


def test_first_call_ships_full_content():
    els = [("VOICE", "voice:Creenash", "CREENASH full guide text")]
    out, st = filter_elements(els, _state(1))
    assert "CREENASH full guide text" in out
    assert st["canon_delivered"]["voice:Creenash"]["t"] == 1


def test_second_identical_call_emits_pointer_not_content():
    els = [("VOICE", "voice:Creenash", "CREENASH full guide text")]
    out1, st1 = filter_elements(els, _state(1))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements(els, st2)
    assert "CREENASH full guide text" not in out2
    assert "Creenash" in out2
    assert "T1" in out2  # pointer references original delivery turn


def test_changed_content_reships_full():
    st = _state(1)
    out1, st1 = filter_elements([("VOICE", "voice:Creenash", "v1")], st)
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements([("VOICE", "voice:Creenash", "v2 CHANGED")], st2)
    assert "v2 CHANGED" in out2


def test_cast_change_ships_only_newcomer():
    els1 = [("VOICE", "voice:Creenash", "CREE"), ("VOICE", "voice:Vela", "VELA")]
    out1, st1 = filter_elements(els1, _state(1))
    els2 = els1 + [("VOICE", "voice:LookHome", "LOOKHOME new")]
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements(els2, st2)
    assert "LOOKHOME new" in out2
    assert "CREE" not in out2
    assert "VELA" not in out2
    assert "Creenash" in out2 and "Vela" in out2  # pointers


def test_none_key_is_always_fresh():
    els = [("SCENE", None, "scene state line")]
    out1, st1 = filter_elements(els, _state(1))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements(els, st2)
    assert "scene state line" in out1
    assert "scene state line" in out2  # never deduped


def test_compaction_reships_everything():
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, st1 = filter_elements(els, _state(5))
    # turn_count regresses below last_canon_turn => compaction
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=5)
    out2, _ = filter_elements(els, st2)
    assert "CREE" in out2


def test_backstop_reships_after_30_turns():
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, st1 = filter_elements(els, _state(1))
    st2 = _state(31, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements(els, st2, backstop_turns=30)
    assert "CREE" in out2


def test_pointer_groups_by_section():
    els = [
        ("VOICE", "voice:Creenash", "CREE"),
        ("DISTILLATIONS", "distill:rel_x", "REL X"),
    ]
    _, st1 = filter_elements(els, _state(1))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements(els, st2)
    assert "VOICE:" in out2
    assert "DISTILLATIONS:" in out2


def test_backstop_does_not_reship_before_30_turns():
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, st1 = filter_elements(els, _state(1))
    st_at_29 = _state(30, st1["canon_delivered"], last_canon_turn=1)
    out_at_29, _ = filter_elements(els, st_at_29, backstop_turns=30)
    assert "CREE" not in out_at_29  # diff=29, not yet stale


def test_compaction_wipes_stale_keys_from_state():
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, st1 = filter_elements(els, _state(5))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=5)  # regression => compaction
    _, new_state = filter_elements(els, st2)
    assert list(new_state["canon_delivered"].keys()) == ["voice:Creenash"]
    assert new_state["canon_delivered"]["voice:Creenash"]["t"] == 2


def test_duplicate_key_in_one_call_takes_first():
    els = [("VOICE", "voice:X", "FIRST"), ("VOICE", "voice:X", "SECOND")]
    out, st = filter_elements(els, _state(1))
    assert "FIRST" in out
    assert "SECOND" not in out
    assert st["canon_delivered"]["voice:X"]["h"]  # recorded


def test_preserves_unrelated_state_keys():
    """Regression: the new_state filter_elements returns must keep keys it does
    not own (e.g. injected_npcs, which the stop hook reads). check_canon writes
    new_state back to disk, so wiping injected_npcs here would cause false
    'uninjected NPC' stop-hook warnings every turn NPCs are present.
    """
    st = _state(1)
    st["injected_npcs"] = ["Vela", "Kess"]
    st["some_other_key"] = {"nested": True}
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, new_state = filter_elements(els, st)
    assert new_state["injected_npcs"] == ["Vela", "Kess"]
    assert new_state["some_other_key"] == {"nested": True}


def test_filter_returns_fresh_count_when_requested():
    els = [
        ("VOICE", "voice:Creenash", "CREE"),
        ("VOICE", "voice:Vela", "VELA"),
        ("SCENE", None, "live"),
    ]
    out, st, stats = filter_elements_with_stats(els, _state(1))
    assert stats["fresh"] == 2          # two keyed elements shipped full
    assert stats["pointers"] == 0
    assert stats["always_fresh"] == 1   # the None-key element


def test_stats_counts_pointers_on_redelivery():
    els = [("VOICE", "voice:Creenash", "CREE")]
    _, st1, _ = filter_elements_with_stats(els, _state(1))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    _, _, stats = filter_elements_with_stats(els, st2)
    assert stats["pointers"] == 1   # unchanged key collapses to a pointer
    assert stats["fresh"] == 0


def test_none_last_canon_turn_does_not_crash():
    # State files can carry an explicit null last_canon_turn; must not raise.
    state = {"turn_count": 3, "last_canon_turn": None, "canon_delivered": {}}
    out, st, stats = filter_elements_with_stats(
        [("VOICE", "voice:Vela", "VELA GUIDE")], state
    )
    assert "VELA GUIDE" in out          # ships full (treated as fresh)
    assert stats["fresh"] == 1
    assert st["last_canon_turn"] == 3   # healed to an int


def test_none_turn_count_does_not_crash():
    state = {"turn_count": None, "last_canon_turn": None, "canon_delivered": {}}
    out, st, _ = filter_elements_with_stats(
        [("VOICE", "voice:Vela", "VELA")], state
    )
    assert "VELA" in out
    assert st["last_canon_turn"] == 0


def test_scene_block_lifecycle_with_compaction():
    """full -> fold -> change -> fold -> compaction-reset -> full."""
    emo_v1 = ("EMOTIONAL STATE", "scene:emotional_state", "**EMOTIONAL STATE:**\nCreenash: resolved")
    # T1: first delivery -> full
    out1, st1 = filter_elements([emo_v1], _state(1))
    assert "Creenash: resolved" in out1
    # T2: unchanged -> pointer
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, st2b = filter_elements([emo_v1], st2)
    assert "Creenash: resolved" not in out2
    assert "emotional_state" in out2 and "✓T1" in out2  # pointer label + original-delivery marker
    # T3: content change -> full again
    emo_v2 = ("EMOTIONAL STATE", "scene:emotional_state", "**EMOTIONAL STATE:**\nCreenash: afraid")
    st3 = _state(3, st2b["canon_delivered"], last_canon_turn=2)
    out3, st3b = filter_elements([emo_v2], st3)
    assert "Creenash: afraid" in out3
    # Compaction: simulate post_compact wiping canon_delivered
    st_compacted = _state(4, delivered={}, last_canon_turn=3)
    out4, _ = filter_elements([emo_v2], st_compacted)
    assert "Creenash: afraid" in out4, "after compaction the block must re-ship full"


def test_recoverable_section_pointer_carries_lorebook_hint():
    # "lore:vela" -> display key "vela" in the pointer (prefix stripped)
    el = ("CONTEXT", "lore:vela", "[PEOP] **vela** (CANONICAL): full bio")
    out1, st1 = filter_elements([el], _state(1))
    assert "full bio" in out1  # first delivery full
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements([el], st2)
    assert "full bio" not in out2
    assert "vela ✓T1" in out2
    assert "↻ lorebook(view, vela)" in out2  # self-healing recovery path


def test_nonrecoverable_section_pointer_has_no_hint():
    el = ("VOICE", "voice:Vela", "VELA guide")
    out1, st1 = filter_elements([el], _state(1))
    st2 = _state(2, st1["canon_delivered"], last_canon_turn=1)
    out2, _ = filter_elements([el], st2)
    assert "lorebook(view" not in out2
