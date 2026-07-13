"""Bespoke reader for the Ceruline arcology (leaf module).

Ceruline is a hand-authored 11-tier arcology in CERULINE_PLAYER_REFERENCE.md.
Its shape is a one-off the content-forge generator does NOT emit; this reader is
Ceruline-specific by owner ruling (2026-06-15) and does not generalize to forged
settlements. Parses the tiered file into a per-tier roster and renders a lean
who's-around card. LEAF: imports only re/pathlib; NEVER server.
"""
import re
from pathlib import Path

CERULINE_FILE = "CERULINE_PLAYER_REFERENCE.md"

_TIER_RE = re.compile(r'^##\s+TIER\s+(\d+)\s*:\s*(.+?)\s*$')
_LOC_RE = re.compile(r'^###\s+(.+?)\s*$')
_BULLET_RE = re.compile(r'^-\s+\*\*(.+?)\*\*')
_ROLE_RE = re.compile(r'^\*\*(Proprietor|Representative|Residents?|Current Residents|'
                      r'Current Leadership|Current Authority|Former Proprietor)\:\*\*\s*(.+?)\s*$')
_KEY_LOC_RE = re.compile(r'^\*\*Location:\*\*\s*(.+?)\s*(?:\(Tier\s*(\d+)\))?\s*$')

_TITLES = ("Lord", "Lady", "Master", "Scholar", "Observer", "Merchant-Captain",
           "Grand", "Matriarch", "Dr.", "Dr", "Captain", "Sir", "Madam", "Surgeon")


def _norm(s):
    return re.sub("[‘’ʼ′`]", "'", (s or "")).strip()


_TITLE_KEYS = {t.rstrip('.').lower() for t in _TITLES}


def identity_key(name):
    """Dedup identity: apostrophe/case-normalize, then iteratively strip leading title
    tokens so 'Matriarch Amara Vane' -> 'amara vane' and
    'Master Surgeon Brant' -> 'brant'. Single source of truth for name matching
    across the card, the npc_states dossier, and the settlement overlay."""
    tokens = [t for t in re.split(r'\s+', _norm(name)) if t]
    while len(tokens) > 1 and tokens[0].rstrip('.').lower() in _TITLE_KEYS:
        tokens.pop(0)
    return " ".join(tokens).lower()


# Back-compat alias (internal callers may still use the underscored name).
_identity_key = identity_key


def _short_label(name):
    """'NOBLE QUARTER / UPPER RESIDENTIAL' -> 'Noble Quarter'; 'CULTIVATION DISTRICT' -> 'Cultivation'."""
    head = name.split("/")[0].strip()
    head = re.sub(r'\s+(DISTRICT|LEVEL|QUARTER|MARKET)\b.*$', lambda m: (' Quarter' if m.group(1) == 'QUARTER' else ''),
                  head, flags=re.IGNORECASE).strip()
    return head.title()


def _clean_person_name(raw):
    """Strip a trailing (parenthetical) and any ' - '/' — ' tail, return the name or None
    if it is a bare descriptor (no proper name)."""
    name = re.sub(r'\s*\([^()]*\)\s*$', '', raw or '').strip()
    name = re.split(r'\s+[-—–]\s+', name)[0].strip()
    if not name:
        return None
    if name.startswith(_TITLES):
        return name
    tokens = [t for t in re.split(r'\s+', name) if t]
    if len(tokens) == 1 and tokens[0][:1].isupper():
        return name
    if tokens and all(t[:1].isupper() or t[:1] in '"' for t in tokens):
        return name
    return None  # e.g. "Four-armed cacogen", "Professional cacogen"


def parse_ceruline(content: str):
    """Parse the tiered file into [{num, name, short, people:[{name, location}]}], tier order preserved."""
    lines = (content or "").splitlines()
    tiers = {}          # num -> dict
    order = []          # tier nums in first-seen order
    cur_tier = None
    cur_loc = None
    in_key = False
    key_name = None

    def ensure_tier(num, name=None):
        if num not in tiers:
            tiers[num] = {"num": num, "name": name or f"Tier {num}",
                          "short": _short_label(name) if name else f"Tier {num}",
                          "people": [], "_seen": {}}
            order.append(num)
        elif name and tiers[num]["name"].startswith("Tier "):
            tiers[num]["name"] = name
            tiers[num]["short"] = _short_label(name)
        return tiers[num]

    def add_person(tier_num, name, location, is_key=False):
        t = ensure_tier(tier_num)
        key = _identity_key(name)
        if not key:
            return
        existing = t["_seen"].get(key)
        if existing is not None:
            # KEY-NPCS is the curated record — on collision it overwrites display
            # name + location; otherwise first-occurrence-wins (skip).
            if is_key:
                existing["name"] = name
                existing["location"] = location or existing["location"]
            return
        person = {"name": name, "location": location or "?"}
        t["_seen"][key] = person
        t["people"].append(person)

    for raw in lines:
        line = raw.rstrip()
        m = _TIER_RE.match(line)
        if m:
            cur_tier = int(m.group(1))
            ensure_tier(cur_tier, m.group(2).strip())
            cur_loc = None
            in_key = False
            continue
        if line.strip().upper().startswith("## KEY NPCS"):
            in_key = True
            cur_tier = None
            key_name = None
            continue
        if line.startswith("## "):       # any other H2 ends tier/key context
            in_key = False
            cur_tier = None
            cur_loc = None
            continue
        lm = _LOC_RE.match(line)
        if lm:
            if in_key:
                key_name = _clean_person_name(lm.group(1))
            else:
                cur_loc = lm.group(1).strip()
            continue
        if in_key and key_name:
            km = _KEY_LOC_RE.match(line.strip())
            if km:
                loc = km.group(1).strip()
                tier_num = int(km.group(2)) if km.group(2) else None
                if tier_num is not None:
                    add_person(tier_num, key_name, loc, is_key=True)
                key_name = None
            continue
        if cur_tier is not None:
            bm = _BULLET_RE.match(line.strip())
            if bm:
                nm = _clean_person_name(bm.group(1))
                if nm:
                    add_person(cur_tier, nm, cur_loc)
                continue
            rm = _ROLE_RE.match(line.strip())
            if rm:
                nm = _clean_person_name(rm.group(2))
                if nm:
                    add_person(cur_tier, nm, cur_loc)
                continue

    return [tiers[n] for n in order]


_DAY_RE = re.compile(r'\bDay\s+(\d+)\b', re.IGNORECASE)


def reference_as_of(content) -> "int | None":
    """The MAX integer day stamped anywhere in the reference (\\bDay N\\b, case-insensitive).
    None if no Day-N stamp is found. On the real file this returns the latest snapshot day."""
    days = [int(m) for m in _DAY_RE.findall(content or "")]
    return max(days) if days else None


def _staleness_line(as_of_day=None, current_day=None) -> str:
    if as_of_day is None:
        return "⚠ Reference may be stale/incomplete — verify against recent play."
    line = (f"⚠ Reference as of Day {as_of_day} — may be stale/incomplete "
            f"(newer tiers & events not shown); verify against recent play.")
    if current_day is not None and current_day > as_of_day:
        line += f" [now Day {current_day}, {current_day - as_of_day}d on]"
    return line


def tier_list(tiers, as_of_day=None, current_day=None) -> str:
    labels = " · ".join(t["short"] for t in tiers if t["people"])
    return ('CERULINE — which tier? (reference_location scope="who", focus=<tier>)\n'
            + _staleness_line(as_of_day, current_day) + '\n  '
            + labels)


def match_tier(focus, tiers):
    if not focus:
        return None
    f = _norm(focus).lower()
    fnum = None
    nm = re.search(r'(\d+)', f)
    if nm and re.fullmatch(r'(tier\s*|t)?\d+', f):
        fnum = int(nm.group(1))
    # Pass 1: exact tier-number or exact short-label/full-name match.
    for t in tiers:
        if fnum is not None and t["num"] == fnum:
            return t
        if f == t["short"].lower() or f == t["name"].lower():
            return t
    # Pass 2: substring fallback only if no exact match found.
    for t in tiers:
        short = t["short"].lower()
        full = t["name"].lower()
        if f in short or short in f or f in full:
            return t
    return None


def build_tier_card(tier, npc_overlay=None, as_of_day=None, current_day=None) -> str:
    npc_overlay = npc_overlay or {}
    lines = [f"CERULINE — {tier['short']} (T{tier['num']}) — REFERENCE roster",
             _staleness_line(as_of_day, current_day)]
    for p in tier["people"]:
        ov = npc_overlay.get(p["name"])
        if ov and str(ov.get("status", "")).upper() == "DEAD":
            lines.append(f"  {p['name']} — †dead since Day {ov.get('day', '?')}")
        else:
            lines.append(f"  {p['name']} — {p['location']}")
    lines.append('  → other tiers: reference_location("Ceruline", scope="who")')
    return "\n".join(lines)


_CERULINE_ALIASES = ("ceruline", "ceruline arcology", "the arcology")


def is_ceruline(location) -> bool:
    return _norm(location).lower() in _CERULINE_ALIASES


def _read(campaign_dir):
    return (Path(campaign_dir) / CERULINE_FILE).read_text(encoding="utf-8")


def who_card(campaign_dir, focus=None, npc_overlay=None, current_day=None):
    content = _read(campaign_dir)
    as_of = reference_as_of(content)
    tiers = parse_ceruline(content)
    if not focus:
        return tier_list(tiers, as_of_day=as_of, current_day=current_day)
    t = match_tier(focus, tiers)
    if not t:
        return (f'No tier "{focus}" — pick one:\n'
                + tier_list(tiers, as_of_day=as_of, current_day=current_day))
    return build_tier_card(t, npc_overlay=npc_overlay, as_of_day=as_of, current_day=current_day)


def trade_summary(campaign_dir):
    content = _read(campaign_dir)
    m = re.search(r'^##\s+TRADE\b[^\n]*$(.*?)(?=^##\s|\Z)', content, re.MULTILINE | re.DOTALL)
    if not m:
        return "CERULINE — trade\n(no trade section)"
    body = [ln.strip() for ln in m.group(1).splitlines() if ln.strip()]
    lean = [ln for ln in body if ln.startswith("**") or ln.startswith("-")][:8]
    return "CERULINE — trade\n" + "\n".join(lean)
