"""Pure data-shaping functions for the companion dashboard.

DUMB RENDERER discipline: reads ONLY the two player-view artifacts
(player_view.json, player_map.txt) from a campaign dir. Never writes,
never imports server, never opens any other campaign file.
Spec: docs/superpowers/specs/2026-07-05-terminal-uiux-design.md (Component 4)
"""
import json
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
    }


def parleys_list(view: dict) -> list:
    """Shape the Parleys tab list (slug + tier only). [] when none open."""
    if not view:
        return []
    return [{"slug": p.get("slug"), "tier": p.get("tier")}
            for p in (view.get("open_parleys") or [])]
