# Rubicon Seven — Technical Design Document

**Version:** 8.9.1
**Date:** 2026-05-29 (last full 13-section parity audit); canon-engine sections last touched 2026-06-06
**System:** Rubicon Seven MCP + Campaign State
**Platform:** FastMCP 3.0.0b1 on WSL2, Claude Code CLI

---

> **How to read this document.** The rendered prose is the **current** specification — it is the single source of truth for how the system behaves now. The dated `<!-- REVIEWED / UPDATED yyyy-mm-dd ... -->` HTML comments are a **historical changelog**, not current spec: each records what changed (and why) on its date, newest entry first within a section. They are kept for provenance and to stop rejected approaches being re-tried. **Read them as history** — an older entry may cite numbers or behavior that a later entry or the live prose has since superseded (e.g. a 2026-05-29 note says the distillation collection held 179 entries; the 2026-06-06 harvest took it to ~1,459). When a comment and the prose disagree, the prose and the newest dated entry win.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture](#2-architecture)
3. [The Canon Engine (check_canon)](#3-the-canon-engine)
4. [Hook Chain](#4-hook-chain)
5. [Prose Quality Stack](#5-prose-quality-stack)
6. [State Management](#6-state-management)
7. [Combat System](#7-combat-system)
8. [Generation Stack](#8-generation-stack)
9. [Spatial Systems](#9-spatial-systems)
10. [ChromaDB & Vector Search](#10-chromadb--vector-search)
11. [Tool Visibility & Gating](#11-tool-visibility--gating)
12. [Data Schema Reference](#12-data-schema-reference)
13. [Operational Summary](#13-operational-summary)

---

## 1. System Overview
<!-- Authoritative tool count lives in §1 "MCP Tool Inventory" (verified via mcp.list_tools()). Do not scatter hard counts elsewhere — they rot. -->
<!-- Paths are derived (rubicon_paths.py), not machine-specific. Exact line/file counts deliberately omitted from this spec — they rot; run wc/find for current figures. -->

Rubicon Seven is an autonomous DM system for Vaults of Vaarn (dying-earth science-fantasy TTRPG). It comprises two directories:

| Directory | Role |
|-----------|------|
| **Engine dir** — `$RUBICON_ENGINE_DIR` (default: this repo's root) | MCP server, tools, hooks, generation, rules data, ChromaDB client |
| **Campaign dir** — `$RUBICON_CAMPAIGN_DIR` (default: the sibling `rubicon-seven-campaign/`) | Campaign state, prep files, lorebook, character data — the data store |

Paths are derived at runtime by `rubicon_paths.py` (env override, else this repo's root and its sibling); nothing is hardcoded to a specific machine. (Exact line/file counts are intentionally omitted — they rot; run `wc`/`find` for current figures.)

They connect via the Model Context Protocol. The campaign directory is the data store. The MCP server reads and writes to it. Claude Code is the runtime host — it receives player input, calls MCP tools, and produces narrative output. The hook system validates every stage of that process.

The server resolves its data root from the `RUBICON_CAMPAIGN_DIR` env var (resolved in `rubicon_paths.py`), defaulting to the real campaign dir. **Engine-repo sandbox (2026-06-10):** the engine repo's (gitignored) `.mcp.json` sets `RUBICON_CAMPAIGN_DIR` to `sandbox-campaign/` — a gitignored throwaway built by `scripts/make_sandbox.py` (copies `rulebook/` from the sibling campaign repo; synthesizes test PCs + minimal state files) — so live smoke tests run from the engine repo can never touch real play state (the engine-play-never-canon rule). **WSL gotcha (2026-06-11):** the MCP client runs in WSL but launches the *Windows* venv Python; env vars do NOT cross that boundary unless named in `WSLENV` — the `.mcp.json` env block must include `"WSLENV": "RUBICON_CAMPAIGN_DIR:PYTHONUNBUFFERED"` or the server silently falls back to the REAL campaign dir. The test suite independently isolates itself via `tests/conftest.py` (temp campaign dir per test + session-scoped byte-snapshot/restore of the live `hooks/` data files).

**Canonical skills/output-style location (2026-06-10):** `skills/` (content-forge, vaarn-portrait, session-start, session-end, vaarn-start) and `output-styles/` (rubicon-seven-dm + base) in the engine repo are the canonical, versioned copies; the deployed copies in `~/.claude/skills/` and the campaign repo are downstream (see `skills/README.md` and `docs/DEVELOPMENT.md` §6). These ship inside the 1.0.0 plugin.

**`vaarn-start` (`skills/vaarn-start/SKILL.md`):** the OSS onboarding front door for a brand-new player, run once before any real play. It walks TONE (a short conversation that writes the player's own DM-protocol `CLAUDE.md`) → SETUP (detects the platform, generates the engine config, scaffolds a blank Day-1 campaign dir via `scripts/scaffold_campaign.py`) → CHARACTER (rolls up the wanderer through the live engine-pushed chargen chain: `character(action="create")` → `create_finalize` → the pushed weapon/armour/boon rolls) → SCENE (opens the first scene) → SESSION ZERO + HANDOFF (writes a session-zero save so `/session-start` works). Like the other skills, it stays thin: every mechanic is engine-owned and pushed, not re-encoded as skill prose.

### Design Principles

1. **Dual failure philosophy** — Enforcement hooks fail closed (exception = block delivery, not allow through). Tools fail open (exception = skip injection, continue with reduced context). Two *advisory* hooks are deliberate exceptions and fail open by design: `phrase_reminder.py` (UserPromptSubmit) prints nothing and exits 0 on any error — a missing discipline reminder must never block a turn; `post_compact.py` (PostCompact) likewise stays silent on error — no re-injected validate_prose reminder is better than a crash. Guardrails break loud; advisory nudges and data degrade quiet.
2. **Atomic writes** — All file writes use temp-file-then-rename to prevent corruption
3. **Mtime-based caching** — JSON files cached in memory, invalidated on filesystem change
4. **Escalating context** — Most turns inject ~500 tokens; full context fires only when triggers demand it
5. **Tool Before Tale** — No narrative claims without tool verification first
6. **Secrets stay classified** — DM-only content never surfaces to the player

---

## 2. Architecture


### Per-Turn Execution Flow

```
Player input
    │
    ▼
┌─────────────────────────────────────────────────┐
│  UserPromptSubmit Hooks                         │
│  1. turn_reset.py (316 lines) — reset canon     │
│     flags, compute scene fingerprint, decide    │
│     if canon is required this turn              │
│  2. phrase_reminder.py — inject discipline       │
│     reminder, bell tracking, semantic priming   │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Claude generates response, calling tools...    │
│                                                 │
│  For each tool call:                            │
│  ┌────────────────────────────────────────────┐ │
│  │ PreToolUse: gate_check.py                  │ │
│  │ - ALWAYS tools: pass                       │ │
│  │ - GATED: require canon_verified +          │ │
│  │          canon_succeeded                   │ │
│  └────────────────────────────────────────────┘ │
│                                                 │
│  After check_canon returns:                     │
│  ┌────────────────────────────────────────────┐ │
│  │ PostToolUse: spoiler_check.py              │ │
│  │ - Validates check_canon output             │ │
│  │ - Sets canon_succeeded = True              │ │
│  │ - Injects spoiler reminder if secrets      │ │
│  └────────────────────────────────────────────┘ │
│                                                 │
│  After prepare_save_state returns:              │
│  ┌────────────────────────────────────────────┐ │
│  │ PostToolUse: verify_save.py (167 lines)    │ │
│  │ - Spawns verify_save_agent.py subprocess   │ │
│  │ - Compares proposed save fields against    │ │
│  │   conversation transcript                  │ │
│  │ - 80% token overlap threshold              │ │
│  │ - HARD BLOCK if unverified claims found    │ │
│  │ - Returns corrected fields for re-save     │ │
│  └────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Stop event: consolidated_stop_check.py         │
│  16 sequential checks (one blocks — dm-design   │
│  review gate; the other 15 are diagnostic-only  │
│  or advisory). See §4 for the full list.        │
└─────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────┐
│  Async (detached subprocess):                   │
│  prose_observer.py                              │
│  - Haiku 4.5 judges response against 11        │
│    situation strategy categories                │
│  - Writes violations to catch_analytics.json    │
│  - Feeds phrase_reminder.py on NEXT turn        │
└─────────────────────────────────────────────────┘
```

### Middleware Stack

Two FastMCP middleware layers process every tool call (registered in the `FastMCP(...)` constructor at `server.py:1443`):

| Layer | Class | Behavior |
|-------|-------|----------|
| Response Caching | `ResponseCachingMiddleware` | 5-minute TTL on static lookups (`lorebook_view`, `reference_location`, `lookup`, `gift`, `narrative_qa`). Saves redundant MCP round-trips. |
| Performance Logging | `PerfLoggingMiddleware` (instance `perf_logger`) | Logs response size and wall-clock time per tool call to `logs/perf_log.jsonl`. Diagnostic only — nothing reads it automatically. |

### MCP Tool Inventory (49 tools)

Tools are registered across 7 files: server.py (36 `@mcp.tool` decorators), session_tools.py (8 — the save/persistence chain: `save_state`, `prepare_save_state`, `confirm_save`, `load_last_session`, `full_session_startup`, `verify_session_save`, `distill_session`, `ingest_distillations`), content_forge.py (1 — `roll`/forge), geography_system.py (1 — `geography`), map_system.py (1 — `map`), rulebook_system.py (1 — `rulebook`), social_system.py (1 — `parley`, the negotiation state machine; see §9 Social Play-Loop). External modules register via `register_*_tools(mcp, ...)` called at startup. 36 + 8 + 4 + 1 = 49 (verified against the live `@mcp.tool` registry 2026-07-04).

Consolidated 2026-05-27: 24 standalone tools merged into 8 action-based tools (see `docs/superpowers/specs/2026-05-27-tool-consolidation-design.md`).

W1 family merge 2026-06-14 (the first tool-RENAME wave of the 64→~31 decomposition program; see `docs/superpowers/plans/2026-06-12-tool-consolidation-decomposition-plan.md`): six tools collapsed into three action-dispatched domain tools — `constraint(action=add|check)` ← constraint_add/check; `narrative_qa(action=validate|check|list)` ← validate_prose/anti_patterns; `log(action=add|get)` ← log_beat/get_session_log. The prose gate (gate_check) is now action-aware (clears on `narrative_qa(action='validate')`). Each of the six legacy names remained **one cycle as a transparent tombstone alias** (delegates to the same private `_impl`, identical return); all such tombstones were then deleted (see the *Tombstone-removal cleanup 2026-06-14* paragraph below), so the category table now shows only the live action-dispatched surface. Merge tag-tension resolved per family: `constraint` is GATED (write posture), `log` is ALWAYS (read posture, keeps `log(get)` available at resume).

W2 family merge 2026-06-14 (second tool-RENAME wave): file I/O split by gate posture into two tools — `files(action=list|read|pdf)` ← list_files/read_file_section/read_pdf_pages (all ALWAYS reads); `edit_file(action=replace|overwrite)` ← replace_in_file/update_file (both GATED writes). Reads and writes stay separate tools precisely because their gate postures differ and both matter (you read files pre-canon at resume; writes must stay gated) — a single `file` tool would force a tension. The prep-edit detector in `consolidated_stop_check.py` now matches `edit_file`. Five legacy names remain one cycle as transparent tombstone aliases. Prep tools (update_active_prep/validate_prep_file) left unmerged (gate-tension + low value).

W3 family merge 2026-06-14 (third tool-RENAME wave): the three RAG read tools → `search(action=history|tiered|health)` ← search_campaign_history (a tier-2 wrapper) + search_history_tiered + chroma_health_check. Reads only (all ALWAYS), so no gate-tension; the dispatcher is async (the two query impls are async). The index-WRITE tools (reindex_recent/ingest_distillations/distill_session) stay separate — read/write posture split + save-pipeline sensitivity. The world-tick canon-pull push and the session-start CONTEXT RETRIEVAL help now emit `search(action='history')`. Three legacy names remain one cycle as transparent tombstones. (Pre-existing source bug noted in commit: reindex_recent inherits chroma_health_check's tags.)

Affliction wave 2026-06-14 (first MEDIUM/combat-path wave): `condition`+`disease`+`toxin`+`wound` → `affliction(kind=condition|disease|toxin|wound, action=…)`, a two-axis dispatcher with a 27-param union. Each source became a private `_<name>_impl` (body unchanged); the dispatcher routes by `kind`, passing each impl exactly its declared params, with FieldInfo normalization for the toxin/wound params (condition/disease self-normalize). All four GATED → no gate-tension; tag = union. 17 structured `push_call` sites re-pointed to `affliction(kind=…)`; 18 hardcoded f-string guidance refs deferred to the tombstone-removal pass. Four legacy names remain one cycle as transparent tombstones. Reviewed heavy (combat-path): param-routing introspection + a 4-agent adversarial Workflow → zero findings.

Tombstone-removal cleanup 2026-06-14 (closes the consolidation easy-rail). All **18 transparent tombstone functions** deleted from `server.py` (constraint_add/constraint_check, anti_patterns/validate_prose, log_beat/get_session_log, list_files/read_file_section/read_pdf_pages, replace_in_file/update_file, search_campaign_history/search_history_tiered/chroma_health_check, condition/disease/toxin/wound) — the durable `_<name>_impl`s and the new domain dispatchers remain. Their 18 old `TOOL_TAGS` keys removed. The deferred old-name guidance refs were re-pointed to the new surface across the WHOLE codebase, not just `server.py`: the 18 affliction f-string hints + the `read_file_section()`/`log_beat()`/`search_history_tiered`/`search_campaign_history` docstring refs (server.py), the `conditions.py` resurrection push, two `phrase_reminder.py` reflex pushes, and the `content-forge`/`session-start` SKILL.md pushes + allowed-tools list. Legacy hook literals dropped: `gate_check.py` clears the prose gate ONLY on `narrative_qa(action='validate')` (the `validate_prose` literal is gone; the internal `validate_prose_required`/`_called` state-flag keys are a server↔hook contract and stay); `consolidated_stop_check.py`'s two prep-edit detectors key only `edit_file` now. `reindex_recent`'s decorator now uses its own tag key (was the cosmetic `chroma_health_check` borrow). Tests: 103 direct `server.condition(/disease(/toxin(/wound(` invocations migrated to `server.affliction(kind=…, …)` across 7 files (behavior-identical — dispatcher `_nz` + impl self-normalization); tombstone-existence subtests removed from `TestXMerge`; `REAL_TOOLS` allowlist and the prep-gate/transcript tests re-pointed to the domain names. Full suite **2307 passed / same 15 known pre-existing failures**; zero new. **18 narrow tools → 8 domain tools is now clean** (no back-compat aliases). Cross-repo follow-up: the campaign repo's own copies of these SKILL.md files need the same re-point before the consolidated tools go live there.

Category table below ground-truthed against the live `@mcp.tool` registry 2026-07-04 (49 tools; each appears once, counts sum to 49). The pre-2026-06-14 legacy names (get_session_log, get_current_day, set_bell, gleam_check, update_photosynthesis, condition/disease/wound/toxin, constraint_add/check, update_vehicle_location, log_beat, search_campaign_history/search_history_tiered/chroma_health_check, list_files/read_file_section/read_pdf_pages, replace_in_file/update_file, anti_patterns/validate_prose) are gone — folded into the action-dispatched domain tools shown here.

| Category | Count | Tools |
|----------|-------|-------|
| Session Management | 10 | check_canon, save_state, prepare_save_state, confirm_save, verify_session_save, full_session_startup, load_last_session, advance_day, sync_campaign_day, log(action=add/get) |
| Character | 8 | character, rest(action=short/long), codex(action=add/remove/use/mishap), cybernetic(action=install/list/remove), gift(action=add/remove/cost), affliction(kind=condition/disease/toxin/wound), usage, supply |
| Combat | 2 | combat, lookup(action=creature/exotica/weapon_tag/career) |
| Location/Exploration | 6 | map, constraint(action=add/check), update_location_progress, validate_prep_file, reference_location, geography |
| Generation | 3 | roll(action=encounter/reaction/exotica/mutation/location/soul/settlement/landmark/placename/weather/environment/chargen/check/save/damage/list_tables), generate(action=exotica/weapon/armour/npc/poison/elixir/gift/drug/crucible/codex/faction/story_seed), rulebook |
| Narrative | 7 | lorebook, npc, relationship, thread, faction, antagonist, parley(action=open/status/list/move/tier/needle/reveal/close) — see §9 Social Play-Loop |
| Search/History | 4 | search(action=history/tiered/health), reindex_recent, ingest_distillations, distill_session |
| File Operations | 3 | files(action=list/read/pdf), edit_file(action=replace/overwrite), update_active_prep |
| Validation/Admin | 6 | reset_gate, session_mode, validate_campaign_state, narrative_qa(action=validate/check/list), get_visibility_status, test_dice |

---

## 3. The Canon Engine

**Location:** `server.py` — `def check_canon` (find via `workspaceSymbol`; body runs to the next `@mcp.tool`; check_canon helpers precede the decorator). Line numbers omitted deliberately — navigate by symbol, per the LSP-first pillar.
**Tool:** `check_canon()`

The most important tool in the system. Runs every player turn, gates all narrative tools, and builds the context window that informs Claude's response.

### Parameters

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `user_input` | str | required | The player's message |
| `needs` | list[str] | [] | Context blocks to load. Valid: voice, relationships, prep, npc_knowledge, threads, history, characters, lorebook_full, prep_npcs:\<name\>. Empty = regex auto-detect. |
| `auto_correct_prep` | bool | False | Auto-fix Active Prep field on mismatch |

### Files Read (in order)

1. CURRENT_STATUS.md — parsed via `_parse_status_content()`, reused throughout
2. lorebook.json — cached with mtime invalidation
3. .hook_state.json — turn count, scene_changed flag
4. VOICE.md — selectively loaded sections for present characters only
5. RELATIONSHIP_MATRIX.json — for present character relationship injection
6. characters/*.json — split-file sheets (sole source of truth; monolithic characters.json fallback retired)
7. npc_states.json — NPC knowledge scope injection
8. narrative_threads.json — active thread injection
9. Active prep file (e.g., CERULINE_ARCOLOGY_PREP.md) — surgical section reads
10. LOCATION_REGISTRY.json — location/prep mismatch validation
11. scene_state/emotional_state.md — fallback if CURRENT_STATUS lacks emotional section
12. .canon_distillations.json — local distillation cache
13. ChromaDB collections — canon_distillations first, then campaign_history_tiered

### Context Shopping List (replaces Three Output Modes)

check_canon no longer uses light/auto-light/full modes. Instead, context is assembled from discrete blocks requested via the `needs` parameter.

| Block | What it loads | Secrets? |
|-------|-------------|----------|
| `voice` | VOICE.md sections for present characters | No |
| `relationships` | RELATIONSHIP_MATRIX.json entries for present characters | No |
| `prep` | Prep overview + location section + scene-type routing + DM ONLY secrets + progress log | Always bundled |
| `prep_npcs:<name>` | Specific NPC section from active prep, regardless of Present field | Yes |
| `npc_knowledge` | npc_states.json knowledge boundaries for present characters | Yes |
| `threads` | Active narrative threads | Yes |
| `history` | ChromaDB deep search (progressive tiers) | No |
| `characters` | Full party stat blocks | No |
| `lorebook_full` | Full `context` field instead of `short_context` for keyword-matched entries | Inherent |

**Default (empty `needs`):** Regex fallback runs — identical to pre-redesign auto-light behavior.

**When `needs` has items:** Union of Claude's list + regex results. System only adds, never subtracts.

### Regex Fallback Mapping

Regex patterns on player input automatically add blocks. Multiple triggers union together.

| Trigger | Condition | Blocks added |
|---------|-----------|-------------|
| Scene change | Location or Present fingerprint changed | `prep`, `voice`, `relationships`, `npc_knowledge`, `characters` |
| Session start | Turn count ≤ 1 | All blocks |
| Scene recall | `***` suffix on input | `history`, `lorebook_full`, `prep` |
| Intimate regex | kiss, embrace, naked, etc. | `voice`, `relationships`, `lorebook_full` |
| Lore question regex | "what do we know," "who is," etc. | `lorebook_full`, `history`, `threads` |
| High match count | 4+ lorebook keyword hits | `lorebook_full`, `threads`, `prep` |

### Lorebook Matching

Each lorebook entry's keywords are matched against user input using word-boundary regex:

```
\b{escaped_keyword}\b
```

This prevents "arc" from matching "search" and "Kael" from matching "Kaela." First keyword match per entry wins — breaks after first hit to avoid double-counting.

Context depth depends on mode:
- Light/auto-light: uses `short_context` field (falls back to `context`)
- Full: uses full `context` field
- Any entry over 500 chars is smart-truncated, preserving identity fields (pronouns, species)

### Prep File Integration

1. Reads `Active Prep:` field from CURRENT_STATUS.md
2. Loads that prep file from the campaign directory
3. Extracts overview (capped at 300 chars)
4. Performs surgical section reads based on:
   - **Sub-location matching**: Parses current location's first comma segment, matches against `#### LOC: Name(id)` headers with fuzzy matching
   - **NPC matching**: Matches present NPCs against `### NPC: Name(alias)` headers
   - **Scene-type routing**: settlement/social → Factions; vault_exploration/combat → Encounters; travel → Encounters
5. First load of a prep file per server session includes the `## FOR NEW CLAUDE` section (up to 1500 chars)

### Secrets System

Four parsing patterns extract classified content from prep files:

| Pattern | Format | Extracts |
|---------|--------|----------|
| Modern | `DM ONLY...END DM ONLY` blocks | Bullet points and short sentences |
| Legacy GM | `## MODULE OVERVIEW (GM KNOWLEDGE ONLY)` | "The Twist" and "True Purpose" text |
| Structured | `### SECRET: id` with `Scope: dm_only` | The `Truth:` field |
| Section | `## DM KNOWLEDGE` | Bullet points |

Extracted secrets injected under `**⛔ SECRETS (do not reveal until discovered):**`, capped at 7 items. Separate from DM Knowledge in CURRENT_STATUS.md (capped at 500 chars).

### Delta Delivery (element-level)

check_canon assembles output in two streams:

1. **Always-fresh scene state** (`result` list) — location, present characters, recent beats, mood, next-expected, the classified **SECRETS / DM-Knowledge** blocks, and prep. Live or load-bearing state that must never be stale, so it is never deduplicated and ships in full each call. Day/bell/location are ground-truthed in CURRENT_STATUS and are **never folded**; the classified secrets/DM-knowledge are deliberately kept fresh (smallest reward, highest staleness risk). Two always-fresh continuity caps trim runaway length without changing what is delivered: each `RECENT BEATS` line is capped at **220 chars** (`server.py` ~3923), and the one-line header `Last beat:` glance-pointer is capped at **140 chars** (~4772, the full beats already follow in `RECENT BEATS`).
2. **Delta-delivered canon** (`dedup_elements` list) — repeated reference blocks that bloat the window: per-character voice guides, per-character relationships, per-species/per-rule rules-in-play, per-NPC conversational context, both distillation blocks (cache + ingested) per entry, the **EMOTIONAL STATE table and ARC** scene blocks (`scene_state.scene_dedup_elements`), and the per-keyword **CONTEXT lorebook bios** (`scene_state.context_dedup_elements`). Each is a keyed element `(section, key, content)` routed through `canon_delivery.filter_elements`. Both distillation lanes apply two hygiene filters before queueing a nugget: `_is_placeholder_nugget()` (`server.py` ~3296) drops empty / `<UNKNOWN>` / placeholder payloads (one such broken nugget had been shipping every turn), and the **ingested (semantic) lane skips any `topic_key` already queued by the cache lane** (`_cache_nugget_keys`, ~4618) so a fact never double-ships across lanes. Nuggets are **not** length-truncated: their payloads are fact-dense (a real canon fact routinely sits 900–1,150 chars in), so a length cap drops 2nd/3rd facts and costs recall — verified against the 259-case recall harness, where a 400-char cap caused CAUGHT→MISSED regressions.

`canon_delivery.filter_elements(elements, hook_state)` (pure module, unit-tested in isolation) ships an element's full content only when it is **new**, its **content hash changed**, or it is **stale** (≥30 turns since last delivery). Otherwise it collapses to a compact pointer under an `**[IN CONTEXT — already delivered this session]**` footer (e.g. `VOICE: Mira ✓T3`). A key repeated within a single call keeps its first occurrence. Per-element delivery state lives in `hook_state['canon_delivered']` (`{key: {"h": hash, "t": turn}}`).

**Scene/CONTEXT folding** (`scene_state.py`, pure + unit-tested; 2026-06-02 window diet) routes the static scene blocks and lorebook CONTEXT matches into `dedup_elements`: ARC under key `scene:arc`, the emotional table under `scene:emotional_state`, and each lorebook bio under `lore:<first-keyword>`. `context_dedup_elements` **groups all lines sharing a keyword into a single element** (distinct lines joined in first-seen order, exactly-identical lines collapsed) so the in-call key-dedup can never drop a distinct entry — this is a presentation-only fold, never ground-truth loss. Sections listed in `canon_delivery.RECOVERABLE_SECTIONS` (`{"CONTEXT"}`) render their folded pointers with a **self-healing recovery call** — e.g. `mira ✓T40 ↻ lorebook(view, mira)` — so a stale pointer left by a missed compaction still gives the DM a one-call recovery path. Measured impact on a 42-call session: EMOTIONAL STATE 82%, CONTEXT 39%, combined ~60% fewer window chars on the folded blocks (`scripts/measure_canon_diet.py`).

Reset semantics:
- **Session-start** — `hooks/turn_reset.py` clears `canon_delivered` (fresh session, fresh window).
- **Compaction** — `hooks/post_compact.py` clears it (gameplay path), and `filter_elements` independently re-ships everything when it detects a turn-count regression (belt-and-suspenders).
- **30-turn backstop** — any single element re-ships if it has not been delivered in 30 turns, guarding against drift.
- **Normal turns** — preserved, so already-delivered elements stay deduped.

The final assembly re-reads hook state immediately before filtering (so `injected_npcs` written earlier in the same call survives the `_write_hook_state`), and is **fail-open**: any error in the delta path falls back to concatenating all element content in full. A read tool must never starve canon on a bug.

A per-turn telemetry line is logged at INFO via `filter_elements_with_stats`: `canon_delta needs=<blocks> fresh=<n> pointers=<n> always_fresh=<n>` — counts only, no canon content.

> Legacy note: the prior `_check_canon_dedup_blocks()` single-`'composite'`-block hashing is retained in `server.py` but is no longer wired into check_canon (kept one cycle for rollback). Its weakness — any change re-shipped the whole monolith — is what element-level delta delivery replaces.

### Book-Lore Canon Layer (2026-07-13)

check_canon carries a second, **read-only** match source beneath the campaign lorebook: the engine-shipped Crimson Hound world-lore file `data/rules/rulebook/lore_additions.json` (v2.2.0, 170 entries, 6 flagged `scene_inject: false`). The layer exists because the lorebook scaffolds **empty** for new campaigns — without it a fresh table's DM narrates with zero automatic world grounding even though the facts ship in the plugin. Design spec: `docs/superpowers/specs/2026-07-12-book-lore-canon-layer-design.md`.

Mechanics (all verified against the shipped code):
- **Pure leaf module `book_lore.py`** (imports stdlib `re` only, never server): `book_entries(raw)` converts lore entries into the lorebook entry shape (`category="book"`, `status="CH"`, `short_context` mirrors text ≤500 chars) and skips `scene_inject: false` (referee advice — the `rulebook` tool still serves those); `match_book_entries(entries, input_lower, campaign_keywords, broad_kw)` word-boundary-matches with the campaign scan's exact semantics and tuple shape. Fail-open is **per-entry**: one malformed row is skipped, the rest survive.
- **Campaign canon always wins, two ways.** (1) *Subject-coverage suppression:* a book entry sharing ANY keyword with any campaign lorebook entry never matches — the campaign owns that subject outright, whether or not its entry matched this turn. (2) *Budget priority:* book matches render after all campaign matches, under `BOOK_CONTEXT_CAP = 3` (`server.py` ~4481), inside the overall `CONTEXT_CAP = 8`; broad-token book matches render only under lore intent, capped to the leftover book budget.
- **Escalation-inert:** book matches never feed `matches`/`specific_matches`, so they cannot trigger auto-FULL (`lorebook_match_count` counts campaign matches only).
- **Rendering** rides the existing pipeline unchanged: lines emit as `[BOOK] **<first keyword>** (CH): …`, >500-char text goes through `_smart_truncate_lorebook_entry`, and lines fold via `context_dedup_elements` like any lorebook bio.
- **Fail-open, three layers:** `_load_cached_json` (no fixed cache key — default `str(path)`, so a repointed `RULES_DATA_DIR` can never serve a stale copy) → the module's per-entry guards → an outer `except` that zeroes `book_matches`. Missing/corrupt file ⇒ output identical to pre-layer behavior. The NO-MATCHES escalation reminder fires only when campaign AND book both matched nothing.
- **No campaign file is ever written.** Book facts have one home (the shipped file); engine-side fixes reach every table on update. Trigger-word hygiene is guarded by `tests/test_book_lore_layer.py` (`_GENERIC_DENY` denylist, `_META_IDS` sync, shape/uniqueness); entry texts are PDF-verified (Crimson Hound printed pages — the Sable Gecko batch extraction is a locator only).

### Reveal Discipline (2026-07-16)

Engine-enforced reveal discipline — born from the D134 Thyricost session (an NPC spoke a DM-only name; room payloads firehosed discovery). Player-directed; spec `docs/superpowers/specs/2026-07-16-reveal-discipline-design.md`. Three surfaces (all verified against shipped code):

- **Revealed Ledger (engine state).** `revealed_ledger` list in each site's map-state JSON (`maps/<name>_map.json`), entries `{"fact" (≤300c), "day", "source_room", "source_action"}`, written only by `map_system._ledger_append`. Auto-appended: `enter_room` first visit ("Entered <room>"), `search_room` ("Searched <room>" + loot names), `reveal_secret` (the discovery line). Explicit lever: `map(action="reveal", map_name=..., fact=..., room_id?)` → `MapSystem.reveal_fact` — the DM calls it the moment the party learns a fact socially/by deduction. On vault turns (`_active_vault_turn()` non-None) check_canon appends `_revealed_ledger_injection()` (placed after the no-matches/escalation logic, next to the site-features block): newest 8 facts + "(+N earlier)" + the charter (*NPCs may assert ONLY these facts; off-ledger they speculate and may be WRONG; unledgered names are unspeakable*) + the map(reveal) push. Empty ledger still renders the charter. Whitelist-by-construction: only reveal paths and neutral markers ever write it.
- **DM-only name tripwire (validate_prose).** `_vp_check_dm_name_leaks` runs in the deterministic block right after `_vp_check_tripwires`, only when there is an active vault AND a resolvable active prep (`_resolve_active_prep_path`: `GAME_STATE["active_prep_file"]`, falling back to CURRENT_STATUS `**Active Prep:**`). `_dm_only_proper_nouns(prep_path)` extracts proper nouns appearing ONLY in DM-only content: player side = `_filter_dm_only_content(...)` **plus** header-style DM sections cut by regex (`## DM ONLY — …` / `## DM KNOWLEDGE` / `## … (GM KNOWLEDGE ONLY)` through the next h2) — that extra cut is load-bearing: the ⛔-block filter alone sees zero DM content in live-convention preps. Candidates come from body lines only (headers are structure), possessives normalize, any word that ever appears fully lowercase in the prep is dropped (common noun), and `_DM_NAME_STOPWORDS` carries a common-English band (bias: false positives block play; false negatives just mean one exotic name isn't machine-guarded). Nouns already in the ledger pass. Violation text carries the `map(action="reveal", ...)` remediation. Cache keyed (path, mtime, ledger length); fail-open everywhere; deterministic — no judge model.
- **Paced room delivery.** `location_content` gains `first_glance`/`inspection` views of the obvious tier: an explicit `### First Glance` subsection (`_section_tier` → "glance") IS the glance layer (all Observables become inspection); otherwise the first paragraph of each obvious body is the glance and the rest is inspection. Plain `"obvious"` behavior is unchanged for other callers (glance sections additionally render there so nothing is lost). `enter_room` serves glance + `[DM]` notes + a render-ONE-finding discipline push naming `map(action="look")`; `look_room` / `map(action="look", room_id?, feature?)` serves inspection detail with **no turn cost** (feature= scopes to matching paragraphs; unknown feature hints a search); `search_room` carries the same discipline line. `validate_prep_file` recognizes First Glance as a reveal-tier header and NOTEs single-paragraph Observables (pacing-poor). Conventions: `docs/PREP_FILE_SCHEMA.md` "First Glance" + content-forge's room template (authors First Glance natively; new preps must NOT hand-author REVEALED LEDGER markdown — discovery tracking is engine state).

Tests: `tests/test_reveal_ledger.py`, `tests/test_dm_name_leak.py`, `tests/test_paced_delivery.py`.

### Error Handling

Fail-open philosophy: nearly every injection block is wrapped in `try/except` that catches Exception and passes silently. check_canon never crashes — it degrades gracefully by skipping non-critical injections. ChromaDB failures, missing files, and embedding errors all skip silently.

<!-- REVIEWED AND CORRECTED 2026-05-29 — shopping list redesign implemented. RE-VERIFIED 2026-05-29: check_canon line numbers re-anchored to current code (def at 3561, body 3561-4721, decorator 3557, helpers ~3337-3556; prior "3636-4808 / helpers 3459-3635" was stale). Parameters, auto-light mode, dedup logic (10-turn staleness), lorebook word-boundary regex, ChromaDB tier ordering (distillations first), canon_blocks definition, regex fallback mapping — all verified against code. -->

<!-- REVIEWED AND UPDATED 2026-05-31 — check_canon delivery rewritten from single-'composite'-block dedup to element-level delta delivery (canon_delivery.py: filter_elements / filter_elements_with_stats). Voice (per-character + core_rules + bond), relationships (per-char), rules-in-play (per-rule), conversational context (per-NPC), and both distillation blocks (per-entry) now ship only on first-delivery / content-change / 30-turn-staleness; already-delivered elements collapse to an [IN CONTEXT] pointer footer. State: hook_state['canon_delivered'], reset on session-start (turn_reset) + compaction (turn regression in-filter + post_compact). Always-fresh scene state (location/present/beats/mood/arc/emotional table/secrets/prep) bypasses the filter. Final assembly re-reads hook state before filtering so injected_npcs survives; fail-open fallback ships full content on any error. Stats logged per turn (needs/fresh/pointers/always_fresh). Legacy _check_canon_dedup_blocks retained unused pending one-cycle rollback window. Full tests/ suite green (577 passed, 1 skipped); 2 pre-existing collection errors (test_sonnet_observer, test_tiered_search) reference missing modules, unrelated. -->

<!-- REVIEWED AND UPDATED 2026-06-06 (signal-to-noise tuning loop) — measured the full check_canon output through a real-engine harness (rubicon-seven-mcp/scripts/canon_recall_live.py: drives the actual check_canon over all 259 recall cases, resets the per-turn fold so each renders worst-case fresh, captures recall AND token volume). Baseline worst-case ~1,896 tok/turn; real session-mode (fold active) ~1,242 tok/turn (scripts/canon_session_volume.py). SHIPPED (server.py, recall-verified): (1) `_is_placeholder_nugget` drops empty/`<UNKNOWN>` nuggets in BOTH distillation lanes (~3296, called at the cache lane ~4625 and the ingested lane ~4703) — a broken nugget had been shipping in 100% of turns; (2) cross-lane dedup — ingested lane skips any topic_key already queued by the cache lane (`_cache_nugget_keys` ~4618); (3) RECENT BEATS per-line cap 220c (~3923) + header Last-beat cap 140c (~4772). Net −7.5% worst-case volume, recall held by construction (deterministic 0 canon-term losses across all 210 non-MISSED cases + LLM spot-check). REJECTED with evidence (do not retry): nugget length-truncation (fact-dense; any volume-meaningful cap caused CAUGHT→MISSED), and reordering `_query_distillation_cache` to prioritize input-mention hits (ballooned volume +17% by pulling long relationship/history nuggets — input-mention is kept LAST deliberately, ~3499). EMOTIONAL STATE was confirmed ALREADY folding via scene:emotional_state (the apparent per-turn injection was a worst-case-harness artifact, not live behavior). Inert until MCP restart. Changelog: rubicon-seven-mcp/tests/results/2026-06-06-tuning-changelog.md. -->

<!-- REVIEWED AND UPDATED 2026-06-02 (v8.9.3, check_canon window diet, MCP merge 53b05e3) — extended delta delivery to the static-ish scene blocks and lorebook CONTEXT bios. ARC + EMOTIONAL STATE moved OUT of the always-fresh result list INTO dedup_elements via new pure module scene_state.py::scene_dedup_elements (keys scene:arc / scene:emotional_state). Per-keyword CONTEXT lorebook bios moved into dedup_elements via scene_state.py::context_dedup_elements (key lore:<first-keyword>); that helper GROUPS all lines sharing a keyword into one element (distinct lines joined, exact dups collapsed) so the filter's in-call key-dedup cannot drop a distinct same-keyword entry — presentation-only fold, no content loss (fixed in commit 223a577 after review caught the drop). canon_delivery.py gained RECOVERABLE_SECTIONS={"CONTEXT"} → folded CONTEXT pointers carry a self-healing "↻ lorebook(view, <kw>)" recovery call. CORRECTED the prior always-fresh list: ARC and the EMOTIONAL STATE table now FOLD (no longer always-fresh); day/bell/location still never fold; classified SECRETS/DM-Knowledge deliberately stay always-fresh. Compaction reset re-verified (post_compact.py + turn_reset.py both clear canon_delivered; blocking gate test asserts wiring+behavior). Anti-hallucination guards (blacklist/validate_prose/fabrication_bans) untouched. Measured EMO 82% / CONTEXT 39% / combined ~60% over a 42-call session (scripts/measure_canon_diet.py). Spec+plan under MCP docs/superpowers/. tests/ green: 601 passed, 1 skipped, 1 pre-existing unrelated failure (test_antagonist_cultivation, identical on main). -->

---

## 4. Hook Chain

### Hook Files and Execution Points

| Hook Point | File | Purpose |
|------------|------|---------|
| UserPromptSubmit | `turn_reset.py` | Reset per-turn state, scene fingerprinting, canon requirement decision |
| UserPromptSubmit | `phrase_reminder.py` | Inject discipline reminders, bell tracking, semantic priming with specific caught phrases |
| PreToolUse | `gate_check.py` | Block gated tools, track canon verification, enforce validate_prose |
| PostToolUse | `spoiler_check.py` | Validate check_canon output, set canon_succeeded flag |
| PostToolUse | `verify_save.py` | Verify save content against transcript, block if unverified claims found |
| PostResponse (Stop) | `consolidated_stop_check.py` | 16 checks (one blocks — dm-design review gate; the rest diagnostic/advisory), analytics logging, observer spawn |
| PostCompact | `post_compact.py` | Re-inject validate_prose requirement after context compaction |

**Support files:**

| File | Purpose |
|------|---------|
| `hook_utils.py` | Shared utilities, state management, file locking, STATE_CHANGING_TOOLS constants |
| `blacklist_evolver.py` | Evolution cycle — grows blacklist.json from catch analytics at session-end, prunes old catches |

### Prose-Tic Policing (2026-07-19)

A 58.5k-word audit of the Thyricost leg proved the prose had **mutated around its own bans** —
"the way X \<verbs\>" (66×), participle/bare-appositive variants of the banned "the X of a Y
who/that" template (24×), "a (very) long time" (19×), "a stillness with contents" (5×) — while
27 exact-banned phrases reached live output. Four coordinated changes:

1. **blacklist.json v9** — five mutation-family `structural_patterns` (regexes FP-validated
   against the transcript corpus) + "four thousand years"/"through the bond" in use_sparingly.
   Consumed by `narrative_qa(validate)` (`_load_prose_patterns`, mtime-cached).
2. **judge_prompt.txt** — categories 3/4/6 name the re-lexicalized variants; category 10 adds
   the **portent-closer** flag (turn-final standalone mood-fragment ≲8 words).
3. **Unconditional Stop-hook backstop** — `_check_anti_pattern`'s validate_prose_required branch
   no longer early-returns (commit 173999d had switched the deterministic scan OFF on exactly
   the turns that skipped self-validation); it arms the flag and falls through. Regression:
   `tests/test_antipattern_backstop.py`.
4. **Template nominations (the durable fix)** — the Stop hook appends substantial gameplay turns
   to a capped campaign-scoped corpus (`rubicon_paths.prose_window_path`, 200 turns);
   `_run_prose_evolution` (save-commit) feeds it to `blacklist_evolver.run_template_scan`, which
   slot-normalizes prose (proper nouns→`<N>`, pronouns→`<P>`), counts recurring 3–5-token frames,
   and NOMINATES over-threshold frames not already covered by existing regexes into blacklist.json
   `template_nominations` (`status: "pending"`, owner review — never auto-ban). This catches the
   NEXT mutation without a human noticing first. Tests: `tests/test_template_detection.py`.

**Defenses-before-harm** (same date, owner ruling from the D134 memory-eater retcon):
`_standing_defenses_injection` (server.py, wired into check_canon beside the Revealed Ledger)
surfaces on vault/combat turns every roster item/augment/gift whose effect matches defensive
markers, capped at 12 lines, with the charter: a strike a listed defense answers is narrated as
ANSWERED — never written as landed and retconned. Tests: `tests/test_standing_defenses.py`
(incl. live-roster count probe). Judgment-side counterparts live in the campaign repo's VOICE.md
(speaker/wit/flattery budgets) and SCENE_FRAMING_GUIDE.md (action-termination, closer-variety,
simile-budget, inert-texture rules).

### Shared State

All hooks share state via `.hook_state.json` in the hooks directory, managed by `hook_utils.py`.

**State schema with defaults:**

```json
{
  "canon_verified": false,
  "canon_succeeded": false,
  "session_started": false,
  "context_reminded": false,
  "force_all": false,
  "turn_count": 0,
  "scene_fingerprint": "",
  "scene_changed": true,
  "skip_canon_enforcement": false,
  "session_type": "development",
  "session_vocabulary": [],
  "canon_required": true,
  "lorebook_required": false,
  "lorebook_triggers": [],
  "lorebook_called": false,
  "verified_npcs": [],
  "validate_prose_called": false,
  "validate_prose_required": false,
  "catch_count": 0,
  "catch_log": {}
}
```

Deprecated and removed: `last_stop_blocker`, `approved_hooks` (were part of the rewrite-cycle architecture, eliminated in the hook chain redesign).

**File locking:** `.hook_state.lock` file with exclusive creation, 5-second timeout, 10-second stale lock detection. Retry interval: 10ms.

**Atomic save:** Write to `.tmp` file, then `os.replace()` for atomic rename.

**Shared constants in hook_utils.py:** `STATE_CHANGING_TOOLS` (12 tools), `NON_STATE_ACTIONS`, `TOOL_LABELS` — shared between validate_prose (server.py) and the stop hook for prep-file-progress gating.

### turn_reset.py — Scene Fingerprinting and Canon Gating

**Scene fingerprint computation:**
1. Read CURRENT_STATUS.md
2. Extract `**Location:**` and `**Present:**` via regex
3. Normalize: location lowercased; present names split by comma, lowercased, sorted alphabetically
4. Hash: `MD5("{location}|{sorted_present}")[:12]`
5. If file unreadable: empty string (treated as "scene changed")

**Canon requirement decision tree:**

```
Scene changed? ──────────────────────────── YES → require canon
                                              │
Admin command or parenthetical (...)? ─── YES → skip canon
                                              │
Turn ≤ 3? ───────────────────────────────── YES → require canon
                                              │
Turn % 3 == 0? ──────────────────────────── YES → require canon
                                              │
                                            NO → skip canon
```

**Per-turn reset (non-retry turns):**
- `canon_verified` → False
- `canon_succeeded` → False
- `lorebook_required` → recomputed from keyword extraction
- `lorebook_triggers` → recomputed
- `lorebook_called` → False
- `force_all` → recomputed from /all detection
- `verified_npcs` → []
- `validate_prose_called` → False

**Persistent across turns:** `session_started`, `session_type`, `session_vocabulary`, `catch_count`, `catch_log`, `turn_count` (incremented).

**Special commands:**
- `/all`: Sets `force_all: True`, shows all tools regardless of context filtering
- `/fp`: Calls `mark_false_positive()` — a retired no-op since `corrections.json` was neutralized (§5/§12); the call is safe but writes nothing
- `/session-start`: Resets session_type to "gameplay", clears vocabulary and catch counts

### gate_check.py — Tool-Level Access Control

**Decision tree for each tool call:**

```
Is tool check_canon? ─── YES → set canon_verified=True, allow
                              │
Is tool lorebook/npc? ──── YES → record target in verified_npcs (fall through — NOT allowed yet; gating continues below)
                              │
Is tool full_session_startup? ── YES → set all flags True, allow
                              │
validate_prose_required? ─── YES → Is tool validate_prose? → clear flag, allow
                              │         │
                              │    Not maintenance? → BLOCK ("call validate_prose first")
                              │
Is Safety.GATED? ────────── YES → Is canon_required False? → allow
                              │         │
                              │    Gate A: canon_verified? → No → BLOCK
                              │         │
                              │    Gate B: canon_succeeded? → No → BLOCK
                              │         │
                              │       allow
                              │
Is session_started False? ── YES → BLOCK (unless Safety.ALWAYS)
                              │
                           allow
```

**Retired tier:** There is no `Safety.DANGEROUS` tier — it was deliberately removed. The `Safety` class defines only `ALWAYS` and `GATED`. The former DANGEROUS file-ops are now `GATED` (require check_canon). `tests/test_gating_removed.py` guards this: it asserts `Safety` has no `DANGEROUS` attribute and that `gate_check.py` contains no dangling `Safety.DANGEROUS` reference.

**Lorebook/npc lookups are recorded, not whitelisted:** When `lorebook` or `npc` is called, gate_check records the looked-up target in `verified_npcs` and then **falls through** to the normal gating logic — it does NOT allow-and-return. If the tool is GATED and check_canon hasn't succeeded this turn, the lookup is still blocked. The recording only persists which entity was queried (so the NPC-fabrication check survives stop-hook retries); it does not grant access.

### spoiler_check.py — Canon Output Validation

Only processes check_canon output. Other tools pass through immediately.

**Validation heuristics:**

| Check | Patterns | Result |
|-------|----------|--------|
| Error indicators | "Error:", "ToolError", "not found", "Could not read", "Could not load", "File not found", "Failed to", "Exception:", "Traceback" | Fail — canon_succeeded stays False |
| Success indicators | `"**PRESENT CHARACTERS:**"`, `"**[BLOCKS:"`, `"**[AUTO-LIGHT]**"`, `"**[LIGHT MODE]**"` (deprecated), `"**CONTEXT"`, `"Location:"`, `"Present:"` | Pass — canon_succeeded set True |
| Neither found | — | Fail |

**Spoiler injection:** If output contains "SECRETS" AND ("do not reveal" OR "dm only"), injects a boxed three-item reminder about keeping secrets classified.

### consolidated_stop_check.py — Diagnostic-Only Post-Response Layer

**Architecture:** Checks run linearly. Each returns `(blocked, reason, state_updates)`. State updates accumulate and are saved at the end — BEFORE any block fires, so armed state persists across a blocked stop. **One check blocks** (the dm-design review gate, Check 1b, added 2026-06-12 — reason on stderr, `sys.exit(2)`); every other check is diagnostic-only and returns `(False, "", state_updates)`.

The diagnostic-only posture remains deliberate for prose checks: the player should only ever see one version of each narrative response. All prose enforcement happens pre-delivery via validate_prose (Section 5); the soft checks log diagnostics that feed the next turn's phrase_reminder and the session-end evolution cycle. The dm-design gate is different in kind — it polices a WORKFLOW obligation (forged content must be reviewed), not prose, so blocking does not create rewrite artifacts.

#### Check 1: Canon Enforcement
- Skips if: maintenance mode, non-gameplay session, canon_required is False
- If canon_verified is False on a required turn: soft log only

#### Check 1b: dm-design Review Gate (BLOCKING — `_check_dm_design_gate`)

The runner's only blocking path (shipped 2026-06-12, content-forge revision; tests: `tests/test_dm_design_gate.py`, 41 tests).

- **Trigger:** a `*_PREP.md` file forged this turn arms `state["pending_dm_design"]` (`{file, set_turn}`). `Write` to any prep always arms (creating/overwriting is forging-scale, even on the active prep); Edit-family tools (`Edit`, `update_file`, `replace_in_file`) arm ONLY when the target matches none of the Active Prep tokens — `_active_prep_tokens()` parses every prep stem out of the CURRENT_STATUS Active Prep value (bare stems included), because `_check_prep_file` nudges a routine progress-log edit to the active prep every state-changing turn and that must never arm the gate. If the active prep is unresolvable, edit-family does not arm (only Write does).
- **Block:** while `pending_dm_design` is set (this turn or any earlier one), the stop blocks with `CONTENT FORGED, REVIEW PENDING: <file> ... NEXT: /dm-design integrate <file> (or say "skip review" ...)` and logs a hard correction.
- **Release:** an `Agent`/`Task` dispatch this turn whose DESCRIPTION contains `dm-design` or `dm narrative design` clears pending. Prompt text is deliberately not scanned — a stray mention inside a long prompt must not open the gate.
- **Skip:** `state["skip_dm_design_gate"]` (player said "skip review") clears pending and resets itself to False — one-shot waiver.
- **Bypass:** `maintenance_mode` or `skip_canon_enforcement` passes WITHOUT clearing pending (dm-design itself runs under maintenance mode and writes prep files; the review obligation survives maintenance work). Precedence per evaluation: bypass > release > skip > trigger/block.
- **Fail-silent:** any internal error passes without blocking and logs a breadcrumb to `hooks/observer_errors.log`.
- **Turn slicing (`_get_turn_messages`):** all tool-use scanning is sliced to THIS turn — everything after the last human user message, where a role-"user" message whose content blocks are all `tool_result` is NOT a turn boundary (`_is_human_user_message`). Dual-path transcript: prefers in-memory `transcript_messages` (tests/legacy callers), falls back to parsing the JSONL at `hook_input["transcript_path"]` (real Stop-hook stdin; `_load_transcript_file_messages` also tolerates a single JSON document). All soft checks now share this path: `_hydrate_transcript_messages()` (top of `main()`) populates `hook_input["transcript_messages"]` once from `_get_turn_messages` when real Stop-hook stdin provides only `transcript_path`, so the legacy direct readers (response-text fallback, narrative classifier, state-changing-tool scan, canon-was-called, NPC tool-target scan) run live off one shared tail-read; a caller-provided non-empty `transcript_messages` is left untouched, fail-open on any problem (shipped 2026-06-12; tests/test_stop_checks_transcript_port.py).
- **State preservation:** `turn_reset.py` now carries `pending_dm_design`, `skip_dm_design_gate`, and `maintenance_mode` across turn resets, so an armed gate survives until released or waived.

#### Check 2: Anti-Pattern Blacklist
- Loads `blacklist.json`: 90 blacklisted phrases + 34 use-sparingly + 5 protected + 5 structural patterns = 134 total (canonical split — the other §5 mentions of this count point back here)
- Each phrase compiled as case-insensitive word-boundary regex
- **Blacklisted**: Any match → soft log, increment catch_count
- **Use-sparingly**: First use in session → phrase added to session_vocabulary. Second use → soft log.
- If `validate_prose_called` is False and response > 200 chars: logs a warning
- Catch data feeds `catch_analytics.json` for the evolution cycle

#### Check 3: Semantic Observer Spawn
- Determines if turn is "narrative" (not maintenance, turn > 3, response > 300 chars, tool calls < 50% of content)
- If narrative: spawns prose_observer.py as detached subprocess (Haiku 4.5)
- Writes response text to `/tmp/rubicon_observer_{session}_{turn}.json`
- Observer results feed phrase_reminder on the next turn

#### Check 4: Prep File Progress
- Gets active prep filename from CURRENT_STATUS.md
- Scans for state-changing tool calls (12 tools in STATE_CHANGING_TOOLS, imported from hook_utils.py)
- Filters out read-only actions (npc:get, map:render, character:get, etc.)
- If state-changing tools used BUT prep file NOT edited this turn: **soft log** (enforcement moved to validate_prose step 9)

#### Check 5: Lorebook Gap
- Required when `lorebook_required=True` (set by turn_reset based on keyword extraction)
- If lorebook(view) was called this turn: passes
- Otherwise: soft log ("LOREBOOK GAP")

#### Check 5b: NPC Fabrication
- Skips short responses (<100 chars), maintenance, non-gameplay, meta-discussion
- Loads NPC names from npc_states.json
- Excludes party members, present characters, and common English false positives ("quill", "sage", "veil", etc.)
- For each NPC mentioned without verification: soft log

#### Check 5c: In-Dialogue Fabrication (`hooks/dialogue_claim_scanner.py`)
- Scans quoted dialogue for factual claims:
  - Duration claims (number + time unit, including word-form numbers)
  - Quantity claims (number + noun)
  - Date references ("Day 122", "the 17th")
  - Relationship verbs (29 verbs like "married", "betrayed", "trusted")
- Cross-references claims against distillation cache
- Unverified claims: soft log

#### Check 6: Backstory Hallucination
- 10 compiled regex patterns matching false backstory insertion (two quoted-dialogue patterns were intentionally removed — dialogue is stripped before scanning, so they were dead code):
  - "the first time we met", "remember when we", "we used to", "back when we", "since that day", etc.
- Pre-filter: strips quoted dialogue and italicized bond text before scanning
- Only matches ≥ 20 chars count
- If patterns found AND check_canon was NOT called this turn: soft log

#### Check 7: Vault Liveness (`_check_vault_liveness`)
- While a vault's `vault_enforce` gate is armed, every narrative turn must advance the armed map's `current_turn` past `vault_enforce.last_turn` (only `map(enter|search|wait)` satisfies it). A non-satisfying narrative turn sets `vault_action_required=True`, which blocks tools next turn until a map action lands.

#### Check 8: Settlement Change Nag (`_check_settlement_change_nag`)
- Advisory-only: prints a reminder when a settlement change is narrated but not stamped via the settlement tooling this turn.

#### Check 9: Uncrystallized Names (`_check_uncrystallized_names`, C24)
- Advisory-only: prints one quiet line when a named-but-unrecorded proper noun recurs across ≥2 turns, suggesting the DM crystallize it (npc/lorebook). Carries per-name turn counts across turns.

#### Check 10: Ceruline Reconcile Nudge (`_check_ceruline_reconcile_nudge`)
- Advisory-only: a session-end nudge to reconcile the Ceruline settlement reader against canon. Carries `ceruline_seen_session` across turns.

#### Check 11: Stale Parley Nudge (`_check_stale_parley_nudge`, 2026-07-04)
- Advisory-only: prints one line per OPEN parley that has gone quiet ≥7 campaign days.

#### Check 12: Prose-Dice Watcher (`_check_prose_dice`, 2026-07-04)
- Advisory-only: prints one line when dice resolution is narrated but no dice-capable engine tool (`roll`/`test_dice`/`combat`/`map`) ran this turn.

#### Check 13: NPC Continuity (`_check_npc_continuity`)
- Never blocks: unions NPCs named this turn into `open_npc_scene`, which `gate_check.py`'s NPC-boundary gate later enforces (cleared only by `npc(action="continuity")`).

### blacklist_evolver.py — Self-Improving Blacklist Growth

Runs at session-end as part of maintenance. Reads catch_analytics.json and corrections.json, identifies recurring patterns, and writes new entries to blacklist.json.

**Thresholds:**
- New phrase → `use_sparingly`: 3+ catches across 2+ sessions
- `use_sparingly` → `banned`: 5+ additional catches after being added
- Stale flag: not caught in 10+ sessions (logged, not auto-removed)

**Functions:** `find_promotion_candidates()`, `find_tier_promotions()`, `find_stale_phrases()`, `apply_evolution()`, `run_evolution()`.

**What the player sees:** Nothing. Silent at session-end. The only visible effect is that next session, validate_prose catches things it didn't catch before.

<!-- REVIEWED AND CORRECTED 2026-05-31 — §4 parity pass: line counts re-derived from live code (turn_reset 316, gate_check 124, consolidated_stop_check 1039, post_compact 54, hook_utils 345, blacklist_evolver 151); phantom Safety.DANGEROUS branch removed (tier retired, guarded by tests/test_gating_removed.py); lorebook/npc lookup clarified (records, falls through — not allow-and-return); STATE_CHANGING_TOOLS 12; blacklist 78 banned + 46 use_sparingly; relationship verbs 29; backstory patterns 10.
     REVIEWED AND CORRECTED 2026-05-28 — hook chain redesign + re-verified by agent swarm. blacklist_evolver line count corrected (137→145, prune integration). State schema note: DEFAULT_STATE in hook_utils.py is partial; full schema constructed by turn_reset.py at runtime. Stop hook diagnostic-only confirmed (all 8 checks return False). gate_check decision tree verified. PostCompact verified. -->

---

## 5. Prose Quality Stack

Four layers. Only the first can block delivery. Everything else is diagnostic.

**Design philosophy:** The player should only ever see one version of each response. All enforcement happens pre-delivery via validate_prose. Post-delivery layers exist to log diagnostics that feed the next turn's awareness and the session-end evolution cycle.

### Layer 1: validate_prose (MCP Tool) — The Gate

Called by Claude before outputting narrative. The single pre-output quality gate. If it flags violations, Claude rewrites in its thinking block before delivery. The player never sees the flawed version.

**Three-layer enforcement (if Claude forgets to call it):**
1. **Tool description** — says "REQUIRED" and "enforced by gate_check." Survives compaction (loaded on demand from MCP server).
2. **PostCompact hook** — re-injects the validate_prose requirement into context immediately after compaction (the primary cause of skips).
3. **gate_check enforcement** — if validate_prose was skipped on a narrative turn, the stop hook sets `validate_prose_required: True`. Next turn, gate_check blocks ALL MCP tools until validate_prose is called. One unfiltered turn max, then hard-locked.

**Pipeline (runs in order, skips Haiku if earlier deterministic checks catch violations):**

| Step | Check | Source | Cost |
|------|-------|--------|------|
| 1 | Fabrication-ban scan | fabrication_bans.json — hard-block on any draft that re-asserts a permanently corrected error (entity + wrong-term pairs); runs first, cheapest and certain | ~0ms |
| 2 | Literal blacklist scan | blacklist.json — banned phrases (current split at §4 Check 2), case-insensitive word-boundary regex | ~0ms |
| 3 | Structural regex scan | blacklist.json `structural_patterns` — 5 pattern-level checks for negation-correction across sentence breaks, characterization formulas, freeze/lock synonyms | ~0ms |
| 4 | NPC mention verification | Cross-reference NPC names against check_canon injection, lorebook/npc tool calls, Present field | ~0ms |
| 5 | Backstory hallucination patterns | 10 regex patterns for false memory insertion ("the first time we met", "remember when we", etc.) | ~0ms |
| 6 | In-dialogue factual claim scan | Duration, quantity, date, relationship claims inside quoted dialogue vs distillation cache | ~5ms |
| 7 | Deterministic widening checks | Pet-name, tripwire, and narration-claim scans (`fabrication_detectors`) — catch bond pet-names, tripwire violations, and unsupported narration assertions | ~0ms |
| 8 | Haiku semantic review | API call — draft text + 11 violation categories, forced tool-use schema. **Only runs if ALL prior deterministic checks (steps 1-7) found nothing.** | 1-3s |
| 9 | Prep progress check | If state-changing tools used this turn, remind to update prep progress log | ~0ms |

**Step 8 (Haiku semantic review) details:**
- Model: Haiku 4.5 (`claude-haiku-4-5-20251001`)
- Timeout: 5 seconds (faster than the post-delivery observer's 30s — latency matters pre-delivery)
- Fail-open: returns empty list on any error (no API key, timeout, parse failure)
- Filters to high/medium confidence violations only
- Same tool schema and violation categories as the post-delivery observer

**Use-sparingly phrases:**
Allowed once per session, then flagged on second use (current count at §4 Check 2). Includes: "weighted pause", "eyes meet", "small smile", "without looking", "half-smile", "unhurried", "deliberately", "architecture of", "the particular", and several body-action patterns. Tracked via `session_vocabulary` in hook state.

### Layer 2: consolidated_stop_check Blacklist — The Diagnostic Logger

Runs the same blacklist scan post-delivery, logging to `catch_analytics.json`. **Never blocks.** Exists to catch anything validate_prose missed and feed the evolution cycle. (`corrections.json` is a retired no-op — see §12 Corrections Log.)

**Blacklisted phrases — illustrative categories:**

> Note: `blacklist.json` stores `blacklisted_phrases` as a flat list with no per-category metadata (current count at §4 Check 2). The grouping below is a hand-maintained editorial illustration of the *kinds* of phrases banned; its rows predate recent additions and do not sum to the live total. Treat it as a flavour map, not an authoritative count.

| Category | Count | Examples |
|----------|-------|---------|
| Freeze/stillness | 12 | "goes still", "went rigid", "muscles lock", "froze in place" |
| Breathing-as-shock | 6 | "breath catches", "exhales slowly", "lets out a breath" |
| Duration padding | 3 | "for a long moment", "for what feels like" |
| Voice modulation | 7 | "voice quiet", "barely a whisper", "voice drops" |
| Vague facial signal | 4 | "expression softens", "face softens", "gaze softens" |
| Something shifts | 2 | "something shifts", "something passes between" |
| Weight/settling | 3 | "the weight of", "settles like", "lands like" |
| Hanging words/silence | 9 | "words hang in", "hangs in the air", "silence stretches" |
| Eye contact | 5 | "eyes find hers", "holds her gaze", "searches his face" |
| Time/world shrinking | 3 | "time seems to", "world narrows", "everything fades away" |
| Structural/formulaic | 5 | "you're not just X, you're", "it's not just X, it's" |
| Characterization formula | 1 | `the \w+ of (a|an) \w+ (who|that)` (regex) |
| Negation-correction | 3 | `not .{1,40}[,;—] (but)? the/a/an...` (regex) |

**Structural patterns (5):** Negation-correction across sentence breaks (2 variants), expanded characterization formula, double-negation-affirmation, freeze/lock structural synonyms. These catch rephrasings that bypass the literal blacklist.

**Protected phrases (5):** A short allowlist (`blacklist.json` `protected_phrases`) that the blacklist evolution cycle must never auto-promote into the banned list, even if analytics flag them as frequent — `blacklist_evolver.py` skips any candidate in this set. Rounds out the four `blacklist.json` categories — current split at §4 Check 2 (protected and structural stay fixed at 5 each; total 134).

### Layer 3: prose_observer — The Deep Diagnostic

**Model:** Haiku 4.5 (`claude-haiku-4-5-20251001`)
**Invocation:** Detached subprocess, fire-and-forget (from stop hook Check 3)
**API call:** Forced tool-use with `record_violations` schema
**Max output:** 1024 tokens
**Timeout:** 30 seconds

Separate from the pre-delivery Haiku call in validate_prose (step 8). The observer runs post-delivery with a longer timeout for deeper analysis. Both use the same 11 violation categories but serve different purposes: validate_prose gates output, the observer provides richer diagnostic data.

**11 Violation Categories:**

| Category | What It Catches |
|----------|----------------|
| Reaction Shot | Freeze-and-lock language, respiratory interruption, petrification metaphors |
| Emotional Beat | Vague signal-words on face/voice, abstract emotional labels |
| The Pause | Treating silence as an actor that stretches/hangs/descends |
| Transition | Duration-padding phrases, adverbial softeners, announcing shifts |
| Landing | Impact metaphors, words treated as physical objects that strike/settle |
| Characterization | Abstract quality via relational formula, "the X of a Y who/that" |
| Negation-Correction | Defining by what it is NOT before stating what it IS |
| Voice Modulation | Vocal-adjective delivery tags, "voice soft/quiet/rough" |
| Travel Math | Fabricated distances, travel times without geography tool |
| Density Drift | Prose thinning — too many short sentences without substance |
| Synthesis Incoherence | Contradictions between narrative and established canon |

**Feedback loop:** Results written to `catch_analytics.json`. On the NEXT turn, `phrase_reminder.py` reads this file and surfaces the top 3 semantic categories plus specific caught phrases (with quotes) as part of its discipline injection.

**Firing criteria:** Not maintenance, turn > 3, response > 300 chars, tool-call blocks < 50% of content blocks.

**Cost:** One Haiku API call per narrative turn. Always exits 0 (fail-open). Errors logged to `observer_errors.log`.

### Layer 4: blacklist_evolver — The Growth Engine

Runs at session-end as part of maintenance. Reads `catch_analytics.json`, identifies recurring patterns, and writes new entries to `blacklist.json`.

**Thresholds:**
- New phrase → `use_sparingly`: 3+ catches across 2+ sessions
- `use_sparingly` → `banned`: 5+ additional catches
- Stale flag: not caught in 10+ sessions (logged, not auto-removed)

**Effect:** The blacklist grows over time without manual intervention. Patterns that I keep reaching for despite nudges get permanently added to the pre-delivery gate. The system gets smarter each session.

### Enforcement Summary

| Layer | When | Blocks? | Data Written |
|-------|------|---------|-------------|
| validate_prose (9 steps) | Before output (called by Claude) | Yes (pre-delivery gate) | hook_state (`validate_prose_called` flag) |
| gate_check enforcement | Next turn (PreToolUse) | Yes — blocks all MCP tools if validate_prose was skipped | hook_state (`validate_prose_required` flag) |
| PostCompact hook | After compaction | No (injection only) | hook_state (resets `validate_prose_called`) |
| Blacklist scan (stop hook) | After output (stop hook) | Never | catch_analytics.json (`corrections.json` is a retired no-op) |
| Prose observer | After output (async subprocess) | Never | catch_analytics.json |
| phrase_reminder | Next turn (UserPromptSubmit) | No (injection only) | None (reads catch_analytics.json) |
| blacklist_evolver | Session-end (maintenance) | No | blacklist.json (adds/promotes phrases) |

<!-- SUPERSEDED 2026-05-31 — §5 parity pass: the "7-step pipeline" and "76+26+5" counts certified below are no longer current. Pipeline restructured to 9 steps (added the fabrication-ban scan as step 1 and the pet-name/tripwire/narration widening checks as step 7; backstory now precedes the in-dialogue claim scan; Haiku review gated behind all of steps 1-7). Live blacklist.json counts now 78 blacklisted + 46 use-sparingly + 5 protected + 5 structural. See the current §5 body for authoritative numbers; the prior stamp is retained below as the dated record of what was done on 2026-05-28.
     REVIEWED AND CORRECTED 2026-05-28 — rewritten for hook chain redesign + validate_prose enforcement. 7-step pipeline, diagnostic-only stop hook, evolution cycle (Layer 4), three-layer enforcement (tool description + PostCompact + gate_check), phrase counts corrected (76+26+5 structural). -->

### The Fabrication Guard

Where the rest of the Prose Quality Stack polices *how* the prose reads, the Fabrication Guard polices whether it is *true to canon* — it stops the DM from asserting wrong relationships, jobs, pet-names, dates, or established facts. It has two halves: **prevention** (a widened pre-output gate) and a **learning loop** that turns every player correction into a permanent, one-shot fix.

**Design priorities:**
- **Invisible** — operates on the draft before output; nothing appears in narration. Same contract as the rest of the gate: the player only ever sees the corrected version.
- **Zero-maintenance** — it seeds itself from a who's-who fact set and then learns from the corrections the player already gives. No manual rule-writing.
- **Anti-cry-wolf** — the deterministic checks are deliberately narrow and sentence-scoped; the smart (Haiku) judge is gated behind them; and permanent bans come *only* from confirmed corrections, never from a guess.

#### Prevention — the widened Gate

The guard rides inside `validate_prose` (the Layer 1 gate, in `server.py`), still REQUIRED before narrative output and still enforced by `gate_check` (skipping it locks tools next turn). On each draft the gate now runs the following, in order — cheapest and most certain first, the smart judge last:

1. **Never-again ban check** (`_vp_check_fabrication_bans` → `hooks/fabrication_bans.py`) — hard-blocks any draft that re-asserts a claim the player has permanently corrected, and surfaces the correct fact in the violation. Runs first because it is the cheapest and most certain check.
2. **Blacklist + structural phrase patterns** — the existing prose-discipline scans (Section 5, steps 2–3).
3. **Use-sparingly / overused phrase check** — existing (Section 5, the `session_vocabulary` scan).
4. **NPC-mention check, backstory check, in-dialogue factual-claim check** — existing, cross-referenced against the distillation cache.
5. **Pet-name, tripwire, and narration relationship/job checks** (`hooks/fabrication_detectors.py`):
   - **Pet-names** — forbidden bond-names used in the wrong register (a campaign-defined bond-name spoken outside private `*bond*` text).
   - **Tripwires** — per-character canon hard rules (e.g. a photosynthete PC never eats; Mystic Gifts need no save). Campaign-specific pet-names and tripwires are DATA, loaded per call from the campaign dir's `fabrication_tripwires.json` (fail-open; 2026-07-12 — campaign facts never live in engine code); only setting-generic book rules are built in. Sentence-scoped, so a multi-character scene doesn't false-fire when an unrelated character is mentioned in an adjacent sentence.
   - **Narration claims** — relationship/job assertions about a named canon character in narrator voice, matched against a narrow familial-verb set and a bounded "Name, the role," appositive. Deliberately narrow to avoid crying wolf.
6. **Semantic judges — only if nothing above fired:**
   - The existing prose-style **Haiku judge** (`_vp_call_haiku_judge`).
   - Then, **only when a known canon name appears in the draft**, the **fact-checking Haiku judge** (`_vp_call_fact_judge`, prompt in `hooks/fact_judge_prompt.txt`). It receives the draft plus an answer key of cache facts *scoped to the entities named in the draft* (so the payload stays bounded as the cache grows), and flags only medium/high-confidence contradictions. Both judges fail open — any error returns no violations rather than blocking.

#### The cheat-sheet — the distillation cache

The answer key the guard checks against is the distillation cache (`hooks/distillation_cache.py`), seeded with who's-who facts by `hooks/canon_facts_seed.py` (identity + relationship entries, written under a new `identity` topic-key suffix added to `hook_utils.VALID_TOPIC_SUFFIXES`). Every gating turn, `check_canon` surfaces the relevant entries via `_query_distillation_cache`, which now also surfaces a *present* character's single-character `identity` entry even when their name does not appear in the player's input. The cache is bootstrapped once from the historical correction corpus (see below).

#### The learning loop — every correction is a permanent fix

On the player's turn, `hooks/turn_reset.py` (UserPromptSubmit) runs `looks_like_correction(message)`. If the message looks like a correction, it pairs it with the DM's prior turn and spawns `hooks/correction_capture_runner.py` as a **detached background process** (`start_new_session=True`), so the turn never stalls waiting on it.

The runner calls `correction_capture.capture_correction`, which extracts a `{entity, wrong_terms, correct_fact}` triple (via Haiku) and then:
- writes the **correct fact** to the distillation cache, so it re-enters context through `check_canon`, and
- writes the **wrong claim** to the never-again list (`fabrication_bans.json` at the campaign root — campaign-scoped since the personalization-leak fix).

One correction equals one permanent block. Unlike a prose phrase (which needs several catches before it is promoted to banned by the evolver), a *fact* needs only a single correction — the player should never have to correct the same canon error twice.

The one-time seed of both the cache and the ban list is done by `correction_capture.bootstrap_from_halluc_results` together with `extract_corrections_from_transcript`, which mine real play transcripts and the prior audit's confirmed-error corpus through the same extractor. The runnable entry point is `scripts/seed_fabrication_guard.py` (`--halluc-results <corpus.json> --transcript <play log .jsonl>`); it is idempotent (bans dedupe by entity+wrong_terms; cache entries replace by `topic_key`). First seed run (2026-05-30): 92 candidates → 68 unique permanent bans.

**Maintainer note:** `hooks/correction_logger.log_correction` remains a retired no-op (from the §12 cleanup). The live learning path is `correction_capture`, **not** the old `corrections.json`. Do not wire anything new to `correction_logger`.

#### Context cost

The bans, detectors, and cache all live server-side. Per turn the model receives only the small capped "RELEVANT CANON" brief that `check_canon` already injects (≤5 entries) plus a short `CLEAN`/violations result from `validate_prose`. No large failure-condition lists ever enter the model's context — the guard's cost is paid in server-side compute, not tokens.

<!-- ADDED 2026-05-30 — Fabrication Guard documented at build completion (Task 12). Function/file names verified against rubicon-seven-mcp@feat/canon-redesign: _vp_check_fabrication_bans, _vp_call_haiku_judge, _vp_call_fact_judge, _query_distillation_cache (server.py); fabrication_bans.py, fabrication_detectors.py (check_pet_names/check_tripwires/check_narration_claims), distillation_cache.py, canon_facts_seed.py, fact_judge_prompt.txt, correction_capture.py (looks_like_correction/capture_correction/bootstrap_from_halluc_results/extract_corrections_from_transcript), correction_capture_runner.py, turn_reset.py (detached Popen, start_new_session=True). 'identity' confirmed in hook_utils.VALID_TOPIC_SUFFIXES. correction_logger.log_correction confirmed no-op. Line numbers intentionally omitted (drift). -->

---

## 6. State Management

*Post-decomposition note (2026-06-17): many helpers this section attributes to `server.py` now live in extracted domain modules (`engine_core`, `substances`, `character_tools`, `generators`, and others) and are imported back into `server.py`'s namespace. Find any symbol via `workspaceSymbol` rather than assuming a file; the behavior claims below are unaffected.*

### File Hierarchy

```
rubicon-seven-campaign/                    (CAMPAIGN REPO)
├── CURRENT_STATUS.md          ← Session checkpoint (read every turn)
├── CLAUDE.md                  ← DM protocol and rules
├── VAARN_DM_SCREEN.md         ← Party/political/world reference
├── VOICE.md                   ← Character voice guides
├── VAARN_DM_REFERENCE.md      ← Rules/prep/lore reference
│
├── characters/                ← Split character files
│   ├── _meta.json
│   ├── <character>.json (one per PC)
│   └── ...
│
├── lorebook.json              ← 602K lore database (keyword-triggered canon)
├── npc_states.json            ← NPC dispositions, knowledge, secrets
├── narrative_threads.json     ← Plot threads and developments
├── narrative_relationships.json ← PC/NPC relationship status + history
├── party.json                 ← Consolidated party stats
├── characters/                ← Split character sheets (sole source) + _meta.json
├── game_state.json            ← In-session exploration/combat state
│
├── MASTER_CONTINUITY_CURRENT.md  ← Running session narrative archive
├── ANTAGONIST_CULTIVATION.md     ← DM threat tracking
├── RESONANCE_INDEX.md            ← Callback/echo tracking
├── WORLD_PROGRESS.md             ← NPC actions between sessions
│
├── dossiers/                  ← Antagonist intelligence files
├── prep/                      ← Location prep files
├── chroma-db/                 ← ChromaDB persistent storage
├── rulebook/                  ← Vaarn 2e rules in JSON
│   ├── rules.json
│   ├── tables.json (677K)
│   ├── bestiary.json (192K)
│   ├── equipment.json
│   ├── gifts.json
│   └── lore_additions.json
│
└── companion/                 ← Browser-based DM screen

rubicon-seven-mcp/hooks/                   (MCP REPO — runtime state)
├── .hook_state.json           ← Per-turn hook enforcement state
├── .canon_distillations.json  ← Distillation cache (~1,459 entries, grows at session-end)
├── catch_analytics.json       ← Prose quality catch data (feeds evolution cycle)
└── corrections.json           ← Hook correction log (feeds pattern analysis)
```

### CURRENT_STATUS.md — The Canonical Checkpoint

**Format:**

```markdown
# CURRENT STATUS - DAY {N}
**Last Updated:** {timestamp}
---
## SCENE STATE
**Day:** / **Location:** / **Present:** / **Last 3 Beats:** /
**Last Speaker:** / **Tension/Mood:** / **Next Expected:**
---
## ARC CONTEXT
**Current Arc:** / **Arc Summary:** / **Arc Tension:**
---
## EMOTIONAL STATE
| Character | Current State |
---
## ACTIVE SCENE
**Scene Type:** / **Active Prep:** / **Hot Preps:** / **Active Map:**
---
## DM KNOWLEDGE
## ACTIVE THREADS
## PARTY HP STATUS
## PHOTOSYNTHESIS
```

**Tools that write it:**

| Tool | What It Updates |
|------|----------------|
| save_state() | Full scene state, arc context, emotional state, HP sync, day header |
| log_beat() | Last 3 Beats (rolling window of 3), emotional state table |
| advance_day() | Day header |
| update_photosynthesis() | Photosynthesis line |
| _update_current_status_prep() | Active Prep and Scene Type fields |
| sync_campaign_day() | Day consistency across files |

**Tools that read it:**

| Tool | What It Reads |
|------|--------------|
| check_canon() | Everything — parsed via _parse_status_content() every user message |
| full_session_startup() | Day, present characters, active threads |
| get_current_day() | Day number from header |

### Two-Phase Save Protocol

**Why two phases:** Prevents accidental data corruption. The DM reviews changes before committing.

#### Phase 1: prepare_save_state()

Takes 18+ parameters covering session summary, scene state, arc context, emotional states, NPC changes, inventory changes, and new canon entries.

**Safeguards:**
- Input sanitization: `_sanitize_param()` strips leaked XML envelope tags from LLM-generated parameter values (a real production bug)
- Day-regression guard: if caller's day is >2 below CURRENT_STATUS.md header, save is blocked unless `force_day=True` (fixes a real bug where day regressed from 128 to 121)

**Computes diffs for:**
- MASTER_CONTINUITY_CURRENT.md (append)
- CURRENT_STATUS.md (scene/arc/emotional state updates)
- lorebook.json (new canon entries)
- NPC_ROSTER.md (NPC changes)
- characters.json (inventory changes)
- JSON meta timestamps

**Generates an 8-character MD5 token**, stores everything in global `PENDING_SAVE` dict. Token expires after 600 seconds (10 minutes).

#### Phase 2: confirm_save()

Validates token match, checks 10-minute expiration, clears PENDING_SAVE before calling save_state (prevents double-commit).

Must be called directly by the main agent — not via SendMessage/subagent (too slow, token may expire).

#### save_state() — Actual Writes

1. Runs antagonist cultivation review (scans session beats for trust breaches, abandonments, NPC hurt, promises, power shifts)
2. Updates ANTAGONIST_CULTIVATION.md with opportunities, prunes dormant seeds >20 days old
3. Appends narrative_log to MASTER_CONTINUITY_CURRENT.md
4. Indexes narrative into ChromaDB (4 tiers, batched by 32)
5. Updates CURRENT_STATUS.md: day, scene state, arc context, emotional state, HP sync
6. Adds new_canon to lorebook.json
7. Updates NPC_ROSTER.md
8. Applies inventory_changes to the character split sheets
9. Syncs meta timestamps

### Hardened Session-End Pipeline (shipped 2026-05-31)

An earlier `/session-end` dispatched **one** subagent through ~16 phases in a single context — the shape most exposed to silently dropping a tail step (ingest, verify). The hardened replacement shipped as the plain `session-end` skill (there is no separate `session-end-hardened` skill and no live legacy fallback path) and splits the work by its three distinct context profiles:

1. **Reconcile** (fresh) — the only stage that reads the full transcript. Settles the day (hard gate), sweeps this session's player corrections and backfills any the live fire-and-forget catcher dropped, builds the distillation entries, and writes + **freezes** a structured **facts record** (`session_end_facts.json`, git-ignored) per `skills/session-end/facts-record-schema.md` (canonical copy in this repo; the deployed copy runs from the campaign repo's `.claude/skills/session-end/`).
2. **Write** (fresh) — reads the *frozen facts record, not the transcript*. Prune-then-patches the rich files (world progress, resonance, memory note always, synthesis fresh always, hygiene on a budget-condition flag, DM screen, threads, cultivation curation + dossiers). One file, one writer.
3. **Verify** (fresh) — Layer 1 calls the deterministic `verify_session_save()` MCP tool (`hooks/session_verify.py`); Layer 2 does judgment checks (narrative coverage, no fabrication, dormant-arc flag). Bounded send-it-back loop re-dispatches the Write agent scoped to any flagged file.

The conductor (the skill) runs the three agents sequentially, handles the player-approval diff, and runs the index calls (`distill_session` write → `ingest_distillations` → `reindex_recent`) **after** `confirm_save` — the save block commits last. A second, lighter Verify pass confirms the cache loop closed (zero un-posted distillations) and emits a DM-only vital-signs line.

**`verify_session_save()` deterministic checks:** writes-landed (file mtime ≥ facts-record mtime, per expected-writes derivation), file budgets, day agreement (CURRENT_STATUS = facts = transcript), corrections-landed (every swept correction has a ban + cache entry), cache-loop closed (pass 2), antagonist integrity (dossier index stamped today + every active/ripening dossier has a today-dated maintenance log — **counts only, never contents**), reindex clean. Vital signs: corrections captured, any banned error reaching committed prose (alarm), budget trend, distillation growth.

**W2 context-budget tripwires (2026-06-12, `hooks/session_verify.py`):** the knowledge layer must alarm instead of decaying silently (the fired≠surfaced pattern applied to files). `check_budgets` additions: campaign-memory MEMORY.md line budget **190** (margin before the loader's 200-line truncation cliff; a *missing* memory file now FAILs instead of passing as 0 lines), DM-screen **Tensions block** char budget **2500** (measured from the `^Tensions` line to the next `## ` header — char bloat hides inside a file under its line budget), campaign **CLAUDE.md** warn at **8000 bytes** (every-turn import; warn-only since protocol edits are deliberate). New `check_staleness` (both passes): scans MEMORY.md + VAARN_DM_SCREEN.md for ALL-CAPS `PENDING` markers — each must carry `(check-by YYYY-MM-DD)` or `(check-by Dnnn)`; missing or past-due check-bys WARN (loud in the report, never blocks a save on prose). Tests: `tests/test_w2_context_tripwires.py` (16).

**Ownership / no-clobber:** the Write agent owns the rich narrative files and the dossiers; `save_state` keeps owning the save block + its existing patches. `ANTAGONIST_CULTIVATION.md` is patched by **both** (Write agent curates DORMANT SEEDS/ACTIVE THREATS/ESCALATION LOG; `save_state`'s `_review_cultivation` auto-appends OPPORTUNITIES) — exactly as today, both non-destructive section-patches on fresh reads. `save_state` does not touch the dossiers or the dossier index. The pipeline is **idempotent** — re-running after a crash, rejection, or failed verify lands on the same end state.

**Folds in two parked projects:** thread reconciliation (the dormant-arc lever) and engine vital-signs (the recurring health readout).

**Crystallization feed (2026-07-04):** the frozen facts record also carries `facts.npc_candidates` (people met this session who are neither party nor already recorded) and `facts.faction_shifts` (organisational standing that moved). At Step 7.5 the DM judges each candidate recur-vs-evaporate and applies the recurring ones via `npc(action="set"/"continuity")`, and applies each faction shift via `faction(action="earn"/"set"/"add")` — see `skills/session-end/facts-record-schema.md`.

### Character Data

**Storage:** Split-file architecture at `characters/*.json` with `_meta.json` — the **sole** source of truth. Each character is a separate JSON file. The legacy monolithic `characters.json` fallback was **retired** (2026-06-08, T4): it had silently drifted from the split sheets (missing weapons/range markers), so `_load_characters` now reads split-only and returns a clear error rather than serving stale data; no code path writes the monolithic file.

**Tool:** `character()` — 36 actions (`VALID_CHARACTER_ACTIONS`, `server.py`). The core get/list/update/level-up/damage actions are described here; recruit/dismiss/pet/steed/vehicle/mercenary/follower/elixir actions are documented in their own subsections below (E5, D2-D5, B2/B3, PC-gen) — not enumerated in full here to avoid drift.

**Character data shape:**

```json
{
  "name": "Thornback",
  "species": "neobloom",
  "role": "PC",
  "pronouns": "he",
  "level": 4,
  "hp": {"current": 23, "max": 23},
  "av": {
    "base": 16,
    "conditional": [{"total": 21, "condition": "with glaive", "bonus": 5}]
  },
  "xp": {"current": 0, "needed": 4},
  "abilities": {
    "STR": {"current": 0, "base": 0, "notes": ""},
    "DEX": {"current": 4, "base": 2, "notes": "+2 from Hyper-elastic Tendons"},
    "CON": {"current": 1, "base": 1},
    "INT": {"current": 0, "base": 0},
    "PSY": {"current": 1, "base": 1},
    "EGO": {"current": 0, "base": 0}
  },
  "slot_capacity_total": 11,
  "inventory": {
    "carried": [{"name": "Vibro-glaive", "slots": 2, "damage": "3d8+6", "id": "..."}],
    "stored": []
  },
  "augmentations": {"head": {}, "body": {}, "limbs": {}},
  "mystic_gifts": [{"name": "Dissolving Thread", "effect": "..."}],
  "gleam": 3,
  "attacks": [{"name": "Vibro-glaive", "damage": "3d8+6", "type": "melee", "range": "close"}],
  "wounds": [],
  "wounds_slots_used": 0,
  "special_traits": {
    "vulnerabilities": [{"type": "fire", "effect": "DOUBLE damage (flammable)"}],
    "mutations": []
  },
  "bloomboons": []
}
```

**Damage flow:**
1. Check vulnerability (e.g. a sheet vulnerability doubling fire damage)
2. Apply damage to HP
3. If HP crosses 0: look up wound from BIOLOGICAL_WOUNDS or SYNTHETIC_WOUNDS table
4. Wound consumes inventory slots and may apply ability damage (rolled via dice_roller)
5. Death conditions: HP ≤ -20, all slots filled with wounds, or any ability below -10

**Level-up flow:**
1. `gain_xp()` awards XP, alerts when current ≥ needed (needed = current level number)
2. `level_up()` requires exactly 3 stat increases and a d8 HP roll
3. Resets XP to 0/new_level, caps stats at +10
4. Alternative paths: `level_up_proteus` (cacogen d100 mutation table), `level_up_bloomboon` (neobloom d20 table with rejection sampling)

### Toxin Die (B1)

Book-accurate (Crimson Hound), **symmetric** across PCs and Biological enemies — replaces the old flat-damage treatment of `TOX`.

- **Shared primitive** `dice_chain.py` — a pure ladder `cured < d4 < d6 < d8 < d10 < d12 < d20` with `roll` / `step_down` (deplete) / `escalate` (bigger-wins) / `size`. Reusable by the future Usage Die (ranged ammo / consumables).
- **State:** `toxin_die` on the PC sheet (`characters/*.json`) and on the enemy combat entry (`active_combat.enemies[name]`). Cleared = absent / `"cured"`.
- **Susceptibility = Biological only.** Enemies via `stats.type` containing "Biological"; PCs via species/physiology with an explicit `toxin_immune` override (e.g. a Synth PC). Non-Biological = immune (consistent with poison immunity in the resistance matrix).
- **Save:** DC = `10 + die faces` (uncapped). PC target → the **player rolls** their CON save and feeds the total to `toxin(action='resolve', …)`; enemy target → the engine **auto-rolls** `d20 + creature Level (cap +10)` and resolves. A failed save gains/escalates the die (bigger-wins); a success does nothing.
- **Tick:** roll the current die, subtract from HP, and **deplete one rung on a 1-2** (single roll does double duty). Fires **automatically each combat round** for every afflicted combatant via `_check_round_advance`; out of combat it is a DM-invoked lever (one tick per exploration turn). PC HP feeds the existing death-condition checks; an enemy reduced to 0 is defeated.
- **Combat reroute:** a `TOX`/poison hit in `_combat_attack` reroutes at the top of the hit path — a Biological target makes the save/incur, no flat damage; a non-Biological target is immune.
- **Cure:** a DM lever (`toxin(action='cure', …)`) that steps the die down or clears it — no hard-coded item→cure mapping (curing is narrative/source-dependent per the book).
- **Tool:** `toxin(action=…)` — `status` / `check` / `resolve` / `tick` / `cure` — a thin wrapper over the testable `_toxin_dispatch`. (Engine logic lives in the `_toxin_*` helpers in server.py.)

### Ranged Usage Die (U1)

Ranged weapons consume ammunition via the book's Usage Die (Crimson Hound, Explorer's Guide p.34–35), **reusing the `dice_chain.py` primitive untouched** (`Expended < d4 < … < d20` — same ladder as the Toxin Die, just labelled "Expended" at the bottom). **PC-only** (the Usage Die is a player resource-management mechanic; no bestiary entry carries ammo).

- **State:** the weapon's existing `ammo` field (`"Ud8"` notation) on `inventory.carried[]` (authoritative; the `attacks[]` list is a display mirror synced by name), plus an `ammo_max` sibling field. `ammo_max` is **stamped at the generator** (`weapon_schema.build_weapon` sets it = `ammo` at mint), enforced by `validate_weapon` (`ammo` ⇒ a valid `ammo_max`), backfilled onto existing sheets, and lazy-initialised as a safety net. It caps `feed`/`reload` so restoration never exceeds the weapon's natural die.
- **Applicability** keys off `range == "ranged"` AND a truthy `ammo` field — **never `type`/`tier`** (the generator stamps range/ammo reliably but records tier only for display, and hand-authored sheets use a different `type` key). Helper `_weapon_has_tag` detects tags via `engine_tags` with a prose-`tags` fallback (covers the inherent-Fungal Spore Thrower); `parasitic`/`fungal` are registered engine keys in `weapon_schema`.
- **Trigger:** the engine records each ranged usage-die weapon a PC fires in `active_combat["weapons_fired"]` (deduped), and at **combat-end** (`_combat_end`, before state-clear) rolls each **once** — book-literal "ranged weapons roll their usage die once after combat" — depleting on a 1-2. Results appear in the combat summary; an unresolvable fired weapon is surfaced, not silently dropped.
- **Empty = hard-block:** firing an `Expended` weapon in `_combat_attack` returns an "OUT OF AMMO" message (with `ammo_note` + carried ammo items) and does **not** resolve the attack.
- **Parasitic** weapons never deplete (skipped everywhere; `status` shows ∞). **Fungal** weapons get a `feed` action that steps the die **up** one rung via `escalate`, capped at `ammo_max` (organic reload; restores, never supercharges). Only the *ammo* clauses of these tags are honoured here; their other clauses (unequip-surgery, no-damage-vs-Fungal) belong to inventory/resistance systems (roadmap U5).
- **Reload** is a DM lever (`usage(action='reload')`): sets the die back (default `ammo_max`, capped), rejects junk input, refuses a "cannot be reloaded" note unless overridden, and surfaces carried `type=="ammo"` items + the `ammo_note` for the DM to reconcile in fiction. It does **not** enforce item decrement (the narrative-intelligence-layer design; enforced consumption is deferred to U4).
- **Tool:** `usage(action=…)` — `status` / `roll` / `reload` / `feed` — a thin wrapper over the testable `_usage_dispatch`. (Engine logic lives in the `_usage_*` helpers in server.py; `roll` also serves out-of-combat single shots and the book's exotica "roll after each use".)

### Equipment Usage Die & Encumbrance (U2)

Extends depletion from ranged ammo to **all carried equipment**, and enforces Vaarn's item-slot/encumbrance constraint (Explorer's Guide p.34–39). The player says *"I use the X"* in plain narration; the engine resolves the cost behind the scenes and keeps the slot ledger correct.

- **Pure primitive** `item_slots.py` (the slot-math sibling of `dice_chain.py`; no game state, importable by both server.py and the hooks): `slot_cap(con, bonus)` = `10 + CON + mutation`, `is_encumbered(used, cap)`, `HARD_CEILING = 20`; plus item-field reading — `item_usage_die` (reads canonical **`usage_die`** then the weapon alias **`ammo`**), `item_is_depletable`, `depletable_label`, and `parse_slots_uses` (the book `slots_uses` notation → structured fields).
- **Field model (reconciled):** `usage_die`/`usage_max` is canonical for equipment; `ammo`/`ammo_max` is the U1 weapon alias (read/written interchangeably via the accessor — U1 sheets untouched); `uses`/`uses_max` is the separate discrete-count mechanic; `slots` is orthogonal (inventory weight).
- **Unified verb** `usage(action='use', character, item)` → `_item_resolve` (any carried item) + `_item_use`: a **usage-die** item rolls per-use and steps down on a 1–2 (stays in inventory, refuelable); a **discrete** `uses` item decrements and, at 0, is **removed from `carried[]`** (its slots free automatically via `_refresh_slot_fields`); an **unlimited** item no-ops. Equipment is **per-use** (book: "exotica roll their die after each use") — distinct from U1's ranged once-after-combat path, which stays ranged-only (`_usage_applies` unchanged; the two triggers never cross).
- **Encumbrance (book-accurate, enforced):** `_calculate_slots` adds an `encumbered` flag (`(gear + gifts + codices + wounds) > slot_capacity_total`). Inventory adds (`_apply_inventory_changes`) now **allow exceeding the personal cap up to the hard 20-slot ceiling**, flagging **Encumbered** instead of rejecting (reject only beyond 20). Encumbered → **DIS on STR/DEX/CON saves**; because PC saves are player-rolled, the modifier is **surfaced** (`_encumbrance_save_note`, wired into both toxin CON-save prompts) rather than silently rolled. Wounds always apply (they enter via the wound path, never the capacity-gated add); death-by-wounds (`_check_death_conditions`) is unchanged. **Forward-compat:** every slot site counts `wounds_slots_used` toward used, so the future Wounds loop drops in without refactor.
- **Reflex discoverability (the "how does Claude find the right tool?" rule):** the UserPromptSubmit hook `phrase_reminder._build_load_block` pushes a per-turn **LOAD** line (used/cap + Encumbered) and a **DEPLETABLES** list into the DM's context before narration — each with the exact `usage(action="use", character="…", item="…")` call (double-quoted, apostrophe-safe). The `usage(action='status')` output carries the same LOAD + push-call payload on demand. So *"I use the blowtorch"* arrives with its trigger and call already in front of Claude.
- **Generator (check-the-generators):** `_stamp_slots_uses` parses a minted exotica's `slots_uses` string into structured `slots` + `usage_die`/`usage_max` or `uses`/`uses_max` at the point `_roll_exotica` mints a result (a per-result `dict(_raw)` copy — the shared `EXOTICA_TABLE` constant is never mutated).
- **House rule:** the book's separate **"Encumbrance initiative"** combat rule is deliberately **not** implemented (Joe, 2026-06-09). Out of scope (separate roadmap items): enforced discrete-item consumption beyond auto-remove, and enemy-side equipment depletion.

### Wounds Application Loop

When PC damage lands at **HP ≤ 0**, the engine applies the book's wound (Explorer's Guide p.37–39) at that HP — automatically, every time, from the book-real tables — and keeps every consequence live. Spec: `docs/superpowers/specs/2026-06-09-wounds-application-design.md`; plan: `docs/superpowers/plans/2026-06-09-wounds-application.md`.

- **Pure primitive `wounds.py`** (sibling of `item_slots.py`/`dice_chain.py`; imported by server.py AND the hook): both tables with **structured effect fields** (`dis_saves`, `deprived`, `av_penalty_die`, `blind`, `daily_tick`, `until_fixed_ability`, `special`, …); `wound_for_hp` (clamps −20); `roll_wound_record` (rolls **derived** magnitudes/durations once and stamps them ON the record; never rolls mutations); `derived_effects(records)` (the single aggregate reader); `forced_drop_slots`. The Synthetic table is transcribed from the extraction — the previous in-server copy was fabricated (a renamed Biological mirror) and is gone.
- **The storage rule — derive, don't mutate:** "until fixed"/state effects (DIS-on-saves, Supercoolant **Deprived/no-HP-regain**, Synthskin **−AV + double damage**, Vischip **blind**, unconscious/Death's Door, the daily tick *while active*) are **read fresh from the active records** at every consumer — healing the record makes them vanish with zero reversal code. Rolled-once mutations (ability damage, max-HP loss, the −18 level loss, the Personality-Nexus reroll — 3d6-lowest, verified vs the chargen extraction, resets `base` AND `current`) are applied once via `_apply_ability_damage_from_wound`/siblings and are never reversed by heal (recovery table = deferred seam).
- **Unified trigger** (`_character_take_damage` → `_apply_wound`): damage > 0 landing at HP ≤ 0 wounds at `max(new_hp, −20)` — landing exactly at 0 (Knocked Out), dropping from above, or taking damage while already down are all the same rule (replaces two buggy branches: exactly-0 never fired; damage-while-down printed but applied nothing). Duplicates stack. Pre-damage derived reads: Synthskin doubles incoming damage; **Death's Door** makes any damage lethal — HP snaps to −20 so death is state-true, not just narrated.
- **Special wounds:** Knocked Out / Update Required (player-rolled CON save; prompt pushes `wound(action="ko_save", …)`; fail → unconscious d6 rounds, **all attacks auto-hit**); Damaged Item (d20 over the carried items' occupied slot spans — zero-slot items hold no position; struck item gets **`broken: true`**, an item-level flag that survives wound healing; past the last span = lucky miss); Bloody Mess (3 × 3d6, each sum a full wound at −sum, 18 rerolled so it never nests; slots come from the children — book's "3–9").
- **Forced drop (Joe ruling: wounds evict gear):** gear room = `cap − wound_slots`; gear over the room → **"MUST DROP N"** surfaced at application and re-pushed per-turn until resolved (engine computes N; the player chooses what falls — nothing is auto-deleted). Zero-slot wounds evict nothing (voluntary over-cap stays U2-legal Encumbrance). All-slots-wounds death unchanged.
- **`wound()` tool** (gated like `toxin`/`usage`): `status` (records + derived summary) · `heal` (→ **`_remove_wound`**, the single removal seam — Long Rest's heal-one-wound, Sprayflesh, Trauma-Response Rig, DM fiat all route here; stacked identical wounds heal one copy; never touches mutations or `broken`) · `ko_save` (player-reported pass/fail — the engine never needs the DC) · `wake` (DM lever for duration expiry; clears the stale duration too).
- **Combat readers:** unconscious PC target → **AUTO-HIT** (no d20); Synthskin `av_penalty` reduces `_defender_av` (floor 0); blind PC attacker → ranged **blocked** (incl. thrown, per the A4 house rule), melee at **mechanical DIS** when the engine owns the roll (2d20 keep worse — Iron Law 3 reserves only the player's dice; the player is *instructed* up-front instead); wound DIS joins `_encumbrance_save_note` on save prompts via `_wound_save_note`.
- **Rest & day:** Deprived blocks HP regain on Short AND Long Rest (only HP — the heal-one-wound offer and ability restore still run); Long Rest's wound listing pushes the exact double-quoted `wound(action="heal", …)` call per wound; `advance_day` applies the Cascading-Kinesthetics daily tick per elapsed day (same-day/backwards re-calls never re-tick — the tool is idempotent; failures surface in-band).
- **Broken items:** guarded at use/attack time ONLY (`_broken_item_msg`, shared so wording can't drift): `usage(use/roll)` blocked, attack blocked (broken > blind > ammo precedence; never prompts the wielder), `_combat_damage` auto-read blocked; status tags BROKEN. **Never pushed per-turn.** Repair = DM-fiat seam (out of scope by design).
- **The per-turn WOUNDS push** (`phrase_reminder._build_wounds_block`, after the LOAD block, fail-open): **concision-budgeted** (Joe's constraint) — silent when nobody is wounded (the common case costs zero tokens); one line per wounded PC; **derived/owed content only** (mutations are already on the sheet and never restated — pure-mutation wounds appear by name only); high-stakes flags always shown while active (`UNCONSCIOUS(attacks auto-hit, N rounds)` · `DEATH'S DOOR(next damage kills)` · `MUST DROP N` · the pending-KO `ko_save` call).
- **Out of scope (clean seams):** item repair; reversing rolled-once mutations on heal (recovery-table ruling; Long Rest's one-point restore stays); enemy-side wounds; resurrection/Ego-Engine reinstall (the −19 row surfaces the salvage note); auto-expiry of unconscious durations (the `wake` lever + surfaced durations until an exploration-turn clock exists). Wounds is the keystone the S (Survival) and E (Afflictions) roadmap clusters generalize.

### Survival & Supply (S1)

Daily water/food consumption, hybrid party-pool + carried-rations supply, and the Deprived condition (blocks healing; 3-day death clock). Silent at an earned home base, live in the field. Book authority: extraction batch_02 p.35 (1 water/day, Deprived, 3-day thirst death), batch_03 p.37 (Deprivation blocks Rests). Spec: `docs/superpowers/specs/2026-06-10-survival-supply-design.md`; plan: `docs/superpowers/plans/2026-06-10-survival-supply.md`.

- **Pure primitive `survival.py`** (repo root, sibling of `wounds.py`): `survival_block` (defaults applied; `biological` wound_table → needs ON, all other wound_tables → needs OFF unless the sheet overrides — covers vehicles, synthetics, mechanical entries); `daily_needs` (water + food ON-READ: survival block × parasitic doubling — any equipped item with a `tags` or `engine_tags` `"parasitic"` entry doubles all ration needs); `deprivation_clock` (reads `death_days_thirst`/`death_days_starvation` from the sheet, defaults 3); `consume_day` (pool → carried → shortfall, MUTATES in-memory; `already` param credits ledger-tracked rest consumption so the same ration isn't charged twice on days that contain a rest, R-S1c); `tick_deprivation` (MUTATES `conditions`: creates record on first unmet day, leaves it if still unmet, removes it when met); `condition_effects` (aggregate read, same pattern as `wounds.derived_effects`: tolerant of garbage, read-only). `_has_tag` checks both `engine_tags` (generated weapons, plain lowercase) and `tags` (hand-authored, parenthetical-stripped via `_tag_key`).

- **Data shapes.** Supply record lives in `characters/_meta.json` under `"supply"`: `{"mode": "abundant"|"field", "pool": null|{"food": N, "water": N}, "pool_location": str, "follower_mouths": int, "separated": [key, …], "ledger": {"day": int, "consumed": {key: {"water": N, "food": N}}}}`. Default on first access: abundant, pool null, no followers, empty ledger. Per-PC survival overrides live on the character sheet under `"survival"`: `{"needs_water": bool, "needs_food": bool, "water_per_day": int, "food_per_day": int, "death_days_thirst": int, "death_days_starvation": int, "photosynthesis_window_days": int}` — all optional (defaults apply from `survival_block`). Condition records live on the character sheet under `"conditions"` (the E1 scaffold): `[{"name": "Deprived", "cause": "thirst"|"starvation", "since_day": int, "death_day": int}]`. Standard carried-ration item shape (inventory lists): `{"name": …, "ration_type": "water"|"food", "rations": N, "slots": 1}`.

- **`advance_day` supply tick** (server.py line ~6333, `SUPPLY DAILY TICK` block, same idempotency contract as the wound tick). Fires only when `supply.mode == "field"` and `elapsed_days > 0`. Per elapsed day, per PC: reads `daily_needs`, checks `separated` to decide pool access, calls `consume_day` (pool first, then carried rations), calls `tick_deprivation` per need. Death check before tick: if a Deprived record's `death_day <= tick_day` and the need is still unmet, HP snaps to −20 (state-true death, same convention as Death's Door). Follower mouths drink from the pool first-class before the PC pass. Vehicles are skipped by TWO guards: the tick hard-skips any sheet with `type == "vehicle"` before computing needs, AND `survival_block`'s defaults are OFF for non-biological wound_tables so `daily_needs` returns zero anyway; because of the hard-skip, a vehicle sheet gaining a `survival` block with explicit needs is still NOT a consumer (the check-the-generators note for future vehicle survival is captured as a DEBT item). Corpses (HP −20) are NOT explicitly skipped by the tick — `daily_needs` returns zero for non-biological; a dead PC whose sheet remains in `characters/` retains a tombstone condition record that persists until resurrection tooling clears it (Task 4 review note; the resurrect/stabilize seam is a DEBT item). Ledger is reset to `{"day": new_day, "consumed": {}}` after the tick completes, so rest credits from the new day start clean. Failures are caught, logged, and surfaced in-band; they never silently corrupt state. Pushes `supply(action="status")` when any PC is still Deprived after the tick.

- **`advance_day` WEATHER NAG** (server.py `WEATHER NAG` block, after the condition push, before the site auto-stamp). The desert weather hex-walk (`roll(action="weather")`) is pull-only — nothing advances or surfaces the marker. In FIELD mode (out in the desert, where weather bites; silent in abundant/settlement mode) and only on a real forward jump (`new_day - old_campaign_day >= 1`; same-day/backwards re-calls stay silent), the tick appends a `**WEATHER**` line pushing `roll(action="weather")`. Because `advance_day` takes an ABSOLUTE target day, a time-skip can jump several days at once; the hex-walk steps ONCE per day, so an N-day jump surfaces the count ("N days passed — walk the weather hex N steps, one per day, roll for EACH") so a multi-day skip is not under-walked. Push-only: the engine NEVER auto-rolls (the DM rules which days count — [[feedback-engine-vs-dm-judgment]]). Travel days route through here (`travel_day → on_day_tick → advance_day`, always a 1-day step), so each travel day gets a single-step nag; `travel_day` itself only READS the current marker to gate the day and never pushes a roll, so there is no double-push. tests/test_weather_nag.py.

- **`rest()` consumption (R-S1c)** — field mode only; abundant mode is free. Short Rest consumes 1 water per PC (the primary desert need; food is a DM-adjustable fallback via `supply(action="adjust")`). Long Rest consumes 1 water + 1 food per PC. Both call `_rest_consume(char_names, data, water_each, food_each)` which: pools the ledger credit so the same ration never charges twice on days that also contain an `advance_day` tick; scales by the PC's actual `daily_needs` multiplier so a Parasitic-equipped PC pays double at rests too; saves carried-ration mutations to the sheet before saving the supply meta (C1: the pool and carried counts must be consistent). When the pool runs dry and no carried rations cover the need, `_rest_consume` returns SHORT lines and pushes `supply(action="status")`. The Deprived-blocks-HP-regain check was generalized from the wound-only `_deprived_wound_name` to `_deprived_block_reason(char)`: checks wound records first (Supercoolant Leak stays working), then `condition_effects` on `conditions` — same block regardless of source.

- **Photosynthesis window as sheet data** — `update_photosynthesis` and the `advance_day` photosynthesis fallback both call `_photosynthesis_window()`, which reads `survival.photosynthesis_window_days` from the first character sheet that declares it (book default 3 when absent). A window-extending graft is modelled as `photosynthesis_window_days: 4` on the sheet (book 3 + the graft's +1 day), not a magic constant in the code. The previous hardcoded `+ 4` is gone.

- **`supply()` tool** (6 actions, gated like `toxin`/`usage`): `status` (mode, pool counts, days-at-burn, per-PC Deprived clocks) · `depart` (enter field mode; pass `food`/`water` counts to initialize a pool, or omit for carried-only) · `arrive` (return to abundant; clears every PC's Deprived records — per ruling R-S1a home-base access IS eating/drinking — persists sheets-first/meta-last, resets the ledger, and reports `Recovered from Deprived (home supply): …`) · `adjust` (+/− pool counts, follower mouths) · `separate` (cut a named PC off from the pool — they draw only from their carried rations) · `rejoin` (return them to the pool). Docstring trigger-line: `Reach for this WHEN the party leaves or returns to a supplied base, …`. **World tick (2026-06-12):** `supply` gained a `location` param — `arrive` stamps the named location's last-visited day and, on a return after 7+ days away, pushes the book's settlement-changes roll. See *World Tick — play-loop slice 1* below for the stamp mechanics and the fired-≠-surfaced PILLAR.

- **Reflex SUPPLY line** (`phrase_reminder._build_supply_block`): returns `[]` when `mode != "field"` (silent at home). In the field: one AMBIENT entry `SUPPLY: {food}F/{water}W pool ≈ {days}d` (or `SUPPLY: carried-only` when pool is null), plus one URGENT entry per Deprived PC `DEPRIVED: {name} {cause} — no healing, dies Day {death_day} → supply(action="status")`. Wired into `_build_reflex_block` alongside the WOUNDS and LOAD builders. Snapshot keys: `supply:pool` → `"{food}F/{water}W"` (field mode with a pool); `deprived:{name}:{cause}` → `"{death_day}"`. Fail-silent inside the existing `_build_reflex_block` try/except.

- **Out of scope (clean seams):** resurrect/stabilize tooling must clear stale Deprived conditions alongside restoring HP (corpse tombstone records are intentional — see DEBT entry); S2 Foraging (consumes `supply(action="adjust")`); Parasitic non-survival clause (surgery-to-unequip); the survival-half of U5 is absorbed — U5's remaining scope is the resistance half of the Fungal tag.

**S2 Foraging (2026-06-11):** `supply(action="forage", character="A, B")` (field mode only; vehicles and dead PCs refused as foragers) rolls the book's d100 Desert Foraging table (pp.137-138) per forager — duplicates render once as a shared discovery. The certified `table-desert-foraging` (campaign `rulebook/tables.json`) carries machine-readable annotations applied by `scripts/annotate_foraging_s2.py`: `yield` objects (`{"water": "d8", "food": 3}`) for unconditionally-free rations, `cache` size keys for Survival Cache rows (chain-rolled from `table-treasure-cache-survival`), and nothing for scene rows — the absence of a suggested credit IS the DM-rules-this signal. Yields resolve via `survival.resolve_yield` (negative annotations clamp to 0); scene prose dice are annotated by `survival.roll_dice_in_text` (uppercase D is book dice notation — deliberate); nothing is ever auto-credited — the output pushes ready-to-run `supply(action="adjust", character=..., water=N, food=N)` calls (R-S2a) which land rations as carried items via `survival.adjust_carried` (top-up then mint, 3/slot, S1 item shape; Water Tokens currency untouched; vehicle credit refused, corpse credit warned). The pool form of `adjust` now REFUSES when no pool exists (R-S1b: pools come from earned bases, never from finds). Weather (p.146) is parked as its own roadmap item (W).

### Persistent status framework (E1, 2026-06-11)

General engine-owned persistent conditions (curses, Burning, disease, Twinning death bond, photosynthesis deprivation): applied by name, ticked daily/weekly/per-round by the engine, saved-to-end by player rolls, death-gated through the Twinning bond. Spec: `docs/superpowers/specs/2026-06-11-status-framework-design.md`; plan: `docs/superpowers/plans/2026-06-11-status-framework.md`. Rulings R-E1a..h. Book authority: batch_08 p.229 (Resurrection), batch_02 p.15 (photosynthesis), batch_08 p.228 (disease Virulence saves).

- **`conditions.py`** (repo root, sibling of `wounds.py`/`survival.py`). Pure, no I/O. Two public surfaces: `normalize_record(req, day)` validates a DM-supplied apply request into a stored record (returns `(rec, "")` on success, `(None, error_str)` on failure; unknown top-level keys dropped silently for forward compat); `condition_effects(conditions)` aggregates derived state read-only (tolerant of garbage, returns a fixed-key dict). `survival.condition_effects` is now a re-export of the same function — one implementation, no fork. `resurrection_push()` returns a fresh copy of the five-path p.229 list.

- **Record shape** (stored on character sheet under `"conditions"`, list of dicts): `{"name": str, "since_day": int}` minimum; optional: `"cause"`, `"note"`, `"death_day"`, `"effects"`, `"tick"`, `"save_to_end"`. Effects sub-object: `{"no_hp_regain": bool, "dis_saves": [ability...], "twinned": {"partner": display_name}}`. Tick sub-object: `{"cadence": "round"|"day"|"week", "hp": dice_notation, "abilities": {stat: dice}, "label": str}`. Save-to-end: `{"ability": str, "dc": int}`. Round-cadence ticks **require `tick.hp`** — ability-drain round ticks are not in scope (use day/week for ability drain; `normalize_record` rejects a round-cadence record with no `hp` die). Week-cadence records live in `condition_effects["day_ticks"]`; consumers check `entry["cadence"]` to fire at the correct 7-day boundary.

- **`condition_effects` output keys:** `deprived`, `no_hp_regain`, `deprived_causes`, `dying` (Deprived-only, for backward compat with S1 consumers that render `DEPRIVED:` labels), `dis_saves` (sorted union), `twinned_partner`, `round_ticks`, `day_ticks` (includes week-cadence), `save_to_end` (list of `(name, ability, dc)` tuples), `death_clocks` (non-Deprived clocks as `(label, day)` tuples), `active` (int count). Deprived `death_day` goes into `dying`, NOT `death_clocks` — the two sets never overlap.

- **`condition` tool** (4 actions, FieldInfo-normalized so direct test calls work). `apply`: builds a normalized record from flat params (`name`, `cause`, `note`, `death_day`, `no_hp_regain`, `dis_saves` comma-str, `tick_cadence`/`tick_hp`/`tick_abilities`-JSON, `save_ability`/`save_dc`, `twin_partner`); guards: vehicle refused, dead PC warned (not refused — tombstone records are legal); duplicate name rejected. `clear`: single name (substring match; ambiguity-guarded like wound heal) or `all_conditions=True` (revival lever; clears `twinning_pending` too; outputs `p.229` reminder). `status`: party-wide table (skips vehicles, skips PCs with no conditions); includes `DEATH PENDING` notice for any PC with `twinning_pending` set; status includes countdown `(in N day(s))` when campaign_day is readable from `_load_characters()` meta. `save`: resolves a save-to-end by comparing `save_total` to `save_to_end.dc`; pass clears the record, fail keeps it. Engine-owned conditions (`Deprived` from supply/photosynthesis) are documented as DM-do-not-apply; the tool does not refuse them if hand-applied, but the supply tick owns the mint/clear lifecycle. Docstring trigger-line: `Reach for this WHEN a persistent condition starts or ends on a PC`.

- **Tick cadences — engine-rolled vs player-rolled.** The toxin-tick (B1) sets the precedent: HP damage from conditions is engine-rolled (the DM does not ask the player). Round-cadence `tick.hp` damage is engine-rolled inside `_check_round_advance`. Day/week `tick.hp` damage is engine-rolled inside the `advance_day` CONDITION TICK block. Ability drains (`tick.abilities`) are also engine-rolled. **Save-to-end is player-rolled**: the engine prompts (`condition(action="status")` shows the `save_total=<roll>` push); the player rolls and reports; `condition(action="save")` resolves it. Deprived death clocks break both tick loops: a dead PC (HP <= -20) is skipped by the corpse guard; if a tick kills a PC mid-catchup the inner loop `break`s so no second tick fires on the corpse.

- **Death gate (`_death_gate`, `_check_death_gated`).** Every site that can mark a PC dead consults `_death_gate(key, char, data, window_key)` before acting. Returns `(allowed: bool, lines: list[str])`. When `allowed` is `False`, the caller treats the death as refused: the char stays alive. Window keys (`_death_window()`): active combat → `combat:r{round}`; outside combat → `day:{campaign_day}` from `_meta.json` (falls back to `"day:unknown"`). The outside-combat key is the smallest reliable shared instant: two blasts resolved as two tool calls in the same day still pair. `_check_death_gated` wraps `_check_death_conditions` + `_death_gate`, returning `(is_dead, reason, lines)`.

- **Twinning semantics (R-E1f, homebrew named for Caves of Qud's twinning lampreys; source: a campaign artifact).** A mutual bond: BOTH sheets must carry `conditions[{name: "Twinning", effects: {twinned: {partner: <display_name>}}}]`. Display names are matched case-insensitively (`_twinning_partner_check`). One-sided record (partner doesn't carry the back-bond) is treated as severed — death stands, warning emitted. Gate behavior: (1) no Twinning → gate open, death stands; (2) partner already dead (HP <= -20) → gate open, bond broken; (3) partner has a stale `twinning_pending` from a different window → refuse THIS death (brink clamp, new pending), the stale mark is inert — only an exact window match pairs; (4) partner has a matching-window `twinning_pending` → BOTH die (partner snapped to HP -20, `twinning_pending` popped, saved, `TWINNING SUNDERED` output with `"Two deaths, two rulings"` note); (5) no partner pending → refuse death. Brink clamping on refusal: HP floor -19 (not -20), ability floor -10. `twinning_pending` lifecycle: stamped on refusal by `_death_gate`; expired by `advance_day` (pops marks whose window != `day:{new_day}`, reports `TWINNING PENDING EXPIRED`); cleared by `combat(action="end")` (pops any `combat:`-prefixed marks); cleared by `condition(action="clear")` when the Twinning record itself is cleared. Partner-side pending is NOT popped on a one-sided clear (self-heals within a day) — known deferred item.

- **Five-path resurrection push (R-E1e).** Every real PC death (gate allowed) appends `conditions.resurrection_push()` to the output lines. The five paths verbatim from `conditions.RESURRECTION_PATHS`: Mycomorph Spores (INT save, d4 days), Necrotech (always a downside), Pseudo-Womb (CON save, 7 days), Spirit (d20 + Level >= 16, HP-spend rules), Ego-Engine Transplant (Synths only, restart Level 1). Fires at: `_apply_hp_damage_and_wounds` death path, advance_day deprivation death, advance_day condition-tick clock death.

- **`advance_day` CONDITION TICK block** (after the supply tick, before WORLD PROGRESS; same idempotency contract as the wound tick). Per character (vehicles skipped, corpses HP <= -20 skipped): (1) photosynthesis Deprived mint — if `survival.photosynthesis_window_days` is set and `photosynthesis_last_fed_day` is an int and `new_day > last_fed` and no existing photosynthesis Deprived record, mint `{"name": "Deprived", "cause": "photosynthesis", "since_day": last_fed+1, "death_day": last_fed+window}`. (2) Generic death clocks (NOT thirst/starvation — supply tick owns those): for each condition with a `death_day <= tick_day`, snap HP to -20 then call `_death_gate`; if allowed, log death + resurrection push + break; if refused (Twinning), stamp pending + break. (3) Day/week drains: for each `day_ticks` entry, week-cadence records fire only when BOTH guards pass — `tick_day > since_day` AND `(tick_day - since_day) % 7 == 0` — so a week condition applied Day 10 first fires Day 17, never on its application day (records with `since_day == 0` are warned and skipped entirely: no anchor for the 7-day math); then roll dice, call `_apply_hp_damage_and_wounds` or `_apply_ability_damage_from_wound`, then `_check_death_gated`. Pushes `condition(action="status")` when any PC has active conditions.

- **Photosynthesis wiring (R-E1c).** Structured field `survival.photosynthesis_last_fed_day` (int, campaign day) on the photosynthetic PC's sheet is what the engine reads. `update_photosynthesis(last_fed_day, current_day)`: updates CURRENT_STATUS.md (authoritative prose), writes `photosynthesis_last_fed_day` to the sheet, clears any `Deprived (photosynthesis)` record. Stale-feed guard: refuses if `last_fed_day + window <= current_day` (a living PC cannot have last fed before their death window). `supply(action="arrive")` does NOT clear photosynthesis Deprived — walking indoors is not sunlight; only `update_photosynthesis` (feeding) clears it. The legacy markdown-only path (`advance_day` photosynthesis regex warning) is suppressed when the structured field is armed (no double-reporting).

- **Combat-round condition tick** (in `_check_round_advance`, after the toxin block). Iterates `party_snapshot` keys; for each living PC with `round_ticks` entries (hp die only — round-cadence ability-drain records have no `hp` key so the guard `if not t.get("hp"): continue` skips them; by design, not a bug): rolls the die engine-side, calls `_apply_hp_damage_and_wounds` with `window_key=f"combat:r{round}"`, saves the PC sheet, logs the tick. Death via Burning rides through the Twinning gate. Pushes `condition(action="clear", character="<name>", name="<condition>")` when any tick fires (the extinguish lever).

- **Reflex CONDITIONS block** (`phrase_reminder._build_conditions_block`). Silent when no PC has conditions. Skips Deprived (thirst/starvation) — supply block owns those. Photosynthesis Deprived, other generic conditions: AMBIENT. Death clock (any `death_day` set) or round-cadence tick or `twinning_pending` mark: URGENT. Wired into `_build_reflex_block` alongside WOUNDS/LOAD/SUPPLY. Snapshot keys: `cond:{name}:{condition_name}` → `str(death_day or "on")` (non-Deprived conditions only; Deprived snapshot keys are the existing `deprived:{name}:{cause}` entries).

- **`_condition_save_note(char, stat)`** — save-prompt DIS suffix matching `_wound_save_note` contract. Returns `" - at **DISADVANTAGE** ({names}: roll 2d20, take the worse)"` when `stat` is in `condition_effects["dis_saves"]`, else `""`. Wired at CON save sites (toxin, virulence) alongside the wound note.

- **`_deprived_block_reason` extended (R-E1b).** After the S1 Deprived branch, before the final fallback: iterates `conditions` and returns `"{name} - no HP regain until cleared"` for the first record whose `effects.no_hp_regain` is True. Generic conditions block rest healing the same way Deprived does.

- **Known deferred items (clean seams).** Wound + condition DIS on the same stat double-renders on a single save prompt (two separate note strings concatenated — functionally correct, cosmetically noisy; not a bug). Round-cadence ability drains are unsupported by design (no HP die → skipped by the `if not t.get("hp")` guard; use day/week cadence). Partner-side `twinning_pending` not popped on a one-sided clear (self-heals within the day when the pending window expires) — the advance_day expiry loop handles it.

- **Live backfill (campaign repo):** `scripts/backfill_conditions_e1.py` — stamps the campaign's mutual Twinning pair (ruling R-E1f) and migrates the photosynthesis fed-day from CURRENT_STATUS.md prose (`**Last Fed:** Day N` primary, `**PHOTOSYNTHESIS:** Fed Day N` fallback) into `survival.photosynthesis_last_fed_day`. Idempotent; `--dry-run` previews.

<!-- ADDED 2026-06-11 — Documents E1 persistent status framework (branch feat/status-framework). Verified against live code: conditions.py (normalize_record, condition_effects, RESURRECTION_PATHS), server.py _death_gate/_check_death_gated/_death_window (after _check_death_conditions), condition tool (after supply()), advance_day CONDITION TICK + twinning_pending expiry, _check_round_advance condition tick, update_photosynthesis stale-feed guard, _combat_end pending cleanup, hooks/phrase_reminder._build_conditions_block. Rulings R-E1a..h per the 2026-06-11 spec. -->

### Disease system (E2, 2026-06-11)

Six organic Crimson Hound diseases (CH pp.228-229) layered on top of the E1 condition framework. Data-driven: a pure `diseases.py` catalog + builder, a one-call `disease` tool (apply/expose/list/info), and `advance_day` progression that flows through the existing Twinning-aware death seam. Status/save/clear remain on the `condition` tool; disease tool outputs push there. Spec: `docs/superpowers/specs/2026-06-11-disease-design.md`; plan: `docs/superpowers/plans/2026-06-11-disease.md`. Rulings R-E2a..f. Book authority: `archive/rulebook-source/extraction/batch_08_locations_exotica.md` lines 2681-2787 (pp.228-229). Nanomachine infections (pp.230-231) are E3 — out of scope.

- **`diseases.py`** (repo root, 400 lines as of 2026-06-12 — 180 at E2 ship, grown by the E3 nanomachine family; pure data + builder, no I/O, ASCII-only). The `DISEASES` dict now holds twelve entries (six organic + six nanomachine, see the E3 section); the organic six are keyed by display name: Brain Coral, Wrathworms, Jellybones, Hivey Hump, Labyrinth Pox, Lumenrot. Each entry carries: `virulence` (int 1-5), `tn` (= 10 + virulence, R-E2a), `symptoms` (prose), `cure` (prose), `vector` (prose), and optional `tick`, `on_apply`, `on_max_hp_zero`, `rider`, `transformation`, `stages` (prose riders the engine cannot automate).

- **`IMMUNE_SPECIES_STEMS = ("synth", "lith")`** — substring match on a lowercased species string. The extraction spells the Lith ancestry both "Lithling" and "Lithing"; matching the stable stem "lith" covers both. `disease_susceptible_pc(char)` returns `False` for immune species; the tool's `force=True` overrides for the "unless otherwise noted" cases.

- **`build_disease_record(name, day)`** — the single minting path for disease condition records. Routes the condition shell through `conditions.normalize_record` (single-source validation, no fourth record shape). Builds a `req` dict with `cause="disease"`, `save_to_end={"ability": "CON", "dc": 10+virulence}` (the cure save), and optionally `tick`, `on_max_hp_zero`, `note` (prose rider concatenated). Returns `(record, push_lines, "")` on success or `(None, None, error)` for unknown names or validation failures. `push_lines` is a list surfacing symptoms, cure, and stages.

- **Tick grammar extensions in `conditions.py` (R-E2c):** Three features added to `normalize_record` and `condition_effects` on top of the E1 base:
  1. **Flat amounts** (`_is_amount` / `_norm_drain`): `tick.hp`, `tick.max_hp`, and `tick.abilities` values now accept plain positive integers ("1", "3") in addition to dice notation. `_norm_drain` normalizes both forms to a stored string; `_roll_drain` (server.py) handles flat strings by bypassing `roll_notation` entirely.
  2. **`tick.max_hp`**: reduces `hp.max` per tick (floor 0) rather than current HP. Accepted by `normalize_record` alongside `tick.hp`; surfaced in `condition_effects["day_ticks"]` entries as `"max_hp"` key. Current HP is clamped down to the new max after each drain.
  3. **`tick.save`**: an engine-rolled gate `{"ability": str, "dc": int}` on a tick entry. When present, `advance_day` rolls d20 + ability modifier; a pass skips the drain for that day, a miss lets it fire. Validated by `normalize_record` (ability must be in `ABILITIES`, dc must be an int); stored in the tick sub-object and surfaced through `condition_effects`.
  4. **Record-level `on_max_hp_zero`**: `{"death_in_days": int}` stored on the condition record. `normalize_record` requires `tick.max_hp` to be present (the clock fires when max HP reaches 0) and rejects `death_in_days <= 0`. When `advance_day` sees `new_max <= 0` and the record carries `on_max_hp_zero`, it stamps `death_day = tick_day + death_in_days` on the condition record (idempotent guard: only if `death_day` is currently `None`). The generic death-clock branch at the top of the per-day loop then fires at the stamped day.

- **`condition_effects` extended:** The `day_ticks` entry dict now carries four new keys passed through from the stored tick: `"max_hp"` (may be `None`), `"save"` (may be `None`), and `"on_max_hp_zero"` (carried from the condition record itself, not the tick sub-object). Existing consumers reading `"hp"` and `"abilities"` are unaffected.

- **`disease` tool** (4 actions, FieldInfo-normalized, `tool_tags.py` entry `{Safety.GATED, Phase.REST, Domain.CHARACTER}`). Trigger line: `"Reach for this WHEN a PC is exposed to or contracts one of the six organic Vaarnish diseases ..."`.
  - **`list`**: browses all six diseases — Virulence, TN, and tick summary (or "no engine tick (prose rider)" for Wrathworms/Brain Coral). Pushes `disease(action="info", disease="<name>")`.
  - **`info`**: one disease in full — symptoms, cure, vector, rider, endpoint, stages. Pushes the `apply` call.
  - **`expose`**: DM lever. Optional `odds` param (N-in-M string) rolls a die and short-circuits if the PC isn't exposed; otherwise (or with no odds) emits a resist-save push: `disease(action="apply", character=..., disease=..., save_total=<resist total>)`. Appends a corpse tombstone note if the PC is dead.
  - **`apply`**: (1) immunity check — refuses Synth/Lithling unless `force=True`; (2) resist-save check — if `save_total` is provided and `>= tn`, nothing is applied; (3) duplicate check; (4) calls `build_disease_record`; (5) appends the record to `char["conditions"]`; (6) Brain Coral on-apply trade — rolls `d8`, drains STR via `_apply_ability_damage_from_wound`, routes the STR loss through `_check_death_gated` (Twinning-aware, window `day:{day}`); on a real death stamps HP -20, appends transformation prose + p.229 menu and skips the PSY gain; on a brink clamp (Twinning refusal) still skips the PSY gain; only on a confirmed-alive path does PSY gain apply; (7) saves; (8) emits an "Engine enforces" summary with the tick, the `on_max_hp_zero` vanish line, and the cure save reminder; pushes `condition(action="status")` and `condition(action="save", character=..., name=..., save_total=<cure roll>)`. Appends a corpse tombstone note if the PC is dead when apply is called.

- **`advance_day` CONDITION TICK — disease extensions** (in the existing tick block, after the generic death-clock branch, inside the day/week drain loop):
  - **Save gate** (`tick.save`, Lumenrot): engine rolls d20 + ability modifier (current slot value) vs the stored DC. A pass logs "save PASS ... no drain" and `continue`s; a miss logs "save MISS ... drain fires" and proceeds. Engine-rolled because multi-day advance cannot stall on a player roll (toxin-tick precedent); only the cure save is player-rolled.
  - **HP drain** (`tick.hp`): unchanged from E1 — calls `_apply_hp_damage_and_wounds`; breaks out of the drain loop on HP <= -20.
  - **Max-HP drain** (`tick.max_hp`, Labyrinth Pox): reduces `hp["max"]` by `_roll_drain(t["max_hp"])` (floor 0), clamps `hp["current"]` down to the new max. When `new_max <= 0` and the tick entry carries `on_max_hp_zero`, stamps `death_day` on the matching condition record (idempotent: only if `death_day is None`). The death-clock branch at the top of the per-day loop fires when that day arrives.
  - **Ability drain** (`tick.abilities`, Jellybones/Hivey Hump/Lumenrot): calls `_apply_ability_damage_from_wound` then `_check_death_gated` per ability. A real EGO/CON-to-0 transformation death: HP is snapped to -20, `_disease_death_prose` injects transformation text + body-state note above the p.229 menu, then the ability drain loop `break`s (one death readout, no post-mortem drains).
  - **Corpse guard inside the drain loop**: checks `hp["current"] <= -20` at the top of each tick-entry iteration and `break`s — a PC killed mid-catchup gets no further ticks.

- **`_disease_death_prose(char)`** — helper called at every disease transformation death. Iterates the PC's conditions, finds any with `cause="disease"` whose entry in `DISEASES` has a `transformation` key, and emits `"TRANSFORMATION (<name>): <endpoint prose>"` lines. Appends `"Body-state note: the corpse's condition (dissolved, vanished, hive-ridden) is a DM ruling on which p.229 paths remain open."` These lines are injected above the p.229 menu by both the ability-drain death branch and the generic clock death branch.

- **Disease catalog summary:**
  - *Brain Coral* (V1, TN 11): no tick; on-apply `d8` STR drain / PSY gain (Twinning-gated drain, PSY gain skipped on death); cure: antifungal.
  - *Wrathworms* (V2, TN 12): no tick; double-damage rider and EGO-save-to-retreat prose only (DM adjudicates, engine does not automate); cure: de-worming tinctures.
  - *Jellybones* (V2, TN 12): weekly STR `d4` + CON `d4` drain; AV/claw/bludgeoning prose riders (DM adjudicates); cure: Stiff Drink.
  - *Hivey Hump* (V3, TN 13): daily EGO `1` drain; transformation at EGO 0 (Hiveyman NPC, death-equivalent, Twinning-gated); swarm-attack progression rider (DM unlocks); cure: fumigation.
  - *Labyrinth Pox* (V4, TN 14): weekly `d8` max-HP drain; `on_max_hp_zero` stamps `death_in_days=3` (Stage 3 vanish, Twinning-gated); stage prose pushed (DM narrates apertures); cure: hypergeometric blade / Normality Fields.
  - *Lumenrot* (V5, TN 15): daily CON `1` drain, gated on a CON save vs DC 15 (engine-rolled); transformation at CON 0 (luminous slime, death-equivalent, Twinning-gated); cure: triple-syringe triad.

- **What is deliberately prose-only (DM adjudicates):** Wrathworm doubled-damage and EGO-save-to-retreat; Pox stage narrative (apertures widening, inventory-slot fiction); Jellybones AV/attack/bludgeoning modifiers; Hivey Hump swarm-attack unlock schedule. The engine drains the stats and gates the death; the DM narrates the in-world consequences.

- **Deferred (clean seams):** E3 nanomachine infections (pp.230-231) are explicitly out of scope here — the same `diseases.py` / `disease` tool architecture will extend to them. Auto-contraction hooks (no engine-side exposure rolls fired automatically), Wrathworm combat automation, Pox stage machine — none built.

<!-- ADDED 2026-06-11 — Documents E2 disease system (branch feat/disease). Verified against live code: diseases.py (DISEASES catalog, IMMUNE_SPECIES_STEMS, disease_susceptible_pc, build_disease_record), conditions.py (_is_amount, _norm_drain, normalize_record tick.max_hp/tick.save/on_max_hp_zero, condition_effects new keys), server.py disease tool (apply/expose/list/info, Brain Coral gated trade, corpse note), _roll_drain, _disease_death_prose, advance_day CONDITION TICK (save gate, max-HP drain, on_max_hp_zero stamp, ability-drain death break, corpse guard). Rulings R-E2a..f per the 2026-06-11 spec. Suite: 1466 passed / 1 xfailed. -->

### Nanomachine infections (E3, 2026-06-11)

Six nanomachine infections (CH pp.230-231, preview physical pp.236-237) running on the E2 Virulence engine — same `diseases.py` catalog, same `disease` tool (apply/expose/list/info), same `advance_day` tick machinery — plus three family-specific mechanics: (a) ability-slot occupancy (infection overwrites any pre-existing implant, leaving a marker the `cybernetic` tool sees); (b) DIS resist saves for Synths/cyborgs instead of immunity (nanomachines infect ALL creature types, but augmented bodies resist at Disadvantage); (c) The Gitch's full crystal loop (daily save-gated CON tick -> Gitch-Crystal wound per miss -> +1 AV and -1 infected ability per crystal -> Gitchghast transformation when all slots fill). Two small effect hooks also ship: half-HP Long/Short Rest regain (Janus Lenses) and double rations (Fabricator Stoma). Spec: `docs/superpowers/specs/2026-06-11-nanomachine-infection-design.md`; plan: `docs/superpowers/plans/2026-06-11-nanomachine-infection.md`. Rulings R-E3a..c. Book authority: `archive/rulebook-source/extraction/batch_08_locations_exotica.md` lines 2795-2893 (campaign repo; column-interleaved — the PDF read and spec catalog table are authoritative for numbers/prose).

- **`diseases.py` nanomachine family** — six new entries added to `DISEASES`, all with `family="nanomachine"`, a `slots` field (fixed list of ability names, or `"d6"` for The Gitch's rolled slot), and `cause="nanomachine"` stamped by `build_disease_record` (organic six keep `cause="disease"`, all twelve gain `family` fields: organic six get `family="organic"`). All nanomachine records are minted through the same `build_disease_record` -> `conditions.normalize_record` single-source path — no fourth record shape. Gitch special: because the catalog tick is save-only (no `abilities` drain until the consumer fires), `build_disease_record` rolls d6 -> STR..EGO for the infected slot and splices it into `tick["abilities"]` before routing through `normalize_record`; the rolled slot is stamped on the stored record (the crystal consumer reads it back via the `gitch` flag).

- **`disease_susceptible_pc(char, family="organic")`** — extended with a `family` kwarg (default `"organic"` preserves E2 immunity for Synth/Lithling). For `family="nanomachine"`, the function returns `True` for ALL PCs — nanomachines infect everything. The Synth/Lithling DIS line is surfaced separately by `nano_resist_dis`.

- **`nano_resist_dis(char) -> bool`** — returns `True` when the PC's species stem matches `"synth"` or `"lith"`, OR when any slot in `char["augmentations"]` holds a non-None, non-infection dict (i.e., any installed cybernetic). When `True`, the `disease` tool's `expose` and `apply` outputs append a `"SAVE WITH DIS (roll twice, take the lower)"` line.

- **`conditions.py` — two new effect keys** (additive, same pattern as `no_hp_regain`):
  - `hp_regain_half` — boolean; validated in `normalize_record` effects block and aggregated in `condition_effects`. A Long Rest halves the full HP restore (round down, min 1); a Short Rest halves the roll-and-heal advisory (round down, min 1). `no_hp_regain` wins when both are present (checked first).
  - `double_rations` — boolean; aggregated in `condition_effects`. Doubles food and water needs in `survival.daily_needs` (the parasitic-tag OR) and the `_rest_consume` multiplier site (same OR pattern). The `condition_effects` init dict adds both keys at `False`.

- **Slot occupancy (the family mechanic, `disease` tool `apply`)** — after the condition record is appended to `char["conditions"]`, the nanomachine apply block resolves target slots (fixed list from the catalog, or the tick's ability key for The Gitch's rolled slot). For each slot: if `char["augmentations"][slot]` holds an implant dict, the engine destroys it — reverses its `stat_bonus` using the `_cybernetic_remove` logic (dict branch for single implants, list branch for stacked implants; both branches pop `notes` after decrement), outputs `"<slot> slot: implant '<name>' is OVERWRITTEN - gone."`, then writes an infection marker `{"name": "INFECTION: <disease>", "infection": True, "disease": <disease>, "day_installed": day}`. If the slot is already None (empty), the marker is written directly. The output names every occupied slot and appends a cure-first reminder.

- **`cybernetic` install guard** — `_cybernetic_install` checks the target slot for an infection marker (`augs[slot]["infection"] == True`) BEFORE the standard slot-occupied rejection. A marked slot returns a rejection string (not a `ToolError`, so the DM sees it), with a push to `condition(action="save", character=..., name=<disease>, save_total=<cure roll>)` (label: "cure to free the slot"). The standard occupied-slot `ToolError` check follows unchanged.

- **`_clear_infection_markers(char, names)`** — helper called in both `condition` tool clear branches. Iterates `char["augmentations"]`, removes any slot whose value is a dict with `infection==True` and whose embedded disease name matches a name in the cleared-record list. Returns the list of `(slot, disease)` pairs cleared (for surfacing). Safe to call unconditionally (no-op when no markers exist). Called in: `all_conditions` branch (names = every cleared record name), single-clear branch (names = every matched record name, `[c.get("name") for c in matches]`), and the apply path's own overwrite (inline, not via this helper).

- **`_disease_death_prose(char)` extended** — widened from `cause == "disease"` to `cause in ("disease", "nanomachine")` so Gitchghast/somnambulist/Stoma transformation prose surfaces correctly at nanomachine transformation deaths.

- **Nanomachine catalog summary:**
  - *Goldencough* (V1, TN 11, slot CON): on-apply `d6` CON drain (gated Brain-Coral pattern; no gain side — unlike Brain Coral, Goldencough has no `ability_up`); `coughing_fit: True` in the catalog entry, read by `_condition_save_note` on CON saves (one-liner: "on a FAILED CON save, Goldencough triggers a coughing fit: d4 damage + an infectious golden-thread cloud (DM runs the fit)"). Cure: smoke-lodge day-long ceremony.
  - *Janus Lenses* (V2, TN 12, slot PSY): `effects.hp_regain_half: True`; Long Rest halves HP regain, Short Rest advisory halved. Cannot be ambushed asleep/from behind (prose rider). Cure: cybernetics surgeon.
  - *Usurper Arm* (V2, TN 12, slots DEX+EGO): condition record + `save_to_end` only; d6 locale rolled at apply (stored in note). Combat lever pushed as prose: EGO save to dominate (extra one-hand attack) or the limb turns hostile (Level 2, AV 17, d6; missed attacks vs the limb hit the host). Cure: surgeon (untrained amputation = regrowth via nanomachinery).
  - *Dreamcage* (V3, TN 13, slots INT+PSY): `effects.no_hp_regain: True` (Long/Short Rest never heals) + day tick flat `-1 PSY` (rides existing E2 ability-drain grammar, no new code); at PSY 0, hollow somnambulist (gated transformation death via existing `_check_death_gated` / `_disease_death_prose` seam). SOURCE: stats book-true (V3, INT+PSY); effects Joe homebrew R-E3a (preview PDF truncates mid-sentence). Cure save: CON vs 13.
  - *Fabricator Stoma* (V4, TN 14, slots STR+CON): `effects.double_rations: True`; daily metabolic hijacking doubles food and water. D6 extruded object rolled at apply (stored in note: 1 plasteel plate, 2 Autarch idol, 3 laspistol parts, 4 empty memory crystal, 5 negative-weight orb, 6 gaming dice). Cure: surgeon, "not cheap."
  - *The Gitch* (V5, TN 15, slot rolled d6 -> STR..EGO): full crystal loop (R-E3b) — see Gitch loop section below.

- **The Gitch crystal loop (`advance_day` CONDITION TICK, R-E3b)** — inside the existing ability-drain block, keyed on `c.get("gitch") == True` on the condition record. When the engine-rolled CON save (dc 15) misses, the drain fires (`-1` to the rolled slot ability via `_apply_ability_damage_from_wound`) AND a crystal is added:
  1. A wound record `{"name": "Gitch Crystals", "slots": 1, "av_bonus": 1, "gitch": True, "day": tick_day}` is appended to `char["wounds"]`.
  2. `char["wounds_slots_used"]` is recomputed as the sum of `r.get("slots", 0)` across all wound records (the E2 recompute-as-sum precedent).
  3. `_calculate_slots(char)` is called; `effective_free` (capacity - total_used - wounds) is read.
  4. The output surfaces crystal count and cumulative AV bonus: `"Gitch crystal forms in an item slot (Day N) -- +X AV (Gitch plating), X slot(s) crystal-filled, effective free Y"`.
  5. **Gitchghast endpoint**: when `effective_free <= 0` (all available slots crystal-filled, including the encumbered/over-capacity edge), HP is snapped to -20, `_death_gate` is called (Twinning-aware), and on a gated-allowed death the output emits `"!!! <name> becomes a mindless GITCHGHAST"` + `_disease_death_prose` transformation prose + p.229 resurrection menu. On a Twinning-brink hold, the transformation is refused and the crystal output already emitted stands.
  6. After the Gitch block, `_check_death_gated` is called for the ability drain itself (the standard ability-drain death check, e.g. CON-to-0 independently triggers it).

- **The real AV combat hook** — `wounds.derived_effects(wounds)` aggregates `av_bonus` (initialized to 0 at line 143, accumulated beside `av_penalty` at line 158: `eff["av_bonus"] += r.get("av_bonus", 0)`). `_defender_av` (server.py, PCs only — enemies return early before this seam) reads both: `max(0, base_av - _deff["av_penalty"] + _deff["av_bonus"])`. Each Gitch-Crystal wound record carries `av_bonus: 1`; the crystals heal via the existing wound-heal flow (crystal wounds clear with the standard wound tool), and the AV bonus heals for free with them. The `+N AV (Gitch plating)` line also surfaces in `wound(action="status")` derived-effects summary and in the reflex WOUNDS block (`hooks/phrase_reminder.py` `_wound_parens`, "+N AV (Gitch)").

- **Effect consumers:**
  - Long Rest (server.py `_rest_long`): after the `no_hp_regain` gate (which wins), checks `hp_regain_half` — if True, computes `gain = max(1, full // 2)` (round down, min 1) and applies that partial restore instead of full max HP. Engine-applied (not advisory) because long rest is a DM-called guaranteed action.
  - Short Rest (server.py `_rest_short_calculate`): after the `no_hp_regain` gate, checks `hp_regain_half` — if True, surfaces `"heals HALF of (d8 +/- CON), round down, min 1 (Janus Lenses)"` advisory text. Short-rest healing is player-rolled by design (D&D-style, the engine does not apply it); the halving advisory is the correct surface.
  - `_rest_consume` (server.py): the `double_rations` condition effect is OR-ed into the parasitic-tag multiplier: `_dbl = _sv.condition_effects(char.get("conditions") or [])["double_rations"]`; if True OR parasitic-tagged, multiplier = 2.
  - `survival.daily_needs` (survival.py): same OR pattern at the `daily_needs` site: `condition_effects(...)["double_rations"]` doubles food and water alongside the parasitic-tag check.

- **Prose riders (DM-adjudicates, pushed not automated):**
  - Usurper Arm combat: EGO save to dominate the arm (extra one-hand attack, on a fail the arm turns hostile — Level 2, AV 17, d6; missed attacks vs the limb count as hits on the host). Pushed in the apply output; DM runs the arm as an NPC statline.
  - Goldencough coughing fits: triggered by any failed CON save anywhere the PC makes one — surfaced by `_condition_save_note` as a one-line reminder (d4 damage + infectious golden-thread cloud). The fit and cloud are DM fiction; the engine only reminds at the save moment.
  - Gitch settlement exclusion: when crystals are visible, settlement NPCs refuse entry — DM narrates; the engine does not automate NPC reactions.
  - Fabricator Stoma extrusion: the same mass-produced object is extruded each morning (painful); cure multi-day surgery. Both are DM narration.

- **What is out (deferred, clean seams):** Usurper Arm combat automation (EGO-save dominate / hostile-limb NPC loop); Goldencough coughing-fit automation (fires on ANY failed CON save anywhere — the engine only reminds, does not intercept every CON roll); Maladaptor / Gitchghast bestiary entries (bestiary work, not this cycle); Gitch-dust environmental exposure automation (DM lever via `disease(action="expose")`).

- **DM notes (design-awareness, opus-review additions):**
  - A Twinning-brink-held Gitch PC continues accumulating crystals (and +AV) past slot capacity each day the Twinning gate refuses transformation. "Consequences stand" semantics: the brink hold does not stop the crystal loop; only curing the Gitch stops it. The mounting AV is real, the mounting slot pressure is real, and the Twinning partner's life is the only thing holding the transformation back.
  - A PC infected in their CON slot transforms roughly twice as fast as baseline: the `-1 CON per crystal` drain also shrinks slot capacity (CON governs carrying capacity in this engine), meaning each missed save reduces both free slots AND capacity simultaneously — a compounding effect that accelerates the Gitchghast endpoint.
  - A PC already encumbered (carrying capacity exceeded) transforms on the FIRST missed save: `effective_free` is already <= 0 before any crystal forms, so the Gitchghast check fires the moment the first crystal is appended and the recomputed `effective_free` is read.

<!-- ADDED 2026-06-12 — Documents E3 nanomachine infection system (branch feat/nanomachine-infection). Verified against live code: diseases.py (six nanomachine DISEASES entries with family/slots, nano_resist_dis, disease_susceptible_pc family kwarg, build_disease_record cause=nanomachine + Gitch slot roll), conditions.py (hp_regain_half + double_rations in normalize_record + condition_effects), server.py disease tool (nanomachine apply slot-occupancy block, implant overwrite stat_bonus reversal, INFECTION marker write, _clear_infection_markers in both clear branches, DIS line on expose/apply), cybernetic install infection-marker guard, _rest_long hp_regain_half halving, _rest_short_calculate advisory halving, _rest_consume + survival.daily_needs double_rations OR, advance_day Gitch crystal loop (save-miss -> wound append -> slots_used recompute -> effective_free check -> Gitchghast _death_gate), wounds.derived_effects av_bonus init+accumulate, _defender_av max(0, base-penalty+bonus), _disease_death_prose widened to cause=nanomachine, _condition_save_note Goldencough coughing-fit note. Rulings R-E3a..c per the 2026-06-12 spec. Suite: 1515 passed / 1 xfailed. -->

### Resurrection paths (E5, 2026-06-12)

The five p.242 resurrection paths (Mycomorph Spores, Necrotech, Pseudo-Womb, Spirit, Ego-Engine) become engine-run mechanics: per-path timers ticked on `advance_day`, save prompts surfaced at the resolution moment, sheet surgery applied on resolve, and Spirit tracked as a live state with an HP-essence spend economy. **No new tool** (R-E5a: Joe ruling, tool-count concern): everything rides three new `character` actions. Spec: `docs/superpowers/specs/2026-06-12-resurrection-paths-design.md`; plan: `docs/superpowers/plans/2026-06-12-resurrection-paths.md`. Rulings R-E5a..c. Book authority: preview PDF physical p.242 (five paths); ability generation physical p.13 (3d6 per ability, the LOWEST die is the bonus -- the Ego-Engine reroll). Standard save verified batch_02 ~1668-1672: d20 + ability bonus, total >= 16 succeeds; natural 20 always passes, natural 1 always fails.

#### `character` tool: three new actions (R-E5a)

All resurrection mechanics ride the existing `character` tool (server.py). Three new action names are appended to `VALID_CHARACTER_ACTIONS` and three new params added to the `character` signature (all `Field(default=None/False)`): `path`, `save_total`, `natural_die`, `kind`, `target_level`, `replace`, `intact_core`. The second-line docstring action menu is extended for discoverability; the trigger-line (first line) is unchanged.

- **`character(action="resurrect", name=..., path=..., replace=False)`** (`_character_resurrect`) -- Begin a path on a corpse (`hp.current <= -20`). Vehicles and the living are refused. `path` is prefix-matched against `RESURRECTION_CATALOG`. A second begin call is refused unless `replace=True` ("two wombs, one soul"). Spirit is special: it mints no in-progress record -- the bid is immediate; the function pushes the literal `resurrect_resolve` call (`save_total=<d20+Level>`, `natural_die=<the d20 face>`) and returns. Mycomorph engine-rolls a d4 via `_roll_d4()`, stamps `due_day = day + d4`. Pseudo-Womb stamps `due_day = day + 7`. Necrotech and Ego-Engine carry no timer and push `resurrect_resolve` directly. The in-progress record `{"path", "began_day", "due_day", "resolved": False}` is written to `char["resurrection"]` (NOT into `char["conditions"]` -- the condition tick skips corpses by design; the resurrection tick is corpse-exempt). Campaign day is read as `data.get("meta", {}).get("campaign_day") or 0` (the disease-tool precedent).

- **`character(action="resurrect_resolve", name=..., path=..., save_total=..., natural_die=..., intact_core=False)`** (`_character_resurrect_resolve`) -- Apply the outcome. Standard save: `int(save_total) >= 16` passes; `natural_die == 20` forces pass; `natural_die == 1` forces fail. Resolved-guard: a already-resolved record refuses re-resolve (prevents re-running surgery on a living PC). Exception: `outcome == "spirit_failed"` blocks only path `"spirit"` (one bid per death); the other four paths remain legal on that corpse and `spirit_failed` does not trip the general resolved-guard for them.

- **`character(action="spirit_spend", name=..., kind=..., target_level=...)`** (`_character_spirit_spend`) -- The Spirit economy: `kind="touch"` spends d6 essence; `kind="possess"` spends d6 + `target_level`. Refused while faded (`spirit.faded_until` is an int) or without a `spirit` block. At 0 essence: `spirit.faded_until = day + 1`, Spirit condition note updated to `"FADED (returns sunrise Day N)"`. Otherwise: live essence updated in both `spirit` block and Spirit condition note.

#### `conditions.py` additions

- **`RESURRECTION_CATALOG`** (dict keyed by path name) -- five path entries, each with `label`, `timer` (`"d4"` / `"+7"` / `None`), `save` (`{"ability": ..., "dc": 16}` or `None`; Spirit uses `"ability": "LEVEL"` to distinguish its d20+Level bid from a standard ability bonus), `needs` (DM-confirm prose), `reminder` (the push prose surfaced at begin/tick outputs). Placed beside `RESURRECTION_PATHS` and `resurrection_push()` (unchanged). The `RESURRECTION_PATHS` death-push text (five-line p.229 menu, emitted at every real PC death since E1) is NOT modified.

- **`D6_ABILITY`** (dict) -- `{1: "STR", 2: "DEX", 3: "CON", 4: "INT", 5: "PSY", 6: "EGO"}`. Rolled at the begin step for any future path that needs a random ability slot.

- **`validate_resurrection_record(req, day) -> (record, "") | (None, error)`** -- Validates a begin request into a stored in-progress record. Mirrors `normalize_record`'s `(record, error)` signature. Checks `path` against `RESURRECTION_CATALOG`; validates `began_day` and `due_day` as integers. Returns `{"path", "began_day", "due_day", "resolved": False}`.

#### `advance_day` RESURRECTION TICK

A new block placed after the CONDITION TICK (which ends at ~line 6806) and before the WORLD PROGRESS comment (the 2026-06-12 WORLD TICK block — see *World Tick — play-loop slice 1* below — now sits between this tick and WORLD PROGRESS). The two ticks have deliberately opposite corpse semantics: the CONDITION TICK has a corpse guard (`hp.current <= -20: continue`); the RESURRECTION TICK has NO corpse guard (corpse-exempt by design -- resurrection records live ON corpses).

- Vehicle guard (`type == "vehicle": continue`) is kept.
- Multi-day idempotency: `r_elapsed = max(0, new_day - old_campaign_day)` (or 1 if non-int); the tick only runs when `r_elapsed > 0`.
- **Due-day push (timer paths):** for each character, if `char["resurrection"]` is an unresolved dict and `rec["due_day"] <= new_day`, the tick surfaces `URGENT: <name>'s <label> resurrection is DUE (Day N).` + the literal `resurrect_resolve` push (with `save_total=<d20+ABILITY bonus>` and `natural_die=<the d20 face>` for save paths; no save params for no-save paths). Does NOT auto-resolve -- the save is the player's.
- **Spirit sunrise (R-E5b):** if `char["spirit"]` is a dict and `spirit["faded_until"] <= new_day`, essence is restored to `spirit["max_essence"]`, `faded_until` is cleared to `None`, the Spirit condition note is updated, and `_save_single_character` is called. Output line: `"<name>'s spirit re-forms at sunrise (essence restored to N - engine ruling: a sunrise is a full reset)."` -- the full-reset is an **engine ruling** (the book says spirits fade and return at sunrise but does not state the returning essence; the engine treats a sunrise as a full reset, DM-adjustable via direct sheet edit).
- The `res_tick` accumulator is initialized beside `cond_tick = ""` and interpolated into the `advance_day` return string right after `{cond_tick}`.

#### `_character_resurrect_resolve` -- five path outcomes and sheet surgery

All resolve paths call `_save_single_character` once at the end (after all surgery), then push `condition(action="status", character=...)` for sheet verification.

| Path | Pass/fail | Sheet surgery |
|---|---|---|
| `pseudo_womb` | CON save >= 16 | **Both pass and fail:** `_revival_cleanup(char)`, HP set to max (`hp["current"] = hp["max"]`), `char["wounds"] = []`, `char["wounds_slots_used"] = 0` (clone has no scars -- Gitch-crystal AV bonus dies with the old body). Pass: record stamped `"pass"`. Fail: two `_roll_cacogen_mutation()` calls appended to `char["special_traits"]["mutations"]`, record stamped `"fail"`, both mutation names surfaced in output. |
| `mycomorph` | INT save >= 16 | `char["species"] = "Mycomorph"` (both pass and fail); `_revival_cleanup(char)`. Pass: Level/Gifts/abilities kept, record `"pass"`. Fail: `level = 1`, `xp = {"current": 0, "needed": 1}`, record `"fail"` + Level-1-rebuild push (engine does NOT rebuild). Ancestry-swap line always appended: `"ANCESTRY SWAP: <old_species> traits are now dead -- apply Mycomorph special rules"`. HP set DM-side (lever pushed). |
| `spirit` | d20 + Level >= 16 (natural_die honored) | Pass: `char["spirit"] = {"essence": old_max_hp, "max_essence": old_max_hp, "faded_until": None}`; Spirit condition minted on `char["conditions"]` (note carries essence count + spend rules). Body stays a corpse (`hp` stays at -20; the spirit block is the live surface). Record stamped `"spirit"`. Fail: record stamped `"spirit_failed"` (one bid per death; re-bid of `path="spirit"` refused by resolved-guard; other four paths re-pushed via `_cnd.resurrection_push()`). |
| `necrotech` | None (no save) | `_revival_cleanup(char)`, `char["synthetic_type"] = True`, record `"pass"`, downside reminder pushed (DM rules the mind-or-flesh decay), HP DM-set lever pushed. |
| `ego_engine` | None (requires `intact_core=True`) | `level = 1`, `xp = {"current": 0, "needed": 1}`, STR/DEX/CON rerolled via `_roll_3d6_lowest()` (lowest of 3d6 = the ability bonus, p.13; all three dice shown in output: `"N (3d6: X,Y,Z take lowest)"`); INT/PSY/EGO untouched. `_revival_cleanup(char)`, record `"pass"`, HP DM-set lever pushed. |

**Wounds rule:** `pseudo_womb` (pass and fail) clears `char["wounds"]` and `char["wounds_slots_used"]` to zero -- a clone body has no scars, and Gitch-crystal AV bonuses die with the old body. All other paths (`mycomorph`, `necrotech`, `ego_engine`) call `_wounds_survive_line()` instead: if wounds exist, the output surfaces `"N wound(s) survived death - DM rules which remain on this body."` The wounds are NOT cleared by the engine (the old body is reused/transplanted; DM makes the ruling).

**Twinning on revival:** `_revival_cleanup` pops `char["twinning_pending"]` (the death-pending mark). This severs the revived PC's own Twinning record. The partner's record is not touched by the engine; the existing `_twinning_partner_check` surfaces a severed-bond warning when the living partner's sheet is next checked. Re-bonding after resurrection is a DM/fiction call.

#### Helper functions

- **`_revival_cleanup(char)`** (server.py, placed beside `_clear_infection_markers`) -- The revival lever: `_clear_infection_markers(char, [c.get("name") for c in conds])` -> `char["conditions"] = []` -> `char.pop("twinning_pending", None)` -> `char.pop("spirit", None)` (removes a stale spirit block if the PC was previously a spirit and is now revived by another path). Does NOT save; the resolve caller saves once after all surgery. This replicates the `condition` clear-all branch trio internally -- calling the `condition()` MCP tool function is forbidden here (re-entrancy: the tool layer has its own load/find/save cycle).

- **`_roll_cacogen_mutation() -> dict`** -- Loads `CACOGEN_MUTATIONS.json` (engine rules-data via `read_rules_data`), rolls `dice.d100()`, returns `{"name", "effect", "source": "d100=N"}`. This is the single minting path for cacogen mutations: used by both `_character_level_up_proteus` (Proteus level-up) AND `_character_resurrect_resolve` pseudo-womb fail (check-the-generators discipline: one minting path, never copied).

- **`_roll_3d6_lowest() -> (int, list)`** -- Rolls three `dice.roll_notation("d6")["total"]` calls, returns `(min(rolls), rolls)`. The lowest value is the ability bonus (book p.13); `rolls` is the full list so the output can show all three dice. Monkeypatch target on the `server` module for tests.

- **`_roll_d4() -> int`** and **`_roll_d6() -> int`** -- Single-die wrappers via `dice.roll_notation("dN")["total"]`. Monkeypatch targets.

#### Spirit surfacing in the reflex block

The Spirit condition rides the existing `_build_conditions_block` (hooks/phrase_reminder.py) for free: it is a real condition minted on `char["conditions"]` with `name="Spirit"`. One 3-line branch added to `_build_conditions_block`: when the condition name is `"Spirit"`, the function reads `char["spirit"]` -- if `faded_until` is an int, appends `" - FADED (sunrise Day N)"` to the label; else if `essence` is an int, appends `" - essence N/M"`. The Spirit condition therefore surfaces in the per-turn reflex block as `"Spirit - essence N/M"` or `"Spirit - FADED (sunrise Day N)"` automatically, without a new reflex hook.

#### `nano_resist_dis` extended (diseases.py)

`nano_resist_dis(char)` gains a new first check: `if char.get("synthetic_type"): return True`. A Necrotech-revived PC's `synthetic_type = True` flag makes them resist nanomachine infestations with DIS (the same species-stem / augmentation check path) -- the Necrotech revival ALSO stamps the PC as Synthetic-type for all nanomachine-DIS purposes.

#### Record lifecycle and corpse semantics

The `resurrection` record lives on the corpse's sheet under the top-level `resurrection` key (not in `conditions`). On resolve it is stamped `{"resolved": True, "outcome": "<pass|fail|spirit|spirit_failed|...>", "resolved_day": N}` with the in-progress fields preserved as history. The tick treats `resolved == True` as inert and skips it -- consistent with the Deprived tombstone-record pattern. The condition tick (CONDITION TICK in `advance_day`) still skips corpses via its existing corpse guard; only the RESURRECTION TICK visits corpses.

**Spirit-pass body:** when `path="spirit"` passes, the body stays a corpse (`hp.current` remains -20). The condition tick therefore still skips the body (corpse guard fires). The spirit block on the sheet is the live surface for all ongoing mechanics; the Spirit condition rides the reflex conditions block.

#### What is out (deferred)

- **Level-1 auto-rebuild** (Mycomorph fail, Ego-Engine) -- the engine stamps species/Level/XP and pushes rebuild instructions; the actual stat/gift rebuild is a DM+player session.
- **Possession mechanics beyond HP-spend** -- what the spirit does while possessing a target is DM narration; the engine only deducts the essence cost.
- **Corpse-state flavor tables** (book physical p.243) -- DM color, out of scope.
- **Mycomorph-availability checks** -- whether a Mycomorph PC/NPC is actually present is fiction; DM confirms by making the `resurrect` call.

<!-- ADDED 2026-06-12 — Documents E5 resurrection paths system (branch feat/resurrection-paths). Verified against live code: conditions.py (RESURRECTION_CATALOG five paths with timer/save/needs/reminder; D6_ABILITY; validate_resurrection_record; RESURRECTION_PATHS + resurrection_push unchanged), server.py (VALID_CHARACTER_ACTIONS appends resurrect/resurrect_resolve/spirit_spend; character tool seven new params; _character_resurrect corpse guard + prefix-match + spirit-bid push + timer logic; _character_resurrect_resolve resolved-guard + spirit_failed exception + _passed() helper + five path branches + _wounds_survive_line + _stamp; _character_spirit_spend faded-guard + touch/possess cost + fade logic; _roll_d4/_roll_d6/_roll_3d6_lowest/_roll_cacogen_mutation helpers; _revival_cleanup clears conditions + infection markers + twinning_pending + stale spirit block, no save; advance_day RESURRECTION TICK corpse-exempt due-day push + spirit sunrise full-reset), diseases.py (nano_resist_dis synthetic_type OR), hooks/phrase_reminder.py (_build_conditions_block Spirit essence/faded branch). Rulings R-E5a..c per the 2026-06-12 spec. Suite: 1560 passed / 1 xfailed. -->

### Gambits (2026-06-12)

Book rule (CH p.29, extraction batch_03 ~56-95, verified): an attack total STRICTLY
higher than 20 after all bonuses lets the attacker attempt a stunt IN ADDITION to the
attack's damage. Engine surface (`server.py`, the `_combat_attack` hit path):

- `gambit_available = total is not None and total > 20` -- computed once on the hit
  path; auto-hits on unconscious targets carry `total=None` and never flag (no roll,
  and anything goes against the helpless). Fumble/miss `dm_result` blocks stamp the
  key `false`; the hit block stamps the real value.
- When available, a 4-line `*** GAMBIT AVAILABLE ***` block is appended between the
  damage line and the DM-only JSON: the book's menu (`_GAMBIT_MENU` -- Disarm STR /
  damage armour -1 AV STR / move again / force-or-pin STR / blind 1 turn DEX / steal
  DEX / dismount STR / any comparable feat) plus the forgo-damage-to-deny-the-save
  trade. ENEMY attackers flag with DM-facing phrasing ("DM: <foe> (intelligent foe)
  may attempt a stunt") -- the book grants gambits to intelligent NPCs.
- The TOX/poison reroute (which early-returns into the Toxin-Die flow) appends the
  same block when total > 20 (review catch -- a poison hit is still a hit).
- Resolution is DM-adjudicated end-to-end (engine-vs-DM rule): the engine never rolls
  the target's save and never applies a gambit effect; -1 AV, Blinded, disarms etc.
  are applied by the DM through the existing levers (`condition`, enemy stats).

Tests: `tests/test_gambits.py` (6 -- threshold strictness at exactly 20, hit-only,
miss-with-high-total, enemy DM phrasing, auto-hit exclusion, TOX-reroute survival).

<!-- ADDED 2026-06-12 -- Gambits feature (branch feat/gambits). Verified against live code:
_GAMBIT_MENU + _gambit_block + gambit_available computation and the three dm_result stamps,
the TOX-reroute append, tests/test_gambits.py. Book authority re-verified same day. -->

### C1 — Reactive / Triggered Abilities (2026-06-12)

PC sheets carry a structured `special_traits.triggers` list; the enemy→PC branch of
`_combat_attack` fires the ones whose conditions it can see deterministically (Joe
rulings R-C1a..d; spec `docs/superpowers/specs/2026-06-12-c1-reactive-triggers-design.md`).
Book-verified: Toxic Sap = Bloomboon #10, Acid Blood = Cacogen mutation #01, Mirrored
Leaves = Bloomboon #2 (extraction batch_03). Three `effect` enums are engine-run;
anything else degrades to a one-line `REACTIVE FLAG` (data-only extensibility):

- **`retaliate`** (Acid Blood, d4 acid): fires when an enemy hit applies damage
  and the attack is not ranged-marked (range field, or attack-name words
  bow/rifle/gun/sling/thrown/spit/beam/blast/ray); routed through the REAL
  `_combat_damage` enemy path -- resistances, defeat handling, morale, combat-end
  push all live, so a retaliation CAN kill the attacker. The retaliation passes
  `skip_round_advance=True` (a new keyword-only `_combat_damage` param): a reaction
  is not an action and never ticks the round. After a retaliation kill the gambit
  block is suppressed and `gambit_available` stamps false (`(no gambit - attacker
  defeated by retaliation)`), and `morale_broken` is computed AFTER the reactive
  firing so the JSON agrees with the prose (both opus review catches).
- **`tox_attack`** (Toxic Sap, d10 TOX): fires when the enemy attack NAME
  matches bite words (bite/biting/fangs/maw/jaws) -- on the TOX-reroute path it fires
  on the bite itself, before any PC damage resolves (deliberate, arguably MORE
  book-aligned: the book triggers on the bite). Rides the B1 Toxin Die machinery
  (`_toxin_attack_reroute`: enemy auto CON save, non-Biological immune with the line
  saying so). The trigger's `tox_die` is validated against the legal ranks at fire
  time; a typo'd value flags instead of dice_chain's silent "cured" no-op. The
  not-machine-visible "creature EATS part of the PC" case is a documented DM lever
  (combat docstring names the literal `toxin(action="check", ...)` call). Language is
  TOXIN/TOX throughout, never "poison" (R-C1d). The daily harvestable sap dose is
  sheet data only (DM-adjudicated until B2 Poisons).
- **`reflect_save`** (Mirrored Leaves): an enemy beam hit is reported but
  damage is WITHHELD -- the REACTIVE block names the player-rolled DEX save (book
  rule: total above 15 succeeds, batch_02 ~1669) and pushes both pre-filled
  `combat(action="damage", ...)` forks (FAIL -> PC takes it, SUCCESS -> reflected at
  the enemy). The pushed amount is post-crit, pre-resistance; the damage call applies
  resistance exactly once. dm_result stamps `reactive_pending: true` + the withheld
  amount. A beam attack that is ALSO a bite appends a note surfacing the swallowed
  `tox_attack` lever with a pre-filled `toxin` push.

`reactive` (list of fired trigger names, `[]` otherwise) is stamped on the hit, miss,
and fumble `dm_result` blocks like `gambit_available`; the TOX-reroute early return is
prose-only (pre-existing -- no dm_result block exists on that path). Triggers fire ONLY
on the enemy→PC branch; sheets without `special_traits.triggers` no-op at every layer.
Campaign sheets book-aligned per R-C1a (one sheet had drifted from the book's
d4-on-melee-damage), the Toxic Sap attack-entry trigger text corrected to bite/eat,
the Mirrored Leaves trigger minted (campaign commit `7460b2a`).

Tests: `tests/test_reactive_triggers.py` (23 -- retaliation damage/resistance/kill
incl. defeat handling + gambit suppression + morale stamp, ranged/miss/no-trigger
exclusions, bite pass+fail saves, claw exclusion, Synth immunity, beam withhold +
both forks + PC HP untouched, kinetic-normal, invalid tox_die flag, unknown-effect
degradation, round-advance isolation, beam-bite lever note, TOX-reroute + gambit +
reactive triple coexistence).

<!-- ADDED 2026-06-12 -- C1 feature (branch feat/reactive-triggers, f3082dd + 0dbaf0e).
Verified against live code post-review: _reactive_triggers_for/_fire_reactive_triggers,
the three hook sites, skip_round_advance, the gambit/morale post-retaliation fixes,
tests/test_reactive_triggers.py count. Spec-compliance review PASS; opus adversarial
2 MAJOR + 3 MINOR all fixed and pinned. -->

### C2 — Bloomboons (2026-06-12)

`character(action="level_up_bloomboon")` (pre-existing) extended to the book rule
and made mechanically real (rulings R-C2a..c; spec
`docs/superpowers/specs/2026-06-12-c2-bloomboons-design.md`). The curated
`NEOBLOOM_BLOOMBOONS.json` was certified against the book (CH p.049, extraction
batch_03 ~870-935): all 20 entries match -- the first curated table to pass clean.

- **Book repeat rule (found defect fixed):** the old code REROLLED repeats
  (rejection sampling); the book says "take the next Boon down." Now: a repeat
  d20 walks forward to the first un-owned boon, wrapping 20->1 (engine default;
  the book is silent past 20; the walk is noted in the output and stamped in the
  boon's `source`). All 20 owned = clean refusal that consumes nothing. Dedup is
  case-insensitive everywhere (review hardening).
- **`engine_effects` annotations on the table** (S2 foraging precedent;
  idempotent script `scripts/annotate_bloomboons_c2.py`, names-pinned against a
  hardcoded book list so it refuses a drifted table; `name`/`effect` text never
  altered): #1 av_base_bonus, #2/#3/#10 C1-schema trigger records (+#10's attack
  entry), #7/#8/#9/#15/#16/#18 daily_use, the rest dm_levers.
- **Level-up consumes engine_effects (R-C2a, deterministic auto):**
  av_base_bonus increments the AV base (int and `{"base": N, ...}` shapes;
  sibling keys like `conditional` preserved); trigger/attack/daily_use append
  with case-insensitive name-dedup (`special_traits.triggers` / `attacks` /
  `special_traits.daily_uses`); non-dict `special_traits` or non-list `attacks`
  warn loudly and skip rather than crash; dm_levers render as a prose block with
  the literal calls (deliberate: conditional player choices are not push-format
  NEXT steps -- spec-review-noted deviation); the result's NEXT block pushes
  `character(action="get", ...)`. Sheet surgery is transactional: one
  `_save_single_character` at the end, so a mid-stamp crash leaves the disk
  sheet untouched (adversarially verified with forced crashes).
- **`melee_missed` trigger kind (R-C2b, Barbed Bark d4):** a phase gate in
  `_fire_reactive_triggers` makes miss-kind and hit-kind triggers strictly
  disjoint in both directions. Fires on the enemy->PC MISS **and FUMBLE**
  branches (a flailing miss still meets the barbs -- pinned), same machinery as
  C1 (ranged exclusion, real `_combat_damage` with `skip_round_advance=True`,
  defeat/morale/combat-end handling); `reactive` and per-attack `morale_broken`
  stamped on the miss/fumble dm_results.
- **Campaign backfill (R-C2c):** a character-creation Toxic Sap minted as a
  proper `bloomboons` entry so the dedup/walk sees it (campaign repo; his C1
  trigger/attack entries untouched). `scripts/make_sandbox.py` copies the
  bloomboon table (same gap class the E5 smoke caught).
- Known cosmetic: an AV bump does not recompute a `conditional[].total` display
  value (combat math reads `base` and is correct; pre-existing manual-total
  pattern).

Tests: `tests/test_bloomboons.py` (21 -- walk/wrap/refusal, per-family stamping
incl. both AV shapes, dedup, push, real-table names-pin + unaltered-text +
script idempotency) + 9 Barbed Bark tests in `tests/test_reactive_triggers.py`
+ the rewritten next-down pin in `tests/test_xp_levelup.py`.

<!-- ADDED 2026-06-12 -- C2 feature (branch feat/bloomboons, a2b5d91 + 6673bb3 +
the hardening commit). Verified against live code post-review: the walk math, the
stamp consumers, the phase gate, annotation idempotency (sha-identical double run).
Spec-compliance review PASS (1 MINOR, the push-format deviation documented above);
opus adversarial: ship-ready, zero live-reachable defects, 2 MINOR hardenings
applied inline (case-insensitive dedup, non-list attacks warning). -->

### B2 — Poisons (2026-06-12)

The book's d20 Vaarnish Poison Generator (CH printed p.56) made mechanically
real (rulings R-B2a..c; spec `docs/superpowers/specs/2026-06-12-b2-poisons-design.md`).
Assembly over existing machinery: no new tool.

- **`VAARNISH_POISONS` certified table** (server.py, directly below
  `HYPERGEOMETRIC_MISHAPS`): 20 rows carrying verbatim book fields (`colour`,
  `form`, `delivery`, `effect_text` — pinned by tests) plus structured
  `engine_effects` (`save`: `none`|`con_vs_15`; `lesser`/`greater` effects of
  kind `tox`|`ability_loss`|`condition`|`max_hp_loss`|`death`). ONE d20 reads
  the whole row (single-roll table; per-column rolling would be invented).
- **Application (R-B2a save fork)** — two new actions on the `toxin` tool,
  dispatched through `_toxin_dispatch`:
  - `poison_apply(target=, poison=)`: `poison` is a row number 1-20 or an
    inline record (JSON dict; `_poison_record` is the single resolver). Rows
    1-5 (pure TOX) have NO application save — the Toxin Die mechanic IS the
    save; they route straight to `_toxin_attack_reroute` (B1). Other rows:
    CON save vs flat **TN 15** (`POISON_SAVE_TN`, engine default — the book's
    beam-reflection "above 15" is the only flat-save precedent). PC targets
    get the push to `poison_resolve` (player rolls, Iron Law 3); enemies
    auto-roll `_poison_enemy_save` (d20 + Level, cap +10).
  - `poison_resolve(target=, poison=, save_total=)`: save passed -> lesser
    effect (None for slashless rows 16-19 = fully resisted); failed -> greater.
  - **Immunity first, ALL rows** (`_poison_immune`): the B1 PC check (Synth
    species, `toxin_immune`, "immune to poison" physiology) plus an
    `augmentations` scan for "immunity to all poisons" (Cyberliver); enemies
    use TOX-equivalence (non-Biological).
  - **Effect routing** (`_poison_resolve_effect`, injectable `rng`):
    ability_loss via `_apply_ability_damage_from_wound` (row 11 greater =
    ONE d8 applied to both INT and PSY, `single_roll`; an ability driven
    below -10 is a real death and routes through `_poison_death` exactly like
    row 20 — adversarial M2 fix); conditions via the E1
    `conditions.py` substrate (durations roll the die and stamp `until_day`;
    permanent rows mint no-expiry records + a DM-lever line); row 20 lesser =
    max-HP cut with current clamped (death when max reaches 0); row 20
    greater = `_poison_death` — HP snapped to -20 then the REAL gated seam
    (`_death_gate(cause="poison")`, Twinning honored, p.229 resurrection push
    on an allowed death). Enemy targets get prose only for non-TOX effects
    (enemies carry no ability/condition records).
- **`until_day` condition auto-expiry** (new substrate): `conditions.normalize_record`
  passes `until_day` (int) through; the advance_day condition tick sweeps each
  PC's conditions AFTER the day's ticks have run (a condition gets its final
  day's effect) and clears any with `current_day > until_day`, surfacing the
  expiry line. Corpses are skipped by the existing corpse guard.
- **Weapon coating (R-B2b)** — `toxin(action="poison_coat", target=<PC>,
  weapon=, poison=)` stamps `poison_coating` `{label, poison}` on the carried
  weapon record (`_find_weapon_record`, substring match); re-coating an
  already-coated weapon surfaces "REPLACED (lost)" for the old dose
  (adversarial m1 fix); an inline record whose `name` matches a carried item
  consumes that dose item. In `_combat_attack`'s PC->enemy hit branch (after
  damage + defeat handling, mirror of the C1 firing sites): the coating is
  POPPED before the apply (`_consume_weapon_coating` persists the pop on a
  fresh sheet load, matching the disk record by equal-coating identity with
  exact-name disambiguation — never fuzzy substring alone, so name-colliding
  inventories cannot let a spent dose re-fire; a failed disk match surfaces a
  loud WARNING — adversarial M1 fix), then `poison_apply` fires at the
  target; `dm_result["poison_coating_fired"]` stamped; prose notes the
  coating spent. Misses/fumbles never consume; a crit is one dose; the next
  hit is clean.
- **Generator** — `generate(action="poison", roll=<optional 1-20>)`: one d20
  (injectable rng), full row + `_pf` push lines (the pre-filled
  `poison_apply` call; weapon-coat rows also push `poison_coat`).
- **Daily-use runner (R-B2c)** — `character(action="use_daily", name=,
  daily=)` -> `_character_use_daily`: finds the `special_traits.daily_uses`
  entry (case-insensitive), refuses when `last_used_day >= today`
  (availability is `last_used_day < today`; no reset sweep exists or is
  needed), stamps the day, and executes an optional `engine_effect.mint_item`
  into `inventory.carried` (same container/id/day stamping as the inventory
  add path). Poison-typed mints push the coat/apply calls. C2's data-only
  entries keep working (stamp + note, DM adjudicates). The relevant live sheet
  gained the "Harvest Toxic Sap" entry (campaign repo, mints a d10 TOX
  "Toxic Sap dose" inline-poison item — closes the C1 R-C1d IOU).

Out of scope (per spec): antidote brewing (B5; POT = toxin strength mapping
recorded there), airborne/catalyst exposure automation (DM adjudicates, then
`poison_apply`), NPC-vs-NPC poisoning.

Tests: `tests/test_poisons.py` (78 — verbatim table pin + schema, until_day
normalization/expiry/survival, all five effect kinds incl. the death gate
(`cause="poison"`) and single-roll row 11, immunity short-circuit, enemy
auto-resolve, inline records, tool wiring + trigger line, generator pushes,
coating stamp/fire/miss/second-hit/crit, daily-use stamp/refuse/mint).

<!-- ADDED 2026-06-12 -- B2 feature (branch feat/poisons). Every claim above
verified against the shipped code at write time: table constant + pins,
POISON_SAVE_TN=15, dispatch branches, _poison_resolve_effect routing,
_poison_death gate cause, conditions.py until_day passthrough + advance_day
sweep placement, _consume_weapon_coating pop-before-apply, _character_use_daily
availability rule, campaign sheet commit. -->

### B3 — Elixirs (2026-06-13)

The book's d100 Example Elixirs table (CH printed pp.53-54) made mechanically
real (rulings R-B3a..e; spec `docs/superpowers/specs/2026-06-13-b3-elixirs-design.md`,
plan `docs/superpowers/plans/2026-06-13-b3-elixirs.md`). Assembly over the B2
machinery + a new Exploration-Turn duration substrate. No new tool — two new
actions (`generate(action="elixir")`, `character(action="drink_elixir")`).

- **`VAARNISH_ELIXIRS` certified table** (server.py, directly below
  `VAARNISH_POISONS`): 40 rows carrying verbatim book fields (`name`,
  `component`, `pot`, `effect_text`, `application` = `drink`|`topical`|`inject`,
  pinned by tests) plus a structured `engine_effects` dict keyed by `kind`. ONE
  d100 reads the whole row (`_elixir_row_for`). **R-B3a** fixes the book's
  overlapping 43-45/44-46 typo by an even split — Glittercough 43-44 (row 15),
  Growth Serum 45-46 (row 16); `test_band_coverage_exact` proves 1-100 maps to
  exactly one row. **R-B3b** assigns Pupeteer 4 Exploration Turns (book text
  cut off).
- **engine_effects kinds** (the taxonomy `_elixir_apply_effect` dispatches):
  `prose_only`, `condition`, `av_bonus`, `ability_mod`, `hp_regen`,
  `hp_set_zero`, `hp_floor`, `resurrection`, `save_fork`, `gift_mint`,
  `sheet_surgery`, `follower_mint`.
- **Exploration-Turn duration substrate (new):** `conditions.normalize_record`
  now passes through `until_turn` (int), `turn_map` (str), `revert` (snapshot
  dict), `derived_effects.av_bonus` (int), and `hp_floor` (int).
  `conditions.expire_turn_conditions(char, map_name, current_turn)` clears the
  conditions whose `until_turn` has passed on THIS map and applies any `revert`
  via `_apply_revert` (HP is the `{"current","max"}` dict; restored current =
  `min(live, snapshot)` — expiry NEVER heals; armed triggers are disarmed via
  `revert.remove_trigger`). `map_system.MapSystem.advance_turns` fires a
  registered `turn_hook(map_name, current_turn)` AFTER the counter advances;
  `server._expire_turn_conditions_for_map` (bound as `map_system.turn_hook`
  near the loaders) sweeps every PC, persists, and returns wear-off lines that
  prepend the encounter output. `get_map_state` defensively stamps `map_name`.
- **Duration stamping (`_elixir_duration_stamp`):** `{"days": N}` -> `until_day`
  failsafe; `{"turns": N}` -> `until_turn`/`turn_map` when a vault clock is
  active (`_active_vault_turn` reads CURRENT_STATUS.md 'Active Map' ->
  `map_system.get_map_state`), ELSE a DM-paced note. Every ET condition ALSO
  gets a `day + 1` `until_day` failsafe so it can never leak past the next day.
- **`character(action="drink_elixir", name=, elixir=, target=, save_total=)`**
  (`_character_drink_elixir`): (1) physiology guard — Synthetic/Mineral PCs
  cannot DRINK (topical/inject bypass, CH p.51); (2) consume a matching dose
  item from inventory (loud WARNING if absent, never blocks); (3) apply the
  effect by kind. `_elixir_record` accepts a row index 1-40, a d100 roll, or an
  inline JSON record (mirrors `_poison_record`).
- **Death-seam rows (full-depth review):**
  - **Death Draught (R-B3e, `hp_set_zero`):** book-literal — snap to 0 HP and
    fire the SAME `_apply_wound` combat uses (biological/synthetic table).
  - **Immortality Injector (R-B3d, `hp_floor` = -19):** mints a `Deathless`
    condition carrying `hp_floor`. `_elixir_hp_floor(char)` is read at the two
    HP-reduction sites in `_apply_hp_damage_and_wounds` (the normal subtraction
    AND the Death's-Door lethal snap) to clamp damage at the floor, and as a
    belt-and-braces guard at the top of `_check_death_conditions` (a Deathless
    PC cannot die from HP/slots/abilities even via a direct `update_hp` to -20)
    while the floor is active.
  - **Kalotoxin (`save_fork`, save=None):** transformation death routed through
    the REAL gated seam (`_death_gate(cause="Kalotoxin ...")`, Twinning honored;
    on refusal HP held at -19 and the half-state is the DM's).
  - **Two-phase save forks (Glittercough/Pupeteer):** PC target rolls
    (`save_total` TN 15, two-call push like B2); enemy target auto-resolves via
    `_poison_enemy_save`. Targets resolve through `_resolve_target_char` (self
    first, then a roster walk) so it works under both loader shapes.
- **Lazarus Tonic = sixth E5 resurrection path (R-B3c):** a sixth entry in
  `conditions.RESURRECTION_CATALOG` (`lazarus_tonic`, timer None, save None).
  The `resurrection` kind validates the corpse (`_lazarus_eligible` — biological
  AND `hp.current <= -20`, the same predicate E5's resurrect-begin uses) and
  pushes the `character(action="resurrect" / "resurrect_resolve",
  path="lazarus_tonic")` pair. The resolve branch restores life (revival
  cleanup + HP to max, wounds survive) at the cost of one Level.
- **Push kinds:** `gift_mint` pushes `gift(action="add", ...)` per gift (G1's
  real action name; temporary gifts also mint an expiry condition);
  `sheet_surgery` pushes a PERMANENT note; `follower_mint` rolls the count die
  and pushes an npc/lorebook record (Broodlings are a minion swarm, not D2
  recruit-table followers).
- **until_day failsafe parity (Task 10):** `conditions.expire_day_conditions`
  applies the SAME `_apply_revert` as the turn sweep; the advance_day until_day
  sweep now calls it, so a turn-duration elixir that outlives its vault restores
  stats at the day failsafe instead of leaking doubled STR forever.
- **`_defender_av`** now adds condition-side `derived_effects.av_bonus` (Plating,
  Spineskin, Lithification) on top of the wound-derived AV math.
- **Generator** — `generate(action="elixir", roll=<optional 1-100>)`:
  `_generate_elixir` (injectable rng) renders the row + the pre-filled
  `character(action="drink_elixir", ...)` push.

Out of scope (per spec): the permanent sheet-surgery rows are DM-applied via
the pushed `update_stat`/notes calls; Metamorphic/Cloning body generation is the
content-forge skill's job.

Tests: `tests/test_elixirs.py` (37 — table pins + band coverage, normalize
passthroughs, the turn-expiry sweep + map hook, `_defender_av` condition AV,
generator bands, the full drink path incl. physiology guard / dose / ET stamp /
ability_mod revert / Growth Serum double-and-revert, the death-seam rows
(Death Draught wound, Immortality floor, Kalotoxin gate, two-phase Pupeteer),
the Lazarus path, the push kinds, and day-failsafe revert parity).

<!-- ADDED 2026-06-13 -- B3 feature (branch feat/elixirs). Every claim above
verified against the shipped code at write time: VAARNISH_ELIXIRS constant +
pins, conditions.py until_turn/turn_map/revert/derived_effects/hp_floor
passthroughs + expire_turn_conditions/expire_day_conditions/_apply_revert,
map_system advance_turns turn_hook + get_map_state map_name stamp, server
_expire_turn_conditions_for_map binding, _character_drink_elixir +
_elixir_apply_effect kind dispatch, _elixir_hp_floor clamp sites +
_check_death_conditions guard, _lazarus_eligible + RESURRECTION_CATALOG sixth
entry + resolve branch, _defender_av condition av_bonus read. Suite 1987
passed / 15 pre-existing failures (flaky list). -->

### B4 — Drugs (2026-06-13)

The book's d20 Vaarnish Drug generator (CH printed p.45) made real as
`generate(action="drug")` — a flavour generator only, no mechanics
(spec `docs/superpowers/specs/2026-06-13-b4-drugs-design.md`).

- **`VAARNISH_DRUGS` certified table** (server.py, directly below
  `VAARNISH_ELIXIRS`): four INDEPENDENT d20 columns — `hue`, `form`,
  `ingested_by`, `effect` (1-20 each, verbatim book entries incl. the
  oddities Octarine/Ulfire, Drunk in Urine, Only Affects Synths, Behold
  Azathoth, Can't Stop Dancing).
- **`_generate_drug(rolls=None, rng=random.randint)`** rolls one d20 per
  column, but the EFFECT column is rolled **TWICE** (the book's
  "EFFECT (X2)" header) — five d20s total: hue, form, ingested_by,
  effect, effect. `rolls` accepts a 5-int list or a comma-separated string
  (tests/replays); otherwise random. Two effects render as `A + B`; a
  **doubled effect** (same row twice) collapses to one named effect with a
  "rolled twice -- DM adjudicates" note and a back-reference in the push.
- **Prose-only push.** The generator pushes a single
  `condition(action="apply", ...)` next-call so the high lands as a
  DM-ruled condition (duration DM-set). No usage die, no `engine_effects`.
- **R-B4a: addiction DEFERRED.** The preview book has no addiction
  mechanic; the roadmap's old "cost/addiction" framing was pattern-
  completion. No cost/addiction engine ships — revisit when the full
  edition lands.

Tests: `tests/test_drugs.py` (8 — table pins + verbatim oddities, forced
deterministic rolls, double-effect collapse, the condition push, comma-
string input, and the random-rng path).

### B5 — Alchemy (2026-06-13)

A **reference build** (CH printed pp.51-52; spec
`docs/superpowers/specs/2026-06-13-b5-alchemy-design.md`). **Decision:** ship
a certified rules card + a flavor generator, NOT a harvest/brew engine
(rulings R-B5a harvest is DM-manual, R-B5b brewing is reference-only, R-B5c
the brewed result is a B3 elixir row OR a custom elixir). Rationale (the
cognition-harness call): the gaps that bite at the table are rule-recall and
flavor, not item-by-item bookkeeping — so the engine surfaces the rules and
mints crucible flavor, and the DM runs the harvest/brew narratively. No state,
no mechanics, no new tool.

- **`ALCHEMY_REFERENCE_CARD` + `lookup(action="alchemy")`** (server.py, beside
  the crucible tables; dispatched **before** the `if not query` guard so the
  card needs no query). A static certified card covering: the Crucible (1 item
  slot, fire-proof, corrosion-resistant); Components (one harvested body part
  per creature, 1 slot, no stacking); the seven **Essence ↔ creature-type
  pairings** — Blood/Biological, Blue Ikor/Synthetic, Mycelium/Fungal,
  Psychespinal Fluid/Psychic, Manifold Marrow/Hypergeometric, Living
  Dust/Mineral, Paradox Bile/Outsider (doses = creature Level, up to 10 stack
  per slot; dual-type creatures pick one); **Potency calibration** POT 1 =
  mundane-item minor, POT 3 = Exotica-grade effect, POT 5 = permanent
  consequence (referee-set, most elixirs 1-3, effect tied to the creature);
  the **brewing rule** (heat + Crucible + receptacle; takes POT Exploration
  Turns, can't be truncated; 1 Component + Essences equal to POT, and the
  Essences MUST be of **different types**); the drinking rule (Synthetic and
  Mineral PCs cannot drink elixirs); and the **antidote POT mapping** —
  d6 TOX → POT 1, d8 → POT 2, d10 → POT 3, d12 → POT 4, d20 → POT 5 (this
  closes the IOU the B2 Poisons note banked). The card forward-references B3's
  `generate(action="elixir")` and `character(action="drink_elixir")` as the
  brewed-result flow.
- **`CRUCIBLE_QUALITIES` / `CRUCIBLE_SHAPES` (two d20 tables) +
  `generate(action="crucible")`** — one d20 on each table (quality + shape) →
  a named Crucible (e.g. "Quicksilver Pyramid"), 1 item slot, persists
  nothing; the DM decides if it enters play. `_generate_crucible(rolls=None,
  rng=random.randint)` accepts a 2-int list or a comma-separated string
  (tests/replays); otherwise random. Reuses the existing `generate` `rolls`
  Field (B4 added it for drugs) — description extended for crucible's
  `quality,shape`, no duplicate Field.

Tests: `tests/test_alchemy.py` (12 — both crucible tables full 1-20 + spot
pins, forced/comma-string/random-rng crucible paths, the card non-empty, all
seven essence pairings, the different-types + Exploration-Turn brew rule, POT
1/3/5 calibration, the exact antidote die mapping, the Synth/Mineral drink
bar, and the unchanged invalid-action tail).

### G2 — Hypergeometric Equations (2026-06-13)

A **data + one-generator** build (CH printed pp.57, 59-60; spec
`docs/superpowers/specs/2026-06-13-g2-equations-design.md`). It completes the
codex feature: the d20 mishap table (`HYPERGEOMETRIC_MISHAPS`) and the codex
reading flow (`codex(action=add/remove/use/mishap_roll)`) were already
book-true and live — **this build adds the equation content and a minting
generator, and changes NOTHING in the reading flow** (the INT save DC, the
Long-Rest lockout, and the natural-1 → `codex(action="mishap_roll")` push in
`_codex_use` are untouched). No state, no new tool.

- **`HYPERGEOMETRIC_EQUATIONS` certified d100** (server.py, directly below
  `HYPERGEOMETRIC_MISHAPS`'s closing brace): 40 rows, each `{"d100": (lo, hi),
  "name", "effect_text"}`. The `[INT]` notation (the reader's INT bonus,
  substituted at read time by `codex action="use"`) is preserved verbatim in
  every effect string — pinned by tests (≥30 rows carry it). Effects are
  DM-adjudicated prose; no `engine_effects`. **R-G2a:** the book prints
  overlapping d100 bands at 43-45 / 44-46 (the identical typo class as the B3
  elixir 43-45/44-46 overlap); even-split to 43-44 (row 15, Return Fixed
  Coordinates) / 45-46 (row 16, Return Random Coordinates), per the R-B3a
  precedent. A band-coverage test verifies 1-100 is covered exactly once.
- **`CODEX_APPEARANCES` d20** (server.py, beside the equations table): 20
  verbatim physical-form descriptions (CH p.57). Row 20's "Mobius" is
  ASCII-normalised from the accented book form (mojibake discipline).
- **`generate(action="codex")`** → `_generate_codex(roll=None,
  rng=random.randint)` (after `_generate_poison`, mirroring its FieldInfo guard
  and `_pf.push_call`/`_pf.next_block` idiom). Rolls (or force-rolls via the
  shared `roll` Field) one d100 for the equation, then one d20 for the physical
  appearance, and renders a codex card carrying the form, the equation name +
  band, the effect (with `[INT]` intact), and a prefilled
  `codex(action="add", character_name="<PC>", codex_name="Codex of <name>",
  equation_name=..., effect=...)` push for when a PC claims it (1 item slot).
  Returns text only; persists nothing. The `generate` docstring, the `action`
  Field, and the invalid-action tail were extended to list `codex`.

Tests: `tests/test_equations.py` (12 — both tables' counts + R-G2a band fix +
exact 1-100 band coverage + verbatim/`[INT]` spot pins; the generator's forced
roll, the R-G2a live bands, the `codex(action=add)` push, the d20-appearance
inclusion via injected rng, and the out-of-range rejection).

### World Tick — play-loop slice 1 (2026-06-12)

The engine spine for off-screen world forces across absences: clocks on narrative threads, fired by `advance_day`, briefed at session start, with return-after-absence change rolls on arrival. **No new tools** — everything rides `thread`, `advance_day`, `supply`, and `full_session_startup`. Spec: `docs/superpowers/specs/2026-06-12-world-tick-design.md`; plan: `docs/superpowers/plans/2026-06-12-world-tick-plan.md`.

**PILLAR — fired ≠ surfaced.** Firing a clock is an engine event; *surfacing* it is a fiction event. Nothing surfaces to the player except in narrative sessions: the engine fires, stamps, and nags the DM with pull handles, but the world change only becomes real when the DM narrates it and logs a thread development with `day >= fired_day`. Until that development exists, the fired clock reappears on EVERY session-start briefing. The other seams in this section (and the `supply`/E5 cross-references above) all defer to this rule.

#### Thread clocks (`thread` tool)

`thread` gained two params, `clock_due_day` / `clock_label`, honored on `add` and `update` (`0` = no change; `-1` on update clears the clock; `resolve` drops it). A wound clock is stored on the thread record as `"clock": {"due_day", "label" (defaults to the thread title), "wound_day" (introduced_day, else the current campaign day), "fired", "fired_day" (stamped once fired)}`. `_thread_list` renders a per-clock suffix line (⏳ DUE / 🔔 FIRED / ⏳ pending); `_thread_get` renders a **Clock:** line (label, due day, wound day, state). Generator day-defaults fixed in the same branch: `development_day` and `introduced_day` now stamp the current campaign day when unsupplied — a day-0 development could never satisfy the `day >= fired_day` surfacing check, and a day-0 thread read as ancient to the stale scan.

#### WORLD TICK in `advance_day`

A new block immediately after the E5 RESURRECTION TICK (same fail-warn try/except shape: failures log a warning and surface a `WARNING: world tick skipped` line, never corrupt state). On arrival at the new day it fires every due, unfired clock ONCE — stamps `fired=True`, `fired_day=<arrival day>` — and emits a **WORLD TICK** block with three pushes per due clock: `thread(action="get", thread_id=...)` (pull the thread), `search_campaign_history(query=<label>)` (pull related canon), and the adjudication-contract push `thread(action="update", ..., development_day=<arrival day>)` labeled LIVE NARRATIVE PLAY ONLY (recording = surfaced); the block header carries the PILLAR reminder (maintenance/dev sessions decide but never narrate or log — park notes as foreshadowing or a new clock). Push-only per the engine-vs-DM rule: the tick never resolves a thread. Malformed clocks (non-dict, non-int due day) are skipped.

#### Arrival stamps + return-after-absence rolls (`supply`)

`supply` gained a `location` param. `arrive` stamps `GAME_STATE["world_tick"]["last_visited"][<lowercased location>]` with the current campaign day — sourced from the same supply meta the ledger uses, guarded against the day-0 fallback (a missing/zero campaign day skips stamping rather than clobbering a real stamp) — and persists via `game_state.json` in all three persistence sites. On a return after `WORLD_TICK_RETURN_DAYS = 7`+ days away, the arrive output pushes the book's settlement-changes roll: `rulebook(action="get", id="table-changes-in-gnomon"|"table-settlement-changes", roll=<d6>|<d20>)` (Gnomon gets its own d6 table; the generic table is a d20). The whole block is fail-soft — a stamp failure can never fail an arrive.

#### ⏳ WORLD FORCES briefing (`full_session_startup` section 6e)

Read-only, fail-soft briefing of thread clocks, ordered: 🔔 FIRED-UNSURFACED first (the PILLAR's enforcement — persists on every briefing until a development with `day >= fired_day` is logged), then ⏳ DUE, then pending sorted by nearest due day. One line per thread, each carrying a `thread(action="get")` pull handle. Clockless threads idle more than 14 days collapse into ONE stale summary line (count + `thread(action="list")` push). The section is omitted entirely when empty.

#### Lifecycle skills (campaign repo)

The session anchors live in the campaign repo's lifecycle skills (campaign commit `3049011`): session-end gained Step 7.5 WORLD TICK RECORD (DM inference writes world deltas into engine state — wind/clear clocks, log developments); session-start's set-the-stage step consumes the WORLD FORCES briefing. Both carry the PILLAR.

Tests: `tests/test_world_tick.py` (33 — clock wind/clear/resolve lifecycle, tick fire-once + malformed-skip, arrival stamp boundary/round-trip + day-0 guard, briefing ordering/persistence/omission, generator day-defaults). Sandbox smoke: `scripts/smoke_world_tick.py`, all checks passed.

<!-- ADDED 2026-06-12 — World Tick, play-loop slice 1 (branch feat/world-tick, commits fb2df58/814665c/6d67b5c+2d896bd/644faa5/efe1315). Verified against live code: thread tool clock_due_day/clock_label params + clock record shape + _thread_list/_thread_get rendering + generator day-defaults; advance_day WORLD TICK block (after RESURRECTION TICK, fires ONCE, push-only, fail-warn); supply location param + last_visited stamp + WORLD_TICK_RETURN_DAYS=7 return push + game_state.json persistence; full_session_startup section 6e WORLD FORCES (fired-unsurfaced persistence, 14-day stale line, omit-when-empty); campaign lifecycle skills commit 3049011. Suite 1788 passed / 15 documented worktree-baseline failures; sandbox smoke green. -->

### Heartbeat Slice A — NPC World-Spine (2026-06-17)

Per-NPC purposeful autonomy: an NPC's `open_purpose` can carry a `purpose_clock` that fires automatically via `advance_day` at a DM-set pace. Spec: `docs/superpowers/specs/2026-06-17-heartbeat-living-world-design.md`; plan: `docs/superpowers/plans/2026-06-17-heartbeat-living-world-plan.md`.

**Pace vocabulary** (server.py `PACE_DAYS` constant). The DM picks a temperature word when writing `npc(action="continuity", pace=...)`:

| Pace | Interval |
|------|---------|
| `still` | never (no clock) |
| `cool` | ~30 days |
| `warm` | ~7 days |
| `hot` | ~3 days |

Pace is monotonically faster along the ramp still → cool → warm → hot. Blank / unrecognised = no clock (same as still). The engine owns what each word means in days; the DM chooses the label.

#### `purpose_clock` field

`_npc_continuity()` writes (or clears) `purpose_clock` on the NPC's `npc_states.json` record. Schema: `{"due_day": int, "label": str, "wound_day": int, "pace": str, "fired": bool}` (plus `"fired_day": int` once fired).

**Auto-plant behavior (spec 2026-06-18, `_HEARTBEAT_DEFAULT_PACE = "cool"`).** When `pace` is empty (the normal DM call), `_npc_continuity` applies the following decision table to the `else` branch:

| Condition | Action |
|-----------|--------|
| `open_purpose` set AND no existing clock | Auto-wind at `_HEARTBEAT_DEFAULT_PACE` (`"cool"`, +30 days) |
| `open_purpose` set AND clock exists AND `fired == True` | Re-arm: reuse stored `pace`, reset `due_day` from current day, clear `fired` and `fired_day` |
| `open_purpose` set AND clock exists AND `fired == False` | Leave clock untouched |
| No `open_purpose` | Leave clock untouched |

**Explicit-pace override.** A non-empty `pace` parameter always takes the outer `if pace and pace.strip()` branch (unchanged): plants/re-winds the clock at the given pace, or clears it for `still` / missing `open_purpose`. This overrides the auto-plant logic entirely.

#### HEARTBEAT SPINE tick in `advance_day`

A new block in `advance_day` (server.py, immediately after the WORLD TICK block). Same fail-warn shape as the thread WORLD TICK. For each NPC with an unfired `purpose_clock` whose `due_day <= new_day`:

1. Calls `_stamp_npc_changed_while_away(slug, note, day)` FIRST — each call persists `changed_while_away` to disk immediately (persistence-ordering caveat: stamping first, then re-loading and setting `fired` flags on the fresh data, prevents the two saves from clobbering each other).
2. Re-loads `npc_states.json` after all stamps, sets `fired=True` / `fired_day=new_day` on each fired record, saves once.
3. Emits a **WORLD TICK — PEOPLE** block with two pushes per fired NPC: `npc(action="get")` (pull the person) and `npc(action="continuity", ...)` labeled LIVE NARRATIVE PLAY ONLY (recording = surfaced, re-winds the clock).

Push-only: the engine never resolves what the person did off-screen. Fire is exactly once per clock cycle (re-winding in a `npc(action="continuity")` call resets `fired=False`).

#### "People moving on their own" in `full_session_startup` (session_tools.py §6e-people)

`_world_forces_people_lines()` (server.py) returns one briefing line per NPC whose `purpose_clock.fired == True` AND whose `changed_while_away.surfaced == False`. Each line is a pull-handle naming the person + their fired day + an `npc(action="get")` call. `full_session_startup` appends the lines under a `=== ⏳ WORLD FORCES (people) ===` header (§6e-people, immediately after the thread WORLD FORCES block §6e). Omitted entirely when empty.

The **fired ≠ surfaced PILLAR** applies: the clock fires (engine event) and stamps `changed_while_away.surfaced=False`; the person drops from the briefing only when the DM surfaces the change in fiction and calls `npc(action="continuity")`, which flips `surfaced=True` and re-winds the clock.

Tests: `tests/test_heartbeat_spine.py`. Suite covers: `_pace_to_due_day` all four vocabs + still/blank/unknown; `_npc_continuity` clock wind/clear/re-wind; `advance_day` heartbeat tick fire-once + idempotency + persistence-ordering (stamp before fired-flag save, no clobber); `_world_forces_people_lines` fired-unsurfaced visibility, drop-after-surface; full-session-startup integration (fired people appear in briefing; absent when empty).

<!-- ADDED 2026-06-17 — Heartbeat Slice A NPC world-spine (branch feat/heartbeat-living-world). Verified against live code: PACE_DAYS constant (server.py line 12285); _pace_to_due_day; _npc_continuity purpose_clock write/clear/re-wind; advance_day HEARTBEAT SPINE block (after WORLD TICK, ~server.py line 6638); _stamp_npc_changed_while_away persistence-ordering caveat (inline comment lines 6641-6648); _world_forces_people_lines (server.py line 12577); full_session_startup §6e-people (session_tools.py lines 402-412). Suite 2445 passed / 1 xfailed. Sandbox smoke: all 6 steps passed. -->
<!-- UPDATED 2026-06-18 — Auto-plant + re-arm behavior (branch feat/heartbeat-auto-plant, commit a126ca8). _HEARTBEAT_DEFAULT_PACE = "cool" (server.py line 12286); auto-plant else-branch in _npc_continuity (server.py lines 12546-12571); four-branch decision table: no-purpose/no-clock → auto-cool; fired → re-arm at stored pace; unfired → leave; explicit pace → outer override. Spec: docs/superpowers/specs/2026-06-18-heartbeat-auto-plant-design.md; plan: docs/superpowers/plans/2026-06-18-heartbeat-auto-plant-plan.md. -->

### Heartbeat Slice B — Crossings (2026-06-18)

When two **live seeds** — a thread clock or an NPC `purpose_clock` — touch the same **person** or **faction**, they have *tangled*. The engine **co-locates** the tangle and **forwards the raw relationship facts it already stores** (dispositions, faction standings); it computes **no** valence, charge, intensity, or scene directive. The DM judges opposed/allied/neutral and the volume; **silent coexistence is a first-class, default outcome.** This is RAG for the DM-model, invisible to the player. It works from **zero** (a new game has zero seeds → zero tangles → silence, no errors) and grows purely from play. Spec: `docs/superpowers/specs/2026-06-18-heartbeat-crossings-design.md`; plan: `docs/superpowers/plans/2026-06-18-heartbeat-crossings-plan.md`.

The helper cluster lives in `server.py` next to the Slice A heartbeat helpers (all after `_world_forces_people_lines`), and is purely **read-only** (forwards, never resolves, never writes):

- **`_crossing_collect_seeds()`** — gathers every live seed and **derives its strong tags at read time** (no stored field, no migration). An NPC seed is tagged to its own slug, its `location` (place, context only), and its `faction` if the record carries one; a thread seed is tagged to every roster NPC whose name appears in its title/description (the existing word-boundary name-match) and to a faction named in its text. Liveness: an NPC clock is live unless fired-AND-surfaced; a thread clock is live unless resolved or fired-AND a development dated ≥ `fired_day` exists.
- **`_crossing_detect()`** — a pure **group-by** over the seeds' person/faction tags; a tag shared by ≥2 distinct seeds is a tangle. A shared broad **place** is never a trigger (it rides along as context). Returns tangle dicts `{tag_type, tag, display, seeds, place, query}`.
- **`_crossing_facts()` / `_crossing_oneliner()` / `_crossing_block()`** — fact-forwarding (dispositions + faction rep, verbatim, no verdict) and the two renders: a quiet one-liner and a loud co-located block (seeds + facts + a `search` pull handle). **`_crossing_distillation_handle()`** adds an on-demand deep-history handle **only when a distillation already exists** for a tangled party (enrich, never found; zero-safe → `None`).
- **`_crossing_time_cluster_lines()`** — the weak §4 orientation crossing: when ≥2 live seeds fired in the same `advance_day` window (same `fired_day`), one "a lot moved while you were gone" line, even with no shared entity.

**Two surfacing channels** (mirroring Slice A): **quiet** — `_crossing_briefing_lines()` (tangle one-liners + time-cluster) is injected into `session_tools.py` via `_INJECTED` and appended under a `=== 🔗 WORLD FORCES (tangles) ===` header in `full_session_startup` (§6e-crossings, right after the §6e-people block; omitted when empty); **loud** — `_crossing_blocks_for_npc(slug)` is called from the always-runs NPC injection in `check_canon` so a tangle surfaces in-scene when the DM names an involved person. The loud channel threads the NPC **roster key** (`npc_id`, carried through `matched_npcs`) — not `name.lower()` — so titled NPCs whose key ≠ name (e.g. key `varn look-home` / name "Lord Marshall Varn Look-Home") surface correctly. §8: the case where one person has both a fired thread naming them and a due `purpose_clock` in one `advance_day` (a benign last-writer-wins on the stamp note) now surfaces as a single person tangle — an awareness comment marks the seam.

Tests: `tests/test_heartbeat_crossings.py` (23) — liveness predicates; detection (person/faction tangle, broad-place-does-NOT-tangle, single-seed-is-not-a-tangle, zero-state); fact-forwarding asserts NO verdict word leaks; distillation handle present/absent; quiet briefing + time-cluster; loud `_crossing_blocks_for_npc`; the divergent-key end-to-end `check_canon` regression; zero-data silence + person-tangle end-to-end smoke.

<!-- ADDED 2026-06-18 — Heartbeat Slice B Crossings (branch feat/heartbeat-crossings, commits 54d0bd7/4d9a4d1/144fd30/5591124/bdadfda/9180cc5 + I1 fix 5ff4f4c). Verified against live code: _crossing_* cluster in server.py after _world_forces_people_lines; _crossing_briefing_lines in session_tools.py _INJECTED + §6e-crossings block in full_session_startup; loud channel in check_canon NPC injection (matched_npcs now carries (npc_id, npc); _cx_slug = npc_id). Engine judges nothing / read-only / zero-safe verified by opus whole-branch review (found+fixed I1 slug round-trip). Suite 2473 passed / 1 xfailed. -->

### Heartbeat — Antagonist Spine (2026-06-18)

The `antagonist` cultivation tool was a **write-only box**: the DM cultivated threats into the engine-managed `ANTAGONIST_CULTIVATION.md` store (see §"Antagonist cultivation" above), but nothing clocked a seed, read the store back, triggered it mid-scene, or escalated it — and `_review_cultivation` auto-composted dormant seeds after 20 days. Proven empirically (a Day-129/130 audit: ~30 cultivated threats, **none** ever surfaced in play). The antagonist spine adds the surfacing half — the threat sibling of the NPC world-spine. The engine **clocks + surfaces + pushes a decision**; it judges nothing, never narrates the off-screen move, never auto-escalates/auto-resolves. Spec: `docs/superpowers/specs/2026-06-18-antagonist-spine-design.md`; plan: `…/plans/2026-06-18-antagonist-spine-plan.md`.

**The per-seed spine tag.** Each seed/threat carries an invisible-in-prose HTML comment one line after its `###` heading, parsed/written by `_antag_*` helpers (server.py, after `_review_cultivation`): `<!-- spine: due_day=<int|empty>; trigger=<comma keywords|empty>; level=<low|med|high|crisis>; fired=<bool>; fired_day=<int|empty> -->`. One file home, no sidecar. Helpers: `_antag_parse_spine_tag` / `_antag_format_spine_tag` (round-trip), `_antag_iter_seeds(content)` (both ACTIVE THREATS + DORMANT SEEDS → `{name, section, planted_day, spine, raw}`; name split on ` - Day planted:`/` - Escalation:` so hyphenated names survive), `_antag_set_spine` (insert/replace a seed's tag), `_antag_seed_is_protected` (live clock OR trigger OR fired).

- **`antagonist` tool gained `due_day` / `trigger` / `pace`** — `add_seed`/`add_threat` write the spine tag (`pace` maps to a `due_day` via the shared `_pace_to_due_day`); `escalate` moves a seed to ACTIVE THREATS and **re-arms** the clock (`fired=false`, fresh `due_day`/`level`) — the DM walks the ladder, the engine re-clocks.
- **ANTAGONIST TICK in `advance_day`** (`_antagonist_tick(new_day)`, after the HEARTBEAT SPINE block; `{antagonist_tick}` in the return) — fires every seed with `due_day <= new_day` and not fired, ONCE: stamps `fired`/`fired_day`, pushes a DECIDE block (escalate/hold/resolve). Push-only, idempotent, single clobber-safe save, fail-warn. fired ≠ surfaced.
- **`check_canon` trigger injection** (`_antagonist_trigger_blocks(input_lower)`, additive block after the NPC injection) — surfaces a seed when one of its trigger keywords is named in play (word-boundary match), capped 2 by severity. The engine surfaces; the DM judges whether/how it bites.
- **Session-start briefing** (`_antagonist_briefing_lines()`, injected into session_tools `_INJECTED`; `=== ☠ ANTAGONIST FORCES ===` block after §6e-crossings) — the read-back the store never had: every ACTIVE THREAT + any dormant seed whose clock fired (awaiting a decision).
- **Stop composting** — `_review_cultivation`'s 20-day auto-prune now spares any seed `_antag_seed_is_protected` (live clock/trigger/fired); only a truly-abandoned (no-clock/no-trigger/unfired) dormant seed is still pruned.

The **one-time ingestion** (assigning real `due_day`/`trigger` values to the campaign's existing ~30-seed backlog) is SEPARATE, private, campaign-side play-state work — not part of this engine spine (spec §7; ships-nothing-of-it to OSS).

Tests: `tests/test_antagonist_spine.py` (29) — tag parse/format/iterate/set (incl. hyphenated names); tool writes clock/trigger + escalate re-arm; tick fires/idempotent/zero-safe; trigger injection (helper + end-to-end through real `check_canon`); briefing read-back; prune exclusion; full-loop + zero-state smoke.

<!-- ADDED 2026-06-18 — Heartbeat Antagonist Spine (branch feat/antagonist-spine, commits 11736c2/ac73650/1b5792c/84d33c1/5aba497/30f656f/9bec3bf + M-A fix 567d725). Verified against live code: _antag_* + _antagonist_tick/_trigger_blocks/_briefing_lines in server.py after _review_cultivation; antagonist tool due_day/trigger/pace params write the spine tag + escalate re-arms; advance_day ANTAGONIST TICK ({antagonist_tick} in return); check_canon trigger injection (additive, after NPC block); _antagonist_briefing_lines in session_tools _INJECTED + §6e-threats block; _review_cultivation prune exclusion. Engine clocks/surfaces/pushes, judges nothing, push-only/read-only/zero-safe — opus whole-branch review READY-TO-MERGE (found+fixed M-A name truncation). Suite 2501+ passed / 1 xfailed; boot clean. -->

### G1 — Mystic Gift generation + Gleam Test (2026-06-12)

Book data (CH printed pp. 47-50; transcribed from the preview PDF — the text-extraction batches garble these pages) lives in **`gifts.py`**: `GIFT_QUALITY`/`GIFT_FORM` (each 20 rows × 4 d20 column-bands = 80 entries; the book's duplicate "Stone" in Form kept and test-pinned), `GIFT_SAMPLE` (d20 SOURCE OF POWER/GIFT pairs; row 12's column-wrap resolved by PDF word x-positions: source "Devouring Memories", gift "Inhuman Speed"), `GLEAM_TEST` (totals 16→35+, threat rows carrying structured `{threat, count_die, arrival_die}` clock metadata), and pure helpers `roll_gift_name`/`gleam_outcome`.

- **`generate(action="gift")`** — two d20s (column-band + row) on each of Quality and Form → the gift NAME (the book gives only the name; effect is agreed collaboratively). `sample=True` rolls the p.47 sample table instead. Text-only, persists nothing; pushes a prefilled `gift(action="add", …)`. Spec: `docs/superpowers/specs/2026-06-12-g1-mystic-gifts-design.md`.
- **`gleam_check` (book-true rewrite)** — the previous 20+/25+/30+ thresholds were INVENTED and are gone (test-pinned absent). Without `test`, reports Gleam (= equipped Gifts + PSY bonus, can be negative) and the real bands (1-15 nothing / 16-34 individual / 35+ cap) plus a `test=True` push. With `test=True`, rolls d20+Gleam on the p.50 table; threat outcomes roll their count/arrival dice and push a prefilled `thread(action="add", …, clock_due_day=<today+arrival>, clock_label=…)` — the WORLD TICK fires the arrival when due. Any test stamps `GAME_STATE["world_tick"]["gleam_last_test_day"]` (riding the already-whitelisted `world_tick` persistence key).
- **GLEAM TICK in `advance_day`** (after WORLD TICK, same fail-warn shape; Joe ruling 2026-06-12: engine owns the weekly cadence) — when 7+ days (`gifts.GLEAM_TEST_CADENCE_DAYS`) have passed since the stamp, pushes **GLEAM TEST DUE** with one exact `gleam_check(character_name=…, test=True)` call per gifted PC, repeating every advance until a test re-stamps the week. First-ever run seeds the stamp to the current day instead of back-nagging history. Giftless PCs are skipped.

Tests: `tests/test_gifts_data.py` (10 — data integrity incl. the Stone duplicate and row-12 geometry) + `tests/test_g1_gift_generator.py` (13 — generator, book-band output, threat clock push, cadence stamp/nag/clear, fail-soft). Reviewed (combined pass, APPROVE): all 160 table entries independently re-verified against the PDF.

### PC Generation — the formal method (2026-06-13)

The engine-enforced character creation procedure (CH printed p.5-6; Joe rulings R-PC1/R-PC2). NPCs stay in the content-forge skill (text-only); a PC writes a SHEET the engine owns for life — so PC generation lives on the `character` tool, two-step.

**`ancestries.py`** (data module, gifts.py pattern): `ANCESTRY_D10` + `ANCESTRIES` — all ten ancestries with `kind`, book-literal `special_rules`, `creation_hooks` (cacogen `{"mutations_at_creation": 3}`; lithling `{"hp_override_dice": "10d8"}` — its Inevitable rule replaces the d8 starting HP, never healable), and image-verified `spark_tables` (banded columns stored flat per row; newbeast's animal-form table is a two-d20 band table). Plus `GEAR_A`/`GEAR_B` (explorer's gear d20, structured `count`/`uses` fields) and pure helpers `ability_roll` (3d6, bonus = LOWEST die), `roll_ancestry`, `roll_sparks`, `roll_gear`. Transcription ground truth: the staged page images at `docs/superpowers/plans/data/spark_pages/` (the geometry-rebuilt JSON garbled banded columns — every cell was image-verified).

- **`character(action="create", name=…)`** — step 1: rolls the six abilities IN ORDER (3d6 each, lowest die = bonus), rolls a d10 ancestry suggestion, stashes the pending rolls in `GAME_STATE["world_tick"]["pc_create_pending"]` (whitelist-riding persistence), and pushes the prefilled finalize call. Nothing persists to the roster; the swap (the book's one player choice) and ancestry stay player-owned levers.
- **`character(action="create_finalize", name=…, ancestry=…, swap="STR,PSY"|"none", take5=…)`** — guards (stash present, valid ancestry, duplicate name/key rejected; failures keep the stash for retry), applies the swap, rolls HP (lithling override > take5 > d8), rolls the ancestry's spark tables, builds the sheet on the split-sheet schema (level 1, XP 0/1, AV 10 unarmoured, slots 10+CON, 3 water + 3 food rations carried, special rules ON the sheet, `wound_table` synthetic for Synths), writes via `_save_single_character`, clears the stash, then inline-rolls gear (both columns) + the d6 starting boon and returns every next call as a push: basic weapon, armour, `save_state(inventory_changes=…)` for the rolled gear, boon delegation (advanced weapon / B3-placeholder crucible item stamped into carried / cybernetic / exotica / codex / G1 gift), and cacogen's three mutations engine-rolled inline via the proteus helper.

Engine-readable fields the final review hardened: rations mint `ration_type`/integer `rations` (the supply tick's schema); per-ancestry survival flags land in `sheet["survival"]` where E1/S1 read them (Neobloom photosynthesis window armed at creation day; Lithling both needs off + biological wound-table note; Faa `death_days_thirst: 21`; Synth 3 Synth Parts); gear uses `usage_die`/integer `uses` (the U2 canonical fields); Lithling Crystalline Flesh stamps `av.base = 10 + Level (max 20)` at creation AND recomputes it in `_character_level_up`.

Tests: `tests/test_ancestries_data.py` (12 — data integrity, band-flat correctness, gear parse) + `tests/test_pc_creation.py` (20 — round trip, guards, swap/take5/lithling-override+level-up-AV, hooks, boon placeholder, engine-readable rations/gear/survival). Spec: `docs/superpowers/specs/2026-06-13-pc-generation-design.md`.

### D2 — Followers (2026-06-13)

Followers (CH p.61-62) as engine-tracked roster members, built on the PC-gen sheet spine. **`followers.py`**: `RECRUIT_TABLE` (the d20+EGO table, totals 0-30, banded LEVEL/HP·AV·ML stored flat per row — image-verified; the LEVEL and AV bands deliberately misalign, e.g. totals 16-20 are Level 2 but still AV 11), `roll_recruit`, and `follower_level_cap(characters, leader_key)` → `(cap=leader EGO bonus, used=sum of follower levels under that leader)` — built reusable for the D4 pets/steeds shared cap.

- **`character(action="recruit_follower", name=<leader>, follower_name=…, recruit_roll=…)`** — rolls d20 + the leader's EGO bonus, ENFORCES the cap before any write (reject reports the math), then writes a `type:"follower"` split sheet (leader key, `ml`, level/HP/AV from the row, all six abilities zero, slots 10+Level, the rolled attack minted via `ws.build_weapon` with an explicit ranged-attack allowlist, `wound_table` synthetic iff the description says Synth, 0 carried rations — followers eat from the party pool the daily tick already feeds). Pushes `relationship(set)` + `supply(status)` + the offer-not-hire reminder.
- **`character(action="follower_level_up", name=…)`** — +d8 max HP ONLY (no ability array), XP reset, slots recomputed; over-cap after growth is WARNED (the book caps command, not growth) with the dismiss push, never rejected.
- **`character(action="dismiss_follower", name=…, reason=…)`** — stamps `notes.departed`, then moves `characters/<key>.json` → `characters/departed/` (the loader globs only `characters/*.json`, so the move IS the roster removal; the file is preserved for return arcs).

Two push-only seams (engine computes, DM rolls): **morale on allied death** — a single `_death_seam_lines` helper now fronts all nine death-emission sites (it gates the five-path resurrection push to PCs only — followers never trigger it — then appends one `MORALE: … d20 + max(own ML, leader EGO) vs 15` line per living follower); **desertion watch** — the S1 daily tick, reusing the existing Deprived `since_day` counter, emits `DESERTION RISK: … (CH p.61)` + a `dismiss_follower` push once a follower hits 3 consecutive unfed days. Tests: `tests/test_followers_data.py` (48) + `tests/test_d2_followers.py` (26) + `tests/test_d2_follower_seams.py` (16). Spec: `docs/superpowers/specs/2026-06-13-d2-followers-design.md`. Unblocks D3 Mercenaries / D4 Pets & Steeds (the cap helper is shared).

### D3 — Mercenaries (2026-06-13)

Combat-specialist hirelings (CH printed p.63-64) as engine-tracked roster members, mirroring the D2 follower sheet spine — but on a SEPARATE command pool. **`mercenaries.py`**: `RECRUIT_TABLE` (the d20+EGO mercenary table, totals 0-30, banded LEVEL/HP·AV·ML stored flat per row — image+position-verified from `extract_words()` y-centers; the bands deliberately misalign across columns, e.g. total 25 = Level 8 but still AV 16 / ML +9), `roll_recruit`, and **`mercenary_level_cap(characters, leader_key)`** → `(cap=leader EGO bonus, used=sum of MERCENARY levels under that leader)`. This is a DISTINCT pool from D2: mercs and followers each have their own EGO-bonus cap (CH p.63 treats them as separate groups), so a leader's followers and mercenaries do NOT compete for the same room. (D4 pets/steeds pool with FOLLOWERS via `follower_level_cap`, never with mercs.)

- **`character(action="recruit_mercenary", name=<leader>, follower_name=…, recruit_roll=…)`** — rolls d20 + leader EGO, enforces the SEPARATE merc cap before any write, then writes a `type:"mercenary"` FIXED sheet (no `xp`/level-up path — mercs never level, CH p.63), with `pay_owed:False`, `carries_baggage:False`, the rolled attack minted via `ws.build_weapon` (a `MERCENARY_RANGED_ATTACKS` allowlist sets range; `damage` is stored as a raw string so the only multi-die row, Uck's 2d10 Nano-edged Greatsword, is preserved). Pushes `relationship(set, status="mercenary")` + `supply(status)` + the pay/sworn-foe reminder + the offer-not-hire note.
- **`character(action="mercenary_expedition_end", name=…)`** — `name` may be a LEADER (marks all that leader's mercs) or a single merc; sets `pay_owed:True` and lists who now owes a wage.
- **`character(action="pay_mercenary", name=…)`** — clears `pay_owed` (1 Exotica per expedition; reminds the DM to deduct the water-token wealth via `lorebook`); no-op note when nothing is owed.
- **`character(action="dismiss_mercenary", name=…, reason=…)`** — stamps `notes.departed` then moves the sheet via the shared **`_move_sheet_to_departed`** helper (extracted from `dismiss_follower`). DELTA: if `pay_owed` is True the merc leaves as a **SWORN FOE** (CH p.63) — the output pushes `antagonist(add_seed)` + a `thread(add, clock_due_day=…)` World-Tick revenge clock as callable next-steps.
- **`character(action="merc_morale_check", name=…)`** — manual lever (leader → all his living mercs, or one merc) emitting the `d20 + ML vs 15` morale line(s).

Two seams: **stoic morale** — mercs sit OUT the D2 per-death follower push entirely (`_follower_morale_lines` filters `type=="follower"`); `_merc_morale_lines` fires ONLY on a party WIPE, wired additively into `_death_seam_lines` when a PC death leaves `_all_pcs_down(data)` True (a PC is `type` absent/`"pc"`; "down" = `hp.current <= 0`; living mercs use their OWN ML, no leader-EGO substitution). **Pay nag** — `_mercenary_pay_nag_lines` emits one `⏳` line per owed merc, wired into `advance_day` next to the GLEAM tick (nags daily while owed — the `pay_owed` flag IS the state, no `world_tick` stamp). Tests: `tests/test_mercenaries.py` (11) + `tests/test_d3_mercenaries.py` (20). Spec: `docs/superpowers/specs/2026-06-13-d3-mercenaries-design.md`; plan: `docs/superpowers/plans/2026-06-13-d3-mercenaries.md`.

### D4 — Pets & Steeds (2026-06-13)

Tame animals (pets) and mounts (steeds) as fixed-stat-block roster hirelings (CH printed pp.65-72), built on the D2/D3 sheet spine. **`pets_steeds.py`**: two image-verified catalogs — **`PETS`** (11 entries: Volt Rat, Bonsai Triffid, Glue Worm, Companion Ooze, Exultant's Hawk, Mycomastiff, Pet Rock, Little Torino, Ray Cat, Skunkey, Synthhound) and **`STEEDS`** (8 entries: Burden Bird, Crysteed, Destrier, Striding Fool, Thin Mare, Weeping Lizard, War Camel, Zorse) — each row carrying `name`/`kind`/`level`/`av`/`morale`/`attack`/`special`/`survival`, steeds adding `item_slots` cargo capacity (the Thin Mare's is `"Special"`: up to 100 slots, d100-vs-slot retrieval). `pet_block(slug)`/`steed_block(slug)` return deep copies so a mutated sheet never corrupts the catalog. Survival is modelled as `{"needs_food":True,"food_per_day":1}` for eaters and `{"needs_food":False}` for non-eaters (Pet Rock, Crysteed, the self-feeding Exultant's Hawk — no invented water need).

**Pooled cap:** pets + steeds + followers all draw on the SAME command pool — `followers.follower_level_cap` (cap = leader's EGO bonus; used = summed Level of every follower/pet/steed under that leader). Mercenaries are a separate pool (D3) and never pool in. Level-0 creatures (the Exultant's Hawk) do not count toward the cap but still occupy the roster.

Five `character` actions (no new tool):
- **`acquire_pet`** (`name`=leader, `companion_type`=catalog slug, `follower_name` optional custom name) — cap-checks against the pooled follower cap, then writes a `type:"pet"` sheet.
- **`acquire_steed`** (`name`=leader, `companion_type`=slug, `rider` optional PC) — writes a `type:"steed"` sheet with its full `item_slots` cargo capacity; the optional `rider` must pass `_is_pc_sheet`.
- **`level_up_pet`** (`name`=pet, `hp_roll`=d8) — spends an XP gift: +d8 max HP and +1 item slot. Pets only; a steed is rejected.
- **`ride_steed`** (`name`=steed, `rider`=PC; `''`/`'none'` to dismount) — sets/clears the one-steed-per-PC mount link.
- **`dismiss_companion`** (`name`=pet/steed, `reason`) — stamps departure and moves the sheet to `characters/departed/` via the shared `_move_sheet_to_departed` helper.

**Feeding seam** (S1 daily tick): an unfed **pet** runs the same Deprived starvation counter as a PC and dies when the counter expires — but a **steed** never starves: after 7 consecutive unfed days it RUNS AWAY (CH p.69), stamped as a departure (not a death), with one runaway push per steed per tick (the standing nag never also prints "DIES Day X" for a steed).

**Death-seam exclusion:** `_is_pc_sheet` classifies `follower`/`mercenary`/`pet`/`steed` as NON-PC, and this is the SAME classification the resurrection gate uses — so a pet or steed that dies (starvation OR combat) gets the morale push but NO five-path resurrection menu (resurrection is PC-only). Tests: `tests/test_pets_steeds.py` (22). Spec: `docs/superpowers/specs/2026-06-13-d4-pets-steeds-design.md`; plan: `docs/superpowers/plans/2026-06-13-d4-pets-steeds.md`. VERIFY-FIRST correction (R-D4b): the book has no mounted-combat-modifier rule (only per-creature traits like the Destrier's Charge) — that roadmap claim was dropped.

### D5 — Vehicles (2026-06-13)

Vehicles (Crimson Hound printed pp.73-76 / PDF 80-83) as fixed-stat-block roster sheets, built on the D2-D4 sheet spine and reusing the engine's existing `vehicles/` roster substrate (`type:"vehicle"` sheets land in `characters/vehicles/`). **`vehicles.py`**: an 11-vehicle catalog — the **9 book vehicles** (`auto_chariot`, `colossus`, `dune_skuggy`, `ornithopter`, `skiff`, `stilt_strutter`, `touring_orb`, `vimana`, `wind_barge`) plus **2 campaign homebrews** (`crawler` = the campaign-homebrew expedition vehicle, Hull 12 / 150 item slots, R-D5b; `ornithopter_titan` = the book Ornithopter stat block with whole-crew capacity, R-D5a) — each row carrying `name`/`kind`/`hull`/`av`/`speed`/`item_slots`/`attack`/`crew`/`special`/`travel`/`homebrew`/`damage_immune`. `vehicle_block(slug)` returns a deep copy so a mutated sheet never corrupts the catalog. On the catalog `hull` is a plain int; on an instantiated SHEET it becomes a `{"current","max"}` dict.

Two `character` actions (no new tool):
- **`acquire_vehicle`** (`name`=owner PC, `vehicle_type`=catalog slug) — instantiates the catalog block as a `type:"vehicle"` sheet under the owner, Hull written as a `{current,max}` dict, `operational:true`.
- **`repair_vehicle`** (`name`=the vehicle, `hull_points`=points to restore) — restores Hull at **1 day per point** (CH p.73, spare parts), clamped to max, and clears the wrecked flag when Hull rises above 0.

**Hull-Points combat** (CH p.73, via `_vehicle_take_damage(name, amount, weapon_tags)`): a single damage source reduces Hull by `amount // 10` (the **1:10 floor** — a hit under 10 raw does nothing; a 19 removes exactly 1, a 9 removes 0). Sources do **NOT stack** — satisfied by construction, since one call is one source (two separate hits of 6 and 8 in a round each floor to 0). The **Vimana** is `damage_immune` (R-D5e): it takes 0 from any weapon unless that weapon is tagged `anti_paradox`; the immunity is per-sheet and never leaks to other vehicles. Hull 0 = **WRECKED** (`operational:false`) — a wreck is NOT a PC death and never routes through `_death_gate`/`_death_seam_lines`, so it emits no five-path resurrection menu (the D3/D4 death-seam class bug, avoided here too). A **Synthetic** vehicle self-attacks using its **current Hull as the to-hit bonus** (`_vehicle_attack_bonus` returns the Hull int, dropping as Hull drops; mechanical vehicles return `None` — they need a human operator). A **chase** is an **opposed Speed save** between two vehicles (`_vehicle_speed_save_lines(a, b)` surfaces each side's Speed for the DM to roll). Both are exposed as `combat` tool actions **`synthetic_attack`** (pass the vehicle as `target=`) and **`chase`** (pass `attacker=` and `target=`).

Tests: `tests/test_vehicles.py`. Spec: `docs/superpowers/specs/2026-06-13-d5-vehicles-design.md`; plan: `docs/superpowers/plans/2026-06-13-d5-vehicles.md`. Completes the D-cluster.

### D1 — Reputation / Faction system (2026-06-13)

Party-level faction reputation (Crimson Hound pp.83-84, 90-91) as an engine-tracked ledger. The cognitive gap closed: the campaign's `FACTIONS_QUICK_REF.md` *defined* a REP scale and named 11 alliances but tracked them as prose with no numbers — nothing held the value, computed the band, or enforced the opposed-faction mirror. **`factions.py`** (pure data, no I/O): `STANDING_BANDS` = the book's **7-band RAW table** (Hero ≥10 / Friend 4-9 / Liked 1-3 / Neutral 0 / Disliked −1..−3 / Enemy −4..−9 / Nemesis ≤−10), each band carrying the verbatim effect text + a derived reaction hint (Liked→ADV, Disliked→DIS, Hero/Friend→favorable, Enemy/Nemesis→hostile); `standing_for(rep)`; the **Minor-faction d20 generator** (`MINOR_FACTION_TABLES` reputation/type/goal/leader/assets/rival, image-verified vs PDF p.93 — book spellings "Aquire Exotica"/"Obssesses Over Trivia" preserved) + `generate_minor_faction(rolls, rng)` (assets rolled twice, returns data only).

State: **`factions.json`** (`{"factions": {slug: record}, "meta": {...}}`), helpers `_load_factions`/`_save_factions`/`_faction_slug` (modeled on `_load_threads`, atomic write, empty default when absent). A record is `{name, scope (alliance|major|minor), type, goal, leader, assets[], rival, opposed[slugs], rep (−10..10), notes, history[{day, delta, reason, rep_after}]}`.

**`faction` tool** (gated like `relationship` — `{Safety.GATED, Phase.SOCIAL, Domain.NARRATIVE}`):
- **`status`** — no name lists all factions (REP + band, sorted REP-desc); a name shows one record's band + verbatim effect + reaction hint + opposed factions + recent history.
- **`earn`** (`amount` may be negative) — adds REP, clamps to [−10,10] (reports caps), logs history, and **auto-mirrors every opposed faction by −amount** (CH "decrease by an equal amount"; each mirror clamped + logged `"opposed to <name>"`; an opposed faction not in the ledger is skipped + noted, never crashes).
- **`spend`** — REP-as-currency: reduces REP by a positive amount, **floor −10** (refuses overspend with the exact shortfall), **no mirror** (consuming standing is not an act for/against anyone).
- **`set`** — absolute clamped override (seeding + DM corrections), logs the signed delta, no mirror.
- **`add`** — register a record (refuses duplicate slug; seeds an initial history entry when rep≠0). **`oppose`** (`name`,`other`) — link a bidirectional, idempotent opposition pair that `earn` then auto-mirrors.
- Generator: **`generate(action="faction")`** rolls the d20 tables and proposes a Minor-faction record + a `faction add` baton (suggests, never auto-commits).

**Two surfacing channels** (the cognition-harness make-or-break — a file + pull-only tool would be a regression vs the auto-loaded prose): **channel-1** a read-only `⚖ FACTION STANDINGS` briefing appended in `full_session_startup` (§6f, mirrors the §6e WORLD FORCES block; sorted, omitted when empty); **channel-2** a turn-time injection in `check_canon` (`_faction_injection_lines`, after the geography block) that surfaces `⚖ FACTION: <name> — REP +N (band) — <effect>` whenever a faction is named in the player's message, read live from `factions.json`, capped at 3 (strongest magnitude first). Proven end-to-end (a test seeds a lorebook + faction and asserts the line appears in `check_canon` output, not just the helper).

**Out of scope (YAGNI):** no hardcoded Major-Faction catalog (R-D1d — campaign factions seeded as data, since they're the campaign's own canon, not the book's 8 examples); no World-Tick REP drift; no auto-wiring to carousing/recruitment (a `spend` just names what it bought); per-PC REP (party-level only, R-D1b); channel-3 NPC-encounter push deferred (R-D1f — NPC sheets carry no faction tag). The campaign's "Cacklemaw ↔ Everyone" opposition stays DM-adjudicated (R-D1e — the engine mirrors named pairwise rivals only). 30 tests (`tests/test_factions.py` + `tests/test_d1_factions.py`). Spec: `docs/superpowers/specs/2026-06-13-d1-faction-system-design.md`; plan: `docs/superpowers/plans/2026-06-13-d1-faction-system.md`.

### Reflex Layer

The Reflex Layer answers the governing "How does Claude find the right tool?" rule (`docs/DEVELOPMENT.md` §3) built out as a first-class system. A fresh, post-compaction DM-Claude cannot remember every MCP tool; the layer makes correct tool use reflexive through three independent components. Spec: `docs/superpowers/specs/2026-06-10-reflex-layer-design.md`; plan: `docs/superpowers/plans/2026-06-10-reflex-layer.md`.

#### Component 1 — Trigger-line docstrings

Every `@mcp.tool` docstring's **first line** follows one fixed shape: `Reach for this WHEN <situation>.` — a trigger naming a concrete in-play moment, not a description of the tool. Every registered tool was converted (across `server.py`, `content_forge.py`, `map_system.py`, `rulebook_system.py`, and `geography_system.py`).

**Enforcement** lives in `tests/test_tool_docstrings.py`. It calls `asyncio.run(server.mcp.list_tools())` to enumerate every registered tool at test time and fails if any description does not lead with `Reach for this WHEN \S.{9,}` (the regex). The PENDING exemption set that allowed the sweep to happen batch-by-batch was deleted once all tools complied — new tools must comply at birth, and the test has no bypass mechanism.

#### Component 2 — In-band push format (`push_format.py`)

`push_format.py` is the **one legal way** tool output names a next tool call. All push sites use it; hand-rolled call strings are forbidden. Values are always double-quoted, so names carrying apostrophes (Death's Door, Kronophage's Echo) can never break the rendered call — the recurring single-quote push bug is impossible by construction.

**API:**
- `push_call(tool, **kwargs) -> str` — renders `tool(key="value", …)`. Pass `raw("…")` for a verbatim token (e.g. `raw('"pass"|"fail"')`).
- `next_block(*calls, label="") -> str` — renders `NEXT: call` or `NEXT (label): call | call`. Empty call list → empty string.

**Live push sites** (all verified on this branch):

| Site | Trigger | Push |
|---|---|---|
| `_usage_deplete_roll` — step-down to Expended | usage die exhausted | `NEXT (reload or feed): usage(action="reload", …)` + `usage(action="feed", …)` only when Fungal |
| `_combat_attack` — OUT-OF-AMMO hard block | Expended weapon fired | `NEXT (reload or switch weapons): usage(action="reload", …)` (+ feed if Fungal) |
| `_usage_feed` — feed success | Fungal die stepped up | `NEXT (check load): usage(action="status", …)` |
| `_combat_damage` — kill (all enemies defeated/fled) | combat effectively over | `NEXT (end combat): combat(action="end")` |
| `_check_morale_triggers` — morale rout clears the field | combat over | `NEXT (end combat): combat(action="end")` |
| `_combat_morale` / forced rout — all enemies fled | combat over | `NEXT (end combat): combat(action="end")` |
| Toxin tick kills last enemy (`_check_round_advance`) | combat over | `NEXT (end combat): combat(action="end")` |
| `_character_update_hp` — manual HP set below 0 | wound threshold crossed | `NEXT (check wound): wound(action="status", character="…")` |
| `advance_day` — daily wound tick fired | degenerative tick applied | `NEXT (wound status): wound(action="status")` |
| `_codex_use` — natural 1 | MISHAP owed | `NEXT (mishap — only on nat 1): codex(action="mishap_roll")` |
| `prepare_save_state` — token minted | preview ready | `NEXT (commit save): confirm_save(token="…")` with the literal token |
| `verify_session_save` — pass-1 PASS | pre-save gate cleared | `NEXT (save): prepare_save_state(session_summary="…", day=N)` |
| `_distill_write` — write complete | nuggets cached, awaiting embed | `NEXT (index step 7): ingest_distillations(session_id="…")` |
| `ingest_distillations` — success | embeds written | `NEXT (index step 7): reindex_recent()` |
| `validate_campaign_state` — DAY DRIFT in issues | day drift detected | `NEXT (fix drift): sync_campaign_day()` — only when drift is present |
| `validate_prep_file` — PASS | prep schema-clean | `NEXT (load prep): map(action="init", map_name="…", prep_file="…")` |

**Principle:** a push must be a valid, copy-pasteable call. Never push a call that could bounce (e.g. `feed` is only pushed when the weapon is actually Fungal; `sync_campaign_day` only when drift is in the issues list).

#### Component 3 — Unified per-turn reflex block

One per-turn context block, assembled by a single budgeter, replaces the ad-hoc LOAD/WOUNDS appends that previously ran independently in `phrase_reminder.py`.

**`reflex_budget.py`** is a pure module (no I/O; importable by server.py and hooks alike). It provides:
- `Entry(tier, text)` — a tiered payload line. `tier` ∈ `URGENT=0`, `CHANGED=1`, `AMBIENT=2`.
- `compose(entries, cap_chars=None) -> str` — assembles under the hard cap (default 600 chars ≈ 150 tokens, overridable via `RUBICON_REFLEX_CAP_CHARS` env var). URGENT lines are always included even if they exceed the cap; CHANGED next; AMBIENT last; cut at the limit with a `(+N quiet)` drop marker. Empty or all-empty input → `""` (zero tokens).
- `diff_lines(old: dict, new: dict) -> list` — generates `Δ label old→new` lines for snapshot keys whose value changed. Keys use `kind:label` format; the label half (after the first `:`) is what renders. Empty `old` snapshot (session start) → no lines (prevents Δ spam on first turn).

**`phrase_reminder._build_reflex_block(campaign_dir, state)`** wires the editor into the UserPromptSubmit hook:
- The existing builders `_build_wounds_block` and `_build_load_block` are not rewritten; their outputs are fed **line-by-line** through the tier classifier so the cap trims the quiet tail rather than annihilating an oversized block (the real campaign's LOAD block alone exceeds the default cap).
- WOUNDS lines containing `UNCONSCIOUS(`, `DEATH'S DOOR(`, `MUST DROP `, or `save owed` → **URGENT**; all other WOUNDS lines → **AMBIENT**.
- LOAD header line containing `ENCUMBERED(` → **URGENT**; remaining LOAD lines → **AMBIENT**.
- `_reflex_snapshot(campaign_dir)` collects the current per-PC fingerprint (`wounds:<PC> wounds` → count, `load:<PC> load` → `used/cap`, `die:<PC>|<item>` → die or `xN`) using the **same** helpers `_build_load_block`/`_build_wounds_block` use so snapshot and rendered blocks can never disagree. Diff against the previous snapshot from `state["reflex_snapshot"]` yields CHANGED lines.
- The current snapshot is written back to `state["reflex_snapshot"]` (persisted across turns in `hooks/.hook_state.json` by the existing `load_state`/`save_state`; cleared on session start by `turn_reset.py`).
- **Fail-silent:** any exception in `_build_reflex_block` → returns `""` and appends the exception to `hooks/observer_errors.log`. A broken reflex must never block a turn. The `file_lock()` wrapping the load/build/save cycle prevents concurrent hook corruption.

**Data flow per turn:** `UserPromptSubmit` → `phrase_reminder.main()` acquires file lock → loads `hook_state` → `_build_reflex_block` reads campaign state + previous snapshot → tier-classifies WOUNDS + LOAD lines and collects Δ lines → `reflex_budget.compose()` under cap → block appended to DM context → updated snapshot saved back to `hook_state` → released.

**Resolved (historical note):** the hard crux where equipment is *used in free narration* (*"I melt the lock"*) with no structural signal naming the torch use was **solved in U2 (shipped 2026-06-09)** via the per-turn reflex push — the engine surfaces each depletable with its exact `usage(use)` call every turn, so the roll-trigger is in front of Claude when it narrates the use. A post-hoc *substance observer* (a judge reading narration for fabrication/contradiction) was later considered and **dropped (2026-06-16 owner ruling): canon correctness is the RAG's job — feed the model the right context up front rather than police its output.** Future systems (toxin per-turn state, survival, afflictions) plug into the same editor as additional contributors; per-turn cost stays capped forever as systems ship.

#### Unified HP≤0 trigger helper

`_apply_hp_damage_and_wounds(key, char, data, damage) -> (lines, lethal_dd)` is the shared in-memory worker for all damage that can wound a PC. It mutates the in-memory `char` dict directly and **never saves** — the caller persists (`_character_take_damage` saves via `_save_single_character`; the toxin tick saves via `_toxin_set`). This ensures the two save paths never race or overwrite each other's wound records.

Shared by:
- `_character_take_damage` — the normal combat/manual damage path (type-based vulnerability checks stay here since toxin ticks carry no damage type).
- `_toxin_tick` (PC path only) — the toxin-bypass bug fix: previously `_toxin_tick` wrote `c["hp"]["current"]` directly, so PC HP dropped below 0 by poison never triggered a wound; now it routes through `_apply_hp_damage_and_wounds`. Enemy tick path is unchanged (enemies use a simpler HP-subtract with defeated flag). **Synthskin doubling now applies to toxin ticks** as a result of this fix.

Sequence inside the helper: derived-effects pre-read → Synthskin doubling → Death's Door lethality (snap HP to −20, return early) → HP subtraction → wound at HP ≤ 0 → death check.

### Lorebook

**Storage:** `lorebook.json` (602K, largest single data file)
**Tool:** `lorebook()` — actions: add, view, update

The canonical lore database. Each entry is a keyword-triggered fact about the world, indexed for injection into check_canon context when the player's input matches.

**Entry schema:**

```json
{
  "keywords": ["amara", "amara vane", "matriarch vane"],
  "category": "people",
  "status": "ESTABLISHED",
  "context": "Matriarch of House Vane, a party member's estranged mother...",
  "source": "session"
}
```

**Categories:** people, places, things, context, scenes, world, religions, factions, knowledge_boundary
**Statuses:** ESTABLISHED, CANONICAL, CORRECTED

**Keyword matching:** Case-insensitive substring match against the player's input. When check_canon fires, it scans the full lorebook for keyword hits and injects matching entries into context. This is the primary mechanism for ensuring narrative consistency — every NPC, location, and established fact has keywords that trigger its injection when relevant.

**Write paths:** `lorebook(action='add')` for new entries, `lorebook(action='update')` for field changes, `save_state()` step 6 for new canon from session saves. NPC auto-population also writes lorebook entries when `npc(action='set')` creates a new NPC.

**ChromaDB indexing:** Lorebook content reaches ChromaDB immediately when an NPC is created — `npc(action='set')` (via `_npc_set()`) auto-populates a lorebook entry and upserts a matching description into the `campaign_history_tiered` collection in the same call. `reindex_recent()` does not touch the lorebook at all — it reindexes only MASTER_CONTINUITY_CURRENT.md.

### NPC State

**Storage:** `npc_states.json`
**Tool:** `npc()` — actions: set, get, list, add_knowledge, continuity, record_death

```json
{
  "npcs": {
    "amara": {
      "name": "Amara Vane",
      "disposition": "allied",
      "knows": ["the envoy's true ancestry", "the cipher project"],
      "wants": "Reform House Vane",
      "secret": "Fears the cipher work will be discovered",
      "location": "the arcology",
      "last_seen_day": 128,
      "history": [
        {"type": "disposition_change", "from": "friendly", "to": "allied", "day": 31},
        {"type": "learned", "what": "the cipher", "day": 128}
      ]
    }
  }
}
```

**Secrets handling:** `npc(action='get')` has a `strip_secrets` parameter. When True, the secret field is omitted. All npc tool output is prefixed `[DM-ONLY]`.

**Auto-population:** When `npc(action='set')` creates a new NPC, it checks lorebook.json for existing keywords. If not found, creates a lorebook entry with category "people" and indexes to ChromaDB.

### NPC Continuity / Living Dossier (2026-06-13)

Per-NPC conversational continuity tracked in `npc_states.json` alongside the existing `disposition`/`knows`/`secret` fields. Spec: `docs/superpowers/specs/2026-06-13-npc-continuity-living-dossier-design.md`; plan: `docs/superpowers/plans/2026-06-13-npc-continuity-living-dossier.md`.

**Dossier fields** (all optional; absent = no-op):
- `left_off` — plain-text note on where the last scene with this NPC ended (capped at 240 chars on write).
- `open_purpose` — the NPC's live goal or unresolved thread the DM should carry forward (capped at 180 chars).
- `changed_while_away` — `{"note": str, "stamped_day": int, "surfaced": bool}` — a World-Tick event relevant to this NPC. The World Tick stamps it `surfaced: false` when a firing thread's label contains the NPC's name (word-boundary `\b` match). It renders once in `check_canon` and is suppressed in all subsequent injections once `surfaced` flips `true`.
- `last_seen_day` — campaign day of the last `npc(action=continuity)` write.
- `purpose_clock` — `{"due_day": int, "label": str, "wound_day": int, "pace": str, "fired": bool}` (plus `"fired_day": int`, stamped only once fired) — a tempo clock on `open_purpose`. Auto-planted at `_HEARTBEAT_DEFAULT_PACE` (`"cool"`, +30 days) the first time `npc(action="continuity")` is called with an `open_purpose` and no explicit `pace`; re-armed automatically on re-engagement when the clock has fired (clears `fired` + `fired_day`, resets `due_day` from current day at its stored pace). An explicit `pace=<still|cool|warm|hot>` always overrides (`still` clears the clock). `advance_day` fires it once when `due_day <= new_day` (stamps `fired=True`, `fired_day`, calls `_stamp_npc_changed_while_away`). Omitted when no purpose has been set.

**Deterministic injection (primary store).** `check_canon` reads `npc_states.json` and renders a `NPC KNOWLEDGE SCOPE` block for every roster NPC whose name (or first name) appears in the user's turn input. This path runs unconditionally — it is NOT gated behind the `npc_knowledge` active-block. `npc_knowledge` controls only lorebook `knowledge_boundary` entries (a separate section); the two paths cannot double-render the same NPC dossier content. The injection self-gates to zero cost when no NPC is named. Primary store = deterministic read from `npc_states.json` every call. Embeddings / ChromaDB are a backstop only, never the primary signal.

**Write path.** `npc(action="continuity", name=..., left_off=..., open_purpose=..., last_seen_day=..., pace=...)` calls `_npc_continuity()` which: slug-matches by display name, writes the three fields with caps applied, flips `changed_while_away.surfaced` to `true` if present, then applies the `purpose_clock` auto-plant decision table (see `purpose_clock` field above). An explicit non-empty `pace` word (still/cool/warm/hot) overrides the auto-plant logic: it plants/re-winds the clock at that pace (`still` clears it). With no `pace` the auto-plant behavior runs: a new clock is seeded at `cool` (+30 days) when an `open_purpose` exists and no clock is present; a fired clock is re-armed at its existing pace from the current day; an unfired clock is left untouched. Unknown NPCs return a graceful error.

**Door gate — advance_day blocked until scene closed.** The Stop hook (`consolidated_stop_check.py`) sets `hook_state["open_npc_scene"]` (a `{slug: {name}}` dict) whenever a roster NPC is NAMED in the model's output (word-boundary match via `detect_open_npcs`). `gate_check.py`'s `npc_boundary_block` returns a hard-block error for `advance_day` (and any other registered boundary tool) while `open_npc_scene` is non-empty. `clear_npc_on_continuity` pops the slug from `open_npc_scene` when `npc(action=continuity, name=<NPC>)` is called, clearing the gate for that NPC. `phrase_reminder.py` injects a per-turn nag line listing the open NPCs. `roll`, `npc`, and non-boundary tools pass through unconditionally.

**World Tick stamp.** When `advance_day` fires a thread clock, it calls `_stamp_npc_changed_while_away(slug, note, day)` for each roster NPC whose name appears (word-boundary) in the thread's label. Stamps `surfaced: false`. The fired-≠-surfaced PILLAR applies: the stamp is an engine event; rendering it in fiction (via the next `check_canon` injection) is the surfacing event; `npc(action=continuity)` flips `surfaced: true`.

**Session-end distillation echo (backstop).** At `/session-end`, `_echo_npc_dossiers_to_distillation_cache()` writes a `npc:<slug>:profile` entry to `hooks/.canon_distillations.json` for every NPC that has at least one of `left_off` or `open_purpose`. Idempotent: an existing entry is overwritten, never duplicated. Topic key suffix `profile` is validated against `hook_utils.VALID_TOPIC_SUFFIXES`. NPCs with no continuity fields are skipped. These entries flow into ChromaDB via `ingest_distillations` and surface through the semantic distillation lane in `check_canon` — a deep-recall backstop for long absences, never the primary path.

Tests: `tests/test_npc_continuity.py` (24). Suite covers: dossier surface on name-match (with and without `npc_knowledge` block), `changed_while_away` surface-then-suppress lifecycle, continuity write roundtrip + cap + dispatch, graceful unknown-NPC, `detect_open_npcs` word-boundary edge cases, `npc_boundary_block` gate logic, `clear_npc_on_continuity` slug pop, `_stamp_npc_changed_while_away` roundtrip + noop-on-unknown, World-Tick `\b` boundary correctness, distillation echo idempotency and open_purpose-only case, and the double-injection regression (npc_knowledge explicit in needs does not produce a second render of the same dossier content).

<!-- ADDED 2026-06-13 — NPC Continuity / Living Dossier (branch feat/npc-continuity). Verified against live code: _npc_continuity / _stamp_npc_changed_while_away helpers; npc(action=continuity) dispatch in npc(); check_canon always-run NPC injection block (lines ~5564-5609, promoted out of npc_knowledge gate per spec 3c); stop_check.detect_open_npcs word-boundary match; gate_check.npc_boundary_block + clear_npc_on_continuity; phrase_reminder nag; _echo_npc_dossiers_to_distillation_cache + VALID_TOPIC_SUFFIXES. Suite 24 passed. -->

### Thread Management

**Storage:** `narrative_threads.json`
**Tool:** `thread()` — actions: add, update, resolve, list, get

```json
{
  "threads": {
    "amara_rapprochement": {
      "id": "amara_rapprochement",
      "title": "Amara Rapprochement",
      "description": "Former enemy becoming ally through shared cipher work",
      "introduced_day": 125,
      "urgency": "medium",
      "foreshadowing": ["blade reveal", "pressure on a hidden name"],
      "developments": [
        {"text": "Joined cipher team", "day": 128},
        {"text": "Tea walk to the high tier, first real laugh", "day": 128}
      ],
      "status": "active"
    }
  },
  "resolved": {}
}
```

**Key:** Lowercased, spaces replaced with underscores. Thread list sorted by urgency (critical first).

**World-tick clock (2026-06-12):** a thread may carry an optional `clock` object — wound via the `clock_due_day` / `clock_label` params on `add`/`update` (`0` = no change; `-1` on update clears; `resolve` drops the clock) — which `advance_day` fires when due. `_thread_list` appends a ⏳ DUE / 🔔 FIRED / ⏳ pending suffix line per clocked thread; `_thread_get` renders a **Clock:** line. Full lifecycle, record shape, and the fired-≠-surfaced PILLAR: *World Tick — play-loop slice 1* above.

### Relationship Management

**Storage:** `narrative_relationships.json`
**Tool:** `relationship()` — actions: set, get, list, history

**Key:** Alphabetically sorted entity pair joined with `|` (e.g., `"amara|brek"`). This ensures the same pair always gets the same key regardless of argument order.

Note: The reputation number system (+10 to -10) from VAARN_DM_SCREEN.md is tracked in that file and CURRENT_STATUS.md, not through this tool. This tool tracks qualitative status changes and history.

### Distillation Cache

**Storage:** `rubicon-seven-mcp/hooks/.canon_distillations.json` (~1,459 entries after the 2026-06-06 whole-campaign harvest, grows each session)
**Tools:** `distill_session()` — actions: analyze, write | `ingest_distillations()` — indexes to ChromaDB

Persistent cache of semantic learnings distilled from canon retrievals. Each entry is keyed by a canonical topic key (e.g., `amara_history`, `amara_varro_relationship`) with 7 valid `topic_key` suffixes (`VALID_TOPIC_SUFFIXES`, hook_utils): relationship, event, history, location, belief, policy, identity.

**Entry shape:** topic_key, learning (1-3 terse sentences), key_facts (4-8 dated bullets), source_pointers, verified_against (source file mtimes), created_session, refined_count, ingested_at_session.

**Write path (session-end Phase 9.25):** `distill_session(action="analyze")` scans for stale entries and session-touched entities. `distill_session(action="write")` validates, checks ChromaDB cosine overlap (auto-merge < 0.3, ambiguous 0.3–0.5, new > 0.5), and writes to cache with `ingested_at_session: null`.

**Index path (session-end Phase 9.5):** `ingest_distillations()` reads unposted entries, embeds via Ollama (nomic-embed-text), upserts to `canon_distillations` ChromaDB collection, marks ingested.

**Read path (every turn):** check_canon queries distillations two ways — cache-file keyword match (`_query_distillation_cache`, ordered pairwise-relationship → identity → input-mention, capped at 5) and ChromaDB cosine search (capped at 5). Strong distillation hits (distance ≤ 0.5) short-circuit raw history search. Both lanes drop placeholder/`<UNKNOWN>` payloads (`_is_placeholder_nugget`) and the semantic lane skips any topic_key already surfaced by the cache lane (cross-lane dedup). Nuggets ship at full length (no truncation — see §3 Delta Delivery for why).

### Hook State

**Storage:** `rubicon-seven-mcp/hooks/.hook_state.json`
**Writers:** `turn_reset.py` (UserPromptSubmit), `gate_check.py` (PreToolUse), `consolidated_stop_check.py` (Stop), `post_compact.py` (PostCompact)

Per-turn enforcement state shared across hooks. Reset by `turn_reset.py` on each real user message; preserved across hook retries.

**Key fields:**

| Field | Type | Lifecycle | Purpose |
|-------|------|-----------|---------|
| `canon_verified` | bool | Reset each turn | check_canon has run this turn |
| `canon_succeeded` | bool | Reset each turn | check_canon passed |
| `canon_required` | bool | Set by gate_check | Whether canon gating is active for this turn |
| `context_reminded` | bool | Set by gate_check | Context reminder has been shown this turn |
| `force_all` | bool | Preserved | Force all checks regardless of gating |
| `session_started` | bool | Set by full_session_startup | Session initialized |
| `turn_count` | int | Incremented each turn | Turn counter for gating (turns ≤ 3 bypass some checks) |
| `scene_fingerprint` | str | Updated each turn | Hash of scene state for change detection |
| `scene_changed` | bool | Computed each turn | Whether scene differs from last turn |
| `validate_prose_called` | bool | Reset each turn | validate_prose was called this turn |
| `validate_prose_required` | bool | Set by stop hook | validate_prose was skipped — gate_check blocks next turn |
| `skip_canon_enforcement` | bool | Set by /maintenance | Bypass all canon gating |
| `session_type` | str | Set at session-start | "gameplay" or "development" |
| `session_vocabulary` | list | Cleared at session-start | Phrases used this session (dedup tracking) |
| `catch_count` | int | Cleared at session-start | Anti-pattern catches this session |
| `catch_log` | dict | Cleared at session-start | Per-category catch details |
| `verified_npcs` | list | Reset each turn | NPCs verified against lorebook this turn |
| `lorebook_required` | bool | Set by stop hook | Lorebook check should run |
| `lorebook_triggers` | list | Set by stop hook | Keywords that triggered lorebook lookup |
| `lorebook_called` | bool | Set by stop hook | Lorebook was called this turn |
| `current_bell` | int | Set by set_bell | 1-24 bell time tracking |

### Analytics State

**Storage:** `rubicon-seven-mcp/hooks/catch_analytics.json` and `corrections.json`

Diagnostic data that feeds the prose quality evolution cycle (Section 5, Layer 4).

**catch_analytics.json:** Records every anti-pattern catch from the stop hook and prose observer. Schema: `_meta` (version, total_sessions_tracked), `catches[]` (timestamped catch records), `phrase_stats{}` (per-phrase hit counts across sessions), `semantic_catches[]` (Haiku observer results). Read by `phrase_reminder.py` on each turn (surfaces top catches) and `blacklist_evolver.py` at session-end (promotes recurring phrases).

**corrections.json:** Log of every hook correction. Each entry: timestamp, hook name, caught text, severity, false_positive flag, reason preview. Read by pattern analysis for false-positive detection.

### ChromaDB Persistent State

**Storage:** `rubicon-seven-campaign/chroma-db/` (persistent directory)
**Embedding model:** nomic-embed-text (768-dimensional, via Ollama)

Two collections persist across sessions:

| Collection | Similarity | Content | Updated By |
|------------|-----------|---------|------------|
| `campaign_history_tiered_v2` | Cosine | Session narratives in 4 tiers (micro 150ch, mini 300ch, medium 800ch, full 3000ch) | `reindex_recent()` at session-end Phase 9 |
| `canon_distillations` | Cosine | Semantic learnings from distillation cache | `ingest_distillations()` at session-end Phase 9.5 |

**Query thresholds:** Cosine collections use 0.5 (strong) / 0.7 (weak) distance thresholds. Strong distillation hits short-circuit raw history drilling. Tiered history uses parent-child linking for progressive detail retrieval.

**Startup:** Only `canon_distillations` is initialized at server startup (via `get_canon_distillations_collection()`) so it exists on first boot. `campaign_history_tiered_v2` is created lazily on first use via `get_chroma_collection()`. Ollama health check fires a warmup call to prevent 4-minute cold-start delay on first embedding request.

### In-Session State

**Storage:** `game_state.json` (persisted) + `GAME_STATE` in-memory dict (lives in `engine_core.py`, imported back into `server.py`)

```python
GAME_STATE = {
    "active_location": str,
    "active_location_name": str,
    "active_prep_file": str | None,
    "revealed_rooms": set,
    "revealed_secrets": set,
    "active_constraints": dict,
    "verified_characters": set,
    "session_started": bool,
    "active_combat": dict | None,
    "world_tick": dict,  # last_visited stamps for the return-after-absence check
}
```

Written atomically after state-modifying operations. Loaded on server startup. Cleared on new location init.

<!-- REVIEWED AND CORRECTED 2026-05-28 — Re-verified by agent swarm. Hook State table expanded from 16 to 22 fields (added canon_required, context_reminded, force_all, lorebook_required, lorebook_triggers, lorebook_called). File hierarchy, CURRENT_STATUS format, character data shape, NPC schema, GAME_STATE keys, ChromaDB collections, lorebook categories/statuses, prepare_save_state params (18) + token (8-char MD5) + expiration (600s) — all verified against code. -->

---

## 7. Combat System

**Location:** `server.py` — `def combat` (the dispatcher) at line 14129; combat helpers `_combat_init` (14209) through `_combat_log` (14706). The creature-resistance engine lives separately at lines 107-280.
**Tool:** `combat()` — actions: init, damage, attack, morale, state, end, log, synthetic_attack, chase
**Helpers:** `_combat_init` (14209), `_combat_damage` (14449), `_combat_morale` (14543), `_combat_state` (14547), `_combat_end` (14639), `_combat_log` (14706), `_check_round_advance` (14415), `_check_morale_triggers` (14338). PC damage delegates to `_character_take_damage` (11321); enemy stats come from `_get_bestiary_entry` (7811) / `_lookup_creature_stats` (7834). (The former `_apply_wound` combat path was removed — see Damage (PC targets).)
**Attack/to-hit helpers:** `_resolve_attacker_weapon` (14631), `_weapon_is_ranged` (14692), `_parse_enemy_attack` (14742), `_combat_attack` (14796), `_defender_av`, `_format_dm_result_block`. The weapon/armour schema lives in `weapon_schema.py`: `build_weapon` (99), `normalize_range` (77), `validate_weapon` (158), `RANGED_BASE_WEAPONS` (69).
**Resistance engine:** `_load_creature_resistances` (107), `_normalize_damage_type` (135), `_creature_types` (150), `_expand_categories` (165), `_resolve_resistance_profile` (176), `_apply_creature_resistance` (225).

### Combat State

```json
{
  "encounter_name": "Gene Thief Pack",
  "started_at": "2026-05-27T14:30:00",
  "round": 1,
  "initiative": "pcs",
  "pcs_acted": false,
  "enemies_acted": false,
  "enemies": {
    "Gene Thief (scarred)": {
      "hp": 12, "max_hp": 12, "av": 14,
      "morale": 2, "lvl": 3,
      "abilities": {"STR": 3, "DEX": 3, "CON": 3, "INT": 3, "PSY": 3, "EGO": 3},
      "creature_type": "Gene Thief",
      "resist_type": "Biological",
      "resistances": {"immune": [], "minimum": [], "double": [], "half": [], "varies": false},
      "incorporeal": false,
      "defeated": false, "fled": false
    }
  },
  "party_snapshot": {"Brek": {"hp": 23, "max_hp": 23}},
  "morale_checked": false,
  "morale_broken": false,
  "log": []
}
```

### Actions

| Action | Function | What It Does |
|--------|----------|-------------|
| init | `_combat_init` | Roll initiative, fetch enemy stats from bestiary, create combat state, load party snapshot |
| damage | `_combat_damage` | Apply HP or ability damage to enemy/PC, auto-check morale triggers, auto-check round advance |
| attack | `_combat_attack` | Resolve one to-hit: d20 + STR/DEX (PC) or LVL (enemy) vs target AV; on hit, compute + apply damage through the resistance engine; emit a DM-only structured result block. See Weapon Attacks & To-Hit below |
| morale | `_combat_morale` | Discretionary morale check (e.g. reinforcements arrive). With `force_morale=True`, runs the same d20+bonus vs DC16 check immediately, bypassing the auto-trigger gate. Without it, reports whether an auto-trigger condition is currently met |
| state | `_combat_state` | Return full combat status: round, initiative, all enemy/PC HP, recent log (last 5 entries) |
| end | `_combat_end` | Archive log to `combat_logs/`, award XP, calculate party damage taken, clear active_combat |
| log | `_combat_log` | Add custom message to log. Optional `side` parameter marks pcs/enemies as acted, triggers round advance |

### Mechanics

**Initiative:** d6 per round. Even = PCs first, odd = enemies first. Re-rolled each round via `_check_round_advance()`. Confirmed against rulebook (rule-initiative).

**Enemy stats:** `_combat_init` calls `_get_bestiary_entry()` and reads the structured JSON fields directly from `bestiary.json` (`level`, `hp`, `av`, `morale`, `type`) — NOT regex-parsed text. Fallback when no entry is found: LVL 1, HP 4, AV 12, Morale 0. Each field resolves independently via `_roll_stat_expr` (14209), so variable dice-expression stats (Quantum Daemon `LVL 2d6`, `AV d6 + 8`, `ML +2d6`) are ROLLED rather than collapsing the creature to defaults; HP derives as LVL x4 when the book gives none. All ability scores are house-ruled to equal LVL. `_combat_init` also resolves the creature's resistance profile via `_resolve_resistance_profile()` and carries `resist_type`, `resistances`, and `incorporeal` onto each enemy dict.

**Damage (enemy targets):**
- HP damage runs through `_apply_creature_resistance(stats, damage_type, amount, weapon_tags)` BEFORE subtraction (see Creature Resistances below).
- HP floors at 0 (no negative HP for enemies). HP = 0 → `defeated = True`.
- Ability damage: reduces enemy ability score (STR/DEX/CON/INT/PSY/EGO). At 0 or below → incapacitated. House rule: ability damage = save penalty equal to amount rolled.
- After any damage: `_check_morale_triggers()` fires automatically.

**Damage (PC targets):**
- Delegates to `_character_take_damage()` (`server.py:11321`) — the authoritative PC damage path, which handles HP tracking, wound generation when HP drops below 0, ability/max-HP loss, unconsciousness / death's door, and saving.
- The earlier in-combat `_apply_wound` path and its duplicate `SYNTHETIC_WOUNDS`/`SYNTH_WOUNDS` wound tables were removed (combat-crash fix); combat no longer owns a separate wound path.

**Morale:**
- Triggers: 50%+ enemies defeated/fled, OR leader killed (checks for "leader" in name string, case-insensitive)
- Roll: d20 + morale_bonus (from first alive enemy) vs DC 16
- Failure: all remaining enemies marked `fled = True`, `morale_broken = True`
- Checked once per round (`morale_checked` flag reset on round advance)
- **Auto-fires from `_combat_damage()`** on trigger. A manual/discretionary check is also available via `combat(action="morale", force_morale=True)` — runs the same d20+bonus vs DC16 check immediately, bypassing the auto-trigger gate (e.g. for a narratively-driven check like reinforcements arriving). Without `force_morale`, the action reports whether an auto-trigger condition is currently met.

**Round advance (`_check_round_advance()`):** Fires when both `pcs_acted` AND `enemies_acted` are True. Increments round, re-rolls initiative (d6), resets acted flags and `morale_checked`. Logs round transition with new initiative.

**Combat end (`_combat_end()`):** Archives full log to `combat_logs/{encounter_name}_{timestamp}.md`. Awards 1 XP per defeated enemy. Reports party damage summary (compares current HP against party_snapshot taken at init). Clears `GAME_STATE["active_combat"]`.

**Combat HUD (`_format_combat_hud()`):** Defined at `server.py:2985`, injected into check_canon output at line 3688 during active combat. Shows:
- Round number, initiative order, acted/not-acted status for each side
- Per-enemy: HP/max, AV, morale bonus, WOUNDED indicator at <50% HP, DEFEATED/FLED status
- Per-PC: current HP/max, damage taken or healed since combat start
- Morale broken warning when `morale_broken = True`

### Weapon Attacks & To-Hit
<!-- ADDED 2026-06-08 — Documents the combat(action='attack') to-hit system + weapon_schema range guarantee (roadmap A1). Verified against live code: _combat_attack (server.py:14796), _resolve_attacker_weapon (14631), _weapon_is_ranged (14692), and weapon_schema.build_weapon/normalize_range/validate_weapon. The build_weapon range GUARANTEE (always-stamp + validator rule) ships on branch fix/weapon-range-guarantee, pending MCP restart-verify → merge; the rest is live on main. The §7 actions/helpers tables here predated the attack system and were extended in the same pass. -->
<!-- UPDATED 2026-06-08 — Added the thrown-melee-weapon HOUSE RULE (combat thrown=True → DEX) on branch feat/thrown-weapons, pending MCP restart-verify → merge. Verified: book has NO thrown mechanic (stat keys off weapon type, batch_03_combat_weapons.md), so this is deliberate homebrew, test-covered (tests/test_combat_attack.py) + real-data e2e (Letter Opener: STR+1 normal, DEX+6 thrown). -->
<!-- VERIFICATION SOURCE: Crimson Hound rules now verified against the book text extraction at campaign archive/rulebook-source/extraction/ (+ the PDF), NOT the curated rules.json which paraphrased "melee/ranged weapon" as "melee/ranged attacks". -->
<!-- NOTE: §7 line numbers (combat at 14129, helpers) predate the attack+thrown additions and have drifted; trust the prose + function names over the exact line cites until a full re-verify pass. -->

`combat(action='attack')` resolves a single attack and returns a player-safe summary plus a DM-only structured result block. Mechanics are invisible to the player by contract — the engine reports the outcome, the DM narrates it.

**Weapon resolution (`_resolve_attacker_weapon`, 14631):** for a PC attacker, reads `inventory.carried[]` and filters to weapons (`type` contains "weapon", or has a `damage` field and is not armour). Selection: a `weapon=` name does a case-insensitive substring match (exactly one → use it; zero → error; many → ambiguous); with no name, the `primary: true` weapon is used, else the sole carried weapon, else ambiguous. Enemy attackers skip this — their attack string comes from the bestiary and is parsed by `_parse_enemy_attack` (14742): it pulls the LEADING dice expression and splits off a trailing damage type written either comma-separated (`"d8, electrical"`) OR space-separated (`"d8 TOX"`, `"d10 beam"` — roadmap A2); any remaining clause (`"(2x)"`, conditionals) becomes an adjudication note, and a save-based attack with no leading dice returns `dice=None` + note.

**Ranged vs melee → to-hit stat (`_weapon_is_ranged`, 14692):** resolution order — (1) the weapon's `range` field (`"ranged"`→True, `"melee"`→False); (2) `type` field containing "ranged"/"melee"; (3) longest-suffix name match against the `RANGED_WEAPONS`/`MELEE_WEAPONS` base-type tables; (4) default melee. A ranged weapon adds **DEX**, a melee weapon adds **STR** (`stat_label = "DEX" if is_ranged else "STR"`). Enemy attackers add **LVL** instead.

**Range guarantee (`weapon_schema`, roadmap A1):** to keep step (1) authoritative and stop weapons silently defaulting to melee, `build_weapon` (the sole weapon-minting chokepoint, used by both the server weapon generator and content-forge) now ALWAYS stamps `range ∈ {"ranged","melee"}` via `normalize_range(value, name)` — a valid explicit value wins, otherwise the class is derived from the weapon name (membership in `RANGED_BASE_WEAPONS`, kept in lockstep with `server.RANGED_WEAPONS` by a guard test), defaulting to melee only for genuinely unknown names. A junk/distance value (e.g. `"long"`, `"80ft"`) is corrected, not trusted. `validate_weapon` enforces `range ∈ {"ranged","melee"}`, so missing/invalid range fails validation. Net effect: basic, advanced, and exotica weapons all carry a valid class, and the party's carried weapons on the split `characters/*.json` sheets were backfilled to match.

**Thrown melee weapons (HOUSE RULE — "our Vaarn" homebrew):** RAW has no thrown mechanic — the book (`batch_03_combat_weapons.md`) ties the stat to the *weapon's* type, so a thrown melee weapon would use STR. We override this: `combat(action='attack', thrown=True)` treats the attack as ranged → **DEX**, even for a melee weapon (`is_ranged = bool(thrown) or _weapon_is_ranged(w)`; display gets a "(thrown)" suffix). `thrown` never downgrades an already-ranged weapon. Flagged as deliberate homebrew, not RAW.

**To-hit roll (`_combat_attack`, 14796):** `total = d20 + bonus` where `bonus` is the resolved stat. For the designated player PC the d20 must be DM-supplied (`to_hit=`) unless `auto_roll=True` — Iron Law 3, the engine never rolls for them without opt-in; all other attackers (followers, pets, enemies) roll `random.randint(1,20)`. The player PC is designated explicitly (not a hardcoded name), case-insensitively against the resolved sheet key: `$RUBICON_PLAYER_PC` env var, else a sheet flagged `{"player": true}` (stamped by `character(action="register")`/chargen); undesignated means everyone auto-rolls. `fumble = (d20 == 1)`, `crit = (d20 == 20)`. `hit = (not fumble) and (crit or total > defender_av)` — strictly greater than AV, a nat-20 always hits, a nat-1 always misses. `defender_av` comes from `_defender_av(target)`.

**DM-only result block (`_format_dm_result_block`):** on every attack the engine returns a structured block with `to_hit_d20/bonus/total`, `defender_av`, `hit/fumble/crit`, and on a hit the authoritative `damage_type`, `damage_raw`, `damage_doubled`, `damage_sent`, `damage_dealt` (post-resistance), `engine_tags`, `target_hp_after/max_hp/defeated`, and `morale_broken` — **per-attack** (roadmap A3): True only when THIS attack broke morale (`bool(combat.morale_broken) and not morale_before`, captured before the roll). A fumble or miss always reports `false` (no damage → no break), and an attack after morale already broke is not re-credited. The persistent combat-wide morale state lives in the combat HUD, not this block. R3 adds two keys on every path: `av_override` (`{"real", "effective", "source"} | null` — set when vibroactive/dimensional-edge capped the contest AV) and `av_damage_mod` (`{"tag", "bracket", "real_av"} | null` — set when piercing/mauling modified damage).

### AV-special weapon tags (R3, 2026-06-11)

Engine-owned; **do not hand-apply** — the engine resolves them automatically from `engine_tags` (or prose `tags` via `ws.resolve_tag`). PC attackers only; enemy-side attacks skip all four. TOX/poison hits reroute to the Toxin Die before any bracket check and are never modified.

- **Vibroactive / Dimensional Edge** (`_weapon_av_override`): the hit contest uses `min(defender_av, 10)` — a cap, never a raise (R-R3b: an AV 9 target stays AV 9). The real AV is preserved for the damage-bracket below.
- **Piercing** (`_weapon_av_damage_tag`): reads the target's REAL AV. `>= 16` → extra weapon die rolled BEFORE crit doubling (engine rolls for everyone except the designated player PC, who is prompted to roll it themself per Iron Law 3 — R-R3c); `<= 13` → damage halved AFTER crit doubling (floor, min 1); 14–15 = no modifier.
- **Mauling** (R-R3a — Piercing's mirror, same brackets inverted): `<= 13` → extra die; `>= 16` → halved. 14–15 = no modifier.

The `roll_detail` hit line shows the pre-halve crit product so the arithmetic reads coherently. `weapon_schema._TAG_ENGINE_KEY` maps the prose labels to canonical keys; `_tag_key` strips spaced-dash clauses (em/en/hyphen with spaces) so "Dimensional Edge" resolves to `dimensional-edge`.

**Live backfill (campaign commit fd2a4bf):** `scripts/backfill_av_tags_r3.py` stamped `dimensional-edge` and `piercing` on the live campaign's AV-special weapons.

<!-- ADDED 2026-06-11 — Documents R3 AV-special weapon tags (branch feat/av-overrides). Verified against live code: _weapon_av_override (server.py:593), _weapon_av_damage_tag (server.py:603), _weapon_has_tag (server.py:573), _AV_OVERRIDE_LABELS (server.py:589), R3 hit-path in _combat_attack (server.py:16897-17012), dm_result keys av_override/av_damage_mod present on all paths (fumble/miss/hit). Rulings: R-R3a Mauling included, R-R3b cap-never-raise, R-R3c the wielder rolls the extra die themselves. -->

### Creature Resistances & Weapon Tags

Damage interactions are driven by the creature's **type(s)** (Crimson Hound, verified printed p.185) plus optional weapon tags. Verified against the book; engine added 2026-06-07.

**Type matrix** (`rulebook/creature_resistances.json`, loaded by `_load_creature_resistances`): the 7 types and their fallbacks — Biological (none), Synthetic (immune suffocation/poison/radiation/fungal_spores, double electrical), Psychic (none), Fungal (half kinetic, double fire/fungicide), Mineral (immune suffocation/poison/radiation/electrical/fire/cold/fungal_spores, double bludgeoning), Hypergeometric (double hypergeometric), Outsider (varies). Multi-type = union of all listed types.

**Resolution (`_resolve_resistance_profile`):** a per-creature `stats.resistances` object with any content REPLACES the type default; an empty/absent object falls through to the type matrix. `extreme_temperature` expands to fire+cold. (The bestiary rebuild bakes the type-union into deviation creatures so replace-semantics never drops a type rule.)

**Application (`_apply_creature_resistance(stats, damage_type, amount, weapon_tags)`):** precedence — incorporeal-gate > immune (0) > minimum (=1) > double+half conflict (normal) > double (x2) > half (/2) > varies (referee self-check note) > base. `damage_type` is normalized via `_normalize_damage_type` (flame→fire, TOX→poison, laser→beam, …).

**Weapon tags** double damage vs a creature type that has no matching damage-type weakness: `anti-paradoxical`→Outsider, `eroding`→Mineral, `psyche-suppressant`→Psychic, `hypergeometric`→Hypergeometric (added 2026-06-12; carries a type-double-fired guard — when the type-level x2 already fired for hypergeometric damage itself, the tag is skipped so the book effect never stacks to x4). (Electrical→Synthetic is already handled by the type rules via `damage_type`, so it is NOT duplicated.) Passed through `combat(action='damage', weapon_tags=[...])`.

**Incorporeal** (`stats.incorporeal`, e.g. Spectre of Indifference): immune to ALL damage except `hypergeometric` damage or an `anti-paradoxical` weapon; the tag then also doubles vs Outsider. `_combat_init` carries the flag onto the enemy.

### Enemy Naming

`combat_descriptors.py` assigns thematic descriptors to distinguish multiple enemies of the same type. 60 descriptors across 6 categories (physical 15, equipment 12, position 10, behavior 10, appearance 8, stance 5). Priority tiers by count: 1-5 prefer physical+position (fallback: a physical+behavior combined descriptor); 6-10 pick any available descriptor (fallback: an equipment+position combined descriptor); 11-15 also pick any available descriptor — identical primary rule to 6-10, differing only in fallback (fallback: two randomly-chosen category descriptors combined); 16+ use the numbered format `#{count} ({descriptor})` with a single random-category modifier. Custom descriptors can be passed via `enemies` parameter: `"Gene Thief (leader)"`.

### Known Issues

- **`_check_round_advance()`** — exactly one definition at `server.py:14415`, called from `_combat_damage()` and `_combat_log()`.

<!-- REVIEWED AND CORRECTED 2026-06-07 — Full re-verification against live code after the bestiary/combat overhaul. Line numbers re-anchored: combat() def 14129; helpers _combat_init 14209, _check_morale_triggers 14338, _check_round_advance 14415, _combat_damage 14449, _combat_morale 14543, _combat_state 14547, _combat_end 14639, _combat_log 14706. Resistance engine 107-280 (_load_creature_resistances 107, _normalize_damage_type 135, _creature_types 150, _expand_categories 165, _resolve_resistance_profile 176, _apply_creature_resistance 225). _format_combat_hud 2985, injected into check_canon at 3688. _character_take_damage 11321; _get_bestiary_entry 7811; _lookup_creature_stats 7834. CHANGES THIS PASS: (1) Enemy stats now read structured JSON from bestiary.json, NOT regex — corrected. (2) Combat State enemy dict gains resist_type/resistances/incorporeal — added. (3) Damage(enemy) now routes through _apply_creature_resistance with full precedence + weapon_tags — documented in new Creature Resistances & Weapon Tags subsection. (4) Damage(PC) delegates to _character_take_damage; the old _apply_wound combat path + SYNTHETIC_WOUNDS/SYNTH_WOUNDS tables were REMOVED (combat-crash fix) — corrected the stale wound description. (5) weapon_tags param added to combat(). VERIFIED unchanged: initiative d6 even=pcs/odd=enemies (14227), morale d20+bonus vs DC16, combat_end XP+archive, HUD contents, descriptor counts 15/12/10/10/8/5=60. Smoke-tested live: Spectre incorporeal immune to fire/0, anti-paradoxical bypass+double=16; Mineral eroding x2. 38 green in bestiary/combat suites. -->

---

## 8. Generation Stack

### Dice Roller

**File:** `dice_roller.py` (429 lines)
**Class:** `DiceRoller` + module-level singleton `_default_roller` with companion functions

**Two RNG systems exist in this project:**
1. **DiceRoller class** — creates one `random.SystemRandom()` at init, reuses it for all rolls. server.py imports the `DiceRoller` class (`from dice_roller import DiceRoller`, server.py:15) and creates its OWN instance, `dice = DiceRoller(use_crypto_random=False, log_rolls=False)` (server.py:91) — it does NOT use the module-level `_default_roller` singleton or the companion helper functions.
2. **ContentForge._roll_die()** — creates a NEW `SystemRandom()` per die roll. Separate entropy source each time.

Both backed by `os.urandom()`. Not seedable, no PRNG cycle bias. DiceRoller is used for gameplay dice (saves, damage, initiative). ContentForge is used for table generation (mutations, locations, settlements).

**Class API (DiceRoller):**

| Method | Signature | Returns |
|--------|-----------|---------|
| `roll` | `(sides, num_dice=1, modifier=0)` | dict: total, rolls, modifier, breakdown, timestamp |
| `d` | `(sides, modifier=0)` | int (single die total) |
| `d2`–`d100` | `(modifier=0)` | int (d2, d3, d4, d6, d8, d10, d12, d20, d100) |
| `roll_with_advantage` | `(sides, modifier=0)` | dict: winner + other_roll |
| `roll_with_disadvantage` | `(sides, modifier=0)` | dict: loser + other_roll |
| `roll_from_table` | `(table: list, die_size=None)` | tuple: (roll_value, entry) |
| `roll_unique_from_table` | `(table: dict, excluded, max_attempts=100)` | tuple: (roll_value, entry) — rejection sampling |
| `parse_dice_notation` | `("3d6+2")` | dict: num_dice, sides, modifier |
| `roll_notation` | `(notation)` | dict: roll result |
| `get_roll_statistics` | `()` | dict: per-die-type distribution (requires `log_rolls=True`) |
| `clear_history` | `()` | None |

**Module singleton:** `_default_roller = DiceRoller(use_crypto_random=False, log_rolls=False)`. Companion functions `roll_dice()`, `d2()`–`d100()`, `roll_notation()` delegate to it. server.py does NOT use these companion functions — it constructs its own `dice = DiceRoller(...)` instance and calls methods on it directly (e.g., `dice.d100()` in `_roll_exotica`). Same numerical behavior (both are `SystemRandom`-backed `DiceRoller` instances), but the wiring is a server-owned instance, not the shared singleton.

**Cryptographic mode:** `DiceRoller(use_crypto_random=True)` uses `secrets.randbelow()`. Available but unused in production.

### Content Forge

**File:** `content_forge.py`
**Data:** `data/content_forge_tables.json` (table count is machine-derivable: `len(json.load(open(...))["tables"])` minus the 3 `_`-prefixed maps; the rulebook/get_table copies of the location sub-tables live in `data/rules/rulebook/tables.json`)
**Class:** `ContentForge` — single instance created at server startup via `register_content_forge_tools()`

**Architecture:** The forge is both a generator AND a dispatch hub. Its `roll()` MCP tool routes 16 actions via `ROLL_DISPATCH` dict — internal generators plus 3 external functions injected at registration (encounter, reaction, exotica), plus the three dice-honesty actions `check`/`save`/`damage`, plus `list_tables`.

**Table loading:** Eager — all tables loaded from JSON into `self.tables` in `__init__()`. One file read per server lifecycle. No lazy loading, no per-call I/O.

**Table entry format:** `{"roll": "1-5", "fields": {"Key": "value", ...}}`. Range parsing supports exact (`"1"`) and inclusive ranges (`"1-5"`). All field values are strings — damage dice, AV, slots are text for the DM to interpret, not parsed structured data.

**Location type dispatch (`_location_type_map`):** Maps d20 rolls to subtable keys: `{"1": "anomaly", "2": "archive", ...}`. When `roll(action="location", location_type="random")`: (1) roll d20 on `location_type` table, (2) look up result in map to get subtable name, (3) roll on that subtable (die per subtable). Two-roll dispatch. All 20 location-type rolls resolve to a backing subtable — there are no dead map entries and no silent fallthrough. 19 distinct subtables: anomaly, archive, arcology, bandit_camp, bounty_hunter, cacklemaw_den, faa_camp, grave, hegemony_outpost, holy_place, oasis, ruin, science_mystic, trade_post, wreck, hegemony_protectorate, oracle_sanctum, vault, monster_lair (20 type rolls map to 19 distinct subtables because two rolls both resolve to `arcology`). Most subtables are d20; `monster_lair` is d100 — the dispatch reads each table's `die`, so the second roll is not always d20.

**ROLL_DISPATCH routing (16 actions):**

| Action | Generator | Dice | Tables | Special Logic |
|--------|-----------|------|--------|---------------|
| `mutation` | `_roll_mutation` | d100 | cacogen_mutation (100 entries) | Rejection sampling for count 1-4 |
| `location` | `_roll_location_subtable` | d20 + (per-subtable die) | location_type + 19 subtables (all 20 map rolls backed) | "random" two-roll dispatch via _location_type_map; second die per subtable (monster_lair is d100) |
| `soul` | `_roll_soul` | d20, d12, d10, d8, d8, d12 | etiology, history_layers (×2), temporal_stakes, ancient_intelligences, ghosts_echoes | 6 rolls. history_layers rolled twice |
| `settlement` | `_roll_settlement` | 4×d20 | settlement_government, values, despises, lacks | Pure table lookup |
| `landmark` | `_roll_landmark` | d100 | landmarks (VoV Referee's Toolbox p.177-178) | Certified table lookup |
| `placename` | `_roll_placename` | d{len(column)} | place_names columns: settlements/ruins/holy_places/hegemony_places/autarchic/mystic/faa_nomad | `category` selects the column; die size matches that column's printed length |
| `weather` | `_roll_weather` | d6 (direction) | `_weather_hex_chart` (37 cells, book pp.155-156) | Hex-chart WALK, not a fresh roll: marker persisted in campaign `weather_state.json`; d6 = direction (1=NW 2=N 3=NE 4=SE 5=S 6=SW); 10 X-void cells block (marker stays), other off-chart moves wrap to the opposite side; `specific_roll` forces the DIRECTION; `table="weather_reset"` (via environment) re-centres on Start D4. Replaced the invented d20 table 2026-06-12 (Joe ruling). tests/test_weather_hex_walk.py |
| `environment` | `_roll_environment` | d6/d12 | weather (hex walk), weather_reset, route_hazards | foraging redirects to supply; weather routes to the hex walk |
| `chargen` | `_roll_chargen` | 6×d20 + d6, or d100 | basic_weapon, body_armour, helm, shield, explorer_gear (×2), starting_boon; OR cacogen_mutation | `table` param: "full"/"weapon"/"armour"/"gear"/"boon"/"mutation" |
| `encounter` | External (injected) | varies | encounter tables from prep files | `roll_encounter_fn` passed at registration |
| `reaction` | External (injected) | d20 | — | `roll_reaction_fn` with EGO modifier |
| `exotica` | External (injected) | d100 | EXOTICA_TABLE in server.py | `roll_exotica_fn` |
| `check` | External (`roll_check_fn`, `kind="check"`) | d20 (± advantage/disadvantage) | — | Dice-honesty action: ability check vs `dc`, reading the named character's ability modifier or a flat `bonus` |
| `save` | External (`roll_check_fn`, `kind="save"`) | d20 (± advantage/disadvantage) | — | Dice-honesty action: same mechanics as `check`, labeled as a saving throw |
| `damage` | External (`roll_damage_fn`) | per `notation` (e.g. `3d8+6`) | — | Dice-honesty action: rolls an arbitrary damage/HP-cost expression |
| `list_tables` | `_list_forge_tables` | — | — | Categorized inventory of all tables |

### Server-Side Generators

Four generators are dispatched from the `generate()` tool (`server.py:8648`) by its `action` parameter — private helpers (leading underscore) that live in `generators.py` (extracted post-decomposition, slice 1) and are imported back into `server.py`'s namespace, not defined directly in `content_forge.py`. They use server.py's own `DiceRoller` instance (`dice`, server.py:91) and/or their own hardcoded tables, adding combinatorial logic the forge doesn't handle.

**`_roll_exotica`** (server.py:8516): d100 lookup against `EXOTICA_TABLE` (hardcoded, ~100 entries). Special-case rolls: roll 69 triggers nested d6 for embedded creature check; roll 82 references encounter table. Uses `dice.d100()` directly. (Also wired into the forge's `roll(action=exotica)` via the injected `roll_exotica_fn`.)

**`_generate_exotica`** (server.py:8669): 4d100 seed generator. Loads separate `exotica_generator.json` with four columns (Material, Form, Theme, Action). Each rolled independently, no dedup. Output is a combinatorial seed string the DM interprets into a unique item — not a finished item.

**`_generate_weapon`** (server.py:8844): 3-tier system (basic/advanced/exotic).
- Base weapon: d12 (basic), d20 (advanced), or d20 with advantage (exotic) from MELEE_WEAPONS or RANGED_WEAPONS dicts
- Tag rolls: d20 basic (always), d20 advanced (if tier ≥ advanced), d20 exotic (if tier = exotic)
- Tag multipliers: specific rolls apply damage/slot modifiers (e.g., roll 12 "Heavy" = 2× damage, 2× slots)
- Polymorphic special case: exotic roll 14 triggers nested d20 for alternate weapon form
- Base weapons carry inherent tags (e.g., Shock Baton has "Electrical")

**`_generate_npc`** (server.py:9079): Cascading rolls across `npc_tables.py`:
- Ancestry: d20 (weighted) or specified directly
- Personality: d20 manner + d20 voice + d20 drive
- Social: d20 bond + d20 faith (weighted) + d20 faction
- Name: d100 on one of 4 name tables (A/B/C/D), selected randomly
- Career: d100 on CAREERS_TABLE → returns a dict `{"career": <name>, "items": <text>}` (e.g., `{"career": "Actor", "items": "Wig, False Nose, Book of Playscripts"}`). The `items` value is descriptive text, not parsed inventory objects.
- Secret: d20 (optional, `include_secret=True`)
- Derived: verbal tics and speech register from ancestry + manner (hardcoded lookup, not rolled)
- Plot hook: templated sentence combining manner + ancestry + drive

**Name style families:** A (formal/archaic: "Abiah", "Baptist"), B (melismatic: "Agupta", "Beneva"), C (descriptive: "Big-Spit", "Boots"), D (patronymic: "Achefoot", "Blueback"). One roll = one name, no combining.

### NPC Tables

**File:** `npc_tables.py` (321 lines)

All plain Python dicts. 13 physical dicts, 10 logical tables:

| Table | Die | Entries | Notes |
|-------|-----|---------|-------|
| ANCESTRY_TABLE | d20 | 20 slots / 10 distinct species | Weighted: True-kin/Mycomorph 3-in-20; Cacogen/Newbeast/Synth/Faa Nomad/Cacklemaw Exile/Neobloom 2-in-20; Planeyfolk/Lithling 1-in-20 |
| MANNER_TABLE | d20 | 20 | Personality trait |
| VOICE_TABLE | d20 | 20 | Speech pattern |
| DRIVE_TABLE | d20 | 20 | Motivation |
| SECRET_TABLE | d20 | 20 | Hidden knowledge/agenda |
| BOND_TABLE | d20 | 20 | Social connection |
| FAITH_TABLE | d20 | 20 slots / 14 distinct faiths | No "None" entry. Weighted: 6 faiths get two slots each (Promised Sun, Everbleeding Wound, Vaa, Seekers of Eyeless Wisdom, Binary Devotion, Brotherhood of the Black Sun) — all tied 2-in-20, no single faith is heaviest; the other 8 faiths get one slot each |
| FACTION_REPUTATION_TABLE | d20 | 20 | Political alignment |
| NAMES_A through NAMES_D | d100 each | 100 each (400 total) | 4 style families |
| CAREERS_TABLE | d100 | 100 | Each entry a dict `{"career", "items"}`; `items` is descriptive text |

### Rulebook System

**File:** `rulebook_system.py` (488 lines)

**Actions:** search (keyword query, optional type filter, limit), get (by ID, bypasses cooldown), stats (loaded counts + cooldown status), reload (re-read from disk), turn (advance dedup counter), session_reset (clear dedup cache).

**De-duplication:** 15-turn cooldown. Tracks `{entry_id: turn_injected}`. After injection, the same rule won't re-appear for 15 turns. Explicit `get` calls bypass cooldown entirely. `session_reset` clears the cache.

**Data sources (6 JSON files):**
- rules.json — Rule entries with id, keywords, rule text, source
- tables.json — Rolling and reference tables with die type and rows
- bestiary.json (192K) — Creature stat blocks with level, AV, morale, attacks, specials
- equipment.json — Weapon/armor definitions
- gifts.json — Mystic gift mechanics
- lore_additions.json — Vaarn-specific lore additions

**Search scoring:** Exact keyword match = 3 points, partial substring = 1 point, ID match = 2 points. Results sorted by score descending.

### DM Design Skill

**Location:** `.claude/skills/dm-design/` (SKILL.md 88 lines + dm-design-agent-prompt.md 320 lines = 408 lines)

The generative pipeline's narrative counterpart. Where the forge generates raw material (locations, NPCs, weather), dm-design gives it structure, etiology, and purpose. Auto-triggers after content-forge generates location-scale output.

**Execution model:** Fresh-context Opus subagent with `bypassPermissions`. All design content is classified — the subagent returns ONLY "Done." or "Incomplete — [reason]" to the player. The main context never sees design content. Maintenance mode is enabled/disabled automatically by SKILL.md to bypass check_canon during design work.

**5-phase methodology:**

| Phase | Purpose | Key Activities | Gate |
|-------|---------|---------------|------|
| 1. Canon Excavation | Verified factual foundation | 13 mandatory search types (lorebook, campaign history, tiered history, geography, rulebook, prep files, design docs, NPC state, cultivation, dossiers, world progress, resonance, CURRENT_STATUS.md). Timeline reconstruction. Knowledge scope audit: OBSERVED / DEDUCED / DM-ONLY / DESIGNED / UNVERIFIED. | Every noun searched, every fact sourced |
| 2. Gamestate Orientation | Understand current moment | 9 situational questions (location, player/DM mission, knowledge, secrets, stakes, beat type, antagonist goals, pressure). Etiology: historically plausible, internally consistent, ≥2 temporal layers. Experience arc: approach → entry → exploration → complication → climax → extraction. | All questions answered with cited sources |
| 3. Design Construction | Synthesize into design | Causal chain audit (test backwards + forwards). NPC 5-bullet audit (KNOW/HIDING/LEVER/NEVER SAY/WOULD TRADE). Victory conditions: designed solution + creative alternative + failure state. Antagonist integration. Callback placement from RESONANCE_INDEX. Write all to disk. | All work on disk, NPCs verified, puzzles multi-path |
| 4. Review & Contradiction | Adversarial error check | 7 checks: timeline, geography, NPC knowledge, lorebook, player knowledge, mechanical, emotional coherence. Etiology stress test ("who built this room and why?"). Spoiler audit: SAFE/GATED/CLASSIFIED. Content-forge crosscheck. | All 7 pass, etiology airtight |
| 5. Output & Filing | Final review + return | Re-read all written files. Confirm no thinking-block notes leaked, all secrets gated, FINGERPRINT immutable. Return "Done." | Clean return |

**Standard outputs:** Location prep files (`<PLACE>_PREP.md`), arc design documents (`<ANTAGONIST>_ARC_DESIGN.md`), truth files, antagonist dossiers, cultivation updates, lorebook entries, resonance additions, world progress entries.

**Named failure mode:** The Amaranthine Archive — anemic prep, invented history, logical gaps requiring retroactive player repair. Referenced 3 times in the methodology as the anti-pattern. Every check exists to prevent recurrence.

**Content-forge crosscheck (Phase 4.4):** When design uses forge output, Phase 4 verifies: creatures were rolled on correct table, NPCs generated via `generate_npc()`, exotica from `roll_exotica()`, etiology consistent with regional lore.

<!-- REVIEWED AND CORRECTED 2026-05-28 — Full rewrite for description-to-function parity. DiceRoller: two RNG systems (class singleton vs forge per-roll), full API table, module-level singleton. ContentForge: class architecture (eager loading, _roll_die per-roll SystemRandom), ROLL_DISPATCH 11-action table, table entry format, _location_type_map with all 17 subtables. UPDATED 2026-05-31: vault (d20) + monster_lair (d100) subtables added from Vaults of Vaarn 2e canon, wiring the previously-dead map rolls 4/5 — now 19 distinct subtables and all 20 type rolls are backed (no silent fallthrough); second die is per-subtable, not always d20. Server-side generators (private helpers with leading underscore, dispatched from the generate() tool at 8673): _roll_exotica (~8541-8617) + forge injection, _generate_exotica (~8694-8868) 4d100, _generate_weapon (~8869-9059) 3-tier, _generate_npc (~9104-9235) cascading rolls + name families + career strings. RE-VERIFIED 2026-05-29: underscores added, line numbers re-anchored, lorebook size 618K→602K. NPC tables: full table. Rulebook: all 6 actions. DM Design: 5-phase methodology with gates, execution model, named failure mode (Amaranthine Archive), content-forge crosscheck. UPDATED 2026-05-31 (generation-stack pass): corrected NPC table sizes against live npc_tables.py — VOICE 8→20, BOND 10→20, MANNER 8→20, FACTION_REPUTATION 13→20, ANCESTRY 8→10 species (added Cacklemaw Exile, 2/20); rewrote FAITH (was "6, Promised Sun/None heaviest") → 20 slots / 14 distinct faiths, no "None" entry, 6 faiths tied at 2-in-20 (none uniquely heaviest). Dice wiring corrected: server.py imports the DiceRoller CLASS (server.py:15) and uses its OWN instance `dice` (server.py:91), NOT the module `_default_roller` singleton or companion helpers (same numerical behavior). CAREERS_TABLE returns a dict {career, items}, not a text string. Server-generator line numbers re-anchored to live server.py: generate() 8648, _roll_exotica 8516, _generate_exotica 8669, _generate_weapon 8844, _generate_npc 9079. DM-design skill files 297→408 lines (SKILL.md 88 + agent-prompt 320); Phase 1 mandatory searches 12→13 (added CURRENT_STATUS.md); Amaranthine Archive references 4→3 (live count in dm-design-agent-prompt.md). Location-subtable passage and its 2026-05-31 vault/monster_lair note left intact. -->

### Content-Forge Skill Revision (2026-06-12)

The content-forge SKILL (`skills/content-forge/SKILL.md`, rewritten 1589→1101 lines, plus `references/` sweep) was brought up to the live engine. Roadmap entry "Content-forge SKILL revision", parts 1+2; spec `docs/superpowers/specs/2026-06-12-content-forge-revision-design.md` (incl. Amendment A).

- **TABLE INDEX delegation (the convention):** ALL random tables live in the engine (`data/content_forge_tables.json`) behind the `roll(...)` tool; the skill NEVER hand-rolls against a markdown table when an action exists. The skill's inline reference tables were deleted in favor of a TABLE INDEX section mapping each generation need to its `roll(action=...)` call; remaining `references/` copies are marked display copies for DM browsing ("the engine rolls").
- **ENGINE CONTRACT section:** generated content must carry the fields the engine runs on — weapons (`name`/`damage`/`slots`, prefer `generate(action="weapon")`), armour, consumables with usage dice or counts, custom creatures with the full combat stat shape, toxic things with a Toxin Die rung, afflictions in the real `condition(...)` grammar. See the skill file for the authoritative field lists.
- **AFFLICTIONS & HAZARDS framework:** d12 theme→disease map over the engine's 12-disease catalog (organic 1-6 / nanomachine 7-12, immunity rules stated), hazard templates with working tool calls, a mandatory etiology rule (who/vector/how long), placement-by-scale table, and a telegraphing rule (describe, never name).
- **Prep conventions:** every mechanical element in a prep carries a ready-to-fire `⚙ ENGINE:` push line directly under it (the running DM — possibly a smaller model, possibly post-compaction — never reconstructs a call); preps at LOCATION scale and above open with a one-screen `## ⚡ RUN CARD` (encounter check, clocks, afflictions, key DCs, rooms, boss/objective, victory conditions) as the first section after the header. Engine-side enforcement: `validate_prep_file` ships two lint checks (2026-07-05) — a reveal-tier WARN for rooms whose body text has no recognized tier subsection (routed through map_system's live parser), and a stale-tool-call lint that harvests registered tool names live from the FastMCP registry (fails loud). RUN CARD presence and ENGINE CONTRACT field checks remain captured roadmap items.
- **Foraging redirect:** the stale pre-S2 d30 foraging table was DELETED from `data/content_forge_tables.json`; `roll(action="environment", table="foraging")` now returns a redirect pushing `supply(action="forage", character=...)` (the S2 certified rulebook d100), and the `roll` tool's `table` field description documents the redirect. Tests: `tests/test_forge_foraging_redirect.py`.
- **Tool-name enforcement:** `tests/test_skill_tool_names.py` pins that skill markdown only references registered MCP tools — five guards as of 2026-07-03: no retired names (a curated RETIRED set); every `name(action=...)` call token must be a registered tool; every `action="X"` value must be in that tool's live-harvested action vocab; every keyword-argument name in a single-line call must be a real parameter on the live tool signature (`inspect.signature` — catches the `stat=`-vs-`ability=` bug class; positional args are a documented open gap); and every skill with `allowed-tools:` frontmatter must declare every registered tool its body pushes (caught session-end pushing `advance_day` without declaring it, day one). Each harvest-style guard has a guard-the-guard test proving it can't silently no-op. Skills-production-hardening pass 2026-07-03 also delegated content-forge's five soul tables to `roll(action="soul")`, forward-ported NPC/faction crystallization into the shipped session-end, and truth-aligned session-start's Step 8 with the real `full_session_startup` output.
- **dm-design review gate:** forging a `*_PREP.md` now blocks the stop until a dm-design review is dispatched or the player waives it — documented at §4, Check 1b. The dm-design agent prompt itself (campaign repo) gained a Phase 4.6 Mechanical Soundness Gate plus extended 4.2/4.4 checks.

<!-- ADDED 2026-06-12 — Content-forge revision (branch worktree-content-forge-revision). Verified against live files: SKILL.md 1101 lines (TABLE INDEX at ~1063, ENGINE CONTRACT at ~656, AFFLICTIONS & HAZARDS at ~706, push lines ~798, RUN CARD ~806, checklists updated incl. validate_prep_file), references/TRAVEL.md + WEATHER.md sweep, content_forge.py foraging redirect (table_map entry removed, NEXT: supply push, list_tables Environment = weather/route_hazards), data/content_forge_tables.json 40 tables / zero "foraging" occurrences, tests/test_skill_tool_names.py + test_forge_foraging_redirect.py. Gate details verified in hooks/consolidated_stop_check.py and cross-referenced to the §4 Check 1b write-up. -->

---

## 9. Spatial Systems

**Two canonical tools.** As of the 2026-05-28/29 spatial-revival (Phases 1–5, complete), spatial gameplay runs through exactly two tools: `map()` for anything the party is *inside* (vault/dungeon/mapped settlement), `geography()` for the overworld. A prior hollow `explore()` tool and a redundant `calculate_journey()` tool were deleted; their useful behavior was folded into `map()` and `geography()` respectively. The system now (a) fires automatically off `Scene Type` (the [Spatial Reflex](#spatial-reflex-phase-2)), (b) is knowledge-gated so the navigator is weighted-but-not-omniscient ([Fog-of-War](#fog-of-war-knowledge-model-phase-3)), (c) accepts generated content 1:1 from content-forge ([Supply](#supply--11-content-integration-phase-4)), and (d) renders on demand, fog-aware, at full label resolution ([Rendering](#rendering--surfacing-phase-5)).

### Map System (Vault/Dungeon)

**File:** `map_system.py`

**Initialization:** `init_map_from_prep()` parses prep files (from the canonical repo-root prep directory) for rooms via regex `##\s*ROOM:\s*(\w+)` — heading must be **h2** (`## ROOM:`), id is `\w+` (no spaces/hyphens/parens). The block runs to the next `## ` heading. Each room block parsed for: Floor, Coords, Name, Connections, Secrets, Type, Entrance, Hazards, NPCs, Loot. Field values are stripped of the bold-label leak (`**Field:**` markup left a stray `**`/leading-space on the first value — fixed Phase 4/5 via `.lstrip('*').strip()` on connections/secrets/hazards/npcs/loot and `.strip('*').strip()` on name). **Coords caveat:** a room with no `**Coords:**` defaults to `[5,5]`, so a multi-room prep that omits coords collapses to one rendered room — real preps must give each room explicit `**Coords:**`.

**Connection format:** `n→touch, e→sight, up→vestibule@2` where `@N` specifies floor transitions. The separator may be `→` (Unicode arrow) **or** `->` — the parser splits on both (`re.split(r'→|->', …)`). Parenthetical annotations on a target (`south→deep_conduit (scout-only)`) are stripped to the bare room id (Phase 4 fix; mirrors secret parsing).

**Secret format:** `alcove→hidden (search + INT DC 14)` — the parenthetical becomes the discovery field. Secrets have a `found` boolean. Discovery requires DM adjudication. It does not auto-discover.

**Room state tracking:**
- discovery_state: unknown → noticed → explored (three states, NOT four)
- search_state: unsearched → searched (separate field from discovery_state)
- party_location and party_floor
- secrets_found (list, append-only — entries formatted as `room_id:secret_id`)
- exploration_log (append-only — also records turn advances)

**Turn + encounter tracking (folded in from the deleted explore() tool):**
- State gains `current_turn`, `noise_level` (standard/noisy/loud), `has_light`, `encounters_rolled`.
- `enter_room()` costs 1 turn with light, 3 turns in darkness; `search_room()` costs 1 turn and is refused in darkness.
- Each turn advance rolls an auto-encounter check: 1d6 where 1 = encounter (reads the prep's `## ENCOUNTERS` section), 2 = omen, 3–6 = nothing. `noisy` rolls 2d6 take-lowest, `loud` rolls 3d6 take-lowest (lower = more danger). Uses `random.SystemRandom()` (not the server dice module — avoids a circular import).
- `set_light(value)` and `set_noise(value)` actions adjust these. Light must be passed explicitly (no silent default).

**Movement validation:** Checks normal connections AND found secret connections. Cannot enter undiscovered secret rooms.

**`spatial_summary(map_name)`:** Inject-ready DM-facing snapshot used by the reflex — party room/floor/turn, adjacent rooms with discovery state, unexplored exits, undiscovered secrets in the current room. Returns None for a missing map; guards dangling connection targets and an invalid `party_location` (returns a repair diagnostic rather than a broken line).

**ASCII rendering:** Coordinate-based grid, Unicode box-drawing characters. Glyphs: ◈ (party), ○ (explored), △ (searched), ? (noticed). Vertical connections shown as arrows inside boxes, not as lines on the map. **Auto-sized (Phase 5):** `BOX_W = max(13, min(longest_room_name + 2, max_box_width))` and `CELL_W = BOX_W + 4` — boxes grow to fit the longest discovered name (no more `Rubicon Se` truncation). `render_map(map_name, floor, resolution)` and the `map(render)` action take a `resolution` (`"compact"` → cap 16, `"large"` → cap 48). Vaults fog via `discovery_state` (unknown rooms are not drawn), not the overworld knowledge model.

### Site Exploration Engine

Generalizes the vault-only map system to any explorable place. A **site** is the unit of exploration; a **vault** is a site that has rooms (`kind=="site"` is set on init when the prep has no `## ROOM:` markers; `kind=="vault"` when it does). A non-vault site is **ambient/roomed** — no room graph, just a place the party occupies while the per-turn clocks and encounter die run.

**Two clocks:**
- `current_turn` — the within-site exploration clock (turn count since entering). Drives the encounter die.
- `last_seen_day` — the world-calendar day the party LEFT the site (plus `last_left_turn`). Stamped automatically by `advance_day` via `_stamp_active_site_left` — last_seen_day is engine-known, so it auto-stamps with no door-gate (unlike NPC continuity). Gives cold-resume the "left day N" context.

**Create-or-resume (`init_or_resume_map`, fronted by the `enter_site`/`map(enter)` action):** entering a site whose state already exists RESUMES it (preserves `current_turn`, discovery, search progress) instead of re-initializing from prep — this fixes the prior reinit-reset bug where re-entering a half-explored place zeroed its turn clock. A fresh site is created from the prep; an existing one is adopted.

**Encounter-die repair:** the per-turn check consumes the prep's parsed `## ENCOUNTERS` table (1d6: 1 = encounter drawn from the table, 2 = omen, 3–6 = nothing; noise raises the die count, take-lowest). It is `turn_based` — each turn advance triggers one check — and runs for ambient sites too, not just roomed vaults.

**Reveal tiers (subsection-grained for roomed sites):** content surfaces in three tiers — **obvious** (revealed on enter), **hidden** (revealed only on `search`), **secret** (DM-gated, never auto-leaked; secret subsection headers and multi-line secret bodies are withheld from player-facing output). Discovery state persists on the map state (`discovery_state`, `search_state`, `secrets_found`).

**Gear-shift + surfacing:** `enter_site` sets `Active Map` in `CURRENT_STATUS.md` (the reflex pointer). `advance_day` auto-stamps `last_seen_day` (scoped to exploration scenes) and carries a reflex nag. Three surfacing channels keep an open site present:
- **Enter/resume baton** — `enter_site` returns a SITE/RESUMING line with the current turn.
- **Per-turn `check_canon` injection** — while in an exploration scene, `_inject_spatial_state` injects `spatial_summary(active_map)` (the `vault_exploration` named branch plus an active-site fallback gated on `"exploration" in scene` — the same gate `_stamp_active_site_left` uses), so an ambient site surfaces its turn-clock line each in-character exploration turn. The gate means a stale `Active Map` left set after leaving does not spam unrelated social/downtime turns. `spatial_summary` has an ambient branch (`kind=="site"` and no rooms) that returns a `📍 Active site … (ambient) — turn N` line; the rooms-based vault rendering is unchanged.
- **Session-start briefing line** — `_active_site_briefing_line()` (near `_active_vault_turn`) emits a `🧭 Mid-exploration at <site> — turn N (left day D)` cue inside `full_session_startup` (§6g) when a site is mid-exploration, omitted entirely when none.

### Site-Entry Detector

**Problem it closes:** the Site Exploration Engine only flips a place into site mode *after* the DM calls `enter_site`. Recognising "this is a site" rested on the DM-model's vigilance — a behavioural seam. The detector makes that trigger fire off **the player's own words**.

**The marker.** Every site prep carries a deterministic HTML-comment marker — a sibling to the `<!-- DUNGEON: ... -->` vault-liveness tag (chosen so the live vault-gate regex is never touched): `<!-- SITE: key=<slug> scene=vault_exploration aliases="A|B|C" -->`. `key` is the `map_name` the site is entered under (== the `Active Map` pointer); for a walkable vault it MUST equal the DUNGEON `map=` slug. The content-forge generator emits it on every site prep; placement is the line under the DUNGEON tag (vault) or the first line (ambient site).

**Module `site_markers.py`** (pure, imported by both the hooks and `server.py`):
- `parse_site_marker(text)` → `{key, scene, aliases}` from the first `<!-- SITE: ... -->`, else `None` (missing `scene` defaults to `vault_exploration`).
- `build_site_index(campaign_dir)` → `{key: {aliases, scene, prep_file, current_turn, last_seen_day, created_day}}` from three unioned sources (marker wins): marker preps (primary); DUNGEON-only preps with a humanised fallback alias (so un-backfilled vaults stay detectable); `maps/*_map.json` keys (already-entered sites). Resume clocks are merged from each `{key}_map.json` when present.
- `detect_named_sites(text, index)` → matched keys via case-insensitive lookaround-bounded alias scan (`(?<!\w)…(?!\w)`, so punctuation-bounded aliases still match), with a min-length + stopword guard against generic false-fires.

**Surfacing (`hooks/phrase_reminder.py`, UserPromptSubmit):** `_build_reflex_block(campaign_dir, state, user_text)` scans the submitted prompt, and for any named site that is not the current `Active Map` pins it in `state["open_site_scene"]` with a short TTL, then surfaces one URGENT reflex line per open site with the exact call: `map(action="enter_site", map_name="<key>", prep_file="<prep>")` plus resume context (`last left turn N, day D`) when known. **Advisory, never a gate** — wrapped fail-open so it can never block a turn. The pin **clears** when the site becomes `Active Map` (compared case-insensitively, since the DM may type a non-lowercase `map_name`), and **fades** via the TTL when a one-off mention is not followed by entry or re-mention.

**Authoring guard (`server.py validate_prep_file`):** a SITE marker's `key` must equal the DUNGEON map slug when present (critical on mismatch); empty aliases or a DUNGEON-header prep lacking a SITE marker warn. This gives the new marker an engine-side validator (closes the check-the-generators loop).

### Settlement Play-Loop (2026-06-15)

**What it is:** a flat, non-hostile "who's around" reader for settlements. No turn clock, no party-location tracking, no new tool — the site-entry detector (above) already handles SITE marker detection; this layer branches on `scene=settlement` instead of routing to `enter_site`.

**Standard for a settlement prep:** carries `<!-- SITE: key=<slug> scene=settlement aliases="…" -->`. Each NPC block carries a `**Location:** <room_id>` field. `validate_prep_file` flags any settlement NPC missing that field (wired to `settlement_system.npcs_missing_location`). The content-forge generator emits both marker and Location fields (`content-forge/SKILL.md`, campaign repo). Coverage: 2 forged settlements (`DUST_PILGRIMS_REST_PREP.md`, `TESSIK_WELL_PREP.md`). The Ceruline arcology uses a different hand-authored shape and is served by a separate bespoke reader (see *Settlement v1 follow-ons* below).

**Leaf module `settlement_system.py`** (pure; imports `site_markers`, never `server.py`):
- `is_settlement_prep(content)` — True iff the SITE marker has `scene=settlement`.
- `_npc_blocks(content)` — yields `(name, title, body)` for each `### NPC` block under `## NPCs` or `## KEY NPCs …` (both header forms recognised by a single regex).
- `parse_settlement(content)` → `{name, npcs:[{name,title,location,role,reaction}], trade}` — extracts Location, Role, reaction first-line, and the TRADE GOODS bullet list.
- `build_who_card(data, npc_overlay, place_overlay)` — renders the roster CARD: settlement-wide standing banner (from `place_overlay["party_standing"]`), one line per NPC (location · title · role · reaction hook), trade line, trailing `update_location_progress` reminder. Authored prose is never rewritten — overlays only annotate.
- `parse_place_status(content)` — latest typed STATUS per target from `- STATUS: <target>: <STATE> (Day N)` lines in the prep's PROGRESS LOG (last write per target wins). Used to build `place_overlay`.
- `build_settlement_index(campaign_dir)` / `resolve_settlement(name, campaign_dir)` — glob all `*_PREP.md` for `scene=settlement` markers, resolve a player/DM name to a prep Path via alias matching (delegates to `site_markers.detect_named_sites`, with a direct-key substring fallback).

**`reference_location` scopes (server.py):** `scope="who"` and `scope="trade"` route to `settlement_system` before the hand-authored `LOCATION_REGISTRY`. `resolve_settlement` finds the prep (error if none); `parse_settlement` parses it; `_settlement_overlays` builds the two overlay dicts; `build_who_card` renders the card (`scope="who"`) or the raw trade line (`scope="trade"`). Prep is re-read fresh on every call — prep is the single source of truth.

**Change handling (no new store):** the DM stamps a change via `update_location_progress(…, status=["the_well: REPAIRED", "party_standing: HOSTILE"])`, which appends `- STATUS: <target>: <STATE> (Day N)` lines to the prep's PROGRESS LOG. `parse_place_status` reads those lines back; the card is built fresh each time, merging base prep + place-overlay (building status, party standing) + npc-overlay. The STATUS regex requires the colon-separated `<target>: <STATE>` shape the `status=` param naturally produces.

**Death overlay (now fed, 2026-06-16):** `build_who_card`'s npc-overlay branch marks a person `†dead since Day N`. The dossier death field is set by `npc(action="record_death", name=…, death_day=…)` (see *Settlement v1 follow-ons* below), and `_settlement_overlays` reads `status=="DEAD"` + `death_day` from `npc_states.json`. Matching is identity-normalized (apostrophe/case + leading-title strip) so a death recorded as "Amara Vane" surfaces for a card name "Matriarch Amara Vane". The place-overlay (standing banner, building status) is also live.

**Push layer:** three seams keep the reader present:
1. **Arrival push** (`hooks/phrase_reminder.py`, `settlement_arrival_push`) — `_build_reflex_block` detects a `scene=settlement` site in `open_site_scene` and calls `settlement_arrival_push(user_text)`, which re-runs `detect_named_sites` against the settlement index and returns a `NEXT (settlement — who's here): reference_location(location=…, scope="who")` push line. Falls back to a direct push-call block if detection doesn't re-fire on a TTL re-render.
2. **Change nag** (`hooks/consolidated_stop_check.py`, `settlement_change_unstamped`) — a non-blocking Stop reflex: detects settlement-change cue words (dead, killed, hostile, banished, …) in the assistant's narrative and nags if `update_location_progress` was not called this turn. Advisory only — never blocks.
3. **Session-end reconcile** — the net for changes that spanned multiple turns without an in-turn stamp. For Ceruline specifically, `hooks/consolidated_stop_check.py::_check_ceruline_reconcile_nudge` prints a one-line advisory at session-end (any of `save_state`/`prepare_save_state`/`distill_session` ran) iff Ceruline came up that session, prompting a `CERULINE_PLAYER_REFERENCE.md` edit. Non-blocking; the "Ceruline seen" flag persists across turns via the check's returned `updates` dict (the Stop runner reloads fresh state and writes only returned updates — in-place `state` mutation does NOT persist).

<!-- ADDED 2026-06-15 (branch feat/settlement-play-loop). Verified against live code: settlement_system.py parse_settlement/build_who_card/parse_place_status/build_settlement_index/resolve_settlement; server.py _settlement_overlays + reference_location scope="who"/"trade" branch; hooks/phrase_reminder.py settlement_arrival_push; hooks/consolidated_stop_check.py settlement_change_unstamped. 2 settlement preps verified in campaign repo. -->

#### Settlement v1 follow-ons (2026-06-16, branch feat/settlement-v1-followons)

Three small additions that "finish settlement v1":

1. **Ceruline bespoke reader** — leaf module `ceruline_reader.py` (imports only `re`/`pathlib`; never `server`). Parses the hand-authored 11-tier `CERULINE_PLAYER_REFERENCE.md` into a per-tier roster via three person-encoding patterns (NPC bullet lists, building role-lines like `**Representative:** Name`, and the `## KEY NPCS` section with `(Tier N)` assignment); descriptor-only role values (e.g. "Four-armed cacogen") are skipped. `reference_location` `scope="who"`/`"trade"` routes Ceruline (matched by `is_ceruline`) to this reader BEFORE the marker path, so forged settlements are untouched. `who` with no `focus` → a lean tier list; `focus=<tier>` → a lean `Name — location` card (one line per person; `†dead` overlay reused via `_settlement_overlays`). `match_tier` resolves a tier by short-label/number, exact-before-substring. Dedup is identity-normalized (`identity_key`: apostrophe/case + iterative leading-title strip) and the `## KEY NPCS` record wins on collision. **One-off by owner ruling** — NOT a generator-emitted standard; a second big settlement would instead get a `**District:**` field added to the content-forge standard format. The dead registry pointer (`CERULINE_ARCOLOGY_REFERENCE.md`, never existed) was repointed to the real file; the non-`who` registry scopes vs the tiered shape remain a pre-existing partial gap (out of scope).
2. **`npc(action="record_death")`** — new action + `death_day` param + `_npc_record_death` helper. Sets `status="DEAD"` + `death_day` (defaults to `get_current_day_safe()`), find-or-creates the dossier record (matching existing by `identity_key` to avoid ghost duplicates), guards non-list `history`, and skips a duplicate history append when already DEAD. NPC-only — does not touch PC/follower/mercenary death seams. Feeds the now-live `†dead` overlay above for both forged settlements and Ceruline.
3. **Session-end Ceruline reconcile nudge** — documented under "Push layer" point 3 above.

<!-- ADDED 2026-06-16. Verified against live code: ceruline_reader.py (parse_ceruline/tier_list/match_tier/build_tier_card/is_ceruline/who_card/trade_summary/identity_key); server.py reference_location Ceruline branch + _settlement_overlays identity fallback + _npc_record_death + VALID_NPC_ACTIONS; hooks/consolidated_stop_check.py ceruline_session_change/_check_ceruline_reconcile_nudge. Suite 2407 passed/1 xfailed; mojibake net-new 0. NOT pushed/merged (Joe-gated). -->

### Player-View Surface (2026-07-05)

**What it is:** the engine-owned, spoiler-safe surface that player-facing chrome (statusline, and
later the /menu previews + companion dashboard) reads. At every state-change seam the engine writes
two artifacts atomically into the campaign dir: `player_view.json` and `player_map.txt`.

**Whitelist, not blacklist (cardinal rule):** `player_view.py` (leaf module, never imports server)
BUILDS the view from player-known homes only — `characters/_meta.json` (day, supply),
`characters/*.json` sheets (name, hp/max, av, wounds count, slots), `party.json` (wealth tokens),
`game_state.json` (location, active-prep NAME only, combat flag), `weather_state.json`, and open
parleys (slug+tier via `social_system.load_parleys`). It never opens antagonist/crossing/purpose-clock
or prep-file content. Guarded by the leak canary (`tests/test_player_view_leak_canary.py`): plants
distinctive secrets in all three hidden homes and asserts absence from both artifacts.

**Fog-of-war map:** `MapSystem.render_fog(map_name)` — only rooms with `discovery_state` explored/
noticed AND not `is_secret` render; unknown/secret rooms are ABSENT (names never appear); noticed
rooms marked `?`, party position `⊕`; connections filtered to fog-visible targets; names only, never
contents. Primary path delegates to `_render_ascii` (one drawing engine for DM + player maps) over a
fog-filtered deep copy; a labeled list-render fallback covers coords-less legacy states.

**Collision auto-layout (2026-07-19):** preps authored without `**Coords:**` default every room to
[5,5], which used to stack all boxes on one cell (last drawn wins, party marker overdrawn — the D135
Thyricost one-room map). `_auto_layout(rooms, party_id)` (map_system.py) now computes a deterministic
render-only layout per floor — BFS from entrance → party room → lowest sorted id, cardinal/diagonal
direction offsets, spiral-probe on collision, disconnected rooms in a free column — applied inside
`_render_ascii` whenever a floor's drawn rooms share coords, so BOTH the DM `render_map` and player
`render_fog` de-stack; authored distinct coords are never touched, and the saved map file is never
mutated. `validate_prep_file` now also warns on missing `**Coords:**`, and content-forge's checklist
requires it. Tests: `tests/test_fog_auto_layout.py`.

**Companion dashboard (2026-07-19 pass):** all four tab `Static`s render with `markup=False` (raw
`[carried]`/`[stale…]` brackets were being parsed as Rich style tags — live garble bug); visible
footer key bindings (q quit, 1–4 tabs, ←/→ cycle); World/Parleys wrapped in `VerticalScroll`;
TOCTOU-safe mtime polling (`model.safe_stat_mtime`); `updated_at` surfaced as "as of HH:MM:SS" in
sub-title + World tab; Map tab headed by the current location; aligned party stat columns; launcher
falls back to the conventional sibling `../rubicon-seven-campaign` when no arg/env is given.
Tests: `tests/test_dashboard_contract.py`, `tests/test_dashboard_launcher.py`.

**Seams:** `_emit_player_view()` (server.py, fail-soft — blanket except → logging.warning, can never
raise into play) fires at save_state (via `session_tools` `_INJECTED`), advance_day, the combat/rest
dispatchers and character update_hp branch (shared emit-tail), and map actions via a None-safe
`MapSystem.on_state_change` callback (never-import-server preserved). Boot fires no seam. Cold-start:
empty campaign → valid empty view.

**Statusline:** `scripts/statusline_rubicon.py` reads `player_view.json` → ONE line
(`Day … · weather │ location │ Name hp/max … │ supply │ ⚔/🤝 flags`), always exits 0, UTF-8-forced
stdout, "no live view" fallback. Registered play-side via the campaign repo's settings `statusLine`
command. **Forge contract (trinity closure):** `validate_prep_file` WARNs when a `## ROOM:` block's
raw text lacks `**Floor:**` or `**Connections:**` (raw-text detection — the parser defaults floor=1,
so parsed values can't signal absence); content-forge SKILL.md carries the matching MANDATORY line.
Spec: `docs/superpowers/specs/2026-07-05-terminal-uiux-design.md`. **Tier 2 shipped (2026-07-05):** the `/menu` skill (`skills/menu/SKILL.md`) — chained AskUserQuestion menus (Characters/Party/Map/Rulebook/Threads & Parleys), every fact from engine tools or the player-view artifacts, Map serves `player_map.txt` only, thread clocks omitted; wiring-gate validated. **Tier 3 shipped (2026-07-05):** the companion dashboard (`dashboard/` Textual app + `scripts/dashboard.py` launcher, textual==7.3.0 pinned) — read-only tabs Party/Map/World/Parleys over the two artifacts ONLY (decoy-file test proves no other file is ever read; zero writes); ~1s mtime poll, last-good+stale on malformed JSON. The emitter's party entries carry item NAMES only — a review-caught str(dict) fallback leak was fixed and locked by a proven-failing canary test. All three tiers of the spec are now live.

### Site-Feature Persistence (2026-07-05)

**What it is:** the "flower" system — leave an item (or any player-known change) at a place and it
becomes a persistent feature of that place until the DM changes it. Fills the gap for UNMAPPED,
un-prepped places (wilderness camps, shrines, landmarks): mapped rooms already persist via
`map(action="update_room")` and prepped places via the PROGRESS LOG; those channels are unchanged
and stay authoritative for their place types.

**Ledger:** `site_features.py` (leaf module, never imports server) owns `<campaign>/site_features.json`
— places keyed by geography-compatible slug, each `{display_name, aliases, next_id, features:
[{id, text, day}], created_day, updated_day}`. Atomic writes (`engine_core._atomic_replace_with_retry`);
missing/corrupt file reads as empty (cold-start safe). **Spoiler rule (by construction):** the ledger
holds only player-known facts — secrets stay in prep files — which is what makes it safe for the
player view. **Engine-vs-DM:** the engine stores and surfaces; it never judges or auto-changes a
feature; `advance_day` does not touch the ledger.

**Routing lever:** `update_location_progress` is place-type-complete. Prep file exists → PROGRESS LOG
(unchanged). No prep file → the call's `summary`, `items_left` ("<item> left here"), `status` lines,
and `consequences` are stamped as ledger features (`_route_to_site_ledger`, server.py). New
`remove="<#id or text fragment>"` param clears one ledger feature (ambiguous fragments error with
candidates; prep places get guidance to edit their log instead). Either path appends a hint when
`maps/<slug>_map.json` exists: room-level detail belongs in `map(action="update_room")`.

**Crystallization nudge:** when save_state inventory changes REMOVE items, the save summary appends
one `🌱 CRYSTALLIZE?` block naming the items and pushing the exact `update_location_progress` call
(`session_tools._crystallize_nudge_block`, `_pf`-assembled so apostrophes survive; advisory —
try/except-wrapped, never fails a save). Current place from `game_state.json` `active_location_name`,
literal `<current place>` placeholder otherwise.

**Resurface seams (all fail-soft):** (1) `geography` `travel_arrive` appends the destination's
`📍 SITE FEATURES` block; (2) `check_canon` injects it when a stamped place is named in turn text or
is the current location (`_site_features_injection`, wired after the geography injection); (3)
`full_session_startup` briefs the current place's features (section 6h, precedence: game_state →
CURRENT_STATUS.md Location line — geography `meta.party_location` is deliberately never consulted;
verified stale in live play); (4) `player_view.json` carries `site_features` (text+day only) for the
current place — leak-canary guarded.

Spec: `docs/superpowers/specs/2026-07-05-site-feature-persistence-design.md`. Tests:
`tests/test_site_features*.py` (module, routing, nudge, surfacing).

### Social Play-Loop (Parley) (2026-07-03)

**What it is:** the Settlement Play-Loop's social sibling — mechanical structure for a negotiation, audience, or diplomatic scene (the named test case is Outer Reach, a diplomatic keyed-site whose own prep opens "This is NOT a dungeon. Combat is the FAILURE state"). It gives a `social_site` scene spatial position-tracking (via the same site-entry machinery as a vault) WITHOUT arming the combat encounter clock, plus a negotiation-progress tracker (tiers, party needles, gated reveals) analogous to `update_location_progress()` for settlements. The engine never judges a negotiation — it parses the authored ladder, stores state, and pushes the exact next call; every tier change, needle shift, and reveal-override is a DM call with a required reason.

**Format contract — the `## PARLEY: <slug>` block.** Authored by content-forge (or by hand) in a prep file, parsed by `social_system.parse_parley_block`:
- `**Stakes:**` / `**Failure state:**` — one-line fields.
- `### TIERS` — a numbered ladder (`N. name — desc | check: STAT DC n`); the em-dash (`—`, not a hyphen) between name and description is load-bearing — the parser requires it. Each tier may carry indented `- label | check: STAT DC n` beats.
- `### PARTIES` — one `#### NPC: <name>` block per side, each with `**Needle:**` (must be one of the 5 `NEEDLE_BANDS`: hostile/wary/neutral/warm/allied), `**Lever:**`, `**Pressure:**`, `**Victory:**`. Trailing inline HTML comments (e.g. the band-legend hint after `**Needle:** wary`) are stripped.
- `### REVEALS` — `- label | gate: tier>=<tier> OR STAT DC n` (either clause optional; `parse_gate` OR-splits on literal `" OR "`).
- `### TEXTURE (dN)` — an optional `| roll | text |` table read by the `social_site` encounter die instead of the generic liveness result.

`social_system.lint_parley_block` is the round-trip guard between the generator (content-forge's `## PARLEY AUTHORING` section, `skills/content-forge/SKILL.md`) and the engine: malformed blocks, duplicate tier names, invalid needle bands, and reveal gates referencing an unknown tier all warn; a legacy `## VICTORY CONDITIONS`/`**VICTORY CONDITION:**` section with no `## PARLEY:` block also warns (migrate it). Wired into `validate_prep_file` (server.py) alongside the existing map-schema/walkability checks; silent (`[]`) when a prep has neither shape — most preps aren't negotiations. `tests/test_social_forge_roundtrip.py` pins the generator's template against the parser.

**State file — `parleys.json`** (campaign dir, atomic write via `_save_json_atomic` with Windows-lock retry, same pattern as other campaign stores). One record per slug; **slugs are never reused** — a closed parley's record is kept as permanent history, so opening a slug that belongs to either an open or a closed parley raises `ValueError`. Record shape: `site_key`, `title`, `status` (`open`/`closed`), `opened_day`, `closed_day`, `outcome`, `stakes`, `failure_state`, `tiers` (each stamped with `reached_day` and per-beat `satisfied`/`day`/`note`), `current_tier`, `parties` (each with `needle` + an append-only `history` of shifts), `reveals` (each with `unlocked`/`unlocked_day`), `texture`, `log` (append-only day/entry pairs).

**Tool: `parley`** (registered by `social_system.register_social_tools`, called from `server.py` with a lazy, never-raising `get_day` wrapper around `get_current_day_safe`). Eight actions:
- `open` — from a prep (`prep=<path>` or `site=<key>`, resolved via `site_markers.build_site_index`) or inline (`title`, `stakes`, `parties`). A prep with no `## PARLEY:` block errors.
- `status` — current tier, unsatisfied beats, party needles, reveal gate labels; `slug` is optional and infers the single open parley (errors listing all open slugs if there are several).
- `list` — one line per open parley; the terminal answer when there are none (no push — the engine never proposes opening a negotiation, that's DM judgment).
- `move` — logs a beat of dialogue/action (`note` required), optionally marks a `beat=<id>` satisfied and/or shifts one NPC's `needle`.
- `tier` — advances/changes the tier (`to`, `reason` **required**); **warns, never blocks**, if beats up to that tier are unsatisfied.
- `needle` — shifts an NPC's disposition band directly, stamping party history.
- `reveal` — attempts to unlock a gated reveal: gate met → unlocked; gate unmet but `reason` given → **unlocked via override**; otherwise GATED, printing only the label and the gate's *condition* (never reveal content, which the engine never stores).
- `close` — sets `outcome`/`closed_day`, then pushes the crystallization trail (`update_location_progress` + `lorebook(action="add")`).

**Push-the-roll rule:** whenever a beat, tier check, or reveal gate carries a `STAT DC n` check, the engine never resolves it — it pushes `roll(action="check", ability=…, dc=…, character="<party face>")` and lets the DM rule the outcome. Every response (including the zero-state `list` with no open parleys) ends with a pushed next call except that documented `list` exemption; error/ambiguity paths (`_err`) also end with a pushed `parley(action="list")` so there is always a way to reorient.

**Four surfacing seams keep an open negotiation present without the DM having to remember it:**
1. **check_canon ride-along** — when an NPC named this turn is a party to an open parley (matched by display name via `social_system.find_by_npc`, case-insensitive), a compact `🤝 PARLEY …` line (current tier, that NPC's needle, next unsatisfied beat, count of still-gated reveals) is injected alongside the NPC's dossier block, capped at 2 parleys per NPC, ending with a pushed `status` call. Reveal content is never in this line — there is none in state to leak.
2. **Session-start briefing** — `full_session_startup` §6e-parleys prints a zero-safe `🤝 OPEN PARLEYS` section (one line per open parley: title, tier, party needles, opened day) via `social_system.parley_briefing_lines`, ending with a pushed `status` call for the oldest open parley.
3. **Stale-parley advisory** — `hooks/consolidated_stop_check.py`'s `_check_stale_parley_nudge` prints one line per open parley quiet ≥7 campaign days (age = current day minus the latest of `opened_day`/log-entry days). Maintenance-gated (`in_maintenance`), non-blocking, always returns `(False, "", {})`.
4. **`social_site` spatial/encounter tie-in** — see below.

**`social_site` scene semantics.** `social_site` is a member of `_EXPLORATION_SCENE_TYPES` (server.py) alongside `vault_exploration`, so a keyed diplomatic site gets the same per-turn `check_canon` spatial injection and `advance_day` last-seen-day stamping as a vault — but `map_system.py` threads the prep's `<!-- SITE: … scene=social_site … -->` marker into map state as `scene`, and the per-turn encounter die branches on it: a `social_site` never calls `_encounter_push_trail` (the reaction→lookup→combat chain). Instead, a `1` result calls `_read_social_texture`, which prefers the *open parley's own* `TEXTURE` table keyed to that site (matched by `site_key`), falling back to the prep's parsed `## ENCOUNTERS` table reframed as texture, and finally to an improvised color beat — always tagged "Weave as tension/color, NOT an ambush (no reaction roll, no statblock)." A `2` result gives a similarly reframed "a quiet sign the moment is watched" line. Combat only enters a `social_site` scene through an explicit DM trigger, then hands off to the combat layer normally — the engine itself never arms it.

**Engine-never-judges boundary.** The parley tool is pure mechanism: it never advances a tier on its own (every `tier` call requires an explicit `to` + `reason`), never moves a needle without a `needle`/`to` action, never narrates a beat or a reveal's content, never auto-rolls a gated check (always pushes `roll(...)` for the DM to call), and never blocks on unsatisfied beats (only warns). The four surfacing seams are read-only reminders — none of them open, advance, or close anything.

**Dice-honesty hardening (2026-07-03, branch `feat/dice-honesty-hardening`).** Two flank guards, both nudge-only. (1) *Site-entry opener push:* `map_system._social_entry_push` — entering or resuming a `social_site` map with no open parley matching its `site_key` appends a pushed `parley(action="open", slug="<key>_parley", site="<key>")` to the map output; silent when a parley is open, silent for vault scenes, lazy-import failure-tolerant (tests: `test_social_entry_opener.py`, 5). (2) *Prose-dice watcher:* `hooks/consolidated_stop_check.py:_check_prose_dice` — a maintenance-gated, never-blocking Stop advisory that fires when the turn's narration contains dice **resolution** language ("give me a roll", "rolled a 14", formula+DC/beat, "natural 20") while none of `roll`/`test_dice`/`combat`/`map` ran that turn; sheet-notation lines (weapon `d8`, gift costs, codex DC displays) are suppressed, precision over recall by design — known accepted false positives are recap/quoting prose (tests: `test_prose_dice_watcher.py`, 25). Spec: `docs/superpowers/specs/2026-07-03-dice-honesty-hardening.md`.

<!-- ADDED 2026-07-03 (branch feat/social-play-loop). Verified against live code: social_system.py (parse_parley_block/lint_parley_block/open_parley/get_open/find_by_npc/parley_blocks_for_npc/parley_briefing_lines/register_social_tools + the parley tool's 8 actions); server.py registration (_social_get_day_safe, line ~2880), _EXPLORATION_SCENE_TYPES incl. social_site, validate_prep_file PARLEY lint (~line 2773), check_canon NPC ride-along (~line 5135), _parley_briefing_lines wrapper (~line 8035); map_system.py scene threading (~line 259) + _read_social_texture (~line 920); session_tools.py §6e-parleys (~line 462); hooks/consolidated_stop_check.py _check_stale_parley_nudge/_stale_parley_lines (~line 1896); skills/content-forge/SKILL.md ## PARLEY AUTHORING section. Tests: tests/test_social_*.py (parser 9, store 8, tool 8, actions 11, wiring 1, scene 8, injection 4, briefing 3, lint 5, roundtrip 2, nudge 7). -->

### Geography System (Overworld)

**File:** `geography_system.py`

**Coordinate system:** Axial hex grid. Ceruline at (0,0). 1 hex = 1 day foot travel (~15 miles). North = +Y, East = +X.

**Distance formula:**
```python
def _hex_distance(x1, y1, x2, y2):
    dx = abs(x2 - x1)
    dy = abs(y2 - y1)
    return max(dx, dy, abs(dx - dy))
```

**Routes (single source of truth):** Stored data, not computed paths. As of Phase 1, `VAARN_GEOGRAPHY.json` is the sole overworld source — the 3 rich routes from the former `TRAVEL_ROUTES.json` (distance_miles, direction, terrain, canonical verified times) were merged in, and `terrain_modifiers` brought along. No pathfinding — routes are declared data points.

**`journey(origin, destination, mode=None)` (folded in from the deleted calculate_journey()):** Returns a travel plan — prefers verified canonical times, else calculates from distance ÷ transport speed (reading `TRANSPORT_SPEEDS.json` as the shared speed engine — the engine's generic base merged with an optional campaign-side `TRANSPORT_SPEEDS.json`, campaign wins per entry; campaign transport modes are play-state and never ship), else falls back to a hex/day estimate. Unknown modes report "no data available" rather than silently emitting nothing.

**`position_context(center, radius=6)`:** Position-relative overworld summary used by the reflex during travel — nearby locations with hex distance + hazard, nearest-first, capped at 8 with a "+N more" overflow hint; empty string for an unknown center. **Fog-aware (Phase 3):** silently drops `fogged` locations and tags `known`-by-reputation ones "(by repute)" — see [Fog-of-War](#fog-of-war-knowledge-model-phase-3).

**Data source:** `VAARN_GEOGRAPHY.json` — 28 locations (coordinates, type, region, `explored`, `known`), 21 routes, 14 regions; plus `TRANSPORT_SPEEDS.json` for mode speeds.

**`validate_consistency()` (Phase 4):** A spatial sanity check (tool action + dm-design gate). Reports coordinate collisions (two locations on one hex), routes referencing a missing location, locations whose `region` isn't in the regions map, missing-coords records, and malformed routes. Returns a clean-bill string when none found. (The live data is clean: the 9 regions referenced-but-undefined were defined from canon — lorebook *PDF p.317 Appendix E* + the campaign's Umber Reaches — so all 28 locations resolve.)

### Travel & Expedition (the step-per-day point-crawl)

**Book truth (CH pp.142-149): overland travel is an abstract DAY-COUNT POINT-CRAWL, NOT a hexcrawl.** Distances are in days between region nodes (route `days_foot`, or `d6/2d6/3d6` by map distance; vehicle ÷2). A hex-grid travel system would be homebrew. Three `geography` actions drive it (logic in `geography_system.py`; state in atomic `travel_state.json`):
- **`depart(destination, mode, noisy, origin?, food?, water?, follower_mouths?)`** → resolves `days_total` (float), writes travel state, enters supply field mode (via the `on_depart` callback → `supply(depart)`), pushes the first `travel_day`. **D134 fixes (2026-07-17):** `origin=` overrides AND persists the stored party location (which was verified stale in live play; without it, the output flags "read from stored party location"); `food`/`water`/`follower_mouths` pass through to `supply(depart)` as pool seeds (vehicle/cargo provisions) and the supply output is SURFACED in the depart result, not swallowed; a failed depart (unknown origin/destination) no longer flips supply to field. **Mode-aware days** (`_resolve_days`): canonical per-mode route days (`days_<mode>`) win; else fast modes resolve from the transport-speed table (`daily_range_miles`, or `base_speed_mph × sustained_hours`, against route `distance_miles` or crow-flies) with a 1-day minimum — an ornithopter is never charged foot-days (the D134 15-days-for-a-2-hour-flight bug); else `days_foot`/dice band with the legacy vehicle ÷2. tests/test_d134_travel_supply.py.
- **`travel_day(pace, forage)`** → resolves ONE day: roll weather (gates the day — `normal`/`half`=0.5 progress/`none`=0), advance the calendar by 1 (`on_day_tick` → `advance_day`, so rations/conditions/world-tick fire), roll day+night d6 encounter dice (1=Encounter→pause+push reaction, 2=Omen, 3-6=nothing; `2d6/3d6`-take-lowest if `noisy`/`forced`), Vigilance d6, decrement `days_remaining`, push the next `travel_day` or `arrive`. `pace="forced"` = 2× distance + an Exhaustion push; `forage=True` = a stay-put day (pushes `supply(forage)`); getting-lost (+d6 days) fires only when a no-travel weather is pushed through under forced pace.
- **`arrive()`** → sets party location, clears travel state, and **hands off to the site-entry detector** (pushes `enter_site` if the destination is an adventure site). **Supply is NOT auto-flipped to abundant (D134 fix, 2026-07-17):** whether an arrival is a supplied base is DM judgment ([[feedback-engine-vs-dm-judgment]]) — arriving at a dead vault's salt-bore rim used to silently end field-mode ration tracking. The `on_arrive` callback is unwired; instead the output pushes `supply(action="arrive", location=)` explicitly gated "IF this is a supplied base", and that supply call still clears Deprived + stamps the World-Tick return clock when run.

Engine ROLLS the dice (travel-time, weather, encounter, Vigilance, lost); the DM ADJUDICATES (the Encounter's identity via the local table; Pursuit's 3 opposed CON saves and Night-Watch surprise as flagged menus). Weather effects (p.146) are wired: half-speed (Dust Storm/Worm-pollen), no-travel (Sand Storm/Prismatic Tempest), 2× water (Heatwave, surfaced), ration gains (Rain/Worm-pollen). Deferred: auto-tracking the Exhaustion inventory item on sheets, and auto-applying Heatwave 2× water in the supply tick (both surfaced as pushes today). Absent-from-book and NOT built: hex grid, miles, nav checks, guide role, porter logistics.

### Reaction roll (CH p.36, book-faithful)

`_roll_reaction` rolls **d20 + EGO** on the book's **4 bands** — Negative (1-7) / Indifferent (8-15) / Positive (16-20) / Actively Helpful (21+). (Replaced a prior 7-band invented table.) **ADV** (2d20 take-higher) / **DIS** (take-lower) come from structured modifiers, netted 1:1: `_reaction_modifiers(char, vs_ancestry, vs_faction)` reads ancestry `special_rules[].reaction` (true-kin **Pure of Blood** = ADV vs true-kin), augmentation `reaction` fields (e.g. an **Etiquette HeadBank** = ADV on all), and **faction standing** (`factions.standing_for(rep)["reaction"]` → ADV when Liked, DIS when Disliked). `roll(action="reaction", character=, vs_ancestry=, vs_faction=)` resolves EGO (dict-or-int) + net ADV/DIS for a named PC; the bare `character_ego` path is unchanged. A travel Encounter pushes this call with the party's modifiers pre-computed — but never auto-rolls (book: the Referee rolls only "when reaction isn't obvious").

**Rendering:** Both ASCII (staggered hex grid, flat-top hexagons) and SVG (Vaarn desert color scheme). Both are **fog-aware and auto-sizing** — see [Rendering](#rendering--surfacing-phase-5).

**Passive context injection:** `scan_for_locations(text)` matches location names against user input (key, display-name, spaceless, and 3+ char partial match); `format_context_injection` renders the matches at the party's **knowledge tier** (Phase 3): `full` → coords + description + travel; `known` → same, tagged "by reputation"; `fogged`-but-named → a name/region stub with a "no first-hand knowledge — do not narrate specifics" caveat (a mention is an in-world reason to surface it, but not to reveal it). Input-keyword-gated, distinct from the scene-driven reflex below.

### Spatial Reflex (Phase 2)

The demand-side wiring that makes the above tools fire automatically during play, riding the `Scene Type` the DM already maintains in `CURRENT_STATUS.md` — no new gate or intent-detector.

- **`Active Map` field** in `CURRENT_STATUS.md` (revived from a previously dead field): parsed by `_parse_status_content`, written by `_update_current_status_active_map` (returns False rather than fabricating an absent field).
- **`_inject_spatial_state(status_parsed)`** runs inside `check_canon` (every in-character turn), placed after the passive geography block and *outside* its keyword guard so it fires on scene type, not input wording. Fail-open (any exception → None, never breaks check_canon):
  - `vault_exploration` → if no Active Map, auto-init from Active Prep (adopting an existing map's state rather than clobbering progress), write the field, inject `spatial_summary`. A prep with no `## ROOM:` markers falls back to prose silently (no field write).
  - `settlement` → inject `spatial_summary` only if an Active Map is already set; never auto-inits (avoids spamming social scenes).
  - `travel` / `hexpedition` → inject `position_context` from the party's tracked overworld position.
- **The one behavioral dependency:** the DM sets `Scene Type` at scene boundaries. This converts the old per-turn "remember to call a spatial tool" discipline (the documented failure mode) into a per-boundary decision, with the injected state then prompting per-turn `map(enter)`/`map(search)` calls.

### Fog-of-War Knowledge Model (Phase 3)

Geography is neutral data; the party's navigator is the default lens for the *macro* chart, but gated by what's earned — enhanced, not omniscient. Each location carries two booleans: `explored` (been there) and `known` (known-of by reputation). `_knowledge_state(loc)` resolves the tier:

- **`full`** — `explored=True`. Full detail.
- **`known`** — `known=True`, not explored. The macro chart: name, region, direction, coords — no interior.
- **`fogged`** — neither. Silent in the unprompted spatial sweep; a name/region rumor-stub only if explicitly mentioned.

`explored` implies `known`, enforced at **every** write path (`mark_explored`, `update_location("explored", True)`); `mark_known` promotes a fogged site to known-of. **Gating applies to auto-injection only** — `position_context` (the travel reflex) drops fogged and tags known "(by repute)"; `format_context_injection` (the named-location scan) renders the three tiers as above. DM-direct tool actions (`query`, `get_distance`, `journey`, `render`) stay omniscient — fog governs what is *narrated*, not what the DM operator can inspect, consistent with the CLASSIFIED rule. Backfill of the 28 live locations is type-driven: macro types (landmark, terrain, anomaly, arcology, crossroads, arcology_ruin, arcology_coastal) → known; specific types (vault, camp, oracle, ruin, settlement, cave_system) → fogged-until-visited. Result: 6 full / 14 known / 8 fogged.

### Supply — 1:1 Content Integration (Phase 4)

The root cause of "maps never just worked": two prep parsers disagreed on the room format. `map_system._parse_rooms_from_prep` (the walkable engine) read **h2** `## ROOM:`; `server._load_prep_file` / `validate_prep_file` read **h3** `### ROOM:`. The validator blessed preps the walkable engine couldn't read. Resolution:

- **Canonical = h2 `## ROOM:`.** `_load_prep_file`'s room regex was aligned to `map_system`'s exact pattern; the two now parse the same rooms (asserted by test). `validate_prep_file` cross-checks the walkable parser, so "valid" ⟺ "walkable." The `### SECRET:` spoiler-section mechanism is separate and unchanged.
- **content-forge** (`content-forge/SKILL.md`) documents that canonical format exactly, with no stale tool references (the deleted `location_init`/`map_init`/`location_*`/`map_*` calls were replaced by the consolidated `map(action=…)`/`geography(action=…)`), mandatory overworld registration via `geography(add_location, …, known=<by type>)`, and `**Entrance:**`.
- **dm-design** gains a spatial-consistency gate (runs `validate_consistency`, confirms walkable rooms + registration), scoped to issues the *design introduced* (pre-existing data debt does not block).
- **Curated backfill** (the active/near-future preps at the time): all walkable (every room reachable from a marked entrance); one overworld-only site registered as its node (interior authoring is downstream content).

### Rendering / Surfacing (Phase 5)

Maps render **on demand**, fog-aware, at full label resolution. `fog_of_war` defaults `False` (DM omniscient); `fog_of_war=True` is the player-facing render, handed over via `SendUserFile`.

- **Fog (overworld):** ASCII hex (`_render_ascii_map`) and SVG (`render_svg`) key on `_knowledge_state` — `full` solid/explored-fill, `known` dashed/dim-fill, `fogged` hidden (`?` / omitted) when fog is on; DM default shows all. `generate_svg_map` and the `geography(render_map/generate_svg)` actions take `fog_of_war`.
- **Auto-sizing:** hex `content_w` and vault `BOX_W` size to the longest label (no `Sandwhisp`/`Rubicon Se` truncation); a `resolution` param ("compact"/"large") caps inline width and lifts it on request.
- **Glyphs/colors:** the four Phase-4 types (arcology_ruin, arcology_coastal, cave_system, settlement) have dedicated ASCII glyphs (⬙ ◐ ◬ ⌂) and SVG `TYPE_COLORS` + legend entries — no anonymous fallback. Player-facing SVG suppresses DM status text.
- **CLAUDE.md** auto-trigger: *player asks to see the map* → `geography(render_map, fog_of_war=True)` inline or `geography(generate_svg, fog_of_war=True)` + `SendUserFile`.

<!-- REVIEWED AND REWRITTEN 2026-05-29 (capstone) — Updated to reflect the FINISHED spatial-revival Phases 1-5. Line counts re-verified against code: map_system 1106→1114, geography 1240→1407. Corrected two now-false claims from the Phases-1-2 draft: connection separator is `→` OR `->` (parser splits on both — the "→ only" claim was wrong), and position_context is now fog-aware (was "RAW"). Replaced "Pending Phases 3-5" with three completed subsections: Fog-of-War Knowledge Model (Phase 3 — known flag, _knowledge_state full/known/fogged, gating on position_context + format_context_injection, DM-direct omniscient, 6/14/8 backfill); Supply / 1:1 Content Integration (Phase 4 — canonical h2 ## ROOM:, _load_prep_file aligned to map_system, validate_prep_file walkability cross-check, validate_consistency, content-forge stale-tool purge + mandatory registration, dm-design gate, 6-prep backfill); Rendering / Surfacing (Phase 5 — fog_of_war on ASCII hex + SVG, BOX_W/content_w auto-size + resolution, 4 type glyphs/colors, on-demand player render via SendUserFile). Added: parser bold-label-leak + parenthetical-strip fixes, Coords [5,5] caveat, validate_consistency, 14 regions (9 defined from canon Appendix E + Umber Reaches), 28 loc/21 routes/14 regions counts. Spatial Reflex (Phase 2) retained unchanged. All symbols verified present in code (41-hit grep: _knowledge_state, validate_consistency, mark_known, fog_of_war, resolution, content_w, TYPE_COLORS, arcology_ruin). -->

---

## 10. ChromaDB & Vector Search

<!-- REVIEWED AND UPDATED 2026-06-06 — refreshed live counts after the v3 whole-campaign distillation harvest: canon_distillations collection 179 → 1,459; .canon_distillations.json cache 179 → 1,459; campaign_history_tiered ~12,400 → ~13,005 chunks (verified via get_canon_distillations_collection().count() / get_chroma_collection().count()). VALID_TOPIC_SUFFIXES corrected to 7 (added `identity`). Documented the two distillation lanes' read-time hygiene (placeholder drop via _is_placeholder_nugget, cross-lane topic_key dedup, deliberate no-truncation, input-mention-queued-last); full rationale in §3 Delta Delivery. -->

<!-- REVIEWED AND CORRECTED 2026-05-29 — Full re-verification against live code + running DB. Corrected: (1) embedding functions 2→3 (added batch get_ollama_embeddings_batch); (2) collection is campaign_history_tiered_v2 (cosine), logical name redirected by get_chroma_collection, L2 legacy fallback; live count 8,200+→~12,400 chunks; (3) search_history_tiered step 3 — only arc+scene_type are ChromaDB where-filters, character+day are Python post-filters; added tier=0 multi-tier mode; (4) progressive search added WEAK band (≤0.7) feeding drill_recommended; (5) distillation entry schema corrected (verified_against key is lorebook_mtime not lorebook.json; added key_facts/source_pointers/created_turn/created_session/refined_turn; file wrapped in {schema_version, distillations}); (6) added distill_session generation step (Phase 9.25). FUNCTIONAL FIX: canon_distillations collection was empty (179 cache entries all marked ingested by a 2026-05-18 backfill, but the collection had been rebuilt empty); added ingest_distillations(force=True) recovery path and refilled the collection (now 179, semantic retrieval verified ≤0.5). SOUNDNESS PASS 2026-05-29 (overbuilt/underbuilt/wired/embeddings): added drift alarm to chroma_health_check; retired legacy reindex_campaign.py + repointed 2 stale breadcrumbs; documented read-time staleness limitation. Embeddings verdict: 768-dim nomic cosine is sufficient for this corpus (~12,400 chunks); thresholds 0.5/0.7 well-calibrated (live hits 0.28–0.44). -->

### Infrastructure

**Embedding model:** Ollama running locally with `nomic-embed-text` at `127.0.0.1:11434` (literal IPv4 since 2026-07-04 — `localhost` resolved IPv6-first on the host and cost a measured ~2s stall per uncached call before fallback). A warmup call fires at server startup (module load) to avoid a slow first request; `check_ollama_health()` then caches availability and backs off for 60 seconds after a failure rather than hammering a down server.

**Three embedding functions** (all share the `nomic-embed-text` model; the task-type prefix matters for retrieval quality):
- **Query** — `get_embedding_cached()`: adds `"search_query: "` prefix, LRU cached (512 entries, keyed by MD5 of the prefixed text). Used for all searches.
- **Index, single** — `get_ollama_embedding_sync()`: adds `"search_document: "` prefix, not cached. Used when indexing one item.
- **Index, batch** — `get_ollama_embeddings_batch()`: adds `"search_document: "` prefix to each item, single `/api/embed` call. Used by reindex paths to embed many chunks at once (much faster than looping).

> Note: `ingest_distillations()` deliberately embeds distillation *documents* with the **query** embedder (`search_query:` prefix) so they match how `check_canon` queries them — both sides use the same prefix.

### Collections

| Logical name | Physical collection | Content | Live size | Similarity |
|------------|---------|---------|------|-----------|
| `campaign_history_tiered` | `campaign_history_tiered_v2` | 80+ sessions, chunked in 4 tiers | ~12,052 chunks (post 2026-07-04 cross-source dedup; `scripts/chroma_staleness.py` reports the live count) | Cosine |
| `canon_distillations` | `canon_distillations` | Verified semantic learnings (the "fact cheat-sheet") | ~1,464 entries | Cosine |

`get_chroma_collection("campaign_history_tiered")` redirects to the cosine `_v2` collection, falling back to a legacy L2 collection only if `_v2` is absent. Distance thresholds adapt to the metric via `_chroma_thresholds()`: cosine collections use GOOD ≤ 0.5 / WEAK ≤ 0.7; legacy L2 uses 300 / 350.

### Tiered Chunking

The live indexer is `chunk_text_tiered()` in `server.py`. Text is split at semantic boundaries first (Tier 4), then each Tier 4 parent is sub-chunked into smaller tiers:

| Tier | Size | Overlap | Purpose |
|------|------|---------|---------|
| 4 | ~3000 chars | Semantic boundaries | Full context chunks. Split at `## SESSION SAVED` → `###` headers → `---` dividers → paragraphs (falls back to fixed-window 3000/500 if no structure found) |
| 3 | 800 chars | 200 (25%) | Medium context |
| 2 | 300 chars | 150 (50%) | Default search tier |
| 1 | 150 chars | 75 (50%) | Micro context, highest precision |

Tiers 1-3 are fixed-window sub-chunks (stride = size − overlap) of their Tier 4 parents, linked by `parent_id`. Each chunk stores: original text (for display) + `embedding_text` (markdown stripped, what actually gets embedded). Metadata: day, arc, characters, scene_type, tier, parent_id (tiers 1-3), source, char_count.

> Note: `migrate_to_v2.py` is a one-time migration script and chunks sub-tiers differently (sentence-boundary, no overlap). The live ongoing path is `chunk_text_tiered()` / `reindex_recent()`, which the table above describes.

### Search Pipeline

**`search_history_tiered()` flow:**
1. Get cached query embedding (the raw query is embedded as-is; the old `_enhance_query_with_context` character-trait enhancer was a dead no-op and was deleted 2026-07-04)
2. Query ChromaDB filtering **only** on `arc` and `scene_type` (the metadata stored as exact-match fields)
3. Post-filter in Python by `day_min`/`day_max` and `character` (over-fetches 3× when post-filtering); `tier=0` searches tiers 1-4 and merges, otherwise a single tier is queried
4. Fuse in the BM25 lexical lane by Reciprocal Rank Fusion (`lexical_lane.py`; lexical-only hits enter at a WEAK-band baseline distance) — see the RAG-hardening addendum below
5. Apply keyword boost — distance × `0.95 ** (keyword matches)`, i.e. ~5% closer per matched query word
6. Apply recency re-rank (`_apply_recency_weight` — mild capped day-decay, strong-match bypass)
7. Apply MMR-style day diversification — 50% distance penalty for results sharing an already-selected day

**Progressive tier search** (`_progressive_tier_search`, used by check_canon):
Searches tiers 1→3 in order, stopping at the first tier with a "good" match (cosine ≤ 0.5) and returning only that tier's good results with signal **`sufficient`**. If no tier is strong but some are within the WEAK band (≤ 0.7), it returns those as fallback with signal **`drill_recommended`**. If nothing qualifies, signal **`no_match`**. Capped at 5 results.

**RAG hardening sprint (2026-07-04, spec `docs/superpowers/specs/2026-07-04-rag-hardening-sprint.md`):** the raw-history lane is now a HYBRID pipeline in both consumers (check_canon + `search(action="history")`): vector tier search → **BM25 lexical lane** (`lexical_lane.py`, leaf module, `rank_bm25` with a tested pure-Python fallback; lazy per-process index rebuilt on collection-count change) fused by **Reciprocal Rank Fusion** (k=60, rank-only; lexical-only hits enter at a WEAK-band baseline distance) → keyword boost (tiered-search lane only) → **recency re-rank** (`_apply_recency_weight`: multiplicative distance penalty, linear in age, capped 20%, strong-match bypass at half the good threshold, neutral on missing day metadata) → day diversification/output. Failure is LOUD: any silent semantic-lane failure (embedder down, collection missing, outer exception) appends `⚠ SEMANTIC RECALL OFFLINE this turn (<reason>)` to the brief — informational only, the canon gate still opens. The ≤20-char semantic skip is gone; short inputs (<40 chars) embed with scene grounding (location + present NPCs). Cultivated ride-along blocks (antagonist triggers, crossings, parleys) carry the 🔒 SECRETS marker so the spoiler hook fires on them like prep secrets (twin constants in server.py/social_system.py). NPC auto-index writes document-prefix embeddings with day/arc/scene_type; `reindex_recent` pre-deletes same-day docs from `save_state`/`tiered_reindex` only (never `npc_auto_index`). Ollama calls use `127.0.0.1` (measured ~2s/call IPv6-resolution stall on `localhost`). Guards: `tests/test_retrieval_canary.py` drives a REAL temp Chroma collection through the composed pipeline with negative controls — broken retrieval can no longer ship green. Ops tooling: `scripts/chroma_staleness.py` (read-only freshness check, exit-coded) and `scripts/score_canon_recall.py` (haiku-judged recall scoring of the 260-case bed); the recall-gate copy step takes the engine's chroma write lock.

### Distillation Cache (the verified-fact cheat-sheet)

**File:** `hooks/.canon_distillations.json`, structured as `{ "schema_version": 1, "distillations": { "<topic_key>": <entry> } }`.
**Purpose:** Pre-verified canon facts, keyed by a normalized topic (character pair or single character + suffix like `relationship`/`history`), so `check_canon` can answer without re-researching raw history.

```json
{
  "topic_key": "amara_varro_relationship",
  "learning": "semantic summary of the verified canon",
  "key_facts": ["..."],
  "source_pointers": ["lorebook.json#amara", "..."],
  "verified_against": {"lorebook_mtime": 1778978390, "npc_states_mtime": 1778978390},
  "created_turn": 12,
  "created_session": "2026-05-18",
  "refined_turn": 40,
  "refined_count": 3,
  "ingested_at_session": "2026-05-18-backfill"
}
```

**Lifecycle:**
- **Generate** — `distill_session(action="analyze"|"write")` at session-end Phase 9.25 scans the session, flags stale/new topics, and writes entries into the cache file.
- **Ingest** — `ingest_distillations()` at Phase 9.5 reads cache entries, embeds each `learning`, and upserts into the `canon_distillations` ChromaDB collection. Normal mode posts only entries with `ingested_at_session = null`; **`force=True` re-posts every entry** — the recovery path for when the collection has been rebuilt empty while the cache still marks entries as ingested.

**Two-layer lookup in check_canon** (cheapest first):
1. **Local file cache** (`_query_distillation_cache`) — exact lookups, queued in priority order: present-character pairs (relationship/history) → present-character identity → any participant slug (≥3 chars) appearing in the input. Input-mention is queued **last** by design (a 2026-06-06 experiment that promoted it ahead of the present-character facts ballooned volume +17% by pulling long relationship/history nuggets ahead of short identity facts). Capped at 5. No embeddings needed; works even if Ollama is down.
2. **ChromaDB `canon_distillations`** — semantic match by *meaning*, catching relevant facts the name-based layer misses. Capped at 5. Strong hits (cosine ≤ 0.5) are surfaced as RELEVANT CANON and **replace** raw-history drilling. Skips any topic_key already queued by layer 1 (cross-lane dedup).
3. Only when both distillation layers come up empty does check_canon fall through to a tiered search of `campaign_history_tiered`.

Both layers drop placeholder/`<UNKNOWN>` payloads via `_is_placeholder_nugget`, and neither length-truncates a nugget (payloads are fact-dense; truncation costs recall — see §3 Delta Delivery).

### Health & Known Limitations

**Drift alarm.** `chroma_health_check()` reports a distillation line comparing the cache (entries marked ingested) against the live collection count, and flags `⚠️ DRIFT` with the `ingest_distillations(force=True)` remedy when the collection is empty (or smaller than the cache claims). This exists because the normal ingest path only posts *unposted* entries and therefore cannot self-heal a wiped collection — the exact failure that left the collection empty before 2026-05-29.

**Staleness is checked at generation, not at read.** Each distillation records `verified_against` source mtimes, and `distill_session(action="analyze")` flags entries whose sources changed (`DistillationCache.is_stale`). That check runs at session-end, **not** when `check_canon` serves a fact mid-session. So editing `lorebook.json`/`npc_states.json` during a session can leave a stale fact served until the next session-end refresh. Accepted trade-off for solo play: enforcing freshness on every canon lookup costs more than the rare mid-session lore edit it would catch.

**Single live indexer.** `chunk_text_tiered()` (server.py) is the only ongoing chunker. `migrate_to_v2.py` remains as a labeled one-time migration artifact (sentence-boundary sub-tiers, no overlap — *not* the live scheme). The legacy flat chunker (`reindex_campaign.py`, ~1,200-char single-tier) was retired 2026-05-29; stale "run reindex_campaign.py" breadcrumbs were repointed to `reindex_recent()`.

---

## 11. Tool Visibility & Gating

<!-- The context-cluster tool-visibility-filtering system was removed wholesale (2026-05-29); the section below explains why. Removal detail in git history (feat/canon-redesign). -->

There is no MCP-side tool *visibility* filtering. **All tools are always visible.** Tool discovery and context economy are handled by the client (Claude Code's `tool_search` / deferred-tool schemas), which is strictly better than the bespoke hiding layer this section used to describe. (Tool *gating* — blocking a call until canon/session preconditions are met — still exists, but lives at the hook layer and keys off the Safety tag; see "What remains" below.)

### What remains

**Tool tags.** `tool_tags.py` still tags each tool via `TOOL_TAGS` on three axes — Safety (`ALWAYS`/`GATED`), Phase, Domain — and every `@mcp.tool` decorator carries them via `_get_tool_tags(name)`. The **Safety axis is live and drives gating** in `gate_check.py` (see below); **Phase and Domain are metadata only** — no code branches on them, and they are retained as harmless documentation and as a hook for any future use.

**Canon enforcement — one path, at the hook layer, driven by the Safety tag.** The discipline "call `check_canon` before narrating or changing state" (Iron Law 1, *Tool Before Tale*) is enforced solely by the hook chain — `consolidated_stop_check.py` (Stop hook) and `gate_check.py` — described in §4. `gate_check.py` reads each tool's Safety tag and branches on it: a tool tagged `Safety.GATED` (`gate_check.py` ~line 97) is blocked until `check_canon` has been called *and* succeeded this turn (respecting `canon_required`), so state-changing tools cannot run ahead of canon; and any tool *not* tagged `Safety.ALWAYS` (~line 115) is blocked until `full_session_startup` completes, so nothing but the startup-safe tools runs before the session is initialized. Both branches respect maintenance mode via `skip_canon_enforcement`. The former MCP-side soft-warning copy (`ToolEnforcementMiddleware`) was removed as a redundant, stale duplicate.

**Maintenance toggle — `session_mode` (2026-06-21).** Maintenance mode (the canon-bypass + prose-coaching mute that the `/maintenance`, `/session-end`, `/dm-design`, and `/session-start` skills enter and leave) is toggled by the **`session_mode(action="maintenance_on"|"maintenance_off")`** MCP tool. `maintenance_on` sets `maintenance_mode`/`skip_canon_enforcement`/`skip_semantic_observer`; `maintenance_off` clears all three and resets the prose-catch counters (so it doubles as the session-start "return to clean gameplay" reset). It is tagged `{Safety.ALWAYS, Phase.SESSION, Domain.META}` — **`ALWAYS` and never `GATED` by design**: it IS the canon bypass, so gating it behind `check_canon` would deadlock, and `ALWAYS` also exempts it from the pre-`full_session_startup` block so `/maintenance` works before a session starts. This replaced the skills' former out-of-band `cd hooks && python3 -c "...poke .hook_state.json..."` shell blocks — moving the mechanic into the engine made the skills cross-platform (macOS/Linux/WSL/native Windows) with no filesystem path. Tests: `tests/test_session_mode.py`.

> **Note — overloaded term.** `vault_exploration` survives elsewhere as a **Scene Type** (a `CURRENT_STATUS.md` field that drives map auto-injection in check_canon, §9). That is a separate mechanism and was untouched by this tearout. It is not the deleted visibility cluster of the same name.

### History

The gating was built to reduce tool-list noise / token cost for the model. By the time of this review it cost more than it earned — it hid the spatial tools, ran the DM near-blind by default, carried two decorative tag dimensions, and was not wired into the play instructions. With a few dozen tools and a capable model plus client-side `tool_search`, the noise problem is already solved upstream, so the layer was removed rather than repaired.

---

## 12. Data Schema Reference

<!-- REVIEWED AND CORRECTED 2026-05-29 — Full re-verification against live files. Lorebook entry schema completed (rule_refs/species/pronouns added; short_context ~85% optional; real categories listed incl. world/factions/religions). Augmented keywords 46→53. catch_analytics keys corrected (_meta + catches added; 200KB + 30-day prune; noted it feeds the live phrase_reminder hook — not inert). Rulebook data files documented (new subsection). rule_refs WIRED into check_canon (RULES IN PLAY) and the lorebook's contaminated ancestry rule_refs cleaned across 31 entries. corrections.json RETIRED (write-only; logger neutralized + file deleted). -->
<!-- UPDATED 2026-06-07 — Verified against live data. rules.json 120→122 (added verified rule-damage-types + rule-weapon-tags; rule-damage/rule-creature-types re-sourced to Crimson Hound). Documented creature_resistances.json + exotica_generator.json as combat-engine-loaded (NOT rulebook_system). Added new Bestiary Data subsection: bestiary.json v3.0.2 (229 entries / 226 combat_active), stats.resistances schema {immune/minimum/double/half/varies/notes}, structured flags (mystic_gift_immune/ranged_immune/mimic/incorporeal/combat_note), schema gate. Counts verified live: rules 122, bestiary entries 229, combat_active 226. -->

### Lorebook Entry

`lorebook.json` is `{ "meta": {...}, "entries": [...] }`. A representative entry:

```json
{
  "keywords": ["amara", "amara vane"],
  "category": "people",
  "status": "ESTABLISHED",
  "context": "Full lore text about Amara Vane...",
  "short_context": "Matriarch. House Vane reformist.",
  "source": "session_day_31",
  "rule_refs": ["rule-ancestry-true-kin-inheritor"],
  "species": "true-kin",
  "pronouns": "she/her"
}
```

- `keywords`, `category`, `status`, `context`, `source` — present on all entries.
- `short_context` — optional (~85% of entries).
- `rule_refs` — list of rule IDs in `rulebook/rules.json` (~50% of entries — 327 of 664). **Consumed live** by check_canon's RULES IN PLAY injection (see §3 / below). Cleaned 2026-05-29 so each character's refs match only its own ancestry.
- `species`, `pronouns` — optional character fields (~55 / ~25 entries).

**Categories (as actually present):** exactly 9 canonical labels, normalized — `context`, `factions`, `knowledge_boundary`, `people`, `places`, `religions`, `scenes`, `things`, `world` (`world` largest). Normalization is complete: the previously-flagged duplicate/inconsistent labels (`location`/`locations`, `npcs`, `items`, etc.) have all been folded into these 9. Verified 2026-05-29 — no other category values exist in the data.

### Lorebook Gate Keywords

Implemented in `hooks/lorebook_gate.py`.

**Extraction:** Tokenize message with `[A-Za-z][A-Za-z0-9'-]{2,}` → intersect with lorebook keywords → return up to 5 (alphabetical; multi-word keywords matched by substring and appended after the sort).

**Filtering:**
- Minimum keyword length: 5 characters.
- Excluded: `ENGINE_EXCLUDE_KEYWORDS` (~72 common English/domain words: wife, mother, room, hall, tower, council, etc.) ∪ campaign `exclude_keywords` (see below) — applied when deriving keywords from the lorebook. **Party character names are excluded live**: `extract_triggers` subtracts the roster (via `hook_utils.load_party_names`, full names + name tokens ≥5 chars) per call, so the exclusion tracks the actual party in ANY campaign, never a hardcoded list (2026-07-13; owner literals are guarded absent from the hook source by `tests/test_stop_hook_party_roster.py`).
- `should_skip_message` bypasses the gate for admin input (`/`, `!`), parentheticals, messages under 20 chars, and hook-feedback echoes.

**Augmented keywords:** `ENGINE_AUGMENT_KEYWORDS` (book/generic always-trigger terms — species, factions, cosmology, book geography, chronology terms; `AUGMENT_KEYWORDS` remains as an alias) ∪ campaign `augment_keywords`, unioned into the keyword set regardless of presence in lorebook entries.

**Campaign-side gate words (2026-07-13):** `lorebook_gate_words.json` in the campaign dir — `{"exclude_keywords": [...], "augment_keywords": [...]}` — merges over the engine lists (excludes subtract from lorebook-derived triggers; augments are always-on). **Fail-open**: missing/malformed file ⇒ engine defaults alone. The keyword cache is keyed on BOTH mtimes (lorebook + gate-words). Campaign-personal words (owner geography like ceruline/kalaxis, table-specific tripwires like patagia/substrate) live in this file, not in engine code — same pattern as `fabrication_tripwires.json`.

### Engine-Bundled Rules-Data (`data/rules/`)

Static book data the engine reads at runtime lives in the engine's own `data/rules/` folder, read via `engine_core.read_rules_data(relpath)` — **engine-always-wins**: it resolves ONLY under `RULES_DATA_DIR` (the engine dir), never the campaign dir, so book data has exactly one home and the "two sources disagree" failure can't recur. Relocated out of the campaign dir 2026-06-17 (OSS prep — the engine ships self-contained; the campaign dir holds play-state only): `CACOGEN_MUTATIONS.json` (d100 mutations, read by `generators._roll_cacogen_mutation`), `NEOBLOOM_BLOOMBOONS.json` (d20 bloomboons, read by `character_tools`), `TRANSPORT_SPEEDS.json` (read by `geography_system`, with a code default fallback; **the one campaign-mergeable rules file** — a campaign-side `TRANSPORT_SPEEDS.json` merges over the engine base and the `campaign://data/transport` resource points at the campaign file when present, because campaign transport modes are play-state, 2026-07-12). `RULES_DATA_DIR` is resolved at call time, so tests redirect it via `monkeypatch.setattr(engine_core, "RULES_DATA_DIR", ...)`. The whole **`rulebook/` directory** (the 8 book JSONs — see below) also lives here, at `data/rules/rulebook/`. **`VAARN_GEOGRAPHY.json` deliberately stays in the campaign dir** — `geography_system` WRITES it during play (discovered locations/routes), so it is play-state, not book data.

### Rulebook Data

`data/rules/rulebook/` (engine-bundled rules-data — relocated from the campaign dir 2026-06-17, engine-always-wins) holds the Vaults of Vaarn rules as JSON: `rules.json`, `tables.json`, `bestiary.json`, `equipment.json`, `gifts.json`, `lore_additions.json` — read by `rulebook_system.py` at init (it resolves `rulebook_dir` from `RULES_DATA_DIR / "rulebook"`; tool documented in §8). Two more files live here but are loaded directly from `RULES_DATA_DIR / "rulebook"` by code outside `rulebook_system`: `creature_resistances.json` (the combat type matrix, via `server._load_creature_resistances`) and `exotica_generator.json` (via `generators`). All read-only. See Bestiary Data below.

`rules.json` is `{ "version", "source", "entries": [...] }` (count is machine-derivable: `len(entries)`). Each rule:

```json
{
  "id": "rule-ancestry-neobloom-flammable",
  "keywords": ["neobloom", "flammable", "fire"],
  "categories": ["ancestry"],
  "contexts": ["combat"],
  "rule": "Neobloom: Take DOUBLE damage from flames and heat-based attacks...",
  "source": "..."
}
```

Every rule entry has exactly these six keys: `id`, `keywords`, `categories`, `contexts`, `rule`, `source` (verified across all entries). The damage layer is verified Crimson Hound: `rule-damage`, `rule-creature-types`, `rule-damage-types` (6 Common Damage Types), `rule-weapon-tags` (full Advanced + Exotic tag list; full verbatim text in `docs/CRIMSON_HOUND_DAMAGE_RULES_VERIFIED.md`).

### Bestiary Data

`data/rules/rulebook/bestiary.json` is `{ "version", "source", "entries": [...] }` — v3.0.1+ is the VERIFIED Crimson Hound rebuild (229 entries, 226 `combat_active`). The regeneration tooling lives engine-side alongside the data at `data/rules/rulebook/`: `_rebuild_bestiary.py` rebuilds `bestiary.json` from the book-sourced `_ch_extract/` records (writes a `bestiary.rebuilt.json` candidate for human review — gitignored, never overwrites the live file). It resolves all paths relative to its own location, so it reads/rebuilds the engine's own bestiary. Not loaded at runtime. A representative combat entry:

```json
{
  "id": "creature-synth-skeleton",
  "keywords": ["synth skeleton"],
  "categories": ["bestiary"],
  "contexts": ["combat_active"],
  "stats": {
    "type": "Synthetic",
    "level": 1, "hp": 4, "av": 11, "morale": 1, "encountered": "d8",
    "attacks": [{"name": "Chrome Claws", "damage": "d6"}],
    "special": ["..."],
    "resistances": {"immune": ["fungal_spores","poison","radiation","suffocation"],
                    "minimum": ["piercing","slashing"], "double": ["electrical"],
                    "half": [], "varies": false, "notes": "..."},
    "mystic_gift_immune": false, "ranged_immune": false, "mimic": false,
    "incorporeal": false, "combat_note": "..."
  },
  "lore_refs": [], "source": "Crimson Hound printed p.206"
}
```

- `stats.type` — one or more of the 7 canonical types (title-case, `/`-joined). Drives the resistance matrix.
- `stats.resistances` — `{immune, minimum, double, half, varies, notes}`. Damage-type vocabulary is canonical (see `_normalize_damage_type`). `minimum` = listed types are reduced to exactly 1.
- Structured combat flags: `mystic_gift_immune` (Gifts fail vs it — psyche-suppressant pattern), `ranged_immune`, `mimic` (adopts target stat block), `incorporeal` (immune except hypergeometric/anti-paradoxical), `combat_note` (free-text tactical, surfaced on lookup).
- Schema gate (`tests/test_bestiary_schema.py`): every `combat_active` entry needs a valid canonical `type` + a `resistances` dict.

`rulebook/creature_resistances.json` is the 7-type fallback matrix `{ "<Type>": {"immune":[], "double":[], "half":[], "varies"?} }`, used ONLY when an entry's `resistances` is empty (see §7 Creature Resistances).

**Cross-links:** lorebook `rule_refs` → rule `id` (traversed live by RULES IN PLAY). No reverse link exists on the rule side: `lore_refs` and `tool_ref` were never authored into the data — they appear in zero rule entries and no code reads them.

**RULES IN PLAY injection:** On a *full* canon check (`active_blocks` non-empty), check_canon matches present characters to their `people` lorebook entries, resolves each entry's `rule_refs` against the rules index, and injects a condensed, capped (~6) "RULES IN PLAY" block. Idle/auto-light turns skip it. So a present character's mechanical rules (flammability, photosynthesis, synth repair, etc.) reach the DM automatically.

### Hook Analytics

`hooks/catch_analytics.json` is `{ "_meta", "catches", "phrase_stats", "semantic_catches" }`, accumulated by `hooks/analytics_utils.py`:

```json
{
  "_meta": {"last_pruned": "2026-05-27", "...": "..."},
  "catches": [
    {"phrase": "goes still", "session_date": "2026-05-27",
     "scene_type": "intimate", "catch_number": 3, "turn_count": 12}
  ],
  "phrase_stats": {
    "the weight of": {
      "total_catches": 20,
      "sessions_seen": 16,
      "clean_streak": 0,
      "scene_type_distribution": {"settlement": 5, "travel": 1, "social": 14},
      "tier": "banned",
      "first_caught": "2026-03-07",
      "last_caught": "2026-04-29"
    }
  },
  "semantic_catches": [
    {"quote": "her breath caught", "category": "Reaction Shot",
     "confidence": "high", "session_id": "session_2026_05_27",
     "turn_id": 12, "timestamp": "2026-05-27T15:30:00"}
  ]
}
```

**Pruning:** size cap at 200KB AND a 30-day age-prune of the `catches` list. **Not inert:** this file feeds the live `phrase_reminder` UserPromptSubmit hook, which injects a "PHRASE DISCIPLINE" reminder (overused phrases for the scene type) before each turn.

### Corrections Log

**Retired 2026-05-29.** `corrections.json` was a write-only log — its only reader (`blacklist_evolver`) is never run at session-end and the player never saw it. The `correction_logger` functions are now no-ops and the file is deleted; callers in the Stop hook / turn-reset are unaffected.

---

## 13. Operational Summary

### What Actually Blocks Delivery

Enforcement lives in two places: the **`gate_check` PreToolUse hook** (the only mechanism that hard-blocks tool calls) and **`validate_prose`** (the pre-output prose gate the DM must call before narrating). The `consolidated_stop_check` Stop hook is soft-moded with ONE exception: its `main()` collects each check's state updates, and every check except the dm-design review gate (§4 Check 1b) has its block signal ignored — telemetry only, feeding session-end review and the `phrase_reminder` hook. The dm-design gate alone hard-blocks: an armed `pending_dm_design` with no dispatched review prints the reason to stderr and exits 2 (the blocking tail of `main()` in `consolidated_stop_check.py`).

| Mechanism | Blocks? | Notes |
|-----------|---------|-------|
| gate_check: GATED tools pre-canon | Yes | Hard block until check_canon is called AND succeeds (respects `canon_required`; read-path tools pass on stable scenes) |
| gate_check: pre-session tools | Yes | Hard block on any non-ALWAYS tool until full_session_startup completes |
| gate_check: validate_prose skipped | Yes | Hard block on the next tool if validate_prose was skipped on the prior narrative turn |
| validate_prose (MCP tool) | Yes | The real prose gate — rejects blacklisted phrasing before output; gate_check enforces it was called |
| consolidated_stop_check: ALL checks (canon, blacklist, lorebook gap, NPC / dialogue / backstory fabrication, prep-file progress) | No | Soft log only — `main()` discards block signals (blocking caused visible rewrite artifacts). Feeds session-end + phrase_reminder. |
| prose_observer (semantic observer) | Never | Async, fail-open, diagnostic only |

> Retired in §11: the `DANGEROUS` safety tier no longer exists. `gate_check` evaluates only `ALWAYS` and `GATED`.

### Token Budget Strategy

| Turn Type | Approx. Tokens Injected | Source |
|-----------|------------------------|--------|
| Auto-light (default) | ~500 | check_canon: lorebook matches + distillation cache + ChromaDB tier 1 |
| Full (scene change, etc.) | ~2000-4000 | check_canon: everything — voice, relationships, prep, characters, threads, progressive ChromaDB |
| No change (dedup hit) | ~20 | "[NO CHANGE]" response |
| Admin command | ~50 | Location + day only |

### Performance Optimizations

| Optimization | Mechanism | Saving |
|-------------|-----------|--------|
| Ollama warmup | Startup call prevents 4-minute first-request delay | ~4 min on first search |
| JSON file cache | Mtime-based invalidation, no size limit (unbounded growth — one entry per unique cache key) | Avoids re-parsing unchanged files |
| Embedding cache | 512-entry LRU prevents redundant Ollama calls | ~100-200ms per cache hit |
| Regex pre-compilation | `_COMPILED_PATTERNS` holds 10 pattern groups compiled once at init. 8 of them (vault, npc_actions, combat, rest, day, creature, loot, travel) drive check_canon's tool recommendations; the other two (intimate, lore_questions) drive context-block escalation rather than tool hints | Avoids per-turn recompilation |
| Response caching middleware | FastMCP ResponseCachingMiddleware, 300s (5-minute) TTL for static lookups | Saves redundant MCP round-trips |
| ChromaDB cosine similarity | HNSW approximate search | Faster than exhaustive L2 |
| Tiered chunking | Semantic boundaries with parent-child linking | Better retrieval precision |
| check_canon dedup | Hash comparison with previous output | Skips redundant context injection |
| Distillation-first search | ChromaDB distillations queried before raw history | Shorter, more relevant results |
| Selective VOICE.md loading | Only present character sections loaded | Avoids injecting 6+ unused voice guides |

### External Dependencies

| Dependency | Version | Purpose |
|-----------|---------|---------|
| FastMCP | 3.0.0b1 | MCP server framework |
| MCP SDK | 1.25.0 | Underlying protocol (wrapped by FastMCP) |
| Ollama | local | Embedding generation (nomic-embed-text) |
| ChromaDB | persistent | Vector search for campaign history |
| Anthropic SDK | — | prose_observer calls Haiku 4.5 |
| pdfplumber | — | PDF reading (rulebook source) |
| Pydantic | — | Parameter validation |

### Key Files by Importance

*(Line counts deliberately omitted — they rot on every edit. Navigate by symbol via the LSP, per CLAUDE.md's LSP-first pillar.)*

| Rank | File | Why |
|------|------|-----|
| 1 | server.py (~17.2K lines) | Post-decomposition core — `@mcp.tool` dispatchers + check_canon, combat, and the death/save/game-state seams (which stay here by design), plus the tool dispatchers that alias back each extracted domain module. The 2026-06-16 audit's locked decomposition map is COMPLETE (2026-06-17): slices 1–4 + 6 shipped (generators, substances, cyber_gifts, bestiary_encounter, character_tools); slice 5 (location_tools) was a verified tombstone. |
| 2 | engine_core.py | Shared substrate extracted from server.py (Wave 0): CAMPAIGN_DIR, file/JSON I/O, dice, GAME_STATE, character I/O, and the death-seam orchestrators. server.py imports-and-re-aliases these; engine_core never imports server (circular-wall verified). |
| 3 | session_tools.py | The 8-tool save/persistence chain (Wave 8): `save_state`/`prepare_save_state`/`confirm_save`/`load_last_session`/`full_session_startup`/`verify_session_save`/`distill_session`/`ingest_distillations`. Registered via `register_session_tools(mcp, srv)` with server deps injected at startup (dodges the circular import). |
| 4 | generators.py | Decomposition slice 1 — the d100/table-driven content generators behind the `generate`/`lookup` tools (exotica, weapons, armour, NPCs, factions, gifts, poisons, codices, drugs, elixirs, crucibles). server.py imports-and-aliases the moved names back; shared tables (`VAARNISH_POISONS/ELIXIRS`, `MELEE/RANGED_WEAPONS`, `_stamp_slots_uses`) stay in server.py and are injected by reference via `register_generators(srv)`. |
| 5 | substances.py | Decomposition slice 2 — the toxin/poison/usage(ammo)/item-consumable helper web behind the `usage`/`affliction`/`supply` tools. The tool dispatchers stay in server.py and alias the moved names back. Cross-module deps (character persistence + the death/wound seam) are reached via call-time delegating shims to `server.<name>` so test monkeypatches stay live; `VAARNISH_POISONS` injected via `register_substances(srv)`. |
| 6 | cyber_gifts.py | Decomposition slice 3 — the cybernetic install/remove/list + gift add/remove/cost/gleam helpers behind the `cybernetic`/`gift` tools. Dispatchers stay in server.py and alias the moved names back. Character-persistence/slot deps reached via the same call-time delegating shims (bound by `register_cyber_gifts(srv)`); gift data lives in `gifts.py` (imported). No fault lines — needed zero test changes. |
| 7 | bestiary_encounter.py | Decomposition slice 4 — bestiary lookups + the encounter-table roll + reaction roll/modifier helpers. The `lookup`/`test_dice` tools and the content_forge registration stay in server.py and alias the moved names back (alias-back precedes the registration that passes `_roll_encounter_table`/`_roll_reaction`/`_roll_reaction_for_character` by reference). Persistence/faction deps via delegating shims; `rulebook_system` (the instance whose `_cache` tests mutate) injected by reference via `register_bestiary_encounter(srv)`; `dice` imported (tests attribute-patch the shared singleton). Fault line: `_faction_rep` dual-patched in test_reaction.py. |
| 8 | character_tools.py | Decomposition slice 6 (final, largest — ~3.1K lines) — the CHARACTER cluster: CRUD/leveling, elixirs, companions (followers/mercenaries/pets/steeds/vehicles), resurrection, wounds, vehicle damage (52 funcs + 5 consts). The `character`/`wound` tool dispatchers stay in server.py and alias the moved names back. 23 cross-module deps (persistence + death/wound seam + substances/generators aliases) via call-time delegating shims bound by `register_character_tools(srv)`; `map_system` (rebind-patched by tests) reached via a `_LiveServerProxy`; `VAARNISH_ELIXIRS`/`BIOLOGICAL_WOUNDS`/`SYNTHETIC_WOUNDS` injected by reference. `_roll_cacogen_mutation` + 4 generic leaves kept in server (delegated). Zero test changes needed. |
| 9 | gate_check.py | Tool-level access control — the only hard gate (GATED pre-canon, pre-session, validate_prose enforcement) |
| 10 | CURRENT_STATUS.md | Canonical session checkpoint, read every turn |
| 11 | lorebook.json (9 canonical categories) | Complete lore database, keyword-triggered injection |
| 12 | consolidated_stop_check.py | Post-response SOFT logging (telemetry/analytics + observer spawn) — blocks only via the dm-design review gate (§4 Check 1b); all other checks feed session-end + phrase_reminder |
| 13 | turn_reset.py | Per-turn state management, scene fingerprinting; preserves the Stop-armed enforcement flags (`validate_prose_required`, `vault_action_required`, `open_npc_scene`) across turns |
| 14 | hook_utils.py | Shared hook state, file locking, fail-closed wrapper, and `in_maintenance(state)` — the unified maintenance-mode switch honoring both `maintenance_mode` and the legacy `skip_canon_enforcement` |
| 15 | CLAUDE.md | DM protocol, auto-triggers, trust order |
| 16 | blacklist.json | Prose blacklist; counts are whatever the file holds (the evolver grows it at session-end). Tiers: blacklisted, use-sparingly, protected, structural |
| 17 | tool_tags.py | Cosmetic tool metadata + Safety tags (ALWAYS/GATED) consumed by gate_check |

<!-- Blocking model (corrected 2026-07-05): consolidated_stop_check is soft for every check EXCEPT the dm-design review gate, whose block signal exits 2; all other block signals are ignored. Hard enforcement is in gate_check (PreToolUse: GATED pre-canon / pre-session / validate_prose-skipped) + the validate_prose tool. Regression guard for the retired DANGEROUS tier (a fail-closed gate_check would have bricked every tool call): tests/test_gating_removed.py. -->
