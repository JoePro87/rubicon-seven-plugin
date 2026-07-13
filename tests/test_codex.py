"""Hypergeometric codex guards (`_codex_use`, `_codex_mishap_roll`).

Codex use is a DC-15 INT save; a natural 1 sends the reader to the d20
Hypergeometric Mishap table. These tests pin the save DC, the "spent until Long
Rest" lockout, the not-found path, and the full 20-entry mishap table.

Characters are written as split files into the temp campaign dir (conftest
autouse fixture); the mishap roll is monkeypatched for determinism.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server


def _write_char(char_id, char):
    chars_dir = server.CAMPAIGN_DIR / "characters"
    chars_dir.mkdir(parents=True, exist_ok=True)
    meta = chars_dir / "_meta.json"
    if not meta.exists():
        meta.write_text(json.dumps({"last_updated": "2026-01-01"}))
    (chars_dir / f"{char_id}.json").write_text(json.dumps(char))


def _vela(**ov):
    c = {
        "name": "Vela",
        "species": "true-kin",
        "abilities": {"INT": {"current": 2, "base": 2}},
        "codices": [{"name": "Hypergeometric Codex", "equation": "Fold Space",
                     "effect": "Short teleport, power [INT]"}],
        "can_use_codices": True,
    }
    c.update(ov)
    return c


def test_use_reports_dc15_and_mishap_warning():
    _write_char("vela", _vela())
    out = server._codex_use("Vela", "Hypergeometric")
    assert "INT Save DC 15" in out
    assert "Natural 1: MISHAP" in out
    assert "[2]" in out  # [INT] substituted with the character's INT bonus


def test_use_blocked_until_long_rest_after_failure():
    _write_char("vela", _vela(can_use_codices=False))
    out = server._codex_use("Vela", "Hypergeometric")
    assert "cannot use codices until Long Rest" in out


def test_use_codex_not_found():
    _write_char("vela", _vela())
    out = server._codex_use("Vela", "Nonexistent Equation")
    assert "not found" in out.lower()


def test_mishap_table_is_full_d20():
    assert set(server.HYPERGEOMETRIC_MISHAPS) == set(range(1, 21))
    assert all("name" in m and "effect" in m for m in server.HYPERGEOMETRIC_MISHAPS.values())


def test_mishap_roll_returns_rolled_entry(monkeypatch):
    monkeypatch.setattr(server.random, "randint", lambda a, b: 10)
    out = server._codex_mishap_roll()
    assert "Labyrinth Pox" in out and "(rolled 10)" in out   # book p.64 entry 10
