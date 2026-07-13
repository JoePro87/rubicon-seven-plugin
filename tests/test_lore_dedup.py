"""Lore/bestiary dedup guards (2026-06-07, deferred ruling #6, conservative).

Two cleanups, both verified against zero code-consumers first:
  - lore_additions.json: the `rule_refs` field is dead (the live "rules in play"
    feature reads rule_refs from lorebook.json, a different file) -> removed.
    The 6 lore entries that purely restated a bestiary stat block were deleted;
    the 2 with unique narrative (indigo-servitor, weekling) were KEPT.
  - bestiary.json: the `lore_refs` field is dead campaign metadata (163/170 were
    dangling, nothing reads it) -> zeroed via _rebuild_bestiary.py.

Reads the real campaign files (independent of conftest's temp-dir redirect).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _rulebook_dir():
    # Engine-bundled rules-data (relocated from the campaign dir 2026-06-17).
    rb = Path(__file__).resolve().parents[1] / "data" / "rules" / "rulebook"
    if not (rb / "bestiary.json").exists():
        pytest.skip("engine rulebook not found")
    return rb


def _lore():
    return json.loads((_rulebook_dir() / "lore_additions.json").read_text(encoding="utf-8"))["entries"]


def _bestiary():
    return json.loads((_rulebook_dir() / "bestiary.json").read_text(encoding="utf-8"))["entries"]


def test_lore_additions_has_no_dead_rule_refs():
    assert all("rule_refs" not in e for e in _lore())


def test_six_pure_duplicate_lore_entries_removed():
    ids = {e["id"] for e in _lore()}
    for gone in ("lore-alzabo", "lore-hegemony-centurion", "lore-hegemony-ordinator",
                 "lore-mycomorph", "lore-neobloom", "lore-quicksilver-exterminator"):
        assert gone not in ids, f"{gone} should have been deleted"


def test_unique_narrative_lore_entries_kept():
    ids = {e["id"] for e in _lore()}
    # these restated a stat block BUT carried unique narrative -> conservative keep
    assert "lore-indigo-servitor" in ids
    assert "lore-weekling" in ids


def test_bestiary_lore_refs_all_empty():
    best = _bestiary()
    assert len(best) == 229
    assert all(not e.get("lore_refs") for e in best), "dead lore_refs must be zeroed"
