"""C20: cybernetic install/remove stat-bonus symmetry (no silent stat corruption).

Install caps a stat bonus at +10, but the buggy remove subtracted the FULL
requested bonus — so a round-trip at a high stat permanently lost points. The
fix stores the EFFECTIVE applied delta at install (stat_bonus_applied) and
reverses THAT on removal, with a fallback to the requested stat_bonus for legacy
records already on sheets. CON changes recompute slot capacity (10 + CON), and
removal runs the death check so a below--10 stat surfaces.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _write_char(char_id, char):
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta = chars_dir / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({"last_updated": "2026-01-01", "campaign_day": 50}))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _reload(name):
    data, _ = server._load_characters()
    _, char = server._find_character(data, name)
    return char


def _bare(name="Cyborg", **abilities):
    ab = {k.upper(): {"current": v, "base": v} for k, v in abilities.items()}
    return {"name": name, "species": "true-kin", "abilities": ab}


# --- round-trip at a capped stat preserves the original score ---------------

def test_roundtrip_at_capped_stat_preserves_score():
    """CON +9, install +3 (caps to +10), then remove: must return to +9, not +7."""
    _write_char("cyborg", _bare(CON=9))
    server._cybernetic_install("Cyborg", "Iron Lung", "CON",
                               "+3 CON, capped", stat_bonus='{"CON": 3}')
    assert _reload("Cyborg")["abilities"]["CON"]["current"] == 10  # capped

    server._cybernetic_remove("Cyborg", "Iron Lung")
    assert _reload("Cyborg")["abilities"]["CON"]["current"] == 9   # back to origin


def test_uncapped_roundtrip_unchanged():
    """A non-capped install/remove is symmetric exactly as before (regression)."""
    _write_char("cyborg", _bare(DEX=1))
    server._cybernetic_install("Cyborg", "Hyper Tendons", "DEX",
                               "+2 DEX", stat_bonus='{"DEX": 2}')
    assert _reload("Cyborg")["abilities"]["DEX"]["current"] == 3
    server._cybernetic_remove("Cyborg", "Hyper Tendons")
    assert _reload("Cyborg")["abilities"]["DEX"]["current"] == 1


# --- legacy-record fallback (implant predates stat_bonus_applied) -----------

def test_legacy_record_falls_back_to_stat_bonus():
    """A sheet whose implant record has only stat_bonus (no stat_bonus_applied)
    still reverses via the stored stat_bonus AND surfaces the legacy notice."""
    c = _bare(STR=2)
    # legacy implant already applied +2 (STR 0 -> 2), no stat_bonus_applied key
    c["augmentations"] = {"STR": {"name": "Old Servo", "stat_bonus": {"STR": 2}}}
    _write_char("cyborg", c)
    out = server._cybernetic_remove("Cyborg", "Old Servo")
    assert _reload("Cyborg")["abilities"]["STR"]["current"] == 0
    assert "legacy implant record" in out


def test_post_fix_record_has_no_legacy_notice():
    """A record minted by the fixed install (carries stat_bonus_applied) removes
    without the legacy notice."""
    _write_char("cyborg", _bare(DEX=1))
    server._cybernetic_install("Cyborg", "Hyper Tendons", "DEX",
                               "+2 DEX", stat_bonus='{"DEX": 2}')
    out = server._cybernetic_remove("Cyborg", "Hyper Tendons")
    assert "legacy implant record" not in out


# --- CON install/remove recompute slot capacity -----------------------------

def test_con_install_recomputes_slots():
    _write_char("cyborg", _bare(CON=2))
    server._cybernetic_install("Cyborg", "Rib Cage", "CON",
                               "+2 CON", stat_bonus='{"CON": 2}')
    char = _reload("Cyborg")
    assert char["abilities"]["CON"]["current"] == 4
    assert char["slot_capacity_total"] == 14  # 10 + CON 4


def test_con_remove_recomputes_slots():
    _write_char("cyborg", _bare(CON=2))
    server._cybernetic_install("Cyborg", "Rib Cage", "CON",
                               "+2 CON", stat_bonus='{"CON": 2}')
    server._cybernetic_remove("Cyborg", "Rib Cage")
    char = _reload("Cyborg")
    assert char["abilities"]["CON"]["current"] == 2
    assert char["slot_capacity_total"] == 12  # 10 + CON 2


# --- removal that lands a stat below -10 surfaces a death warning -----------

def test_remove_below_threshold_surfaces_death_warning():
    """A stat that took damage while an implant was installed can go below -10
    when the implant's bonus is reversed — removal must surface the death."""
    # EGO -9, plus a +2 implant applied (EGO shows -7). Reversing -> -9? no:
    # start EGO at -9 with the implant already giving +2 so current is -7.
    c = _bare()
    c["abilities"]["EGO"] = {"current": -7, "base": -9}
    c["augmentations"] = {"EGO": {"name": "Ego Damper",
                                  "stat_bonus_applied": {"EGO": 2}}}
    _write_char("cyborg", c)
    out = server._cybernetic_remove("Cyborg", "Ego Damper")
    assert _reload("Cyborg")["abilities"]["EGO"]["current"] == -9
    # -9 is not below -10, so no death here; make a harder case below.


def test_remove_pushes_stat_below_minus_ten_warns():
    c = _bare()
    c["abilities"]["EGO"] = {"current": -9, "base": -12}
    c["augmentations"] = {"EGO": {"name": "Ego Damper",
                                  "stat_bonus_applied": {"EGO": 3}}}
    _write_char("cyborg", c)
    out = server._cybernetic_remove("Cyborg", "Ego Damper")
    assert _reload("Cyborg")["abilities"]["EGO"]["current"] == -12
    assert "WARNING" in out and "EGO" in out


# --- nanomachine destroy path uses the applied delta ------------------------

def test_nanomachine_destroy_reverses_applied_delta():
    """An infection overwriting a capped implant reverses the EFFECTIVE delta,
    not the full requested bonus. Janus Lenses occupies PSY and has no
    stat-changing on_apply, so the only PSY movement is the reversal."""
    c = _bare(PSY=9)
    # implant that was capped at install: requested +3 but only +1 applied
    c["abilities"]["PSY"]["current"] = 10
    c["augmentations"] = {"PSY": {"name": "Mind Spur",
                                  "stat_bonus": {"PSY": 3},
                                  "stat_bonus_applied": {"PSY": 1}}}
    _write_char("cyborg", c)
    # apply a nanomachine infection that occupies PSY (force to skip immunity)
    server.affliction(kind="disease", action="apply",
                      character="Cyborg", disease="Janus Lenses", force=True)
    char = _reload("Cyborg")
    # PSY must return to 9 (reverse the +1 applied), not 7 (reverse the +3)
    assert char["abilities"]["PSY"]["current"] == 9
