import json

import site_markers as sm


# --- parse_site_marker -------------------------------------------------------

def test_parse_full_marker():
    text = '<!-- SITE: key=kalaxis scene=vault_exploration aliases="Kalaxis|Kalaxis Arcology|the arcology" -->\n# X'
    m = sm.parse_site_marker(text)
    assert m == {"key": "kalaxis", "scene": "vault_exploration",
                 "aliases": ["Kalaxis", "Kalaxis Arcology", "the arcology"]}


def test_parse_defaults_scene_when_missing():
    m = sm.parse_site_marker('<!-- SITE: key=tessik_well aliases="Tessik Well" -->')
    assert m["scene"] == "vault_exploration"
    assert m["key"] == "tessik_well"


def test_parse_no_marker_returns_none():
    assert sm.parse_site_marker("# Just a prep\n**Type:** vault") is None
    assert sm.parse_site_marker("") is None


def test_parse_marker_below_dungeon_line():
    text = ("<!-- DUNGEON: map=kalaxis enforce=vault-liveness -->\n"
            '<!-- SITE: key=kalaxis scene=vault_exploration aliases="Kalaxis" -->\n# X')
    m = sm.parse_site_marker(text)
    assert m["key"] == "kalaxis" and m["aliases"] == ["Kalaxis"]


# --- detect_named_sites ------------------------------------------------------

def test_detect_word_boundary_case_insensitive():
    idx = {"kalaxis": {"aliases": ["Kalaxis", "the arcology"]}}
    assert sm.detect_named_sites("Let's head into kalaxis at dawn.", idx) == ["kalaxis"]
    assert sm.detect_named_sites("We approach THE ARCOLOGY.", idx) == ["kalaxis"]
    assert sm.detect_named_sites("Kalaxistan is elsewhere.", idx) == []


def test_detect_skips_generic_and_short_aliases():
    idx = {"x": {"aliases": ["the camp", "ru"]}}  # stopword + too-short
    assert sm.detect_named_sites("we make the camp by the ru", idx) == []


def test_detect_multiple_sites_one_prompt():
    idx = {"kalaxis": {"aliases": ["Kalaxis"]}, "thyricost": {"aliases": ["Thyricost"]}}
    out = sm.detect_named_sites("From Kalaxis we ride to Thyricost.", idx)
    assert set(out) == {"kalaxis", "thyricost"}


def test_detect_empty_inputs():
    assert sm.detect_named_sites("", {"k": {"aliases": ["Kalaxis"]}}) == []
    assert sm.detect_named_sites("Kalaxis", {}) == []


def test_detect_alias_with_punctuation_matches():
    # lookaround boundaries (not \b) so a punctuation-bounded alias matches its text
    idx = {"cave": {"aliases": ["C.A.V.E"]}, "pit": {"aliases": ["(the pit)"]}}
    assert sm.detect_named_sites("we descend into C.A.V.E now", idx) == ["cave"]
    assert sm.detect_named_sites("down (the pit) we go", idx) == ["pit"]


# --- build_site_index --------------------------------------------------------

def test_build_index_marker_prep(tmp_path):
    (tmp_path / "KALAXIS_PREP.md").write_text(
        "<!-- DUNGEON: map=kalaxis enforce=vault-liveness -->\n"
        '<!-- SITE: key=kalaxis scene=vault_exploration aliases="Kalaxis|the arcology" -->\n# K',
        encoding="utf-8")
    idx = sm.build_site_index(tmp_path)
    assert idx["kalaxis"]["aliases"] == ["Kalaxis", "the arcology"]
    assert idx["kalaxis"]["prep_file"] == "KALAXIS_PREP.md"


def test_build_index_dungeon_fallback(tmp_path):
    (tmp_path / "OUTER_REACH_PREP.md").write_text(
        "<!-- DUNGEON: map=outer_reach enforce=vault-liveness -->\n# OR", encoding="utf-8")
    idx = sm.build_site_index(tmp_path)
    assert idx["outer_reach"]["aliases"] == ["Outer Reach"]  # humanised derived alias


def test_build_index_maps_fallback_and_resume(tmp_path):
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "midden_oracle_map.json").write_text(
        json.dumps({"prep_file": "MIDDEN_ORACLE_PREP.md", "current_turn": 7,
                    "last_seen_day": 134, "created_day": 130}), encoding="utf-8")
    idx = sm.build_site_index(tmp_path)
    rec = idx["midden_oracle"]
    assert rec["aliases"] == ["Midden Oracle"]
    assert rec["current_turn"] == 7 and rec["last_seen_day"] == 134
    assert rec["prep_file"] == "MIDDEN_ORACLE_PREP.md"


def test_build_index_marker_wins_over_fallback(tmp_path):
    (tmp_path / "KALAXIS_PREP.md").write_text(
        "<!-- DUNGEON: map=kalaxis enforce=vault-liveness -->\n"
        '<!-- SITE: key=kalaxis aliases="Kalaxis|the dead arcology" -->\n# K', encoding="utf-8")
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "kalaxis_map.json").write_text(
        json.dumps({"current_turn": 3}), encoding="utf-8")
    idx = sm.build_site_index(tmp_path)
    assert idx["kalaxis"]["aliases"] == ["Kalaxis", "the dead arcology"]  # marker aliases kept
    assert idx["kalaxis"]["current_turn"] == 3  # resume context still merged


# --- phrase_reminder integration --------------------------------------------

def _reflex_with(monkeypatch, tmp_path, user_text, active_map="", scene="vault_exploration",
                 state=None):
    """Drive phrase_reminder._build_reflex_block with a synthetic campaign + state."""
    import hooks.phrase_reminder as pr
    monkeypatch.setattr(pr, "_read_active_map", lambda: active_map)
    monkeypatch.setattr(pr, "_read_scene_type", lambda: scene)
    monkeypatch.setattr(pr, "_read_active_prep_files", lambda: [])
    st = state if state is not None else {}
    block = pr._build_reflex_block(tmp_path, st, user_text)
    return block, st


def _make_site(tmp_path):
    (tmp_path / "KALAXIS_PREP.md").write_text(
        "<!-- DUNGEON: map=kalaxis enforce=vault-liveness -->\n"
        '<!-- SITE: key=kalaxis scene=vault_exploration aliases="Kalaxis|the arcology" -->\n# K',
        encoding="utf-8")


def test_named_site_pushes_enter_site(monkeypatch, tmp_path):
    _make_site(tmp_path)
    block, st = _reflex_with(monkeypatch, tmp_path, "We finally reach Kalaxis.")
    assert "enter_site" in block and "KALAXIS_PREP.md" in block
    assert 'map_name="kalaxis"' in block  # push carries the map key, not just the prep
    assert "kalaxis" in st["open_site_scene"]


def test_active_site_is_not_pushed(monkeypatch, tmp_path):
    _make_site(tmp_path)
    st = {"open_site_scene": {"kalaxis": {"prep_file": "KALAXIS_PREP.md"}}}
    block, st2 = _reflex_with(monkeypatch, tmp_path, "I search the rubble.",
                              active_map="kalaxis", state=st)
    assert "kalaxis" not in st2["open_site_scene"]  # cleared because it is active
    assert "Player named" not in block


def test_clear_is_case_insensitive(monkeypatch, tmp_path):
    # DM enters with a non-lowercase map_name -> Active Map "Kalaxis" must still clear
    _make_site(tmp_path)
    st = {"open_site_scene": {"kalaxis": {"prep_file": "KALAXIS_PREP.md", "ttl": 1}}}
    block, st2 = _reflex_with(monkeypatch, tmp_path, "I press deeper.",
                              active_map="Kalaxis", scene="social", state=st)
    assert "kalaxis" not in st2["open_site_scene"]
    assert "Player named" not in block


def test_passing_mention_fades(monkeypatch, tmp_path):
    # A one-off mention nags briefly then fades on its own (no permanent URGENT pin).
    _make_site(tmp_path)
    st = {}
    b1, st = _reflex_with(monkeypatch, tmp_path, "I wonder if Kalaxis still stands.",
                          scene="social", state=st)
    assert "Player named" in b1                      # turn 1: fires
    b2, st = _reflex_with(monkeypatch, tmp_path, "I look around warily.",
                          scene="social", state=st)
    assert "Player named" in b2                      # turn 2: still nags (ttl grace)
    b3, st = _reflex_with(monkeypatch, tmp_path, "I keep walking north.",
                          scene="social", state=st)
    assert "Player named" not in b3                  # turn 3: faded
    assert not st.get("open_site_scene")


def test_remention_refreshes_ttl(monkeypatch, tmp_path):
    _make_site(tmp_path)
    st = {}
    _reflex_with(monkeypatch, tmp_path, "Toward Kalaxis.", scene="social", state=st)
    _reflex_with(monkeypatch, tmp_path, "Still nothing.", scene="social", state=st)
    # re-name on what would be the fade turn -> stays alive
    b3, st = _reflex_with(monkeypatch, tmp_path, "Kalaxis at last, its towers near.",
                          scene="social", state=st)
    assert "Player named" in b3
    assert "kalaxis" in st["open_site_scene"]


def test_non_site_text_no_push(monkeypatch, tmp_path):
    # scene="social" so the pre-existing exploration-scene nag stays silent and we
    # isolate the detector: no site named -> no push, empty open_site_scene.
    _make_site(tmp_path)
    block, st = _reflex_with(monkeypatch, tmp_path, "I sharpen my blade and rest.",
                             scene="social")
    assert "enter_site" not in block
    assert not st.get("open_site_scene")


def test_resume_context_in_push(monkeypatch, tmp_path):
    _make_site(tmp_path)
    (tmp_path / "maps").mkdir()
    (tmp_path / "maps" / "kalaxis_map.json").write_text(
        json.dumps({"prep_file": "KALAXIS_PREP.md", "current_turn": 7, "last_seen_day": 134}),
        encoding="utf-8")
    block, st = _reflex_with(monkeypatch, tmp_path, "Back to the arcology at last.")
    assert "turn 7" in block and "day 134" in block
