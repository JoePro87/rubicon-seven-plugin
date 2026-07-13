"""C30 — map encounter-die fire pushes the exact next calls (reaction → lookup → combat).

The hottest moment of vault play (an encounter firing mid-crawl) must hand the
fresh post-compaction DM the trail, mirroring geography_system's proven wording,
rather than describing the procedure in prose.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from map_system import MapSystem


def _m(tmp_path):
    return MapSystem(tmp_path)


def _assert_full_trail(text, query_substr=None):
    assert 'roll(action="reaction"' in text
    assert 'character="<highest-EGO PC>"' in text
    assert 'vs_ancestry="<if known>"' in text
    assert 'lookup(action="creature"' in text
    assert 'query=' in text
    assert 'combat(action="init"' in text
    if query_substr is not None:
        assert query_substr in text


def test_table_match_branch_pushes_calls(tmp_path):
    m = _m(tmp_path)
    state = {
        "encounters": {
            "type": "random_table",
            "dice_size": 6,
            "table_entries": [
                {"roll": 1, "encounter": "2 sand-krakens stalking the gallery",
                 "context": "hungry"},
            ],
        }
    }
    out = m._read_prep_encounter(state)
    # raw row text is passed as the fuzzy lookup query (no name-parsing)
    _assert_full_trail(out, query_substr="sand-krakens")


def test_no_table_improvise_branch_pushes_calls(tmp_path):
    m = _m(tmp_path)
    out = m._read_prep_encounter({})  # no "encounters" key
    assert "no table" in out.lower()
    _assert_full_trail(out)


def test_scripted_site_branch_pushes_calls(tmp_path):
    m = _m(tmp_path)
    state = {"encounters": {"type": "turn_based", "turn_triggers": []}}
    out = m._read_prep_encounter(state)
    assert "scripted" in out.lower()
    _assert_full_trail(out)
