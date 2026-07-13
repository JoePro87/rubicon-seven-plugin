# Platform: Linux (native, not WSL)

POSIX and native. Same shape as macOS; only the Ollama install command differs.

## Detect
- `uname` == "Linux" AND `/proc/version` does NOT contain "microsoft" (that would be WSL).

## Venv layout
- `{{ENGINE_DIR}}/.venv/bin/python` (POSIX `bin/`, NOT `Scripts/python.exe`).
- Create: from the engine dir, `python3 -m venv .venv`.

## Dependencies
1. `{{ENGINE_DIR}}/.venv/bin/python -m pip install -r requirements.txt`
   (mcp/FastMCP, **chromadb==1.3.7** — keep the pin, filelock, anthropic, numpy, requests).
2. **Ollama** (separate local service for search):
   - Install: `curl -fsSL https://ollama.com/install.sh | sh` (or your distro's package), then
     ensure the service is running (`ollama serve` or the systemd unit). Runs on `localhost:11434`.
   - `ollama pull nomic-embed-text`.
   - Optional — if skipped, search stays dark until installed; the engine boots without it.

## mcp.json
Use `assets/mcp.json.posix.template`. POSIX paths; venv command is `.venv/bin/python`.
**No WSLENV.** `RUBICON_CAMPAIGN_DIR` is read directly.

## settings.json hooks
Replace `{{HOOK_PY}}` with `python3`. Hook commands: `python3 {{ENGINE_DIR}}/hooks/...` (POSIX path). Single native interpreter;
the WSL/Windows ChromaDB caution does not apply. Hooks run under system python3.
