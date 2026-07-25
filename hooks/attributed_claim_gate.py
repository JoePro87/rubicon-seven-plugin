"""Attributed-claim gate (leaf; stdlib only) — spec §B, 2026-07-24.

The highest-severity fabrication class: DM invention laundered through a trusted
NPC's mouth ("Thresh told you the price is not fixed in advance"). It borrows the
NPC's authority and the player has no way to audit it.

dialogue_claim_scanner reads only text INSIDE quotes; an attributed claim is
typically OUTSIDE them. This gate is sentence-scoped reported speech:
    <CanonName> ... <ATTRIBUTION_VERB> ... <CLAIM_BODY>
verified against the distillation cache + the Revealed Ledger, or waived by any
canon-consulting tool call in the same turn.
"""

import re

_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+|\n+")

_ATTRIBUTION_RE = re.compile(
    r"\b(said|told|says|tells|promised|promises|described|describes|"
    r"confirmed|confirms|warned|warns|explained|explains|mentioned|mentions|"
    r"claimed|claims|insisted|insists|assured|assures|reported|reports|"
    r"briefed|advised|advises|indicated|noted|swore|vouched)\b", re.I)

# A report must carry content after the verb; bare manner ("said nothing",
# "said it quietly") is prose, not testimony.
_CLAIM_BODY_RE = re.compile(
    r"\b(?:that\b|about\b|:|—\s|the\s|how\s|it\s|they\s|she\s|he\s)", re.I)

# "you told Thresh" / "I said" — the canon name is the AUDIENCE, not the source.
_REVERSAL_GUARD_RE = re.compile(r"\b(you|I|we)\s+(?:\w+\s+){0,2}$", re.I)

# Not an assertion about the past record.
_MODAL_BEFORE_RE = re.compile(
    r"\b(would|will|might|may|could|should|can|if|when|whether|unless)\s+"
    r"(?:\w+\s+){0,2}$", re.I)

# Asserting the ABSENCE of a briefing is the honest move this gate encourages.
_NEGATION_BEFORE_RE = re.compile(
    r"\b(never|doesn'?t|does not|didn'?t|did not|cannot|can'?t|won'?t|"
    r"wouldn'?t|hasn'?t|hadn'?t|refuses? to|without|no\s+one|nobody)\s+"
    r"(?:\w+\s+)?$",
    re.IGNORECASE)

# "Saphora is waiting to be told whether ..." — the canon name is the RECIPIENT.
_PASSIVE_BEFORE_RE = re.compile(r"\b(be|been|being|get|got)\s+$", re.I)

_QUOTE_CHARS = '"“”‘’'

# Engine-authored; exempt exactly as in the spatial gate.
TICKER_HEADER = ">> MECHANICS (relay to player verbatim, after your prose):"

# A quote opening shortly AFTER the verb is a dialogue introduction
# (`Kess says, flat, to no one: "Of course it does"`), not a report of testimony.
_QUOTE_AFTER_RE = re.compile(r'^[^"“”‘’]{0,40}[:,—-]?\s*["“‘]')

# Distance the canon name may sit ahead of the verb.
_NAME_LOOKBACK = 40

# Fraction of the claim body's content words that must appear in the record.
_COVERAGE_THRESHOLD = 0.70

# Below this, the "claim" is manner rather than testimony ("said it quietly").
_MIN_CLAIM_CONTENT_WORDS = 2

_STOPWORDS = {
    "that", "about", "this", "these", "those", "with", "from", "into", "onto",
    "have", "has", "had", "been", "being", "were", "was", "will", "would",
    "there", "their", "them", "they", "then", "than", "what", "when", "which",
    "while", "your", "yours", "you", "and", "but", "for", "not", "the", "its",
    "it's", "her", "his", "him", "she", "hers", "ours", "also", "just", "only",
    "still", "very", "more", "most", "some", "any", "all", "each", "both",
    "here", "does", "did", "doing", "said", "told", "says", "tells", "over",
    "under", "after", "before", "because", "since", "until", "upon", "back",
}

_TAIL = (
    "\n\nPutting an unverified fact in a trusted NPC's mouth is the worst "
    "fabrication class: it borrows their authority and the player has no way to "
    "audit it.\n"
    "Legal moves, in order of preference:\n"
    "  1. search(action=\"tiered\", ...) or check_canon(...) and quote what is "
    "actually on the record.\n"
    "  2. Attribute only the verbatim canon and stop there.\n"
    "  3. Make it the DM's own uncertainty, not the NPC's testimony: "
    "\"Nobody told you what it charges.\"\n"
    "Saying plainly that something is not established is always legal; inventing "
    "an NPC briefing never is. Re-emit the turn with one of those."
)

_SATISFIERS = {"search", "check_canon", "npc", "lorebook", "files", "parley", "map"}


def _content_words(body: str) -> list:
    words = re.findall(r"[a-z][a-z'’\-]+", body.lower())
    return [w for w in words if len(w) > 3 and w not in _STOPWORDS]


_RECORD_SPLIT_RE = re.compile(r"\s*\|\s*|\n+")
_WORD_RE = re.compile(r"[a-z][a-z'’\-]+")

# Per-record inverted index, cached by blob identity. Built once per turn.
_INDEX_CACHE: dict = {"key": None, "value": None}


def _record_index(blob: str):
    """word -> set of record ids, over the ' | '/newline-separated record blob.

    Whole-blob coverage is useless at real scale: the live cache is ~500 KB, and
    almost any content word appears SOMEWHERE in it, so the 2026-07-24 string
    scored as fully covered. Support must come from a SINGLE record — that is
    what "the record says this" means.
    """
    # Cheap identity key: hashing the whole ~0.5 MB blob every turn cost more
    # than the scan itself. Length plus both ends is ample here — the blob is
    # rebuilt only when the underlying files change.
    key = (len(blob), blob[:200], blob[-200:])
    if _INDEX_CACHE["key"] == key:
        return _INDEX_CACHE["value"]
    index: dict = {}
    for rid, record in enumerate(_RECORD_SPLIT_RE.split(blob)):
        for w in _WORD_RE.findall(record):
            if len(w) > 3:
                index.setdefault(w, set()).add(rid)
    _INDEX_CACHE["key"] = key
    _INDEX_CACHE["value"] = index
    return index


def _coverage(body: str, blob: str) -> float:
    """Best fraction of the claim body's content words carried by ONE record."""
    words = _content_words(body)
    if not words:
        return 1.0  # nothing specific asserted — not this gate's business
    uniq = sorted(set(words))
    if not blob:
        return 0.0
    index = _record_index(blob)
    counts: dict = {}
    hit_any = 0
    for w in uniq:
        rids = index.get(w)
        if not rids:
            continue
        hit_any += 1
        for rid in rids:
            counts[rid] = counts.get(rid, 0) + 1
    if not counts:
        return 0.0
    best = max(counts.values())
    # A claim whose words are scattered one-per-record is NOT supported; the
    # per-record best is the honest number.
    return best / len(uniq)


def _is_dialogue_tag(sentence: str, verb_start: int, verb_end: int) -> bool:
    """True for `"Go," she said.` — a tag, not a report.

    Heuristic, deliberately narrow: a closing quote within the 12 characters
    before the verb, and no closing quote after it.
    """
    before = sentence[max(0, verb_start - 12):verb_start]
    if not any(q in before for q in _QUOTE_CHARS):
        return False
    return not any(q in sentence[verb_end:] for q in _QUOTE_CHARS)


def scan_attributed_claims(text, npc_names, verified_blob, tool_names):
    """Return violation strings for reported-speech claims lacking a source.

    npc_names:     lowercased set of canon NPC + party names.
    verified_blob: lowercased distillation-cache learnings/key_facts PLUS the
                   Revealed Ledger facts.
    tool_names:    engine tool short-names called this turn.

    Fail-open: no text or no npc_names yields [].
    """
    if not text or not npc_names:
        return []
    if set(tool_names or []) & _SATISFIERS:
        return []
    blob = (verified_blob or "").lower()
    names = {n for n in npc_names if n and len(n) >= 3}
    idx = text.find(TICKER_HEADER)
    prose = text[:idx] if idx >= 0 else text
    hits = []
    for sentence in _SENTENCE_SPLIT_RE.split(prose):
        if len(sentence) < 12:
            continue
        low = sentence.lower()
        for m in _ATTRIBUTION_RE.finditer(sentence):
            before = sentence[:m.start()]
            if _NEGATION_BEFORE_RE.search(before):
                continue
            if _MODAL_BEFORE_RE.search(before):
                continue
            if _REVERSAL_GUARD_RE.search(before):
                continue
            if _PASSIVE_BEFORE_RE.search(before):
                continue
            if _is_dialogue_tag(sentence, m.start(), m.end()):
                continue
            body = sentence[m.end():]
            if _QUOTE_AFTER_RE.match(body):
                continue  # dialogue introduction, not reported testimony
            if not _CLAIM_BODY_RE.search(body):
                continue
            # Manner, not testimony: "Vela said it quietly" satisfies the loose
            # claim-body pattern but asserts no checkable content. A report needs
            # at least two content words to be a report about anything.
            if len(set(_content_words(body))) < _MIN_CLAIM_CONTENT_WORDS:
                continue
            window = low[max(0, m.start() - _NAME_LOOKBACK):m.start()]
            speaker = next(
                (n for n in names
                 if re.search(rf"(?<!\w){re.escape(n)}(?!\w)", window)), None)
            if not speaker:
                continue
            cov = _coverage(body, blob)
            if cov >= _COVERAGE_THRESHOLD:
                continue
            hits.append(
                f'ATTRIBUTED CLAIM WITHOUT SOURCE: "{sentence.strip()[:200]}" — '
                f"this attributes a briefing to {speaker.title()} that neither the "
                f"distillation cache nor the Revealed Ledger supports (content "
                f"coverage {int(cov * 100)}%), and no "
                f"search()/check_canon()/npc()/lorebook() call was made this turn."
            )
            break  # one violation per sentence
        if len(hits) >= 3:
            break
    return hits


def block_tail() -> str:
    return _TAIL
