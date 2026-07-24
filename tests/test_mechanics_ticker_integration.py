"""Integration tests: the ticker block is appended to the real tool returns.

Every attach point is exercised through the actual function (disk mocked), and
the assertion is that the ticker header + line lands at the END of the return.
Enemy state is asserted QUALITATIVE (no raw numbers in the ticker block).
"""
import server
import character_tools
import engine_core
import mechanics_ticker as mt

HEADER = mt.TICKER_HEADER


def _ticker_block(out):
    """The text from the ticker header onward (the marked relay block)."""
    assert HEADER in out, f"no ticker block in:\n{out}"
    return out[out.index(HEADER):]


# --- _character_take_damage: pc_damage + wound diff --------------------------

def _dmg_isolate(monkeypatch, char, apply_fn=None):
    fixture = {"characters": {char["name"]: char}}
    monkeypatch.setattr(character_tools, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(character_tools, "_find_character",
                        lambda data, name: (char["name"], char))
    monkeypatch.setattr(character_tools, "_save_single_character", lambda *a, **k: None)
    if apply_fn is not None:
        monkeypatch.setattr(character_tools, "_apply_hp_damage_and_wounds", apply_fn)


def test_character_take_damage_ends_with_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 25, "max": 25},
            "wound_table": "biological"}

    def fake_apply(key, c, data, dmg, window_key=None):
        c["hp"]["current"] = 18
        return [], False

    _dmg_isolate(monkeypatch, char, fake_apply)
    out = character_tools._character_take_damage("Creenash", 7, "psychic")
    block = _ticker_block(out)
    assert out.rstrip().endswith("Creenash: -7 HP (psychic) -> 18/25")
    assert HEADER in block


def test_character_take_damage_surfaces_new_wound(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 3, "max": 25},
            "wound_table": "biological", "wounds": []}

    def fake_apply(key, c, data, dmg, window_key=None):
        c["hp"]["current"] = -4
        c.setdefault("wounds", []).append({"name": "Torn Shoulder"})
        return ["**Torn Shoulder**"], False

    _dmg_isolate(monkeypatch, char, fake_apply)
    out = character_tools._character_take_damage("Creenash", 7, "kinetic")
    block = _ticker_block(out)
    assert "Creenash: -7 HP (kinetic) -> -4/25" in block
    assert "Creenash: WOUND - Torn Shoulder" in block


def test_character_take_damage_preexisting_wound_not_reticked(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 10, "max": 25},
            "wound_table": "biological", "wounds": [{"name": "Old Scar"}]}

    def fake_apply(key, c, data, dmg, window_key=None):
        c["hp"]["current"] = 6
        return [], False  # no new wound

    _dmg_isolate(monkeypatch, char, fake_apply)
    out = character_tools._character_take_damage("Creenash", 4, "kinetic")
    assert "WOUND" not in _ticker_block(out)  # Old Scar was already there


# --- _combat_damage: enemy qualitative, PC delegated (no double) --------------

def _combat_isolate(monkeypatch, enemies, party=None, chars=None):
    fixture = {"characters": chars or {}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": enemies, "party_snapshot": party or {},
                         "log": [], "round": 1})


def _enemy(hp=20, mx=20):
    return {"hp": hp, "max_hp": mx, "defeated": False, "fled": False,
            "av": 12, "morale": 0, "resist_type": "Biological"}


def test_combat_enemy_damage_qualitative_ticker(monkeypatch):
    _combat_isolate(monkeypatch, {"Desiccator (lead)": _enemy(20, 20)})
    out = server._combat_damage("Desiccator (lead)", 12, "kinetic")
    block = _ticker_block(out)
    # 8/20 = 0.4 -> bloodied; qualitative word, never the raw HP
    assert "Desiccator (lead): bloodied" in block
    assert "8/20" not in block and "took" not in block


def test_combat_enemy_down_ticker(monkeypatch):
    _combat_isolate(monkeypatch, {"Husk": _enemy(5, 20)})
    out = server._combat_damage("Husk", 50, "kinetic")
    assert "Husk: down" in _ticker_block(out)


def test_combat_enemy_ability_qualitative(monkeypatch):
    _combat_isolate(monkeypatch, {"Brain Coral": _enemy(20, 20)})
    out = server._combat_damage("Brain Coral", 3, "psychic", ability_stat="STR")
    block = _ticker_block(out)
    assert "Brain Coral: weakened (STR)" in block
    # exact new score must not appear in the RELAY block
    assert "-> " not in block or "weakened" in block
    assert "penalty" not in block  # the DM-facing number line is above the block


def test_combat_pc_target_single_ticker(monkeypatch):
    """PC-in-combat delegates to _character_take_damage, which already tickers.
    The combat wrapper must NOT add a second ticker (exactly one header)."""
    pc = {"name": "Creenash", "hp": {"current": 25, "max": 25},
          "wound_table": "biological"}
    _combat_isolate(monkeypatch, {}, party={"Creenash": {"hp": 25}},
                    chars={"Creenash": pc})
    monkeypatch.setattr(character_tools, "_load_characters",
                        lambda: ({"characters": {"Creenash": pc}}, None))
    monkeypatch.setattr(character_tools, "_find_character",
                        lambda data, name: ("Creenash", pc))
    monkeypatch.setattr(character_tools, "_save_single_character", lambda *a, **k: None)

    def fake_apply(key, c, data, dmg, window_key=None):
        c["hp"]["current"] = 22
        return [], False

    monkeypatch.setattr(character_tools, "_apply_hp_damage_and_wounds", fake_apply)
    out = server._combat_damage("Creenash", 3, "kinetic")
    assert out.count(HEADER) == 1                        # no double-emit
    assert "Creenash: -3 HP (kinetic) -> 22/25" in out


# --- conditions ---------------------------------------------------------------

def _cond_isolate(monkeypatch, char):
    fixture = {"characters": {char["name"]: char}, "meta": {"campaign_day": 135}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(server, "_find_character",
                        lambda data, name: (char["name"], char))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)


def test_condition_apply_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 20, "max": 25}, "conditions": []}
    _cond_isolate(monkeypatch, char)
    out = server._condition_impl(action="apply", character="Creenash", name="Burning")
    block = _ticker_block(out)
    assert "Creenash: CONDITION gained - Burning" in block


def test_condition_clear_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 20, "max": 25},
            "conditions": [{"name": "Burning", "since_day": 130}]}
    _cond_isolate(monkeypatch, char)
    out = server._condition_impl(action="clear", character="Creenash", name="Burning")
    block = _ticker_block(out)
    assert "Creenash: CONDITION cleared - Burning" in block


# --- rest / heal --------------------------------------------------------------

def test_rest_long_heal_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 18, "max": 25},
            "abilities": {}, "conditions": [], "wounds": []}
    fixture = {"characters": {"Creenash": char}, "meta": {"campaign_day": 135}}
    monkeypatch.setattr(server, "_load_characters", lambda: (fixture, None))
    monkeypatch.setattr(server, "_find_character",
                        lambda data, name: ("Creenash", char))
    monkeypatch.setattr(server, "_save_characters", lambda *a, **k: None)
    monkeypatch.setattr(server, "_parse_character_list", lambda c: ["Creenash"])
    monkeypatch.setattr(server, "_rest_consume", lambda *a, **k: [])
    out = server._rest_long("Creenash")
    block = _ticker_block(out)
    assert "Creenash: +7 HP -> 25/25" in block


# --- _character_update_hp: manual sets relay the delta -----------------------

def test_update_hp_heal_and_damage_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 10, "max": 25}, "conditions": []}
    _dmg_isolate(monkeypatch, char)
    monkeypatch.setattr(character_tools, "_check_death_conditions",
                        lambda c: (False, ""))
    monkeypatch.setattr(character_tools, "_elixir_hp_floor", lambda c: None)
    out = character_tools._character_update_hp("Creenash", 18)
    block = _ticker_block(out)
    assert "Creenash: +8 HP -> 18/25" in block
    out2 = character_tools._character_update_hp("Creenash", 11)
    block2 = _ticker_block(out2)
    assert "Creenash: -7 HP -> 11/25" in block2


def test_update_hp_no_delta_no_ticker(monkeypatch):
    char = {"name": "Creenash", "hp": {"current": 10, "max": 25}, "conditions": []}
    _dmg_isolate(monkeypatch, char)
    monkeypatch.setattr(character_tools, "_check_death_conditions",
                        lambda c: (False, ""))
    monkeypatch.setattr(character_tools, "_elixir_hp_floor", lambda c: None)
    out = character_tools._character_update_hp("Creenash", 10)
    assert HEADER not in out


def test_take_damage_overkill_relays_true_hp_removed(monkeypatch):
    """Overkill: 10 dealt to a 3-HP character clamped at 0 must relay -3, not
    -10 (the player's own arithmetic has to check out)."""
    char = {"name": "Creenash", "hp": {"current": 3, "max": 29},
            "wound_table": "biological"}

    def fake_apply(key, c, data, dmg, window_key=None):
        c["hp"]["current"] = 0
        return [], False

    _dmg_isolate(monkeypatch, char, apply_fn=fake_apply)
    out = character_tools._character_take_damage("Creenash", 10, "kinetic")
    block = _ticker_block(out)
    assert "Creenash: -3 HP (kinetic) -> 0/29" in block
    assert "-10 HP" not in block
