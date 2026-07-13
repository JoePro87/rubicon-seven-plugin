# Vault Generation Tables

Book-faithful transcription of the CH Referee's Toolbox vault-creation system
(printed pp.105-118). This is the **random-generation layer**; the skill's own
LAYOUT TOPOLOGY / ATTRITION CURVE / SOUL framework (in SKILL.md) is the
*design* layer — use both: generate raw content here, then edit for sense and
soul. Treasure and hazard rows delegate to engine generators (see the ENGINE
GENERATOR CONTRACT in SKILL.md) — roll the real item, don't stat it in prose.

## Creating a Vault — the procedure

1. **Roll d20** for Entrance / Tunnels / Original Function (table below) — the seed.
2. **Drop 3d20 on a blank sheet.** Each die = a cluster of vault-room nodes (A, B, C). Draw the node clusters and label them. This is a layout sketch, not an accurate map.
3. You now have **18 location nodes** joined by pathways. Node markings:
   - **clear circle** = empty room
   - **filled circle** = inhabited (usually a creature lair)
   - **`!` mark** = hazard (node or pathway)
   - **star** = treasure
   - **hashmarks** = special room
4. **Fill cluster A.** For each uninhabited room, roll **d6 twice** (Contents A + Contents B, below).
5. **Inhabited nodes:** generate from the **Lair Rooms** table at the right Depth + add one Room Feature.
6. **Hazard nodes/pathways:** roll on **Vault Hazards**.
7. **Treasure nodes:** roll on **Treasure Rooms**. If treasure shares a room with a creature or hazard, decide how that guards it.
8. **Special nodes:** roll on **Special Rooms**. Some hold secret passages — mark with dotted lines.
9. Repeat steps 4-8 for clusters B and C.
10. **Join the clusters** with new pathways; place an entrance at an empty, hazard-free room (the PCs' start).
11. **Build the floor's encounter table** — at least d6 creatures from the Bestiary, starting with those already placed.
12. **Edit by judgement** — fix dead ends, bottlenecks, over-hard lairs.
13. **Deeper floors:** mark a node with a downward arrow; new floor repeats from step 2, using the next Depth for lairs.
14. **Optional restock** (high-traffic vaults): for each cleared room, roll the Restock table between delves; unexplored another expedition → step the die down and roll again.

### Uninhabited room contents — roll d6 twice

| d6 | Contents A | Contents B |
|---|---|---|
| 1 | Lair | Hazard |
| 2 | — | Room Feature |
| 3 | — | Trinket (book Trinkets d100, p.110) |
| 4 | — | Fauna or Flora |
| 5 | — | Hint to a Hazard or Lair |
| 6 | Treasure | Special Room |

### Restock (d-step, optional)

| Roll | New Contents |
|---|---|
| 1 | Lair AND Treasure |
| 2 | Lair |
| 3 | Hazard |
| 4 | Treasure |
| 5 | Hint to nearby Hazard or Lair |
| 6+ | Nothing |

## Entrance / Tunnels / Original Function (d20)

| d20 | Vault Entrance | The Tunnels | Original Function |
|---|---|---|---|
| 1 | Steel Blast Doors | Half-Flooded | Fallout Shelter |
| 2 | Back of Tiny Cave | Filled with Blue Sand | Transport Network |
| 3 | Enormous Crater | Dusty and Silent | Bioweapon Research |
| 4 | Narrow Fissure in Cliff | Crystal-encrusted | Time Paradox Research |
| 5 | Through Old Sewer | Blood Red Walls | Language Virus Research |
| 6 | Atop Mountain | Decorated Tiles | Geothermal Power Station |
| 7 | Opens At Full Moon | Fire-Damaged | Nuclear Power Station |
| 8 | Scrawled With Runes | Winding and Narrow | Hypergeometry Research |
| 9 | Functioning Lift | Descend Into The Urth | Deep Core Mining |
| 10 | Broken Lift | Somehow Absorb Sound | Military Command Post |
| 11 | Functioning Escalator | Lightless and Dank | Titan AI Memory Banks |
| 12 | Broken Escalator | Spiralling, Strange | Titan AI Cooling System |
| 13 | Ruined Train Tunnel | Lit with Bioluminous Moss | Seed Bank |
| 14 | Beneath Toxic Water | Surprisingly Clean | Interrogation Chambers |
| 15 | Air Filtration Vent | Full of Ancient Corpses | Synth Production |
| 16 | Infested with Bats | Incredibly Cold | Illicit Cloning Facility |
| 17 | Barricaded from Inside | Enormous and Echoing | Spy Network Base |
| 18 | Below Arcology | Battle Damaged | Recycling Plant |
| 19 | Below Settlement | White and Sterile | Hidden Reservoir |
| 20 | Below Ruin | Filled with Garbage | Autarch's Hideout |

## Treasure Rooms (d20 by Depth — ⚙ ENGINE)

Roll 1d20 in Depth 1-4. **Depth 4+:** roll 2d20, stock from A and B. **Depth 9+:** roll 3d20, stock A, B and C. Most rows ARE engine generators — emit the call.

| d20 | A (Depth 1+) | B (Depth 4+) | C (Depth 9+) |
|---|---|---|---|
| 1-3 | d6 Trade Goods | Exotica | Exotica |
| 4-8 | Exotica | Exotica | Exotica |
| 9 | Exotica | Hypergeometric Codex ⚙`generate(action="codex")` | Source of Mystic Gift ⚙`generate(action="gift")` |
| 10 | Exotica | Cybernetic Implant | Source of Mystic Gift ⚙`generate(action="gift")` |
| 11 | Exotica | Hypergeometric Codex ⚙`generate(action="codex")` | Exotic Weapon ⚙`generate(action="weapon", tier="exotic")` |
| 12 | Exotica | Advanced Cybernetic Implant | Advanced Cybernetic Implant |
| 13 | Exotica | Source of Mystic Gift ⚙`generate(action="gift")` | Advanced Cybernetic Implant |
| 14 | Elixir ⚙`generate(action="elixir")` | Elixir ⚙`generate(action="elixir")` | (continue B) |
| 15 | Exotic Weapon ⚙`generate(action="weapon")` | Large Lair Cache | (continue B) |
| 16 | Cybernetic Implant | Medium Occult Cache | Large Occult Cache |
| 17 | Hypergeometric Codex ⚙`generate(action="codex")` | Large Survival Cache | XL Survival Cache |
| 18 | Source of Mystic Gift ⚙`generate(action="gift")` | Small Tomb Cache | Large Bandit Cache |
| 19 | Elixir ⚙`generate(action="elixir")` | Medium Bandit Cache | Large Tomb Cache |
| 20 | Roll again from Column B | Roll again from Column C | Small Magnificent Cache |

(Cybernetic implants: the Advanced Cybernetics d20 is in `rulebook/tables.json`, repaired 2026-06-13.)

## Lair Rooms (d20 by Depth)

Roll d20 at the floor's Depth. A "20" steps to the next Depth; a "1" steps back.

| d20 | Depth 1 | Depth 2 | Depth 3 | Depth 4 | Depth 5 |
|---|---|---|---|---|---|
| 1 | (roll Depth 1) | (roll Depth 1) | (roll Depth 2) | (roll Depth 3) | (roll Depth 4) |
| 2 | D4 Babble Birds | D10 Bandits | D8 Anthropophagi | D6 Battle Boars | D6 Drill Drones |
| 3 | 3d6 Blue Baboons | 3d6 Blue Baboons | D6 Battle Boars | Bacterial Gestalt Colony | D3 Face Dancers |
| 4 | D8 Cacogen | d6 Cacklemaw | 2d6 Cacklemaw | D4 Behemoth Toads | Doppelgeller |
| 5 | Daggertrunk | D6 Copy Cats | D3 Desiccators | 2d6 Cacklemaw + Virago | Fleshwarp |
| 6 | 2d6 Eyeless Dogs | D4 Doomsingers | D4 Doomsingers | D3 Desiccators | D6 Glass Tigers |
| 7 | D10 Faa Nomads | 2d6 Eyeless Dogs | D6 Flabmongers | Fool's Pool | Jollyhoss |
| 8 | D12 Feastbeasts | D6 Flabmongers | D8 Ghouls | D4 Giant Azure Scorpions | D6 Lazarus Guards |
| 9 | D8 Gene Thieves | D8 Greenguard | D4 Giant Azure Scorpions | D8 Ghouls | D4 Leopard Worms |
| 10 | D8 Greenguard | D8 Stumbling Drones | D8 Stumbling Drones | D6 Gitchghast | D4 Maladaptors |
| 11 | D8 Grey Crickets | D8 Grey Crickets | D10 Grimpets | D6 Glass Tigers | Metamorphic Sludge |
| 12 | D6 Lizard Lions | D8 Quill Spiders | Harlequin Serpent | D10 Grimpets + d3 Grimweavers | D4 Moonbeasts |
| 13 | D8 Luxfoe Beetles | D6 Lizard Lions | D6 Hiveymen | D6 Hiveymen | D4 Phase Panthers |
| 14 | 3d6 Phthalo-Jackals | D6 Tiger Flies | D6 Lizard Lions | D4 Hollow Maidens | D4 Pseudo-Giants |
| 15 | D8 Synth Skeletons | 3d6 Phthalo-Jackals | D6 Memory Eaters | Jollyhoss | D4 Sawbone Drones |
| 16 | D8 Nerve Crawlers | D6 Spambots | D6 Plated Beetles | D6 Lambent Lynx | Rustacean |
| 17 | D6 Voltworms | D8 Nerve Crawlers | D4 Sawbone Drones | Metamorphic Sludge | Turretwright |
| 18 | D8 Witchgrubs | D6 Planeyfolk | D8 Shriekmen | D4 Pseudo-Giants | Viridian Ooze |
| 19 | 2d6 Yurlings | D10 Zoanthropes | Subtle Stalker | D4 Seekers of Eyeless Wisdom | D4 Walking Wombs |
| 20 | (roll Depth 2) | (roll Depth 3) | (roll Depth 4) | (roll Depth 5) | (roll Depth 6) |

| d20 | Depth 6 | Depth 7 | Depth 8 | Depth 9 | Depth 10+ |
|---|---|---|---|---|---|
| 2 | Alzabo | Alzabo | Alzabo | d4 Alzabos | d4 Alzabos |
| 3 | Banisher | Amaranthine Death-Worm | Amaranthine Death-Worm | d4 Amaranthine Death-Worms | d4 Amaranthine Death-Worms |
| 4 | D3 Chimera | Banisher | Argent Shepherd | Argent Shepherd | Banisher |
| 5 | Chromavore | D3 Chimera | Banisher | Banisher | D3 Blightbeasts |
| 6 | Doppelgeller | Chromavore | Broodmother | Broodmother | d4 Broodmothers |
| 7 | Entropy Wight | D4 Echopraxists | Blightbeast | Blightbeast | Chernobog |
| 8 | Fractalisk | Entropy Wight | D6 Chimera | d4 Chromavores | d4 Chromavores |
| 9 | D6 Lazarus Guards | D4 Faminebearers | Chromavore | d4 Entropy Wights | Exemplar |
| 10 | D4 Leopard Worms | Fractalisk | D4 Echopraxists | Fissile Glittersludge | Fissile Glittersludge |
| 11 | D4 Maladaptors | Kronophage | Entropy Wight | Fractalisk | d4 Fractalisks |
| 12 | D4 Moonbeasts | D6 Lazarus Guard | D4 Faminebearers | Gorgon | Gorgon |
| 13 | D4 Phase Panthers | D6 Maladaptors | Fissile Glittersludge | Gravity Tyrant | Gravity Tyrant |
| 14 | D6 Regenerators | D6 Moonbeasts | Fractalisk | Kalopede | Kalopede |
| 15 | Rustacean | D6 Regenerators | Gorgon | Kronophage | Kronophage |
| 16 | D4 Scytheslivers | D4 Rustaceans | Juggernaut | Occulith | Occulith |
| 17 | Star Vampire | Psyche Leech | Kronophage | Quicksilver Exterminator | Quicksilver Exterminator |
| 18 | Viridian Ooze | Star Vampire | Psyche Leech | Thermasaur | Thermasaur |
| 19 | Xanthous Mycomorph | Unfolder | D4 Xanthous Mycomorphs | D4 Xanthous Mycomorphs | d4 Unfolders |
| 20 | (roll Depth 7) | (roll Depth 8) | (roll Depth 9) | (roll Depth 10) | Void Dragon |

(Depth-N "1" = roll one Depth lower; "20" = roll one Depth higher. Stat any creature with `lookup(action="creature")`.)

## Vault Hazards (d20 + current Floor number)

Roll d20 and add the floor number, so deeper floors surface nastier hazards. Engine-relevant rows emit a call.

| Total | Hazard | Effect (abridged) |
|---|---|---|
| 2 | Broken Glass | Moving quickly → DEX save vs d4. |
| 3 | Lightning Gun | Pressure pad fires d10 electrical at whoever touches it. |
| 4 | Unstable Ceiling | Sudden movement → cave-in, DEX save vs 3d6 crushing. |
| 5 | Unstable Floor | Failed DEX save → fall (3d6) or drop to a lower stratum. |
| 6 | Toxic Liquid Pool | d10 TOX on exposure. |
| 7 | Mind-slaving Hypnoscreen | EGO save vs paralysis when viewed; act blindfolded to avoid. |
| 8 | Alarm System | Loud noise → guaranteed encounter. |
| 9 | Proximity Mines | d4 hidden; PSY save to search, fail = d6 blast per mine triggered. |
| 10 | Vault Hornet Hive | d8 unblockable swarm/round near the hive; destroy it and they pursue. |
| 11 | Sentry Turrets | D4 Sentry Turrets watching the entrances. |
| 12 | Flammable Gas Leak | Hold breath; any flame → 5d10 blast + 5d10 fire. |
| 13 | Fungal Growths | Spores: CON save vs d8 choking per exploration turn. |
| 14 | Laser Grid Trap | Infrared trigger → DEX save vs 3d6 beam. |
| 15 | Electromagnet | d6 INT/round to Synths; draws and pins metal until switched off. |
| 16 | Vampiric Vines | DEX save to pass; fail = d4 STR/round drain until cut loose. |
| 17 | Corrosive Lichen | d4 acid/round while exposed. |
| 18 | Poisoned Water | Looks innocuous; poisoned → ⚙`generate(action="poison")` for the effect. |
| 19 | Disease | A Vaarnish disease lurks here → ⚙`affliction(kind="disease", action="apply")`. |
| 20 | Nanomachine Infection | A nanomachine infection lurks here → ⚙`affliction(kind="disease", action="apply")` (nanomachine catalog). |
| 21 | Hypergeometric Vortex | Each turn: draw someone in (STR save, fail = random teleport) or spit out a random creature. |
| 22 | Famine Field Projector | All in-room become Deprived; food decomposes. Projector AV 20 / 20 HP. |
| 23 | Deathblight Urn | 1 Deathblight/turn exposed; each point doubles damage taken + halves healing; fades 1/day. |
| 24 | Normality Field Projector | No Gifts/Codices; Hypergeometric/Outsider creatures take d10/round inside. Gen AV 20 / 40 HP. |
| 25 | Supercoolant Leak | Flooded with cold liquid: 1 DEX/exploration turn. |
| 26 | Friendship Field | No violence possible while active. Gen AV 20 / 40 HP. |
| 27 | Antigravity Field | No gravity; DEX save to "swim", fail = drift wrong way. Gen AV 20 / 40 HP. |
| 28 | Darkness Generator | Supernatural pitch black; all actions blind until destroyed. Gen AV 20 / 40 HP. |
| 29 | Neurotoxin Gas Trap | Infrared trigger → all Biological CON save vs Death. |
| 30 | Lithifying Pool | Living tissue → stone on contact, no save. |
| 31 | Highly-Entropic Field Generator | Lose 1 max HP/turn, unrecoverable. Gen AV 20 / 40 HP. |

(The book's hazard list continues past 31 — antimatter sphere, etc. — for very deep floors; pull from the PDF p.114 when a vault runs that deep.)

## Special Rooms (d20 — many are ⚙ ENGINE)

| d20 | Type | Note |
|---|---|---|
| 1 | Advanced Weapon | ⚙`generate(action="weapon", tier="advanced")` |
| 2 | Anomaly | Generate (content-forge anomaly / location tables) |
| 3 | Autarch Shrine | Generate (miscellany: autarchs) |
| 4 | Book | Generate (miscellany: books) |
| 5 | Drug | ⚙`generate(action="drug")` |
| 6 | Fine Art | Generate (miscellany: fine art) |
| 7 | Food | A food-ration source |
| 8 | Fresh Water | A fresh-water source (water tokens) |
| 9 | Hypergeometric Gateway | Leads deeper, to the surface, or elsewhere in Vaarn |
| 10 | Medgel Bed | Resting cures all Wounds + restores all HP — ONCE |
| 11 | Musical Instrument | Generate (instruments) |
| 12 | Mutation | Mutagenic gel: inject for a random mutation |
| 13 | Mystic Gift | ⚙`generate(action="gift")` |
| 14 | Oracle | A reclusive (probably mad) Oracle — see SETTLEMENTS.md Oracle's Sanctum |
| 15 | Petty God Shrine | Generate (miscellany: petty gods) |
| 16 | Poison | ⚙`generate(action="poison")` |
| 17 | Quantum Daemon | A trapped Lesser Quantum Daemon |
| 18 | Secret Doorway | Hidden passage to another room, or a secret Exotica room |
| 19 | Secure Campsite | Can be fortified; safe Long Rest |
| 20 | Vault Merchant | A vault-bound merchant (table below) |

## Vault Fauna & Flora (d20)

| d20 | Type | Note |
|---|---|---|
| 1 | Bat Colony | Disturbed by light/noise → encounter roll. |
| 2 | Vaultcumbers | d6; each = one food AND one water ration. |
| 3 | Cave Spiders | Shy, harmless; webs everywhere. |
| 4 | Ickbulbs | d4 foul-tasting Ickbulbs. |
| 5 | Sand Crabs | 2d6; each = a food ration if boiled. |
| 6 | Phantom Grass | Bioluminescent; conceals you from pursuers. |
| 7 | Dwarf Giraffes | A family of 2d4. |
| 8 | Bloodmoss | Crimson moss mottling the walls. |
| 9 | Sand Octopus | Worth 3 food rations if caught. |
| 10 | Helix Vines | Coiling; conceals you from pursuers. |
| 11 | Centipedes | D4 forearm-long; light-shy; d4 TOX bite if mishandled. |
| 12 | Swordgrass | Moving fast → DEX save vs d4. |
| 13 | Albino Toads | 2d6; poisonous (d8 TOX) if eaten. |
| 14 | Echoferns | Quietly repeat the last noise they heard. |
| 15 | Glow Mice | 3d6; netted in a bottle = a passable light source. |
| 16 | Cave Cacti | Edible but bitter — CON save to keep down and gain the ration. |
| 17 | Land Parrots | 2d4 flightless, tame, stupid; take food from your hand. |
| 18 | Pet Rock | A living pet rock hidden among real rocks; approaches the pure of heart. |
| 19 | Little Torinos | d6 toy-sized rhinos. |
| 20 | Widow's Palm | 2d6 poisonous flowers (d12 TOX if eaten). |

## Vault Merchants (d10)

Rare merchants who seek customers in Vaarn's most dangerous corners. **Killing/extorting them is allowed** — but remove that merchant from future rolls, and after two such outrages ALL vault merchants stop appearing (word gets around).

The full d10 roster (all 10 named merchants + their stock/wants) is engine-owned — roll it via `rulebook(action="get", id="table-vault-merchants", roll=<d10>)` rather than from a copy here, so this reference can't drift from the certified book table. Merchants who sell Gifts/Codices/Weapons/Cybernetics/Elixirs then delegate to the engine generators per the ENGINE CONTRACT.

## Engine handoff

The treasure, special-room, and hazard tables are riddled with engine artifacts —
codices, elixirs, gifts, poisons, drugs, weapons, diseases. When one comes up,
emit its `⚙` call from the ENGINE GENERATOR CONTRACT rather than statting it in
prose. The vault map itself registers via `map(action="init", ...)` per SKILL.md.
