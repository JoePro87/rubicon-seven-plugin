import json
from pathlib import Path
import pytest
from map_system import MapSystem

@pytest.fixture
def camp(tmp_path):
    (tmp_path / "maps").mkdir()
    return tmp_path

def _write_prep(camp, name, body):
    (camp / name).write_text(body, encoding="utf-8")
    return name

VAULT_PREP = """# TEST VAULT — PREP
**Type:** Vault

## ROOM: entry
**Name:** The Entry
**Entrance:** true
**Connections:** n→hall

## ROOM: hall
**Name:** The Hall
**Connections:** s→entry

## ENCOUNTERS

| d6 | Encounter | Context |
|----|-----------|---------|
| 1 | Dust Wraith | drifts from the vents |
"""

AMBIENT_PREP = """# BONEWELL RUIN — PREP
**Type:** Site

## ENCOUNTERS

| d6 | Encounter | Context |
|----|-----------|---------|
| 1 | Scavenger pack | sniffing the ash |
"""

def test_init_then_resume_keeps_turn(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    st = ms.get_map_state("test_vault")
    st["current_turn"] = 7
    ms.save_map_state("test_vault", st)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")  # must RESUME
    assert ms.get_map_state("test_vault")["current_turn"] == 7

def test_resume_preserves_discovery(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    st = ms.get_map_state("test_vault")
    st["discovery"]["hall"] = {"searched": True, "secrets_revealed": [], "taken": ["x"]}
    ms.save_map_state("test_vault", st)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")  # resume
    d = ms.get_map_state("test_vault")["discovery"]
    assert d["hall"]["searched"] is True
    assert d["hall"]["taken"] == ["x"]

def test_new_site_has_two_clocks(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md", current_day=130)
    st = ms.get_map_state("test_vault")
    assert st["current_turn"] == 0
    assert st["created_day"] == 130
    assert st["last_seen_day"] == 130

def test_ambient_site_no_rooms_still_inits(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    out = ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md")
    st = ms.get_map_state("bonewell_ruin")
    assert st is not None
    assert st["party_location"] == "ambient"
    assert st["kind"] == "site"
    assert "⚠️" not in out

def test_roomed_site_baton_nudges_render(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    out = ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    assert 'render' in out and 'map_name="test_vault"' in out  # walkable map -> offer to draw it


def test_ambient_site_baton_no_render_nudge(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    out = ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md")
    assert 'render' not in out  # no rooms -> nothing to draw


def test_resume_roomed_site_nudges_render(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    out = ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")  # RESUME path
    assert out.startswith("▶ RESUMING") and 'render' in out


def test_save_is_atomic_tmp_cleaned(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    assert not list((camp / "maps").glob("*.tmp"))

def test_legacy_state_loads_with_defaults(camp):
    # NOTE: file naming convention is "{map_name}_map.json"; map_name="old_map"
    # therefore loads from "old_map_map.json".
    (camp / "maps" / "old_map_map.json").write_text(json.dumps({
        "map_name": "old", "current_turn": 3, "rooms": {"a": {"id": "a"}},
        "party_location": "a", "exploration_log": [], "encounters_rolled": []
    }), encoding="utf-8")
    ms = MapSystem(camp)
    st = ms.get_map_state("old_map")
    assert st["current_turn"] == 3
    assert st.get("kind") in ("vault", "site")

H3_ROOM_PREP = """# TESSIK WELL — PREP

### ROOM: plaza
**Name:** The Plaza
**Connections:** n→market

### ROOM: market
**Name:** The Market

## ENCOUNTER TABLE: TESSIK WELL ENVIRONS

| d6 | Encounter | Context |
|----|-----------|---------|
| 1 | Dust pilgrims | trudging through |
"""

def test_h3_rooms_parse(camp):
    ms = MapSystem(camp)
    rooms = ms._parse_rooms_from_prep(H3_ROOM_PREP)
    assert set(rooms.keys()) == {"plaza", "market"}

def test_encounter_table_header_variant_parses(camp):
    ms = MapSystem(camp)
    enc = ms._parse_encounters_from_prep(H3_ROOM_PREP)
    assert enc["type"] == "random_table"
    assert any(e["encounter"].lower().startswith("dust pilgrims") for e in enc["table_entries"])

def test_turn_based_table_parses(camp):
    ms = MapSystem(camp)
    enc = ms._parse_encounters_from_prep(
        "## ENCOUNTERS\n- **Turn 3:** A wraith stirs.\n- **Turn 7:** Ceiling groans.\n")
    assert enc["type"] == "turn_based"
    assert {t["turn"] for t in enc["turn_triggers"]} == {3, 7}

def test_no_encounters_section_returns_none(camp):
    ms = MapSystem(camp)
    assert ms._parse_encounters_from_prep("# Just prose, no table") is None

def test_h2_rooms_still_parse_and_subsections_not_split(camp):
    # regression: h2 vault rooms with ### subsections must NOT be split by the subsection
    prep = ("## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nDust everywhere.\n\n"
            "### Loot\nA coin.\n\n## ROOM: vault\n**Name:** Vault\n")
    ms = MapSystem(camp)
    rooms = ms._parse_rooms_from_prep(prep)
    assert set(rooms.keys()) == {"hall", "vault"}
    # the hall's raw block should retain its subsections (not truncated at ### Observables)
    assert "Observables" in rooms["hall"].get("prep_content", "")
    assert "Loot" in rooms["hall"].get("prep_content", "")


import random as _random

class _FixedRandom:
    def __init__(self, val): self.val = val
    def randint(self, a, b): return self.val

def test_encounters_stored_on_create(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    st = ms.get_map_state("bonewell_ruin")
    assert st["encounters"]["type"] == "random_table"

def test_encounter_rolls_real_table(camp, monkeypatch):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)  # table entry 1 = "Scavenger pack"
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    st = ms.get_map_state("bonewell_ruin")
    monkeypatch.setattr(_random, "SystemRandom", lambda: _FixedRandom(1))
    out = ms._auto_encounter_check(st)
    assert "Scavenger pack" in out

def test_turn_based_trigger_fires_once_on_its_turn(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TB_PREP.md",
        "# TB — PREP\n## ROOM: a\n**Name:** A\n**Entrance:** true\n\n"
        "## ENCOUNTERS\n- **Turn 3:** The wraith manifests.\n")
    ms.init_or_resume_map("tb", "TB_PREP.md")
    st = ms.get_map_state("tb")
    st["current_turn"] = 3
    fired = ms._fire_turn_triggers(st)
    assert any("wraith manifests" in f for f in fired)
    st["current_turn"] = 4
    assert ms._fire_turn_triggers(st) == []   # does not re-fire later

def test_turn_based_trigger_not_refired_same_turn(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TB_PREP.md",
        "# TB — PREP\n## ROOM: a\n**Name:** A\n**Entrance:** true\n\n"
        "## ENCOUNTERS\n- **Turn 3:** The wraith manifests.\n")
    ms.init_or_resume_map("tb", "TB_PREP.md")
    st = ms.get_map_state("tb")
    st["current_turn"] = 3
    ms._fire_turn_triggers(st)
    assert ms._fire_turn_triggers(st) == []   # already fired this turn -> empty

def test_no_table_gives_improvise_prompt(camp, monkeypatch):
    ms = MapSystem(camp)
    _write_prep(camp, "BARE_PREP.md", "# Bare — PREP\n## ROOM: a\n**Name:** A\n**Entrance:** true\n")
    ms.init_or_resume_map("bare", "BARE_PREP.md")
    st = ms.get_map_state("bare")
    monkeypatch.setattr(_random, "SystemRandom", lambda: _FixedRandom(1))
    out = ms._auto_encounter_check(st)
    assert "improvise" in out.lower() or "no table" in out.lower()

def test_encounters_stored_for_rooms_site(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)   # has ## ROOM: + table
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md", current_day=130)
    # reload fresh from disk and confirm encounters persisted
    st = ms.get_map_state("test_vault")
    assert st.get("encounters") is not None
    assert st["encounters"]["type"] == "random_table"

def test_turn_trigger_fires_after_being_jumped(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TB_PREP.md",
        "# TB — PREP\n## ROOM: a\n**Name:** A\n**Entrance:** true\n\n"
        "## ENCOUNTERS\n- **Turn 2:** The wraith manifests.\n")
    ms.init_or_resume_map("tb", "TB_PREP.md")
    st = ms.get_map_state("tb")
    st["current_turn"] = 3            # jumped past turn 2 (e.g. darkness move)
    fired = ms._fire_turn_triggers(st)
    assert any("wraith manifests" in f for f in fired)   # still fires, late


RICH_ROOM_PREP = """# RICH — PREP
## ROOM: hall
**Name:** The Hall
**Entrance:** true

### Observables
A vast hall, dust thick on the floor.

### Loot
- Corroded stylus (in the rubble) — INT DC 14.

### DM Notes
Don't explain the bones.

**Secret:** A pressure plate opens the vault if prayed to.
"""

def test_obvious_surfaces_on_enter(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "RICH_PREP.md", RICH_ROOM_PREP)
    ms.init_or_resume_map("rich", "RICH_PREP.md")
    out = ms.enter_room("rich", "hall")
    assert "vast hall" in out.lower()
    assert "corroded stylus" not in out.lower()   # hidden, not yet searched
    assert "pressure plate" not in out.lower()     # secret, never auto

def test_hidden_surfaces_on_search(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "RICH_PREP.md", RICH_ROOM_PREP)
    ms.init_or_resume_map("rich", "RICH_PREP.md")
    ms.enter_room("rich", "hall")
    out = ms.search_room("rich", "hall")
    assert "corroded stylus" in out.lower()
    assert "secret" in out.lower()                 # hint that a secret EXISTS
    assert "pressure plate" not in out.lower()     # never the secret body

def test_search_state_persists(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "RICH_PREP.md", RICH_ROOM_PREP)
    ms.init_or_resume_map("rich", "RICH_PREP.md")
    ms.enter_room("rich", "hall")
    ms.search_room("rich", "hall")
    st = ms.get_map_state("rich")
    assert st["discovery"]["hall"]["searched"] is True

def test_dm_notes_surface_on_enter_as_dm_channel(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "RICH_PREP.md", RICH_ROOM_PREP)
    ms.init_or_resume_map("rich", "RICH_PREP.md")
    out = ms.enter_room("rich", "hall")
    assert "don't explain the bones" in out.lower()
    assert "[dm]" in out.lower()                    # marked DM-channel


def test_secret_subsection_header_never_leaks(camp):
    prep = ("# S — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nA plain hall.\n\n"
            "### Secret\nThe CRYPT_KEY is under the altar.\n")
    _write_prep(camp, "S_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("s", "S_PREP.md")
    assert "crypt_key" not in ms.enter_room("s", "hall").lower()
    assert "crypt_key" not in ms.search_room("s", "hall").lower()

def test_multiline_secret_never_leaks(camp):
    prep = ("# S — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nA plain hall.\n\n"
            "**Secret:** A lever here\nwhich when pulled FLOODS_THE_HALL.\n")
    _write_prep(camp, "S2_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("s2", "S2_PREP.md")
    assert "floods_the_hall" not in ms.enter_room("s2", "hall").lower()

def test_single_star_secret_never_leaks(camp):
    prep = ("# S — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nA plain hall.\n\n"
            "*Secret:* SINGLE_STAR opens it.\n")
    _write_prep(camp, "S3_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("s3", "S3_PREP.md")
    assert "single_star" not in ms.enter_room("s3", "hall").lower()


def test_enter_site_resumes_via_init_or_resume(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    out1 = ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    assert "SITE" in out1 or "turn 0" in out1
    st = ms.get_map_state("bonewell_ruin"); st["current_turn"] = 4
    ms.save_map_state("bonewell_ruin", st)
    out2 = ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=158)
    assert "RESUMING" in out2 and "turn 4" in out2


def test_stamp_active_site_left(camp, monkeypatch):
    import server
    # point server's map_system at the tmp campaign
    from map_system import MapSystem as _MS
    monkeypatch.setattr(server, "map_system", _MS(camp))
    _write_prep(camp, "S_PREP.md", AMBIENT_PREP)
    server.map_system.init_or_resume_map("s", "S_PREP.md", current_day=130)
    server._stamp_active_site_left("s", 137)
    st = server.map_system.get_map_state("s")
    assert st["last_seen_day"] == 137
    assert st["last_left_turn"] == 0


def test_stamp_active_site_left_noop_when_missing(monkeypatch, camp):
    import server
    from map_system import MapSystem as _MS
    monkeypatch.setattr(server, "map_system", _MS(camp))
    # no such site — must not raise
    server._stamp_active_site_left("nonexistent", 140)
    server._stamp_active_site_left(None, 140)


def test_enter_site_sets_active_pointer(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    calls = []
    ms.on_active_site = lambda name: calls.append(name)
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    assert calls == ["bonewell_ruin"]            # set on create
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=140)
    assert calls == ["bonewell_ruin", "bonewell_ruin"]   # re-armed on resume


def test_on_active_site_failure_does_not_break_create(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    def boom(name): raise RuntimeError("x")
    ms.on_active_site = boom
    out = ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    assert ms.get_map_state("bonewell_ruin") is not None   # site still created despite callback raise


def test_spatial_summary_renders_ambient_site(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=130)
    st = ms.get_map_state("bonewell_ruin"); st["current_turn"] = 5
    ms.save_map_state("bonewell_ruin", st)
    out = ms.spatial_summary("bonewell_ruin")
    assert out is not None and "5" in out and "ambient" in out.lower()


def test_spatial_summary_vault_still_renders(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("test_vault", "TEST_VAULT_PREP.md")
    out = ms.spatial_summary("test_vault")
    assert out is not None   # rooms-based path unbroken


def test_active_site_briefing_line(camp, monkeypatch):
    import server
    from map_system import MapSystem as _MS
    monkeypatch.setattr(server, "map_system", _MS(camp))
    _write_prep(camp, "S_PREP.md", AMBIENT_PREP)
    server.map_system.init_or_resume_map("s", "S_PREP.md", current_day=130)
    st = server.map_system.get_map_state("s"); st["current_turn"] = 3; st["last_seen_day"] = 134
    server.map_system.save_map_state("s", st)
    # force _active_vault_turn to report our site active
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("s", 3))
    line = server._active_site_briefing_line()
    assert "s" in line and "turn 3" in line.lower() and "134" in line


def test_active_site_briefing_line_empty_when_none(monkeypatch):
    import server
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    assert server._active_site_briefing_line() == ""


# ── Content-reveal SECRET-LEAK regression probes (workflow review) ──

def test_titled_secret_header_no_leak_on_enter(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nA plain hall.\n\n"
            "### SECRET 3 — The Vault\nThe CROWNKEY lies beneath the altar.\n")
    _write_prep(camp, "T_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t", "T_PREP.md")
    assert "crownkey" not in ms.enter_room("t", "hall").lower()
    assert "crownkey" not in ms.search_room("t", "hall").lower()

def test_titled_secret_colon_no_leak(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Secret: Hidden Door\nLEAKDOOR opens west.\n")
    _write_prep(camp, "T2_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t2", "T2_PREP.md")
    assert "leakdoor" not in ms.enter_room("t2", "hall").lower()

def test_structured_loot_not_on_enter_but_on_search(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n"
            "**Loot:** GOLDIDOL worth 200, silver chalice\n")
    _write_prep(camp, "T3_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t3", "T3_PREP.md")
    assert "goldidol" not in ms.enter_room("t3", "hall").lower()   # hidden until search
    assert "goldidol" in ms.search_room("t3", "hall").lower()      # surfaces on search

def test_secret_connection_target_not_on_enter_or_search(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n"
            "**Secrets:** lever -> VAULTROOM (search the throne)\n")
    _write_prep(camp, "T4_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t4", "T4_PREP.md")
    assert "vaultroom" not in ms.enter_room("t4", "hall").lower()
    assert "vaultroom" not in ms.search_room("t4", "hall").lower()

def test_inline_secret_in_observables_no_leak(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nA dusty room. Secret: INLINELEAK behind the wall. The floor creaks.\n")
    _write_prep(camp, "T5_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t5", "T5_PREP.md")
    out = ms.enter_room("t5", "hall").lower()
    assert "inlineleak" not in out
    assert "dusty room" in out   # the non-secret observable prose still surfaces

def test_titled_hidden_cache_is_hidden_tier(camp):
    prep = ("# T — PREP\n## ROOM: hall\n**Name:** Hall\n**Entrance:** true\n\n"
            "### Observables\nPlain.\n\n### Hidden Cache\nA STASHITEM in the floor.\n")
    _write_prep(camp, "T6_PREP.md", prep)
    ms = MapSystem(camp); ms.init_or_resume_map("t6", "T6_PREP.md")
    assert "stashitem" not in ms.enter_room("t6", "hall").lower()   # not on enter
    assert "stashitem" in ms.search_room("t6", "hall").lower()      # on search


TWO_COL_TABLE_PREP = """# TC — PREP
## ROOM: a
**Name:** A
**Entrance:** true

## ENCOUNTER TABLE: TC

| d6 | Encounter |
|----|-----------|
| 1 | **Alpha** — drifts close |
| 2 | **Beta** — a burst of wind |
| 3 | **Gamma** — color drains |
| 4 | **Delta** — distant sound |
| 5 | **Epsilon** — tracks in dust |
| 6 | **Zeta** — nothing but cold |
"""

def test_two_column_table_keeps_all_rows(camp):
    ms = MapSystem(camp)
    enc = ms._parse_encounters_from_prep(TWO_COL_TABLE_PREP)
    assert enc["type"] == "random_table"
    assert sorted(e["roll"] for e in enc["table_entries"]) == [1, 2, 3, 4, 5, 6]  # no half-drop
    assert enc["dice_size"] == 6
    assert all(e["context"] == "" for e in enc["table_entries"])  # 2-col -> empty context

def test_three_column_table_still_parses(camp):
    body = ("## ENCOUNTERS\n\n| d6 | Encounter | Context |\n|----|----|----|\n"
            "| 1 | Wraith | from the vents |\n| 2 | Crickets | nesting |\n")
    ms = MapSystem(camp)
    enc = ms._parse_encounters_from_prep(body)
    assert sorted(e["roll"] for e in enc["table_entries"]) == [1, 2]
    assert enc["table_entries"][0]["context"] == "from the vents"

def test_real_kalaxis_table_parses_all_rows(camp):
    # the real KALAXIS d6 encounter table is 2-column; all 6 rows must parse
    import os
    kal = r"C:\rubicon-seven-campaign\KALAXIS_PREP.md"
    if os.path.exists(kal):
        ms = MapSystem(camp)
        enc = ms._parse_encounters_from_prep(open(kal, encoding="utf-8").read())
        if enc and enc["type"] == "random_table":
            rolls = sorted(e["roll"] for e in enc["table_entries"])
            assert rolls == list(range(1, max(rolls) + 1))  # contiguous, no dropped rows


def test_get_day_callback_threads_current_day(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "BONEWELL_RUIN_PREP.md", AMBIENT_PREP)
    ms.get_day = lambda: 142
    # simulate the enter_site dispatch path: it pulls the day from the callback
    day = ms.get_day() if callable(getattr(ms, "get_day", None)) else None
    ms.init_or_resume_map("bonewell_ruin", "BONEWELL_RUIN_PREP.md", current_day=day)
    st = ms.get_map_state("bonewell_ruin")
    assert st["created_day"] == 142
    assert st["last_seen_day"] == 142


def test_reset_rebuilds_and_zeroes_turn(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("v", "TEST_VAULT_PREP.md", current_day=10)
    st = ms.get_map_state("v"); st["current_turn"] = 9; ms.save_map_state("v", st)
    ms.init_or_resume_map("v", "TEST_VAULT_PREP.md", current_day=20, reset=True)
    assert ms.get_map_state("v")["current_turn"] == 0   # rebuilt


def test_reset_with_missing_prep_preserves_old_state(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "TEST_VAULT_PREP.md", VAULT_PREP)
    ms.init_or_resume_map("v", "TEST_VAULT_PREP.md", current_day=10)
    st = ms.get_map_state("v"); st["current_turn"] = 5; ms.save_map_state("v", st)
    out = ms.init_or_resume_map("v", "NONEXISTENT_PREP.md", current_day=20, reset=True)
    assert "not found" in out.lower()
    assert ms.get_map_state("v")["current_turn"] == 5   # old state intact, not destroyed


def test_legacy_created_day_not_cross_polluted(camp):
    import json
    (camp / "maps" / "leg_map.json").write_text(json.dumps({
        "map_name": "leg", "current_turn": 2, "rooms": {"a": {"id": "a"}},
        "party_location": "a", "last_seen_day": 7, "exploration_log": [], "encounters_rolled": []
    }), encoding="utf-8")
    ms = MapSystem(camp)
    st = ms.get_map_state("leg")
    assert st["created_day"] is None        # NOT back-filled from last_seen_day
    assert st["last_seen_day"] == 7


def test_resume_different_prep_warns_keeps_state(camp):
    ms = MapSystem(camp)
    _write_prep(camp, "A_PREP.md", VAULT_PREP)
    _write_prep(camp, "B_PREP.md", AMBIENT_PREP)
    ms.init_or_resume_map("x", "A_PREP.md", current_day=10)
    st = ms.get_map_state("x"); st["current_turn"] = 4; ms.save_map_state("x", st)
    out = ms.init_or_resume_map("x", "B_PREP.md", current_day=20)   # different prep, resume
    assert ms.get_map_state("x")["current_turn"] == 4               # state preserved
    assert ms.get_map_state("x")["prep_file"] == "A_PREP.md"        # not silently swapped


def test_is_exploration_scene_exact_token():
    import server as _server
    assert _server._is_exploration_scene("vault_exploration") is True
    assert _server._is_exploration_scene("vault_exploration (deep level)") is True
    assert _server._is_exploration_scene("VAULT_EXPLORATION") is True
    # the leak cases -- must be False:
    assert _server._is_exploration_scene("social (post-exploration debrief)") is False
    assert _server._is_exploration_scene("downtime - planning the next exploration") is False
    assert _server._is_exploration_scene("travel (exploration of the wastes)") is False
    assert _server._is_exploration_scene("settlement") is False
    assert _server._is_exploration_scene("") is False
    assert _server._is_exploration_scene(None) is False


def test_inject_spatial_state_no_leak_on_annotated_social():
    """Free-text 'exploration' annotation on a non-exploration scene must NOT
    trigger the active-site fallback injection even with an Active Map set."""
    import server as _server
    parsed = {
        "scene_type": "social (post-exploration debrief)",
        "active_map": "some_site",
        "active_prep": "None",
    }
    assert _server._inject_spatial_state(parsed) is None
