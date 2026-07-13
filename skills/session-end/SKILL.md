---
name: session-end
description: Session-end — conducts a three-agent pipeline (Reconcile → Write → Verify) with a deterministic verifier and player approval. Saves the day's play to canon.
user-invocable: true
allowed-tools: Read, Edit, Bash, Agent, mcp__rubicon-seven__session_mode, mcp__rubicon-seven__verify_session_save, mcp__rubicon-seven__prepare_save_state, mcp__rubicon-seven__confirm_save, mcp__rubicon-seven__reindex_recent, mcp__rubicon-seven__distill_session, mcp__rubicon-seven__ingest_distillations, mcp__rubicon-seven__sync_campaign_day, mcp__rubicon-seven__thread, mcp__rubicon-seven__antagonist, mcp__rubicon-seven__npc, mcp__rubicon-seven__faction, mcp__rubicon-seven__advance_day
---

# Session End — Conductor

You conduct a three-agent pipeline. You handle the player conversation, the save approval, and the mechanical index calls. The agents do the thinking. The agent prompts live in this skill's own directory (the base directory named when this skill loads): `reconcile-agent-prompt.md`, `write-agent-prompt.md`, `verify-agent-prompt.md`, and the contract `facts-record-schema.md`.

## Step 1: Enable maintenance mode
Call the engine tool:
```
session_mode(action="maintenance_on")
```

## Step 2: Find the transcript and resolve the facts path
The transcript and facts record live in this campaign's own Claude project dir, derived from the campaign folder. This one cross-platform line prints both (uses `python`, not `python3` — works on macOS/Linux/WSL/native Windows):
```bash
python -c "import os,glob;cwd=os.getcwd();slug=''.join('-' if c in '/.\\\\:' else c for c in cwd);d=os.path.join(os.path.expanduser('~'),'.claude','projects',slug);j=sorted(glob.glob(os.path.join(d,'*.jsonl')),key=os.path.getmtime);print('TRANSCRIPT='+(j[-1] if j else 'NONE'));print('FACTS_PATH='+os.path.join(cwd,'session_end_facts.json'))"
```
If `TRANSCRIPT=NONE`, the slug guess missed — list `~/.claude/projects/` and pick the dir matching this campaign folder, then take its newest `*.jsonl`.
The frozen facts record lives at `<campaign-root>/session_end_facts.json` — i.e. `$PWD/session_end_facts.json`, since you run from the campaign folder. Use that absolute path for every `{{FACTS_PATH}}` substitution below.

## Step 3: RECONCILE
Dispatch an Agent (mode `bypassPermissions`) with the full contents of `reconcile-agent-prompt.md` (in this skill's directory), replacing `{{TRANSCRIPT_PATH}}` with the path from Step 2 and `{{FACTS_PATH}}` with the absolute facts path from Step 2. Wait. It writes the frozen facts record and reports the day + counts. Tell the player: "Reconciled — Day N, M beats."

## Step 4: WRITE
Dispatch an Agent (mode `bypassPermissions`) with the full contents of `write-agent-prompt.md`, replacing `{{FACTS_PATH}}` with the absolute facts path. Wait for its per-file report.

## Step 5: VERIFY (pass 1, pre-save)
Dispatch an Agent (mode `bypassPermissions`) with `verify-agent-prompt.md`, replacing `{{FACTS_PATH}}` with the absolute facts path and `{{PASS}}` = 1.
- If it returns a send-back list: re-dispatch the WRITE agent with a SCOPED instruction naming only those files, then re-run VERIFY pass 1. Bounded to 2 rounds per gap; then surface to the player.
- Only when pass 1 is PASS, continue.

## Step 6: SAVE (you do this)
Re-fetch `sync_campaign_day(action="get")`. Call `prepare_save_state(...)` built from the facts record (day = the re-fetched integer; `emotional_states` as a dict; clean plain-text values). If it returns `ERROR:`, re-fetch the day and retry. Show the player the diff + the Verify summary. Ask: "Approve, correct, or reject?"
- **Approve** → `confirm_save(token)`.
- **Correct the save block** → re-call `prepare_save_state` with the fix; re-show.
- **Correct a rich file** → re-dispatch WRITE scoped to that file → VERIFY pass 1 → re-prepare.
- **Reject** → stop; the files written this session remain on disk; a later run is safe (idempotent).

## Step 7: INDEX (you do this, after confirm)
- `distill_session(action="write", entries=<facts.distillation_entries>, session_id=<facts.session_id>)`
- `ingest_distillations(session_id=<facts.session_id>)`
- `reindex_recent()`

## Step 7.5: WORLD TICK RECORD + CRYSTALLIZATION (you do this)
Review the days elapsed this session plus the threads list (`thread(action="list")`). Write world deltas INTO ENGINE STATE. This is where newly-established canon (new NPCs, faction shifts) is crystallized — nothing else in the pipeline owns it, so a person or standing you skip here is invisible to the heartbeat and to `check_canon` next session.

**Threads / antagonists (as before):**
- Wind or clear clocks via `thread` (params `clock_due_day` / `clock_label`; `-1` clears).
- Update the antagonist board via `antagonist`.
- An off-screen force that should move while the party is away gets a clock, not a prose note.

**NEW NPCs (C3) — `facts.npc_candidates`:** the reconcile agent hands you a candidate list (people met this session who are neither party nor already recorded, each with a one-line "why they might recur"). YOU judge recur-vs-evaporate — walk-ons are explicitly allowed to evaporate, do NOT register them. For each candidate you judge RECURRING:
- Register the record: `npc(action="set", name="<as they appear in prose>", disposition="<hostile|wary|neutral|friendly|allied>", wants="<their agenda>", location="<where last seen>", last_seen_day=<day>)`. Add `knows="fact; fact"` and `secret="..."` if the session established them.
- If they have an OPEN agenda that should move while the party is away, give them a purpose_clock so they join the heartbeat: `npc(action="continuity", name="<same name>", left_off="<where the scene left off, <=1 sentence>", open_purpose="<their open agenda, <=1 line>", pace="cool")` — pace is a temperature ramp: `cool` ~monthly, `warm` ~weekly, `hot` every few days; omit / `still` for someone with no forward motion.

**FACTION shifts (C4) — `facts.faction_shifts`:** for each faction-relevant beat the reconcile agent flagged:
- An existing faction's standing moved → `faction(action="earn", name="<faction>", amount=<+/- delta>, reason="<what happened>")` (or `faction(action="set", name=..., rep=<absolute>, reason=...)` to seed/override).
- A newly-distinguished group first fixed in play → `faction(action="add", name="<name EXACTLY as it appears in prose>", rep=<-10..10>, reason="...", notes="...")`. **Naming matters:** `check_canon`'s faction-injection matches the FULL faction name in the message, so register the name the party will actually say in-scene (e.g. "the Cacklemaw Exiles", not bare "Cacklemaw"). When a group splits into hostile-vs-allied splinters of one parent, add a `notes=` cross-reference on each so a fresh DM reading the parent's standing isn't misled about the splinter.
- Do NOT hand-edit `factions.json` — the tool owns the write and the history log.

- `WORLD_PROGRESS.md` is the DM's world-state mirror — update it LAST, from engine state, never instead of it.

## Step 8: VERIFY (pass 2, post-save)
Dispatch VERIFY (same `verify-agent-prompt.md`, `{{FACTS_PATH}}` = the absolute facts path) with `{{PASS}}` = 2, passing `reindex_ok` (from Step 7's reindex result) and `distillations_written` (count from Step 7). Relay the PASS/FAIL and the DM-only vital-signs line. If the cache-loop check fails, re-run `ingest_distillations` once and re-verify.

**Day-regression watch:** pass 2's `day_agreement` check is your backstop against a save mis-stamping the day. If it reports a mismatch (e.g. CURRENT_STATUS or the meta dropped a day), restore with `advance_day(new_day=<correct day>, ...)` and re-verify before reporting done.

## Step 9: Report to the player
What was saved, day + location, emotional states, files updated (counts only for antagonist), reindex status, and the vital-signs line. Surface any ALARM prominently.

## Notes
> **Nothing surfaces to the player except in narrative sessions.** Maintenance and dev sessions may advance days and fire clocks, but must NEVER narrate world changes to the player — fired forces wait on the briefing until a live narrative session surfaces them. Clock labels are player-visible in advance_day output: keep them terse and spoiler-safe (antagonist-board redaction rules apply).

- The save token expires in 10 minutes — don't stall between the diff and approval.
- `/session-start` clears maintenance mode.
- Classified discipline: never quote cultivation/dossier contents; report counts only.
