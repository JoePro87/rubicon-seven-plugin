---
name: content-forge
description: Generate Vaarn locations with mechanical depth AND narrative soul. Creates everything from single rooms to hexcrawls. MANDATORY - Use dice tools for all random elements. Output structured prep documents with DM-only secrets. Integrates with the map() and geography() tools. Use when asked to "generate", "create", "prep", "build" any location, dungeon, region, or hexpedition.
---

# Content Forge — Vaarn Worldbuilding System

## BEFORE GENERATING ANYTHING

1. **Check lorebook:** `lorebook(action="view", keyword="<location name>")` — does this place already exist in canon?
2. **Check geography:** `geography(get_distance)` — is this location registered? Verify distance/direction.
3. **Check campaign history:** `search(action="history", query="location or related NPCs")` — has this place or its people appeared in gameplay?
4. **Check rulebook:** `rulebook(action="search", query="relevant mechanic")` — use official Vaarn 2e rules for DCs, hazards, environmental effects

Generate ONLY after confirming no canon conflicts. New content must integrate with existing world state.

---

## CONTENT TYPE FORK (decide this FIRST)

Every content-forge invocation falls into one of two tracks. The track determines the methodology.

### ARC CONTENT — "Main Quest"
Connected to existing narrative arcs, established NPCs, or active campaign threads. Examples: a site tied to a faction the party is already entangled with; an NPC's homeland or origin; the return of a recurring threat; a place a player has stated intent to visit for story reasons.

**Signals:** The lorebook/campaign history checks above returned significant results. Named NPCs are involved. An existing dossier, prep file, or design doc references this location. The player has stated intent to visit for story reasons.

**Requirements:**
- Full canon excavation (lorebook + campaign history + geography + dossiers + design docs)
- Character hooks for each relevant party member, grounded in specific campaign days
- Five-bullet NPC audit for every significant NPC — KNOW, HIDING, LEVER, NEVER SAY, WOULD TRADE (see `skills/dm-design/dm-design-agent-prompt.md`)
- Victory conditions (designed solution + creative alternative + failure state)
- Sensory detail propagated from the FINGERPRINT (the location's sensory baseline — the smell, light, sound, and texture that make it distinct, established once and echoed with variation into every room) into every keyed area
- `/dm-design` quality gate auto-triggers after generation
- Etiology grounded in verified campaign canon

### DISCOVERY CONTENT — "Weird Shit"
Standalone locations that exist for their own reasons. The world is old. These places were here before the party and will be here after. They connect to the SETTING, not the STORY. Examples: a random vault in the Glass Waste, a Faa oasis, a monster lair, a science-mystic's tower, a Titan ruin with its own problems.

**Signals:** Lorebook/campaign history checks returned nothing or minimal results. No existing dossier or design doc references this location. The player is exploring, not pursuing a thread.

**Requirements:**
- Tables drive generation (d20 location type, d12 history, d10 temporal stakes — use ALL the tables)
- Etiology serves the LOCATION's story, not the party's arc
- Character hooks are optional and generic (ancestry-based, not campaign-day-based)
- NPCs generated via `generate(action="npc")` — the world is full of strangers
- Creatures rolled via `roll(action="location", location_type="monster_lair")` (d100 Monster Lair) — dice choose, DM evaluates
- Five-bullet NPC audit still applies for significant NPCs (good practice regardless)
- `/dm-design` quality gate is OPTIONAL (player can request it, but it doesn't auto-trigger)
- Discoveries should surprise. Connections to the arc are coincidental or absent. The fun is finding something genuinely alien that nobody planned for.

**The dying-earth principle:** The best weird shit exists because a Titan engineer had a bad idea 10,000 years ago, or a fungal colony colonized a ruin, or a synth has been maintaining a garden for no one for centuries. The location doesn't know the party is coming. It doesn't care. It was doing its thing before they arrived and will continue after they leave. THAT is discovery.

---

## THE FORGE PRINCIPLES

Every generated location must have:

1. **Mechanical Foundation** — Tables, stats, encounters (use MCP tools)
2. **Narrative Soul** — Why it exists, who built it, what happened here
3. **Temporal Stakes** — What pressure or ticking clock exists?
4. **Character Hooks** — Why does THIS party care? (Arc: specific. Discovery: generic or absent.)
5. **Monsters & Encounters** — Custom encounter table with `lookup(action="creature", query="X")`
6. **Exotica & Loot** — Treasure placed with `roll(action="exotica")`, tied to history
7. **Spoiler Discipline** — DM-only content clearly marked
8. **Sensory Propagation** — FINGERPRINT sensory baseline extends into EVERY keyed area with 2+ room-specific details. "What does THIS room smell/sound/feel like?"
9. **Victory Conditions** (LOCATION scale+) — Designed solution + creative alternative + failure state. Constraints define the problem; the player defines the solution.

**The Weirdness Principle:** Vaarn is ten thousand years past the end of the world. NOTHING is normal. A fungal colony has been voting on municipal policy for three centuries. A synth tends a garden of glass flowers for a master who died before mammals evolved on this continent. A oasis tastes like champagne because a Titan-era water purifier is still running on corrupted parameters. The default is STRANGE. Familiar fantasy is the exception — if a location could exist in a generic RPG setting, it needs another pass. When generating, always ask: "What is the weirdest true thing about this place?" and put THAT in the first line of the description. Wonder and decay occupy the same sentence, the same object. The beautiful thing is broken. The terrifying thing is mundane. The sacred thing is absurd. Lean into it.

**The goal:** Locations that feel discovered, not generated.

---

## GENERATION MODES

### Mode 1: On-the-Fly (During Play)
When the party encounters something unexpected.

1. Roll on appropriate tables (use dice tools)
2. Generate 2-3 key details and 1 NPC
3. Describe what's observable (no DM-only reveals)
4. Note for later prep if significant

**Output:** Conversational description

### Mode 2: Prep (Before Session)
When building content for future sessions.

1. Roll full location generation
2. Apply soul generation framework
3. Create prep file with DM-only sections
4. Register with appropriate system (geography, map, vault)

**Output:** Structured prep file

---

## SCALE LEVELS

### AREA (Single Encounter Space)
- One room, one scene
- 1-2 notable features
- Optional obstacle or NPC
- Used for: vault rooms, camp areas, single points of interest

### LOCATION (Complete Site)
- 3-8 areas/rooms
- Central tension or purpose
- 2-4 NPCs with motivations
- Used for: oases, trade posts, camps, small settlements

### VAULT (Exploration Site)
- 8-20 rooms across 1-3 floors
- Dungeon structure with progression
- Secrets, obstacles, boss/climax
- Used for: ruins, vaults, dungeons, archives
- **Random-generation tables: `references/VAULTS.md`** — the book's vault procedure (3d20 node-cluster method), entrance/tunnel/function seed, treasure/lair/hazard/special/fauna tables. Generate raw content there, then shape it with the LAYOUT TOPOLOGY / ATTRITION / SOUL frameworks below. Treasure and hazard rows delegate to engine generators (codices, elixirs, gifts, poisons) — emit the `⚙` call.

### REGION (Hex Cluster)
- 4-8 connected locations
- Shared terrain and culture
- Trade routes and hazards
- Used for: regional prep, multi-session arcs
- **Random-generation tables: `references/REGIONS.md`** — the book's drop-dice region method (Regional Feature d20, Landscape, route-hazard "Named For", Place Names, Anomaly d20). Locations register via `geography(action="add_location")`.

### HEXPEDITION (Full Hexcrawl)
- Multiple regions
- Overworld journey structure
- Weather, foraging, navigation
- Used for: major expeditions, campaign arcs

---

## SOUL GENERATION FRAMEWORK

Apply to every location at LOCATION scale or above.

Call `roll(action="soul")` to roll all five dimensions below in one pass. It draws from the engine's certified tables (`data/content_forge_tables.json`) and returns each dimension as a labeled roll — origin (d20 etiology), two history layers (d12 each — locations typically have 2-3), temporal stakes (d10), ancient intelligence presence (d8), and a ghosts & echoes entry (d8) — each line showing the die result and the rolled fields. The DM may override any single rolled entry for better fit; state why when you do, so the override is a visible judgment call, not a silent drift from the roll.

### 1. ETIOLOGY (Origin)
Why the location exists: what era it comes from, who built it, and what it was originally for. This is the seed the rest of the soul grows from — history layers explain what happened to that original purpose over time, stakes explain what's still moving today, and the intelligence/echoes dimensions explain what's left of the people (or things) that were here.

### 2. HISTORY LAYERS
Every location has 2-3 historical layers — distinct periods when different occupants used the place for different reasons, each leaving a remnant (physical evidence) and a ghost (a narrative echo). For each layer, work out:
- **Era:** When this layer was active
- **Occupants:** Who was here
- **Activity:** What they did
- **Remnant:** What physical evidence remains
- **Ghost:** What psychic/narrative echo persists

### 3. TEMPORAL STAKES
What clock is ticking right now — the pressure that makes this location matter this session, not whenever the party gets around to it.

### 4. ANCIENT INTELLIGENCES
`roll(action="soul")` always includes an Ancient Intelligence roll; use it if the location's etiology is Titan-era or Pre-Collapse (a plausible AI could still be running here) — otherwise there's no AI, and the roll goes unused. When one applies, work out:
- What was their original function?
- Who were they loyal to?
- What do they remember of the Collapse?
- What do they want now?

### 5. GHOSTS AND ECHOES
Not literal ghosts (unless warranted) — the narrative presence that lets the party learn the location's history without an NPC reciting it at them: a recording, a journal, graffiti, a corpse's story, a psychic dream-impression, a rumor fragment, a remembering construct, or (rarely, significantly) an actual spirit.

### 6. CHARACTER HOOKS

For every significant location, generate a hook for each party member — keyed to their **ancestry, traits, and personal history**, not to a fixed roster. Use the table below as a starting point; layer on whatever the specific character's background and the campaign's threads suggest.

| PC ancestry / trait | Hook Type | Example Connection |
|---------------------|-----------|-------------------|
| **True-kin** | Old-world lineage, navigation, Autarchy legacy | Autarchy site, stellar navigation, ancestral family |
| **Cacogen** | Mutation, outsider perspective | Bioengineering site, cacogen history, a mutation's source |
| **Synth** | Synthetic nature, memory, machine kinship | Synth history site, AI research, memory crystals |
| **Newbeast** | Beast society, small-creature access | Animal territory, small passages, a newbeast community |
| **Neobloom** | Substrate-born, botanical nature | Botanical architecture, substrate sites, grove/bloom history |
| **Mycomorph** | Fungal hive-mind, spore networks | A fungal colony, decay sites, spore-lore |
| **Faa Nomad** | Clan heritage, desert lore | A Faa clan connection, seasonal gathering ground, ancestor graves |
| **Lithling** | Mineral body, deep-time endurance | Titan-era stone, geological wonders, ancient ruins |
| **Any special skill** | Engineering, telekinesis, sensors, logistics, etc. | A challenge or reward that rewards that specific capability |

**Hook Template:**
- **What draws them:** Why this character specifically cares
- **What they might find:** Character-specific reward or revelation
- **What risk they face:** Character-specific vulnerability here

---

## CREATURE & ENCOUNTER GENERATION

**Every location MUST include monsters and a custom encounter table.**

### Monster Population

For each location, determine:

1. **Dominant Creature** — The primary threat or inhabitant
2. **Secondary Creatures** — 1-2 supporting monster types
3. **Ambient Fauna** — Non-threatening wildlife for atmosphere

### Monster Placement by Scale

| Scale | Dominant | Secondary | Ambient |
|-------|----------|-----------|---------|
| AREA | 1 type | — | Optional |
| LOCATION | 1 type | 1 type | 1-2 types |
| VAULT | 1-2 types | 2-3 types | 2-3 types |
| REGION | 2-3 types | 3-5 types | 3-5 types |

### Monster Selection

1. **Call `roll(action="location", location_type="monster_lair")`** (d100 Monster Lair) for thematic creatures — **ACTUALLY ROLL. Do not browse the bestiary and hand-pick.** Hand-picking causes alphabetical anchoring (e.g. Grey Crickets + Grimweaver + Grimpets all from the G section). The d100 table forces diversity across the full bestiary.
2. **Call `lookup(action="creature", query="name")`** for every creature — never approximate stats
3. **Evaluate the roll** — if the creature doesn't fit the location thematically, roll again. But start with dice, not with preference.
4. **Place logically** — creatures should fit the location's history and environment
5. **Check letter diversity** — if all selected creatures share a starting letter, you probably browsed instead of rolling. Roll again.
6. **Vary behaviors** — same creature type can be hunting, sleeping, wounded, with young
7. **Need an ORIGINAL creature?** When no bestiary entry fits, build one with the **Monster Generator** (`references/MONSTERS.md`): roll Level/HP, Type, AV, Morale, number encountered, attacks, and form/hue/texture/behaviour/habitat. A built creature's Type sets its alchemy Essence and immunities; a Poison attack can be statted via `⚙ generate(action="poison")`. Prefer `lookup(action="creature")` first; generate only when nothing fits.

### Encounter Table Structure

**Every LOCATION or larger MUST have a custom encounter table.**

Template:
```markdown
## ENCOUNTER TABLE: [Location Name]

Roll d6 every exploration turn. Encounter on 1 (or 1-2 in dangerous areas).

| d8 | Encounter | Stats |
|----|-----------|-------|
| 1 | [Dominant creature] — [context] | lookup(action="creature", query="X") |
| 2 | [Dominant creature] — [different context] | lookup(action="creature", query="X") |
| 3 | [Secondary creature] — [context] | lookup(action="creature", query="X") |
| 4 | [Secondary creature] — [context] | lookup(action="creature", query="X") |
| 5 | [Ambient fauna or signs] | Non-combat |
| 6 | [NPC from location] | generate(action="npc") if needed |
| 7 | [Environmental hazard] | Tied to location |
| 8 | [Special/unique event] | One-time or rare |
```

### Encounter Variety

Same creature, different encounters:
- Hunting vs sleeping vs feeding
- Single vs pack vs with young
- Aggressive vs curious vs fleeing
- Fresh vs wounded vs dying
- Signs/tracks vs actual creature

---

## EXOTICA & LOOT GENERATION

**Every VAULT or larger MUST include exotica and loot.**

### Loot Placement by Scale

| Scale | Exotica | Trade Goods | Consumables |
|-------|---------|-------------|-------------|
| AREA | 0-1 | 1-2 | 1-3 |
| LOCATION | 1-2 | 3-5 | 3-6 |
| VAULT | 2-4 | 5-10 | 5-10 |
| REGION | Per location | Per location | Per location |

### Exotica Generation

**Always use MCP tools:**
- `roll(action="exotica")` — Generate random exotica item with full stats
- `roll(action="exotica", specific_roll=42)` — Get specific entry by number
- `lookup(action="exotica", query="keyword")` — Search for thematic items

### Loot Placement Guidelines

1. **Roll exotica** using `roll(action="exotica")` for each item
2. **Place logically** — loot should make sense in context (what would previous occupants have?)
3. **Tie to history** — exotica can reveal story (whose weapon was this? why was it left?)
4. **Add character hooks** — items that matter to specific PCs
5. **Vary accessibility** — some obvious, some hidden, some guarded

### Mechanical consumables = engine-minted

Poisons, drugs, elixirs, codices, and Mystic Gift sources are NOT prose loot — they are engine artifacts. When placing one, carry the `⚙` call from the ENGINE GENERATOR CONTRACT (see MCP TOOL INTEGRATION) so the real book row gets rolled at play time, not invented here:

- a venom vial / coated blade / toxic-creature harvest → `⚙ generate(action="poison")`
- a drug cache → `⚙ generate(action="drug")`
- an alchemist's elixir / brewed tonic → `⚙ generate(action="elixir")`
- a hypergeometric codex → `⚙ generate(action="codex")`
- an obelisk / psychic NPC / locus that grants a Gift → `⚙ generate(action="gift")`

### Loot in Prep Files

```markdown
### Loot
**Exotica:**
- [Item from roll(action="exotica")] — [where found, why it's here]

**Trade Goods:**
- [Item], [quantity], [value in WATER TOKENS — the campaign currency; 1 token = 1 water ration]

**Consumables (mechanical → emit the engine call, do not stat in prose):**
- Rations (Xd6), water units, ammunition
- [Poison/drug/elixir/codex] → ⚙ generate(action="...") per the ENGINE GENERATOR CONTRACT
```

---

## PUZZLE DESIGN

**Every VAULT MUST include at least one puzzle. Puzzles reward thinking, not rolling.**

### Puzzle Types

| d8 | Type | Description | Example |
|----|------|-------------|---------|
| 1 | **Mechanical** | Physical mechanism requiring manipulation | Rotate crystalline lenses to align a light beam through a series of prisms to a receptor |
| 2 | **Sequential** | Steps must be performed in correct order | Governance immersion bays must be activated in the seven-node sequence (lore provides clues) |
| 3 | **Environmental** | Use the room's features to overcome an obstacle | Flood a chamber by redirecting ancient plumbing to float cargo across a gap |
| 4 | **Informational** | A clue found earlier unlocks progress here | A name from the memorial wall is the passcode for a sealed door |
| 5 | **Resource** | Spend something to gain something | Power the elevator by draining your light source — proceed in darkness |
| 6 | **Social** | Convince, deceive, or negotiate with a guardian | A degraded AI asks questions only the original inhabitants would know — bluff or research |
| 7 | **Spatial** | Navigate a space that doesn't behave normally | Rooms connect in impossible geometry; mapping reveals the pattern |
| 8 | **Temporal** | Time-based pressure changes the puzzle state | The solution is only accessible while a machine cycles — 3 rounds to act before it resets |

### Puzzle Design Principles

- **Multiple solution paths.** Every puzzle should have at least 2 valid approaches (intended + creative). A brute-force option should exist but cost something (HP, time, noise, resources).
- **Clues are earned, not given.** Place clues in earlier rooms. Players who explored thoroughly have advantages. Players who rushed still have a chance — it's just harder.
- **Failure is not a dead end.** A failed puzzle should cost resources or time, not block progress entirely. The door opens eventually — but now the encounter table gets worse, or you've used your only light source.
- **Tie to the location's history.** The puzzle should exist because someone built it for a reason. A governance arcology has governance puzzles. A weapons lab has containment puzzles. A tomb has memorial puzzles.

### Puzzle Placement

| Scale | Minimum Puzzles | Notes |
|-------|----------------|-------|
| AREA | 0 | Optional |
| LOCATION | 0-1 | If present, gates a reward |
| VAULT | 1-2 | At least one gates progression, one gates bonus loot |
| REGION | Per vault | Each vault has its own |

---

## TRAP DESIGN

**Traps are the location defending itself — active hazards placed by builders or created by decay.**

### Trap Types

| d10 | Type | Trigger | Effect |
|-----|------|---------|--------|
| 1 | **Pressure plate** | Weight on tile | Projectile (d6), pit, or alarm |
| 2 | **Tripwire** | Movement through doorway | Net, blade (d8), or noise |
| 3 | **Chemical release** | Opening container/door | Toxin cloud (CON save vs poison), corrosive spray (d6) |
| 4 | **Collapsing floor** | Weight threshold | Fall (d6 per 10ft), split party |
| 5 | **Automated defense** | Motion/heat sensor | Laser (d10 beam), turret burst, force field |
| 6 | **Lure trap** | Touching bait item | Cage, adhesive, alarm + reinforcements |
| 7 | **Environmental shift** | Timer or trigger | Room floods, fills with sand, seals shut, temperature drops |
| 8 | **Psychic trap** | Proximity to object | PSY save vs hallucination, fear, memory intrusion |
| 9 | **Decay hazard** | Disturbing unstable structure | Ceiling collapse (DEX save vs 15, d6), toxic dust, electrical discharge |
| 10 | **Symbiotic** | Creature + mechanism | Trap herds prey toward creature's ambush point |

### Trap Design Principles

- **Telegraphed but not obvious.** Describe the evidence (scorch marks, bones near a doorway, a floor tile that's cleaner than its neighbours) without naming the trap. Observant players avoid it. Rushing players eat it.
- **Detection rewards skill use.** A search, a careful look, a scout sent ahead, a character with sensors or radar — these should reveal traps before they fire.
- **Consequences scale with depth.** Surface traps warn (d4, noise). Mid-vault traps hurt (d6-d8, status effects). Deep traps punish (d10+, split party, resource drain).
- **Traps interact with creatures.** The best traps drive you into something else — a noise trap that alerts the dominant creature, a pit that drops you into a nest, a chemical release that enrages nearby wildlife.

### Trap Placement

| Scale | Minimum Traps | Notes |
|-------|--------------|-------|
| AREA | 0 | Optional |
| LOCATION | 0-1 | Usually decay hazards |
| VAULT | 2-4 | Mix of intentional and decay. At least 1 per floor. |
| REGION | Per location | Concentrated in vaults and lairs |

---

## BOSS ENCOUNTER DESIGN

**Every VAULT MUST have a climactic encounter — a fight or confrontation that tests the full party.**

### Boss Sources

| d6 | Boss Type | Example |
|----|-----------|---------|
| 1 | **Apex predator** | The creature that owns this territory — evolved, adapted, territorial |
| 2 | **Corrupted guardian** | Defense system still running but degraded — attacks everything |
| 3 | **Rival party** | Someone else wants what's here — vault raiders, Hegemony salvage team, Cacklemaw scouts |
| 4 | **Environmental climax** | The vault itself is the boss — collapsing, flooding, sealing, activating |
| 5 | **Ancient intelligence** | AI, psychic entity, or bound consciousness — social or combat or both |
| 6 | **Evolved symbiosis** | Two creature types that have merged into something worse over millennia |

### Boss Design Principles

- **Test multiple capabilities.** A boss that only requires "hit it until it dies" wastes the party's diversity. Good bosses require combat AND problem-solving AND positioning AND communication.
- **Lair actions.** The boss's environment acts on its behalf. The room changes each round — a door seals, terrain shifts, reinforcements arrive from a specific direction, a hazard activates on a timer.
- **Morale matters.** Not every boss fights to the death. A guardian might parley once wounded. A rival party might surrender or flee with partial loot. An AI might offer a deal.
- **Foreshadow the boss.** Evidence of the boss should appear 2-3 rooms before the encounter — tracks, kills, environmental damage, NPC warnings. The party should know something big is ahead. Surprise is for traps; dread is for bosses.
- **The boss guards something.** The reward behind the boss should be proportional to the threat. If the boss is guarding nothing, it's just a fight. If it's guarding the mission objective, the stakes are real.

### Boss Placement

| Scale | Bosses | Notes |
|-------|--------|-------|
| AREA | 0 | Too small |
| LOCATION | 0-1 | Optional, gates the best reward |
| VAULT | 1 | Required. Gates progression or the primary objective. |
| REGION | 1 per vault + 1 regional | Regional boss ties locations together |

---

## LAYOUT TOPOLOGY

**Vaults should not be hallways. The player should face route choices with consequences.**

### Layout Patterns

| Pattern | Structure | Player Experience |
|---------|-----------|-------------------|
| **Linear** | A → B → C → D | Predictable, low replay. Only acceptable for very small vaults (3-4 rooms). |
| **Branching** | A → B or C, each leads deeper | Choice. "Do we go left or right?" Each branch has different risks/rewards. |
| **Loop** | A → B → C → A (with shortcut) | Efficiency reward. Players who explore find shortcuts back. Retreat is viable. |
| **Hub** | Central room with 3-4 spokes | Non-linear. Players choose their order. Hub becomes base camp. |
| **Layered** | Multiple paths to the same depth | Route choice with trade-offs. The easy path has less loot. The hard path has traps but better rewards. |

### Layout Principles

- **Minimum 2 routes to the objective** for any VAULT scale. One obvious, one hidden or harder.
- **Loops allow retreat.** If the party can't backtrack safely, they're trapped. Loops let them circle back to resupply, rest, or change approach.
- **Gated branches.** Some paths require a key, a skill, or a sacrifice to access. The gate tells the player: "there's something here worth protecting."
- **The map should reward mapping.** If the layout is a straight line, there's nothing to map. Branching and loops make the player's spatial awareness matter.
- **Verticality.** Multiple floors connected by stairs, shafts, collapses, or elevators. "Going down" should feel like commitment.

---

## ATTRITION CURVE

**A vault should gradually tax resources across its depth. The party enters strong and exits tested.**

### Resource Pressure by Depth

| Depth | Pressure Level | What's Taxed | How |
|-------|---------------|--------------|-----|
| **Entry (rooms 1-2)** | Low | Attention | Environmental storytelling, ambient creatures. No resource cost. Establishes tone. |
| **Outer (rooms 3-5)** | Moderate | HP, consumables | First combat, first trap, first obstacle. Party spends something. |
| **Mid (rooms 5-8)** | High | Inventory, light, special abilities | Harder encounters, resource decisions. "Do we use the last torch here or save it?" |
| **Deep (rooms 8+)** | Critical | Everything | Boss territory. Party is working with what they have left. Rest is risky (encounter checks). |

### Attrition Principles

- **Light is a resource.** Below a certain depth, darkness is the default. Light sources have duration. A bioluminescent character's glow is free but paints a target. Torches run out. Glowstones dim.
- **Inventory fills up.** Loot competes with supplies. The party must choose: carry the exotica or carry the healing kit? This tension should peak at the extraction phase.
- **HP attrition, not HP spikes.** Multiple small costs (d4 trap, d6 hazard, d4 creature) are better than one big hit. The party should feel themselves getting worn down, not ambushed into death.
- **Encounter checks get worse with depth.** The encounter table can shift at depth — surface encounters are scavengers, deep encounters are predators.
- **Rest is a choice, not a given.** Short rests in a vault cost a turn — which means an encounter check. The party trades time for HP. That's a real decision.

---

## FACTION ECOLOGY

**The best vaults have multiple groups with competing interests. The party has leverage.**

### Faction Template

For each faction present in a VAULT:

- **Who are they?** Species, type, numbers.
- **What do they want?** Territory, food, an object, escape, worship.
- **Who do they conflict with?** The other factions in the vault.
- **How do they react to the party?** Hostile, wary, curious, transactional.
- **What can the party offer them?** Food, violence against their enemy, passage, an object.
- **What can they offer the party?** Safe passage, information, access, alliance in combat.

### Faction Placement by Scale

| Scale | Factions | Notes |
|-------|----------|-------|
| AREA | 1 | Just inhabitants |
| LOCATION | 1-2 | At least one can be negotiated with |
| VAULT | 2-3 | Competing interests. Party can ally with one against another. |
| REGION | 3-5 | Political landscape |

### Faction Interaction Principles

- **Factions act independently of the party.** They're already in conflict when the party arrives. The party enters a situation in motion.
- **Helping one faction costs another's goodwill.** Feeding the Grey Crickets might anger the creature that hunts them. Clearing the Grimweaver might let the crickets expand into new territory.
- **Information is currency.** Factions know things about the vault that the party doesn't. A faction encounter is a potential intel source — if the party can communicate and negotiate.
- **Not every faction is combat-capable.** Scavengers, refugees, degraded AIs, trapped scholars — these factions offer social encounters inside a combat environment.

---

## INTERIOR NPC GUIDELINES

**Every VAULT should have at least one social encounter opportunity inside the dungeon.**

### Interior NPC Sources

| d6 | NPC Type | Example |
|----|----------|---------|
| 1 | **Degraded AI** | Still running original programming, confused about the era, can provide information if the party answers its queries |
| 2 | **Trapped scavenger** | Got in but can't get out. Knows part of the layout. Will trade info for rescue. |
| 3 | **Creature with personality** | A newbeast, a synth, something that can communicate. Lives here. Not hostile by default. |
| 4 | **Rival explorer** | Arrived before the party. Injured, hiding, or has claimed territory. Competing for the same objective — or a different one. |
| 5 | **Guardian** | Loyal to the vault's original purpose. Will test the party's intentions before allowing access. |
| 6 | **Prisoner** | Held by the dominant creature or trapped by the environment. Rescue is optional and costs resources. |

### Interior NPC Principles

- **They know something the party doesn't.** The NPC's value is informational — layout, hazards, creature behavior, a secret's location.
- **They want something.** Rescue, food, companionship, an object, revenge. The party can help or refuse.
- **They complicate the plan.** An NPC adds a variable. Escorting a wounded scavenger slows the party. A guardian's test costs time. A rival forces negotiation.
- **They are not quest givers.** Interior NPCs are people in a situation, not vendors dispensing objectives.

---

## TRADE-OFF DESIGN

**The best vaults force choices where gaining one thing costs another.**

### Trade-Off Types

| Type | Mechanism | Example |
|------|-----------|---------|
| **Inventory** | More loot than you can carry | 40 slots of salvage, 30 slots of capacity. What stays? |
| **Route** | Mutually exclusive paths | Left corridor has the weapons cache. Right has the medical supplies. Both collapse behind you. |
| **Time** | Thoroughness vs speed | Every room searched is another encounter check. Rushing means missed loot. |
| **Resource** | Spend to progress | Power the door by draining your last fuel cell. Open the lock by sacrificing an exotica. |
| **Alliance** | Helping one faction angers another | The scavengers will guide you to the vault — but the guardian considers them thieves. |
| **Information** | Knowledge has a price | The AI will tell you the layout — if you delete its archived memories of the original inhabitants. |
| **Moral** | Right thing costs | The trapped NPC slows your extraction. The seedling takes 6 slots you need for salvage. Leaving them is easier. |

### Trade-Off Principles

- **No obvious answer.** If one option is clearly better, it's not a trade-off. Both sides should cost something real.
- **The player decides, not the dice.** Trade-offs are choices, not checks. The player weighs priorities and commits.
- **Consequences persist.** What you left behind stays left. What you sacrificed doesn't come back. The choice matters because it's permanent.
- **At least one hard trade-off per vault.** The party should leave a vault having gained something and lost something — even if what they lost was just the option they didn't take.

---

## MCP TOOL INTEGRATION

### ENGINE GENERATOR CONTRACT

**Governing rule: the skill rolls flavor and structure; the ENGINE mints every mechanical artifact.** When a generated location, NPC, or hoard needs a concrete game object — a poison, a Mystic Gift, a drug, an elixir, a codex, a weapon, a named NPC — DO NOT invent its stats in prose. Call the engine generator below and emit the exact tool call (a `⚙` push line) so the next Claude (or the DM mid-play) can mint it deterministically. The engine owns the book tables, the dice, and the persistence; the skill owns the *why it's here* and the *what it's tied to*.

This is the same discipline the engine itself follows (PUSH the exact next tool-call, don't rely on the reader PULLing it from a tool menu). A prep file or on-the-fly description that says "a vial of viridian poison" is incomplete — it should carry `⚙ generate(action="poison")` so the real row gets rolled.

| Skill needs… | Engine call | Status |
|---|---|---|
| Named NPC (any significant inhabitant) | `generate(action="npc")` | **live** |
| Creature stats (MANDATORY before any combat) | `lookup(action="creature", query="name")` | **live** |
| Exotica seed (4d100) / themed item | `generate(action="exotica")`, `roll(action="exotica")` | **live** |
| Search existing exotica by theme | `lookup(action="exotica", query="keyword")` | **live** |
| Weapon / body armour | `generate(action="weapon")` / `generate(action="armour")` | **live** |
| Random encounter (vault/travel) | `roll(action="encounter")` | **live** |
| **Poison** (vial, coated blade, trap, toxic creature loot) | `generate(action="poison")` → apply via `affliction(kind="toxin", action="poison_apply"/"poison_coat")` | **live** (B2) |
| **Mystic Gift** (obelisk, psychic NPC, locus reward) | `generate(action="gift")` → persist via `gift(action="add")` | **live** (G1) |
| **Drug** (cache, dealer, ingestible loot) | `generate(action="drug")` → apply the high via `affliction(kind="condition", action="apply")` | **live** (B4) |
| **Hypergeometric codex** (equation loot, science-mystic's hoard) | `generate(action="codex")` → claim via `codex(action="add")` | **live** (G2) |
| **Elixir** (alchemist, apothecary, brewed treasure) | `generate(action="elixir")` → drink via `character(action="drink_elixir")` | **live** (B3) |
| **Crucible / alchemy rules** (alchemist's lab, recipe questions) | `generate(action="crucible")`, `lookup(action="alchemy")` | **live** (B5) |
| **Story seed** (backstory, rumour, NPC motive, room contents — when stuck) | `generate(action="story_seed")` (4d100 WHO/WHAT/WITH/WHY) → crystallize via `thread`/`antagonist`/`character` | **live** |
| **Minor faction** (a group inhabiting or contesting the location — reputation, type, goal, leader, assets, rival) | `generate(action="faction")` → persist via `faction(action="add")` | **live** |
| Dice rolls | MCP dice tools | **live** — never mentally randomize |

**Status legend:** *live* = call it today. Every generator in this table is now live on `main` (B3/B4/G2/B5 all merged 2026-07-02). If any call ever errors as unknown, fall back to describing the item in prose and flag it for the DM.

**The reinvention smell test:** if you are about to write the mechanical effect of a poison, gift, drug, elixir, or codex *in prose inside a prep file*, stop — that is the engine's job. Roll its flavor/placement and emit the `⚙` call instead. Settlements, locations, vaults, regions, monsters-as-inhabitants, and their *soul* (etiology, stakes, hooks) ARE the skill's job — generate those here.

### REFERENCE TABLES INDEX

The book's random-generation tables live in `references/`. Roll these to seed content, then shape with the design frameworks below. (Engine artifacts in any table → emit the `⚙` call, don't stat in prose.)

| File | Covers |
|---|---|
| `SETTLEMENTS.md` | Government, values, despises, lacks, assets, problems, changes (return roll), Hegemony Protectorate, Oracle's Sanctum |
| `LOCATIONS.md` | Location-type d20 + ~16 sub-generators (anomaly, archive, arcology, bandit/bounty/Faa camps, grave, holy place, oasis, ruin, science-mystic, trade post, wreck) + route hazards + **pre-authored keyed sites** (Nassak, Fount, Eigin Oasis, Caeba in the Maw — fetch via `rulebook`, don't re-roll) |
| `VAULTS.md` | Vault-creation procedure (node clusters), entrance/tunnel/function, treasure/lair/hazard/special/fauna tables, vault merchants |
| `MONSTERS.md` | Build an original creature: Level/HP, Type, AV, Morale, number, attacks, psychic powers, form, hue/texture/behaviour/habitat |
| `REGIONS.md` | Drop-dice region method, Regional Feature d20, Place Names, Anomaly d20 |
| `MISCELLANY.md` | Books, petty gods, trade caravans, fine clothing, fine dining, rival adventurers (+ gear by role) |
| `TABLES_D100.md` | Monster Lair d100, Landmarks d100 |
| `FACTIONS.md` | The major faction write-ups |
| `TRAVEL.md` / `WEATHER.md` | Travel and weather reference (weather is also engine-run) |

Prefer `lookup(action="creature")` / engine generators over rolling a flavor table when a real mechanical object is needed.

### For Prep Files

| Scale | Registration Tool | State Tracking |
|-------|-------------------|----------------|
| VAULT | `map(action="init", map_name="name", prep_file="FILE.md")` | Use map() exploration actions |
| LOCATION | `map(action="init", map_name="name", prep_file="PREP.md")` | Use map() actions |
| REGION | `geography(action="add_location", ...)` | Use geography() actions |
| HEXPEDITION | Multiple geography() + map() registrations | Full integration |

### Context Integration

When generating content that will be used during play:

1. **Check canon first:** Call `check_canon()` with location name
2. **Respect knowledge scope:** Mark secrets as `dm_only`
3. **Use character data:** Check `characters/*.json` (per-character files) for party abilities
4. **Track in geography:** Add to `VAARN_GEOGRAPHY.json` if overworld

---

## PARLEY AUTHORING

Same discipline as the ENGINE GENERATOR CONTRACT above, applied to negotiations instead of items: the skill authors the ladder, the NPCs, and the stakes; the engine mints and tracks the mechanical state. Any social or diplomatic prep MUST carry a machine-readable `## PARLEY:` block wherever it applies (see rule 1 below) so `parley()` can parse it instead of the DM re-deriving DCs from prose mid-scene.

```markdown
## PARLEY: <slug>

**Stakes:** one line — what each side wants.
**Failure state:** one line — what "combat/walk-away" means here (combat stays gated behind an explicit, observable trigger condition, not an ambient mood shift).

### TIERS
1. contact — party states purpose; no hostility
2. assessment — the other side tests the party | check: EGO DC 15
3. exchange — offers on the table
4. trust — private access granted
5. accord — terms sealed

### PARTIES
#### NPC: She-Who-Keeps
**Needle:** wary            <!-- hostile | wary | neutral | warm | allied -->
**Lever:** the cubs' future — offers protecting it move her most
**Pressure:** sways toward accord if security is credible; toward failure if humiliated before her hunters
**Victory:** stands down the warband; grants archive terms

### REVEALS
- matriarch_true_name | gate: tier>=trust OR EGO DC 18
- secondary_cache | gate: tier>=accord

### TEXTURE (d8)                <!-- optional; replaces the generic liveness result in social scenes -->
| 1 | Wall-weather shift … |
...
```

Rules:
1. Any social/diplomatic LOCATION- or ARC-scale prep MUST carry a `## PARLEY:` block.
2. DCs and gates live ONLY in the block — prose refers to them by name (one fact, one home). Never restate a DC or a gate condition inline in the victory-path narrative; point back to the tier or reveal label instead.
3. End the block's authoring with the pushed opener: `⚙ parley(action="open", slug="<slug>", prep="<file>")`.

---

## PREP FILE FORMAT

### Header Block

**REQUIRED for any prep that registers a map (calls `map(action="init")`) — vaults, dungeons, explorable locations: the literal FIRST line of the file MUST be the machine-readable vault-liveness header shown below. It arms the deterministic vault-liveness gate whenever the prep is the Active Prep, and `validate_prep_file` REJECTS a map-registering prep that lacks it. `map=<slug>` MUST match the `map_name` you register with `map(action="init")`. Non-dungeon preps (settlement / region / event / social) must NOT carry it.**

```markdown
<!-- DUNGEON: map=<map_slug> enforce=vault-liveness -->   ← FIRST LINE — vault/dungeon only; omit for non-dungeon preps
<!-- SITE: key=<map_slug> scene=vault_exploration aliases="Canonical Name|Short Form|the place" -->   ← SITE preps only (any turn-tracked place); see "SITE Marker" below
# LOCATION_NAME - PREP

**Type:** [vault/settlement/lair/holy_place/etc]
**Scale:** [area/location/vault/region]
**Knowledge Scope:** dm_only
**Created:** [date]
**Status:** PREPARED

---

## FOR NEW CLAUDE (READ FIRST)

This is a prepared location for the Rubicon Seven campaign.
Before running this content:
1. Call `check_canon("location_name")`
2. Call `map(action="init", map_name="this_file", prep_file="THIS_FILE.md")` to build the walkable map
3. Review DM ONLY sections — never reveal to player
4. Check current party composition

---
```

### SITE Marker (turn-tracked places — REQUIRED on every site prep)

**A *site* is any place where exploration turns run: vaults, ruins, camps, lairs, holdfasts, and explorable settlements. Every site prep MUST carry a `<!-- SITE: ... -->` marker so the engine can deterministically recognise the place from the player's own words and resume its turn-clock on return — without the DM having to remember to enter site mode. NON-site preps (a dinner, a council, a one-scene social/political event with no exploration turns) must NOT carry it.**

Placement:
- **Walkable vault/dungeon:** the `<!-- DUNGEON: ... -->` line stays the literal FIRST line; the `<!-- SITE: ... -->` line goes immediately below it.
- **Ambient site (ruin/camp/settlement, no walkable room map):** there is no `DUNGEON` line, so the `<!-- SITE: ... -->` line is the FIRST line.

Fields (single line, space-separated `key=value`; do NOT reformat across lines):
- `key=<slug>` — the site key. MUST equal the value `_PREP.md` derives from the filename (e.g. `KALAXIS_PREP.md` → `kalaxis`) and, for a walkable vault, MUST match `map=<slug>` on the DUNGEON line.
- `scene=<type>` — the scene type the engine sets on entry. Use `vault_exploration` for vaults, ruins, camps, lairs, and any turn-clocked exploration site. Use **`scene=settlement`** for settlements — this marks the site non-hostile (no turn clock) AND triggers the engine's who's-around roster on arrival, showing where each NPC is when the party enters.
- `aliases="A|B|C"` — pipe-delimited watch-names the engine scans the player's text for. Include the canonical name plus the natural short forms a player would actually type. Quote the whole value; separate with `|`.

Alias authoring rules:
- Include: the full name, the common short name, and one or two natural "the …" phrasings. E.g. `aliases="Kalaxis|Kalaxis Arcology|the arcology"`, `aliases="The Verdigris Hold|the hold|that green fortress"`.
- Avoid bare generic words that would false-fire across unrelated scenes (`the vault`, `the ruin`, `the place`, a lone `the camp`). Make each alias specific enough that, if the player types it, they almost certainly mean THIS site.
- 2–5 aliases is the sweet spot. More than that usually means some are too generic.

### DM Knowledge Section
```markdown
## DM ONLY — THE TRUTH

**Do not reveal this information to the player until discovered.**

### Etiology
[Why this place exists, who built it, original purpose]

### History
[What happened here across time — the layers]

### Current Stakes
[What clock is ticking, what pressure exists]

### Ancient Intelligence (if any)
[AI presence, disposition, goals]

### Secrets
Each secret must be earned through play:

- **SECRET: secret_id** (hidden)
  - **Truth:** [What is actually true]
  - **Discovery:** [How party can learn this]
  - **Effect:** [What changes when revealed]

### Character Hooks (DM Reference)
[Why specific PCs might care — use to seed hints]

---
```

### Party-Observable Section
```markdown
## OBSERVABLE OVERVIEW

[What the party perceives on approach/entry. Sensory details only.
No DM knowledge leaks. This is what you can describe freely.]

---
```

### Room/Area Format
```markdown
## ROOM: room_id
<!-- room_id MUST be \w+ (letters/digits/underscore only — NO spaces, hyphens, or parentheses).
     Heading MUST be h2 (## ROOM:). The block runs until the next ## heading. -->

**Floor:** [number]
**Coords:** [x,y for map system]
**Name:** [Display name]
**Connections:** [direction→room_id, ...]   (separator → or ->; use @N for cross-floor, e.g. up→vestibule@2)
**Secrets:** [secret_id→target (discovery condition)]
**Entrance:** true   (mark exactly ONE room as the entry point; omit on all others)

### First Glance
[2-3 sensory impressions on entry — what registers in the first three seconds.
No mechanics, no lists. map(enter) serves ONLY this; deeper detail waits for
the player to look. If omitted, the first paragraph of Observables is used.]

### Observables
[Full detail the party can find by looking closer — served by
map(action="look"). Freely describable once queried.]

### Obstacles
- **obstacle_id:** [Description]
  - **Planned Solution:** [Expected approach]
  - **Alternative Solutions:** [Other valid approaches]

### NPCs Present
[Names and observable behavior — motivations in DM ONLY section]

### Loot
[What's here and where]

### DM Notes
[Reminders for running this room]

---
```

### Encounter Format
```markdown
## ENCOUNTERS

### Random Encounter Table (use roll(action="encounter") or below)
| d6 | Encounter |
|----|-----------|
| 1 | [description] |
...

### Set Encounters
Specific encounters that should happen:
- **Trigger:** [Condition]
- **Encounter:** [What happens]

---
```

---

## SPOILER PROTOCOL

### The Iron Rule
**Never narrate DM-only content until party has discovered it through play.**

### Knowledge Scope Labels
- `party_known` — Can be described freely
- `dm_only` — Must be earned through investigation, rolls, or NPC interaction
- `hidden` — Secret that requires specific discovery condition

### When Revealing Secrets
1. Party meets discovery condition
2. Call `map(action="reveal_secret", map_name="vault_name", room_id="room_id", secret_id="secret_id")`
3. Update prep file if permanent change
4. THEN narrate the revelation

### Reveal Pacing & the Revealed Ledger
Discovery tracking is ENGINE state, not markdown — do not author hand-maintained
"REVEALED LEDGER" sections in new preps. When the party learns a DM-only fact
socially or by deduction (an NPC tells them, they piece it together), ledger it
the moment it lands: `map(action="reveal", map_name="vault_name", fact="...")`.
NPCs may assert only ledgered facts; off-ledger they speculate and may be wrong;
unledgered secret names are unspeakable (validate_prose enforces this). Pacing:
map(enter) serves only the First Glance layer — render ONE finding per beat and
let the player's questions pull the rest via map(action="look").

### Red Flags (Never Do These)
- Describing what's behind a locked door before it's opened
- Revealing NPC motivations before interaction
- Explaining the "truth" of a mystery before investigation
- Giving away monster presence before omens

---

## WORKFLOW CHECKLISTS

### Single Location (On-the-Fly)
- [ ] Roll location type (d20)
- [ ] Roll on appropriate sub-tables
- [ ] Generate 1-2 NPCs with `generate(action="npc")`
- [ ] Roll dominant creature via `roll(action="location", location_type="monster_lair")` (d100 Monster Lair)
- [ ] Look up creature stats with `lookup(action="creature", query="name")`
- [ ] Describe observables only
- [ ] Note for later prep if significant

### Single Location (Prep)
- [ ] Roll location type and sub-tables
- [ ] Apply soul generation framework
- [ ] Generate all NPCs with `generate(action="npc")`
- [ ] **Roll monsters:** Dominant + secondary via `roll(action="location", location_type="monster_lair")` (d100 Monster Lair)
- [ ] **Look up all creature stats** with `lookup(action="creature", query="name")`
- [ ] **Build encounter table** (d8, themed to location)
- [ ] **Generate exotica** with `roll(action="exotica")` (1-2 items)
- [ ] Place loot logically throughout location
- [ ] Write prep file with DM sections
- [ ] **MANDATORY:** Register overworld presence — geography(action="add_location", ..., known per type)
- [ ] **MANDATORY:** Emit canonical `## ROOM:` markers so the prep is walkable via map(action="init")
- [ ] **MANDATORY:** Every `## ROOM:` block declares `**Floor:**`, `**Coords:**`, and `**Connections:**` — the
  engine's fog-of-war player map places and links rooms from these fields (`validate_prep_file` warns if any is missing).
  Rooms without `**Coords:**` all default to [5,5] and overlap on the grid — lay out coords roughly matching the
  site's geography, one unique cell per room per floor.
- [ ] Run geography(action="validate_consistency") — confirm no collisions/dangling routes

**If this is a SETTLEMENT prep, two additional requirements apply:**
- [ ] **FIRST LINE of the file:** `<!-- SITE: key=<slug> scene=settlement aliases="Full Name|Short Name|the Name" -->` — this is what makes the engine open with the who's-around roster on arrival; `scene=settlement` marks it non-hostile (no turn clock). No `DUNGEON` line on a settlement (settlements are not walkable vaults).
- [ ] **Every NPC block under `## NPCs` MUST carry `**Location:** <room_id>`** naming a room id from the settlement's `## KEY LOCATIONS` section (time-of-day nuance allowed, e.g. `ledge_house (days), exchange (evenings)`). The engine's who's-around reader keys on this field — an NPC block without it is invisible to the roster.

### Vault/Dungeon (Prep)
- [ ] **FIRST LINE of the file:** `<!-- DUNGEON: map=<slug> enforce=vault-liveness -->` (REQUIRED — arms the vault-liveness gate; `map=<slug>` MUST match the `map_name` you register; `validate_prep_file` rejects a map-registering vault prep without it)
- [ ] **SECOND LINE of the file:** `<!-- SITE: key=<slug> scene=vault_exploration aliases="…|…" -->` (REQUIRED on every site prep — lets the engine recognise the place from the player's words and resume its turn-clock; see "SITE Marker" rules. Ambient ruins/camps with no `DUNGEON` line put this on the FIRST line.)
- [ ] Determine purpose and history (etiology)
- [ ] **Design layout topology** (branching, loop, or hub — NOT linear). Minimum 2 routes to objective.
- [ ] Design room structure (8-20 rooms)
- [ ] Apply soul to each area
- [ ] **Design attrition curve** — map resource pressure across depth (low → moderate → high → critical)
- [ ] Generate all NPCs with `generate(action="npc")` — include at least 1 interior NPC (social encounter)
- [ ] **Roll monsters:** 1-2 dominant + 2-3 secondary creatures via `roll(action="location", location_type="monster_lair")` (USE THE ROLL — do not browse)
- [ ] **Look up all creature stats** with `lookup(action="creature", query="name")`
- [ ] **Design boss encounter** — climactic fight/confrontation gating objective. Lair actions, foreshadowing, multiple capabilities tested.
- [ ] **Build encounter table** (d8, with variety per creature). Table shifts at depth.
- [ ] **Design 2-3 factions** with competing interests. At least 1 non-hostile.
- [ ] **Design 1-2 puzzles** — at least 1 gates progression, 1 gates bonus loot. Multiple solution paths.
- [ ] **Place 2-4 traps** — telegraphed, scaled by depth. At least 1 interacts with creatures.
- [ ] **Generate exotica** with `roll(action="exotica")` (2-4 items)
- [ ] Place loot in specific rooms (trade goods, consumables)
- [ ] **Design at least 1 hard trade-off** — inventory, route, moral, or alliance. No obvious answer.
- [ ] Place secrets and obstacles
- [ ] Write prep file with DM sections
- [ ] Register with vault system

### Region (Prep)
- [ ] Drop dice method (5-6 locations)
- [ ] Determine location types
- [ ] Roll regional terrain
- [ ] Connect with travel routes
- [ ] Determine route hazards
- [ ] Apply soul to each location
- [ ] **Roll regional creatures:** 2-3 dominant + 3-5 secondary
- [ ] **Look up all creature stats** with `lookup(action="creature", query="name")`
- [ ] **Build regional encounter table** (d12 or d20)
- [ ] **Generate exotica per location** with `roll(action="exotica")`
- [ ] Add all to geography system
- [ ] Create regional overview document

### Hexpedition (Prep)
- [ ] Define expedition scope (regions, goals)
- [ ] Generate all regions (use Region checklist for each)
- [ ] Create overworld connections
- [ ] Build weather tracking
- [ ] Create foraging tables
- [ ] **Build master encounter table** per terrain type
- [ ] **Compile creature stats** for all regions
- [ ] **Generate notable exotica** for key locations
- [ ] Register everything in geography
- [ ] Create expedition overview document

---

## INTEGRATION WITH EXISTING SYSTEMS

### With check_canon()
Before generating content for established locations:
```
check_canon("location_name or keywords")
```
Respect existing lorebook entries and relationships.

### With the map tool (consolidated)
For walkable vaults/locations — one tool, all actions:
```
map(action="init", map_name="vault_name", prep_file="VAULT_NAME.md", map_type="vault")
map(action="enter", map_name="vault_name", room_id="room_id")
map(action="search", map_name="vault_name", room_id="room_id")
map(action="render", map_name="vault_name")
map(action="reveal_secret", map_name="vault_name", room_id="room_id", secret_id="secret_id")
map(action="query_nearby", map_name="vault_name", room_id="room_id")
```
(For a room's DM-only detail, use `map(action="get_room", map_name=..., room_id=...)` — it returns the referee view.)

### With the geography tool (consolidated)
For overworld registration (MANDATORY for any location with overworld presence):
```
geography(action="add_location", name="Name", x=X, y=Y, location_type="type",
          region="region", module="MODULE.md", explored=False,
          known=<see knowledge rule below>, description="...")
geography(action="add_route", from_loc="from", to_loc="to", days_foot=N,
          days_ornithopter=M, hazard_level="moderate", notes="...")
geography(action="render_map", center="ceruline", radius=6)
geography(action="validate_consistency")   # run after adding — catch collisions/dangling routes
```

**Knowledge flag (`known`) — set by type (Phase 3 fog-of-war):**
- MACRO types → `known=True`: landmark, terrain, anomaly, arcology, crossroads, arcology_ruin, arcology_coastal.
- SPECIFIC types → `known=False` (fogged until visited): vault, camp, oracle, ruin, settlement, cave_system.
- Any location the party has already visited → also `explored=True` (which implies known).

---

# REFERENCE TABLES

All tables needed for generation, consolidated below.

---

## LOCATIONS — delegate to the engine

Locations are generated from the **certified Crimson Hound tables**. Don't roll them from a
table here — call the engine, then write the place.

- **A random location** -> `roll(action="location")` — rolls the certified d20 location-type
  table (Ruin, Settlement, Oasis, Vault, Lair, Holy Place, Arcology, Grave, Cacklemaw Den,
  Wreck, Faa Nomad Camp, Bandit Camp, Oracle's Sanctum, Science Mystic's Abode, Hegemony
  Outpost, Fortress, Trade Post, Archive, Bounty Hunter's Camp, Anomaly) then its sub-generator.
- **A specific type** -> `roll(action="location", location_type="<type>")` — e.g. `anomaly`,
  `arcology`, `cacklemaw_den`, `fortress`, `hegemony_outpost`, `science_mystic`, `wreck`,
  `oasis`, `ruin`, `bandit_camp`, `bounty_hunter`, `faa_camp`, `grave`, `holy_place`, `trade_post`.
- A **Settlement** result routes to the settlement generator (see `references/SETTLEMENTS.md`).

See `references/LOCATIONS.md` + `references/VAULTS.md`. Light generative surface — the sub-table
gives you the bones (who's here, what they want, the weird detail); you make it a place.

## SETTLEMENTS — delegate to the engine

Settlements use the certified Crimson Hound tables. Don't roll them from a table here.

- **A settlement** -> `roll(action="settlement")` — government (adjective + form, with faith
  rolled separately), values (praises / despises / lacks), a defining asset, and a current
  problem — all book-faithful.
- **Changes on return** -> the certified `settlement_change` table (the engine carries it);
  surface a change as a hook.
- **Hegemony Protectorate** -> `roll(action="location", location_type="hegemony_protectorate")`
- **Oracle's Sanctum** -> `roll(action="location", location_type="oracle_sanctum")`

See `references/SETTLEMENTS.md`. Light generative surface — roll, then write the place; don't simulate it.

## MONSTER LAIR & LANDMARKS — delegate to the engine

Certified d100 tables; don't roll them from a table here.

- **Monster lair** (d100 — who lairs here, where, the omen) -> `roll(action="location", location_type="monster_lair")`
- **Landmark** (d100 — a striking feature on the horizon) -> `roll(action="landmark")`

See `references/TABLES_D100.md`.

## ENVIRONMENT & TRAVEL — delegate to the engine (do NOT roll these from a table here)

These are Crimson Hound book systems the engine owns with certified data. Call the tool;
weave the result into fiction. (Light generative surfaces — flavor + consequence, not a
survival sim.)

- **Weather** → `roll(action="weather")` — the real d6 hex-chart drift over the 8 canonical
  conditions (Still/Hazy/Dust Storm/Sand Storm/Heatwave/Worm-pollen/Rain/Prismatic Tempest),
  with continuity tracked across days. (No "psychic weather" — that was fabricated.) See `references/WEATHER.md`.
- **Foraging** → `supply(action="forage")` — the certified **d100 Desert Foraging** table.
  (Not a d30.)
- **Route hazards / travel** → the region's certified **d20** route-hazard column (via region
  generation / the `rulebook` tool). Travel itself is **days-only and unmapped** (NPC-estimated
  days; halve with a vehicle; close=d6 / moderate=2d6 / far=3d6). No hex grid, no navigation DCs.
  See `references/TRAVEL.md`.

---

**Remember:** The tables are tools. The soul is what makes it matter. Every location is someone's story.

---

## NARRATIVE DESIGN INTEGRATION (Post-Generation Gate)

**Arc content:** Auto-trigger `/dm-design` after generation. The quality gate is mandatory for arc-connected locations — these intersect with campaign canon, established NPCs, and active threads. Contradictions in arc content break immersion.

**Discovery content:** The quality gate is OPTIONAL. Offer it:

> "Run narrative design integration? (Recommended only if this connects to an active arc.)"

If the player accepts, invoke `/dm-design integrate [generated content name]`. If the player declines, skip — discovery content lives on its own terms.

For either track, the dm-design subagent verifies against lorebook, campaign history, geography, and existing prep. It fixes contradictions directly and returns "Done." or "Incomplete — [reason]."
