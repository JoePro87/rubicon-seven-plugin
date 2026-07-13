"""Wave 3A — session-end crystallization ownership (engine side).

Covers the engine changes for:
- C15a: when a new-canon / lorebook(add) keyword ALREADY exists, the fresh
  context is skipped by the dedup — so the engine must PUSH the exact
  lorebook(action="update", ...) merge call AND surface the entry's CURRENT
  context, so the session-end agent merges rather than losing the fact.
- C15b: validate_campaign_state flags stale self-dating lorebook claims
  ('Day N' long past, 'has not yet', 'current members') for DM review only.
- C4 (engine leg): full_session_startup flags a faction record not touched in
  20+ in-game days as a reconcile candidate.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server  # noqa: E402  (isolates CAMPAIGN_DIR via conftest)
import session_tools  # noqa: E402
from session_tools import save_state  # noqa: E402


def _seed_lorebook(campaign_dir, entries):
    lb = {"meta": {"version": 1, "last_updated": "", "description": "x"},
          "entries": entries}
    (campaign_dir / "lorebook.json").write_text(json.dumps(lb), encoding="utf-8")


# ---------------------------------------------------------------------------
# C15a — the merge push on a skipped-duplicate keyword
# ---------------------------------------------------------------------------

def test_save_state_dup_keyword_pushes_merge_call_with_current_context(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_lorebook(campaign_dir, [
        {"keywords": ["vethka"], "category": "people", "status": "CANONICAL",
         "context": "Has not yet appeared publicly to the party.",
         "source": "session_day_74"},
    ])

    result = save_state(
        session_summary="test",
        day=132,
        narrative_log="short",
        new_canon=[
            {"keywords": "vethka", "category": "people", "status": "ESTABLISHED",
             "context": "On Day 131 Vethka hosted Creenash and opened the clan home."},
        ],
    )

    # The fresh fact was NOT silently dropped — the exact merge call is pushed.
    assert 'action="update"' in result and 'keyword="vethka"' in result, result
    assert 'field="context"' in result, result
    # new_value carries the discarded fresh context...
    assert "opened the clan home" in result, result
    # ...and the CURRENT context is surfaced so the agent merges, not overwrites.
    assert "Has not yet appeared publicly" in result, result
    # And the lorebook was NOT auto-overwritten (append-only still skipped it).
    lb = json.loads((campaign_dir / "lorebook.json").read_text(encoding="utf-8"))
    vethka = next(e for e in lb["entries"] if "vethka" in e["keywords"])
    assert vethka["context"] == "Has not yet appeared publicly to the party."


def test_prepare_diff_dup_keyword_shows_merge_push(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_lorebook(campaign_dir, [
        {"keywords": ["cacklemaw exiles"], "category": "factions",
         "status": "ESTABLISHED", "context": "A hostile splinter, kill-on-sight.",
         "source": "session_day_130"},
    ])
    diff = save_state(
        session_summary="test",
        day=132,
        narrative_log="short",
        new_canon=[
            {"keywords": "cacklemaw exiles", "category": "factions",
             "status": "ESTABLISHED", "context": "Now an allied trade partner."},
        ],
        preview=True,
    )
    assert 'action="update"' in diff and 'keyword="cacklemaw exiles"' in diff, diff
    assert "Now an allied trade partner" in diff, diff


def test_novel_keyword_no_merge_push(isolate_campaign_dir):
    """A genuinely new entry crystallizes normally — no merge nag."""
    campaign_dir = isolate_campaign_dir
    _seed_lorebook(campaign_dir, [])
    result = save_state(
        session_summary="test", day=132, narrative_log="short",
        new_canon=[{"keywords": "brand new fact", "category": "event",
                    "status": "ESTABLISHED", "context": "A thing happened."}],
    )
    assert "already exists" not in result, result


def test_lorebook_add_duplicate_pushes_merge_call(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_lorebook(campaign_dir, [
        {"keywords": ["vethka"], "category": "people", "status": "CANONICAL",
         "context": "Matriarch, not yet met.", "source": "s"},
    ])
    out = server.lorebook(
        action="add", keywords="vethka", category="people", status="ESTABLISHED",
        context="Vethka opened the clan home on Day 131.")
    assert "NOT added" in out, out
    assert 'action="update"' in out and 'keyword="vethka"' in out, out
    assert "Matriarch, not yet met" in out, out           # current context surfaced
    assert "opened the clan home" in out, out              # fresh context in new_value


# ---------------------------------------------------------------------------
# C15b — validate_campaign_state staleness sweep
# ---------------------------------------------------------------------------

def _seed_status(campaign_dir, day):
    (campaign_dir / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n", encoding="utf-8")


def test_validate_flags_stale_day_claim(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_status(campaign_dir, 132)
    _seed_lorebook(campaign_dir, [
        {"keywords": ["party"], "category": "people", "status": "CANONICAL",
         "context": "Current members (Day 74): Creenash, Vela.", "source": "s"},
    ])
    out = server.validate_campaign_state()
    assert "LOREBOOK STALE" in out, out
    assert "Day 74" in out, out


def test_validate_flags_stale_phrase(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_status(campaign_dir, 132)
    _seed_lorebook(campaign_dir, [
        {"keywords": ["vethka"], "category": "people", "status": "CANONICAL",
         "context": "Has not yet appeared publicly to the party.", "source": "s"},
    ])
    out = server.validate_campaign_state()
    assert "LOREBOOK STALE-PHRASE" in out, out
    assert "vethka" in out, out


def test_validate_no_false_positive_on_fresh_entry(isolate_campaign_dir):
    campaign_dir = isolate_campaign_dir
    _seed_status(campaign_dir, 132)
    _seed_lorebook(campaign_dir, [
        {"keywords": ["accord"], "category": "event", "status": "ESTABLISHED",
         "context": "The accord was sealed on Day 131 with open trade.", "source": "s"},
    ])
    out = server.validate_campaign_state()
    # Day 131 is within the 20-day window of Day 132 — not stale.
    assert "LOREBOOK STALE" not in out, out


# ---------------------------------------------------------------------------
# C4 (engine leg) — session-start stale-faction flag
# ---------------------------------------------------------------------------

def test_startup_flags_stale_faction(isolate_campaign_dir, monkeypatch):
    monkeypatch.setattr(session_tools, "_thread_current_day", lambda: 160)
    # A faction seeded on day 130 and never touched since.
    server.faction(action="add", name="Cacklemaw Clans", rep=-6,
                   reason="seed", day=130)
    out = server.full_session_startup()
    assert "FACTION STANDINGS" in out, out
    assert "not updated since day 130" in out, out
    assert 'faction(action="status", name="Cacklemaw Clans")' in out, out


def test_startup_no_stale_flag_for_recent_faction(isolate_campaign_dir, monkeypatch):
    monkeypatch.setattr(session_tools, "_thread_current_day", lambda: 135)
    server.faction(action="add", name="Mycomorph Colony", rep=6,
                   reason="seed", day=130)
    out = server.full_session_startup()
    assert "FACTION STANDINGS" in out, out
    assert "not updated since" not in out, out
