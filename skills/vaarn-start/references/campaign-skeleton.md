# Blank Day-1 campaign skeleton — rationale

This doc explains **what each scaffolded file is FOR and why it's load-bearing**. It does NOT
hold the file contents — those live in exactly one place, **`scripts/scaffold_campaign.py`**
(the single source, shared with `scripts/reset_to_base.py` so they can't drift). Step 2.4 runs
that script; do not hand-write these files or copy contents in here.

> Why a script, not skill-prose: the blank structure is deterministic, and it used to be written
> in three places (this doc, the skill step, and the reset tool) — they drifted. One source now.

## What gets created (folders)
`prep/`, `characters/`, `maps/`, `vehicles/`, `chroma-db/` (the vector store — the engine creates
`chroma.sqlite3` on first run), `.claude/output-styles/` (holds the Step-1 output style).

## What gets created (files) — and why each matters
- **`CURRENT_STATUS.md`** — Day 1, location/present unset. The `**Last 3 Beats:**` line is REQUIRED
  (startup validation looks for it); `check_canon` reads the SCENE STATE section. Step 5's save
  pipeline (`prepare_save_state`/`confirm_save`) fills in the opening scene — don't hand-edit it.
- **`MASTER_CONTINUITY_CURRENT.md`** — empty session log; the session-end pipeline appends to it.
- **`ANTAGONIST_CULTIVATION.md`** — the antagonist board the engine clocks/surfaces. Starts empty;
  Step 4 seeds 1-2 tutorial threats via the `antagonist` tool (never hand-author seeds in the file).
- **`characters/_meta.json`** — the PC registry the engine reads before it will touch ANY split
  sheet. **Required before Step 3** or `character(create_finalize)` / `character(register)` fail with
  `split sheets not found`. `campaign_day` is set to 1 so Step-3 creation rolls stamp Day 1 and aren't
  rejected as "stale". (The scaffolder stamps today's date as `last_updated`.)
- **`lorebook.json`** — the canon store, written as `{"entries": []}`. Without it `check_canon`
  early-returns `"lorebook.json not found"`, which is treated as a canon failure and CASCADES into the
  save's canon write + `reindex_recent` on the first `/session-end`. Empty → `check_canon` proceeds.
- **`NPC_ROSTER.md`** — empty roster; absent, the save just warns "NPC_ROSTER.md - Not found", so an
  empty one gives `npc_changes` somewhere to land.
- **`.gitignore`** — privacy guard. The load-bearing line is `.claude/memories.json` (Claude's
  per-folder personal-memory store — can hold personal context + the player's account id; never
  publish it). We do NOT create that memory file; Claude makes its own clean copy under the player's
  account if/when the feature applies. The rest keeps derived data (vector DB, caches) out of commits.

## Written by OTHER steps (not the scaffolder)
- `.mcp.json` — Step 2.3 (platform mcp.json template) · `.claude/settings.json` — Step 2.3
- `CLAUDE.md` — Step 1 template · `.claude/output-styles/rubicon-seven-dm.md` — Step 1 template
- `characters/<pc>.json` — Step 3, written by the engine's `character` tool.
