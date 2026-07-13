"""Forge-backlog ingest guard (CRIMSON HOUND 07-05-26, certified 2026-07-05).

Covers the content-forge backlog ingest:
- the 7 wilderness-location sub-tables added to the rulebook/get_table path
- the criminal-gang tables now carry BOOK content (homebrew retired)
- Eigin Oasis + Caeba in the Maw keyed-location entries
- the Gnomon gazetteer + 7 faction entries (already resident in lore_additions)
- the content_forge generator serves book-accurate oasis/wreck/science_mystic
  (regression guard for the corrupted-extraction repair)

Paths are resolved repo-relatively (never a hardcoded mount).
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

RULEBOOK = REPO / "data" / "rules" / "rulebook"


def _load(name):
    with open(RULEBOOK / name, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def tables():
    return _load("tables.json")


@pytest.fixture(scope="module")
def by_id(tables):
    return {t["id"]: t for t in tables["rolling_tables"] + tables["reference_tables"]}


# ---------------- Step 1: the 7 wilderness sub-tables ----------------

SUBTABLE_COLS = {
    "table-grave": ["location", "grave_for", "burial_method", "grave_quirk"],
    "table-holy-place": ["location", "focus_of_worship", "holy_to", "curated_by"],
    "table-oasis": ["the_water", "whats_here", "whos_here", "custom"],
    "table-ruin": ["what_was_it", "and_then", "and_now", "appearance", "shape", "other_feature"],
    "table-science-mystic": ["abode", "the_mystic", "researching", "they_want"],
    "table-trade-post": ["location", "who_trades_here", "what_is_traded"],
    "table-wreck": ["vehicle", "condition", "cargo", "cause_of_crash"],
}


@pytest.mark.parametrize("tid,cols", SUBTABLE_COLS.items())
def test_subtable_present_shape_and_count(by_id, tid, cols):
    t = by_id.get(tid)
    assert t is not None, f"{tid} missing from tables.json"
    assert t["die"] == "d20"
    assert len(t["entries"]) == 20
    for i, e in enumerate(t["entries"]):
        assert e["roll"] == i + 1
        assert [k for k in e if k != "roll"] == cols
    assert "Crimson Hound printed p." in t["source"]


def test_oasis_merged_who_cells_resolved(by_id):
    who = {e["roll"]: e["whos_here"] for e in by_id["table-oasis"]["entries"]}
    # book merged cells (visual read p.179): 1-4 Trading Caravan, 5-7 Faa Nomads
    assert all(who[r] == "Trading Caravan" for r in (1, 2, 3, 4))
    assert all(who[r] == "Faa Nomads" for r in (5, 6, 7))
    assert who[8] == "Hegemony Rangers"
    assert who[20] == "Famous Musician"


def test_ruin_has_second_subtable_and_paired_and_now(by_id):
    ruin = by_id["table-ruin"]["entries"]
    # the page's second d20 sub-table must be present (was missing from prior extraction)
    for col in ("appearance", "shape", "other_feature"):
        assert ruin[0][col], f"ruin missing {col}"
    assert ruin[0]["shape"] == "Dome" and ruin[19]["shape"] == "Ziggurat"
    # AND NOW is a 10-entry paired-row column: rolls 1 & 2 share a value
    assert ruin[0]["and_now"] == ruin[1]["and_now"] == "Desolate Shell"
    assert ruin[18]["and_now"] == ruin[19]["and_now"] == "Holy Place"


# ---------------- Step 2: gang tables now carry BOOK content ----------------

def test_gang_tables_are_book_not_homebrew(by_id):
    for tid, page in (
        ("table-criminal-gang-drama", "p.267"),
        ("table-criminal-gang-name", "p.268"),
        ("table-criminal-gang-activity", "p.268"),
    ):
        t = by_id[tid]
        assert "homebrew" not in t, f"{tid} still flagged homebrew"
        assert page in t["source"] and "Crimson Hound printed" in t["source"]
        assert "Homebrew" not in t["source"] and "R2" not in t["source"]


def test_gang_name_distinctive_book_row_and_old_split_gone(by_id):
    name = by_id["table-criminal-gang-name"]["entries"]
    r1 = name[0]
    # distinctive BOOK row: NAME A "Golden Street" / NAME B "Mob"
    assert r1["name_a"] == "Golden Street" and r1["name_b"] == "Mob"
    # the homebrew-only column split ("Golden" / "Street Mob") must be gone
    assert not any(e["name_a"] == "Golden" and e["name_b"] == "Street Mob" for e in name)


def test_gang_drama_book_details(by_id):
    drama = by_id["table-criminal-gang-drama"]["entries"]
    # book diaeresis restored
    assert any("Young, Naïve Orphan" == e["npc_a"] for e in drama)
    # row 20 SOURCE OF DRAMA is printed blank in the book (homebrew had filled it)
    assert drama[19]["source_of_drama"] == ""


# ---------------- Step 3: Eigin + Caeba keyed locations ----------------

def test_eigin_oasis_keyed(by_id):
    t = by_id.get("table-location-eigin-oasis")
    assert t is not None
    assert t["lookup_key"] == "room"
    rooms = [e["room"] for e in t["entries"]]
    numbered = [r for r in rooms if r[0].isdigit()]
    assert len(numbered) == 9, f"expected 9 keyed locations, got {numbered}"
    assert any("Eigin Sanctum" in r for r in numbered)
    assert any("Messenger Moth Roost" in r for r in numbered)


def test_caeba_keyed_town_and_corpse(by_id):
    t = by_id.get("table-location-caeba-in-the-maw")
    assert t is not None
    assert t["lookup_key"] == "room"
    rooms = [e["room"] for e in t["entries"]]
    town = [r for r in rooms if r.startswith("Town ")]
    assert len(town) == 12, f"expected 12 town locations, got {town}"
    # flag resolution: town 5 name is Worker's Barracks (not 'Workers' Quarters')
    assert any("Worker's Barracks" in r for r in town)
    corpse_numbered = [r for r in rooms if r.startswith("Corpse ") and r.split()[1].isdigit()]
    assert len(corpse_numbered) == 14, f"expected corpse rooms 1-14, got {corpse_numbered}"
    # Petrichor AV 22 is real (lithling hide); Thunder owns the 20 HP line, not the Grandfather
    detail = " ".join(e["detail"] for e in t["entries"])
    assert "AV 22" in detail
    assert "Item Slots 50" in detail  # on Thunder's block


# ---------------- Step 4: Gnomon gazetteer + 7 factions (already resident) ----------------

def test_gnomon_gazetteer_and_factions_present():
    lore = _load("lore_additions.json")
    ids = {e["id"] for e in lore["entries"]}
    # gazetteer
    assert "lore-gnomon-city" in ids
    # the 7 named factions / their leaders must all be resolvable
    required = [
        "lore-house-lonrot",            # 1 House Lonrot
        "lore-fifth-hegemony-legion",   # 2 The Fifth Hegemony
        "lore-water-baron-ancamulla",   # 3 Water Baron's Militia
        "lore-faith-promised-sun",      # 4 Church of the Promised Sun
        "lore-abbess-faunia",           #   + leader
        "lore-prieval-prise",           # 5 Preival's Crew (leader Prieval Prise)
        "lore-longtooth-jak",           # 6 Friends of Jak (leader Longtooth Jak)
        "lore-crimson-court",           # 7 The Crimson Court
        "lore-nyxia-wall-shadow",       #   + leader Nyxia
    ]
    missing = [i for i in required if i not in ids]
    assert not missing, f"missing Gnomon faction lore: {missing}"


# ---------------- Regression: content_forge generator serves book values ----------------

def test_content_forge_generator_book_accurate():
    import content_forge
    forge = content_forge.ContentForge(REPO / "data")
    cases = [
        ("oasis", 1, "Who's Here (x2)", "Trading Caravan"),
        ("oasis", 8, "Who's Here (x2)", "Hegemony Rangers"),
        ("wreck", 9, "Vehicle", "Orbital Satellite"),
        ("wreck", 9, "Cause of Crash", "Simply Abandoned"),
        ("science_mystic", 7, "The Mystic", "Ostentatious New-Tiger"),
        ("science_mystic", 4, "Researching", "Antigravity Field"),
    ]
    for tname, roll, col, expected in cases:
        entry, _, err = forge.roll_on_table(tname, roll)
        assert err is None, f"{tname} roll {roll}: {err}"
        assert entry["fields"][col] == expected, f"{tname} r{roll} {col}={entry['fields'][col]!r}"
    # no leftover "(Roll twice)" extraction artifacts in the repaired tables
    for tname in ("oasis", "wreck", "science_mystic"):
        for e in forge.tables[tname]["entries"]:
            assert not any("Roll twice" in str(v) for v in e["fields"].values())
