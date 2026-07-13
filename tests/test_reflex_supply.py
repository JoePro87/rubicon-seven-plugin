# tests/test_reflex_supply.py
"""SUPPLY reflex line: silent at home, ambient in the field, urgent when Deprived.

Recon-confirmed API shapes (2026-06-10):
- _build_supply_block(campaign_dir) -> list[Entry]  (NOT str — returns entries directly)
- Entry is a @dataclass with .tier (int) and .text (str)
- URGENT=0, CHANGED=1, AMBIENT=2 (integer constants in reflex_budget.py, accessed as pr._rb.URGENT etc.)
- _build_reflex_block wires entries via _rb.Entry(tier, line) per-line
- _reflex_snapshot keys: 'supply:pool' -> '{food}F/{water}W', 'deprived:{name}:{cause}' -> '{death_day}'
- survival module imported as _sv at module level via sys.path.insert(0, parent.parent)
"""
import json
import sys
from pathlib import Path
import importlib.util

# Load phrase_reminder via file path (same pattern as test_reflex_block.py)
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "phrase_reminder.py"
spec = importlib.util.spec_from_file_location("phrase_reminder", HOOK)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)

# Verified: _rb is the reflex_budget module alias, with URGENT/CHANGED/AMBIENT constants
import reflex_budget as rb
assert rb.URGENT == 0 and rb.AMBIENT == 2, "tier constants changed — update tests"


def _campaign(tmp_path, supply, chars):
    """Write a minimal campaign dir: characters/_meta.json + per-PC sheets."""
    chars_dir = tmp_path / "characters"
    chars_dir.mkdir()
    meta = {"campaign_day": 100, "supply": supply}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    for key, sheet in chars.items():
        (chars_dir / f"{key}.json").write_text(json.dumps(sheet))
    return tmp_path


def _vela(conditions=None):
    """Minimal biological PC sheet with optional conditions list."""
    return {"name": "Vela", "wound_table": "biological",
            "hp": {"current": 10, "max": 12},
            "inventory": {"carried": []}, "conditions": conditions or []}


# ---------------------------------------------------------------------------
# Test 1: abundant mode -> empty list (silent at a base)
# ---------------------------------------------------------------------------

def test_abundant_mode_emits_nothing(tmp_path):
    """In 'abundant' mode the supply line is silent — returns empty list."""
    d = _campaign(tmp_path, {"mode": "abundant", "pool": None,
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela()})
    # Adaptation: plan stub used == [] directly; _build_supply_block returns list[Entry]
    assert pr._build_supply_block(d) == []


# ---------------------------------------------------------------------------
# Test 2: field mode with pool -> one AMBIENT line showing pool counts
# ---------------------------------------------------------------------------

def test_field_mode_ambient_line(tmp_path):
    """Field mode + pool -> exactly one AMBIENT entry with food and water counts."""
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 16, "water": 19},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela()})
    entries = pr._build_supply_block(d)
    # Adaptation: plan used entries[0].tier, entries[0].text — Entry is a @dataclass
    # with .tier and .text; verified from reflex_budget.py
    assert len(entries) == 1
    tier, text = entries[0].tier, entries[0].text
    # Plan: "16F" and "19W" in the ambient line
    assert "16F" in text and "19W" in text
    # Adaptation: plan wrote pr._rb.AMBIENT — the actual attr is pr._rb (module alias)
    # which exposes AMBIENT=2; using rb.AMBIENT directly (same object) is equivalent
    assert tier == rb.AMBIENT


# ---------------------------------------------------------------------------
# Test 3: Deprived PC -> URGENT entry with PC name and death day
# ---------------------------------------------------------------------------

def test_deprived_is_urgent(tmp_path):
    """Deprived condition record -> URGENT entry naming the PC and 'Day 102'."""
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 0, "water": 0},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela(conditions=conds)})
    entries = pr._build_supply_block(d)
    # Adaptation: plan checked pr._rb.URGENT; using rb.URGENT (same constant, verified 0)
    urgent = [e for e in entries if e.tier == rb.URGENT]
    assert any("Vela" in e.text and "Day 102" in e.text for e in urgent)


# ---------------------------------------------------------------------------
# Test 4: snapshot keys present and metric-labeled (mirrors test_reflex_block.py §6)
# ---------------------------------------------------------------------------

def test_snapshot_keys_field_mode(tmp_path):
    """After _build_reflex_block in field mode, snapshot contains supply:pool
    and (when Deprived) deprived:{name}:{cause} — per-cause keys so a PC
    Deprived by thirst AND starvation gets two entries, no clobbering."""
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 7, "water": 5},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela(conditions=conds)})
    state = {}
    pr._build_reflex_block(d, state=state)
    snap = state.get("reflex_snapshot", {})
    # supply:pool key present — value is "{food}F/{water}W"
    assert "supply:pool" in snap
    assert snap["supply:pool"] == "7F/5W"
    # deprived:{name}:{cause} key present — value is "{death_day}"
    assert "deprived:Vela:thirst" in snap
    assert snap["deprived:Vela:thirst"] == "102"


def test_snapshot_two_cause_deprived_no_clobber(tmp_path):
    """A PC Deprived by BOTH thirst and starvation -> two distinct snapshot keys."""
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102},
             {"name": "Deprived", "cause": "starvation", "since_day": 100, "death_day": 103}]
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 0, "water": 0},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela(conditions=conds)})
    snap = pr._reflex_snapshot(d)
    assert snap.get("deprived:Vela:thirst") == "102"
    assert snap.get("deprived:Vela:starvation") == "103"


def test_deprived_missing_death_day_renders_unknown(tmp_path):
    """Garbage record without death_day still renders, as 'dies Day unknown'."""
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99}]
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 0, "water": 0},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela(conditions=conds)})
    entries = pr._build_supply_block(d)
    urgent = [e for e in entries if e.tier == rb.URGENT]
    assert any("Vela" in e.text and "dies Day unknown" in e.text for e in urgent)
    assert not any("None" in e.text for e in urgent)


# ---------------------------------------------------------------------------
# Test 5: mode-flip Δ — supply keys appearing and disappearing fire diff lines
# (mirrors test_reflex_block.py's snapshot-diff mechanics: seed
# state['reflex_snapshot'], call _build_reflex_block, assert on Δ text)
# ---------------------------------------------------------------------------

def test_mode_flip_delta_lines(tmp_path):
    """abundant -> field: Δ none→pool; field -> abundant: Δ pool→none (once)."""
    # Start abundant: snapshot has NO supply keys
    d = _campaign(tmp_path, {"mode": "abundant", "pool": None,
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  {"vela": _vela()})
    meta_path = d / "characters" / "_meta.json"
    state = {}
    pr._build_reflex_block(d, state=state)
    assert "supply:pool" not in state["reflex_snapshot"]

    # Flip to field with a pool -> the appearing key fires a Δ none→ line
    meta_path.write_text(json.dumps(
        {"campaign_day": 100,
         "supply": {"mode": "field", "pool": {"food": 7, "water": 5},
                    "follower_mouths": 0, "separated": [],
                    "ledger": {"day": 100, "consumed": {}}}}))
    block = pr._build_reflex_block(d, state=state)
    assert "Δ pool none→7F/5W" in block
    assert state["reflex_snapshot"].get("supply:pool") == "7F/5W"

    # Flip back to abundant -> the disappearing key fires Δ →none ONCE
    meta_path.write_text(json.dumps(
        {"campaign_day": 100,
         "supply": {"mode": "abundant", "pool": None,
                    "follower_mouths": 0, "separated": [],
                    "ledger": {"day": 100, "consumed": {}}}}))
    block = pr._build_reflex_block(d, state=state)
    assert "Δ pool 7F/5W→none" in block
    # ...and only once: the key is gone from the written-back snapshot,
    # so the NEXT turn has no delta to report
    assert "supply:pool" not in state["reflex_snapshot"]
    block = pr._build_reflex_block(d, state=state)
    assert "Δ pool" not in block


# ---------------------------------------------------------------------------
# Test 6: URGENT survives the cap — reflex_budget.compose always keeps URGENT
# entries; pad the block past 600 chars with ambient depletables and assert
# the DEPRIVED line is still rendered
# ---------------------------------------------------------------------------

def test_deprived_urgent_survives_cap(tmp_path):
    """Field mode + Deprived PC + enough LOAD padding to blow past the cap ->
    the DEPRIVED line still appears (URGENT tier is never trimmed)."""
    conds = [{"name": "Deprived", "cause": "thirst", "since_day": 99, "death_day": 102}]
    chars = {"vela": _vela(conditions=conds)}
    # 9 padding PCs x 4 depletable gadgets -> raw LOAD block alone > 600 chars
    for i in range(9):
        chars[f"pc{i}"] = {
            "name": f"Padder{i}", "wound_table": "biological",
            "hp": {"current": 10, "max": 10},
            "inventory": {"carried": [
                {"name": f"Gadget{j}", "slots": 1, "usage_die": "Ud8"}
                for j in range(4)]},
            "conditions": []}
    d = _campaign(tmp_path, {"mode": "field", "pool": {"food": 0, "water": 0},
                             "follower_mouths": 0, "separated": [],
                             "ledger": {"day": 100, "consumed": {}}},
                  chars)
    raw_load = pr._build_load_block(d)
    assert len(raw_load) > rb.DEFAULT_CAP  # the padding really exceeds the cap
    block = pr._build_reflex_block(d, state={})
    assert "DEPRIVED: Vela thirst" in block
    assert "Day 102" in block
