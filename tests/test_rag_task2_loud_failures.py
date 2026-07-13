"""Task 2 (RAG hardening sprint) — loud failures in the check_canon core seam.

Covers:
  - Item 1: visible SEMANTIC RECALL OFFLINE marker when the vector lane is
    skipped/fails (embedding failure, collection unavailable) — fail-open, gate
    stays open.
  - Item 2/3: the ≤20-char skip is gone; short inputs run the semantic leg with
    a scene-grounded (location + present-name) enriched query.
  - Item 4: cultivated/hidden ride-along blocks (antagonist trigger, crossing,
    parley) carry the exact spoiler tokens hooks/spoiler_check.py watches for.

check_canon is invoked directly (server.check_canon), the same entry other
check_canon tests use. CAMPAIGN_DIR is redirected to a per-test tmp dir seeded
with a minimal lorebook.json (avoids the early-return) and a CURRENT_STATUS.md
with a known Location/Present.
"""

import json
import pytest

import server
import social_system as ss


class _MockCtx:
    """Minimal MCP Context stand-in for check_canon calls."""
    pass


def _seed_campaign(tmp_path, location="Ashfall Reliquary", present="Creenash, Vela"):
    (tmp_path / "lorebook.json").write_text(
        json.dumps({"entries": []}), encoding="utf-8"
    )
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS - DAY 50\n\n"
        "**Last Updated:** 2026-01-01 00:00\n\n"
        "---\n\n"
        "## SCENE STATE (check_canon reads this section)\n\n"
        "**Day:** 50\n"
        f"**Location:** {location}\n"
        f"**Present:** {present}\n",
        encoding="utf-8",
    )


@pytest.fixture
def canon_env(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    _seed_campaign(tmp_path)
    return tmp_path


# ----------------------------------------------------------------------
# Item 1 — visible degradation marker
# ----------------------------------------------------------------------

def test_marker_appears_when_embedder_raises(canon_env, monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(server, "get_embedding_cached", _boom)
    out = server.check_canon(
        _MockCtx(), user_input="I search the ancient library for old records", needs=[]
    )
    assert "SEMANTIC RECALL OFFLINE" in out
    assert "embedding unavailable" in out


def test_marker_appears_when_embedder_returns_none(canon_env, monkeypatch):
    # A None-return (no exception) is silent degradation too — it must still mark.
    monkeypatch.setattr(server, "get_embedding_cached", lambda q: None)
    out = server.check_canon(
        _MockCtx(), user_input="I search the ancient library for old records", needs=[]
    )
    assert "SEMANTIC RECALL OFFLINE" in out


def test_marker_appears_when_history_collection_missing(canon_env, monkeypatch):
    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)

    def _boom(*a, **k):
        raise RuntimeError("no collection")

    # Distillation lane down (caught internally) -> falls through to raw history,
    # whose collection accessor also raises -> clean, distinct reason.
    monkeypatch.setattr(server, "get_canon_distillations_collection", _boom)
    monkeypatch.setattr(server, "get_chroma_collection", _boom)
    out = server.check_canon(
        _MockCtx(), user_input="I search the ancient library for old records", needs=[]
    )
    assert "SEMANTIC RECALL OFFLINE" in out
    assert "history collection unavailable" in out


def test_no_marker_when_healthy(canon_env, monkeypatch):
    from unittest.mock import MagicMock

    monkeypatch.setattr(server, "get_embedding_cached", lambda q: [0.1] * 768)
    dist = MagicMock()
    dist.count.return_value = 0
    monkeypatch.setattr(server, "get_canon_distillations_collection", lambda: dist)
    monkeypatch.setattr(server, "get_chroma_collection", lambda name: MagicMock())
    monkeypatch.setattr(server, "_chroma_thresholds", lambda coll: (0.4, 0.6))
    monkeypatch.setattr(server, "_search_single_tier", lambda *a, **k: [])
    out = server.check_canon(
        _MockCtx(), user_input="I search the ancient library for old records", needs=[]
    )
    assert "SEMANTIC RECALL OFFLINE" not in out


def test_degradation_marker_keeps_gate_open(canon_env, monkeypatch):
    """The marker must NOT false-fail spoiler_check's validation (gate stays open)."""
    from hooks.spoiler_check import is_valid_check_canon_output

    def _boom(*a, **k):
        raise RuntimeError("ollama down")

    monkeypatch.setattr(server, "get_embedding_cached", _boom)
    out = server.check_canon(
        _MockCtx(), user_input="I search the ancient library for old records", needs=[]
    )
    assert "SEMANTIC RECALL OFFLINE" in out
    assert is_valid_check_canon_output(out) is True


# ----------------------------------------------------------------------
# Item 2/3 — short-message path runs the semantic leg with scene grounding
# ----------------------------------------------------------------------

def test_short_message_runs_semantic_leg_with_scene_grounding(canon_env, monkeypatch):
    captured = {}

    def _capture(q):
        captured["query"] = q
        return None  # short-circuit the downstream vector query

    monkeypatch.setattr(server, "get_embedding_cached", _capture)
    # 16 chars — the old `len(query) > 20` gate would have skipped this entirely.
    server.check_canon(_MockCtx(), user_input="attack the ghoul", needs=[])
    q = captured.get("query", "")
    assert "attack the ghoul" in q
    assert "Ashfall Reliquary" in q, f"location grounding missing: {q!r}"
    assert ("Creenash" in q or "Vela" in q), f"present-name grounding missing: {q!r}"


def test_long_message_not_scene_padded(canon_env, monkeypatch):
    captured = {}

    def _capture(q):
        captured["query"] = q
        return None

    monkeypatch.setattr(server, "get_embedding_cached", _capture)
    long_input = (
        "I carefully describe the entire ritual to the assembled elders, "
        "recalling every detail of the pact"
    )
    server.check_canon(_MockCtx(), user_input=long_input, needs=[])
    q = captured.get("query", "")
    assert long_input in q
    # >= 40 chars -> no scene padding appended (lorebook kw-terms may still append,
    # but the location name is not injected for a self-sufficient query).
    assert "Ashfall Reliquary" not in q


# ----------------------------------------------------------------------
# Item 4 — spoiler-marker consistency on cultivated ride-along blocks
# ----------------------------------------------------------------------

def _assert_spoiler_tokens(text):
    assert "SECRETS" in text
    assert ("do not reveal" in text.lower() or "dm only" in text.lower())


def test_antagonist_trigger_block_carries_spoiler_tokens(canon_env):
    server.antagonist(
        action="add_seed", threat_name="Kronophage",
        details="NE time-eater", day=122, trigger="standing stones",
    )
    blocks = server._antagonist_trigger_blocks("we head out to the standing stones")
    assert blocks and "Kronophage" in blocks[0]
    _assert_spoiler_tokens(blocks[0])


def test_crossing_block_carries_spoiler_tokens(monkeypatch):
    monkeypatch.setattr(server, "_crossing_facts", lambda t: [])
    monkeypatch.setattr(server, "_crossing_distillation_handle", lambda t: None)
    tangle = {
        "tag_type": "person",
        "display": "Vela",
        "seeds": [{"kind": "npc", "display": "Vela", "label": "seize the relay"}],
    }
    block = server._crossing_block(tangle)
    assert "Vela" in block  # content otherwise unchanged
    _assert_spoiler_tokens(block)


def test_parley_ride_along_block_carries_spoiler_tokens(tmp_path):
    from tests.test_social_parley_parser import SAMPLE

    parsed = ss.parse_parley_block(SAMPLE)
    ss.open_parley(tmp_path, parsed["slug"], title="Outer Reach Accord", day=131, parsed=parsed)
    blocks = ss.parley_blocks_for_npc(tmp_path, "She-Who-Keeps")
    assert blocks and "🤝" in blocks[0] and "gated reveals:" in blocks[0]
    _assert_spoiler_tokens(blocks[0])


def test_marker_triggers_spoiler_condition_and_keeps_gate_open():
    """The marker fires spoiler_check's warning condition AND keeps the gate open."""
    from hooks.spoiler_check import is_valid_check_canon_output

    scaffold = "**[AUTO-LIGHT]** (turn 1)\nLocation: X | Present: Y\n"
    out = scaffold + server._CULTIVATED_SECRET_MARKER
    assert is_valid_check_canon_output(out) is True  # structural scaffold -> gate opens
    _assert_spoiler_tokens(out)  # spoiler warning condition (spoiler_check.py:194) fires


def test_dead_query_enhancer_removed():
    """Item 3: the dead _enhance_query_with_context / _CHARACTER_TRAITS are gone."""
    assert not hasattr(server, "_enhance_query_with_context")
    assert not hasattr(server, "_CHARACTER_TRAITS")
