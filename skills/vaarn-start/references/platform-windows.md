# Platform: native Windows (no WSL)

Claude Code and the engine both run as Windows processes. No WSL boundary, so no WSLENV.

## Prerequisites (native Windows)
1. **Python 3.12** on PATH (3.9+ works; 3.12 is the tested target). The command is `python` on Windows — there is no `python3` alias.
2. **Git for Windows** (git-scm.com/downloads/win) — recommended, but **NOT required to run the engine**. The engine launches `python.exe` directly (via `.mcp.json`) and `/vaarn-start` builds the venv with plain Python — there is **no bash anywhere in the engine path**. Git Bash matters only if you use Claude Code's own **Bash tool** for the skills' `python -c` helper lines (the Desktop app installs it regardless). If Claude Code can't find it, set `CLAUDE_CODE_GIT_BASH_PATH` (e.g. `C:\Program Files\Git\bin\bash.exe`) in settings. The engine itself does not depend on it.
3. **Ollama** — optional (see Dependencies below).

## Detect
- `os.name == "nt"` (or running from PowerShell/cmd) AND `/proc/version` absent / not "microsoft".

## Venv layout
- `{{ENGINE_DIR_WIN}}\.venv\Scripts\python.exe` (Windows `Scripts\`, not POSIX `bin/`).
- Create: from the engine dir, `python -m venv .venv`.

## Dependencies
1. `{{ENGINE_DIR_WIN}}\.venv\Scripts\python.exe -m pip install -r requirements.txt`
   (mcp/FastMCP, **chromadb==1.3.7** — keep the pin, filelock, anthropic, numpy, requests).
2. **Ollama** (separate local service for search):
   - Install Windows Ollama from ollama.com (runs on `localhost:11434`).
   - `ollama pull nomic-embed-text`.
   - Optional — search stays dark until present; the engine boots without it.

## mcp.json
Use `assets/mcp.json.windows-native.template`. Windows paths (`C:\...`, double backslashes).
**No WSLENV** — `RUBICON_CAMPAIGN_DIR` is read directly.

## settings.json hooks
Replace `{{HOOK_PY}}` in `assets/settings.json.template` with **`python`** (native Windows has no
`python3` alias). Point the hooks at the same engine dir (`{{ENGINE_DIR}}/hooks/...`; forward slashes
are fine for Python on Windows); the hooks are platform-agnostic Python.
