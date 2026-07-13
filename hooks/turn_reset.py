#!/usr/bin/env python3
"""Claude Code hook to reset turn state.

This hook runs on UserPromptSubmit and:
1. Resets the canon_verified flag (requiring check_canon each turn)
2. Resets the canon_succeeded flag (check_canon must succeed to open gate)
3. Detects /all command for forcing all tools visible
4. Preserves session_started state
5. Tracks turn count and scene fingerprint for intelligent gating

SECURITY: Uses fail-closed design via fail_closed_wrapper.
"""

import json
import os
import sys
import hashlib
import re
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

# Campaign directory for status file (portable: env wins, else derived sibling)
from rubicon_paths import campaign_dir as _campaign_dir
CAMPAIGN_DIR = _campaign_dir()

from hooks.hook_utils import (
    fail_closed_wrapper,
    load_state,
    save_state,
    file_lock,
    in_maintenance,
    allow,
    temp_dir,
    detached_popen_kwargs,
)
from hooks.correction_logger import mark_false_positive
from hooks.lorebook_gate import extract_triggers, should_skip_message



def _last_dm_text(hook_input: dict) -> str:
    """Return the text of the most recent assistant (DM) message, or ''."""
    messages = hook_input.get("transcript_messages", [])
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
    return ""


def detect_force_all(message: str) -> bool:
    """Detect if user wants all tools visible."""
    return message.strip().startswith("/all") or "/all" in message.lower()


def detect_false_positive(message: str) -> bool:
    """Detect if user is flagging a false positive."""
    msg_lower = message.strip().lower()
    return msg_lower in ("fp", "false positive", "/fp")


def detect_skip_review(message: str) -> bool:
    """Detect the player waiving the dm-design review gate.

    The dm-design Stop gate honors state["skip_dm_design_gate"], and its block
    message tells the player to "say 'skip review' to waive" — but nothing was
    setting that flag, so the advertised waiver had no detector behind it (the
    gate persisted in .hook_state.json across restarts). This wires the phrase
    the gate already advertises, plus the obvious variants.
    """
    msg_lower = message.lower()
    return (
        "skip review" in msg_lower
        or "skip the review" in msg_lower
        or "skip dm-design" in msg_lower
        or "skip dm design" in msg_lower
        or "waive review" in msg_lower
        or "waive the review" in msg_lower
    )


def compute_scene_fingerprint() -> str:
    """Compute hash of current scene (location + characters present).

    Returns empty string if status file unreadable - treated as "scene changed".
    """
    status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
    if not status_path.exists():
        return ""

    try:
        content = status_path.read_text(encoding='utf-8')

        # Extract Location and Present lines
        location_match = re.search(r'\*\*Location:\*\*\s*(.+?)(?:\n|$)', content)
        present_match = re.search(r'\*\*Present:\*\*\s*(.+?)(?:\n|$)', content)

        location = location_match.group(1).strip() if location_match else ""
        present = present_match.group(1).strip() if present_match else ""

        # Normalize: lowercase, sort characters alphabetically
        present_sorted = ",".join(sorted(p.strip().lower() for p in present.split(",")))

        # Create deterministic fingerprint
        fingerprint_input = f"{location.lower()}|{present_sorted}"
        return hashlib.md5(fingerprint_input.encode()).hexdigest()[:12]

    except Exception:
        return ""  # On error, return empty = treat as scene changed


def should_require_canon(turn_count: int, scene_changed: bool, user_message: str = "") -> bool:
    """Determine if this turn requires check_canon.

    Canon is required when:
    1. Scene changed — fingerprint differs from previous turn
    2. Early session (turn <= 3) — always need full context
    3. Modulo trigger (turn % 3 == 0) — periodic refresh

    Canon is NOT required when:
    - User message matches admin/system command patterns (except scene changes)

    Returns True if canon is required, False if it can be skipped.
    """
    # Scene change always requires canon (even on admin turns)
    if scene_changed:
        return True

    # Admin messages skip canon (except scene changes above)
    # Uses shared list from hook_utils to stay in sync with server.py
    from hooks.hook_utils import ADMIN_COMMAND_PATTERNS
    if user_message:
        input_lower = user_message.lower().strip()
        if any(pattern in input_lower for pattern in ADMIN_COMMAND_PATTERNS):
            return False
        # Parenthetical messages are meta/admin — player convention for OOC
        if input_lower.startswith("("):
            return False

    if turn_count <= 3:
        return True
    if turn_count % 3 == 0:
        return True
    return False


@fail_closed_wrapper
def main():
    """Main hook logic - wrapped in fail_closed_wrapper for safety."""

    # Read and parse JSON from stdin
    raw_stdin = ""
    user_message = ""
    hook_input = {}
    if not sys.stdin.isatty():
        try:
            raw_stdin = sys.stdin.read()
            # Claude Code sends JSON with hook input data
            hook_input = json.loads(raw_stdin) if raw_stdin.strip() else {}
            # Try multiple possible field names for user message
            user_message = (
                hook_input.get("prompt", "") or
                hook_input.get("user_message", "") or
                hook_input.get("message", "") or
                hook_input.get("input", "") or
                ""
            )
            # If no explicit message field, check transcript for last user message
            if not user_message:
                messages = hook_input.get("transcript_messages", [])
                for msg in reversed(messages):
                    if msg.get("role") == "user":
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            user_message = content
                        elif isinstance(content, list):
                            # Content might be array of blocks
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    user_message = block.get("text", "")
                                    break
                        break
        except json.JSONDecodeError:
            # If not JSON, treat raw stdin as the message (fallback)
            user_message = raw_stdin
        except Exception:
            pass

    force_all = detect_force_all(user_message)
    skip_review_requested = detect_skip_review(user_message)

    # Check for false positive feedback
    if detect_false_positive(user_message):
        if mark_false_positive():
            # FP marked, continue normally
            pass

    # --- Correction capture (learning loop) — detached, silent, fail-open ---
    # This spawns a Haiku API agent, so it MUST respect the same guards as the
    # other gameplay hooks: gameplay-only, and NEVER during maintenance mode
    # (mirrors phrase_reminder: session_type == "gameplay" and not skip_canon_enforcement).
    try:
        from hooks.correction_capture import looks_like_correction
        _cc_state = load_state()
        _cc_allowed = (
            _cc_state.get("session_type") == "gameplay"
            and not in_maintenance(_cc_state)
        )
        if _cc_allowed and user_message and looks_like_correction(user_message):
            prior_dm = _last_dm_text(hook_input)
            if prior_dm:
                import subprocess
                import json as _json
                hooks_dir = Path(__file__).parent
                _st = load_state()
                _payload = {
                    "prior_dm": prior_dm,
                    "correction": user_message,
                    "session_id": hook_input.get("session_id") or _st.get("session_id", "unknown"),
                    "turn": _st.get("turn_count", 0),
                    "cache_path": str(CAMPAIGN_DIR / ".canon_distillations.json"),  # campaign-scoped (was engine-relative — privacy leak)
                    "bans_path": str(CAMPAIGN_DIR / "fabrication_bans.json"),  # campaign-scoped (was engine-relative — personalization leak)
                }
                _tmp = Path(temp_dir()) / f"rubicon_capture_{_payload['turn']}_{os.getpid()}.json"
                _tmp.write_text(_json.dumps(_payload), encoding="utf-8")
                subprocess.Popen(
                    ["python3", str(hooks_dir / "correction_capture_runner.py"), str(_tmp)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                    **detached_popen_kwargs(),
                )
    except Exception:
        pass

    with file_lock():
        # Load previous state to preserve session_started and context_reminded
        old_state = load_state()

        # ========================================
        # TURN TRACKING & SCENE FINGERPRINTING
        # For intelligent check_canon gating
        # ========================================
        turn_count = old_state.get("turn_count", 0) + 1

        # Compute current scene fingerprint
        current_fingerprint = compute_scene_fingerprint()
        old_fingerprint = old_state.get("scene_fingerprint", "")

        # Detect scene change (different fingerprint OR empty = unknown = assume changed)
        scene_changed = (
            current_fingerprint != old_fingerprint
            or current_fingerprint == ""
            or old_fingerprint == ""
        )

        # Detect /session-start to set session_type to gameplay
        is_session_start = "/session-start" in user_message or "session-start" in user_message.lower()

        # Determine if canon is required this turn
        canon_required = should_require_canon(turn_count, scene_changed, user_message)

        # Determine if lorebook is required this turn
        # Skip admin/parenthetical/short messages; otherwise scan for lorebook keywords
        lorebook_triggers: list[str] = []
        skip_msg = should_skip_message(user_message)
        if not skip_msg:
            try:
                lorebook_triggers = extract_triggers(user_message, max_triggers=5)
            except Exception:
                lorebook_triggers = []
        lorebook_required = bool(lorebook_triggers)

        # Detect hook feedback echo — stop hook retries and tool schema loads
        # are not real user turns; preserve verification state across them
        _is_hook_retry = False
        if user_message:
            _msg_lower = user_message.lower()
            _is_hook_retry = any(m in _msg_lower for m in (
                "stop hook feedback",
                "stop hook blocking error",
                "pretooluse hook",
                "tool loaded",
            ))

        # Build new state
        state = {
            # Reset canon flags on real user turns; preserve on hook retries
            "canon_verified": old_state.get("canon_verified", False) if _is_hook_retry else False,
            "canon_succeeded": old_state.get("canon_succeeded", False) if _is_hook_retry else False,

            # Whether this turn requires canon before responding
            "canon_required": canon_required,

            # Lorebook gate: required if user input contains lorebook keywords
            "lorebook_required": lorebook_required,
            "lorebook_triggers": lorebook_triggers,
            "lorebook_called": False,

            # Preserve these across turns
            "session_started": old_state.get("session_started", False),
            "context_reminded": old_state.get("context_reminded", False),

            # Set force_all based on current message
            "force_all": force_all,

            # Turn tracking for intelligent gating
            "turn_count": turn_count,
            "scene_fingerprint": current_fingerprint,
            "scene_changed": scene_changed,

            # Preserve skip_canon_enforcement (set by /maintenance skill)
            "skip_canon_enforcement": old_state.get("skip_canon_enforcement", False),

            # Preserve skip_semantic_observer (set by /maintenance skill — stops the Haiku prose observer)
            "skip_semantic_observer": old_state.get("skip_semantic_observer", False),

            # Session type: set to "gameplay" on /session-start, preserved across turns
            "session_type": "gameplay" if is_session_start else old_state.get("session_type", "development"),

            # Session vocabulary: preserved across turns, cleared on /session-start
            "session_vocabulary": [] if is_session_start else old_state.get("session_vocabulary", []),

            # Anti-pattern catch counter: preserved across turns, cleared on /session-start
            "catch_count": 0 if is_session_start else old_state.get("catch_count", 0),
            "catch_log": {} if is_session_start else old_state.get("catch_log", {}),

            # Verified NPCs: preserved across hook retries, cleared on real user turns
            "verified_npcs": old_state.get("verified_npcs", []) if _is_hook_retry else [],

            # Validate prose gate: preserved on hook retries, cleared on real turns
            "validate_prose_called": old_state.get("validate_prose_called", False) if _is_hook_retry else False,

            # Canon delta-delivery: cleared on /session-start, preserved across
            # normal turns (so already-delivered elements stay deduped).
            "canon_delivered": {} if is_session_start else old_state.get("canon_delivered", {}),

            # Reflex snapshot (phrase_reminder Δ baseline): cleared on
            # /session-start, preserved across normal turns — wiping it every
            # turn would kill the CHANGED tier in live play.
            "reflex_snapshot": {} if is_session_start else old_state.get("reflex_snapshot", {}),

            # dm-design review gate: the pending obligation, the player's
            # waiver flag, and maintenance mode must all survive turn resets.
            # The gate (consolidated_stop_check) owns their lifecycle.
            "pending_dm_design": old_state.get("pending_dm_design"),
            # Player can waive the review by saying "skip review" (the phrase the
            # gate's own block message advertises). Latch True this turn; the gate
            # consumes it and resets it to False once it clears pending_dm_design.
            "skip_dm_design_gate": True if skip_review_requested else old_state.get("skip_dm_design_gate", False),
            "maintenance_mode": old_state.get("maintenance_mode", False),

            # Stop-armed enforcement gates (audit 2026-06-16): armed at Stop by
            # consolidated_stop_check, read next turn by gate_check. Rebuilding
            # state from scratch dropped them, so these three enforcements never
            # blocked. Preserve across normal turns (each is cleared by its own
            # satisfier — gate_check on satisfaction, or per-NPC pop). Clear on
            # /session-start: they are about the response just given, and a stale
            # obligation must not block full_session_startup at the next start.
            "validate_prose_required": False if is_session_start else old_state.get("validate_prose_required", False),
            "vault_action_required": False if is_session_start else old_state.get("vault_action_required", False),
            "open_npc_scene": {} if is_session_start else old_state.get("open_npc_scene", {}),

            # BELL time-of-day priming: a continuing value (not an obligation) —
            # carry it so the time annotation survives pure-narrative turns; it
            # persists until _set_bell updates it.
            "current_bell": old_state.get("current_bell", 0),

            # Ceruline per-session advisory: carry across turns, clear on
            # /session-start (it is a "seen this session" flag). Never blocks.
            "ceruline_seen_session": False if is_session_start else old_state.get("ceruline_seen_session", False),
        }

        save_state(state)

    # Always allow (this is UserPromptSubmit, not a tool)
    allow()


if __name__ == "__main__":
    main()
