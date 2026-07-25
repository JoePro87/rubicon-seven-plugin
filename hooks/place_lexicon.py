"""Canon place-name lexicon (leaf; stdlib only; fail-open).

Builds and mtime-caches the set of place names the campaign has actually
committed to disk, so spatial checks are LEXICON-ANCHORED rather than
vibe-anchored: "the wind came from the west" can never fire, because no canon
place name sits in the window.

Sources (data over code — no place name is ever hardcoded here):
  overworld : VAARN_GEOGRAPHY.json  locations keys (underscores -> spaces)
              plus any 'display_name'/'name' field on a location entry.
  regions   : VAARN_GEOGRAPHY.json  regions keys (underscores -> spaces).
  site      : every maps/*.json map_name plus every rooms[*].name.

Fail-open by construction: any exception yields empty frozensets, which
disarms every gate built on top of this. A broken data file must never brick a
live session.
"""

import json
import os
import re
from pathlib import Path

# Names shorter than this are dropped: "the", "sea", "bore" survives, "sea" does not.
_MIN_NAME_CHARS = 4

# Backup/scratch map files the campaign dir accumulates; their stale room names
# would otherwise poison the lexicon.
_BACKUP_MARKERS = (".bak", ".pre-")

_EMPTY = {
    "overworld": frozenset(),
    "site": frozenset(),
    "regions": frozenset(),
    "mtime_key": (),
}

_LEXICON_CACHE: dict = {"key": None, "value": None}

_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+", re.IGNORECASE)


def _norm(name) -> str:
    """Lowercase, underscores->spaces, whitespace-collapsed. '' when unusable."""
    if not isinstance(name, str):
        return ""
    s = name.replace("_", " ").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _add(bucket: set, name) -> None:
    s = _norm(name)
    if len(s) >= _MIN_NAME_CHARS:
        bucket.add(s)
    # Also index the article-stripped form ("the salt bore" -> "salt bore") so a
    # sentence that omits the article still anchors.
    bare = _ARTICLE_RE.sub("", s).strip()
    if bare != s and len(bare) >= _MIN_NAME_CHARS:
        bucket.add(bare)


def _is_backup(path: Path) -> bool:
    n = path.name
    return any(m in n for m in _BACKUP_MARKERS)


def _map_files(campaign: Path) -> list:
    try:
        return sorted(p for p in (campaign / "maps").glob("*.json")
                      if not _is_backup(p))
    except Exception:
        return []


def _mtime_key(campaign: Path) -> tuple:
    parts = []
    for p in [campaign / "VAARN_GEOGRAPHY.json"] + _map_files(campaign):
        try:
            parts.append((str(p), p.stat().st_mtime))
        except Exception:
            parts.append((str(p), None))
    return tuple(parts)


def _config(campaign: Path) -> dict:
    """Optional campaign-side tuning file; fail-open to {}."""
    try:
        path = campaign / "spatial_gate_config.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build(campaign: Path) -> dict:
    overworld, site, regions = set(), set(), set()

    try:
        geo_path = campaign / "VAARN_GEOGRAPHY.json"
        if geo_path.exists():
            geo = json.loads(geo_path.read_text(encoding="utf-8"))
            for key, entry in (geo.get("locations") or {}).items():
                _add(overworld, key)
                if isinstance(entry, dict):
                    _add(overworld, entry.get("display_name"))
                    _add(overworld, entry.get("name"))
            for key in (geo.get("regions") or {}):
                _add(regions, key)
    except Exception:
        pass

    for mp in _map_files(campaign):
        try:
            data = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        _add(site, data.get("map_name"))
        for room in (data.get("rooms") or {}).values():
            if isinstance(room, dict):
                _add(site, room.get("name"))

    cfg = _config(campaign)
    for extra in cfg.get("extra_place_names", []) or []:
        _add(overworld, extra)
    exempt = {_norm(x) for x in (cfg.get("exempt_place_names", []) or [])}
    if exempt:
        overworld -= exempt
        site -= exempt
        regions -= exempt

    return {
        "overworld": frozenset(overworld),
        "site": frozenset(site),
        "regions": frozenset(regions),
        "mtime_key": _mtime_key(campaign),
    }


def load_place_lexicon(campaign_dir) -> dict:
    """Return the mtime-cached canon place lexicon. Never raises.

    Keys: 'overworld', 'site', 'regions' (frozensets of lowercased names) and
    'mtime_key'. Empty sets mean "no data" — callers must treat that as a
    disarmed gate, not as "nothing matched".
    """
    try:
        campaign = Path(campaign_dir)
        if not campaign.exists():
            return dict(_EMPTY)
        key = _mtime_key(campaign)
        if _LEXICON_CACHE["key"] == key and _LEXICON_CACHE["value"] is not None:
            return _LEXICON_CACHE["value"]
        value = _build(campaign)
        _LEXICON_CACHE["key"] = key
        _LEXICON_CACHE["value"] = value
        return value
    except Exception:
        return dict(_EMPTY)


def load_config(campaign_dir) -> dict:
    """Public accessor for spatial_gate_config.json (fail-open to {})."""
    try:
        return _config(Path(campaign_dir))
    except Exception:
        return {}


def campaign_root():
    """RUBICON_CAMPAIGN_DIR if set, else None — same lookup as fabrication_detectors."""
    root = os.environ.get("RUBICON_CAMPAIGN_DIR")
    return Path(root) if root else None
