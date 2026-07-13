"""Phase 3 fog-of-war knowledge model tests for geography_system."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from geography_system import GeographySystem


@pytest.fixture
def geo(tmp_path):
    """Isolated GeographySystem on an empty temp geography file (never touches prod)."""
    return GeographySystem(tmp_path)


# ---- Task 1: schema + helper ----

def test_add_location_defaults_known_false(geo):
    geo.add_location("Hidden Vault", 5, 5, "vault", "central_wastes")
    assert geo._load_geography()["locations"]["hidden_vault"]["known"] is False


def test_add_location_known_true_stored(geo):
    geo.add_location("Great Spire", 4, 4, "landmark", "central_wastes", known=True)
    assert geo._load_geography()["locations"]["great_spire"]["known"] is True


def test_query_locations_includes_known(geo):
    geo.add_location("Repute", 9, 9, "landmark", "central_wastes", known=True)
    rec = [r for r in geo.query_locations() if r["name"] == "repute"][0]
    assert rec["known"] is True


def test_knowledge_state_full_when_explored(geo):
    geo.add_location("Seen It", 1, 1, "vault", "central_wastes", explored=True)
    loc = geo._load_geography()["locations"]["seen_it"]
    assert geo._knowledge_state(loc) == "full"


def test_knowledge_state_known_when_known_not_explored(geo):
    geo.add_location("Heard Of It", 2, 2, "landmark", "central_wastes", known=True)
    loc = geo._load_geography()["locations"]["heard_of_it"]
    assert geo._knowledge_state(loc) == "known"


def test_knowledge_state_fogged_by_default(geo):
    geo.add_location("Secret Cave", 3, 3, "cave_system", "central_wastes")
    loc = geo._load_geography()["locations"]["secret_cave"]
    assert geo._knowledge_state(loc) == "fogged"


def test_update_location_accepts_known_field(geo):
    geo.add_location("Promotable", 6, 0, "landmark", "central_wastes")
    geo.update_location("Promotable", "known", True)
    assert geo._load_geography()["locations"]["promotable"]["known"] is True


# ---- Task 2: mark_explored implies known; mark_known ----

def test_mark_explored_sets_known(geo):
    geo.add_location("Now Visited", 6, 6, "vault", "central_wastes")
    geo.mark_explored("Now Visited")
    loc = geo._load_geography()["locations"]["now_visited"]
    assert loc["explored"] is True
    assert loc["known"] is True


def test_mark_known_promotes_fogged(geo):
    geo.add_location("Rumored Place", 7, 7, "landmark", "central_wastes")
    out = geo.mark_known("Rumored Place")
    assert geo._load_geography()["locations"]["rumored_place"]["known"] is True
    assert "known" in out.lower()


def test_mark_known_idempotent(geo):
    geo.add_location("Already Known", 8, 8, "landmark", "central_wastes", known=True)
    out = geo.mark_known("Already Known")
    assert "already" in out.lower()


def test_mark_known_missing_location(geo):
    out = geo.mark_known("Nowhere At All")
    assert "not found" in out.lower()


# ---- Task 3: position_context fog gate ----

@pytest.fixture
def fog_world(tmp_path):
    g = GeographySystem(tmp_path)
    g.add_location("Hub", 0, 0, "crossroads", "central_wastes", explored=True)
    g.add_location("Big Wall", 2, 0, "landmark", "central_wastes", known=True)
    g.add_location("Seen Vault", 0, 2, "vault", "central_wastes", explored=True)
    g.add_location("Hidden Camp", 1, 1, "camp", "central_wastes")  # fogged
    return g


def test_position_context_shows_known_and_explored(fog_world):
    out = fog_world.position_context("Hub", radius=6)
    assert "big_wall" in out.lower()     # known -> shown
    assert "seen_vault" in out.lower()   # explored -> shown


def test_position_context_drops_fogged(fog_world):
    out = fog_world.position_context("Hub", radius=6)
    assert "hidden_camp" not in out.lower()   # fogged -> silent


def test_position_context_tags_known_by_repute(fog_world):
    out = fog_world.position_context("Hub", radius=6)
    repute_line = [ln for ln in out.splitlines() if "big_wall" in ln.lower()][0]
    assert "repute" in repute_line.lower()


# ---- Task 4: scan injection fog tiers ----

def test_location_context_carries_knowledge(geo):
    geo.add_location("Tagged", 1, 0, "vault", "central_wastes", explored=True)
    ctx = geo.get_location_context("tagged")
    assert ctx["knowledge"] == "full"


def test_format_injection_full_shows_coords(geo):
    geo.add_location("Seen Place", 1, 0, "vault", "central_wastes",
                     explored=True, description="A walked vault.")
    out = geo.format_context_injection(geo.scan_for_locations("we return to seen place"))
    assert "EXPLORED" in out
    assert "(1, 0)" in out
    assert "walked vault" in out.lower()


def test_format_injection_known_shows_macro(geo):
    geo.add_location("Tall Wall", 3, 0, "landmark", "central_wastes",
                     known=True, description="A long wall.")
    out = geo.format_context_injection(geo.scan_for_locations("where is tall wall"))
    assert "reputation" in out.lower()
    assert "(3, 0)" in out          # macro coords allowed
    assert "long wall" in out.lower()  # description shown at known tier


def test_format_injection_fogged_withholds_specifics(geo):
    geo.add_location("Mystery Vault", 2, 0, "vault", "central_wastes",
                     description="Hidden interior detail.")
    out = geo.format_context_injection(geo.scan_for_locations("rumors of mystery vault"))
    assert "FOGGED" in out
    assert "first-hand" in out.lower()
    assert "(2, 0)" not in out                 # coords withheld
    assert "hidden interior" not in out.lower()  # description withheld


def test_format_injection_fallback_respects_known_without_knowledge_key():
    """A raw dict lacking the 'knowledge' key but with known=True must tier as known, not fogged."""
    from geography_system import GeographySystem
    # Build a minimal context dict by hand (simulating a non-get_location_context caller).
    loc = {"name": "Repute Only", "type": "landmark", "region": "Central Wastes",
           "coordinates": "(5, 5)", "explored": False, "known": True,
           "description": "Known by repute."}
    # Use any GeographySystem instance for the method (it reads only the passed dict here).
    import tempfile
    from pathlib import Path
    g = GeographySystem(Path(tempfile.mkdtemp()))
    out = g.format_context_injection([loc])
    assert "FOGGED" not in out          # must NOT be mis-tiered as fogged
    assert "reputation" in out.lower()  # tiered as known
    assert "(5, 5)" in out


# ---- Task 5: geography() tool wiring ----

def _capture_geography_tool(campaign_dir):
    """Register the geography tool against a fake MCP and return the raw function."""
    from geography_system import register_geography_tools
    captured = {}

    class _FakeMCP:
        def tool(self, *args, **kwargs):
            def deco(fn):
                captured[fn.__name__] = fn
                return fn
            return deco

    register_geography_tools(_FakeMCP(), campaign_dir)
    return captured["geography"]


def test_tool_add_location_with_known(tmp_path):
    geography = _capture_geography_tool(tmp_path)
    out = geography(action="add_location", name="Repute Peak", x=4, y=1,
                    location_type="landmark", region="central_wastes", known=True)
    assert "Repute Peak" in out
    g = GeographySystem(tmp_path)
    assert g._load_geography()["locations"]["repute_peak"]["known"] is True


def test_tool_mark_known_action(tmp_path):
    geography = _capture_geography_tool(tmp_path)
    geography(action="add_location", name="Distant Spire", x=5, y=1,
              location_type="landmark", region="central_wastes")
    out = geography(action="mark_known", name="Distant Spire")
    assert "known" in out.lower()
    g = GeographySystem(tmp_path)
    assert g._load_geography()["locations"]["distant_spire"]["known"] is True


def test_tool_update_known_field_coerces_bool(tmp_path):
    geography = _capture_geography_tool(tmp_path)
    geography(action="add_location", name="Toggle Me", x=6, y=1,
              location_type="landmark", region="central_wastes")
    geography(action="update_location", name="Toggle Me", field="known", value="true")
    g = GeographySystem(tmp_path)
    assert g._load_geography()["locations"]["toggle_me"]["known"] is True


# ---- Task 7: reflex travel-injection inherits the fog ----

def test_reflex_travel_injection_drops_fogged(tmp_path):
    """Mirrors server._inject_spatial_state travel path: get_party_location + position_context."""
    g = GeographySystem(tmp_path)
    g.add_location("Camp Base", 0, 0, "crossroads", "central_wastes", explored=True)
    g.set_party_location("Camp Base")
    g.add_location("Far Wall", 3, 0, "landmark", "central_wastes", known=True)   # macro
    g.add_location("Secret Hole", 1, 0, "cave_system", "central_wastes")          # fogged

    party = g.get_party_location()
    injection = g.position_context(party)

    assert "far_wall" in injection.lower()        # macro chart surfaces
    assert "secret_hole" not in injection.lower()  # fogged stays silent


# ---- Phase 3 hardening: invariant + coverage pins ----

def test_update_explored_true_implies_known(geo):
    """update_location('explored', True) must also set known (explored implies known)."""
    geo.add_location("Edge Case", 4, 4, "vault", "central_wastes")  # fogged
    geo.update_location("Edge Case", "explored", True)
    loc = geo._load_geography()["locations"]["edge_case"]
    assert loc["explored"] is True
    assert loc["known"] is True


def test_update_unrelated_field_preserves_known(geo):
    """Editing an unrelated field must not drop the known flag."""
    geo.add_location("Keep Known", 5, 4, "landmark", "central_wastes", known=True)
    geo.update_location("Keep Known", "description", "new blurb")
    assert geo._load_geography()["locations"]["keep_known"]["known"] is True


def test_position_context_explored_not_tagged_by_repute(geo):
    """An explored location must NOT carry the '(by repute)' marker (that's known-only)."""
    geo.add_location("Center Hub", 0, 0, "crossroads", "central_wastes", explored=True)
    geo.add_location("Walked Vault", 1, 0, "vault", "central_wastes", explored=True)
    out = geo.position_context("Center Hub", radius=6)
    vault_line = [ln for ln in out.splitlines() if "walked_vault" in ln.lower()][0]
    assert "by repute" not in vault_line.lower()
