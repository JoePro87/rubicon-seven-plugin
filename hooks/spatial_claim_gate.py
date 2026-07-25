"""Spatial-claim gate (leaf; stdlib only) — spec §A, 2026-07-24.

A compass bearing, a distance, or a containment relation asserted about a KNOWN
CANON PLACE must be backed by a governing engine call in the same turn. Bearings
between canon places come from the file, not from where the party happens to be
standing — the answer must be the same every time it is asked.

Lexicon-anchored: a class fires only when a canon place name (hooks/place_lexicon)
falls within +/-_WINDOW_CHARS of the match. "The wind came out of the west" can
never fire.
"""

import re

FENCED_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
TICKER_HEADER = ">> MECHANICS (relay to player verbatim, after your prose):"

# ~N=12 tokens; measured flat past this (spec §0.4).
_WINDOW_CHARS = 84

_DIRECTION_RE = re.compile(
    r"\b(?:due\s+)?(?:north|south|east|west)(?:[-\s]?(?:east|west))?\b"
    r"|\b(?:northern|southern|eastern|western|northward|southward|"
    r"eastward|westward|upstream|downstream|leeward|windward)\b",
    re.IGNORECASE)

_DISTANCE_RE = re.compile(
    r"\b\d[\d,\.]*\s*(?:miles?|mi|leagues?|hexes?|klicks?|kilometres?|km)\b"
    r"|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|half)\s+"
    r"(?:days?|hours?|weeks?)['’]?s?\s+"
    r"(?:travel|march|ride|walk|walking|flight|journey|out|away|off)\b",
    re.IGNORECASE)

_CONTAINMENT_RE = re.compile(
    r"\b(?:inside|within|outside|beyond|past|beneath|under|above|"
    r"on\s+the\s+far\s+side\s+of|at\s+the\s+(?:mouth|edge|rim|foot|head)\s+of|"
    r"this\s+(?:side|end)\s+of|the\s+far\s+(?:side|end)\s+of)\b",
    re.IGNORECASE)

# class label -> (regex, {tier: satisfying tool short-names})
_CLASSES = [
    ("bearing", _DIRECTION_RE, {
        "overworld": {"geography", "check_canon", "files"},
        "site": {"map", "check_canon", "files"},
    }),
    ("distance", _DISTANCE_RE, {
        "overworld": {"geography", "check_canon"},
        "site": {"geography", "check_canon"},
    }),
    ("containment", _CONTAINMENT_RE, {
        "overworld": {"geography", "map", "check_canon", "files"},
        "site": {"geography", "map", "check_canon", "files"},
    }),
]

_SATISFIER_HINT = {
    ("bearing", "overworld"): "geography()/check_canon()",
    ("bearing", "site"): "map()/check_canon()",
    ("distance", "overworld"): "geography()/check_canon()",
    ("distance", "site"): "geography()/check_canon()",
    ("containment", "overworld"): "geography()/map()/check_canon()",
    ("containment", "site"): "geography()/map()/check_canon()",
}

_TAIL = (
    "\nRe-emit with the governing call made, or with the spatial assertion removed. "
    "Re-deriving a bearing from the current scene is the 2026-07-24 failure — the "
    "answer must be the same every time it is asked, which means it comes from the "
    "file, not from the frame. Saying plainly that something is not established is "
    "always legal; inventing one never is."
)


def _scannable(text: str) -> str:
    """Truncate at the engine-authored ticker, then blank out fenced blocks.

    Fenced blocks are blanked (spaces of equal length) rather than deleted so
    every offset stays aligned with the original text — the register's excerpts
    and the window arithmetic both depend on that.
    """
    idx = text.find(TICKER_HEADER)
    prose = text[:idx] if idx >= 0 else text
    return FENCED_BLOCK_RE.sub(lambda m: " " * len(m.group(0)), prose)


def _names_in_window(low: str, start: int, end: int, lexicon: dict, window: int):
    """Return (tier, name) for every canon place name near [start, end).

    Overworld first — if a name is in both tiers, the stricter overworld
    satisfier set governs.
    """
    lo = max(0, start - window)
    hi = min(len(low), end + window)
    chunk = low[lo:hi]
    found = []
    for tier in ("overworld", "regions", "site"):
        for name in lexicon.get(tier) or ():
            if name in chunk and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", chunk):
                found.append(("overworld" if tier in ("overworld", "regions") else "site", name))
    return found


def extract_spatial_assertions(text, lexicon, window=_WINDOW_CHARS):
    """Yield typed spatial assertions for the session register (spec §D.2).

    Returns a list of (subject, relation, object, value, excerpt):
      relation 'bearing'  -> value is the normalized compass word
      relation 'distance' -> value is the raw distance phrase
    When only one canon name is in scope, object is '@scene' (a weaker key that
    still catches "western mouth" re-asserted as "eastern mouth").
    """
    out = []
    if not text or not lexicon:
        return out
    prose = _scannable(text)
    low = prose.lower()
    for label, rx, _sat in _CLASSES:
        if label == "containment":
            continue
        for m in rx.finditer(prose):
            names = _names_in_window(low, m.start(), m.end(), lexicon, window)
            uniq = []
            for _tier, n in names:
                if n not in uniq:
                    uniq.append(n)
            if not uniq:
                continue
            excerpt = prose[max(0, m.start() - 40): m.end() + 40].strip()
            value = m.group(0).strip().lower()
            if len(uniq) >= 2:
                out.append((uniq[0], label, uniq[1], value, excerpt))
            else:
                out.append((uniq[0], label, "@scene", value, excerpt))
    return out


def scan_unbacked_spatial(text, tool_names, lexicon):
    """Return a list of violation strings. Empty list = pass.

    Fail-open: no text, or an empty lexicon (missing/corrupt geography data),
    yields [] — a disarmed gate, never a crash.
    """
    if not text or not lexicon:
        return []
    if not (lexicon.get("overworld") or lexicon.get("site")):
        return []
    prose = _scannable(text)
    low = prose.lower()
    called = set(tool_names or [])
    seen = set()
    hits = []
    for label, rx, satisfiers in _CLASSES:
        for m in rx.finditer(prose):
            names = _names_in_window(low, m.start(), m.end(), lexicon, _WINDOW_CHARS)
            if not names:
                continue
            tiers = {t for t, _ in names}
            tier = "overworld" if "overworld" in tiers else "site"
            if (label, tier) in seen:
                continue
            if called & satisfiers[tier]:
                continue
            seen.add((label, tier))
            name = next(n for t, n in names if t == tier)
            phrase = prose[max(0, m.start() - 24): m.end() + 24].strip()
            hint = _SATISFIER_HINT[(label, tier)]
            hits.append(
                f'SPATIAL CLAIM WITHOUT SOURCE: "{phrase}" ({label}, {tier}; '
                f'canon place "{name}") — this turn made no {hint} call. '
                f"Compass bearings and distances between canon places come from "
                f'geography(action="get_distance") or geography(action="journey"), '
                f"NEVER from where the party happens to be standing. Legal moves: "
                f"make the call, or cut the bearing, or say plainly that it is not "
                f"established."
            )
    return hits


def block_tail() -> str:
    return _TAIL
