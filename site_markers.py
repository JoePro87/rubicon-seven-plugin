"""Site-entry detection primitives (pure, importable by hooks AND server.py).

A "site" is any turn-tracked adventure place (vault/ruin/camp/explorable settlement).
Site preps carry a `<!-- SITE: key=<slug> scene=<scene> aliases="A|B" -->` marker — a
sibling to the `<!-- DUNGEON: ... -->` vault-liveness tag. These functions recognise a
site from the player's words and build resume context without importing the server.
"""
import json
import re
from pathlib import Path

_SITE_MARKER_RE = re.compile(r'<!--\s*SITE:\s*(.*?)\s*-->', re.IGNORECASE | re.DOTALL)
_DUNGEON_MAP_RE = re.compile(
    r'<!--\s*DUNGEON:\s*map=(\S+)\s+enforce=vault-liveness\s*-->', re.IGNORECASE)
_KV_RE = re.compile(r'(\w+)\s*=\s*(?:"([^"]*)"|(\S+))')

# Generic words that must never act as a watch-name (protects derived fallback aliases).
_SITE_ALIAS_STOPWORDS = {
    "the camp", "the vault", "the ruin", "the place", "the site", "the lair",
    "camp", "vault", "ruin", "site", "lair", "home", "here", "there",
}
_MIN_ALIAS_LEN = 4


def _kv(body):
    """Parse space-separated key=value pairs; values may be "quoted" to allow spaces/pipes."""
    out = {}
    for m in _KV_RE.finditer(body or ""):
        out[m.group(1).lower()] = m.group(2) if m.group(2) is not None else m.group(3)
    return out


def derive_key_from_prep(prep_filename):
    """'KALAXIS_PREP.md' -> 'kalaxis' (mirrors server._derive_map_name)."""
    base = Path(prep_filename).name
    base = re.sub(r'\.md$', '', base, flags=re.IGNORECASE)
    base = re.sub(r'_PREP$', '', base, flags=re.IGNORECASE)
    return base.lower()


def _derive_alias_from_key(key):
    """'outer_reach' -> 'Outer Reach' (a humanised single fallback alias)."""
    return key.replace("_", " ").title()


def parse_site_marker(text):
    """Return {"key","scene","aliases":[...]} from the first <!-- SITE: ... -->, or None."""
    if not text:
        return None
    m = _SITE_MARKER_RE.search(text)
    if not m:
        return None
    kv = _kv(m.group(1))
    key = (kv.get("key") or "").strip().lower()
    if not key:
        return None
    scene = (kv.get("scene") or "vault_exploration").strip() or "vault_exploration"
    aliases = [a.strip() for a in (kv.get("aliases") or "").split("|") if a.strip()]
    return {"key": key, "scene": scene, "aliases": aliases}


def _blank_record(prep_file, aliases, scene="vault_exploration"):
    return {"aliases": aliases, "scene": scene, "prep_file": prep_file,
            "current_turn": None, "last_seen_day": None, "created_day": None}


def build_site_index(campaign_dir):
    """Index every known site: marker preps (primary), DUNGEON-only preps (fallback A),
    and already-entered maps/*_map.json keys (fallback B). Merge resume clocks from state."""
    campaign_dir = Path(campaign_dir)
    index = {}

    for prep in sorted(campaign_dir.glob("*_PREP.md")):
        try:
            content = prep.read_text(encoding="utf-8")
        except Exception:
            continue
        marker = parse_site_marker(content)
        if marker:
            key = marker["key"]
            aliases = marker["aliases"] or [_derive_alias_from_key(key)]
            index[key] = _blank_record(prep.name, aliases, marker["scene"])
        else:
            dm = _DUNGEON_MAP_RE.search(content)
            if dm:
                key = (dm.group(1).strip().lower() or derive_key_from_prep(prep.name))
                index.setdefault(key, _blank_record(prep.name, [_derive_alias_from_key(key)]))

    maps_dir = campaign_dir / "maps"
    if maps_dir.is_dir():
        for mf in sorted(maps_dir.glob("*_map.json")):
            key = mf.name[:-len("_map.json")].lower()
            index.setdefault(key, _blank_record(None, [_derive_alias_from_key(key)]))

        # Merge resume context from per-site state where present.
        for key, rec in index.items():
            mf = maps_dir / f"{key}_map.json"
            if not mf.exists():
                continue
            try:
                st = json.loads(mf.read_text(encoding="utf-8"))
            except Exception:
                continue
            rec["current_turn"] = st.get("current_turn")
            rec["last_seen_day"] = st.get("last_seen_day")
            rec["created_day"] = st.get("created_day")
            if rec.get("prep_file") is None:
                rec["prep_file"] = st.get("prep_file")
    return index


def detect_named_sites(text, site_index):
    """Word-boundary, case-insensitive scan of aliases against text -> matched site keys."""
    if not text or not site_index:
        return []
    matched, seen = [], set()
    for key, rec in site_index.items():
        for alias in rec.get("aliases", []):
            a = (alias or "").strip()
            if len(a) < _MIN_ALIAS_LEN or a.lower() in _SITE_ALIAS_STOPWORDS:
                continue
            # Lookaround boundaries (not \b) so aliases that start/end with a
            # non-word char — "(the pit)", "C.A.V.E" — still match their own text.
            if re.search(rf"(?<!\w){re.escape(a)}(?!\w)", text, re.IGNORECASE):
                if key not in seen:
                    seen.add(key)
                    matched.append(key)
                break
    return matched
