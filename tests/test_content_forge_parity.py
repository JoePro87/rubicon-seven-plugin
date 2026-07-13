"""Guard: content-forge FACTIONS.md hardcoded creature stat blocks must not drift
from the canonical bestiary.json. (They are a second, hand-maintained copy; this
test fails loudly if a future bestiary rebuild changes a creature FACTIONS quotes.)"""
import json
import re
from pathlib import Path

_CAMPAIGN = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"
FACTIONS = _CAMPAIGN / "content-forge" / "references" / "FACTIONS.md"
# bestiary.json is engine-bundled rules-data now (FACTIONS.md stays campaign-side)
BESTIARY = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook" / "bestiary.json"


def _bestiary_keyword_map():
    """normalized keyword -> stats dict."""
    entries = json.loads(BESTIARY.read_text(encoding="utf-8"))["entries"]
    m = {}
    for e in entries:
        for kw in e.get("keywords", []):
            m[kw.lower().strip()] = e.get("stats", {})
    return m


def _match(name, kwmap):
    """Exact keyword match first; else the longest keyword (>=5 chars) that is a
    substring of the name. Returns stats dict or None."""
    n = name.lower().strip()
    if n in kwmap:
        return kwmap[n]
    best_kw, best_stats = "", None
    for kw, stats in kwmap.items():
        if len(kw) >= 5 and kw in n and len(kw) > len(best_kw):
            best_kw, best_stats = kw, stats
    return best_stats


def _factions_blocks():
    """List of (name, lvl, hp_or_None, av_or_None) parsed from FACTIONS.md."""
    text = FACTIONS.read_text(encoding="utf-8")
    out = []
    for name, paren in re.findall(r"([A-Z][A-Za-z'’-]+(?: [A-Z][A-Za-z'’-]+)*) \(([^)]*\bLVL \d+[^)]*)\)", text):
        lvl = re.search(r"LVL (\d+)", paren)
        if not lvl:
            continue
        hp = re.search(r"(\d+) HP", paren)
        av = re.search(r"AV (\d+)", paren)
        out.append((name.strip(), int(lvl.group(1)),
                    int(hp.group(1)) if hp else None,
                    int(av.group(1)) if av else None))
    return out


def test_factions_statblocks_parse():
    # Guard the guard: if the FACTIONS format changes so nothing parses, fail.
    assert len(_factions_blocks()) >= 5, "parsed too few FACTIONS stat blocks - format drift?"


def test_content_forge_factions_match_bestiary():
    kwmap = _bestiary_keyword_map()
    drift, checked = [], 0
    for name, lvl, hp, av in _factions_blocks():
        stats = _match(name, kwmap)
        if not stats:
            continue  # flavour-only reference not in the bestiary - not a drift
        checked += 1
        if stats.get("level") != lvl:
            drift.append(f"{name}: LVL forge={lvl} bestiary={stats.get('level')}")
        if hp is not None and stats.get("hp") != hp:
            drift.append(f"{name}: HP forge={hp} bestiary={stats.get('hp')}")
        if av is not None and stats.get("av") != av:
            drift.append(f"{name}: AV forge={av} bestiary={stats.get('av')}")
    assert checked >= 5, f"expected to cross-check >=5 shared creatures, got {checked}"
    assert not drift, "content-forge FACTIONS.md drifted from bestiary.json:\n" + "\n".join(drift)


def test_chargen_weapon_is_structured():
    # roll=14 on basic_weapon_ranged → Laser Rifle (damage_type='beam', Tags='Beam')
    import content_forge
    import weapon_schema as ws
    obj = content_forge.chargen_weapon_obj("ranged", roll=14)  # Laser Rifle
    assert obj["damage_type"] == "beam"
    assert ws.validate_weapon(obj) == []
