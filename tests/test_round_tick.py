"""E1 Task 5: round-cadence conditions tick in _check_round_advance,
through the unified damage path and the death gate.

Follows the test_toxin_combat_integration.py pattern: directly seed
GAME_STATE with pcs_acted/enemies_acted=True and call _check_round_advance.
Character files are written to the temp campaign dir (isolate_campaign_dir
is autouse=True in conftest.py), following the test_death_gate_twinning.py
file-based seeding pattern.
"""
import json
import pytest
import server


# ---------------------------------------------------------------------------
# Minimal character fixtures
# ---------------------------------------------------------------------------

def _creenash():
    return {
        "name": "Creenash",
        "hp": {"current": 19, "max": 23},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 1, "base": 1},
            "DEX": {"current": 6, "base": 4},
            "CON": {"current": 6, "base": 6},
            "INT": {"current": 1, "base": 1},
            "PSY": {"current": 1, "base": 1},
            "EGO": {"current": 5, "base": 5},
        },
        "conditions": [],
    }


def _vela():
    return {
        "name": "Vela",
        "hp": {"current": 24, "max": 24},
        "wound_table": "biological",
        "abilities": {
            "STR": {"current": 2, "base": 2},
            "DEX": {"current": 4, "base": 4},
            "CON": {"current": 3, "base": 3},
            "INT": {"current": 4, "base": 4},
            "PSY": {"current": 3, "base": 3},
            "EGO": {"current": 5, "base": 3},
        },
        "conditions": [],
    }


def _seed(dirpath, creenash_data=None, vela_data=None, day=100):
    """Write minimal character split-sheets into the temp campaign dir."""
    chars_dir = dirpath / "characters"
    chars_dir.mkdir(exist_ok=True, parents=True)
    meta = {"version": 1, "campaign_day": day,
            "supply": {"mode": "abundant", "pool": None, "follower_mouths": 0,
                       "separated": [], "ledger": {"day": day, "consumed": {}}}}
    (chars_dir / "_meta.json").write_text(json.dumps(meta))
    (chars_dir / "creenash.json").write_text(
        json.dumps(creenash_data if creenash_data is not None else _creenash()))
    (chars_dir / "vela.json").write_text(
        json.dumps(vela_data if vela_data is not None else _vela()))


def _seed_combat(monkeypatch, party_snapshot, round_num=1):
    """Inject GAME_STATE with both sides having acted so round advances."""
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": round_num,
        "initiative": "pcs",
        "pcs_acted": True,
        "enemies_acted": True,
        "morale_checked": False,
        "party_snapshot": party_snapshot,
        "enemies": {
            "Raider (scarred)": {
                "hp": 15, "max_hp": 15, "lvl": 2,
                "defeated": False, "fled": False,
                "resist_type": "Biological",
            }
        },
        "log": [],
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_burning_ticks_each_round(isolate_campaign_dir, monkeypatch):
    """Burning (round-cadence d8) ticks when _check_round_advance fires."""
    _seed(isolate_campaign_dir)
    # Apply the Burning condition via the condition tool
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8",
                     note="until extinguished")
    data, _ = server._load_characters()
    _, ch = server._find_character(data, "creenash")
    hp0 = ch["hp"]["current"]

    # party_snapshot keyed by the same name _find_character resolves
    _seed_combat(monkeypatch, party_snapshot={"creenash": {"hp": hp0, "max_hp": 23}})
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 5})

    msg = server._check_round_advance()

    assert msg is not None
    assert "Burning" in msg and "5" in msg
    assert 'affliction(kind="condition", action="clear"' in msg          # the extinguish lever

    # HP must be reduced on disk
    data2, _ = server._load_characters()
    _, ch2 = server._find_character(data2, "creenash")
    assert ch2["hp"]["current"] == hp0 - 5


def test_round_tick_respects_twinning_gate(isolate_campaign_dir, monkeypatch):
    """Burning tick that would kill a Twinned PC is intercepted by the gate."""
    _seed(isolate_campaign_dir)
    # Stamp mutual Twinning
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8")

    # Set Creenash near-death so Burning tick would kill
    data, _ = server._load_characters()
    key, ch = server._find_character(data, "creenash")
    ch["hp"]["current"] = -18
    server._save_single_character(key, ch, data)

    _seed_combat(monkeypatch, party_snapshot={"creenash": {"hp": -18, "max_hp": 23}},
                 round_num=2)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})

    msg = server._check_round_advance()

    assert msg is not None
    assert "TWINNING" in msg and "death prevented" in msg

    data2, _ = server._load_characters()
    _, ch2 = server._find_character(data2, "creenash")
    assert ch2["hp"]["current"] == -19           # clamped at brink
    assert "twinning_pending" in ch2
    assert ch2["twinning_pending"]["window"].startswith("combat:r")


def test_two_round_conditions_first_lethal_breaks(isolate_campaign_dir, monkeypatch):
    """Two round HP conditions, first tick lethal: exactly ONE death banner,
    ONE resurrection menu, the second condition never fires on the corpse."""
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8")
    server.affliction(kind="condition", action="apply", character="creenash", name="Caustic",
                     tick_cadence="round", tick_hp="d6")
    data, _ = server._load_characters()
    key, ch = server._find_character(data, "creenash")
    ch["hp"]["current"] = -15
    server._save_single_character(key, ch, data)

    _seed_combat(monkeypatch, party_snapshot={"creenash": {"hp": -15, "max_hp": 23}})
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})

    msg = server._check_round_advance()

    assert msg.count("!!! FATALITY: HP dropped to -20 or below !!!") == 1
    assert msg.count("p.229") == 1                # ONE resurrection menu
    assert "Caustic" not in msg                   # second tick never fired

    data2, _ = server._load_characters()
    _, ch2 = server._find_character(data2, "creenash")
    assert ch2["hp"]["current"] == -23            # -15 - 8, NOT double-drained to -31


def test_toxin_and_burning_same_round(isolate_campaign_dir, monkeypatch):
    """Toxin Die AND Burning on one PC: both tick in one round_advance and
    both effects persist on disk (no lost update between _toxin_set's save
    and the round-tick's _save_single_character)."""
    _seed(isolate_campaign_dir)
    server.affliction(kind="condition", action="apply", character="creenash", name="Burning",
                     tick_cadence="round", tick_hp="d8")
    data, _ = server._load_characters()
    key, ch = server._find_character(data, "creenash")
    ch["toxin_die"] = "d6"
    hp0 = ch["hp"]["current"]
    server._save_single_character(key, ch, data)

    _seed_combat(monkeypatch, party_snapshot={"creenash": {"hp": hp0, "max_hp": 23}})
    # toxin rolls via dice_chain.roll; 3 not in (1,2) so the die does NOT step
    monkeypatch.setattr(server._dc, "roll", lambda die, rng=None: 3)
    # burning rolls via dice.roll_notation
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 5})

    msg = server._check_round_advance()

    assert "Toxin Die" in msg and "Burning" in msg

    data2, _ = server._load_characters()
    _, ch2 = server._find_character(data2, "creenash")
    assert ch2["hp"]["current"] == hp0 - 3 - 5    # both damages landed on disk
    assert ch2.get("toxin_die") == "d6"           # toxin die persisted (no step)


def test_both_twins_burn_to_death_same_round(isolate_campaign_dir, monkeypatch):
    """Twinned pair BOTH with lethal Burning in one round: the gate pairs
    them (first refused with a pending combat:rN mark, second sunders) -
    BOTH end dead, SUNDERED banner present."""
    _seed(isolate_campaign_dir)
    for me, partner in (("creenash", "Vela"), ("vela", "Creenash")):
        server.affliction(kind="condition", action="apply", character=me, name="Twinning",
                         twin_partner=partner)
        server.affliction(kind="condition", action="apply", character=me, name="Burning",
                         tick_cadence="round", tick_hp="d8")
    data, _ = server._load_characters()
    for nm in ("creenash", "vela"):
        k, c = server._find_character(data, nm)
        c["hp"]["current"] = -15
        server._save_single_character(k, c, data)

    _seed_combat(monkeypatch,
                 party_snapshot={"creenash": {"hp": -15, "max_hp": 23},
                                 "vela": {"hp": -15, "max_hp": 24}},
                 round_num=2)
    monkeypatch.setattr(server.dice, "roll_notation", lambda n: {"total": 8})

    msg = server._check_round_advance()

    assert "SUNDERED" in msg and "BOTH ARE DEAD" in msg

    data2, _ = server._load_characters()
    _, creen2 = server._find_character(data2, "creenash")
    _, vela2 = server._find_character(data2, "vela")
    assert creen2["hp"]["current"] == -20         # re-killed partner snapped to -20
    assert vela2["hp"]["current"] <= -20          # the sundering twin is dead too
    assert "twinning_pending" not in creen2       # pending consumed by the pairing


def test_no_round_tick_without_round_conditions(isolate_campaign_dir, monkeypatch):
    """No CONDITION block in message when no PC has round-cadence conditions."""
    _seed(isolate_campaign_dir)
    _seed_combat(monkeypatch, party_snapshot={"creenash": {"hp": 19, "max_hp": 23}})

    msg = server._check_round_advance()

    assert msg is not None
    # Either no CONDITION mention at all, or no Burning (the specific round tick)
    assert "Burning" not in msg
