"""A0.1 provenance stamps on revealed-ledger writes (spec §4, design 2026-07-22)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from map_system import MapSystem  # noqa: E402


def _mk(tmp_path):
    ms = MapSystem(tmp_path)
    (tmp_path / "maps").mkdir(exist_ok=True)
    return ms


def test_ledger_append_stores_provenance(tmp_path):
    ms = _mk(tmp_path)
    state = {}
    ms._ledger_append(state, "The door is bronze", "r1", "reveal", provenance="mint")
    assert state["revealed_ledger"][0]["provenance"] == "mint"


def test_ledger_append_no_provenance_key_when_empty(tmp_path):
    ms = _mk(tmp_path)
    state = {}
    ms._ledger_append(state, "The door is bronze", "r1", "enter")
    assert "provenance" not in state["revealed_ledger"][0]


def test_auto_append_seams_self_stamp_map(tmp_path):
    """enter_room / search_room / reveal_secret write engine-derived facts:
    their source IS the map JSON, so they self-stamp provenance='map'."""
    ms = _mk(tmp_path)
    state = {
        "rooms": {"r1": {"name": "Salt Hall", "discovery_state": "unknown",
                         "exits": {}, "features": []}},
        "current_room": None, "current_turn": 0,
    }
    # Call the append exactly as enter_room does, with the new stamp:
    ms._ledger_append(state, "Entered Salt Hall", "r1", "enter", provenance="map")
    assert state["revealed_ledger"][0]["provenance"] == "map"


def _mk_with_map(tmp_path):
    ms = _mk(tmp_path)
    state = {"rooms": {}, "revealed_ledger": [
        {"fact": "Salt-bore: 60m shaft", "day": 1, "source_room": "", "source_action": "reveal"},
    ]}
    ms.save_map_state("testvault", state)
    return ms


def test_reveal_without_provenance_rejected_nothing_written(tmp_path):
    ms = _mk_with_map(tmp_path)
    out = ms.reveal_fact("testvault", "Ceruline is Node Four")
    assert "REJECTED" in out and "provenance" in out
    assert len(ms.get_map_state("testvault")["revealed_ledger"]) == 1


def test_reveal_mint_succeeds_and_is_labeled(tmp_path):
    ms = _mk_with_map(tmp_path)
    out = ms.reveal_fact("testvault", "A brass bell hangs in the stairwell", provenance="mint")
    assert "REJECTED" not in out
    entries = ms.get_map_state("testvault")["revealed_ledger"]
    assert entries[-1]["provenance"] == "mint"


def test_reveal_player_succeeds(tmp_path):
    ms = _mk_with_map(tmp_path)
    ms.reveal_fact("testvault", "We named the mule Petros", provenance="player")
    assert ms.get_map_state("testvault")["revealed_ledger"][-1]["provenance"] == "player"


def test_reveal_ledger_ref_valid_and_invalid(tmp_path):
    ms = _mk_with_map(tmp_path)
    ok = ms.reveal_fact("testvault", "The shaft lip has crumbled further", provenance="ledger:1")
    assert "REJECTED" not in ok
    bad = ms.reveal_fact("testvault", "Phantom fact", provenance="ledger:99")
    assert "REJECTED" in bad
    assert len(ms.get_map_state("testvault")["revealed_ledger"]) == 2  # 1 seed + 1 ok


def test_reveal_prep_ref_verified_against_active_prep(tmp_path):
    ms = _mk_with_map(tmp_path)
    ms.get_prep_text = lambda: "The keeper maintains the stacks against the salt wind."
    ok = ms.reveal_fact("testvault", "The keeper maintains the stacks",
                        provenance='prep:keeper maintains the stacks')
    assert "REJECTED" not in ok
    bad = ms.reveal_fact("testvault", "The keeper commands a fleet",
                         provenance='prep:commands a fleet')
    assert "REJECTED" in bad


def test_reveal_prep_ref_fails_closed_without_prep_text(tmp_path):
    ms = _mk_with_map(tmp_path)          # get_prep_text is None
    out = ms.reveal_fact("testvault", "Anything", provenance="prep:anything at all")
    assert "REJECTED" in out


def test_reveal_prep_ref_too_short_rejected(tmp_path):
    ms = _mk_with_map(tmp_path)
    ms.get_prep_text = lambda: "abc is here"
    out = ms.reveal_fact("testvault", "Anything", provenance="prep:abc")
    assert "REJECTED" in out


def test_ledger_injection_marks_minted_entries(tmp_path, monkeypatch):
    """DM-facing ledger surface: minted entries carry a [MINTED] label so the
    DM sees which facts the engine could NOT source to prep/ledger/player;
    earned/unstamped entries stay unlabeled. Player journal is unaffected."""
    import server
    ms = _mk_with_map(tmp_path)  # seeds one unstamped "Salt-bore" entry
    ms.reveal_fact("testvault", "A brass bell hangs in the stairwell", provenance="mint")
    # _revealed_ledger_injection() takes no args; it derives the ledger name via
    # _active_vault_turn() and reads the module-level map_system. Monkeypatch
    # both seams so the injection renders OUR seeded ledger on a vault turn.
    monkeypatch.setattr(server, "map_system", ms)
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    out = server._revealed_ledger_injection()
    assert "brass bell" in out
    assert "[MINTED]" in out
    minted_lines = [l for l in out.splitlines() if "[MINTED]" in l]
    # Only the minted entry is labeled; the earned Salt-bore entry is not.
    assert "brass bell" in minted_lines[0]
    assert not any("Salt-bore" in l for l in minted_lines)
