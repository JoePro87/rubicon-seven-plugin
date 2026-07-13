# Rubicon Seven MCP Server

A comprehensive Model Context Protocol (MCP) server for running solo tabletop RPG campaigns using Claude Code. Built for *Vaults of Vaarn* but adaptable to other systems.

## Overview

This MCP server provides ~50 consolidated tools (hundreds of actions) for managing a narrative-focused TTRPG campaign through Claude Code. It handles character stats, combat tracking, spatial mapping, journey calculations, NPC relationship dynamics, narrative continuity, and campaign history search using vector embeddings.

**Key Features:**

- **Character Management:** Full stat tracking, HP/damage, leveling, XP, cybernetics, mystic gifts, codex management
- **Combat System:** Initiative tracking, enemy HP, morale checks, wounds, damage typing (kinetic/beam/blast/flame/electrical/TOX)
- **Spatial Systems:** Vault/dungeon mapping with ASCII visualization, overworld geography with travel time calculations
- **Narrative Tools:** Lorebook (canon tracking), relationship tracking, plot thread management, NPC state tracking, emotional continuity
- **Search & History:** Tiered vector search across your accumulated sessions using ChromaDB and Ollama embeddings
- **Session Management:** State saves with diff previews, narrative beat logging, photosynthesis timers, constraint enforcement
- **Generation Tools:** Random encounters, NPCs, weapons, exotica, roll tables integrated with rulebook data
- **Hook System:** Pre/post-flight validation for narrative quality, anti-pattern detection, canon enforcement

## Requirements

- **Python 3.10+**
- **Claude Code CLI** (latest version)
- **Ollama** (for local embeddings with nomic-embed-text model)
- **Vaults of Vaarn 2e rulebook** (PDF) — *optional.* The engine ships the mechanical
  data it needs (bestiary, equipment, tables — CC BY 4.0, credit Leo Hunt); the book
  itself is a great read and the best way to understand the setting, but play works
  without it. Not included.

## Installation

### Recommended: install as a Claude Code plugin

This is the turnkey path — no manual venv, no `.mcp.json` editing, no bash (works on
macOS, Linux, WSL, and **native Windows**).

> **Use Claude Code in your terminal, not the Claude Desktop app.** The Desktop app's
> handling of slash commands interferes with the `/plugin` commands below. Install
> Claude Code and run it from a real terminal (PowerShell/cmd on Windows, or your
> shell on macOS/Linux).

**1. Make a folder for your campaign and launch Claude Code inside it.** Your save
data lives in whatever directory you start Claude Code from. For a brand-new
campaign, start in an empty folder:

```bash
mkdir my-vaarn-campaign && cd my-vaarn-campaign
claude
```

**2. Add the marketplace and install the plugin** (run these inside Claude Code):

```
/plugin marketplace add JoePro87/rubicon-seven-plugin
/plugin install rubicon-seven@rubicon-seven
```

This makes the `/vaarn-start` onboarding skill (and the engine hooks) available.

**3. Run the onboarding skill — it sets up everything and starts your game:**

```
/vaarn-start
```

`/vaarn-start` detects your platform, builds the engine's Python environment
(one-time, ~a minute), wires this campaign's `.mcp.json`, rolls your character, and
opens the first scene. There is no separate "build" step and no bash involved — it
runs the same way on every OS.

**Required — local embeddings (Ollama).** The dungeon master's campaign memory and
history search run on local embeddings, so set up **Ollama** *before* you play — the
engine relies on it to recall your story reliably:

```bash
ollama pull nomic-embed-text   # one-time, ~275 MB
```

Keep the Ollama app running during play. (Full details: [Set Up Ollama](#5-set-up-ollama-for-campaign-history-search) below.) Everything else is handled by the plugin.

### Updating

```
/plugin marketplace update rubicon-seven
/reload-plugins
```

Then **re-run `/vaarn-start` once** — it is safe to re-run and its dependency step
re-syncs your engine environment (updates sometimes add new Python packages; e.g.
`rank_bm25` in v0.6.0, `textual` for the companion dashboard in v0.8.0). If you
skip this and something new complains about a missing package, the fix is the
same: re-run `/vaarn-start`, or `pip install -r requirements.txt` into the
engine's venv.

---

### Manual install (from source)

Use this if you're developing the engine or want full control over the Python
environment and MCP wiring.

#### 1. Clone the Repository

```bash
git clone https://github.com/JoePro87/rubicon-seven-plugin.git
cd rubicon-seven-plugin
```

#### 2. Set Up Python Virtual Environment

**On Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**On WSL/Linux/macOS:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Use `requirements.txt`, not a hand-picked package list — the ChromaDB version is
> **pinned on purpose** (the on-disk search-store format changed after 1.3.x, and a
> newer ChromaDB can silently migrate or corrupt an existing store).

#### 3. Create Campaign Data Directory

The MCP server expects campaign data in a **separate directory** from the code:

```bash
# On Windows (place it wherever you like; a sibling of the engine repo is the default)
mkdir C:\path\to\rubicon-seven-campaign

# On WSL
mkdir /mnt/c/path/to/rubicon-seven-campaign
```

**Core campaign directory structure** (the engine creates files as play needs them;
`/vaarn-start` scaffolds all of this for you, and works for manual installs too):
```
rubicon-seven-campaign/
├── CURRENT_STATUS.md          # Active scene state
├── game_state.json            # Party location, active prep, combat state
├── characters/                # One sheet per PC + _meta.json (campaign day, supply)
├── npc_states.json            # NPC disposition and knowledge
├── RELATIONSHIP_MATRIX.json   # Relationship tracking
├── narrative_threads.json     # Plot thread management (with world-force clocks)
├── lorebook.json              # Canon facts database
├── party.json                 # Party wealth ledger
├── site_features.json         # Persistent features of unmapped places
├── MASTER_CONTINUITY_CURRENT.md  # Session history
├── prep/                      # Location prep files
└── maps/                      # Vault/site map state
```

#### 4. Configure MCP Server

Copy the example configuration:

```bash
cp .mcp.json.example .mcp.json
```

Edit `.mcp.json` with your paths:

```json
{
  "mcpServers": {
    "rubicon-seven": {
      "command": "C:\\path\\to\\rubicon-seven\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\rubicon-seven\\server.py"],
      "env": {
        "RUBICON_CAMPAIGN_DIR": "C:\\path\\to\\your-campaign"
      }
    }
  }
}
```

**Note:** `command` must point at your venv's interpreter for your platform — `...\.venv\Scripts\python.exe` on Windows (use `\\` separators in JSON), `.../.venv/bin/python` on macOS/Linux. On WSL the engine runs under Windows Python, so use the Windows paths there too.

#### 5. Set Up Ollama (for Campaign History Search)

Install Ollama from https://ollama.ai, then pull the embedding model:

```bash
ollama pull nomic-embed-text
ollama serve  # Keep this running for search functionality
```

#### 6. Copy Hook State Template

```bash
cp hooks/.hook_state.json.example hooks/.hook_state.json
```

Edit `hooks/.hook_state.json` to enable/disable narrative enforcement hooks.

#### 7. Test Installation

```bash
# Test imports (with the venv activated, per step 2)
python -c "import server; print('OK')"

# Run test suite
python -m pytest tests/ -v
```

**Expected output:** All imports succeed, tests pass

## Usage

### Starting a Session

In Claude Code, use the `/session-start` skill or call `full_session_startup()` tool manually:

```
/session-start
```

This initializes the campaign state and loads recent history context.

### Running the Campaign

The DM persona is the `rubicon-seven-dm` **output style**, installed and activated by
`/vaarn-start` — there is no separate skill to invoke; once set up, you just play.
The DM calls the engine's tools itself as the story needs them:

- `check_canon(user_input="...")` - Get current narrative context (called every turn)
- `character(action="get", name="Astra")` - View character stats
- `combat(action="init", enemies=["Gene Thief", "Raider"])` - Start combat
- `map(action="render", map_name="ruined_vault")` - Display vault map
- `search(action="tiered", query="...", tier=1)` - Search campaign history

### Ending a Session

```
/session-end
```

This saves all campaign state, narrative beats, and indexes the session for future search.

### Indexing Campaign History

Indexing is automatic: session saves index new material, and day-to-day reindexing
runs through the `reindex_recent` MCP tool. There is no manual indexing step.

## Project Structure

```
rubicon-seven/
├── server.py                    # Main MCP server (large monolith; ~38 domain modules extracted alongside)
├── dice_roller.py               # Dice mechanics (d20, saves, damage)
├── map_system.py                # Vault mapping and ASCII rendering
├── geography_system.py          # Overworld travel and location tracking
├── npc_tables.py                # NPC generation (ancestry, careers, secrets)
├── combat_descriptors.py        # Enemy identifier pool for combat
├── tool_tags.py                 # Tool visibility tagging system
├── data/rules/                  # Shipped rules data (bestiary, equipment, tables — CC BY 4.0)
├── skills/                      # Claude Code skills (/vaarn-start, /session-start, /menu, ...)
├── hooks/                       # Game-rule + narrative-quality hooks (registered from the campaign dir)
│   ├── turn_reset.py            # UserPromptSubmit: canon flags, scene fingerprint
│   ├── gate_check.py            # PreToolUse: blocks tools until check_canon succeeds
│   ├── consolidated_stop_check.py  # Stop: canon / anti-pattern / prep / observer
│   └── ...
├── dashboard/                   # Companion terminal dashboard (vaarn-dash)
├── tests/                       # Test suite
├── docs/                        # Extended documentation
│   └── TECHNICAL_DESIGN_DOCUMENT.md  # Complete system documentation (live spec)
└── scripts/                     # Utility scripts
```

## Documentation

**For players:**
- **[WHAT_IS_VAARN.md](docs/WHAT_IS_VAARN.md)** - The setting, in one page
- **[PREP_FILE_SCHEMA.md](docs/PREP_FILE_SCHEMA.md)** - The location prep-file format

**For maintainers & contributors:**
- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Engine development: LSP-first navigation, the decomposition recipe, testing, gotchas
- **[TECHNICAL_DESIGN_DOCUMENT.md](docs/TECHNICAL_DESIGN_DOCUMENT.md)** - The live architecture spec (read this for development)

## Key Concepts

### Canon Tracking (Lorebook)

The lorebook is the source of truth for established facts. `check_canon()` must be called every turn to prevent continuity errors.

```python
check_canon(user_input="What does my character look like?")
```

Returns character descriptions, relationships, emotional states, active constraints, and relevant lorebook entries.

### Tiered Search

Campaign history uses 4-tier progressive search for cost efficiency:

- **Tier 1** (~150-char chunks): Quick existence checks
- **Tier 2** (~300-char chunks): Dialogue snippets
- **Tier 3** (~800-char chunks): Scene segments
- **Tier 4** (~3000-char chunks): Full context recovery

Start small, escalate only if the snippets are too thin.

### Hook System

Hooks enforce game rules and prime narrative quality:
- `gate_check` (PreToolUse) - Blocks engine tools until `check_canon` succeeds in the turn
- `turn_reset` (UserPromptSubmit) - Resets canon flags, computes the scene fingerprint
- `consolidated_stop_check` (Stop) - Canon, anti-pattern, prep-file, and prose-observer checks

State persists in `hooks/.hook_state.json` (gitignored; seeded from `.hook_state.json.example`).

### Prep File Workflow

Location prep files use a **read-modify-write** pattern:
1. DM reads prep file directly (Read tool)
2. DM updates PROGRESS LOG section (Edit tool)
3. Hooks verify prep file was consulted

This replaces older state-machine patterns.

## Development

### Testing

```bash
# Run all tests (venv activated)
python -m pytest tests/ -v

# Test specific tool
python -m pytest tests/test_character.py -v
```

### Adding Tools

Tools are defined in `server.py`. Follow existing patterns:

1. Add tool decorator with name and description
2. Implement handler function
3. Update `tool_tags.py` if tool should be context-filtered
4. Add tests to `tests/`
5. Update `docs/TECHNICAL_DESIGN_DOCUMENT.md` if significant

### Editing server.py

The file has Unicode encoding issues. If the Edit tool fails, use Python scripts for line-by-line edits.

## License

Two licenses, two kinds of material (see [`NOTICE`](NOTICE) for the full statement):

- **Engine code** — MIT (see [`LICENSE`](LICENSE)).
- **Vaults of Vaarn setting/rules data** (`data/rules/`) — derived from *Vaults of
  Vaarn* by **Leo Hunt**, used under **CC BY 4.0**. Attribution to Leo Hunt is the
  only requirement. This is an unofficial fan tool; the rulebook PDF is not included.

## Acknowledgments

- Built for **Vaults of Vaarn** by Leo Hunt (setting content © Leo Hunt, used under CC BY 4.0 — see NOTICE)
- Uses **Claude Code** by Anthropic
- Embeddings via **Ollama** (nomic-embed-text)
- Vector search via **ChromaDB**

## Contact

For questions or collaboration, open an issue on GitHub.
