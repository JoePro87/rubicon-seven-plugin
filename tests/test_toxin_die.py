import server
import engine_core


def test_enemy_biological_susceptible():
    assert server._toxin_susceptible_enemy({"resist_type": "Biological"}) is True
    assert server._toxin_susceptible_enemy({"resist_type": "Biological / Psychic"}) is True
    assert server._toxin_susceptible_enemy({"resist_type": "Synthetic"}) is False
    assert server._toxin_susceptible_enemy({"resist_type": "Mineral"}) is False


def test_pc_biological_default_true():
    assert server._toxin_susceptible_pc({"species": "True-kin"}) is True
    assert server._toxin_susceptible_pc({"species": "Neobloom"}) is True
    assert server._toxin_susceptible_pc({"species": "Cacogen"}) is True


def test_pc_synth_immune():
    assert server._toxin_susceptible_pc({"species": "Synth", "toxin_immune": True}) is False
    assert server._toxin_susceptible_pc({"species": "Synth"}) is False
    assert server._toxin_susceptible_pc(
        {"species": "?", "physiology": "Synth. Immune to poison/disease."}
    ) is False


def _mk_pc(monkeypatch, key="creenash", **fields):
    """Stage one PC in a fake characters store and patch the loaders."""
    char = {"name": key.capitalize(), "species": "Neobloom",
            "hp": {"current": 20, "max": 20}, **fields}
    data = {"meta": {}, "characters": {key: char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    saved = {}
    monkeypatch.setattr(server, "_save_single_character",
                        lambda k, c, d=None: saved.update({k: c}))
    return char, saved


def test_resolve_enemy(monkeypatch):
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": {"Ooze (alpha)": {"hp": 10, "max_hp": 10, "lvl": 3,
                                                      "resist_type": "Biological"}}})
    h = server._toxin_resolve("Ooze (alpha)")
    assert h["kind"] == "enemy" and h["key"] == "Ooze (alpha)"


def test_resolve_pc(monkeypatch):
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    _mk_pc(monkeypatch)
    h = server._toxin_resolve("creenash")
    assert h["kind"] == "pc" and h["key"] == "creenash"


def test_get_set_toxin_die_pc(monkeypatch):
    char, saved = _mk_pc(monkeypatch)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    assert server._toxin_get(h) == "cured"
    server._toxin_set(h, "d8")
    assert server._toxin_get(h) == "d8"
    assert saved["creenash"]["toxin_die"] == "d8"


def test_get_set_toxin_die_enemy(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": {"Ooze (alpha)": {"hp": 10, "max_hp": 10, "lvl": 3,
                                                      "resist_type": "Biological"}}})
    h = server._toxin_resolve("Ooze (alpha)")
    server._toxin_set(h, "d6")
    assert server._toxin_get(h) == "d6"
    assert server.GAME_STATE["active_combat"]["enemies"]["Ooze (alpha)"]["toxin_die"] == "d6"


def test_save_dc():
    assert server._toxin_save_dc("d6") == 16
    assert server._toxin_save_dc("d8") == 18
    assert server._toxin_save_dc("d20") == 30


def test_enemy_save_uses_level_cap10():
    enemy = {"lvl": 3}
    passed, detail = server._toxin_enemy_save(enemy, "d6", rng=lambda lo, hi: 20)
    assert passed is True and "DC 16" in detail
    passed, _ = server._toxin_enemy_save({"lvl": 99}, "d20", rng=lambda lo, hi: 1)
    assert passed is False


def test_incur_on_fail_escalates(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d6")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    server._toxin_incur(h, "d10", save_passed=False)
    assert server._toxin_get(h) == "d10"


def test_incur_on_fail_smaller_unchanged(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d8")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    server._toxin_incur(h, "d6", save_passed=False)
    assert server._toxin_get(h) == "d8"


def test_incur_on_success_unchanged(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="cured")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    server._toxin_incur(h, "d8", save_passed=True)
    assert server._toxin_get(h) == "cured"


def test_tick_subtracts_hp_no_deplete(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d8")
    char["hp"] = {"current": 20, "max": 20}
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    h = server._toxin_resolve("creenash")
    msg = server._toxin_tick(h, rng=lambda lo, hi: 5)
    assert char["hp"]["current"] == 15
    assert server._toxin_get(h) == "d8"
    assert "5" in msg


def test_tick_depletes_on_low(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d8")
    char["hp"] = {"current": 20, "max": 20}
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    monkeypatch.setattr(server, "_check_death_conditions", lambda c: (False, ""))
    monkeypatch.setattr(engine_core, "_check_death_conditions", server._check_death_conditions)
    h = server._toxin_resolve("creenash")
    server._toxin_tick(h, rng=lambda lo, hi: 2)
    assert char["hp"]["current"] == 18
    assert server._toxin_get(h) == "d6"


def test_tick_enemy_defeat(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": {"Ooze (alpha)": {"hp": 3, "max_hp": 10, "lvl": 2,
                                                      "defeated": False, "fled": False,
                                                      "resist_type": "Biological",
                                                      "toxin_die": "d8"}}, "log": []})
    h = server._toxin_resolve("Ooze (alpha)")
    server._toxin_tick(h, rng=lambda lo, hi: 6)
    e = server.GAME_STATE["active_combat"]["enemies"]["Ooze (alpha)"]
    assert e["hp"] == 0 and e["defeated"] is True


def test_tick_cured_noop(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="cured")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    assert server._toxin_tick(h) is None


def test_cure_step(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d10")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    server._toxin_cure(h, full=False)
    assert server._toxin_get(h) == "d8"


def test_cure_full(monkeypatch):
    char, saved = _mk_pc(monkeypatch, toxin_die="d12")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    h = server._toxin_resolve("creenash")
    server._toxin_cure(h, full=True)
    assert server._toxin_get(h) == "cured"


def test_tool_status_clean(monkeypatch):
    char, _ = _mk_pc(monkeypatch, toxin_die="cured")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_dispatch(action="status", target="creenash")
    assert "clean" in out.lower() or "no toxin" in out.lower()


def test_tool_check_pc_reports_dc(monkeypatch):
    char, _ = _mk_pc(monkeypatch)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_dispatch(action="check", target="creenash", tox_die="d8")
    assert "18" in out and "CON save" in out


def test_tool_check_immune_pc(monkeypatch):
    char, _ = _mk_pc(monkeypatch, species="Synth")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_dispatch(action="check", target="creenash", tox_die="d8")
    assert "immune" in out.lower()


def test_tool_check_enemy_autorolls(monkeypatch):
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat",
                        {"enemies": {"Ooze (alpha)": {"hp": 10, "max_hp": 10, "lvl": 2,
                                                      "defeated": False, "fled": False,
                                                      "resist_type": "Biological"}}, "log": []})
    out = server._toxin_dispatch(action="check", target="Ooze (alpha)", tox_die="d8")
    assert "vs DC 18" in out


def test_tool_resolve_applies_pc_save(monkeypatch):
    char, _ = _mk_pc(monkeypatch, toxin_die="cured")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    server._toxin_dispatch(action="resolve", target="creenash", tox_die="d8", save_total=10)
    h = server._toxin_resolve("creenash")
    assert server._toxin_get(h) == "d8"


def test_tool_cure(monkeypatch):
    char, _ = _mk_pc(monkeypatch, toxin_die="d8")
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    server._toxin_dispatch(action="cure", target="creenash", full=True)
    h = server._toxin_resolve("creenash")
    assert server._toxin_get(h) == "cured"
