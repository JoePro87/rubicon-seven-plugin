"""Vertical-spine maps (a bore/shaft vault: rooms chained by up/down on ONE
floor) must auto-layout as a descending chain with drawn connectors — not
collapse into the disconnected fallback column (live bug: 14-room map rendered
as the entrance plus a bare one-column dump, no connectors)."""
from map_system import MapSystem


def _room(rid, name, connections, entrance=False):
    return {
        "id": rid, "floor": 1, "coords": [5, 5], "name": name,
        "connections": connections, "secret_connections": {},
        "discovery_state": "explored", "search_state": "unsearched",
        "is_secret": False, "is_entrance": entrance,
        "hazards": [], "npcs": [], "loot": [], "notes": "",
    }


def _bore_rooms():
    """entry —down→ mid —down→ sump, plus a lateral gallery east of mid."""
    return {
        "entry": _room("entry", "Bore Entry", {"down": "mid"}, entrance=True),
        "mid": _room("mid", "Mid Landing", {"up": "entry", "down": "sump", "east": "gallery"}),
        "gallery": _room("gallery", "Gallery", {"west": "mid"}),
        "sump": _room("sump", "Sump", {"up": "mid"}),
    }


def test_auto_layout_walks_vertical_spine():
    ms = MapSystem.__new__(MapSystem)
    placed = ms._auto_layout(_bore_rooms(), party_id=None)
    assert len(set(placed.values())) == 4
    # The chain descends: each down-step lands strictly lower than its parent,
    # and nothing was dumped in the disconnected fallback column (x >= start+2).
    assert placed["mid"][1] > placed["entry"][1]
    assert placed["sump"][1] > placed["mid"][1]
    assert placed["gallery"][0] > placed["mid"][0]
    xs = [c[0] for c in placed.values()]
    assert max(xs) - min(xs) <= 1, f"fallback column detected: {placed}"


def test_auto_layout_knows_full_diagonal_names():
    rooms = {
        "a": _room("a", "A", {"southeast": "b"}, entrance=True),
        "b": _room("b", "B", {"northwest": "a"}),
    }
    ms = MapSystem.__new__(MapSystem)
    placed = ms._auto_layout(rooms, party_id=None)
    ax, ay = placed["a"]
    bx, by = placed["b"]
    assert (bx, by) == (ax + 1, ay + 1)


def test_render_draws_connectors_from_actual_adjacency():
    ms = MapSystem.__new__(MapSystem)
    state = {"map_name": "bore", "party_location": "entry", "rooms": _bore_rooms()}
    out = ms._render_ascii(state, state["rooms"], 1, "Bore")
    # Every room renders (no truncated fallback), and vertical connector lines
    # exist between the stacked boxes.
    for name in ("Bore Entry", "Mid Landing", "Gallery", "Sump"):
        assert name in out
    assert "│" in out, "no vertical connector drawn for the down-chain"
    assert "─" in out, "no horizontal connector drawn for the east gallery"
