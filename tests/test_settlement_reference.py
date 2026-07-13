"""tests/test_settlement_reference.py — B4 integration tests for reference_location settlement scopes.

Tests that scope="who" and scope="trade" delegate to settlement_system BEFORE
the hand-authored LOCATION_REGISTRY path in reference_location.
"""
import server

SETTLEMENT_OK = '''<!-- SITE: key=foo scene=settlement aliases="Foo" -->
# FOO — PREP
## NPCs
### ALDA — Keeper
**Location:** the_gate
**Role:** guards the gate
## TRADE GOODS AVAILABLE
- rope
'''


def test_reference_location_who_returns_card(tmp_path, monkeypatch):
    (tmp_path / "FOO_PREP.md").write_text(SETTLEMENT_OK, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.reference_location(location="foo", scope="who")
    assert "ALDA" in out and "the_gate" in out


def test_reference_location_trade_returns_market(tmp_path, monkeypatch):
    (tmp_path / "FOO_PREP.md").write_text(SETTLEMENT_OK, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.reference_location(location="foo", scope="trade")
    assert "rope" in out


# ---------------------------------------------------------------------------
# Task C2: card overlays (end-to-end — place_overlay from PROGRESS LOG)
# ---------------------------------------------------------------------------

def test_card_shows_standing_banner_from_progress_log(tmp_path, monkeypatch):
    """_settlement_overlays must parse STATUS stamps and pass them to build_who_card."""
    body = SETTLEMENT_OK + "\n## PROGRESS LOG\n### Day 112\n- STATUS: party_standing: HOSTILE (Day 112)\n"
    (tmp_path / "FOO_PREP.md").write_text(body, encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.reference_location(location="foo", scope="who")
    assert "HOSTILE" in out


# ---------------------------------------------------------------------------
# Task 4: Ceruline bespoke reader routing + registry pointer
# ---------------------------------------------------------------------------
from pathlib import Path

CER_FIXTURE = (Path(__file__).resolve().parent.parent.parent
               / "rubicon-seven-campaign" / "CERULINE_PLAYER_REFERENCE.md")


def test_ceruline_who_no_focus_lists_tiers(monkeypatch, tmp_path):
    if not CER_FIXTURE.exists():
        import pytest; pytest.skip("fixture absent")
    (tmp_path / "CERULINE_PLAYER_REFERENCE.md").write_text(
        CER_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.reference_location(location="Ceruline", scope="who", focus=None)
    assert "which tier?" in out


def test_ceruline_who_focus_returns_card(monkeypatch, tmp_path):
    if not CER_FIXTURE.exists():
        import pytest; pytest.skip("fixture absent")
    (tmp_path / "CERULINE_PLAYER_REFERENCE.md").write_text(
        CER_FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    out = server.reference_location(location="Ceruline", scope="who", focus="Noble Quarter")
    assert "(T10)" in out and "Scholar Tiberius" in out


def test_registry_pointer_is_real_file():
    # The Ceruline registry entry must not name a non-existent file.
    src = Path(server.__file__).read_text(encoding="utf-8")
    assert "CERULINE_ARCOLOGY_REFERENCE.md" not in src
    assert "CERULINE_PLAYER_REFERENCE.md" in src
