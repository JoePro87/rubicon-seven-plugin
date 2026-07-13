from pathlib import Path

import server

FIXTURE = [
    {"id": "creature-alzabo", "keywords": ["Alzabo", "Mocking Bear"],
     "stats": {"type": "Biological", "level": 8, "hp": 36, "av": 15, "morale": "+9",
               "attacks": [{"name": "Claw", "damage": "d8"}], "special": ["Mimics voices."]}},
]

def test_get_bestiary_entry_by_keyword(monkeypatch):
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": FIXTURE})
    e = server._get_bestiary_entry("Alzabo")
    assert e is not None and e["stats"]["level"] == 8

def test_get_bestiary_entry_case_and_partial(monkeypatch):
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": FIXTURE})
    assert server._get_bestiary_entry("mocking bear")["stats"]["av"] == 15

def test_get_bestiary_entry_missing(monkeypatch):
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": FIXTURE})
    assert server._get_bestiary_entry("Dragon") is None

def test_lookup_reads_from_json_not_deprecated(monkeypatch):
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": FIXTURE})
    # Fail loudly if the deprecated markdown is consulted
    monkeypatch.setattr(server, "read_file", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read deprecated file")))
    out = server._lookup_creature_stats("Alzabo")
    assert "ALZABO" in out  # name is uppercased in header
    assert "8" in out and "15" in out  # level and av from JSON
    assert "not found" not in out.lower()

def test_lookup_missing_creature_ascii_only(monkeypatch):
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": FIXTURE})
    out = server._lookup_creature_stats("Nonexistent")
    assert "not found" in out.lower()
    assert out.isascii()  # no cp1252 mojibake

def test_combat_init_carries_type_and_resistances(monkeypatch):
    fungal = [{"id": "creature-viridian-ooze", "keywords": ["Viridian Ooze"],
               "stats": {"type": "Fungal", "level": 4, "hp": 16, "av": 9, "morale": "+8",
                         "attacks": [{"name": "Engulf", "damage": "d3"}], "special": []}}]
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": fungal})
    monkeypatch.setattr(server, "_load_characters", lambda: ({"characters": {}}, None))
    monkeypatch.setattr(server, "_save_game_state", lambda *a, **k: None)
    monkeypatch.setitem(server.GAME_STATE, "active_combat", None)
    server._combat_init(["Viridian Ooze"])
    enemy = next(iter(server.GAME_STATE["active_combat"]["enemies"].values()))
    assert enemy["hp"] == 16 and enemy["av"] == 9 and enemy["lvl"] == 4 and enemy["morale"] == 8
    assert enemy["resist_type"] == "Fungal"
    assert "kinetic" in enemy["resistances"]["half"]


def test_no_code_path_reads_deprecated_topaz():
    src = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    assert "TOPAZ_BESTIARY_v2.md" not in src, "deprecated bestiary still referenced in server.py"


def test_lookup_surfaces_structured_combat_flags(monkeypatch):
    fix = [{"id": "creature-test-flags", "keywords": ["Test Flags"],
            "stats": {"type": "Synthetic", "level": 6, "hp": 24, "av": 16,
                      "mystic_gift_immune": True, "ranged_immune": True, "mimic": True,
                      "combat_note": "Custom tactical note here.", "special": []}}]
    monkeypatch.setattr(server.rulebook_system, "_cache", {"bestiary": fix})
    out = server._lookup_creature_stats("Test Flags")
    assert "MYSTIC GIFTS DO NOT FUNCTION" in out
    assert "RANGED-IMMUNE" in out
    assert "MIMIC" in out
    assert "Custom tactical note here." in out
