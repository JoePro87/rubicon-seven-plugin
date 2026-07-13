"""Phase 4: server prep parser canonicalized to h2 '## ROOM:' — 1:1 with map_system."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import server
from map_system import MapSystem


CANONICAL_PREP = """# TESTVAULT - PREP

**Type:** vault

## ROOM: entry_hall

**Name:** Entry Hall
**Entrance:** true
**Connections:** n→inner_sanctum

Observable text.

## ROOM: inner_sanctum

**Name:** Inner Sanctum
**Connections:** s→entry_hall

More text.
"""


def test_server_parser_reads_h2_rooms():
    # _load_prep_file joins with server.CAMPAIGN_DIR, so write there
    prep_filename = "TESTVAULT.md"
    prep = server.CAMPAIGN_DIR / prep_filename
    prep.write_text(CANONICAL_PREP, encoding="utf-8")
    data, error = server._load_prep_file(prep_filename)
    assert not error
    rooms = data.get("rooms", {})
    assert "entry_hall" in rooms
    assert "inner_sanctum" in rooms


def test_server_and_map_system_agree_on_room_count():
    # Write prep under CAMPAIGN_DIR so _load_prep_file can find it
    prep_filename = "TESTVAULT.md"
    prep = server.CAMPAIGN_DIR / prep_filename
    prep.write_text(CANONICAL_PREP, encoding="utf-8")
    server_rooms = set(server._load_prep_file(prep_filename)[0].get("rooms", {}))
    ms = MapSystem(server.CAMPAIGN_DIR)
    map_rooms = set(ms._parse_rooms_from_prep(CANONICAL_PREP))
    assert server_rooms == map_rooms, (server_rooms, map_rooms)
