"""C29 — the relationship() TOOL store (narrative_relationships.json) is surfaced.

check_canon must inject a stored relationship (status + last-change day + a pull
handle) when BOTH entities are in the Present roster, so an engine-recorded shift
resurfaces without the DM remembering to pull. Only one entity present = no inject.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import server


def _store(monkeypatch, rels):
    monkeypatch.setattr(server, "_load_relationships", lambda: ({"relationships": rels}, None))


def test_both_present_injects_line_with_pull_handle(monkeypatch):
    _store(monkeypatch, {
        "kael|vela": {
            "entities": ["Kael", "Vela"], "status": "allied",
            "last_interaction_day": 129,
            "history": [{"from_status": "wary", "to_status": "allied", "day": 129}],
        }
    })
    out = server._relationship_store_present_lines(["Kael", "Vela"])
    assert len(out) == 1
    section, key, line = out[0]
    assert section == "RELATIONSHIPS"
    assert key == "relstore:kael|vela"
    assert "Kael" in line and "Vela" in line and "allied" in line
    assert "Day 129" in line
    # history present -> pull handle is history
    assert 'relationship(action="history"' in line


def test_only_one_present_no_inject(monkeypatch):
    _store(monkeypatch, {
        "kael|vela": {"entities": ["Kael", "Vela"], "status": "allied",
                      "last_interaction_day": 129, "history": []}
    })
    assert server._relationship_store_present_lines(["Kael", "Quill"]) == []


def test_no_history_uses_get_handle(monkeypatch):
    _store(monkeypatch, {
        "kael|vela": {"entities": ["Kael", "Vela"], "status": "wary",
                      "last_interaction_day": 0, "history": []}
    })
    out = server._relationship_store_present_lines(["Kael", "Vela"])
    assert len(out) == 1
    assert 'relationship(action="get"' in out[0][2]


def test_empty_store_is_silent(monkeypatch):
    _store(monkeypatch, {})
    assert server._relationship_store_present_lines(["Kael", "Vela"]) == []
