"""Task 10 Fix Batch 1 — push audit: combat-end, wound-status, codex-mishap
pushes, and usage status formatter migration.

Six findings:
  1. _combat_damage: last enemy dropped to 0 HP → NEXT combat(action="end")
  2. _check_morale_triggers: morale break clears last enemies → NEXT combat(action="end")
  3. _character_update_hp: HP set below 0 → NEXT wound(action="status", character=...)
  4. advance_day: wound daily tick fired → NEXT wound(action="status")
  5. _codex_use: natural-1 MISHAP line → NEXT codex(action="mishap_roll")
  6. _usage_dispatch status: hand-rolled f-string → _pf.push_call identical output

Negative cases: enemy down but others alive → NO end-combat push;
HP set to positive → no wound push; codex output (pre-roll) → no mishap push
(the push only fires at the NAT-1 MISHAP outcome line).
"""
import server
import engine_core
import push_format as _pf


# ============================================================
# Shared helpers (mirroring test_combat_attack.py pattern)
# ============================================================

def _make_enemy(hp=20, av=12, defeated=False, fled=False):
    return {
        "hp": hp,
        "max_hp": hp,
        "av": av,
        "morale": 0,
        "lvl": 2,
        "defeated": defeated,
        "fled": fled,
        "resist_type": "Biological",
        "resistances": {"immune": [], "double": [], "half": [], "minimum": [], "varies": False},
        "incorporeal": False,
        "attack_name": "Slam",
        "attack_damage": "d6",
        "attacks": [],
    }


def _base_combat_isolate(monkeypatch, enemies, party_snapshot=None):
    """Inject minimal mocks for _combat_damage / _check_morale_triggers tests."""
    pc_char = {
        "name": "Roscar",
        "hp": {"current": 23, "max": 23},
        "wound_table": "biological",
        "abilities": {"STR": {"current": 1}, "DEX": {"current": 2}},
        "inventory": {"carried": []},
        "attacks": [],
    }
    chars_data = {"characters": {"roscar": pc_char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (chars_data, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_round_advance", lambda: "")
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)

    snap = party_snapshot or {"roscar": {"hp": 23, "max_hp": 23}}
    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1,
        "enemies": dict(enemies),
        "party_snapshot": snap,
        "morale_broken": False,
        "morale_checked": False,
        "pcs_acted": False,
        "enemies_acted": False,
        "log": [],
    })
    return pc_char, chars_data


# ============================================================
# Finding 1: _combat_damage — last enemy drops to 0 HP
# ============================================================

def test_last_enemy_defeated_pushes_combat_end(monkeypatch):
    """When the single enemy drops to 0 HP (all enemies now defeated), the
    output must include NEXT (end combat): combat(action="end")."""
    enemies = {"Brute (alpha)": _make_enemy(hp=5, av=2)}
    _base_combat_isolate(monkeypatch, enemies)
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    # Force the d20 hit and damage roll
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)
    monkeypatch.setattr(server, "_roll_stat_expr", lambda expr, default=1: 10)
    monkeypatch.setattr(server, "_resolve_attacker_weapon",
                        lambda attacker, weapon=None: {
                            "name": "Fist", "type": "melee", "damage": "d4",
                            "damage_type": "kinetic", "engine_tags": []})

    out = server._combat_damage("Brute (alpha)", 10, "kinetic")

    assert "defeated" in out.lower()
    assert 'combat(action="end")' in out
    assert "NEXT" in out


def test_enemy_down_but_others_alive_no_end_push(monkeypatch):
    """When ONE enemy is dropped but others remain active, NO end-combat push."""
    enemies = {
        "Brute (alpha)": _make_enemy(hp=5, av=2),
        "Brute (beta)": _make_enemy(hp=20, av=5),
    }
    _base_combat_isolate(monkeypatch, enemies)
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_resolve_attacker_weapon",
                        lambda attacker, weapon=None: {
                            "name": "Fist", "type": "melee", "damage": "d4",
                            "damage_type": "kinetic", "engine_tags": []})

    out = server._combat_damage("Brute (alpha)", 10, "kinetic")

    assert "defeated" in out.lower()
    # beta is still alive — must NOT push end combat
    assert 'combat(action="end")' not in out


def test_all_enemies_fled_after_last_defeat_pushes_end(monkeypatch):
    """Enemy defeated + one that already fled = all down → push end."""
    enemies = {
        "Brute (alpha)": _make_enemy(hp=5, av=2),
        "Runner (fled)": _make_enemy(hp=10, fled=True),
    }
    _base_combat_isolate(monkeypatch, enemies)
    monkeypatch.setattr(server, "_check_morale_triggers", lambda: "")
    monkeypatch.setattr(server, "_resolve_attacker_weapon",
                        lambda attacker, weapon=None: {
                            "name": "Fist", "type": "melee", "damage": "d4",
                            "damage_type": "kinetic", "engine_tags": []})

    out = server._combat_damage("Brute (alpha)", 10, "kinetic")

    assert 'combat(action="end")' in out


# ============================================================
# Finding 2: _check_morale_triggers — morale break flees last enemy
# ============================================================

def test_morale_break_with_no_survivors_pushes_combat_end(monkeypatch):
    """When _check_morale_triggers fails morale and all enemies are now fled,
    the result must include NEXT (end combat): combat(action="end")."""
    enemies = {
        "Brute (alpha)": _make_enemy(hp=10, defeated=False, fled=False),
    }
    _base_combat_isolate(monkeypatch, enemies)
    # Force a morale-trigger scenario: 1 enemy, 0 defeated so far — inject
    # the 50%-defeated trigger by marking the enemy defeated count manually.
    # Easiest: just call _check_morale_triggers with a pre-rigged state.
    combat = server.GAME_STATE["active_combat"]
    # Mark 50%+ condition: half-defeated, one alive
    combat["enemies"]["Fodder (dead)"] = _make_enemy(hp=0, defeated=True)
    combat["morale_checked"] = False

    # Force d20=1 (morale fails)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)

    out = server._check_morale_triggers()

    assert out is not None
    assert "FAILED" in out
    assert 'combat(action="end")' in out
    assert "NEXT" in out


def test_morale_break_with_survivors_no_end_push(monkeypatch):
    """Morale breaks but two enemies remain that cannot all flee (they were
    already defeated). Wait — actually when morale breaks ALL remaining flee.
    So this test: morale holds (success) → no end push."""
    enemies = {
        "Brute (alpha)": _make_enemy(hp=10),
        "Fodder (dead)": _make_enemy(hp=0, defeated=True),
    }
    _base_combat_isolate(monkeypatch, enemies)
    combat = server.GAME_STATE["active_combat"]
    combat["morale_checked"] = False

    # Force d20=20 (morale succeeds)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 20)

    out = server._check_morale_triggers()

    assert out is not None
    assert "SUCCESS" in out
    assert 'combat(action="end")' not in out


# ============================================================
# Finding 2b (review batch): forced-morale rout — _combat_morale(force_morale=True)
# ============================================================

def test_forced_morale_rout_clears_field_pushes_combat_end(monkeypatch):
    """When a FORCED morale check fails and every enemy flees (field clear),
    the output must include NEXT (end combat): combat(action=\"end\") — same
    coverage as the auto-trigger path."""
    enemies = {"Brute (alpha)": _make_enemy(hp=10)}
    _base_combat_isolate(monkeypatch, enemies)

    # Force d20=1 -> roll 1 + morale 0 = 1 vs DC 16 -> FAILED, all flee
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)

    out = server._combat_morale(force_morale=True)

    assert "FAILED" in out
    assert 'combat(action="end")' in out
    assert "NEXT" in out


# ============================================================
# Finding 2c (review batch): toxin tick defeats LAST enemy in _check_round_advance
# ============================================================

def test_toxin_tick_defeats_last_enemy_pushes_combat_end(monkeypatch):
    """When the round-advance toxin tick drops the LAST enemy to 0 HP
    (_toxin_tick sets defeated), the round message must carry the
    end-combat push."""
    poisoned = _make_enemy(hp=1)          # any toxin roll (>=1) kills it
    poisoned["toxin_die"] = "d4"
    enemies = {"Venom-bit (alpha)": poisoned}

    pc_char = {
        "name": "Roscar",
        "hp": {"current": 23, "max": 23},
        "inventory": {"carried": []},
        "attacks": [],
    }
    chars_data = {"characters": {"roscar": pc_char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (chars_data, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)

    monkeypatch.setitem(server.GAME_STATE, "active_combat", {
        "round": 1,
        "enemies": dict(enemies),
        "party_snapshot": {"roscar": {"hp": 23, "max_hp": 23}},
        "morale_broken": False,
        "morale_checked": False,
        "pcs_acted": True,       # both sides acted -> round advances
        "enemies_acted": True,
        "initiative": "pcs",
        "log": [],
    })

    out = server._check_round_advance()

    assert out is not None
    assert "defeated by toxin" in out
    assert 'combat(action="end")' in out
    assert "NEXT" in out


# ============================================================
# Finding 3: _character_update_hp — HP set below 0
# ============================================================

def test_hp_below_zero_adds_wound_status_push(monkeypatch):
    """When _character_update_hp sets HP < 0, output must include
    NEXT (check wound): wound(action="status", character="<name>")."""
    char = {"name": "Roscar", "hp": {"current": 5, "max": 23},
            "wounds": [], "wound_table": "biological"}
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)

    out = server._character_update_hp("roscar", -3)

    assert "below 0" in out.lower() or "below zero" in out.lower() or "HP below 0" in out
    assert 'affliction(kind="wound", action="status"' in out
    assert 'character="Roscar"' in out
    assert "NEXT" in out


def test_hp_positive_no_wound_push(monkeypatch):
    """When HP is set to a positive value, NO wound push."""
    char = {"name": "Roscar", "hp": {"current": 5, "max": 23},
            "wounds": [], "wound_table": "biological"}
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)

    out = server._character_update_hp("roscar", 15)

    assert 'affliction(kind="wound", action="status"' not in out
    assert "NEXT" not in out


def test_hp_zero_fires_wound_push(monkeypatch):
    """C-edge: HP set exactly to 0 fires the wound-status push, matching the
    unified 'wound at HP <= 0' rule (engine_core: damage>0 and new_hp<=0).
    0 HP = incapacitated (book), so the manual path's safety-net push must fire."""
    char = {"name": "Roscar", "hp": {"current": 5, "max": 23},
            "wounds": [], "wound_table": "biological"}
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)

    out = server._character_update_hp("roscar", 0)

    assert 'affliction(kind="wound", action="status"' in out
    assert "NEXT" in out
    assert "at or below 0" in out.lower()


def test_hp_one_no_wound_push(monkeypatch):
    """The exact boundary the fix must NOT cross: HP set to 1 (>0) does not
    fire the wound push."""
    char = {"name": "Roscar", "hp": {"current": 5, "max": 23},
            "wounds": [], "wound_table": "biological"}
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)

    out = server._character_update_hp("roscar", 1)

    assert 'affliction(kind="wound", action="status"' not in out
    assert "NEXT" not in out


# ============================================================
# Finding 4: advance_day — wound tick fired
# ============================================================

def test_advance_day_wound_tick_appends_wound_status_push(monkeypatch, tmp_path):
    """When advance_day fires a wound daily tick (tick_lines non-empty), the
    return string must end with NEXT (wound status): wound(action="status")."""
    import wounds as _wnd

    # Patch filesystem reads to avoid real campaign dir
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS - DAY 5\n**Day:** 5\n", encoding="utf-8")

    # Character with a degenerative wound that has a daily_tick
    char_with_wound = {
        "name": "Roscar",
        "hp": {"current": 5, "max": 23},
        "wounds": [{"name": "Cascading Kinesthetics Debilitation",
                    "stat_effects": {"STR": -1},
                    "daily_tick": True,
                    "tick_stat": "STR",
                    "tick_amount": 1}],
    }
    chars_data = {"characters": {"roscar": char_with_wound},
                  "_meta": {"campaign_day": 5}}

    # Fake character meta for day sync
    chars_dir = tmp_path / "characters"
    chars_dir.mkdir()
    import json
    (chars_dir / "_meta.json").write_text(
        json.dumps({"campaign_day": 5}), encoding="utf-8")

    monkeypatch.setattr(server, "_load_characters", lambda: (chars_data, None))
    monkeypatch.setattr(server, "_save_single_character", lambda *a, **k: None)
    monkeypatch.setattr(server, "_load_npc_states",
                        lambda: ({"npcs": {}}, None))
    monkeypatch.setattr(server, "_save_npc_states", lambda *a, **k: None)
    # Patch derived_effects to return a real tick
    monkeypatch.setattr(_wnd, "derived_effects",
                        lambda wounds: {"daily_tick": {"STR": 1},
                                        "drop_items": False, "double_damage": False,
                                        "deaths_door": False, "ko_save_owed": False,
                                        "notes": []})
    monkeypatch.setattr(server, "_apply_ability_damage_from_wound",
                        lambda char, effects: ["  STR -1"])
    monkeypatch.setattr(engine_core, "_apply_ability_damage_from_wound", server._apply_ability_damage_from_wound)
    # No photosynthesis in status
    monkeypatch.setattr(server, "read_file",
                        lambda name: "# CURRENT STATUS - DAY 5\n**Day:** 5\n")
    monkeypatch.setattr(server, "write_file", lambda name, content: True)

    out = server.advance_day(6, "Party rests")

    assert "WOUND DAILY TICK" in out
    assert 'affliction(kind="wound", action="status")' in out
    assert "NEXT" in out


def test_advance_day_no_tick_no_wound_push(monkeypatch, tmp_path):
    """When no wound tick fires, no wound push is appended."""
    monkeypatch.setattr(server, "CAMPAIGN_DIR", tmp_path)
    (tmp_path / "CURRENT_STATUS.md").write_text(
        "# CURRENT STATUS - DAY 5\n**Day:** 5\n", encoding="utf-8")

    chars_dir = tmp_path / "characters"
    chars_dir.mkdir()
    import json
    (chars_dir / "_meta.json").write_text(
        json.dumps({"campaign_day": 5}), encoding="utf-8")

    chars_data = {"characters": {}, "_meta": {"campaign_day": 5}}
    monkeypatch.setattr(server, "_load_characters", lambda: (chars_data, None))
    monkeypatch.setattr(server, "_load_npc_states",
                        lambda: ({"npcs": {}}, None))
    monkeypatch.setattr(server, "_save_npc_states", lambda *a, **k: None)
    monkeypatch.setattr(server, "read_file",
                        lambda name: "# CURRENT STATUS - DAY 5\n**Day:** 5\n")
    monkeypatch.setattr(server, "write_file", lambda name, content: True)

    out = server.advance_day(6, "Party rests")

    assert "WOUND DAILY TICK" not in out
    assert 'affliction(kind="wound", action="status")' not in out


# ============================================================
# Finding 5: _codex_use — natural-1 MISHAP line
# ============================================================

def test_codex_use_mishap_line_has_mishap_roll_push(monkeypatch):
    """_codex_use output must include NEXT (mishap): codex(action="mishap_roll")
    on the Natural-1 MISHAP line."""
    char = {
        "name": "Roscar",
        "can_use_codices": True,
        "abilities": {"INT": {"current": 2}},
        "codices": [{"name": "Kronophage's Binding",
                     "equation": "Temporal Lock",
                     "effect": "Locks target in time for [INT] rounds"}],
    }
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._codex_use("roscar", "Kronophage")

    assert "Natural 1" in out or "MISHAP" in out
    assert 'codex(action="mishap_roll")' in out
    assert "NEXT" in out


def test_codex_use_non_mishap_lines_no_push(monkeypatch):
    """The success and failure outcome lines must NOT carry the mishap push —
    only the Natural-1 MISHAP line gets it. The push should appear exactly once."""
    char = {
        "name": "Roscar",
        "can_use_codices": True,
        "abilities": {"INT": {"current": 2}},
        "codices": [{"name": "Kronophage's Binding",
                     "equation": "Temporal Lock",
                     "effect": "Locks target in time for [INT] rounds"}],
    }
    data = {"characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._codex_use("roscar", "Kronophage")

    # Push appears exactly once (not duplicated on success/failure lines)
    assert out.count('codex(action="mishap_roll")') == 1


# ============================================================
# Finding 6: _usage_dispatch status — push_format migration
# ============================================================

def test_status_push_uses_double_quoted_push_call(monkeypatch):
    """The usage(action="use", ...) call in the status output must be produced
    by push_format (double-quoted) and must match the exact old string for
    apostrophe-free names."""
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6"}
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": []}
    data = {"meta": {}, "characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._usage_dispatch("status", character="roscar")

    # Must contain the correctly formatted call
    assert 'usage(action="use", character="Roscar", item="Railgun")' in out
    # Must NOT use single-quoted values (the old apostrophe-bug form)
    assert "action='use'" not in out


def test_status_push_apostrophe_item_name_renders_in_double_quotes(monkeypatch):
    """An item with an apostrophe in its name must appear inside double quotes."""
    weapon = {"name": "Death's Cradle", "type": "ranged_weapon", "damage": "d8",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6"}
    char = {"name": "Roscar", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": []}
    data = {"meta": {}, "characters": {"roscar": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._usage_dispatch("status", character="roscar")

    # The apostrophe must live inside double quotes, not break the call
    assert 'item="Death\'s Cradle"' in out
    assert "action='use'" not in out


def test_status_push_character_apostrophe_name_renders_in_double_quotes(monkeypatch):
    """A character name with an apostrophe must appear inside double quotes."""
    weapon = {"name": "Railgun", "type": "ranged_weapon", "damage": "d12",
              "range": "ranged", "ammo": "Ud6", "ammo_max": "Ud6"}
    char = {"name": "O'Malley", "hp": {"current": 23, "max": 23},
            "inventory": {"carried": [weapon]},
            "attacks": []}
    data = {"meta": {}, "characters": {"omalley": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._usage_dispatch("status", character="omalley")

    assert 'character="O\'Malley"' in out
    assert "action='use'" not in out


def test_status_output_format_identical_for_plain_names(monkeypatch):
    """Regression: the rendered call string for apostrophe-free names must be
    IDENTICAL to what the old f-string produced (no behavior change)."""
    weapon = {"name": "Blowtorch", "type": "tool", "damage": "d4",
              "ammo": "Ud6", "ammo_max": "Ud6"}
    char = {"name": "Vela", "hp": {"current": 20, "max": 20},
            "inventory": {"carried": [weapon]},
            "attacks": []}
    data = {"meta": {}, "characters": {"vela": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))

    out = server._usage_dispatch("status", character="vela")

    expected_call = 'usage(action="use", character="Vela", item="Blowtorch")'
    assert expected_call in out
