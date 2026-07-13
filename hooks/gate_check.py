#!/usr/bin/env python3
"""Claude Code hook to enforce tool gating (FAIL-CLOSED).

This hook runs on PreToolUse and blocks gated tools
if check_canon hasn't been called AND succeeded this turn.

SECURITY: This hook uses fail-closed design. ANY exception
results in blocking the tool, not allowing it through.
"""

import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tool_tags import Safety, TOOL_TAGS
from hooks.hook_utils import (
    fail_closed_wrapper,
    load_state,
    save_state,
    read_hook_input,
    extract_tool_name,
    block,
    allow,
    file_lock,
    in_maintenance,
)


# Boundary tools that end a scene. Conservative v1: advance_day only — the
# unambiguous, safe-to-block "time moved" signal. NEVER add save_state/
# prepare_save_state (must not block saves).
_NPC_BOUNDARY_TOOLS = {"advance_day"}


def npc_boundary_block(tool_name, tool_input, state):
    """Return a block message if a scene-boundary tool is called while an NPC
    scene is open and unrecorded; else None."""
    if tool_name not in _NPC_BOUNDARY_TOOLS:
        return None
    open_map = state.get("open_npc_scene", {})
    if not open_map:
        return None
    names = ", ".join(f"{v.get('name', slug)} (name='{slug}')" for slug, v in open_map.items())
    return (f"OPEN NPC SCENE: record continuity before time advances — "
            f"npc(action='continuity', name='<npc>', left_off='...', open_purpose='...') "
            f"for: {names}. (The world-tick will move on; capture where you left off first.)")


def clear_npc_on_continuity(tool_input, state):
    """If this is npc(action='continuity', name=X), drop X from open_npc_scene."""
    if not isinstance(tool_input, dict):
        return
    if tool_input.get("action", "").lower().strip() != "continuity":
        return
    name = (tool_input.get("name") or "").lower().strip()
    if name and name in state.get("open_npc_scene", {}):
        state["open_npc_scene"].pop(name, None)


@fail_closed_wrapper
def main():
    """Main hook logic - wrapped in fail_closed_wrapper for safety."""

    # Read and parse hook input (raises on failure -> fail closed)
    hook_input = read_hook_input()

    raw_tool_name = hook_input.get("tool_name", "")
    tool_name = extract_tool_name(raw_tool_name)

    # Load current state with locking
    with file_lock():
        state = load_state()

        # Rejected-save-token gate (C19): the PostToolUse verify_save hook records
        # the token of any save it rejected for unverified/hallucinated claims.
        # confirm_save carrying a rejected token must NOT commit that save. This
        # sits ABOVE the maintenance-mode bypass on purpose — it guards the live
        # canon write into MASTER_CONTINUITY + ChromaDB. It is self-clearing: a
        # re-called prepare_save_state mints a fresh token, so a legitimate re-save
        # can never be trapped by a stale flag. NOTE: this only ever blocks
        # confirm_save — never prepare_save_state/save_state (must not block saves).
        if tool_name == "confirm_save":
            _cs_ti = hook_input.get("tool_input", {})
            if not isinstance(_cs_ti, dict):
                _cs_ti = {}
            _cs_token = str(_cs_ti.get("token", "") or "")
            _rejected = state.get("rejected_save_tokens", [])
            if _cs_token and isinstance(_rejected, list) and _cs_token in _rejected:
                block(
                    "BLOCKED: this save was rejected by verify_save for unverified or "
                    "hallucinated claims. Re-run prepare_save_state with the corrected "
                    "fields verify_save returned — that mints a fresh token you can then "
                    f"confirm. [raw: {raw_tool_name}]"
                )

        # Special handling for check_canon - marks that verification was ATTEMPTED
        # Note: canon_succeeded is set by spoiler_check.py AFTER check_canon returns
        if tool_name == "check_canon":
            state["canon_verified"] = True
            # canon_succeeded stays False until spoiler_check validates output
            save_state(state)
            allow()

        # Record NPC verification when lorebook/npc tools are used
        # Persists in state so NPC fabrication check survives stop hook retries
        if tool_name in ("lorebook", "npc"):
            tool_input = hook_input.get("tool_input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}
            target = tool_input.get("keyword", "") or tool_input.get("name", "")
            if target:
                verified = list(state.get("verified_npcs", []))
                target_lower = target.lower()
                if target_lower not in verified:
                    verified.append(target_lower)
                state["verified_npcs"] = verified
            # A continuity write clears its open-scene flag (door gate, Task 3).
            # Runs even if target is empty; the clear persists below.
            clear_npc_on_continuity(tool_input, state)
            save_state(state)

        # Special handling for full_session_startup - marks session start
        if tool_name == "full_session_startup":
            state["session_started"] = True
            state["canon_verified"] = True
            state["canon_succeeded"] = True  # Startup bypasses normal verification
            # Clear maintenance bypass (all three keys) so it can't ride into play.
            state["skip_canon_enforcement"] = False
            state["maintenance_mode"] = False
            state["skip_semantic_observer"] = False
            state["turn_count"] = 0  # Reset turn tracking for new session
            save_state(state)
            allow()

        # Validate prose enforcement — if the prose gate was skipped on a narrative
        # turn, block all tools until narrative_qa(action='validate') is called this turn.
        # Bypassed in maintenance mode (skip_canon_enforcement).
        if state.get("validate_prose_required", False):
            if not in_maintenance(state):
                # The prose gate is narrative_qa(action='validate').
                _vp_ti = hook_input.get("tool_input", {})
                if not isinstance(_vp_ti, dict):
                    _vp_ti = {}
                _is_prose_gate = (
                    tool_name == "narrative_qa"
                    and _vp_ti.get("action", "").lower().strip() == "validate"
                )
                if _is_prose_gate:
                    # This IS the prose gate — clear the flag and allow
                    state["validate_prose_required"] = False
                    state["validate_prose_called"] = True
                    save_state(state)
                    allow()
                else:
                    block(f"BLOCKED: the prose gate was skipped last narrative turn. "
                          f"Call narrative_qa(action='validate', text=...) with your draft "
                          f"before using any other tool. [raw: {raw_tool_name}]")

        # Vault-liveness enforcement — if a narrative turn completed inside an armed vault
        # without advancing current_turn, block all tools until a map action is taken.
        # A map(enter|search|wait) satisfies the gate (those actions mutate current_turn).
        # Bypassed in maintenance mode (skip_canon_enforcement).
        if state.get("vault_action_required", False):
            if not in_maintenance(state):
                vault_enforce = state.get("vault_enforce", {})
                map_name = vault_enforce.get("map", "unknown")
                if tool_name == "map":
                    # This IS the map tool — clear the flag and allow.
                    # consolidated_stop_check will update last_turn after the tool fires.
                    state["vault_action_required"] = False
                    save_state(state)
                    allow()
                else:
                    block(
                        f"VAULT ARMED ({map_name}): the dungeon must advance every turn — "
                        f"call map(enter/search) to move, or map(action=\"wait\", map_name=\"{map_name}\") "
                        f"to hold (ticks time, rolls the encounter die, advances the clock). "
                        f"A parley is fine; a frozen dungeon is not. "
                        f"[raw: {raw_tool_name}]"
                    )

        # NPC continuity enforcement: don't let time advance with an open,
        # unrecorded NPC scene. Bypassed in maintenance mode.
        if not in_maintenance(state):
            _npc_msg = npc_boundary_block(tool_name, hook_input.get("tool_input", {}), state)
            if _npc_msg:
                block(f"{_npc_msg} [raw: {raw_tool_name}]")

        # Get tool tags
        tags = TOOL_TAGS.get(tool_name, set())

        # Check if tool is GATED (requires check_canon to succeed)
        if Safety.GATED in tags:
            # Respect canon_required — if turn_reset determined canon isn't needed
            # (stable scene, not modulo-3 turn), don't block read-path tools
            canon_required = state.get("canon_required", True)

            # Must have both: check_canon was called AND it succeeded
            if not state.get("canon_verified", False) and canon_required:
                block(f"BLOCKED: Tool '{tool_name}' requires check_canon first. "
                      f"Call check_canon to verify campaign state before using state-changing tools. "
                      f"[raw: {raw_tool_name}]")

            if not state.get("canon_succeeded", False) and canon_required:
                block(f"BLOCKED: Tool '{tool_name}' requires check_canon to SUCCEED. "
                      f"check_canon was called but hasn't completed successfully yet. "
                      f"[raw: {raw_tool_name}]")

        # Check session startup requirement
        if not state.get("session_started", False):
            if Safety.ALWAYS not in tags:
                block(f"BLOCKED: Tool '{tool_name}' unavailable until full_session_startup completes. "
                      f"Start the session properly first. [raw: {raw_tool_name}]")

    # All checks passed
    allow()


if __name__ == "__main__":
    main()
