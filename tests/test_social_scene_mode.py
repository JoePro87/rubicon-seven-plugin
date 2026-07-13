"""Task 6 — the `social_site` scene token: spatial tracking WITHOUT combat cadence.

A diplomatic keyed site (map for position tracking) must NOT arm the combat trail
when the encounter die hits. In a `social_site` scene the die still ticks, but a hit
reads the open parley's TEXTURE table (color/tension) — or, absent a parley texture,
the prep's encounter row reframed as social texture — and NEVER pushes the
reaction→lookup→combat trail. Legacy vault states are untouched.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import social_system as ss
import map_system as ms
from map_system import MapSystem


# A social keyed site: SITE marker with scene=social_site, one ROOM (so init parses),
# an ENCOUNTERS table (the fallback source), and a PARLEY with a TEXTURE table.
SOCIAL_PREP = """<!-- SITE: key=socialvault scene=social_site aliases="Outer Reach" -->

## ROOM: entrance
**Floor:** 1
**Coords:** 5,5
**Name:** Council Ground
**Entrance:** true
**Connections:** e→hall

## ROOM: hall
**Floor:** 1
**Coords:** 6,5
**Name:** Long Hall
**Connections:** w→entrance

## ENCOUNTERS
| d6 | Encounter | Context |
|----|-----------|---------|
| 1 | 2 sand-krakens stalking the gallery | hungry |
| 2 | a lone scavenger | wary |

## PARLEY: socialvault_accord
**Stakes:** the clan wants survival.

### TIERS
1. contact — party states purpose

### TEXTURE (d8)
| 1 | Wall-weather shift builds on the ridge. |
| 2 | Cubs peer around a corner at the party. |
"""

# A legacy vault site: NO SITE marker (scene defaults to vault_exploration) with an
# encounter table — the combat cadence must remain intact.
VAULT_PREP = """## ROOM: entrance
**Floor:** 1
**Coords:** 5,5
**Name:** Entrance
**Entrance:** true
**Connections:** e→gallery

## ROOM: gallery
**Floor:** 1
**Coords:** 6,5
**Name:** Gallery
**Connections:** w→entrance

## ENCOUNTERS
| d6 | Encounter | Context |
|----|-----------|---------|
| 1 | 2 sand-krakens stalking the gallery | hungry |
"""


def _force_roll(monkeypatch, value):
    import random
    monkeypatch.setattr(random.SystemRandom, "randint", lambda self, a, b: value)


def _social_map(tmp_path, *, open_parley=True):
    # Enter via the real site-entry path (init_or_resume_map) so state carries the
    # parsed encounter table the fallback reads — exactly as production does.
    (tmp_path / "SOCIAL_PREP.md").write_text(SOCIAL_PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=1)
    if open_parley:
        parsed = ss.parse_parley_block(SOCIAL_PREP)
        ss.open_parley(tmp_path, "socialvault_accord", title="Accord",
                       day=1, site_key="socialvault", parsed=parsed)
    return m


def _vault_map(tmp_path):
    (tmp_path / "VAULT_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    m.init_or_resume_map("legacyvault", "VAULT_PREP.md", "vault", current_day=1)
    return m


# --- brief's first test, verbatim ---------------------------------------------
def test_exploration_scene_types_includes_social_site():
    src = open("server.py", encoding="utf-8").read()
    assert '"social_site"' in src.split("_EXPLORATION_SCENE_TYPES")[1][:200]


# --- the contract: TEXTURE, no combat trail -----------------------------------
def test_social_scene_encounter_has_no_combat_trail(tmp_path, monkeypatch):
    m = _social_map(tmp_path)
    state = m.get_map_state("socialvault")
    assert state["scene"] == "social_site"
    _force_roll(monkeypatch, 1)  # force the encounter die to hit
    out = m._auto_encounter_check(state)
    assert "TEXTURE" in out
    assert "combat(" not in out
    # rolled the parley's own texture table (roll 1 row)
    assert "Wall-weather shift" in out


def test_social_scene_hit_without_parley_falls_back_to_prep_row(tmp_path, monkeypatch):
    m = _social_map(tmp_path, open_parley=False)
    state = m.get_map_state("socialvault")
    _force_roll(monkeypatch, 1)
    out = m._auto_encounter_check(state)
    assert "TEXTURE" in out
    assert "combat(" not in out
    # fell back to the prep ENCOUNTERS row text, reframed as social texture
    assert "sand-krakens" in out
    # the combat next-call trail must be absent (the whole point of the mode)
    assert 'roll(action="reaction"' not in out
    assert 'lookup(action="creature"' not in out


def test_social_scene_omen_reframed_social(tmp_path, monkeypatch):
    m = _social_map(tmp_path)
    state = m.get_map_state("socialvault")
    _force_roll(monkeypatch, 2)  # omen
    out = m._auto_encounter_check(state)
    assert "TEXTURE" in out
    assert "OMEN" not in out
    assert "combat(" not in out


def test_social_scene_no_hit_unchanged(tmp_path, monkeypatch):
    m = _social_map(tmp_path)
    state = m.get_map_state("socialvault")
    _force_roll(monkeypatch, 5)  # nothing
    out = m._auto_encounter_check(state)
    assert out is None


# --- legacy behaviour: vault path + combat trail intact -----------------------
def test_legacy_state_without_scene_uses_combat_trail(tmp_path, monkeypatch):
    # A hand-built state with NO scene key must take the vault path unchanged.
    m = _vault_map(tmp_path)
    state = m.get_map_state("legacyvault")
    state.pop("scene", None)  # simulate a legacy save that predates the field
    _force_roll(monkeypatch, 1)
    out = m._auto_encounter_check(state)
    assert "combat(action=\"init\"" in out
    assert "roll(action=\"reaction\"" in out


def test_vault_marker_defaults_scene_to_vault_exploration(tmp_path):
    # No SITE marker → scene threads as the default, combat cadence preserved.
    m = _vault_map(tmp_path)
    state = m.get_map_state("legacyvault")
    assert state["scene"] == "vault_exploration"


def test_social_marker_threads_scene(tmp_path):
    m = _social_map(tmp_path, open_parley=False)
    state = m.get_map_state("socialvault")
    assert state["scene"] == "social_site"
