"""The reflex editor: one per-turn block, one budget (Reflex Layer Component 3).

Spec: docs/superpowers/specs/2026-06-10-reflex-layer-design.md.
Pure composition + snapshot diff. The hook (phrase_reminder.py) owns all I/O.
Cap default ~600 chars ≈ ~150 tokens; override env RUBICON_REFLEX_CAP_CHARS.
"""
import os
from dataclasses import dataclass

URGENT, CHANGED, AMBIENT = 0, 1, 2

DEFAULT_CAP = int(os.environ.get("RUBICON_REFLEX_CAP_CHARS", "600"))


@dataclass
class Entry:
    tier: int
    text: str


def compose(entries, cap_chars: int = None) -> str:
    cap = DEFAULT_CAP if cap_chars is None else cap_chars
    live = [e for e in entries if e.text]
    if not live:
        return ""
    urgent = [e.text for e in live if e.tier == URGENT]
    rest = [e for e in live if e.tier != URGENT]
    rest.sort(key=lambda e: e.tier)  # stable: CHANGED before AMBIENT
    lines = list(urgent)
    used = sum(len(t) + 1 for t in lines)
    dropped = 0
    for e in rest:
        cost = len(e.text) + 1
        if used + cost > cap:
            dropped += 1
            continue
        lines.append(e.text)
        used += cost
    if not lines:
        return ""
    if dropped:
        lines.append(f"(+{dropped} quiet)")
    return "\n".join(lines)


def diff_lines(old: dict, new: dict) -> list:
    """Δ lines for keys whose value changed. Keys are 'kind:label' strings;
    only the label (after the first ':') renders — include the metric name in
    the label when kinds can collide on the same subject (e.g. 'wounds:Mira
    wounds' and 'load:Mira load' render as distinct Δ lines).
    Empty old snapshot (session start) -> no lines."""
    if not old:
        return []
    out = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if a == b:
            continue
        label = key.split(":", 1)[1] if ":" in key else key
        out.append(f"Δ {label} {a if a is not None else 'none'}→{b if b is not None else 'none'}")
    return out
