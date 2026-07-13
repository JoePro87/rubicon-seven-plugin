#!/usr/bin/env python3
"""PostToolUse hook: Validate check_canon success and inject spoiler reminder.

CRITICAL RESPONSIBILITIES:
1. Set canon_succeeded=True ONLY when check_canon returns valid output
2. Inject spoiler warning when secrets are present

This is the hook that actually opens the gate for GATED tools.
The gate_check.py PreToolUse hook verifies canon_succeeded before
allowing state-changing tools.

SECURITY: Uses fail-closed design via fail_closed_wrapper.
"""

import sys
import json
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks.hook_utils import (
    fail_closed_wrapper,
    load_state,
    save_state,
    file_lock
)


def normalize_output(output) -> str:
    """Convert tool output to string, handling dict/nested formats."""
    if isinstance(output, dict):
        # Claude Code may send {"result": "..."} or {"content": "..."}
        if "result" in output:
            return str(output["result"])
        if "content" in output:
            return str(output["content"])
        # Fallback: stringify the whole dict
        return str(output)
    return str(output) if output else ""


def is_valid_check_canon_output(output) -> bool:
    """Check if check_canon output indicates success.

    Returns False if output looks like an error message,
    which means check_canon didn't actually work.
    """
    # Normalize to string first
    output = normalize_output(output)

    if not output or not output.strip():
        return False

    # Structural success markers are AUTHORITATIVE and checked FIRST. check_canon
    # always returns its scene scaffold; a genuine tool error never does. Checking
    # these before the error scan is what prevents Bug 4 (macOS playtest): a stray
    # "not found" / "failed" buried in legitimate canon body text (a lorebook miss,
    # an NPC note, a search snippet) must NOT false-fail the gate and leave every
    # combat/antagonist turn blocked behind a reset_gate + retry.
    success_indicators = [
        "**PRESENT CHARACTERS:**",  # Full mode header
        "**[BLOCKS:",               # Shopping-list mode header
        "**[AUTO-LIGHT]**",         # Auto-light mode header
        "**[LIGHT MODE]**",         # DEPRECATED — kept for backward compat
        "**CONTEXT",                # Context matches header
        "Location:",                # Always present
        "Present:",                 # Always present
    ]

    for indicator in success_indicators:
        if indicator in output:
            return True

    # No structural scaffold present — this looks like an error or empty response.
    # Confirm against known error shapes and fail closed either way.
    error_indicators = [
        "Error:",
        "ToolError",
        "not found",
        "Could not read",
        "Could not load",
        "File not found",
        "Failed to",
        "Exception:",
        "Traceback",
    ]
    output_lower = output.lower()
    for indicator in error_indicators:
        if indicator.lower() in output_lower:
            return False

    # No success scaffold and no recognized error shape — treat as invalid (fail closed).
    return False


def extract_tool_name(full_name: str) -> str:
    """Extract the base tool name from MCP-prefixed format."""
    if full_name.startswith("mcp__rubicon-seven__"):
        return full_name[len("mcp__rubicon-seven__"):]
    return full_name


# Cap the debug log so it can't grow without bound — debug_log() fires on every
# check_canon call, and the file had reached ~4.9 MB. Once it hits this size,
# debug_log() stops appending until the file is truncated/rotated out of band.
# 1 MB is plenty to troubleshoot the most recent runs.
_DEBUG_LOG_MAX_BYTES = 1_000_000


def debug_log(msg: str):
    """Write debug info to file for troubleshooting (bounded by _DEBUG_LOG_MAX_BYTES)."""
    log_file = Path(__file__).parent / ".spoiler_check_debug.log"
    try:
        if log_file.exists() and log_file.stat().st_size >= _DEBUG_LOG_MAX_BYTES:
            return  # log is full; skip appending until it's rotated/truncated
        with open(log_file, "a", encoding="utf-8") as f:
            from datetime import datetime
            f.write(f"[{datetime.now().isoformat()}] {msg}\n")
    except Exception:
        pass  # Don't let logging break the hook


@fail_closed_wrapper
def main():
    """Main hook logic - wrapped in fail_closed_wrapper for safety."""

    debug_log("=== spoiler_check.py started ===")

    # Read hook input from stdin
    if sys.stdin.isatty():
        debug_log("stdin is tty - no input")
        # No input - pass through (shouldn't happen in normal operation)
        print(json.dumps({"continue": True}))
        return

    raw_input = sys.stdin.read()
    debug_log(f"raw_input length: {len(raw_input)}")

    if not raw_input.strip():
        debug_log("empty input - pass through")
        # Empty input - pass through
        print(json.dumps({"continue": True}))
        return

    hook_input = json.loads(raw_input)
    debug_log(f"hook_input keys: {list(hook_input.keys())}")

    raw_tool_name = hook_input.get("tool_name", "")
    tool_name = extract_tool_name(raw_tool_name)
    tool_output = hook_input.get("tool_response", "")

    debug_log(f"tool_name: {tool_name}")
    debug_log(f"tool_output type: {type(tool_output).__name__}")
    debug_log(f"tool_output preview: {str(tool_output)[:200]}")

    # Only process check_canon results
    if tool_name != "check_canon":
        # Pass through silently for other tools
        print(json.dumps({"continue": True}))
        return

    # Normalize output for validation
    normalized_output = normalize_output(tool_output)
    debug_log(f"normalized_output preview: {normalized_output[:200] if normalized_output else 'EMPTY'}")

    # This IS check_canon - validate its output and set canon_succeeded
    with file_lock():
        state = load_state()
        debug_log(f"state before: {state}")

        is_valid = is_valid_check_canon_output(normalized_output)
        debug_log(f"is_valid_check_canon_output result: {is_valid}")

        if is_valid:
            # check_canon succeeded - open the gate for GATED tools
            state["canon_succeeded"] = True
            save_state(state)
            debug_log("SUCCESS: canon_succeeded set to True")
        else:
            # check_canon returned an error - gate stays closed
            state["canon_succeeded"] = False
            save_state(state)
            debug_log("FAILURE: canon_succeeded remains False")
            # Warn Claude about the failure
            print(json.dumps({
                "continue": True,
                "message": "WARNING: check_canon appears to have failed. "
                           "GATED tools will remain blocked. Review the error above."
            }))
            return

    # Check if secrets were returned - inject spoiler reminder
    if "SECRETS" in normalized_output and ("do not reveal" in normalized_output.lower() or "dm only" in normalized_output.lower()):
        reminder = """
═══════════════════════════════════════════════════════════════
  SPOILER GATE ACTIVE — SECRETS PRESENT IN CONTEXT

Before writing your response, verify:
[ ] Am I revealing ANY information from the SECRETS section?
[ ] Am I hinting at hidden content the player hasn't discovered?
[ ] Would a player reading this learn something they shouldn't?

If YES to ANY: REWRITE before sending. Secrets are earned, not given.
═══════════════════════════════════════════════════════════════
"""
        print(json.dumps({
            "continue": True,
            "message": reminder.strip()
        }))
    else:
        # No secrets, pass through
        print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
