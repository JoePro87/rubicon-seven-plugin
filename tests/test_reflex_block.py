# tests/test_reflex_block.py
"""Integration: _build_reflex_block composes LOAD/WOUNDS through the reflex editor.

Fail-silent contract, tier ordering, snapshot delta detection, and snapshot write-back.
Import pattern copied verbatim from tests/test_wounds_reminder.py.
"""
import json
from pathlib import Path
import importlib.util

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "phrase_reminder.py"
spec = importlib.util.spec_from_file_location("phrase_reminder", HOOK)
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)


# ---------------------------------------------------------------------------
# Fixture helpers — mirror _write_char from test_wounds_reminder.py
# ---------------------------------------------------------------------------

def _write_char(dirpath, name, carried=None, capacity=13, wounds=None,
                gifts=0, codices=0):
    (dirpath / "characters").mkdir(exist_ok=True)
    wounds = wounds or []
    wound_slots = sum(r.get("slots", 0) for r in wounds if isinstance(r, dict))
    (dirpath / "characters" / f"{name.lower()}.json").write_text(json.dumps({
        "name": name, "slot_capacity_total": capacity,
        "wounds": wounds, "wounds_slots_used": wound_slots,
        "mystic_gifts": ["g"] * gifts, "codices": ["c"] * codices,
        "inventory": {"carried": carried or []},
    }))


# ---------------------------------------------------------------------------
# Test 1: empty campaign -> empty block
# ---------------------------------------------------------------------------

def test_reflex_block_empty_when_nothing_live(tmp_path):
    """No characters dir, no state -> returns empty string."""
    assert pr._build_reflex_block(tmp_path, state={}) == ""


def test_reflex_block_empty_when_clean_char(tmp_path):
    """Character with no wounds and no depletables -> empty block."""
    _write_char(tmp_path, "Kess", carried=[{"name": "Rope", "slots": 1}])
    assert pr._build_reflex_block(tmp_path, state={}) == ""


# ---------------------------------------------------------------------------
# Test 2: urgent wounds rank above load in the composed block
# ---------------------------------------------------------------------------

def test_wounds_with_flags_rank_urgent_above_load(tmp_path):
    """UNCONSCIOUS flag -> WOUNDS is URGENT; should appear before LOAD."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"}],
                wounds=[{"name": "Cracked Skull", "slots": 2,
                         "unconscious": True, "duration": "4 hours",
                         "effect": "-d8 INT. Pass out."}])
    block = pr._build_reflex_block(tmp_path, state={})
    assert "WOUNDS:" in block
    assert "LOAD:" in block
    assert block.index("WOUNDS:") < block.index("LOAD:")


def test_deaths_door_is_urgent(tmp_path):
    """DEATH'S DOOR flag triggers URGENT tier for wounds."""
    _write_char(tmp_path, "Roscar",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}],
                wounds=[{"name": "Death's Door", "slots": 5,
                         "deaths_door": True, "unconscious": True,
                         "effect": "Any further damage is LETHAL."}])
    block = pr._build_reflex_block(tmp_path, state={})
    assert "DEATH'S DOOR" in block
    assert block.index("WOUNDS:") < block.index("LOAD:")


def test_must_drop_is_urgent(tmp_path):
    """MUST DROP flag triggers URGENT tier for wounds."""
    # cap=13, wound_slots=5 -> gear_room=8; gear=9 slots -> drop 1
    _write_char(tmp_path, "Vela", capacity=13,
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"},
                         {"name": "Loot", "slots": 8}],
                wounds=[{"name": "Death's Door", "slots": 5,
                         "deaths_door": True, "unconscious": True,
                         "effect": "lethal"}])
    block = pr._build_reflex_block(tmp_path, state={})
    assert "MUST DROP" in block
    assert block.index("WOUNDS:") < block.index("LOAD:")


def test_save_owed_is_urgent(tmp_path):
    """'save owed' text in wounds block triggers URGENT tier."""
    _write_char(tmp_path, "Petros",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"}],
                wounds=[{"name": "Knocked Out", "slots": 0,
                         "pending_con_save": True,
                         "effect": "CON save vs unconscious d6 rounds"}])
    block = pr._build_reflex_block(tmp_path, state={})
    # 'save owed' appears in the rendered wounds text (from _render_wound)
    assert "save owed" in block
    assert block.index("WOUNDS:") < block.index("LOAD:")


# ---------------------------------------------------------------------------
# Test 3: ambient wounds appear after load (ENCUMBERED makes load urgent)
# ---------------------------------------------------------------------------

def test_encumbered_load_urgent_above_ambient_wounds(tmp_path):
    """ENCUMBERED load -> LOAD is URGENT; ambient wounds rank below.

    Fixture: gear = 1 (Blowtorch) + 13 (Loot) = 14 > cap 13 -> ENCUMBERED.
    Wound has 0 slots (KO-style slot value) so MUST DROP never fires;
    no unconscious/deaths_door/save-owed flags -> wounds stay AMBIENT.
    """
    _write_char(tmp_path, "Vela", capacity=13,
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"},
                         {"name": "Loot", "slots": 13}],
                wounds=[{"name": "Bloody Gash", "slots": 0,
                         "effect": "-d8 max HP"}])
    block = pr._build_reflex_block(tmp_path, state={})
    assert "ENCUMBERED" in block
    assert "WOUNDS:" in block
    assert block.index("LOAD:") < block.index("WOUNDS:")


# ---------------------------------------------------------------------------
# Test 4: Δ line appears when a usage die differs from snapshot
# ---------------------------------------------------------------------------

def test_changed_line_on_usage_die_step(tmp_path):
    """Snapshot has Ud8; campaign fixture has Ud6 -> Δ line appears."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    state = {"reflex_snapshot": {"die:Vela|Blowtorch": "Ud8"}}
    block = pr._build_reflex_block(tmp_path, state=state)
    assert "Δ Vela|Blowtorch Ud8→Ud6" in block


def test_changed_line_on_wound_count(tmp_path):
    """Snapshot has 0 wounds; PC now has 1 -> Δ line, metric in the label."""
    _write_char(tmp_path, "Vela",
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    state = {"reflex_snapshot": {"wounds:Vela wounds": "0"}}
    block = pr._build_reflex_block(tmp_path, state=state)
    assert "Δ Vela wounds 0→1" in block


def test_same_pc_wounds_and_load_deltas_distinct(tmp_path):
    """Same PC, wounds AND load both changed -> two textually distinct Δ lines."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}],
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    # current: wounds=1; load = 1 (Blowtorch) + 1 (wound slot) = 2/13
    state = {"reflex_snapshot": {"wounds:Vela wounds": "0",
                                 "load:Vela load": "1/13"}}
    block = pr._build_reflex_block(tmp_path, state=state)
    assert "Δ Vela wounds 0→1" in block
    assert "Δ Vela load 1/13→2/13" in block


def test_changed_line_on_integer_uses_step(tmp_path):
    """Integer-uses depletables get Δ coverage too (x3 -> x2)."""
    _write_char(tmp_path, "Kess",
                carried=[{"name": "Draught", "slots": 1, "uses": 2}])
    state = {"reflex_snapshot": {"die:Kess|Draught": "x3"}}
    block = pr._build_reflex_block(tmp_path, state=state)
    assert "Δ Kess|Draught x3→x2" in block


# ---------------------------------------------------------------------------
# Test 5: first turn (no snapshot) -> no Δ spam
# ---------------------------------------------------------------------------

def test_first_turn_no_delta_spam(tmp_path):
    """Empty state (no reflex_snapshot key) -> no Δ lines."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    block = pr._build_reflex_block(tmp_path, state={})
    assert "Δ" not in block


def test_none_snapshot_no_delta_spam(tmp_path):
    """Explicit None snapshot -> no Δ lines (same as missing)."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    block = pr._build_reflex_block(tmp_path, state={"reflex_snapshot": None})
    assert "Δ" not in block


# ---------------------------------------------------------------------------
# Test 6: snapshot written back into state dict
# ---------------------------------------------------------------------------

def test_snapshot_written_back_die(tmp_path):
    """After building, state['reflex_snapshot'] holds the current die value."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    state = {}
    pr._build_reflex_block(tmp_path, state=state)
    assert "reflex_snapshot" in state
    assert state["reflex_snapshot"].get("die:Vela|Blowtorch") == "Ud6"


def test_snapshot_written_back_wounds(tmp_path):
    """After building, snapshot holds wound count for the PC (metric-labeled key)."""
    _write_char(tmp_path, "Roscar",
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"},
                        {"name": "Crippling Wound", "slots": 1, "dis_saves": ["DEX"],
                         "effect": "DIS DEX"}])
    state = {}
    pr._build_reflex_block(tmp_path, state=state)
    assert state["reflex_snapshot"].get("wounds:Roscar wounds") == "2"


def test_snapshot_written_back_load(tmp_path):
    """After building, snapshot holds load string for the PC (metric-labeled key)."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"},
                         {"name": "Loot", "slots": 3}],
                capacity=13)
    state = {}
    pr._build_reflex_block(tmp_path, state=state)
    assert state["reflex_snapshot"].get("load:Vela load") == "4/13"


def test_snapshot_integer_uses_item(tmp_path):
    """Integer-uses depletables land in the snapshot as 'xN'."""
    _write_char(tmp_path, "Kess",
                carried=[{"name": "Draught", "slots": 1, "uses": 3}])
    state = {}
    pr._build_reflex_block(tmp_path, state=state)
    assert state["reflex_snapshot"].get("die:Kess|Draught") == "x3"


def test_snapshot_skips_non_pc_files(tmp_path):
    """A dict JSON without 'inventory' (config/non-PC file) contributes nothing."""
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    (tmp_path / "characters" / "party_config.json").write_text(json.dumps({
        "name": "PartyConfig", "wounds": [{"name": "Ghost Wound", "slots": 1}]}))
    snap = pr._reflex_snapshot(tmp_path)
    assert not any("PartyConfig" in k for k in snap)
    assert "die:Vela|Blowtorch" in snap


# ---------------------------------------------------------------------------
# Test 7: fail-silent on contributor crash (and the crash is LOGGED)
# ---------------------------------------------------------------------------

def _redirect_log(monkeypatch, tmp_path):
    """Point the reflex error log at a tmp file so tests never touch the live log."""
    log = tmp_path / "reflex_errors.log"
    monkeypatch.setattr(pr, "REFLEX_ERROR_LOG", log)
    return log


def test_fail_silent_on_wounds_block_crash(monkeypatch, tmp_path):
    """If _build_wounds_block raises, _build_reflex_block returns '' silently."""
    _redirect_log(monkeypatch, tmp_path)
    def _boom(*_args):
        raise RuntimeError("simulated wounds crash")
    monkeypatch.setattr(pr, "_build_wounds_block", _boom)
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    result = pr._build_reflex_block(tmp_path, state={})
    assert result == ""


def test_fail_silent_on_load_block_crash(monkeypatch, tmp_path):
    """If _build_load_block raises, _build_reflex_block returns '' silently."""
    _redirect_log(monkeypatch, tmp_path)
    def _boom(*_args):
        raise RuntimeError("simulated load crash")
    monkeypatch.setattr(pr, "_build_load_block", _boom)
    _write_char(tmp_path, "Vela",
                wounds=[{"name": "Bloody Gash", "slots": 1, "effect": "-d8 max HP"}])
    result = pr._build_reflex_block(tmp_path, state={})
    assert result == ""


def test_fail_silent_on_snapshot_crash(monkeypatch, tmp_path):
    """If _reflex_snapshot raises, _build_reflex_block returns '' silently."""
    _redirect_log(monkeypatch, tmp_path)
    def _boom(*_args):
        raise RuntimeError("simulated snapshot crash")
    monkeypatch.setattr(pr, "_reflex_snapshot", _boom)
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    result = pr._build_reflex_block(tmp_path, state={})
    assert result == ""


def test_contributor_crash_is_logged(monkeypatch, tmp_path):
    """Fail-silent must still leave a trace in the error log (spec rule)."""
    log = _redirect_log(monkeypatch, tmp_path)
    def _boom(*_args):
        raise RuntimeError("boom for the log")
    monkeypatch.setattr(pr, "_build_wounds_block", _boom)
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"}])
    assert pr._build_reflex_block(tmp_path, state={}) == ""
    text = log.read_text(encoding="utf-8")
    assert "reflex_block:" in text
    assert "boom for the log" in text


# ---------------------------------------------------------------------------
# Test 8: composed block within cap with realistic content
# ---------------------------------------------------------------------------

def test_composed_block_within_default_cap(tmp_path):
    """Realistic fixture: 1 urgent wound + 1 delta + load stays within 600 chars."""
    import reflex_budget as rb
    _write_char(tmp_path, "Vela",
                carried=[{"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"},
                         {"name": "Rope", "slots": 1}],
                capacity=13,
                wounds=[{"name": "Cracked Skull", "slots": 2,
                         "unconscious": True, "duration": "4 hours",
                         "effect": "-d8 INT. Pass out."}])
    state = {"reflex_snapshot": {"die:Vela|Blowtorch": "Ud8"}}
    block = pr._build_reflex_block(tmp_path, state=state)
    assert len(block) <= rb.DEFAULT_CAP + 50  # allow slight overage for urgent-always rule


# ---------------------------------------------------------------------------
# Test 9: no characters dir -> empty string (not a crash)
# ---------------------------------------------------------------------------

def test_reflex_block_missing_characters_dir(tmp_path):
    """No characters/ directory at all -> ''."""
    assert pr._build_reflex_block(tmp_path, state={}) == ""


# ---------------------------------------------------------------------------
# Test 10: per-line tiering — the cap TRIMS oversized content, never
# annihilates it (the real campaign's LOAD block alone exceeds 600 chars)
# ---------------------------------------------------------------------------

def test_oversized_load_trims_not_annihilates(tmp_path):
    """9 PCs with many depletables -> raw LOAD block far over the cap, yet the
    composed block keeps 'LOAD:' and reports the trimmed tail as quiet."""
    import re
    import reflex_budget as rb
    for i in range(9):
        _write_char(tmp_path, f"Pc{i}", carried=[
            {"name": f"Gadget{j}", "slots": 1, "usage_die": "Ud8"}
            for j in range(4)])
    raw = pr._build_load_block(tmp_path)
    assert len(raw) > rb.DEFAULT_CAP  # the failure mode being fixed
    block = pr._build_reflex_block(tmp_path, state={})
    assert "LOAD:" in block
    assert re.search(r"\(\+\d+ quiet\)", block)


def test_quiet_state_real_shape_composes_nonempty(tmp_path):
    """A real-campaign-shaped quiet state (several PCs, many depletables, no
    wounds, nobody encumbered) must still render a non-empty block."""
    _write_char(tmp_path, "Kettle", carried=[
        {"name": "Blowtorch", "slots": 1, "usage_die": "Ud6"},
        {"name": "Rations", "slots": 1, "usage_die": "Ud8"},
        {"name": "Sprayflesh", "slots": 1, "uses": 2},
    ])
    _write_char(tmp_path, "Roscar", carried=[
        {"name": "Railgun", "slots": 2, "ammo": "Ud10"},
        {"name": "Repair Paste", "slots": 1, "uses": 3},
    ])
    _write_char(tmp_path, "Vela", carried=[
        {"name": "Needle Pistol", "slots": 1, "ammo": "Ud8"},
        {"name": "Glowcubes", "slots": 1, "uses": 4},
    ])
    block = pr._build_reflex_block(tmp_path, state={})
    assert block != ""
    assert "LOAD:" in block
