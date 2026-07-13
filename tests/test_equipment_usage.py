# tests/test_equipment_usage.py
import server
import item_slots as isl


def _pc(items):
    return {"name": "Petros", "slot_capacity_total": 13, "wounds_slots_used": 0,
            "mystic_gifts": [], "codices": [], "abilities": {"CON": {"current": 3}},
            "inventory": {"carried": list(items)}}


def _handle(server_mod, monkeypatch, char):
    data = {"characters": {"petros": char}}
    monkeypatch.setattr(server_mod, "_load_characters", lambda: (data, None))
    monkeypatch.setattr(server_mod, "_save_single_character", lambda *a, **k: None)
    return data


def test_use_usage_die_depletes_on_one_or_two(monkeypatch):
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8", "usage_max": "Ud8"}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)   # force deplete
    out = server._usage_dispatch(action="use", character="Petros", item="Blowtorch")
    assert "Ud6" in out  # d8 -> d6
    assert char["inventory"]["carried"][0]["usage_die"] == "Ud6"


def test_use_usage_die_survives_on_high_roll(monkeypatch):
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8", "usage_max": "Ud8"}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 7)
    server._usage_dispatch(action="use", character="Petros", item="Blowtorch")
    assert char["inventory"]["carried"][0]["usage_die"] == "Ud8"   # unchanged


def test_use_discrete_decrements(monkeypatch):
    char = _pc([{"name": "Med Kit", "slots": 1, "uses": 3, "uses_max": 3}])
    _handle(server, monkeypatch, char)
    out = server._usage_dispatch(action="use", character="Petros", item="Med Kit")
    assert char["inventory"]["carried"][0]["uses"] == 2
    assert "2" in out


def test_use_discrete_to_zero_removes_and_frees_slot(monkeypatch):
    char = _pc([{"name": "Draught", "slots": 1, "uses": 1, "uses_max": 1}])
    _handle(server, monkeypatch, char)
    out = server._usage_dispatch(action="use", character="Petros", item="Draught")
    assert all(i.get("name") != "Draught" for i in char["inventory"]["carried"])  # removed
    assert "freed" in out.lower() or "consumed" in out.lower()


def test_use_unlimited_is_noop(monkeypatch):
    char = _pc([{"name": "Ansible", "slots": 1}])
    _handle(server, monkeypatch, char)
    out = server._usage_dispatch(action="use", character="Petros", item="Ansible")
    assert "nothing" in out.lower() or "no usage" in out.lower()


def test_use_ammo_alias_on_weapon_still_works(monkeypatch):
    char = _pc([{"name": "Bolts", "slots": 1, "ammo": "Ud20", "ammo_max": "Ud20"}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # deplete
    server._usage_dispatch(action="use", character="Petros", item="Bolts")
    assert char["inventory"]["carried"][0]["ammo"] == "Ud12"  # writes back to ammo alias


def test_lazy_normalize_uses_max(monkeypatch):
    char = _pc([{"name": "Smoke Bomb", "slots": 1, "uses": 1}])  # no uses_max
    _handle(server, monkeypatch, char)
    server._usage_dispatch(action="use", character="Petros", item="Smoke Bomb")
    # consumed (1->0, removed); no crash from missing uses_max
    assert all(i.get("name") != "Smoke Bomb" for i in char["inventory"]["carried"])


def test_lazy_normalize_usage_max(monkeypatch):
    char = _pc([{"name": "Flare", "slots": 1, "usage_die": "Ud6"}])  # no usage_max
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 1)  # force deplete
    server._usage_dispatch(action="use", character="Petros", item="Flare")
    assert char["inventory"]["carried"][0].get("usage_max") == "Ud6"


def test_use_accepts_weapon_alias_param(monkeypatch):
    # The tool exposes both `item` and back-compat `weapon`; dispatch must honor either.
    char = _pc([{"name": "Blowtorch", "slots": 1, "usage_die": "Ud8", "usage_max": "Ud8"}])
    _handle(server, monkeypatch, char)
    monkeypatch.setattr(server.random, "randint", lambda a, b: 2)
    out = server._usage_dispatch(action="use", character="Petros", weapon="Blowtorch")
    assert "Ud6" in out


def test_status_shows_load_and_all_depletables(monkeypatch):
    char = _pc([
        {"name": "Blowtorch", "slots": 1, "usage_die": "Ud8"},
        {"name": "Med Kit", "slots": 1, "uses": 3},
        {"name": "Rope", "slots": 1},
    ])
    data = {"characters": {"petros": char}}
    monkeypatch.setattr(server, "_load_characters", lambda: (data, None))
    out = server._usage_dispatch(action="status")
    assert "LOAD" in out and "Petros" in out
    assert "Blowtorch (Ud8)" in out
    assert "Med Kit (x3)" in out
    assert "Rope" not in out  # non-depletable not listed
    assert 'action="use"' in out   # the exact next call is surfaced (push-discovery)


def test_combat_end_autoroll_stays_ranged_only():
    # A non-ranged usage-die item must NOT be treated as a fired ranged weapon.
    equip = {"name": "Blowtorch", "range": "melee", "usage_die": "Ud8"}
    assert server._usage_applies(equip) is False   # U1 predicate stays ranged+ammo only
