"""settlement_system.py — flat, non-hostile settlement reader (leaf module).

A "settlement" is a SITE-marked prep with scene=settlement (see site_markers.py).
This module PARSES a settlement prep into a people-roster and RENDERS a recall card.
It is a LEAF: it imports site_markers (also a leaf) but NEVER server.py.
Prep is the single source of truth; this module only reads it (plus optional overlays).
"""
import re
from pathlib import Path
import site_markers as _sm

_NPC_HEADER_RE = re.compile(
    r'^###\s+([A-Z][^\n]*?)\s*(?:\s[—–\-]\s(.+?))?(?:\s*\([^)]*\))?\s*$',
    re.MULTILINE
)
_FIELD_RE = lambda name: re.compile(rf'^\*\*{name}:\*\*\s*(.+)$', re.MULTILINE)
_LOCATION_RE = _FIELD_RE("Location")


def is_settlement_prep(content: str) -> bool:
    """True iff the prep carries a SITE marker with scene=settlement."""
    marker = _sm.parse_site_marker(content or "")
    return bool(marker) and marker.get("scene") == "settlement"


def _npc_blocks(content: str):
    """Yield (name, title, body_text) for each ### block under the ## NPCs section."""
    # Isolate the NPCs section. Recognises both:
    #   ## NPCs             (standard heading)
    #   ## KEY NPCs ...     (Tessik Well / extended heading with optional trailing text)
    m = re.search(r'^##\s+(?:KEY\s+)?NPCs\b[^\n]*$(.*?)(?=^##\s|\Z)', content or "", re.MULTILINE | re.DOTALL)
    if not m:
        return
    section = m.group(1)
    headers = list(_NPC_HEADER_RE.finditer(section))
    for i, h in enumerate(headers):
        start = h.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(section)
        name = h.group(1).strip()
        title = (h.group(2) or "").strip()
        yield name, title, section[start:end]


def npcs_missing_location(content: str):
    """Names of settlement NPCs whose block lacks a **Location:** field (validator use)."""
    out = []
    for name, _title, body in _npc_blocks(content):
        if not _LOCATION_RE.search(body):
            out.append(name)
    return out


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_ROLE_RE = _FIELD_RE("Role")
_REACT_RE = re.compile(r'^\*\*How [^\n]*Reacts to the Party:\*\*\s*\n(.+?)(?=^\*\*|\Z)',
                       re.MULTILINE | re.DOTALL)


def parse_settlement(content: str) -> dict:
    """Parse a settlement prep into {name, npcs:[{name,title,location,role,reaction}], trade}."""
    title_m = re.search(r'^#\s+(.+?)\s*(?:[—–\-]\s*PREP)?\s*$', content or "", re.MULTILINE)
    name = title_m.group(1).strip() if title_m else "Settlement"

    npcs = []
    for npc_name, npc_title, body in _npc_blocks(content):
        loc_m = _LOCATION_RE.search(body)
        role_m = _ROLE_RE.search(body)
        react_m = _REACT_RE.search(body)
        npcs.append({
            "name": npc_name,
            "title": npc_title,
            "location": loc_m.group(1).strip() if loc_m else None,
            "role": role_m.group(1).strip() if role_m else "",
            "reaction": (react_m.group(1).strip().split("\n")[0].lstrip("- ").strip()
                         if react_m else ""),
        })

    trade = ""
    tm = re.search(r'^##\s+TRADE GOODS[^\n]*$(.*?)(?=^##\s|\Z)',
                   content or "", re.MULTILINE | re.DOTALL)
    if tm:
        items = [ln.strip("- ").strip() for ln in tm.group(1).splitlines()
                 if ln.strip().startswith("-")]
        trade = ", ".join(items)

    return {"name": name, "npcs": npcs, "trade": trade}


# ---------------------------------------------------------------------------
# Card renderer
# ---------------------------------------------------------------------------

def build_who_card(data: dict, npc_overlay: dict | None = None, place_overlay: dict | None = None) -> str:
    """Render the who's-around recall card. Overlays (optional) mark per-person status
    (npc_overlay[name] = {"status","day"}) and per-place status (place_overlay[room]).
    Authored prose is never mutated; overlays only annotate the rendered card."""
    npc_overlay = npc_overlay or {}
    place_overlay = place_overlay or {}
    lines = [f"{data['name'].upper()} — who's here  (live from prep = source of truth)"]

    # Settlement-wide standing banner, if any.
    standing = place_overlay.get("party_standing")
    if standing:
        lines.append(f"⚠ This settlement is {standing['status']} to you (since Day {standing['day']})")

    for n in data["npcs"]:
        ov = npc_overlay.get(n["name"])
        if ov and ov.get("status") == "DEAD":
            lines.append(f"{n['name']} — †dead since Day {ov.get('day', '?')}")
            continue
        loc = n["location"] or "?"
        head = f"{n['name']} — {loc} — {n['title']}".rstrip(" —")
        if n["role"]:
            head += f"; {n['role']}"
        lines.append(head)
        if n["reaction"]:
            lines.append(f"          ↳ {n['reaction']}")

    if data["trade"]:
        lines.append(f"Trade: {data['trade']}")
    lines.append('More: reference_location(location="' + data["name"] + '", focus="<name>")')
    lines.append('Change here (death/leave/standing)? → update_location_progress(location=..., '
                 'summary=..., consequences=...)')
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Place-status parser (Task C2)
# ---------------------------------------------------------------------------

_STATUS_RE = re.compile(r'^- STATUS:\s*([^:]+):\s*([A-Z_]+)\s*\(Day\s*(\d+)\)\s*$', re.MULTILINE)


def parse_place_status(content: str) -> dict:
    """Latest typed STATUS per target from a prep's PROGRESS LOG. Last write wins.

    Returns {target: {"status": STATE, "day": N}} for every STATUS stamp found.
    Designed to read the PROGRESS LOG section written by update_location_progress.
    """
    out = {}
    for m in _STATUS_RE.finditer(content or ""):
        target, state, day = m.group(1).strip(), m.group(2).strip(), int(m.group(3))
        prev = out.get(target)
        if prev is None or day >= prev["day"]:
            out[target] = {"status": state, "day": day}
    return out


# ---------------------------------------------------------------------------
# Resolver (Task B3)
# ---------------------------------------------------------------------------


def build_settlement_index(campaign_dir):
    """{key: {"prep_file","aliases"}} for every scene=settlement SITE-marked prep."""
    campaign_dir = Path(campaign_dir)
    index = {}
    for prep in sorted(campaign_dir.glob("*_PREP.md")):
        try:
            content = prep.read_text(encoding="utf-8")
        except Exception:
            continue
        marker = _sm.parse_site_marker(content)
        if marker and marker.get("scene") == "settlement":
            index[marker["key"]] = {
                "prep_file": prep.name,
                "aliases": marker["aliases"] or [marker["key"].replace("_", " ")],
            }
    return index


def _norm_apos(s):
    """Normalize typographic apostrophes/primes to ASCII ' so a settlement name like
    "Dust Pilgrim's Rest" resolves whether typed with a straight ' or a curly '
    (editors and the tool transport routinely swap them)."""
    return re.sub("[‘’ʼ′`]", "'", s or "")


def resolve_settlement(name, campaign_dir):
    """Resolve a player/DM name to a settlement prep Path, or None.
    Apostrophe-style-insensitive (settlement names commonly carry apostrophes)."""
    index = build_settlement_index(campaign_dir)
    nname = _norm_apos(name)
    norm_aliases = {k: {"aliases": [_norm_apos(a) for a in v["aliases"]]} for k, v in index.items()}
    matched = _sm.detect_named_sites(nname, norm_aliases)
    if not matched:
        # direct key / substring fallback (apostrophe- and separator-insensitive)
        nl = nname.lower().strip()
        nl_key = nl.replace("'", "").replace(" ", "_")  # "dust pilgrim's rest" -> "dust_pilgrims_rest"
        for k in index:
            if nl == k or nl in k or k in nl or nl_key == k:
                matched = [k]
                break
    if not matched:
        return None
    return Path(campaign_dir) / index[matched[0]]["prep_file"]
