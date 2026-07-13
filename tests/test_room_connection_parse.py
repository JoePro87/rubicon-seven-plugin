"""Regression: **Connections:** bold-label close must not leak into the first direction key."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from map_system import MapSystem


@pytest.fixture
def ms(tmp_path):
    return MapSystem(tmp_path)


def test_first_connection_direction_is_clean(ms):
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Connections:** n→b, e→c\n")
    assert rooms["a"]["connections"] == {"n": "b", "e": "c"}


def test_first_secret_id_is_clean(ms):
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Secrets:** alcove→hidden (search), niche→cache (INT)\n")
    secrets = rooms["a"]["secret_connections"]
    assert "alcove" in secrets
    assert not any(k.startswith("*") or k != k.strip() for k in secrets)


def test_hazards_npcs_loot_clean(ms):
    block = ("## ROOM: a\n\n"
             "**Hazards:** gas trap, pit\n"
             "**NPCs:** warden, scribe\n"
             "**Loot:** coin, blade\n")
    r = ms._parse_rooms_from_prep(block)["a"]
    assert r["hazards"][0] == "gas trap"
    assert r["npcs"][0] == "warden"
    assert r["loot"][0] == "coin"


def test_arrow_variant_also_clean(ms):
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Connections:** up->b\n")
    assert rooms["a"]["connections"] == {"up": "b"}
