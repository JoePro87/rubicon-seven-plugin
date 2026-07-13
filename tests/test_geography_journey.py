"""Tests for geography_system.journey() — ported from calculate_journey."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem

CAMPAIGN = Path(__file__).resolve().parents[2] / "rubicon-seven-campaign"


@pytest.fixture
def geo():
    return GeographySystem(CAMPAIGN)


def test_journey_returns_distance_and_modes(geo):
    out = geo.journey("ceruline", "delta_complex")
    assert "delta" in out.lower()
    assert "mile" in out.lower()
    assert "foot" in out.lower()


def test_journey_uses_canonical_verified_time(geo):
    out = geo.journey("ceruline", "delta_complex", mode="ornithopter")
    assert "22" in out or "minute" in out.lower()


def test_journey_unknown_location_errors(geo):
    out = geo.journey("ceruline", "nowhere_that_exists")
    assert "not found" in out.lower() or "error" in out.lower()


def test_journey_falls_back_to_hex_estimate(geo):
    out = geo.journey("ceruline", "salt_bones")
    assert "salt" in out.lower()
    assert "calculated" in out.lower()  # no canonical time -> speed calc path


def test_journey_single_mode_shows_only_that_mode(geo):
    out = geo.journey("ceruline", "delta_complex", mode="foot")
    assert "foot" in out.lower()
    assert "ornithopter" not in out.lower()


def test_journey_unknown_mode_reports_no_data(geo):
    out = geo.journey("ceruline", "delta_complex", mode="submarine")
    assert "no data" in out.lower() or "unknown transport" in out.lower()


def test_journey_shows_hazard_line(geo):
    out = geo.journey("ceruline", "salt_bones")  # this route has hazard_level "low"
    assert "hazard" in out.lower()
