import json, os, sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import weapon_schema as ws

def _campaign():
    env = os.environ.get("RUBICON_CAMPAIGN_DIR")
    cands = [Path(env)] if env else []
    cands.append(Path(__file__).resolve().parents[2] / "rubicon-seven-campaign")
    for b in cands:
        if (b / "characters").exists():
            return b
    pytest.skip("campaign sheets not locatable")

def _carried(d):
    return (d.get("inventory", {}) or {}).get("carried", []) or []

def test_every_sheet_weapon_has_valid_schema():
    bad = []
    for f in sorted((_campaign() / "characters").glob("*.json")):
        if f.name == "_meta.json": continue
        d = json.loads(f.read_text(encoding="utf-8"))
        for w in _carried(d):
            typ = (w.get("type") or "")
            is_weapon = ("weapon" in typ) or (w.get("damage") and "armor" not in typ and "armour" not in typ)
            if not is_weapon: continue
            if not w.get("damage_type"):
                bad.append((f.name, w.get("name"), "no damage_type")); continue
            errs = ws.validate_weapon(w)
            if errs: bad.append((f.name, w.get("name"), errs))
    assert not bad, bad

def test_every_sheet_armour_has_valid_av():
    bad = []
    for f in sorted((_campaign() / "characters").glob("*.json")):
        if f.name == "_meta.json": continue
        d = json.loads(f.read_text(encoding="utf-8"))
        for a in _carried(d):
            typ = (a.get("type") or "")
            if "armor" not in typ and "armour" not in typ: continue
            if not isinstance(a.get("av_bonus"), int):
                bad.append((f.name, a.get("name"), "no int av_bonus")); continue
            errs = ws.validate_armour(a)
            if errs: bad.append((f.name, a.get("name"), errs))
    assert not bad, bad
