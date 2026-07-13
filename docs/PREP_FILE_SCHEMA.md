# Prep File Schema

A **prep file** is a Markdown document that describes a location the party can visit — a
vault, a ruin, a settlement, an explorable site. The engine *parses* prep files into
structured data (rooms, secrets, constraints, encounters) so the DM-model can run the
place without re-reading the whole file every turn, and so the walkable-map and
vault-liveness systems can track movement and trigger events.

This document specifies the format. **The parser and validator are the authority** — a
prep file is "valid" when `validate_prep_file` says so. The relevant code:

- Parser: `server.py` → `_load_prep_file()` (server.py:1878)
- Validator: `server.py` → `_validate_prep_schema()` (server.py:2459) and the
  `validate_prep_file` MCP tool (server.py:2641)
- Site / vault markers: `site_markers.py` → `parse_site_marker()` (the `<!-- SITE: -->`
  and `<!-- DUNGEON: -->` comment markers)
- Settlement rules: `settlement_system.py` → `is_settlement_prep()`,
  `npcs_missing_location()`

**Naming convention:** prep files are named `<PLACE>_PREP.md` (e.g. `OLD_CISTERN_PREP.md`)
and live in the campaign directory. The engine derives a map slug from the filename by
stripping `_PREP.md` and lowercasing (`OLD_CISTERN_PREP.md` → `old_cistern`); see
`site_markers.derive_key_from_prep()`.

---

## How the parser sees a file

The parser is **regex-driven and section-based**, not a strict Markdown parser. It scans
the whole file for a small set of *exact* heading patterns and field markers. Everything
between recognized sections is treated as free prose (DM-readable, never parsed). This
means:

- Section markers are **case-sensitive** and must match exactly (`## ROOM:`, `### SECRET:`).
- Field markers are **bold-label** lines: `**Name:**`, `**Floor:**`, etc.
- IDs (after `ROOM:` / `SECRET:` / `CONSTRAINT:`) must be a single `\w+` token —
  snake_case, no spaces.
- Prose you don't mark up is invisible to the engine; that's intentional. Use it freely.

---

## Required vs optional

| Element | Status | Enforced by |
|---|---|---|
| At least one `## ROOM:` block | **REQUIRED** (critical error if missing) | `_validate_prep_schema`, server.py:2476 |
| `**Type:**` header field | Recommended (warning if missing) | server.py:2471 |
| Per-room `**Name:**`, `**Floor:**`, `**Connections:**` | Recommended (warning each) | server.py:2480–2485 |
| `**Reveal Condition:**` on each secret | Recommended (warning) | server.py:2496 |
| `<!-- DUNGEON: map=<slug> enforce=vault-liveness -->` header | **REQUIRED *if* the file contains a `map(action="init"...)` call** | server.py:2664 |
| `<!-- SITE: key=<slug> ... -->` marker | Recommended for any runnable site; **key must equal the DUNGEON slug** if both present | server.py:2683 |
| `**Location:**` on every NPC | **REQUIRED for settlement preps** (`scene=settlement`) | server.py:2702, `settlement_system.npcs_missing_location` |

"Critical errors" block `map(action="init")`; "warnings" are advisory and do not block.

---

## Heading & marker reference

### Comment markers (first lines of the file)

```
<!-- DUNGEON: map=old_cistern enforce=vault-liveness -->
<!-- SITE: key=old_cistern scene=vault_exploration aliases="Old Cistern|the cistern" -->
```

- **`<!-- DUNGEON: ... -->`** — registers the file with the vault-liveness gate (turn
  tracking, encounter rolls, walkable-map enforcement). Required whenever the prep itself
  invokes `map(action="init")`. `map=` is the slug; it should match the filename-derived
  slug unless the prep deliberately maps to a different name.
- **`<!-- SITE: ... -->`** — lets the engine recognize the place from the player's words.
  Fields: `key` (the slug; **must equal the DUNGEON `map=` slug** when both are present),
  `scene` (`vault_exploration`, `settlement`, etc.), and `aliases` (a `|`-separated list
  of names the player might type). A site marker without aliases produces a warning — the
  detector then falls back to the filename only.

### Header block

A `**Type:**` line near the top classifies the place (free text — e.g.
`Vault`, `Settlement (Oasis Waypoint)`, `Ruin`). Only `**Type:**` is parsed into
metadata; other header lines (`**Scale:**`, `**Status:**`, `**Created:**`, etc.) are
conventional but unparsed prose.

### `### SECRET: <id>`

A piece of hidden truth and the condition under which it surfaces. Parsed fields:

- `**Scope:**` — `dm_only` (default if omitted) or `party_known`.
- `**Truth:**` — what is actually true.
- `**Reveal Condition:**` — what causes it to surface (warning if missing).

Additional bold lines (`**Party Believes:**`, `**Reveal Consequences:**`) are conventional
DM prose and not parsed.

### `### CONSTRAINT: <id>`

A standing limitation on a subject. Parsed fields:

- `**Subject:**` — who/what is constrained.
- `**Limitation:**` — what they cannot do.
- `**Scope:**` — `party_known` (default if omitted) or `dm_only`.

### `## ROOM: <id>`

One traversable location. Parsed fields:

- `**Name:**` — display name.
- `**Floor:**` — integer floor number.
- `**Connections:**` — exits, e.g. `north→processing_hall, up→archive@2`. The
  `<dir>→<room_id>` arrows are how the walkable map links rooms; the `@N` suffix denotes a
  floor change.
- `**Obstacles:**` — a sub-list; each obstacle should be paired with a
  `**Planned Solution:**` (warning if not).
- `**Secrets Present:**` — which secret IDs are discoverable here.

All other prose under a ROOM (the description, `**DM Note:**`, `**Loot:**`, etc.) is
free text for the DM.

### `## ENCOUNTERS`

Optional. Two formats are auto-detected:

- **Turn-based** (vaults): lines like `- **Turn 3:** A patrol arrives.`
- **Random table** (overworld/settlements): a Markdown table whose first column is the
  roll value, e.g. `| 1 | Pack of scavengers | flee from fire |`. The dice size is read
  from a `| dN |` header if present, otherwise inferred from the highest roll value.

An optional `Roll d6 every N turns` (or `... every N days`) line sets the encounter
frequency.

---

## DM-only / spoiler convention

Secrets default to `**Scope:** dm_only`. Beyond the parsed scope field, preps conventionally
wall off spoiler content behind a loud banner so the DM-model never narrates it to the
player:

```
⛔ DM ONLY — NEVER REVEAL TO PLAYER ⛔
```

Everything below such a banner (etiology, hidden stakes, secret blocks) is for the
DM-model's eyes only. (Remember: every prep surface is the DM-model's prosthetic memory —
the player reads only the prose the DM writes, never the prep file itself.)

---

## Minimal valid example

The smallest file the validator accepts: one room, no `map(action="init")` call (so no
DUNGEON header is required).

```markdown
# OLD CISTERN — PREP

**Type:** Ruin

## ROOM: entry
**Name:** Flooded Entry
**Floor:** 1
**Connections:** down→sump
```

This passes (one room, all room fields present). It will warn only if you later add a
secret without a reveal condition, or call `map(action="init")` without the DUNGEON header.

---

## Fuller annotated example (vault)

```markdown
<!-- DUNGEON: map=old_cistern enforce=vault-liveness -->
<!-- SITE: key=old_cistern scene=vault_exploration aliases="Old Cistern|the cistern" -->
# OLD CISTERN — PREP

**Type:** Ruin (Flooded Reservoir)
**Scale:** Location
**Knowledge Scope:** Mixed (party_known + dm_only)
**Status:** PREPARED

---

## FOR THE DM (READ FIRST)
A collapsed Titan-era water reservoir. Two floors; the lower one is flooded.
Run check_canon before narrating, and review the DM ONLY section below.

---

⛔ DM ONLY — NEVER REVEAL TO PLAYER ⛔

### SECRET: drowned_cache
**Scope:** dm_only
**Truth:** A sealed equipment locker sits at the bottom of the sump, intact.
**Reveal Condition:** A character searches the flooded floor and succeeds on a STR/DEX check to reach the bottom.

### CONSTRAINT: rising_water
**Subject:** lower floor
**Limitation:** The sump floods one room per exploration turn; trapped characters take drowning damage.
**Scope:** party_known

---

## ENCOUNTERS
- **Turn 2:** A pump-servitor reactivates and begins draining — or flooding — at random.
- **Turn 5:** Something large moves in the sump.

---

## ROOMS

## ROOM: entry
**Name:** Flooded Entry
**Floor:** 1
**Connections:** down→sump, east→pump_room
**Entrance:** true

A cracked stone vestibule. Ankle-deep water. A stair descends into darkness.

**Obstacles:**
- **Rusted Grate:** A corroded grate blocks the stair.
  **Planned Solution:** Pry it (STR) or squeeze through (DEX, risks a cut).

**Secrets Present:** (none here)

## ROOM: pump_room
**Name:** Pump Room
**Floor:** 1
**Connections:** west→entry

Dormant pumping machinery lines the walls.

## ROOM: sump
**Name:** The Sump
**Floor:** 1
**Connections:** up→entry
**Secrets Present:** drowned_cache

The flooded lower chamber. Cold, black, deep.
```

This file passes validation: it has rooms with names/floors/connections, a DUNGEON header
(because a real prep that registers a map needs one), a SITE marker whose `key` matches the
DUNGEON `map=` slug, secrets with reveal conditions, and obstacle/solution pairs.

---

## Settlement preps (extra rule)

A prep whose SITE marker has `scene=settlement` is read by `settlement_system` to build a
"who's around" roster. For these, **every NPC block under the `## NPCs` (or `## KEY NPCs`)
heading must carry a `**Location:**` field** — the roster reader keys on it, and a missing
`**Location:**` is a *critical error* (server.py:2702). NPC blocks are `### NAME — Title`
headings; the parser also accepts the extended `## KEY NPCs ...` heading form
(`settlement_system._npc_blocks`).

```markdown
## NPCs

### WELL-KEEPER — Settlement Elder
**Location:** the_well
**Role:** Manages water access and traveler relations
...
```

---

## Validation workflow

Run before first play of a location:

```
validate_prep_file(prep_file="OLD_CISTERN_PREP.md")
```

- `✓ VALID` — prints room/secret counts and (on a fully clean file) pushes the next
  call, `map(action="init", ...)`.
- `❌ CRITICAL ERRORS` — these block `map(action="init")`; fix them first.
- `⚠️ WARNINGS` — advisory; the file still loads.

The validator also runs a **walkability cross-check** — it parses the rooms a second time
through the live `map_system` engine and warns if the two disagree, which catches malformed
`## ROOM:` headings the regex skipped (server.py:2714).
