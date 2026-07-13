#!/usr/bin/env python3
"""
PostToolUse hook for prepare_save_state.
Verifies save content against transcript, corrects hallucinations.

Trigger: PostToolUse on mcp__rubicon-seven__prepare_save_state

Flow:
1. Receive proposed save fields + transcript path
2. Spawn verification subagent
3. Subagent compares each claim against transcript
4. If unverified claims found: correct them
5. Return corrected fields in block message for Claude to re-save
"""

import json
import re
import subprocess
import sys
import os
from pathlib import Path

# Force UTF-8 on stdout/stderr before anything prints. Native Windows defaults to
# cp1252, where any non-Latin-1 glyph crashes a print. This hook does not import
# hook_utils (which would do this for us), so guard it inline. See
# hook_utils.ensure_utf8_streams for the rationale.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Portable engine-dir resolution (env wins, else derived from this file's location)
# instead of hardcoding the owner's machine paths. This hook has no sys.path
# insertion of its own, so add the engine root before importing rubicon_paths.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rubicon_paths import engine_dir as _engine_dir
MCP_DIR = _engine_dir()

SCRIPTS_DIR = MCP_DIR / "scripts"

# Use system python3 (matches other hooks in settings.json)
PYTHON_CMD = "python3"


def log_debug(message: str):
    """Log debug info to file for troubleshooting."""
    log_path = MCP_DIR / "logs" / "verify_save_debug.log"
    log_path.parent.mkdir(exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        from datetime import datetime
        f.write(f"{datetime.now().isoformat()} | {message}\n")


# Max rejected tokens to retain — bounds the list so it can't grow unbounded.
_MAX_REJECTED_TOKENS = 20


def _extract_save_token(tool_input: dict, tool_response) -> str:
    """Pull the confirmation token minted by prepare_save_state out of the tool
    result. prepare_save_state prints 'CONFIRMATION TOKEN: {token}' (8-hex from
    md5[:8]); tool_response may be a raw string or a structured content blob, so
    serialize whatever it is and regex for the printed line. tool_input carries
    no token (the server mints it), but check it as a defensive fallback."""
    if isinstance(tool_response, str):
        blob = tool_response
    else:
        try:
            blob = json.dumps(tool_response)
        except Exception:
            blob = str(tool_response)
    m = re.search(r"CONFIRMATION TOKEN:\s*([0-9a-fA-F]{6,64})", blob)
    if m:
        return m.group(1)
    if isinstance(tool_input, dict) and tool_input.get("token"):
        return str(tool_input["token"])
    return ""


def _record_rejected_token(tool_input: dict, tool_response) -> None:
    """Record the rejected save's token so gate_check can block a confirm_save
    that would otherwise commit the hallucination-flagged save. Locked + atomic,
    same as every other hook-state write."""
    token = _extract_save_token(tool_input, tool_response)
    if not token:
        log_debug("verify_save: corrections made but no token found to record")
        return
    try:
        from hooks.hook_utils import file_lock, load_state, save_state
        with file_lock():
            state = load_state()
            rejected = state.get("rejected_save_tokens", [])
            if not isinstance(rejected, list):
                rejected = []
            if token not in rejected:
                rejected.append(token)
            state["rejected_save_tokens"] = rejected[-_MAX_REJECTED_TOKENS:]
            save_state(state)
        log_debug(f"verify_save: recorded rejected token {token}")
    except Exception as e:
        log_debug(f"verify_save: could not record rejected token: {e}")


def main():
    """Main hook entry point."""
    try:
        hook_input = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        # Invalid input, pass through
        print(json.dumps({"systemMessage": f"verify_save: Invalid JSON input: {e}"}))
        return

    # Log input fields for debugging (first few runs)
    log_debug(f"Hook input keys: {list(hook_input.keys())}")
    log_debug(f"transcript_path present: {'transcript_path' in hook_input}")

    tool_input = hook_input.get("tool_input", {})
    tool_response = hook_input.get("tool_response", {})
    transcript_path = hook_input.get("transcript_path", "")

    # Can't verify without transcript
    if not transcript_path:
        print(json.dumps({
            "systemMessage": "verify_save: No transcript_path, skipping verification"
        }))
        return

    if not os.path.exists(transcript_path):
        print(json.dumps({
            "systemMessage": f"verify_save: Transcript not found at {transcript_path}, skipping"
        }))
        return

    # Run verification
    result = verify_save_content(tool_input, transcript_path)

    if result.get("error"):
        # Verification failed, pass through with warning
        print(json.dumps({
            "systemMessage": f"verify_save: Verification error: {result['error']}"
        }))
        return

    if result.get("corrections_made"):
        # Record the rejected save's token so gate_check blocks a confirm_save
        # that would otherwise commit this hallucination-flagged save (C19).
        _record_rejected_token(tool_input, tool_response)

        # Block and return corrected fields
        corrected = result["corrected_fields"]
        change_log = result.get("change_log", "No details")

        block_message = f"""SAVE VERIFICATION FAILED - Unverified claims detected and corrected.

CHANGES MADE:
{change_log}

CORRECTED FIELDS (use these to re-call prepare_save_state):
```json
{json.dumps(corrected, indent=2)}
```

You MUST call prepare_save_state again with the corrected fields above."""

        print(json.dumps({
            "decision": "block",
            "reason": block_message
        }))
    else:
        # All claims verified, pass through
        print(json.dumps({
            "systemMessage": "verify_save: All claims verified against transcript"
        }))


def verify_save_content(proposed_fields: dict, transcript_path: str) -> dict:
    """
    Spawn verification subagent to check proposed save against transcript.

    Returns:
        {
            "corrections_made": bool,
            "corrected_fields": dict (if corrections made),
            "change_log": str (description of changes),
            "error": str (if verification failed)
        }
    """
    # Build verification prompt
    fields_json = json.dumps(proposed_fields, indent=2)

    verify_script = SCRIPTS_DIR / "verify_save_agent.py"

    if not verify_script.exists():
        return {"error": f"Verification script not found: {verify_script}"}

    try:
        # Run verification script with proposed fields and transcript path
        result = subprocess.run(
            [
                PYTHON_CMD,
                str(verify_script),
                "--transcript", transcript_path,
                "--fields", fields_json
            ],
            capture_output=True,
            text=True,
            timeout=90,  # 90 second timeout for verification
            cwd=str(MCP_DIR)
        )

        if result.returncode != 0:
            return {"error": f"Verification script failed: {result.stderr[:500]}"}

        # Parse verification result
        try:
            verification_result = json.loads(result.stdout)
            return verification_result
        except json.JSONDecodeError:
            return {"error": f"Invalid JSON from verification script: {result.stdout[:500]}"}

    except subprocess.TimeoutExpired:
        return {"error": "Verification timed out after 90 seconds"}
    except FileNotFoundError:
        return {"error": f"Python interpreter not found: {PYTHON_CMD}"}
    except Exception as e:
        return {"error": f"Verification failed: {str(e)}"}


if __name__ == "__main__":
    main()
