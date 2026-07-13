"""Certification of forge tables against the book extraction.

Verifies the tables flagged as truncated during the content-forge revision:
cacklemaw_den and hegemony_outpost get full 20-row book data (VoV Referee's
Toolbox); helm/shield were full-coverage already but carried two wrong
shield names. Weather is a separate Joe ruling (the book system is a d6
hex-chart walk, not a d20 table) and is not asserted here.
"""

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TABLES_PATH = REPO_ROOT / "data" / "content_forge_tables.json"


def _load(name):
    data = json.loads(TABLES_PATH.read_text(encoding="utf-8"))
    return data["tables"][name]


def _coverage(table):
    """Expand roll ranges to the set of integers covered."""
    covered = []
    for entry in table["entries"]:
        spec = str(entry["roll"])
        if "-" in spec:
            lo, hi = spec.split("-")
            covered.extend(range(int(lo), int(hi) + 1))
        else:
            covered.append(int(spec))
    return covered


def _row(table, roll):
    for entry in table["entries"]:
        spec = str(entry["roll"])
        if "-" in spec:
            lo, hi = spec.split("-")
            if int(lo) <= roll <= int(hi):
                return entry["fields"]
        elif int(spec) == roll:
            return entry["fields"]
    raise AssertionError(f"roll {roll} not covered")


# --- coverage: every flagged table covers 1-20 exactly once --------------

def test_full_d20_coverage_no_filler():
    for name in ["cacklemaw_den", "hegemony_outpost", "helm", "shield"]:
        table = _load(name)
        covered = _coverage(table)
        assert sorted(covered) == list(range(1, 21)), name
        text = json.dumps(table["entries"])
        assert "Roll twice" not in text, name
        assert "Various" not in text, name


# --- cacklemaw den: book spans land on the right rows ---------------------

def test_cacklemaw_sworn_to_spans():
    t = _load("cacklemaw_den")
    assert _row(t, 5)["Sworn To"] == "Mama Hecklehaw"
    assert _row(t, 6)["Sworn To"] == "Mama Gloatgrim"
    assert _row(t, 15)["Sworn To"] == "Mama Yawningfool"
    assert _row(t, 16)["Sworn To"] == "Nana Rictus"
    assert _row(t, 18)["Sworn To"] == "Nana Rictus"
    assert _row(t, 19)["Sworn To"] == "Nana Blacklaugh"


def test_cacklemaw_book_rows():
    t = _load("cacklemaw_den")
    assert _row(t, 4)["They Want"] == "Meat"
    assert _row(t, 8)["They Want"] == "Water"
    assert _row(t, 20)["Weapons"] == "Teeth and Claws"
    assert _row(t, 20)["Activity"] == "Fighting (Faa Nomads)"
    assert _row(t, 17)["Activity"] == "Fighting (Other Monster)"


# --- hegemony outpost: invented unit gone, book units in -------------------

def test_outpost_no_invented_artillery():
    t = _load("hegemony_outpost")
    assert "Artillery" not in json.dumps(t["entries"])


def test_outpost_unit_type_spans():
    t = _load("hegemony_outpost")
    assert _row(t, 2)["Unit Type"] == "Deserters (d6)"
    assert _row(t, 3)["Unit Type"] == "Scouts (d6)"
    assert _row(t, 10)["Unit Type"] == "Rangers (d8)"
    assert _row(t, 14)["Unit Type"] == "Synth-Hunting Team (d8)"
    assert _row(t, 18)["Unit Type"] == "Legionaries (d20)"
    assert _row(t, 19)["Unit Type"] == "Ornithopter Crew (d8)"


def test_outpost_book_rows():
    t = _load("hegemony_outpost")
    assert _row(t, 17)["Activity"] == "Combat With Monster"
    assert _row(t, 19)["Activity"] == "Combat With Faa"
    assert _row(t, 20)["Commander"] == "Beloved"
    assert _row(t, 20)["Mood"] == "Mournful"


# --- shield: the two wrong names fixed -------------------------------------

def test_shield_book_names():
    t = _load("shield")
    assert _row(t, 6)["Shield"] == "Wooden Shield"
    assert _row(t, 16)["Shield"] == "Ceramic Shield"


# --- settlements: certified vs the book (tier-1 CH-parity restore) ----------
# The prior settlement tables were fabricated (Anarchy/Plutocracy/Meritocracy…
# under real book-table names). These now come byte-for-byte from the certified
# data/rules/rulebook/tables.json. Guard against regression back to invention.

def test_settlement_tables_full_d20_coverage():
    for name in ["settlement_government", "settlement_values",
                 "settlement_asset", "settlement_problem", "settlement_change"]:
        assert sorted(_coverage(_load(name))) == list(range(1, 21)), name


def test_settlement_government_is_book_not_fabricated():
    t = _load("settlement_government")
    assert _row(t, 1)["Adjective"] == "Secretive"
    assert _row(t, 1)["Form"] == "Tyranny"
    assert _row(t, 1)["Faith"] == "Church of the Promised Sun"
    blob = json.dumps(t["entries"])
    for fab in ["Anarchy", "Plutocracy", "Meritocracy", "Military Junta",
                "AI Overseer", "Faa Council", "Hegemony Client"]:
        assert fab not in blob, f"fabricated government entry still present: {fab}"


def test_settlement_values_book_rows():
    r1 = _row(_load("settlement_values"), 1)
    assert r1["Praises"] == "Acts of Violence"
    assert r1["Despises"] == "Law Abiding Dullards"
    assert r1["Lacks"] == "History"


def test_settlement_asset_problem_change_book_rows():
    assert _row(_load("settlement_asset"), 1)["Asset"] == "Matter Fabricator"
    assert _row(_load("settlement_problem"), 1)["Problem"] == "Power Struggle"
    assert _row(_load("settlement_change"), 1)["Change"] == "Argument"


# --- location-type selector: certified d20 order (tier-2) -------------------
# The master location_type table + the roll->subtable map were misordered
# (roll 9 gave Trade Post, 16 gave Science Mystic) with non-canon "Hegemony
# Fort/Protectorate". Both now follow certified table-region-location-type.

def test_location_type_master_is_certified():
    t = _load("location_type")
    names = {int(e["roll"]): e["fields"]["Location"] for e in t["entries"]}
    assert names[9] == "Cacklemaw Den"
    assert names[16] == "Fortress"
    assert names[17] == "Trade Post"
    assert names[18] == "Archive"
    assert names[20] == "Anomaly"
    blob = json.dumps(t["entries"])
    assert "Hegemony Fort" not in blob and "Hegemony Protectorate" not in blob


def test_location_type_map_matches_certified_order():
    m = json.loads(TABLES_PATH.read_text(encoding="utf-8"))["tables"]["_location_type_map"]
    assert m["2"] == "settlement"
    assert m["9"] == "cacklemaw_den"
    assert m["16"] == "fortress"
    assert m["17"] == "trade_post"
    assert m["18"] == "archive"


def test_fortress_table_book_rows():
    t = _load("fortress")
    assert sorted(_coverage(t)) == list(range(1, 21))
    r1 = _row(t, 1)
    assert r1["Location"] == "High Cliffs"
    assert r1["Garrisoned By"] == "The New Hegemony"


# --- monster lair d100: invented Sphinx removed, book order restored (tier-3) --

def test_monster_lair_book_fixes():
    t = _load("monster_lair")
    by = {str(e["roll"]): e["fields"] for e in t["entries"]}
    assert len(t["entries"]) == 100
    # #2/#3 in book order (Anthrophagi at 2, Amaranthine Death-Worms at 3)
    assert "Anthrophagi" in by["2"]["Inhabitants"]
    assert "Amaranthine Death-Worm" in by["3"]["Inhabitants"]
    # Kronophage spelling
    assert by["44"]["Inhabitants"] == "Kronophage"
    blob = json.dumps(t["entries"])
    assert "Khronophage" not in blob
    # invented Sphinx gone; real Sawbone Drones restored at #74
    assert "Sphinx" not in blob
    assert "Sawbone Drones" in by["74"]["Inhabitants"]


# --- landmarks d100 + region place-names: certified, rebuilt from PDF (tier-3) --

def test_landmarks_certified_d100():
    t = _load("landmarks")
    assert sorted(_coverage(t)) == list(range(1, 101))
    by = {str(e["roll"]): e["fields"]["Landmark"] for e in t["entries"]}
    assert by["5"] == "Rock Resembling Boot"          # skill had fabricated this slot
    assert by["43"] == "Toxic Geyser, Plumes of Pink Fluid"
    blob = json.dumps(t["entries"])
    for fab in ["Spiral Bone Tower", "Mechanical Forest", "Gravity Well", "Portal Frame"]:
        assert fab not in blob, f"fabricated landmark still present: {fab}"


def test_region_place_names_certified():
    cols = json.loads(TABLES_PATH.read_text(encoding="utf-8"))["tables"]["_region_place_names"]["columns"]
    for cat in ["settlements", "ruins", "holy_places", "hegemony_places", "autarchic", "mystic"]:
        assert len(cols[cat]) == 20, cat
    assert cols["settlements"][0] == "Jakara"
    assert cols["ruins"][19] == "Scorched Whiterot"
    assert cols["hegemony_places"][0] == "Arid Agrizone KP3"
    assert len(cols["faa_nomad"]) == 3  # partial column in the preview book
