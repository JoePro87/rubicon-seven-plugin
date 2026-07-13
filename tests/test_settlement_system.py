"""Tests for settlement_system.py — Task A3 (detection helpers + validator integration)."""
import settlement_system as ss

SETTLEMENT_OK = """<!-- SITE: key=foo scene=settlement aliases="Foo" -->
# FOO — PREP
## NPCs
### ALDA — Keeper
**Location:** the_gate
**Role:** guards the gate
## TRADE GOODS AVAILABLE
- rope
"""

SETTLEMENT_NO_LOC = """<!-- SITE: key=foo scene=settlement aliases="Foo" -->
# FOO — PREP
## NPCs
### ALDA — Keeper
**Role:** guards the gate
"""


def test_is_settlement_true_for_scene_settlement():
    assert ss.is_settlement_prep(SETTLEMENT_OK) is True


def test_is_settlement_false_for_vault():
    assert ss.is_settlement_prep("<!-- SITE: key=v scene=vault_exploration -->\n# V") is False


def test_npcs_missing_location_listed():
    missing = ss.npcs_missing_location(SETTLEMENT_NO_LOC)
    assert missing == ["ALDA"]


def test_npcs_missing_location_empty_when_present():
    assert ss.npcs_missing_location(SETTLEMENT_OK) == []


def test_validate_prep_flags_missing_location(tmp_path, monkeypatch):
    import server
    p = tmp_path / "FOO_PREP.md"
    p.write_text(SETTLEMENT_NO_LOC, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.validate_prep_file("FOO_PREP.md")
    assert "missing **Location:**" in out


# ---------------------------------------------------------------------------
# Task B1: parse_settlement
# ---------------------------------------------------------------------------

def test_parse_roster_extracts_people():
    data = ss.parse_settlement(SETTLEMENT_OK)
    assert data["npcs"][0]["name"] == "ALDA"
    assert data["npcs"][0]["title"] == "Keeper"
    assert data["npcs"][0]["location"] == "the_gate"
    assert data["npcs"][0]["role"] == "guards the gate"


def test_parse_roster_trade_line():
    data = ss.parse_settlement(SETTLEMENT_OK)
    assert "rope" in data["trade"]


from pathlib import Path
# Resolve the campaign repo REPO-RELATIVELY (sibling of the engine repo) so this runs
# under the canonical Windows venv Python too — not via a hardcoded /mnt/c mount, which
# Windows Python can't see. __file__ -> tests/ -> engine root -> parent holding both repos.
_CAMP = Path(__file__).resolve().parent.parent.parent / "rubicon-seven-campaign"


def test_parse_real_dust_pilgrims_rest():
    f = _CAMP / "DUST_PILGRIMS_REST_PREP.md"
    if not f.exists():
        import pytest; pytest.skip("campaign fixture not present")
    data = ss.parse_settlement(f.read_text(encoding="utf-8"))
    names = {n["name"] for n in data["npcs"]}
    assert {"DRESSIK", "SARENN", "TILLUX", "VESSEL"} <= names
    assert all(n["location"] for n in data["npcs"])  # backfill (A1) holds


# ---------------------------------------------------------------------------
# Task B2: build_who_card
# ---------------------------------------------------------------------------

def test_card_lists_every_person_with_location():
    data = ss.parse_settlement(SETTLEMENT_OK)
    card = ss.build_who_card(data)
    assert "ALDA" in card and "the_gate" in card
    assert "rope" in card                      # trade line present
    assert "update_location_progress" in card  # card-carried stamp reminder (Phase D2)


def test_card_marks_dead_from_overlay():
    data = ss.parse_settlement(SETTLEMENT_OK)
    card = ss.build_who_card(data, npc_overlay={"ALDA": {"status": "DEAD", "day": 112}})
    assert "ALDA" in card and "dead" in card.lower() and "112" in card


# ---------------------------------------------------------------------------
# Task B3: resolve_settlement + build_settlement_index
# ---------------------------------------------------------------------------

def test_resolve_settlement_by_alias(tmp_path):
    (tmp_path / "FOO_PREP.md").write_text(SETTLEMENT_OK, encoding="utf-8")
    f = ss.resolve_settlement("foo", tmp_path)
    assert f and f.name == "FOO_PREP.md"


def test_resolve_settlement_none_for_unknown(tmp_path):
    assert ss.resolve_settlement("nope", tmp_path) is None


def test_resolve_settlement_apostrophe_insensitive(tmp_path):
    # A settlement whose name carries an apostrophe must resolve whether the caller
    # types a straight ' or a typographic ' (the tool transport routinely swaps them).
    marker = '<!-- SITE: key=pilgrims_rest scene=settlement aliases="Pilgrim\'s Rest" -->\n# PILGRIM\'S REST\n## NPCs\n### ALDA — Keeper\n**Location:** the_gate\n'
    (tmp_path / "PILGRIMS_REST_PREP.md").write_text(marker, encoding="utf-8")
    assert ss.resolve_settlement("Pilgrim's Rest", tmp_path) is not None      # straight U+0027
    assert ss.resolve_settlement("Pilgrim’s Rest", tmp_path) is not None  # curly U+2019


# ---------------------------------------------------------------------------
# Task E1-ext: _npc_blocks recognises "## KEY NPCs ..." section heading
# ---------------------------------------------------------------------------

KEY_NPCS_FIXTURE = """<!-- SITE: key=tessik_well scene=settlement aliases="Tessik Well" -->
# TESSIK WELL - PREP
## KEY NPCs (OBSERVABLE INFO)
### Grandmother Tessik (She/Her)
**Location:** grandmother_tent
**Role:** Clan Matriarch
### Kasim (He/Him)
**Location:** grandmother_tent
**Role:** The Patient
## TRADE GOODS AVAILABLE
- water
"""


def test_key_npcs_section_parsed():
    """_npc_blocks must handle '## KEY NPCs (OBSERVABLE INFO)' as well as '## NPCs'."""
    data = ss.parse_settlement(KEY_NPCS_FIXTURE)
    names = [n["name"] for n in data["npcs"]]
    assert "Grandmother Tessik" in names, f"Grandmother Tessik missing from {names}"
    assert "Kasim" in names, f"Kasim missing from {names}"
    # Locations must be filled (Location field is present in the fixture)
    for n in data["npcs"]:
        assert n["location"], f"{n['name']} has empty location"


def test_key_npcs_npc_header_parenthetical():
    """NPC headers of the form '### Name (pronoun)' are parsed correctly."""
    data = ss.parse_settlement(KEY_NPCS_FIXTURE)
    tessik = next(n for n in data["npcs"] if "Tessik" in n["name"])
    assert tessik["name"] == "Grandmother Tessik"
    # The pronoun/title fragment after the first paren may appear in title or be empty —
    # what matters is name is clean and location is correct.
    assert tessik["location"] == "grandmother_tent"


# ---------------------------------------------------------------------------
# Task C1: update_location_progress typed STATUS stamps
# ---------------------------------------------------------------------------

def test_progress_status_line_written(tmp_path, monkeypatch):
    import server
    p = tmp_path / "FOO_PREP.md"
    p.write_text(SETTLEMENT_OK + "\n## PROGRESS LOG\n", encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    # MCP-decorated functions leave unspecified Field() params as FieldInfo when
    # called directly in-process — pass all optional params explicitly.
    server.update_location_progress(
        location="FOO_PREP.md", day=112, summary="well repaired",
        items_taken=[], items_left=[], secrets_revealed=[], npcs_met=[],
        combat_notes="", consequences="",
        status=["the_well: REPAIRED", "party_standing: HOSTILE"])
    txt = p.read_text(encoding="utf-8")
    assert "STATUS: the_well: REPAIRED (Day 112)" in txt
    assert "STATUS: party_standing: HOSTILE (Day 112)" in txt


# ---------------------------------------------------------------------------
# Task C2: parse_place_status
# ---------------------------------------------------------------------------

def test_parse_place_status_from_progress_log():
    prog = "## PROGRESS LOG\n### Day 112 — Visit\n- STATUS: the_well: REPAIRED (Day 112)\n- STATUS: party_standing: HOSTILE (Day 112)\n"
    place = ss.parse_place_status(prog)
    assert place["the_well"]["status"] == "REPAIRED"
    assert place["party_standing"]["status"] == "HOSTILE"
    assert place["party_standing"]["day"] == 112
