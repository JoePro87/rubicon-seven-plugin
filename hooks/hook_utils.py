#!/usr/bin/env python3
"""Shared utilities for Claude Code hooks.

All hooks should use these utilities to ensure consistent
fail-closed behavior and atomic state management.
"""

import os
import sys
import json
import functools
import time
import tempfile
import subprocess
from pathlib import Path
from typing import Optional
from contextlib import contextmanager


def ensure_utf8_streams() -> None:
    """Force this hook process's stdout/stderr to UTF-8.

    On native Windows, Python defaults stdout/stderr to the legacy cp1252
    codec. Printing any non-Latin-1 glyph the engine emits (the gear, arrows,
    box-drawing, emoji) then raises UnicodeEncodeError. Because the gate/Stop
    hooks are FAIL-CLOSED, such a crash blocks the player on every turn — the
    game is unplayable on native Windows out of the box. errors="replace" makes
    even an unexpected glyph degrade to '?' instead of crashing. Idempotent and
    defensive: any failure is swallowed so this can never be the thing that
    breaks a fail-closed hook.
    """
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# Run at import time so every hook that imports hook_utils is protected before
# it prints anything (imports resolve before any hook's print statements).
ensure_utf8_streams()

# State file location
STATE_FILE = Path(__file__).parent / ".hook_state.json"
LOCK_FILE = Path(__file__).parent / ".hook_state.lock"

# A lock left behind by a crashed/killed holder is reclaimed once it ages past
# this. Hook operations under the lock are sub-second, so 3s is a wide margin —
# and crucially it is SHORTER than the default acquire timeout (5s), so a
# leftover lock is reclaimed WITHIN a normal wait instead of guaranteeing a
# TimeoutError (the full-suite-only flake root cause).
_STALE_LOCK_SECONDS = 3.0

# Exit codes
EXIT_ALLOW = 0
EXIT_BLOCK = 2

# Canonical list of admin/system command patterns.
# Used by both turn_reset.py (to skip canon requirement) and
# server.py SYSTEM_COMMAND_PATTERNS (to return minimal context).
# If you add a pattern here, it takes effect in both layers.
ADMIN_COMMAND_PATTERNS = [
    'confirm save', 'set active prep', 'turn on', 'turn off',
    'reload prep', 'sync campaign', 'toggle', 'end session',
    'save session', 'save game', 'save the game',
]

# State-changing tools — shared between validate_prose (server.py) and
# consolidated_stop_check.py for prep-file-progress gating.
STATE_CHANGING_TOOLS = {
    "mcp__rubicon-seven__map",
    "mcp__rubicon-seven__combat",
    "mcp__rubicon-seven__npc",
    "mcp__rubicon-seven__relationship",
    "mcp__rubicon-seven__roll",
    "mcp__rubicon-seven__generate",
    "mcp__rubicon-seven__character",
    "mcp__rubicon-seven__rest",
    "mcp__rubicon-seven__advance_day",
    "mcp__rubicon-seven__codex",
    "mcp__rubicon-seven__gift",
    "mcp__rubicon-seven__cybernetic",
}

NON_STATE_ACTIONS = {
    "mcp__rubicon-seven__map": {"render", "get_room", "query_nearby", "list_floors"},
    "mcp__rubicon-seven__npc": {"get", "list"},
    "mcp__rubicon-seven__combat": {"state", "log"},
    "mcp__rubicon-seven__relationship": {"get", "list", "history"},
    "mcp__rubicon-seven__character": {"get", "list"},
}

TOOL_LABELS = {
    "mcp__rubicon-seven__map": "map movement",
    "mcp__rubicon-seven__combat": "combat",
    "mcp__rubicon-seven__npc": "NPC state change",
    "mcp__rubicon-seven__relationship": "relationship change",
    "mcp__rubicon-seven__roll": "roll result",
    "mcp__rubicon-seven__generate": "content generated",
    "mcp__rubicon-seven__character": "character state change",
    "mcp__rubicon-seven__rest": "rest taken",
    "mcp__rubicon-seven__advance_day": "day advanced",
    "mcp__rubicon-seven__codex": "codex ability",
    "mcp__rubicon-seven__gift": "gift changed",
    "mcp__rubicon-seven__cybernetic": "cybernetic changed",
}


def block(message: str) -> None:
    """Block tool with message and exit."""
    print(message, file=sys.stderr)
    sys.exit(EXIT_BLOCK)


def allow(message: Optional[str] = None) -> None:
    """Allow tool with optional message and exit."""
    if message:
        print(message)
    sys.exit(EXIT_ALLOW)


# ============================================================
# Cross-platform process / temp-file helpers
# ============================================================
#
# Hooks write subprocess handoff payloads to a temp dir and spawn
# fire-and-forget observer children. Both operations had POSIX-only
# assumptions (a hardcoded "/tmp" path and start_new_session=True) that
# silently break on native Windows. These two helpers centralize the
# portable form so the pattern isn't duplicated across hooks.
#
# On the owner's WSL rig (POSIX python3) both helpers return EXACTLY what
# the old hardcoded code did, so live behavior is byte-for-byte unchanged.


def temp_dir() -> str:
    """Return the directory hooks should use for subprocess handoff files.

    Resolution order:
      1. ``RUBICON_TEMP_DIR`` env var, if set (explicit override).
      2. ``tempfile.gettempdir()`` — the OS temp dir.

    On the owner's POSIX rig this yields ``/tmp`` (or ``$TMPDIR``),
    equivalent to the previous hardcoded ``"/tmp"``. On native Windows it
    yields the real per-user temp dir instead of an unresolvable ``/tmp``.
    """
    override = os.environ.get("RUBICON_TEMP_DIR")
    if override:
        return override
    return tempfile.gettempdir()


def detached_popen_kwargs() -> dict:
    """Return the kwargs that fully detach a fire-and-forget child process.

    POSIX (``os.name != "nt"``): ``{"start_new_session": True}`` — byte-for-byte
    identical to the previous hardcoded behavior on the owner's WSL rig.

    Windows (``os.name == "nt"``): ``CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS``
    creation flags, since ``start_new_session`` is ignored there and the child
    would otherwise remain a blocking process that dies with the parent.
    """
    if os.name == "nt":
        return {
            "creationflags": (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            )
        }
    return {"start_new_session": True}


def fail_closed_wrapper(func):
    """Decorator that ensures hooks exit with BLOCK on any exception.

    This is the critical safety wrapper - if ANYTHING goes wrong,
    we block the tool rather than allowing it through.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except SystemExit:
            # Re-raise intentional exits (from block() and allow())
            raise
        except Exception as e:
            # Any other exception = fail closed
            block(f"HOOK ERROR (fail-closed): {type(e).__name__}: {e}")
    return wrapper


@contextmanager
def file_lock(*, lock_path: Optional[Path] = None, timeout: float = 5.0):
    """Cross-platform file locking context manager.

    Uses simple lock file with timeout. Not perfect but prevents
    most race conditions between concurrent hook invocations.

    Args:
        lock_path: Path to the lock file. Defaults to the shared LOCK_FILE.
                   Pass a per-resource path (e.g. cache_file.lock) to avoid
                   contention with the main hook state lock. Keyword-only
                   to prevent accidental positional misuse (e.g. file_lock(5.0)
                   would otherwise silently treat 5.0 as a path).
        timeout:   Seconds to wait before raising TimeoutError. Keyword-only.
    """
    lf = Path(lock_path) if lock_path is not None else LOCK_FILE
    start_time = time.time()

    while True:
        try:
            # Try to create lock file exclusively
            fd = lf.open('x')
            fd.write(str(time.time()))
            fd.close()
            break
        except (FileExistsError, PermissionError):
            # FileExistsError: another holder has the lock.
            # PermissionError (Windows WinError 5/32): the lock file is
            # TRANSIENTLY locked by a racing create/unlink or the AV/search
            # indexer. On Windows a simultaneous race surfaces as a sharing
            # violation, NOT FileExistsError — treat it as contention and retry,
            # never crash. (This is the uncaught-WinError-32 flake.)
            try:
                lock_age = time.time() - float(lf.read_text())
                if lock_age > _STALE_LOCK_SECONDS:
                    # Stale lock from a crashed/killed holder, reclaim it.
                    try:
                        lf.unlink()
                    except (FileNotFoundError, PermissionError):
                        pass
                    continue
            except (ValueError, FileNotFoundError, PermissionError):
                # Corrupted / removed / transiently locked — retry.
                continue

            # Check timeout
            if time.time() - start_time > timeout:
                raise TimeoutError("Could not acquire state file lock")

            time.sleep(0.01)  # Brief wait before retry

    try:
        yield
    finally:
        # Release. On Windows the unlink can transiently fail (WinError 5/32);
        # retry briefly, then leave it — a future acquirer reclaims it once it
        # ages past _STALE_LOCK_SECONDS rather than this crashing on release.
        for _attempt in range(5):
            try:
                lf.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.02)


def in_maintenance(state: dict) -> bool:
    """True when maintenance mode is active — the prose/advisory layer is muted.

    Single source of truth for every "skip the prose coaching" bypass check.
    Honors BOTH historical keys, which mean the same thing:
      - `maintenance_mode`        — the honest name
      - `skip_canon_enforcement`  — the older name (set by the /maintenance
                                    skill and the "turn off canon enforcement"
                                    command); kept for back-compat.

    NOTE: this governs only the advisory layer (phrase reminders, anti-pattern
    logging, the prose observer, soft stop checks). The core canon door-gate
    and the session-startup gate enforce REGARDLESS of maintenance mode.
    """
    if not isinstance(state, dict):
        return False
    return bool(state.get("maintenance_mode") or state.get("skip_canon_enforcement"))


def load_state() -> dict:
    """Load hook state from file with locking.

    Returns default state if file doesn't exist or is corrupted.
    """
    default_state = {
        "canon_verified": False,
        "canon_succeeded": False,
        "session_started": False,
        "context_reminded": False,
        "force_all": False,
        # Intelligent gating fields
        "turn_count": 0,
        "scene_fingerprint": "",
        "scene_changed": True,  # Default to True = assume scene changed
        "skip_canon_enforcement": False,
        # Session type: "gameplay" or "development" — canon enforcement only fires in gameplay
        "session_type": "development",
        # Session vocabulary tracking for anti-repetition (phrases used this session)
        "session_vocabulary": [],
    }

    if not STATE_FILE.exists():
        return default_state

    try:
        content = STATE_FILE.read_text(encoding='utf-8')
        state = json.loads(content)
        # Ensure all expected keys exist
        for key, default in default_state.items():
            if key not in state:
                state[key] = default
        return state
    except (json.JSONDecodeError, IOError):
        return default_state


def save_state(state: dict) -> None:
    """Save hook state to file atomically with locking.

    Uses write-to-temp-then-rename pattern for atomicity.
    """
    temp_file = STATE_FILE.with_suffix('.tmp')

    try:
        # Write to temp file
        temp_file.write_text(json.dumps(state, indent=2), encoding='utf-8')
        # Atomic rename
        temp_file.replace(STATE_FILE)
    except Exception:
        # Clean up temp file if it exists
        try:
            temp_file.unlink()
        except FileNotFoundError:
            pass
        raise


def read_hook_input() -> dict:
    """Read and parse JSON from stdin.

    Raises exception on failure (caught by fail_closed_wrapper).
    """
    if sys.stdin.isatty():
        raise ValueError("No input on stdin")

    raw = sys.stdin.read()
    if not raw.strip():
        raise ValueError("Empty stdin")

    return json.loads(raw)


def set_bell(bell: int) -> None:
    """Update current_bell in hook state."""
    with file_lock():
        state = load_state()
        state["current_bell"] = max(1, min(24, bell))
        save_state(state)


def extract_tool_name(full_name: str) -> str:
    """Extract the base tool name from MCP-prefixed format.

    Claude Code passes tools as 'mcp__<server>__<tool>' but
    TOOL_TAGS uses just '<tool>'.
    """
    if full_name.startswith("mcp__rubicon-seven__"):
        return full_name[len("mcp__rubicon-seven__"):]
    return full_name


# ============================================================
# Topic-key normalization for canon distillation cache
# ============================================================

VALID_TOPIC_SUFFIXES = frozenset({
    "relationship", "event", "history",
    "location", "belief", "policy", "identity",
})

# Process-lifetime cache for the alias map. Loaded lazily on first call to
# _load_alias_map(); subsequent calls return the cached dict (no disk I/O).
_ALIAS_MAP_CACHE = None


def _load_alias_map() -> dict:
    """Build an alias map from npc_states.json. Maps full names to first-word slugs.

    Returns dict: {"amara vane": "amara", "varn look-home": "varn", ...}
    The first word of each name is used as the slug. NPCs with title-prefix names
    (e.g. "Lord Marshall Varn Look-Home") will map to the title word ("lord"),
    which may be undesirable — register such NPCs by their distinctive name in
    npc_states.json for best results.

    Hyphens in slugs are converted to underscores so the alias path produces
    keys consistent with the fallback slug path in _normalize_participant().

    Fail-safe: returns empty dict on any error. Normalization still works without
    aliases — just less aggressive name collapsing. Result is cached at module
    level for process lifetime.
    """
    global _ALIAS_MAP_CACHE
    if _ALIAS_MAP_CACHE is not None:
        return _ALIAS_MAP_CACHE
    aliases: dict = {}
    try:
        # Resolve the campaign dir the same way every other hook does — via
        # RUBICON_CAMPAIGN_DIR — instead of guessing by co-location. (audit 2026-06-16)
        # Fallback when the env var is unset: derive the sibling of the engine repo
        # (this file is <engine>/hooks/hook_utils.py, so parents[2] is the engine's
        # parent) named "rubicon-seven-campaign" — portable, not a hardcoded machine
        # path. The env var is always set in the test suite, so this default never
        # fires there (kept test-neutral on purpose).
        _default_campaign = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"
        campaign_root = Path(os.environ.get("RUBICON_CAMPAIGN_DIR", str(_default_campaign)))
        npc_path = campaign_root / "npc_states.json"
        if not npc_path.exists():
            _ALIAS_MAP_CACHE = aliases
            return aliases
        data = json.loads(npc_path.read_text(encoding="utf-8"))
        for npc in data.get("npcs", {}).values():
            name = npc.get("name", "").strip().lower()
            if not name:
                continue
            # First word of name maps to itself; full name maps to first word.
            # Hyphens become underscores so alias-path output matches fallback-path output.
            first = name.split()[0] if " " in name else name
            first = first.replace("-", "_")
            aliases[name] = first
            aliases[first] = first
    except Exception:
        # Fail open — return whatever we have
        pass
    _ALIAS_MAP_CACHE = aliases
    return aliases


def _normalize_participant(name: str) -> str:
    """Normalize a participant name to its canonical slug form."""
    name = name.strip().lower()
    if not name:
        raise ValueError("Participant name cannot be empty")
    aliases = _load_alias_map()
    # Compound names (e.g., "Brek/AUGUR") — use first component
    if "/" in name:
        name = name.split("/", 1)[0].strip()
    # Apply alias if known, else slug-ify spaces and hyphens
    slug = aliases.get(name, name.replace(" ", "_").replace("-", "_"))
    return slug


def normalize_topic_key(participants: list[str], suffix: str) -> str:
    """Produce a canonical topic key for the distillation cache.

    Args:
        participants: list of participant names (strings)
        suffix: one of VALID_TOPIC_SUFFIXES

    Returns:
        Canonical key string, e.g. "amara_varro_relationship"

    Raises:
        ValueError: if suffix is invalid or participants is empty
    """
    if suffix not in VALID_TOPIC_SUFFIXES:
        raise ValueError(
            f"Invalid suffix '{suffix}'. Must be one of {sorted(VALID_TOPIC_SUFFIXES)}"
        )
    if not participants:
        raise ValueError("participants must contain at least one name")

    normalized = sorted(_normalize_participant(p) for p in participants)
    return "_".join(normalized + [suffix])
