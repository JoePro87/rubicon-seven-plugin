"""Revealed Ledger: state["revealed_ledger"] auto-appended by enter/search/reveal_secret,
plus the explicit map(action="reveal") lever (reveal_fact). Whitelist-by-construction —
only text the party has legitimately learned may enter the ledger (see map_system.py
_ledger_append docstring)."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem
import server


PREP = """## ROOM: room_a
**Floor:** 1
**Coords:** 5,5
**Name:** Room A
**Entrance:** true
**Connections:** e→room_b
**Loot:** rusted dagger

## ROOM: room_b
**Floor:** 1
**Coords:** 6,5
**Name:** Room B
**Connections:** w→room_a

## ENCOUNTERS
Roll d6 every 1 turn
"""

PREP_WITH_SECRET = """## ROOM: room_a
**Floor:** 1
**Coords:** 5,5
**Name:** Room A
**Entrance:** true
**Secrets:** secret_1→room_b (search the east wall)

## ROOM: room_b
**Floor:** 1
**Coords:** 6,5
**Name:** Room B

## ENCOUNTERS
Roll d6 every 1 turn
"""


@pytest.fixture
def map_sys(tmp_path):
    return MapSystem(tmp_path)


@pytest.fixture
def tmp_map(map_sys, tmp_path):
    prep = tmp_path / "TEST_LEDGER_PREP.md"
    prep.write_text(PREP, encoding="utf-8")
    map_sys.init_map_from_prep("ledgervault", "TEST_LEDGER_PREP.md", "vault")
    return "ledgervault"


@pytest.fixture
def tmp_map_with_secret(map_sys, tmp_path):
    prep = tmp_path / "TEST_SECRET_PREP.md"
    prep.write_text(PREP_WITH_SECRET, encoding="utf-8")
    map_sys.init_map_from_prep("secretvault", "TEST_SECRET_PREP.md", "vault")
    return "secretvault"


@pytest.fixture
def tmp_map_with_loot(tmp_map):
    return tmp_map


def test_reveal_fact_appends_and_persists(map_sys, tmp_map):
    map_sys.reveal_fact(tmp_map, "The seal bears a hound sigil", room_id="antechamber", provenance="mint")
    state = map_sys.get_map_state(tmp_map)
    entry = state["revealed_ledger"][-1]
    assert entry["fact"] == "The seal bears a hound sigil"
    assert entry["source_room"] == "antechamber"
    assert entry["source_action"] == "reveal"


def test_reveal_secret_ledgers(map_sys, tmp_map_with_secret):
    map_sys.reveal_secret(tmp_map_with_secret, "room_a", "secret_1")
    state = map_sys.get_map_state(tmp_map_with_secret)
    assert any(e["source_action"] == "reveal_secret" for e in state["revealed_ledger"])


def test_enter_first_visit_ledgers_once(map_sys, tmp_map):
    map_sys.enter_room(tmp_map, "room_b")
    map_sys.enter_room(tmp_map, "room_a")
    map_sys.enter_room(tmp_map, "room_b")
    state = map_sys.get_map_state(tmp_map)
    marks = [e for e in state["revealed_ledger"] if e["source_room"] == "room_b" and e["source_action"] == "enter"]
    assert len(marks) == 1


def test_search_ledgers_loot(map_sys, tmp_map_with_loot):
    map_sys.search_room(tmp_map_with_loot, "room_a")
    state = map_sys.get_map_state(tmp_map_with_loot)
    assert any("loot" in e["fact"].lower() or e["source_action"] == "search" for e in state["revealed_ledger"])


def test_reveal_fact_empty_rejected(map_sys, tmp_map):
    out = map_sys.reveal_fact(tmp_map, "   ", provenance="mint")
    assert "❌" in out


def test_reveal_fact_autocreates_social_ledger(map_sys):
    """Non-vault reveal home: with no map for this name, reveal_fact mints a
    ledger-only state ONLY when the injected sanction callback approves the
    name (the active prep's stem, in live wiring)."""
    map_sys.ledger_autocreate_ok = lambda name: name == "hollow_market_prep"
    out = map_sys.reveal_fact("hollow_market_prep", "The broker runs the debt ring", provenance="mint")
    assert "Ledgered" in out
    state = map_sys.get_map_state("hollow_market_prep")
    assert state and state.get("kind") == "ledger"
    assert state["revealed_ledger"][-1]["fact"] == "The broker runs the debt ring"


def test_reveal_fact_unknown_name_still_errors(map_sys):
    """A name the sanction rejects (e.g. a typo'd vault name) still hard-errors
    on a missing map — auto-create is scoped to the active prep only."""
    map_sys.ledger_autocreate_ok = lambda name: False
    out = map_sys.reveal_fact("no_such_map", "x", provenance="mint")
    assert "Map not found" in out


# ---------------------------------------------------------------------------
# _revealed_ledger_injection (check_canon injection, Task 2)
# ---------------------------------------------------------------------------

def _mock_state(ledger):
    return {"revealed_ledger": ledger}


def test_ledger_injection_renders_facts(monkeypatch):
    ledger = [
        {"fact": "The seal bears a hound sigil", "day": 3, "source_room": "antechamber", "source_action": "reveal"},
        {"fact": "The vault hums with power", "day": 3, "source_room": "antechamber", "source_action": "reveal"},
    ]
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 3))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: _mock_state(ledger))
    block = server._revealed_ledger_injection()
    assert "REVEALED LEDGER" in block
    assert "hound sigil" in block
    assert "NPCs may assert ONLY these facts" in block


def test_ledger_injection_empty_ledger_still_charters(monkeypatch):
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: _mock_state([]))
    block = server._revealed_ledger_injection()
    assert "Nothing discovered yet" in block
    assert "unspeakable" in block.lower()


def test_ledger_injection_no_vault(monkeypatch, tmp_path):
    # No vault AND no active prep -> no injection. Point CAMPAIGN_DIR at an empty
    # tmp dir and clear the active prep so the non-vault path finds no prep
    # (never reads live campaign data).
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    assert server._revealed_ledger_injection() == ""


def test_ledger_injection_social_scene_charters(monkeypatch, tmp_path):
    """Non-vault turn with an Active Prep carrying DM-only content: the charter
    injects using the prep-scoped ledger name (the prep stem), even with no
    reveals yet. This is the social/settlement lane the original incident hit."""
    server._DM_NOUN_CACHE["key"] = None
    server._DM_NOUN_CACHE["nouns"] = frozenset()
    prep = tmp_path / "HOLLOW_MARKET_PREP.md"
    prep.write_text(
        "## OVERVIEW\n**Name:** Hollow Market\nStalls under a torn awning.\n\n"
        "## DM ONLY — THE TRUTH\n"
        "The broker VESKARN secretly runs the slave-debt ring.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: None)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", prep.name)
    block = server._revealed_ledger_injection()
    assert "REVEALED LEDGER" in block
    assert "HOLLOW_MARKET_PREP" in block  # prep-stem ledger name
    assert "unspeakable" in block.lower()
    assert "Nothing discovered yet" in block


def test_ledger_injection_prepless_social_silent(monkeypatch, tmp_path):
    """Non-vault turn with no active prep: no injection (prepless scenes stay
    quiet)."""
    server._DM_NOUN_CACHE["key"] = None
    server._DM_NOUN_CACHE["nouns"] = frozenset()
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    assert server._revealed_ledger_injection() == ""


def test_ledger_injection_caps_at_8(monkeypatch):
    ledger = [
        {"fact": f"fact {i}", "day": 1, "source_room": "r", "source_action": "reveal"}
        for i in range(12)
    ]
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: _mock_state(ledger))
    block = server._revealed_ledger_injection()
    for i in range(4, 12):
        assert f"fact {i}\n" in block or f"fact {i} " in block
    for i in range(0, 4):
        assert f"fact {i}\n" not in block and f"fact {i} " not in block
    assert "(+4 earlier" in block
