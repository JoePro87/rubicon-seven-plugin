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
import re
import time
from collections import Counter
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


# ---------------------------------------------------------------------------
# Construction-frame (template) detection
#
# The phrase mechanism above bans literal strings. But the DM's prose mutates
# AROUND literal bans into recurring syntactic FRAMES ("the way she grips a
# rail" / "the way weather clears" are one frame, two strings). These helpers
# detect those frames and NOMINATE them for owner review — they NEVER auto-ban.
# ---------------------------------------------------------------------------

_PRONOUNS = frozenset(
    {"she", "he", "they", "it", "you", "we", "her", "his", "their", "its"}
)
_STOPWORDS = frozenset(
    {"the", "a", "an", "of", "and", "to", "in", "on", "at", "with", "for",
     "as", "is", "was", "it"}
)
_SLOTS = frozenset({"<N>", "<P>", "<#>"})
_SENTENCE_SPLIT = re.compile(r"[.!?;]")
_NUMBER = re.compile(r"^\d[\d,.]*$")


def _tokenize_sentence(sentence: str) -> list[str]:
    """Normalize one sentence into slotted tokens.

    Pronouns -> <P>, capitalized mid-sentence words (proper nouns) -> <N>,
    numbers -> <#>, everything else lowercased. Punctuation is stripped from
    tokens. The first real word is the sentence start, never a proper noun.
    """
    tokens: list[str] = []
    word_index = 0
    for raw in sentence.split():
        core = raw.strip(".,!?;:\"'()[]{}—–…“”‘’`")
        if not core:
            continue
        lower = core.lower()
        if lower in _PRONOUNS:
            tokens.append("<P>")
        elif word_index > 0 and core[0].isupper() and core.isalpha():
            tokens.append("<N>")
        elif _NUMBER.match(core):
            tokens.append("<#>")
        else:
            tokens.append(lower)
        word_index += 1
    return tokens


def _has_content(gram: tuple[str, ...]) -> bool:
    """True if the frame has at least one non-stopword, non-slot token."""
    return any(t not in _STOPWORDS and t not in _SLOTS for t in gram)


def _sentence_frames(tokens: list[str]) -> list[str]:
    out: list[str] = []
    for n in (3, 4, 5):
        for i in range(len(tokens) - n + 1):
            gram = tuple(tokens[i:i + n])
            if _has_content(gram):
                out.append(" ".join(gram))
    return out


def extract_frames(text: str) -> list[str]:
    """Normalize prose into slotted 3-, 4-, and 5-token construction frames."""
    frames: list[str] = []
    for sentence in _SENTENCE_SPLIT.split(text):
        frames.extend(_sentence_frames(_tokenize_sentence(sentence)))
    return frames


def _contains(long_toks: list[str], short_toks: list[str]) -> bool:
    n = len(short_toks)
    return any(long_toks[i:i + n] == short_toks
               for i in range(len(long_toks) - n + 1))


def find_template_candidates(
    prose_samples: list[str],
    min_count: int = 8,
    existing_patterns: list[str] = None,
) -> list[dict]:
    """Count construction frames across samples; return those over threshold.

    Returns [{"frame", "count", "example"}, ...] sorted by count desc. Frames
    whose representative example is already caught by an existing structural
    regex are filtered out (invalid regexes are skipped). A 3-gram that only
    ever occurs inside exactly one surviving longer candidate is collapsed away
    in favour of that longer frame.
    """
    compiled = []
    for pat in existing_patterns or []:
        try:
            compiled.append(re.compile(pat, re.IGNORECASE))
        except re.error:
            continue

    counts: Counter = Counter()
    examples: dict[str, str] = {}
    for sample in prose_samples:
        for sentence in _SENTENCE_SPLIT.split(sample):
            snippet = sentence.strip()
            if not snippet:
                continue
            for frame in _sentence_frames(_tokenize_sentence(sentence)):
                counts[frame] += 1
                examples.setdefault(frame, snippet)

    # threshold + existing-pattern filter (drop frames the live regexes cover)
    surviving = {
        frame: n for frame, n in counts.items()
        if n >= min_count
        and not any(rx.search(examples[frame]) for rx in compiled)
    }

    # sub-frame collapse: a 3-gram whose every occurrence is accounted for by a
    # longer surviving candidate (same count) carries no independent signal —
    # keep the longer frame instead.
    tok_map = {frame: frame.split() for frame in surviving}
    longer = [f for f in surviving if len(tok_map[f]) >= 4]
    drop: set[str] = set()
    for frame in surviving:
        if len(tok_map[frame]) != 3:
            continue
        containers = [L for L in longer
                      if surviving[L] == surviving[frame]
                      and _contains(tok_map[L], tok_map[frame])]
        if containers:
            drop.add(frame)

    results = [
        {"frame": frame, "count": surviving[frame], "example": examples[frame]}
        for frame in surviving if frame not in drop
    ]
    results.sort(key=lambda d: (-d["count"], d["frame"]))
    return results


def run_template_scan(
    prose_samples: list[str],
    blacklist_path: Path = BLACKLIST_FILE,
    nominated_date: str = None,
    min_count: int = 8,
) -> dict:
    """Scan prose for recurring construction frames and NOMINATE them.

    Writes candidates into blacklist.json under the ``template_nominations``
    key (each {"frame", "count", "example", "nominated", "status": "pending"}).
    NEVER writes into blacklisted_phrases / structural_patterns — nomination
    only, for owner review. Existing frames (any status) are not re-nominated;
    every other blacklist key is preserved untouched.

    WIRING NOTE: no raw prose currently flows into ``run_evolution`` (analytics
    only carries phrase_stats). To activate this, server.py's
    ``_run_prose_evolution`` should pass the committed session's narration text
    (split into samples) to this function alongside the existing evolution call.
    """
    data = json.loads(blacklist_path.read_text(encoding="utf-8"))
    existing_patterns = [p.get("pattern", "")
                         for p in data.get("structural_patterns", [])]
    candidates = find_template_candidates(
        prose_samples, min_count=min_count, existing_patterns=existing_patterns
    )

    noms = data.setdefault("template_nominations", [])
    already = {n.get("frame") for n in noms}
    date = nominated_date or time.strftime("%Y-%m-%d")

    nominated = 0
    for cand in candidates:
        if cand["frame"] in already:
            continue
        noms.append({
            "frame": cand["frame"],
            "count": cand["count"],
            "example": cand["example"],
            "nominated": date,
            "status": "pending",
        })
        already.add(cand["frame"])
        nominated += 1

    if nominated:
        blacklist_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    return {"nominated": nominated, "candidates": len(candidates)}


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
