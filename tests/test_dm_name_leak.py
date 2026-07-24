"""Reveal discipline Part B (Task 3): DM-only proper-noun tripwire in validate_prose.

Blocks narration that leaks an invented DM-only name (from the active prep's
⛔ DM ONLY ⛔ blocks) before it has been ledgered via the Revealed Ledger
(map(action="reveal", ...)). Deterministic, fail-open (never blocks live play
on a bug in this check).
"""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


PREP_TEXT = """## ROOM: antechamber
**Name:** Antechamber
**Description:** A dusty entry hall. The Antechamber smells of ozone.

⛔ DM ONLY ⛔
The true name of the guardian is VORNMEK. It was bound here by the
sorcerer Tessarine, who is never named aloud by the living.
⛔ END DM ONLY ⛔

## ENCOUNTERS
Roll d6 every 1 turn
"""


@pytest.fixture
def tmp_prep(tmp_path):
    p = tmp_path / "TEST_DM_NAME_PREP.md"
    p.write_text(PREP_TEXT, encoding="utf-8")
    return p


@pytest.fixture(autouse=False)
def _reset_cache():
    server._DM_NOUN_CACHE["key"] = None
    server._DM_NOUN_CACHE["nouns"] = frozenset()
    yield
    server._DM_NOUN_CACHE["key"] = None
    server._DM_NOUN_CACHE["nouns"] = frozenset()


def _wire_active_prep(monkeypatch, tmp_path, tmp_prep, ledger=None):
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(
        server.map_system, "get_map_state",
        lambda name: {"revealed_ledger": ledger or []},
    )
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", tmp_prep.name)


def test_dm_only_name_blocked(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    _wire_active_prep(monkeypatch, tmp_path, tmp_prep)
    hits = server._vp_check_dm_name_leaks('Tesslyn whispers: "VORNMEK is starving."')
    assert hits and "vornmek" in hits[0].lower()


def test_mixed_case_dm_only_name_blocked(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    _wire_active_prep(monkeypatch, tmp_path, tmp_prep)
    hits = server._vp_check_dm_name_leaks('The old woman mutters, "I served Tessarine once."')
    assert hits and "tessarine" in hits[0].lower()


def test_ledgered_name_passes(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    ledger = [{"fact": "The guardian's true name is VORNMEK", "day": 2,
               "source_room": "antechamber", "source_action": "reveal"}]
    _wire_active_prep(monkeypatch, tmp_path, tmp_prep, ledger=ledger)
    hits = server._vp_check_dm_name_leaks('Tesslyn whispers: "VORNMEK is starving."')
    assert hits == []


def test_player_facing_name_never_blocked(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    _wire_active_prep(monkeypatch, tmp_path, tmp_prep)
    hits = server._vp_check_dm_name_leaks("The party steps into the Antechamber.")
    assert hits == []


def test_no_vault_or_no_prep_silent(monkeypatch, tmp_path, _reset_cache):
    # No vault AND no active prep -> silent. Point CAMPAIGN_DIR at an empty tmp
    # dir and clear the active prep so the non-vault path finds no prep (never
    # reads live campaign data).
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    hits = server._vp_check_dm_name_leaks('"VORNMEK is starving," it says.')
    assert hits == []


def test_fail_open_on_bad_prep(monkeypatch, tmp_path, _reset_cache):
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: {"revealed_ledger": []})
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", "DOES_NOT_EXIST.md")
    hits = server._vp_check_dm_name_leaks('"VORNMEK is starving," it says.')
    assert hits == []


def test_current_status_active_prep_fallback(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    """When GAME_STATE['active_prep_file'] is empty, fall back to CURRENT_STATUS.md's
    **Active Prep:** line (the same reader check_canon's prep block uses)."""
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: {"revealed_ledger": []})
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    status = tmp_path / "CURRENT_STATUS.md"
    status.write_text(f"**Active Prep:** {tmp_prep.name}\n", encoding="utf-8")
    hits = server._vp_check_dm_name_leaks('Tesslyn whispers: "VORNMEK is starving."')
    assert hits and "vornmek" in hits[0].lower()


def test_no_dm_only_block_no_candidates(monkeypatch, tmp_path, _reset_cache):
    prep = tmp_path / "NO_SECRETS_PREP.md"
    prep.write_text("## ROOM: hall\n**Name:** Grand Hall\n**Description:** A wide hall.\n",
                     encoding="utf-8")
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: {"revealed_ledger": []})
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", prep.name)
    hits = server._vp_check_dm_name_leaks("The party enters the Grand Hall.")
    assert hits == []


def test_header_style_dm_only_section_blocked(monkeypatch, tmp_path, _reset_cache):
    """Live preps mark DM sections with '## DM ONLY — <title>' HEADERS (no ⛔ pair) —
    the D134 leak came from exactly this shape. Names inside must still trip."""
    prep = tmp_path / "HEADER_STYLE_PREP.md"
    prep.write_text(
        "## ROOM: gallery\n**Name:** Root Gallery\n\n"
        "### Observables\nPale roots drink from a mineral pool.\n\n"
        "## DM ONLY — THE TRUTH\n"
        "The substrate intelligence calls itself THALVEK. It was bound by "
        "the archivist Merrowen, whose name the machines never speak.\n\n"
        "## ZONE B\nMore rooms here.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: {"revealed_ledger": []})
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", prep.name)
    nouns = server._dm_only_proper_nouns(prep)
    assert "thalvek" in nouns and "merrowen" in nouns
    # player-facing text elsewhere in the prep never becomes a tripwire
    assert "gallery" not in nouns and "zone" not in nouns
    hits = server._vp_check_dm_name_leaks('"THALVEK hungers," the machine intones.')
    assert hits and "thalvek" in hits[0].lower()


def _wire_social_prep(monkeypatch, tmp_path, tmp_prep, ledger=None, state=None):
    """A NON-vault turn (no active map) that still has an Active Prep carrying
    DM-only content — the social/settlement scene shape the original incident
    happened in. The reveal store is keyed by the prep's filename stem."""
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    if state is None and ledger is not None:
        state = {"revealed_ledger": ledger}
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: state)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", tmp_prep.name)


def test_social_scene_dm_only_name_blocked(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    """Active Prep, NO active map: an unledgered DM-only name still trips. The
    reveal store never existed (get_map_state -> None) so it reads empty =
    fail-SAFE (every DM-only name blocks)."""
    _wire_social_prep(monkeypatch, tmp_path, tmp_prep, state=None)
    hits = server._vp_check_dm_name_leaks('Tesslyn whispers: "VORNMEK is starving."')
    assert hits and "vornmek" in hits[0].lower()
    # the fix instruction points at the prep-scoped ledger name (the prep stem)
    assert tmp_prep.stem in hits[0]


def test_social_scene_ledgered_name_passes(monkeypatch, tmp_path, tmp_prep, _reset_cache):
    """Same social scene, but the name has been revealed via the prep-scoped
    ledger -> no longer blocked."""
    ledger = [{"fact": "The guardian's true name is VORNMEK", "day": 4,
               "source_room": "", "source_action": "reveal"}]
    _wire_social_prep(monkeypatch, tmp_path, tmp_prep, ledger=ledger)
    hits = server._vp_check_dm_name_leaks('Tesslyn whispers: "VORNMEK is starving."')
    assert hits == []


def test_prepless_social_scene_silent(monkeypatch, tmp_path, _reset_cache):
    """No active map AND no active prep: no candidates, no block, no crash."""
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: None)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", None)
    hits = server._vp_check_dm_name_leaks('"VORNMEK is starving," it says.')
    assert hits == []


def test_social_scene_no_dm_content_no_block(monkeypatch, tmp_path, _reset_cache):
    """Active Prep with NO DM-only content on a non-vault turn: the tripwire
    does not engage (no noise on secret-free social scenes)."""
    prep = tmp_path / "PLAIN_SOCIAL_PREP.md"
    prep.write_text("## OVERVIEW\n**Name:** Market Row\nA busy market of stalls.\n",
                    encoding="utf-8")
    monkeypatch.setattr(server, "_active_vault_turn", lambda: (None, None))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: None)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", prep.name)
    hits = server._vp_check_dm_name_leaks("The party wanders Market Row.")
    assert hits == []


def test_markdown_headers_and_stopwords_not_flagged(monkeypatch, tmp_path, _reset_cache):
    """Common capitalized markdown/English artifacts inside a DM-only block must
    NOT become tripwires - only invented proper nouns should."""
    prep = tmp_path / "HEADER_PREP.md"
    prep.write_text(
        "## ROOM: vault\n**Name:** Vault\n\n"
        "⛔ DM ONLY — THE TRUTH ⛔\n"
        "This Secret must Never be revealed. The Truth is hidden here. "
        "When the party learns this, update the Room notes.\n"
        "⛔ END DM ONLY ⛔\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_active_vault_turn", lambda: ("testvault", 1))
    monkeypatch.setattr(server.map_system, "get_map_state", lambda name: {"revealed_ledger": []})
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    monkeypatch.setitem(server.GAME_STATE, "active_prep_file", prep.name)
    nouns = server._dm_only_proper_nouns(prep)
    for common in ("this", "secret", "never", "truth", "when", "room", "notes",
                   "the", "dm", "only", "end"):
        assert common not in nouns, f"false-positive stopword leaked through: {common}"
