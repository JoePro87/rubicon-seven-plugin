"""C25 — prose-gate hot path: concurrent semantic judges + distillation parse cache.

Two independent perf fixes on the every-clean-turn path:
  (a) the haiku voice-judge and the fact-judge run concurrently, not back-to-back;
  (b) DistillationCache._read_raw reuses a module-level parse while the file's
      mtime is unchanged, so the 2.3MB JSON isn't re-parsed 2-3x per turn.
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import hooks.distillation_cache as dc


# ---------------------------------------------------------------------------
# (b) distillation parse cache
# ---------------------------------------------------------------------------

def test_read_raw_cache_hit_returns_same_object(tmp_path):
    dc._PARSE_CACHE.clear()
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema_version": 1, "distillations": {"k": {"topic_key": "k"}}}))
    cache = dc.DistillationCache(p)
    r1 = cache._read_raw()
    r2 = cache._read_raw()
    assert r1 is r2, "unchanged file should serve the cached parse, not re-parse"


def test_read_raw_reparses_on_mtime_change(tmp_path):
    dc._PARSE_CACHE.clear()
    p = tmp_path / "c.json"
    p.write_text(json.dumps({"schema_version": 1, "distillations": {"k": {"topic_key": "k"}}}))
    cache = dc.DistillationCache(p)
    r1 = cache._read_raw()
    # Bump mtime (and content) → cache must invalidate.
    st = p.stat()
    p.write_text(json.dumps({"schema_version": 1, "distillations": {"k2": {"topic_key": "k2"}}}))
    os.utime(p, (st.st_atime, st.st_mtime + 5))
    r3 = cache._read_raw()
    assert r3 is not r1
    assert "k2" in r3["distillations"]


def test_put_keeps_cache_coherent(tmp_path):
    dc._PARSE_CACHE.clear()
    p = tmp_path / "c.json"
    cache = dc.DistillationCache(p)
    cache.put({"topic_key": "a", "learning": "x"})
    assert cache.get("a")["learning"] == "x"
    # A cache-hit read after the write still reflects the written value.
    assert cache.get("a")["learning"] == "x"


# ---------------------------------------------------------------------------
# (a) concurrent semantic judges
# ---------------------------------------------------------------------------

_JUDGE_SLEEP = 0.3


def _patch_deterministic_clean(monkeypatch, server, names):
    """Make every deterministic prose check pass so we reach the judge branch."""
    monkeypatch.setattr(server, "_load_prose_patterns", lambda: ([], [], []))
    for fn in (
        "_vp_check_fabrication_bans", "_vp_check_npc_mentions", "_vp_check_backstory",
        "_vp_check_dialogue_claims", "_vp_check_petnames", "_vp_check_tripwires",
        "_vp_check_narration_claims", "_vp_check_combat_mechanics",
    ):
        monkeypatch.setattr(server, fn, lambda *a, **k: [])
    monkeypatch.setattr(server, "_vp_check_prep_progress", lambda *a, **k: "")
    monkeypatch.setattr(server, "_vp_known_canon_names", lambda: names)
    monkeypatch.setattr(server, "_vp_cache_facts_blob", lambda *a, **k: "blob")


def test_judges_run_concurrently_and_both_called(monkeypatch):
    import server
    calls = []

    def slow_haiku(text):
        calls.append("haiku")
        time.sleep(_JUDGE_SLEEP)
        return []

    def slow_fact(text, blob):
        calls.append("fact")
        time.sleep(_JUDGE_SLEEP)
        return []

    _patch_deterministic_clean(monkeypatch, server, {"amara"})
    monkeypatch.setattr(server, "_vp_call_haiku_judge", slow_haiku)
    monkeypatch.setattr(server, "_vp_call_fact_judge", slow_fact)

    start = time.time()
    out = server._validate_prose_impl("Amara crossed the courtyard at dusk.")
    elapsed = time.time() - start

    assert "haiku" in calls and "fact" in calls, "both judges must run"
    assert elapsed < 2 * _JUDGE_SLEEP, (
        f"judges ran sequentially ({elapsed:.2f}s ~= 2x{_JUDGE_SLEEP}s); expected concurrent"
    )
    assert out.startswith("CLEAN")


def test_fact_judge_skipped_when_no_canon_name(monkeypatch):
    import server
    calls = []
    monkeypatch.setattr(server, "_vp_call_haiku_judge", lambda t: calls.append("haiku") or [])
    monkeypatch.setattr(server, "_vp_call_fact_judge", lambda t, b: calls.append("fact") or [])
    _patch_deterministic_clean(monkeypatch, server, {"amara"})

    # Draft names no known canon → fact-judge precheck fails → fact-judge skipped.
    server._validate_prose_impl("The wind moved over empty dunes.")
    assert "haiku" in calls
    assert "fact" not in calls
