"""S2: annotate table-desert-foraging with machine-readable yield/cache keys.

Idempotent: strips any existing yield/cache keys, then applies the mapping.
Run with the Windows venv python. Verifies row count and prints a summary.

Mapping drafted 2026-06-11 against extraction batch_06 ~1657-1813 and
re-verified at implementation time. Rule (spec section 3): yield ONLY for
unconditionally-free rations; judgment calls default to NO annotation.
"""
import json
from pathlib import Path

TABLES = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign" / "rulebook" / "tables.json"

# roll -> annotation. Rows absent from this dict get no annotation (scene/
# encounter/nothing). Dice strings are rolled at forage time; ints are flat.
ANNOTATIONS = {
    38: {"yield": {"water": 1}},          # canteen, 1 fresh water
    43: {"yield": {"food": 3}},           # 3 rations dried meat in cloth
    44: {"yield": {"water": "d4"}},       # abandoned air-well holds d4 (free)
    45: {"yield": {"food": "d6"}},        # Hegemony Ration Pack, d6 cubes
    49: {"yield": {"food": 1}},           # flightless owl burrow, worth 1
    51: {"yield": {"water": 3}},          # plastic bottle, 3 water
    53: {"yield": {"water": 4}},          # wrecked Auto-Chariot cooling system
    54: {"yield": {"food": "d6"}},        # jar of d6 pickles
    55: {"yield": {"water": "d6"}},       # d6 vacuum-sealed Hegemony water
    56: {"yield": {"food": 8}},           # dead Zorse, still fresh
    57: {"yield": {"food": 6}},           # 6 Sand-Oysters
    58: {"yield": {"water": 1}},          # Solar Saint statue weeps 1/day (today's)
    59: {"yield": {"water": "d8"}},       # d8 wax-sealed jars (water)
    60: {"yield": {"food": "d8"}},        # d8 wax-sealed jars (nutrition paste)
    61: {"yield": {"water": "d8"}},       # d8 plasteel cans
    65: {"yield": {"water": 6}},          # large plastic bottle
    66: {"yield": {"food": 8}},           # gut-skin bag of pemmican
    71: {"yield": {"food": 12}},          # bed of 12 Sand-Oysters
    72: {"cache": "Small"},
    73: {"yield": {"water": 12}},         # exploratory well, 12 buckets
    74: {"yield": {"food": "2d12"}},      # algae cultivar array (scrape)
    76: {"yield": {"water": "3d6"}},      # melting ice sculpture
    77: {"yield": {"food": "2d6"}},       # obelisk sacrifice, edible meat
    78: {"yield": {"food": "2d8"}},       # scorpion husk fungus
    79: {"yield": {"water": "2d10"}},     # void-craft water recycling
    80: {"yield": {"water": "2d10"}},     # 2d10 wax-sealed jars
    81: {"cache": "Medium"},
    83: {"yield": {"food": "2d6", "water": "d8"}},  # traveller's stash in hut
    84: {"yield": {"water": 8}},          # dead mystic's pack (gift book = DM)
    85: {"yield": {"water": "2d12"}},     # 2d12 jars (water)
    86: {"yield": {"food": "2d12"}},      # 2d12 jars (nutrition paste)
    89: {"yield": {"water": 12}},         # plastic barrel
    90: {"cache": "Large"},
    93: {"yield": {"food": 40}},          # colossal oyster bed
    96: {"yield": {"water": "3d6", "food": "3d6"}},  # crashed Ornithopter (rifles = DM)
    98: {"yield": {"water": "d100", "food": "d100"}},  # wind-barge wreck (goods = DM)
    100: {"cache": "Extra-Large"},
    # Deliberate NON-annotations (scene/conditional — DM rules):
    # 33 husk (mycomorph-only), 34 inedible Ickbulbs, 36 toxic pond, 39 Cacklemaw,
    # 40 vending machine (payment), 41 cacti (a day to tap), 42 Waterguide (a day),
    # 46 Sand Octopus (if caught), 47 Glass Tigers (if driven off), 50 beehive (if smoked),
    # 52 Unicorn whelps (mother), 62 Faa Nomads (exchange), 63 Thunderstrike eggs (mother),
    # 64 aquarium sphere (moral scene), 67 dining table (site), 68 butchers (steal-what-
    # you-carry), 69 fridge fruit (rots on opening — DM times it), 70 ambrosia (drink,
    # not water ration), 75 Feastbeasts (livestock), 82 crack (carry-limited), 87 step-
    # well (site), 88 Meal Fabricator (site), 91 Sky Whale (encounter/hour), 92 monger
    # (exchange), 94 Zorse saddlebags (spec's own default-to-scene example), 95 serai
    # (site), 97 Seven-Fruit grove (site), 99 Oasis (site/location).
}


def main():
    data = json.loads(TABLES.read_text(encoding="utf-8"))
    table = next(t for t in data["rolling_tables"]
                 if t.get("id") == "table-desert-foraging")
    applied = stripped = 0
    for e in table["entries"]:
        for key in ("yield", "cache"):
            if key in e:
                del e[key]
                stripped += 1
        ann = ANNOTATIONS.get(e.get("roll"))
        if ann:
            e.update(ann)
            applied += 1
    assert applied == len(ANNOTATIONS), \
        f"applied {applied} != mapping {len(ANNOTATIONS)} — roll keys missing from table?"
    TABLES.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"[annotate_foraging_s2] stripped {stripped} old keys, "
          f"applied {applied} annotations to {TABLES}")


if __name__ == "__main__":
    main()
