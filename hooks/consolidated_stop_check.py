#!/usr/bin/env python3
"""Consolidated Stop hook: Runs all four stop checks in a single process.

Replaces force_check_canon.py, anti_pattern_check.py, prep_file_check.py,
and backstory_check.py. Reads stdin once, loads state once, short-circuits
on first block. Saves ~20,000 tokens/session in metadata overhead.

Order (cheapest first):
1. Canon enforcement (flag check)
2. Anti-pattern / blacklist scan
3. Prep file progress log check
4. Backstory hallucination scan

SECURITY: Uses fail-closed design via fail_closed_wrapper.
"""

# PEP 563: defer annotation evaluation so PEP 604 unions (str | None) parse on
# Python 3.9 — these hooks run under the system python3, which is 3.9 on a stock macOS.
from __future__ import annotations

import os
import sys
import json
import re
import time
import pickle
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks.hook_utils import (
    fail_closed_wrapper,
    load_state,
    save_state,
    read_hook_input,
    file_lock,
    in_maintenance,
    load_party_names,
    STATE_CHANGING_TOOLS,
    NON_STATE_ACTIONS,
    TOOL_LABELS,
    temp_dir,
    detached_popen_kwargs,
)
from hooks.correction_logger import log_correction
from hooks.analytics_utils import log_catch as _analytics_log_catch
from hooks.lorebook_gate import lorebook_was_called, assistant_turn_is_tool_only
try:
    from hooks.mechanics_source_gate import scan_unbacked_mechanics
except ImportError:  # sibling-import fallback (hooks/ on sys.path directly)
    from mechanics_source_gate import scan_unbacked_mechanics

# ---------------------------------------------------------------------------
# Constants from anti_pattern_check
# ---------------------------------------------------------------------------
BLACKLIST_FILE = Path(__file__).parent / "blacklist.json"
CACHE_FILE = Path(__file__).parent / ".blacklist_cache.pkl"

from rubicon_paths import campaign_dir as _campaign_dir
CAMPAIGN_DIR = _campaign_dir()
# CAMPAIGN-SCOPED canon distillation cache (was engine-relative — cross-campaign privacy leak)
_DEFAULT_CACHE_PATH = CAMPAIGN_DIR / ".canon_distillations.json"

FALLBACK_PHRASES = [
    "goes? still",
    "goes? very still",
    "breath catches",
    "breath hitches",
    "for a long moment",
    "voice quiet",
    "voice soft",
    "voice gentle",
    "stars? wheel(s|ing)? overhead",
    "something shifts",
    "expression softens",
    "the weight of",
    "something in (her|his|their) (voice|eyes)",
    "lets? (that|it) (land|sit)",
    "silence stretches",
]

# ---------------------------------------------------------------------------
# Constants from prep_file_check
# ---------------------------------------------------------------------------
STATUS_FILE = CAMPAIGN_DIR / "CURRENT_STATUS.md"

# STATE_CHANGING_TOOLS, NON_STATE_ACTIONS, TOOL_LABELS imported from hook_utils

# ---------------------------------------------------------------------------
# Constants from backstory_check
# ---------------------------------------------------------------------------
BACKSTORY_PATTERNS = [
    r"(the )?(first time|when) (we|I|you) (met|saw|encountered|found)",
    r"(remember when|do you remember|you remember) (we|I|you)",
    r"(the day|the night|the moment) (we|I|you) (first|met|found)",
    r"(we|I) (used to|always|never) (be|have|do|say|think)",
    # "back when" / "before we" require party pronouns; standalone "years ago"
    # and "long ago" are normal setting description in a dying-earth game.
    r"(back when|before we) (we|I|you|the party)",
    r"(I|we) (once|always|never) (did|said|was|were|had)",
    # Quoted-dialogue patterns removed — dialogue is now stripped before scanning,
    # so these would never match.  Keeping them would be dead code.
    r"(that was|it was) (the|when|how|why) (we|I|you)",
    r"(since|after|before) (that day|we met|I found|you left)",
    r"(how we|when we|where we) (met|started|began|first)",
    r"(our first|my first) (meeting|encounter|time together)",
]

COMPILED_BACKSTORY = [
    re.compile(p, re.IGNORECASE | re.MULTILINE) for p in BACKSTORY_PATTERNS
]


# ===================================================================
# Helper functions (replicated from originals)
# ===================================================================

def _read_scene_type() -> str:
    try:
        content = (CAMPAIGN_DIR / "CURRENT_STATUS.md").read_text(encoding="utf-8")
        match = re.search(r'\*\*Scene Type:\*\*\s*(\S+)', content)
        return match.group(1).strip() if match else "unknown"
    except Exception:
        return "unknown"


def _get_response_text(hook_input: dict) -> str:
    """Extract Claude's response text from hook input."""
    response_text = hook_input.get("last_assistant_message", "")
    if not response_text:
        response_text = hook_input.get("assistant_message", "")
    if not response_text:
        messages = hook_input.get("transcript_messages", [])
        if messages:
            for msg in reversed(messages):
                if msg.get("role") == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        response_text = " ".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    else:
                        response_text = str(content)
                    break
    return response_text


def _get_user_text(hook_input: dict) -> str:
    """Extract THIS turn's human prompt text from hook input.

    Prefers an explicit last_user_message key (tests / legacy callers); falls
    back to the hydrated transcript_messages, scanning for the last role-'user'
    record whose content is real human text (tool_result messages are also
    role-'user' but their content lists carry tool_result blocks, no text).
    Returns '' on any problem (fail-safe — the checker just sees no names)."""
    txt = hook_input.get("last_user_message", "") if isinstance(hook_input, dict) else ""
    if txt:
        return txt
    messages = hook_input.get("transcript_messages", []) if isinstance(hook_input, dict) else []
    if not isinstance(messages, list):
        return ""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", "")
        if isinstance(content, str):
            if content.strip():
                return content
        elif isinstance(content, list):
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = " ".join(p for p in parts if p)
            if joined.strip():
                return joined
    return ""


# ===================================================================
# NPC continuity: open-scene detection (door gate, Task 3)
# ===================================================================

_NPC_FIRSTNAME_STOPWORDS = {"dr", "dr.", "mr", "mr.", "mrs", "ms", "sir", "lord", "lady", "the", "a", "an", "of"}


def detect_open_npcs(turn_text: str, roster: dict) -> set:
    """Return slugs of roster NPCs NAMED in this turn's text.

    roster: {slug: display_name}. WORD-BOUNDARY match on the full name, with a
    first-name fallback (mirrors the check_canon injection trigger). The
    boundary anchors prevent suffix false-positives ('ted' inside 'waited');
    short honorifics/stopwords are skipped so a title-prefixed name like
    'Dr. Mirena Vosh' never opens on a bare 'dr.'."""
    text = turn_text or ""
    hit = set()
    for slug, name in roster.items():
        nm = (name or "").strip()
        if not nm:
            continue
        if re.search(rf"\b{re.escape(nm)}\b", text, re.IGNORECASE):
            hit.add(slug)
            continue
        first = nm.split()[0]
        if len(first) >= 3 and first.lower() not in _NPC_FIRSTNAME_STOPWORDS:
            if re.search(rf"\b{re.escape(first)}\b", text, re.IGNORECASE):
                hit.add(slug)
    return hit


def _check_npc_continuity(state, last_user_text, last_assistant_text):
    """Union roster NPCs named this turn into open_npc_scene. Returns updates dict."""
    try:
        import json as _json, os as _os
        # Behavior-preserving env-gate (identical to main): NPC-continuity stays
        # DORMANT unless RUBICON_CAMPAIGN_DIR is explicitly set. Activating it is a
        # separate owner-approved change, out of scope for path-portability. When
        # the var IS set (sandbox/OSS), resolve portably via the module CAMPAIGN_DIR.
        if not _os.environ.get("RUBICON_CAMPAIGN_DIR"):
            return {}
        f = CAMPAIGN_DIR / "npc_states.json"
        if not f.exists():
            return {}
        data = _json.loads(f.read_text(encoding="utf-8"))
        roster = {slug: rec.get("name", slug) for slug, rec in data.get("npcs", {}).items()}
    except Exception:
        return {}
    named = detect_open_npcs((last_user_text or "") + " " + (last_assistant_text or ""), roster)
    if not named:
        return {}
    open_map = dict(state.get("open_npc_scene", {}))
    for slug in named:
        open_map.setdefault(slug, {"name": roster.get(slug, slug)})
    return {"open_npc_scene": open_map}


# ===================================================================
# Narrative-turn classifier (Task 4 — for prose_observer gating)
# ===================================================================

_MIN_NARRATIVE_CHARS = 300
_TOOL_HEAVY_RATIO = 0.5  # If tool-call blocks > 50% of content blocks, not narrative


def _is_meta_only_response(text: str) -> bool:
    """True when the assistant's ENTIRE output is parenthetical meta.

    Table convention (campaign CLAUDE.md, Intent Parsing): parenthetical =
    out-of-character meta — enforcement Q&A, model questions, check-ins.
    D135 complaint 3: such turns armed the prose gate and forced a junk
    validate call on throwaway text, polluting catch analytics. A turn counts
    as meta-only when every non-empty paragraph is wrapped in parentheses —
    narrative prose never has that shape across ALL paragraphs.
    """
    stripped = (text or "").strip()
    if not stripped:
        return False
    paragraphs = [p.strip() for p in stripped.split("\n\n") if p.strip()]
    return all(p.startswith("(") and p.endswith(")") for p in paragraphs)


def _is_narrative_turn(hook_input: dict, response_text: str, state: dict) -> bool:
    """Decide whether the prose observer should run on this turn.

    Conservative — false-negatives preferred over false-positives.
    The observer is cheap per turn but noisy analytics is costly to
    interpret, so we only run on clearly-narrative turns.

    Returns False in these cases:
    - Maintenance mode (skip_canon_enforcement True)
    - Response under _MIN_NARRATIVE_CHARS chars (after whitespace strip)
    - Last assistant message has more tool-call blocks than text blocks
      (tool-heavy turn — the narration is procedural, not scene-level)
    - Empty / whitespace-only response
    """
    # Maintenance bypass
    if in_maintenance(state):
        return False

    # Session-start bypass — first 4 turns are startup overhead, not narrative
    if state.get("turn_count", 0) <= 3:
        return False

    # Empty or too short
    if not response_text or len(response_text.strip()) < _MIN_NARRATIVE_CHARS:
        return False

    # Entirely-parenthetical output = out-of-character meta, not narration
    if _is_meta_only_response(response_text):
        return False

    # Tool-heavy check: inspect the LAST assistant message's content blocks
    messages = hook_input.get("transcript_messages", [])
    last_assistant = None
    for msg in reversed(messages):
        if msg.get("role") == "assistant":
            last_assistant = msg
            break

    if last_assistant:
        content = last_assistant.get("content", [])
        if isinstance(content, list) and content:
            tool_calls = sum(
                1 for b in content
                if isinstance(b, dict) and b.get("type") == "tool_use"
            )
            text_blocks = sum(
                1 for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            )
            total = tool_calls + text_blocks
            if total > 0 and (tool_calls / total) > _TOOL_HEAVY_RATIO:
                return False

    return True


# ===================================================================
# Observer spawn (Task 5)
# ===================================================================

import subprocess

# Portable temp dir (env RUBICON_TEMP_DIR, else OS temp; "/tmp" on the POSIX
# rig). Module-level so tests can monkeypatch _TEMP_DIR; read at call time below.
_TEMP_DIR = temp_dir()
_OBSERVER_SCRIPT = str(Path(__file__).parent / "prose_observer.py")


def _spawn_observer(response_text: str, session_id: str, turn_id: int,
                    scene_type: str = "unknown") -> None:
    """Spawn the prose observer as a fully detached child process.

    Writes response + metadata to a temp JSON file, then invokes
    prose_observer.py with the file path as argv[1]. The child
    is detached via start_new_session=True so parent can return
    immediately without waiting for observer completion.

    scene_type is read at spawn time (from CURRENT_STATUS) and carried in the
    payload so the observer can stamp semantic catches with the same scene
    dimension the deterministic v1 path records.

    Fail-safe: all exceptions caught and logged; never raises
    back into the hook chain.
    """
    try:
        temp_path = Path(_TEMP_DIR) / f"rubicon_observer_{session_id}_{turn_id}.json"
        payload = {
            "session_id": session_id,
            "turn_id": turn_id,
            "response_text": response_text,
            "scene_type": scene_type,
        }
        temp_path.write_text(json.dumps(payload), encoding="utf-8")

        subprocess.Popen(
            ["python3", _OBSERVER_SCRIPT, str(temp_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **detached_popen_kwargs(),
        )
    except Exception as e:
        try:
            print(f"[stop_hook] observer spawn failed: {e}", file=sys.stderr)
        except Exception:
            pass


def _check_semantic_observer(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check 5: Spawn prose observer on narrative turns (Task 5).

    Always returns (False, "", updates) — observer is advisory, never blocks.
    """
    hook_name = "semantic_observer"

    # Bypass if skip_semantic_observer flag is set (e.g., during maintenance)
    if state.get("skip_semantic_observer", False):
        return False, "", {}

    if not _is_narrative_turn(hook_input, response_text, state):
        return False, "", {}

    session_id = hook_input.get("session_id", "unknown-session")
    turn_id = state.get("turn_count", 0)
    scene_type = _read_scene_type()

    _spawn_observer(response_text, session_id, turn_id, scene_type)

    return False, "", {}


# --- Anti-pattern helpers ---

def _load_blacklist() -> tuple[list[str], list[str]]:
    try:
        data = json.loads(BLACKLIST_FILE.read_text(encoding="utf-8"))
        blacklisted = data.get("blacklisted_phrases", [])
        sparingly = data.get("use_sparingly", [])
        if blacklisted:
            return blacklisted, sparingly
    except (FileNotFoundError, json.JSONDecodeError, IOError):
        pass
    return FALLBACK_PHRASES, []


def _compile_patterns(phrases: list[str]) -> list[tuple[re.Pattern, str]]:
    compiled = []
    for phrase in phrases:
        if any(c in phrase for c in r"\[](){}*+?|^$"):
            pattern = rf"\b{phrase}\b"
        else:
            pattern = rf"\b{re.escape(phrase)}\b"
        try:
            compiled.append((re.compile(pattern, re.IGNORECASE), phrase))
        except re.error:
            continue
    return compiled


def _load_blacklist_cached():
    bl_mtime = BLACKLIST_FILE.stat().st_mtime if BLACKLIST_FILE.exists() else 0
    if CACHE_FILE.exists():
        try:
            cache = pickle.loads(CACHE_FILE.read_bytes())
            if cache.get("mtime") == bl_mtime:
                return cache["blacklist_patterns"], cache["sparingly_patterns"]
        except Exception:
            pass
    blacklisted, sparingly = _load_blacklist()
    bl_patterns = _compile_patterns(blacklisted)
    sp_patterns = _compile_patterns(sparingly)
    try:
        CACHE_FILE.write_bytes(pickle.dumps({
            "mtime": bl_mtime,
            "blacklist_patterns": bl_patterns,
            "sparingly_patterns": sp_patterns,
        }))
    except Exception:
        pass
    return bl_patterns, sp_patterns


def _find_violations(text: str, patterns: list[tuple[re.Pattern, str]]) -> list[str]:
    violations = []
    for pattern, original in patterns:
        for m in pattern.finditer(text):
            violations.append(m.group(0))
    return violations


# --- Prep file helpers ---

def _get_active_prep_file() -> str | None:
    try:
        text = STATUS_FILE.read_text(encoding="utf-8")
    except (FileNotFoundError, IOError):
        return None
    for line in text.splitlines():
        if "**Active Prep:**" in line:
            value = line.split("**Active Prep:**", 1)[1].strip()
            if not value or value.lower() == "none":
                return None
            return value
    return None


def _iter_tool_uses(messages):
    """Yield (tool_name, tool_input) for every assistant tool_use block.

    Shared scanner for all checks that inspect tool calls. Tolerates
    malformed data at every level (non-list messages, non-dict
    messages/blocks) by yielding nothing.
    """
    if not isinstance(messages, list):
        return
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_input = block.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}
            yield block.get("name", ""), tool_input


def _iter_assistant_tool_uses(hook_input):
    """Yield (tool_name, tool_input) from hook_input's in-memory transcript."""
    if not isinstance(hook_input, dict):
        return
    yield from _iter_tool_uses(hook_input.get("transcript_messages", []))


# Reverse tail-read tuning: real session transcripts run to hundreds of MB;
# parsing the whole file per stop costs seconds. The gate only needs the
# LAST turn, so read backwards in blocks and stop at the last human prompt.
_TAIL_BLOCK_BYTES = 2 * 1024 * 1024   # 2MB per backward read
_TAIL_MAX_BYTES = 16 * 1024 * 1024    # give up (fail-open) beyond this


def _is_human_user_message(msg) -> bool:
    """True for a real human prompt; False for mid-turn tool_result returns
    and injected (isMeta) messages.

    In the real transcript, tool results come back as role-"user" messages
    whose content blocks are all tool_result -- those are NOT turn
    boundaries. Neither are isMeta messages (injected, not the player).
    """
    if not isinstance(msg, dict) or msg.get("role") != "user":
        return False
    if msg.get("isMeta"):
        return False
    content = msg.get("content", "")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                continue
            return True
        return False
    return True


def _is_human_boundary_record(rec) -> bool:
    """True if a raw transcript record is a human prompt (turn boundary)."""
    if not isinstance(rec, dict):
        return False
    if rec.get("isMeta"):
        return False
    msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
    return _is_human_user_message(msg)


def _tail_lines_to_last_human(transcript_path,
                              block_bytes=_TAIL_BLOCK_BYTES,
                              max_bytes=_TAIL_MAX_BYTES) -> list:
    """Read the transcript JSONL backwards in blocks; return decoded lines
    from the LAST human user record through EOF.

    Never parses the whole file; each line is examined at most once.
    Returns all lines if beginning-of-file is reached within the cap, and
    [] (fail-open: the gate sees no tool uses and passes) if no human
    boundary is found within max_bytes. Returns [] on any error.
    """
    def _decode(lines_bytes):
        return [lb.decode("utf-8", "replace") for lb in lines_bytes]

    def _is_human_line(line_bytes):
        line = line_bytes.strip()
        if not line:
            return False
        try:
            rec = json.loads(line.decode("utf-8", "replace"))
        except Exception:
            return False
        return _is_human_boundary_record(rec)

    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            read_total = 0
            leftover = b""
            collected = []  # decoded lines after the current scan position
            while pos > 0 and read_total < max_bytes:
                step = min(block_bytes, pos, max_bytes - read_total)
                pos -= step
                f.seek(pos)
                data = f.read(step) + leftover
                read_total += step
                lines = data.split(b"\n")
                if pos > 0:
                    # First element may be a partial line continuing earlier
                    # in the file -- defer it to the next block.
                    leftover = lines[0]
                    lines = lines[1:]
                else:
                    leftover = b""
                for i in range(len(lines) - 1, -1, -1):
                    if _is_human_line(lines[i]):
                        return _decode(lines[i:]) + collected
                collected = _decode(lines) + collected
            if pos == 0:
                return collected  # whole (small) file read, no boundary
            return []  # cap exhausted without a boundary: fail-open
    except Exception:
        return []


def _normalize_transcript_records(raw_records) -> list:
    """Normalize raw transcript records to message dicts.

    Unwraps the JSONL {"type": ..., "message": {...}} envelope, skips
    isMeta-injected records, keeps only user/assistant messages.
    """
    messages = []
    if not isinstance(raw_records, list):
        return messages
    for rec in raw_records:
        if not isinstance(rec, dict):
            continue
        if rec.get("isMeta"):
            continue
        msg = rec.get("message") if isinstance(rec.get("message"), dict) else rec
        if isinstance(msg, dict) and msg.get("role") in ("user", "assistant"):
            messages.append(msg)
    return messages


def _load_transcript_file_messages(transcript_path) -> list:
    """Load normalized messages for the LAST TURN from transcript_path.

    Real Claude Code Stop-hook stdin carries transcript_path pointing at a
    JSONL file (one record per line, each wrapping the message as
    {"type": ..., "message": {"role": ..., "content": [...]}}). Reads the
    file tail backwards (_tail_lines_to_last_human) instead of parsing the
    whole transcript. Small single-JSON-document transcripts (a list of
    messages, or a dict with a "messages"/"conversation" list) are
    tolerated as a fallback -- same tolerances as verify_save's transcript
    handling. Returns [] on any problem.
    """
    records = []
    for line in _tail_lines_to_last_human(transcript_path):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not any(isinstance(r, dict) for r in records):
        # Fallback: a small transcript may be one JSON document, not JSONL
        # (a one-line JSON list parses above as a single non-dict record).
        try:
            path = Path(transcript_path)
            if path.stat().st_size > _TAIL_MAX_BYTES:
                return []
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(doc, list):
            records = doc
        elif isinstance(doc, dict):
            records = doc.get("messages", doc.get("conversation", []))

    return _normalize_transcript_records(records)


def _get_turn_messages(hook_input) -> list:
    """Messages for THIS TURN ONLY: everything after the last human prompt.

    Prefers the in-memory transcript_messages shape (tests / legacy callers);
    falls back to parsing the JSONL at hook_input["transcript_path"] (real
    Stop-hook stdin). Returns [] on any problem.
    """
    if not isinstance(hook_input, dict):
        return []
    messages = hook_input.get("transcript_messages")
    # A missing, non-list, or EMPTY in-memory transcript all fall back to
    # the on-disk transcript (real Stop-hook stdin provides only the path).
    if not isinstance(messages, list) or not messages:
        messages = []
        transcript_path = hook_input.get("transcript_path", "")
        if isinstance(transcript_path, str) and transcript_path:
            messages = _load_transcript_file_messages(transcript_path)

    last_human = -1
    for i, msg in enumerate(messages):
        if _is_human_user_message(msg):
            last_human = i
    return messages[last_human + 1:]


def _hydrate_transcript_messages(hook_input) -> None:
    """Make the legacy in-memory readers work on real Stop-hook stdin.

    Real stdin provides only transcript_path; every check that reads
    hook_input["transcript_messages"] directly would silently see [] live.
    Populate that key once with THIS TURN's messages so the soft checks and
    the response-text fallback all share one tail-read (and the dm-design
    gate's own _get_turn_messages call reuses it instead of re-reading).

    A caller-provided non-empty transcript_messages (tests / legacy) is
    left untouched. Fail-open: on any problem the key stays absent and the
    checks see no messages, exactly as before.
    """
    if not isinstance(hook_input, dict):
        return
    if hook_input.get("transcript_messages"):
        return
    turn_messages = _get_turn_messages(hook_input)
    if turn_messages:
        hook_input["transcript_messages"] = turn_messages


def _check_state_changing_tools_called(hook_input: dict) -> list[str]:
    tools_called = []
    for tool_name, tool_input in _iter_assistant_tool_uses(hook_input):
        if tool_name in STATE_CHANGING_TOOLS:
            action = tool_input.get("action", "")
            exempt_actions = NON_STATE_ACTIONS.get(tool_name, set())
            if action and action in exempt_actions:
                continue
            tools_called.append(tool_name)
    return tools_called


def _check_prep_file_edited(hook_input: dict, prep_filename: str) -> bool:
    prep_lower = prep_filename.lower()
    for tool_name, tool_input in _iter_assistant_tool_uses(hook_input):
        if tool_name == "Edit":
            if prep_lower in tool_input.get("file_path", "").lower():
                return True
        if tool_name == "mcp__rubicon-seven__edit_file":
            if prep_lower in tool_input.get("filename", "").lower():
                return True
        if tool_name == "mcp__rubicon-seven__update_location_progress":
            if prep_lower in tool_input.get("location", "").lower():
                return True
    return False


# --- Backstory helpers ---

# Regex to strip content that should NOT be scanned for backstory claims:
#   - Quoted dialogue: "..."  (NPC speech containing past-tense verbs is not a claim)
#   - Italicized bond text: *...*  (telepathic communication, not narrator backstory)
_DIALOGUE_OR_BOND_RE = re.compile(
    r'"[^"]*"'          # double-quoted dialogue
    r"|"
    r"\*[^*]+\*",       # italicized bond/telepathy text
    re.DOTALL,
)

# Minimum match length to consider a backstory claim real.
# Short fragments like "I once had" are almost always conversational, not
# narrator-voice backstory fabrication.  Real hallucinations tend to be
# full clauses: "the first time we met at Sandwhisper Station" (40+ chars).
_MIN_CLAIM_LENGTH = 20


def _strip_dialogue_and_bond(text: str) -> str:
    """Remove quoted dialogue and italicized bond text before scanning."""
    return _DIALOGUE_OR_BOND_RE.sub("", text)


def _has_backstory_claims(text: str) -> list[str]:
    # Strip dialogue and bond communication first — content inside quotes
    # or italics is character speech, not narrator backstory claims.
    cleaned = _strip_dialogue_and_bond(text)
    matches = []
    for pattern in COMPILED_BACKSTORY:
        for match in pattern.finditer(cleaned):
            snippet = match.group(0)
            # Skip very short matches — they're conversational fragments,
            # not real backstory fabrication.
            if len(snippet) < _MIN_CLAIM_LENGTH:
                continue
            matches.append(snippet[:80])
    return matches


def _check_canon_was_called(hook_input: dict, state: dict) -> bool:
    if state.get("canon_verified", False) and state.get("canon_succeeded", False):
        return True
    messages = hook_input.get("transcript_messages", [])
    for msg in messages:
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        if "check_canon" in block.get("name", ""):
                            return True
    return False


# ===================================================================
# Individual check functions — return (block: bool, reason: str, hook_name: str, state_updates: dict)
# ===================================================================

def _check_canon(hook_input: dict, state: dict) -> tuple[bool, str, dict]:
    """Check 1: Canon enforcement (from force_check_canon.py)."""
    hook_name = "force_check_canon"

    if in_maintenance(state):
        return False, "", {}

    if state.get("session_type", "development") != "gameplay":
        return False, "", {}

    # If canon is not required this turn (skip turn), pass without blocking
    if not state.get("canon_required", True):
        return False, "", {}

    if not state.get("canon_verified", False):
        reason = (
            "CANON NOT VERIFIED. Response delivered without check_canon on a required turn."
        )
        log_correction(
            hook_name="force_check_canon",
            caught_text="Response without check_canon",
            reason_given=reason,
            severity="soft",
        )
        # Log silently — do NOT block. Same approach as anti-pattern check.
        # Claude sees the miss logged and self-corrects on subsequent turns.
        # Blocking causes visible rewrite-cycle artifacts that break immersion.
        return False, "", {}

    return False, "", {}


def _basename_of(path: str) -> str:
    """Basename of a path, tolerant of Windows separators."""
    return path.replace("\\", "/").rstrip("/").split("/")[-1]


# Prep-file tokens inside the Active Prep status value. The live status line
# is annotated free text (e.g. "CERULINE_ARCOLOGY_PREP.md (forward base =
# ...); PLANEYFOLK_CONTACT_PREP / _TRUTH for ...") and may name preps as
# bare stems without .md — extract every token rather than treating the
# whole value as one filename.
_PREP_TOKEN_RE = re.compile(r"[\w-]+_PREP(?:\.md)?\b", re.IGNORECASE)


def _active_prep_tokens(active_value) -> set:
    """Lowercase set of prep STEMS (no .md) named in the Active Prep value."""
    if not isinstance(active_value, str) or not active_value:
        return set()
    tokens = set()
    for match in _PREP_TOKEN_RE.findall(active_value):
        stem = match.lower()
        if stem.endswith(".md"):
            stem = stem[: -len(".md")]
        tokens.add(stem)
    return tokens


def _find_prep_write_this_turn(turn_messages, active_prep_tokens):
    """Return the basename of a *_PREP.md file FORGED this turn, or None.

    Covers the same write surface as _check_prep_file_edited: native
    Write/Edit (file_path) and the MCP file tools (filename).

    Trigger rule (active-prep exemption):
    - Write to any *_PREP.md arms -- creating/overwriting a prep is
      forging-scale change, even on the active prep.
    - Edit-family tools (Edit, edit_file [replace/overwrite]) arm ONLY if
      the target matches NONE of the Active Prep tokens -- _check_prep_file
      nudges a progress-log edit to the active prep every state-changing
      turn, and that routine edit must never arm the gate. If the active
      prep cannot be resolved (empty token set), edit-family does NOT arm
      (only Write does), so an unreadable status file cannot recreate that
      false positive.
    """
    if not isinstance(active_prep_tokens, set):
        active_prep_tokens = set()
    for tool_name, tool_input in _iter_tool_uses(turn_messages):
        if tool_name == "Write":
            raw = tool_input.get("file_path", "")
            edit_family = False
        elif tool_name == "Edit":
            raw = tool_input.get("file_path", "")
            edit_family = True
        elif tool_name == "mcp__rubicon-seven__edit_file":
            raw = tool_input.get("filename", "")
            edit_family = True
        else:
            continue
        if not isinstance(raw, str) or not raw:
            continue
        basename = _basename_of(raw)
        if not basename.lower().endswith("_prep.md"):
            continue
        if edit_family:
            if not active_prep_tokens:
                continue  # active prep unknown: only Write arms
            stem = basename.lower()[: -len(".md")]
            if stem in active_prep_tokens:
                continue  # routine progress-log edit to an active prep
        return basename
    return None


def _dm_design_dispatched_this_turn(turn_messages) -> bool:
    """True if an Agent/Task dispatch this turn targets the dm-design pass.

    DESCRIPTION-only match (the skill dispatches description "DM narrative
    design agent"; slash dispatches say "dm-design ..."). Prompt text is
    deliberately NOT scanned — a stray mention inside a long prompt must
    not open the gate.
    """
    for tool_name, tool_input in _iter_tool_uses(turn_messages):
        if tool_name not in ("Agent", "Task"):
            continue
        description = str(tool_input.get("description", "")).lower()
        if "dm-design" in description or "dm narrative design" in description:
            return True
    return False


def _check_dm_design_gate(hook_input: dict, state: dict) -> tuple[bool, str, dict]:
    """Check 1b: dm-design review gate -- the one BLOCKING check in this runner.

    Forging a *_PREP.md file this turn arms state["pending_dm_design"]; the
    stop is then blocked (same turn or any later turn) until a dm-design
    Agent/Task dispatch releases it or the player waives it via
    state["skip_dm_design_gate"].

    Precedence per evaluation: bypass (maintenance, keeps pending) >
    release > skip > trigger/block.

    Fail-silent: any internal error passes without blocking -- this check
    must never crash the runner or strand a live session.
    """
    hook_name = "dm_design_gate"
    try:
        # 1. Bypass -- dm-design itself runs under maintenance_mode and writes
        #    prep files; the gate must not self-trigger. Pass WITHOUT clearing
        #    pending: the review obligation survives maintenance work.
        if in_maintenance(state):
            return False, "", {}

        # Scope all tool-use scanning to THIS TURN ONLY (messages after the
        # last human prompt), whether the transcript arrived in-memory or
        # via transcript_path JSONL.
        turn_messages = _get_turn_messages(hook_input)

        # 2. Release -- the dm-design review pass was dispatched this turn.
        if _dm_design_dispatched_this_turn(turn_messages):
            if state.get("pending_dm_design"):
                return False, "", {"pending_dm_design": None}
            return False, "", {}

        # 3. Skip -- player said "skip review"; waive and clear the flag.
        if state.get("skip_dm_design_gate"):
            return False, "", {
                "pending_dm_design": None,
                "skip_dm_design_gate": False,
            }

        # 4. Trigger -- a prep file was forged this turn: arm (or re-arm).
        #    Routine progress-log edits to the ACTIVE prep are exempt (see
        #    _find_prep_write_this_turn); resolve the active prep the same
        #    way _check_prep_file does, then extract every prep token from
        #    the annotated status value.
        updates: dict = {}
        pending = state.get("pending_dm_design")
        active_tokens = _active_prep_tokens(_get_active_prep_file())
        prep_file = _find_prep_write_this_turn(turn_messages, active_tokens)
        if prep_file:
            pending = {
                "file": prep_file,
                "set_turn": state.get("turn_count", 0),
            }
            updates["pending_dm_design"] = pending

        # Block -- pending exists (from this turn or an earlier one).
        if not isinstance(pending, dict) or not pending:
            return False, "", updates

        fname = pending.get("file", "unknown")
        reason = (
            f"CONTENT FORGED, REVIEW PENDING: {fname} has not passed the "
            f"dm-design gate. NEXT: /dm-design integrate {fname}  "
            f'(or say "skip review" to waive - discovery content may not '
            f"need the gate)"
        )
        try:
            log_correction(
                hook_name=hook_name,
                caught_text=fname,
                reason_given=reason,
                severity="hard",
            )
        except Exception:
            pass
        return True, reason, updates
    except Exception as e:
        # Fail-silent: never crash the runner -- but leave a telemetry
        # breadcrumb (same log file the prose observer uses).
        try:
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
            error_log = Path(__file__).parent / "observer_errors.log"
            with error_log.open("a", encoding="utf-8") as f:
                f.write(f"{timestamp}  dm_design_gate: {type(e).__name__}: {e}\n")
        except Exception:
            pass
        return False, "", {}


_PROSE_WINDOW_CAP = 200


def _append_prose_window(text: str) -> None:
    """Append a narration turn to the campaign-scoped rolling prose window
    (rubicon_paths.prose_window_path), keeping the newest _PROSE_WINDOW_CAP
    entries. Source corpus for the evolver's template-nomination scan."""
    try:
        from rubicon_paths import prose_window_path
    except ImportError:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from rubicon_paths import prose_window_path
    path = prose_window_path()
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    lines.append(json.dumps({"text": text}, ensure_ascii=False))
    if len(lines) > _PROSE_WINDOW_CAP:
        lines = lines[-_PROSE_WINDOW_CAP:]
    tmp = path.with_suffix(".jsonl.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def _check_anti_pattern(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check 2: Anti-pattern / blacklist scan (soft logger — validate_prose is the real gate)."""
    hook_name = "anti_pattern_check"

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    if not response_text:
        return False, "", {}

    # Meta-only turns (every paragraph parenthetical) are not narration:
    # don't arm the prose gate, don't scan, don't feed the template corpus.
    # (D135 complaint 3 — armed gates on meta answers forced junk validate
    # calls; scanning meta text about bans would also log phantom catches.)
    if _is_meta_only_response(response_text):
        return False, "", {}

    # Rolling narration window (template-nomination corpus, 2026-07-19):
    # substantial gameplay turns are appended to a capped campaign-scoped
    # JSONL the evolver's template scan reads at save-commit. Fail-open.
    if len(response_text) > 200 and state.get("session_type") == "gameplay":
        try:
            _append_prose_window(response_text)
        except Exception:
            pass

    # Log warning if validate_prose was not called for gameplay narrative.
    # 2026-07-19 fix (Thyricost leak audit): this used to EARLY-RETURN, which
    # switched the deterministic blacklist scan OFF on exactly the turns that
    # skipped self-validation — 27 hard-banned phrases reached live narration.
    # Now it only arms the flag and falls through; the scan runs regardless.
    _vp_extra = {}
    if (not state.get("validate_prose_called", False)
            and len(response_text) > 200
            and state.get("session_type") == "gameplay"):
        log_correction(
            hook_name="validate_prose_gate",
            caught_text="",
            reason_given="Narrative output without validate_prose call",
            severity="warning",
        )
        _vp_extra["validate_prose_required"] = True

    blacklist_patterns, sparingly_patterns = _load_blacklist_cached()

    # Hard blacklist
    violations = _find_violations(response_text, blacklist_patterns)
    if violations:
        unique = list(set(violations))
        phrase_list = ", ".join(f'"{v}"' for v in unique[:5])

        catch_count = state.get("catch_count", 0) + 1
        catch_log = dict(state.get("catch_log", {}))
        for v in unique:
            key = v.lower()
            catch_log[key] = catch_log.get(key, 0) + 1

        top_offenders = sorted(catch_log.items(), key=lambda x: x[1], reverse=True)[:5]
        offender_str = ", ".join(f'"{k}" (x{v})' for k, v in top_offenders)

        verbose_reason = (
            f"ANTI-PATTERN (catch #{catch_count} this session): {phrase_list}. "
            f"Repeat offenders: {offender_str}."
        )

        log_correction(
            hook_name="anti_pattern_check",
            caught_text=phrase_list,
            reason_given=verbose_reason,
            severity="soft",
        )

        try:
            scene_type = _read_scene_type()
            turn_count = state.get("turn_count", 0)
            for v in unique:
                _analytics_log_catch(v, scene_type, catch_count, turn_count)
        except Exception:
            pass

        updates = {
            "catch_count": catch_count,
            "catch_log": catch_log,
        }

        # Soft log — validate_prose is the pre-output gate. This logs for session-end review.
        return False, "", {**updates, **_vp_extra}

    # Use-sparingly phrases
    if sparingly_patterns:
        sparingly_hits = _find_violations(response_text, sparingly_patterns)
        if sparingly_hits:
            session_vocab = list(state.get("session_vocabulary", []))
            repeated = [h for h in sparingly_hits if h.lower() in [v.lower() for v in session_vocab]]

            if repeated:
                unique_repeated = list(set(repeated))
                phrase_list = ", ".join(f'"{v}"' for v in unique_repeated[:5])

                catch_count = state.get("catch_count", 0) + 1
                catch_log = dict(state.get("catch_log", {}))
                for v in unique_repeated:
                    key = v.lower()
                    catch_log[key] = catch_log.get(key, 0) + 1

                top_offenders = sorted(catch_log.items(), key=lambda x: x[1], reverse=True)[:5]
                offender_str = ", ".join(f'"{k}" (x{v})' for k, v in top_offenders)

                verbose_reason = (
                    f"OVERUSED PHRASE (catch #{catch_count} this session): {phrase_list} (already used). "
                    f"Repeat offenders: {offender_str}."
                )

                log_correction(
                    hook_name="anti_pattern_check",
                    caught_text=phrase_list,
                    reason_given=verbose_reason,
                    severity="soft",
                )

                try:
                    scene_type = _read_scene_type()
                    turn_count = state.get("turn_count", 0)
                    for v in unique_repeated:
                        _analytics_log_catch(v, scene_type, catch_count, turn_count)
                except Exception:
                    pass

                updates = {
                    "catch_count": catch_count,
                    "catch_log": catch_log,
                }

                # Soft log — validate_prose is the pre-output gate. This logs for session-end review.
                return False, "", {**updates, **_vp_extra}

            # Not repeated — record in session vocabulary
            for hit in sparingly_hits:
                if hit.lower() not in [v.lower() for v in session_vocab]:
                    session_vocab.append(hit)
            # Pass vocab update through state updates
            return False, "", {"session_vocabulary": session_vocab, **_vp_extra}

    # All clear
    return False, "", dict(_vp_extra)


def _check_prep_file(hook_input: dict, state: dict) -> tuple[bool, str, dict]:
    """Check 3: Prep file progress log (from prep_file_check.py)."""
    hook_name = "prep_file_check"

    prep_filename = _get_active_prep_file()
    if not prep_filename:
        return False, "", {}

    tools_called = _check_state_changing_tools_called(hook_input)
    if not tools_called:
        return False, "", {}

    if _check_prep_file_edited(hook_input, prep_filename):
        return False, "", {}

    # Soft log — prep file not edited despite state-changing tools
    unique_tools = list(set(tools_called))
    labels = [TOOL_LABELS.get(t, t.split("__")[-1]) for t in unique_tools]
    change_list = ", ".join(labels)

    reason = (
        f"State-changing tools used ({change_list}). "
        f"Edit {prep_filename} PROGRESS LOG before delivery."
    )

    log_correction(
        hook_name="prep_file_check",
        caught_text=change_list,
        reason_given=reason,
        severity="soft",
    )
    return False, "", {}


def _check_lorebook(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check: lorebook gate.

    Hard-blocks when:
      - turn_reset flagged lorebook_required (user input contained lorebook keywords)
      - AND no lorebook(view, ...) call fired this turn
      - AND the turn produced narrative text (not tool-only)
      - AND not in maintenance mode / not a rewrite turn we already blocked

    On block, returns a short reason naming up to 3 triggers and instructing
    a lorebook(view, <kw>) call before re-delivery.
    """
    hook_name = "lorebook_check"

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    # Not required this turn — pass
    if not state.get("lorebook_required", False):
        return False, "", {}

    # If the turn was tool-only (no narrative text), nothing to gate yet — pass
    if assistant_turn_is_tool_only(hook_input):
        return False, "", {}

    # If lorebook was actually called this turn — pass
    if lorebook_was_called(hook_input):
        return False, "", {"lorebook_called": True}

    # Soft pass — log the gap for DM self-correction but do not block delivery
    triggers = state.get("lorebook_triggers", []) or []
    trig_str = ", ".join(triggers[:3]) if triggers else "lore-bearing entity"
    primary = triggers[0] if triggers else "<keyword>"
    reason = (
        f"LOREBOOK GAP (soft): {trig_str}. "
        f"lorebook(view, '{primary}') was not called this turn."
    )

    log_correction(
        hook_name="lorebook_check",
        caught_text=trig_str,
        reason_given=reason,
        severity="soft",
    )

    return False, "", {}


def _check_backstory(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check 4: Backstory hallucination scan (from backstory_check.py)."""
    hook_name = "backstory_check"

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    if not response_text:
        return False, "", {}

    claims = _has_backstory_claims(response_text)
    if not claims:
        return False, "", {}

    # Claims found — check if canon was verified
    if _check_canon_was_called(hook_input, state):
        return False, "", {}

    # Soft log only — validate_prose is the primary gate.
    claim_preview = claims[0][:60] if claims else "unknown"
    reason = (
        f"BACKSTORY HALLUCINATION: Unverified backstory claim detected. "
        f"Previous response visible. Call check_canon, then correct claim briefly. "
        f"Reference MASTER_CONTINUITY_ORIGINS.md if needed."
    )

    log_correction(
        hook_name="backstory_check",
        caught_text=claim_preview,
        reason_given=reason,
        severity="soft",
    )

    return False, "", {}


def _load_party_names() -> set:
    """Party-member names to never flag as fabrication, read from the LIVE
    character roster rather than a hardcoded personal-campaign list.

    Delegates to the shared hook_utils.load_party_names loader (one home,
    no drifted copies) — same split-sheet/monolithic-fallback/fail-open
    contract, resolved via the module CAMPAIGN_DIR.
    """
    return load_party_names(CAMPAIGN_DIR)


def _check_npc_fabrication(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check 5b: NPC mentioned in narrative without verification.

    Soft-blocks when an NPC name appears in narrative text (excluding dialogue
    and bond/italic text) but was not covered by check_canon injection or a
    lorebook/npc tool call this turn.

    Prevents fabricated NPC history from reaching the player.
    """
    hook_name = "npc_fabrication_check"

    # Skip short responses (not narrative turns)
    if len(response_text) < 100:
        return False, "", {}

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    # Skip non-gameplay sessions
    if state.get("session_type", "development") != "gameplay":
        return False, "", {}

    # Skip non-narrative responses (meta discussion, technical explanations, tool summaries)
    # Narrative prose uses second-person ("you"), scene verbs, and NPC dialogue in quotes.
    # Meta responses discuss implementation, use "the hook", "server.py", "check_canon", etc.
    meta_signals = ["server.py", "check_canon", "lorebook(", "hook", "MCP", "implement",
                    "Phase ", "token", "caching", "inject", "function", "middleware"]
    meta_count = sum(1 for signal in meta_signals if signal in response_text)
    has_narrative_markers = ("What do you do?" in response_text or
                            "\nyou " in response_text.lower() or
                            "\nYour " in response_text or
                            '"' in response_text[:500])
    if meta_count >= 2 and not has_narrative_markers:
        return False, "", {}

    # Load NPC names from npc_states.json
    npc_path = CAMPAIGN_DIR / "npc_states.json"
    if not npc_path.exists():
        return False, "", {}

    try:
        npc_data = json.loads(npc_path.read_text(encoding="utf-8"))
    except Exception:
        return False, "", {}

    # Build name set from npc_states keys
    npc_names = set()
    for npc_id, npc in npc_data.get("npcs", {}).items():
        name = npc.get("name", "")
        if name and len(name) > 2:
            npc_names.add(name)

    # Party characters are always covered — never flag these. Read from the live
    # roster (not a hardcoded personal-campaign list) so it tracks the current
    # party and doesn't leak owner names / mis-flag another deployment's party.
    party_names = _load_party_names()

    # Present characters from CURRENT_STATUS.md are scene-verified
    present_npcs = set()
    try:
        status_path = CAMPAIGN_DIR / "CURRENT_STATUS.md"
        if status_path.exists():
            for line in status_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("**Present:**"):
                    names_part = line.replace("**Present:**", "").strip()
                    for n in names_part.split(","):
                        n = n.strip()
                        if n:
                            present_npcs.add(n)
                    break
    except Exception:
        pass

    # Get NPCs covered by check_canon injection (written by server.py hop injection)
    injected_npcs = set(state.get("injected_npcs", []))

    # Get NPCs verified via gate_check state tracking (survives stop hook retries)
    state_verified_npcs = set(state.get("verified_npcs", []))

    # Get NPCs targeted by tool calls this turn
    tool_targeted_npcs = set()
    messages = hook_input.get("transcript_messages", [])
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_name = block.get("name", "")
            tool_input = block.get("input", {})
            if not isinstance(tool_input, dict):
                tool_input = {}
            # lorebook(view, keyword) — keyword is the NPC name
            if "lorebook" in tool_name:
                kw = tool_input.get("keyword", "")
                if kw:
                    tool_targeted_npcs.add(kw.lower())
            # npc(get/set, name) — name is the NPC name
            elif "npc" in tool_name:
                name = tool_input.get("name", "")
                if name:
                    tool_targeted_npcs.add(name.lower())
            # check_canon covers present characters via injected_npcs state
            elif "check_canon" in tool_name:
                pass

    # Strip dialogue and bond text — reuse existing helper
    stripped = _strip_dialogue_and_bond(response_text)

    # Common English words that are also NPC names (false positive filter)
    false_positive_filter = {
        "quill", "sage", "veil", "grace", "dawn", "ash", "ember",
        "oracle", "anchor", "reed", "mason", "hunter", "herald",
    }

    # Check each NPC name against stripped narrative
    unverified_mentions = []
    for name in npc_names:
        if name in party_names:
            continue
        name_lower = name.lower()
        if name_lower in false_positive_filter:
            continue

        # Word boundary search in stripped narrative
        if re.search(rf"\b{re.escape(name)}\b", stripped, re.IGNORECASE):
            # Check if covered by injection, tool call, or scene presence
            is_covered = False
            # Present in current scene (from CURRENT_STATUS.md)
            if name in present_npcs or any(name.lower() in n.lower() for n in present_npcs):
                is_covered = True
            # Covered by check_canon hop injection
            elif name_lower in {n.lower() for n in injected_npcs}:
                is_covered = True
            elif any(name_lower in n.lower() for n in injected_npcs):
                is_covered = True
            # Covered by lorebook/npc tool call this turn
            elif name_lower in tool_targeted_npcs:
                is_covered = True
            # NPC name contains a targeted keyword (e.g. "amara" covers "Amara Vane")
            elif any(t in name_lower for t in tool_targeted_npcs):
                is_covered = True
            # Targeted keyword contains NPC name (e.g. "amara vane" covers "Amara")
            elif any(name_lower in t for t in tool_targeted_npcs):
                is_covered = True

            # Covered by state-tracked verification (gate_check records these)
            if not is_covered:
                if name_lower in state_verified_npcs:
                    is_covered = True
                elif any(t in name_lower for t in state_verified_npcs):
                    is_covered = True
                elif any(name_lower in t for t in state_verified_npcs):
                    is_covered = True

            if not is_covered:
                unverified_mentions.append(name)

    if unverified_mentions:
        names_str = ", ".join(unverified_mentions[:3])
        primary = unverified_mentions[0]
        reason = (
            f"NPC FABRICATION RISK: {names_str} mentioned in narrative without verification. "
            f"Call lorebook(view, \"{primary.lower()}\") or npc(get, \"{primary}\") "
            f"before writing about this character."
        )

        log_correction(
            hook_name="npc_fabrication_check",
            caught_text=names_str,
            reason_given=reason,
            severity="soft",
        )

        # Soft log only — validate_prose is the primary gate.
        return False, "", {}

    # All clear
    return False, "", {}


def _get_map_current_turn(map_name: str) -> int | None:
    """Read current_turn from maps/<map_name>_map.json (the model-independent ground truth).

    Returns None if the file doesn't exist or can't be parsed.
    Deliberately reads from disk every call — the hook and MCP server are separate
    processes; in-memory GAME_STATE is NOT accessible here.
    """
    map_path = CAMPAIGN_DIR / "maps" / f"{map_name}_map.json"
    try:
        data = json.loads(map_path.read_text(encoding="utf-8"))
        return data.get("current_turn")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Task D3: Settlement change reflex nag (pure helper + runner check)
# ---------------------------------------------------------------------------

_SETTLEMENT_CHANGE_CUES = re.compile(
    r'\b(dead|dies|killed|slain|burns?\s+down|destroyed|flees|leaves\s+for\s+good|'
    r'now\s+hostile|turns\s+on\s+the\s+party|banished|exiled)\b',
    re.IGNORECASE,
)


def settlement_change_unstamped(transcript_text: str, tool_calls_this_turn) -> bool:
    """True if the turn narrates a material settlement change but wrote no progress stamp.

    Pure helper — unit-testable without any hook machinery.

    Args:
        transcript_text: The assistant's narrative text for this turn.
        tool_calls_this_turn: List/iterable of tool name strings called this turn.

    Returns True iff a settlement-change cue is present AND
    'update_location_progress' is NOT in tool_calls_this_turn.
    """
    if not _SETTLEMENT_CHANGE_CUES.search(transcript_text or ""):
        return False
    return "update_location_progress" not in (tool_calls_this_turn or [])


def _check_settlement_change_nag(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Advisory: nag when a settlement change was narrated but not stamped this turn.

    NEVER blocks (returns False). Appends a reflex advisory line to stdout so
    Claude sees it as a reminder without triggering a rewrite cycle.
    The advisory is printed directly here; the runner sees no block reason.
    """
    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    if not response_text:
        return False, "", {}

    # Collect tool names called this turn
    tool_names = [name for name, _ in _iter_assistant_tool_uses(hook_input)]

    if settlement_change_unstamped(response_text, tool_names):
        print(
            "⚙ A settlement change was narrated but not recorded — "
            "stamp it: update_location_progress(location=..., summary=..., status=[...])"
        )

    # Always non-blocking — never return True
    return False, "", {}


# ---------------------------------------------------------------------------
# Settlement v1 follow-on: session-end Ceruline reconcile nudge (non-blocking)
# ---------------------------------------------------------------------------

_SESSION_END_TOOLS = {"save_state", "prepare_save_state", "distill_session"}


def ceruline_session_change(transcript_text, tool_calls_this_turn, seen_flag) -> bool:
    """True iff this is a session-end turn AND Ceruline came up this session.

    seen_flag is the persisted 'ceruline mentioned earlier this session' state.
    Pure/unit-testable. The caller persists the flag and clears it on fire.
    """
    seen = bool(seen_flag) or ("ceruline" in (transcript_text or "").lower())
    ending = any(t in _SESSION_END_TOOLS for t in (tool_calls_this_turn or []))
    return bool(seen and ending)


def _check_ceruline_reconcile_nudge(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Advisory: at session-end, if Ceruline came up this session, nudge a reference-file
    reconcile. NEVER blocks. One line. Honors the maintenance bypass.

    State persistence note: main() does NOT persist in-place mutations of `state`; it
    merges each check's returned third-tuple dict into all_updates and writes that. So
    the ceruline_seen_session flag is carried via the returned `updates` dict (matching
    _check_vault_liveness / _check_npc_continuity), not by mutating `state` in place.
    """
    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    tool_names = [name for name, _ in _iter_assistant_tool_uses(hook_input)]
    seen = state.get("ceruline_seen_session", False)

    updates = {}
    if not seen and "ceruline" in (response_text or "").lower():
        seen = True
        updates["ceruline_seen_session"] = True

    if ceruline_session_change(response_text, tool_names, seen):
        print(
            "⟳ Ceruline came up this session — update CERULINE_PLAYER_REFERENCE.md if "
            "people moved/died/stance shifted (the who's-around reader reads it live)."
        )
        updates["ceruline_seen_session"] = False

    # Always non-blocking — never return True.
    return False, "", updates


def _check_vault_liveness(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check: vault-liveness gate.

    While vault_enforce is armed, every narrative turn MUST advance the armed
    map's current_turn past vault_enforce.last_turn. The only satisfying signal
    is map(enter|search|wait) — all of which call advance_turns() + save_map_state().

    On a satisfying turn: update vault_enforce.last_turn from the on-disk map JSON.
    On a non-satisfying narrative turn: set vault_action_required=True (gate blocks
    tools next turn until map action is taken, then gate_check clears it).
    On tool-heavy / maintenance turns: pass silently.
    """
    hook_name = "vault_liveness_check"

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    # Only active when armed
    vault_enforce = state.get("vault_enforce", {})
    if not vault_enforce.get("armed"):
        return False, "", {}

    map_name = vault_enforce.get("map", "")
    last_turn = vault_enforce.get("last_turn", 0)

    # Read current_turn from disk (model-independent ground truth)
    current_turn = _get_map_current_turn(map_name)
    if current_turn is None:
        # Map file missing — can't gate; pass silently
        return False, "", {}

    if current_turn > last_turn:
        # Turn advanced — satisfying. Update last_turn.
        new_enforce = dict(vault_enforce)
        new_enforce["last_turn"] = current_turn
        return False, "", {"vault_enforce": new_enforce, "vault_action_required": False}

    # current_turn has NOT advanced. Only gate on narrative turns.
    if not _is_narrative_turn(hook_input, response_text, state):
        return False, "", {}

    # Narrative turn with frozen dungeon — set the flag (gate_check blocks next turn)
    log_correction(
        hook_name=hook_name,
        caught_text=f"map={map_name} current_turn={current_turn} last_turn={last_turn}",
        reason_given=(
            f"VAULT LIVENESS: narrative turn completed inside armed vault '{map_name}' "
            f"with current_turn frozen at {current_turn} (last_turn={last_turn}). "
            f"map(enter/search/wait) required next turn."
        ),
        severity="soft",
    )
    return False, "", {"vault_action_required": True}


def _check_in_dialogue_fabrication(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Check 5c: factual claims inside dialogue must be canon-verified.

    Catches the 'seventy-nine days' failure class where NPCs assert facts
    (durations, quantities, dates, relationships) in quoted speech that
    are not supported by the distillation cache or recent canon retrieval.
    """
    hook_name = "in_dialogue_fabrication_check"

    # Short responses skip
    if len(response_text) < 60:
        return False, "", {}

    # Maintenance bypass
    if in_maintenance(state):
        return False, "", {}

    # Skip non-gameplay sessions
    if state.get("session_type", "development") != "gameplay":
        return False, "", {}

    # Load scanner
    try:
        from hooks.dialogue_claim_scanner import detect_claims_in_response
    except ImportError:
        from dialogue_claim_scanner import detect_claims_in_response

    claims = detect_claims_in_response(response_text)
    if not claims:
        return False, "", {}

    # Load the distillation cache to verify against
    try:
        from hooks.distillation_cache import DistillationCache
    except ImportError:
        from distillation_cache import DistillationCache

    cache_path = _DEFAULT_CACHE_PATH
    cache = DistillationCache(cache_path)

    # Build a flat string of all key_facts across all cache entries
    # The check is intentionally permissive on the cache side — if a claim's
    # specifics appear anywhere in the cache, allow.
    all_facts_blob = "\n".join(
        " | ".join(entry.get("key_facts", []))
        for entry in cache.all_entries()
    ).lower()

    unverified = []
    for claim_type, claim_text in claims:
        # If the claim text appears in any cached fact, consider it verified
        if claim_text.lower() in all_facts_blob:
            continue
        # Bare-DIGIT fallback only — word-form numbers must match the full phrase
        bare = re.search(r'\b(\d+)\b', claim_text)
        if bare and bare.group(0) in all_facts_blob:
            continue
        unverified.append((claim_type, claim_text))

    if not unverified:
        return False, "", {}

    types_str = ", ".join(sorted(set(c[0] for c in unverified)))
    samples = "; ".join(f'[{t}] "{c}"' for t, c in unverified[:3])
    reason = (
        f"IN-DIALOGUE FABRICATION RISK: unverified factual claim(s) inside dialogue. "
        f"Types: {types_str}. Samples: {samples}. "
        f"Call check_canon for the relevant topic OR drill the cache to verify, "
        f"or rewrite the dialogue without the unsupported specific."
    )

    log_correction(
        hook_name=hook_name,
        caught_text=samples,
        reason_given=reason,
        severity="soft",
    )

    # Soft log only — validate_prose is the primary gate.
    return False, "", {}


# ---------------------------------------------------------------------------
# C24: Uncrystallized-names advisory (crystallization-capture counter).
#
# NOT a fabrication/correctness check (the free-narration observer that policed
# canon correctness was deliberately dropped 2026-06-16). This is a soft, never-
# blocking COUNTER: it notices proper nouns the DM has NAMED in narrative that
# have no canonical record (npc_states / lorebook / etc.), and after a name
# recurs across >=2 turns it prints ONE quiet line suggesting the DM crystallize
# it if it should persist. Fails silent; respects maintenance mode; never blocks.
# ---------------------------------------------------------------------------

# Setting vocabulary — Vaarn proper nouns + the 10 ancestries + the common
# capitalized words that begin sentences. Frozen; keeps the scan from drowning
# in setting-vocab / grammar false positives. Stored lowercased.
_SETTING_VOCAB = frozenset(w.lower() for w in {
    # setting + peoples
    "Vaarn", "Vaarnish", "Faa", "Sea", "Wasting", "Wastes",
    "True-kin", "Truekin", "Cacogen", "Cacogens", "Newbeast", "Newbeasts",
    "Mycomorph", "Mycomorphs", "Synth", "Synths", "Nomad", "Nomads",
    "Cacklemaw", "Exile", "Exiles", "Neobloom", "Neoblooms", "Planeyfolk",
    "Lithling", "Lithlings",
    # capitalized grammar / sentence-openers / pronouns
    "The", "A", "An", "And", "But", "Or", "Nor", "For", "Yet", "So",
    "He", "She", "It", "They", "We", "You", "I", "His", "Her", "Their",
    "Its", "Your", "Our", "My", "This", "That", "These", "Those", "There",
    "Here", "Then", "Now", "When", "Where", "What", "Who", "Whom", "Why",
    "How", "If", "As", "At", "In", "On", "Of", "To", "By", "With", "From",
    "Not", "No", "Yes", "Do", "Does", "Did", "Is", "Are", "Was", "Were",
    "Be", "Been", "Will", "Would", "Could", "Should", "Can", "May", "Might",
    "Must", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Day",
    "Night", "Morning", "Evening", "North", "South", "East", "West",
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    "Sunday", "God", "Sun", "Moon",
})

# Capitalized word / multi-word phrase, tokens >=3 letters (skips "A", "I").
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-z]{2,}(?:[ -][A-Z][a-z]{2,})*)\b")

_KNOWN_NAMES_CACHE = None


def _uncrystallized_known_names() -> set:
    """Build the lowercased union of names that already have a canonical home, so
    the proper-noun scan only surfaces genuinely-new inventions. Fail-soft per
    source. Both the full name and its word tokens are added (so 'Faa Nomad'
    matches on either token). Built once per hook process."""
    global _KNOWN_NAMES_CACHE
    if _KNOWN_NAMES_CACHE is not None:
        return _KNOWN_NAMES_CACHE
    known = set(_SETTING_VOCAB)

    def _add(s):
        if not s or not isinstance(s, str):
            return
        s = s.strip().lower()
        if not s:
            return
        known.add(s)
        for tok in re.split(r"[ \-/]+", s):
            if len(tok) >= 3:
                known.add(tok)

    # party roster (characters/*.json)
    try:
        cdir = CAMPAIGN_DIR / "characters"
        if cdir.is_dir():
            for cf in cdir.glob("*.json"):
                _add(cf.stem)
                try:
                    cd = json.loads(cf.read_text(encoding="utf-8"))
                    if isinstance(cd, dict):
                        _add(cd.get("name"))
                except Exception:
                    pass
    except Exception:
        pass
    # npc_states.json (keys + names)
    try:
        nd = json.loads((CAMPAIGN_DIR / "npc_states.json").read_text(encoding="utf-8"))
        for slug, rec in nd.get("npcs", {}).items():
            _add(slug)
            if isinstance(rec, dict):
                _add(rec.get("name"))
    except Exception:
        pass
    # lorebook.json (keywords)
    try:
        lb = json.loads((CAMPAIGN_DIR / "lorebook.json").read_text(encoding="utf-8"))
        for entry in lb.get("entries", []):
            for kw in (entry.get("keywords", []) if isinstance(entry, dict) else []):
                _add(kw)
    except Exception:
        pass
    # geography (locations + regions keys and names)
    try:
        gd = json.loads((CAMPAIGN_DIR / "VAARN_GEOGRAPHY.json").read_text(encoding="utf-8"))
        for sect in ("locations", "regions"):
            for slug, rec in (gd.get(sect, {}) or {}).items():
                _add(slug)
                if isinstance(rec, dict):
                    _add(rec.get("name"))
    except Exception:
        pass
    # bestiary / rulebook creature vocabulary (engine-side, read-only book data)
    try:
        bp = Path(__file__).parent.parent / "data" / "rules" / "rulebook" / "bestiary.json"
        bd = json.loads(bp.read_text(encoding="utf-8"))
        for entry in bd.get("entries", []):
            for kw in (entry.get("keywords", []) if isinstance(entry, dict) else []):
                _add(kw)
    except Exception:
        pass

    _KNOWN_NAMES_CACHE = known
    return known


def _scan_uncrystallized_candidates(text: str, known: set) -> set:
    """Proper nouns in `text` that are not in the known-name union. A candidate is
    'known' if the whole phrase OR every word token is known (so a phrase built
    from known tokens, e.g. 'Faa Nomad', is not flagged)."""
    out = set()
    for m in _PROPER_NOUN_RE.finditer(text or ""):
        cand = m.group(1).strip()
        cl = cand.lower()
        if cl in known:
            continue
        toks = [t for t in re.split(r"[ \-]+", cl) if t]
        if toks and all(t in known for t in toks):
            continue
        out.add(cand)
    return out


def _check_uncrystallized_names(hook_input: dict, state: dict,
                                response_text: str) -> tuple[bool, str, dict]:
    """C24 advisory: surface proper nouns the DM has named that have no canonical
    record, once they recur across >=2 turns. NEVER blocks; the runner sees no
    block reason. Persists per-name turn counts across turns via the updates dict."""
    if in_maintenance(state):
        return False, "", {}
    if not response_text:
        return False, "", {}
    known = _uncrystallized_known_names()
    # Guard: if the campaign data didn't load (thin union), skip — otherwise every
    # proper noun looks uncrystallized. lorebook presence is the liveness signal.
    if not (CAMPAIGN_DIR / "lorebook.json").exists():
        return False, "", {}

    candidates = _scan_uncrystallized_candidates(response_text, known)
    tracker = dict(state.get("uncrystallized_name_turns", {}) or {})
    if not candidates and not tracker:
        return False, "", {}

    turn = state.get("turn_count", 0)
    recurring = []
    for name in sorted(candidates):
        rec = tracker.get(name) or {"count": 0, "last_turn": -1}
        if rec.get("last_turn") != turn:
            rec["count"] = rec.get("count", 0) + 1
            rec["last_turn"] = turn
        tracker[name] = rec
        if rec["count"] >= 2:
            recurring.append(name)

    # Keep the tracker bounded — retain the 40 most-recently-seen names.
    if len(tracker) > 40:
        for stale in sorted(tracker, key=lambda n: tracker[n].get("last_turn", -1))[:len(tracker) - 40]:
            tracker.pop(stale, None)

    if recurring:
        shown = ", ".join(recurring[:6])
        print(f"⚑ Uncrystallized names this session: {shown} — "
              f"npc(action=\"set\") / lorebook(action=\"add\") if they should persist.")

    return False, "", {"uncrystallized_name_turns": tracker}


# ---------------------------------------------------------------------------
# Task 11: Stale-parley nudge (non-blocking)
# ---------------------------------------------------------------------------

_STALE_PARLEY_DAYS = 7


def _read_current_campaign_day():
    """Read campaign_day from characters/_meta.json.

    Same source phrase_reminder.py's CONDITIONS push reads (the roster-level
    meta file, not a per-character sheet's nested "meta"). Returns None on
    any problem (missing file, bad JSON, missing key)."""
    try:
        meta_path = CAMPAIGN_DIR / "characters" / "_meta.json"
        if not meta_path.exists():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8")).get("campaign_day")
    except Exception:
        return None


def _stale_parley_lines(campaign_dir, current_day) -> list:
    """Advisory lines for OPEN parleys quiet >=7 campaign days.

    Pure, never raises. Staleness is current_day minus a parley's latest
    activity (the max of opened_day and every log-entry day). Missing/corrupt
    parleys.json, an unimportable social_system, or a non-int current_day all
    yield [] rather than raising -- this feeds the non-blocking Stop-hook
    advisory layer.
    """
    if not isinstance(current_day, int):
        return []
    try:
        import social_system as ss
        open_parleys = ss.get_open(campaign_dir)
    except Exception:
        return []
    if not isinstance(open_parleys, dict):
        return []

    lines = []
    for slug, record in open_parleys.items():
        if not isinstance(record, dict):
            continue
        try:
            latest = record.get("opened_day", 0) or 0
            for entry in record.get("log", []) or []:
                if isinstance(entry, dict):
                    day = entry.get("day")
                    if isinstance(day, int) and day > latest:
                        latest = day
            age = current_day - latest
            if age >= _STALE_PARLEY_DAYS:
                title = record.get("title", slug)
                lines.append(
                    f"🤝 open parley '{title}' has been quiet ~{age} days — "
                    f'parley(action="status", slug="{slug}") or close it.'
                )
        except Exception:
            continue
    return lines


def _check_stale_parley_nudge(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Advisory: nudge on OPEN parleys that have gone quiet >=7 campaign days.

    NEVER blocks. Mirrors _check_uncrystallized_names / _check_settlement_change_nag:
    prints directly to stdout, always returns (False, "", {}).
    """
    if in_maintenance(state):
        return False, "", {}

    current_day = _read_current_campaign_day()
    for line in _stale_parley_lines(CAMPAIGN_DIR, current_day):
        print(line)

    return False, "", {}


# ---------------------------------------------------------------------------
# Dice-honesty hardening item 2: prose-dice watcher (non-blocking)
# ---------------------------------------------------------------------------

# Resolution language only -- a formula tied to an outcome or imperative.
# Deliberately NOT matched: bare notation (weapon "d8", gift "d6 HP/use",
# a sheet's "DC 15" stat display) -- precision over recall, since a miss is
# cheap (advisory) and a false positive is noise Joe reads every turn.
_DICE_RESOLUTION_PATTERNS = [
    r"give me a roll",
    r"roll(?:ed)?\s+(?:a\s+|an\s+)?\d+",
    r"d20\s*[+\-]\s*\w+.{0,40}(?:DC|beat|vs)\s*\d+",
    r"natural\s+(?:1|20)",
    r"\brolls?\b.{0,40}\b(?:DC|save|check)\b",
]

_COMPILED_DICE_RESOLUTION_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in _DICE_RESOLUTION_PATTERNS
]

# Dice-capable engine tools whose call this turn certifies any narrated dice.
# Matched by bare suffix (name.split("__")[-1]) so both the real
# "mcp__rubicon-seven__roll" transcript form and a bare "roll" test/legacy
# form are recognized -- map counts because its encounter die is real
# engine randomness.
_DICE_CAPABLE_TOOL_SUFFIXES = {"roll", "test_dice", "combat", "map"}


def _looks_like_sheet_bullet(line: str) -> bool:
    """True for a stat/sheet display line, e.g. '- **Weapons:** Saber (d8) · Rifle (d10)'.

    Notation-context suppressor: a line opening with a bullet marker and
    carrying a field separator (':' or '·') reads as a sheet display, not
    narrated dice resolution -- skip it before pattern-matching.
    """
    stripped = line.strip()
    if not stripped or not (stripped.startswith("-") or stripped.startswith("*")):
        return False
    return (":" in stripped) or ("·" in stripped)


def _dice_resolution_language(text) -> bool:
    """True iff dice RESOLUTION language (not bare notation) appears in text.

    Pure, never raises. Filters out sheet-bullet lines first, then checks
    the curated resolution-pattern list against what remains.
    """
    if not isinstance(text, str) or not text:
        return False
    kept_lines = [ln for ln in text.split("\n") if not _looks_like_sheet_bullet(ln)]
    filtered = "\n".join(kept_lines)
    return any(p.search(filtered) for p in _COMPILED_DICE_RESOLUTION_PATTERNS)


def _tool_calls_include_dice(tool_calls_this_turn) -> bool:
    for name in (tool_calls_this_turn or []):
        if isinstance(name, str) and name.split("__")[-1] in _DICE_CAPABLE_TOOL_SUFFIXES:
            return True
    return False


def prose_dice_narrated(response_text: str, tool_calls_this_turn) -> bool:
    """True if dice resolution was narrated this turn with no dice-capable
    engine tool (roll/test_dice/combat/map) called to certify it.

    Pure helper -- unit-testable without any hook machinery. Mirrors
    settlement_change_unstamped's shape: a cue check gated by tool absence.
    """
    if not _dice_resolution_language(response_text):
        return False
    return not _tool_calls_include_dice(tool_calls_this_turn)


def _check_prose_dice(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """Advisory: dice resolution narrated in prose without a certifying engine roll.

    NEVER blocks, NEVER raises (fully guarded). Silent if roll/test_dice/
    combat/map ran this turn, in maintenance mode, or on any malformed input.
    """
    try:
        if in_maintenance(state):
            return False, "", {}
        tool_names = [name for name, _ in _iter_assistant_tool_uses(hook_input)]
        if prose_dice_narrated(response_text, tool_names):
            print(
                "🎲 dice narrated without an engine roll — use roll(...)/test_dice(...) "
                "so the result is certified."
            )
    except Exception:
        pass
    return False, "", {}


def _check_mechanics_source(hook_input: dict, state: dict, response_text: str) -> tuple[bool, str, dict]:
    """A0.2 — fail-closed: narrated mechanics must trace to a tool call this turn.

    A narrated mechanical resolution (HP delta, AV, forced check, dice,
    condition, rule label) must be backed by a governing engine tool call in
    the same turn (scan_unbacked_mechanics). BLOCKING: returns True on a
    violation so the reason wins over advisory checks.

    Short-circuits BEFORE any scanning on:
      - maintenance mode (engine-dev rooms don't narrate; full_session_startup
        clears maintenance so this can never ride into play), and
      - meta-only turns (entirely-parenthetical out-of-character asides — the
        D135 exemption). NOT gated on length/turn_count: a one-line "You lose
        12 HP" with no backing tool is exactly the failure this gate targets,
        so the full _is_narrative_turn length/turn_count/tool-heavy filters are
        deliberately not applied here (they would neuter the gate).
    """
    if in_maintenance(state):
        return False, "", {}
    if _is_meta_only_response(response_text):
        return False, "", {}
    tool_names = [
        name.replace("mcp__rubicon-seven__", "")
        for name, _ in _iter_assistant_tool_uses(hook_input)
    ]
    hits = scan_unbacked_mechanics(response_text, tool_names)
    if hits:
        reason = (
            "MECHANICS GATE (A0.2 — fail-closed):\n" + "\n".join(hits[:4])
            + "\nRe-emit the turn with the governing tool call made, or with the "
              "mechanic removed from the prose (the >> MECHANICS line relays numbers)."
        )
        return True, reason, {}
    return False, "", {}


# ===================================================================
# Main entry point
# ===================================================================

@fail_closed_wrapper
def main():
    hook_input = read_hook_input()
    # Real Stop-hook stdin carries transcript_path only; load this turn's
    # messages once so every check below sees them in-memory.
    _hydrate_transcript_messages(hook_input)
    with file_lock():
        state = load_state()

    response_text = _get_response_text(hook_input)
    user_text = _get_user_text(hook_input)

    checks = [
        lambda: _check_canon(hook_input, state),
        # BLOCKING check: forged preps must pass the dm-design review gate.
        lambda: _check_dm_design_gate(hook_input, state),
        # BLOCKING check (A0.2): narrated mechanics must trace to a tool call
        # this turn. Registered before advisory checks so its reason wins.
        lambda: _check_mechanics_source(hook_input, state, response_text),
        lambda: _check_anti_pattern(hook_input, state, response_text),
        lambda: _check_semantic_observer(hook_input, state, response_text),
        lambda: _check_prep_file(hook_input, state),
        lambda: _check_lorebook(hook_input, state, response_text),
        lambda: _check_npc_fabrication(hook_input, state, response_text),
        lambda: _check_in_dialogue_fabrication(hook_input, state, response_text),
        lambda: _check_backstory(hook_input, state, response_text),
        lambda: _check_vault_liveness(hook_input, state, response_text),
        # Settlement change reflex: narrated-but-unstamped settlement change → advisory nag.
        # NEVER blocks — prints a reminder to stdout and returns (False, "", {}).
        lambda: _check_settlement_change_nag(hook_input, state, response_text),
        # C24: uncrystallized-names advisory. NEVER blocks — prints one quiet line
        # when a named-but-unrecorded proper noun recurs across >=2 turns; carries
        # per-name turn counts across turns via the returned updates dict.
        lambda: _check_uncrystallized_names(hook_input, state, response_text),
        # Settlement v1: session-end Ceruline reconcile nudge.
        # NEVER blocks — prints a one-line advisory; carries ceruline_seen_session
        # across turns via the returned updates dict (not in-place state mutation).
        lambda: _check_ceruline_reconcile_nudge(hook_input, state, response_text),
        # Task 11: stale-parley nudge. NEVER blocks — prints one advisory line
        # per OPEN parley quiet >=7 campaign days.
        lambda: _check_stale_parley_nudge(hook_input, state, response_text),
        # Dice-honesty hardening item 2: prose-dice watcher. NEVER blocks --
        # prints one advisory when dice resolution is narrated but no
        # dice-capable engine tool (roll/test_dice/combat/map) ran this turn.
        lambda: _check_prose_dice(hook_input, state, response_text),
        # NPC continuity: union NPCs named this turn into open_npc_scene
        # (never auto-clears — the continuity write clears the flag via gate_check).
        lambda: (False, "", _check_npc_continuity(state, user_text, response_text)),
    ]

    all_updates = {}
    block_reason = None
    for check_fn in checks:
        _blocked, _reason, updates = check_fn()
        all_updates.update(updates)
        if _blocked and block_reason is None:
            block_reason = _reason

    if all_updates:
        with file_lock():
            final_state = load_state()
            final_state.update(all_updates)
            save_state(final_state)

    if block_reason:
        # Stop-hook block convention: reason on stderr, exit code 2.
        # State updates above are saved FIRST so pending_dm_design persists
        # across the blocked stop.
        print(block_reason, file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
