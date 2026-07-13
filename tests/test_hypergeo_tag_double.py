"""Hypergeometric WEAPON TAG doubles vs Hypergeometric creatures (CH advanced tag 13).

Book: "The weapon exists partially outside of Euclidean space and deals doubled
damage to Hypergeometric creatures." Before this fix the tag was inert -- only a
hypergeometric DAMAGE TYPE doubled (via the creature-type resistance matrix).
The tag exists for weapons whose damage type is NOT hypergeometric (e.g. the
kinetic Extradimensional Letter Opener, which gains the tag via Extra-Dimensional).

Guard: when the type-level double ACTUALLY fired for hypergeometric damage, that
double already represents the book effect -- the tag must NOT stack (no x4). When
it did not fire (incorporeal bypass; explicit profile omitting hypergeometric) or
fired for a different damage type, the tag still applies.
"""
import server


def test_hypergeo_tag_kinetic_weapon_doubles_vs_hypergeometric_creature():
    # (a) The core gap: kinetic damage + hypergeometric TAG vs a Hypergeometric creature -> x2.
    stats = {"type": "Hypergeometric"}
    amt, note = server._apply_creature_resistance(stats, "kinetic", 5, weapon_tags=["hypergeometric"])
    assert amt == 10 and "hypergeometric" in note.lower()


def test_hypergeo_damage_type_plus_tag_does_not_quadruple():
    # (b) Guard: damage type hypergeometric (type-double fires) AND the tag present -> x2 total, NOT x4.
    stats = {"type": "Hypergeometric",
             "resistances": {"immune": [], "double": ["hypergeometric"], "half": [], "varies": False}}
    amt, note = server._apply_creature_resistance(stats, "hypergeometric", 6, weapon_tags=["hypergeometric"])
    assert amt == 12, f"expected 12 (single x2), got {amt} -- note: {note}"


def test_hypergeo_damage_type_plus_tag_via_type_default_matrix():
    # (b, matrix path) Same guard through the 7-type fallback matrix (no explicit resistances).
    stats = {"type": "Hypergeometric"}
    amt, note = server._apply_creature_resistance(stats, "hypergeometric", 6, weapon_tags=["hypergeometric"])
    assert amt == 12, f"expected 12 (single x2), got {amt} -- note: {note}"


def test_hypergeo_tag_no_double_vs_non_hypergeometric_creature():
    # (c) The tag only matches the Hypergeometric creature type.
    stats = {"type": "Biological"}
    amt, _ = server._apply_creature_resistance(stats, "kinetic", 5, weapon_tags=["hypergeometric"])
    assert amt == 5


def test_letter_opener_engine_tags_vs_hypergeometric_creature():
    # (d) Real-data shape: an Extradimensional Letter Opener (Extra-Dimensional
    # exotic tag grants Hypergeometric + Anti-Paradoxical; kinetic/piercing d4 damage).
    weapon = {
        "name": "Extradimensional Letter Opener",
        "damage": "d4",
        "damage_type": "kinetic",
        "kinetic_subtype": "piercing",
        "engine_tags": ["dimensional-edge", "hypergeometric", "anti-paradoxical"],
        "range": "melee",
    }
    stats = {"type": "Hypergeometric"}
    amt, note = server._apply_creature_resistance(
        stats, weapon["kinetic_subtype"], 4, weapon_tags=weapon["engine_tags"])
    assert amt == 8 and "hypergeometric" in note.lower()
    # anti-paradoxical must NOT fire here (creature is not an Outsider)
    assert "anti-paradoxical" not in note.lower()


def test_anti_paradoxical_vs_outsider_regression_pin():
    # (e) Existing tag-double behavior unchanged.
    stats = {"type": "Outsider"}
    amt, note = server._apply_creature_resistance(stats, "fire", 5, weapon_tags=["anti-paradoxical"])
    assert amt == 10 and "anti-paradoxical" in note.lower()


def test_incorporeal_hypergeometric_creature_letter_opener_combo():
    # Incorporeal + Hypergeometric creature vs a kinetic weapon carrying BOTH tags
    # (the letter opener case): anti-paradoxical bypasses the incorporeal gate
    # (base passes), then the hypergeometric TAG doubles vs the creature type.
    stats = {"type": "Hypergeometric", "incorporeal": True}
    amt, note = server._apply_creature_resistance(
        stats, "kinetic", 4, weapon_tags=["hypergeometric", "anti-paradoxical"])
    assert amt == 8 and "incorporeal bypassed" in note.lower()
    # Without anti-paradoxical, the hypergeometric TAG alone does NOT bypass
    # incorporeal (book: only hypergeometric DAMAGE or anti-paradoxical weapons).
    amt2, _ = server._apply_creature_resistance(
        stats, "kinetic", 4, weapon_tags=["hypergeometric"])
    assert amt2 == 0


def test_incorporeal_hypergeo_damage_plus_tag_doubles():
    # I1: incorporeal bypass sets base = amount WITHOUT the type-level double firing,
    # so the hypergeometric TAG must still double here (the guard keys on whether the
    # type double actually fired, not on the damage type alone).
    stats = {"type": "Hypergeometric", "incorporeal": True}
    amt, note = server._apply_creature_resistance(
        stats, "hypergeometric", 4, weapon_tags=["hypergeometric"])
    assert amt == 8, f"expected 8 (bypass grants base, tag doubles), got {amt} -- note: {note}"
    assert "incorporeal bypassed" in note.lower()


def test_explicit_profile_without_hypergeo_double_tag_still_fires():
    # I1 latent case: an explicit resistance profile that omits hypergeometric from
    # 'double' means the type double never fires -- the tag must still apply.
    stats = {"type": "Hypergeometric",
             "resistances": {"immune": [], "double": ["fire"], "half": [], "varies": False}}
    amt, note = server._apply_creature_resistance(
        stats, "hypergeometric", 5, weapon_tags=["hypergeometric"])
    assert amt == 10, f"expected 10 (tag x2, no type double), got {amt} -- note: {note}"


def test_hypergeo_tag_stacks_on_unrelated_type_double():
    # A type-level double for a DIFFERENT damage type (kinetic weakness) must not
    # suppress the hypergeometric tag: kinetic x2 (weakness) then tag x2 (type) = x4.
    stats = {"type": "Hypergeometric",
             "resistances": {"immune": [], "double": ["kinetic"], "half": [], "varies": False}}
    amt, note = server._apply_creature_resistance(
        stats, "kinetic", 3, weapon_tags=["hypergeometric"])
    assert amt == 12, f"expected 12 (kinetic x2 then tag x2), got {amt} -- note: {note}"


def test_generator_mints_hypergeometric_engine_tag():
    # Check-the-generators rule: a weapon minted with the Hypergeometric prose tag
    # must carry the engine tag, or the combat fix is dead for future weapons.
    import weapon_schema as ws
    w = ws.build_weapon(
        "Sword", "d8", 2,
        prose_tags=["Hypergeometric - exists partially outside Euclidean space"])
    assert "hypergeometric" in w["engine_tags"]
