"""Tests for geography.position_context() — Phase 3 fog-aware position-relative overworld."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem

CAMPAIGN = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"


@pytest.fixture
def geo():
    return GeographySystem(CAMPAIGN)


def test_empty_for_unknown_center(geo):
    assert geo.position_context("nowhere_that_exists", radius=5) == ""


def test_lists_nearby_with_distances(geo):
    out = geo.position_context("ceruline", radius=8)
    assert "ceruline" in out.lower()           # header names the center
    assert "hex" in out.lower()                 # distances shown
    assert "-" in out                            # at least one bullet line


def test_respects_radius(geo):
    near = geo.position_context("ceruline", radius=2)
    far = geo.position_context("ceruline", radius=10)
    assert len(far.split("\n")) > len(near.split("\n"))
    assert "nassaks_tomb" in near  # 1 hex away -> in radius 2


def test_excludes_center_itself(geo):
    out = geo.position_context("ceruline", radius=8)
    # the center should appear only in the header, not as its own bullet line
    bullet_lines = [l for l in out.split("\n") if l.startswith("- ")]
    assert all("ceruline" not in l.lower() for l in bullet_lines)


def test_truncation_hint_when_more_than_eight(tmp_path):
    """Truncation hint fires when >8 non-fogged neighbors fall within radius.
    Isolated from live campaign data so it stays deterministic under Phase 3 fog."""
    g = GeographySystem(tmp_path)
    g.add_location("Center", 0, 0, "crossroads", "central_wastes", explored=True)
    # 10 known landmarks, all non-fogged, all within radius 10.
    for i in range(1, 11):
        g.add_location(f"Mark {i}", i, 0, "landmark", "central_wastes", known=True)
    out = g.position_context("Center", radius=10)
    assert "more within" in out  # >8 visible -> overflow hint


def test_singular_hex_for_adjacent(geo):
    out = geo.position_context("ceruline", radius=8)
    assert "1 hex" in out and "1 hexes" not in out  # nassaks_tomb is 1 hex
