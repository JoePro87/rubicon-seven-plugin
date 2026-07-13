"""Dice-honesty hardening Item 1 — social-site entry pushes the parley opener.

When the party enters (or resumes) a keyed site whose scene is `social_site` and no
open parley exists for that site_key, the map layer appends a pushed opener:
parley(action="open", slug="<site_key>_parley", site="<site_key>"). Idempotent
(silent once a matching parley is open), silent for vault scenes, silent+safe on
social_system import/read failure. Mirrors _read_social_texture's guard pattern.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import social_system as ss
from map_system import MapSystem

# Reuses the SOCIAL_PREP / VAULT_PREP fixtures' shape from test_social_scene_mode.py
# (SITE marker with scene=social_site, one PARLEY block with a TEXTURE table).
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

PUSH_MARKER = 'parley(action="open", slug="socialvault_parley", site="socialvault")'


def test_social_entry_push_appears_when_no_parley_open(tmp_path):
    (tmp_path / "SOCIAL_PREP.md").write_text(SOCIAL_PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    out = m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=1)
    assert PUSH_MARKER in out
    assert "open the negotiation" in out


def test_social_entry_push_absent_when_parley_already_open(tmp_path):
    (tmp_path / "SOCIAL_PREP.md").write_text(SOCIAL_PREP, encoding="utf-8")
    parsed = ss.parse_parley_block(SOCIAL_PREP)
    ss.open_parley(tmp_path, "socialvault_accord", title="Accord",
                    day=1, site_key="socialvault", parsed=parsed)
    m = MapSystem(tmp_path)
    out = m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=1)
    assert "parley(action=\"open\"" not in out


def test_social_entry_push_absent_on_resume_when_parley_already_open(tmp_path):
    # Idempotent across both entry paths: enter once (opens no parley, arms the
    # push), then open a parley and resume — the push must clear on resume too.
    (tmp_path / "SOCIAL_PREP.md").write_text(SOCIAL_PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=1)
    parsed = ss.parse_parley_block(SOCIAL_PREP)
    ss.open_parley(tmp_path, "socialvault_accord", title="Accord",
                    day=1, site_key="socialvault", parsed=parsed)
    out = m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=2)
    assert "▶ RESUMING" in out
    assert "parley(action=\"open\"" not in out


def test_social_entry_push_absent_for_vault_scene(tmp_path):
    (tmp_path / "VAULT_PREP.md").write_text(VAULT_PREP, encoding="utf-8")
    m = MapSystem(tmp_path)
    out = m.init_or_resume_map("legacyvault", "VAULT_PREP.md", "vault", current_day=1)
    assert "parley(action=\"open\"" not in out


def test_social_entry_push_import_failure_is_safe(tmp_path, monkeypatch):
    (tmp_path / "SOCIAL_PREP.md").write_text(SOCIAL_PREP, encoding="utf-8")
    monkeypatch.setitem(sys.modules, "social_system", None)  # forces ImportError
    m = MapSystem(tmp_path)
    out = m.init_or_resume_map("socialvault", "SOCIAL_PREP.md", "vault", current_day=1)
    assert "parley(action=\"open\"" not in out
    assert out  # no crash, still returns the normal arrival text
