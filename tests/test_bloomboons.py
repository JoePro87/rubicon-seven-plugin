"""C2 Bloomboons (spec 2026-06-12-c2-bloomboons-design.md).

Three surfaces:
1. level_up_bloomboon repeat rule - book fix (CH p.049): a repeat roll takes
   the NEXT boon down (wrap 20->1 as engine default); all-20 owned refuses.
2. engine_effects consumption - av_base_bonus (both AV sheet shapes),
   trigger/attack/daily_use stamping with name-dedup, dm_levers prose block,
   push discipline (character get).
3. Annotation integrity on the REAL campaign table - names pinned to the
   hardcoded book list, name/effect text never altered, script idempotent.

Fixture idioms from test_xp_levelup.py (split-file char in the conftest
temp campaign dir); real-table tests resolve the engine-bundled table at
data/rules/NEOBLOOM_BLOOMBOONS.json (the source the engine actually reads)
per the judge-against-the-real-runner rule.
"""
import json
import shutil
from pathlib import Path

import pytest

import server
import engine_core
from scripts.annotate_bloomboons_c2 import ANNOTATIONS, BOOK_NAMES, main as annotate_main


# The 20 book names, hardcoded INDEPENDENTLY of the script (the pin must
# catch a drifted script too).
PINNED_NAMES = [
    "Plated Bark", "Mirrored Leaves", "Barbed Bark", "Shield Vines",
    "Lashing Vines", "Vantablooms", "Empathogen Pollen", "Soporific Pollen",
    "Neurotoxic Pollen", "Toxic Sap", "Vampiric Roots", "Luftpods",
    "Tesla Blossom", "Seed Cannon", "Medicinal Fruit", "Sticky Sap",
    "Sapling Retainers", "Blast Pods", "Grafting", "Puppeteer Roots",
]

# The certified effect text (pre-annotation snapshot of the campaign table,
# which passed book certification clean). engine_effects must never alter it.
PINNED_EFFECTS = {
    "Plated Bark": "Gain +2 base AV",
    "Mirrored Leaves": "DEX save to reflect Beam attacks back at source. DIS when hiding",
    "Barbed Bark": "Opponents who miss melee attacks against you suffer d4 damage",
    "Shield Vines": "Spend 2 DEX to grow Shield Vine (+1 Armour). DEX loss can't heal until vines shed",
    "Lashing Vines": "Spend 2 STR to grow Lashing Vine (+1 melee attack, d6). STR loss can't heal until vines shed",
    "Vantablooms": "Light-absorbing blooms create shadow cloud. Ranged attacks have DIS to hit you. ADV to hide from pursuers",
    "Empathogen Pollen": "Once per day, release pollen cloud. Biological creatures EGO save or become friendly/harmless for d6 rounds",
    "Soporific Pollen": "Once per day, release pollen cloud. Biological creatures EGO save or fall asleep for d6 rounds",
    "Neurotoxic Pollen": "Once per day, release pollen cloud. Biological creatures CON save or reduced to 1 HP",
    "Toxic Sap": "Emit 1 dose poisonous sap per day (d10 TOX). Creatures who bite/eat you must CON save vs d10 TOX",
    "Vampiric Roots": "Root on Biological creatures, dealing d4 damage/round. Heal HP equal to damage. Target STR save to tear you off",
    "Luftpods": "Sprout lighter-than-air gas pods. Can fly slowly/predictably. Can act as parachute for one other character",
    "Tesla Blossom": "Spend 2 CON to grow Tesla Blossom (extra ranged electrical attack d6/round, ADV vs Synths). CON loss can't heal until shed",
    "Seed Cannon": "Spend 2 DEX to grow Seed Cannon (extra ranged attack d6/round). DEX loss can't heal until shed",
    "Medicinal Fruit": "Daily golden fruit. Eaten as food ration, heals d10 + CON bonus HP. Max fruit = your Level. Can't eat own fruit",
    "Sticky Sap": "Emit 1 dose glutinous sap per day. Spreads as strong contact glue. Creatures STR save or stuck fast. Saltwater dissolves",
    "Sapling Retainers": "Spend d4 CON to create equal number Sapling Retainers (L.VL 1, AV 12, ML +1, ATK d6). Serve rest of day then wither",
    "Blast Pods": "Daily explosive pod (d10 blast). Max pods = your Level",
    "Grafting": "Graft Biological creature part to branches/trunk. Gain appropriate attack/bonus. For each day grafted part alive, lose 1 CON",
    "Puppeteer Roots": "Burrow roots into Biological creature's nervous system. Target EGO save vs control. Damage split between both entities",
}

# The engine-bundled bloomboon table — the real source the engine reads
# (relocated from the campaign dir into the engine 2026-06-17).
REAL_TABLE = Path(__file__).resolve().parents[1] / "data" / "rules" / "NEOBLOOM_BLOOMBOONS.json"


# ---------------------------------------------------------------------------
# Fixture helpers (test_xp_levelup idioms)
# ---------------------------------------------------------------------------

def _write_char(char_id, char):
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta_path = chars_dir / "_meta.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({"last_updated": "2026-01-01"}))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _read_char(char_id):
    p = server.CAMPAIGN_DIR / "characters" / f"{char_id}.json"
    return json.loads(p.read_text())


def _neobloom(**overrides):
    char = {
        "name": overrides.pop("name", "Sprout"),
        "species": "neobloom",
        "level": 1,
        "xp": {"current": 1, "needed": 1},
        "hp": {"current": 20, "max": 20},
        "av": overrides.pop("av", 12),
        "abilities": {
            "STR": {"current": 0, "base": 0},
            "DEX": {"current": 1, "base": 1},
            "CON": {"current": 2, "base": 2},
        },
    }
    char.update(overrides)
    return char


def _write_annotated_table():
    """The full 20-boon table with the script's REAL engine_effects mapping,
    written into the isolated temp campaign dir."""
    table = {}
    for i, nm in enumerate(BOOK_NAMES, start=1):
        entry = {"name": nm, "effect": PINNED_EFFECTS[nm]}
        if str(i) in ANNOTATIONS:
            entry["engine_effects"] = ANNOTATIONS[str(i)]
        table[str(i)] = entry
    (server.CAMPAIGN_DIR / "NEOBLOOM_BLOOMBOONS.json").write_text(
        json.dumps(table))
    return table


def _grant(monkeypatch, char_id, roll):
    monkeypatch.setattr(server.dice, "d20", lambda *a, **k: roll)
    return server._character_level_up_bloomboon(char_id)


# ---------------------------------------------------------------------------
# Repeat rule: next boon down, wrap, all-20 refusal
# ---------------------------------------------------------------------------

def test_repeat_walks_to_next_unowned_and_notes_it(monkeypatch):
    char = _neobloom()
    char["bloomboons"] = [
        {"name": "Shield Vines", "effect": "x", "source": "d20=4"},
        {"name": "Lashing Vines", "effect": "x", "source": "d20=5"},
    ]
    _write_char("sprout", char)
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 4)     # 4 and 5 owned -> walks to 6
    saved = _read_char("sprout")
    names = [b["name"] for b in saved["bloomboons"]]
    assert "Vantablooms" in names
    assert names.count("Shield Vines") == 1
    assert "next boon down" in out
    rec = next(b for b in saved["bloomboons"] if b["name"] == "Vantablooms")
    assert rec["source"] == "d20=4 -> next-down #6"


def test_repeat_wraps_20_to_1(monkeypatch):
    char = _neobloom()
    char["bloomboons"] = [{"name": "Puppeteer Roots", "effect": "x",
                           "source": "d20=20"}]
    _write_char("sprout", char)
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 20)
    saved = _read_char("sprout")
    names = [b["name"] for b in saved["bloomboons"]]
    assert "Plated Bark" in names              # wrapped 20 -> 1
    assert "wrapped 20->1" in out


def test_all_twenty_owned_is_a_clean_refusal(monkeypatch):
    char = _neobloom()
    char["bloomboons"] = [{"name": nm, "effect": "x", "source": "d20=?"}
                          for nm in PINNED_NAMES]
    _write_char("sprout", char)
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 7)
    saved = _read_char("sprout")
    assert "all 20 Bloomboons" in out
    assert saved["level"] == 1                 # nothing applied
    assert saved["xp"] == {"current": 1, "needed": 1}
    assert len(saved["bloomboons"]) == 20


# ---------------------------------------------------------------------------
# engine_effects stamping
# ---------------------------------------------------------------------------

def test_plated_bark_increments_dict_av_base(monkeypatch):
    # A standing +AV bloomboon lifts the no-armour BASELINE so it composes with
    # worn armour (Bug 5): unarmoured 14 -> 16, base recomputed = 16 (no armour).
    _write_char("sprout", _neobloom(av={"base": 14, "source": "bark"}))
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 1)
    saved = _read_char("sprout")
    assert saved["av"]["base"] == 16
    assert saved["av"]["unarmoured"] == 16     # baseline lifted by the standing bonus
    assert "14 -> 16" in out


def test_plated_bark_increments_int_av(monkeypatch):
    # Legacy int av is normalized to the dict shape (the one _character_get and
    # the AV recompute use), with the standing bonus folded into the baseline.
    _write_char("sprout", _neobloom(av=12))
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 1)
    saved = _read_char("sprout")
    assert saved["av"]["base"] == 14
    assert saved["av"]["unarmoured"] == 14
    assert "12 -> 14" in out


def test_barbed_bark_stamps_melee_missed_trigger(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 3)
    saved = _read_char("sprout")
    trigs = saved["special_traits"]["triggers"]
    assert len(trigs) == 1
    t = trigs[0]
    assert t["name"] == "Barbed Bark"
    assert t["when"] == "melee_missed"
    assert t["effect"] == "retaliate"
    assert t["damage"] == "d4"
    assert "Combat trigger stamped: Barbed Bark" in out


def test_mirrored_leaves_stamps_reflect_trigger(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    _grant(monkeypatch, "sprout", 2)
    t = _read_char("sprout")["special_traits"]["triggers"][0]
    assert t["name"] == "Mirrored Leaves"
    assert t["when"] == "beam_attack_hit"
    assert t["effect"] == "reflect_save"
    assert t["save"] == "DEX"


def test_toxic_sap_stamps_trigger_and_defensive_attack(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 10)
    saved = _read_char("sprout")
    t = saved["special_traits"]["triggers"][0]
    assert t["name"] == "Toxic Sap"
    assert t["when"] == "bitten"
    assert t["effect"] == "tox_attack"
    assert t["tox_die"] == "d10"
    atks = saved["attacks"]
    assert any(a["name"] == "Toxic Sap" and a["type"] == "defensive"
               for a in atks)
    assert "Attack entry stamped: Toxic Sap" in out


def test_trigger_and_attack_dedup_by_name(monkeypatch):
    """A sheet that already carries the trigger/attack (Creenash backfill
    scenario) never gets a double."""
    char = _neobloom()
    char["special_traits"] = {"triggers": [
        {"name": "Toxic Sap", "when": "bitten", "effect": "tox_attack",
         "tox_die": "d10", "source": "Bloomboon #10 (CH p.049)"}]}
    char["attacks"] = [{"name": "Toxic Sap", "damage": "d10 TOX",
                        "type": "defensive"}]
    _write_char("sprout", char)
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 10)
    saved = _read_char("sprout")
    assert len(saved["special_traits"]["triggers"]) == 1
    assert len(saved["attacks"]) == 1
    assert "not duplicated" in out
    # the boon RECORD still lands (it was never on the bloomboons list)
    assert any(b["name"] == "Toxic Sap" for b in saved["bloomboons"])


def test_daily_use_lands_in_special_traits(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 7)
    saved = _read_char("sprout")
    dailies = saved["special_traits"]["daily_uses"]
    assert len(dailies) == 1
    assert dailies[0]["name"] == "Empathogen Pollen"
    assert "EGO save" in dailies[0]["note"]
    assert "Daily use stamped: Empathogen Pollen" in out


def test_daily_use_dedup_by_name(monkeypatch):
    char = _neobloom()
    char["special_traits"] = {"daily_uses": [
        {"name": "Medicinal Fruit", "note": "already here"}]}
    _write_char("sprout", char)
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 15)
    saved = _read_char("sprout")
    assert len(saved["special_traits"]["daily_uses"]) == 1
    assert "not duplicated" in out


def test_dm_lever_boon_stamps_nothing_mechanical(monkeypatch):
    _write_char("sprout", _neobloom(av=12))
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 4)     # Shield Vines: lever only
    saved = _read_char("sprout")
    assert saved["av"] == 12
    assert "triggers" not in saved.get("special_traits", {})
    assert "daily_uses" not in saved.get("special_traits", {})
    assert "attacks" not in saved
    assert "DM levers" in out
    assert 'character(action="update_stat"' in out
    # the boon record itself still lands
    assert any(b["name"] == "Shield Vines" for b in saved["bloomboons"])


def test_result_pushes_character_get(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    out = _grant(monkeypatch, "sprout", 1)
    assert 'character(action="get", name="Sprout")' in out
    assert "NEXT" in out


def test_level_and_xp_bookkeeping_unchanged(monkeypatch):
    _write_char("sprout", _neobloom())
    _write_annotated_table()
    _grant(monkeypatch, "sprout", 3)
    saved = _read_char("sprout")
    assert saved["level"] == 2
    assert saved["xp"] == {"current": 0, "needed": 2}
    assert saved["hp"]["max"] == 20            # no HP roll
    assert saved["abilities"]["CON"]["current"] == 2  # no stat bump


def test_table_without_engine_effects_still_works(monkeypatch):
    """A bare name/effect table (pre-annotation shape) must keep working."""
    _write_char("sprout", _neobloom())
    # The bloomboon table is engine-bundled rules-data; redirect RULES_DATA_DIR
    # at the temp campaign dir so this controlled bare table is what's read.
    monkeypatch.setattr(engine_core, "RULES_DATA_DIR", server.CAMPAIGN_DIR)
    bare = {str(i): {"name": f"Bloom{i}", "effect": f"Effect {i}"}
            for i in range(1, 21)}
    (server.CAMPAIGN_DIR / "NEOBLOOM_BLOOMBOONS.json").write_text(
        json.dumps(bare))
    out = _grant(monkeypatch, "sprout", 5)
    saved = _read_char("sprout")
    assert any(b["name"] == "Bloom5" for b in saved["bloomboons"])
    assert "Engine effects" not in out


# ---------------------------------------------------------------------------
# Annotation integrity on the REAL table
# ---------------------------------------------------------------------------

def _real_table():
    if not REAL_TABLE.exists():
        pytest.skip("campaign repo not present")
    return json.loads(REAL_TABLE.read_bytes().decode("utf-8"))


def test_real_table_names_pin():
    data = _real_table()
    names = [data[str(i)]["name"] for i in range(1, 21)]
    assert names == PINNED_NAMES


def test_real_table_name_and_effect_text_unaltered():
    data = _real_table()
    assert len(data) == 20
    for i in range(1, 21):
        entry = data[str(i)]
        assert set(entry) <= {"name", "effect", "engine_effects"}, (
            f"entry {i} grew unexpected keys: {sorted(entry)}")
        assert entry["effect"] == PINNED_EFFECTS[entry["name"]], (
            f"entry {i} ({entry['name']}): effect text altered")


def test_real_table_carries_all_twenty_annotations():
    data = _real_table()
    for roll, ann in ANNOTATIONS.items():
        assert data[roll].get("engine_effects") == ann, (
            f"entry {roll}: engine_effects drifted from the script mapping")


def test_real_table_trigger_records_match_c1_schema():
    data = _real_table()
    for roll in ("2", "3", "10"):
        t = data[roll]["engine_effects"]["trigger"]
        assert {"name", "when", "effect", "source"} <= set(t)
        assert t["name"] == data[roll]["name"]


def test_annotation_script_is_idempotent(tmp_path):
    if not REAL_TABLE.exists():
        pytest.skip("campaign repo not present")
    work = tmp_path / "NEOBLOOM_BLOOMBOONS.json"
    shutil.copyfile(REAL_TABLE, work)
    annotate_main(work)
    first = work.read_bytes()
    annotate_main(work)
    second = work.read_bytes()
    assert first == second
    assert b"\r\n" in first                    # CRLF preserved
    data = json.loads(first.decode("utf-8"))
    names = [data[str(i)]["name"] for i in range(1, 21)]
    assert names == PINNED_NAMES               # text never altered
