# Platform: macOS

Everything is POSIX and native — no WSL, no Windows venv. Simplest case.

## Detect
- `uname` == "Darwin".

## Venv layout
- `{{ENGINE_DIR}}/.venv/bin/python` (POSIX `bin/`, NOT `Scripts/python.exe`).
- Create: from the engine dir, `python3 -m venv .venv`.

## Dependencies
1. `{{ENGINE_DIR}}/.venv/bin/python -m pip install -r requirements.txt`
   (mcp/FastMCP, **chromadb==1.3.7** — keep the pin, filelock, anthropic, numpy, requests).
2. **Ollama** (separate local service for search):
   - Install: `brew install ollama` (or download from ollama.com), then start it
     (`ollama serve`, or the menu-bar app). Runs on `localhost:11434`.
   - `ollama pull nomic-embed-text`.
   - Optional — if skipped, search stays dark until installed; the engine boots without it.

## mcp.json
Use `assets/mcp.json.posix.template`. POSIX paths; venv command is `.venv/bin/python`.
**No WSLENV.** `RUBICON_CAMPAIGN_DIR` is read directly.

## settings.json hooks
Replace `{{HOOK_PY}}` with `python3`. Hook commands: `python3 {{ENGINE_DIR}}/hooks/...` (POSIX path). The ChromaDB pin caution
(WSL python3 vs Windows venv) does NOT apply here — there's a single native interpreter, and
the venv python is canonical for the server.

⚠ **Hooks run under the system `python3`, which on a stock Mac is 3.9** (Command Line Tools).
The hooks are written to be **system-python-safe (≥3.9, stdlib-only)** — that's a hard contract,
not "it's fine by luck." Every hook carries `from __future__ import annotations` so modern type
syntax (`str | None`) parses on 3.9. If you add or edit a hook, keep it 3.9-compatible (no
`match` statements, no runtime `X | Y` unions, no venv-only imports like chromadb) — otherwise it
crashes at module load under the system interpreter and the Stop/PostCompact hooks fail every turn.
