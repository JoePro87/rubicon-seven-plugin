"""C2 — session-end new_canon crystallization channel.

The facts-record contract now emits new_canon as DICTS ({keywords, category,
status, context}); the engine requires dicts and crystallizes them into
lorebook.json. A non-dict (legacy string) entry is a contract violation: it is
DROPPED, and that drop must be LOUD (distinct from a legitimate duplicate skip),
not silently buried — the historical bug was that every string entry vanished
with no signal.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402  (isolates CAMPAIGN_DIR via conftest)
from session_tools import save_state


def _seed_empty_lorebook(campaign_dir):
    lb = {"meta": {"version": 1, "last_updated": "", "description": "x"}, "entries": []}
    (campaign_dir / "lorebook.json").write_text(json.dumps(lb), encoding="utf-8")


def test_dict_entry_crystallizes_string_entry_rejected_loudly(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_empty_lorebook(campaign_dir)

    result = save_state(
        session_summary="test",
        day=51,
        narrative_log="short",  # < 50 chars → skip ChromaDB indexing (no ollama)
        new_canon=[
            {"keywords": "glasswright accord", "category": "event",
             "status": "ESTABLISHED", "context": "The accord was sealed on Day 51."},
            "The accord was sealed on Day 51.",  # legacy STRING → must be rejected
        ],
    )

    # The malformed string entry is surfaced loudly, not buried as a duplicate.
    assert "REJECTED" in result, f"non-dict new_canon reject was not loud: {result!r}"

    lb = json.loads((campaign_dir / "lorebook.json").read_text(encoding="utf-8"))
    all_keywords = {kw for e in lb["entries"] for kw in e.get("keywords", [])}
    # The dict entry crystallized...
    assert "glasswright accord" in all_keywords
    # ...and the string entry did NOT sneak in as an entry.
    assert len(lb["entries"]) == 1, f"unexpected entries: {lb['entries']}"


def test_preview_diff_flags_rejected_entry(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_empty_lorebook(campaign_dir)

    diff = save_state(
        session_summary="test",
        day=51,
        narrative_log="short",
        new_canon=["a bare string that should be rejected"],
        preview=True,
    )
    assert "REJECTED" in diff, f"prepare diff did not flag the malformed entry: {diff!r}"


def test_all_dicts_no_reject_noise(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_empty_lorebook(campaign_dir)

    result = save_state(
        session_summary="test",
        day=51,
        narrative_log="short",
        new_canon=[{"keywords": "outer reach clan", "category": "faction",
                    "status": "ESTABLISHED", "context": "Allied exile clan."}],
    )
    assert "REJECTED" not in result
    lb = json.loads((campaign_dir / "lorebook.json").read_text(encoding="utf-8"))
    assert any("outer reach clan" in e.get("keywords", []) for e in lb["entries"])
