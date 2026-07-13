# Monster Generator Tables

Book-faithful transcription of the CH Referee's Toolbox monster generator
(printed pp.215-218). Use this to build an original creature when no bestiary
entry fits. **Before improvising stats, always try `lookup(action="creature",
query="name")`** — if a real bestiary creature fits the scene, use it. This
generator is for genuinely new monsters.

Bands are read from the book's d20 columns (merged cells reconstructed from the
page's ruling-line geometry, 2026-06-13). Each column is rolled independently.

## Build sequence

1. **Level + HP** (d20) — HP = Level x 4 (Level 0 = 1 HP).
2. **Type** (d20) — sets the Essence type for alchemy and any type immunities.
3. **AV** (d20) — defence.
4. **Morale** (d20) — the morale bonus / flee behaviour.
5. **Number encountered** (d20).
6. **Basic attack** (d20) + **Special attack** (d20). At **Level 5+**, also roll
   **two Psychic Powers** (d20 twice).
7. **Form** (d20 on the table matching the creature's Type) + **Hue / Texture /
   Behaviour / Habitat** (d20 each) for description.

## Level / HP (d20)

| d20 | Level (HP) |
|---|---|
| 1-3 | 0 (1 HP) |
| 4-6 | 1 (4 HP) |
| 7-8 | 2 (8 HP) |
| 9-10 | 3 (12 HP) |
| 11-12 | 4 (16 HP) |
| 13 | 5 (20 HP) |
| 14 | 6 (24 HP) |
| 15 | 7 (28 HP) |
| 16 | 8 (32 HP) |
| 17 | 9 (36 HP) |
| 18 | 10 (40 HP) |
| 19 | 11 (44 HP) |
| 20 | 12 (48 HP) |

## Type (d20)

| d20 | Type |
|---|---|
| 1-5 | Biological |
| 6-8 | Synthetic |
| 9-10 | Fungal |
| 11-12 | Biological / Synthetic |
| 13-14 | Biological / Psychic |
| 15-16 | Hypergeometric |
| 17 | Synthetic / Hypergeometric |
| 18 | Synthetic / Psychic |
| 19 | Mineral |
| 20 | Outsider |

(Dual types: the alchemist may extract either Essence — see `lookup(action="alchemy")`.)

## AV (d20)

| d20 | AV | (Armour analogue) |
|---|---|---|
| 1 | 9 | — |
| 2-4 | 10 | Unarmoured |
| 5-6 | 11 | Desert Robes |
| 7-8 | 12 | Light Armour |
| 9-10 | 13 | Light Armour + Shield |
| 11-12 | 14 | Medium Armour |
| 13-14 | 15 | Medium Armour + Shield |
| 15-16 | 16 | Heavy Armour |
| 17 | 17 | Heavy Armour + Shield |
| 18 | 18 | Super-Heavy Armour |
| 19 | 19 | — |
| 20 | 20 | — |

## Morale (d20)

| d20 | Morale |
|---|---|
| 1 | Always Flees |
| 2 | +1 |
| 3-4 | +2 |
| 5-6 | +3 |
| 7-8 | +4 |
| 9-10 | +5 |
| 11-12 | +6 |
| 13-14 | +7 |
| 15-17 | +8 |
| 18 | +9 |
| 19 | +10 |
| 20 | Never Flees |

## Number Encountered (d20)

| d20 | Number |
|---|---|
| 1 | d20 |
| 2 | 3d6 |
| 3 | 2d6 |
| 4 | d12 |
| 5-8 | d10 |
| 9-11 | d8 |
| 12-15 | d6 |
| 16-18 | d4 |
| 19-20 | Alone |

## Basic Attack (d20)

| d20 | Attack |
|---|---|
| 1 | Weak Melee (d4) |
| 2 | Weak Ranged (d4) |
| 3-4 | Melee (d6) |
| 5-6 | Ranged (d6) |
| 7 | Area (d6 blast) |
| 8-9 | Strong Melee (d8) |
| 10-11 | Strong Ranged (d8) |
| 12 | Strong Area (d8 blast) |
| 13 | Heavy Melee (d10) |
| 14 | Heavy Ranged (d10) |
| 15 | Heavy Area (d10 blast) |
| 16 | Super-Heavy Melee (d12) |
| 17 | Super-Heavy Ranged (d12) |
| 18 | Super-Heavy Area (d12 blast) |
| 19-20 | Special Attack (roll on the Special Attack column) |

## Special Attack (d20)

| d20 | Special Attack |
|---|---|
| 1 | Cause Mutation (CON save to resist) |
| 2 | Acid Spray (d3 damage + d3 AV decay) |
| 3 | Lightning (d8 electrical) |
| 4 | Enfeebling Touch (d6 STR damage) |
| 5 | Freeze Ray (d6 DEX damage) |
| 6 | Sickening Blast (d6 CON damage) |
| 7 | Memory Leech (d6 INT damage) |
| 8 | Psionic Scream (d6 PSY damage) |
| 9 | Ego-Death Ray (d6 EGO damage) |
| 10 | Flame Breath (2d8 fire) |
| 11 | Laser Eyes (2d8 beam) |
| 12 | Poison Sting (d8 TOX) |
| 13 | Lifesteal (d8, heal equal to damage dealt) |
| 14 | Parasite Implant (fills 1 slot, d6 damage per day) |
| 15 | Swallow Whole (d12 ongoing, STR save to break free) |
| 16 | Cause Wound (roll 2d8 on the Wounds table) |
| 17 | Entropic Touch (-d4 Max HP) |
| 18 | Poison Cloud (d10 TOX, blast) |
| 19 | Cause Blindness (CON save vs d6 rounds of Blindness) |
| 20 | Destroy Item (d20 determines the slot) |

## Psychic Power (d20 — Level 5+ only, roll twice)

| d20 | Psychic Power |
|---|---|
| 1 | Telepathy (Short Range) |
| 2 | Telepathy (Long Range) |
| 3 | Telekinesis (Weak, d4) |
| 4 | Telekinesis (Average, d6) |
| 5 | Telekinesis (Strong, d8) |
| 6 | Telekinesis (Powerful, d10) |
| 7 | Pyrokinesis (Weak, d4 flame) |
| 8 | Pyrokinesis (Average, d6 flame) |
| 9 | Pyrokinesis (Strong, d8 flame) |
| 10 | Pyrokinesis (Powerful, d10 flame) |
| 11 | Weak Mind Control (EGO save w/ ADV to resist) |
| 12 | Mind Control (EGO save to resist) |
| 13 | Strong Mind Control (EGO save w/ DIS to resist) |
| 14 | Mental Shield (Immune to Psychic Effects) |
| 15 | Normality Field (Mystic Gifts non-functional nearby) |
| 16 | Teleportation |
| 17 | Weak Psychic Barrier (+4 AV, must focus) |
| 18 | Psychic Barrier (+6 AV, must focus) |
| 19 | Strong Psychic Barrier (+8 AV, must focus) |
| 20 | Summon Orbs |

## Form by Type (d20)

| d20 | Biological | Synthetic | Fungal |
|---|---|---|---|
| 1 | Humanoid | Warrior-like | Geometric |
| 2 | Vulpine | Autarch-shaped | Classic Mushroom |
| 3 | Canine | Android | Frilled Growths |
| 4 | Feline | Barrel-shaped | Spotted Sphere |
| 5 | Amphibian | Child-like | Spore-belching Spires |
| 6 | Avian | Camera-like | Moss-like |
| 7 | Reptilian | Crab-like | Cup-like |
| 8 | Elephantine | Cube | Humanoid |
| 9 | Horse-like | Cylinder | Mass of Tendrils |
| 10 | Plant-like | Bird-like | Hollow Puffball |
| 11 | Jellyfish-like | Tangle of Wires | Dandelion Fuzz |
| 12 | Squid-like | Wheeled | Creeping Slime |
| 13 | Worm-like | Tank-like | Eye Garden |
| 14 | Beetle-like | Insectile | Riddled with Holes |
| 15 | Snake-like | Spherical | Cauliflower |
| 16 | Arachnoid | Blade-like | Disc-like |
| 17 | Bat-like | Prism | Veil-like |
| 18 | Fish-like | Priest-like | Coral-like |
| 19 | Ape-like | Pyramid-like | Glassy Filaments |
| 20 | Bear-like | Snake-like | Brain-like |

| d20 | Hypergeometric | Mineral | Outsider |
|---|---|---|---|
| 1 | Luminous | Humanoid | Not Quite Human |
| 2 | Hollow | Smooth | Mist-like |
| 3 | Spherical | Sharp | Water-like |
| 4 | Recursive | Crumbling | Bacteria-like |
| 5 | Inverted | Statue-like | Light-like |
| 6 | Paper-like | Spherical | Echo-like |
| 7 | Fractured | Rectangular | Storm-like |
| 8 | Unfolding | Cement-like | Flame-like |
| 9 | Lantern-like | Brick-like | Shadow-like |
| 10 | Moon-like | Boulder-like | Star-like |
| 11 | Splintering | Chimney-like | Ice-like |
| 12 | Cubist | Serpentine | Glass-like |
| 13 | Compressed | Crystalline | Ash-like |
| 14 | Smeared | Sand-like | Flower-like |
| 15 | Angular | Spider-like | Eye-like |
| 16 | Prismatic | Wheel-like | Hand-like |
| 17 | Ouroborous | Fragmented | Tongue-like |
| 18 | Tesseract | Pitted | Liquid-like |
| 19 | Glitching | Fragile | Wheel-like |
| 20 | Shadow-like | Towering | Tree-like |

## Hue / Texture / Behaviour / Habitat (d20 each)

| d20 | Hue | Texture | Behaviour | Habitat |
|---|---|---|---|---|
| 1 | Ochre | Feathered | Scavenger | Featureless Sands |
| 2 | Crimson | Rubbery | Ambushes | Caves |
| 3 | White | Warty | Stalks | Salt Pan |
| 4 | Azure | Slimy | Feigns Death | Hard Rocky Plain |
| 5 | Orange | Fuzzy | Echolocation | Oases |
| 6 | Emerald | Hairy | Buries Self / Victim | Near Settlements |
| 7 | Violet | Velvet | Flies / Levitates | Near Monoliths |
| 8 | Concrete Grey | Soft | Hates Reflections | Atop Mesas |
| 9 | Dusty Brown | Tree Bark | Scared of Fire | Hills |
| 10 | Black | Leather | Nocturnal | Underground Vaults |
| 11 | Peach Pink | Jelly | Parasitic | Toxic Lakeshores |
| 12 | Indigo | Burnt | Symbiotic | Toxic Lake (In Water) |
| 13 | Gold | Spongy | Thief of Strange Objects | Fungal Forests |
| 14 | Silver | Veined | Swallows Food Whole | Crystal Growths |
| 15 | Bronze | Downy | Often Sleeping | Windswept Plains |
| 16 | Zebra Striped | Dry | Craves Honey | Mountains |
| 17 | Iridescent | Damp | Whispers | Winding Canyons |
| 18 | Cornflower Blue | Pitted | Mimicry | Abandoned Cities |
| 19 | Chameleon Colours | Crusty | Blind or Deaf | Cactus Fields |
| 20 | Transparent | Spiny | Vampiric | Sky Islands |

## Engine handoff

- A built monster's **Type** sets its alchemy Essence (`lookup(action="alchemy")`)
  and any damage immunities (Mineral, etc.).
- A **Poison Sting / Poison Cloud** special attack can be statted as a real
  toxin: `⚙ generate(action="poison")`.
- If the creature carries loot, run the ENGINE GENERATOR CONTRACT (SKILL.md).
- Register the creature on the relevant prep/encounter file; for an entry that
  recurs, consider adding it to the bestiary so `lookup(action="creature")`
  finds it next time.
