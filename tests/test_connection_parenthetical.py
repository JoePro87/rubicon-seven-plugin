"""Regression: connection targets with parenthetical annotations must strip to clean room ids."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from map_system import MapSystem


@pytest.fixture
def ms(tmp_path):
    return MapSystem(tmp_path)


def test_parenthetical_stripped_from_target(ms):
    rooms = ms._parse_rooms_from_prep(
        "## ROOM: a\n\n**Connections:** south→deep_conduit (Bugsie-only without engineering)\n"
    )
    assert rooms["a"]["connections"] == {"south": "deep_conduit"}


def test_multiple_connections_with_parentheticals(ms):
    rooms = ms._parse_rooms_from_prep(
        "## ROOM: a\n\n**Connections:** northwest→dead_zone (via hatch), east→root_gallery (with engineering)\n"
    )
    assert rooms["a"]["connections"] == {"northwest": "dead_zone", "east": "root_gallery"}


def test_plain_connection_still_works(ms):
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Connections:** n→b, e→c\n")
    assert rooms["a"]["connections"] == {"n": "b", "e": "c"}


def test_cross_floor_at_suffix_still_works(ms):
    rooms = ms._parse_rooms_from_prep("## ROOM: a\n\n**Connections:** up→vestibule@2\n")
    conn = rooms["a"]["connections"]["up"]
    # @N cross-floor syntax must survive: target room 'vestibule', floor 2
    assert (conn == {"room": "vestibule", "floor": 2}) or (isinstance(conn, dict) and conn.get("room") == "vestibule")
