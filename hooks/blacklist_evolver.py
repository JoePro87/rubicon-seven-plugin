"""Blacklist evolution cycle — grows blacklist.json from catch analytics.

Called at session-end. Reads catch_analytics.json and corrections.json,
identifies recurring patterns, and adds new entries to blacklist.json.

Thresholds:
- New phrase -> use_sparingly: 3+ catches across 2+ sessions
- use_sparingly -> banned: 5+ additional catches after being added
- Stale flag: not caught in 10+ sessions (logged, not auto-removed)
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rubicon_paths import catch_analytics_path

HOOKS_DIR = Path(__file__).parent
# CAMPAIGN-SCOPED (was engine-relative — privacy leak; see rubicon_paths.catch_analytics_path).
ANALYTICS_FILE = catch_analytics_path()
CORRECTIONS_FILE = HOOKS_DIR / "corrections.json"
BLACKLIST_FILE = HOOKS_DIR / "blacklist.json"

MIN_CATCHES_FOR_PROMOTION = 3
MIN_SESSIONS_FOR_PROMOTION = 2
SPARINGLY_TO_BANNED_THRESHOLD = 5
STALE_SESSION_THRESHOLD = 10


def find_promotion_candidates(
    analytics: dict, existing_phrases: set[str], protected: frozenset[str] = frozenset()
) -> set[str]:
    """Find phrases caught often enough to add to the blacklist."""
    candidates = set()
    for phrase, stats in analytics.get("phrase_stats", {}).items():
        if phrase.lower() in existing_phrases:
            continue
        if phrase.lower() in protected:
            continue
        total = stats.get("total_catches", 0)
        sessions = stats.get("sessions_seen", 0)
        if total >= MIN_CATCHES_FOR_PROMOTION and sessions >= MIN_SESSIONS_FOR_PROMOTION:
            candidates.add(phrase)
    return candidates


def find_tier_promotions(
    analytics: dict, sparingly_phrases: set[str], threshold: int = SPARINGLY_TO_BANNED_THRESHOLD,
    protected: frozenset[str] = frozenset()
) -> set[str]:
    """Find use_sparingly phrases that should promote to banned."""
    promotions = set()
    for phrase, stats in analytics.get("phrase_stats", {}).items():
        if phrase.lower() in protected:
            continue
        if phrase.lower() in sparingly_phrases:
            if stats.get("total_catches", 0) >= threshold:
                promotions.add(phrase)
    return promotions


def find_stale_phrases(analytics: dict, all_phrases: set[str]) -> set[str]:
    """Find blacklisted phrases not caught in 10+ sessions (may be unused)."""
    stale = set()
    total_sessions = analytics.get("_meta", {}).get("total_sessions_tracked", 0)
    for phrase, stats in analytics.get("phrase_stats", {}).items():
        if phrase.lower() in all_phrases:
            sessions_since = total_sessions - stats.get("sessions_seen", 0)
            if sessions_since >= STALE_SESSION_THRESHOLD:
                stale.add(phrase)
    return stale


def apply_evolution(
    blacklist_path: Path,
    new_phrases: list[str],
    promotions: set[str],
) -> dict:
    """Write evolution results to blacklist.json."""
    data = json.loads(blacklist_path.read_text(encoding="utf-8"))
    banned = data.get("blacklisted_phrases", [])
    sparingly = data.get("use_sparingly", [])

    added = 0
    for phrase in new_phrases:
        if phrase not in sparingly and phrase not in banned:
            sparingly.append(phrase)
            added += 1

    promoted = 0
    for phrase in promotions:
        for i, sp in enumerate(sparingly):
            if sp.lower() == phrase.lower():
                sparingly.pop(i)
                if sp not in banned:
                    banned.append(sp)
                promoted += 1
                break

    data["blacklisted_phrases"] = banned
    data["use_sparingly"] = sparingly

    meta = data.get("_meta", {})
    meta["version"] = meta.get("version", 0) + 1
    meta["last_updated"] = time.strftime("%Y-%m-%d")
    meta["last_evolution"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    data["_meta"] = meta

    blacklist_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"added": added, "promoted": promoted}


def run_evolution(
    analytics_path: Path = ANALYTICS_FILE,
    blacklist_path: Path = BLACKLIST_FILE,
) -> dict:
    """Run the full evolution cycle. Called from session-end maintenance."""
    try:
        analytics = json.loads(analytics_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"added": 0, "promoted": 0, "stale_flagged": 0, "error": "no analytics"}

    try:
        bl_data = json.loads(blacklist_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"added": 0, "promoted": 0, "stale_flagged": 0, "error": "no blacklist"}

    banned = set(p.lower() for p in bl_data.get("blacklisted_phrases", []))
    sparingly = set(p.lower() for p in bl_data.get("use_sparingly", []))
    all_phrases = banned | sparingly
    protected = frozenset(p.lower() for p in bl_data.get("protected_phrases", []))

    candidates = find_promotion_candidates(analytics, all_phrases, protected=protected)
    promotions = find_tier_promotions(analytics, sparingly, protected=protected)
    stale = find_stale_phrases(analytics, all_phrases)

    result = {"added": 0, "promoted": 0, "stale_flagged": len(stale)}
    if candidates or promotions:
        evolution_result = apply_evolution(blacklist_path, list(candidates), promotions)
        result["added"] = evolution_result["added"]
        result["promoted"] = evolution_result["promoted"]

    result["candidates"] = list(candidates)
    result["promotions"] = list(promotions)
    result["stale"] = list(stale)

    # Prune catch entries older than 30 days to prevent unbounded growth
    try:
        from analytics_utils import prune_old_catches
        result["pruned"] = prune_old_catches(max_age_days=30)
    except Exception:
        result["pruned"] = 0

    return result
