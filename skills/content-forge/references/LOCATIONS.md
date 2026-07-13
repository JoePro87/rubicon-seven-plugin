# Locations — delegate to the engine

Locations are generated from the **certified Crimson Hound tables**. Don't roll them from a
table here — call the engine, then write the place into fiction. (Light generative surface: the
sub-table gives you the bones — who's here, what they want, the weird true detail — and you turn
it into somewhere real.)

## Generate a location

**Random** (rolls the certified d20 location-type, then its sub-generator):
```
roll(action="location")
```

**A specific type:**
```
roll(action="location", location_type="<type>")
```

The certified location types (certified `table-region-location-type` order):

| d20 | Type | `location_type=` |
|----|------|------------------|
| 1 | Ruin | `ruin` |
| 2 | Settlement | → `roll(action="settlement")` |
| 3 | Oasis | `oasis` |
| 4 | Vault | `vault` (see `references/VAULTS.md`) |
| 5 | Lair | `monster_lair` |
| 6 | Holy Place | `holy_place` |
| 7 | Arcology | `arcology` |
| 8 | Grave | `grave` |
| 9 | Cacklemaw Den | `cacklemaw_den` |
| 10 | Wreck | `wreck` |
| 11 | Faa Nomad Camp | `faa_camp` |
| 12 | Bandit Camp | `bandit_camp` |
| 13 | Oracle's Sanctum | `oracle_sanctum` |
| 14 | Science Mystic's Abode | `science_mystic` |
| 15 | Hegemony Outpost | `hegemony_outpost` |
| 16 | Fortress | `fortress` |
| 17 | Trade Post | `trade_post` |
| 18 | Archive | `archive` |
| 19 | Bounty Hunter's Camp | `bounty_hunter` |
| 20 | Anomaly | `anomaly` |

(Also available: `hegemony_protectorate` as a Hegemony Outpost sub-generator.)

## How to use it

Each sub-table returns multi-column book detail. Read it, then layer on the **soul** (see
SKILL.md — etiology, history, a temporal stake) and the FINGERPRINT sensory baseline. The dice
choose; you evaluate and write. Don't pre-roll a whole region into a spreadsheet — generate a
place when the party reaches it, and let it feel discovered.

## Pre-authored keyed sites (drop-in, don't generate)

Named Adventure-Atlas / vault sites are ingested whole — fetch them, don't re-roll:
`rulebook(action="get", id="<id>")` (or `rulebook(action="search", ...)` / `lookup` by name).

| Site | id |
|---|---|
| Tomb of Nassak An-Rah (starter vault) | `table-location-tomb-of-nassak-an-rah` |
| Fount of Illustrious Flesh | `table-location-fount-of-illustrious-flesh` |
| Eigin Oasis (safe-oasis settlement) | `table-location-eigin-oasis` |
| Caeba in the Maw (trundle-town + Grandfather corpse-dungeon) | `table-location-caeba-in-the-maw` |

The 7 wilderness sub-generators above are also addressable by id for the rulebook path
(`rulebook(action="get", id=...)`): `table-grave`, `table-holy-place`, `table-oasis`,
`table-ruin`, `table-science-mystic`, `table-trade-post`, `table-wreck`. Criminal-gang
generation: `table-criminal-gang-name` / `-drama` / `-activity` (book p.267-268).
