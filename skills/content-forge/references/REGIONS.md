# Region Creation & Place Names

Book-faithful transcription of the CH Referee's Toolbox region-creation system
(printed pp.157-161). This is the **hex-cluster / drop-dice** method for
sketching a whole region; the skill's REGION scale guidance (SKILL.md) covers
the design judgement on top.

> **Preview-edition note:** several Place Name columns are placeholders in the
> preview PDF (only a couple of entries filled). Those are flagged below — do
> NOT invent entries for them ([[no-invented-systems]]); generate names freely
> in fiction or pull from the two complete columns.

## Region Creation — the procedure (drop-dice method)

1. Take a blank A4 sheet.
2. **Drop a handful of dice** (5-6 for a decent region; no upper limit — more dice = more features). Any size up to d20; smaller dice constrain results.
3. **Circle each die where it fell** and record its number. Consult the **Regional Feature** chart (below) for what location it is.
4. **Connect locations** with lines (2-3 connections each is plenty) = known travel routes. For the days of travel between two: if close on the page roll d6; moderate distance 2d6; very far 3d6 (the result = days on foot).
5. **Route safety:** routes touching an even-numbered location are (relatively) safe. A route between two **odd-numbered** locations carries a **hazard** (bandits, roving monster, weather, terrain).
6. **Detail each location** using this book's tables (you're not obliged to abide by results — inspiration only).
7. For overall terrain, roll **Landscape** (below); use the Landmarks table (TABLES_D100.md) for navigation features.
8. **Build a region encounter table** — let the region's character pick the creatures (a synth-factory ruin → malfunctioning synths; settlement-rich → trade caravans).
9. **Seed a few NPCs** and what they want from the party — call `generate(action="story_seed")` for a WHO/WHAT/WITH/WHY hook if stuck.

## Regional Feature (d20)

| d20 | Location Type | Landscape | Route Hazard "Named For" |
|---|---|---|---|
| 1 | Ruin | Featureless Sands | Famous Resident |
| 2 | Settlement | Salt Pan | Famous Resident |
| 3 | Oasis | Hard Rocky Plain | Local Wildlife |
| 4 | Vault | Dried-up Lake | Local Wildlife |
| 5 | Lair | Dried-up River | Natural Wonder |
| 6 | Holy Place | Towering Monoliths | Natural Wonder |
| 7 | Arcology | Mesas | Natural Hazard |
| 8 | Grave | Low Hills | Natural Hazard |
| 9 | Cacklemaw Den | Single Mountain | Famous Monster |
| 10 | Wreck | Toxic Lake | Famous Monster |
| 11 | Faa Nomad Camp | Toxic River | Long-Dead Settlement |
| 12 | Bandit Camp | Fungal Forest | Long-Dead Settlement |
| 13 | Oracle's Sanctum | Crystal Growths | Forgotten Religion |
| 14 | Science Mystic's Abode | Windswept Plateau | Forgotten Religion |
| 15 | Hegemony Outpost | Mountainous | Local Weather |
| 16 | Fortress | Winding Canyons | Local Weather |
| 17 | Trade Post | Abandoned City | Natural Resource |
| 18 | Archive | Cactus Fields | Natural Resource |
| 19 | Bounty Hunter's Camp | Riddled with Caves | Name No Longer Understood |
| 20 | Anomaly | Garbage-strewn Wastes | Name No Longer Understood |

Most Location Type results have their own sub-generator in **LOCATIONS.md**
(anomaly, archive, arcology, bandit camp, grave, oasis, ruin, wreck, etc.);
Settlement → **SETTLEMENTS.md**; Anomaly also has a d20 detail generator (below).

The "Named For" column tells you what a place/route is named after — pair it
with the Place Names tables for a quick evocative name.

## Place Names — delegate to the engine

Certified region name generators (VoV Referee's Toolbox p.159-160). Roll the category you need:

```
roll(action="placename", category="<category>")
```

Categories (the engine carries ALL of them, including the Settlements / Ruins / Holy Places /
Hegemony columns the old preview was missing):
`settlements`, `ruins`, `holy_places`, `hegemony_places`, `autarchic`, `mystic` (full d20),
and `faa_nomad` (partial — only 3 names printed in the preview book).

Use a result as-is, or as a seed to twist into something the region's history suggests.

## Anomaly Generator (d20 — printed p.161)

Roll each column independently for a strange anomaly (also reachable as the
Anomaly location type). Effects lean weird — many tie to engine systems.

| d20 | Quality | Form | Primary Effect | Secondary Effect |
|---|---|---|---|---|
| 1 | Dazzling | Web | Inverts Local Gravity | Induces Paranoia |
| 2 | Nauseating | Mist | Heals Injuries | Total Silence Nearby |
| 3 | Floating | Cave | Translates Languages | Absorbs Light |
| 4 | Singing | Tower | Reanimates Dead | Extreme Cold Nearby |
| 5 | Mist-like | Lotus | Merges Creatures Together | Strange Music Audible |
| 6 | Glitching | Tree | Makes Prophecies | Strange Voices Echo |
| 7 | Luminous | Pool | Other Universe Visible | Localised Weather System |
| 8 | Radioactive | Fountain | Implants Memories | Time Flows Strangely |
| 9 | Self-replicating | Stone | Implants Mystic Gifts ⚙`generate(action="gift")` | Induces Mania |
| 10 | Quicksilver | Skull | Induces Amnesia | Always Nighttime Nearby |
| 11 | Many-eyed | Prism | Induces Delusions | Induces Mutations |
| 12 | Iridescent | Cube | Kills Indiscriminately | Rusts All Metal |
| 13 | Toxic | Pyramid | Induces Empathy | Exudes Lightning |
| 14 | Crystal | Sphere | Transforms Matter | Exudes Flames |
| 15 | Speaking | House | Teleports Matter | Exudes Toxins ⚙`generate(action="poison")` |
| 16 | Mobile | Miasma | Creates Planeyfolk | Creates Solid Light |
| 17 | Blossoming | Waterfall | Creates Monsters (MONSTERS.md) | Nanomachine Cloud ⚙`affliction(kind="disease", action="apply")` |
| 18 | Burning | Infant | Grants Visions of Past | Infection with Virus ⚙`affliction(kind="disease", action="apply")` |
| 19 | Mesmerising | Shell | Grants Visions of Future | Infection with Fungus ⚙`affliction(kind="disease", action="apply")` |
| 20 | Terrifying | Helix | Makes Thoughts Solid | Infection with Spirit |

## Engine handoff

Region locations register via `geography(action="add_location", ...)`; vaults
within them via `map(action="init", ...)`. Anomaly effects that grant Gifts,
exude toxins, or spread infections delegate to the engine generators per the
ENGINE GENERATOR CONTRACT (SKILL.md).
