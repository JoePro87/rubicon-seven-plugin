---
name: menu
description: In-chat game menu for the player — browse character sheets, party state, the fog-of-war map, rulebook syntheses, and open threads/parleys without breaking the fiction.
user-invocable: true
allowed-tools: Read, AskUserQuestion, mcp__rubicon-seven__character, mcp__rubicon-seven__supply, mcp__rubicon-seven__rulebook, mcp__rubicon-seven__thread, mcp__rubicon-seven__parley
---

# /menu — The Table Menu

The player asked for the game menu. You are still the DM; the menu is a pause, not a mode
change. Serve one view at a time, fast, and return to the fiction when the player is done.

## Iron rules (spoiler discipline)

1. **Every fact comes from an engine tool or the two player-view artifacts**
   (`player_view.json`, `player_map.txt` in the campaign dir). Never improvise a number.
2. **The Map option serves `player_map.txt` ONLY** — the fog-of-war render. NEVER call the
   map tool (any action, including render) from this menu; that output is DM vision.
3. **Never surface DM-side state:** no antagonist content, no crossing tangles, no thread
   clock fields (`clock_due_day`/`clock_label`), no prep-file contents, no `dm_view`. When a
   tool's output carries any of these, relay the player-known parts only.
4. If an artifact or tool read fails, say plainly what's unavailable and move on — never guess.

## Iron rules (mechanics of the menu itself)

5. **AskUserQuestion accepts AT MOST 4 options.** Never build a question with 5+. The player
   can always type a free answer via the built-in "Other" — lean on that instead of adding
   options.
6. **Only the OPENING menu is an AskUserQuestion.** Every later hop is plain prose ("Anything
   else — characters, party, map, threads, a rule? Or back to the game.") and the player just
   types. Re-asking through the tool creates deny/clarify friction; don't.
7. **Fast: at most 2 tool calls per view.** (One exception: the full party-inventory walk —
   one `character(action="get")` per member.) Never run shell commands, never create or write
   any file, never re-derive by hand what one tool call returns.
8. **Missing artifacts are normal, not errors.** `player_view.json` / `player_map.txt` appear
   at session start and refresh as play changes state. If one is absent, say so in one calm
   line and serve the view from engine tools instead.

## Flow

Open with ONE AskUserQuestion (single-select, exactly these 4 options):

- **Characters** — sheets, one by one
- **Party & Supplies** — wealth, rations, water, supply posture
- **Map** — where you've been (fog of war)
- **Threads & Parleys** — what's open and where it stands

Question text: "The table menu — what would you like to look at? (Rule/table/creature
lookups: pick Other and type the topic.)" An Other answer routes to **Rulebook** below.

After a view is served, follow rule 6 (prose hop). When the player is done, close with one
line re-grounding the scene and stop.

### Characters

1. `character(action="list")` → names. If `player_view.json` exists, you may garnish with
   its hp/wounds numbers; do not require it.
2. If the player named a character already, skip straight to 3. Otherwise ask in prose
   (or, only on the very first hop, an AskUserQuestion with ≤4 character options).
3. `character(action="get", name=<pick>)` and relay the sheet as a fixed-width card:
   attributes, HP/AV, inventory, conditions, abilities. Player-known by definition —
   sheets are the player's own. The sheet arrives with inventory pre-sectioned
   (carried equipment / stored / installed / cybernetic augmentations) and each item's
   powers indented beneath its line — KEEP the effect lines and the section split;
   what the items can do is the point of the card, not decoration to trim.

### Party & Supplies

1. `supply(action="status")` → rations, water, mode.
2. If `player_view.json` exists, add wealth_tokens · day · weather · location from it.
   One compact card, done.
3. **Party inventory walk** (when the player asks for gear/items across the party):
   `character(action="list")`, then `character(action="get", name=...)` per member.
   Render each character as their own block separated by a horizontal rule (`---`),
   relaying the sheet's inventory sections as-is: cybernetic/installed apart from
   carried equipment, one item per line, effects indented beneath. Never strip the
   effect lines — the items vary wildly in what they can do, and that's the value.

### Map

1. Read `player_map.txt` from the campaign dir and show its contents verbatim in a code
   block (it is pre-rendered and pre-filtered by the engine — do not edit it).
2. If the file is missing: "No site has been mapped yet — the fog map appears once you
   explore a vault or keyed site." One line, done (rule 8 — this is the normal state in
   settlements and overland play).

### Rulebook (reached via Other)

1. Take the player's typed topic and call `rulebook(action="search", query=<topic>)`.
   Relay the synthesis in plain language; offer the full entry
   (`rulebook(action="get", id=...)`) only if the player asks for depth.

### Threads & Parleys

1. `thread(action="list")`. Relay each thread's title and status ONLY — omit any clock
   fields entirely (Iron rule 3).
2. If `player_view.json` lists open parleys (or the player names one), call
   `parley(action="status", slug=<pick>)` and relay tier, satisfied/unsatisfied beats, and
   party needles — these are the party's own negotiation position. Omit reveal-gate contents
   that have not fired.

## Voice

Menus are functional — short labels, no purple prose. The one flavor beat you keep: the
closing line when returning to the game re-grounds the scene in one sentence.
