"""Deterministic fabrication detectors for the Gate.

Three concerns, all checked against a draft before output:
  - check_pet_names: campaign-defined bond-names no NPC may speak outside *bond* text.
  - check_tripwires: documented per-character rules the written tripwires failed to hold.
  - check_narration_claims (Task 4): relationship/job claims about named canon characters
    stated in narrator voice, cross-checked against the distillation cache.

Campaign-specific pet-names and tripwires are DATA, not code: they load from
``fabrication_tripwires.json`` in the campaign directory (fail-open — a missing
or malformed file just means no campaign-specific guards). Only setting-generic
book rules are built in. LEAF: never imports server.
"""

import json
import os
import re
from pathlib import Path

# Strip *bond* italic spans (the sanctioned private channel) before scanning.
_BOND_SPAN_RE = re.compile(r"\*[^*]+\*", re.DOTALL)

# --- Built-in tripwires: setting-generic BOOK rules only, never campaign facts ---
_BUILTIN_TRIPWIRES = [
    (r"\b(dissolving thread|kronophage'?s echo|mystic gift|telekinesis|telepathy)\b",
     r"\b(psy\s+save|save\s+(to|against)|saving throw|must save|roll(ed)?\s+to\s+resist)\b",
     "TRIPWIRE: Mystic Gifts always work at the cost of HP — they require NO save."),
]

_CAMPAIGN_RULES_FILE = "fabrication_tripwires.json"


def _campaign_rules() -> dict:
    """Load campaign pet-names/tripwires from the campaign dir; fail-open to empty.

    Read per call (the file is tiny and the checks run on Stop/gate cadence, not
    in a hot loop) so edits and test seeding take effect without cache games.
    """
    try:
        root = os.environ.get("RUBICON_CAMPAIGN_DIR")
        if not root:
            return {}
        path = Path(root) / _CAMPAIGN_RULES_FILE
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def check_pet_names(text: str) -> list[str]:
    entries = _campaign_rules().get("forbidden_pet_names", [])
    if not entries:
        return []
    scannable = _BOND_SPAN_RE.sub("", text)
    low = scannable.lower()
    hits = []
    for entry in entries:
        name = (entry.get("name") or "").lower() if isinstance(entry, dict) else ""
        if name and re.search(rf"\b{re.escape(name)}\b", low):
            hits.append(entry.get("message") or (
                f'PET-NAME VIOLATION: "{name}" is an intimate bond-name; '
                f'no NPC may speak it.'))
    return hits


# Sentence boundaries — a tripwire fires only when subject AND action co-occur
# within the SAME sentence, to avoid cross-sentence false positives.
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+|\n+")


def _active_tripwires() -> list[tuple[re.Pattern, re.Pattern, str]]:
    """Built-in book-rule tripwires + campaign tripwires; bad entries are skipped."""
    wires = [(re.compile(s, re.I), re.compile(c, re.I), m)
             for s, c, m in _BUILTIN_TRIPWIRES]
    for entry in _campaign_rules().get("tripwires", []):
        try:
            wires.append((re.compile(entry["subject"], re.I),
                          re.compile(entry["context"], re.I),
                          entry["message"]))
        except Exception:
            continue
    return wires


# Negation guard (2026-07-20, live-corpus probe): the rule-STATING sentence
# "Creenash never eats" tripped the Creenash-eats tripwire. A context match
# directly preceded by a negation (one intervening adverb allowed: "never
# actually eats") asserts the rule rather than violating it — skip it.
_NEGATION_BEFORE_RE = re.compile(
    r"\b(never|doesn'?t|does not|cannot|can'?t|won'?t|wouldn'?t|"
    r"refuses? to|without)\s+(?:\w+\s+)?$",
    re.IGNORECASE)


def check_tripwires(text: str) -> list[str]:
    sentences = _SENTENCE_SPLIT_RE.split(text)
    hits = []
    for subject_re, context_re, msg in _active_tripwires():
        for s in sentences:
            if not subject_re.search(s):
                continue
            if any(not _NEGATION_BEFORE_RE.search(s[:m.start()])
                   for m in context_re.finditer(s)):
                hits.append(msg)
                break
    return hits


# --- Narration claims: job/relationship assertions about named canon characters ---

# Narration relationship pass uses ONLY high-precision familial verbs — NOT the broad
# dialogue verb set, and NOT ambiguous words like "raised" (raised a weapon) or
# "betrayed" (betrayed her fear), which would cry wolf on ordinary narration.
_NARRATION_RELATIONSHIP_RE = re.compile(
    r"\b(married|wedded|wed|betrothed|espoused|widowed|divorced|"
    r"fathered|mothered|sired|orphaned|disowned)\b", re.IGNORECASE)

# Strip quoted dialogue AND *bond* text — narration scanner only inspects narrator voice.
_DIALOGUE_OR_BOND_RE = re.compile(r'"[^"]*"|"[^"]*"|\*[^*]+\*', re.DOTALL)

# "<Name>, the <role>," — a comma/period-bounded appositive only. The reversed
# "the <word> <Name>" form was removed and a closing-punctuation lookahead added,
# because both matched structural nouns ("the wind Kael", "Bugsie, the smallest of
# them") and cried wolf on ordinary narration.
_APPOSITIVE_RE = re.compile(r"\b([A-Z][a-z]+),\s+the\s+([a-z]+)(?=[,.])")

# --- Tracked-entity quantity claims in narration (D135 complaint 2c) ---
# "Somewhere in this hall there is a way to file four petitions" sailed through
# because the quantity scanner only reads quoted dialogue. Narration gets a
# NARROW version: numerals attached to nouns the campaign declares tracked
# (``tracked_quantity_nouns`` in fabrication_tripwires.json). Noun-list-driven
# by construction so ordinary scenery counts ("three doors") never flag.
try:
    from hooks.dialogue_claim_scanner import _COMPOUNDS, _BASE_NUMBERS
except ImportError:
    from dialogue_claim_scanner import _COMPOUNDS, _BASE_NUMBERS

# Concrete numbers only — vague quantifiers ("many", "several", "countless")
# are legitimate narration texture, not checkable counts.
_VAGUE_QUANTIFIERS = {"many", "several", "few", "countless", "dozens",
                      "hundreds", "thousands"}
_CONCRETE_NUMBER_WORDS = "|".join(
    _COMPOUNDS + [n for n in _BASE_NUMBERS if n not in _VAGUE_QUANTIFIERS])

_TRACKED_QTY_CACHE: dict = {"key": None, "regex": None}


def _tracked_quantity_re():
    """Compiled numeral+tracked-noun regex, rebuilt only when the noun list changes."""
    nouns = _campaign_rules().get("tracked_quantity_nouns", [])
    key = tuple(sorted({str(n).strip().lower() for n in nouns if str(n).strip()}))
    if not key:
        return None
    if _TRACKED_QTY_CACHE["key"] != key:
        alternation = "|".join(re.escape(n) for n in key)
        _TRACKED_QTY_CACHE["regex"] = re.compile(
            rf"\b(\d+|{_CONCRETE_NUMBER_WORDS})[\s-]+({alternation})\b",
            re.IGNORECASE)
        _TRACKED_QTY_CACHE["key"] = key
    return _TRACKED_QTY_CACHE["regex"]


def _all_tokens_present(blob: str, *tokens) -> bool:
    # All given tokens must appear as whole words. An empty cache blob means everything
    # is unverified, so claims flag by default.
    return all(re.search(rf"\b{re.escape(t.lower())}\b", blob) for t in tokens if t)


# --- Combat mechanics leak detector (Iron Law 6 backstop) ---
# Each pattern is compiled once at module load for speed.

# Literal field names that should never appear in player-facing prose.
_COMBAT_FIELD_RE = re.compile(r"\b(damage_type|engine_tags)\b", re.IGNORECASE)

# "to_hit" or "to-hit" (internal stat reference).
_TO_HIT_RE = re.compile(r"\bto[_-]hit\b", re.IGNORECASE)

# Dice-roll LEAKS — mechanically anchored so ordinary physical rolling
# ("the cart rolls 3 feet", "she rolls 3 knucklebones") never trips.
# The article "a", the "roll of N" idiom, or a to-hit/vs anchor marks a die score.
_ROLL_A_NUMBER_RE = re.compile(r"\broll(?:ed|s|ing)?\s+a\s+\d+\b", re.IGNORECASE)
_ROLL_OF_NUMBER_RE = re.compile(r"\b(?:a\s+)?roll\s+of\s+\d+\b", re.IGNORECASE)
_ROLL_VS_RE = re.compile(
    r"\broll(?:ed|s)?\s+\d+\s+(?:to[\s_-]?hit|vs\.?|versus|against)\b", re.IGNORECASE)
# Dice notation "3d12", "2d8", "1d20" — unambiguous mechanics, never in narrative.
_DICE_NOTATION_RE = re.compile(r"\b\d+d\d+\b", re.IGNORECASE)

# HP fraction: "12/29 HP" — raw hit-point values.
_HP_FRACTION_RE = re.compile(r"\b\d+\s*/\s*\d+\s*HP\b", re.IGNORECASE)

_COMBAT_PATTERNS: list[tuple[re.Pattern, str]] = [
    (_COMBAT_FIELD_RE,    "field name (damage_type/engine_tags)"),
    (_TO_HIT_RE,          "to-hit reference"),
    (_ROLL_A_NUMBER_RE,   "exposed die score (roll a N)"),
    (_ROLL_OF_NUMBER_RE,  "exposed die score (roll of N)"),
    (_ROLL_VS_RE,         "exposed roll vs target"),
    (_DICE_NOTATION_RE,   "dice notation"),
    (_HP_FRACTION_RE,     "HP fraction"),
]


def check_combat_mechanics(text: str) -> list[str]:
    """Return a violation string for each leaked combat mechanic found in *text*.

    Flags: damage_type / engine_tags field names, to_hit / to-hit references,
    mechanically-anchored die-score leaks ("rolls a 18", "a roll of 15",
    "rolled 12 vs the raider"), dice notation ("3d12"), and raw HP fractions
    ("12/29 HP"). Ordinary physical rolling ("the cart rolls 3 feet") is NOT
    flagged. Returns [] when the text is clean narrative prose.
    """
    hits = []
    for pattern, label in _COMBAT_PATTERNS:
        for m in pattern.finditer(text):
            hits.append(
                f'COMBAT MECHANIC LEAK: "{m.group()}" ({label}) — '
                f"render as prose, not numbers (Iron Law 6)"
            )
    return hits


def check_narration_claims(text: str, known_names: set, cache_facts_blob: str = "") -> list[str]:
    """Flag relationship/job claims in NARRATION about a named canon character that the
    distillation cache does not support.

    Args:
        text: the draft.
        known_names: lowercase canon character names (from npc_states.json / party).
        cache_facts_blob: lowercase concatenation of cache key_facts + learnings.
    """
    narration = _DIALOGUE_OR_BOND_RE.sub("", text)
    low_blob = (cache_facts_blob or "").lower()
    hits = []

    # 1) Appositive job/role claims: "<Name>, the <job>,"
    for m in _APPOSITIVE_RE.finditer(narration):
        name = m.group(1).lower()
        job = m.group(2).lower()
        if name in known_names and job and not _all_tokens_present(low_blob, name, job):
            hits.append(
                f'NARRATION CLAIM: "{name} … {job}" — unverified role for a canon '
                f'character. Verify via lorebook(view, "{name}") / npc(get) before output.'
            )

    # 2) Familial relationship claims in narration, scoped to the sentence.
    for sentence in _SENTENCE_SPLIT_RE.split(narration):
        m = _NARRATION_RELATIONSHIP_RE.search(sentence)
        if not m:
            continue
        low_sent = sentence.lower()
        named = [n for n in known_names if re.search(rf"\b{re.escape(n)}\b", low_sent)]
        if named and not _all_tokens_present(low_blob, m.group(0).lower()):
            hits.append(
                f'NARRATION CLAIM: relationship "{m.group(0)}" asserted about '
                f'{named[0]} — verify before output.'
            )

    # 3) Quantities attached to campaign-tracked entities. Verified when BOTH
    # the numeral and the noun appear in the cache blob (so "three petitions"
    # passes against "three outstanding departure petitions"); anything else
    # flags — an unsupported count of a tracked thing is exactly the D135 error.
    qty_re = _tracked_quantity_re()
    if qty_re is not None:
        for m in qty_re.finditer(narration):
            if _all_tokens_present(low_blob, m.group(1).lower(), m.group(2).lower()):
                continue
            hits.append(
                f'NARRATION CLAIM: "{m.group(0)}" — unverified count of a tracked '
                f'entity. Verify the number (thread/search/lorebook) before asserting it.'
            )
    return hits
