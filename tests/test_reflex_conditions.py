# tests/test_reflex_conditions.py
"""E1 Task 6: the CONDITIONS reflex line - silent/ambient/urgent tiers."""
import json
from pathlib import Path
import importlib.util

# Load phrase_reminder via file path (same pattern as test_reflex_supply.py)
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "phrase_reminder.py"
spec = importlib.util.spec_from_file_location("phrase_reminder", HOOK)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

import reflex_budget as rb
assert rb.URGENT == 0 and rb.AMBIENT == 2, "tier constants changed — update tests"


def _campaign(tmp_path, conds, pending=None):
    """Write a minimal campaign dir: characters/_meta.json + Creenash sheet."""
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "_meta.json").write_text(json.dumps({"campaign_day": 100}))
    sheet = {"name": "Creenash", "inventory": {"carried": []},
             "conditions": conds}
    if pending:
        sheet["twinning_pending"] = pending
    (cdir / "creenash.json").write_text(json.dumps(sheet))
    return tmp_path


def test_silent_when_no_conditions(tmp_path):
    """No conditions -> empty list (SILENT)."""
    root = _campaign(tmp_path, [])
    assert pr._build_conditions_block(root) == []


def test_ambient_for_quiet_condition(tmp_path):
    """A condition with no death clock and no round tick -> AMBIENT."""
    root = _campaign(tmp_path, [{"name": "Twinning",
                                 "effects": {"twinned": {"partner": "Vela"}}}])
    entries = pr._build_conditions_block(root)
    assert len(entries) == 1
    assert entries[0].tier == rb.AMBIENT
    assert "Twinning" in entries[0].text


def test_urgent_for_death_clock_and_round_tick(tmp_path):
    """Death-clock and round-cadence tick conditions -> all URGENT."""
    root = _campaign(tmp_path, [
        {"name": "Doom Mark", "cause": "ritual", "death_day": 104},
        {"name": "Burning", "tick": {"cadence": "round", "hp": "d8"}}])
    entries = pr._build_conditions_block(root)
    assert entries and all(e.tier == rb.URGENT for e in entries)
    text = " ".join(e.text for e in entries)
    assert "Day 104" in text and "d8" in text


def test_urgent_for_pending_window(tmp_path):
    """twinning_pending on the sheet -> URGENT entry containing PENDING."""
    root = _campaign(tmp_path, [{"name": "Twinning",
                                 "effects": {"twinned": {"partner": "Vela"}}}],
                     pending={"window": "combat:r3"})
    entries = pr._build_conditions_block(root)
    assert entries[0].tier == rb.URGENT
    assert "PENDING" in entries[0].text.upper()


def test_supply_owned_deprived_not_duplicated(tmp_path):
    """Deprived thirst/starvation stays with _build_supply_block; photosynthesis renders here."""
    root = _campaign(tmp_path, [
        {"name": "Deprived", "cause": "thirst", "death_day": 103},
        {"name": "Deprived", "cause": "photosynthesis", "death_day": 104}])
    entries = pr._build_conditions_block(root)
    text = " ".join(e.text for e in entries)
    assert "photosynthesis" in text and "thirst" not in text


def test_snapshot_keys_for_delta(tmp_path):
    """_reflex_snapshot includes 'cond:' keys for non-Deprived conditions."""
    root = _campaign(tmp_path, [{"name": "Burning",
                                 "tick": {"cadence": "round", "hp": "d8"}}])
    snap = pr._reflex_snapshot(root)
    assert any(k.startswith("cond:") for k in snap)


def test_multi_pc_mixed_tiers(tmp_path):
    """PC1 urgent + PC2 ambient -> two entries, each at its own tier."""
    root = _campaign(tmp_path, [{"name": "Doom Mark", "death_day": 104}])
    (tmp_path / "characters" / "vela.json").write_text(json.dumps(
        {"name": "Vela", "inventory": {"carried": []},
         "conditions": [{"name": "Twinning",
                         "effects": {"twinned": {"partner": "Creenash"}}}]}))
    entries = pr._build_conditions_block(root)
    assert len(entries) == 2
    by_name = {("Creenash" if "Creenash" in e.text else "Vela"): e
               for e in entries}
    assert by_name["Creenash"].tier == rb.URGENT
    assert by_name["Vela"].tier == rb.AMBIENT


def test_condition_delta_line_round_trip(tmp_path):
    """Seed the snapshot, then apply a condition -> the next reflex block
    carries a delta line for the new cond: key."""
    root = _campaign(tmp_path, [])
    state = {}
    pr._build_reflex_block(root, state=state)
    assert not any(k.startswith("cond:")
                   for k in state.get("reflex_snapshot", {}))
    # Apply Burning on the sheet between turns
    sheet_path = tmp_path / "characters" / "creenash.json"
    sheet = json.loads(sheet_path.read_text())
    sheet["conditions"] = [{"name": "Burning",
                            "tick": {"cadence": "round", "hp": "d8"}}]
    sheet_path.write_text(json.dumps(sheet))
    block = pr._build_reflex_block(root, state=state)
    assert "Δ Creenash:Burning none→on" in block
    assert state["reflex_snapshot"].get("cond:Creenash:Burning") == "on"


def test_spirit_and_incubation_render_without_crash(tmp_path):
    """E5 Task 4: Spirit condition with live essence surfaces correctly."""
    cdir = tmp_path / "characters"
    cdir.mkdir()
    (cdir / "_meta.json").write_text(json.dumps({"campaign_day": 100}))
    (cdir / "creenash.json").write_text(json.dumps({
        "name": "Creenash", "hp": {"current": -20, "max": 23},
        "spirit": {"essence": 12, "max_essence": 23, "faded_until": None},
        "conditions": [{"name": "Spirit", "since_day": 100,
                        "note": "unquiet spirit -- essence 12/23"}],
    }))
    entries = pr._build_conditions_block(str(tmp_path))
    text = " ".join(e.text for e in entries)
    assert "Spirit" in text
    assert "12" in text          # the live essence surfaces


def test_daily_disease_grind_is_urgent(tmp_path):
    """A day/week-cadence HP/ability drain disease must be URGENT, not AMBIENT
    (else the cap can drop a PC silently grinding toward death)."""
    root = _campaign(tmp_path, [
        {"name": "Lumenrot", "tick": {"cadence": "day", "hp": "d4"}}])
    entries = pr._build_conditions_block(root)
    assert entries and entries[0].tier == rb.URGENT
    assert "drains" in entries[0].text and "per day" in entries[0].text


def test_disease_grind_snapshot_tracks_erosion(tmp_path):
    """The cond snapshot folds eroding HP in, so day-over-day grind makes a Δ."""
    root = _campaign(tmp_path, [
        {"name": "Lumenrot", "tick": {"cadence": "day", "hp": "d4"}}])
    sheet_p = tmp_path / "characters" / "creenash.json"
    sheet = json.loads(sheet_p.read_text())
    sheet["hp"] = {"current": 12, "max": 20}
    sheet_p.write_text(json.dumps(sheet))
    snap1 = pr._reflex_snapshot(root)
    assert snap1["cond:Creenash:Lumenrot"] == "on|hp12/20"
    sheet["hp"]["current"] = 9          # the disease grinds 3 HP off
    sheet_p.write_text(json.dumps(sheet))
    snap2 = pr._reflex_snapshot(root)
    assert snap2["cond:Creenash:Lumenrot"] == "on|hp9/20"


def test_due_resurrection_surfaces_urgent(tmp_path):
    """An unresolved resurrection past its due_day gets an URGENT per-turn
    surface naming the resolve call (no such surface existed before)."""
    root = _campaign(tmp_path, [])      # campaign_day = 100
    sheet_p = tmp_path / "characters" / "creenash.json"
    sheet = json.loads(sheet_p.read_text())
    sheet["resurrection"] = {"path": "pseudo_womb", "due_day": 98,
                             "resolved": False}
    sheet_p.write_text(json.dumps(sheet))
    entries = pr._build_conditions_block(root)
    text = " ".join(e.text for e in entries)
    assert any(e.tier == rb.URGENT for e in entries)
    assert "RESURRECTION" in text and "resurrect_resolve" in text and "Day 98" in text


def test_resurrection_not_surfaced_before_due_or_when_resolved(tmp_path):
    """Not-yet-due or already-resolved resurrection -> no surface."""
    root = _campaign(tmp_path, [])      # day 100
    sheet_p = tmp_path / "characters" / "creenash.json"
    sheet = json.loads(sheet_p.read_text())
    sheet["resurrection"] = {"path": "pseudo_womb", "due_day": 105,
                             "resolved": False}
    sheet_p.write_text(json.dumps(sheet))
    assert not any("RESURRECTION" in e.text
                   for e in pr._build_conditions_block(root))
    sheet["resurrection"] = {"path": "pseudo_womb", "due_day": 90,
                             "resolved": True}
    sheet_p.write_text(json.dumps(sheet))
    assert not any("RESURRECTION" in e.text
                   for e in pr._build_conditions_block(root))
