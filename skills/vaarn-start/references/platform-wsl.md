# Platform: Windows + WSL

The owner's rig class. Claude Code runs inside WSL (Linux), but the engine runs as a
**Windows** process — because the live ChromaDB store must be opened by the Windows venv
(NTFS + the chromadb 1.3.7 pin). This split is why WSLENV matters.

## Detect
- `/proc/version` (or `uname -r`) contains "microsoft" → WSL.

## Venv layout
- The engine venv is the **Windows** venv: `{{ENGINE_DIR_WIN}}\.venv\Scripts\python.exe`.
- From WSL you invoke it via the `/mnt/c/...` path, e.g.
  `/mnt/c/path/to/rubicon-seven-mcp/.venv/Scripts/python.exe`.
- Create it with the Windows Python, not WSL python3:
  `python.exe -m venv .venv` (run from the engine dir in a Windows shell or via `cmd.exe /c`).

## Dependencies
1. `{{ENGINE_DIR_WIN}}\.venv\Scripts\python.exe -m pip install -r requirements.txt`
   (FastMCP/mcp, **chromadb==1.3.7** — the pin is load-bearing, filelock, anthropic, numpy, requests).
   Run this with the WINDOWS venv python — never WSL system python3 (it ships chromadb 1.5.x
   and corrupts the 1.3.x store).
2. **Ollama** (separate local service, powers search; not pip-installable):
   - Install the **Windows** Ollama (the engine is a Windows process and reaches Ollama on
     `localhost:11434`). Download from ollama.com.
   - `ollama pull nomic-embed-text` (the embedding model the engine uses).
   - If the player skips Ollama now, that's fine: search stays dark until installed; the engine
     boots gracefully without it.

## mcp.json
Use `assets/mcp.json.windows-wsl.template`. Paths are Windows form (`C:\...`, double
backslashes in JSON). **WSLENV is MANDATORY:**
`"WSLENV": "RUBICON_CAMPAIGN_DIR:PYTHONUNBUFFERED"`. Without it the campaign-dir variable
silently does NOT cross WSL→Windows and the engine binds to the wrong folder (the default
sibling of the engine dir), so the player's brand-new campaign appears empty.

## settings.json hooks
Replace `{{HOOK_PY}}` with `python3`. Hook commands are then `python3 {{ENGINE_DIR}}/hooks/...` where `{{ENGINE_DIR}}` is the POSIX
`/mnt/c/...` path (the hooks run inside WSL, under WSL python3 — that's correct; hooks don't
touch the ChromaDB store). Only the MCP server itself runs as the Windows process.
