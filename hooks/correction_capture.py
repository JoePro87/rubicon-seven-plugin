"""The learning loop: turn a player correction into a permanent fix.

Runs on the player's turn (UserPromptSubmit). When the player's message looks like a
correction of the DM's previous turn, an extractor (Haiku by default, injectable for
tests) pulls out {entity, wrong_terms, correct_fact, failure_mode, participants}. The
correct fact is written to the distillation cache (re-enters context via check_canon);
the wrong claim is written to the never-again list (the Gate hard-blocks it forever).

Fail-open and silent: any failure leaves game state untouched and never surfaces.
"""

import json
import os
import re
from pathlib import Path

try:
    from hooks.canon_facts_seed import build_identity_entry, build_relationship_entry
except ImportError:
    from canon_facts_seed import build_identity_entry, build_relationship_entry

# Signals mined from real play: ALL-CAPS shouting, explicit corrections, parentheticals.
_CORRECTION_PHRASES = [
    "no,", "no.", "nope", "wrong", "that's not", "thats not", "not a ", "not the ",
    "you made that up", "made it up", "you invented", "didn't happen", "never happened",
    "isn't", "is not", "incorrect", "should be",
]


def looks_like_correction(message: str) -> bool:
    if not message or len(message.strip()) < 3:
        return False
    m = message.strip()
    # Parenthetical aside that contains a corrective phrase.
    if m.startswith("(") and any(p in m.lower() for p in _CORRECTION_PHRASES):
        return True
    # Shouting: a run of ALL-CAPS words (>=2 letters) signals frustration at an error.
    if re.search(r"\b[A-Z]{2,}\b(?:\s+\b[A-Z]{2,}\b)?", m) and any(
            p in m.lower() for p in _CORRECTION_PHRASES):
        return True
    # Plain explicit correction.
    low = m.lower()
    return any(low.startswith(p) or f" {p}" in low for p in
               ("no,", "no.", "nope", "wrong", "that's not", "you made that up",
                "never happened", "incorrect"))


def _default_extractor(prior_dm: str, correction: str):
    """Haiku extraction of the corrected fact. Returns dict or None. Fail-open."""
    try:
        import anthropic
    except ImportError:
        return None
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        kp = Path.home() / ".rubicon-seven" / "api_key"
        api_key = kp.read_text(encoding="utf-8").strip() if kp.exists() else None
    if not api_key:
        return None
    tool = {
        "name": "record_correction",
        "description": "Extract the corrected canon fact from a player's correction of the DM.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "The canon character/thing corrected."},
                "wrong_terms": {"type": "array", "items": {"type": "string"},
                                "description": "1-3 distinctive words from the WRONG claim (e.g. ['botanist'])."},
                "correct_fact": {"type": "string", "description": "The corrected fact, one sentence."},
                "failure_mode": {"type": "string"},
                "participants": {"type": "array", "items": {"type": "string"},
                                 "description": "If a relationship, the 2 people; else just [entity]."},
                "is_correction": {"type": "boolean"},
            },
            "required": ["entity", "wrong_terms", "correct_fact", "failure_mode",
                         "participants", "is_correction"],
        },
    }
    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=5)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=512,
            system=("Extract the corrected canon fact. The DM said something; the player "
                    "corrected it. Identify the entity, the wrong words, and the right fact. "
                    "Set is_correction=false if the player is NOT correcting a fact."),
            messages=[{"role": "user",
                       "content": f"DM SAID:\n{prior_dm}\n\nPLAYER CORRECTION:\n{correction}"}],
            tools=[tool], tool_choice={"type": "tool", "name": "record_correction"},
        )
        for block in resp.content:
            if getattr(block, "type", None) == "tool_use":
                payload = getattr(block, "input", None)
                if isinstance(payload, dict) and payload.get("is_correction"):
                    return payload
        return None
    except Exception:
        return None


def capture_correction(prior_dm, correction, cache, bans, extractor=None,
                       session_id="unknown", turn=0) -> bool:
    """Extract a correction and persist it. Returns True if a fix was written."""
    extractor = extractor or _default_extractor
    try:
        data = extractor(prior_dm, correction)
    except Exception:
        return False
    if not data:
        return False
    entity = (data.get("entity") or "").strip()
    correct_fact = (data.get("correct_fact") or "").strip()
    wrong_terms = [t for t in data.get("wrong_terms", []) if t.strip()]
    if not entity or not correct_fact or not wrong_terms:
        return False

    # 1) Permanent ban on the wrong claim.
    bans.add_ban(entity=entity, wrong_terms=wrong_terms, correct_fact=correct_fact,
                 failure_mode=data.get("failure_mode", "unknown"),
                 session_id=session_id, turn=turn)

    # 2) Right fact into the cache (re-enters context via check_canon).
    participants = [p for p in data.get("participants", []) if p.strip()]
    key_facts = wrong_terms_to_facts(correct_fact)
    try:
        if len(participants) >= 2:
            entry = build_relationship_entry(participants, correct_fact, key_facts, session_id)
        else:
            entry = build_identity_entry(entity, correct_fact, key_facts, session_id)
        cache.put(entry)
    except Exception:
        pass  # ban already written; cache write is best-effort
    return True


def wrong_terms_to_facts(correct_fact: str):
    """Minimal key_facts list from the corrected sentence (the sentence itself)."""
    return [correct_fact]


_CORPUS_SIGNALS = re.compile(
    r"what the fuck|\bthe fuck\b|making shit up|make shit up|made (that|it|this) up|"
    r"hallucinat|that'?s wrong|you'?re wrong|not canon|never happened|didn'?t happen|"
    r"\bnope\b|\bstop making\b|you made (that|it) up|that never happened|you invented",
    re.IGNORECASE,
)


def _transcript_msg_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(b.get("text", "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def extract_corrections_from_transcript(path) -> list:
    """Scan a Claude Code transcript (.jsonl) for player messages that look like
    corrections, each paired with the immediately preceding assistant (DM) message.

    Returns records shaped like _halluc_results.json hallucinations entries:
      {is_hallucination: True, what_dm_got_wrong: <prior DM text>, player_signal: <player text>}
    The net is intentionally wide; the bootstrap's per-record extractor filters non-corrections.
    """
    from pathlib import Path
    records = []
    last_assistant = ""
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        msg = obj.get("message") or obj
        if not isinstance(msg, dict):
            continue
        role = msg.get("role") or obj.get("type")
        text = _transcript_msg_text(msg.get("content"))
        if role == "assistant" and text:
            last_assistant = text
        elif role == "user" and text:
            # Skip tool-result / hook-echo turns (not real player speech).
            # Heuristic on the raw line: tool-result/hook-echo turns aren't real player speech.
            low = text.lower()
            if "tool_use_id" in line or "stop hook" in low or "pretooluse" in low:
                continue
            if _CORPUS_SIGNALS.search(text) and last_assistant:
                records.append({
                    "is_hallucination": True,
                    "what_dm_got_wrong": last_assistant[:2000],
                    "player_signal": text[:1000],
                })
    return records


def bootstrap_from_halluc_results(path, cache, bans, extractor=None,
                                  session_id="seed-corpus") -> int:
    """One-time seed: turn each confirmed historical hallucination into a permanent ban +
    a cache fact, reusing the live extraction brain. Returns count seeded. Fail-open.

    Reads the halluc-hunt output:
      {"hallucinations": [ {is_hallucination, what_dm_got_wrong, player_signal, ...} ]}
    The (what_dm_got_wrong, player_signal) pair IS the (DM-said, player-correction) pair.
    """
    from pathlib import Path
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return 0
    if not isinstance(data, dict):
        return 0
    records = data.get("hallucinations") or data.get("all") or []
    if not isinstance(records, list):
        return 0
    seeded = 0
    for r in records:
        if not r.get("is_hallucination"):
            continue
        prior = r.get("what_dm_got_wrong", "")
        corr = r.get("player_signal", "")
        if not prior or not corr:
            continue
        if capture_correction(prior_dm=prior, correction=corr, cache=cache, bans=bans,
                              extractor=extractor, session_id=session_id, turn=0):
            seeded += 1
    return seeded
