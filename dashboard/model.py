"""Pure data-shaping functions for the companion dashboard.

DUMB RENDERER discipline: reads ONLY the two player-view artifacts
(player_view.json, player_map.txt) from a campaign dir. Never writes,
never imports server, never opens any other campaign file.
Spec: docs/superpowers/specs/2026-07-05-terminal-uiux-design.md (Component 4)
"""
import json
from datetime import datetime
from pathlib import Path

VIEW_FILENAME = "player_view.json"
MAP_FILENAME = "player_map.txt"

NO_VIEW_PLACEHOLDER = ("no live view yet -- run /session-start in your campaign "
                       "session (or play a turn) and this fills in")


def read_artifacts(campaign_dir):
    """Read the two player-view artifacts and nothing else.

    Returns (view, map_text, stale):
      view: parsed dict, or None if the file is missing or malformed.
      map_text: the fog-render text, or None if missing.
      stale: True only when player_view.json EXISTS but fails to parse --
        callers should keep their last good render and show a stale indicator.
    Never raises.
    """
    campaign_dir = Path(campaign_dir)
    view_path = campaign_dir / VIEW_FILENAME
    map_path = campaign_dir / MAP_FILENAME

    view = None
    stale = False
    if view_path.exists():
        try:
            view = json.loads(view_path.read_text(encoding="utf-8"))
        except Exception:
            view = None
            stale = True

    map_text = None
    if map_path.exists():
        try:
            map_text = map_path.read_text(encoding="utf-8")
        except Exception:
            map_text = None

    return view, map_text, stale


def safe_stat_mtime(path: Path):
    """Return path's mtime, or None if it doesn't exist or a race removes/
    replaces it between the existence check and the stat call (TOCTOU)."""
    try:
        return path.stat().st_mtime
    except (FileNotFoundError, OSError):
        return None


def format_time(iso_str: str) -> str:
    """Render an ISO timestamp as HH:MM:SS. Returns the raw string if it
    doesn't parse (never raises)."""
    try:
        return datetime.fromisoformat(iso_str).strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return str(iso_str)


def _norm_item(it) -> dict:
    """Normalize an item to {name, where, effect}. Tolerates both the current
    dict shape and the pre-2026-07-07 plain-string shape (old view files)."""
    if isinstance(it, dict):
        return {"name": it.get("name") or "?",
                "where": it.get("where"),
                "effect": it.get("effect")}
    return {"name": str(it), "where": None, "effect": None}


def party_cards(view: dict) -> list:
    """Shape party data for the Party tab. [] when there's no live view."""
    if not view:
        return []
    cards = []
    for member in view.get("party") or []:
        hp = member.get("hp")
        hp_max = member.get("hp_max")
        slots_free = member.get("slots_free")
        slots_total = member.get("slots_total")
        cards.append({
            "name": member.get("name") or "?",
            "hp_text": f"{hp if hp is not None else '?'}/{hp_max if hp_max is not None else '?'}",
            "av": member.get("av"),
            "wounds": member.get("wounds"),
            "slots_text": f"{slots_free if slots_free is not None else '?'}/"
                          f"{slots_total if slots_total is not None else '?'}",
            "items": [_norm_item(i) for i in (member.get("items") or [])],
        })
    return cards


_WHERE_ORDER = ("carried", "cybernetic")  # these first, rest alphabetical, given_away last


def _where_sort_key(where: str):
    if where in _WHERE_ORDER:
        return (0, _WHERE_ORDER.index(where), where)
    if where == "given_away":
        return (2, 0, where)
    return (1, 0, where)


def _wrap(text: str, width: int, indent: str) -> list:
    """Wrap text to width with a hanging indent; never returns []."""
    import textwrap
    return textwrap.wrap(text, width=width,
                         subsequent_indent=indent) or [text]


def render_party_text(cards: list, width: int = 76) -> str:
    """Format party cards as plain text (markup-free). Card header on its own
    underlined line so stats never fight the name for column space; duplicate
    items collapse to 'name x N'; long effect texts wrap with hanging indent."""
    lines = []
    for c in cards:
        lines.append(c["name"])
        lines.append("=" * max(len(c["name"]), 24))
        lines.append(f"  HP {c['hp_text']:<7} AV {str(c['av']):<4} "
                     f"Wounds {str(c['wounds']):<3} Slots {c['slots_text']}")
        lines.append("")
        if c["items"]:
            by_where = {}
            for it in c["items"]:
                by_where.setdefault(it.get("where") or "carried", []).append(it)
            for where in sorted(by_where, key=_where_sort_key):
                lines.append(f"  {where}")
                counts = {}
                for it in by_where[where]:
                    key = (it["name"], it.get("effect"))
                    counts[key] = counts.get(key, 0) + 1
                for (name, effect), n in counts.items():
                    entry = f"    - {name}" + (f" x {n}" if n > 1 else "")
                    if effect:
                        entry += f": {effect}"
                    lines.extend(_wrap(entry, width, " " * 8))
        else:
            lines.append("  (no items)")
        lines.append("")
    return "\n".join(lines).rstrip()


def world_summary(view: dict):
    """Shape the World tab summary. None when there's no live view."""
    if not view:
        return None
    return {
        "day": view.get("day"),
        "weather": view.get("weather"),
        "location": view.get("location"),
        "active_prep": view.get("active_prep"),
        "supply_mode": (view.get("supply") or {}).get("mode"),
        "wealth_tokens": view.get("wealth_tokens"),
        "in_combat": bool(view.get("in_combat")),
        "parley_count": len(view.get("open_parleys") or []),
        "updated_at": view.get("updated_at"),
    }


def parleys_list(view: dict) -> list:
    """Shape the Parleys tab list (slug + tier only). [] when none open."""
    if not view:
        return []
    return [{"slug": p.get("slug"), "tier": p.get("tier")}
            for p in (view.get("open_parleys") or [])]
