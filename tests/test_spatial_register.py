"""Session-scoped spatial assertion register (spec §F.4, 2026-07-24).

ADVISORY only, two relations only. General contradiction detection is declared
infeasible in spec §D.1 and is deliberately NOT built.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hooks.spatial_register import normalize_assertion, record  # noqa: E402


def _rec(tmp_path, session, subj, rel, obj, value, turn=1):
    key, norm = normalize_assertion(subj, rel, obj, value)
    return record(tmp_path, session, key, norm, "excerpt", turn=turn)


def test_same_key_same_value_twice_is_silent(tmp_path):
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 1) == []
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 2) == []


def test_opposite_direction_same_session_contradicts(tmp_path):
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 1) == []
    out = _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "west", 7)
    assert len(out) == 1
    assert "SELF-CONTRADICTION" in out[0]
    assert "turn 1" in out[0]


def test_pair_order_flip_with_flipped_direction_agrees(tmp_path):
    """`A west-of B` then `B east-of A` are the SAME claim, not a contradiction."""
    assert _rec(tmp_path, "s1", "ceruline", "bearing", "thyricost", "west", 1) == []
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 2) == []


def test_surface_forms_normalize(tmp_path):
    assert _rec(tmp_path, "s1", "ceruline", "bearing", "thyricost", "due west", 1) == []
    assert _rec(tmp_path, "s1", "ceruline", "bearing", "thyricost", "western", 2) == []


def test_distance_within_tolerance_agrees(tmp_path):
    assert _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "280 miles", 1) == []
    assert _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "275 miles", 2) == []


def test_distance_outside_tolerance_contradicts(tmp_path):
    assert _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "280 miles", 1) == []
    out = _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "40 miles", 5)
    assert len(out) == 1 and "SELF-CONTRADICTION" in out[0]


def test_session_change_wipes_the_register(tmp_path):
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 1) == []
    # New session: canon may legitimately have changed between sessions.
    assert _rec(tmp_path, "s2", "thyricost", "bearing", "ceruline", "west", 1) == []


def test_scene_anchor_key_is_not_reordered(tmp_path):
    key, _ = normalize_assertion("thyricost", "bearing", "@scene", "west")
    assert key == "thyricost|bearing|@scene"


def test_corrupt_register_file_fails_open(tmp_path):
    (tmp_path / ".spatial_register.json").write_text("{not json", encoding="utf-8")
    assert _rec(tmp_path, "s1", "thyricost", "bearing", "ceruline", "east", 1) == []


def test_unwritable_dir_fails_open():
    assert _rec(Path("/nonexistent/dir/xyz"), "s1",
                "thyricost", "bearing", "ceruline", "east", 1) == []


def test_unparseable_distance_never_contradicts(tmp_path):
    assert _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "a fair way", 1) == []
    assert _rec(tmp_path, "s1", "ceruline", "distance", "thyricost", "280 miles", 2) == []
