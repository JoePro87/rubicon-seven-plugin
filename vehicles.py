"""D5 Vehicles (Crimson Hound printed pp.73-76 / PDF 80-83) + campaign homebrew.

Hull-Points combat entities instantiated as type:"vehicle" roster sheets (stored
in the vehicles/ dir). Stats image-verified -- see
docs/superpowers/specs/2026-06-13-d5-vehicles-design.md. The two homebrews
(crawler, ornithopter_titan) come from the engine rules-data TRANSPORT_SPEEDS.json
(R-D5a/b). `damage_immune` marks the Vimana (R-D5e); only anti-paradox weapons
unravel it. `speed` is an int, except the Wind Barge "d6/day" sentinel.
"""
import copy

VEHICLES = {
    "auto_chariot": {"name": "Auto-Chariot", "kind": "Synthetic", "hull": 8, "av": 18,
                     "speed": 6, "item_slots": 80,
                     "attack": {"name": "Gauss Cannon", "damage": "d12"},
                     "crew": "No pilot needed; 5 passengers",
                     "special": "Self-driving; will not accept a new master until the old has died.",
                     "homebrew": False, "damage_immune": False},
    "colossus": {"name": "Colossus", "kind": "Synthetic", "hull": 10, "av": 20,
                 "speed": 3, "item_slots": 100,
                 "attack": {"name": "Sword", "damage": "d12",
                            "note": "or Swarm Missiles (2d10 blast)", "tags": ["blast"]},
                 "crew": "One pilot",
                 "special": "Mechanical warrior-saint effigy; pilot suspended in the belly.",
                 "homebrew": False, "damage_immune": False},
    "dune_skuggy": {"name": "Dune Skuggy", "kind": "Mechanical", "hull": 5, "av": 13,
                    "speed": 9, "item_slots": 30,
                    "attack": {"name": "Flak Cannon", "damage": "d10"},
                    "crew": "1 driver, 1 gunner, 2 passengers",
                    "special": "Crude guzzeline desert vehicle.",
                    "homebrew": False, "damage_immune": False},
    "ornithopter": {"name": "Ornithopter", "kind": "Mechanical", "hull": 7, "av": 18,
                    "speed": 12, "item_slots": 70,
                    "attack": {"name": "Laser Lance", "damage": "3d6", "tags": ["beam"]},
                    "crew": "1 pilot, 1 gunner, up to 6 passengers",
                    "special": "Pre-Collapse beating-wing flyer.",
                    "homebrew": False, "damage_immune": False},
    "skiff": {"name": "Skiff", "kind": "Mechanical", "hull": 2, "av": 16,
              "speed": 8, "item_slots": 10,
              "attack": {"name": "Mounted Rifle", "damage": "d8"},
              "crew": "1 driver, 1 passenger",
              "special": "A lightweight hover-bike (covers the campaign 'hoverbike', R-D5c); "
                         "fast, unstable, lethal when it malfunctions.",
              "homebrew": False, "damage_immune": False},
    "stilt_strutter": {"name": "Stilt Strutter", "kind": "Mechanical", "hull": 4, "av": 18,
                       "speed": 2, "item_slots": 40,
                       "attack": {"name": "Mounted Cannon", "damage": "d12"},
                       "crew": "1 pilot, 1 gunner, up to 4 passengers",
                       "special": "Towering mechanised walker; navigates treacherous ground.",
                       "homebrew": False, "damage_immune": False},
    "touring_orb": {"name": "Touring Orb", "kind": "Synthetic", "hull": 2, "av": 16,
                    "speed": 1, "item_slots": 20, "attack": None,
                    "crew": "No pilot; up to 4 passengers",
                    "special": "Fabricates 1 fizzy ration/day; lectures on local flora/fauna.",
                    "homebrew": False, "damage_immune": False},
    "vimana": {"name": "Vimana", "kind": "Hypergeometric/Mineral", "hull": 1, "av": 20,
               "speed": 10, "item_slots": 10,
               "attack": {"name": "Annihilation Ray", "damage": "2d10", "tags": ["beam"]},
               "crew": "1 on the throne; 12 retainers may cling",
               "special": "Damage Immunity: impervious to all damage, pilot immortal while "
                          "seated; only anti-paradox weapons unravel it.",
               "homebrew": False, "damage_immune": True},
    "wind_barge": {"name": "Wind Barge", "kind": "Mechanical", "hull": 15, "av": 18,
                   "speed": "d6/day", "item_slots": 200, "attack": None,
                   "crew": "At least 4 crew to operate; 50 passengers",
                   "special": "Wooden cargo ship on a sky-seeking stone; unarmed by custom, "
                              "carries 2d6 Level-2 guards.",
                   "homebrew": False, "damage_immune": False},
    # --- Homebrew (R-D5a/b) ---
    "crawler": {"name": "Cargo Crawler", "kind": "Mechanical", "hull": 12, "av": 14,
                "speed": 6, "item_slots": 150,
                "attack": None,
                "crew": "Any with vehicle operation; 4 passengers",
                "special": "Campaign-homebrew expedition vehicle. "
                           "25 mph / 200 mi-day; fuel + maintenance.",
                "homebrew": True, "damage_immune": False,
                "travel": {"mph": 25, "daily_range_miles": 200, "sustained_hours": 24}},
    "ornithopter_titan": {"name": "Ornithopter (Titan-class)", "kind": "Mechanical",
                          "hull": 7, "av": 18, "speed": 12, "item_slots": 70,
                          "attack": {"name": "Laser Lance", "damage": "3d6", "tags": ["beam"]},
                          "crew": "1 pilot + the whole crew (no 6-seat cap)",
                          "special": "Campaign homebrew (R-D5a): the book Ornithopter block, but "
                                     "Titan-class - fits the whole crew. "
                                     "120 mph cruise, 960 mi/day, 24h sustained.",
                          "homebrew": True, "damage_immune": False,
                          "travel": {"mph": 120, "daily_range_miles": 960, "sustained_hours": 24}},
}


def vehicle_block(slug):
    """Deep copy of a VEHICLES row (None if unknown)."""
    row = VEHICLES.get(slug)
    return copy.deepcopy(row) if row else None
