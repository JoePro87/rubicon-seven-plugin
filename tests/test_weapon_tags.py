"""Weapon-tag parity guards (verified vs Crimson Hound, 2026-06-07 audit).

Locks the two Exotic-tag damage mechanics that the old ingestion got wrong
("triple base damage" instead of the book's "gains N additional damage dice").
The book reading is the one already baked into live sheets (a Nano-edged
Railgun 3d12 = base d12 + 2 dice). See
docs/CRIMSON_HOUND_DAMAGE_RULES_VERIFIED.md.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _tag(table, name):
    return next(t for t in table.values() if t["name"] == name)


def test_autarchs_grants_four_additional_dice_not_triple():
    effect = _tag(server.EXOTIC_TAGS, "Autarch's")["effect"]
    assert "4 additional damage dice" in effect
    assert "triple" not in effect.lower()  # the old-ingestion error must not return
    assert "trade value" not in effect.lower()  # unverified claim was dropped


def test_nano_edged_grants_two_additional_dice_not_triple():
    effect = _tag(server.EXOTIC_TAGS, "Nano-edged")["effect"]
    assert "2 additional damage dice" in effect
    assert "triple" not in effect.lower()


def test_advanced_tag_type_doublings_intact():
    # The three tags the combat engine relies on for type-doubling (verified book text).
    assert "Outsider" in _tag(server.ADVANCED_TAGS, "Anti-Paradoxical")["effect"]
    assert "Mineral" in _tag(server.ADVANCED_TAGS, "Eroding")["effect"]
    assert "Psychic" in _tag(server.ADVANCED_TAGS, "Psyche-Suppressant")["effect"]


def test_basic_tags_match_book_d20():
    """Basic tag table verified vs the book (page-fed 2026-06-07).

    The old table had a hallucinated 'Accurate' at roll 1 (which shifted every
    roll) and was missing 'Shoddy' at roll 19. Pin the corrected d20 mapping."""
    bt = server.BASIC_TAGS
    assert len(bt) == 20 and set(bt) == set(range(1, 21))
    assert bt[1]["name"] == "Ancient"        # roll 1 is Ancient, NOT Accurate
    assert bt[20]["name"] == "Translucent"
    # the hallucinated tag is gone from every tier of the basic table
    assert all(t["name"] != "Accurate" for t in bt.values())
    # the previously-missing book tag is present and correct
    assert bt[19]["name"] == "Shoddy"
    assert "one step smaller" in bt[19]["effect"]


def test_weapon_base_tables_match_book():
    """Melee/Ranged base-type tables verified vs the book (page-fed 2026-06-07)."""
    m = server.MELEE_WEAPONS
    assert len(m) == 20
    # Scythe was wrongly d6/1slot; book is d8/2slots
    scythe = next(w for w in m.values() if w["name"] == "Scythe")
    assert scythe["damage"] == "d8" and scythe["slots"] == 2
    r = server.RANGED_WEAPONS
    assert len(r) == 20
    laser_cannon = next(w for w in r.values() if w["name"] == "Laser Cannon")
    assert laser_cannon["ammo"] == "Ud6"
    porta = next(w for w in r.values() if w["name"] == "Port-A-Cannon")
    assert porta["ammo"] == "Ud4"
    railgun = next(w for w in r.values() if w["name"] == "Railgun")
    assert railgun["slots"] == 6 and railgun["tags"] == []  # base Railgun has no tag


def test_chargen_weapon_tables_mirror_book_base_tables():
    """Character-creation weapon tables (content_forge) must mirror the verified
    server.py book base tables — single source of truth enforced by test.
    Ruling 2026-06-07: chargen has NO separate table; the PC chooses melee or
    ranged and rolls on that. The fabricated 'basic_weapon' table is retired."""
    cf = json.loads(
        (Path(__file__).resolve().parent.parent / "data" / "content_forge_tables.json").read_text(encoding="utf-8")
    )
    T = cf["tables"]
    assert "basic_weapon" not in T, "fabricated single chargen table must be gone"
    assert "basic_weapon_melee" in T and "basic_weapon_ranged" in T

    def as_map(tbl):
        return {int(e["roll"]): (e["fields"]["Weapon"], e["fields"]["Damage"], e["fields"]["Slots"])
                for e in tbl["entries"]}

    m, r = as_map(T["basic_weapon_melee"]), as_map(T["basic_weapon_ranged"])
    for roll, w in server.MELEE_WEAPONS.items():
        assert m[roll] == (w["name"], w["damage"], str(w["slots"]))
    for roll, w in server.RANGED_WEAPONS.items():
        assert r[roll] == (w["name"], w["damage"], str(w["slots"]))

    # the old fabricated weapon names are gone from chargen
    names = {v[0] for v in m.values()} | {v[0] for v in r.values()}
    for fake in ("Knife", "Cudgel", "Hatchet", "Machete", "Short Bow", "Polearm"):
        assert fake not in names


def test_generate_weapon_emits_structured_object():
    import server, weapon_schema as ws
    # Laser Rifle is RANGED_WEAPONS roll 14 (beam). basic tag roll 1 = no extra dice.
    obj = server._generate_weapon_obj(tier="basic", weapon_type="ranged", base_roll=14, basic_roll=1)
    assert obj["damage_type"] == "beam"
    assert ws.validate_weapon(obj) == []
    assert "name" in obj and "damage" in obj and "slots" in obj


def test_generate_armour_emits_structured_object():
    import server, weapon_schema as ws
    # body_armour roll 3 = Ancestral Hazard Wrap, AV 12 → av_bonus = 2
    obj = server._generate_armour_obj(body_roll=3)
    assert obj["av_bonus"] >= 1 and "name" in obj
    assert ws.validate_armour(obj) == []


# ---------------------------------------------------------------------------
# Task 14: armour is AV-only for the engine; two book properties as prose
# (Crimson Hound Explorer's Guide p.34 — verified 2026-06-08)
# ---------------------------------------------------------------------------

def test_armour_engine_tags_stays_empty_av_only():
    import weapon_schema as ws
    a = ws.build_armour(name="Indigo Brigandine", av_bonus=3, slots=3, prose_tags=[])
    assert a["engine_tags"] == []          # AV-only for the engine — no armour combat tags exist
    assert ws.validate_armour(a) == []


def test_armour_type_properties_match_book():
    import weapon_schema as ws
    # The only two armour types with a printed mechanical property (Explorer's Guide p.34)
    assert ws.ARMOUR_TYPE_PROPERTIES["Hazard Wrap"] == "ADV on Saves vs Radiation and Toxins"
    assert ws.ARMOUR_TYPE_PROPERTIES["Plate Armour"] == "DIS when swimming or climbing."


def test_generated_hazard_wrap_surfaces_property_as_prose_not_engine_tag():
    import server, weapon_schema as ws
    obj = server._generate_armour_obj(body_roll=3)   # Ancestral Hazard Wrap
    assert "Hazard Wrap" in obj["name"]
    assert any("Radiation and Toxins" in t for t in obj["tags"])   # prose tag carries the book property
    assert obj["engine_tags"] == []                                # NOT an engine tag
    assert ws.validate_armour(obj) == []


def test_generated_plain_armour_has_no_property_tag():
    import server
    obj = server._generate_armour_obj(body_roll=8)   # Tarnished Brigandine — no printed property
    assert obj["tags"] == []
    assert obj["engine_tags"] == []
