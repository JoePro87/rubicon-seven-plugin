"""PC-gen Tasks 1a/1b - ancestry + gear data integrity (all 10 ancestries)."""
from ancestries import (ANCESTRIES, ANCESTRY_D10, GEAR_A, GEAR_B,
                        ability_roll, roll_gear, roll_sparks)

BATCH = ["true-kin", "cacogen", "synth", "newbeast", "neobloom",
         "mycomorph", "faa-nomad", "cacklemaw-exile", "planeyfolk",
         "lithling"]


def test_d10_covers_ten_ancestries():
    assert sorted(ANCESTRY_D10) == list(range(1, 11))
    assert len(set(ANCESTRY_D10.values())) == 10


def test_batch_tables_complete():
    for key in BATCH:
        a = ANCESTRIES[key]
        for t in a["spark_tables"]:
            if t.get("band_table"):
                assert sorted(t["bands"]) == [(1, 5), (6, 10), (11, 15), (16, 20)]
                assert all(len(v) == 20 for v in t["bands"].values())
            else:
                assert sorted(t["rows"]) == list(range(1, 21)), (key, t["title"])
                for r, cols in t["rows"].items():
                    assert set(cols) == set(t["columns"]), (key, t["title"], r)
                    assert all(isinstance(v, str) and v for v in cols.values())


def test_no_pdf_artifacts():
    import json, re

    def jsonable(o):  # band tables use tuple keys, which json rejects
        if isinstance(o, dict):
            return {str(k): jsonable(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [jsonable(x) for x in o]
        return o

    blob = json.dumps(jsonable({k: ANCESTRIES[k] for k in BATCH}))
    assert "\\u00bf" not in blob and "\\ufffd" not in blob
    # "LogLang" is a real in-world proper noun (synth Synthetic Mind rule),
    # not a PDF camel-squish; exclude it like "McK".
    assert not re.search(r"[a-z][A-Z]",
                         blob.replace("McK", "").replace("LogLang", ""))


def test_truekin_caste_bands_flat():
    rows = [t for t in ANCESTRIES["true-kin"]["spark_tables"]
            if "CASTE" in t["columns"]][0]["rows"]
    assert rows[1]["CASTE"] == rows[4]["CASTE"]          # 1-4 Servitor
    assert "Servitor" in rows[4]["CASTE"]
    assert "Freeholder" in rows[5]["CASTE"] and "Freeholder" in rows[9]["CASTE"]
    assert "Exultant" in rows[18]["CASTE"] and "Exultant" in rows[20]["CASTE"]


def test_cacogen_creation_hook():
    assert ANCESTRIES["cacogen"]["creation_hooks"] == {"mutations_at_creation": 3}


def test_ability_roll_lowest_die():
    rolls = iter([4, 2, 6])
    bonus, dice = ability_roll(lambda a, b: next(rolls))
    assert bonus == 2 and dice == [4, 2, 6]


def test_roll_sparks_reads_whole_row():
    seq = iter([1])
    out = roll_sparks("true-kin", lambda a, b: next(seq, 1))
    appearance = out["appearance"]
    assert appearance["BODY"] == "Tall" and appearance["ATTIRE"] == "Rags"


def test_planeyfolk_flat_bands_flat():
    rows = [t for t in ANCESTRIES["planeyfolk"]["spark_tables"]
            if "HOW YOU BECAME FLAT" in t["columns"]][0]["rows"]
    col = "HOW YOU BECAME FLAT"
    assert rows[1][col] == rows[5][col]                  # 1-5 Parents
    assert "Parents were Planeyfolk" in rows[5][col]
    assert "in utero" in rows[6][col] and "in utero" in rows[7][col]
    assert "Quantum Daemon" in rows[8][col] and "Quantum Daemon" in rows[9][col]
    assert "gateway" in rows[10][col] and "gateway" in rows[11][col]
    assert "ate hypergeometric food" in rows[12][col]
    assert rows[12][col] == rows[13][col]
    assert "inducted you" in rows[14][col] and rows[14][col] == rows[15][col]
    assert "tesseract" in rows[16][col] and rows[16][col] == rows[17][col]
    assert "hypergeometrician" in rows[18][col]
    assert rows[18][col] == rows[20][col]                # 18-20 accident


def test_lithling_size_bands_flat():
    rows = [t for t in ANCESTRIES["lithling"]["spark_tables"]
            if "SIZE" in t["columns"]][0]["rows"]
    assert rows[1]["SIZE"] == "Child-like" and rows[5]["SIZE"] == "Child-like"
    assert rows[6]["SIZE"] == "Small" and rows[10]["SIZE"] == "Small"
    assert rows[11]["SIZE"] == "Moderate" and rows[14]["SIZE"] == "Moderate"
    assert rows[15]["SIZE"] == "Large" and rows[17]["SIZE"] == "Large"
    assert rows[18]["SIZE"] == "Imposing" and rows[20]["SIZE"] == "Imposing"


def test_lithling_creation_hook():
    assert ANCESTRIES["lithling"]["creation_hooks"] == {
        "hp_override_dice": "10d8"}


def test_gear_tables_complete():
    # Engine item schema (item_slots.py): integer `uses` counters for (xN)
    # suffixes, `usage_die` notation for (UdX) suffixes.
    for table in (GEAR_A, GEAR_B):
        assert sorted(table) == list(range(1, 21))
        for item in table.values():
            assert isinstance(item["name"], str) and item["name"]
            assert "(" not in item["name"]  # suffixes parsed, not inlined
            if "uses" in item:
                assert isinstance(item["uses"], int) and item["uses"] > 0
            if "usage_die" in item:
                assert item["usage_die"].startswith("Ud")
    # Spot-checks read off the page (digits from the PDF text layer)
    assert GEAR_A[1] == {"name": "Flashbang", "uses": 5}
    assert GEAR_A[18] == {"name": "Tube of Glue", "usage_die": "Ud8"}
    assert GEAR_A[19] == {"name": "Ball Bearings", "usage_die": "Ud20"}
    assert GEAR_B[2] == {"name": "Oxygen Mask", "usage_die": "Ud6"}
    assert GEAR_B[16] == {"name": "Anti-toxin", "uses": 3}


def test_roll_gear_one_roll_each_column():
    seq = iter([1, 2])
    out = roll_gear(lambda a, b: next(seq))
    assert out["rolls"] == (1, 2)
    assert out["gear_a"]["name"] == "Flashbang"
    assert out["gear_b"]["name"] == "Oxygen Mask"


def test_npc_generator_description_names_every_ancestry():
    """The generate(npc) ancestry description is where a DM-model learns the
    valid values. If it lists fewer than the d10 roster, the unlisted ancestries
    go invisible -- the exact bug that stranded cacklemaw-exile + planeyfolk.
    Guard the description against drifting out of sync with the roster."""
    import inspect
    import generators
    field = inspect.signature(
        generators._generate_npc).parameters["ancestry"].default
    desc = getattr(field, "description", "") or ""
    for key in ANCESTRY_D10.values():
        assert ANCESTRIES[key]["name"] in desc, key
