"""Tests for distill_session() MCP tool."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))


@pytest.fixture
def tmp_cache(tmp_path):
    from hooks.distillation_cache import DistillationCache
    cache_path = tmp_path / ".canon_distillations.json"
    return DistillationCache(cache_path)


@pytest.fixture
def sample_entry():
    return {
        "topic_key": "amara_history",
        "learning": "Amara Vane is the Matriarch of House Vane.",
        "key_facts": ["Matriarch of House Vane", "Mira's biological mother"],
        "source_pointers": ["lorebook.json:amara"],
        "verified_against": {"lorebook_mtime": 1000, "npc_states_mtime": 1000},
        "created_turn": 0,
        "created_session": "backfill",
        "refined_turn": 0,
        "refined_count": 1,
        "ingested_at_session": "backfill",
    }


@pytest.fixture
def populated_cache(tmp_cache, sample_entry):
    tmp_cache.put(sample_entry)
    return tmp_cache


def test_analyze_finds_stale_entries(populated_cache, sample_entry):
    from hooks.distillation_cache import DistillationCache
    current_mtimes = {"lorebook_mtime": 2000, "npc_states_mtime": 1000}
    stale = [
        e for e in populated_cache.all_entries()
        if populated_cache.is_stale(e, current_mtimes)
    ]
    assert len(stale) == 1
    assert stale[0]["topic_key"] == "amara_history"


def test_analyze_finds_no_stale_when_current(populated_cache, sample_entry):
    current_mtimes = {"lorebook_mtime": 1000, "npc_states_mtime": 1000}
    stale = [
        e for e in populated_cache.all_entries()
        if populated_cache.is_stale(e, current_mtimes)
    ]
    assert len(stale) == 0


def test_analyze_detects_entity_names_in_text(populated_cache):
    session_text = "Amara joined the cipher team and worked with Brek."
    existing_keys = [e["topic_key"] for e in populated_cache.all_entries()]
    all_slugs = set()
    for key in existing_keys:
        parts = key.split("_")
        if parts:
            all_slugs.update(parts[:-1])
    text_lower = session_text.lower()
    matched = [s for s in all_slugs if len(s) >= 3 and s in text_lower]
    assert "amara" in matched


def test_distill_session_analyze_exists():
    from server import distill_session
    assert callable(distill_session)


def test_distill_session_analyze_returns_string():
    from server import distill_session
    result = distill_session(action="analyze", session_text="Nothing happened.")
    assert isinstance(result, str)


def test_write_rejects_entry_without_topic_key():
    from server import distill_session
    result = distill_session(
        action="write",
        entries=[{"learning": "some text", "key_facts": ["fact"], "source_pointers": []}],
        session_id="test-session",
    )
    assert "rejected" in result.lower() or "invalid" in result.lower() or "missing" in result.lower()


def test_write_rejects_entry_without_learning():
    from server import distill_session
    result = distill_session(
        action="write",
        entries=[{"topic_key": "test_history", "learning": "", "key_facts": ["fact"], "source_pointers": []}],
        session_id="test-session",
    )
    assert "rejected" in result.lower() or "empty" in result.lower() or "invalid" in result.lower()


def test_write_rejects_entry_without_key_facts():
    from server import distill_session
    result = distill_session(
        action="write",
        entries=[{"topic_key": "test_history", "learning": "some text", "key_facts": [], "source_pointers": []}],
        session_id="test-session",
    )
    assert "rejected" in result.lower() or "empty" in result.lower() or "invalid" in result.lower()


def test_write_creates_new_entry(tmp_path, monkeypatch):
    from hooks.distillation_cache import DistillationCache
    import server

    cache_path = tmp_path / ".canon_distillations.json"
    test_cache = DistillationCache(cache_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: False)

    result = server.distill_session(
        action="write",
        entries=[{
            "topic_key": "seam_history",
            "learning": "Seam is a Lithling scholar who arrived at Ceruline on Day 128.",
            "key_facts": ["Lithling scholar", "Arrived D128"],
            "source_pointers": ["lorebook.json:seam"],
        }],
        session_id="test-session",
    )
    assert "created" in result.lower()
    entry = test_cache.get("seam_history")
    assert entry is not None
    assert entry["learning"].startswith("Seam is a Lithling")
    assert entry["ingested_at_session"] is None


def test_write_updates_existing_entry(tmp_path, monkeypatch):
    from hooks.distillation_cache import DistillationCache
    import server

    cache_path = tmp_path / ".canon_distillations.json"
    test_cache = DistillationCache(cache_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)

    test_cache.put({
        "topic_key": "amara_history",
        "learning": "Amara is the Matriarch.",
        "key_facts": ["Matriarch of House Vane"],
        "source_pointers": ["lorebook.json:amara"],
        "verified_against": {"lorebook_mtime": 1000},
        "created_turn": 0,
        "created_session": "backfill",
        "refined_turn": 0,
        "refined_count": 1,
        "ingested_at_session": "backfill",
    })

    result = server.distill_session(
        action="write",
        entries=[{
            "topic_key": "amara_history",
            "learning": "Amara joined the cipher team on Day 128.",
            "key_facts": ["Matriarch of House Vane", "Joined cipher team D128"],
            "source_pointers": ["lorebook.json:amara"],
        }],
        session_id="test-session",
    )
    assert "updated" in result.lower()

    entry = test_cache.get("amara_history")
    assert entry["learning"] == "Amara joined the cipher team on Day 128."
    assert entry["refined_count"] == 2
    assert entry["ingested_at_session"] is None
    assert "Joined cipher team D128" in entry["key_facts"]
    assert "Matriarch of House Vane" in entry["key_facts"]


def test_write_with_ollama_offline_still_creates(tmp_path, monkeypatch):
    """When Ollama is offline, write should still create entries (skip overlap detection)."""
    from hooks.distillation_cache import DistillationCache
    import server

    cache_path = tmp_path / ".canon_distillations.json"
    test_cache = DistillationCache(cache_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: False)

    result = server.distill_session(
        action="write",
        entries=[{
            "topic_key": "new_npc_history",
            "learning": "A new NPC appeared in the session.",
            "key_facts": ["Appeared D129"],
            "source_pointers": ["lorebook.json:new_npc"],
        }],
        session_id="test-offline",
    )
    assert "created" in result.lower()
    assert "ollama" in result.lower()
    entry = test_cache.get("new_npc_history")
    assert entry is not None


def test_write_empty_entries_returns_nothing():
    """Write with empty entries list should return a clean message."""
    from server import distill_session
    result = distill_session(action="write", entries=[], session_id="test")
    assert "nothing" in result.lower() or "no entries" in result.lower()


def test_unknown_action_returns_error():
    """Unknown action should return an error message."""
    from server import distill_session
    result = distill_session(action="invalid_action")
    assert "error" in result.lower() or "unknown" in result.lower()


def test_analyze_then_write_pipeline(tmp_path, monkeypatch):
    """Full pipeline: analyze finds nothing stale, write creates new entry."""
    from hooks.distillation_cache import DistillationCache
    import server

    cache_path = tmp_path / ".canon_distillations.json"
    test_cache = DistillationCache(cache_path)
    monkeypatch.setattr(server, "_DISTILLATION_CACHE_PATH", cache_path)
    monkeypatch.setattr(server, "check_ollama_health", lambda force=False: False)
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)

    analyze_result = server.distill_session(
        action="analyze",
        session_text="Seam the Lithling arrived at Ceruline.",
    )
    assert "existing entries" in analyze_result.lower() or "no existing" in analyze_result.lower()

    write_result = server.distill_session(
        action="write",
        entries=[{
            "topic_key": "seam_history",
            "learning": "Seam is a Lithling scholar who arrived at Ceruline on Day 128.",
            "key_facts": ["Lithling scholar", "Arrived at Ceruline D128"],
            "source_pointers": ["lorebook.json:seam"],
        }],
        session_id="integration-test",
    )
    assert "created" in write_result.lower()

    entry = test_cache.get("seam_history")
    assert entry is not None
    assert entry["ingested_at_session"] is None
    assert entry["created_session"] == "integration-test"


def test_session_end_prompt_references_distill_session():
    """The session-end skill must wire up the distill_session tool.

    The original monolithic session-end-agent-prompt.md was split into a SKILL.md
    plus per-phase agent prompts (reconcile/verify/write), so we scan the whole
    skill directory rather than a single (now-removed) file. Repo-relative path so
    this resolves under the Windows venv Python too. The old 'Phase 9.25' label did
    not survive the refactor; the meaningful assertion — that the flow references
    distill_session — does.
    """
    skill_dir = (Path(__file__).resolve().parents[2]
                 / "rubicon-seven-campaign" / ".claude" / "skills" / "session-end")
    if not skill_dir.exists():
        pytest.skip("Session-end skill not found")
    combined = "\n".join(
        f.read_text(encoding="utf-8") for f in skill_dir.glob("*.md")
    )
    assert "distill_session" in combined
