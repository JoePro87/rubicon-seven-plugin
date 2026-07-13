#!/usr/bin/env python3
"""Lorebook gate helpers.

Provides:
- load_lorebook_keywords()   — mtime-cached set of trigger keywords from lorebook.json
- extract_triggers(message)  — keywords present in the user message (filtered)
- lorebook_was_called(hook_input) — True if a lorebook(view, ...) tool_use fired this turn
- should_skip_message(message) — True for admin / parenthetical / very-short input

The gate is data-driven: lorebook.json is the source of truth. New entries auto-extend
the trigger vocabulary on next turn (mtime invalidates cache).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# Ensure the engine root is importable for rubicon_paths. This module is normally
# imported by a hook that already inserted the root on sys.path, but it may also be
# imported standalone (tests), so insert defensively — mirrors the other hooks.
sys.path.insert(0, str(Path(__file__).parent.parent))
from rubicon_paths import campaign_dir as _campaign_dir

CAMPAIGN_DIR = _campaign_dir()
LOREBOOK_PATH = CAMPAIGN_DIR / "lorebook.json"

# Campaign-side gate-words file: per-campaign exclude/augment vocabulary, the
# home for a campaign's own trip-wire words and personal-roster belt-and-
# suspenders excludes. Same fail-open pattern as fabrication_tripwires.json.
GATE_WORDS_FILENAME = "lorebook_gate_words.json"
GATE_WORDS_PATH = CAMPAIGN_DIR / GATE_WORDS_FILENAME

# Minimum keyword length — shorter keywords are too noisy
MIN_KEYWORD_LEN = 5

# Keywords excluded from the gate even if present in lorebook:
#  - party members are excluded via the LIVE roster (hook_utils.load_party_names),
#    applied per-call in extract_triggers — never hardcoded here
#  - campaign-specific excludes come from the campaign-side gate-words file
#  - high-frequency English words that happen to appear in lorebook keyword lists
ENGINE_EXCLUDE_KEYWORDS = {
    # Common English / generic relational terms
    "wife", "husband", "spouse", "married", "love", "mother", "father",
    "daughter", "son", "sister", "brother", "friend", "child", "children",
    "people", "person", "place", "thing", "story", "history", "memory",
    "today", "yesterday", "tomorrow", "morning", "evening", "night",
    "before", "after", "during", "always", "never", "sometimes",
    "small", "large", "great", "little", "first", "second", "third",
    # Pronoun-ish / verb-ish that ended up as keywords somewhere
    "about", "where", "when", "what", "which", "would", "could", "should",
    "their", "there", "these", "those", "other", "another",
    "room", "hall", "door", "table", "chair", "window", "wall",
    # Domain words too generic on their own
    "archives", "archive", "garden", "tower", "house", "tier",
    "council", "audience", "letter", "scene", "message",
}

# Always-trigger augment list — high-risk terms not always present in lorebook keywords
# but explicitly named as tripwires in CLAUDE.md / VOICE.md / failure history.
# Book/generic vocabulary only (verified against the engine's shipped rules data
# 2026-07-13) — campaign-specific tripwires live in the campaign-side gate-words
# file (GATE_WORDS_PATH) so playtesters get a home for their own.
# Edit when new BOOK/GENERIC tripwires emerge.
ENGINE_AUGMENT_KEYWORDS = frozenset({
    # Neobloom biology (Day 116/123 failure modes)
    "neobloom", "neoblooms", "voxpod", "voxpods",
    "photosynthesis", "photosynthesize", "photosynthetic",
    "amaranthine",
    "interface", "compounds", "bioluminescent", "bioluminescence",
    # Species
    "true-kin", "truekin", "cacogen", "synth",
    "lithling", "planeyfolk", "newbeast",
    # Factions / cults
    "hegemony", "autarch", "autarchy", "seekers", "brotherhood",
    "cacklemaw",
    # Cosmology / mystic
    "kronophage", "mycomorph", "communion", "gleam", "exotica",
    # Geography (book-generic)
    "vaarn", "lazul",
    # Time / chronology terms — fire the time-estimation rule
    "ago", "decade", "decades", "century", "centuries",
    "millennia", "millennium", "since", "before",
})

# Back-compat alias — existing imports/tests reference AUGMENT_KEYWORDS.
AUGMENT_KEYWORDS = ENGINE_AUGMENT_KEYWORDS


def _load_gate_words() -> tuple[float, frozenset, frozenset]:
    """Campaign-side gate words: (mtime, excludes, augments). Fail-open."""
    try:
        mtime = GATE_WORDS_PATH.stat().st_mtime
        data = json.loads(GATE_WORDS_PATH.read_text(encoding="utf-8"))
        exc = frozenset(
            str(w).strip().lower() for w in data.get("exclude_keywords", []) if str(w).strip()
        )
        aug = frozenset(
            str(w).strip().lower() for w in data.get("augment_keywords", []) if str(w).strip()
        )
        return mtime, exc, aug
    except Exception:
        return 0.0, frozenset(), frozenset()


def _load_keywords_from_disk(campaign_excludes: frozenset) -> tuple[float, frozenset[str]]:
    """Read lorebook.json, return (mtime, keyword_set). On error: (0.0, empty)."""
    try:
        mtime = LOREBOOK_PATH.stat().st_mtime
        data = json.loads(LOREBOOK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0.0, frozenset()

    entries = data.get("entries", [])
    if not isinstance(entries, list):
        return mtime, frozenset()

    keywords: set[str] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        for kw in e.get("keywords", []) or []:
            if not isinstance(kw, str):
                continue
            kw_norm = kw.strip().lower()
            if len(kw_norm) < MIN_KEYWORD_LEN:
                continue
            if kw_norm in ENGINE_EXCLUDE_KEYWORDS or kw_norm in campaign_excludes:
                continue
            keywords.add(kw_norm)

    return mtime, frozenset(keywords)


# Module-level cache; invalidated when either the lorebook or gate-words file changes
_CACHE: dict = {"mtime": -1.0, "gw_mtime": -1.0, "keywords": frozenset()}


def load_lorebook_keywords() -> frozenset[str]:
    """Return the active keyword set, reloading if lorebook.json or the
    campaign gate-words file changed."""
    try:
        mtime = LOREBOOK_PATH.stat().st_mtime
    except Exception:
        # lorebook.json missing/unreadable: never silently drop tripwire enforcement.
        # Fall back to the always-on augment lists (engine + campaign) if nothing
        # is cached yet (a populated cache already includes the augments from a
        # prior load).
        if _CACHE["keywords"]:
            return _CACHE["keywords"]
        _gw_mtime, _exc, campaign_augments = _load_gate_words()
        return frozenset(ENGINE_AUGMENT_KEYWORDS | campaign_augments)

    gw_mtime, campaign_excludes, campaign_augments = _load_gate_words()
    if mtime != _CACHE["mtime"] or gw_mtime != _CACHE["gw_mtime"]:
        new_mtime, new_kw = _load_keywords_from_disk(campaign_excludes)
        _CACHE["mtime"] = new_mtime
        _CACHE["gw_mtime"] = gw_mtime
        _CACHE["keywords"] = frozenset(new_kw | ENGINE_AUGMENT_KEYWORDS | campaign_augments)
    return _CACHE["keywords"]


# Word-boundary tokenizer — captures alphanumeric runs (handles hyphens via split)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]{2,}")


def extract_triggers(message: str, max_triggers: int = 5) -> list[str]:
    """Return up to N lorebook keywords matched in the message.

    Matches whole-token (word-boundary). Case-insensitive.
    """
    if not message:
        return []
    keywords = load_lorebook_keywords()
    if not keywords:
        return []

    tokens = {m.group(0).lower() for m in _TOKEN_RE.finditer(message)}
    # Exact whole-token matches
    hits = sorted(tokens & keywords)
    # Also try multi-word keywords (containing space or hyphen) via substring
    msg_lower = message.lower()
    multi = [kw for kw in keywords if (" " in kw or "-" in kw) and kw in msg_lower]
    for m in multi:
        if m not in hits:
            hits.append(m)

    # Party names are excluded fresh every call from the LIVE roster — no cache
    # staleness class, since the roster can change between turns.
    from hooks.hook_utils import load_party_names
    party: set[str] = set()
    try:
        for nm in load_party_names(CAMPAIGN_DIR):
            nml = nm.strip().lower()
            if nml:
                party.add(nml)
                for tok in nml.split():
                    if len(tok) >= MIN_KEYWORD_LEN:
                        party.add(tok)
    except Exception:
        party = set()
    hits = [h for h in hits if h not in party]

    return hits[:max_triggers]


# Patterns for messages that should skip the gate entirely
_ADMIN_PREFIXES = ("/", "!")
_PARENTHETICAL_RE = re.compile(r"^\s*\(.+\)\s*$", re.DOTALL)

# Markers that identify hook-injected feedback being echoed as user input.
# When a stop hook blocks with stderr like "LOREBOOK GAP: halyn ...", that
# string arrives as the next user prompt. Without this guard the gate sees
# its own error message, re-extracts 'halyn', and re-arms itself forever.
_HOOK_ECHO_MARKERS = (
    "stop hook feedback",
    "stop hook blocking error",
    "lorebook gap:",
    "canon not verified",
    "prep gap:",
    "userpromptsubmit hook",
    "pretooluse hook",
)


def should_skip_message(message: str) -> bool:
    """True if this user message should not trigger the lorebook gate."""
    if not message:
        return True
    stripped = message.strip()
    if len(stripped) < 20:
        return True
    if stripped.startswith(_ADMIN_PREFIXES):
        return True
    if _PARENTHETICAL_RE.match(stripped):
        return True
    # Hook feedback echo guard — prevents self-cascading trigger loops
    lowered = stripped.lower()
    if any(marker in lowered for marker in _HOOK_ECHO_MARKERS):
        return True
    return False


def lorebook_was_called(hook_input: dict) -> bool:
    """Scan the assistant's tool_use blocks this turn for a lorebook call."""
    messages = hook_input.get("transcript_messages", [])
    # Walk backward from the most recent assistant message
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                if name == "mcp__rubicon-seven__lorebook":
                    return True
        # Only inspect the most recent assistant turn
        break
    return False


def assistant_turn_is_tool_only(hook_input: dict) -> bool:
    """True if the most recent assistant turn was tool calls only (no narrative text)."""
    messages = hook_input.get("transcript_messages", [])
    for msg in reversed(messages):
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            return False
        text_chars = 0
        had_tool = False
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                had_tool = True
            elif block.get("type") == "text":
                text_chars += len(block.get("text", "").strip())
        # Tool-only if there was a tool call and no meaningful text
        return had_tool and text_chars < 50
    return False
