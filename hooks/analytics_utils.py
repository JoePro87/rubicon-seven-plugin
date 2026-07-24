#!/usr/bin/env python3
"""Persistent catch analytics for anti-pattern hooks.

Accumulates pattern catch data across sessions in catch_analytics.json.
All public functions are fail-safe: errors are caught internally and never
propagate to callers, so hook logic is never interrupted by analytics failures.
"""

import sys
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from hooks.hook_utils import file_lock
from rubicon_paths import catch_analytics_path

# CAMPAIGN-SCOPED (was engine-relative `Path(__file__).parent`, a privacy leak — see
# rubicon_paths.catch_analytics_path). Each campaign owns its own analytics; nothing ships.
ANALYTICS_FILE = catch_analytics_path()
MAX_FILE_SIZE = 200 * 1024  # 200KB — phrase_stats alone can run ~60KB; semantic_catches needs headroom on top.
MIN_SEMANTIC_KEEP = 50  # Never drain semantic_catches below this; we need enough history for session-start summary.


def _load_analytics() -> dict:
    """Load analytics file. Returns default structure if missing/corrupt."""
    default = {
        "_meta": {
            "version": 1,
            "last_pruned": datetime.now().strftime("%Y-%m-%d"),
            "total_sessions_tracked": 0,
        },
        "catches": [],
        "phrase_stats": {},
        "semantic_catches": [],
    }
    if not ANALYTICS_FILE.exists():
        return default
    try:
        data = json.loads(ANALYTICS_FILE.read_text(encoding="utf-8"))
        # Ensure top-level keys exist
        for key in default:
            if key not in data:
                data[key] = default[key]
        return data
    except (json.JSONDecodeError, IOError):
        return default


def _save_analytics(data: dict) -> None:
    """Save analytics file atomically."""
    tmp = ANALYTICS_FILE.with_suffix(".tmp")
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(ANALYTICS_FILE)
    except Exception:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


def _enforce_size_limit(data: dict) -> dict:
    """Prune oldest catch entries if file would exceed MAX_FILE_SIZE.

    Prunes v1 `catches` first (chunks of 10), then v2 `semantic_catches`
    (chunks of 25). Preserves most recent entries in both lists.

    Guard: never drains `semantic_catches` below `MIN_SEMANTIC_KEEP`. If
    phrase_stats has bloated the file past budget, exit over-budget rather
    than destroy the catch history the session-start summary depends on.
    """
    content = json.dumps(data, indent=2)
    # First drain v1 catches (legacy format, no minimum guard)
    while len(content.encode("utf-8")) > MAX_FILE_SIZE and data.get("catches"):
        data["catches"] = data["catches"][10:]
        content = json.dumps(data, indent=2)
    # If still over, drain v2 semantic_catches in chunks of 25 — but hold a floor.
    while (
        len(content.encode("utf-8")) > MAX_FILE_SIZE
        and len(data.get("semantic_catches", [])) > MIN_SEMANTIC_KEEP
    ):
        # Keep most-recent entries; drop oldest 25 at a time.
        data["semantic_catches"] = data["semantic_catches"][-max(MIN_SEMANTIC_KEEP, len(data["semantic_catches"]) - 25):]
        content = json.dumps(data, indent=2)
    return data


def log_catch(
    phrase: str,
    scene_type: str,
    catch_number: int,
    turn_count: int,
) -> None:
    """Record a single catch event and update phrase_stats.

    Args:
        phrase: The exact matched phrase text.
        scene_type: Current scene type (settlement, combat, intimate, etc.).
        catch_number: Cumulative catch count within this session.
        turn_count: Current turn number within this session.
    """
    try:
        with file_lock():
            data = _load_analytics()

            today = datetime.now().strftime("%Y-%m-%d")
            key = phrase.lower().strip()

            # Append individual catch entry
            data["catches"].append({
                "phrase": key,
                "session_date": today,
                "scene_type": scene_type,
                "catch_number": catch_number,
                "turn_count": turn_count,
            })

            # Update phrase_stats
            stats = data.setdefault("phrase_stats", {})
            if key not in stats:
                stats[key] = {
                    "total_catches": 0,
                    "sessions_seen": 0,
                    "clean_streak": 0,
                    "scene_type_distribution": {},
                    "tier": "banned",
                    "first_caught": today,
                    "last_caught": today,
                }

            ps = stats[key]
            ps["total_catches"] = ps.get("total_catches", 0) + 1
            ps["last_caught"] = today

            # Update scene_type_distribution
            dist = ps.setdefault("scene_type_distribution", {})
            dist[scene_type] = dist.get(scene_type, 0) + 1

            # sessions_seen: increment only if this is the first catch for
            # this phrase on this date (approximation of per-session)
            date_catches_for_phrase = [
                c for c in data["catches"]
                if c["phrase"] == key and c["session_date"] == today
            ]
            if len(date_catches_for_phrase) == 1:
                ps["sessions_seen"] = ps.get("sessions_seen", 0) + 1

            # Reset clean_streak on catch
            ps["clean_streak"] = 0

            data = _enforce_size_limit(data)
            _save_analytics(data)
    except Exception:
        # Analytics failures must never crash hooks
        pass


def get_phrase_stats(phrase: Optional[str] = None) -> dict:
    """Return stats for one phrase (by key) or all phrases.

    Args:
        phrase: Lowercase phrase key, or None for all stats.

    Returns:
        Single phrase stat dict, or full phrase_stats dict.
        Empty dict on error.
    """
    try:
        with file_lock():
            data = _load_analytics()
        stats = data.get("phrase_stats", {})
        if phrase is not None:
            return stats.get(phrase.lower().strip(), {})
        return stats
    except Exception:
        return {}


def get_scene_weights(scene_type: str) -> dict:
    """Return {phrase: catch_count} for a given scene type.

    Useful for prioritizing reminders: phrases caught most often in
    this scene type are most likely to recur.

    Args:
        scene_type: e.g. "settlement", "combat", "intimate", "travel".

    Returns:
        Dict mapping phrase -> catch count in that scene type,
        sorted descending by count. Empty dict on error.
    """
    try:
        with file_lock():
            data = _load_analytics()
        stats = data.get("phrase_stats", {})
        weights = {}
        for phrase_key, ps in stats.items():
            dist = ps.get("scene_type_distribution", {})
            count = dist.get(scene_type, 0)
            if count > 0:
                weights[phrase_key] = count
        # Sort descending
        return dict(sorted(weights.items(), key=lambda x: x[1], reverse=True))
    except Exception:
        return {}


def prune_old_catches(max_age_days: int = 30) -> int:
    """Remove individual catch entries older than max_age_days.

    Keeps phrase_stats intact (they accumulate forever).

    Args:
        max_age_days: Entries older than this many days are removed.

    Returns:
        Number of entries pruned. 0 on error.
    """
    try:
        with file_lock():
            data = _load_analytics()
            cutoff = (datetime.now() - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
            original_count = len(data["catches"])
            data["catches"] = [
                c for c in data["catches"]
                if c.get("session_date", "9999-99-99") >= cutoff
            ]
            pruned = original_count - len(data["catches"])
            if pruned > 0:
                data["_meta"]["last_pruned"] = datetime.now().strftime("%Y-%m-%d")
            data = _enforce_size_limit(data)
            _save_analytics(data)
            return pruned
    except Exception:
        return 0


def increment_session_count() -> None:
    """Increment total_sessions_tracked. Call at session start."""
    try:
        with file_lock():
            data = _load_analytics()
            data["_meta"]["total_sessions_tracked"] = (
                data["_meta"].get("total_sessions_tracked", 0) + 1
            )
            _save_analytics(data)
    except Exception:
        pass


def update_clean_streaks(session_catches: set[str]) -> None:
    """Update clean_streak for all tracked phrases at session end.

    For phrases NOT in session_catches: increment clean_streak.
    For phrases IN session_catches: reset clean_streak to 0.

    Args:
        session_catches: Set of lowercase phrase keys caught this session.
    """
    try:
        with file_lock():
            data = _load_analytics()
            stats = data.get("phrase_stats", {})
            for phrase_key, ps in stats.items():
                if phrase_key in session_catches:
                    ps["clean_streak"] = 0
                else:
                    ps["clean_streak"] = ps.get("clean_streak", 0) + 1
            _save_analytics(data)
    except Exception:
        pass


# ===================================================================
# Semantic catch logging (v2 schema extension)
# ===================================================================

def log_semantic_catch(
    quote: str,
    category: str,
    confidence: str,
    session_id: str,
    turn_id: int,
    scene_type: str = "unknown",
) -> None:
    """Log a Sonnet observer finding to catch_analytics.json.

    Entries are keyed by (session_id, turn_id, quote) — writing the
    same quote for the same turn overwrites; different quotes on the
    same turn append. This matches the observer's actual usage: a
    single turn may surface multiple distinct violations.

    Args:
        quote: The violating phrase or passage Sonnet identified.
        category: Situation Strategy label (e.g., "Reaction Shot").
        confidence: "high" | "medium" | "low".
        session_id: Claude Code session UUID.
        turn_id: Monotonic turn counter from hook state.
        scene_type: Scene type at catch time (e.g. "social", "combat"),
            so semantic catches carry the same scene dimension the
            deterministic v1 phrase_stats path already records. Defaults
            to "unknown" when the caller can't resolve it.

    Fail-safe: any error (lock timeout, corrupt file, etc.) is caught
    and silently swallowed — analytics is advisory, never critical.
    """
    try:
        with file_lock(timeout=2.0):
            data = _load_analytics()
            # Ensure schema v2 sections exist
            data["_meta"]["version"] = 2
            if "semantic_catches" not in data:
                data["semantic_catches"] = []

            # Idempotent per-quote: same (session, turn, quote) overwrites;
            # different quotes on the same turn append.
            key = (session_id, turn_id, quote)
            new_entry = {
                "quote": quote,
                "category": category,
                "confidence": confidence,
                "session_id": session_id,
                "turn_id": turn_id,
                "scene_type": scene_type,
                "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            }
            for i, existing in enumerate(data["semantic_catches"]):
                if (existing.get("session_id"), existing.get("turn_id"), existing.get("quote")) == key:
                    data["semantic_catches"][i] = new_entry
                    break
            else:
                data["semantic_catches"].append(new_entry)

            data = _enforce_size_limit(data)
            _save_analytics(data)
    except Exception as e:
        # Fail-safe: log to stderr but never propagate
        try:
            print(f"[analytics] log_semantic_catch failed: {e}", file=sys.stderr)
        except Exception:
            pass


def get_recent_semantic_catches(session_id: Optional[str] = None, limit: int = 100) -> list:
    """Read semantic catches from analytics, optionally filtered by session.

    Returns a list of catch dicts. Newest last. If analytics file is missing
    or malformed, returns empty list.

    Args:
        session_id: If provided, only return catches matching this session.
        limit: Maximum entries to return (most recent).

    Returns:
        List of catch dicts, or [] on any failure.
    """
    try:
        with file_lock():
            data = _load_analytics()
        catches = data.get("semantic_catches", [])
        if session_id:
            catches = [c for c in catches if c.get("session_id") == session_id]
        return catches[-limit:]
    except Exception:
        return []
