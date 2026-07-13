from scene_state import scene_dedup_elements, context_dedup_elements


def test_arc_and_emotion_become_keyed_elements():
    els = scene_dedup_elements(arc="**ARC:** a shut crossing", emotional_state="| Creenash | resolved |")
    keys = {k for (_s, k, _c) in els}
    assert keys == {"scene:arc", "scene:emotional_state"}


def test_arc_element_carries_arc_content():
    els = scene_dedup_elements(arc="**ARC:** a shut crossing", emotional_state=None)
    arc_content = next(c for (_s, k, c) in els if k == "scene:arc")
    assert "**ARC:**" in arc_content
    assert "shut crossing" in arc_content


def test_emotion_element_carries_header_and_content():
    els = scene_dedup_elements(arc=None, emotional_state="| Creenash | resolved |")
    section, key, content = els[0]
    assert key == "scene:emotional_state"
    assert "**EMOTIONAL STATE:**" in content
    assert "Creenash" in content


def test_none_values_produce_no_elements():
    assert scene_dedup_elements(arc=None, emotional_state=None) == []


def test_whitespace_only_values_produce_no_elements():
    assert scene_dedup_elements(arc="   ", emotional_state="   ") == []


def test_never_folds_location_or_secrets():
    """scene_dedup_elements must ONLY ever emit arc / emotional_state keys —
    never location, beats, mood, or any classified family."""
    els = scene_dedup_elements(arc="x", emotional_state="y")
    keys = {k for (_s, k, _c) in els}
    assert keys <= {"scene:arc", "scene:emotional_state"}


def test_context_matches_become_per_entry_keyed_elements():
    rendered = [("vela", "[PEOP] **vela** (CANONICAL): bio"),
                ("creenash", "[PEOP] **creenash** (CORRECTED): bio2")]
    els = context_dedup_elements(rendered)
    assert ("CONTEXT", "lore:vela", "[PEOP] **vela** (CANONICAL): bio") in els
    assert {k for (_s, k, _c) in els} == {"lore:vela", "lore:creenash"}


def test_context_skips_empty():
    assert context_dedup_elements([("", "x"), ("vela", "")]) == []


def test_context_skips_whitespace_only():
    assert context_dedup_elements([("   ", "x"), ("vela", "   ")]) == []


def test_context_groups_same_keyword_lines_into_one_element():
    rendered = [("vela", "[SCEN] **vela** (CANONICAL): scene bio"),
                ("vela", "[PEOP] **vela** (CANONICAL): people bio")]
    els = context_dedup_elements(rendered)
    # one element for the keyword, containing BOTH distinct bios (no content dropped)
    assert len(els) == 1
    section, key, content = els[0]
    assert (section, key) == ("CONTEXT", "lore:vela")
    assert "scene bio" in content and "people bio" in content


def test_context_dedups_exactly_identical_lines():
    rendered = [("vela", "[SCEN] **vela** (CANONICAL): same"),
                ("vela", "[SCEN] **vela** (CANONICAL): same")]
    els = context_dedup_elements(rendered)
    assert len(els) == 1
    assert els[0][2].count("same") == 1  # exact duplicate collapsed


def test_context_preserves_distinct_keywords_order():
    rendered = [("vela", "[PEOP] **vela** (X): a"),
                ("creenash", "[PEOP] **creenash** (X): b")]
    els = context_dedup_elements(rendered)
    assert [k for (_s, k, _c) in els] == ["lore:vela", "lore:creenash"]
