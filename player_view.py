"""Player-view emitter — the spoiler-safe surface player-facing chrome reads.

WHITELIST module: it assembles ONLY player-known fields from their canonical
homes (sheets, party.json, game_state, weather, open parleys). It must NEVER
read ANTAGONIST_CULTIVATION.md, crossing/purpose-clock internals, or prep
files. Leaf module: never imports server.
Spec: docs/superpowers/specs/2026-07-05-terminal-uiux-design.md
"""
import json
from datetime import datetime
from pathlib import Path

from engine_core import _atomic_replace_with_retry

VIEW_FILENAME = "player_view.json"
MAP_FILENAME = "player_map.txt"


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# Item power fields the player may see (their own gear). notes and
# engine_tags stay locked out — DM secrets can live there (canary-locked).
_ITEM_EFFECT_FIELDS = (("effect", ""), ("effect_special", "special: "),
                       ("effect_daily", "daily: "))


def _item_entries(char: dict) -> list:
    """Whitelist walk of every inventory section -> {name, where, effect}.

    Schema-tolerant like survival.py's _iter_items: iterates ALL sections of
    the inventory dict (section names vary, e.g. "carried", "stored_ceruline");
    cybernetic augmentations join with where="cybernetic". A dict entry is
    NEVER str()'d whole -- that would dump notes/engine_tags/stats (DM secrets
    can live in an item's notes) into the player artifact. Trusted fields:
    "name"/"id" plus the effect* power fields (2026-07-07 owner ask: the
    dashboard must show what items DO); anything else never crosses.
    """
    def _entry(d: dict, where: str) -> dict:
        e = {"name": d.get("name") or d.get("id") or "(unnamed item)",
             "where": where}
        effect = " · ".join(f"{lbl}{d[f]}" for f, lbl in _ITEM_EFFECT_FIELDS
                            if d.get(f))
        if effect:
            e["effect"] = effect
        return e

    entries = []
    inv = char.get("inventory") or {}
    for where, section in inv.items():
        if not isinstance(section, list):
            continue
        for item in section:
            if isinstance(item, dict):
                entries.append(_entry(item, where))
            else:
                entries.append({"name": str(item), "where": where})
    for augs in (char.get("augmentations") or {}).values():
        for aug in (augs if isinstance(augs, list) else [augs]):
            if isinstance(aug, dict):
                entries.append(_entry(aug, "cybernetic"))
    return entries


def _current_place_features(campaign_dir: Path, location) -> list:
    """Site-feature ledger entries for the current place. Ledger content is
    player-known by construction (spoiler rule lives in site_features.py) —
    whitelist-safe. Only text+day cross into the artifact."""
    try:
        import site_features
        entry = site_features.place_entry(campaign_dir, location)
        if entry:
            return [{"text": f.get("text"), "day": f.get("day")}
                    for f in entry.get("features", [])]
    except Exception:
        pass
    return []


def _last_mechanics_events(campaign_dir: Path) -> list:
    """Last 5 mechanical deltas (mechanics_ticker ledger). Player-known by
    construction: PC numbers are theirs; enemy entries are qualitative. []
    when the file is absent. Leaf-safe: mechanics_ticker never imports server."""
    try:
        import mechanics_ticker
        return mechanics_ticker.last_events(campaign_dir, 5)
    except Exception:
        return []


def _journal(campaign_dir: Path) -> dict:
    """The player journal: the active site's revealed ledger, newest first, plus
    its open docket tracks. Spoiler-safe by construction — the ledger holds only
    party-earned facts and the docket stands were written from play. The active
    site = the maps/*_map.json with the newest last_seen_day (mtime fallback)."""
    try:
        maps_dir = campaign_dir / "maps"
        best, best_key = None, (-1, -1.0)
        for f in maps_dir.glob("*_map.json"):
            data = _read_json(f)
            if not isinstance(data, dict):
                continue
            day = data.get("last_seen_day")
            key = (day if isinstance(day, int) else -1, f.stat().st_mtime)
            if key > best_key:
                best, best_key = data, key
        if not best:
            return {}
        entries = [{"day": e.get("day"), "fact": e.get("fact", "")}
                   for e in (best.get("revealed_ledger") or [])][-30:]
        entries.reverse()
        tracks = [{"title": t.get("title", ""), "status": t.get("status", ""),
                   "stand": t.get("stand", "")}
                  for t in (best.get("tracks") or [])
                  if isinstance(t, dict) and t.get("status") != "RESOLVED"]
        return {"site": best.get("map_name"), "entries": entries, "tracks": tracks}
    except Exception:
        return {}


def build_view(campaign_dir: Path) -> dict:
    campaign_dir = Path(campaign_dir)
    meta = _read_json(campaign_dir / "characters" / "_meta.json") or {}
    game = _read_json(campaign_dir / "game_state.json") or {}
    party_file = _read_json(campaign_dir / "party.json") or {}
    weather = _read_json(campaign_dir / "weather_state.json") or {}

    party = []
    chars_dir = campaign_dir / "characters"
    if chars_dir.is_dir():
        for f in sorted(chars_dir.glob("*.json")):
            if f.name == "_meta.json":
                continue
            c = _read_json(f) or {}
            hp = c.get("hp") or {}
            av = c.get("av") or {}
            conditions = [cd.get("name") for cd in (c.get("conditions") or [])
                          if isinstance(cd, dict) and cd.get("name")]
            party.append({
                "name": c.get("name") or f.stem,
                "hp": hp.get("current") if isinstance(hp, dict) else hp,
                "hp_max": hp.get("max") if isinstance(hp, dict) else None,
                "av": av.get("base") if isinstance(av, dict) else av,
                "wounds": len(c.get("wounds") or []),
                "conditions": conditions,
                "slots_free": c.get("slots_free"),
                "slots_total": c.get("slot_capacity_total"),
                "items": _item_entries(c),
            })

    open_parleys = []
    try:
        from social_system import load_parleys
        for slug, p in (load_parleys(campaign_dir) or {}).items():
            if isinstance(p, dict) and p.get("status", "open") == "open":
                open_parleys.append({"slug": slug, "tier": p.get("current_tier", p.get("tier"))})
    except Exception:
        pass

    prep = game.get("active_prep_file")
    return {
        "day": meta.get("campaign_day"),
        "weather": weather.get("weather"),
        "location": game.get("active_location_name"),
        "active_prep": Path(prep).stem if prep else None,
        "site_features": _current_place_features(campaign_dir, game.get("active_location_name")),
        "last_events": _last_mechanics_events(campaign_dir),
        "journal": _journal(campaign_dir),
        "party": party,
        "wealth_tokens": (party_file.get("wealth") or {}).get("tokens"),
        "supply": meta.get("supply") or {},
        "open_parleys": open_parleys,
        "in_combat": bool(game.get("active_combat")),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    _atomic_replace_with_retry(tmp, path)


def write_player_view(campaign_dir: Path, fog_map_text=None) -> None:
    campaign_dir = Path(campaign_dir)
    view = build_view(campaign_dir)
    _atomic_write_text(campaign_dir / VIEW_FILENAME,
                       json.dumps(view, indent=1, ensure_ascii=False))
    if fog_map_text is not None:
        _atomic_write_text(campaign_dir / MAP_FILENAME, fog_map_text)
