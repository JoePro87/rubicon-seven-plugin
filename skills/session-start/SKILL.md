---
name: session-start
description: Initialize a new Vaarn game session with full MCP tool access. Checks for pending saves, loads all context, and states the current situation aloud for confirmation.
user-invocable: true
allowed-tools: Read, Bash, mcp__rubicon-seven__session_mode, mcp__rubicon-seven__full_session_startup, mcp__rubicon-seven__files, mcp__rubicon-seven__map, mcp__rubicon-seven__check_canon, mcp__rubicon-seven__sync_campaign_day, mcp__rubicon-seven__advance_day, mcp__rubicon-seven__thread, mcp__rubicon-seven__parley
---

# Session Start - Full Startup Workflow

You are beginning a new Vaarn game session. Your job is to load all context and confirm the current state with the player before proceeding.

## Step 1: Reset Session State

Clear any leftover maintenance flags and prose-catch counters and ensure gameplay mode is active. Call the engine tool:

```
session_mode(action="maintenance_off")
```

Then arm the NEXT session's output-style variant (anti-normalization rotation — this session's
style is already loaded, so the composition deliberately takes effect next launch). Run with the
engine venv's Python, pointing at this campaign folder:

```bash
<ENGINE_DIR venv python> <ENGINE_DIR>/scripts/compose_style_variant.py <CAMPAIGN_DIR>
```

(WSL + Windows venv: the script and campaign ARGUMENTS must be Windows-form paths —
`C:\...` — because Windows Python cannot open `/mnt/c/...` paths; only the `python.exe`
itself may be addressed via `/mnt/c/`.)

It prints one line (which stance is armed). Fail-soft by design — if it reports a skip or error,
note it and continue; never block session start on it.

## Step 2: Consult Auto Memory

Read this campaign's auto-memory `MEMORY.md` (if it exists). It lives in your campaign's own Claude project-memory dir. This cross-platform line prints it (uses `python`, works on macOS/Linux/WSL/native Windows):

```bash
python -c "import os;cwd=os.getcwd();slug=''.join('-' if c in '/.\\\\:' else c for c in cwd);p=os.path.join(os.path.expanduser('~'),'.claude','projects',slug,'memory','MEMORY.md');print(open(p,encoding='utf-8').read() if os.path.exists(p) else '(no MEMORY.md yet — early sessions)')"
```

This contains DM notes from previous sessions — pacing observations, voice calibration, cultivation hunches, soft context that structured state files don't capture. Use these notes to inform your approach this session, but do NOT share them with the player.

## Step 3: Review World Progress

Read `WORLD_PROGRESS.md`. This tracks what NPCs have been doing between sessions. Review silently:

- Check if any NPC actions should have completed based on current day
- Note progress that should surface in opening narration or organic discovery
- Identify any pending items that may intersect with today's scene
- Do NOT announce NPC progress mechanically — weave it into narration (a finished draft on a desk, a repair completed, a political update mentioned in passing)

## Step 4: Resonance Callbacks (via Narrative Synthesis)

Callback opportunities are covered by dm_narrative_synthesis.md (Step 7) which contains the organized "Callbacks Queued" section with activation triggers and delivery paths.

Full RESONANCE_INDEX.md is available via `files(action="read", filename="RESONANCE_INDEX.md", section_header="callback title")` if you need the raw context for a specific moment. Do NOT read the full file at session-start.

## Step 5: Review Antagonist Cultivation

Read `ANTAGONIST_CULTIVATION.md`. This is your private threat-tracking workspace — active threats, dormant seeds, and opportunities. Review what's in play so you can weave foreshadowing and NPC behavior into the session organically.

- Check if any dormant seeds should escalate based on current day and events
- Note active threats that may intersect with today's scene
- Do NOT share any contents with the player. Do NOT mention specific seeds, threats, or details.
- You may say "Cultivation reviewed" and nothing more.

## Step 6: Load Antagonist Dossiers (HARD GATE — DO NOT SKIP)

Dossiers carry operational detail (chronology, plans, assets, knowledge scope, weaknesses) that cultivation seeds do not — they exist to prevent improvising antagonist canon under in-scene pressure.

1. Read `ANTAGONIST_DOSSIER_INDEX.md`.
2. For every dossier in the **ACTIVE** and **RIPENING** sections, read the full dossier file at its listed path (`dossiers/[NAME]_DOSSIER.md`).
3. Do NOT read DORMANT or RESOLVED dossiers at session-start — they stay unloaded to protect the token budget.
4. Silent review. Absorb chronology, operational plans, and knowledge-scope maps for every hot-loaded antagonist.
5. Do NOT announce dossier load to the player. Do NOT quote or paraphrase dossier contents. Say nothing about this step.

**Why this matters:** Any antagonist whose dossier is hot-loaded here can surface in-scene today with coherent answers to player pressure-tests. Any antagonist whose seed is in cultivation but has NO dossier must be narrated only at cultivation's level of abstraction — no improvised specifics. If such a seed surfaces, log the gap for session-end to fill; do NOT fabricate detail under scene pressure.

**Token budget:** ACTIVE+RIPENING dossiers should stay ≤ 3-4 total at any time. If the index shows more, token management needs a look at next session-end.

## Step 7: Review Narrative Synthesis

Read `dm_narrative_synthesis.md` from the same project-memory dir (if it exists):

```bash
python -c "import os;cwd=os.getcwd();slug=''.join('-' if c in '/.\\\\:' else c for c in cwd);p=os.path.join(os.path.expanduser('~'),'.claude','projects',slug,'memory','dm_narrative_synthesis.md');print(open(p,encoding='utf-8').read() if os.path.exists(p) else '(no synthesis file yet)')"
```

This contains DM-level pattern recognition: unnoticed narrative rhymes, dormant character arcs, tonal gaps, structural opportunities, and queued callbacks.

Review silently:

- Are any dormant arcs approaching activation based on current day? (e.g., a party member's unclaimed gift, an NPC's buried fear, a long-deferred wish)
- Do queued callbacks intersect with today's likely scenes?
- Are tonal gaps still present or have they been addressed?
- Has the campaign had a genuine loss recently, or is it still in ascendancy mode?

Use these observations to shape pacing, NPC behavior, and environmental detail. Do NOT announce them to the player.

## Step 8: Load Session Context

Call `full_session_startup()` — this returns the sections the engine actually emits at startup:
- Current day and in-world date
- **Recent NPC states** — NPCs seen in the last 10 in-game days (disposition, location, wants)
- **Active threads** (from `CURRENT_STATUS.md`) and **tracked threads** (from `narrative_threads.json`)
- **⏳ WORLD FORCES briefing** (thread clocks + people moving on their own) — one line per clocked/moving force; 🔔 FIRED-but-unsurfaced ones persist until surfaced
- **🔗 WORLD FORCES (tangles)** — seeds that have knotted together around a shared person/faction; the engine co-locates them, you judge valence
- **☠ ANTAGONIST FORCES** — cultivated threats that are due or active
- **🤝 OPEN PARLEYS** — negotiations currently in progress (title, tier, party needles, day opened)
- **⚖ FACTION STANDINGS** — party REP with every tracked faction, flagged when stale
- **📍 SITE FEATURES (current place)** — stamped persistent features of wherever the party currently is (the site-feature ledger; omitted when none)
- **🔗 RECENTLY SHIFTED RELATIONSHIPS** — pairs whose status changed recently
- **Last session save block (full checkpoint narrative) — this is the canonical resume content; no separate `load_last_session()` call is needed**

**Not returned here:** voice guides, the relationship lexicon, scene state, arc context, emotional state, and vector search results are all deferred to `check_canon`, which loads them on its first per-turn call (Step 10 below) — don't expect them from `full_session_startup()` itself.

## Step 9: Check Vault Map State (if in vault)

If the scene state indicates vault exploration, call `map(action="render", map_name=<active map>)` to check current exploration state — revealed rooms, turn count, and encounter clock. (Map state also auto-injects on the `check_canon` call in Step 10 for vault scenes, per the spatial reflex.)

## Step 10: Verify Canon

Call `check_canon("session recovery")` to load canon/context for the current scene.

## Step 10.5: Initialize Bell Tracking

Read the `**Current Bell:**` field from CURRENT_STATUS.md. If present, set it via the engine tool (runs after Step 10's check_canon, so the gate is open):

```
sync_campaign_day(action="set_bell", bell=<BELL_NUMBER>)
```

If no bell field exists, infer from the last beat context (e.g., "morning" → 9, "evening" → 19) and set it. This ensures the phrase_reminder hook shows the correct in-game time from turn 1.

## Step 11: State Aloud

Summarize the current state clearly and completely:

```
**Session Resume - Day [X]**

**Location:** [where the party is]
**Present:** [who is here]

**Emotional States:**
- [Character]: [how they're feeling]
- [Character]: [how they're feeling]

**Last Beat:** [what just happened]

**Arc Context:** [current story arc and tension]

**Next Expected:** [what's pending/what comes next]

**Active Threads:**
- [urgent threads]
- [ongoing threads]
```

### Consume the ⏳ WORLD FORCES and 🤝 OPEN PARLEYS briefings

Consume the ⏳ WORLD FORCES briefing from `full_session_startup`: every 🔔 FIRED-UNSURFACED and ⏳ DUE force must surface in-fiction this session (a rumor, a changed settlement, an ambush) or be explicitly deferred by winding a new clock. Surfacing = logging the development on the thread (`thread(action="update", thread_id=..., development=..., development_day=...)`) — that is what clears it from future briefings.

If the 🤝 OPEN PARLEYS section lists a negotiation, weave its current state into the situation statement above (e.g. under "Next Expected") so the player resumes it deliberately instead of being surprised by it.

## Step 12: Confirm with Player

Ask the player:
> "Ready to continue? Let me know if anything needs correction."

Wait for their confirmation before proceeding with the session.

## Step 13: Day Reconciliation Gate (HARD GATE — DO NOT SKIP)

**This gate runs after the player confirms resume and BEFORE any narrative output.**

Meta day only advances when `advance_day()` is called. If the player implies a day change and you narrate without advancing first, the meta stays frozen and the session-end save commits the wrong day.

### Parse the player's resume message for day signals:

| Player said | Interpretation | Required action |
|-------------|----------------|-----------------|
| `"it's Day N"` / `"morning of Day N"` / `"start of Day N"` (N > saved day) | Explicit new-day declaration | Call `advance_day(new_day=N, brief_summary="Session starting on Day N — resumed from Day M save")` before narrating |
| `"next morning"` / `"the following day"` / `"the day after"` | Implicit +1 advance | Call `advance_day(new_day=saved_day+1, brief_summary="Session opening — the next morning")` before narrating |
| `"N days later"` / `"skip ahead N days"` | Explicit time skip | Call `advance_day(new_day=saved_day+N, brief_summary=...)` before narrating |
| No day mention, picks up where save left off | Same-day continuation | No advance needed. Proceed. |
| Ambiguous | Ask. Do NOT assume. | Pause and clarify: "Is this continuing Day M from the save, or are we starting Day N+?" |

### After advancing (if advancement was needed):

1. Confirm via `sync_campaign_day(action="get")` — the returned day MUST match the advanced day.
2. If it doesn't match, do not narrate. Debug first (check `CURRENT_STATUS.md` header, `characters/_meta.json`).
3. Only after the meta reflects the correct day may narration begin.

## Important Notes

> **Nothing surfaces to the player except in narrative sessions.** Maintenance and dev sessions may advance days and fire clocks, but must NEVER narrate world changes to the player — fired forces wait on the briefing until a live narrative session surfaces them. Clock labels are player-visible in advance_day output: keep them terse and spoiler-safe (antagonist-board redaction rules apply).

- ALWAYS call full_session_startup() first — memory is not canon
- State emotional states clearly for character consistency
- Step 13 is a hard gate. `advance_day()` runs before narration, not after. Every session.

