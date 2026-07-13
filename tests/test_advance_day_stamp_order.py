"""Edge-case: advance_day commits the authoritative day-stamp AFTER its ticks.

advance_day used to write characters/_meta.json (the retry gate: every tick
computes elapsed = new_day - old_campaign_day) BEFORE running the per-character
ticks. A process death mid-tick then left the day advanced but the ticks
half-applied and unreplayable (a re-call sees elapsed 0). The fix defers the
_meta.json day-stamp to just before the return, so an interrupted run leaves
old_campaign_day intact and a re-call replays the day.

Invariant tested: a tick that raises (modelling a process kill via
KeyboardInterrupt, which the per-tick `except Exception` guards do NOT catch)
leaves the day unstamped; a clean run stamps exactly once and still reports the
sync line.
"""
import json

import server


def _seed(dirpath, day=100):
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {
        "version": 1, "campaign_day": day,
        "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                   "separated": [], "ledger": {"day": day, "consumed": {}}},
    }
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(json.dumps({
        "name": "Creenash", "hp": {"current": 20, "max": 20},
        "abilities": {"CON": {"current": 2, "base": 2}},
        "wound_table": "biological", "wounds": [], "conditions": [],
        "inventory": {"carried": []},
    }))
    (dirpath / "CURRENT_STATUS.md").write_text(
        f"# CURRENT STATUS - DAY {day}\n\n**Day:** {day}\n")


def _meta_day(dirpath):
    return json.loads(
        (dirpath / "characters" / "_meta.json").read_text()).get("campaign_day")


def test_clean_run_stamps_meta_once(isolate_campaign_dir):
    _seed(isolate_campaign_dir, day=100)
    out = server.advance_day(101, "a quiet night")
    assert _meta_day(isolate_campaign_dir) == 101       # stamped
    assert "characters/_meta.json" in out               # sync line preserved
    assert "Advanced to Day 101" in out


def test_tick_crash_leaves_day_unstamped(isolate_campaign_dir, monkeypatch):
    _seed(isolate_campaign_dir, day=100)

    def _boom(*a, **k):
        raise KeyboardInterrupt("process killed mid-tick")
    monkeypatch.setattr(server, "_antagonist_tick", _boom)

    import pytest
    with pytest.raises(KeyboardInterrupt):
        server.advance_day(101, "interrupted")

    # The authoritative retry gate must be untouched, so a re-call replays.
    assert _meta_day(isolate_campaign_dir) == 100
