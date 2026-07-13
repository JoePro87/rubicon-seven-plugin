"""
Behavioral tests for the character XP / level-up system.

Covers the four advancement entry points on the `character` tool:
  - gain_xp
  - level_up                (standard: 3 stats +1, HP roll, XP reset)
  - level_up_proteus        (Cacogen — roll a mutation instead of stats/HP)
  - level_up_bloomboon      (Neobloom — roll a bloomboon instead of stats/HP)

Why behavioral (not existence-only): level-up is irreversible in a save. An
off-by-one on the level, an HP-application bug, or a mishandled XP threshold
permanently corrupts a character sheet. These tests pin the exact numeric
contract of the real implementations in server.py.

Isolation: every test builds a throwaway character in
`server.CAMPAIGN_DIR/characters/` (the temp dir provided by conftest's
autouse `isolate_campaign_dir` fixture). No live sheet is ever touched.
Random rolls (Proteus d100, Bloomboon d20, level_up HP d8) are supplied
explicitly or monkeypatched so assertions are deterministic.
"""

import json

import pytest

import server
import engine_core


# ---------------------------------------------------------------------------
# Fixture helpers — write a real split-file character into the temp campaign
# ---------------------------------------------------------------------------

def _write_char(char_id, char):
    """Persist a single character as a split file (the mode level-up code uses)."""
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta_path = chars_dir / "_meta.json"
    if not meta_path.exists():
        meta_path.write_text(json.dumps({"last_updated": "2026-01-01"}))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _read_char(char_id):
    """Read the persisted character back from disk (proves the save happened)."""
    p = server.CAMPAIGN_DIR / "characters" / f"{char_id}.json"
    return json.loads(p.read_text())


def _base_char(**overrides):
    """A minimal but valid character sheet."""
    char = {
        "name": overrides.pop("name", "Testbloom"),
        "species": overrides.pop("species", "true-kin"),
        "level": 1,
        "xp": {"current": 0, "needed": 1},
        "hp": {"current": 20, "max": 20},
        "abilities": {
            "STR": {"current": 0, "base": 0},
            "DEX": {"current": 1, "base": 1},
            "CON": {"current": 2, "base": 2},
            "INT": {"current": 0, "base": 0},
            "PSY": {"current": 0, "base": 0},
            "EGO": {"current": 1, "base": 1},
        },
    }
    char.update(overrides)
    return char


@pytest.fixture
def tk(tmp_path):
    """A standard true-kin character on disk, returns its char_id."""
    char = _base_char(name="Testkin", species="true-kin")
    _write_char("testkin", char)
    return "testkin"


# Minimal advancement tables. Mutation/bloomboon tables are engine-bundled
# rules-data (read via read_rules_data); redirect RULES_DATA_DIR at the temp
# campaign dir so these controlled tables are what the engine reads.
def _write_tables(monkeypatch):
    monkeypatch.setattr(engine_core, "RULES_DATA_DIR", server.CAMPAIGN_DIR)

    cac = {str(i): {"name": "Acidic Blood",
                    "effect": "Corrosive blood, immune to acid"} for i in range(1, 101)}
    cac["42"] = {"name": "Extra Eyes", "effect": "Cannot be surprised"}
    (server.CAMPAIGN_DIR / "CACOGEN_MUTATIONS.json").write_text(json.dumps(cac))

    bloom = {str(i): {"name": f"Bloom{i}", "effect": f"Effect {i}"} for i in range(1, 21)}
    bloom["7"] = {"name": "Plated Bark", "effect": "Gain +2 base AV"}
    (server.CAMPAIGN_DIR / "NEOBLOOM_BLOOMBOONS.json").write_text(json.dumps(bloom))


# ---------------------------------------------------------------------------
# gain_xp
# ---------------------------------------------------------------------------

def test_gain_xp_accumulates_and_persists(tk):
    out = server._character_gain_xp(tk, 1, "killed a thing")
    assert "0 -> 1" in out
    saved = _read_char(tk)
    assert saved["xp"]["current"] == 1
    assert saved["level"] == 1  # gain_xp NEVER changes level on its own


def test_gain_xp_is_additive_across_calls(tk):
    server._character_gain_xp(tk, 1, "a")
    server._character_gain_xp(tk, 2, "b")
    assert _read_char(tk)["xp"]["current"] == 3


def test_gain_xp_announces_levelup_at_threshold(tk):
    # level 1 needs 1 XP -> reaching it flags LEVEL UP AVAILABLE
    out = server._character_gain_xp(tk, 1, "threshold")
    assert "LEVEL UP AVAILABLE" in out
    assert "Level 2" in out


def test_gain_xp_below_threshold_no_levelup_flag():
    # level 3 needs 3 XP; 2 is not enough
    char = _base_char(name="Slow", species="true-kin")
    char["level"] = 3
    char["xp"] = {"current": 0, "needed": 3}
    _write_char("slow", char)
    out = server._character_gain_xp("slow", 2, "partial")
    assert "LEVEL UP AVAILABLE" not in out
    assert _read_char("slow")["xp"]["current"] == 2


# ---------------------------------------------------------------------------
# level_up (standard advancement)
# ---------------------------------------------------------------------------

def test_level_up_blocked_without_xp(tk):
    # fresh char has 0/1 XP
    out = server._character_level_up(tk, "DEX,CON,EGO", 5)
    assert "Not enough XP" in out
    # nothing changed on disk
    saved = _read_char(tk)
    assert saved["level"] == 1
    assert saved["hp"]["max"] == 20


def test_level_up_applies_level_hp_stats_and_resets_xp(tk):
    server._character_gain_xp(tk, 1, "earned")  # 1/1, eligible
    out = server._character_level_up(tk, "DEX,CON,EGO", 6)

    saved = _read_char(tk)
    # Level: 1 -> 2
    assert saved["level"] == 2
    assert "Level: 1 -> 2" in out
    # HP: max 20 + roll 6 = 26, current set to new max
    assert saved["hp"]["max"] == 26
    assert saved["hp"]["current"] == 26
    # Stats each +1
    assert saved["abilities"]["DEX"]["current"] == 2  # was 1
    assert saved["abilities"]["CON"]["current"] == 3  # was 2
    assert saved["abilities"]["EGO"]["current"] == 2  # was 1
    assert saved["abilities"]["STR"]["current"] == 0  # untouched
    # XP reset to 0 / new level
    assert saved["xp"] == {"current": 0, "needed": 2}


def test_level_up_con_updates_slot_capacity(tk):
    server._character_gain_xp(tk, 1, "earned")
    server._character_level_up(tk, "DEX,CON,EGO", 4)
    saved = _read_char(tk)
    # CON went 2 -> 3, slot capacity = 10 + CON
    assert saved["slot_capacity_bonus"] == 3
    assert saved["slot_capacity_total"] == 13


def test_level_up_requires_exactly_three_stats(tk):
    server._character_gain_xp(tk, 1, "earned")
    out = server._character_level_up(tk, "DEX,CON", 4)
    assert "exactly 3 stats" in out
    assert _read_char(tk)["level"] == 1  # unchanged


def test_level_up_rejects_invalid_stat(tk):
    server._character_gain_xp(tk, 1, "earned")
    out = server._character_level_up(tk, "DEX,CON,LUCK", 4)
    assert "Invalid stat" in out
    assert _read_char(tk)["level"] == 1


def test_level_up_rejects_out_of_range_hp_roll(tk):
    server._character_gain_xp(tk, 1, "earned")
    out = server._character_level_up(tk, "DEX,CON,EGO", 9)
    assert "HP roll must be 1-8" in out
    assert _read_char(tk)["level"] == 1


def test_level_up_rejects_stat_at_max(tk):
    char = _base_char(name="Maxed", species="true-kin")
    char["abilities"]["DEX"] = {"current": 10, "base": 10}
    char["xp"] = {"current": 1, "needed": 1}
    _write_char("maxed", char)
    from fastmcp.exceptions import ToolError as FastToolError  # noqa: F401
    with pytest.raises(Exception) as exc:
        server._character_level_up("maxed", "DEX,CON,EGO", 4)
    assert "maximum" in str(exc.value).lower()
    # level not advanced
    assert _read_char("maxed")["level"] == 1


def test_level_up_is_not_idempotent_after_xp_reset(tk):
    """After one level_up the XP is reset to 0; a second call must be blocked."""
    server._character_gain_xp(tk, 1, "earned")
    server._character_level_up(tk, "DEX,CON,EGO", 4)  # now level 2, xp 0/2
    out2 = server._character_level_up(tk, "DEX,CON,EGO", 4)
    assert "Not enough XP" in out2
    # Only ONE level was gained — no double application
    assert _read_char(tk)["level"] == 2


# ---------------------------------------------------------------------------
# level_up_proteus (Cacogen mutation)
# ---------------------------------------------------------------------------

def test_proteus_rejects_non_cacogen(tk):
    server._character_gain_xp(tk, 1, "earned")
    out = server._character_level_up_proteus(tk)
    assert "not a Cacogen" in out
    assert _read_char(tk)["level"] == 1


def test_proteus_blocked_without_xp(monkeypatch):
    char = _base_char(name="Kessish", species="cacogen")
    _write_char("kessish", char)
    _write_tables(monkeypatch)
    out = server._character_level_up_proteus("kessish")
    assert "Not enough XP" in out
    assert _read_char("kessish")["level"] == 1


def test_proteus_levels_and_adds_mutation_no_stat_or_hp_change(monkeypatch):
    char = _base_char(name="Kessish", species="cacogen")
    char["xp"] = {"current": 1, "needed": 1}
    _write_char("kessish", char)
    _write_tables(monkeypatch)
    monkeypatch.setattr(server.dice, "d100", lambda *a, **k: 42)

    out = server._character_level_up_proteus("kessish")
    saved = _read_char("kessish")

    assert saved["level"] == 2
    assert "Extra Eyes" in out
    # HP and stats unchanged (traded for the mutation)
    assert saved["hp"]["max"] == 20
    assert saved["abilities"]["CON"]["current"] == 2
    # mutation recorded with its roll source
    muts = saved["special_traits"]["mutations"]
    assert any(m["name"] == "Extra Eyes" and m["source"] == "d100=42" for m in muts)
    # XP reset
    assert saved["xp"] == {"current": 0, "needed": 2}


# ---------------------------------------------------------------------------
# level_up_bloomboon (Neobloom power)
# ---------------------------------------------------------------------------

def test_bloomboon_rejects_non_neobloom(tk):
    server._character_gain_xp(tk, 1, "earned")
    out = server._character_level_up_bloomboon(tk)
    assert "not a Neobloom" in out
    assert _read_char(tk)["level"] == 1


def test_bloomboon_blocked_without_xp(monkeypatch):
    char = _base_char(name="Creenashish", species="neobloom")
    _write_char("creenashish", char)
    _write_tables(monkeypatch)
    out = server._character_level_up_bloomboon("creenashish")
    assert "Not enough XP" in out
    assert _read_char("creenashish")["level"] == 1


def test_bloomboon_levels_and_adds_power_no_stat_or_hp_change(monkeypatch):
    char = _base_char(name="Creenashish", species="neobloom")
    char["xp"] = {"current": 1, "needed": 1}
    _write_char("creenashish", char)
    _write_tables(monkeypatch)
    monkeypatch.setattr(server.dice, "d20", lambda *a, **k: 7)

    out = server._character_level_up_bloomboon("creenashish")
    saved = _read_char("creenashish")

    assert saved["level"] == 2
    assert "Plated Bark" in out
    assert saved["hp"]["max"] == 20  # no HP roll
    assert saved["abilities"]["CON"]["current"] == 2  # no stat increase
    booms = saved["bloomboons"]
    assert any(b["name"] == "Plated Bark" and b["source"] == "d20=7" for b in booms)
    assert saved["xp"] == {"current": 0, "needed": 2}


def test_bloomboon_repeat_takes_next_boon_down(monkeypatch):
    """C2 book fix (CH p.049): a repeat roll takes the NEXT boon down,
    never a reroll. Roll 7 owned -> boon #8."""
    char = _base_char(name="Creenashish", species="neobloom")
    char["xp"] = {"current": 1, "needed": 1}
    char["bloomboons"] = [{"name": "Plated Bark", "effect": "Gain +2 base AV",
                           "source": "d20=7"}]
    _write_char("creenashish", char)
    _write_tables(monkeypatch)

    monkeypatch.setattr(server.dice, "d20", lambda *a, **k: 7)

    server._character_level_up_bloomboon("creenashish")
    saved = _read_char("creenashish")
    names = [b["name"] for b in saved["bloomboons"]]
    assert names.count("Plated Bark") == 1  # not duplicated
    assert "Bloom8" in names                # the next boon down


def test_gain_xp_offers_bloomboon_choice_to_neobloom():
    """Book (CH p.049): on level-up a Neobloom MAY roll a Bloomboon instead of the
    standard HP + ability gains. gain_xp must surface BOTH paths at the level-up
    decision point so the choice is never silently skipped."""
    char = _base_char(name="Creenashish", species="neobloom")
    char["xp"] = {"current": 0, "needed": 1}
    _write_char("creenashish", char)
    out = server._character_gain_xp("creenashish", 1, "earned")
    assert "LEVEL UP AVAILABLE" in out
    assert 'action="level_up"' in out            # standard advancement still offered
    assert 'action="level_up_bloomboon"' in out  # AND the bloomboon roll
    assert "choose one" in out.lower()


def test_gain_xp_no_bloomboon_choice_for_non_neobloom(tk):
    """A non-Neobloom level-up offers standard advancement only — no bloomboon push."""
    out = server._character_gain_xp(tk, 1, "earned")
    assert "LEVEL UP AVAILABLE" in out
    assert 'action="level_up"' in out
    assert "level_up_bloomboon" not in out
