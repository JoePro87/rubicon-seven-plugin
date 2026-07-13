"""D4 Pets & Steeds (Crimson Hound printed pp.65-72 / PDF 72-79).

Tame animals (PETS) and mounts (STEEDS) instantiated as fixed-stat-block roster
hirelings. Stats are image-verified against the rendered PDF pages -- see
docs/superpowers/plans/data/pets_steeds_pages/VERIFICATION_NOTES.md.

Cap: the combined Level of all pets + steeds + other followers under a PC's
command cannot exceed the PC's EGO bonus (p.65). Level-0 creatures do not count
toward the cap but must still be fed. Mercenaries are a SEPARATE pool (D3).
"""
import copy

# Survival shapes. Book gives "one ration per day"; model as 1 food, no water
# (do not invent a water need the book does not state). Non-eaters are exempt.
EATS = {"needs_food": True, "needs_water": False, "food_per_day": 1}
NO_NEED = {"needs_food": False, "needs_water": False}

PETS = {
    "volt_rat": {"name": "Citrine-Coated Volt Rat", "kind": "Biological",
                 "level": 1, "av": 13, "morale": 3,
                 "attack": {"name": "Jolt", "damage": "d6", "tags": ["electrical"]},
                 "special": "", "survival": dict(EATS)},
    "bonsai_triffid": {"name": "Bonsai Triffid", "kind": "Biological",
                       "level": 1, "av": 11, "morale": 1,
                       "attack": {"name": "Vines", "damage": "d4",
                                  "note": "or Blinding Spit (DEX save vs Blinded 1 round)"},
                       "special": "Blinded: no ranged attacks, DIS on melee.",
                       "survival": dict(EATS)},
    "glue_worm": {"name": "Glue Worm", "kind": "Biological",
                  "level": 1, "av": 11, "morale": 1,
                  "attack": {"name": "Nip", "damage": "d4",
                             "note": "or Glue Spit (STR save vs Entangled)"},
                  "special": "Entangled d2 turns: AV -5, cannot move freely.",
                  "survival": dict(EATS)},
    "companion_ooze": {"name": "Companion Ooze", "kind": "Biological",
                       "level": 1, "av": 9, "morale": 5, "item_slots": 10,
                       "attack": {"name": "Engulf", "damage": "d4",
                                  "note": "ongoing, STR save to break free"},
                       "special": "Gelatinous: immune to bludgeoning/crushing.",
                       "survival": dict(EATS)},
    "exultants_hawk": {"name": "Exultant's Hawk", "kind": "Biological/Synthetic",
                       "level": 0, "hp": 1, "av": 16, "morale": 3,
                       "attack": {"name": "Claws", "damage": "d4"},
                       "special": "Hunter: brings 1 ration of bird meat/day under "
                                  "open skies (self-feeding).",
                       "survival": dict(NO_NEED)},
    "mycomastiff": {"name": "Mycomastiff", "kind": "Fungal",
                    "level": 1, "av": 12, "morale": 3,
                    "attack": {"name": "Bite", "damage": "d4",
                               "note": "or Spores (d4 TOX, Blast)"},
                    "special": "Spores: CON save after each or no more spores "
                               "without a Long Rest.",
                    "survival": dict(EATS)},
    "pet_rock": {"name": "Pet Rock", "kind": "Mineral",
                 "level": 1, "av": 20, "morale": 10,
                 "attack": {"name": "Thrown", "damage": "d4"},
                 "special": "Living Stone: no eat/drink/breathe; cannot regain HP.",
                 "survival": dict(NO_NEED)},
    "little_torino": {"name": "Little Torino", "kind": "Biological",
                      "level": 1, "av": 15, "morale": 5,
                      "attack": {"name": "Little Horn", "damage": "d6"},
                      "special": "", "survival": dict(EATS)},
    "ray_cat": {"name": "Ray Cat", "kind": "Biological",
                "level": 1, "av": 13, "morale": 4,
                "attack": {"name": "Claws", "damage": "d4",
                           "note": "or Laser Eyes (d4 beam)"},
                "special": "Geiger Kitty: fur reddens near hazardous radiation.",
                "survival": dict(EATS)},
    "skunkey": {"name": "Skunkey", "kind": "Biological",
                "level": 1, "av": 12, "morale": 1,
                "attack": {"name": "Thrown Rock", "damage": "d4",
                           "note": "or Stench Spray (CON save vs vomiting)"},
                "special": "Stench: failed CON -> DIS on saves+attacks next turn; "
                           "noseless/gutless immune.",
                "survival": dict(EATS)},
    "synthhound": {"name": "Synthhound", "kind": "Synthetic",
                   "level": 1, "av": 13, "morale": 10,
                   "attack": {"name": "Bite", "damage": "d4"},
                   "special": "Watchdog Protocol: a physical attack that would "
                              "kill the owner kills the Synthhound instead "
                              "(DM-adjudicated).",
                   "survival": dict(EATS)},
}

STEEDS = {
    "burden_bird": {"name": "Burden Bird", "kind": "Biological",
                    "level": 2, "av": 12, "morale": 2, "item_slots": 20,
                    "attack": {"name": "Peck", "damage": "d6"},
                    "special": "Spooks easily.", "survival": dict(EATS)},
    "crysteed": {"name": "Crysteed", "kind": "Mineral",
                 "level": 7, "av": 22, "morale": 5, "item_slots": 70,
                 "attack": {"name": "Kick", "damage": "d6", "note": "3x"},
                 "special": "Inevitable: cannot recover HP; at 0 HP shatters to "
                            "dust; does not eat/drink.",
                 "survival": dict(NO_NEED)},
    "destrier": {"name": "Destrier", "kind": "Biological",
                 "level": 10, "av": 18, "morale": 10, "item_slots": 20,
                 "attack": {"name": "Bite", "damage": "d8",
                            "note": "+ Kick (d10) / Charge (DEX save vs 3d8, needs run-up)"},
                 "special": "Cavalry charger.", "survival": dict(EATS)},
    "striding_fool": {"name": "Striding Fool", "kind": "Biological",
                      "level": 4, "av": 12, "morale": 4, "item_slots": 40,
                      "attack": {"name": "Fists", "damage": "d6", "note": "2x"},
                      "special": "Abomination: DIS on true-kin reaction rolls "
                                 "while ridden.",
                      "survival": dict(EATS)},
    "thin_mare": {"name": "Thin Mare", "kind": "Hypergeometric",
                  "level": 5, "av": 12, "morale": 5, "item_slots": "Special",
                  "attack": {"name": "Bite", "damage": "d8", "tags": ["hypergeometric"]},
                  "special": "Thin (2D, slips through gaps). Internal Storage: up "
                             "to 100 slots, d100-vs-slot retrieval.",
                  "survival": dict(EATS)},
    "weeping_lizard": {"name": "Weeping Lizard", "kind": "Biological",
                       "level": 3, "av": 16, "morale": 3, "item_slots": 30,
                       "attack": {"name": "Bite", "damage": "d8",
                                  "note": "+ Tear Spray (CON save vs Blindness)"},
                       "special": "Climbs sheer/glassy surfaces.",
                       "survival": dict(EATS)},
    "war_camel": {"name": "War Camel", "kind": "Biological",
                  "level": 4, "av": 15, "morale": 4, "item_slots": 40,
                  "attack": {"name": "Hump-Mounted Turret", "damage": "d10",
                             "note": "+ Kick (d6)"},
                  "special": "Mirror-AV + flechette cannons.",
                  "survival": dict(EATS)},
    "zorse": {"name": "Zorse", "kind": "Biological",
              "level": 5, "av": 13, "morale": 4, "item_slots": 50,
              "attack": {"name": "Kick", "damage": "d8"},
              "special": "Intolerant of extreme heat/deprivation.",
              "survival": dict(EATS)},
}


def pet_block(slug):
    """Deep copy of a PETS row (None if unknown)."""
    row = PETS.get(slug)
    return copy.deepcopy(row) if row else None


def steed_block(slug):
    """Deep copy of a STEEDS row (None if unknown)."""
    row = STEEDS.get(slug)
    return copy.deepcopy(row) if row else None
