"""Site-feature ledger — persistent features for UNMAPPED, un-prepped places.

The flower use-case: leave an item at a wilderness camp/shrine and it stays a
feature of that place until the DM changes it via the same lever
(update_location_progress routes here when the place has no prep file).

WHITELIST-BY-CONSTRUCTION: this ledger holds only player-known facts (the
player caused or witnessed them). Secrets stay in prep files — that rule is
what makes the ledger safe for the player view.

Engine-vs-DM boundary: the engine stores and surfaces features; it never
judges or auto-changes them. advance_day does not touch this ledger.

Leaf module: never imports server. Storage: <campaign>/site_features.json,
atomic writes via engine_core._atomic_replace_with_retry. Cold-start safe:
missing or corrupt file reads as an empty ledger.
Spec: docs/superpowers/specs/2026-07-05-site-feature-persistence-design.md
"""
import json
from pathlib import Path

from engine_core import _atomic_replace_with_retry

LEDGER_FILENAME = "site_features.json"
_MIN_SCAN_LEN = 4  # never scan-match place names shorter than this


def slugify(name: str) -> str:
    """Geography-compatible slug (see geography_system.add_location)."""
    return str(name).strip().lower().replace(" ", "_").replace("'", "")


def _ledger_path(campaign_dir) -> Path:
    return Path(campaign_dir) / LEDGER_FILENAME


def load_ledger(campaign_dir) -> dict:
    try:
        data = json.loads(_ledger_path(campaign_dir).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("places"), dict):
            return data
    except Exception:
        pass
    return {"version": 1, "places": {}}


def _save_ledger(campaign_dir, ledger) -> None:
    path = _ledger_path(campaign_dir)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ledger, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    _atomic_replace_with_retry(tmp, path)


def stamp_feature(campaign_dir, place, text, day, aliases=None) -> str:
    text = (text or "").strip()
    if not text:
        return "ERROR: empty feature text — nothing stamped"
    slug = slugify(place)
    if not slug:
        return "ERROR: empty place name — nothing stamped"
    ledger = load_ledger(campaign_dir)
    entry = ledger["places"].setdefault(slug, {
        "display_name": str(place).strip(), "aliases": [], "next_id": 1,
        "features": [], "created_day": day,
    })
    for a in (aliases or []):
        a = (a or "").strip()
        if a and a.lower() not in [x.lower() for x in entry["aliases"]]:
            entry["aliases"].append(a)
    fid = entry.get("next_id", 1)
    entry["features"].append({"id": fid, "text": text, "day": day})
    entry["next_id"] = fid + 1
    entry["updated_day"] = day
    _save_ledger(campaign_dir, ledger)
    return (f"📍 Feature stamped at {entry['display_name']} "
            f"(#{fid}, Day {day}): {text}")


def remove_feature(campaign_dir, place, match, day) -> str:
    slug = slugify(place)
    ledger = load_ledger(campaign_dir)
    entry = ledger["places"].get(slug)
    if not entry or not entry.get("features"):
        return f"ERROR: no stamped features at '{place}'"
    feats = entry["features"]
    m = str(match).strip()
    hits = [f for f in feats if m.isdigit() and f.get("id") == int(m)]
    if not hits:
        hits = [f for f in feats
                if m and m.lower() in str(f.get("text", "")).lower()]
    if not hits:
        listing = "; ".join(f"#{f['id']} {f['text']}" for f in feats)
        return (f"ERROR: no feature at '{place}' matching '{match}'. "
                f"Current: {listing}")
    if len(hits) > 1:
        listing = "; ".join(f"#{f['id']} {f['text']}" for f in hits)
        return (f"ERROR: '{match}' is ambiguous at '{place}' — matches "
                f"{listing}. Use the #id.")
    feats.remove(hits[0])
    entry["updated_day"] = day
    _save_ledger(campaign_dir, ledger)
    return (f"📍 Feature removed at {entry['display_name']} "
            f"(Day {day}): {hits[0]['text']}")


def place_entry(campaign_dir, place):
    """Slug match first, else two-way substring on display name/aliases.

    Two-way because the live location string is often longer than the place
    name ("Ceruline Arcology — Anchor's Office corridor" contains "Ceruline
    Arcology") and sometimes shorter ("Ceruline").
    """
    if not place:
        return None
    ledger = load_ledger(campaign_dir)
    slug = slugify(place)
    entry = ledger["places"].get(slug)
    if entry is not None:
        return entry
    needle = str(place).strip().lower()
    if len(needle) < _MIN_SCAN_LEN:
        return None
    for e in ledger["places"].values():
        names = [e.get("display_name", "")] + list(e.get("aliases", []))
        for n in names:
            n = (n or "").strip().lower()
            if len(n) >= _MIN_SCAN_LEN and (needle in n or n in needle):
                return e
    return None


def features_for(campaign_dir, place) -> list:
    entry = place_entry(campaign_dir, place)
    return list(entry.get("features", [])) if entry else []


def scan_text_for_places(campaign_dir, text) -> dict:
    """Which stamped places (with features) are named in `text`?"""
    if not text:
        return {}
    low = str(text).lower()
    # Apostrophe-flattened twin: a place stamped as "Pilgrims Rest" must
    # still match prose that spells it "Pilgrim's Rest" (and vice versa) —
    # slugify() strips apostrophes, so slug lookups already agree.
    low_flat = low.replace("'", "")
    out = {}
    for slug, e in load_ledger(campaign_dir)["places"].items():
        if not e.get("features"):
            continue
        names = [e.get("display_name", "")] + list(e.get("aliases", []))
        for n in names:
            n = (n or "").strip().lower()
            if len(n) >= _MIN_SCAN_LEN and (n in low or n.replace("'", "") in low_flat):
                out[slug] = e
                break
    return out


def format_features_block(entry) -> str:
    lines = [f"📍 SITE FEATURES — {entry.get('display_name', '?')}:"]
    for f in entry.get("features", []):
        lines.append(f"  • {f.get('text')} (since Day {f.get('day')})")
    return "\n".join(lines)
