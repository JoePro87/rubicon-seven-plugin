#!/usr/bin/env python3
"""PostCompact hook: Re-inject validate_prose requirement after context compaction.

Compaction is the primary cause of validate_prose skips — Claude loses the
CLAUDE.md instruction to call it. This hook fires after every compaction
and outputs a system reminder that validate_prose is required.

Also resets validate_prose_called to False (new context = clean slate).
Re-derives vault_enforce from CURRENT_STATUS + prep header (both on disk)
so the vault-liveness gate survives compaction.

SECURITY: Fail-open. If anything breaks, no reminder is better than a crash.
"""

# PEP 563: defer annotation evaluation so PEP 604 unions (dict | None) parse on
# Python 3.9 — these hooks run under the system python3, which is 3.9 on a stock macOS.
from __future__ import annotations

import os
import re
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks.hook_utils import load_state, save_state, file_lock, in_maintenance

from rubicon_paths import campaign_dir as _campaign_dir
CAMPAIGN_DIR = _campaign_dir()

_DUNGEON_HEADER_RE = re.compile(
    r'<!--\s*DUNGEON:\s*map=(\S+)\s+enforce=vault-liveness\s*-->'
)


def _re_derive_vault_enforce() -> dict | None:
    """Re-derive vault_enforce from CURRENT_STATUS.md and the active prep file(s).

    Returns a vault_enforce dict if a DUNGEON-headered prep is active, else None.
    This is a compaction-safe re-derivation — no in-process state needed.
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    try:
        text = status_path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Extract Active Prep filenames
    active_prep_line = ""
    for line in text.splitlines():
        if "**Active Prep:**" in line:
            active_prep_line = line.split("**Active Prep:**", 1)[1].strip()
            break

    if not active_prep_line or active_prep_line.lower() == "none":
        return None

    parts = re.split(r'[;,/]', active_prep_line)
    for part in parts:
        part = re.sub(r'\([^)]*\)', '', part).strip()
        m_fn = re.search(r'(\S+\.md)', part, re.IGNORECASE)
        if not m_fn:
            continue
        prep_path = CAMPAIGN_DIR / m_fn.group(1)
        try:
            with open(prep_path, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 10:
                        break
                    m = _DUNGEON_HEADER_RE.search(line)
                    if m:
                        map_name = m.group(1)
                        # Read current_turn from the map JSON
                        map_path = CAMPAIGN_DIR / "maps" / f"{map_name}_map.json"
                        current_turn = 0
                        try:
                            data = json.loads(map_path.read_text(encoding="utf-8"))
                            current_turn = data.get("current_turn", 0)
                        except Exception:
                            pass
                        return {
                            "armed": True,
                            "map": map_name,
                            "last_turn": current_turn,  # after compaction, reseed at current
                        }
        except Exception:
            continue

    return None


def main():
    try:
        # Reset validate_prose_called and re-derive vault_enforce after compaction
        with file_lock():
            state = load_state()

            # Skip if maintenance mode
            if in_maintenance(state):
                sys.exit(0)

            # Skip if not gameplay
            if state.get("session_type", "development") != "gameplay":
                sys.exit(0)

            state["validate_prose_called"] = False
            state["canon_delivered"] = {}  # compaction = fresh context; re-ship all canon

            # Force check_canon on the next narrative turn (C27). Compaction is the
            # DM's most amnesiac moment, yet the per-turn canon_required gate stays
            # off when the scene fingerprint is unchanged (as it typically is right
            # after a compaction). Blanking the fingerprint makes turn_reset compute
            # scene_changed=True -> canon_required=True next turn, so a freshly
            # compacted DM cannot narrate from a lossy summary with zero canon pull.
            state["scene_fingerprint"] = ""

            # Clear transient vault gate flag (compaction = new context = fresh turn)
            state["vault_action_required"] = False

            # Re-derive vault_enforce from disk (compaction-safe)
            new_enforce = _re_derive_vault_enforce()
            if new_enforce:
                state["vault_enforce"] = new_enforce
            else:
                # No armed vault — disarm
                state["vault_enforce"] = {"armed": False}

            save_state(state)

        # Inject reminder into Claude's context
        reminder_parts = [
            "COMPACTION OCCURRED. "
            "narrative_qa(action='validate') is REQUIRED before all narrative output. "
            "Call narrative_qa(action='validate', text=...) with your draft before delivering to the player.",
            "check_canon is REQUIRED on your next narrative turn.",
        ]

        # Vault reminder if re-armed
        vault_state = state.get("vault_enforce", {})
        if vault_state.get("armed"):
            map_name = vault_state.get("map", "unknown")
            current_turn = vault_state.get("last_turn", 0)
            reminder_parts.append(
                f"VAULT STILL ARMED ({map_name}, turn {current_turn}): "
                f"vault-liveness gate is live — map(enter/search/wait) required every narrative turn."
            )

        print("\n".join(reminder_parts))
        sys.exit(0)

    except Exception:
        # Fail-open — no reminder is better than a crash
        sys.exit(0)


if __name__ == "__main__":
    main()
