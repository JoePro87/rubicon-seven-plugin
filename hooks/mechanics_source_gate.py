"""A0.2 — mechanics-from-tools detector (leaf; stdlib only).

A narrated mechanical resolution (HP delta, AV, forced check, dice, condition,
rule label) must be backed by a governing engine tool call in the same turn.
Deterministic: regex classes -> satisfying tool sets. The engine-authored
'>> MECHANICS' ticker block is exempt (tool-backed by construction).
"""
import re

TICKER_HEADER = ">> MECHANICS (relay to player verbatim, after your prose):"

_CLASSES = [
    ("HP delta", re.compile(r"\b(?:takes?|took|taking|deals?|dealt|suffer(?:s|ed)?|los(?:e|es|t)|costs?|drains?|restor(?:es|ed)|heals?|regains?)\s+(?:\w+\s+){0,2}?\d+\s*(?:HP|hit\s*points?|damage)\b", re.IGNORECASE),
     {"combat", "character", "gift", "rest", "affliction", "roll"}),
    ("HP fraction", re.compile(r"\b\d+\s*/\s*\d+\s*HP\b", re.IGNORECASE),
     {"combat", "character", "rest"}),
    ("armour value", re.compile(r"\bAV\s*\d+\b"),
     {"combat", "lookup", "character"}),
    ("forced check", re.compile(r"\b(?:make|roll|attempt)s?\s+(?:a|an|the)\s+(?:\w+\s+){0,2}?(?:check|save|saving\s+throw)\b", re.IGNORECASE),
     {"roll", "combat"}),
    ("dice notation", re.compile(r"\b\d+d\d+\b"),
     {"roll", "combat", "gift", "lookup", "generate"}),
    ("rule label", re.compile(r"\bhouse\s*[- ]?rules?\b", re.IGNORECASE),
     {"rulebook", "lookup"}),
    ("condition applied", re.compile(r"\b(?:you\s+are\s+now|gains?|is\s+now|becomes?)\s+(?:deprived|poisoned|bleeding|stunned|blinded|deafened|paralyzed|diseased|infected)\b", re.IGNORECASE),
     {"affliction", "combat", "character", "lookup"}),
]


def scan_unbacked_mechanics(text, tool_names):
    if not text:
        return []
    idx = text.find(TICKER_HEADER)
    prose = text[:idx] if idx >= 0 else text
    called = set(tool_names or [])
    hits = []
    for label, rx, satisfiers in _CLASSES:
        if called & satisfiers:
            continue
        for m in rx.finditer(prose):
            hits.append(
                f'MECHANICS WITHOUT TOOL: "{m.group(0)}" ({label}) — narrate this only '
                f"from a {'/'.join(sorted(satisfiers))} call this turn; the number/effect "
                f"must come from the tool, not the prose. Legal moves: make the call, or "
                f"cut the mechanic from the narration."
            )
            break  # one violation per class is enough to block
    return hits
