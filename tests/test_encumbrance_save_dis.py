# tests/test_encumbrance_save_dis.py
import server


def _char(encumbered):
    cap = 13
    carried = 14 if encumbered else 5
    return {"name": "Tester", "slot_capacity_total": cap, "wounds_slots_used": 0,
            "mystic_gifts": [], "codices": [],
            "inventory": {"carried": [{"name": "x", "slots": carried}]}}


def test_save_note_only_for_str_dex_con_when_encumbered():
    enc = _char(True)
    assert "DISADVANTAGE" in server._encumbrance_save_note(enc, "CON")
    assert "DISADVANTAGE" in server._encumbrance_save_note(enc, "STR")
    assert "DISADVANTAGE" in server._encumbrance_save_note(enc, "DEX")
    assert server._encumbrance_save_note(enc, "EGO") == ""      # not a phys save
    assert server._encumbrance_save_note(_char(False), "CON") == ""  # not encumbered


def test_check_action_prompt_shows_dis_for_encumbered_pc(monkeypatch):
    enc = _char(True)
    enc["species"] = "Neobloom"  # toxin-susceptible
    data = {"meta": {}, "characters": {"tester": enc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_dispatch(action="check", target="tester", tox_die="d8")
    assert "roll a CON save" in out
    assert "DISADVANTAGE" in out


def test_check_action_prompt_no_dis_for_unencumbered_pc(monkeypatch):
    light = _char(False)
    light["species"] = "Neobloom"
    data = {"meta": {}, "characters": {"tester": light}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_dispatch(action="check", target="tester", tox_die="d8")
    assert "roll a CON save" in out
    assert "DISADVANTAGE" not in out


def test_reroute_prompt_shows_dis_for_encumbered_pc(monkeypatch):
    enc = _char(True)
    enc["species"] = "Neobloom"
    data = {"meta": {}, "characters": {"tester": enc}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_attack_reroute(attacker=None, target="tester", tox_die="d8", attacker_kind="enemy")
    assert "roll CON save" in out
    assert "DISADVANTAGE" in out


def test_reroute_prompt_no_dis_for_unencumbered_pc(monkeypatch):
    light = _char(False)
    light["species"] = "Neobloom"
    data = {"meta": {}, "characters": {"tester": light}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    out = server._toxin_attack_reroute(attacker=None, target="tester", tox_die="d8", attacker_kind="enemy")
    assert "roll CON save" in out
    assert "DISADVANTAGE" not in out
