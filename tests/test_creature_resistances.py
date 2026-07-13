import server


def test_resistance_matrix_loads_seven_types():
    matrix = server._load_creature_resistances()
    for t in ["Biological", "Synthetic", "Psychic", "Fungal", "Mineral", "Hypergeometric", "Outsider"]:
        assert t in matrix
    assert "electrical" in matrix["Synthetic"]["double"]
    assert matrix["Outsider"].get("varies") is True


def test_normalize_damage_type():
    assert server._normalize_damage_type("TOX") == "poison"
    assert server._normalize_damage_type("Heat") == "fire"
    assert server._normalize_damage_type("crushing") == "bludgeoning"
    assert server._normalize_damage_type("electrical") == "electrical"
    assert server._normalize_damage_type("WeirdNew") == "weirdnew"  # unknown -> lowercased passthrough


def test_resolve_profile_explicit_wins():
    stats = {"type": "Synthetic", "resistances": {"immune": ["kinetic"], "double": [], "half": []}}
    prof = server._resolve_resistance_profile(stats)
    assert "kinetic" in prof["immune"]
    assert "electrical" not in prof["double"]  # explicit profile overrides the Synthetic default

def test_resolve_profile_type_default():
    stats = {"type": "Synthetic"}  # no explicit resistances
    prof = server._resolve_resistance_profile(stats)
    assert "electrical" in prof["double"]
    assert "poison" in prof["immune"]

def test_resolve_profile_multitype_union_and_flag():
    stats = {"type": "Fungal / Mineral"}  # Fungal half kinetic; Mineral double bludgeoning + immunities
    prof = server._resolve_resistance_profile(stats)
    assert "kinetic" in prof["half"]
    assert "bludgeoning" in prof["double"]
    assert "poison" in prof["immune"]

def test_resolve_profile_extreme_temperature_expands():
    # A stat block granting 'extreme_temperature' immunity expands to both fire and cold.
    # (Book: only Mineral is immune to extreme temperatures via its type; Synthetic is NOT.)
    stats = {"type": "Biological", "resistances": {"immune": ["extreme_temperature"]}}
    prof = server._resolve_resistance_profile(stats)
    assert "fire" in prof["immune"] and "cold" in prof["immune"]


def test_apply_synthetic_electrical_doubles():
    stats = {"type": "Synthetic"}
    amt, note = server._apply_creature_resistance(stats, "electrical", 6)
    assert amt == 12 and "x2" in note

def test_apply_fungal_kinetic_halves():
    stats = {"type": "Fungal"}
    amt, note = server._apply_creature_resistance(stats, "kinetic", 7)
    assert amt == 3 and "/2" in note  # 7 // 2 = 3

def test_apply_mineral_poison_immune():
    stats = {"type": "Mineral"}
    amt, note = server._apply_creature_resistance(stats, "TOX", 9)
    assert amt == 0 and "immune" in note.lower()

def test_apply_explicit_override_immune():
    stats = {"type": "Synthetic", "resistances": {"immune": ["kinetic"]}}
    amt, note = server._apply_creature_resistance(stats, "kinetic", 8)
    assert amt == 0 and "immune" in note.lower()

def test_apply_outsider_varies_passthrough():
    stats = {"type": "Outsider"}
    amt, note = server._apply_creature_resistance(stats, "fire", 5)
    assert amt == 5 and "vary" in note.lower()

def test_apply_no_modifier_returns_base_empty_note():
    stats = {"type": "Biological"}
    amt, note = server._apply_creature_resistance(stats, "fire", 5)
    assert amt == 5 and note == ""


def test_combat_damage_applies_enemy_resistance(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "enemies": {"Ooze (alpha)": {
            "hp": 16, "max_hp": 16, "defeated": False, "fled": False,
            "resist_type": "Fungal",
            "resistances": {"immune": [], "double": ["fire"], "half": ["kinetic"], "varies": False},
        }},
        "party_snapshot": {}, "log": [],
    })
    out = server._combat_damage("Ooze (alpha)", 6, "fire")
    enemy = server.GAME_STATE["active_combat"]["enemies"]["Ooze (alpha)"]
    assert enemy["hp"] == 4         # 16 - (6 doubled = 12) = 4
    assert "x2" in out


def test_empty_explicit_resistances_falls_through_to_type_default():
    # An all-empty resistances object must NOT suppress the type-default matrix.
    stats = {"type": "Synthetic", "resistances": {"immune": [], "double": [], "half": [], "varies": False}}
    prof = server._resolve_resistance_profile(stats)
    assert "electrical" in prof["double"]   # Synthetic default revived
    assert "poison" in prof["immune"]
    amt, _ = server._apply_creature_resistance(stats, "electrical", 5)
    assert amt == 10                         # electrical doubled via type default


def test_nonempty_explicit_still_overrides_type_default():
    stats = {"type": "Synthetic", "resistances": {"immune": ["kinetic"], "double": [], "half": [], "varies": False}}
    prof = server._resolve_resistance_profile(stats)
    assert "kinetic" in prof["immune"]
    assert "electrical" not in prof["double"]  # real per-creature override wins


def test_minimum_bucket_only_affects_listed_type():
    # 'minimum damage from X' -> X always deals exactly 1; ALL other types unaffected.
    stats = {"type": "Biological / Synthetic",
             "resistances": {"immune": [], "minimum": ["bludgeoning"], "double": [], "half": [], "varies": False}}
    amt, note = server._apply_creature_resistance(stats, "bludgeoning", 12)
    assert amt == 1 and "minimum" in note.lower()
    amt_crush, _ = server._apply_creature_resistance(stats, "crushing", 9)   # synonym -> bludgeoning
    assert amt_crush == 1
    # every other damage type resolves normally (NOT reduced to 1)
    assert server._apply_creature_resistance(stats, "fire", 8)[0] == 8
    assert server._apply_creature_resistance(stats, "electrical", 5)[0] == 5
    assert server._apply_creature_resistance(stats, "slashing", 7)[0] == 7


def test_weapon_tag_anti_paradoxical_doubles_vs_outsider():
    stats = {"type": "Outsider"}  # varies -> base passes through, tag doubles it
    amt, note = server._apply_creature_resistance(stats, "fire", 5, weapon_tags=["anti-paradoxical"])
    assert amt == 10 and "anti-paradoxical" in note.lower()

def test_weapon_tag_eroding_doubles_vs_mineral():
    stats = {"type": "Mineral"}  # beam is not in Mineral's immune set
    amt, note = server._apply_creature_resistance(stats, "beam", 6, weapon_tags=["eroding"])
    assert amt == 12 and "eroding" in note.lower()

def test_weapon_tag_psyche_suppressant_doubles_vs_psychic():
    stats = {"type": "Psychic"}
    amt, _ = server._apply_creature_resistance(stats, "fire", 4, weapon_tags=["psyche-suppressant"])
    assert amt == 8

def test_weapon_tag_no_effect_vs_wrong_type():
    stats = {"type": "Biological"}
    amt, _ = server._apply_creature_resistance(stats, "fire", 5, weapon_tags=["anti-paradoxical", "eroding"])
    assert amt == 5  # no matching type -> no doubling

def test_weapon_tag_does_not_revive_type_immunity():
    # An eroding weapon doubles vs Mineral, but Mineral is immune to poison -> still 0.
    stats = {"type": "Mineral"}
    amt, _ = server._apply_creature_resistance(stats, "poison", 9, weapon_tags=["eroding"])
    assert amt == 0

def test_incorporeal_immune_to_conventional():
    stats = {"type": "Outsider", "incorporeal": True}
    amt, note = server._apply_creature_resistance(stats, "fire", 8)
    assert amt == 0 and "incorporeal" in note.lower()

def test_incorporeal_harmed_by_hypergeometric_damage():
    stats = {"type": "Outsider", "incorporeal": True}
    amt, _ = server._apply_creature_resistance(stats, "hypergeometric", 8)
    assert amt == 8  # hypergeometric bypasses incorporeal (no anti-paradoxical tag -> not doubled)

def test_incorporeal_harmed_and_doubled_by_anti_paradoxical():
    stats = {"type": "Outsider", "incorporeal": True}
    amt, _ = server._apply_creature_resistance(stats, "fire", 8, weapon_tags=["anti-paradoxical"])
    assert amt == 16  # anti-paradoxical bypasses incorporeal AND doubles vs Outsider

def test_weapon_tags_none_is_backward_compatible():
    stats = {"type": "Synthetic"}
    assert server._apply_creature_resistance(stats, "electrical", 6) == server._apply_creature_resistance(stats, "electrical", 6, weapon_tags=None)


def test_minimum_immune_precedence():
    # immune (0) still beats minimum (1) when a type is in both
    stats = {"resistances": {"immune": ["fire"], "minimum": ["fire"]}}
    assert server._apply_creature_resistance(stats, "fire", 10)[0] == 0


# --- kinetic sub-types (slashing / piercing / bludgeoning) ---

def test_damage_match_keys_subtype_maps_to_parent():
    assert server._damage_match_keys("slashing") == {"slashing", "kinetic"}
    assert server._damage_match_keys("piercing") == {"piercing", "kinetic"}
    assert server._damage_match_keys("bludgeoning") == {"bludgeoning", "kinetic"}
    assert server._damage_match_keys("kinetic") == {"kinetic"}  # generic does NOT imply a sub-type
    assert server._damage_match_keys("beam") == {"beam"}


def test_subtype_double_and_half_mechanism():
    # ENGINE mechanism (synthetic profile — not any specific creature): a kinetic
    # sub-type listed in `double` doubles, one in `half` halves, and a generic
    # (unspecified) kinetic hit is NOT assumed to be any sub-type.
    stats = {"type": "Biological",
             "resistances": {"double": ["slashing"], "half": ["bludgeoning"]}}
    assert server._apply_creature_resistance(stats, "slashing", 6)[0] == 12      # x2
    assert server._apply_creature_resistance(stats, "bludgeoning", 6)[0] == 3    # /2
    assert server._apply_creature_resistance(stats, "piercing", 6)[0] == 6       # unlisted -> normal
    assert server._apply_creature_resistance(stats, "kinetic", 6)[0] == 6        # generic -> normal


def test_planeyfolk_flat_rule_book_accurate():
    # Book (CH bestiary, Planeyfolk): double damage from "slashing or slicing"
    # weapons — slashing ONLY. NOT piercing, and there is NO bludgeoning half.
    stats = {"type": "Biological / Hypergeometric",
             "resistances": {"double": ["slashing"], "half": []}}
    assert server._apply_creature_resistance(stats, "slashing", 6)[0] == 12      # x2 (book)
    assert server._apply_creature_resistance(stats, "piercing", 6)[0] == 6       # NOT doubled
    assert server._apply_creature_resistance(stats, "bludgeoning", 6)[0] == 6    # NOT halved
    assert server._apply_creature_resistance(stats, "kinetic", 6)[0] == 6        # generic normal


def test_planeyfolk_bestiary_data_has_no_piercing():
    # Data-integrity: the REAL bestiary Planeyfolk entry must match the book —
    # double on slashing (plus the Hypergeometric type-union), never piercing.
    import json
    from pathlib import Path
    bestiary_path = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook" / "bestiary.json"
    if not bestiary_path.exists():
        import pytest
        pytest.skip("engine bestiary.json not found")
    entries = json.loads(bestiary_path.read_text(encoding="utf-8"))["entries"]
    pf = next(e for e in entries if e.get("id") == "creature-planeyfolk")
    double = pf["stats"]["resistances"]["double"]
    assert "slashing" in double
    assert "piercing" not in double, f"book says slashing/slicing only; piercing is fabricated: {double}"


def test_subtyped_hit_still_gets_blanket_kinetic_resistance():
    # Fungal halves kinetic; a slashing (kinetic sub-type) hit must still be halved.
    stats = {"type": "Fungal"}
    assert server._apply_creature_resistance(stats, "slashing", 8)[0] == 4
    assert server._apply_creature_resistance(stats, "kinetic", 8)[0] == 4


def test_mineral_double_bludgeoning_only_on_subtype():
    # Mineral doubles bludgeoning specifically; generic kinetic is not assumed bludgeoning.
    stats = {"type": "Mineral"}
    assert server._apply_creature_resistance(stats, "bludgeoning", 5)[0] == 10  # x2
    assert server._apply_creature_resistance(stats, "kinetic", 5)[0] == 5       # normal
