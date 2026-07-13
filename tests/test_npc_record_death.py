# tests/test_npc_record_death.py
"""Tests for npc(action="record_death") — feeds the wired †dead settlement overlay.

NPC-only: writes status=DEAD + death_day to npc_states.json. Does not touch the
PC/follower/mercenary death seams. MCP-decorated funcs called in-process leave
unset Field params as FieldInfo, so all params are passed explicitly.
"""
import server


def _states(monkeypatch, tmp_path):
    f = tmp_path / "npc_states.json"
    monkeypatch.setattr(server, "NPC_STATE_FILE", f)
    return f


def test_record_death_sets_status_and_day(monkeypatch, tmp_path):
    _states(monkeypatch, tmp_path)
    out = server.npc(action="record_death", name="Joss", death_day=91)
    assert "Joss" in out and "91" in out
    data, _ = server._load_npc_states()
    rec = data["npcs"]["joss"]
    assert rec["status"] == "DEAD" and rec["death_day"] == 91
    assert any(h.get("type") == "death" for h in rec["history"])


def test_record_death_creates_record_if_absent(monkeypatch, tmp_path):
    _states(monkeypatch, tmp_path)
    server.npc(action="record_death", name="Nobody Special", death_day=5)
    data, _ = server._load_npc_states()
    assert data["npcs"]["nobody special"]["status"] == "DEAD"


def test_record_death_default_day(monkeypatch, tmp_path):
    _states(monkeypatch, tmp_path)
    monkeypatch.setattr(server, "get_current_day_safe", lambda: 120)
    server.npc(action="record_death", name="Varro", death_day=0)
    data, _ = server._load_npc_states()
    assert data["npcs"]["varro"]["death_day"] == 120


def test_record_death_requires_name(monkeypatch, tmp_path):
    _states(monkeypatch, tmp_path)
    out = server.npc(action="record_death", name=None, death_day=5)
    assert "name" in out.lower()


def test_overlay_surfaces_recorded_death(monkeypatch, tmp_path):
    # End-to-end: a recorded death shows up in _settlement_overlays for a matching name.
    _states(monkeypatch, tmp_path)
    server.npc(action="record_death", name="Scholar Tiberius", death_day=77)
    p = tmp_path / "x.md"
    p.write_text("", encoding="utf-8")
    data = {"name": "X", "npcs": [{"name": "Scholar Tiberius"}]}
    npc_overlay, _ = server._settlement_overlays(p, data)
    assert npc_overlay["Scholar Tiberius"]["status"] == "DEAD"
    assert npc_overlay["Scholar Tiberius"]["day"] == 77


def test_overlay_matches_across_title_forms(monkeypatch, tmp_path):
    # Bug guard: card shows a TITLE-bearing name while the dossier stored a
    # title-stripped one. The identity-normalized fallback must still surface DEAD.
    _states(monkeypatch, tmp_path)
    server.npc(action="record_death", name="Amara Vane", death_day=88)
    p = tmp_path / "x.md"
    p.write_text("", encoding="utf-8")
    data = {"name": "X", "npcs": [{"name": "Matriarch Amara Vane"}]}
    npc_overlay, _ = server._settlement_overlays(p, data)
    assert npc_overlay["Matriarch Amara Vane"]["status"] == "DEAD"
    assert npc_overlay["Matriarch Amara Vane"]["day"] == 88


def test_record_death_no_duplicate_under_title_form(monkeypatch, tmp_path):
    # Recording under the TITLE form when a title-stripped record already exists
    # must update that record, not spawn a second.
    _states(monkeypatch, tmp_path)
    server.npc(action="record_death", name="Amara Vane", death_day=10)
    server.npc(action="record_death", name="Matriarch Amara Vane", death_day=88)
    data, _ = server._load_npc_states()
    amaras = [k for k in data["npcs"] if "amara" in k.lower()]
    assert len(amaras) == 1
    rec = data["npcs"][amaras[0]]
    assert rec["status"] == "DEAD" and rec["death_day"] == 88
    # No history bloat: only ONE death entry despite two record_death calls.
    deaths = [h for h in rec["history"] if h.get("type") == "death"]
    assert len(deaths) == 1
