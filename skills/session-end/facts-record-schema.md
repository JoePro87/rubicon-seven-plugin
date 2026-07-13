# Session-End Facts Record — Schema

The Reconcile agent writes this once to `session_end_facts.json` in the campaign root (the folder you play from — the conductor passes the absolute path as `{{FACTS_PATH}}`) and **freezes it**. The Write agent and Verify agent read it; neither edits it. It is transient (overwritten each run) and git-ignored.

The values below are illustrative placeholders — substitute your own campaign's people, places, and arc.

```json
{
  "run_started_at": "2026-05-31T14:00:00",
  "session_id": "2026-05-31",
  "day": 129,
  "day_reconciled": {"was": 128, "now": 129, "advanced": true},
  "scene": {
    "location": "the cistern-town market, lower tier",
    "characters_present": ["<PC name>", "<PC name>", "<NPC name>"],
    "last_speaker": "<NPC name>",
    "last_beat": "The archivist set the canister down without looking at it.",
    "next_expected": "A party member opens page twenty of the journal."
  },
  "beats": ["ordered", "list", "of in-world events this session"],
  "narrative_log": "Prose summary of the session built from the beats — the text the save block will use and the vital-signs scanner will check.",
  "locations_touched": ["SOME_PREP_FILE.md"],
  "people": {
    "present": ["<NPC name>"],
    "mentioned": ["<other NPC>"],
    "relationship_shifts": ["<NPC> → <PC>: rapprochement deepened"]
  },
  "mechanical_changes": ["<PC> HP 24/24 unchanged", "no level changes"],
  "emotional_states": {"<PC>": "sharp, settled", "<NPC>": "guarded, thawing"},
  "arc": {"current_arc": "...", "arc_summary": "...", "arc_tension": "...", "mood": "..."},
  "escalations": ["warrant 48h window opened"],
  "scratchpad_routed": {
    "cultivation_seeds": [], "npc_notes": [], "narrative_observations": [], "pacing_notes": []
  },
  "corrections": [
    {"entity": "<npc_slug>", "wrong_terms": ["botanist"], "correct_fact": "<NPC> is a navigator, not a botanist.", "topic_key": "<npc_slug>_identity"}
  ],
  "distillation_entries": [
    {"topic_key": "<npc_slug>_identity", "learning": "...", "key_facts": ["..."], "source_pointers": ["lorebook.json:<npc_slug>"], "type": "identity", "characters": ["<npc_slug>"], "entities": ["<faction or house>"], "arc": "CURRENT", "day_range": "130"}
  ],
  "new_canon": ["..."],
  "npc_candidates": [
    {"name": "<NPC name>", "why": "One line on why they might recur — an open agenda, a promise, a standing tie."}
  ],
  "faction_shifts": [
    {"faction": "<faction name>", "shift": "Sealed a peace accord — allied trade partner (was untracked).", "kind": "add"}
  ],
  "memory_flags": {"consolidation_needed": false}
}
```

## `npc_candidates` and `faction_shifts` (the crystallization feed — C3 / C4)

These two lists are what the conductor's **Step 7.5** turns into engine records. The reconcile agent BUILDS them; the conductor (DM) ACTS on them. They are a feed for a judgment call, not a guaranteed write — so the verifier does NOT expect every candidate to land (a walk-on the DM lets evaporate is correct, not a gap).

| Field | Element shape | Meaning |
|-------|---------------|---------|
| `npc_candidates` | `{name, why}` | A person present this session who is neither party nor already in `npc_states.json`. `why` = one line on why they might recur. The DM registers RECURRING ones via `npc(action="set")` (+ `npc(action="continuity", pace=...)` if they have an open agenda); walk-ons are allowed to evaporate. |
| `faction_shifts` | `{faction, shift, kind}` | An organisational standing that moved. `kind`: `earn` (delta), `set` (absolute), `add` (group first named this session). `faction` = the name EXACTLY as it appears in prose (channel-2 `check_canon` injection matches the full name). The DM applies it via `faction(action=<kind>, ...)`. |

Both default to `[]`. An empty list is a normal, quiet outcome (a session with no new recurring people / no organisational movement).

## Expected-writes derivation (the verifier uses this)

Given the facts record, these writes are EXPECTED to have landed:

| Always | Conditional |
|--------|-------------|
| `MEMORY.md` (session note) | `RESONANCE_INDEX.md` — if any resonant beat (judgment; Write agent sets it, verifier checks file freshness only when `beats` non-empty) |
| `dm_narrative_synthesis.md` (synthesis, fresh) | prep PROGRESS LOGs — if `locations_touched` non-empty |
| `VAARN_DM_SCREEN.md` (checked/patched) | `ANTAGONIST_CULTIVATION.md` + dossiers — if `escalations` or `scratchpad_routed.cultivation_seeds` non-empty |
| `WORLD_PROGRESS.md` | `narrative_threads.json` — if `escalations` non-empty |
| character JSON sync *(owned by the save commit, not a write-agent file; verifier treats it as agent-attested)* | hygiene pass on `MEMORY.md`/synthesis — if `memory_flags.consolidation_needed` |

"Landed" = file mtime ≥ the facts record's own mtime (the record is written first, so any genuine write is newer).
