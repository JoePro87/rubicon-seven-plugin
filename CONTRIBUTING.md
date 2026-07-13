# Contributing to Rubicon Seven

Rubicon Seven is a custom MCP (Model Context Protocol) server that turns an LLM into the
autonomous Dungeon Master for a solo tabletop campaign (the rules target *Vaults of Vaarn*).
The engine is the DM's prosthetic: persistent memory, rules enforcement, world simulation, and
honesty checks. This guide is for people working on the **engine code**.

## Roles, so the design makes sense

The model **is the DM**; the human is the **player**. Almost every surface the engine produces —
world-state files, antagonist boards, session-start briefings, the canon gate, the RAG search —
is consumed **by the DM-model**, not shown to the player. The player only ever reads the prose the
DM writes. Keep that in mind when naming or documenting a feature: an engine surface is the
DM-model reading its own notes, not a player-facing dashboard.

**Design line:** deterministic mechanics (rules-data, persistent state, dice, clocks) belong in the
**engine/tools**; situational judgment (tone, pacing, when to bend a rule) belongs to the **DM
model**. Expose a lever; don't hardcode the policy. Skills/onboarding stay *thin* — they orchestrate
and relay engine output, they don't re-encode a mechanic the engine already owns (two sources of
truth drift).

## Repo layout

| Path | Purpose |
|------|---------|
| `server.py` | The main MCP server. A large monolith (~16k lines); most tools are defined here. ~38 domain modules have been extracted alongside it. |
| `engine_core.py`, `character_tools.py`, `session_tools.py`, `generators.py`, `substances.py`, `bestiary_encounter.py`, `cyber_gifts.py`, … | Extracted domain modules. |
| `dice_roller.py`, `map_system.py`, `geography_system.py`, `npc_tables.py`, `ancestries.py`, `followers.py` | Supporting systems and rules-data. |
| `rubicon_paths.py` | Stdlib-only path resolution (engine dir, campaign dir, derived paths). Imported by hooks too, so it must stay dependency-free. |
| `hooks/` | UserPromptSubmit / PreToolUse / PostToolUse / Stop hooks that enforce game rules and prime narrative quality. Registered from the **campaign** repo's `.claude/settings.json`. |
| `data/rules/` | Book-derived rules data (the engine is self-contained for all rulebook data). |
| `tests/` | The pytest suite. |
| `docs/TECHNICAL_DESIGN_DOCUMENT.md` | The live architecture spec — **read this first.** |
| `docs/DEVELOPMENT.md` | The build loop, Definition of Done, branching, versioning. |
| `docs/SYSTEMS_ROADMAP.md` | The single source of truth for what to build. |

A running campaign lives in a **separate** directory (default: a sibling folder named
`rubicon-seven-campaign`, or `$RUBICON_CAMPAIGN_DIR`). The engine repo holds **no** play-state;
a player creates their campaign folder by running the `/vaarn-start` onboarding skill.

## Python environment

Use a virtual environment — **not** system Python.

> On Windows/WSL, system Python on an NTFS mount can corrupt SQLite (ChromaDB). Always use the
> repo venv interpreter.

```bash
# create + activate (POSIX)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Windows venv interpreter is at .venv/Scripts/python.exe (no bin/).
```

### Test imports after editing the monolith
```bash
python -c "import server; print('OK')"
```

### Run the suite
```bash
python -m pytest tests/ -v
```

## Navigating the monolith — LSP-first

`server.py` is large, and written-down line numbers rot the moment code moves. **Navigate and edit
by *symbol*, using a language-server (LSP), not by scrolling or trusting line numbers in docs.**

- Find a definition: workspace/document symbol search.
- **Before editing any shared function, find its references first** — see the whole blast radius
  before you change it. This is the single most important habit in this codebase; the monolith
  breeds seam bugs.
- Trace flow with incoming/outgoing calls; resolve types with go-to-definition / hover.
- The LSP reads the *live* tree, so it beats any written-down line number — but it is **not
  infallible**: reference search can miss calls made through a module alias
  (`import x as _x; _x.fn()`) or dynamic dispatch. If a result looks suspiciously empty,
  cross-check with `grep`.

## Decomposition: extracting from `server.py`

When moving code out of the monolith into a domain module, the proven recipe:

1. **Verbatim AST move** — move the function bodies unchanged; don't refactor in the same step.
2. **Alias every moved name back** into `server.py` (functions **and** constants), so existing
   callers keep working.
3. For data tables that *staying* code reads, keep them in `server.py` and inject by reference via
   a `register_*()` call.
4. For cross-module dependencies the moved code calls that tests monkeypatch, use a **call-time
   delegating shim** (`def dep(*a, **k): return getattr(_server, "dep")(*a, **k)`) so patching stays
   transparent and tests don't churn.
5. **Never `import server` inside a new module.** The MCP launches via `python server.py`, so
   `server` runs as `__main__`; a second `import server` re-executes it as a distinct module and
   hits the alias-back mid-init (circular import). Instead bind the live module through
   `register_*(srv)` and read it via `_server`.
6. **Boot-verify by actually running `python server.py`** (the `__main__` path) — not just
   `import server`. Only the run catches the re-entry class of bug; pytest imports as `server` and
   won't see it.

## Tests

- The canonical suite is `tests/` (pytest). Keep it green.
- Combat, death, and save/load are the highest-risk seams: changes there warrant the full suite
  plus a boot-verify, and an extra review pass.
- Tests resolve data paths repo-relatively (via `conftest.py`) — never hardcode an absolute machine
  path.

## Known gotchas

- `server.py` has some Unicode-encoding corruption in places; if an exact-string edit fails, fall
  back to a programmatic line edit.
- ChromaDB lives under the campaign dir and is rebuilt from session data; don't commit it.
- Per-campaign runtime state (canon caches, analytics, fabrication bans, hook state) is
  campaign-scoped and gitignored — it must never be tracked in the engine repo.

## Build loop & Definition of Done

See `docs/DEVELOPMENT.md` for the full loop (brainstorm → spec → plan → build → review → finish),
the Definition of Done, branching, and versioning. In short: work on a branch; keep the suite
green; update `docs/TECHNICAL_DESIGN_DOCUMENT.md` after a significant change; and design so that a
fresh model can find the right tool — prefer having the engine **push the next tool-call** in its
output over relying on the model to pull it from a long tool list.
