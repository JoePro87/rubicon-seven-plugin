"""Session-scoped spatial assertion register (leaf; stdlib only) — spec §D.

NOT a general contradiction detector. Spec §D.1 declares that infeasible and
forbids attempting it: `.prose_window.jsonl` has no session boundary, no turn id
and no day, and semantic clustering of free prose costs a model call per turn.

What IS typed and extractable is the 2026-07-24 shape: a BEARING or a DISTANCE
between two named canon entities, asserted more than one way inside a single
session. Two relations only. Session-scoped by construction, which sidesteps
"canon legitimately changed between sessions". ADVISORY — never blocks, because
the extraction is heuristic and a false contradiction that blocks a turn is
worse than one that prints a line the DM can settle with a single tool call.
"""

import json
import re
from pathlib import Path

_REGISTER_FILE = ".spatial_register.json"

_OPPOSITE = {
    "north": "south", "south": "north", "east": "west", "west": "east",
    "northeast": "southwest", "southwest": "northeast",
    "northwest": "southeast", "southeast": "northwest",
    "upstream": "downstream", "downstream": "upstream",
    "leeward": "windward", "windward": "leeward",
}

# Surface forms -> canonical compass word.
_DIR_ALIAS = {
    "northern": "north", "northward": "north",
    "southern": "south", "southward": "south",
    "eastern": "east", "eastward": "east",
    "western": "west", "westward": "west",
}

_UNIT_TO_MILES = {
    "mile": 1.0, "miles": 1.0, "mi": 1.0,
    "league": 3.0, "leagues": 3.0,
    "hex": 6.0, "hexes": 6.0,
    "km": 0.621371, "kilometre": 0.621371, "kilometres": 0.621371,
    "klick": 0.621371, "klicks": 0.621371,
}

_DISTANCE_VALUE_RE = re.compile(
    r"(\d[\d,\.]*)\s*([a-z]+)", re.IGNORECASE)

_TOLERANCE = 0.10


def _canon_direction(value: str) -> str:
    """Reduce a raw direction phrase to a canonical compass word, or ''."""
    v = (value or "").strip().lower()
    v = re.sub(r"^due\s+", "", v)
    v = v.replace("-", "").replace(" ", "")
    if v in _OPPOSITE:
        return v
    if v in _DIR_ALIAS:
        return _DIR_ALIAS[v]
    return v


def _canon_distance(value: str):
    """Return miles as a float, or None when unparseable."""
    m = _DISTANCE_VALUE_RE.search(value or "")
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    unit = m.group(2).lower()
    factor = _UNIT_TO_MILES.get(unit)
    if factor is None:
        return None
    return num * factor


def normalize_assertion(subject, relation, obj, value=None):
    """Return (key, normalized_value), order-independent.

    The pair is sorted so `A west-of B` and `B east-of A` collapse to the same
    key; when sorting flips the pair, a bearing value is flipped with it, so the
    two agreeing statements compare equal instead of contradicting.
    """
    a = (subject or "").strip().lower()
    b = (obj or "").strip().lower()
    rel = (relation or "").strip().lower()
    val = value

    if rel == "bearing":
        val = _canon_direction(value)
    elif rel == "distance":
        miles = _canon_distance(value)
        val = miles if miles is not None else None

    # '@scene' is a positional anchor, not a place — never reorder against it.
    if b != "@scene" and a != "@scene" and b < a:
        a, b = b, a
        if rel == "bearing" and val in _OPPOSITE:
            val = _OPPOSITE[val]

    return f"{a}|{rel}|{b}", val


def _path(campaign_dir) -> Path:
    return Path(campaign_dir) / _REGISTER_FILE


def _load(campaign_dir, session_id) -> dict:
    """Read the register, resetting it wholesale when the session changes."""
    fresh = {"session_id": session_id, "assertions": {}}
    try:
        p = _path(campaign_dir)
        if not p.exists():
            return fresh
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("assertions"), dict):
            return fresh
        if data.get("session_id") != session_id:
            return fresh
        return data
    except Exception:
        return fresh


def _values_agree(relation, old, new) -> bool:
    if relation == "distance":
        if old is None or new is None:
            return True
        try:
            hi = max(abs(float(old)), abs(float(new)))
            if hi == 0:
                return True
            return abs(float(old) - float(new)) / hi <= _TOLERANCE
        except Exception:
            return True
    if old is None or new is None or old == "" or new == "":
        return True
    return old == new


def record(campaign_dir, session_id, key, value, turn_text_excerpt, turn=None):
    """Append (key -> value) to the session register.

    Returns a list of advisory violation strings when the SAME key was already
    recorded THIS SESSION with a DIFFERENT value. Fail-open to [] — a corrupt or
    unwritable register must never disturb play.
    """
    try:
        relation = key.split("|")[1] if "|" in key else ""
        data = _load(campaign_dir, session_id)
        entries = data["assertions"].setdefault(key, [])
        violations = []
        for prior in entries:
            if not _values_agree(relation, prior.get("value"), value):
                a, _rel, b = (key.split("|") + ["", "", ""])[:3]
                violations.append(
                    f"SELF-CONTRADICTION: this session you have already recorded "
                    f"{a} {relation} {b} as {prior.get('value')} "
                    f"(turn {prior.get('turn')}); this turn says {value}. One of "
                    f"these is wrong and the player will remember both. Call "
                    f'geography(action="get_distance", origin="{a}", '
                    f'destination="{b}") and state the answer that survives.'
                )
                break
        entries.append({
            "value": value,
            "turn": turn,
            "excerpt": (turn_text_excerpt or "")[:160],
        })
        # Bound growth: a long session must not grow this file without limit.
        if len(entries) > 20:
            del entries[:-20]
        data["session_id"] = session_id
        _path(campaign_dir).write_text(
            json.dumps(data, indent=1), encoding="utf-8")
        return violations
    except Exception:
        return []
